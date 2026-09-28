"""Evolution Lab server: /api/* for the dashboard, SSE chat with the Lab Analyst, HITL action queue, static ui/.

Pattern: docs/reference/server_reference.py. The server ships the whole demo folder (Cloud Run), so the experiment
views read run evidence (runs/*.json, incl. in-flight *.partial.json) directly; the agent reads the exported lab_*
tables. Agents never execute writes: propose_* results are lifted into ACTIONS and executed only on Hold-to-Confirm.
Promotion is never offered for runs whose source is not "alphaevolve".
"""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from energy_lab.config import RUNS_DIR, SOURCE_ALPHAEVOLVE  # noqa: E402
from energy_lab.harness.budget import BudgetPolicy, Ledger  # noqa: E402
from energy_lab.harness.evidence import append_review, list_evidence, load_run, promotion_gate, reviews_for  # noqa: E402
from energy_lab.store import STORE, src  # noqa: E402

APP_NAME = "energy_lab"
app = FastAPI(title="AlphaEvolve Energy Lab")
ACTIONS: dict[str, dict] = {}
AUDIT: list[dict] = []


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


class ReviewIn(BaseModel):
    program_id: str
    reviewer: str = "demo-reviewer"
    note: str = ""


# ---------------------------------------------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"ok": True, "agent_backend": os.getenv("AGENT_BACKEND", "local"), "data_backend": os.getenv("DATA_BACKEND", "local"),
            "dataset": STORE.dataset, "ui_variant": ui_variant()}


def ui_variant() -> str:
    """'alpha' serves UI version alpha at / (v2 at /v2/, v1 at /v1/); anything else keeps v2 at / and v1 at /v1/."""
    return "alpha" if os.getenv("UI_VARIANT", "").strip().lower() == "alpha" else "v2"


@lru_cache(maxsize=8)
def _heatmap(fy: int) -> dict:
    rows = STORE.query("SELECT date, slot, tokyo_price_jpy_kwh AS p FROM {t:market_history} WHERE fiscal_year = @fy "
                       "ORDER BY date, slot", fy=fy)
    dates = sorted({r["date"] for r in rows})
    idx = {d: i for i, d in enumerate(dates)}
    z = [[None] * 48 for _ in dates]
    for r in rows:
        z[idx[r["date"]]][r["slot"] - 1] = r["p"]
    return {"fiscal_year": fy, "dates": dates, "slots": list(range(1, 49)), "z": z, "unit": "JPY/kWh",
            "source": src("market_history")}


@app.get("/api/market/heatmap")
def market_heatmap(fy: int = 2025):
    if fy not in (2023, 2024, 2025):
        raise HTTPException(404, "history covers FY2023-FY2025")
    return _heatmap(fy)


@lru_cache(maxsize=1)
def _duration() -> dict:
    out = {}
    for fy in (2023, 2024, 2025):
        rows = STORE.query("SELECT tokyo_price_jpy_kwh AS p FROM {t:market_history} WHERE fiscal_year = @fy "
                           "ORDER BY tokyo_price_jpy_kwh DESC", fy=fy)
        ps = [r["p"] for r in rows]
        n = len(ps)
        pts = sorted({0, n - 1, *[int(i * (n - 1) / 199) for i in range(200)]})
        out[str(fy)] = [[round(100 * i / (n - 1), 2), ps[i]] for i in pts]
    return {"series": out, "x": "% of hours exceeded", "unit": "JPY/kWh", "source": src("market_history")}


@app.get("/api/market/duration")
def market_duration():
    return _duration()


@app.get("/api/market/rm_scatter")
def market_rm_scatter(fy: int = 2025):
    rows = STORE.query("SELECT reserve_margin_pct AS rm, imbalance_price_jpy_kwh AS imb, tokyo_price_jpy_kwh AS spot "
                       "FROM {t:market_history} WHERE fiscal_year = @fy AND (reserve_margin_pct < 14 OR slot = 36)", fy=fy)
    return {"fiscal_year": fy, "points": [[r["rm"], r["imb"], r["spot"]] for r in rows],
            "curve": [[x / 2, _scar(x / 200)] for x in range(0, 31)], "unit": "reserve margin %, JPY/kWh",
            "source": src("market_history")}


