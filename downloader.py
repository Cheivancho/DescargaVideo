"""Descarga con yt-dlp: trabajos, progreso, cancelación, pausa y cola de ítems."""
import copy
import logging
import os
import re
import shutil
import time
import traceback
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass

import yt_dlp

from convert import Converter
from formats import (
    AUDIO_FORMATS,
    COOKIE_BROWSERS,
    audio_extras,
    audio_template,
    build_format_selector,
    final_ext,
    trim_options,
    variant_tag,
    video_extras,
    video_template,
)
from util import fmt_eta, fmt_speed, short_title

log = logging.getLogger("descargador")


INFO_MAX_AGE = 20 * 60  # segundos: pasado este tiempo las URLs de stream del análisis pueden haber caducado


def find_js_runtimes() -> dict:
    """Runtime de JavaScript para los desafíos de YouTube (EJS). {} si no hay ninguno instalado."""
    for name, exe in (("deno", "deno"), ("node", "node"), ("bun", "bun"), ("quickjs", "qjs")):
        path = shutil.which(exe)
        if path:
            return {name: {"path": path}}
    return {}


_YT_LINK = re.compile(r"^https?://(?:(?:www|m|music)\.)?(?:youtube\.com|youtu\.be)/\S+$", re.I)


def youtube_link(text: str) -> str | None:
    """Primer enlace de YouTube del texto (p. ej. del portapapeles), o None."""
    text = (text or "").strip()
    line = text.splitlines()[0].strip() if text else ""
    return line if _YT_LINK.match(line) else None


def video_list_info(url: str) -> tuple[bool, bool]:
    """(tiene_video, tiene_lista) para enlaces de YouTube, p. ej. watch?v=X&list=Y -> (True, True)."""
    try:
        u = urllib.parse.urlparse(url.strip())
    except ValueError:
        return False, False
    host = (u.hostname or "").lower()
    q = urllib.parse.parse_qs(u.query)
    if host == "youtu.be":
        return bool(u.path.strip("/")), bool(q.get("list"))
    if host == "youtube.com" or host.endswith(".youtube.com"):
        return bool(q.get("v")), bool(q.get("list"))
    return False, False


def has_video_and_list(url: str) -> bool:
    v, lst = video_list_info(url)
    return v and lst


def diagnose_formats(heights: list, warning: str | None, has_js: bool) -> str | None:
    """Mensaje útil cuando el análisis devuelve pocas resoluciones (o ninguna); None si todo parece normal."""
    if heights and len(heights) > 2 and max(heights) > 360:
        return None
    parts = ["Se encontraron muy pocas resoluciones." if heights else "No se encontraron resoluciones."]
    if not has_js:
        parts.append("No hay un motor JavaScript (Deno): YouTube oculta formatos sin él. "
                     "Coloca deno.exe junto a la app (ver README).")
    if warning:
        parts.append("Aviso de yt-dlp: " + warning.strip()[:200])
    parts.append("Prueba otro video, actualiza el motor (Ayuda) o inicia sesión con cookies del navegador.")
    return " ".join(parts)


class YtLogger:
    """Logger para yt-dlp: escribe en el log y recuerda la última advertencia."""

    def __init__(self) -> None:
        self.last_warning: str | None = None

    def debug(self, msg: str) -> None:
        (log.debug if msg.startswith("[debug] ") else log.info)(msg)

    def info(self, msg: str) -> None:
        log.info(msg)

    def warning(self, msg: str) -> None:
        log.warning(msg)
        self.last_warning = msg

    def error(self, msg: str) -> None:
        log.error(msg)


