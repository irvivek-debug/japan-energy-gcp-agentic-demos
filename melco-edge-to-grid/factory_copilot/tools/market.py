"""Market Intelligence tools: JEPX prices, DR events, PV ensemble forecast, 30-min deviation exposure."""
from __future__ import annotations

from statistics import mean

from ..core import bess as bess_core
from ..core.clock import DEMO_DATE, normalise_date, slot_start
from ..datastore import STORE
from . import common as C


def get_jepx_prices(date: str) -> dict:
    """Return JEPX Tokyo-area 30-minute prices for a delivery date, the detected price-spike window, the
    wide-area reserve margin and the imbalance price (settled, or estimated for future slots).

    Args:
      date: Delivery date YYYY-MM-DD. Use 2026-08-19 for today (the demo clock is 2026-08-19 13:30 JST).
    """
    try:
        date = C.normalise_date(date)
        p = C.prices(date)
        if not p:
            return C.err(f"no JEPX prices for {date} (available 2026-06-01 to 2026-08-20)", "jepx_prices_30min")
        spot = [v["spot_jpy_kwh"] for v in p.values()]
        spikes = C.spike_slots(date) if date == DEMO_DATE else [s for s in p if p[s]["spot_jpy_kwh"] >= max(35.0, 1.5 * sorted(spot)[24])]
        windows = [{"start": slot_start(a), "end": slot_start(b + 1), "slots": list(range(a, b + 1)),
                    "avg_spot_jpy_kwh": C.r1(mean(p[s]["spot_jpy_kwh"] for s in range(a, b + 1)), 2),
                    "max_spot_jpy_kwh": max(p[s]["spot_jpy_kwh"] for s in range(a, b + 1)),
                    "avg_plant_price_jpy_kwh": C.r1(mean(p[s]["plant_energy_price_jpy_kwh"] for s in range(a, b + 1)), 2),
                    "max_imbalance_jpy_kwh": max(p[s]["imbalance_jpy_kwh"] for s in range(a, b + 1)),
                    "min_reserve_margin_pct": min(p[s]["reserve_margin_pct"] for s in range(a, b + 1))}
                   for a, b in C.contiguous_windows(spikes)]
        peak = max(p, key=lambda s: p[s]["spot_jpy_kwh"])
        show = range(27, 45) if date == DEMO_DATE else range(1, 49)
        rows = [{"slot": s, "time": C.slot_rows_label(s), "spot": p[s]["spot_jpy_kwh"], "intraday": p[s]["intraday_jpy_kwh"],
                 "imbalance": p[s]["imbalance_jpy_kwh"], "reserve_margin_pct": p[s]["reserve_margin_pct"],
                 "plant_price": p[s]["plant_energy_price_jpy_kwh"], "status": p[s]["price_status"]} for s in show]
        now = p.get(C.NOW_SLOT) if date == DEMO_DATE else None
        return C.ok({
            "date": date, "area": "Tokyo", "units": "JPY/kWh",
            "daily_avg_spot": C.r1(mean(spot), 2), "daily_max_spot": max(spot), "daily_min_spot": min(spot),
            "peak_slot": peak, "peak_time": C.slot_rows_label(peak),
            "spot_now": now["spot_jpy_kwh"] if now else None, "plant_price_now": now["plant_energy_price_jpy_kwh"] if now else None,
            "spike_threshold_jpy_kwh": C.r1(max(35.0, 1.5 * sorted(spot)[24]), 2),
            "spike_windows": windows,
            "slots": rows,
            "notes": [C.energy_price_note(),
                      "Imbalance price includes the scarcity adjustment on the wide-area reserve margin (45 JPY/kWh at 8 %, cap 200 JPY/kWh at 3 % until 2026-09-30; the cap rises to 300 JPY/kWh from 2026-10-01).",
                      "Synthetic prices calibrated to the FY2026 Tokyo regime (August 2026 mean about 21 JPY/kWh)."],
        }, "jepx_prices_30min", "tariff_contract")
    except Exception as e:  # never raise to the model
        return C.err(str(e), "jepx_prices_30min")


