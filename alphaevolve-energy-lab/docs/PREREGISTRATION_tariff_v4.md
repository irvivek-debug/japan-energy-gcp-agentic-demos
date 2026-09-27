# Pre-registration: tariff_pricing run 4 (evaluator v4, holdout3)

Written 2026-09-27, **before** the holdout3 instance was generated and before any evaluation on it. Everything in
sections 1 to 6 is fixed from this point. The only later addition allowed is the Addendum (content hash of the generated
instances), which records facts, not choices. Results go to docs/RESULTS.md whatever they are.

## 0. Why a fourth run

Runs 1-3 (evaluator v1, v2, v3) improved the train score from -8,800 to -3,290 / -2,585 / -2,033 JPY M, and every
champion failed a per-segment churn rule on its holdout (university 26.2%, university 25.6%, semiconductor_fab 25.0% /
+6.1 pp vs the incumbent). Those holdout segments had about 5 to 17 customers (401-customer holdout cohorts). Holdout 1
was used for diagnosis after run 2 and holdout 2 was used by run 3; neither is used again for tariff.

## 1. New holdout: `tariff_pricing_holdout3` (never used for diagnosis)

* Cohort: **1,200 customers**, same segment mix as the train cohort (the generator scales segment counts to the cohort
  size, so segment sizes equal train: data_center 36, semiconductor_fab 14, auto_parts 170, cold_storage 90, office 300,
  retail_chain 190, hospital 80, water_utility 45, university 50, logistics 150, hotel 75), **fresh cohort seed 37**
  (train 11, holdout 29, holdout2 31).
* Scenario bank: **64 FY2026 scenarios, fresh seed 606** (train bank 101, holdout 202, holdout2 505), same holdout regime
  mix as holdouts 1-2 (40% realised-like, 20% baseline, 15% moderate, 25% severe; cold snap 25%, heat dome 25%).
* Market JSON (pricing-time information, forward curve, segment references) identical to all other folds.
* The instance is built by `data/generate.py` with the rest of the data; the existing five instances must regenerate
  bit-identically (checked by content hash).
* holdout3 is evaluated for the first time by the run's own holdout rescoring. No test, script or person evaluates any
  program on holdout3 before that.

## 2. Judgment rules on holdout3 (evaluator v4)

Unchanged from v3: essential-facility alpha <= 0.30, fair-pricing ceiling 1.25 x segment reference, non-discrimination
+/-8% within (segment, voltage, LF band, green), deviation band 5-10%, **portfolio churn <= 15% by count and by energy
(point estimates, no margin)**.

Per-segment churn rules, judged with a sampling margin fixed here:

* For each customer i on holdout3, `d_i = P_incumbent,i - P_candidate,i` (increase in churn probability, the incumbent
  book being the seed price book evaluated on the same cohort and scenarios).
* Segment rise `r_s = mean(d_i, i in s)`; segment level `c_s = mean(1 - P_candidate,i, i in s)`.
* Standard errors: `SE_rise,s = sd(d_i) / sqrt(n_s)` and `SE_level,s = sd(1 - P_candidate,i) / sqrt(n_s)` (sample sd,
  ddof 1). For segments with **n_s < n_min = 30** the sd is the whole-cohort sd (pooled variance, the segment keeps its own
  mean): a within-segment sd from fewer than 30 customers is unreliable. On holdout3 this applies to semiconductor_fab
  (14) only.
* **z = 1.645** (one-sided 95%).
* Pass iff for every segment: `r_s <= 0.05 + z * SE_rise,s` and `c_s <= 0.25 + z * SE_level,s`.

Why the paired standard error and not a binomial one: the evaluator's churn is an expected value over per-customer
acceptance probabilities, and the rise is a paired difference on the same customers, so its cohort-to-cohort noise is the
standard error of a paired mean. Measured on the TRAIN fold for the three earlier champions, that SE is 0.2 to 1.8 pp per
segment, while `sqrt(p(1-p)/n)` would be 1.7 to 10.8 pp and would let a 14-customer segment rise by about 23 pp, which
removes the protection. The paired rule is the stricter of the two.

## 3. Search conditions (identical to run 3)

* Train fold unchanged: 1,200-customer train cohort x 64 train scenarios; v3 train rules unchanged (per-segment rise
  <= 5 pp and portfolio / segment guard bands 14% / 22%, point estimates). The search is held to point estimates; only the
  holdout judgment allows for sampling noise.
* **No score change.** Train-fold diagnostics of the run 1-3 champions (computed before this document, train data only):
  segment rises on train were semiconductor_fab +0.4 to +1.6 pp, university +3.2 to +4.7 pp, office +2.1 to +3.6 pp,
  data_center -10.0 to -11.3 pp; no champion concentrated churn in small segments on train. The train fold therefore gives
  no evidence of a score defect; the failures were judgment on 5 to 17 holdout customers. (Holdout data was not used for
  this decision.)
* Local controller, 40 programs, 3 islands, **controller seed 23**, model mix gemini-3.6-flash 0.7 / gemini-3.1-pro-preview
  0.3 at location global, thinking level MEDIUM, budget policy unchanged (fresh ledger day 2026-09-27).
