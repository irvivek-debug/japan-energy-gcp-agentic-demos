"""BESS Strategy tools: state, policy schedules (rule_based_v1 vs forecast_aware_v2), comparison, and the
(pending-only) schedule proposal."""
from __future__ import annotations

import uuid

from ..core import bess as bess_core
from ..core.clock import DEMO_DATE, DEMO_NOW, slot_start
from ..datastore import STORE
from . import common as C

POLICY_NOTE = ("forecast_aware_v2 is a hand-tuned forecast-aware policy. AlphaEvolve (generally available on Google Cloud "
               "since 2026-07-10) is the path to evolving this policy family against the same simulator; that search is "
               "shown in the Energy Lab demo, not here.")


def get_bess_state(ts: str) -> dict:
    """Return the battery (BESS-01, 4 MW / 8 MWh, BESS-as-a-Service) state at a timestamp: state of charge,
    power, mode, available charge/discharge power, limits, and today's operating history.

    Args:
      ts: Timestamp YYYY-MM-DDTHH:MM (JST). Use 2026-08-19T13:30 for now.
    """
    try:
        t = (ts or DEMO_NOW).strip()
        if "T" not in t:
            t = f"{C.normalise_date(t)}T13:30"
        rows = STORE.query("SELECT * FROM {t:bess_state_5min} WHERE ts <= @t ORDER BY ts DESC LIMIT 1", t=t)
        if not rows:
            return C.err(f"no BESS state at or before {t}", "bess_state_5min")
        r = rows[0]
        day = STORE.query("SELECT MIN(soc_pct) AS soc_min, MAX(soc_pct) AS soc_max, "
                          "SUM(CASE WHEN power_kw > 0 THEN power_kw ELSE 0 END) / 12.0 AS discharged_kwh, "
                          "SUM(CASE WHEN power_kw < 0 THEN -power_kw ELSE 0 END) / 12.0 AS charged_kwh "
                          "FROM {t:bess_state_5min} WHERE date = @d AND ts <= @t", d=r["date"], t=r["ts"])[0]
        p = C.bess_params()
        return C.ok({
            "asset_id": "BESS-01", "ts": r["ts"], "soc_pct": C.r1(r["soc_pct"], 2), "power_kw": C.r1(r["power_kw"]), "mode": r["mode"],
            "active_policy": r["policy"], "cell_temp_c": C.r1(r["cell_temp_c"]),
            "available_discharge_kw_30min": C.r1(r["available_discharge_kw"]), "available_charge_kw_30min": C.r1(r["available_charge_kw"]),
            "energy_available_to_10pct_kwh": C.r1(max(0.0, (r["soc_pct"] - p.soc_min_pct) / 100 * p.energy_kwh * p.eff_discharge)),
            "limits": {"power_kw": p.power_kw, "energy_kwh": p.energy_kwh, "soc_min_pct": p.soc_min_pct, "soc_max_pct": p.soc_max_pct,
                       "round_trip_efficiency": round(p.eff_charge * p.eff_discharge, 3), "ramp_kw_per_min": 2000},
            "today_so_far": {"soc_min_pct": C.r1(day["soc_min"], 1), "soc_max_pct": C.r1(day["soc_max"], 1),
                             "charged_kwh": C.r1(day["charged_kwh"]), "discharged_kwh": C.r1(day["discharged_kwh"])},
        }, "bess_state_5min", "tariff_contract")
    except Exception as e:
        return C.err(str(e), "bess_state_5min")


def _run(date: str, policy: str):
    date = C.normalise_date(date)
    di = C.day_inputs(date)
    soc = float(C.bess_now()["soc_pct"]) if date == DEMO_DATE else 50.0
    p, pp = C.bess_params(), C.policy_params(date)
    r50 = bess_core.simulate(policy, soc, di, "p50", p, pp)
    r10 = bess_core.simulate(policy, soc, di, "p10", p, pp)
    return date, di, soc, r50, r10, bess_core.kpis(r50, r10, di, p)


