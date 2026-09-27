"""Deterministic synthetic data generator for the Retail Energy Desk concept demo.

Usage:  python data/generate.py            (writes data/out/*.csv and data/schema.json)

Everything is driven by data/simulation_parameters.yaml and a single seed. Tables are BigQuery-ready:
column types come from SCHEMA below (STRING, INT64, FLOAT64, BOOL), dates/timestamps are ISO strings,
and precomputed date / slot / hour / month columns replace date functions.

Deliberate anomalies (the agents must find these; tests assert they are present):
  A1  evening scarcity on 2026-08-19: wide-area reserve margin 3-4 % in slots 35-39, imbalance and spot spike
  A2  VPP-R-17 telemetry frozen from 09:30 (flat SOC, stale last_seen) while it carries a dKW commitment
  A3  Kanagawa Cold Chain (bandwidth tariff, +/-5 %) breaches its band repeatedly in August
  A4  one NFC certificate claimed by two data-center customers (plus one claim with no matching generation and
      one expired-vintage claim, so the audit has three distinct finding types)
  A5  prompt injection inside the Hokuso Cloud Campus bill (docs_corpus)
  A6  balance group short in slots 35-38 on the scenario day (heat pushed demand above the day-ahead plan)
"""
from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
PKG = os.path.join(HERE, "..", "retail_desk")
CORPUS = os.path.join(PKG, "corpus")
P = yaml.safe_load(open(os.path.join(HERE, "simulation_parameters.yaml")))
SEED = int(P["seed"])
SC = P["scenario"]
SCEN_DATE = SC["date"]
NOW = SC["now"]
NOW_SLOT = int(SC["now_slot"])
GC_MIN = int(SC["gate_closure_minutes"])
NOW_HOUR = int(NOW[11:13])  # hours before this one are complete and metered


# ----------------------------------------------------------------------------------------------- helpers
def rng(tag: str) -> np.random.Generator:
    """Independent, deterministic stream per table so editing one table never shifts another."""
    return np.random.default_rng([SEED, abs(hash_str(tag)) % (2**31)])


def hash_str(s: str) -> int:
    h = 2166136261
    for ch in s.encode():
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h


def drange(a: str, b: str) -> list[str]:
    d0, d1 = date.fromisoformat(a), date.fromisoformat(b)
    return [(d0 + timedelta(days=i)).isoformat() for i in range((d1 - d0).days + 1)]


def slot_start(d: str, slot: int) -> str:
    m = (slot - 1) * 30
    return f"{d}T{m // 60:02d}:{m % 60:02d}"


def slot_end(d: str, slot: int) -> str:
    dt = datetime.fromisoformat(slot_start(d, slot)) + timedelta(minutes=30)
    return dt.strftime("%Y-%m-%dT%H:%M")


def gate_closure(d: str, slot: int) -> str:
    dt = datetime.fromisoformat(slot_start(d, slot)) - timedelta(minutes=GC_MIN)
    return dt.strftime("%Y-%m-%dT%H:%M")


def gate_status(d: str, slot: int, now: str = NOW) -> str:
    if slot_end(d, slot) <= now:
        return "delivered"
    if slot_start(d, slot) <= now:
        return "in_delivery"
    if gate_closure(d, slot) <= now:
        return "closed"
    return "open"


def is_weekend(d: str) -> bool:
    return date.fromisoformat(d).weekday() >= 5


def slot_hour(slot: int) -> int:
    return (slot - 1) // 2


SLOTS = np.arange(1, 49)
HOUR_OF_SLOT = (SLOTS - 1) // 2
FRAC_HOUR = (SLOTS - 1) / 2.0 + 0.25  # mid-slot hour


def interp_hourly(profile24: list[float]) -> np.ndarray:
    """24 hourly values -> 48 half-hour values (linear, circular)."""
    x = np.arange(25)
    y = np.array(list(profile24) + [profile24[0]])
    return np.interp(FRAC_HOUR, x, y)


# ------------------------------------------------------------------------------------ temperature backbone
def tokyo_tmax(d: str) -> float:
    """Tokyo daily maximum temperature (degC), deterministic seasonal curve plus the August heatwave."""
    dd = date.fromisoformat(d)
    doy = dd.timetuple().tm_yday
    base = 30.8 + 4.2 * math.sin((doy - 135) / 365.0 * 2 * math.pi) - 0.6
    heatwave = {"2026-08-15": 35.0, "2026-08-16": 35.6, "2026-08-17": 36.2, "2026-08-18": 36.9, "2026-08-19": 37.8,
                "2026-08-20": 36.6}  # SYNTHETIC heatwave daily maxima (degC)
    if d in heatwave:
        return heatwave[d]
    heat = {"2026-08-14": 1.2}
    wobble = 1.1 * math.sin(doy * 0.9) + 0.7 * math.sin(doy * 2.3)
    rainy = -2.5 if date(2026, 6, 8) <= dd <= date(2026, 7, 12) else 0.0
    return round(base + heat.get(d, 0.0) + wobble + rainy, 2)


def diurnal(tmax: float, spread: float = 8.0) -> np.ndarray:
    """48-slot temperature: min near 05:00, max near 14:00."""
    tmin = tmax - spread
    h = FRAC_HOUR
    shape = np.where(
        h < 5, 0.18 * (5 - h) / 5,
        np.where(h < 14, (h - 5) / 9.0, np.clip(1 - (h - 14) / 15.0, 0, 1) ** 1.3),
    )
    return tmin + (tmax - tmin) * np.clip(shape, 0, 1)


def build_temperature(dates: list[str]) -> dict[str, dict[str, np.ndarray]]:
    r = rng("temperature")
    heat_up = {int(k): float(v) for k, v in P["portfolio"]["scenario_heat_uplift_c"].items()}
    out = {}
    for d in dates:
        actual = diurnal(tokyo_tmax(d)) + r.normal(0, 0.25, 48)
        da = actual + r.normal(0, 0.55, 48)
        latest = actual.copy()
        if d == SCEN_DATE:
            # Latest view: peak ~37.8 C at 14:00 and a slow evening decline (no relief overnight).
            tmax = tokyo_tmax(d)
            base = diurnal(tmax)
            latest = np.where(FRAC_HOUR <= 14, base, tmax - 0.42 * (FRAC_HOUR - 14))
            # The day-ahead forecast (issued 2026-08-18) expected evening thunderstorms and a sea breeze that never
            # arrived, so it under-called late-afternoon and evening temperatures by the uplift below.
            uplift = np.zeros(48)
            for s in range(17, 49):
                if s in heat_up:
                    uplift[s - 1] = heat_up[s]
                elif s < min(heat_up):
                    uplift[s - 1] = 0.3 + (s - 17) * (heat_up[min(heat_up)] - 0.3) / (min(heat_up) - 17)
                else:
                    uplift[s - 1] = max(0.8, heat_up[max(heat_up)] - 0.25 * (s - max(heat_up)))
            da = latest - uplift
            actual = latest + r.normal(0, 0.2, 48)
        out[d] = {"actual": actual, "da": da, "latest": latest}
    return out


# ----------------------------------------------------------------------------------------------- market


def scarcity_price(rm: float) -> float:
    pts = sorted(P["imbalance"]["scarcity_curve"], key=lambda p: p[0])  # ascending margin
    lo_m, hi_price = pts[0]
    hi_m, lo_price = pts[-1]
    if rm >= hi_m:
        return 0.0
    if rm <= lo_m:
        return float(P["imbalance"]["cap_jpy_kwh"])
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return float(np.interp(rm, xs, ys))


def build_spot(temps) -> pd.DataFrame:
    r = rng("spot")
    sp = P["spot"]
    shape = interp_hourly(sp["hourly_shape"])
    shape = shape / shape.mean()
    rows = []
    day_eps = 0.0
    for d in drange(P["calendar"]["spot_start"], P["calendar"]["spot_end"]):
        m = int(d[5:7])
        tmax = tokyo_tmax(d)
        heat = 1 + sp["heat_sensitivity_per_c"] * max(0.0, tmax - 32.0)
        wk = sp["weekend_factor"] if is_weekend(d) else 1.0
        evening_heat = 1 + 0.04 * max(0.0, tmax - 34.0) * (shape > 1.1)
        day_eps = 0.55 * day_eps + r.normal(0, sp["daily_log_sd"])
        tokyo = (sp["tokyo_monthly_mean"][m] / 1.02) * shape * heat * wk * evening_heat * np.exp(day_eps + r.normal(0, sp["slot_noise_sd"], 48))
        if d == SCEN_DATE:
            for s, v in sp["scenario_evening_tokyo"].items():
                tokyo[int(s) - 1] = float(v) * (1 + r.normal(0, 0.01))
        split = sp["system_ratio"][m] * np.where(shape > 1.1, 1 - 0.03 * max(0.0, tmax - 34.0), 1.0)
        system = tokyo * split * np.exp(r.normal(0, 0.03, 48))
        vol = 15500 * (0.8 + 0.4 * shape / shape.max()) * np.exp(r.normal(0, 0.05, 48))
        for s in SLOTS:
            rows.append({
                "date": d, "slot": int(s), "hour": slot_hour(int(s)), "month": d[:7],
                "start_time": slot_start(d, int(s)),
                "tokyo_price_jpy_kwh": round(float(np.clip(tokyo[s - 1], sp["price_floor"], sp["price_cap"])), 2),
                "system_price_jpy_kwh": round(float(np.clip(system[s - 1], sp["price_floor"], sp["price_cap"])), 2),
                "system_volume_mwh": round(float(vol[s - 1]), 1),
            })
    df = pd.DataFrame(rows)
    fixed = (df.date == SCEN_DATE) & df.slot.isin([int(k) for k in sp["scenario_evening_tokyo"]])
    for m, target in sp["tokyo_monthly_mean"].items():
        mm = df.month == f"2026-{int(m):02d}"
        if not mm.any():
            continue
        free = mm & ~fixed
        need = target * mm.sum() - df.loc[mm & fixed, "tokyo_price_jpy_kwh"].sum()
        k = need / df.loc[free, "tokyo_price_jpy_kwh"].sum()
        df.loc[free, "tokyo_price_jpy_kwh"] = (df.loc[free, "tokyo_price_jpy_kwh"] * k).round(2)
        df.loc[free, "system_price_jpy_kwh"] = (df.loc[free, "system_price_jpy_kwh"] * k).round(2)
    return df


