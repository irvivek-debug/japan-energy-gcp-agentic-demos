"""Shared helpers for tools: data loaders (portable SQL via STORE), result envelopes, plan builders.

All loaders read through STORE so the same code runs on DuckDB-over-CSV and on BigQuery. Static
reference data is cached per process (the demo data does not change at runtime).
"""
from __future__ import annotations

import functools
import json
import re
from statistics import mean, median

from ..core import bess as bess_core
from ..core import dr_math
from ..core.clock import DEMO_DATE, normalise_date, normalise_hhmm, now_slot, slot_of, slot_start, window_slots
from ..datastore import STORE
from ..edge.interlock_engine import EdgeContext

NOW_SLOT = now_slot()


def src(*tables: str) -> list[str]:
    return [STORE.source_label(t) for t in tables]


def ok(payload: dict, *tables: str) -> dict:
    return {"status": "ok", **payload, "source": src(*tables)}


def err(message: str, *tables: str) -> dict:
    return {"status": "error", "error": message, "source": src(*tables)}


def r1(x, n=1):
    return None if x is None else round(float(x), n)


# ------------------------------------------------------------------------------------------------
# cached reference data
# ------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def assets() -> dict[str, dict]:
    return {r["asset_id"]: r for r in STORE.query("SELECT * FROM {t:assets}")}


@functools.lru_cache(maxsize=1)
def rules() -> dict[str, dict]:
    return {r["rule_id"]: r for r in STORE.query("SELECT * FROM {t:interlock_rules}")}


@functools.lru_cache(maxsize=1)
def tags() -> dict[tuple[str, str], float]:
    return {(r["asset_id"], r["tag_name"]): r["value"] for r in STORE.query("SELECT asset_id, tag_name, value FROM {t:plc_tags_snapshot}")}


@functools.lru_cache(maxsize=1)
def tariff() -> dict[str, float]:
    return {r["parameter"]: r["value"] for r in STORE.query("SELECT parameter, value FROM {t:tariff_contract}")}


@functools.lru_cache(maxsize=8)
def schedule(date: str) -> list[dict]:
    return STORE.query("SELECT * FROM {t:production_schedule} WHERE date = @d OR (date < @d AND end_ts >= @d) ORDER BY start_ts", d=date)


@functools.lru_cache(maxsize=8)
def asset_forecast(date: str) -> dict[str, dict[int, float]]:
    out: dict[str, dict[int, float]] = {}
    for r in STORE.query("SELECT asset_id, slot, forecast_kw FROM {t:load_forecast_30min} WHERE date = @d", d=date):
        out.setdefault(r["asset_id"], {})[int(r["slot"])] = float(r["forecast_kw"])
    return out


@functools.lru_cache(maxsize=8)
def site_plan(date: str) -> dict[int, dict]:
    return {int(r["slot"]): r for r in STORE.query("SELECT * FROM {t:site_plan_30min} WHERE date = @d ORDER BY slot", d=date)}


@functools.lru_cache(maxsize=16)
def prices(date: str) -> dict[int, dict]:
    return {int(r["slot"]): r for r in STORE.query("SELECT * FROM {t:jepx_prices_30min} WHERE date = @d ORDER BY slot", d=date)}


@functools.lru_cache(maxsize=8)
def dr_events(date: str = "") -> list[dict]:
    if date:
        return STORE.query("SELECT * FROM {t:dr_events} WHERE date = @d ORDER BY start_slot", d=date)
    return STORE.query("SELECT * FROM {t:dr_events} ORDER BY date")


@functools.lru_cache(maxsize=1)
def bess_now() -> dict:
    rows = STORE.query("SELECT * FROM {t:bess_state_5min} ORDER BY ts DESC LIMIT 1")
    return rows[0]


