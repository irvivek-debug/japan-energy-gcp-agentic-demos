"""Read-only endpoints behind UI version alpha (the CEO story). Only figures that no existing endpoint serves:
the value timeline by month, the plant schematic twin, a recorded run per agent (from the evaluation evidence,
labelled replay) and a replay of the 13:00 call built from the deterministic tools (no model call, badged replay)."""
from __future__ import annotations

import asyncio
import functools
import json
import os
import time
from collections import defaultdict

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from factory_copilot.core.clock import DEMO_DATE, DEMO_NOW
from factory_copilot.datastore import STORE
from factory_copilot.tools import common as C
from factory_copilot.tools import factory as T_factory
from factory_copilot.tools import health as T_health
from factory_copilot.tools import market as T_market
from factory_copilot.tools import safety as T_safety

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "eval", "results")
router = APIRouter(prefix="/api/alpha")

MONTH_NAMES = {"01": "Jan", "02": "Feb", "03": "Mar", "04": "Apr", "05": "May", "06": "Jun", "07": "Jul", "08": "Aug", "09": "Sep", "10": "Oct", "11": "Nov", "12": "Dec"}


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------------------------------------
@router.get("/timeline")
@functools.lru_cache(maxsize=1)
def timeline():
    """Verified savings by month from the ledger, DR settlements by month, billing peaks where load history exists,
    and the month the DR season began (the regime change the story marks)."""
    t = C.tariff()
    led = STORE.query("SELECT month, category, amount_jpy FROM {t:savings_ledger} ORDER BY month")
    by_m: dict[str, dict[str, float]] = defaultdict(dict)
    for r in led:
        by_m[r["month"]][r["category"]] = float(r["amount_jpy"])
    dr: dict[str, dict[str, float]] = defaultdict(lambda: {"payment": 0.0, "penalty": 0.0, "events": 0})
    for e in C.dr_events(""):
        if e["status"] == "settled":
            m = e["date"][:7]
            dr[m]["payment"] += float(e["payment_jpy"])
            dr[m]["penalty"] += float(e["penalty_jpy"])
            dr[m]["events"] += 1
    peaks = {r["month"]: float(r["p"]) for r in STORE.query("SELECT month, MAX(import_kw) AS p FROM {t:site_load_30min} GROUP BY month")}
    months = sorted(set(by_m) | set(dr) | set(peaks))
    rows = []
    for m in months:
        cats = by_m.get(m, {})
        rows.append({
            "month": m, "label": MONTH_NAMES[m[5:7]],
            "verified_m_jpy": round(sum(cats.values()) / 1e6, 2) if cats else None,
            "demand_charge_avoided_m_jpy": round(cats["demand_charge_avoided"] / 1e6, 2) if "demand_charge_avoided" in cats else None,
            "dr_net_m_jpy": round((dr[m]["payment"] - dr[m]["penalty"]) / 1e6, 2) if m in dr else None,
            "dr_events": dr[m]["events"] if m in dr else 0,
            "billing_peak_kw": round(peaks[m], 1) if m in peaks else None,
            "demand_charge_m_jpy": round(peaks[m] * t["demand_charge_jpy_kw_month"] / 1e6, 2) if m in peaks else None,
        })
    first_dr = next((r for r in rows if r["dr_events"]), None)
    marker = None
    if first_dr:
        i = rows.index(first_dr)
        prev = rows[i - 1] if i else None
        marker = {"month": first_dr["month"], "label": first_dr["label"], "verified_m_jpy": first_dr["verified_m_jpy"],
                  "previous_verified_m_jpy": prev["verified_m_jpy"] if prev else None,
                  "text": "DR season began" + (f"; verified savings fell from {prev['verified_m_jpy']:.2f} to {first_dr['verified_m_jpy']:.2f} M JPY" if prev and prev["verified_m_jpy"] and first_dr["verified_m_jpy"] else "")}
    checks = []
    for m in [r["month"] for r in rows if r["billing_peak_kw"]]:
        to = DEMO_DATE if m == DEMO_DATE[:7] else f"{m}-31"
        c = C.billing_peak_check(m, to)
        if c:
            checks.append({"month": m, "label": MONTH_NAMES[m[5:7]], **{k: c[k] for k in c if k != "source"}})
    return {"rows": rows, "marker": marker, "billing_peaks": checks, "demand_charge_jpy_kw_month": t["demand_charge_jpy_kw_month"],
            "contracted_kw": t["contracted_demand_kw"], "source": C.src("savings_ledger", "dr_events", "site_load_30min", "tariff_contract")}


