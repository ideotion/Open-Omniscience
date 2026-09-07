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

BOTH residuals this file recorded as "NOT fixed" are now CLOSED (2026-09-07,
prompt 21 S2) and pinned here and in ``test_security_hardening.py``:
* ``safe_href`` / ``sanitize_url`` (src/utils/security.py) caught ``Exception``;
  both now catch ``ValueError`` only, pinned by the NET-02 block in
  ``tests/test_security_hardening.py`` (this file's helpers were already narrow).
* ``_clean_url`` stripped the query string BEFORE validation, which dropped the
  ``uddg=`` target of real DuckDuckGo ``/l/?uddg=...`` redirect results -- every
  one of them, in the one sanctioned external discovery channel. The redirect is
  now resolved FIRST, by ``_unwrap_search_redirect``; the PRH-03 block at the
  bottom of this file pins the resolution, the discard cases, and the
  byte-identical path a non-redirect URL still takes.

The query strip itself is DELIBERATELY unchanged and still not pinned as
"correct": it is right for this consumer (``discover_sources_by_topic`` keeps the
DOMAIN and treats the URL as a homepage to look for feeds under) and wrong in
general, for the recorded reason that a URL's query can BE the article address.
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


# --------------------------------------------------------------------------- #
# PRH-03: the DuckDuckGo /l/?uddg= redirect
# --------------------------------------------------------------------------- #
#
# DuckDuckGo's HTML endpoint links its OWN redirector, not the publisher. Before
# the fix, _clean_url stripped the query string before validating, so every such
# result reached the validator as "//duckduckgo.com/l/" -- scheme-less, therefore
# dropped. The tests below pin the resolution, the two ways a redirect is
# DISCARDED rather than half-trusted, and the byte-identical path a non-redirect
# URL still takes (the negative-space half: an over-eager unwrap that rewrote
# ordinary results would be the same defect pointing the other way).

_TARGET = "https://news.example/world/story-1"
_ENCODED = "https%3A%2F%2Fnews.example%2Fworld%2Fstory-1"


def test_a_protocol_relative_ddg_redirect_resolves_to_the_publisher_url():
    assert (
        DuckDuckGoSearch._clean_url(f"//duckduckgo.com/l/?uddg={_ENCODED}&rut=abc123")
        == _TARGET
    )


def test_a_root_relative_ddg_redirect_resolves_too():
    """DuckDuckGo has also emitted the host-less form."""
    assert DuckDuckGoSearch._clean_url(f"/l/?kh=-1&uddg={_ENCODED}") == _TARGET


def test_the_html_entity_form_resolves():
    """The href arrives out of raw HTML, so its separators are ``&amp;``."""
    assert DuckDuckGoSearch._clean_url(f"//duckduckgo.com/l/?uddg={_ENCODED}&amp;rut=abc") == _TARGET


def test_the_redirect_no_longer_reads_as_scheme_less_and_is_no_longer_dropped():
    """The exact defect, stated as its own assertion: the pre-fix behaviour was
    ``None`` (dropped), and the wrong repair would have been the redirector."""
    out = DuckDuckGoSearch._clean_url(f"//duckduckgo.com/l/?uddg={_ENCODED}&rut=abc123")
    assert out is not None, "the redirect is dropped again -- PRH-03 has regressed"
    assert "duckduckgo.com" not in out


def test_parse_results_carries_the_publisher_domain_not_the_redirector():
    """The WIRING, not the helper: a helper test cannot see that ``_parse_results``
    still calls it, nor that ``_extract_domain`` then reads the publisher host --
    which is the field ``discover_sources_by_topic`` dedups and names sources by."""
    html = (
        '<a class="result__a" href="//duckduckgo.com/l/?uddg='
        + _ENCODED
        + '&amp;rut=deadbeef">World story</a>'
    )
    results = DuckDuckGoSearch._parse_results(html, max_results=5)
    assert len(results) == 1, results
    assert results[0]["url"] == _TARGET
    assert results[0]["domain"] == "news.example"


# --- discard, never half-trust --------------------------------------------- #
#
# Tested at BOTH levels deliberately, and the split is the point. Through
# ``_clean_url`` the relative / dangerous-scheme refusals are EQUIVALENT to the
# caller's own later scheme+netloc check and ``safe_href`` -- measured, by
# mutation: deleting the refusal changes no outcome there. They are this
# helper's own contract, so they are pinned by DIRECT tests of the helper. The
# MISSING-target case is not equivalent at either level, and the absolute
# redirector URL below is the input that shows why.


def test_a_redirect_with_no_target_is_discarded():
    assert DuckDuckGoSearch._clean_url("//duckduckgo.com/l/?rut=abc123") is None


def test_an_absolute_redirector_with_no_target_never_becomes_a_ddg_source():
    """The discriminating shape: ``https://duckduckgo.com/l/`` is a perfectly
    valid https URL, so falling back to the redirector instead of discarding it
    would hand ``_parse_results`` duckduckgo.com as a DISCOVERED SOURCE, with its
    own domain, ready for ``discover_sources_by_topic`` to register."""
    assert DuckDuckGoSearch._clean_url("https://duckduckgo.com/l/?rut=abc123") is None


def test_a_redirect_whose_target_is_a_dangerous_scheme_is_discarded():
    assert (
        DuckDuckGoSearch._clean_url("//duckduckgo.com/l/?uddg=javascript%3Aalert(1)") is None
    )


def test_a_redirect_whose_target_is_relative_is_discarded():
    assert DuckDuckGoSearch._clean_url("//duckduckgo.com/l/?uddg=%2Fsettings") is None


# --- the helper's own contract, driven directly ----------------------------- #


def test_unwrap_returns_none_for_a_relative_target():
    assert DuckDuckGoSearch._unwrap_search_redirect("//duckduckgo.com/l/?uddg=%2Fsettings") is None


def test_unwrap_returns_none_for_a_dangerous_scheme_target():
    assert (
        DuckDuckGoSearch._unwrap_search_redirect("//duckduckgo.com/l/?uddg=javascript%3Aalert(1)")
        is None
    )


def test_unwrap_returns_none_for_a_missing_target():
    assert DuckDuckGoSearch._unwrap_search_redirect("//duckduckgo.com/l/?rut=abc") is None


def test_unwrap_returns_the_input_unchanged_for_a_non_redirect():
    assert (
        DuckDuckGoSearch._unwrap_search_redirect("https://news.example/a?x=1")
        == "https://news.example/a?x=1"
    )


def test_a_duckduckgo_host_on_another_path_is_not_a_redirect():
    """The path check on its own: without it, the host check alone would let any
    duckduckgo.com URL carrying a ``uddg`` parameter be rewritten."""
    raw = "//duckduckgo.com/html/?uddg=https%3A%2F%2Fevil.example%2F"
    assert DuckDuckGoSearch._unwrap_search_redirect(raw) == raw
    assert DuckDuckGoSearch._clean_url(raw) is None


# --- negative space: nothing else changed ----------------------------------- #


def test_a_plain_result_url_is_untouched_by_the_unwrap():
    assert DuckDuckGoSearch._clean_url("https://news.example/a") == "https://news.example/a"


def test_a_foreign_host_with_an_l_path_is_never_unwrapped():
    """An over-eager unwrap would let any site's ``/l/?uddg=`` hand us a URL we
    then treat as a discovered source. Only DuckDuckGo's own redirector counts."""
    assert (
        DuckDuckGoSearch._clean_url("https://news.example/l/?uddg=https%3A%2F%2Fevil.example%2F")
        == "https://news.example/l/"
    )


def test_a_uddg_parameter_on_an_ordinary_path_is_never_unwrapped():
    """The path check is load-bearing on its own: without it, ANY result URL
    carrying a ``uddg`` parameter would be rewritten to whatever it names."""
    assert (
        DuckDuckGoSearch._clean_url("https://news.example/a?uddg=https%3A%2F%2Fevil.example%2F")
        == "https://news.example/a"
    )


def test_the_query_strip_still_applies_to_an_ordinary_result():
    """Deliberately pinned as UNCHANGED, not as correct -- see the module docstring."""
    assert DuckDuckGoSearch._clean_url("https://news.example/a?utm_source=x") == "https://news.example/a"


def test_an_unwrapped_target_keeps_its_path():
    """The target's own path must survive; only its query meets the strip."""
    assert (
        DuckDuckGoSearch._clean_url(
            "//duckduckgo.com/l/?uddg=https%3A%2F%2Fnews.example%2Fdeep%2Fpath%2F%3Fid%3D9"
        )
        == "https://news.example/deep/path/"
    )


# --- PRH-03, negative space that the host check owns ------------------------ #
#
# Added on the PROMPT_20 branch AFTER PR #1031 landed the implementation above,
# because two sessions found PRH-03 in parallel. Everything the other session
# built is kept; these four are the cases its matrix does not reach, and each is
# a branch of ``_unwrap_search_redirect`` that no test here drives.


def test_a_subdomain_hop_is_unwrapped():
    """``html.duckduckgo.com`` is the host this app actually fetches
    (``SEARCH_URL``), so the ``endswith(".duckduckgo.com")`` branch is not a
    generality -- it is the production path, and nothing above drives it."""
    assert (
        DuckDuckGoSearch._clean_url(f"//html.duckduckgo.com/l/?uddg={_ENCODED}&rut=abc")
        == _TARGET
    )


def test_a_lookalike_host_is_not_unwrapped():
    """``duckduckgo.com`` as a LABEL PREFIX of somebody else's domain must not
    match. This is what makes the pair ``host != HOST and not
    host.endswith("." + HOST)`` load-bearing rather than decorative: a
    substring test would accept this host and hand discovery whatever it names.
    Asserted as the exact surviving URL rather than ``is None``, so it cannot
    pass merely because the lookalike was refused for some other reason."""
    assert (
        DuckDuckGoSearch._clean_url(f"https://duckduckgo.com.evil.example/l/?uddg={_ENCODED}")
        == "https://duckduckgo.com.evil.example/l/"
    )


def test_uddg_is_found_when_it_is_not_the_FIRST_parameter():
    """Parameter order is DuckDuckGo's choice, not ours, and this is the
    discriminating input for the entity-unescape ORDER: reading the query before
    ``&amp;`` becomes ``&`` leaves the second pair named ``amp;uddg``, so a hop
    that puts ``rut`` first loses its target. With ``uddg`` first the two orders
    are indistinguishable."""
    assert (
        DuckDuckGoSearch._clean_url(f"//duckduckgo.com/l/?rut=abc123&amp;uddg={_ENCODED}")
        == _TARGET
    )


def test_an_EMPTY_uddg_is_discarded_and_not_merely_a_missing_one():
    """``keep_blank_values=False`` is what makes an empty target read as absent.
    Distinct from the missing-parameter case above: drop that flag and this hop
    unwraps to ``""``, which is falsy, so the discard still happens -- but by a
    different line. Pinned so the flag cannot be changed silently."""
    assert DuckDuckGoSearch._clean_url("//duckduckgo.com/l/?uddg=&rut=abc") is None
