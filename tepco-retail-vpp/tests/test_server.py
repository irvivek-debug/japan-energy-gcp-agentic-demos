"""Server: dashboard endpoints are bound to the datastore, and the HITL queue only executes on confirm."""
import pytest
from fastapi.testclient import TestClient

import server.app as srv
from retail_desk.tools import market

c = TestClient(srv.app)


@pytest.mark.parametrize("url", ["/api/health", "/api/clock", "/api/kpis", "/api/market", "/api/position", "/api/vpp/fleet?slot=35",
                                 "/api/vpp/telemetry/VPP-R-17", "/api/cfe/customers", "/api/cfe/heatmap?customer_id=C-0001&month=2026-08",
                                 "/api/scenarios", "/api/actions", "/api/audit"])
def test_endpoints_ok(url):
    assert c.get(url).status_code == 200


def test_kpis_bound_to_tools():
    k = c.get("/api/kpis").json()
    pos = market.get_balance_position("2026-08-19", 35, 38)["summary"]
    assert k["net_open_position_next4"]["value"] == pytest.approx(pos["net_open_position_open_slots_mwh"], abs=0.2)
    assert k["vpp_available"]["untrusted"] == ["VPP-R-17"]
    assert k["reserve_margin"]["min_ahead"] <= 3.2


def test_scenarios_cover_prd():
    assert [s["id"] for s in c.get("/api/scenarios").json()] == [f"S{i}" for i in range(1, 11)]


def test_hitl_queue_confirm_reject_and_overlay():
    srv.ACTIONS.clear(), srv.AUDIT.clear(), srv.OVERLAY.clear()
    r = market.propose_vpp_dispatch("2026-08-19", 35, 38)

    class Part:  # minimal stand-in for a genai function_response part
        def __init__(self, name, resp):
            self.function_call = None
            self.text = None
            self.function_response = type("FR", (), {"name": name, "response": resp})()

    content = type("C", (), {"parts": [Part("propose_vpp_dispatch", r)]})()
    evs = srv._part_events("trading_dispatch_agent", content)
    assert [e["type"] for e in evs] == ["tool_result", "pending_action"]
    aid = evs[1]["action"]["id"]
    before = c.get("/api/kpis").json()["net_open_position_next4"]["value"]
    assert c.get("/api/actions").json()[0]["status"] == "pending"
    assert c.post(f"/api/actions/{aid}/confirm").json()["status"] == "executed_sandbox"
    assert c.post(f"/api/actions/{aid}/confirm").status_code == 409
    after = c.get("/api/kpis").json()["net_open_position_next4"]["value"]
    assert after > before + 100, "confirmed sandbox dispatch closes most of the short"
    log = c.get("/api/audit").json()
    assert log[0]["action_id"] == aid and log[0]["method"] == "hold_to_confirm_2s"
    evs2 = srv._part_events("trading_dispatch_agent", content)  # re-proposal must not resurrect a decided action
    assert evs2[1]["action"]["status"] == "executed_sandbox"
    srv.ACTIONS.clear(), srv.AUDIT.clear(), srv.OVERLAY.clear()


def test_agent_import_has_no_side_effects(monkeypatch):
    import importlib
    import socket

    def boom(*a, **k):
        raise AssertionError("network access during import")

    monkeypatch.setattr(socket, "create_connection", boom)
    import retail_desk.agent as ag

    importlib.reload(ag)
    assert ag.root_agent.name == "desk_orchestrator" and len(ag.root_agent.sub_agents) == 5


# ---------------------------------------------------------------------------------- failed model calls surface as errors
def _sse_events(resp_text):
    import json as _json

    return [_json.loads(line[6:]) for line in resp_text.splitlines() if line.startswith("data: ")]


