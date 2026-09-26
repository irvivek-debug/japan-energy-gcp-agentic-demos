"""FY2023-FY2025 'realised' history (calibrated synthetic) and calibration statistics."""
from __future__ import annotations

from dataclasses import replace

import numpy as np

from . import facts
from .calendar import fy_days
from datetime import date

from .market import Event, Regime, simulate

MONTHS_FY = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]

# Per-FY regime settings (LAB calibration choices; targets are MARKET_FACTS figures).
HISTORY_REGIMES = {
    2023: Regime(name="FY2023", rm_lt8_target=25, rm_tail_target=(0.062, 6), imb_noise=3.3, imb_k=6.5, sys_premium_mean=1.42,
                 events=[Event("heat", date(2023, 7, 24), 8, temp_delta=1.3), Event("heat", date(2023, 9, 4), 6, temp_delta=1.0)]),
    2024: Regime(name="FY2024", rm_lt8_target=42, rm_tail_target=(0.062, 14), imb_noise=4.0, imb_k=8.0, sys_premium_mean=1.20,
                 events=[Event("heat", date(2024, 7, 22), 9, temp_delta=1.5), Event("cold", date(2025, 2, 4), 5, temp_delta=-2.5)]),
    2025: Regime(name="FY2025", rm_lt8_target=38, rm_tail_target=(0.062, 8), imb_noise=2.5, imb_k=5.5, sys_premium_mean=1.33,
                 events=[Event("heat", date(2025, 8, 1), 8, temp_delta=1.5), Event("cold", date(2026, 2, 7), 4, temp_delta=-2.2)]),
}
# Hot-summer temperature anomalies vs the model's warm-shifted normals (LAB-ASSUMPTION; recent summers were
# record-warm, these are not measured values).
TEMP_ANOM = {(2023, 7): 0.6, (2023, 8): 1.0, (2023, 9): 1.8, (2024, 7): 1.0, (2024, 8): 0.8, (2024, 9): 1.4,
             (2025, 7): 0.9, (2025, 8): 0.7, (2025, 9): 0.6, (2023, 12): 0.8, (2024, 1): 0.6, (2025, 2): -0.6}
GROWTH = {2023: 0.992, 2024: 0.996, 2025: 1.0, 2026: 1.004}
PV_CAP = {2023: 0.90, 2024: 0.95, 2025: 1.0, 2026: 1.05}


def monthly_targets(fy: int) -> dict[tuple[int, int], float]:
    """(calendar-year-agnostic) {(fy, month): target mean}. FY2025 monthly figures are VERIFIED (computed);
    FY2023/FY2024 reuse the FY2025 monthly profile scaled to the VERIFIED annual mean."""
    base = np.array(facts.TOKYO_MONTHLY_FY2025)
    if fy == 2025:
        vals = base
    else:
        vals = base / base.mean() * facts.TOKYO_ANNUAL_MEAN[fy]
    return {(fy, m): float(v) for m, v in zip(MONTHS_FY, vals)}


def floor_counts(fy: int) -> dict[int, int]:
    base = {2: 1, 3: 33, 4: 35, 5: 36}                     # FY2025 Tokyo counts, VERIFIED (computed)
    scale = {2023: 0.5, 2024: 0.7, 2025: 1.0}.get(fy, 1.0)  # fewer floor events with less solar (LAB-ASSUMPTION)
    return {m: int(round(c * scale)) for m, c in base.items()}


def generate_history(seed: int = 20260926) -> dict[str, np.ndarray]:
    parts = []
    for k, fy in enumerate((2023, 2024, 2025)):
        rng = np.random.default_rng(seed + 1000 * k)
        days = fy_days(fy)
        path = simulate(days, rng, HISTORY_REGIMES[fy], monthly_targets(fy), TEMP_ANOM, GROWTH, PV_CAP,
                        floor_counts(fy))
        parts.append(path)
    out = {}
    for key in parts[0]:
        out[key] = np.concatenate([p[key] for p in parts], axis=0)
    return out


def price_stats(path: dict, fy: int) -> dict:
    sel = path["fy"] == fy
    p = path["tokyo"][sel]
    sysp = path["system"][sel]
    imb = path["imbalance"][sel]
    working = path["working"][sel]
    daily = p.mean(axis=1)
    flat = p.ravel()
    lr = np.diff(np.log(daily))
    x = flat - flat.mean()
    lag1 = float((x[1:] * x[:-1]).mean() / x.var())
    lag48 = float((x[48:] * x[:-48]).mean() / x.var())
    top4 = np.sort(p, axis=1)[:, -4:].mean(axis=1)
    bot4 = np.sort(p, axis=1)[:, :4].mean(axis=1)
    d = (imb - p).ravel()
    months = path["month"][sel]
    monthly = [float(p[months == m].mean()) for m in MONTHS_FY]
    return {
        "fy": fy, "tokyo_mean": float(flat.mean()), "system_mean": float(sysp.mean()),
        "tokyo_premium": float((p - sysp).mean()), "p5": float(np.percentile(flat, 5)),
        "p50": float(np.percentile(flat, 50)), "p95": float(np.percentile(flat, 95)), "max": float(flat.max()),
        "weekday_mean": float(p[working].mean()), "weekend_mean": float(p[~working].mean()),
        "daily_mean_sd": float(daily.std()), "daily_range_mean": float((p.max(1) - p.min(1)).mean()),
        "within_day_sd": float(p.std(axis=1).mean()), "dod_logret_sd": float(lr.std()), "lag1": lag1, "lag48": lag48,
        "floor_slots": int((flat <= 0.011).sum()), "spread_2h": float((top4 - bot4).mean()),
        "imb_minus_spot_mean": float(d.mean()), "imb_minus_spot_sd": float(d.std()),
        "imb_p5": float(np.percentile(d, 5)), "imb_p95": float(np.percentile(d, 95)),
        "imb_zero_share": float((imb.ravel() <= 0.001).mean()), "imb_ge45": int((imb >= 45).sum()),
        "imb_ge100": int((imb >= 100).sum()), "imb_max": float(imb.max()),
        "rm_lt10": int((path["rm"][sel] < 0.10).sum()), "rm_lt8": int((path["rm"][sel] < 0.08).sum()),
        "rm_min": float(path["rm"][sel].min()),
        "demand_twh": float(path["demand"][sel].sum() * 0.5 / 1000), "demand_peak": float(path["demand"][sel].max()),
        "demand_min": float(path["demand"][sel].min()),
        "pv_share": float(path["pv"][sel].sum() / path["demand"][sel].sum()), "pv_max": float(path["pv"][sel].max()),
        "monthly": monthly,
        "id_minus_spot_mean": float((path["id_mid"][sel] - p).mean()), "id_minus_spot_sd": float((path["id_mid"][sel] - p).std()),
    }
