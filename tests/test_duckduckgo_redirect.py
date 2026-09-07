"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

PRH-03: DuckDuckGo's HTML endpoint does not link results directly. Every
``result__a`` href is a protocol-relative hop through its own ``/l/`` redirect,
with the real target percent-encoded in ``uddg`` and a ``rut`` signature beside
it. ``_clean_url`` stripped the query string BEFORE validating, so the target
was discarded and the remaining ``//duckduckgo.com/l/`` was rejected as
scheme-less -- every real result dropped, silently, in the ONE sanctioned
external channel this app has.

WHAT THE FIXTURES ARE, stated rather than implied: ``duckduckgo.com`` is
egress-blocked from this sandbox (``curl`` -> 000 against a ``pypi.org`` 200
control), so the HTML below is a specimen written to DuckDuckGo's DOCUMENTED
redirect shape, not a captured live response. That is enough to pin the defect
and the fix -- the parser only ever sees the href -- and it is NOT enough to
claim the live markup is unchanged; ``test_the_parser_still_reads_a_direct_href``
is what keeps the older shape working if it is.

Both directions are pinned, because an over-eager unwrap is as wrong as the
omission: the unwrap must not smuggle a non-http scheme past ``safe_href``, must
not fire for a host that merely carries a ``uddg`` parameter, and must leave a
direct href byte-identical to what it produced before the fix.
"""

from __future__ import annotations

from urllib.parse import quote

import pytest

from src.services.duckduckgo import DuckDuckGoSearch

# The real shape: protocol-relative, "uddg" percent-encoded, "&amp;" separator
# (it arrives from raw markup), a "rut" signature after it.
_TARGET = "https://example.com/world/2026/story"


def _hop(target: str, *, host: str = "duckduckgo.com", entity: bool = True) -> str:
    sep = "&amp;" if entity else "&"
    return f"//{host}/l/?uddg={quote(target, safe='')}{sep}rut=0123456789abcdef"


# --------------------------------------------------------------------------- #
# Anti-vacuity: the fixture really is the shape this file is about
# --------------------------------------------------------------------------- #


def test_the_fixture_is_the_redirect_shape_and_not_a_direct_href():
    """Without this, every assertion below could be passing about a plain URL."""
    href = _hop(_TARGET)
    assert href.startswith("//duckduckgo.com/l/?uddg=")
    assert "&amp;rut=" in href
    assert _TARGET not in href, "the target must be ENCODED, or the test proves nothing"


# --------------------------------------------------------------------------- #
# The defect and the fix
# --------------------------------------------------------------------------- #


def test_a_redirect_result_yields_its_target():
    assert DuckDuckGoSearch._clean_url(_hop(_TARGET)) == _TARGET


def test_a_redirect_target_keeps_its_own_query_string():
    """An older CMS puts the article id in the query ("/news/?articleid=2504").
    "uddg" is the complete address DuckDuckGo resolved, so stripping it would
    re-introduce this fix's own defect one layer down."""
    target = "https://antiwar.example/news/?articleid=2504"
    assert DuckDuckGoSearch._clean_url(_hop(target)) == target


def test_an_https_scheme_on_the_hop_is_also_unwrapped():
    assert DuckDuckGoSearch._clean_url("https:" + _hop(_TARGET)) == _TARGET


def test_a_subdomain_hop_is_unwrapped():
    assert DuckDuckGoSearch._clean_url(_hop(_TARGET, host="html.duckduckgo.com")) == _TARGET


def test_a_plain_ampersand_separator_is_unwrapped_too():
    assert DuckDuckGoSearch._clean_url(_hop(_TARGET, entity=False)) == _TARGET


def test_uddg_is_found_when_it_is_not_the_FIRST_parameter():
    """The discriminating input for the entity-unescape ORDER. Splitting the query on
    a raw "&" leaves the second pair named "amp;uddg", so a hop that puts "rut" first
    -- parameter order is DuckDuckGo's choice, not ours -- loses its target unless
    "&amp;" became "&" BEFORE the query is read. Without this case the move is
    equivalent to the old order and the test suite could not tell them apart."""
    href = "//duckduckgo.com/l/?rut=0123456789abcdef&amp;uddg=" + quote(_TARGET, safe="")
    assert DuckDuckGoSearch._clean_url(href) == _TARGET


def test_a_target_carrying_a_literal_percent_is_decoded_exactly_once():
    """The raw "uddg" value is handed to the caller's single ``unquote``. Decoding
    it in the unwrap as well would turn %2525 into a bare "%"."""
    target = "https://example.com/a%25b"
    assert DuckDuckGoSearch._clean_url(_hop(target)) == target


