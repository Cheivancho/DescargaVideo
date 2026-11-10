"""Nombre del producto: un solo lugar (branding.py) y coherente en todos los archivos de compilación."""
import os
import re

import branding

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def leer(nombre: str) -> str:
    with open(os.path.join(ROOT, nombre), encoding="utf-8-sig") as f:
        return f.read()


def test_el_slug_no_tiene_espacios_ni_tildes_ni_simbolos():
    assert re.fullmatch(r"[A-Za-z0-9]+", branding.APP_SLUG)
    assert branding.EXE_NAME == branding.APP_SLUG


def test_el_nombre_no_usa_la_marca_youtube():
    assert "youtube" not in branding.APP_NAME.lower()
    assert "youtube" not in branding.APP_SLUG.lower()
    assert branding.APP_NAME == "DescargaVideo"


def test_el_instalador_termina_en_setup_exe_para_el_actualizador():
    # check_app_update busca el asset con endswith("setup.exe"): debe valer tanto con el nombre nuevo como con el viejo
    assert branding.SETUP_NAME.lower().endswith("setup.exe")
    assert branding.SETUP_NAME == f"{branding.APP_SLUG}-Setup.exe"


def test_installer_iss_usa_el_nombre_nuevo():
    iss = leer("installer.iss")
    slug = branding.APP_SLUG
    assert f"AppName={branding.APP_NAME}" in iss
    assert f"OutputBaseFilename={slug}-Setup" in iss
    assert f"UninstallDisplayIcon={{app}}\\{slug}.exe" in iss
    assert f'Source: "dist\\{slug}\\*"' in iss
    assert f'Filename: "{{app}}\\{slug}.exe"' in iss


def test_installer_iss_conserva_el_appid_para_reemplazar_al_viejo():
    """Si el AppId cambiara, Windows trataría la app nueva como otra distinta y quedarían dos instaladas."""
    assert "AppId={{B6F1D6C2-5C1E-4D0B-9E57-7A2C6F0E1D41}" in leer("installer.iss")


def test_installer_iss_borra_el_ejecutable_y_los_accesos_directos_viejos():
    iss = leer("installer.iss")
    seccion = iss.split("[InstallDelete]", 1)[1].split("[", 1)[0]
    assert f"{{app}}\\{branding.LEGACY_DATA_DIRNAME}.exe" in seccion
    assert "{autoprograms}\\Descargador de YouTube.lnk" in seccion
    assert "{autodesktop}\\Descargador de YouTube.lnk" in seccion


def test_los_scripts_de_compilacion_y_publicacion_usan_el_mismo_nombre():
    slug = branding.APP_SLUG
    assert f"--name {slug}" in leer("build.ps1")
    assert f"output\\{slug}-Setup.exe" in leer("build.ps1")
    release = leer("release.ps1")
    for nombre in (f"output\\{slug}-Setup.exe", f"output\\{slug}.zip", f"output\\{slug}-portable.zip",
                   f"dist\\{slug}\\*"):
        assert nombre in release
    ci = leer(os.path.join(".github", "workflows", "release.yml"))
    for nombre in (f"output\\{slug}-Setup.exe", f"output\\{slug}.zip", f"output\\{slug}-portable.zip"):
        assert nombre in ci


def test_no_queda_el_nombre_viejo_en_codigo_ni_scripts():
    """El nombre anterior solo puede aparecer donde hace falta por compatibilidad (migración e instalador)."""
    viejos = ("Descargador de YouTube", "DescargadorYouTube")
    for archivo in ("ui.py", "app.py", "config.py", "convert.py", "downloader.py", "build.ps1", "release.ps1",
                    os.path.join(".github", "workflows", "release.yml")):
        texto = leer(archivo)
        for v in viejos:
            assert v not in texto, f"{archivo} todavía menciona «{v}»"
    # updater.py: el nombre viejo solo en comentarios/docstrings de la migración, nunca en una ruta fija
    assert 'os.path.join(base, "DescargadorYouTube")' not in leer("updater.py")
    assert branding.LEGACY_DATA_DIRNAME == "DescargadorYouTube"


def test_el_repositorio_sigue_siendo_el_de_las_releases_actuales():
    # Mientras el repo no se renombre en GitHub, las versiones instaladas buscan actualizaciones aquí.
    assert branding.REPO == "Cheivancho/descargador-youtube"
