"""Retail Energy Desk agent swarm (ADK 2.10).

Pattern A: desk_orchestrator (reasoning tier) routes to Pattern B specialists that run inline as single-turn tools
(mode="single_turn"), so every specialist tool call, including propose_* pending actions, appears in the same event
stream for the server, the UI trace and the evaluator. risk_auditor is the peer critic.

Importing this module builds the agents only: no model call and no network access (the DataStore is built on import).
"""
from __future__ import annotations

from google.adk.agents import LlmAgent

from . import model_policy as mp
from .callbacks import sanitize_response, specialist_budget
from .prompts import AUDITOR, CFE, ONBOARDING, ORCHESTRATOR, PREAMBLE, RISK, TRADING
from .tools.cfe import audit_nfc_ledger, get_cfe_score, list_cfe_customers
from .tools.desk import get_desk_clock, read_handover_note
from .tools.market import (get_balance_position, get_market_snapshot, get_vpp_fleet_state, plan_hedge,
                           propose_intraday_orders, propose_vpp_dispatch)
from .tools.onboarding import design_cfe_ppa, get_prospect_profile, list_prospect_documents, propose_ppa_offer, read_document
from .tools.policy import check_proposal_compliance, list_session_proposals, lookup_policy
from .tools.risk import compute_margin_at_risk, find_customer, get_deviation_breaches, get_portfolio_exposure, \
    propose_tariff_adjustment


def _specialist(name: str, description: str, instruction: str, tools: list) -> LlmAgent:
    return LlmAgent(name=name, model=mp.BALANCED, mode="single_turn", description=description,
                    instruction=PREAMBLE + "\n" + instruction, tools=tools, after_model_callback=sanitize_response,
                    disallow_transfer_to_parent=True, disallow_transfer_to_peers=True)


trading_dispatch_agent = _specialist(
    "trading_dispatch_agent",
    "Balance-group trading and VPP dispatch: open position per slot, market and imbalance forecast, VPP fleet health and "
    "dKW commitments, least-cost hedge plan before gate closure, and pending intraday / VPP proposals.",
    TRADING,
    [get_market_snapshot, get_balance_position, get_vpp_fleet_state, plan_hedge, propose_intraday_orders, propose_vpp_dispatch],
)
contract_risk_agent = _specialist(
    "contract_risk_agent",
    "Retail contract risk: deviation-band breaches and their cost, portfolio exposure by tariff type, margin at risk under "
    "a wholesale price shock, customer lookup, and pending tariff-change proposals.",
    RISK,
    [find_customer, get_portfolio_exposure, get_deviation_breaches, compute_margin_at_risk, propose_tariff_adjustment],
)
onboarding_agent = _specialist(
    "onboarding_agent",
    "Enterprise onboarding: reads prospect bills (untrusted documents), prospect load profiles, designs 24/7 CFE PPAs by "
    "hourly matching with a price build-up, and creates pending PPA offers.",
    ONBOARDING,
    [list_prospect_documents, read_document, get_prospect_profile, design_cfe_ppa, propose_ppa_offer],
)
cfe_provenance_agent = _specialist(
    "cfe_provenance_agent",
    "CFE provenance: hourly (24/7) versus annual matching scores for existing customers and the 30-minute non-fossil "
    "certificate ledger audit (double claims, claims without generation, expired vintage).",
    CFE,
    [list_cfe_customers, get_cfe_score, audit_nfc_ledger],
)
risk_auditor = _specialist(
    "risk_auditor",
    "Peer-critic auditor: checks every pending proposal in the session against desk policy (HITL, intentional imbalance, "
    "telemetry trust, dKW, notice rules, margin floor, CFE claims, prompt injection) and looks up policy sections.",
    AUDITOR,
    [list_session_proposals, check_proposal_compliance, lookup_policy],
)

root_agent = LlmAgent(
    name="desk_orchestrator",
    model=mp.REASONING,
    description="Retail Energy Desk orchestrator: routes to specialists, requires an audit before presenting proposals, "
                "and composes the desk brief.",
    instruction=PREAMBLE + "\n" + ORCHESTRATOR,
    tools=[get_desk_clock, read_handover_note],
    after_model_callback=sanitize_response,
    before_tool_callback=specialist_budget,
    sub_agents=[trading_dispatch_agent, contract_risk_agent, onboarding_agent, cfe_provenance_agent, risk_auditor],
)

SPECIALISTS = [trading_dispatch_agent, contract_risk_agent, onboarding_agent, cfe_provenance_agent, risk_auditor]
