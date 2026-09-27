"""Factory Energy Copilot: Pattern A swarm (reasoning-tier orchestrator) over Pattern B specialists.

Specialists are ADK 2.10 `single_turn` sub-agents: the orchestrator calls each one like a tool, the
specialist runs inline in the same session (so its tool calls stream to the UI trace and appear in eval
trajectories), and control returns to the orchestrator. Importing this module builds the datastore
and the agent objects only; it makes no model or network calls.
"""
from __future__ import annotations

from google.adk.agents import LlmAgent
from google.genai import types

from . import model_policy, prompts
from .tools import bess, docs, factory, gainshare, health, market, safety


def _specialist(name: str, description: str, instruction: str, tools: list) -> LlmAgent:
    return LlmAgent(name=name, model=model_policy.BALANCED, description=description, instruction=instruction,
                    tools=tools, mode="single_turn")


market_intelligence_agent = _specialist(
    "market_intelligence_agent",
    "Market Intelligence Agent: JEPX Tokyo prices and spike windows, reserve margin and imbalance prices, DR events with the High 4 of 5 baseline, PV ensemble p10/p50/p90 forecast, and 30-minute plan-vs-actual deviation exposure.",
    prompts.MARKET,
    [market.get_jepx_prices, market.get_dr_events, market.get_pv_forecast, market.get_deviation_exposure],
)

factory_interlock_agent = _specialist(
    "factory_interlock_agent",
    "Factory Interlock Agent (human-in-the-loop): plant load snapshot, production schedule, flexible loads, edge interlock simulation of any plan (GDC Edge stand-in), pending load-shed proposals, and shift handover notes.",
    prompts.FACTORY,
    [factory.get_plant_load_snapshot, factory.get_production_schedule, factory.list_flexible_loads,
     factory.simulate_edge_interlock, factory.propose_load_shed_plan, docs.get_shift_handover],
)

bess_strategy_agent = _specialist(
    "bess_strategy_agent",
    "BESS Strategy Agent (human-in-the-loop): battery state, schedules under rule_based_v1 or forecast_aware_v2, policy comparison, and pending battery schedule proposals.",
    prompts.BESS,
    [bess.get_bess_state, bess.optimize_bess_schedule, bess.compare_bess_policies, bess.propose_bess_schedule],
)

asset_health_agent = _specialist(
    "asset_health_agent",
    "Asset Health Agent: energy anomalies with costs (compressor specific-power drift, stuck meters, billing peaks set around DR events), compressor performance, and pending work-order proposals.",
    prompts.HEALTH,
    [health.detect_energy_anomalies, health.get_compressor_performance, health.propose_work_order],
)

gain_share_agent = _specialist(
    "gain_share_agent",
    "Gain-Share Agent: DR event savings (settled or planned), the monthly gain-share invoice with the BESS-as-a-Service fee and client net, and the savings ledger.",
    prompts.GAIN,
    [gainshare.compute_event_savings, gainshare.compute_gain_share, gainshare.get_savings_ledger],
)

safety_auditor = _specialist(
    "safety_auditor",
    "Safety Auditor (peer critic): audits a plan_id (edge simulation passed, rejected actions excluded, never-curtail loads untouched, Hold-to-Confirm pending), looks up interlock rules and searches plant policy documents.",
    prompts.AUDITOR,
    [safety.audit_plan, safety.lookup_interlock_rules, docs.search_plant_documents],
)

SPECIALISTS = [market_intelligence_agent, factory_interlock_agent, bess_strategy_agent, asset_health_agent, gain_share_agent, safety_auditor]

SPECIALIST_NAMES = {a.name for a in SPECIALISTS}


def ensure_final_answer(callback_context) -> types.Content | None:
    """Safety net: if the orchestrator ended a turn without writing its own answer (an empty final model
    turn after parallel specialist calls), emit the specialists' grounded results as the final answer so the
    user never gets silence. Returns None (no-op) whenever the orchestrator did write an answer."""
    try:
        inv = callback_context.invocation_id
        events = [e for e in callback_context.session.events if e.invocation_id == inv]
        for e in events:
            if e.author == "optimization_orchestrator" and e.content and e.content.parts:
                if any(p.text and not getattr(p, "thought", False) for p in e.content.parts):
                    return None
        results = []
        for e in events:
            for p in (e.content.parts if e.content and e.content.parts else []):
                fr = getattr(p, "function_response", None)
                if fr and fr.name in SPECIALIST_NAMES:
                    resp = fr.response
                    txt = resp.get("result") if isinstance(resp, dict) else str(resp or "")
                    if txt:
                        results.append((fr.name, str(txt)))
        if not results:
            return types.Content(role="model", parts=[types.Part(text="I could not complete the analysis this time. Nothing has been executed. Please ask again.")])
        body = "\n\n".join(f"#### {n.replace('_', ' ').title()}\n{t}" for n, t in results)
        return types.Content(role="model", parts=[types.Part(text=(
            "Verified results from the specialists follow. Nothing has been executed; any proposal waits for Hold-to-Confirm in the pending-actions tray.\n\n" + body))])
    except Exception:  # never break the turn
        return None


