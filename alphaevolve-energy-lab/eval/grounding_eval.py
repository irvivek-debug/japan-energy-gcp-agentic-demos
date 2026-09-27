"""Grounding eval: ground truth computed by SQL at test time (never stored), agent answers live, key figures compared.

Label per probe: GROUNDED (tool calls happened AND every key figure matches truth within tolerance), UNGROUNDED (no tool
call, or a figure is missing / wrong), UNVERIFIABLE (the truth query returned nothing; reported, never dropped).
A failing probe is retried once and classified transient / persistent; the first attempt is kept as evidence.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from _agent import ROOT, ask, has_number

from energy_lab.store import STORE


def q1(sql: str, **p):
    rows = STORE.query(sql, **p)
    return rows[0] if rows else None


def probes() -> list[dict]:
    out = []
    r = q1("SELECT AVG(tokyo_price_jpy_kwh) AS v FROM {t:market_history} WHERE fiscal_year = 2025")
    out.append({"id": "fy2025_tokyo_mean", "question": "What was the average Tokyo area spot price in FY2025?",
                "truth": [(round(r["v"], 2), 0.02)] if r and r["v"] is not None else None})
    r = q1("SELECT SUM(CASE WHEN imbalance_price_jpy_kwh >= 45 THEN 1 ELSE 0 END) AS v FROM {t:market_history} WHERE fiscal_year = 2024")
    out.append({"id": "fy2024_imb_ge45", "question": "In FY2024, how many half-hour slots had imbalance prices at or above 45 JPY/kWh?",
                "truth": [(float(r["v"]), 0.0)] if r else None})
    r = q1("SELECT ROUND(SUM(annual_mwh) / 1000000, 3) AS v, COUNT(*) AS n FROM {t:customers_train} WHERE segment = 'data_center'")
    out.append({"id": "dc_segment_twh", "question": "How many data center customers does KBG have and what is their annual energy in TWh?",
                "truth": [(float(r["n"]), 0.0), (float(r["v"]), 0.011)] if r else None})
    r = q1("SELECT value AS v FROM {t:cost_stack} WHERE component = 'wheeling_basic' AND voltage = 'HV' AND period = '2026-11..'")
    out.append({"id": "hv_wheeling_nov26", "question": "What is the high-voltage wheeling basic charge from November 2026?",
                "truth": [(float(r["v"]), 0.005)] if r else None})
    runs = STORE.query("SELECT run_id, problem, programs_evaluated, valid_count, invalid_count, seed_train, best_train, "
                       "holdout_delta FROM {t:lab_runs} ORDER BY started")
    tp = [x for x in runs if x["problem"] == "tariff_pricing"]
    jt = [x for x in runs if x["problem"] == "jepx_trading"]
    if tp:
        t = tp[0]
        out.append({"id": "tariff_first_seed_best", "question": f"What were the seed and best train scores of run {t['run_id']}?",
                    "truth": [(round(t["seed_train"], 1), 0.6), (round(t["best_train"], 1), 0.6)]})
        t = tp[-1]
        hd = t["holdout_delta"]
        out.append({"id": "tariff_latest_holdout_delta", "question": f"What is the holdout delta of run {t['run_id']}?",
                    "truth": [(round(hd, 1), 0.6)] if hd is not None else [], "expect_none": hd is None})
        # Did the latest tariff run keep every rule? Truth from the recomputed per-segment judgments: every segment the
        # champion passes only under the sampling margin must be named with its rise and margin limit, and the reply
        # must say the pass depends on the margin.
        relies = STORE.query("SELECT segment, n, rise, margin_rise_limit FROM {t:lab_segment_judgments} WHERE run_id = @r "
                             "AND fold_role = 'holdout' AND is_champion AND relies_on_margin ORDER BY segment", r=t["run_id"])
        if relies:
            out.append({"id": "tariff_latest_every_rule",
                        "question": (f"Did tariff run {sum(1 for x in tp if x['valid_count'])} ({t['run_id']}) keep every "
                                     "rule on its holdout customers?"),
                        "truth": [v for x in relies for v in ((round(x["rise"] * 100, 1), 0.1),
                                                              (round(x["margin_rise_limit"] * 100, 1), 0.1))],
                        "require_terms": ["margin"] + [x["segment"].split("_")[0] for x in relies]})
    else:
        out.append({"id": "tariff_first_seed_best", "question": "What were the seed and best train scores of the first tariff run?", "truth": None})
    if jt:
        j = jt[-1]
        out.append({"id": "trading_programs_invalid", "question": f"How many programs did run {j['run_id']} evaluate and how many were invalid?",
                    "truth": [(float(j["programs_evaluated"]), 0.0), (float(j["invalid_count"]), 0.0)]})
    return out


def label(p: dict, res: dict) -> tuple[str, list]:
    if p["truth"] is None:
        return "UNVERIFIABLE", []
    if not res["tool_calls"]:
        return "UNGROUNDED", ["no tool call"]
    if p.get("expect_none"):
        ok = any(w in res["reply"].lower() for w in ("no holdout", "not available", "none", "null", "no validated", "missing"))
        return ("GROUNDED" if ok else "UNGROUNDED"), [] if ok else ["did not state that no holdout delta exists"]
    miss = [f"{v} (tol {t})" for v, t in p["truth"] if not has_number(res["reply"], v, t)]
    miss += [f"term '{w}'" for w in p.get("require_terms", []) if w.lower() not in res["reply"].lower()]
    return ("GROUNDED" if not miss else "UNGROUNDED"), miss


async def main() -> None:
    results = []
    for p in probes():
        first = await ask(p["question"])
        lab, miss = label(p, first)
        rec = {"id": p["id"], "truth": p["truth"], "first_attempt": {**first, "label": lab, "missing": miss}}
        if lab == "UNGROUNDED":
            second = await ask(p["question"])
            lab2, miss2 = label(p, second)
            rec["retry"] = {**second, "label": lab2, "missing": miss2}
            rec["classification"] = "transient" if lab2 == "GROUNDED" else "persistent"
            rec["final"] = lab2
        else:
            rec["classification"] = "clean" if lab == "GROUNDED" else "n/a"
            rec["final"] = lab
        results.append(rec)
        print(f"{p['id']:30s} {rec['final']:12s} {rec['classification']:10s} tools={[c['name'] for c in first['tool_calls']]} "
              f"({first['latency_s']} s)", flush=True)
    out = {"total": len(results), "grounded": sum(r["final"] == "GROUNDED" for r in results),
           "ungrounded": sum(r["final"] == "UNGROUNDED" for r in results),
           "unverifiable": [r["id"] for r in results if r["final"] == "UNVERIFIABLE"], "probes": results}
    Path(ROOT / "eval" / "results").mkdir(parents=True, exist_ok=True)
    (ROOT / "eval" / "results" / "grounding_results.json").write_text(json.dumps(out, indent=1, default=str))
    print(f"GROUNDING: {out['grounded']}/{out['total']} GROUNDED; unverifiable: {out['unverifiable'] or 'none'}")


if __name__ == "__main__":
    asyncio.run(main())
