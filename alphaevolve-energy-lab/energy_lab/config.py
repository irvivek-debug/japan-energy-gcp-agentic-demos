"""Paths and constants shared by the lab. No project ids, accounts or keys live here (read from env)."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent            # demo root (alphaevolve-energy-lab/)
PKG = Path(__file__).resolve().parent                     # energy_lab/
DATA_DIR = ROOT / "data"
OUT_DIR = DATA_DIR / "out"
SCHEMA_PATH = DATA_DIR / "schema.json"
INSTANCE_DIR = Path(os.getenv("LAB_INSTANCE_DIR", str(DATA_DIR / "instances")))
RUNS_DIR = Path(os.getenv("LAB_RUNS_DIR", str(ROOT / "runs")))
PROBLEMS_DIR = PKG / "problems"

DEFAULT_DATASET = "energy_alphaevolve_lab"
PROBLEMS = ("tariff_pricing", "jepx_trading")

# Evidence sources. Only "alphaevolve" can ever make `evolved` true (see harness/promotion.py).
SOURCE_LOCAL = "local-gemini-controller"
SOURCE_ALPHAEVOLVE = "alphaevolve"
SOURCE_DRY_RUN = "local-dry-run-mutator"
