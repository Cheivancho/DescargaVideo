"""Descargador de YouTube con interfaz oscura (tkinter + yt-dlp).

- Detecta todas las resoluciones realmente disponibles del video.
- Descarga una, varias o todas; soporta playlists y audio MP3.
- Panel derecho con miniatura y características del video.
Requiere: yt-dlp, Pillow y ffmpeg (en el PATH o junto al ejecutable).
"""
import copy
import ctypes
import glob
import io
import logging
import logging.handlers
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import urllib.parse
import urllib.request
from dataclasses import dataclass
from tkinter import filedialog, messagebox, ttk

import updater

updater.prepare_ytdlp()  # solo aplica lo ya descargado (local, sin red); debe ir antes de importar yt_dlp

import yt_dlp  # noqa: E402
from PIL import Image, ImageOps, ImageTk  # noqa: E402

# Permite usar el ffmpeg.exe que esté junto al ejecutable
_APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
os.environ["PATH"] = _APP_DIR + os.pathsep + os.environ.get("PATH", "")

_RES_DIR = getattr(sys, "_MEIPASS", _APP_DIR)

OUT_FORMATS = {
    "H.264 + AAC (MP4, ligero y compatible)": "h264",
    "H.265 / HEVC + AAC (MP4, más pequeño)": "h265",
    "ProRes 422 HQ (MOV, Media Encoder / edición)": "prores",
    "ProRes 422 (MOV, más liviano)": "prores_std",
    "DNxHR HQ (MOV, Premiere / Avid / DaVinci)": "dnxhr",
    "HAP (MOV, Resolume)": "hap",
    "HAP Q (MOV, Resolume, más calidad)": "hapq",
    "Motion JPEG (MOV, intra-frame ligero)": "mjpeg",
    "Original de YouTube (sin convertir)": "original",
}

# kind -> (nombre, extensión, args de video, args de audio, args extra)
_AAC = ["-c:a", "aac", "-b:a", "320k"]
_PCM = ["-c:a", "pcm_s16le"]
RECODE_SPECS = {
    "h265": ("H.265 + AAC", ".mp4", ["-c:v", "libx265", "-crf", "20", "-preset", "medium",
                                      "-pix_fmt", "yuv420p", "-tag:v", "hvc1"], _AAC, ["-movflags", "+faststart"]),
    "prores": ("ProRes 422 HQ", ".mov", ["-c:v", "prores_ks", "-profile:v", "3", "-vendor", "apl0",
                                          "-pix_fmt", "yuv422p10le"], _PCM, []),
    "prores_std": ("ProRes 422", ".mov", ["-c:v", "prores_ks", "-profile:v", "2", "-vendor", "apl0",
                                           "-pix_fmt", "yuv422p10le"], _PCM, []),
    "dnxhr": ("DNxHR HQ", ".mov", ["-c:v", "dnxhd", "-profile:v", "dnxhr_hq", "-pix_fmt", "yuv422p"], _PCM, []),
    "hap": ("HAP", ".mov", ["-c:v", "hap", "-format", "hap"], _PCM, []),
    "hapq": ("HAP Q", ".mov", ["-c:v", "hap", "-format", "hap_q"], _PCM, []),
    "mjpeg": ("Motion JPEG", ".mov", ["-c:v", "mjpeg", "-q:v", "2", "-pix_fmt", "yuvj422p"], _PCM, []),
}

PLAYLIST_HEIGHTS = [2160, 1440, 1080, 720, 480, 360, 240, 144]

# Paleta
BG = "#121216"
PANEL = "#1b1b22"
FIELD = "#24242d"
CORAL = "#F22E62"
CORAL_DIM = "#a51f43"
CORAL_SOFT = "#f77a99"
MUTED = "#a0607a"
FONT = "Segoe UI"

THUMB_W, THUMB_H = 320, 180  # en píxeles a 96 DPI; se escalan con el DPI de la pantalla
INFO_MAX_AGE = 20 * 60  # segundos: pasado este tiempo las URLs de stream del análisis pueden haber caducado

log = logging.getLogger("descargador")


