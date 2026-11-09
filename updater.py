"""Actualizaciones automáticas.

1. yt-dlp: en segundo plano se consulta PyPI y la versión nueva se deja en `yt-dlp.next`;
   en el siguiente arranque (antes de importar yt_dlp) pasa a ser la activa.
2. La propia app: se consulta la última Release de GitHub y, si es más nueva y trae su
   SHA-256, se descarga el instalador y se ejecuta en modo silencioso.
"""
import hashlib
import importlib.machinery
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import zipfile

VERSION = "1.2.0"
REPO = "Cheivancho/descargador-youtube"

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DescargadorYouTube")
YTDLP_DIR = os.path.join(DATA_DIR, "yt-dlp")
YTDLP_NEXT = os.path.join(DATA_DIR, "yt-dlp.next")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
YTDLP_CHECK_EVERY = 6 * 3600  # segundos
YTDLP_RETRY_EVERY = 3600  # tras un fallo se reintenta antes
HEADERS = {"User-Agent": f"DescargadorYouTube/{VERSION}"}
SETUP_NAME = "DescargadorYouTube-Setup.exe"

log = logging.getLogger("descargador")


def parse_version(v: str | None) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _get(url: str, timeout: float = 6):
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=timeout)


# ---------------------------------------------------------------- state.json
_state_lock = threading.Lock()


