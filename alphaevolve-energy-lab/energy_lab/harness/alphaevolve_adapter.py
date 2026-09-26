"""Production path: run the SAME problem through Google's AlphaEvolve service (Gemini Enterprise Agent Platform).

Status in this repository: NOT executed. The user's project has no Gemini Enterprise app with AlphaEvolve provisioned
(AlphaEvolve on Google Cloud has been generally available since 2026-07-10; MARKET_FACTS 11). Everything this adapter
needs from the lab is shared with the local controller, so switching is one flag:

    GE_APP_ID=<engine id> python -m energy_lab.harness.run --problem tariff_pricing --backend alphaevolve

Prerequisites (from the alphaevolve skill, verified against alpha_evolve 0.1.0):
  * a Gemini Enterprise app with AlphaEvolve provisioned; REST surface discoveryengine.googleapis.com, location
    ``global``; models at ``global`` (balanced / reasoning tiers from model_policy)
  * ``pip install alpha_evolve`` (not pinned in requirements.txt: the package ships with the GE provisioning)
  * ADC from an interactive human login; never a key. GOOGLE_CLOUD_PROJECT and GE_APP_ID from env.
Contract details that matter:
  * the initial program must arrive WITH its evaluation attached (platform rejects a bare seed)
  * candidates handed to the evaluator carry only content; ``None`` marks invalid; -inf is mapped to None
  * the platform stops only on its evaluated-count criterion, so wall clock and plateau are enforced here: the loop runs
    under an asyncio timeout, and on plateau ``exp.max_programs_evaluated`` is pulled down to ``evaluated + 1``
  * baseline lock, budget ledger, holdout rescoring and the evidence schema are identical to the local controller;
    evidence records ``source: "alphaevolve"`` and ``evolved`` can flip only via harness.evidence.promotion_gate
"""
from __future__ import annotations

import asyncio
import os
import threading
import time
from datetime import datetime, timezone

from .. import model_policy
from ..config import SOURCE_ALPHAEVOLVE
from ..problems.base import ProblemSpec
from .baseline import verify_baseline
from .budget import BudgetPolicy, Ledger, PlateauTracker
from .contract import EvalOutcome, primary_score
from .evaluate import evaluate_candidate, make_contract_evaluator
from .evidence import EvidenceWriter
from .package import split_program

try:  # guarded: the lab runs without the client installed
    from alpha_evolve.client import AlphaEvolveClient  # type: ignore
    from alpha_evolve.controller import run_controller_loop  # type: ignore
    from alpha_evolve.experiment import AlphaEvolveExperiment  # type: ignore

    AVAILABLE = True
except Exception:  # noqa: BLE001
    AlphaEvolveClient = AlphaEvolveExperiment = run_controller_loop = None
    AVAILABLE = False


class AlphaEvolveUnavailable(RuntimeError):
    pass


def config_from_env() -> dict:
    return {"project_id": os.environ.get("GOOGLE_CLOUD_PROJECT"), "location": "global",
            "collection": os.environ.get("GE_COLLECTION", "default_collection"), "engine": os.environ.get("GE_APP_ID"),
            "assistant": os.environ.get("GE_ASSISTANT", "default_assistant")}


def preflight() -> dict:
    cfg = config_from_env()
    missing = [k for k in ("project_id", "engine") if not cfg[k]]
    status = {"client_installed": AVAILABLE, "missing_env": missing, "ready": AVAILABLE and not missing}
    return status


