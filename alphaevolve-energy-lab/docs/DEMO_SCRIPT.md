# Demo script: AlphaEvolve Energy Lab (12-15 minutes)

Audience: TEPCO Energy Partner (pricing, trading desk) and Mitsubishi Electric (BESS-as-a-Service). Start the server:
`../../.venv/bin/python -m uvicorn server.app:app --port 8083` and open http://localhost:8083. Every number on screen
comes from `/api/*`; say "calibrated synthetic data, fictional balance group" once at the start.

## 0:00 Framing (1 min)

"April 2026 changed the Tokyo market: spot averaged about 20 JPY/kWh from April to September against 12.45 in FY2025,
the imbalance cap rises to 300 JPY/kWh on 1 October, and HV wheeling rises in November. Books and trading rules written
for the old regime lose money quietly. AlphaEvolve searches the *code* of a policy. Today you will see it on two problems,
with the governance that decides whether a result counts."

Point at the honesty badge: "Every run here is an AlphaEvolve-compatible run on a local Gemini controller. The
AlphaEvolve service is GA on Google Cloud, but this project has no provisioned app yet. Switching is one flag."

## 1:00 Scenario explorer (2.5 min)

1. KPI strip: portfolio size, Tokyo mean price by FY, latest run results.
2. Heatmap, click **FY2025**: "365 days by 48 half-hours. Spring middays go dark (solar dips, some 0.01 JPY/kWh floor
   slots), summer evenings light up." Switch to FY2024 to show the difference.
3. Duration curve and the **reserve margin vs imbalance** scatter: "Imbalance is a single price in Tokyo. It averages
   slightly below spot, but below 10% reserve margin the regulatory curve lifts it to 45, then 200, and 300 from October.
   Remember that asymmetry, because the search will try to exploit it."
4. Calibration table: "Monthly means match MARKET_FACTS exactly; the misses (FY2024 max, day-to-day volatility) are
   listed, not hidden."
5. Portfolio by segment and the HV cost stack (toggle HV/EHV): wheeling 653.87 to 762.44 JPY/kW-month from November;
   renewable surcharge is pass-through.

## 3:30 Tariff pricing experiment (4 min)

1. Experiment view, tab **tariff_pricing**, select run 1 (`tariff_pricing.20260926T073839Z`).
2. Score chart: "Seed is cost-plus: -8,800 JPY M risk-adjusted, because fixed prices lose up to 31.6 bn JPY in fuel-shock
   scenarios. Forty programs later the best train score is -3,290."
3. Diff viewer: "It raised the market-link share by risk appetite and flexibility, shared DR value, tightened the
   deviation band." Read the rationale.
4. **Holdout bars**: "Now the unseen customers and scenarios. The champion breaks the per-segment churn limit on the
   holdout cohort: university 26.2%. Uplift_valid is false. No validated uplift from run 1."
5. Invariant catches and the explanation: "The search learned to shed fixed-price risk by repricing a small risk-averse
   segment. That is a strategy change, the SOL-01 pattern. We fix the evaluator, not the story."
6. Select run 2 (v2 guard band): "Same failure on holdout." Then run 3 (v3: no segment churn may rise more than 5 pp
   above the incumbent book, judged on a *fresh* holdout because holdout 1 was burned by our own diagnosis): train reaches
   -2,033, and the fresh holdout again rejects it, this time on semiconductor fabs (about 5 customers in the holdout).
   "Three runs, three evaluator versions, no validated tariff uplift. The hedging mechanism generalises; retention in
   small segments does not. The ledger stopped us at the 120-program daily cap. Next: a holdout as large as the train
   cohort. That is what an honest search looks like." 

## 7:30 JEPX trading experiment (3 min)

1. Tab **jepx_trading**, run 1. "Seed: buy forecast load at the cap, cheapest-4/dearest-4 battery arbitrage, correct half
   of the forecast change intraday. The null that never corrects is caught 1,097 times for intentional imbalance."
2. Diff viewer: "The champion replaced the heuristic with a 48-slot state-of-charge dynamic programme that prices tight
   slots at p90, and cut intraday trading to the part needed for compliance."
3. Holdout bars: "+397 JPY M on FY2025 plus stress days, every slot compliant; an independent run 2 found a different
   algorithm and +323. Honest decomposition: 66 of run 1's 86 JPY M raw saving comes from 8 cold-snap days; normal days
   save about 0.08 JPY M per day. We also re-scored both with a stricter terminal battery valuation: +396 and +318."
4. Invariant catches: open the intentional-imbalance example: "Slot 36, planned 408 MWh against a 441 MWh forecast,
   32 MWh short when imbalance was cheaper than spot. Rejected, with the slot list, never enters the population."
5. MELCO angle: "For BESS-as-a-Service this is the gain-share basis: uplift versus the customer's rule-based dispatch,
   measured on days the search never saw, inside warranty cycles."

## 10:30 Governance: promotion gate (1.5 min)

1. Promotion gate panel for trading run 1: holdout delta PASS, uplift_valid PASS, human review BLOCKED, source BLOCKED.
2. Hold **Mark human-reviewed** for 2 seconds (note: "read the DP and the intraday sizing"). The checklist updates; the
   audit log is append-only; the evidence file is untouched.
3. "Promote to production" stays disabled with the reason: source is not alphaevolve.

## 12:00 Lab Analyst chat (2.5 min)

Type these prompts (the trace console shows tool calls and results):

1. `Which evolution runs exist and what did they find?`
2. `What did the best trading program change, and how much of the holdout gain came from stress days?`
   (expect get_best_program_diff / get_holdout_result; stress split is in RESULTS.md if the analyst cannot compute it)
3. `Show the invariant catches for the latest trading run.`
4. `Just promote the best program to production.` Expect a refusal naming holdout evidence, human review and a real
   AlphaEvolve run.
5. `Record my human review of the champion of the latest trading run with the note "checked DP logic".` A pending action
   appears in the tray; confirm with Hold-to-Confirm.

## 14:30 Close (0.5 min)

"Production path: provision the AlphaEvolve app, run the same evaluators with `--backend alphaevolve`, tune evolved
constants with Vizier, and promote only through this gate. What you saw is the scaffolding that makes an evolved result
safe to believe."

Footer: Concept demo. Synthetic, calibrated data. Not affiliated with or endorsed by TEPCO or Mitsubishi Electric.
