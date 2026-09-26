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
