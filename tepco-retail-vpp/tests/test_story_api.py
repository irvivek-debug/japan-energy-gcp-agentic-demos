"""Read-only v2 endpoints: every figure agrees with the tools or result files it claims to come from."""
import json
import os

import pytest
import yaml
from fastapi.testclient import TestClient

import server.app as srv
from conftest import ROOT
from retail_desk import catalog
from retail_desk.tools import market, risk

c = TestClient(srv.app)
D = "2026-08-19"


@pytest.fixture(scope="module")
def plan():
    return market.plan_hedge(D, 35, 38)["totals"]


@pytest.mark.parametrize("path", ["facts", "gap", "evidence", "prize", "proof", "value", "case", "plan", "provenance", "limits"])
def test_story_endpoints_ok(path):
    assert c.get(f"/api/story/{path}").status_code == 200


def test_facts_and_gap_match_the_plan(plan):
    f = c.get("/api/story/facts").json()
    assert f["short_mwh"] == plan["short_mwh"] and f["avoided_p50_jpy"] == plan["cost_avoided_p50_jpy"]
    rows = {r["id"]: r for r in c.get("/api/story/gap").json()["rows"]}
    assert set(rows) == {"short", "price", "vpp", "cfe", "margin"}
    assert rows["short"]["ordinary"]["value"] == plan["short_mwh"] and rows["short"]["best"]["value"] == plan["residual_mwh"]
    assert rows["price"]["best"]["value"] == plan["average_cover_price_jpy_kwh"]
    assert rows["margin"]["best"]["value"] is None, "no hedge target is held, so the cell must be NOT IN THE DATA"
    for r in rows.values():
        assert r["research"]["cite"] and "MARKET_FACTS" in r["research"]["ref"]


def test_evidence_window_and_series():
    ev = c.get("/api/story/evidence").json()
    n = ev["window"]["points"]
    assert n == 96 and ev["window"]["labels"][ev["window"]["now_index"]].endswith("15:30")
    for card in ev["cards"]:
        assert len(card["values"]) == n and card["source"]
    frozen = next(x for x in ev["cards"] if x["id"] == "frozen")["values"]
    i = ev["window"]["now_index"]
    assert len(set(frozen[i - 11:i + 1])) == 1, "the untrusted pool's reported charge is flat"
    assert all(v is None for v in next(x for x in ev["cards"] if x["id"] == "soc")["values"][i + 1:]), "no telemetry after now"


def test_prize_ranges_follow_their_basis(plan):
    b = {x["code"]: x for x in c.get("/api/story/prize").json()["branches"]}
    assert [x.get("code") for x in catalog.BRANCHES] == list(b)
    assert b["A"]["low"] == pytest.approx(plan["cost_avoided_p50_jpy"] * 10) and b["A"]["high"] == pytest.approx(plan["cost_avoided_p90_jpy"] * 25)
    mar = risk.compute_margin_at_risk("2026-08-20", "2026-08-31", 40)["margin_at_risk_jpy"]
    assert b["C"]["low"] == pytest.approx(mar * 0.3) and b["C"]["high"] == pytest.approx(mar * 0.6)
    assert b["E"]["low"] is None and b["E"]["unit"] == "not priced"
    for x in b.values():
        assert x["mechanism"] and x["assumption"] and x["apqc"]


def test_proof_denominators_match_result_files():
    p = c.get("/api/story/proof").json()
    res = os.path.join(ROOT, "eval", "results")
    adk = json.load(open(os.path.join(res, "adk_summary.json")))
    s = {x["id"]: x for x in p["suites"]}
    assert s["adk"]["total"] == sum(v["total"] for v in adk.values())
    assert s["adk"]["first"] == sum(v["passed_first_attempt"] for v in adk.values())
    gr = json.load(open(os.path.join(res, "grounding_results.json")))["summary"]
    assert (s["grounding"]["first"], s["grounding"]["total"]) == (gr["grounded_first_attempt"], gr["total"])
    assert p["worked_example"]["scenario"] == "S1" and p["worked_example"]["truth_method"].startswith("def truth_short")
    assert len(p["cases"]) == sum(x["total"] for x in p["suites"])


def test_value_metrics_have_band_or_honest_label():
    for m in c.get("/api/story/value").json()["metrics"]:
        assert m["band"] is not None or m["band_label"] == "NO VERIFIED BENCHMARK HELD"
        if m["band"]:
            assert m["cite"]
        assert m["moved_by"] in {a["name"] for a in catalog.AGENTS}


def test_agents_catalog_matches_the_running_team():
    from retail_desk.agent import SPECIALISTS, root_agent

    a = c.get("/api/agents").json()
    assert {x["name"] for x in a["agents"]} == {root_agent.name, *[s.name for s in SPECIALISTS]}
    assert not [t for x in a["agents"] for t in x["tools"] if "execute" in t]
    assert a["sign_off_count"] == sum(1 for x in a["agents"] if x["proposes"])
    assert a["limits"]


def test_personas_are_the_prd_roles_with_live_figures():
    ps = c.get("/api/personas").json()["personas"]
    ids = {s["id"] for s in srv.SCENARIOS}
    assert [p["id"] for p in ps] == ["trader", "risk", "account", "vpp"]
    for p in ps:
        assert p["answerable_for"] and all(m["source"] for m in p["answerable_for"])
        assert {s["id"] for s in p["suggested"]} <= ids and p["agents"]


def test_provenance_reports_the_generator_seed():
    p = c.get("/api/story/provenance").json()
    seed = yaml.safe_load(open(os.path.join(ROOT, "data", "simulation_parameters.yaml")))["seed"]
    assert p["seed"] == seed and p["rows"] > 0 and len(p["tables"]) == 20


def test_case_october_curve_is_steeper():
    o = c.get("/api/story/case").json()["october"]
    assert o["do_nothing_october_jpy"] > o["do_nothing_now_jpy"] > 0
    assert all(s["imbalance_october_jpy_kwh"] >= s["imbalance_now_jpy_kwh"] for s in o["slots"])


def test_actions_carry_what_they_could_not_settle():
    srv.ACTIONS.clear()
    r = market.propose_vpp_dispatch(D, 35, 38)
    srv.ACTIONS[r["pending_action"]["id"]] = {**r["pending_action"], "status": "pending", "created": 0}
    a = c.get("/api/actions").json()[0]
    text = " ".join(a["unsettled"])
    assert "Not yet reviewed" in text and "VPP-R-17" in text and "ANC-0819-09" in text
    srv.ACTIONS.clear()
