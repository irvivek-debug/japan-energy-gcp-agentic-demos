"""Contract risk tools: customer lookup, portfolio exposure, deviation-band breaches, margin at risk, tariff proposals.

Definitions (also in docs/TECHNICAL_DESIGN.md section 5):
  deviation breach (bandwidth tariff): |actual - nominated| > band% x nominated in a delivered 30-minute slot
  excess deviation energy: max(|actual - nominated| - band% x nominated, 0)
  deviation cost: excess deviation energy x imbalance price of that slot (chargeable under the deviation clause)
  margin at risk: unhedged price-exposed volume x forward baseload price x price shock
    price-exposed = fixed and bandwidth tariffs (market-linked tariffs pass spot through)
    hedged volume per day = active baseload hedge MW x 24 h (capped at the exposed volume)
"""
from __future__ import annotations

from datetime import date as _date, timedelta
from typing import Any, Optional

from ..clock import NOW, SCENARIO_DATE
from ..store import STORE, src
from ._common import check_date, err, r2, record_proposal, safe_tool, short_hash

NOTICE_DAYS = 30
EXPOSED = ("fixed", "bandwidth")


@safe_tool
def find_customer(query: str) -> dict:
    """Find retail customers by id (C-NNNN) or by part of the name, returning contract terms: segment, tariff type,
    deviation band, contracted kW, expected margin, DR enrolment, essential-facility flag and CFE contract.

    Args:
      query: Customer id such as C-0051, or a name fragment such as "Kanagawa Cold".
    """
    q = str(query).strip()
    if not q:
        return err("query is empty")
    rows = STORE.query(
        "SELECT * FROM {t:customers} WHERE customer_id = @id OR LOWER(name) LIKE @pat ORDER BY customer_id LIMIT 10",
        id=q.upper(), pat=f"%{q.lower()}%",
    )
    if not rows:
        return {"status": "not_found", "query": q, "source": src("customers")}
    return {"status": "ok", "matches": [{k: r2(v) if isinstance(v, float) else v for k, v in r.items()} for r in rows],
            "source": src("customers")}


def _expected_mwh(d: str) -> tuple[dict, str]:
    """Expected MWh per customer for a date (load table up to the scenario day, daily forecast after)."""
    if d <= SCENARIO_DATE:
        rows = STORE.query(
            "SELECT customer_id, SUM(COALESCE(actual_kwh, forecast_latest_kwh)) / 1000.0 AS mwh "
            "FROM {t:customer_load_30min} WHERE date = @d GROUP BY customer_id", d=d)
        return {r["customer_id"]: r["mwh"] for r in rows}, "customer_load_30min"
    rows = STORE.query("SELECT customer_id, forecast_mwh AS mwh FROM {t:customer_forecast_daily} WHERE date = @d", d=d)
    return {r["customer_id"]: r["mwh"] for r in rows}, "customer_forecast_daily"


