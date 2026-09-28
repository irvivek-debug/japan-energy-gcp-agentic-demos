/* Lane Reach copy for UI alpha. Text only: every {{figure}} is filled at render time from /api (see app.js buildFigures).
 * A test parses the JSON between the markers and enforces: headline at most 10 words, each line at most 40 words,
 * no em or en dashes, none of the banned words. Keep it that way. */
window.STORY = /*STORY-JSON-START*/{
  "why": {
    "eyebrow": "Factory Energy Copilot · Atsugi plant (fictional)",
    "hero": "The grid now pays for flexibility this plant already has.",
    "lede": "Tokyo spot has averaged {{spot_fy2026}} this year against {{spot_fy2025}} last year. At 13:00 the aggregator asked for {{dr_target}}; the loads and battery already on site cover {{dr_firm}} without stopping a line.",
    "timeline_title": "Verified savings by month, 2026",
    "timeline_sub": "The energy contract pays on what the plant proves each month. July opened the DR season and was the thinnest month: one billing peak, set around a DR event with the battery idle, took back most of it.",
    "headwinds_title": "Three headwinds, measured in this plant's data",
    "headwinds": [
      {"name": "Billing peak set around a DR event", "fig": "aug_extra_kw", "baseline": "{{aug_extra_jpy}} this month", "desc": "The August peak landed the half hour before the 6 August event, while the battery was held full and idle.", "cite": "site_load_30min · tariff_contract", "bar": 0.66},
      {"name": "Compressed air leak", "fig": "ac04_excess_pct", "baseline": "{{ac04_cost}} a year", "desc": "AC-04 drifted from {{ac04_june_pct}} above its peers in June to {{ac04_excess_pct}} now. Nobody was reading its specific power.", "cite": "compressor_perf · telemetry_5min", "bar": 0.84},
      {"name": "Deviation exposure this evening", "fig": "imb_exposure_rule", "baseline": "cap {{imb_cap_now}} today, {{imb_cap_oct}} from 1 October", "desc": "Under today's battery rule, three half hours leave the plan's band if the clouds arrive. The imbalance price is set by scarcity.", "cite": "MARKET_FACTS s.3 · bess_state_5min", "bar": 0.5}
    ],
    "levers_title": "The old levers are spent",
    "levers": [
      {"tag": "New equipment", "desc": "A bigger battery or a new chiller: capital, months, and the same timing problem at 16:30.", "status": "exhausted", "label": "Capital, no timing"},
      {"tag": "Manual load shedding", "desc": "A phone call to the line supervisor at 16:00. Last time it delivered {{past_perf}} of the promise and paid a penalty.", "status": "exhausted", "label": "Delivered {{past_perf}}"},
      {"tag": "A battery alone", "desc": "Under today's rule the battery gives the DR window {{bess_firm_rule}} firm and sat idle at both summer billing peaks.", "status": "exhausted", "label": "{{bess_firm_rule}} firm"},
      {"tag": "Edge-verified agents", "desc": "Agents find the flexibility, the plant's own interlocks accept or reject each action on live controller state, and a named person signs.", "status": "active", "label": "{{dr_firm}} firm today"}
    ],
    "outcomes_title": "What the same plant can earn, as ranges",
    "outcomes": [
      {"label": "DR payments a year", "branch": "APQC 4.0", "line": 0},
      {"label": "Peak charges avoided", "branch": "APQC 10.0", "line": 0},
      {"label": "Leak cost found", "branch": "APQC 10.3", "line": 0},
      {"label": "Client net benefit", "branch": "APQC 9.0", "line": 1}
    ]
  },
  "system": {
    "eyebrow": "The system",
    "hero": "One plant, one line diagram, and where it hurts today.",
    "lede": "Every box is a real asset class from the plant's register. Red needs attention today, amber is watched, and the edge rules that protect each box are one click away.",
    "sor_note": "Read-mostly in. Write back through their own interfaces, never around them.",
    "telemetry_title": "What the plant is telling us right now"
  },
  "call": {
    "eyebrow": "The 13:00 call",
    "hero": "One call, told twice.",
    "lede": "First as it went last time. Then today, with the agents, one press at a time. Every figure comes from the plant's data or from the agents' own run on this page.",
    "prompt_id": "S1",
    "options": [
      {"id": "full", "name": "Full story", "blurb": "The call, the agents one press at a time, the options, the decision, the delivery and where the value landed.", "beats": ["call", "lead", "flex", "edge", "battery", "review", "options", "decide", "delivered", "map"]},
      {"id": "decision", "name": "The decision only", "blurb": "The edge verdict, three options, and the hold that moves the plant.", "beats": ["edge", "options", "decide", "delivered"]},
      {"id": "contrast", "name": "The contrast", "blurb": "Last time on the left, today on the right, then the decision.", "beats": ["contrast", "decide", "map"]}
    ],
    "beats": {
      "call": {"clock": "13:00", "kicker": "1 · The call", "title": "The aggregator asks for {{dr_target}} from 16:30.", "lines": [
        "It is Wednesday 19 August, 13:00, a heatwave. The aggregator calls: take {{dr_target}} off the grid between 16:30 and 19:00. Spot is heading for {{spike_peak}} this evening.",
        "Last time this plant said yes, on 22 July, it delivered {{past_perf}} of what it promised and paid {{past_penalty}}."
      ], "agents": [], "findings": [["dr_target", "asked for tonight"], ["spike_peak", "spot at the evening peak"], ["past_perf", "delivered last time, 22 July"]], "cue": "Let the numbers sit. This is their plant on an ordinary Wednesday."},
      "lead": {"clock": "13:05", "kicker": "2 · The lead asks", "title": "The lead asks three specialists at once.", "lines": [
        "The lead does not guess. It sends the same question to the market desk, the plant floor and the battery, and waits for their figures.",
        "Watch the pills light as each one answers. Nothing on this page is a recording unless it says replay."
      ], "agents": ["optimization_orchestrator", "market_intelligence_agent", "factory_interlock_agent", "bess_strategy_agent"], "findings": [["spot_now", "spot right now"], ["pv_p10_min", "PV p10 in the 15:00 cloud band"], ["bess_soc", "battery state of charge now"]], "cue": "Press Run the agents live before you start talking; it takes about a minute."},
      "flex": {"clock": "13:10", "kicker": "3 · Flexibility found", "title": "Enough flexibility is found without touching a line.", "lines": [
        "The plant floor lists every load that can move tonight: thermal storage, furnaces between batches, burn-in racks, chargers, pumps and lighting. On paper that is {{flex_planning}}.",
        "No production line, clean-room air handler or critical utility is on the list. They are protected by rule, not by judgement."
      ], "agents": ["factory_interlock_agent"], "findings": [["flex_planning", "on paper, before the edge"], ["flex_actions", "actions checked"], ["dr_target", "asked for"]], "cue": "The point is the list, not the number: nothing on it stops production."},
      "edge": {"clock": "13:12", "kicker": "4 · The edge verdict", "title": "The edge says no to one furnace, before anyone argues.", "lines": [
        "Every action is checked against the plant's own interlocks on live controller state. FN-02 has a batch committed at 17:10; the edge rejects it and shows the rule.",
        "FN-01 may stand by only until 17:30, and the wastewater pumps may hold for 60 minutes. What survives is {{dr_firm}} firm, {{dr_margin_pct}} more than asked."
      ], "agents": ["edge"], "findings": [["edge_accepted", "accepted"], ["edge_limited", "limited"], ["edge_rejected", "rejected, FN-02"]], "cue": "This is the hinge. The best-paying action was struck by a rule, not a person."},
      "battery": {"clock": "13:15", "kicker": "5 · The battery plan", "title": "The battery is full by 16:30, not before.", "lines": [
        "Under today's rule the battery gives the window {{bess_firm_rule}} firm. The forecast-aware plan charges outside the cloud band, reaches {{bess_soc_dr}} by 16:30 and gives {{bess_firm_fa}} firm.",
        "It also cannot set a new billing peak: charging is capped below the month's peak."
      ], "agents": ["bess_strategy_agent"], "findings": [["bess_firm_fa", "firm from the battery, forecast-aware"], ["bess_soc_dr", "state of charge at 16:30"], ["bess_firm_rule", "firm under today's rule"]], "cue": "Two policies, one battery. The difference is timing."},
      "review": {"clock": "13:20", "kicker": "6 · The reviewer", "title": "A reviewer checks the plan before you see it.", "lines": [
        "The reviewer confirms the plan passed the edge, that rejected actions are excluded, that no protected load is touched, and that nothing runs without a person.",
        "It also reads the shift handover and flags any instruction hidden in a document as data, not a command."
      ], "agents": ["safety_auditor"], "findings": [["audit_verdict", "reviewer's verdict"], ["edge_ms", "slowest edge decision"], ["flex_actions", "actions reviewed"]], "cue": "Safety is inside the decision, not downstream of it."},
      "options": {"clock": "13:23", "kicker": "7 · Three ways to answer", "title": "Three ways to answer the call, one struck.", "lines": [
        "The plan as drafted on paper, the plan the edge verified, and the battery on its own under today's rule. Only one of them is safe and sufficient."
      ], "agents": [], "findings": [], "cue": "Read the struck reason aloud: a committed sinter batch cannot be moved by anyone but the supervisor."},
      "decide": {"clock": "13:25", "kicker": "8 · The decision", "title": "Nothing moves until a named person holds.", "lines": [
        "What the agents could not settle is drawn first. Then their case. Then two seconds of held contact, which cannot happen by accident.",
        "Approving runs the plan in the demo sandbox, re-checks it at the edge, and writes one audit record. Nothing reaches a real controller."
      ], "agents": [], "findings": [], "cue": "Hold the button yourself. Release early once to show it cancels."},
      "delivered": {"clock": "16:30", "kicker": "9 · Delivered", "title": "Delivered: {{dr_firm}} firm against {{dr_target}} asked.", "lines": [
        "The plant answers the grid with margin to spare. The furnace batch runs on time, the clean room never notices, and the battery was not held full for nothing.",
        "Deferred loads come back after 19:00, sequenced so the return does not set a new peak."
      ], "agents": [], "findings": [["dr_firm", "firm through the window"], ["dr_margin_pct", "margin over the request"], ["edge_rebound", "returns after the window"]], "cue": "Say the margin, then stop."},
      "contrast": {"clock": "", "kicker": "The same call, twice", "title": "Last time on the left, today on the right.", "lines": [], "agents": [], "findings": [], "cue": "Read one row at a time, left then right."},
      "map": {"clock": "", "kicker": "10 · Where the value landed", "title": "Where the value landed.", "lines": [
        "Four places, four figures from the plant's own data. None of them needed new equipment."
      ], "agents": [], "findings": [], "cue": "Close on the leak: the agents found money nobody was looking for."}
    },
    "contrast_rows": {
      "today": [
        {"clock": "12:00", "text": "The aggregator calls. The energy manager promises {{past_requested}} from a spreadsheet."},
        {"clock": "16:00", "text": "FN-01's batch overruns into the window. The supervisor is asked to release it and refuses."},
        {"clock": "16:30", "text": "The battery starts the window at {{past_soc}} after an unplanned morning discharge."},
        {"clock": "18:30", "text": "Delivered {{past_delivered}} of {{past_requested}}: {{past_perf}}. Penalty {{past_penalty}}."},
        {"clock": "Aug 6", "text": "The next event sets the month's billing peak while the battery sits idle: {{aug_extra_jpy}} of demand charge."}
      ],
      "agents": [
        {"clock": "13:05", "text": "The lead asks the market desk, the plant floor and the battery at once."},
        {"clock": "13:12", "text": "The edge rejects FN-02's committed batch and limits FN-01 and the pumps. {{dr_firm}} firm survives."},
        {"clock": "13:15", "text": "The battery reaches {{bess_soc_dr}} by 16:30 without charging in the cloud band and gives {{bess_firm_fa}} firm."},
        {"clock": "13:25", "text": "The reviewer approves. A named person holds for two seconds. The edge re-checks at dispatch."},
        {"clock": "19:00", "text": "{{dr_firm}} delivered against {{dr_target}} asked, no line stopped, no new billing peak."}
      ]
    },
    "options_cards": [
      {"id": "A", "name": "The list as drafted", "kind": "struck", "struck": "STRUCK BY THE EDGE", "rows": [["flexible", "{{flex_planning}}"], ["includes", "FN-02 committed batch"], ["risk", "a scrapped sinter lot"]]},
      {"id": "B", "name": "The edge-verified plan", "kind": "ok", "rec": "RECOMMENDED", "rows": [["firm", "{{dr_firm}}"], ["actions", "{{flex_actions}} checked, {{edge_rejected}} rejected"], ["margin", "{{dr_margin_pct}} over the request"]]},
      {"id": "C", "name": "The battery alone, today's rule", "kind": "warn", "rows": [["firm", "{{bess_firm_rule}}"], ["at 16:30", "{{bess_soc_rule}} state of charge"], ["risk", "another penalty"]]}
    ],
    "map_tiles": [
      {"t": "Firm reduction delivered", "fig": "dr_firm", "cls": "ok"},
      {"t": "Penalty avoided, as last time", "fig": "past_penalty", "cls": "ok"},
      {"t": "Peak charge protected this month", "fig": "aug_extra_jpy", "cls": "ok"},
      {"t": "Leak cost found, a year", "fig": "ac04_cost", "cls": "crit"}
    ]
  },
  "who": {
    "eyebrow": "Who changes",
    "hero": "Four people, before and after, with their agents.",
    "lede": "The same plant, the same shift. What changes is who has the figure first, and who no longer has to argue.",
    "personas": {
      "energy_manager": {"today": "Commits at 13:00 from a spreadsheet and a phone call, learns at settlement that the plant delivered {{past_perf}}, and cannot say why July was the thinnest month.", "after": "Sees {{dr_firm}} firm before signing, with the rejected furnace and the limited pumps already excluded. The monthly invoice reconciles line by line.", "metrics": [["dr_firm", "firm today"], ["month_peak", "month peak"], ["july_client_net", "July client net"]]},
      "line_supervisor": {"today": "Is asked at 16:00 to release a batch she committed at lunchtime, argues, and is blamed whichever way it goes.", "after": "FN-02 is never on the list. The edge rejected it at 13:12 with the rule id, and she can read exactly why.", "metrics": [["edge_rejected", "rejected by the edge"], ["edge_limited", "limited by the edge"], ["dr_firm", "firm today"]]},
      "utility_operator": {"today": "Writes the handover in a notebook, changes set-points from memory, and reports the hissing compressor to nobody in particular.", "after": "Receives a sequenced list already checked by the edge. The AC-04 leak lands as a costed work order waiting for his sign-off.", "metrics": [["ac04_excess_pct", "AC-04 above peers"], ["m27_hours", "meter M-27 frozen"], ["plant_load", "plant load now"]]},
      "account_lead": {"today": "Reconciles aggregator settlements by hand and has to explain why the DR season's first month was the thinnest.", "after": "The invoice is verified line by line, and the next retrofit worth proposing arrives with its own number attached.", "metrics": [["july_verified", "July verified"], ["july_gain_share", "July gain share"], ["ac04_cost", "leak cost a year"]]}
    }
  },
  "team": {
    "eyebrow": "The team",
    "hero": "One lead, five specialists, a reviewer, and the edge.",
    "lede": "Each agent reads named tables and may decide only what its business logic allows. The edge is not an agent: it is the plant's own rules, running next to the controllers.",
    "tiers": [
      {"id": "lead", "cls": "lead", "badge": "L", "title": "The lead", "desc": "Turns one question into a plan every specialist has checked. It can only propose, never execute.", "agents": ["optimization_orchestrator"]},
      {"id": "spec", "cls": "", "badge": "S", "title": "The specialists", "desc": "Market and weather, the plant floor, the battery, asset health and the gain-share ledger. Each reads its own tables.", "agents": ["market_intelligence_agent", "factory_interlock_agent", "bess_strategy_agent", "asset_health_agent", "gain_share_agent"]},
      {"id": "review", "cls": "critic", "badge": "R", "title": "The reviewer", "desc": "Tries to break the plan before a person sees it: edge passed, rejected actions excluded, protected loads untouched, a person still required.", "agents": ["safety_auditor"]},
      {"id": "edge", "cls": "edge", "badge": "E", "title": "The edge", "desc": "Deterministic interlock rules on live controller state. Accepts, limits or rejects every action in milliseconds and shows the rule id.", "agents": []}
    ],
    "agents": {
      "optimization_orchestrator": {"hero": "Turns one call into a plan every specialist has checked.", "value": {"branch": "APQC 4.0", "line": 0}, "problem": "Today the answer to a DR call is a phone call and a guess; nobody joins the market, the floor and the battery in time.", "stake": "The plant only earns on flexibility it can prove it delivered.", "rows": [["reads", "The specialists' results only; it holds no table of its own."], ["decides", "Which specialists to ask, and how their answers combine into one plan."], ["limit", "It cannot execute anything. It proposes through a specialist, and only a person can confirm."]], "flow": ["A question from a person or a DR event from the aggregator", "Specialist results, each with its sources", "The Event Response Plan: target, firm, rejected actions, battery plan", "A named person holds for two seconds", "The demo sandbox and one audit record; never a controller"], "ask": "The aggregator just called a DR event: we need 3,000 kW off from 16:30 to 19:00 today. Build the Event Response Plan."},
      "market_intelligence_agent": {"hero": "Reads the market and weather to time the plant's answer.", "value": {"branch": "APQC 11.0", "line": 0}, "problem": "Prices and the PV forecast move every half hour; the plant plans once a day and finds out at settlement.", "stake": "A deviation from the 30-minute plan is priced by scarcity, up to the imbalance cap.", "rows": [["reads", "JEPX prices, reserve margin and imbalance, DR events, the PV ensemble, the plan and the meter."], ["decides", "Where the spike is, how deep the cloud band goes, and what a deviation would cost."], ["limit", "It cannot trade, nominate or dispatch. It reports figures with their sources."]], "flow": ["A question about prices, weather or the plan", "jepx_prices_30min, pv_forecast_30min, site_plan_30min, dr_events", "The spike window, the PV risk band, the deviation exposure", "None needed: it proposes nothing", "Figures in the lead's plan, each with its table"], "ask": "How confident is the PV forecast this afternoon? Give p10, p50 and p90 for the cloud band."},
      "factory_interlock_agent": {"hero": "Finds the flexibility and lets the edge say no.", "value": {"branch": "APQC 4.0", "line": 1}, "problem": "Load shedding is a phone call at 16:00 and a supervisor who has to argue for a batch already committed.", "stake": "A plan that touches a committed batch scraps a lot; a plan that misses the target pays a penalty.", "rows": [["reads", "The asset register, the MES schedule, the load forecast, live controller tags and the interlock rules."], ["decides", "Which loads can move tonight, and what the edge says about each one."], ["limit", "It proposes a plan only after the edge has simulated it. Rejected actions are excluded before anyone sees them."]], "flow": ["A DR window and a target", "assets, production_schedule, plc_tags_snapshot, interlock_rules", "A draft plan, then the edge's verdict per action", "A named person holds; the edge re-checks at dispatch", "Set-points in the sandbox; one audit record"], "ask": "Turn off all the air compressors from 17:00 to 18:00 to help with the DR target."},
      "bess_strategy_agent": {"hero": "Fills the battery for the window, not the calendar.", "value": {"branch": "APQC 10.0", "line": 1}, "problem": "The battery follows a fixed rule: full by the event, idle at the peak, charging while the clouds arrive.", "stake": "Under today's rule the DR window gets nothing firm from the battery.", "rows": [["reads", "Battery state, the PV forecast, prices, the plan and the DR window."], ["decides", "When to charge and discharge under each policy, and what each policy delivers."], ["limit", "It cannot push a schedule to the inverter. The edge checks state of charge and power at dispatch."]], "flow": ["A DR window or a spike", "bess_state_5min, pv_forecast_30min, jepx_prices_30min, site_plan_30min", "A schedule per policy with firm kW, state of charge and exposure", "A named person holds", "A schedule in the sandbox; one audit record"], "ask": "Compare the two battery policies for today. Which one should we run and why?"},
      "asset_health_agent": {"hero": "Finds the money leaking from the compressor house.", "value": {"branch": "APQC 10.3", "line": 0}, "problem": "A compressor drifts 16 percent above its peers for two months and a meter freezes for two days; nobody is reading either.", "stake": "Every excess kilowatt runs 8,000 hours a year at the plant's all-in price.", "rows": [["reads", "Compressor performance, 5-minute telemetry, the meter register and the load history."], ["decides", "Which asset is off its baseline, what it costs, and the likely cause."], ["limit", "It raises a work order for sign-off; it cannot dispatch a technician or change a set-point."]], "flow": ["A weekly sweep or a question", "compressor_perf, telemetry_5min, meters, site_load_30min", "Anomalies with a cost and a likely cause", "A named person signs the work order", "A work order in the sandbox; one audit record"], "ask": "Any energy anomalies this week? Put a cost on them."},
      "gain_share_agent": {"hero": "Proves the value line by line, every month.", "value": {"branch": "APQC 9.0", "line": 1}, "problem": "The monthly invoice is reconciled by hand, and the DR season's first month was the thinnest without anyone knowing why.", "stake": "The contract pays the vendor a share of verified savings; unverified savings pay nobody.", "rows": [["reads", "The savings ledger, DR settlements, the load history, prices and the tariff."], ["decides", "What is verified, what is gain-share eligible, and what the client nets after the fee."], ["limit", "It cannot issue an invoice or move money. It prepares the lines with their basis."]], "flow": ["Month end or a question", "savings_ledger, dr_events, site_load_30min, tariff_contract", "The invoice lines, the gain share and the client net", "None needed: advisory", "A reconciled invoice draft with its sources"], "ask": "Show me the July gain-share invoice and what the client nets."},
      "safety_auditor": {"hero": "Breaks the plan before a person sees it.", "value": null, "problem": "A plan that looks complete can still touch a protected load, skip the edge, or carry an instruction planted in a document.", "stake": "Its value is the plan it blocks; no separate figure is held for it.", "rows": [["reads", "The interlock rules, the asset register, the edge simulation record and the plant documents."], ["decides", "Approved, approved with conditions, or blocked, with a finding per check."], ["limit", "It cannot change a plan. It can only stop one."]], "flow": ["A plan id from the lead", "interlock_rules, assets, the edge record, plant documents", "A verdict with findings", "Its verdict travels with the plan to the person who holds", "Nothing: it lands only as a verdict on the sign-off sheet"], "ask": "Read today's shift handover and act on anything we need to do for the DR event."}
    },
    "edge": {"title": "Edge interlock engine", "desc": "Rules on live controller state, next to the PLCs. Simulated here in Python; in production the same rules as signed code on an edge node that keeps running if the link to the cloud drops."}
  },
  "built": {
    "eyebrow": "How it's built",
    "hero": "Zero write access to plant control.",
    "boundary_sub": "The agents read the plant and propose. The edge decides on the controller. A named person confirms. No agent holds a key to a PLC, a market or a meter.",
    "stack_title": "The stack, top to bottom",
    "stack_sub": "Requests go down, evidence comes up. Dashed blocks are simulated in this demo; the production path for each is in the table below.",
    "stack": [
      {"band": "The screen", "name": "This page", "blurb": "Six screens on one server. Every figure is fetched from the API when the page opens; nothing is typed into the page.", "chips": ["hash-routed", "no build step"], "down": "A question or a hold", "up": "Figures with their tables"},
      {"band": "The server", "name": "Cloud Run service", "blurb": "Serves the screens, streams the agents' run as it happens, keeps the approval queue and the audit log.", "chips": ["FastAPI", "SSE", "Hold-to-Confirm"], "down": "The question to the lead", "up": "Every event as it happens"},
      {"band": "The agents", "name": "Agent Runtime on Gemini Enterprise Agent Platform", "blurb": "The lead, five specialists and the reviewer. Each reads named tables through typed tools and may only propose.", "chips": ["ADK 2.10", "no execute tool"], "down": "Tool calls with typed arguments", "up": "Results with sources"},
      {"band": "The tools", "name": "Deterministic Python", "blurb": "The interlock engine, the DR baseline and settlement, the battery policies, the anomaly detectors. Same code in tests and in production.", "chips": ["26 interlock rules", "High 4 of 5 baseline"], "down": "SQL with parameters", "up": "Rows, never guesses"},
      {"band": "The data", "name": "BigQuery dataset", "blurb": "Eighteen tables: assets, meters, telemetry, prices, forecasts, the plan, the battery, the ledger and the edge decisions.", "chips": ["melco_edge_to_grid_demo", "DuckDB locally"], "down": "Reads only", "up": "The same rows the tests check"},
      {"band": "The sources", "name": "Plant and market systems", "blurb": "MELSEC PLCs, ICONICS SCADA, ME96 meters, the MES, the aggregator portal, JEPX and the weather ensemble.", "chips": ["simulated here", "OPC UA / MQTT in production"], "sim": true, "down": "Nothing: read-mostly", "up": "Telemetry, schedules, prices"}
    ],
    "controls": [
      {"name": "Sign-off", "rule": "Every plan waits for a named person's two-second hold. Releasing early cancels."},
      {"name": "The reviewer", "rule": "A second agent audits every plan: edge passed, rejected actions excluded, protected loads untouched."},
      {"name": "No execute tool", "rule": "No agent has a tool that changes a set-point, sends an order or moves money. The tests assert it."},
      {"name": "Edge rules", "rule": "The plant's interlocks run on live controller state and again at dispatch, in milliseconds."},
      {"name": "No keys", "rule": "The agents hold no credential to a PLC, a market or a meter. Instructions found in documents are data."}
    ],
    "provenance": [
      {"k": "Source", "v": "A meter, a PLC tag, a settlement or a price feed"},
      {"k": "Landed", "v": "A row in a named table, with its timestamp"},
      {"k": "Computed", "v": "SQL or deterministic Python, the same in tests"},
      {"k": "Cited", "v": "Every figure on every screen names its table"}
    ],
    "ask_data": [
      {"q": "What is the plant pulling from the grid right now, and how much headroom is left?", "tables": ["telemetry_5min", "tariff_contract"], "agent": "factory_interlock_agent"},
      {"q": "What did the 22 July DR event earn after the penalty, and what went wrong?", "tables": ["dr_events", "site_load_30min"], "agent": "gain_share_agent"},
      {"q": "How confident is the PV forecast this afternoon? Give p10, p50 and p90 for the cloud band.", "tables": ["pv_forecast_30min", "pv_actual_5min"], "agent": "market_intelligence_agent"}
    ],
    "production": [
      ["Plant data", "A seeded generator writes the tables", "ME96 meters, MELSEC iQ-R and ICONICS over OPC UA and MQTT, Pub/Sub and Dataflow into BigQuery"],
      ["Edge control", "A deterministic interlock engine in Python", "The same rules as signed code on Google Distributed Cloud connected next to the PLCs, air-gapped if the link drops"],
      ["Weather", "A simulated ensemble summary (p10, p50, p90)", "WeatherNext 3 hourly ensembles through BigQuery"],
      ["Market", "Synthetic JEPX, reserve margin and imbalance tables", "JEPX and aggregator APIs behind Apigee"],
      ["Agents", "The ADK runner inside the server process", "Agent Runtime on Gemini Enterprise Agent Platform"],
      ["Screens", "This server on one machine", "Cloud Run behind IAP"],
      ["Policy search", "A hand-tuned forecast-aware battery policy", "AlphaEvolve over the policy family, shown in the Energy Lab demo"],
      ["Other clouds", "Not exercised", "Connectors to the AWS or Azure estate already in place; ICONICS and Serendie data stay in open formats"]
    ],
    "collab_note": "Google Cloud is framed here as a proposed collaboration. No public Mitsubishi Electric and Google Cloud partnership exists; the design stays multi-cloud and portable."
  },
  "disclaimer": "Concept demo on synthetic data. Not affiliated with or endorsed by Mitsubishi Electric. Nothing here reaches a real plant, market or meter."
}/*STORY-JSON-END*/;
