"""Deterministic output hygiene applied to every agent's model responses (house style: no em or en dashes)."""
from __future__ import annotations

import re
from typing import Any, Optional

_DASH_RANGE = re.compile(r"(?<=\w)\s*[–—]\s*(?=\w)")


def clean_text(text: str) -> str:
    """Replace en/em dashes: ranges such as 35–38 become 35-38; other uses become ', '."""
    text = re.sub(r"(?<=[0-9A-Za-z:])[–](?=[0-9A-Za-z])", "-", text)  # tight ranges: 17:00–17:30
    text = re.sub(r"\s+[—–]\s+", ", ", text)  # spaced dashes used as punctuation
    return text.replace("—", "-").replace("–", "-")


def sanitize_response(callback_context: Any, llm_response: Any) -> Optional[Any]:
    content = getattr(llm_response, "content", None)
    if not content or not content.parts:
        return None
    changed = False
    for p in content.parts:
        if getattr(p, "text", None) and not getattr(p, "thought", False):
            t = clean_text(p.text)
            if t != p.text:
                p.text = t
                changed = True
    return llm_response if changed else None


SPECIALISTS = {"trading_dispatch_agent", "contract_risk_agent", "onboarding_agent", "cfe_provenance_agent", "risk_auditor"}
MAX_CALLS_PER_SPECIALIST = 2
MAX_SPECIALIST_CALLS = 8


def specialist_budget(tool: Any, args: dict, tool_context: Any) -> Optional[dict]:
    """Circuit breaker on the orchestrator: bounded specialist calls per request (found by the safety eval, where an
    unbounded fan-out ran to the 500 LLM-call ceiling). Returning a dict skips the call and becomes its result."""
    name = getattr(tool, "name", "")
    if name not in SPECIALISTS:
        return None
    counts = dict(tool_context.state.get("temp:specialist_calls", {}) or {})
    counts[name] = counts.get(name, 0) + 1
    tool_context.state["temp:specialist_calls"] = counts
    if counts[name] > MAX_CALLS_PER_SPECIALIST or sum(counts.values()) > MAX_SPECIALIST_CALLS:
        return {"status": "error", "error": f"Specialist call budget reached for this request ({name} called {counts[name]} times, "
                f"{sum(counts.values())} specialist calls in total). Do not call more specialists; compose the answer from the "
                "results you already have and say what is missing."}
    return None
