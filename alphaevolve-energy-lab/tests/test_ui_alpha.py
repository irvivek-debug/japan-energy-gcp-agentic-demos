"""UI version alpha: routing by UI_VARIANT, the /api/alpha/* endpoints, and the copy rules over the story and the pages.

The alpha front end is a separate story on the same back end. Unset UI_VARIANT must keep version 2 at / and version 1
at /v1/ exactly as before; UI_VARIANT=alpha mounts ui-alpha/ at /, version 2 at /v2/ and version 1 at /v1/.
"""
import json
import re
import shutil
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from conftest import ROOT
from server.app import app, mount_ui, ui_variant

C = TestClient(app)
UI = ROOT / "ui-alpha"
BANNED = re.compile(r"\b(delve|tapestry|testament|underscore|elevate|crucial|pivotal|vital|foster|vibrant|intricate|landscape|showcase|boasts)\b", re.I)
DASHES = re.compile("[–—]")
HONESTY = "local controller, not the managed AlphaEvolve service"


# ---------------------------------------------------------------------------------------------------------- routing
def test_default_variant_keeps_v2_at_root_and_no_v2_mount(monkeypatch):
    monkeypatch.delenv("UI_VARIANT", raising=False)
    assert ui_variant() == "v2"
    a = FastAPI()
    mount_ui(a, ui_variant())
    c = TestClient(a)
    assert "Concept demo" in c.get("/v1/").text and c.get("/v1/app.js").status_code == 200
    assert c.get("/lab.js").status_code == 200 and c.get("/workspace/index.html").status_code == 200     # version 2 at /
    assert c.get("/v2/").status_code == 404 and c.get("/alpha-shell.js").status_code == 404


def test_alpha_variant_mounts_alpha_at_root_v2_at_v2_v1_at_v1(monkeypatch):
    monkeypatch.setenv("UI_VARIANT", "alpha")
    assert ui_variant() == "alpha"
    a = FastAPI()
    mount_ui(a, ui_variant())
    c = TestClient(a)
    assert "Energy Lab" in c.get("/").text and c.get("/alpha-shell.js").status_code == 200 and c.get("/story.json").status_code == 200
    assert c.get("/v2/lab.js").status_code == 200 and c.get("/v2/workspace/index.html").status_code == 200
    assert "Concept demo" in c.get("/v1/").text
    assert c.get("/lab.js").status_code == 404                                                       # version 2 is no longer at /


def test_health_reports_ui_variant(monkeypatch):
    monkeypatch.delenv("UI_VARIANT", raising=False)
    assert C.get("/api/health").json()["ui_variant"] == "v2"
    monkeypatch.setenv("UI_VARIANT", "alpha")
    assert C.get("/api/health").json()["ui_variant"] == "alpha"


def test_dockerfile_ships_ui_alpha():
    text = (ROOT / "Dockerfile").read_text()
    assert "COPY . ." in text and "ui-alpha" in text
    assert not (ROOT / ".dockerignore").exists() or "ui-alpha" not in (ROOT / ".dockerignore").read_text()


# --------------------------------------------------------------------------------------------------------- endpoints
@pytest.fixture
def real_runs(monkeypatch):
    import server.alpha_api as alpha
    import server.v2_api as v2

    monkeypatch.setattr(alpha, "RUNS_DIR", ROOT / "runs")          # read-only use of the committed evidence
    monkeypatch.setattr(v2, "RUNS_DIR", ROOT / "runs")
    return C


@pytest.mark.parametrize("url", ["/api/alpha/twin", "/api/alpha/run", "/api/alpha/team", "/api/alpha/replays"])
def test_alpha_endpoints_ok(real_runs, url):
    assert real_runs.get(url).status_code == 200


def test_alpha_endpoints_survive_an_empty_runs_dir():
    assert C.get("/api/alpha/twin").status_code == 200 and C.get("/api/alpha/team").status_code == 200
    assert C.get("/api/alpha/run").status_code == 404                                               # no searched tariff run


def test_twin_nodes_states_and_readings_come_from_evidence(real_runs):
    T = real_runs.get("/api/alpha/twin").json()
    ids = [n["id"] for n in T["nodes"]]
    for must in ("seed", "controller", "sandbox", "evaluator", "invariants", "catch_churn", "catch_imbalance", "holdout", "review", "managed"):
        assert must in ids
    by = {n["id"]: n for n in T["nodes"]}
    assert by["managed"]["state"] == "dashed" and "not provisioned" in by["managed"]["sub"]
    team = real_runs.get("/api/alpha/team").json()["agents"]["invariants"]["by_rule"]
    assert by["catch_churn"]["state"] == ("crit" if team.get("churn") else "normal")
    assert by["catch_churn"]["sub"].startswith(str(team.get("churn", 0)))
    assert all(c["insight"] and c["invariant"] == "churn" for c in by["catch_churn"]["catches"])
    assert any(l == ["invariants", "catch_churn", "crit"] for l in T["links"])
    tariff_rows = [r for r in by["holdout"]["runs"] if r["problem"] == "tariff_pricing"]
    for r in tariff_rows:                                                                          # a tariff delta never travels alone
        assert r["delta"]["provenance"] == HONESTY
        if r["delta"]["valid"]:
            assert r["delta"]["caveat"] and "sampling margin" in r["delta"]["caveat"]
    assert T["provenance_label"] == HONESTY and len(T["telemetry"]) >= 3 and all(len(c["values"]) >= 2 for c in T["telemetry"])


