"""Crafted violators must be caught by the tariff policy invariants; disabling a gate must let them through
(mutation check: a test that cannot fail is not a gate)."""
import pytest

from energy_lab.harness.evaluate import evaluate_candidate
from energy_lab.problems import get_problem
from energy_lab.problems.tariff_pricing import evaluator as tev
from energy_lab.problems.tariff_pricing import model as tm

from conftest import swap_block

SPEC = get_problem("tariff_pricing")

BASE = '''def price_book(customer, market):
    margin = 1.5
    energy = energy_cost_jpy_kwh(customer, market)
    other = non_energy_cost_jpy_kwh(customer, market)
    alpha = 0.5 if customer["segment"] == "data_center" else 0.0
    rate = energy + other + margin
    band = 10.0
    {mutation}
    return {{"energy_rate_jpy_kwh": round(rate, 3), "alpha": alpha, "market_adder_jpy_kwh": round(other + margin, 3),
            "demand_charge_jpy_kw_month": round(wheeling_basic_jpy_kw_month(customer, market) + 50.0, 1),
            "deviation_band_pct": band, "deviation_penalty_jpy_kwh": 1.0, "dr_discount_jpy_kw_month": 0.0, "term_years": 1}}
'''

VIOLATORS = {
    "essential_alpha": 'alpha = 0.6 if customer["segment"] in ("hospital", "water_utility") else alpha',
    "deviation_band": "band = 12.0",
    # prices on a customer-identity proxy (contract size parity) instead of cost / segment
    "non_discrimination": 'rate = rate * (1.12 if int(customer["contract_kw"]) % 2 == 0 else 0.9)',
    # churn-driven "uplift": price low-margin, weather-sensitive segments out of the book
    "churn": 'rate = rate * 1.35 if customer["segment"] in ("office", "retail_chain", "hotel", "university") else rate',
    "fair_price_ceiling": 'rate = rate * 1.6 if customer["segment"] == "hospital" else rate',
}


def ev(mutation: str):
    return evaluate_candidate(SPEC, swap_block(SPEC.seed_src, BASE.format(mutation=mutation)), "train")


def test_seed_is_valid_and_base_matches_seed():
    seed = evaluate_candidate(SPEC, SPEC.seed_src, "train")
    base = ev("pass")
    assert seed.valid and base.valid
    assert abs(seed.score - base.score) < 1e-6


@pytest.mark.parametrize("invariant", list(VIOLATORS))
def test_violator_is_caught(invariant):
    out = ev(VIOLATORS[invariant])
    assert out.score is None and out.kind == "policy"
    names = [v["invariant"] for v in out.details["violations"]]
    assert invariant in names, names
    assert any(l.startswith("policy:") for l, _ in out.insights)
    assert out.raw_score is not None          # evidence keeps what it would have scored


def test_churn_violator_would_have_scored_higher_than_seed():
    """The SOL-01 pattern: pricing customers out can raise the raw objective; the invariant must still reject it."""
    seed = evaluate_candidate(SPEC, SPEC.seed_src, "train")
    out = ev('rate = rate * 1.6 if customer["segment"] in ("office", "retail_chain", "hotel", "logistics") else rate')
    assert out.score is None
    assert "churn" in [v["invariant"] for v in out.details["violations"]]
    assert out.raw_score is not None and seed.score is not None


@pytest.mark.parametrize("invariant,policy_fn", [
    ("essential_alpha", "policy_essential_alpha"), ("deviation_band", "policy_band"),
    ("non_discrimination", "policy_nondiscrimination"), ("fair_price_ceiling", "policy_fair_ceiling"),
])
def test_mutation_disabling_gate_lets_violator_through(monkeypatch, invariant, policy_fn):
    monkeypatch.setattr(tev, "POLICIES", tuple(p for p in tev.POLICIES if p.__name__ != policy_fn))
    out = ev(VIOLATORS[invariant])
    names = [v["invariant"] for v in (out.details.get("violations") or [])]
    assert invariant not in names


