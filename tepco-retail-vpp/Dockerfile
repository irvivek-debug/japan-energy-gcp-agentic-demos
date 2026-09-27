# Retail Energy Desk UI + API (Cloud Run). Agents run in-process (AGENT_BACKEND=local) or on Agent Runtime
# (AGENT_BACKEND=agent_engine). Data comes from BigQuery (DATA_BACKEND=bigquery) or the bundled CSVs (local).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY retail_desk/ retail_desk/
COPY server/ server/
COPY ui/ ui/
COPY data/out/ data/out/
# The proof chapter reads the evaluation summaries and the grounding truth method (no model is called at runtime).
COPY eval/results/ eval/results/
COPY eval/grounding_eval.py eval/harness.py eval/
RUN useradd --create-home --uid 10001 app && chown -R app /app
USER app
CMD exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT}
