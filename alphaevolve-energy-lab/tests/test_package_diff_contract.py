"""EVOLVE-BLOCK packaging, static checks, SEARCH/REPLACE application and the evaluator contract."""
import math

import pytest

from energy_lab.harness.contract import EvalOutcome, clean_score, validate_contract
from energy_lab.harness.diff import DiffError, apply_reply, parse_hunks
from energy_lab.harness.evaluate import evaluate_candidate, make_contract_evaluator
from energy_lab.harness.package import PackagingError, check_scaffolding, split_program, static_check
from energy_lab.problems import get_problem

from conftest import swap_block

SPEC = get_problem("tariff_pricing")


def test_split_roundtrip_and_markers():
    p = split_program(SPEC.seed_src)
    assert p.source == SPEC.seed_src
    assert "def price_book" in p.block and "def clamp" in p.prefix
    with pytest.raises(PackagingError):
        split_program("def f():\n    pass\n")


def test_scaffold_change_is_detected_and_invalid():
    src = SPEC.seed_src.replace("def clamp(x, lo, hi):", "def clamp(x, lo, hi):  # tweaked")
    assert check_scaffolding(SPEC.seed_program, split_program(src))
    out = evaluate_candidate(SPEC, src, "train")
    assert out.score is None and out.kind == "scaffold"


@pytest.mark.parametrize("block,needle", [
    ("import os\ndef price_book(c, m):\n    return {}\n", "import of 'os'"),
    ("def price_book(c, m):\n    return eval('1')\n", "'eval'"),
    ("def price_book(c, m):\n    return c.__class__\n", "dunder"),
    ("CACHE = {}\ndef price_book(c, m):\n    return CACHE\n", "module-level mutable"),
    ("def price_book(c, m, memo=[]):\n    return memo\n", "mutable default"),
    ("import numpy as np\ndef price_book(c, m):\n    return np.random.rand()\n", "nondeterminism"),
    ("def other(c, m):\n    return {}\n", "required function 'price_book'"),
])
def test_static_check_rejects(block, needle):
    probs = static_check(split_program(swap_block(SPEC.seed_src, block)), ("price_book",))
    assert any(needle in p for p in probs), probs


def test_static_check_accepts_seed():
    assert static_check(SPEC.seed_program, ("price_book",)) == []


BLOCK = "def f(x):\n    a = 1\n    if a:\n        return a + 1\n    return 0\n"


def test_diff_exact_and_reindent_and_fuzzy():
    new, rep = apply_reply(BLOCK, "<<<<<<< SEARCH\n    a = 1\n=======\n    a = 2\n>>>>>>> REPLACE")
    assert "a = 2" in new and rep.methods == ["exact"]
    new, rep = apply_reply(BLOCK, "<<<<<<< SEARCH\nif a:\n    return a + 1\n=======\nif a:\n    return a + 5\n>>>>>>> REPLACE")
    assert "        return a + 5" in new and rep.methods == ["reindent"]
    new, rep = apply_reply(BLOCK, "<<<<<<< SEARCH\n    if a :\n        return a + 1\n=======\n    if a:\n        return 9\n>>>>>>> REPLACE")
    assert "return 9" in new and rep.methods[0].startswith("fuzzy")


def test_diff_failures_are_reported_not_guessed():
    with pytest.raises(DiffError):
        apply_reply(BLOCK, "<<<<<<< SEARCH\n    zzz = 3\n=======\n    zzz = 4\n>>>>>>> REPLACE")
    with pytest.raises(DiffError):
        apply_reply(BLOCK, "no diff here")
    with pytest.raises(DiffError):
        apply_reply(BLOCK, "<<<<<<< SEARCH\n# EVOLVE-BLOCK-END\n=======\n\n>>>>>>> REPLACE")


def test_full_rewrite_mode():
    reply = "Rewrite:\n```python\ndef f(x):\n    return 42\n```\n"
    new, rep = apply_reply(BLOCK, reply, ("f",))
    assert rep.mode == "full_rewrite" and "42" in new


def test_parse_multiple_hunks_with_indented_markers():
    t = "<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n  <<<<<<< SEARCH\nc\n  =======\nd\n  >>>>>>> REPLACE\n"
    assert parse_hunks(t) == [("a", "b"), ("c", "d")]


def test_contract_maps_inf_and_nan_to_none():
    assert clean_score(float("-inf")) is None and clean_score(float("nan")) is None
    d = EvalOutcome(score=float("-inf"), insights=[("x", "y")]).to_contract()
    validate_contract(d)
    assert d["scores"]["scores"][0]["score"] is None


def test_contract_evaluator_on_seed_and_broken_candidate():
    ev = make_contract_evaluator(SPEC, "train")
    good = ev({"content": {"files": [{"path": "program.py", "content": SPEC.seed_src}]}})
    validate_contract(good)
    assert isinstance(good["scores"]["scores"][0]["score"], float) and math.isfinite(good["scores"]["scores"][0]["score"])
    bad = ev({"content": {"files": [{"path": "program.py", "content": swap_block(SPEC.seed_src, "def price_book(c, m):\n    return 1 / 0\n")}]}})
    validate_contract(bad)
    assert bad["scores"]["scores"][0]["score"] is None
    assert "ZeroDivisionError" in bad["insights"]["insights"][0]["text"]
    missing = ev({"content": {}})
    assert missing["scores"]["scores"][0]["score"] is None
