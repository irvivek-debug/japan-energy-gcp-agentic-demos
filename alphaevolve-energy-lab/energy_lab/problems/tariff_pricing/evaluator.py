"""tariff_pricing evaluator: sandboxed price_book -> validation -> policy invariants -> FY2026 settlement -> score.

Policy invariants are declared as ``policy_ok(instance, solution) -> (ok, detail)`` functions and enforced at score
time. A violation makes the candidate invalid (score None) with an insight starting ``policy:`` so such candidates never
enter the population. The raw objective is still computed and recorded (``raw_score``) so evidence can show what a
violating candidate *would* have scored (e.g. a churn-driven "uplift").
"""
from __future__ import annotations

import json
import math
import time
from functools import lru_cache

import numpy as np

from ...harness.contract import (KIND_DETERMINISM, KIND_FORMAT, KIND_INSTANCE, KIND_POLICY, KIND_SANDBOX, EvalOutcome,
                                 invalid)
from ...harness.sandbox import SandboxError, SandboxLimits, SandboxSession
from ...sim.portfolio import SEGMENTS
from ..base import InstanceError, load_instance
from . import model as tm

LIMITS = SandboxLimits(wall_s=60.0, call_timeout_s=30.0, cpu_s=50, mem_mb=1024)
DETERMINISM_PROBE = 60


@lru_cache(maxsize=4)
def _prepared(fold: str, sha: str):
    arr, _ = load_instance(f"tariff_pricing_{fold}")
    fwd_P, fwd_W = arr["fwd_P"].astype(float), arr["fwd_W"].astype(float)
    pre = tm.prepare(arr, fwd_P, fwd_W, float(arr["sigma_f"]))
    feats = json.loads(str(arr["features_json"]))
    market = json.loads(str(arr["market_json"]))
    return pre, feats, market


def _validate(offers: list, n: int) -> list[str]:
    errs = []
    if not isinstance(offers, list) or len(offers) != n:
        return [f"price_book must return one dict per customer (got {type(offers).__name__})"]
    for i, o in enumerate(offers):
        if not isinstance(o, dict):
            errs.append(f"customer #{i}: offer is {type(o).__name__}, expected dict")
        else:
            missing = [k for k in tm.OFFER_KEYS if k not in o]
            if missing:
                errs.append(f"customer #{i}: missing keys {missing}")
            else:
                for k, (lo, hi) in tm.OFFER_BOUNDS.items():
                    v = o[k]
                    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
                        errs.append(f"customer #{i}: {k}={v!r} is not a finite number")
                    elif not (lo - 1e-9 <= float(v) <= hi + 1e-9):
                        errs.append(f"customer #{i}: {k}={v} outside [{lo}, {hi}]")
                if isinstance(o.get("term_years"), (int, float)) and float(o["term_years"]) not in (1.0, 2.0, 3.0):
                    errs.append(f"customer #{i}: term_years must be 1, 2 or 3 (got {o['term_years']})")
        if len(errs) >= 6:
            break
    return errs


# --- policy invariants: policy_ok(instance, solution) -> (ok, detail) ---------------------------------------------
def policy_essential_alpha(pre, o, feats, market, res):
    bad = np.where(pre.essential & (o["alpha"] > tm.POLICY["essential_alpha_max"] + 1e-9))[0]
    if bad.size:
        ex = [f"{feats[i]['segment']} alpha={o['alpha'][i]:.2f}" for i in bad[:3]]
        return False, {"invariant": "essential_alpha", "count": int(bad.size),
                       "text": f"{bad.size} essential-facility offers have alpha > 0.30 (e.g. {', '.join(ex)})"}
    return True, None


def policy_band(pre, o, feats, market, res):
    b = o["deviation_band_pct"]
    bad = np.where((b < tm.POLICY["band_min_pct"] - 1e-9) | (b > tm.POLICY["band_max_pct"] + 1e-9))[0]
    if bad.size:
        return False, {"invariant": "deviation_band", "count": int(bad.size),
                       "text": f"{bad.size} offers have deviation_band_pct outside [5, 10] (e.g. {b[bad[0]]:.2f})"}
    return True, None


def policy_fair_ceiling(pre, o, feats, market, res):
    ref = np.array([market["segment_reference_jpy_kwh"][f["segment"]][f["voltage"]] for f in feats])
    ratio = res["eff"] / ref
    bad = np.where(ratio > tm.POLICY["fair_ceiling_ratio"] + 1e-9)[0]
    if bad.size:
        i = bad[np.argmax(ratio[bad])]
        return False, {"invariant": "fair_price_ceiling", "count": int(bad.size),
                       "text": (f"{bad.size} customers priced above 1.25 x segment reference (worst: {feats[i]['segment']}/"
                                f"{feats[i]['voltage']} effective {res['eff'][i]:.2f} vs ref {ref[i]:.2f} JPY/kWh)")}
    return True, None


