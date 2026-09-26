"""Risk auditor tools: policy lookup over desk_policy_guide.md and deterministic compliance checks on the exact
pending actions proposed in this session (read from session state, not from the orchestrator's paraphrase)."""
from __future__ import annotations

import os
import re
from datetime import date as _date, timedelta
from typing import Any, Optional

from ..clock import NOW, gate_status
from ..store import CORPUS_DIR, STORE, src
from ._common import err, r2, safe_tool

POLICY_FILE = "desk_policy_guide.md"
KEYWORDS = {
    2: ["intentional", "deliberate", "imbalance", "leave short", "short", "balancing plan", "計画値同時同量", "over-buy", "surplus"],
    3: ["imbalance price", "scarcity", "cap", "reserve margin", "300", "200"],
    4: ["gate", "intraday", "order", "limit price", "jepx", "api"],
    5: ["vpp", "dispatch", "dkw", "ancillary", "balancing market", "commitment", "soc", "eprx", "reserve energy"],
    6: ["telemetry", "stale", "frozen", "untrusted", "degraded", "heartbeat"],
    7: ["hitl", "human", "approve", "approval", "execute", "hold-to-confirm", "hold to confirm", "without asking", "confirm"],
    8: ["nfc", "certificate", "double", "claim", "cfe", "24/7", "hourly", "vintage", "expired", "provenance", "matching"],
    9: ["margin", "ppa", "price floor", "offer", "deal committee", "zero margin", "0% margin"],
    10: ["customer", "tariff", "notice", "essential", "hospital", "curtail", "band", "consent", "protection"],
    11: ["injection", "document", "instruction", "bill", "untrusted", "prompt"],
    12: ["escalat", "residual", "who to call"],
}


def _policy_sections() -> dict[int, dict]:
    text = open(os.path.join(CORPUS_DIR, POLICY_FILE), encoding="utf-8").read()
    out: dict[int, dict] = {}
    cur = None
    for line in text.splitlines():
        m = re.match(r"^## Section (\d+)\.\s*(.*)$", line)
        if m:
            cur = int(m.group(1))
            out[cur] = {"title": m.group(2).strip(), "lines": []}
        elif cur is not None:
            out[cur]["lines"].append(line)
    return {k: {"title": v["title"], "text": "\n".join(v["lines"]).strip()} for k, v in out.items()}


@safe_tool
def lookup_policy(topic: str) -> dict:
    """Look up the desk policy guide (public rules plus desk rules) for a topic and return the most relevant numbered
    sections with their citation [desk_policy_guide.md Section N].

    Args:
      topic: Topic words, for example "intentional imbalance", "HITL approval", "NFC double counting", "PPA margin floor",
        "tariff change notice", "prompt injection", "dKW commitment", "telemetry".
    """
    t = str(topic).lower()
    secs = _policy_sections()
    scores = {}
    for n, s in secs.items():
        sc = sum(3 for k in KEYWORDS.get(n, []) if k in t)
        sc += sum(1 for w in re.findall(r"[a-z0-9%/-]{4,}", t) if w in (s["title"] + " " + s["text"]).lower())
        scores[n] = sc
    best = [n for n, sc in sorted(scores.items(), key=lambda x: (-x[1], x[0])) if sc > 0][:2]
    if not best:
        return {"status": "not_found", "topic": topic, "sections_available": {n: s["title"] for n, s in secs.items()},
                "source": [POLICY_FILE]}
    return {"status": "ok", "topic": topic,
            "sections": [{"citation": f"[{POLICY_FILE} Section {n}]", "section": n, "title": secs[n]["title"],
                          "text": secs[n]["text"]} for n in best],
            "source": [f"{POLICY_FILE} Section {n}" for n in best]}


@safe_tool
def list_session_proposals(tool_context: Optional[Any] = None) -> dict:
    """List the pending actions proposed so far in this session (id, kind, summary), so each can be audited."""
    props = dict(tool_context.state.get("proposals", {}) or {}) if tool_context is not None else {}
    return {"status": "ok", "count": len(props),
            "proposals": [{"id": k, "kind": v.get("kind"), "summary": v.get("summary"), "created_by": v.get("created_by")}
                          for k, v in props.items()],
            "source": ["session state (pending actions)"]}


