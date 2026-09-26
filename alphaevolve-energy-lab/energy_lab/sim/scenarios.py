"""FY2026 Monte Carlo scenario bank (CALIBRATED SYNTHETIC).

The tariff book is priced as of March 2026 for the FY2026 contract year. Scenario regimes:
  baseline        FY2025-like levels (MARKET_FACTS 1.3 monthly profile) x U(0.92, 1.12)
  moderate_shock  FY2025 x U(1.25, 1.50), wider intraday shape, steeper net-load slope
  severe_shock    FY2025 x U(1.55, 1.90), FY2026-like shape stretch (spring trough/peak 11.8/29.7, MARKET_FACTS 1.4)
  realised_like   Apr-Sep = FY2026 to-date monthly means (MARKET_FACTS 1.3) x U(0.97, 1.03), Oct-Mar = FY2025 x U(1.45, 1.85)
Stress events (injected on top of the regime level):
  cold_snap_lng   Jan 2027, 14-21 days, -4.5 C, 2-3 GW capacity loss, daily-mean peak U(110, 170) JPY/kWh
                  (Jan-2021 event: Tokyo daily mean 167, peak 252 JPY/kWh, MARKET_FACTS 1.6)
  heat_dome       Jul/Aug 2026, 8-12 days, +3.2 C, 1-2 GW loss, daily-mean peak U(55, 90) (2022: daily 69-86, peak 200)
All FY2026 paths switch the imbalance scarcity curve to C=300 / D=50 on 2026-10-01 and apply the cumulative-price
rule after the switch (MARKET_FACTS 3).

Train bank (the pricing desk's forward view): 55% baseline, 30% moderate, 15% severe; cold snap 8%, heat dome 12%.
Holdout bank (unseen seeds, harsher): 40% realised_like, 20% baseline, 15% moderate, 25% severe; cold snap 25%,
heat dome 25%.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import numpy as np

from . import facts
from .calendar import fy_days
from .history import GROWTH, MONTHS_FY, PV_CAP
from .market import Event, Regime, simulate

BANKS = {
    "train": {"regimes": (("baseline", 0.55), ("moderate_shock", 0.30), ("severe_shock", 0.15)),
              "p_cold": 0.08, "p_heat": 0.12},
    "holdout": {"regimes": (("realised_like", 0.40), ("baseline", 0.20), ("moderate_shock", 0.15), ("severe_shock", 0.25)),
                "p_cold": 0.25, "p_heat": 0.25},
}
FY26_FLOORS = {2: 2, 3: 30, 4: 30, 5: 60}      # FY2026 to date: Apr 28, May 70 Tokyo floor slots (MARKET_FACTS 1.4)


def draw_regime(rng: np.random.Generator, bank: str) -> tuple[Regime, dict, str, list[str]]:
    spec = BANKS[bank]
    names = [r for r, _ in spec["regimes"]]
    probs = np.array([p for _, p in spec["regimes"]])
    name = names[rng.choice(len(names), p=probs / probs.sum())]
    base = np.array(facts.TOKYO_MONTHLY_FY2025)
    noise = rng.lognormal(0, 0.05, 12)
    if name == "baseline":
        vals = base * rng.uniform(0.92, 1.12) * noise
        reg = Regime(name=name, rm_lt8_target=45, rm_tail_target=(0.062, 10), imb_noise=3.0, imb_k=6.0)
    elif name == "moderate_shock":
        vals = base * rng.uniform(1.25, 1.50) * noise
        reg = Regime(name=name, shape_stretch=1.2, nl_elasticity=1.2, rm_lt8_target=55, rm_tail_target=(0.062, 14),
                     imb_noise=4.2, imb_k=7.5, id_noise=2.2, sys_premium_mean=2.6)
    elif name == "severe_shock":
        vals = base * rng.uniform(1.55, 1.90) * noise
        reg = Regime(name=name, shape_stretch=1.38, nl_elasticity=1.35, rm_lt8_target=60, rm_tail_target=(0.062, 18),
                     imb_noise=5.5, imb_k=9.0, id_noise=3.2, sys_premium_mean=3.75)
    else:  # realised_like
        h1 = np.array(facts.TOKYO_MONTHLY_FY2026_H1) * rng.uniform(0.97, 1.03, 6)
        h2 = base[6:] * rng.uniform(1.45, 1.85) * noise[6:]
        vals = np.concatenate([h1, h2])
        reg = Regime(name=name, shape_stretch=1.38, nl_elasticity=1.35, rm_lt8_target=60, rm_tail_target=(0.062, 18),
                     imb_noise=5.5, imb_k=9.0, id_noise=3.2, sys_premium_mean=3.75)
    targets = {(2026, m): float(v) for m, v in zip(MONTHS_FY, vals)}
    events, tags = [], []
    if rng.random() < spec["p_cold"]:
        start = date(2027, 1, int(rng.integers(5, 16)))
        peak_daily = float(rng.uniform(110.0, 170.0))                  # Jan-2021 Tokyo daily mean peak 167.0
        events.append(Event("cold_snap_lng", start, int(rng.integers(14, 22)), temp_delta=-4.5,
                            cap_loss_gw=float(rng.uniform(2.0, 3.0)), level_mult_peak=peak_daily / targets[(2026, 1)]))
        tags.append("cold_snap_lng")
    if rng.random() < spec["p_heat"]:
        start = date(2026, 7, 15) + timedelta(days=int(rng.integers(0, 36)))
        peak_daily = float(rng.uniform(55.0, 90.0))                    # 2022 heat: Tokyo daily means 69-86
        events.append(Event("heat_dome", start, int(rng.integers(8, 13)), temp_delta=3.2,
                            cap_loss_gw=float(rng.uniform(1.0, 2.0)), level_mult_peak=peak_daily / targets[(2026, 8)]))
        tags.append("heat_dome")
    return replace(reg, events=events), targets, name, tags


def generate_bank(bank: str, n: int, seed: int) -> dict:
    """Simulate n FY2026 paths. Returns stacked arrays [n, 365, 48] plus per-scenario metadata."""
    days = fy_days(2026)
    keys = ("tokyo", "imbalance", "rm", "rm_gc", "delta_gw", "working", "observance", "month", "anom_day", "id_mid",
            "event_mult", "demand", "pv")
    acc = {k: [] for k in keys}
    meta = []
    for s in range(n):
        rng = np.random.default_rng(seed + 7919 * s)
        reg, targets, name, tags = draw_regime(rng, bank)
        path = simulate(days, rng, reg, targets, {}, GROWTH, PV_CAP, FY26_FLOORS)
        for k in keys:
            acc[k].append(path[k])
        p = path["tokyo"]
        meta.append({"scenario": s, "bank": bank, "seed": seed + 7919 * s, "regime": name, "stress": tags,
                     "mean_price": float(p.mean()), "max_price": float(p.max()),
                     "h1_mean": float(p[:183].mean()), "h2_mean": float(p[183:].mean()),
                     "imb_max": float(path["imbalance"].max()), "rm_min": float(path["rm"].min()),
                     "slots_ge_100": int((p >= 100).sum())})
    out = {k: np.stack(v) for k, v in acc.items()}
    out["meta"] = meta
    out["dates"] = np.array([d.isoformat() for d in days])
    return out
