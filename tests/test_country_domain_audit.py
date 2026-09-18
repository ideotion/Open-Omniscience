"""Q1115: a country field that contradicts its own domain — PROPOSED, never corrected.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Institutions C7 found `cityofvancouver.us` — a US city — carrying `country: ca`, and said in
the same breath what the fix must NOT be: **"a naive ccTLD check is NOT the audit (`.uk` vs
`gb` and `.eu` for EU bodies are both legitimate)."**

So most of what follows tests the REFUSALS. A rule that rewrote `country` from the ccTLD
would fix the one row and break two whole classes at once, and the damage would be invisible
at the moment it ran — it shows up as a country distribution nobody can explain months later.
The fixture therefore carries one row per legitimate pattern, so the audit has to decline
each of them by name rather than by luck.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.catalog.country_domain_audit import (
    SKIP_AGREES,
    SKIP_NO_COUNTRY,
    SKIP_NO_SIGNAL,
    SKIP_SUPRANATIONAL,
    audit_rows,
)

# (id, domain, stored_country, expectation) — one row per case the docket names.
FIXTURE = [
    (1, "cityofvancouver.us", "ca", "propose"),   # C7's own finding
    (2, "bbc.co.uk", "fr", "propose"),            # a real disagreement UNDER .uk
    (3, "gov.uk", "gb", SKIP_AGREES),             # .uk stored as gb: legitimate
    (4, "europa.eu", "be", SKIP_SUPRANATIONAL),   # a union, not a country
    (5, "who.is", "ch", SKIP_NO_SIGNAL),          # .is repurposed as generic
    (6, "example.com", "de", SKIP_NO_SIGNAL),     # a gTLD says nothing
    (7, "praha.cz", None, SKIP_NO_COUNTRY),       # absent is not wrong
    (8, "lemonde.fr", "fr", SKIP_AGREES),
]


@pytest.fixture
def audited() -> dict:
    return audit_rows((i, d, c) for i, d, c, _ in FIXTURE)


def test_the_fixture_covers_every_outcome_the_ruling_names(audited: dict) -> None:
    """Anti-vacuity. Each refusal below is only meaningful because a row exercises it; a
    fixture missing the `.eu` or `.uk` case would let the audit pass while breaking them."""
    expected = {e for _i, _d, _c, e in FIXTURE}
    assert expected == {"propose", SKIP_AGREES, SKIP_SUPRANATIONAL, SKIP_NO_SIGNAL,
                        SKIP_NO_COUNTRY}
    assert audited["examined"] == len(FIXTURE)


def test_the_finding_that_prompted_the_ruling_is_proposed(audited: dict) -> None:
    proposed = {p["domain"] for p in audited["proposals"]}
    assert "cityofvancouver.us" in proposed
    row = next(p for p in audited["proposals"] if p["domain"] == "cityofvancouver.us")
    assert row["stored_country"] == "ca" and row["domain_implies"] == "us"
    # BOTH values travel, because which one is wrong is a question for a person.
    assert "ca" in row["reason"] and "us" in row["reason"]
    assert "question for a person" in row["reason"]


@pytest.mark.parametrize(
    ("domain", "why"),
    [(d, e) for _i, d, _c, e in FIXTURE if e != "propose"],
)
def test_a_legitimate_pattern_is_never_proposed(domain, why, audited: dict) -> None:
    """The refusals, one case each so a failure names the pattern that broke."""
    assert domain not in {p["domain"] for p in audited["proposals"]}, (
        f"{domain} was proposed; the ruling names it as legitimate ({why})"
    )


def test_every_row_is_accounted_for_in_exactly_one_bucket(audited: dict) -> None:
    """A diagnostic that publishes only its hits cannot be checked for over-reach OR for
    quietly examining almost nothing, so the skips are counted and must sum."""
    assert audited["proposed"] + sum(audited["skipped"].values()) == audited["examined"]
    assert audited["skipped"][SKIP_SUPRANATIONAL] == 1
    assert audited["skipped"][SKIP_NO_COUNTRY] == 1
    assert audited["skipped"][SKIP_AGREES] == 2
    assert audited["skipped"][SKIP_NO_SIGNAL] == 2


def test_the_cctld_meaning_is_read_from_one_module_not_restated() -> None:
    """One module decides what a ccTLD means. Two would drift, and the drift would show up
    as a country audit disagreeing with the country inference on the same domain."""
    from src.catalog import cctld
    from src.catalog.country_domain_audit import _domain_country

    for domain in ("lemonde.fr", "praha.cz", "bbc.co.uk"):
        implied, _why = _domain_country(domain)
        inferred = cctld.infer_country(domain) or cctld._SPECIAL_COUNTRY.get(
            cctld._tld(domain) or ""
        )
        assert implied == inferred, f"{domain}: audit says {implied}, cctld says {inferred}"


def test_it_proposes_and_never_applies() -> None:
    """The ruling's word is 'proposes'. There is no apply, and the caveat says so where a
    reader meets the numbers."""
    from src.api import source_management as sm

    src = Path(sm.__file__).read_text(encoding="utf-8")
    assert "/country-domain-audit/apply" not in src
    out = audit_rows([(1, "cityofvancouver.us", "ca")])
    assert "nothing is applied" in out["caveat"].lower()
    assert "weak evidence" in out["caveat"]


def test_the_route_answers_and_is_not_shadowed() -> None:
    from fastapi.testclient import TestClient

    from src.api import source_management as sm
    from src.api.main import app

    paths = [r.path for r in sm.router.routes]
    first = min(i for i, p in enumerate(paths) if "country-domain-audit" in p)
    by_id = min(i for i, p in enumerate(paths) if "{source_id}" in p)
    assert first < by_id, "the audit route is shadowed by /{source_id}"

    with TestClient(app) as c:
        r = c.get("/api/sources/country-domain-audit?limit=10")
        assert r.status_code == 200, r.text
        body = r.json()
        assert set(body) >= {"proposals", "examined", "proposed", "skipped", "caveat"}