def build_imbalance(spot: pd.DataFrame) -> pd.DataFrame:
    r = rng("imbalance")
    ip = P["imbalance"]
    scen_rm = {int(k): float(v) for k, v in ip["scenario_reserve_margin"].items()}
    band = float(ip["forecast_band_pp"])
    rows = []
    last = SCEN_DATE
    for d, g in spot[spot.date <= last].groupby("date", sort=True):
        tmax = tokyo_tmax(d)
        base = r.uniform(14, 21)
        prices = g.tokyo_price_jpy_kwh.to_numpy()
        for s in SLOTS:
            evening = max(0.0, 1 - abs(FRAC_HOUR[s - 1] - 18.0) / 3.0)
            midday = max(0.0, 1 - abs(FRAC_HOUR[s - 1] - 12.5) / 4.0)
            rm = base - 5.5 * evening + 2.0 * midday - 0.8 * max(0.0, tmax - 33.0) * (0.4 + evening) + r.normal(0, 0.6)
            rm = float(max(rm, 6.2))
            if d == SCEN_DATE:
                rm = scen_rm.get(int(s), max(rm, 10.2))
            rm = round(rm, 2)  # price from the stored (rounded) margin so the table is exactly self-consistent
            spot_p = float(prices[s - 1])
            forecast = d == SCEN_DATE and s >= NOW_SLOT
            if forecast:
                p50 = max(spot_p * 1.07, scarcity_price(rm))
                p10 = max(spot_p * 0.95, scarcity_price(rm + band))
                p90 = max(spot_p * 1.25, scarcity_price(rm - band))
            else:
                p50 = max(spot_p * r.uniform(ip["normal_ratio_low"], ip["normal_ratio_high"]), scarcity_price(rm))
                p10 = p90 = p50
            rows.append({
                "date": d, "slot": int(s), "hour": slot_hour(int(s)), "month": d[:7], "start_time": slot_start(d, int(s)),
                "reserve_margin_pct": round(rm, 2),
                "imbalance_price_jpy_kwh": round(p50, 2),
                "imbalance_p10_jpy_kwh": round(p10, 2),
                "imbalance_p90_jpy_kwh": round(p90, 2),
                "scarcity_flag": bool(rm < max(p[0] for p in ip["scarcity_curve"])),
                "is_forecast": bool(forecast),
            })
    return pd.DataFrame(rows)


def build_intraday(spot: pd.DataFrame, imb: pd.DataFrame) -> pd.DataFrame:
    r = rng("intraday")
    ipd = P["intraday"]
    book = {int(k): v for k, v in ipd["scenario_book"].items()}
    sub = spot[(spot.date >= P["calendar"]["intraday_start"]) & (spot.date <= SCEN_DATE)]
    rows = []
    for rec in sub.itertuples():
        d, s = rec.date, rec.slot
        st = gate_status(d, s)
        vwap = max(0.01, rec.tokyo_price_jpy_kwh + r.normal(ipd["premium_mean"] * 0.3, ipd["premium_sd"] * 0.5))
        spread = r.uniform(*ipd["spread_normal"])
        bid, ask = vwap - spread / 2, vwap + spread / 2
        depth = r.uniform(*ipd["depth_normal_mwh"])
        ask2, depth2 = ask * r.uniform(1.04, 1.10), r.uniform(10, 40)
        traded = r.uniform(*ipd["traded_mwh"])
        snap = gate_closure(d, s)
        if d == SCEN_DATE and st == "open":
            snap = NOW
            traded = traded * 0.6
            if s in book:
                b = book[s]
                bid, ask, depth, ask2, depth2 = b["bid"], b["ask"], b["depth"], b["ask2"], b["depth2"]
                vwap = (bid + ask) / 2
                traded = r.uniform(60, 140)
            else:
                ask = max(ask, rec.tokyo_price_jpy_kwh * 1.08)
                bid = ask - spread
                ask2 = ask * r.uniform(1.04, 1.10)
        rows.append({
            "date": d, "slot": int(s), "hour": slot_hour(int(s)), "month": d[:7], "start_time": slot_start(d, int(s)),
            "gate_closure_time": gate_closure(d, s), "snapshot_time": snap,
            "vwap_jpy_kwh": round(float(vwap), 2), "best_bid_jpy_kwh": round(float(bid), 2),
            "best_ask_jpy_kwh": round(float(ask), 2), "ask_depth_mwh": round(float(depth), 1),
            "ask_level2_jpy_kwh": round(float(ask2), 2), "ask_level2_depth_mwh": round(float(depth2), 1),
            "traded_volume_mwh": round(float(traded), 1),
        })
    return pd.DataFrame(rows)


CELLS = [
    ("W01", "Tokyo Otemachi", 35.69, 139.76, 0.0), ("W02", "Tokyo Hachioji", 35.66, 139.32, 0.6),
    ("W03", "Kanagawa Yokohama", 35.44, 139.64, -0.9), ("W04", "Kanagawa Sagamihara", 35.57, 139.37, 0.4),
    ("W05", "Saitama Kumagaya", 36.15, 139.39, 1.6), ("W06", "Saitama Saitama", 35.86, 139.65, 0.8),
    ("W07", "Chiba Inzai", 35.83, 140.15, -0.2), ("W08", "Chiba Chiba", 35.61, 140.12, -0.8),
    ("W09", "Ibaraki Tsukuba", 36.08, 140.08, -0.1), ("W10", "Gunma Maebashi", 36.39, 139.06, 1.2),
]


def build_weather(temps) -> pd.DataFrame:
    r = rng("weather")
    rows = []
    for d in drange(P["calendar"]["intraday_start"], P["calendar"]["spot_end"]):
        issue = f"{(date.fromisoformat(d) - timedelta(days=1)).isoformat()}T18:00"
        if d >= SCEN_DATE:
            issue = f"{SCEN_DATE}T12:00"
        cloud = float(np.clip(r.normal(0.18, 0.12), 0, 0.7))
        view = temps[d]["latest"] if d >= SCEN_DATE else temps[d]["da"]
        for cid, name, lat, lon, off in CELLS:
            tcell = view + off
            for h in range(24):
                t = float(tcell[2 * h])
                sun = max(0.0, math.sin(math.pi * (h + 0.5 - 5.0) / 13.8)) if 5 <= h + 0.5 <= 18.8 else 0.0
                ghi = 930 * sun ** 1.25 * (1 - cloud) * (1 + r.normal(0, 0.03))
                spread_t = 0.8 + 0.25 * (d > SCEN_DATE)
                rows.append({
                    "cell_id": cid, "cell_name": name, "lat": lat, "lon": lon, "issue_time": issue,
                    "date": d, "hour": h, "month": d[:7], "valid_time": f"{d}T{h:02d}:00",
                    "temp_p10_c": round(t - spread_t, 1), "temp_p50_c": round(t, 1), "temp_p90_c": round(t + spread_t, 1),
                    "ghi_p10_wm2": round(max(0.0, ghi * 0.78), 0), "ghi_p50_wm2": round(max(0.0, ghi), 0),
                    "ghi_p90_wm2": round(max(0.0, ghi * 1.12), 0),
                })
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------------- customers
PLACES = ["Adachi", "Akishima", "Ageo", "Asaka", "Chofu", "Ebina", "Fuchu", "Fujisawa", "Funabashi", "Hadano",
          "Hino", "Hiratsuka", "Ichikawa", "Ichihara", "Iruma", "Kamagaya", "Kasukabe", "Kawagoe", "Kawaguchi",
          "Kisarazu", "Koshigaya", "Kodaira", "Machida", "Matsudo", "Misato", "Mobara", "Nagareyama", "Narita",
          "Niiza", "Noda", "Odawara", "Sayama", "Soka", "Tama", "Toda", "Tsurumi", "Urayasu", "Warabi", "Yamato",
          "Yokosuka", "Zama", "Chigasaki", "Kashima", "Koga", "Ushiku", "Toride", "Kunitachi", "Koganei", "Inagi",
          "Shinagawa", "Koto", "Sumida", "Hamura", "Fussa", "Kiyose", "Higashiyamato", "Shiki", "Wako", "Hanno",
          "Sakura", "Yotsukaido", "Tomisato", "Ami", "Tsuchiura", "Kasama", "Oyama", "Sano", "Ashikaga", "Kiryu"]