def policy_nondiscrimination(pre, o, feats, market, res):
    keys = [(f["segment"], f["voltage"], f["lf_band"], f["green_required"]) for f in feats]
    groups: dict = {}
    for i, k in enumerate(keys):
        groups.setdefault(k, []).append(i)
    worst, n_bad, ex = 0.0, 0, None
    for k, idx in groups.items():
        r = o["energy_rate_jpy_kwh"][idx]
        med = float(np.median(r))
        if med <= 0:
            continue
        dev = np.abs(r / med - 1.0)
        nb = int((dev > tm.POLICY["nondiscrimination_tol"] + 1e-9).sum())
        if nb:
            n_bad += nb
            if dev.max() > worst:
                worst = float(dev.max())
                ex = k
    if n_bad:
        return False, {"invariant": "non_discrimination", "count": n_bad,
                       "text": (f"{n_bad} energy rates deviate more than 8% from their group median (worst {worst:.1%} in "
                                f"group segment={ex[0]}, voltage={ex[1]}, lf_band={ex[2]}, green={ex[3]})")}
    return True, None


@lru_cache(maxsize=4)
def incumbent_segment_churn(fold: str, sha: str) -> dict:
    """Segment churn of the incumbent (seed) book on this fold's cohort. Trusted code: executed in-process, not sandboxed."""
    from .spec import SEED_PATH

    ns: dict = {"__name__": "incumbent_seed"}
    exec(compile(SEED_PATH.read_text(), str(SEED_PATH), "exec"), ns)
    pre, feats, market = _prepared(fold, sha)
    offers = [ns["price_book"](f, market) for f in feats]
    res = tm.settle(pre, tm.offers_to_arrays(offers), market["segment_reference_jpy_kwh"])
    return res["seg_churn"]


def churn_limits(fold: str) -> dict:
    lim = {k: tm.POLICY[k] for k in ("churn_max_portfolio", "churn_max_energy", "churn_max_segment")}
    if fold == "train":
        lim = {k: min(v, tm.TRAIN_CHURN_GUARD[k]) for k, v in lim.items()}
    return lim


def policy_churn(pre, o, feats, market, res, fold: str = "holdout", incumbent: dict | None = None):
    lim = churn_limits(fold)
    tag = " (train guard band)" if fold == "train" else ""
    msgs = []
    if incumbent:
        rises = [f"{k} {incumbent[k]:.1%} -> {v:.1%}" for k, v in res["seg_churn"].items()
                 if k in incumbent and v - incumbent[k] > tm.SEGMENT_CHURN_RISE_MAX + 1e-9]
        if rises:
            msgs.append(f"segment churn rises more than {tm.SEGMENT_CHURN_RISE_MAX:.0%} above the incumbent book: " + ", ".join(rises))
    if res["churn_count"] > lim["churn_max_portfolio"] + 1e-9:
        msgs.append(f"portfolio churn {res['churn_count']:.1%} > {lim['churn_max_portfolio']:.0%}{tag}")
    if res["churn_energy"] > lim["churn_max_energy"] + 1e-9:
        msgs.append(f"energy-weighted churn {res['churn_energy']:.1%} > {lim['churn_max_energy']:.0%}{tag}")
    segs = [f"{k} {v:.1%}" for k, v in res["seg_churn"].items() if v > lim["churn_max_segment"] + 1e-9]
    if segs:
        msgs.append(f"segment churn > {lim['churn_max_segment']:.0%}{tag}: " + ", ".join(segs))
    if msgs:
        return False, {"invariant": "churn", "count": len(msgs),
                       "text": "; ".join(msgs) + " (pricing customers out is a strategy change, not an uplift)"}
    return True, None


POLICIES = (policy_essential_alpha, policy_band, policy_fair_ceiling, policy_nondiscrimination, policy_churn)


