"""CLI for the AlphaEvolve Energy Lab harness.

    python -m energy_lab.harness.run --lock                      # record baseline locks (after data/generate.py)
    python -m energy_lab.harness.run --verify                    # verify both locks (refuses on mismatch)
    python -m energy_lab.harness.run --problem tariff_pricing    # live run, local Gemini controller (default backend)
    python -m energy_lab.harness.run --problem jepx_trading --backend alphaevolve   # production path (needs GE_APP_ID)
    python -m energy_lab.harness.run --problem tariff_pricing --dry-run            # offline mutator, never evidence
    python -m energy_lab.harness.run --budget                    # ledger usage today
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone

from ..config import PROBLEMS
from ..problems import get_problem
from .baseline import BaselineLockError, record_baseline, verify_baseline
from .budget import JST, BudgetExceeded, BudgetPolicy, Ledger


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="energy_lab.harness.run")
    ap.add_argument("--problem", choices=PROBLEMS)
    ap.add_argument("--backend", choices=("local", "alphaevolve"), default="local")
    ap.add_argument("--max-programs", type=int, default=None)
    ap.add_argument("--islands", type=int, default=3)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--lock", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--budget", action="store_true")
    a = ap.parse_args(argv)
    probs = [a.problem] if a.problem else list(PROBLEMS)
    if a.lock:
        for p in probs:
            lock = record_baseline(get_problem(p))
            print(f"locked {p}: seed {lock['seed_score']:.3f} null_raw {lock['null_raw']:.3f} (null valid={lock['null_valid']})")
        return 0
    if a.verify:
        for p in probs:
            try:
                r = verify_baseline(get_problem(p))
                print(f"{p}: baseline reproduced (seed {r['seed_raw']:.6f}, null {r['null_raw']:.6f}, seed-null {r['seed_minus_null']:+.3f})")
            except BaselineLockError as e:
                print(f"{p}: REFUSED - {e}")
                return 2
        return 0
    if a.budget:
        led, pol = Ledger(), BudgetPolicy.from_env()
        day = datetime.now(timezone.utc).astimezone(JST).date().isoformat()
        for p in PROBLEMS:
            print(p, json.dumps({**led.usage(p, day), "policy": pol.__dict__}))
        return 0
    if not a.problem:
        ap.error("--problem is required for a run")
    spec = get_problem(a.problem)
    try:
        if a.backend == "alphaevolve":
            from .alphaevolve_adapter import AlphaEvolveUnavailable, run_alphaevolve

            try:
                rec = run_alphaevolve(spec, max_programs=a.max_programs)
            except AlphaEvolveUnavailable as e:
                print(f"REFUSED: {e}")
                return 3
        else:
            from .local_controller import run_local

            rec = run_local(spec, dry_run=a.dry_run, max_programs=a.max_programs, islands=a.islands, rng_seed=a.seed)
    except (BaselineLockError, BudgetExceeded) as e:
        print(f"REFUSED: {e}")
        return 2
    ho = rec.get("holdout") or {}
    print(json.dumps({"run_id": rec["run_id"], "source": rec["source"], "seed_train": (rec.get("seed") or {}).get("train"),
                      "best_train": (rec.get("best") or {}).get("train"), "holdout_seed": ho.get("seed"),
                      "best_holdout": ho.get("best_holdout"), "holdout_delta": ho.get("holdout_delta"),
                      "uplift_valid": rec.get("uplift_valid"), "invalid_by_kind": rec.get("invalid_by_kind"),
                      "tokens": rec.get("tokens")}, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
