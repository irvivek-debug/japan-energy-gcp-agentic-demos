# UI version alpha: the CEO story, in the mining front-end design language

Version 2 was too dense. Version alpha is a **separate front end** on the **same back end** (same server, same
`/api`, same agents, same BigQuery) that explains the deep work in simple language to a CEO-level audience, with
a visual on every screen. It adopts the owner's **light** mining front-end language (the HTML 10 tokens: off-white
canvas, white cards, Google blue, serif headlines, mono figures) and its six-screen story structure. The kit is
[`docs/reference/ui-alpha/`](reference/ui-alpha/): `alpha.css` (tokens + every component below) and
`alpha-shell.js` (hash-routed screens, `api`, `fig`, `range`, drawer, toast, `hold`, `stream`, `play`).

## 1. The two lanes (from the owner's visual system)

| Lane | Where it lives in alpha | Rule |
|---|---|---|
| **Reach** (the story) | every screen surface | One idea per card. Headline six to ten words. Two sentences of body, at most. A number bigger than the words. No diagrams of technology before screen 6. |
| **Proof** (the product) | drawers, deep dives, the live agent stream | Dense is fine. Real agent output, real tables, real figures. Never a still: the agent stream plays live. |

Everything a CEO reads is Lane Reach. Everything they click into is Lane Proof. A screen that needs its caption has
failed: switch the copy off and the numbers and visuals must still make the point.

## 2. Page structure (one `index.html`, six hash-routed screens, identical order in all three demos)

Header: brand (product name) · `SYNTHETIC · SANDBOX` green pill · six tabs · avatar. `main.main-content` holds six
`.screen-pane`s. `Alpha.mount()` builds the header from `window.ALPHA`.

| # | Tab label | Purpose (what the CEO takes away) | Must contain |
|---|---|---|---|
| 1 | **Why now** | The market moved; the old levers are spent; a decision layer is the lever left. | Serif hero claim (≤ 10 words) · 2-sentence lede with the two figures that matter · **timeline chart** (SVG line, the regime change marked) · **3 headwind cards** (big number, red bar, one-line cause, source cite) · **lever exhaustion matrix** (4 columns; the 4th, highlighted blue, is the agentic decision layer) · **outcomes bar** (4 blue figures, all ranges) |
| 2 | **The system** | Here is your operation as a map, and where it hurts today. | **Schematic twin**: dashed zone boxes on a grid, nodes with state (normal / amber watched / red critical with pulsing dot), SVG links (hot = animated dashes), click a node → slide-over drawer with live readings and "who watches this" · **telemetry cards** (3 to 6, sparklines, critical border) · **systems-of-record strip** at the bottom ("read-mostly in, write back through their APIs, never around") |
| 3 | **The afternoon** (TEPCO) / **The call** (MELCO) / **The run** (Lab) | One event, told twice: as it goes today, then with the agents, one press at a time. | `.mo-options` (Full story / The decision only / The contrast) · beats rail with clocks · stage per beat: kicker, serif title, 2-3 plain sentences, agent pills that light as the **live** stream reaches them, **findings** (3 big figures from `/api`), presenter-cue toggle, "How this was produced" drawer · a **contrast** beat (two columns: today with red-clock hits vs with agents with green-clock wins) · an **options** beat (3 cards, one `struck` by the reviewer/edge with the reason) · the **decide** beat: "What it could not settle" box, the agent's case, then `Alpha.hold` (2 s ring) that POSTs the real `/api/actions/{id}/confirm` and shows the audit result · the **map** beat: where the value landed (4 tiles) |
| 4 | **Who changes** | Named roles, before and after, and the agents assigned to each. | Persona pill strip (initials avatar) · identity row (portrait tile, serif name/title, one line of what they own, 3 metric chips) · **Core job-to-be-done** blue box · **Today's broken reality** (red head) vs **With the agents** (green head) · **Assigned squad**: rows with `ADVISORY` / `ARBITER` / `SIGN-OFF` badges, one line each, "Ask it" chip that opens the live agent in the drawer with a suggested question |
| 5 | **The team** | The lead, the specialists, the reviewer, and (MELCO) the edge. What each reads and what it may decide. | Toolbar (search + filter chips) · **topology timeline** (tiers with badges: lead blue, specialists grey, reviewer red, edge amber) with agent cards · **deep dive** per agent: serif title + `badge-id` + APQC pill, green **value unlocked** card (range), red **the problem it removes** card, blue **business logic** card (stake line + rows incl. a `limit` row: what it may not do), the **five-stage decision flow** `trigger → reads → decides → approval → lands` with a business sentence on every stage, right column: **Ask this agent** (live) · **Play the recorded run** (replay from eval evidence, labelled replay) · provenance rows (tables read) |
| 6 | **How it's built** | The boundary, the stack, and what is simulated vs production. | **Boundary hero** ("Zero write access to the market" / "…to plant control" / "Nothing here promotes code to production") · **architecture stack** (blocks top-down: the screen → Cloud Run → Agent Runtime → tools → BigQuery → sources; `sim` dashed blocks for simulated sources; seams with request-down / evidence-up) · **control rail** (guardrails: sign-off, reviewer, invariants, edge rules, no keys) · **4-stage provenance** (source → landed → computed → cited) · **Ask the data directly** (3 grounded questions with the tables they hit) · production path table (demo simulates / production uses) |

