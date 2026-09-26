# Scenario and data: Kanto Balance Group (fictional), calibrated synthetic

Everything in this lab is **calibrated synthetic data** about a **fictional** retail balance group. No customer, site,
bid or run in this repository is real. Calibration targets come from `docs/research/MARKET_FACTS.md` (as of 2026-09-26;
cited below as "MF section"). Figures there tagged VERIFIED were read from primary sources or computed from official
JEPX / TEPCO PG / imbalance-system CSVs; ESTIMATE figures are analyst inferences and are used here only as simulator
assumptions. Anything this lab chose without a source is marked **LAB-ASSUMPTION**.

Regenerate everything (deterministic, about 4 s): `python data/generate.py` then `python data/make_figures.py`.

## 1. The scenario universe

| Item | Value | Basis |
|---|---|---|
| Balance group | Kanto Balance Group (KBG), retail BG in the TEPCO PG (Tokyo) area | fictional |
| Customers | 1,200 HV/EHV C&I customers in the train cohort (6.0 TWh/yr, mean net load ~690 MW); separate 401-customer holdout cohorts (holdout, holdout2) | LAB-ASSUMPTION (segment table below) |
| Solar | 40 MW PPA, 6 sites (Ibaraki, Chiba, Tochigi), output follows TEPCO-area solar with local noise | shape MF 7 |
| Battery | 8 sites, 60 MW / 180 MWh (four 2 h, four 4 h), dispatched as one fleet, BESS-as-a-Service | RTE 85% MF 12 (NREL ATB) |
| Market | JEPX day-ahead (single price, 48 products, gate 10:00 D-1), intraday (continuous, gate H-1), single-price imbalance with scarcity curve | MF 1.1, 2, 3 |
| History | FY2023-FY2025 (2023-04-01 to 2026-03-31), 52,608 half-hours | calibrated to MF 1-3, 7 |
| FY2026 | Monte Carlo scenario banks: 64 train + 64 holdout paths x 17,520 half-hours | MF 1.2-1.6, 3, 5 |

Segments (train cohort; all parameters LAB-ASSUMPTIONS, see `segments` table): data_center 36, semiconductor_fab 14,
auto_parts 170, cold_storage 90, office 300, retail_chain 190, hospital 80 (essential), water_utility 45 (essential),
university 50, logistics 150, hotel 75. Voltage follows the TEPCO PG classes (MF 5.1): EHV at 2,000 kW or more.

## 2. Market model (`energy_lab/sim/market.py`)

The chain is physical first, statistical second, then calibrated exactly where MARKET_FACTS gives a number:

1. **Temperature (Tokyo).** Approximate JMA 1991-2020 monthly normals + 0.8 C recent warming (LAB-ASSUMPTION, not in
   MARKET_FACTS), AR(1) daily anomalies (sd 1.6 C summer, 2.0 C winter), diurnal cosine, explicit heat and cold events.
   D-1 forecast error 1.3 C (daily) and H-1 error 0.35 C (LAB-ASSUMPTION) drive every forecast error downstream.
2. **TEPCO-area demand.** The FY2025 hour-of-day profiles for summer, winter and spring (MF 7, VERIFIED computed) blended
   by month, weekday/holiday/New Year/Obon factors, temperature response (2.1 GW per C summer daytime, 1.25 GW per C
   winter), AR model noise. D-1 and H-1 forecasts use the forecast temperatures.
3. **Solar.** FY2025 seasonal profiles (MF 7) x Beta-distributed daily clearness (rainy June), capacity growth
   0.90 / 0.95 / 1.00 / 1.05 for FY2023-26 (LAB-ASSUMPTION; FY2025 max 17.04 GW, FY2026 17.84 GW in MF 7).
4. **Wide-area reserve margin.** Monthly available capacity x (1 - AR outages) - unit trips + 85% of solar, divided by
   demand. The capacity scale is **bisected so that slots with RM < 8% equal the count of imbalance prices >= 45 JPY/kWh**
   (38 in FY2025, MF 3), and the tail below 8% is compressed so RM < 6.2% matches the >= 100 count.
