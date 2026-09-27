"""Per-segment churn judgment detail for tariff runs judged with a sampling margin (evaluator v4, holdout3).

Recomputed deterministically, with no model call: every saved top-k program of the run is executed again in the sandbox
on the train fold and on the holdout fold, settled with the evaluator's own model, and each customer segment is tested
under both rule sets:

* point rules (v3 style): rise vs the incumbent book <= 5 pp, segment churn <= the fold's point limit (25% on holdout,
  22% train guard band);
* margin rules (v4, docs/PREREGISTRATION_tariff_v4.md section 2): the same limits plus z x the paired standard error
  (pooled sd below n_min customers). The margin is applied only on the folds listed in model.MARGIN_FOLDS; on the
  train fold it is reported for information.

The result is a derived analysis file ``runs/analysis/<run_id>.segment_judgments.json`` (created once, never
overwritten). The run's evidence file is only read; its SHA-256 is recorded and checked on every later use. Before
anything is written, the recomputation is checked against the evidence: holdout segment tests equal the ones the run
stored, holdout validity equals the run's, every top-k candidate is valid on train.

The caveat text is built by pure functions from these numbers, so the same words reach the lab tables, the analyst's
tools and the UI, and no figure is typed by hand.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

TOL = 1e-9


class JudgmentMismatch(RuntimeError):
    """The recomputation disagrees with the run's evidence: nothing is written."""


# ---------------------------------------------------------------------------------------------------------------- facts
def margin_judged(rec: dict) -> bool:
    """True for a searched tariff run whose holdout fold was judged with the sampling margin by the current code."""
    from .problems.tariff_pricing import model as tm

    if rec.get("problem") != "tariff_pricing" or rec.get("status") != "finished":
        return False
    kinds = rec.get("invalid_by_kind") or {}
    if (rec.get("valid_count") or 0) == 0 and kinds and set(kinds) <= {"generation"}:
        return False                                   # zero-program attempt: nothing to judge
    fold = (rec.get("holdout") or {}).get("fold")
    return fold in tm.MARGIN_FOLDS and rec.get("evaluator_version") == tm.EVALUATOR_VERSION


def _file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _segment_row(t: dict, point_level_limit: float, z: float, rise_max: float) -> dict:
    """Both rule sets for one segment. Margin limit = point limit + z x paired SE (pre-registered formula)."""
    m_rise = rise_max + z * t["se_rise"]
    m_level = point_level_limit + z * t["se_level"]
    pr, pl = t["rise"] <= rise_max + TOL, t["churn"] <= point_level_limit + TOL
    mr, ml = t["rise"] <= m_rise + TOL, t["churn"] <= m_level + TOL
    return {"segment": t["segment"], "n": t["n"], "pooled_sd": bool(t["pooled_sd"]), "incumbent_churn": t["incumbent_churn"],
            "churn": t["churn"], "rise": t["rise"], "se_rise": t["se_rise"], "se_level": t["se_level"],
            "point_rise_limit": rise_max, "margin_rise_limit": m_rise, "point_level_limit": point_level_limit,
            "margin_level_limit": m_level, "passes_point_rise": pr, "passes_point_level": pl, "passes_point": pr and pl,
            "passes_margin_rise": mr, "passes_margin_level": ml, "passes_margin": mr and ml,
            "relies_on_margin": (mr and ml) and not (pr and pl)}


