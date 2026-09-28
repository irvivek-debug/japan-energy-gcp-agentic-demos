# Evolution Lab UI + API (Cloud Run). The Lab Analyst runs in-process (AGENT_BACKEND=local) or on Agent Runtime
# (AGENT_BACKEND=agent_engine). Data: DuckDB over the committed data/out CSVs (DATA_BACKEND=local) or BigQuery
# (DATA_BACKEND=bigquery). Evaluator instances (*.npz, gitignored) are NOT needed to serve the UI; searches run where
# `python data/generate.py && python -m energy_lab.harness.run --verify` succeeds (the lock refuses on a hash mismatch).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# ui/ (version 2), ui/v1/ and ui-alpha/ (the CEO story) all ship; UI_VARIANT=alpha serves ui-alpha/ at / (v2 at /v2/, v1 at /v1/).
CMD exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT}
