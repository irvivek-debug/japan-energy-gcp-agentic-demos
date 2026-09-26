"""Shared helper for the grounding and safety evals: run one prompt through the local ADK runner and capture
tool calls (with args), tool results (pending actions, errors), the orchestrator's reply and latency."""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from factory_copilot.agent import root_agent  # noqa: E402


async def run_prompt(prompt: str, timeout_s: float = 420.0) -> dict:
    ss = InMemorySessionService()
    runner = Runner(agent=root_agent, app_name="factory_copilot", session_service=ss)
    s = await ss.create_session(app_name="factory_copilot", user_id="eval")
    t0 = time.time()
    calls, results, reply, error = [], [], "", None

    async def consume():
        nonlocal reply
        async for ev in runner.run_async(user_id="eval", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text=prompt)])):
            for p in (ev.content.parts if ev.content and ev.content.parts else []):
                if p.function_call:
                    calls.append({"agent": ev.author, "tool": p.function_call.name, "args": dict(p.function_call.args or {})})
                elif p.function_response:
                    resp = p.function_response.response or {}
                    results.append({"agent": ev.author, "tool": p.function_response.name, "response": resp})
                elif p.text and not p.thought and ev.author == root_agent.name:
                    reply += p.text

    try:
        await asyncio.wait_for(consume(), timeout=timeout_s)
    except Exception as e:  # recorded, never hidden
        error = f"{type(e).__name__}: {str(e)[:300]}"
    tool_errors = [{"tool": r["tool"], "error": r["response"].get("error")} for r in results
                   if isinstance(r["response"], dict) and r["response"].get("status") == "error"]
    pending = [r["response"]["pending_action"] for r in results if isinstance(r["response"], dict) and r["response"].get("pending_action")]
    return {"prompt": prompt, "reply": reply, "latency_s": round(time.time() - t0, 1), "error": error,
            "tool_calls": calls, "tool_names": [c["tool"] for c in calls], "tool_errors": tool_errors, "pending_actions": pending}


NUM = re.compile(r"(?<![\w.])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(million|m\b|k\b)?", re.I)


def numbers_in(text: str) -> list[float]:
    out = []
    for m in NUM.finditer(text or ""):
        v = float(m.group(1).replace(",", ""))
        suf = (m.group(2) or "").lower()
        if suf in ("million", "m"):
            v *= 1e6
        elif suf == "k":
            out.append(v)          # keep the raw value as well: "3,000 kW" style is not a thousands suffix
            v *= 1e3
        out.append(v)
    return out


def matches(truth: float, found: list[float], rel: float = 0.01, abs_tol: float = 0.0) -> bool:
    tol = max(abs(truth) * rel, abs_tol)
    return any(abs(f - truth) <= tol for f in found)


def dump(path: str, obj) -> None:
    with open(path, "w") as f:
        json.dump(obj, f, indent=1, default=str)
