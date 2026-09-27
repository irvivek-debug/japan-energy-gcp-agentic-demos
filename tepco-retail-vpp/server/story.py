"""Read-only endpoints for the v2 screens (landing, case chapters, workspace). Every figure is computed here from the
datastore and the deterministic tools, or read from eval/results; research claims carry their MARKET_FACTS citation.
Nothing is written: these endpoints never create, change or execute anything."""
from __future__ import annotations

import inspect
import json
import os
import statistics
import threading
from functools import lru_cache
from typing import Any

from fastapi import APIRouter

from retail_desk import catalog, model_policy
from retail_desk.clock import NOW, SCENARIO_DATE, gate_status, slot_label
from retail_desk.store import STORE, src
from retail_desk.tools import cfe as cfe_tools
from retail_desk.tools import market as mk
from retail_desk.tools import onboarding as ob
from retail_desk.tools import risk as rk

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "eval", "results")
router = APIRouter(prefix="/api")
SHORT = (35, 38)
MF = "docs/research/MARKET_FACTS.md"
NO_BENCH = "NO VERIFIED BENCHMARK HELD"

# Research claims (third-party figures), each with its source as held in MARKET_FACTS.md. Rendered in a different
# register from measured figures on every screen.
RESEARCH = {
    "balancing": {"claim": "Every balancing group plans in 30-minute slots and settles any deviation at the imbalance price; "
                           "deliberate imbalance is treated as improper conduct.",
                  "cite": "METI / JFTC fair electricity trading guideline, 2026-03-13 edition", "ref": f"{MF} section 3"},
    "scarcity": {"claim": "Scarcity pricing reaches its 200 JPY/kWh cap at a 3% wide-area reserve margin; the cap rises to "
                          "300 JPY/kWh on 2026-10-01, when JEPX intraday also becomes API-only.",
                 "cite": "METI / EGC 2019 interim report; EGC committee 2025-04-25; JEPX notice 2026-09-08", "ref": f"{MF} sections 3, 4.1"},
    "flex": {"claim": "1.14 million home batteries, about 9.57 GWh, shipped FY2013-FY2025; aggregated low-voltage resources may "
                      "join every balancing product from FY2026.",
             "cite": "JEMA 2026-06-05; OCCTO balancing market subcommittee 2025-09-26", "ref": f"{MF} section 8"},
    "cfe": {"claim": "Google's carbon-free energy score on the TEPCO grid was 23% in 2025 (7% contracted, 16% from the grid).",
            "cite": "Google 2026 Environmental Report", "ref": f"{MF} section 6.4"},
    "prices": {"claim": "Tokyo area spot averaged 20.36 JPY/kWh in FY2026 to date against 12.45 in FY2025, after fuel costs "
                        "rose and a large long-term contract ended.",
               "cite": "JEPX spot results (analyst computation); EGC committee 2026-06-19", "ref": f"{MF} sections 1.2, 1.6"},
}


def _r(x: Any, n: int = 1) -> Any:
    return None if x is None else round(float(x), n)


# ------------------------------------------------------------------------------------------- shared figures
_FIG_LOCK = threading.Lock()


def figures() -> dict:
    """Compute-once: concurrent first requests wait for one computation instead of each re-running it."""
    with _FIG_LOCK:
        return _figures()


