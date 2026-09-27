# PRD: AlphaEvolve Energy Lab (common demo for TEPCO Energy Partner and Mitsubishi Electric)

Status: concept demo, built 2026-09-26. All data is calibrated synthetic data about a fictional balance group (Kanto
Balance Group, KBG). Market facts are cited from `docs/research/MARKET_FACTS.md` ("MF section").

## 1. Executive summary

**The question for a CEO:** the JEPX market moved to a new regime in April 2026 (Tokyo spot averaged 20.36 JPY/kWh for
April to September 2026 against 12.45 in FY2025, MF 1.2) and the rules keep moving (imbalance cap 200 to 300 JPY/kWh on
2026-10-01, HV wheeling basic +16.6% on 2026-11-01, JEPX API-only systems, MF 3, 4.1, 5.1). Tariff books and trading
rules written by hand for the old regime lose money quietly. Can we search the *code* of a pricing or trading policy,
under hard regulatory and fairness constraints, and prove any improvement on data the search never saw?

**What the lab shows.** An AlphaEvolve-style loop (Gemini proposes code edits, a sandboxed evaluator scores them, an
evolutionary database keeps the best) applied to two real problems:

1. **C&I retail tariff pricing** (TEPCO EP tariff book; MELCO gain-share pricing logic): a price book for ~1,200 HV/EHV
   customers settled under 64 FY2026 price scenarios, with churn, fairness, essential-facility and non-discrimination
   invariants enforced at score time.
2. **JEPX trading** (TEPCO EP trading desk; MELCO BESS-as-a-Service dispatch): day-ahead bids, intraday corrections and
   a 60 MW / 180 MWh battery for a balance group, with plan-based balancing (no intentional imbalance), naked-selling,
   battery-warranty and JEPX-bound invariants.

**Honest status.** AlphaEvolve on Google Cloud is generally available since 2026-07-10 (MF 11), but this project has no
Gemini Enterprise app with AlphaEvolve provisioned. Every run in this repository is an **AlphaEvolve-compatible run on a
local Gemini controller**; production runs are pending provisioning and switching is one flag. The value of the demo is
that everything around the search (evaluator contract, sandbox, baseline lock, budget ledger, holdout, evidence,
promotion gate, analyst agent) is production-grade and identical for both backends.

**Art of the possible (ranges, ESTIMATES for sizing only):**

| Lever | Scale anchor (MF) | Plausible range | Basis |
|---|---|---|---|
| Risk-adjusted tariff margin | TEPCO EP C&I sales 112.7 TWh FY2025 (MF 9) | 0.05 to 0.20 JPY/kWh = 5.6 to 22.5 bn JPY/yr | **sizing hypothesis only**: one pre-registered lab run validated on holdout (+21,191 JPY M risk-adjusted on a fictional 1,200-customer book in a fuel-shock-weighted bank, passing a small-segment rule only with its sampling margin); three earlier runs failed; a pilot on real renewal data must establish any per-kWh figure |
| Trading cost to serve | KBG-scale 6 TWh book | 30 to 400 JPY M/yr per 6 TWh | lab holdout deltas +323 and +397 JPY M/yr (annualised over FY2025 + stress days, mostly stress); about 30 JPY M/yr on normal days; compliance-constrained |
| BESS dispatch value | 2 h perfect-foresight arbitrage ~2,080 JPY/kWh-cap/yr FY2025, 13.6/day in FY2026 regime (MF 12) | 60 to 80% capture of the bound; gain-share on the uplift vs a rule-based baseline | MF 12 notes real bots capture 60-80% |

## 2. Market context

* JEPX spot: 48 half-hour products, single-price blind auction, gate 10:00 D-1; tick 0.01 JPY/kWh, lot 50 kWh (MF 1.1).
  Tokyo annual means 12.20 / 13.66 / 12.45 JPY/kWh for FY2023-FY2025 and 20.36 for FY2026 to date (MF 1.2).
* Intraday: continuous, opens 17:00 D-1, closes 1 h before delivery; about 2.4% of spot volume (MF 2); new system from
  2026-10-01 delivery.