Every screen ends with a `Technical detail` drawer for the engineer in the room and the disclaimer line.

## 3. Story mapping per demo

**TEPCO Retail Energy Desk** · product "Retail Energy Desk" · event: **The 15:40 decision** (gate closes 16:00).
1 Why now: hero "The market moved 60 percent in April. Your tariff book did not." Timeline = Tokyo spot FY2020 to
FY2026 (monthly means, April 2026 marked); headwinds = FY2026 price regime, imbalance cap 200 → 300 JPY/kWh on
2026-10-01, JEPX API-only from 2026-10-01; levers = buy forward / cut margin / pass through / **agentic desk**;
outcomes = imbalance avoided, margin at risk covered, hours to onboard a PPA, VPP MW trusted (ranges).
2 The system: zones Supply (PPA, clean resources) → Market (JEPX spot, intraday) → Balance group (position: red in
slots 35-38) → Flexibility (VPP clusters: VPP-R-17 red, E-04 amber) → Customers (segments; Kanagawa Cold Chain amber)
→ Settlement (imbalance, NFC ledger: double claim red). SoR strip: JEPX, TSO, billing, meter data, NFC registry.
3 The afternoon: beats 15:40 short position · 15:42 the desk lead asks · 15:44 the specialists (trading, VPP state)
· 15:47 the reviewer strikes "leave slot 36 short" · 15:50 the decision (intraday orders + VPP dispatch, hold) ·
16:00 gate closes, position covered · contrast (today: imbalance settles at 184.8 JPY/kWh; with agents: 54.7).
4 Who changes: trader, risk manager, enterprise account manager, VPP operations lead (from the PRD).
5 The team: desk_orchestrator (lead), trading_dispatch, contract_risk, onboarding, cfe_provenance (specialists),
risk_auditor (reviewer). 6 How it's built: boundary "Zero write access to JEPX or the TSO"; production path Apigee →
JEPX API, Pub/Sub + Dataflow VPP telemetry, WeatherNext 3, Powerledger-style ledger.

**MELCO Factory Energy Copilot** · product "Factory Energy Copilot" · event: **The 13:00 call** (aggregator asks
for 3,000 kW from 16:30). Timeline = plant demand charge and DR revenue by month (Jan to Aug 2026) or JEPX August
spikes; headwinds = billing peak set around a DR event, AC-04 leak cost, imbalance band exposure; levers = new
equipment / manual load shedding / a BESS alone / **edge-verified agents**; outcomes = firm kW delivered, DR payment
share, peak charge avoided, leak cost found (ranges). 2 The system: single-line schematic: Grid (contract 16 MW) →
main switchboard → asset classes (clean-room HVAC critical-protected, chillers + TES, compressors AC-04 red,
furnaces FN-02 amber committed batch, lines and burn-in, EV chargers, PV 3 MWp, BESS 4 MW/8 MWh) → Aggregator / JEPX.
SoR strip: MELSEC PLCs, ICONICS SCADA, ME96 meters, MES, aggregator portal. 3 The call: 13:00 the call · 13:05 the
lead asks · 13:10 flexibility found · 13:12 the edge rejects FN-02 and limits FN-01, WW pumps · 13:15 BESS plan ·
13:20 safety auditor · 13:25 decide (hold) · 16:30 to 19:00 delivered · contrast (past event 59% delivered vs
3,576 kW firm). 4 personas: plant energy manager, line supervisor, facilities operator, MELCO account lead. 5 team
incl. the edge interlock engine as its own amber tier. 6 boundary "Zero write access to plant control"; GDC Edge,
OPC UA/MQTT, multi-cloud; Google Cloud framed as a proposed collaboration.

