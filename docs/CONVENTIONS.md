# Engineering Conventions (all three demos)

This repository holds three **independent** concept demos. Each demo folder must build, test, evaluate and
deploy on its own; copy shared reference code in, never import across demo folders.

| Folder | Demo | UI accent |
|---|---|---|
| `tepco-retail-vpp/` | TEPCO Energy Partner: Retail Energy Desk (Mega-VPP, algorithmic hedging, 24/7 CFE PPAs) | `#a7caed` |
| `melco-edge-to-grid/` | Mitsubishi Electric: Edge-to-Grid Factory Energy Copilot (GDC Edge interlocks, Auto-DR, BESS-as-a-Service) | `#b8a6f0` |
| `alphaevolve-energy-lab/` | Common: AlphaEvolve Energy Lab (tariff pricing + JEPX trading algorithm evolution) | `#7fd1c7` |

## 1. Runtime facts verified on 2026-09-26 (do not re-litigate)

* Python: use `<WORKSPACE>/.venv/bin/python` (3.12, ADK `google-adk==2.10.0`, `google-genai`, `vertexai`
  1.165, `duckdb`, `pandas`, `numpy`, `scipy`, `fastapi`, `uvicorn`, `pytest`, `google-cloud-bigquery`).
  Install anything extra with `UV_CACHE_DIR=<WORKSPACE>/.tools/uv-cache <WORKSPACE>/.tools/uvpkg/bin/uv pip install --python <WORKSPACE>/.venv/bin/python <pkg>`.
