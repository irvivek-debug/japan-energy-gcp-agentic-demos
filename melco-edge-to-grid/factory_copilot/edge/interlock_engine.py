"""Edge interlock engine: a deterministic stand-in for the control loop that would run on
Google Distributed Cloud (GDC) connected hardware inside the plant.

"The cloud agents propose; the edge disposes."  Every action in a plan is checked against hard and
soft interlocks using the edge's live PLC view (plc_tags_snapshot), the production schedule and the
asset-level load forecast. Each action gets a verdict:

  ACCEPT  - executes as requested (once a human confirms the plan with Hold-to-Confirm)
  LIMIT   - executes inside a safe envelope (clipped kW, duration or set-point), rule cited
  REJECT  - would break a hard interlock; never executes, rule cited

The engine is pure: no I/O, no clock, no randomness. Latency figures are simulated and deterministic
(derived from the number of rules evaluated plus a hash of the action), standing in for the
sub-10 ms decisions a local control loop makes without a cloud round trip.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from dataclasses import dataclass, field
from statistics import mean

from ..core import bess as bess_core
from ..core.clock import normalise_hhmm, slot_of, slot_start, window_slots

EDGE_NODE = "gdc-edge-atsugi-01 (simulated)"
ACCEPT, LIMIT, REJECT = "ACCEPT", "LIMIT", "REJECT"

ACTION_SYNONYMS = {
    "shed": "curtail", "reduce": "curtail", "curtailment": "curtail", "cut": "curtail", "turn_off": "off", "switch_off": "off",
    "shutdown": "off", "shut_down": "off", "stop": "off", "power_off": "off", "disable": "off",
    "defer_start": "defer", "defer_charge": "defer", "defer_charging": "defer", "delay": "defer", "postpone": "defer",
    "defer_cycle": "defer", "reschedule": "defer", "defer_batch": "defer_batch", "delay_batch": "defer_batch", "move_batch": "defer_batch",
    "tes_shift": "tes_discharge", "thermal_storage": "tes_discharge", "tes": "tes_discharge", "discharge_tes": "tes_discharge",
    "raise_setpoint": "setpoint_shift", "setpoint": "setpoint_shift", "setpoint_shift": "setpoint_shift",
    "chw_setpoint": "chw_setpoint", "chilled_water_setpoint": "chw_setpoint", "dimming": "dim", "dim": "dim",
    "shift": "shift", "prepump": "shift", "hold": "shift", "fan_trim": "trim", "trim": "trim",
    "standby": "standby", "idle": "standby", "pressure_setpoint": "pressure_setpoint", "header_setpoint": "pressure_setpoint",
    "discharge": "discharge", "charge": "charge", "dispatch_policy": "dispatch_policy", "policy": "dispatch_policy",
    "pause": "pause", "off": "off", "curtail": "curtail",
}


@dataclass
class EdgeContext:
    date: str
    now_slot: int
    assets: dict[str, dict]
    rules: dict[str, dict]
    tags: dict[tuple[str, str], float]
    forecast_kw: dict[str, dict[int, float]]          # asset -> slot -> kW (no action)
    schedule: list[dict]                              # production_schedule rows for the date
    import_p50: dict[int, float]                      # site import before BESS (PV p50)
    bess_inputs: bess_core.DayInputs | None = None
    bess_params: bess_core.BessParams = field(default_factory=bess_core.BessParams)
    policy_params: bess_core.PolicyParams = field(default_factory=bess_core.PolicyParams)
    bess_soc_now: float = 50.0
    tes_capacity_kwh_th: float = 14000.0
    tes_floor_pct: float = 15.0
    chw_max_c: float = 8.5
    air_peer_sp: float = 6.1


# ------------------------------------------------------------------------------------------------
def canonical_plan(plan: dict) -> dict:
    keep = {k: plan.get(k) for k in ("date", "start", "end", "event_id", "target_kw") if plan.get(k) not in (None, "")}
    keep["actions"] = [{k: v for k, v in sorted(a.items()) if v not in (None, "")} for a in plan.get("actions", [])]
    return keep


def plan_id_for(plan: dict) -> str:
    h = hashlib.sha1(json.dumps(canonical_plan(plan), sort_keys=True, default=str).encode()).hexdigest()[:6].upper()
    d = str(plan.get("date", "")).replace("-", "")[4:8] or "0000"
    return f"PLAN-{d}-{h}"


def parse_plan(plan_json) -> dict:
    """Accept a dict, a JSON string, or a bare list of actions. Raises ValueError on garbage."""
    if isinstance(plan_json, dict):
        plan = dict(plan_json)
    else:
        txt = str(plan_json).strip()
        if txt.startswith("```"):
            txt = re.sub(r"^```(json)?", "", txt).rstrip("`").strip()
        obj = json.loads(txt)
        plan = {"actions": obj} if isinstance(obj, list) else dict(obj)
    if not isinstance(plan.get("actions"), list) or not plan["actions"]:
        raise ValueError("plan must contain a non-empty 'actions' list")
    return plan


def expand_assets(spec: str, assets: dict[str, dict]) -> list[str]:
    """'AC-04', 'AC-*', 'AC-01..AC-06', 'AC-01,AC-02', 'compressor' (a class) -> asset ids."""
    spec = str(spec).strip()
    out: list[str] = []
    for part in [p.strip() for p in re.split(r"[;,]", spec) if p.strip()]:
        if part in assets:
            out.append(part)
        elif ".." in part:
            a, b = [x.strip() for x in part.split("..", 1)]
            ids = sorted(assets)
            if a in ids and b in ids:
                out += ids[ids.index(a): ids.index(b) + 1]
        elif any(c in part for c in "*?"):
            out += sorted(x for x in assets if fnmatch.fnmatch(x, part.upper()))
        else:
            cls = part.lower().rstrip("s").replace(" ", "_")
            aliases = {"all_compressor": "compressor", "air_compressor": "compressor", "clean-room_hvac": "cleanroom_hvac",
                       "cleanroom_hvac": "cleanroom_hvac", "clean_room_hvac": "cleanroom_hvac"}
            cls = aliases.get(cls, cls)
            out += sorted(x for x, a in assets.items() if a["asset_class"] == cls)
    seen, res = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            res.append(x)
    return res


def _latency_ms(asset_id: str, action: str, n_rules: int) -> float:
    j = int(hashlib.md5(f"{asset_id}:{action}".encode()).hexdigest()[:4], 16) / 65535.0
    return round(1.8 + 0.42 * n_rules + 2.4 * j, 2)


def _rule_applies(rule: dict, asset_id: str) -> bool:
    ap = rule["applies_to"]
    return ap == "*" or any(fnmatch.fnmatch(asset_id, p.strip()) for p in ap.split(";"))


# ------------------------------------------------------------------------------------------------
class _Eval:
    def __init__(self, ctx: EdgeContext, plan: dict):
        self.ctx = ctx
        self.plan = plan
        self.date = plan.get("date") or ctx.date
        self.w_start = normalise_hhmm(plan.get("start") or "16:30")
        self.w_end = normalise_hhmm(plan.get("end") or "19:00")
        self.win = window_slots(self.w_start, self.w_end)
        self.ac_off: set[str] = set()
        self.bess_soc = ctx.bess_soc_now

    def fc(self, aid: str, slot: int) -> float:
        return self.ctx.forecast_kw.get(aid, {}).get(slot, 0.0)

    def tag(self, aid: str, name: str, default=None):
        return self.ctx.tags.get((aid, name), default)

    def result(self, aid, action, req_kw, verdict, rules, reason, by_slot, n_rules=3, extra=None):
        vals = list(by_slot.values()) or [0.0]
        wv = [by_slot.get(s, 0.0) for s in self.win] or [0.0]
        r = {"asset_id": aid, "action": action, "requested_kw": round(float(req_kw or 0.0), 1), "verdict": verdict,
             "rule_ids": rules, "reason": reason,
             "granted_avg_kw": round(mean(wv), 1) if verdict != REJECT else 0.0,
             "granted_min_kw": round(min(wv), 1) if verdict != REJECT else 0.0,
             "granted_by_slot": {int(s): round(v, 1) for s, v in by_slot.items()} if verdict != REJECT else {},
             "latency_ms": _latency_ms(aid, action, n_rules)}
        if extra:
            r.update(extra)
        return r

    # -------------------------------------------------------------------------------------------
    def evaluate(self, raw: dict) -> list[dict]:
        aspec = raw.get("asset_id") or raw.get("asset") or raw.get("assets") or ""
        action = ACTION_SYNONYMS.get(str(raw.get("action", "")).strip().lower().replace(" ", "_").replace("-", "_"),
                                     str(raw.get("action", "")).strip().lower())
        start = normalise_hhmm(raw.get("start") or self.w_start)
        end = normalise_hhmm(raw.get("end") or self.w_end)
        slots = window_slots(start, end)
        req_kw = raw.get("kw", raw.get("requested_kw"))
        ids = expand_assets(aspec, self.ctx.assets) if aspec not in ("COMP-HDR",) else ["COMP-HDR"]
        if not ids:
            return [self.result(str(aspec), action, req_kw, REJECT, ["IR-GEN-01"], f"Unknown asset '{aspec}'.", {}, 1)]
        out = []
        for aid in ids:
            out.append(self._one(aid, action, raw, slots, start, end, req_kw))
        return out

    def _one(self, aid, action, raw, slots, start, end, req_kw):
        if aid == "COMP-HDR":
            return self._compressor(aid, "pressure_setpoint", raw, slots, req_kw)
        a = self.ctx.assets[aid]
        cls = a["asset_class"]
        if cls in ("critical_utility", "cleanroom_exhaust", "receiving_point"):
            return self.result(aid, action, req_kw, REJECT, ["IR-UT-01"],
                               f"{a['asset_name']} is a critical utility and is never curtailed.", {}, 2)
        if cls == "production_line":
            return self.result(aid, action, req_kw, REJECT, ["IR-LN-01"],
                               "No line stops or slowdowns from energy actions; only the production supervisor can release a line in MES.", {}, 2)
        handler = {"cleanroom_hvac": self._cleanroom, "compressor": self._compressor, "furnace": self._furnace,
                   "chiller": self._chiller, "thermal_storage": self._tes, "burn_in": self._burnin, "ev_charger": self._ev,
                   "lighting": self._lighting, "office_hvac": self._office, "wastewater": self._ww, "bess": self._bess,
                   "cooling_aux": self._aux, "pv": self._pv, "building_general": self._aux}.get(cls)
        if handler is None:
            return self.result(aid, action, req_kw, REJECT, ["IR-GEN-01"], f"No edge control model for class {cls}.", {}, 1)
        return handler(aid, action, raw, slots, req_kw)

    # ---- handlers -------------------------------------------------------------------------------
    def _aux(self, aid, action, raw, slots, req_kw):
        return self.result(aid, action, req_kw, REJECT, ["IR-GEN-01"],
                           "Auxiliary load follows its parent system; control the parent (chiller plant or building) instead.", {}, 1)

    def _pv(self, aid, action, raw, slots, req_kw):
        return self.result(aid, action, req_kw, REJECT, ["IR-GEN-01"], "Curtailing PV raises grid import; not a load reduction.", {}, 1)

    def _cleanroom(self, aid, action, raw, slots, req_kw):
        cur = self.tag(aid, "airflow_pct", 100.0)
        floor = self.tag(aid, "min_airflow_pct", 100.0)
        if action in ("off", "curtail", "standby") and not raw.get("to_pct"):
            rules = ["IR-CR-01"] + (["IR-CR-02"] if floor >= 100 else [])
            return self.result(aid, action, req_kw, REJECT, rules,
                               f"Switching off or cutting {aid} drops airflow to 0 % against a floor of {floor:.0f} %: pressure cascade lost, particle excursion, yield loss on exposed SiC product.", {}, 3)
        if floor >= 100:
            return self.result(aid, action, req_kw, REJECT, ["IR-CR-02"],
                               f"{aid} serves a production zone; airflow is held at 100 % while product is exposed.", {}, 3)
        target = max(floor + 3.0, float(raw.get("to_pct") or floor + 3.0))
        ratio = (target / cur) ** 3 if cur > 0 else 1.0
        by = {s: self.fc(aid, s) * (1 - ratio) for s in slots}
        feas = mean(by.values()) if by else 0.0
        verdict, reason = ACCEPT, f"Fan speed trimmed from {cur:.0f} % to {target:.0f} % airflow (floor {floor:.0f} % + 3 % margin); fan power scales with speed cubed."
        if req_kw and float(req_kw) > feas + 1:
            verdict = LIMIT
            reason = f"Requested {float(req_kw):.0f} kW exceeds the safe trim. " + reason
        elif req_kw:
            by = {s: min(v, float(req_kw)) for s, v in by.items()}
        return self.result(aid, "trim", req_kw, verdict, ["IR-CR-01"], reason, by, 3, {"to_airflow_pct": target})

    def _air_state(self):
        caps, flows = {}, {}
        for i in range(1, 7):
            u = f"AC-0{i}"
            caps[u] = self.tag(u, "capacity_nm3min", 42.0)
            flows[u] = self.tag(u, "flow_nm3min", 0.0)
        demand = self.tag("COMP-HDR", "air_demand_nm3min", sum(flows.values()))
        return caps, flows, demand

    def _compressor(self, aid, action, raw, slots, req_kw):
        caps, flows, demand = self._air_state()
        p_now = self.tag("COMP-HDR", "header_pressure_mpa", 0.66)
        p_set = self.tag("COMP-HDR", "header_setpoint_mpa", 0.68)
        vol = self.tag("COMP-HDR", "system_volume_m3", 60.0)
        rule_min = self.ctx.rules.get("IR-CA-03", {}).get("limit_value", 0.65)
        if action == "pressure_setpoint":
            to = float(raw.get("to_mpa") or raw.get("value") or 0.65)
            verdict, rules = ACCEPT, ["IR-CA-03", "IR-CA-01"]
            reason = f"Header setpoint {p_set:.2f} -> {to:.2f} MPa; far end stays above 0.60 MPa."
            if to < rule_min:
                verdict, reason = LIMIT, f"Requested {to:.2f} MPa is below the {rule_min:.2f} MPa floor; clipped to {rule_min:.2f} MPa."
                to = rule_min
            pct = 0.7 * max(0.0, (p_set - to) / 0.01) / 100.0
            total = {s: sum(self.fc(f"AC-0{i}", s) for i in range(1, 7)) for s in slots}
            by = {s: total[s] * pct for s in slots}
            return self.result("COMP-HDR", "pressure_setpoint", req_kw, verdict, rules, reason, by, 3, {"to_mpa": to})
        if action == "standby":
            others_avail = sum(c for u, c in caps.items() if u != aid and u not in self.ac_off)
            n1 = others_avail + caps[aid] - max(caps.values())
            if n1 < demand:
                return self.result(aid, action, req_kw, REJECT, ["IR-CA-02"], f"N-1 capacity {n1:.0f} Nm3/min < demand {demand:.0f}.", {}, 4)
            sp = self.tag(aid, "specific_power", self.ctx.air_peer_sp)
            gain = flows[aid] * max(0.0, sp - self.ctx.air_peer_sp)
            by = {s: gain for s in slots}
            return self.result(aid, action, req_kw, ACCEPT, ["IR-CA-02", "IR-CA-01"],
                               f"{aid} to standby (auto-start ready); its {flows[aid]:.0f} Nm3/min moves to peers at {self.ctx.air_peer_sp:.2f} vs {sp:.2f} kW/(Nm3/min). N-1 capacity {n1:.0f} >= demand {demand:.0f} Nm3/min.",
                               by, 4, {"efficiency_gain_only": True})
        # off / curtail / shed: the unit is isolated (not available)
        self.ac_off.add(aid)
        avail = sum(c for u, c in caps.items() if u not in self.ac_off)
        largest = max([c for u, c in caps.items() if u not in self.ac_off] or [0.0])
        deficit = demand - avail
        if deficit > 0:
            rate = (deficit / 60.0) * 0.1013 / vol          # MPa per second
            t = max(0.0, (p_now - 0.60) / rate) if rate > 0 else 0.0
            return self.result(aid, action, req_kw, REJECT, ["IR-CA-01", "IR-CA-02"],
                               f"With {', '.join(sorted(self.ac_off))} off, available air {avail:.0f} Nm3/min < demand {demand:.0f}; header pressure falls from {p_now:.2f} to 0.60 MPa in about {t:.0f} s and pneumatic actuators on the lines fault.",
                               {}, 5, {"time_to_min_pressure_s": round(t, 1)})
        if avail - largest < demand:
            return self.result(aid, action, req_kw, REJECT, ["IR-CA-02"],
                               f"N-1 violated: available {avail:.0f} minus largest unit {largest:.0f} < demand {demand:.0f} Nm3/min.", {}, 5)
        by = {s: 0.0 for s in slots}
        return self.result(aid, action, req_kw, LIMIT, ["IR-CA-02"], "Isolating a unit gives no net saving: peers pick up the same air. Use standby for AC-04 instead.", by, 4)

    def _batch_conflict(self, aid, slots):
        """Return (active_rows, committed) for batches overlapping the slots."""
        rows = [r for r in self.ctx.schedule if r["asset_id"] == aid and r["job_type"] == "sinter_batch"
                and r["start_slot"] < max(slots) + 1 and r["end_slot"] > min(slots)]
        return rows

    def _furnace(self, aid, action, raw, slots, req_kw):
        rows = self._batch_conflict(aid, slots)
        committed = self.tag(aid, "batch_committed", 0.0) >= 1
        c_start = self.tag(aid, "committed_batch_start_min")
        if rows:
            b = rows[0]
            is_committed = committed and c_start is not None and normalise_hhmm(b["start_ts"]) == f"{int(c_start) // 60:02d}:{int(c_start) % 60:02d}"
            started = b.get("status") in ("running", "completed") or b["start_slot"] < min(slots)
            need_h = (max(slots) + 1 - b["start_slot"]) * 0.5
            if not is_committed and not started and action in ("defer_batch", "defer") and need_h <= float(b.get("deferrable_h") or 0.0):
                by = {s: (max(0.0, self.fc(aid, s) - 130.0) if s >= b["start_slot"] else 0.0) for s in slots}
                return self.result(aid, "defer_batch", req_kw, ACCEPT, ["IR-FN-02", "IR-FN-01"],
                                   f"Batch {b['lot_id']} is planned and not committed at the PLC; its start moves from {b['start_ts'][11:]} to {slot_start(max(slots) + 1)} "
                                   f"(+{need_h:.1f} h, planning limit {float(b.get('deferrable_h') or 0):.0f} h). The furnace holds at about 130 kW until then.",
                                   by, 4, {"rebound_kwh": round(sum(by.values()) * 0.5, 1)})
            rules = (["IR-FN-02", "IR-FN-01"] if is_committed else ["IR-FN-01"])
            why = (f"Batch {b['lot_id']} ({b['start_ts'][11:]}-{b['end_ts'][11:]}) is committed at the PLC (sinter paste printed, recipe loaded): the edge cannot defer or shed it; only the production supervisor can release it in MES. "
                   if is_committed else f"Batch {b['lot_id']} ({b['start_ts'][11:]}-{b['end_ts'][11:]}) overlaps the window and cannot be cut or paused. ")
            why += "Sintering profiles are non-interruptible once started."
            return self.result(aid, action, req_kw, REJECT, rules, why, {}, 4, {"conflicting_batch": b["lot_id"]})
        if action not in ("standby", "curtail", "off", "defer", "defer_batch"):
            return self.result(aid, action, req_kw, REJECT, ["IR-GEN-01"], "Unsupported furnace action.", {}, 1)
        nxt = self.tag(aid, "next_batch_start_min")
        lead = self.tag(aid, "reheat_lead_min", 90.0)
        by = {s: max(0.0, self.fc(aid, s) - 40.0) for s in slots}
        if nxt is not None and nxt > 0:
            latest_end = nxt - lead
            end_min = max(slots) * 30
            if end_min > latest_end:
                keep = [s for s in slots if s * 30 <= latest_end]
                if not keep:
                    return self.result(aid, action, req_kw, REJECT, ["IR-FN-03"], "Next batch too close to allow standby and reheat.", {}, 3)
                by = {s: (v if s in keep else 0.0) for s, v in by.items()}
                return self.result(aid, "standby", req_kw, LIMIT, ["IR-FN-03"],
                                   f"Standby allowed until {slot_start(max(keep) + 1)} so the furnace can reheat ({lead:.0f} min) before its next batch.", by, 3)
        return self.result(aid, "standby", req_kw, ACCEPT, ["IR-FN-03"],
                           f"No batch in the window; holding power drops to standby and reheat ({lead:.0f} min) completes before the next batch.", by, 3)

    def _chiller(self, aid, action, raw, slots, req_kw):
        if action in ("chw_setpoint", "setpoint_shift"):
            delta = float(raw.get("delta_c") or raw.get("value") or 1.5)
            cur = self.tag("CHW-PLANT", "chw_supply_temp_c", 7.0)
            allowed = max(0.0, self.ctx.chw_max_c - cur)
            verdict, reason = ACCEPT, f"Chilled-water supply {cur:.1f} -> {cur + min(delta, allowed):.1f} C (limit {self.ctx.chw_max_c} C); about 2.5 % chiller power per C."
            if delta > allowed + 1e-9:
                verdict, reason = LIMIT, f"Requested +{delta:.1f} C exceeds the {self.ctx.chw_max_c} C supply limit; clipped to +{allowed:.1f} C."
                delta = allowed
            by = {s: self.fc(aid, s) * 0.025 * delta for s in slots}
            return self.result(aid, "chw_setpoint", req_kw, verdict, ["IR-CH-01"], reason, by, 2, {"delta_c": delta})
        running = self.tag("CHW-PLANT", "chillers_running", 4.0)
        return self.result(aid, action, req_kw, REJECT, ["IR-CH-01", "IR-CH-03"],
                           f"Taking a chiller offline with {running:.0f} running leaves the remaining units short of the cooling load; supply temperature would pass 8.5 C. Use thermal storage (TES-01) instead.", {}, 3)

    def _tes(self, aid, action, raw, slots, req_kw):
        soc = self.tag("TES-01", "tes_soc_pct", 85.0)
        cap = self.tag("TES-01", "tes_capacity_kwh_th", self.ctx.tes_capacity_kwh_th)
        cop = self.tag("CHW-PLANT", "cop", 5.3)
        avail_e = max(0.0, (soc - self.ctx.tes_floor_pct) / 100 * cap) / cop
        req = float(req_kw or 700.0)
        chillers = {s: sum(self.fc(f"CH-0{i}", s) for i in range(1, 5)) for s in slots}
        by = {s: min(req, max(0.0, chillers[s] - 2 * 300.0)) for s in slots}
        energy = sum(by.values()) * 0.5
        verdict, rules = ACCEPT, ["IR-CH-02", "IR-CH-03"]
        reason = f"Thermal storage carries {req:.0f} kW of chiller load; TES {soc:.0f} % -> {soc - 100 * energy * cop / cap:.0f} % (floor {self.ctx.tes_floor_pct:.0f} %); two chillers stay online."
        if energy > avail_e:
            scale = avail_e / energy
            by = {s: v * scale for s, v in by.items()}
            verdict, reason = LIMIT, f"TES energy limits the shift to {mean(by.values()):.0f} kW to keep {self.ctx.tes_floor_pct:.0f} % in the tank."
        elif any(v < req - 1 for v in by.values()):
            verdict = LIMIT
            reason += " Limited in slots where chiller load is low (two chillers must stay loaded)."
        return self.result(aid, "tes_discharge", req_kw, verdict, rules, reason, by, 3,
                           {"rebound_kwh": round(energy, 1)})

    def _burnin(self, aid, action, raw, slots, req_kw):
        cycles = [r for r in self.ctx.schedule if r["asset_id"] == aid and r["job_type"] == "burn_in_cycle"]
        first = min(slots)
        last_end = max(slots) + 1
        # 'running' is judged at the decision time (now), from the MES status, not at the window start
        running = [c for c in cycles if c["status"] == "running" and c["end_slot"] > first]
        if running and action in ("pause", "off", "curtail", "defer"):
            c = running[0]
            return self.result(aid, action, req_kw, REJECT, ["IR-BI-02"],
                               f"Cycle {c['lot_id']} is running ({c['start_ts'][11:]}-{c['end_ts'][11:]}); pausing mid-cycle invalidates the test.", {}, 3)
        overlapping = [c for c in cycles if c["status"] == "planned" and c["start_slot"] < last_end and c["end_slot"] > first]
        if not overlapping:
            by = {s: 0.0 for s in slots}
            return self.result(aid, "defer", req_kw, LIMIT, ["IR-BI-01"], "No planned cycle overlaps the window; nothing to defer.", by, 2)
        c = overlapping[0]
        defer_h = (last_end - c["start_slot"]) * 0.5
        if action == "pause" or defer_h > 3.0:
            return self.result(aid, "defer", req_kw, REJECT, ["IR-BI-01"],
                               f"Cycle {c['lot_id']} starts {c['start_ts'][11:]}; moving it clear of the window needs {defer_h:.1f} h, above the 3 h limit.", {}, 3)
        by = {s: (self.fc(aid, s) if c["start_slot"] <= s < c["end_slot"] else 0.0) for s in slots}
        return self.result(aid, "defer", req_kw, ACCEPT, ["IR-BI-01"],
                           f"Cycle {c['lot_id']} start moves from {c['start_ts'][11:]} to {slot_start(last_end)} (+{defer_h:.1f} h, limit 3 h).",
                           by, 3, {"rebound_kwh": round(sum(by.values()) * 0.5, 1)})

    def _ev(self, aid, action, raw, slots, req_kw):
        if aid in {f"EV-0{i}" for i in range(1, 7)}:
            by = {s: 0.0 for s in slots}
            return self.result(aid, "defer", req_kw, LIMIT, ["IR-EV-02"], "Forklift charger: no charging scheduled in the window and shift-change charging is not deferred.", by, 2)
        arr = self.tag(aid, "arrival_soc_pct", 40.0)
        need = self.tag(aid, "required_soc_pct", 80.0)
        hours_needed = (need - arr) / 100 * 75.0 / 50.0
        by = {s: self.fc(aid, s) for s in slots}
        return self.result(aid, "defer", req_kw, ACCEPT, ["IR-EV-01"],
                           f"Van charge (arrival {arr:.0f} % -> {need:.0f} %, about {hours_needed:.1f} h at 50 kW) still completes well before 07:00.",
                           by, 2, {"rebound_kwh": round(sum(by.values()) * 0.5, 1)})

    def _lighting(self, aid, action, raw, slots, req_kw):
        pct = float(raw.get("pct") or raw.get("dim_pct") or 30.0)
        if action == "off":
            pct = 100.0
        verdict, reason = ACCEPT, f"Dim {pct:.0f} % (policy limit 30 %)."
        if pct > 30.0:
            verdict, reason, pct = LIMIT, f"Requested {pct:.0f} % dimming exceeds the 30 % illuminance limit; clipped to 30 %.", 30.0
        by = {s: self.fc(aid, s) * pct / 100 for s in slots}
        return self.result(aid, "dim", req_kw, verdict, ["IR-LT-01"], reason, by, 2, {"dim_pct": pct})

    def _office(self, aid, action, raw, slots, req_kw):
        if action == "off":
            return self.result(aid, action, req_kw, LIMIT, ["IR-OF-01"], "Office air handlers are not switched off; applying the +2 C set-point limit instead.",
                               {s: self.fc(aid, s) * 0.32 for s in slots}, 2, {"delta_c": 2.0})
        delta = float(raw.get("delta_c") or raw.get("value") or 2.0)
        cur = self.tag("OF-ZONE", "zone_setpoint_c", 26.0)
        allowed = max(0.0, 28.0 - cur)
        verdict, reason = ACCEPT, f"Zone set-point {cur:.0f} -> {cur + min(delta, allowed):.0f} C (policy limit 28 C)."
        if delta > allowed:
            verdict, reason, delta = LIMIT, f"Requested +{delta:.1f} C exceeds the 28 C limit; clipped to +{allowed:.1f} C.", allowed
        by = {s: self.fc(aid, s) * 0.16 * delta for s in slots}
        return self.result(aid, "setpoint_shift", req_kw, verdict, ["IR-OF-01"], reason, by, 2, {"delta_c": delta})

    def _ww(self, aid, action, raw, slots, req_kw):
        minutes = float(raw.get("minutes") or 60.0) if action != "off" else len(slots) * 30.0
        to_alarm = self.tag("WW-PIT", "minutes_to_high_alarm_no_pumping", 75.0)
        allowed = min(60.0, to_alarm - 10.0)
        verdict = ACCEPT
        reason = f"Pre-pump the pit and hold for {min(minutes, allowed):.0f} min (limit 60 min; high alarm in {to_alarm:.0f} min at current inflow)."
        window_min = len(slots) * 30
        if minutes > allowed or window_min > allowed:
            verdict = LIMIT
            reason = f"Hold limited to {allowed:.0f} min of the {window_min} min window (pit high alarm). " + reason
        n = int(min(minutes, allowed) // 30)
        by = {s: (self.fc(aid, s) if i < n else 0.0) for i, s in enumerate(slots)}
        return self.result(aid, "shift", req_kw, verdict, ["IR-WW-01"], reason, by, 2, {"hold_min": min(minutes, allowed)})

    def _bess(self, aid, action, raw, slots, req_kw):
        p = self.ctx.bess_params
        if action == "dispatch_policy" or raw.get("policy"):
            pol = raw.get("policy") or "forecast_aware_v2"
            if pol not in bess_core.POLICIES or self.ctx.bess_inputs is None:
                return self.result(aid, action, req_kw, REJECT, ["IR-GEN-01"], f"Unknown BESS policy '{pol}'.", {}, 1)
            rows = bess_core.simulate(pol, self.ctx.bess_soc_now, self.ctx.bess_inputs, "p50", p, self.ctx.policy_params)
            socs = [r["soc_end_pct"] for r in rows]
            ok = all(p.soc_min_pct - 1e-6 <= x <= p.soc_max_pct + 1e-6 for x in socs) and all(abs(r["power_kw"]) <= p.power_kw for r in rows)
            by = {r["slot"]: max(0.0, r["power_kw"]) for r in rows if r["slot"] in self.win}
            by = {s: by.get(s, 0.0) for s in slots}
            pre = [r for r in rows if r["slot"] < min(self.win)]
            soc_at = next((r["soc_start_pct"] for r in rows if r["slot"] == min(self.win)), None)
            steps = max((abs(r["power_kw"] - prev["power_kw"]) for prev, r in zip(rows, rows[1:])), default=0.0)
            reason = (f"Policy {pol}: SOC {self.ctx.bess_soc_now:.1f} % now -> {soc_at:.1f} % at {self.w_start}, min {min(socs):.1f} %, within 10-95 %. "
                      f"Largest set-point step {steps:.0f} kW is ramped at 2,000 kW/min.")
            return self.result(aid, "dispatch_policy", req_kw, ACCEPT if ok else LIMIT, ["IR-BS-01", "IR-BS-02", "IR-BS-03"], reason, by, 4,
                               {"policy": pol, "pre_window_charge_kwh": round(sum(-r["power_kw"] for r in pre if r["power_kw"] < 0) * 0.5, 1),
                                "soc_at_window_start_pct": soc_at, "soc_min_pct": round(min(socs), 2)})
        req = float(req_kw or 0.0)
        sign = -1.0 if action == "charge" else 1.0
        rules = ["IR-BS-01", "IR-BS-02"]
        verdict, notes = ACCEPT, []
        if req > p.power_kw:
            verdict, notes = LIMIT, [f"power clipped to {p.power_kw:.0f} kW (IR-BS-02)"]
            req = p.power_kw
        soc = self.bess_soc
        by = {}
        for s in range(self.ctx.now_slot, max(slots) + 1):
            if s in slots:
                pw = bess_core.clip_power(soc, sign * req, p)
                if abs(pw) + 1 < req:
                    verdict = LIMIT
                    if "SOC" not in " ".join(notes):
                        notes.append(f"SOC reaches the {'10' if sign > 0 else '95'} % limit at {slot_start(s)}; power reduced (IR-BS-01)")
                by[s] = max(0.0, pw)
                soc = bess_core.soc_step(soc, pw, p)
        self.bess_soc = soc
        reason = (f"{'Discharge' if sign > 0 else 'Charge'} {req:.0f} kW from SOC {self.ctx.bess_soc_now:.1f} %; end SOC {soc:.1f} %. "
                  + ("; ".join(notes) if notes else "Within 10-95 % SOC and 4,000 kW."))
        return self.result(aid, action, req_kw, verdict, rules, reason, {s: by.get(s, 0.0) for s in slots}, 3)


# ------------------------------------------------------------------------------------------------
def evaluate_plan(plan_json, ctx: EdgeContext) -> dict:
    """Evaluate a plan and return per-action verdicts plus plant-level totals.

    plan_json: dict or JSON string {"date", "start", "end", "event_id", "target_kw", "actions": [
               {"asset_id", "action", "kw", "start", "end", ...}]}.
    """
    plan = parse_plan(plan_json)
    ev = _Eval(ctx, plan)
    results: list[dict] = []
    for raw in plan["actions"]:
        results.extend(ev.evaluate(raw))
    win = ev.win
    red = {s: 0.0 for s in win}
    for r in results:
        if r["verdict"] != REJECT:
            for s, v in r["granted_by_slot"].items():
                if s in red:
                    red[s] += v
    target = float(plan.get("target_kw") or 0.0)
    firm = min(red.values()) if red else 0.0
    avg = mean(red.values()) if red else 0.0
    first_step = red.get(win[0], 0.0) if win else 0.0
    seq_min = max(1, int(-(-first_step // 2500)))
    by_slot = [{"slot": s, "ts": f"{ev.date}T{slot_start(s)}", "forecast_import_kw": round(ctx.import_p50.get(s, 0.0), 1),
                "reduction_kw": round(red[s], 1), "planned_import_kw": round(ctx.import_p50.get(s, 0.0) - red[s], 1)} for s in win]
    rebound = sum(r.get("rebound_kwh", 0.0) for r in results if r["verdict"] != REJECT)
    counts = {k: sum(1 for r in results if r["verdict"] == k) for k in (ACCEPT, LIMIT, REJECT)}
    return {
        "plan_id": plan.get("plan_id") or plan_id_for(plan),
        "edge_node": EDGE_NODE,
        "evaluated_at": f"{ctx.date}T{slot_start(ctx.now_slot)}",
        "window": {"date": ev.date, "start": ev.w_start, "end": ev.w_end, "slots": win},
        "event_id": plan.get("event_id", ""),
        "target_kw": target,
        "actions": results,
        "summary": {
            "actions_evaluated": len(results), "accepted": counts[ACCEPT], "limited": counts[LIMIT], "rejected": counts[REJECT],
            "firm_reduction_kw": round(firm, 1), "average_reduction_kw": round(avg, 1),
            "margin_kw": round(firm - target, 1) if target else None,
            "margin_pct": round(100 * (firm - target) / target, 1) if target else None,
            "meets_target": bool(target and firm >= target),
            "total_decision_ms": round(sum(r["latency_ms"] for r in results), 2),
            "max_action_decision_ms": max((r["latency_ms"] for r in results), default=0.0),
            "rebound_kwh_after_window": round(rebound, 1),
            "sequencing": f"First-slot step of {first_step:,.0f} kW is sequenced over {seq_min} min (IR-PL-01, 2,500 kW/min).",
        },
        "by_slot": by_slot,
        "rejected_actions": [{"asset_id": r["asset_id"], "action": r["action"], "rule_ids": r["rule_ids"], "reason": r["reason"]}
                             for r in results if r["verdict"] == REJECT],
    }


def firm_slots(result: dict) -> dict[int, float]:
    return {row["slot"]: row["reduction_kw"] for row in result["by_slot"]}


def slot_label(slot: int) -> str:
    return slot_start(slot)


__all__ = ["EdgeContext", "evaluate_plan", "parse_plan", "plan_id_for", "expand_assets", "ACCEPT", "LIMIT", "REJECT", "slot_of"]