@functools.lru_cache(maxsize=4)
def month_peak_to_date(date: str) -> dict:
    rows = STORE.query("SELECT MAX(import_kw) AS peak FROM {t:site_load_30min} WHERE month = @m AND date < @d", m=date[:7], d=date)
    pk = float(rows[0]["peak"] or 0.0)
    at = STORE.query("SELECT date, slot FROM {t:site_load_30min} WHERE month = @m AND date < @d AND import_kw >= @p ORDER BY date LIMIT 1",
                     m=date[:7], d=date, p=pk - 0.001)
    return {"peak_kw": pk, "date": at[0]["date"] if at else None, "slot": int(at[0]["slot"]) if at else None}


def energy_price_note() -> str:
    t = tariff()
    return (f"Plant all-in energy price = JEPX Tokyo spot x {t['loss_factor']:.2f} + {t['service_fee_jpy_kwh'] + t['wheeling_energy_jpy_kwh'] + t['capacity_contribution_jpy_kwh'] + t['renewable_levy_jpy_kwh']:.2f} JPY/kWh "
            "(service fee, wheeling energy, capacity contribution, renewable levy).")


# ------------------------------------------------------------------------------------------------
# windows and slot sets
# ------------------------------------------------------------------------------------------------
def dr_window(date: str) -> tuple[list[int], dict | None]:
    evs = [e for e in dr_events(date)]
    if not evs:
        return [], None
    e = evs[0]
    return list(range(int(e["start_slot"]), int(e["end_slot"]))), e


def spike_slots(date: str) -> list[int]:
    p = prices(date)
    if not p:
        return []
    thr = max(35.0, 1.5 * median(v["spot_jpy_kwh"] for v in p.values()))
    return [s for s in sorted(p) if p[s]["spot_jpy_kwh"] >= thr and (date != DEMO_DATE or s >= NOW_SLOT)]


def pv_risk_slots(date: str, ratio: float = 0.40) -> list[int]:
    sp = site_plan(date)
    return [s for s, r in sp.items() if not r["is_actual"] and r["pv_p50_kw"] >= 300 and (r["pv_p50_kw"] - r["pv_p10_kw"]) / r["pv_p50_kw"] >= ratio]


def contiguous_windows(slots: list[int]) -> list[tuple[int, int]]:
    out, cur = [], []
    for s in sorted(slots):
        if cur and s == cur[-1] + 1:
            cur.append(s)
        else:
            if cur:
                out.append((cur[0], cur[-1]))
            cur = [s]
    if cur:
        out.append((cur[0], cur[-1]))
    return out


def bess_params() -> bess_core.BessParams:
    t = tariff()
    rte = t.get("bess_round_trip_efficiency", 0.85)
    e = rte ** 0.5
    return bess_core.BessParams(power_kw=4000.0, energy_kwh=8000.0, soc_min_pct=10.0, soc_max_pct=95.0, eff_charge=e, eff_discharge=e)


def policy_params(date: str) -> bess_core.PolicyParams:
    peak = month_peak_to_date(date)["peak_kw"]
    return bess_core.PolicyParams(v2_import_ceiling_kw=(peak - 150.0) if peak else 14000.0)