SEG_WORDS = {
    "auto_parts": ["Auto Parts", "Precision Castings", "Stamping Works", "Drivetrain Components", "Harness Works", "Die Cast"],
    "cold_storage": ["Cold Chain", "Frozen Logistics", "Cold Storage", "Reefer Center"],
    "office": ["Tower", "Business Center", "Office Park", "Plaza", "Square"],
    "retail_chain": ["Supermarkets", "Home Centers", "Drugstores", "Department Store", "Food Halls"],
    "hospital": ["General Hospital", "Medical Center", "Memorial Hospital", "Rehabilitation Hospital"],
    "university": ["University", "Institute of Technology", "College of Science"],
    "logistics": ["Logistics Center", "Distribution Hub", "Fulfillment Center", "Freight Terminal"],
    "hotel": ["Hotel", "Grand Hotel", "Bay Hotel", "Garden Hotel"],
}
DC_NAMES = ["Otemachi Edge Center", "Mitaka Compute Park", "Shiroi Data Campus", "Kawasaki Bay Cloud Hall",
            "Kashiwa Cloud Hall", "Sagami Data Works", "Tokorozawa Compute Center", "Narashino Data Park",
            "Tachikawa Hyperscale Hall", "Yachiyo Cloud Campus", "Atsugi Data Center", "Nerima Edge Hall"]
FAB_NAMES = ["Oyama Wafer Works", "Tsukuba Micro Devices", "Kumagaya Silicon Fab", "Honjo Power Chips",
             "Ome Precision Semiconductor", "Isesaki Crystal Fab", "Mito Sensor Fab", "Kazo Photonics Fab"]
PREFS = ["Tokyo", "Kanagawa", "Saitama", "Chiba", "Ibaraki", "Tochigi", "Gunma"]
SEGMENT_SHAPES = {  # 24 hourly fractions of contracted kW (weekday, weekend)
    "data_center": ([0.80] * 12 + [0.81, 0.82, 0.82, 0.82, 0.81] + [0.80] * 7, [0.80] * 24),
    "semiconductor_fab": ([0.84] * 24, [0.83] * 24),
    "auto_parts": ([0.26] * 7 + [0.55] + [0.76] * 12 + [0.55, 0.35, 0.28, 0.26], [0.22] * 24),
    "cold_storage": ([0.55] * 7 + [0.62] + [0.70] * 11 + [0.64, 0.6, 0.58, 0.56, 0.55], [0.55] * 7 + [0.62] * 17),
    "office": ([0.20] * 7 + [0.40, 0.66] + [0.76] * 9 + [0.66, 0.50, 0.36, 0.26, 0.22, 0.20], [0.20] * 24),
    "retail_chain": ([0.26] * 8 + [0.48] + [0.80] * 12 + [0.56, 0.34, 0.28], [0.26] * 8 + [0.50] + [0.82] * 12 + [0.56, 0.34, 0.28]),
    "hospital": ([0.52] * 7 + [0.66] + [0.80] * 10 + [0.70, 0.62, 0.58, 0.55, 0.53, 0.52], [0.52] * 7 + [0.62] * 12 + [0.56] * 5),
    "university": ([0.25] * 8 + [0.42] + [0.52] * 9 + [0.42, 0.32, 0.28, 0.26, 0.25, 0.25], [0.24] * 24),
    "logistics": ([0.30] * 6 + [0.62] + [0.72] * 15 + [0.50, 0.34], [0.28] * 6 + [0.52] * 16 + [0.36, 0.30]),
    "hotel": ([0.50] * 6 + [0.66, 0.72, 0.68] + [0.60] * 9 + [0.74] * 5 + [0.58], [0.52] * 6 + [0.68, 0.74, 0.70] + [0.62] * 9 + [0.76] * 5 + [0.60]),
}


def build_customers() -> pd.DataFrame:
    r = rng("customers")
    pf = P["portfolio"]
    rows = []
    used = set()
    cid = 0
    for seg, (count, kw_lo, kw_hi, lf, sens) in pf["segments"].items():
        for i in range(count):
            cid += 1
            if seg == "data_center":
                name = DC_NAMES[i]
            elif seg == "semiconductor_fab":
                name = FAB_NAMES[i]
            elif seg == "cold_storage" and i == 0:
                name = "Kanagawa Cold Chain"
            else:
                while True:
                    name = f"{r.choice(PLACES)} {r.choice(SEG_WORDS[seg])}"
                    if name not in used:
                        break
            used.add(name)
            kw = float(round(r.uniform(kw_lo, kw_hi), -2))
            if seg == "semiconductor_fab":
                tariff = "fixed" if i % 3 else "bandwidth"
            elif seg == "data_center":
                tariff = "market_linked" if i % 2 else "fixed"
            elif seg == "cold_storage":
                tariff = "bandwidth" if (i == 0 or r.random() < 0.55) else "fixed"
            else:
                tariff = str(r.choice(list(pf["tariff_mix"].keys()), p=list(pf["tariff_mix"].values())))
            band = None
            if tariff == "bandwidth":
                band = 5.0 if (i == 0 and seg == "cold_storage") or r.random() < 0.6 else 10.0
            fixed_price = round(float(r.uniform(*pf["fixed_energy_price_jpy_kwh"])), 2) if tariff in ("fixed", "bandwidth") else None
            adder = round(float(r.uniform(*pf["market_adder_jpy_kwh"])), 2) if tariff == "market_linked" else None
            margin = round(float(r.uniform(*pf["margin_jpy_kwh"])), 2)
            if name == "Kanagawa Cold Chain":
                kw, margin, fixed_price = 4200.0, 1.05, 23.40
            dr = bool(r.random() < {"cold_storage": 0.55, "auto_parts": 0.45, "logistics": 0.40, "retail_chain": 0.35}.get(seg, 0.15))
            if seg == "hospital":
                dr = False
            cfe = seg == "data_center" and i in (0, 2, 4, 6, 7, 9) or seg == "semiconductor_fab" and i in (1, 4)
            rows.append({
                "customer_id": f"C-{cid:04d}", "name": name, "segment": seg,
                "voltage": "extra_high" if kw >= 2000 else "high", "prefecture": str(r.choice(PREFS)),
                "tariff_type": tariff, "deviation_band_pct": band, "fixed_energy_price_jpy_kwh": fixed_price,
                "market_adder_jpy_kwh": adder, "contracted_kw": kw,
                "annual_mwh": round(kw * lf * 8.76, 0), "margin_jpy_kwh": margin, "dr_enrolled": dr,
                "essential_facility": seg == "hospital", "cfe_contract": bool(cfe),
                "cfe_product": ("hourly_24x7" if cfe and i in (2, 4, 7) else "annual_volumetric") if cfe else None,
                "contract_end": f"{2027 + int(r.integers(0, 4))}-03-31",
            })
    return pd.DataFrame(rows)


def load_matrix(customers: pd.DataFrame, dates: list[str], temps, which: str, r: np.random.Generator) -> np.ndarray:
    """Expected load (kWh per 30 min), shape (customers, days, 48)."""
    pf = P["portfolio"]["segments"]
    out = np.zeros((len(customers), len(dates), 48))
    shapes = {seg: (interp_hourly(w), interp_hourly(we)) for seg, (w, we) in SEGMENT_SHAPES.items()}
    for j, d in enumerate(dates):
        t = temps[d][which]
        wkend = is_weekend(d)
        for i, c in enumerate(customers.itertuples()):
            sens = pf[c.segment][4]
            shp = shapes[c.segment][1 if wkend else 0]
            temp_f = 1 + sens * np.clip(t - 26.0, 0, None)
            out[i, j, :] = c.contracted_kw * 0.5 * shp * temp_f
    return out


def build_customer_load(customers: pd.DataFrame, temps) -> tuple[pd.DataFrame, np.ndarray, list[str]]:
    r = rng("load")
    dates = drange(P["calendar"]["load_start"], SCEN_DATE)
    act = load_matrix(customers, dates, temps, "actual", r)
    da = load_matrix(customers, dates, temps, "da", r)
    lat = load_matrix(customers, dates, temps, "latest", r)
    n, nd, _ = act.shape
    unit_bias = r.normal(0, 0.012, (n, 1, 1))
    act = act * (1 + unit_bias + r.normal(0, 0.022, act.shape))
    da = da * (1 + unit_bias * 0.6 + r.normal(0, 0.008, da.shape))
    lat = lat * (1 + unit_bias * 0.8 + r.normal(0, 0.006, lat.shape))
    # Bandwidth customers nominate D-1 with good site knowledge: past days sit close to metered load; on the scenario
    # day the nomination follows the day-ahead view, so the heat shows up as deviations.
    nominated = act * (1 + r.normal(0, 0.017, act.shape))
    scen_j = dates.index(SCEN_DATE)
    nominated[:, scen_j, :] = da[:, scen_j, :] * (1 + r.normal(0, 0.006, (act.shape[0], 48)))
    kcc = int(np.where(customers.name.to_numpy() == "Kanagawa Cold Chain")[0][0])
    # A3: compressor load in the heat runs well above the customer's own nomination in the afternoon/evening.
    for j, d in enumerate(dates):
        heat = max(0.0, tokyo_tmax(d) - 30.0)
        aft = np.clip(1 - np.abs(FRAC_HOUR - 16.0) / 6.0, 0, 1)
        bias = 0.022 * heat * aft + 0.015
        act[kcc, j, :] = nominated[kcc, j, :] * (1 + bias + r.normal(0, 0.028, 48))
    scen = dates.index(SCEN_DATE)
    rows_c = []
    bandwidth = customers.tariff_type.to_numpy() == "bandwidth"
    for i, c in enumerate(customers.itertuples()):
        for j, d in enumerate(dates):
            for s in SLOTS:
                delivered = not (j == scen and s >= NOW_SLOT)
                rows_c.append((
                    c.customer_id, d, int(s), d[:7],
                    round(float(da[i, j, s - 1]), 1),
                    round(float(lat[i, j, s - 1] if j == scen else da[i, j, s - 1] * 0.5 + act[i, j, s - 1] * 0.5), 1),
                    round(float(act[i, j, s - 1]), 1) if delivered else None,
                    round(float(nominated[i, j, s - 1]), 1) if bandwidth[i] else None,
                    delivered,
                ))
    df = pd.DataFrame(rows_c, columns=["customer_id", "date", "slot", "month", "forecast_da_kwh", "forecast_latest_kwh",
                                       "actual_kwh", "nominated_kwh", "is_actual"])
    return df, act, dates


