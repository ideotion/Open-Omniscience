"""``/docs`` (Swagger) and ``/redoc`` are OFF unless ``OO_API_DOCS=1`` (A-021, R285 option A, ruled R411).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE QUESTION THIS ANSWERS. Both pages are shells: the BROWSER fetches their script, style and favicon from ``cdn.jsdelivr.net`` and
``fastapi.tiangolo.com`` (and ReDoc's font from ``fonts.googleapis.com``). That broke "no external resource" in a tool whose pages are
otherwise served from the install alone, and the pages were exempt from the strict CSP so the browser allowed it. Now neither route is
served by default (404), no page the app serves names a third-party host, and the one switch that brings them back also brings the CSP
exemption back (and only then). ``/openapi.json`` stays: plain JSON, nothing third-party, and under the strict CSP.

The switch is read once, at import, so the "on" half runs in a child interpreter: the ``app`` singleton is process-wide and a reload of it
in a test would be seen by every other test.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

_ROOT = Path(__file__).resolve().parent.parent
_THIRD_PARTY = (
    "cdn.jsdelivr.net",
    "fastapi.tiangolo.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "unpkg.com",
    "cdnjs.cloudflare.com",
)
# A link or a window.open to the interactive pages. ``(?<![\w/.-])`` keeps ``/api/docs`` (the Help reader's own route) out of it.
_DOCS_LINK = re.compile(r"""(?<![\w/.-])/(?:docs|redoc)(?![\w/-])""")


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("OO_API_DOCS", raising=False)
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from src.api.main import app

    with TestClient(app, base_url="http://127.0.0.1:8000") as c:
        yield c


def test_neither_page_is_served_by_default(client):
    from src.api import main

    assert main._API_DOCS_ON is False, (
        "this process was started with OO_API_DOCS=1: the default cannot be measured here"
    )
    for path in ("/docs", "/redoc", "/docs/oauth2-redirect"):
        assert client.get(path).status_code == 404, path


def test_the_schema_stays_and_takes_the_strict_csp(client):
    r = client.get("/openapi.json")
    assert r.status_code == 200 and r.json()["info"]["title"] == "Open Omniscience API"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"], (
        "with the pages off nothing is exempt from the strict CSP"
    )


def test_no_served_page_names_a_third_party_host_or_links_the_pages(client):
    """The Help panel and the palette linked ``/docs``; the fallback page did too. Scan what is SERVED and the static tree."""
    served = client.get("/")
    assert served.status_code == 200 and "<html" in served.text.lower(), (
        "positive control: the shell was served"
    )
    texts = {"GET /": served.text}
    for f in sorted((_ROOT / "src" / "static").rglob("*")):
        # Locale files are translations of chrome strings, vendored libraries are checksum-pinned elsewhere: both are text we do not author here.
        if f.suffix in {".html", ".js", ".css", ".svg", ".webmanifest"} and "vendor" not in f.parts:
            texts[str(f.relative_to(_ROOT))] = f.read_text(encoding="utf-8", errors="replace")
    assert len(texts) > 10, "positive control: the static tree was found"
    offenders = [f"{name}: {h}" for name, t in texts.items() for h in _THIRD_PARTY if h in t]
    assert not offenders, offenders
    links = [f"{name}: {m.group(0)}" for name, t in texts.items() for m in _DOCS_LINK.finditer(t)]
    assert not links, f"a link to a page that is not served by default: {links}"


def test_the_fallback_page_does_not_link_the_pages():
    src = (_ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    fallback = src[src.index("Welcome to Open Omniscience") :][:300]
    assert "API is running" in fallback, "positive control: found the fallback page"
    assert not _DOCS_LINK.search(fallback), fallback


def test_the_help_documents_do_not_send_a_reader_to_a_page_that_is_off():
    """The Help reader serves ``docs/*.md`` (and ``docs/i18n/<lang>/*.md``): a paragraph that names ``/docs`` or ``/redoc`` must also say
    ``OO_API_DOCS``, or it points a reader at a 404. The static-tree scan above cannot see these files."""
    from src.api import main

    checked = 0
    stale: list[str] = []
    for meta in main._DOCS.values():
        if meta["file"] == "CHANGES.md":
            continue  # history: it records what was true when each entry shipped (its 1.x top-bar entry names the old /docs link)
        for f in [
            _ROOT / "docs" / meta["file"],
            *sorted((_ROOT / "docs" / "i18n").glob(f"*/{meta['file']}")),
        ]:
            if not f.exists():
                continue
            checked += 1
            for para in re.split(r"\n\s*\n", f.read_text(encoding="utf-8")):
                if (
                    _DOCS_LINK.search(para) or "8000/docs" in para or "8000/redoc" in para
                ) and "OO_API_DOCS" not in para:
                    stale.append(f"{f.relative_to(_ROOT)}: {para.strip()[:90]!r}")
    assert checked >= 8, "positive control: the Help documents were found"
    assert not stale, stale


_CHILD = """
import json, sys
sys.path.insert(0, sys.argv[1])  # ``-I`` ignores PYTHONPATH, so the tree under test is put first by hand
from fastapi.testclient import TestClient
import src.api.main as main
from src.api.main import app
main._serving_gate_open = True  # as tests/conftest.py does: no lifespan runs here, and R644's gate would answer 503 (R646)
c = TestClient(app, base_url="http://127.0.0.1:8000")  # no ``with``: the lifespan is not under test
out = {}
for p in ("/docs", "/redoc", "/openapi.json"):
    r = c.get(p)
    out[p] = [r.status_code, "Content-Security-Policy" in r.headers, r.text.count("cdn.jsdelivr.net")]
print("RESULT " + json.dumps(out))
"""


def _child(value: str | None, tmp_path) -> dict[str, list]:
    env = {k: v for k, v in os.environ.items() if k != "OO_API_DOCS"}
    env.update(OO_DATA_DIR=str(tmp_path), OO_NO_SCHEDULER="1")
    if value is not None:
        env["OO_API_DOCS"] = value
    done = subprocess.run(
        [sys.executable, "-I", "-c", _CHILD, str(_ROOT)],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=300,
    )
    line = next((ln for ln in done.stdout.splitlines() if ln.startswith("RESULT ")), "")
    assert line, f"the child printed no result:\n{done.stdout[-800:]}\n{done.stderr[-1500:]}"
    return json.loads(line[len("RESULT ") :])


def test_the_switch_brings_both_pages_back_and_exempts_only_them(tmp_path):
    on = _child("1", tmp_path)
    assert on["/docs"][0] == 200 and on["/redoc"][0] == 200, on
    assert on["/docs"][2] >= 1, (
        "positive control: the page that is back is the CDN one this change is about"
    )
    assert on["/docs"][1] is False and on["/redoc"][1] is False, (
        "back on, the pages carry no strict CSP (they could not load otherwise)"
    )
    assert on["/openapi.json"][0] == 200 and on["/openapi.json"][1] is True, (
        "only the two pages are exempt: the schema keeps the strict CSP"
    )


@pytest.mark.parametrize("value", [None, "0", "", "true", "yes", " 1", "1 ", "11"])
def test_only_the_exact_value_one_turns_it_on(tmp_path, value):
    """``true``/``yes`` are not ``1``: the same strict reading ``OO_AIRPLANE_SOCKET_GUARD`` and the other switches have."""
    off = _child(value, tmp_path)
    assert off["/docs"][0] == 404 and off["/redoc"][0] == 404, off
