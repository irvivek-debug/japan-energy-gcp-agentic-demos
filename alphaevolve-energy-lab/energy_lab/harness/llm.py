"""Mutators: the live Gemini mutator (Vertex AI, location global) and a deterministic dry-run mutator.

The Gemini client reads GOOGLE_GENAI_USE_VERTEXAI / GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION from the
environment (ADC). Nothing identifying the project is written to disk. Token usage and an estimated
cost (see model_policy.PRICING_NOTE) are returned with every call for the evidence file.
"""
from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass

from .. import model_policy


@dataclass
class Generation:
    text: str
    model: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    latency_s: float = 0.0
    cost_usd: float = 0.0
    error: str | None = None
    attempts: int = 1


class GenerationUnavailable(RuntimeError):
    """The mutator cannot generate at all (e.g. credentials need re-authentication). Raised before a run starts."""


class GeminiMutator:
    kind = "gemini"

    def preflight(self) -> None:
        """Refresh Application Default Credentials without spending a model call; refuse early if they are unusable.

        Run tariff_pricing.20260927T081840Z spent its whole 40-program budget on RefreshError in 5 s; this check (and the
        controller's consecutive-failure breaker) makes that impossible."""
        import os

        missing = [k for k, want in (("GOOGLE_GENAI_USE_VERTEXAI", "TRUE"), ("GOOGLE_CLOUD_LOCATION", "global"),
                                     ("GOOGLE_CLOUD_PROJECT", None))
                   if not os.getenv(k) or (want and os.getenv(k, "").upper() != want.upper())]
        if missing:   # without these the client silently tries the API-key path (operator error 2026-09-27)
            raise GenerationUnavailable("Vertex AI configuration missing or wrong: " + ", ".join(missing)
                                        + " (need GOOGLE_GENAI_USE_VERTEXAI=TRUE, GOOGLE_CLOUD_LOCATION=global, GOOGLE_CLOUD_PROJECT)")
        try:
            import google.auth
            from google.auth.transport.requests import Request

            creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            creds.refresh(Request())
        except Exception as e:  # noqa: BLE001
            raise GenerationUnavailable(f"model credentials unusable: {type(e).__name__}: {str(e)[:200]}") from None

    def __init__(self, temperature: float = 1.0, max_output_tokens: int = 24576, timeout_s: float = 240.0,
                 thinking_level: str | None = None):
        import os
        from google.genai import types

        self._types = types
        self._timeout_ms = int(timeout_s * 1000)
        self._client = None          # created on first use, so budget / baseline refusals need no credentials
        import threading

        self._client_lock = threading.Lock()   # two worker threads must not each create (and drop) a client
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        # MEDIUM keeps a generation near 30-60 s so 40 programs fit the 30-min wall at concurrency 2
        self.thinking_level = (thinking_level or os.getenv("MUTATOR_THINKING_LEVEL", "MEDIUM")).upper()

    @property
    def client(self):
        with self._client_lock:
            if self._client is None:
                from google import genai

                self._client = genai.Client(http_options=self._types.HttpOptions(timeout=self._timeout_ms))
            return self._client

    def generate(self, model: str, system: str, prompt: str) -> Generation:
        t0 = time.monotonic()
        last_err = None
        for attempt in range(1, 4):
            try:
                cfg = self._types.GenerateContentConfig(
                    system_instruction=system, temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
                    automatic_function_calling=self._types.AutomaticFunctionCallingConfig(disable=True),
                    thinking_config=self._types.ThinkingConfig(thinking_level=self.thinking_level))
                r = self.client.models.generate_content(model=model, contents=prompt, config=cfg)
                u = r.usage_metadata
                pt = int(getattr(u, "prompt_token_count", 0) or 0)
                ot = int(getattr(u, "candidates_token_count", 0) or 0)
                tt = int(getattr(u, "thoughts_token_count", 0) or 0)
                return Generation(text=r.text or "", model=model, prompt_tokens=pt, output_tokens=ot,
                                  thinking_tokens=tt, latency_s=round(time.monotonic() - t0, 2),
                                  cost_usd=model_policy.estimate_cost_usd(model, pt, ot + tt), attempts=attempt)
            except Exception as e:  # noqa: BLE001  classify: retry transient, surface persistent
                last_err = f"{type(e).__name__}: {str(e)[:300]}"
                transient = any(s in str(e) for s in ("429", "503", "500", "RESOURCE_EXHAUSTED", "UNAVAILABLE",
                                                      "DEADLINE", "timed out", "Timeout"))
                if not transient or attempt == 3:
                    break
                time.sleep(4 * attempt)
        return Generation(text="", model=model, latency_s=round(time.monotonic() - t0, 2), error=last_err,
                          attempts=attempt)


class DryRunMutator:
    """Deterministic, offline mutator for tests and harness smoke runs.

    It nudges one numeric literal in the EVOLVE-BLOCK per call and emits a proper SEARCH/REPLACE hunk.
    Runs driven by it are recorded with source ``local-dry-run-mutator`` and can never count as evidence.
    """

    kind = "dry_run"

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def generate(self, model: str, system: str, prompt: str) -> Generation:
        m = re.search(r"<current_block>\n(.*?)</current_block>", prompt, re.S)
        block = m.group(1) if m else ""
        lines = block.split("\n")
        cands = [i for i, ln in enumerate(lines) if re.search(r"=\s*-?\d+\.\d+", ln) and not ln.strip().startswith("#")]
        if not cands:
            return Generation(text="no change", model=f"dry-run:{model}")
        i = self.rng.choice(cands)
        old = lines[i]

        def bump(mm: re.Match) -> str:
            v = float(mm.group(1))
            return f"= {round(v * self.rng.choice([0.8, 0.9, 1.1, 1.25]), 4)}"

        new = re.sub(r"=\s*(-?\d+\.\d+)", bump, old, count=1)
        text = f"Adjusting a constant.\n<<<<<<< SEARCH\n{old}\n=======\n{new}\n>>>>>>> REPLACE\n"
        return Generation(text=text, model=f"dry-run:{model}")