@lru_cache(maxsize=1)
def _figures() -> dict:
    """The handful of scenario figures every v2 screen quotes, computed once from the tools."""
    # The seven tool calls are independent; run them together so a cold start costs the slowest one, not the sum
    # (measured on BigQuery: 36.5 s sequential). The datastore is thread-safe (one cursor per query).
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=8) as ex:
        f_plan = ex.submit(mk.plan_hedge, SCENARIO_DATE, *SHORT)
        f_mkt = ex.submit(mk._market_rows, SCENARIO_DATE, 1, 48)
        f_fs = ex.submit(mk.fleet_state, SCENARIO_DATE, SHORT[0])
        f_mar = ex.submit(rk.compute_margin_at_risk, "2026-08-20", "2026-08-31", 40)
        f_dev = ex.submit(rk.get_deviation_breaches, "2026-08-01", SCENARIO_DATE)
        f_cfe = ex.submit(cfe_tools.get_cfe_score, "C-0001", "2026-08")
        f_ppa = ex.submit(ob.design_cfe_ppa, "PR-01", 90, 15)
        f_led = ex.submit(cfe_tools.audit_nfc_ledger, "2026-08")
    plan = f_plan.result()
    t = plan["totals"]
    rows = plan["per_slot"]
    short = t["short_mwh"]
    imb_w = sum(r["short_mwh"] * r["imbalance_p50_jpy_kwh"] for r in rows) / short
    ask = statistics.mean(r["intraday_level1_price_jpy_kwh"] for r in rows)
    mkt = f_mkt.result()
    ahead = [r for r in mkt if 32 < int(r["slot"]) <= 44]
    low = min(ahead, key=lambda r: r["reserve_margin_pct"])
    fs = f_fs.result()
    avail = sum(c["available_kw"] for c in fs["clusters"]) / 1000
    disp = sum(c["dispatchable_kw"] for c in fs["clusters"]) / 1000
    committed = sum(c["committed_dkw_kw"] for c in fs["clusters"]) / 1000
    untrusted = [c for c in fs["clusters"] if c["health"] == "untrusted"]
    untrusted_kw = sum(c["available_kw"] for c in untrusted) / 1000
    at_risk = [{"cluster_id": c["cluster_id"], "commitments": c["commitments"], "committed_kw": c["committed_dkw_kw"]}
               for c in untrusted if c["commitments"]]
    mar, dev, otemachi, ppa, ledger = f_mar.result(), f_dev.result(), f_cfe.result(), f_ppa.result(), f_led.result()
    from retail_desk.tools.desk import get_desk_clock

    c = get_desk_clock()
    clock = {"now": c["now"], "gate_closure": c["next_gate_closure"]["gate_closure"], "minutes_left": c["next_gate_closure"]["minutes_left"],
             "next_slot": c["next_gate_closure"]["slot"], "next_slot_time": c["next_gate_closure"]["slot_time"]}
    return {
        "clock": clock,
        "short_mwh": short, "short_by_slot": {r["slot"]: r["short_mwh"] for r in rows},
        "plan_cost_jpy": t["plan_cost_jpy"], "do_nothing_p50_jpy": t["do_nothing_expected_cost_p50_jpy"],
        "do_nothing_p90_jpy": t["do_nothing_cost_p90_jpy"], "avoided_p50_jpy": t["cost_avoided_p50_jpy"],
        "avoided_p90_jpy": t["cost_avoided_p90_jpy"], "residual_mwh": t["residual_mwh"],
        "vpp_mwh": t["vpp_mwh"], "intraday_mwh": t["intraday_mwh"], "cover_price_jpy_kwh": t["average_cover_price_jpy_kwh"],
        "vpp_cost_jpy": sum(r["vpp_cost_jpy"] for r in rows), "imbalance_p50_weighted_jpy_kwh": imb_w,
        "intraday_ask_avg_jpy_kwh": ask, "reserve_margin_min_pct": float(low["reserve_margin_pct"]),
        "reserve_margin_min_slot": int(low["slot"]), "reserve_margin_min_time": slot_label(int(low["slot"])),
        "vpp_available_mw": avail, "vpp_dispatchable_mw": disp, "dkw_committed_mw": committed,
        "untrusted_mw": untrusted_kw, "untrusted": [c["cluster_id"] for c in untrusted], "dkw_at_risk": at_risk,
        "clusters_total": len(fs["clusters"]),
        "mar_jpy": mar["margin_at_risk_jpy"], "margin_before_jpy": mar["expected_margin_before_jpy"],
        "margin_after_jpy": mar["expected_margin_after_jpy"], "hedge_cover_pct": mar["hedge_cover_pct"],
        "negative_margin_customers": mar["customers_negative_margin_after_shock"],
        "dev_total_cost_jpy": dev["total_deviation_cost_jpy"], "dev_top": dev["top_customers"][0],
        "dev_top_share_pct": dev["worst_customer_share_of_cost_pct"], "dev_customers_breaching": dev["customers_with_breaches"],
        "otemachi": {k: otemachi[k] for k in ("name", "annual_style_volumetric_match_pct", "contracted_hourly_matched_pct",
                                              "grid_cfe_contribution_pct", "cfe_score_24x7_pct")},
        "ppa": {"prospect": "Hokuso Cloud Campus", "site": "Inzai, Chiba", "target_pct": 90, "term_years": 15,
                "achieved_hourly_cfe_pct": ppa.get("achieved_hourly_cfe_pct"), "annual_matched_pct": ppa.get("annual_matched_pct"),
                "annual_load_gwh": ppa.get("annual_load_gwh"), "price_range_jpy_kwh": ppa.get("price_build_up", {}).get("price_range_jpy_kwh"),
                "price_jpy_kwh": ppa.get("price_build_up", {}).get("total_jpy_kwh")},
        "ledger": {"findings": ledger["findings_total"], "entries": ledger["entries_checked"],
                   "double_claims": ledger["double_claims"], "affected": ledger["affected_customers"]},
    }


def _money(v: float) -> str:
    a = abs(v)
    s = f"{a / 1e9:,.2f}B" if a >= 1e9 else (f"{a / 1e6:,.1f}M" if a >= 1e6 else f"{a:,.0f}")
    return ("-" if v < 0 else "") + s + " JPY"


# ------------------------------------------------------------------------------------------------ landing
@router.get("/story/provenance")
def story_provenance():
    p = os.path.join(ROOT, "retail_desk", "data_manifest.json")
    m = json.load(open(p)) if os.path.exists(p) else {}
    return {"dataset": STORE.dataset, "backend": STORE.backend, "seed": m.get("seed"), "generator": m.get("generator"),
            "scenario_now": NOW, "calendar": m.get("calendar"), "tables": m.get("tables"), "rows": m.get("rows"),
            "research": MF}


@router.get("/story/facts")
def story_facts():
    f = figures()
    return {"now": NOW, "scenario_date": SCENARIO_DATE, **f,
            "agents": len(catalog.AGENTS), "branches": len(catalog.BRANCHES),
            "sign_off_kinds": ["intraday_orders", "vpp_dispatch", "tariff_adjustment", "ppa_offer"],
            "source": src("balance_position_30min", "imbalance_30min", "jepx_intraday_30min", "vpp_telemetry_30min",
                          "customer_forecast_daily", "cfe_allocation_hourly", "prospect_load_hourly", "nfc_ledger")}


