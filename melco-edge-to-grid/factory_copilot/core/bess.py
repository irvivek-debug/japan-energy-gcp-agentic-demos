"""BESS dispatch policies (deterministic). Positive power = discharge (reduces grid import).

Two policies are compared in the demo:
  * rule_based_v1      - the policy the BESS-as-a-Service unit runs today: night charge, midday top-up,
                         demand limiting above a fixed import threshold. It does not read the DR event,
                         the JEPX curve or the PV ensemble, and never updates the 30-minute nomination.
  * forecast_aware_v2  - hand-tuned forecast-aware policy. It
                           1. pre-charges toward a target SOC before the DR window, skipping PV-risk slots
                              (ensemble p10 far below p50), capping charge so import stays under the demand
                              ceiling even in the p10 PV case, and keeping locked slots (gate closure, 60 min
                              before delivery) inside the deviation band of the day-ahead nomination;
                           2. re-nominates open slots to its own p50 plan;
                           3. discharges a flat block across the DR window and the JEPX spike tail, keeping a
                              reserve SOC;
                           4. in the p10 PV case, the edge controller follows the nomination in real time by
                              discharging the PV shortfall beyond 80 % of the band (contingency);
                           5. recharges from 22:00.
                         AlphaEvolve search over this policy family is the path to an evolved version (see the
                         Energy Lab demo). Nothing in this module is labelled "evolved".
"""
from __future__ import annotations

from dataclasses import dataclass

POLICIES = ("rule_based_v1", "forecast_aware_v2")


@dataclass
class BessParams:
    power_kw: float = 4000.0
    energy_kwh: float = 8000.0
    soc_min_pct: float = 10.0
    soc_max_pct: float = 95.0
    eff_charge: float = 0.95
    eff_discharge: float = 0.95


@dataclass
class PolicyParams:
    # rule_based_v1
    v1_night_slots: tuple[int, int] = (3, 10)        # 01:00-05:00
    v1_night_kw: float = 900.0
    v1_night_soc_cap: float = 90.0
    v1_midday_slots: tuple[int, int] = (25, 30)      # 12:00-15:00
    v1_midday_kw: float = 600.0
    v1_midday_soc_cap: float = 80.0
    v1_demand_limit_kw: float = 13500.0
    # forecast_aware_v2
    v2_target_soc_pct: float = 95.0
    v2_reserve_soc_pct: float = 20.0
    v2_import_ceiling_kw: float = 14000.0
    v2_band_use: float = 0.8                          # use at most 80 % of the deviation band
    v2_night_recharge_from_slot: int = 45            # 22:00
    v2_night_recharge_kw: float = 1500.0


@dataclass
class DayInputs:
    """Per-slot inputs for the rest of the day (slots >= now)."""
    slots: list[int]
    import_p50: dict[int, float]          # forecast receiving-point import before BESS, PV at p50
    import_p10: dict[int, float]          # same with PV at ensemble p10 (the downside case)
    nominated: dict[int, float]           # day-ahead 30-min nomination (includes the v1 day-ahead BESS plan)
    spot: dict[int, float]
    imbalance: dict[int, float]
    dr_slots: list[int]
    spike_slots: list[int]
    risk_slots: list[int]
    locked_slots: list[int]               # gate closure: cannot be re-nominated
    band_pct: float = 7.5
    energy_adder_jpy_kwh: float = 0.0


def soc_step(soc: float, power_kw: float, p: BessParams) -> float:
    de = -power_kw * 0.5 / p.eff_discharge if power_kw >= 0 else -power_kw * 0.5 * p.eff_charge
    return soc + 100.0 * de / p.energy_kwh


def clip_power(soc: float, power_kw: float, p: BessParams) -> float:
    """Clip a requested power so the SOC stays within [soc_min, soc_max] over one 30-min slot."""
    power_kw = max(-p.power_kw, min(p.power_kw, power_kw))
    if power_kw > 0:
        max_kwh = max(0.0, (soc - p.soc_min_pct) / 100.0 * p.energy_kwh) * p.eff_discharge
        return min(power_kw, max_kwh / 0.5)
    if power_kw < 0:
        max_kwh = max(0.0, (p.soc_max_pct - soc) / 100.0 * p.energy_kwh) / p.eff_charge
        return -min(-power_kw, max_kwh / 0.5)
    return 0.0


def _band(d: DayInputs, s: int) -> float:
    return d.band_pct / 100.0 * d.nominated.get(s, 0.0)


