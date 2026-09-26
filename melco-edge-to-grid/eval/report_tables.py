"""Print markdown tables for docs/EVAL_REPORT.md from eval/results/*.json (no numbers are typed by hand)."""
from __future__ import annotations

import json
import os

RES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")


def load(name):
    p = os.path.join(RES, name)
    return json.load(open(p)) if os.path.exists(p) else None


def fmt(v):
    return "n/a" if v is None else (f"{v:.2f}" if isinstance(v, float) else str(v))


def adk():
    s = load("adk_summary.json")
    if not s:
        print("no ADK summary")
        return
    print("| Set | Case | First attempt | Retry | Classification | Trajectory | Rubric | Hallucination | Latency s | Tokens |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for cid, c in s["cases"].items():
        m = c["metrics_first"]
        info = c.get("info_first", {})
        print(f"| {c['set']} | `{cid}` | {c['first_attempt']} | {c['retry'] or ''} | {c['classification']} | "
              f"{fmt(m.get('tool_trajectory_avg_score', {}).get('score'))} | {fmt(m.get('rubric_based_final_response_quality_v1', {}).get('score'))} | "
              f"{fmt(m.get('hallucinations_v1', {}).get('score'))} | {fmt(info.get('invocation_duration_v1'))} | {fmt(info.get('token_usage_v1'))} |")
    cases = list(s["cases"].values())
    print(f"\nTotal {len(cases)}; first-attempt pass {sum(c['first_attempt'] == 'PASSED' for c in cases)}; "
          f"pass after one retry {sum(c['final'] != 'FAILED' for c in cases)}; persistent failures {[k for k, c in s['cases'].items() if c['final'] == 'FAILED']}")
    print("Set wall times:", {k: v["wall_s"] for k, v in s["sets"].items()}, "infra errors:", {k: v["infra_error"] for k, v in s["sets"].items() if v["infra_error"]})


def grounding():
    g = load("grounding_results.json")
    if not g:
        print("no grounding results")
        return
    print("| Probe | First attempt | Final | Classification | Checks (figure: matched) | Latency s | Tool calls |")
    print("|---|---|---|---|---|---|---|")
    for p in g["probes"]:
        f = p.get("first", {})
        checks = "; ".join(f"{c['figure']} = {c['truth']}: {'yes' if c['matched'] else 'NO'}" for c in f.get("checks", []))
        print(f"| `{p['id']}` | {f.get('label', '')} | {p['label']} | {p.get('classification', '')} | {checks} | {f.get('latency_s', '')} | {len(f.get('tool_names', []))} |")
    print("\nSummary:", g.get("summary"))


def safety():
    s = load("safety_results.json")
    if not s:
        print("no safety results")
        return
    print("| Probe | Category | First attempt | Final | Classification | Failed checks (first attempt) | Pending kinds | Latency s |")
    print("|---|---|---|---|---|---|---|---|")
    for p in s["probes"]:
        f = p["first"]
        bad = [k for k, v in f["checks"].items() if not v]
        print(f"| `{p['id']}` | {p['category']} | {'PASS' if f['passed'] else 'FAIL'} | {'PASS' if p['passed'] else 'FAIL'} | {p['classification']} | "
              f"{', '.join(bad) or 'none'} | {', '.join(x for x in f.get('pending_kinds', []) if x) or 'none'} | {f['latency_s']} |")
    print("\nSummary:", s.get("summary"), "Static:", s.get("static"))


if __name__ == "__main__":
    adk()
    print()
    grounding()
    print()
    safety()
