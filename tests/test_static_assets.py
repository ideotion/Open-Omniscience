"""
Externalised UI assets are served (audit PR H).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

index.html's inline CSS/JS were decomposed into cached /static/app.css and
/static/app.js. node --check proves the script's syntax; this proves the server
actually serves the files (a 404 would silently break the UI), and that index.html
references them with the same /static/ pattern that already works for i18n.js.
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.api.main import app

from tests.js_source_helper import app_modules

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"


def test_app_js_and_css_are_served():
    """EVERY engine module must be served, not just the first one.

    app.js became 17 ordered modules (S-3, 2026-08-20). A single named asset here
    would have kept passing while sixteen modules 404'd -- and a 404 on any one of
    them is a broken app, since they share one global scope.
    """
    c = TestClient(app)
    assets = [(f"/static/{m}", m, "javascript") for m in app_modules()]
    assets.append(("/static/app.css", "app.css", "css"))
    for path, on_disk, ctype in assets:
        r = c.get(path)
        assert r.status_code == 200, f"{path} must be served (404 would break the UI)"
        assert ctype in r.headers.get("content-type", "").lower(), (
            f"{path} must be served with a {ctype} content-type"
        )
        # Served content matches the on-disk asset (a MOVE, not a mutation).
        # Normalise newlines: a Windows checkout (core.autocrlf) stores CRLF, which
        # StaticFiles serves verbatim while read_text() translates CRLF->LF.
        assert r.text.replace("\r\n", "\n") == (_STATIC / on_disk).read_text(encoding="utf-8")


def test_index_html_links_the_externalised_assets():
    """The served root document references the cached assets (same /static/ pattern
    as the already-working i18n.js), in the correct order."""
    c = TestClient(app)
    html = c.get("/").text
    assert '<link rel="stylesheet" href="/static/app.css">' in html
    mods = app_modules()
    for m in mods:
        assert f'<script src="/static/{m}"></script>' in html, f"{m} is not linked"
    # Classic external scripts preserve globals + inline handlers; load order kept.
    # i18n.js before the engine, and the engine in the order app_modules() reports --
    # which is read from this same document, so what is checked here is that the
    # ORDER IS MONOTONIC, i.e. nothing was inserted out of sequence.
    assert html.index("/static/i18n.js") < html.index(f"/static/{mods[0]}")
    positions = [html.index(f'<script src="/static/{m}"></script>') for m in mods]
    assert positions == sorted(positions), "the engine modules are not in load order"
    assert "<style>" not in html, "no inline CSS may remain in the served document"


def test_app_js_is_substantial_and_app_css_present():
    """Sanity floor: the script/style genuinely moved out (not an empty stub).

    Summed across the engine's modules -- a per-module floor would be wrong (a small
    module legitimately carries few bytes) and would need re-tuning every time a
    boundary moves.
    """
    total = sum((_STATIC / m).stat().st_size for m in app_modules())
    assert total > 100_000, f"the engine is only {total} bytes across its modules"
    assert (_STATIC / "app.css").stat().st_size > 10_000
