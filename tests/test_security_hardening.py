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
    # The Origin a browser at the app's own address sends carries the port the Host header carries (TestClient's own Host
    # is ``testserver``, so the address is stated).
    assert (
        client.post(
            "/api/briefing/refresh", headers={"Host": "127.0.0.1:8000", "Origin": "http://127.0.0.1:8000"}
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
        headers={"Host": "localhost:8000", "Origin": "http://localhost:8000", "Referer": "https://evil.example/"},
    )
    assert r.status_code == 200


def test_safe_methods_ignore_a_null_origin(client):
    assert client.get("/api/health", headers={"Origin": "null"}).status_code in (200, 404)


# --- audit 0.5.0 A-001: the Origin must name THIS server, port included --------- #
# The guard compared the Origin's HOSTNAME with the loopback names and nothing else, so any other web app on the machine
# (a dev server, a notebook, a local UI on ``localhost:9999``) passed as a "loopback origin". A browser tells two pages apart
# by scheme, host and port; the Host header carries the host and the port of the server it reached, so the Origin (or the
# Referer, when no Origin is sent) must name the same host and the same effective port (80 / 443 by scheme when none is
# written).
def _from(client, origin=None, referer=None, host="localhost:8000", path="/api/briefing/refresh", **kw):
    headers = {"Host": host}
    if origin is not None:
        headers["Origin"] = origin
    if referer is not None:
        headers["Referer"] = referer
    return client.post(path, headers=headers, **kw)


@pytest.mark.parametrize(
    "host,origin",
    [
        ("localhost:8000", "http://localhost:8000"),
        ("127.0.0.1:8000", "http://127.0.0.1:8000"),
        ("[::1]:8000", "http://[::1]:8000"),
        ("localhost:9123", "http://localhost:9123"),  # OO_PORT is not 8000
        ("LocalHost:8000", "http://localhost:8000"),  # names are case-insensitive
        ("localhost", "http://localhost"),  # no port written on either side: the scheme's own
        ("localhost:80", "http://localhost"),
    ],
)
def test_an_origin_naming_this_server_is_allowed(client, host, origin):
    assert _from(client, origin=origin, host=host).status_code == 200, (host, origin)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:9999",  # another local web app
        "http://127.0.0.1:1",
        "http://localhost",  # port 80, not 8000
        "http://127.0.0.1:80",
        "http://localhost:8001",
        "http://localhost:99999",  # not a port at all
        "http://localhost:abc",
        "ftp://localhost:8000",  # not a web origin
        "http://127.0.0.1:8000",  # the same server by another name: the Host header names localhost
    ],
)
def test_a_loopback_origin_on_another_port_or_name_is_refused(client, origin):
    r = _from(client, origin=origin)
    assert r.status_code == 403, origin
    assert "Cross-origin" in r.json()["detail"]


def test_a_referer_alone_is_held_to_the_same_rule(client):
    assert _from(client, referer="http://localhost:9999/index.html").status_code == 403
    assert _from(client, referer="http://127.0.0.1:1/").status_code == 403
    assert _from(client, referer="http://localhost:8000/index.html").status_code == 200


def test_a_foreign_port_cannot_reach_a_json_route_with_a_body_that_names_no_content_type(client):
    """The route takes a JSON body, and FastAPI parses a body with no Content-Type as JSON, so the request is a CORS
    "simple" one (an untyped Blob) that needs no preflight. The Origin check is what stops it. ``online: false`` is the
    direction that is safe to send: if the guard ever lets it through, the kill switch is engaged and the test says so."""
    from src.ingest import activate_kill_switch, clear_kill_switch, kill_switch_active

    before = kill_switch_active()
    try:
        r = client.post(
            "/api/system/network",
            content=b'{"online": false}',
            headers={"Host": "localhost:8000", "Origin": "http://localhost:9999"},
        )
        assert r.status_code == 403
        assert "content-type" not in {k.lower() for k in r.request.headers}, "the request must carry no Content-Type"
        assert kill_switch_active() == before, "the refused request changed the network mode"
    finally:
        (activate_kill_switch if before else clear_kill_switch)()


def test_oo_allowed_hosts_names_are_accepted_as_an_origin_and_still_port_checked(client, monkeypatch):
    """A-017: the Host guard accepted a LAN self-hoster's name, the CSRF check refused it, so their own UI could not post."""
    host = "myhost.lan:8000"
    assert _from(client, origin="http://myhost.lan:8000", host=host).status_code in (403, 421)  # not listed yet
    monkeypatch.setenv("OO_ALLOWED_HOSTS", "myhost.lan")
    assert _from(client, origin="http://myhost.lan:8000", host=host).status_code == 200
    assert _from(client, origin="http://myhost.lan:9999", host=host).status_code == 403
    assert _from(client, origin="http://evil.example:8000", host=host).status_code == 403


