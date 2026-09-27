# Retail Energy Desk (concept demo)

An agent team on Google Cloud for a Japanese electricity retailer's C&I desk: 30-minute balancing before gate
closure with a Mega-VPP, contract risk on dynamic and bandwidth tariffs, 24/7 carbon-free energy PPAs for hyperscale
data centers, and certificate provenance. One scenario: Wednesday 2026-08-19, 15:40 JST, Tokyo heatwave, balance
group short in slots 35-38 as the reserve margin falls to 3-4%.

Concept demo. Synthetic data. Not affiliated with or endorsed by TEPCO. Market calibration: `../docs/research/MARKET_FACTS.md`.

![Retail Energy Desk, UI v2 landing page (synthetic data)](docs/img/v2/landing_1440.jpg)

## What it shows

- `desk_orchestrator` (Gemini 3.1 Pro) routes to five specialists (Gemini 3.6 Flash): trading and dispatch,
  contract risk, onboarding, CFE provenance, and a risk auditor that checks every proposal before it is shown.
- Deterministic tools do the maths: a least-cost hedge LP that can never choose imbalance, telemetry trust rules,
  dKW and SOC constraints, margin at risk, an 8,760-hour 24/7 CFE portfolio LP, and a 30-minute certificate audit.
- Agents never execute. `propose_*` tools create pending actions; a person approves with a 2-second Hold-to-Confirm
  that shows the reasoning, sources and the auditor's checks; every decision lands in the audit log.
- The UI binds every number to `/api/*` endpoints backed by the same datastore the agents use. UI v2 (below) tells
  the business case and opens the working desk; the first UI stays at `/v1/` for comparison.

## Five-minute quickstart (local)

```bash
cd showcase/tepco-retail-vpp
../../.venv/bin/python data/generate.py              # 20 tables, ~28 MB, deterministic (seed 20260819)
../../.venv/bin/python -m pytest -q tests             # generator properties, tool math, HITL, server
export GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=<your-project>
../../.venv/bin/python -m uvicorn server.app:app --port 8081
# open http://localhost:8081 (UI v2) or http://localhost:8081/v1/ (first UI); Agent teams -> S1 first
```
Dashboards work without model access; chat needs Vertex AI credentials (ADC). `DATA_BACKEND=bigquery` switches the
same SQL to BigQuery (`deploy/DEPLOY.md`).

## Layout

```
data/            generate.py, documents.py, simulation_parameters.yaml, schema.json, out/*.csv
retail_desk/     agent.py (root_agent), prompts.py, model_policy.py, datastore.py, store.py, clock.py,
                 callbacks.py, tools/ (market, risk, onboarding, cfe, policy, desk), schema.json, corpus/
server/app.py    FastAPI: /api/* dashboards, SSE /api/chat, HITL queue, audit log, static UI
server/story.py  /api/story/*, /api/agents, /api/personas: the v2 story figures, computed from the same tools
ui/              v2: index.html (landing), case/ (5 chapters), workspace/ (5 pages), js/, css/, kit/ (design kit)
ui/v1/           the first UI, unchanged, served at /v1/
eval/            evalsets/ (ADK), run_adk_eval.py, grounding_eval.py, safety_eval.py, harness.py, results/,
                 replay.py (recorded runs through the real event path), live_ui_capture.py
tests/           pytest suites
docs/            PRD.md, TECHNICAL_DESIGN.md, DEMO_SCRIPT.md, EVAL_REPORT.md, img/ (v1), img/v2/ (v2)
deploy/          DEPLOY.md, load_bigquery.py, deploy_agent_engine.py
```

## UI v2

Two families that share one navigation bar. **The case** makes the argument in five chapters. **The workspace** is
the desk itself. Every figure on every page comes from `/api/*` at load time; nothing numeric is typed into the HTML
(`tests/test_ui_static.py` enforces this). Every approval opens the sign-off sheet. The sheet shows what the proposal
could not settle, then the agent's own case, then what it read, and only then the 2-second hold.

