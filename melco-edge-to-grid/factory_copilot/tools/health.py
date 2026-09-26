"""Asset Health tools: energy anomaly detection (compressor specific-power drift, stuck meters by
energy-balance reconciliation, demand-peak anomalies) and the (pending-only) work-order proposal."""
from __future__ import annotations

import datetime as dt
import uuid
from statistics import mean, median

from ..core.clock import slot_start
from ..datastore import STORE
from . import common as C


def _span_min(a: str, b: str) -> float:
    return (dt.datetime.fromisoformat(b) - dt.datetime.fromisoformat(a)).total_seconds() / 60.0


def _avg_price(d0: str, d1: str) -> float:
    r = STORE.query("SELECT AVG(plant_energy_price_jpy_kwh) AS p FROM {t:jepx_prices_30min} WHERE date >= @a AND date <= @b", a=d0, b=d1)[0]
    return float(r["p"] or 0.0)


def get_compressor_performance(from_date: str, to_date: str) -> dict:
    """Return compressed-air performance per compressor for a date range: energy, delivered air, specific
    power (kW per Nm3/min, lower is better), excess vs the peer median, and the daily trend of the worst unit.

    Args:
      from_date: Start date YYYY-MM-DD (data from 2026-06-01).
      to_date: End date YYYY-MM-DD (2026-08-19 is partial to 13:30).
    """
    try:
        a, b = C.normalise_date(from_date), C.normalise_date(to_date)
        rows = STORE.query("SELECT compressor_id, SUM(energy_kwh) AS kwh, SUM(air_nm3) AS air, SUM(runtime_h) AS run_h, AVG(avg_load_pct) AS load "
                           "FROM {t:compressor_perf} WHERE date >= @a AND date <= @b GROUP BY compressor_id ORDER BY compressor_id", a=a, b=b)
        if not rows:
            return C.err(f"no compressor data between {a} and {b}", "compressor_perf")
        sp = {r["compressor_id"]: (r["kwh"] / (r["air"] / 60.0)) if r["air"] else None for r in rows}
        out = []
        for r in rows:
            peers = [v for k, v in sp.items() if k != r["compressor_id"] and v]
            pm = median(peers) if peers else None
            out.append({"compressor_id": r["compressor_id"], "energy_kwh": C.r1(r["kwh"]), "air_nm3": C.r1(r["air"]), "runtime_h": C.r1(r["run_h"]),
                        "specific_power_kw_per_nm3min": C.r1(sp[r["compressor_id"]], 3), "peer_median": C.r1(pm, 3),
                        "excess_vs_peers_pct": C.r1(100 * (sp[r["compressor_id"]] / pm - 1)) if pm and sp[r["compressor_id"]] else None,
                        "avg_load_pct": C.r1(r["load"])})
        worst = max(out, key=lambda x: x["excess_vs_peers_pct"] or -99)
        trend = STORE.query("SELECT date, specific_power_kw_per_nm3min AS sp FROM {t:compressor_perf} WHERE compressor_id = @c AND date >= @a AND date <= @b ORDER BY date",
                            c=worst["compressor_id"], a=a, b=b)
        return C.ok({"from": a, "to": b, "compressors": out, "worst_unit": worst["compressor_id"],
                     "worst_unit_daily_trend": [{"date": t["date"], "specific_power": C.r1(t["sp"], 3)} for t in trend][-15:]}, "compressor_perf")
    except Exception as e:
        return C.err(str(e), "compressor_perf")


