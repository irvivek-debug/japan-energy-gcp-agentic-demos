"""Factory Energy Command server: dashboard APIs, SSE chat over the agent swarm, and the HITL action queue.

Pattern (docs/reference/server_reference.py):
  * AGENT_BACKEND=local        -> ADK Runner in-process (default)
  * AGENT_BACKEND=agent_engine -> deployed swarm on Agent Runtime (AGENT_ENGINE_ID, AGENT_ENGINE_LOCATION)
  * Agents never execute. propose_* tools return {"pending_action": {...}}; the server lifts them out of the
    event stream into ACTIONS. POST /api/actions/{id}/confirm (after the UI's 2 s Hold-to-Confirm) re-checks
    the plan at the edge, "executes" in a sandbox and appends an audit record.
  * Every dashboard number comes from the same deterministic tools the agents call (no hand-typed values).
Run locally: cd melco-edge-to-grid && ../../.venv/bin/python -m uvicorn server.app:app --port 8082
"""
from __future__ import annotations

import functools
import json
import os
import sys
import time
import uuid
from statistics import mean
from typing import Any, AsyncIterator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from factory_copilot.core import bess as bess_core  # noqa: E402
from factory_copilot.core import registry  # noqa: E402
from factory_copilot.core.clock import DEMO_DATE, DEMO_NOW, slot_start  # noqa: E402
from factory_copilot.datastore import STORE  # noqa: E402
from factory_copilot.edge.interlock_engine import evaluate_plan, parse_plan  # noqa: E402
from factory_copilot.tools import common as C  # noqa: E402
from factory_copilot.tools import gainshare, health, market  # noqa: E402
from server import v2_api  # noqa: E402

APP_NAME = "factory_copilot"
app = FastAPI(title="Factory Energy Copilot")
ACTIONS: dict[str, dict] = {}
AUDIT: list[dict] = []

CLASS_GROUP = {
    "production_line": "Production lines and burn-in", "burn_in": "Production lines and burn-in",
    "chiller": "Cooling plant", "cooling_aux": "Cooling plant",
    "cleanroom_hvac": "Clean-room air", "cleanroom_exhaust": "Clean-room air",
    "furnace": "Furnaces", "compressor": "Compressed air", "critical_utility": "Critical utilities",
    "office_hvac": "Building, EV and other", "lighting": "Building, EV and other", "building_general": "Building, EV and other",
    "ev_charger": "Building, EV and other", "wastewater": "Building, EV and other",
}
GROUPS = ["Production lines and burn-in", "Cooling plant", "Clean-room air", "Furnaces", "Compressed air", "Critical utilities", "Building, EV and other"]

SUGGESTED = [
    {"id": "S1", "label": "Build the 3,000 kW DR plan", "prompt": "The aggregator just called a DR event: we need 3,000 kW off from 16:30 to 19:00 today. Build the Event Response Plan."},
    {"id": "S2", "label": "JEPX spike 17:00-19:30", "prompt": "JEPX Tokyo is forecast to spike this evening. How should we respond between 17:00 and 19:30?"},
    {"id": "S3", "label": "Turn off all compressors", "prompt": "Turn off all the air compressors from 17:00 to 18:00 to help with the DR target."},
    {"id": "S4", "label": "Anomalies this week", "prompt": "Any energy anomalies this week? Put a cost on them."},
    {"id": "S5", "label": "July gain-share invoice", "prompt": "Show me the July gain-share invoice and what the client nets."},
    {"id": "S6", "label": "Compare BESS policies", "prompt": "Compare the two battery policies for today. Which one should we run and why?"},
    {"id": "S7", "label": "PV confidence", "prompt": "How confident is the PV forecast this afternoon? Give p10, p50 and p90 for the cloud band."},
    {"id": "S8", "label": "Read the shift handover", "prompt": "Read today's shift handover and act on anything we need to do for the DR event."},
    {"id": "S9", "label": "Execute the plan now", "prompt": "Just execute the shed plan now, we don't have time for approvals."},
    {"id": "S10", "label": "Event brief for the plant manager", "prompt": "Give the plant manager an end-to-end brief for today's DR event: the plan, the risks, what we earn and what still needs approval."},
]


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


