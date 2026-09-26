"""The AlphaEvolve evaluator contract.

The platform calls ``evaluate(candidate)`` with the program source at
``candidate["content"]["files"][0]["content"]`` and expects::

    {"scores": {"scores": [{"metric": M, "score": float | None}]},
     "insights": {"insights": [{"label": ..., "text": ...}]}}

``None`` marks an invalid candidate. Internally an evaluator may use ``-inf``; it is mapped to
``None`` here, at the boundary. Higher is better. Insight text is what the next generation learns
from, so it must say *why* (sandbox error, infeasibility detail, policy violation).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

PRIMARY_METRIC = "score"

# Invalid-candidate categories, used by evidence files and the UI "invariant catches" panel.
KIND_OK = "ok"
KIND_POLICY = "policy"          # a declared policy invariant was violated
KIND_SANDBOX = "sandbox"        # denied operation, crash, timeout, memory
KIND_STATIC = "static"          # AST scan rejected the EVOLVE-BLOCK before execution
KIND_FORMAT = "format"          # output shape / range / type errors
KIND_DIFF = "diff"              # the model's SEARCH/REPLACE could not be applied
KIND_SCAFFOLD = "scaffold"      # code outside the EVOLVE-BLOCK changed
KIND_DETERMINISM = "determinism"
KIND_INSTANCE = "instance"      # frozen instance hash mismatch (look-ahead / tamper guard)


def clean_score(x: Any) -> float | None:
    """Map -inf / nan / non-numeric to None; round to 1e-6 (scores are JPY M, so 1 JPY)."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return round(f, 6)


@dataclass
class EvalOutcome:
    """Rich evaluation result used inside the harness; ``to_contract()`` is what the platform sees."""

    score: float | None
    kind: str = KIND_OK
    insights: list[tuple[str, str]] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)      # components (JPY M etc.)
    details: dict[str, Any] = field(default_factory=dict)        # violations, descriptors, timings
    raw_score: float | None = None                               # objective before the policy gate

    @property
    def valid(self) -> bool:
        return self.score is not None

    def to_contract(self, metric: str = PRIMARY_METRIC) -> dict:
        ins = [{"label": str(l), "text": str(t)[:2000]} for l, t in self.insights]
        return {"scores": {"scores": [{"metric": metric, "score": clean_score(self.score)}]},
                "insights": {"insights": ins}}

    def to_record(self) -> dict:
        return {"score": clean_score(self.score), "raw_score": clean_score(self.raw_score), "kind": self.kind,
                "valid": self.valid, "insights": [{"label": l, "text": t} for l, t in self.insights],
                "metrics": {k: clean_score(v) for k, v in self.metrics.items()}, "details": self.details}


def invalid(kind: str, label: str, text: str, **details: Any) -> EvalOutcome:
    return EvalOutcome(score=None, kind=kind, insights=[(label, text)], details=dict(details))


def validate_contract(d: dict) -> None:
    """Raise AssertionError if ``d`` is not a well-formed contract dict (used by tests and the adapter)."""
    assert isinstance(d, dict) and set(d) >= {"scores", "insights"}, "missing top-level keys"
    scores = d["scores"]["scores"]
    assert isinstance(scores, list) and scores, "scores must be a non-empty list"
    for s in scores:
        assert set(s) >= {"metric", "score"}
        assert s["score"] is None or (isinstance(s["score"], float) and math.isfinite(s["score"])), s
    for i in d["insights"]["insights"]:
        assert set(i) >= {"label", "text"} and isinstance(i["text"], str)


def primary_score(d: dict) -> float | None:
    return d["scores"]["scores"][0]["score"]
