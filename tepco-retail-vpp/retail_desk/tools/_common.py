"""Shared helpers for tools: error envelope, validation, rounding."""
from __future__ import annotations

import functools
import hashlib
import json
import math
from typing import Any, Callable

from ..clock import valid_date


def safe_tool(fn: Callable) -> Callable:
    """Wrap a tool so any exception becomes {"status": "error"} instead of raising to the model."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:  # surface, never raise to the model
            return {"status": "error", "error": f"{type(exc).__name__}: {str(exc)[:300]}", "tool": fn.__name__}

    return wrapper


def err(msg: str, **extra: Any) -> dict:
    return {"status": "error", "error": msg, **extra}


def check_date(d: str) -> str | None:
    return None if valid_date(d) else f"date must be YYYY-MM-DD, got {d!r}"


def check_slots(a: int, b: int) -> str | None:
    try:
        a, b = int(a), int(b)
    except (TypeError, ValueError):
        return "slots must be integers 1-48"
    if not (1 <= a <= 48 and 1 <= b <= 48 and a <= b):
        return f"slots must satisfy 1 <= from_slot <= to_slot <= 48, got {a}..{b}"
    return None


def r2(x: Any, n: int = 2) -> Any:
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return x
    if math.isnan(v):
        return None
    return round(v, n)


def short_hash(obj: Any) -> str:
    return hashlib.sha1(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()[:6]


def record_proposal(tool_context: Any, action: dict) -> None:
    """Store a pending action in session state so the risk auditor can check the exact proposal."""
    if tool_context is None:
        return
    props = dict(tool_context.state.get("proposals", {}) or {})
    props[action["id"]] = action
    tool_context.state["proposals"] = props