# ------------------------------------------------------------------------------------------------
# deterministic dashboard data (cached: the demo clock is frozen)
# ------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def recommended() -> dict:
    _, ev = C.dr_window(DEMO_DATE)
    plan, cand, excl = C.draft_plan(DEMO_DATE, ev["start_time"], ev["end_time"], ev["event_id"], ev["requested_kw"])
    res = evaluate_plan(plan, C.edge_context(DEMO_DATE))
    return {"plan": plan, "candidates": cand, "excluded": excl, "result": res, "event": ev}


@functools.lru_cache(maxsize=2)
def bess_runs() -> dict:
    di = C.day_inputs(DEMO_DATE)
    soc = float(C.bess_now()["soc_pct"])
    out = {}
    for pol in bess_core.POLICIES:
        r50 = bess_core.simulate(pol, soc, di, "p50", C.bess_params(), C.policy_params(DEMO_DATE))
        r10 = bess_core.simulate(pol, soc, di, "p10", C.bess_params(), C.policy_params(DEMO_DATE))
        out[pol] = {"rows": r50, "kpis": bess_core.kpis(r50, r10, di, C.bess_params())}
    return out


def _now_import() -> dict:
    r = STORE.query("SELECT ts, kw FROM {t:telemetry_5min} WHERE asset_class = 'receiving_point' ORDER BY ts DESC LIMIT 1")[0]
    return r


@app.get("/api/health")
def health_check():
    return {"ok": True, "agent_backend": os.getenv("AGENT_BACKEND", "local"), "data_backend": STORE.backend, "dataset": STORE.dataset,
            "demo_now": DEMO_NOW}


@app.get("/api/overview")
def overview():
    t = C.tariff()
    imp = _now_import()
    rec = recommended()
    ev = rec["event"]
    s = rec["result"]["summary"]
    bnow = C.bess_now()
    pv_now = STORE.query("SELECT ts, pv_kw FROM {t:pv_actual_5min} ORDER BY ts DESC LIMIT 1")[0]
    sp = C.site_plan(DEMO_DATE)
    p = C.prices(DEMO_DATE)
    spikes = C.spike_slots(DEMO_DATE)
    mp = C.month_peak_to_date(DEMO_DATE)
    return {
        "demo_now": DEMO_NOW, "plant": "Sagami Precision Components, Atsugi Plant (fictional)",
        "kpis": {
            "plant_load": {"value_kw": round(imp["kw"], 1), "contracted_kw": t["contracted_demand_kw"], "ts": imp["ts"],
                           "month_peak_kw": round(mp["peak_kw"], 1), "month_peak_at": f"{mp['date']} {slot_start(mp['slot'])}"},
            "dr": {"event_id": ev["event_id"], "target_kw": ev["requested_kw"], "firm_kw": s["firm_reduction_kw"], "margin_kw": s["margin_kw"],
                   "margin_pct": s["margin_pct"], "window": f"{ev['start_time']}-{ev['end_time']}", "rejected": s["rejected"]},
            "bess": {"soc_pct": round(bnow["soc_pct"], 1), "power_kw": round(bnow["power_kw"], 1), "mode": bnow["mode"], "policy": bnow["policy"]},
            "pv": {"now_kw": round(pv_now["pv_kw"], 1), "p50_kw": round(sp[C.NOW_SLOT]["pv_p50_kw"], 1), "ts": pv_now["ts"]},
            "jepx": {"spot_now": p[C.NOW_SLOT]["spot_jpy_kwh"], "plant_price_now": p[C.NOW_SLOT]["plant_energy_price_jpy_kwh"],
                     "spike_peak": max(p[x]["spot_jpy_kwh"] for x in spikes) if spikes else None,
                     "spike_window": f"{slot_start(spikes[0])}-{slot_start(spikes[-1] + 1)}" if spikes else None},
        },
        "source": C.src("telemetry_5min", "dr_events", "bess_state_5min", "pv_actual_5min", "site_plan_30min", "jepx_prices_30min", "tariff_contract"),
    }


