"""Agent wiring, tool contracts (never raise, always cite), HITL (no execute path), injection handling,
SQL portability, and the server's action queue."""
import inspect
import os
import re

import pytest

from conftest import ROOT
from factory_copilot import prompts
from factory_copilot.agent import AGENT_INVENTORY, SPECIALISTS, root_agent
from factory_copilot.core import registry
from factory_copilot.tools import bess, docs, factory, gainshare, health, market, safety

ALL_TOOLS = [t for a in SPECIALISTS for t in a.tools]
GOOD_ARGS = {
    "get_jepx_prices": {"date": "2026-08-19"}, "get_dr_events": {"date": "2026-08-19"}, "get_pv_forecast": {"date": "2026-08-19"},
    "get_deviation_exposure": {"date": "2026-08-19"}, "get_plant_load_snapshot": {"ts": "2026-08-19T13:25"},
    "get_production_schedule": {"date": "2026-08-19", "start": "16:30", "end": "19:00"},
    "list_flexible_loads": {"date": "2026-08-19", "start": "16:30", "end": "19:00"},
    "simulate_edge_interlock": {"plan_json": '{"date":"2026-08-19","start":"16:30","end":"19:00","actions":[{"asset_id":"AC-04","action":"standby"}]}'},
    "propose_load_shed_plan": None, "get_shift_handover": {"date": "2026-08-19"}, "get_bess_state": {"ts": "2026-08-19T13:30"},
    "optimize_bess_schedule": {"date": "2026-08-19", "policy": "forecast_aware_v2"}, "compare_bess_policies": {"date": "2026-08-19"},
    "propose_bess_schedule": {"date": "2026-08-19", "policy": "forecast_aware_v2", "rationale": "test"},
    "detect_energy_anomalies": {"from_date": "2026-08-13", "to_date": "2026-08-19"},
    "get_compressor_performance": {"from_date": "2026-08-13", "to_date": "2026-08-19"},
    "propose_work_order": {"asset_id": "AC-04", "issue": "leak survey", "priority": "P2", "rationale": "test"},
    "compute_event_savings": {"event_id": "DR-20260708"}, "compute_gain_share": {"month": "2026-07"},
    "get_savings_ledger": {"from_month": "2026-01", "to_month": "2026-07"}, "audit_plan": None,
    "lookup_interlock_rules": {"asset_or_class": "FN-02"}, "search_plant_documents": {"query": "furnace batch committed"},
}


def test_swarm_wiring():
    assert root_agent.name == "optimization_orchestrator"
    assert [s.name for s in root_agent.sub_agents] == ["market_intelligence_agent", "factory_interlock_agent", "bess_strategy_agent",
                                                        "asset_health_agent", "gain_share_agent", "safety_auditor"]
    assert all(s.mode == "single_turn" for s in root_agent.sub_agents)
    assert all(len(a.tools) <= 10 for a in SPECIALISTS)
    assert {x["agent_id"] for x in AGENT_INVENTORY} == {root_agent.name} | {s.name for s in SPECIALISTS}


def test_preamble_reaches_every_agent():
    for a in [root_agent] + SPECIALISTS:
        assert a.instruction.startswith(prompts.PREAMBLE)
        assert "2026-08-19" in a.instruction and "never the project" in a.instruction


def test_no_execute_tool_anywhere():
    names = [t.__name__ for t in ALL_TOOLS]
    assert not [n for n in names if n.startswith("execute") or "execute_" in n]
    for t in ALL_TOOLS:
        if t.__name__.startswith("propose_"):
            assert "Hold-to-Confirm" in inspect.getdoc(t), t.__name__


def test_tools_have_typed_args_and_docstrings():
    for t in ALL_TOOLS:
        sig = inspect.signature(t)
        doc = inspect.getdoc(t) or ""
        assert "Args:" in doc, t.__name__
        for p in sig.parameters.values():
            assert p.annotation is not inspect._empty, (t.__name__, p.name)


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.__name__)
def test_tool_contract_ok_and_cited(tool):
    args = GOOD_ARGS[tool.__name__]
    if args is None:
        fl = factory.list_flexible_loads("2026-08-19", "16:30", "19:00")
        pid = factory.simulate_edge_interlock(fl["draft_plan_json"])["plan_id"]
        args = {"plan_id": pid, "rationale": "test"} if tool.__name__ == "propose_load_shed_plan" else {"plan_id": pid}
    r = tool(**args)
    assert isinstance(r, dict) and r.get("status") in ("ok", "pending_approval", "estimate", "settled"), r
    assert r.get("source"), tool.__name__


@pytest.mark.parametrize("tool", ALL_TOOLS, ids=lambda t: t.__name__)
def test_tool_never_raises_on_garbage(tool):
    garbage = {p: "garbage" for p in inspect.signature(tool).parameters}
    r = tool(**garbage)
    assert isinstance(r, dict) and "status" in r


