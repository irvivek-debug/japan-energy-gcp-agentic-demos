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
            out.append("\n  Diagnosis (from the stored responses; the judge reports a score, not a verdict per rubric): trajectory "
                       "1.0 and hallucinations 1.0 on both attempts, and the figures are correct (train -8,800.4 to -2,159.0, "
                       "holdout delta 21,190.9 JPY M, local controller). The mechanism list quotes price-book constants from the "
                       "diff (0.620 JPY/kWh, 26.0 JPY/kW-month, 72%) without a bracketed table, which is the most likely unmet "
                       "rubric of the four ('every figure is cited'): 3 of 4 met, 0.75 < 0.8. The same case failed the same way "
                       "when it targeted run 3 (superseded record, section 5), so this is an agent habit, not a run 4 effect. "
                       "The rubric was not loosened after the fact.")
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
    out.append("\nNote: the eval sets were first built from the lab tables when 5 runs existed and rebuilt on 2026-09-27 "
               "(section 5); only the two cases whose target run changed were re-run. Trading run 3 is not referenced by any "
               "case. An earlier interim ADK attempt on `cost_stack_hv` failed its rubric (the agent "
               "computed its own differences); the agent instruction and `explain_cost_stack` were changed before this full run.")
    rr = load("rerun_2026-09-27.json")
    if rr and rr.get("status") == "LIVE RE-RUN DONE":
        out.append("\n## 5. Update 2026-09-27: new latest tariff run, affected cases re-run live\n")
        out.append(f"The pre-registered tariff run 4 (`{rr['latest_tariff_run']}`) replaced `{rr['previous_latest_tariff_run']}` "
                   "as the latest tariff run, so the eval sets were rebuilt from the lab tables and the cases that name the "
                   f"latest run were re-run live (`{rr['command']}`). The two zero-program attempts "
                   f"({', '.join('`' + x + '`' for x in rr['zero_program_attempts_not_targeted'])}) are labelled infrastructure "
                   "failures by the tools and are never the 'latest' target.\n")
        out.append("| Case | Final | Class | tool_trajectory | rubric_quality | hallucinations | Question |")
        out.append("|---|---|---|---|---|---|---|")
        for c in rr["adk_cases_rerun"]:
            m = (c.get("retry") if c["final"] == "PASSED" and c.get("retry") else c["first_attempt"])["metrics"]
            out.append(f"| {c['eval_id']} | {c['final']} | {c['classification']} | {m.get('tool_trajectory_avg_score')} | "
                       f"{m.get('rubric_based_final_response_quality_v1')} | {m.get('hallucinations_v1')} | "
                       f"{c['first_attempt']['question']} |")
        t = rr["adk_totals_after_rerun"]
        out.append(f"\n* ADK totals in section 1 include these two re-run cases: **{t['passed_final']}/{t['total']}** after one "
                   f"retry, {t['passed_first_attempt']}/{t['total']} on the first attempt. The replaced records are kept in "
                   "`adk_summary.json` under `superseded`: "
                   + "; ".join(f"`{x['eval_id']}` {x['final']} on the previous run" for x in rr["adk_cases_superseded"]) + ".")
        out.append(f"* Two invalid attempts are kept under `invalid_attempts` and not counted: "
                   + "; ".join(f"`{x['eval_id']}`: {x['why']}" for x in rr["adk_invalid_attempts_kept_not_counted"]) + ".")
        gg = rr["grounding_full_rerun"]
        out.append(f"* Grounding, full re-run: **{gg['grounded']}/{gg['total']} GROUNDED**; the retargeted probe "
                   f"`tariff_latest_holdout_delta` (truth {gg['tariff_latest_holdout_delta']['truth']}) is "
                   f"{gg['tariff_latest_holdout_delta']['final']} via {', '.join(gg['tariff_latest_holdout_delta']['tools'])}; "
                   f"tool-side errors: {gg['tool_errors']} of {gg['tool_calls']} tool calls.")
        out.append(f"* Safety eval: not re-run (no safety probe names the latest tariff run); recorded results that name earlier runs stay valid because {rr['recorded_results_still_valid_because']}.")
        errs = rr.get("finding_tool_errors_in_recorded_evals") or []
        out.append(f"\n**Finding, found while preparing the re-run:** {len(errs)} recorded probe attempts contain a tool-side error "
                   "from `get_holdout_result` (" + ", ".join(sorted({e["eval"] + ":" + e["probe"] for e in errs})) + "). "
                   f"{rr['finding_explanation']} The grounding and safety graders judge the final answer, so these probes passed "
                   "with a broken tool; the evidence recorded the errors, but no check failed on them. A happy-path test now "
                   "calls every tool on the committed tables, and the mutation check includes this bug. The safety records "
                   "above predate the fix and still show the error.")
        closed = rr.get("gap_closed_by")
        out.append(f"\n**Gap found by the re-run{' (closed the same day, section 6)' if closed else ' (not fixed)'}:** "
                   + (rr['gap_found_by_rerun'].replace(" Not fixed here (it would change the agent after its evals); listed as a gap.", "")
                      if closed else rr['gap_found_by_rerun']))
    elif rr:
        out.append("\n## 5. Update 2026-09-27\n")
        out.append(f"Re-run status: {rr.get('status')}. See eval/results/rerun_2026-09-27.json.")
    cf = load("caveat_followup_2026-09-27.json")
    if cf:
        out.append("\n## 6. Follow-up 2026-09-27: the sampling-margin caveat is carried as data\n")
        rel = "; ".join(f"{x['segment']} (n={x['n']}) rise {x['rise'] * 100:+.1f} pp vs {x['point_rise_limit'] * 100:.1f} pp point "
                        f"limit, {x['margin_rise_limit'] * 100:.1f} pp margin limit" for x in cf["champion_relies_on_margin"])
        out.append("The gap in section 5 is closed through data, not agent wording (the agent instruction is unchanged). "
                   "`energy_lab/segment_judgments.py` re-executes every saved top-k program of the run in the sandbox on train "
                   "and on holdout3 (no model call) and judges each segment under the v3 point rules and the v4 margin rules. "
                   f"The result (`{cf['judgment_file']}`) is checked against the evidence before it is written "
                   f"({', '.join(k for k, v in cf['judgment_checks'].items() if v)}); the evidence file's SHA-256 is recorded "
                   "and no evidence file changed. `energy_lab.export_evidence` exports it as `lab_segment_judgments` (both schema "
                   "files identical) and derives `lab_holdout.judgment_note`, `lab_holdout.relies_on_margin`, "
                   "`lab_holdout.valid_point_rules`, `lab_runs.uplift_caveat` and a `CAVEAT:` suffix on `lab_runs.uplift_note`. "
                   "`list_runs`, `get_run_summary`, `get_best_program_diff` and `get_holdout_result` return the caveat; "
                   f"`get_holdout_result` also returns the champion's margin-dependent segments. Champion: {rel}.\n")
        out.append("| Live check | Final | Class | tool_trajectory | rubric_quality | hallucinations | Mentions the margin |")
        out.append("|---|---|---|---|---|---|---|")
        for c in cf["adk_cases"]:
            a = c["attempts"][-1] if c["final"] == "PASSED" and len(c["attempts"]) > 1 else c["attempts"][0]
            m = a["metrics"]
            out.append(f"| ADK `{c['eval_id']}` | {c['final']} | {c['classification']} | {m.get('tool_trajectory_avg_score')} | "
                       f"{m.get('rubric_based_final_response_quality_v1')} | {m.get('hallucinations_v1')} | "
                       f"{' / '.join('yes' if x['mentions_sampling_margin'] else 'NO' for x in c['attempts'])} |")
        gp = cf["grounding_probe"]
        out.append(f"| Grounding `{gp['id']}`: \"{gp['question']}\" | {gp['final']} | {gp['classification']} | tools: "
                   f"{', '.join(gp['tools'])} | truth {gp['truth']} | terms required: {', '.join(gp['require_terms'])} | "
                   f"{'yes' if gp['final'] == 'GROUNDED' else 'NO'} |")
        gt, at, mu = cf["grounding_total"], cf["adk_totals"], cf["mutations"]
        out.append(f"\n* Grounding totals after the re-run: {gt['grounded']}/{gt['total']} GROUNDED, {gt['tool_errors']} tool-side "
                   f"errors. ADK totals: {at['passed_final']}/{at['total']} after one retry, {at['passed_first_attempt']}/{at['total']} "
                   "first attempt; `best_diff_tariff_latest` still fails its rubric at 0.75 on both attempts (section 1 diagnosis), "
                   "now while stating the caveat.")
        out.append(f"* Tests: `tests/test_segment_judgments.py` (caveat present for run 4 and absent for every trading run in "
                   "all four tools; derived from the recomputed table, agrees with the pre-registered secondary analysis; "
                   "recomputation is identical and the evidence hash unchanged; exported table equals the judgment file). "
                   f"Mutation check: {mu['detected']}/{mu['total']} gates detected, including the three new ones.")
        out.append(f"* Command: `{cf['command']}`.")
    out.append("\n## 7. Skipped / not covered\n")
    out.append("* Agent Runtime (deployed) path: not exercised here (no deployment by demo builders); the same agent object is "
               "evaluated in-process.\n* BigQuery backend: not exercised live; DuckDB-over-CSV runs the identical SQL.")
    (ROOT / "docs" / "EVAL_REPORT.md").write_text("\n".join(out) + "\n")
    print("wrote docs/EVAL_REPORT.md")


if __name__ == "__main__":
    main()
