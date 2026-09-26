"""Kanto Balance Group (KBG) C&I customer portfolio: CALIBRATED SYNTHETIC, fictional customers.

Segment archetypes carry 30-min load shapes (weekday / non-working / shutdown), monthly factors, weather
sensitivity, forecastability, flexibility, price response, DR willingness and relationship value. Per-customer
parameters perturb the archetype deterministically, so the evaluator reconstructs every load from a few numbers
(no billions of rows). All segment parameters are LAB-ASSUMPTIONS (documented in docs/SCENARIO_AND_DATA.md); the
wheeling / voltage split follows the TEPCO PG tariff classes in MARKET_FACTS 5.1 (HV 50-2,000 kW, EHV >= 2,000 kW).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .market import HOURS_SLOT, h24_to_slots

SEGMENTS = ["data_center", "semiconductor_fab", "auto_parts", "cold_storage", "office", "retail_chain", "hospital",
            "water_utility", "university", "logistics", "hotel"]


@dataclass(frozen=True)
class Segment:
    name: str
    n_train: int
    kw_median: float
    kw_sigma: float
    weekday24: tuple
    nonwork_level: float           # non-working-day level multiplier on the weekday shape (or flat level if flat_nonwork)
    flat_nonwork: bool
    shutdown_level: float          # New Year / Obon
    monthly: tuple                 # Jan..Dec multipliers (normal weather)
    cool: float                    # relative load change per deg C (summer anomaly)
    heat: float                    # relative load change per deg C colder (winter anomaly)
    sigma_slot: float              # 30-min deviation vs plan (fraction)
    sigma_month: float             # monthly energy deviation vs plan (fraction)
    flex_share: float
    flex_hours: float
    style_probs: tuple             # (tender, negotiated, auto_renew)
    elasticity_mult: float
    risk_aversion: tuple           # (lo, hi) uniform
    term_pref: tuple               # probabilities for T* = 1, 2, 3
    dr_share: float
    dr_cost_median: float          # JPY/kW-month needed to enrol
    green_prob: float
    weather_corr: float            # correlation of deviations with the system weather factor
    discipline: tuple              # achievable deviation reduction under a strict band (lo, hi)
    clv_per_mw: float              # relationship value, JPY M per MW-year (cross-sell: PPA, BESS, DR)
    essential: bool = False


def _t(*v):
    return tuple(float(x) for x in v)


SEG = {s.name: s for s in [
    Segment("data_center", 36, 3500, 0.55, _t(*[0.97] * 10, 1.0, 1.02, 1.03, 1.03, 1.03, 1.02, 1.0, *[0.98] * 7), 1.0, False, 0.98,
            _t(0.98, 0.98, 0.98, 0.99, 1.0, 1.02, 1.05, 1.06, 1.04, 1.0, 0.99, 0.98), 0.004, 0.0, 0.025, 0.015, 0.03, 2,
            (0.6, 0.4, 0.0), 1.3, (0.08, 0.3), (0.3, 0.4, 0.3), 0.05, 800, 0.8, 0.2, (0.2, 0.4), 1.5),
    Segment("semiconductor_fab", 14, 6000, 0.5, _t(*[0.99] * 8, *[1.01] * 10, *[1.0] * 6), 0.99, False, 0.97,
            _t(0.99, 0.99, 0.99, 1.0, 1.0, 1.01, 1.03, 1.03, 1.02, 1.0, 0.99, 0.99), 0.003, 0.0, 0.03, 0.02, 0.02, 1,
            (0.5, 0.5, 0.0), 1.2, (0.8, 1.4), (0.2, 0.4, 0.4), 0.02, 1500, 0.7, 0.15, (0.3, 0.5), 2.0),
    Segment("auto_parts", 170, 700, 0.7, _t(0.35, 0.35, 0.35, 0.35, 0.35, 0.4, 0.55, 0.8, 1.0, 1.0, 1.0, 1.0, 0.85, 1.0, 1.0, 1.0, 1.0, 0.92, 0.9, 0.9, 0.9, 0.88, 0.8, 0.55),
            0.32, True, 0.15, _t(0.97, 1.0, 1.02, 0.98, 0.97, 1.0, 1.03, 0.95, 1.02, 1.0, 1.0, 0.98), 0.010, 0.003, 0.08, 0.04, 0.08, 3,
            (0.3, 0.4, 0.3), 1.1, (0.6, 1.2), (0.6, 0.3, 0.1), 0.15, 500, 0.25, 0.5, (0.3, 0.6), 1.0),
    Segment("cold_storage", 90, 450, 0.6, _t(*[0.9] * 7, 0.95, *[1.06] * 10, 1.0, 0.95, *[0.9] * 4), 0.96, False, 0.9,
            _t(0.9, 0.9, 0.94, 0.98, 1.02, 1.08, 1.16, 1.18, 1.1, 1.0, 0.94, 0.92), 0.015, 0.0, 0.06, 0.035, 0.22, 4,
            (0.2, 0.3, 0.5), 1.0, (0.4, 1.0), (0.5, 0.35, 0.15), 0.30, 250, 0.15, 0.6, (0.4, 0.7), 1.2),
    Segment("office", 300, 450, 0.8, _t(0.25, 0.25, 0.25, 0.25, 0.25, 0.25, 0.3, 0.45, 0.8, 1.0, 1.0, 1.0, 0.95, 1.0, 1.0, 1.0, 1.0, 0.95, 0.85, 0.7, 0.55, 0.4, 0.3, 0.27),
            0.3, True, 0.25, _t(1.1, 1.08, 0.98, 0.92, 0.92, 1.02, 1.2, 1.22, 1.12, 0.94, 0.95, 1.05), 0.030, 0.015, 0.07, 0.035, 0.06, 2,
            (0.3, 0.3, 0.4), 1.0, (0.7, 1.3), (0.6, 0.3, 0.1), 0.10, 450, 0.35, 0.8, (0.2, 0.4), 0.6),
    Segment("retail_chain", 190, 400, 0.6, _t(0.35, 0.35, 0.35, 0.35, 0.35, 0.35, 0.38, 0.45, 0.55, 0.85, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.95, 0.8, 0.5, 0.4),
            1.05, False, 0.8, _t(1.05, 1.03, 0.98, 0.94, 0.95, 1.02, 1.15, 1.17, 1.08, 0.96, 0.96, 1.05), 0.025, 0.010, 0.06, 0.03, 0.05, 2,
            (0.4, 0.4, 0.2), 1.1, (0.5, 1.0), (0.6, 0.3, 0.1), 0.08, 500, 0.3, 0.75, (0.2, 0.4), 0.8),
    Segment("hospital", 80, 800, 0.6, _t(0.7, 0.7, 0.7, 0.7, 0.7, 0.72, 0.75, 0.8, 0.95, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 0.95, 0.9, 0.9, 0.85, 0.8, 0.75, 0.72),
            0.88, False, 0.88, _t(1.07, 1.06, 1.0, 0.95, 0.95, 1.02, 1.12, 1.14, 1.06, 0.96, 0.98, 1.05), 0.020, 0.012, 0.05, 0.025, 0.03, 1,
            (0.3, 0.2, 0.5), 0.8, (1.2, 2.0), (0.4, 0.3, 0.3), 0.0, 5000, 0.1, 0.7, (0.2, 0.4), 1.0, True),
    Segment("water_utility", 45, 1200, 0.8, _t(0.88, 0.88, 0.88, 0.88, 0.88, 0.95, 1.05, 1.08, 1.05, 1.0, 0.95, 0.95, 0.95, 0.95, 0.95, 0.97, 1.0, 1.05, 1.08, 1.06, 1.02, 0.98, 0.92, 0.9),
            0.97, False, 0.97, _t(0.97, 0.97, 0.98, 0.99, 1.0, 1.02, 1.06, 1.08, 1.04, 1.0, 0.98, 0.97), 0.008, 0.0, 0.05, 0.03, 0.25, 6,
            (0.9, 0.1, 0.0), 0.9, (1.2, 2.0), (0.7, 0.2, 0.1), 0.30, 300, 0.2, 0.4, (0.4, 0.7), 1.0, True),
    Segment("university", 50, 1100, 0.7, _t(0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.35, 0.45, 0.8, 1.0, 1.0, 1.0, 0.95, 1.0, 1.0, 1.0, 1.0, 0.9, 0.8, 0.75, 0.6, 0.45, 0.35, 0.32),
            0.35, True, 0.3, _t(1.0, 0.85, 0.75, 0.95, 1.0, 1.05, 1.1, 0.78, 0.95, 1.0, 1.0, 0.98), 0.025, 0.012, 0.09, 0.05, 0.06, 2,
            (0.8, 0.2, 0.0), 1.0, (0.8, 1.5), (0.8, 0.15, 0.05), 0.10, 400, 0.5, 0.7, (0.2, 0.4), 0.8),
    Segment("logistics", 150, 500, 0.7, _t(0.62, 0.6, 0.6, 0.6, 0.62, 0.75, 0.82, 0.88, 0.95, 1.0, 1.0, 1.0, 0.98, 1.0, 1.0, 1.0, 1.0, 0.98, 0.95, 0.92, 0.9, 0.85, 0.75, 0.68),
            0.8, False, 0.6, _t(0.98, 0.97, 0.98, 0.98, 0.98, 1.02, 1.07, 1.08, 1.04, 1.0, 1.02, 1.1), 0.012, 0.006, 0.09, 0.05, 0.12, 4,
            (0.3, 0.3, 0.4), 1.05, (0.5, 1.0), (0.6, 0.3, 0.1), 0.15, 350, 0.3, 0.55, (0.3, 0.5), 1.2),
    Segment("hotel", 75, 700, 0.6, _t(0.65, 0.63, 0.62, 0.62, 0.63, 0.7, 0.85, 1.0, 1.0, 0.95, 0.85, 0.8, 0.8, 0.78, 0.78, 0.8, 0.88, 0.95, 1.05, 1.05, 1.05, 1.0, 0.9, 0.78),
            1.05, False, 1.05, _t(1.04, 1.03, 1.0, 0.97, 0.98, 1.02, 1.12, 1.15, 1.05, 0.98, 0.98, 1.04), 0.020, 0.012, 0.07, 0.04, 0.05, 2,
            (0.2, 0.3, 0.5), 0.9, (0.6, 1.2), (0.5, 0.35, 0.15), 0.05, 700, 0.2, 0.7, (0.2, 0.4), 0.6),
]}

STYLES = ["tender", "negotiated", "auto_renew"]
STYLE_INERTIA = {"tender": 2.0, "negotiated": 2.5, "auto_renew": 3.15}       # logit utility at price parity
STYLE_ELASTICITY = {"tender": 0.36, "negotiated": 0.24, "auto_renew": 0.14}   # logit units per 1% price gap
CREDIT = ["A", "B", "C", "D"]
CREDIT_PD = {"A": 0.002, "B": 0.008, "C": 0.025, "D": 0.06}


def segment_shape(seg: Segment, month: int, daytype: str) -> np.ndarray:
    """Normalised 48-slot shape (weekday peak ~1) for a segment, month and day type (working/nonworking/shutdown)."""
    wk = h24_to_slots(seg.weekday24)
    if daytype == "working":
        base = wk
    elif daytype == "shutdown":
        base = wk * seg.shutdown_level if not seg.flat_nonwork else np.full(48, seg.shutdown_level)
    else:
        base = np.full(48, seg.nonwork_level) if seg.flat_nonwork else wk * seg.nonwork_level
    return base * seg.monthly[month - 1]


def draw_customers(cohort: str, n_total: int, seed: int) -> list[dict]:
    """Draw a cohort. Feature fields are visible to price_book; fields prefixed h_ are hidden evaluator behaviour."""
    rng = np.random.default_rng(seed)
    scale = n_total / sum(s.n_train for s in SEG.values())
    out = []
    cid = 0
    for name in SEGMENTS:
        seg = SEG[name]
        n = max(3, int(round(seg.n_train * scale)))
        for _ in range(n):
            cid += 1
            kw = float(np.clip(rng.lognormal(np.log(seg.kw_median), seg.kw_sigma), 60, 60000))
            voltage = "EHV" if kw >= 2000 else "HV"
            style = STYLES[rng.choice(3, p=np.array(seg.style_probs) / sum(seg.style_probs))]
            amp = float(np.clip(rng.normal(1.0, 0.08), 0.8, 1.2))
            shift = int(rng.integers(-2, 3))
            level = float(np.clip(rng.normal(1.0, 0.06), 0.85, 1.15))
            credit = CREDIT[rng.choice(4, p=[0.35, 0.4, 0.18, 0.07])]
            tenure = int(rng.integers(1, 11))
            switched = bool(rng.random() < (0.45 if style == "tender" else 0.2))
            risk = float(rng.uniform(*seg.risk_aversion))
            dr_cost = float(rng.lognormal(np.log(seg.dr_cost_median), 0.35))
            flex = float(np.clip(seg.flex_share * rng.lognormal(0, 0.35), 0, 0.45))
            sig_slot = float(seg.sigma_slot * rng.lognormal(0, 0.25))
            sig_month = float(seg.sigma_month * rng.lognormal(0, 0.25))
            t_pref = int(rng.choice([1, 2, 3], p=seg.term_pref))
            out.append({
                "customer_id": f"{cohort[:2].upper()}-{cid:05d}", "cohort": cohort, "segment": name, "voltage": voltage,
                "contract_kw": round(kw, 1), "essential": seg.essential,
                "green_required": bool(rng.random() < seg.green_prob), "credit_rating": credit, "tenure_years": tenure,
                "switched_last_5y": switched, "procurement_style": style,
                "flex_share": round(flex, 4), "flex_hours": float(seg.flex_hours),
                "forecast_mape_pct": round(100 * sig_slot * 0.8, 2), "monthly_deviation_pct": round(100 * sig_month, 2),
                "risk_appetite": _appetite(risk, seg.risk_aversion, rng),
                "dr_interest": "none" if seg.dr_share == 0 else ("high" if dr_cost < seg.dr_cost_median * 0.8 else
                                                                  "medium" if dr_cost < seg.dr_cost_median * 1.2 else "low"),
                "preferred_term_hint": t_pref if rng.random() < 0.7 else int(rng.choice([1, 2, 3])),
                # shape modifiers (deterministic reconstruction)
                "shape_amp": round(amp, 4), "shape_shift": shift, "level_mult": round(level, 4),
                # hidden behaviour (evaluator only)
                "h_risk_aversion": round(risk, 4),
                "h_elasticity": round(STYLE_ELASTICITY[style] * seg.elasticity_mult * float(rng.lognormal(0, 0.2)), 4),
                "h_inertia": round(STYLE_INERTIA[style] + 0.05 * min(tenure, 8) - (0.35 if switched else 0.0) + float(rng.normal(0, 0.25)), 4),
                "h_term_pref": t_pref, "h_dr_cost": round(dr_cost, 1), "h_dr_share": seg.dr_share,
                "h_flex_response": round(float(rng.beta(4, 3)), 4), "h_flex_share": round(flex, 4),
                "h_sigma_slot": round(sig_slot, 5), "h_sigma_month": round(sig_month, 5),
                "h_discipline": round(float(rng.uniform(*seg.discipline)), 4),
                "h_weather_corr": round(float(np.clip(seg.weather_corr + rng.normal(0, 0.08), 0, 0.95)), 4),
                "h_pd": CREDIT_PD[credit], "h_clv_jpy_m": round(kw / 1000 * seg.clv_per_mw * float(rng.lognormal(0, 0.4)), 4),
                "h_comp_margin": round(float(rng.normal(1.75, 0.45)), 4), "h_comp_noise": round(float(rng.lognormal(0, 0.03)), 5),
                "h_quote_noise": round(float(rng.lognormal(0, 0.035)), 5),
            })
    return out


def _appetite(risk: float, rng_bounds: tuple, rng: np.random.Generator) -> str:
    """Noisy survey proxy of (hidden) risk aversion: high aversion -> 'low' appetite, ~75% accurate."""
    lo, hi = rng_bounds
    pct = (risk - lo) / max(hi - lo, 1e-9) + rng.normal(0, 0.2)
    return "low" if pct > 0.66 else ("high" if pct < 0.33 else "medium")


def customer_shape(c: dict, month: int, daytype: str) -> np.ndarray:
    """48-slot relative load for one customer (before level scaling), deterministic from its parameters."""
    seg = SEG[c["segment"]]
    base = segment_shape(seg, month, daytype)
    m = base.mean()
    shaped = m + c["shape_amp"] * (base - m)
    return np.roll(shaped, c["shape_shift"]) * c["level_mult"]


def weather_multiplier(seg: Segment, month: int, temp_anom: float) -> float:
    if month in (7, 8):
        return 1.0 + seg.cool * max(temp_anom, -3.0)
    if month in (6, 9):
        return 1.0 + 0.6 * seg.cool * max(temp_anom, -3.0)
    if month in (12, 1, 2):
        return 1.0 + seg.heat * max(-temp_anom, -3.0)
    if month in (3, 11):
        return 1.0 + 0.5 * seg.heat * max(-temp_anom, -3.0)
    return 1.0


def annual_avg_kw(c: dict) -> float:
    """Contract kW x an implied load factor from the archetype (so kW, kWh and shape are consistent)."""
    seg = SEG[c["segment"]]
    wk = segment_shape(seg, 6, "working")
    return c["contract_kw"] * float(np.mean(wk)) / float(np.max(wk) * 1.08)


def daytype_of(working: bool, obs: str) -> str:
    if obs in ("new_year", "obon"):
        return "shutdown"
    return "working" if working else "nonworking"


SLOT_HOURS = HOURS_SLOT
