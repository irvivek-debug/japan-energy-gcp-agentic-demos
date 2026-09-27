"""Read-only endpoints for UI version 2 (landing, case chapters, workspace). Every figure the v2 pages show comes from
here or from the v1 endpoints; this module computes from the lab tables, the evidence files in runs/, eval/results and
the MARKET_FACTS-derived constants in energy_lab/sim/facts.py. Nothing here writes.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException

from energy_lab.config import RUNS_DIR, SOURCE_ALPHAEVOLVE
from energy_lab.harness.budget import BudgetPolicy, Ledger
from energy_lab.harness.evidence import list_evidence, load_run, promotion_gate, reviews_for
from energy_lab.segment_judgments import evidence_caveat
from energy_lab.sim import facts
from energy_lab.sim.instances import SEEDS
from energy_lab.store import STORE, src

ROOT = Path(__file__).resolve().parent.parent
router = APIRouter(prefix="/api/v2")
HONESTY = "local controller, not the managed AlphaEvolve service"
RAW_RE = re.compile(r"would have scored (-?[\d,]+\.?\d*) JPY M")
NO_BENCH = "NO VERIFIED BENCHMARK HELD"


def _finished() -> list[dict]:
    recs = [r for r in list_evidence(RUNS_DIR, include_partial=False) if r.get("status") == "finished"]
    return sorted(recs, key=lambda r: r.get("started") or "")


def _by_problem(recs: list[dict], problem: str, searched_only: bool = False) -> list[dict]:
    return [r for r in recs if r["problem"] == problem and (not searched_only or not _infra_failure(r))]


def _infra_failure(r: dict) -> bool:
    """A run in which no program was ever generated (every model call failed): not a search result."""
    kinds = r.get("invalid_by_kind") or {}
    return (r.get("valid_count") or 0) == 0 and bool(kinds) and set(kinds) <= {"generation"}


def _raw_holdout(row: dict) -> float | None:
    """Raw objective of a holdout row: its score if valid, else the pre-gate objective printed by the evaluator."""
    if row.get("holdout") is not None:
        return row["holdout"]
    for ins in row.get("holdout_insights") or []:
        m = RAW_RE.search(ins.get("text", ""))
        if m:
            return float(m.group(1).replace(",", ""))
    return None


def _run_brief(r: dict) -> dict:
    ho = r.get("holdout") or {}
    champ = next((x for x in ho.get("top_k", []) if x["id"] == ho.get("best_id")), None)
    raw = _raw_holdout(champ) if champ else None
    infra = _infra_failure(r)
    return {"run_id": r["run_id"], "problem": r["problem"], "source": r.get("source"), "provenance": HONESTY,
            "infrastructure_failure": infra,
            "status_label": ("INFRASTRUCTURE FAILURE: no program was generated" if infra else
                             "VALIDATED ON HOLDOUT" if r.get("uplift_valid") else "NO VALIDATED UPLIFT"),
            "evaluator_version": (r.get("evaluator_version") or "v1").split(":")[0],
            "holdout_fold": ho.get("fold", "holdout"), "programs": (r.get("budget") or {}).get("programs_evaluated"),
            "seed_train": (r.get("seed") or {}).get("train"), "best_train": (r.get("best") or {}).get("train"),
            "holdout_seed": ho.get("seed"), "best_holdout": ho.get("best_holdout"), "holdout_delta": ho.get("holdout_delta"),
            "champion_raw_holdout": raw,
            "champion_raw_delta": (raw - ho["seed"]) if (raw is not None and ho.get("seed") is not None) else None,
            "uplift_valid": r.get("uplift_valid"), "invalid_by_kind": r.get("invalid_by_kind") or {},
            "caveat": _margin_caveat(r) if r.get("uplift_valid") else None,
            "cost_usd": (r.get("tokens") or {}).get("cost_usd"), "started": r.get("started")}


def _margin_caveat(r: dict) -> str | None:
    """If a validated champion passed a per-segment churn rule only thanks to the sampling margin, say so. Same function
    and words as the lab tables (energy_lab.segment_judgments), computed from the run's stored holdout segment tests."""
    return evidence_caveat(r)


def _q1(sql: str, **p) -> dict:
    rows = STORE.query(sql, **p)
    return rows[0] if rows else {}


def _cal(metric: str, fy: int) -> dict:
    return _q1("SELECT synthetic, target, market_facts_section FROM {t:calibration} WHERE metric = @m AND fiscal_year = @fy",
               m=metric, fy=fy)


