"""UI version alpha: the /api/alpha/* endpoints, UI_VARIANT routing, the replay stream and the copy rules over the
story data (Lane Reach: headline at most 10 words, lines at most 40 words, no dashes, no banned words)."""
import importlib
import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT
from server import alpha_api
from server import app as srv

C = TestClient(srv.app)
BANNED = re.compile(r"\b(delve|tapestry|testament|underscore|elevate|crucial|pivotal|vital|foster|vibrant|intricate|landscape|showcase|boasts)\b", re.I)
DASHES = re.compile("[–—]")
UI = os.path.join(ROOT, "ui-alpha")


def _get(ep):
    r = C.get(ep)
    assert r.status_code == 200, ep
    return r.json()


def _story():
    src = open(os.path.join(UI, "story.js")).read()
    return json.loads(src.split("/*STORY-JSON-START*/")[1].split("/*STORY-JSON-END*/")[0])


# ---------------------------------------------------------------------------------------------- routing
def test_default_variant_keeps_v2_at_root():
    assert "/kit.css" in C.get("/").text and "alpha-shell.js" not in C.get("/").text
    assert C.get("/api/health").json()["ui_variant"] == "v2"
    assert C.get("/v1/").status_code == 200


def test_alpha_variant_mounts_alpha_at_root_and_keeps_v2_and_v1(monkeypatch):
    monkeypatch.setenv("UI_VARIANT", "alpha")
    monkeypatch.setenv("WARM_CACHES", "0")
    mod = importlib.reload(srv)
    try:
        c = TestClient(mod.app)
        root = c.get("/").text
        assert "alpha-shell.js" in root and "pane-call" in root
        assert c.get("/api/health").json()["ui_variant"] == "alpha"
        for asset in ("/alpha.css", "/alpha-extra.css", "/alpha-shell.js", "/story.js", "/schematic.js", "/call.js", "/app.js"):
            assert c.get(asset).status_code == 200, asset
        v2 = c.get("/v2/").text
        assert "/kit.css" in v2 and "alpha-shell.js" not in v2
        assert c.get("/v2", follow_redirects=False).headers["location"] == "/v2/"
        assert c.get("/kit.css").status_code == 200                # v2's absolute asset paths still resolve
        assert c.get("/case/gap.html").status_code == 200
        assert 'src="app.js"' in c.get("/v1/").text               # v1 unchanged
        assert c.get("/api/alpha/timeline").status_code == 200
    finally:
        monkeypatch.delenv("UI_VARIANT")
        importlib.reload(srv)
    assert "alpha-shell.js" not in C.get("/").text


def test_dockerfile_copies_alpha():
    assert "COPY ui-alpha/ ui-alpha/" in open(os.path.join(ROOT, "Dockerfile")).read()


# ---------------------------------------------------------------------------------------------- endpoints
def test_timeline_from_ledger_events_and_peaks():
    t = _get("/api/alpha/timeline")
    months = [r["month"] for r in t["rows"]]
    assert months == sorted(months) and months[0] == "2026-01"
    jul = next(r for r in t["rows"] if r["month"] == "2026-07")
    assert jul["dr_events"] == 2 and jul["verified_m_jpy"] > 0 and jul["billing_peak_kw"] > 14000
    assert t["marker"]["month"] == "2026-07" and "DR season" in t["marker"]["text"]
    aug = next(b for b in t["billing_peaks"] if b["month"] == "2026-08")
    assert aug["around_dr_event"] and aug["extra_billing_demand_kw"] > 0 and abs(aug["extra_demand_charge_jpy"] - aug["extra_billing_demand_kw"] * t["demand_charge_jpy_kw_month"]) < t["demand_charge_jpy_kw_month"]
    assert t["contracted_kw"] == 16000


def test_schematic_is_a_real_twin():
    s = _get("/api/alpha/schematic")
    ids = {n["id"] for n in s["nodes"]}
    assert {"grid", "msb", "pv", "bess", "aggregator", "jepx", "cleanroom", "lines", "compressors", "furnaces", "wastewater"} <= ids
    by = {n["id"]: n for n in s["nodes"]}
    assert by["compressors"]["state"] == "crit" and "AC-04" in by["compressors"]["sub"]
    assert by["furnaces"]["state"] == "watch" and "FN-02" in by["furnaces"]["sub"] and by["furnaces"]["plan_summary"]["reject"] == 1
    assert by["wastewater"]["plan_summary"]["limit"] == 4
    assert [r["rule_id"] for r in by["cleanroom"]["rules"]] == ["IR-CR-01", "IR-CR-02"]
    assert by["cleanroom"]["plan_summary"] is None or all(p["asset_id"] not in ("CR-AHU-01", "CR-AHU-02", "CR-AHU-03", "CR-AHU-04") for p in by["cleanroom"]["plan"])
    for n in s["nodes"]:
        assert n["label"] and n["sub"] and n["watchers"] and n["readings"], n["id"]
        assert n["zone"] in {z["id"] for z in s["zones"]}
    for a, b, _ in s["links"]:
        assert a in ids and b in ids
    assert s["edge_summary"]["firm_reduction_kw"] > 3000 and s["plan_id"].startswith("PLAN-")


