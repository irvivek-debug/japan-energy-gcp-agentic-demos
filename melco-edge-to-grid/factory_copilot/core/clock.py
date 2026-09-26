"""Demo clock and 30-minute slot helpers (pure functions, no I/O).

The demo is frozen at Wednesday 2026-08-19 13:30 JST (Tokyo heatwave). Slot 1 is 00:00-00:30,
slot 48 is 23:30-24:00, matching the Japanese 30-minute balancing unit (koma).
"""
from __future__ import annotations

import datetime as _dt

DEMO_DATE = "2026-08-19"
DEMO_NOW = "2026-08-19T13:30"
DEMO_NOW_HHMM = "13:30"
TIMEZONE = "JST (UTC+9)"


def slot_of(hhmm: str) -> int:
    """Slot (1..48) that *starts* at or contains the given HH:MM time. '24:00' maps to 49."""
    h, m = (int(x) for x in hhmm.strip().split(":")[:2])
    return h * 2 + m // 30 + 1


def slot_start(slot: int) -> str:
    m = (slot - 1) * 30
    return f"{m // 60:02d}:{m % 60:02d}"


def slot_end(slot: int) -> str:
    m = slot * 30
    return f"{m // 60:02d}:{m % 60:02d}"


def window_slots(start_hhmm: str, end_hhmm: str) -> list[int]:
    """Slots covering [start, end). Example: 16:30-19:00 -> [34, 35, 36, 37, 38]."""
    s, e = slot_of(start_hhmm), slot_of(end_hhmm)
    return list(range(s, e))


def ts_of(date: str, slot: int) -> str:
    return f"{date}T{slot_start(slot)}"


def now_slot() -> int:
    return slot_of(DEMO_NOW_HHMM)


def normalise_hhmm(value: str) -> str:
    """Accepts '16:30', '1630', '16', '2026-08-19T16:30' and returns 'HH:MM'."""
    v = str(value).strip()
    if "T" in v:
        v = v.split("T", 1)[1]
    v = v.replace(".", ":")
    if ":" not in v:
        v = v.zfill(4) if len(v) > 2 else v.zfill(2) + "00"
        v = v[:2] + ":" + v[2:4]
    h, m = v.split(":")[:2]
    return f"{int(h):02d}:{int(m):02d}"


def normalise_date(value: str | None) -> str:
    """'' / 'today' / None -> DEMO_DATE; otherwise the ISO date part."""
    if not value or str(value).strip().lower() in {"today", "now", "current"}:
        return DEMO_DATE
    v = str(value).strip()
    return v.split("T", 1)[0]


def day_of_week(date: str) -> str:
    return _dt.date.fromisoformat(date).strftime("%a")


def month_of(date: str) -> str:
    return date[:7]