def _scar(rm: float) -> float:
    from energy_lab.sim.market import scarcity_curve

    return float(scarcity_curve(rm, 200.0, 45.0))


@app.get("/api/market/monthly")
def market_monthly():
    rows = STORE.query("SELECT fiscal_year, month, ROUND(AVG(tokyo_price_jpy_kwh), 3) AS tokyo, ROUND(AVG(system_price_jpy_kwh), 3) "
                       "AS system_price, ROUND(AVG(imbalance_price_jpy_kwh), 3) AS imbalance, ROUND(AVG(fuel_index), 3) AS fuel_index "
                       "FROM {t:market_history} GROUP BY fiscal_year, month ORDER BY fiscal_year, month")
    scen = STORE.query("SELECT bank, month, ROUND(AVG(mean_price_jpy_kwh), 3) AS mean_price FROM {t:scenario_monthly} "
                       "GROUP BY bank, month ORDER BY bank, month")
    return {"history": rows, "fy2026_scenarios": scen, "source": src("market_history", "scenario_monthly")}


@app.get("/api/market/shape")
def market_shape(fy: int = 2025):
    rows = STORE.query("SELECT CASE WHEN month IN (3, 4, 5) THEN 'spring' WHEN month IN (6, 7, 8, 9) THEN 'summer' "
                       "WHEN month IN (10, 11) THEN 'autumn' ELSE 'winter' END AS season, hour, "
                       "ROUND(AVG(tokyo_price_jpy_kwh), 3) AS price FROM {t:market_history} WHERE fiscal_year = @fy "
                       "GROUP BY 1, 2 ORDER BY 1, 2", fy=fy)
    return {"fiscal_year": fy, "rows": rows, "source": src("market_history")}


@app.get("/api/calibration")
def calibration():
    rows = STORE.query("SELECT fiscal_year, metric, synthetic, target, rel_error_pct, market_facts_section, status "
                       "FROM {t:calibration} WHERE target IS NOT NULL ORDER BY fiscal_year, metric")
    return {"rows": rows, "source": src("calibration")}


@app.get("/api/portfolio")
def portfolio():
    from energy_lab.tools.lab_tools import get_portfolio_stats

    return get_portfolio_stats("")


@app.get("/api/cost_stack")
def cost_stack(voltage: str = "HV"):
    from energy_lab.tools.lab_tools import explain_cost_stack

    return explain_cost_stack(voltage)


@app.get("/api/scenarios")
def scenarios():
    rows = STORE.query("SELECT bank, regime, stress, COUNT(DISTINCT scenario) AS scenarios, ROUND(AVG(annual_mean_price_jpy_kwh), 3) "
                       "AS annual_mean, MAX(max_price_jpy_kwh) AS max_price FROM {t:scenario_monthly} GROUP BY bank, regime, stress "
                       "ORDER BY bank, regime, stress")
    return {"rows": rows, "source": src("scenario_monthly")}


# --- experiments (evidence files) ----------------------------------------------------------------------------------
def _summary(rec: dict) -> dict:
    ho = rec.get("holdout") or {}
    best = rec.get("best") or {}
    return {"run_id": rec["run_id"], "problem": rec["problem"], "status": rec.get("status"), "source": rec.get("source"),
            "evolved": bool(rec.get("evolved")), "started": rec.get("started"), "finished": rec.get("finished"),
            "programs": (rec.get("budget") or {}).get("programs_evaluated"), "valid": rec.get("valid_count"),
            "invalid": rec.get("invalid_count"), "seed_train": (rec.get("seed") or {}).get("train"),
            "best_train": best.get("train"), "holdout_seed": ho.get("seed"), "best_holdout": ho.get("best_holdout"),
            "holdout_delta": ho.get("holdout_delta"), "uplift_valid": rec.get("uplift_valid"),
            "cost_usd": (rec.get("tokens") or {}).get("cost_usd"), "stopped_reason": (rec.get("budget") or {}).get("stopped_reason")}