def _judge_fold(src: str, fold: str) -> dict:
    """Run one program on one fold (sandboxed) and judge every segment under both rule sets. Deterministic."""
    from .harness.sandbox import SandboxSession
    from .problems.base import load_instance
    from .problems.tariff_pricing import evaluator as tev
    from .problems.tariff_pricing import model as tm

    _, sha = load_instance(f"tariff_pricing_{fold}")
    pre, feats, market = tev._prepared(fold, sha)
    with SandboxSession(src, tev.LIMITS) as sb:
        sb.put("market", market)
        offers = sb.map("price_book", feats, shared=("market",))
    errs = tev._validate(offers, len(feats))
    if errs:
        return {"fold": fold, "instance_sha256": sha, "error": "; ".join(errs)[:500]}
    o = tm.offers_to_arrays(offers)
    res = tm.settle(pre, o, market["segment_reference_jpy_kwh"])
    inc = tev._incumbent(fold, sha)
    lim = tev.churn_limits(fold)
    segs = [_segment_row(t, lim["churn_max_segment"], tm.MARGIN_Z, tm.SEGMENT_CHURN_RISE_MAX)
            for t in tev.segment_margin_tests(pre.seg_idx, inc["P"], res["P"])]
    other = []
    for pol in tev.POLICIES:
        if pol is not tev.policy_churn:
            ok, detail = pol(pre, o, feats, market, res)
            if not ok:
                other.append(detail["invariant"])
    port = {"churn_count": res["churn_count"], "churn_energy": res["churn_energy"],
            "limit_count": lim["churn_max_portfolio"], "limit_energy": lim["churn_max_energy"]}
    port["passes"] = (res["churn_count"] <= lim["churn_max_portfolio"] + TOL and res["churn_energy"] <= lim["churn_max_energy"] + TOL)
    base = not other and port["passes"]
    rule = "margin" if fold in tm.MARGIN_FOLDS else "point"
    valid_point = base and all(s["passes_point"] for s in segs)
    valid_margin = base and all(s["passes_margin"] for s in segs)
    return {"fold": fold, "instance_sha256": sha, "rule_applied": rule, "score": res["score"], "segments": segs,
            "portfolio": port, "other_invariants_failed": other, "valid_point": valid_point, "valid_margin": valid_margin,
            "valid_under_applied_rule": valid_margin if rule == "margin" else valid_point}


def compute(rec: dict, evidence_file: Path) -> dict:
    """Recompute the judgment detail for every top-k candidate of a margin-judged run and check it against the evidence."""
    from .harness.package import assemble
    from .problems import get_problem
    from .problems.tariff_pricing import model as tm

    spec = get_problem("tariff_pricing")
    progs = {p["id"]: p for p in rec["programs"]}
    ho = rec["holdout"]
    cands, problems = [], []
    for rank, row in enumerate(ho.get("top_k", []), 1):
        p = progs[row["id"]]
        src = assemble(spec.seed_program.prefix, p["block"], spec.seed_program.suffix)
        tr, hd = _judge_fold(src, "train"), _judge_fold(src, ho["fold"])
        cands.append({"rank": rank, "id": row["id"], "is_champion": row["id"] == ho.get("best_id"),
                      "block_sha": p.get("block_sha"), "folds": {"train": tr, "holdout": hd}})
        # --- the recomputation must reproduce what the run recorded
        if hd.get("valid_under_applied_rule") is not bool(row.get("holdout_valid")):
            problems.append(f"{row['id']}: holdout validity {hd.get('valid_under_applied_rule')} != evidence {row.get('holdout_valid')}")
        if not tr.get("valid_under_applied_rule"):
            problems.append(f"{row['id']}: not valid on train under the train rules, but it is in the run's top-k")
        stored = {t["segment"]: t for t in (row.get("holdout_segment_tests") or [])}
        for s in hd.get("segments", []):
            t = stored.get(s["segment"])
            if t is None:
                problems.append(f"{row['id']}: no stored holdout test for {s['segment']}")
                continue
            for a, b in (("rise", "rise"), ("churn", "churn"), ("se_rise", "se_rise"), ("se_level", "se_level"),
                         ("margin_rise_limit", "rise_limit"), ("margin_level_limit", "level_limit")):
                if abs(s[a] - t[b]) > 1e-9:
                    problems.append(f"{row['id']} {s['segment']}: {a} {s[a]!r} != stored {b} {t[b]!r}")
            if s["passes_margin"] is not bool(t["pass"]):
                problems.append(f"{row['id']} {s['segment']}: margin pass {s['passes_margin']} != stored {t['pass']}")
    if problems:
        raise JudgmentMismatch("; ".join(problems[:8]))
    return {"run_id": rec["run_id"], "created": datetime.now(timezone.utc).isoformat(),
            "evidence_file": evidence_file.name, "evidence_sha256": _file_sha(evidence_file),
            "evaluator_version": tm.EVALUATOR_VERSION, "holdout_fold": ho["fold"], "best_id": ho.get("best_id"),
            "uplift_valid": rec.get("uplift_valid"), "z": tm.MARGIN_Z, "n_min": tm.MARGIN_N_MIN,
            "method": "every top-k program re-executed in the sandbox on train and holdout; no model call",
            "checks": {"holdout_segment_tests_match_evidence": True, "holdout_validity_matches_evidence": True,
                       "all_top_k_valid_on_train": True},
            "candidates": cands}