def _policy_catches(recs: list[dict]) -> dict:
    total, by_inv, reached = 0, {}, 0
    for r in recs:
        for p in r.get("programs", [])[1:]:
            if p.get("kind") == "policy":
                total += 1
                for v in p.get("violations") or []:
                    by_inv[v.get("invariant")] = by_inv.get(v.get("invariant"), 0) + 1
            if p.get("kind") != "ok" and p.get("score") is not None:
                reached += 1
    return {"candidates": total, "by_invariant": by_inv, "invalid_that_reached_population": reached}


# ---------------------------------------------------------------------------------------------------------------------
@router.get("/landing")
def landing():
    recs = _finished()
    tp, jt = _by_problem(recs, "tariff_pricing", True), _by_problem(recs, "jepx_trading", True)
    fy25 = _q1("SELECT AVG(tokyo_price_jpy_kwh) AS v FROM {t:market_history} WHERE fiscal_year = 2025").get("v")
    reg = _cal("holdout_realised_like_H1_mean", 2026)
    t_last = _run_brief(tp[-1]) if tp else {}
    j_valid = [_run_brief(r) for r in jt if r.get("uplift_valid")]
    j_best = max(j_valid, key=lambda b: b["holdout_delta"]) if j_valid else (_run_brief(jt[-1]) if jt else {})
    t_seed_cvar = (tp[-1]["seed"]["metrics"].get("cvar95_shortfall_jpy_m") if tp else None)
    t_best_cvar = ((tp[-1].get("best") or {}).get("metrics") or {}).get("cvar95_shortfall_jpy_m") if tp else None
    catches = _policy_catches(recs)
    searched = [r for r in recs if not _infra_failure(r)]
    zero_program = [r["run_id"] for r in recs if _infra_failure(r)]
    # programs actually generated and scored: failed model calls are budget, not programs
    total_programs = sum(((r.get("budget") or {}).get("programs_evaluated") or 0)
                         - ((r.get("invalid_by_kind") or {}).get("generation") or 0) for r in searched)
    t_valid = [_run_brief(r) for r in tp if r.get("uplift_valid")]
    rows = [
        {"id": "price_regime", "quantity": "Tokyo spot price level", "unit": "JPY/kWh",
         "ordinary": {"value": fy25, "label": "FY2025, history in this data"},
         "best": {"value": reg.get("synthetic"), "label": "FY2026 Apr-Sep regime, holdout scenario bank"},
         "gap": (reg.get("synthetic") - fy25) if (reg and fy25 is not None) else None,
         "research": {"text": f"FY2025 {facts.TOKYO_ANNUAL_MEAN[2025]:.2f}; FY2026 Apr-Sep {facts.TOKYO_FY2026_TO_DATE_MEAN:.2f} JPY/kWh",
                      "source": "MARKET_FACTS 1.2, VERIFIED (computed from JEPX)"}},
        {"id": "tariff_tail_risk", "quantity": "Tail risk of the cost-plus renewal book (CVaR95 shortfall)", "unit": "JPY M",
         "ordinary": {"value": t_seed_cvar, "label": "cost-plus seed book, train scenarios"},
         "best": {"value": t_best_cvar, "label": f"latest tariff champion, train only ({t_last.get('run_id', 'none')})"},
         "gap": (t_best_cvar - t_seed_cvar) if (t_best_cvar is not None and t_seed_cvar is not None) else None,
         "research": {"text": "TEPCO EP has offered a 100% spot-linked high-voltage plan since FY2024",
                      "source": "MARKET_FACTS 5.4, VERIFIED"}},
        {"id": "tariff_holdout", "quantity": "Tariff book on unseen customers and scenarios (score)", "unit": "JPY M",
         "ordinary": {"value": t_last.get("holdout_seed"), "label": f"seed on {t_last.get('holdout_fold', 'holdout')}"},
         "best": {"value": t_last.get("best_holdout"), "label": "champion, only if it keeps every invariant"},
         "gap": t_last.get("holdout_delta"), "validated": bool(t_valid), "caveat": t_last.get("caveat"),
         "research": {"text": NO_BENCH, "source": ""}},
        {"id": "trading_holdout", "quantity": "Trading cost to serve on held-out days (score, higher is better)", "unit": "JPY M/yr",
         "ordinary": {"value": j_best.get("holdout_seed"), "label": "seed strategy"},
         "best": {"value": j_best.get("best_holdout"), "label": f"best validated champion ({j_best.get('run_id', 'none')})"},
         "gap": j_best.get("holdout_delta"), "validated": bool(j_valid),
         "research": {"text": (f"2 h battery perfect-foresight arbitrage bound about {facts.PERFECT_FORESIGHT_2H_JPY_KWH_CAP_YR[2025]:,} "
                               f"JPY/kWh-cap/yr in FY2025; real bots capture {facts.REAL_CAPTURE_OF_PERFECT_FORESIGHT[0]:.0%} to "
                               f"{facts.REAL_CAPTURE_OF_PERFECT_FORESIGHT[1]:.0%}"), "source": "MARKET_FACTS 12, ESTIMATE"}},
        {"id": "caught", "quantity": "Rule-breaking candidates caught before scoring", "unit": "candidates",
         "ordinary": {"value": catches["candidates"], "label": f"caught across {len(searched)} searched runs"},
         "best": {"value": catches["invalid_that_reached_population"], "label": "reached the population"},
         "gap": None, "research": {"text": facts.IMBALANCE_IMPROPER_CONDUCT.capitalize(), "source": "MARKET_FACTS 3, VERIFIED"}},
    ]
    note = ("The gap is what this data shows between the cost-plus / rule-based seeds and the evolved programs, judged on "
            "customers and days the search never saw. It is not a forecast for any real company: the data is calibrated "
            "synthetic data and every run used the " + HONESTY + ".")
    return {"product": "AlphaEvolve Energy Lab", "provenance_label": HONESTY,
            "hero": {"fy2025_tokyo_mean": fy25, "fy2026_regime_mean": reg.get("synthetic"),
                     "fy2026_research": facts.TOKYO_FY2026_TO_DATE_MEAN, "runs": len(searched), "programs": total_programs,
                     "zero_program_attempts": len(zero_program),
                     "trading_best_delta": j_best.get("holdout_delta"), "tariff_validated": bool(t_valid),
                     "policy_catches": catches["candidates"]},
            "gap_rows": rows, "gap_note": note,
            "doors": {"case": [{"label": "searched runs", "value": len(searched), "unit": ""},
                               {"label": "candidates caught by a rule", "value": catches["candidates"], "unit": ""},
                               {"label": "validated trading holdout runs", "value": len(j_valid), "unit": ""}],
                      "workspace": [{"label": "agent teams", "value": 2, "unit": ""},
                                    {"label": "roles", "value": len(_personas()["personas"]), "unit": ""},
                                    {"label": "runs awaiting human review", "value": sum(1 for r in searched if not reviews_for(r["run_id"], RUNS_DIR)), "unit": ""}]},
            "generator": {"history_seed": SEEDS["history"], "seeds": dict(SEEDS), "source": "energy_lab/sim/instances.py SEEDS"},
            "source": src("market_history", "calibration") + ["runs/*.json"]}