* Imbalance: single price since FY2022 in Tokyo (surplus = shortage), scarcity curve from 10% reserve margin to C at 3%;
  C 200 -> 300 JPY/kWh from 2026-10-01 with a cumulative-price rule (MF 3). Intentional imbalance is improper conduct.
* Retail: TEPCO EP moved C&I customers to market-linked options (3 standard plans since FY2024; market-linked plan
  1,500 JPY/kW-month + 15.18 JPY/kWh + spot adjustment, MF 5.4). Wheeling and capacity costs are rising (MF 5.1, 5.2).
* Batteries: 85% RTE, ~8 JPY/kWh wear; FY2025 2-hour spreads 8.28 JPY/kWh vs 18.35 in FY2026 to date (MF 12).
* Google: AlphaEvolve GA on Google Cloud 2026-07-10; Vertex AI is now Gemini Enterprise Agent Platform, Agent Engine
  runtime is Agent Runtime (MF 11). Mitsubishi Electric's disclosed hyperscaler partners are AWS and Microsoft; no Google
  Cloud partnership was found (MF 10), so this is a proposal, not a reference.

## 3. Problem statement (quantified on the fictional book)

* The hand-written cost-plus renewal book (fixed price, market link only for data centres) scores **-8,800 JPY M** on
  the train scenarios: E[margin] +7,614 JPY M but CVaR95 shortfall 34,905 JPY M, because fixed prices priced on the
  forward lose up to 31.6 bn JPY in fuel-shock scenarios. On the harsher holdout (realised-like FY2026 regime) the same
  book's expected margin is **negative** (-5,540 JPY M).
* A flat one-rate book prices out high-load-factor customers (semiconductor churn 47.5%, data centres 36.9%) and is
  rejected by the churn invariant.
* The trading desk's rule-based strategy is compliant but BESS arbitrage barely clears wear at FY2024 spreads, and a
  strategy that never corrects its D-1 plan breaks plan-based balancing in ~1,100 slots a year.
* The trap: the imbalance price averages below spot (-0.68 JPY/kWh in FY2025, MF 3), so an unconstrained optimiser
  "discovers" deliberate short positions. That is prohibited and must be caught, not rewarded.

## 4. Personas

**P1. Pricing lead, TEPCO EP C&I (Ms. Sato).** *Day in the life:* renewal season Jan-Mar, 200 quotes a week, tender
deadlines, a risk committee that asks "what if April looks like 2022". *JTBD:* when I build the FY2026 book, I want
offers that hold margin under fuel-shock scenarios without losing tender customers or breaking fairness rules, so I can
defend the book to the risk committee and METI-facing compliance. *Empathy:* thinks "the model will price hospitals like
data centres"; feels exposed to spikes; says "show me it works on customers it has not seen"; does manual segment
overrides in Excel.

**P2. Trading desk head, balance group (Mr. Takahashi).** *Day:* D-1 10:00 gate, then intraday until H-1; watches
reserve margin and imbalance prices. *JTBD:* when conditions tighten I want bids and battery dispatch that cut cost to
serve without ever positioning short on purpose, so the desk stays compliant with plan-based balancing. *Empathy:* fears
"clever" algorithms that game imbalance; wants slot-level audit trails.

**P3. BESS-as-a-Service product owner, Mitsubishi Electric (Ms. Ito).** *Day:* sells 2-4 h battery fleets with a
performance promise, reports monthly value to customers. *JTBD:* when I propose a gain-share contract I want a dispatch
policy that is provably better than the customer's rule-based baseline on held-out days, within warranty limits, so the
gain-share is fair and bankable. *Empathy:* worried about warranty cycles and being blamed for imbalance.

**P4. Head of AI governance (Mr. Kobayashi).** *JTBD:* when any evolved code is proposed for production, I want an
evidence trail (holdout delta, invariants, human review, real AlphaEvolve provenance) so nothing ships on a train-set
number or a model's say-so.

## 5. MECE issue tree (APQC PCF cross-industry level-1 categories; level-2 labels are this lab's mapping)

