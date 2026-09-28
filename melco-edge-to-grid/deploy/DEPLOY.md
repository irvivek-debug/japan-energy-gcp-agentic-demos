# Deploy: Edge-to-Grid Factory Energy Copilot

All commands use placeholders. Never commit a project id, account or key. Region for data and services:
**asia-northeast1 (Tokyo)**; Gemini 3.x models are called at the **global** endpoint.

| Resource | Name (default) | Notes |
|---|---|---|
| BigQuery dataset | `melco_edge_to_grid_demo` (asia-northeast1) | 18 tables from `data/out/*.csv`, types from `data/schema.json` |
| Agent Runtime app (formerly Agent Engine) | `factory-energy-copilot` (asia-northeast1) | `factory_copilot.agent.root_agent`; ships `factory_copilot/` only (schema.json and corpus/ are inside it) |
| Cloud Run service | `factory-energy-command` (asia-northeast1) | `Dockerfile`, UI + API, HITL queue; `AGENT_BACKEND=agent_engine` |
| Service accounts | `sa-agent-runtime`, `sa-web` | Least privilege (below) |
| Staging bucket | `gs://${GOOGLE_CLOUD_PROJECT}-melco-e2g-staging` (asia-northeast1) | Agent Runtime packaging |

```bash
export GOOGLE_CLOUD_PROJECT=<your-project>        # never written to a file
export REGION=asia-northeast1
export DATASET=melco_edge_to_grid_demo
```

## 1. Data: BigQuery

Regenerate (optional, deterministic) and load with the Python SDK (ADC):

```bash
cd melco-edge-to-grid
python data/generate.py                  # writes data/out/*.csv, data/schema.json, factory_copilot/schema.json
python - <<'EOF'
import json, os
from google.cloud import bigquery
project, region, dataset = os.environ["GOOGLE_CLOUD_PROJECT"], "asia-northeast1", "melco_edge_to_grid_demo"
bq = bigquery.Client(project=project, location=region)
bq.create_dataset(bigquery.Dataset(f"{project}.{dataset}"), exists_ok=True)
schema = json.load(open("data/schema.json"))["tables"]
for name, spec in schema.items():
    job = bq.load_table_from_file(
        open(f"data/out/{name}.csv", "rb"), f"{project}.{dataset}.{name}",
        job_config=bigquery.LoadJobConfig(source_format="CSV", skip_leading_rows=1, write_disposition="WRITE_TRUNCATE",
                                          schema=[bigquery.SchemaField(c["name"], c["type"], description=c["description"]) for c in spec["columns"]]))
    job.result(); print(name, bq.get_table(f"{project}.{dataset}.{name}").num_rows)
EOF
```

gcloud / bq equivalent (per table): `bq --location=$REGION mk -d $GOOGLE_CLOUD_PROJECT:$DATASET` then
`bq load --source_format=CSV --skip_leading_rows=1 $DATASET.<table> data/out/<table>.csv <schema.json for that table>`.

Verify the tools on BigQuery: `DATA_BACKEND=bigquery BQ_PROJECT=$GOOGLE_CLOUD_PROJECT python -m pytest tests/test_bigquery_backend.py`.

## 2. Service accounts (least privilege)

```bash
gcloud iam service-accounts create sa-agent-runtime --project $GOOGLE_CLOUD_PROJECT
gcloud iam service-accounts create sa-web --project $GOOGLE_CLOUD_PROJECT
# agents: read the dataset, run jobs, call models
bq add-iam-policy-binding --member=serviceAccount:sa-agent-runtime@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com --role=roles/bigquery.dataViewer $GOOGLE_CLOUD_PROJECT:$DATASET
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT --member=serviceAccount:sa-agent-runtime@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com --role=roles/bigquery.jobUser
gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT --member=serviceAccount:sa-agent-runtime@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com --role=roles/aiplatform.user
# web: query the agent + read the dataset for the dashboard
for r in roles/aiplatform.user roles/bigquery.jobUser; do gcloud projects add-iam-policy-binding $GOOGLE_CLOUD_PROJECT --member=serviceAccount:sa-web@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com --role=$r; done
bq add-iam-policy-binding --member=serviceAccount:sa-web@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com --role=roles/bigquery.dataViewer $GOOGLE_CLOUD_PROJECT:$DATASET
```

No keys. Argolis organisations enforce domain-restricted sharing: do not bind `allUsers`; share the UI through IAP with named users.

## 3. Agents: Agent Runtime (Python SDK)