def load_or_compute(rec: dict, runs_dir: Path) -> dict | None:
    """The run's judgment file: read it if present (after checking the evidence is unchanged), else compute and create it."""
    if not margin_judged(rec):
        return None
    ev = runs_dir / f"{rec['run_id']}.json"
    out = runs_dir / "analysis" / f"{rec['run_id']}.segment_judgments.json"
    if out.exists():
        j = json.loads(out.read_text())
        if ev.exists() and j.get("evidence_sha256") != _file_sha(ev):
            raise JudgmentMismatch(f"{ev.name} changed since {out.name} was computed; evidence files must never change")
        return j
    j = compute(rec, ev)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x") as f:                            # created once, never overwritten
        json.dump(j, f, indent=1)
    return j


# ------------------------------------------------------------------------------------------------------------- wording
def _pp(x: float) -> str:
    return f"{x * 100:.1f}"


def _ranks(ranks: list[int]) -> str:
    if not ranks:
        return "none"
    rs = sorted(ranks)
    if rs == list(range(rs[0], rs[-1] + 1)) and len(rs) > 1:
        return f"{rs[0]}-{rs[-1]}"
    return ", ".join(str(r) for r in rs)


def _seg_detail(s: dict, kind: str) -> str:
    """kind 'margin_only': what passes only with the margin; 'fails': what fails even with it."""
    parts = []
    if kind == "margin_only":
        if not s["passes_point_rise"]:
            parts.append(f"rise {s['rise'] * 100:+.1f} pp > {_pp(s['point_rise_limit'])} pp point limit, "
                         f"<= {_pp(s['margin_rise_limit'])} pp margin limit")
        if not s["passes_point_level"]:
            parts.append(f"churn {_pp(s['churn'])}% > {_pp(s['point_level_limit'])}% point limit, "
                         f"<= {_pp(s['margin_level_limit'])}% margin limit")
    else:
        if not s["passes_margin_rise"]:
            parts.append(f"rise {s['rise'] * 100:+.1f} pp > {_pp(s['margin_rise_limit'])} pp margin limit")
        if not s["passes_margin_level"]:
            parts.append(f"churn {_pp(s['churn'])}% > {_pp(s['margin_level_limit'])}% margin limit")
    return f"{s['segment']} (n={s['n']}) " + " and ".join(parts)


def candidate_note(hd: dict) -> str:
    """judgment_note for one lab_holdout row, from its holdout-fold judgment."""
    if not hd or hd.get("error"):
        return f"not judged: {(hd or {}).get('error', 'no judgment')}"
    if hd["valid_margin"]:
        relies = [s for s in hd["segments"] if s["relies_on_margin"]]
        if relies:
            return "passes only under the pre-registered sampling margin: " + "; ".join(_seg_detail(s, "margin_only") for s in relies)
        return "passes the point-estimate rules too; no segment relies on the sampling margin"
    why = [_seg_detail(s, "fails") for s in hd["segments"] if not s["passes_margin"]]
    if not hd["portfolio"]["passes"]:
        why.append(f"portfolio churn {_pp(hd['portfolio']['churn_count'])}% by count / {_pp(hd['portfolio']['churn_energy'])}% "
                   f"by energy vs {_pp(hd['portfolio']['limit_count'])}% limits")
    why += [f"invariant {x}" for x in hd["other_invariants_failed"]]
    return "invalid even with the sampling margin: " + "; ".join(why)


