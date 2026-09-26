"""Flatten run evidence (runs/*.json, runs/reviews.jsonl) into BigQuery-ready tables in data/out.

    python -m energy_lab.export_evidence

The Lab Analyst agent reads run evidence ONLY through these tables (via STORE), because Agent Runtime ships just the
``energy_lab/`` package. Only finalised evidence files are exported (in-flight *.partial.json are skipped).
"""
from __future__ import annotations

import csv
import json
import sys

from .config import OUT_DIR, RUNS_DIR
from .harness.evidence import list_evidence, reviews_path
from .schema_def import SCHEMA


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return f"{v:.6f}".rstrip("0").rstrip(".") if abs(v) < 1e9 else f"{v:.2f}"
    return v


def _write(name: str, rows: list[dict]) -> int:
    cols = [c["name"] for c in SCHEMA[name]["columns"]]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_DIR / f"{name}.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in cols])
    return len(rows)


def run_rows(rec: dict) -> dict:
    ho = rec.get("holdout") or {}
    bl = rec.get("baseline_lock") or {}
    best = rec.get("best") or {}
    tok = rec.get("tokens") or {}
    uv = rec.get("uplift_valid")
    lineage = best.get("lineage") or []
    return {
        "run_id": rec["run_id"], "problem": rec["problem"], "source": rec.get("source"), "backend": rec.get("backend"),
        "evolved": bool(rec.get("evolved")), "started": rec.get("started"), "finished": rec.get("finished"),
        "programs_evaluated": (rec.get("budget") or {}).get("programs_evaluated"), "valid_count": rec.get("valid_count"),
        "invalid_count": rec.get("invalid_count"), "stopped_reason": (rec.get("budget") or {}).get("stopped_reason"),
        "wall_s": (rec.get("budget") or {}).get("wall_s"), "seed_train": (rec.get("seed") or {}).get("train"),
        "null_train_raw": bl.get("null_raw"), "null_train_valid": bl.get("null_valid"), "best_train": best.get("train"),
        "best_program_id": best.get("id"), "train_delta_vs_seed": best.get("train_delta_vs_seed"),
        "holdout_seed": ho.get("seed"), "holdout_null_raw": ho.get("null_raw"), "best_holdout": ho.get("best_holdout"),
        "holdout_delta": ho.get("holdout_delta"), "uplift_valid": "null" if uv is None else str(bool(uv)).lower(),
        "uplift_note": rec.get("uplift_note"), "llm_calls": tok.get("calls"), "prompt_tokens": tok.get("prompt"),
        "output_tokens": tok.get("output"), "thinking_tokens": tok.get("thinking"), "cost_usd_est": tok.get("cost_usd"),
        "model_mix": json.dumps(rec.get("model_mix")), "instance_train_sha": ((rec.get("instances") or {}).get("train") or {}).get("sha256"),
        "instance_holdout_sha": ((rec.get("instances") or {}).get("holdout") or {}).get("sha256"),
        "best_rationale": " || ".join(f"{x['id']}: {x['rationale']}" for x in lineage[1:])[:6000],
        "best_diff_vs_seed": (best.get("diff_vs_seed") or "")[:20000], "honesty_note": rec.get("honesty_note"),
        "pricing_note": rec.get("pricing_note"),
    }


def export_all(quiet: bool = False) -> dict[str, int]:
    recs = [r for r in list_evidence(RUNS_DIR, include_partial=False) if r.get("status") == "finished"]
    runs, progs, catches, hold = [], [], [], []
    for rec in recs:
        runs.append(run_rows(rec))
        best_so_far = None
        for p in rec.get("programs", []):
            if p.get("score") is not None and (best_so_far is None or p["score"] > best_so_far):
                best_so_far = p["score"]
            ins = p.get("insights") or [{}]
            gen = p.get("generation") or {}
            ds = p.get("diff_stats") or {}
            progs.append({"run_id": rec["run_id"], "problem": rec["problem"], "idx": p["idx"], "program_id": p["id"],
                          "parent_id": p.get("parent_id"), "island": p.get("island"), "model": p.get("model"),
                          "valid": bool(p.get("valid")), "kind": p.get("kind"), "score": p.get("score"),
                          "raw_score": p.get("raw_score"), "best_so_far": best_so_far, "eval_s": p.get("eval_s"),
                          "gen_latency_s": gen.get("latency_s"), "prompt_tokens": gen.get("prompt_tokens"),
                          "output_tokens": gen.get("output_tokens"), "lines_added": ds.get("lines_added"),
                          "lines_removed": ds.get("lines_removed"), "first_insight_label": ins[0].get("label"),
                          "first_insight_text": (ins[0].get("text") or "")[:1500], "rationale": (p.get("rationale") or "")[:1500],
                          "block_sha": p.get("block_sha")})
            if p.get("kind") == "policy":
                for v in p.get("violations") or []:
                    catches.append({"run_id": rec["run_id"], "problem": rec["problem"], "idx": p["idx"], "program_id": p["id"],
                                    "model": p.get("model"), "invariant": v.get("invariant"), "violations": v.get("count"),
                                    "raw_score": p.get("raw_score"), "text": (v.get("text") or "")[:1500]})
        ho = rec.get("holdout") or {}
        for rank, row in enumerate(ho.get("top_k", []), 1):
            hs = row.get("holdout")
            hold.append({"run_id": rec["run_id"], "problem": rec["problem"], "rank": rank, "program_id": row["id"],
                         "is_seed": row.get("idx") == 0, "is_champion": row["id"] == ho.get("best_id"),
                         "train_score": row.get("train"), "holdout_score": hs, "holdout_valid": bool(row.get("holdout_valid")),
                         "holdout_kind": row.get("holdout_kind"), "holdout_seed": ho.get("seed"),
                         "delta_vs_seed": (hs - ho["seed"]) if (hs is not None and ho.get("seed") is not None) else None})
    reviews = []
    rp = reviews_path(RUNS_DIR)
    if rp.exists():
        for line in rp.read_text().splitlines():
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            reviews.append({k: e.get(k) for k in ("run_id", "program_id", "reviewer", "note", "at")})
    counts = {"lab_runs": _write("lab_runs", runs), "lab_programs": _write("lab_programs", progs),
              "lab_invariant_catches": _write("lab_invariant_catches", catches), "lab_holdout": _write("lab_holdout", hold),
              "lab_reviews": _write("lab_reviews", reviews)}
    if not quiet:
        print(json.dumps(counts))
    return counts


if __name__ == "__main__":
    export_all()
    sys.exit(0)