@safe_tool
def get_portfolio_exposure(date: str) -> dict:
    """Portfolio view for one date by tariff type: customers, contracted MW, expected MWh, average margin JPY/kWh,
    which volumes carry wholesale price exposure, and the baseload hedge cover for that day.

    Args:
      date: Date YYYY-MM-DD (load data 2026-08-01..2026-08-19, daily forecast 2026-08-20..2026-08-31).
    """
    e = check_date(date)
    if e:
        return err(e)
    vol, table = _expected_mwh(date)
    if not vol:
        return {"status": "not_found", "date": date, "note": "coverage is 2026-08-01..2026-08-31",
                "source": src("customer_load_30min", "customer_forecast_daily")}
    cust = STORE.query("SELECT customer_id, segment, tariff_type, contracted_kw, margin_jpy_kwh FROM {t:customers}")
    hedge = STORE.query("SELECT SUM(mw) AS mw FROM {t:hedge_book} WHERE start_date <= @d AND end_date >= @d", d=date)
    hedge_mw = float(hedge[0]["mw"] or 0) if hedge else 0.0
    by: dict[str, dict] = {}
    seg: dict[str, float] = {}
    for c in cust:
        v = float(vol.get(c["customer_id"], 0) or 0)
        b = by.setdefault(c["tariff_type"], {"customers": 0, "contracted_mw": 0.0, "expected_mwh": 0.0, "_m": 0.0})
        b["customers"] += 1
        b["contracted_mw"] += c["contracted_kw"] / 1000
        b["expected_mwh"] += v
        b["_m"] += v * c["margin_jpy_kwh"]
        seg[c["segment"]] = seg.get(c["segment"], 0) + v
    for k, b in by.items():
        b["avg_margin_jpy_kwh"] = r2(b.pop("_m") / b["expected_mwh"], 2) if b["expected_mwh"] else None
        b["contracted_mw"] = r2(b["contracted_mw"], 1)
        b["expected_mwh"] = r2(b["expected_mwh"], 1)
        b["wholesale_price_exposure"] = "retailer bears spot risk" if k in EXPOSED else "passed through to customer"
    exposed = sum(by[k]["expected_mwh"] for k in by if k in EXPOSED)
    hedged = min(exposed, hedge_mw * 24)
    return {
        "status": "ok", "date": date, "volume_basis": table, "by_tariff_type": by,
        "by_segment_mwh": {k: r2(v, 1) for k, v in sorted(seg.items(), key=lambda x: -x[1])},
        "price_exposed_mwh": r2(exposed, 1), "hedge_mw": r2(hedge_mw, 0), "hedged_mwh": r2(hedged, 1),
        "hedge_cover_pct": r2(100 * hedged / exposed, 1) if exposed else None,
        "unhedged_exposed_mwh": r2(exposed - hedged, 1),
        "source": src("customers", table, "hedge_book"),
    }


def breach_rows(from_date: str, to_date: str, band_override: Optional[dict] = None) -> list[dict]:
    return STORE.query(
        """
        WITH d AS (
          SELECT l.customer_id, l.date, l.slot, l.actual_kwh, l.nominated_kwh, c.deviation_band_pct,
                 ABS(l.actual_kwh - l.nominated_kwh) AS dev_kwh,
                 c.deviation_band_pct / 100.0 * l.nominated_kwh AS band_kwh,
                 i.imbalance_price_jpy_kwh AS price
          FROM {t:customer_load_30min} l
          JOIN {t:customers} c ON c.customer_id = l.customer_id
          JOIN {t:imbalance_30min} i ON i.date = l.date AND i.slot = l.slot
          WHERE c.tariff_type = 'bandwidth' AND l.is_actual = TRUE AND l.date >= @f AND l.date <= @t
        )
        SELECT customer_id, COUNT(*) AS slots_evaluated,
               SUM(CASE WHEN dev_kwh > band_kwh THEN 1 ELSE 0 END) AS breach_slots,
               SUM(CASE WHEN dev_kwh > band_kwh AND actual_kwh > nominated_kwh THEN 1 ELSE 0 END) AS over_slots,
               SUM(GREATEST(dev_kwh - band_kwh, 0)) / 1000.0 AS excess_mwh,
               SUM(GREATEST(dev_kwh - band_kwh, 0) * price) AS deviation_cost_jpy,
               MAX(deviation_band_pct) AS band_pct
        FROM d GROUP BY customer_id
        """,
        f=from_date, t=to_date,
    )


