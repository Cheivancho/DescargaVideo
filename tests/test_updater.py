"""Actualizador: versiones, hash obligatorio de la app, descarga verificada y motor yt-dlp."""
import hashlib
import io
import json
import os
import time
import zipfile

import pytest

import updater


class Resp(io.BytesIO):
    """Respuesta HTTP simulada (contexto + headers)."""

    def __init__(self, data: bytes, headers=None):
        super().__init__(data)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_get(release: dict, extra: dict | None = None):
    """_get falso: la API de releases devuelve 'release'; otras URLs, lo indicado en 'extra' (url -> bytes)."""
    extra = extra or {}

    def _get(url, timeout=6):
        if url.endswith("/releases/latest"):
            return Resp(json.dumps(release).encode())
        return Resp(extra[url], {"Content-Length": str(len(extra[url]))})
    return _get


SETUP = {"name": "DescargadorYouTube-Setup.exe", "browser_download_url": "http://x/setup", "size": 3}
HASH = "ab" * 32


def release(tag="v9.0.0", assets=None):
    return {"tag_name": tag, "body": "Notas", "assets": [SETUP] if assets is None else assets}


@pytest.mark.parametrize("v, esperado", [
    ("1.2.0", (1, 2, 0)), ("v2.0.10", (2, 0, 10)), ("", ()), (None, ()), ("sin números", ()), ("1.10", (1, 10)),
])
def test_parse_version(v, esperado):
    assert updater.parse_version(v) == esperado


def test_version_se_compara_numericamente():
    assert updater.parse_version("1.10.0") > updater.parse_version("1.9.9")


def test_update_sin_hash_se_rechaza(monkeypatch):
    monkeypatch.setattr(updater, "_get", fake_get(release()))
    assert updater.check_app_update() is None


def test_update_con_digest_del_asset(monkeypatch):
    asset = {**SETUP, "digest": "sha256:" + HASH.upper()}
    monkeypatch.setattr(updater, "_get", fake_get(release(assets=[asset])))
    upd = updater.check_app_update()
    assert upd["version"] == "9.0.0" and upd["sha256"] == HASH and upd["url"] == "http://x/setup"


def test_update_digest_mal_formado_se_ignora(monkeypatch):
    asset = {**SETUP, "digest": "sha256:no-es-un-hash"}
    monkeypatch.setattr(updater, "_get", fake_get(release(assets=[asset])))
    assert updater.check_app_update() is None


def test_update_con_asset_sha256(monkeypatch):
    side = {"name": SETUP["name"] + ".sha256", "browser_download_url": "http://x/h"}
    monkeypatch.setattr(updater, "_get", fake_get(release(assets=[SETUP, side]),
                                                  {"http://x/h": f"{HASH}  {SETUP['name']}\n".encode()}))
    assert updater.check_app_update()["sha256"] == HASH


def test_update_asset_sha256_ilegible_se_rechaza(monkeypatch):
    side = {"name": SETUP["name"] + ".sha256", "browser_download_url": "http://x/h"}
    monkeypatch.setattr(updater, "_get", fake_get(release(assets=[SETUP, side]), {"http://x/h": b"basura"}))
    assert updater.check_app_update() is None


@pytest.mark.parametrize("tag", ["v1.2.0", "v1.0.0", "v0.9"])
def test_update_misma_version_o_anterior_no_se_ofrece(monkeypatch, tag):
    asset = {**SETUP, "digest": "sha256:" + HASH}
    monkeypatch.setattr(updater, "_get", fake_get(release(tag=tag, assets=[asset])))
    assert updater.check_app_update() is None


def test_update_sin_instalador_no_se_ofrece(monkeypatch):
    monkeypatch.setattr(updater, "_get", fake_get(release(assets=[{"name": "otra-cosa.zip"}])))
    assert updater.check_app_update() is None


def test_download_sin_hash_se_niega():
    with pytest.raises(ValueError, match="SHA-256"):
        updater.download_installer({"url": "http://x/setup", "sha256": None})


def test_download_hash_incorrecto_borra_el_archivo(monkeypatch):
    data = b"abc"
    monkeypatch.setattr(updater, "_get", fake_get({}, {"http://x/setup": data}))
    with pytest.raises(ValueError, match="dañado"):
        updater.download_installer({"url": "http://x/setup", "sha256": HASH, "size": 3})


def test_download_correcto_devuelve_ruta_y_progreso(monkeypatch):
    data = b"contenido del instalador"
    monkeypatch.setattr(updater, "_get", fake_get({}, {"http://x/setup": data}))
    avances = []
    path = updater.download_installer({"url": "http://x/setup", "sha256": hashlib.sha256(data).hexdigest().upper(),
                                       "size": len(data)}, avances.append)
    try:
        assert open(path, "rb").read() == data and avances[-1] == 100
    finally:
        os.remove(path)