@lru_cache(maxsize=1)
def _evidence_series() -> dict:
    rows = STORE.query(
        "SELECT date, AVG(tokyo_price_jpy_kwh) AS tokyo_mean, MAX(tokyo_price_jpy_kwh) AS tokyo_max, "
        "MAX(imbalance_price_jpy_kwh) AS imbalance_max, MIN(reserve_margin_pct) AS rm_min, MAX(area_demand_gw) AS area_peak, "
        "AVG(kbg_demand_mw) AS kbg_mean, SUM(area_pv_gw) / SUM(area_demand_gw) AS pv_share FROM {t:market_history} "
        "GROUP BY date ORDER BY date")
    dates = [r["date"] for r in rows]

    def col(k, scale=1.0, nd=3):
        return [None if r[k] is None else round(float(r[k]) * scale, nd) for r in rows]

    series = [
        {"id": "tokyo_mean", "label": "Tokyo spot, daily mean", "unit": "JPY/kWh", "values": col("tokyo_mean"),
         "status": [{"min": 20, "label": "HIGH"}, {"min": 0, "label": "NORMAL"}]},
        {"id": "tokyo_max", "label": "Tokyo spot, daily max", "unit": "JPY/kWh", "values": col("tokyo_max", nd=2),
         "status": [{"min": 40, "label": "SPIKE"}, {"min": 0, "label": "NORMAL"}]},
        {"id": "imbalance_max", "label": "Imbalance price, daily max", "unit": "JPY/kWh", "values": col("imbalance_max", nd=2),
         "status": [{"min": 45, "label": "SCARCITY PRICING"}, {"min": 0, "label": "NORMAL"}]},
        {"id": "rm_min", "label": "Wide-area reserve margin, daily min", "unit": "%", "values": col("rm_min", nd=2),
         "status": [{"max": 8, "label": "TIGHT"}, {"max": 10, "label": "WATCH"}, {"max": 1e9, "label": "NORMAL"}]},
        {"id": "area_peak", "label": "TEPCO area demand, daily peak", "unit": "GW", "values": col("area_peak", nd=2),
         "status": [{"min": 52, "label": "PEAK"}, {"min": 0, "label": "NORMAL"}]},
        {"id": "kbg_mean", "label": "KBG balance-group load, daily mean", "unit": "MW", "values": col("kbg_mean", nd=1),
         "status": [{"min": 0, "label": "METERED"}]},
    ]
    return {"dates": dates, "window": {"from": dates[0], "to": dates[-1], "days": len(dates)}, "series": series,
            "status_rule": "first matching threshold wins (min: value >= min; max: value < max)",
            "source": src("market_history")}