@router.get("/story/gap")
def story_gap():
    f = figures()
    o = f["otemachi"]
    p = f["ppa"]
    rows = [
        {"id": "short", "quantity": "Evening short at gate closure", "unit": "MWh",
         "sub": f"Slots {SHORT[0]}-{SHORT[1]}, {slot_label(SHORT[0])[:5]} to {slot_label(SHORT[1])[-5:]}",
         "ordinary": {"value": f["short_mwh"], "unit": "MWh", "label": "left open if nobody acts"},
         "best": {"value": f["residual_mwh"], "unit": "MWh", "label": "left open after the least-cost plan"},
         "gap": {"text": f"{f['short_mwh']:,.1f} MWh to cover in {f['clock']['minutes_left']} min"},
         "research": RESEARCH["balancing"], "source": src("balance_position_30min")},
        {"id": "price", "quantity": "Price of each kWh of cover", "unit": "JPY/kWh", "sub": "Scarcity slots, weighted by the short",
         "ordinary": {"value": f["imbalance_p50_weighted_jpy_kwh"], "unit": "JPY/kWh", "label": "imbalance forecast (p50)"},
         "best": {"value": f["cover_price_jpy_kwh"], "unit": "JPY/kWh",
                  "label": f"batteries plus intraday (intraday alone {f['intraday_ask_avg_jpy_kwh']:,.1f})"},
         "gap": {"text": f"{f['imbalance_p50_weighted_jpy_kwh'] - f['cover_price_jpy_kwh']:,.1f} JPY/kWh, "
                         f"{_money(f['avoided_p50_jpy'])} this evening"},
         "research": RESEARCH["scarcity"], "source": src("imbalance_30min", "jepx_intraday_30min", "vpp_clusters")},
        {"id": "vpp", "quantity": "Battery and demand-response power at 17:00", "unit": "MW", "sub": f"{f['clusters_total']} pools",
         "ordinary": {"value": f["vpp_available_mw"], "unit": "MW", "label": "reported as available"},
         "best": {"value": f["vpp_dispatchable_mw"], "unit": "MW", "label": "trusted and not sold to the grid operator"},
         "gap": {"text": f"{f['vpp_available_mw'] - f['vpp_dispatchable_mw']:,.1f} MW that cannot be counted on "
                         f"({f['dkw_committed_mw']:,.1f} MW committed, {len(f['untrusted'])} pool untrusted)"},
         "research": RESEARCH["flex"], "source": src("vpp_clusters", "vpp_telemetry_30min", "ancillary_commitments")},
        {"id": "cfe", "quantity": "Clean supply matched hour by hour", "unit": "%", "sub": f"{o['name']}, August to date",
         "ordinary": {"value": o["contracted_hourly_matched_pct"], "unit": "%",
                      "label": f"hour by hour, while the annual view reads {o['annual_style_volumetric_match_pct']:,.1f}%"},
         "best": {"value": p["achieved_hourly_cfe_pct"], "unit": "%", "label": f"24/7 design for the {p['site'].split(',')[0]} campus"},
         "gap": {"text": f"{(p['achieved_hourly_cfe_pct'] or 0) - o['contracted_hourly_matched_pct']:+,.1f} points"},
         "research": RESEARCH["cfe"], "source": src("cfe_allocation_hourly", "prospect_load_hourly", "clean_supply_hourly")},
        {"id": "margin", "quantity": "Margin if spot rises 40%", "unit": "JPY", "sub": "Rest of August, 12 days",
         "ordinary": {"value": f["margin_before_jpy"], "unit": "JPY", "label": f"expected, {f['hedge_cover_pct']:,.1f}% hedged"},
         "best": {"value": None, "unit": "JPY", "label": "no hedge target is held in the book"},
         "gap": {"text": f"{_money(f['mar_jpy'])} at risk; margin ends at {_money(f['margin_after_jpy'])}"},
         "research": RESEARCH["prices"], "source": src("customer_forecast_daily", "forward_curve_daily", "hedge_book")},
    ]
    note = ("This is one heatwave afternoon on synthetic data calibrated to FY2026 market prices. The cost avoided is the "
            "expected imbalance cost at the p50 forecast minus the cost of the plan, not a realised saving. The gap is the "
            "distance between what the desk can see and what it can act on before 16:00. Value per year is argued in the "
            "case, as ranges, with every assumption named.")
    return {"rows": rows, "note": note, "as_of": NOW}