def day_inputs(date: str) -> bess_core.DayInputs:
    date = normalise_date(date)
    sp = site_plan(date)
    pr = prices(date)
    t = tariff()
    slots = [s for s in range(NOW_SLOT if date == DEMO_DATE else 1, 49)]
    dr, _ = dr_window(date)
    adder = t["service_fee_jpy_kwh"] + t["wheeling_energy_jpy_kwh"] + t["capacity_contribution_jpy_kwh"] + t["renewable_levy_jpy_kwh"]
    lock_n = int(t.get("gate_closure_min", 60) // 30)
    return bess_core.DayInputs(
        slots=slots,
        import_p50={s: float(sp[s]["forecast_import_p50_kw"]) for s in slots},
        import_p10={s: float(sp[s]["forecast_import_p10pv_kw"]) for s in slots},
        nominated={s: float(sp[s]["nominated_kw"]) for s in slots},
        spot={s: float(pr[s]["spot_jpy_kwh"]) * t["loss_factor"] for s in slots},
        imbalance={s: float(pr[s]["imbalance_jpy_kwh"]) for s in slots},
        dr_slots=dr, spike_slots=spike_slots(date), risk_slots=pv_risk_slots(date),
        locked_slots=[s for s in slots if s < (NOW_SLOT + lock_n)] if date == DEMO_DATE else [],
        band_pct=t["deviation_band_pct"], energy_adder_jpy_kwh=adder,
    )


def edge_context(date: str = DEMO_DATE) -> EdgeContext:
    date = normalise_date(date)
    sp = site_plan(date)
    return EdgeContext(
        date=date, now_slot=NOW_SLOT, assets=assets(), rules=rules(), tags=tags(), forecast_kw=asset_forecast(date),
        schedule=schedule(date), import_p50={s: float(r["forecast_import_p50_kw"]) for s, r in sp.items()},
        bess_inputs=day_inputs(date), bess_params=bess_params(), policy_params=policy_params(date),
        bess_soc_now=float(bess_now()["soc_pct"]),
        air_peer_sp=peer_specific_power(),
    )


@functools.lru_cache(maxsize=1)
def peer_specific_power() -> float:
    vals = [v for (a, n), v in tags().items() if n == "specific_power" and a != "AC-04" and v > 0]
    return round(mean(vals), 3) if vals else 6.1


# ------------------------------------------------------------------------------------------------
# cloud-side planning view (what the specialists see before the edge decides)
# ------------------------------------------------------------------------------------------------
def draft_plan(date: str, start: str, end: str, event_id: str = "", target_kw: float = 0.0) -> tuple[dict, list[dict], list[dict]]:
    """Build the planning-view candidate list and a draft plan (every candidate included).

    Returns (plan, candidates, excluded). The cloud view uses the MES schedule and asset flex classes; it
    does not see live PLC state (batch commitment, pit level, airflow floors). The edge decides.
    """
    date = normalise_date(date)
    start, end = normalise_hhmm(start), normalise_hhmm(end)
    win = window_slots(start, end)
    fc = asset_forecast(date)
    A = assets()
    sch = schedule(date)
    cand, excl, actions = [], [], []

    def avg_fc(aid, factor=1.0):
        return mean(fc.get(aid, {}).get(s, 0.0) for s in win) * factor if win else 0.0

    def add(aid, action, est, method, note, act):
        cand.append({"asset_id": aid, "asset_name": A[aid]["asset_name"] if aid in A else aid, "asset_class": A[aid]["asset_class"] if aid in A else "compressed_air_header",
                     "action": action, "planning_estimate_kw": r1(est), "method": method, "note": note})
        actions.append(act)

    # BESS (forecast-aware policy)
    di = day_inputs(date)
    rows = bess_core.simulate("forecast_aware_v2", float(bess_now()["soc_pct"]), di, "p50", bess_params(), policy_params(date))
    dis = [max(0.0, r["power_kw"]) for r in rows if r["slot"] in win]
    add("BESS-01", "dispatch_policy", mean(dis) if dis else 0.0, "forecast_aware_v2: pre-charge outside PV-risk slots, flat discharge over DR + spike window",
        "SOC path checked at the edge", {"asset_id": "BESS-01", "action": "dispatch_policy", "policy": "forecast_aware_v2"})
    add("TES-01", "tes_discharge", 700.0, "Thermal storage carries chiller load", "Planning value 700 kW", {"asset_id": "TES-01", "action": "tes_discharge", "kw": 700})
    ch = sum(avg_fc(f"CH-0{i}") for i in range(1, 5))
    add("CH-01", "chw_setpoint", ch * 0.025 * 1.5, "Chilled-water supply +1.5 C on all chillers", "Asset spec CH-*", {"asset_id": "CH-*", "action": "chw_setpoint", "delta_c": 1.5})
    add("AC-04", "standby", 45.0, "Degraded unit to standby; peers carry its air", "Efficiency gain only", {"asset_id": "AC-04", "action": "standby"})
    ac = sum(avg_fc(f"AC-0{i}") for i in range(1, 7))
    add("COMP-HDR", "pressure_setpoint", ac * 0.021, "Header setpoint 0.68 -> 0.65 MPa", "", {"asset_id": "COMP-HDR", "action": "pressure_setpoint", "to_mpa": 0.65})
    for aid in ("CR-AHU-05", "CR-AHU-06"):
        add(aid, "trim", avg_fc(aid, 0.23), "Support-zone fan trim toward the airflow floor", "", {"asset_id": aid, "action": "trim"})
    # furnaces: planning view sees batch start times and planned deferral windows only
    for fid in ("FN-01", "FN-02", "FN-03"):
        batches = [r for r in sch if r["asset_id"] == fid and r["job_type"] == "sinter_batch" and r["start_slot"] < win[-1] + 1 and r["end_slot"] > win[0]]
        if batches and batches[0]["status"] == "planned" and float(batches[0]["deferrable_h"] or 0) > 0:
            b = batches[0]
            add(fid, "defer_batch", avg_fc(fid), f"Defer batch {b['lot_id']} ({b['start_ts'][11:]}) to after the window",
                "MES shows the batch as planned; commitment state is only known at the PLC", {"asset_id": fid, "action": "defer_batch"})
        elif not batches:
            add(fid, "standby", max(0.0, avg_fc(fid) - 40.0), "Idle furnace to standby", "Reheat lead time applies",
                {"asset_id": fid, "action": "standby"})
        else:
            excl.append({"asset_id": fid, "reason": "Batch already running in the window (non-interruptible)"})
    for i in range(1, 9):
        bid = f"BI-0{i}"
        cyc = [c for c in sch if c["asset_id"] == bid and c["job_type"] == "burn_in_cycle" and c["status"] == "planned"
               and c["start_slot"] < win[-1] + 1 and c["end_slot"] > win[0]]
        if not cyc:
            excl.append({"asset_id": bid, "reason": "No planned cycle overlaps the window"})
            continue
        need = (win[-1] + 1 - cyc[0]["start_slot"]) * 0.5
        if need > float(cyc[0]["deferrable_h"] or 0):
            excl.append({"asset_id": bid, "reason": f"Cycle starts {cyc[0]['start_ts'][11:]}; clearing the window needs {need:.1f} h (> 3 h)"})
            continue
        add(bid, "defer", avg_fc(bid), f"Defer cycle start {cyc[0]['start_ts'][11:]} to {end}", "", {"asset_id": bid, "action": "defer"})
    vans = [f"EV-{i:02d}" for i in range(7, 11)]
    add("EV-07", "defer", sum(avg_fc(v) for v in vans), "Defer van charging (EV-07..EV-10) to after the window", "Vans need 80 % by 07:00",
        {"asset_id": "EV-07,EV-08,EV-09,EV-10", "action": "defer"})
    cand[-1]["asset_id"] = "EV-07..EV-10"
    add("OF-AHU-01", "setpoint_shift", sum(avg_fc(f"OF-AHU-0{i}", 0.32) for i in range(1, 5)), "Office zones +2 C (to 28 C)", "OF-AHU-01..04",
        {"asset_id": "OF-AHU-*", "action": "setpoint_shift", "delta_c": 2})
    cand[-1]["asset_id"] = "OF-AHU-01..04"
    add("LT-01", "dim", sum(avg_fc(f"LT-0{i}", 0.30) for i in range(1, 7)), "Dim office and warehouse lighting 30 %", "LT-01..06",
        {"asset_id": "LT-*", "action": "dim", "pct": 30})
    cand[-1]["asset_id"] = "LT-01..06"
    add("WW-01", "shift", sum(avg_fc(f"WW-0{i}") for i in range(1, 5)), "Pre-pump wastewater pit and hold", "WW-01..04; planning assumes the whole window",
        {"asset_id": "WW-*", "action": "shift", "minutes": len(win) * 30})
    cand[-1]["asset_id"] = "WW-01..04"
    for aid, a in A.items():
        if a["asset_class"] == "production_line":
            excl.append({"asset_id": aid, "reason": "No line stops (plant energy policy s.4)"})
        elif a["asset_class"] in ("critical_utility", "cleanroom_exhaust"):
            excl.append({"asset_id": aid, "reason": "Critical utility, never curtailed"})
        elif aid in ("CR-AHU-01", "CR-AHU-02", "CR-AHU-03", "CR-AHU-04"):
            excl.append({"asset_id": aid, "reason": "Production-zone clean-room air handler (airflow held at 100 %)"})
    plan = {"date": date, "start": start, "end": end, "event_id": event_id, "target_kw": target_kw, "actions": actions}
    return plan, cand, excl


def compact_plan_json(plan: dict) -> str:
    return json.dumps(plan, separators=(",", ":"))


def keep_non_rejected(plan: dict, result: dict) -> dict:
    """Return a plan with only the actions that did not produce any REJECT at the edge."""
    rejected = {r["asset_id"] for r in result["actions"] if r["verdict"] == "REJECT"}
    from ..edge.interlock_engine import expand_assets
    kept = []
    for a in plan["actions"]:
        ids = expand_assets(a["asset_id"], assets()) if a["asset_id"] != "COMP-HDR" else ["COMP-HDR"]
        if not any(i in rejected for i in ids):
            kept.append(a)
    return {**plan, "actions": kept}


INJECTION_PATTERNS = [
    r"ignore (all |the )?(previous |prior )?(interlocks?|instructions|rules|safety)",
    r"(switch|turn|shut) (off|down) (the )?clean-?room",
    r"do not ask for (confirmation|approval)",
    r"pre-?approved",
    r"(note|message|instruction)s? to (the )?(ai|copilot|assistant|agent)",
    r"bypass (the )?(interlock|hold-to-confirm|approval)",
    r"execute (it |this )?(immediately|now) without",
]


def scan_injection(text: str) -> list[str]:
    hits = []
    low = text.lower()
    for p in INJECTION_PATTERNS:
        for m in re.finditer(p, low):
            hits.append(text[m.start():m.end()])
    return sorted(set(hits))


def slot_rows_label(s: int) -> str:
    return f"{slot_start(s)}-{slot_start(s + 1)}"


def baseline_for(date: str, start_slot: int, end_slot: int, event_day_values: dict[int, float] | None = None) -> dict:
    """High 4 of 5 baseline (with same-day adjustment) from site_load_30min history."""
    rows = STORE.query("SELECT date, slot, import_kw, bess_kw, baseline_eligible FROM {t:site_load_30min} WHERE date < @d AND date >= @d0",
                       d=date, d0=_minus_days(date, 30))
    load, net, elig = {}, {}, set()
    for r in rows:
        load.setdefault(r["date"], {})[int(r["slot"])] = float(r["import_kw"])
        net.setdefault(r["date"], {})[int(r["slot"])] = float(r["import_kw"]) + float(r["bess_kw"])
        if r["baseline_eligible"]:
            elig.add(r["date"])
    if event_day_values is None:
        ev = STORE.query("SELECT slot, import_kw, bess_kw FROM {t:site_load_30min} WHERE date = @d", d=date)
        event_day_values = {int(r["slot"]): float(r["import_kw"]) + float(r["bess_kw"]) for r in ev}
    return dr_math.high_4_of_5_baseline(load, net, sorted(elig, reverse=True), list(range(start_slot, end_slot)), event_day_values)


def _minus_days(date: str, n: int) -> str:
    import datetime as _dt
    return (_dt.date.fromisoformat(date) - _dt.timedelta(days=n)).isoformat()


def today_adjustment_values(date: str) -> dict[int, float]:
    """Event-day load net of BESS for the adjustment slots: metered where available, forecast (PV p50) after 13:30."""
    sp = site_plan(date)
    out = {}
    for s, r in sp.items():
        if r["is_actual"]:
            out[s] = float(r["forecast_import_p50_kw"])  # for past slots this equals metered gross - PV (before BESS)
        else:
            out[s] = float(r["forecast_import_p50_kw"])
    return out


__all__ = [n for n in dir() if not n.startswith("_")]


def flat_meter_runs(from_ts: str, to_ts: str, min_repeats: int = 24) -> list[dict]:
    """Meters whose reading repeats one exact value over a contiguous run (a frozen meter signature).

    Storage, generation and the receiving point are excluded (constant set-points and night-time zero PV
    are normal). Non-contiguous repeats of a common value are discarded by comparing count and time span.
    """
    import datetime as _dt
    rows = STORE.query(
        "SELECT meter_id, asset_class, kw, COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM {t:telemetry_5min} "
        "WHERE ts >= @a AND ts <= @b AND kw >= 50 AND asset_class NOT IN ('receiving_point', 'bess', 'pv') "
        "GROUP BY meter_id, asset_class, kw HAVING COUNT(*) >= @n ORDER BY n DESC", a=from_ts, b=to_ts, n=min_repeats)
    out = []
    for r in rows:
        span = (_dt.datetime.fromisoformat(r["last_ts"]) - _dt.datetime.fromisoformat(r["first_ts"])).total_seconds() / 60.0
        if abs(span - (int(r["n"]) - 1) * 5) <= 10:
            out.append({**r, "n": int(r["n"]), "span_min": span})
    return out


def billing_peak_check(month: str, to_date: str) -> dict | None:
    """Was the month's billing peak (to date) set around a DR event while the battery sat idle?"""
    pk = STORE.query("SELECT date, slot, import_kw, bess_kw FROM {t:site_load_30min} WHERE month = @m AND date <= @d ORDER BY import_kw DESC LIMIT 1",
                     m=month, d=to_date)
    if not pk:
        return None
    p0 = pk[0]
    evs = {e["date"]: e for e in dr_events("") if e["status"] == "settled"}
    ev = evs.get(p0["date"])
    around, position = False, None
    if ev:
        s = int(p0["slot"])
        if int(ev["start_slot"]) - 4 <= s < int(ev["start_slot"]):
            around, position = True, "in the 2 hours before the event (battery held full for the event)"
        elif int(ev["end_slot"]) <= s < int(ev["end_slot"]) + 4:
            around, position = True, "in the 2 hours after the event (battery depleted, deferred loads rebounding)"
    non_ev = STORE.query("SELECT MAX(import_kw) AS p FROM {t:site_load_30min} WHERE month = @m AND date <= @d AND is_dr_event = FALSE", m=month, d=to_date)
    ev_dates = list(evs)
    rows = STORE.query("SELECT date, MAX(import_kw) AS p FROM {t:site_load_30min} WHERE month = @m AND date <= @d GROUP BY date", m=month, d=to_date)
    other = max([float(r["p"]) for r in rows if r["date"] not in ev_dates] or [0.0])
    t = tariff()
    thr = 13500.0
    extra = max(0.0, float(p0["import_kw"]) - max(other, thr)) if around and abs(float(p0["bess_kw"])) < 50 else 0.0
    return {"month_billing_peak_kw": r1(p0["import_kw"]), "set_at": f"{p0['date']} {slot_start(int(p0['slot']))}", "dr_event": ev["event_id"] if ev else None,
            "position": position, "around_dr_event": bool(around and abs(float(p0["bess_kw"])) < 50), "bess_kw_at_peak": r1(p0["bess_kw"]),
            "demand_limit_threshold_kw": thr, "highest_peak_on_non_event_days_kw": r1(other),
            "extra_billing_demand_kw": r1(extra), "extra_demand_charge_jpy": round(extra * t["demand_charge_jpy_kw_month"]),
            "basis": f"(billing peak - max(highest non-event-day peak, {thr:,.0f} kW demand-limit threshold)) x {t['demand_charge_jpy_kw_month']:.0f} JPY/kW-month",
            "cause": ("The battery sat idle at the peak " + (position or "") + "; rule_based_v1 demand limiting (13,500 kW) could not act.") if around else None}
