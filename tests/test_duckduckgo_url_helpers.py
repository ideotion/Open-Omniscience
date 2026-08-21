"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Pins for the BUG-05 narrowing: the duckduckgo URL-parsing helper fallbacks
(`_clean_url` / `_extract_domain` / `_resolve_url`) catch ``ValueError`` ONLY.
The narrowing itself already shipped; until now nothing exercised it, so a
drive-by "harden" back to ``except Exception`` would have landed green. Each
helper gets its fallback branch driven by the one realistic ``ValueError``
(an invalid IPv6 literal, the exception ``urlparse`` genuinely raises) AND a
propagation test proving an UNEXPECTED exception escapes — the half a widened
except would silently swallow, which is exactly how these tests would redden.

Deliberately imported via the canonical ``src.services.duckduckgo`` path (the
older test_duckduckgo.py imports a ``services.duckduckgo`` sys.path alias — a
different module object).

Recorded here, NOT fixed (behaviour changes, out of this session's territory):
* ``safe_href`` (src/utils/security.py) still holds a broad ``except`` in the
  ``_clean_url`` chain.
* ``_clean_url`` strips the query string BEFORE validation, which drops the
  ``uddg=`` target of real DuckDuckGo ``/l/?uddg=...`` redirect results. That
  finding is recorded in PARKED.md; the happy-path tests below use query-less
  URLs so the strip semantics are deliberately NOT pinned as correct.
"""

from __future__ import annotations

import pytest

import src.services.duckduckgo as ddg_mod
from src.services.duckduckgo import DuckDuckGoSearch

# The exception urlparse genuinely raises: a '[' in the netloc with no ']'.
_INVALID_IPV6 = "https://[::1/path"


# --------------------------------------------------------------------------- #
# _clean_url
# --------------------------------------------------------------------------- #


def test_clean_url_accepts_a_plain_http_url():
    assert DuckDuckGoSearch._clean_url("https://example.com/story") == "https://example.com/story"


def test_clean_url_rejects_a_scheme_less_url():
    assert DuckDuckGoSearch._clean_url("example.com/story") is None


def test_clean_url_invalid_ipv6_takes_the_valueerror_fallback():
    # Sanity first: this really is the ValueError case, not a silent parse.
    with pytest.raises(ValueError):
        ddg_mod.urlparse(_INVALID_IPV6)
    assert DuckDuckGoSearch._clean_url(_INVALID_IPV6) is None


def test_clean_url_rejects_a_non_http_scheme_via_safe_href():
    assert DuckDuckGoSearch._clean_url("ftp://host.example/file") is None


def test_clean_url_unexpected_exception_propagates(monkeypatch):
    """A planted non-ValueError from urlparse must ESCAPE — the except is
    ``ValueError`` only. Widening it back to ``except Exception`` turns this
    into a silent ``None`` and reddens the test."""

    def _boom(url):
        raise RuntimeError("planted: not a parse error")

    monkeypatch.setattr(ddg_mod, "urlparse", _boom)
    with pytest.raises(RuntimeError):
        DuckDuckGoSearch._clean_url("https://example.com/x")


# --------------------------------------------------------------------------- #
# _extract_domain
# --------------------------------------------------------------------------- #


def test_extract_domain_strips_www():
    assert DuckDuckGoSearch._extract_domain("https://www.example.com/a") == "example.com"


def test_extract_domain_invalid_ipv6_takes_the_valueerror_fallback():
    assert DuckDuckGoSearch._extract_domain(_INVALID_IPV6) == ""


def test_extract_domain_unexpected_exception_propagates(monkeypatch):
    def _boom(url):
        raise RuntimeError("planted: not a parse error")

    monkeypatch.setattr(ddg_mod, "urlparse", _boom)
    with pytest.raises(RuntimeError):
        DuckDuckGoSearch._extract_domain("https://example.com/a")


# --------------------------------------------------------------------------- #
# _resolve_url
# --------------------------------------------------------------------------- #


def test_resolve_url_passes_an_absolute_url_through():
    assert (
        DuckDuckGoSearch._resolve_url("https://x.example/f.xml", "https://base.example/")
        == "https://x.example/f.xml"
    )


def test_resolve_url_joins_a_root_relative_path_against_the_base():
    assert (
        DuckDuckGoSearch._resolve_url("/feed.xml", "https://base.example/dir")
        == "https://base.example/feed.xml"
    )


def test_resolve_url_invalid_ipv6_base_takes_the_valueerror_fallback():
    assert DuckDuckGoSearch._resolve_url("feed.xml", _INVALID_IPV6) is None


def test_resolve_url_none_path_propagates_attribute_error():
    """``None.startswith`` raises AttributeError, which the narrowed except
    must NOT swallow: the caller's own ``except Exception`` net (with its
    logger.exception traceback) is the designed place for it, never a silent
    per-helper ``None``. ``discover_sources_by_topic`` can feed exactly this
    when a search result stores ``None`` under "url"."""
    with pytest.raises(AttributeError):
        DuckDuckGoSearch._resolve_url(None, "https://base.example/")
