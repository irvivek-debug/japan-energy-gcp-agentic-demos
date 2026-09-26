"""Evidence files and the promotion rule.

One evidence file per run: ``runs/<problem>.<started>.json``, created exclusively (mode 'x') when the
run finalises and never overwritten (a re-run once erased the reclassified evidence it replaced).
While a run is in flight its progress lives in ``runs/<problem>.<started>.partial.json`` (the UI polls
it); the partial is removed after the final file is written.

Human reviews are an append-only audit log (``runs/reviews.jsonl``), never an edit of the evidence.

``evolved`` may flip only when: a run record exists with ``source == "alphaevolve"``, a holdout delta,
``uplift_valid`` not False, and a human has read the evolved block. Local-controller and dry runs
never count, whatever their scores.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import RUNS_DIR, SOURCE_ALPHAEVOLVE

SCHEMA = "energy_lab.run_evidence/v1"


def utc_stamp(dt: datetime | None = None) -> str:
    return (dt or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")


class EvidenceExists(FileExistsError):
    pass


class EvidenceWriter:
    def __init__(self, problem: str, started: datetime, runs_dir: Path | None = None):
        self.dir = Path(runs_dir or RUNS_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.run_id = f"{problem}.{utc_stamp(started)}"
        self.final_path = self.dir / f"{self.run_id}.json"
        self.partial_path = self.dir / f"{self.run_id}.partial.json"
        if self.final_path.exists():
            raise EvidenceExists(f"{self.final_path} already exists; evidence is never overwritten")

    def progress(self, record: dict) -> None:
        tmp = self.partial_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**record, "status": "running"}, default=str))
        tmp.replace(self.partial_path)

    def finalize(self, record: dict) -> Path:
        record = {**record, "status": "finished"}
        with open(self.final_path, "x") as f:     # exclusive create: never overwrite
            json.dump(record, f, indent=1, default=str)
        os.chmod(self.final_path, 0o444)
        if self.partial_path.exists():
            self.partial_path.unlink()
        return self.final_path


def list_evidence(runs_dir: Path | None = None, include_partial: bool = True) -> list[dict]:
    d = Path(runs_dir or RUNS_DIR)
    out = []
    if not d.exists():
        return out
    for p in sorted(d.glob("*.json")):
        if p.name == "ledger.json" or p.name.endswith(".tmp"):
            continue
        is_partial = p.name.endswith(".partial.json")
        if is_partial and not include_partial:
            continue
        try:
            rec = json.loads(p.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if rec.get("schema") != SCHEMA:
            continue
        rec["_path"] = str(p)
        out.append(rec)
    return out


def load_run(run_id: str, runs_dir: Path | None = None) -> dict | None:
    d = Path(runs_dir or RUNS_DIR)
    for name in (f"{run_id}.json", f"{run_id}.partial.json"):
        p = d / name
        if p.exists():
            rec = json.loads(p.read_text())
            rec["_path"] = str(p)
            return rec
    return None


# --- human review audit (append-only) --------------------------------------------------------------------
def reviews_path(runs_dir: Path | None = None) -> Path:
    return Path(runs_dir or RUNS_DIR) / "reviews.jsonl"


def append_review(run_id: str, program_id: str, reviewer: str, note: str, runs_dir: Path | None = None) -> dict:
    entry = {"run_id": run_id, "program_id": program_id, "reviewer": reviewer, "note": note[:500],
             "at": datetime.now(timezone.utc).isoformat(), "kind": "human_review"}
    p = reviews_path(runs_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def reviews_for(run_id: str, runs_dir: Path | None = None) -> list[dict]:
    p = reviews_path(runs_dir)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("run_id") == run_id:
            out.append(e)
    return out


def promotion_gate(record: dict, reviews: list[dict] | None = None) -> dict[str, Any]:
    """The checklist the UI and the analyst agent show. Pure function of evidence + review log."""
    ho = record.get("holdout") or {}
    best_id = ho.get("best_id")
    reviews = reviews if reviews is not None else []
    reviewed = any(r.get("program_id") == best_id for r in reviews) if best_id else False
    delta = ho.get("holdout_delta")
    checks = [
        {"id": "holdout_delta", "label": "Holdout delta recorded and positive",
         "ok": isinstance(delta, (int, float)) and delta > 0, "value": delta},
        {"id": "uplift_valid", "label": "uplift_valid is not False (policy invariants hold on holdout)",
         "ok": record.get("uplift_valid") is not False and record.get("uplift_valid") is not None,
         "value": record.get("uplift_valid")},
        {"id": "human_review", "label": "A human has read the evolved block", "ok": reviewed,
         "value": len([r for r in reviews if r.get("program_id") == best_id])},
        {"id": "source", "label": "Run source is a real AlphaEvolve experiment (source == alphaevolve)",
         "ok": record.get("source") == SOURCE_ALPHAEVOLVE, "value": record.get("source")},
    ]
    eligible = all(c["ok"] for c in checks)
    blockers = [c["label"] for c in checks if not c["ok"]]
    return {"run_id": record.get("run_id"), "best_program_id": best_id, "checks": checks,
            "evolved": bool(eligible), "promotion_allowed": bool(eligible), "blockers": blockers}