def get_dr_events(date: str) -> dict:
    """Return demand-response events: the event(s) on a date with contract terms and the estimated
    High 4 of 5 baseline, plus the settled history (including the under-delivered event).

    Args:
      date: Event date YYYY-MM-DD (use 2026-08-19 for today's dispatch). Pass an empty string for all events.
    """
    try:
        d = (date or "").strip()
        d = C.normalise_date(d) if d else ""
        t = C.tariff()
        hist = C.dr_events("")
        on_date = [e for e in hist if not d or e["date"] == d]
        out = []
        for e in on_date:
            item = {k: e[k] for k in ("event_id", "date", "start_time", "end_time", "requested_kw", "notified_at", "status", "program", "baseline_method")}
            if e["status"] == "settled":
                item.update({k: e[k] for k in ("baseline_kw", "actual_kw", "delivered_kw", "delivered_kwh", "shortfall_kwh", "payment_jpy", "penalty_jpy", "net_settlement_jpy", "notes")})
                item["performance_pct"] = C.r1(100 * e["delivered_kw"] / e["requested_kw"])
            else:
                bl = C.baseline_for(e["date"], int(e["start_slot"]), int(e["end_slot"]), C.today_adjustment_values(e["date"]))
                item["estimated_baseline"] = {"baseline_avg_kw": bl["baseline_avg_kw"], "selected_days": bl["selected_days"],
                                              "candidate_days": bl["candidate_days"], "same_day_adjustment_kw": bl["same_day_adjustment_kw"],
                                              "baseline_by_slot_kw": {slot_start(s): v for s, v in bl["baseline_kw"].items()},
                                              "note": "Adjustment slots after 13:30 use the forecast; final value is set at settlement."}
                item["notes"] = e["notes"]
                item["requested_kwh"] = e["requested_kw"] * (int(e["end_slot"]) - int(e["start_slot"])) * 0.5
            out.append(item)
        terms = {"energy_rate_jpy_kwh": t["dr_energy_rate_jpy_kwh"], "penalty_rate_jpy_kwh": t["dr_penalty_rate_jpy_kwh"],
                 "availability_jpy_kw_month": t["dr_availability_jpy_kw_month"], "contracted_capacity_kw": t["dr_contracted_capacity_kw"],
                 "payment_cap": "paid kWh capped at the requested kWh",
                 "measurement": "receiving-point import vs High 4 of 5 baseline with same-day adjustment (net of BESS charging)"}
        return C.ok({"date": d or "all", "events": out, "contract_terms": terms,
                     "history_summary": [{"event_id": e["event_id"], "date": e["date"], "requested_kw": e["requested_kw"], "delivered_kw": e["delivered_kw"],
                                          "status": e["status"], "net_settlement_jpy": e["net_settlement_jpy"]} for e in hist if e["status"] == "settled"]},
                    "dr_events", "site_load_30min", "site_plan_30min", "tariff_contract")
    except Exception as e:
        return C.err(str(e), "dr_events")


