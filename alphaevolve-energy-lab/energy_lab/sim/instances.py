"""Builds the frozen evaluator instances (tariff_pricing_{train,holdout}, jepx_trading_{train,holdout}).

Deterministic given the seeds below. Instances are written with fixed zip metadata and hashed by content
(sim/npz.py) so regenerating the gitignored cache reproduces the manifest hashes and the baseline locks.
"""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
from scipy.signal import lfilter

from . import facts
from .assets import BESS, BESS_SITES, PV_PPA
from .calendar import fy_days, is_holiday, observance, season_of_month
from .history import GROWTH, PV_CAP
from .market import Event, Regime, S, simulate
from .portfolio import SEG, SEGMENTS, customer_shape, daytype_of, draw_customers, segment_shape
from .scenarios import FY26_FLOORS, generate_bank

SEEDS = {"history": 20260926, "train_cohort": 11, "holdout_cohort": 29, "train_bank": 101, "holdout_bank": 202,
         "kbg_noise": 303, "stress_path": 404, "holdout2_cohort": 31, "holdout2_bank": 505,
         "holdout3_cohort": 37, "holdout3_bank": 606}
N_SCEN = {"train": 64, "holdout": 64}
DT_NAMES = [f"{m:02d}-{t}" for m in range(1, 13) for t in ("working", "nonworking", "shutdown")] + ["heat-working", "cold-working"]
H_OPTIONS = (1, 2, 3, 4, 6)
DR_CALL_SLOTS, DR_MAX_DAYS = 6, 12


# --- helpers -----------------------------------------------------------------------------------------------
def _dt_idx(month: int, dt: int) -> int:
    return (month - 1) * 3 + dt


def archetype_table() -> np.ndarray:
    arch = np.zeros((len(SEGMENTS), 38, S))
    for k, name in enumerate(SEGMENTS):
        seg = SEG[name]
        for m in range(1, 13):
            for t, label in enumerate(("working", "nonworking", "shutdown")):
                arch[k, _dt_idx(m, t)] = segment_shape(seg, m, label)
        arch[k, 36] = segment_shape(seg, 8, "working")
        arch[k, 37] = segment_shape(seg, 1, "working")
    return arch


def classify_days(bank: dict) -> np.ndarray:
    """[S, n_days] day-type index per scenario."""
    Sn, nd = bank["month"].shape
    out = np.zeros((Sn, nd), int)
    for s in range(Sn):
        for i in range(nd):
            m = int(bank["month"][s, i])
            obs = str(bank["observance"][s, i])
            working = bool(bank["working"][s, i])
            ev = float(bank["event_mult"][s, i]) > 1.01
            an = float(bank["anom_day"][s, i])
            if working and m in (6, 7, 8, 9) and (ev or an > 2.5):
                out[s, i] = 36
            elif working and m in (12, 1, 2) and (ev or an < -3.5):
                out[s, i] = 37
            else:
                dt = {"working": 0, "nonworking": 1, "shutdown": 2}[daytype_of(working, obs)]
                out[s, i] = _dt_idx(m, dt)
    return out


