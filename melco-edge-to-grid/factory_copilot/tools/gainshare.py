"""Gain-Share tools: per-event savings (settled or planned), monthly gain-share invoice, savings ledger."""
from __future__ import annotations

from statistics import mean

from ..core import bess as bess_core
from ..core import dr_math, registry
from ..core.clock import DEMO_DATE, slot_start
from ..datastore import STORE
from ..edge.interlock_engine import evaluate_plan
from . import common as C


def _recommended_plan_result(date: str, start: str, end: str, event_id: str, target: float) -> dict:
    plan, _, _ = C.draft_plan(date, start, end, event_id, target)
    return evaluate_plan(plan, C.edge_context(date))


def compute_event_savings(event_id: str, plan_id: str = "") -> dict:
    """Compute the savings of a DR event. Settled events: settlement, energy value and gain-share split.
    Today's event: estimate for an edge-verified plan (plan_id from simulate_edge_interlock, or the
    recommended plan if empty): measured delivery vs the High 4 of 5 baseline, DR payment or penalty,
    energy cost avoided net of rebound and battery charging, demand charge and imbalance effects.

    Args:
      event_id: DR event id, for example DR-20260819 (today) or DR-20260722.
      plan_id: Optional plan_id from simulate_edge_interlock; empty uses the recommended plan.
    """
    try:
        rows = STORE.query("SELECT * FROM {t:dr_events} WHERE event_id = @e", e=(event_id or "").strip())
        if not rows:
            ids = [r["event_id"] for r in C.dr_events("")]
            return C.err(f"unknown event {event_id}; known events: {ids}", "dr_events")
        ev = rows[0]
        t = C.tariff()
        share = t["gain_share_pct"] / 100.0
        s0, s1 = int(ev["start_slot"]), int(ev["end_slot"])
        slots = list(range(s0, s1))
        price = C.prices(ev["date"])
        if ev["status"] == "settled":
            bl = C.baseline_for(ev["date"], s0, s1)
            act = {int(r["slot"]): float(r["import_kw"]) for r in STORE.query("SELECT slot, import_kw FROM {t:site_load_30min} WHERE date = @d", d=ev["date"])}
            st = dr_math.settle_event(ev["requested_kw"], bl["baseline_kw"], {s: act[s] for s in slots}, t["dr_energy_rate_jpy_kwh"],
                                      t["dr_penalty_rate_jpy_kwh"], t["dr_payment_cap_ratio"])
            energy = sum(max(0.0, st["delivered_by_slot_kw"][s]) * 0.5 * price[s]["plant_energy_price_jpy_kwh"] for s in slots) if price else None
            gross = st["payment_jpy"] - st["penalty_jpy"] + (energy or 0.0)
            return C.ok({
                "event_id": ev["event_id"], "date": ev["date"], "window": f"{ev['start_time']}-{ev['end_time']}", "status": "settled",
                "requested_kw": ev["requested_kw"], "baseline_avg_kw": st["baseline_avg_kw"], "actual_avg_kw": st["actual_avg_kw"],
                "delivered_avg_kw": st["delivered_avg_kw"], "performance_pct": st["performance_pct"], "delivered_kwh": st["delivered_kwh"],
                "shortfall_kwh": st["shortfall_kwh"], "baseline_days": bl["selected_days"], "same_day_adjustment_kw": bl["same_day_adjustment_kw"],
                "dr_payment_jpy": st["payment_jpy"], "dr_penalty_jpy": st["penalty_jpy"],
                "energy_cost_avoided_jpy": round(energy) if energy is not None else None,
                "event_value_jpy": round(gross), "vendor_gain_share_jpy": round(max(0.0, gross) * share), "client_share_jpy": round(gross - max(0.0, gross) * share),
                "reconciles_with_aggregator": abs(st["delivered_avg_kw"] - ev["delivered_kw"]) < 1.0 and abs(st["penalty_jpy"] - ev["penalty_jpy"]) < 2,
                "notes": ev["notes"],
            }, "dr_events", "site_load_30min", "jepx_prices_30min", "tariff_contract")

        # --- today's event: estimate for an edge-verified plan
        rec = registry.get(plan_id) if plan_id else None
        if rec:
            res, used = rec["result"], plan_id
        else:
            res = _recommended_plan_result(ev["date"], ev["start_time"], ev["end_time"], ev["event_id"], ev["requested_kw"])
            used = f"{res['plan_id']} (recommended plan, edge-verified in this call)"
        red = {r["slot"]: r["reduction_kw"] for r in res["by_slot"]}
        missing = [s for s in slots if s not in red]
        coverage = None
        if missing:
            coverage = (f"Plan {res['plan_id']} covers {res['window']['start']}-{res['window']['end']}, which misses "
                        f"{', '.join(C.slot_rows_label(s) for s in missing)} of the {ev['start_time']}-{ev['end_time']} DR window; "
                        "those slots count as zero reduction. Build the plan on a window that includes the whole DR window.")
        sp = C.site_plan(ev["date"])
        fc = {s: float(sp[s]["forecast_import_p50_kw"]) for s in slots}
        planned = {s: fc[s] - red.get(s, 0.0) for s in slots}
        bl = C.baseline_for(ev["date"], s0, s1, C.today_adjustment_values(ev["date"]))
        st = dr_math.settle_event(ev["requested_kw"], bl["baseline_kw"], planned, t["dr_energy_rate_jpy_kwh"], t["dr_penalty_rate_jpy_kwh"], t["dr_payment_cap_ratio"])
        bess_act = next((a for a in res["actions"] if a["asset_id"] == "BESS-01" and a["verdict"] != "REJECT"), None)
        bess_by = bess_act["granted_by_slot"] if bess_act and "granted_by_slot" in bess_act else {}
        if bess_act and not bess_by:
            full = registry.get(res["plan_id"])
            bess_by = next((a["granted_by_slot"] for a in (full["result"]["actions"] if full else []) if a["asset_id"] == "BESS-01"), {})
        load_red = {s: red.get(s, 0.0) - bess_by.get(s, 0.0) for s in slots}
        pp = {s: price[s]["plant_energy_price_jpy_kwh"] for s in price}
        evening = mean(pp[s] for s in range(41, 49))
        rebound_kwh = res["summary"]["rebound_kwh_after_window"]
        load_value = sum(load_red[s] * 0.5 * pp[s] for s in slots) - rebound_kwh * evening
        # battery: value of window discharge minus the pre-charge that made it possible, minus wear
        di = C.day_inputs(ev["date"])
        v2 = bess_core.simulate("forecast_aware_v2", float(C.bess_now()["soc_pct"]), di, "p50", C.bess_params(), C.policy_params(ev["date"]))
        v1 = bess_core.simulate("rule_based_v1", float(C.bess_now()["soc_pct"]), di, "p50", C.bess_params(), C.policy_params(ev["date"]))
        pre = [r for r in v2 if r["slot"] < s0]
        charge_cost = sum(-r["power_kw"] * 0.5 * pp[r["slot"]] for r in pre if r["power_kw"] < 0)
        v1_pre_cost = sum(-r["power_kw"] * 0.5 * pp[r["slot"]] for r in v1 if r["slot"] < s0 and r["power_kw"] < 0)
        dis_kwh = sum(bess_by.get(s, 0.0) * 0.5 for s in slots)
        bess_value = sum(bess_by.get(s, 0.0) * 0.5 * pp[s] for s in slots) - (charge_cost - v1_pre_cost) - dis_kwh * t["bess_degradation_jpy_kwh"]
        # demand charge: compare no-action peak (v1, PV p50) and plan peak with the month's billing peak to date
        mp = C.month_peak_to_date(ev["date"])["peak_kw"]
        noact_peak = max(r["import_after_bess_kw"] for r in v1)
        plan_peak = max(r["import_after_bess_kw"] - (load_red.get(r["slot"], 0.0)) for r in v2)
        dem = max(0.0, max(noact_peak, mp) - max(plan_peak, mp)) * t["demand_charge_jpy_kw_month"]
        k1 = bess_core.kpis(v1, bess_core.simulate("rule_based_v1", float(C.bess_now()["soc_pct"]), di, "p10", C.bess_params(), C.policy_params(ev["date"])), di)
        k2 = bess_core.kpis(v2, bess_core.simulate("forecast_aware_v2", float(C.bess_now()["soc_pct"]), di, "p10", C.bess_params(), C.policy_params(ev["date"])), di)
        imb = k1["pre_event_imbalance_exposure_jpy_p10pv"] - k2["pre_event_imbalance_exposure_jpy_p10pv"]
        dr_net = st["payment_jpy"] - st["penalty_jpy"]
        total = dr_net + load_value + bess_value + dem + imb
        return C.ok({
            "event_id": ev["event_id"], "date": ev["date"], "window": f"{ev['start_time']}-{ev['end_time']}", "status": "estimate",
            "plan_used": used, "requested_kw": ev["requested_kw"], "coverage_warning": coverage,
            "physical_firm_reduction_kw": res["summary"]["firm_reduction_kw"], "physical_avg_reduction_kw": res["summary"]["average_reduction_kw"],
            "estimated_baseline_avg_kw": bl["baseline_avg_kw"], "baseline_days": bl["selected_days"], "same_day_adjustment_kw": bl["same_day_adjustment_kw"],
            "forecast_import_no_action_avg_kw": C.r1(mean(fc.values())), "planned_import_avg_kw": C.r1(mean(planned.values())),
            "estimated_measured_delivery_avg_kw": st["delivered_avg_kw"], "estimated_measured_delivery_min_slot_kw": st["delivered_min_kw"],
            "estimated_performance_pct": st["performance_pct"],
            "value_breakdown_jpy": {
                "dr_energy_payment": st["payment_jpy"], "dr_penalty": -st["penalty_jpy"],
                "load_shift_energy_cost_avoided_net_of_rebound": round(load_value),
                "battery_energy_value_net_of_precharge_and_wear": round(bess_value),
                "demand_charge_avoided": round(dem),
                "imbalance_risk_avoided_p10pv": round(imb),
            },
            "event_value_jpy": round(total),
            "vendor_gain_share_jpy": round(max(0.0, total) * share), "client_share_jpy": round(total - max(0.0, total) * share),
            "gain_share_pct": t["gain_share_pct"],
            "assumptions": [
                f"Measured delivery = estimated baseline minus planned import (receiving point); the baseline adjustment uses the forecast after 13:30.",
                f"Rebound {rebound_kwh:,.0f} kWh (deferred burn-in, van charging, thermal-storage recharge) valued at the 20:00-24:00 average of {evening:.2f} JPY/kWh.",
                f"Battery wear {t['bess_degradation_jpy_kwh']:.0f} JPY per kWh discharged; pre-charge cost is the extra charging versus the current policy.",
                (f"Demand charge: month billing peak to date {mp:,.0f} kW; no-action peak today {noact_peak:,.0f} kW; plan peak {plan_peak:,.0f} kW. "
                 + ("Neither exceeds the month peak, so no demand charge is avoided today." if dem == 0 else "")),
                "Imbalance risk avoided compares pre-event deviation exposure of the current and recommended BESS policies in the p10 PV case.",
            ],
        }, "dr_events", "site_load_30min", "site_plan_30min", "jepx_prices_30min", "tariff_contract", "bess_state_5min", "interlock_rules")
    except Exception as e:
        return C.err(str(e), "dr_events")


