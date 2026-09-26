"""BigQuery parity: the same SQL answers on BigQuery and on local DuckDB. Skips unless DATA_BACKEND=bigquery."""
import os

import pytest

pytestmark = pytest.mark.skipif(os.getenv("DATA_BACKEND", "local").lower() != "bigquery",
                                reason="set DATA_BACKEND=bigquery (and BQ_PROJECT/GOOGLE_CLOUD_PROJECT, BQ_DATASET) to run")


def test_bigquery_matches_local():
    from retail_desk.datastore import DataStore
    from retail_desk.store import DATA_DIR, SCHEMA_PATH, STORE
    from retail_desk.tools import cfe, market, risk

    assert STORE.backend == "bigquery"
    bq_plan = market.plan_hedge("2026-08-19", 35, 38)["totals"]
    bq_breach = risk.get_deviation_breaches("2026-08-01", "2026-08-19")["total_breach_slots"]
    bq_audit = cfe.audit_nfc_ledger("2026-08")["findings_total"]
    os.environ["DATA_BACKEND"] = "local"
    try:
        local = DataStore("tepco_retail_desk_demo", DATA_DIR, SCHEMA_PATH)
        import retail_desk.store as st

        st.STORE, saved = local, st.STORE
        for mod in (market, risk, cfe):
            mod.STORE = local
        market._plan.cache_clear()
        assert market.plan_hedge("2026-08-19", 35, 38)["totals"] == bq_plan
        assert risk.get_deviation_breaches("2026-08-01", "2026-08-19")["total_breach_slots"] == bq_breach
        assert cfe.audit_nfc_ledger("2026-08")["findings_total"] == bq_audit
    finally:
        os.environ["DATA_BACKEND"] = "bigquery"
