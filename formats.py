"""Formatos de salida y opciones de descarga: constantes, selector de formato de yt-dlp, filtros de ffmpeg,
recorte de tramos y escala. Sin interfaz ni E/S: es la parte más fácil de probar."""
import re

import yt_dlp

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
H264_CPU = ("H.264 + AAC", ".mp4", ["-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p"],
            _AAC, ["-movflags", "+faststart"])
INTRA_KINDS = ("prores", "prores_std", "dnxhr", "hap", "hapq")  # formatos de edición: la nota VP9/AV1 aplica a estos
_HEVC_EXTRA = ["-movflags", "+faststart"]
# kind -> [(encoder, argumentos de video)] por orden de preferencia. Solo se ofrecen si ffmpeg los lista Y una
# codificación de prueba de 1 s con ESTOS MISMOS argumentos funciona.
GPU_TABLE = {
    "h264_gpu": [
        ("h264_nvenc", ["-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", "0",
                        "-pix_fmt", "yuv420p"]),
        ("h264_qsv", ["-c:v", "h264_qsv", "-global_quality", "20", "-pix_fmt", "nv12"]),
        ("h264_amf", ["-c:v", "h264_amf", "-rc", "cqp", "-qp_i", "20", "-qp_p", "20", "-quality", "quality",
                      "-pix_fmt", "yuv420p"]),
    ],
    "h265_gpu": [
        ("hevc_nvenc", ["-c:v", "hevc_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "22", "-b:v", "0",
                        "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]),
        ("hevc_qsv", ["-c:v", "hevc_qsv", "-global_quality", "23", "-pix_fmt", "nv12", "-tag:v", "hvc1"]),
        ("hevc_amf", ["-c:v", "hevc_amf", "-rc", "cqp", "-qp_i", "23", "-qp_p", "23", "-quality", "quality",
                      "-pix_fmt", "yuv420p", "-tag:v", "hvc1"]),
    ],
}
GPU_FALLBACK = {"h264_gpu": "h264", "h265_gpu": "h265"}  # si la GPU falla se reintenta con CPU
_GPU_VENDOR = {"nvenc": "NVIDIA NVENC", "qsv": "Intel QSV", "amf": "AMD AMF"}
_GPU_LABEL = {"h264_gpu": "H.264 + AAC (GPU {v}, MP4 rápido)", "h265_gpu": "H.265 / HEVC + AAC (GPU {v}, MP4 rápido)"}


def register_gpu_formats(gpu: dict) -> list[str]:
    """Añade a OUT_FORMATS/RECODE_SPECS las opciones por GPU detectadas. Devuelve las etiquetas nuevas."""
    added = []
    for kind, enc in gpu.items():
        args = dict(GPU_TABLE.get(kind, [])).get(enc)
        if not args:
            continue
        vendor = _GPU_VENDOR[enc.rsplit("_", 1)[1]]
        label = _GPU_LABEL[kind].format(v=vendor)
        RECODE_SPECS[kind] = (label.split(" (")[0] + f" ({vendor})", ".mp4", list(args), _AAC, list(_HEVC_EXTRA))
        if kind not in OUT_FORMATS.values():
            OUT_FORMATS[label] = kind
            added.append(label)
    return added


PLAYLIST_HEIGHTS = [2160, 1440, 1080, 720, 480, 360, 240, 144]


def final_ext(kind: str) -> str:
    """Extensión del archivo de video una vez convertido al formato de salida."""
    return RECODE_SPECS[kind][1] if kind in RECODE_SPECS else ".mp4"


AUDIO_FORMATS = {  # nombre -> (códec de yt-dlp, extensión, ¿admite calidad en kbps?)
    "MP3": ("mp3", ".mp3", True), "M4A": ("m4a", ".m4a", True), "Opus": ("opus", ".opus", True),
    "WAV": ("wav", ".wav", False), "FLAC": ("flac", ".flac", False),
}
AUDIO_QUALITIES = ["320", "256", "192", "128"]
SUBS_MODES = ["Incrustar (MP4)", "Guardar .srt"]


def parse_langs(text: str) -> list[str]:
    """'es, en' -> ['es', 'en']. Descarta basura; si no queda nada, usa es,en."""
    langs = [x for x in re.split(r"[,\s;]+", text or "") if re.fullmatch(r"[A-Za-z0-9*_.-]{1,20}", x)]
    return langs or ["es", "en"]


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


def audio_template(is_playlist: bool, tag: str = "") -> str:
    name = f"%(title)s{tag}.%(ext)s"
    return "%(playlist_title)s/%(playlist_index)03d - " + name if is_playlist else name


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


SCALE_PRESETS = ["Sin cambios", "1920x1080", "3840x2160", "1280x720", "Personalizada"]
SCALE_MODES = {"Ajustar con barras": "fit", "Rellenar recortando": "fill", "Estirar": "stretch"}
FPS_CHOICES = ["Máximo", "30", "60"]


def parse_time(text: str | None) -> float | None:
    """'' -> None; 'mm:ss' o 'hh:mm:ss' (segundos con decimales opcionales) -> segundos. ValueError si es inválido."""
    t = (text or "").strip()
    if not t:
        return None
    parts = t.split(":")
    ok = 2 <= len(parts) <= 3 and all(re.fullmatch(r"\d{1,3}", p) for p in parts[:-1]) \
        and re.fullmatch(r"\d{1,2}(?:\.\d+)?", parts[-1])
    if not ok:
        raise ValueError(f"Tiempo no válido: «{t}». Usa mm:ss u hh:mm:ss (p. ej. 1:30 o 0:01:30).")
    nums = [float(p) for p in parts]
    if nums[-1] >= 60 or (len(parts) == 3 and nums[1] >= 60):
        raise ValueError(f"Tiempo no válido: «{t}». Minutos y segundos deben ser menores que 60.")
    h = nums[0] if len(parts) == 3 else 0.0
    return h * 3600 + nums[-2] * 60 + nums[-1]


def validate_trim(start_text: str, end_text: str, duration: float | None = None, exact: bool = False) -> dict | None:
    """Tramo a descargar: None si Inicio y Fin están vacíos; ValueError si no son coherentes."""
    start, end = parse_time(start_text), parse_time(end_text)
    if start is None and end is None:
        return None
    if end is not None and end <= (start or 0):
        raise ValueError("El Fin del tramo debe ser posterior al Inicio.")
    if duration and start is not None and start >= duration:
        raise ValueError("El Inicio del tramo está después del final del video.")
    return {"start": start, "end": end, "exact": bool(exact)}


def _tstr(sec: float | None, default: str) -> str:
    if sec is None:
        return default
    s = int(sec)
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m:02d}m{s:02d}s"


def range_tag(trim: dict | None) -> str:
    """Etiqueta para el nombre del archivo: ' [00m10s-00m20s]' (vacía si no hay tramo)."""
    if not trim:
        return ""
    return f" [{_tstr(trim['start'] or 0, '00m00s')}-{_tstr(trim['end'], 'fin')}]"


def variant_tag(spec: dict) -> str:
    """Sufijo del nombre de archivo que distingue variantes del mismo video: tramo, escala y FPS."""
    tag = range_tag(spec.get("trim"))
    sc = spec.get("scale")
    if sc:
        tag += f" [{sc['w']}x{sc['h']}" + {"fill": " recorte", "stretch": " estirado"}.get(sc["mode"], "") + "]"
    if spec.get("fps"):
        tag += f" [{spec['fps']}fps]"
    return tag


def trim_options(trim: dict | None) -> dict:
    """Opciones de yt-dlp para descargar solo un tramo (corte exacto = re-codifica en los cortes)."""
    if not trim:
        return {}
    ranges = [(trim["start"] or 0, trim["end"] or float("inf"))]
    return {"download_ranges": yt_dlp.utils.download_range_func(None, ranges),
            "force_keyframes_at_cuts": bool(trim["exact"])}


def parse_resolution(text: str) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{2,5})\s*[xX×]\s*(\d{2,5})\s*", text or "")
    if not m or not all(16 <= int(g) <= 8192 for g in m.groups()):
        raise ValueError(f"Resolución no válida: «{text}». Usa AxB, p. ej. 1920x1080 (16 a 8192).")
    return int(m[1]), int(m[2])


