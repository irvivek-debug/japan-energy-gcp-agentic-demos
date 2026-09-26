"""The server runs sync endpoints in a threadpool and the Evolution Lab fires several panel requests at once.
A DuckDB connection shared across threads interleaves result sets; datastore.py uses one cursor per query.
This guards that fix: 16 threads, 120 mixed queries, every result must carry its own key column."""
import concurrent.futures as cf
import os

import pytest

from energy_lab.store import STORE

QUERIES = [
    ("SELECT slot, tokyo_price_jpy_kwh FROM {t:market_history} WHERE date = @d ORDER BY slot", {"d": "2025-08-06"}, "slot"),
    ("SELECT customer_id, segment FROM {t:customers_train} ORDER BY customer_id", {}, "customer_id"),
    ("SELECT component, value FROM {t:cost_stack} WHERE voltage = @v", {"v": "HV"}, "component"),
    ("SELECT fiscal_year, AVG(tokyo_price_jpy_kwh) AS m FROM {t:market_history} GROUP BY fiscal_year", {}, "fiscal_year"),
]


@pytest.mark.skipif(os.getenv("DATA_BACKEND", "local") != "local", reason="DuckDB threading property")
def test_concurrent_queries_do_not_interleave():
    work = QUERIES * 30
    with cf.ThreadPoolExecutor(16) as ex:
        results = list(ex.map(lambda q: STORE.query(q[0], **q[1]), work))
    for rows, (_, _, key) in zip(results, work):
        assert rows and key in rows[0] and all(r[key] is not None for r in rows)
