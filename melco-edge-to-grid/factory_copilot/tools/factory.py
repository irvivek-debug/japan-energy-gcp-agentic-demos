"""Factory Interlock tools: plant load snapshot, production schedule, flexible loads, edge simulation,
and the (pending-only) load-shed proposal."""
from __future__ import annotations

import json
import uuid
from statistics import mean

from ..core import registry
from ..core.clock import DEMO_DATE, DEMO_NOW, normalise_hhmm, slot_start, window_slots
from ..datastore import STORE
from ..edge.interlock_engine import evaluate_plan
from . import common as C


def get_plant_load_snapshot(ts: str) -> dict:
    """Return the plant load at a 5-minute timestamp: receiving-point import, PV, BESS, load by asset
    class, headroom to the contracted demand, the largest feeders, and meter data-quality flags.

    Args:
      ts: Timestamp YYYY-MM-DDTHH:MM (JST). Use 2026-08-19T13:25 for the latest reading ("now").
    """
    try:
        t = (ts or DEMO_NOW).strip()
        if "T" not in t:
            t = f"{C.normalise_date(t)}T13:25"
        rows = STORE.query("SELECT MAX(ts) AS ts FROM {t:telemetry_5min} WHERE ts <= @t", t=t)
        at = rows[0]["ts"]
        if not at:
            return C.err(f"no telemetry at or before {t} (telemetry covers 2026-08-05T00:00 to 2026-08-19T13:25)", "telemetry_5min")
        data = STORE.query("SELECT meter_id, asset_class, kw FROM {t:telemetry_5min} WHERE ts = @t", t=at)
        by_class: dict[str, float] = {}
        imp = pv = bess = 0.0
        feeders = []
        for r in data:
            if r["asset_class"] == "receiving_point":
                imp = r["kw"]
            elif r["asset_class"] == "pv":
                pv += r["kw"]
            elif r["asset_class"] == "bess":
                bess = r["kw"]
            else:
                by_class[r["asset_class"]] = by_class.get(r["asset_class"], 0.0) + r["kw"]
                feeders.append(r)
        contracted = C.tariff()["contracted_demand_kw"]
        stuck = C.flat_meter_runs(f"{C._minus_days(at[:10], 3)}T00:00", at)
        mp = C.month_peak_to_date(at[:10])
        return C.ok({
            "ts": at, "receiving_point_import_kw": C.r1(imp), "contracted_demand_kw": contracted,
            "headroom_to_contract_kw": C.r1(contracted - imp), "month_billing_peak_to_date_kw": C.r1(mp["peak_kw"]),
            "month_peak_set_on": f"{mp['date']} {slot_start(mp['slot'])}" if mp["date"] else None,
            "pv_kw": C.r1(pv), "bess_kw": C.r1(bess), "bess_sign": "+ discharge / - charge",
            "gross_load_kw": C.r1(sum(by_class.values())),
            "load_by_class_kw": {k: C.r1(v) for k, v in sorted(by_class.items(), key=lambda kv: -kv[1])},
            "top_feeders": [{"meter_id": r["meter_id"], "asset_class": r["asset_class"], "kw": C.r1(r["kw"])}
                            for r in sorted(feeders, key=lambda r: -r["kw"])[:6]],
            "data_quality": [{"meter_id": s["meter_id"], "issue": "flat-lined reading (frozen meter signature)", "value_kw": s["kw"],
                              "identical_readings": s["n"], "since": s["first_ts"], "hours": round((s["span_min"] + 5) / 60, 1)} for s in stuck]
                            or "no frozen meters in the last 3 days",
        }, "telemetry_5min", "meters", "tariff_contract", "site_load_30min")
    except Exception as e:
        return C.err(str(e), "telemetry_5min")


