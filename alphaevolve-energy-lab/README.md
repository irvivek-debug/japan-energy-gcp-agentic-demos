# AlphaEvolve Energy Lab

Evolutionary code search (AlphaEvolve contract) on two Japanese electricity problems for a fictional retail balance
group, Kanto Balance Group (KBG): **C&I tariff pricing** (TEPCO Energy Partner tariff book; Mitsubishi Electric
gain-share pricing) and **JEPX trading** (day-ahead + intraday + 60 MW / 180 MWh battery; MELCO BESS-as-a-Service).

**Honest status.** There is no Gemini Enterprise app with AlphaEvolve provisioned for this project. All runs here are
**AlphaEvolve-compatible runs on a local Gemini controller** (`source: "local-gemini-controller"`, `evolved: false`).
The production path (`energy_lab/harness/alphaevolve_adapter.py`, the real `alpha_evolve` client on discoveryengine,
location global) uses the same evaluator, sandbox, baseline lock, budget ledger, holdout and evidence schema: switching
is one flag (`--backend alphaevolve` with `GE_APP_ID`).

Concept demo. Synthetic, calibrated data (targets from `docs/research/MARKET_FACTS.md`). Not affiliated with or
endorsed by TEPCO or Mitsubishi Electric.

## 5-minute quickstart (local)

```bash
cd showcase/alphaevolve-energy-lab
../../.venv/bin/python data/generate.py                      # deterministic data + instances (~4 s)
../../.venv/bin/python -m energy_lab.harness.run --verify    # baseline locks reproduce to the yen
../../.venv/bin/python -m pytest -q tests                    # harness, invariants, sandbox, data, tools, server
../../.venv/bin/python -m uvicorn server.app:app --port 8083 # UI at http://localhost:8083
```

Live search (Gemini at location global; ADC):

```bash
GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global GOOGLE_CLOUD_PROJECT=<project> \
  ../../.venv/bin/python -m energy_lab.harness.run --problem tariff_pricing          # or jepx_trading
../../.venv/bin/python -m energy_lab.export_evidence                                  # evidence -> lab_* tables
../../.venv/bin/python -m energy_lab.harness.run --problem jepx_trading --dry-run     # offline mutator, never evidence
```

## Architecture

```
data/generate.py ─▶ data/out/*.csv (BigQuery-ready, schema.json) ─▶ STORE (DuckDB local / BigQuery deployed)
        │                                                               ▲
        └▶ data/instances/*.npz (content-hashed, read-only) ─▶ evaluator ◀── local controller (Gemini 3.6 Flash 0.7 / 3.1 Pro 0.3)
                                                                 │      ◀── AlphaEvolve adapter (production path)
             sandbox child (untrusted policy code, decisions only) ┘
evaluator ─▶ runs/<problem>.<started>.json (never overwritten) ─▶ export_evidence ─▶ lab_* tables ─▶ Lab Analyst (ADK)
server/app.py (FastAPI /api + SSE chat + HITL) ─▶ ui/ (Evolution Lab)
```

| Path | What |
|---|---|
| `energy_lab/sim/` | market model (weather, demand, solar, reserve margin, spot, intraday, imbalance), FY2026 scenario banks, portfolio, assets, instance builders |
| `energy_lab/problems/tariff_pricing/` | seed / null programs (EVOLVE-BLOCK), vectorised FY2026 settlement model, evaluator with policy invariants (v4: v3 rules plus a pre-registered sampling margin for per-segment churn on holdout3) |
| `energy_lab/problems/jepx_trading/` | seed / null programs, trusted day-by-day simulator, evaluator with compliance invariants |
| `energy_lab/harness/` | contract, packaging, sandbox, diff, baseline lock, budget ledger, evidence + promotion gate, local controller, AlphaEvolve adapter, CLI |
| `energy_lab/agent.py`, `tools/` | Lab Analyst (Pattern B, balanced tier, 9 tools, no execute/promote tool) |
| `server/`, `ui/` | Evolution Lab dashboard |
| `eval/` | ADK eval (12 cases), grounding eval, safety eval |
| `runs/` | evidence files, budget ledger, logs, append-only review log |

