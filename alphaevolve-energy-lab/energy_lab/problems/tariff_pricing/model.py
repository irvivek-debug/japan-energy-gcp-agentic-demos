"""Trusted settlement model for the C&I tariff-pricing problem (FY2026 renewal book).

Everything here runs in the parent process on the frozen instance; candidate code never sees it. Units: JPY,
kWh, kW; portfolio results in JPY M. Settlement is vectorised over customers x scenarios x representative day
types (38 = 12 months x {working, non-working, shutdown} + heat-dome working + cold-snap working, weighted by
the scenario's own day counts), so one evaluation of 1,200 customers x 64 FY2026 scenarios takes well under a
second.

Economics per customer i and scenario s:
  revenue = (1-a) r E + a (CE - S_flex + adder E) + demand_charge kW 12 + penalty - DR discount paid
  cost    = CE - S_flex + wheeling + capacity + NFC(green) + balancing + imbalance + credit loss - DR benefit
  CE = loss_factor x sum(price x load) (JPY), S_flex = procurement saving from load the customer shifts under the
  market link (customer keeps a share a, retailer keeps 1-a).
Acceptance is a logit on the customer's subjective effective price vs its (hidden) competitor reference, with
risk aversion x alpha, term preference, deviation-penalty exposure, DR net value and expected flex savings.
Score = E_s[margin] - LAMBDA x CVaR95(E[margin] - margin_s) + retained lifetime value (JPY M).
The renewable-energy surcharge (4.18 JPY/kWh in FY2026) is a pure pass-through and excluded from both sides.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np
from scipy.special import expit
from scipy.stats import norm

from ...sim import facts
from ...sim.portfolio import SEG, SEGMENTS

N_DT = 38
IDX_HEAT, IDX_COLD = 36, 37
H_OPTIONS = np.array([1.0, 2.0, 3.0, 4.0, 6.0])
LAMBDA_CVAR = 0.5
CVAR_Q = 0.95
FLEX_EFFICIENCY = 0.6                  # share of declared flexible energy actually shifted daily (LAB-ASSUMPTION)
BALANCING_OVERHEAD = 0.25              # JPY/kWh BG operations cost (LAB-ASSUMPTION)
LGD, EXPOSURE_MONTHS = 0.6, 2.0
TERM_RISK_JPY_KWH = 1.5                # forward-level uncertainty per extra locked year (LAB-ASSUMPTION)
TERM_RISK_WEIGHT = 0.5
LTV_TERM_BONUS = 0.35
LOSS_FACTOR = {0: 1.04, 1: 1.03}       # HV, EHV (MARKET_FACTS 5.4 ESTIMATE 1.03-1.05)
WHEEL_BASIC = {0: (facts.WHEELING["HV"]["basic"], facts.WHEELING["HV"]["basic_from_2026_11"]),
               1: (facts.WHEELING["EHV"]["basic"], facts.WHEELING["EHV"]["basic_from_2026_11"])}
WHEEL_ENERGY = {0: facts.WHEELING["HV"]["energy"], 1: facts.WHEELING["EHV"]["energy"]}
TOKYO_H3_PEAK_KW = 55.0e6              # OCCTO FY2026 Tokyo summer peak forecast 55.0 GW (MARKET_FACTS 7)
CAPACITY_JPY_KW_YR = facts.CAPACITY_BURDEN_TOKYO_BN_JPY[2026] * 1e9 / TOKYO_H3_PEAK_KW   # derived ~4,597
NFC = facts.NFC_PRICE["nonFIT_renewable"]
POLICY = {"essential_alpha_max": 0.30, "fair_ceiling_ratio": 1.25, "band_min_pct": 5.0, "band_max_pct": 10.0,
          "nondiscrimination_tol": 0.08, "churn_max_portfolio": 0.15, "churn_max_energy": 0.15,
          "churn_max_segment": 0.25}
# Evaluator v2 (after run tariff_pricing.20260926T073839Z): during the SEARCH (train fold) the churn limits carry a guard
# band so a policy cannot ride the regulatory limit on the train cohort and tip over it on unseen customers. The holdout
# fold is always judged at the regulatory limits above.
TRAIN_CHURN_GUARD = {"churn_max_portfolio": 0.14, "churn_max_energy": 0.14, "churn_max_segment": 0.22}
# Evaluator v3 (after run tariff_pricing.20260926T074912Z): both earlier champions shed fixed-price risk by repricing a
# small, risk-averse segment (university churn 11.8% -> ~22% on train, >25% on the holdout cohort). That is a strategy
# change the score did not price. v3 encodes what the incumbent book protects: on every fold, no segment's churn may
# rise more than SEGMENT_CHURN_RISE_MAX above the incumbent (seed) book's churn for that segment on the same cohort.
SEGMENT_CHURN_RISE_MAX = 0.05
EVALUATOR_VERSION = ("tariff_pricing/v3: segment churn may rise <= 5 pp vs the incumbent book on the same cohort "
                     "(+ v2 train guard band 14%/22%); judged on the fresh holdout2 fold (holdout 1 burned by runs 1-2)")
OFFER_BOUNDS = {"energy_rate_jpy_kwh": (0.0, 80.0), "alpha": (0.0, 1.0), "market_adder_jpy_kwh": (-5.0, 20.0),
                "demand_charge_jpy_kw_month": (0.0, 6000.0), "deviation_band_pct": (0.0, 100.0),
                "deviation_penalty_jpy_kwh": (0.0, 50.0), "dr_discount_jpy_kw_month": (0.0, 3000.0),
                "term_years": (1, 3)}
OFFER_KEYS = tuple(OFFER_BOUNDS)


def dt_index(month: int, dt: int) -> int:
    return (month - 1) * 3 + dt


def dt_month(d: int) -> int:
    return 8 if d == IDX_HEAT else 1 if d == IDX_COLD else d // 3 + 1


def weather_coefs(seg_idx: np.ndarray) -> np.ndarray:
    """[N, N_DT, 2] (cool, heat) multipliers applied to (TA, -TA) per day type."""
    cool = np.array([SEG[s].cool for s in SEGMENTS])[seg_idx]
    heat = np.array([SEG[s].heat for s in SEGMENTS])[seg_idx]
    wc = np.zeros((len(seg_idx), N_DT, 2))
    for d in range(N_DT):
        m = dt_month(d)
        fc = 1.0 if m in (7, 8) else 0.6 if m in (6, 9) else 0.0
        fh = 1.0 if m in (12, 1, 2) else 0.5 if m in (3, 11) else 0.0
        wc[:, d, 0] = cool * fc
        wc[:, d, 1] = heat * fh
    return wc


def weather_mult(wc: np.ndarray, ta: np.ndarray) -> np.ndarray:
    """wc [N, D, 2], ta [S, D] -> [N, S, D]."""
    t = np.clip(ta, -6, 6)[None, :, :]
    return 1.0 + wc[:, None, :, 0] * np.maximum(t, -3.0) + wc[:, None, :, 1] * np.maximum(-t, -3.0)


def reconstruct_shapes(arch: np.ndarray, seg_idx: np.ndarray, amp: np.ndarray, shift: np.ndarray,
                       level: np.ndarray) -> np.ndarray:
    """arch [n_seg, N_DT, 48] -> customer shapes [N, N_DT, 48] (same transform as portfolio.customer_shape)."""
    base = arch[seg_idx]                                            # [N, D, 48]
    m = base.mean(axis=2, keepdims=True)
    shaped = m + amp[:, None, None] * (base - m)
    out = np.empty_like(shaped)
    for k in np.unique(shift):
        sel = shift == k
        out[sel] = np.roll(shaped[sel], int(k), axis=2)
    return out * level[:, None, None]


def g_excess(c: np.ndarray, sigma: np.ndarray) -> np.ndarray:
    """E[max(|X| - c, 0)], X ~ N(0, sigma)."""
    sigma = np.maximum(sigma, 1e-9)
    z = c / sigma
    return 2.0 * (sigma * norm.pdf(z) - c * (1.0 - norm.cdf(z)))


@dataclass
class Prepared:
    n: int
    seg_idx: np.ndarray
    volt: np.ndarray
    lf_band: np.ndarray
    contract_kw: np.ndarray
    B: np.ndarray
    SH: np.ndarray
    wc: np.ndarray
    E_fwd: np.ndarray            # kWh/yr at forward day counts, normal weather
    F: np.ndarray                # shape-weighted forward price JPY/kWh
    lf: np.ndarray
    wheel_basic_yr: np.ndarray   # JPY/yr (fixed)
    wheel_energy: np.ndarray     # JPY/kWh
    cap_cost: np.ndarray         # JPY/yr
    comp: np.ndarray             # true competitor effective price JPY/kWh (hidden)
    avail: np.ndarray            # DR availability [N, 48]
    h_idx: np.ndarray
    hidden: dict
    green: np.ndarray
    essential: np.ndarray
    # scenario tensors
    CE: np.ndarray               # [N, S] lf x sum(price x load), JPY
    E: np.ndarray                # [N, S] kWh
    FLEXV: np.ndarray            # [N, S] JPY saved if the full declared flex were shifted (before a/response)
    DRV: np.ndarray              # [N, S] JPY per kW of DR enrolled
    KAPPA: np.ndarray            # [S]
    flex_fwd: np.ndarray         # [N] expected JPY/yr flex value at forward (customer view)
    sigma_f: float               # forward vol JPY/kWh (customer risk view)
    S: int


def prepare(arr: dict, fwd_P: np.ndarray, fwd_W: np.ndarray, sigma_f: float, seg_ref: dict | None = None) -> Prepared:
    seg_idx = arr["c_seg"].astype(int)
    SH = reconstruct_shapes(arr["arch"], seg_idx, arr["c_amp"], arr["c_shift"].astype(int), arr["c_level"])
    B = arr["c_base_kw"]
    volt = arr["c_volt"].astype(int)
    lf = np.where(volt == 1, LOSS_FACTOR[1], LOSS_FACTOR[0])
    wc = weather_coefs(seg_idx)
    day_kwh = B[:, None] * SH.sum(axis=2) * 0.5                                  # [N, D] at normal weather
    E_fwd = day_kwh @ fwd_W
    F = (B[:, None] * np.einsum("idt,dt->id", SH, fwd_P) * 0.5 @ fwd_W) / E_fwd
    contract = arr["c_contract_kw"]
    basic = np.where(volt == 1, WHEEL_BASIC[1][0] * 7 + WHEEL_BASIC[1][1] * 5, WHEEL_BASIC[0][0] * 7 + WHEEL_BASIC[0][1] * 5)
    wheel_basic_yr = contract * basic
    wheel_energy = np.where(volt == 1, WHEEL_ENERGY[1], WHEEL_ENERGY[0])
    cool = np.array([SEG[s].cool for s in SEGMENTS])[seg_idx]
    cp_kw = B * SH[:, dt_index(8, 0), 28] * (1 + 2.0 * cool)
    cap_cost = CAPACITY_JPY_KW_YR * cp_kw
    green = arr["c_green"].astype(bool)
    comp = (F * lf + (wheel_basic_yr + cap_cost) / E_fwd + wheel_energy + arr["h_comp_margin"] + NFC * green
            + BALANCING_OVERHEAD) * arr["h_comp_noise"]
    peak_ref = np.maximum(SH[:, dt_index(8, 0)], SH[:, dt_index(1, 0)])
    avail = np.clip(peak_ref / peak_ref.max(axis=1, keepdims=True), 0, 1)
    h_idx = np.abs(arr["c_flex_hours"][:, None] - H_OPTIONS[None, :]).argmin(axis=1)
    hidden = {k: arr[k] for k in arr if k.startswith("h_")}
    # --- scenario tensors ---
    P, W, TA = arr["s_P"].astype(float), arr["s_W"].astype(float), arr["s_TA"].astype(float)
    wm = weather_mult(wc, TA)                                                 # [N, S, D]
    A = np.einsum("idt,sdt->isd", SH, P)                                      # [N, S, D]
    CE = lf[:, None] * B[:, None] * 0.5 * np.einsum("isd,sd->is", wm * A, W)
    Eday = B[:, None, None] * wm * SH.sum(axis=2)[:, None, :] * 0.5           # [N, S, D]
    E = np.einsum("isd,sd->is", Eday, W)
    SP = arr["s_SP"].astype(float)                                            # [S, D, 5]
    sp_i = SP[:, :, h_idx].transpose(2, 0, 1)                                 # [N, S, D]
    FLEXV = FLEX_EFFICIENCY * lf[:, None] * np.einsum("isd,sd->is", Eday * sp_i, W)
    DRV = avail @ arr["s_DRV"].astype(float).T                                # [N, S] JPY per kW
    # customer-side expectation of flex value at the forward (train-mean spreads)
    SPf = arr["f_SP"].astype(float)                                           # [D, 5]
    flex_fwd = FLEX_EFFICIENCY * lf * ((day_kwh * SPf[:, h_idx].T) @ fwd_W)
    return Prepared(n=len(B), seg_idx=seg_idx, volt=volt, lf_band=arr["c_lfband"].astype(int), contract_kw=contract,
                    B=B, SH=SH, wc=wc, E_fwd=E_fwd, F=F, lf=lf, wheel_basic_yr=wheel_basic_yr,
                    wheel_energy=wheel_energy, cap_cost=cap_cost, comp=comp, avail=avail, h_idx=h_idx, hidden=hidden,
                    green=green, essential=arr["c_essential"].astype(bool), CE=CE, E=E, FLEXV=FLEXV, DRV=DRV,
                    KAPPA=arr["s_KAPPA"].astype(float), flex_fwd=flex_fwd, sigma_f=float(sigma_f), S=P.shape[0])


def offers_to_arrays(offers: list[dict]) -> dict[str, np.ndarray]:
    return {k: np.array([float(o[k]) for o in offers]) for k in OFFER_KEYS}


def settle(pre: Prepared, o: dict[str, np.ndarray], seg_ref: np.ndarray) -> dict:
    """Vectorised FY2026 settlement of an offer book. Returns metrics, per-customer arrays and invariant inputs."""
    h = pre.hidden
    a, r, adder = o["alpha"], o["energy_rate_jpy_kwh"], o["market_adder_jpy_kwh"]
    dch, band, q = o["demand_charge_jpy_kw_month"], o["deviation_band_pct"], o["deviation_penalty_jpy_kwh"]
    disc, T = o["dr_discount_jpy_kw_month"], np.round(o["term_years"])
    # deviation discipline
    strength = np.minimum(1.0, q / 3.0) * (1.0 - (np.clip(band, 5, 10) - 5.0) / 10.0)
    red = 1.0 - h["h_discipline"] * strength
    sig_slot, sig_month = h["h_sigma_slot"] * red, h["h_sigma_month"] * red
    pen_rate = g_excess(band / 100.0, sig_month)                     # expected excess deviation share per month
    pen_fwd = q * pen_rate * pre.E_fwd                               # JPY/yr (customer cost, retailer revenue)
    # DR
    dr_kw = h["h_dr_share"] * pre.contract_kw
    p_dr = np.where((disc > 0) & (dr_kw > 0), expit(4.0 * (disc / np.maximum(h["h_dr_cost"], 1.0) - 1.0)), 0.0)
    dr_pay = disc * dr_kw * 12.0 * p_dr
    dr_net_cust = p_dr * np.maximum(disc - h["h_dr_cost"], 0.0) * dr_kw * 12.0
    # --- customer view at the forward (acceptance) ---
    bill_fwd = ((1 - a) * r * pre.E_fwd + a * (pre.F * pre.lf + adder) * pre.E_fwd + dch * pre.contract_kw * 12.0
                + pen_fwd - dr_pay)
    eff = bill_fwd / pre.E_fwd
    shift_frac = h["h_flex_response"] * np.minimum(1.0, a / 0.5) * pre.hidden["h_flex_share"]
    flex_saving_cust = a * shift_frac * pre.flex_fwd
    risk_prem = h["h_risk_aversion"] * a * pre.sigma_f * 0.5
    eff_sub = eff + risk_prem - (flex_saving_cust + dr_net_cust) / pre.E_fwd
    certainty = 0.15 * h["h_risk_aversion"] * (T - 1) * (1 - a)
    U = (h["h_inertia"] + h["h_elasticity"] * 100.0 * (pre.comp - eff_sub) / pre.comp
         - 0.25 * np.abs(T - h["h_term_pref"]) + certainty)
    P = expit(U)
    # --- settlement under each scenario [N, S] ---
    E = pre.E
    s_flex = shift_frac[:, None] * pre.FLEXV
    rev = ((1 - a)[:, None] * r[:, None] * E + a[:, None] * (pre.CE - s_flex + adder[:, None] * E)
           + (dch * pre.contract_kw * 12.0 + q * pen_rate * pre.E_fwd - dr_pay)[:, None])
    imb = (sig_slot * h["h_weather_corr"])[:, None] * E * pre.KAPPA[None, :]
    credit = (h["h_pd"] * LGD * EXPOSURE_MONTHS / 12.0)[:, None] * rev
    cost = (pre.CE - s_flex + pre.wheel_basic_yr[:, None] + pre.wheel_energy[:, None] * E + pre.cap_cost[:, None]
            + (NFC * pre.green + BALANCING_OVERHEAD)[:, None] * E + imb + credit
            - (p_dr * dr_kw)[:, None] * pre.DRV)
    margin = rev - cost                                                   # JPY [N, S]
    M = (P[:, None] * margin).sum(axis=0) / 1e6                           # JPY M per scenario
    EM = float(M.mean())
    short = EM - M
    k = max(1, int(np.ceil((1 - CVAR_Q) * len(M))))
    cvar = float(np.sort(short)[-k:].mean())
    ltv_i = P * (h["h_clv_jpy_m"] * (1 + LTV_TERM_BONUS * (T - 1))
                 - TERM_RISK_WEIGHT * (T - 1) * (1 - a) * pre.E_fwd * TERM_RISK_JPY_KWH / 1e6)
    ltv = float(ltv_i.sum())
    score = EM - LAMBDA_CVAR * cvar + ltv
    churn = 1 - P
    seg_churn = {SEGMENTS[s]: float(churn[pre.seg_idx == s].mean()) for s in np.unique(pre.seg_idx)}
    return {
        "score": score, "expected_margin": EM, "cvar95_shortfall": cvar, "ltv": ltv, "M": M,
        "worst_margin": float(M.min()), "best_margin": float(M.max()),
        "churn_count": float(churn.mean()), "churn_energy": float((churn * pre.E_fwd).sum() / pre.E_fwd.sum()),
        "seg_churn": seg_churn, "P": P, "eff": eff, "eff_sub": eff_sub,
        "mean_alpha": float((a * pre.E_fwd).sum() / pre.E_fwd.sum()),
        "dr_enrolled_mw": float((p_dr * dr_kw * P).sum() / 1000.0),
        "flex_value_retailer": float(((1 - a)[:, None] * s_flex * P[:, None]).sum(axis=0).mean() / 1e6),
        "imbalance_cost": float((imb * P[:, None]).sum(axis=0).mean() / 1e6),
        "penalty_revenue": float((q * pen_rate * pre.E_fwd * P).sum() / 1e6),
        "retained_twh": float((P * pre.E_fwd).sum() / 1e9),
        "margin_per_kwh": float(EM * 1e6 / max((P * pre.E_fwd).sum(), 1.0)),
    }


def market_json(arr: dict) -> dict:
    return json.loads(str(arr["market_json"]))
