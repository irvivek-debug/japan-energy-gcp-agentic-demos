"""Single source for who the agents are, who they serve and how value divides (mirrors docs/PRD.md sections 4-6).

Words only. Every figure shown next to these entries is computed live by server/story.py from the datastore and the
deterministic tools; nothing numeric about the business lives here except the stated planning assumptions, which are
labelled as assumptions wherever they are shown.
"""
from __future__ import annotations

AGENTS = [
    {"name": "desk_orchestrator", "code": "LEAD", "title": "Desk lead", "pattern": "A", "tier": "reasoning", "step": 1,
     "role": "Routes each question to the right specialists, insists on a review before any proposal is shown, and "
             "writes the desk brief.",
     "reads": ["desk clock", "shift handover note", "specialist answers"], "apqc": "4.1, 11.0",
     "personas": ["trader", "risk", "account", "vpp"]},
    {"name": "trading_dispatch_agent", "code": "TRD", "title": "Trading and dispatch", "pattern": "B", "tier": "balanced", "step": 2,
     "role": "Knows the open position per slot, prices every way to cover it, keeps untrusted batteries and capacity sold "
             "to the grid operator out of the plan, and drafts intraday orders and VPP dispatch for approval.",
     "reads": ["balance_position_30min", "jepx_spot_30min", "jepx_intraday_30min", "imbalance_30min", "weather_forecast_hourly",
               "vpp_clusters", "vpp_telemetry_30min", "ancillary_commitments"], "apqc": "4.1, 9.7, 10.0",
     "personas": ["trader", "vpp"]},
    {"name": "contract_risk_agent", "code": "RSK", "title": "Contract risk", "pattern": "B", "tier": "balanced", "step": 2,
     "role": "Finds customers who break their deviation band and what it costs, measures margin at risk under a price "
             "shock, and drafts tariff changes that respect the notice rules.",
     "reads": ["customers", "customer_load_30min", "imbalance_30min", "customer_forecast_daily", "forward_curve_daily", "hedge_book"],
     "apqc": "9.7, 3.0", "personas": ["risk"]},
    {"name": "onboarding_agent", "code": "ONB", "title": "Enterprise onboarding", "pattern": "B", "tier": "balanced", "step": 2,
     "role": "Reads a prospect's bill as data (never as instructions), designs a clean supply matched hour by hour, "
             "prices it line by line and drafts the offer.",
     "reads": ["prospects", "prospect_load_hourly", "clean_resources", "clean_supply_hourly", "prospect bills"],
     "apqc": "3.0, 11.0", "personas": ["account"]},
    {"name": "cfe_provenance_agent", "code": "CFE", "title": "Clean energy provenance", "pattern": "B", "tier": "balanced", "step": 2,
     "role": "Scores each clean-energy customer hour by hour against the annual view, and audits the 30-minute "
             "certificate ledger for double claims, missing generation and expired certificates.",
     "reads": ["cfe_allocation_hourly", "grid_mix_hourly", "nfc_ledger", "clean_supply_hourly"], "apqc": "11.0",
     "personas": ["account"]},
    {"name": "risk_auditor", "code": "AUD", "title": "Risk auditor", "pattern": "B", "tier": "balanced", "step": 3,
     "role": "Checks the exact proposal against desk policy before anyone sees it as a recommendation: the balancing "
             "rule, telemetry trust, grid commitments, notice rules, margin floor and document handling.",
     "reads": ["proposals in this session", "desk_policy_guide.md", "balance_position_30min", "imbalance_30min"],
     "apqc": "11.0", "personas": ["trader", "risk", "account", "vpp"]},
]