5. **Tokyo spot price.** Seasonal hour shape (MF 1.4) x monthly level (MF 1.3) x weekday factor x net-load anomaly
   elasticity (MF 1.5 slope 0.357 JPY/kWh per GW converts to elasticity ~1) with convexity x daily AR level with upward
   jumps x slot AR noise x scarcity multiplier from RM. Spring solar-surplus **0.01 JPY/kWh floor events** are placed in
   the lowest net-load midday non-working slots with the MF 1.4 monthly counts (Feb 1, Mar 33, Apr 35, May 36 in FY2025).
   Each month is then rescaled so its mean equals the target **exactly** (FY2025 monthly means MF 1.3; FY2023/FY2024 use
   the FY2025 monthly profile scaled to their VERIFIED annual means, MF 1.2). Stress prices saturate near the 252 JPY/kWh
   record (MF 1.6).
6. **System price.** Tokyo minus a positive gamma premium in ~90% of slots (MF 1.2: premium 1.37-1.40 JPY/kWh).
7. **Intraday (Tokyo delivery, at H-1).** Mid = spot + 0.25 + 0.35 x the system-imbalance signal + noise; half-spread
   0.25 + 3%; KBG-accessible liquidity ~30 MWh per slot (about 8% of the national 388 MWh average, MF 2). The +0.25 premium
   and the liquidity cap are LAB-ASSUMPTIONS: MARKET_FACTS gives national intraday vs system (+0.68) and vs Tokyo (-0.71)
   because area intraday data is not yet published.
8. **Imbalance (single price, MF 3).** Base = spot + k x (system H-1 forecast error in GW) + fat-tailed noise, 0 JPY/kWh
   when the system is long with high solar, bounded by max(C, spot), then floored by the regulatory **scarcity curve**:
   0 at RM >= 10%, linear to D at 8%, linear to C at 3%, flat below (interpolation is the MF 3 ESTIMATE). C = 200 / D = 45
   until 2026-09-30; **C = 300 / D = 50 from 2026-10-01**, with the cumulative-price rule (>= 30 slots at >= 200 in 7 days
   -> cap 100). The simulator also supports dual shortage/surplus prices; Tokyo instances use the single price because
   MARKET_FACTS verified surplus = shortage in every slot checked (FY2024-FY2026).

### FY2026 scenario banks (`energy_lab/sim/scenarios.py`)

The tariff book is priced as of 2026-03-16 for FY2026. Regimes: baseline (FY2025 x U(0.92, 1.12)), moderate fuel shock
(x U(1.25, 1.50)), severe (x U(1.55, 1.90), shape stretch matching the FY2026 spring trough/peak 11.8/29.7, MF 1.4) and,
holdout only, **realised_like** (Apr-Sep = FY2026 to-date monthly means 20.1 / 18.0 / 20.0 / 19.9 / 21.2 / 23.4, MF 1.3;
Oct-Mar = FY2025 x U(1.45, 1.85)). Stress events: **cold snap with LNG shortage** (Jan 2027, 14-21 days, -4.5 C,
daily-mean peak U(110, 170) JPY/kWh; Jan-2021 peak daily mean 167, MF 1.6) and **heat dome** (Jul-Aug, daily-mean peak
U(55, 90); 2022 daily means 69-86, MF 1.6).

| Bank | Mix | Stress probability | Role |
|---|---|---|---|
| train (seeds 101 + 7919k) | 55% baseline, 30% moderate, 15% severe | cold 8%, heat 12% | the desk's forward view; forward curve = its mean |
| holdout (seeds 202 + 7919k) | 40% realised-like, 20% baseline, 15% moderate, 25% severe | cold 25%, heat 25% | unseen, harsher: the FY2026 regime shift |

Every FY2026 path switches the imbalance cap on 2026-10-01 and prices the November 2026 wheeling increase.

## 3. Customer portfolio (`energy_lab/sim/portfolio.py`)

Each segment archetype defines a weekday 24-hour shape, a non-working and shutdown level, monthly factors, cooling and
heating sensitivity, 30-minute and monthly forecast deviation, flexible share and window, procurement style mix
(tender / negotiated / auto-renew), elasticity multiplier, risk-aversion range, term preference, DR share and cost,
green-product probability, weather correlation of deviations, forecast discipline, and relationship value. Each
customer perturbs the archetype with three numbers (amplitude, slot shift, level), so the evaluator **reconstructs every
load deterministically** from `segment_archetypes` (11 x 38 day types x 48) plus per-customer parameters.

