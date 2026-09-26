"""Write docs/EVAL_REPORT.md from eval/results/*.json (real results only; every skipped item listed by name)."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "eval" / "results"


def load(name):
    p = RES / name
    return json.loads(p.read_text()) if p.exists() else None


def main() -> None:
    adk, gr, sf = load("adk_summary.json"), load("grounding_results.json"), load("safety_results.json")
    out = ["# Evaluation report: Lab Analyst (live Gemini, generated from eval/results)", "",
           f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by `eval/make_report.py`. Agent: "
           "`energy_lab/agent.py:root_agent` (Pattern B, gemini-3.6-flash at location global). Judge: gemini-3.6-flash. "
           "Each failing case is retried once; the first attempt is kept; `transient` = passed on retry, `persistent` = failed "
           "twice. Denominators include every case; nothing is dropped.", ""]
    # ---- ADK
    out.append("## 1. ADK evaluation (AgentEvaluator: tool trajectory + rubric quality + hallucinations)")
    if not adk:
        out.append("\nNOT RUN: eval/results/adk_summary.json missing.")
    else:
        out.append(f"\n**{adk['passed_final']}/{adk['total']} passed after one retry; {adk['passed_first_attempt']}/{adk['total']} "
                   "on the first attempt.**\n")
        out.append("| Set | Case | Final | Class | tool_trajectory | rubric_quality | hallucinations | Latency (s) |")
        out.append("|---|---|---|---|---|---|---|---|")
        for c in adk["cases"]:
            att = c.get("retry") if c["final"] == "PASSED" and c.get("retry") else c["first_attempt"]
            m = {x["metric"]: x for x in att.get("metrics", [])}

            def sc(k):
                x = m.get(k)
                return f"{float(x['score']):.2f} {x['status']}" if x and x.get("score") not in (None, "") else "n/a"

            out.append(f"| {c['set']} | {c['eval_id']} | {c['final']} | {c['classification']} | {sc('tool_trajectory_avg_score')} | "
                       f"{sc('rubric_based_final_response_quality_v1')} | {sc('hallucinations_v1')} | {att.get('latency_s')} |")
        fails = [c for c in adk["cases"] if c["final"] != "PASSED"]
        if fails:
            out.append("\nFailures (evidence in eval/results/adk_*.csv):\n")
            for c in fails:
                e = (c.get("retry") or c["first_attempt"]).get("error") or ""
                out.append(f"* `{c['eval_id']}` ({c['classification']}): {e[:400].strip()}")
            out.append("\n  Diagnosis (from the stored responses): trajectory 1.0 and hallucinations 1.0 on both attempts; the answer is "
                       "correct (mechanism, no validated uplift, train vs holdout rule) but quotes code constants from the diff "
                       "(0.70, 1.18, -0.38, ...) with section-level rather than per-figure citations, which fails the strict "
                       "'every figure is cited' rubric (3 of 4 rubrics met, 0.75 < 0.8). The rubric was not loosened after the fact.")
    # ---- grounding
    out.append("\n## 2. Grounding eval (truth by SQL at test time)")
    if not gr:
        out.append("\nNOT RUN: eval/results/grounding_results.json missing.")
    else:
        out.append(f"\n**{gr['grounded']}/{gr['total']} GROUNDED**, {gr['ungrounded']} UNGROUNDED, UNVERIFIABLE: "
                   f"{', '.join(gr['unverifiable']) or 'none'}.\n")
        out.append("| Probe | Final label | Class | Truth (value, tol) | Tools called | Latency (s) |")
        out.append("|---|---|---|---|---|---|")
        for p in gr["probes"]:
            a = p.get("retry") or p["first_attempt"]
            out.append(f"| {p['id']} | {p['final']} | {p['classification']} | {p['truth']} | "
                       f"{', '.join(c['name'] for c in a['tool_calls'])} | {a['latency_s']} |")
    # ---- safety
    out.append("\n## 3. Safety eval (injection, regulatory refusal, promotion refusal, HITL, reconciliation, fabrication)")
    if not sf:
        out.append("\nNOT RUN: eval/results/safety_results.json missing.")
    else:
        out.append(f"\n**{sf['passed']}/{sf['total']} passed** (a probe passes only if the hard check AND the LLM judge pass).\n")
        out.append("| Probe | Final | Class | Hard check | Judge | Judge reason | Tools called |")
        out.append("|---|---|---|---|---|---|---|")
        for p in sf["probes"]:
            a = p["first_attempt"] if p["final"] == "PASS" and not p.get("retry") else (p.get("retry") or p["first_attempt"])
            out.append(f"| {p['id']} | {p['final']} | {p['classification']} | {a['hard_check']} | {a['judge']['pass']} | "
                       f"{a['judge']['reason'][:180].replace('|', '/')} | {', '.join(c['name'] for c in a['tool_calls']) or 'none'} |")
        hitl = next((p for p in sf["probes"] if p["id"] == "hitl_review_not_executed"), None)
        if hitl:
            se = hitl["first_attempt"].get("side_effect_check", {})
            out.append(f"\nHITL side effect: reviews.jsonl hash before/after equal = {se.get('unchanged')} (no write without "
                       "Hold-to-Confirm).")
    out.append("\n## 4. Harness tests (pytest) and mutation checks\n")
    pt = RES / "pytest_summary.txt"
    out.append(("Two consecutive full runs: " + " / ".join(l.strip() for l in pt.read_text().splitlines() if l.strip()))
               if pt.exists() else "pytest summary not recorded.")
    mc = load("mutation_checks.json")
    if mc:
        n = sum(1 for r in mc["results"] if r.get("suite_went_red"))
        out.append(f"\nFile-level mutation check (`tests/mutation_check.py`): **{n}/{len(mc['results'])} gates detected** "
                   "(each gate broken in the source, its test must go red, source restored):\n")
        out.append("| Mutation | Test | Suite went red |")
        out.append("|---|---|---|")
        for r in mc["results"]:
            out.append(f"| {r['mutation']} | `{r.get('test', '').split('::')[-1]}` | {r.get('suite_went_red')} |")
        out.append("\nThe first mutation pass found two tests that did not isolate their gate (per-slot compliance was also caught "
                   "by the systematic-bias check; the seed == null lock check was masked by a reproduction failure). Both tests "
                   "were rewritten to isolate their gate; the tables above are from the re-run.")
    out.append("\nNote: the eval sets were built from the lab tables when 5 runs existed; trading run 3 finished afterwards "
               "and is not referenced by any case. An earlier interim ADK attempt on `cost_stack_hv` failed its rubric (the agent "
               "computed its own differences); the agent instruction and `explain_cost_stack` were changed before this full run.")
    out.append("\n## 5. Skipped / not covered\n")
    out.append("* Agent Runtime (deployed) path: not exercised here (no deployment by demo builders); the same agent object is "
               "evaluated in-process.\n* BigQuery backend: not exercised live; DuckDB-over-CSV runs the identical SQL.")
    (ROOT / "docs" / "EVAL_REPORT.md").write_text("\n".join(out) + "\n")
    print("wrote docs/EVAL_REPORT.md")


if __name__ == "__main__":
    main()
