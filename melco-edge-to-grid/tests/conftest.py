import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("DATA_BACKEND", "local")


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Record the last full run so the v2 proof page can show it (eval/results/pytest_last.json)."""
    import datetime as _dt
    import json as _json
    st = terminalreporter.stats
    counts = {k: len(st.get(k, [])) for k in ("passed", "failed", "skipped", "error")}
    if sum(counts.values()) < 50:      # only record full-suite runs, not single-file runs
        return
    path = os.path.join(ROOT, "eval", "results", "pytest_last.json")
    with open(path, "w") as f:
        _json.dump({**counts, "exit_status": int(exitstatus), "at": _dt.datetime.now().strftime("%Y-%m-%dT%H:%M"),
                    "skipped_reason": "BigQuery backend test runs only with DATA_BACKEND=bigquery"}, f, indent=1)
