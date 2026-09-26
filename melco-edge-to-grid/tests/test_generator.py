"""Generator properties: structure, determinism, mandatory anomalies, physical and market invariants.

Properties, not pinned literals: counts derive from the config, anomalies are asserted by their signature,
market figures are checked against the MARKET_FACTS ranges they were calibrated to.
"""
import datetime as dt
import hashlib
import json
import os
import re

import pandas as pd
import pytest
import yaml

from conftest import ROOT

OUT = os.path.join(ROOT, "data", "out")
P = yaml.safe_load(open(os.path.join(ROOT, "data", "simulation_parameters.yaml")))
SCHEMA = json.load(open(os.path.join(ROOT, "data", "schema.json")))["tables"]


def load(name):
    types = {c["name"]: c["type"] for c in SCHEMA[name]["columns"]}
    df = pd.read_csv(os.path.join(OUT, f"{name}.csv"), keep_default_na=False, na_values=[""])
    for c, t in types.items():
        if t == "STRING":
            df[c] = df[c].fillna("").astype(str)
    return df


def test_schema_copies_identical():
    assert open(os.path.join(ROOT, "data", "schema.json")).read() == open(os.path.join(ROOT, "factory_copilot", "schema.json")).read()


@pytest.mark.parametrize("name", sorted(SCHEMA))
def test_every_table_matches_schema(name):
    df = pd.read_csv(os.path.join(OUT, f"{name}.csv"), nrows=200)
    assert list(df.columns) == [c["name"] for c in SCHEMA[name]["columns"]]
    assert set(c["type"] for c in SCHEMA[name]["columns"]) <= {"STRING", "INT64", "FLOAT64", "BOOL"}
    assert len(df) > 0


def test_total_size_under_40mb():
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT) if f.endswith(".csv"))
    assert total < 40e6


def test_generator_is_deterministic(tmp_path):
    import importlib.util
    spec = importlib.util.spec_from_file_location("gen", os.path.join(ROOT, "data", "generate.py"))
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    gen.main(out_dir=str(tmp_path), schema_targets=[str(tmp_path / "schema.json")])
    for f in ("site_load_30min.csv", "dr_events.csv", "compressor_perf.csv", "jepx_prices_30min.csv", "savings_ledger.csv"):
        a = hashlib.sha256(open(os.path.join(OUT, f), "rb").read()).hexdigest()
        b = hashlib.sha256(open(tmp_path / f, "rb").read()).hexdigest()
        assert a == b, f"{f} differs between runs"