* Gemini 3.x on Vertex resolves **only at the `global` location** in this project. Always run with
  `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `GOOGLE_CLOUD_LOCATION=global`, `GOOGLE_CLOUD_PROJECT` from env.
* Model tiers (single source per demo: `<pkg>/model_policy.py`, env-overridable, never hardcode IDs elsewhere):

  | Tier | Env var | Default | Use |
  |---|---|---|---|
  | reasoning | `MODEL_REASONING` | `gemini-3.1-pro-preview` | Pattern A orchestrators, AlphaEvolve 30% mutator share |
  | balanced | `MODEL_BALANCED` | `gemini-3.6-flash` | Specialist agents, eval judge, AlphaEvolve 70% mutator share |
  | high-volume | `MODEL_FAST` | `gemini-3.5-flash-lite` | Cheap summarisation / classification |

  `gemini-3.1-pro` (non-preview) returns 404; the Gemini 2.5 family retires 2026-10-16, do not use it.
* Deployment region for BigQuery, Agent Engine and Cloud Run: **`asia-northeast1` (Tokyo)**. (us-central1 is
  near its Agent Engine quota from other work in this project.) Models are still called at `global`.
* gcloud CLI needs interactive re-auth; the Python SDKs work through ADC. Deployment is done centrally by the
  lead with Python SDKs. Demo builders **do not deploy**; they deliver the artifacts listed in section 8.
* Never write a project id, account email, token or key into any file. Read `GOOGLE_CLOUD_PROJECT` from env.
  The repository is going public.

## 2. Folder layout (per demo)

```
<demo>/
  README.md                      # what it is, 5-minute quickstart (local), architecture picture, eval summary
  docs/PRD.md                    # product requirements (template: section 9)
  docs/TECHNICAL_DESIGN.md       # architecture, data model, agents, access model, security, deployment
  docs/DEMO_SCRIPT.md            # click-by-click demo narrative with the exact prompts
  docs/EVAL_REPORT.md            # generated from the latest eval run, honest denominators
  data/generate.py               # deterministic synthetic data generator (seeded), writes data/out/*.csv
  data/schema.json               # {"tables": {name: {"description", "columns": [{"name","type","description"}]}}}
  data/out/*.csv                 # generated data (commit if total < 40 MB, else commit a smaller "demo" cut)
  <pkg>/__init__.py              # `from . import agent`
  <pkg>/agent.py                 # exposes root_agent
  <pkg>/model_policy.py
  <pkg>/datastore.py             # copied from docs/reference/datastore.py
  <pkg>/tools/*.py               # deterministic tools (plain functions with typed args + docstrings)
  eval/evalsets/*.test.json      # ADK eval sets
  eval/test_config.json          # ADK criteria
  eval/run_adk_eval.py           # runs AgentEvaluator over all eval sets, writes eval/results/*.csv
  eval/grounding_eval.py         # scenario probes, ground truth computed by SQL at test time
  eval/safety_eval.py            # prompt-injection, refusal, HITL no-execution probes
  server/app.py                  # FastAPI: /api/* + static ui/ + SSE chat (pattern: docs/reference/server_reference.py)
  ui/index.html, ui/app.js, ui/styles.css  (+ copied tokens.css, hold-to-confirm.js)
  tests/                         # pytest: generator properties, tool math, both SQL backends where possible
  requirements.txt               # exact pins (copy versions from the shared venv: `pip freeze`)
  Dockerfile                     # python:3.12-slim, uvicorn server.app:app on $PORT
  .env.example                   # every env var, no values that identify the project
```

## 3. Data layer

* Copy `docs/reference/datastore.py` unchanged. Tools issue parameterised SQL with `{t:table}` and `@param`.
  The same SQL runs on DuckDB-over-CSV (`DATA_BACKEND=local`, default) and BigQuery (`DATA_BACKEND=bigquery`).
* Column types come only from `data/schema.json` (`STRING`, `INT64`, `FLOAT64`, `BOOL`). Dates and timestamps
  are ISO strings (`2026-08-19`, `2026-08-19T17:30`). Add precomputed `date`, `slot` (1..48), `hour`, `month`
  columns instead of date functions. Only portable SQL (see datastore docstring).
* The generator is seeded and deterministic; tests assert **properties** (row counts derive from the config,
  anomalies present, invariants hold), not pinned literals.
* **Deliberate anomalies are mandatory**: agents that detect problems need problems present.
* Citations: agents cite structured sources as `[dataset.table]` using `STORE.source_label(table)`; documents
  as `[filename.ext Page N]` (or `[filename.ext Section N]` for text docs).

## 4. Agents (ADK 2.10)

* `from google.adk.agents import LlmAgent`; tools are plain typed functions with Google-style docstrings
  (`Args:` section). Tools never raise to the model: return `{"status": "error", "error": ...}`.
* Every tool result carries `"source": [<dataset.table>, ...]` so the model can cite and evals can check.
* **Shared preamble** prepended to every agent instruction (including custom ones): where the data lives
  (dataset name, "the dataset is never the project"), citation format, "never present a number you did not get
  from a tool; if the user supplies numbers, reconcile them against the tables and say which you used",
  plain business English, no em dashes, units always (JPY/kWh, MW, MWh, %).
* **HITL**: agents never execute write actions. Write-type tools are named `propose_*` and return
  `{"status": "pending_approval", "pending_action": {"kind", "summary", "details", "risk", "requires": "hold_to_confirm"}}`.
  The server lifts pending actions out of the event stream; the UI Hold-to-Confirm executes them in a sandbox and
  writes an audit record. There must be no `execute_*` tool reachable by any agent.
* Pattern A swarm: root orchestrator (reasoning tier) + specialists (balanced tier) via `sub_agents` or
  `AgentTool`; include a peer-critique auditor that checks grounding, HITL and regulatory rules before the
  orchestrator presents a recommendation.
* Keep tool counts per agent <= 10; keep instructions specific to the JTBD scenarios in the PRD.

## 5. Evaluation (required; this is how the demo is "tested")

1. **ADK evaluation** (`AgentEvaluator.evaluate`, verified working pattern in `docs/reference/`):
   `tool_trajectory_avg_score` (`match_type: ANY_ORDER` or `IN_ORDER`), `rubric_based_final_response_quality_v1`
   with case-specific rubrics, `hallucinations_v1`; judge model = balanced tier. >= 10 eval cases per demo
   covering every specialist agent and the end-to-end scenario.
2. **Grounding eval**: for each PRD scenario, compute ground truth with SQL at test time (never stored), run the
   agent, require (a) tool calls occurred, (b) the key figures in the answer match truth within tolerance.
   Label results `GROUNDED` / `UNGROUNDED` / `UNVERIFIABLE` (unverifiable is reported, never silently dropped).
3. **Safety eval**: prompt injection embedded in a document the agent reads; a user request that breaks a
   regulatory or safety rule (must refuse and explain); HITL (no write executes without confirmation).
4. Retry a failing case once and classify `transient` vs `persistent`; keep the first attempt as evidence.
   Store question, tool names, tool errors, reply and latency per case in `eval/results/`.
5. `docs/EVAL_REPORT.md` states pass counts with honest denominators and lists every skipped case by name.

## 6. UI

* Static HTML/JS (no build step), ECharts from `https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js`,
  copy `docs/reference/ui/tokens.css` and `hold-to-confirm.js`; set `--accent` per demo.
* Dark, flat, matte, 1px borders, bento grid, 44x44 px targets, color never the only signal, keyboard operable.
* Every screen: KPI strip bound to `/api/*` data (no hand-typed numbers), agent swarm console (live trace of
  agent, tool calls, results in JetBrains Mono), chat composer, pending-actions tray with Hold-to-Confirm that
  shows the agent's reasoning and source before confirm.
* User-facing copy: no em/en dashes, none of: delve, tapestry, testament, underscore, elevate, crucial, pivotal,
  vital, foster, vibrant, intricate, landscape, showcase, boasts.
* Footer on every page: `Concept demo. Synthetic data. Not affiliated with or endorsed by <company>.` No
  company logos or brand marks.

## 7. Server

* `server/app.py` follows `docs/reference/server_reference.py`: `/api/health`, domain `/api/*` endpoints for the
  dashboard, `/api/chat` (SSE), `/api/actions` + confirm/reject, static `ui/`.
* `AGENT_BACKEND=local` (ADK Runner in-process) or `agent_engine` (`AGENT_ENGINE_ID`, `AGENT_ENGINE_LOCATION`).
* Must start locally with: `cd <demo> && ../../.venv/bin/python -m uvicorn server.app:app --port 80xx`.

## 8. Hand-off artifacts for central deployment

* `data/schema.json` + `data/out/*.csv` (BigQuery load), dataset default name set in `<pkg>/datastore` init.
* `<pkg>/agent.py:root_agent` importable with no side effects beyond building the datastore.
* `requirements.txt`, `Dockerfile`, `.env.example`.
* `deploy/DEPLOY.md` describing the resources (dataset, Agent Engine app, Cloud Run service) with gcloud and
  SDK commands using `${GOOGLE_CLOUD_PROJECT}` placeholders.

## 9. PRD and Technical Design templates

**PRD** (`docs/PRD.md`): 1 Executive summary (value as ranges, CEO framing, "art of the possible") ·
2 Market context (cite `docs/research/MARKET_FACTS.md`) · 3 Problem statement (quantified) · 4 Personas
(Day in the Life, JTBD, empathy map) · 5 MECE issue tree with APQC codes · 6 Agent inventory table
(`Agent ID | Role | APQC | Pattern A/B/C | hitl_required | Originating JTBD | Data needed`) · 7 Scenarios
(each is simultaneously UAT probe, demo script and acceptance criterion) · 8 Success metrics with baselines ·
9 Functional + non-functional requirements · 10 Assumptions ledger (`* **ASSUMPTION**: ... — impact if wrong`)
and open questions · 11 Out of scope · 12 Roadmap (demo, pilot, production) · 13 Risks.

**Technical Design** (`docs/TECHNICAL_DESIGN.md`): 1 Architecture (Mermaid diagram: edge/source systems,
ingestion, BigQuery, agents on Agent Engine, Cloud Run UI, Apigee/JEPX, etc., mark what the demo simulates vs
what production uses) · 2 Data model (tables, DDL, relationships) · 3 Synthetic data spec (volumes,
distributions, calibration sources, deliberate anomalies) · 4 Agent architecture (per agent: pattern, tier,
tools, delegation, prompts summary) · 5 Deterministic math (formulas) · 6 Evaluation design · 7 Access model
(service accounts per tier, least privilege, WIF, no keys; Argolis-only domain binding warning) · 8 Security
(OWASP LLM top 10 mapping, prompt injection, DLP) · 9 Deployment (Agent Engine, Cloud Run, BigQuery,
asia-northeast1) · 10 Production path (what changes for real: Apigee JEPX API, Pub/Sub/Dataflow, GDC Edge,
Powerledger, etc.) · 11 Cost estimate (ranges).