# ------------------------------------------------------------------------------------------------
WATCHERS = {
    "market": ["Market and weather"], "interlock": ["Plant and edge interlocks"], "bess": ["Battery"], "health": ["Asset health"],
}
CLASS_NODES = [
    # id, label, classes, zone, watchers
    ("cleanroom", "Clean-room air", ["cleanroom_hvac", "cleanroom_exhaust"], "protected", ["interlock"]),
    ("lines", "Production lines", ["production_line"], "protected", ["interlock", "health"]),
    ("utilities", "Critical utilities", ["critical_utility"], "protected", ["interlock"]),
    ("cooling", "Chillers and thermal store", ["chiller", "thermal_storage", "cooling_aux"], "flexible", ["interlock"]),
    ("compressors", "Compressed air", ["compressor"], "flexible", ["interlock", "health"]),
    ("furnaces", "Sintering furnaces", ["furnace"], "flexible", ["interlock"]),
    ("burnin", "Burn-in racks", ["burn_in"], "flexible", ["interlock"]),
    ("ev", "EV and forklift chargers", ["ev_charger"], "flexible", ["interlock"]),
    ("building", "Offices and lighting", ["office_hvac", "lighting", "building_general"], "flexible", ["interlock"]),
    ("wastewater", "Wastewater pumps", ["wastewater"], "flexible", ["interlock"]),
]


def _kw_now_by_class() -> dict[str, float]:
    ts = STORE.query("SELECT MAX(ts) AS ts FROM {t:telemetry_5min}")[0]["ts"]
    rows = STORE.query("SELECT asset_class, SUM(kw) AS kw FROM {t:telemetry_5min} WHERE ts = @ts GROUP BY asset_class", ts=ts)
    return {r["asset_class"]: float(r["kw"]) for r in rows}


