"""Portable, parameterised SQL over BigQuery (deployed) or DuckDB-on-CSV (local/dev/CI).

Copy this file into each demo package unchanged (demos stay independent).

Rules that keep one SQL string valid on both engines:
  * reference tables as {t:table_name}; pass values as @named params (never f-string values in)
  * every column type comes from data/schema.json (STRING, INT64, FLOAT64, BOOL only)
  * dates/timestamps are STRING in ISO form ('2026-08-19', '2026-08-19T17:30') and are compared as strings
  * portable functions only: SUM AVG MIN MAX COUNT ROUND ABS COALESCE CASE, GREATEST/LEAST,
    GROUP BY / ORDER BY / LIMIT / simple JOINs / CTEs (WITH). No DATE_*, TIMESTAMP_*, QUALIFY, ARRAY_AGG, STRUCT.
"""
from __future__ import annotations

import json
import os
import re
from typing import Any

_TYPE_DUCK = {"STRING": "VARCHAR", "INT64": "BIGINT", "FLOAT64": "DOUBLE", "BOOL": "BOOLEAN"}


def _bq_type(v: Any) -> str:
    if isinstance(v, bool):
        return "BOOL"
    if isinstance(v, int):
        return "INT64"
    if isinstance(v, float):
        return "FLOAT64"
    return "STRING"


class DataStore:
    """backend = env DATA_BACKEND in {local, bigquery}; dataset = env BQ_DATASET or the default given."""

    def __init__(self, default_dataset: str, data_dir: str, schema_path: str):
        self.backend = os.getenv("DATA_BACKEND", "local").lower()
        self.dataset = os.getenv("BQ_DATASET", default_dataset)
        with open(schema_path) as f:
            self.schema = json.load(f)["tables"]
        if self.backend == "bigquery":
            from google.cloud import bigquery  # lazy: local mode needs no GCP libs

            # BQ_PROJECT wins: Agent Engine may expose GOOGLE_CLOUD_PROJECT as a project number
            self.project = os.environ.get("BQ_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
            if not self.project:
                raise RuntimeError("BQ_PROJECT or GOOGLE_CLOUD_PROJECT must be set when DATA_BACKEND=bigquery")
            self._bq = bigquery.Client(project=self.project, location=os.getenv("BQ_LOCATION", "asia-northeast1"))
        else:
            import duckdb

            self._con = duckdb.connect()
            for name, spec in self.schema.items():
                path = os.path.join(data_dir, f"{name}.csv")
                if not os.path.exists(path):
                    raise FileNotFoundError(f"{path} missing - run the data generator first")
                cols = ", ".join(f"'{c['name']}': '{_TYPE_DUCK[c['type']]}'" for c in spec["columns"])
                self._con.execute(
                    f"CREATE VIEW {name} AS SELECT * FROM read_csv('{path}', header=true, columns={{{cols}}})"
                )

    def fq(self, table: str) -> str:
        if table not in self.schema:
            raise KeyError(f"unknown table {table}")
        return f"`{self.project}.{self.dataset}.{table}`" if self.backend == "bigquery" else table

    def source_label(self, table: str) -> str:
        """The literal citation string agents must use: [dataset.table]."""
        return f"{self.dataset}.{table}"

    def query(self, sql: str, **params: Any) -> list[dict]:
        sql = re.sub(r"\{t:(\w+)\}", lambda m: self.fq(m.group(1)), sql)
        if self.backend == "bigquery":
            from google.cloud import bigquery

            cfg = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter(k, _bq_type(v), v) for k, v in params.items()]
            )
            return [dict(r.items()) for r in self._bq.query(sql, job_config=cfg).result()]
        # One cursor per query: a DuckDB connection is not safe to share across threads (FastAPI threadpool),
        # and concurrent execute() calls on it interleave result sets.
        cur = self._con.cursor().execute(re.sub(r"@(\w+)", r"$\1", sql), params)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


# ---------------------------------------------------------------------------------------------
# Demo binding (the only addition to the shared reference file): one STORE per process.
# Default dataset for this demo; override with env BQ_DATASET. The dataset is never the project.
# Agent Engine ships only this package, so schema.json lives inside it. Local CSVs (data/out) are
# only read when DATA_BACKEND=local.
# ---------------------------------------------------------------------------------------------
DEFAULT_DATASET = "melco_edge_to_grid_demo"
_PKG = os.path.dirname(os.path.abspath(__file__))
STORE = DataStore(
    DEFAULT_DATASET,
    data_dir=os.getenv("DATA_DIR", os.path.join(os.path.dirname(_PKG), "data", "out")),
    schema_path=os.path.join(_PKG, "schema.json"),
)