def optimize_bess_schedule(date: str, policy: str) -> dict:
    """Compute the BESS schedule for the rest of the day under a policy and return per-slot power and SOC
    plus KPIs (DR firm contribution, SOC at the DR start, spike energy, PV-risk charging, peak import,
    deviation exposure for the p10 PV case, energy cost, SOC limit checks).

    Args:
      date: Date YYYY-MM-DD (use 2026-08-19 for today).
      policy: "forecast_aware_v2" (recommended) or "rule_based_v1" (current policy).
    """
    try:
        policy = (policy or "forecast_aware_v2").strip()
        if policy not in bess_core.POLICIES:
            return C.err(f"unknown policy '{policy}'; choose one of {list(bess_core.POLICIES)}", "bess_state_5min")
        date, di, soc, r50, r10, k = _run(date, policy)
        rows = [{"time": C.slot_rows_label(r["slot"]), "power_kw": r["power_kw"], "soc_end_pct": C.r1(r["soc_end_pct"]),
                 "import_after_bess_kw": r["import_after_bess_kw"], "flags": ",".join(f for f, on in (("DR", r["in_dr_window"]), ("spike", r["in_spike_window"]),
                                                                                                       ("pv_risk", r["pv_risk_slot"]), ("gate_closed", r["gate_closed"])) if on)}
                for r in r50 if r["slot"] <= 44]
        return C.ok({
            "date": date, "policy": policy, "soc_now_pct": C.r1(soc, 2), "power_sign": "+ discharge / - charge",
            "windows": {"dr": [C.slot_rows_label(s) for s in di.dr_slots], "jepx_spike": [C.slot_rows_label(s) for s in di.spike_slots],
                        "pv_risk": [C.slot_rows_label(s) for s in di.risk_slots], "gate_closed": [C.slot_rows_label(s) for s in di.locked_slots]},
            "import_ceiling_kw": C.r1(C.policy_params(date).v2_import_ceiling_kw),
            "month_billing_peak_to_date_kw": C.r1(C.month_peak_to_date(date)["peak_kw"]),
            "schedule": rows, "kpis": k, "policy_note": POLICY_NOTE,
        }, "bess_state_5min", "site_plan_30min", "jepx_prices_30min", "dr_events", "pv_forecast_30min", "site_load_30min")
    except Exception as e:
        return C.err(str(e), "bess_state_5min")