def build_balance_position(load: pd.DataFrame) -> pd.DataFrame:
    r = rng("balance")
    pf = P["portfolio"]
    pre = {int(k): float(v) for k, v in pf["intraday_prebought_share"].items()}
    agg = load.groupby(["date", "slot"], sort=True).agg(
        da=("forecast_da_kwh", "sum"), latest=("forecast_latest_kwh", "sum"), actual=("actual_kwh", "sum"),
        n_actual=("is_actual", "sum")).reset_index()
    rows = []
    for rec in agg.itertuples():
        d, s = rec.date, int(rec.slot)
        da, latest = rec.da / 1000.0, rec.latest / 1000.0
        delivered = rec.n_actual > 0
        actual = rec.actual / 1000.0 if delivered else None
        bilateral = round(da * pf["bilateral_share"], 1)
        spot_mwh = round(da - bilateral, 1)
        if d == SCEN_DATE:
            ref = actual if (delivered and s < NOW_SLOT - 6) else latest
            share = pre.get(s, 0.85 if s < NOW_SLOT else 1.0)
            # Slots already covered this morning sit flat to slightly long (within the 0.5 MWh tolerance).
            intraday = max(0.0, (ref - da) * share) + (r.uniform(0.05, 0.45) if share >= 1.0 else 0.0)
        else:
            intraday = max(0.0, (actual - da) * r.uniform(0.55, 0.9))
        intraday = round(max(0.0, intraday), 1)
        total = round(bilateral + spot_mwh + intraday, 1)
        against = actual if delivered else latest
        rows.append({
            "date": d, "slot": s, "hour": slot_hour(s), "month": d[:7], "start_time": slot_start(d, s),
            "gate_closure_time": gate_closure(d, s), "gate_status": gate_status(d, s),
            "demand_forecast_da_mwh": round(da, 1), "demand_forecast_latest_mwh": round(latest, 1),
            "demand_actual_mwh": round(actual, 1) if delivered else None,
            "procured_bilateral_mwh": bilateral, "procured_spot_mwh": spot_mwh, "procured_intraday_mwh": intraday,
            "vpp_dispatched_mwh": 0.0, "total_procured_mwh": total,
            "open_position_mwh": round(total - against, 1),
        })
    return pd.DataFrame(rows)


def build_forward_and_hedges(customers: pd.DataFrame, temps) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    r = rng("forward")
    dates = drange("2026-08-20", P["calendar"]["forward_end"])
    fwd = []
    for d in dates:
        m = int(d[5:7])
        fp = P["portfolio"]["forward"]
        base = {8: fp["aug_base"], 9: fp["sep_base"]}[m] * (1 + 0.02 * max(0, tokyo_tmax(d) - 33)) * (0.9 if is_weekend(d) else 1.0)
        fwd.append({"date": d, "month": d[:7], "baseload_jpy_kwh": round(base * r.uniform(0.98, 1.02), 2),
                    "peak_jpy_kwh": round(base * fp["peak_ratio"] * r.uniform(0.98, 1.03), 2),
                    "source_note": "synthetic forward curve (futures-style settlement marks)"})
    fwd = pd.DataFrame(fwd)
    pf = P["portfolio"]["segments"]
    fc = []
    for c in customers.itertuples():
        lf = pf[c.segment][3]
        for d in drange("2026-08-20", "2026-08-31"):
            temp_f = 1 + pf[c.segment][4] * max(0.0, tokyo_tmax(d) - 28.0) * 0.6
            wk = 0.62 if is_weekend(d) and c.segment in ("office", "auto_parts", "university") else 1.0
            fc.append({"customer_id": c.customer_id, "date": d, "month": d[:7],
                       "forecast_mwh": round(c.contracted_kw * lf * 24 / 1000.0 * temp_f * wk * r.uniform(0.97, 1.03), 2)})
    fc = pd.DataFrame(fc)
    exposed = fc.merge(customers[["customer_id", "tariff_type"]], on="customer_id")
    exposed = exposed[exposed.tariff_type.isin(["fixed", "bandwidth"])]
    avg_mw = exposed.groupby("date").forecast_mwh.sum().mean() / 24.0
    target = avg_mw * P["portfolio"]["hedge_ratio_august"]
    hp = P["portfolio"]["hedge_prices"]
    hedges = [
        {"hedge_id": "HB-2608-01", "product": "baseload", "instrument": "bilateral", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "mw": round(target * 0.55, 0), "price_jpy_kwh": hp["bilateral"]},
        {"hedge_id": "HB-2608-02", "product": "baseload", "instrument": "futures", "start_date": "2026-08-01",
         "end_date": "2026-08-31", "mw": round(target * 0.30, 0), "price_jpy_kwh": hp["futures"]},
        {"hedge_id": "HB-2608-03", "product": "baseload", "instrument": "futures", "start_date": "2026-08-17",
         "end_date": "2026-08-23", "mw": round(target * 0.15, 0), "price_jpy_kwh": hp["heatwave_week"]},
        {"hedge_id": "HB-2609-01", "product": "baseload", "instrument": "bilateral", "start_date": "2026-09-01",
         "end_date": "2026-09-30", "mw": round(target * 0.8, 0), "price_jpy_kwh": hp["september"]},
    ]
    return fwd, fc, pd.DataFrame(hedges)


