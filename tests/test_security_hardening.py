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

import src.utils.security as sec
from src.ingest import BlockedTarget, EthicalFetcher
from src.utils.security import csv_safe_cell, safe_href, sanitize_url


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


# --- NET-02: the app-wide sanitizers catch ValueError ONLY ------------------ #
# The two URL sanitizers held ``except Exception: return ""``. That is the right
# ANSWER for the one exception ``urlparse`` genuinely raises (an unterminated
# IPv6 literal) and the wrong one for everything else: a TypeError from a
# bytes/None argument, a RecursionError, an AttributeError from a caller passing
# the wrong object, all became a clean empty string indistinguishable from "this
# link was unsafe". These are the app-wide sanitizers, so a silent swallow here
# is silent everywhere -- every reader/law/link surface that renders an ingested
# URL. Each function gets its ValueError fallback DRIVEN, and a propagation test
# proving an unexpected exception escapes; widening either except back reddens
# exactly the two propagation tests.

# The exception ``urlparse`` genuinely raises: a '[' in the netloc with no ']'.
_INVALID_IPV6 = "https://[::1/path"


def test_the_invalid_ipv6_literal_really_is_the_valueerror_case():
    """Anti-vacuity for the two fallback tests below: if ``urlparse`` ever stopped
    raising here, they would pass without exercising the fallback at all."""
    with pytest.raises(ValueError):
        sec.urlparse(_INVALID_IPV6)


def test_safe_href_invalid_ipv6_takes_the_valueerror_fallback():
    assert safe_href(_INVALID_IPV6) == ""


def test_safe_href_unexpected_exception_propagates(monkeypatch):
    def _boom(url):
        raise RuntimeError("planted: not a parse error")

    monkeypatch.setattr(sec, "urlparse", _boom)
    with pytest.raises(RuntimeError):
        safe_href("https://example.com/x")


def test_sanitize_url_invalid_ipv6_takes_the_valueerror_fallback():
    assert sanitize_url(_INVALID_IPV6) == ""


def test_sanitize_url_unexpected_exception_propagates(monkeypatch):
    def _boom(url):
        raise RuntimeError("planted: not a parse error")

    monkeypatch.setattr(sec, "urlparse", _boom)
    with pytest.raises(RuntimeError):
        sanitize_url("https://example.com/x")


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


def test_script_src_allows_no_inline_script(client):
    """S-006's last clause / NET-04 (0.5 row I, Q1127 = a): script runs only from files.

    Every inline handler became a data-on-* binding run by /static/oo-on.js and every
    inline <script> a file; tests/test_inline_handler_ratchet.py holds both at zero. The
    browser is what enforces the policy, so the policy must actually say it. style-src
    keeps 'unsafe-inline' (unruled), which is why this reads the script-src directive only.
    """
    csp = client.get("/").headers["Content-Security-Policy"]
    directives = {d.split()[0]: d.split()[1:] for d in (x.strip() for x in csp.split(";")) if d}
    assert directives["script-src"] == ["'self'"], csp


def test_swagger_docs_exempt_from_strict_csp(client):
    # /docs loads CDN assets; it must not get the strict 'self' CSP.
    assert "Content-Security-Policy" not in client.get("/docs").headers


# --- S-009: search injection -> 400, never a 500 ---------------------------- #
@pytest.mark.parametrize("q", ['a") OR 1=1 --', "((unbalanced", 'x" AND'])
def test_injection_style_search_returns_400_not_500(client, q):
    r = client.get("/api/articles", params={"query": q})
    assert r.status_code in (200, 400)  # rejected or empty match — never a 500
    assert r.status_code != 500


@pytest.mark.parametrize("bad", [b"https://example.com", 12, object()])
def test_a_non_str_input_already_raised_BEFORE_the_narrowing(bad):
    """PARKED.md parked this narrowing on the blocker "changes behaviour for
    non-str inputs of an app-wide sanitizer". Measured on the pre-fix code, that
    is not true of either function: both run ``re.sub`` (``safe_href``) or a
    ``.lower()`` chain (``sanitize_url``) on the input BEFORE the ``try``, so a
    truthy non-str already raised ``TypeError``/``AttributeError`` OUTSIDE the
    block and the broad except never covered it. Recorded as a test rather than
    an argument, because the blocker is why the item sat parked from 2026-08-20.
    """
    with pytest.raises((TypeError, AttributeError)):
        safe_href(bad)
    with pytest.raises((TypeError, AttributeError)):
        sanitize_url(bad)


# --- R191: a PRESENT Origin/Referer that names no host is refused ------------ #
# `Origin: null` (sandboxed iframe, file:// page, cross-origin redirect) parses to no hostname, and the guard used
# to read "no host" as "no header". Only an ABSENT header is allowed.
@pytest.mark.parametrize("value", ["null", "file://", "file:///etc/hosts", "data:text/html,x", "about:blank", ""])
def test_origin_that_names_no_host_is_refused(client, value):
    r = client.post("/api/briefing/refresh", headers={"Origin": value})
    assert r.status_code == 403, value


@pytest.mark.parametrize("value", ["null", "file:///x", "about:blank"])
def test_referer_that_names_no_host_is_refused(client, value):
    r = client.post("/api/briefing/refresh", headers={"Referer": value})
    assert r.status_code == 403, value


def test_null_origin_is_not_rescued_by_a_loopback_referer(client):
    r = client.post(
        "/api/briefing/refresh",
        headers={"Origin": "null", "Referer": "http://127.0.0.1:8000/"},
    )
    assert r.status_code == 403


def test_a_loopback_origin_is_not_undone_by_a_foreign_referer(client):
    # The Origin decides alone when it is sent (the long-standing behaviour, pinned so the rewrite keeps it).
    r = client.post(
        "/api/briefing/refresh",
        headers={"Origin": "http://localhost:8000", "Referer": "https://evil.example/"},
    )
    assert r.status_code == 200


def test_safe_methods_ignore_a_null_origin(client):
    assert client.get("/api/health", headers={"Origin": "null"}).status_code in (200, 404)


# --- R191: a 422 never echoes the request body ------------------------------- #
CANARY = "canary-passphrase-4f9c1e7a"


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/system/create-db", {"passphrase": CANARY}),  # `confirm` missing
        ("/api/system/encrypt-db", {"passphrase": CANARY, "consent": True}),  # `confirm` missing
        ("/api/system/unlock", {"pass": CANARY, "n": {"x": CANARY}}),  # `passphrase` missing
    ],
)
def test_validation_error_does_not_echo_the_body(client, path, body):
    r = client.post(path, json=body)
    assert r.status_code == 422, (path, r.status_code)
    assert CANARY not in r.text
    for item in r.json()["detail"]:
        assert set(item) == {"type", "loc", "msg"}
        assert "input" not in item and "ctx" not in item


def test_malformed_json_422_does_not_echo_the_body(client):
    r = client.post(
        "/api/system/create-db",
        content=f'{{"passphrase": "{CANARY}", '.encode(),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 422
    assert CANARY not in r.text
    # pydantic's own answer here carries `input` and `ctx`; the key set is what fails on the old handler
    for item in r.json()["detail"]:
        assert set(item) == {"type", "loc", "msg"}
