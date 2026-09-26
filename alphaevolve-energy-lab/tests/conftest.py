"""Test isolation: evidence and ledger writes go to a temp runs dir, never to runs/."""
import os
import sys
import tempfile
from pathlib import Path

_TMP_RUNS = tempfile.mkdtemp(prefix="lab_test_runs_")
os.environ["LAB_RUNS_DIR"] = _TMP_RUNS          # must be set before energy_lab.config is imported
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


@pytest.fixture
def runs_dir(tmp_path):
    return tmp_path


def swap_block(seed_src: str, new_block: str) -> str:
    from energy_lab.harness.package import assemble, split_program

    p = split_program(seed_src)
    return assemble(p.prefix, new_block, p.suffix)
