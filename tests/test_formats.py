"""Selector de formato, filtros de ffmpeg, recorte, escala y consistencia de los formatos de salida."""
import pytest

import formats
from formats import (
    AUDIO_FORMATS,
    OUT_FORMATS,
    RECODE_SPECS,
    audio_extras,
    audio_template,
    build_format_selector,
    build_video_filter,
    final_ext,
    parse_langs,
    parse_resolution,
    parse_time,
    range_tag,
    resolve_scale,
    scale_filter,
    trim_options,
    validate_trim,
    variant_tag,
    video_extras,
    video_template,
)


# ---------------------------------------------------------------- formatos de salida
def test_cada_formato_tiene_su_receta():
    for clave in OUT_FORMATS.values():
        if clave not in ("h264", "original"):
            assert clave in RECODE_SPECS, f"falta RECODE_SPECS['{clave}']"


def test_recetas_bien_formadas():
    for clave, (nombre, ext, video, audio, extra) in RECODE_SPECS.items():
        assert nombre and ext in (".mp4", ".mov"), clave
        assert video[0] == "-c:v" and audio[0] == "-c:a", clave
        assert isinstance(extra, list)


@pytest.mark.parametrize("kind, ext", [("h264", ".mp4"), ("original", ".mp4"), ("h265", ".mp4"),
                                       ("prores", ".mov"), ("hap", ".mov"), ("dnxhr", ".mov"), ("mjpeg", ".mov")])
def test_final_ext(kind, ext):
    assert final_ext(kind) == ext


def test_formatos_gpu_se_registran_y_son_consistentes(monkeypatch):
    monkeypatch.setattr(formats, "OUT_FORMATS", dict(OUT_FORMATS))
    monkeypatch.setattr(formats, "RECODE_SPECS", dict(RECODE_SPECS))
    nuevos = formats.register_gpu_formats({"h264_gpu": "h264_nvenc", "h265_gpu": "hevc_nvenc", "otra": "x"})
    assert len(nuevos) == 2 and "h264_gpu" in formats.RECODE_SPECS and "h265_gpu" in formats.OUT_FORMATS.values()
    assert formats.RECODE_SPECS["h265_gpu"][2][:2] == ["-c:v", "hevc_nvenc"]
    assert formats.register_gpu_formats({"h264_gpu": "h264_nvenc"}) == []  # ya registrado: no duplica
    assert set(formats.GPU_FALLBACK) == set(formats.GPU_TABLE)


# ---------------------------------------------------------------- selector de formato
def test_selector_video_individual():
    s = build_format_selector(1080)
    assert s == ("bestvideo[height=1080][vcodec^=avc1]+bestaudio[acodec^=mp4a]/"
                 "bestvideo[height=1080]+bestaudio/best[height=1080]")


def test_selector_playlist_usa_menor_o_igual_y_cae_a_best():
    s = build_format_selector(720, is_playlist=True)
    assert "height<=720" in s and "height=720" not in s and s.endswith("/best")


@pytest.mark.parametrize("pl", [False, True])
def test_selector_fps(pl):
    s = build_format_selector(1080, pl, fps=30)
    assert s.count("[fps<=?30]") == 3  # tolera formatos sin dato de fps
    assert "fps" not in build_format_selector(1080, pl, fps=None)


def test_plantillas_de_nombre():
    assert video_template(1080, False) == "%(title)s [1080p].%(ext)s"
    assert video_template(720, True, " [00m10s-fin]") == (
        "%(playlist_title)s/%(playlist_index)03d - %(title)s [720p] [00m10s-fin].%(ext)s")
    assert audio_template(False) == "%(title)s.%(ext)s"
    assert audio_template(True, " [x]").startswith("%(playlist_title)s/")


def test_parse_langs():
    assert parse_langs("es, en") == ["es", "en"]
    assert parse_langs("en;pt-BR  fr") == ["en", "pt-BR", "fr"]
    assert parse_langs("") == ["es", "en"] and parse_langs("!!!") == ["es", "en"]