# ---------------------------------------------------------------- yt-dlp
def test_safe_extract_rechaza_rutas_peligrosas(tmp_path):
    for nombre in ("yt_dlp/../../evil.py", "yt_dlp/..\\evil.py"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr(nombre, "x")
        with zipfile.ZipFile(buf) as z, pytest.raises(ValueError, match="Ruta no permitida"):
            updater._safe_extract(z, ("yt_dlp/",), str(tmp_path))


def test_safe_extract_solo_los_prefijos(tmp_path):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("yt_dlp/__init__.py", "ok")
        z.writestr("otro/archivo.py", "no")
    with zipfile.ZipFile(buf) as z:
        updater._safe_extract(z, ("yt_dlp/",), str(tmp_path))
    assert (tmp_path / "yt_dlp" / "__init__.py").exists() and not (tmp_path / "otro").exists()


def test_required_ejs_version():
    meta = ("Requires-Dist: requests; extra == 'default'\n"
            "Requires-Dist: yt-dlp-ejs==0.8.0; extra == 'default'\n"
            "Requires-Dist: yt-dlp-ejs==0.8.0; extra == 'pin'\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("yt_dlp-1.0.dist-info/METADATA", meta)
    assert updater.required_ejs_version(buf.getvalue()) == "0.8.0"
    vacio = io.BytesIO()
    with zipfile.ZipFile(vacio, "w") as z:
        z.writestr("x.txt", "")
    assert updater.required_ejs_version(vacio.getvalue()) is None


@pytest.fixture
def datos(tmp_path, monkeypatch):
    """Redirige todo el estado del actualizador a una carpeta temporal."""
    monkeypatch.setattr(updater, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(updater, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(updater, "YTDLP_DIR", str(tmp_path / "yt-dlp"))
    monkeypatch.setattr(updater, "YTDLP_NEXT", str(tmp_path / "yt-dlp.next"))
    return tmp_path


@pytest.mark.parametrize("contenido", [None, "{corrupto", "[1, 2]", '"texto"', ""])
def test_state_viejo_o_corrupto_no_falla(datos, contenido):
    if contenido is not None:
        (datos / "state.json").write_text(contenido, encoding="utf-8")
    assert updater.load_state() == {}
    updater.update_state(a=1)
    assert updater.load_state() == {"a": 1}


def test_fallo_de_red_guarda_last_check_y_reintenta_antes(datos, monkeypatch):
    def falla():
        raise OSError("sin internet")
    monkeypatch.setattr(updater, "download_ytdlp_next", falla)
    assert updater.background_ytdlp_update() is None
    st = updater.load_state()
    assert st["ytdlp_last_ok"] is False and time.time() - st["ytdlp_last_check"] < 5
    # justo después no se vuelve a intentar...
    llamadas = []
    monkeypatch.setattr(updater, "download_ytdlp_next", lambda: llamadas.append(1))
    updater.background_ytdlp_update()
    assert not llamadas
    # ...pero tras la hora de reintento (menor que el intervalo normal) sí
    updater.update_state(ytdlp_last_check=time.time() - updater.YTDLP_RETRY_EVERY - 5)
    updater.background_ytdlp_update()
    assert llamadas
    assert updater.YTDLP_RETRY_EVERY < updater.YTDLP_CHECK_EVERY


def test_exito_respeta_el_intervalo_largo(datos, monkeypatch):
    monkeypatch.setattr(updater, "download_ytdlp_next", lambda: "9.9.9")
    assert updater.background_ytdlp_update() == "9.9.9"
    llamadas = []
    monkeypatch.setattr(updater, "download_ytdlp_next", lambda: llamadas.append(1))
    updater.update_state(ytdlp_last_check=time.time() - updater.YTDLP_RETRY_EVERY - 5)
    updater.background_ytdlp_update()
    assert not llamadas  # tras un éxito todavía no toca


def test_apply_pending_intercambia_directorios(datos):
    (datos / "yt-dlp").mkdir()
    (datos / "yt-dlp" / "version.txt").write_text("1.0")
    (datos / "yt-dlp.next").mkdir()
    (datos / "yt-dlp.next" / "version.txt").write_text("2.0")
    updater.apply_pending_ytdlp()
    assert updater.installed_update_version() == "2.0" and not (datos / "yt-dlp.next").exists()


def test_apply_pending_sin_nada_no_hace_nada(datos):
    updater.apply_pending_ytdlp()
    assert not (datos / "yt-dlp").exists()


def test_reset_engine_borra_todo(datos):
    for d in ("yt-dlp", "yt-dlp.next"):
        (datos / d).mkdir()
        (datos / d / "version.txt").write_text("1")
    updater.reset_ytdlp_engine()
    assert not (datos / "yt-dlp").exists() and not (datos / "yt-dlp.next").exists()