## Results at a glance (7 searched runs, 280 program slots of which 279 generated a program, about USD 9.6 estimated; plus 2 zero-program attempts)

| Problem | Runs | Train (seed -> best) | Holdout delta (only citable number) | Invalid caught |
|---|---|---|---|---|
| tariff_pricing | 3 (evaluator v1, v2, v3 + fresh holdout) | -8,800 -> -3,290 / -2,585 / -2,033 JPY M | **none validated**: every champion broke small-segment churn protection on unseen customers | 6 churn (policy), 1 diff |
| tariff_pricing run 4 | pre-registered (evaluator v4, 1,200-customer holdout3) | -8,800 -> -2,159 JPY M | **+21,190.9 JPY M, uplift_valid true**, but the 14-customer semiconductor segment passes only with the pre-registered sampling margin (+5.1 pp vs a 5 pp point limit) | 2 churn (policy), 1 generation; 2 earlier zero-program attempts (credentials, operator error) |
| jepx_trading | 3 (evaluator v1, v1, v2) | -85,419 -> -85,373 / -85,370 / -85,398 JPY M/yr | **+397.3 / +323.2 / +205.8 JPY M**, all slots compliant (mostly from stress days) | 3 intentional imbalance, 1 diff, 1 sandbox |

All runs are local-controller runs: `evolved = false`, nothing is promotable. Evaluation: see `docs/EVAL_REPORT.md`
and the mutation check (16/16 gates). The pre-registration for the tariff follow-up is `docs/PREREGISTRATION_tariff_v4.md`;
it was run with one command, `python -m energy_lab.followup tariff_v4`, and the affected analyst evals with
`python eval/rerun_affected.py` (both refuse without usable Vertex AI credentials).

## UI (version 2 at `/`, version 1 at `/v1/`)

`../../.venv/bin/python -m uvicorn server.app:app --port 8083`, then open http://localhost:8083. Version 2 follows the
shared design language in `../docs/DESIGN_V2.md` (accent `#8fd0bc`) and reads every figure from `/api` (read-only
`/api/v2/*` endpoints in `server/v2_api.py`, plus the v1 endpoints). Every screen that shows a run says "local
controller, not the managed AlphaEvolve service".

| Family | Pages | What it shows |
|---|---|---|
| Landing | `/` | the thesis, the gap measured in this data against cited research, a time scrubber over FY2025 evidence, two doors |
| The case for change | `/case/index.html`, `gap.html`, `prize.html`, `solution.html`, `proof.html` | 1 case, 2 gap (seed vs champion on holdout per run, status label per run), 3 prize (ranges only), 4 solution (candidate path and demo vs production), 5 proof (tests, mutations, ADK, grounding, safety) |
| Workspace | `/workspace/value.html`, `index.html` (Cockpit), `swarm.html` (Agent teams), `persona.html` (My role), `handover.html` | metric ranges, run cockpit and scenario explorer, the Lab Analyst chat with its flow, role views, the promotion dossier and brief |
| Version 1 | `/v1/` | the unchanged control-room dashboard |

The only write on any page is "Mark human-reviewed", which opens the sign-off sheet (2-second hold) and appends to
`runs/reviews.jsonl`; "Promote to production" stays disabled with its reason. A failed model call shows the server's
error line, never a made-up answer. Screenshots at 1440 px and 390 px: `docs/img/v2/`.

## Results and evaluation

See `docs/RESULTS.md` (seed vs null vs best on train and holdout, invariant catches, costs) and `docs/EVAL_REPORT.md`.
Design: `docs/PRD.md`, `docs/TECHNICAL_DESIGN.md`, `docs/SCENARIO_AND_DATA.md`. Demo: `docs/DEMO_SCRIPT.md`.
Deployment: `deploy/DEPLOY.md`.
