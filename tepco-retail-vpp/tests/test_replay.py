"""Recorded live runs replayed through the server's real event path (no model calls)."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

import server.app as srv
from conftest import ROOT

sys.path.insert(0, os.path.join(ROOT, "eval"))
import replay  # noqa: E402

c = TestClient(srv.app)
RUNS = replay.recordings()


def _events(text):
    import json

    return [json.loads(line[6:]) for line in text.splitlines() if line.startswith("data: ")]


def _post(monkeypatch, stream, msg="replay"):
    monkeypatch.setattr(srv, "_local_stream", lambda m, s: stream)
    return _events(c.post("/api/chat", json={"message": msg}).text)


@pytest.mark.skipif(not RUNS, reason="no recorded runs in eval/results/probes")
@pytest.mark.parametrize("sid", sorted(RUNS))
def test_every_recording_replays_to_an_answer(monkeypatch, sid):
    ev = _post(monkeypatch, replay.replay_stream(RUNS[sid]))
    assert ev[0]["type"] == "session" and ev[0].get("replay") is True
    assert [e for e in ev if e["type"] == "text" and e["author"] == "desk_orchestrator"]
    assert ev[-1]["type"] == "final" and not [e for e in ev if e["type"] == "error"]


@pytest.mark.skipif("S1" not in RUNS, reason="no S1 recording")
def test_s1_replay_lifts_audited_actions_through_the_real_path(monkeypatch):
    srv.ACTIONS.clear()
    ev = _post(monkeypatch, replay.replay_stream(RUNS["S1"]))
    kinds = sorted(e["action"]["kind"] for e in ev if e["type"] == "pending_action")
    assert kinds == ["intraday_orders", "vpp_dispatch"]
    assert {e["verdict"] for e in ev if e["type"] == "audit"} == {"pass"}
    acts = c.get("/api/actions").json()
    assert len(acts) == 2 and all(a["status"] == "pending" and a["audit"]["verdict"] == "pass" and a["unsettled"] for a in acts)
    srv.ACTIONS.clear()


def test_failed_model_call_replays_as_no_answer(monkeypatch):
    ev = _post(monkeypatch, replay.failing_stream("Hedge slots 35-38"))
    assert ev[-1]["type"] == "error" and ev[-1]["error"].startswith("no answer") and "Reauthentication" in ev[-1]["error"]
    assert not [e for e in ev if e["type"] in ("final", "text")]
