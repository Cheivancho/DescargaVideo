"""Descargador de YouTube con interfaz oscura (tkinter + yt-dlp).

- Detecta todas las resoluciones realmente disponibles del video.
- Descarga una, varias o todas; soporta playlists, audio, subtítulos, recortes, escala y conversión a ProRes/HAP/etc.
- Panel derecho con miniatura y características del video.
Requiere: yt-dlp, Pillow y ffmpeg (en el PATH o junto al ejecutable).

Este archivo es el punto de entrada (PyInstaller y --selftest); la lógica está en config, formats, convert,
downloader, util, ui y updater.
"""
import shutil
import sys

import updater

updater.prepare_ytdlp()  # solo aplica lo ya descargado (local, sin red); debe ir antes de importar yt_dlp

import yt_dlp  # noqa: E402

from config import setup_environment, setup_logging  # noqa: E402
from downloader import find_js_runtimes  # noqa: E402
from ui import App, enable_dpi_awareness  # noqa: E402

__all__ = ["App", "main"]

setup_environment()  # PATH: ffmpeg.exe / deno.exe junto al ejecutable
enable_dpi_awareness()  # antes de crear cualquier ventana


def selftest(path: str) -> None:
    """Diagnóstico: escribe versiones y rutas a un archivo."""
    import yt_dlp.extractor.youtube as _yt
    try:
        import yt_dlp_ejs
        _ejs = yt_dlp_ejs.version
    except Exception:  # noqa: BLE001
        _ejs = "NO DISPONIBLE"
    with open(path, "w", encoding="utf-8") as _f:
        _f.writelines(line + "\n" for line in (
            f"app={updater.VERSION}", f"yt_dlp={yt_dlp.version.__version__}", f"file={yt_dlp.__file__}",
            f"extractor={_yt.__file__}", f"yt_dlp_ejs={_ejs}",
            f"js_runtime={list(find_js_runtimes()) or 'NINGUNO'}", f"ffmpeg={shutil.which('ffmpeg')}"))


def main() -> None:
    if len(sys.argv) > 2 and sys.argv[1] == "--selftest":
        selftest(sys.argv[2])
        sys.exit(0)
    setup_logging()
    App().mainloop()


if __name__ == "__main__":
    main()
