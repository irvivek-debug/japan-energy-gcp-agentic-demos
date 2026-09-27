"""UI v2: the read-only endpoints behind every figure on the new pages, the routing of / and /v1/, and the copy rules."""
import json
import os
import re

import pytest
from fastapi.testclient import TestClient

from conftest import ROOT
from server import app as srv
from server import v2_api

C = TestClient(srv.app)
BANNED = re.compile(r"\b(delve|tapestry|testament|underscore|elevate|crucial|pivotal|vital|foster|vibrant|intricate|landscape|showcase|boasts)\b", re.I)
DASHES = re.compile("[–—]")
V2_PAGES = ["/", "/case/index.html", "/case/gap.html", "/case/prize.html", "/case/solution.html", "/case/proof.html",
            "/workspace/value.html", "/workspace/index.html", "/workspace/swarm.html", "/workspace/persona.html", "/workspace/handover.html"]


def _get(ep):
    r = C.get(ep)
    assert r.status_code == 200, ep
    return r.json()


@pytest.mark.parametrize("page", V2_PAGES)
def test_v2_pages_served(page):
    r = C.get(page)
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "/kit.css" in r.text and "/config.js" in r.text


def test_v1_kept_at_v1():
    r = C.get("/v1", follow_redirects=False)
    assert r.status_code in (307, 308) and r.headers["location"] == "/v1/"
    v1 = C.get("/v1/")
    assert v1.status_code == 200 and 'src="app.js"' in v1.text and "/kit.css" not in v1.text
    for asset in ("/v1/app.js", "/v1/styles.css", "/v1/tokens.css", "/v1/hold-to-confirm.js"):
        assert C.get(asset).status_code == 200, asset
    assert 'src="app.js"' not in C.get("/").text
    assert C.get("/favicon.ico").status_code == 200


def test_meta_counts_every_table():
    m = _get("/api/meta")
    schema = json.load(open(os.path.join(ROOT, "factory_copilot", "schema.json")))
    assert [t["name"] for t in m["tables"]] == list(schema["tables"])
    assert all(t["rows"] > 0 for t in m["tables"])
    assert m["demo_now"].startswith("2026-08-19") and m["backend"] in ("local", "bigquery")
    assert all(len(w) == 2 and w[0] <= w[1] for w in m["windows"].values())


def test_research_facts_all_cited():
    r = _get("/api/research")
    assert r["facts"] and r["statements"]
    for k, f in r["facts"].items():
        assert f["cite"] and f["label"] and f["value"] is not None, k
    for k, s in r["statements"].items():
        assert s["cite"], k
    assert r["facts"]["imbalance_cap_oct"]["value"] == 300


def test_gap_rows_from_data():
    g = _get("/api/gap")
    keys = [r["key"] for r in g["rows"]]
    assert keys == ["dr_delivery", "billing_peak", "compressed_air", "pv_forecast", "bess_soc", "deviation"]
    for r in g["rows"]:
        for f in ("quantity", "ordinary", "best", "gap", "research", "cite", "source"):
            assert r.get(f), (r["key"], f)
    assert g["note"]["is"] and g["note"]["is_not"]
    ov = _get("/api/overview")["kpis"]
    peak = next(r for r in g["rows"] if r["key"] == "billing_peak")
    assert f"{ov['plant_load']['month_peak_kw']:,.0f}" in peak["ordinary"]


def test_strip_series_align():
    s = _get("/api/strip")
    n = len(s["times"])
    assert n > 48 and s["window"] == [s["times"][0], s["times"][-1]]
    assert {x["key"] for x in s["series"]} == {"import", "compressed_air", "m27", "pv", "bess_soc", "jepx"}
    for x in s["series"]:
        assert len(x["values"]) == n and len(x["status"]) == n and len(x["badge"]) == n, x["key"]
        assert x["unit"] and x["source"]


def test_prize_is_ranges_with_honest_gap():
    p = _get("/api/prize")
    codes = [b["code"] for b in p["branches"]]
    assert len(codes) == 6 and len(set(codes)) == 6
    for b in p["branches"]:
        assert b["hue"] in {f"b{i}" for i in range(1, 7)} and b["lines"]
        for ln in b["lines"]:
            if ln["low"] is None:
                assert ln["high"] is None       # rendered as NOT IN THE DATA, never a guessed point
            else:
                assert ln["low"] <= ln["high"], ln
    assert any(ln["low"] is None for b in p["branches"] for ln in b["lines"])


def test_value_metrics_have_band_or_honest_label():
    v = _get("/api/value")
    assert len(v["metrics"]) == 7
    for m in v["metrics"]:
        assert m["unit"] and m["agent"] and m["reading"], m["key"]
        assert m["band"] is not None or m["band_text"], m["key"]
        if m["band"] is None and m["band_text"] == "NO VERIFIED BENCHMARK HELD":
            assert not m["cite"]