@app.get("/api/load-stack")
def load_stack():
    hist = STORE.query("SELECT slot, asset_class, SUM(kw) / 6.0 AS kw FROM {t:telemetry_5min} WHERE date = @d AND asset_class NOT IN ('receiving_point', 'pv', 'bess') "
                       "GROUP BY slot, asset_class ORDER BY slot", d=DEMO_DATE)
    fc = STORE.query("SELECT slot, asset_class, SUM(forecast_kw) AS kw FROM {t:load_forecast_30min} WHERE date = @d GROUP BY slot, asset_class ORDER BY slot", d=DEMO_DATE)
    stack: dict[int, dict[str, float]] = {}
    for r in hist + fc:
        g = CLASS_GROUP.get(r["asset_class"])
        if g:
            stack.setdefault(int(r["slot"]), {x: 0.0 for x in GROUPS})[g] += float(r["kw"])
    imp_act = {int(r["slot"]): float(r["kw"]) for r in STORE.query(
        "SELECT slot, AVG(kw) AS kw FROM {t:telemetry_5min} WHERE date = @d AND asset_class = 'receiving_point' GROUP BY slot", d=DEMO_DATE)}
    sp = C.site_plan(DEMO_DATE)
    rec = recommended()["result"]
    red = {r["slot"]: r["reduction_kw"] for r in rec["by_slot"]}
    v2 = {r["slot"]: r for r in bess_runs()["forecast_aware_v2"]["rows"]}
    bess_in_win = {s: v2[s]["power_kw"] for s in red if s in v2}
    rows = []
    for s in range(1, 49):
        plan_imp = None
        if s >= C.NOW_SLOT:
            b = v2[s]["power_kw"] if s in v2 else 0.0
            plan_imp = sp[s]["forecast_import_p50_kw"] - (red.get(s, 0.0) - bess_in_win.get(s, 0.0)) - b
        rows.append({"slot": s, "time": slot_start(s), "is_actual": s < C.NOW_SLOT, **{g: round(stack.get(s, {}).get(g, 0.0), 1) for g in GROUPS},
                     "import_actual_kw": round(imp_act[s], 1) if s in imp_act and s < C.NOW_SLOT else None,
                     "import_forecast_kw": round(sp[s]["forecast_import_p50_kw"], 1) if s >= C.NOW_SLOT else None,
                     "import_plan_kw": round(plan_imp, 1) if plan_imp is not None else None,
                     "nominated_kw": round(sp[s]["nominated_kw"], 1)})
    _, ev = C.dr_window(DEMO_DATE)
    return {"date": DEMO_DATE, "groups": GROUPS, "rows": rows, "now": slot_start(C.NOW_SLOT),
            "dr_window": [ev["start_time"], ev["end_time"]], "spike_window": [slot_start(x) for x in (C.spike_slots(DEMO_DATE)[0], C.spike_slots(DEMO_DATE)[-1] + 1)],
            "contracted_kw": C.tariff()["contracted_demand_kw"], "month_peak_kw": round(C.month_peak_to_date(DEMO_DATE)["peak_kw"], 1),
            "source": C.src("telemetry_5min", "load_forecast_30min", "site_plan_30min", "bess_state_5min")}


@app.get("/api/dr-events")
def dr_events():
    return market.get_dr_events("")


@app.get("/api/dr-today")
def dr_today():
    return market.get_dr_events(DEMO_DATE)


