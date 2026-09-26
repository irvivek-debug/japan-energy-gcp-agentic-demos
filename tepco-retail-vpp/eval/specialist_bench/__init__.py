"""Eval-only bench: each specialist cloned with identical model, instruction and tools, in chat mode, so ADK's
AgentEvaluator can run it as the root (ADK 2.10 rejects single_turn agents as a Runner root). The production
single_turn path is evaluated end to end through desk_orchestrator in eval/evalsets/e2e."""
from . import agent  # noqa: F401