def test_mutation_relaxed_churn_limit_lets_churn_violator_through(monkeypatch):
    for k in ("churn_max_portfolio", "churn_max_energy", "churn_max_segment"):
        monkeypatch.setitem(tm.POLICY, k, 1.0)
        monkeypatch.setitem(tm.TRAIN_CHURN_GUARD, k, 1.0)
    monkeypatch.setattr(tm, "SEGMENT_CHURN_RISE_MAX", 1.0)
    out = ev(VIOLATORS["churn"])
    assert "churn" not in [v["invariant"] for v in (out.details.get("violations") or [])]


def test_train_guard_band_is_stricter_than_holdout_limit():
    assert tev.churn_limits("train")["churn_max_segment"] < tev.churn_limits("holdout")["churn_max_segment"] == 0.25
    # a book with ~23-24% churn in one segment: rejected on train (guard 22%), judged at 25% on holdout
    ok, _ = tev.policy_churn(None, None, None, None, {"churn_count": 0.1, "churn_energy": 0.1,
                                                     "seg_churn": {"university": 0.235}}, "train")
    ok_h, _ = tev.policy_churn(None, None, None, None, {"churn_count": 0.1, "churn_energy": 0.1,
                                                       "seg_churn": {"university": 0.235}}, "holdout")
    assert not ok and ok_h


def test_format_errors_are_invalid_not_scored():
    out = evaluate_candidate(SPEC, swap_block(SPEC.seed_src, "def price_book(c, m):\n    return {'alpha': 2}\n"), "train")
    assert out.score is None and out.kind == "format"


def test_runtime_determinism_probe_catches_hidden_state():
    # A class attribute used as a call counter passes the static scan; the runtime re-evaluation probe must catch it.
    block = "class _State:\n    n = 0\n\n\n" + BASE.format(mutation="_State.n += 1\n    rate = rate * (1 + _State.n * 1e-6)")
    out = evaluate_candidate(SPEC, swap_block(SPEC.seed_src, block), "train")
    assert out.score is None and out.kind == "determinism"


def test_holdout_fold_uses_unseen_customers_and_scenarios():
    tr = evaluate_candidate(SPEC, SPEC.seed_src, "train")
    ho = evaluate_candidate(SPEC, SPEC.seed_src, "holdout")
    assert tr.details["instance_sha256"] != ho.details["instance_sha256"]
    assert tr.valid and ho.valid
    assert ho.metrics["expected_margin_jpy_m"] < tr.metrics["expected_margin_jpy_m"]   # harsher, realised-like shock


def test_v3_segment_churn_rise_vs_incumbent_is_caught():
    """Repricing one small segment out (university) can stay under the absolute limits; v3 must still reject it."""
    out = ev('rate = rate * 1.09 if customer["segment"] == "university" else rate')
    v = [x for x in out.details.get("violations") or [] if x["invariant"] == "churn"]
    assert out.score is None and v and "above the incumbent book" in v[0]["text"]


def test_v3_mutation_disabling_rise_rule_lets_it_through(monkeypatch):
    monkeypatch.setattr(tm, "SEGMENT_CHURN_RISE_MAX", 1.0)
    out = ev('rate = rate * 1.09 if customer["segment"] == "university" else rate')
    v = [x for x in out.details.get("violations") or [] if x["invariant"] == "churn"]
    assert not v or "above the incumbent book" not in v[0]["text"]


def test_tariff_holdout_moved_to_fresh_fold():
    assert SPEC.holdout_fold == "holdout2"
    h2 = evaluate_candidate(SPEC, SPEC.seed_src, "holdout2")
    h1 = evaluate_candidate(SPEC, SPEC.seed_src, "holdout")
    assert h2.valid and h1.valid and h2.details["instance_sha256"] != h1.details["instance_sha256"]
    assert "v3" in h2.details["evaluator_version"]