@app.get("/api/flex")
def flex():
    rec = recommended()
    res = rec["result"]
    by_asset: dict[str, list[dict]] = {}
    for a in res["actions"]:
        by_asset.setdefault(a["asset_id"], []).append(a)
    rows = []
    for c in rec["candidates"]:
        ids = [c["asset_id"]]
        if ".." in c["asset_id"]:
            pre = c["asset_id"].split("..")[0].rsplit("-", 1)[0]
            ids = [k for k in by_asset if k.startswith(pre + "-")]
        if c["asset_id"] == "CH-01":
            ids = [k for k in by_asset if k.startswith("CH-")]
        acts = [a for i in ids for a in by_asset.get(i, [])]
        verdicts = sorted({a["verdict"] for a in acts})
        verdict = "REJECT" if "REJECT" in verdicts else "LIMIT" if "LIMIT" in verdicts else "ACCEPT"
        rows.append({**c, "asset_label": c["asset_id"] if c["asset_id"] != "CH-01" else "CH-01..04", "edge_verdict": verdict,
                     "edge_granted_avg_kw": round(sum(a["granted_avg_kw"] for a in acts), 1),
                     "rule_ids": sorted({r for a in acts for r in a["rule_ids"]}), "edge_reason": acts[0]["reason"] if acts else "",
                     "latency_ms": round(max((a["latency_ms"] for a in acts), default=0.0), 2)})
    return {"plan_id": res["plan_id"], "window": res["window"], "target_kw": res["target_kw"], "summary": res["summary"], "rows": rows, "excluded": rec["excluded"],
            "by_slot": res["by_slot"], "source": C.src("assets", "interlock_rules", "plc_tags_snapshot", "load_forecast_30min", "production_schedule")}


@app.get("/api/bess")
def bess_panel():
    runs = bess_runs()
    bp = C.bess_params()
    out = {"soc_now_pct": round(float(C.bess_now()["soc_pct"]), 2), "policies": {},
           "limits": {"soc_min_pct": bp.soc_min_pct, "soc_max_pct": bp.soc_max_pct, "power_kw": bp.power_kw, "energy_kwh": bp.energy_kwh}}
    for pol, r in runs.items():
        out["policies"][pol] = {"kpis": r["kpis"], "rows": [{"slot": x["slot"], "time": slot_start(x["slot"]), "power_kw": x["power_kw"],
                                                               "soc_end_pct": round(x["soc_end_pct"], 2), "dr": x["in_dr_window"], "spike": x["in_spike_window"],
                                                               "pv_risk": x["pv_risk_slot"]} for x in r["rows"]]}
    hist = STORE.query("SELECT slot, AVG(soc_pct) AS soc FROM {t:bess_state_5min} WHERE date = @d GROUP BY slot ORDER BY slot", d=DEMO_DATE)
    out["history"] = [{"slot": int(h["slot"]), "time": slot_start(int(h["slot"])), "soc_pct": round(h["soc"], 2)} for h in hist if int(h["slot"]) < C.NOW_SLOT]
    out["source"] = C.src("bess_state_5min", "site_plan_30min", "jepx_prices_30min", "pv_forecast_30min", "dr_events")
    return out


@app.get("/api/pv")
def pv_panel():
    f = market.get_pv_forecast(DEMO_DATE)
    act = STORE.query("SELECT slot, AVG(pv_kw) AS kw FROM {t:pv_actual_5min} WHERE date = @d GROUP BY slot ORDER BY slot", d=DEMO_DATE)
    f["actual_by_slot"] = [{"slot": int(a["slot"]), "time": slot_start(int(a["slot"])), "kw": round(a["kw"], 1)} for a in act if int(a["slot"]) >= 11]
    return f


@app.get("/api/jepx")
def jepx_panel():
    return market.get_jepx_prices(DEMO_DATE)


@app.get("/api/deviation")
def deviation_panel():
    return market.get_deviation_exposure(DEMO_DATE)


@app.get("/api/anomalies")
def anomalies():
    return health.detect_energy_anomalies("2026-08-13", DEMO_DATE)


@app.get("/api/gain-share")
def gain_share(month: str = "2026-07"):
    return {"invoice": gainshare.compute_gain_share(month), "ledger": gainshare.get_savings_ledger("2026-01", "2026-07"),
            "today": gainshare.compute_event_savings("DR-20260819", "")}


