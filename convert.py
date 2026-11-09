"""Conversión con ffmpeg: formatos de salida, escala, miniaturas, y detección de encoders por GPU."""
import glob
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Callable

from yt_dlp.utils import DownloadCancelled

import updater
from formats import (
    _AAC,
    AUDIO_FORMATS,
    GPU_FALLBACK,
    GPU_TABLE,
    H264_CPU,
    INTRA_KINDS,
    RECODE_SPECS,
    build_video_filter,
)

log = logging.getLogger("descargador")


def _ffmpeg_signature() -> str:
    """Identifica el ffmpeg en uso (ruta, tamaño y fecha) para saber si el resultado cacheado sigue valiendo."""
    p = shutil.which("ffmpeg")
    try:
        st = os.stat(p)
        return f"{p}|{st.st_size}|{int(st.st_mtime)}"
    except (OSError, TypeError):
        return ""


def ffmpeg_encoder_names() -> set[str]:
    """Nombres de encoders de video que ffmpeg dice tener ('ffmpeg -encoders')."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, timeout=20, text=True,
                             encoding="utf-8", errors="replace",
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return set(re.findall(r"^\s*V\S*\s+(\w+)", out, re.M))


def probe_encoder(args: list[str]) -> bool:
    """¿Funciona de verdad este encoder? Codifica 1 segundo de video negro a ninguna parte."""
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=black:s=640x360:r=25:d=1",
           *args, "-f", "null", "-"]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=30, text=True, encoding="utf-8", errors="replace",
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.TimeoutExpired):
        return False
    if r.returncode != 0:
        log.info("Encoder de prueba no disponible (%s): %s", args[1], (r.stderr or "").strip()[-200:])
    return r.returncode == 0


def cached_gpu() -> dict:
    """Resultado de la última detección si corresponde al ffmpeg actual; {} si no hay (no ejecuta nada)."""
    st = updater.load_state().get("gpu")
    if isinstance(st, dict) and st.get("sig") and st.get("sig") == _ffmpeg_signature():
        return {k: st[k] for k in GPU_TABLE if isinstance(st.get(k), str)}
    return {}


def detect_gpu_encoders(force: bool = False) -> dict:
    """{'h264_gpu': 'h264_nvenc', ...} solo con los encoders que pasan la prueba. Cachea el resultado."""
    if not force:
        st = updater.load_state().get("gpu")
        if isinstance(st, dict) and st.get("sig") == _ffmpeg_signature() and all(k in st for k in GPU_TABLE):
            return cached_gpu()
    names = ffmpeg_encoder_names()
    result = {}
    for kind, options in GPU_TABLE.items():
        enc = next((e for e, args in options if e in names and probe_encoder(args)), None)
        if enc:
            result[kind] = enc
    updater.update_state(gpu={"sig": _ffmpeg_signature(), **{k: result.get(k) for k in GPU_TABLE}})
    return result


class Converter:
    """Ejecuta ffmpeg de forma cancelable. 'emit' recibe los mensajes de estado para la interfaz."""

    def __init__(self, is_cancelled: Callable[[], bool], emit: Callable[[tuple], None]) -> None:
        self.is_cancelled = is_cancelled
        self.emit = emit
        self.proc = None  # proceso de ffmpeg en curso

    def kill(self, proc: subprocess.Popen) -> None:
        """Termina ffmpeg; si no responde en unos segundos, lo mata."""
        try:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except OSError:
            pass

    @staticmethod
    def remove_quietly(path: str) -> None:
        for _ in range(10):  # Windows puede tardar un instante en soltar el archivo
            try:
                if os.path.exists(path):
                    os.remove(path)
                return
            except OSError:
                time.sleep(0.3)

    def run_ffmpeg(self, cmd: list[str], dest: str) -> tuple[bool, str]:
        """Ejecuta ffmpeg de forma cancelable. Devuelve (ok, stderr). Si se cancela: lo detiene, borra
        'dest' (archivo parcial) y lanza DownloadCancelled; el archivo de entrada no se toca."""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace", creationflags=flags)
        except OSError as e:
            log.exception("No se pudo lanzar ffmpeg")
            return False, str(e)
        self.proc = proc
        err = ""
        try:
            while True:
                try:
                    _, err = proc.communicate(timeout=0.3)
                    break
                except subprocess.TimeoutExpired:
                    if self.is_cancelled():
                        self.kill(proc)
                        self.remove_quietly(dest)
                        raise DownloadCancelled("Cancelado durante la conversión") from None
        finally:
            self.proc = None
        if proc.returncode != 0:
            log.error("ffmpeg falló: %s", (err or "").strip()[-500:])
            self.remove_quietly(dest)
            return False, err or ""
        return True, ""

    @staticmethod
    def probe_codecs(path: str) -> tuple[str | None, str | None] | None:
        """(códec de video, códec de audio) según 'ffmpeg -i'; None si no se pudo inspeccionar."""
        try:
            info = subprocess.run(["ffmpeg", "-hide_banner", "-i", path], capture_output=True, timeout=30,
                                  text=True, encoding="utf-8", errors="replace",
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stderr
        except (OSError, subprocess.TimeoutExpired):
            log.warning("No se pudo inspeccionar %s con ffmpeg", path, exc_info=True)
            return None
        vid = re.search(r"Stream #.*Video: (\w+)", info)
        aud = re.search(r"Stream #.*Audio: (\w+)", info)
        return (vid.group(1) if vid else None), (aud.group(1) if aud else None)

    def post_video(self, path: str, spec: dict) -> None:
        """Post-hook de cada video: convierte al formato de salida y, en MP4, incrusta la miniatura."""
        self.convert(path, spec)
        self.embed_thumbnail(path, spec)

    def post_audio(self, path: str, spec: dict) -> None:
        """Post-hook del audio: en MP3 y M4A incrusta la miniatura como carátula."""
        codec = AUDIO_FORMATS[spec["audio_fmt"]][0]
        if spec.get("embed") and codec in ("mp3", "m4a"):
            cover = ["-disposition:v:0", "attached_pic"] if codec == "m4a" else [
                "-id3v2_version", "3", "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
            self.attach_cover(path, cover, maps=("-map", "0:a", "-map", "1:v"))  # sin pistas de datos/capítulos

    def attach_cover(self, path: str, extra_args: list[str],
                     maps: tuple[str, ...] = ("-map", "0", "-map", "1")) -> None:
        """Añade a 'path' la imagen que dejó yt-dlp junto al archivo (.jpg) como carátula, y borra las miniaturas."""
        if not (path and os.path.isfile(path)):
            return
        base, ext = os.path.splitext(path)
        thumbs = [base + e for e in (".jpg", ".jpeg", ".png", ".webp")]
        try:
            thumb = next((t for t in thumbs if os.path.isfile(t)), None)
            if thumb:
                tmp = base + ".thumb" + ext
                cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-i", thumb, *maps,
                       "-c", "copy", *extra_args, tmp]
                ok, _ = self.run_ffmpeg(cmd, tmp)
                if ok:
                    os.replace(tmp, path)
                else:
                    log.warning("No se pudo incrustar la miniatura en %s", path)
        finally:
            for t in thumbs:
                self.remove_quietly(t)

    def encode(self, path: str, spec: dict, ext: str, vcodec: list[str], acodec: list[str], extra: list[str],
               vf: str) -> str | None:
        """Un intento de conversión con ffmpeg. Devuelve la ruta del archivo nuevo o None si falló."""
        dest = path[:-4] + (".compat.mp4" if ext == ".mp4" else ext)
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-map", "0:v:0", "-map", "0:a?"]
        if vf:
            cmd += ["-vf", vf]
        if ext == ".mp4" and spec.get("subs") and spec.get("subs_mode") == "embed":
            cmd += ["-map", "0:s?", "-c:s", "copy"]  # conserva los subtítulos incrustados
        cmd += vcodec + acodec + extra + [dest]
        ok, _ = self.run_ffmpeg(cmd, dest)
        return dest if ok else None

    def convert(self, path: str, spec: dict) -> None:
        """Convierte el video descargado al formato de salida elegido.

        H.264: solo recodifica lo necesario (video VP9/AV1 y/o audio Opus).
        Resto de formatos: recodifica siempre y borra el MP4 intermedio.
        GPU: si falla, se reintenta con CPU. Se puede cancelar: se detiene ffmpeg, se borra el archivo parcial
        y se conserva el MP4 original.
        """
        kind = spec["kind"]
        vf = build_video_filter(spec)  # escala/recorte: fuerza recodificar el video
        if kind == "original" or not path or not path.lower().endswith(".mp4") or not os.path.isfile(path):
            return
        codecs = self.probe_codecs(path)
        if codecs is None and kind == "h264":
            return
        src_v, src_a = codecs or (None, None)
        if kind == "h264":
            v_ok = src_v == "h264" and not vf
            a_ok = (not src_a) or src_a == "aac"
            if v_ok and a_ok:
                return
            label, ext = "H.264 + AAC", ".mp4"
            vcodec = ["-c:v", "copy"] if v_ok else list(H264_CPU[2])
            acodec = ["-c:a", "copy"] if a_ok else _AAC
            extra = ["-movflags", "+faststart"]
        else:
            label, ext, vcodec, acodec, extra = RECODE_SPECS[kind]
        note = ""
        if kind in INTRA_KINDS and src_v in ("vp9", "av1"):
            note = f"  El origen es {src_v.upper()}: la conversión mejora la compatibilidad, no la calidad."
        self.emit(("status", f"Convirtiendo a {label} (puede tardar)…{note}"))
        dest = self.encode(path, spec, ext, vcodec, acodec, extra, vf)
        if dest is None and kind in GPU_FALLBACK:
            cpu = H264_CPU if GPU_FALLBACK[kind] == "h264" else RECODE_SPECS[GPU_FALLBACK[kind]]
            log.warning("La conversión por GPU (%s) falló; se reintenta con CPU", label)
            self.emit(("status", f"La conversión por GPU falló; reintentando con CPU ({cpu[0]})…"))
            label, ext, vcodec, acodec, extra = cpu
            dest = self.encode(path, spec, ext, vcodec, acodec, extra, vf)
        if dest is None:
            self.emit(("status", f"No se pudo convertir a {label}; se conserva el MP4 original."))
            return
        if ext == ".mp4":
            os.replace(dest, path)  # sustituye al MP4 intermedio
        else:
            os.remove(path)

    def embed_thumbnail(self, path: str, spec: dict) -> None:
        """Incrusta la miniatura (.jpg que dejó yt-dlp) como carátula del MP4. Otros contenedores: no hace nada."""
        if spec.get("embed") and path and path.lower().endswith(".mp4"):
            self.attach_cover(path, ["-disposition:v:1", "attached_pic"])

    @staticmethod
    def cleanup_orphans(out: str) -> None:
        """Borra restos de conversiones interrumpidas (*.compat.mp4) en la carpeta y sus subcarpetas directas."""
        for pat in ("*.compat.mp4", os.path.join("*", "*.compat.mp4")):
            for p in glob.glob(os.path.join(glob.escape(out), pat)):
                try:
                    os.remove(p)
                    log.info("Resto de conversión eliminado: %s", p)
                except OSError:
                    pass