def get_pv_forecast(date: str) -> dict:
    """Return the latest PV ensemble forecast (p10 / p50 / p90 per 30-min slot) for the afternoon, the
    PV-risk slots where p10 falls far below p50, and the ensemble's calibration over the previous 14 days.

    Args:
      date: Target date YYYY-MM-DD (use 2026-08-19 for today).
    """
    try:
        date = C.normalise_date(date)
        issues = STORE.query("SELECT issued_at FROM {t:pv_forecast_30min} WHERE date = @d GROUP BY issued_at ORDER BY issued_at DESC", d=date)
        if not issues:
            return C.err(f"no PV forecast for {date}", "pv_forecast_30min")
        latest = issues[0]["issued_at"]
        rows = STORE.query("SELECT slot, p10_kw, p50_kw, p90_kw, clear_sky_kw FROM {t:pv_forecast_30min} WHERE date = @d AND issued_at = @i ORDER BY slot",
                           d=date, i=latest)
        first = C.NOW_SLOT if date == DEMO_DATE else 11
        rows = [r for r in rows if r["slot"] >= first]
        prev = {r["slot"]: r for r in STORE.query("SELECT slot, p10_kw, p50_kw FROM {t:pv_forecast_30min} WHERE date = @d AND issued_at = @i",
                                                   d=date, i=issues[-1]["issued_at"])} if len(issues) > 1 else {}
        risk = [r["slot"] for r in rows if r["p50_kw"] >= 300 and (r["p50_kw"] - r["p10_kw"]) / r["p50_kw"] >= 0.40]
        table = [{"slot": r["slot"], "time": C.slot_rows_label(r["slot"]), "p10_kw": C.r1(r["p10_kw"]), "p50_kw": C.r1(r["p50_kw"]),
                  "p90_kw": C.r1(r["p90_kw"]), "p10_gap_pct": C.r1(100 * (r["p50_kw"] - r["p10_kw"]) / r["p50_kw"]) if r["p50_kw"] > 0 else None,
                  "pv_risk_slot": r["slot"] in risk} for r in rows]
        worst = max(rows, key=lambda r: r["p50_kw"] - r["p10_kw"]) if rows else None
        cal = STORE.query(
            "WITH a AS (SELECT date, slot, AVG(pv_kw) AS act FROM {t:pv_actual_5min} WHERE date < @d AND date >= @d0 GROUP BY date, slot) "
            "SELECT COUNT(*) AS n, SUM(CASE WHEN a.act >= f.p10_kw AND a.act <= f.p90_kw THEN 1 ELSE 0 END) AS inside, "
            "AVG(ABS(a.act - f.p50_kw)) AS mae, SUM(CASE WHEN a.act < f.p10_kw THEN 1 ELSE 0 END) AS below_p10 "
            "FROM a JOIN {t:pv_forecast_30min} f ON f.date = a.date AND f.slot = a.slot WHERE f.p50_kw > 50",
            d=date, d0=C._minus_days(date, 14))[0]
        now_act = STORE.query("SELECT pv_kw FROM {t:pv_actual_5min} WHERE date = @d ORDER BY ts DESC LIMIT 1", d=date)
        return C.ok({
            "date": date, "issued_at": latest, "earlier_issue": issues[-1]["issued_at"] if len(issues) > 1 else None,
            "model": "WeatherNext-class 64-member ensemble (simulated; production would use WeatherNext 3 hourly runs)",
            "pv_capacity_kwp": 3000, "pv_now_kw": C.r1(now_act[0]["pv_kw"]) if now_act else None,
            "slots": table,
            "pv_risk_slots": [C.slot_rows_label(s) for s in risk],
            "deepest_gap": {"time": C.slot_rows_label(worst["slot"]), "p10_kw": C.r1(worst["p10_kw"]), "p50_kw": C.r1(worst["p50_kw"]),
                            "p90_kw": C.r1(worst["p90_kw"]), "gap_kw": C.r1(worst["p50_kw"] - worst["p10_kw"])} if worst else None,
            "afternoon_energy_kwh": {k: C.r1(sum(r[f"{k}_kw"] for r in rows) * 0.5) for k in ("p10", "p50", "p90")},
            "sharpening": ({"slot": C.slot_rows_label(worst["slot"]), "p10_at_earlier_issue_kw": C.r1(prev[worst["slot"]]["p10_kw"]),
                            "p10_at_latest_issue_kw": C.r1(worst["p10_kw"])} if worst and worst["slot"] in prev else None),
            "calibration_14d": {"slots_scored": int(cal["n"] or 0),
                                "p10_p90_coverage_pct": C.r1(100 * (cal["inside"] or 0) / cal["n"]) if cal["n"] else None,
                                "below_p10_pct": C.r1(100 * (cal["below_p10"] or 0) / cal["n"]) if cal["n"] else None,
                                "p50_mae_kw": C.r1(cal["mae"])},
        }, "pv_forecast_30min", "pv_actual_5min")
    except Exception as e:
        return C.err(str(e), "pv_forecast_30min")