@app.get("/api/runs")
def runs(problem: str = ""):
    recs = [r for r in list_evidence(RUNS_DIR) if not problem or r["problem"] == problem]
    recs.sort(key=lambda r: r.get("started") or "", reverse=True)
    return {"runs": [_summary(r) for r in recs]}


def _run(run_id: str) -> dict:
    rec = load_run(run_id, RUNS_DIR)
    if not rec:
        raise HTTPException(404, f"run {run_id} not found")
    return rec


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str):
    rec = _run(run_id)
    progs = [{k: p.get(k) for k in ("idx", "id", "parent_id", "island", "model", "score", "raw_score", "valid", "kind",
                                     "descriptor", "eval_s")} | {"insight": (p.get("insights") or [{}])[0]}
             for p in rec.get("programs", [])]
    islands: dict[str, list] = {}
    for p in rec.get("programs", []):
        if p.get("score") is not None:
            islands.setdefault(str(p.get("island")), []).append({"id": p["id"], "score": p["score"], "model": p.get("model")})
    leaderboard = {k: sorted(v, key=lambda x: x["score"], reverse=True)[:5] for k, v in islands.items()}
    return {**_summary(rec), "honesty_note": rec.get("honesty_note"), "score_curve": rec.get("score_curve"),
            "programs": progs, "island_leaderboard": leaderboard, "budget": rec.get("budget"),
            "budget_policy": rec.get("budget_policy"), "tokens": rec.get("tokens"), "model_mix": rec.get("model_mix"),
            "pricing_note": rec.get("pricing_note"), "invalid_by_kind": rec.get("invalid_by_kind"),
            "baseline_lock": {k: (rec.get("baseline_lock") or {}).get(k) for k in ("reproduced", "seed_raw", "null_raw", "null_valid",
                                                                                   "seed_minus_null", "instance_sha256")},
            "search": rec.get("search"), "seed_metrics": (rec.get("seed") or {}).get("metrics"),
            "best_metrics": (rec.get("best") or {}).get("metrics")}


@app.get("/api/runs/{run_id}/diff")
def run_diff(run_id: str, program_id: str = ""):
    rec = _run(run_id)
    progs = {p["id"]: p for p in rec.get("programs", [])}
    seed = rec["programs"][0]
    pid = program_id or (rec.get("best") or {}).get("id") or seed["id"]
    if pid not in progs:
        raise HTTPException(404, "program not found")
    p = progs[pid]
    from energy_lab.harness.diff import unified

    return {"run_id": run_id, "program_id": pid, "seed_block": seed["block"], "program_block": p["block"],
            "diff_vs_seed": unified(seed["block"], p["block"], "seed", pid), "rationale": p.get("rationale"),
            "lineage": (rec.get("best") or {}).get("lineage") if pid == (rec.get("best") or {}).get("id") else None,
            "score": p.get("score"), "metrics": p.get("metrics"), "insights": p.get("insights")}


@app.get("/api/runs/{run_id}/catches")
def run_catches(run_id: str):
    rec = _run(run_id)
    rows = []
    for p in rec.get("programs", [])[1:]:
        if p.get("valid"):
            continue
        rows.append({"idx": p["idx"], "id": p["id"], "model": p.get("model"), "kind": p.get("kind"),
                     "raw_score": p.get("raw_score"),
                     "invariants": [v.get("invariant") for v in (p.get("violations") or [])],
                     "insights": (p.get("insights") or [])[:3], "rationale": (p.get("rationale") or "")[:600]})
    return {"run_id": run_id, "seed_train": (rec.get("seed") or {}).get("train"), "catches": rows,
            "by_kind": rec.get("invalid_by_kind")}


