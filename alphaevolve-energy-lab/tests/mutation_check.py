"""File-level mutation check: break each gate in the SOURCE, confirm its test goes red, restore.

    python tests/mutation_check.py        # never while a search is running (the sandbox child is re-read per candidate)

A test that cannot fail is not a gate. Results: eval/results/mutation_checks.json.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

MUTATIONS = [
    ("datastore: one DuckDB connection shared across threads", "energy_lab/datastore.py",
     "cur = self._con.cursor().execute(", "cur = self._con.execute(",
     "tests/test_datastore_concurrency.py::test_concurrent_queries_do_not_interleave"),
    ("sandbox: socket patch removed", "energy_lab/harness/sandbox_child.py",
     'socket.socket = _deny("network access (socket)")', "pass",
     "tests/test_sandbox.py::test_socket_denied_even_if_import_guard_is_bypassed"),
    ("sandbox: out-of-installation reads allowed (look-ahead)", "energy_lab/harness/sandbox_child.py",
     "        if not path.startswith(prefixes):\n            raise PermissionError(f\"sandbox: reading outside",
     "        if False:\n            raise PermissionError(f\"sandbox: reading outside",
     "tests/test_sandbox.py::test_no_look_ahead_read_of_frozen_instance"),
    ("trading: per-slot compliance tolerance x100", "energy_lab/problems/jepx_trading/sim.py",
     "if abs(gap) > tol + 1e-6:", "if abs(gap) > tol * 100:",
     "tests/test_invariants_trading.py::test_intentional_imbalance_is_caught_with_slot_list"),
    ("trading: naked-selling check disabled", "energy_lab/problems/jepx_trading/sim.py",
     "            if sold > allowed:", "            if sold > allowed * 1e9:",
     "tests/test_invariants_trading.py::test_other_invariants"),
    ("tariff: essential alpha limit 0.30 -> 0.95", "energy_lab/problems/tariff_pricing/model.py",
     '"essential_alpha_max": 0.30', '"essential_alpha_max": 0.95',
     "tests/test_invariants_tariff.py::test_violator_is_caught"),
    ("tariff: v3 rise rule disabled", "energy_lab/problems/tariff_pricing/model.py",
     "SEGMENT_CHURN_RISE_MAX = 0.05", "SEGMENT_CHURN_RISE_MAX = 5.0",
     "tests/test_invariants_tariff.py::test_v3_segment_churn_rise_vs_incumbent_is_caught"),
    ("baseline: seed == null check removed", "energy_lab/harness/baseline.py",
     'problems.append("seed and null score the same: the evaluator cannot separate them")', "pass",
     "tests/test_baseline_budget_evidence.py::test_baseline_refuses_evaluator_that_cannot_separate_seed_from_null"),
    ("evidence: exclusive create -> overwrite", "energy_lab/harness/evidence.py",
     'with open(self.final_path, "x") as f:', 'with open(self.final_path, "w") as f:',
     "tests/test_baseline_budget_evidence.py::test_evidence_is_never_overwritten"),
    ("budget: invalid candidates reset the plateau", "energy_lab/harness/budget.py",
     "        if score is None:          # invalid: neither advances nor resets\n            return self.plateaued",
     "        if score is None:\n            self.since = 0\n            return self.plateaued",
     "tests/test_baseline_budget_evidence.py::test_plateau_counts_feasible_only"),
    ("promotion: source check removed", "energy_lab/harness/evidence.py",
     '"ok": record.get("source") == SOURCE_ALPHAEVOLVE, "value": record.get("source")},',
     '"ok": True, "value": record.get("source")},',
     "tests/test_baseline_budget_evidence.py::test_promotion_gate_requires_all_four"),
]


def main() -> int:
    results = []
    for name, rel, old, new, test in MUTATIONS:
        path = ROOT / rel
        src = path.read_text()
        if old not in src:
            results.append({"mutation": name, "status": "SNIPPET_NOT_FOUND", "file": rel})
            print(f"SKIP {name}: snippet not found")
            continue
        try:
            path.write_text(src.replace(old, new, 1))
            p = subprocess.run([PY, "-m", "pytest", "-q", "-x", "--no-header", "-p", "no:cacheprovider", test],
                               cwd=ROOT, capture_output=True, text=True, timeout=600)
            red = p.returncode != 0
        finally:
            path.write_text(src)
        results.append({"mutation": name, "file": rel, "test": test, "suite_went_red": red,
                        "tail": p.stdout.strip().splitlines()[-1] if p.stdout.strip() else ""})
        print(f"{'RED (gate works)' if red else 'GREEN (GATE NOT PROTECTED)'}: {name}")
    ok = all(r.get("suite_went_red") for r in results)
    out = ROOT / "eval" / "results" / "mutation_checks.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"all_gates_protected": ok, "results": results}, indent=1))
    print(f"{sum(r.get('suite_went_red', False) for r in results)}/{len(results)} mutations detected")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
