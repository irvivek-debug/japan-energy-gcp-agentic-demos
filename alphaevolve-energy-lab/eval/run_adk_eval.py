"""Run ADK AgentEvaluator over every eval set (live Gemini), one case at a time, retry once, classify, keep evidence.

    GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=... python eval/run_adk_eval.py

AgentEvaluator raises AssertionError on failure, so each case runs in its own call (a single-case eval set written to a
temp dir next to a copy of test_config.json). Per-invocation CSV rows go to eval/results/adk_<set>_<case>.csv and a summary
to eval/results/adk_summary.json (first attempt kept; a failing case is retried once: pass -> transient, fail -> persistent).
"""
from __future__ import annotations

import asyncio
import csv
import json
import shutil
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
RESULTS = ROOT / "eval" / "results"
CSV_COLUMNS = ["eval_set_id", "eval_id", "metric_name", "threshold", "score", "eval_status", "prompt", "expected_response",
               "actual_response", "expected_tool_calls", "actual_tool_calls"]


async def run_case(set_dir: Path, case: dict, attempt: int) -> dict:
    from google.adk.evaluation.agent_evaluator import AgentEvaluator

    tmp = Path(tempfile.mkdtemp(prefix="adk_case_"))
    shutil.copy(set_dir / "test_config.json", tmp / "test_config.json")
    (tmp / "case.test.json").write_text(json.dumps({"eval_set_id": f"{set_dir.name}_{case['eval_id']}", "eval_cases": [case]}))
    out_csv = RESULTS / f"adk_{set_dir.name}_{case['eval_id']}_a{attempt}.csv"
    t0 = time.time()
    status, err = "PASSED", None
    try:
        await AgentEvaluator.evaluate(agent_module="energy_lab", eval_dataset_file_path_or_dir=str(tmp / "case.test.json"),
                                      num_runs=1, output_file=str(out_csv))
    except AssertionError as e:
        status, err = "FAILED", str(e)[:1500]
    except Exception as e:  # noqa: BLE001  infrastructure error: keep evidence
        status, err = "ERROR", f"{type(e).__name__}: {e}"[:1500] + traceback.format_exc()[-600:]
    metrics = []
    if out_csv.exists():
        with open(out_csv) as f:
            first = f.readline()
            f.seek(0)
            names = None if first.startswith("eval_set_id,") else CSV_COLUMNS   # ADK omits the header when appending
            for r in csv.DictReader(f, fieldnames=names):
                metrics.append({"metric": r.get("metric_name"), "score": r.get("score"), "status": r.get("eval_status"),
                                "actual_tool_calls": (r.get("actual_tool_calls") or "")[:800],
                                "actual_response": (r.get("actual_response") or "")[:2500]})
    return {"set": set_dir.name, "eval_id": case["eval_id"], "attempt": attempt, "status": status, "error": err,
            "latency_s": round(time.time() - t0, 1), "question": case["conversation"][0]["user_content"]["parts"][0]["text"],
            "metrics": metrics}


async def main() -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    summary = []
    for set_dir in sorted((ROOT / "eval" / "evalsets").iterdir()):
        if not set_dir.is_dir():
            continue
        data = json.loads(next(set_dir.glob("*.test.json")).read_text())
        for case in data["eval_cases"]:
            first = await run_case(set_dir, case, 1)
            rec = {"set": set_dir.name, "eval_id": case["eval_id"], "first_attempt": first}
            if first["status"] != "PASSED":
                second = await run_case(set_dir, case, 2)
                rec["retry"] = second
                rec["classification"] = "transient" if second["status"] == "PASSED" else "persistent"
                rec["final"] = "PASSED" if second["status"] == "PASSED" else first["status"]
            else:
                rec["classification"] = "clean"
                rec["final"] = "PASSED"
            summary.append(rec)
            print(f"{set_dir.name:8s} {case['eval_id']:28s} first={first['status']:7s} final={rec['final']:7s} "
                  f"{rec['classification']} ({first['latency_s']} s)", flush=True)
    passed = sum(1 for r in summary if r["final"] == "PASSED")
    clean = sum(1 for r in summary if r["classification"] == "clean")
    out = {"total": len(summary), "passed_final": passed, "passed_first_attempt": clean, "cases": summary}
    (RESULTS / "adk_summary.json").write_text(json.dumps(out, indent=1))
    print(f"ADK eval: {passed}/{len(summary)} passed after one retry ({clean}/{len(summary)} on first attempt)")


if __name__ == "__main__":
    asyncio.run(main())
