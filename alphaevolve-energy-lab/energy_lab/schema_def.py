"""Single source of truth for the BigQuery / DuckDB table schemas (written to data/schema.json and energy_lab/schema.json).

Types: STRING, INT64, FLOAT64, BOOL only. Dates/timestamps are ISO strings. All data is CALIBRATED SYNTHETIC.
"""
from __future__ import annotations


def _t(desc: str, cols: list[tuple[str, str, str]]) -> dict:
    return {"description": desc, "columns": [{"name": n, "type": t, "description": d} for n, t, d in cols]}


S, I, F, B = "STRING", "INT64", "FLOAT64", "BOOL"

SCHEMA = {
    "market_history": _t(
        "30-minute TEPCO PG (Tokyo) area market history FY2023-FY2025 plus KBG balance-group series. Calibrated synthetic "
        "data (targets: MARKET_FACTS 1-3, 7).", [
            ("ts", S, "slot start, ISO local JST (YYYY-MM-DDTHH:MM)"), ("date", S, "delivery date YYYY-MM-DD"),
            ("fiscal_year", I, "Japanese fiscal year (April-March)"), ("month", I, "calendar month 1-12"),
            ("slot", I, "30-min product 1-48 (1 = 00:00-00:30)"), ("hour", I, "hour of day 0-23"),
            ("day_of_week", I, "0=Monday"), ("is_holiday", B, "national holiday"), ("is_working_day", B, "weekday, not holiday/New Year/Obon"),
            ("observance", S, "new_year / obon / golden_week or empty"), ("temp_c", F, "Tokyo temperature, deg C"),
            ("area_demand_gw", F, "TEPCO area demand, GW"), ("area_demand_da_fcst_gw", F, "D-1 area demand forecast, GW"),
            ("area_pv_gw", F, "TEPCO area solar output, GW"), ("net_load_gw", F, "demand minus solar, GW"),
            ("reserve_margin_pct", F, "wide-area reserve margin proxy, %"),
            ("tokyo_price_jpy_kwh", F, "JEPX day-ahead Tokyo area price, JPY/kWh"),
            ("system_price_jpy_kwh", F, "JEPX day-ahead system price, JPY/kWh"),
            ("intraday_bid_jpy_kwh", F, "intraday best bid at H-1 (Tokyo delivery), JPY/kWh"),
            ("intraday_ask_jpy_kwh", F, "intraday best ask at H-1 (Tokyo delivery), JPY/kWh"),
            ("imbalance_price_jpy_kwh", F, "single imbalance price (surplus = shortage), JPY/kWh"),
            ("scarcity_price_jpy_kwh", F, "scarcity-curve component vs reserve margin at gate closure, JPY/kWh"),
            ("fuel_index", F, "monthly price-level index (LNG-like factor), FY2025 mean = 1"),
            ("kbg_demand_mw", F, "KBG balance-group demand, MW"), ("kbg_demand_da_fcst_mw", F, "KBG D-1 demand forecast p50, MW"),
            ("kbg_pv_mw", F, "KBG 40 MW solar PPA output, MW"), ("tokyo_price_da_fcst_jpy_kwh", F, "desk D-1 price forecast p50, JPY/kWh")]),
    "calendar": _t("Calendar FY2023-FY2026 with Japanese national holidays and observance periods.", [
        ("date", S, "YYYY-MM-DD"), ("fiscal_year", I, "fiscal year"), ("month", I, "month"), ("day_of_week", I, "0=Monday"),
        ("is_holiday", B, "national holiday incl. substitute and citizens' holidays"), ("is_working_day", B, "working day"),
        ("observance", S, "new_year / obon / golden_week or empty")]),
    "scenario_monthly": _t("FY2026 Monte Carlo scenario banks (train = desk view at pricing time; holdout = unseen, harsher), "
                           "summarised per scenario and month.", [
        ("bank", S, "train or holdout"), ("scenario", I, "scenario index"), ("regime", S, "baseline / moderate_shock / severe_shock / realised_like"),
        ("stress", S, "injected stress events (cold_snap_lng, heat_dome) or none"), ("month", I, "calendar month"),
        ("mean_price_jpy_kwh", F, "monthly mean Tokyo price"), ("max_price_jpy_kwh", F, "monthly max slot price"),
        ("p95_price_jpy_kwh", F, "monthly 95th percentile slot price"), ("mean_imbalance_jpy_kwh", F, "monthly mean imbalance price"),
        ("max_imbalance_jpy_kwh", F, "monthly max imbalance price"), ("min_reserve_margin_pct", F, "monthly min reserve margin %"),
        ("slots_ge_100", I, "slots with Tokyo price >= 100 JPY/kWh"), ("annual_mean_price_jpy_kwh", F, "scenario FY2026 annual mean")]),
    "customers_train": None, "customers_holdout": None, "customers_holdout2": None,
    "customer_behaviour_train": None, "customer_behaviour_holdout": None, "customer_behaviour_holdout2": None,
    "segment_archetypes": _t("Segment archetype 30-min relative load shapes per representative day type (38 types).", [
        ("segment", S, "customer segment"), ("day_type", S, "MM-working / MM-nonworking / MM-shutdown / heat-working / cold-working"),
        ("slot", I, "1-48"), ("hour", I, "0-23"), ("relative_load", F, "load relative to the segment weekday peak (~1)")]),
    "segments": _t("Segment archetype parameters (LAB-ASSUMPTIONS).", [
        ("segment", S, "segment"), ("train_customers", I, "customers in the train cohort"), ("kw_median", F, "median contract kW"),
        ("cooling_sens_per_c", F, "load change per deg C (summer)"), ("heating_sens_per_c", F, "load change per deg C colder (winter)"),
        ("sigma_slot", F, "30-min deviation vs plan (fraction)"), ("sigma_month", F, "monthly deviation vs plan (fraction)"),
        ("flex_share", F, "shiftable energy share"), ("flex_hours", F, "shift window hours"), ("dr_share", F, "curtailable share of contract kW"),
        ("dr_cost_median_jpy_kw_month", F, "median DR enrolment cost"), ("green_prob", F, "share requiring a green product"),
        ("essential", B, "essential facility (alpha <= 0.3)"), ("clv_jpy_m_per_mw_year", F, "relationship value"),
        ("tender_share", F, "share procuring by tender")]),
    "cost_stack": _t("Retail cost stack components for TEPCO PG area C&I supply, with status and source.", [
        ("component", S, "component"), ("voltage", S, "HV / EHV / all"), ("period", S, "validity period"), ("value", F, "value"),
        ("unit", S, "unit"), ("status", S, "VERIFIED / ESTIMATE / DERIVED / LAB-ASSUMPTION"), ("source", S, "citation"),
        ("treatment", S, "how the evaluator uses it")]),
    "bess_sites": _t("KBG BESS fleet (8 fictional sites, BESS-as-a-Service), dispatched as one 60 MW / 180 MWh battery.", [
        ("site_id", S, "site id"), ("name", S, "fictional site name"), ("prefecture", S, "prefecture"), ("power_mw", F, "MW"),
        ("energy_mwh", F, "MWh"), ("duration_h", I, "hours"), ("commissioned", S, "YYYY-MM"), ("voltage", S, "grid connection"),
        ("rte", F, "round-trip efficiency"), ("soc_min_pct", F, "min SOC %"), ("soc_max_pct", F, "max SOC %"),
        ("operator_model", S, "commercial model")]),
    "solar_ppa": _t("KBG 40 MW solar PPA (fictional).", [
        ("name", S, "name"), ("capacity_mw", F, "MW"), ("sites", I, "sites"), ("prefectures", S, "prefectures"), ("contract", S, "terms")]),
    "trading_days": _t("Days in the jepx_trading train (FY2024) and holdout (FY2025 + stress) folds.", [
        ("fold", S, "train / holdout"), ("date", S, "date"), ("block", I, "8-day block"), ("tag", S, "normal / stress_*"),
        ("kbg_energy_mwh", F, "KBG net energy"), ("mean_spot_jpy_kwh", F, "mean Tokyo DA price"), ("max_spot_jpy_kwh", F, "max DA price"),
        ("max_imbalance_jpy_kwh", F, "max imbalance price"), ("min_reserve_margin_pct", F, "min reserve margin %"),
        ("da_demand_mape_pct", F, "D-1 demand forecast MAPE %")]),
    "calibration": _t("Calibration evidence: synthetic statistics vs MARKET_FACTS targets.", [
        ("fiscal_year", I, "FY"), ("metric", S, "statistic"), ("synthetic", F, "synthetic value"), ("target", F, "MARKET_FACTS value"),
        ("abs_error", F, "absolute error"), ("rel_error_pct", F, "relative error %"), ("market_facts_section", S, "section"),
        ("status", S, "calibrated / diagnostic / scenario")]),
    # --- evidence tables (exported from runs/*.json by `python -m energy_lab.export_evidence`) ---------------------
    "lab_runs": _t("One row per finished evolution run (evidence file).", [
        ("run_id", S, "problem.startedUTC"), ("problem", S, "tariff_pricing / jepx_trading"),
        ("source", S, "local-gemini-controller / alphaevolve / local-dry-run-mutator"), ("backend", S, "local / alphaevolve"),
        ("evolved", B, "true only for a promoted AlphaEvolve run"), ("started", S, "ISO UTC"), ("finished", S, "ISO UTC"),
        ("programs_evaluated", I, "candidates generated and evaluated"), ("valid_count", I, "feasible candidates"),
        ("invalid_count", I, "invalid candidates"), ("stopped_reason", S, "max_programs / wall_clock / plateau"), ("wall_s", F, "seconds"),
        ("seed_train", F, "seed score, train, JPY M"), ("null_train_raw", F, "null raw objective, train, JPY M"),
        ("null_train_valid", B, "null satisfies policy invariants on train"), ("best_train", F, "best feasible train score, JPY M"),
        ("best_program_id", S, "champion program id (best train score)"), ("train_delta_vs_seed", F, "best_train - seed_train"),
        ("holdout_seed", F, "seed score on holdout"), ("holdout_null_raw", F, "null raw objective on holdout"),
        ("best_holdout", F, "champion score on holdout"), ("holdout_delta", F, "best_holdout - holdout_seed (the only citable uplift)"),
        ("uplift_valid", S, "true / false / null"), ("uplift_note", S, "why"), ("llm_calls", I, "model calls"),
        ("prompt_tokens", I, "prompt tokens"), ("output_tokens", I, "output tokens"), ("thinking_tokens", I, "thinking tokens"),
        ("cost_usd_est", F, "estimated USD (see pricing_note)"), ("model_mix", S, "mutator models and weights"),
        ("instance_train_sha", S, "train instance content hash"), ("instance_holdout_sha", S, "holdout instance content hash"),
        ("best_rationale", S, "the champion's lineage rationales"), ("best_diff_vs_seed", S, "unified diff of the champion vs seed"),
        ("honesty_note", S, "provenance statement"), ("pricing_note", S, "cost estimate basis")]),
    "lab_programs": _t("Every candidate program of every run.", [
        ("run_id", S, "run"), ("problem", S, "problem"), ("idx", I, "program index (0 = seed)"), ("program_id", S, "id"),
        ("parent_id", S, "parent"), ("island", I, "island"), ("model", S, "mutator model"), ("valid", B, "feasible"),
        ("kind", S, "ok / policy / sandbox / static / format / diff / ..."), ("score", F, "train score JPY M (null if invalid)"),
        ("raw_score", F, "objective before the policy gate"), ("best_so_far", F, "running best feasible score"),
        ("eval_s", F, "evaluation seconds"), ("gen_latency_s", F, "generation seconds"), ("prompt_tokens", I, "tokens"),
        ("output_tokens", I, "tokens"), ("lines_added", I, "diff lines added vs parent"), ("lines_removed", I, "diff lines removed"),
        ("first_insight_label", S, "first evaluator insight label"), ("first_insight_text", S, "first evaluator insight text"),
        ("rationale", S, "mutator rationale"), ("block_sha", S, "EVOLVE-BLOCK hash")]),
    "lab_invariant_catches": _t("Invalid candidates caught by a policy invariant (one row per violated invariant).", [
        ("run_id", S, "run"), ("problem", S, "problem"), ("idx", I, "program index"), ("program_id", S, "id"), ("model", S, "model"),
        ("invariant", S, "invariant name"), ("violations", I, "violation count"), ("raw_score", F, "what it would have scored"),
        ("text", S, "insight text")]),
    "lab_holdout": _t("Holdout rescoring of the top train candidates.", [
        ("run_id", S, "run"), ("problem", S, "problem"), ("rank", I, "rank by train score"), ("program_id", S, "id"),
        ("is_seed", B, "is the seed"), ("is_champion", B, "selected on train"), ("train_score", F, "train"),
        ("holdout_score", F, "holdout (null if invalid)"), ("holdout_valid", B, "feasible on holdout"), ("holdout_kind", S, "kind"),
        ("holdout_seed", F, "seed on holdout"), ("delta_vs_seed", F, "holdout_score - holdout_seed")]),
    "lab_reviews": _t("Append-only human review log (Hold-to-Confirm in the UI).", [
        ("run_id", S, "run"), ("program_id", S, "program"), ("reviewer", S, "reviewer label"), ("note", S, "note"), ("at", S, "ISO UTC")]),
}