@router.get("/evidence")
def evidence():
    return _evidence_series()


@router.get("/prize")
def prize():
    recs = _finished()
    tp, jt = _by_problem(recs, "tariff_pricing", True), _by_problem(recs, "jepx_trading", True)
    j_valid = [_run_brief(r)["holdout_delta"] for r in jt if r.get("uplift_valid")]
    t_valid = [_run_brief(r)["holdout_delta"] for r in tp if r.get("uplift_valid")]
    t_caveats = [c for c in (_margin_caveat(r) for r in tp if r.get("uplift_valid")) if c]
    t_raw = [b["champion_raw_delta"] for b in (_run_brief(r) for r in tp) if b["champion_raw_delta"] is not None]
    t_cvar = [(r["seed"]["metrics"]["cvar95_shortfall_jpy_m"] - (r.get("best") or {}).get("metrics", {}).get("cvar95_shortfall_jpy_m", 0))
              for r in tp if (r.get("best") or {}).get("metrics")]
    fleet_kwh = 180_000.0
    lo_c, hi_c = facts.REAL_CAPTURE_OF_PERFECT_FORESIGHT
    bound25 = facts.PERFECT_FORESIGHT_2H_JPY_KWH_CAP_YR[2025] * fleet_kwh / 1e6
    bound26 = facts.PERFECT_FORESIGHT_2H_FY2026_JPY_KWH_CAP_DAY * 365 * fleet_kwh / 1e6
    rows = [
        {"code": "APQC 4.0", "branch": "Deliver: day-ahead, intraday and battery for the balance group", "colour": "b1",
         "mechanism": "evolved bidding and battery dispatch inside the compliance band", "unit": "JPY M/yr",
         "low": min(j_valid) if j_valid else None, "high": max(j_valid) if j_valid else None,
         "basis": f"holdout deltas of {len(j_valid)} validated trading runs (FY2025 + 16 stress days, annualised); {HONESTY}",
         "citable": bool(j_valid), "status": "VALIDATED ON HOLDOUT" if j_valid else "NOT IN THE DATA"},
        {"code": "APQC 10.0", "branch": "Assets: battery arbitrage headroom for a 180 MWh fleet", "colour": "b2",
         "mechanism": "wholesale-only arbitrage, 60 to 80% of the perfect-foresight bound", "unit": "JPY M/yr",
         "low": bound25 * lo_c, "high": bound26 * hi_c,
         "basis": "MARKET_FACTS 12 ESTIMATE: FY2025 bound x 60% to FY2026-regime bound x 80%, times the fleet's 180 MWh",
         "citable": True, "status": "RESEARCH ESTIMATE"},
        {"code": "APQC 3.0", "branch": "Market and sell: the C&I renewal book", "colour": "b3",
         "mechanism": "market-link share by risk appetite, segment margins, DR value sharing", "unit": "JPY M",
         "low": (min(t_valid) if t_valid else (min(t_raw) if t_raw else None)),
         "high": (max(t_valid) if t_valid else (max(t_raw) if t_raw else None)),
         "caveat": "; ".join(t_caveats) or None,
         "basis": (f"holdout deltas of {len(t_valid)} validated tariff run(s) on holdout3 (1,200 customers, pre-registered); "
                   f"{HONESTY}" if t_valid else
                   "RAW potential: champion's holdout objective before the policy gate minus the seed; the champions broke "
                   "segment-retention invariants on holdout, so this is NOT CITABLE"),
         "citable": bool(t_valid), "status": "VALIDATED ON HOLDOUT" if t_valid else "RAW, NOT CITABLE"},
        {"code": "APQC 11.0", "branch": "Risk: tail risk of the renewal book (CVaR95 shortfall reduction)", "colour": "b4",
         "mechanism": "moving fixed-price exposure to the market-linked share", "unit": "JPY M",
         "low": min(t_cvar) if t_cvar else None, "high": max(t_cvar) if t_cvar else None,
         "basis": "train fold only (seed minus champion CVaR95); not validated on holdout", "citable": False,
         "status": "TRAIN ONLY, NOT CITABLE"},
    ]
    searched = [r for r in recs if not _infra_failure(r)]
    costs = [(r.get("tokens") or {}).get("cost_usd") for r in searched if (r.get("tokens") or {}).get("cost_usd") is not None]
    return {"rows": rows, "cost_of_search": {"runs": len(searched), "usd_low": min(costs) if costs else None,
                                             "usd_high": max(costs) if costs else None, "usd_total": sum(costs) if costs else None,
                                             "zero_program_attempts": len(recs) - len(searched),
                                             "basis": "per searched run; token counts x assumed list prices "
                                                      "(model_policy.PRICING_NOTE); zero-program attempts cost nothing"},
            "rule": "Only ranges marked citable may be quoted; everything else is labelled as raw or train-only.",
            "provenance_label": HONESTY, "source": ["runs/*.json", "energy_lab/sim/facts.py (MARKET_FACTS)"]}


