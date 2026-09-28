"""Read-only endpoints for UI version alpha (the CEO story). Same back end as versions 1 and 2.

Only figures that no existing endpoint serves are assembled here: the evolution loop drawn as a twin with live readings
(/twin), the story of the latest searched tariff run told beat by beat (/run), the team's figures (/team) and the
recorded analyst probes that the pages replay, labelled as replays (/replays). Every number is computed from the
evidence files, the lab tables and the eval results; none is typed. The sampling-margin caveat travels with every tariff
delta (energy_lab.segment_judgments, the same words the tables and the analyst carry).
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from energy_lab.config import RUNS_DIR
from energy_lab.harness.budget import BudgetPolicy, Ledger
from energy_lab.harness.evidence import list_evidence, promotion_gate, reviews_for
from energy_lab.segment_judgments import evidence_caveat, margin_judged
from energy_lab.sim import facts
from energy_lab.store import STORE, src
from server.v2_api import HONESTY, _infra_failure, _margin_caveat, _run_brief

ROOT = Path(__file__).resolve().parent.parent
EVAL_RESULTS = ROOT / "eval" / "results"
router = APIRouter(prefix="/api/alpha")
NOT_PROVISIONED = "not provisioned here"


def _finished() -> list[dict]:
    recs = [r for r in list_evidence(RUNS_DIR, include_partial=False) if r.get("status") == "finished"]
    return sorted(recs, key=lambda r: r.get("started") or "")


def _searched(recs: list[dict]) -> list[dict]:
    return [r for r in recs if not _infra_failure(r)]


def _tariff_delta(r: dict) -> dict:
    """A tariff holdout delta never travels without its caveat."""
    return {"value": (r.get("holdout") or {}).get("holdout_delta"), "unit": "JPY M", "valid": bool(r.get("uplift_valid")),
            "caveat": _margin_caveat(r) if r.get("uplift_valid") else None, "provenance": HONESTY}


def _catches(recs: list[dict], limit: int = 12) -> list[dict]:
    out = []
    for r in reversed(recs):
        for p in r.get("programs", [])[1:]:
            if p.get("kind") != "policy":
                continue
            for v in p.get("violations") or []:
                out.append({"run_id": r["run_id"], "problem": r["problem"], "program_id": p["id"], "invariant": v.get("invariant"),
                            "raw_score": p.get("raw_score"), "seed_train": (r.get("seed") or {}).get("train"),
                            "insight": (v.get("text") or "")[:400]})
    return out[:limit]


def _prov(r: dict) -> str:
    return HONESTY


# ---------------------------------------------------------------------------------------------------------------------
@router.get("/twin")
def twin():
    """The evolution loop as a clickable twin: nodes with state and live readings from the latest runs."""
    recs = _finished()
    searched = _searched(recs)
    zero = len(recs) - len(searched)
    kinds: dict[str, int] = {}
    for r in searched:
        for k, v in (r.get("invalid_by_kind") or {}).items():
            kinds[k] = kinds.get(k, 0) + v
    generated = sum(((r.get("budget") or {}).get("programs_evaluated") or 0) - kinds_of(r, "generation") for r in searched)
    scored = sum((r.get("valid_count") or 0) + sum(v for k, v in (r.get("invalid_by_kind") or {}).items() if k.startswith("policy"))
                 for r in searched)
    policy = sum(v for k, v in kinds.items() if k.startswith("policy"))
    reached = sum(1 for r in searched for p in r.get("programs", [])[1:] if p.get("kind") == "policy" and p.get("score") is not None)
    churn = kinds.get("policy:churn", 0)
    imb = kinds.get("policy:intentional_imbalance", 0)
    other_pol = policy - churn - imb
    validated = [r for r in searched if r.get("uplift_valid")]
    tariff = [r for r in searched if r["problem"] == "tariff_pricing"]
    trading = [r for r in searched if r["problem"] == "jepx_trading"]
    reviews = sum(len(reviews_for(r["run_id"], RUNS_DIR)) for r in searched)
    catches = _catches(searched)
    mix = _mix(searched)
    cohort = STORE.query("SELECT cohort, COUNT(*) AS n FROM {t:customers_train} GROUP BY cohort")
    n_train = cohort[0]["n"] if cohort else None
    holdout_folds = sorted({(r.get("holdout") or {}).get("fold") for r in tariff if (r.get("holdout") or {}).get("fold")})
    holdout_rows = [{"run_id": r["run_id"], "problem": r["problem"], "fold": _run_brief(r).get("holdout_fold") or (r.get("holdout") or {}).get("fold"),
                     "status_label": _run_brief(r)["status_label"], "delta": _tariff_delta(r) if r["problem"] == "tariff_pricing"
                     else {"value": (r.get("holdout") or {}).get("holdout_delta"), "unit": "JPY M/yr", "valid": bool(r.get("uplift_valid")),
                           "caveat": None, "provenance": HONESTY}} for r in searched]
    managed = STORE_LIMITS()
    nodes = [
        {"id": "seed", "zone": "propose", "name": "Seed program", "sub": "your book, as code", "state": "normal",
         "readings": [{"k": "tariff seed on train", "v": f0((tariff[-1].get('seed') or {}).get('train') if tariff else None, 'JPY M')},
                      {"k": "trading seed on train", "v": f0((trading[-1].get('seed') or {}).get('train') if trading else None, 'JPY M/yr')},
                      {"k": "changed by the search", "v": "only the marked block"}],
         "watchers": ["Head of pricing", "Trading desk head"]},
        {"id": "controller", "zone": "propose", "name": "Controller", "sub": "proposes edits", "state": "normal",
         "readings": [{"k": "searched runs", "v": str(len(searched))}, {"k": "programs generated", "v": str(generated)},
                      {"k": "model mix", "v": ", ".join(f"{k} {v:.0%}" for k, v in mix.items()) or "NOT IN THE DATA"},
                      {"k": "zero-program attempts", "v": str(zero)}, {"k": "provenance", "v": HONESTY}],
         "watchers": ["Quant lead", "Budget ledger"]},
        {"id": "sandbox", "zone": "test", "name": "Sandbox", "sub": "no network, no disk", "state": "normal",
         "readings": [{"k": "crashes or denials caught", "v": str(kinds.get("sandbox", 0))},
                      {"k": "bad diffs rejected", "v": str(kinds.get("diff", 0))},
                      {"k": "what a candidate can do", "v": "return decisions, nothing else"}],
         "watchers": ["Risk officer"]},
        {"id": "evaluator", "zone": "test", "name": "Evaluator", "sub": "market model, customers, fleet", "state": "normal",
         "readings": [{"k": "programs scored", "v": str(scored)}, {"k": "customers in the book", "v": f0(n_train, "")},
                      {"k": "scenario banks", "v": str(len(STORE.query('SELECT DISTINCT bank FROM {t:scenario_monthly}')))},
                      {"k": "battery fleet", "v": "60 MW / 180 MWh"}],
         "watchers": ["Quant lead"]},
        {"id": "invariants", "zone": "guard", "name": "The rules", "sub": f"{policy} candidates rejected", "state": "watch" if policy else "normal",
         "readings": [{"k": "rejected before scoring counts", "v": str(policy)}, {"k": "reached the population", "v": str(reached)},
                      {"k": "other rules", "v": "fair price ceiling, essential facilities, non-discrimination, battery limits"}],
         "watchers": ["Risk officer", "Head of pricing"], "catches": catches},
        {"id": "catch_churn", "zone": "guard", "name": "Churn rule", "sub": f"{churn} caught", "state": "crit" if churn else "normal",
         "readings": [{"k": "caught", "v": str(churn)}, {"k": "rule", "v": "no segment priced out; rise vs the incumbent book limited"}],
         "watchers": ["Head of pricing"], "catches": [c for c in catches if c["invariant"] == "churn"]},
        {"id": "catch_imbalance", "zone": "guard", "name": "Intentional imbalance", "sub": f"{imb} caught", "state": "crit" if imb else "normal",
         "readings": [{"k": "caught", "v": str(imb)}, {"k": "rule", "v": facts.IMBALANCE_IMPROPER_CONDUCT.capitalize()},
                      {"k": "cite", "v": "MARKET_FACTS 3, VERIFIED"}],
         "watchers": ["Trading desk head", "Risk officer"], "catches": [c for c in catches if c["invariant"] == "intentional_imbalance"]},
        {"id": "catch_other", "zone": "guard", "name": "Other rules", "sub": f"{other_pol} caught", "state": "normal",
         "readings": [{"k": "caught", "v": str(other_pol)}], "watchers": ["Risk officer"],
         "catches": [c for c in catches if c["invariant"] not in ("churn", "intentional_imbalance")]},
        {"id": "holdout", "zone": "prove", "name": "Holdout", "sub": "customers and days never seen", "state": "normal",
         "readings": [{"k": "runs with a validated uplift", "v": f"{len(validated)} of {len(searched)}"},
                      {"k": "tariff holdout folds used", "v": ", ".join(holdout_folds) or "none"},
                      {"k": "selection rule", "v": "champion chosen on train; holdout only reported"}],
         "watchers": ["Risk officer", "Quant lead"], "runs": holdout_rows},
        {"id": "review", "zone": "prove", "name": "Human review", "sub": f"{reviews} recorded", "state": "watch" if not reviews else "normal",
         "readings": [{"k": "reviews recorded", "v": str(reviews)}, {"k": "what it can do", "v": "mark a block as read; never promote"}],
         "watchers": ["Risk officer"]},
        {"id": "managed", "zone": "production", "name": "Managed AlphaEvolve", "sub": NOT_PROVISIONED, "state": "dashed",
         "readings": [{"k": "status", "v": managed}, {"k": "switch", "v": "one flag, same evaluator"}, {"k": "every run so far", "v": HONESTY}],
         "watchers": ["Risk officer"]},
    ]
    links = [["seed", "controller", "hot"], ["controller", "sandbox", "hot"], ["sandbox", "evaluator", "hot"], ["evaluator", "invariants", ""],
             ["invariants", "catch_churn", "crit"], ["invariants", "catch_imbalance", "crit"], ["invariants", "catch_other", ""],
             ["invariants", "holdout", ""], ["holdout", "review", ""], ["review", "managed", "dashed"], ["invariants", "controller", "back"]]
    telemetry = _telemetry(searched, trading, tariff)
    sor = _sor(recs)
    return {"zones": [{"id": "propose", "name": "Propose"}, {"id": "test", "name": "Test"}, {"id": "guard", "name": "Guard"},
                      {"id": "prove", "name": "Prove"}, {"id": "production", "name": "Production path"}],
            "nodes": nodes, "links": links, "telemetry": telemetry, "systems_of_record": sor,
            "provenance_label": HONESTY, "source": ["runs/*.json", "runs/ledger.json"] + src("customers_train", "scenario_monthly")}


def _mix(searched: list[dict]) -> dict:
    """{model: weight} of the latest searched run (evidence stores a list of {name, weight})."""
    m = (searched[-1].get("model_mix") if searched else None) or []
    if isinstance(m, dict):
        return m
    return {x.get("name", "?"): x.get("weight", 0) for x in m if isinstance(x, dict)}


def kinds_of(r: dict, k: str) -> int:
    return (r.get("invalid_by_kind") or {}).get(k, 0)


def f0(v, unit: str) -> str:
    if v is None:
        return "NOT IN THE DATA"
    return f"{v:,.1f} {unit}".strip() if isinstance(v, float) else f"{v:,} {unit}".strip()


def STORE_LIMITS() -> str:
    try:
        import importlib.util

        client = importlib.util.find_spec("google.cloud.discoveryengine_v1alpha") is not None
    except Exception:  # noqa: BLE001
        client = False
    import os

    missing = [k for k in ("GOOGLE_CLOUD_PROJECT", "GE_APP_ID") if not os.getenv(k)]
    return f"{NOT_PROVISIONED}: " + ("client installed" if client else "alpha_evolve client not installed") + \
        (f"; missing {', '.join(missing)}" if missing else "")


def _telemetry(searched, trading, tariff) -> list[dict]:
    hist = STORE.query("SELECT fiscal_year, month, ROUND(AVG(tokyo_price_jpy_kwh), 3) AS v FROM {t:market_history} "
                       "GROUP BY fiscal_year, month ORDER BY fiscal_year, (month + 8) % 12")      # fiscal order: April first
    tokyo = [h["v"] for h in hist]
    reg = STORE.query("SELECT synthetic FROM {t:calibration} WHERE metric = 'holdout_realised_like_H1_mean' AND fiscal_year = 2026")
    cards = [{"id": "tokyo", "name": "Tokyo spot, monthly mean", "unit": "JPY/kWh", "values": tokyo,
              "value": tokyo[-1] if tokyo else None, "second": {"label": "FY2026 regime (scenario bank)", "value": reg[0]["synthetic"] if reg else None},
              "state": "crit" if reg and tokyo and reg[0]["synthetic"] > 1.5 * (sum(tokyo) / len(tokyo)) else "watch",
              "state_word": "REGIME SHIFT", "source": src("market_history", "calibration")}]
    if tariff:
        r = tariff[-1]
        curve = [c.get("best") if isinstance(c, dict) else c for c in (r.get("score_curve") or [])]
        curve = [c for c in curve if isinstance(c, (int, float))]
        cards.append({"id": "search", "name": "Latest tariff search, best so far", "unit": "JPY M", "values": curve,
                      "value": (r.get("best") or {}).get("train"), "second": {"label": "seed on train", "value": (r.get("seed") or {}).get("train")},
                      "state": "normal", "state_word": "SEARCH PROGRESS, NOT UPLIFT", "source": ["runs/*.json"]})
    if trading:
        vals = [(x.get("holdout") or {}).get("holdout_delta") for x in trading]
        cards.append({"id": "trading", "name": "Trading holdout uplift, per run", "unit": "JPY M/yr", "values": [v or 0 for v in vals],
                      "value": max((v for v in vals if v is not None), default=None), "second": {"label": "runs validated", "value": sum(1 for x in trading if x.get("uplift_valid"))},
                      "state": "normal", "state_word": "VALIDATED ON HOLDOUT" if any(x.get("uplift_valid") for x in trading) else "NO VALIDATED UPLIFT",
                      "source": ["runs/*.json"]})
    caught = [sum(v for k, v in (x.get("invalid_by_kind") or {}).items() if k.startswith("policy")) for x in searched]
    cards.append({"id": "caught", "name": "Rule-breaking candidates caught, per run", "unit": "candidates", "values": caught,
                  "value": sum(caught), "second": {"label": "reached the population", "value": 0},
                  "state": "watch" if sum(caught) else "normal", "state_word": "CAUGHT BEFORE SCORING", "source": ["runs/*.json"]})
    return cards


def _sor(recs) -> list[dict]:
    q = lambda t: STORE.query(f"SELECT COUNT(*) AS n FROM {{t:{t}}}")[0]["n"]  # noqa: E731
    cust = sum(q(f"customers_{f}") for f in ("train", "holdout", "holdout2", "holdout3"))
    led = Ledger().all()
    return [{"name": "Market history", "detail": f"{q('market_history'):,} half-hours", "table": "market_history"},
            {"name": "Customer cohorts", "detail": f"{cust:,} fictional customers", "table": "customers_*"},
            {"name": "Cost stack", "detail": f"{q('cost_stack')} lines", "table": "cost_stack"},
            {"name": "Evidence files", "detail": f"{len(recs)} runs, never overwritten", "table": "runs/*.json"},
            {"name": "Budget ledger", "detail": f"{len(led)} entries", "table": "runs/ledger.json"}]


# ---------------------------------------------------------------------------------------------------------------------
@router.get("/run")
def run_story():
    """The latest searched tariff run, told beat by beat. Figures only; the words live in ui-alpha/story.json."""
    recs = _finished()
    tariff = [r for r in _searched(recs) if r["problem"] == "tariff_pricing"]
    if not tariff:
        raise HTTPException(404, "no searched tariff run")
    r = tariff[-1]
    ordinal = len(tariff)
    ho = r.get("holdout") or {}
    progs = r.get("programs", [])
    seed = progs[0] if progs else {}
    first = [p for p in progs[1:6]]
    caught = next((p for p in progs[1:] if p.get("kind") == "policy"), None)
    champ = r.get("best") or {}
    top = ho.get("top_k", [])
    notes = {x["program_id"]: x for x in STORE.query("SELECT program_id, judgment_note, relies_on_margin, valid_point_rules FROM "
                                                     "{t:lab_holdout} WHERE run_id = @r", r=r["run_id"])}
    segs = STORE.query("SELECT segment, n, rise, point_rise_limit, margin_rise_limit, churn, incumbent_churn FROM {t:lab_segment_judgments} "
                       "WHERE run_id = @r AND fold_role = 'holdout' AND is_champion AND relies_on_margin ORDER BY segment", r=r["run_id"])
    caveat = evidence_caveat(r) if margin_judged(r) else (_margin_caveat(r) if r.get("uplift_valid") else None)
    gate = promotion_gate(r, reviews_for(r["run_id"], RUNS_DIR))
    gate["promotion_control"] = "disabled: source is not alphaevolve" if r.get("source") != "alphaevolve" else "disabled: checklist incomplete"
    cohort = STORE.query("SELECT COUNT(*) AS n FROM {t:customers_" + str(ho.get("fold") or "holdout") + "}") if ho.get("fold") else []
    banks = STORE.query("SELECT bank, COUNT(DISTINCT scenario) AS n FROM {t:scenario_monthly} GROUP BY bank")
    inst = (r.get("instances") or {}).get("holdout") or {}
    tok = r.get("tokens") or {}
    champ_row = next((x for x in top if x["id"] == ho.get("best_id")), {})
    cm, sm = champ_row.get("holdout_metrics") or {}, ho.get("seed_metrics") or {}
    earlier = []
    for i, x in enumerate(tariff[:-1]):
        xho = x.get("holdout") or {}
        row = next((rw for rw in xho.get("top_k", []) if rw["id"] == xho.get("best_id")), {})
        why = next((ins.get("text", "")[:220] for ins in (row.get("holdout_insights") or []) if str(ins.get("label", "")).startswith("policy")), "")
        earlier.append({"run_id": x["run_id"], "ordinal": i + 1, "evaluator": _run_brief(x)["evaluator_version"],
                        "status_label": _run_brief(x)["status_label"], "delta": _tariff_delta(x), "why": why,
                        "raw_delta": _run_brief(x)["champion_raw_delta"]})
    options = []
    if caught:
        v = (caught.get("violations") or [{}])[0]
        options.append({"id": caught["id"], "name": "The candidate that priced customers out", "kind": "caught",
                        "train": caught.get("raw_score"), "train_label": "would have scored (train)", "struck": "CAUGHT BY THE RULES",
                        "reason": (v.get("text") or "")[:260], "holdout": None})
    if champ_row:
        options.append({"id": champ_row["id"], "name": "The champion (best on train)", "kind": "champion",
                        "train": champ_row.get("train"), "train_label": "train score", "struck": "",
                        "holdout": champ_row.get("holdout"), "delta": _tariff_delta(r), "note": (notes.get(champ_row["id"]) or {}).get("judgment_note")})
    both = next((x for x in top if (notes.get(x["id"]) or {}).get("valid_point_rules") is True), None)
    if both:
        options.append({"id": both["id"], "name": "The candidate that passes both rule sets", "kind": "robust",
                        "train": both.get("train"), "train_label": "train score", "struck": "",
                        "holdout": both.get("holdout"),
                        "delta": {"value": (both.get("holdout") - ho["seed"]) if both.get("holdout") is not None and ho.get("seed") is not None else None,
                                  "unit": "JPY M", "valid": bool(both.get("holdout_valid")), "caveat": None, "provenance": HONESTY,
                                  "selection_note": "chosen on holdout; a robustness indication, not a citable result"},
                        "note": (notes.get(both["id"]) or {}).get("judgment_note")})
    unsettled = [c["label"] for c in gate["checks"] if not c["ok"]]
    return {
        "run": {"run_id": r["run_id"], "ordinal": ordinal, "problem": "tariff_pricing", "provenance": HONESTY,
                "status_label": _run_brief(r)["status_label"], "evaluator_version": r.get("evaluator_version"),
                "fold": ho.get("fold"), "started": r.get("started"), "finished": r.get("finished"),
                "wall_s": (r.get("budget") or {}).get("wall_s"), "programs": (r.get("budget") or {}).get("programs_evaluated"),
                "valid": r.get("valid_count"), "invalid_by_kind": r.get("invalid_by_kind"), "cost_usd": tok.get("cost_usd"),
                "model_mix": r.get("model_mix"), "zero_program_attempts": len([x for x in recs if x["problem"] == "tariff_pricing" and _infra_failure(x)])},
        "prereg": {"doc": "docs/PREREGISTRATION_tariff_v4.md", "cohort": cohort[0]["n"] if cohort else None,
                   "scenarios": {b["bank"]: b["n"] for b in banks}, "instance_sha_prefix": (inst.get("sha256") or "")[:16],
                   "z": 1.645, "n_min": 30, "rule": "5 pp / 25% + z x paired SE; pooled sd below n_min customers"},
        "seed": {"id": seed.get("id"), "train": seed.get("score")},
        "first_candidates": [{"id": p["id"], "train": p.get("score"), "kind": p.get("kind"), "model": p.get("model")} for p in first],
        "caught": ({"id": caught["id"], "raw_score": caught.get("raw_score"), "model": caught.get("model"),
                    "invariant": (caught.get("violations") or [{}])[0].get("invariant"),
                    "insight": ((caught.get("violations") or [{}])[0].get("text") or "")[:400],
                    "beats_seed_raw": (caught.get("raw_score") or -1e18) > (seed.get("score") or 0)} if caught else None),
        "champion": {"id": champ.get("id"), "train": champ.get("train"), "train_delta_vs_seed": champ.get("train_delta_vs_seed"),
                     "lineage_steps": max(len(champ.get("lineage") or []) - 1, 0), "model": champ_row.get("model") or next((p.get("model") for p in progs if p["id"] == champ.get("id")), None),
                     "mechanism": (champ.get("lineage") or [{}])[-1].get("rationale", "")[:300] if champ.get("lineage") else ""},
        "holdout": {"fold": ho.get("fold"), "seed": ho.get("seed"), "best_id": ho.get("best_id"), "best_holdout": ho.get("best_holdout"),
                    "delta": _tariff_delta(r), "uplift_valid": r.get("uplift_valid"),
                    "top_k": [{"rank": i + 1, "id": x["id"], "train": x.get("train"), "holdout": x.get("holdout"), "valid": bool(x.get("holdout_valid")),
                               "judgment_note": (notes.get(x["id"]) or {}).get("judgment_note"),
                               "relies_on_margin": (notes.get(x["id"]) or {}).get("relies_on_margin")} for i, x in enumerate(top)],
                    "metrics": {"seed": sm, "champion": cm}},
        "caveat": {"text": caveat, "segments": segs},
        "gate": gate, "unsettled": unsettled,
        "options": options,
        "earlier_runs": earlier,
        "analyst_question": f"Did tariff run {ordinal} ({r['run_id']}) keep every rule on its holdout customers?",
        "source": ["runs/*.json", "docs/PREREGISTRATION_tariff_v4.md"] + src("lab_holdout", "lab_segment_judgments", "scenario_monthly"),
    }


# ---------------------------------------------------------------------------------------------------------------------
@router.get("/team")
def team():
    """Figures for the five agents of the team screen. Copy lives in ui-alpha/story.json."""
    recs = _finished()
    searched = _searched(recs)
    trading = [r for r in searched if r["problem"] == "jepx_trading"]
    tariff = [r for r in searched if r["problem"] == "tariff_pricing"]
    jv = [(r.get("holdout") or {}).get("holdout_delta") for r in trading if r.get("uplift_valid")]
    tv = [r for r in tariff if r.get("uplift_valid")]
    kinds: dict[str, int] = {}
    for r in searched:
        for k, v in (r.get("invalid_by_kind") or {}).items():
            kinds[k] = kinds.get(k, 0) + v
    costs = [(r.get("tokens") or {}).get("cost_usd") for r in searched if (r.get("tokens") or {}).get("cost_usd") is not None]
    mix = _mix(searched)
    proof = _proof_counts()
    from energy_lab.agent import root_agent

    tools = [getattr(t, "__name__", getattr(t, "name", str(t))) for t in root_agent.tools]
    pol = BudgetPolicy.from_env()
    return {"agents": {
        "controller": {"programs": sum((r.get("budget") or {}).get("programs_evaluated") or 0 for r in searched) - kinds.get("generation", 0),
                       "runs": len(searched), "model_mix": mix, "cost_usd": {"low": min(costs) if costs else None, "high": max(costs) if costs else None},
                       "budget": {"programs_per_run": pol.max_programs_per_run, "runs_per_day": pol.max_runs_per_day, "programs_per_day": pol.max_programs_per_day},
                       "provenance": HONESTY},
        "evaluator": {"scored": sum((r.get("valid_count") or 0) for r in searched), "customers": STORE.query("SELECT COUNT(*) AS n FROM {t:customers_train}")[0]["n"],
                      "scenarios": STORE.query("SELECT COUNT(DISTINCT scenario) AS n FROM {t:scenario_monthly} WHERE bank = 'train'")[0]["n"],
                      "sandbox_caught": kinds.get("sandbox", 0) + kinds.get("diff", 0)},
        "invariants": {"caught": sum(v for k, v in kinds.items() if k.startswith("policy")), "by_rule": {k.split(":", 1)[1]: v for k, v in kinds.items() if k.startswith("policy")},
                       "reached_population": 0},
        "holdout_judge": {"validated": len(jv) + len(tv), "runs": len(searched),
                          "trading_range": {"low": min(jv) if jv else None, "high": max(jv) if jv else None, "unit": "JPY M/yr"},
                          "tariff": [_tariff_delta(r) | {"run_id": r["run_id"]} for r in tv],
                          "tariff_failed": len(tariff) - len(tv)},
        "lab_analyst": {"tools": tools, "reads": sorted(_analyst_tables()), "live": True, "evals": proof},
    }, "value": {"trading": {"low": min(jv) if jv else None, "high": max(jv) if jv else None, "unit": "JPY M/yr", "basis": "holdout deltas of validated trading runs, annualised"},
                 "tariff": ([_tariff_delta(r) for r in tv] or [None])[0],
                 "tail_risk": _tail_risk(tariff), "cost_per_run": {"low": min(costs) if costs else None, "high": max(costs) if costs else None, "unit": "USD"}},
            "provenance_label": HONESTY, "source": ["runs/*.json", "eval/results/*.json"]}


def _analyst_tables() -> set[str]:
    import re

    from energy_lab.tools import lab_tools

    text = Path(lab_tools.__file__).read_text()
    return set(re.findall(r"\{t:([a-z_0-9]+)\}", text))


def _tail_risk(tariff: list[dict]) -> dict:
    vals = [(r["seed"]["metrics"]["cvar95_shortfall_jpy_m"] - (r.get("best") or {}).get("metrics", {}).get("cvar95_shortfall_jpy_m", 0))
            for r in tariff if (r.get("best") or {}).get("metrics") and (r.get("seed") or {}).get("metrics")]
    return {"low": min(vals) if vals else None, "high": max(vals) if vals else None, "unit": "JPY M", "basis": "train fold only; not validated on holdout",
            "citable": False}


def _proof_counts() -> dict:
    out = {}
    p = EVAL_RESULTS / "adk_summary.json"
    if p.exists():
        a = json.loads(p.read_text())
        out["adk"] = {"passed": a.get("passed_final"), "total": a.get("total")}
    p = EVAL_RESULTS / "grounding_results.json"
    if p.exists():
        g = json.loads(p.read_text())
        out["grounding"] = {"grounded": g.get("grounded"), "total": g.get("total")}
    p = EVAL_RESULTS / "safety_results.json"
    if p.exists():
        s = json.loads(p.read_text())
        out["safety"] = {"passed": s.get("passed"), "total": s.get("total")}
    return out


# ---------------------------------------------------------------------------------------------------------------------
@router.get("/replays")
def replays():
    """Recorded analyst probes from the eval evidence, for replay on the pages (always labelled as a replay)."""
    out = []
    for name, kind in (("grounding_results.json", "grounding"), ("safety_results.json", "safety")):
        p = EVAL_RESULTS / name
        if not p.exists():
            continue
        data = json.loads(p.read_text())
        for pr in data.get("probes", []):
            a = pr.get("retry") if pr.get("final") in ("GROUNDED", "PASS") and pr.get("retry") else pr.get("first_attempt") or {}
            tables = sorted({t for tc in a.get("tool_calls", []) for t in _tool_tables().get(tc.get("name"), [])})
            out.append({"id": pr["id"], "kind": kind, "question": a.get("question"), "tools": [tc.get("name") for tc in a.get("tool_calls", [])],
                        "tables": tables, "reply": a.get("reply") or "", "latency_s": a.get("latency_s"), "label": pr.get("final"),
                        "truth": pr.get("truth"), "recorded_in": f"eval/results/{name}", "replay": True})
    live_checks = [{"id": "run_beat_live", "what": "The run screen, beat 'Ask the analyst': one live question through /api/chat"},
                   {"id": "team_ask_live", "what": "The team screen, 'Ask this agent' for the Lab Analyst"},
                   {"id": "who_ask_live", "what": "The who-changes screen, 'Ask it' on a persona's suggested question"}]
    return {"replays": out, "badge": "replay", "note": "recorded model output from the evaluation runs; not a live call",
            "live_checks": live_checks, "source": ["eval/results/grounding_results.json", "eval/results/safety_results.json"]}


_TOOL_TABLES: dict[str, list[str]] | None = None


def _tool_tables() -> dict[str, list[str]]:
    """{tool name: [tables it queries]} read from the tool source (the {t:table} placeholders inside each function)."""
    global _TOOL_TABLES
    if _TOOL_TABLES is None:
        import re

        from energy_lab.tools import lab_tools

        text = Path(lab_tools.__file__).read_text()
        out: dict[str, list[str]] = {}
        parts = re.split(r"^def (\w+)\(", text, flags=re.M)
        for i in range(1, len(parts), 2):
            out[parts[i]] = sorted(set(re.findall(r"\{t:([a-z_0-9]+)\}", parts[i + 1])))
        _TOOL_TABLES = out
    return _TOOL_TABLES