@router.get("/schematic")
@functools.lru_cache(maxsize=1)
def schematic():
    """The plant as a single-line twin: grid and market, the switchboard with PV and battery, the protected classes and
    the flexible classes. Each node carries live readings, the edge rules that protect it, who watches it and today's
    plan verdicts."""
    assets = C.assets()
    rules = C.rules()
    tags = C.tags()
    t = C.tariff()
    kw_now = _kw_now_by_class()
    flex = T_factory.list_flexible_loads(DEMO_DATE, "16:30", "19:00")
    sim = T_factory.simulate_edge_interlock(flex["draft_plan_json"])
    verdict_by_asset = {a["asset_id"]: a for a in sim.get("actions", [])}
    for x in sim.get("rejected_actions", []):
        verdict_by_asset[x["asset_id"]] = {**x, "verdict": "REJECT"}
    anomalies = {a["asset_id"]: a for a in T_health.detect_energy_anomalies("2026-08-13", DEMO_DATE).get("anomalies", [])}
    ov_load = STORE.query("SELECT ts, kw FROM {t:telemetry_5min} WHERE asset_class = 'receiving_point' ORDER BY ts DESC LIMIT 1")[0]
    bess = C.bess_now()
    pv = T_market.get_pv_forecast(DEMO_DATE)
    risk = [s for s in pv.get("slots", []) if s.get("pv_risk_slot")]
    pv_now = STORE.query("SELECT pv_kw AS kw FROM {t:pv_actual_5min} ORDER BY ts DESC LIMIT 1")
    jepx = T_market.get_jepx_prices(DEMO_DATE)
    spike = (jepx.get("spike_windows") or [{}])[0]
    ev = next((e for e in C.dr_events(DEMO_DATE)), None)
    peak = C.month_peak_to_date(DEMO_DATE)

    def rule_rows(classes):
        out = []
        for r in rules.values():
            if r["asset_class"] in classes:
                out.append({"rule_id": r["rule_id"], "text": f"{r['parameter']} {r['operator']} {r['limit_value']:g} {r['unit']}", "why": r["rationale"], "severity": r["severity"]})
        return out

    def reading(asset_id, tag, label, unit=None):
        v = tags.get((asset_id, tag))
        return {"k": label, "v": v, "unit": unit or ""} if v is not None else None

    nodes = []
    # zone 1: grid and market
    nodes.append({"id": "aggregator", "zone": "market", "label": "Aggregator", "state": "watch" if ev else "normal",
                  "sub": f"{ev['event_id']}: {float(ev['requested_kw']):,.0f} kW, {ev['start_time']} to {ev['end_time']}" if ev else "no event today",
                  "readings": [{"k": "Asked for", "v": float(ev["requested_kw"]), "unit": "kW"}, {"k": "Window", "v": f"{ev['start_time']} to {ev['end_time']}", "unit": ""},
                               {"k": "Notified", "v": ev["notified_at"], "unit": ""}, {"k": "Baseline", "v": ev["baseline_method"], "unit": ""}] if ev else [],
                  "rules": [], "watchers": WATCHERS["market"], "plan": None, "note": "Day-of dispatch under the summer DR programme; settlement against the High 4 of 5 baseline."})
    nodes.append({"id": "jepx", "zone": "market", "label": "JEPX Tokyo spot", "state": "watch" if spike else "normal",
                  "sub": f"now {jepx.get('spot_now', 0):.2f} JPY/kWh, spike {spike.get('start', '')} to {spike.get('end', '')}" if spike else f"now {jepx.get('spot_now', 0):.2f} JPY/kWh",
                  "readings": [{"k": "Spot now", "v": jepx.get("spot_now"), "unit": "JPY/kWh"}, {"k": "Plant all-in now", "v": jepx.get("plant_price_now"), "unit": "JPY/kWh"},
                               {"k": "Spike peak", "v": spike.get("max_spot_jpy_kwh"), "unit": "JPY/kWh"}, {"k": "Imbalance estimate in the spike", "v": spike.get("max_imbalance_jpy_kwh"), "unit": "JPY/kWh"},
                               {"k": "Reserve margin, lowest", "v": spike.get("min_reserve_margin_pct"), "unit": "%"}],
                  "rules": [], "watchers": WATCHERS["market"], "plan": None, "note": "Synthetic prices inside the real FY2026 range; production reads the JEPX API."})
    nodes.append({"id": "grid", "zone": "market", "label": "66 kV receiving point", "state": "normal",
                  "sub": f"import {float(ov_load['kw']):,.0f} kW of {t['contracted_demand_kw']:,.0f} kW contracted",
                  "readings": [{"k": "Import now", "v": float(ov_load["kw"]), "unit": "kW"}, {"k": "Contracted demand", "v": t["contracted_demand_kw"], "unit": "kW"},
                               {"k": "Month billing peak", "v": peak.get("peak_kw"), "unit": "kW"}, {"k": "Demand charge", "v": t["demand_charge_jpy_kw_month"], "unit": "JPY/kW-month"},
                               {"k": "Deviation band", "v": t["deviation_band_pct"], "unit": "%"}],
                  "rules": rule_rows(["plant"]), "watchers": WATCHERS["market"] + WATCHERS["interlock"], "plan": None, "note": "Meter M-01 on the 66 kV incomer; the month's highest half hour sets the demand charge."})
    # zone 2: switchboard, PV, battery
    nodes.append({"id": "msb", "zone": "switchboard", "label": "Main switchboard", "state": "normal",
                  "sub": f"{float(ov_load['kw']) / t['contracted_demand_kw'] * 100:.1f} % of contract at {ov_load['ts'][11:]}",
                  "readings": [{"k": "Plant load now", "v": float(ov_load["kw"]), "unit": "kW"}, {"k": "Feeders metered", "v": STORE.query("SELECT COUNT(*) AS n FROM {t:meters}")[0]["n"], "unit": "ME96 meters"},
                               {"k": "Assets registered", "v": len(assets), "unit": ""}],
                  "rules": rule_rows(["plant", "any"]), "watchers": WATCHERS["interlock"], "plan": None, "note": "Every set-point change is sequenced here at no more than the plant ramp limit."})
    pv_kwp = sum(float(a["rated_kw"]) for a in assets.values() if a["asset_class"] == "pv")
    worst = min(risk, key=lambda s: s["p10_kw"]) if risk else None
    nodes.append({"id": "pv", "zone": "switchboard", "label": "Rooftop and carport PV", "state": "watch" if risk else "normal",
                  "sub": f"{pv_kwp / 1000:.0f} MWp; cloud band {risk[0]['time'][:5]} to {risk[-1]['time'][-5:]}" if risk else f"{pv_kwp / 1000:.0f} MWp",
                  "readings": [{"k": "Output now", "v": float(pv_now[0]["kw"]) if pv_now else None, "unit": "kW"}, {"k": "Capacity", "v": pv_kwp, "unit": "kWp"},
                               {"k": f"p10 at {worst['time'][:5]}" if worst else "p10", "v": worst["p10_kw"] if worst else None, "unit": "kW"},
                               {"k": f"p50 at {worst['time'][:5]}" if worst else "p50", "v": worst["p50_kw"] if worst else None, "unit": "kW"}],
                  "rules": [], "watchers": WATCHERS["market"] + WATCHERS["bess"], "plan": None, "note": pv.get("model", "")})
    bv = verdict_by_asset.get("BESS-01")
    nodes.append({"id": "bess", "zone": "switchboard", "label": "Battery 4 MW / 8 MWh", "state": "normal",
                  "sub": f"{float(bess['soc_pct']):.1f} % SOC, {bess['mode']} {abs(float(bess['power_kw'])):,.0f} kW",
                  "readings": [{"k": "State of charge", "v": float(bess["soc_pct"]), "unit": "%"}, {"k": "Power now", "v": float(bess["power_kw"]), "unit": "kW"},
                               {"k": "Policy today", "v": bess.get("policy"), "unit": ""}, reading("BESS-01", "cell_temp_c", "Cell temperature", "C")],
                  "rules": rule_rows(["bess"]), "watchers": WATCHERS["bess"], "plan": bv, "note": "BESS-as-a-Service; the edge checks the SOC path and every set-point step."})
    # zones 3 and 4: asset classes
    for nid, label, classes, zone, who in CLASS_NODES:
        members = [a for a in assets.values() if a["asset_class"] in classes]
        rated = sum(float(a["rated_kw"]) for a in members)
        now = sum(kw_now.get(c, 0.0) for c in classes)
        plan = [verdict_by_asset[a["asset_id"]] for a in members if a["asset_id"] in verdict_by_asset]
        state, sub, extra = "normal", f"{len(members)} assets, {rated:,.0f} kW rated", []
        if nid == "compressors" and "AC-04" in anomalies:
            an = anomalies["AC-04"]["evidence"]
            state, sub = "crit", f"AC-04 {an['recent_excess_vs_peers_pct']:.1f} % above its peers"
            extra = [{"k": "AC-04 specific power", "v": an["specific_power_kw_per_nm3min"], "unit": "kW/(Nm3/min)"}, {"k": "Peer median", "v": an["peer_median"], "unit": "kW/(Nm3/min)"},
                     {"k": "Excess cost, per year", "v": anomalies["AC-04"]["impact"]["annual_cost_jpy"], "unit": "JPY"}, reading("COMP-HDR", "header_pressure_mpa", "Header pressure", "MPa"),
                     reading("COMP-HDR", "air_demand_nm3min", "Air demand", "Nm3/min")]
        elif nid == "furnaces" and tags.get(("FN-02", "batch_committed")):
            s0, e0 = tags.get(("FN-02", "committed_batch_start_min"), 0), tags.get(("FN-02", "committed_batch_end_min"), 0)
            state, sub = "watch", f"FN-02 batch committed {int(s0 // 60):02d}:{int(s0 % 60):02d} to {int(e0 // 60):02d}:{int(e0 % 60):02d}"
            extra = [{"k": "FN-02 batch committed", "v": "yes, paste printed", "unit": ""}, {"k": "FN-02 batch window", "v": f"{int(s0 // 60):02d}:{int(s0 % 60):02d} to {int(e0 // 60):02d}:{int(e0 % 60):02d}", "unit": ""},
                     reading("FN-01", "reheat_lead_min", "FN-01 reheat lead", "min"), {"k": "FN-01 batch active", "v": "yes" if tags.get(("FN-01", "batch_active")) else "no", "unit": ""}]
        elif nid == "lines" and "M-27" in anomalies:
            an = anomalies["M-27"]["evidence"]
            state, sub = "watch", f"meter M-27 on {an['metered_assets']} frozen {an['duration_h']:.1f} h"
            extra = [{"k": "M-27 identical readings", "v": an["identical_readings"], "unit": ""}, {"k": "Frozen since", "v": an["since"], "unit": ""},
                     {"k": "Unallocated energy", "v": anomalies["M-27"]["impact"]["unallocated_kwh"], "unit": "kWh"}]
        elif nid == "cleanroom":
            extra = [reading("CR-AHU-01", "airflow_pct", "Production-zone airflow", "% of design")]
            sub = f"{len(members)} units, airflow held at {tags.get(('CR-AHU-01', 'airflow_pct'), 0):.0f} %"
        elif nid == "cooling":
            extra = [reading("TES-01", "tes_soc_pct", "Thermal store", "%"), reading("TES-01", "tes_capacity_kwh_th", "Store capacity", "kWh-th")]
        elif nid == "wastewater":
            extra = [{"k": "Hold allowed", "v": rules["IR-WW-01"]["limit_value"], "unit": "min"}]
        readings = [{"k": "Load now", "v": round(now, 1), "unit": "kW"}, {"k": "Rated", "v": rated, "unit": "kW"}, {"k": "Units", "v": len(members), "unit": ""}] + [x for x in extra if x]
        nodes.append({"id": nid, "zone": zone, "label": label, "state": state, "sub": sub, "readings": readings, "rules": rule_rows(classes),
                      "watchers": sum((WATCHERS[w] for w in who), []), "plan": plan or None, "classes": classes,
                      "plan_summary": {"accept": sum(p["verdict"] == "ACCEPT" for p in plan), "limit": sum(p["verdict"] == "LIMIT" for p in plan),
                                       "reject": sum(p["verdict"] == "REJECT" for p in plan), "granted_kw": round(sum(float(p.get("granted_avg_kw", 0) or 0) for p in plan), 1)} if plan else None})
    zones = [{"id": "market", "title": "Grid and market"}, {"id": "switchboard", "title": "Switchboard"},
             {"id": "protected", "title": "Protected, never curtailed"}, {"id": "flexible", "title": "Flexible loads"}]
    in_plan = {n["id"] for n in nodes if n.get("plan")}
    links = [["aggregator", "grid", "hot"], ["jepx", "grid", ""], ["grid", "msb", "hot"], ["pv", "msb", ""], ["bess", "msb", "hot" if "bess" in in_plan else ""]]
    links += [["msb", n["id"], "hot" if n["id"] in in_plan else ("crit" if n["state"] == "crit" else "")] for n in nodes if n["zone"] in ("protected", "flexible")]
    sor = [{"name": "MELSEC PLCs", "sub": f"{len(tags)} live tags"}, {"name": "ICONICS SCADA", "sub": "OPC UA and MQTT"},
           {"name": "ME96 meters", "sub": f"{STORE.query('SELECT COUNT(*) AS n FROM {t:meters}')[0]['n']} meters, 5-minute"},
           {"name": "MES", "sub": f"{len(C.schedule(DEMO_DATE))} jobs today"}, {"name": "Aggregator portal", "sub": f"{len(C.dr_events(''))} events this season"}]
    return {"zones": zones, "nodes": nodes, "links": links, "systems_of_record": sor, "plan_id": sim.get("plan_id"), "edge_summary": sim.get("summary"),
            "demo_now": DEMO_NOW, "source": C.src("assets", "meters", "telemetry_5min", "plc_tags_snapshot", "interlock_rules", "dr_events", "jepx_prices_30min", "pv_forecast_30min", "bess_state_5min", "compressor_perf")}


