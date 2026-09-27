"""Static UI contract for v1 (kept at /v1/) and v2 (the three families at /)."""
import glob
import os
import re

from fastapi.testclient import TestClient

from conftest import ROOT

UI = os.path.join(ROOT, "ui")
BANNED = r"\b(delve|tapestry|testament|underscore|elevate|crucial|pivotal|vital|foster|vibrant|intricate|landscape|showcase|boasts)\b"
V2_PAGES = ["index.html", "case/index.html", "case/gap.html", "case/prize.html", "case/solution.html", "case/proof.html",
            "workspace/value.html", "workspace/index.html", "workspace/swarm.html", "workspace/persona.html", "workspace/handover.html"]


def read(name):
    return open(os.path.join(UI, name), encoding="utf-8").read()


def v2_js():
    return [p for p in glob.glob(os.path.join(UI, "**", "*.js"), recursive=True) if "/v1/" not in p]


def test_v1_contract():
    html = read("v1/index.html")
    assert "Concept demo. Synthetic data. Not affiliated with or endorsed by TEPCO." in html
    assert 'href="tokens.css"' in html and 'type="module"' in html
    js = read("v1/app.js")
    assert "hold-to-confirm.js" in js and "holdToConfirm(" in js


def test_v2_pages_load_the_kit_and_shell():
    for page in V2_PAGES:
        html = read(page)
        assert '<link rel="stylesheet" href="/kit/kit.css">' in html and "/css/v2.css" in html, page
        for s in ("/js/app-shell.js", "/kit/shell.js", "/kit/motion.js", "/kit/signoff.js", "/js/desk.js"):
            assert f'src="{s}"' in html, (page, s)
        ext = [s for s in re.findall(r'<script[^>]+src="([^"]+)"', html) if s.startswith("http")]
        assert all(s.startswith("https://cdn.jsdelivr.net/npm/echarts@5/") for s in ext), (page, ext)
    assert "Not affiliated with or endorsed by" in read("kit/shell.js") and 'company: "TEPCO"' in read("js/app-shell.js")


def test_kit_is_the_reference_copy():
    import filecmp

    ref = os.path.join(ROOT, "..", "docs", "reference", "ui-v2")
    if os.path.isdir(ref):
        for f in ("kit.css", "shell.js", "motion.js", "signoff.js"):
            assert filecmp.cmp(os.path.join(ref, f), os.path.join(UI, "kit", f), shallow=False), f


def test_every_api_path_used_exists():
    from server.app import app

    routes = set(app.openapi()["paths"])  # includes routes from included routers
    for p in v2_js() + [os.path.join(UI, "v1", "app.js")]:
        for u in set(re.findall(r"/api/[a-z0-9/_-]+", open(p, encoding="utf-8").read())):
            base = u.rstrip("/")
            ok = any(base == r or r.startswith(base + "/") or ("{" in r and base.startswith(r.split("{")[0].rstrip("/"))) for r in routes)
            assert ok, f"{os.path.relpath(p, UI)} calls {u} which the server does not expose"


def test_approvals_only_through_signoff():
    for p in v2_js():
        src = open(p, encoding="utf-8").read()
        if "/kit/" in p:
            continue
        assert "/confirm" not in src or p.endswith("desk.js"), f"{p} posts a confirm outside Desk.openAction"


def test_copy_rules():
    files = [os.path.join(UI, p) for p in V2_PAGES] + v2_js() + glob.glob(os.path.join(UI, "css", "*.css")) + [os.path.join(UI, "v1", f) for f in ("index.html", "app.js", "styles.css")]
    for f in files:
        text = open(f, encoding="utf-8").read()
        assert "—" not in text and "–" not in text, f"dash in {f}"
        assert not re.search(BANNED, text, re.I), f"banned word in {f}"


def test_no_figures_typed_into_v2_html():
    unit = re.compile(r"\d[\d,.]*\s*(MWh|MW|kWh|JPY|%|GWh)")
    for page in V2_PAGES:
        text = re.sub(r"<style>.*?</style>", "", read(page), flags=re.S)  # CSS lengths are not figures
        assert not unit.search(text), f"a figure is typed into {page}"


def test_pages_served():
    from server.app import app

    c = TestClient(app)
    for p in ["/", "/case/", "/case/gap.html", "/case/prize.html", "/case/solution.html", "/case/proof.html", "/workspace/",
              "/workspace/value.html", "/workspace/swarm.html", "/workspace/persona.html", "/workspace/handover.html",
              "/v1/", "/v1/app.js", "/v1/tokens.css", "/v1/hold-to-confirm.js", "/kit/kit.css", "/js/desk.js", "/css/v2.css"]:
        assert c.get(p).status_code == 200, p
