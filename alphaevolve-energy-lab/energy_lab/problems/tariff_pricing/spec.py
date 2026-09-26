from __future__ import annotations

from pathlib import Path

from ..base import ProblemSpec
from .evaluator import descriptor, evaluate
from .model import EVALUATOR_VERSION

_HERE = Path(__file__).resolve().parent
SEED_PATH = _HERE / "seed_program.py"

SPEC = ProblemSpec(
    name="tariff_pricing",
    title="C&I retail tariff pricing (KBG FY2026 renewal book)",
    description=(_HERE / "description.md").read_text(),
    required_functions=("price_book",),
    seed_path=SEED_PATH,
    null_path=_HERE / "null_program.py",
    evaluate=evaluate,
    descriptor=descriptor,
    descriptor_names=("mean_alpha_bucket", "churn_bucket"),
    version=EVALUATOR_VERSION,
    holdout_fold="holdout2",
    notes={"train": "1,200-customer train cohort x 64 FY2026 train-bank scenarios",
           "holdout": "401-customer holdout cohort x 64 unseen holdout-bank scenarios (used by runs 1-2; burned)",
           "holdout2": "fresh 400-customer cohort (seed 31) x 64 fresh holdout-bank scenarios (seed 505); used from run 3"},
)