def bank_stats(bank: dict) -> dict[str, np.ndarray]:
    """Reduce full 365x48 paths to representative-day tensors + nonlinear statistics."""
    P = bank["tokyo"]
    imb = bank["imbalance"]
    Sn, nd, _ = P.shape
    types = classify_days(bank)
    s_P = np.zeros((Sn, 38, S))
    s_W = np.zeros((Sn, 38))
    s_TA = np.zeros((Sn, 38))
    s_SP = np.zeros((Sn, 38, len(H_OPTIONS)))
    srt = np.sort(P, axis=2)
    spreads = np.stack([srt[:, :, -2 * h:].mean(axis=2) - srt[:, :, :2 * h].mean(axis=2) for h in H_OPTIONS], axis=2)
    for s in range(Sn):
        for d in range(38):
            sel = types[s] == d
            if sel.any():
                s_P[s, d] = P[s, sel].mean(axis=0)
                s_W[s, d] = sel.sum()
                s_TA[s, d] = bank["anom_day"][s, sel].mean()
                s_SP[s, d] = spreads[s, sel].mean(axis=0)
            else:  # unused type: month mean profile, zero weight
                m = 8 if d == 36 else 1 if d == 37 else d // 3 + 1
                msel = bank["month"][s] == m
                s_P[s, d] = P[s, msel].mean(axis=0)
                s_SP[s, d] = spreads[s, msel].mean(axis=0)
    # DR value: up to 12 call days (highest daily max imbalance price with max >= 30), best 3 h window each
    s_DRV = np.zeros((Sn, S))
    kappa = np.zeros(Sn)
    for s in range(Sn):
        dmax = imb[s].max(axis=1)
        cand = np.where(dmax >= 30.0)[0]
        days = cand[np.argsort(-dmax[cand])][:DR_MAX_DAYS]
        for i in days:
            win = np.convolve(imb[s, i], np.ones(DR_CALL_SLOTS), "valid")
            j = int(win.argmax())
            s_DRV[s, j:j + DR_CALL_SLOTS] += imb[s, i, j:j + DR_CALL_SLOTS] * 0.5      # JPY per kW (0.5 kWh/slot)
        z = bank["delta_gw"][s] / max(bank["delta_gw"][s].std(), 1e-9)
        kappa[s] = float((z * (imb[s] - P[s])).mean())
    annual = P.mean(axis=(1, 2))
    return {"s_P": s_P.astype(np.float32), "s_W": s_W.astype(np.float32), "s_TA": s_TA.astype(np.float32),
            "s_SP": s_SP.astype(np.float32), "s_DRV": s_DRV.astype(np.float32), "s_KAPPA": kappa.astype(np.float32),
            "s_annual": annual.astype(np.float32)}


CUST_NUM = ["contract_kw", "shape_amp", "shape_shift", "level_mult", "flex_hours"]
HIDDEN = ["h_risk_aversion", "h_elasticity", "h_inertia", "h_term_pref", "h_dr_cost", "h_dr_share", "h_flex_response",
          "h_flex_share", "h_sigma_slot", "h_sigma_month", "h_discipline", "h_weather_corr", "h_pd", "h_clv_jpy_m",
          "h_comp_margin", "h_comp_noise", "h_quote_noise"]


def customer_arrays(cs: list[dict], arch: np.ndarray) -> dict[str, np.ndarray]:
    seg_idx = np.array([SEGMENTS.index(c["segment"]) for c in cs])
    amp = np.array([c["shape_amp"] for c in cs])
    shift = np.array([c["shape_shift"] for c in cs])
    level = np.array([c["level_mult"] for c in cs])
    from ..problems.tariff_pricing.model import reconstruct_shapes, weather_coefs

    SH = reconstruct_shapes(arch, seg_idx, amp, shift, level)
    wc = weather_coefs(seg_idx)
    hot = SH * (1 + wc[:, :, 0:1] * 3.0 + wc[:, :, 1:2] * 4.5)          # design-day peak (hot summer / cold winter)
    peak = hot.max(axis=(1, 2))
    contract = np.array([c["contract_kw"] for c in cs])
    out = {"c_seg": seg_idx.astype(np.int16), "c_volt": np.array([1 if c["voltage"] == "EHV" else 0 for c in cs], np.int8),
           "c_contract_kw": contract, "c_base_kw": contract / (1.05 * peak), "c_amp": amp, "c_shift": shift.astype(np.int8),
           "c_level": level, "c_flex_hours": np.array([c["flex_hours"] for c in cs]),
           "c_green": np.array([c["green_required"] for c in cs]), "c_essential": np.array([c["essential"] for c in cs]),
           "c_id": np.array([c["customer_id"] for c in cs])}
    for h in HIDDEN:
        out[h] = np.array([float(c[h]) for c in cs])
    return out


