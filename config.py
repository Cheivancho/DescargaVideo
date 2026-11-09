"""Rutas, ajustes (state.json), presets (presets.json) y log."""
import json
import logging
import logging.handlers
import os
import re
import sys

import updater
from formats import (
    AUDIO_FORMATS,
    AUDIO_QUALITIES,
    COOKIE_BROWSERS,
    FPS_CHOICES,
    OUT_FORMATS,
    SCALE_MODES,
    SCALE_PRESETS,
    SUBS_MODES,
)

log = logging.getLogger("descargador")

# Carpeta del ejecutable (o del código) y de los recursos empaquetados por PyInstaller
APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
RES_DIR = getattr(sys, "_MEIPASS", APP_DIR)


def setup_environment() -> None:
    """Permite usar el ffmpeg.exe (y deno.exe) que estén junto al ejecutable."""
    os.environ["PATH"] = APP_DIR + os.pathsep + os.environ.get("PATH", "")


DEFAULT_SETTINGS = {
    "out_dir": os.path.join(os.path.expanduser("~"), "Videos", "YouTube"),
    "fmt": "h264", "audio": False, "preset": "", "geometry": "",
    "audio_fmt": "MP3", "audio_q": "320", "subs": False, "subs_langs": "es,en", "subs_mode": SUBS_MODES[0],
    "embed": False, "fps": FPS_CHOICES[0], "scale_preset": SCALE_PRESETS[0], "scale_custom": "1920x1080",
    "scale_mode": next(iter(SCALE_MODES)), "cookies": COOKIE_BROWSERS[0],
}


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
    if s["fps"] not in FPS_CHOICES:
        s["fps"] = FPS_CHOICES[0]
    if s["scale_preset"] not in SCALE_PRESETS:
        s["scale_preset"] = SCALE_PRESETS[0]
    if s["scale_mode"] not in SCALE_MODES:
        s["scale_mode"] = next(iter(SCALE_MODES))
    if s["cookies"] not in COOKIE_BROWSERS:
        s["cookies"] = COOKIE_BROWSERS[0]
    return s


PRESETS_FILE = os.path.join(updater.DATA_DIR, "presets.json")
PRESET_KEYS = ("fmt", "audio", "audio_fmt", "audio_q", "subs", "subs_langs", "subs_mode", "embed", "fps",
               "scale_preset", "scale_custom", "scale_mode")
FACTORY_PRESETS = {  # de solo lectura; el recorte nunca se guarda en un preset
    "Resolume 1080p (HAP)": {"heights": [1080], "fmt": "hap", "scale_preset": "1920x1080",
                             "scale_mode": "Ajustar con barras"},
    "Premiere 1080p (ProRes 422)": {"heights": [1080], "fmt": "prores_std"},
    "Web ligero 720p (H.264)": {"heights": [720], "fmt": "h264", "fps": "30"},
    "Solo audio MP3 320": {"heights": [], "audio": True, "audio_fmt": "MP3", "audio_q": "320"},
}


def normalize_preset(raw: dict) -> dict:
    """Preset válido y completo a partir de un dict posiblemente viejo, incompleto o con tipos erróneos."""
    raw = raw if isinstance(raw, dict) else {}
    s = load_settings({"settings": {k: raw[k] for k in PRESET_KEYS if k in raw}})
    out = {k: s[k] for k in PRESET_KEYS}
    h = raw.get("heights")
    out["heights"] = sorted({x for x in h if isinstance(x, int) and not isinstance(x, bool) and 0 < x < 10000},
                            reverse=True) if isinstance(h, list) else []
    return out


def load_presets() -> dict:
    """Presets del usuario (presets.json). Un archivo ausente o corrupto equivale a no tener presets."""
    try:
        with open(PRESETS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): normalize_preset(v) for k, v in raw.items() if isinstance(v, dict) and str(k).strip()}


def save_presets(presets: dict) -> None:
    os.makedirs(os.path.dirname(PRESETS_FILE), exist_ok=True)
    tmp = PRESETS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(presets, f, ensure_ascii=False, indent=2)
    os.replace(tmp, PRESETS_FILE)


def pick_heights(available: list[int], wanted: list[int]) -> list[int]:
    """Resoluciones disponibles que mejor cubren las pedidas (la pedida, o la mayor menor que ella, o la menor)."""
    chosen = set()
    for w in wanted:
        if w in available:
            chosen.add(w)
        else:
            lower = [a for a in available if a <= w]
            if lower or available:
                chosen.add(max(lower) if lower else min(available))
    return sorted(chosen, reverse=True)


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
