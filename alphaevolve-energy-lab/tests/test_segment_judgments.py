"""The sampling-margin caveat travels as data: recomputed judgments -> lab tables -> analyst tools (and the UI).

Uses the committed evidence (runs/, read-only) and the committed tables (data/out). Run 4 is the pre-registered tariff
run whose champion passes semiconductor_fab only under the sampling margin; trading runs never carry a caveat.
"""
import hashlib
import json
import re

import pytest

from conftest import ROOT

RUNS = ROOT / "runs"
RUN4 = "tariff_pricing.20260927T085054Z"


def _rec(run_id):
    p = RUNS / f"{run_id}.json"
    if not p.exists():
        pytest.skip(f"{p.name} not present")
    return json.loads(p.read_text())


def _judgment():
    p = RUNS / "analysis" / f"{RUN4}.segment_judgments.json"
    if not p.exists():
        pytest.skip("run 4 judgment file not computed yet (python -m energy_lab.export_evidence)")
    return json.loads(p.read_text())


def _trading_ids():
    return sorted(p.stem for p in RUNS.glob("jepx_trading.*.json") if not p.name.endswith(".partial.json"))


@pytest.fixture
def real_tools():
    from energy_lab.datastore import DataStore
    from energy_lab.tools import lab_tools as t

    real = DataStore("energy_alphaevolve_lab", str(ROOT / "data" / "out"), str(ROOT / "energy_lab" / "schema.json"))
    orig, t.STORE = t.STORE, real
    try:
        yield t
    finally:
        t.STORE = orig


def test_tools_carry_the_margin_caveat_for_run4_and_none_for_trading(real_tools):
    t = real_tools
    j = _judgment()
    champ = next(c for c in j["candidates"] if c["is_champion"])
    fab = next(s for s in champ["folds"]["holdout"]["segments"] if s["relies_on_margin"])
    r = t.get_holdout_result(RUN4)
    assert r["status"] == "ok"
    cav = r["uplift_caveat"]
    assert "sampling margin" in cav and f"{fab['segment']} (n={fab['n']})" in cav
    assert f"{fab['rise'] * 100:+.1f} pp" in cav and f"{fab['margin_rise_limit'] * 100:.1f} pp margin limit" in cav
    assert "CAVEAT: " + cav in r["run"]["uplift_note"]
    top = r["top_k"][0]
    assert top["is_champion"] and top["relies_on_margin"] is True and top["valid_point_rules"] is False
    seg = r["champion_segment_judgments"]["segments"]
    assert [s["segment"] for s in seg] == [fab["segment"]] and seg[0]["passes_point"] is False and seg[0]["passes_margin"] is True
    for tool in (t.get_run_summary, t.get_best_program_diff):
        assert tool(RUN4)["uplift_caveat"] == cav
    listed = {x["run_id"]: x["uplift_caveat"] for x in t.list_runs("")["runs"]}
    assert listed[RUN4] == cav
    trading = _trading_ids()
    assert trading, "no trading runs to check"
    for rid in trading:
        h = t.get_holdout_result(rid)
        assert h["status"] == "ok" and h["uplift_caveat"] == "" and "champion_segment_judgments" not in h
        assert all("judgment_note" not in x for x in h["top_k"])
        assert t.get_run_summary(rid)["uplift_caveat"] == "" and listed[rid] == ""
        assert "CAVEAT" not in (h["run"]["uplift_note"] or "")


def test_caveat_is_derived_from_the_recomputed_judgment_not_typed():
    from energy_lab import export_evidence as ex
    from energy_lab import segment_judgments as sj

    rec, j = _rec(RUN4), _judgment()
    cav = ex.uplift_caveat(rec, j)
    assert cav and cav.startswith("passes only under the pre-registered sampling margin")
    # ranks that would be invalid under the v3 point rules agree with the pre-registered secondary analysis
    sec = json.loads((RUNS / "analysis" / f"{RUN4}.secondary_v4.json").read_text())
    v3_invalid = [i for i, x in enumerate(sec["v3_point_estimate_rules_on_holdout3"], 1) if not x["v3_rules_valid"]]
    m = re.search(r"under v3 point rules ranks? ([\d, -]+) of the top (\d+) would be invalid", cav)
    assert m, cav
    listed = m.group(1)
    expected = f"{v3_invalid[0]}-{v3_invalid[-1]}" if len(v3_invalid) > 1 else str(v3_invalid[0])
    assert listed == expected and int(m.group(2)) == len(sec["v3_point_estimate_rules_on_holdout3"])
    # every lab_holdout row of run 4 gets a note; margin reliance matches the recomputed segments
    for c in j["candidates"]:
        h = ex.holdout_judgment(j, c["id"])
        relies = any(s["relies_on_margin"] for s in c["folds"]["holdout"]["segments"])
        assert h["relies_on_margin"] is relies and bool(h["judgment_note"])
        assert ("only under the pre-registered sampling margin" in h["judgment_note"]) is relies
    # the UI server builds the same words from the evidence file alone
    assert sj.evidence_caveat(rec) == cav
    # a run with no margin gets nothing
    for rid in _trading_ids():
        r = _rec(rid)
        assert sj.load_or_compute(r, RUNS) is None and ex.uplift_caveat(r, None) is None and sj.evidence_caveat(r) is None
        assert "CAVEAT" not in (ex.run_rows(r, None)["uplift_note"] or "")


def test_judgment_file_matches_unchanged_evidence_and_recomputes_identically():
    from energy_lab import segment_judgments as sj

    j = _judgment()
    ev = RUNS / j["evidence_file"]
    assert hashlib.sha256(ev.read_bytes()).hexdigest() == j["evidence_sha256"]      # evidence never modified since
    assert all(j["checks"].values())
    rec = json.loads(ev.read_text())
    again = sj.compute(rec, ev)                                   # deterministic: re-executing gives the same table
    assert again["candidates"] == j["candidates"]
    # train rows are judged with the train point rules and every top-k candidate is valid there
    for c in j["candidates"]:
        tr = c["folds"]["train"]
        assert tr["rule_applied"] == "point" and tr["valid_under_applied_rule"] is True
        assert c["folds"]["holdout"]["rule_applied"] == "margin"


def test_exported_table_matches_the_judgment_file():
    import csv

    j = _judgment()
    rows = [r for r in csv.DictReader(open(ROOT / "data" / "out" / "lab_segment_judgments.csv")) if r["run_id"] == RUN4]
    n_seg = len(j["candidates"][0]["folds"]["holdout"]["segments"])
    assert len(rows) == len(j["candidates"]) * 2 * n_seg
    relies = {(r["program_id"], r["segment"]) for r in rows if r["fold_role"] == "holdout" and r["relies_on_margin"] == "true"}
    expect = {(c["id"], s["segment"]) for c in j["candidates"] for s in c["folds"]["holdout"]["segments"] if s["relies_on_margin"]}
    assert relies == expect and relies