Representative days: 12 months x {working, non-working, shutdown (New Year / Obon)} + heat-dome working + cold-snap
working = 38 types, **weighted by each scenario's own day counts**, so stress days carry their own prices and loads.

**Visible vs hidden.** `customers_*` holds only what a pricing desk would know (segment, voltage, kW, energy, load factor,
shape cost, wheeling and capacity per kWh, flexibility, forecast error, credit, tenure, procurement style, noisy survey
proxies for risk appetite and DR interest, a noisy competitor quote). `customer_behaviour_*` holds the hidden behaviour
the evaluator uses (true elasticity, inertia, risk aversion, competitor reference, DR cost, discipline, relationship
value). Candidates never see the hidden table.

## 4. Cost stack (`cost_stack` table)

| Component | Value | Status | Treatment |
|---|---|---|---|
| Wheeling HV basic | 653.87 JPY/kW-month to Oct 2026, 762.44 from Nov 2026 | VERIFIED MF 5.1 | cost, recovered via demand charge |
| Wheeling HV energy | 1.84 JPY/kWh (2.37 before Apr 2024) | VERIFIED MF 5.1 | cost |
| Wheeling EHV | 423.39 / 446.25 JPY/kW-month + 0.91 JPY/kWh | VERIFIED MF 5.1 | cost |
| Capacity contribution | 252.83 bn JPY Tokyo burden / 55.0 GW Tokyo peak = ~4,597 JPY/kW-yr of coincident peak | DERIVED from MF 5.2 + 7 | cost by coincident peak (MF 5.2 ESTIMATE ~0.94 JPY/kWh average) |
| Loss factor | 1.04 HV, 1.03 EHV | ESTIMATE MF 5.4 | procurement = consumption x loss factor |
| NFC (non-FIT renewable) | 1.21 JPY/kWh | VERIFIED MF 6.2 (FY2026 R1) | cost for green products |
| Balancing overhead | 0.25 JPY/kWh | LAB-ASSUMPTION | cost |
| Renewable surcharge | 4.18 JPY/kWh (FY2026) | VERIFIED MF 5.3 | **pure pass-through: excluded from margin and offers** |
| Imbalance | single price with scarcity curve | VERIFIED MF 3 | settled per slot (trading) / covariance cost (tariff) |
| BESS degradation | 8 JPY/kWh discharged | ESTIMATE MF 12 | trading cost |

## 5. Assets

Battery: 60 MW / 180 MWh, RTE 85% (split sqrt(0.85) each way), SOC 10-95%, <= 2 cycles/day, warranty 450 cycles/yr
(LAB-ASSUMPTIONS typical of LFP warranties), degradation 8 JPY/kWh discharged (MF 12 recommends 7-10). At FY2024-FY2025
2-hour spreads (8.3-8.8 JPY/kWh, MF 12) pure arbitrage barely clears wear, which is realistic and shows up in the results.

## 6. Evaluator instances (`data/instances`, gitignored)

| Instance | Content |
|---|---|
| tariff_pricing_train | 1,200 customers x 64 train scenarios: rep-day prices [64, 38, 48], day counts, temperature anomalies, flex spreads, DR value per kW by slot, imbalance covariance, forward curve, visible features JSON, market JSON |
| tariff_pricing_holdout | 401 unseen customers x 64 unseen holdout scenarios, same market JSON (pricing-time information); used by tariff runs 1-2, then **burned** (it informed evaluator v3) |
| tariff_pricing_holdout2 | fresh 401-customer cohort (seed 31) x 64 fresh holdout-bank scenarios (seed 505, same regime mix); the tariff holdout from run 3 on |
| jepx_trading_train | 96 days of FY2024 in 12 seasonal 8-day blocks: realised demand/PV/spot/intraday quotes/imbalance/RM, D-1 and H-1 forecasts, 14-day price history |
| jepx_trading_holdout | 96 days of FY2025 + 8 heat-dome + 8 cold-snap/LNG stress days from a severe FY2026 path |

Instances are written with fixed zip metadata and hashed by content (`energy_lab/sim/npz.py`); `data/instances/manifest.json`
records the SHA-256 and every evaluation re-verifies it. Regenerating on the same platform reproduces the hashes and the
baseline locks; on a different CPU/libm the lock may refuse, which is the intended behaviour (re-lock deliberately).

