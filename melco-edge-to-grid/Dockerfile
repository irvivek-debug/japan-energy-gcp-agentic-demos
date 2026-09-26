# Factory Energy Command (UI + API + local agent runner). Cloud Run: PORT is injected; default 8080.
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY factory_copilot/ factory_copilot/
COPY server/ server/
COPY ui/ ui/
COPY data/out/ data/out/
COPY data/schema.json data/schema.json
# DATA_BACKEND=bigquery in production (data/out is only read when DATA_BACKEND=local)
CMD exec uvicorn server.app:app --host 0.0.0.0 --port ${PORT}