# --------------------------------------------------------------------------- #
# Negative space: the unwrap must not become a smuggling route
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "file:///etc/passwd",
        "ftp://host.example/file",
    ],
)
def test_a_redirect_carrying_a_non_http_target_is_refused(bad):
    """The unwrapped target meets the SAME ``safe_href`` allowlist a direct href
    does -- otherwise the fix would hand an attacker a way past it.

    Measured by mutation, because the two halves are not interchangeable: with
    ``safe_href`` neutered only ``ftp://`` survives here. ``javascript:``/``data:``/
    ``file:`` carry no authority, so the ``parsed.netloc`` check refuses them first.
    ``safe_href`` is what stands between discovery and a scheme that DOES have a
    host, which is exactly the class a redirect hop could smuggle."""
    assert DuckDuckGoSearch._clean_url(_hop(bad)) is None


def test_a_redirect_carrying_a_scheme_less_target_is_refused():
    assert DuckDuckGoSearch._clean_url(_hop("example.com/story")) is None


def test_a_hop_with_no_uddg_is_refused_rather_than_falling_through():
    """A DuckDuckGo-internal link is not a result. Falling through would leave the
    scheme-less "//duckduckgo.com/l/" -- rejected today by accident, and the
    accident is what the fix must not rely on."""
    assert DuckDuckGoSearch._clean_url("//duckduckgo.com/l/?rut=0123456789abcdef") is None


def test_an_ABSOLUTE_target_less_hop_is_refused_by_the_guard_and_not_by_luck():
    """The discriminating input for that guard. A protocol-relative hop falls out on
    its own once the query is stripped (no scheme), so the guard looks redundant --
    the mutation replacing it with a fall-through passes every other test here. An
    ABSOLUTE hop does not: strip its query and "https://duckduckgo.com/l/" is a
    perfectly valid http URL, so without the guard a DuckDuckGo-internal link is
    returned as a search result and gets fetched as a source."""
    assert DuckDuckGoSearch._clean_url("https://duckduckgo.com/l/?rut=0123456789abcdef") is None


def test_an_empty_uddg_is_refused():
    assert DuckDuckGoSearch._clean_url("//duckduckgo.com/l/?uddg=&rut=abc") is None


def test_a_foreign_host_carrying_a_uddg_parameter_is_not_unwrapped():
    """Only DuckDuckGo's own hop is unwrapped. A page we merely found must never
    be able to redirect discovery at a target of its choosing -- here the foreign
    URL keeps the pre-existing tracking strip and the "uddg" value is ignored."""
    href = "https://evil.example/l/?uddg=" + quote("https://target.example/x", safe="")
    assert DuckDuckGoSearch._clean_url(href) == "https://evil.example/l/"


def test_a_lookalike_host_is_not_unwrapped():
    """"duckduckgo.com" as a LABEL PREFIX of somebody else's domain must not match.
    Asserted as the exact surviving URL rather than "is None", so the test cannot
    pass merely because the lookalike was rejected for some other reason."""
    href = "https://duckduckgo.com.evil.example/l/?uddg=" + quote("https://t.example/x", safe="")
    assert DuckDuckGoSearch._clean_url(href) == "https://duckduckgo.com.evil.example/l/"


# --------------------------------------------------------------------------- #
# Negative-space twin: the direct-href path is unchanged
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.com/story", "https://example.com/story"),
        ("https://example.com/a?utm_source=ddg", "https://example.com/a"),
        ("https://example.com/a&amp;b", "https://example.com/a&b"),
        ("https://example.com/a&amp;b?x=1", "https://example.com/a&b"),
        ("example.com/story", None),
        ("", None),
    ],
)
def test_the_parser_still_reads_a_direct_href(raw, expected):
    """The entity-unescape moved AHEAD of the query strip. It cannot change where
    the first "?" is (``&amp;`` contains none and produces none), so a direct href
    resolves to exactly what it did before -- pinned rather than argued."""
    assert DuckDuckGoSearch._clean_url(raw) == expected


# --------------------------------------------------------------------------- #
# End to end, through the real parser: the before/after
# --------------------------------------------------------------------------- #


_HTML = f"""
<html>
  <div class="result">
    <a class="result__a" href="{_hop("https://alpha.example/one")}">Alpha</a>
  </div>
  <div class="result">
    <a class="result__a" href="{_hop("https://beta.example/two?id=9")}">Beta</a>
  </div>
  <div class="result">
    <a class="result__a" href="{_hop("javascript:alert(1)")}">Hostile</a>
  </div>
</html>
"""


def test_parse_results_returns_the_redirect_backed_results():
    """BEFORE the fix this returned []: all three hrefs lost their target to the
    query strip and were rejected as scheme-less. AFTER, the two real results
    survive with their domains, and the hostile one is still refused."""
    out = DuckDuckGoSearch._parse_results(_HTML, max_results=10)
    assert [r["url"] for r in out] == [
        "https://alpha.example/one",
        "https://beta.example/two?id=9",
    ]
    assert [r["domain"] for r in out] == ["alpha.example", "beta.example"]
    assert [r["title"] for r in out] == ["Alpha", "Beta"]
