import os
import sys

import pandas as pd
import pytest
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "data"))
OUT = os.path.join(ROOT, "data", "out")


@pytest.fixture(scope="session")
def params():
    return yaml.safe_load(open(os.path.join(ROOT, "data", "simulation_parameters.yaml")))


@pytest.fixture(scope="session")
def csv():
    cache = {}

    def load(name):
        if name not in cache:
            cache[name] = pd.read_csv(os.path.join(OUT, f"{name}.csv"))
        return cache[name]

    return load