# ------------------------------------------------------------------------------------------------- VPP
def build_vpp() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    r = rng("vpp")
    vp = P["vpp"]
    prefix = {"residential_battery": "R", "heat_pump_water_heater": "H", "cni_bess": "C", "ev_depot": "E", "dr_load": "D"}
    per_dev = {"residential_battery": 4.9, "heat_pump_water_heater": 1.3, "cni_bess": 500.0, "ev_depot": 50.0, "dr_load": 400.0}
    clusters = []
    for cls, (count, kw_lo, kw_hi, hours, min_soc, c_lo, c_hi, resp) in vp["classes"].items():
        for i in range(1, count + 1):
            cid = f"VPP-{prefix[cls]}-{i:02d}"
            kw = float(round(r.uniform(kw_lo, kw_hi), -1))
            if cid == vp["frozen_cluster"]:
                kw = 1500.0
            clusters.append({
                "cluster_id": cid, "name": f"{cls.replace('_', ' ').title()} pool {PLACES[(i * 7 + len(cls)) % len(PLACES)]}",
                "asset_class": cls, "area": str(r.choice(PREFS[:4])),
                "device_count": int(max(1, round(kw / per_dev[cls]))), "capacity_kw": kw,
                "energy_kwh": float(round(kw * hours * r.uniform(0.95, 1.05), -1)),
                "min_soc_pct": float(min_soc), "max_soc_pct": 95.0 if min_soc else 0.0,
                "dispatch_cost_jpy_kwh": round(float(r.uniform(c_lo, c_hi)), 2), "response_time_s": int(resp),
                "telemetry_interval_s": 60 if cls in ("cni_bess", "ev_depot") else 300,
                "program": {"residential_battery": "residential storage program", "heat_pump_water_heater": "heat pump water heater program",
                            "cni_bess": "C&I battery partner program", "ev_depot": "fleet EV depot program", "dr_load": "C&I demand response program"}[cls],
            })
    cl = pd.DataFrame(clusters)
    # Telemetry for 2026-08-18 (full day) and 2026-08-19 up to the 15:40 snapshot (slot 32).
    rows = []
    frozen = vp["frozen_cluster"]
    for c in cl.itertuples():
        base_online = r.uniform(0.93, 0.99)
        soc_prev = None
        for d in drange(P["calendar"]["telemetry_start"], SCEN_DATE):
            last_slot = NOW_SLOT if d == SCEN_DATE else 48
            for s in range(1, last_slot + 1):
                ts = NOW if (d == SCEN_DATE and s == NOW_SLOT) else slot_end(d, s)
                h = FRAC_HOUR[s - 1]
                if c.asset_class == "residential_battery":
                    if h < 6:
                        soc = 55 - 3.3 * h
                    elif h < 8.5:
                        soc = 35
                    elif h < 14:
                        soc = 35 + (h - 8.5) / 5.5 * 56
                    elif h < 17:
                        soc = 91
                    else:
                        soc = 91 - (h - 17) / 6.0 * 40
                    soc += r.normal(0, 0.8)
                    online = base_online
                elif c.asset_class == "cni_bess":
                    soc = (62 + 12 * math.sin(h / 24 * 2 * math.pi)) if h < 11 else (86 if h < 17 else 86 - (h - 17) * 6)
                    soc += r.normal(0, 0.6)
                    online = 1.0
                elif c.asset_class == "ev_depot":
                    soc = 64 + 6 * math.cos((h - 3) / 24 * 2 * math.pi) + r.normal(0, 0.8)
                    online = 0.48 + 0.3 * (h < 7 or h > 19) + r.normal(0, 0.02)
                    if c.cluster_id == vp["degraded_cluster"] and d == SCEN_DATE and s > 22:
                        online = 0.21
                else:
                    soc = None
                    online = base_online
                online = float(np.clip(online, 0.05, 1.0))
                if soc is not None:
                    soc = float(np.clip(soc, c.min_soc_pct if c.min_soc_pct else 5, 95))
                if c.asset_class == "heat_pump_water_heater":
                    avail_kw = c.capacity_kw * online * (0.32 if 10 <= h < 16 else 0.22)
                    avail_kwh = avail_kw * 1.5
                elif c.asset_class == "dr_load":
                    avail_kw = c.capacity_kw * online * 0.9
                    avail_kwh = avail_kw * 2.0
                else:
                    avail_kw = c.capacity_kw * online
                    avail_kwh = max(0.0, (soc - c.min_soc_pct) / 100.0 * c.energy_kwh * online)
                last_seen = (datetime.fromisoformat(ts) - timedelta(seconds=int(r.integers(10, 200)))).strftime("%Y-%m-%dT%H:%M")
                rec = {"cluster_id": c.cluster_id, "date": d, "slot": s, "hour": slot_hour(s), "month": d[:7],
                       "timestamp": ts, "soc_pct": round(soc, 1) if soc is not None else None,
                       "available_kw": round(avail_kw, 1), "available_kwh": round(avail_kwh, 1),
                       "online_devices": int(round(c.device_count * online)), "last_seen": last_seen}
                if c.cluster_id == frozen and d == SCEN_DATE:
                    if s == vp["frozen_from_slot"] - 1:
                        rec["soc_pct"] = 78.0
                        rec["available_kw"] = round(c.capacity_kw * online, 1)
                        rec["available_kwh"] = round((78.0 - c.min_soc_pct) / 100 * c.energy_kwh * online, 1)
                        soc_prev = dict(rec)
                    elif s >= vp["frozen_from_slot"]:
                        # A2: gateway keeps republishing the last value; device heartbeat stopped at 09:34.
                        rec.update({k: soc_prev[k] for k in ("soc_pct", "available_kw", "available_kwh", "online_devices")})
                        rec["last_seen"] = f"{SCEN_DATE}T09:34"
                rows.append(rec)
    tel = pd.DataFrame(rows)
    prod = P["ancillary"]["products"]
    comm = [
        ("ANC-0819-01", 35, 40, "tertiary_1", "VPP-C-01", 2500), ("ANC-0819-02", 35, 40, "secondary_2", "VPP-C-03", 2000),
        ("ANC-0819-03", 35, 40, "tertiary_1", "VPP-C-06", 3000), ("ANC-0819-04", 33, 40, "tertiary_2", "VPP-C-08", 2500),
        ("ANC-0819-05", 35, 40, "tertiary_2", "VPP-R-03", 800), ("ANC-0819-06", 35, 40, "tertiary_2", "VPP-R-04", 800),
        ("ANC-0819-07", 35, 40, "tertiary_2", "VPP-R-05", 800), ("ANC-0819-08", 35, 40, "tertiary_2", "VPP-R-06", 800),
        ("ANC-0819-09", 35, 40, "tertiary_2", "VPP-R-17", 1200), ("ANC-0819-10", 35, 40, "tertiary_2", "VPP-D-02", 2000),
    ]
    prices = P["ancillary"]["price_jpy_per_dkw_30min"]
    anc = pd.DataFrame([{
        "commitment_id": a, "date": SCEN_DATE, "from_slot": f, "to_slot": t, "product": p, "cluster_id": c,
        "committed_kw": float(kw), "response_minutes": int(prod[p][0]), "duration_hours": float(prod[p][1]),
        "reserve_energy_kwh": float(kw) * float(prod[p][1]) * float(P["ancillary"]["activation_buffer"]),
        "price_jpy_per_dkw_30min": round(float(r.uniform(*prices[p])), 2), "tso_area": "Tokyo", "status": "awarded",
        "awarded_at": "2026-08-18T15:00",
    } for a, f, t, p, c, kw in comm])
    return cl, tel, anc


# -------------------------------------------------------------------------------------- clean supply, CFE
RESOURCES = [
    # id, type, region, contracted_mw (retail portfolio), available_mw for new PPAs, nfc certificate type
    ("CR-SOL-KANTO", "solar", "Kanto", 560.0, 150.0, "non_fit_renewable_tracked"),
    ("CR-SOL-TOHOKU", "solar", "Tohoku", 260.0, 90.0, "non_fit_renewable_tracked"),
    ("CR-WND-ON", "onshore_wind", "Tohoku", 180.0, 70.0, "non_fit_renewable_tracked"),
    ("CR-WND-OFF", "offshore_wind", "Kanto offshore", 120.0, 90.0, "non_fit_renewable_tracked"),
    ("CR-HYD-ROR", "hydro_run_of_river", "Chubu-Kanto mountains", 140.0, 30.0, "non_fit_renewable_tracked"),
    ("CR-HYD-RES", "hydro_reservoir", "Kanto mountains", 90.0, 25.0, "non_fit_renewable_tracked"),
    ("CR-NUC-G", "nuclear_generic", "contracted share (generic)", 300.0, 28.0, "non_fit_nonrenewable_tracked"),
    ("CR-BIO", "biomass", "Ibaraki coast", 60.0, 15.0, "non_fit_renewable_tracked"),
]


def cf_profile(rtype: str, dates: list[str], r: np.random.Generator) -> np.ndarray:
    """Hourly capacity factor, shape (len(dates)*24,)."""
    out = []
    ar = 0.0
    for d in dates:
        dd = date.fromisoformat(d)
        doy = dd.timetuple().tm_yday
        m = dd.month
        for h in range(24):
            if rtype == "solar":
                daylen = 12.2 + 2.3 * math.sin((doy - 80) / 365 * 2 * math.pi)
                sr = 12 - daylen / 2
                x = (h + 0.5 - sr) / daylen
                sun = math.sin(math.pi * x) ** 1.3 if 0 < x < 1 else 0.0
                if h == 0:
                    cloud = float(np.clip(r.normal(0.28 if m in (6, 7) else 0.2, 0.18), 0, 0.9))
                cf = 0.82 * sun * (1 - cloud)
            elif rtype in ("onshore_wind", "offshore_wind"):
                seas = 1 + 0.35 * math.cos((doy - 15) / 365 * 2 * math.pi)
                ar = 0.93 * ar + r.normal(0, 0.22)
                base = 0.22 if rtype == "onshore_wind" else 0.31
                cf = base * seas * math.exp(ar) * (1 + 0.08 * math.sin((h - 3) / 24 * 2 * math.pi))
            elif rtype == "hydro_run_of_river":
                cf = 0.48 + 0.22 * math.exp(-((doy - 135) / 35) ** 2) - 0.08 * (m in (1, 2)) + r.normal(0, 0.015)
            elif rtype == "hydro_reservoir":
                cf = 0.18 + 0.55 * (h in range(8, 11) or h in range(17, 22)) + r.normal(0, 0.02)
            elif rtype == "nuclear_generic":
                outage = (m == 10 and dd.day >= 5) or (m == 11 and dd.day <= 18)
                cf = 0.38 if outage else 0.92 + r.normal(0, 0.005)  # staggered refuelling: one unit of the share offline
            else:  # biomass
                cf = 0.0 if (m == 5 and dd.day <= 12) else 0.78 + r.normal(0, 0.02)
            out.append(float(np.clip(cf, 0, 1)))
    return np.array(out)


