"""Calibration targets, each tagged with its MARKET_FACTS.md section and verification status.

Source document: docs/research/MARKET_FACTS.md (as of 2026-09-26) in the showcase repository. Figures tagged
VERIFIED were read from primary sources or computed from official JEPX / TEPCO PG / imbalance-system CSVs by the
research analyst. ESTIMATE figures are the analyst's inference and are used only as simulator assumptions.
Everything the simulator produces from these targets is CALIBRATED SYNTHETIC DATA, never a reported figure.
Items marked LAB-ASSUMPTION are this lab's own modelling choices (no source), stated in docs/SCENARIO_AND_DATA.md.
"""
from __future__ import annotations

# --- JEPX spot, Tokyo area (MARKET_FACTS 1.2-1.5) --------------------------------------------------------
TOKYO_ANNUAL_MEAN = {2023: 12.20, 2024: 13.66, 2025: 12.45}            # VERIFIED (computed) 1.2
TOKYO_FY2026_TO_DATE_MEAN = 20.36                                        # VERIFIED (computed) 1.2, Apr 1-Sep 27
SYSTEM_ANNUAL_MEAN = {2023: 10.74, 2024: 12.31, 2025: 11.08}           # VERIFIED 1.2 (JEPX business reports)
TOKYO_PREMIUM_OVER_SYSTEM = {2024: 1.37, 2025: 1.40, 2026: 3.75}        # VERIFIED (computed) 1.2
TOKYO_PREMIUM_SLOT_SHARE = 0.90                                          # VERIFIED (computed) 1.2 (~90% of slots differ)
TOKYO_MONTHLY_FY2025 = [11.5, 11.2, 13.0, 13.9, 13.2, 12.9, 13.1, 11.8, 11.2, 12.1, 11.2, 14.4]   # Apr..Mar, 1.3
TOKYO_MONTHLY_FY2026_H1 = [20.1, 18.0, 20.0, 19.9, 21.2, 23.4]          # Apr..Sep (Sep to 27th), 1.3
WEEKDAY_WEEKEND = {2024: (14.21, 12.28), 2025: (13.03, 11.00)}           # VERIFIED (computed) 1.3
HOURLY_SHAPE_FY2025 = {                                                  # VERIFIED (computed) 1.4, JPY/kWh, hour 0..23
    "spring": [12.5, 12.3, 12.3, 12.5, 12.7, 12.9, 12.8, 11.8, 11.0, 10.8, 9.5, 8.8, 8.1, 9.4, 10.4, 11.8, 13.6, 15.0, 16.0, 15.6, 14.9, 14.3, 14.1, 13.2],
    "summer": [11.7, 11.3, 11.2, 11.2, 11.2, 11.1, 10.8, 10.7, 10.7, 11.7, 11.5, 11.9, 11.3, 13.7, 14.9, 16.0, 18.3, 18.5, 18.3, 17.1, 15.6, 13.9, 13.4, 12.2],
    "autumn": [11.4, 11.1, 11.1, 11.3, 11.4, 11.7, 12.6, 12.0, 11.3, 11.3, 10.8, 10.6, 10.1, 11.3, 12.3, 14.0, 16.4, 16.1, 15.5, 15.0, 14.4, 13.0, 12.5, 11.7],
    "winter": [10.5, 10.4, 10.4, 10.3, 10.4, 10.7, 12.4, 13.9, 12.9, 11.5, 10.2, 9.3, 8.8, 9.3, 9.8, 11.0, 13.3, 14.2, 14.0, 13.5, 13.3, 12.6, 11.9, 11.0],
}
FY2026_SPRING_TROUGH_PEAK = (11.8, 29.7)                                 # VERIFIED (computed) 1.4
SLOT_QUANTILES = {2024: (8.50, 13.14, 20.78, 49.65), 2025: (7.96, 11.53, 19.43, 45.01)}  # p5, p50, p95, max, 1.5
FY2026_QUANTILES = (10.27, 19.34, 32.39, 64.28)                          # p5, p50, p95, max (to date), YAML
DAILY_MEAN_SD_FY2025 = 2.31                                              # 1.5
DAILY_RANGE_MEAN_FY2025 = 9.45                                           # 1.5
WITHIN_DAY_SD_FY2025 = 2.66                                              # 1.5
DAILY_RANGE_MEAN_FY2026 = 22.03                                          # 1.5
DOD_LOG_RETURN_SD = {2024: 0.159, 2025: 0.145, 2026: 0.169}              # 1.5
LAG1_AUTOCORR, LAG48_AUTOCORR = 0.94, 0.66                               # 1.5 (FY2025)
PRICE_NETLOAD = {2025: (2.04, 0.357), 2026: (1.23, 0.699)}               # intercept, slope JPY/kWh per GW, 1.5
NETLOAD_MEAN_FY2025_GW = 29.2                                            # 1.5
FLOOR_SLOTS_TOKYO_FY2025 = {"Feb": 1, "Mar": 33, "Apr": 35, "May": 36}   # 0.01 JPY/kWh slots, 1.4
MAX_TOKYO = {2023: 50.00, 2024: 49.65, 2025: 45.01}                      # 1.6
PRICE_FLOOR, PRICE_CAP_SIM = 0.01, 999.99                                # 1.1 (cap is an ESTIMATE / technical limit)
PRICE_TICK, LOT_MWH = 0.01, 0.05                                         # 1.1: tick 0.01 JPY/kWh, lot 50 kWh
STRESS_EVENTS = {                                                        # 1.6
    "jan2021_coldsnap_lng": {"peak": 252.0, "daily_mean_peak": 167.0, "days": 21},
    "mar2022_tightness": {"plateau": 80.0, "daily_mean_peak": 76.7},
    "jun2022_heat": {"peak": 200.0, "daily_mean_peak": 86.1},
}

