"""The server runs sync endpoints in a threadpool and the dashboard loads about a dozen panels at once.
A DuckDB connection shared across threads interleaves result sets; datastore.py uses one cursor per query.
This guards that fix (16 threads, 120 mixed queries, each result must carry its own key column and values),
and exercises the real dashboard endpoints concurrently."""
import concurrent.futures as cf
import os

import pytest

from factory_copilot.datastore import STORE

QUERIES = [
    ("SELECT slot, spot_jpy_kwh FROM {t:jepx_prices_30min} WHERE date = @d ORDER BY slot", {"d": "2026-08-19"}, "slot", 48),
    ("SELECT asset_id, asset_class FROM {t:assets} ORDER BY asset_id", {}, "asset_id", None),
    ("SELECT meter_id, kw FROM {t:telemetry_5min} WHERE ts = @t ORDER BY meter_id", {"t": "2026-08-19T13:25"}, "meter_id", None),
    ("SELECT rule_id, limit_value FROM {t:interlock_rules} ORDER BY rule_id", {}, "rule_id", None),
    ("SELECT compressor_id, SUM(energy_kwh) AS kwh FROM {t:compressor_perf} GROUP BY compressor_id ORDER BY compressor_id", {}, "compressor_id", 6),
]

pytestmark = pytest.mark.skipif(os.getenv("DATA_BACKEND", "local") != "local", reason="DuckDB threading property")


def test_concurrent_queries_do_not_interleave():
    expected = {q[0]: len(STORE.query(q[0], **q[1])) for q in QUERIES}
    work = QUERIES * 24   # 120 queries
    with cf.ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda q: STORE.query(q[0], **q[1]), work))
    for rows, (sql, _, key, n) in zip(results, work):
        assert rows and key in rows[0], sql
        assert len(rows) == expected[sql] and (n is None or len(rows) == n)
        assert all(r[key] is not None for r in rows)


def test_dashboard_endpoints_concurrently():
    from fastapi.testclient import TestClient
    from server.app import app
    c = TestClient(app)
    eps = ["/api/overview", "/api/load-stack", "/api/flex", "/api/bess", "/api/pv", "/api/jepx", "/api/anomalies",
           "/api/gain-share?month=2026-07", "/api/edge-decisions", "/api/dr-events", "/api/dr-today", "/api/deviation"] * 3
    with cf.ThreadPoolExecutor(12) as ex:
        res = list(ex.map(lambda e: (e, c.get(e)), eps))
    for ep, r in res:
        assert r.status_code == 200, ep
        body = r.json()
        assert body.get("status", "ok") in ("ok", "estimate") or "kpis" in body or "rows" in body or "policies" in body, ep
