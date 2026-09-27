"""Generator properties, calibration, schema parity, deterministic instances, agent tools, server, dry-run controller."""
import csv
import json
from datetime import date

import numpy as np
import pytest

from energy_lab.config import OUT_DIR, ROOT, SCHEMA_PATH
from energy_lab.problems.base import load_instance, load_manifest
from energy_lab.sim import facts
from energy_lab.sim.calendar import fy_days, is_holiday


def rows(table):
    with open(OUT_DIR / f"{table}.csv") as f:
        return list(csv.DictReader(f))


def test_schema_copy_in_package_is_identical():
    assert SCHEMA_PATH.read_text() == (ROOT / "energy_lab" / "schema.json").read_text()


def test_every_table_matches_schema_columns():
    schema = json.loads(SCHEMA_PATH.read_text())["tables"]
    for name, spec in schema.items():
        with open(OUT_DIR / f"{name}.csv") as f:
            header = next(csv.reader(f))
        assert header == [c["name"] for c in spec["columns"]], name
        assert {c["type"] for c in spec["columns"]} <= {"STRING", "INT64", "FLOAT64", "BOOL"}


def test_history_row_count_derives_from_calendar():
    n_days = sum(len(fy_days(fy)) for fy in (2023, 2024, 2025))
    assert len(rows("market_history")) == 48 * n_days


def test_calibration_monthly_means_hit_market_facts():
    cal = rows("calibration")
    monthly = [r for r in cal if r["metric"].startswith("monthly_mean_m")]
    assert len(monthly) == 36
    assert all(abs(float(r["rel_error_pct"])) < 0.5 for r in monthly)
    annual = {(r["fiscal_year"], r["metric"]): r for r in cal}
    for fy, tgt in facts.TOKYO_ANNUAL_MEAN.items():
        assert abs(float(annual[(str(fy), "tokyo_mean")]["synthetic"]) - tgt) < 0.05


def test_prices_respect_market_rules():
    h = rows("market_history")
    p = np.array([float(r["tokyo_price_jpy_kwh"]) for r in h])
    imb = np.array([float(r["imbalance_price_jpy_kwh"]) for r in h])
    assert p.min() >= facts.PRICE_FLOOR and p.max() <= facts.PRICE_CAP_SIM
    assert imb.max() <= 200.0 + 1e-9                          # C = 200 JPY/kWh before 2026-10-01
    assert (p <= 0.011).sum() > 0                              # spring floor events exist (deliberate anomaly)


def test_holiday_calendar():
    assert is_holiday(date(2026, 9, 22))                      # citizens' holiday (Silver Week 2026)
    assert is_holiday(date(2025, 11, 24))                     # substitute holiday for Nov 23 (Sunday)
    assert not is_holiday(date(2025, 11, 25))


def test_scenario_banks_include_stress_and_cap_switch():
    sm = rows("scenario_monthly")
    assert any(r["stress"] != "none" for r in sm if r["bank"] == "holdout")
    ho = [float(r["annual_mean_price_jpy_kwh"]) for r in sm if r["bank"] == "holdout"]
    tr = [float(r["annual_mean_price_jpy_kwh"]) for r in sm if r["bank"] == "train"]
    assert np.mean(ho) > np.mean(tr)                           # holdout is the harsher, realised-like view
    assert max(float(r["max_imbalance_jpy_kwh"]) for r in sm) <= 300.0 + 1e-9


def test_instances_verify_and_are_read_only():
    for name in load_manifest()["instances"]:
        arr, sha = load_instance(name)
        assert len(sha) == 64
        a = next(v for v in arr.values() if isinstance(v, np.ndarray) and v.ndim > 0 and v.dtype.kind == "f")
        with pytest.raises(ValueError):
            a[0] = 1


def test_instance_content_is_deterministic():
    from energy_lab.sim.instances import N_SCEN, SEEDS, build_tariff
    from energy_lab.sim.npz import content_sha256
    from energy_lab.sim.scenarios import generate_bank

    tr = generate_bank("train", N_SCEN["train"], SEEDS["train_bank"])
    ho = generate_bank("holdout", N_SCEN["holdout"], SEEDS["holdout_bank"])
    built = build_tariff(tr, ho)
    for name in ("tariff_pricing_train", "tariff_pricing_holdout"):
        assert content_sha256(built[name]["arrays"]) == load_manifest()["instances"][name]["sha256"]


