"""Deterministic generator for the AlphaEvolve Energy Lab (CALIBRATED SYNTHETIC DATA).

    python data/generate.py            # CSVs (data/out), schema.json, evaluator instances (data/instances) + manifest

Everything is seeded; re-running reproduces identical CSVs and identical instance content hashes, so the baseline
locks in energy_lab/problems/*/baseline_lock.json keep holding after the gitignored instance cache is rebuilt.
Calibration targets and citations: docs/SCENARIO_AND_DATA.md (source: docs/research/MARKET_FACTS.md).
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from energy_lab.config import INSTANCE_DIR, OUT_DIR, SCHEMA_PATH  # noqa: E402
from energy_lab.problems.tariff_pricing import model as tm  # noqa: E402
from energy_lab.sim import facts  # noqa: E402
from energy_lab.sim.assets import BESS, BESS_SITES, PV_PPA  # noqa: E402
from energy_lab.sim.calendar import fy_days, is_holiday, is_working_day, observance, slot_label  # noqa: E402
from energy_lab.sim.history import HISTORY_REGIMES, generate_history, monthly_targets, price_stats  # noqa: E402
from energy_lab.sim.instances import (DT_NAMES, N_SCEN, SEEDS, archetype_table, build_tariff,  # noqa: E402
                                      build_trading)
from energy_lab.sim.npz import save_npz  # noqa: E402
from energy_lab.sim.portfolio import SEG, SEGMENTS  # noqa: E402
from energy_lab.sim.scenarios import generate_bank  # noqa: E402

from energy_lab.schema_def import SCHEMA  # noqa: E402


def write_csv(name: str, rows: list[dict]) -> int:
    cols = [c["name"] for c in SCHEMA[name]["columns"]]
    path = OUT_DIR / f"{name}.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in cols])
    return len(rows)


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, (bool, np.bool_)):
        return "true" if v else "false"
    if isinstance(v, (float, np.floating)):
        return f"{float(v):.6g}" if abs(float(v)) < 1e6 else f"{float(v):.2f}"
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def main() -> None:
    t0 = time.time()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    INSTANCE_DIR.mkdir(parents=True, exist_ok=True)
    counts = {}
    print("history FY2023-FY2025 ...")
    hist = generate_history(SEEDS["history"])
    print("scenario banks ...")
    tr_bank = generate_bank("train", N_SCEN["train"], SEEDS["train_bank"])
    ho_bank = generate_bank("holdout", N_SCEN["holdout"], SEEDS["holdout_bank"])
    ho2_bank = generate_bank("holdout", N_SCEN["holdout"], SEEDS["holdout2_bank"])   # fresh unseen bank (same regime mix)
    print("tariff instances ...")
    tariff = build_tariff(tr_bank, ho_bank, ho2_bank)
    print("trading instances ...")
    trading = build_trading(hist, tariff["tariff_pricing_train"]["customers"])
    kh = trading.pop("_kbg_history")
    stress = trading.pop("_stress")

    # ---- instances + manifest --------------------------------------------------------------------------------
    manifest = {"generator": "data/generate.py", "seeds": SEEDS, "hash": "sha256 over sorted (name, dtype, shape, bytes)",
                "instances": {}}
    for name, obj in {**tariff, **trading}.items():
        arrays = obj["arrays"]
        path = INSTANCE_DIR / f"{name}.npz"
        digest = save_npz(path, arrays)
        path.chmod(0o444)
        manifest["instances"][name] = {"file": path.name, "sha256": digest, "arrays": len(arrays),
                                       "bytes": path.stat().st_size}
        print(f"  {name}: {path.stat().st_size / 1e6:.1f} MB sha256 {digest[:16]}")
    tmp = INSTANCE_DIR / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, indent=1))
    tmp.replace(INSTANCE_DIR / "manifest.json")          # atomic: evaluators re-read the manifest on every call

    # ---- market_history ------------------------------------------------------------------------------------------
    rows = []
    n = len(hist["date"])
    level = hist["level"]
    for i in range(n):
        d = str(hist["date"][i])
        for t in range(48):
            rows.append({
                "ts": f"{d}T{slot_label(t + 1)}", "date": d, "fiscal_year": int(hist["fy"][i]), "month": int(hist["month"][i]),
                "slot": t + 1, "hour": t // 2, "day_of_week": int(hist["dow"][i]), "is_holiday": bool(hist["holiday"][i]),
                "is_working_day": bool(hist["working"][i]), "observance": str(hist["observance"][i]),
                "temp_c": round(float(hist["t_slot"][i, t]), 2), "area_demand_gw": round(float(hist["demand"][i, t]), 3),
                "area_demand_da_fcst_gw": round(float(hist["demand_fc_da"][i, t]), 3),
                "area_pv_gw": round(float(hist["pv"][i, t]), 3), "net_load_gw": round(float(hist["nl"][i, t]), 3),
                "reserve_margin_pct": round(float(hist["rm"][i, t]) * 100, 2),
                "tokyo_price_jpy_kwh": float(hist["tokyo"][i, t]), "system_price_jpy_kwh": float(hist["system"][i, t]),
                "intraday_bid_jpy_kwh": float(hist["id_bid"][i, t]), "intraday_ask_jpy_kwh": float(hist["id_ask"][i, t]),
                "imbalance_price_jpy_kwh": float(hist["imbalance"][i, t]),
                "scarcity_price_jpy_kwh": round(float(hist["scarcity"][i, t]), 2),
                "fuel_index": round(float(level[i]) / facts.TOKYO_ANNUAL_MEAN[2025], 4),
                "kbg_demand_mw": round(float(kh["kbg"]["demand"][i, t]), 2),
                "kbg_demand_da_fcst_mw": round(float(kh["kbg"]["da_p50"][i, t]), 2),
                "kbg_pv_mw": round(float(kh["pv"]["pv"][i, t]), 3),
                "tokyo_price_da_fcst_jpy_kwh": round(float(kh["pf"]["p50"][i, t]), 3),
            })
    counts["market_history"] = write_csv("market_history", rows)

    # ---- calendar ----------------------------------------------------------------------------------------------
    rows = []
    for fy in (2023, 2024, 2025, 2026):
        for d in fy_days(fy):
            rows.append({"date": d.isoformat(), "fiscal_year": fy, "month": d.month, "day_of_week": d.weekday(),
                         "is_holiday": is_holiday(d), "is_working_day": is_working_day(d), "observance": observance(d) or ""})
    counts["calendar"] = write_csv("calendar", rows)

    # ---- scenario banks: per scenario x month summary -------------------------------------------------------------
    rows = []
    months_fy = [4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3]
    for bank_name, bank in (("train", tr_bank), ("holdout", ho_bank)):
        for s, meta in enumerate(bank["meta"]):
            for m in months_fy:
                sel = bank["month"][s] == m
                p = bank["tokyo"][s][sel]
                imb = bank["imbalance"][s][sel]
                rows.append({"bank": bank_name, "scenario": s, "regime": meta["regime"], "stress": "+".join(meta["stress"]) or "none",
                             "month": m, "mean_price_jpy_kwh": round(float(p.mean()), 3), "max_price_jpy_kwh": float(p.max()),
                             "p95_price_jpy_kwh": round(float(np.percentile(p, 95)), 3),
                             "mean_imbalance_jpy_kwh": round(float(imb.mean()), 3), "max_imbalance_jpy_kwh": float(imb.max()),
                             "min_reserve_margin_pct": round(float(bank["rm"][s][sel].min()) * 100, 2),
                             "slots_ge_100": int((p >= 100).sum()), "annual_mean_price_jpy_kwh": round(meta["mean_price"], 3)})
    counts["scenario_monthly"] = write_csv("scenario_monthly", rows)

    # ---- customers (visible features + hidden evaluator behaviour, clearly separated) -------------------------------
    for fold in ("train", "holdout", "holdout2"):
        obj = tariff[f"tariff_pricing_{fold}"]
        feats = json.loads(str(obj["arrays"]["features_json"]))
        rows = []
        for c, f in zip(obj["customers"], feats):
            rows.append({"customer_id": c["customer_id"], "cohort": fold, **f})
        counts[f"customers_{fold}"] = write_csv(f"customers_{fold}", rows)
        rows = []
        for c in obj["customers"]:
            rows.append({"customer_id": c["customer_id"], "cohort": fold, "segment": c["segment"],
                         **{k: c[k] for k in ("shape_amp", "shape_shift", "level_mult")},
                         **{k: c[k] for k in c if k.startswith("h_")}})
        counts[f"customer_behaviour_{fold}"] = write_csv(f"customer_behaviour_{fold}", rows)

    # ---- segment archetypes ------------------------------------------------------------------------------------------
    arch = archetype_table()
    rows = []
    for k, seg in enumerate(SEGMENTS):
        for d, dname in enumerate(DT_NAMES):
            for t in range(48):
                rows.append({"segment": seg, "day_type": dname, "slot": t + 1, "hour": t // 2, "relative_load": round(float(arch[k, d, t]), 5)})
    counts["segment_archetypes"] = write_csv("segment_archetypes", rows)
    rows = []
    for name in SEGMENTS:
        s = SEG[name]
        rows.append({"segment": name, "train_customers": s.n_train, "kw_median": s.kw_median, "cooling_sens_per_c": s.cool,
                     "heating_sens_per_c": s.heat, "sigma_slot": s.sigma_slot, "sigma_month": s.sigma_month,
                     "flex_share": s.flex_share, "flex_hours": s.flex_hours, "dr_share": s.dr_share,
                     "dr_cost_median_jpy_kw_month": s.dr_cost_median, "green_prob": s.green_prob, "essential": s.essential,
                     "clv_jpy_m_per_mw_year": s.clv_per_mw, "tender_share": s.style_probs[0]})
    counts["segments"] = write_csv("segments", rows)

    # ---- cost stack ---------------------------------------------------------------------------------------------------
    rows = []
    def cs(component, voltage, period, value, unit, status, source, treatment):
        rows.append({"component": component, "voltage": voltage, "period": period, "value": value, "unit": unit,
                     "status": status, "source": source, "treatment": treatment})
    for v in ("HV", "EHV"):
        w = facts.WHEELING[v]
        cs("wheeling_basic", v, "2024-04..2026-10", w["basic"], "JPY/kW-month", "VERIFIED", "MARKET_FACTS 5.1 (TEPCO PG 託送供給等約款)", "cost; recovered via demand charge")
        cs("wheeling_basic", v, "2026-11..", w["basic_from_2026_11"], "JPY/kW-month", "VERIFIED", "MARKET_FACTS 5.1", "cost")
        cs("wheeling_energy", v, "2024-04..", w["energy"], "JPY/kWh", "VERIFIED", "MARKET_FACTS 5.1", "cost")
        cs("wheeling_energy", v, "..2024-03", w["energy_pre_2024_04"], "JPY/kWh", "VERIFIED", "MARKET_FACTS 5.1", "history only")
        cs("loss_factor", v, "FY2026", tm.LOSS_FACTOR[1 if v == "EHV" else 0], "ratio", "ESTIMATE", "MARKET_FACTS 5.4 (1.03-1.05)", "procurement = consumption x loss factor")
    for fy, val in facts.CAPACITY_PRICE_TOKYO_JPY_KW_YR.items():
        cs("capacity_auction_price", "all", f"FY{fy}", val, "JPY/kW-year", "VERIFIED", "MARKET_FACTS 5.2 (OCCTO)", "reference")
    for fy, val in facts.CAPACITY_PER_KWH_TOKYO.items():
        cs("capacity_contribution_per_kwh", "all", f"FY{fy}", val, "JPY/kWh", "ESTIMATE", "MARKET_FACTS 5.2", "reference")
    cs("capacity_contribution", "all", "FY2026", round(tm.CAPACITY_JPY_KW_YR, 1), "JPY/kW-year of coincident peak", "DERIVED",
       "252.83 bn JPY Tokyo burden (MARKET_FACTS 5.2) / 55.0 GW Tokyo H3 peak (MARKET_FACTS 7)", "cost allocated by coincident peak kW")
    for fy, val in facts.RENEWABLE_SURCHARGE.items():
        cs("renewable_surcharge", "all", f"FY{fy}", val, "JPY/kWh", "VERIFIED", "MARKET_FACTS 5.3", "pass-through; excluded from margin")
    cs("nfc_nonfit_renewable", "all", "FY2026 R1", facts.NFC_PRICE["nonFIT_renewable"], "JPY/kWh", "VERIFIED", "MARKET_FACTS 6.2", "cost for green products")
    cs("nfc_fit", "all", "FY2026 R1", facts.NFC_PRICE["FIT"], "JPY/kWh", "VERIFIED", "MARKET_FACTS 6.2", "reference")
    cs("balancing_overhead", "all", "FY2026", tm.BALANCING_OVERHEAD, "JPY/kWh", "LAB-ASSUMPTION", "this lab", "cost")
    cs("imbalance_scarcity_C", "all", "..2026-09-30", 200, "JPY/kWh", "VERIFIED", "MARKET_FACTS 3", "imbalance cap")
    cs("imbalance_scarcity_C", "all", "2026-10-01..", 300, "JPY/kWh", "VERIFIED", "MARKET_FACTS 3", "imbalance cap")
    cs("imbalance_scarcity_D", "all", "..2026-09-30", 45, "JPY/kWh", "VERIFIED", "MARKET_FACTS 3", "price at 8% reserve margin")
    cs("imbalance_scarcity_D", "all", "2026-10-01..", 50, "JPY/kWh", "VERIFIED", "MARKET_FACTS 3", "price at 8% reserve margin")
    cs("bess_degradation", "all", "FY2026", facts.BESS_DEGRADATION_JPY_KWH, "JPY/kWh discharged", "ESTIMATE", "MARKET_FACTS 12", "trading cost")
    counts["cost_stack"] = write_csv("cost_stack", rows)

    # ---- assets -------------------------------------------------------------------------------------------------------
    rows = [dict(zip(["site_id", "name", "prefecture", "power_mw", "energy_mwh", "duration_h", "commissioned", "voltage"], s))
            | {"rte": BESS["rte"], "soc_min_pct": BESS["soc_min_frac"] * 100, "soc_max_pct": BESS["soc_max_frac"] * 100,
               "operator_model": "BESS-as-a-Service"} for s in BESS_SITES]
    counts["bess_sites"] = write_csv("bess_sites", rows)
    counts["solar_ppa"] = write_csv("solar_ppa", [PV_PPA])

    # ---- trading days -------------------------------------------------------------------------------------------------
    rows = []
    for fold in ("train", "holdout"):
        a = trading[f"jepx_trading_{fold}"]["arrays"]
        for i in range(len(a["day_date"])):
            rows.append({"fold": fold, "date": str(a["day_date"][i]), "block": int(a["day_block"][i]), "tag": str(a["day_tag"][i]),
                         "kbg_energy_mwh": round(float((a["demand_mw"][i] - a["pv_mw"][i]).sum() * 0.5), 1),
                         "mean_spot_jpy_kwh": round(float(a["spot"][i].mean()), 3), "max_spot_jpy_kwh": float(a["spot"][i].max()),
                         "max_imbalance_jpy_kwh": float(a["imbalance"][i].max()),
                         "min_reserve_margin_pct": round(float(a["rm"][i].min()) * 100, 2),
                         "da_demand_mape_pct": round(float(np.abs(a["da_demand_p50"][i] / a["demand_mw"][i] - 1).mean() * 100), 2)})
    counts["trading_days"] = write_csv("trading_days", rows)

    # ---- calibration evidence -----------------------------------------------------------------------------------------
    rows = []
    targets = {
        2023: {"tokyo_mean": facts.TOKYO_ANNUAL_MEAN[2023], "system_mean": facts.SYSTEM_ANNUAL_MEAN[2023], "max": facts.MAX_TOKYO[2023]},
        2024: {"tokyo_mean": 13.66, "system_mean": 12.31, "p5": 8.50, "p50": 13.14, "p95": 20.78, "max": 49.65,
               "weekday_mean": 14.21, "weekend_mean": 12.28, "dod_logret_sd": 0.159, "spread_2h": 8.77,
               "imb_minus_spot_sd": 7.03, "imb_max": 194.11, "demand_peak": 56.99},
        2025: {"tokyo_mean": 12.45, "system_mean": 11.08, "p5": 7.96, "p50": 11.53, "p95": 19.43, "max": 45.01,
               "weekday_mean": 13.03, "weekend_mean": 11.00, "daily_mean_sd": 2.31, "daily_range_mean": 9.45,
               "within_day_sd": 2.66, "dod_logret_sd": 0.145, "lag1": 0.94, "lag48": 0.66, "floor_slots": 105,
               "spread_2h": 8.28, "imb_minus_spot_mean": -0.68, "imb_minus_spot_sd": 4.93, "imb_p5": -7.67,
               "imb_p95": 5.72, "imb_zero_share": 0.040, "imb_ge45": 38, "imb_ge100": 8, "imb_max": 131.49,
               "demand_twh": 281.4, "demand_peak": 57.67, "demand_min": 18.30, "pv_share": 0.092, "pv_max": 17.04},
    }
    sections = {"tokyo_mean": "1.2", "system_mean": "1.2", "p5": "1.5", "p50": "1.5", "p95": "1.5", "max": "1.5/1.6",
                "weekday_mean": "1.3", "weekend_mean": "1.3", "daily_mean_sd": "1.5", "daily_range_mean": "1.5",
                "within_day_sd": "1.5", "dod_logret_sd": "1.5", "lag1": "1.5", "lag48": "1.5", "floor_slots": "1.4",
                "spread_2h": "12", "imb_minus_spot_mean": "3", "imb_minus_spot_sd": "3", "imb_p5": "3", "imb_p95": "3",
                "imb_zero_share": "3", "imb_ge45": "3", "imb_ge100": "3", "imb_max": "3", "demand_twh": "7 (eria basis)",
                "demand_peak": "7", "demand_min": "7", "pv_share": "7", "pv_max": "7"}
    stats_all = {}
    for fy in (2023, 2024, 2025):
        st = price_stats(hist, fy)
        stats_all[fy] = st
        for k, v in st.items():
            if k in ("fy", "monthly"):
                continue
            tgt = targets[fy].get(k)
            rows.append({"fiscal_year": fy, "metric": k, "synthetic": round(float(v), 4),
                         "target": tgt, "abs_error": None if tgt is None else round(abs(float(v) - tgt), 4),
                         "rel_error_pct": None if not tgt else round(100 * (float(v) - tgt) / abs(tgt), 2),
                         "market_facts_section": sections.get(k, "") if tgt is not None else "",
                         "status": "calibrated" if tgt is not None else "diagnostic"})
        for m, v, tgt in zip(months_fy, st["monthly"], [monthly_targets(fy)[(fy, m)] for m in months_fy]):
            rows.append({"fiscal_year": fy, "metric": f"monthly_mean_m{m:02d}", "synthetic": round(v, 4), "target": round(tgt, 3),
                         "abs_error": round(abs(v - tgt), 4), "rel_error_pct": round(100 * (v - tgt) / tgt, 2),
                         "market_facts_section": "1.3" if fy == 2025 else "1.2 (annual) x 1.3 (FY2025 monthly profile)",
                         "status": "calibrated"})
    for bank_name, bank in (("train", tr_bank), ("holdout", ho_bank)):
        ann = np.array([m["mean_price"] for m in bank["meta"]])
        rows.append({"fiscal_year": 2026, "metric": f"{bank_name}_bank_annual_mean", "synthetic": round(float(ann.mean()), 3),
                     "target": None, "abs_error": None, "rel_error_pct": None, "market_facts_section": "1.2 (FY2026 to date 20.36)",
                     "status": "scenario"})
        rl = [m for m in bank["meta"] if m["regime"] == "realised_like"]
        if rl:
            h1 = float(np.mean([m["h1_mean"] for m in rl]))
            rows.append({"fiscal_year": 2026, "metric": f"{bank_name}_realised_like_H1_mean", "synthetic": round(h1, 3),
                         "target": 20.36, "abs_error": round(abs(h1 - 20.36), 3), "rel_error_pct": round(100 * (h1 - 20.36) / 20.36, 2),
                         "market_facts_section": "1.2/1.3", "status": "calibrated"})
    counts["calibration"] = write_csv("calibration", rows)

    # ---- evidence tables (empty until runs are exported by energy_lab.export_evidence) ------------------------------
    from energy_lab.export_evidence import export_all

    counts.update(export_all(quiet=True))

    # ---- schema.json (+ package copy for Agent Runtime) ------------------------------------------------------------
    schema = {"dataset_default": "energy_alphaevolve_lab", "tables": SCHEMA}
    SCHEMA_PATH.write_text(json.dumps(schema, indent=1))
    shutil.copyfile(SCHEMA_PATH, ROOT / "energy_lab" / "schema.json")
    total = sum((OUT_DIR / f"{k}.csv").stat().st_size for k in SCHEMA)
    (ROOT / "data" / "generation_report.json").write_text(json.dumps(
        {"row_counts": counts, "csv_total_mb": round(total / 1e6, 2), "instances": manifest["instances"],
         "stress_path": {"heat_start": stress["heat_start"], "cold_start": stress["cold_start"]},
         "calibration_fy2025": {k: v for k, v in stats_all[2025].items() if k != "monthly"}}, indent=1, default=float))
    print(json.dumps(counts, indent=0))
    print(f"CSV total {total / 1e6:.1f} MB; done in {time.time() - t0:.1f} s")


if __name__ == "__main__":
    main()
