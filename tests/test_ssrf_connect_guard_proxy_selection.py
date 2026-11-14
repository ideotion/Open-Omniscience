"""The EthicalFetcher's connect-time scope allows only the proxy each request actually goes through (follow-up to PR #1979).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``_guarded_redirect_get`` gave ``connect_scope`` the whole merged proxy mapping. A proxy named by a HOSTNAME for a scheme this
request does not use (``HTTPS_PROXY=http://corp-proxy:3128`` and a plain ``http://`` page) stood the check down for a request that
went direct, so a name that resolved public at ``_guard_target`` time and loopback at connect time (DNS rebinding) was fetched: the
window the connect-time guard exists to close. And a loopback proxy for the other scheme let a direct request reach its port. The
scope of each request now holds the one proxy ``requests.utils.select_proxy`` picks for that request's URL, the function the adapter
itself uses, so the two cannot disagree.
"""

from __future__ import annotations

import os

import pytest

from src.ingest import BlockedTarget
from tests.test_ssrf_connect_guard import _REQUEST_LINES, _fetcher, loopback_server, rebinding_dns  # noqa: F401 - fixtures

pytestmark = pytest.mark.usefixtures("rebinding_dns")


@pytest.fixture
def clean_proxy_env(monkeypatch):
    for name in [n for n in os.environ if n.lower().endswith("_proxy")]:  # the machine's own would win over the one set here
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OO_SSRF_CONNECT_GUARD", raising=False)
    return monkeypatch


@pytest.mark.parametrize("variable", ["HTTPS_PROXY", "all_proxy_unused_scheme"])
def test_a_hostname_proxy_for_another_scheme_cannot_stand_the_guard_down(loopback_server: int, clean_proxy_env, variable: str):  # noqa: F811
    """Before: the rebinding name was fetched as a 200 while ``HTTPS_PROXY`` named a host, for a plain-http page that went direct."""
    if variable == "HTTPS_PROXY":
        clean_proxy_env.setenv("HTTPS_PROXY", "http://proxy.invalid:3128")
        fetcher = _fetcher()
    else:  # the same through the session's own mapping
        fetcher = _fetcher()
        fetcher.session.proxies = {"https": "http://proxy.invalid:3128"}
    with pytest.raises(BlockedTarget) as excinfo:
        fetcher.fetch(f"http://rebind.test:{loopback_server}/")
    assert "127.0.0.1" in str(excinfo.value)
    assert _REQUEST_LINES == []


def test_a_loopback_proxy_for_the_other_scheme_does_not_open_its_port(loopback_server: int, clean_proxy_env):  # noqa: F811
    """The proxy's exact address and port are allowed only to a request that goes THROUGH it. (A pin, not a reproduction: on the
    EthicalFetcher the resolution check already refused this one, since the rebinding answer is not the asked host.)"""
    fetcher = _fetcher()
    fetcher.session.proxies = {"https": f"http://127.0.0.1:{loopback_server}"}
    with pytest.raises(BlockedTarget):
        fetcher.fetch(f"http://rebind.test:{loopback_server}/")
    assert _REQUEST_LINES == []


def test_a_request_through_its_own_loopback_proxy_still_works(loopback_server: int, clean_proxy_env):  # noqa: F811
    """The proxied path is unchanged: the proxy this request uses is allowed by its exact address and port."""
    fetcher = _fetcher()
    proxy = f"http://127.0.0.1:{loopback_server}"
    fetcher.session.proxies = {"http": proxy}
    result = fetcher.fetch("http://rebind.test/page")
    assert "INTERNAL SERVICE SECRET" in str(getattr(result, "html", result))
    assert _REQUEST_LINES and _REQUEST_LINES[0].startswith("http://rebind.test")


@pytest.fixture
def idn_rebinding(rebinding_dns):  # noqa: F811 - wraps the resolver the rebinding fixture installed
    """``bücher.test`` (IDNA ``xn--bcher-kva.test``) answers public once, then loopback."""
    import socket

    import src.ingest.airplane as ap
    from tests.test_ssrf_connect_guard import _PUBLIC

    inner = ap._orig_getaddrinfo
    calls: list[str] = []

    def _resolver(host, port, *args, **kwargs):  # type: ignore[no-untyped-def]
        name = host.decode() if isinstance(host, bytes) else host
        if name in ("bücher.test", "xn--bcher-kva.test"):
            calls.append(name)
            answer = _PUBLIC if len(calls) == 1 else "127.0.0.1"
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (answer, port or 0))]
        return inner(host, port, *args, **kwargs)

    ap._orig_getaddrinfo = _resolver  # type: ignore[assignment]
    try:
        yield calls
    finally:
        ap._orig_getaddrinfo = inner  # type: ignore[assignment]


@pytest.mark.parametrize(
    "setup",
    ["env-no-proxy", "per-host-key"],
)
def test_an_idn_host_selects_its_proxy_as_the_adapter_does(loopback_server: int, clean_proxy_env, idn_rebinding, setup: str):  # noqa: F811
    """Before: the scope selected on the RAW url (``bücher.test``) while requests selects on the IDNA-encoded one, so a Punycode
    ``NO_PROXY`` entry (or a Unicode per-host key) made our side expect the hostname proxy and stand down while requests went direct:
    the rebinding name's loopback answer was fetched (security read C on PR #2001)."""
    if setup == "env-no-proxy":
        clean_proxy_env.setenv("HTTP_PROXY", "http://proxy.invalid:3128")
        clean_proxy_env.setenv("NO_PROXY", "xn--bcher-kva.test")
        fetcher = _fetcher()
    else:
        fetcher = _fetcher()
        fetcher.session.proxies = {"http://bücher.test": "http://proxy.invalid:3128"}  # a key never matches the encoded host
    with pytest.raises(BlockedTarget) as excinfo:
        fetcher.fetch(f"http://bücher.test:{loopback_server}/")
    assert "127.0.0.1" in str(excinfo.value)
    assert _REQUEST_LINES == []
