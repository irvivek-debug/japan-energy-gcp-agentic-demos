"""Baseline lock refuses broken evaluators; budget is enforced; evidence is never overwritten; promotion needs all four."""
from datetime import datetime, timezone

import pytest

from energy_lab.config import SOURCE_ALPHAEVOLVE, SOURCE_LOCAL
from energy_lab.harness import baseline as bl
from energy_lab.harness.budget import BudgetExceeded, BudgetPolicy, Ledger, PlateauTracker
from energy_lab.harness.contract import EvalOutcome
from energy_lab.harness.evidence import EvidenceExists, EvidenceWriter, append_review, promotion_gate, reviews_for
from energy_lab.problems import get_problem

SPEC = get_problem("tariff_pricing")


def test_baseline_reproduces_on_frozen_instance():
    r = bl.verify_baseline(SPEC)
    assert r["reproduced"] and r["seed_raw"] != r["null_raw"]


def test_baseline_refuses_evaluator_that_cannot_separate_seed_from_null(tmp_path):
    """Isolates the seed == null check: both reproduce their (equal) locked values, so only that check can refuse."""
    import dataclasses
    import json
    import shutil

    seed_p, null_p = tmp_path / "seed_program.py", tmp_path / "null_program.py"
    shutil.copy(SPEC.seed_path, seed_p)
    shutil.copy(SPEC.null_path, null_p)
    fake = dataclasses.replace(SPEC, seed_path=seed_p, null_path=null_p)
    lock = json.loads(SPEC.baseline_lock_path.read_text())
    lock.update(seed_raw=5.0, null_raw=5.0, null_valid=True)
    fake.baseline_lock_path.write_text(json.dumps(lock))
    const = lambda src, fold="train": EvalOutcome(score=5.0, raw_score=5.0)  # noqa: E731
    with pytest.raises(bl.BaselineLockError) as e:
        bl.verify_baseline(fake, evaluate=const)
    assert "cannot separate them" in str(e.value) and "does not reproduce" not in str(e.value)


def test_baseline_refuses_drifting_evaluator():
    def drift(src, fold="train"):
        o = SPEC.evaluate(src, fold=fold)
        o.raw_score = (o.raw_score or 0) + 0.01          # 10,000 JPY of drift
        o.score = o.raw_score if o.score is not None else None
        return o

    with pytest.raises(bl.BaselineLockError) as e:
        bl.verify_baseline(SPEC, evaluate=drift)
    assert "does not reproduce" in str(e.value)


def test_baseline_refuses_changed_instance(monkeypatch):
    real = bl.load_manifest

    def tampered():
        m = real()
        m["instances"]["tariff_pricing_train"] = {**m["instances"]["tariff_pricing_train"], "sha256": "0" * 64}
        return m

    monkeypatch.setattr(bl, "load_manifest", tampered)
    with pytest.raises(bl.BaselineLockError) as e:
        bl.verify_baseline(SPEC)
    assert "instance hash changed" in str(e.value)


def test_budget_ledger_enforces_run_and_day_limits(runs_dir):
    led = Ledger(runs_dir / "ledger.json")
    pol = BudgetPolicy(max_programs_per_run=40, max_programs_per_day=120, max_runs_per_day=4)
    with pytest.raises(BudgetExceeded):
        led.check_can_start("tariff_pricing", 41, pol)
    now = datetime.now(timezone.utc).isoformat()
    for k in range(3):
        led.reserve({"run_id": f"r{k}", "problem": "tariff_pricing", "started": now, "programs": 40})
    with pytest.raises(BudgetExceeded):                      # 120 used + 1 > 120/day
        led.check_can_start("tariff_pricing", 1, pol)
    assert led.check_can_start("jepx_trading", 40, pol)["runs"] == 0   # per-problem ledger
    led.reserve({"run_id": "dry", "problem": "jepx_trading", "started": now, "programs": 40, "counts_against_budget": False})
    assert led.usage("jepx_trading", Ledger.day_of(now))["programs"] == 0


