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

_STATIC = Path(__file__).resolve().parents[1] / "src" / "static"


def test_app_js_and_css_are_served():
    c = TestClient(app)
    for path, on_disk, ctype in (
        ("/static/app.js", "app.js", "javascript"),
        ("/static/app.css", "app.css", "css"),
    ):
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
    assert '<script src="/static/app.js"></script>' in html
    # classic external script preserves globals + inline handlers; load order kept.
    assert html.index("/static/i18n.js") < html.index("/static/app.js")
    assert "<style>" not in html, "no inline CSS may remain in the served document"


def test_app_js_is_substantial_and_app_css_present():
    """Sanity floor: the script/style genuinely moved out (not an empty stub)."""
    assert (_STATIC / "app.js").stat().st_size > 100_000
    assert (_STATIC / "app.css").stat().st_size > 10_000
