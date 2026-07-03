"""PWA: installable manifest + a minimal, safe offline service worker (item #69).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Frontend-only PWA groundwork: a web-app manifest (installable, theme colour, icons)
and a service worker that caches ONLY the static app shell under /static/ and NEVER
API/data responses (the stale-data guard). Strategy is network-first so an online user
always gets fresh code. The SW is served under /static/ so full offline navigation of
"/" needs a 1-line backend route (noted in the PR); the manifest works fully. Static
file guards (browser-unverified per fork-3).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"
_HTML = (_STATIC / "index.html").read_text(encoding="utf-8")


def test_manifest_is_valid_and_installable():
    m = json.loads((_STATIC / "manifest.json").read_text(encoding="utf-8"))
    assert m["name"] and m["short_name"]
    assert m["start_url"] == "/" and m["scope"] == "/"
    assert m["display"] == "standalone"
    assert m.get("theme_color") and m.get("background_color")
    icons = {i["src"] for i in m["icons"]}
    assert "/static/favicon.svg" in icons and "/static/icon.png" in icons


def test_icon_asset_is_present():
    assert (_STATIC / "icon.png").exists(), "the manifest icon must be served"


def test_head_links_manifest_and_theme():
    assert '<link rel="manifest" href="/static/manifest.json">' in _HTML
    assert 'name="theme-color"' in _HTML
    assert 'rel="apple-touch-icon"' in _HTML


def test_service_worker_is_registered_best_effort():
    assert 'navigator.serviceWorker.register("/static/sw.js")' in _HTML
    assert '"serviceWorker" in navigator' in _HTML
    assert ".catch(function () {})" in _HTML  # never breaks boot


def test_service_worker_caches_only_the_static_shell_never_api():
    sw = (_STATIC / "sw.js").read_text(encoding="utf-8")
    # only same-origin GET requests under /static/ are handled
    assert 'req.method !== "GET"' in sw
    assert 'url.origin !== self.location.origin' in sw
    assert 'url.pathname.startsWith("/static/")' in sw
    # the precache SHELL list must carry ONLY /static/ paths (never an /api or /metrics url)
    shell = re.search(r"const SHELL = \[(.*?)\];", sw, re.S).group(1)
    entries = re.findall(r'"([^"]+)"', shell)
    assert entries and all(e.startswith("/static/") for e in entries), entries
    # network-first (fresh online, cache offline) — no stale-code footgun
    assert "fetch(req)" in sw and "caches.match(req)" in sw
    # only successful basic 200s are cached (never opaque/error)
    assert 'res.status === 200 && res.type === "basic"' in sw
    # old cache versions are purged on activate
    assert 'caches.delete(k)' in sw and 'oo-shell-v1' in sw
