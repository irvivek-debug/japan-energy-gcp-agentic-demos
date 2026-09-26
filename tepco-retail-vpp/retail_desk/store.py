"""Builds the one DataStore used by every tool. Paths resolve relative to the package so the package directory is
self-contained for Agent Runtime (formerly Vertex AI Agent Engine) deployments; CSVs are needed only when
DATA_BACKEND=local."""
from __future__ import annotations

import os

from .datastore import DataStore

PKG_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(PKG_DIR, "schema.json")
CORPUS_DIR = os.path.join(PKG_DIR, "corpus")
DATA_DIR = os.getenv("LOCAL_DATA_DIR", os.path.join(PKG_DIR, "..", "data", "out"))
DEFAULT_DATASET = "tepco_retail_desk_demo"

STORE = DataStore(DEFAULT_DATASET, DATA_DIR, SCHEMA_PATH)


def src(*tables: str) -> list[str]:
    """Citation labels [dataset.table] for the given tables."""
    return [STORE.source_label(t) for t in tables]
