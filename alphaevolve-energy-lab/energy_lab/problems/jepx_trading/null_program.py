"""KBG balance-group trading strategy: JEPX day-ahead bids, intraday corrections, BESS dispatch.

Only the EVOLVE-BLOCK is searched; the helpers above it are fixed and may be called from the block.
plan_day_ahead(ctx) is called at D-1 10:00; adjust_intraday(ctx_t) at t-1h for each slot t in order.
"""
import math

SLOTS = 48


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def soc_after(soc, mw, bess):
    """State of charge (MWh) after one 30-min slot at mw (+ discharge, - charge)."""
    if mw >= 0:
        return soc - mw * 0.5 / bess["eta_discharge"]
    return soc + (-mw) * 0.5 * bess["eta_charge"]


def feasible_mw(mw, soc, bess, discharged_today=0.0):
    """Clip a requested MW to power rating, SOC window and the daily discharge cap."""
    mw = clamp(mw, -bess["power_mw"], bess["power_mw"])
    if mw >= 0:
        max_by_soc = (soc - bess["soc_min_mwh"]) * bess["eta_discharge"] / 0.5
        max_by_cycles = max(0.0, bess["max_daily_discharge_mwh"] - discharged_today) / 0.5
        return max(0.0, min(mw, max_by_soc, max_by_cycles) - 1e-6)
    max_charge = (bess["soc_max_mwh"] - soc) / (0.5 * bess["eta_charge"])
    return -max(0.0, min(-mw, max_charge) - 1e-6)


def clip_plan(plan_mw, soc0, bess):
    """Make a 48-slot plan feasible sequentially from soc0."""
    out, soc, dis = [], soc0, 0.0
    for mw in plan_mw:
        f = feasible_mw(mw, soc, bess, dis)
        out.append(f)
        soc = soc_after(soc, f, bess)
        dis += max(f, 0.0) * 0.5
    return out


def tolerance_mwh(forecast_mwh, rules):
    """Compliance band around the best available net-load forecast (plan-based balancing)."""
    return max(rules["tolerance_abs_mwh"], rules["tolerance_rel"] * abs(forecast_mwh))


def lots(qty_mwh, rules):
    return math.floor(max(qty_mwh, 0.0) / rules["lot_mwh"]) * rules["lot_mwh"]


# EVOLVE-BLOCK-START
def plan_day_ahead(ctx):
    """Null: buy the D-1 forecast net load at the price cap; no BESS."""
    rules = ctx["rules"]
    net = ctx["forecast"]["net_load_mwh_p50"]
    bids = [{"slot": t + 1, "side": "buy", "qty_mwh": lots(net[t], rules), "limit_jpy_kwh": rules["price_cap"]}
            for t in range(SLOTS) if net[t] > 0]
    return {"bids": bids, "bess_plan_mw": [0.0] * SLOTS}


def adjust_intraday(ctx):
    """Null: no intraday trading, battery idle."""
    return {"orders": [], "bess_mw": 0.0}
# EVOLVE-BLOCK-END
