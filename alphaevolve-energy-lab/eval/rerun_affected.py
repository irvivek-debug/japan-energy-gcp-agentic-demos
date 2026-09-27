"""Second command after the pre-registered tariff run: re-run the Lab Analyst eval cases a new latest tariff run affects.

    GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=<project> python eval/rerun_affected.py

1. refuses without usable credentials; 2. rebuilds the eval sets from the current lab tables (the "latest tariff" cases then
target the newest searched tariff run); 3. re-runs those ADK cases (retry once, transient / persistent) and merges them into
eval/results/adk_summary.json, keeping the superseded records; 4. re-runs the full grounding eval (truth by SQL at test
time); 5. regenerates docs/EVAL_REPORT.md.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
AFFECTED = ("best_diff_tariff_latest", "holdout_tariff_latest")


async def main() -> int:
    from energy_lab.harness.llm import GeminiMutator, GenerationUnavailable

    try:
        GeminiMutator().preflight()
    except GenerationUnavailable as e:
        print(f"REFUSED: {e}")
        return 2
    subprocess.run([sys.executable, str(ROOT / "eval" / "build_evalsets.py")], check=True, cwd=ROOT)
    import run_adk_eval as r

    d = ROOT / "eval" / "evalsets" / "runs"
    cases = [c for c in json.loads((d / "runs.test.json").read_text())["eval_cases"] if c["eval_id"] in AFFECTED]
    summ_p = ROOT / "eval" / "results" / "adk_summary.json"
    summ = json.loads(summ_p.read_text())
    summ.setdefault("superseded", [])
    tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")      # unique attempt suffix: never append to an old CSV
    for case in cases:
        first = await r.run_case(d, case, f"{tag}_1")
        rec = {"set": "runs", "eval_id": case["eval_id"], "first_attempt": first, "rerun_at": datetime.now(timezone.utc).isoformat()}
        if first["status"] != "PASSED":
            second = await r.run_case(d, case, f"{tag}_2")
            rec["retry"] = second
            rec["classification"] = "transient" if second["status"] == "PASSED" else "persistent"
            rec["final"] = "PASSED" if second["status"] == "PASSED" else first["status"]
        else:
            rec["classification"], rec["final"] = "clean", "PASSED"
        old = [c for c in summ["cases"] if c["eval_id"] == case["eval_id"]]
        summ["superseded"].extend(old)
        summ["cases"] = [c for c in summ["cases"] if c["eval_id"] != case["eval_id"]] + [rec]
        print(case["eval_id"], rec["final"], rec["classification"], flush=True)
    summ["passed_final"] = sum(1 for c in summ["cases"] if c["final"] == "PASSED")
    summ["passed_first_attempt"] = sum(1 for c in summ["cases"] if c["classification"] == "clean")
    summ["total"] = len(summ["cases"])
    summ_p.write_text(json.dumps(summ, indent=1))
    subprocess.run([sys.executable, str(ROOT / "eval" / "grounding_eval.py")], check=True, cwd=ROOT)
    subprocess.run([sys.executable, str(ROOT / "eval" / "make_report.py")], check=True, cwd=ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
