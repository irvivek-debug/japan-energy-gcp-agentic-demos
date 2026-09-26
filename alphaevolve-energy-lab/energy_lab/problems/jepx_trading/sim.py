"""Trusted balance-group trading simulator for KBG (runs in the parent; candidate code only returns decisions).

Per day (blocks of 8 consecutive days; BESS state of charge carries over within a block):
  D-1 10:00  plan_day_ahead(ctx)   ctx = forecasts (demand, PV, price quantiles, reserve margin), BESS state,
                                    calendar, last 14 days of realised DA prices. Nothing realised about day D.
  DA auction single price per slot: exogenous clearing price + price impact k x (our net volume - forecast net load);
             buy fills if limit >= clearing, sell fills if limit <= clearing (bisection on the monotone residual).
  t-1h       adjust_intraday(ctx_t) for each slot in order: H-1 forecasts for slot t, DA position, BESS SOC,
             intraday best bid/ask and KBG-accessible liquidity; continuous fills at ask/bid + impact, capped.
  delivery   realised demand and PV, BESS physics (power, SOC 10-95%, RTE split sqrt(0.85)), single-price imbalance
             (MARKET_FACTS 3: surplus and shortage settle at the same price), degradation cost per MWh discharged.
Policy invariants (violations are collected with slot lists; any violation invalidates the candidate):
  intentional_imbalance  planned position after intraday (DA fills + marketable ID orders + BESS) must be within
                         max(5 MWh, 3%) of the best available (H-1) net-load forecast, in both directions, and the
                         mean signed gap over all slots must stay within +/-0.5% (no systematic edge-of-band bias)
  naked_selling          DA sells per slot <= planned BESS discharge + forecast PV surplus; ID net position >= -(BESS+PV)
  bess_limits            |MW| <= rating, SOC within 10-95% (plan and dispatch), discharge <= 2 cycles/day
  bess_warranty          annualised discharge throughput <= 450 cycles x 180 MWh
  jepx_bounds            limits in [0.01, 999.99] JPY/kWh, quantities finite and >= 0, slots 1..48, <= 20 bids/slot
Score (JPY M) = -(annualised cost to serve + risk penalty); cost = DA + ID procurement + imbalance settlement +
degradation + terminal SOC valuation; risk penalty = (CVaR95 - mean) of daily excess cost vs a buy-actual-at-DA benchmark,
x 18.25 days (the 5% tail of a year).
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field

import numpy as np

from ...sim.market import scarcity_curve

S = 48
MAX_BIDS_PER_SLOT = 20
SOC_TOL = 1e-3            # MWh numerical tolerance on SOC / throughput limits
SYSTEMATIC_BIAS_MAX = 0.005   # |mean(planned - forecast)| / mean(forecast) over all slots
# Evaluator v2 (after run jepx_trading.20260926T075644Z): v1 valued the end-of-block SOC change at the block's mean price
# with no losses, so ending a block fuller earned a credit worth ~3x its real value on calm blocks. v2 charges a deficit at
# its replacement cost (mean / eta_charge) and credits a surplus at what it can deliver (mean x eta_discharge - wear).
TERMINAL_VALUATION = "v2"
EVALUATOR_VERSION = ("jepx_trading/v2: terminal SOC at replacement / deliverable value (v1: mean price, no losses); "
                     "compliance tolerance max(5 MWh, 3%) + systematic-bias limit 0.5%")
LAMBDA_RISK = 1.0
TAIL_DAYS = 18.25


class Violations:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def add(self, inv: str, where: str, text: str, **extra):
        v = self.items.setdefault(inv, {"invariant": inv, "count": 0, "examples": [], "slots": []})
        v["count"] += 1
        if len(v["examples"]) < 4:
            v["examples"].append(text)
        if len(v["slots"]) < 40:
            v["slots"].append(where)
        for k, val in extra.items():
            v.setdefault(k, 0.0)
            v[k] += val

    def as_list(self) -> list[dict]:
        out = []
        for v in self.items.values():
            txt = f"{v['count']} violation(s); e.g. " + " | ".join(v["examples"][:3])
            if v["invariant"] == "intentional_imbalance":
                txt += f"; slots: {', '.join(v['slots'][:12])}{' ...' if v['count'] > 12 else ''}"
                if "short_mwh" in v:
                    txt += f"; total deliberate shortfall {v.get('short_mwh', 0):.0f} MWh, surplus {v.get('long_mwh', 0):.0f} MWh"
            out.append({**v, "text": txt})
        return out

    def __bool__(self):
        return bool(self.items)


@dataclass
class DayResult:
    date: str
    da_cost: float = 0.0
    id_cost: float = 0.0
    imb_cost: float = 0.0
    deg_cost: float = 0.0
    bench: float = 0.0
    imb_abs_mwh: float = 0.0
    load_mwh: float = 0.0
    discharge_mwh: float = 0.0
    id_volume_mwh: float = 0.0
    da_buy_mwh: float = 0.0

    @property
    def cost(self) -> float:
        return self.da_cost + self.id_cost + self.imb_cost + self.deg_cost


def _q(x: np.ndarray | float, sd: np.ndarray | float, z: float) -> np.ndarray:
    return np.maximum(np.asarray(x) + z * np.asarray(sd), 0.0)


def _r(a) -> list:
    return [round(float(v), 3) for v in a]


class TradingSim:
    def __init__(self, arr: dict):
        self.a = {k: np.asarray(v) for k, v in arr.items()}
        self.params = json.loads(str(arr["params_json"]))
        self.b = self.params["bess"]
        self.E = self.b["energy_mwh"]
        self.P = self.b["power_mw"]
        self.soc_min, self.soc_max = self.b["soc_min_frac"] * self.E, self.b["soc_max_frac"] * self.E
        self.eta_c, self.eta_d = self.b["eta_charge"], self.b["eta_discharge"]
        self.deg = self.b["degradation_jpy_per_mwh"]
        self.max_daily_dis = self.b["max_cycles_per_day"] * self.E
        self.tol_abs = self.params["compliance_tolerance"]["abs_mwh"]
        self.tol_rel = self.params["compliance_tolerance"]["rel"]
        self.floor, self.cap = self.params["jepx"]["price_floor"], self.params["jepx"]["price_cap"]
        self.lot = self.params["jepx"]["lot_mwh"]
        self.k_da = self.params["da_price_impact_jpy_kwh_per_mwh"]
        self.k_id = self.params["id_impact_jpy_kwh_per_mwh"]
        self.n_days = len(self.a["day_date"])

    # -- contexts (built ONLY from forecasts, past realised prices and current state) ---------------------------
    def rules(self, i: int) -> dict:
        c = float(self.a["c_val"][i].max())
        return {"price_floor": self.floor, "price_cap": self.cap, "tick_jpy_kwh": 0.01, "lot_mwh": self.lot,
                "tolerance_abs_mwh": self.tol_abs, "tolerance_rel": self.tol_rel, "imbalance_single_price": True,
                "scarcity_curve": {"B_pct": 10, "B_prime_pct": 8, "A_pct": 3, "D": 50.0 if c > 250 else 45.0, "C": c},
                "max_bids_per_slot": MAX_BIDS_PER_SLOT}

    def bess_static(self) -> dict:
        return {"power_mw": self.P, "energy_mwh": self.E, "soc_min_mwh": self.soc_min, "soc_max_mwh": self.soc_max,
                "eta_charge": self.eta_c, "eta_discharge": self.eta_d, "rte": self.b["rte"],
                "degradation_jpy_per_mwh": self.deg, "max_daily_discharge_mwh": self.max_daily_dis}

    def da_ctx(self, i: int, soc: float, warranty_left: float) -> dict:
        a = self.a
        dem, dsd = a["da_demand_p50"][i], a["da_demand_sd"][i]
        pv, psd = a["da_pv_p50"][i], a["da_pv_sd"][i]
        m = int(a["day_month"][i])
        return {
            "date": str(a["day_date"][i]), "weekday": int(a["day_dow"][i]), "is_working_day": bool(a["day_working"][i]),
            "is_holiday": bool(a["day_holiday"][i]), "month": m,
            "season": {12: "winter", 1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer",
                       7: "summer", 8: "summer", 9: "summer", 10: "autumn", 11: "autumn"}[m],
            "forecast": {
                "demand_mw": {"p10": _r(_q(dem, dsd, -1.2816)), "p50": _r(dem), "p90": _r(_q(dem, dsd, 1.2816))},
                "pv_mw": {"p10": _r(_q(pv, psd, -1.2816)), "p50": _r(pv), "p90": _r(_q(pv, psd, 1.2816))},
                "net_load_mwh_p50": _r((dem - pv) * 0.5),
                "price_jpy_kwh": {"p10": _r(a["da_price_p10"][i]), "p50": _r(a["da_price_p50"][i]),
                                  "p90": _r(a["da_price_p90"][i])},
                "reserve_margin_p50": [round(float(x), 4) for x in a["da_rm_p50"][i]],
            },
            "recent_prices_jpy_kwh": [_r(r) for r in a["hist14"][i]],
            "bess": {**self.bess_static(), "soc_mwh": float(soc), "warranty_remaining_mwh": round(warranty_left, 1)},
            "rules": self.rules(i),
        }

    def id_ctx(self, i: int, t: int, da_net: float, da_prices: np.ndarray, soc: float, planned: float,
               discharged: float, da_plan: list, da_ctx_forecast: dict) -> dict:
        a = self.a
        dem, dsd = float(a["ha_demand_p50"][i, t]), float(a["ha_demand_sd"][i, t])
        pv, psd = float(a["ha_pv_p50"][i, t]), float(a["ha_pv_sd"][i, t])
        rm = float(a["ha_rm"][i, t])
        r = self.rules(i)
        return {
            "date": str(a["day_date"][i]), "slot": t + 1,
            "forecast_ha": {"demand_mw": round(dem, 3), "demand_sd_mw": round(dsd, 3), "pv_mw": round(pv, 3),
                            "pv_sd_mw": round(psd, 3), "net_load_mwh": round((dem - pv) * 0.5, 3), "reserve_margin": round(rm, 4),
                            "imbalance_scarcity_price_est": round(float(scarcity_curve(rm, r["scarcity_curve"]["C"],
                                                                                        r["scarcity_curve"]["D"])), 2)},
            "forecast_da": da_ctx_forecast,
            "position_mwh": {"da_net": round(da_net, 3)},
            "da_clearing_prices_jpy_kwh": _r(da_prices),
            "intraday": {"best_bid": float(a["id_bid"][i, t]), "best_ask": float(a["id_ask"][i, t]),
                         "liquidity_mwh": float(a["id_liq_mwh"][i, t]), "impact_jpy_kwh_per_mwh": self.k_id},
            "bess": {**self.bess_static(), "soc_mwh": float(soc), "planned_mw": float(planned),
                     "discharged_today_mwh": float(discharged), "da_plan_mw": [float(x) for x in da_plan]},
            "rules": r,
        }

    # -- market mechanics ---------------------------------------------------------------------------------------
    def clear_da(self, i: int, buys: list, sells: list, ref_mwh: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Returns clearing price [48], filled buy MWh [48], filled sell MWh [48]."""
        exo = self.a["spot"][i].astype(float)
        tight = np.clip((0.12 - self.a["rm"][i].astype(float)) / 0.12, 0, 1)
        k = self.k_da * (1 + 4 * tight)
        price, fb, fs = np.empty(S), np.zeros(S), np.zeros(S)
        for t in range(S):
            bq = np.array([q for q, _ in buys[t]]) if buys[t] else np.zeros(0)
            bl = np.array([l for _, l in buys[t]]) if buys[t] else np.zeros(0)
            sq = np.array([q for q, _ in sells[t]]) if sells[t] else np.zeros(0)
            sl = np.array([l for _, l in sells[t]]) if sells[t] else np.zeros(0)

            def net(x):
                return bq[bl >= x].sum() - sq[sl <= x].sum()

            def f(x):
                return x - exo[t] - k[t] * (net(x) - ref_mwh[t])

            lo, hi = self.floor, self.cap
            if f(lo) >= 0:
                p = lo
            elif f(hi) <= 0:
                p = hi
            else:
                for _ in range(50):
                    mid = 0.5 * (lo + hi)
                    if f(mid) < 0:
                        lo = mid
                    else:
                        hi = mid
                p = hi
            p = round(p, 2)
            price[t] = p
            fb[t] = bq[bl >= p].sum()
            fs[t] = sq[sl <= p].sum()
        return price, fb, fs

    def terminal_value(self, start: float, end: float, mean_price: float) -> float:
        """Cost (JPY, + = cost) of ending a block at ``end`` MWh vs ``start`` MWh."""
        d = start - end
        if TERMINAL_VALUATION == "v1":
            return d * mean_price * 1000.0
        if d >= 0:                                          # deficit: energy must be bought back through the charger
            return d / self.eta_c * mean_price * 1000.0
        return d * self.eta_d * mean_price * 1000.0 + (-d) * self.eta_d * self.deg   # surplus: deliverable value, net of wear

    # -- physics helpers ------------------------------------------------------------------------------------------
    def soc_after(self, soc: float, mw: float) -> float:
        return soc - mw * 0.5 / self.eta_d if mw >= 0 else soc + (-mw) * 0.5 * self.eta_c

    def run(self, sandbox, collect_days: bool = False) -> dict:
        a = self.a
        viol = Violations()
        days: list[DayResult] = []
        blocks = a["day_block"].astype(int)
        soc = self.b["soc_start_frac"] * self.E
        block_start_soc = soc
        terminal = 0.0
        total_dis = 0.0
        warranty_total = self.b["warranty_cycles_per_year"] * self.E * self.n_days / 365.0
        excess = []
        gap_sum, fc_sum = 0.0, 0.0
        for i in range(self.n_days):
            new_block = i == 0 or blocks[i] != blocks[i - 1]
            if new_block:
                if i > 0:   # value the previous block's terminal SOC at its mean DA price
                    sel = blocks == blocks[i - 1]
                    terminal += self.terminal_value(block_start_soc, soc, float(a["spot"][sel].mean()))
                soc = self.b["soc_start_frac"] * self.E
                block_start_soc = soc
            day = DayResult(date=str(a["day_date"][i]))
            ctx = self.da_ctx(i, soc, warranty_total - total_dis)
            plan_out = sandbox.call("plan_day_ahead", ctx)
            buys, sells, plan = self._validate_da(i, plan_out, ctx, soc, viol)
            ref = (a["da_demand_p50"][i] - a["da_pv_p50"][i]).astype(float) * 0.5
            da_price, fb, fs = self.clear_da(i, buys, sells, ref)
            da_net = fb - fs
            day.da_cost = float((da_net * da_price).sum() * 1000.0)
            day.da_buy_mwh = float(fb.sum())
            discharged = 0.0
            fc_da = {"net_load_mwh_p50": ctx["forecast"]["net_load_mwh_p50"], "price_jpy_kwh_p50": ctx["forecast"]["price_jpy_kwh"]["p50"]}
            for t in range(S):
                ctx_t = self.id_ctx(i, t, float(da_net[t]), da_price, soc, float(plan[t]), discharged, plan, fc_da)
                out = sandbox.call("adjust_intraday", ctx_t)
                orders, mw = self._validate_id(i, t, out, viol)
                # BESS physics + limits (violations recorded, dispatch clipped to stay physical)
                if abs(mw) > self.P + 1e-6:
                    viol.add("bess_limits", f"{day.date} s{t + 1}", f"{day.date} slot {t + 1}: bess_mw {mw:.1f} exceeds {self.P} MW")
                    mw = math.copysign(self.P, mw)
                new_soc = self.soc_after(soc, mw)
                if new_soc < self.soc_min - SOC_TOL or new_soc > self.soc_max + SOC_TOL:
                    viol.add("bess_limits", f"{day.date} s{t + 1}",
                             f"{day.date} slot {t + 1}: SOC would reach {new_soc:.1f} MWh (limits {self.soc_min:.0f}-{self.soc_max:.0f})")
                    new_soc = min(max(new_soc, self.soc_min), self.soc_max)
                    mw = (soc - new_soc) * 2 * self.eta_d if new_soc <= soc else -(new_soc - soc) * 2 / self.eta_c
                if mw > 0:
                    discharged += mw * 0.5
                    if discharged > self.max_daily_dis + SOC_TOL:
                        viol.add("bess_limits", f"{day.date} s{t + 1}",
                                 f"{day.date}: daily discharge {discharged:.0f} MWh > {self.max_daily_dis:.0f} MWh (2 cycles)")
                soc = new_soc
                # intraday fills
                bid, ask, liq = float(a["id_bid"][i, t]), float(a["id_ask"][i, t]), float(a["id_liq_mwh"][i, t])
                mb = sum(q for s, q, l in orders if s == "buy" and l >= ask)
                ms = sum(q for s, q, l in orders if s == "sell" and l <= bid)
                fb_id, fs_id = min(mb, liq), min(ms, liq)
                id_cost = fb_id * (ask + self.k_id * fb_id / 2) * 1000.0 - fs_id * (bid - self.k_id * fs_id / 2) * 1000.0
                day.id_cost += id_cost
                day.id_volume_mwh += fb_id + fs_id
                # compliance: planned position vs best available forecast (intent = marketable quantities)
                fc = float(ctx_t["forecast_ha"]["net_load_mwh"])
                planned_pos = float(da_net[t]) + mb - ms + mw * 0.5
                tol = max(self.tol_abs, self.tol_rel * abs(fc))
                gap = planned_pos - fc
                gap_sum += gap
                fc_sum += abs(fc)
                if abs(gap) > tol + 1e-6:
                    direction = "short" if gap < 0 else "long"
                    viol.add("intentional_imbalance", f"{day.date} s{t + 1}",
                             f"{day.date} slot {t + 1}: planned {planned_pos:.1f} MWh vs forecast {fc:.1f} MWh "
                             f"({direction} {abs(gap):.1f} > tol {tol:.1f}); imbalance {a['imbalance'][i, t]:.2f} vs spot "
                             f"{a['spot'][i, t]:.2f} JPY/kWh",
                             short_mwh=max(0.0, -gap - tol), long_mwh=max(0.0, gap - tol))
                pv_sur = max(0.0, float(a["ha_pv_p50"][i, t] - a["ha_demand_p50"][i, t])) * 0.5
                if float(da_net[t]) + mb - ms < -(max(0.0, mw) * 0.5 + pv_sur) - 0.05:
                    viol.add("naked_selling", f"{day.date} s{t + 1}",
                             f"{day.date} slot {t + 1}: net market position {float(da_net[t]) + mb - ms:.1f} MWh is short "
                             f"beyond BESS discharge + PV surplus")
                # delivery + imbalance (single price)
                load = float(a["demand_mw"][i, t] - a["pv_mw"][i, t]) * 0.5
                pos = float(da_net[t]) + fb_id - fs_id + mw * 0.5
                imb = pos - load
                ip = float(a["imbalance"][i, t])
                day.imb_cost += -imb * ip * 1000.0
                day.imb_abs_mwh += abs(imb)
                day.load_mwh += load
                if mw > 0:
                    day.deg_cost += mw * 0.5 * self.deg
                    day.discharge_mwh += mw * 0.5
                day.bench += load * float(a["spot"][i, t]) * 1000.0
            total_dis += day.discharge_mwh
            excess.append(day.cost - day.bench)
            days.append(day)
        sel = blocks == blocks[-1]
        terminal += self.terminal_value(block_start_soc, soc, float(a["spot"][sel].mean()))
        ann = 365.0 / self.n_days
        if total_dis * ann > self.b["warranty_cycles_per_year"] * self.E + 1e-6:
            viol.add("bess_warranty", "annual", f"annualised discharge {total_dis * ann:.0f} MWh > warranty "
                                               f"{self.b['warranty_cycles_per_year'] * self.E:.0f} MWh")
        bias = gap_sum / max(fc_sum, 1e-9)
        if abs(bias) > SYSTEMATIC_BIAS_MAX:
            viol.add("intentional_imbalance", "all slots",
                     f"systematic {'short' if bias < 0 else 'long'} bias: mean planned-minus-forecast {bias:+.2%} of forecast "
                     f"net load across all slots (limit +/-{SYSTEMATIC_BIAS_MAX:.1%}); positioning at the edge of the band "
                     "every slot is intentional imbalance")
        ex = np.array(excess)
        k = max(1, int(np.ceil(0.05 * len(ex))))
        cvar = float(np.sort(ex)[-k:].mean())
        risk_pen = LAMBDA_RISK * max(0.0, cvar - float(ex.mean())) * TAIL_DAYS
        cost_total = sum(d.cost for d in days) + terminal
        annual_cost = cost_total * ann
        score = -(annual_cost + risk_pen) / 1e6
        load = sum(d.load_mwh for d in days)
        res = {
            "score": score, "annual_cost_jpy_m": annual_cost / 1e6, "risk_penalty_jpy_m": risk_pen / 1e6,
            "da_cost_jpy_m": sum(d.da_cost for d in days) * ann / 1e6, "id_cost_jpy_m": sum(d.id_cost for d in days) * ann / 1e6,
            "imbalance_cost_jpy_m": sum(d.imb_cost for d in days) * ann / 1e6,
            "degradation_jpy_m": sum(d.deg_cost for d in days) * ann / 1e6, "terminal_soc_jpy_m": terminal * ann / 1e6,
            "benchmark_jpy_m": sum(d.bench for d in days) * ann / 1e6,
            "cost_vs_benchmark_jpy_kwh": (cost_total - sum(d.bench for d in days)) / (load * 1000.0),
            "unit_cost_jpy_kwh": cost_total / (load * 1000.0),
            "imbalance_abs_share": sum(d.imb_abs_mwh for d in days) / load,
            "id_volume_share": sum(d.id_volume_mwh for d in days) / load,
            "bess_cycles_per_day": sum(d.discharge_mwh for d in days) / (self.E * self.n_days),
            "worst_day_excess_jpy_m": float(ex.max()) / 1e6, "worst_day": days[int(ex.argmax())].date,
            "n_days": self.n_days, "violations": viol.as_list(), "plan_bias": bias,
        }
        if collect_days:
            res["days"] = [d.__dict__ | {"cost": d.cost} for d in days]
        return res

    # -- validation -----------------------------------------------------------------------------------------------
    def _num(self, v) -> float | None:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return None
        f = float(v)
        return f if math.isfinite(f) else None

    def _validate_da(self, i: int, out, ctx: dict, soc: float, viol: Violations):
        date = str(self.a["day_date"][i])
        buys = [[] for _ in range(S)]
        sells = [[] for _ in range(S)]
        plan = np.zeros(S)
        if not isinstance(out, dict) or "bids" not in out or "bess_plan_mw" not in out:
            raise FormatError("plan_day_ahead must return {'bids': [...], 'bess_plan_mw': [48 floats]}")
        bp = out["bess_plan_mw"]
        if not isinstance(bp, list) or len(bp) != S or any(self._num(x) is None for x in bp):
            raise FormatError("bess_plan_mw must be a list of 48 finite numbers")
        plan = np.array([float(x) for x in bp])
        if not isinstance(out["bids"], list):
            raise FormatError("bids must be a list")
        count = np.zeros(S, int)
        for b in out["bids"]:
            if not isinstance(b, dict):
                raise FormatError("each bid must be a dict {slot, side, qty_mwh, limit_jpy_kwh}")
            slot, side, qty, lim = b.get("slot"), b.get("side"), self._num(b.get("qty_mwh")), self._num(b.get("limit_jpy_kwh"))
            if not isinstance(slot, int) or isinstance(slot, bool) or not 1 <= slot <= S or side not in ("buy", "sell") \
                    or qty is None or lim is None:
                viol.add("jepx_bounds", f"{date}", f"{date}: malformed bid {str(b)[:120]}")
                continue
            if qty < 0 or lim < self.floor - 1e-9 or lim > self.cap + 1e-9:
                viol.add("jepx_bounds", f"{date} s{slot}", f"{date} slot {slot}: qty {qty} / limit {lim} outside JEPX bounds "
                                                          f"[0.01, 999.99] JPY/kWh")
                continue
            count[slot - 1] += 1
            q = math.floor(qty / self.lot + 1e-9) * self.lot
            lim = round(lim, 2)
            if q <= 0:
                continue
            (buys if side == "buy" else sells)[slot - 1].append((q, lim))
        if (count > MAX_BIDS_PER_SLOT).any():
            viol.add("jepx_bounds", date, f"{date}: more than {MAX_BIDS_PER_SLOT} bids in a slot")
        # plan feasibility from the context's SOC
        s = soc
        dis = 0.0
        for t in range(S):
            mw = plan[t]
            if abs(mw) > self.P + 1e-6:
                viol.add("bess_limits", f"{date} plan s{t + 1}", f"{date} DA plan slot {t + 1}: {mw:.1f} MW > rating")
            s = self.soc_after(s, mw)
            if s < self.soc_min - SOC_TOL or s > self.soc_max + SOC_TOL:
                viol.add("bess_limits", f"{date} plan s{t + 1}", f"{date} DA plan slot {t + 1}: SOC {s:.1f} MWh out of 10-95%")
                s = min(max(s, self.soc_min), self.soc_max)
            dis += max(mw, 0) * 0.5
        if dis > self.max_daily_dis + SOC_TOL:
            viol.add("bess_limits", f"{date} plan", f"{date} DA plan discharges {dis:.0f} MWh > 2 cycles")
        # naked selling in the DA book
        pv_sur = np.maximum(np.array(ctx["forecast"]["pv_mw"]["p50"]) - np.array(ctx["forecast"]["demand_mw"]["p10"]), 0) * 0.5
        for t in range(S):
            sold = sum(q for q, _ in sells[t])
            allowed = max(plan[t], 0.0) * 0.5 + pv_sur[t] + 0.05
            if sold > allowed:
                viol.add("naked_selling", f"{date} s{t + 1}", f"{date} slot {t + 1}: DA sells {sold:.1f} MWh > BESS discharge "
                                                            f"+ PV surplus {allowed:.1f} MWh")
        return buys, sells, plan

    def _validate_id(self, i: int, t: int, out, viol: Violations):
        date = str(self.a["day_date"][i])
        if not isinstance(out, dict) or "orders" not in out or "bess_mw" not in out:
            raise FormatError("adjust_intraday must return {'orders': [...], 'bess_mw': float}")
        mw = self._num(out["bess_mw"])
        if mw is None:
            raise FormatError("bess_mw must be a finite number")
        if not isinstance(out["orders"], list):
            raise FormatError("orders must be a list")
        orders = []
        for o in out["orders"]:
            if not isinstance(o, dict):
                raise FormatError("each order must be a dict {side, qty_mwh, limit_jpy_kwh}")
            side, qty, lim = o.get("side"), self._num(o.get("qty_mwh")), self._num(o.get("limit_jpy_kwh"))
            if side not in ("buy", "sell") or qty is None or lim is None or qty < 0 or lim < self.floor - 1e-9 or lim > self.cap + 1e-9:
                viol.add("jepx_bounds", f"{date} s{t + 1}", f"{date} slot {t + 1}: intraday order {str(o)[:100]} outside bounds")
                continue
            q = math.floor(qty / self.lot + 1e-9) * self.lot
            if q > 0:
                orders.append((side, q, round(lim, 2)))
        return orders, mw


class FormatError(ValueError):
    pass
