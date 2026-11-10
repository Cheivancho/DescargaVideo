"""Nombre y datos de marca del producto. Es el ÚNICO lugar donde está escrito: el resto del código importa de aquí.

Si algún día cambia el nombre otra vez, se cambia aquí y en los archivos de compilación (build.ps1, release.ps1,
installer.iss, DescargaVideo.spec, release.yml); tests/test_branding.py comprueba que todos coincidan.
"""

APP_NAME = "DescargaVideo"  # nombre legible, el que ve la gente
APP_SLUG = "DescargaVideo"  # sin espacios ni tildes: ejecutable, carpetas y nombres de archivo
EXE_NAME = APP_SLUG
PUBLISHER = "Cheivancho"

# Repositorio donde se publican las Releases (y de donde la app busca actualizaciones). Las versiones instaladas
# antes del cambio de nombre del repositorio siguen encontrándolo: GitHub redirige el nombre anterior.
REPO = "Cheivancho/DescargaVideo"

DATA_DIRNAME = APP_SLUG  # %LOCALAPPDATA%\DescargaVideo
LEGACY_DATA_DIRNAME = "DescargadorYouTube"  # nombre anterior de la carpeta de datos (se copia al arrancar)
SETUP_NAME = f"{APP_SLUG}-Setup.exe"  # instalador (el actualizador solo exige que el asset termine en «setup.exe»)
