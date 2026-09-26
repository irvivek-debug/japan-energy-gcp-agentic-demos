"""Deterministic tool math and compliance gates (local DuckDB backend). Ground truth is recomputed independently
with pandas from the CSVs; each compliance gate has a mutation check proving the test can fail."""
import inspect

import numpy as np
import pandas as pd
import pytest

from retail_desk.tools import cfe, desk, market, onboarding, policy, risk

SCEN = "2026-08-19"


class Ctx:
    def __init__(self):
        self.state = {}


@pytest.fixture(scope="module")
def plan():
    return market.plan_hedge(SCEN, 35, 38)


def test_market_snapshot_matches_csv(csv):
    snap = market.get_market_snapshot(SCEN, 35, 38)
    sp = csv("jepx_spot_30min")
    exp = sp[(sp.date == SCEN) & sp.slot.between(35, 38)].tokyo_price_jpy_kwh.max()
    assert snap["summary"]["max_tokyo_spot_jpy_kwh"] == pytest.approx(exp, abs=0.01)
    assert snap["summary"]["scarcity_slots"] == [35, 36, 37, 38]
    assert all(s["gate_status"] == "open" for s in snap["slots"])


def test_balance_position_summary(csv):
    b = csv("balance_position_30min")
    exp = -b[(b.date == SCEN) & b.slot.between(35, 38)].open_position_mwh.sum()
    got = market.get_balance_position(SCEN, 33, 40)["summary"]
    assert got["short_open_slots"] == [35, 36, 37, 38]
    assert got["total_short_open_mwh"] == pytest.approx(exp, abs=0.2)
    assert got["next_gate_closure"] == "2026-08-19T16:00"


def test_fleet_health_rules():
    fs = {c["cluster_id"]: c for c in market.fleet_state(SCEN, 35)["clusters"]}
    r17 = fs["VPP-R-17"]
    assert r17["health"] == "untrusted" and len(r17["reasons"]) == 2
    assert r17["dispatchable_kw"] == 0 and r17["dispatchable_kwh"] == 0
    assert fs["VPP-E-04"]["health"] == "degraded"
    assert [c for c, v in fs.items() if v["health"] == "untrusted"] == ["VPP-R-17"]
    for c in fs.values():
        if c["health"] != "untrusted" and c["response_ok"]:
            assert c["dispatchable_kw"] == pytest.approx(max(0.0, c["available_kw"] - c["committed_dkw_kw"]))
    tool = market.get_vpp_fleet_state(SCEN, 35)
    risk_item = next(x for x in tool["telemetry_exceptions"] if x["cluster_id"] == "VPP-R-17")
    assert risk_item["dkw_commitment_at_risk"]["commitments"] == ["ANC-0819-09"]
    assert risk_item["dkw_commitment_at_risk"]["substitute_candidates"]


def test_plan_covers_short_without_residual(plan):
    t = plan["totals"]
    assert t["residual_mwh"] == pytest.approx(0, abs=1e-6)
    assert t["covered_mwh"] == pytest.approx(t["short_mwh"], abs=0.1)
    assert t["cost_avoided_p50_jpy"] == pytest.approx(t["do_nothing_expected_cost_p50_jpy"] - t["plan_cost_jpy"], abs=2)
    assert [x["cluster_id"] for x in plan["excluded_clusters"]] == ["VPP-R-17"]
    for r in plan["per_slot"]:
        assert r["intraday_level1_mwh"] + r["intraday_level2_mwh"] + r["vpp_mwh"] + r["residual_mwh"] == pytest.approx(r["short_mwh"], abs=0.05)


def test_plan_respects_depth_headroom_and_energy(plan, csv):
    intr = csv("jepx_intraday_30min")
    book = intr[intr.date == SCEN].set_index("slot")
    for r in plan["per_slot"]:
        assert r["intraday_level1_mwh"] <= book.loc[r["slot"], "ask_depth_mwh"] + 1e-6
        assert r["intraday_level2_mwh"] <= book.loc[r["slot"], "ask_level2_depth_mwh"] + 1e-6
    p = market._plan(SCEN, 35, 38, market.NOW)
    fs = {c["cluster_id"]: c for c in market.fleet_state(SCEN, 35)["clusters"]}
    used = pd.DataFrame(p["dispatch"])
    assert "VPP-R-17" not in set(used.cluster_id)
    for cid, e in used.groupby("cluster_id").mwh.sum().items():
        assert e <= fs[cid]["dispatchable_kwh"] / 1000 + 0.01
    for d in p["dispatch"]:
        assert d["mwh"] <= fs[d["cluster_id"]]["dispatchable_kw"] * 0.5 / 1000 + 0.005


