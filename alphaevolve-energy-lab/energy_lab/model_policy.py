"""Single source of model ids for this demo (env-overridable). Never hardcode model ids elsewhere.

Tiers follow docs/CONVENTIONS.md section 1. Gemini 3.x resolves only at location `global`.
The evolutionary mutator mix mirrors the AlphaEvolve generation_settings default:
balanced 0.7 / reasoning 0.3.

Token prices are PLANNING ASSUMPTIONS for cost accounting in evidence files, not quoted list prices.
Override them with env vars when the current Vertex AI price list is confirmed.
"""
from __future__ import annotations

import os

MODEL_REASONING = os.getenv("MODEL_REASONING", "gemini-3.1-pro-preview")
MODEL_BALANCED = os.getenv("MODEL_BALANCED", "gemini-3.6-flash")
MODEL_FAST = os.getenv("MODEL_FAST", "gemini-3.5-flash-lite")

# Agent tier for the Lab Analyst (Pattern B single agent) and the eval judge.
ANALYST_MODEL = MODEL_BALANCED
JUDGE_MODEL = MODEL_BALANCED


def mutator_mix() -> list[dict]:
    """Weighted model mix for candidate generation (same shape as AlphaEvolve generation_settings.models)."""
    w_bal = float(os.getenv("MUTATOR_WEIGHT_BALANCED", "0.7"))
    return [{"name": MODEL_BALANCED, "weight": w_bal}, {"name": MODEL_REASONING, "weight": round(1.0 - w_bal, 6)}]


# USD per 1M tokens (input, output incl. thinking). ASSUMPTION: verify against the live price list.
_PRICE_DEFAULTS = {
    "balanced": (float(os.getenv("PRICE_BALANCED_IN", "0.50")), float(os.getenv("PRICE_BALANCED_OUT", "3.00"))),
    "reasoning": (float(os.getenv("PRICE_REASONING_IN", "2.00")), float(os.getenv("PRICE_REASONING_OUT", "12.00"))),
    "fast": (float(os.getenv("PRICE_FAST_IN", "0.10")), float(os.getenv("PRICE_FAST_OUT", "0.40"))),
}
PRICING_NOTE = ("Cost is estimated from token counts x assumed USD/1M-token prices "
                "(balanced 0.50/3.00, reasoning 2.00/12.00 unless overridden by PRICE_* env vars); "
                "not a billing figure.")


def price_per_million(model: str) -> tuple[float, float]:
    if model == MODEL_REASONING:
        return _PRICE_DEFAULTS["reasoning"]
    if model == MODEL_FAST:
        return _PRICE_DEFAULTS["fast"]
    return _PRICE_DEFAULTS["balanced"]


def estimate_cost_usd(model: str, prompt_tokens: int, output_tokens: int) -> float:
    pin, pout = price_per_million(model)
    return round(prompt_tokens / 1e6 * pin + output_tokens / 1e6 * pout, 6)