def forward_from_train(st: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray, float]:
    W = st["s_W"].astype(float)
    P = st["s_P"].astype(float)
    fwd_W = W.mean(axis=0)
    wsum = W.sum(axis=0)
    fwd_P = np.where(wsum[:, None] > 0, (W[:, :, None] * P).sum(axis=0) / np.maximum(wsum[:, None], 1e-9), P.mean(axis=0))
    f_SP = np.where(wsum[:, None] > 0, (W[:, :, None] * st["s_SP"]).sum(axis=0) / np.maximum(wsum[:, None], 1e-9),
                    st["s_SP"].mean(axis=0))
    sigma_f = float(np.std(st["s_annual"]))
    return fwd_P, fwd_W, f_SP, sigma_f


def lf_band(lf: np.ndarray) -> np.ndarray:
    return np.where(lf < 0.40, 0, np.where(lf < 0.65, 1, 2))


LF_BAND_NAMES = ["low", "mid", "high"]
VOLT_NAMES = ["HV", "EHV"]


def build_tariff(train_bank: dict, holdout_bank: dict, holdout2_bank: dict | None = None,
                 holdout3_bank: dict | None = None) -> dict[str, dict]:
    """Folds: train, holdout (burned for tariff after runs 1-2 informed evaluator v3) and holdout2 (fresh cohort + bank)."""
    from ..problems.tariff_pricing import model as tm

    arch = archetype_table()
    st_tr, st_ho = bank_stats(train_bank), bank_stats(holdout_bank)
    stats = {"train": st_tr, "holdout": st_ho}
    banks = {"train": train_bank, "holdout": holdout_bank}
    fwd_P, fwd_W, f_SP, sigma_f = forward_from_train(st_tr)
    cohorts = {"train": draw_customers("train", 1200, SEEDS["train_cohort"]),
               "holdout": draw_customers("holdout", 400, SEEDS["holdout_cohort"])}
    if holdout2_bank is not None:
        cohorts["holdout2"] = draw_customers("holdout2", 400, SEEDS["holdout2_cohort"])
        stats["holdout2"] = bank_stats(holdout2_bank)
        banks["holdout2"] = holdout2_bank
    if holdout3_bank is not None:   # pre-registered (docs/PREREGISTRATION_tariff_v4.md): as large as the train cohort
        cohorts["holdout3"] = draw_customers("holdout3", 1200, SEEDS["holdout3_cohort"])
        stats["holdout3"] = bank_stats(holdout3_bank)
        banks["holdout3"] = holdout3_bank
    raw = {}
    for fold, cs in cohorts.items():
        ca = customer_arrays(cs, arch)
        st = stats[fold]
        arr = {**ca, "arch": arch.astype(np.float64), **st, "f_SP": f_SP.astype(np.float32),
               "c_lfband": np.zeros(len(cs), np.int8)}
        pre = tm.prepare(arr, fwd_P, fwd_W, sigma_f)
        lfv = pre.E_fwd / (arr["c_contract_kw"] * 8760.0)
        arr["c_lfband"] = lf_band(lfv).astype(np.int8)
        raw[fold] = (cs, arr, pre, lfv)
    # segment reference (fair-pricing ceiling) from the TRAIN cohort's competitor offers; reused for holdout
    cs, arr, pre, _ = raw["train"]
    seg_ref = {}
    for k, name in enumerate(SEGMENTS):
        seg_ref[name] = {}
        for v, vn in enumerate(VOLT_NAMES):
            sel = (pre.seg_idx == k) & (pre.volt == v)
            if not sel.any():
                sel = pre.seg_idx == k
            seg_ref[name][vn] = round(float(np.average(pre.comp[sel], weights=pre.E_fwd[sel])), 4)
    months_fy = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    fwd_month = []
    for m in months_fy:
        idx = [tm.dt_index(m, t) for t in range(3)] + ([36] if m == 8 else []) + ([37] if m == 1 else [])
        w = fwd_W[idx]
        fwd_month.append(round(float((fwd_P[idx].mean(axis=1) * w).sum() / max(w.sum(), 1e-9)), 3))
    base_w = fwd_W / fwd_W.sum()
    work_idx = [tm.dt_index(m, 0) for m in range(1, 13)]
    day_mask = np.zeros(S, bool)
    day_mask[16:44] = True
    market = {
        "fiscal_year": 2026, "pricing_date": "2026-03-16", "currency": "JPY",
        "note": ("Forward view at pricing time = probability-weighted mean of the desk's FY2026 scenario bank "
                 "(train bank). Calibrated synthetic data."),
        "forward_monthly_jpy_kwh": fwd_month, "forward_months": months_fy,
        "forward_baseload_jpy_kwh": round(float((fwd_P.mean(axis=1) * base_w).sum()), 3),
        "forward_weekday_daytime_jpy_kwh": round(float(fwd_P[work_idx][:, day_mask].mean()), 3),
        "forward_night_jpy_kwh": round(float(fwd_P[:, ~day_mask].mean()), 3),
        "forward_vol_annual_jpy_kwh": round(sigma_f, 3),
        "scenario_regime_mix": {"baseline": 0.55, "moderate_shock": 0.30, "severe_shock": 0.15},
        "loss_factor": {"HV": tm.LOSS_FACTOR[0], "EHV": tm.LOSS_FACTOR[1]},
        "cost_stack": {
            "wheeling_basic_jpy_kw_month": {"HV": {"Apr-Oct": tm.WHEEL_BASIC[0][0], "Nov-Mar": tm.WHEEL_BASIC[0][1]},
                                            "EHV": {"Apr-Oct": tm.WHEEL_BASIC[1][0], "Nov-Mar": tm.WHEEL_BASIC[1][1]}},
            "wheeling_energy_jpy_kwh": {"HV": tm.WHEEL_ENERGY[0], "EHV": tm.WHEEL_ENERGY[1]},
            "capacity_jpy_per_kw_year_of_coincident_peak": round(tm.CAPACITY_JPY_KW_YR, 1),
            "balancing_overhead_jpy_kwh": tm.BALANCING_OVERHEAD, "nfc_renewable_jpy_kwh": tm.NFC,
            "renewable_surcharge_jpy_kwh": facts.RENEWABLE_SURCHARGE[2026],
            "renewable_surcharge_treatment": "pass-through, excluded from margin and from offers",
        },
        "segment_reference_jpy_kwh": seg_ref,
        "policy": tm.POLICY,
        "tepco_ep_reference_plans_hv_fy2026": facts.TEPCO_EP_HV_PLANS_FY2026,
        "imbalance_scarcity_curve": {"B_pct": 10, "B_prime_pct": 8, "A_pct": 3, "D_until_2026_09": 45, "C_until_2026_09": 200,
                                     "D_from_2026_10": 50, "C_from_2026_10": 300},
        "dr_value_estimate_jpy_per_kw_year": round(float(st_tr["s_DRV"].sum(axis=1).mean()), 1),
        "flex_spread_estimate_jpy_kwh": {str(h): round(float((f_SP[:, k] * base_w).sum()), 3) for k, h in enumerate(H_OPTIONS)},
        "imbalance_cost_estimate_jpy_kwh_per_unit_deviation": round(float(st_tr["s_KAPPA"].mean()), 4),
        "offer_fields": {"energy_rate_jpy_kwh": "fixed energy rate on the (1-alpha) share",
                         "alpha": "market-link share in [0,1] billed at JEPX Tokyo x loss factor + market_adder",
                         "market_adder_jpy_kwh": "adder on the market-linked share",
                         "demand_charge_jpy_kw_month": "on contract kW",
                         "deviation_band_pct": "5..10 (% of planned monthly energy)",
                         "deviation_penalty_jpy_kwh": "on monthly deviation beyond the band",
                         "dr_discount_jpy_kw_month": "on committed DR kW if the customer enrols",
                         "term_years": "1, 2 or 3"},
    }
    out = {}
    for fold, (cs, arr, pre, lfv) in raw.items():
        feats = []
        for i, c in enumerate(cs):
            wheel_kwh = (pre.wheel_basic_yr[i] / pre.E_fwd[i]) + pre.wheel_energy[i]
            feats.append({
                "segment": c["segment"], "voltage": c["voltage"], "contract_kw": c["contract_kw"],
                "annual_mwh": round(float(pre.E_fwd[i] / 1000), 1), "load_factor": round(float(lfv[i]), 4),
                "lf_band": LF_BAND_NAMES[int(arr["c_lfband"][i])],
                "expected_energy_cost_jpy_kwh": round(float(pre.F[i]), 4),
                "shape_premium": round(float(pre.F[i] / market["forward_baseload_jpy_kwh"]), 4),
                "wheeling_jpy_kwh_equiv": round(float(wheel_kwh), 4),
                "capacity_cost_jpy_kwh": round(float(pre.cap_cost[i] / pre.E_fwd[i]), 4),
                "coincident_peak_kw": round(float(pre.cap_cost[i] / tm.CAPACITY_JPY_KW_YR), 1),
                "flex_share": c["flex_share"], "flex_hours": c["flex_hours"],
                "forecast_mape_pct": c["forecast_mape_pct"], "monthly_deviation_pct": c["monthly_deviation_pct"],
                "credit_rating": c["credit_rating"], "essential": c["essential"], "green_required": c["green_required"],
                "tenure_years": c["tenure_years"], "switched_last_5y": c["switched_last_5y"],
                "procurement_style": c["procurement_style"], "risk_appetite": c["risk_appetite"],
                "dr_interest": c["dr_interest"], "dr_potential_kw": round(float(c["h_dr_share"] * c["contract_kw"]), 1),
                "preferred_term_hint": c["preferred_term_hint"],
                "competitor_quote_est_jpy_kwh": round(float(pre.comp[i] * c["h_quote_noise"]), 3),
                "current_rate_jpy_kwh": round(float(pre.comp[i] - pre.F[i] * pre.lf[i] * (1 - facts.TOKYO_ANNUAL_MEAN[2025] / market["forward_baseload_jpy_kwh"])), 3),
            })
        arr = {k: v for k, v in arr.items()}
        arr["features_json"] = np.array(json.dumps(feats, separators=(",", ":")))
        arr["market_json"] = np.array(json.dumps(market, separators=(",", ":")))
        arr["fwd_P"] = fwd_P.astype(np.float32)
        arr["fwd_W"] = fwd_W.astype(np.float32)
        arr["sigma_f"] = np.array(sigma_f)
        meta = banks[fold]["meta"]
        arr["scen_json"] = np.array(json.dumps(meta, separators=(",", ":")))
        out[f"tariff_pricing_{fold}"] = {"arrays": arr, "customers": cs, "prepared": pre}
    return out