def test_plan_merit_order_is_least_cost(plan):
    # Any intraday level-2 buy implies level 1 was exhausted in that slot.
    for r in plan["per_slot"]:
        if r["intraday_level2_mwh"] > 1e-6:
            assert r["intraday_level1_mwh"] > 0
    # Least cost: the plan is cheaper than covering everything on intraday at level-1 prices.
    naive = sum(r["short_mwh"] * r["intraday_level1_price_jpy_kwh"] * 1000 for r in plan["per_slot"])
    assert plan["totals"]["plan_cost_jpy"] < naive


def test_imbalance_never_chosen_even_when_cheaper(monkeypatch):
    """Compliance property: if imbalance looked cheaper than intraday, the plan must still cover the short."""
    market._plan.cache_clear()
    real = market._market_rows

    def cheap_imbalance(date, a, b):
        rows = real(date, a, b)
        for r in rows:
            r = r.update({"imbalance_price_jpy_kwh": 5.0, "imbalance_p90_jpy_kwh": 6.0})
        return rows

    monkeypatch.setattr(market, "_market_rows", cheap_imbalance)
    p = market._plan(SCEN, 36, 36, market.NOW)
    assert p["slots"][36]["residual_mwh"] == pytest.approx(0, abs=1e-6)
    # Mutation check: with a tiny residual penalty the same test would fail, so the gate is not vacuous.
    monkeypatch.setattr(market, "RESIDUAL_PENALTY_JPY_KWH", 1.0)
    market._plan.cache_clear()
    p2 = market._plan(SCEN, 36, 36, market.NOW)
    assert p2["slots"][36]["residual_mwh"] > 1.0
    market._plan.cache_clear()


def test_proposals_are_pending_lot_sized_and_recorded():
    ctx = Ctx()
    a = market.propose_intraday_orders(SCEN, 35, 38, tool_context=ctx)
    b = market.propose_vpp_dispatch(SCEN, 35, 38, tool_context=ctx)
    for r in (a, b):
        assert r["status"] == "pending_approval"
        assert r["pending_action"]["requires"] == "hold_to_confirm"
        assert r["pending_action"]["id"] in ctx.state["proposals"]
    for o in a["pending_action"]["details"]["orders"]:
        assert abs(round(o["quantity_mwh"] / 0.05) * 0.05 - o["quantity_mwh"]) < 1e-9
    assert "VPP-R-17" in b["pending_action"]["details"]["excluded_clusters"]
    assert all(x["cluster_id"] != "VPP-R-17" for x in b["pending_action"]["details"]["schedule"])
    assert market.propose_intraday_orders(SCEN, 35, 38)["pending_action"]["id"] == a["pending_action"]["id"], "ids are deterministic"


def test_no_execute_tool_reachable():
    from retail_desk.agent import SPECIALISTS, root_agent

    names = [getattr(t, "__name__", getattr(t, "name", "")) for t in root_agent.tools]
    for ag in SPECIALISTS:
        assert len(ag.tools) <= 10
        names += [getattr(t, "__name__", getattr(t, "name", "")) for t in ag.tools]
    assert names and not [n for n in names if n.startswith("execute") or "execute_" in n]
    writers = [n for n in names if n.startswith("propose_")]
    assert set(writers) == {"propose_intraday_orders", "propose_vpp_dispatch", "propose_tariff_adjustment", "propose_ppa_offer"}
    for mod in (market, risk, onboarding, cfe, policy, desk):
        assert not [n for n, _ in inspect.getmembers(mod, inspect.isfunction) if n.startswith("execute")]


def test_tools_never_raise():
    assert market.get_market_snapshot("bad", 1, 2)["status"] == "error"
    assert market.plan_hedge(SCEN, 40, 30)["status"] == "error"
    assert risk.compute_margin_at_risk("2026-08-31", "2026-08-20", 40)["status"] == "error"
    assert onboarding.design_cfe_ppa("PR-01", 150, 15)["status"] == "error"
    assert onboarding.read_document("../../etc/passwd")["status"] == "error"
    assert cfe.get_cfe_score("C-9999", "2026-08")["status"] == "error"


