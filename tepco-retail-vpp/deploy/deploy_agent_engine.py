"""Deploy the swarm to Agent Runtime (formerly Vertex AI Agent Engine) in asia-northeast1 with the Python SDK.

Usage: GOOGLE_CLOUD_PROJECT=<project> STAGING_BUCKET=gs://<bucket> [AGENT_SA=<sa-email>] python deploy/deploy_agent_engine.py
Only the retail_desk/ package is shipped (schema.json and corpus/ live inside it); data is read from BigQuery.
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DATA_BACKEND", "bigquery")


def main() -> None:
    import vertexai
    from vertexai import agent_engines

    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    vertexai.init(project=project, location=os.getenv("AGENT_ENGINE_LOCATION", "asia-northeast1"),
                  staging_bucket=os.environ["STAGING_BUCKET"])
    os.environ.setdefault("BQ_PROJECT", project)
    from retail_desk.agent import root_agent

    reqs = [l.strip() for l in open(os.path.join(ROOT, "requirements.txt")) if l.strip() and not l.startswith("#")
            and not l.startswith(("pytest", "fastapi", "uvicorn", "httpx"))]
    env = {"DATA_BACKEND": "bigquery", "BQ_DATASET": os.getenv("BQ_DATASET", "tepco_retail_desk_demo"), "BQ_PROJECT": project,
           "BQ_LOCATION": "asia-northeast1", "GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "MODEL_LOCATION": "global",
           "MODEL_REASONING": os.getenv("MODEL_REASONING", "gemini-3.1-pro-preview"),
           "MODEL_BALANCED": os.getenv("MODEL_BALANCED", "gemini-3.6-flash"), "MODEL_FAST": os.getenv("MODEL_FAST", "gemini-3.5-flash-lite")}
    remote = agent_engines.create(
        agent_engines.AdkApp(agent=root_agent, app_name="retail_desk"),
        requirements=reqs, extra_packages=[os.path.join(ROOT, "retail_desk")], env_vars=env,
        display_name="retail-energy-desk", description="Retail Energy Desk agent swarm (concept demo, synthetic data)",
        service_account=os.getenv("AGENT_SA") or None,
    )
    print("AGENT_ENGINE_ID =", remote.resource_name)


if __name__ == "__main__":
    main()
