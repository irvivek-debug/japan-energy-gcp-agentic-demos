# Deploying the Retail Energy Desk (central deployment hand-off)

Region: **asia-northeast1 (Tokyo)** for BigQuery, Agent Runtime (formerly Vertex AI Agent Engine) and Cloud Run.
Models are called at the **global** location (Gemini 3.x resolves only there); the package pins this with
`MODEL_LOCATION=global` through ADK's `Gemini(client_kwargs=...)`, so it does not depend on the reserved
`GOOGLE_CLOUD_LOCATION` of the runtime. All commands use placeholders; never write a project id into a file.

## Resources

| Resource | Name | Notes |
|---|---|---|
| BigQuery dataset | `tepco_retail_desk_demo` | 20 tables from `data/schema.json` + `data/out/*.csv` (28 MB, ~440k rows) |
| Agent Runtime app | `retail-energy-desk` | `retail_desk.agent:root_agent` wrapped in `AdkApp` (app_name `retail_desk`) |
| Cloud Run service | `retail-energy-desk` | `Dockerfile`, `uvicorn server.app:app`, port `$PORT` (8080) |
| Service accounts | `desk-agent@`, `desk-ui@` | least privilege, see below; no keys (Workload Identity / attached SA only) |

## 1. Environment

```bash
export GOOGLE_CLOUD_PROJECT=<your-project>        # never commit
export BQ_PROJECT=${GOOGLE_CLOUD_PROJECT}
export BQ_DATASET=tepco_retail_desk_demo
export REGION=asia-northeast1
export STAGING_BUCKET=gs://${GOOGLE_CLOUD_PROJECT}-agent-staging-${REGION}
```

## 2. Service accounts (least privilege)

```bash
gcloud iam service-accounts create desk-agent --display-name "Retail desk agents (Agent Runtime)"
gcloud iam service-accounts create desk-ui --display-name "Retail desk UI (Cloud Run)"
# Agents: read the dataset, run query jobs, call Gemini
gcloud projects add-iam-policy-binding ${GOOGLE_CLOUD_PROJECT} --member serviceAccount:desk-agent@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com --role roles/bigquery.jobUser
gcloud projects add-iam-policy-binding ${GOOGLE_CLOUD_PROJECT} --member serviceAccount:desk-agent@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com --role roles/aiplatform.user
bq add-iam-policy-binding --member=serviceAccount:desk-agent@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com --role=roles/bigquery.dataViewer ${GOOGLE_CLOUD_PROJECT}:${BQ_DATASET}
# UI: dashboards read the dataset and call the deployed agent
gcloud projects add-iam-policy-binding ${GOOGLE_CLOUD_PROJECT} --member serviceAccount:desk-ui@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com --role roles/bigquery.jobUser
gcloud projects add-iam-policy-binding ${GOOGLE_CLOUD_PROJECT} --member serviceAccount:desk-ui@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com --role roles/aiplatform.user
bq add-iam-policy-binding --member=serviceAccount:desk-ui@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com --role=roles/bigquery.dataViewer ${GOOGLE_CLOUD_PROJECT}:${BQ_DATASET}
```
Argolis note: if the project enforces domain-restricted sharing, bind only identities from the allowed domain and
do not use `allUsers` on Cloud Run; front the service with IAP or `--no-allow-unauthenticated`.

## 3. BigQuery (Python SDK)

```bash
python deploy/load_bigquery.py            # creates the dataset in asia-northeast1, loads 20 tables WRITE_TRUNCATE
DATA_BACKEND=bigquery python -m pytest -q tests/test_bigquery_backend.py   # parity: BigQuery answers == DuckDB answers
```

## 4. Agent Runtime (Python SDK)

```bash
AGENT_SA=desk-agent@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com python deploy/deploy_agent_engine.py
# prints AGENT_ENGINE_ID = projects/.../locations/asia-northeast1/reasoningEngines/...
```
Shipped: only `retail_desk/` (it contains `schema.json` and `corpus/`). Env set on the runtime: `DATA_BACKEND=bigquery`,
`BQ_DATASET`, `BQ_PROJECT`, `BQ_LOCATION`, `GOOGLE_GENAI_USE_VERTEXAI=TRUE`, `MODEL_LOCATION=global`, `MODEL_*`.
Importing `retail_desk.agent` has no side effects beyond building the DataStore (tested in `tests/test_server.py`).

## 5. Cloud Run (UI + API)

```bash
gcloud run deploy retail-energy-desk --source . --region ${REGION} \
  --service-account desk-ui@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com --no-allow-unauthenticated \
  --set-env-vars DATA_BACKEND=bigquery,BQ_DATASET=${BQ_DATASET},BQ_PROJECT=${GOOGLE_CLOUD_PROJECT},BQ_LOCATION=${REGION},AGENT_BACKEND=agent_engine,AGENT_ENGINE_ID=<id-from-step-4>,AGENT_ENGINE_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=TRUE,MODEL_LOCATION=global \
  --memory 2Gi --cpu 2 --min-instances 1 --timeout 600
```
The server lifts pending actions from the Agent Runtime event stream exactly as in local mode; Hold-to-Confirm
executes only in the server's sandbox and writes the audit log (in memory for the demo; Firestore or BigQuery in a pilot).

## 6. Smoke test after deploy

```bash
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" https://<service-url>/api/health
curl -s -H "Authorization: Bearer $(gcloud auth print-identity-token)" https://<service-url>/api/kpis
```
Then run S1 from the UI ("Gate-closure hedge"): expect two pending actions (intraday and VPP), both audited PASS,
VPP-R-17 excluded. For a grounding check against the deployed stack, run `python eval/grounding_eval.py S1,S5`
with `DATA_BACKEND=bigquery`.

## Entrypoints

| What | Entrypoint |
|---|---|
| Agent | `retail_desk.agent:root_agent` (package `retail_desk`, `__init__` imports `agent`) |
| Server | `server.app:app` (FastAPI; `/api/*`, SSE `/api/chat`, static `ui/`) |
| Data load | `deploy/load_bigquery.py` |
| Agent deploy | `deploy/deploy_agent_engine.py` |
