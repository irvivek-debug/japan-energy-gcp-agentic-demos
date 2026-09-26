"""Trading and dispatch tools: market snapshot, balance position, VPP fleet state, least-cost hedge plan, proposals.

Compliance is encoded in the math, not only in prompts:
  * plan_hedge never chooses imbalance as a cheaper option: residual imbalance carries a penalty far above any market
    price, so it appears only when cover is physically unavailable (policy guide Section 2.3).
  * untrusted VPP clusters (stale or frozen telemetry) are excluded (Section 6), dKW-committed capacity and its
    reserve energy are held back (Section 5), intraday buys never exceed the open short (Section 2.4).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Optional

import numpy as np

from ..clock import NOW, gate_closure, gate_status, minutes_between, slot_label, slot_start
from ..store import STORE, src
from ._common import check_date, check_slots, err, r2, record_proposal, safe_tool, short_hash

STALE_MINUTES = 30
FROZEN_RECORDS = 12
LOT_MWH = 0.05
RESIDUAL_PENALTY_JPY_KWH = 100000.0  # imbalance is never an economic choice


# --------------------------------------------------------------------------------------------- market data
def _market_rows(date: str, a: int, b: int) -> list[dict]:
    return STORE.query(
        """
        SELECT s.slot, s.start_time, s.tokyo_price_jpy_kwh, s.system_price_jpy_kwh,
               i.best_bid_jpy_kwh, i.best_ask_jpy_kwh, i.ask_depth_mwh, i.ask_level2_jpy_kwh, i.ask_level2_depth_mwh,
               i.vwap_jpy_kwh, m.reserve_margin_pct, m.imbalance_price_jpy_kwh, m.imbalance_p10_jpy_kwh,
               m.imbalance_p90_jpy_kwh, m.scarcity_flag, m.is_forecast, w.temp_p50_c, w.temp_p90_c
        FROM {t:jepx_spot_30min} s
        LEFT JOIN {t:jepx_intraday_30min} i ON i.date = s.date AND i.slot = s.slot
        LEFT JOIN {t:imbalance_30min} m ON m.date = s.date AND m.slot = s.slot
        LEFT JOIN {t:weather_forecast_hourly} w ON w.date = s.date AND w.hour = s.hour AND w.cell_id = 'W01'
        WHERE s.date = @date AND s.slot >= @a AND s.slot <= @b
        ORDER BY s.slot
        """,
        date=date, a=int(a), b=int(b),
    )


@safe_tool
def get_market_snapshot(date: str, from_slot: int, to_slot: int) -> dict:
    """Market view per 30-minute slot: JEPX Tokyo-area and system spot price, intraday best bid/ask with depth,
    imbalance price (actual, or p10/p50/p90 forecast for unsettled slots), wide-area reserve margin, scarcity flag,
    gate status and the Tokyo temperature forecast. All prices are JPY/kWh.

    Args:
      date: Delivery date YYYY-MM-DD. The desk scenario day is 2026-08-19 (now 15:40 JST).
      from_slot: First 30-minute slot, 1-48 (slot 35 = 17:00-17:30).
      to_slot: Last slot, 1-48, inclusive.
    """
    e = check_date(date) or check_slots(from_slot, to_slot)
    if e:
        return err(e)
    rows = _market_rows(date, from_slot, to_slot)
    if not rows:
        return {"status": "not_found", "date": date, "note": "spot data covers 2026-06-01..2026-08-20",
                "source": src("jepx_spot_30min")}
    out = []
    for r in rows:
        s = int(r["slot"])
        out.append({
            "slot": s, "time": slot_label(s), "gate_status": gate_status(date, s), "gate_closure": gate_closure(date, s),
            "tokyo_spot_jpy_kwh": r2(r["tokyo_price_jpy_kwh"]), "system_spot_jpy_kwh": r2(r["system_price_jpy_kwh"]),
            "intraday_best_bid_jpy_kwh": r2(r["best_bid_jpy_kwh"]), "intraday_best_ask_jpy_kwh": r2(r["best_ask_jpy_kwh"]),
            "intraday_ask_depth_mwh": r2(r["ask_depth_mwh"], 1),
            "intraday_ask_level2_jpy_kwh": r2(r["ask_level2_jpy_kwh"]),
            "intraday_ask_level2_depth_mwh": r2(r["ask_level2_depth_mwh"], 1),
            "reserve_margin_pct": r2(r["reserve_margin_pct"]),
            "imbalance_p50_jpy_kwh" if r["is_forecast"] else "imbalance_actual_jpy_kwh": r2(r["imbalance_price_jpy_kwh"]),
            **({"imbalance_p10_jpy_kwh": r2(r["imbalance_p10_jpy_kwh"]), "imbalance_p90_jpy_kwh": r2(r["imbalance_p90_jpy_kwh"])}
               if r["is_forecast"] else {}),
            "scarcity_pricing": bool(r["scarcity_flag"]) if r["scarcity_flag"] is not None else None,
            "tokyo_temp_p50_c": r2(r["temp_p50_c"], 1),
        })
    scarce = [o["slot"] for o in out if o["scarcity_pricing"]]
    rm = [o["reserve_margin_pct"] for o in out if o["reserve_margin_pct"] is not None]
    imb = [o.get("imbalance_p50_jpy_kwh", o.get("imbalance_actual_jpy_kwh")) for o in out]
    imb = [x for x in imb if x is not None]
    return {
        "status": "ok", "date": date, "as_of": NOW, "slots": out,
        "summary": {
            "min_reserve_margin_pct": min(rm) if rm else None,
            "max_imbalance_jpy_kwh": max(imb) if imb else None,
            "scarcity_slots": scarce,
            "max_tokyo_spot_jpy_kwh": max(o["tokyo_spot_jpy_kwh"] for o in out),
        },
        "rules": "Scarcity imbalance price: 0 uplift at 10% reserve margin, 45 JPY/kWh at 8%, cap 200 JPY/kWh at 3% "
                 "(cap rises to 300 JPY/kWh from 2026-10-01) [desk_policy_guide.md Section 3].",
        "source": src("jepx_spot_30min", "jepx_intraday_30min", "imbalance_30min", "weather_forecast_hourly"),
    }


def _position_rows(date: str, a: int, b: int) -> list[dict]:
    return STORE.query(
        """
        SELECT slot, demand_forecast_da_mwh, demand_forecast_latest_mwh, demand_actual_mwh, procured_bilateral_mwh,
               procured_spot_mwh, procured_intraday_mwh, vpp_dispatched_mwh, total_procured_mwh, open_position_mwh
        FROM {t:balance_position_30min}
        WHERE date = @date AND slot >= @a AND slot <= @b ORDER BY slot
        """,
        date=date, a=int(a), b=int(b),
    )


@safe_tool
def get_balance_position(date: str, from_slot: int, to_slot: int) -> dict:
    """Balance group position per 30-minute slot: day-ahead plan, latest demand forecast, metered demand for delivered
    slots, supply by source (bilateral, JEPX spot, intraday, VPP) and the open position in MWh (negative = short).

    Args:
      date: Delivery date YYYY-MM-DD (balance data covers 2026-08-01..2026-08-19).
      from_slot: First slot 1-48.
      to_slot: Last slot 1-48, inclusive.
    """
    e = check_date(date) or check_slots(from_slot, to_slot)
    if e:
        return err(e)
    rows = _position_rows(date, from_slot, to_slot)
    if not rows:
        return {"status": "not_found", "date": date, "note": "balance data covers 2026-08-01..2026-08-19",
                "source": src("balance_position_30min")}
    out = []
    for r in rows:
        s = int(r["slot"])
        out.append({"slot": s, "time": slot_label(s), "gate_status": gate_status(date, s),
                    "gate_closure": gate_closure(date, s),
                    "demand_da_plan_mwh": r2(r["demand_forecast_da_mwh"], 1),
                    "demand_latest_forecast_mwh": r2(r["demand_forecast_latest_mwh"], 1),
                    "demand_actual_mwh": r2(r["demand_actual_mwh"], 1),
                    "supply_bilateral_mwh": r2(r["procured_bilateral_mwh"], 1), "supply_spot_mwh": r2(r["procured_spot_mwh"], 1),
                    "supply_intraday_mwh": r2(r["procured_intraday_mwh"], 1), "supply_vpp_mwh": r2(r["vpp_dispatched_mwh"], 1),
                    "open_position_mwh": r2(r["open_position_mwh"], 1)})
    open_slots = [o for o in out if o["gate_status"] == "open"]
    short = [o for o in open_slots if o["open_position_mwh"] < -0.5]
    return {
        "status": "ok", "date": date, "as_of": NOW, "slots": out,
        "summary": {
            "open_gate_slots": [o["slot"] for o in open_slots],
            "short_open_slots": [o["slot"] for o in short],
            "total_short_open_mwh": r2(-sum(o["open_position_mwh"] for o in short), 1),
            "net_open_position_open_slots_mwh": r2(sum(o["open_position_mwh"] for o in open_slots), 1),
            "next_gate_closure": min((o["gate_closure"] for o in open_slots), default=None),
        },
        "source": src("balance_position_30min"),
    }


# ----------------------------------------------------------------------------------------------- VPP fleet
def fleet_state(date: str, slot: int, now: str = NOW) -> dict:
    """Per-cluster health and dispatchable headroom for a target slot (shared by tools, planner, API)."""
    clusters = STORE.query("SELECT * FROM {t:vpp_clusters} ORDER BY cluster_id")
    tel = STORE.query(
        "SELECT cluster_id, slot, timestamp, soc_pct, available_kw, available_kwh, online_devices, last_seen "
        "FROM {t:vpp_telemetry_30min} WHERE timestamp <= @now AND timestamp >= @since ORDER BY cluster_id, timestamp",
        now=now, since=(datetime.fromisoformat(now) - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M"),
    )
    comm = STORE.query(
        "SELECT commitment_id, cluster_id, product, committed_kw, reserve_energy_kwh, from_slot, to_slot, response_minutes "
        "FROM {t:ancillary_commitments} WHERE date = @date AND from_slot <= @slot AND to_slot >= @slot",
        date=date, slot=int(slot),
    )
    by_c: dict[str, list[dict]] = {}
    for t in tel:
        by_c.setdefault(t["cluster_id"], []).append(t)
    com_by: dict[str, list[dict]] = {}
    for c in comm:
        com_by.setdefault(c["cluster_id"], []).append(c)
    lead_s = max(0.0, minutes_between(now, slot_start(date, slot)) * 60)
    out = []
    for c in clusters:
        cid = c["cluster_id"]
        recs = by_c.get(cid, [])
        last = recs[-1] if recs else None
        reasons, health = [], "ok"
        if last is None:
            health, reasons = "untrusted", ["no telemetry"]
        else:
            age = minutes_between(last["last_seen"], now)
            if age > STALE_MINUTES:
                reasons.append(f"stale: last heartbeat {last['last_seen']} ({age:.0f} min before {now})")
            socs = [r["soc_pct"] for r in recs[-FROZEN_RECORDS:] if r["soc_pct"] is not None]
            if len(socs) == FROZEN_RECORDS and len(set(socs)) == 1:
                reasons.append(f"frozen: SOC flat at {socs[0]}% for {FROZEN_RECORDS} records (6 h)")
            if reasons:
                health = "untrusted"
            else:
                share = last["online_devices"] / max(1, c["device_count"])
                floor = 0.3 if c["asset_class"] == "ev_depot" else 0.6
                if share < floor:
                    health = "degraded"
                    reasons.append(f"degraded: {share * 100:.0f}% of devices reporting (floor {floor * 100:.0f}%)")
        committed = sum(x["committed_kw"] for x in com_by.get(cid, []))
        reserve = sum(x["reserve_energy_kwh"] for x in com_by.get(cid, []))
        avail_kw = float(last["available_kw"]) if last else 0.0
        avail_kwh = float(last["available_kwh"]) if last else 0.0
        trusted = health != "untrusted"
        resp_ok = c["response_time_s"] <= lead_s
        out.append({
            "cluster_id": cid, "asset_class": c["asset_class"], "name": c["name"], "health": health, "reasons": reasons,
            "capacity_kw": c["capacity_kw"], "energy_kwh": c["energy_kwh"], "soc_pct": last["soc_pct"] if last else None,
            "available_kw": avail_kw, "available_kwh": avail_kwh, "last_seen": last["last_seen"] if last else None,
            "online_devices": last["online_devices"] if last else 0, "device_count": c["device_count"],
            "committed_dkw_kw": committed, "reserved_energy_kwh": reserve,
            "commitments": [x["commitment_id"] for x in com_by.get(cid, [])],
            "dispatchable_kw": max(0.0, avail_kw - committed) if (trusted and resp_ok) else 0.0,
            "dispatchable_kwh": max(0.0, avail_kwh - reserve) if (trusted and resp_ok) else 0.0,
            "dispatch_cost_jpy_kwh": c["dispatch_cost_jpy_kwh"], "response_time_s": c["response_time_s"],
            "response_ok": resp_ok,
        })
    return {"date": date, "slot": int(slot), "snapshot": now, "clusters": out, "commitments": comm}


@safe_tool
def get_vpp_fleet_state(date: str, slot: int) -> dict:
    """VPP fleet state for one delivery slot from the latest telemetry: available and dispatchable MW/MWh by asset
    class, balancing-market dKW commitments that must be held back, and telemetry health. Clusters with stale or
    frozen telemetry are untrusted and excluded from dispatch.

    Args:
      date: Delivery date YYYY-MM-DD (telemetry snapshot is 2026-08-19 15:40).
      slot: Target delivery slot 1-48.
    """
    e = check_date(date) or check_slots(slot, slot)
    if e:
        return err(e)
    fs = fleet_state(date, int(slot))
    cls: dict[str, dict] = {}
    for c in fs["clusters"]:
        k = cls.setdefault(c["asset_class"], {"clusters": 0, "capacity_mw": 0.0, "available_mw": 0.0,
                                              "committed_dkw_mw": 0.0, "dispatchable_mw": 0.0, "dispatchable_mwh": 0.0,
                                              "untrusted": 0, "degraded": 0})
        k["clusters"] += 1
        k["capacity_mw"] += c["capacity_kw"] / 1000
        k["available_mw"] += c["available_kw"] / 1000
        k["committed_dkw_mw"] += c["committed_dkw_kw"] / 1000
        k["dispatchable_mw"] += c["dispatchable_kw"] / 1000
        k["dispatchable_mwh"] += c["dispatchable_kwh"] / 1000
        k["untrusted"] += c["health"] == "untrusted"
        k["degraded"] += c["health"] == "degraded"
    for k in cls.values():
        for f in ("capacity_mw", "available_mw", "committed_dkw_mw", "dispatchable_mw", "dispatchable_mwh"):
            k[f] = r2(k[f], 2)
    exceptions = []
    for c in fs["clusters"]:
        if c["health"] != "ok":
            item = {"cluster_id": c["cluster_id"], "asset_class": c["asset_class"], "health": c["health"],
                    "reasons": c["reasons"], "last_seen": c["last_seen"], "soc_pct": c["soc_pct"],
                    "excluded_from_dispatch": c["health"] == "untrusted"}
            if c["commitments"] and c["health"] == "untrusted":
                subs = [x for x in fs["clusters"] if x["asset_class"] == c["asset_class"] and x["health"] == "ok"
                        and not x["commitments"] and x["dispatchable_kw"] >= c["committed_dkw_kw"]]
                subs.sort(key=lambda x: -x["dispatchable_kw"])
                item["dkw_commitment_at_risk"] = {"commitments": c["commitments"], "committed_kw": c["committed_dkw_kw"],
                                                  "substitute_candidates": [x["cluster_id"] for x in subs[:3]]}
            exceptions.append(item)
    tot = lambda f: r2(sum(v[f] for v in cls.values()), 2)  # noqa: E731
    return {
        "status": "ok", "date": date, "slot": int(slot), "time": slot_label(int(slot)), "telemetry_snapshot": NOW,
        "by_asset_class": cls,
        "totals": {"capacity_mw": tot("capacity_mw"), "available_mw": tot("available_mw"),
                   "committed_dkw_mw": tot("committed_dkw_mw"), "dispatchable_mw": tot("dispatchable_mw"),
                   "dispatchable_mwh": tot("dispatchable_mwh"), "clusters": len(fs["clusters"])},
        "telemetry_exceptions": exceptions,
        "dkw_commitments_in_slot": [{"commitment_id": x["commitment_id"], "cluster_id": x["cluster_id"], "product": x["product"],
                                     "committed_kw": x["committed_kw"], "slots": f"{x['from_slot']}-{x['to_slot']}"}
                                    for x in fs["commitments"]],
        "rules": "Untrusted = heartbeat older than 30 min or SOC flat for 6 h [desk_policy_guide.md Section 6]; "
                 "dKW capacity and 2x duration reserve energy are held back [desk_policy_guide.md Section 5].",
        "source": src("vpp_clusters", "vpp_telemetry_30min", "ancillary_commitments"),
    }


# ----------------------------------------------------------------------------------------------- hedge plan
@lru_cache(maxsize=64)
def _plan(date: str, a: int, b: int, now: str) -> dict:
    from scipy.optimize import linprog

    pos = {int(r["slot"]): r for r in _position_rows(date, a, b)}
    mkt = {int(r["slot"]): r for r in _market_rows(date, a, b)}
    slots, closed, longs = [], [], []
    for s in range(a, b + 1):
        st = gate_status(date, s, now)
        if s not in pos:
            continue
        op = float(pos[s]["open_position_mwh"])
        if st != "open":
            closed.append({"slot": s, "gate_status": st, "open_position_mwh": r2(op, 1)})
        elif op < -0.5:
            slots.append(s)
        elif op > 0.5:
            longs.append({"slot": s, "open_position_mwh": r2(op, 1)})
    # Fleet: clusters dispatchable over all planned slots (min headroom across the slots, shared energy budget).
    fleets = {s: fleet_state(date, s, now) for s in slots}
    cl_ids = [c["cluster_id"] for c in fleets[slots[0]]["clusters"]] if slots else []
    excluded = []
    if slots:
        for c in fleets[slots[0]]["clusters"]:
            if c["health"] == "untrusted":
                excluded.append({"cluster_id": c["cluster_id"], "asset_class": c["asset_class"], "reasons": c["reasons"],
                                 "would_have_offered_kw": c["available_kw"], "commitments_at_risk": c["commitments"]})
    need = {s: -float(pos[s]["open_position_mwh"]) for s in slots}
    # Variables: per slot [q1, q2, residual] + per (cluster, slot) dispatch.
    idx: dict[tuple, int] = {}
    cost, ub = [], []

    def add(key, c, u):
        idx[key] = len(cost)
        cost.append(c)
        ub.append(u)

    for s in slots:
        m = mkt[s]
        add(("q1", s), float(m["best_ask_jpy_kwh"]), float(m["ask_depth_mwh"] or 0))
        add(("q2", s), float(m["ask_level2_jpy_kwh"]), float(m["ask_level2_depth_mwh"] or 0))
        add(("res", s), RESIDUAL_PENALTY_JPY_KWH, None)
        for c in fleets[s]["clusters"]:
            if c["dispatchable_kw"] > 0 and c["dispatchable_kwh"] > 0:
                add(("vpp", c["cluster_id"], s), float(c["dispatch_cost_jpy_kwh"]), c["dispatchable_kw"] * 0.5 / 1000)
    n = len(cost)
    result: dict[str, Any] = {"slots": {}, "dispatch": [], "excluded": excluded, "closed": closed, "longs": longs}
    if not slots:
        return result
    A_eq, b_eq = [], []
    for s in slots:
        row = np.zeros(n)
        for k, i in idx.items():
            if (k[0] in ("q1", "q2", "res") and k[1] == s) or (k[0] == "vpp" and k[2] == s):
                row[i] = 1
        A_eq.append(row)
        b_eq.append(need[s])
    A_ub, b_ub = [], []
    energy = {c["cluster_id"]: c["dispatchable_kwh"] / 1000 for c in fleets[slots[0]]["clusters"]}
    for cid in cl_ids:
        cols = [i for k, i in idx.items() if k[0] == "vpp" and k[1] == cid]
        if cols:
            row = np.zeros(n)
            row[cols] = 1
            A_ub.append(row)
            b_ub.append(energy[cid])
    res = linprog(np.array(cost), A_ub=np.array(A_ub) if A_ub else None, b_ub=np.array(b_ub) if b_ub else None,
                  A_eq=np.array(A_eq), b_eq=np.array(b_eq), bounds=[(0, u) for u in ub], method="highs")
    if res.status != 0:
        raise RuntimeError(f"hedge LP failed: {res.message}")
    x = res.x
    cinfo = {c["cluster_id"]: c for c in fleets[slots[0]]["clusters"]}
    for s in slots:
        m = mkt[s]
        q1, q2, rs = x[idx[("q1", s)]], x[idx[("q2", s)]], x[idx[("res", s)]]
        vpp = [(k[1], x[i]) for k, i in idx.items() if k[0] == "vpp" and k[2] == s and x[i] > 1e-6]
        vpp_mwh = sum(v for _, v in vpp)
        vpp_cost = sum(v * cinfo[c]["dispatch_cost_jpy_kwh"] for c, v in vpp) * 1000
        intra_cost = (q1 * float(m["best_ask_jpy_kwh"]) + q2 * float(m["ask_level2_jpy_kwh"])) * 1000
        p50, p90 = float(m["imbalance_price_jpy_kwh"]), float(m["imbalance_p90_jpy_kwh"])
        result["slots"][s] = {
            "slot": s, "time": slot_label(s), "gate_closure": gate_closure(date, s), "short_mwh": r2(need[s], 1),
            "intraday_level1_mwh": r2(q1, 2), "intraday_level1_price_jpy_kwh": r2(m["best_ask_jpy_kwh"]),
            "intraday_level2_mwh": r2(q2, 2), "intraday_level2_price_jpy_kwh": r2(m["ask_level2_jpy_kwh"]),
            "intraday_cost_jpy": r2(intra_cost, 0), "vpp_mwh": r2(vpp_mwh, 2), "vpp_cost_jpy": r2(vpp_cost, 0),
            "residual_mwh": r2(rs, 2), "imbalance_p50_jpy_kwh": r2(p50), "imbalance_p90_jpy_kwh": r2(p90),
            "residual_expected_cost_jpy": r2(rs * p50 * 1000, 0),
            "do_nothing_cost_p50_jpy": r2(need[s] * p50 * 1000, 0), "do_nothing_cost_p90_jpy": r2(need[s] * p90 * 1000, 0),
            "tokyo_spot_jpy_kwh": r2(m["tokyo_price_jpy_kwh"]), "reserve_margin_pct": r2(m["reserve_margin_pct"]),
        }
        for c, v in vpp:
            result["dispatch"].append({"cluster_id": c, "asset_class": cinfo[c]["asset_class"], "slot": s,
                                       "mwh": r2(v, 3), "mw": r2(v * 2, 3), "cost_jpy_kwh": cinfo[c]["dispatch_cost_jpy_kwh"]})
    return result


@safe_tool
def plan_hedge(date: str, from_slot: int, to_slot: int) -> dict:
    """Deterministic least-cost cover of the open short per slot before gate closure. Options in merit order are
    VPP dispatch (trusted clusters only, dKW capacity and reserve energy held back, shared SOC budget across slots)
    and JEPX intraday buys (best ask and second ask level, limited by book depth). Imbalance is never chosen as an
    option; any residual is what cannot physically be covered and must be escalated. Returns cost of the plan versus
    the expected imbalance cost of doing nothing (p50 and p90).

    Args:
      date: Delivery date YYYY-MM-DD (scenario 2026-08-19).
      from_slot: First slot 1-48.
      to_slot: Last slot 1-48, inclusive.
    """
    e = check_date(date) or check_slots(from_slot, to_slot)
    if e:
        return err(e)
    p = _plan(date, int(from_slot), int(to_slot), NOW)
    rows = list(p["slots"].values())
    if not rows:
        return {"status": "nothing_to_cover", "date": date, "closed_or_delivered": p["closed"], "long_slots": p["longs"],
                "note": "No open-gate slot in range is short by more than 0.5 MWh.",
                "source": src("balance_position_30min")}
    t = lambda f: sum(r[f] for r in rows)  # noqa: E731
    plan_cost = t("intraday_cost_jpy") + t("vpp_cost_jpy")
    residual_cost = t("residual_expected_cost_jpy")
    dn50, dn90 = t("do_nothing_cost_p50_jpy"), t("do_nothing_cost_p90_jpy")
    covered = t("intraday_level1_mwh") + t("intraday_level2_mwh") + t("vpp_mwh")
    by_class: dict[str, float] = {}
    for d in p["dispatch"]:
        by_class[d["asset_class"]] = by_class.get(d["asset_class"], 0) + d["mwh"]
    return {
        "status": "ok", "date": date, "as_of": NOW, "per_slot": rows,
        "vpp_dispatch_by_class_mwh": {k: r2(v, 2) for k, v in sorted(by_class.items())},
        "vpp_clusters_used": len({d["cluster_id"] for d in p["dispatch"]}),
        "totals": {
            "short_mwh": r2(t("short_mwh"), 1), "covered_mwh": r2(covered, 1),
            "intraday_mwh": r2(t("intraday_level1_mwh") + t("intraday_level2_mwh"), 2), "vpp_mwh": r2(t("vpp_mwh"), 2),
            "residual_mwh": r2(t("residual_mwh"), 2),
            "plan_cost_jpy": r2(plan_cost, 0), "residual_expected_cost_jpy": r2(residual_cost, 0),
            "do_nothing_expected_cost_p50_jpy": r2(dn50, 0), "do_nothing_cost_p90_jpy": r2(dn90, 0),
            "cost_avoided_p50_jpy": r2(dn50 - plan_cost - residual_cost, 0),
            "cost_avoided_p90_jpy": r2(dn90 - plan_cost - residual_cost, 0),
            "average_cover_price_jpy_kwh": r2(plan_cost / (covered * 1000), 2) if covered else None,
        },
        "excluded_clusters": p["excluded"], "closed_or_delivered_slots": p["closed"], "long_slots": p["longs"],
        "rules_applied": [
            "Imbalance is never selected as a cheaper option; residual only if physically uncoverable "
            "[desk_policy_guide.md Section 2].",
            "Untrusted telemetry clusters excluded [desk_policy_guide.md Section 6].",
            "dKW capacity and reserve energy held back [desk_policy_guide.md Section 5].",
            "Buys never exceed the open short [desk_policy_guide.md Section 2].",
        ],
        "source": src("balance_position_30min", "jepx_intraday_30min", "imbalance_30min", "vpp_clusters",
                      "vpp_telemetry_30min", "ancillary_commitments"),
    }


def _lots(mwh: float) -> float:
    return round(round(mwh / LOT_MWH) * LOT_MWH, 2)


@safe_tool
def propose_intraday_orders(date: str, from_slot: int, to_slot: int, tool_context: Optional[Any] = None) -> dict:
    """Create PENDING JEPX intraday buy orders for the intraday legs of the least-cost hedge plan (quantities rounded
    to 50 kWh lots, limit price = highest ask level used). Nothing is sent to the market: a person must approve with
    Hold-to-Confirm.

    Args:
      date: Delivery date YYYY-MM-DD.
      from_slot: First slot 1-48.
      to_slot: Last slot 1-48, inclusive.
    """
    e = check_date(date) or check_slots(from_slot, to_slot)
    if e:
        return err(e)
    p = _plan(date, int(from_slot), int(to_slot), NOW)
    orders = []
    for s, r in sorted(p["slots"].items()):
        q = _lots((r["intraday_level1_mwh"] or 0) + (r["intraday_level2_mwh"] or 0))
        if q <= 0:
            continue
        limit = r["intraday_level2_price_jpy_kwh"] if (r["intraday_level2_mwh"] or 0) > 1e-6 else r["intraday_level1_price_jpy_kwh"]
        orders.append({"slot": s, "time": r["time"], "side": "buy", "quantity_mwh": q, "limit_price_jpy_kwh": limit,
                       "expected_cost_jpy": r["intraday_cost_jpy"], "gate_closure": r["gate_closure"],
                       "imbalance_p50_jpy_kwh": r["imbalance_p50_jpy_kwh"]})
    if not orders:
        return {"status": "nothing_to_propose", "note": "The plan has no intraday legs in this range.",
                "source": src("balance_position_30min", "jepx_intraday_30min")}
    total_q = r2(sum(o["quantity_mwh"] for o in orders), 2)
    total_c = r2(sum(o["expected_cost_jpy"] for o in orders), 0)
    slots = f"{orders[0]['slot']}-{orders[-1]['slot']}" if len(orders) > 1 else str(orders[0]["slot"])
    action = {
        "id": f"PA-ID-{date[5:7]}{date[8:10]}-{int(from_slot):02d}{int(to_slot):02d}-{short_hash(orders)}",
        "kind": "intraday_orders", "created_by": "trading_dispatch_agent",
        "summary": f"Buy {total_q} MWh on JEPX intraday for slots {slots} on {date}, limit up to "
                   f"{max(o['limit_price_jpy_kwh'] for o in orders)} JPY/kWh, expected cost {total_c:,.0f} JPY",
        "details": {"date": date, "orders": orders, "total_quantity_mwh": total_q, "expected_cost_jpy": total_c},
        "risk": "medium",
        "reasoning": [f"Slot {o['slot']}: short covered partly at intraday ask; expected imbalance p50 "
                      f"{o['imbalance_p50_jpy_kwh']} JPY/kWh vs limit {o['limit_price_jpy_kwh']} JPY/kWh" for o in orders],
        "sources": src("balance_position_30min", "jepx_intraday_30min", "imbalance_30min") + ["desk_policy_guide.md Section 4"],
        "requires": "hold_to_confirm",
    }
    record_proposal(tool_context, action)
    return {"status": "pending_approval", "pending_action": action,
            "note": "Pending only. No order has been sent. Approval requires Hold-to-Confirm by a person.",
            "source": action["sources"][:3]}


@safe_tool
def propose_vpp_dispatch(date: str, from_slot: int, to_slot: int, tool_context: Optional[Any] = None) -> dict:
    """Create a PENDING VPP dispatch schedule (per cluster and slot) for the VPP legs of the least-cost hedge plan.
    Untrusted clusters are never included. Nothing is dispatched: a person must approve with Hold-to-Confirm.

    Args:
      date: Delivery date YYYY-MM-DD.
      from_slot: First slot 1-48.
      to_slot: Last slot 1-48, inclusive.
    """
    e = check_date(date) or check_slots(from_slot, to_slot)
    if e:
        return err(e)
    p = _plan(date, int(from_slot), int(to_slot), NOW)
    sched = [d for d in p["dispatch"] if d["mwh"] and d["mwh"] > 0]
    if not sched:
        return {"status": "nothing_to_propose", "note": "The plan has no VPP legs in this range.",
                "source": src("vpp_clusters", "vpp_telemetry_30min")}
    total = r2(sum(d["mwh"] for d in sched), 2)
    cost = r2(sum(d["mwh"] * d["cost_jpy_kwh"] * 1000 for d in sched), 0)
    by_slot = {}
    for d in sched:
        by_slot[d["slot"]] = r2(by_slot.get(d["slot"], 0) + d["mwh"], 2)
    excluded = [x["cluster_id"] for x in p["excluded"]]
    action = {
        "id": f"PA-VPP-{date[5:7]}{date[8:10]}-{int(from_slot):02d}{int(to_slot):02d}-{short_hash(sched)}",
        "kind": "vpp_dispatch", "created_by": "trading_dispatch_agent",
        "summary": f"Dispatch {total} MWh from {len({d['cluster_id'] for d in sched})} VPP clusters across slots "
                   f"{min(by_slot)}-{max(by_slot)} on {date}, expected cost {cost:,.0f} JPY"
                   + (f"; excluded {', '.join(excluded)} (untrusted telemetry)" if excluded else ""),
        "details": {"date": date, "schedule": sched, "mwh_by_slot": by_slot, "total_mwh": total, "expected_cost_jpy": cost,
                    "excluded_clusters": excluded},
        "risk": "medium",
        "reasoning": [f"VPP cost {min(d['cost_jpy_kwh'] for d in sched)}-{max(d['cost_jpy_kwh'] for d in sched)} JPY/kWh is "
                      "below the intraday ask and the imbalance forecast in every slot",
                      "dKW commitments and their reserve energy are held back", "Clusters with stale or frozen telemetry excluded"],
        "sources": src("vpp_clusters", "vpp_telemetry_30min", "ancillary_commitments") + ["desk_policy_guide.md Section 5"],
        "requires": "hold_to_confirm",
    }
    record_proposal(tool_context, action)
    return {"status": "pending_approval", "pending_action": action,
            "note": "Pending only. No dispatch signal has been sent. Approval requires Hold-to-Confirm by a person.",
            "source": action["sources"][:3]}
