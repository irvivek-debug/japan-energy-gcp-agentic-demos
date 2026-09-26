"""30-minute market model for the TEPCO PG (Tokyo) area: CALIBRATED SYNTHETIC DATA.

Chain (all arrays are [n_days, 48], slot 0 = 00:00-00:30 JST):
  temperature (Tokyo, climatology + AR anomalies + heat/cold events) and its D-1 / H-1 forecasts
  -> area demand (MARKET_FACTS 7 seasonal hour profiles, weekday/holiday factors, temperature response)
  -> area solar (MARKET_FACTS 7 seasonal profiles x daily clearness)
  -> wide-area reserve margin (available capacity vs demand, outages, LNG-shortage stress)
  -> Tokyo area spot price: seasonal hour shape (MARKET_FACTS 1.4) x monthly level (1.3) x weekday factor x
     net-load anomaly elasticity (1.5 slope) x daily AR level x slot AR noise x scarcity multiplier, with
     spring 0.01 floor events, then monthly levels re-scaled so monthly means hit their targets exactly
  -> system price (Tokyo minus a positive premium in ~90% of slots, 1.2)
  -> intraday Tokyo-delivery quotes at H-1 (bid/ask, KBG liquidity cap)
  -> single-price imbalance (3): base = spot + k x system imbalance (GC forecast error) + noise, 0 JPY/kWh when
     long with high solar, floored by the scarcity curve B=10% -> D at 8% -> C at 3% (C 200 -> 300, D 45 -> 50 from
     2026-10-01; cumulative-price rule after the switch).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
from scipy.signal import lfilter

from . import facts
from .calendar import day_frame, fiscal_year, is_working_day, observance

S = 48
HOURS_SLOT = (np.arange(S) + 0.5) / 2.0            # slot-centre hour (0.25, 0.75, ... 23.75)
# Approximate JMA 1991-2020 Tokyo monthly mean temperatures (deg C); not from MARKET_FACTS. LAB-ASSUMPTION.
TOKYO_NORMALS = [5.4, 6.1, 9.4, 14.3, 18.8, 21.9, 25.7, 26.9, 23.3, 18.0, 12.5, 7.7]
DIURNAL_HALF_AMP = [4.0, 4.0, 4.2, 4.3, 4.2, 3.4, 3.6, 3.8, 3.4, 3.6, 3.9, 4.0]
WARM_SHIFT = 0.8                                    # recent-decade warming vs 1991-2020 normals (LAB-ASSUMPTION)


def h24_to_slots(v24) -> np.ndarray:
    """Periodic linear interpolation of an hour-of-day profile (value at hour centre) to 48 slot centres."""
    v = np.asarray(v24, float)
    x = np.arange(24) + 0.5
    return np.interp(HOURS_SLOT, np.concatenate([x - 24, x, x + 24]), np.concatenate([v, v, v]))


def _monthly_interp(doy: np.ndarray, monthly: list[float]) -> np.ndarray:
    mid = np.array([15, 45, 74, 105, 135, 166, 196, 227, 258, 288, 319, 349], float)
    vals = np.asarray(monthly, float)
    return np.interp(doy, np.concatenate([mid - 365, mid, mid + 365]), np.concatenate([vals, vals, vals]))


# --- month -> blends of the MARKET_FACTS seasonal profiles --------------------------------------------------
DEMAND_BLEND = {1: {"winter": 1.0}, 2: {"winter": 1.0}, 3: {"winter": 0.5, "spring": 0.5}, 4: {"spring": 1.0},
                5: {"spring": 1.0}, 6: {"spring": 0.55, "summer": 0.45}, 7: {"summer": 1.0}, 8: {"summer": 1.0},
                9: {"summer": 0.6, "spring": 0.4}, 10: {"spring": 1.0}, 11: {"spring": 0.7, "winter": 0.3},
                12: {"winter": 1.0}}
DEMAND_MONTH_ADJ = {1: 1.02, 2: 1.0, 3: 0.97, 4: 0.99, 5: 0.98, 6: 1.0, 7: 0.97, 8: 1.02, 9: 0.99, 10: 1.02,
                    11: 1.0, 12: 0.98}
PV_BLEND = {1: ("winter", 0.92), 2: ("winter", 1.08), 3: ("spring", 0.95), 4: ("spring", 1.0), 5: ("spring", 1.06),
            6: ("summer", 0.82), 7: ("summer", 0.95), 8: ("summer", 1.05), 9: ("summer", 0.82), 10: ("spring", 0.78),
            11: ("winter", 0.95), 12: ("winter", 0.85)}
PRICE_SEASON = {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer",
                7: "summer", 8: "summer", 9: "summer", 10: "autumn", 11: "autumn"}
PV_MEAN_CLEARNESS = {1: 0.62, 2: 0.60, 3: 0.52, 4: 0.52, 5: 0.52, 6: 0.42, 7: 0.48, 8: 0.55, 9: 0.45, 10: 0.48,
                     11: 0.55, 12: 0.60}


def _blend(profiles: dict, weights: dict) -> np.ndarray:
    return sum(w * h24_to_slots(profiles[k]) for k, w in weights.items())


DEMAND_SHAPES = {m: _blend(facts.DEMAND_HOURLY_GW_FY2025, DEMAND_BLEND[m]) * DEMAND_MONTH_ADJ[m] for m in range(1, 13)}
PV_SHAPES = {m: h24_to_slots(facts.PV_HOURLY_GW_FY2025[PV_BLEND[m][0]]) * PV_BLEND[m][1] for m in range(1, 13)}
PRICE_SHAPES = {m: h24_to_slots(facts.HOURLY_SHAPE_FY2025[PRICE_SEASON[m]]) for m in range(1, 13)}
DAYTIME = ((HOURS_SLOT >= 8) & (HOURS_SLOT < 20)).astype(float)
EVENING = ((HOURS_SLOT >= 16) & (HOURS_SLOT < 21)).astype(float)
MIDDAY = ((HOURS_SLOT >= 10) & (HOURS_SLOT < 15)).astype(float)


@dataclass
class Event:
    kind: str            # "heat_dome" | "cold_snap_lng" | "tightness"
    start: date
    days: int
    temp_delta: float = 0.0
    cap_loss_gw: float = 0.0          # available-capacity loss (outages / LNG shortage)
    level_mult_peak: float = 1.0      # fuel-scarcity multiplier on the daily price level at the event peak


@dataclass
class Regime:
    """Parameters of one price regime. History uses one regime per FY; scenarios draw one per path."""
    name: str = "baseline"
    nl_elasticity: float = 1.05
    nl_convexity: float = 1.5
    shape_stretch: float = 1.05
    sigma_daily: float = 0.035
    phi_daily: float = 0.85
    sigma_slot: float = 0.08
    phi_slot: float = 0.70
    spike_k: float = 1.65
    spike_pow: float = 1.5
    weekend_factor: float = 1.03     # non-working-day level multiplier (before the NL effect)
    imb_k: float = 6.0                # JPY/kWh per GW of system imbalance at GC
    imb_noise: float = 2.6
    imb_bias: float = -1.10
    id_premium: float = 0.25          # Tokyo-delivery intraday mid minus spot (LAB-ASSUMPTION)
    id_noise: float = 1.35
    id_signal: float = 0.35
    sys_premium_mean: float = 1.40
    floor_slots_per_year: int = 105
    cap_scale: float = 1.0
    rm_lt8_target: int | None = None   # if set, capacity is bisected so RM<8% occurs in this many slots
    rm_tail_target: tuple[float, int] | None = None  # (threshold, max slots): compress the tail below 8% to match
    jump_prob: float = 0.05            # daily upward level jumps (tight days) -> right skew
    jump_size: float = 0.22
    outage_mean: float = 0.035
    events: list[Event] = field(default_factory=list)


# ------------------------------------------------------------------------------------------------------------
def temperature(days: list[date], rng: np.random.Generator, month_anom: dict[tuple[int, int], float],
                events: list[Event]) -> dict[str, np.ndarray]:
    cal = day_frame(days)
    n = len(days)
    doy = cal["doy"].astype(float)
    clim = _monthly_interp(doy, TOKYO_NORMALS) + WARM_SHIFT
    amp = _monthly_interp(doy, DIURNAL_HALF_AMP)
    sig = np.where(np.isin(cal["month"], [6, 7, 8, 9]), 1.6, np.where(np.isin(cal["month"], [12, 1, 2]), 2.0, 1.8))
    anom = _ar(rng, n, 0.75, 1.0) * sig
    shift = np.array([month_anom.get((int(f), int(m)), 0.0) for f, m in zip(cal["fy"], cal["month"])])
    ev = np.zeros(n)
    for e in events:
        if e.temp_delta == 0:
            continue
        for k in range(e.days):
            idx = _day_index(days, e.start, k)
            if idx is not None:
                ramp = min(1.0, (k + 1) / 2.0, (e.days - k) / 2.0)
                ev[idx] += e.temp_delta * ramp
    t_day = clim + anom + shift + ev
    diurnal = np.cos(2 * np.pi * (HOURS_SLOT - 14.5) / 24.0)
    t_slot = t_day[:, None] + amp[:, None] * diurnal[None, :]
    # reference climate the demand profiles embed: FY2025-like warm summers (LAB-ASSUMPTION)
    ref_shift = np.where(np.isin(cal["month"], [7, 8, 9]), 1.5, 0.3)
    t_ref = (clim + ref_shift)[:, None] + amp[:, None] * diurnal[None, :]
    # forecasts: D-1 10:00 (daily error 1.3 C, persistent through the day) and H-1 (0.35 C, AR in slots)
    e_da = rng.normal(0, 1.3, n)[:, None] + rng.normal(0, 0.4, (n, S))
    e_ha = _ar_slots(rng, n, 0.9, 0.35)
    return {"t_day": t_day, "t_slot": t_slot, "t_ref": t_ref, "t_fc_da": t_slot + e_da, "t_fc_ha": t_slot + e_ha,
            "anom_day": anom + shift + ev}


def _day_index(days: list[date], start: date, k: int) -> int | None:
    d0 = days[0]
    i = (start - d0).days + k
    return i if 0 <= i < len(days) else None


def _ar(rng: np.random.Generator, length: int, phi: float, sigma: float) -> np.ndarray:
    """Stationary AR(1) with marginal sd ``sigma`` (vectorised with lfilter)."""
    e = rng.standard_normal(length) * sigma * np.sqrt(1 - phi ** 2)
    e[0] = rng.normal(0, sigma)
    return lfilter([1.0], [1.0, -phi], e)


def _ar_slots(rng: np.random.Generator, n: int, phi: float, sigma: float) -> np.ndarray:
    """AR(1) over the flattened slot sequence (continuous across midnight)."""
    return _ar(rng, n * S, phi, sigma).reshape(n, S)


def _ar_days(rng: np.random.Generator, n: int, phi: float, sigma: float) -> np.ndarray:
    return _ar(rng, n, phi, sigma)


def daytype_factors(days: list[date]) -> tuple[np.ndarray, np.ndarray]:
    """(working flag [n], demand multiplier [n,48]) for weekday / non-working / observance days."""
    working = np.array([is_working_day(d) for d in days])
    obs = np.array([observance(d) or "" for d in days])
    a, b = 0.045 * DAYTIME + 0.03 * (1 - DAYTIME), 0.11 * DAYTIME + 0.085 * (1 - DAYTIME)
    mult = np.where(working[:, None], 1 + a[None, :], 1 - b[None, :])
    deep = np.isin(obs, ["new_year", "obon"])
    mult = np.where(deep[:, None], mult * (1 - 0.07 * DAYTIME[None, :]), mult)
    return working, mult


def temp_sensitivity(month: np.ndarray) -> np.ndarray:
    """Area demand response, GW per deg C of (T - T_ref), [n,48]. Summer cooling +, winter heating -."""
    cool = 2.1 * (0.5 + 0.5 * DAYTIME)
    heat = -1.25 * (0.6 + 0.4 * ((HOURS_SLOT >= 6) & (HOURS_SLOT < 10) | (HOURS_SLOT >= 16) & (HOURS_SLOT < 21)))
    w_cool = np.select([np.isin(month, [7, 8]), np.isin(month, [6, 9])], [1.0, 0.6], 0.0)
    w_heat = np.select([np.isin(month, [12, 1, 2]), np.isin(month, [3, 11])], [1.0, 0.5], 0.0)
    return w_cool[:, None] * cool[None, :] + w_heat[:, None] * heat[None, :]


def area_demand(days: list[date], temp: dict, rng: np.random.Generator, growth: np.ndarray,
                extra_gw: np.ndarray | None = None) -> dict[str, np.ndarray]:
    cal = day_frame(days)
    n = len(days)
    base = np.stack([DEMAND_SHAPES[int(m)] for m in cal["month"]])
    working, mult = daytype_factors(days)
    sens = temp_sensitivity(cal["month"])
    expected = base * mult * growth[:, None]
    model_err = _ar_slots(rng, n, 0.97, 0.010)
    d = expected + sens * (temp["t_slot"] - temp["t_ref"]) + expected * model_err
    if extra_gw is not None:
        d = d + extra_gw
    d_fc_da = expected + sens * (temp["t_fc_da"] - temp["t_ref"]) + expected * _ar_slots(rng, n, 0.97, 0.012)
    d_fc_ha = d - sens * (temp["t_slot"] - temp["t_fc_ha"]) - expected * _ar_slots(rng, n, 0.9, 0.005)
    return {"demand": np.maximum(d, 12.0), "demand_expected": expected, "demand_fc_da": d_fc_da,
            "demand_fc_ha": d_fc_ha, "working": working, "sens": sens}


def area_pv(days: list[date], rng: np.random.Generator, cap_factor: np.ndarray) -> dict[str, np.ndarray]:
    cal = day_frame(days)
    n = len(days)
    months = cal["month"]
    mean_k = np.array([PV_MEAN_CLEARNESS[int(m)] for m in months])
    # daily clearness ~ Beta with the month mean (dispersion kappa=4), normalised so E[pv] = profile
    kappa = 4.0
    k = rng.beta(mean_k * kappa, (1 - mean_k) * kappa)
    shape = np.stack([PV_SHAPES[int(m)] for m in months])
    cloud = np.exp(_ar_slots(rng, n, 0.85, 0.10) - 0.005)
    pv = shape * (k / mean_k)[:, None] * cloud * cap_factor[:, None]
    pv = np.minimum(pv, 17.9 * cap_factor[:, None])
    # forecasts: D-1 clearness error (sd 0.12 in clearness units), H-1 residual (sd 5% of shape)
    k_da = np.clip(k + rng.normal(0, 0.12, n), 0.02, 0.98)
    pv_da = shape * (k_da / mean_k)[:, None] * cap_factor[:, None]
    pv_ha = pv * np.exp(rng.normal(0, 0.05, (n, S)))
    return {"pv": pv, "pv_fc_da": pv_da, "pv_fc_ha": pv_ha, "clearness": k, "pv_expected": shape * cap_factor[:, None]}


def reserve_margin(days: list[date], demand: np.ndarray, pv: np.ndarray, rng: np.random.Generator,
                   regime: Regime) -> tuple[np.ndarray, float]:
    """Wide-area reserve margin proxy (fraction). Available = monthly dispatchable capacity x (1 - outage) + solar.

    If ``regime.rm_lt8_target`` is set, the capacity scale is bisected (no extra random draws) so that RM < 8%
    occurs in that many slots: the scarcity-curve count of imbalance prices >= D (45 JPY/kWh) is the target.
    """
    cal = day_frame(days)
    n = len(days)
    cap_m = {4: 37.0, 5: 37.0, 6: 48.5, 7: 55.0, 8: 56.0, 9: 52.0, 10: 41.0, 11: 43.0, 12: 49.0, 1: 52.0, 2: 51.0, 3: 44.0}
    cap = np.array([cap_m[int(m)] for m in cal["month"]])
    outage = np.clip(regime.outage_mean + _ar_days(rng, n, 0.8, 0.018), 0.0, 0.2)
    trips = (rng.random(n) < 0.04) * rng.uniform(0.5, 2.0, n)            # occasional unit trips (GW)
    loss = np.zeros(n)
    for e in regime.events:
        for k in range(e.days):
            i = _day_index(days, e.start, k)
            if i is not None:
                loss[i] += e.cap_loss_gw * min(1.0, (k + 1) / 2.0, (e.days - k) / 2.0)
    rest = (-trips)[:, None] + 0.85 * pv + _ar_slots(rng, n, 0.9, 0.5)
    firm = (cap * (1 - outage))[:, None]

    def rm_at(c: float) -> np.ndarray:
        return (c * firm + rest) / demand - 1.0

    scale = regime.cap_scale
    if regime.rm_lt8_target is not None:      # calibrate on the no-event system; events are applied afterwards
        lo, hi = 0.7, 1.4
        for _ in range(40):
            mid = 0.5 * (lo + hi)
            if (rm_at(mid) < 0.08).sum() > regime.rm_lt8_target:
                lo = mid
            else:
                hi = mid
        scale = hi
    rm = rm_at(scale)
    if regime.rm_tail_target is not None:
        thr, cnt = regime.rm_tail_target
        k_lo, k_hi = 0.05, 1.0
        for _ in range(40):
            k = 0.5 * (k_lo + k_hi)
            comp = np.where(rm < 0.08, 0.08 - (0.08 - rm) * k, rm)
            if (comp < thr).sum() > cnt:
                k_hi = k
            else:
                k_lo = k
        rm = np.where(rm < 0.08, 0.08 - (0.08 - rm) * k_lo, rm)
    rm = rm - loss[:, None] / demand
    return rm, scale


def scarcity_multiplier(rm: np.ndarray, regime: Regime) -> np.ndarray:
    tau = np.clip((0.12 - rm) / 0.12, 0.0, 1.0)
    return np.exp(regime.spike_k * tau ** regime.spike_pow)


def spot_prices(days: list[date], dem: dict, pv: dict, rm: np.ndarray, rng: np.random.Generator, regime: Regime,
                month_target: dict[tuple[int, int], float], floor_by_month: dict[int, int] | None = None,
                calib_iters: int = 4) -> dict[str, np.ndarray]:
    cal = day_frame(days)
    n = len(days)
    months, fys = cal["month"], cal["fy"]
    shape = np.stack([PRICE_SHAPES[int(m)] for m in months])
    lshape = np.log(shape / shape.mean(axis=1, keepdims=True)) * regime.shape_stretch
    working = dem["working"]
    wk = np.where(working, 1.0, regime.weekend_factor)
    nl = dem["demand"] - pv["pv"]
    nl_exp = dem["demand_expected"] / np.where(working, 1.0, 1.0)[:, None] - pv["pv_expected"]
    # NL anomaly vs the all-days expectation for that month/slot (so weekend NL also lowers price)
    nl_ref = np.zeros_like(nl)
    for m in range(1, 13):
        idx = months == m
        if idx.any():
            nl_ref[idx] = nl_exp[idx].mean(axis=0)
    ratio = np.clip(nl, 3.0, None) / np.clip(nl_ref, 3.0, None)
    ln_nl = regime.nl_elasticity * np.log(ratio) + regime.nl_convexity * np.maximum(ratio - 1.0, 0.0) ** 2
    x_d = _ar_days(rng, n, regime.phi_daily, regime.sigma_daily)
    x_d = x_d + (rng.random(n) < regime.jump_prob) * rng.normal(regime.jump_size, 0.08, n)
    y_t = _ar_slots(rng, n, regime.phi_slot, regime.sigma_slot)
    spike = scarcity_multiplier(rm, regime)
    ev_mult = np.ones(n)
    for e in regime.events:
        if e.level_mult_peak == 1.0:
            continue
        for k in range(e.days):
            i = _day_index(days, e.start, k)
            if i is not None:
                ramp = min(1.0, (k + 1) / 4.0, (e.days - k) / 5.0)
                ev_mult[i] = max(ev_mult[i], 1.0 + (e.level_mult_peak - 1.0) * ramp)
    raw = np.exp(lshape + ln_nl + x_d[:, None] + y_t) * wk[:, None] * spike * ev_mult[:, None]
    # spring solar-surplus floor events (0.01 JPY/kWh): lowest NL/NL_ref midday non-working slots per month
    floor_mask = np.zeros((n, S), bool)
    if floor_by_month:
        for (m, cnt) in floor_by_month.items():
            if cnt <= 0:
                continue
            idx = np.where(months == m)[0]
            if idx.size == 0:
                continue
            cand = ratio[idx] + (1 - MIDDAY)[None, :] * 10 + working[idx][:, None] * 0.35
            flat = np.argsort(cand, axis=None)[:cnt]
            r, c = np.unravel_index(flat, cand.shape)
            floor_mask[idx[r], c] = True
    level = np.ones(n)
    keys = list(zip(fys.tolist(), months.tolist()))
    for key in set(keys):
        sel = np.array([k == key for k in keys])
        level[sel] = month_target.get(key, 12.0)
    price = raw * level[:, None]
    calm = ev_mult < 1.01          # stress-event days add on top of the target level (excluded from calibration)
    for _ in range(calib_iters):  # re-scale each month so the realised (non-event) monthly mean equals its target
        for key in set(keys):
            sel = np.array([k == key for k in keys])
            tgt = month_target.get(key)
            if tgt is None:
                continue
            cal_sel = sel & calm
            if cal_sel.sum() == 0:
                continue
            non_floor = ~floor_mask[cal_sel]
            adj = (tgt * cal_sel.sum() * S - facts.PRICE_FLOOR * floor_mask[cal_sel].sum()) / max(price[cal_sel][non_floor].sum(), 1e-9)
            price[sel] *= adj
    price = np.where(floor_mask, facts.PRICE_FLOOR, price)
    # stress prices saturate near the historical record (Tokyo 252.00 JPY/kWh, 2021-01-15; MARKET_FACTS 1.6)
    price = np.where(price > 200.0, 200.0 + 60.0 * np.tanh((price - 200.0) / 60.0), price)
    price = np.clip(np.round(price, 2), facts.PRICE_FLOOR, facts.PRICE_CAP_SIM)
    return {"tokyo": price, "nl": nl, "nl_ref": nl_ref, "floor": floor_mask, "spike": spike, "level": level,
            "event_mult": ev_mult}


def system_prices(tokyo: np.ndarray, rng: np.random.Generator, premium_mean: float) -> np.ndarray:
    n = tokyo.shape[0]
    differs = rng.random((n, S)) < facts.TOKYO_PREMIUM_SLOT_SHARE
    prem = rng.gamma(2.0, premium_mean / facts.TOKYO_PREMIUM_SLOT_SHARE / 2.0, (n, S)) * differs
    prem = prem * np.clip(tokyo / 12.0, 0.3, 3.0)
    return np.clip(np.round(tokyo - prem, 2), facts.PRICE_FLOOR, None)


def scarcity_curve(rm: np.ndarray, c_val: np.ndarray | float, d_val: np.ndarray | float) -> np.ndarray:
    """Regulatory scarcity-adjusted imbalance price vs wide-area reserve margin (MARKET_FACTS 3).

    0 at RM >= 10%, linear to D at 8%, linear to C at 3%, flat C below 3% (interpolation is an ESTIMATE).
    """
    b, bp, a = facts.SCARCITY_B, facts.SCARCITY_B_PRIME, facts.SCARCITY_A
    rm = np.asarray(rm, float)
    seg1 = np.clip((b - rm) / (b - bp), 0, 1) * d_val
    seg2 = d_val + np.clip((bp - rm) / (bp - a), 0, 1) * (np.asarray(c_val) - d_val)
    return np.where(rm >= b, 0.0, np.where(rm >= bp, seg1, seg2))


def imbalance_prices(days: list[date], tokyo: np.ndarray, rm: np.ndarray, dem: dict, pv: dict,
                     rng: np.random.Generator, regime: Regime) -> dict[str, np.ndarray]:
    n = len(days)
    delta = (dem["demand"] - dem["demand_fc_ha"]) - (pv["pv"] - pv["pv_fc_ha"])   # GW, + = system short
    base = tokyo + regime.imb_k * delta + regime.imb_bias + rng.standard_t(4, (n, S)) * regime.imb_noise / np.sqrt(2)
    base = base * np.clip(tokyo / 12.0, 0.5, 4.0) ** 0.3
    # zero price when the system is long with high solar (VRE-curtailment-type conditions)
    solar_share = pv["pv"] / dem["demand"]
    zero = (delta < -0.15) & (solar_share > 0.28) & (rng.random((n, S)) < 0.85)
    base = np.where(zero, 0.0, np.maximum(base, 0.0))
    switch = np.array([d >= date(2026, 10, 1) for d in days])
    c_val = np.where(switch, facts.SCARCITY_C["from_2026_10_01"], facts.SCARCITY_C["to_2026_09_30"])[:, None]
    d_val = np.where(switch, facts.SCARCITY_D["from_2026_10_01"], facts.SCARCITY_D["to_2026_09_30"])[:, None]
    rm_gc = rm + rng.normal(0, 0.004, (n, S))
    # cumulative-price rule (only with the 300 cap): >=30 slots of spot >=200 in prior 7 days -> cap 100
    cap_eff = np.broadcast_to(c_val, (n, S)).copy()
    for i in range(n):
        if not switch[i]:
            continue
        lo = max(0, i - 7)
        if (tokyo[lo:i] >= facts.CUMULATIVE_RULE["trigger_price"]).sum() >= facts.CUMULATIVE_RULE["trigger_slots"]:
            cap_eff[i] = facts.CUMULATIVE_RULE["reduced_cap"]
    scar = scarcity_curve(rm_gc, cap_eff, d_val)
    base = np.minimum(base, np.maximum(cap_eff, tokyo))          # base price bounded by max(C, spot)
    imb = np.round(np.maximum(base, scar), 2)
    return {"imbalance": imb, "delta_gw": delta, "scarcity": scar, "rm_gc": rm_gc, "c_val": cap_eff}


def intraday_quotes(tokyo: np.ndarray, delta: np.ndarray, rng: np.random.Generator, regime: Regime) -> dict:
    n = tokyo.shape[0]
    mid = tokyo + regime.id_premium + regime.id_signal * regime.imb_k * delta * 0.5 + \
        rng.normal(0, regime.id_noise, (n, S)) * np.clip(tokyo / 12.0, 0.5, 3.0) ** 0.5
    mid = np.maximum(mid, facts.PRICE_FLOOR)
    half = 0.25 + 0.03 * mid
    liq = np.clip(rng.normal(30.0, 6.0, (n, S)), 10.0, 45.0)      # KBG-accessible MWh per slot (LAB-ASSUMPTION)
    return {"id_mid": np.round(mid, 2), "id_bid": np.round(np.maximum(mid - half, 0.01), 2),
            "id_ask": np.round(mid + half, 2), "id_liq_mwh": np.round(liq, 1)}


def simulate(days: list[date], rng: np.random.Generator, regime: Regime, month_target: dict,
             month_temp_anom: dict | None = None, growth_by_fy: dict | None = None,
             pv_cap_by_fy: dict | None = None, floor_by_month: dict | None = None) -> dict[str, np.ndarray]:
    """Full market path for a list of consecutive days."""
    cal = day_frame(days)
    growth = np.array([(growth_by_fy or {}).get(int(f), 1.0) for f in cal["fy"]])
    pvcap = np.array([(pv_cap_by_fy or {}).get(int(f), 1.0) for f in cal["fy"]])
    temp = temperature(days, rng, month_temp_anom or {}, regime.events)
    dem = area_demand(days, temp, rng, growth)
    sol = area_pv(days, rng, pvcap)
    rm, cap_scale = reserve_margin(days, dem["demand"], sol["pv"], rng, regime)
    sp = spot_prices(days, dem, sol, rm, rng, regime, month_target, floor_by_month)
    sysp = system_prices(sp["tokyo"], rng, regime.sys_premium_mean)
    imb = imbalance_prices(days, sp["tokyo"], rm, dem, sol, rng, regime)
    idq = intraday_quotes(sp["tokyo"], imb["delta_gw"], rng, regime)
    out = {**{k: v for k, v in cal.items()}, **temp, **dem, **sol, "rm": rm, **sp, "system": sysp, **imb, **idq}
    out["cap_scale"] = np.full(len(days), cap_scale)
    return out