# --- Intraday (MARKET_FACTS 2) ---------------------------------------------------------------------------
INTRADAY_MINUS_TOKYO = (-0.71, 1.92)            # mean, SD, national intraday vs Tokyo area price FY2025
INTRADAY_MINUS_SYSTEM = {2025: (0.68, 1.71), 2026: (1.07, 4.63)}
INTRADAY_IN_SLOT_RANGE = {2025: 8.80, 2026: 20.0}
INTRADAY_AVG_MWH_PER_SLOT = 388                 # national, FY2025

# --- Imbalance (MARKET_FACTS 3) ---------------------------------------------------------------------------
IMBALANCE_SINGLE_PRICE = True                   # VERIFIED (computed): surplus == shortage price in every slot checked
IMB_MINUS_SPOT = {2024: (None, 7.03), 2025: (-0.68, 4.93), 2026: (None, 9.42)}   # mean, SD
IMB_MINUS_SPOT_Q_FY2025 = (-7.67, 5.72)         # p5, p95
IMB_ZERO_SHARE_FY2025 = 0.040                   # share of slots at 0.00
IMB_MAX = {2024: 194.11, 2025: 131.49}
SCARCITY_B, SCARCITY_B_PRIME, SCARCITY_A = 0.10, 0.08, 0.03   # reserve-margin points (fractions)
SCARCITY_D = {"to_2026_09_30": 45.0, "from_2026_10_01": 50.0}
SCARCITY_C = {"to_2026_09_30": 200.0, "from_2026_10_01": 300.0}
SCARCITY_SWITCH_DATE = "2026-10-01"
CUMULATIVE_RULE = {"trigger_price": 200.0, "trigger_slots": 30, "window_days": 7, "reduced_cap": 100.0, "release_price": 100.0}

# --- Cost stack, TEPCO PG area (MARKET_FACTS 5) -----------------------------------------------------------
WHEELING = {  # JPY/kW-month basic, JPY/kWh energy (VERIFIED 5.1)
    "HV": {"basic": 653.87, "basic_from_2026_11": 762.44, "energy": 1.84, "energy_pre_2024_04": 2.37},
    "EHV": {"basic": 423.39, "basic_from_2026_11": 446.25, "energy": 0.91, "energy_pre_2024_04": 1.33},
}
CAPACITY_PRICE_TOKYO_JPY_KW_YR = {2024: 14137, 2025: 3495, 2026: 5834, 2027: 9555}   # VERIFIED 5.2
CAPACITY_BURDEN_TOKYO_BN_JPY = {2024: 492.18, 2025: 134.30, 2026: 252.83}             # VERIFIED 5.2
CAPACITY_PER_KWH_TOKYO = {2024: 1.84, 2025: 0.50, 2026: 0.94}                        # ESTIMATE 5.2
RENEWABLE_SURCHARGE = {2023: 1.40, 2024: 3.49, 2025: 3.98, 2026: 4.18}               # VERIFIED 5.3 (pass-through)
NFC_PRICE = {"FIT": 0.40, "nonFIT_renewable": 1.21}                                  # VERIFIED 6.2 (FY2026 R1)
LOSS_FACTOR = 1.04                                                                   # ESTIMATE 5.4
SERVICE_FEE_RANGE = (1.0, 3.0)                                                       # ESTIMATE 5.4
TEPCO_EP_HV_PLANS_FY2026 = {                                                         # VERIFIED 5.4
    "basic_plan": {"basic": 2530, "energy": 17.43},
    "zero_market_adj": {"basic": 2720, "energy": 17.21},
    "market_linked": {"basic": 1500, "energy_day": 15.18, "energy_night": 15.00, "base_spot": 11.60, "coeff": 1.142},
}