def compute_gain_share(month: str) -> dict:
    """Compute the monthly gain-share invoice: verified savings by category, eligible savings, the equipment
    vendor's gain share (contract %), the BESS-as-a-Service fee, the client's net benefit, and a check that
    DR lines reconcile with the aggregator settlements.

    Args:
      month: Month YYYY-MM, for example 2026-07.
    """
    try:
        m = (month or "").strip()[:7]
        rows = STORE.query("SELECT category, amount_jpy, gain_share_eligible, basis, event_ids FROM {t:savings_ledger} WHERE month = @m ORDER BY category", m=m)
        if not rows:
            return C.err(f"no savings ledger for {m} (available 2026-01 to 2026-07)", "savings_ledger")
        t = C.tariff()
        pct = t["gain_share_pct"]
        eligible = sum(r["amount_jpy"] for r in rows if r["gain_share_eligible"])
        total = sum(r["amount_jpy"] for r in rows)
        share = max(0.0, eligible) * pct / 100.0
        fee = t["baas_fee_jpy_month"]
        evs = STORE.query("SELECT event_id, payment_jpy, penalty_jpy, delivered_kw, requested_kw FROM {t:dr_events} WHERE status = 'settled' AND date >= @a AND date <= @b",
                          a=f"{m}-01", b=f"{m}-31")
        led_pay = sum(r["amount_jpy"] for r in rows if r["category"] == "dr_energy_payment")
        led_pen = -sum(r["amount_jpy"] for r in rows if r["category"] == "dr_penalty")
        lost = C.billing_peak_check(m, f"{m}-31")
        return C.ok({
            "month": m, "gain_share_pct": pct, "gain_share_pct_contract_range": "20-30 %",
            "categories": [{"category": r["category"], "amount_jpy": round(r["amount_jpy"]), "gain_share_eligible": bool(r["gain_share_eligible"]),
                            "basis": r["basis"], "event_ids": r["event_ids"]} for r in rows],
            "total_verified_savings_jpy": round(total), "eligible_savings_jpy": round(eligible),
            "vendor_gain_share_jpy": round(share), "baas_fee_jpy": round(fee),
            "vendor_recurring_revenue_jpy": round(share + fee),
            "client_net_benefit_jpy": round(total - share - fee),
            "client_net_formula": "total verified savings - vendor gain share - BESS-as-a-Service fee",
            "demand_peak_check": lost,
            "dr_reconciliation": {"events": [e["event_id"] for e in evs], "aggregator_payments_jpy": round(sum(e["payment_jpy"] for e in evs)),
                                  "aggregator_penalties_jpy": round(sum(e["penalty_jpy"] for e in evs)),
                                  "ledger_payments_jpy": round(led_pay), "ledger_penalties_jpy": round(led_pen),
                                  "reconciles": abs(sum(e["payment_jpy"] for e in evs) - led_pay) < 2 and abs(sum(e["penalty_jpy"] for e in evs) - led_pen) < 2},
        }, "savings_ledger", "tariff_contract", "dr_events")
    except Exception as e:
        return C.err(str(e), "savings_ledger")