# ------------------------------------------------------------------------------------------------
RECORDED = {  # agent -> the grounding probe whose recorded reply shows this agent's work, and the ADK case set
    "optimization_orchestrator": ("G01_S1_dr_plan", "end_to_end"), "market_intelligence_agent": ("G07_S7_pv", "market"),
    "factory_interlock_agent": ("G03_S3_compressors", "factory"), "bess_strategy_agent": ("G06_S6_bess", "bess"),
    "asset_health_agent": ("G04_S4_anomalies", "health"), "gain_share_agent": ("G05_S5_july", "gainshare"), "safety_auditor": ("G01_S1_dr_plan", "safety"),
}


@router.get("/recorded")
def recorded(agent: str = "optimization_orchestrator"):
    """A recorded run from the evaluation evidence (eval/results), labelled replay: the prompt, the reply the agents gave
    then, the SQL checks that grounded it, and the ADK cases for that agent's set."""
    probe_id, case_set = RECORDED.get(agent, RECORDED["optimization_orchestrator"])
    gr = _load_json(os.path.join(RES, "grounding_results.json")) or {}
    adk = _load_json(os.path.join(RES, "adk_summary.json")) or {}
    probe = next((p for p in gr.get("probes", []) if p["id"] == probe_id), None)
    cases = [{"id": k, "first": v["first_attempt"], "latency_s": v.get("info_first", {}).get("invocation_duration_v1")} for k, v in adk.get("cases", {}).items() if v.get("set") == case_set]
    return {"agent": agent, "replay": True, "label": "replay from eval/results, not a live run",
            "probe": {"id": probe["id"], "prompt": probe["prompt"], "reply": probe["first"]["reply"], "verdict": probe["label"],
                      "checks": probe["first"].get("checks", []), "recorded_at": gr.get("run_at") or gr.get("at")} if probe else None,
            "cases": cases, "source": ["eval/results/grounding_results.json", "eval/results/adk_summary.json"]}


