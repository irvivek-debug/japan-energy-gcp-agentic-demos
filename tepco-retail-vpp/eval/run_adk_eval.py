"""Run every ADK eval set with AgentEvaluator (tool trajectory, rubric-based quality, hallucinations; judge = balanced
tier), retry each failing case once, classify transient vs persistent, and write evidence to eval/results/.

Usage (from the demo root, with GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=...):
  python eval/run_adk_eval.py                 # all sets
  python eval/run_adk_eval.py e2e             # one set: e2e | specialists | auditor
Outputs: eval/results/adk_<set>_<file>.csv (per-invocation metric rows, first attempt), *_retry.csv, adk_summary.json
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL = os.path.join(ROOT, "eval")
RES = os.path.join(EVAL, "results")
sys.path.insert(0, ROOT)
sys.path.insert(0, EVAL)

from google.adk.evaluation.agent_evaluator import AgentEvaluator  # noqa: E402

SCORED = ("tool_trajectory_avg_score", "rubric_based_final_response_quality_v1", "hallucinations_v1")  # pass/fail criteria

SETS = {
    # set: (agent_module, {file: agent_name or None})
    "e2e": ("retail_desk", {"e2e.test.json": None}),
    "specialists": ("specialist_bench", {"trading.test.json": "trading_dispatch_agent", "contract_risk.test.json": "contract_risk_agent",
                                         "onboarding.test.json": "onboarding_agent", "cfe.test.json": "cfe_provenance_agent"}),
    "auditor": ("specialist_bench", {"auditor.test.json": "risk_auditor"}),
}


def _rows(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


async def _run(module: str, test_file: str, agent_name: str | None, out_csv: str) -> str | None:
    if os.path.exists(out_csv):
        os.remove(out_csv)
    try:
        await AgentEvaluator.evaluate(agent_module=module, eval_dataset_file_path_or_dir=test_file, agent_name=agent_name,
                                      num_runs=1, output_file=out_csv, print_detailed_results=False)
        return None
    except AssertionError as e:  # AgentEvaluator raises on any failed metric; keep going
        return str(e)[:2000]
    except Exception as e:  # infrastructure error: record, do not hide
        return f"{type(e).__name__}: {str(e)[:2000]}"


def _by_case(rows: list[dict]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rows:
        c = out.setdefault(r["eval_id"], {"metrics": {}, "prompt": r.get("prompt"), "actual_response": r.get("actual_response"),
                                          "actual_tool_calls": r.get("actual_tool_calls"), "expected_tool_calls": r.get("expected_tool_calls")})
        c["metrics"][r["metric_name"]] = {"score": r["score"], "status": r["eval_status"], "threshold": r["threshold"]}
    for c in out.values():
        scored = {k: m for k, m in c["metrics"].items() if k in SCORED}
        c["passed"] = len(scored) == len(SCORED) and all(m["status"] == "PASSED" for m in scored.values())
        c["info"] = {k: m["score"] for k, m in c["metrics"].items() if k not in SCORED}  # ADK 2.10 informational metrics
    return out


async def main(selected: list[str]) -> None:
    os.makedirs(RES, exist_ok=True)
    summary_path = os.path.join(RES, "adk_summary.json")
    summary = json.load(open(summary_path)) if os.path.exists(summary_path) else {}
    for set_name in selected:
        module, files = SETS[set_name]
        for fname, agent_name in files.items():
            path = os.path.join(EVAL, "evalsets", set_name, fname)
            spec = json.load(open(path))
            stem = f"adk_{set_name}_{fname.replace('.test.json', '')}"
            t0 = time.time()
            err1 = await _run(module, path, agent_name, os.path.join(RES, f"{stem}.csv"))
            first = _by_case(_rows(os.path.join(RES, f"{stem}.csv")))
            dur1 = round(time.time() - t0, 1)
            missing = [c["eval_id"] for c in spec["eval_cases"] if c["eval_id"] not in first]
            failing = [cid for cid, c in first.items() if not c["passed"]] + missing
            retry, dur2, err2 = {}, 0.0, None
            if failing:
                tmp = os.path.join(EVAL, "evalsets", set_name, f"_retry_{fname}")
                json.dump({**spec, "eval_set_id": spec["eval_set_id"] + "_retry",
                           "eval_cases": [c for c in spec["eval_cases"] if c["eval_id"] in failing]}, open(tmp, "w"), ensure_ascii=False)
                t1 = time.time()
                err2 = await _run(module, tmp, agent_name, os.path.join(RES, f"{stem}_retry.csv"))
                dur2 = round(time.time() - t1, 1)
                os.remove(tmp)
                retry = _by_case(_rows(os.path.join(RES, f"{stem}_retry.csv")))
            cases = {}
            for c in spec["eval_cases"]:
                cid = c["eval_id"]
                f = first.get(cid)
                r = retry.get(cid)
                if f and f["passed"]:
                    cls = "pass"
                elif r and r["passed"]:
                    cls = "transient"
                elif r or f:
                    cls = "persistent"
                else:
                    cls = "not_run"
                cases[cid] = {"classification": cls, "first_attempt": f, "retry": r}
            summary[f"{set_name}/{fname}"] = {
                "agent_module": module, "agent_name": agent_name or "desk_orchestrator", "cases": cases,
                "passed_first_attempt": sum(1 for v in cases.values() if v["classification"] == "pass"),
                "passed_after_retry": sum(1 for v in cases.values() if v["classification"] in ("pass", "transient")),
                "total": len(cases), "first_error": err1, "retry_error": err2, "seconds": dur1 + dur2,
                "run_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            }
            json.dump(summary, open(summary_path, "w"), indent=1, default=str)
            s = summary[f"{set_name}/{fname}"]
            print(f"{set_name}/{fname}: first {s['passed_first_attempt']}/{s['total']}, after retry {s['passed_after_retry']}/{s['total']} "
                  f"({s['seconds']} s)", flush=True)
            for cid, v in cases.items():
                mets = {k[:20]: m["status"][0] + ":" + str(m["score"])[:4] for k, m in (v["first_attempt"] or {}).get("metrics", {}).items() if k in SCORED}
                print(f"   {cid:36} {v['classification']:10} {mets}", flush=True)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or list(SETS)))