def test_proposals_are_pending_only():
    fl = factory.list_flexible_loads("2026-08-19", "16:30", "19:00")
    sim = factory.simulate_edge_interlock(fl["draft_plan_json"])
    p = factory.propose_load_shed_plan(sim["plan_id"], "test", "DR-20260819")
    assert p["status"] == "pending_approval" and p["pending_action"]["requires"] == "hold_to_confirm"
    assert all(a["verdict"] != "REJECT" for a in p["pending_action"]["details"]["actions"])
    assert [x["asset_id"] for x in p["pending_action"]["details"]["excluded_by_edge"]] == ["FN-02"]
    assert factory.propose_load_shed_plan("PLAN-NOPE", "x")["status"] == "error"
    for q in (bess.propose_bess_schedule("2026-08-19", "forecast_aware_v2", "t"), health.propose_work_order("AC-04", "x", "P1", "t")):
        assert q["status"] == "pending_approval" and q["pending_action"]["requires"] == "hold_to_confirm"


def test_rejected_only_plan_cannot_be_proposed():
    sim = factory.simulate_edge_interlock('{"date":"2026-08-19","start":"17:00","end":"18:00","actions":[{"asset_id":"AC-*","action":"off"}]}')
    assert sim["summary"]["rejected"] == 6
    assert factory.propose_load_shed_plan(sim["plan_id"], "x")["status"] == "error"


def test_audit_requires_edge_simulation():
    registry.reset()
    assert safety.audit_plan("PLAN-NONE")["verdict"] == "BLOCKED"
    fl = factory.list_flexible_loads("2026-08-19", "16:30", "19:00")
    sim = factory.simulate_edge_interlock(fl["draft_plan_json"])
    a = safety.audit_plan(sim["plan_id"])
    assert a["verdict"] == "APPROVED" and {f["check"] for f in a["findings"]} >= {"edge_simulation", "human_in_the_loop", "never_curtail_loads"}


def test_injection_is_flagged_as_data():
    h = docs.get_shift_handover("2026-08-19")
    assert h["security"]["suspected_prompt_injection"]
    assert "[shift_handover_2026-08-19.md Section 6]" in h["security"]["flagged_sections"]
    clean = docs.search_plant_documents("same-day adjustment")
    assert clean["results"][0]["citation"].startswith("[dr_contract_summary.md Section")
    assert not clean["results"][0]["security"]["suspected_prompt_injection"]


def test_sql_is_portable():
    banned = re.compile(r"\b(DATE_ADD|DATE_SUB|DATE_TRUNC|TIMESTAMP_\w+|QUALIFY|ARRAY_AGG|STRUCT|EXTRACT|STRFTIME|INTERVAL)\b", re.I)
    for mod in (market, factory, bess, health, gainshare, safety):
        src = inspect.getsource(mod)
        for sql in re.findall(r'"((?:SELECT|WITH)[^"]*)"', src):
            assert not banned.search(sql), sql
    common_src = open(os.path.join(ROOT, "factory_copilot", "tools", "common.py")).read()
    assert not banned.search(" ".join(re.findall(r'"((?:SELECT|WITH)[^"]*)"', common_src)))


def test_server_endpoints_and_hitl_queue():
    from fastapi.testclient import TestClient
    from server import app as srv
    c = TestClient(srv.app)
    for ep in ("/api/health", "/api/overview", "/api/load-stack", "/api/flex", "/api/bess", "/api/pv", "/api/jepx", "/api/anomalies",
               "/api/gain-share?month=2026-07", "/api/edge-decisions", "/api/dr-events", "/api/suggested-prompts"):
        assert c.get(ep).status_code == 200, ep
    ov = c.get("/api/overview").json()["kpis"]
    assert ov["dr"]["firm_kw"] >= ov["dr"]["target_kw"] and ov["dr"]["rejected"] == 1
    # lift a pending action out of a tool result exactly as the SSE stream does
    fl = factory.list_flexible_loads("2026-08-19", "16:30", "19:00")
    sim = factory.simulate_edge_interlock(fl["draft_plan_json"])
    resp = factory.propose_load_shed_plan(sim["plan_id"], "test", "DR-20260819")

    class P:
        function_call = None
        text = None

        class function_response:
            name = "propose_load_shed_plan"
    P.function_response.response = resp

    class Content:
        parts = [P]
    evs = srv._part_events("factory_interlock_agent", Content)
    pa = [e for e in evs if e["type"] == "pending_action"][0]["action"]
    assert c.get("/api/actions").json()[0]["status"] == "pending"
    r = c.post(f"/api/actions/{pa['id']}/confirm").json()
    assert r["status"] == "executed_sandbox"
    audit = c.get("/api/audit").json()[0]
    assert audit["edge_recheck"]["rejected"] == 0 and audit["decision"] == "confirm"
    assert c.post(f"/api/actions/{pa['id']}/reject").status_code == 409


def test_final_answer_safety_net():
    """If the orchestrator ends a turn without its own text, the specialists' grounded results become the answer."""
    from google.genai import types
    from factory_copilot import agent as A

    class Ev:
        def __init__(self, author, parts, inv="inv-1"):
            self.author, self.invocation_id = author, inv
            self.content = types.Content(role="model", parts=parts)

    fr = types.Part(function_response=types.FunctionResponse(name="market_intelligence_agent", response={"result": "PV p10 212.5 kW [ds.pv_forecast_30min]"}))

    class Ctx:
        invocation_id = "inv-1"
        session = type("S", (), {"events": [Ev("optimization_orchestrator", [fr])]})()

    out = A.ensure_final_answer(Ctx())
    assert "212.5 kW" in out.parts[0].text and "Nothing has been executed" in out.parts[0].text
    Ctx.session.events.append(Ev("optimization_orchestrator", [types.Part(text="Final answer")]))
    assert A.ensure_final_answer(Ctx()) is None