@app.get("/api/runs/{run_id}/holdout")
def run_holdout(run_id: str):
    rec = _run(run_id)
    return {"run_id": run_id, "holdout": rec.get("holdout"), "uplift_valid": rec.get("uplift_valid"),
            "uplift_note": rec.get("uplift_note")}


@app.get("/api/runs/{run_id}/gate")
def run_gate(run_id: str):
    rec = _run(run_id)
    gate = promotion_gate(rec, reviews_for(run_id, RUNS_DIR))
    gate["promotion_control"] = ("enabled" if gate["promotion_allowed"] and rec.get("source") == SOURCE_ALPHAEVOLVE else
                                 "disabled: source is not alphaevolve" if rec.get("source") != SOURCE_ALPHAEVOLVE else
                                 "disabled: checklist incomplete")
    gate["reviews"] = reviews_for(run_id, RUNS_DIR)
    return gate


@app.post("/api/runs/{run_id}/review")
def run_review(run_id: str, body: ReviewIn):
    """Executed only by the UI Hold-to-Confirm control. Appends an audit record; never promotes."""
    rec = _run(run_id)
    if rec.get("status") != "finished":
        raise HTTPException(409, "run still in progress")
    if body.program_id not in {p["id"] for p in rec.get("programs", [])}:
        raise HTTPException(404, "program not in run")
    entry = append_review(run_id, body.program_id, body.reviewer, body.note, RUNS_DIR)
    AUDIT.append({"action": "mark_human_reviewed", **entry})
    return {"status": "recorded", "review": entry, "gate": promotion_gate(rec, reviews_for(run_id, RUNS_DIR))}


@app.post("/api/runs/{run_id}/promote")
def run_promote(run_id: str):
    rec = _run(run_id)
    gate = promotion_gate(rec, reviews_for(run_id, RUNS_DIR))
    raise HTTPException(403, "promotion refused: " + "; ".join(gate["blockers"] or ["promotion is out of scope for this demo"]))


@app.get("/api/ledger")
def ledger():
    led = Ledger()
    return {"policy": BudgetPolicy.from_env().__dict__, "runs": led.all()}


@app.get("/api/overview")
def overview():
    recs = [r for r in list_evidence(RUNS_DIR, include_partial=False)]
    latest = {}
    for r in sorted(recs, key=lambda r: r.get("started") or ""):
        latest[r["problem"]] = _summary(r)
    stats = STORE.query("SELECT fiscal_year, ROUND(AVG(tokyo_price_jpy_kwh), 2) AS tokyo_mean FROM {t:market_history} "
                        "GROUP BY fiscal_year ORDER BY fiscal_year")
    port = STORE.query("SELECT COUNT(*) AS customers, ROUND(SUM(annual_mwh) / 1000000, 2) AS annual_twh FROM {t:customers_train}")
    catches = sum(sum((r.get("invalid_by_kind") or {}).values()) for r in recs)
    return {"latest_by_problem": latest, "runs": len(recs), "invalid_caught_total": catches,
            "tokyo_mean_by_fy": stats, "portfolio": port[0] if port else {}, "cost_usd_total":
            round(sum((r.get("tokens") or {}).get("cost_usd", 0) or 0 for r in recs), 2),
            "source": src("market_history", "customers_train")}