_CUST = [
    ("customer_id", S, "fictional id"), ("cohort", S, "train / holdout"), ("segment", S, "segment"), ("voltage", S, "HV / EHV"),
    ("contract_kw", F, "contract kW"), ("annual_mwh", F, "expected annual MWh at the forward"), ("load_factor", F, "annual load factor"),
    ("lf_band", S, "low / mid / high"), ("expected_energy_cost_jpy_kwh", F, "shape-weighted forward price"),
    ("shape_premium", F, "shape cost vs baseload forward"), ("wheeling_jpy_kwh_equiv", F, "wheeling per kWh"),
    ("capacity_cost_jpy_kwh", F, "capacity contribution per kWh"), ("coincident_peak_kw", F, "kW at the system peak"),
    ("flex_share", F, "shiftable share"), ("flex_hours", F, "shift window h"), ("forecast_mape_pct", F, "30-min deviation %"),
    ("monthly_deviation_pct", F, "monthly deviation %"), ("credit_rating", S, "A-D"), ("essential", B, "essential facility"),
    ("green_required", B, "green product"), ("tenure_years", I, "years with KBG"), ("switched_last_5y", B, "switched supplier recently"),
    ("procurement_style", S, "tender / negotiated / auto_renew"), ("risk_appetite", S, "survey proxy"), ("dr_interest", S, "survey proxy"),
    ("dr_potential_kw", F, "DR potential kW"), ("preferred_term_hint", I, "stated term preference"),
    ("competitor_quote_est_jpy_kwh", F, "noisy competitor estimate"), ("current_rate_jpy_kwh", F, "FY2025 effective rate")]