def compare_bess_policies(date: str) -> dict:
    """Compare rule_based_v1 (current) and forecast_aware_v2 (recommended) for a date on the same forecasts:
    DR firm kW, SOC at the DR start, spike energy, charging in PV-risk slots, peak import, deviation exposure
    (p10 PV case), BESS energy cost, and the DR payment at stake.

    Args:
      date: Date YYYY-MM-DD (use 2026-08-19 for today).
    """
    try:
        out, kp = {}, {}
        for pol in bess_core.POLICIES:
            date_n, di, soc, r50, r10, k = _run(date, pol)
            kp[pol] = k
        t = C.tariff()
        _, ev = C.dr_window(date_n)
        hours = len(di.dr_slots) * 0.5
        a, b = kp["rule_based_v1"], kp["forecast_aware_v2"]
        delta = {key: C.r1(b[key] - a[key], 1) for key in ("dr_firm_kw", "dr_energy_kwh", "spike_energy_kwh", "charge_in_pv_risk_slots_kwh",
                                                             "peak_import_p10pv_kw", "pre_event_imbalance_exposure_jpy_p10pv", "bess_energy_cost_jpy")
                 if a.get(key) is not None and b.get(key) is not None}
        dr_value = (b["dr_firm_kw"] - a["dr_firm_kw"]) * hours * t["dr_energy_rate_jpy_kwh"] if ev else 0.0
        mp = C.month_peak_to_date(date_n)
        return C.ok({
            "date": date_n, "soc_now_pct": C.r1(soc, 2), "policies": kp, "delta_v2_minus_v1": delta,
            "value_at_stake": {
                "dr_energy_payment_difference_jpy": round(dr_value),
                "dr_note": (f"BESS firm contribution to the {ev['requested_kw']:,.0f} kW DR window: v1 {a['dr_firm_kw']:,.0f} kW vs v2 {b['dr_firm_kw']:,.0f} kW "
                            f"over {hours:.1f} h at {t['dr_energy_rate_jpy_kwh']:.0f} JPY/kWh (penalty {t['dr_penalty_rate_jpy_kwh']:.0f} JPY/kWh if the plant falls short).") if ev else None,
                "bess_energy_cost_difference_jpy": delta.get("bess_energy_cost_jpy"),
                "imbalance_exposure_difference_jpy_p10pv": delta.get("pre_event_imbalance_exposure_jpy_p10pv"),
                "demand_charge": (f"Month billing peak to date {mp['peak_kw']:,.0f} kW (set {mp['date']} {slot_start(mp['slot'])}). "
                                  f"Peak import in the p10 PV case: v1 {a['peak_import_p10pv_kw']:,.0f} kW, v2 {b['peak_import_p10pv_kw']:,.0f} kW; "
                                  f"v2 caps charging at {C.policy_params(date_n).v2_import_ceiling_kw:,.0f} kW so pre-charging cannot set a new peak."),
            },
            "recommendation": "forecast_aware_v2" if b["dr_firm_kw"] >= a["dr_firm_kw"] else "rule_based_v1",
            "policy_note": POLICY_NOTE,
        }, "bess_state_5min", "site_plan_30min", "jepx_prices_30min", "dr_events", "pv_forecast_30min", "tariff_contract", "site_load_30min")
    except Exception as e:
        return C.err(str(e), "bess_state_5min")


def propose_bess_schedule(date: str, policy: str, rationale: str) -> dict:
    """Queue a BESS policy schedule for human approval (Hold-to-Confirm). Nothing executes here; the edge
    re-checks SOC and power limits at dispatch.

    Args:
      date: Date YYYY-MM-DD (use 2026-08-19 for today).
      policy: "forecast_aware_v2" or "rule_based_v1".
      rationale: One or two sentences on why, citing the key KPIs.
    """
    try:
        policy = (policy or "forecast_aware_v2").strip()
        if policy not in bess_core.POLICIES:
            return C.err(f"unknown policy '{policy}'", "bess_state_5min")
        date, di, soc, r50, r10, k = _run(date, policy)
        if k["soc_limit_violations"]:
            return C.err("schedule violates SOC limits; not proposed", "bess_state_5min")
        sched = [{"time": C.slot_rows_label(r["slot"]), "power_kw": r["power_kw"], "soc_end_pct": C.r1(r["soc_end_pct"])} for r in r50 if r["power_kw"] != 0]
        pa = {"id": f"act-{uuid.uuid4().hex[:8]}", "kind": "bess_schedule",
              "summary": (f"BESS-01 {policy} for {date}: SOC {soc:.1f} % now -> {k['soc_at_dr_start_pct']:.1f} % at the DR start, "
                          f"{k['dr_firm_kw']:,.0f} kW firm across the DR window, end SOC {k['soc_end_pct']:.1f} %."),
              "details": {"policy": policy, "date": date, "kpis": k, "schedule": sched, "rationale": rationale,
                          "sources": C.src("bess_state_5min", "site_plan_30min", "jepx_prices_30min", "pv_forecast_30min")},
              "risk": "low", "requires": "hold_to_confirm"}
        return {"status": "pending_approval", "pending_action": pa, "message": "Queued for Hold-to-Confirm approval. Nothing has been executed.",
                "source": C.src("bess_state_5min", "site_plan_30min")}
    except Exception as e:
        return C.err(str(e), "bess_state_5min")
