"""One evaluation path for every backend (local controller, AlphaEvolve adapter, tests, UI).

packaging -> scaffold check -> static AST check -> problem evaluator (sandboxed candidate, trusted
simulation, policy invariants, score). The AlphaEvolve-facing function ``make_contract_evaluator``
wraps it in the platform contract and never raises.
"""
from __future__ import annotations

import time
import traceback
from typing import Callable

from ..problems.base import ProblemSpec
from .contract import KIND_SCAFFOLD, KIND_STATIC, EvalOutcome, invalid
from .package import PackagingError, check_scaffolding, split_program, static_check


def evaluate_candidate(spec: ProblemSpec, src: str, fold: str = "train") -> EvalOutcome:
    t0 = time.monotonic()
    try:
        prog = split_program(src)
    except PackagingError as e:
        return invalid(KIND_SCAFFOLD, "packaging", str(e))
    err = check_scaffolding(spec.seed_program, prog)
    if err:
        return invalid(KIND_SCAFFOLD, "scaffold", err)
    problems = static_check(prog, spec.required_functions)
    if problems:
        return invalid(KIND_STATIC, "static", "; ".join(problems[:6]))
    try:
        out = spec.evaluate(src, fold=fold)
    except Exception as e:  # noqa: BLE001  evaluator bug: surface loudly, never score it
        out = invalid("evaluator_error", "evaluator_error",
                      f"{type(e).__name__}: {e}\n{traceback.format_exc()[-800:]}")
    out.details.setdefault("eval_s", round(time.monotonic() - t0, 3))
    return out


def make_contract_evaluator(spec: ProblemSpec, fold: str = "train",
                            on_result: Callable[[str, EvalOutcome], None] | None = None) -> Callable[[dict], dict]:
    """AlphaEvolve evaluator_function: candidate dict in, contract dict out (None for invalid)."""

    def evaluate(candidate: dict) -> dict:
        try:
            src = candidate["content"]["files"][0]["content"]
        except (KeyError, IndexError, TypeError):
            return invalid(KIND_SCAFFOLD, "packaging", "candidate has no content.files[0].content").to_contract()
        out = evaluate_candidate(spec, src, fold)
        if on_result:
            try:
                on_result(src, out)
            except Exception:  # noqa: BLE001  bookkeeping must not break the platform loop
                pass
        return out.to_contract()

    return evaluate
