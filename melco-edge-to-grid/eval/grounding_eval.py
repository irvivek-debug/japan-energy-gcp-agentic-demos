"""Grounding eval: for each PRD scenario, compute the ground truth at test time (SQL over the same dataset,
or the deterministic edge/BESS engine for plan figures, labelled as such; never stored), run the live agent,
and require (a) tool calls occurred and (b) the key figures in the reply match the truth within tolerance.

Labels: GROUNDED (tools called, every key figure matched), UNGROUNDED (a figure missing or wrong, or no tool
calls), UNVERIFIABLE (the truth could not be computed; reported, never dropped). A failing probe is retried once
and classified transient / persistent; the first attempt is kept as evidence.

Run from the demo root with the Vertex env vars:  python eval/grounding_eval.py
Writes eval/results/grounding_results.json
"""
from __future__ import annotations

import asyncio
import os
import sys
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval._runner import ROOT, dump, matches, numbers_in, run_prompt  # noqa: E402
from factory_copilot.core import bess as B  # noqa: E402
from factory_copilot.datastore import STORE  # noqa: E402
from factory_copilot.edge.interlock_engine import evaluate_plan  # noqa: E402
from factory_copilot.tools import common as C  # noqa: E402

D = "2026-08-19"


def q1(sql, **p):
    rows = STORE.query(sql, **p)
    return rows[0] if rows else None


# ---- truths (computed now, from the data) ----------------------------------------------------
def t_dr_plan():
    ev = q1("SELECT requested_kw, start_slot, end_slot FROM {t:dr_events} WHERE date = @d", d=D)
    soc = q1("SELECT soc_pct FROM {t:bess_state_5min} ORDER BY ts DESC LIMIT 1")["soc_pct"]
    plan, _, _ = C.draft_plan(D, "16:30", "19:00", "DR-20260819", ev["requested_kw"])
    firm = evaluate_plan(plan, C.edge_context(D))["summary"]["firm_reduction_kw"]
    return [("requested_kw [SQL dr_events]", ev["requested_kw"], 0.001, 0), ("edge firm kW [engine]", firm, 0.01, 0),
            ("BESS SOC now % [SQL bess_state_5min]", soc, 0.0, 0.2)]


def t_spike():
    r = q1("SELECT MAX(spot_jpy_kwh) AS mx, AVG(spot_jpy_kwh) AS av FROM {t:jepx_prices_30min} WHERE date = @d AND slot >= 35 AND slot <= 39", d=D)
    return [("spike peak spot JPY/kWh [SQL]", r["mx"], 0.0, 0.05), ("spike avg spot JPY/kWh [SQL]", r["av"], 0.0, 0.06)]


def t_anomalies():
    rows = STORE.query("SELECT compressor_id, SUM(energy_kwh) AS kwh, SUM(air_nm3) AS air FROM {t:compressor_perf} WHERE date >= @a AND date <= @b AND air_nm3 > 0 GROUP BY compressor_id",
                       a="2026-08-17", b=D)
    sp = {r["compressor_id"]: r["kwh"] / (r["air"] / 60.0) for r in rows}
    exc = 100 * (sp["AC-04"] / median(v for k, v in sp.items() if k != "AC-04") - 1)
    stuck = q1("SELECT COUNT(*) AS n FROM {t:telemetry_5min} WHERE meter_id = 'M-27' AND ts >= '2026-08-17T09:35' AND kw = "
               "(SELECT kw FROM {t:telemetry_5min} WHERE meter_id = 'M-27' AND ts = '2026-08-19T13:25')")
    m27 = "M-27" if stuck["n"] >= 24 else "NO-STUCK-METER"
    return [("AC-04 excess % vs peers [SQL compressor_perf]", exc, 0.0, 0.6), ("stuck meter id [SQL telemetry]", m27, 0, 0)]


def t_july():
    rows = STORE.query("SELECT amount_jpy, gain_share_eligible FROM {t:savings_ledger} WHERE month = '2026-07'")
    total = sum(r["amount_jpy"] for r in rows)
    elig = sum(r["amount_jpy"] for r in rows if r["gain_share_eligible"])
    t = {r["parameter"]: r["value"] for r in STORE.query("SELECT parameter, value FROM {t:tariff_contract}")}
    share = elig * t["gain_share_pct"] / 100
    return [("July total savings JPY [SQL]", total, 0.012, 0), ("vendor gain share JPY [SQL]", share, 0.012, 0),
            ("client net JPY [SQL]", total - share - t["baas_fee_jpy_month"], 0.02, 0)]


def t_bess_compare():
    di = C.day_inputs(D)
    soc = float(C.bess_now()["soc_pct"])
    out = []
    for pol in ("forecast_aware_v2",):
        r50 = B.simulate(pol, soc, di, "p50", C.bess_params(), C.policy_params(D))
        k = B.kpis(r50, B.simulate(pol, soc, di, "p10", C.bess_params(), C.policy_params(D)), di)
        out += [("v2 DR firm kW [engine]", k["dr_firm_kw"], 0.01, 0), ("v2 SOC at DR start % [engine]", k["soc_at_dr_start_pct"], 0.0, 0.3)]
    return out


