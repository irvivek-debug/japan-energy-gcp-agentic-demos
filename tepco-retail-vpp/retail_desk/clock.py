"""Desk clock and 30-minute slot arithmetic (Japan: 48 slots per day, gate closure 1 hour before delivery)."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta

NOW = os.getenv("DESK_NOW", "2026-08-19T15:40")  # scenario clock (JST)
SCENARIO_DATE = NOW[:10]
GATE_CLOSURE_MINUTES = 60
IMBALANCE_CAP_NOW = 200.0  # JPY/kWh until 2026-09-30 (MARKET_FACTS s3)
IMBALANCE_CAP_FROM_OCT = 300.0  # JPY/kWh from 2026-10-01
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def valid_date(d: str) -> bool:
    return bool(_DATE.match(str(d)))


def slot_start(d: str, slot: int) -> str:
    m = (int(slot) - 1) * 30
    return f"{d}T{m // 60:02d}:{m % 60:02d}"


def slot_end(d: str, slot: int) -> str:
    return (datetime.fromisoformat(slot_start(d, slot)) + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M")


def slot_label(slot: int) -> str:
    a = (int(slot) - 1) * 30
    b = a + 30
    return f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}"


def gate_closure(d: str, slot: int) -> str:
    return (datetime.fromisoformat(slot_start(d, slot)) - timedelta(minutes=GATE_CLOSURE_MINUTES)).strftime("%Y-%m-%dT%H:%M")


def gate_status(d: str, slot: int, now: str = NOW) -> str:
    if slot_end(d, slot) <= now:
        return "delivered"
    if slot_start(d, slot) <= now:
        return "in_delivery"
    if gate_closure(d, slot) <= now:
        return "closed"
    return "open"


def minutes_between(a: str, b: str) -> float:
    return (datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds() / 60.0


def current_slot(now: str = NOW) -> int:
    t = datetime.fromisoformat(now)
    return (t.hour * 60 + t.minute) // 30 + 1
