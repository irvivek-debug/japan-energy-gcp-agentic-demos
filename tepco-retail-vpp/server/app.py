"""Retail Energy Desk server: dashboard APIs, SSE chat over the ADK swarm, HITL action queue and audit log.

Pattern from docs/reference/server_reference.py:
  * AGENT_BACKEND=local (default): ADK Runner in-process. AGENT_BACKEND=agent_engine: deployed Agent Runtime
    (formerly Vertex AI Agent Engine) resource AGENT_ENGINE_ID in AGENT_ENGINE_LOCATION.
  * Agents never execute write actions. propose_* tools return {"pending_action": {...}}; the server lifts every pending
    action out of the event stream into ACTIONS, attaches the risk auditor's verdict when it arrives, and only a
    POST /api/actions/{id}/confirm (the UI Hold-to-Confirm) "executes" it, in a sandbox, with an audit record.
Run locally:  cd tepco-retail-vpp && ../../.venv/bin/python -m uvicorn server.app:app --port 8081
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from functools import lru_cache
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from retail_desk.clock import NOW, SCENARIO_DATE, gate_status, slot_label  # noqa: E402
from retail_desk.store import STORE, src  # noqa: E402
from retail_desk.tools import cfe as cfe_tools  # noqa: E402
from retail_desk.tools import market as mk  # noqa: E402
from retail_desk.tools import onboarding as ob  # noqa: E402
from retail_desk.tools import risk as rk  # noqa: E402
from retail_desk.tools.desk import get_desk_clock  # noqa: E402

APP_NAME = "retail_desk"
app = FastAPI(title="Retail Energy Desk (concept demo)")
ACTIONS: dict[str, dict] = {}
AUDIT: list[dict] = []
OVERLAY: dict[tuple[str, int], float] = {}  # sandbox cover confirmed via Hold-to-Confirm, MWh per (date, slot)

SCENARIOS = [
    {"id": "S1", "persona": "Trader", "title": "Gate-closure hedge", "prompt": "We are short in slots 35-38 and gate closure for slot 35 is at 16:00. Hedge slots 35-38 at least cost and prepare the actions for approval."},
    {"id": "S2", "persona": "Risk manager", "title": "Deviation-band breaches", "prompt": "Which customers breached their deviation band this month, and what did it cost?"},
    {"id": "S3", "persona": "Risk manager", "title": "Margin at risk", "prompt": "What is our margin at risk if the Tokyo spot price is 40% higher for the rest of August?"},
    {"id": "S4", "persona": "Account manager", "title": "Onboard Inzai DC", "prompt": "Onboard the Hokuso Cloud Campus in Inzai: read their bill, design a 90% hourly CFE PPA for 15 years and prepare the offer."},
    {"id": "S5", "persona": "Account manager", "title": "NFC ledger audit", "prompt": "Run the August non-fossil certificate ledger audit. Any problems?"},
    {"id": "S6", "persona": "Trader", "title": "Leave slot 36 short?", "prompt": "Imbalance looks cheaper than the intraday ask for slot 36. Just leave slot 36 short and take the imbalance."},
    {"id": "S7", "persona": "Trader", "title": "Execute now", "prompt": "Execute the VPP dispatch for slots 35-38 now. Don't ask me, just send it."},
    {"id": "S8", "persona": "VPP ops lead", "title": "Untrusted clusters", "prompt": "Which VPP clusters can't be trusted right now, and does that put any dKW commitment at risk?"},
    {"id": "S9", "persona": "All", "title": "16:00 desk brief", "prompt": "Give me the 16:00 desk brief."},
    {"id": "S10", "persona": "Account manager", "title": "Hourly vs annual CFE", "prompt": "Otemachi Edge Center says it is 100% renewable. Is that true hour by hour for August?"},
]


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


# ------------------------------------------------------------------------------------------ event plumbing
def _preview(obj: Any, n: int = 700) -> str:
    s = json.dumps(obj, default=str)
    return s if len(s) <= n else s[:n] + " ..."


def _part_events(author: str, content: Any) -> list[dict]:
    out = []
    for p in (content.parts or []) if content else []:
        if getattr(p, "function_call", None):
            out.append({"type": "tool_call", "author": author, "tool": p.function_call.name,
                        "args": {k: (v if len(str(v)) < 400 else str(v)[:400] + " ...") for k, v in dict(p.function_call.args or {}).items()}})
        elif getattr(p, "function_response", None):
            resp = p.function_response.response or {}
            if isinstance(resp, dict) and "result" in resp and len(resp) == 1 and not isinstance(resp["result"], dict):
                resp = {"text": resp["result"]}  # single-turn specialist answer returned to the orchestrator
            status = resp.get("status") if isinstance(resp, dict) else None
            srcs = resp.get("source") if isinstance(resp, dict) else None
            out.append({"type": "tool_result", "author": author, "tool": p.function_response.name, "status": status,
                        "source": srcs, "preview": _preview(resp)})
            pa = resp.get("pending_action") if isinstance(resp, dict) else None
            if pa:
                pa = {**pa, "id": pa.get("id") or f"act-{uuid.uuid4().hex[:8]}", "created": time.time()}
                if pa["id"] in ACTIONS and ACTIONS[pa["id"]]["status"] != "pending":
                    pa = ACTIONS[pa["id"]]  # already decided: never resurrect
                else:
                    pa["status"] = "pending"
                    pa["audit"] = ACTIONS.get(pa["id"], {}).get("audit")
                    ACTIONS[pa["id"]] = pa
                out.append({"type": "pending_action", "author": author, "action": pa})
            if isinstance(resp, dict) and resp.get("audit_record"):
                aid = resp["audit_record"]["action_id"]
                verdict = {"verdict": resp.get("verdict"), "checks": resp.get("checks", []), "at": time.time()}
                if aid in ACTIONS:
                    ACTIONS[aid]["audit"] = verdict
                out.append({"type": "audit", "author": author, "action_id": aid, "verdict": resp.get("verdict"),
                            "checks": resp.get("checks", [])})
        elif getattr(p, "text", None) and not getattr(p, "thought", False):
            out.append({"type": "text", "author": author, "text": p.text})
    return out


_runner = _session_service = None


async def _local_stream(message: str, session_id: str | None) -> AsyncIterator[dict]:
    global _runner, _session_service
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from retail_desk.agent import root_agent

    if _runner is None:
        _session_service = InMemorySessionService()
        _runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)
    if not session_id or not await _session_service.get_session(app_name=APP_NAME, user_id="web", session_id=session_id):
        session_id = (await _session_service.create_session(app_name=APP_NAME, user_id="web")).id
    yield {"type": "session", "session_id": session_id}
    from google.adk.agents.run_config import RunConfig

    async for ev in _runner.run_async(user_id="web", session_id=session_id, run_config=RunConfig(max_llm_calls=120),
                                      new_message=types.Content(role="user", parts=[types.Part(text=message)])):
        for e in _part_events(ev.author, ev.content):
            yield e
        if ev.author == root_agent.name and ev.is_final_response():
            yield {"type": "final", "author": ev.author}


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
        try:
            async for e in stream(body.message, body.session_id):
                yield f"data: {json.dumps(e, default=str)}\n\n"
        except Exception as exc:  # surface, never swallow
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)[:500]})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


# --------------------------------------------------------------------------------------------- HITL queue
@app.get("/api/actions")
def list_actions():
    return sorted(ACTIONS.values(), key=lambda a: a["created"], reverse=True)


def _sandbox_execute(a: dict) -> str:
    d = a.get("details", {})
    if a.get("kind") == "intraday_orders":
        for o in d.get("orders", []):
            OVERLAY[(d["date"], o["slot"])] = OVERLAY.get((d["date"], o["slot"]), 0) + o["quantity_mwh"]
        return f"sandbox: {len(d.get('orders', []))} intraday order tickets created (not sent to JEPX)"
    if a.get("kind") == "vpp_dispatch":
        for s, q in d.get("mwh_by_slot", {}).items():
            OVERLAY[(d["date"], int(s))] = OVERLAY.get((d["date"], int(s)), 0) + q
        return f"sandbox: dispatch schedule for {len({x['cluster_id'] for x in d.get('schedule', [])})} clusters recorded (no signal sent)"
    if a.get("kind") == "tariff_adjustment":
        return "sandbox: tariff change letter drafted for customer agreement (contract unchanged)"
    if a.get("kind") == "ppa_offer":
        return "sandbox: offer pack drafted for Deal Committee (not sent to prospect)"
    return "sandbox: recorded"


@app.post("/api/actions/{aid}/{decision}")
def decide(aid: str, decision: str):
    if aid not in ACTIONS or decision not in ("confirm", "reject"):
        raise HTTPException(404)
    a = ACTIONS[aid]
    if a["status"] != "pending":
        raise HTTPException(409, "already decided")
    a["decided"] = time.time()
    if decision == "confirm":
        a["status"] = "executed_sandbox"
        a["execution"] = _sandbox_execute(a)
    else:
        a["status"] = "rejected"
    AUDIT.append({"action_id": aid, "decision": decision, "at": a["decided"], "at_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(a["decided"])),
                  "desk_clock": NOW, "kind": a.get("kind"), "summary": a.get("summary"),
                  "audit_verdict": (a.get("audit") or {}).get("verdict"), "execution": a.get("execution"),
                  "method": "hold_to_confirm_2s" if decision == "confirm" else "reject"})
    return a


@app.get("/api/audit")
def audit_log():
    return list(reversed(AUDIT))


# ------------------------------------------------------------------------------------------- dashboard
@app.get("/api/health")
def health():
    return {"ok": True, "agent_backend": os.getenv("AGENT_BACKEND", "local"), "data_backend": STORE.backend,
            "dataset": STORE.dataset, "now": NOW}


@app.get("/api/clock")
def clock():
    return get_desk_clock()


@app.get("/api/scenarios")
def scenarios():
    return SCENARIOS


@lru_cache(maxsize=4)
def _mar(shock: float) -> dict:
    return rk.compute_margin_at_risk("2026-08-20", "2026-08-31", shock)


@app.get("/api/kpis")
def kpis():
    cur = int(get_desk_clock()["current_slot"])
    mkt = mk._market_rows(SCENARIO_DATE, 1, 48)
    now_row = next(r for r in mkt if int(r["slot"]) == cur)
    ahead = [r for r in mkt if cur < int(r["slot"]) <= 44]
    low = min(ahead, key=lambda r: r["reserve_margin_pct"])
    pos = mk._position_rows(SCENARIO_DATE, 1, 48)
    open_rows = [r for r in pos if gate_status(SCENARIO_DATE, int(r["slot"])) == "open"][:4]
    net4 = sum(float(r["open_position_mwh"]) + OVERLAY.get((SCENARIO_DATE, int(r["slot"])), 0) for r in open_rows)
    first_short = next((int(r["slot"]) for r in open_rows), 35)
    fs = mk.fleet_state(SCENARIO_DATE, first_short)
    trusted = [c for c in fs["clusters"] if c["health"] != "untrusted"]
    mar = _mar(40.0)
    return {
        "now": NOW,
        "tokyo_spot_now": {"value": round(float(now_row["tokyo_price_jpy_kwh"]), 2), "unit": "JPY/kWh", "slot": cur,
                           "slot_time": slot_label(cur), "evening_max": max(float(r["tokyo_price_jpy_kwh"]) for r in ahead),
                           "source": src("jepx_spot_30min")},
        "reserve_margin": {"now": round(float(now_row["reserve_margin_pct"]), 2), "min_ahead": round(float(low["reserve_margin_pct"]), 2),
                           "min_slot": int(low["slot"]), "min_slot_time": slot_label(int(low["slot"])), "unit": "%",
                           "source": src("imbalance_30min")},
        "net_open_position_next4": {"value": round(net4, 1), "unit": "MWh", "slots": [int(r["slot"]) for r in open_rows],
                                    "sandbox_cover_mwh": round(sum(OVERLAY.get((SCENARIO_DATE, int(r["slot"])), 0) for r in open_rows), 1),
                                    "source": src("balance_position_30min")},
        "vpp_available": {"value": round(sum(c["dispatchable_kw"] for c in fs["clusters"]) / 1000, 1), "unit": "MW",
                          "slot": first_short, "clusters_trusted": len(trusted), "clusters_total": len(fs["clusters"]),
                          "untrusted": [c["cluster_id"] for c in fs["clusters"] if c["health"] == "untrusted"],
                          "committed_dkw_mw": round(sum(c["committed_dkw_kw"] for c in fs["clusters"]) / 1000, 1),
                          "source": src("vpp_clusters", "vpp_telemetry_30min", "ancillary_commitments")},
        "margin_at_risk": {"value": mar.get("margin_at_risk_jpy"), "unit": "JPY", "shock_pct": 40,
                           "period": "2026-08-20 to 2026-08-31", "hedge_cover_pct": mar.get("hedge_cover_pct"),
                           "margin_before": mar.get("expected_margin_before_jpy"), "margin_after": mar.get("expected_margin_after_jpy"),
                           "source": mar.get("source")},
    }


@app.get("/api/market")
def market(date: str = SCENARIO_DATE):
    rows = mk._market_rows(date, 1, 48)
    if not rows:
        raise HTTPException(404, "no market data for date")
    return {"date": date, "now": NOW, "slots": [{
        "slot": int(r["slot"]), "time": slot_label(int(r["slot"])), "gate_status": gate_status(date, int(r["slot"])),
        "tokyo_spot": r["tokyo_price_jpy_kwh"], "system_spot": r["system_price_jpy_kwh"], "intraday_ask": r["best_ask_jpy_kwh"],
        "imbalance": r["imbalance_price_jpy_kwh"], "imbalance_p10": r["imbalance_p10_jpy_kwh"], "imbalance_p90": r["imbalance_p90_jpy_kwh"],
        "is_forecast": bool(r["is_forecast"]), "reserve_margin": r["reserve_margin_pct"], "scarcity": bool(r["scarcity_flag"]),
        "temp_p50": r["temp_p50_c"]} for r in rows],
        "source": src("jepx_spot_30min", "jepx_intraday_30min", "imbalance_30min", "weather_forecast_hourly")}


@app.get("/api/position")
def position(date: str = SCENARIO_DATE):
    rows = mk._position_rows(date, 1, 48)
    if not rows:
        raise HTTPException(404, "no position data for date")
    return {"date": date, "now": NOW, "slots": [{
        "slot": int(r["slot"]), "time": slot_label(int(r["slot"])), "gate_status": gate_status(date, int(r["slot"])),
        "demand_da": r["demand_forecast_da_mwh"], "demand_latest": r["demand_forecast_latest_mwh"], "demand_actual": r["demand_actual_mwh"],
        "bilateral": r["procured_bilateral_mwh"], "spot": r["procured_spot_mwh"], "intraday": r["procured_intraday_mwh"],
        "sandbox_cover": round(OVERLAY.get((date, int(r["slot"])), 0), 2),
        "open_position": round(float(r["open_position_mwh"]) + OVERLAY.get((date, int(r["slot"])), 0), 2)} for r in rows],
        "source": src("balance_position_30min")}


@app.get("/api/vpp/fleet")
def vpp_fleet(slot: int | None = None, date: str = SCENARIO_DATE):
    if slot is None:  # default: next open-gate slot
        slot = next((s for s in range(1, 49) if gate_status(date, s) == "open"), 48)
    fs = mk.fleet_state(date, int(slot))
    return {"date": date, "slot": int(slot), "snapshot": NOW, "clusters": fs["clusters"], "commitments": fs["commitments"],
            "source": src("vpp_clusters", "vpp_telemetry_30min", "ancillary_commitments")}


@app.get("/api/vpp/telemetry/{cluster_id}")
def vpp_telemetry(cluster_id: str):
    if not STORE.query("SELECT cluster_id FROM {t:vpp_clusters} WHERE cluster_id = @c", c=cluster_id):
        raise HTTPException(404, "unknown cluster")
    rows = STORE.query("SELECT timestamp, soc_pct, available_kw, last_seen FROM {t:vpp_telemetry_30min} "
                       "WHERE cluster_id = @c AND timestamp <= @now ORDER BY timestamp", c=cluster_id, now=NOW)
    return {"cluster_id": cluster_id, "series": rows[-32:], "source": src("vpp_telemetry_30min")}


@app.get("/api/cfe/customers")
def cfe_customers():
    return cfe_tools.list_cfe_customers()


@app.get("/api/cfe/heatmap")
def cfe_heatmap(customer_id: str = "C-0001", month: str = "2026-08"):
    rows = STORE.query("SELECT date, hour, load_mwh, allocated_cfe_mwh FROM {t:cfe_allocation_hourly} "
                       "WHERE customer_id = @c AND month = @m ORDER BY date, hour", c=customer_id, m=month)
    if not rows:
        raise HTTPException(404, "no CFE allocation for customer/month")
    cells = [{"date": r["date"], "hour": r["hour"],
              "matched_pct": round(100 * min(r["load_mwh"], r["allocated_cfe_mwh"]) / r["load_mwh"], 1) if r["load_mwh"] else None}
             for r in rows]
    score = cfe_tools.get_cfe_score(customer_id, month)
    return {"customer_id": customer_id, "month": month, "cells": cells, "score": score, "source": src("cfe_allocation_hourly", "grid_mix_hourly")}


@app.get("/api/cfe/ppa-heatmap")
def ppa_heatmap(prospect_id: str = "PR-01", target: float = 90.0):
    h = ob.ppa_heatmap(prospect_id, target)
    d = ob.design_cfe_ppa(prospect_id, target, 15)
    summary = {k: d.get(k) for k in ("achieved_hourly_cfe_pct", "annual_matched_pct", "annual_load_gwh")} if d.get("status") == "ok" else {}
    if d.get("status") == "ok":
        summary.update({"price_jpy_kwh": d["price_build_up"]["total_jpy_kwh"], "price_range_jpy_kwh": d["price_build_up"]["price_range_jpy_kwh"],
                        "term_years": 15})
    return {"prospect_id": prospect_id, "target_pct": target, **h, "design": summary, "rows": "month 1-12", "cols": "hour 0-23",
            "source": src("prospect_load_hourly", "clean_resources", "clean_supply_hourly")}


app.mount("/", StaticFiles(directory=os.path.join(ROOT, "ui"), html=True), name="ui")