@lru_cache(maxsize=1)
def _personas() -> dict:
    return json.loads((ROOT / "energy_lab" / "personas.json").read_text())


@router.get("/personas")
def personas():
    recs = _finished()
    out = []
    for p in _personas()["personas"]:
        latest = {}
        for prob in p["problems"]:
            rs = _by_problem(recs, prob, True)
            if rs:
                latest[prob] = _run_brief(rs[-1])
        out.append({**p, "latest_runs": latest})
    return {"personas": out, "source": _personas()["source"]}


@router.get("/teams")
def teams():
    from energy_lab import model_policy
    from energy_lab.harness.alphaevolve_adapter import preflight
    from energy_lab.tools.lab_tools import ALL_TOOLS

    recs = _finished()
    progs = sum((r.get("budget") or {}).get("programs_evaluated") or 0 for r in recs)
    kinds: dict = {}
    for r in recs:
        for k, v in (r.get("invalid_by_kind") or {}).items():
            kinds[k] = kinds.get(k, 0) + v
    rescored = sum(len((r.get("holdout") or {}).get("top_k", [])) for r in recs)
    reviews = sum(len(reviews_for(r["run_id"], RUNS_DIR)) for r in recs)
    pf = preflight()
    led, pol = Ledger(), BudgetPolicy.from_env()
    from datetime import datetime, timezone

    from energy_lab.harness.budget import JST

    day = datetime.now(timezone.utc).astimezone(JST).date().isoformat()
    usage = {p: led.usage(p, day) for p in ("tariff_pricing", "jepx_trading")}
    mix = model_policy.mutator_mix()
    loop = {"id": "evolution_loop", "name": "Evolution loop", "provenance": HONESTY,
            "stages": [
                {"step": 1, "role": "The lead", "name": "Local controller", "detail": "islands + MAP-Elites-lite, picks parents and inspirations",
                 "stat": {"label": "programs generated", "value": progs}},
                {"step": 2, "role": "Specialists, working together", "name": "Mutators, sandbox, evaluator",
                 "detail": " / ".join(f"{m['name']} {m['weight']:.0%}" for m in mix) + "; fresh subprocess per candidate; trusted simulator",
                 "stat": {"label": "invalid by kind", "value": kinds}},
                {"step": 3, "role": "The reviewer", "name": "Policy invariants + holdout rescoring",
                 "detail": "rule-breaking candidates never enter the population; top 5 rescored on unseen data",
                 "stat": {"label": "holdout rescores", "value": rescored}},
                {"step": 4, "role": "Your sign-off", "name": "Human review (2 s hold)", "detail": "append-only audit; never promotes",
                 "stat": {"label": "reviews recorded", "value": reviews}}]}
    analyst = {"id": "lab_analyst", "name": "Lab Analyst", "pattern": "B (single agent, balanced tier)",
               "model": model_policy.ANALYST_MODEL, "tools": [f.__name__ for f in ALL_TOOLS],
               "signoff_tools": ["propose_human_review"], "reads": sorted({t for t in STORE.schema if t.startswith("lab_")} |
                                                                        {"market_history", "scenario_monthly", "customers_train", "cost_stack", "calibration"}),
               "stages": [
                   {"step": 1, "role": "The lead", "name": "lab_analyst", "detail": "reads your question, picks tools"},
                   {"step": 2, "role": "Specialists, working together", "name": "9 read-only tools", "detail": "SQL over the lab tables"},
                   {"step": 3, "role": "The reviewer", "name": "Evidence rules in the instruction",
                    "detail": "holdout delta is the only citable uplift; generated text is untrusted data"},
                   {"step": 4, "role": "Your sign-off", "name": "propose_human_review", "detail": "pending until you hold to confirm"}]}
    limits = [
        {"item": "Managed AlphaEvolve service", "ok": pf["ready"],
         "text": "ready" if pf["ready"] else ("not provisioned: " + ("alpha_evolve client not installed; " if not pf["client_installed"] else "")
                                              + (f"missing {', '.join({'project_id': 'GOOGLE_CLOUD_PROJECT', 'engine': 'GE_APP_ID'}.get(m, m) for m in pf['missing_env'])}"
                                                 if pf["missing_env"] else ""))},
        *[{"item": f"Budget today, {p}", "ok": u["programs"] < pol.max_programs_per_day and u["runs"] < pol.max_runs_per_day,
           "text": f"{u['programs']} of {pol.max_programs_per_day} programs, {u['runs']} of {pol.max_runs_per_day} runs used"}
          for p, u in usage.items()],
        {"item": "Promotion", "ok": False, "text": "no run can be promoted: every run's source is the local controller"},
    ]
    return {"teams": [loop, analyst], "limits": limits, "day": day, "source": ["runs/*.json", "runs/ledger.json"]}


