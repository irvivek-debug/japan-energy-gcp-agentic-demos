#!/usr/bin/env python3
"""Deploy one demo folder to Google Cloud with Application Default Credentials only (no gcloud CLI needed).

Every step is idempotent and ends with a verification check, not just an exit code.

  export GOOGLE_CLOUD_PROJECT=<project-id>          # never hardcoded
  python tools/gcp_deploy.py bq-load      --demo tepco-retail-vpp --dataset tepco_retail_desk_demo
  python tools/gcp_deploy.py agent-engine --demo tepco-retail-vpp --package retail_desk \
         --display-name "TEPCO Retail Energy Desk swarm" --dataset tepco_retail_desk_demo
  python tools/gcp_deploy.py cloud-run    --demo tepco-retail-vpp --service tepco-retail-desk \
         --env DATA_BACKEND=bigquery --env BQ_DATASET=tepco_retail_desk_demo

Region defaults to asia-northeast1 (REGION env). Gemini is always called at the `global` location.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tarfile
import time
import uuid

import google.auth
import google.auth.transport.requests as gtr

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REGION = os.getenv("REGION", "asia-northeast1")
AR_REPO = os.getenv("AR_REPO", "energy-demos")
EXCLUDE_DIRS = {".venv", "__pycache__", ".pytest_cache", "node_modules", ".git", "results", ".adk"}
EXCLUDE_SUFFIX = (".pyc", ".pyo", ".log", ".DS_Store")


def project() -> str:
    p = os.getenv("GOOGLE_CLOUD_PROJECT")
    if not p:
        sys.exit("GOOGLE_CLOUD_PROJECT is not set")
    return p


def session() -> gtr.AuthorizedSession:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    return gtr.AuthorizedSession(creds)


def check(r, what: str):
    if r.status_code >= 300:
        sys.exit(f"{what} failed: HTTP {r.status_code} {r.text[:800]}")
    return r.json() if r.text else {}


def wait_op(s, url: str, what: str, timeout: int = 1800, key: str = "done") -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        op = check(s.get(url), what)
        if op.get(key):
            if op.get("error"):
                sys.exit(f"{what} failed: {json.dumps(op['error'])[:800]}")
            return op
        time.sleep(5)
    sys.exit(f"{what}: timed out after {timeout}s")


def project_number(s) -> str:
    return check(s.get(f"https://cloudresourcemanager.googleapis.com/v1/projects/{project()}"), "describe project")["projectNumber"]


# --------------------------------------------------------------------------------------------- BigQuery
def bq_load(args):
    from google.cloud import bigquery

    demo = os.path.join(ROOT, args.demo)
    schema = json.load(open(os.path.join(demo, "data", "schema.json")))["tables"]
    client = bigquery.Client(project=project(), location=REGION)
    ds = bigquery.Dataset(f"{project()}.{args.dataset}")
    ds.location = REGION
    ds.description = f"Synthetic concept-demo data for {args.demo}. Not real customer data."
    ds.labels = {"demo": args.demo.replace("_", "-")[:63], "data": "synthetic"}
    client.create_dataset(ds, exists_ok=True)
    empty = []
    for name, spec in schema.items():
        path = os.path.join(demo, "data", "out", f"{name}.csv")
        fields = [bigquery.SchemaField(c["name"], c["type"], description=c.get("description", "")[:1024]) for c in spec["columns"]]
        cfg = bigquery.LoadJobConfig(schema=fields, source_format=bigquery.SourceFormat.CSV, skip_leading_rows=1,
                                     write_disposition="WRITE_TRUNCATE", allow_quoted_newlines=True)
        table_id = f"{project()}.{args.dataset}.{name}"
        with open(path, "rb") as f:
            client.load_table_from_file(f, table_id, job_config=cfg).result()
        t = client.get_table(table_id)
        t.description = spec.get("description", "")[:16000]
        client.update_table(t, ["description"])
        import pandas as pd

        expected = len(pd.read_csv(path, dtype=str, keep_default_na=False))
        n = list(client.query(f"SELECT COUNT(*) AS n FROM `{table_id}`").result())[0].n
        status = "OK" if n == expected else "MISMATCH"
        if n == 0:
            empty.append(name)
        print(f"  {status:8s} {name:32s} rows={n:>9,} expected={expected:>9,}")
        if n != expected:
            sys.exit(f"row count mismatch for {name}")
    unexpected = [t for t in empty if t not in args.allow_empty]
    if unexpected:
        sys.exit(f"empty tables: {unexpected} (pass --allow-empty <table> only for tables that are empty by design)")
    print(f"BigQuery dataset {args.dataset} loaded and verified ({len(schema)} tables).")


# --------------------------------------------------------------------------------------------- IAM
def add_project_bindings(s, bindings: list[tuple[str, str]]):
    url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{project()}"
    pol = check(s.post(f"{url}:getIamPolicy", json={"options": {"requestedPolicyVersion": 3}}), "getIamPolicy")
    changed = False
    for role, member in bindings:
        b = next((b for b in pol.setdefault("bindings", []) if b["role"] == role and "condition" not in b), None)
        if b is None:
            pol["bindings"].append({"role": role, "members": [member]})
            changed = True
        elif member not in b["members"]:
            b["members"].append(member)
            changed = True
    if changed:
        pol["version"] = 3
        check(s.post(f"{url}:setIamPolicy", json={"policy": pol}), "setIamPolicy")
    print(f"  project IAM: {'updated' if changed else 'already present'}: {[r for r, _ in bindings]} -> {bindings[0][1] if bindings else ''}")


def ensure_sa(s, account_id: str, display: str) -> str:
    email = f"{account_id}@{project()}.iam.gserviceaccount.com"
    r = s.get(f"https://iam.googleapis.com/v1/projects/{project()}/serviceAccounts/{email}")
    if r.status_code == 404:
        check(s.post(f"https://iam.googleapis.com/v1/projects/{project()}/serviceAccounts",
                     json={"accountId": account_id, "serviceAccount": {"displayName": display}}), "create SA")
        time.sleep(10)
        print(f"  created service account {email}")
    else:
        check(r, "get SA")
    return email


def grant_dataset_reader(member_email: str, dataset: str, member_type: str = "serviceAccount"):
    from google.cloud import bigquery

    client = bigquery.Client(project=project(), location=REGION)
    ds = client.get_dataset(f"{project()}.{dataset}")
    entries = list(ds.access_entries)
    if not any(e.entity_id == member_email and e.role == "READER" for e in entries):
        entries.append(bigquery.AccessEntry("READER", "userByEmail", member_email))
        ds.access_entries = entries
        client.update_dataset(ds, ["access_entries"])
        print(f"  dataset {dataset}: READER granted to {member_email}")


# --------------------------------------------------------------------------------------------- Agent Engine
def agent_engine(args):
    import vertexai
    from vertexai import agent_engines

    s = session()
    pnum = project_number(s)
    bucket = f"{project()}-energy-demos-staging"
    r = s.get(f"https://storage.googleapis.com/storage/v1/b/{bucket}")
    if r.status_code == 404:
        check(s.post("https://storage.googleapis.com/storage/v1/b", params={"project": project()},
                     json={"name": bucket, "location": REGION, "iamConfiguration": {"uniformBucketLevelAccess": {"enabled": True}}}),
              "create staging bucket")
    # Agent Engine runs as the Vertex AI Reasoning Engine service agent; it needs model + BigQuery job/data roles.
    re_agent = f"service-{pnum}@gcp-sa-aiplatform-re.iam.gserviceaccount.com"
    add_project_bindings(s, [("roles/aiplatform.user", f"serviceAccount:{re_agent}"),
                             ("roles/bigquery.jobUser", f"serviceAccount:{re_agent}")])
    if args.dataset:
        grant_dataset_reader(re_agent, args.dataset)

    demo = os.path.join(ROOT, args.demo)
    os.chdir(demo)  # extra_packages paths are relative to the demo root
    sys.path.insert(0, demo)
    os.environ.setdefault("DATA_BACKEND", "local")  # build locally from CSV; runtime uses env_vars below
    mod = __import__(f"{args.package}.agent", fromlist=["root_agent"])
    reqs = [l.strip() for l in open("requirements.txt") if l.strip() and not l.startswith("#")]
    extra = [args.package] + [p for p in args.extra if os.path.exists(p)]
    env = {"GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "GOOGLE_CLOUD_LOCATION": "global", "DATA_BACKEND": "bigquery",
           "BQ_PROJECT": project(), "BQ_LOCATION": REGION}
    if args.dataset:
        env["BQ_DATASET"] = args.dataset
    for kv in args.env:
        k, v = kv.split("=", 1)
        env[k] = v
    vertexai.init(project=project(), location=REGION, staging_bucket=f"gs://{bucket}")
    app = agent_engines.AdkApp(agent=mod.root_agent)
    existing = [e for e in agent_engines.list(filter=f'display_name="{args.display_name}"')]
    kw = dict(requirements=reqs, extra_packages=extra, env_vars=env, display_name=args.display_name,
              description=args.description or args.display_name, gcs_dir_name=args.package)
    if existing:
        print(f"  updating {existing[0].resource_name}")
        remote = agent_engines.update(existing[0].resource_name, agent_engine=app, **kw)
    else:
        remote = agent_engines.create(app, **kw)
    print(f"AGENT_ENGINE_ID={remote.resource_name}")
    json.dump({"resource_name": remote.resource_name, "region": REGION, "display_name": args.display_name},
              open(os.path.join(demo, "deploy", "agent_engine.local.json"), "w"), indent=2)


# --------------------------------------------------------------------------------------------- Cloud Run
def _tar_source(demo: str) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for dirpath, dirnames, filenames in os.walk(demo):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            for fn in filenames:
                if fn.endswith(EXCLUDE_SUFFIX) or fn.startswith(".env") and fn != ".env.example" or fn.endswith(".local.json"):
                    continue
                full = os.path.join(dirpath, fn)
                tar.add(full, arcname=os.path.relpath(full, demo))
    return buf.getvalue()


def cloud_run(args):
    s = session()
    p, pnum = project(), project_number(s)
    demo = os.path.join(ROOT, args.demo)
    # 1. Artifact Registry repo
    ar = f"https://artifactregistry.googleapis.com/v1/projects/{p}/locations/{REGION}/repositories"
    if s.get(f"{ar}/{AR_REPO}").status_code == 404:
        op = check(s.post(ar, params={"repositoryId": AR_REPO}, json={"format": "DOCKER", "description": "energy concept demos"}), "create AR repo")
        wait_op(s, f"https://artifactregistry.googleapis.com/v1/{op['name']}", "create AR repo")
    if args.image:
        image = args.image
    else:
        # 2. upload source
        bucket = f"{p}-energy-demos-staging"
        obj = f"source/{args.service}-{int(time.time())}.tgz"
        data = _tar_source(demo)
        check(s.post(f"https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o", params={"uploadType": "media", "name": obj},
                     data=data, headers={"Content-Type": "application/gzip"}), "upload source")
        print(f"  uploaded {len(data)/1e6:.1f} MB source")
        # 3. Cloud Build
        tag = time.strftime("%Y%m%d-%H%M%S")
        image = f"{REGION}-docker.pkg.dev/{p}/{AR_REPO}/{args.service}:{tag}"
        build_sa = f"projects/{p}/serviceAccounts/{pnum}-compute@developer.gserviceaccount.com"
        body = {"source": {"storageSource": {"bucket": bucket, "object": obj}},
                "steps": [{"name": "gcr.io/cloud-builders/docker", "args": ["build", "-t", image, "."]}],
                "images": [image], "serviceAccount": build_sa, "options": {"logging": "CLOUD_LOGGING_ONLY"}, "timeout": "1200s"}
        op = check(s.post(f"https://cloudbuild.googleapis.com/v1/projects/{p}/locations/{REGION}/builds", json=body), "submit build")
        build_id = op["metadata"]["build"]["id"]
        print(f"  build {build_id} submitted")
        while True:
            b = check(s.get(f"https://cloudbuild.googleapis.com/v1/projects/{p}/locations/{REGION}/builds/{build_id}"), "get build")
            if b["status"] in ("SUCCESS", "FAILURE", "INTERNAL_ERROR", "TIMEOUT", "CANCELLED", "EXPIRED"):
                break
            time.sleep(10)
        if b["status"] != "SUCCESS":
            sys.exit(f"build {b['status']}: {b.get('logUrl')}")
        print(f"  image {image}")
    # 4. runtime service account
    sa = ensure_sa(s, "energy-demo-web", "Energy demos Cloud Run runtime")
    add_project_bindings(s, [("roles/aiplatform.user", f"serviceAccount:{sa}"), ("roles/bigquery.jobUser", f"serviceAccount:{sa}"),
                             ("roles/logging.logWriter", f"serviceAccount:{sa}")])
    for ds in args.dataset:
        grant_dataset_reader(sa, ds)
    # 5. Cloud Run service
    env = {"GOOGLE_GENAI_USE_VERTEXAI": "TRUE", "GOOGLE_CLOUD_LOCATION": "global", "GOOGLE_CLOUD_PROJECT": p,
           "BQ_PROJECT": p, "BQ_LOCATION": REGION}
    for kv in args.env:
        k, v = kv.split("=", 1)
        env[k] = v
    svc_url = f"https://run.googleapis.com/v2/projects/{p}/locations/{REGION}/services"
    svc = {"template": {"serviceAccount": sa, "timeout": "600s", "maxInstanceRequestConcurrency": 40,
                        "scaling": {"minInstanceCount": 0, "maxInstanceCount": 1},
                        "containers": [{"image": image, "ports": [{"containerPort": 8080}],
                                        "env": [{"name": k, "value": v} for k, v in env.items()],
                                        "resources": {"limits": {"cpu": "2", "memory": "4Gi"}, "startupCpuBoost": True}}]},
           "labels": {"demo": args.service}}
    if args.iap_member:
        svc["iapEnabled"] = True
    r = s.get(f"{svc_url}/{args.service}")
    if r.status_code == 404:
        op = check(s.post(svc_url, params={"serviceId": args.service}, json=svc), "create service")
    else:
        op = check(s.patch(f"{svc_url}/{args.service}", json=svc), "update service")
    wait_op(s, f"https://run.googleapis.com/v2/{op['name']}", "deploy service")
    out = check(s.get(f"{svc_url}/{args.service}"), "get service")
    if args.iap_member:
        enable_iap_access(s, pnum, args.service, args.iap_member)
    print(f"SERVICE_URL={out.get('uri')}")
    json.dump({"service": args.service, "url": out.get("uri"), "image": image, "region": REGION},
              open(os.path.join(demo, "deploy", "cloud_run.local.json"), "w"), indent=2)


def enable_iap_access(s, pnum: str, service: str, members: list[str]):
    """Browser access through IAP (Google sign-in) instead of a public service.

    IAP's service agent gets run.invoker on the service; each named member gets iap.httpsResourceAccessor.
    Members are explicit (user:... or group:...); a domain-wide grant is a separate, human-approved decision.
    """
    iap_agent = f"serviceAccount:service-{pnum}@gcp-sa-iap.iam.gserviceaccount.com"
    run_res = f"https://run.googleapis.com/v2/projects/{project()}/locations/{REGION}/services/{service}"
    iap_res = f"https://iap.googleapis.com/v1/projects/{pnum}/iap_web/cloud_run-{REGION}/services/{service}"
    for url, role, mems, get in ((run_res, "roles/run.invoker", [iap_agent], "GET"),
                                 (iap_res, "roles/iap.httpsResourceAccessor", members, "POST")):
        pol = check(s.get(f"{url}:getIamPolicy") if get == "GET" else s.post(f"{url}:getIamPolicy", json={}), f"getIamPolicy {role}")
        b = next((b for b in pol.setdefault("bindings", []) if b["role"] == role), None)
        if b is None:
            pol["bindings"].append({"role": role, "members": list(mems)})
        else:
            b["members"] = sorted(set(b["members"]) | set(mems))
        check(s.post(f"{url}:setIamPolicy", json={"policy": pol}), f"setIamPolicy {role}")
        print(f"  {role} -> {mems}")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bq-load"); b.add_argument("--demo", required=True); b.add_argument("--dataset", required=True)
    b.add_argument("--allow-empty", action="append", default=[], help="table that is empty by design")
    a = sub.add_parser("agent-engine"); a.add_argument("--demo", required=True); a.add_argument("--package", required=True)
    a.add_argument("--display-name", required=True); a.add_argument("--description", default="")
    a.add_argument("--dataset", default=""); a.add_argument("--extra", action="append", default=[])
    a.add_argument("--env", action="append", default=[])
    c = sub.add_parser("cloud-run"); c.add_argument("--demo", required=True); c.add_argument("--service", required=True)
    c.add_argument("--env", action="append", default=[]); c.add_argument("--dataset", action="append", default=[])
    c.add_argument("--image", default="", help="reuse an existing image (skip Cloud Build)")
    c.add_argument("--iap-member", action="append", default=[], help="user:alice@example.com; enables IAP")
    args = ap.parse_args()
    {"bq-load": bq_load, "agent-engine": agent_engine, "cloud-run": cloud_run}[args.cmd](args)


if __name__ == "__main__":
    main()
