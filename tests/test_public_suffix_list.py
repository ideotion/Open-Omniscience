"""The vendored Public Suffix List: verified against the upstream's OWN vectors.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

WHY THE CANONICAL VECTORS AND NOT HAND-WRITTEN CASES. A hand-written expectation
is a value I chose, so a test built from them measures my understanding of the
algorithm rather than the algorithm. ``tests/data/public_suffix_list_tests.txt``
is the vector set published BY the list's maintainers (CC0), so it is evidence
about the implementation and not about its author.

IT PAID FOR ITSELF ON THE FIRST RUN, which is the entry worth keeping: my
hand-written cases were all green and the canonical set found two real defects.
(1) A LEADING DOT was stripped, so ``.example.com`` answered ``example.com``
where the spec says a malformed input has no registrable domain. (2) The list
stores internationalised rules in UNICODE (``公司.cn``) while hosts arrive in
PUNYCODE, so every ``xn--``-encoded host fell through to the wrong suffix -- a
defect with NO positive-space symptom at all: the answers looked like ordinary
domains.
"""

from __future__ import annotations

import hashlib
import shlex
from pathlib import Path

import pytest

from src.catalog import publicsuffix as PS

_VECTORS = Path(__file__).resolve().parent / "data" / "public_suffix_list_tests.txt"

# The vector file's own digest. Pinned here rather than in the registry because it
# is a TEST fixture; the registry entry's couplings name it and require the two to
# be refreshed together (a newer list judged by older vectors proves nothing).
_VECTORS_SHA256 = "61a3a502cf471d1a919d5e43c10e910023b0c4230e1db506f8e2ff0b47d2234e"


@pytest.fixture(autouse=True)
def _fresh_cache():
    """The module memoises the parsed list; a test that swaps the file must not
    inherit a previous test's parse."""
    PS._reset_cache_for_tests()
    yield
    PS._reset_cache_for_tests()


def _canonical_cases() -> list[tuple[str | None, str | None]]:
    out: list[tuple[str | None, str | None]] = []
    for line in _VECTORS.read_text("utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        host, expected = shlex.split(s)
        out.append((None if host == "null" else host, None if expected == "null" else expected))
    return out


def test_the_vendored_list_matches_its_recorded_digest():
    data = PS._LIST_PATH.read_bytes()
    assert hashlib.sha256(data).hexdigest() == PS.PUBLIC_SUFFIX_LIST_SHA256, (
        "the vendored Public Suffix List is not the file its constant describes"
    )
    assert hashlib.sha256(_VECTORS.read_bytes()).hexdigest() == _VECTORS_SHA256, (
        "the canonical vectors are not the file this test's constant describes"
    )


def test_every_canonical_upstream_vector_passes():
    cases = _canonical_cases()
    # Anti-vacuity: an empty or truncated vector file would make this pass for free.
    assert len(cases) >= 70, f"only {len(cases)} vectors parsed from {_VECTORS.name}"
    bad = [
        (host, expected, PS.registrable_domain_psl(host, include_private=True))
        for host, expected in cases
        if PS.registrable_domain_psl(host, include_private=True) != expected
    ]
    assert not bad, f"{len(bad)} of {len(cases)} canonical vectors fail: {bad[:5]}"


def test_the_icann_private_split_is_a_real_choice_not_a_default():
    """Both readings must be reachable and they must DIFFER, or the argument is
    decoration and a caller cannot actually pick a rule."""
    assert PS.registrable_domain_psl("someone.github.io", include_private=True) == "someone.github.io"
    assert PS.registrable_domain_psl("someone.github.io", include_private=False) == "github.io"
    # And where no private rule applies, the two agree — so the flag is not simply
    # bolting a label on.
    for host in ("email.bbc.com", "www.bbc.co.uk", "mail.example.co.jp"):
        assert PS.registrable_domain_psl(host, include_private=True) == PS.registrable_domain_psl(
            host, include_private=False
        ), host


def test_a_public_suffix_is_never_returned_as_a_publisher():
    """``co.uk`` names no registrant. Answering it would present a suffix as a
    publisher and merge every British site into one source."""
    for suffix in ("co.uk", "uk", "com", "org.au", "ac.jp"):
        assert PS.registrable_domain_psl(suffix, include_private=True) is None, suffix


def test_a_missing_list_degrades_with_a_reason_and_never_guesses(monkeypatch, tmp_path):
    """The negative space: with no list, a lookup must be an honest absence. A
    two-label fallback would answer ``co.uk`` for ``bbc.co.uk`` — a WRONG publisher,
    which reads as data rather than as an error."""
    monkeypatch.setattr(PS, "_LIST_PATH", tmp_path / "absent.dat")
    PS._reset_cache_for_tests()
    status = PS.list_status()
    assert status["available"] is False
    assert status["reason"] and "could not be read" in status["reason"]
    for host in ("bbc.co.uk", "email.bbc.com", "someone.github.io"):
        assert PS.registrable_domain_psl(host, include_private=True) is None, host
        assert PS.public_suffix(host, include_private=True) is None, host


def test_a_tampered_list_is_refused_rather_than_parsed(monkeypatch, tmp_path):
    """Unknown bytes must never become publishers. A digest mismatch is a refusal
    with the two digests named, not a best-effort parse."""
    fake = tmp_path / "public_suffix_list.dat"
    fake.write_text("// ===BEGIN ICANN DOMAINS===\ncom\nevil\n// ===END ICANN DOMAINS===\n", "utf-8")
    monkeypatch.setattr(PS, "_LIST_PATH", fake)
    PS._reset_cache_for_tests()
    status = PS.list_status()
    assert status["available"] is False
    assert "digest" in (status["reason"] or "")
    assert PS.registrable_domain_psl("a.evil", include_private=True) is None


def test_an_ip_literal_or_a_non_domain_has_no_registrable_domain():
    for host in ("192.168.1.2", "10.0.0.1", "localhost", "", None, "[::1]", "a..b.com"):
        assert PS.registrable_domain_psl(host, include_private=True) is None, host


def test_list_status_states_its_method_and_its_vintage():
    status = PS.list_status()
    assert status["available"] is True
    assert status["as_of"] == PS.PUBLIC_SUFFIX_LIST_AS_OF
    assert "no network call" in status["method"]
    assert status["icann_rules"] > 5000 and status["private_rules"] > 1000