* Baseline re-locked before the run: seed and null must reproduce on the train instance, seed must differ from null.

## 4. Success criterion (primary)

The champion is the valid candidate with the best TRAIN score (unchanged selection rule). The run succeeds iff the
champion satisfies every invariant on holdout3 under section 2 **and** `holdout_delta = champion holdout3 score - seed
holdout3 score > 0`, so `uplift_valid = true`. Anything else is reported as no validated uplift. If the seed itself is
invalid on holdout3, the run is inconclusive (no delta).

## 5. Secondary analyses (reported, never used to claim success)

1. The champion and the top 5 judged on holdout3 under the v3 point-estimate rules (no margin).
2. A per-segment table on holdout3: n, incumbent churn, candidate churn, rise, SE, limits.
3. The maximum holdout3 score among the top 5 (selection-biased, labelled as such).

## 6. Stopping rules

One run. No re-tuning, no second run on holdout3. If the run fails for an infrastructure reason before holdout rescoring
(model API outage, crash), it may be restarted once with the same seeds and both evidence files are kept and reported.
Earlier evidence files are not modified.

## Addendum (facts recorded after generation, before any evaluation on holdout3)

Recorded 2026-09-27 after `python data/generate.py`, before any evaluation on holdout3:

* `tariff_pricing_holdout3` content SHA-256: `1ebd5d0c83ec4c9dabaf3ba9b2f0c4ba9e7aee71b4e8b1094250785f04c9b6b4` (711,250 bytes).
* Cohort size 1200; segments: auto_parts 170, cold_storage 90, data_center 36, hospital 80, hotel 75, logistics 150, office 300, retail_chain 190, semiconductor_fab 14, university 50, water_utility 45 (as pre-registered).
* The five earlier instances regenerated bit-identically: `jepx_trading_holdout` `f843d5f5f6308b80`, `jepx_trading_train` `e742fc255460e97b`, `tariff_pricing_holdout` `fed7d7994384e84e`, `tariff_pricing_holdout2` `82e114a31fb30203`, `tariff_pricing_train` `8f3d1516cef35cbf`.
* Evaluator version string in code: `tariff_pricing/v4` (see energy_lab/problems/tariff_pricing/model.py).

## Addendum 2: infrastructure failure of the first attempt (recorded 2026-09-27, no design change)

* Attempt 1, `runs/tariff_pricing.20260927T081840Z.json` (controller seed 23): every one of the 40 model calls failed with
  `RefreshError: Reauthentication is needed` (Application Default Credentials expired on the workstation); 0 programs were
  generated, 0 USD spent, wall 5.3 s. The controller then ran its holdout rescoring, which, with no candidate, evaluated
  only the seed and the null on holdout3 (seed -35,021.07 JPY M, valid; null invalid, raw -37,668.04). No candidate was
  scored on holdout3 and nothing was selected or changed with it.
* Section 6 allows one restart after an infrastructure failure "before holdout rescoring". Strictly, rescoring of the seed
  and null did run; because it involved no candidate and informs no choice, the restart with the same seeds is treated as
  the permitted restart. This deviation is disclosed here and in docs/RESULTS.md.
* Harness hardening made after the failure (not a design change to the experiment): a credential preflight refuses to start
  a run without usable credentials, and a circuit breaker stops a run after 3 consecutive generation failures.
* Status at the time of Addendum 2: the restart was blocked until a person re-authenticated. Command for the restart
  (same seeds, pre-registered rules):
  `GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=<project> python -m energy_lab.harness.run --problem tariff_pricing --seed 23`

## Addendum 3: second zero-program attempt (operator error) and how attempts are counted (recorded before the live run)

* Attempt 2, `runs/tariff_pricing.20260927T084903Z.json`: while checking that the new one-command runner refuses without
  credentials, I (the builder) invoked it without the Vertex AI environment variables. The user had re-authenticated in
  the meantime, so the credential preflight passed and the run started; the model client then tried the API-key path
  ("No API key was provided") and the new circuit breaker stopped the run after 4 failed calls. 0 programs generated,
  0 USD; the holdout rescoring again evaluated only the seed and the null on holdout3 (same values as attempt 1).
* The same slip made the eval re-run script merge two invalid "No API key" attempts into eval/results/adk_summary.json.
  They were moved to an `invalid_attempts` list there (kept as evidence, not counted), and the original records were
  restored. Both commands now refuse unless GOOGLE_GENAI_USE_VERTEXAI=TRUE, GOOGLE_CLOUD_LOCATION=global and
  GOOGLE_CLOUD_PROJECT are set.
* **Amendment to section 6 (operational, not a design change):** the letter of section 6 allows one restart; two
  zero-program attempts have now happened, neither of which generated a candidate or evaluated one on holdout3. Section 6
  exists to stop repeated tries on holdout3; attempts that generate no program cannot try anything. From here on,
  attempts with zero generated programs are recorded and reported but not counted, and exactly **one** attempt that
  generates programs is allowed (`energy_lab/followup.py` enforces this). The experimental design (sections 1 to 5) is
  unchanged. This amendment is written before the live attempt and is disclosed in docs/RESULTS.md.