# --- agent tools ---------------------------------------------------------------------------------------------------
def test_tools_cite_sources_and_handle_missing():
    from energy_lab.tools import lab_tools as t

    ms = t.get_market_stats(2025)
    assert ms["status"] == "ok" and ms["source"] == ["energy_alphaevolve_lab.market_history", "energy_alphaevolve_lab.calibration"]
    assert abs(ms["stats"]["tokyo_mean_jpy_kwh"] - facts.TOKYO_ANNUAL_MEAN[2025]) < 0.05
    assert t.get_market_stats(2019)["status"] == "not_found"
    assert t.get_run_summary("no.such.run")["status"] == "not_found"
    assert t.explain_cost_stack("LV")["status"] == "error"
    ps = t.get_portfolio_stats("")
    assert ps["portfolio_total"]["customers"] == len(rows("customers_train"))


def test_agent_has_no_execute_or_promote_tool():
    import energy_lab

    names = [f.__name__ for f in energy_lab.agent.root_agent.tools]
    assert not any(n.startswith("execute_") or "promote" in n for n in names)
    assert all(n.startswith(("list_", "get_", "explain_", "propose_")) for n in names)


def test_propose_human_review_writes_nothing(tmp_path):
    from energy_lab.tools import lab_tools as t

    r = t.propose_human_review("no.such.run", "p001", "x")
    assert r["status"] == "not_found"


# --- server ----------------------------------------------------------------------------------------------------------
def test_server_endpoints_and_promotion_refusal():
    from fastapi.testclient import TestClient

    from server.app import app

    c = TestClient(app)
    for u in ("/api/health", "/api/overview", "/api/market/heatmap?fy=2024", "/api/market/duration", "/api/portfolio",
              "/api/cost_stack?voltage=EHV", "/api/calibration", "/api/runs", "/api/ledger"):
        assert c.get(u).status_code == 200, u
    hm = c.get("/api/market/heatmap?fy=2025").json()
    assert len(hm["z"]) == 365 and len(hm["z"][0]) == 48
    assert c.get("/api/market/heatmap?fy=2019").status_code == 404


# --- controller (offline dry-run mutator) ----------------------------------------------------------------------------
def test_dry_run_controller_end_to_end(runs_dir):
    from energy_lab.harness.budget import BudgetPolicy, Ledger
    from energy_lab.harness.llm import DryRunMutator
    from energy_lab.harness.local_controller import LocalController
    from energy_lab.problems import get_problem

    pol = BudgetPolicy(max_programs_per_run=4, concurrency=2)
    ctl = LocalController(get_problem("tariff_pricing"), DryRunMutator(3), policy=pol, ledger=Ledger(runs_dir / "l.json"),
                          runs_dir=runs_dir, dry_run=True, log=lambda *a: None)
    rec = ctl.run()
    assert rec["source"] == "local-dry-run-mutator" and rec["evolved"] is False
    assert rec["budget"]["programs_evaluated"] == 4
    assert rec["holdout"]["seed"] is not None and "holdout_delta" in rec["holdout"]
    assert (runs_dir / f"{rec['run_id']}.json").exists()
    assert not list(runs_dir.glob("*.partial.json"))


def test_every_tool_succeeds_on_real_data():
    """Happy-path regression: every agent tool must return status ok (or pending_approval) on the committed tables.
    get_holdout_result silently returned a SQL error ('at' is a reserved word) until 2026-09-27 and the evals, which
    grade final answers, did not notice because the agent fell back to other tools."""
    import os

    import energy_lab.store as store_mod
    from energy_lab.datastore import DataStore
    from energy_lab.tools import lab_tools as t

    real = DataStore("energy_alphaevolve_lab", str(ROOT / "data" / "out"), str(ROOT / "energy_lab" / "schema.json"))
    orig = t.STORE
    t.STORE = real
    try:
        runs = real.query("SELECT run_id, best_program_id FROM {t:lab_runs} ORDER BY started")
        if not runs:
            pytest.skip("no exported runs")
        rid, pid = runs[-1]["run_id"], runs[-1]["best_program_id"]
        calls = [t.list_runs(""), t.get_run_summary(rid), t.get_best_program_diff(rid), t.get_invariant_catches(rid, ""),
                 t.get_holdout_result(rid), t.get_market_stats(2025, 0), t.get_market_stats(2026, 1),
                 t.get_portfolio_stats(""), t.explain_cost_stack("HV"), t.propose_human_review(rid, pid, "test")]
        for r in calls:
            assert r["status"] in ("ok", "pending_approval"), r
    finally:
        t.STORE = orig