def get_savings_ledger(from_month: str, to_month: str) -> dict:
    """Return monthly verified savings by category with the gain share, BESS-as-a-Service fee and client net
    per month, for trend questions.

    Args:
      from_month: First month YYYY-MM (ledger starts 2026-01).
      to_month: Last month YYYY-MM (ledger ends 2026-07).
    """
    try:
        a, b = (from_month or "2026-01")[:7], (to_month or "2026-07")[:7]
        rows = STORE.query("SELECT month, category, amount_jpy, gain_share_eligible FROM {t:savings_ledger} WHERE month >= @a AND month <= @b ORDER BY month, category", a=a, b=b)
        if not rows:
            return C.err(f"no ledger rows between {a} and {b}", "savings_ledger")
        t = C.tariff()
        months: dict[str, dict] = {}
        for r in rows:
            m = months.setdefault(r["month"], {"month": r["month"], "by_category": {}, "total_jpy": 0.0, "eligible_jpy": 0.0})
            m["by_category"][r["category"]] = round(r["amount_jpy"])
            m["total_jpy"] += r["amount_jpy"]
            if r["gain_share_eligible"]:
                m["eligible_jpy"] += r["amount_jpy"]
        out = []
        for m in months.values():
            share = max(0.0, m["eligible_jpy"]) * t["gain_share_pct"] / 100
            out.append({**m, "total_jpy": round(m["total_jpy"]), "eligible_jpy": round(m["eligible_jpy"]), "vendor_gain_share_jpy": round(share),
                        "baas_fee_jpy": round(t["baas_fee_jpy_month"]), "client_net_jpy": round(m["total_jpy"] - share - t["baas_fee_jpy_month"])})
        return C.ok({"from": a, "to": b, "months": out,
                     "totals": {"savings_jpy": sum(x["total_jpy"] for x in out), "vendor_gain_share_jpy": sum(x["vendor_gain_share_jpy"] for x in out),
                                "baas_fees_jpy": sum(x["baas_fee_jpy"] for x in out), "client_net_jpy": sum(x["client_net_jpy"] for x in out)}},
                    "savings_ledger", "tariff_contract")
    except Exception as e:
        return C.err(str(e), "savings_ledger")
