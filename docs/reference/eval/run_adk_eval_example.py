"""Verified 2026-09-26 with google-adk 2.10.0 + gemini-3.6-flash @ global: all three criteria PASSED.
Run from the demo root with GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=...
agent_module is the importable package that exposes `agent.root_agent` (package __init__ does `from . import agent`).
test_config.json must sit next to the *.test.json files. AgentEvaluator raises AssertionError on failures, so
wrap per-file calls in try/except to collect all results; output_file writes per-invocation CSV rows."""
import asyncio
from google.adk.evaluation.agent_evaluator import AgentEvaluator

asyncio.run(AgentEvaluator.evaluate(agent_module="refagent", eval_dataset_file_path_or_dir="eval/ref.test.json",
                                    num_runs=1, output_file="eval/results.csv"))
