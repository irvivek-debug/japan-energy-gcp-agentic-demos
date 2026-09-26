"""Run one prompt through the local ADK runner and print the event trace (agent, tool calls, results, text).

Usage: python eval/probe.py "question"   (needs GOOGLE_GENAI_USE_VERTEXAI / GOOGLE_CLOUD_LOCATION / GOOGLE_CLOUD_PROJECT)
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.runners import Runner  # noqa: E402
from google.adk.sessions import InMemorySessionService  # noqa: E402
from google.genai import types  # noqa: E402

from factory_copilot.agent import root_agent  # noqa: E402


async def run(q: str, verbose: bool = True):
    ss = InMemorySessionService()
    r = Runner(agent=root_agent, app_name="factory_copilot", session_service=ss)
    s = await ss.create_session(app_name="factory_copilot", user_id="probe")
    t0 = time.time()
    calls, final = [], ""
    async for ev in r.run_async(user_id="probe", session_id=s.id, new_message=types.Content(role="user", parts=[types.Part(text=q)])):
        for p in (ev.content.parts if ev.content and ev.content.parts else []):
            if p.function_call:
                calls.append((ev.author, p.function_call.name))
                if verbose:
                    print(f"[{time.time() - t0:6.1f}s] {ev.author} -> {p.function_call.name}({json.dumps(dict(p.function_call.args or {}))[:220]})")
            elif p.function_response:
                if verbose:
                    print(f"[{time.time() - t0:6.1f}s] {ev.author} <- {p.function_response.name}: {json.dumps(p.function_response.response, default=str)[:200]}")
            elif p.text and not p.thought:
                if verbose:
                    print(f"[{time.time() - t0:6.1f}s] {ev.author} TEXT final={ev.is_final_response()}: {p.text[:300]!r}")
                if ev.author == root_agent.name and ev.is_final_response():
                    final = p.text
    print(f"\n==== FINAL ({time.time() - t0:.1f}s, {len(calls)} calls)\n{final}")
    return calls, final


if __name__ == "__main__":
    asyncio.run(run(" ".join(sys.argv[1:]) or "What is the PV confidence this afternoon?"))