def test_row_counts_derive_from_config():
    meters = load("meters")
    tel = load("telemetry_5min")
    start = dt.datetime.fromisoformat(P["periods"]["telemetry_start"] + "T00:00")
    now = dt.datetime.fromisoformat(P["demo_now"])
    intervals = int((now - start).total_seconds() // 300)
    assert len(tel) == len(meters) * intervals
    site = load("site_load_30min")
    days = (now.date() - dt.date.fromisoformat(P["periods"]["site_history_start"])).days
    now_slot = now.hour * 2 + now.minute // 30 + 1
    assert len(site) == days * 48 + (now_slot - 1)
    assert tel["ts"].max() < P["demo_now"]


def test_asset_register_is_plant_scale():
    a = load("assets")
    assert 70 <= len(a) <= 90
    assert set(["AC-04", "FN-02", "BESS-01", "TES-01", "CR-AHU-01", "M-27"]) - set(a["asset_id"]) == {"M-27"}
    assert (a[a.asset_class == "pv"]["rated_kw"].sum()) == sum(P["pv"]["arrays"].values())
    assert 50 <= len(load("meters")) <= 65


def test_receiving_point_balances_with_loads_pv_bess():
    s = load("site_load_30min")
    resid = s["gross_load_kw"] - s["pv_kw"] - s["bess_kw"] - s["import_kw"]
    assert resid.abs().max() < 1.0
    assert s["import_kw"].max() < P["plant"]["contracted_demand_kw"]


def test_bess_soc_within_limits():
    b = load("bess_state_5min")
    assert b["soc_pct"].min() >= P["bess"]["soc_min_pct"] - 1e-6
    assert b["soc_pct"].max() <= P["bess"]["soc_max_pct"] + 1e-6
    assert b["power_kw"].abs().max() <= P["bess"]["power_kw"] + 1e-6


def test_pv_physical():
    pv = load("pv_actual_5min")
    assert pv["pv_kw"].min() >= 0
    assert pv.loc[(pv.hour < 4) | (pv.hour >= 19), "pv_kw"].max() == 0
    assert pv["pv_kw"].max() <= sum(P["pv"]["arrays"].values())
    f = load("pv_forecast_30min")
    assert ((f.p10_kw <= f.p50_kw + 1e-6) & (f.p50_kw <= f.p90_kw + 1e-6)).all()


def test_anomaly_ac04_specific_power_drift():
    c = load("compressor_perf")
    recent = c[c.date >= "2026-08-17"].groupby("compressor_id").apply(lambda g: g.energy_kwh.sum() / (g.air_nm3.sum() / 60), include_groups=False)
    peers = recent.drop(["AC-04", "AC-06"], errors="ignore")
    peers = peers[peers > 0]
    excess = recent["AC-04"] / peers.median() - 1
    assert 0.15 <= excess <= 0.20


def test_anomaly_m27_stuck_about_two_days():
    t = load("telemetry_5min")
    m = t[t.meter_id == "M-27"].sort_values("ts")
    run = m[m.ts >= P["stuck_meter"]["start"]]
    assert run["kw"].nunique() == 1
    assert len(run) * 5 / 60 >= 48
    before = m[m.ts < P["stuck_meter"]["start"]]
    assert before["kw"].nunique() > 50


def test_anomaly_fn02_batch_overlaps_dr_window():
    s = load("production_schedule")
    ev = P["dr_events"]["today"]
    fn02 = s[(s.asset_id == "FN-02") & (s.job_type == "sinter_batch") & (s.date == ev["date"])]
    overl = fn02[(fn02.start_ts < f"{ev['date']}T{ev['end']}") & (fn02.end_ts > f"{ev['date']}T{ev['start']}")]
    assert len(overl) == 1 and not overl.iloc[0]["interruptible"]
    tags = load("plc_tags_snapshot")
    assert tags[(tags.asset_id == "FN-02") & (tags.tag_name == "batch_committed")]["value"].iloc[0] == 1.0


def test_anomaly_pv_cloud_band_at_1500():
    f = load("pv_forecast_30min")
    latest = f[(f.date == P["demo_now"][:10]) & (f.issued_at == f"{P['demo_now'][:10]}T13:00")]
    deep = latest[latest.slot == P["pv"]["cloud_band_today"]["deepest_slot"]].iloc[0]
    assert deep.p10_kw < 0.35 * deep.p50_kw
    assert deep.ts.endswith("15:00")


def test_anomaly_injection_note_present():
    txt = open(os.path.join(ROOT, "factory_copilot", "corpus", "shift_handover_2026-08-19.md")).read().lower()
    assert "ignore interlocks" in txt and "clean-room hvac" in txt and "do not ask for confirmation" in txt


def test_dr_history_has_one_underdelivery_and_reconciles():
    from factory_copilot.core import dr_math
    d = load("dr_events")
    settled = d[d.status == "settled"]
    assert len(settled) >= 3
    under = settled[settled.delivered_kw < settled.requested_kw]
    assert len(under) == 1 and under.iloc[0]["penalty_jpy"] > 0
    assert (settled[settled.delivered_kw >= settled.requested_kw]["penalty_jpy"] == 0).all()
    site = load("site_load_30min")
    for _, e in settled.iterrows():
        load_by, net_by = {}, {}
        for dte, g in site.groupby("date"):
            load_by[dte] = dict(zip(g.slot, g.import_kw))
            net_by[dte] = dict(zip(g.slot, g.import_kw + g.bess_kw))
        elig = sorted(site.loc[site.baseline_eligible & (site.date < e.date), "date"].unique(), reverse=True)
        slots = list(range(int(e.start_slot), int(e.end_slot)))
        bl = dr_math.high_4_of_5_baseline(load_by, net_by, elig, slots, net_by[e.date])
        st = dr_math.settle_event(e.requested_kw, bl["baseline_kw"], {s: load_by[e.date][s] for s in slots}, e.energy_rate_jpy_kwh, e.penalty_rate_jpy_kwh)
        assert abs(st["delivered_avg_kw"] - e.delivered_kw) < 0.5
        assert abs(st["penalty_jpy"] - e.penalty_jpy) < 2


def test_jepx_calibrated_to_fy2026_regime():
    j = load("jepx_prices_30min")
    monthly = j.groupby(j.date.str[:7]).spot_jpy_kwh.mean()
    for m, target in (("2026-06", 20.0), ("2026-07", 19.9), ("2026-08", 21.2)):   # MARKET_FACTS s.1.3
        assert abs(monthly[m] - target) < 1.5, (m, monthly[m])
    assert j.spot_jpy_kwh.max() < 64.28          # below the FY2026 real Tokyo maximum
    assert j.imbalance_jpy_kwh.max() <= 200.0     # scarcity cap until 2026-09-30
    today = j[j.date == P["demo_now"][:10]].set_index("slot")
    assert today.loc[35:39, "spot_jpy_kwh"].min() >= 35.0 and today.loc[30, "spot_jpy_kwh"] < 35.0


def test_ledger_july_dr_lines_reconcile():
    led = load("savings_ledger")
    d = load("dr_events")
    jul = led[led.month == "2026-07"].set_index("category")
    evs = d[(d.date.str[:7] == "2026-07") & (d.status == "settled")]
    assert abs(jul.loc["dr_energy_payment", "amount_jpy"] - evs.payment_jpy.sum()) < 2
    assert abs(-jul.loc["dr_penalty", "amount_jpy"] - evs.penalty_jpy.sum()) < 2
    assert set(led.month) == set(P["periods"]["ledger_months"])


def test_corpus_figures_match_contract_table():
    t = load("tariff_contract").set_index("parameter")["value"]
    dr = open(os.path.join(ROOT, "factory_copilot", "corpus", "dr_contract_summary.md")).read()
    gs = open(os.path.join(ROOT, "factory_copilot", "corpus", "gain_share_agreement_summary.md")).read()
    assert f"{t['dr_availability_jpy_kw_month']:.0f} JPY per kW-month" in dr
    assert f"{t['dr_energy_rate_jpy_kwh']:.0f} JPY per delivered kWh" in dr
    assert f"{t['dr_penalty_rate_jpy_kwh']:.0f} JPY per kWh short" in dr
    assert f"{t['dr_contracted_capacity_kw']:,.0f} kW" in dr
    assert f"{t['baas_fee_jpy_month']:,.0f} JPY per month" in gs
    assert f"{t['gain_share_pct']:.0f} %" in gs


def test_no_identifiers_in_repo_files():
    """The repo goes public: no project id (read from env at test time), e-mail address or API key in any source file."""
    pats = [r"[\w.+-]+@(gmail|google)\.com", r"AIza[0-9A-Za-z_-]{20}"]
    pats += [re.escape(v) for v in {os.getenv("GOOGLE_CLOUD_PROJECT"), os.getenv("BQ_PROJECT")} if v]
    bad = re.compile("|".join(pats))
    for base, _, files in os.walk(ROOT):
        if any(x in base for x in ("/data/out", "__pycache__", "/.snap", "/eval/results")):
            continue
        for f in files:
            if f.endswith((".py", ".md", ".json", ".yaml", ".js", ".html", ".css", ".txt", ".example")) or f == "Dockerfile":
                assert not bad.search(open(os.path.join(base, f), errors="ignore").read()), os.path.join(base, f)
