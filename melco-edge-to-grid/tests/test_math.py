"""DR baseline and settlement, BESS policy mechanics, savings and gain-share arithmetic."""
import pytest

from factory_copilot.core import bess as B
from factory_copilot.core import dr_math
from factory_copilot.tools import common as C
from factory_copilot.tools import gainshare as G


def test_high_4_of_5_selects_top_four_and_adjusts():
    days = ["d5", "d4", "d3", "d2", "d1"]           # most recent first
    level = {"d5": 100, "d4": 90, "d3": 80, "d2": 120, "d1": 110}
    load = {d: {s: float(level[d]) for s in range(1, 49)} for d in days}
    net = {d: {s: float(level[d]) for s in range(1, 49)} for d in days}
    ev_day = {s: 110.0 for s in range(1, 49)}        # 10 above the selected mean of 100 in adjustment slots
    bl = dr_math.high_4_of_5_baseline(load, net, days, [34, 35], ev_day)
    assert bl["selected_days"] == sorted(["d5", "d4", "d2", "d1"])  # d3 (lowest) dropped
    assert bl["adjustment_slots"] == [28, 29, 30, 31]
    assert bl["same_day_adjustment_kw"] == pytest.approx(5.0)       # 110 - mean(100, 90, 120, 110)
    assert bl["baseline_kw"][34] == pytest.approx(110.0)


def test_settlement_penalty_and_cap():
    base = {1: 1000.0, 2: 1000.0}
    under = dr_math.settle_event(500, base, {1: 700.0, 2: 700.0}, 45, 60)
    assert under["delivered_avg_kw"] == 300 and under["shortfall_kwh"] == pytest.approx(200)
    assert under["penalty_jpy"] == 12000 and under["payment_jpy"] == 13500
    over = dr_math.settle_event(500, base, {1: 300.0, 2: 300.0}, 45, 60)
    assert over["paid_kwh"] == pytest.approx(500) and over["penalty_jpy"] == 0


def test_soc_step_and_clip():
    p = B.BessParams()
    assert B.clip_power(10.0, 1000, p) == 0.0
    assert B.clip_power(95.0, -1000, p) == 0.0
    s = 50.0
    for _ in range(20):
        s = B.soc_step(s, B.clip_power(s, 4000, p), p)
    assert s >= p.soc_min_pct - 1e-9


@pytest.fixture(scope="module")
def runs():
    di = C.day_inputs("2026-08-19")
    soc = float(C.bess_now()["soc_pct"])
    out = {}
    for pol in B.POLICIES:
        r50 = B.simulate(pol, soc, di, "p50", C.bess_params(), C.policy_params("2026-08-19"))
        r10 = B.simulate(pol, soc, di, "p10", C.bess_params(), C.policy_params("2026-08-19"))
        out[pol] = (r50, r10, B.kpis(r50, r10, di, C.bess_params()))
    return di, out


def test_forecast_aware_policy_properties(runs):
    di, out = runs
    r50, r10, k = out["forecast_aware_v2"]
    by = {r["slot"]: r for r in r50}
    assert all(by[s]["power_kw"] >= 0 for s in di.risk_slots)                  # no charging in PV-risk slots
    ceiling = C.policy_params("2026-08-19").v2_import_ceiling_kw
    assert max(r["import_after_bess_kw"] for r in r10) <= ceiling + 1           # import ceiling holds in the p10 case
    for s in di.locked_slots:                                                   # gate-closed slots stay inside 80 % of the band
        assert abs(by[s]["deviation_kw"]) <= 0.8 * by[s]["band_kw"] + 1
    assert k["soc_limit_violations"] == 0 and k["dr_firm_kw"] > 0
    assert ceiling < C.month_peak_to_date("2026-08-19")["peak_kw"]              # cannot set a new billing peak


def test_v2_beats_v1_on_dr_firmness(runs):
    _, out = runs
    assert out["forecast_aware_v2"][2]["dr_firm_kw"] > out["rule_based_v1"][2]["dr_firm_kw"]
    assert out["forecast_aware_v2"][2]["charge_in_pv_risk_slots_kwh"] <= out["rule_based_v1"][2]["charge_in_pv_risk_slots_kwh"]


def test_gain_share_invoice_arithmetic():
    g = G.compute_gain_share("2026-07")
    assert g["status"] == "ok"
    elig = sum(c["amount_jpy"] for c in g["categories"] if c["gain_share_eligible"])
    total = sum(c["amount_jpy"] for c in g["categories"])
    assert g["eligible_savings_jpy"] == pytest.approx(elig, abs=2)
    assert g["vendor_gain_share_jpy"] == pytest.approx(max(0, elig) * g["gain_share_pct"] / 100, abs=2)
    assert g["client_net_benefit_jpy"] == pytest.approx(total - g["vendor_gain_share_jpy"] - g["baas_fee_jpy"], abs=3)
    assert g["dr_reconciliation"]["reconciles"]


def test_event_savings_settled_and_estimate():
    s = G.compute_event_savings("DR-20260722")
    assert s["status"] == "settled" and s["reconciles_with_aggregator"] and s["dr_penalty_jpy"] > 0
    e = G.compute_event_savings("DR-20260819", "")
    assert e["status"] == "estimate"
    assert e["estimated_measured_delivery_avg_kw"] >= e["requested_kw"]
    parts = e["value_breakdown_jpy"]
    assert e["event_value_jpy"] == pytest.approx(sum(parts.values()), abs=3)
    assert e["vendor_gain_share_jpy"] + e["client_share_jpy"] == pytest.approx(e["event_value_jpy"], abs=2)
    assert G.compute_event_savings("DR-NOPE")["status"] == "error"