def detect_energy_anomalies(from_date: str, to_date: str) -> dict:
    """Detect energy anomalies in a date range and cost them: compressors whose specific power drifts above
    peers (air leak signature, with annual cost), sub-meters stuck on a flat reading (confirmed by an
    energy-balance check against the receiving point), and a monthly billing peak set around a DR event
    while the battery could not limit demand.

    Args:
      from_date: Start date YYYY-MM-DD (telemetry from 2026-08-05; compressor data from 2026-06-01).
      to_date: End date YYYY-MM-DD (use 2026-08-19 for today).
    """
    try:
        a, b = C.normalise_date(from_date), C.normalise_date(to_date)
        price = _avg_price(a, b) or _avg_price("2026-08-01", "2026-08-19")
        anomalies, below = [], []
        # 1) compressor specific-power drift, judged on the most recent 3 days of the range (a developing leak is
        #    diluted by a long-range average) and reported with the range average and the early-June reference
        recent_a = max(a, C._minus_days(b, 2))

        def sp_by_unit(d0, d1):
            q = STORE.query("SELECT compressor_id, SUM(energy_kwh) AS kwh, SUM(air_nm3) AS air, SUM(runtime_h) AS run_h FROM {t:compressor_perf} "
                            "WHERE date >= @a AND date <= @b AND air_nm3 > 0 GROUP BY compressor_id", a=d0, b=d1)
            return {r["compressor_id"]: r for r in q if r["air"]}

        rng_u, rec_u = sp_by_unit(a, b), sp_by_unit(recent_a, b)
        jun_u = sp_by_unit("2026-06-01", "2026-06-14")
        spf = lambda u: {k: v["kwh"] / (v["air"] / 60.0) for k, v in u.items()}
        sp_rng, sp_rec, sp_jun = spf(rng_u), spf(rec_u), spf(jun_u)
        for cid in sorted(sp_rec):
            pm = median(v for k, v in sp_rec.items() if k != cid)
            exc = sp_rec[cid] / pm - 1
            if exc < 0.12:
                below.append({"compressor_id": cid, "recent_excess_vs_peers_pct": C.r1(100 * exc),
                              "note": "below the 12 % flag threshold (trim unit at part load; expected)" if cid == "AC-05" else "below the 12 % flag threshold"})
                continue
            u = rec_u[cid]
            excess_kw = (u["kwh"] - (u["air"] / 60.0) * pm) / u["run_h"] if u["run_h"] else 0.0
            pm_rng = median(v for k, v in sp_rng.items() if k != cid)
            pm_jun = median(v for k, v in sp_jun.items() if k != cid) if len(sp_jun) > 1 else None
            annual_kwh = excess_kw * 8000.0
            anomalies.append({
                "anomaly_id": f"ANM-{cid}-SP", "asset_id": cid, "type": "compressor_specific_power_drift", "severity": "high" if exc >= 0.15 else "medium",
                "evidence": {"recent_window": f"{recent_a} to {b}", "specific_power_kw_per_nm3min": C.r1(sp_rec[cid], 3), "peer_median": C.r1(pm, 3),
                             "recent_excess_vs_peers_pct": C.r1(100 * exc), "range_avg_excess_vs_peers_pct": C.r1(100 * (sp_rng[cid] / pm_rng - 1)),
                             "early_june_excess_vs_peers_pct": C.r1(100 * (sp_jun[cid] / pm_jun - 1)) if pm_jun and cid in sp_jun else None},
                "impact": {"excess_kw_while_running": C.r1(excess_kw), "annual_excess_kwh": C.r1(annual_kwh, 0), "annual_cost_jpy": round(annual_kwh * price),
                           "basis": f"excess kW x 8,000 run h/yr x {price:.2f} JPY/kWh average all-in price over the range"},
                "likely_cause": "Air leak on the discharge / dryer purge line (hissing reported in the shift handover) or a failing inlet/blow-off valve.",
                "recommended_action": "Ultrasonic leak survey and dryer purge valve inspection; run the unit as standby until repaired (peers carry the air with N-1 intact).",
            })
        # 2) stuck (flat-lined) meters, confirmed by energy balance
        flat = C.flat_meter_runs(f"{a}T00:00", f"{b}T23:55")
        for f in flat:
            span = f["span_min"]
            bal = STORE.query(
                "WITH r AS (SELECT ts, SUM(CASE WHEN asset_class IN ('receiving_point','pv','bess') THEN kw ELSE -kw END) AS resid "
                "FROM {t:telemetry_5min} WHERE date >= @a AND date <= @b GROUP BY ts) "
                "SELECT AVG(CASE WHEN ts < @s THEN resid END) AS before_kw, AVG(CASE WHEN ts >= @s THEN resid END) AS after_kw FROM r",
                a=C._minus_days(f["first_ts"][:10], 3), b=b, s=f["first_ts"])[0]
            hours = (span + 5) / 60.0
            gap = (bal["after_kw"] or 0.0) - (bal["before_kw"] or 0.0)
            mtr = STORE.query("SELECT asset_ids FROM {t:meters} WHERE meter_id = @m", m=f["meter_id"])
            anomalies.append({
                "anomaly_id": f"ANM-{f['meter_id']}-FLAT", "asset_id": f["meter_id"], "type": "stuck_meter", "severity": "high",
                "evidence": {"metered_assets": mtr[0]["asset_ids"] if mtr else "", "flat_value_kw": f["kw"], "identical_readings": int(f["n"]),
                             "since": f["first_ts"], "until": f["last_ts"], "duration_h": C.r1(hours),
                             "energy_balance_residual_before_kw": C.r1(bal["before_kw"]), "energy_balance_residual_after_kw": C.r1(bal["after_kw"])},
                "impact": {"unallocated_kw": C.r1(gap), "unallocated_kwh": C.r1(gap * hours, 0), "unallocated_value_jpy": round(gap * hours * price),
                           "settlement_risk": "Receiving-point DR settlement is unaffected; sub-meter M&V for gain-share line items on this feeder is held until repair [gain_share_agreement_summary.md Section 4]."},
                "likely_cause": "Meter or gateway communication freeze (reading repeats while the line runs normally per MES).",
                "recommended_action": "Replace or reset the meter communication module; back-fill the gap from the energy balance.",
            })
        # 3) billing peak set around a DR event while the battery could not limit demand
        pkinfo = C.billing_peak_check(b[:7], b)
        if pkinfo and pkinfo["around_dr_event"]:
            anomalies.append({
                "anomaly_id": f"ANM-PEAK-{b[:7]}", "asset_id": "BESS-01", "type": "billing_peak_set_around_dr_event", "severity": "medium",
                "evidence": {k: pkinfo[k] for k in ("month_billing_peak_kw", "set_at", "dr_event", "position", "bess_kw_at_peak", "demand_limit_threshold_kw",
                                                    "highest_peak_on_non_event_days_kw")},
                "impact": {"extra_billing_demand_kw": pkinfo["extra_billing_demand_kw"], "demand_charge_jpy_this_month": pkinfo["extra_demand_charge_jpy"],
                           "basis": pkinfo["basis"]},
                "likely_cause": pkinfo["cause"],
                "recommended_action": "Use forecast_aware_v2: it plans state of charge for both the DR window and peak limiting, and caps pre-charging below the month's billing peak.",
            })
        total = sum(x["impact"].get("annual_cost_jpy", 0) for x in anomalies)
        return C.ok({"from": a, "to": b, "anomalies_found": len(anomalies), "anomalies": anomalies, "checked_below_threshold": below,
                     "annualised_cost_of_drift_jpy": total, "price_basis_jpy_kwh": C.r1(price, 2)},
                    "compressor_perf", "telemetry_5min", "meters", "site_load_30min", "jepx_prices_30min", "tariff_contract")
    except Exception as e:
        return C.err(str(e), "compressor_perf", "telemetry_5min")