@router.get("/dossier/{run_id}")
def dossier(run_id: str):
    rec = load_run(run_id, RUNS_DIR)
    if not rec:
        raise HTTPException(404, f"run {run_id} not found")
    rv = reviews_for(run_id, RUNS_DIR)
    gate = promotion_gate(rec, rv)
    brief = _run_brief(rec) if rec.get("status") == "finished" else {"run_id": run_id, "status": rec.get("status")}
    best = rec.get("best") or {}
    catches = []
    for p in rec.get("programs", [])[1:]:
        if not p.get("valid"):
            catches.append({"idx": p["idx"], "id": p["id"], "kind": p.get("kind"),
                            "invariants": [v.get("invariant") for v in p.get("violations") or []],
                            "insight": ((p.get("insights") or [{}])[0].get("text") or "")[:400]})
    return {"run": brief, "status": rec.get("status"), "provenance": HONESTY, "gate": gate,
            "promotion_control": "disabled: source is not alphaevolve" if rec.get("source") != SOURCE_ALPHAEVOLVE else "per checklist",
            "champion": {"id": best.get("id"), "model": best.get("model"), "train": best.get("train"),
                         "train_delta_vs_seed": best.get("train_delta_vs_seed"), "metrics": best.get("metrics"),
                         "lineage": [{"id": x["id"], "score": x["score"], "model": x["model"]} for x in best.get("lineage") or []]},
            "holdout": rec.get("holdout"), "uplift_note": rec.get("uplift_note"), "catches": catches,
            "evaluator_version": rec.get("evaluator_version"), "instances": rec.get("instances"),
            "budget": rec.get("budget"), "tokens": {k: v for k, v in (rec.get("tokens") or {}).items() if k != "by_model"},
            "reviews": rv, "source": [f"runs/{run_id}.json", "runs/reviews.jsonl"]}


