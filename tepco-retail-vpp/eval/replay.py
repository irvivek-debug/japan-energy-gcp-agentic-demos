"""Replay recorded agent runs through the server's real event path, without calling any model.

Recorded runs live in eval/results/probes (harness output from live Gemini runs on 2026-09-26: every tool call with
its author and arguments, every tool result, the pending actions and the lead's reply). This module rebuilds
ADK-shaped events from a recording, in the nesting the swarm produces (lead calls a specialist, the specialist's own
calls and results, the specialist's words, the lead's result), and pushes them through server.app.adk_event_to_ui:
the same code that lifts pending actions into the approval queue and attaches the auditor's verdict.

It is a verification and fallback tool. Anything shown from a replay is labelled as a replay; it is never presented as
a live answer. Recorded text passes through the current output hygiene (retail_desk.callbacks.clean_text), as live
model text does today.
"""
from __future__ import annotations

import glob
import json
import os
from typing import Any, AsyncIterator

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBES = os.path.join(ROOT, "eval", "results", "probes")
LEAD = "desk_orchestrator"
SPECIALISTS = {"trading_dispatch_agent", "contract_risk_agent", "onboarding_agent", "cfe_provenance_agent", "risk_auditor"}


class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _part(fc=None, fr=None, text=None):
    return _Obj(function_call=fc, function_response=fr, text=text, thought=False)


def _ev(author, parts, final=False, error_code=None, error_message=None):
    e = _Obj(author=author, content=_Obj(parts=parts), error_code=error_code, error_message=error_message)
    e.is_final_response = lambda: final
    return e


def recordings() -> dict[str, dict]:
    """Scenario id -> recorded run (latest recording wins)."""
    out: dict[str, dict] = {}
    for f in sorted(glob.glob(os.path.join(PROBES, "*.json"))):
        d = json.load(open(f))
        if "question" in d:
            from server.app import SCENARIOS

            sid = next((s["id"] for s in SCENARIOS if s["prompt"] == d["question"]), None)
            if sid:
                out[sid] = {**d, "recorded_file": os.path.basename(f)}
        else:
            for sid, run in d.items():
                out[sid] = {**run, "recorded_file": os.path.basename(f)}
    return out


def rebuild(run: dict) -> list:
    """ADK-shaped events in the order the swarm emits them."""
    import copy

    from retail_desk.callbacks import clean_text

    run = copy.deepcopy(run)  # never mutate the caller's recording
    calls: dict[str, list] = {}
    results: dict[str, list] = {}
    for c in run["tool_calls"]:
        calls.setdefault(c["author"], []).append(c)
    for r in run["tool_results"]:
        results.setdefault(r["author"], []).append(r)

    def take_result(author, tool):
        for i, r in enumerate(results.get(author, [])):
            if r["tool"] == tool:
                return results[author].pop(i)
        return {"author": author, "tool": tool, "result": {"status": "error", "error": "no recorded result"}}

    events = []
    for c in calls.get(LEAD, []):
        events.append(_ev(LEAD, [_part(fc=_Obj(name=c["tool"], args=c["args"]))]))
        if c["tool"] in SPECIALISTS:
            for sc in calls.get(c["tool"], []):
                if sc.get("_done"):
                    continue
                sc["_done"] = True
                events.append(_ev(c["tool"], [_part(fc=_Obj(name=sc["tool"], args=sc["args"]))]))
                r = take_result(c["tool"], sc["tool"])
                events.append(_ev(c["tool"], [_part(fr=_Obj(name=sc["tool"], response=r["result"]))]))
            lr = take_result(LEAD, c["tool"])
            words = lr["result"].get("result") if isinstance(lr["result"], dict) else str(lr["result"])
            if words:
                events.append(_ev(c["tool"], [_part(text=clean_text(str(words)))], final=True))
            events.append(_ev(LEAD, [_part(fr=_Obj(name=c["tool"], response=lr["result"]))]))
        else:
            r = take_result(LEAD, c["tool"])
            events.append(_ev(LEAD, [_part(fr=_Obj(name=c["tool"], response=r["result"]))]))
    if run.get("reply"):
        events.append(_ev(LEAD, [_part(text=clean_text(run["reply"]))], final=True))
    return events


async def replay_stream(run: dict) -> AsyncIterator[dict]:
    """A stand-in for server.app._local_stream that replays a recording through the real event conversion."""
    from server.app import LEAD as _LEAD, adk_event_to_ui

    yield {"type": "session", "session_id": f"replay-{run.get('recorded_file', 'run')}", "replay": True,
           "recorded_file": run.get("recorded_file")}
    for ev in rebuild(run):
        for e in adk_event_to_ui(ev):
            yield e
        if ev.author == _LEAD and ev.is_final_response():
            yield {"type": "final", "author": ev.author}


async def failing_stream(message: str = "", session_id: Any = None) -> AsyncIterator[dict]:
    """What the desk emits when the model call fails, e.g. expired Application Default Credentials."""
    yield {"type": "session", "session_id": "replay-error"}
    yield {"type": "tool_call", "author": LEAD, "tool": "trading_dispatch_agent", "args": {"request": message[:120]}}
    raise RuntimeError("google.auth.exceptions.RefreshError: Reauthentication is needed. Please run "
                       "`gcloud auth application-default login` to reauthenticate.")
