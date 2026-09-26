"""Single source of model ids for this demo (env-overridable). Never hardcode model ids elsewhere.

Gemini 3.x resolves only at the `global` location in the demo project: run with
GOOGLE_GENAI_USE_VERTEXAI=TRUE, GOOGLE_CLOUD_LOCATION=global and GOOGLE_CLOUD_PROJECT from the environment.
"""
from __future__ import annotations

import os

REASONING = os.getenv("MODEL_REASONING", "gemini-3.1-pro-preview")   # Pattern A orchestrator
BALANCED = os.getenv("MODEL_BALANCED", "gemini-3.6-flash")          # specialists, peer auditor, eval judge
FAST = os.getenv("MODEL_FAST", "gemini-3.5-flash-lite")              # cheap summarisation / classification

TIERS = {"reasoning": REASONING, "balanced": BALANCED, "fast": FAST}


def model_for(tier: str) -> str:
    return TIERS[tier]
