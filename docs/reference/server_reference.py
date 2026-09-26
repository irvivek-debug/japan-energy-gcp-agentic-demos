"""Reference FastAPI server: serves ui/, streams ADK events over SSE, owns the HITL action queue.

Pattern (copy + adapt per demo):
  * AGENT_BACKEND=local        -> ADK Runner in-process (default; also used by evals)
  * AGENT_BACKEND=agent_engine -> vertexai Agent Engine resource AGENT_ENGINE_ID (deployed swarm)
  * Agents NEVER execute write actions. propose_* tools return {"pending_action": {...}} in their result.
    The server lifts every pending_action out of the event stream into ACTIONS; the UI Hold-to-Confirm
    calls POST /api/actions/{id}/confirm, and only then the server "executes" (sandbox/simulated) and
    appends an audit record. This works identically whether the agent ran locally or on Agent Engine.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, AsyncIterator

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

APP_NAME = "demo"
app = FastAPI()
ACTIONS: dict[str, dict] = {}
AUDIT: list[dict] = []


class ChatIn(BaseModel):
    message: str
    session_id: str | None = None


def _part_events(author: str, content: Any) -> list[dict]:
    out = []
    for p in (content.parts or []) if content else []:
        if getattr(p, "function_call", None):
            out.append({"type": "tool_call", "author": author, "tool": p.function_call.name, "args": dict(p.function_call.args or {})})
        elif getattr(p, "function_response", None):
            resp = p.function_response.response or {}
            out.append({"type": "tool_result", "author": author, "tool": p.function_response.name, "result": resp})
            pa = resp.get("pending_action") if isinstance(resp, dict) else None
            if pa:
                pa = {**pa, "id": pa.get("id") or f"act-{uuid.uuid4().hex[:8]}", "status": "pending", "created": time.time()}
                ACTIONS[pa["id"]] = pa
                out.append({"type": "pending_action", "author": author, "action": pa})
        elif getattr(p, "text", None):
            out.append({"type": "text", "author": author, "text": p.text})
    return out


_runner = _session_service = None


async def _local_stream(message: str, session_id: str | None) -> AsyncIterator[dict]:
    global _runner, _session_service
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from mypkg.agent import root_agent  # <- demo package

    if _runner is None:
        _session_service = InMemorySessionService()
        _runner = Runner(agent=root_agent, app_name=APP_NAME, session_service=_session_service)
    if not session_id or not await _session_service.get_session(app_name=APP_NAME, user_id="web", session_id=session_id):
        session_id = (await _session_service.create_session(app_name=APP_NAME, user_id="web")).id
    yield {"type": "session", "session_id": session_id}
    async for ev in _runner.run_async(user_id="web", session_id=session_id,
                                      new_message=types.Content(role="user", parts=[types.Part(text=message)])):
        for e in _part_events(ev.author, ev.content):
            yield e
        if ev.is_final_response():
            yield {"type": "final", "author": ev.author}


async def _agent_engine_stream(message: str, session_id: str | None) -> AsyncIterator[dict]:
    import vertexai
    from vertexai import agent_engines
    from google.genai import types

    vertexai.init(project=os.environ["GOOGLE_CLOUD_PROJECT"], location=os.environ.get("AGENT_ENGINE_LOCATION", "asia-northeast1"))
    remote = agent_engines.get(os.environ["AGENT_ENGINE_ID"])
    if not session_id:
        session_id = (await remote.async_create_session(user_id="web"))["id"]
    yield {"type": "session", "session_id": session_id}
    async for ev in remote.async_stream_query(user_id="web", session_id=session_id, message=message):
        content = types.Content.model_validate(ev["content"]) if ev.get("content") else None
        for e in _part_events(ev.get("author", "agent"), content):
            yield e
    yield {"type": "final"}


@app.post("/api/chat")
async def chat(body: ChatIn):
    stream = _agent_engine_stream if os.getenv("AGENT_BACKEND", "local") == "agent_engine" else _local_stream

    async def sse():
        try:
            async for e in stream(body.message, body.session_id):
                yield f"data: {json.dumps(e, default=str)}\n\n"
        except Exception as exc:  # surface, never swallow
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)[:500]})}\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream")


@app.get("/api/actions")
def list_actions():
    return sorted(ACTIONS.values(), key=lambda a: a["created"], reverse=True)


@app.post("/api/actions/{aid}/{decision}")
def decide(aid: str, decision: str):
    if aid not in ACTIONS or decision not in ("confirm", "reject"):
        raise HTTPException(404)
    a = ACTIONS[aid]
    if a["status"] != "pending":
        raise HTTPException(409, "already decided")
    a["status"] = "executed_sandbox" if decision == "confirm" else "rejected"
    a["decided"] = time.time()
    AUDIT.append({"action_id": aid, "decision": decision, "at": a["decided"], "summary": a.get("summary")})
    return a


@app.get("/api/health")
def health():
    return {"ok": True, "agent_backend": os.getenv("AGENT_BACKEND", "local"), "data_backend": os.getenv("DATA_BACKEND", "local")}


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "ui"), html=True), name="ui")