# ---------------------------------------------------------------- escala (ffmpeg)
def test_filtro_ajustar_con_barras():
    f = scale_filter(1920, 1080, "fit")
    assert f.startswith("scale=1920:1080:force_original_aspect_ratio=decrease")
    assert "pad=1920:1080:(ow-iw)/2:(oh-ih)/2" in f and f.endswith("setsar=1")


def test_filtro_rellenar_recortando():
    f = scale_filter(1280, 720, "fill")
    assert "force_original_aspect_ratio=increase" in f and "crop=1280:720" in f and "pad=" not in f


def test_filtro_estirar():
    f = scale_filter(3840, 2160, "stretch")
    assert f.startswith("scale=3840:2160") and "force_original" not in f and "pad=" not in f and "crop=" not in f


def test_filtro_modo_desconocido_cae_a_barras():
    assert scale_filter(100, 100, "raro") == scale_filter(100, 100, "fit")


def test_build_video_filter():
    assert build_video_filter({"kind": "h264"}) == ""
    assert build_video_filter({"kind": "prores", "scale": None}) == ""
    assert "crop=trunc(iw/4)*4:trunc(ih/4)*4" == build_video_filter({"kind": "hap"})  # HAP sin escala
    assert build_video_filter({"kind": "hapq"}) .startswith("crop=")
    con_escala = build_video_filter({"kind": "hap", "scale": {"w": 1920, "h": 1080, "mode": "fit"}})
    assert con_escala.startswith("scale=1920:1080") and "trunc" not in con_escala


@pytest.mark.parametrize("texto, esperado", [("1920x1080", (1920, 1080)), (" 1280 X 720 ", (1280, 720)),
                                             ("3840×2160", (3840, 2160))])
def test_parse_resolution(texto, esperado):
    assert parse_resolution(texto) == esperado


@pytest.mark.parametrize("texto", ["", "1920", "axb", "10x10", "99999x1080", "1920x", "-1920x1080"])
def test_parse_resolution_invalida(texto):
    with pytest.raises(ValueError):
        parse_resolution(texto)


def test_resolve_scale():
    assert resolve_scale("Sin cambios", "", "", "h264") == (None, [])
    sc, notas = resolve_scale("1920x1080", "", "Rellenar recortando", "h264")
    assert sc == {"w": 1920, "h": 1080, "mode": "fill"} and notas == []
    sc, notas = resolve_scale("Personalizada", "1367x769", "Estirar", "h264")  # H.264 pide dimensiones pares
    assert (sc["w"], sc["h"]) == (1368, 770) and notas
    sc, notas = resolve_scale("Personalizada", "1366x768", "Ajustar con barras", "hap")  # HAP, múltiplos de 4
    assert (sc["w"], sc["h"]) == (1368, 768) and "HAP" in notas[0]
    with pytest.raises(ValueError):
        resolve_scale("Personalizada", "mal", "Estirar", "h264")


# ---------------------------------------------------------------- recorte
@pytest.mark.parametrize("texto, seg", [("", None), ("  ", None), ("0:30", 30.0), ("1:30", 90.0), ("00:01:30", 90.0),
                                        ("10:05", 605.0), ("1:02:03", 3723.0), ("0:05.5", 5.5), ("100:00", 6000.0)])
def test_parse_time_validos(texto, seg):
    assert parse_time(texto) == seg


@pytest.mark.parametrize("texto", ["90", "1:75", "1:60", "1:60:00", "a:b", "1:2:3:4", "-1:30", "1:", ":30", "1:30s",
                                   "1.5:30"])
def test_parse_time_invalidos(texto):
    with pytest.raises(ValueError):
        parse_time(texto)


def test_validate_trim():
    assert validate_trim("", "") is None
    assert validate_trim("0:10", "0:20", 60, True) == {"start": 10.0, "end": 20.0, "exact": True}
    assert validate_trim("", "0:20") == {"start": None, "end": 20.0, "exact": False}
    assert validate_trim("0:10", "") ["end"] is None
    for ini, fin, dur in (("0:20", "0:10", 60), ("0:10", "0:10", 60), ("1:00", "", 30), ("0:00", "0:00", None)):
        with pytest.raises(ValueError):
            validate_trim(ini, fin, dur)