def plan_v2(soc_start: float, d: DayInputs, p: BessParams, pp: PolicyParams) -> dict[int, float]:
    """Requested power per slot for forecast_aware_v2 in the p50 world (before SOC clipping)."""
    req = {s: 0.0 for s in d.slots}
    block = [s for s in sorted(set(d.dr_slots) | set(d.spike_slots)) if s in req]
    first = block[0] if block else None
    if first is not None:
        charge_slots = [s for s in d.slots if s < first and s not in d.risk_slots]
        caps = {}
        for s in charge_slots:
            cap = min(p.power_kw, max(0.0, pp.v2_import_ceiling_kw - d.import_p10.get(s, 0.0)))
            if s in d.locked_slots:
                room = pp.v2_band_use * _band(d, s) - (d.import_p50.get(s, 0.0) - d.nominated.get(s, 0.0))
                cap = min(cap, max(0.0, room))
            caps[s] = cap
        need_grid = max(0.0, (pp.v2_target_soc_pct - soc_start) / 100.0 * p.energy_kwh) / p.eff_charge
        todo = [s for s in charge_slots if caps[s] > 1e-6]
        while need_grid > 1e-6 and todo:  # water-fill: equal share, capped per slot
            share = need_grid / (0.5 * len(todo))
            nxt = []
            for s in todo:
                take = min(share, caps[s] + req[s])  # req is negative while charging
                req[s] -= take
                need_grid -= take * 0.5
                if caps[s] + req[s] > 1e-6:
                    nxt.append(s)
            if len(nxt) == len(todo):
                break
            todo = nxt
        req = {s: -float(int(-v // 10) * 10) if v < 0 else v for s, v in req.items()}   # round charge DOWN so caps hold
        soc = soc_start
        for s in d.slots:
            if s >= first:
                break
            soc = soc_step(soc, clip_power(soc, req[s], p), p)
        usable_kwh = max(0.0, (soc - pp.v2_reserve_soc_pct) / 100.0 * p.energy_kwh) * p.eff_discharge
        flat = int(min(p.power_kw, usable_kwh / (0.5 * len(block))) // 50) * 50.0
        for s in block:
            req[s] = flat
    for s in d.slots:
        if s >= pp.v2_night_recharge_from_slot and (first is None or s > block[-1]):
            req[s] = -pp.v2_night_recharge_kw
    return req


def effective_nomination(policy: str, d: DayInputs, planned_power: dict[int, float]) -> dict[int, float]:
    """v1 keeps the day-ahead nomination; v2 re-nominates open slots to its own p50 plan."""
    if policy == "rule_based_v1":
        return dict(d.nominated)
    out = {}
    for s in d.slots:
        out[s] = d.nominated.get(s, 0.0) if s in d.locked_slots else d.import_p50.get(s, 0.0) - planned_power.get(s, 0.0)
    return out


def simulate(policy: str, soc_start: float, d: DayInputs, scenario: str = "p50",
             p: BessParams | None = None, pp: PolicyParams | None = None) -> list[dict]:
    """Simulate a policy slot by slot for scenario 'p50' or 'p10' (PV at ensemble p10)."""
    p = p or BessParams()
    pp = pp or PolicyParams()
    if policy not in POLICIES:
        raise ValueError(f"unknown policy '{policy}'; choose one of {list(POLICIES)}")
    if scenario not in ("p50", "p10"):
        raise ValueError("scenario must be 'p50' or 'p10'")
    imp = d.import_p10 if scenario == "p10" else d.import_p50
    planned = plan_v2(soc_start, d, p, pp) if policy == "forecast_aware_v2" else None
    nom_eff = effective_nomination(policy, d, planned or {})
    rows, soc = [], soc_start
    for s in d.slots:
        contingency = 0.0
        if policy == "rule_based_v1":
            want = 0.0
            if pp.v1_night_slots[0] <= s <= pp.v1_night_slots[1] and soc < pp.v1_night_soc_cap:
                want = -pp.v1_night_kw
            elif pp.v1_midday_slots[0] <= s <= pp.v1_midday_slots[1] and soc < pp.v1_midday_soc_cap:
                want = -pp.v1_midday_kw
            elif imp.get(s, 0.0) > pp.v1_demand_limit_kw:
                want = imp[s] - pp.v1_demand_limit_kw
        else:
            want = planned[s]
            if scenario == "p10" and s in d.risk_slots:
                excess = (imp.get(s, 0.0) - want) - nom_eff.get(s, 0.0) - pp.v2_band_use * _band(d, s)
                contingency = max(0.0, excess)
                want += contingency
        power = round(clip_power(soc, want, p), 1)
        soc_end = soc_step(soc, power, p)
        after = imp.get(s, 0.0) - power
        nom = nom_eff.get(s, 0.0)
        rows.append({
            "slot": s,
            "power_kw": power,
            "requested_kw": round(want, 1),
            "contingency_kw": round(contingency, 1),
            "clipped": abs(power - want) > 0.5,
            "soc_start_pct": round(soc, 2),
            "soc_end_pct": round(soc_end, 2),
            "import_before_bess_kw": round(imp.get(s, 0.0), 1),
            "import_after_bess_kw": round(after, 1),
            "nomination_kw": round(nom, 1),
            "deviation_kw": round(after - nom, 1),
            "band_kw": round(_band(d, s), 1),
            "spot_jpy_kwh": d.spot.get(s),
            "in_dr_window": s in d.dr_slots,
            "in_spike_window": s in d.spike_slots,
            "pv_risk_slot": s in d.risk_slots,
            "gate_closed": s in d.locked_slots,
        })
        soc = soc_end
    return rows


def kpis(rows_p50: list[dict], rows_p10: list[dict], d: DayInputs, p: BessParams | None = None) -> dict:
    """Policy KPIs used by compare_bess_policies and the UI (p50 plan + p10 PV stress case)."""
    p = p or BessParams()

    def dr_stats(rows):
        by = {r["slot"]: r for r in rows}
        vals = [by[s]["power_kw"] for s in d.dr_slots if s in by]
        first = min(d.dr_slots) if d.dr_slots else None
        soc_at = by[first]["soc_start_pct"] if first in by else None
        return (round(min(vals), 1) if vals else 0.0, round(sum(vals) / len(vals), 1) if vals else 0.0,
                round(sum(max(0.0, v) * 0.5 for v in vals), 1), soc_at)

    def pre_event_exposure(rows):
        first = min(d.dr_slots) if d.dr_slots else 99
        n_out, jpy, worst = 0, 0.0, 0.0
        for r in rows:
            if r["slot"] >= first or not r["nomination_kw"]:
                continue
            excess_kwh = max(0.0, abs(r["deviation_kw"]) - r["band_kw"]) * 0.5
            if excess_kwh > 0:
                n_out += 1
            jpy += excess_kwh * d.imbalance.get(r["slot"], 0.0)
            worst = max(worst, abs(r["deviation_kw"]) / r["band_kw"] if r["band_kw"] else 0.0)
        return n_out, round(jpy), round(100 * worst, 1)

    f50, a50, e50, soc50 = dr_stats(rows_p50)
    f10, a10, e10, soc10 = dr_stats(rows_p10)
    o50, j50, w50 = pre_event_exposure(rows_p50)
    o10, j10, w10 = pre_event_exposure(rows_p10)
    by = {r["slot"]: r for r in rows_p50}
    socs = [rows_p50[0]["soc_start_pct"]] + [r["soc_end_pct"] for r in rows_p50] if rows_p50 else []
    socs10 = [r["soc_end_pct"] for r in rows_p10]
    energy_cost = sum(-r["power_kw"] * 0.5 * ((r["spot_jpy_kwh"] or 0.0) + d.energy_adder_jpy_kwh) for r in rows_p50)
    return {
        "dr_firm_kw": f50,
        "dr_avg_kw": a50,
        "dr_energy_kwh": e50,
        "soc_at_dr_start_pct": soc50,
        "dr_firm_kw_p10pv": f10,
        "soc_at_dr_start_pct_p10pv": soc10,
        "spike_energy_kwh": round(sum(max(0.0, by[s]["power_kw"]) * 0.5 for s in d.spike_slots if s in by), 1),
        "charge_in_pv_risk_slots_kwh": round(sum(max(0.0, -by[s]["power_kw"]) * 0.5 for s in d.risk_slots if s in by), 1),
        "peak_import_p50_kw": round(max(r["import_after_bess_kw"] for r in rows_p50), 1) if rows_p50 else None,
        "peak_import_p10pv_kw": round(max(r["import_after_bess_kw"] for r in rows_p10), 1) if rows_p10 else None,
        "pre_event_slots_outside_band_p50": o50,
        "pre_event_slots_outside_band_p10pv": o10,
        "pre_event_imbalance_exposure_jpy_p50": j50,
        "pre_event_imbalance_exposure_jpy_p10pv": j10,
        "worst_deviation_pct_of_band_p10pv": w10,
        "bess_energy_cost_jpy": round(energy_cost),
        "soc_min_pct": round(min(socs + socs10), 2) if socs else None,
        "soc_end_pct": rows_p50[-1]["soc_end_pct"] if rows_p50 else None,
        "soc_limit_violations": sum(1 for x in socs + socs10 if x < p.soc_min_pct - 1e-6 or x > p.soc_max_pct + 1e-6),
        "clipped_slots": sum(1 for r in rows_p50 if r["clipped"]),
    }
