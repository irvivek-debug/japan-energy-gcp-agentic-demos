"""The one DataStore instance for this demo (dataset default: energy_alphaevolve_lab).

Local (DATA_BACKEND=local, default): DuckDB views over data/out/*.csv. Deployed (DATA_BACKEND=bigquery): BigQuery
dataset BQ_DATASET in BQ_PROJECT / GOOGLE_CLOUD_PROJECT. The schema file ships inside the package (Agent Runtime only
ships energy_lab/), resolved relative to this file.
"""
from __future__ import annotations

import os

from .datastore import DataStore

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATASET = "energy_alphaevolve_lab"
DATA_DIR = os.getenv("LAB_DATA_DIR", os.path.join(_HERE, "..", "data", "out"))

STORE = DataStore(DEFAULT_DATASET, DATA_DIR, os.path.join(_HERE, "schema.json"))


def src(*tables: str) -> list[str]:
    return [STORE.source_label(t) for t in tables]