def test_range_tag_y_variant_tag():
    assert range_tag(None) == ""
    assert range_tag({"start": 10, "end": 20}) == " [00m10s-00m20s]"
    assert range_tag({"start": None, "end": 65}) == " [00m00s-01m05s]"
    assert range_tag({"start": 3725, "end": None}) == " [1h02m05s-fin]"
    spec = {"trim": {"start": 1, "end": 2}, "scale": {"w": 1280, "h": 720, "mode": "fill"}, "fps": 30}
    assert variant_tag(spec) == " [00m01s-00m02s] [1280x720 recorte] [30fps]"
    assert variant_tag({}) == ""
    assert variant_tag({"scale": {"w": 1, "h": 2, "mode": "fit"}}) == " [1x2]"


def test_trim_options():
    assert trim_options(None) == {}
    o = trim_options({"start": 5, "end": None, "exact": True})
    assert o["force_keyframes_at_cuts"] is True
    rangos = list(o["download_ranges"]({"duration": 60}, None))
    assert rangos[0]["start_time"] == 5 and rangos[0]["end_time"] == float("inf")


# ---------------------------------------------------------------- subtítulos, miniatura, audio
def spec_base(**kw):
    return {"subs": False, "subs_langs": ["es", "en"], "subs_mode": "embed", "embed": False,
            "audio_fmt": "MP3", "audio_q": "320", **kw}


def test_video_extras_vacio():
    assert video_extras(spec_base(), ".mp4") == {}


def test_subtitulos_se_incrustan_solo_en_mp4():
    mp4 = video_extras(spec_base(subs=True), ".mp4")
    assert mp4["writesubtitles"] and mp4["subtitleslangs"] == ["es", "en"]
    assert mp4["postprocessors"][0]["key"] == "FFmpegEmbedSubtitle"
    mov = video_extras(spec_base(subs=True), ".mov")  # MOV: se guarda el .srt aparte
    assert [p["key"] for p in mov["postprocessors"]] == ["FFmpegSubtitlesConvertor"]
    srt = video_extras(spec_base(subs=True, subs_mode="srt"), ".mp4")
    assert [p["key"] for p in srt["postprocessors"]] == ["FFmpegSubtitlesConvertor"]


def test_miniatura_y_metadatos_solo_en_mp4():
    mp4 = video_extras(spec_base(embed=True), ".mp4")
    assert mp4["writethumbnail"] is True
    assert [p["key"] for p in mp4["postprocessors"]] == ["FFmpegThumbnailsConvertor", "FFmpegMetadata"]
    assert video_extras(spec_base(embed=True), ".mov") == {}  # se ignora sin romper


@pytest.mark.parametrize("fmt, tiene_calidad", [("MP3", True), ("M4A", True), ("Opus", True), ("WAV", False),
                                                ("FLAC", False)])
def test_audio_extras_calidad(fmt, tiene_calidad):
    pp = audio_extras(spec_base(audio_fmt=fmt))["postprocessors"][0]
    assert pp["key"] == "FFmpegExtractAudio" and pp["preferredcodec"] == AUDIO_FORMATS[fmt][0]
    assert ("preferredquality" in pp) is tiene_calidad


@pytest.mark.parametrize("fmt, miniatura, metadatos", [("MP3", True, True), ("M4A", True, True), ("Opus", False, True),
                                                       ("FLAC", False, True), ("WAV", False, False)])
def test_audio_extras_miniatura_y_metadatos(fmt, miniatura, metadatos):
    o = audio_extras(spec_base(audio_fmt=fmt, embed=True))
    claves = [p["key"] for p in o["postprocessors"]]
    assert o.get("writethumbnail", False) is miniatura
    assert ("FFmpegMetadata" in claves) is metadatos
    assert "EmbedThumbnail" not in claves  # la carátula la incrusta la app (EmbedThumbnail exigiría ffprobe)