def test_proof_reads_eval_results():
    p = _get("/api/proof")
    adk = json.load(open(os.path.join(ROOT, "eval", "results", "adk_summary.json")))
    assert p["adk"]["total"] == len(adk["cases"]) and p["adk"]["pass_after_retry"] <= p["adk"]["total"]
    assert p["runs"][-1]["run"] == "final" and p["runs"][-1]["cases"] == p["adk"]["total"]
    we = p["worked_example"]
    assert we["truth"]["p10_kw"] <= we["truth"]["p50_kw"] <= we["truth"]["p90_kw"]
    assert we["question"] and str(int(we["truth"]["p10_kw"])) in we["reply_excerpt"].replace(",", "")
    assert "{t:" not in we["sql"]


def test_personas_reference_real_agents_prompts_and_kpis():
    ps = _get("/api/personas")["personas"]
    agents = {a["agent_id"] for a in _get("/api/agents")["agents"]}
    prompts = {p["id"] for p in _get("/api/suggested-prompts")["prompts"]}
    persona_js = open(os.path.join(ROOT, "ui", "workspace", "persona.js")).read()
    assert len(ps) == 4
    for p in ps:
        assert set(p["agents"]) <= agents and set(p["questions"]) <= prompts, p["id"]
        for k in p["kpis"]:
            assert f"{k}:" in persona_js, (p["id"], k)


def test_agents_carry_role_reads_description():
    ag = _get("/api/agents")["agents"]
    roles = [a["role"] for a in ag]
    assert roles.count("The lead") == 1 and roles.count("The reviewer") == 1 and roles.count("Specialist") >= 4
    assert all(a["description"] and a["reads"] for a in ag)


def test_compressor_trend_and_bess_limits():
    t = _get("/api/compressor-trend")
    assert len(t["dates"]) == len(t["ac04"]) == len(t["peer_median"]) > 7
    assert t["ac04"][-1] > t["peer_median"][-1]
    lim = _get("/api/bess")["limits"]
    assert lim["soc_min_pct"] < lim["soc_max_pct"] and lim["power_kw"] > 0 and lim["energy_kwh"] > 0


def test_enrich_action_for_sign_off_sheet():
    from factory_copilot.tools import factory
    fl = factory.list_flexible_loads("2026-08-19", "16:30", "19:00")
    sim = factory.simulate_edge_interlock(fl["draft_plan_json"])
    resp = factory.propose_load_shed_plan(sim["plan_id"], "test rationale", "DR-20260819")
    pa = {"id": "x", "kind": "load_shed_plan", "summary": "s", "details": resp.get("pending_action", resp).get("details", {}), "proposed_by": "factory_interlock_agent"}
    e = v2_api.enrich_action(pa)
    assert e["author"] == "factory_interlock_agent" and e["reasoning"]
    assert any("edge rejected" in u for u in e["unverified"])
    assert e["unverified"][0].startswith("Edge verdicts on") and "REJECT" in e["unverified"][0]
    assert any("rebound" in u for u in e["unverified"])
    wo = v2_api.enrich_action({"kind": "work_order", "details": {"rationale": "r"}})
    assert wo["reasoning"] == "r" and wo["unverified"]


def test_api_copy_has_no_dashes_or_banned_words():
    for ep in ("/api/gap", "/api/prize", "/api/value", "/api/personas", "/api/research", "/api/agents"):
        txt = json.dumps(_get(ep), ensure_ascii=False)
        assert not DASHES.search(txt), ep
        assert not BANNED.search(txt), ep


def test_ui_copy_rules_and_no_hand_typed_research():
    for d in ("", "case", "workspace"):
        base = os.path.join(ROOT, "ui", d)
        for f in os.listdir(base):
            if f.endswith((".html", ".js")) and f not in ("shell.js", "motion.js", "signoff.js"):
                src = open(os.path.join(base, f)).read()
                assert not DASHES.search(src), f
                assert not BANNED.search(src), f
    # research figures come from /api/research, not from the page source
    facts = _get("/api/research")["facts"]
    case_js = open(os.path.join(ROOT, "ui", "case", "case.js")).read()
    for k in ("tokyo_spot_fy2026", "vppdr_tertiary2_fy2025h1", "wheeling_ehv_basic"):
        assert str(facts[k]["value"]) not in case_js, k


def test_chat_reports_a_run_that_ends_without_an_answer(monkeypatch):
    """A failed model call (for example expired credentials) must reach the page as an error, not an empty answer."""
    class Sess:
        async def get_session(self, **k):
            return None

        async def create_session(self, **k):
            return type("S", (), {"id": "s-test"})()

    class Runner:
        async def run_async(self, **k):
            return
            yield  # an async generator that ends with no events

    monkeypatch.setattr(srv, "_runner", Runner())
    monkeypatch.setattr(srv, "_session_service", Sess())
    monkeypatch.setenv("AGENT_BACKEND", "local")
    r = C.post("/api/chat", json={"message": "Build the DR plan"})
    evs = [json.loads(x[6:]) for x in r.text.split("\n\n") if x.startswith("data: ")]
    assert [e["type"] for e in evs] == ["session", "error", "done"]
    assert "without an answer" in evs[1]["error"]