@router.get("/story/evidence")
def story_evidence():
    days = ["2026-08-18", SCENARIO_DATE]
    labels = [f"{d[5:]} {slot_label(s)[:5]}" for d in days for s in range(1, 49)]
    idx = {(d, s): i for i, (d, s) in enumerate((d, s) for d in days for s in range(1, 49))}
    n = len(labels)

    def series(rows, key):
        vals = [None] * n
        for r in rows:
            k = (r["date"], int(r["slot"]))
            if k in idx:
                vals[idx[k]] = _r(r[key], 2)
        return vals

    spot = STORE.query("SELECT date, slot, tokyo_price_jpy_kwh FROM {t:jepx_spot_30min} WHERE date >= @a AND date <= @b", a=days[0], b=days[1])
    imb = STORE.query("SELECT date, slot, imbalance_price_jpy_kwh, reserve_margin_pct, scarcity_flag, is_forecast FROM {t:imbalance_30min} "
                      "WHERE date >= @a AND date <= @b", a=days[0], b=days[1])
    pos = STORE.query("SELECT date, slot, open_position_mwh, demand_actual_mwh FROM {t:balance_position_30min} WHERE date >= @a AND date <= @b",
                      a=days[0], b=days[1])
    tel = STORE.query("SELECT t.date, t.slot, t.cluster_id, t.soc_pct FROM {t:vpp_telemetry_30min} t JOIN {t:vpp_clusters} c "
                      "ON c.cluster_id = t.cluster_id WHERE c.asset_class = 'residential_battery' AND t.date >= @a", a=days[0])
    untrusted = set(figures()["untrusted"])
    soc_sum: dict = {}
    frozen = [None] * n
    for r in tel:
        k = (r["date"], int(r["slot"]))
        if r["cluster_id"] in untrusted:
            frozen[idx[k]] = _r(r["soc_pct"], 1)
            continue
        a = soc_sum.setdefault(k, [0.0, 0])
        a[0] += r["soc_pct"]
        a[1] += 1
    soc = [None] * n
    for k, (s, c) in soc_sum.items():
        soc[idx[k]] = round(s / c, 1)
    forecast = [False] * n
    scarcity = [False] * n
    for r in imb:
        i = idx[(r["date"], int(r["slot"]))]
        forecast[i] = bool(r["is_forecast"])
        scarcity[i] = bool(r["scarcity_flag"])
    now_i = idx[(SCENARIO_DATE, 32)]
    cards = [
        {"id": "spot", "label": "Tokyo area spot price", "unit": "JPY/kWh", "values": series(spot, "tokyo_price_jpy_kwh"),
         "kind": "cleared day ahead", "source": src("jepx_spot_30min")},
        {"id": "imbalance", "label": "Imbalance price", "unit": "JPY/kWh", "values": series(imb, "imbalance_price_jpy_kwh"),
         "kind": "settled, then p50 forecast", "source": src("imbalance_30min")},
        {"id": "reserve", "label": "Wide-area reserve margin", "unit": "%", "values": series(imb, "reserve_margin_pct"),
         "kind": "actual, then forecast", "source": src("imbalance_30min")},
        {"id": "position", "label": "Balance group open position", "unit": "MWh", "values": series(pos, "open_position_mwh"),
         "kind": "negative is short", "source": src("balance_position_30min")},
        {"id": "soc", "label": "Home batteries, average charge", "unit": "%", "values": soc,
         "kind": "trusted pools, recorded to 15:40", "source": src("vpp_telemetry_30min")},
        {"id": "frozen", "label": f"Pool {', '.join(sorted(untrusted)) or 'none'}, charge", "unit": "%", "values": frozen,
         "kind": "reported value, heartbeat stale", "source": src("vpp_telemetry_30min")},
    ]
    return {"window": {"from": f"{days[0]}T00:00", "to": f"{days[1]}T24:00", "points": n, "labels": labels, "now_index": now_i,
                       "now": NOW}, "forecast": forecast, "scarcity": scarcity, "cards": cards}


# ------------------------------------------------------------------------------------------------ the case
CURVES = {"today": (200.0, 45.0), "october": (300.0, 50.0)}  # (cap C, D) in JPY/kWh, MARKET_FACTS section 3


def _scarcity(rm: float, cap: float, d: float) -> float:
    """Scarcity-adjusted imbalance curve (MARKET_FACTS s3): 0 at 10%, D at 8%, cap at 3% and below, linear between."""
    if rm >= 10:
        return 0.0
    if rm >= 8:
        return d * (10 - rm) / 2
    if rm > 3:
        return d + (8 - rm) / 5 * (cap - d)
    return cap


@router.get("/story/case")
def story_case():
    f = figures()
    mkt = {int(r["slot"]): r for r in mk._market_rows(SCENARIO_DATE, *SHORT)}
    slots = []
    for s, short in f["short_by_slot"].items():
        r = mkt[int(s)]
        rm = float(r["reserve_margin_pct"])
        now_p = max(float(r["tokyo_price_jpy_kwh"]) * 1.07, _scarcity(rm, CURVES["today"][0], CURVES["today"][1]))
        oct_p = max(float(r["tokyo_price_jpy_kwh"]) * 1.07, _scarcity(rm, CURVES["october"][0], CURVES["october"][1]))
        slots.append({"slot": int(s), "time": slot_label(int(s)), "short_mwh": short, "reserve_margin_pct": rm,
                      "imbalance_now_jpy_kwh": round(now_p, 2), "imbalance_october_jpy_kwh": round(oct_p, 2)})
    now_cost = sum(x["short_mwh"] * x["imbalance_now_jpy_kwh"] * 1000 for x in slots)
    oct_cost = sum(x["short_mwh"] * x["imbalance_october_jpy_kwh"] * 1000 for x in slots)
    daily = STORE.query("SELECT date, AVG(tokyo_price_jpy_kwh) AS tokyo, AVG(system_price_jpy_kwh) AS sys, MAX(tokyo_price_jpy_kwh) AS peak "
                        "FROM {t:jepx_spot_30min} GROUP BY date ORDER BY date")
    months = STORE.query("SELECT month, AVG(tokyo_price_jpy_kwh) AS tokyo FROM {t:jepx_spot_30min} GROUP BY month ORDER BY month")
    mar = rk.compute_margin_at_risk("2026-08-20", "2026-08-31", 40)
    pros = STORE.query("SELECT prospect_id, name, site, segment, projected_annual_mwh, projected_peak_mw, cfe_ambition_pct "
                       "FROM {t:prospects} ORDER BY prospect_id")
    return {
        "curves": {"today": {"cap_jpy_kwh": 200.0, "d_jpy_kwh": 45.0, "cap_at_margin_pct": 3.0, "d_at_margin_pct": 8.0, "no_uplift_from_pct": 10.0,
                             "valid": "until 2026-09-30"},
                   "october": {"cap_jpy_kwh": 300.0, "d_jpy_kwh": 50.0, "cap_at_margin_pct": 3.0, "d_at_margin_pct": 8.0, "no_uplift_from_pct": 10.0,
                               "valid": "from 2026-10-01"}, "cite": RESEARCH["scarcity"]["cite"], "ref": RESEARCH["scarcity"]["ref"]},
        "october": {"slots": slots, "do_nothing_now_jpy": now_cost, "do_nothing_october_jpy": oct_cost,
                    "method": "p50 imbalance for this evening's forecast reserve margins, on today's curve (cap 200, D 45) and on the "
                              "curve from 2026-10-01 (cap 300, D 50); base price floor = 1.07 x spot, as in the imbalance forecast"},
        "daily_spot": [{"date": d["date"], "tokyo": _r(d["tokyo"], 2), "system": _r(d["sys"], 2), "peak": _r(d["peak"], 2)} for d in daily],
        "monthly_spot": [{"month": m["month"], "tokyo": _r(m["tokyo"], 2)} for m in months],
        "margin_by_tariff": mar["by_tariff_type"], "margin": {k: mar[k] for k in ("margin_at_risk_jpy", "expected_margin_before_jpy",
                                                                               "expected_margin_after_jpy", "hedge_cover_pct", "price_shock_pct",
                                                                               "from_date", "to_date")},
        "prospects": [{**p, "projected_annual_gwh": _r(p["projected_annual_mwh"] / 1000, 1)} for p in pros],
        "research": {"growth": {"claim": "Data-center and semiconductor load in Japan is forecast to add 4.20 GW by FY2030 and 7.62 GW by "
                                         "FY2035; the Tokyo summer peak grows from 55.0 GW (FY2026) to 58.9 GW (FY2035).",
                                "cite": "OCCTO demand forecast, 2026-01-21", "ref": f"{MF} section 7"},
                     "prices": RESEARCH["prices"], "scarcity": RESEARCH["scarcity"], "balancing": RESEARCH["balancing"],
                     "api": {"claim": "JEPX's new trading system is server to server with no screens; intraday moves to it for deliveries "
                                      "from 2026-10-01.", "cite": "JEPX notices 2025-04-10 and 2026-09-08", "ref": f"{MF} section 4.1"}},
        "source": src("balance_position_30min", "imbalance_30min", "jepx_spot_30min", "customer_forecast_daily", "prospects"),
    }


