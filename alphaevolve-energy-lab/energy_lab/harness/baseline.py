"""Refuse to start on an unlocked baseline.

Before any run the recorded seed and null scores must reproduce to the yen (1e-6 JPY M) on the frozen
train instance, the instance hash must match the one recorded at lock time, and the seed must differ
from the null. An evaluator that cannot separate seed from null cannot grade a search.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Callable

from ..problems.base import ProblemSpec, load_manifest
from .contract import EvalOutcome

TOL = 1e-6  # JPY M == 1 JPY


class BaselineLockError(RuntimeError):
    pass


def _objective(o: EvalOutcome) -> float | None:
    """Seed/null comparisons use the raw objective so a null that trips a policy is still comparable."""
    return o.raw_score if o.raw_score is not None else o.score


def record_baseline(spec: ProblemSpec, fold: str = "train") -> dict:
    seed = spec.evaluate(spec.seed_src, fold=fold)
    null = spec.evaluate(spec.null_src, fold=fold)
    if not seed.valid:
        raise BaselineLockError(f"seed is invalid on {fold}: {seed.insights[:2]}")
    inst = load_manifest()["instances"][f"{spec.name}_{fold}"]
    lock = {
        "problem": spec.name, "fold": fold, "instance_sha256": inst["sha256"],
        "seed_score": seed.score, "seed_raw": _objective(seed),
        "null_score": null.score, "null_raw": _objective(null), "null_valid": null.valid,
        "null_insights": [{"label": l, "text": t} for l, t in null.insights[:6]],
        "seed_metrics": seed.metrics, "null_metrics": null.metrics,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    spec.baseline_lock_path.write_text(json.dumps(lock, indent=1))
    return lock


def verify_baseline(spec: ProblemSpec, evaluate: Callable[..., EvalOutcome] | None = None,
                    fold: str = "train") -> dict:
    """Raise BaselineLockError unless seed and null reproduce exactly and differ. Returns the lock report."""
    evaluate = evaluate or spec.evaluate
    if not spec.baseline_lock_path.exists():
        raise BaselineLockError(f"no baseline lock for {spec.name}: run `python -m energy_lab.harness.run --lock`")
    lock = json.loads(spec.baseline_lock_path.read_text())
    inst = load_manifest()["instances"][f"{spec.name}_{fold}"]
    if inst["sha256"] != lock["instance_sha256"]:
        raise BaselineLockError(f"instance hash changed since the lock ({inst['sha256'][:12]} != "
                                f"{lock['instance_sha256'][:12]}); re-lock deliberately after review")
    seed = evaluate(spec.seed_src, fold=fold)
    null = evaluate(spec.null_src, fold=fold)
    problems = []
    if not seed.valid:
        problems.append(f"seed is invalid now: {seed.insights[:1]}")
    s_now, n_now = _objective(seed), _objective(null)
    if s_now is None or abs(s_now - lock["seed_raw"]) > TOL:
        problems.append(f"seed does not reproduce: {s_now} vs locked {lock['seed_raw']}")
    if (n_now is None) != (lock["null_raw"] is None) or (n_now is not None and abs(n_now - lock["null_raw"]) > TOL):
        problems.append(f"null does not reproduce: {n_now} vs locked {lock['null_raw']}")
    if null.valid != lock["null_valid"]:
        problems.append(f"null validity changed: {null.valid} vs locked {lock['null_valid']}")
    if s_now is not None and n_now is not None and abs(s_now - n_now) <= TOL:
        problems.append("seed and null score the same: the evaluator cannot separate them")
    if problems:
        raise BaselineLockError("baseline lock failed: " + "; ".join(problems))
    return {"reproduced": True, "seed_score": seed.score, "seed_raw": s_now, "null_score": null.score,
            "null_raw": n_now, "null_valid": null.valid, "instance_sha256": inst["sha256"],
            "seed_minus_null": None if n_now is None else s_now - n_now,
            "seed_metrics": seed.metrics, "null_metrics": null.metrics,
            "null_insights": [{"label": l, "text": t} for l, t in null.insights[:6]]}