@router.get("/value")
def value():
    recs = _finished()
    tp, jt = _by_problem(recs, "tariff_pricing", True), _by_problem(recs, "jepx_trading", True)

    def champ_metrics(r):
        ho = r.get("holdout") or {}
        row = next((x for x in ho.get("top_k", []) if x["id"] == ho.get("best_id")), None)
        return (row or {}).get("holdout_metrics") or {}

    def rng(vals):
        vals = [v for v in vals if v is not None]
        return {"low": min(vals), "high": max(vals)} if vals else {"low": None, "high": None}

    seed_ho = (jt[-1].get("holdout") or {}).get("seed_metrics", {}) if jt else {}
    t_seed = tp[-1]["seed"]["metrics"] if tp else {}
    metrics = [
        {"id": "cost_vs_benchmark", "label": "Trading cost vs buying actual load at the DA price", "unit": "JPY/kWh", "better": "lower",
         "site_seed": seed_ho.get("cost_vs_benchmark_jpy_kwh"), "site_range": rng([champ_metrics(r).get("cost_vs_benchmark_jpy_kwh") for r in jt]),
         "band": {"text": NO_BENCH, "source": ""}, "fold": "holdout"},
        {"id": "bess_cycles", "label": "Battery cycles per day", "unit": "cycles/day", "better": "within warranty",
         "site_seed": seed_ho.get("bess_cycles_per_day"), "site_range": rng([champ_metrics(r).get("bess_cycles_per_day") for r in jt]),
         "band": {"text": "about 1 cycle/day in utility-scale planning assumptions", "source": "MARKET_FACTS 12 (NREL ATB 2024)"}, "fold": "holdout"},
        {"id": "imbalance_share", "label": "Imbalance as a share of load", "unit": "%", "better": "inside the compliance band",
         "site_seed": (seed_ho.get("imbalance_abs_share") or 0) * 100 if seed_ho else None,
         "site_range": rng([(champ_metrics(r).get("imbalance_abs_share") * 100) if champ_metrics(r).get("imbalance_abs_share") is not None else None for r in jt]),
         "band": {"text": NO_BENCH, "source": ""}, "fold": "holdout"},
        {"id": "tariff_alpha", "label": "Energy-weighted market-link share of the renewal book", "unit": "share", "better": "context",
         "site_seed": t_seed.get("mean_alpha"), "site_range": rng([((r.get("best") or {}).get("metrics") or {}).get("mean_alpha") for r in tp]),
         "band": {"text": "TEPCO EP offers a 100% spot-linked plan alongside fixed plans", "source": "MARKET_FACTS 5.4"}, "fold": "train"},
        {"id": "tariff_cvar", "label": "Renewal book CVaR95 shortfall", "unit": "JPY M", "better": "lower",
         "site_seed": t_seed.get("cvar95_shortfall_jpy_m"), "site_range": rng([((r.get("best") or {}).get("metrics") or {}).get("cvar95_shortfall_jpy_m") for r in tp]),
         "band": {"text": NO_BENCH, "source": ""}, "fold": "train"},
        {"id": "tariff_churn", "label": "Renewal book expected churn (by count)", "unit": "%", "better": "at or below 15%",
         "site_seed": (t_seed.get("churn_count") or 0) * 100 if t_seed else None,
         "site_range": rng([(((r.get("best") or {}).get("metrics") or {}).get("churn_count") or 0) * 100 for r in tp]),
         "band": {"text": NO_BENCH, "source": ""}, "fold": "train"},
    ]
    return {"metrics": metrics, "provenance_label": HONESTY, "source": ["runs/*.json"]}


@router.get("/proof")
def proof():
    res = ROOT / "eval" / "results"

    def load(n):
        p = res / n
        return json.loads(p.read_text()) if p.exists() else None

    adk, gr, sf, mc = load("adk_summary.json"), load("grounding_results.json"), load("safety_results.json"), load("mutation_checks.json")
    pt = (res / "pytest_summary.txt").read_text().splitlines() if (res / "pytest_summary.txt").exists() else []
    ex = None
    if gr:
        p = next((x for x in gr["probes"] if x["id"] == "fy2025_tokyo_mean"), gr["probes"][0])
        a = p["first_attempt"]
        ex = {"question": a["question"], "truth": p["truth"], "tools": [c["name"] for c in a["tool_calls"]],
              "reply_excerpt": a["reply"][:600], "label": p["final"]}
    recs = _finished()
    return {"adk": {"passed": adk["passed_final"], "first_attempt": adk["passed_first_attempt"], "total": adk["total"],
                    "failures": [c["eval_id"] for c in adk["cases"] if c["final"] != "PASSED"]} if adk else None,
            "grounding": {"grounded": gr["grounded"], "total": gr["total"], "unverifiable": gr["unverifiable"]} if gr else None,
            "safety": {"passed": sf["passed"], "total": sf["total"], "probes": [p["id"] for p in sf["probes"]]} if sf else None,
            "mutation": {"detected": sum(1 for r in mc["results"] if r.get("suite_went_red")), "total": len(mc["results"])} if mc else None,
            "pytest": [l.strip() for l in pt if l.strip()], "worked_grounding_example": ex,
            "runs": [_run_brief(r) for r in recs], "policy_catches": _policy_catches(recs),
            "provenance_label": HONESTY, "source": ["eval/results/*.json", "runs/*.json"]}