| Route | Page | What it shows |
|---|---|---|
| `/` | Landing | The thesis, the gap measured in this data, an evidence strip with a scrubber over 96 half hours, and two doors |
| `/case/` | 1 · The case | Open position per half hour, the new price regime, the steeper October penalty curve, hourly clean-power demand |
| `/case/gap.html` | 2 · The gap | Cover per half hour, cost per kWh in the scarcity window, fleet reported against deliverable, and two gaps no dashboard shows |
| `/case/prize.html` | 3 · The prize | Value ranges for five separate branches, none counted twice; one has no verified figure and says so |
| `/case/solution.html` | 4 · The solution | Question to sign-off flow; what the demo simulates and what production uses |
| `/case/proof.html` | 5 · The proof | Eval results with their denominators, and one grounding example worked through |
| `/workspace/value.html` | Value | Seven desk metrics, each with a band or "no verified benchmark held" |
| `/workspace/` | Cockpit | The v1 desk panels restyled: market, position, fleet, CFE, queue and chat |
| `/workspace/swarm.html` | Agent teams | The six agents; flow nodes light up from the live event stream |
| `/workspace/persona.html` | My role | The four PRD roles, each with live figures and its own questions |
| `/workspace/handover.html` | Handover | "Write this brief now": each team writes its own part, or says it was not asked |

New read-only endpoints: `/api/story/{facts,gap,evidence,case,plan,prize,proof,value,provenance,limits}`,
`/api/agents` and `/api/personas`. `/api/actions` now carries `unsettled` for each action (what it could not settle).
A failed model call ends the stream with an `error` event ("no answer: <reason>"), never a `final`. An approval that
would cover more than the open short is refused with a 409.

### Pages (headless Chromium, 1440 and 390 px, zero console errors, no horizontal scroll)

| Page | 1440 px | 390 px |
|---|---|---|
| Landing | <img src="docs/img/v2/landing_1440.jpg" width="420"> | <img src="docs/img/v2/landing_390.jpg" width="140"> |
| The case | <img src="docs/img/v2/case_index_1440.jpg" width="420"> | <img src="docs/img/v2/case_index_390.jpg" width="140"> |
| The gap | <img src="docs/img/v2/case_gap_1440.jpg" width="420"> | <img src="docs/img/v2/case_gap_390.jpg" width="140"> |
| The prize | <img src="docs/img/v2/case_prize_1440.jpg" width="420"> | <img src="docs/img/v2/case_prize_390.jpg" width="140"> |
| The solution | <img src="docs/img/v2/case_solution_1440.jpg" width="420"> | <img src="docs/img/v2/case_solution_390.jpg" width="140"> |
| The proof | <img src="docs/img/v2/case_proof_1440.jpg" width="420"> | <img src="docs/img/v2/case_proof_390.jpg" width="140"> |
| Value | <img src="docs/img/v2/workspace_value_1440.jpg" width="420"> | <img src="docs/img/v2/workspace_value_390.jpg" width="140"> |
| Cockpit | <img src="docs/img/v2/workspace_index_1440.jpg" width="420"> | <img src="docs/img/v2/workspace_index_390.jpg" width="140"> |
| Agent teams | <img src="docs/img/v2/workspace_swarm_1440.jpg" width="420"> | <img src="docs/img/v2/workspace_swarm_390.jpg" width="140"> |
| My role | <img src="docs/img/v2/workspace_persona_1440.jpg" width="420"> | <img src="docs/img/v2/workspace_persona_390.jpg" width="140"> |
| Handover | <img src="docs/img/v2/workspace_handover_1440.jpg" width="420"> | <img src="docs/img/v2/workspace_handover_390.jpg" width="140"> |

### Live runs, 2026-09-27 (each image carries an orange "Live run" label)

These are real Gemini runs on the local DuckDB backend: S1 on Agent teams took 58 s, one risk-manager question on My
role took 28 s, and "Write this brief now" took 86 s. `eval/live_ui_capture.py` recorded each run's event stream
from the real `/api/chat` endpoint, and the stream was played into the page at 4x its recorded pace. The sandbox
blocks binding a local port, so no browser reached a running server. Details: `docs/EVAL_REPORT.md`, "UI v2
verification".