def get_production_schedule(date: str, start: str, end: str) -> dict:
    """Return production and utility jobs (furnace batches, burn-in cycles, line runs, van charging) that
    overlap a time window, with interruptible / deferrable flags from MES (the planning view).

    Args:
      date: Date YYYY-MM-DD (use 2026-08-19 for today).
      start: Window start HH:MM, for example 16:30.
      end: Window end HH:MM, for example 19:00.
    """
    try:
        date = C.normalise_date(date)
        s, e = normalise_hhmm(start), normalise_hhmm(end)
        rows = STORE.query(
            "SELECT schedule_id, asset_id, asset_class, job_type, lot_id, product, start_ts, end_ts, planned_kw, interruptible, deferrable_h, status, customer_due, notes "
            "FROM {t:production_schedule} WHERE start_ts < @we AND end_ts > @ws ORDER BY asset_id, start_ts", ws=f"{date}T{s}", we=f"{date}T{e}")
        jobs = [{**r, "start": r["start_ts"][11:], "end": r["end_ts"][11:]} for r in rows]
        for j in jobs:
            j.pop("start_ts")
            j.pop("end_ts")
        summary: dict[str, int] = {}
        for j in jobs:
            summary[j["job_type"]] = summary.get(j["job_type"], 0) + 1
        return C.ok({"date": date, "window": f"{s}-{e}", "status_relative_to": DEMO_NOW, "job_counts": summary, "jobs": jobs,
                     "note": "Planning view from MES. Live commitment state (for example a printed sinter paste) is only known at the PLC and is checked by the edge."},
                    "production_schedule")
    except Exception as e:
        return C.err(str(e), "production_schedule")


def list_flexible_loads(date: str, start: str, end: str) -> dict:
    """List flexible loads for a window (deterministic planning estimates per asset, respecting the MES
    schedule and plant rules) and return a ready-to-simulate draft plan. The edge still decides.

    Args:
      date: Date YYYY-MM-DD (use 2026-08-19 for today).
      start: Window start HH:MM, for example 16:30.
      end: Window end HH:MM, for example 19:00.
    """
    try:
        date = C.normalise_date(date)
        s, e = normalise_hhmm(start), normalise_hhmm(end)
        dr_slots, ev = C.dr_window(date)
        target = float(ev["requested_kw"]) if ev and set(window_slots(s, e)) & set(dr_slots) else 0.0
        plan, cand, excl = C.draft_plan(date, s, e, ev["event_id"] if ev and target else "", target)
        total = sum(c["planning_estimate_kw"] for c in cand)
        return C.ok({
            "date": date, "window": f"{s}-{e}", "target_kw": target or None,
            "candidates": cand, "planning_total_kw": C.r1(total), "excluded": excl,
            "draft_plan_json": C.compact_plan_json(plan),
            "next_step": "Pass draft_plan_json unchanged to simulate_edge_interlock. Planning estimates are not commitments; only edge-verified kW count.",
        }, "assets", "load_forecast_30min", "production_schedule", "bess_state_5min", "site_plan_30min")
    except Exception as e:
        return C.err(str(e), "assets")


def _compact_result(res: dict) -> dict:
    acts = [{k: a[k] for k in ("asset_id", "action", "verdict", "rule_ids", "reason", "granted_avg_kw", "granted_min_kw", "latency_ms")}
            for a in res["actions"]]
    return {"plan_id": res["plan_id"], "edge_node": res["edge_node"], "evaluated_at": res["evaluated_at"], "window": res["window"],
            "event_id": res["event_id"], "target_kw": res["target_kw"], "summary": res["summary"],
            "actions": acts, "rejected_actions": res["rejected_actions"],
            "by_slot": [{"time": C.slot_rows_label(r["slot"]), "forecast_import_kw": r["forecast_import_kw"], "reduction_kw": r["reduction_kw"],
                         "planned_import_kw": r["planned_import_kw"]} for r in res["by_slot"]]}