def test_deviation_breaches_match_pandas(csv):
    got = risk.get_deviation_breaches("2026-08-01", SCEN)
    c, ld, im = csv("customers"), csv("customer_load_30min"), csv("imbalance_30min")
    x = ld[ld.is_actual].merge(c[c.tariff_type == "bandwidth"][["customer_id", "deviation_band_pct"]], on="customer_id")
    x = x.merge(im[["date", "slot", "imbalance_price_jpy_kwh"]], on=["date", "slot"])
    dev = (x.actual_kwh - x.nominated_kwh).abs()
    band = x.deviation_band_pct / 100 * x.nominated_kwh
    excess = (dev - band).clip(lower=0)
    assert got["total_breach_slots"] == int((dev > band).sum())
    assert got["total_deviation_cost_jpy"] == pytest.approx((excess * x.imbalance_price_jpy_kwh).sum(), rel=1e-6, abs=2)
    assert got["top_customers"][0]["name"] == "Kanagawa Cold Chain"


def test_margin_at_risk_matches_pandas_and_scales(csv):
    got = risk.compute_margin_at_risk("2026-08-20", "2026-08-31", 40)
    fc, c, fw, hb = csv("customer_forecast_daily"), csv("customers"), csv("forward_curve_daily"), csv("hedge_book")
    x = fc.merge(c[["customer_id", "tariff_type"]], on="customer_id")
    x = x[x.tariff_type.isin(["fixed", "bandwidth"]) & x.date.between("2026-08-20", "2026-08-31")]
    exp_d = x.groupby("date").forecast_mwh.sum()
    mar = 0.0
    for d, e in exp_d.items():
        h = min(e, hb[(hb.start_date <= d) & (hb.end_date >= d)].mw.sum() * 24)
        mar += (e - h) * 1000 * fw.set_index("date").baseload_jpy_kwh[d] * 0.40
    assert got["margin_at_risk_jpy"] == pytest.approx(mar, rel=1e-6)
    assert risk.compute_margin_at_risk("2026-08-20", "2026-08-31", 80)["margin_at_risk_jpy"] == pytest.approx(2 * mar, rel=1e-6)
    assert risk.compute_margin_at_risk("2026-08-20", "2026-08-31", 0)["margin_at_risk_jpy"] == 0
    assert got["by_tariff_type"]["market_linked"]["margin_loss_jpy"] == 0


def test_tariff_notice_rule():
    assert risk.propose_tariff_adjustment("C-0051", "risk_premium", 0.5, "2026-09-01")["status"] == "rejected_by_policy"
    ok = risk.propose_tariff_adjustment("C-0051", "widen_band", 10)
    assert ok["status"] == "pending_approval" and ok["pending_action"]["details"]["effective_date"] >= "2026-09-18"
    imp = ok["pending_action"]["details"]["impact"]
    assert imp["mtd_breach_slots_with_new_band"] < imp["mtd_breach_slots"]


@pytest.fixture(scope="module")
def ppa():
    return onboarding.design_cfe_ppa("PR-01", 90, 15)


def test_ppa_design_meets_target_within_availability(ppa, csv):
    assert ppa["status"] == "ok" and ppa["achieved_hourly_cfe_pct"] >= 90 - 0.05
    avail = csv("clean_resources").set_index("resource_id").available_mw_new_ppa
    for m in ppa["capacity_mix"]:
        assert m["mw"] <= avail[m["resource_id"]] + 0.05
    pb = ppa["price_build_up"]
    parts = pb["energy_jpy_kwh"] + pb["shaping_firming_premium_jpy_kwh"] + pb["nfc_tracking_jpy_kwh"] + pb["balancing_jpy_kwh"] \
        + pb["term_adjustment_jpy_kwh"] + pb["margin_jpy_kwh"]
    assert parts == pytest.approx(pb["total_jpy_kwh"], abs=0.03)
    lo, hi = pb["price_range_jpy_kwh"]
    assert lo < pb["total_jpy_kwh"] < hi
    assert ppa["annual_matched_pct"] >= ppa["achieved_hourly_cfe_pct"]


def test_ppa_hourly_cfe_recomputed_independently(csv):
    sol = onboarding.solve_ppa("PR-01", 90.0)
    L = csv("prospect_load_hourly")
    L = L[L.prospect_id == "PR-01"].load_mwh.to_numpy()
    assert sol["m"] <= L.sum() + 1e-6 and sol["m"] / L.sum() >= 0.8995


