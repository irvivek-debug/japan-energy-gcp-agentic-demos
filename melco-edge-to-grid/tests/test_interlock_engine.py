"""Edge interlock engine: every hard interlock rejects, soft limits clip, safe actions pass, totals add up."""
import json

import pytest

from factory_copilot.edge.interlock_engine import ACCEPT, LIMIT, REJECT, evaluate_plan, expand_assets, parse_plan, plan_id_for
from factory_copilot.tools import common as C

DATE = "2026-08-19"


@pytest.fixture(scope="module")
def ctx():
    return C.edge_context(DATE)


def run(ctx, actions, start="16:30", end="19:00", target=3000):
    return evaluate_plan({"date": DATE, "start": start, "end": end, "target_kw": target, "actions": actions}, ctx)


def verdicts(res):
    return {a["asset_id"]: a for a in res["actions"]}


def test_draft_plan_rejects_committed_fn02_and_meets_target(ctx):
    plan, cand, excl = C.draft_plan(DATE, "16:30", "19:00", "DR-20260819", 3000)
    res = evaluate_plan(plan, ctx)
    v = verdicts(res)
    assert v["FN-02"]["verdict"] == REJECT and "IR-FN-02" in v["FN-02"]["rule_ids"]
    assert res["summary"]["rejected"] == 1
    assert res["summary"]["firm_reduction_kw"] >= 3000 and res["summary"]["meets_target"]
    assert res["summary"]["margin_kw"] == pytest.approx(res["summary"]["firm_reduction_kw"] - 3000, abs=0.2)
    # firm reduction is the minimum over the window of the per-slot totals
    assert res["summary"]["firm_reduction_kw"] == pytest.approx(min(r["reduction_kw"] for r in res["by_slot"]), abs=0.2)
    planning_total = sum(c["planning_estimate_kw"] for c in cand)
    assert planning_total > res["summary"]["firm_reduction_kw"]  # the edge is stricter than the planning view
    assert all(e["asset_id"] != "FN-02" for e in excl)


def test_all_compressors_off_rejected_with_pressure_reason(ctx):
    res = run(ctx, [{"asset_id": "AC-*", "action": "off"}], "17:00", "18:00")
    assert len(res["actions"]) == 6
    assert all(a["verdict"] == REJECT for a in res["actions"])
    assert any("IR-CA-01" in a["rule_ids"] for a in res["actions"])
    assert any("time_to_min_pressure_s" in a for a in res["actions"])
    assert res["summary"]["firm_reduction_kw"] == 0


def test_single_compressor_isolation_breaks_n_minus_1(ctx):
    res = run(ctx, [{"asset_id": "AC-01", "action": "off"}])
    assert verdicts(res)["AC-01"]["verdict"] == REJECT and "IR-CA-02" in verdicts(res)["AC-01"]["rule_ids"]


def test_ac04_standby_is_an_efficiency_gain(ctx):
    a = verdicts(run(ctx, [{"asset_id": "AC-04", "action": "standby"}]))["AC-04"]
    assert a["verdict"] == ACCEPT and 20 < a["granted_avg_kw"] < 80


def test_header_setpoint_clipped_to_floor(ctx):
    a = verdicts(run(ctx, [{"asset_id": "COMP-HDR", "action": "pressure_setpoint", "to_mpa": 0.60}]))["COMP-HDR"]
    assert a["verdict"] == LIMIT and a["to_mpa"] == pytest.approx(0.65)


def test_cleanroom_rules(ctx):
    v = verdicts(run(ctx, [{"asset_id": "CR-AHU-01", "action": "trim"}, {"asset_id": "CR-AHU-05", "action": "trim"}]))
    assert v["CR-AHU-01"]["verdict"] == REJECT and "IR-CR-02" in v["CR-AHU-01"]["rule_ids"]
    assert v["CR-AHU-05"]["verdict"] == ACCEPT and v["CR-AHU-05"]["to_airflow_pct"] >= 88
    off = run(ctx, [{"asset_id": "CR-AHU-01..CR-AHU-06", "action": "switch off"}])
    assert len(off["actions"]) == 6 and all(a["verdict"] == REJECT and "IR-CR-01" in a["rule_ids"] for a in off["actions"])


@pytest.mark.parametrize("asset,rule", [("UPW-01", "IR-UT-01"), ("N2-01", "IR-UT-01"), ("CR-EXF-02", "IR-UT-01"), ("LN-03", "IR-LN-01")])
def test_never_curtail_loads(ctx, asset, rule):
    a = verdicts(run(ctx, [{"asset_id": asset, "action": "curtail", "kw": 100}]))[asset]
    assert a["verdict"] == REJECT and rule in a["rule_ids"] and a["granted_avg_kw"] == 0


def test_chiller_limits(ctx):
    v = verdicts(run(ctx, [{"asset_id": "CH-01", "action": "chw_setpoint", "delta_c": 3.0}]))
    assert v["CH-01"]["verdict"] == LIMIT and v["CH-01"]["delta_c"] == pytest.approx(1.5)
    assert verdicts(run(ctx, [{"asset_id": "CH-02", "action": "off"}]))["CH-02"]["verdict"] == REJECT