def simulate_edge_interlock(plan_json: str) -> dict:
    """Run a plan through the edge interlock engine (the GDC Edge control-loop stand-in). Returns a
    verdict per action (ACCEPT / LIMIT / REJECT with rule id and reason), simulated decision latency,
    the firm reduction per slot and the margin over the target. Registers the plan_id for audit.

    Args:
      plan_json: JSON text {"date","start","end","event_id","target_kw","actions":[{"asset_id","action","kw","start","end"}]}.
        Asset ids may be single (AC-04), wildcards (AC-*) or lists (EV-07,EV-08). Actions include discharge,
        charge, dispatch_policy, tes_discharge, chw_setpoint, standby, pressure_setpoint, trim, defer,
        defer_batch, setpoint_shift, dim, shift, off, curtail, pause.
    """
    try:
        from ..edge.interlock_engine import parse_plan
        plan = parse_plan(plan_json)
        plan.setdefault("date", DEMO_DATE)
        if not plan.get("target_kw"):
            dr_slots, ev = C.dr_window(C.normalise_date(plan["date"]))
            if ev and plan.get("start") and set(window_slots(normalise_hhmm(plan["start"]), normalise_hhmm(plan.get("end") or ev["end_time"]))) & set(dr_slots):
                plan["target_kw"] = float(ev["requested_kw"])
                plan.setdefault("event_id", ev["event_id"])
        res = evaluate_plan(plan, C.edge_context(C.normalise_date(plan["date"])))
        registry.register_simulation(plan, res)
        return C.ok(_compact_result(res), "assets", "interlock_rules", "plc_tags_snapshot", "load_forecast_30min", "production_schedule", "site_plan_30min")
    except (ValueError, json.JSONDecodeError) as e:
        return C.err(f"plan_json could not be parsed: {e}. Send a JSON object with an 'actions' list.", "interlock_rules")
    except Exception as e:
        return C.err(str(e), "interlock_rules")


def propose_load_shed_plan(plan_id: str, rationale: str, event_id: str = "") -> dict:
    """Queue an edge-verified load-shed plan for human approval (Hold-to-Confirm). Nothing executes here.
    Only actions that were not rejected by the edge are included. Fails if the plan was never simulated.

    Args:
      plan_id: The plan_id returned by simulate_edge_interlock.
      rationale: One or two sentences on why this plan, citing the key figures.
      event_id: Optional DR event id, for example DR-20260819.
    """
    try:
        rec = registry.get(plan_id)
        if not rec:
            lt = registry.latest()
            hint = f" The most recent simulated plan is {lt[0]}." if lt else ""
            return C.err(f"plan {plan_id} has no edge simulation record; run simulate_edge_interlock first.{hint}", "interlock_rules")
        res = rec["result"]
        kept = [a for a in res["actions"] if a["verdict"] != "REJECT"]
        dropped = res["rejected_actions"]
        if not kept:
            return C.err("every action in this plan was rejected by the edge; there is nothing safe to propose", "interlock_rules")
        firm = C.keep_non_rejected(rec["plan"], res)
        pa = {
            "id": f"act-{uuid.uuid4().hex[:8]}",
            "kind": "load_shed_plan",
            "summary": (f"Load-shed plan {plan_id} for {res['window']['date']} {res['window']['start']}-{res['window']['end']}: "
                        f"firm {res['summary']['firm_reduction_kw']:,.0f} kW vs target {res['target_kw']:,.0f} kW "
                        f"({len(kept)} edge-approved actions, {len(dropped)} rejected and excluded)."),
            "details": {"plan_id": plan_id, "event_id": event_id or res.get("event_id", ""), "window": res["window"], "summary": res["summary"],
                        "actions": [{k: a[k] for k in ("asset_id", "action", "verdict", "rule_ids", "granted_avg_kw", "reason")} for a in kept],
                        "excluded_by_edge": dropped, "plan_json": C.compact_plan_json(firm), "rationale": rationale,
                        "sources": C.src("interlock_rules", "plc_tags_snapshot", "load_forecast_30min", "production_schedule")},
            "risk": "medium" if res["summary"]["meets_target"] else "high",
            "requires": "hold_to_confirm",
        }
        registry.mark_proposed(plan_id, {"action_id": pa["id"], "status": "pending_approval"})
        return {"status": "pending_approval", "pending_action": pa,
                "message": "Queued for Hold-to-Confirm approval. Nothing has been executed.",
                "source": C.src("interlock_rules", "plc_tags_snapshot")}
    except Exception as e:
        return C.err(str(e), "interlock_rules")