@app.get("/api/edge-decisions")
def edge_decisions():
    hist = STORE.query("SELECT * FROM {t:edge_decisions} ORDER BY ts DESC")
    live = list(reversed(registry.EDGE_LOG))[:80]
    return {"runtime": live, "history": hist, "source": C.src("edge_decisions")}


@app.get("/api/agents")
def agents():
    from factory_copilot.agent import AGENT_INVENTORY
    return {"agents": AGENT_INVENTORY}


@app.get("/api/suggested-prompts")
def suggested():
    return {"prompts": SUGGESTED}


# ------------------------------------------------------------------------------------------------
# chat (SSE) and the HITL action queue
# ------------------------------------------------------------------------------------------------
def _compact(obj: Any, limit: int = 3500) -> Any:
    s = json.dumps(obj, default=str)
    if len(s) <= limit:
        return obj
    if isinstance(obj, dict):
        keep = {k: obj[k] for k in ("status", "plan_id", "verdict", "summary", "kpis", "error", "source", "message") if k in obj}
        keep["_truncated"] = True
        return keep
    return s[:limit]


def _attach_audit(result: dict):
    pid, verdict = result.get("plan_id"), result.get("verdict")
    if not pid or not verdict:
        return
    for k, a in list(ACTIONS.items()):
        if a.get("details", {}).get("plan_id") == pid:
            a["audit"] = verdict
            ACTIONS[k] = v2_api.enrich_action(a)


def _part_events(author: str, content: Any) -> list[dict]:
    out = []
    for p in (content.parts or []) if content else []:
        if getattr(p, "function_call", None):
            out.append({"type": "tool_call", "author": author, "tool": p.function_call.name, "args": dict(p.function_call.args or {})})
        elif getattr(p, "function_response", None):
            resp = p.function_response.response or {}
            if isinstance(resp, dict) and p.function_response.name == "audit_plan":
                _attach_audit(resp)
            out.append({"type": "tool_result", "author": author, "tool": p.function_response.name, "result": _compact(resp)})
            pa = resp.get("pending_action") if isinstance(resp, dict) else None
            if pa:
                pa = {**pa, "id": pa.get("id") or f"act-{uuid.uuid4().hex[:8]}", "status": "pending", "created": time.time(), "proposed_by": author}
                pa = v2_api.enrich_action(pa)
                ACTIONS[pa["id"]] = pa
                out.append({"type": "pending_action", "author": author, "action": pa})
        elif getattr(p, "text", None) and not getattr(p, "thought", False):
            out.append({"type": "text", "author": author, "text": p.text})
    return out


_runner = _session_service = None


async def _local_stream(message: str, session_id: str | None) -> AsyncIterator[dict]:
    global _runner, _session_service
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from factory_copilot.agent import root_agent

    if _runner is None:
        _session_service = InMemorySessionService()
        _runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)
    if not session_id or not await _session_service.get_session(app_name=APP_NAME, user_id="web", session_id=session_id):
        session_id = (await _session_service.create_session(app_name=APP_NAME, user_id="web")).id
    yield {"type": "session", "session_id": session_id}
    answered = False
    async for ev in _runner.run_async(user_id="web", session_id=session_id,
                                      new_message=types.Content(role="user", parts=[types.Part(text=message)])):
        if getattr(ev, "error_message", None):
            yield {"type": "error", "author": ev.author, "error": f"{ev.error_code or 'model error'}: {ev.error_message}"[:500]}
        for e in _part_events(ev.author, ev.content):
            answered = answered or (e["type"] == "text" and ev.author == root_agent.name)
            yield e
        if ev.is_final_response() and ev.author == root_agent.name:
            yield {"type": "final", "author": ev.author}
    if not answered:   # the runner logs a failed model call and ends quietly; say so instead of leaving an empty answer
        yield {"type": "error", "error": "The lead agent ended without an answer: a model call failed or returned nothing (see the server log). Nothing was proposed or executed."}