@safe_tool
def get_deviation_breaches(from_date: str, to_date: str) -> dict:
    """Deviation-band breaches for bandwidth-tariff customers over delivered slots in a date range: breach count and
    rate, excess energy beyond the band (MWh) and the deviation cost at the imbalance price (JPY), worst customers
    first, plus the hour-of-day pattern for the worst customer.

    Args:
      from_date: First date YYYY-MM-DD (load data starts 2026-08-01).
      to_date: Last date YYYY-MM-DD, inclusive (metered data ends 2026-08-19 15:30).
    """
    e = check_date(from_date) or check_date(to_date)
    if e:
        return err(e)
    rows = breach_rows(from_date, to_date)
    if not rows:
        return {"status": "not_found", "note": "no metered bandwidth-tariff slots in range",
                "source": src("customer_load_30min", "customers", "imbalance_30min")}
    names = {r["customer_id"]: r["name"] for r in STORE.query("SELECT customer_id, name FROM {t:customers} WHERE tariff_type = 'bandwidth'")}
    out = []
    for r in rows:
        out.append({"customer_id": r["customer_id"], "name": names.get(r["customer_id"]), "band_pct": r2(r["band_pct"], 1),
                    "slots_evaluated": int(r["slots_evaluated"]), "breach_slots": int(r["breach_slots"]),
                    "breach_rate_pct": r2(100 * r["breach_slots"] / r["slots_evaluated"], 1),
                    "over_consumption_breaches": int(r["over_slots"]), "excess_mwh": r2(r["excess_mwh"], 2),
                    "deviation_cost_jpy": r2(r["deviation_cost_jpy"], 0)})
    out.sort(key=lambda x: -x["deviation_cost_jpy"])
    breached = [o for o in out if o["breach_slots"] > 0]
    total_cost = sum(o["deviation_cost_jpy"] for o in out)
    worst = breached[0] if breached else None
    pattern = []
    if worst:
        pattern = STORE.query(
            """
            SELECT l.slot AS slot,
                   SUM(CASE WHEN ABS(l.actual_kwh - l.nominated_kwh) > c.deviation_band_pct / 100.0 * l.nominated_kwh
                            THEN 1 ELSE 0 END) AS breaches, COUNT(*) AS slots
            FROM {t:customer_load_30min} l JOIN {t:customers} c ON c.customer_id = l.customer_id
            WHERE l.customer_id = @cid AND l.is_actual = TRUE AND l.date >= @f AND l.date <= @t
            GROUP BY l.slot ORDER BY l.slot
            """,
            cid=worst["customer_id"], f=from_date, t=to_date,
        )
        hours: dict[int, list[int]] = {}
        for p in pattern:
            h = (int(p["slot"]) - 1) // 2
            hv = hours.setdefault(h, [0, 0])
            hv[0] += int(p["breaches"])
            hv[1] += int(p["slots"])
        pattern = [{"hour": h, "breach_rate_pct": r2(100 * v[0] / v[1], 1)} for h, v in sorted(hours.items())]
    return {
        "status": "ok", "from_date": from_date, "to_date": to_date,
        "definition": "Breach = |actual - nominated| > band% x nominated in a metered 30-minute slot; cost = excess "
                      "energy beyond the band x imbalance price of that slot.",
        "bandwidth_customers_evaluated": len(out), "customers_with_breaches": len(breached),
        "total_breach_slots": sum(o["breach_slots"] for o in out),
        "total_excess_mwh": r2(sum(o["excess_mwh"] for o in out), 2), "total_deviation_cost_jpy": r2(total_cost, 0),
        "worst_customer_share_of_cost_pct": r2(100 * worst["deviation_cost_jpy"] / total_cost, 1) if worst and total_cost else None,
        "top_customers": breached[:8], "worst_customer_hourly_breach_rate": pattern,
        "source": src("customer_load_30min", "customers", "imbalance_30min"),
    }


