"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Regression tests for fetcher safety-limit findings TEST-01/02/03:
  - TEST-01: max body-size cap is enforced (declared Content-Length and
             materialised body).
  - TEST-02: the redirect cap terminates a redirect chain.
  - TEST-03: the SSRF guard refuses a hostname that *resolves* to an internal
             address (DNS-rebinding-to-internal), exercising the resolve path.

The fetcher's limit logic (`_read_body`, `_http_get`) runs on an injected test
session, so TEST-01/02 use a fake session. The SSRF guard only runs on a real
session, so TEST-03 uses a real EthicalFetcher with socket.getaddrinfo patched.
"""

from __future__ import annotations

import socket

import pytest

import src.ingest as ingest_mod
from src.ingest import BlockedTarget, EthicalFetcher, FetchFailed


# --------------------------------------------------------------------------- #
# Fake session that supports redirects (Location) and explicit headers/content.
# --------------------------------------------------------------------------- #

class _Resp:
    def __init__(self, status_code=200, text="", content_type="text/html",
                 url=None, location=None, content_length=None):
        self.status_code = status_code
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        if location is not None:
            self.headers["Location"] = location
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self.url = url

    def close(self):
        pass


class _Session:
    def __init__(self):
        self.headers = {}
        self._routes = {}

    def route(self, url, **kwargs):
        self._routes[url] = _Resp(url=url, **kwargs)

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        if url in self._routes:
            return self._routes[url]
        # default: permissive robots.txt or a 404 for anything unrouted
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", url=url, content_type="text/plain")
        return _Resp(status_code=404, text="not found", url=url)


def _fetcher(session, **kw):
    return EthicalFetcher(min_interval_s=0.0, session=session, **kw)


# --- TEST-01: body-size cap ------------------------------------------------- #

def test_declared_content_length_over_cap_is_rejected():
    sess = _Session()
    sess.route("https://example.com/robots.txt", text="User-agent: *\nAllow: /",
               content_type="text/plain")
    sess.route("https://example.com/big", text="x", content_length=10_000_000)
    f = _fetcher(sess, max_bytes=1024)
    with pytest.raises(FetchFailed, match="declared length"):
        f.fetch("https://example.com/big")


def test_materialised_body_over_cap_is_rejected():
    sess = _Session()
    sess.route("https://example.com/robots.txt", text="User-agent: *\nAllow: /",
               content_type="text/plain")
    # No Content-Length header, but the actual body exceeds the cap.
    sess.route("https://example.com/big", text="A" * 5000)
    f = _fetcher(sess, max_bytes=1024)
    with pytest.raises(FetchFailed, match="exceeds"):
        f.fetch("https://example.com/big")


# --- TEST-02: redirect cap -------------------------------------------------- #

class _RedirectSession(_Session):
    """Always 302s to the next numbered URL -> an unbounded chain."""

    def get(self, url, timeout=None, allow_redirects=True, **kwargs):
        if url.endswith("/robots.txt"):
            return _Resp(text="User-agent: *\nAllow: /", url=url, content_type="text/plain")
        return _Resp(status_code=302, location=f"{url}/next", url=url)


def test_redirect_chain_terminates_at_cap():
    f = _fetcher(_RedirectSession())
    with pytest.raises(FetchFailed, match="too many redirects"):
        f.fetch("https://example.com/loop")


# --- TEST-03: SSRF guard blocks a hostname resolving to an internal IP ------- #

def test_hostname_resolving_to_internal_ip_is_blocked(monkeypatch):
    """A public-looking hostname that resolves to 127.0.0.1 (DNS rebinding to
    internal) must be refused by the SSRF guard's resolve-and-check path."""

    def fake_getaddrinfo(host, *a, **k):
        # Pretend the name resolves to loopback regardless of how it looks.
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0)  # real session => guard active
    with pytest.raises(BlockedTarget, match="non-public"):
        f.fetch("https://totally-public.example/")


def test_hostname_resolving_to_metadata_ip_is_blocked(monkeypatch):
    """The cloud metadata endpoint (169.254.169.254) must be refused even when
    reached via a benign-looking hostname."""

    def fake_getaddrinfo(host, *a, **k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("169.254.169.254", 0))]

    monkeypatch.setattr(ingest_mod.socket, "getaddrinfo", fake_getaddrinfo)
    f = EthicalFetcher(min_interval_s=0.0)
    with pytest.raises(BlockedTarget):
        f.fetch("https://metadata.example/")