## 7. Calibration evidence

Generated by `data/generate.py` into the `calibration` table (targets are MARKET_FACTS values).

<!-- CALIBRATION_TABLE -->
| FY | Metric | Synthetic | MARKET_FACTS | Rel. error | MF section |
|---|---|---|---|---|---|
| 2023 | tokyo_mean | 12.21 | 12.2 | +0.1% | 1.2 |
| 2023 | system_mean | 10.75 | 10.74 | +0.1% | 1.2 |
| 2023 | max | 48.62 | 50 | -2.8% | 1.5/1.6 |
| 2024 | tokyo_mean | 13.67 | 13.66 | +0.1% | 1.2 |
| 2024 | system_mean | 12.3 | 12.31 | -0.1% | 1.2 |
| 2024 | p5 | 8.84 | 8.5 | +4.0% | 1.5 |
| 2024 | p50 | 13.15 | 13.14 | +0.1% | 1.5 |
| 2024 | p95 | 20.29 | 20.78 | -2.4% | 1.5 |
| 2024 | max | 38.24 | 49.65 | -23.0% (!) | 1.5/1.6 |
| 2024 | weekday_mean | 14.37 | 14.21 | +1.1% | 1.3 |
| 2024 | weekend_mean | 12.35 | 12.28 | +0.6% | 1.3 |
| 2024 | dod_logret_sd | 0.1623 | 0.159 | +2.1% | 1.5 |
| 2024 | spread_2h | 9.257 | 8.77 | +5.5% | 12 |
| 2024 | imb_minus_spot_sd | 6.49 | 7.03 | -7.7% | 3 |
| 2024 | imb_max | 138 | 194.1 | -28.9% (!) | 3 |
| 2024 | demand_peak | 52.43 | 56.99 | -8.0% | 7 |
| 2025 | tokyo_mean | 12.47 | 12.45 | +0.2% | 1.2 |
| 2025 | system_mean | 11.08 | 11.08 | -0.0% | 1.2 |
| 2025 | p5 | 7.689 | 7.96 | -3.4% | 1.5 |
| 2025 | p50 | 12.03 | 11.53 | +4.3% | 1.5 |
| 2025 | p95 | 18.64 | 19.43 | -4.1% | 1.5 |
| 2025 | max | 41.76 | 45.01 | -7.2% | 1.5/1.6 |
| 2025 | weekday_mean | 13.23 | 13.03 | +1.6% | 1.3 |
| 2025 | weekend_mean | 11.02 | 11 | +0.2% | 1.3 |
| 2025 | daily_mean_sd | 2.122 | 2.31 | -8.2% | 1.5 |
| 2025 | daily_range_mean | 9.704 | 9.45 | +2.7% | 1.5 |
| 2025 | within_day_sd | 2.608 | 2.66 | -1.9% | 1.5 |
| 2025 | dod_logret_sd | 0.1705 | 0.145 | +17.6% (!) | 1.5 |
| 2025 | lag1 | 0.952 | 0.94 | +1.3% | 1.5 |
| 2025 | lag48 | 0.61 | 0.66 | -7.6% | 1.5 |
| 2025 | floor_slots | 105 | 105 | +0.0% | 1.4 |
| 2025 | spread_2h | 8.603 | 8.28 | +3.9% | 12 |
| 2025 | imb_minus_spot_mean | -0.759 | -0.68 | -11.6% (!) | 3 |
| 2025 | imb_minus_spot_sd | 4.552 | 4.93 | -7.7% | 3 |
| 2025 | imb_p5 | -7.4 | -7.67 | +3.5% | 3 |
| 2025 | imb_p95 | 5.38 | 5.72 | -5.9% | 3 |
| 2025 | imb_zero_share | 0.0459 | 0.04 | +14.7% (!) | 3 |
| 2025 | imb_ge45 | 38 | 38 | +0.0% | 3 |
| 2025 | imb_ge100 | 10 | 8 | +25.0% (!) | 3 |
| 2025 | imb_max | 137 | 131.5 | +4.2% | 3 |
| 2025 | demand_twh | 275.3 | 281.4 | -2.2% | 7 (eria basis) |
| 2025 | demand_peak | 56.06 | 57.67 | -2.8% | 7 |
| 2025 | demand_min | 19.39 | 18.3 | +6.0% | 7 |
| 2025 | pv_share | 0.0936 | 0.092 | +1.7% | 7 |
| 2025 | pv_max | 17.9 | 17.04 | +5.0% | 7 |
| 2026 | holdout_realised_like_H1_mean | 20.81 | 20.36 | +2.2% | 1.2/1.3 |

