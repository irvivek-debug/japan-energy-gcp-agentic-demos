"""The server runs sync endpoints in a threadpool; the dashboard fires several panel requests at once.
A DuckDB connection shared across threads interleaves result sets (observed: KeyError 'slot' in /api/position).
This guards the one-cursor-per-query fix: without it, ~40% of these queries return another query's columns."""
import concurrent.futures as cf
import os

import pytest

from retail_desk.store import STORE

QUERIES = [
    ("SELECT slot, tokyo_price_jpy_kwh FROM {t:jepx_spot_30min} WHERE date = @d ORDER BY slot", {"d": "2026-08-19"}, "slot"),
    ("SELECT customer_id, segment FROM {t:customers} ORDER BY customer_id", {}, "customer_id"),
]


@pytest.mark.skipif(os.getenv("DATA_BACKEND", "local") != "local", reason="DuckDB threading property")
def test_concurrent_queries_do_not_interleave():
    work = QUERIES * 60
    with cf.ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda q: STORE.query(q[0], **q[1]), work))
    for rows, (_, _, key) in zip(results, work):
        assert rows and key in rows[0]