# --- KBG trading instances ------------------------------------------------------------------------------------
def kbg_segment_tables(cs: list[dict], arch: np.ndarray) -> np.ndarray:
    """[n_seg, 38, 48] sum of customer base kW x shape per segment (kW)."""
    ca = customer_arrays(cs, arch)
    from ..problems.tariff_pricing.model import reconstruct_shapes

    SH = reconstruct_shapes(arch, ca["c_seg"].astype(int), ca["c_amp"], ca["c_shift"].astype(int), ca["c_level"])
    agg = np.zeros((len(SEGMENTS), 38, S))
    for k in range(len(SEGMENTS)):
        sel = ca["c_seg"] == k
        agg[k] = (ca["c_base_kw"][sel, None, None] * SH[sel]).sum(axis=0)
    return agg


def kbg_demand(path: dict, agg: np.ndarray, rng: np.random.Generator, growth: float = 1.0) -> dict[str, np.ndarray]:
    n = len(path["date"])
    months = path["month"]
    idx = np.array([_dt_idx(int(m), {"working": 0, "nonworking": 1, "shutdown": 2}[daytype_of(bool(w), str(o))])
                    for m, w, o in zip(months, path["working"], path["observance"])])
    cool = np.array([SEG[s].cool for s in SEGMENTS])
    heat = np.array([SEG[s].heat for s in SEGMENTS])
    fc = np.select([np.isin(months, [7, 8]), np.isin(months, [6, 9])], [1.0, 0.6], 0.0)
    fh = np.select([np.isin(months, [12, 1, 2]), np.isin(months, [3, 11])], [1.0, 0.5], 0.0)

    def load_for(anom: np.ndarray) -> np.ndarray:
        a = np.clip(anom, -8, 8)
        tot = np.zeros((n, S))
        for k in range(len(SEGMENTS)):
            wm = 1 + cool[k] * fc[:, None] * np.maximum(a, -3) + heat[k] * fh[:, None] * np.maximum(-a, -3)
            tot += agg[k][idx] * wm
        return tot / 1000.0 * growth                          # MW

    base_actual = load_for(path["t_slot"] - path["t_ref"])
    base_da = load_for(path["t_fc_da"] - path["t_ref"])
    base_ha = load_for(path["t_fc_ha"] - path["t_ref"])

    def ar(phi, sig):
        e = rng.standard_normal(n * S) * sig * np.sqrt(1 - phi ** 2)
        return lfilter([1.0], [1.0, -phi], e).reshape(n, S)

    idio = ar(0.97, 0.012) + np.repeat(rng.normal(0, 0.008, n), S).reshape(n, S)
    actual = base_actual * (1 + idio)
    da = base_da * (1 + ar(0.97, 0.014))
    da = da * (actual.mean() / da.mean())        # the desk's model is calibrated on history (no systematic bias)
    ha = base_ha * (1 + idio - ar(0.9, 0.006))
    sd_da = np.full((n, S), 0.032) * da
    sd_ha = np.full((n, S), 0.010) * ha
    return {"demand": actual, "da_p50": da, "da_sd": sd_da, "ha_p50": ha, "ha_sd": sd_ha}


