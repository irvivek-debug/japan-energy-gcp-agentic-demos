"""Demand-response baseline and settlement math (pure, deterministic, unit-tested).

Baseline method (per the plant's aggregator contract, see data/docs_corpus/dr_contract_summary.md):
  * "High 4 of 5": take the 5 most recent eligible weekdays before the event day (weekends, public
    holidays, plant shutdown days and previous DR event days are excluded), rank them by their average
    receiving-point load over the event slots, keep the highest 4, and average them slot by slot.
  * Same-day adjustment: add the average difference between the event day and the 4 selected days over
    the adjustment slots (4 slots ending 1 hour before the event starts, i.e. start-6 .. start-3).
    The adjustment is computed on load net of BESS (import + BESS discharge - BESS charge), so battery
    charging before an event cannot inflate the baseline.
  * Delivered reduction = baseline - actual receiving-point import, averaged over the event slots.
"""
from __future__ import annotations

from statistics import mean


def adjustment_slots(start_slot: int) -> list[int]:
    return [s for s in range(start_slot - 6, start_slot - 2) if s >= 1]


def select_baseline_days(eligible_dates_desc: list[str], window_avg_by_date: dict[str, float],
                         n_candidates: int = 5, n_keep: int = 4) -> tuple[list[str], list[str]]:
    """Return (candidate_days, selected_days) for High-N-of-M.

    eligible_dates_desc: eligible dates sorted most recent first (already filtered for weekday/holiday/event).
    window_avg_by_date: average load over the event slots for each date.
    """
    candidates = [d for d in eligible_dates_desc if d in window_avg_by_date][:n_candidates]
    ranked = sorted(candidates, key=lambda d: (-window_avg_by_date[d], d))
    return candidates, sorted(ranked[:n_keep])


def high_4_of_5_baseline(
    load_by_date: dict[str, dict[int, float]],
    net_of_bess_by_date: dict[str, dict[int, float]],
    eligible_dates_desc: list[str],
    event_slots: list[int],
    event_day_net_of_bess: dict[int, float] | None,
    same_day_adjustment: bool = True,
) -> dict:
    """Compute the High 4 of 5 baseline with optional same-day adjustment.

    load_by_date: receiving-point import kW per slot for historical dates.
    net_of_bess_by_date: import + bess_kw per slot (used only for the adjustment).
    event_day_net_of_bess: event-day import + bess_kw for the adjustment slots (actual or forecast).
    """
    if not event_slots:
        raise ValueError("event_slots must not be empty")
    window_avg = {d: mean(load_by_date[d][s] for s in event_slots) for d in eligible_dates_desc
                  if d in load_by_date and all(s in load_by_date[d] for s in event_slots)}
    candidates, selected = select_baseline_days(eligible_dates_desc, window_avg)
    if len(selected) < 4:
        raise ValueError(f"not enough eligible baseline days: {candidates}")
    raw = {s: mean(load_by_date[d][s] for d in selected) for s in event_slots}
    adj_s = adjustment_slots(event_slots[0])
    adjustment = 0.0
    if same_day_adjustment and event_day_net_of_bess and adj_s:
        ref = {s: mean(net_of_bess_by_date[d][s] for d in selected) for s in adj_s}
        diffs = [event_day_net_of_bess[s] - ref[s] for s in adj_s if s in event_day_net_of_bess]
        adjustment = mean(diffs) if diffs else 0.0
    baseline = {s: raw[s] + adjustment for s in event_slots}
    return {
        "candidate_days": candidates,
        "selected_days": selected,
        "window_avg_by_candidate_kw": {d: round(window_avg[d], 1) for d in candidates},
        "baseline_raw_kw": {s: round(v, 1) for s, v in raw.items()},
        "adjustment_slots": adj_s,
        "same_day_adjustment_kw": round(adjustment, 1),
        "baseline_kw": {s: round(v, 1) for s, v in baseline.items()},
        "baseline_avg_kw": round(mean(baseline.values()), 1),
    }


def settle_event(requested_kw: float, baseline_kw: dict[int, float], actual_kw: dict[int, float],
                 energy_rate_jpy_kwh: float, penalty_rate_jpy_kwh: float,
                 payment_cap_ratio: float = 1.0) -> dict:
    """Settle one DR event from baseline and actual (or planned) receiving-point load."""
    slots = sorted(baseline_kw)
    hours = len(slots) * 0.5
    per_slot = {s: baseline_kw[s] - actual_kw[s] for s in slots}
    delivered_avg = mean(per_slot.values())
    delivered_kwh = delivered_avg * hours
    requested_kwh = requested_kw * hours
    paid_kwh = min(max(delivered_kwh, 0.0), requested_kwh * payment_cap_ratio)
    shortfall_kwh = max(0.0, requested_kwh - delivered_kwh)
    payment = paid_kwh * energy_rate_jpy_kwh
    penalty = shortfall_kwh * penalty_rate_jpy_kwh
    return {
        "hours": hours,
        "baseline_avg_kw": round(mean(baseline_kw[s] for s in slots), 1),
        "actual_avg_kw": round(mean(actual_kw[s] for s in slots), 1),
        "delivered_by_slot_kw": {s: round(v, 1) for s, v in per_slot.items()},
        "delivered_avg_kw": round(delivered_avg, 1),
        "delivered_min_kw": round(min(per_slot.values()), 1),
        "delivered_kwh": round(delivered_kwh, 1),
        "requested_kwh": round(requested_kwh, 1),
        "performance_pct": round(100.0 * delivered_avg / requested_kw, 1) if requested_kw else None,
        "paid_kwh": round(paid_kwh, 1),
        "shortfall_kwh": round(shortfall_kwh, 1),
        "payment_jpy": round(payment),
        "penalty_jpy": round(penalty),
        "net_jpy": round(payment - penalty),
    }