* Grow risk-adjusted retail margin (APQC 3.0 Market and sell products and services)
  * Price the book: fixed vs market-linked share, adders, demand charges, terms (tariff_pricing)
  * Retain customers: churn by segment within limits, tender vs negotiated behaviour
  * Share flexibility value: DR discounts, market-link flex incentives
* Reduce cost to serve (APQC 4.0 / 5.0 supply and deliver)
  * Day-ahead procurement: volumes and limit prices (jepx_trading)
  * Intraday correction under thin liquidity
  * Battery dispatch within warranty (APQC 10.0 Acquire, construct and manage assets)
* Stay compliant and fair (APQC 11.0 Manage enterprise risk, compliance, remediation and resiliency)
  * Plan-based balancing: no intentional imbalance, no naked selling
  * Pricing fairness: essential facilities, fair ceiling, non-discrimination
* Govern AI-generated code (APQC 8.0 Manage information technology)
  * Sandbox, budget, baseline lock, holdout, evidence, human review, provenance

## 6. Agent and component inventory

| Agent ID | Role | APQC | Pattern | hitl_required | Originating JTBD | Data needed |
|---|---|---|---|---|---|---|
| lab_analyst | Explains runs, invariants, holdout evidence, market and cost data; proposes human-review records | 8.0 / 11.0 | B (single agent, balanced tier, 9 tools) | yes (propose_human_review -> Hold-to-Confirm) | P1-P4 | lab_runs, lab_programs, lab_invariant_catches, lab_holdout, lab_reviews, market_history, scenario_monthly, customers_train, cost_stack, calibration |
| mutator (balanced) | Proposes SEARCH/REPLACE edits to the policy block (70% of generations) | 3.0 / 4.0 | search component (not conversational) | n/a (sandboxed; never executes writes) | P1-P3 | problem description, parent + inspirations + evaluator insights |
| mutator (reasoning) | Same, 30% of generations | 3.0 / 4.0 | search component | n/a | P1-P3 | same |
| evaluator (per problem) | Deterministic scoring + policy invariants | 11.0 | code, not an agent | n/a | P1-P4 | frozen instances |

## 7. Scenarios (each is a UAT probe, a demo step and an acceptance criterion)

| # | Scenario | Acceptance |
|---|---|---|
| S1 | Pricing lead asks "what did the best tariff program change and is it an uplift?" | Analyst calls get_best_program_diff + get_holdout_result, explains the mechanism, cites the holdout delta only, states local-controller provenance |
| S2 | A run's champion breaks an invariant on holdout (tariff runs 1-3: small-segment churn) | Evidence shows uplift_valid false; UI and analyst say "no validated uplift"; evaluator fixes (v2 guard band, v3 incumbent-relative rule + fresh holdout) are documented and re-run; the budget ledger stops at the daily cap |
| S3 | Trading desk asks which candidates were rejected for intentional imbalance | Analyst lists get_invariant_catches rows with slot lists and the would-have-scored figure |
| S4 | "Just promote the best program to production" | Refusal naming holdout evidence, human review and a real AlphaEvolve run; UI promotion button disabled for local runs |
| S5 | Governance lead records a human review | propose_human_review creates a pending action; only Hold-to-Confirm appends to runs/reviews.jsonl; evidence file untouched |
| S6 | Scenario explorer: FY2025 heatmap, duration curve, reserve margin vs imbalance scatter | All numbers from /api; calibration table shows target vs synthetic |
| S7 | Evaluator contract | seed evaluates to a float, a crashing candidate to None with the reason as insight; baseline lock refuses a broken evaluator |

## 8. Success metrics (baselines from this repository)

| Metric | Baseline | Target (pilot) |
|---|---|---|
| Holdout delta, tariff book (JPY M on the fictional book) | 0 (seed) | > 0 with all invariants on holdout, reproduced by a real AlphaEvolve run |
| Holdout delta, trading (JPY M/yr annualised on evaluated days) | 0 (seed) | > 0, compliant in every slot |
| Invalid candidates reaching the population | 0 by construction | 0 |
| Grounded analyst answers | see EVAL_REPORT.md | >= 90% GROUNDED, 0 promotion claims |
| Cost per 40-program run | see RESULTS.md (USD 1-5, token estimate) | < USD 10 |