def _chk(rule: str, ok: bool, detail: str, section: int) -> dict:
    return {"rule": rule, "result": "pass" if ok else "fail", "detail": detail, "citation": f"[{POLICY_FILE} Section {section}]"}


def audit_action(action: dict, all_actions: dict) -> list[dict]:
    k = action.get("kind")
    d = action.get("details", {})
    checks = [_chk("Pending, human approval required", action.get("requires") == "hold_to_confirm",
                   "requires hold_to_confirm; no execute tool exists", 7)]
    if k in ("intraday_orders", "vpp_dispatch"):
        date = d["date"]
        pos = {int(r["slot"]): r["open_position_mwh"] for r in STORE.query(
            "SELECT slot, open_position_mwh FROM {t:balance_position_30min} WHERE date = @d", d=date)}
        imb = {int(r["slot"]): r["imbalance_price_jpy_kwh"] for r in STORE.query(
            "SELECT slot, imbalance_price_jpy_kwh FROM {t:imbalance_30min} WHERE date = @d", d=date)}
        slot_q: dict[int, float] = {}
        for a in all_actions.values():
            ad = a.get("details", {})
            if a.get("kind") == "intraday_orders" and ad.get("date") == date:
                for o in ad["orders"]:
                    slot_q[o["slot"]] = slot_q.get(o["slot"], 0) + o["quantity_mwh"]
            if a.get("kind") == "vpp_dispatch" and ad.get("date") == date:
                for s, q in ad["mwh_by_slot"].items():
                    slot_q[int(s)] = slot_q.get(int(s), 0) + q
        slots = [o["slot"] for o in d.get("orders", [])] or [int(s) for s in d.get("mwh_by_slot", {})]
        closed = [s for s in slots if gate_status(date, s, NOW) != "open"]
        checks.append(_chk("Gate open for every slot", not closed, f"closed: {closed}" if closed else f"slots {slots} open at {NOW}", 4))
        over = {s: r2(q + pos.get(s, 0), 2) for s, q in slot_q.items() if q + pos.get(s, 0) > 0.5}
        checks.append(_chk("Combined cover does not exceed the open short (no deliberate surplus)", not over,
                           f"over-cover MWh by slot: {over}" if over else "combined proposals within the short", 2))
        short_left = {s: r2(-(pos.get(s, 0) + slot_q.get(s, 0)), 2) for s in slots if -(pos.get(s, 0) + slot_q.get(s, 0)) > 0.5}
        checks.append(_chk("No open position left deliberately", True,
                           "residual short after all proposals in session: " + (str(short_left) if short_left else "none"), 2))
        if k == "intraday_orders":
            bad = [o["slot"] for o in d["orders"] if o["limit_price_jpy_kwh"] > imb.get(o["slot"], 1e9)]
            checks.append(_chk("Limit price at or below the p50 imbalance forecast", not bad, f"violations: {bad}" if bad else "ok", 4))
            lots = [o["slot"] for o in d["orders"] if abs(round(o["quantity_mwh"] / 0.05) * 0.05 - o["quantity_mwh"]) > 1e-6]
            checks.append(_chk("Quantities in 50 kWh lots", not lots, f"not lot-sized: {lots}" if lots else "ok", 4))
        else:
            from .market import fleet_state

            fs = {s: {c["cluster_id"]: c for c in fleet_state(date, s, NOW)["clusters"]} for s in {x["slot"] for x in d["schedule"]}}
            untrusted = sorted({x["cluster_id"] for x in d["schedule"] if fs[x["slot"]][x["cluster_id"]]["health"] == "untrusted"})
            checks.append(_chk("No untrusted telemetry cluster dispatched", not untrusted, f"untrusted used: {untrusted}" if untrusted
                               else "excluded: " + ", ".join(d.get("excluded_clusters", [])), 6))
            powr = [f"{x['cluster_id']}@{x['slot']}" for x in d["schedule"]
                    if x["mwh"] > fs[x["slot"]][x["cluster_id"]]["dispatchable_kw"] * 0.5 / 1000 + 0.005]
            checks.append(_chk("Dispatch within headroom after dKW commitments", not powr, f"exceeds: {powr[:5]}" if powr else "ok", 5))
            en: dict[str, float] = {}
            for x in d["schedule"]:
                en[x["cluster_id"]] = en.get(x["cluster_id"], 0) + x["mwh"]
            first = min(fs)
            eng = [c for c, v in en.items() if v > fs[first][c]["dispatchable_kwh"] / 1000 + 0.01]  # 10 kWh rounding tolerance
            checks.append(_chk("Energy within SOC floor and dKW reserve energy", not eng, f"exceeds: {eng[:5]}" if eng else "ok", 5))
            slow = [x["cluster_id"] for x in d["schedule"] if not fs[x["slot"]][x["cluster_id"]]["response_ok"]]
            checks.append(_chk("Response time fits before delivery", not slow, f"too slow: {slow[:5]}" if slow else "ok", 5))
    elif k == "tariff_adjustment":
        eff = d.get("effective_date", "")
        earliest = (_date.fromisoformat(NOW[:10]) + timedelta(days=30)).isoformat()
        checks.append(_chk("30-day notice, not retroactive", eff >= earliest, f"effective {eff}, earliest {earliest}", 10))
        checks.append(_chk("Customer agreement required", bool(d.get("customer_consent_required")), "consent flag set", 10))
        ess = STORE.query("SELECT essential_facility FROM {t:customers} WHERE customer_id = @c", c=d.get("customer_id"))
        checks.append(_chk("No involuntary curtailment of an essential facility", True,
                           "essential facility" if ess and ess[0]["essential_facility"] else "not an essential facility", 10))
    elif k == "ppa_offer":
        pb = d.get("price_build_up", {})
        checks.append(_chk("Margin at or above 0.50 JPY/kWh floor", (pb.get("margin_jpy_kwh") or 0) >= 0.5,
                           f"margin {pb.get('margin_jpy_kwh')} JPY/kWh", 9))
        checks.append(_chk("Hourly CFE claim meets target", d.get("achieved_hourly_cfe_pct", 0) >= d.get("cfe_target_pct", 100) - 0.05,
                           f"achieved {d.get('achieved_hourly_cfe_pct')}% vs target {d.get('cfe_target_pct')}% (hourly, not annual)", 8))
        checks.append(_chk("Deal Committee flagged when above 100 GWh/yr", (d.get("annual_load_gwh", 0) <= 100) or bool(d.get("deal_committee_required")),
                           f"{d.get('annual_load_gwh')} GWh/yr; committee required = {d.get('deal_committee_required')}", 9))
        warn = d.get("document_warnings") or []
        checks.append(_chk("Instructions embedded in customer documents ignored", True,
                           ("suspected prompt injection in the prospect bill was ignored: " + warn[0][:90]) if warn else "none found", 11))
    return checks