# --- Tokyo-area demand and solar (MARKET_FACTS 7) ---------------------------------------------------------
AREA_DEMAND_TWH = {2024: 267.5, 2025: 268.3}                                         # VERIFIED 7 (TEPCO HD basis)
AREA_DEMAND_TWH_ERIA_FY2025 = 281.4                                                  # VERIFIED (computed) eria_jukyu basis
PEAK_GW = {2023: 55.25, 2024: 56.99, 2025: 57.54}                                    # summer peaks, VERIFIED 7
WINTER_PEAK_GW = {2023: 49.90, 2024: 48.37, 2025: 50.29}
MIN_DEMAND_GW_FY2025 = 18.30
DEMAND_HOURLY_GW_FY2025 = {                                                          # VERIFIED (computed) 7
    "summer": [29.9, 27.9, 26.9, 26.6, 26.6, 27.0, 29.0, 33.0, 38.5, 42.7, 44.6, 45.9, 45.9, 46.7, 46.6, 46.2, 45.6, 43.8, 42.6, 41.3, 39.2, 37.0, 34.9, 32.7],
    "winter": [30.1, 28.9, 28.5, 28.5, 28.9, 30.5, 33.8, 36.9, 39.0, 39.3, 38.1, 37.1, 35.6, 35.7, 35.5, 35.8, 37.1, 38.7, 39.2, 38.8, 38.1, 36.6, 34.6, 32.5],
    "spring": [22.9, 21.9, 21.9, 22.2, 22.4, 22.5, 23.0, 24.4, 26.7, 28.6, 29.2, 29.5, 28.7, 29.2, 29.1, 29.0, 29.3, 29.4, 30.1, 29.7, 28.6, 27.2, 25.9, 24.5],
}
PV_HOURLY_GW_FY2025 = {                                                              # VERIFIED (computed) 7
    "summer": [0, 0, 0, 0, 0, 0.4, 2.0, 4.7, 7.4, 9.7, 11.2, 12.1, 12.0, 10.8, 8.9, 6.4, 3.5, 1.2, 0.1, 0, 0, 0, 0, 0],
    "spring": [0, 0, 0, 0, 0, 0.3, 1.5, 3.8, 6.2, 8.2, 9.5, 10.1, 9.8, 8.9, 7.2, 5.0, 2.6, 0.7, 0, 0, 0, 0, 0, 0],
    "winter": [0, 0, 0, 0, 0, 0, 0, 1.0, 4.2, 7.3, 9.6, 10.6, 10.5, 9.1, 6.6, 3.4, 0.7, 0, 0, 0, 0, 0, 0, 0],
}
PV_MAX_GW = {2025: 17.04, 2026: 17.84}
PV_SHARE_FY2025 = 0.092
SUMMER_2025_SUPPLY_GW = 67.42                                                        # at the 57.54 GW peak (85% usage)

# --- Battery economics (MARKET_FACTS 12) ------------------------------------------------------------------
BESS_RTE = 0.85                                        # VERIFIED (NREL ATB 2024)
BESS_DEGRADATION_JPY_KWH = 8.0                         # ESTIMATE (recommended sim value 7-10)
SPREAD_2H = {2023: 8.66, 2024: 8.77, 2025: 8.28, 2026: 18.35}   # mean daily top-4 minus bottom-4, VERIFIED (computed)
SPREAD_4H = {2023: 7.66, 2024: 7.89, 2025: 7.25, 2026: 15.41}
PERFECT_FORESIGHT_2H_JPY_KWH_CAP_YR = {2024: 2190, 2025: 2080}   # ESTIMATE 12

# --- DR (MARKET_FACTS 8) ----------------------------------------------------------------------------------
CAPACITY_MARKET_DR_CALL_HOURS = 3                      # VERIFIED 8 (must deliver for 3 h when called)