def kbg_pv(path: dict, rng: np.random.Generator, cap_factor: float) -> dict[str, np.ndarray]:
    n = len(path["date"])
    scale = PV_PPA["capacity_mw"] / (17.9 * cap_factor)
    local = np.exp(rng.normal(0, 0.05, (n, S)))
    pv = np.clip(path["pv"] * scale * local, 0, PV_PPA["capacity_mw"])
    da = np.clip(path["pv_fc_da"] * scale, 0, PV_PPA["capacity_mw"])
    ha = np.clip(path["pv_fc_ha"] * scale * local * np.exp(rng.normal(0, 0.03, (n, S))), 0, PV_PPA["capacity_mw"])
    shape = np.clip(path["pv_expected"] * scale, 0, None)
    return {"pv": pv, "da_p50": da, "da_sd": 0.25 * shape + 0.5, "ha_p50": ha, "ha_sd": 0.06 * shape + 0.2}


def price_forecasts(path: dict, rng: np.random.Generator) -> dict[str, np.ndarray]:
    n = len(path["date"])
    spot = path["tokyo"]
    e_d = rng.normal(0, 0.07, n)[:, None]
    e_t = lfilter([1.0], [1.0, -0.8], rng.standard_normal(n * S) * 0.06 * 0.6).reshape(n, S)
    spike_log = np.log(np.maximum(path["spike"], 1.0)) + np.log(np.maximum(path["event_mult"], 1.0))[:, None]
    p50 = np.maximum(spot * np.exp(e_d + e_t - 0.6 * spike_log), 0.01)
    rm_fc = path["rm"] + rng.normal(0, 0.012, n)[:, None] + rng.normal(0, 0.006, (n, S))
    tight = np.clip((0.12 - rm_fc) / 0.12, 0, 1)
    p10 = p50 * np.exp(-1.2816 * 0.12)
    p90 = p50 * np.exp(1.2816 * 0.12) * (1 + 1.5 * tight)
    return {"p10": p10, "p50": p50, "p90": p90, "rm_fc": rm_fc}


