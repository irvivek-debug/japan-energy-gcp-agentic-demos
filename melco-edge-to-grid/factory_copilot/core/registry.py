"""In-process registry of edge-simulated plans, proposals and edge decisions.

Why: the safety auditor must be able to prove a plan passed the edge simulation before it is presented,
and propose_* tools must refuse plans that were never simulated. In production this state lives in the
edge decision log (BigQuery edge_decisions via Pub/Sub) and the pending-action store (Firestore); for the
demo it is process memory, shared by all agents running in the same process (local runner or one Agent
Runtime instance).
"""
from __future__ import annotations

import threading
import time

_LOCK = threading.Lock()
PLANS: dict[str, dict] = {}
EDGE_LOG: list[dict] = []
_SEQ = [0]


def register_simulation(plan: dict, result: dict) -> str:
    pid = result["plan_id"]
    with _LOCK:
        PLANS[pid] = {"plan": plan, "result": result, "simulated_at": time.time(), "proposal": None, "audit": None}
        for a in result["actions"]:
            _SEQ[0] += 1
            EDGE_LOG.append({"decision_id": f"EDG-RT-{_SEQ[0]:05d}", "ts": result["evaluated_at"], "event_id": result.get("event_id", ""),
                             "plan_id": pid, "asset_id": a["asset_id"], "action": a["action"], "requested_kw": a["requested_kw"],
                             "granted_kw": a["granted_avg_kw"], "verdict": a["verdict"], "rule_id": ",".join(a["rule_ids"]),
                             "reason": a["reason"], "latency_ms": a["latency_ms"], "edge_node": result["edge_node"], "runtime": True})
    return pid


def get(plan_id: str) -> dict | None:
    return PLANS.get((plan_id or "").strip())


def latest(date: str | None = None) -> tuple[str, dict] | None:
    items = [(k, v) for k, v in PLANS.items() if not date or v["result"]["window"]["date"] == date]
    if not items:
        return None
    return max(items, key=lambda kv: kv[1]["simulated_at"])


def mark_proposed(plan_id: str, proposal: dict) -> None:
    with _LOCK:
        if plan_id in PLANS:
            PLANS[plan_id]["proposal"] = proposal


def mark_audited(plan_id: str, audit: dict) -> None:
    with _LOCK:
        if plan_id in PLANS:
            PLANS[plan_id]["audit"] = audit


def reset() -> None:
    with _LOCK:
        PLANS.clear()
        EDGE_LOG.clear()