def t_pv():
    r = q1("SELECT p10_kw, p50_kw, p90_kw FROM {t:pv_forecast_30min} WHERE date = @d AND issued_at = @i AND slot = 31", d=D, i=f"{D}T13:00")
    return [("PV p10 kW 15:00 [SQL]", r["p10_kw"], 0.0, 1.0), ("PV p50 kW 15:00 [SQL]", r["p50_kw"], 0.0, 1.0), ("PV p90 kW 15:00 [SQL]", r["p90_kw"], 0.0, 1.0)]


def t_0722():
    r = q1("SELECT delivered_kw, penalty_jpy, payment_jpy FROM {t:dr_events} WHERE event_id = 'DR-20260722'")
    return [("delivered kW [SQL]", r["delivered_kw"], 0.0, 1.0), ("penalty JPY [SQL]", r["penalty_jpy"], 0.0, 2), ("payment JPY [SQL]", r["payment_jpy"], 0.0, 2)]


def t_snapshot():
    r = q1("SELECT kw FROM {t:telemetry_5min} WHERE asset_class = 'receiving_point' ORDER BY ts DESC LIMIT 1")
    return [("import kW now [SQL]", r["kw"], 0.0, 1.0), ("headroom kW [SQL]", 16000 - r["kw"], 0.0, 1.0)]


def t_compressors():
    r = q1("SELECT limit_value FROM {t:interlock_rules} WHERE rule_id = 'IR-CA-01'")
    return [("header minimum MPa [SQL interlock_rules]", r["limit_value"], 0.0, 0.001), ("rule id cited [SQL interlock_rules]", "IR-CA-0", 0, 0)]


PROBES = [
    ("G01_S1_dr_plan", "The aggregator just called a DR event: we need 3,000 kW off from 16:30 to 19:00 today. Build the Event Response Plan.", t_dr_plan),
    ("G02_S2_spike", "JEPX Tokyo is forecast to spike this evening. What are the spike prices between 17:00 and 19:30 and how should we respond?", t_spike),
    ("G03_S3_compressors", "Turn off all the air compressors from 17:00 to 18:00 to help with the DR target.", t_compressors),
    ("G04_S4_anomalies", "Any energy anomalies this week? Put a cost on them.", t_anomalies),
    ("G05_S5_july", "Show me the July gain-share invoice and what the client nets.", t_july),
    ("G06_S6_bess", "Compare the two battery policies for today. Which one should we run and why?", t_bess_compare),
    ("G07_S7_pv", "How confident is the PV forecast this afternoon? Give p10, p50 and p90 for the cloud band.", t_pv),
    ("G08_0722", "What did the 22 July DR event earn after the penalty, and what was the gain share on it?", t_0722),
    ("G09_snapshot", "What is the plant pulling from the grid right now and how much headroom do we have to the contracted demand?", t_snapshot),
]


def judge(res: dict, truths) -> dict:
    found = numbers_in(res["reply"])
    checks = [{"figure": name, "truth": v if isinstance(v, str) else round(v, 3),
               "matched": (v in res["reply"]) if isinstance(v, str) else matches(v, found, rel, ab)} for (name, v, rel, ab) in truths]
    if not res["tool_calls"]:
        label = "UNGROUNDED"
    else:
        label = "GROUNDED" if all(c["matched"] for c in checks) else "UNGROUNDED"
    return {"label": label, "checks": checks}


async def main():
    out = {"probes": []}
    for pid, prompt, tf in PROBES:
        try:
            truths = tf()
        except Exception as e:
            out["probes"].append({"id": pid, "label": "UNVERIFIABLE", "reason": f"truth failed: {e}"})
            continue
        first = await run_prompt(prompt)
        j1 = judge(first, truths)
        rec = {"id": pid, "prompt": prompt, "first": {**j1, **{k: first[k] for k in ("latency_s", "tool_names", "tool_errors", "error", "reply")}}}
        if j1["label"] != "GROUNDED":
            second = await run_prompt(prompt)
            j2 = judge(second, truths)
            rec["retry"] = {**j2, **{k: second[k] for k in ("latency_s", "tool_names", "tool_errors", "error", "reply")}}
            rec["label"] = j2["label"]
            rec["classification"] = "transient" if j2["label"] == "GROUNDED" else "persistent"
        else:
            rec["label"], rec["classification"] = "GROUNDED", "pass"
        out["probes"].append(rec)
        print(f"{pid}: first={j1['label']} final={rec['label']} ({rec['classification']}) latency={first['latency_s']}s "
              f"checks={[(c['figure'], c['matched']) for c in j1['checks']]}", flush=True)
        dump(os.path.join(ROOT, "eval", "results", "grounding_results.json"), out)
    labels = [p["label"] for p in out["probes"]]
    out["summary"] = {"total": len(labels), "grounded": labels.count("GROUNDED"), "ungrounded": labels.count("UNGROUNDED"),
                      "unverifiable": labels.count("UNVERIFIABLE"),
                      "grounded_first_attempt": sum(1 for p in out["probes"] if p.get("first", {}).get("label") == "GROUNDED")}
    dump(os.path.join(ROOT, "eval", "results", "grounding_results.json"), out)
    print(out["summary"])


if __name__ == "__main__":
    asyncio.run(main())