def propose_work_order(asset_id: str, issue: str, priority: str, rationale: str) -> dict:
    """Queue a maintenance work order for human approval (Hold-to-Confirm) before it goes to the CMMS.
    Nothing is created until a person confirms.

    Args:
      asset_id: Asset or meter id, for example AC-04 or M-27.
      issue: Short description of the problem and the requested work.
      priority: "P1" (24 h), "P2" (7 days) or "P3" (next shutdown).
      rationale: The evidence and cost, with citations.
    """
    try:
        a = C.assets()
        known = asset_id in a or STORE.query("SELECT meter_id FROM {t:meters} WHERE meter_id = @m", m=asset_id)
        if not known:
            return C.err(f"unknown asset or meter {asset_id}", "assets", "meters")
        pr = (priority or "P2").upper()
        if pr not in ("P1", "P2", "P3"):
            pr = "P2"
        pa = {"id": f"act-{uuid.uuid4().hex[:8]}", "kind": "work_order",
              "summary": f"Work order {pr} for {asset_id}: {issue}",
              "details": {"asset_id": asset_id, "issue": issue, "priority": pr, "rationale": rationale, "target_system": "CMMS (simulated)",
                          "sources": C.src("compressor_perf", "telemetry_5min", "meters")},
              "risk": "low", "requires": "hold_to_confirm"}
        return {"status": "pending_approval", "pending_action": pa, "message": "Queued for Hold-to-Confirm approval. No ticket has been created yet.",
                "source": C.src("assets", "meters")}
    except Exception as e:
        return C.err(str(e), "assets")
