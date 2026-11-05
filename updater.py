"""Actualizaciones automáticas.

1. yt-dlp: al iniciar, si hay una versión nueva en PyPI se descarga a una carpeta
   del usuario y se usa en lugar de la que viene empaquetada en el .exe.
2. La propia app: se consulta la última Release de GitHub y, si es más nueva,
   se descarga el instalador y se ejecuta en modo silencioso.
"""
import hashlib
import importlib.machinery
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

VERSION = "1.1.0"
REPO = "Cheivancho/descargador-youtube"

DATA_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "DescargadorYouTube")
YTDLP_DIR = os.path.join(DATA_DIR, "yt-dlp")
STATE_FILE = os.path.join(DATA_DIR, "state.json")
YTDLP_CHECK_EVERY = 6 * 3600  # segundos
HEADERS = {"User-Agent": f"DescargadorYouTube/{VERSION}"}


def parse_version(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or ""))


def _get(url, timeout=6):
    req = urllib.request.Request(url, headers=HEADERS)
    return urllib.request.urlopen(req, timeout=timeout)


def _load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_state(st):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(st, f)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- yt-dlp
class _YtdlpFinder:
    """Redirige 'yt_dlp' y sus submódulos a la carpeta actualizada, aun en un .exe congelado.

    Debe quedar instalado durante toda la sesión: yt-dlp importa extractores bajo demanda.
    """

    @classmethod
    def find_spec(cls, name, path=None, target=None):
        if name == "yt_dlp" or name.startswith("yt_dlp."):
            return importlib.machinery.PathFinder.find_spec(name, path, target)
        return None


def _bundled_ytdlp_version():
    try:
        from importlib.metadata import version
        return version("yt-dlp")
    except Exception:  # noqa: BLE001
        return None


def _installed_update_version():
    try:
        with open(os.path.join(YTDLP_DIR, "version.txt"), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:  # noqa: BLE001
        return None


def _download_ytdlp():
    """Descarga el wheel más reciente de yt-dlp desde PyPI. Devuelve la versión o None."""
    with _get("https://pypi.org/pypi/yt-dlp/json", 8) as r:
        meta = json.load(r)
    latest = meta["info"]["version"]
    current = _installed_update_version() or _bundled_ytdlp_version()
    if current and parse_version(latest) <= parse_version(current):
        return None
    wheel = next(u for u in meta["urls"] if u["packagetype"] == "bdist_wheel")
    with _get(wheel["url"], 60) as r:
        data = r.read()
    if hashlib.sha256(data).hexdigest() != wheel["digests"]["sha256"]:
        raise ValueError("Hash del wheel de yt-dlp no coincide")
    tmp = YTDLP_DIR + ".tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    os.makedirs(tmp)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for m in z.namelist():
            if m.startswith("yt_dlp/") and ".." not in m.split("/"):
                z.extract(m, tmp)
    with open(os.path.join(tmp, "version.txt"), "w", encoding="utf-8") as f:
        f.write(latest)
    shutil.rmtree(YTDLP_DIR, ignore_errors=True)
    os.replace(tmp, YTDLP_DIR)
    return latest


def prepare_ytdlp():
    """Llamar ANTES de 'import yt_dlp'. Actualiza si hace falta y prioriza la copia nueva."""
    try:
        st = _load_state()
        if time.time() - st.get("ytdlp_last_check", 0) > YTDLP_CHECK_EVERY:
            try:
                _download_ytdlp()
                st["ytdlp_last_check"] = time.time()
                _save_state(st)
            except Exception:  # noqa: BLE001
                pass  # sin internet u otro fallo: se usa lo que haya
        upd = _installed_update_version()
        bundled = _bundled_ytdlp_version()
        if upd and os.path.isdir(os.path.join(YTDLP_DIR, "yt_dlp")) and \
                (not bundled or parse_version(upd) > parse_version(bundled)):
            sys.path.insert(0, YTDLP_DIR)
            sys.meta_path.insert(0, _YtdlpFinder)
            try:
                import yt_dlp  # noqa: F401
            except Exception:  # noqa: BLE001
                for m in [m for m in sys.modules if m == "yt_dlp" or m.startswith("yt_dlp.")]:
                    del sys.modules[m]
                sys.meta_path.remove(_YtdlpFinder)
                sys.path.remove(YTDLP_DIR)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- la app
def check_app_update():
    """Devuelve dict(version, notes, url, size, sha256) si hay una versión nueva; si no, None."""
    with _get(f"https://api.github.com/repos/{REPO}/releases/latest", 8) as r:
        rel = json.load(r)
    tag = rel.get("tag_name", "")
    if parse_version(tag) <= parse_version(VERSION):
        return None
    asset = next((a for a in rel.get("assets", []) if a["name"].lower().endswith("setup.exe")), None)
    if not asset:
        return None
    digest = (asset.get("digest") or "")
    return {"version": tag.lstrip("v"), "notes": (rel.get("body") or "").strip(),
            "url": asset["browser_download_url"], "size": asset.get("size", 0),
            "sha256": digest.split(":", 1)[1] if digest.startswith("sha256:") else None}


def download_installer(update, progress=None):
    """Descarga el instalador a una carpeta temporal y devuelve su ruta."""
    d = tempfile.mkdtemp(prefix="DescargadorYouTube-update-")
    path = os.path.join(d, "DescargadorYouTube-Setup.exe")
    h = hashlib.sha256()
    with _get(update["url"], 30) as r, open(path, "wb") as f:
        total = int(r.headers.get("Content-Length") or update["size"] or 0)
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
    if update.get("sha256") and h.hexdigest().lower() != update["sha256"].lower():
        raise ValueError("El instalador descargado está dañado (hash incorrecto).")
    return path


def run_installer(path):
    """Lanza el instalador en modo silencioso (con barra de progreso) y debe cerrarse la app."""
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen([path, "/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"],
                     creationflags=flags, close_fds=True)