**AlphaEvolve Energy Lab** · product "Energy Lab" · event: **The 09:00 run** (a pre-registered search). 1 Why now:
hero "Your price book and your trading rules are code. Code can be evolved." Timeline = FY2023 to FY2026 Tokyo
price (regime shift) with the seed tariff book's tail loss; headwinds = FY2026 regime, tail risk (CVaR) of the
fixed book, intentional-imbalance temptation; levers = hire quants / buy a black box / tune by hand / **evolve
under guardrails**; outcomes = trading holdout delta range, tariff tail-risk reduction, invalid candidates caught,
cost per run. 2 The system: the evolution loop as a twin: Seed → Controller (Gemini) → Sandbox → Evaluator
(market model, 1,200 customers, BESS fleet) → Invariants (churn, intentional imbalance: red catch nodes) → Holdout
(fresh cohort) → Human review → Managed AlphaEvolve (dashed: not provisioned here). SoR strip: market history,
customer cohorts, cost stack, evidence files, budget ledger. 3 The run: 09:00 pre-registration frozen · 09:05
first candidates · 09:20 a candidate caught pricing fabs out · 09:40 champion on train · 10:00 holdout3 rescoring
· 10:05 the caveat (margin) · the review gate (hold = "mark human-reviewed", never promotion) · contrast (runs 1-3 no
citable uplift vs run 4 +21,191 JPY M with caveat). 4 personas: head of pricing, head of trading, quant lead, risk
officer. 5 team: controller, evaluator, invariants, holdout judge, Lab Analyst (live). 6 boundary "Nothing here
promotes code to production"; `local controller, not the managed AlphaEvolve service` wherever a run is shown.

## 4. Copy rules (Lane Reach)
* Headline ≤ 10 words, sentence case, a claim not a label. Body ≤ 2 sentences, ≤ 40 words. Numbers carry units.
* Plain words: "the agents", "the reviewer", "sign-off", "the edge". No `ADK`, `Agent Runtime`, `BigQuery`,
  `SSE`, `LLM`, `orchestrator`, `Pattern A/B` on screens 1 to 5 outside drawers.
* Value as ranges, never a point. Every research figure carries a `cite` (MARKET_FACTS section). A missing figure
  renders `NOT IN THE DATA`.
* Humanizer: no em or en dashes, active voice, none of: delve, tapestry, testament, underscore, elevate, crucial,
  pivotal, vital, foster, vibrant, intricate, landscape, showcase, boasts.
* Honesty strings are design: `replay` badges on replays, `local controller` on Lab runs, the sampling-margin
  caveat next to the tariff number, "what it could not settle" before every hold.

## 5. Visual rules
* Tokens exactly as `alpha.css`. Light only. Serif for hero/section/deep-dive titles; sans for body; mono for
  figures, ids, cites. Cards 8px radius, xs shadow. Status colours are reserved (red critical, amber watched,
  green good, blue primary) and always paired with a word.
* Charts: inline SVG built from `/api` rows (no chart library needed; ECharts allowed if already loaded). One axis.
  Categorical colours `--c1..--c6` in fixed order, direct-labelled. Sparklines in telemetry cards.
* Motion is quiet: pane fade 0.2 s, `riseIn` stagger ≤ 5 px on the architecture stack and decision flow, pulsing
  dot on critical nodes, animated dashes on hot links, the 2 s hold ring, seam drift. Reduced motion honoured.
* 44 px targets; phone width 390 px works with no horizontal scroll (tabs scroll horizontally).

## 6. Engineering
* Files: `ui-alpha/index.html`, `ui-alpha/alpha.css` + `alpha-shell.js` (copied from the kit), `ui-alpha/app.js`
  (+ `story.js`, `schematic.js` if you like). No build step. `ALPHA` config at the top of `app.js`.
* Server: `UI_VARIANT=alpha` mounts `ui-alpha/` at `/`, keeps v2 at `/v2/` and v1 at `/v1/`. Unset keeps today's
  behaviour (v2 at `/`, v1 at `/v1/`). Add `/api/alpha/*` read-only endpoints only where an existing endpoint does
  not already serve the figure; TestClient tests for each. `/api/health` reports `ui_variant`.
* Dockerfile copies `ui-alpha/`. Deploy is a second Cloud Run service (`<service>-alpha`) with `UI_VARIANT=alpha`
  and otherwise identical env (same `AGENT_ENGINE_ID`, same dataset).
* Verify: `node --check` every JS; headless render of all six screens at 1440 and 390 with zero console errors and
  no horizontal scroll (screenshots to `docs/img/alpha/`); a copy test (no dashes / banned words in `ui-alpha/` and
  alpha API strings); a live run of the event beat and the deep-dive "Ask this agent" against the local backend;
  Lane Reach word counts enforced by a test over the story JSON (headline ≤ 10 words).