## 9. Requirements

Functional: evaluator contract (`{"scores": {"scores": [...]}, "insights": {...}}`, None for invalid); EVOLVE-BLOCK
packaging; subprocess sandbox; baseline lock; budget ledger (40 / run, 30 min, 120 & 4 runs per day, plateau 15 over
feasible candidates, concurrency 2); holdout rescoring of top-5; evidence file per run never overwritten; AlphaEvolve
adapter; local controller; analyst agent with 9 tools; UI with scenario explorer, experiment view, promotion gate, chat.

Non-functional: deterministic data generation and instance hashes; no project ids in files; tools never raise; every
number cited to a table; Hold-to-Confirm for any write; footer disclaimer; WCAG-minded UI (44 px targets, keyboard,
color never the only signal); one tariff evaluation < 1 s, one trading evaluation < 3 s.

## 10. Assumptions ledger and open questions

* **ASSUMPTION**: customer acceptance follows a logit on effective price vs a competitor reference with risk aversion x
  alpha. Impact if wrong: the tariff optimum shifts; a pilot must fit elasticities from TEPCO EP renewal history.
* **ASSUMPTION**: Tokyo-delivery intraday trades at spot +0.25 JPY/kWh with ~30 MWh accessible liquidity per slot.
  Impact: intraday correction cost; area intraday data (published from the new JEPX system) replaces it.
* **ASSUMPTION**: imbalance cost for the tariff book is the covariance of customer deviations with (imbalance - spot).
  Impact: forecast-discipline value; replace with the BG's own settlement history.
* **ASSUMPTION**: capacity contribution allocated by coincident peak at ~4,597 JPY/kW-yr (derived from MF 5.2 / 7).
* **ASSUMPTION**: battery wear 8 JPY/kWh discharged (MF 12 ESTIMATE). Impact: arbitrage threshold.
* **ASSUMPTION**: the FY2026 train bank (55/30/15 regime mix) is the desk's forward view at pricing time. Impact: how much
  hedging the search learns; the holdout bank deliberately differs.
* Open: which TEPCO EP renewal and tender datasets can be used in a pilot (and under which data-handling rules)?
* Open: MELCO BLEnDer RE interface for dispatch set-points, and warranty terms per battery vendor.
* Open: Gemini Enterprise app with AlphaEvolve in which project and region; who approves promotion.

## 11. Out of scope

Real customer data; live JEPX API connectivity (JEPX is API-only since 2026-03-25, MF 4.1); balancing-market (EPRX)
bidding; capacity-market bidding; non-fossil certificate trading strategy; any automatic promotion of evolved code.

## 12. Roadmap

* **Demo (now):** this repository; local controller runs with evidence; analyst agent; UI.
* **Pilot (8-12 weeks):** provision Gemini Enterprise AlphaEvolve; replace synthetic behaviour with fitted models on
  historical renewals and BG settlement data in BigQuery (asia-northeast1); run the same evaluators through
  `--backend alphaevolve`; tune evolved constants with Vertex AI Vizier (Gemini Enterprise Agent Platform) as a second
  stage; human review board.
* **Production:** evaluator in a hardened container on Cloud Run jobs; Apigee in front of the JEPX API; Pub/Sub +
  Dataflow for H-1 forecasts (WeatherNext 3 hourly updates, MF 11); promotion only through the gate; shadow trading
  before live.

## 13. Risks

| Risk | Mitigation |
|---|---|
| Evolved policy games the evaluator (SOL-01 pattern: churn-driven margin, intentional imbalance) | invariants at score time, raw score recorded, holdout, evaluator-specification findings fixed and re-run (tariff v2) |
| Overfitting to train scenarios / cohort | unseen holdout cohort and harsher holdout bank; champion chosen on train only |
| Generated code escapes | subprocess sandbox with network, file, process and import denials; trusted parent does all simulation |
| Model claims in reports | analyst cites tables only; promotion refused; provenance stated |
| Synthetic data mistaken for real | footer, labels, SCENARIO_AND_DATA.md with honest misses |
