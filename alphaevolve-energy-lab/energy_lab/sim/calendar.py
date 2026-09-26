"""Japanese fiscal-year calendar: national holidays (incl. substitute and sandwiched days), observance periods
(New Year Dec 29-Jan 3, Obon Aug 13-16, Golden Week), day types and 30-minute slot timestamps.

Holiday rules follow the Act on National Holidays (fixed dates, Happy-Monday rules, equinox dates as published
for 2023-2027, substitute holiday when a holiday falls on Sunday, citizens' holiday between two holidays).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

EQUINOX = {  # (vernal, autumnal) as published by the National Astronomical Observatory of Japan
    2023: (date(2023, 3, 21), date(2023, 9, 23)), 2024: (date(2024, 3, 20), date(2024, 9, 22)),
    2025: (date(2025, 3, 20), date(2025, 9, 23)), 2026: (date(2026, 3, 20), date(2026, 9, 23)),
    2027: (date(2027, 3, 21), date(2027, 9, 23)),
}
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _nth_monday(y: int, m: int, n: int) -> date:
    d = date(y, m, 1)
    d += timedelta(days=(7 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def national_holidays(year: int) -> set[date]:
    h = {date(year, 1, 1), _nth_monday(year, 1, 2), date(year, 2, 11), date(year, 2, 23), date(year, 4, 29),
         date(year, 5, 3), date(year, 5, 4), date(year, 5, 5), _nth_monday(year, 7, 3), date(year, 8, 11),
         _nth_monday(year, 9, 3), _nth_monday(year, 10, 2), date(year, 11, 3), date(year, 11, 23)}
    if year in EQUINOX:
        h |= set(EQUINOX[year])
    # substitute holidays
    for d in sorted(h):
        if d.weekday() == 6:
            s = d + timedelta(days=1)
            while s in h:
                s += timedelta(days=1)
            h.add(s)
    # citizens' holiday: a weekday sandwiched between two holidays
    for d in sorted(h):
        mid = d + timedelta(days=1)
        if mid not in h and (d + timedelta(days=2)) in h and mid.weekday() != 6:
            h.add(mid)
    return h


_HOL: set[date] = set()
for _y in range(2022, 2029):
    _HOL |= national_holidays(_y)


def is_holiday(d: date) -> bool:
    return d in _HOL


def observance(d: date) -> str | None:
    if (d.month == 12 and d.day >= 29) or (d.month == 1 and d.day <= 3):
        return "new_year"
    if d.month == 8 and 13 <= d.day <= 16:
        return "obon"
    if (d.month == 4 and d.day >= 29) or (d.month == 5 and d.day <= 5):
        return "golden_week"
    return None


def is_working_day(d: date) -> bool:
    return d.weekday() < 5 and not is_holiday(d) and observance(d) not in ("new_year", "obon")


def fiscal_year(d: date) -> int:
    return d.year if d.month >= 4 else d.year - 1


def fy_days(fy: int) -> list[date]:
    start, end = date(fy, 4, 1), date(fy + 1, 3, 31)
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def season_of_month(m: int) -> str:
    return {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer", 7: "summer",
            8: "summer", 9: "summer", 10: "autumn", 11: "autumn"}[m]


def fy_month_index(m: int) -> int:
    """0 = April ... 11 = March."""
    return (m - 4) % 12


def day_frame(days: list[date]) -> dict[str, np.ndarray]:
    """Per-day calendar attributes as arrays."""
    return {
        "date": np.array([d.isoformat() for d in days]),
        "month": np.array([d.month for d in days]),
        "fy": np.array([fiscal_year(d) for d in days]),
        "dow": np.array([d.weekday() for d in days]),
        "holiday": np.array([is_holiday(d) for d in days]),
        "working": np.array([is_working_day(d) for d in days]),
        "observance": np.array([observance(d) or "" for d in days]),
        "doy": np.array([d.timetuple().tm_yday for d in days]),
    }


def slot_label(slot: int) -> str:
    """slot 1..48 -> 'HH:MM' start time."""
    m = (slot - 1) * 30
    return f"{m // 60:02d}:{m % 60:02d}"