# ------------------------------------------------------------------------------------------------
def _replay_events() -> list[dict]:
    """The 13:00 call replayed from the deterministic tools: real tool outputs, a real pending action, no model call.
    Specialist lines are derived from tool results; the lead's closing text is the recorded reply from the evaluation."""
    from google.genai import types

    from server import app as srv

    O, F, M, B, S, G = "optimization_orchestrator", "factory_interlock_agent", "market_intelligence_agent", "bess_strategy_agent", "safety_auditor", "gain_share_agent"
    evs: list[dict] = []
    t = [0.0]

    def add(author, content):
        for e in srv._part_events(author, content):
            t[0] += 0.6
            evs.append({**e, "t": round(t[0], 1), "replay": True})

    def call(name, args):
        return types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args=args))])

    def resp(name, r):
        return types.Content(role="model", parts=[types.Part(function_response=types.FunctionResponse(name=name, response=r))])

    def text(s):
        return types.Content(role="model", parts=[types.Part(text=s)])

    evs.append({"type": "session", "session_id": f"replay-{int(time.time())}", "replay": True, "t": 0})
    add(O, call(M, {"request": "JEPX, imbalance and PV for 16:30 to 19:00"}))
    add(O, call(F, {"request": "3,000 kW plan for DR-20260819, 16:30 to 19:00"}))
    add(O, call(B, {"request": "battery plan for the DR window and the spike"}))
    jp = T_market.get_jepx_prices(DEMO_DATE)
    add(M, call("get_jepx_prices", {"date": DEMO_DATE})); add(M, resp("get_jepx_prices", jp))
    pv = T_market.get_pv_forecast(DEMO_DATE)
    add(M, call("get_pv_forecast", {"date": DEMO_DATE})); add(M, resp("get_pv_forecast", pv))
    sw = (jp.get("spike_windows") or [{}])[0]
    risk = [s for s in pv.get("slots", []) if s.get("pv_risk_slot")]
    add(M, text(f"Spot peaks at {sw.get('max_spot_jpy_kwh', 0):.1f} JPY/kWh between {sw.get('start', '')} and {sw.get('end', '')}; the imbalance estimate reaches {sw.get('max_imbalance_jpy_kwh', 0):.1f}. "
                + (f"PV p10 falls to {min(s['p10_kw'] for s in risk):,.1f} kW in the {risk[0]['time'][:5]} cloud band." if risk else "")))
    fl = T_factory.list_flexible_loads(DEMO_DATE, "16:30", "19:00")
    add(F, call("list_flexible_loads", {"date": DEMO_DATE, "start": "16:30", "end": "19:00"})); add(F, resp("list_flexible_loads", fl))
    sim = T_factory.simulate_edge_interlock(fl["draft_plan_json"])
    add(F, call("simulate_edge_interlock", {"plan_json": "(draft plan)"})); add(F, resp("simulate_edge_interlock", sim))
    s = sim["summary"]
    rej = "; ".join(f"{x['asset_id']} {x['action']} ({', '.join(x['rule_ids'])})" for x in sim.get("rejected_actions", []))
    prop = T_factory.propose_load_shed_plan(sim["plan_id"], f"Edge-verified plan {sim['plan_id']}: firm {s['firm_reduction_kw']:,.0f} kW against {fl.get('target_kw', 3000):,.0f} kW; rejected actions excluded.", "DR-20260819")
    add(F, call("propose_load_shed_plan", {"plan_id": sim["plan_id"]})); add(F, resp("propose_load_shed_plan", prop))
    add(F, text(f"The edge evaluated {s['actions_evaluated']} actions: {s['accepted']} accepted, {s['limited']} limited, {s['rejected']} rejected ({rej}). "
                f"Firm {s['firm_reduction_kw']:,.0f} kW against the {fl.get('target_kw', 3000):,.0f} kW target; the plan is queued for sign-off."))
    from factory_copilot.tools import bess as T_bess
    add(B, call("optimize_bess_schedule", {"date": DEMO_DATE}))
    try:
        bo = T_bess.optimize_bess_schedule(DEMO_DATE, "forecast_aware_v2")
    except TypeError:
        bo = T_bess.optimize_bess_schedule(DEMO_DATE)
    add(B, resp("optimize_bess_schedule", bo))
    k = bo.get("kpis") or bo.get("policies", {}).get("forecast_aware_v2", {}).get("kpis", {})
    add(B, text(f"forecast_aware_v2 reaches {k.get('soc_at_dr_start_pct', 0):.1f} % SOC by 16:30 and gives the window {k.get('dr_firm_kw', 0):,.0f} kW firm; it does not charge in the cloud band."))
    add(O, call(S, {"request": f"audit {sim['plan_id']}"}))
    au = T_safety.audit_plan(sim["plan_id"])
    add(S, call("audit_plan", {"plan_id": sim["plan_id"]})); add(S, resp("audit_plan", au))
    add(S, text(f"Audit {au.get('verdict', au.get('status'))}: " + "; ".join(f"{f['check']} {f['result']}" for f in au.get("findings", []))))
    gr = _load_json(os.path.join(RES, "grounding_results.json")) or {}
    probe = next((p for p in gr.get("probes", []) if p["id"] == "G01_S1_dr_plan"), None)
    add(O, text(probe["first"]["reply"] if probe else f"Edge-verified plan {sim['plan_id']} waits for your sign-off. Nothing has been executed."))
    evs.append({"type": "final", "author": O, "replay": True, "t": round(t[0] + 0.2, 1)})
    evs.append({"type": "done", "t": round(t[0] + 0.3, 1), "replay": True})
    return evs


@router.get("/replay")
async def replay(pace_ms: int = 350):
    """The 13:00 call as a badged replay: the same event shapes as /api/chat, produced by the deterministic tools with no
    model call. The pending action it queues is real, so the sign-off hold can be exercised without a model."""
    evs = await asyncio.to_thread(_replay_events)

    async def sse():
        for e in evs:
            yield f"data: {json.dumps(e, default=str)}\n\n"
            await asyncio.sleep(max(0, min(pace_ms, 2000)) / 1000)

    return StreamingResponse(sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