def margin_at_risk(from_date: str, to_date: str, price_shock_pct: float) -> dict:
    fc = STORE.query(
        "SELECT f.customer_id, f.date, f.forecast_mwh, c.name, c.segment, c.tariff_type, c.margin_jpy_kwh "
        "FROM {t:customer_forecast_daily} f JOIN {t:customers} c ON c.customer_id = f.customer_id "
        "WHERE f.date >= @f AND f.date <= @t", f=from_date, t=to_date)
    fwd = {r["date"]: r["baseload_jpy_kwh"] for r in STORE.query(
        "SELECT date, baseload_jpy_kwh FROM {t:forward_curve_daily} WHERE date >= @f AND date <= @t", f=from_date, t=to_date)}
    hedges = STORE.query("SELECT hedge_id, start_date, end_date, mw, price_jpy_kwh FROM {t:hedge_book}")
    days = sorted({r["date"] for r in fc})
    shock = float(price_shock_pct) / 100.0
    exposed_d = {d: 0.0 for d in days}
    for r in fc:
        if r["tariff_type"] in EXPOSED:
            exposed_d[r["date"]] += r["forecast_mwh"]
    hedged_d = {d: min(exposed_d[d], sum(h["mw"] for h in hedges if h["start_date"] <= d <= h["end_date"]) * 24) for d in days}
    share_unhedged = {d: (1 - hedged_d[d] / exposed_d[d]) if exposed_d[d] else 0 for d in days}
    per_c: dict[str, dict] = {}
    for r in fc:
        c = per_c.setdefault(r["customer_id"], {"customer_id": r["customer_id"], "name": r["name"], "segment": r["segment"],
                                                "tariff_type": r["tariff_type"], "mwh": 0.0, "base_margin_jpy": 0.0,
                                                "margin_loss_jpy": 0.0})
        c["mwh"] += r["forecast_mwh"]
        c["base_margin_jpy"] += r["forecast_mwh"] * 1000 * r["margin_jpy_kwh"]
        if r["tariff_type"] in EXPOSED:
            c["margin_loss_jpy"] += r["forecast_mwh"] * share_unhedged[r["date"]] * 1000 * fwd[r["date"]] * shock
    mar = sum(c["margin_loss_jpy"] for c in per_c.values())
    base = sum(c["base_margin_jpy"] for c in per_c.values())
    return {"days": days, "exposed_d": exposed_d, "hedged_d": hedged_d, "fwd": fwd, "per_c": per_c, "mar": mar, "base": base}


@safe_tool
def compute_margin_at_risk(from_date: str, to_date: str, price_shock_pct: float) -> dict:
    """Margin at risk if the Tokyo wholesale price rises by a given percentage over a future period: price-exposed
    (fixed and bandwidth tariff) volume not covered by baseload hedges, valued at the forward baseload price times the
    shock. Returns the portfolio total, the expected margin before and after, and the customers hit hardest.

    Args:
      from_date: First date YYYY-MM-DD (forecast coverage 2026-08-20..2026-08-31; "rest of August" = 2026-08-20 to 2026-08-31).
      to_date: Last date YYYY-MM-DD, inclusive.
      price_shock_pct: Price shock in percent, for example 40 for +40 %.
    """
    e = check_date(from_date) or check_date(to_date)
    if e:
        return err(e)
    if from_date > to_date:
        return err("from_date must be on or before to_date")
    m = margin_at_risk(from_date, to_date, price_shock_pct)
    if not m["days"]:
        return {"status": "not_found", "note": "forecast coverage is 2026-08-20..2026-08-31",
                "source": src("customer_forecast_daily")}
    exposed = sum(m["exposed_d"].values())
    hedged = sum(m["hedged_d"].values())
    per = list(m["per_c"].values())
    neg = [c for c in per if c["base_margin_jpy"] - c["margin_loss_jpy"] < 0]
    top = sorted(per, key=lambda c: -c["margin_loss_jpy"])[:8]
    by_t: dict[str, dict] = {}
    for c in per:
        b = by_t.setdefault(c["tariff_type"], {"mwh": 0.0, "margin_loss_jpy": 0.0})
        b["mwh"] += c["mwh"]
        b["margin_loss_jpy"] += c["margin_loss_jpy"]
    return {
        "status": "ok", "from_date": m["days"][0], "to_date": m["days"][-1], "days": len(m["days"]),
        "price_shock_pct": float(price_shock_pct),
        "margin_at_risk_jpy": r2(m["mar"], 0),
        "expected_margin_before_jpy": r2(m["base"], 0), "expected_margin_after_jpy": r2(m["base"] - m["mar"], 0),
        "price_exposed_mwh": r2(exposed, 1), "hedged_mwh": r2(hedged, 1), "unhedged_exposed_mwh": r2(exposed - hedged, 1),
        "hedge_cover_pct": r2(100 * hedged / exposed, 1) if exposed else None,
        "avg_forward_baseload_jpy_kwh": r2(sum(m["fwd"].values()) / len(m["fwd"]), 2),
        "by_tariff_type": {k: {"mwh": r2(v["mwh"], 1), "margin_loss_jpy": r2(v["margin_loss_jpy"], 0)} for k, v in by_t.items()},
        "customers_negative_margin_after_shock": len(neg),
        "top_customers_by_margin_loss": [{"customer_id": c["customer_id"], "name": c["name"], "tariff_type": c["tariff_type"],
                                          "mwh": r2(c["mwh"], 1), "margin_loss_jpy": r2(c["margin_loss_jpy"], 0),
                                          "margin_after_jpy": r2(c["base_margin_jpy"] - c["margin_loss_jpy"], 0)} for c in top],
        "method": "unhedged exposed MWh x forward baseload JPY/kWh x shock; market-linked tariffs pass spot through; "
                  "hedges pro rata across exposed customers",
        "source": src("customer_forecast_daily", "customers", "forward_curve_daily", "hedge_book"),
    }


