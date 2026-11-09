"""Ajustes (state.json) y presets: migración de estados viejos o corruptos."""
import json

import pytest

import config
from config import (
    DEFAULT_SETTINGS,
    FACTORY_PRESETS,
    PRESET_KEYS,
    load_presets,
    load_settings,
    normalize_preset,
    pick_heights,
    save_presets,
)
from formats import OUT_FORMATS


def test_sin_settings_usa_los_valores_por_defecto():
    assert load_settings({}) == DEFAULT_SETTINGS
    assert load_settings({"ytdlp_last_check": 1}) == DEFAULT_SETTINGS  # state.json de una versión antigua


@pytest.mark.parametrize("raro", [None, "basura", 3, [1, 2], True])
def test_settings_no_dict_se_ignora(raro):
    assert load_settings({"settings": raro}) == DEFAULT_SETTINGS


def test_settings_con_tipos_y_valores_invalidos():
    malos = {
        "fmt": "inexistente", "audio": "sí", "geometry": "ancho x alto", "audio_fmt": "MIDI", "audio_q": "9999",
        "subs_mode": 3, "fps": "120", "scale_preset": "?", "scale_mode": None, "cookies": "Netscape",
        "out_dir": 5, "desconocida": 1,
    }
    assert load_settings({"settings": malos}) == DEFAULT_SETTINGS


def test_settings_validos_se_respetan_y_completan():
    s = load_settings({"settings": {"fmt": "hap", "audio": True, "geometry": "1280x800", "out_dir": "D:\\Videos",
                                    "fps": "30", "cookies": "Firefox", "preset": "Mío"}})
    assert s["fmt"] == "hap" and s["audio"] is True and s["geometry"] == "1280x800" and s["out_dir"] == "D:\\Videos"
    assert s["fps"] == "30" and s["cookies"] == "Firefox" and s["preset"] == "Mío"
    assert s["audio_fmt"] == DEFAULT_SETTINGS["audio_fmt"]  # lo que falta, por defecto


def test_todos_los_formatos_guardables_son_validos():
    for clave in OUT_FORMATS.values():
        assert load_settings({"settings": {"fmt": clave}})["fmt"] == clave


# ---------------------------------------------------------------- presets
@pytest.fixture
def presets_en_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PRESETS_FILE", str(tmp_path / "presets.json"))
    return tmp_path / "presets.json"


def test_presets_sin_archivo(presets_en_tmp):
    assert load_presets() == {}


@pytest.mark.parametrize("contenido", ["{corrupto", "[]", '"x"', "null", ""])
def test_presets_corruptos_equivalen_a_ninguno(presets_en_tmp, contenido):
    presets_en_tmp.write_text(contenido, encoding="utf-8")
    assert load_presets() == {}


def test_presets_ida_y_vuelta(presets_en_tmp):
    save_presets({"Mío": normalize_preset({"heights": [720, 1080], "fmt": "hapq", "audio": True})})
    p = load_presets()["Mío"]
    assert p["heights"] == [1080, 720] and p["fmt"] == "hapq" and p["audio"] is True
    assert set(PRESET_KEYS) <= set(p)


def test_presets_entradas_malas_se_descartan_o_se_corrigen(presets_en_tmp):
    presets_en_tmp.write_text(json.dumps({"ok": {"fmt": "zzz", "heights": [1080, "x", None, True, -5, 99999]},
                                          "": {"fmt": "hap"}, "roto": 5}), encoding="utf-8")
    p = load_presets()
    assert list(p) == ["ok"] and p["ok"]["fmt"] == "h264" and p["ok"]["heights"] == [1080]


def test_presets_de_fabrica_son_validos():
    assert set(FACTORY_PRESETS) == {"Resolume 1080p (HAP)", "Premiere 1080p (ProRes 422)",
                                    "Web ligero 720p (H.264)", "Solo audio MP3 320"}
    for nombre, raw in FACTORY_PRESETS.items():
        n = normalize_preset(raw)
        assert n["fmt"] in OUT_FORMATS.values(), nombre
        assert normalize_preset(n) == n  # idempotente
    assert normalize_preset(FACTORY_PRESETS["Resolume 1080p (HAP)"])["scale_preset"] == "1920x1080"
    assert normalize_preset(FACTORY_PRESETS["Solo audio MP3 320"])["heights"] == []


def test_los_presets_no_guardan_el_recorte():
    assert not any("trim" in k for k in PRESET_KEYS)


@pytest.mark.parametrize("disponibles, pedidas, esperado", [
    ([1080, 720, 480], [1080], [1080]),
    ([720, 480], [1080], [720]),           # no hay 1080: la mayor menor que ella
    ([360, 240], [480, 1080], [360]),
    ([360], [144], [360]),                 # solo hay mayores: la menor disponible
    ([1080, 720], [1080, 720], [1080, 720]),
    ([720], [], []),
    ([], [1080], []),
])
def test_pick_heights(disponibles, pedidas, esperado):
    assert pick_heights(disponibles, pedidas) == esperado


def test_formato_gpu_guardado_no_se_pierde_sin_deteccion():
    assert load_settings({"settings": {"fmt": "h264_gpu"}})["fmt"] == "h264_gpu"
    assert load_settings({"settings": {"fmt": "inventado"}})["fmt"] == "h264"


def test_register_gpu_formats_quita_los_que_ya_no_funcionan():
    from formats import RECODE_SPECS, register_gpu_formats
    register_gpu_formats({"h264_gpu": "h264_nvenc"})
    assert "h264_gpu" in OUT_FORMATS.values() and "h264_gpu" in RECODE_SPECS
    register_gpu_formats({})
    assert "h264_gpu" not in OUT_FORMATS.values() and "h264_gpu" not in RECODE_SPECS
