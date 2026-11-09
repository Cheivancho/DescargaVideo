import pytest

from util import fmt_date, fmt_dur, fmt_eta, fmt_num, fmt_speed, short_title


@pytest.mark.parametrize("n, esperado", [
    (None, "—"), (0, "0"), (999, "999"), (1000, "1K"), (1500, "1.5K"), (2_000_000, "2M"), (3_400_000_000, "3.4B"),
])
def test_fmt_num(n, esperado):
    assert fmt_num(n) == esperado


@pytest.mark.parametrize("s, esperado", [
    ("20240131", "31/01/2024"), (None, "—"), ("", "—"), ("2024", "—"), ("2024013", "—"),
])
def test_fmt_date(s, esperado):
    assert fmt_date(s) == esperado


@pytest.mark.parametrize("sec, esperado", [
    (None, "—"), (0, "—"), (5, "0:05"), (65, "1:05"), (3600, "1:00:00"), (3725.9, "1:02:05"),
])
def test_fmt_dur(sec, esperado):
    assert fmt_dur(sec) == esperado


@pytest.mark.parametrize("bps, esperado", [
    (None, ""), (0, ""), (500, "500 B/s"), (2048, "2.0 KiB/s"), (12.3 * 2 ** 20, "12.3 MiB/s"),
    (3 * 2 ** 30, "3.0 GiB/s"),
])
def test_fmt_speed(bps, esperado):
    assert fmt_speed(bps) == esperado


@pytest.mark.parametrize("sec, esperado", [(None, ""), (0, "00:00"), (41, "00:41"), (125, "02:05"), (3725, "1:02:05")])
def test_fmt_eta(sec, esperado):
    assert fmt_eta(sec) == esperado


def test_short_title():
    assert short_title(None) == ""
    assert short_title("corto") == "corto"
    largo = short_title("x" * 60, 10)
    assert len(largo) == 10 and largo.endswith("…")
