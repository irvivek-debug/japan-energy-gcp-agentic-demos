"""Same tools against BigQuery. Skipped unless DATA_BACKEND=bigquery (and GOOGLE_CLOUD_PROJECT / BQ_PROJECT set,
dataset loaded per deploy/DEPLOY.md). Compares BigQuery results with the local DuckDB results."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("DATA_BACKEND", "local").lower() != "bigquery", reason="set DATA_BACKEND=bigquery to run")


def test_bigquery_matches_local():
    from factory_copilot.datastore import STORE
    from factory_copilot.tools import market
    assert STORE.backend == "bigquery"
    rows = STORE.query("SELECT COUNT(*) AS n FROM {t:dr_events}")
    assert rows[0]["n"] >= 4
    j = market.get_jepx_prices("2026-08-19")
    assert j["status"] == "ok" and j["spike_windows"]
    r = STORE.query("SELECT MAX(import_kw) AS p FROM {t:site_load_30min} WHERE month = @m", m="2026-08")
    assert r[0]["p"] > 10000