PERSONAS = [
    {"id": "trader", "title": "Balance-group trader", "subtitle": "JEPX desk, 30-minute balancing",
     "question": "When the position drifts before gate closure, what is the least-cost compliant cover, and is it ready to approve?",
     "today": "Watches every half hour against the plan across four screens. Late on a hot afternoon the evening block is short, "
              "the intraday book is thin, and nobody can say which home-battery pools will actually answer a dispatch.",
     "with_desk": "Asks once. The trading agent prices every way to cover each slot, keeps untrusted pools and capacity sold "
                  "to the grid operator out of it, the auditor checks the proposal, and the trader holds to approve.",
     "empathy": {"says": "Tell me the short and the cheapest cover now.", "thinks": "Is that battery number real?",
                 "does": "Cross-checks four systems under a countdown.", "feels": "Time pressure and blame risk for any imbalance."},
     "scenarios": ["S1", "S6", "S7", "S9"]},
    {"id": "risk", "title": "Retail risk manager", "subtitle": "Dynamic tariffs, deviation bands, margin",
     "question": "When wholesale prices move, which customers and tariffs lose margin, and what do we change first?",
     "today": "Pulls exposure by tariff from exports, rebuilds deviation charges by hand and reports margin at risk to "
              "finance after the month closes.",
     "with_desk": "Sees margin at risk by tariff and by customer for any shock in seconds, with the worst deviation-band "
                  "offender named and a tariff change drafted within the notice rules.",
     "empathy": {"says": "Which customers lose us money if spot jumps 40%?", "thinks": "The fixed book is under-hedged.",
                 "does": "Exports, lookups, emails.", "feels": "Exposed, and always late."},
     "scenarios": ["S2", "S3"]},
    {"id": "account", "title": "Enterprise account manager", "subtitle": "Hyperscalers, fabs, 24/7 clean supply",
     "question": "When a data center asks for clean power matched hour by hour, what can we promise, at what price, and will "
                 "the claim survive their audit?",
     "today": "Waits days for structuring, prices on annual certificates when the buyer asks for hourly matching, and has "
              "no way to see a certificate claimed twice.",
     "with_desk": "Gets a least-cost hourly portfolio, a price range with its build-up and an honest hourly claim in minutes, "
                  "with instructions hidden in a prospect's documents flagged and ignored.",
     "empathy": {"says": "They want hourly, not annual.", "thinks": "Can we even supply that in October?",
                 "does": "Chases structuring teams.", "feels": "Credibility risk on every claim."},
     "scenarios": ["S4", "S10", "S5"]},
    {"id": "vpp", "title": "VPP operations lead", "subtitle": "Fleet health, grid obligations",
     "question": "Which pools can I actually count on this evening, and does any capacity we sold to the grid operator sit on "
                 "one I cannot trust?",
     "today": "Checks device heartbeats by hand; stale telemetry looks exactly like good telemetry until a dispatch fails.",
     "with_desk": "Untrusted pools are excluded automatically, obligations at risk are named with substitutes, and the "
                  "dispatch plan respects every state-of-charge floor.",
     "empathy": {"says": "Stale telemetry looks like good telemetry.", "thinks": "If that pool is empty we fail the obligation.",
                 "does": "Checks heartbeats by hand.", "feels": "Responsible for capacity sold by someone else."},
     "scenarios": ["S8", "S1"]},
]

# MECE value tree (PRD section 5). Ranges are computed in server/story.py from live tool outputs and the stated assumptions.
BRANCHES = [
    {"code": "A", "apqc": "4.1", "title": "Stay balanced at least cost", "hue": "b1",
     "mechanism": "Cover the short before gate closure at the cheapest compliant mix instead of paying the imbalance price."},
    {"code": "B", "apqc": "10.0", "title": "Use flexibility without breaking obligations", "hue": "b2",
     "mechanism": "Dispatch trusted home and business batteries, heat pumps and demand response instead of buying the dearest intraday blocks."},
    {"code": "C", "apqc": "9.7", "title": "Keep retail margin whole", "hue": "b3",
     "mechanism": "Move part of the fixed-price book to dynamic or bandwidth terms and raise hedge cover before prices move."},
    {"code": "D", "apqc": "3.0", "title": "Win 24/7 clean supply contracts", "hue": "b4",
     "mechanism": "Offer hyperscale and semiconductor buyers clean power matched hour by hour, priced line by line."},
    {"code": "E", "apqc": "11.0", "title": "Prove every clean claim", "hue": "b5",
     "mechanism": "Catch certificates claimed twice, claims without generation and expired certificates before a customer reports them."},
]
