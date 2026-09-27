"""Live UI check without a bound port: send the v2 pages' exact questions to the real /api/chat endpoint (local
DuckDB backend, live Gemini) and record every SSE frame with its true arrival time, plus the approval queue after.

The endpoint function is called in-process and its StreamingResponse body is read frame by frame: the same generator
a browser reads, without the HTTP layer. (TestClient would buffer the whole stream until the run ends, losing the
timing, and the sandbox blocks binding a local port.) The captures are then streamed into the real page code by the
headless check, at their recorded pace (see docs/EVAL_REPORT.md, UI v2 verification).

Usage: GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=... python eval/live_ui_capture.py
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "eval", "results", "live_ui")


def handover_prompt() -> str:
    src = open(os.path.join(ROOT, "ui", "workspace", "handover.js"), encoding="utf-8").read()
    body = src.split("const PROMPT =", 1)[1].split(";", 1)[0]
    return "".join(re.findall(r'"([^"]*)"', body))


async def capture(srv, name: str, message: str) -> dict:
    t0 = time.time()
    events = []
    resp = await srv.chat(srv.ChatIn(message=message))
    buf = ""
    async for chunk in resp.body_iterator:
        buf += chunk if isinstance(chunk, str) else chunk.decode()
        while "\n\n" in buf:
            frame, buf = buf.split("\n\n", 1)
            if frame.startswith("data: "):
                events.append({"t": round(time.time() - t0, 2), "event": json.loads(frame[6:])})
    rec = {"name": name, "message": message, "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": round(time.time() - t0, 1),
           "method": "in-process read of the /api/chat StreamingResponse; t = seconds from the request to each frame",
           "events": events, "errors": [e["event"] for e in events if e["event"]["type"] == "error"],
           "answered": any(e["event"]["type"] == "text" and e["event"].get("author") == "desk_orchestrator" for e in events),
           "pending": [e["event"]["action"]["id"] for e in events if e["event"]["type"] == "pending_action"],
           "audits": {e["event"]["action_id"]: e["event"]["verdict"] for e in events if e["event"]["type"] == "audit"}}
    json.dump(rec, open(os.path.join(OUT, f"{name}.json"), "w"), indent=1, default=str, ensure_ascii=False)
    first = next((e["t"] for e in events if e["event"]["type"] == "tool_call"), None)
    print(f"{name}: {rec['seconds']} s, {len(events)} events, first tool call at {first} s, answered={rec['answered']}, "
          f"pending={rec['pending']}, audits={rec['audits']}, errors={[e['error'][:120] for e in rec['errors']]}", flush=True)
    return rec


async def main(which: list[str]) -> None:
    import server.app as srv

    os.makedirs(OUT, exist_ok=True)
    sc = {s["id"]: s["prompt"] for s in srv.SCENARIOS}
    jobs = {"swarm_S1": sc["S1"], "persona_risk_S3": sc["S3"], "handover": handover_prompt()}
    for name in which or list(jobs):
        await capture(srv, name, jobs[name])
    json.dump(srv.list_actions(), open(os.path.join(OUT, "actions_after.json"), "w"), indent=1, default=str)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main(sys.argv[1:]))
