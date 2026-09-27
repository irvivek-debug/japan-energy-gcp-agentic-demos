"""One command for the pre-registered tariff follow-up (docs/PREREGISTRATION_tariff_v4.md).

    GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=<project> \\
        python -m energy_lab.followup tariff_v4

Does, in order, and refuses at the first failed guard:
  1. credentials usable (no model call spent), 2. holdout3 content hash equals the pre-registered hash, evaluator v4 is
  the judging code, 3. at most one restart after the infrastructure-failed attempt (pre-registration section 6),
  4. baseline lock reproduces, 5. budget ledger admits 40 programs,
  6. the 40-program local-controller run (controller seed 23) with top-5 holdout3 rescoring and its evidence file,
  7. secondary analyses (pre-registration section 5) into runs/analysis/<run_id>.secondary_v4.json (new file),
  8. lab_* export, 9. RESULTS.md: result section filled from the evidence by template, tables and figures re-rendered.
Nothing here decides anything the pre-registration did not fix.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from .config import ROOT, RUNS_DIR
from .harness.evidence import list_evidence

PREREG = ROOT / "docs" / "PREREGISTRATION_tariff_v4.md"
RESULTS = ROOT / "docs" / "RESULTS.md"
CONTROLLER_SEED = 23
# Pre-registration section 6 as amended in Addendum 3: attempts in which no program was generated (infrastructure or
# operator failures) never evaluated a candidate on holdout3 and do not count; exactly ONE searched attempt is allowed.


def _is_infra(r: dict) -> bool:
    kinds = r.get("invalid_by_kind") or {}
    return (r.get("valid_count") or 0) == 0 and bool(kinds) and set(kinds) <= {"generation"}


def v4_attempts() -> list[dict]:
    return [r for r in list_evidence(RUNS_DIR, include_partial=False)
            if r.get("problem") == "tariff_pricing" and str(r.get("evaluator_version", "")).startswith("tariff_pricing/v4")]


def guards(log=print) -> None:
    from .harness.baseline import verify_baseline
    from .harness.budget import BudgetPolicy, Ledger
    from .harness.llm import GeminiMutator
    from .problems import get_problem
    from .problems.base import load_instance
    from .problems.tariff_pricing import model as tm

    GeminiMutator().preflight()
    log("credentials: usable")
    spec = get_problem("tariff_pricing")
    if spec.holdout_fold != "holdout3" or not tm.EVALUATOR_VERSION.startswith("tariff_pricing/v4"):
        raise SystemExit("REFUSED: the judging code is not evaluator v4 on holdout3")
    _, sha = load_instance("tariff_pricing_holdout3")
    if sha not in PREREG.read_text():
        raise SystemExit(f"REFUSED: holdout3 content hash {sha[:16]} is not the pre-registered one")
    log(f"holdout3 hash matches the pre-registration: {sha[:16]}")
    done = [r for r in v4_attempts() if not _is_infra(r)]
    if done:
        raise SystemExit(f"REFUSED: the pre-registered run already took place ({done[0]['run_id']}); no second run on holdout3")
    infra = [r["run_id"] for r in v4_attempts() if _is_infra(r)]
    if infra:
        log(f"earlier zero-program attempts (no candidate touched holdout3): {infra}")
    lock = verify_baseline(spec)
    log(f"baseline reproduced: seed {lock['seed_raw']:.3f}, null {lock['null_raw']:.3f}")
    state = Ledger().check_can_start("tariff_pricing", 40, BudgetPolicy.from_env())
    log(f"budget admits the run: {state}")


def secondary(rec: dict) -> dict:
    """Pre-registration section 5: v3 point-estimate rules on holdout3 for the top 5; per-segment table; max top 5."""
    from .harness.package import assemble
    from .problems import get_problem
    from .problems.tariff_pricing import evaluator as tev
    from .problems.tariff_pricing import model as tm

    spec = get_problem("tariff_pricing")
    progs = {p["id"]: p for p in rec["programs"]}
    ho = rec["holdout"]
    saved = tm.MARGIN_FOLDS
    rows = []
    try:
        tm.MARGIN_FOLDS = ()                       # judge holdout3 with the v3 point-estimate segment rules
        for row in ho["top_k"]:
            src = assemble(spec.seed_program.prefix, progs[row["id"]]["block"], spec.seed_program.suffix)
            o = tev.evaluate(src, "holdout3")
            rows.append({"id": row["id"], "train": row["train"], "v4_holdout3": row["holdout"], "v3_rules_holdout3": o.score,
                         "v3_rules_valid": o.valid, "v3_rules_first_insight": (o.insights[0][1] if o.insights else "")[:300]})
    finally:
        tm.MARGIN_FOLDS = saved
    champ = next((r for r in ho["top_k"] if r["id"] == ho.get("best_id")), None)
    return {"run_id": rec["run_id"], "created": datetime.now(timezone.utc).isoformat(),
            "prereg": "docs/PREREGISTRATION_tariff_v4.md section 5 (reported, never used to claim success)",
            "v3_point_estimate_rules_on_holdout3": rows,
            "champion_segment_table_v4": (champ or {}).get("holdout_segment_tests"),
            "max_holdout3_in_top5": ho.get("max_holdout_in_top_k"), "max_holdout3_id": ho.get("max_holdout_id"),
            "max_note": "selection-biased: chosen on holdout3; not citable"}


def _f(x) -> str:
    return "none" if x is None else f"{x:,.1f}"


def result_section(rec: dict, sec: dict) -> str:
    ho = rec["holdout"]
    champ = next((r for r in ho["top_k"] if r["id"] == ho.get("best_id")), None) or {}
    success = bool(rec.get("uplift_valid"))
    tok = rec.get("tokens") or {}
    fails = [t for t in (champ.get("holdout_segment_tests") or []) if not t["pass"]]
    lines = [f"**Pre-registered run 4 result (`{rec['run_id']}`, filled by `python -m energy_lab.followup tariff_v4`).**",
             "",
             f"* Primary criterion (champion valid on holdout3 and holdout delta > 0): **{'MET' if success else 'NOT MET'}**; "
             f"uplift_valid = {rec.get('uplift_valid')}; note: {rec.get('uplift_note')}.",
             f"* Train: seed {rec['seed']['train']:,.1f} -> best {rec['best']['train']:,.1f} JPY M "
             f"({rec['budget']['programs_evaluated']} programs, {rec['valid_count']} valid, invalid by kind {rec.get('invalid_by_kind')}).",
             f"* holdout3: seed {_f(ho['seed'])}; champion `{ho.get('best_id')}` "
             f"{_f(ho.get('best_holdout')) if ho.get('best_holdout') is not None else 'invalid on holdout3'}; "
             f"holdout delta {_f(ho.get('holdout_delta'))} JPY M.",
             f"* Segments failing the v4 rule for the champion: {', '.join(t['segment'] + ' (n ' + str(t['n']) + ')' for t in fails) or 'none'}.",
             f"* Secondary (not a success claim): v3 point-estimate rules on holdout3, champion valid = "
             f"{next((r['v3_rules_valid'] for r in sec['v3_point_estimate_rules_on_holdout3'] if r['id'] == ho.get('best_id')), None)}; "
             f"max holdout3 score in the top 5 = {_f(sec['max_holdout3_in_top5'])} ({sec['max_note']}).",
             f"* Cost: {tok.get('calls')} model calls, {tok.get('prompt', 0):,} prompt / {tok.get('output', 0):,} output / "
             f"{tok.get('thinking', 0):,} thinking tokens, USD {tok.get('cost_usd', 0):.2f} estimated.",
             f"* Evidence: `runs/{rec['run_id']}.json`; secondary analyses: `runs/analysis/{rec['run_id']}.secondary_v4.json`.",
             "* local controller, not the managed AlphaEvolve service; evolved stays false."]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    if argv[:1] != ["tariff_v4"]:
        print(__doc__)
        return 1
    try:
        guards()
    except SystemExit as e:
        print(e)
        return 2
    except Exception as e:  # noqa: BLE001  (GenerationUnavailable, BaselineLockError, BudgetExceeded)
        print(f"REFUSED: {type(e).__name__}: {e}")
        return 2
    from .export_evidence import export_all
    from .harness.local_controller import run_local
    from .problems import get_problem

    rec = run_local(get_problem("tariff_pricing"), max_programs=40, islands=3, rng_seed=CONTROLLER_SEED)
    sec = secondary(rec) if not _is_infra(rec) else {"run_id": rec["run_id"], "note": "infrastructure failure, no analyses"}
    out = RUNS_DIR / "analysis" / f"{rec['run_id']}.secondary_v4.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x") as f:
        json.dump(sec, f, indent=1, default=str)
    export_all()
    text = RESULTS.read_text()
    block = result_section(rec, sec) if not _is_infra(rec) else f"Restart `{rec['run_id']}` also failed for an infrastructure reason; see its evidence."
    text = re.sub(r"<!-- RUN4_RESULT -->.*?<!-- /RUN4_RESULT -->", lambda m: f"<!-- RUN4_RESULT -->\n{block}\n<!-- /RUN4_RESULT -->", text, flags=re.S)
    RESULTS.write_text(text)
    for script in ("data/render_results.py",):
        subprocess.run([sys.executable, str(ROOT / script)], check=True, cwd=ROOT)
    print(block)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