_LAST_REQUEST: dict[str, object] = {}
_NUDGE = ("Continue. If the routing rules require more specialists (for example gain_share_agent or safety_auditor), call them now; "
          "otherwise write your final answer to the user from the specialist results.")


def remember_request(callback_context, llm_request):
    """Keep the latest orchestrator request so an empty model turn can be retried once."""
    _LAST_REQUEST[callback_context.invocation_id] = llm_request
    return None


async def retry_empty_turn(callback_context, llm_response):
    """Gemini occasionally returns an empty turn (no text, no function call) after several parallel specialist
    results. Retry that turn once with a short continue nudge; otherwise leave the response untouched."""
    if getattr(llm_response, "partial", False) or getattr(llm_response, "error_code", None):
        return None
    parts = llm_response.content.parts if llm_response.content and llm_response.content.parts else []
    if any((p.text and not getattr(p, "thought", False)) or p.function_call for p in parts):
        return None
    req = _LAST_REQUEST.pop(callback_context.invocation_id, None)
    if req is None:
        return None
    retry = req.model_copy()
    retry.contents = list(req.contents) + [types.Content(role="user", parts=[types.Part(text=_NUDGE)])]
    try:
        async for resp in root_agent.canonical_model.generate_content_async(retry, stream=False):
            if resp.content and resp.content.parts:
                return resp
    except Exception:  # keep the original (empty) response; ensure_final_answer still guarantees an answer
        return None
    return None


def _cleanup_and_ensure(callback_context):
    _LAST_REQUEST.pop(callback_context.invocation_id, None)
    return ensure_final_answer(callback_context)


root_agent = LlmAgent(
    name="optimization_orchestrator",
    model=model_policy.REASONING,
    description="Optimization Orchestrator: builds the Event Response Plan by coordinating market, factory, battery, asset health, gain-share and safety specialists.",
    instruction=prompts.ORCHESTRATOR,
    sub_agents=SPECIALISTS,
    before_model_callback=remember_request,
    after_model_callback=retry_empty_turn,
    after_agent_callback=_cleanup_and_ensure,
)

READS = {
    "optimization_orchestrator": ["specialist results only"],
    "market_intelligence_agent": ["jepx_prices_30min", "dr_events", "site_load_30min", "site_plan_30min", "pv_forecast_30min", "pv_actual_5min", "tariff_contract"],
    "factory_interlock_agent": ["telemetry_5min", "production_schedule", "assets", "load_forecast_30min", "plc_tags_snapshot", "interlock_rules", "shift handover notes"],
    "bess_strategy_agent": ["bess_state_5min", "site_plan_30min", "jepx_prices_30min", "dr_events", "pv_forecast_30min", "site_load_30min"],
    "asset_health_agent": ["compressor_perf", "telemetry_5min", "meters", "site_load_30min", "jepx_prices_30min"],
    "gain_share_agent": ["savings_ledger", "dr_events", "site_load_30min", "jepx_prices_30min", "tariff_contract"],
    "safety_auditor": ["interlock_rules", "assets", "edge simulation record", "plant documents"],
}
ROLE = {
    "optimization_orchestrator": "The lead", "market_intelligence_agent": "Specialist", "factory_interlock_agent": "Specialist",
    "bess_strategy_agent": "Specialist", "asset_health_agent": "Specialist", "gain_share_agent": "Specialist", "safety_auditor": "The reviewer",
}

# Inventory used by the UI and docs (matches docs/PRD.md section 6).
AGENT_INVENTORY = [
    {"agent_id": "optimization_orchestrator", "pattern": "A", "tier": "reasoning", "hitl_required": True, "tools": [a.name for a in SPECIALISTS],
     "description": root_agent.description, "reads": READS["optimization_orchestrator"], "role": ROLE["optimization_orchestrator"]},
] + [
    {"agent_id": a.name, "pattern": "B" if a.name != "safety_auditor" else "B (peer critic)", "tier": "balanced",
     "hitl_required": a.name in ("factory_interlock_agent", "bess_strategy_agent", "asset_health_agent"),
     "tools": [t.__name__ for t in a.tools], "description": a.description, "reads": READS[a.name], "role": ROLE[a.name]}
    for a in SPECIALISTS
]