def setup_logging() -> None:
    """Log rotativo en DATA_DIR\\log.txt (~1 MB, 3 copias). Nunca debe impedir que la app arranque."""
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    try:
        os.makedirs(updater.DATA_DIR, exist_ok=True)
        h = logging.handlers.RotatingFileHandler(os.path.join(updater.DATA_DIR, "log.txt"), maxBytes=1_000_000,
                                                 backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        log.addHandler(h)
    except OSError:
        log.addHandler(logging.NullHandler())


def enable_dpi_awareness() -> None:
    """Evita el escalado borroso de Windows en pantallas con DPI alto."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # por monitor
    except Exception:  # noqa: BLE001
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass


def find_js_runtimes() -> dict:
    """Runtime de JavaScript para los desafíos de YouTube (EJS). {} si no hay ninguno instalado."""
    for name, exe in (("deno", "deno"), ("node", "node"), ("bun", "bun"), ("quickjs", "qjs")):
        path = shutil.which(exe)
        if path:
            return {name: {"path": path}}
    return {}


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


def fmt_speed(bps) -> str:
    if not bps:
        return ""
    for unit, div in (("GiB/s", 2 ** 30), ("MiB/s", 2 ** 20), ("KiB/s", 2 ** 10)):
        if bps >= div:
            return f"{bps / div:.1f} {unit}"
    return f"{bps:.0f} B/s"


def fmt_eta(sec) -> str:
    if sec is None:
        return ""
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def final_ext(kind: str) -> str:
    """Extensión del archivo de video una vez convertido al formato de salida."""
    return RECODE_SPECS[kind][1] if kind in RECODE_SPECS else ".mp4"


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
            text_tail = "procesando…"
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


AUDIO_FORMATS = {  # nombre -> (códec de yt-dlp, extensión, ¿admite calidad en kbps?)
    "MP3": ("mp3", ".mp3", True), "M4A": ("m4a", ".m4a", True), "Opus": ("opus", ".opus", True),
    "WAV": ("wav", ".wav", False), "FLAC": ("flac", ".flac", False),
}
AUDIO_QUALITIES = ["320", "256", "192", "128"]
SUBS_MODES = ["Incrustar (MP4)", "Guardar .srt"]


@dataclass
class Job:
    """Un trabajo de yt-dlp: una resolución (o el audio) de un ítem de descarga."""
    item: dict
    label: str
    opts: dict
    ext: str  # extensión final del archivo (tras convertir)
    spec: dict


def parse_langs(text: str) -> list[str]:
    """'es, en' -> ['es', 'en']. Descarta basura; si no queda nada, usa es,en."""
    langs = [x for x in re.split(r"[,\s;]+", text or "") if re.fullmatch(r"[A-Za-z0-9*_.-]{1,20}", x)]
    return langs or ["es", "en"]


def short_title(title: str | None, n: int = 28) -> str:
    title = (title or "").strip()
    return title if len(title) <= n else title[:n - 1].rstrip() + "…"


def build_format_selector(height: int, is_playlist: bool = False, fps: int | None = None) -> str:
    """Selector de formato de yt-dlp: prefiere H.264 + AAC y cae a lo que haya. 'fps' limita los cuadros por segundo."""
    f = f"[fps<=?{int(fps)}]" if fps else ""
    if is_playlist:  # en listas: la mejor calidad HASTA la altura elegida
        return (f"bestvideo[height<={height}]{f}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                f"bestvideo[height<={height}]{f}+bestaudio/best[height<={height}]{f}/best")
    return (f"bestvideo[height={height}]{f}[vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
            f"bestvideo[height={height}]{f}+bestaudio/best[height={height}]{f}")


def video_template(height: int, is_playlist: bool, tag: str = "") -> str:
    name = f"%(title)s [{height}p]{tag}.%(ext)s"
    return "%(playlist_title)s/%(playlist_index)03d - " + name if is_playlist else name


def audio_template(is_playlist: bool) -> str:
    return "%(playlist_title)s/%(playlist_index)03d - %(title)s.%(ext)s" if is_playlist else "%(title)s.%(ext)s"


_THUMB_CONV = {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"}


def video_extras(spec: dict, ext: str) -> dict:
    """Opciones de yt-dlp para subtítulos, miniatura y metadatos de un video cuya extensión final es 'ext'."""
    opts: dict = {}
    pps: list[dict] = []
    if spec.get("subs"):
        opts.update(writesubtitles=True, writeautomaticsub=True, subtitleslangs=list(spec["subs_langs"]))
        if spec.get("subs_mode") == "embed" and ext == ".mp4":
            pps.append({"key": "FFmpegEmbedSubtitle", "already_have_subtitle": False})
        else:  # MOV y demás contenedores no admiten subtítulos incrustados: se guardan aparte
            pps.append({"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"})
    if spec.get("embed") and ext == ".mp4":
        opts["writethumbnail"] = True  # la carátula se incrusta después de convertir (ver _embed_thumbnail)
        pps.insert(0, dict(_THUMB_CONV))
        pps.append({"key": "FFmpegMetadata", "add_metadata": True})
    if pps:
        opts["postprocessors"] = pps
    return opts


def audio_extras(spec: dict) -> dict:
    """Opciones de yt-dlp para el trabajo de audio: extracción, metadatos y miniatura (solo MP3/M4A)."""
    codec, _ext, has_q = AUDIO_FORMATS[spec["audio_fmt"]]
    extract: dict = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
    if has_q:
        extract["preferredquality"] = spec["audio_q"]
    opts: dict = {}
    pps = [extract]
    if spec.get("embed"):
        if codec in ("mp3", "m4a"):
            opts["writethumbnail"] = True
            # La carátula la incrusta la app con ffmpeg (EmbedThumbnail de yt-dlp exigiría ffprobe)
            pps = [dict(_THUMB_CONV), extract, {"key": "FFmpegMetadata", "add_metadata": True}]
        elif codec != "wav":
            pps.append({"key": "FFmpegMetadata", "add_metadata": True})
    opts["postprocessors"] = pps
    return opts


DEFAULT_SETTINGS = {
    "out_dir": os.path.join(os.path.expanduser("~"), "Videos", "YouTube"),
    "fmt": "h264", "audio": False, "preset": "", "geometry": "",
    "audio_fmt": "MP3", "audio_q": "320", "subs": False, "subs_langs": "es,en", "subs_mode": SUBS_MODES[0],
    "embed": False,
}
_YT_LINK = re.compile(r"^https?://(?:(?:www|m|music)\.)?(?:youtube\.com|youtu\.be)/\S+$", re.I)


def load_settings(state: dict | None = None) -> dict:
    """Ajustes guardados en state.json['settings']. Tolera claves ausentes, tipos erróneos y estados corruptos."""
    raw = (updater.load_state() if state is None else state).get("settings")
    s = dict(DEFAULT_SETTINGS)
    if isinstance(raw, dict):
        for k, default in DEFAULT_SETTINGS.items():
            if isinstance(raw.get(k), type(default)):
                s[k] = raw[k]
    if s["fmt"] not in OUT_FORMATS.values():
        s["fmt"] = DEFAULT_SETTINGS["fmt"]
    if not re.fullmatch(r"\d{3,5}x\d{3,5}", s["geometry"]):
        s["geometry"] = ""
    if s["audio_fmt"] not in AUDIO_FORMATS:
        s["audio_fmt"] = "MP3"
    if s["audio_q"] not in AUDIO_QUALITIES:
        s["audio_q"] = "320"
    if s["subs_mode"] not in SUBS_MODES:
        s["subs_mode"] = SUBS_MODES[0]
    return s


def youtube_link(text: str) -> str | None:
    """Primer enlace de YouTube del texto (p. ej. del portapapeles), o None."""
    text = (text or "").strip()
    line = text.splitlines()[0].strip() if text else ""
    return line if _YT_LINK.match(line) else None


def fmt_num(n):
    if n is None:
        return "—"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}".replace(".0", "")
    return str(n)


def fmt_date(s):
    return f"{s[6:8]}/{s[4:6]}/{s[0:4]}" if s and len(s) == 8 else "—"


def fmt_dur(sec):
    if not sec:
        return "—"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.ui = max(self.winfo_fpixels("1i") / 96, 1.0)  # factor de escala por DPI
        self.thumb_w, self.thumb_h = self.px(THUMB_W), self.px(THUMB_H)
        self.title("Descargador de YouTube")
        self.geometry(f"{self.px(1060)}x{self.px(700)}")
        self.minsize(self.px(1000), self.px(680))
        self.configure(bg=BG)
        try:
            self.iconbitmap(os.path.join(_RES_DIR, "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        self.q = queue.Queue()
        self.ytlog = YtLogger()
        self.js_runtimes = find_js_runtimes()
        self.is_playlist = False
        self.analyzed_url = None  # URL realmente analizada: la descarga usa esta, no el campo de texto
        self.analyzed_info = None  # info de un video individual, reutilizable mientras no caduque
        self.analyzed_at = 0.0
        self.playlist_choice = None  # "video" | "list" | None (el enlace no era ambiguo)
        self.tracker = None
        self.skipped = []
        self._ff_proc = None
        self.res_vars = {}
        self.busy = False
        self.cur_spec = {}
        self.cancel = False
        self.thumb_img = None
        self.settings = load_settings()
        self.last_error = ""
        self.out_dir = tk.StringVar(value=self.settings["out_dir"])
        self._restore_geometry()
        self._styles()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<FocusIn>", self._on_focus_in)
        self.after(300, self._paste_clipboard_link)
        self.after(100, self._poll)
        self.after(1200, lambda: threading.Thread(target=self._check_update_worker, daemon=True).start())
        # La consulta/descarga de yt-dlp va en segundo plano y DESPUÉS de mostrar la ventana
        self.after(2500, lambda: threading.Thread(target=self._engine_update_worker, daemon=True).start())

    def _restore_geometry(self) -> None:
        m = re.fullmatch(r"(\d+)x(\d+)", self.settings["geometry"])
        if not m:
            return
        w = min(max(int(m[1]), self.px(1000)), self.winfo_screenwidth())
        h = min(max(int(m[2]), self.px(680)), self.winfo_screenheight())
        self.geometry(f"{w}x{h}")

    def _save_settings(self) -> None:
        self.settings.update({k: var.get() for k, var in self.v.items()})
        self.settings.update(out_dir=self.out_dir.get(), fmt=OUT_FORMATS.get(self.fmt_var.get(), "h264"),
                             geometry=f"{self.winfo_width()}x{self.winfo_height()}")
        updater.update_state(settings=self.settings)

    def _on_close(self) -> None:
        try:
            self._save_settings()
        except Exception:  # noqa: BLE001
            log.warning("No se pudieron guardar los ajustes", exc_info=True)
        self.destroy()

    def _paste_clipboard_link(self) -> None:
        """Si el campo está vacío y el portapapeles tiene un enlace de YouTube, lo pega (sin analizar)."""
        if self.url_var.get().strip() or self.busy:
            return
        try:
            link = youtube_link(self.clipboard_get())
        except tk.TclError:  # portapapeles vacío o con algo que no es texto
            return
        if link:
            self.url_var.set(link)
            self.status.set("Enlace pegado desde el portapapeles. Pulsa Analizar.")

    def _on_focus_in(self, event) -> None:
        if event.widget is self:
            self._paste_clipboard_link()

    def px(self, n: int) -> int:
        """Píxeles a 96 DPI -> píxeles reales de esta pantalla."""
        return int(round(n * getattr(self, "ui", 1.0)))

    # ---------- Estilos ----------
    def _styles(self):
        s = ttk.Style(self)
        s.theme_use("clam")
        s.configure("TEntry", fieldbackground=FIELD, foreground=CORAL, insertcolor=CORAL,
                    bordercolor=CORAL_DIM, lightcolor=FIELD, darkcolor=FIELD, padding=8)
        s.map("TEntry", bordercolor=[("focus", CORAL)])
        s.configure("Dark.TNotebook", background=PANEL, borderwidth=0, tabmargins=(0, 0, 0, 6), bordercolor=PANEL,
                    lightcolor=PANEL, darkcolor=PANEL)
        s.configure("Dark.TNotebook.Tab", lightcolor=FIELD, bordercolor=FIELD)
        s.configure("Dark.TNotebook.Tab", background=FIELD, foreground=CORAL_SOFT, padding=(14, 6), borderwidth=0,
                    font=(FONT, 10, "bold"))
        s.map("Dark.TNotebook.Tab", background=[("selected", CORAL_DIM)], foreground=[("selected", "white")])
        s.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=CORAL, arrowcolor=CORAL,
                    bordercolor=CORAL_DIM, lightcolor=FIELD, darkcolor=FIELD, padding=4)
        s.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", CORAL)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", CORAL)
        self.option_add("*TCombobox*Listbox.selectBackground", CORAL_DIM)
        s.configure("Coral.Horizontal.TProgressbar", troughcolor=FIELD, background=CORAL,
                    bordercolor=PANEL, lightcolor=CORAL, darkcolor=CORAL, thickness=8)

    def _btn(self, parent, text, cmd, solid=False, **kw):
        b = tk.Button(parent, text=text, command=cmd, relief="flat", bd=0, cursor="hand2",
                      font=(FONT, 10, "bold"),
                      bg=CORAL if solid else FIELD, fg=BG if solid else CORAL,
                      activebackground=CORAL_SOFT if solid else CORAL_DIM,
                      activeforeground=BG if solid else "white",
                      disabledforeground="#6b4757", padx=14, pady=7, **kw)
        return b

    def _tab(self, name):
        """Pestaña del panel izquierdo; devuelve el marco interior donde colocar los controles."""
        outer = tk.Frame(self.tabs, bg=PANEL)
        self.tabs.add(outer, text=f"  {name}  ")
        inner = tk.Frame(outer, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=4, pady=6)
        return inner

    def _check(self, parent, text, var, **kw):
        return tk.Checkbutton(parent, text="  " + text, variable=var, bg=PANEL, fg=CORAL, activebackground=PANEL,
                              activeforeground=CORAL_SOFT, selectcolor=FIELD, font=(FONT, 10), bd=0,
                              highlightthickness=0, cursor="hand2", **kw)

    def _sync_audio_quality(self):
        has_q = AUDIO_FORMATS.get(self.v["audio_fmt"].get(), ("", "", False))[2]
        self.audio_q_box.config(state="readonly" if has_q else "disabled")

    def _label(self, parent, text="", size=10, bold=False, color=CORAL, bg=BG, **kw):
        return tk.Label(parent, text=text, bg=bg, fg=color, font=(FONT, size, "bold" if bold else "normal"), **kw)

    # ---------- UI ----------
    def _build(self):
        # Cabecera
        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=24, pady=(20, 8))
        self._label(head, "▶  Descargador de YouTube", 18, True).pack(side="left")
        self._label(head, f"v{updater.VERSION}", 9, False, MUTED).pack(side="left", padx=(10, 0), pady=(8, 0))
        self.btn_help = self._btn(head, "Ayuda ▾", self._show_help_menu)
        self.btn_help.config(pady=3, padx=10)
        self.btn_help.pack(side="right")
        self.engine_lbl = self._label(head, "", 9, False, MUTED)
        self.engine_lbl.pack(side="right", padx=(0, 12), pady=(2, 0))
        self.help_menu = tk.Menu(self, tearoff=0, bg=PANEL, fg=CORAL, activebackground=CORAL_DIM,
                                 activeforeground="white", font=(FONT, 10), bd=0)
        self.help_menu.add_command(label="Abrir log", command=self._open_log)
        self.help_menu.add_command(label="Acerca de…", command=self._about)
        self.help_menu.add_separator()
        self.help_menu.add_command(label="Buscar actualizaciones ahora", command=self._check_updates_now)
        self.help_menu.add_command(label="Restaurar motor incluido", command=self._reset_engine)

        # Barra de URL
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=24, pady=(4, 14))
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", self._on_url_edit)
        self.url = ttk.Entry(bar, font=(FONT, 11), textvariable=self.url_var)
        self.url.pack(side="left", fill="x", expand=True, ipady=3)
        self.url.bind("<Return>", lambda e: self.analyze())
        self.btn_an = self._btn(bar, "Analizar", self.analyze)
        self.btn_an.pack(side="left", padx=(10, 0))

        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 20))
        body.columnconfigure(0, weight=1, uniform="c")
        body.columnconfigure(1, weight=1, uniform="c")
        body.rowconfigure(0, weight=1)

        # ----- Panel izquierdo: opciones (pestañas) -----
        left = tk.Frame(body, bg=PANEL)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        inner = tk.Frame(left, bg=PANEL)
        inner.pack(fill="both", expand=True, padx=16, pady=14)

        # Destino: se empaqueta primero (side="bottom") para que SIEMPRE sea visible
        dest_box = tk.Frame(inner, bg=PANEL)
        dest_box.pack(side="bottom", fill="x", pady=(10, 0))
        self._label(dest_box, "CARPETA DE DESTINO", 9, True, CORAL_SOFT, PANEL).pack(anchor="w", pady=(0, 6))
        dest = tk.Frame(dest_box, bg=PANEL)
        dest.pack(fill="x")
        ttk.Entry(dest, textvariable=self.out_dir).pack(side="left", fill="x", expand=True)
        self._btn(dest, "…", self._browse).pack(side="left", padx=(8, 0))

        self.tabs = ttk.Notebook(inner, style="Dark.TNotebook")
        self.tabs.pack(fill="both", expand=True)
        tab_video = self._tab("Video")
        tab_extra = self._tab("Extras")

        # --- Pestaña Video ---
        self._label(tab_video, "RESOLUCIONES", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        row = tk.Frame(tab_video, bg=PANEL)
        row.pack(fill="x", pady=(6, 8))
        self._btn(row, "Todas", lambda: self._set_all(True)).pack(side="left")
        self._btn(row, "Ninguna", lambda: self._set_all(False)).pack(side="left", padx=6)

        self.res_frame = tk.Frame(tab_video, bg=PANEL)
        self.res_frame.pack(fill="x")
        self.res_hint = self._label(self.res_frame, "Analiza un enlace para ver\nlas resoluciones disponibles.",
                                    10, False, MUTED, PANEL, justify="left")
        self.res_hint.pack(anchor="w", pady=10)

        tk.Frame(tab_video, bg=CORAL_DIM, height=1).pack(fill="x", pady=12)

        self._label(tab_video, "FORMATO DE SALIDA", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self.fmt_var = tk.StringVar(value=next((k for k, v in OUT_FORMATS.items() if v == self.settings["fmt"]),
                                               next(iter(OUT_FORMATS))))
        ttk.Combobox(tab_video, textvariable=self.fmt_var, values=list(OUT_FORMATS), state="readonly",
                     font=(FONT, 10)).pack(fill="x", pady=(6, 0))
        self._label(tab_video, "ProRes y HAP generan archivos muy pesados (varios GB por minuto en 4K).",
                    8, False, MUTED, PANEL, wraplength=self.px(380), justify="left").pack(anchor="w", pady=(4, 0))

        # --- Pestaña Extras ---
        s = self.settings
        self.v = {
            "audio": tk.BooleanVar(value=s["audio"]), "audio_fmt": tk.StringVar(value=s["audio_fmt"]),
            "audio_q": tk.StringVar(value=s["audio_q"]), "subs": tk.BooleanVar(value=s["subs"]),
            "subs_langs": tk.StringVar(value=s["subs_langs"]), "subs_mode": tk.StringVar(value=s["subs_mode"]),
            "embed": tk.BooleanVar(value=s["embed"]),
        }
        self.audio_var = self.v["audio"]

        self._label(tab_extra, "AUDIO", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self._check(tab_extra, "Descargar también solo audio", self.v["audio"]).pack(anchor="w", pady=(6, 2))
        arow = tk.Frame(tab_extra, bg=PANEL)
        arow.pack(fill="x", pady=(0, 4))
        self._label(arow, "Formato", 9, False, MUTED, PANEL).pack(side="left")
        ttk.Combobox(arow, textvariable=self.v["audio_fmt"], values=list(AUDIO_FORMATS), state="readonly", width=7,
                     font=(FONT, 10)).pack(side="left", padx=(6, 12))
        self._label(arow, "Calidad (kbps)", 9, False, MUTED, PANEL).pack(side="left")
        self.audio_q_box = ttk.Combobox(arow, textvariable=self.v["audio_q"], values=AUDIO_QUALITIES, width=5,
                                        state="readonly", font=(FONT, 10))
        self.audio_q_box.pack(side="left", padx=6)
        self.v["audio_fmt"].trace_add("write", lambda *_: self._sync_audio_quality())
        self._sync_audio_quality()

        tk.Frame(tab_extra, bg=CORAL_DIM, height=1).pack(fill="x", pady=10)
        self._label(tab_extra, "SUBTÍTULOS", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self._check(tab_extra, "Descargar subtítulos", self.v["subs"]).pack(anchor="w", pady=(6, 2))
        srow = tk.Frame(tab_extra, bg=PANEL)
        srow.pack(fill="x", pady=(0, 4))
        self._label(srow, "Idiomas", 9, False, MUTED, PANEL).pack(side="left")
        ttk.Entry(srow, textvariable=self.v["subs_langs"], width=10).pack(side="left", padx=(6, 12))
        ttk.Combobox(srow, textvariable=self.v["subs_mode"], values=SUBS_MODES, state="readonly", width=16,
                     font=(FONT, 10)).pack(side="left")
        self._label(tab_extra, "Incrustar solo funciona en MP4; en MOV se guarda el .srt aparte.", 8, False, MUTED,
                    PANEL, wraplength=self.px(380), justify="left").pack(anchor="w")

        tk.Frame(tab_extra, bg=CORAL_DIM, height=1).pack(fill="x", pady=10)
        self._label(tab_extra, "MINIATURA Y METADATOS", 9, True, CORAL_SOFT, PANEL).pack(anchor="w")
        self._check(tab_extra, "Incrustar miniatura y metadatos", self.v["embed"]).pack(anchor="w", pady=(6, 2))
        self._label(tab_extra, "Solo MP4, MP3 y M4A (en MOV, Opus, WAV y FLAC se ignora la miniatura).", 8, False,
                    MUTED, PANEL, wraplength=self.px(380), justify="left").pack(anchor="w")

        # ----- Panel derecho: preview -----
        right = tk.Frame(body, bg=PANEL)
        right.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        rin = tk.Frame(right, bg=PANEL)
        rin.pack(fill="both", expand=True, padx=20, pady=14)

        # Zona inferior: se empaqueta primero con side="bottom" para que SIEMPRE sea visible
        acts = tk.Frame(rin, bg=PANEL)
        acts.pack(side="bottom", fill="x")
        self.btn_dl = tk.Button(acts, text="⬇   DESCARGAR", command=self.download, relief="flat", bd=0,
                                cursor="hand2", font=(FONT, 14, "bold"), bg=CORAL, fg=BG,
                                activebackground=CORAL_SOFT, activeforeground=BG,
                                disabledforeground="#6b4757", pady=12, state="disabled")
        self.btn_dl.pack(side="left", fill="x", expand=True)
        self.btn_cancel = self._btn(acts, "Cancelar", self._cancel)
        self.btn_cancel.config(state="disabled", pady=14)
        self.btn_cancel.pack(side="left", padx=(8, 0))
        self._update_dl_style()

        self.result_row = tk.Frame(rin, bg=PANEL)  # «Abrir carpeta» / «Copiar error»: solo cuando aplican
        self.result_row.pack(side="bottom", fill="x", pady=(0, 6))
        self.btn_open = self._btn(self.result_row, "📂  Abrir carpeta", self._open_folder)
        self.btn_copyerr = self._btn(self.result_row, "Copiar error", self._copy_error)

        self.status = tk.StringVar(value="Pega un enlace y pulsa Analizar.")
        tk.Label(rin, textvariable=self.status, bg=PANEL, fg=CORAL_SOFT, font=(FONT, 9),
                 wraplength=self.px(380), justify="left", anchor="w").pack(side="bottom", fill="x", pady=(0, 8))
        self.bar = ttk.Progressbar(rin, maximum=100, style="Coral.Horizontal.TProgressbar")
        self.bar.pack(side="bottom", fill="x", pady=(0, 6))

        # Contenedor de tamaño fijo: la miniatura nunca se encoge ni depende del largo del título
        self.thumb_box = tk.Frame(rin, bg=FIELD, height=self.thumb_h)
        self.thumb_box.pack(fill="x")
        self.thumb_box.pack_propagate(False)
        self.thumb = tk.Label(self.thumb_box, bg=FIELD, fg=MUTED, text="Vista previa", font=(FONT, 11), bd=0)
        self.thumb.place(relx=0.5, rely=0.5, anchor="center")
        self.dur_badge = self._label(self.thumb, "", 9, True, "white", "#000000", padx=6, pady=1)

        self.title_lbl = self._label(rin, "Sin video", 12, True, CORAL, PANEL, wraplength=self.px(360), justify="left",
                                     anchor="w")
        self.title_lbl.pack(anchor="w", pady=(8, 2), fill="x")
        self.chan_lbl = self._label(rin, "", 10, False, CORAL_SOFT, PANEL, anchor="w")
        self.chan_lbl.pack(fill="x")

        self.meta = {}
        grid = tk.Frame(rin, bg=PANEL)
        grid.pack(fill="x", pady=(8, 4))
        grid.columnconfigure((0, 1), weight=1, uniform="m")
        for i, key in enumerate(["Duración", "Vistas", "Publicado", "Likes", "Mejor calidad", "Resoluciones"]):
            cell = tk.Frame(grid, bg=PANEL)
            cell.grid(row=i // 2, column=i % 2, sticky="w", pady=2)
            self._label(cell, key.upper() + "  ", 8, True, MUTED, PANEL).pack(side="left")
            v = self._label(cell, "—", 10, True, CORAL, PANEL)
            v.pack(side="left")
            self.meta[key] = v

    def _show_help_menu(self) -> None:
        self.help_menu.tk_popup(self.btn_help.winfo_rootx(), self.btn_help.winfo_rooty() + self.btn_help.winfo_height())

    def _open_log(self) -> None:
        path = os.path.join(updater.DATA_DIR, "log.txt")
        if os.path.isfile(path):
            os.startfile(path)
        else:
            messagebox.showinfo("Log", "Todavía no hay registro (log.txt).")

    def _about(self) -> None:
        pend = updater.pending_update_version()
        text = f"Descargador de YouTube v{updater.VERSION}\nyt-dlp {yt_dlp.version.__version__}"
        if pend:
            text += f"\n(motor {pend} listo; se aplica al reiniciar)"
        text += f"\nMotor JavaScript: {', '.join(self.js_runtimes) or 'ninguno'}"
        messagebox.showinfo("Acerca de", text)

    def _check_updates_now(self) -> None:
        self.status.set("Buscando actualizaciones…")

        def work():
            try:
                upd = updater.check_app_update()
                v = updater.background_ytdlp_update(force=True)
                if v:
                    self.q.put(("engine", v))
                if upd:
                    self.q.put(("app_update", upd))
                elif v:
                    self.q.put(("msgbox", "Actualizaciones", f"Motor yt-dlp {v} descargado (se aplica al reiniciar)."))
                else:
                    self.q.put(("msgbox", "Actualizaciones", "Todo está al día."))
            except Exception as e:  # noqa: BLE001
                log.warning("Búsqueda manual de actualizaciones fallida", exc_info=True)
                self.q.put(("msgbox", "Actualizaciones", f"No se pudo comprobar: {e}"))
        threading.Thread(target=work, daemon=True).start()

    def _reset_engine(self) -> None:
        if messagebox.askyesno("Restaurar motor", "Se borrará el yt-dlp descargado y se volverá al incluido en la "
                               "app.\nSe aplica al reiniciar. ¿Continuar?"):
            updater.reset_ytdlp_engine()
            self.engine_lbl.config(text="Motor restaurado (se aplica al reiniciar)")

    def _open_folder(self) -> None:
        path = self.out_dir.get()
        if os.path.isdir(path):
            os.startfile(path)

    def _copy_error(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.last_error)
        self.status.set("Error copiado al portapapeles.")

    def _show_result_buttons(self, ok: bool, has_error: bool) -> None:
        for b in (self.btn_open, self.btn_copyerr):
            b.pack_forget()
        if ok:
            self.btn_open.pack(side="left")
        if has_error:
            self.btn_copyerr.pack(side="left", padx=(8 if ok else 0, 0))

    def _update_dl_style(self):
        if str(self.btn_dl["state"]) == "disabled":
            self.btn_dl.config(bg=FIELD)
        else:
            self.btn_dl.config(bg=CORAL)

    def _set_dl(self, enabled):
        self.btn_dl.config(state="normal" if enabled else "disabled")
        self._update_dl_style()

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.out_dir.get())
        if d:
            self.out_dir.set(d)

    def _set_all(self, v):
        for var in self.res_vars.values():
            var.set(v)

    def _show_resolutions(self, heights, hint=None):
        for w in self.res_frame.winfo_children():
            w.destroy()
        self.res_vars = {}
        if not heights:
            self._label(self.res_frame, "No se encontraron resoluciones.\nRevisa el mensaje de estado.", 10, False,
                        MUTED, PANEL, justify="left").pack(anchor="w")
            return
        for i, h in enumerate(heights):
            var = tk.BooleanVar(value=(i == 0))
            self.res_vars[h] = var
            label = f"{h}p"
            if h >= 4320:
                label += " 8K"
            elif h >= 2160:
                label += " 4K"
            elif h >= 1080:
                label += " HD"
            tk.Checkbutton(self.res_frame, text=label, variable=var, indicatoron=False,
                           bg=FIELD, fg=CORAL, selectcolor=CORAL, activebackground=CORAL_DIM,
                           activeforeground="white", font=(FONT, 10, "bold"), relief="flat", bd=0,
                           highlightthickness=0, cursor="hand2", width=9, pady=7,
                           command=self._refresh_chips).grid(row=i // 3, column=i % 3, padx=4, pady=4, sticky="w")
        self._refresh_chips()

    def _refresh_chips(self):
        # El texto de un chip seleccionado pasa a oscuro para contrastar con el fondo coral
        for w in self.res_frame.winfo_children():
            if isinstance(w, tk.Checkbutton):
                sel = w.getvar(str(w.cget("variable")))
                w.config(fg=BG if str(sel) in ("1", "True") else CORAL)

    # ---------- Análisis ----------
    def _url_matches(self) -> bool:
        return self.analyzed_url is not None and self.url_var.get().strip() == self.analyzed_url

    def _on_url_edit(self, *_) -> None:
        """Si se edita la URL después de analizar, DESCARGAR queda bloqueado hasta volver a analizar."""
        if self.analyzed_url is None or self.busy:
            return
        if self._url_matches():
            self._set_dl(True)
        else:
            self._set_dl(False)
            self.status.set("La URL cambió. Vuelve a pulsar Analizar.")

    def _ask_playlist_choice(self):
        """¿Solo este video o toda la lista? Devuelve "video", "list" o None (cancelar)."""
        result = {"v": None}
        dlg = tk.Toplevel(self, bg=PANEL)
        dlg.title("Enlace con lista")
        dlg.resizable(False, False)
        dlg.transient(self)
        try:
            dlg.iconbitmap(os.path.join(_RES_DIR, "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        box = tk.Frame(dlg, bg=PANEL)
        box.pack(padx=24, pady=20)
        self._label(box, "Este enlace es de un video dentro de una lista.", 11, True, CORAL, PANEL).pack(anchor="w")
        self._label(box, "¿Descargar solo este video o toda la lista?", 10, False, CORAL_SOFT, PANEL
                    ).pack(anchor="w", pady=(4, 14))
        row = tk.Frame(box, bg=PANEL)
        row.pack(fill="x")

        def pick(v):
            result["v"] = v
            dlg.destroy()
        self._btn(row, "Solo este video", lambda: pick("video"), solid=True).pack(side="left")
        self._btn(row, "Toda la lista", lambda: pick("list")).pack(side="left", padx=8)
        self._btn(row, "Cancelar", lambda: pick(None)).pack(side="left")
        dlg.protocol("WM_DELETE_WINDOW", lambda: pick(None))
        dlg.update_idletasks()
        x = self.winfo_rootx() + (self.winfo_width() - dlg.winfo_reqwidth()) // 2
        y = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_reqheight()) // 2
        dlg.geometry(f"+{max(x, 0)}+{max(y, 0)}")
        dlg.grab_set()
        self.wait_window(dlg)
        return result["v"]

    def _ydl_base(self) -> dict:
        opts = {"quiet": True, "noprogress": True, "logger": self.ytlog}
        if self.js_runtimes:
            opts["js_runtimes"] = self.js_runtimes
        return opts

    def analyze(self):
        url = self.url_var.get().strip()
        if not url or self.busy:
            return
        choice = None
        if has_video_and_list(url):
            choice = self._ask_playlist_choice()
            if choice is None:
                return
        self.busy = True
        self.analyzed_url = None
        self.btn_an.config(state="disabled")
        self._set_dl(False)
        self.status.set("Analizando…")
        threading.Thread(target=self._analyze_worker, args=(url, choice), daemon=True).start()

    def _analyze_worker(self, url, choice):
        try:
            self.ytlog.last_warning = None
            opts = {**self._ydl_base(), "extract_flat": "in_playlist", "noplaylist": choice == "video"}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
            is_pl = info.get("_type") == "playlist"
            if is_pl:
                heights = PLAYLIST_HEIGHTS
                entries = [e for e in (info.get("entries") or []) if e]
                thumb_url = info.get("thumbnail") or next(
                    (t["url"] for e in entries for t in (e.get("thumbnails") or [])[-1:]), None)
            else:
                heights = sorted(
                    {f["height"] for f in info.get("formats", [])
                     if f.get("vcodec") not in (None, "none") and f.get("height")}, reverse=True)
                thumb_url = info.get("thumbnail")
            data = None
            if thumb_url:
                try:
                    req = urllib.request.Request(thumb_url, headers={"User-Agent": "Mozilla/5.0"})
                    data = urllib.request.urlopen(req, timeout=15).read()
                except Exception:  # noqa: BLE001
                    data = None
            fps = max((f.get("fps") or 0 for f in info.get("formats", []) or []), default=0)
            self.q.put(("analyzed", url, choice, info, is_pl, heights, data, fps))
        except Exception as e:  # noqa: BLE001
            log.exception("Error al analizar %s", url)
            self.last_error = f"Al analizar {url}\n{traceback.format_exc()}"
            self.q.put(("error", str(e)))

    def _apply_info(self, url, choice, info, is_pl, heights, data, fps):
        self.is_playlist = is_pl
        self.analyzed_url = url
        self.playlist_choice = choice
        self.analyzed_info = None if is_pl else info
        self.analyzed_at = time.time()
        title = info.get("title") or "Sin título"
        self.title_lbl.config(text=title if len(title) <= 80 else title[:79].rstrip() + "…")
        if is_pl:
            n = len(info.get("entries") or [])
            self.chan_lbl.config(text=info.get("uploader") or info.get("channel") or "Playlist")
            vals = {"Duración": f"{n} videos", "Vistas": "—", "Publicado": "—",
                    "Mejor calidad": "Hasta " + f"{max(heights)}p", "Resoluciones": "Playlist", "Likes": "—"}
            self.dur_badge.place_forget()
        else:
            self.chan_lbl.config(text=info.get("uploader") or info.get("channel") or "")
            best = f"{max(heights)}p" + (f" · {int(fps)}fps" if fps else "") if heights else "—"
            vals = {"Duración": fmt_dur(info.get("duration")), "Vistas": fmt_num(info.get("view_count")),
                    "Publicado": fmt_date(info.get("upload_date")), "Mejor calidad": best,
                    "Resoluciones": str(len(heights)), "Likes": fmt_num(info.get("like_count"))}
            self.dur_badge.config(text=fmt_dur(info.get("duration")))
            self.dur_badge.place(relx=1.0, rely=1.0, x=-8, y=-8, anchor="se")
        for k, v in vals.items():
            self.meta[k].config(text=v)
        self._set_thumbnail(data)
        hint = None if is_pl else diagnose_formats(heights, self.ytlog.last_warning, bool(self.js_runtimes))
        self._show_resolutions(heights, hint)
        if is_pl:
            self.status.set("Playlist: se usará la mejor calidad hasta la resolución elegida.")
        else:
            self.status.set(hint or f"{len(heights)} resoluciones disponibles. Elige y descarga.")

    def _set_thumbnail(self, data):
        """Muestra la miniatura recortada a 16:9; si no hay o falla, vuelve al marcador."""
        try:
            if not data:
                raise ValueError("sin miniatura")
            img = ImageOps.fit(Image.open(io.BytesIO(data)).convert("RGB"), (self.thumb_w, self.thumb_h))
            self.thumb_img = ImageTk.PhotoImage(img)
            self.thumb.config(image=self.thumb_img, text="", width=self.thumb_w, height=self.thumb_h)
        except Exception:  # noqa: BLE001
            self.thumb_img = None
            self.thumb.config(image="", text="Sin vista previa", width=0, height=0)
            self.dur_badge.place_forget()

    # ---------- Descarga ----------
    def _collect_spec(self) -> dict:
        """Lee la interfaz y devuelve las opciones del trabajo (un dict simple, apto para la cola y los presets)."""
        v = {k: var.get() for k, var in self.v.items()}
        return {
            "out_dir": self.out_dir.get(),
            "kind": OUT_FORMATS[self.fmt_var.get()],
            "heights": [h for h, var in self.res_vars.items() if var.get()],
            "audio": bool(v["audio"]), "audio_fmt": v["audio_fmt"], "audio_q": v["audio_q"],
            "subs": bool(v["subs"]), "subs_langs": parse_langs(v["subs_langs"]),
            "subs_mode": "embed" if str(v["subs_mode"]).startswith("Incrustar") else "srt",
            "embed": bool(v["embed"]),
        }

    def download(self):
        if self.busy:
            return
        if not self._url_matches():
            self.status.set("La URL cambió. Vuelve a pulsar Analizar.")
            self._set_dl(False)
            return
        spec = self._collect_spec()
        if not spec["heights"] and not spec["audio"]:
            messagebox.showwarning("Nada seleccionado", "Marca al menos una resolución o el audio.")
            return
        os.makedirs(spec["out_dir"], exist_ok=True)
        item = {"url": self.analyzed_url, "is_playlist": self.is_playlist, "info": self.analyzed_info,
                "analyzed_at": self.analyzed_at, "title": self.title_lbl.cget("text"), "spec": spec}
        self._start_download([item])

    def _start_download(self, items):
        self.busy = True
        self.cancel = False
        self.last_error = ""
        self._show_result_buttons(False, False)
        self._save_settings()
        self._set_dl(False)
        self.btn_an.config(state="disabled")
        self.btn_cancel.config(state="normal")
        threading.Thread(target=self._download_worker, args=(items,), daemon=True).start()

    def _cancel(self):
        self.cancel = True
        self.status.set("Cancelando…")

    def _hook(self, d):
        if self.cancel:
            raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario")
        if self.tracker:
            pct, text = self.tracker.update(d)
            self.q.put(("progress", pct, text))

    def _kill_ffmpeg(self, proc):
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
    def _remove_quietly(path):
        for _ in range(10):  # Windows puede tardar un instante en soltar el archivo
            try:
                if os.path.exists(path):
                    os.remove(path)
                return
            except OSError:
                time.sleep(0.3)

    def _run_ffmpeg(self, cmd, dest):
        """Ejecuta ffmpeg de forma cancelable. Devuelve (ok, stderr). Si se cancela: lo detiene, borra
        'dest' (archivo parcial) y lanza DownloadCancelled; el archivo de entrada no se toca."""
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace", creationflags=flags)
        except OSError as e:
            log.exception("No se pudo lanzar ffmpeg")
            return False, str(e)
        self._ff_proc = proc
        err = ""
        try:
            while True:
                try:
                    _, err = proc.communicate(timeout=0.3)
                    break
                except subprocess.TimeoutExpired:
                    if self.cancel:
                        self._kill_ffmpeg(proc)
                        self._remove_quietly(dest)
                        raise yt_dlp.utils.DownloadCancelled("Cancelado durante la conversión") from None
        finally:
            self._ff_proc = None
        if proc.returncode != 0:
            log.error("ffmpeg falló: %s", (err or "").strip()[-500:])
            self._remove_quietly(dest)
            return False, err or ""
        return True, ""

    @staticmethod
    def _probe_codecs(path):
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

    def _post_video(self, path):
        """Post-hook de cada video: convierte al formato de salida y, en MP4, incrusta la miniatura."""
        spec = self.cur_spec
        self._convert(path, spec)
        self._embed_thumbnail(path, spec)

    def _post_audio(self, path):
        """Post-hook del audio: en MP3 y M4A incrusta la miniatura como carátula."""
        spec = self.cur_spec
        codec = AUDIO_FORMATS[spec["audio_fmt"]][0]
        if spec.get("embed") and codec in ("mp3", "m4a"):
            cover = ["-disposition:v:0", "attached_pic"] if codec == "m4a" else [
                "-id3v2_version", "3", "-metadata:s:v", "title=Album cover", "-metadata:s:v", "comment=Cover (front)"]
            self._attach_cover(path, cover, maps=("-map", "0:a", "-map", "1:v"))  # sin pistas de datos/capítulos

    def _attach_cover(self, path, extra_args, maps=("-map", "0", "-map", "1")):
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
                ok, _ = self._run_ffmpeg(cmd, tmp)
                if ok:
                    os.replace(tmp, path)
                else:
                    log.warning("No se pudo incrustar la miniatura en %s", path)
        finally:
            for t in thumbs:
                self._remove_quietly(t)

    def _convert(self, path, spec):
        """Convierte el video descargado al formato de salida elegido.

        H.264: solo recodifica lo necesario (video VP9/AV1 y/o audio Opus).
        Resto de formatos: recodifica siempre y borra el MP4 intermedio.
        Se puede cancelar: se detiene ffmpeg, se borra el archivo parcial y se conserva el MP4 original.
        """
        kind = spec["kind"]
        if kind == "original" or not path or not path.lower().endswith(".mp4") or not os.path.isfile(path):
            return
        if kind == "h264":
            codecs = self._probe_codecs(path)
            if codecs is None:
                return
            vcodec_src, acodec_src = codecs
            v_ok = vcodec_src == "h264"
            a_ok = (not acodec_src) or acodec_src == "aac"
            if v_ok and a_ok:
                return
            label, ext = "H.264 + AAC", ".mp4"
            vcodec = ["-c:v", "copy"] if v_ok else ["-c:v", "libx264", "-crf", "17", "-preset", "medium",
                                                     "-pix_fmt", "yuv420p"]
            acodec = ["-c:a", "copy"] if a_ok else _AAC
            extra = ["-movflags", "+faststart"]
        else:
            label, ext, vcodec, acodec, extra = RECODE_SPECS[kind]
        dest = path[:-4] + (".compat.mp4" if ext == ".mp4" else ext)
        self.q.put(("status", f"Convirtiendo a {label} (puede tardar)…"))
        cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", path, "-map", "0:v:0", "-map", "0:a?"]
        if ext == ".mp4" and spec.get("subs") and spec.get("subs_mode") == "embed":
            cmd += ["-map", "0:s?", "-c:s", "copy"]  # conserva los subtítulos incrustados
        cmd += vcodec + acodec + extra + [dest]
        ok, _ = self._run_ffmpeg(cmd, dest)
        if not ok:
            self.q.put(("status", f"No se pudo convertir a {label}; se conserva el MP4 original."))
            return
        if ext == ".mp4":
            os.replace(dest, path)  # sustituye al MP4 intermedio
        else:
            os.remove(path)

    def _embed_thumbnail(self, path, spec):
        """Incrusta la miniatura (.jpg que dejó yt-dlp) como carátula del MP4. Otros contenedores: no hace nada."""
        if spec.get("embed") and path and path.lower().endswith(".mp4"):
            self._attach_cover(path, ["-disposition:v:1", "attached_pic"])

    @staticmethod
    def _cleanup_orphans(out):
        """Borra restos de conversiones interrumpidas (*.compat.mp4) en la carpeta y sus subcarpetas directas."""
        for pat in ("*.compat.mp4", os.path.join("*", "*.compat.mp4")):
            for p in glob.glob(os.path.join(glob.escape(out), pat)):
                try:
                    os.remove(p)
                    log.info("Resto de conversión eliminado: %s", p)
                except OSError:
                    pass

    def _make_skip_filter(self, holder, ext):
        """match_filter de yt-dlp: salta lo que ya existe con su nombre final (extensión tras convertir)."""
        def match(info_dict, *, incomplete=False):
            if incomplete or holder.get("ydl") is None:
                return None
            try:
                final = os.path.splitext(holder["ydl"].prepare_filename(info_dict))[0] + ext
            except Exception:  # noqa: BLE001
                return None
            if os.path.isfile(final):
                name = os.path.basename(final)
                self.skipped.append(name)
                self.q.put(("status", f"Ya existía: {name}"))
                return f"ya existía: {name}"
            return None
        return match

    def _run_job(self, opts, url, info, analyzed_at, ext):
        holder = {}
        opts = {**opts, "match_filter": self._make_skip_filter(holder, ext)}
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

    def _build_jobs(self, item):
        """Convierte un ítem (URL + spec) en trabajos de yt-dlp: uno por resolución y uno de audio."""
        spec, pl, out = item["spec"], item["is_playlist"], item["spec"]["out_dir"]
        ext = final_ext(spec["kind"])
        base = {**self._ydl_base(), "progress_hooks": [self._hook], "ignoreerrors": False,
                "noplaylist": not pl, "continuedl": True}
        jobs = []
        for h in spec["heights"]:
            opts = {**base, "post_hooks": [self._post_video], "format": build_format_selector(h, pl),
                    "merge_output_format": "mp4", "outtmpl": os.path.join(out, video_template(h, pl))}
            opts.update(video_extras(spec, ext))
            jobs.append(Job(item, f"{h}p", opts, ext, spec))
        if spec["audio"]:
            codec, aext, has_q = AUDIO_FORMATS[spec["audio_fmt"]]
            opts = {**base, "post_hooks": [self._post_audio], "format": "bestaudio/best",
                    "outtmpl": os.path.join(out, audio_template(pl))}
            opts.update(audio_extras(spec))
            label = spec["audio_fmt"] + (f" {spec['audio_q']}" if has_q else "")
            jobs.append(Job(item, label, opts, aext, spec))
        return jobs

    def _download_worker(self, items):
        jobs = [j for it in items for j in self._build_jobs(it)]
        self.tracker = ProgressTracker(len(jobs))
        self.skipped = []
        failed = []
        outs = sorted({it["spec"]["out_dir"] for it in items})
        for o in outs:
            self._cleanup_orphans(o)
        url = items[0]["url"] if items else ""
        try:
            for i, job in enumerate(jobs, 1):
                if self.cancel:
                    raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario")
                self.cur_spec = job.spec
                label = job.label if len(items) == 1 else f"{short_title(job.item.get('title'))} · {job.label}"
                self.tracker.start_job(i, label)
                self.q.put(("progress", self.tracker.last, f"[{i}/{len(jobs)}] Iniciando {label}…"))
                try:
                    self._run_job(job.opts, job.item["url"], job.item["info"], job.item["analyzed_at"], job.ext)
                except yt_dlp.utils.DownloadCancelled:
                    raise
                except Exception as e:  # noqa: BLE001
                    if self.cancel:
                        raise yt_dlp.utils.DownloadCancelled("Cancelado por el usuario") from None
                    log.exception("Falló el trabajo %s de %s", label, job.item["url"])
                    self.last_error = f"Trabajo {label} de {job.item['url']}\n{traceback.format_exc()}"
                    failed.append(f"{label}: {str(e)[:120]}")
            msg = "✔ Descarga completada en: " + ", ".join(outs)
            if self.skipped:
                msg += "\nYa existían: " + ", ".join(self.skipped)
            if failed:
                msg += "\nFallaron: " + "; ".join(failed)
            self.q.put(("done", msg, not failed))
        except yt_dlp.utils.DownloadCancelled:
            self.q.put(("done", "Descarga cancelada.", False))
        except Exception as e:  # noqa: BLE001
            log.exception("Error en la descarga")
            self.last_error = f"Descarga de {url}\n{traceback.format_exc()}"
            self.q.put(("done", f"Error: {e}", False))
        finally:
            self.tracker = None

    # ---------- Motor yt-dlp en segundo plano ----------
    def _engine_update_worker(self):
        try:
            v = updater.background_ytdlp_update()
            if v:
                self.q.put(("engine", v))
        except Exception:  # noqa: BLE001
            log.warning("Fallo al actualizar el motor", exc_info=True)

    # ---------- Actualización de la app ----------
    def _check_update_worker(self):
        try:
            upd = updater.check_app_update()
            if upd:
                self.q.put(("app_update", upd))
        except Exception:  # noqa: BLE001
            pass  # sin internet: se ignora en silencio

    def _show_update_dialog(self, upd):
        dlg = tk.Toplevel(self, bg=PANEL)
        dlg.title("Actualización disponible")
        dlg.resizable(False, False)
        dlg.transient(self)
        try:
            dlg.iconbitmap(os.path.join(_RES_DIR, "icon.ico"))
        except Exception:  # noqa: BLE001
            pass
        w, h = self.px(460), self.px(330)
        x = self.winfo_rootx() + (self.winfo_width() - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        box = tk.Frame(dlg, bg=PANEL)
        box.pack(fill="both", expand=True, padx=24, pady=20)
        self._label(box, "¡Hay una nueva versión!", 15, True, CORAL, PANEL).pack(anchor="w")
        self._label(box, f"Versión instalada: {updater.VERSION}      Nueva: {upd['version']}", 10, False,
                    CORAL_SOFT, PANEL).pack(anchor="w", pady=(4, 10))
        notes = tk.Text(box, height=7, bg=FIELD, fg=CORAL, relief="flat", font=(FONT, 9), wrap="word",
                        highlightthickness=0, padx=8, pady=8)
        notes.insert("1.0", upd["notes"] or "Mejoras y correcciones.")
        notes.config(state="disabled")
        notes.pack(fill="x")
        bar = ttk.Progressbar(box, maximum=100, style="Coral.Horizontal.TProgressbar")
        msg = tk.StringVar(value="La app se cerrará y se reabrirá sola al terminar.")
        tk.Label(box, textvariable=msg, bg=PANEL, fg=CORAL_SOFT, font=(FONT, 9)).pack(anchor="w", pady=(10, 0))
        row = tk.Frame(box, bg=PANEL)
        row.pack(side="bottom", fill="x")
        bar.pack(side="bottom", fill="x", pady=(0, 10))

        def start():
            btn_ok.config(state="disabled")
            btn_later.config(state="disabled")
            msg.set("Descargando actualización…")

            def work():
                try:
                    path = updater.download_installer(upd, lambda p: self.q.put(("upd_progress", bar, p)))
                    self.q.put(("upd_run", path))
                except Exception as e:  # noqa: BLE001
                    self.q.put(("upd_fail", dlg, msg, btn_ok, btn_later, str(e)))
            threading.Thread(target=work, daemon=True).start()

        btn_ok = tk.Button(row, text="Actualizar ahora", command=start, relief="flat", bd=0, cursor="hand2",
                           font=(FONT, 11, "bold"), bg=CORAL, fg=BG, activebackground=CORAL_SOFT,
                           activeforeground=BG, disabledforeground="#6b4757", padx=16, pady=9)
        btn_ok.pack(side="left", fill="x", expand=True)
        btn_later = self._btn(row, "Más tarde", dlg.destroy)
        btn_later.config(pady=11)
        btn_later.pack(side="left", padx=(8, 0))
        dlg.grab_set()

    # ---------- Cola de eventos ----------
    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "analyzed":
                    self._apply_info(*msg[1:])
                    self.busy = False
                    self.btn_an.config(state="normal")
                    self._set_dl(self._url_matches())
                elif kind == "engine":
                    self.engine_lbl.config(text="Motor actualizado (se aplica al reiniciar)")
                elif kind == "app_update":
                    self._show_update_dialog(msg[1])
                elif kind == "upd_progress":
                    msg[1]["value"] = msg[2]
                elif kind == "upd_run":
                    updater.run_installer(msg[1])
                    self.destroy()
                    return
                elif kind == "upd_fail":
                    _, dlg, m, b1, b2, err = msg
                    m.set("No se pudo actualizar: " + err[:120])
                    b1.config(state="normal", text="Reintentar")
                    b2.config(state="normal")
                elif kind == "error":
                    self.busy = False
                    self.btn_an.config(state="normal")
                    self.status.set("Error: " + msg[1][:300])
                elif kind == "progress":
                    self.bar["value"] = msg[1]
                    self.status.set(msg[2])
                elif kind == "status":
                    self.status.set(msg[1])
                elif kind == "msgbox":
                    messagebox.showinfo(msg[1], msg[2])
                elif kind == "done":
                    self.busy = False
                    self.bar["value"] = 0
                    self.btn_an.config(state="normal")
                    self._set_dl(self._url_matches())
                    self.btn_cancel.config(state="disabled")
                    self.status.set(msg[1])
                    self._show_result_buttons(msg[2], bool(self.last_error))
        except queue.Empty:
            pass
        self.after(100, self._poll)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":  # diagnóstico: escribe info a un archivo y sale
        import yt_dlp.extractor.youtube as _yt
        try:
            import yt_dlp_ejs
            _ejs = yt_dlp_ejs.version
        except Exception:  # noqa: BLE001
            _ejs = "NO DISPONIBLE"
        with open(sys.argv[2], "w", encoding="utf-8") as _f:
            _f.writelines(line + "\n" for line in (
                f"app={updater.VERSION}", f"yt_dlp={yt_dlp.version.__version__}", f"file={yt_dlp.__file__}",
                f"extractor={_yt.__file__}", f"yt_dlp_ejs={_ejs}",
                f"js_runtime={list(find_js_runtimes()) or 'NINGUNO'}", f"ffmpeg={shutil.which('ffmpeg')}"))
        sys.exit(0)
    enable_dpi_awareness()
    setup_logging()
    App().mainloop()
