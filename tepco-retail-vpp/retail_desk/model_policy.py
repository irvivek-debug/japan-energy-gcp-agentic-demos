"""Single source of model IDs and model construction (env-overridable). Never hardcode model IDs elsewhere.

Gemini 3.x resolves only at the `global` location, while Agent Runtime (formerly Vertex AI Agent Engine) runs in
asia-northeast1 and reserves GOOGLE_CLOUD_LOCATION. So on Vertex the model client location is pinned explicitly with
MODEL_LOCATION (default global) via ADK's Gemini(client_kwargs=...). Construction is lazy: no network on import.
"""
from __future__ import annotations

import os
from typing import Any

REASONING_ID = os.getenv("MODEL_REASONING", "gemini-3.1-pro-preview")  # Pattern A orchestrator
BALANCED_ID = os.getenv("MODEL_BALANCED", "gemini-3.6-flash")  # specialists, auditor, eval judge
FAST_ID = os.getenv("MODEL_FAST", "gemini-3.5-flash-lite")  # cheap summarisation / classification


def llm(model_id: str) -> Any:
    if os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").upper() not in ("TRUE", "1"):
        return model_id  # API-key mode or tests: plain model string
    from google.adk.models import Gemini
    from google.genai import types

    return Gemini(model=model_id, client_kwargs={"location": os.getenv("MODEL_LOCATION", "global")},
                  retry_options=types.HttpRetryOptions(attempts=4, initial_delay=2.0, max_delay=30.0))


REASONING = llm(REASONING_ID)
BALANCED = llm(BALANCED_ID)
FAST = llm(FAST_ID)