def run_alphaevolve(spec: ProblemSpec, *, max_programs: int | None = None, policy: BudgetPolicy | None = None,
                    ledger: Ledger | None = None, log=print) -> dict:
    """End-to-end production run. Raises AlphaEvolveUnavailable with the exact missing prerequisite."""
    pf = preflight()
    if not pf["ready"]:
        raise AlphaEvolveUnavailable(
            "AlphaEvolve backend not ready: " + ("alpha_evolve client not installed; " if not pf["client_installed"] else "")
            + (f"missing env {pf['missing_env']} (needs a Gemini Enterprise app with AlphaEvolve provisioned)" if pf["missing_env"] else ""))
    policy = policy or BudgetPolicy.from_env()
    ledger = ledger or Ledger()
    n = min(max_programs or policy.max_programs_per_run, policy.max_programs_per_run)
    lock = verify_baseline(spec)
    ledger.check_can_start(spec.name, n, policy)
    started = datetime.now(timezone.utc)
    writer = EvidenceWriter(spec.name, started)
    ledger.reserve({"run_id": writer.run_id, "problem": spec.name, "started": started.isoformat(), "source": SOURCE_ALPHAEVOLVE,
                    "programs": n, "counts_against_budget": True})
    seen: list[tuple[str, EvalOutcome]] = []
    plateau = PlateauTracker(policy.plateau_patience, lock["seed_score"])
    exp_ref: dict = {}
    mtx = threading.Lock()

    def on_result(src: str, out: EvalOutcome) -> None:  # bookkeeping + plateau enforcement
        with mtx:
            seen.append((src, out))
            if plateau.update(out.score) and "exp" in exp_ref:
                exp_ref["exp"].max_programs_evaluated = len(seen) + 1
                exp_ref["stop"] = "plateau"

    cfg = config_from_env()
    client = AlphaEvolveClient(**cfg)
    evaluate = make_contract_evaluator(spec, "train", on_result=on_result)
    exp = AlphaEvolveExperiment(ae_client=client, evaluator_function=evaluate, max_programs_evaluated=n,
                                parallel_evaluation=False)
    exp_ref["exp"] = exp
    exp.create_experiment({"title": f"KBG {spec.title}", "problem_description": spec.description, "program_language": "python",
                           "run_settings": {"max_programs": n, "concurrency": policy.concurrency},
                           "generation_settings": {"models": model_policy.mutator_mix()}})
    seed = {"content": {"files": [{"path": "program.py", "content": spec.seed_src}]}}
    seed_score = primary_score(exp.evaluator_client(seed))
    exp.create_initial_program({**seed, "evaluation": {"scores": {"scores": [{"metric": "score", "score": seed_score}]}}})
    exp.start_experiment()
    t0 = time.monotonic()
    stop = "max_programs"
    try:
        asyncio.run(asyncio.wait_for(run_controller_loop(exp), timeout=policy.max_wall_s))
    except asyncio.TimeoutError:
        stop = "wall_clock"
    stop = exp_ref.get("stop", stop)
    # Rescore on holdout with the same rule as the local controller: champion = best TRAIN score.
    valid = sorted([(o.score, src) for src, o in seen if o.valid], key=lambda x: x[0], reverse=True)
    seed_h = evaluate_candidate(spec, spec.seed_src, spec.holdout_fold)
    top = []
    for score, src in valid[:5]:
        o = evaluate_candidate(spec, src, spec.holdout_fold)
        top.append({"train": score, "holdout": o.score, "holdout_valid": o.valid, "block": split_program(src).block})
    best_h = top[0]["holdout"] if top else None
    delta = best_h - seed_h.score if (best_h is not None and seed_h.score is not None) else None
    record = {"schema": "energy_lab.run_evidence/v1", "run_id": writer.run_id, "problem": spec.name, "source": SOURCE_ALPHAEVOLVE,
              "backend": "alphaevolve", "evolved": False, "started": started.isoformat(),
              "finished": datetime.now(timezone.utc).isoformat(), "baseline_lock": lock,
              "budget": {"programs_evaluated": len(seen), "max_programs": n, "wall_s": round(time.monotonic() - t0, 1),
                         "stopped_reason": stop},
              "holdout": {"seed": seed_h.score, "top_k": top, "best_holdout": best_h, "holdout_delta": delta},
              "uplift_valid": (delta is not None and delta > 0 and top[0]["holdout_valid"]) if top else False,
              "note": "evolved flips only after human review via harness.evidence.promotion_gate"}
    path = writer.finalize(record)
    ledger.record(writer.run_id, status="finished", programs=len(seen), stopped_reason=stop, holdout_delta=delta)
    log(f"AlphaEvolve evidence -> {path}")
    return record