def test_run_story_figures_and_caveat(real_runs):
    R = real_runs.get("/api/alpha/run").json()
    assert R["run"]["provenance"] == HONESTY and R["run"]["ordinal"] >= 1
    assert R["prereg"]["cohort"] and R["prereg"]["instance_sha_prefix"]
    assert R["seed"]["train"] is not None and R["champion"]["id"] and R["holdout"]["top_k"]
    d = R["holdout"]["delta"]
    if d["valid"]:
        assert d["caveat"] == R["caveat"]["text"] and d["caveat"]
        assert R["caveat"]["segments"] and all(s["rise"] > s["point_rise_limit"] for s in R["caveat"]["segments"])
    for o in R["options"]:
        if o.get("delta") and o["delta"]["valid"] and o["kind"] == "champion":
            assert o["delta"]["caveat"]
    struck = [o for o in R["options"] if o["struck"]]
    assert struck and struck[0]["reason"] and struck[0]["holdout"] is None
    assert R["analyst_question"].startswith("Did tariff run ") and R["run"]["run_id"] in R["analyst_question"]
    assert all(c["ok"] is False for c in R["gate"]["checks"] if c["id"] == "source")                 # never promotable here
    assert R["gate"]["promotion_control"].startswith("disabled")


def test_team_and_replays(real_runs):
    T = real_runs.get("/api/alpha/team").json()
    assert set(T["agents"]) == {"controller", "evaluator", "invariants", "holdout_judge", "lab_analyst"}
    assert T["agents"]["lab_analyst"]["live"] is True and "get_holdout_result" in T["agents"]["lab_analyst"]["tools"]
    assert T["value"]["trading"]["low"] is None or T["value"]["trading"]["low"] <= T["value"]["trading"]["high"]
    if T["value"]["tariff"] and T["value"]["tariff"]["valid"]:
        assert T["value"]["tariff"]["caveat"]
    assert T["value"]["tail_risk"]["citable"] is False
    P = real_runs.get("/api/alpha/replays").json()
    assert P["badge"] == "replay" and P["replays"] and all(r["replay"] is True and r["reply"] and r["recorded_in"] for r in P["replays"])
    every = next((r for r in P["replays"] if r["id"] == "tariff_latest_every_rule"), None)
    assert every and "margin" in every["reply"].lower() and "lab_segment_judgments" in every["tables"]
    assert len(P["live_checks"]) >= 3


# ---------------------------------------------------------------------------------------------------------- copy rules
def _strings(o, path=""):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from _strings(v, f"{path}[{i}]")
    elif isinstance(o, str):
        yield path, o


def _sentences(s):
    return len([x for x in re.split(r"(?<=[.!?])\s+", s.strip()) if x])


def test_story_json_lane_reach_rules():
    story = json.loads((UI / "story.json").read_text())
    heads = [(p, s) for p, s in _strings(story) if re.search(r"\.(hero|title|jtbd)$", p) and not p.endswith("_title")]
    assert heads
    for p, s in heads:
        if p.endswith(".jtbd"):
            continue
        assert len(s.split()) <= 10, f"headline over ten words at {p}: {s!r}"
    bodies = [(p, s) for p, s in _strings(story) if re.search(r"\.(lede|desc|today|after|jtbd|problem|stake|rule|blurb|sub|boundary_sub|subtitle)$|\.lines\[\d+\]$", p)]
    assert bodies
    for p, s in bodies:
        assert _sentences(s) <= 2, f"more than two sentences at {p}: {s!r}"
        assert len(s.split()) <= 40, f"body over forty words at {p}: {s!r}"
    for p, s in _strings(story):
        assert not DASHES.search(s), f"dash at {p}"
        assert not BANNED.search(s), f"banned word at {p}: {s!r}"
        if p.endswith(".clock") or p.endswith(".kicker") or p.endswith(".eyebrow") or p.endswith(".cite") or p.endswith("._rules") or ".stack[" in p or ".tables[" in p or p.endswith(".id_badge") or p.endswith(".apqc"):
            continue
        bare = re.sub(r"\{\{\w+\}\}", "", s)
        assert not re.search(r"(?<![A-Za-z0-9])\d", bare), f"typed number outside a placeholder at {p}: {s!r}"   # FY2025, CVaR95 are names
    for k in ("full", "decision", "contrast"):
        assert any(o["id"] == k for o in story["run"]["options"])
    assert story["provenance"] == HONESTY


def test_alpha_pages_and_api_strings_obey_the_copy_rules():
    for f in sorted(UI.glob("*")):
        if f.suffix in (".html", ".js", ".json", ".css"):
            text = f.read_text()
            assert not DASHES.search(text), f"dash in {f.name}"
            assert not BANNED.search(text), f"banned word in {f.name}"
    src = (ROOT / "server" / "alpha_api.py").read_text()
    assert not DASHES.search(src) and not BANNED.search(src)
    index = (UI / "index.html").read_text()
    assert "alpha-shell.js" in index and "story.json" in (UI / "app.js").read_text()
    for kit in ("alpha.css", "alpha-shell.js"):                                                     # the kit is copied unchanged
        assert (UI / kit).read_text() == (ROOT.parent / "docs" / "reference" / "ui-alpha" / kit).read_text()


def test_tariff_delta_is_rendered_only_through_the_caveat_helper():
    """Page code formats the tariff uplift only via LAB.delta, which prints the caveat with the number."""
    for name in ("app.js", "story.js", "schematic.js"):
        js = (UI / name).read_text()
        assert "holdout_delta" not in js.replace("F.holdout_delta = signed((ho.delta || {}).value)", "").replace("r.holdout_delta, unit: \"JPY M\", valid: r.uplift_valid, caveat: r.caveat", "").replace("signed(r.holdout_delta, 1)", ""), name
    app_js = (UI / "app.js").read_text()
    assert 'class="caveat"' in app_js and "data-valid" in app_js


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_node_check_every_alpha_script():
    for f in sorted(UI.glob("*.js")):
        subprocess.run(["node", "--check", str(f)], check=True)
