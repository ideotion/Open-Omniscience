"""The IPCC click surface: the endpoint's own refusals, the listing, and the UI's consent gate.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

THE PAIR THAT MATTERS is the button and the endpoint (invariant #14f): both halves are asserted,
separately, so a caller that never opened the UI meets the same refusal.
"""

from __future__ import annotations

import json
import pathlib
import re
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.api import ipcc as ipcc_api
from src.database.models import Article, Base
from src.ingest import activate_kill_switch, clear_kill_switch, ipcc_spm
from src.ingest.fetch_verdict import NETWORK_REFUSED
from tests.js_source_helper import function_source, read_static

_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    app = FastAPI()
    app.include_router(ipcc_api.router)
    return TestClient(app)


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_the_endpoint_refuses_under_the_kill_switch_and_names_airplane_mode(client):
    activate_kill_switch()
    try:
        r = client.post("/api/ipcc/spm/wg1/fetch", json={"consent": True})
    finally:
        clear_kill_switch()
    assert r.status_code == 409, r.text
    assert r.json()["detail"] == NETWORK_REFUSED
    assert "airplane mode" in r.json()["detail"].lower()


def test_the_endpoint_demands_consent_on_its_own(client, monkeypatch):
    started = []
    monkeypatch.setattr(ipcc_api._SPM_JOB, "start", lambda **kw: started.append(kw) or {})
    for body in ({}, {"consent": False}):
        r = client.post("/api/ipcc/spm/wg1/fetch", json=body)
        assert r.status_code == 400, r.text
        assert "consent" in r.json()["detail"]
    assert started == []


def test_unknown_key_is_404_and_never_starts_a_job(client, monkeypatch):
    monkeypatch.setattr(ipcc_api._SPM_JOB, "start", lambda **kw: pytest.fail("started"))
    assert client.post("/api/ipcc/spm/wg9/fetch", json={"consent": True}).status_code == 404


def test_a_second_click_while_running_reports_the_live_job_not_an_error(client, monkeypatch):
    def busy(**kw):
        raise RuntimeError("already running")

    monkeypatch.setattr(ipcc_api._SPM_JOB, "start", busy)
    r = client.post("/api/ipcc/spm/wg1/fetch", json={"consent": True})
    assert r.status_code == 200 and r.json()["started"] is False


def test_the_job_is_a_single_run_writer_that_is_not_cancellable():
    job = ipcc_api._SPM_JOB
    assert job.is_writer is True
    assert job.cancellable is False


def test_the_listing_is_local_and_says_what_is_stored(db):
    out = ipcc_api.spm_list(db)
    assert [i["key"] for i in out["items"]] == ["wg1", "wg2", "wg3", "syr"]
    assert not any(i["stored"] for i in out["items"])
    assert out["disclosure"] == ipcc_spm.DISCLOSURE
    assert "nothing is requested" in out["method"]
    entry = ipcc_spm.spm_entry("wg2")
    src = ipcc_spm.ensure_ipcc_source(db)
    db.add(
        Article(
            url=entry.url,
            source_id=src.id,
            canonical_url=entry.url,
            title=entry.title,
            content="x",
            hash="h" * 8,
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    items = {i["key"]: i for i in ipcc_api.spm_list(db)["items"]}
    assert items["wg2"]["stored"] is True and items["wg2"]["article_id"]
    assert items["wg1"]["stored"] is False


def test_the_fetch_button_passes_the_one_network_consent():
    src = function_source(read_static("app-ipcc.js"), "ipccFetch")
    at = re.search(r"!\s*await\s+ensureOnline\(", src)
    assert at, "ensureOnline's answer is not negated, so it is awaited and discarded:\n" + src
    i, depth = at.end() - 1, 0
    while i < len(src):
        depth += {"(": 1, ")": -1}.get(src[i], 0)
        if depth == 0:
            break
        i += 1
    tail = src[i + 1 :].lstrip()
    assert tail.startswith(") return") or tail.startswith(")) return"), tail[:80]
    assert "consent: true" in src


def test_the_list_read_is_not_gated():
    assert "ensureOnline" not in function_source(read_static("app-ipcc.js"), "loadIpccSpm")


def test_the_panel_shows_the_disclosure_visibly_and_loads_with_its_section():
    html = (_ROOT / "src" / "static" / "index.html").read_text(encoding="utf-8")
    i = html.index('id="ipcc-spm"')
    panel = html[i : html.index("</section>", i)]
    cav = re.search(r'<p class="card-caveat"[^>]*>(.*?)</p>', panel, re.S)
    assert cav and cav.group(1) == ipcc_spm.DISCLOSURE
    assert "hidden" not in panel
    shell = read_static("app-shell.js")
    m = re.search(r"ipcc:\s*\(\)\s*=>\s*\{(.*?)\},", shell, re.S)
    assert m and "loadIpccSpm" in m.group(1)
    assert "/static/app-ipcc.js" in html
    assert "/static/app-ipcc.js" in read_static("sw.js")


def test_every_visible_string_is_keyed_in_all_twelve_locales():
    src = read_static("app-ipcc.js")
    strings = set(re.findall(r'\b_?tx?\("([^"]+)"\)', src))
    strings |= {"IPCC reports", ipcc_spm.DISCLOSURE, "— Summaries for Policymakers"}
    locales = sorted((_ROOT / "src" / "static" / "locales").glob("*.json"))
    assert len(locales) == 12
    missing = [
        f"{p.name}: {s!r}"
        for p in locales
        for s in strings
        if s not in json.loads(p.read_text(encoding="utf-8"))
    ]
    assert not missing, "\n".join(missing)