def test_plateau_counts_feasible_only():
    p = PlateauTracker(3, best=10.0)
    for s in (None, None, None, None):
        p.update(s)
    assert p.since == 0 and not p.plateaued                 # invalid neither advance nor reset
    for s in (9.0, None, 9.5, 10.0):
        p.update(s)
    assert p.plateaued
    p.update(11.0)
    assert p.since == 0


def test_evidence_is_never_overwritten(runs_dir):
    started = datetime(2026, 9, 26, 1, 2, 3, tzinfo=timezone.utc)
    w = EvidenceWriter("tariff_pricing", started, runs_dir)
    w.finalize({"schema": "x", "run_id": w.run_id})
    with pytest.raises(EvidenceExists):
        EvidenceWriter("tariff_pricing", started, runs_dir)
    with pytest.raises(FileExistsError):
        w.finalize({"schema": "x", "run_id": w.run_id})


def _rec(source, delta=5.0, uplift=True):
    return {"run_id": "r1", "source": source, "uplift_valid": uplift, "holdout": {"best_id": "p007", "holdout_delta": delta}}


def test_promotion_gate_requires_all_four(runs_dir):
    assert not promotion_gate(_rec(SOURCE_LOCAL), [{"program_id": "p007"}])["evolved"]          # local never counts
    assert not promotion_gate(_rec(SOURCE_ALPHAEVOLVE), [])["evolved"]                           # no human review
    assert not promotion_gate(_rec(SOURCE_ALPHAEVOLVE, delta=-1.0), [{"program_id": "p007"}])["evolved"]
    assert not promotion_gate(_rec(SOURCE_ALPHAEVOLVE, uplift=False), [{"program_id": "p007"}])["evolved"]
    assert not promotion_gate(_rec(SOURCE_ALPHAEVOLVE, uplift=None), [{"program_id": "p007"}])["evolved"]
    assert not promotion_gate(_rec(SOURCE_ALPHAEVOLVE), [{"program_id": "other"}])["evolved"]    # review of another block
    assert promotion_gate(_rec(SOURCE_ALPHAEVOLVE), [{"program_id": "p007"}])["evolved"]
    append_review("r1", "p007", "tester", "read it", runs_dir)
    assert len(reviews_for("r1", runs_dir)) == 1


class _DeadMutator:
    kind = "dead"

    def generate(self, model, system, prompt):
        from energy_lab.harness.llm import Generation

        return Generation(text="", model=model, error="RefreshError: Reauthentication is needed.")


def test_circuit_breaker_stops_on_consecutive_generation_errors(runs_dir):
    from energy_lab.harness.local_controller import MAX_CONSECUTIVE_GENERATION_ERRORS, LocalController
    from energy_lab.problems import get_problem

    pol = BudgetPolicy(max_programs_per_run=40, concurrency=1)
    rec = LocalController(get_problem("jepx_trading"), _DeadMutator(), policy=pol, ledger=Ledger(runs_dir / "l.json"),
                          runs_dir=runs_dir, dry_run=True, log=lambda *a: None).run()
    assert rec["budget"]["stopped_reason"] == "generation_errors"
    assert rec["budget"]["programs_evaluated"] == MAX_CONSECUTIVE_GENERATION_ERRORS


def test_preflight_refuses_before_any_budget_is_reserved(runs_dir):
    from energy_lab.harness.llm import GenerationUnavailable
    from energy_lab.harness.local_controller import LocalController
    from energy_lab.problems import get_problem

    class NoCreds(_DeadMutator):
        def preflight(self):
            raise GenerationUnavailable("model credentials unusable: RefreshError")

    led = Ledger(runs_dir / "l.json")
    with pytest.raises(GenerationUnavailable):
        LocalController(get_problem("tariff_pricing"), NoCreds(), ledger=led, runs_dir=runs_dir, log=lambda *a: None).run()
    assert led.all() == [] and not list(runs_dir.glob("*.json"))
