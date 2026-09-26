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
    """Seed: price-taker for forecast net load + cheapest-4 / dearest-4 BESS arbitrage with an RTE threshold."""
    bess, rules = ctx["bess"], ctx["rules"]
    price = ctx["forecast"]["price_jpy_kwh"]["p50"]
    order = sorted(range(SLOTS), key=lambda t: price[t])
    cheap, dear = order[:4], order[-4:]
    plan = [0.0] * SLOTS
    buy_avg = sum(price[t] for t in cheap) / 4.0
    sell_avg = sum(price[t] for t in dear) / 4.0
    if sell_avg * bess["rte"] - buy_avg > bess["degradation_jpy_per_mwh"] / 1000.0 + 1.0:
        for t in cheap:
            plan[t] = -bess["power_mw"]
        for t in dear:
            plan[t] = bess["power_mw"]
    plan = clip_plan(plan, bess["soc_mwh"], bess)
    net = ctx["forecast"]["net_load_mwh_p50"]
    bids = []
    for t in range(SLOTS):
        qty = net[t] - plan[t] * 0.5
        if qty > 0:
            bids.append({"slot": t + 1, "side": "buy", "qty_mwh": lots(qty, rules), "limit_jpy_kwh": rules["price_cap"]})
    return {"bids": bids, "bess_plan_mw": plan}


def adjust_intraday(ctx):
    """Seed: follow the BESS plan; correct 50% of the forecast gap, never leaving more than 80% of the tolerance."""
    bess, rules, idm = ctx["bess"], ctx["rules"], ctx["intraday"]
    mw = feasible_mw(bess["planned_mw"], bess["soc_mwh"], bess, bess["discharged_today_mwh"])
    forecast = ctx["forecast_ha"]["net_load_mwh"]
    position = ctx["position_mwh"]["da_net"] + mw * 0.5
    gap = forecast - position
    tol = tolerance_mwh(forecast, rules)
    qty = 0.5 * gap
    if abs(gap - qty) > 0.8 * tol:
        qty = gap - math.copysign(0.8 * tol, gap)
    orders = []
    if qty >= rules["lot_mwh"]:
        orders.append({"side": "buy", "qty_mwh": lots(qty, rules), "limit_jpy_kwh": min(rules["price_cap"], idm["best_ask"] + 2.0)})
    elif qty <= -rules["lot_mwh"]:
        orders.append({"side": "sell", "qty_mwh": lots(-qty, rules), "limit_jpy_kwh": max(rules["price_floor"], idm["best_bid"] - 2.0)})
    return {"orders": orders, "bess_mw": mw}
# EVOLVE-BLOCK-END