class ProgressTracker:
    """Progreso global monótono de una descarga: trabajos × videos de la lista × pistas (video, audio)."""

    VIDEO_WEIGHT = 0.85  # la pista de video pesa más que la de audio

    def __init__(self, n_jobs: int) -> None:
        self.n_jobs = max(1, n_jobs)
        self.last = 0.0
        self.start_job(1, "")

    def start_job(self, idx: int, label: str) -> None:
        self.job, self.label = idx, label
        self.entry, self.n_entries = 0, 1
        self.files_done, self.weights = 0, None
        self.last = max(self.last, (idx - 1) * 100 / self.n_jobs)

    def update(self, d: dict) -> tuple[float, str]:
        info = d.get("info_dict") or {}
        pidx = info.get("playlist_index") or 1
        self.n_entries = info.get("n_entries") or info.get("playlist_count") or self.n_entries
        if pidx != self.entry:
            self.entry, self.files_done, self.weights = pidx, 0, None
        if self.weights is None:
            video_only = info.get("vcodec") not in (None, "none") and info.get("acodec") in (None, "none")
            self.weights = [self.VIDEO_WEIGHT, 1 - self.VIDEO_WEIGHT] if video_only else [1.0]
        w = self.weights
        if d.get("status") == "finished":
            self.files_done = min(self.files_done + 1, len(w))
            frac = sum(w[:self.files_done])
            text_tail = "procesando…" if self.files_done >= len(w) else ""  # si falta la pista de audio, sigue
        else:
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            f = min((d.get("downloaded_bytes") or 0) / total, 1.0) if total else 0.0
            cur = w[self.files_done] if self.files_done < len(w) else 0
            frac = sum(w[:self.files_done]) + cur * f
            eta = ("ETA " + fmt_eta(d.get("eta"))) if d.get("eta") is not None else ""
            text_tail = " · ".join(x for x in (fmt_speed(d.get("speed")), eta) if x)
        n = max(self.n_entries, 1)
        pct = ((self.job - 1) + ((self.entry - 1) + min(frac, 1.0)) / n) / self.n_jobs * 100
        self.last = max(self.last, min(pct, 100.0))
        parts = [f"[{self.job}/{self.n_jobs}] {self.label}"]
        if n > 1:
            parts.append(f"video {self.entry} de {n}")
        elif len(w) > 1:
            parts.append("audio" if self.files_done >= 1 else "video")
        if text_tail:
            parts.append(text_tail)
        return self.last, " · ".join(parts)


@dataclass
class Job:
    """Un trabajo de yt-dlp: una resolución (o el audio) de un ítem de descarga."""
    item: dict
    label: str
    opts: dict
    ext: str  # extensión final del archivo (tras convertir)
    spec: dict


class DownloadPaused(yt_dlp.utils.DownloadCancelled):
    """Se lanza desde el hook de progreso para detener la descarga conservando los .part (Pausar)."""


def friendly_error(msg: str, browser: str = "") -> str:
    """Traduce los errores más comunes de yt-dlp a un mensaje comprensible; el resto se deja tal cual."""
    m = re.sub(r"^(?:ERROR:\s*)+", "", (msg or "").strip())
    low = m.lower()
    if browser and browser != "Ninguno" and ("dpapi" in low or "decrypt" in low or ("cookie" in low and any(
            k in low for k in ("could not copy", "database", "permission", "locked", "could not find",
                               "unable to read", "failed to")))):
        return (f"No se pudieron leer las cookies de {browser}. Chrome y Edge recientes bloquean el acceso (cierra el "
                "navegador por completo) o las cifran; Firefox suele ser lo más fiable. Prueba con otro navegador o "
                "con «Ninguno».")
    if "sign in to confirm" in low or "not a bot" in low:
        return ("YouTube pide verificar que no eres un robot. Prueba eligiendo las cookies de un navegador donde "
                "hayas iniciado sesión (pestaña Extras).")
    if any(k in low for k in ("private video", "video unavailable", "this video is not available")):
        return "El video no está disponible (privado, eliminado o bloqueado en tu región)."
    if any(k in low for k in ("getaddrinfo failed", "unable to download webpage", "timed out", "connection reset",
                              "network is unreachable", "failed to resolve")):
        return "No hay conexión con YouTube. Revisa tu internet e inténtalo de nuevo."
    return m