@router.get("/story/plan")
def story_plan():
    plan = mk.plan_hedge(SCENARIO_DATE, *SHORT)
    fs = mk.fleet_state(SCENARIO_DATE, SHORT[0])
    classes: dict = {}
    for c in fs["clusters"]:
        k = classes.setdefault(c["asset_class"], {"pools": 0, "available_mw": 0.0, "dispatchable_mw": 0.0, "committed_mw": 0.0,
                                                 "untrusted_mw": 0.0, "untrusted": 0, "degraded": 0})
        k["pools"] += 1
        k["available_mw"] += c["available_kw"] / 1000
        k["dispatchable_mw"] += c["dispatchable_kw"] / 1000
        k["committed_mw"] += min(c["committed_dkw_kw"], c["available_kw"]) / 1000 if c["health"] != "untrusted" else 0
        if c["health"] == "untrusted":
            k["untrusted"] += 1
            k["untrusted_mw"] += c["available_kw"] / 1000
        k["degraded"] += c["health"] == "degraded"
    for k in classes.values():
        for x in ("available_mw", "dispatchable_mw", "committed_mw", "untrusted_mw"):
            k[x] = round(k[x], 2)
    return {"per_slot": plan["per_slot"], "totals": plan["totals"], "vpp_by_class_mwh": plan["vpp_dispatch_by_class_mwh"],
            "excluded": plan["excluded_clusters"], "fleet_by_class": classes, "rules": plan["rules_applied"], "source": plan["source"]}


@router.get("/story/prize")
def story_prize():
    f = figures()
    lo_ev, hi_ev = 10, 25
    per_event_vpp = f["vpp_mwh"] * 1000 * f["intraday_ask_avg_jpy_kwh"] - f["vpp_cost_jpy"]
    load = f["ppa"]["annual_load_gwh"] or 0
    ranges = {
        "A": {"low": f["avoided_p50_jpy"] * lo_ev, "high": f["avoided_p90_jpy"] * hi_ev, "unit": "JPY per year",
              "basis": f"{_money(f['avoided_p50_jpy'])} (p50) to {_money(f['avoided_p90_jpy'])} (p90) avoided on this evening, "
                       f"times {lo_ev} to {hi_ev} scarcity evenings a year",
              "assumption": f"{lo_ev} to {hi_ev} scarcity evenings a year for this balancing group; above the cap after 2026-10-01 the value rises"},
        "B": {"low": per_event_vpp * lo_ev, "high": per_event_vpp * hi_ev, "unit": "JPY per year",
              "basis": f"{f['vpp_mwh']:,.1f} MWh dispatched at {f['vpp_cost_jpy'] / (f['vpp_mwh'] * 1000):,.1f} JPY/kWh instead of the "
                       f"{f['intraday_ask_avg_jpy_kwh']:,.1f} JPY/kWh average intraday ask, times {lo_ev} to {hi_ev} events",
              "assumption": "the intraday ask is the next alternative for the battery volume; wear and incentives are in the dispatch cost"},
        "C": {"low": f["mar_jpy"] * 0.30, "high": f["mar_jpy"] * 0.60, "unit": "JPY per 12-day stress window",
              "basis": f"30% to 60% of the {_money(f['mar_jpy'])} margin at risk at +40% spot for the rest of August",
              "assumption": "part of the fixed book moves to dynamic or bandwidth terms and hedge cover rises from "
                            f"{f['hedge_cover_pct']:,.1f}%"},
        "D": {"low": load * 1e6 * 0.9, "high": load * 1e6 * 1.3, "unit": "JPY per year, per campus",
              "basis": f"{load:,.1f} GWh a year at a retail margin of 0.9 to 1.3 JPY/kWh on a 15 to 20 year contract",
              "assumption": "one hyperscale campus of this size signs; the margin floor in desk policy is 0.50 JPY/kWh"},
        "E": {"low": None, "high": None, "unit": "not priced",
              "basis": f"{f['ledger']['findings']} ledger findings this month across {len(f['ledger']['affected'])} customers",
              "assumption": "the value is protecting the price premium on hourly claims; no verified figure for that premium is held"},
    }
    branches = [{**b, **ranges[b["code"]]} for b in catalog.BRANCHES]
    return {"branches": branches, "scale_note": "Ranges are for the synthetic C&I book in this demo (about 11 TWh a year). "
            "Each line names its mechanism and its assumption; the branches do not overlap, so they can be read side by side "
            "but not simply added across different units.", "as_of": NOW}


