from __future__ import annotations

from pathlib import Path

from ..base import ProblemSpec
from .evaluator import descriptor, evaluate
from .sim import EVALUATOR_VERSION

_HERE = Path(__file__).resolve().parent

SPEC = ProblemSpec(
    name="jepx_trading",
    title="JEPX trading algorithm (KBG day-ahead + intraday + BESS)",
    description=(_HERE / "description.md").read_text(),
    required_functions=("plan_day_ahead", "adjust_intraday"),
    seed_path=_HERE / "seed_program.py",
    null_path=_HERE / "null_program.py",
    evaluate=evaluate,
    descriptor=descriptor,
    descriptor_names=("bess_cycles_bucket", "intraday_volume_bucket"),
    version=EVALUATOR_VERSION,
    notes={"train": "96 days of FY2024 (12 seasonal blocks of 8 days)",
           "holdout": "96 days of FY2025 + 16 stress days (heat dome, cold snap with LNG shortage)"},
)