TRAIN_BLOCKS = [date(2024, 4, 8), date(2024, 5, 13), date(2025, 3, 10), date(2024, 6, 17), date(2024, 7, 22),
                date(2024, 8, 19), date(2024, 9, 16), date(2024, 10, 14), date(2024, 11, 11), date(2024, 12, 9),
                date(2025, 1, 20), date(2025, 2, 3)]
HOLDOUT_BLOCKS = [date(2025, 4, 14), date(2025, 5, 19), date(2026, 3, 9), date(2025, 6, 23), date(2025, 7, 30),
                  date(2025, 8, 18), date(2025, 9, 15), date(2025, 10, 20), date(2025, 11, 17), date(2025, 12, 15),
                  date(2026, 1, 26), date(2026, 2, 5)]
BLOCK_DAYS = 8


def stress_path(agg: np.ndarray) -> tuple[dict, list[date], list[date]]:
    """One FY2026 severe path with a cold-snap/LNG event and a heat dome, for the trading holdout stress blocks."""
    rng = np.random.default_rng(SEEDS["stress_path"])
    days = fy_days(2026)
    base = np.array(facts.TOKYO_MONTHLY_FY2025) * 1.7
    targets = {(2026, m): float(v) for m, v in zip([4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3], base)}
    heat_start, cold_start = date(2026, 7, 27), date(2027, 1, 12)
    reg = Regime(name="stress", shape_stretch=1.38, nl_elasticity=1.35, rm_lt8_target=60, rm_tail_target=(0.062, 18),
                 imb_noise=5.5, imb_k=9.0, id_noise=3.2, sys_premium_mean=3.75,
                 events=[Event("heat_dome", heat_start, 10, temp_delta=3.2, cap_loss_gw=1.5, level_mult_peak=80.0 / targets[(2026, 8)]),
                         Event("cold_snap_lng", cold_start, 18, temp_delta=-4.5, cap_loss_gw=2.5, level_mult_peak=150.0 / targets[(2026, 1)])])
    path = simulate(days, rng, reg, targets, {}, GROWTH, PV_CAP, FY26_FLOORS)
    return path, [heat_start + timedelta(days=1)], [cold_start + timedelta(days=3)]