class Downloader:
    """Estado y lógica de una sesión de descarga. La interfaz lo maneja con 'cancel', 'paused' y recibe
    los eventos por 'emit' (tuplas ("progress", pct, texto), ("status", texto), ("done", texto, ok))."""

    def __init__(self, emit: Callable[[tuple], None], js_runtimes: dict | None = None) -> None:
        self.emit = emit
        self.js_runtimes = js_runtimes or {}
        self.cookie_browser = COOKIE_BROWSERS[0]
        self.ytlog = YtLogger()
        self.cancel = False
        self.paused = False
        self.tracker = None
        self.skipped = []
        self.failed_items = []  # ítems con algún trabajo fallido (la cola los conserva para reintentar)
        self.cur_spec = {}
        self.last_error = ""
        self.converter = Converter(lambda: self.cancel, emit, lambda: self.paused)

    def add_error(self, text: str) -> None:
        """Acumula el detalle de cada fallo (no solo el último) para 'Copiar error'."""
        self.last_error = f"{self.last_error}\n\n{text}" if self.last_error else text

    def _post_video(self, path: str) -> None:
        self.converter.post_video(path, self.cur_spec)

    def _post_audio(self, path: str) -> None:
        self.converter.post_audio(path, self.cur_spec)

    def hook(self, d: dict) -> None:
        if self.cancel:
            raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario")
        if self.paused:
            raise DownloadPaused("Pausado")
        if self.tracker:
            pct, text = self.tracker.update(d)
            self.emit(("progress", pct, text))

    def is_finished(self, path: str, ext: str) -> bool:
        """¿El archivo ya está en su formato final? En MP4 el intermedio tiene el mismo nombre que el resultado,
        así que se comprueba el códec: un MP4 sin convertir (conversión cancelada o fallida) no cuenta."""
        kind = self.cur_spec.get("kind")
        if ext != ".mp4" or kind not in ("h264", "h264_gpu", "h265", "h265_gpu"):
            return True
        codecs = self.converter.probe_codecs(path)
        if codecs is None:
            return True  # no se pudo inspeccionar: se conserva el comportamiento de saltar
        vid, aud = codecs
        want = "hevc" if kind.startswith("h265") else "h264"
        return vid == want and (not aud or aud == "aac")

    def make_skip_filter(self, holder: dict, ext: str) -> Callable:
        """match_filter de yt-dlp: salta lo que ya existe con su nombre final (extensión tras convertir)."""
        def match(info_dict, *, incomplete=False):
            if incomplete or holder.get("ydl") is None:
                return None
            try:
                final = os.path.splitext(holder["ydl"].prepare_filename(info_dict))[0] + ext
            except Exception:  # noqa: BLE001
                return None
            if os.path.isfile(final) and self.is_finished(final, ext):
                name = os.path.basename(final)
                self.skipped.append(name)
                self.emit(("status", f"Ya existía: {name}"))
                return f"ya existía: {name}"
            return None
        return match

    def run_job(self, opts: dict, url: str, info: dict | None, analyzed_at: float, ext: str) -> None:
        """Ejecuta un trabajo; si se pausa, espera y lo reanuda (yt-dlp continúa desde los .part)."""
        while True:
            try:
                self.run_job_once(opts, url, info, analyzed_at, ext)
                return
            except DownloadPaused:
                self.wait_if_paused()

    def run_job_once(self, opts: dict, url: str, info: dict | None, analyzed_at: float, ext: str) -> None:
        holder = {}
        opts = {**opts, "match_filter": self.make_skip_filter(holder, ext)}
        fresh = info is not None and (time.time() - analyzed_at) < INFO_MAX_AGE
        with yt_dlp.YoutubeDL(opts) as ydl:
            holder["ydl"] = ydl
            if fresh:
                try:  # reutiliza el análisis: evita re-extraer el video por cada resolución
                    ydl.process_ie_result(copy.deepcopy(info), download=True)
                    return
                except yt_dlp.utils.DownloadCancelled:
                    raise
                except Exception:  # noqa: BLE001
                    if self.cancel:  # yt-dlp envuelve la cancelación de un post-hook en otro error
                        raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario") from None
                    log.warning("No se pudo reutilizar el análisis; se vuelve a extraer", exc_info=True)
            ydl.download([url])

    def build_jobs(self, item: dict) -> list[Job]:
        """Convierte un ítem (URL + spec) en trabajos de yt-dlp: uno por resolución y uno de audio."""
        spec, pl, out = item["spec"], item["is_playlist"], item["spec"]["out_dir"]
        ext = final_ext(spec["kind"])
        base = {**self.ydl_base(), "progress_hooks": [self.hook], "ignoreerrors": False,
                "noplaylist": not pl, "continuedl": True}
        jobs = []
        tag, trim = variant_tag(spec), trim_options(spec.get("trim"))
        for h in spec["heights"]:
            sel = build_format_selector(h, pl, spec.get("fps"), bool(item.get("vertical")))
            opts = {**base, "post_hooks": [self._post_video], "format": sel,
                    "merge_output_format": "mp4", "outtmpl": os.path.join(out, video_template(h, pl, tag))}
            opts.update(trim)
            opts.update(video_extras(spec, ext))
            jobs.append(Job(item, f"{h}p", opts, ext, spec))
        if spec["audio"]:
            codec, aext, has_q = AUDIO_FORMATS[spec["audio_fmt"]]
            opts = {**base, "post_hooks": [self._post_audio], "format": "bestaudio/best",
                    "outtmpl": os.path.join(out, audio_template(pl, tag))}
            opts.update(trim)
            opts.update(audio_extras(spec))
            label = spec["audio_fmt"] + (f" {spec['audio_q']}" if has_q else "")
            jobs.append(Job(item, label, opts, aext, spec))
        return jobs

    def run(self, items: list[dict]) -> None:
        jobs = [j for it in items for j in self.build_jobs(it)]
        self.tracker = ProgressTracker(len(jobs))
        self.skipped = []
        self.failed_items = []
        failed = []
        outs = sorted({it["spec"]["out_dir"] for it in items})
        for o in outs:
            self.converter.cleanup_orphans(o)
        url = items[0]["url"] if items else ""
        try:
            for i, job in enumerate(jobs, 1):
                if self.cancel:
                    raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario")
                self.wait_if_paused()
                self.cur_spec = job.spec
                label = job.label if len(items) == 1 else f"{short_title(job.item.get('title'))} · {job.label}"
                self.tracker.start_job(i, label)
                note = " ".join(job.spec.get("notes") or []) if i == 1 else ""
                self.emit(("progress", self.tracker.last,
                            f"[{i}/{len(jobs)}] Iniciando {label}…" + (f"  ({note})" if note else "")))
                try:
                    self.run_job(job.opts, job.item["url"], job.item["info"], job.item["analyzed_at"], job.ext)
                except yt_dlp.utils.DownloadCancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    if self.cancel:
                        raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario") from None
                    log.exception("Falló el trabajo %s de %s", label, job.item["url"])
                    self.add_error(f"Trabajo {label} de {job.item['url']}\n{traceback.format_exc()}")
                    failed.append(f"{label}: {friendly_error(str(e), self.cookie_browser)[:200]}")
                    if not any(job.item is f for f in self.failed_items):
                        self.failed_items.append(job.item)
            head = "⚠ Descarga terminada con errores en: " if failed else "✔ Descarga completada en: "
            msg = head + ", ".join(outs)
            if self.skipped:
                msg += "\nYa existían: " + ", ".join(self.skipped)
            if failed:
                msg += "\nFallaron: " + "; ".join(failed)
            self.emit(("done", msg, not failed))
        except yt_dlp.utils.DownloadCancelled:
            self.emit(("done", "Descarga cancelada.", False))
        except Exception as e:  # noqa: BLE001
            log.exception("Error en la descarga")
            self.add_error(f"Descarga de {url}\n{traceback.format_exc()}")
            self.emit(("done", f"Error: {friendly_error(str(e), self.cookie_browser)}", False))
        finally:
            self.tracker = None

    def wait_if_paused(self) -> None:
        if not self.paused:
            return
        self.emit(("status", "⏸ Pausado: los archivos parciales se conservan. Pulsa Reanudar."))
        while self.paused and not self.cancel:
            time.sleep(0.2)
        if self.cancel:
            raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario")
        self.emit(("status", "Reanudando…"))

    def ydl_base(self) -> dict:
        opts = {"quiet": True, "noprogress": True, "logger": self.ytlog}
        if self.cookie_browser != COOKIE_BROWSERS[0]:
            opts["cookiesfrombrowser"] = (self.cookie_browser.lower(),)
        if self.js_runtimes:
            opts["js_runtimes"] = self.js_runtimes
        return opts