@router.get("/solution")
def solution():
    recs = _finished()
    progs = sum((r.get("budget") or {}).get("programs_evaluated") or 0 for r in recs)
    kinds: dict = {}
    for r in recs:
        for k, v in (r.get("invalid_by_kind") or {}).items():
            kinds[k.split(":")[0]] = kinds.get(k.split(":")[0], 0) + v
    uplift = sum(1 for r in recs if r.get("uplift_valid"))
    reviews = sum(len(reviews_for(r["run_id"], RUNS_DIR)) for r in recs)
    stages = [
        {"id": "controller", "name": "Controller", "what": "picks a parent and inspirations, asks a model for a code edit",
         "count": progs, "count_label": "programs generated"},
        {"id": "sandbox", "name": "Sandbox", "what": "runs the edited policy in a fresh locked-down process; it only returns decisions",
         "count": kinds.get("sandbox", 0), "count_label": "crashes or denials caught"},
        {"id": "evaluator", "name": "Evaluator", "what": "trusted simulator settles the decisions and scores them",
         "count": progs - sum(kinds.get(k, 0) for k in ("diff", "sandbox", "static", "format")), "count_label": "programs scored"},
        {"id": "invariants", "name": "Invariants", "what": "churn, fairness, essential facilities, intentional imbalance, battery limits",
         "count": kinds.get("policy", 0), "count_label": "rule-breaking candidates rejected"},
        {"id": "holdout", "name": "Holdout", "what": "top 5 rescored on customers and days the search never saw",
         "count": uplift, "count_label": "runs with a validated holdout delta"},
        {"id": "human_review", "name": "Human review", "what": "a person reads the evolved block and holds to confirm",
         "count": reviews, "count_label": "reviews recorded"},
        {"id": "managed", "name": "Managed AlphaEvolve", "what": "the same contract on the Gemini Enterprise app",
         "count": sum(1 for r in recs if r.get("source") == SOURCE_ALPHAEVOLVE), "count_label": "managed runs"},
    ]
    arch = [
        {"layer": "Search", "demo": "local Gemini controller (gemini-3.6-flash 0.7 / gemini-3.1-pro-preview 0.3)",
         "production": "managed AlphaEvolve on a Gemini Enterprise app, same evaluator contract (one flag)"},
        {"layer": "Evaluator", "demo": "subprocess sandbox on the workstation", "production": "hardened container job, no egress"},
        {"layer": "Market data", "demo": "calibrated synthetic history and scenario banks", "production": "JEPX API via Apigee, OCCTO and TEPCO PG data in BigQuery"},
        {"layer": "Customer book", "demo": "fictional 1,200-customer cohorts with hidden behaviour", "production": "renewal history and fitted acceptance models"},
        {"layer": "Analyst", "demo": "ADK agent in-process or on Agent Runtime", "production": "Agent Runtime in asia-northeast1"},
        {"layer": "Promotion", "demo": "refused for every local run", "production": "holdout delta + human review + managed-run provenance + shadow period"},
    ]
    return {"stages": stages, "architecture": arch, "provenance_label": HONESTY, "source": ["runs/*.json"]}


@router.get("/pill")
def pill():
    recs = _finished()
    led, pol = Ledger(), BudgetPolicy.from_env()
    from datetime import datetime, timezone

    from energy_lab.harness.budget import JST

    day = datetime.now(timezone.utc).astimezone(JST).date().isoformat()
    used = sum(led.usage(p, day)["programs"] for p in ("tariff_pricing", "jepx_trading"))
    n_zero = sum(1 for r in recs if _infra_failure(r))
    runs = f"{len(recs) - n_zero} runs" + (f" + {n_zero} failed attempts" if n_zero else "")
    return {"text": f"{runs} · {used} of {2 * pol.max_programs_per_day} program budget today · {HONESTY}",
            "title": "Source: runs/*.json and runs/ledger.json (the ledger charges failed model calls too)"}
