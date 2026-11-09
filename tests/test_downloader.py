"""Enlaces, progreso, errores comprensibles, diagnóstico de formatos y runtime de JavaScript."""
import pytest

import downloader
from downloader import (
    ProgressTracker,
    diagnose_formats,
    find_js_runtimes,
    friendly_error,
    has_video_and_list,
    video_list_info,
    youtube_link,
)


# ---------------------------------------------------------------- enlaces
@pytest.mark.parametrize("url, esperado", [
    ("https://www.youtube.com/watch?v=abc&list=PL123", (True, True)),
    ("https://www.youtube.com/watch?list=PL123&v=abc&index=2", (True, True)),
    ("https://youtu.be/abc?list=PL123", (True, True)),
    ("https://music.youtube.com/watch?v=abc&list=RDabc", (True, True)),
    ("https://www.youtube.com/playlist?list=PL123", (False, True)),
    ("https://www.youtube.com/watch?v=abc", (True, False)),
    ("https://youtu.be/abc", (True, False)),
    ("https://www.youtube.com/@canal", (False, False)),
    ("https://example.com/watch?v=abc&list=PL123", (False, False)),
    ("https://notyoutube.com/watch?v=abc&list=x", (False, False)),
    ("no es una url", (False, False)),
    ("", (False, False)),
])
def test_video_list_info(url, esperado):
    assert video_list_info(url) == esperado


def test_has_video_and_list():
    assert has_video_and_list("https://www.youtube.com/watch?v=abc&list=PL1")
    assert not has_video_and_list("https://www.youtube.com/playlist?list=PL1")
    assert not has_video_and_list("https://www.youtube.com/watch?v=abc")


@pytest.mark.parametrize("texto, esperado", [
    ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc"),
    ("  https://youtu.be/abc  \nsegunda línea", "https://youtu.be/abc"),
    ("https://m.youtube.com/watch?v=abc", "https://m.youtube.com/watch?v=abc"),
    ("hola", None), ("", None), (None, None), ("https://example.com/video", None),
    ("https://www.youtube.com/watch?v=abc y más texto", None),
])
def test_youtube_link(texto, esperado):
    assert youtube_link(texto) == esperado


# ---------------------------------------------------------------- progreso global
def evento(estado="downloading", hecho=0, total=100, vcodec="avc1", acodec="none", idx=None, n=None, speed=None,
           eta=None):
    info = {"vcodec": vcodec, "acodec": acodec, "playlist_index": idx, "n_entries": n}
    return {"status": estado, "downloaded_bytes": hecho, "total_bytes": total, "speed": speed, "eta": eta,
            "info_dict": info}


def test_progreso_es_monotono_y_no_vuelve_a_cero_entre_video_y_audio():
    t = ProgressTracker(2)
    t.start_job(1, "1080p")
    pcts = []
    for e in (evento(hecho=0), evento(hecho=50), evento("finished"),                   # pista de video
              evento(hecho=5, vcodec="none", acodec="mp4a"), evento("finished", vcodec="none", acodec="mp4a")):
        pcts.append(t.update(e)[0])
    t.start_job(2, "MP3")
    for e in (evento(hecho=30, vcodec="none", acodec="mp4a"), evento("finished", vcodec="none", acodec="mp4a")):
        pcts.append(t.update(e)[0])
    assert pcts == sorted(pcts)
    assert pcts[2] > 0 and pcts[3] >= pcts[2]  # tras el video no se reinicia
    assert pcts[4] == pytest.approx(50.0)  # primer trabajo de dos completo
    assert pcts[-1] == pytest.approx(100.0)


def test_progreso_texto_con_velocidad_y_eta():
    t = ProgressTracker(3)
    t.start_job(2, "1080p")
    _, texto = t.update(evento(hecho=10, speed=12.3 * 2 ** 20, eta=41, vcodec="avc1", acodec="mp4a"))
    assert texto == "[2/3] 1080p · 12.3 MiB/s · ETA 00:41"


def test_progreso_playlist_muestra_n_de_m():
    t = ProgressTracker(1)
    t.start_job(1, "720p")
    p1, texto = t.update(evento(hecho=50, vcodec="avc1", acodec="mp4a", idx=4, n=40))
    assert "video 4 de 40" in texto
    p2, _ = t.update(evento(hecho=10, vcodec="avc1", acodec="mp4a", idx=5, n=40))
    assert p2 > p1  # pasar al video siguiente avanza
    assert 100 * 3 / 40 <= p1 <= 100 * 4 / 40


def test_progreso_nunca_retrocede_ni_pasa_de_100():
    t = ProgressTracker(1)
    t.start_job(1, "x")
    a = t.update(evento(hecho=90, vcodec="avc1", acodec="mp4a"))[0]
    b = t.update(evento(hecho=10, vcodec="avc1", acodec="mp4a"))[0]  # dato atrasado
    c = t.update(evento("finished", vcodec="avc1", acodec="mp4a"))[0]
    assert b >= a and c == pytest.approx(100.0)


def test_progreso_sin_total_no_falla():
    t = ProgressTracker(1)
    pct, texto = t.update({"status": "downloading", "downloaded_bytes": 5, "info_dict": {}})
    assert pct == 0 and "[1/1]" in texto


def test_progreso_start_job_reserva_los_trabajos_previos():
    t = ProgressTracker(4)
    t.start_job(3, "x")  # los dos primeros se saltaron (ya existían)
    assert t.last == pytest.approx(50.0)


# ---------------------------------------------------------------- errores y diagnóstico
def test_friendly_error_cookies():
    m = friendly_error("ERROR: Could not copy Chrome cookie database. See https://github.com/yt-dlp/yt-dlp/issues/7271",
                       "Chrome")
    assert "cookies de Chrome" in m and "Firefox" in m
    assert "cookies" in friendly_error("ERROR: Failed to decrypt with DPAPI", "Edge")
    assert friendly_error("Could not copy Chrome cookie database", "Ninguno").startswith("Could not copy")


@pytest.mark.parametrize("original, trozo", [
    ("ERROR: [youtube] x: Sign in to confirm you're not a bot", "robot"),
    ("ERROR: [youtube] x: Video unavailable", "no está disponible"),
    ("ERROR: [youtube] x: Private video. Sign in", "no está disponible"),
    ("<urlopen error [Errno 11001] getaddrinfo failed>", "conexión"),
])
def test_friendly_error_comunes(original, trozo):
    assert trozo in friendly_error(original)


def test_friendly_error_desconocido_se_deja_igual_sin_prefijo():
    assert friendly_error("ERROR: ERROR: algo raro") == "algo raro"
    assert friendly_error(None) == ""


def test_diagnose_formats():
    assert diagnose_formats([2160, 1080, 720, 480], None, True) is None
    sin = diagnose_formats([], None, True)
    assert "No se encontraron" in sin and "Deno" not in sin
    poco = diagnose_formats([360, 144], "Some formats missing", False)
    assert "pocas" in poco and "Deno" in poco and "Some formats missing" in poco
    assert diagnose_formats([240], None, True) is not None  # una sola resolución baja también avisa


def test_find_js_runtimes_orden_de_preferencia(monkeypatch):
    hay = {"node": r"C:\node.exe", "deno": r"C:\deno.exe"}
    monkeypatch.setattr(downloader.shutil, "which", lambda exe: hay.get(exe))
    assert find_js_runtimes() == {"deno": {"path": r"C:\deno.exe"}}
    hay.pop("deno")
    assert list(find_js_runtimes()) == ["node"]
    hay.clear()
    assert find_js_runtimes() == {}
