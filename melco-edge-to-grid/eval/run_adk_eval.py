"""Run every ADK eval set live on Gemini with AgentEvaluator, retry failing cases once, and summarise.

Run from the demo root:
  GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=<project> python eval/run_adk_eval.py [set ...]

Outputs (eval/results/):
  adk_<set>.csv          per-invocation, per-metric rows from the first attempt (kept as evidence)
  adk_<set>_retry.csv    rows for cases retried once
  adk_summary.json       per case: first-attempt status, retry status, classification, metric scores, wall time
Metrics (eval/test_config.json): tool_trajectory_avg_score (ANY_ORDER, names only), rubric_based_final_response_quality_v1
(shared + case rubrics), hallucinations_v1; judge = balanced tier model.
"""
from __future__ import annotations

import asyncio
import csv
import glob
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

from google.adk.evaluation.agent_evaluator import AgentEvaluator  # noqa: E402
from google.adk.evaluation.eval_config import EvalConfig  # noqa: E402
from google.adk.evaluation.eval_set import EvalSet  # noqa: E402

RES = os.path.join(ROOT, "eval", "results")
CONFIG = EvalConfig.model_validate_json(open(os.path.join(ROOT, "eval", "test_config.json")).read())


def read_rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def case_status(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        c = out.setdefault(r["eval_id"], {"metrics": {}, "status": "PASSED"})
        try:
            score = float(r["score"]) if r["score"] not in ("", "None") else None
        except ValueError:
            score = None
        if r["eval_status"] == "INFORMATIONAL":
            c.setdefault("info", {})[r["metric_name"]] = score
            continue
        c["metrics"][r["metric_name"]] = {"score": score, "status": r["eval_status"], "threshold": float(r["threshold"]) if r["threshold"] else None}
        if r["eval_status"] != "PASSED":
            c["status"] = "FAILED"
        c["actual_tool_calls"] = r.get("actual_tool_calls", "")
        c["prompt"] = r.get("prompt", "")
        c["actual_response"] = r.get("actual_response", "")
    return out


async def run_set(es: EvalSet, out_csv: str) -> tuple[float, str | None]:
    if os.path.exists(out_csv):
        os.remove(out_csv)
    t0 = time.time()
    err = None
    try:
        await AgentEvaluator.evaluate_eval_set(agent_module="factory_copilot", eval_set=es, eval_config=CONFIG, num_runs=1,
                                               print_detailed_results=False, output_file=out_csv)
    except AssertionError:
        pass  # failures are read from the CSV
    except Exception as e:  # infrastructure error: record, never hide
        err = f"{type(e).__name__}: {str(e)[:400]}"
    return time.time() - t0, err


async def main(selected: list[str]):
    os.makedirs(RES, exist_ok=True)
    summary = {"model_reasoning": os.getenv("MODEL_REASONING", "gemini-3.1-pro-preview"),
               "model_balanced": os.getenv("MODEL_BALANCED", "gemini-3.6-flash"), "sets": {}, "cases": {}}
    files = sorted(glob.glob(os.path.join(ROOT, "eval", "evalsets", "*.test.json")))
    for path in files:
        name = os.path.basename(path).replace(".test.json", "")
        if selected and name not in selected:
            continue
        es = EvalSet.model_validate_json(open(path).read())
        first_csv = os.path.join(RES, f"adk_{name}.csv")
        wall, err = await run_set(es, first_csv)
        first = case_status(read_rows(first_csv))
        failed = [c for c in es.eval_cases if first.get(c.eval_id, {}).get("status") != "PASSED"]
        retry = {}
        rwall = 0.0
        if failed:
            rs = EvalSet(eval_set_id=f"{es.eval_set_id}_retry", name=f"{es.name} retry", eval_cases=failed)
            rwall, rerr = await run_set(rs, os.path.join(RES, f"adk_{name}_retry.csv"))
            retry = case_status(read_rows(os.path.join(RES, f"adk_{name}_retry.csv")))
            err = err or rerr
        summary["sets"][name] = {"cases": len(es.eval_cases), "wall_s": round(wall, 1), "retry_wall_s": round(rwall, 1), "infra_error": err}
        for c in es.eval_cases:
            f1 = first.get(c.eval_id, {"status": "NO_RESULT", "metrics": {}})
            r1 = retry.get(c.eval_id)
            if f1["status"] == "PASSED":
                cls, final = "pass", "PASSED"
            elif r1 and r1["status"] == "PASSED":
                cls, final = "transient", "PASSED_ON_RETRY"
            else:
                cls, final = "persistent", "FAILED"
            summary["cases"][c.eval_id] = {"set": name, "first_attempt": f1["status"], "retry": r1["status"] if r1 else None,
                                           "classification": cls, "final": final, "metrics_first": f1["metrics"],
                                           "metrics_retry": r1["metrics"] if r1 else None, "prompt": f1.get("prompt", ""),
                                           "info_first": f1.get("info", {}), "tool_calls_first": f1.get("actual_tool_calls", "")[:4000]}
        print(f"[{name}] {len(es.eval_cases)} cases in {wall:.0f}s; first-attempt pass "
              f"{sum(1 for c in es.eval_cases if first.get(c.eval_id, {}).get('status') == 'PASSED')}; retried {len(failed)}; err={err}", flush=True)
        with open(os.path.join(RES, "adk_summary.json"), "w") as f:
            json.dump(summary, f, indent=1)
    cases = summary["cases"].values()
    print(json.dumps({"total": len(cases), "pass_first": sum(1 for c in cases if c["first_attempt"] == "PASSED"),
                      "pass_after_retry": sum(1 for c in cases if c["final"] != "FAILED"),
                      "persistent_fail": [k for k, c in summary["cases"].items() if c["final"] == "FAILED"]}, indent=1))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
