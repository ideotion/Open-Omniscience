"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

NET-02: the last two broad ``except Exception`` blocks in the URL-parsing path --
``sanitize_url`` and ``safe_href`` in ``src/utils/security.py`` -- narrowed to the
``ValueError`` ``urlparse`` actually raises, mirroring the BUG-05 narrowing already
pinned for the DuckDuckGo helpers in ``tests/test_duckduckgo_url_helpers.py``.

WHY THIS IS SAFE, measured rather than argued. PARKED.md parked this on "narrowing
changes behaviour for non-str inputs of an app-wide sanitizer". It does not: BOTH
functions run ``re.sub`` on the input BEFORE the ``try``, and ``re.sub`` with a str
pattern raises ``TypeError`` on a non-str -- outside the block, today, unchanged.
The two function-local ``from urllib.parse import urlparse`` lines were hoisted to
module scope in the same change, exactly as ``src/services/duckduckgo.py`` already
does, so a propagation pin can reach the name at all.
``test_a_non_str_input_already_raised_before_the_narrowing`` pins that premise, so a
future reader can see the blocker was refuted rather than overruled.

WHY IT IS WORTH DOING. ``except Exception`` here fails CLOSED (drops the href), which
is the safe direction and is exactly what makes it invisible: a genuine bug inside the
sanitizer would read as "this link is unsafe", forever, on every link, with nothing
saying so -- the degrade-wrapper-as-hiding-place shape the ledger records for K2 and
``ai_diagnostics._safe``. The realistic failure keeps returning ``""``; only an
UNEXPECTED one now escapes to the caller, where it can be seen.
"""

from __future__ import annotations

import pytest

import src.utils.security as sec
from src.utils.security import safe_href, sanitize_url

# The exception urlparse genuinely raises: a '[' in the netloc with no ']'.
_INVALID_IPV6 = "https://[::1/path"


def test_the_invalid_ipv6_really_is_a_valueerror():
    """Anti-vacuity: without this the fallback tests below could be passing about a
    URL that parses perfectly well."""
    from urllib.parse import urlparse

    with pytest.raises(ValueError):
        urlparse(_INVALID_IPV6)


# --------------------------------------------------------------------------- #
# The realistic failure still fails CLOSED
# --------------------------------------------------------------------------- #


def test_safe_href_invalid_ipv6_still_returns_empty():
    assert safe_href(_INVALID_IPV6) == ""


def test_sanitize_url_invalid_ipv6_still_returns_empty():
    assert sanitize_url(_INVALID_IPV6) == ""


# --------------------------------------------------------------------------- #
# An UNEXPECTED exception now escapes instead of being swallowed
# --------------------------------------------------------------------------- #


def test_safe_href_unexpected_exception_propagates(monkeypatch):
    """Widening back to ``except Exception`` turns this into a silent ``""`` and
    reddens the test by name."""

    def _boom(url):
        raise RuntimeError("planted: not a parse error")

    monkeypatch.setattr(sec, "urlparse", _boom)
    with pytest.raises(RuntimeError):
        safe_href("https://example.com/a")


def test_sanitize_url_unexpected_exception_propagates(monkeypatch):
    def _boom(url):
        raise RuntimeError("planted: not a parse error")

    monkeypatch.setattr(sec, "urlparse", _boom)
    with pytest.raises(RuntimeError):
        sanitize_url("https://example.com/a")


# --------------------------------------------------------------------------- #
# The premise PARKED.md parked this on, refuted
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bad", [123, 4.5, ["https://example.com"], {"a": 1}, object()])
def test_a_non_str_input_already_raised_before_the_narrowing(bad):
    """A truthy non-str never reached the ``try`` in either function: ``re.sub``
    with a str pattern rejects it first. So the broad except never covered this
    case and narrowing cannot have changed it."""
    with pytest.raises(TypeError):
        safe_href(bad)
    with pytest.raises(TypeError):
        sanitize_url(bad)


# --------------------------------------------------------------------------- #
# Negative-space twin: the sanitizers still sanitize
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "bad",
    [
        "javascript:alert(1)",
        " javascript:alert(1)",
        "data:text/html;base64,PHNjcmlwdD4=",
        "vbscript:msgbox(1)",
        "file:///etc/passwd",
        "ftp://host.example/f",
    ],
)
def test_safe_href_still_drops_every_dangerous_scheme(bad):
    assert safe_href(bad) == ""


def test_safe_href_still_keeps_http_links():
    assert safe_href("https://example.com/a") == "https://example.com/a"
    assert safe_href("http://example.com") == "http://example.com"


def test_sanitize_url_still_drops_dangerous_schemes_and_keeps_relative_paths():
    assert sanitize_url("javascript:alert(1)") == ""
    assert sanitize_url("/relative/path") == "/relative/path"
    assert sanitize_url("https://example.com/a") == "https://example.com/a"
