"""jepx_trading evaluator: sandboxed strategy -> trusted day-by-day simulation -> policy invariants -> score."""
from __future__ import annotations

import time
from functools import lru_cache

import numpy as np

from ...harness.contract import (KIND_DETERMINISM, KIND_FORMAT, KIND_INSTANCE, KIND_POLICY, KIND_SANDBOX, EvalOutcome,
                                 invalid)
from ...harness.sandbox import SandboxError, SandboxLimits, SandboxSession
from ..base import InstanceError, load_instance
from .sim import FormatError, TradingSim

LIMITS = SandboxLimits(wall_s=120.0, call_timeout_s=10.0, cpu_s=100, mem_mb=1024)


@lru_cache(maxsize=4)
def _sim(fold: str, sha: str) -> TradingSim:
    arr, _ = load_instance(f"jepx_trading_{fold}")
    return TradingSim(arr)


def evaluate(src: str, fold: str = "train", collect_days: bool = False) -> EvalOutcome:
    t0 = time.monotonic()
    try:
        _, sha = load_instance(f"jepx_trading_{fold}")
    except InstanceError as e:
        return invalid(KIND_INSTANCE, "instance", str(e))
    sim = _sim(fold, sha)
    try:
        with SandboxSession(src, LIMITS) as sb:
            ctx0 = sim.da_ctx(0, sim.b["soc_start_frac"] * sim.E, 1e9)
            probe_a = sb.call("plan_day_ahead", ctx0)
            probe_b = sb.call("plan_day_ahead", ctx0)
            if probe_a != probe_b:
                return invalid(KIND_DETERMINISM, "determinism", "plan_day_ahead returned different plans for identical ctx")
            res = sim.run(sb, collect_days=collect_days)
    except SandboxError as e:
        return invalid(KIND_SANDBOX, "sandbox", f"{e.etype}: {e}")
    except FormatError as e:
        return invalid(KIND_FORMAT, "format", str(e))
    try:
        _, sha_after = load_instance(f"jepx_trading_{fold}")
    except InstanceError as e:
        return invalid(KIND_INSTANCE, "instance", str(e))
    if sha_after != sha:
        return invalid(KIND_INSTANCE, "instance", "instance hash changed during evaluation")
    metrics = {k: res[k] for k in ("annual_cost_jpy_m", "risk_penalty_jpy_m", "da_cost_jpy_m", "id_cost_jpy_m",
                                   "imbalance_cost_jpy_m", "degradation_jpy_m", "terminal_soc_jpy_m", "benchmark_jpy_m",
                                   "cost_vs_benchmark_jpy_kwh", "unit_cost_jpy_kwh", "imbalance_abs_share",
                                   "id_volume_share", "bess_cycles_per_day", "worst_day_excess_jpy_m")}
    insights = [
        ("score_components", f"annual cost {res['annual_cost_jpy_m']:.1f} + risk penalty {res['risk_penalty_jpy_m']:.1f} "
                             f"=> score {res['score']:.1f} JPY M; vs buy-actual-at-DA benchmark "
                             f"{res['cost_vs_benchmark_jpy_kwh']:+.3f} JPY/kWh"),
        ("cost_breakdown", f"DA {res['da_cost_jpy_m']:.1f}, intraday {res['id_cost_jpy_m']:.1f}, imbalance "
                           f"{res['imbalance_cost_jpy_m']:.1f}, degradation {res['degradation_jpy_m']:.1f}, terminal SOC "
                           f"{res['terminal_soc_jpy_m']:.1f} JPY M/yr"),
        ("operations", f"|imbalance| {res['imbalance_abs_share']:.2%} of load; intraday volume {res['id_volume_share']:.2%}; "
                       f"BESS {res['bess_cycles_per_day']:.2f} cycles/day; worst day {res['worst_day']} excess "
                       f"{res['worst_day_excess_jpy_m']:.1f} JPY M"),
    ]
    details = {"eval_s": round(time.monotonic() - t0, 3), "fold": fold, "instance_sha256": sha,
               "violations": res["violations"], "n_days": res["n_days"]}
    if collect_days:
        details["days"] = res["days"]
    if res["violations"]:
        ins = [(f"policy: {v['invariant']}", v["text"]) for v in res["violations"]] + [
            ("raw_objective", f"would have scored {res['score']:.1f} JPY M without the policy gate")] + insights
        return EvalOutcome(score=None, kind=KIND_POLICY, insights=ins, metrics=metrics, details=details, raw_score=res["score"])
    return EvalOutcome(score=res["score"], insights=insights, metrics=metrics, details=details, raw_score=res["score"])


def descriptor(out: EvalOutcome) -> tuple[int, int]:
    c = out.metrics.get("bess_cycles_per_day", 0.0) or 0.0
    v = out.metrics.get("id_volume_share", 0.0) or 0.0
    return int(np.digitize(c, [0.3, 0.7, 1.2])), int(np.digitize(v, [0.005, 0.015, 0.03]))