def resolve_scale(preset: str, custom: str, mode_label: str, kind: str) -> tuple[dict | None, list[str]]:
    """Resolución de salida elegida -> ({'w','h','mode'} | None, avisos). HAP exige múltiplos de 4; el resto, pares."""
    if preset == "Sin cambios":
        return None, []
    w, h = parse_resolution(custom if preset == "Personalizada" else preset)
    step = 4 if kind in ("hap", "hapq") else 2
    w2, h2 = -(-w // step) * step, -(-h // step) * step
    notes = []
    if (w2, h2) != (w, h):
        notes.append(f"Resolución ajustada a {w2}x{h2} (múltiplo de {step}" + (" para HAP)." if step == 4 else ")."))
    return {"w": w2, "h": h2, "mode": SCALE_MODES.get(mode_label, "fit")}, notes


def scale_filter(w: int, h: int, mode: str) -> str:
    """Filtro de ffmpeg para llevar el video a w×h: 'fit' (barras), 'fill' (recorta) o 'stretch' (estira)."""
    if mode == "fill":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,crop={w}:{h},setsar=1"
    if mode == "stretch":
        return f"scale={w}:{h}:flags=lanczos,setsar=1"
    return (f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1")


def build_video_filter(spec: dict) -> str:
    """Cadena -vf de ffmpeg para el trabajo ('' si no hace falta). HAP sin escala recorta a múltiplos de 4."""
    sc = spec.get("scale")
    if sc:
        return scale_filter(sc["w"], sc["h"], sc["mode"])
    if spec.get("kind") in ("hap", "hapq"):
        return "crop=trunc(iw/4)*4:trunc(ih/4)*4"
    return ""


COOKIE_BROWSERS = ["Ninguno", "Firefox", "Chrome", "Edge", "Brave"]
