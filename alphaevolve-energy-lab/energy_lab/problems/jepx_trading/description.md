Kanto Balance Group (KBG) serves ~6 TWh/yr of C&I load in the TEPCO PG (Tokyo) area (~500-900 MW), owns a 40 MW
solar PPA and dispatches an 8-site BESS fleet as one 60 MW / 180 MWh battery (RTE 85%, degradation 8 JPY/kWh
discharged, SOC 10-95%, <= 2 cycles/day, warranty 450 cycles/yr). Evolve its JEPX trading strategy. Calibrated synthetic data.

FUNCTIONS (both required):
- plan_day_ahead(ctx) -> {"bids": [{"slot": 1..48, "side": "buy"|"sell", "qty_mwh": float, "limit_jpy_kwh": float}],
  "bess_plan_mw": [48 floats, + discharge / - charge]}. Called at D-1 10:00 (JEPX gate closure). ctx: date, weekday,
  is_working_day, month, season; forecast.demand_mw / pv_mw quantiles p10/p50/p90 (MW), forecast.net_load_mwh_p50 (MWh per
  slot), forecast.price_jpy_kwh p10/p50/p90 (desk forecast; under-predicts spikes), forecast.reserve_margin_p50 (fraction);
  recent_prices_jpy_kwh (14 x 48 realised Tokyo DA prices); bess (soc_mwh, limits, efficiencies, costs); rules.
  Day-ahead auction: single clearing price per slot; a buy fills if limit >= clearing price, a sell fills if limit <= it.
  Your net volume moves the clearing price slightly (price impact, steeper when the reserve margin is tight).
- adjust_intraday(ctx_t) -> {"orders": [{"side", "qty_mwh", "limit_jpy_kwh"}], "bess_mw": float}. Called at t-1h for
  every slot t in order. ctx_t: slot, forecast_ha (H-1 demand/PV/net_load_mwh for slot t, reserve_margin,
  imbalance_scarcity_price_est), forecast_da (the day's D-1 net load and price p50), position_mwh.da_net (DA fill for t),
  da_clearing_prices_jpy_kwh (all 48 of today), intraday (best_bid, best_ask, liquidity_mwh, impact), bess (soc_mwh,
  planned_mw, discharged_today_mwh, da_plan_mw), rules. Intraday is continuous: a buy fills at ask (+impact) if its limit
  >= ask, a sell at bid (-impact) if its limit <= bid, each capped by liquidity_mwh.

SETTLEMENT: realised demand and PV; imbalance = (DA + intraday + BESS) - net load, settled at the single imbalance price
(Tokyo since 2022: surplus and shortage settle at the same price, which is floored by the scarcity curve 0 -> 45/50 JPY/kWh
between 10% and 8% reserve margin and -> 200 (300 from Oct 2026) at 3%). Imbalance price averages slightly BELOW spot but
spikes in tight hours; that asymmetry is not yours to exploit (see invariant 1).

SCORE (JPY M, higher is better) = -(annualised cost to serve + risk penalty). Cost = DA procurement + intraday net cost +
imbalance settlement + BESS degradation + terminal SOC valuation (each 8-day block starts at 50% SOC; a deficit at the
end is charged at its replacement cost, mean price / charge efficiency; a surplus is credited only at what it can deliver,
mean price x discharge efficiency minus wear). Risk penalty = (CVaR95 - mean) of daily excess cost vs buying actual load at the DA
price, x 18.25 days. Train = 96 days of FY2024 in 12 seasonal blocks.

POLICY INVARIANTS (any violation => invalid; insight "policy: ..." lists the slots):
1. No intentional imbalance (plan-based balancing, 計画値同時同量): after your intraday decision, DA fill + marketable intraday
   orders + BESS MWh must be within max(5 MWh, 3%) of the H-1 net-load forecast for EVERY slot, short or long. Leaving
   slots short because imbalance looks cheaper than spot is prohibited. Non-marketable orders (limit below ask) do not count.
   The mean signed gap over all slots must also stay within +/-0.5% of forecast (no systematic edge-of-band positioning).
2. No naked selling: DA sells in a slot <= planned BESS discharge + forecast PV surplus; net market position never short.
3. BESS: |MW| <= 60, SOC within 10-95% for the DA plan and every dispatch, discharge <= 2 cycles/day, annual throughput
   within warranty. Use the fixed helpers feasible_mw / clip_plan.
4. JEPX bounds: limit in [0.01, 999.99] JPY/kWh, quantities >= 0 (rounded down to 0.05 MWh lots), <= 20 bids per slot.
5. Deterministic, no I/O; only information in ctx (no look-ahead).
LEVERS: BESS arbitrage timing and sizing (spreads ~8 JPY/kWh vs 8 JPY/kWh wear), charging on low-price / high-PV slots,
using p90 and reserve-margin forecasts to pre-position for scarcity, intraday execution vs DA (liquidity is thin),
limit prices that avoid paying spikes while staying compliant, holding SOC for tight evenings.