| Step | 1440 px | 390 px |
|---|---|---|
| S1 mid-run: the lead routes, trading is asked | <img src="docs/img/v2/live_swarm_running_1440.jpg" width="420"> | <img src="docs/img/v2/live_swarm_running_390.jpg" width="140"> |
| S1 finished: two proposals, both passed by the auditor | <img src="docs/img/v2/live_swarm_done_1440.jpg" width="420"> | <img src="docs/img/v2/live_swarm_done_390.jpg" width="140"> |
| Sign-off sheet: what it could not settle comes first | <img src="docs/img/v2/live_signoff_1440.jpg" width="420"> | <img src="docs/img/v2/live_signoff_390.jpg" width="140"> |
| My role, retail risk manager: margin at risk | <img src="docs/img/v2/live_persona_risk_1440.jpg" width="420"> | <img src="docs/img/v2/live_persona_risk_390.jpg" width="140"> |
| Handover written; onboarding "not asked" | <img src="docs/img/v2/live_handover_1440.jpg" width="420"> | <img src="docs/img/v2/live_handover_390.jpg" width="140"> |

### Replays of recorded runs, not live (each image carries an orange "Replay" label)

`eval/replay.py` rebuilds the 2026-09-26 live probe recordings (`eval/results/probes/`) and pushes them through the
server's own event conversion. Replays are for verification and fallback only; the page never presents one as a
live answer.

| Step | 1440 px | 390 px |
|---|---|---|
| S1 mid-run | <img src="docs/img/v2/replay_swarm_running_1440.jpg" width="420"> | <img src="docs/img/v2/replay_swarm_running_390.jpg" width="140"> |
| S1 finished | <img src="docs/img/v2/replay_swarm_done_1440.jpg" width="420"> | <img src="docs/img/v2/replay_swarm_done_390.jpg" width="140"> |
| Sign-off sheet | <img src="docs/img/v2/replay_signoff_1440.jpg" width="420"> | <img src="docs/img/v2/replay_signoff_390.jpg" width="140"> |
| My role, account manager: S4 with the injected bill flagged | <img src="docs/img/v2/replay_persona_account_1440.jpg" width="420"> | <img src="docs/img/v2/replay_persona_account_390.jpg" width="140"> |
| Handover from the S9 recording | <img src="docs/img/v2/replay_handover_1440.jpg" width="420"> | <img src="docs/img/v2/replay_handover_390.jpg" width="140"> |
| A failed model call (expired credentials): "no answer" and the reason, flow stopped | <img src="docs/img/v2/replay_error_no_answer_1440.jpg" width="420"> | <img src="docs/img/v2/replay_error_no_answer_390.jpg" width="140"> |

## Architecture

```mermaid
flowchart LR
  UI["Cloud Run UI + API<br/>Hold-to-Confirm, audit"] <--> ORCH["desk_orchestrator<br/>Agent Runtime"]
  ORCH --> TR[trading_dispatch] & CR[contract_risk] & ON[onboarding] & CF[cfe_provenance] & AU[risk_auditor]
  TR & CR & ON & CF & AU --> BQ[("BigQuery<br/>tepco_retail_desk_demo")]
  JEPX["JEPX API via Apigee<br/>(production)"] -.-> BQ
  DER["VPP telemetry via Pub/Sub + Dataflow<br/>(production)"] -.-> BQ
  WX["WeatherNext 3<br/>(production)"] -.-> BQ
```
Full diagram with "demo simulates / production uses" labels: `docs/TECHNICAL_DESIGN.md`.

## Evaluation summary

See `docs/EVAL_REPORT.md` for denominators, retries and every failure with evidence.

<!-- EVAL:BEGIN -->
| Suite | First attempt | After one retry |
|---|---|---|
| ADK AgentEvaluator (trajectory + rubric + hallucination) | 18/19 | 19/19 |
| Grounding (SQL truth at test time) | 10/10 | 10/10 |
| Safety (injection, refusal, HITL) | 9/9 | 9/9 |
| pytest | 102 passed, 1 skipped (twice) | |
<!-- EVAL:END -->

## Scenarios

S1 gate-closure hedge, S2 deviation-band breaches, S3 margin at risk, S4 onboard the Inzai data-center prospect with
a 90% hourly CFE PPA (bill contains a prompt injection), S5 certificate ledger audit, S6 refusal to leave a slot short
on purpose, S7 refusal to execute without approval, S8 untrusted VPP clusters, S9 16:00 desk brief, S10 hourly vs
annual CFE. Click-by-click: `docs/DEMO_SCRIPT.md`.
