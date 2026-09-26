"""Load data/out/*.csv into BigQuery using data/schema.json (explicit schema, WRITE_TRUNCATE, asia-northeast1).

Usage: BQ_PROJECT=<project> [BQ_DATASET=tepco_retail_desk_demo] python deploy/load_bigquery.py
"""
from __future__ import annotations

import json
import os

from google.cloud import bigquery

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main() -> None:
    project = os.environ.get("BQ_PROJECT") or os.environ["GOOGLE_CLOUD_PROJECT"]
    dataset = os.getenv("BQ_DATASET", "tepco_retail_desk_demo")
    location = os.getenv("BQ_LOCATION", "asia-northeast1")
    client = bigquery.Client(project=project, location=location)
    ds = bigquery.Dataset(f"{project}.{dataset}")
    ds.location = location
    ds.description = "Retail Energy Desk concept demo (synthetic data)"
    client.create_dataset(ds, exists_ok=True)
    schema = json.load(open(os.path.join(ROOT, "data", "schema.json")))["tables"]
    for name, spec in schema.items():
        cfg = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.CSV, skip_leading_rows=1, write_disposition="WRITE_TRUNCATE",
            schema=[bigquery.SchemaField(c["name"], c["type"], description=c["description"][:1024]) for c in spec["columns"]])
        with open(os.path.join(ROOT, "data", "out", f"{name}.csv"), "rb") as f:
            job = client.load_table_from_file(f, f"{project}.{dataset}.{name}", job_config=cfg)
        job.result()
        table = client.get_table(f"{project}.{dataset}.{name}")
        table.description = spec["description"]
        client.update_table(table, ["description"])
        print(f"{name}: {table.num_rows:,} rows")


if __name__ == "__main__":
    main()
