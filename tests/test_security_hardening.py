"""
Regression tests for the security-audit hardening (S-001..S-009).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Each test pins a control the audit added so it cannot silently regress: CSV formula-
injection neutralization, the http(s) href allowlist, the SSRF target guard, the
CSRF/Origin refusal + security headers, and search-injection -> 400 (not 500).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.ingest import BlockedTarget, EthicalFetcher
from src.utils.security import csv_safe_cell, safe_href


# --- S-004: CSV / spreadsheet formula injection ----------------------------- #
@pytest.mark.parametrize("dangerous", ["=cmd()", "+1", "-1+2", "@SUM(A1)", "\tTAB", "\rCR"])
def test_csv_safe_cell_neutralizes_formula_leaders(dangerous):
    out = csv_safe_cell(dangerous)
    assert out.startswith("'"), f"{dangerous!r} not neutralized -> {out!r}"


def test_csv_safe_cell_leaves_benign_values():
    assert csv_safe_cell("BBC News") == "BBC News"
    assert csv_safe_cell(42) == "42"
    assert csv_safe_cell(None) == ""


# --- S-005: javascript:/data: URI not rendered as a link -------------------- #
@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(1)",
        "data:text/html,<script>1</script>",
        " javascript:alert(1)",
        "vbscript:msgbox",
        "file:///etc/passwd",
    ],
)
def test_safe_href_drops_dangerous_schemes(bad):
    assert safe_href(bad) == ""


def test_safe_href_keeps_http_links():
    assert safe_href("https://example.com/a") == "https://example.com/a"
    assert safe_href("http://example.com") == "http://example.com"


# --- S-001: SSRF target guard ----------------------------------------------- #
@pytest.mark.parametrize(
    "internal",
    [
        "http://127.0.0.1/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://10.0.0.5/",
        "http://192.168.1.1/",
        "http://[::1]/",
    ],
)
def test_fetcher_blocks_internal_ip_literals(internal):
    with pytest.raises(BlockedTarget):
        EthicalFetcher().fetch(internal)


def test_fetcher_rejects_non_http_scheme():
    from src.ingest import FetchFailed

    with pytest.raises(FetchFailed):
        EthicalFetcher().fetch("ftp://example.com/x")


# --- S-003 / S-006: CSRF refusal + security headers ------------------------- #
@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_cross_origin_state_change_is_refused(client):
    r = client.post("/api/briefing/refresh", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_origin_and_no_origin_allowed(client):
    assert client.post("/api/briefing/refresh").status_code == 200
    assert (
        client.post(
            "/api/briefing/refresh", headers={"Origin": "http://127.0.0.1:8000"}
        ).status_code
        == 200
    )


def test_security_headers_present(client):
    h = client.get("/").headers
    assert h.get("X-Content-Type-Options") == "nosniff"
    assert h.get("X-Frame-Options") == "DENY"
    assert (
        "Content-Security-Policy" in h and "frame-ancestors 'none'" in h["Content-Security-Policy"]
    )


def test_swagger_docs_exempt_from_strict_csp(client):
    # /docs loads CDN assets; it must not get the strict 'self' CSP.
    assert "Content-Security-Policy" not in client.get("/docs").headers


# --- S-009: search injection -> 400, never a 500 ---------------------------- #
@pytest.mark.parametrize("q", ['a") OR 1=1 --', "((unbalanced", 'x" AND'])
def test_injection_style_search_returns_400_not_500(client, q):
    r = client.get("/api/articles", params={"query": q})
    assert r.status_code in (200, 400)  # rejected or empty match — never a 500
    assert r.status_code != 500