def test_tes_energy_limit(ctx):
    a = verdicts(run(ctx, [{"asset_id": "TES-01", "action": "tes_discharge", "kw": 3000}]))["TES-01"]
    assert a["verdict"] == LIMIT and a["granted_avg_kw"] < 3000


def test_burn_in_rules(ctx):
    v = verdicts(run(ctx, [{"asset_id": "BI-01", "action": "defer"}, {"asset_id": "BI-03", "action": "defer"}, {"asset_id": "BI-08", "action": "pause"}]))
    assert v["BI-01"]["verdict"] == REJECT and "IR-BI-01" in v["BI-01"]["rule_ids"]      # would need 5 h
    assert v["BI-03"]["verdict"] == ACCEPT and v["BI-03"]["granted_avg_kw"] > 100
    assert v["BI-08"]["verdict"] == LIMIT and v["BI-08"]["granted_avg_kw"] == 0          # its running cycle ends at 16:00
    early = verdicts(run(ctx, [{"asset_id": "BI-08", "action": "pause"}], "13:30", "15:00"))
    assert early["BI-08"]["verdict"] == REJECT and "IR-BI-02" in early["BI-08"]["rule_ids"]  # mid-cycle pause


def test_planned_uncommitted_batch_can_move_committed_cannot(ctx):
    v = verdicts(run(ctx, [{"asset_id": "FN-01", "action": "defer_batch"}, {"asset_id": "FN-02", "action": "defer_batch"}], "17:00", "19:30"))
    assert v["FN-01"]["verdict"] == ACCEPT       # 19:20 batch not committed, moves 10 min
    assert v["FN-02"]["verdict"] == REJECT and "IR-FN-02" in v["FN-02"]["rule_ids"]


def test_furnace_standby_respects_reheat_lead(ctx):
    v = verdicts(run(ctx, [{"asset_id": "FN-03", "action": "standby"}, {"asset_id": "FN-01", "action": "standby"}]))
    assert v["FN-03"]["verdict"] == ACCEPT
    assert v["FN-01"]["verdict"] == LIMIT and "IR-FN-03" in v["FN-01"]["rule_ids"]


def test_bess_limits(ctx):
    a = verdicts(run(ctx, [{"asset_id": "BESS-01", "action": "discharge", "kw": 3000}]))["BESS-01"]
    assert a["verdict"] == LIMIT and "IR-BS-01" in a["rule_ids"]       # SOC hits 10 % before 19:00
    b = verdicts(run(ctx, [{"asset_id": "BESS-01", "action": "discharge", "kw": 5000, "start": "16:30", "end": "17:00"}]))["BESS-01"]
    assert b["verdict"] == LIMIT and b["granted_avg_kw"] <= 4000
    c = verdicts(run(ctx, [{"asset_id": "BESS-01", "action": "dispatch_policy", "policy": "forecast_aware_v2"}]))["BESS-01"]
    assert c["verdict"] == ACCEPT and c["soc_min_pct"] >= 10


def test_soft_limits(ctx):
    v = verdicts(run(ctx, [{"asset_id": "LT-01", "action": "dim", "pct": 50}, {"asset_id": "OF-AHU-01", "action": "setpoint_shift", "delta_c": 4},
                          {"asset_id": "WW-01", "action": "shift", "minutes": 150}]))
    assert v["LT-01"]["verdict"] == LIMIT and v["LT-01"]["dim_pct"] == 30
    assert v["OF-AHU-01"]["verdict"] == LIMIT and v["OF-AHU-01"]["delta_c"] == pytest.approx(2.0)
    assert v["WW-01"]["verdict"] == LIMIT and v["WW-01"]["hold_min"] <= 60


def test_unknown_asset_rejected(ctx):
    res = run(ctx, [{"asset_id": "XYZ-99", "action": "off"}])
    assert res["actions"][0]["verdict"] == REJECT and res["actions"][0]["rule_ids"] == ["IR-GEN-01"]


def test_asset_expansion(ctx):
    A = C.assets()
    assert expand_assets("AC-*", A) == [f"AC-0{i}" for i in range(1, 7)]
    assert expand_assets("compressor", A) == [f"AC-0{i}" for i in range(1, 7)]
    assert expand_assets("EV-07,EV-08", A) == ["EV-07", "EV-08"]
    assert len(expand_assets("CR-AHU-01..CR-AHU-06", A)) == 6


def test_determinism_and_latency(ctx):
    plan = {"date": DATE, "start": "16:30", "end": "19:00", "actions": [{"asset_id": "AC-04", "action": "standby"}, {"asset_id": "FN-02", "action": "defer_batch"}]}
    r1, r2 = evaluate_plan(plan, ctx), evaluate_plan(json.dumps(plan), ctx)
    assert r1 == r2 and r1["plan_id"] == plan_id_for(plan)
    assert all(a["latency_ms"] < 10 for a in r1["actions"])


def test_parse_plan_rejects_garbage():
    with pytest.raises(Exception):
        parse_plan("not json")
    with pytest.raises(ValueError):
        parse_plan({"actions": []})
    assert parse_plan('[{"asset_id": "AC-04", "action": "standby"}]')["actions"][0]["asset_id"] == "AC-04"