def test_recorded_run_is_labelled_replay():
    for agent in alpha_api.RECORDED:
        r = _get(f"/api/alpha/recorded?agent={agent}")
        assert r["replay"] is True and "replay" in r["label"]
        assert r["probe"]["reply"] and r["probe"]["prompt"] and r["cases"], agent
    assert _get("/api/alpha/recorded?agent=nobody")["agent"] == "nobody"


def test_replay_streams_badged_events_and_queues_a_real_action():
    r = C.get("/api/alpha/replay?pace_ms=0")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    evs = [json.loads(x[6:]) for x in r.text.split("\n\n") if x.startswith("data: ")]
    assert all(e.get("replay") is True for e in evs)
    types = [e["type"] for e in evs]
    assert types[0] == "session" and types[-1] == "done" and "final" in types
    edge = next(e for e in evs if e["type"] == "tool_result" and e["tool"] == "simulate_edge_interlock")
    assert edge["result"]["summary"]["rejected"] == 1 and edge["result"]["rejected_actions"][0]["asset_id"] == "FN-02"
    pa = next(e for e in evs if e["type"] == "pending_action")["action"]
    assert pa["kind"] == "load_shed_plan" and pa["unverified"] and pa["audit"] == "APPROVED"
    assert any(e["type"] == "tool_result" and e["tool"] == "audit_plan" and e["result"]["verdict"] == "APPROVED" for e in evs)
    queued = [a for a in C.get("/api/actions").json() if a["id"] == pa["id"]]
    assert queued and queued[0]["status"] == "pending"
    done = C.post(f"/api/actions/{pa['id']}/confirm").json()
    assert done["status"] == "executed_sandbox"
    audit = next(a for a in C.get("/api/audit").json() if a["action_id"] == pa["id"])
    assert audit["decision"] == "confirm" and audit["edge_recheck"]["rejected"] == 0


# ---------------------------------------------------------------------------------------------- copy rules
def test_story_lane_reach_word_counts():
    st = _story()
    heads = [st["why"]["hero"], st["system"]["hero"], st["call"]["hero"], st["who"]["hero"], st["team"]["hero"], st["built"]["hero"]]
    heads += [b["title"] for b in st["call"]["beats"].values()] + [a["hero"] for a in st["team"]["agents"].values()]
    for h in heads:
        assert len(re.findall(r"\S+", h)) <= 10, h
    lines = [st["why"]["lede"], st["system"]["lede"], st["call"]["lede"], st["who"]["lede"], st["team"]["lede"]]
    for b in st["call"]["beats"].values():
        lines += b["lines"]
    for p in st["who"]["personas"].values():
        lines += [p["today"], p["after"]]
    for a in st["team"]["agents"].values():
        lines += [a["problem"], a["stake"]] + [v for _, v in a["rows"]]
    for ln in lines:
        assert len(re.findall(r"\S+", ln)) <= 40, ln


def test_story_and_ui_copy_rules():
    for f in os.listdir(UI):
        if f.endswith((".js", ".html", ".css")) and f not in ("alpha-shell.js", "alpha.css"):
            src = open(os.path.join(UI, f)).read()
            assert not DASHES.search(src), f
            assert not BANNED.search(src), f
    st = _story()
    txt = json.dumps(st, ensure_ascii=False)
    assert not DASHES.search(txt) and not BANNED.search(txt)
    # no technology words on the story screens 1 to 5 (drawers and screen 6 may name the stack)
    reach = json.dumps({k: st[k] for k in ("why", "system", "who")}, ensure_ascii=False) + json.dumps(st["call"]["beats"], ensure_ascii=False)
    assert not re.search(r"\b(ADK|Agent Runtime|BigQuery|SSE|LLM|orchestrator|Pattern [AB])\b", reach)


def test_alpha_api_strings_follow_copy_rules():
    for ep in ("/api/alpha/timeline", "/api/alpha/schematic"):
        txt = json.dumps(_get(ep), ensure_ascii=False)
        assert not DASHES.search(txt), ep
        assert not BANNED.search(txt), ep


def test_story_figures_resolve_from_api_only():
    """Every {{placeholder}} in the story must be a key app.js builds from /api; the story itself holds no digits
    that look like a figure with a unit."""
    st = _story()
    src = json.dumps(st, ensure_ascii=False)
    keys = set(re.findall(r"\{\{(\w+)\}\}", src))
    app_js = open(os.path.join(UI, "app.js")).read()
    for k in keys:
        assert re.search(rf"\bF\.{k}\b", app_js), k
    reach = json.dumps({k: st[k] for k in ("why", "system", "who")}, ensure_ascii=False) + json.dumps(st["call"]["beats"], ensure_ascii=False)
    assert not re.search(r"\d[\d,.]*\s?(kW|MW|JPY|%|MWh|kWh)\b", reach), "a hand-typed figure with a unit in Lane Reach copy"


@pytest.mark.parametrize("f", ["app.js", "call.js", "schematic.js", "story.js", "alpha-shell.js"])
def test_alpha_js_parses(f):
    import subprocess
    assert subprocess.run(["node", "--check", os.path.join(UI, f)], capture_output=True).returncode == 0, f
