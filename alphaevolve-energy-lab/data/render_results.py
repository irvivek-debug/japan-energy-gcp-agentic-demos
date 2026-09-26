"""Render the evidence-derived tables and score-curve SVGs into docs/RESULTS.md (between marker comments).

    python data/render_results.py
Numbers come only from runs/*.json (finished evidence files).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "data"))

from energy_lab.harness.evidence import list_evidence  # noqa: E402
from make_figures import svg_lines  # noqa: E402

DOC = ROOT / "docs" / "RESULTS.md"
FIG = ROOT / "docs" / "figures"


def f(x, nd=1):
    return "n/a" if x is None else f"{x:,.{nd}f}"


def main() -> None:
    recs = sorted([r for r in list_evidence(include_partial=False) if r.get("status") == "finished"],
                  key=lambda r: r["started"])
    head = ("| Run | Problem | Evaluator | Seed (train) | Null raw (train) | Best train | Holdout seed | Best holdout (champion) | "
            "Holdout delta | uplift_valid | Invalid caught (by kind) | Programs | Cost (USD est.) |")
    rows = [head, "|" + "---|" * 13]
    for r in recs:
        ho = r.get("holdout") or {}
        inv = ", ".join(f"{k} {v}" for k, v in (r.get("invalid_by_kind") or {}).items()) or "none"
        rows.append(f"| `{r['run_id']}` | {r['problem']} | {(r.get('evaluator_version') or 'v1').split(':')[0].split('/')[-1]} | "
                    f"{f(r['seed']['train'])} | {f((r.get('baseline_lock') or {}).get('null_raw'))} (invalid) | "
                    f"{f((r.get('best') or {}).get('train'))} | {f(ho.get('seed'))} ({ho.get('fold', 'holdout')}) | "
                    f"{f(ho.get('best_holdout'))} | {f(ho.get('holdout_delta'))} | {r.get('uplift_valid')} | {inv} | "
                    f"{(r.get('budget') or {}).get('programs_evaluated')} | {f((r.get('tokens') or {}).get('cost_usd'), 2)} |")
    table = "\n".join(rows)
    tok = ["| Run | LLM calls | Prompt tokens | Output tokens | Thinking tokens | Flash calls | Pro calls | Wall (s) | Stopped |",
           "|---|---|---|---|---|---|---|---|---|"]
    for r in recs:
        t = r.get("tokens") or {}
        bm = t.get("by_model") or {}
        fl = sum(v["calls"] for k, v in bm.items() if "flash" in k)
        pr = sum(v["calls"] for k, v in bm.items() if "pro" in k)
        tok.append(f"| `{r['run_id']}` | {t.get('calls')} | {t.get('prompt'):,} | {t.get('output'):,} | {t.get('thinking'):,} | "
                   f"{fl} | {pr} | {(r.get('budget') or {}).get('wall_s')} | {(r.get('budget') or {}).get('stopped_reason')} |")
    tot_cost = sum((r.get("tokens") or {}).get("cost_usd", 0) or 0 for r in recs)
    tot_calls = sum((r.get("tokens") or {}).get("calls", 0) or 0 for r in recs)
    tok.append(f"| **total** | {tot_calls} | | | | | | | USD {tot_cost:.2f} est. |")
    hold = []
    for r in recs:
        ho = r.get("holdout") or {}
        hold.append(f"\n**`{r['run_id']}`** (holdout fold `{ho.get('fold', 'holdout')}`; seed {f(ho.get('seed'))}; "
                    f"champion = best train score):\n")
        hold.append("| Rank | Program | Train | Holdout | Valid on holdout | First holdout insight |")
        hold.append("|---|---|---|---|---|---|")
        for k, row in enumerate(ho.get("top_k", []), 1):
            ins = (row.get("holdout_insights") or [{}])[0].get("text", "")[:150].replace("|", "/")
            hold.append(f"| {k} | `{row['id']}` | {f(row['train'])} | {f(row['holdout'])} | {row['holdout_valid']} | {ins} |")
    catches = []
    for r in recs:
        for p in r.get("programs", [])[1:]:
            if p.get("kind") == "policy":
                for v in p.get("violations") or []:
                    catches.append(f"| `{r['run_id']}` | #{p['idx']} `{p['id']}` | {p.get('model')} | {v.get('invariant')} | "
                                   f"{f(p.get('raw_score'))} | {(v.get('text') or '')[:260].replace('|', '/')} |")
    catch_tbl = "\n".join(["| Run | Candidate | Model | Invariant | Would have scored | Evaluator insight |", "|---|---|---|---|---|---|"]
                          + (catches or ["| - | - | - | - | - | none |"]))
    FIG.mkdir(parents=True, exist_ok=True)
    figs = []
    for r in recs:
        curve = r.get("score_curve") or []
        valid = [c for c in curve if c["score"] is not None]
        best = [c for c in curve if c["best"] is not None]
        name = f"score_curve_{r['run_id'].replace('.', '_')}.svg"
        seed = r["seed"]["train"]
        svg_lines(FIG / name, f"{r['run_id']}: train score by program (JPY M)", [
            ("feasible candidates", [c["idx"] for c in valid], [c["score"] for c in valid], "dots"),
            ("best so far", [c["idx"] for c in best], [c["best"] for c in best], "line"),
            ("seed", [0, max(c["idx"] for c in curve)], [seed, seed], "dash")], "program index", "score (JPY M)")
        figs.append(f"![{r['run_id']}](figures/{name})")
    s = DOC.read_text()

    def put(s, marker, content):
        pat = re.compile(rf"<!-- {marker} -->.*?<!-- /{marker} -->", re.S)
        block = f"<!-- {marker} -->\n{content}\n<!-- /{marker} -->"
        return pat.sub(lambda m: block, s) if pat.search(s) else s.replace(f"<!-- {marker} -->", block)

    s = put(s, "RUN_TABLE", table)
    s = put(s, "TOKEN_TABLE", "\n".join(tok))
    s = put(s, "HOLDOUT_TABLES", "\n".join(hold))
    s = put(s, "CATCH_TABLE", catch_tbl)
    s = put(s, "SCORE_FIGS", "\n\n".join(figs))
    DOC.write_text(s)
    print("RESULTS tables rendered for", len(recs), "runs")


if __name__ == "__main__":
    main()
