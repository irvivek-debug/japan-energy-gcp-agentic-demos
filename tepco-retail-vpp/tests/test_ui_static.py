"""Static UI contract: disclaimer, allowed CDN only, module wiring, copy rules, and API paths that exist."""
import os
import re

from fastapi.testclient import TestClient

from conftest import ROOT

UI = os.path.join(ROOT, "ui")
BANNED = r"\b(delve|tapestry|testament|underscore|elevate|crucial|pivotal|vital|foster|vibrant|intricate|landscape|showcase|boasts)\b"


def read(name):
    return open(os.path.join(UI, name), encoding="utf-8").read()


def test_index_contract():
    html = read("index.html")
    assert "Concept demo. Synthetic data. Not affiliated with or endorsed by TEPCO." in html
    assert "<title>Retail Energy Desk</title>" in html
    assert 'href="tokens.css"' in html and 'type="module"' in html
    srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
    external = [s for s in srcs if s.startswith("http")]
    assert all(s.startswith("https://cdn.jsdelivr.net/npm/echarts@5/") for s in external), external


def test_app_imports_hold_to_confirm_and_uses_real_endpoints():
    js = read("app.js")
    assert "hold-to-confirm.js" in js and "holdToConfirm(" in js
    from server.app import app

    routes = {r.path for r in app.routes if hasattr(r, "path")}
    used = set(re.findall(r"/api/[a-z/_-]+", js))
    for u in used:
        base = u.rstrip("/")
        ok = any(base == r or r.startswith(base + "/") or (("{" in r) and base.startswith(r.split("{")[0].rstrip("/"))) for r in routes)
        assert ok, f"app.js calls {u} which the server does not expose"


def test_copy_rules():
    for f in ("index.html", "app.js", "styles.css"):
        text = read(f)
        assert "—" not in text and "–" not in text, f"dash in {f}"
        assert not re.search(BANNED, text, re.I), f"banned word in {f}"


def test_static_files_served():
    from server.app import app

    c = TestClient(app)
    for p in ("/", "/tokens.css", "/hold-to-confirm.js", "/app.js", "/styles.css"):
        assert c.get(p).status_code == 200, p
