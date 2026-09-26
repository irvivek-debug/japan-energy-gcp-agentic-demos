#!/usr/bin/env python
"""Deterministic synthetic data generator for the Edge-to-Grid Factory Energy Copilot demo.

Builds a 5-minute physical model of a fictional ~16 MW SiC-module / automotive-ECU plant in Atsugi
(TEPCO PG area) from 2026-06-01 to the demo day, and derives every table from that one model so the
receiving-point import, sub-meters, BESS, PV, DR settlements and the savings ledger reconcile.

Usage:  python data/generate.py            (writes data/out/*.csv, data/schema.json, factory_copilot/schema.json)
All parameters: data/simulation_parameters.yaml. Seeded; re-running gives byte-identical output.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import shutil
import sys

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from factory_copilot.core import bess as bess_core  # noqa: E402
from factory_copilot.core import dr_math  # noqa: E402
from factory_copilot.core.clock import slot_of, slot_start, ts_of  # noqa: E402

P = yaml.safe_load(open(os.path.join(HERE, "simulation_parameters.yaml")))
OUT = os.path.join(HERE, "out")
STEP = 5
PER_DAY = 288
DEMO_DATE = P["demo_now"][:10]
NOW_HHMM = P["demo_now"][11:16]
NOW_SLOT = slot_of(NOW_HHMM)


def rng(name: str) -> np.random.Generator:
    h = int(hashlib.sha256(f"{P['seed']}:{name}".encode()).hexdigest()[:12], 16)
    return np.random.default_rng(h)


def hm(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def fmt_min(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


# ------------------------------------------------------------------------------------------------
# Calendar and weather
# ------------------------------------------------------------------------------------------------
START = P["periods"]["site_history_start"]
DAYS = pd.date_range(START, DEMO_DATE, freq="D").strftime("%Y-%m-%d").tolist()
ALL_DAYS = pd.date_range(START, "2026-08-20", freq="D").strftime("%Y-%m-%d").tolist()
N = len(DAYS) * PER_DAY
I_NOW = (len(DAYS) - 1) * PER_DAY + hm(NOW_HHMM) // STEP
HOL = set(P["calendar"]["public_holidays"])
RED = set(P["calendar"]["plant_reduced_days"])
EVENT_DATES = {e["date"]: e for e in P["dr_events"]["history"]}
TODAY_EVENT = P["dr_events"]["today"]


def day_type(d: str) -> str:
    if d in RED:
        return "reduced"
    if d in HOL:
        return "holiday"
    wd = dt.date.fromisoformat(d).weekday()
    return "saturday" if wd == 5 else "sunday" if wd == 6 else "weekday"


DAYTYPE = {d: day_type(d) for d in ALL_DAYS}
INTENS = {d: P["calendar"]["intensity"][DAYTYPE[d]] for d in ALL_DAYS}


def build_weather():
    r = rng("weather")
    tmax, cloud = {}, {}
    for d in ALL_DAYS:
        for rg in P["weather"]["tmax_ranges"]:
            if rg["from"] <= d <= rg["to"]:
                tmax[d] = float(r.uniform(rg["lo"], rg["hi"]))
                cloud[d] = float(r.uniform(rg["cloud_lo"], rg["cloud_hi"]))
                break
        else:
            tmax[d], cloud[d] = 35.0, 0.15
        if d in P["weather"]["fixed_days"]:
            tmax[d] = float(P["weather"]["fixed_days"][d]["tmax"])
            cloud[d] = float(P["weather"]["fixed_days"][d]["cloud"])
    return tmax, cloud


TMAX, CLOUD = build_weather()
DIURNAL = P["weather"]["diurnal_range_c"]


def temp_at(d_idx: int, minute: float) -> float:
    """Diurnal curve: min at 05:00, max at 14:00 (half-cosine rise 9 h, fall 15 h)."""
    d = DAYS[d_idx] if d_idx < len(DAYS) else ALL_DAYS[d_idx]
    tmx = TMAX[d]
    h = minute / 60.0
    if 5 <= h <= 14:
        f = 0.5 - 0.5 * math.cos(math.pi * (h - 5) / 9)
        tmin = tmx - DIURNAL
    else:
        hh = h - 14 if h > 14 else h + 10
        f = 0.5 + 0.5 * math.cos(math.pi * hh / 15)
        prev = ALL_DAYS[max(0, d_idx - 1)]
        tmin = tmx - DIURNAL if h > 14 else TMAX[prev] - DIURNAL
        tmx = tmx if h > 14 else TMAX[prev]
    return tmin + (tmx - tmin) * f


IDX = np.arange(N)
DIDX = IDX // PER_DAY
MIN = (IDX % PER_DAY) * STEP
DATE_OF = np.array(DAYS)[DIDX]
T_AIR = np.array([temp_at(int(di), float(m)) for di, m in zip(DIDX, MIN)])
DT_OF = np.array([DAYTYPE[d] for d in DAYS])[DIDX]
INT_DAY = np.array([INTENS[d] for d in DAYS])[DIDX]
NIGHT = (MIN < 360) | (MIN >= 1320)
PROD = INT_DAY * np.where(NIGHT, 0.93, 1.0)       # production intensity
WEEKDAY = DT_OF == "weekday"
SAT = DT_OF == "saturday"


def ar_noise(name: str, sigma: float, rho: float = 0.9) -> np.ndarray:
    r = rng("noise:" + name)
    w = r.normal(0, sigma * math.sqrt(1 - rho * rho), N)
    e = np.empty(N)
    acc = 0.0
    for i in range(N):
        acc = rho * acc + w[i]
        e[i] = acc
    return e + r.normal(0, sigma * 0.35, N)


# ------------------------------------------------------------------------------------------------
# Asset register
# ------------------------------------------------------------------------------------------------
ASSETS: list[dict] = []
METERS: list[dict] = []


def add_asset(asset_id, name, cls, area, crit, flex_class, flex_method, rated, flex_nom, max_shift, meter, plc):
    ASSETS.append(dict(asset_id=asset_id, asset_name=name, asset_class=cls, area=area, criticality=crit,
                       flex_class=flex_class, flex_method=flex_method, rated_kw=float(rated),
                       flex_kw_nominal=float(flex_nom), max_shift_h=float(max_shift), meter_id=meter,
                       plc_tag=plc, controller="MELSEC iQ-R series PLC" if plc else ""))


def build_register():
    for i in range(1, 7):
        prod_zone = i <= 4
        add_asset(f"CR-AHU-0{i}", f"Clean-room air handler {i}", "cleanroom_hvac",
                  "Clean room ISO 6/7 production (SiC module)" if prod_zone else "Clean room ISO 8 support (gowning, corridors)",
                  "critical", "trim" if not prod_zone else "none",
                  "Fan speed trim down to the airflow floor (support zones only)" if not prod_zone else "No trim: production-zone airflow held at 100 % while product is exposed",
                  260, 0 if prod_zone else 40, 0, f"M-0{i + 1}", f"iQR-HVAC1/D{2000 + 10 * i}")
    for i in range(1, 5):
        add_asset(f"CR-EXF-0{i}", f"Clean-room exhaust fan {i}", "cleanroom_exhaust", "Clean room", "critical", "none",
                  "Safety exhaust (process gases); never curtailed", 50, 0, 0, "M-08", f"iQR-HVAC1/D{2100 + 10 * i}")
    for i in range(1, 5):
        add_asset(f"OF-AHU-0{i}", f"Office air handler {i}", "office_hvac", "Office and admin building", "low", "setpoint",
                  "Zone setpoint +2 C up to the 28 C policy limit", 140, 45, 0, "M-09" if i <= 2 else "M-10", f"iQR-BMS1/D{3000 + 10 * i}")
    for i in range(1, 5):
        add_asset(f"CH-0{i}", f"Centrifugal chiller {i}", "chiller", "Central utility plant", "high", "tes_shift",
                  "Unload while thermal storage carries the cooling load; chilled-water supply +1.5 C", 800, 0, 0,
                  f"M-{10 + i}", f"iQR-UTIL1/D{4000 + 10 * i}")
    add_asset("TES-01", "Chilled-water thermal storage tank (14 MWh-th)", "thermal_storage", "Central utility plant", "high",
              "storage", "Discharge stored chilled water to unload chillers", 0, 700, 0, "", "iQR-UTIL1/D4100")
    for i in range(1, 5):
        add_asset(f"CT-0{i}", f"Cooling tower fan {i}", "cooling_aux", "Central utility plant", "high", "none",
                  "Follows chiller staging", 30, 0, 0, "M-15", f"iQR-UTIL1/D{4200 + 10 * i}")
        add_asset(f"CHWP-0{i}", f"Chilled-water pump {i}", "cooling_aux", "Central utility plant", "high", "none",
                  "Follows chiller staging", 37, 0, 0, "M-16", f"iQR-UTIL1/D{4300 + 10 * i}")
    for i in range(1, 7):
        add_asset(f"AC-0{i}", f"Air compressor {i} (250 kW class)", "compressor", "Compressor house", "high",
                  "standby" if i == 4 else "none",
                  "Move to standby and let peers carry the load (efficiency gain); header setpoint trim" if i == 4 else "Header pressure must hold 0.60 MPa with N-1 redundancy",
                  260, 45 if i == 4 else 0, 0, f"M-{16 + i}", f"iQR-UTIL2/D{5000 + 10 * i}")
    for i in range(1, 4):
        add_asset(f"FN-0{i}", f"Reflow / sintering furnace {i}", "furnace", "SiC module back-end", "high", "batch",
                  "Standby when idle; batch start deferral only if the batch is not committed at the PLC", 1150, 90 if i == 3 else 820,
                  3, f"M-{22 + i}", f"iQR-FN{i}/D{6000 + 10 * i}")
    for i in range(1, 7):
        sic = i <= 4
        add_asset(f"LN-0{i}", f"{'SiC module line' if sic else 'ECU SMT and end-of-line test line'} {i}", "production_line",
                  "SiC module front/back-end" if sic else "Automotive ECU assembly", "critical", "none",
                  "No line stops (production supervisor MES release required)", 780 if sic else 480, 0, 0,
                  f"M-{25 + i}", f"iQR-LN{i}/D{7000 + 10 * i}")
    for i in range(1, 9):
        add_asset(f"BI-0{i}", f"Burn-in rack {i}", "burn_in", "ECU reliability test", "medium", "defer",
                  "Defer cycle start up to 3 h (never pause mid-cycle)", 115, 112, 3, f"M-{31 + i}", f"iQR-TEST1/D{8000 + 10 * i}")
    for i in range(1, 11):
        van = i >= 7
        add_asset(f"EV-{i:02d}", f"{'Delivery van' if van else 'Forklift'} charger {i}", "ev_charger", "Logistics yard",
                  "low", "defer", "Defer charging; vans must reach 80 % by 07:00" if van else "Forklift chargers follow shift changes",
                  50 if van else 12, 50 if van else 0, 3 if van else 0, "M-41" if van else "M-40", f"iQR-LOG1/D{8200 + 10 * i}")
    for i in range(1, 7):
        add_asset(f"LT-0{i}", f"Office and warehouse lighting panel {i}", "lighting", "Office and warehouse", "low", "dim",
                  "Dim up to 30 % (desk illuminance policy)", 36, 11, 0, f"M-{41 + (i + 1) // 2}", f"iQR-BMS1/D{3100 + 10 * i}")
    for i in range(1, 5):
        add_asset(f"WW-0{i}", f"Wastewater lift pump {i}", "wastewater", "Wastewater treatment", "low", "shift",
                  "Pre-pump the pit then hold for up to 60 min", 45, 45, 1, "M-45" if i <= 2 else "M-46", f"iQR-WWT1/D{9000 + 10 * i}")
    add_asset("UPW-01", "Ultra-pure water plant", "critical_utility", "Utility plant", "critical", "none", "Never curtailed", 400, 0, 0, "M-47", "iQR-UTIL3/D9100")
    add_asset("N2-01", "Nitrogen generator", "critical_utility", "Utility plant", "critical", "none", "Never curtailed", 320, 0, 0, "M-48", "iQR-UTIL3/D9110")
    add_asset("IT-01", "Server and MES room", "critical_utility", "Admin building", "critical", "none", "Never curtailed", 140, 0, 0, "M-49", "")
    for i in range(1, 3):
        add_asset(f"PCW-0{i}", f"Process cooling water pump {i}", "critical_utility", "Utility plant", "critical", "none", "Never curtailed", 85, 0, 0, "M-50", f"iQR-UTIL3/D{9120 + 10 * i}")
        add_asset(f"VAC-0{i}", f"Process vacuum pump {i}", "critical_utility", "Utility plant", "critical", "none", "Never curtailed", 100, 0, 0, f"M-{50 + i}", f"iQR-UTIL3/D{9140 + 10 * i}")
    add_asset("MISC-01", "Admin building and canteen general power", "building_general", "Admin building", "low", "none", "Not controllable", 300, 0, 0, "M-57", "")
    for i, (k, kwp) in enumerate(P["pv"]["arrays"].items(), start=1):
        add_asset(k, {1: "Rooftop PV array A", 2: "Rooftop PV array B", 3: "Carport PV array"}[i] + f" ({kwp} kWp)", "pv", "Roof and carport",
                  "low", "generation", "Generation (not a load)", kwp, 0, 0, f"M-{52 + i}", f"iQR-PV1/D{9300 + 10 * i}")
    add_asset("BESS-01", "Battery energy storage 4 MW / 8 MWh (BESS-as-a-Service)", "bess", "Substation yard", "high", "storage",
              "Charge / discharge within SOC 10-95 %", 4000, 4000, 0, "M-56", "iQR-BESS1/D9500")
    add_asset("GRID-01", "66 kV receiving point", "receiving_point", "Substation", "critical", "none", "Receiving-point meter", 16000, 0, 0, "M-01", "")

    by_meter: dict[str, list[dict]] = {}
    for a in ASSETS:
        if a["meter_id"]:
            by_meter.setdefault(a["meter_id"], []).append(a)
    for m in sorted(by_meter, key=lambda x: int(x.split("-")[1])):
        members = by_meter[m]
        cls = members[0]["asset_class"]
        role = {"receiving_point": "receiving_point", "pv": "generation", "bess": "storage"}.get(cls, "feeder")
        METERS.append(dict(meter_id=m, meter_model="ME96-series multi-measuring instrument (class 0.5S energy)",
                           role=role, asset_ids=";".join(a["asset_id"] for a in members), asset_class=cls,
                           feeder=f"{'66 kV incomer' if role == 'receiving_point' else 'LV/HV feeder ' + m[2:]}",
                           comms="Modbus RTU to gateway, OPC UA to SCADA historian", install_year=2019 if int(m[2:]) < 50 else 2023))


build_register()
A_BY = {a["asset_id"]: a for a in ASSETS}

# ------------------------------------------------------------------------------------------------
# Schedules (furnace batches, burn-in cycles)
# ------------------------------------------------------------------------------------------------
T0 = dt.datetime.fromisoformat(START + "T00:00")


def abs_min(date: str, hhmm: str) -> int:
    return int((dt.datetime.fromisoformat(f"{date}T{hhmm}") - T0).total_seconds() // 60)


FIXED_FROM = abs_min("2026-08-18", "12:00")
FURNACE_FIXED = {
    "FN-01": [("2026-08-18", "14:10", 150), ("2026-08-18", "18:00", 150), ("2026-08-18", "21:10", 150), ("2026-08-19", "01:00", 150),
              ("2026-08-19", "04:30", 150), ("2026-08-19", "07:40", 150), ("2026-08-19", "10:50", 150), ("2026-08-19", "13:40", 150),
              ("2026-08-19", "19:20", 150), ("2026-08-19", "22:20", 150)],
    "FN-02": [("2026-08-18", "13:00", 150), ("2026-08-18", "16:20", 150), ("2026-08-18", "19:30", 150), ("2026-08-18", "22:40", 150),
              ("2026-08-19", "02:10", 150), ("2026-08-19", "05:20", 150), ("2026-08-19", "08:30", 150), ("2026-08-19", "11:40", 150),
              ("2026-08-19", "17:10", 150), ("2026-08-19", "20:20", 150)],
    "FN-03": [("2026-08-18", "12:40", 150), ("2026-08-18", "15:50", 150), ("2026-08-18", "19:00", 150), ("2026-08-18", "22:10", 150),
              ("2026-08-19", "02:00", 150), ("2026-08-19", "05:20", 150), ("2026-08-19", "08:00", 150), ("2026-08-19", "11:00", 150),
              ("2026-08-19", "20:30", 150)],
}
BURNIN_FIXED = {  # demo-day cycles (start HH:MM, 240 min)
    "BI-01": ["09:00", "14:00"], "BI-02": ["09:30", "14:30"], "BI-03": ["10:30", "16:00"], "BI-04": ["11:00", "16:15"],
    "BI-05": ["11:30", "16:30"], "BI-06": ["12:30", "17:00"], "BI-07": ["08:00", "19:30"], "BI-08": ["08:00", "12:00"],
}


def furnace_batches(fid: str) -> list[tuple[int, int]]:
    r = rng("furnace:" + fid)
    out, t = [], {"FN-01": 20, "FN-02": 75, "FN-03": 130}[fid]
    horizon = FIXED_FROM
    while t < horizon:
        d = DAYS[min(len(DAYS) - 1, t // 1440)]
        dtp = DAYTYPE[d]
        if dtp == "reduced" and fid != "FN-01":
            t += int(r.choice([240, 360]))
            continue
        dur = 150 + int(r.choice([0, 0, 10, 20]))
        out.append((t, t + dur))
        gap = int(r.choice([30, 40, 50, 60, 90])) if dtp == "weekday" else int(r.choice([90, 150, 240]))
        t += dur + gap
    out = [b for b in out if b[1] <= FIXED_FROM]
    for (d, s, dur) in FURNACE_FIXED[fid]:
        st = abs_min(d, s)
        out.append((st, st + dur))
    return sorted(out)


def burnin_cycles(bid: str) -> list[tuple[int, int]]:
    r = rng("burnin:" + bid)
    out, t = [], int(r.integers(0, 240))
    horizon = abs_min(DEMO_DATE, "00:00")
    while t < horizon:
        d = DAYS[min(len(DAYS) - 1, t // 1440)]
        if DAYTYPE[d] in ("reduced", "holiday", "sunday") and r.random() < 0.6:
            t += 300
            continue
        out.append((t, t + 240))
        t += 240 + int(r.choice([30, 45, 60, 90, 120, 150]))
    out = [c for c in out if c[1] <= horizon]
    for s in BURNIN_FIXED[bid]:
        st = abs_min(DEMO_DATE, s)
        out.append((st, st + 240))
    return sorted(out)


FURN = {f: furnace_batches(f) for f in ("FN-01", "FN-02", "FN-03")}
BURN = {f"BI-0{i}": burnin_cycles(f"BI-0{i}") for i in range(1, 9)}

# ------------------------------------------------------------------------------------------------
# Load model (expected = noise-free, actual = expected * (1 + AR noise))
# ------------------------------------------------------------------------------------------------
EXP: dict[str, np.ndarray] = {}
ACT: dict[str, np.ndarray] = {}
ABS = IDX * STEP  # absolute minutes since T0


def set_load(aid: str, expected: np.ndarray, sigma: float):
    EXP[aid] = np.maximum(0.0, expected)
    ACT[aid] = np.maximum(0.0, expected * (1.0 + ar_noise(aid, sigma)))


def build_loads():
    airflow = np.ones(N)
    for i in range(1, 7):
        base = 238.0 if i <= 4 else 205.0
        set_load(f"CR-AHU-0{i}", base * (1 + 0.006 * (T_AIR - 25)) * airflow * (0.98 + 0.02 * PROD), 0.012)
    for i in range(1, 5):
        set_load(f"CR-EXF-0{i}", np.full(N, 46.0), 0.01)
    office_on = (WEEKDAY & (MIN >= 420) & (MIN < 1200)) | (SAT & (MIN >= 480) & (MIN < 1020))
    for i in range(1, 5):
        load = np.where(office_on, (40 + 7.0 * np.maximum(0, T_AIR - 22)) * np.where(SAT, 0.55, 1.0), 12.0)
        set_load(f"OF-AHU-0{i}", load * (1.0 + 0.04 * (i - 2.5)), 0.03)
    # chillers
    process_heat = 5800.0 * PROD
    envelope = 270.0 * np.maximum(0, T_AIR - 16)
    office_cool = np.where(office_on, 150.0 * np.maximum(0, T_AIR - 22), 0.0)
    q_th = process_heat + envelope + office_cool
    cop = 6.3 - 0.09 * (T_AIR - 25)
    kwe = q_th / cop
    n_run = np.clip(np.ceil(kwe / 690.0), 2, 4)
    for i in range(1, 5):
        on = n_run >= i
        set_load(f"CH-0{i}", np.where(on, kwe / n_run, 0.0) * (1 + 0.01 * (i - 2.5)), 0.015)
        set_load(f"CT-0{i}", np.where(on, 12 + 0.018 * kwe / n_run, 0.0), 0.02)
        set_load(f"CHWP-0{i}", np.where(on, 37.0, 0.0), 0.01)
    EXP["TES-01"] = np.zeros(N)
    ACT["TES-01"] = np.zeros(N)
    # compressors
    ca = P["compressed_air"]
    demand = ca["demand_nm3min_weekday"] * np.where(WEEKDAY, 1.0, 0.0) + ca["demand_nm3min_weekday"] * (1 - WEEKDAY) * INT_DAY
    demand = demand * np.where(NIGHT, 0.95, 1.0)
    cap = ca["unit_capacity_nm3min"]
    tdays = (ABS / 1440.0)
    tel_start = (dt.date.fromisoformat(P["periods"]["telemetry_start"]) - dt.date.fromisoformat(START)).days
    demo_day = len(DAYS) - 1
    drift = np.interp(tdays, [0, tel_start, demo_day + 1], [0.02, ca["ac04_drift_start"], ca["ac04_drift_end"]])
    base_flow = np.minimum(cap * 0.97, demand / 4.0)
    rest = np.maximum(0.0, demand - 4 * base_flow)
    flows = {1: base_flow, 2: base_flow, 3: base_flow, 4: base_flow,
             5: np.minimum(cap, rest), 6: np.maximum(0.0, rest - cap)}
    sp_off = {1: -0.01, 2: 0.005, 3: 0.0, 4: 0.0, 5: 0.012, 6: -0.004}
    for i in range(1, 7):
        sp = ca["peer_specific_power"] * (1 + sp_off[i]) * (1 + (drift if i == 4 else 0.0))
        partload = np.where((i == 5) & (flows[i] < cap * 0.8), 1.08, 1.0)
        set_load(f"AC-0{i}", flows[i] * sp * partload, 0.012)
    EXP["_air_demand"] = demand
    EXP["_ac_flow"] = flows
    EXP["_ac04_drift"] = drift
    # furnaces
    for fid, batches in FURN.items():
        p = np.full(N, 130.0)
        for (s, e) in batches:
            m = (ABS >= s) & (ABS < e)
            rel = ABS - s
            p[m] = np.where(rel[m] < 30, 1150.0, np.where(rel[m] >= (e - s) - 20, 420.0, 820.0))
        set_load(fid, p, 0.01)
    # production lines
    for i in range(1, 7):
        if i <= 4:
            load = (720.0 + 25 * (i - 2.5)) * PROD * (1 + 0.004 * (T_AIR - 25))
        else:
            on = (WEEKDAY & (MIN >= 360) & (MIN < 1350)) | (SAT & (MIN >= 360) & (MIN < 900))
            load = np.where(on, 455.0 * INT_DAY, 60.0)
        set_load(f"LN-0{i}", load, 0.02)
    for bid, cycles in BURN.items():
        p = np.full(N, 4.0)
        for (s, e) in cycles:
            p[(ABS >= s) & (ABS < e)] = 112.0
        set_load(bid, p, 0.01)
    fork_windows = [(330, 420), (810, 900), (1290, 1380)]
    for i in range(1, 11):
        if i <= 6:
            on = np.zeros(N, bool)
            for (a, b) in fork_windows:
                on |= (MIN >= a + 5 * (i % 3)) & (MIN < b)
            load = np.where(on, 12.0, 0.3) * np.where(WEEKDAY, 1.0, 0.5)
        else:
            on = (WEEKDAY | SAT) & (MIN >= 990) & (MIN < 1170)
            load = np.where(on, 50.0 * np.where(SAT, 0.5, 1.0), 0.5)
        set_load(f"EV-{i:02d}", load, 0.01)
    light_on = (WEEKDAY & (MIN >= 420) & (MIN < 1260)) | (SAT & (MIN >= 480) & (MIN < 1020))
    for i in range(1, 7):
        set_load(f"LT-0{i}", np.where(light_on, 36.0 * np.where(SAT, 0.6, 1.0), 6.0), 0.01)
    for i in range(1, 5):
        on = ((MIN + 15 * i) % 60) < 30
        set_load(f"WW-0{i}", np.where(on, 45.0 * (0.8 + 0.2 * INT_DAY), 0.5), 0.02)
    set_load("UPW-01", 385.0 * (0.97 + 0.03 * PROD), 0.01)
    set_load("N2-01", 305.0 * np.sqrt(PROD), 0.01)
    set_load("IT-01", np.full(N, 132.0), 0.008)
    for i in range(1, 3):
        set_load(f"PCW-0{i}", 80.0 * (0.9 + 0.1 * PROD), 0.01)
        set_load(f"VAC-0{i}", 96.0 * (0.9 + 0.1 * PROD), 0.01)
    set_load("MISC-01", np.where(office_on, 265.0, 145.0), 0.03)


build_loads()
LOAD_IDS = [a["asset_id"] for a in ASSETS if a["asset_class"] not in ("pv", "bess", "receiving_point")]

# ------------------------------------------------------------------------------------------------
# PV
# ------------------------------------------------------------------------------------------------
SUNRISE, SUNSET = hm(P["pv"]["sunrise"]), hm(P["pv"]["sunset"])


def clear_sky_frac(minute: np.ndarray) -> np.ndarray:
    x = (minute - SUNRISE) / (SUNSET - SUNRISE)
    return np.where((x > 0) & (x < 1), np.sin(np.pi * np.clip(x, 0, 1)) ** 1.25, 0.0)


def build_pv():
    cs = clear_sky_frac(MIN.astype(float))
    r = rng("pv:clouds")
    c_day = np.array([CLOUD[d] for d in DAYS])[DIDX]
    ar = ar_noise("pv:cloud_ar", 0.35, 0.93)
    c_eff = np.clip(c_day * (1 + ar), 0, 1)
    t_cell = T_AIR + 25 * cs
    derate = 1 + P["pv"]["temp_coeff_per_c"] * (t_cell - 25)
    total_exp = 0.0
    for k, kwp in P["pv"]["arrays"].items():
        yld = P["pv"]["peak_yield"] * (0.97 if k == "PV-03" else 1.0)
        clear = kwp * yld * cs * derate
        EXP[k + "_clear"] = clear
        EXP[k] = clear * (1 - 0.75 * c_day)
        ACT[k] = np.maximum(0.0, clear * (1 - 0.75 * c_eff) * (1 + r.normal(0, 0.01, N)))
        total_exp = total_exp + clear
    EXP["_pv_clear_total"] = total_exp
    EXP["_irr"] = 1000 * cs * (1 - 0.75 * c_eff)
    EXP["_tcell"] = t_cell


build_pv()
PV_IDS = list(P["pv"]["arrays"].keys())

# ------------------------------------------------------------------------------------------------
# Historical DR events: physical actions on event days (applied to ACT only)
# ------------------------------------------------------------------------------------------------
EV_ACTIONS: dict[str, dict] = {}


def apply_events():
    for ev in P["dr_events"]["history"]:
        d = ev["date"]
        s, e = abs_min(d, ev["start"]), abs_min(d, ev["end"])
        win = (ABS >= s) & (ABS < e)
        after = (ABS >= e) & (ABS < e + (e - s))
        acts = ev.get("actions", {})
        applied = {}
        if "TES-01" in acts:
            chs = [f"CH-0{i}" for i in range(1, 5)]
            tot = sum(ACT[c] for c in chs)
            frac = np.where(tot > 0, np.minimum(1.0, acts["TES-01"] / np.maximum(tot, 1)), 0)
            for c in chs:
                ACT[c] = np.where(win, ACT[c] * (1 - frac), ACT[c])
            applied["TES-01"] = acts["TES-01"]

        def group_cut(prefix, kw, rebound):
            ids = [a for a in LOAD_IDS if a.startswith(prefix)]
            tot = sum(ACT[a] for a in ids)
            frac = np.where(tot > 0, np.minimum(1.0, kw / np.maximum(tot, 1)), 0)
            for a in ids:
                cut = ACT[a] * frac
                ACT[a] = np.where(win, ACT[a] - cut, ACT[a])
                if rebound:
                    shifted = np.zeros(N)
                    idx_w = np.where(win)[0]
                    idx_a = np.where(after)[0]
                    n = min(len(idx_w), len(idx_a))
                    shifted[idx_a[:n]] = cut[idx_w[:n]]
                    ACT[a] = ACT[a] + shifted
            applied[prefix] = kw

        for key, prefix, reb in (("BI", "BI-", True), ("EV", "EV-", True), ("OF", "OF-AHU", False), ("LT", "LT-", False), ("AC", "AC-04", False)):
            if key in acts:
                group_cut(prefix, acts[key], reb)
        if "furnace_overrun" in ev:
            fo = ev["furnace_overrun"]
            ACT[fo["asset"]] = np.where(win & (ABS < s + 150), np.maximum(ACT[fo["asset"]], fo["kw"]), ACT[fo["asset"]])
            applied["furnace_overrun"] = fo["kw"]
        EV_ACTIONS[ev["event_id"]] = applied


apply_events()

# ------------------------------------------------------------------------------------------------
# Gross load, BESS (rule_based_v1 history with event overrides), receiving point
# ------------------------------------------------------------------------------------------------
LOSS = 1 + P["plant"]["transformer_loss_pct"] / 100.0
GROSS_ACT = sum(ACT[a] for a in LOAD_IDS)
GROSS_EXP = sum(EXP[a] for a in LOAD_IDS)
PV_ACT = sum(ACT[k] for k in PV_IDS)
PV_EXP = sum(EXP[k] for k in PV_IDS)
BP = bess_core.BessParams(power_kw=P["bess"]["power_kw"], energy_kwh=P["bess"]["energy_kwh"],
                          soc_min_pct=P["bess"]["soc_min_pct"], soc_max_pct=P["bess"]["soc_max_pct"],
                          eff_charge=P["bess"]["eff_charge"], eff_discharge=P["bess"]["eff_discharge"])
PP = bess_core.PolicyParams(v1_night_kw=P["policies"]["v1_night_kw"], v1_midday_kw=P["policies"]["v1_midday_kw"],
                            v1_demand_limit_kw=P["policies"]["v1_demand_limit_kw"],
                            v2_target_soc_pct=P["policies"]["v2_target_soc_pct"], v2_reserve_soc_pct=P["policies"]["v2_reserve_soc_pct"],
                            v2_import_ceiling_kw=P["policies"]["v2_import_ceiling_kw"], v2_night_recharge_kw=P["policies"]["v2_night_recharge_kw"])


def slot_mean(arr: np.ndarray, day_i: int) -> np.ndarray:
    return arr[day_i * PER_DAY:(day_i + 1) * PER_DAY].reshape(48, 6).mean(axis=1)


def build_bess():
    power = np.zeros(N)
    soc_arr = np.zeros(N)
    soc = 55.0
    pre_bess_import = GROSS_ACT * LOSS - PV_ACT
    for di, d in enumerate(DAYS):
        imp = slot_mean(pre_bess_import, di)
        ev = EVENT_DATES.get(d)
        for s in range(1, 49):
            if d == DEMO_DATE and s >= NOW_SLOT:
                break
            want = None
            if d == DEMO_DATE and s == 1:
                soc = P["bess"]["soc_end_of_2026_08_18_pct"]
            if ev:
                es, ee = slot_of(ev["start"]), slot_of(ev["end"])
                if d == "2026-07-22":
                    if 19 <= s <= 22:
                        want = 1500.0      # unplanned morning discharge left the unit low
                    elif 25 <= s < es:
                        want = 0.0         # midday top-up switched off in manual mode
                if es <= s < ee:
                    want = float(ev.get("bess_kw", ev.get("actions", {}).get("BESS-01", 0.0)))
                elif s < es and d != "2026-07-22" and s >= es - 8:
                    want = -1200.0 if soc < 90 else 0.0   # operator pre-charge before the event
            if d == "2026-08-18" and 35 <= s <= 42:
                target = P["bess"]["soc_end_of_2026_08_18_pct"]
                left = 43 - s
                want = max(0.0, (soc - target) / 100 * BP.energy_kwh * BP.eff_discharge / (0.5 * left))
            if want is None:
                if 3 <= s <= 10 and soc < PP.v1_night_soc_cap:
                    want = -PP.v1_night_kw
                elif 25 <= s <= 30 and soc < PP.v1_midday_soc_cap:
                    want = -PP.v1_midday_kw
                elif imp[s - 1] > PP.v1_demand_limit_kw:
                    want = imp[s - 1] - PP.v1_demand_limit_kw
                else:
                    want = 0.0
            pw = bess_core.clip_power(soc, want, BP)
            new = bess_core.soc_step(soc, pw, BP)
            i0 = di * PER_DAY + (s - 1) * 6
            power[i0:i0 + 6] = pw
            soc_arr[i0:i0 + 6] = np.linspace(soc, new, 7)[:-1]
            soc = new
    return power, soc_arr, soc


BESS_P, BESS_SOC, SOC_NOW = build_bess()
IMPORT = GROSS_ACT * LOSS - PV_ACT - BESS_P

# ------------------------------------------------------------------------------------------------
# Writers
# ------------------------------------------------------------------------------------------------
SCHEMA: dict[str, dict] = {}


def write(name: str, df: pd.DataFrame, description: str, cols: list[tuple[str, str, str]]):
    assert list(df.columns) == [c[0] for c in cols], (name, list(df.columns))
    for c, t, _ in cols:
        if t == "FLOAT64":
            df[c] = df[c].astype(float).round(3)
        elif t == "INT64":
            df[c] = df[c].astype("int64")
        elif t == "BOOL":
            df[c] = df[c].astype(bool)
    df.to_csv(os.path.join(OUT, f"{name}.csv"), index=False)
    SCHEMA[name] = {"description": description, "columns": [{"name": c, "type": t, "description": d} for c, t, d in cols]}
    print(f"  {name:24s} {len(df):8d} rows")


def ts_str(i: int) -> str:
    return f"{DATE_OF[i]}T{fmt_min(int(MIN[i]))}"


def main(out_dir: str | None = None, schema_targets: list[str] | None = None):
    global OUT
    OUT = out_dir or OUT
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        if f.endswith(".csv"):
            os.remove(os.path.join(OUT, f))
    print(f"Generating demo data (seed {P['seed']}, now {P['demo_now']}, BESS SOC now {SOC_NOW:.1f} %)")

    # ---- assets / meters
    write("assets", pd.DataFrame(ASSETS), "Asset register: every load, generator and storage asset with its PLC tag, meter and flexibility class.", [
        ("asset_id", "STRING", "Asset identifier, e.g. AC-04"), ("asset_name", "STRING", "Descriptive name"),
        ("asset_class", "STRING", "Class used for load stacks and interlock rules"), ("area", "STRING", "Plant area"),
        ("criticality", "STRING", "critical / high / medium / low"), ("flex_class", "STRING", "none, trim, setpoint, tes_shift, storage, standby, batch, defer, dim, shift, generation"),
        ("flex_method", "STRING", "How flexibility is delivered and its limits"), ("rated_kw", "FLOAT64", "Rated electrical power kW"),
        ("flex_kw_nominal", "FLOAT64", "Nominal flexible kW (planning value; the edge engine decides)"), ("max_shift_h", "FLOAT64", "Maximum deferral in hours"),
        ("meter_id", "STRING", "ME96-series meter measuring this asset (shared meters cover several assets)"), ("plc_tag", "STRING", "MELSEC iQ-R style controller/device tag"),
        ("controller", "STRING", "Controller family")])
    write("meters", pd.DataFrame(METERS), "ME96-series meter register (57 meters).", [
        ("meter_id", "STRING", "Meter id M-01..M-57"), ("meter_model", "STRING", "Meter model family"), ("role", "STRING", "receiving_point / feeder / generation / storage"),
        ("asset_ids", "STRING", "Semicolon-separated asset ids on this meter"), ("asset_class", "STRING", "Asset class of the metered assets"),
        ("feeder", "STRING", "Feeder name"), ("comms", "STRING", "Communication path"), ("install_year", "INT64", "Installation year")])

    # ---- telemetry_5min (per meter), telemetry window only, up to now
    tel0 = (dt.date.fromisoformat(P["periods"]["telemetry_start"]) - dt.date.fromisoformat(START)).days * PER_DAY
    rng_i = np.arange(tel0, I_NOW)
    stuck_i = int((dt.datetime.fromisoformat(P["stuck_meter"]["start"]) - T0).total_seconds() // 60 // STEP)
    frames = []
    ts_col = np.array([ts_str(i) for i in rng_i])
    date_col = DATE_OF[rng_i]
    hour_col = (MIN[rng_i] // 60).astype(int)
    slot_col = (MIN[rng_i] // 30 + 1).astype(int)
    for m in METERS:
        ids = m["asset_ids"].split(";")
        if m["role"] == "receiving_point":
            kw = IMPORT[rng_i]
        elif m["role"] == "generation":
            kw = sum(ACT[a] for a in ids)[rng_i]
        elif m["role"] == "storage":
            kw = BESS_P[rng_i]
        else:
            kw = sum(ACT[a] for a in ids)[rng_i]
        kw = np.round(kw, 1)
        if m["meter_id"] == P["stuck_meter"]["meter_id"]:
            k0 = np.where(rng_i == stuck_i - 1)[0][0]
            kw = kw.copy()
            kw[k0 + 1:] = kw[k0]
        frames.append(pd.DataFrame({"ts": ts_col, "date": date_col, "hour": hour_col, "slot": slot_col, "meter_id": m["meter_id"],
                                    "asset_class": m["asset_class"], "kw": kw, "kwh": np.round(kw * STEP / 60.0, 3), "quality": "ok"}))
    write("telemetry_5min", pd.concat(frames, ignore_index=True), "5-minute average power per ME96 meter (2026-08-05 to now). Storage meter: + discharge / - charge.", [
        ("ts", "STRING", "Interval start, ISO local time JST"), ("date", "STRING", "Date"), ("hour", "INT64", "Hour 0-23"), ("slot", "INT64", "30-min slot 1-48"),
        ("meter_id", "STRING", "Meter id"), ("asset_class", "STRING", "Asset class of the meter"), ("kw", "FLOAT64", "Average kW over the interval"),
        ("kwh", "FLOAT64", "Energy kWh in the interval"), ("quality", "STRING", "Quality flag reported by the gateway")])

    # ---- site_load_30min
    rows = []
    for di, d in enumerate(DAYS):
        imp, gross, pv, bp = (slot_mean(a, di) for a in (IMPORT, GROSS_ACT * LOSS, PV_ACT, BESS_P))
        tt = slot_mean(T_AIR, di)
        ev_today = EVENT_DATES.get(d)
        for s in range(1, 49):
            if d == DEMO_DATE and s >= NOW_SLOT:
                break
            in_ev = bool(ev_today and slot_of(ev_today["start"]) <= s < slot_of(ev_today["end"]))
            rows.append({"date": d, "slot": s, "ts": ts_of(d, s), "hour": (s - 1) // 2, "month": d[:7], "day_type": DAYTYPE[d],
                         "baseline_eligible": DAYTYPE[d] == "weekday" and d not in EVENT_DATES and d != DEMO_DATE,
                         "import_kw": imp[s - 1], "import_kwh": imp[s - 1] * 0.5, "gross_load_kw": gross[s - 1], "pv_kw": pv[s - 1],
                         "bess_kw": bp[s - 1], "temp_c": tt[s - 1], "is_dr_event": in_ev, "event_id": ev_today["event_id"] if in_ev else ""})
    site = pd.DataFrame(rows)
    write("site_load_30min", site.copy(), "Receiving-point 30-minute load history (2026-06-01 to now), the basis for DR baselines and settlement.", [
        ("date", "STRING", "Date"), ("slot", "INT64", "30-min slot 1-48"), ("ts", "STRING", "Slot start"), ("hour", "INT64", "Hour"), ("month", "STRING", "YYYY-MM"),
        ("day_type", "STRING", "weekday / saturday / sunday / holiday / reduced"), ("baseline_eligible", "BOOL", "Weekday, not a holiday, reduced day or DR event day"),
        ("import_kw", "FLOAT64", "Average receiving-point import kW (after PV and BESS)"), ("import_kwh", "FLOAT64", "Import kWh in the slot"),
        ("gross_load_kw", "FLOAT64", "Sum of plant loads incl. transformer losses kW"), ("pv_kw", "FLOAT64", "PV output kW"),
        ("bess_kw", "FLOAT64", "BESS power kW (+ discharge, - charge)"), ("temp_c", "FLOAT64", "Outdoor temperature C"),
        ("is_dr_event", "BOOL", "Slot inside a DR event window"), ("event_id", "STRING", "DR event id when inside an event")])

    # ---- weather-driven forecasts for the demo day
    di_now = len(DAYS) - 1
    slots_all = list(range(1, 49))
    exp_asset_slot = {a: slot_mean(EXP[a], di_now) for a in LOAD_IDS}
    act_asset_slot = {a: slot_mean(ACT[a], di_now) for a in LOAD_IDS}
    gross_fc = {s: LOSS * sum((act_asset_slot if s < NOW_SLOT else exp_asset_slot)[a][s - 1] for a in LOAD_IDS) for s in slots_all}
    clear = slot_mean(EXP["_pv_clear_total"], di_now)
    band = P["pv"]["cloud_band_today"]
    p50f, p10f = {}, {}
    for s in slots_all:
        if s == band["deepest_slot"]:
            p50f[s], p10f[s] = band["p50_factor"], band["p10_factor"]
        elif band["start_slot"] <= s <= band["end_slot"]:
            p50f[s], p10f[s] = (1 + band["p50_factor"]) / 2 - 0.03, 0.40
        else:
            p50f[s], p10f[s] = 0.96, 0.84
    pv_act_slot = slot_mean(PV_ACT, di_now)
    pv50 = {s: (pv_act_slot[s - 1] if s < NOW_SLOT else clear[s - 1] * p50f[s]) for s in slots_all}
    pv10 = {s: (pv_act_slot[s - 1] if s < NOW_SLOT else clear[s - 1] * p10f[s]) for s in slots_all}
    pv90 = {s: (pv_act_slot[s - 1] if s < NOW_SLOT else clear[s - 1] * 1.0) for s in slots_all}

    # ---- PV forecasts (history issues at 06:00, demo day at 06:00 and 13:00)
    frows = []
    rf = rng("pv:forecast")
    for di, d in enumerate(DAYS):
        clear_d = slot_mean(EXP["_pv_clear_total"], di)
        act_d = slot_mean(PV_ACT, di)
        cday = CLOUD[d]
        for s in range(11, 39):
            if clear_d[s - 1] <= 1:
                continue
            if d == DEMO_DATE:
                for issued, fac in (("06:00", 0.5), ("13:00", 1.0)):
                    if issued == "06:00":
                        f50 = 0.96 - (0.96 - p50f[s]) * fac
                        f10 = 0.84 - (0.84 - p10f[s]) * fac
                    else:
                        f50, f10 = p50f[s], p10f[s]
                    frows.append({"issued_at": f"{d}T{issued}", "date": d, "slot": s, "ts": ts_of(d, s), "p10_kw": clear_d[s - 1] * f10,
                                  "p50_kw": clear_d[s - 1] * f50, "p90_kw": clear_d[s - 1], "clear_sky_kw": clear_d[s - 1],
                                  "model": "WeatherNext-class 64-member ensemble (simulated)"})
                continue
            spread = 0.07 + 0.30 * cday
            e = rf.normal(0, 0.07 + 0.22 * cday)
            p50 = min(clear_d[s - 1], max(0.0, act_d[s - 1] * (1 + e)))
            frows.append({"issued_at": f"{d}T06:00", "date": d, "slot": s, "ts": ts_of(d, s),
                          "p10_kw": max(0.0, p50 * (1 - spread)), "p50_kw": p50, "p90_kw": min(clear_d[s - 1], p50 * (1 + spread * 0.8)),
                          "clear_sky_kw": clear_d[s - 1], "model": "WeatherNext-class 64-member ensemble (simulated)"})
    pvf = pd.DataFrame(frows)
    pvf = pvf[pvf["date"] >= P["periods"]["telemetry_start"]].reset_index(drop=True)
    write("pv_forecast_30min", pvf, "PV output forecast per 30-min slot from a weather ensemble (p10/p50/p90), issued daily at 06:00 and at 13:00 on the demo day.", [
        ("issued_at", "STRING", "Forecast issue time"), ("date", "STRING", "Target date"), ("slot", "INT64", "Target slot"), ("ts", "STRING", "Slot start"),
        ("p10_kw", "FLOAT64", "10th percentile PV kW (downside)"), ("p50_kw", "FLOAT64", "Median PV kW"), ("p90_kw", "FLOAT64", "90th percentile PV kW"),
        ("clear_sky_kw", "FLOAT64", "Clear-sky PV kW for reference"), ("model", "STRING", "Forecast source")])

    pv_rows = []
    for i in rng_i:
        pv_rows.append((ts_str(i), DATE_OF[i], int(MIN[i] // 60), int(MIN[i] // 30 + 1), PV_ACT[i], EXP["_irr"][i], EXP["_tcell"][i]))
    write("pv_actual_5min", pd.DataFrame(pv_rows, columns=["ts", "date", "hour", "slot", "pv_kw", "irradiance_wm2", "module_temp_c"]),
          "Measured PV output, total of the three arrays (5-min).", [
              ("ts", "STRING", "Interval start"), ("date", "STRING", "Date"), ("hour", "INT64", "Hour"), ("slot", "INT64", "Slot"),
              ("pv_kw", "FLOAT64", "PV kW"), ("irradiance_wm2", "FLOAT64", "Plane-of-array irradiance W/m2"), ("module_temp_c", "FLOAT64", "Module temperature C")])

    # ---- JEPX prices
    mk = P["market"]
    shape25 = np.array(mk["fy2025_summer_hourly"])
    b = (mk["fy2026_summer_peak"] - mk["fy2026_summer_trough"]) / (shape25.max() - shape25.min())
    a = mk["fy2026_summer_trough"] - b * shape25.min()
    base_hour = a + b * shape25
    rj = rng("jepx")
    jrows = []
    jdays = pd.date_range(mk["jepx_start"], P["periods"]["jepx_end"], freq="D").strftime("%Y-%m-%d").tolist()
    lvl = 0.0
    reserve_today = {int(k): v for k, v in mk["reserve_margin_today"].items()}
    spike_today = {int(k): v for k, v in mk["spike_today_slots"].items()}

    def scarcity(r_pct):
        if r_pct >= mk["scarcity_B_pct"]:
            return 0.0
        if r_pct >= mk["scarcity_Bp_pct"]:
            return mk["scarcity_D"] * (mk["scarcity_B_pct"] - r_pct) / (mk["scarcity_B_pct"] - mk["scarcity_Bp_pct"])
        if r_pct >= mk["scarcity_A_pct"]:
            return mk["scarcity_D"] + (mk["scarcity_C"] - mk["scarcity_D"]) * (mk["scarcity_Bp_pct"] - r_pct) / (mk["scarcity_Bp_pct"] - mk["scarcity_A_pct"])
        return mk["scarcity_C"]

    for d in jdays:
        lvl = 0.55 * lvl + rj.normal(0, mk["daily_log_sd"])
        month_f = mk["june_level_factor"] if d[5:7] == "06" else mk["july_level_factor"] if d[5:7] == "07" else 1.07
        tmx = TMAX.get(d, 34.0)
        heat = max(0.0, tmx - 33.0)
        weekend = DAYTYPE.get(d, "weekday") in ("saturday", "sunday", "holiday", "reduced")
        for s in range(1, 49):
            h = (s - 1) // 2
            p = base_hour[h] * month_f * math.exp(lvl)
            ev_shape = math.exp(-((s - 37.5) ** 2) / 18.0)
            p += heat * 2.2 * ev_shape
            if d in mk["heatwave_evening_peaks"]:
                p = max(p, mk["heatwave_evening_peaks"][d] * (0.55 + 0.45 * ev_shape) if 30 <= s <= 44 else p)
            if weekend:
                p -= mk["weekend_discount"]
            p = max(0.01, p + rj.normal(0, 0.9))
            if d == DEMO_DATE and s in spike_today:
                p = spike_today[s]
            rm = reserve_today.get(s) if d == DEMO_DATE else (14.0 - 1.1 * heat * ev_shape + rj.normal(0, 1.2))
            rm = max(3.5, rm) if rm is not None else max(8.5, 12.5 - 0.9 * heat * ev_shape + rj.normal(0, 0.8))
            intr = p + rj.normal(mk["intraday_premium_mean"] * 0.3, mk["intraday_premium_sd"] * 0.5)
            if d == DEMO_DATE and s in spike_today:
                intr = p * (1 + mk["intraday_spike_premium_today"])
            imb = max(0.0, p + rj.normal(mk["imbalance_minus_spot_mean"], mk["imbalance_minus_spot_sd"] * 0.6))
            imb = min(mk["scarcity_C"], max(imb, scarcity(rm)))
            if d < DEMO_DATE or (d == DEMO_DATE and s < NOW_SLOT - 1):
                status = "settled"
            elif d == DEMO_DATE:
                status = "spot_cleared_imbalance_estimate"
            else:
                status = "spot_cleared"
            all_in = p * P["tariff"]["loss_factor"] + P["tariff"]["service_fee_jpy_kwh"] + P["tariff"]["wheeling_energy_jpy_kwh"] + \
                P["tariff"]["capacity_contribution_jpy_kwh"] + P["tariff"]["renewable_levy_jpy_kwh"]
            jrows.append({"date": d, "slot": s, "ts": ts_of(d, s), "hour": h, "area": mk["jepx_area"], "spot_jpy_kwh": round(p, 2),
                          "intraday_jpy_kwh": round(max(0.01, intr), 2), "imbalance_jpy_kwh": round(imb, 2), "reserve_margin_pct": round(rm, 1),
                          "plant_energy_price_jpy_kwh": round(all_in, 2), "price_status": status})
    jepx = pd.DataFrame(jrows)
    write("jepx_prices_30min", jepx.copy(), "JEPX Tokyo-area prices per 30-min slot (synthetic, calibrated to the FY2026 regime in MARKET_FACTS), with the wide-area reserve margin, imbalance price and the plant's all-in market-linked energy price.", [
        ("date", "STRING", "Delivery date"), ("slot", "INT64", "Slot 1-48"), ("ts", "STRING", "Slot start"), ("hour", "INT64", "Hour"), ("area", "STRING", "JEPX area"),
        ("spot_jpy_kwh", "FLOAT64", "Day-ahead spot area price JPY/kWh"), ("intraday_jpy_kwh", "FLOAT64", "Intraday (continuous) price JPY/kWh; latest indicative for future slots"),
        ("imbalance_jpy_kwh", "FLOAT64", "Imbalance price JPY/kWh (settled, or estimate for future slots) incl. scarcity adjustment, cap 200 until 2026-09-30"),
        ("reserve_margin_pct", "FLOAT64", "Wide-area reserve margin % (forecast for future slots)"),
        ("plant_energy_price_jpy_kwh", "FLOAT64", "Plant all-in energy price = spot x 1.04 + service fee + wheeling energy + capacity + renewable levy"),
        ("price_status", "STRING", "settled / spot_cleared_imbalance_estimate / spot_cleared")])
    J = {(r.date, r.slot): r for r in jepx.itertuples()}

    # ---- asset-level load forecast for the rest of the demo day
    lf = []
    for s in range(NOW_SLOT, 49):
        for aid in LOAD_IDS:
            if A_BY[aid]["asset_class"] == "thermal_storage":
                continue
            lf.append({"issued_at": f"{DEMO_DATE}T13:00", "date": DEMO_DATE, "slot": s, "ts": ts_of(DEMO_DATE, s), "asset_id": aid,
                       "asset_class": A_BY[aid]["asset_class"], "forecast_kw": exp_asset_slot[aid][s - 1]})
    write("load_forecast_30min", pd.DataFrame(lf), "Asset-level load forecast for the rest of the demo day (no DR action), issued 13:00.", [
        ("issued_at", "STRING", "Issue time"), ("date", "STRING", "Date"), ("slot", "INT64", "Slot"), ("ts", "STRING", "Slot start"), ("asset_id", "STRING", "Asset"),
        ("asset_class", "STRING", "Asset class"), ("forecast_kw", "FLOAT64", "Forecast average kW")])

    # ---- day-ahead nomination (made 2026-08-18 12:00, cooler temperature forecast, no cloud band, v1 BESS plan)
    temp_bias = 0.978
    gross_da = {s: gross_fc[s] * (temp_bias if s >= 20 else 0.995) for s in slots_all}
    pv_da = {s: clear[s - 1] * 0.95 for s in slots_all}
    da_inputs = bess_core.DayInputs(slots=slots_all, import_p50={s: gross_da[s] - pv_da[s] for s in slots_all},
                                    import_p10={s: gross_da[s] - pv_da[s] for s in slots_all}, nominated={s: gross_da[s] - pv_da[s] for s in slots_all},
                                    spot={s: J[(DEMO_DATE, s)].spot_jpy_kwh for s in slots_all}, imbalance={}, dr_slots=[], spike_slots=[],
                                    risk_slots=[], locked_slots=[])
    v1_da = bess_core.simulate("rule_based_v1", P["bess"]["soc_end_of_2026_08_18_pct"], da_inputs, "p50", BP, PP)
    nominated = {r["slot"]: r["import_after_bess_kw"] for r in v1_da}
    act_bess_slot = slot_mean(BESS_P, di_now)
    plan_rows = []
    for s in slots_all:
        is_act = s < NOW_SLOT
        plan_rows.append({"date": DEMO_DATE, "slot": s, "ts": ts_of(DEMO_DATE, s), "is_actual": is_act, "nominated_kw": nominated[s],
                          "forecast_gross_kw": gross_fc[s], "pv_p50_kw": pv50[s], "pv_p10_kw": pv10[s], "pv_p90_kw": pv90[s],
                          "forecast_import_p50_kw": gross_fc[s] - pv50[s], "forecast_import_p10pv_kw": gross_fc[s] - pv10[s],
                          "actual_bess_kw": act_bess_slot[s - 1] if is_act else 0.0,
                          "temp_forecast_c": slot_mean(T_AIR, di_now)[s - 1]})
    write("site_plan_30min", pd.DataFrame(plan_rows), "Demo-day 30-minute plan: day-ahead nomination (30-min plan-vs-actual balancing), load and PV forecasts, import before BESS for PV p50 and p10.", [
        ("date", "STRING", "Date"), ("slot", "INT64", "Slot"), ("ts", "STRING", "Slot start"), ("is_actual", "BOOL", "True for slots already metered (before 13:30)"),
        ("nominated_kw", "FLOAT64", "Day-ahead nominated import kW (plan submitted by 12:00 D-1, includes the rule_based_v1 BESS plan)"),
        ("forecast_gross_kw", "FLOAT64", "Forecast gross plant load incl. losses kW"), ("pv_p50_kw", "FLOAT64", "PV p50 kW (13:00 issue)"),
        ("pv_p10_kw", "FLOAT64", "PV p10 kW"), ("pv_p90_kw", "FLOAT64", "PV p90 kW"), ("forecast_import_p50_kw", "FLOAT64", "Import before BESS with PV p50"),
        ("forecast_import_p10pv_kw", "FLOAT64", "Import before BESS with PV p10 (downside)"), ("actual_bess_kw", "FLOAT64", "Metered BESS kW for past slots"),
        ("temp_forecast_c", "FLOAT64", "Outdoor temperature forecast C")])

    # ---- BESS state
    brows = []
    for i in rng_i:
        pw = BESS_P[i]
        soc = BESS_SOC[i]
        mode = "discharge" if pw > 1 else "charge" if pw < -1 else "idle"
        brows.append({"ts": ts_str(i), "date": DATE_OF[i], "hour": int(MIN[i] // 60), "slot": int(MIN[i] // 30 + 1), "soc_pct": soc, "power_kw": pw,
                      "mode": mode, "cell_temp_c": 27.0 + 0.12 * (T_AIR[i] - 25) + 0.0012 * abs(pw),
                      "available_discharge_kw": min(BP.power_kw, max(0.0, (soc - BP.soc_min_pct) / 100 * BP.energy_kwh * BP.eff_discharge / 0.5)),
                      "available_charge_kw": min(BP.power_kw, max(0.0, (BP.soc_max_pct - soc) / 100 * BP.energy_kwh / BP.eff_charge / 0.5)),
                      "policy": "rule_based_v1"})
    last = brows[-1]
    brows.append({**last, "ts": f"{DEMO_DATE}T{NOW_HHMM}", "slot": NOW_SLOT, "soc_pct": SOC_NOW, "hour": int(NOW_HHMM[:2]),
                  "available_discharge_kw": min(BP.power_kw, (SOC_NOW - BP.soc_min_pct) / 100 * BP.energy_kwh * BP.eff_discharge / 0.5),
                  "available_charge_kw": min(BP.power_kw, (BP.soc_max_pct - SOC_NOW) / 100 * BP.energy_kwh / BP.eff_charge / 0.5)})
    write("bess_state_5min", pd.DataFrame(brows), "BESS-01 state every 5 minutes (+ discharge / - charge), plus the 13:30 snapshot.", [
        ("ts", "STRING", "Interval start"), ("date", "STRING", "Date"), ("hour", "INT64", "Hour"), ("slot", "INT64", "Slot"), ("soc_pct", "FLOAT64", "State of charge % at interval start"),
        ("power_kw", "FLOAT64", "Power kW (+ discharge)"), ("mode", "STRING", "charge / discharge / idle"), ("cell_temp_c", "FLOAT64", "Average cell temperature C"),
        ("available_discharge_kw", "FLOAT64", "Discharge power available for 30 min within SOC limits"), ("available_charge_kw", "FLOAT64", "Charge power available for 30 min"),
        ("policy", "STRING", "Active dispatch policy")])

    # ---- compressor performance (daily)
    crow = []
    flows = EXP["_ac_flow"]
    for di, d in enumerate(DAYS):
        if d == DEMO_DATE:
            sl = slice(di * PER_DAY, I_NOW)
        else:
            sl = slice(di * PER_DAY, (di + 1) * PER_DAY)
        for i in range(1, 7):
            kw = ACT[f"AC-0{i}"][sl]
            fl = flows[i][sl]
            kwh = kw.sum() * STEP / 60
            air = (fl * STEP).sum()
            run_h = (kw > 5).sum() * STEP / 60
            crow.append({"date": d, "compressor_id": f"AC-0{i}", "runtime_h": run_h, "energy_kwh": kwh, "air_nm3": air,
                         "specific_power_kw_per_nm3min": kwh / (air / 60.0) if air > 0 else 0.0,
                         "avg_load_pct": 100 * fl.mean() / P["compressed_air"]["unit_capacity_nm3min"],
                         "header_pressure_mpa": P["compressed_air"]["header_pressure_mpa"] + (0.004 if d < "2026-08-01" else 0.0) - 0.003 * (i == 4) * (di / len(DAYS))})
    write("compressor_perf", pd.DataFrame(crow), "Daily compressed-air performance per compressor (energy, delivered air, specific power).", [
        ("date", "STRING", "Date (demo day is partial to 13:30)"), ("compressor_id", "STRING", "Compressor"), ("runtime_h", "FLOAT64", "Loaded running hours"),
        ("energy_kwh", "FLOAT64", "Electrical energy kWh"), ("air_nm3", "FLOAT64", "Delivered air Nm3 (header flow meter)"),
        ("specific_power_kw_per_nm3min", "FLOAT64", "kW per Nm3/min; lower is better"), ("avg_load_pct", "FLOAT64", "Average load %"),
        ("header_pressure_mpa", "FLOAT64", "Average header pressure MPa")])

    # ---- production schedule (demo day and the day before)
    prow = []
    def status_of(st_abs, en_abs):
        now_abs = abs_min(DEMO_DATE, NOW_HHMM)
        return "completed" if en_abs <= now_abs else "running" if st_abs <= now_abs else "planned"

    def add_job(asset, job, lot, product, st_abs, en_abs, kw, interruptible, deferrable_h, notes, due=""):
        st = T0 + dt.timedelta(minutes=st_abs)
        en = T0 + dt.timedelta(minutes=en_abs)
        d = st.strftime("%Y-%m-%d")
        if d < "2026-08-18" or d > DEMO_DATE:
            return
        prow.append({"schedule_id": f"SCH-{asset}-{st.strftime('%m%d%H%M')}", "date": d, "asset_id": asset, "asset_class": A_BY[asset]["asset_class"],
                     "job_type": job, "lot_id": lot, "product": product, "start_ts": st.strftime("%Y-%m-%dT%H:%M"), "end_ts": en.strftime("%Y-%m-%dT%H:%M"),
                     "start_slot": slot_of(st.strftime("%H:%M")), "end_slot": slot_of(en.strftime("%H:%M")) if en.strftime("%Y-%m-%d") == d else 49,
                     "planned_kw": kw, "interruptible": interruptible, "deferrable_h": deferrable_h, "status": status_of(st_abs, en_abs),
                     "customer_due": due, "notes": notes})

    for fid, batches in FURN.items():
        for k, (s, e) in enumerate(batches):
            if s < abs_min("2026-08-18", "00:00"):
                continue
            st = T0 + dt.timedelta(minutes=s)
            lot = f"LOT-{fid[-2:]}-{st.strftime('%m%d')}-{st.strftime('%H%M')}"
            note = "Non-interruptible sintering profile once started. Start may move up to 3 h in planning."
            if fid == "FN-02" and st.strftime("%Y-%m-%dT%H:%M") == "2026-08-19T17:10":
                note = "Customer lot for EV inverter modules, due 08:00 tomorrow. Non-interruptible once started."
            planned = status_of(s, e) == "planned"
            add_job(fid, "sinter_batch", lot, "SiC power module 1200 V class", s, e, 830.0, False, 3.0 if planned else 0.0, note, "2026-08-20T08:00")
        if fid == "FN-03":
            add_job(fid, "idle_window", "", "", abs_min(DEMO_DATE, "13:30"), abs_min(DEMO_DATE, "20:30"), 130.0, True, 0.0,
                    "No batch until 20:30 (awaiting substrates). Reheat from standby takes 90 min.")
    for bid, cycles in BURN.items():
        for (s, e) in cycles:
            if s < abs_min("2026-08-18", "00:00"):
                continue
            st = T0 + dt.timedelta(minutes=s)
            add_job(bid, "burn_in_cycle", f"BI-LOT-{bid[-1]}-{st.strftime('%m%d%H%M')}", "Automotive ECU (brake-by-wire)", s, e, 112.0, False, 3.0,
                    "Cycle start may be deferred up to 3 h; a started cycle must not pause (test validity).", "2026-08-21T12:00")
    for i in range(1, 7):
        for d in ("2026-08-18", DEMO_DATE):
            for sh, (a_, b_) in enumerate([("06:00", "14:00"), ("14:00", "22:00"), ("22:00", "23:59")], start=1):
                if i >= 5 and sh == 3:
                    continue
                s_abs, e_abs = abs_min(d, a_), abs_min(d, b_) + (1 if b_ == "23:59" else 0)
                add_job(f"LN-0{i}", "production_run", f"RUN-L{i}-{d[5:7]}{d[8:]}-S{sh}",
                        "SiC power module" if i <= 4 else "Automotive ECU", s_abs, e_abs, 720.0 if i <= 4 else 455.0, False, 0.0,
                        "Continuous production. No line stops without MES release.")
    for i in range(7, 11):
        add_job(f"EV-{i:02d}", "ev_charge_session", "", "Delivery van", abs_min(DEMO_DATE, "16:30"), abs_min(DEMO_DATE, "19:30"), 50.0, True, 3.0,
                "Vans return 16:30; must reach 80 % SOC by 07:00 departure.", "2026-08-20T07:00")
    sched = pd.DataFrame(prow).sort_values(["date", "asset_id", "start_ts"]).reset_index(drop=True)
    write("production_schedule", sched, "Production and utility schedule for 2026-08-18 and the demo day (planning view from MES).", [
        ("schedule_id", "STRING", "Schedule row id"), ("date", "STRING", "Start date"), ("asset_id", "STRING", "Asset"), ("asset_class", "STRING", "Asset class"),
        ("job_type", "STRING", "sinter_batch / burn_in_cycle / production_run / ev_charge_session / idle_window"), ("lot_id", "STRING", "Lot or run id"),
        ("product", "STRING", "Product"), ("start_ts", "STRING", "Start"), ("end_ts", "STRING", "End"), ("start_slot", "INT64", "Start slot"), ("end_slot", "INT64", "End slot (exclusive)"),
        ("planned_kw", "FLOAT64", "Planned average kW"), ("interruptible", "BOOL", "Can be interrupted once started"), ("deferrable_h", "FLOAT64", "Maximum start deferral h"),
        ("status", "STRING", "completed / running / planned (relative to 13:30)"), ("customer_due", "STRING", "Customer due time"), ("notes", "STRING", "Planner notes")])

    # ---- PLC tag snapshot (edge live state at 13:30)
    tn = f"{DEMO_DATE}T{NOW_HHMM}"
    flows_now = {i: float(flows[i][I_NOW - 1]) for i in range(1, 7)}
    ca = P["compressed_air"]
    tags = [
        ("COMP-HDR", "iQR-UTIL2/D5100", "header_pressure_mpa", ca["header_pressure_mpa"], "MPa", "Measured at the header"),
        ("COMP-HDR", "iQR-UTIL2/D5102", "header_setpoint_mpa", ca["header_setpoint_mpa"], "MPa", "Cascade controller setpoint"),
        ("COMP-HDR", "iQR-UTIL2/D5104", "air_demand_nm3min", float(EXP["_air_demand"][I_NOW - 1]), "Nm3/min", "Plant air demand"),
        ("COMP-HDR", "iQR-UTIL2/D5106", "system_volume_m3", ca["system_volume_m3"], "m3", "Receivers plus header"),
        ("COMP-HDR", "iQR-UTIL2/D5108", "far_end_drop_mpa", 0.03, "MPa", "Pressure drop to the far end of the header"),
    ]
    for i in range(1, 7):
        tags.append((f"AC-0{i}", f"iQR-UTIL2/D{5000 + 10 * i}", "flow_nm3min", flows_now[i], "Nm3/min", "running" if flows_now[i] > 0.5 else "standby (auto-start ready)"))
        tags.append((f"AC-0{i}", f"iQR-UTIL2/D{5001 + 10 * i}", "capacity_nm3min", ca["unit_capacity_nm3min"], "Nm3/min", ""))
        tags.append((f"AC-0{i}", f"iQR-UTIL2/D{5002 + 10 * i}", "specific_power", float(ACT[f"AC-0{i}"][I_NOW - 1] / max(flows_now[i], 0.1)) if flows_now[i] > 0.5 else 0.0, "kW/(Nm3/min)", ""))
    for i in range(1, 7):
        prod_zone = i <= 4
        tags.append((f"CR-AHU-0{i}", f"iQR-HVAC1/D{2001 + 10 * i}", "airflow_pct", 100.0 if prod_zone else 96.0, "% of design", ""))
        tags.append((f"CR-AHU-0{i}", f"iQR-HVAC1/D{2002 + 10 * i}", "min_airflow_pct", 100.0 if prod_zone else 85.0, "% of design",
                     "Production zone: product exposed" if prod_zone else "Support zone"))
    tes = P["tes"]
    tags += [
        ("TES-01", "iQR-UTIL1/D4101", "tes_soc_pct", tes["soc_now_pct"], "%", "Stratified tank charge"),
        ("TES-01", "iQR-UTIL1/D4102", "tes_capacity_kwh_th", tes["capacity_kwh_th"], "kWh-th", ""),
        ("CHW-PLANT", "iQR-UTIL1/D4001", "chw_supply_temp_c", tes["chw_supply_now_c"], "C", ""),
        ("CHW-PLANT", "iQR-UTIL1/D4003", "chillers_running", float(sum(1 for i in range(1, 5) if ACT[f"CH-0{i}"][I_NOW - 1] > 5)), "count", ""),
        ("CHW-PLANT", "iQR-UTIL1/D4005", "cop", float(6.3 - 0.09 * (T_AIR[I_NOW - 1] - 25)), "", "Plant COP at current wet-bulb"),
        ("FN-01", "iQR-FN1/D6011", "batch_active", 1.0, "bool", "Batch 13:40-16:10"),
        ("FN-01", "iQR-FN1/D6013", "batch_committed", 0.0, "bool", "Next batch 19:20 not yet committed"),
        ("FN-01", "iQR-FN1/D6015", "next_batch_start_min", float(hm("19:20")), "min of day", "19:20"),
        ("FN-01", "iQR-FN1/D6017", "reheat_lead_min", 90.0, "min", "Standby to process temperature"),
        ("FN-02", "iQR-FN2/D6021", "batch_active", 0.0, "bool", "Holding between batches"),
        ("FN-02", "iQR-FN2/D6023", "batch_committed", 1.0, "bool", "Sinter paste printed 13:05 for the 17:10 batch; recipe loaded"),
        ("FN-02", "iQR-FN2/D6025", "committed_batch_start_min", float(hm("17:10")), "min of day", "17:10"),
        ("FN-02", "iQR-FN2/D6027", "committed_batch_end_min", float(hm("19:40")), "min of day", "19:40"),
        ("FN-03", "iQR-FN3/D6031", "batch_active", 0.0, "bool", "Idle, awaiting substrates"),
        ("FN-03", "iQR-FN3/D6033", "next_batch_start_min", float(hm("20:30")), "min of day", "20:30"),
        ("FN-03", "iQR-FN3/D6035", "reheat_lead_min", 90.0, "min", "Standby to process temperature"),
        ("WW-PIT", "iQR-WWT1/D9001", "pit_level_pct", 42.0, "%", ""),
        ("WW-PIT", "iQR-WWT1/D9003", "minutes_to_high_alarm_no_pumping", 75.0, "min", "At the current inflow"),
        ("OF-ZONE", "iQR-BMS1/D3001", "zone_setpoint_c", 26.0, "C", "Office zones"),
        ("LT-ZONE", "iQR-BMS1/D3101", "dim_level_pct", 100.0, "%", ""),
        ("BESS-01", "iQR-BESS1/D9501", "soc_pct", SOC_NOW, "%", ""),
        ("BESS-01", "iQR-BESS1/D9503", "cell_temp_c", 30.8, "C", ""),
        ("PLANT", "iQR-PLANT/D100", "max_step_kw_per_min", 2500.0, "kW/min", "Sequencing limit for aggregate load steps"),
    ]
    for i in range(1, 9):
        cyc = BURN[f"BI-0{i}"]
        now_abs = abs_min(DEMO_DATE, NOW_HHMM)
        running = [c for c in cyc if c[0] <= now_abs < c[1]]
        nxt = [c for c in cyc if c[0] > now_abs]
        tags.append((f"BI-0{i}", f"iQR-TEST1/D{8001 + 10 * i}", "cycle_running", 1.0 if running else 0.0, "bool", ""))
        tags.append((f"BI-0{i}", f"iQR-TEST1/D{8003 + 10 * i}", "next_cycle_start_min", float((nxt[0][0] - abs_min(DEMO_DATE, "00:00"))) if nxt else -1.0, "min of day", ""))
    for i in range(7, 11):
        tags.append((f"EV-{i:02d}", f"iQR-LOG1/D{8201 + 10 * i}", "arrival_soc_pct", 38.0 + 3 * (i - 7), "%", "Forecast at 16:30 return"))
        tags.append((f"EV-{i:02d}", f"iQR-LOG1/D{8203 + 10 * i}", "required_soc_pct", 80.0, "%", "By 07:00"))
    write("plc_tags_snapshot", pd.DataFrame([{"ts": tn, "asset_id": a, "plc_tag": t, "tag_name": n, "value": float(v), "unit": u, "note": note}
                                             for (a, t, n, v, u, note) in tags]),
          "Edge live state at 13:30 read from MELSEC iQ-R PLC tags via OPC UA (the edge interlock engine's view).", [
              ("ts", "STRING", "Snapshot time"), ("asset_id", "STRING", "Asset or subsystem"), ("plc_tag", "STRING", "PLC device tag"), ("tag_name", "STRING", "Tag name"),
              ("value", "FLOAT64", "Value"), ("unit", "STRING", "Unit"), ("note", "STRING", "Note")])

    # ---- interlock rules
    rules = [
        ("IR-CR-01", "cleanroom_hvac", "*", "airflow_pct", ">=", 85.0, "% of design", "hard",
         "Clean-room air handlers must hold the design air-change rate and the pressure cascade. Below the floor, particle counts rise within minutes and exposed SiC die and wafers lose yield.",
         "Plant QA spec QS-CR-003 (ISO 14644 design basis); interlock rationale sheet s.2"),
        ("IR-CR-02", "cleanroom_hvac", "CR-AHU-01;CR-AHU-02;CR-AHU-03;CR-AHU-04", "airflow_pct", ">=", 100.0, "% of design", "hard",
         "Production-zone air handlers stay at 100 % while product is exposed. Only support-zone units (CR-AHU-05/06) may trim to 85 %.",
         "Plant QA spec QS-CR-003; interlock rationale sheet s.2"),
        ("IR-UT-01", "critical_utility", "UPW-01;N2-01;IT-01;PCW-01;PCW-02;VAC-01;VAC-02;CR-EXF-*", "curtailment_kw", "==", 0.0, "kW", "hard",
         "Ultra-pure water, nitrogen, process vacuum, process cooling, safety exhaust and MES servers are never curtailed.",
         "Plant energy policy s.3; interlock rationale sheet s.1"),
        ("IR-CA-01", "compressor", "*", "header_pressure_mpa", ">=", 0.60, "MPa", "hard",
         "Pneumatic actuators on the lines and clean-room isolation valves fault below 0.60 MPa at the far end of the header; lines stop.",
         "Utility design basis UDB-CA-01; interlock rationale sheet s.3"),
        ("IR-CA-02", "compressor", "*", "n_minus_1_capacity_nm3min", ">=", 1.0, "x demand", "hard",
         "Available compressor capacity minus the largest unit must still cover plant air demand (N-1). Standby units count as available only if auto-start ready.",
         "Utility design basis UDB-CA-01; interlock rationale sheet s.3"),
        ("IR-CA-03", "compressor", "*", "header_setpoint_mpa", ">=", 0.65, "MPa", "hard",
         "Setpoint may be trimmed only down to 0.65 MPa so the far end (0.03 MPa drop) stays above 0.60 MPa with margin.",
         "Utility design basis UDB-CA-01; interlock rationale sheet s.3"),
        ("IR-FN-01", "furnace", "*", "power_reduction_during_batch_kw", "==", 0.0, "kW", "hard",
         "Sintering and reflow profiles are non-interruptible. Any power reduction during a batch scraps the lot and can crack substrates.",
         "Process spec PS-SNT-07; interlock rationale sheet s.4"),
        ("IR-FN-02", "furnace", "*", "committed_batch_move", "==", 0.0, "bool", "hard",
         "Once sinter paste is printed the batch is committed at the PLC (pot-life clock running). The edge cannot move or defer it; only the production supervisor can release it in MES.",
         "Process spec PS-SNT-07; plant energy policy s.4"),
        ("IR-FN-03", "furnace", "*", "standby_clear_of_next_batch_min", ">=", 90.0, "min", "hard",
         "An idle furnace may drop to standby only if it can reheat (90 min) before its next batch.",
         "Process spec PS-SNT-07; interlock rationale sheet s.4"),
        ("IR-CH-01", "chiller", "*", "chw_supply_temp_c", "<=", 8.5, "C", "hard",
         "Chilled-water supply above 8.5 C loses clean-room humidity control (dew point) and process tool cooling margin.",
         "Utility design basis UDB-CHW-02; interlock rationale sheet s.5"),
        ("IR-CH-02", "thermal_storage", "TES-01", "tes_soc_end_pct", ">=", 15.0, "%", "hard",
         "Thermal storage must keep 15 % for a chiller trip ride-through.", "Utility design basis UDB-CHW-02"),
        ("IR-CH-03", "chiller", "*", "chillers_running", ">=", 2.0, "count", "hard",
         "At least two chillers stay online (N+1 for the clean room).", "Utility design basis UDB-CHW-02"),
        ("IR-LN-01", "production_line", "*", "curtailment_kw", "==", 0.0, "kW", "hard",
         "No line stops or slowdowns from energy actions. A line may only be released by the production supervisor in MES.",
         "Plant energy policy s.4"),
        ("IR-BI-01", "burn_in", "*", "start_deferral_h", "<=", 3.0, "h", "hard",
         "A burn-in cycle start may be deferred by up to 3 h without breaching test lead time.", "Reliability test procedure RT-ECU-11"),
        ("IR-BI-02", "burn_in", "*", "pause_mid_cycle", "==", 0.0, "bool", "hard",
         "A running burn-in cycle must not pause; the test is invalidated and must restart.", "Reliability test procedure RT-ECU-11"),
        ("IR-EV-01", "ev_charger", "EV-07;EV-08;EV-09;EV-10", "soc_by_departure_pct", ">=", 80.0, "%", "soft",
         "Vans must reach 80 % by 07:00. Deferral is allowed while the charge still fits before departure.", "Logistics policy LG-02"),
        ("IR-EV-02", "ev_charger", "EV-01;EV-02;EV-03;EV-04;EV-05;EV-06", "defer_during_shift_change", "==", 0.0, "bool", "soft",
         "Forklift chargers are not deferred across shift changes.", "Logistics policy LG-02"),
        ("IR-LT-01", "lighting", "*", "dim_pct", "<=", 30.0, "%", "soft",
         "Office and warehouse lighting may be dimmed by at most 30 % (desk and aisle illuminance policy).", "Plant energy policy s.5"),
        ("IR-OF-01", "office_hvac", "*", "zone_setpoint_c", "<=", 28.0, "C", "soft",
         "Office zones may be raised to 28 C at most.", "Plant energy policy s.5"),
        ("IR-WW-01", "wastewater", "*", "hold_min", "<=", 60.0, "min", "hard",
         "Lift pumps may hold for at most 60 min before the pit reaches its high alarm.", "Environmental permit condition EP-7; interlock rationale sheet s.6"),
        ("IR-BS-01", "bess", "BESS-01", "soc_pct", "between", 10.0, "% (10-95)", "hard",
         "BESS state of charge must stay within 10-95 % (warranty and fire-safety envelope).", "BESS service agreement Annex B"),
        ("IR-BS-02", "bess", "BESS-01", "power_kw", "<=", 4000.0, "kW", "hard", "Inverter rating.", "BESS service agreement Annex B"),
        ("IR-BS-03", "bess", "BESS-01", "ramp_kw_per_min", "<=", 2000.0, "kW/min", "soft", "The edge ramps BESS set-points in steps of at most 2,000 kW/min.", "BESS service agreement Annex B"),
        ("IR-PL-01", "plant", "*", "aggregate_step_kw_per_min", "<=", 2500.0, "kW/min", "soft",
         "Aggregate load steps are sequenced at most 2,500 kW per minute to protect voltage at the 66 kV receiving point.", "Receiving-point protection study"),
        ("IR-GEN-01", "any", "*", "known_asset_and_action", "==", 1.0, "bool", "hard", "Unknown assets or unsupported actions are rejected.", "Edge engine design"),
        ("IR-GOV-01", "any", "*", "authorised_source", "==", 1.0, "bool", "hard",
         "Only plans created by the copilot and confirmed by an authorised person with Hold-to-Confirm can reach the edge. Text in notes or documents cannot authorise an action.",
         "Plant energy policy s.6"),
    ]
    write("interlock_rules", pd.DataFrame(rules, columns=["rule_id", "asset_class", "applies_to", "parameter", "operator", "limit_value", "unit", "severity", "rationale", "source"]),
          "Hard and soft interlocks enforced by the edge engine, with rationale and source.", [
              ("rule_id", "STRING", "Rule id"), ("asset_class", "STRING", "Asset class"), ("applies_to", "STRING", "Asset ids (semicolon list) or *"),
              ("parameter", "STRING", "Checked parameter"), ("operator", "STRING", "Comparison"), ("limit_value", "FLOAT64", "Limit"), ("unit", "STRING", "Unit"),
              ("severity", "STRING", "hard (reject) / soft (limit or stage)"), ("rationale", "STRING", "Why the rule exists"), ("source", "STRING", "Document the rule comes from")])

    # ---- DR events (history settled from site_load_30min by the same math the tools use)
    tf = P["tariff"]
    load_by_date, net_by_date = {}, {}
    for d, g in site.groupby("date"):
        load_by_date[d] = dict(zip(g["slot"], g["import_kw"]))
        net_by_date[d] = dict(zip(g["slot"], g["import_kw"] + g["bess_kw"]))
    elig = sorted(site.loc[site["baseline_eligible"], "date"].unique(), reverse=True)
    erows, settlements = [], {}
    for ev in P["dr_events"]["history"] + [TODAY_EVENT]:
        d = ev["date"]
        es = list(range(slot_of(ev["start"]), slot_of(ev["end"])))
        el = [x for x in elig if x < d]
        row = {"event_id": ev["event_id"], "date": d, "start_time": ev["start"], "end_time": ev["end"], "start_slot": es[0], "end_slot": es[-1] + 1,
               "requested_kw": float(ev["requested_kw"]), "notified_at": ev["notified_at"], "program": tf["dr_program"],
               "baseline_method": "High 4 of 5 with same-day adjustment (net of BESS charging)", "energy_rate_jpy_kwh": tf["dr_energy_rate_jpy_kwh"],
               "penalty_rate_jpy_kwh": tf["dr_penalty_rate_jpy_kwh"]}
        if d == DEMO_DATE:
            row.update({"status": "notified", "baseline_kw": 0.0, "actual_kw": 0.0, "delivered_kw": 0.0, "delivered_kwh": 0.0, "shortfall_kwh": 0.0,
                        "payment_jpy": 0.0, "penalty_jpy": 0.0, "net_settlement_jpy": 0.0,
                        "notes": "Aggregator dispatch received 13:00. Tokyo area reserve margin forecast below 6 % in the evening."})
        else:
            bl = dr_math.high_4_of_5_baseline(load_by_date, net_by_date, el, es, net_by_date[d])
            st = dr_math.settle_event(ev["requested_kw"], bl["baseline_kw"], {s: load_by_date[d][s] for s in es},
                                      tf["dr_energy_rate_jpy_kwh"], tf["dr_penalty_rate_jpy_kwh"], tf["dr_payment_cap_ratio"])
            settlements[ev["event_id"]] = (bl, st)
            row.update({"status": "settled", "baseline_kw": bl["baseline_avg_kw"], "actual_kw": st["actual_avg_kw"], "delivered_kw": st["delivered_avg_kw"],
                        "delivered_kwh": st["delivered_kwh"], "shortfall_kwh": st["shortfall_kwh"], "payment_jpy": st["payment_jpy"], "penalty_jpy": st["penalty_jpy"],
                        "net_settlement_jpy": st["net_jpy"], "notes": ev.get("note", "Delivered above the request.")})
        erows.append(row)
    dre = pd.DataFrame(erows)
    write("dr_events", dre, "Demand-response events from the aggregator: three settled summer events and today's dispatch.", [
        ("event_id", "STRING", "Event id"), ("date", "STRING", "Event date"), ("start_time", "STRING", "Start HH:MM"), ("end_time", "STRING", "End HH:MM"),
        ("start_slot", "INT64", "First slot"), ("end_slot", "INT64", "End slot (exclusive)"), ("requested_kw", "FLOAT64", "Requested reduction kW"),
        ("notified_at", "STRING", "Dispatch time"), ("program", "STRING", "Program"), ("baseline_method", "STRING", "Baseline method"),
        ("energy_rate_jpy_kwh", "FLOAT64", "Payment per delivered kWh"), ("penalty_rate_jpy_kwh", "FLOAT64", "Penalty per kWh short"),
        ("status", "STRING", "settled / notified"), ("baseline_kw", "FLOAT64", "Average baseline kW"), ("actual_kw", "FLOAT64", "Average actual import kW"),
        ("delivered_kw", "FLOAT64", "Average delivered reduction kW"), ("delivered_kwh", "FLOAT64", "Delivered kWh"), ("shortfall_kwh", "FLOAT64", "Shortfall kWh"),
        ("payment_jpy", "FLOAT64", "Energy payment JPY"), ("penalty_jpy", "FLOAT64", "Penalty JPY"), ("net_settlement_jpy", "FLOAT64", "Payment minus penalty JPY"),
        ("notes", "STRING", "Notes")])

    # ---- tariff / contract parameters
    trows = [
        ("contracted_demand_kw", P["plant"]["contracted_demand_kw"], "kW", "tariff", "Contracted demand at the 66 kV receiving point"),
        ("loss_factor", tf["loss_factor"], "x", "tariff", "Spot price multiplier for losses (ESTIMATE, MARKET_FACTS s.5.4)"),
        ("service_fee_jpy_kwh", tf["service_fee_jpy_kwh"], "JPY/kWh", "tariff", "Retailer service fee (ESTIMATE 1-3 JPY/kWh, MARKET_FACTS s.5.4)"),
        ("wheeling_energy_jpy_kwh", tf["wheeling_energy_jpy_kwh"], "JPY/kWh", "tariff", "TEPCO PG extra-high-voltage wheeling energy charge until 2026-10-31 (MARKET_FACTS s.5.1)"),
        ("wheeling_basic_jpy_kw_month", tf["wheeling_basic_jpy_kw_month"], "JPY/kW-month", "tariff", "TEPCO PG extra-high-voltage wheeling basic charge until 2026-10-31 (MARKET_FACTS s.5.1)"),
        ("capacity_contribution_jpy_kwh", tf["capacity_contribution_jpy_kwh"], "JPY/kWh", "tariff", "Capacity contribution pass-through FY2026 Tokyo (ESTIMATE, MARKET_FACTS s.5.2)"),
        ("renewable_levy_jpy_kwh", tf["renewable_levy_jpy_kwh"], "JPY/kWh", "tariff", "FY2026 renewable energy surcharge (MARKET_FACTS s.5.3)"),
        ("demand_charge_jpy_kw_month", tf["demand_charge_jpy_kw_month"], "JPY/kW-month", "tariff", "Demand charge on the monthly maximum 30-min demand (demo assumption; level from MARKET_FACTS s.5.4)"),
        ("deviation_band_pct", tf["deviation_band_pct"], "%", "tariff", "30-min deviation band vs the nominated plan; excess passed through at the imbalance price"),
        ("gate_closure_min", tf["gate_closure_min"], "min", "tariff", "Plan revisions allowed until 60 min before delivery (MARKET_FACTS s.3)"),
        ("imbalance_price_cap_jpy_kwh", P["market"]["scarcity_C"], "JPY/kWh", "market", "Scarcity imbalance cap until 2026-09-30 (MARKET_FACTS s.3)"),
        ("imbalance_price_cap_from_2026_10_01_jpy_kwh", P["market"]["scarcity_C_from_2026_10_01"], "JPY/kWh", "market", "Cap from 2026-10-01 (MARKET_FACTS s.3)"),
        ("dr_energy_rate_jpy_kwh", tf["dr_energy_rate_jpy_kwh"], "JPY/kWh", "dr", "Aggregator payment per delivered kWh (demo assumption)"),
        ("dr_penalty_rate_jpy_kwh", tf["dr_penalty_rate_jpy_kwh"], "JPY/kWh", "dr", "Penalty per kWh short of the request (demo assumption)"),
        ("dr_availability_jpy_kw_month", tf["dr_availability_jpy_kw_month"], "JPY/kW-month", "dr", "Availability payment July-September (demo assumption)"),
        ("dr_contracted_capacity_kw", tf["dr_contracted_capacity_kw"], "kW", "dr", "Contracted DR capacity"),
        ("dr_payment_cap_ratio", tf["dr_payment_cap_ratio"], "x", "dr", "Payment capped at the requested kWh"),
        ("gain_share_pct", tf["gain_share_pct"], "%", "gain_share", "Equipment vendor share of verified Auto-DR savings (contract range 20-30 %)"),
        ("baas_fee_jpy_month", tf["baas_fee_jpy_month"], "JPY/month", "baas", "BESS-as-a-Service monthly fee (4 MW / 8 MWh, managed)"),
        ("bess_degradation_jpy_kwh", P["bess"]["degradation_jpy_per_kwh"], "JPY/kWh", "baas", "Wear cost per kWh discharged (ESTIMATE, MARKET_FACTS s.12)"),
        ("bess_round_trip_efficiency", P["bess"]["eff_charge"] * P["bess"]["eff_discharge"], "x", "baas", "AC round trip (MARKET_FACTS s.12)"),
    ]
    write("tariff_contract", pd.DataFrame([{"contract_id": tf["contract_id"], "parameter": a, "value": float(v), "unit": u, "category": c, "description": ds}
                                           for (a, v, u, c, ds) in trows]),
          "Tariff, DR, gain-share and BESS-as-a-Service contract parameters.", [
              ("contract_id", "STRING", "Contract id"), ("parameter", "STRING", "Parameter name"), ("value", "FLOAT64", "Value"), ("unit", "STRING", "Unit"),
              ("category", "STRING", "tariff / market / dr / gain_share / baas"), ("description", "STRING", "Description and source")])

    # ---- savings ledger (Jan-Jul 2026). July is derived from site data and settled events.
    rl = rng("ledger")
    lrows = []
    jmon = jepx.copy()
    jmon["month"] = jmon["date"].str[:7]
    site_m = site.merge(jepx[["date", "slot", "plant_energy_price_jpy_kwh", "imbalance_jpy_kwh"]], on=["date", "slot"], how="left")
    for mth in P["periods"]["ledger_months"]:
        winter = mth in ("2026-01", "2026-02", "2026-03")
        fy26 = mth >= "2026-04"
        if mth == "2026-07":
            sm = site_m[site_m["month"] == mth]
            no_bess_peak = (sm["import_kw"] + sm["bess_kw"]).max()
            peak = sm["import_kw"].max()
            dem = (no_bess_peak - peak) * tf["demand_charge_jpy_kw_month"]
            energy = (sm["bess_kw"] * 0.5 * sm["plant_energy_price_jpy_kwh"]).sum() - (sm["bess_kw"].clip(lower=0) * 0.5).sum() * P["bess"]["degradation_jpy_per_kwh"]
            shift = 1.15e6 + rl.normal(0, 0.1e6)
            jul_events = dre[(dre["date"].str[:7] == mth) & (dre["status"] == "settled")]
            items = [
                ("demand_charge_avoided", dem, True, f"Monthly peak {peak:,.0f} kW vs {no_bess_peak:,.0f} kW without BESS peak limiting x {tf['demand_charge_jpy_kw_month']} JPY/kW-month", ""),
                ("energy_cost_avoided", energy + shift, True, "BESS time shift valued at the plant's all-in slot price, net of wear cost, plus scheduled load shifting (burn-in, EV, TES)", ""),
                ("dr_availability", tf["dr_availability_jpy_kw_month"] * tf["dr_contracted_capacity_kw"], True, "Availability payment for 3,000 kW contracted DR capacity", ""),
                ("dr_energy_payment", jul_events["payment_jpy"].sum(), True, "Aggregator energy payments for settled events", ";".join(jul_events["event_id"])),
                ("dr_penalty", -jul_events["penalty_jpy"].sum(), True, "Under-delivery penalties", ";".join(jul_events.loc[jul_events["penalty_jpy"] > 0, "event_id"])),
                ("imbalance_avoided", 0.52e6 + rl.normal(0, 0.05e6), True, "Deviation kept inside the 7.5 % band by BESS following (estimated from band excursions avoided)", ""),
                ("efficiency_savings", 0.78e6 + rl.normal(0, 0.05e6), False, "Compressor setpoint and LED retrofits (SaaS analytics; not gain-share eligible)", ""),
            ]
        else:
            peak_red = (1700 if winter else 1500) + rl.normal(0, 120)
            spread_scale = 1.9 if fy26 else 1.0
            items = [
                ("demand_charge_avoided", peak_red * tf["demand_charge_jpy_kw_month"], True, f"Estimated monthly peak reduction {peak_red:,.0f} kW from BESS peak limiting", ""),
                ("energy_cost_avoided", (1.05e6 * spread_scale + rl.normal(0, 0.12e6)) + 0.6e6, True, "BESS time shift at the market-linked price plus load shifting", ""),
                ("imbalance_avoided", (0.28e6 if winter else 0.36e6) + rl.normal(0, 0.04e6), True, "Deviation kept inside the band (estimated)", ""),
                ("efficiency_savings", (0.55e6 if winter else 0.68e6) + rl.normal(0, 0.04e6), False, "Efficiency measures (not gain-share eligible)", ""),
            ]
        for (cat, amt, elig_, basis, evs) in items:
            lrows.append({"month": mth, "category": cat, "amount_jpy": round(float(amt)), "gain_share_eligible": elig_, "basis": basis, "event_ids": evs})
    write("savings_ledger", pd.DataFrame(lrows), "Monthly verified savings by category, January to July 2026 (July derived from site data and settled DR events).", [
        ("month", "STRING", "YYYY-MM"), ("category", "STRING", "Savings category"), ("amount_jpy", "FLOAT64", "Amount JPY (negative = cost)"),
        ("gain_share_eligible", "BOOL", "Counts toward the Auto-DR gain share"), ("basis", "STRING", "How the amount was computed"), ("event_ids", "STRING", "DR events included")])

    # ---- edge decision log (history)
    drows = []
    k = 0
    hist_actions = {
        "DR-20260708": [("BESS-01", "discharge", 1500, "ACCEPT", "IR-BS-01", "SOC path 88 % -> 49 % within 10-95 %"),
                        ("TES-01", "tes_discharge", 600, "ACCEPT", "IR-CH-02", "TES end SOC 41 % >= 15 %"),
                        ("BI-03", "defer_start", 110, "ACCEPT", "IR-BI-01", "Start deferred 2 h (limit 3 h)"),
                        ("EV-07", "defer_charge", 50, "ACCEPT", "IR-EV-01", "Charge fits before 07:00"),
                        ("LN-03", "curtail", 300, "REJECT", "IR-LN-01", "No line stops without MES release")],
        "DR-20260722": [("BESS-01", "discharge", 1400, "LIMIT", "IR-BS-01", "SOC 29 % at start; energy runs out after about 60 min"),
                        ("TES-01", "tes_discharge", 450, "ACCEPT", "IR-CH-02", "TES end SOC 52 %"),
                        ("FN-01", "curtail", 850, "REJECT", "IR-FN-01", "Batch overran into the window; non-interruptible profile"),
                        ("BI-02", "pause", 110, "REJECT", "IR-BI-02", "Mid-cycle pause invalidates the test")],
        "DR-20260806": [("BESS-01", "discharge", 1800, "ACCEPT", "IR-BS-01", "SOC path 92 % -> 45 %"),
                        ("TES-01", "tes_discharge", 650, "ACCEPT", "IR-CH-02", "TES end SOC 38 %"),
                        ("AC-04", "standby", 45, "ACCEPT", "IR-CA-02", "N-1 capacity 210 Nm3/min >= demand 176"),
                        ("CR-AHU-02", "trim", 60, "REJECT", "IR-CR-02", "Production-zone airflow held at 100 %"),
                        ("OF-AHU-01", "setpoint_shift", 45, "ACCEPT", "IR-OF-01", "26 C -> 28 C")],
    }
    lat = rng("latency")
    for ev_id, acts in hist_actions.items():
        ev = next(e for e in P["dr_events"]["history"] if e["event_id"] == ev_id)
        for (aid, act, kw, verdict, rule, reason) in acts:
            k += 1
            t = dt.datetime.fromisoformat(ev["notified_at"]) + dt.timedelta(minutes=12)
            drows.append({"decision_id": f"EDG-{k:05d}", "ts": t.strftime("%Y-%m-%dT%H:%M"), "event_id": ev_id, "plan_id": f"PLAN-{ev_id[3:]}-H",
                          "asset_id": aid, "action": act, "requested_kw": float(kw), "granted_kw": float(0 if verdict == "REJECT" else kw * (0.7 if verdict == "LIMIT" else 1.0)),
                          "verdict": verdict, "rule_id": rule, "reason": reason, "latency_ms": round(float(lat.uniform(2.1, 9.5)), 2), "edge_node": "gdc-edge-atsugi-01"})
    write("edge_decisions", pd.DataFrame(drows), "Edge interlock decision log for past DR events (new simulations are appended at runtime).", [
        ("decision_id", "STRING", "Decision id"), ("ts", "STRING", "Decision time"), ("event_id", "STRING", "DR event"), ("plan_id", "STRING", "Plan id"),
        ("asset_id", "STRING", "Asset"), ("action", "STRING", "Requested action"), ("requested_kw", "FLOAT64", "Requested kW"), ("granted_kw", "FLOAT64", "Granted kW"),
        ("verdict", "STRING", "ACCEPT / LIMIT / REJECT"), ("rule_id", "STRING", "Deciding rule"), ("reason", "STRING", "Reason"),
        ("latency_ms", "FLOAT64", "Simulated edge decision latency ms"), ("edge_node", "STRING", "Edge node")])

    # ---- schema files
    schema = {"dataset_default": "melco_edge_to_grid_demo", "generated_by": "data/generate.py", "seed": P["seed"], "demo_now": P["demo_now"], "tables": SCHEMA}
    targets = schema_targets if schema_targets is not None else [os.path.join(HERE, "schema.json"), os.path.join(ROOT, "factory_copilot", "schema.json")]
    for path in targets:
        with open(path, "w") as f:
            json.dump(schema, f, indent=1)
    total = sum(os.path.getsize(os.path.join(OUT, f)) for f in os.listdir(OUT))
    print(f"Wrote {len(SCHEMA)} tables, {total / 1e6:.1f} MB")
    for ev_id, (bl, st) in settlements.items():
        print(f"  {ev_id}: baseline {bl['baseline_avg_kw']:.0f} kW (adj {bl['same_day_adjustment_kw']:+.0f}), delivered {st['delivered_avg_kw']:.0f} kW, "
              f"payment {st['payment_jpy']:,} JPY, penalty {st['penalty_jpy']:,} JPY")


if __name__ == "__main__":
    main()