```python
import os, vertexai
from vertexai import agent_engines
from factory_copilot.agent import root_agent      # import builds the datastore only; no model or network calls

project, region = os.environ["GOOGLE_CLOUD_PROJECT"], "asia-northeast1"
vertexai.init(project=project, location=region, staging_bucket=f"gs://{project}-melco-e2g-staging")
app = agent_engines.AdkApp(agent=root_agent, enable_tracing=True)
remote = agent_engines.create(
    agent_engine=app,
    display_name="factory-energy-copilot",
    requirements=open("requirements.txt").read().split("\n"),
    extra_packages=["factory_copilot"],                    # schema.json and corpus/ ship inside the package
    env_vars={
        "GOOGLE_GENAI_USE_VERTEXAI": "TRUE",
        "GOOGLE_CLOUD_LOCATION": "global",                  # Gemini 3.x resolves only at global
        "DATA_BACKEND": "bigquery",
        "BQ_PROJECT": project,                             # Agent Runtime may expose the project as a number
        "BQ_DATASET": "melco_edge_to_grid_demo",
        "BQ_LOCATION": region,
        "MODEL_REASONING": "gemini-3.1-pro-preview",
        "MODEL_BALANCED": "gemini-3.6-flash",
    },
    service_account=f"sa-agent-runtime@{project}.iam.gserviceaccount.com",
)
print(remote.resource_name)    # -> AGENT_ENGINE_ID for Cloud Run
```

If the runtime reserves `GOOGLE_CLOUD_LOCATION`, apply the same global-endpoint override used for the other demos in this repository (the model location must stay `global`; data and runtime stay in asia-northeast1).

Smoke test: `remote.stream_query(user_id="smoke", message="How confident is the PV forecast this afternoon?")` should call `market_intelligence_agent` then `get_pv_forecast` and cite `[melco_edge_to_grid_demo.pv_forecast_30min]`.

## 4. UI and API: Cloud Run

```bash
gcloud run deploy factory-energy-command --source . --region $REGION --project $GOOGLE_CLOUD_PROJECT \
  --service-account sa-web@$GOOGLE_CLOUD_PROJECT.iam.gserviceaccount.com \
  --no-allow-unauthenticated --max-instances 1 --memory 2Gi --cpu 2 --timeout 600 \
  --set-env-vars GOOGLE_CLOUD_PROJECT=$GOOGLE_CLOUD_PROJECT,GOOGLE_GENAI_USE_VERTEXAI=TRUE,GOOGLE_CLOUD_LOCATION=global,AGENT_BACKEND=agent_engine,AGENT_ENGINE_ID=<resource name from step 3>,AGENT_ENGINE_LOCATION=$REGION,DATA_BACKEND=bigquery,BQ_PROJECT=$GOOGLE_CLOUD_PROJECT,BQ_DATASET=$DATASET,BQ_LOCATION=$REGION
```

* Entrypoint: `CMD exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT}` (PORT defaults to 8080).
* `--max-instances 1` keeps the in-memory pending-action queue and audit log on one instance for the demo (production: Firestore).
* Put IAP in front (or use `gcloud run services proxy` for a private demo).
* The dashboard panels query BigQuery directly through the same tool functions; the chat streams from Agent Runtime and the server lifts `pending_action` payloads out of the event stream.

Verify: `curl -H "Authorization: Bearer $(gcloud auth print-identity-token)" https://<service-url>/api/health` returns `{"ok": true, "agent_backend": "agent_engine", "data_backend": "bigquery", ...}`.

## 5. Evaluate the deployment

From the demo root with the same env vars as local:
`python eval/run_adk_eval.py` (ADK suite, local runner against BigQuery with `DATA_BACKEND=bigquery`), `python eval/grounding_eval.py`, `python eval/safety_eval.py`. Update `docs/EVAL_REPORT.md` from `eval/results/`.

## 6. Entrypoints summary

| What | Entrypoint |
|---|---|
| Agent root | `factory_copilot.agent:root_agent` (package `factory_copilot`, `__init__` imports `agent`) |
| Server | `server.app:app` (FastAPI) |
| Data | `data/generate.py`, `data/schema.json`, `data/out/*.csv` |
| Evals | `eval/run_adk_eval.py`, `eval/grounding_eval.py`, `eval/safety_eval.py` |
| Env template | `.env.example` |

## Version alpha as a second service

Deploy the same image a second time as `<service>-alpha` with `UI_VARIANT=alpha` and otherwise identical env (same `AGENT_ENGINE_ID`, same dataset). It serves the CEO story at `/`, version 2 at `/v2/` and version 1 at `/v1/`; `/api/health` reports `ui_variant`. The Dockerfile already copies `ui-alpha/`.
