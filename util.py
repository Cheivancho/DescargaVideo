"""Utilidades de formato de texto."""


def fmt_num(n: int | None) -> str:
    if n is None:
        return "—"
    for unit, div in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if n >= div:
            return f"{n / div:.1f}{unit}".replace(".0", "")
    return str(n)


def fmt_date(s: str | None) -> str:
    return f"{s[6:8]}/{s[4:6]}/{s[0:4]}" if s and len(s) == 8 else "—"


def fmt_dur(sec: float | None) -> str:
    if not sec:
        return "—"
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_speed(bps: float | None) -> str:
    if not bps:
        return ""
    for unit, div in (("GiB/s", 2 ** 30), ("MiB/s", 2 ** 20), ("KiB/s", 2 ** 10)):
        if bps >= div:
            return f"{bps / div:.1f} {unit}"
    return f"{bps:.0f} B/s"


def fmt_eta(sec: float | None) -> str:
    if sec is None:
        return ""
    h, r = divmod(int(sec), 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def short_title(title: str | None, n: int = 28) -> str:
    title = (title or "").strip()
    return title if len(title) <= n else title[:n - 1].rstrip() + "…"
