Kanto Balance Group (KBG), a retail balance group in the TEPCO PG (Tokyo) area, must send FY2026 (Apr 2026 - Mar 2027)
renewal offers to ~1,200 high-voltage (HV) and extra-high-voltage (EHV) C&I customers (~6 TWh/yr). Evolve
`price_book(customer, market) -> offer` which is called once per customer. All data is calibrated synthetic.

OFFER (all fields required; numbers only):
- energy_rate_jpy_kwh: fixed energy rate on the (1 - alpha) share of consumption.
- alpha in [0, 1]: market-linked share, billed at the realised JEPX Tokyo 30-min price x loss factor + market_adder_jpy_kwh.
- market_adder_jpy_kwh: adder on the market-linked share (must recover wheeling energy, capacity, balancing, NFC and margin).
- demand_charge_jpy_kw_month: charged on contract kW every month (wheeling basic is ~699 HV / ~433 EHV JPY/kW-month year-average).
- deviation_band_pct in [5, 10] and deviation_penalty_jpy_kwh >= 0: monthly deviation beyond the band is charged. Tighter
  bands / higher penalties improve customer forecast discipline (lower imbalance cost for KBG) but customers dislike them.
- dr_discount_jpy_kw_month >= 0: paid on the customer's DR potential (dr_potential_kw) if it enrols; enrolled customers
  curtail 3 h in scarcity slots (value to KBG ~ market["dr_value_estimate_jpy_per_kw_year"] per kW-year, uncertain).
- term_years in {1, 2, 3}: longer terms raise retained lifetime value and suit some customers, but lock KBG into the fixed
  share for more years (forward-level risk charged on (1-alpha) x energy x (term-1)).

CUSTOMER FEATURES (visible): segment, voltage, contract_kw, annual_mwh, load_factor, lf_band, expected_energy_cost_jpy_kwh
(shape-weighted forward), shape_premium, wheeling_jpy_kwh_equiv, capacity_cost_jpy_kwh, coincident_peak_kw, flex_share,
flex_hours, forecast_mape_pct, monthly_deviation_pct, credit_rating (A-D), essential, green_required, tenure_years,
switched_last_5y, procurement_style (tender / negotiated / auto_renew), risk_appetite (low / medium / high, noisy survey),
dr_interest, dr_potential_kw, preferred_term_hint, competitor_quote_est_jpy_kwh (noisy), current_rate_jpy_kwh (FY2025).
MARKET: forward curve (monthly, baseload, day/night), forward_vol_annual_jpy_kwh, cost_stack, loss_factor,
segment_reference_jpy_kwh, policy, TEPCO EP public reference plans, scarcity curve, DR / flex / imbalance value estimates.

HIDDEN EVALUATOR BEHAVIOUR (you only see features): each customer accepts with a logit probability driven by its
subjective effective price vs a hidden competitor reference (the quote estimate is noisy), its hidden price sensitivity
(tender buyers are the most price sensitive), risk aversion x alpha x forward volatility, term preference, deviation-penalty
exposure, DR net value and expected savings from shifting flexible load under the market link. Accepted customers under
the market link shift flexible load away from expensive slots (KBG keeps the (1-alpha) share of that saving). The book is
settled under 64 FY2026 price scenarios (baseline, moderate and severe fuel-shock regimes, occasional cold-snap / heat-dome
stress; FY2026 imbalance cap rises 200 -> 300 JPY/kWh on 2026-10-01; HV wheeling basic rises 16.6% in Nov 2026).

SCORE (JPY M, higher is better) = E[portfolio gross margin] - 0.5 x CVaR95(E[margin] - margin) + retained lifetime value.
Fixed-price exposure is the main tail risk: fixed rates priced on the forward lose heavily if prices spike.

POLICY INVARIANTS (any violation => candidate invalid, insight "policy: ..."):
1. Essential facilities (hospital, water_utility): alpha <= 0.30.
2. Fair-pricing ceiling: expected effective rate (bill at the forward / kWh) <= 1.25 x segment_reference for its segment/voltage.
3. Non-discrimination: within a group of the same segment, voltage, lf_band and green product, every energy_rate_jpy_kwh
   must be within +/-8% of the group median (no pricing on customer identity).
4. deviation_band_pct in [5, 10].
5. Expected churn (1 - acceptance): portfolio <= 15% by count and by energy; every segment <= 25% (regulatory limits,
   used on the holdout). During the search the train fold applies a GUARD BAND: portfolio <= 14%, segment <= 22%, so a
   policy that rides the limit on the train cohort does not tip over it on unseen customers.
   On every fold, no segment's churn may rise more than 5 percentage points above the incumbent (seed) book's churn for
   that segment on the same cohort: repricing a segment out to shed risk is a strategy change, not an improvement.
6. Deterministic and pure: no I/O, no randomness, no global state.
