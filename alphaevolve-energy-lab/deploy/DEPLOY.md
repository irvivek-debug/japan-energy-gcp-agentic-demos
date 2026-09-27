# Deploy: AlphaEvolve Energy Lab

Region for data, Agent Runtime and Cloud Run: **asia-northeast1**. Gemini 3.x models are called at **global**.
Placeholders: `${GOOGLE_CLOUD_PROJECT}`, `${REGION}=asia-northeast1`, `${DATASET}=energy_alphaevolve_lab`. Nothing in this
repository identifies a project. Deployment is done centrally; demo builders do not deploy.

## 0. Before you start (workstation)

```bash
python data/generate.py                        # CSVs, schema.json, instances (deterministic)
python -m energy_lab.harness.run --verify      # baseline locks reproduce (refuses on a different CPU/libm: re-lock deliberately)
python -m energy_lab.export_evidence           # lab_* tables from runs/*.json
python -m pytest -q tests                      # harness, data, tools, server
```

## 1. BigQuery dataset and tables

```bash
bq --location=${REGION} mk --dataset ${GOOGLE_CLOUD_PROJECT}:${DATASET}
python - <<'EOF'
import json, subprocess
schema = json.load(open("data/schema.json"))["tables"]
for name, spec in schema.items():
    cols = ",".join(f"{c['name']}:{c['type']}" for c in spec["columns"])
    subprocess.run(["bq", "load", "--replace", "--source_format=CSV", "--skip_leading_rows=1",
                    f"${GOOGLE_CLOUD_PROJECT}:${DATASET}.{name}", f"data/out/{name}.csv", cols], check=True)
EOF
```

SDK alternative: `google.cloud.bigquery.Client(location="asia-northeast1").load_table_from_file(..., job_config=LoadJobConfig(schema=[SchemaField(...)]))`
with the same schema. Re-run `energy_lab.export_evidence` and reload the five `lab_*` tables after every new run.

## 2. Service accounts (least privilege; no keys, use ADC / Workload Identity Federation)

| SA | Roles |
|---|---|
| `lab-analyst-runtime` | `roles/bigquery.dataViewer` on the dataset, `roles/bigquery.jobUser`, `roles/aiplatform.user` |
| `lab-ui` | `roles/bigquery.dataViewer` on the dataset, `roles/aiplatform.user` (to query Agent Runtime) |
| `lab-search` (optional, Cloud Run job) | `roles/aiplatform.user`, `roles/discoveryengine.user` (AlphaEvolve), `roles/bigquery.dataEditor` on lab_* only, object create on the evidence bucket (retention policy: no overwrite) |

## 3. Lab Analyst on Agent Runtime (Gemini Enterprise Agent Platform, formerly Vertex AI Agent Engine)

Agent Runtime ships only the `energy_lab/` package, so the agent reads evidence from the BigQuery `lab_*` tables and the
schema from `energy_lab/schema.json`.

```python
import vertexai
from vertexai import agent_engines
from energy_lab.agent import root_agent

vertexai.init(project="${GOOGLE_CLOUD_PROJECT}", location="asia-northeast1", staging_bucket="gs://${GOOGLE_CLOUD_PROJECT}-lab-staging")
app = agent_engines.AdkApp(agent=root_agent)
remote = agent_engines.create(
    app,
    requirements=open("requirements.txt").read().splitlines(),
    extra_packages=["energy_lab"],
    display_name="alphaevolve-energy-lab-analyst",
    env_vars={"DATA_BACKEND": "bigquery", "BQ_PROJECT": "${GOOGLE_CLOUD_PROJECT}", "BQ_DATASET": "energy_alphaevolve_lab",
              "BQ_LOCATION": "asia-northeast1", "GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "GOOGLE_CLOUD_LOCATION": "global",
              "MODEL_BALANCED": "gemini-3.6-flash"},
    service_account="lab-analyst-runtime@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com",
)
print(remote.resource_name)   # -> AGENT_ENGINE_ID for Cloud Run
```

Importing `energy_lab.agent` builds STORE and the agent object only; it makes no model or network calls.

## 4. Cloud Run (UI + API)

```bash
gcloud run deploy alphaevolve-energy-lab --source . --region ${REGION} \
  --service-account lab-ui@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com \
  --set-env-vars DATA_BACKEND=bigquery,BQ_PROJECT=${GOOGLE_CLOUD_PROJECT},BQ_DATASET=${DATASET},BQ_LOCATION=${REGION},AGENT_BACKEND=agent_engine,AGENT_ENGINE_ID=<resource name>,AGENT_ENGINE_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=global \
  --no-allow-unauthenticated
```

The Dockerfile runs `uvicorn server.app:app --host 0.0.0.0 --port ${PORT}` (PORT=8080). The container serves the
committed evidence in `runs/` for the experiment views; it does not need the evaluator instances.

## 5. Real AlphaEvolve runs (when the Gemini Enterprise app is provisioned)

```bash
pip install alpha_evolve                        # ships with the GE AlphaEvolve provisioning (not pinned here)
export GOOGLE_CLOUD_PROJECT=... GE_APP_ID=<engine id>
python -m energy_lab.harness.run --problem tariff_pricing --backend alphaevolve
```

Same evaluator, sandbox, baseline lock, budget ledger, holdout rescoring and evidence schema as the local controller;
evidence records `source: "alphaevolve"`. `evolved` flips only through the promotion gate (holdout delta, uplift_valid,
human review, source).

## 6. Smoke checks after deploy

* `GET /api/health` shows `data_backend=bigquery`, `agent_backend=agent_engine`.
* Ask the analyst "Which evolution runs exist?"; it must cite `[energy_alphaevolve_lab.lab_runs]`.
* `POST /api/runs/<local run>/promote` must return 403.

## 7. Changes since v1.0.0 that affect a deployment (2026-09-27)

* `lab_reviews.at` is renamed `reviewed_at` (`AT` is a reserved word; `get_holdout_result` returned a SQL error on
  DuckDB, and the same query is expected to fail on BigQuery, where `AT` is also reserved). Reload the five `lab_*` tables with
  `--replace` from the new `data/out` and redeploy the analyst package (tool query changed).
* New tables `customers_holdout3` and `customer_behaviour_holdout3` (1,200 rows each), a new tariff evidence file
  (run 4, infrastructure failure) and new read-only endpoints `/api/v2/*` for UI version 2 (served at `/`; version 1 at
  `/v1/`). Cloud Run needs a new revision; no new permissions.
* New table `lab_segment_judgments` (per-segment churn judgment of every top-k candidate of a margin-judged tariff run,
  recomputed by `energy_lab.export_evidence` without a model call) and new columns `lab_runs.uplift_caveat`,
  `lab_holdout.valid_point_rules`, `lab_holdout.relies_on_margin`, `lab_holdout.judgment_note`. Load the new table,
  reload `lab_runs` and `lab_holdout` with `--replace` from `data/out` using the regenerated `data/schema.json`, and
  redeploy the analyst package (four tool queries changed: `list_runs`, `get_run_summary`, `get_best_program_diff`,
  `get_holdout_result`).