def run_caveat(cands: list[dict], best_id: str | None, uplift_valid) -> str | None:
    """The uplift caveat for a run: set only when a validated champion passes a segment rule only thanks to the margin.

    ``cands``: [{"rank", "id", "holdout": {"segments": [...], "valid_point", "valid_margin"}}].
    """
    if not uplift_valid:
        return None
    champ = next((c for c in cands if c["id"] == best_id), None)
    if not champ:
        return None
    relies = [s for s in champ["holdout"]["segments"] if s["relies_on_margin"]]
    if not relies:
        return None
    k = len(cands)
    margin_only = [c["rank"] for c in cands if c["holdout"]["valid_margin"] and not c["holdout"]["valid_point"]]
    both = [c["rank"] for c in cands if c["holdout"]["valid_point"]]
    neither = [c["rank"] for c in cands if not c["holdout"]["valid_margin"]]
    text = ("passes only under the pre-registered sampling margin: " + "; ".join(_seg_detail(s, "margin_only") for s in relies)
            + f"; under v3 point rules rank{'s' if len(margin_only) > 1 else ''} {_ranks(margin_only)} of the top {k} "
            f"would be invalid")
    if both:
        text += f" (rank{'s' if len(both) > 1 else ''} {_ranks(both)} pass both rule sets)"
    if neither:
        text += f"; rank{'s' if len(neither) > 1 else ''} {_ranks(neither)} fail both"
    return text


def candidates_from_judgment(j: dict) -> list[dict]:
    return [{"rank": c["rank"], "id": c["id"], "holdout": c["folds"]["holdout"]} for c in j["candidates"]]


def candidates_from_evidence(rec: dict) -> list[dict]:
    """The same candidate structure rebuilt from the run's stored holdout segment tests (no re-execution).

    Used by the UI server, which reads evidence files; it gives the same words as the recomputed table because the
    recomputation is checked to reproduce these stored tests. Segment-level only: a candidate invalid on holdout for any
    reason is invalid under both rule sets (the point rules are never looser than the margin rules)."""
    from .problems.tariff_pricing import evaluator as tev
    from .problems.tariff_pricing import model as tm

    ho = rec.get("holdout") or {}
    lim = tev.churn_limits(ho.get("fold") or "holdout")["churn_max_segment"]
    out = []
    for rank, row in enumerate(ho.get("top_k", []), 1):
        segs = [_segment_row(t, lim, tm.MARGIN_Z, tm.SEGMENT_CHURN_RISE_MAX) for t in (row.get("holdout_segment_tests") or [])]
        vm = bool(row.get("holdout_valid"))
        out.append({"rank": rank, "id": row["id"],
                    "holdout": {"segments": segs, "valid_margin": vm, "valid_point": vm and all(s["passes_point"] for s in segs)}})
    return out


def evidence_caveat(rec: dict) -> str | None:
    """run_caveat computed from a margin-judged run's evidence file (UI server path)."""
    if not margin_judged(rec):
        return None
    ho = rec.get("holdout") or {}
    return run_caveat(candidates_from_evidence(rec), ho.get("best_id"), rec.get("uplift_valid"))


# ---------------------------------------------------------------------------------------------------------- table rows
def table_rows(rec: dict, j: dict) -> list[dict]:
    """lab_segment_judgments rows: one per (candidate, fold, segment)."""
    rows = []
    for c in j["candidates"]:
        for role, fd in c["folds"].items():
            for s in fd.get("segments", []):
                rows.append({"run_id": rec["run_id"], "problem": rec["problem"], "rank": c["rank"], "program_id": c["id"],
                             "is_champion": c["is_champion"], "fold_role": role, "fold": fd["fold"],
                             "rule_applied": fd["rule_applied"], "instance_sha": fd["instance_sha256"], **s,
                             "candidate_valid_point": fd["valid_point"], "candidate_valid_margin": fd["valid_margin"],
                             "valid_under_applied_rule": fd["valid_under_applied_rule"]})
    return rows