def build_clean_supply() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    res = pd.DataFrame([{
        "resource_id": a, "resource_type": b, "region": c, "contracted_mw": m, "available_mw_new_ppa": av,
        "nfc_certificate_type": n, "cost_jpy_kwh": float(P["ppa"]["resource_cost_jpy_kwh"][b]),
    } for a, b, c, m, av, n in RESOURCES])
    rows = []
    cf_cache = {}
    for period, dates in (("actual", drange("2026-07-01", SCEN_DATE)), ("p50_projection", drange("2027-01-01", "2027-12-31"))):
        for rid, rtype, _, mw, _, _ in RESOURCES:
            cf = cf_profile(rtype, dates, rng(f"cf-{rid}-{period}"))
            cf_cache[(rid, period)] = cf
            for k, v in enumerate(cf):
                d = dates[k // 24]
                h = k % 24
                if period == "actual" and d == SCEN_DATE and h >= NOW_HOUR:
                    continue  # only complete metered hours before 'now'
                rows.append((rid, period, d, h, d[:7], round(v, 4), round(v * mw, 2)))
    cs = pd.DataFrame(rows, columns=["resource_id", "period", "date", "hour", "month", "capacity_factor", "generation_mwh"])
    return res, cs, cf_cache


def build_grid_mix() -> pd.DataFrame:
    r = rng("gridmix")
    rows = []
    for d in drange("2026-07-01", SCEN_DATE):
        cloud = float(np.clip(r.normal(0.22, 0.14), 0, 0.8))
        for h in range(24):
            if d == SCEN_DATE and h >= NOW_HOUR:
                continue
            sun = max(0.0, math.sin(math.pi * (h + 0.5 - 5.0) / 13.8)) if 5 <= h + 0.5 <= 18.8 else 0.0
            cfe = 0.10 + 0.30 * sun * (1 - cloud) + r.normal(0, 0.008)
            rows.append({"date": d, "hour": h, "month": d[:7], "grid_cfe_share_pct": round(100 * cfe, 2),
                         "carbon_intensity_g_kwh": round((1 - cfe) * 640 + r.normal(0, 6), 1)})
    return pd.DataFrame(rows)


# Contracted clean portfolios (MW shares of resources) for existing CFE customers.
CFE_PORTFOLIOS = {
    "hourly_24x7": {"CR-NUC-G": 0.55, "CR-HYD-ROR": 0.16, "CR-HYD-RES": 0.08, "CR-WND-ON": 0.12, "CR-SOL-KANTO": 0.24},
    "annual_volumetric": {"CR-SOL-KANTO": 0.62, "CR-SOL-TOHOKU": 0.34, "CR-WND-ON": 0.18, "CR-HYD-ROR": 0.06},
}


def customer_hourly_load(c, dates: list[str], temps, r) -> np.ndarray:
    pf = P["portfolio"]["segments"]
    sens, shapes = pf[c.segment][4], SEGMENT_SHAPES[c.segment]
    out = []
    for d in dates:
        t = temps[d]["actual"]
        shp = interp_hourly(shapes[1] if is_weekend(d) else shapes[0])
        kwh = c.contracted_kw * 0.5 * shp * (1 + sens * np.clip(t - 26.0, 0, None))
        hourly = (kwh[0::2] + kwh[1::2]) / 1000.0
        out.extend(list(hourly * (1 + r.normal(0, 0.015, 24))))
    return np.array(out)


def build_cfe(customers: pd.DataFrame, temps, act: np.ndarray, load_dates: list[str], cf_cache) -> tuple[pd.DataFrame, pd.DataFrame]:
    r = rng("cfe")
    dates = drange("2026-07-01", SCEN_DATE)
    idx_by_id = {cid: i for i, cid in enumerate(customers.customer_id)}
    alloc_rows, ledger = [], []
    cert_seq = 0
    for c in customers[customers.cfe_contract].itertuples():
        i = idx_by_id[c.customer_id]
        load = customer_hourly_load(c, dates, temps, r)
        # August hours use the same metered actuals as customer_load_30min (consistency by construction).
        for j, d in enumerate(load_dates):
            k0 = dates.index(d) * 24
            half = act[i, j, :] / 1000.0
            load[k0:k0 + 24] = half[0::2] + half[1::2]
        avg_mw = load.mean()
        port = CFE_PORTFOLIOS[c.cfe_product]
        # Size the contracted shares so annual volumetric cover is ~100-104 % of load.
        gen_by_res = {rid: cf_cache[(rid, "actual")][: len(dates) * 24] for rid in port}
        unit = sum(port[rid] * gen_by_res[rid].mean() for rid in port)
        scale = avg_mw * r.uniform(1.00, 1.04) / unit
        mw_share = {rid: port[rid] * scale for rid in port}
        for k in range(len(dates) * 24):
            d, h = dates[k // 24], k % 24
            if d == SCEN_DATE and h >= NOW_HOUR:
                continue  # hour 15 is incomplete at 15:40
            by_res = {rid: mw_share[rid] * gen_by_res[rid][k] for rid in port}
            alloc = sum(by_res.values())
            alloc_rows.append({"customer_id": c.customer_id, "date": d, "hour": h, "month": d[:7],
                               "load_mwh": round(float(load[k]), 3), "allocated_cfe_mwh": round(float(alloc), 3)})
            for rid, mwh in by_res.items():
                if mwh < 0.005 or d < "2026-08-01":  # the 30-minute certificate pilot ledger starts 2026-08-01
                    continue
                for half_slot in (0, 1):
                    cert_seq += 1
                    s = h * 2 + 1 + half_slot
                    ledger.append({
                        "certificate_id": f"NFC{d[2:4]}{d[5:7]}{d[8:10]}-{rid[3:]}-{s:02d}-{cert_seq:05d}",
                        "resource_id": rid, "generation_date": d, "generation_hour": h, "generation_slot": s,
                        "generation_start": slot_start(d, s), "mwh": round(float(mwh) / 2, 4),
                        "vintage_fy": "FY2026", "issue_date": (date.fromisoformat(d) + timedelta(days=3)).isoformat(),
                        "expiry_date": "2027-06-30", "claimed_by_customer_id": c.customer_id,
                        "claim_date": (date.fromisoformat(d) + timedelta(days=5)).isoformat(), "claim_month": d[:7],
                    })
    led = pd.DataFrame(ledger)
    rtype = {a: b for a, b, *_ in RESOURCES}
    ctype = {a: n for a, b, c, m, av, n in RESOURCES}
    led["resource_type"] = led.resource_id.map(rtype)
    led["certificate_type"] = led.resource_id.map(ctype)
    # A4: double claim. A certificate legitimately claimed by C-0005 re-appears as a claim by C-0008.
    orig = led[(led.claimed_by_customer_id == "C-0005") & (led.claim_month == "2026-08") &
               (led.resource_id == "CR-WND-ON") & (led.generation_date == "2026-08-07")].sort_values("generation_start").iloc[18]
    dup = orig.copy()
    dup["claimed_by_customer_id"] = "C-0008"
    dup["claim_date"] = "2026-08-14"
    # Claim with no matching generation: a solar certificate stamped at 02:00.
    ghost = orig.copy()
    ghost.update({"certificate_id": "NFC260812-SOL-KANTO-05-G0001", "resource_id": "CR-SOL-KANTO",
                  "resource_type": "solar", "generation_date": "2026-08-12", "generation_hour": 2, "generation_slot": 5,
                  "generation_start": "2026-08-12T02:00", "mwh": 3.2, "claimed_by_customer_id": "C-0010",
                  "claim_date": "2026-08-15", "issue_date": "2026-08-13"})
    # Expired vintage: FY2025 certificate (claim window closed 2026-06-30) claimed against August consumption.
    stale = orig.copy()
    stale.update({"certificate_id": "NFC260314-HYD-ROR-23-V0001", "resource_id": "CR-HYD-ROR",
                  "resource_type": "hydro_run_of_river", "generation_date": "2026-03-14", "generation_hour": 11,
                  "generation_slot": 23, "generation_start": "2026-03-14T11:00", "mwh": 4.5, "vintage_fy": "FY2025",
                  "issue_date": "2026-03-20", "expiry_date": "2026-06-30", "claimed_by_customer_id": "C-0014",
                  "claim_date": "2026-08-10", "claim_month": "2026-08"})
    led = pd.concat([led, pd.DataFrame([dup, ghost, stale])], ignore_index=True)
    led = led.sort_values(["claim_month", "generation_start", "certificate_id", "claimed_by_customer_id"]).reset_index(drop=True)
    led.insert(0, "entry_id", [f"LE-{k + 1:07d}" for k in range(len(led))])
    return pd.DataFrame(alloc_rows), led


# ---------------------------------------------------------------------------------------------- prospects
PROSPECTS = [
    ("PR-01", "Hokuso Cloud Campus", "Hokuso Digital Infrastructure KK (fictional)", "Inzai, Chiba", "hyperscale_data_center",
     62.0, "bill_PR-01_hokuso_cloud_campus_2026-07.txt", 90.0),
    ("PR-02", "Minuma Power Devices", "Minuma Power Devices KK (fictional)", "Saitama, Saitama", "power_semiconductor_fab",
     34.0, "bill_PR-02_minuma_power_devices_2026-07.txt", 80.0),
    ("PR-03", "Sagamihara Logistics Hub", "Sagami Gateway Logistics KK (fictional)", "Sagamihara, Kanagawa", "logistics_hub",
     8.5, "bill_PR-03_sagamihara_logistics_hub_2026-07.txt", 60.0),
]


def build_prospects() -> tuple[pd.DataFrame, pd.DataFrame]:
    r = rng("prospects")
    dates = drange("2027-01-01", "2027-12-31")
    rows, prof = [], []
    for pid, name, legal, site, seg, peak, doc, cfe in PROSPECTS:
        load = []
        for d in dates:
            dd = date.fromisoformat(d)
            doy = dd.timetuple().tm_yday
            summer = math.exp(-((doy - 215) / 45) ** 2)
            for h in range(24):
                if seg == "hyperscale_data_center":
                    ramp = 0.86 + 0.08 * min(1.0, doy / 240)  # phase-1 halls fill through the year
                    v = peak * ramp * (0.90 + 0.07 * summer + 0.02 * math.sin((h - 9) / 24 * 2 * math.pi))
                elif seg == "power_semiconductor_fab":
                    v = peak * (0.88 + 0.04 * summer + r.normal(0, 0.01)) * (0.55 if (dd.month == 12 and dd.day >= 28) or (dd.month == 1 and dd.day <= 3) else 1)
                else:
                    day = 1.0 if 6 <= h < 22 else 0.32
                    wk = 0.7 if dd.weekday() == 6 else 1.0
                    v = peak * day * wk * (0.62 + 0.18 * summer) + r.normal(0, 0.1)
                load.append(max(0.0, v * (1 + r.normal(0, 0.012))))
        load = np.array(load)
        for k, v in enumerate(load):
            d = dates[k // 24]
            prof.append((pid, d, k % 24, d[:7], round(float(v), 3)))
        rows.append({"prospect_id": pid, "name": name, "legal_entity": legal, "site": site, "segment": seg,
                     "projected_peak_mw": round(float(load.max()), 1), "projected_annual_mwh": round(float(load.sum()), 0),
                     "load_factor": round(float(load.mean() / load.max()), 3), "cfe_ambition_pct": cfe,
                     "current_supplier": "incumbent retailer (anonymised)", "bill_document": doc,
                     "stage": "qualification", "desired_start": "2027-04-01"})
    return pd.DataFrame(rows), pd.DataFrame(prof, columns=["prospect_id", "date", "hour", "month", "load_mwh"])


# ---------------------------------------------------------------------------------------------- schema
S, I, F, B = "STRING", "INT64", "FLOAT64", "BOOL"
SCHEMA = {
    "jepx_spot_30min": ("JEPX day-ahead spot results per 30-minute slot, Tokyo area and system price (synthetic).", [
        ("date", S, "Delivery date YYYY-MM-DD"), ("slot", I, "30-minute slot 1-48 (slot 1 = 00:00-00:30)"),
        ("hour", I, "Hour of day 0-23"), ("month", S, "YYYY-MM"), ("start_time", S, "Slot start YYYY-MM-DDTHH:MM JST"),
        ("tokyo_price_jpy_kwh", F, "Tokyo area price JPY/kWh"), ("system_price_jpy_kwh", F, "System price JPY/kWh"),
        ("system_volume_mwh", F, "Contracted volume MWh (system)")]),
    "jepx_intraday_30min": ("JEPX intraday (continuous) market per slot for the scenario fortnight; open slots on the scenario day hold the 15:40 order-book snapshot.", [
        ("date", S, "Delivery date"), ("slot", I, "Slot 1-48"), ("hour", I, "Hour 0-23"), ("month", S, "YYYY-MM"),
        ("start_time", S, "Slot start"), ("gate_closure_time", S, "Gate closure (1 h before delivery)"),
        ("snapshot_time", S, "Time of the book snapshot"), ("vwap_jpy_kwh", F, "Volume-weighted average price JPY/kWh"),
        ("best_bid_jpy_kwh", F, "Best bid JPY/kWh"), ("best_ask_jpy_kwh", F, "Best ask JPY/kWh"),
        ("ask_depth_mwh", F, "MWh available at best ask"), ("ask_level2_jpy_kwh", F, "Second ask level JPY/kWh"),
        ("ask_level2_depth_mwh", F, "MWh available at second ask level"), ("traded_volume_mwh", F, "Traded volume MWh")]),
    "imbalance_30min": ("Wide-area reserve margin and imbalance settlement price per slot; scenario-day slots from 32 are forecasts with p10/p90.", [
        ("date", S, "Delivery date"), ("slot", I, "Slot 1-48"), ("hour", I, "Hour 0-23"), ("month", S, "YYYY-MM"),
        ("start_time", S, "Slot start"), ("reserve_margin_pct", F, "Wide-area reserve margin % (actual or forecast)"),
        ("imbalance_price_jpy_kwh", F, "Imbalance price JPY/kWh (actual, or p50 forecast when is_forecast)"),
        ("imbalance_p10_jpy_kwh", F, "p10 forecast JPY/kWh (equals actual when settled)"),
        ("imbalance_p90_jpy_kwh", F, "p90 forecast JPY/kWh (equals actual when settled)"),
        ("scarcity_flag", B, "True when the reserve margin is inside the scarcity-pricing range"),
        ("is_forecast", B, "True for slots not yet settled")]),
    "weather_forecast_hourly": ("WeatherNext-style ensemble forecast (p10/p50/p90) for 10 Kanto cells.", [
        ("cell_id", S, "Grid cell id"), ("cell_name", S, "Cell name"), ("lat", F, "Latitude"), ("lon", F, "Longitude"),
        ("issue_time", S, "Forecast issue time"), ("date", S, "Valid date"), ("hour", I, "Valid hour 0-23"),
        ("month", S, "YYYY-MM"), ("valid_time", S, "Valid time"), ("temp_p10_c", F, "Temperature p10 degC"),
        ("temp_p50_c", F, "Temperature p50 degC"), ("temp_p90_c", F, "Temperature p90 degC"),
        ("ghi_p10_wm2", F, "Global horizontal irradiance p10 W/m2"), ("ghi_p50_wm2", F, "GHI p50 W/m2"),
        ("ghi_p90_wm2", F, "GHI p90 W/m2")]),
    "customers": ("C&I retail customers of the desk portfolio (fictional names).", [
        ("customer_id", S, "Customer id C-NNNN"), ("name", S, "Fictional customer name"), ("segment", S, "Segment"),
        ("voltage", S, "extra_high (>= 2,000 kW) or high"), ("prefecture", S, "Prefecture"),
        ("tariff_type", S, "fixed, market_linked or bandwidth"),
        ("deviation_band_pct", F, "Bandwidth tariff deviation band +/- % (null if not bandwidth)"),
        ("fixed_energy_price_jpy_kwh", F, "Energy price for fixed and bandwidth tariffs JPY/kWh"),
        ("market_adder_jpy_kwh", F, "Adder over spot for market-linked tariffs JPY/kWh"),
        ("contracted_kw", F, "Contracted demand kW"), ("annual_mwh", F, "Expected annual consumption MWh"),
        ("margin_jpy_kwh", F, "Expected retail margin JPY/kWh"), ("dr_enrolled", B, "Enrolled in demand response"),
        ("essential_facility", B, "Essential facility (no involuntary curtailment)"),
        ("cfe_contract", B, "Has a clean-energy (CFE) supply contract"),
        ("cfe_product", S, "hourly_24x7 or annual_volumetric (null if none)"), ("contract_end", S, "Contract end date")]),
    "customer_load_30min": ("Per-customer 30-minute load, 2026-08-01 to the scenario day. actual_kwh is null after 'now' (slot 32 onward on 2026-08-19).", [
        ("customer_id", S, "Customer id"), ("date", S, "Date"), ("slot", I, "Slot 1-48"), ("month", S, "YYYY-MM"),
        ("forecast_da_kwh", F, "Day-ahead forecast kWh (basis of the balancing plan)"),
        ("forecast_latest_kwh", F, "Latest intraday forecast kWh"), ("actual_kwh", F, "Metered kWh (null if not delivered)"),
        ("nominated_kwh", F, "Customer nomination kWh (bandwidth tariffs only)"), ("is_actual", B, "True when metered")]),
    "balance_position_30min": ("Balance group (C&I desk) plan vs actual per slot: demand, procurement by source and open position (negative = short).", [
        ("date", S, "Date"), ("slot", I, "Slot"), ("hour", I, "Hour"), ("month", S, "YYYY-MM"), ("start_time", S, "Slot start"),
        ("gate_closure_time", S, "Gate closure time"), ("gate_status", S, "delivered, in_delivery, closed or open at 15:40 snapshot"),
        ("demand_forecast_da_mwh", F, "Day-ahead demand plan MWh"), ("demand_forecast_latest_mwh", F, "Latest demand forecast MWh"),
        ("demand_actual_mwh", F, "Metered demand MWh (null if not delivered)"), ("procured_bilateral_mwh", F, "Bilateral MWh"),
        ("procured_spot_mwh", F, "JEPX spot MWh"), ("procured_intraday_mwh", F, "Intraday MWh already bought"),
        ("vpp_dispatched_mwh", F, "VPP energy already scheduled MWh"), ("total_procured_mwh", F, "Total supply MWh"),
        ("open_position_mwh", F, "Supply minus demand MWh (negative = short)")]),
    "customer_forecast_daily": ("Daily consumption forecast per customer for the rest of August.", [
        ("customer_id", S, "Customer id"), ("date", S, "Date"), ("month", S, "YYYY-MM"), ("forecast_mwh", F, "Forecast MWh")]),
    "forward_curve_daily": ("Synthetic Tokyo-area forward marks per delivery day.", [
        ("date", S, "Delivery date"), ("month", S, "YYYY-MM"), ("baseload_jpy_kwh", F, "Baseload forward JPY/kWh"),
        ("peak_jpy_kwh", F, "Peak forward JPY/kWh"), ("source_note", S, "Provenance note")]),
    "hedge_book": ("Baseload hedges covering price-exposed retail volume.", [
        ("hedge_id", S, "Hedge id"), ("product", S, "baseload"), ("instrument", S, "bilateral or futures"),
        ("start_date", S, "Start date"), ("end_date", S, "End date"), ("mw", F, "MW hedged each hour"),
        ("price_jpy_kwh", F, "Hedge price JPY/kWh")]),
    "vpp_clusters": ("Mega-VPP clusters (aggregated DER pools).", [
        ("cluster_id", S, "Cluster id"), ("name", S, "Cluster name"), ("asset_class", S, "residential_battery, heat_pump_water_heater, cni_bess, ev_depot, dr_load"),
        ("area", S, "Prefecture"), ("device_count", I, "Devices in pool"), ("capacity_kw", F, "Dispatchable power kW"),
        ("energy_kwh", F, "Energy capacity kWh"), ("min_soc_pct", F, "SOC floor % (0 for non-storage)"),
        ("max_soc_pct", F, "SOC ceiling %"), ("dispatch_cost_jpy_kwh", F, "Dispatch cost incl. customer incentive JPY/kWh"),
        ("response_time_s", I, "Response time seconds"), ("telemetry_interval_s", I, "Expected telemetry interval seconds"),
        ("program", S, "Program")]),
    "vpp_telemetry_30min": ("Cluster telemetry per slot (2026-08-18 and 2026-08-19 up to the 15:40 snapshot).", [
        ("cluster_id", S, "Cluster id"), ("date", S, "Date"), ("slot", I, "Slot"), ("hour", I, "Hour"), ("month", S, "YYYY-MM"),
        ("timestamp", S, "Record time"), ("soc_pct", F, "State of charge % (null for non-storage)"),
        ("available_kw", F, "Available up-regulation kW"), ("available_kwh", F, "Energy above SOC floor kWh"),
        ("online_devices", I, "Devices reporting"), ("last_seen", S, "Last device heartbeat time")]),
    "ancillary_commitments": ("Balancing-market dKW commitments already awarded for the scenario evening block.", [
        ("commitment_id", S, "Commitment id"), ("date", S, "Date"), ("from_slot", I, "First slot"), ("to_slot", I, "Last slot"),
        ("product", S, "Balancing product"), ("cluster_id", S, "Cluster holding the reserve"), ("committed_kw", F, "dKW committed kW"),
        ("response_minutes", I, "Required response minutes (EPRX product requirement)"),
        ("duration_hours", F, "Required delivery duration hours (EPRX product requirement)"),
        ("reserve_energy_kwh", F, "Energy the desk must hold back: committed kW x duration x 2 activations (desk policy)"),
        ("price_jpy_per_dkw_30min", F, "Cleared dKW price JPY per dKW per 30 min"), ("tso_area", S, "TSO area"), ("status", S, "Status"),
        ("awarded_at", S, "Award time")]),
    "clean_resources": ("Contracted clean supply resources (generic, no named plants).", [
        ("resource_id", S, "Resource id"), ("resource_type", S, "Type"), ("region", S, "Region"),
        ("contracted_mw", F, "MW contracted to the retail portfolio"), ("available_mw_new_ppa", F, "MW available for new PPAs"),
        ("nfc_certificate_type", S, "Non-fossil certificate type"), ("cost_jpy_kwh", F, "Desk cost JPY/kWh")]),
    "clean_supply_hourly": ("Hourly capacity factor and generation per resource: 'actual' (2026-07-01 to now) and 'p50_projection' (2027).", [
        ("resource_id", S, "Resource id"), ("period", S, "actual or p50_projection"), ("date", S, "Date"), ("hour", I, "Hour"),
        ("month", S, "YYYY-MM"), ("capacity_factor", F, "Capacity factor 0-1"), ("generation_mwh", F, "Generation MWh for contracted MW")]),
    "grid_mix_hourly": ("Tokyo-area grid carbon-free share and carbon intensity per hour.", [
        ("date", S, "Date"), ("hour", I, "Hour"), ("month", S, "YYYY-MM"), ("grid_cfe_share_pct", F, "Carbon-free share of grid mix %"),
        ("carbon_intensity_g_kwh", F, "gCO2/kWh")]),
    "cfe_allocation_hourly": ("Hourly load and allocated contracted clean energy for customers with CFE contracts.", [
        ("customer_id", S, "Customer id"), ("date", S, "Date"), ("hour", I, "Hour"), ("month", S, "YYYY-MM"),
        ("load_mwh", F, "Metered load MWh"), ("allocated_cfe_mwh", F, "Contracted clean energy allocated MWh")]),
    "nfc_ledger": ("Non-fossil certificate claim ledger at 30-minute granularity (Powerledger-style provenance).", [
        ("entry_id", S, "Ledger entry id"), ("certificate_id", S, "Certificate id"), ("resource_id", S, "Generating resource"),
        ("generation_date", S, "Generation date"), ("generation_hour", I, "Generation hour"), ("generation_slot", I, "Generation slot"),
        ("generation_start", S, "Generation slot start"), ("mwh", F, "Certified MWh"), ("vintage_fy", S, "Fiscal-year vintage"),
        ("issue_date", S, "Issue date"), ("expiry_date", S, "Last date the certificate may be claimed"),
        ("claimed_by_customer_id", S, "Customer claiming the certificate"), ("claim_date", S, "Claim date"),
        ("claim_month", S, "Consumption month the claim is applied to"), ("resource_type", S, "Resource type"),
        ("certificate_type", S, "Certificate type")]),
    "prospects": ("Enterprise prospects in the onboarding pipeline (fictional).", [
        ("prospect_id", S, "Prospect id"), ("name", S, "Site name"), ("legal_entity", S, "Legal entity (fictional)"),
        ("site", S, "Location"), ("segment", S, "Segment"), ("projected_peak_mw", F, "Projected peak MW"),
        ("projected_annual_mwh", F, "Projected annual MWh"), ("load_factor", F, "Load factor"),
        ("cfe_ambition_pct", F, "Stated hourly CFE ambition %"), ("current_supplier", S, "Current supplier"),
        ("bill_document", S, "Bill file in docs_corpus"), ("stage", S, "Pipeline stage"), ("desired_start", S, "Desired supply start")]),
    "prospect_load_hourly": ("Projected hourly load for contract year 1 (2027).", [
        ("prospect_id", S, "Prospect id"), ("date", S, "Date"), ("hour", I, "Hour"), ("month", S, "YYYY-MM"), ("load_mwh", F, "Load MWh")]),
}


def write_table(name: str, df: pd.DataFrame) -> None:
    cols = [c[0] for c in SCHEMA[name][1]]
    missing = set(cols) - set(df.columns)
    assert not missing, f"{name} missing {missing}"
    out = df[cols].copy()
    for cname, ctype, _ in SCHEMA[name][1]:
        if ctype == B:
            out[cname] = out[cname].map(lambda v: "" if v is None or (isinstance(v, float) and math.isnan(v)) else ("true" if v else "false"))
        elif ctype == I:
            out[cname] = out[cname].astype("Int64")
    out.to_csv(os.path.join(OUT, f"{name}.csv"), index=False)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    temps = build_temperature(drange(P["calendar"]["spot_start"], P["calendar"]["spot_end"]))
    spot = build_spot(temps)
    imb = build_imbalance(spot)
    intr = build_intraday(spot, imb)
    weather = build_weather(temps)
    customers = build_customers()
    load, act, load_dates = build_customer_load(customers, temps)
    bal = build_balance_position(load)
    fwd, fc, hedges = build_forward_and_hedges(customers, temps)
    clusters, tel, anc = build_vpp()
    res, cs, cf_cache = build_clean_supply()
    grid = build_grid_mix()
    alloc, ledger = build_cfe(customers, temps, act, load_dates, cf_cache)
    prospects, pload = build_prospects()
    tables = {
        "jepx_spot_30min": spot, "jepx_intraday_30min": intr, "imbalance_30min": imb, "weather_forecast_hourly": weather,
        "customers": customers, "customer_load_30min": load, "balance_position_30min": bal,
        "customer_forecast_daily": fc, "forward_curve_daily": fwd, "hedge_book": hedges, "vpp_clusters": clusters,
        "vpp_telemetry_30min": tel, "ancillary_commitments": anc, "clean_resources": res, "clean_supply_hourly": cs,
        "grid_mix_hourly": grid, "cfe_allocation_hourly": alloc, "nfc_ledger": ledger, "prospects": prospects,
        "prospect_load_hourly": pload,
    }
    for name, df in tables.items():
        write_table(name, df)
    schema = {"tables": {n: {"description": d, "columns": [{"name": c, "type": t, "description": x} for c, t, x in cols]}
                         for n, (d, cols) in SCHEMA.items()}}
    for path in (os.path.join(HERE, "schema.json"), os.path.join(PKG, "schema.json")):
        with open(path, "w") as f:  # data/schema.json (BigQuery load) and the packaged copy must stay identical
            json.dump(schema, f, indent=1)
    manifest = {"generator": "data/generate.py", "seed": SEED, "scenario_now": NOW, "calendar": P["calendar"],
                "tables": {n: len(df) for n, df in tables.items()}, "rows": int(sum(len(t) for t in tables.values()))}
    with open(os.path.join(PKG, "data_manifest.json"), "w") as f:  # read by the UI provenance footers
        json.dump(manifest, f, indent=1)
    from documents import write_documents  # noqa: E402  (sibling module, keeps this file focused on tables)
    write_documents(CORPUS, P, prospects, pload)
    total = sum(os.path.getsize(os.path.join(OUT, f"{n}.csv")) for n in tables)
    print(f"wrote {len(tables)} tables, {sum(len(t) for t in tables.values()):,} rows, {total / 1e6:.1f} MB -> {OUT}")


if __name__ == "__main__":
    import sys

    sys.path.insert(0, HERE)
    main()
