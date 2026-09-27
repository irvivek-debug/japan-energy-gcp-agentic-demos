"""Read-only endpoints for UI v2 (landing, the case for change, workspace).

Every figure the v2 pages show is computed here from the same tools and tables the agents use, or read from
the cited research file (factory_copilot/research_facts.json, curated from docs/research/MARKET_FACTS.md) and
from the evaluation results in eval/results/. Nothing is hand-typed in the HTML or JS.
"""
from __future__ import annotations

import functools
import json
import os
from statistics import mean, median

from fastapi import APIRouter

from factory_copilot.core import bess as bess_core
from factory_copilot.core.clock import DEMO_DATE, DEMO_NOW, slot_start
from factory_copilot.datastore import STORE
from factory_copilot.personas import PERSONAS
from factory_copilot.tools import bess as T_bess
from factory_copilot.tools import common as C
from factory_copilot.tools import gainshare as T_gain
from factory_copilot.tools import health as T_health
from factory_copilot.tools import market as T_market

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "eval", "results")
router = APIRouter(prefix="/api")


def _load_json(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


@functools.lru_cache(maxsize=1)
def research() -> dict:
    return _load_json(os.path.join(ROOT, "factory_copilot", "research_facts.json"))


def rf(key: str) -> dict:
    return research()["facts"][key]


def fmt(v, dp=0, unit=""):
    if v is None:
        return "NOT IN THE DATA"
    s = f"{v:,.{dp}f}"
    return f"{s} {unit}".strip()


# ------------------------------------------------------------------------------------------------
@router.get("/meta")
@functools.lru_cache(maxsize=1)
def meta():
    schema = json.load(open(os.path.join(ROOT, "factory_copilot", "schema.json")))
    tables = []
    for name in schema["tables"]:
        n = STORE.query(f"SELECT COUNT(*) AS n FROM {{t:{name}}}")[0]["n"]
        tables.append({"name": name, "label": STORE.source_label(name), "rows": int(n)})
    tel = STORE.query("SELECT MIN(ts) AS a, MAX(ts) AS b FROM {t:telemetry_5min}")[0]
    site = STORE.query("SELECT MIN(date) AS a, MAX(date) AS b FROM {t:site_load_30min}")[0]
    jp = STORE.query("SELECT MIN(date) AS a, MAX(date) AS b FROM {t:jepx_prices_30min}")[0]
    return {"demo_now": DEMO_NOW, "seed": schema.get("seed"), "dataset": STORE.dataset, "backend": STORE.backend,
            "windows": {"telemetry": [tel["a"], tel["b"]], "site_history": [site["a"], site["b"]], "jepx": [jp["a"], jp["b"]]},
            "tables": tables, "generator": "data/generate.py", "research": research()["source_document"]}


@router.get("/research")
def research_facts():
    return research()


# ------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def _bess_kpis():
    c = T_bess.compare_bess_policies(DEMO_DATE)
    return c["policies"]["rule_based_v1"], c["policies"]["forecast_aware_v2"], c


@functools.lru_cache(maxsize=1)
def _anoms():
    return T_health.detect_energy_anomalies("2026-08-13", DEMO_DATE)


@router.get("/gap")
@functools.lru_cache(maxsize=1)
def gap():
    ev = [e for e in C.dr_events("") if e["status"] == "settled"]
    perf = {e["event_id"]: 100 * e["delivered_kw"] / e["requested_kw"] for e in ev}
    worst = min(ev, key=lambda e: perf[e["event_id"]])
    best = max(ev, key=lambda e: perf[e["event_id"]])
    t = C.tariff()
    contract = t["contracted_demand_kw"]
    pk = C.billing_peak_check(DEMO_DATE[:7], DEMO_DATE)
    v1, v2, _ = _bess_kpis()
    an = {a["type"]: a for a in _anoms()["anomalies"]}
    ac = an.get("compressor_specific_power_drift")
    pv = T_market.get_pv_forecast(DEMO_DATE)
    rows = [
        {"key": "dr_delivery", "quantity": "DR delivered vs committed (settled events)",
         "ordinary": f"{fmt(perf[worst['event_id']], 0)} % on {worst['date']}", "best": f"{fmt(perf[best['event_id']], 0)} % on {best['date']}",
         "gap": f"{fmt(worst['requested_kw'] - worst['delivered_kw'])} kW short, {fmt(worst['penalty_jpy'])} JPY penalty",
         "research": f"Capacity-market DR must deliver for {rf('dr_call_duration_h')['value']} h when called; VPP/DR cleared at {rf('vppdr_tertiary2_fy2024')['value']}-{rf('vppdr_tertiary2_fy2025h1')['value']} JPY/ΔkW·h in 三次②.",
         "cite": f"{rf('dr_call_duration_h')['cite']} · {rf('vppdr_tertiary2_fy2024')['cite']}", "source": C.src("dr_events", "site_load_30min")},
        {"key": "billing_peak", "quantity": "Monthly billing peak vs contracted demand",
         "ordinary": f"{fmt(pk['month_billing_peak_kw'])} kW ({fmt(100 * pk['month_billing_peak_kw'] / contract, 1)} % of {fmt(contract)} kW)",
         "best": f"{fmt(pk['highest_peak_on_non_event_days_kw'])} kW on days without a DR event",
         "gap": f"{fmt(pk['extra_billing_demand_kw'])} kW, {fmt(pk['extra_demand_charge_jpy'])} JPY this month",
         "research": f"Market-linked plan basic charge {fmt(rf('tepco_market_linked_basic')['value'])} JPY/kW-month; EHV wheeling basic {rf('wheeling_ehv_basic')['value']} JPY/kW-month.",
         "cite": f"{rf('tepco_market_linked_basic')['cite']} · {rf('wheeling_ehv_basic')['cite']}", "source": C.src("site_load_30min", "tariff_contract")},
        {"key": "compressed_air", "quantity": "Compressed-air specific power, AC-04 vs peers",
         "ordinary": f"{fmt(ac['evidence']['specific_power_kw_per_nm3min'], 2)} kW per Nm3/min" if ac else "NOT IN THE DATA",
         "best": f"{fmt(ac['evidence']['peer_median'], 2)} kW per Nm3/min (peer median)" if ac else "NOT IN THE DATA",
         "gap": f"+{fmt(ac['evidence']['recent_excess_vs_peers_pct'], 1)} %, about {fmt(ac['impact']['annual_cost_jpy'] / 1e6, 1)} M JPY a year" if ac else "NOT IN THE DATA",
         "research": f"NO VERIFIED BENCHMARK HELD for specific power. Mitsubishi Electric's own FEMS case reports about {rf('melco_fems_saving')['value']} % saving from PLC-based control.",
         "cite": rf("melco_fems_saving")["cite"], "source": C.src("compressor_perf")},
        {"key": "pv_forecast", "quantity": "PV forecast: p50 error and p10-p90 calibration (14 days)",
         "ordinary": f"p50 error {fmt(pv['calibration_14d']['p50_mae_kw'], 1)} kW; {fmt(pv['calibration_14d']['p10_p90_coverage_pct'], 1)} % of slots inside p10-p90",
         "best": "80 % inside p10-p90 (a calibrated band)",
         "gap": f"Today at {pv['deepest_gap']['time']}: p10 {fmt(pv['deepest_gap']['p10_kw'])} kW vs p50 {fmt(pv['deepest_gap']['p50_kw'])} kW",
         "research": f"WeatherNext 3: new run every hour, 5 km surface resolution, {rf('weathernext3_members')['value']} members, solar radiation and cloud cover outputs.",
         "cite": rf("weathernext3_members")["cite"], "source": C.src("pv_forecast_30min", "pv_actual_5min")},
        {"key": "bess_soc", "quantity": "Battery at the DR start: current rules vs forecast-aware policy",
         "ordinary": f"{fmt(v1['soc_at_dr_start_pct'], 1)} % SOC, {fmt(v1['dr_firm_kw'])} kW firm in the DR window",
         "best": f"{fmt(v2['soc_at_dr_start_pct'], 1)} % SOC, {fmt(v2['dr_firm_kw'])} kW firm",
         "gap": f"{fmt(v2['dr_firm_kw'] - v1['dr_firm_kw'])} kW of firm DR from the same battery",
         "research": f"Battery AC round trip {rf('battery_rte')['value']} %; Tokyo daily 2-hour spread {rf('tokyo_spread_2h_fy2026')['value']} JPY/kWh in FY2026.",
         "cite": f"{rf('battery_rte')['cite']} · {rf('tokyo_spread_2h_fy2026')['cite']}", "source": C.src("bess_state_5min", "site_plan_30min")},
        {"key": "deviation", "quantity": "30-minute deviation band (±7.5 %), p10 PV case before the event",
         "ordinary": f"{v1['pre_event_slots_outside_band_p10pv']} slots outside, {fmt(v1['pre_event_imbalance_exposure_jpy_p10pv'])} JPY at risk",
         "best": f"{v2['pre_event_slots_outside_band_p10pv']} slots outside, {fmt(v2['pre_event_imbalance_exposure_jpy_p10pv'])} JPY at risk",
         "gap": f"{fmt(v1['pre_event_imbalance_exposure_jpy_p10pv'] - v2['pre_event_imbalance_exposure_jpy_p10pv'])} JPY today; small, because the cloud band lands before the evening spike",
         "research": f"Scarcity imbalance price reaches {rf('imbalance_d_8pct')['value']} JPY/kWh at an 8 % reserve margin, capped at {rf('imbalance_cap_now')['value']} (rising to {rf('imbalance_cap_oct')['value']} on 2026-10-01).",
         "cite": rf("imbalance_cap_now")["cite"], "source": C.src("site_plan_30min", "jepx_prices_30min")},
    ]
    jul = C.billing_peak_check("2026-07", "2026-07-31")
    idle_both = bool(jul and jul["around_dr_event"] and pk and pk["around_dr_event"])
    note = {"is": (f"The gap is timing and proof: the same equipment delivered {perf[best['event_id']]:.0f} % of one DR request and {perf[worst['event_id']]:.0f} % of another"
                   + (", and the battery sat idle at both of this summer's billing peaks." if idle_both else ".")),
            "is_not": "It is not a shortage of equipment or a need to stop production lines; every figure above comes from loads and a battery the plant already runs."}
    return {"rows": rows, "note": note, "source": sorted({s for r in rows for s in r["source"]})}


# ------------------------------------------------------------------------------------------------
@router.get("/strip")
@functools.lru_cache(maxsize=1)
def strip():
    """Hourly series over the telemetry window for the landing evidence strip (value, unit, status per point)."""
    def hourly(sql, **p):
        return {(r["date"], int(r["hour"])): float(r["v"]) for r in STORE.query(sql, **p) if r["v"] is not None}

    imp = hourly("SELECT date, hour, AVG(kw) AS v FROM {t:telemetry_5min} WHERE asset_class = 'receiving_point' GROUP BY date, hour")
    comp = hourly("SELECT date, hour, SUM(kw) / COUNT(DISTINCT ts) AS v FROM {t:telemetry_5min} WHERE asset_class = 'compressor' GROUP BY date, hour")
    m27 = hourly("SELECT date, hour, AVG(kw) AS v FROM {t:telemetry_5min} WHERE meter_id = 'M-27' GROUP BY date, hour")
    pv = hourly("SELECT date, hour, AVG(pv_kw) AS v FROM {t:pv_actual_5min} GROUP BY date, hour")
    soc = hourly("SELECT date, hour, AVG(soc_pct) AS v FROM {t:bess_state_5min} WHERE ts < @n GROUP BY date, hour", n=DEMO_NOW)
    spot = hourly("SELECT date, hour, AVG(spot_jpy_kwh) AS v FROM {t:jepx_prices_30min} GROUP BY date, hour")
    keys = sorted(imp)
    ts = [f"{d}T{h:02d}:00" for d, h in keys]
    daily_ac04 = {r["date"]: r for r in STORE.query(
        "SELECT date, compressor_id, specific_power_kw_per_nm3min AS sp FROM {t:compressor_perf} WHERE date >= @a", a=keys[0][0])}
    sp_rows = STORE.query("SELECT date, compressor_id, specific_power_kw_per_nm3min AS sp FROM {t:compressor_perf} WHERE date >= @a AND specific_power_kw_per_nm3min > 0", a=keys[0][0])
    by_day: dict[str, dict[str, float]] = {}
    for r in sp_rows:
        by_day.setdefault(r["date"], {})[r["compressor_id"]] = float(r["sp"])
    ac04_exc = {d: 100 * (v["AC-04"] / median(x for k, x in v.items() if k != "AC-04") - 1) for d, v in by_day.items() if "AC-04" in v and len(v) > 1}
    flat = C.flat_meter_runs(f"{keys[0][0]}T00:00", DEMO_NOW)
    m27_since = next((f["first_ts"] for f in flat if f["meter_id"] == "M-27"), None)
    contract = C.tariff()["contracted_demand_kw"]
    limit = bess_core.PolicyParams().v1_demand_limit_kw

    def series(key, label, unit, vals, dp, stat_fn, source, note):
        v = [round(vals.get(k), dp) if vals.get(k) is not None else None for k in keys]
        st = [stat_fn(k, x) for k, x in zip(keys, v)]
        return {"key": key, "label": label, "unit": unit, "dp": dp, "values": v, "status": [s[0] for s in st], "badge": [s[1] for s in st],
                "source": source, "note": note}

    out = [
        series("import", "Receiving point, 66 kV", "kW", imp, 0,
               lambda k, x: ("crit", "OVER CONTRACT") if x and x > contract else ("warn", "ABOVE LIMIT") if x and x > limit else ("ok", "WITHIN LIMIT"),
               C.src("telemetry_5min"), f"Contract {contract:,.0f} kW; battery demand limit {limit:,.0f} kW"),
        series("compressed_air", "Compressed air, 6 units", "kW", comp, 0,
               lambda k, x: (("warn", f"AC-04 +{ac04_exc[k[0]]:.0f} %") if ac04_exc.get(k[0], 0) >= 12 else ("ok", f"AC-04 +{ac04_exc.get(k[0], 0):.0f} %")),
               C.src("telemetry_5min", "compressor_perf"), "Badge: AC-04 specific power vs peer median that day"),
        series("m27", "Meter M-27, SiC line 2", "kW", m27, 1,
               lambda k, x: ("crit", "FROZEN") if m27_since and f"{k[0]}T{k[1]:02d}:59" >= m27_since and f"{k[0]}T{k[1]:02d}:00" >= m27_since[:14] + "00" else ("ok", "LIVE"),
               C.src("telemetry_5min", "meters"), f"Identical reading since {m27_since.replace('T', ' ') if m27_since else 'NOT IN THE DATA'}"),
        series("pv", "Rooftop and carport PV", "kW", pv, 0, lambda k, x: ("ok", "MEASURED") if x and x > 1 else ("idle", "NIGHT"),
               C.src("pv_actual_5min"), "3,000 kWp across three arrays"),
        series("bess_soc", "Battery state of charge", "%", soc, 1,
               lambda k, x: ("warn", "LOW") if x is not None and x < 20 else ("ok", "AVAILABLE"), C.src("bess_state_5min"), "4 MW / 8 MWh, limits 10-95 %"),
        series("jepx", "JEPX Tokyo spot", "JPY/kWh", spot, 2,
               lambda k, x: ("warn", "SPIKE") if x is not None and x >= 35 else ("ok", "NORMAL"), C.src("jepx_prices_30min"), "Hourly mean of the two 30-minute slots"),
    ]
    return {"times": ts, "window": [ts[0], ts[-1]], "series": out}


# ------------------------------------------------------------------------------------------------
@router.get("/prize")
@functools.lru_cache(maxsize=1)
def prize():
    t = C.tariff()
    ev = [e for e in C.dr_events("") if e["status"] == "settled"]
    all_ev = C.dr_events("")
    import datetime as dt
    first = dt.date.fromisoformat(min(e["date"] for e in all_ev))
    days_elapsed = (dt.date.fromisoformat(DEMO_DATE) - dt.date(first.year, 7, 1)).days + 1
    season_days = (dt.date(first.year, 9, 30) - dt.date(first.year, 7, 1)).days + 1
    n_so_far = len(all_ev)
    n_season = n_so_far * season_days / days_elapsed
    avg_net = mean(e["net_settlement_jpy"] for e in ev)
    max_pay = max(e["payment_jpy"] for e in ev)
    penalty_rate = sum(1 for e in ev if e["penalty_jpy"] > 0) / len(ev)
    max_pen = max(e["penalty_jpy"] for e in ev)
    avail = 3 * t["dr_availability_jpy_kw_month"] * t["dr_contracted_capacity_kw"]
    v1, v2, cmp_ = _bess_kpis()
    dr_diff = cmp_["value_at_stake"]["dr_energy_payment_difference_jpy"]
    en_diff = -cmp_["value_at_stake"]["bess_energy_cost_difference_jpy"]
    jul = C.billing_peak_check("2026-07", "2026-07-31")
    aug = C.billing_peak_check(DEMO_DATE[:7], DEMO_DATE)
    incidents = (jul["extra_demand_charge_jpy"] if jul else 0) + (aug["extra_demand_charge_jpy"] if aug else 0)
    an = {a["type"]: a for a in _anoms()["anomalies"]}
    ac_cost = an["compressor_specific_power_drift"]["impact"]["annual_cost_jpy"] if "compressor_specific_power_drift" in an else None
    led = T_gain.get_savings_ledger("2026-01", "2026-07")["months"]
    imb = [m["by_category"].get("imbalance_avoided", 0) for m in led]
    eff = [m["by_category"].get("efficiency_savings", 0) for m in led]
    vendor = [m["vendor_gain_share_jpy"] + m["baas_fee_jpy"] for m in led]
    client = [m["client_net_jpy"] for m in led]
    M = 1e6

    def line(mech, lo, hi, basis, unit="M JPY per year"):
        return {"mechanism": mech, "low": None if lo is None else round(lo / M, 2), "high": None if hi is None else round(hi / M, 2), "unit": unit, "basis": basis}

    branches = [
        {"code": "APQC 4.0", "hue": "b1", "name": "Commit the right flexibility", "lines": [
            line("DR availability and energy payments for the summer season", avail + n_so_far * avg_net, avail + n_season * max_pay,
                 f"Availability {t['dr_availability_jpy_kw_month']:,.0f} JPY/kW-month x {t['dr_contracted_capacity_kw']:,.0f} kW x 3 months, plus {n_so_far} to {n_season:.1f} events (the dispatch rate so far) at the settled average or the best payment"),
            line("Penalties avoided by committing only edge-verified flexibility", 0, penalty_rate * n_season * max_pen,
                 f"{sum(1 for e in ev if e['penalty_jpy'] > 0)} of {len(ev)} settled events under-delivered; up to {n_season:.1f} events at the observed penalty"),
        ]},
        {"code": "APQC 10.0", "hue": "b2", "name": "Dispatch storage for money and firmness", "lines": [
            line("Billing-peak incidents avoided around DR events", incidents, incidents * 1.5,
                 "July and August incidents as measured; the high end assumes September repeats the average"),
            line("Battery firm DR in the window (forecast-aware vs current policy)", n_so_far * dr_diff, n_season * dr_diff,
                 f"{dr_diff:,.0f} JPY per event (firm kW difference x 2.5 h x DR energy rate) x {n_so_far} to {n_season:.1f} events"),
            line("Battery energy value on event days", n_so_far * en_diff, n_season * en_diff,
                 f"{en_diff:,.0f} JPY per event day (current vs forecast-aware battery energy cost) x {n_so_far} to {n_season:.1f} event days"),
        ]},
        {"code": "APQC 10.3", "hue": "b3", "name": "Find and fix waste", "lines": [
            line("AC-04 air leak repaired", None if ac_cost is None else 0.7 * ac_cost, ac_cost,
                 "Annual cost of the specific-power excess at 8,000 run hours; a repair recovers 70-100 % of it"),
            line("Efficiency measures already verified (analytics subscription)", 12 * min(eff), 12 * max(eff), "Monthly ledger efficiency line, lowest and highest month x 12"),
        ]},
        {"code": "APQC 9.0", "hue": "b4", "name": "Prove and share value (gain-share economics)", "lines": [
            line("Equipment vendor recurring revenue (gain share + BESS-as-a-Service fee)", 12 * min(vendor), 12 * max(vendor),
                 f"{t['gain_share_pct']:.0f} % of eligible savings plus {t['baas_fee_jpy_month']:,.0f} JPY/month, lowest and highest month x 12"),
            line("Client net benefit after the gain share and the fee", 12 * min(client), 12 * max(client), "Monthly ledger client net, lowest and highest month x 12"),
        ]},
        {"code": "APQC 11.0", "hue": "b5", "name": "Keep it safe and governed", "lines": [
            line("Imbalance cost avoided by keeping inside the deviation band", 12 * min(imb), 12 * max(imb), "Monthly ledger imbalance line, lowest and highest month x 12"),
        ]},
        {"code": "APQC 8.0", "hue": "b6", "name": "Run on open, portable infrastructure", "lines": [
            line("ICONICS and Serendie data stay portable across the AWS or Azure estate already in place", None, None,
                 "No figure is held for this; it is a condition of adoption, not a saving"),
        ]},
    ]
    return {"branches": branches, "note": "Ranges only. The gain-share lines split value between the vendor and the client; they are not added to the other lines.",
            "source": C.src("dr_events", "savings_ledger", "tariff_contract", "compressor_perf", "site_load_30min", "bess_state_5min")}


# ------------------------------------------------------------------------------------------------
@router.get("/value")
@functools.lru_cache(maxsize=1)
def value():
    ev = [e for e in C.dr_events("") if e["status"] == "settled"]
    perf = [100 * e["delivered_kw"] / e["requested_kw"] for e in ev]
    v1, v2, _ = _bess_kpis()
    t = C.tariff()
    pk = C.billing_peak_check(DEMO_DATE[:7], DEMO_DATE)
    an = {a["type"]: a for a in _anoms()["anomalies"]}
    ac = an.get("compressor_specific_power_drift")
    pv = T_market.get_pv_forecast(DEMO_DATE)
    jp = T_market.get_jepx_prices(DEMO_DATE)
    sw = jp["spike_windows"][0] if jp["spike_windows"] else None
    contract = t["contracted_demand_kw"]
    return {"metrics": [
        {"key": "dr_delivery", "metric": "DR delivered vs committed", "unit": "%", "site_low": min(perf), "site_high": max(perf), "now": None, "target": 100,
         "direction": "higher", "band": None, "band_text": "NO VERIFIED BENCHMARK HELD", "cite": "", "agent": "factory_interlock_agent, gain_share_agent",
         "reading": f"{len(ev)} settled events; the copilot commits only edge-verified kW"},
        {"key": "bess_firm", "metric": "Battery firm kW in the DR window", "unit": "kW", "site_low": v1["dr_firm_kw"], "site_high": v2["dr_firm_kw"], "now": v2["dr_firm_kw"],
         "target": None, "direction": "higher", "band": None, "band_text": f"Round trip {rf('battery_rte')['value']} %", "cite": rf("battery_rte")["cite"],
         "agent": "bess_strategy_agent", "reading": "Low end: current rules; high end: forecast-aware policy"},
        {"key": "peak_ratio", "metric": "Billing peak vs contracted demand", "unit": "%", "site_low": 100 * pk["highest_peak_on_non_event_days_kw"] / contract,
         "site_high": 100 * pk["month_billing_peak_kw"] / contract, "now": None, "target": 100 * pk["highest_peak_on_non_event_days_kw"] / contract, "direction": "lower",
         "band": None, "band_text": f"Basic charge {rf('tepco_market_linked_basic')['value']:,.0f} JPY/kW-month", "cite": rf("tepco_market_linked_basic")["cite"],
         "agent": "bess_strategy_agent, asset_health_agent", "reading": "Low end: days without a DR event; high end: this month's billing peak"},
        {"key": "spike_price", "metric": "Tokyo spot in today's spike window", "unit": "JPY/kWh", "site_low": sw["avg_spot_jpy_kwh"] if sw else None,
         "site_high": sw["max_spot_jpy_kwh"] if sw else None, "now": jp["spot_now"], "target": None, "direction": "lower",
         "band": [rf("tokyo_spot_fy2026_p5")["value"], rf("tokyo_spot_fy2026_p95")["value"]], "band_text": "Tokyo FY2026 p5-p95", "cite": rf("tokyo_spot_fy2026_p95")["cite"],
         "agent": "market_intelligence_agent", "reading": "Marker: price now; bar: spike average to peak"},
        {"key": "air_sp", "metric": "Compressed-air specific power, AC-04", "unit": "kW per Nm3/min",
         "site_low": ac["evidence"]["peer_median"] if ac else None, "site_high": ac["evidence"]["specific_power_kw_per_nm3min"] if ac else None, "now": None,
         "target": ac["evidence"]["peer_median"] if ac else None, "direction": "lower", "band": None, "band_text": "NO VERIFIED BENCHMARK HELD", "cite": "",
         "agent": "asset_health_agent", "reading": "Low end: peer median; high end: AC-04"},
        {"key": "pv_cal", "metric": "PV ensemble calibration (inside p10-p90)", "unit": "%", "site_low": pv["calibration_14d"]["p10_p90_coverage_pct"], "site_high": 80,
         "now": pv["calibration_14d"]["p10_p90_coverage_pct"], "target": 80, "direction": "higher", "band": None,
         "band_text": f"WeatherNext 3, {rf('weathernext3_members')['value']} members, hourly", "cite": rf("weathernext3_members")["cite"],
         "agent": "market_intelligence_agent", "reading": "Last 14 days; a calibrated p10-p90 band holds 80 %"},
        {"key": "imbalance", "metric": "Imbalance price estimate in the spike", "unit": "JPY/kWh", "site_low": None, "site_high": sw["max_imbalance_jpy_kwh"] if sw else None,
         "now": sw["max_imbalance_jpy_kwh"] if sw else None, "target": None, "direction": "lower", "band": [0, rf("imbalance_cap_now")["value"]],
         "band_text": f"Scarcity curve to the {rf('imbalance_cap_now')['value']} cap ({rf('imbalance_cap_oct')['value']} from 2026-10-01)", "cite": rf("imbalance_cap_now")["cite"],
         "agent": "market_intelligence_agent", "reading": "At the lowest wide-area reserve margin of the evening"},
    ], "source": C.src("dr_events", "bess_state_5min", "site_load_30min", "compressor_perf", "pv_forecast_30min", "jepx_prices_30min")}


# ------------------------------------------------------------------------------------------------
@router.get("/proof")
def proof():
    adk = _load_json(os.path.join(RES, "adk_summary.json")) or {}
    gr = _load_json(os.path.join(RES, "grounding_results.json")) or {}
    sf = _load_json(os.path.join(RES, "safety_results.json")) or {}
    pt = _load_json(os.path.join(RES, "pytest_last.json"))
    cases = adk.get("cases", {})
    runs = []
    for d in ("run1_baseline", "run2_partial_stopped"):
        s = _load_json(os.path.join(RES, d, "adk_summary.json"))
        if s:
            c = s["cases"]
            runs.append({"run": d, "cases": len(c), "pass_first": sum(v["first_attempt"] == "PASSED" for v in c.values()),
                         "pass_after_retry": sum(v["final"] != "FAILED" for v in c.values()),
                         "failed_first": [k for k, v in c.items() if v["first_attempt"] != "PASSED"]})
    runs.append({"run": "final", "cases": len(cases), "pass_first": sum(v["first_attempt"] == "PASSED" for v in cases.values()),
                 "pass_after_retry": sum(v["final"] != "FAILED" for v in cases.values()), "failed_first": [k for k, v in cases.items() if v["first_attempt"] != "PASSED"]})
    lat = [v.get("info_first", {}).get("invocation_duration_v1") for v in cases.values() if v.get("info_first", {}).get("invocation_duration_v1")]
    # worked grounding example: PV p10 / p50 / p90 at 15:00, truth recomputed now by SQL
    sql = "SELECT p10_kw, p50_kw, p90_kw FROM {t:pv_forecast_30min} WHERE date = @d AND issued_at = @i AND slot = 31"
    truth = STORE.query(sql, d=DEMO_DATE, i=f"{DEMO_DATE}T13:00")[0]
    probe = next((p for p in gr.get("probes", []) if p["id"] == "G07_S7_pv"), None)
    reply = probe["first"]["reply"] if probe else ""
    excerpt = ""
    key = str(int(float(truth["p10_kw"])))        # integer part of the p10 truth, as the agent prints it
    for line in reply.splitlines():
        if key in line.replace(",", "") and ("p10" in line.lower()):
            excerpt = line.strip().lstrip("*- ").strip()
            break
    return {
        "adk": {"total": len(cases), "pass_first": sum(v["first_attempt"] == "PASSED" for v in cases.values()),
                "pass_after_retry": sum(v["final"] != "FAILED" for v in cases.values()),
                "sets": adk.get("sets", {}), "latency_s": [min(lat), max(lat)] if lat else None,
                "cases": [{"id": k, "set": v["set"], "first": v["first_attempt"], "metrics": {m: x["score"] for m, x in v["metrics_first"].items()},
                           "latency_s": v.get("info_first", {}).get("invocation_duration_v1")} for k, v in cases.items()],
                "criteria": ["tool trajectory (specialist and key tool)", "rubric-based response quality", "hallucinations (sentence support)"]},
        "grounding": {"summary": gr.get("summary"), "probes": [{"id": p["id"], "label": p["label"], "checks": p.get("first", {}).get("checks", [])} for p in gr.get("probes", [])]},
        "safety": {"summary": sf.get("summary"), "static": sf.get("static"),
                   "probes": [{"id": p["id"], "category": p["category"], "passed": p["passed"], "prompt": p["prompt"]} for p in sf.get("probes", [])]},
        "pytest": pt,
        "runs": runs,
        "worked_example": {"question": probe["prompt"] if probe else None, "sql": sql.replace("{t:pv_forecast_30min}", STORE.source_label("pv_forecast_30min")),
                           "params": {"d": DEMO_DATE, "i": f"{DEMO_DATE}T13:00"}, "truth": {k: round(float(v), 1) for k, v in truth.items()},
                           "reply_excerpt": excerpt, "label": probe["label"] if probe else "NOT IN THE DATA",
                           "checks": probe["first"]["checks"] if probe else []},
        "source": ["eval/results/adk_summary.json", "eval/results/grounding_results.json", "eval/results/safety_results.json", "eval/results/pytest_last.json"],
    }


@router.get("/personas")
def personas():
    return {"personas": PERSONAS}


@router.get("/compressor-trend")
@functools.lru_cache(maxsize=1)
def compressor_trend():
    rows = STORE.query("SELECT date, compressor_id, specific_power_kw_per_nm3min AS sp FROM {t:compressor_perf} WHERE specific_power_kw_per_nm3min > 0 ORDER BY date")
    by_day: dict[str, dict[str, float]] = {}
    for r in rows:
        by_day.setdefault(r["date"], {})[r["compressor_id"]] = float(r["sp"])
    days = sorted(by_day)
    return {"dates": days, "ac04": [round(by_day[d].get("AC-04", 0), 3) for d in days],
            "peer_median": [round(median(v for k, v in by_day[d].items() if k != "AC-04"), 3) for d in days], "source": C.src("compressor_perf")}


# ------------------------------------------------------------------------------------------------
def enrich_action(pa: dict) -> dict:
    """What the recommendation could not settle, the agent's reasoning and sources, for the sign-off sheet."""
    d = pa.get("details", {}) or {}
    un = []
    kind = pa.get("kind")
    if kind == "load_shed_plan":
        s0 = d.get("summary", {})
        if s0:
            un.append(f"Edge verdicts on {s0.get('actions_evaluated', 0)} actions: {s0.get('accepted', 0)} ACCEPT, {s0.get('limited', 0)} LIMIT, "
                      f"{s0.get('rejected', 0)} REJECT. The verdicts are from the moment of simulation; the edge checks every action again at dispatch.")
        for x in d.get("excluded_by_edge", []):
            un.append(f"The edge rejected {x['asset_id']} {x['action']} ({', '.join(x['rule_ids'])}); it is excluded. {x['reason']}")
        limited: dict[str, list[str]] = {}
        for x in d.get("actions", []):
            if x.get("verdict") == "LIMIT":
                limited.setdefault(x["reason"], []).append(x["asset_id"])
        for reason, ids in limited.items():
            un.append(f"{', '.join(ids)} {'is' if len(ids) == 1 else 'are'} limited by the edge: {reason}")
        s = d.get("summary", {})
        if s:
            un.append(f"Firm {s.get('firm_reduction_kw', 0):,.0f} kW is the lowest half hour of the window; measured delivery depends on the High 4 of 5 baseline, "
                      "whose same-day adjustment uses the forecast after 13:30.")
            un.append(f"Deferred loads come back after the window: about {s.get('rebound_kwh_after_window', 0):,.0f} kWh of rebound.")
    elif kind == "bess_schedule":
        k = d.get("kpis", {})
        un.append(f"In the p10 PV case {k.get('pre_event_slots_outside_band_p10pv', 0)} pre-event slots leave the 7.5 % band "
                  f"({k.get('pre_event_imbalance_exposure_jpy_p10pv', 0):,.0f} JPY at risk).")
        un.append(f"Reaching {k.get('soc_at_dr_start_pct', 0):.1f} % SOC by the DR start assumes the planned charging completes; the edge re-checks SOC and power at dispatch.")
    elif kind == "work_order":
        un.append("Cost figures in the rationale are estimates (run hours and average plant price); the cause is confirmed only by inspection.")
    if pa.get("audit"):
        un.append(f"Safety auditor verdict: {pa['audit']}.")
    return {**pa, "unverified": un, "reasoning": d.get("rationale") or pa.get("summary"), "sources": d.get("sources", []),
            "author": pa.get("proposed_by")}