(!) = more than 10% off; see Honest misses.
<!-- /CALIBRATION_TABLE -->

Monthly means: all 36 FY2023-FY2025 monthly targets are met within 0.5% (by construction; see `calibration` rows
`monthly_mean_mMM`). Holdout realised-like FY2026 H1 mean vs the 20.36 JPY/kWh FY2026-to-date figure is in the last row.

**Honest misses.** FY2024 spot maximum (38 vs 49.65 JPY/kWh) and imbalance maximum (138 vs 194) are low: the model's
tightest FY2024 slot reaches RM ~5%, not ~3%. FY2025 day-over-day volatility of daily means is 18% high (weekday/weekend
transitions and spring floor days add jumps). The median is ~4% high, the p95 ~4% low: the real distribution is more
right-skewed. None of these affect the direction of any result; they are listed so nobody mistakes the lab for data.

Spike frequency (synthetic vs MARKET_FACTS):

<!-- SPIKE_TABLE -->
| FY | spot >= 30 | spot >= 40 | spot max | imbalance >= 45 | imbalance >= 100 | imbalance max | MARKET_FACTS reference |
|---|---|---|---|---|---|---|---|
| FY2023 | 17 | 5 | 48.62 | 33 | 9 | 130.89 | Tokyo max 50.00 |
| FY2024 | 22 | 0 | 38.24 | 56 | 20 | 137.97 | Tokyo max 49.65; imbalance max 194.11 |
| FY2025 | 22 | 3 | 41.76 | 38 | 10 | 137.01 | Tokyo max 45.01; imbalance >=45: 38, >=100: 8, max 131.49 |
<!-- /SPIKE_TABLE -->

Figures (SVG, `docs/figures/`): `price_duration.svg` (duration curves FY2023-25), `intraday_shape_fy2025.svg`
(hour-of-day mean by season vs MF 1.4), `monthly_fy2025.svg` (monthly means vs MF 1.3), `scarcity_curve.svg`
(imbalance vs reserve margin with the 200/45 and 300/50 curves).

## 8. Data dictionary (BigQuery dataset `energy_alphaevolve_lab`)

`data/schema.json` (identical copy in `energy_lab/schema.json`) is the authoritative dictionary: every column has a type
(STRING / INT64 / FLOAT64 / BOOL) and a description. Tables:

| Table | Rows | What |
|---|---|---|
| market_history | 52,608 | 30-min FY2023-FY2025: temperature, area demand + D-1 forecast, solar, net load, reserve margin, Tokyo / system / intraday / imbalance prices, scarcity component, fuel index, KBG demand + forecast, KBG solar, desk price forecast |
| calendar | 1,461 | FY2023-FY2026 days with national holidays (substitute and citizens' holidays) and observance periods |
| scenario_monthly | 1,536 | FY2026 banks per scenario x month |
| customers_train / customers_holdout / customers_holdout2 | 1,200 / 401 / 401 | visible features |
| customer_behaviour_train / _holdout / _holdout2 | 1,200 / 401 / 401 | hidden evaluator behaviour |
| segment_archetypes / segments | 20,064 / 11 | load shapes and segment parameters |
| cost_stack | 30 | components with status and source |
| bess_sites / solar_ppa | 8 / 1 | assets |
| trading_days | 208 | days in the trading folds |
| calibration | 144 | synthetic vs MARKET_FACTS |
| lab_runs / lab_programs / lab_invariant_catches / lab_holdout / lab_reviews | per run | evidence exported by `python -m energy_lab.export_evidence` |

Deliberate anomalies (the agents and the search need problems to find): spring 0.01 JPY/kWh floor slots, heat and cold
events, reserve-margin scarcity slots with imbalance at the regulatory curve, zero-price imbalance slots, a +0.3% D-1
forecast bias removed by the desk's calibration (documented in `energy_lab/sim/instances.py`), the April-2026 regime shift
in the holdout bank, the November 2026 wheeling increase and the October 2026 imbalance cap change.
