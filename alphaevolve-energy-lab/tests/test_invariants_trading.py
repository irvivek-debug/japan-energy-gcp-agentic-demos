"""Crafted trading violators (intentional imbalance, edge-of-band bias, naked selling, BESS, JEPX bounds) must be
caught with slot-level insights; disabling each gate lets them through; contexts carry no realised future data."""
import json

import numpy as np
import pytest

from energy_lab.harness.evaluate import evaluate_candidate
from energy_lab.problems import get_problem
from energy_lab.problems.base import load_instance
from energy_lab.problems.jepx_trading import sim as tsim

from conftest import swap_block

SPEC = get_problem("jepx_trading")
SEED_BLOCK = SPEC.seed_program.block


def with_da(extra: str) -> str:
    """Insert code before plan_day_ahead's return (bids / plan are in scope)."""
    return SEED_BLOCK.replace('    return {"bids": bids, "bess_plan_mw": plan}', extra + '\n    return {"bids": bids, "bess_plan_mw": plan}')


def with_id(extra: str) -> str:
    """Insert code before adjust_intraday's return (orders / mw / gap / forecast are in scope)."""
    return SEED_BLOCK.replace('    return {"orders": orders, "bess_mw": mw}', extra + '\n    return {"orders": orders, "bess_mw": mw}')


# Leaves slots ~6% short whenever the H-1 reserve margin says "no scarcity": imbalance looks cheaper than spot there.
SHORT_WHEN_CALM = with_id('''    if ctx["forecast_ha"]["reserve_margin"] > 0.12:
        sell = max(0.0, (position + sum(o["qty_mwh"] if o["side"] == "buy" else -o["qty_mwh"] for o in orders)) - 0.94 * forecast)
        orders = [o for o in orders if o["side"] != "buy"]
        buy_now = max(0.0, 0.94 * forecast - position)
        if buy_now > 0:
            orders = [{"side": "buy", "qty_mwh": lots(buy_now, rules), "limit_jpy_kwh": idm["best_ask"] + 2.0}]
        elif position - 0.94 * forecast > rules["lot_mwh"]:
            orders = [{"side": "sell", "qty_mwh": lots(position - 0.94 * forecast, rules), "limit_jpy_kwh": idm["best_bid"] - 2.0}]''')
# Stays inside the per-slot band but always 2.5% short: systematic edge-of-band positioning.
EDGE_OF_BAND = with_id('''    target = 0.975 * forecast
    d = target - position
    orders = []
    if d >= rules["lot_mwh"]:
        orders = [{"side": "buy", "qty_mwh": lots(d, rules), "limit_jpy_kwh": idm["best_ask"] + 2.0}]
    elif d <= -rules["lot_mwh"]:
        orders = [{"side": "sell", "qty_mwh": lots(-d, rules), "limit_jpy_kwh": max(rules["price_floor"], idm["best_bid"] - 2.0)}]''')
NAKED_SELL = with_da('''    bids.append({"slot": 20, "side": "sell", "qty_mwh": 50.0, "limit_jpy_kwh": rules["price_floor"]})''')
BESS_OVER = with_id('''    mw = 80.0''')
BOUNDS = with_da('''    bids.append({"slot": 3, "side": "buy", "qty_mwh": 1.0, "limit_jpy_kwh": 1500.0})''')


def ev(block: str):
    return evaluate_candidate(SPEC, swap_block(SPEC.seed_src, block), "train")


def names(out):
    return [v["invariant"] for v in (out.details.get("violations") or [])]


def test_seed_valid_null_invalid():
    seed = evaluate_candidate(SPEC, SPEC.seed_src, "train")
    null = evaluate_candidate(SPEC, SPEC.null_src, "train")
    assert seed.valid
    assert not null.valid and "intentional_imbalance" in names(null)     # never corrects its D-1 plan


def test_intentional_imbalance_is_caught_with_slot_list():
    out = ev(SHORT_WHEN_CALM)
    assert out.score is None and "intentional_imbalance" in names(out)
    v = next(v for v in out.details["violations"] if v["invariant"] == "intentional_imbalance")
    # the PER-SLOT gate must fire (not only the systematic-bias check): slot-level examples with the tolerance
    per_slot = [e for e in v["examples"] if "planned" in e and "tol" in e and "short" in e]
    assert per_slot, v["examples"]
    assert any(s.startswith("20") and " s" in s for s in v["slots"])     # e.g. "2024-04-08 s36"
    text = next(t for l, t in out.insights if l == "policy: intentional_imbalance")
    assert "slots:" in text
    assert out.raw_score is not None


def test_edge_of_band_bias_is_caught():
    out = ev(EDGE_OF_BAND)
    assert out.score is None
    v = next(v for v in out.details["violations"] if v["invariant"] == "intentional_imbalance")
    assert any("systematic short bias" in e for e in v["examples"])


@pytest.mark.parametrize("block,inv", [(NAKED_SELL, "naked_selling"), (BESS_OVER, "bess_limits"), (BOUNDS, "jepx_bounds")])
def test_other_invariants(block, inv):
    out = ev(block)
    assert out.score is None and inv in names(out)


def test_mutation_widened_tolerance_lets_short_violator_through(monkeypatch):
    orig = tsim.TradingSim.__init__

    def wide(self, arr):
        orig(self, arr)
        self.tol_rel, self.tol_abs = 0.5, 500.0

    monkeypatch.setattr(tsim.TradingSim, "__init__", wide)
    from energy_lab.problems.jepx_trading import evaluator as tev

    tev._sim.cache_clear()
    try:
        out = ev(SHORT_WHEN_CALM)
        assert "intentional_imbalance" not in names(out) or all(
            "systematic" in e for v in out.details["violations"] if v["invariant"] == "intentional_imbalance" for e in v["examples"])
    finally:
        tev._sim.cache_clear()


def test_mutation_disabled_bias_check_lets_edge_of_band_through(monkeypatch):
    monkeypatch.setattr(tsim, "SYSTEMATIC_BIAS_MAX", 1.0)
    out = ev(EDGE_OF_BAND)
    assert "intentional_imbalance" not in names(out)


def test_contexts_contain_no_realised_future_data():
    arr, _ = load_instance("jepx_trading_train")
    poisoned = {k: np.array(v, copy=True) for k, v in arr.items()}
    for k in ("demand_mw", "pv_mw", "imbalance", "rm"):
        poisoned[k] = np.full_like(poisoned[k], np.nan, dtype=np.float64)
    sim = tsim.TradingSim(poisoned)
    for i in (0, 10, 50):
        da = json.dumps(sim.da_ctx(i, 90.0, 1e5))
        assert "NaN" not in da
        # the day's own DA spot is only revealed after the auction; the D-1 context must not contain it
        spot_vals = {f"{x:.2f}" for x in np.asarray(arr["spot"][i], float)}
        ctx = sim.da_ctx(i, 90.0, 1e5)
        assert ctx["recent_prices_jpy_kwh"][-1] != [round(float(x), 3) for x in arr["spot"][i]]
        for t in (0, 20, 47):
            idc = json.dumps(sim.id_ctx(i, t, 100.0, np.asarray(arr["spot"][i], float), 90.0, 0.0, 0.0, [0.0] * 48,
                                        {"net_load_mwh_p50": [0.0] * 48}))
            assert "NaN" not in idc
        assert spot_vals  # sanity
