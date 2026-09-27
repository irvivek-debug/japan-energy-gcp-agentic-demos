"""UI v2 read-only endpoints: shape, provenance honesty, figures derived from evidence (not typed), v1 still served."""
import re

import pytest
from fastapi.testclient import TestClient

from energy_lab.harness.evidence import list_evidence
from server.app import app
from server.v2_api import HONESTY

C = TestClient(app)
V2 = ["/api/v2/landing", "/api/v2/evidence", "/api/v2/prize", "/api/v2/personas", "/api/v2/teams", "/api/v2/value",
      "/api/v2/proof", "/api/v2/solution", "/api/v2/pill"]


@pytest.mark.parametrize("url", V2)
def test_v2_endpoints_ok(url):
    assert C.get(url).status_code == 200


def test_v1_still_served_at_v1():
    assert C.get("/v1/").status_code == 200 and "Concept demo" in C.get("/v1/").text
    assert C.get("/v1/app.js").status_code == 200
    assert C.get("/favicon.ico").status_code == 200              # no 404 in the browser console on any page


def test_landing_gap_rows_come_from_data():
    L = C.get("/api/v2/landing").json()
    assert 4 <= len(L["gap_rows"]) <= 6
    fy25 = C.get("/api/market/monthly").json()["history"]
    assert L["hero"]["fy2025_tokyo_mean"] == pytest.approx(
        sum(r["tokyo"] for r in fy25 if r["fiscal_year"] == 2025) / 12, abs=0.05)
    for row in L["gap_rows"]:
        assert "source" in row["research"] and row["research"]["text"]
    assert L["provenance_label"] == HONESTY


def test_prize_only_citable_ranges_are_marked_citable():
    P = C.get("/api/v2/prize").json()
    recs = [r for r in list_evidence(include_partial=False) if r.get("status") == "finished"]
    tariff_valid = any(r.get("uplift_valid") for r in recs if r["problem"] == "tariff_pricing")
    row = next(r for r in P["rows"] if r["code"] == "APQC 3.0")
    assert row["citable"] is tariff_valid
    if not tariff_valid:
        assert "NOT CITABLE" in row["status"]
    for r in P["rows"]:
        assert r["low"] is None or r["high"] is None or r["low"] <= r["high"]


def test_every_run_view_carries_the_provenance_string(monkeypatch):
    import server.v2_api as v2
    from energy_lab.config import ROOT

    monkeypatch.setattr(v2, "RUNS_DIR", ROOT / "runs")          # read-only use of the real evidence files
    runs = C.get("/api/v2/proof").json()["runs"]
    assert runs and all(r["provenance"] == HONESTY for r in runs)
    d = C.get(f"/api/v2/dossier/{runs[0]['run_id']}").json()
    assert d["provenance"] == HONESTY and d["promotion_control"].startswith("disabled")
    assert C.get("/api/v2/dossier/no.such.run").status_code == 404
    infra = [r for r in runs if r["infrastructure_failure"]]
    assert all(r["status_label"].startswith("INFRASTRUCTURE FAILURE") for r in infra)
    L = C.get("/api/v2/landing").json()                        # a failed run is never presented as the latest search
    row = next(x for x in L["gap_rows"] if x["id"] == "tariff_tail_risk")
    assert all(r["run_id"] not in row["best"]["label"] for r in infra)


def test_evidence_series_align_with_dates():
    E = C.get("/api/v2/evidence").json()
    n = len(E["dates"])
    assert n == E["window"]["days"] and all(len(s["values"]) == n for s in E["series"])
    assert re.match(r"\d{4}-\d{2}-\d{2}", E["dates"][0])


def test_teams_limits_are_honest():
    T = C.get("/api/v2/teams").json()
    names = [t["id"] for t in T["teams"]]
    assert names == ["evolution_loop", "lab_analyst"]
    promo = next(l for l in T["limits"] if l["item"] == "Promotion")
    assert promo["ok"] is False


def test_zero_program_attempts_are_not_counted_as_searches(monkeypatch):
    import server.v2_api as v2
    from energy_lab.config import ROOT
    from energy_lab.sim.instances import SEEDS

    monkeypatch.setattr(v2, "RUNS_DIR", ROOT / "runs")          # read-only use of the real evidence files
    recs = [r for r in list_evidence(ROOT / "runs", include_partial=False) if r.get("status") == "finished"]
    searched = [r for r in recs if not v2._infra_failure(r)]
    L = C.get("/api/v2/landing").json()
    assert L["hero"]["runs"] == len(searched)
    assert L["hero"]["zero_program_attempts"] == len(recs) - len(searched)
    generated = sum(r["budget"]["programs_evaluated"] - (r.get("invalid_by_kind") or {}).get("generation", 0) for r in searched)
    assert L["hero"]["programs"] == generated                   # failed model calls are budget, not programs
    assert L["generator"]["history_seed"] == SEEDS["history"]
    cost = C.get("/api/v2/prize").json()["cost_of_search"]
    assert cost["runs"] == len(searched) and (cost["usd_low"] is None or cost["usd_low"] > 0)
    pill = C.get("/api/v2/pill").json()["text"]
    assert pill.startswith(f"{len(searched)} runs") and HONESTY in pill