def get_deviation_exposure(date: str) -> dict:
    """Return the 30-minute plan-vs-actual exposure for the rest of the day if nothing changes: the
    day-ahead nomination, forecast import (PV p50 and p10) with the current BESS policy, the +/-7.5 %
    band, and the imbalance cost at risk per slot.

    Args:
      date: Date YYYY-MM-DD (use 2026-08-19 for today).
    """
    try:
        date = C.normalise_date(date)
        di = C.day_inputs(date)
        p = C.bess_params()
        pp = C.policy_params(date)
        soc = float(C.bess_now()["soc_pct"])
        r50 = bess_core.simulate("rule_based_v1", soc, di, "p50", p, pp)
        r10 = bess_core.simulate("rule_based_v1", soc, di, "p10", p, pp)
        rows, risk50, risk10 = [], 0.0, 0.0
        for a, b in zip(r50, r10):
            s = a["slot"]
            ex50 = max(0.0, abs(a["deviation_kw"]) - a["band_kw"]) * 0.5
            ex10 = max(0.0, abs(b["deviation_kw"]) - b["band_kw"]) * 0.5
            imb = di.imbalance.get(s, 0.0)
            risk50 += ex50 * imb
            risk10 += ex10 * imb
            rows.append({"slot": s, "time": C.slot_rows_label(s), "nominated_kw": a["nomination_kw"], "forecast_import_p50_kw": a["import_after_bess_kw"],
                         "forecast_import_p10pv_kw": b["import_after_bess_kw"], "band_kw": a["band_kw"],
                         "deviation_p50_pct": C.r1(100 * a["deviation_kw"] / a["nomination_kw"]) if a["nomination_kw"] else None,
                         "deviation_p10pv_pct": C.r1(100 * b["deviation_kw"] / b["nomination_kw"]) if b["nomination_kw"] else None,
                         "imbalance_est_jpy_kwh": imb, "at_risk_p10pv_jpy": round(ex10 * imb), "gate_closed": s in di.locked_slots,
                         "in_dr_window": s in di.dr_slots})
        outside10 = [r for r in rows if r["at_risk_p10pv_jpy"] > 0]
        _, ev = C.dr_window(date)
        dr_note = None
        if ev and di.dr_slots:
            nom = mean(di.nominated[s] for s in di.dr_slots if s in di.nominated)
            dr_note = (f"During the DR window the aggregator re-nominates the plan. A {ev['requested_kw']:,.0f} kW shed without re-nomination "
                       f"would sit {100 * ev['requested_kw'] / nom:.1f} % below the nominated {nom:,.0f} kW, far outside the band.")
        return C.ok({
            "date": date, "band_pct": di.band_pct, "policy_assumed": "rule_based_v1 (current BESS policy), no DR action",
            "gate_closure": "slots starting within 60 min cannot be re-nominated: " + ", ".join(C.slot_rows_label(s) for s in di.locked_slots),
            "slots": rows,
            "summary": {"imbalance_at_risk_p50_jpy": round(risk50), "imbalance_at_risk_p10pv_jpy": round(risk10),
                        "slots_outside_band_p10pv": [r["time"] for r in outside10],
                        "worst_slot_p10pv": max(rows, key=lambda r: abs(r["deviation_p10pv_pct"] or 0))["time"] if rows else None},
            "dr_note": dr_note,
        }, "site_plan_30min", "jepx_prices_30min", "bess_state_5min", "tariff_contract")
    except Exception as e:
        return C.err(str(e), "site_plan_30min")
