"""Shared harness: run one prompt through the real swarm (ADK Runner, in-process) and capture evidence.

Evidence per run (testing skill: a failure without evidence is a fresh investigation): question, every tool call with
author and args, tool-side error payloads, pending actions, the final reply and latency.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from typing import Any

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


async def run_query(message: str, agent=None, app_name: str = "retail_desk") -> dict[str, Any]:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    if agent is None:
        from retail_desk.agent import root_agent as agent
    ss = InMemorySessionService()
    runner = Runner(agent=agent, app_name=app_name, session_service=ss)
    session = await ss.create_session(app_name=app_name, user_id="eval")
    calls, results, errors, pending, texts = [], [], [], [], []
    final = ""
    t0 = time.time()
    try:
        from google.adk.agents.run_config import RunConfig

        async for ev in runner.run_async(user_id="eval", session_id=session.id, run_config=RunConfig(max_llm_calls=120),
                                         new_message=types.Content(role="user", parts=[types.Part(text=message)])):
            for p in (ev.content.parts if ev.content and ev.content.parts else []):
                if p.function_call:
                    calls.append({"author": ev.author, "tool": p.function_call.name, "args": dict(p.function_call.args or {})})
                elif p.function_response:
                    resp = p.function_response.response or {}
                    results.append({"author": ev.author, "tool": p.function_response.name, "result": resp})
                    if isinstance(resp, dict):
                        if resp.get("status") == "error":
                            errors.append({"tool": p.function_response.name, "error": resp.get("error")})
                        if resp.get("pending_action"):
                            pending.append(resp["pending_action"])
                elif p.text and not getattr(p, "thought", False):
                    texts.append((ev.author, p.text))
            if ev.author == agent.name and ev.is_final_response() and ev.content and ev.content.parts:
                final = "".join(p.text or "" for p in ev.content.parts if not getattr(p, "thought", False))
    except Exception as exc:  # keep evidence, never swallow
        errors.append({"tool": "<runner>", "error": f"{type(exc).__name__}: {str(exc)[:400]}"})
    finally:
        await runner.close()
    sess = await ss.get_session(app_name=app_name, user_id="eval", session_id=session.id)
    state = dict(sess.state) if sess else {}
    return {"question": message, "reply": final, "tool_calls": calls, "tool_results": results, "tool_errors": errors,
            "pending_actions": pending, "audits": state.get("audits", {}), "latency_s": round(time.time() - t0, 1),
            "agent": agent.name}


def run(message: str, agent=None) -> dict[str, Any]:
    return asyncio.run(run_query(message, agent=agent))


def summarize(out: dict[str, Any]) -> str:
    lines = [f"Q: {out['question']}", f"latency {out['latency_s']} s"]
    for c in out["tool_calls"]:
        args = {k: (v if len(str(v)) < 90 else str(v)[:90] + "...") for k, v in c["args"].items()}
        lines.append(f"  {c['author']:>22} -> {c['tool']} {args}")
    for e in out["tool_errors"]:
        lines.append(f"  ERROR {e}")
    for p in out["pending_actions"]:
        lines.append(f"  PENDING {p['id']}: {p['summary']}")
    for k, v in out["audits"].items():
        lines.append(f"  AUDIT {k}: {v}")
    lines.append("REPLY:\n" + out["reply"])
    return "\n".join(lines)


if __name__ == "__main__":
    import json

    out = run(" ".join(sys.argv[1:]) or "Hedge slots 35-38 before gate closure.")
    os.makedirs(os.path.join(ROOT, "eval", "results", "probes"), exist_ok=True)
    with open(os.path.join(ROOT, "eval", "results", "probes", f"probe_{int(time.time())}.json"), "w") as f:
        json.dump(out, f, indent=1, default=str)
    print(summarize(out))
