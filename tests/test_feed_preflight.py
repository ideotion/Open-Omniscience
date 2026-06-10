"""
First-run feed preflight: robots per host + per-provider samples + the log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Maintainer-ruled (2026-06-10): initialization verifies the bundled calendar
directory and extracts robots verdicts for ALL default fetch targets into a
shareable log. No network in tests — a stub fetcher scripts every response.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from src.monitoring import feed_preflight as fpf


@dataclass
class _Resp:
    status_code: int
    text: str = ""


class _Session:
    """Scripted robots responses: deny worldpublicholiday, allow the rest."""

    def get(self, url, **kw):
        if "worldpublicholiday.com" in url:
            return _Resp(200, "User-agent: *\nDisallow: /\n")
        return _Resp(200, "User-agent: *\nAllow: /\n")


@dataclass
class _Fetch:
    content: str


class _Fetcher:
    session = _Session()
    timeout = 5
    user_agent = "OpenOmniscienceBot/test"

    def fetch(self, url, *, require_html=True):
        return _Fetch(content="BEGIN:VCALENDAR\nEND:VCALENDAR" if ".ics" in url else "date,value\n2026-01-01,1\n")


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))


def test_feed_preflight_writes_verdict_log():
    assert fpf.has_run_before() is False
    summary = fpf.run_feed_preflight(_Fetcher(), sample_per_provider=2)
    assert fpf.has_run_before() is True
    # Robots checked once per distinct host; the denial is recorded, not hidden.
    assert summary["hosts"] >= 5
    assert summary["robots_denied"] >= 1
    records = fpf.recent_results()
    robots = [r for r in records if r["kind"] == "robots"]
    assert {r["host"] for r in robots} >= {"calendar.google.com", "worldpublicholiday.com"}
    denied = next(r for r in robots if r["host"] == "worldpublicholiday.com")
    assert denied["robots"] == "disallowed"
    # Samples are bounded per provider AND never taken where robots said no.
    cal = [r for r in records if r["kind"] == "calendar_feed"]
    by_host: dict[str, int] = {}
    for r in cal:
        by_host[r["host"]] = by_host.get(r["host"], 0) + 1
        assert r["host"] != "worldpublicholiday.com"
    assert all(n <= 2 for n in by_host.values())
    # The JSONL is verbatim-parseable (the log IS the deliverable).
    for line in (fpf._log_path()).read_text().splitlines():
        json.loads(line)


def test_network_diagnostics_export_shape():
    from fastapi.testclient import TestClient

    from src.api.main import app

    fpf.run_feed_preflight(_Fetcher(), sample_per_provider=1)
    with TestClient(app) as c:
        r = c.get("/api/diagnostics/network")
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "")
        body = r.json()
        assert body["export_schema"] == "oo-export-1"
        assert body["kind"] == "network-preflight"
        for key in ("sources", "feeds", "calendar_verdicts", "method"):
            assert key in body["data"]
        assert any(rec["kind"] == "robots" for rec in body["data"]["feeds"])


def test_bundled_world_outline_is_real_and_present():
    """The temporal map ships preconfigured (maintainer ask 2026-06-10): the
    public-domain Natural Earth outline is BUNDLED — no download at install."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "src" / "static" / "world_outline.json"
    assert path.exists(), "world_outline.json must ship in the repo (CLAUDE.md)"
    data = json.loads(path.read_text("utf-8"))
    assert len(data["rings"]) > 50  # real coastlines, not a stub
    assert sum(len(r) for r in data["rings"]) > 2000


def test_debug_bundle_shape_and_error_capture():
    """The one-click debug bundle (maintainer: 'I'll click every button and
    send you the log') carries every diagnosis section + captured warnings."""
    import logging

    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.monitoring.errorlog import install

    install()
    logging.getLogger("oo.test").warning("synthetic warning for the bundle")
    with TestClient(app) as c:
        r = c.get("/api/diagnostics/debug-bundle")
        assert r.status_code == 200
        assert "attachment" in r.headers.get("content-disposition", "")
        body = r.json()
        assert body["kind"] == "debug-bundle"
        data = body["data"]
        for key in (
            "runtime", "corpus", "scheduler", "network",
            "imports", "calendar_imports", "law_documents", "wiki_pages", "errors",
        ):
            assert key in data
        assert data["runtime"]["python"]
        assert "kill_switch" in data["runtime"]
        assert any("synthetic warning" in e["message"] for e in data["errors"])