@safe_tool
def propose_tariff_adjustment(customer_id: str, adjustment_type: str, new_value: float, effective_date: str = "",
                              tool_context: Optional[Any] = None) -> dict:
    """Create a PENDING tariff change proposal for one customer with its quantified impact. Types: "widen_band"
    (new_value = new deviation band %), "risk_premium" (new_value = JPY/kWh added to the energy price) or
    "switch_to_market_linked" (new_value = adder over spot in JPY/kWh). The change is effective no earlier than 30
    days after notice. Nothing changes until a person approves with Hold-to-Confirm and the customer agrees.

    Args:
      customer_id: Customer id, for example C-0051.
      adjustment_type: One of widen_band, risk_premium, switch_to_market_linked.
      new_value: Band % for widen_band, or JPY/kWh for the other types.
      effective_date: Optional YYYY-MM-DD; defaults to the first day of the month after 30 days notice.
    """
    types = ("widen_band", "risk_premium", "switch_to_market_linked")
    if adjustment_type not in types:
        return err(f"adjustment_type must be one of {types}")
    c = STORE.query("SELECT * FROM {t:customers} WHERE customer_id = @id", id=str(customer_id).upper())
    if not c:
        return err(f"unknown customer {customer_id}")
    c = c[0]
    earliest = _date.fromisoformat(NOW[:10]) + timedelta(days=NOTICE_DAYS)
    if not effective_date:
        nm = earliest.replace(day=1) + timedelta(days=32)
        eff = earliest if earliest.day == 1 else nm.replace(day=1)
        effective_date = eff.isoformat()
    elif check_date(effective_date):
        return err(check_date(effective_date))
    if effective_date < earliest.isoformat():
        return {"status": "rejected_by_policy", "error": f"effective_date {effective_date} is inside the 30-day notice "
                f"period; earliest allowed is {earliest.isoformat()} [desk_policy_guide.md Section 10]",
                "source": ["desk_policy_guide.md Section 10"]}
    mtd = breach_rows("2026-08-01", NOW[:10])
    cur = next((r for r in mtd if r["customer_id"] == c["customer_id"]), None)
    impact: dict[str, Any] = {"current_tariff": c["tariff_type"], "current_band_pct": c["deviation_band_pct"],
                              "current_margin_jpy_kwh": c["margin_jpy_kwh"]}
    vol = STORE.query("SELECT SUM(actual_kwh) / 1000.0 AS mwh FROM {t:customer_load_30min} WHERE customer_id = @id AND is_actual = TRUE",
                      id=c["customer_id"])[0]["mwh"] or 0
    if cur:
        impact.update({"mtd_breach_slots": int(cur["breach_slots"]), "mtd_excess_mwh": r2(cur["excess_mwh"], 2),
                       "mtd_deviation_cost_jpy": r2(cur["deviation_cost_jpy"], 0)})
    if adjustment_type == "widen_band":
        if c["tariff_type"] != "bandwidth":
            return err("widen_band applies only to bandwidth tariffs")
        nb = float(new_value)
        rows = STORE.query(
            """
            SELECT SUM(CASE WHEN ABS(l.actual_kwh - l.nominated_kwh) > @nb / 100.0 * l.nominated_kwh THEN 1 ELSE 0 END) AS breaches,
                   SUM(GREATEST(ABS(l.actual_kwh - l.nominated_kwh) - @nb / 100.0 * l.nominated_kwh, 0)) / 1000.0 AS excess_mwh,
                   SUM((GREATEST(ABS(l.actual_kwh - l.nominated_kwh) - c.deviation_band_pct / 100.0 * l.nominated_kwh, 0)
                        - GREATEST(ABS(l.actual_kwh - l.nominated_kwh) - @nb / 100.0 * l.nominated_kwh, 0)) * i.imbalance_price_jpy_kwh) AS absorbed_jpy
            FROM {t:customer_load_30min} l JOIN {t:customers} c ON c.customer_id = l.customer_id
            JOIN {t:imbalance_30min} i ON i.date = l.date AND i.slot = l.slot
            WHERE l.customer_id = @id AND l.is_actual = TRUE
            """, nb=nb, id=c["customer_id"])[0]
        premium = (rows["absorbed_jpy"] or 0) / (vol * 1000) if vol else 0
        impact.update({"new_band_pct": nb, "mtd_breach_slots_with_new_band": int(rows["breaches"] or 0),
                       "mtd_excess_mwh_with_new_band": r2(rows["excess_mwh"], 2),
                       "deviation_cost_desk_would_absorb_mtd_jpy": r2(rows["absorbed_jpy"], 0),
                       "break_even_premium_jpy_kwh": r2(premium, 2)})
        summary = f"Widen {c['name']} deviation band from +/-{c['deviation_band_pct']:.0f}% to +/-{nb:.0f}% with a " \
                  f"{premium:.2f} JPY/kWh premium, effective {effective_date}"
    elif adjustment_type == "risk_premium":
        impact.update({"premium_jpy_kwh": float(new_value), "mtd_volume_mwh": r2(vol, 1),
                       "mtd_equivalent_revenue_jpy": r2(vol * 1000 * float(new_value), 0)})
        summary = f"Add a {float(new_value):.2f} JPY/kWh risk premium to {c['name']}, effective {effective_date}"
    else:
        impact.update({"new_market_adder_jpy_kwh": float(new_value)})
        summary = f"Move {c['name']} to a market-linked tariff at spot + {float(new_value):.2f} JPY/kWh, effective {effective_date}"
    details = {"customer_id": c["customer_id"], "customer_name": c["name"], "adjustment_type": adjustment_type,
               "new_value": float(new_value), "effective_date": effective_date, "impact": impact,
               "customer_consent_required": True, "notice_days": NOTICE_DAYS}
    action = {"id": f"PA-TAR-{c['customer_id']}-{short_hash(details)}", "kind": "tariff_adjustment",
              "created_by": "contract_risk_agent", "summary": summary, "details": details, "risk": "medium",
              "reasoning": [f"Month-to-date breaches: {impact.get('mtd_breach_slots', 0)} slots, deviation cost "
                            f"{impact.get('mtd_deviation_cost_jpy', 0):,.0f} JPY",
                            "Effective date respects 30-day notice; customer agreement required"],
              "sources": src("customers", "customer_load_30min", "imbalance_30min") + ["desk_policy_guide.md Section 10"],
              "requires": "hold_to_confirm"}
    record_proposal(tool_context, action)
    return {"status": "pending_approval", "pending_action": action,
            "note": "Pending only. No contract has changed. Needs Hold-to-Confirm and the customer's agreement.",
            "source": action["sources"][:3]}