def build_trading(history: dict, train_cohort: list[dict]) -> dict[str, dict]:
    arch = archetype_table()
    agg = kbg_segment_tables(train_cohort, arch)
    rng = np.random.default_rng(SEEDS["kbg_noise"])
    hist_dates = [date.fromisoformat(d) for d in history["date"]]
    hist = {"kbg": kbg_demand(history, agg, rng), "pv": kbg_pv(history, rng, 1.0), "pf": price_forecasts(history, rng)}
    spath, heat_starts, cold_starts = stress_path(agg)
    s_rng = np.random.default_rng(SEEDS["kbg_noise"] + 1)
    shist = {"kbg": kbg_demand(spath, agg, s_rng, growth=1.02), "pv": kbg_pv(spath, s_rng, 1.05),
             "pf": price_forecasts(spath, s_rng)}
    sdates = [date.fromisoformat(d) for d in spath["date"]]

    def gather(src_path, src, dates_all, block_starts, tags):
        rows = []
        for b, st in enumerate(block_starts):
            i0 = dates_all.index(st)
            for k in range(BLOCK_DAYS):
                rows.append((b, i0 + k, tags[b]))
        idx = np.array([r[1] for r in rows])
        blk = np.array([r[0] for r in rows])
        tag = np.array([r[2] for r in rows])
        arrs = {
            "day_date": np.array([dates_all[i].isoformat() for i in idx]), "day_block": blk.astype(np.int16),
            "day_tag": tag, "day_month": src_path["month"][idx].astype(np.int8), "day_dow": src_path["dow"][idx].astype(np.int8),
            "day_working": src_path["working"][idx], "day_holiday": src_path["holiday"][idx],
            "demand_mw": src["kbg"]["demand"][idx], "pv_mw": src["pv"]["pv"][idx],
            "spot": src_path["tokyo"][idx], "id_bid": src_path["id_bid"][idx], "id_ask": src_path["id_ask"][idx],
            "id_liq_mwh": src_path["id_liq_mwh"][idx], "imbalance": src_path["imbalance"][idx], "rm": src_path["rm"][idx],
            "da_demand_p50": src["kbg"]["da_p50"][idx], "da_demand_sd": src["kbg"]["da_sd"][idx],
            "da_pv_p50": src["pv"]["da_p50"][idx], "da_pv_sd": src["pv"]["da_sd"][idx],
            "da_price_p10": src["pf"]["p10"][idx], "da_price_p50": src["pf"]["p50"][idx], "da_price_p90": src["pf"]["p90"][idx],
            "da_rm_p50": src["pf"]["rm_fc"][idx],
            "ha_demand_p50": src["kbg"]["ha_p50"][idx], "ha_demand_sd": src["kbg"]["ha_sd"][idx],
            "ha_pv_p50": src["pv"]["ha_p50"][idx], "ha_pv_sd": src["pv"]["ha_sd"][idx], "ha_rm": src_path["rm_gc"][idx],
            "hist14": np.stack([src_path["tokyo"][i - 14:i] for i in idx]),
            "c_val": src_path["c_val"][idx],
        }
        return arrs

    train = gather(history, hist, hist_dates, TRAIN_BLOCKS, ["normal"] * len(TRAIN_BLOCKS))
    ho_hist = gather(history, hist, hist_dates, HOLDOUT_BLOCKS, ["normal"] * len(HOLDOUT_BLOCKS))
    ho_stress = gather(spath, shist, sdates, heat_starts + cold_starts, ["stress_heat_dome", "stress_cold_snap_lng"])
    ho_stress["day_block"] = ho_stress["day_block"] + len(HOLDOUT_BLOCKS)
    holdout = {k: np.concatenate([ho_hist[k], ho_stress[k]]) for k in ho_hist}
    params = {"bess": BESS, "bess_sites": [dict(zip(["site_id", "name", "prefecture", "mw", "mwh", "duration_h", "commissioned", "voltage"], s))
                                           for s in BESS_SITES],
              "pv_ppa": PV_PPA, "jepx": {"price_floor": facts.PRICE_FLOOR, "price_cap": facts.PRICE_CAP_SIM,
                                         "tick": facts.PRICE_TICK, "lot_mwh": facts.LOT_MWH, "da_gate_closure": "10:00 D-1",
                                         "intraday_gate_closure": "1 h before delivery"},
              "da_price_impact_jpy_kwh_per_mwh": facts.PRICE_NETLOAD[2025][1] / 500.0,
              "id_impact_jpy_kwh_per_mwh": 0.04, "imbalance_single_price": True,
              "compliance_tolerance": {"abs_mwh": 5.0, "rel": 0.03}}
    out = {}
    for fold, arrs in (("train", train), ("holdout", holdout)):
        arrs = {k: (v.astype(np.float32) if v.dtype == np.float64 else v) for k, v in arrs.items()}
        arrs["params_json"] = np.array(json.dumps(params, separators=(",", ":")))
        out[f"jepx_trading_{fold}"] = {"arrays": arrs}
    out["_kbg_history"] = hist
    out["_stress"] = {"path": spath, "series": shist, "heat_start": heat_starts[0].isoformat(), "cold_start": cold_starts[0].isoformat()}
    return out