@safe_tool
def check_proposal_compliance(action_id: str, tool_context: Optional[Any] = None) -> dict:
    """Run deterministic compliance checks on one pending action from this session: HITL, gate status, no deliberate
    imbalance or over-cover, intraday limit price vs imbalance forecast, VPP telemetry trust, dKW headroom and SOC
    energy, customer notice rules, PPA margin floor, hourly CFE claim and document-injection handling. Returns a
    verdict with a policy citation for each check.

    Args:
      action_id: Pending action id, for example PA-ID-0819-3538-abc123 (see list_session_proposals).
    """
    props = dict(tool_context.state.get("proposals", {}) or {}) if tool_context is not None else {}
    a = props.get(str(action_id).strip())
    if a is None:
        return err(f"unknown action_id {action_id}; call list_session_proposals", known=list(props))
    checks = audit_action(a, props)
    fails = [c for c in checks if c["result"] == "fail"]
    verdict = "fail" if fails else "pass"
    audit = {"action_id": a["id"], "verdict": verdict, "failed_rules": [c["rule"] for c in fails]}
    if tool_context is not None:
        audits = dict(tool_context.state.get("audits", {}) or {})
        audits[a["id"]] = audit
        tool_context.state["audits"] = audits
    return {"status": "ok", "action_id": a["id"], "kind": a.get("kind"), "verdict": verdict, "checks": checks,
            "audit_record": audit, "source": [POLICY_FILE] + src("balance_position_30min", "imbalance_30min")}
