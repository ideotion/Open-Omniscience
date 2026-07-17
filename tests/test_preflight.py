"""
Open Omniscience - Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
Source-reliability preflight (maintainer live-test request): robots verdicts,
metadata updates, the shareable JSONL log, and the alert path for denials.
"""

from __future__ import annotations

import uuid

from src.database.models import Source, SourceMetadata
from src.database.session import SessionLocal, init_db
from src.monitoring.preflight import preflight_sources, recent_results


class _Resp:
    def __init__(self, status_code=200, text=""):
        self.status_code = status_code
        self.text = text


class _Sess:
    """robots/homepage scripted per domain."""

    def __init__(self, robots: dict[str, object], home_ok=True):
        self.headers = {}
        self._robots = robots
        self._home_ok = home_ok

    def get(self, url, timeout=None, allow_redirects=True, **kw):
        from urllib.parse import urlparse

        host = urlparse(url).netloc
        if url.endswith("/robots.txt"):
            spec = self._robots.get(host, 200)
            if isinstance(spec, Exception):
                raise spec
            if isinstance(spec, int):
                return _Resp(spec, "User-agent: *\nAllow: /" if spec == 200 else "")
            return _Resp(200, spec)  # explicit robots body
        return _Resp(200 if self._home_ok else 503, "<html>ok</html>")


class _F:
    def __init__(self, session):
        self.session = session
        self.timeout = 5
        self.user_agent = "OpenOmniscienceBot/test"

    # Test doubles for the guarded-fetch methods preflight now routes through
    # (audit fix 2026-07-17, SSRF/CWE-918): a stub session performs no real
    # network I/O, so there is nothing to guard -- mirrors
    # EthicalFetcher._guard_target's own real behaviour for an injected
    # non-real session (a no-op).
    def _guard_target(self, host):
        return None

    def _guarded_redirect_get(self, url, **kw):
        return self.session.get(url, timeout=self.timeout, allow_redirects=False), url


def _mk(session, domain):
    s = Source(name=domain, domain=domain, language="en", enabled=True)
    session.add(s)
    session.flush()
    return s


def test_check_one_refuses_a_private_ip_target_without_any_network_call():
    """Audit finding 2026-07-17 (SSRF, CWE-918): _check_one used to call
    ``fetcher.session.get(url, allow_redirects=True)`` directly on the raw
    requests.Session, bypassing EthicalFetcher's own SSRF guard entirely. A
    REAL EthicalFetcher (a real requests.Session, so _guard_target's checks
    are live) targeting a private-address domain must be refused BEFORE any
    HTTP request is attempted -- IP-literal targets need no DNS resolution,
    so this is a hermetic, network-free test of the real guard."""
    from src.ingest import EthicalFetcher
    from src.monitoring.preflight import _check_one

    fetcher = EthicalFetcher()  # a real requests.Session -- never actually used, the guard fires first
    source = Source(name="internal", domain="127.0.0.1", language="en", enabled=True)

    rec = _check_one(fetcher, source)
    assert rec["verdict"] == "unreachable"
    assert rec["reachable"] is False
    assert "non-public" in rec["robots_error"].lower()


def test_preflight_verdicts_metadata_and_log(tmp_path, monkeypatch):
    monkeypatch.setattr("src.paths.data_dir", lambda: tmp_path)
    init_db()
    db = SessionLocal()
    try:
        ok = _mk(db, f"ok-{uuid.uuid4().hex[:6]}.example")
        denied = _mk(db, f"deny-{uuid.uuid4().hex[:6]}.example")
        delayed = _mk(db, f"slow-{uuid.uuid4().hex[:6]}.example")
        fetcher = _F(_Sess({
            denied.domain: "User-agent: *\nDisallow: /",
            delayed.domain: "User-agent: *\nAllow: /\nCrawl-delay: 7",
        }))
        summary = preflight_sources(db, fetcher, limit=500)  # shared hermetic DB: cover all enabled rows
        assert summary["checked"] >= 3
        assert denied.domain in summary["robots_denied"]  # the loud alert path
        # metadata updated accordingly
        md = db.query(SourceMetadata).filter_by(source_id=denied.id).one()
        assert md.robots_allowed is False
        ms = db.query(SourceMetadata).filter_by(source_id=delayed.id).one()
        assert ms.robots_allowed is True and ms.crawl_delay == 7.0
        assert delayed.rate_limit_ms >= 7000  # politeness raised to honour robots
        # the shareable log exists with one verdict per domain
        rows = recent_results()
        assert {r["domain"] for r in rows} >= {ok.domain, denied.domain, delayed.domain}
        rec = next(r for r in rows if r["domain"] == denied.domain)
        assert rec["verdict"] == "robots_denied" and rec["robots"] == "disallowed"
    finally:
        db.close()