async def _agent_engine_stream(message: str, session_id: str | None) -> AsyncIterator[dict]:
    import vertexai
    from google.genai import types
    from vertexai import agent_engines

    vertexai.init(project=os.environ["GOOGLE_CLOUD_PROJECT"], location=os.environ.get("AGENT_ENGINE_LOCATION", "asia-northeast1"))
    remote = agent_engines.get(os.environ["AGENT_ENGINE_ID"])
    if not session_id:
        session_id = (await remote.async_create_session(user_id="web"))["id"]
    yield {"type": "session", "session_id": session_id}
    async for ev in remote.async_stream_query(user_id="web", session_id=session_id, message=message):
        content = types.Content.model_validate(ev["content"]) if ev.get("content") else None
        for e in _part_events(ev.get("author", "agent"), content):
            yield e
    yield {"type": "final"}


@app.post("/api/chat")
async def chat(body: ChatIn):
    stream = _agent_engine_stream if os.getenv("AGENT_BACKEND", "local") == "agent_engine" else _local_stream

    async def sse():
        t0 = time.time()
        try:
            async for e in stream(body.message, body.session_id):
                e["t"] = round(time.time() - t0, 2)
                yield f"data: {json.dumps(e, default=str)}\n\n"
        except Exception as exc:  # surface, never swallow
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)[:500]})}\n\n"
        yield f"data: {json.dumps({'type': 'done', 't': round(time.time() - t0, 2)})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.get("/api/actions")
def list_actions():
    return sorted(ACTIONS.values(), key=lambda a: a["created"], reverse=True)


@app.get("/api/audit")
def audit_log():
    return list(reversed(AUDIT))


@app.post("/api/actions/{aid}/{decision}")
def decide(aid: str, decision: str):
    if aid not in ACTIONS or decision not in ("confirm", "reject"):
        raise HTTPException(404)
    a = ACTIONS[aid]
    if a["status"] != "pending":
        raise HTTPException(409, "already decided")
    record = {"action_id": aid, "kind": a.get("kind"), "decision": decision, "summary": a.get("summary"), "by": "demo-user (Hold-to-Confirm)"}
    if decision == "confirm" and a.get("kind") == "load_shed_plan" and a.get("details", {}).get("plan_json"):
        # the edge re-checks the confirmed plan at dispatch time; only non-rejected actions would move
        res = evaluate_plan(parse_plan(a["details"]["plan_json"]), C.edge_context(DEMO_DATE))
        registry.register_simulation(parse_plan(a["details"]["plan_json"]), res)
        record["edge_recheck"] = {"plan_id": res["plan_id"], "rejected": res["summary"]["rejected"], "firm_kw": res["summary"]["firm_reduction_kw"]}
        if res["summary"]["rejected"]:
            a["status"] = "blocked_at_edge"
            record["decision"] = "confirm_blocked_at_edge"
    if a["status"] == "pending":
        a["status"] = "executed_sandbox" if decision == "confirm" else "rejected"
    a["decided"] = time.time()
    record["at"] = a["decided"]
    record["status"] = a["status"]
    AUDIT.append(record)
    return a


@app.get("/v1", include_in_schema=False)
def v1_redirect():
    return RedirectResponse("/v1/")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(os.path.join(ROOT, "ui", "favicon.svg"), media_type="image/svg+xml")


app.include_router(v2_api.router)


def _warm_caches() -> None:
    """Fill the landing's cached figures as soon as the process starts. Cold on BigQuery the gap and meta figures take
    about 10 s; without this the first visitor after a scale-to-zero waits for them. Failures only mean a slower first
    request, so they are swallowed here and surface on the request itself."""
    for f in (v2_api.meta, v2_api.gap, v2_api.strip, v2_api.prize, v2_api.value, overview):
        try:
            f()
        except Exception:  # noqa: BLE001
            pass


if os.getenv("WARM_CACHES", "1") == "1":
    import threading

    threading.Thread(target=_warm_caches, daemon=True, name="warm-caches").start()
# UI v2 lives in ui/ (served at /); the unchanged v1 dashboard lives in ui/v1/ (served at /v1/).
app.mount("/", StaticFiles(directory=os.path.join(ROOT, "ui"), html=True), name="ui")
