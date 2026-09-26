"""Problem registry. Each problem exposes a ProblemSpec (see base.py)."""
from __future__ import annotations

from .base import ProblemSpec


def get_problem(name: str) -> ProblemSpec:
    if name == "tariff_pricing":
        from .tariff_pricing.spec import SPEC
        return SPEC
    if name == "jepx_trading":
        from .jepx_trading.spec import SPEC
        return SPEC
    raise KeyError(f"unknown problem {name!r}")