def load_state() -> dict:
    """Lee state.json. Si no existe, está corrupto o no es un objeto JSON, devuelve {}."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            st = json.load(f)
        return st if isinstance(st, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def save_state(st: dict) -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(st, f)
        os.replace(tmp, STATE_FILE)
    except Exception:  # noqa: BLE001
        pass


def update_state(**changes) -> None:
    """Lee-modifica-escribe state.json de forma segura entre hilos."""
    with _state_lock:
        st = load_state()
        st.update(changes)
        save_state(st)


# ---------------------------------------------------------------- yt-dlp
class _YtdlpFinder:
    """Redirige 'yt_dlp' (y yt_dlp_ejs) a la carpeta actualizada, aun en un .exe congelado.

    Debe quedar instalado durante toda la sesión: yt-dlp importa extractores bajo demanda.
    """

    @classmethod
    def find_spec(cls, name, path=None, target=None):
        if name in ("yt_dlp", "yt_dlp_ejs") or name.startswith(("yt_dlp.", "yt_dlp_ejs.")):
            return importlib.machinery.PathFinder.find_spec(name, path, target)
        return None


def _dist_version(dist: str) -> str | None:
    try:
        from importlib.metadata import version
        return version(dist)
    except Exception:  # noqa: BLE001
        return None


def _bundled_ytdlp_version() -> str | None:
    return _dist_version("yt-dlp")


def _bundled_ejs_version() -> str | None:
    return _dist_version("yt-dlp-ejs")


def _read_version(folder: str) -> str | None:
    try:
        with open(os.path.join(folder, "version.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return None


def installed_update_version() -> str | None:
    return _read_version(YTDLP_DIR)


def pending_update_version() -> str | None:
    return _read_version(YTDLP_NEXT)


def _safe_extract(zf: zipfile.ZipFile, prefixes: tuple, dest: str) -> None:
    """Extrae solo los miembros bajo 'prefixes', rechazando rutas que escapen de 'dest'."""
    root = os.path.realpath(dest)
    for m in zf.namelist():
        if not m.startswith(prefixes) or m.endswith("/"):
            continue
        target = os.path.realpath(os.path.join(dest, *m.split("/")))
        if ".." in m.split("/") or "\\" in m or os.path.commonpath([root, target]) != root:
            raise ValueError(f"Ruta no permitida en el wheel: {m}")
        zf.extract(m, dest)


def _fetch_wheel(meta: dict) -> bytes:
    wheel = next(u for u in meta["urls"] if u["packagetype"] == "bdist_wheel")
    with _get(wheel["url"], 60) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != wheel["digests"]["sha256"]:
        raise ValueError("Hash del wheel no coincide")
    return data


def required_ejs_version(wheel_bytes: bytes) -> str | None:
    """Versión exacta de yt-dlp-ejs que pide el wheel de yt-dlp (Requires-Dist), o None."""
    with zipfile.ZipFile(io.BytesIO(wheel_bytes)) as z:
        name = next((n for n in z.namelist() if n.endswith(".dist-info/METADATA")), None)
        text = z.read(name).decode("utf-8", "replace") if name else ""
    m = re.search(r"^Requires-Dist: yt-dlp-ejs==([\w.]+);.*extra == 'default'", text, re.M)
    return m.group(1) if m else None


def download_ytdlp_next() -> str | None:
    """Descarga el yt-dlp más reciente a 'yt-dlp.next' (NO toca el activo). Devuelve la versión o None."""
    with _get("https://pypi.org/pypi/yt-dlp/json", 8) as r:
        meta = json.load(r)
    latest = meta["info"]["version"]
    current = pending_update_version() or installed_update_version() or _bundled_ytdlp_version()
    if current and parse_version(latest) <= parse_version(current):
        return None
    data = _fetch_wheel(meta)
    ejs_wanted = required_ejs_version(data)
    tmp = YTDLP_NEXT + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            _safe_extract(z, ("yt_dlp/",), tmp)
        if ejs_wanted and ejs_wanted != _bundled_ejs_version():
            # yt-dlp fija una versión exacta de yt-dlp-ejs: se trae la misma que pide el wheel nuevo
            with _get(f"https://pypi.org/pypi/yt-dlp-ejs/{ejs_wanted}/json", 8) as r:
                ejs_meta = json.load(r)
            with zipfile.ZipFile(io.BytesIO(_fetch_wheel(ejs_meta))) as z:
                _safe_extract(z, ("yt_dlp_ejs/",), tmp)
        with open(os.path.join(tmp, "version.txt"), "w", encoding="utf-8") as f:
            f.write(latest)
        shutil.rmtree(YTDLP_NEXT, ignore_errors=True)
        os.replace(tmp, YTDLP_NEXT)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return latest


def background_ytdlp_update(force: bool = False) -> str | None:
    """Consulta PyPI y deja la versión nueva en 'yt-dlp.next' (se aplica al próximo arranque).

    Pensada para un hilo en segundo plano. Guarda siempre 'ytdlp_last_check'; si falla, el
    reintento llega antes (YTDLP_RETRY_EVERY). Devuelve la versión descargada o None.
    """
    st = load_state()
    every = YTDLP_CHECK_EVERY if st.get("ytdlp_last_ok", True) else YTDLP_RETRY_EVERY
    if not force and time.time() - st.get("ytdlp_last_check", 0) < every:
        return None
    try:
        v = download_ytdlp_next()
        update_state(ytdlp_last_check=time.time(), ytdlp_last_ok=True)
        return v
    except Exception:  # noqa: BLE001
        log.warning("No se pudo comprobar/descargar yt-dlp", exc_info=True)
        update_state(ytdlp_last_check=time.time(), ytdlp_last_ok=False)
        return None


def apply_pending_ytdlp() -> None:
    """Operación local y rápida (sin red): si hay 'yt-dlp.next', pasa a ser el yt-dlp activo."""
    try:
        if os.path.isfile(os.path.join(YTDLP_NEXT, "version.txt")):
            shutil.rmtree(YTDLP_DIR, ignore_errors=True)
            os.replace(YTDLP_NEXT, YTDLP_DIR)
    except Exception:  # noqa: BLE001
        log.warning("No se pudo aplicar la actualización pendiente de yt-dlp", exc_info=True)


def reset_ytdlp_engine() -> None:
    """Borra el motor descargado (y el pendiente); se vuelve al incluido en la app al reiniciar."""
    for d in (YTDLP_DIR, YTDLP_NEXT, YTDLP_NEXT + ".tmp"):
        shutil.rmtree(d, ignore_errors=True)
    update_state(ytdlp_last_check=0)


def prepare_ytdlp() -> None:
    """Llamar ANTES de 'import yt_dlp'. Solo trabajo local: aplica lo ya descargado y activa la copia."""
    try:
        apply_pending_ytdlp()
        upd = installed_update_version()
        bundled = _bundled_ytdlp_version()
        if upd and os.path.isdir(os.path.join(YTDLP_DIR, "yt_dlp")) and \
                (not bundled or parse_version(upd) > parse_version(bundled)):
            sys.path.insert(0, YTDLP_DIR)
            sys.meta_path.insert(0, _YtdlpFinder)
            try:
                import yt_dlp  # noqa: F401
            except Exception:  # noqa: BLE001
                for m in [m for m in sys.modules if m.split(".")[0] in ("yt_dlp", "yt_dlp_ejs")]:
                    del sys.modules[m]
                sys.meta_path.remove(_YtdlpFinder)
                sys.path.remove(YTDLP_DIR)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- la app
_HEX64 = re.compile(r"\b[0-9a-fA-F]{64}\b")


def _asset_sha256(asset: dict, assets: list) -> str | None:
    """SHA-256 del instalador: primero el campo 'digest' del asset; si no, el asset '.sha256'."""
    digest = asset.get("digest") or ""
    if digest.lower().startswith("sha256:") and _HEX64.fullmatch(digest.split(":", 1)[1]):
        return digest.split(":", 1)[1].lower()
    want = (asset["name"] + ".sha256").lower()
    side = next((a for a in assets if a.get("name", "").lower() == want), None)
    if side:
        try:
            with _get(side["browser_download_url"], 8) as r:
                m = _HEX64.search(r.read(4096).decode("utf-8", "replace"))
            if m:
                return m.group(0).lower()
        except Exception:  # noqa: BLE001
            log.warning("No se pudo leer %s", side.get("name"), exc_info=True)
    return None


def check_app_update() -> dict | None:
    """Devuelve dict(version, notes, url, size, sha256) si hay una versión nueva con hash; si no, None.

    Una versión nueva SIN SHA-256 disponible se rechaza (no se ofrece ni se ejecuta).
    """
    with _get(f"https://api.github.com/repos/{REPO}/releases/latest", 8) as r:
        rel = json.load(r)
    tag = rel.get("tag_name", "")
    if parse_version(tag) <= parse_version(VERSION):
        return None
    assets = rel.get("assets", [])
    asset = next((a for a in assets if a["name"].lower().endswith("setup.exe")), None)
    if not asset:
        return None
    sha = _asset_sha256(asset, assets)
    if not sha:
        log.warning("La versión %s no publica SHA-256: actualización rechazada", tag)
        return None
    return {"version": tag.lstrip("v"), "notes": (rel.get("body") or "").strip(),
            "url": asset["browser_download_url"], "size": asset.get("size", 0), "sha256": sha}


def download_installer(update: dict, progress=None) -> str:
    """Descarga el instalador y verifica su SHA-256. Sin hash o con hash distinto, no devuelve ruta."""
    if not update.get("sha256"):
        raise ValueError("Actualización rechazada: no hay SHA-256 con el que verificar el instalador.")
    d = tempfile.mkdtemp(prefix="DescargadorYouTube-update-")
    path = os.path.join(d, SETUP_NAME)
    h = hashlib.sha256()
    with _get(update["url"], 30) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or update.get("size") or 0)
        done = 0
        while True:
            chunk = r.read(256 * 1024)
            if not chunk:
                break
            f.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if progress and total:
                progress(done * 100 / total)
    if h.hexdigest().lower() != update["sha256"].lower():
        shutil.rmtree(d, ignore_errors=True)
        raise ValueError("El instalador descargado está dañado (hash incorrecto).")
    return path


def run_installer(path: str) -> None:
    """Lanza el instalador en modo silencioso (con barra de progreso) y debe cerrarse la app."""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)
