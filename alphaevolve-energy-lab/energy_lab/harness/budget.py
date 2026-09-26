"""Budget is enforced, not proposed.

Generation (Gemini calls), not evaluation, drives cost. Production defaults: 40 programs / run,
30 min wall, 120 programs and 4 runs / day (per problem), plateau patience 15 (over FEASIBLE candidates
only: invalid ones neither advance nor reset it), concurrency 2. The ledger is checked before a run
starts and recorded after. Wall clock and plateau are enforced by the harness because the platform
stops only on its evaluated-count criterion.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from ..config import RUNS_DIR

JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class BudgetPolicy:
    max_programs_per_run: int = 40
    max_wall_s: int = 1800
    max_programs_per_day: int = 120
    max_runs_per_day: int = 4
    plateau_patience: int = 15
    concurrency: int = 2

    @classmethod
    def from_env(cls) -> "BudgetPolicy":
        d = cls()
        return cls(
            max_programs_per_run=int(os.getenv("AE_MAX_PROGRAMS", d.max_programs_per_run)),
            max_wall_s=int(os.getenv("AE_MAX_WALL_S", d.max_wall_s)),
            max_programs_per_day=int(os.getenv("AE_MAX_PROGRAMS_PER_DAY", d.max_programs_per_day)),
            max_runs_per_day=int(os.getenv("AE_MAX_RUNS_PER_DAY", d.max_runs_per_day)),
            plateau_patience=int(os.getenv("AE_PLATEAU_PATIENCE", d.plateau_patience)),
            concurrency=int(os.getenv("AE_CONCURRENCY", d.concurrency)),
        )


class BudgetExceeded(RuntimeError):
    pass


class Ledger:
    """Append-only JSON ledger of runs (runs/ledger.json). Day boundaries are Asia/Tokyo calendar days."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else RUNS_DIR / "ledger.json"
        self._lock = threading.Lock()

    def _read(self) -> dict:
        if not self.path.exists():
            return {"runs": []}
        return json.loads(self.path.read_text())

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(self.path)

    @staticmethod
    def day_of(ts_iso: str) -> str:
        return datetime.fromisoformat(ts_iso).astimezone(JST).date().isoformat()

    def usage(self, problem: str, day: str) -> dict:
        runs = [r for r in self._read()["runs"] if r["problem"] == problem and self.day_of(r["started"]) == day
                and r.get("counts_against_budget", True)]
        return {"runs": len(runs), "programs": sum(int(r.get("programs", 0)) for r in runs)}

    def check_can_start(self, problem: str, requested_programs: int, policy: BudgetPolicy,
                        now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        day = now.astimezone(JST).date().isoformat()
        u = self.usage(problem, day)
        if requested_programs > policy.max_programs_per_run:
            raise BudgetExceeded(f"requested {requested_programs} programs > {policy.max_programs_per_run} per run")
        if u["runs"] >= policy.max_runs_per_day:
            raise BudgetExceeded(f"{problem}: {u['runs']} runs already today (limit {policy.max_runs_per_day}/day)")
        if u["programs"] + requested_programs > policy.max_programs_per_day:
            raise BudgetExceeded(f"{problem}: {u['programs']} programs used today + {requested_programs} requested "
                                 f"> {policy.max_programs_per_day}/day")
        return {"day": day, **u, "remaining_programs_today": policy.max_programs_per_day - u["programs"]}

    @contextlib.contextmanager
    def _xlock(self):
        """Thread lock + cross-process advisory file lock around read-modify-write of the ledger."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock, open(self.path.with_suffix(".lock"), "w") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)

    def reserve(self, entry: dict) -> None:
        """Record a run at start (status=running) so concurrent starts see it; finalised by ``record``."""
        with self._xlock():
            data = self._read()
            data["runs"].append({**entry, "status": "running"})
            self._write(data)

    def record(self, run_id: str, **fields) -> None:
        with self._xlock():
            data = self._read()
            for r in data["runs"]:
                if r["run_id"] == run_id:
                    r.update(fields)
                    break
            else:
                data["runs"].append({"run_id": run_id, **fields})
            self._write(data)

    def all(self) -> list[dict]:
        return self._read()["runs"]


class PlateauTracker:
    """Counts consecutive FEASIBLE candidates that fail to beat the best feasible score."""

    def __init__(self, patience: int, best: float | None = None, min_improvement: float = 1e-6):
        self.patience = patience
        self.best = best
        self.since = 0
        self.min_improvement = min_improvement

    def update(self, score: float | None) -> bool:
        if score is None:          # invalid: neither advances nor resets
            return self.plateaued
        if self.best is None or score > self.best + self.min_improvement:
            self.best = score
            self.since = 0
        else:
            self.since += 1
        return self.plateaued

    @property
    def plateaued(self) -> bool:
        return self.since >= self.patience


def policy_dict(p: BudgetPolicy) -> dict:
    return asdict(p)