def test_failed_model_call_surfaces_as_error_not_success(monkeypatch):
    async def broken(message, session_id):
        yield {"type": "session", "session_id": "s1"}
        yield {"type": "tool_call", "author": "desk_orchestrator", "tool": "trading_dispatch_agent", "args": {}}
        raise RuntimeError("RefreshError: Reauthentication is needed. Please run `gcloud auth application-default login`")

    monkeypatch.setattr(srv, "_local_stream", broken)
    ev = _sse_events(c.post("/api/chat", json={"message": "Hedge slots 35-38"}).text)
    errs = [e for e in ev if e["type"] == "error"]
    assert errs and "no answer" in errs[-1]["error"] and "Reauthentication" in errs[-1]["error"]
    assert not [e for e in ev if e["type"] == "final"], "a failed call must never be reported as finished"
    assert not [e for e in ev if e["type"] == "text"]


def test_stream_without_an_answer_is_an_error(monkeypatch):
    async def silent(message, session_id):
        yield {"type": "session", "session_id": "s2"}
        yield {"type": "tool_call", "author": "desk_orchestrator", "tool": "get_desk_clock", "args": {}}
        yield {"type": "final", "author": "desk_orchestrator"}

    monkeypatch.setattr(srv, "_local_stream", silent)
    ev = _sse_events(c.post("/api/chat", json={"message": "x"}).text)
    assert [e["type"] for e in ev][-1] == "error" and "no answer" in ev[-1]["error"]
    assert not [e for e in ev if e["type"] == "final"]


def test_model_error_on_an_adk_event_becomes_an_error_event():
    fake = type("Ev", (), {"author": "trading_dispatch_agent", "content": None, "error_code": "UNAUTHENTICATED",
                           "error_message": "Reauthentication is needed"})()
    out = srv.adk_event_to_ui(fake)
    assert out == [{"type": "error", "author": "trading_dispatch_agent", "error": "UNAUTHENTICATED: Reauthentication is needed"}]


def test_answered_stream_passes_through(monkeypatch):
    async def ok(message, session_id):
        yield {"type": "session", "session_id": "s3"}
        yield {"type": "text", "author": "desk_orchestrator", "text": "Covered."}
        yield {"type": "final", "author": "desk_orchestrator"}

    monkeypatch.setattr(srv, "_local_stream", ok)
    ev = _sse_events(c.post("/api/chat", json={"message": "x"}).text)
    assert [e["type"] for e in ev] == ["session", "text", "final"]


def test_duplicate_cover_from_two_conversations_is_flagged_and_refused():
    """Live v2 check found it: the Agent teams page and the Handover page each raised the same hedge in separate
    conversations, and each auditor (which sees only its own conversation) passed it. The queue must say so and the
    server must refuse the approval that would cover more than the open short."""
    srv.ACTIONS.clear(), srv.AUDIT.clear(), srv.OVERLAY.clear()

    class Part:
        def __init__(self, name, resp):
            self.function_call = None
            self.text = None
            self.function_response = type("FR", (), {"name": name, "response": resp})()

    ids = []
    for conv in ("a", "b"):
        for fn in (market.propose_intraday_orders, market.propose_vpp_dispatch):
            r = fn("2026-08-19", 35, 38)
            r["pending_action"]["id"] += f"-{conv}"  # same content, different conversation
            ev = srv._part_events("trading_dispatch_agent", type("C", (), {"parts": [Part(fn.__name__, r)]})())
            ids.append(ev[-1]["action"]["id"])
    q = {a["id"]: a for a in c.get("/api/actions").json()}
    assert all(any("more than the open short" in u for u in q[i]["unsettled"]) for i in ids)
    assert any("another conversation" in u for u in q[ids[0]]["unsettled"])
    assert c.post(f"/api/actions/{ids[0]}/confirm").status_code == 200  # first set: intraday, then VPP
    assert c.post(f"/api/actions/{ids[1]}/confirm").status_code == 200
    refused = c.post(f"/api/actions/{ids[2]}/confirm")
    assert refused.status_code == 409 and "more than the open short" in refused.json()["detail"]
    assert c.get("/api/actions").json() and srv.ACTIONS[ids[2]]["status"] == "pending"
    assert len(srv.AUDIT) == 2, "a refused approval writes no audit record of an execution"
    assert c.post(f"/api/actions/{ids[2]}/reject").json()["status"] == "rejected"
    srv.ACTIONS.clear(), srv.AUDIT.clear(), srv.OVERLAY.clear()