def _excerpt(text: str, n: int) -> str:
    """Cut at the last full sentence or line before n characters, so an excerpt never ends mid-thought."""
    if len(text) <= n:
        return text
    cut = text[:n]
    i = max(cut.rfind(". "), cut.rfind(".\n"), cut.rfind("\n\n"))
    return (cut[: i + 1] if i > n // 2 else cut).rstrip()


def _read(name: str) -> dict | None:
    p = os.path.join(RESULTS, name)
    return json.load(open(p)) if os.path.exists(p) else None


@router.get("/story/proof")
def story_proof():
    adk = _read("adk_summary.json") or {}
    gr = _read("grounding_results.json")
    sf = _read("safety_results.json")
    rep = _read("report_summary.json") or {}
    suites = []
    if adk:
        suites.append({"id": "adk", "name": "Agent evaluation (ADK)", "what": "Tool path, answer quality against case rubrics, and "
                       "hallucination checks, judged by a second model",
                       "first": sum(v["passed_first_attempt"] for v in adk.values()),
                       "after_retry": sum(v["passed_after_retry"] for v in adk.values()), "total": sum(v["total"] for v in adk.values())})
    if gr:
        s = gr["summary"]
        suites.append({"id": "grounding", "name": "Grounding", "what": "The key figures in each answer checked against truth "
                       "recomputed from the tables at test time", "first": s["grounded_first_attempt"],
                       "after_retry": s["grounded_after_retry"], "total": s["total"], "unverifiable": s.get("unverifiable", [])})
    if sf:
        s = sf["summary"]
        suites.append({"id": "safety", "name": "Safety", "what": "Instructions hidden in a bill, requests that break the "
                       "balancing rule or the margin floor, and attempts to skip human approval",
                       "first": s["passed_first_attempt"], "after_retry": s["passed_after_retry"], "total": s["total"]})
    cases = []
    for key, v in adk.items():
        for cid, c in v["cases"].items():
            cases.append({"suite": "adk", "set": key.split("/")[0], "id": cid, "agent": v["agent_name"], "result": c["classification"]})
    for cid, c in ((gr or {}).get("cases") or {}).items():
        cases.append({"suite": "grounding", "id": cid, "result": c["classification"], "label": c["first_attempt"]["label"]})
    for cid, c in ((sf or {}).get("cases") or {}).items():
        cases.append({"suite": "safety", "id": cid, "desc": c.get("desc"), "result": c["classification"]})
    worked = None
    if gr and "S1" in gr["cases"]:
        c = gr["cases"]["S1"]
        fa = c["first_attempt"]
        method = None
        try:
            import sys

            sys.path.insert(0, os.path.join(ROOT, "eval"))
            import grounding_eval

            method = inspect.getsource(grounding_eval.truth_short).strip()
        except Exception:
            method = None
        worked = {"scenario": "S1", "question": c.get("question"), "label": fa["label"], "classification": c["classification"],
                  "latency_s": fa.get("latency_s"), "tool_calls": fa.get("tool_calls", []),
                  "facts": [{"name": x["name"], "truth": x.get("truth"), "any_of": x.get("any_of"), "matched": x["matched"], "found": x.get("found"),
                             "basis": x.get("basis"), "options": x.get("options")} for x in fa.get("facts", [])],
                  "truth_method": method, "reply_excerpt": _excerpt(fa.get("reply") or "", 1400)}
    latencies = [c["first_attempt"].get("latency_s") for c in ((gr or {}).get("cases") or {}).values() if c["first_attempt"].get("latency_s")]
    return {"suites": suites, "pytest": rep.get("pytest"), "cases": cases, "worked_example": worked,
            "latency_s": {"median": _r(statistics.median(latencies)), "max": _r(max(latencies))} if latencies else None,
            "skipped": ["BigQuery parity test: runs only with DATA_BACKEND=bigquery"],
            "run_at": {"adk": max((v.get("run_at", "") for v in adk.values()), default=None), "grounding": (gr or {}).get("run_at"),
                       "safety": (sf or {}).get("run_at")}}


# ------------------------------------------------------------------------------------------------ workspace
@router.get("/story/value")
def story_value():
    f = figures()
    o = f["otemachi"]
    p = f["ppa"]
    top = f["dev_top"]
    metrics = [
        {"id": "cover", "name": "Evening short covered before gate closure", "unit": "%", "moved_by": "trading_dispatch_agent",
         "site": {"low": 100 * (1 - f["residual_mwh"] / f["short_mwh"]), "high": 100 * (1 - f["residual_mwh"] / f["short_mwh"]),
                  "label": f"{f['short_mwh']:,.1f} MWh short, {f['residual_mwh']:,.1f} MWh left after the plan"},
         "band": None, "band_label": NO_BENCH},
        {"id": "price", "name": "Price paid per kWh of cover in the scarcity slots", "unit": "JPY/kWh", "moved_by": "trading_dispatch_agent",
         "site": {"low": f["cover_price_jpy_kwh"], "high": f["imbalance_p50_weighted_jpy_kwh"],
                  "label": "the plan's average, against the imbalance price if nobody acts (p50)"},
         "band": {"low": 45.0, "high": 200.0}, "band_label": "Scarcity imbalance price: 45 JPY/kWh at 8% reserve margin, "
         "200 JPY/kWh cap at 3%", "cite": RESEARCH["scarcity"]["cite"]},
        {"id": "vppshare", "name": "Share of the short met by batteries and demand response", "unit": "%", "moved_by": "trading_dispatch_agent",
         "site": {"low": 100 * f["vpp_mwh"] / f["short_mwh"], "high": 100 * f["vpp_mwh"] / f["short_mwh"],
                  "label": f"{f['vpp_mwh']:,.1f} of {f['short_mwh']:,.1f} MWh, with {', '.join(f['untrusted'])} excluded"},
         "band": None, "band_label": NO_BENCH},
        {"id": "hedge", "name": "Price-exposed volume hedged, rest of August", "unit": "%", "moved_by": "contract_risk_agent",
         "site": {"low": f["hedge_cover_pct"], "high": f["hedge_cover_pct"],
                  "label": f"{_money(f['mar_jpy'])} margin at risk at +40% spot"},
         "band": None, "band_label": NO_BENCH},
        {"id": "breach", "name": "Deviation-band breach rate, worst customer", "unit": "%", "moved_by": "contract_risk_agent",
         "site": {"low": top["breach_rate_pct"], "high": top["breach_rate_pct"],
                  "label": f"{top['name']}: {top['breach_slots']} breaches, {f['dev_top_share_pct']:,.1f}% of the book's deviation cost"},
         "band": None, "band_label": NO_BENCH},
        {"id": "cfe", "name": "Clean supply matched hour by hour", "unit": "%", "moved_by": "cfe_provenance_agent",
         "site": {"low": o["contracted_hourly_matched_pct"], "high": p["achieved_hourly_cfe_pct"],
                  "label": f"{o['name']} today, against the 24/7 design for the Inzai campus"},
         "band": {"low": 17.0, "high": 66.0}, "band_label": "Google CFE: 17% to 23% on the TEPCO grid (2024-2025), 64% to 66% "
         "worldwide (2023-2025)", "cite": RESEARCH["cfe"]["cite"]},
        {"id": "ppa", "name": "24/7 clean supply price, Inzai campus", "unit": "JPY/kWh", "moved_by": "onboarding_agent",
         "site": {"low": (p["price_range_jpy_kwh"] or [None, None])[0], "high": (p["price_range_jpy_kwh"] or [None, None])[1],
                  "label": f"{p['achieved_hourly_cfe_pct']}% hourly, {p['term_years']} years, before network charges and levies"},
         "band": {"low": 12.45, "high": 20.36}, "band_label": "Tokyo area spot annual mean: 12.45 JPY/kWh (FY2025) to 20.36 (FY2026 to date)",
         "cite": RESEARCH["prices"]["cite"]},
    ]
    return {"metrics": metrics, "as_of": NOW}


def _tools(agent) -> list[str]:
    out = []
    for t in agent.tools:
        n = getattr(t, "__name__", None) or getattr(t, "name", "")
        if n:
            out.append(n)
    return out


@router.get("/agents")
def agents():
    from retail_desk.agent import SPECIALISTS, root_agent

    objs = {a.name: a for a in [root_agent, *SPECIALISTS]}
    out = []
    for a in catalog.AGENTS:
        o = objs[a["name"]]
        tools = [t for t in _tools(o) if t not in {s.name for s in SPECIALISTS}]
        writes = [t for t in tools if t.startswith("propose_")]
        out.append({**a, "model": model_policy.REASONING_ID if a["tier"] == "reasoning" else model_policy.BALANCED_ID,
                    "tools": tools, "tool_count": len(tools), "proposes": writes, "sign_off": bool(writes),
                    "calls": [s.name for s in SPECIALISTS] if a["name"] == root_agent.name else []})
    proof = story_proof()
    lat = proof.get("latency_s") or {}
    limits = [
        f"Answers take time: a median of {lat.get('median')} s and up to {lat.get('max')} s end to end in the last grounding run, "
        "because a reasoning-tier lead calls specialists one at a time." if lat else "Answer latency has not been measured yet.",
        "The data is synthetic and stops at the 15:40 snapshot; nothing here reads a live market, meter or device.",
        "Approving an action runs it in a sandbox and writes an audit record; no order reaches JEPX and no battery is dispatched.",
        "The 30-minute certificate ledger is a provenance pilot; Japan has no government hourly or 30-minute certificate yet.",
        "The lead may call each specialist at most twice per question; a question needing more is answered with what it has, and says so.",
    ]
    return {"agents": out, "sign_off_count": sum(1 for a in out if a["sign_off"]), "limits": limits}


_PM_LOCK = threading.Lock()


def _persona_metrics() -> dict:
    with _PM_LOCK:
        return _persona_metrics_once()


@lru_cache(maxsize=1)
def _persona_metrics_once() -> dict:
    f = figures()
    o = f["otemachi"]
    pros = STORE.query("SELECT SUM(projected_annual_mwh) AS mwh, COUNT(*) AS n FROM {t:prospects}")[0]
    return {
        "trader": [{"label": "Open short, slots 35-38", "value": f["short_mwh"], "unit": "MWh", "source": src("balance_position_30min")},
                   {"label": "Imbalance cost if left (p50)", "value": f["do_nothing_p50_jpy"] / 1e6, "unit": "M JPY", "source": src("imbalance_30min")},
                   {"label": "Minutes to the next gate closure", "value": f["clock"]["minutes_left"], "unit": "min", "source": ["desk clock"]}],
        "risk": [{"label": "Margin at risk at +40% spot", "value": f["mar_jpy"] / 1e6, "unit": "M JPY", "source": src("customer_forecast_daily", "hedge_book")},
                 {"label": "Price-exposed volume hedged", "value": f["hedge_cover_pct"], "unit": "%", "source": src("hedge_book")},
                 {"label": "Deviation cost this month", "value": f["dev_total_cost_jpy"] / 1e3, "unit": "k JPY", "source": src("customer_load_30min")}],
        "account": [{"label": "Prospect load in the pipeline", "value": pros["mwh"] / 1000, "unit": "GWh/yr", "source": src("prospects")},
                    {"label": f"{o['name']}, hourly matched", "value": o["contracted_hourly_matched_pct"], "unit": "%", "source": src("cfe_allocation_hourly")},
                    {"label": "Certificate ledger findings, August", "value": f["ledger"]["findings"], "unit": "", "source": src("nfc_ledger")}],
        "vpp": [{"label": "Power you can count on at 17:00", "value": f["vpp_dispatchable_mw"], "unit": "MW", "source": src("vpp_telemetry_30min")},
                {"label": "Capacity sold to the grid operator", "value": f["dkw_committed_mw"], "unit": "MW", "source": src("ancillary_commitments")},
                {"label": "Pools that cannot be trusted", "value": len(f["untrusted"]), "unit": "", "source": src("vpp_telemetry_30min")}],
    }


@router.get("/personas")
def personas():
    from server.app import SCENARIOS

    sc = {s["id"]: s for s in SCENARIOS}
    m = _persona_metrics()
    out = []
    for p in catalog.PERSONAS:
        out.append({**p, "answerable_for": m[p["id"]], "agents": [a["name"] for a in catalog.AGENTS if p["id"] in a["personas"]],
                    "suggested": [sc[s] for s in p["scenarios"] if s in sc]})
    return {"personas": out}


# ------------------------------------------------------------------------------------ what a proposal could not settle
def unsettled(a: dict) -> list[str]:
    """Plain statements of what a pending action could not settle, grounded in its own details and the audit."""
    d = a.get("details", {}) or {}
    out: list[str] = []
    k = a.get("kind")
    if k == "intraday_orders":
        orders = d.get("orders", [])
        if orders:
            out.append(f"Book depth and asks can move before each gate closes; the quantities rest on the {NOW[11:]} snapshot of the "
                       f"JEPX intraday book ({len(orders)} slots).")
            p90 = [o for o in orders if o.get("imbalance_p50_jpy_kwh") is not None]
            if p90:
                out.append("The limit prices sit below the p50 imbalance forecast; the p90 forecast reaches the 200 JPY/kWh cap, so "
                           "an unfilled order leaves real exposure.")
    elif k == "vpp_dispatch":
        ex = d.get("excluded_clusters", [])
        if ex:
            out.append(f"Excluded {', '.join(ex)}: its telemetry cannot be trusted, so its true state of charge is unknown.")
        fs = mk.fleet_state(d.get("date", SCENARIO_DATE), SHORT[0])
        for c in fs["clusters"]:
            if c["health"] == "untrusted" and c["commitments"]:
                out.append(f"Grid commitment {', '.join(c['commitments'])} ({c['committed_dkw_kw']:,.0f} kW) sits on {c['cluster_id']} "
                           "and needs a trusted substitute before the block starts; this dispatch does not arrange that.")
            if c["health"] == "degraded" and any(x["cluster_id"] == c["cluster_id"] for x in d.get("schedule", [])):
                why = (c["reasons"][0] if c["reasons"] else "partial reporting").removeprefix("degraded: ")
                out.append(f"{c['cluster_id']} is degraded ({why}); it is "
                           "dispatched at its reported availability.")
        out.append("Customer response is assumed at each pool's stated response time; actual delivery is only known after metering.")
    elif k == "tariff_adjustment":
        out.append("Needs the customer's written agreement; the effect is estimated from month-to-date metering, not from their "
                   "future load.")
    elif k == "ppa_offer":
        out.append("The price rests on planning assumptions: resource costs, 4-hour storage cost and an 18.0 JPY/kWh residual energy "
                   "price for 2027.")
        if d.get("deal_committee_required"):
            out.append(f"Above 100 GWh a year ({d.get('annual_load_gwh')} GWh), so Deal Committee approval is also required.")
        for w in d.get("document_warnings", []) or []:
            out.append(f"The prospect's bill contained instructions aimed at the agent, which were ignored: \"{w[:110]}\"")
    aud = a.get("audit")
    if not aud:
        out.insert(0, "Not yet reviewed by risk_auditor in this session.")
    else:
        for c in aud.get("checks", []):
            if c.get("result") == "fail":
                out.insert(0, f"The auditor failed this on: {c['rule']} ({c.get('detail', '')}).")
    return out


@router.get("/story/limits")
def limits():
    return {"limits": agents()["limits"]}


def warm() -> None:
    """Warm the caches (the PPA design is an 8,760-hour LP) so the first page load is quick."""
    try:
        figures()
        _persona_metrics()
    except Exception:  # never block startup on a warm-up
        pass