# --- chat (SSE) + HITL actions -------------------------------------------------------------------------------------
def _part_events(author: str, content: Any) -> list[dict]:
    out = []
    for p in (content.parts or []) if content else []:
        if getattr(p, "function_call", None):
            out.append({"type": "tool_call", "author": author, "tool": p.function_call.name, "args": dict(p.function_call.args or {})})
        elif getattr(p, "function_response", None):
            resp = p.function_response.response or {}
            out.append({"type": "tool_result", "author": author, "tool": p.function_response.name,
                        "result": json.loads(json.dumps(resp, default=str))})
            pa = resp.get("pending_action") if isinstance(resp, dict) else None
            if pa:
                pa = {**pa, "id": pa.get("id") or f"act-{uuid.uuid4().hex[:8]}", "status": "pending", "created": time.time(),
                      "reasoning_source": resp.get("source")}
                ACTIONS[pa["id"]] = pa
                out.append({"type": "pending_action", "author": author, "action": pa})
        elif getattr(p, "text", None):
            out.append({"type": "text", "author": author, "text": p.text})
    return out


_runner = _session_service = None


async def _local_stream(message: str, session_id: str | None) -> AsyncIterator[dict]:
    global _runner, _session_service
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from energy_lab.agent import root_agent

    if _runner is None:
        _session_service = InMemorySessionService()
        _runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)
    if not session_id or not await _session_service.get_session(app_name=APP_NAME, user_id="web", session_id=session_id):
        session_id = (await _session_service.create_session(app_name=APP_NAME, user_id="web")).id
    yield {"type": "session", "session_id": session_id}
    async for ev in _runner.run_async(user_id="web", session_id=session_id,
                                      new_message=types.Content(role="user", parts=[types.Part(text=message)])):
        for e in _part_events(ev.author, ev.content):
            yield e
        if ev.is_final_response():
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
        except Exception as exc:  # noqa: BLE001  surface, never swallow
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)[:500]})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.get("/api/actions")
def list_actions():
    return sorted(ACTIONS.values(), key=lambda a: a["created"], reverse=True)


@app.post("/api/actions/{aid}/{decision}")
def decide(aid: str, decision: str):
    if aid not in ACTIONS or decision not in ("confirm", "reject"):
        raise HTTPException(404)
    a = ACTIONS[aid]
    if a["status"] != "pending":
        raise HTTPException(409, "already decided")
    if decision == "confirm" and a.get("kind") == "mark_human_reviewed":
        d = a.get("details", {})
        rec = load_run(d.get("run_id", ""), RUNS_DIR)
        if not rec:
            raise HTTPException(404, "run not found")
        entry = append_review(d["run_id"], d["program_id"], "demo-reviewer (via analyst proposal)", d.get("note", ""), RUNS_DIR)
        a["result"] = entry
        a["status"] = "executed"
    else:
        a["status"] = "executed_sandbox" if decision == "confirm" else "rejected"
    a["decided"] = time.time()
    AUDIT.append({"action_id": aid, "decision": decision, "at": a["decided"], "summary": a.get("summary")})
    return a


@app.get("/api/audit")
def audit():
    return {"audit": AUDIT[-50:]}


from server.alpha_api import router as alpha_router  # noqa: E402  (read-only endpoints for UI version alpha)
from server.v2_api import router as v2_router  # noqa: E402  (read-only endpoints for UI version 2)

app.include_router(v2_router)
app.include_router(alpha_router)


def mount_ui(target: FastAPI, variant: str) -> None:
    """Static mounts. UI_VARIANT=alpha: ui-alpha/ at /, ui/ (version 2) at /v2/, ui/v1/ at /v1/. Otherwise unchanged:
    version 2 at / and version 1 at /v1/ (no /v2/ mount)."""
    target.mount("/v1", StaticFiles(directory=str(ROOT / "ui" / "v1"), html=True), name="ui_v1")   # version 1, unchanged
    if variant == "alpha":
        target.mount("/v2", StaticFiles(directory=str(ROOT / "ui"), html=True), name="ui_v2")
        target.mount("/", StaticFiles(directory=str(ROOT / "ui-alpha"), html=True), name="ui")
    else:
        target.mount("/", StaticFiles(directory=str(ROOT / "ui"), html=True), name="ui")          # version 2


mount_ui(app, ui_variant())