def test_a_tls_proxy_that_forwards_the_scheme_is_the_documented_route(client, monkeypatch):
    """docs/SECURITY.md: behind a reverse proxy that terminates TLS the effective ports must still agree. uvicorn rewrites the
    request's scheme from ``X-Forwarded-Proto`` (from 127.0.0.1 / ::1 by default); here the scheme is set the way the client's
    base URL sets it. ``https`` + ``Origin: https://<name>`` is port 443 on both sides; a proxy that hides the scheme leaves
    ``http`` (port 80) against an https Origin (port 443), which is refused."""
    monkeypatch.setenv("OO_ALLOWED_HOSTS", "myhost.lan")
    from src.api.main import app

    behind_proxy = TestClient(app, base_url="https://myhost.lan")  # no ``with``: the fixture's client already ran the lifespan
    assert behind_proxy.post("/api/briefing/refresh", headers={"Origin": "https://myhost.lan"}).status_code == 200
    scheme_hidden = TestClient(app, base_url="http://myhost.lan")
    r = scheme_hidden.post("/api/briefing/refresh", headers={"Origin": "https://myhost.lan"})
    assert r.status_code == 403 and "Cross-origin" in r.json()["detail"]
    # the name must still be one the operator listed
    monkeypatch.delenv("OO_ALLOWED_HOSTS")
    assert behind_proxy.post("/api/briefing/refresh", headers={"Origin": "https://myhost.lan"}).status_code in (403, 421)


def test_the_test_clients_own_host_name_is_served_only_when_the_operator_lists_it(client, monkeypatch):
    """R226: ``testserver`` (Starlette's TestClient name) is not served by default, as a Host or as an Origin: a page served from a
    name that resolves to an attacker and is then rebound to loopback would pass both checks. ``tests/conftest.py`` lists it the way
    an operator lists a name, which is the only way either check takes it."""
    monkeypatch.delenv("OO_ALLOWED_HOSTS")
    assert _from(client, origin="http://testserver:8000", host="testserver:8000").status_code == 403
    assert _from(client, origin="http://testserver", host="testserver").status_code == 403
    assert _from(client, origin="http://testserver:8000", host="localhost:8000").status_code == 403  # the hostname-equality rule, whatever the allow-set holds
    assert client.get("/api/health", headers={"Host": "testserver"}).status_code == 421
    monkeypatch.setenv("OO_ALLOWED_HOSTS", "testserver")
    assert _from(client, origin="http://testserver:8000", host="testserver:8000").status_code == 200
    assert client.get("/api/health", headers={"Host": "testserver"}).status_code == 200


def test_an_over_long_port_in_the_host_header_is_refused_not_a_server_error(client):
    """``int()`` of a run of more than 4,300 digits raises; the middleware answered 500 where the old guard answered 200."""
    r = _from(client, origin="http://localhost:8000", host="localhost:" + "9" * 5000)
    assert r.status_code == 403


def test_a_bracketed_ipv6_name_in_oo_allowed_hosts_works_for_both_guards(client, monkeypatch):
    """The Host guard reads ``[fe80::1]:8000`` as ``[fe80::1]``; urlparse hands the Origin's name back without its brackets. An
    operator who lists the bracketed spelling (as the docs say) must get past both, and the port is still checked."""
    host = "[fe80::1]:8000"
    monkeypatch.setenv("OO_ALLOWED_HOSTS", "[fe80::1]")
    assert _from(client, origin="http://[fe80::1]:8000", host=host).status_code == 200
    assert _from(client, origin="http://[fe80::1]:9999", host=host).status_code == 403
    assert _from(client, origin="http://[fe80::2]:8000", host=host).status_code == 403


def test_the_two_readers_agree_on_odd_values():
    from src.api.main import _host_header_parts, _origin_parts

    assert _origin_parts("http://localhost:8000") == ("localhost", 8000)
    assert _origin_parts("https://localhost") == ("localhost", 443)
    assert _origin_parts("http://[::1]:8000/x?y#z") == ("::1", 8000)
    assert _origin_parts("HTTP://LocalHost") == ("localhost", 80)
    for bad in ("", "null", "file:///x", "about:blank", "data:text/html,x", "ftp://localhost", "http://localhost:99999", "http://localhost:x", "http://"):
        assert _origin_parts(bad) is None, bad
    assert _host_header_parts("localhost:8000", "http") == ("localhost", 8000)
    assert _host_header_parts("localhost", "https") == ("localhost", 443)
    assert _host_header_parts("[::1]:8000", "http") == ("::1", 8000)
    assert _host_header_parts("[::1]", "http") == ("::1", 80)
    assert _host_header_parts("::1", "http") == ("::1", 80)  # a raw IPv6 literal has no port
    for bad in ("localhost:", "localhost:abc", "localhost:0", "localhost:65536", "localhost:-1", "[::1]x", "localhost:" + "9" * 5000):
        assert _host_header_parts(bad, "http") is None, bad


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