def evaluate(src: str, fold: str = "train") -> EvalOutcome:
    t0 = time.monotonic()
    try:
        arr, sha = load_instance(f"tariff_pricing_{fold}")
    except InstanceError as e:
        return invalid(KIND_INSTANCE, "instance", str(e))
    pre, feats, market = _prepared(fold, sha)
    try:
        with SandboxSession(src, LIMITS) as sb:
            sb.put("market", market)
            offers = sb.map("price_book", feats, shared=("market",))
            again = sb.map("price_book", feats[:DETERMINISM_PROBE], shared=("market",))
    except SandboxError as e:
        return invalid(KIND_SANDBOX, "sandbox", f"{e.etype}: {e}")
    if json.dumps(offers[:DETERMINISM_PROBE], sort_keys=True, default=str) != json.dumps(again, sort_keys=True, default=str):
        return invalid(KIND_DETERMINISM, "determinism", "price_book returned different offers for identical inputs")
    errs = _validate(offers, len(feats))
    if errs:
        return invalid(KIND_FORMAT, "format", "; ".join(errs))
    o = tm.offers_to_arrays(offers)
    res = tm.settle(pre, o, market["segment_reference_jpy_kwh"])
    violations = []
    incumbent = incumbent_segment_churn(fold, sha)
    for pol in POLICIES:
        ok, detail = (pol(pre, o, feats, market, res, fold, incumbent) if pol is policy_churn
                      else pol(pre, o, feats, market, res))
        if not ok:
            violations.append(detail)
    try:  # the frozen instance must be unchanged after the candidate ran (tamper / look-ahead guard)
        _, sha_after = load_instance(f"tariff_pricing_{fold}")
    except InstanceError as e:
        return invalid(KIND_INSTANCE, "instance", str(e))
    if sha_after != sha:
        return invalid(KIND_INSTANCE, "instance", "instance hash changed during evaluation")
    metrics = {"expected_margin_jpy_m": res["expected_margin"], "cvar95_shortfall_jpy_m": res["cvar95_shortfall"],
               "ltv_jpy_m": res["ltv"], "worst_scenario_margin_jpy_m": res["worst_margin"],
               "churn_count": res["churn_count"], "churn_energy": res["churn_energy"], "mean_alpha": res["mean_alpha"],
               "dr_enrolled_mw": res["dr_enrolled_mw"], "flex_value_jpy_m": res["flex_value_retailer"],
               "imbalance_cost_jpy_m": res["imbalance_cost"], "penalty_revenue_jpy_m": res["penalty_revenue"],
               "retained_twh": res["retained_twh"], "margin_per_kwh": res["margin_per_kwh"]}
    worst_seg = max(res["seg_churn"].items(), key=lambda kv: kv[1])
    insights = [
        ("score_components", f"E[margin] {res['expected_margin']:.1f} - 0.5 x CVaR95 {res['cvar95_shortfall']:.1f} + LTV "
                             f"{res['ltv']:.1f} = {res['score']:.1f} JPY M"),
        ("risk", f"worst scenario margin {res['worst_margin']:.1f} JPY M; energy-weighted mean alpha {res['mean_alpha']:.2f}"),
        ("retention", f"churn {res['churn_count']:.1%} by count, {res['churn_energy']:.1%} by energy; highest segment "
                      f"{worst_seg[0]} {worst_seg[1]:.1%}; retained {res['retained_twh']:.2f} TWh"),
        ("levers", f"DR enrolled {res['dr_enrolled_mw']:.1f} MW; retailer flex value {res['flex_value_retailer']:.1f} JPY M; "
                   f"imbalance cost {res['imbalance_cost']:.1f} JPY M; penalty revenue {res['penalty_revenue']:.1f} JPY M; "
                   f"margin {res['margin_per_kwh']:.2f} JPY/kWh"),
        ("segments", "churn by segment: " + ", ".join(f"{k} {v:.0%}" for k, v in res["seg_churn"].items())),
    ]
    details = {"eval_s": round(time.monotonic() - t0, 3), "fold": fold, "instance_sha256": sha,
               "evaluator_version": tm.EVALUATOR_VERSION, "churn_limits": churn_limits(fold),
               "seg_churn": res["seg_churn"], "violations": violations}
    if violations:
        ins = [(f"policy: {v['invariant']}", v["text"]) for v in violations] + [
            ("raw_objective", f"would have scored {res['score']:.1f} JPY M without the policy gate")] + insights[:3]
        return EvalOutcome(score=None, kind=KIND_POLICY, insights=ins, metrics=metrics, details=details,
                           raw_score=res["score"])
    return EvalOutcome(score=res["score"], insights=insights, metrics=metrics, details=details, raw_score=res["score"])


def descriptor(out: EvalOutcome) -> tuple[int, int]:
    a = out.metrics.get("mean_alpha", 0.0) or 0.0
    c = out.metrics.get("churn_count", 0.0) or 0.0
    return int(np.digitize(a, [0.15, 0.35, 0.6])), int(np.digitize(c, [0.06, 0.09, 0.12]))