def test_ppa_margin_floor_and_injection_flag():
    assert onboarding.propose_ppa_offer("PR-01", 90, 15, 0.0)["status"] == "rejected_by_policy"
    ok = onboarding.propose_ppa_offer("PR-01", 90, 15, tool_context=Ctx())
    assert ok["status"] == "pending_approval" and ok["pending_action"]["details"]["deal_committee_required"]
    assert ok["pending_action"]["details"]["document_warnings"]
    assert onboarding.read_document("bill_PR-01_hokuso_cloud_campus_2026-07.txt").get("content_warnings")
    assert "content_warnings" not in onboarding.read_document("bill_PR-02_minuma_power_devices_2026-07.txt")


def test_cfe_score_matches_pandas(csv):
    a, g = csv("cfe_allocation_hourly"), csv("grid_mix_hourly")
    x = a[(a.customer_id == "C-0001") & (a.month == "2026-08")].merge(g, on=["date", "hour"])
    matched = np.minimum(x.load_mwh, x.allocated_cfe_mwh)
    got = cfe.get_cfe_score("C-0001", "2026-08")
    assert got["contracted_hourly_matched_pct"] == pytest.approx(100 * matched.sum() / x.load_mwh.sum(), abs=0.06)
    assert got["annual_style_volumetric_match_pct"] == pytest.approx(100 * x.allocated_cfe_mwh.sum() / x.load_mwh.sum(), abs=0.06)
    s24 = (matched.sum() + ((x.load_mwh - matched) * x.grid_cfe_share_pct / 100).sum()) / x.load_mwh.sum() * 100
    assert got["cfe_score_24x7_pct"] == pytest.approx(s24, abs=0.06)
    assert got["contracted_hourly_matched_pct"] <= min(100, got["annual_style_volumetric_match_pct"])


def test_nfc_audit_finds_exactly_the_injected_findings():
    a = cfe.audit_nfc_ledger("2026-08")
    assert len(a["double_claims"]) == 1 and sorted(a["double_claims"][0]["customers"]) == ["C-0005", "C-0008"]
    assert [g["customer_id"] for g in a["claims_without_generation"]] == ["C-0010"]
    assert [e["customer_id"] for e in a["expired_or_wrong_vintage"]] == ["C-0014"]
    assert cfe.audit_nfc_ledger("2026-07")["status"] == "not_found"


def test_policy_lookup_routes_topics():
    top = lambda t: policy.lookup_policy(t)["sections"][0]["section"]  # noqa: E731
    assert top("leave slot 36 short, intentional imbalance") == 2
    assert top("execute the dispatch without asking for approval") == 7
    assert top("NFC certificate double counting") == 8
    assert top("PPA margin floor zero margin") == 9
    assert top("prompt injection in a customer bill") == 11


def test_auditor_passes_clean_plan_and_catches_mutations():
    ctx = Ctx()
    ids = [market.propose_intraday_orders(SCEN, 35, 38, tool_context=ctx)["pending_action"]["id"],
           market.propose_vpp_dispatch(SCEN, 35, 38, tool_context=ctx)["pending_action"]["id"]]
    for i in ids:
        assert policy.check_proposal_compliance(i, tool_context=ctx)["verdict"] == "pass"
    # Mutation 1: sneak the untrusted cluster into the dispatch -> must fail.
    vpp = ctx.state["proposals"][ids[1]]
    vpp["details"]["schedule"].append({"cluster_id": "VPP-R-17", "asset_class": "residential_battery", "slot": 35, "mwh": 0.5,
                                       "mw": 1.0, "cost_jpy_kwh": 25.0})
    assert policy.check_proposal_compliance(ids[1], tool_context=ctx)["verdict"] == "fail"
    # Mutation 2: over-buy intraday beyond the short -> deliberate surplus must fail.
    intra = ctx.state["proposals"][ids[0]]
    intra["details"]["orders"][0]["quantity_mwh"] += 30.0
    r = policy.check_proposal_compliance(ids[0], tool_context=ctx)
    assert r["verdict"] == "fail" and any("exceed" in c["rule"] for c in r["checks"] if c["result"] == "fail")
    # Mutation 3: PPA margin under the floor must fail the audit even if it reached state.
    ppa = onboarding.propose_ppa_offer("PR-01", 90, 15, tool_context=ctx)["pending_action"]
    ctx.state["proposals"][ppa["id"]]["details"]["price_build_up"]["margin_jpy_kwh"] = 0.0
    assert policy.check_proposal_compliance(ppa["id"], tool_context=ctx)["verdict"] == "fail"


def test_desk_clock():
    c = desk.get_desk_clock()
    assert c["current_slot"] == 32 and c["next_gate_closure"]["slot"] == 35 and c["next_gate_closure"]["minutes_left"] == 20