_BEH = [("customer_id", S, "id"), ("cohort", S, "cohort"), ("segment", S, "segment"), ("shape_amp", F, "diurnal amplitude"),
        ("shape_shift", I, "slot shift"), ("level_mult", F, "level multiplier"),
        ("h_risk_aversion", F, "hidden: risk aversion"), ("h_elasticity", F, "hidden: logit units per 1% price gap"),
        ("h_inertia", F, "hidden: logit utility at parity"), ("h_term_pref", I, "hidden: preferred term"),
        ("h_dr_cost", F, "hidden: DR enrolment cost JPY/kW-month"), ("h_dr_share", F, "hidden: DR share"),
        ("h_flex_response", F, "hidden: flex response"), ("h_flex_share", F, "hidden: flex share"),
        ("h_sigma_slot", F, "hidden: 30-min deviation"), ("h_sigma_month", F, "hidden: monthly deviation"),
        ("h_discipline", F, "hidden: achievable deviation reduction"), ("h_weather_corr", F, "hidden: weather correlation"),
        ("h_pd", F, "hidden: probability of default"), ("h_clv_jpy_m", F, "hidden: relationship value JPY M/yr"),
        ("h_comp_margin", F, "hidden: competitor margin JPY/kWh"), ("h_comp_noise", F, "hidden: competitor noise"),
        ("h_quote_noise", F, "hidden: quote-estimate noise")]
for _fold in ("train", "holdout", "holdout2"):
    SCHEMA[f"customers_{_fold}"] = _t(f"KBG {_fold} cohort: features visible to price_book (fictional customers).", _CUST)
    SCHEMA[f"customer_behaviour_{_fold}"] = _t(f"KBG {_fold} cohort: hidden evaluator behaviour (never shown to candidates).", _BEH)
