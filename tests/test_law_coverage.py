"""
S5 of the law-vertical brief (2026-07-17): the per-jurisdiction law coverage/
freshness diagnostic. Counts + verdict tallies only, no score; THE COMPLETENESS
PRINCIPLE (never present a tracked count as a coverage claim) is pinned as an
explicit, honest string on every jurisdiction.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument
from src.law.coverage import (
    COVERAGE_NO_COUNTRY,
    COVERAGE_NO_ENUMERATION,
    COVERAGE_UNIT_UNDECLARED,
    law_coverage_report,
    official_enumerations,
)

# A crafted enumeration map, so the unit tests below are not asserting against the
# 225-source shipped harvest. ONE guard (the last in this file) deliberately drives the
# real catalog, because the shipped data is its own claim.
_ENUM = {
    "fr": [{"value": 76, "unit": "codes en vigueur", "as_of": "2026-07-17",
            "source_url": "https://legi.example/codes", "domain": "legi.example",
            "country": "fr", "off_domain_source": False}],
    "ng": [{"value": 0, "unit": "current legislation documents", "as_of": "2026-07-17",
            "source_url": "https://ng.example/legislation", "domain": "ng.example",
            "country": "ng", "off_domain_source": False,
            "source_notes": "Real, important gap, not an estimate."}],
}


def _assert_no_fraction_anywhere(payload, *, tracked: int, enumerated: int) -> None:
    """The negative-space guard for the completeness principle, applied to the WHOLE
    payload rather than to the one key a fraction would obviously live in.

    A coverage fraction is exactly what this report must never publish, and it could
    arrive under any name. So compute what the forbidden numbers would be and assert
    that none of them appears as a value anywhere in the payload, at any depth. The
    percentage form and the raw ratio are both checked, because "13%" and "0.13" are
    the same fabrication.
    """
    forbidden = set()
    if enumerated:
        forbidden.add(round(100 * tracked / enumerated, 1))
        forbidden.add(round(tracked / enumerated, 4))
    seen: list = []

    def walk(node, path="$"):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")
        elif isinstance(node, float):
            seen.append((path, node))

    walk(payload)
    # baseline_pct is a REAL measurement over the tracked set (how many of the documents
    # we track have a baseline) and is not a coverage claim, so it is exempt BY PATH.
    offenders = [
        (p, v) for p, v in seen
        if v in forbidden and not p.endswith("baseline_pct")
    ]
    assert not offenders, f"a coverage fraction reached the payload: {offenders}"


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)()


def test_empty_store_reports_zero_honestly():
    s = _session()
    r = law_coverage_report(s)
    assert r["documents"] == 0 and r["baselined"] == 0
    assert r["jurisdictions"] == []
    assert "no score" in r["method"] or "no score" in r["caveat"]


def test_per_jurisdiction_counts_and_verdicts():
    s = _session()
    now = datetime.now(UTC)
    s.add_all(
        [
            LawDocument(
                jurisdiction="uk", title="Act 1", url="https://law.example/uk1",
                baseline_text="x", last_status="baseline captured", last_checked_at=now,
            ),
            LawDocument(
                jurisdiction="uk", title="Act 2", url="https://law.example/uk2",
                last_status="fetch error: robots.txt disallows https://x",
                last_checked_at=now - timedelta(hours=5),
            ),
            LawDocument(
                jurisdiction="fr", title="Loi 1", url="https://law.example/fr1",
                baseline_text="y", last_status="changed (+10 bytes vs baseline)",
                last_checked_at=now,
            ),
            LawDocument(jurisdiction="fr", title="Loi 2", url="https://law.example/fr2"),  # never checked
        ]
    )
    s.commit()

    r = law_coverage_report(s)
    assert r["documents"] == 4 and r["baselined"] == 2
    by_jur = {j["jurisdiction"]: j for j in r["jurisdictions"]}
    assert set(by_jur) == {"fr", "uk"}

    uk = by_jur["uk"]
    assert uk["tracked"] == 2 and uk["baselined"] == 1 and uk["baseline_pct"] == 50.0
    assert uk["verdicts"] == {"baselined": 1, "robots_blocked": 1}
    assert uk["never_checked"] == 0
    assert uk["oldest_check_age_hours"] == 5.0 and uk["newest_check_age_hours"] == 0.0

    fr = by_jur["fr"]
    assert fr["tracked"] == 2 and fr["baselined"] == 1
    assert fr["verdicts"] == {"changed": 1}
    assert fr["never_checked"] == 1  # Loi 2 was never fetched


def test_completeness_principle_never_fabricates_a_coverage_fraction():
    """THE COMPLETENESS PRINCIPLE (brief §2). AMENDED 2026-09-07 (S4): the report now
    PRINTS a jurisdiction's own official enumeration when the catalog knows one, so the
    old assertion (a fixed "no enumeration adapter" string on every jurisdiction) would
    now pass only by the report having stayed useless. The property it guarded is
    unchanged and is asserted more strongly below: whatever is known, no fraction of
    tracked-over-enumerated is ever computed."""
    s = _session()
    s.add(LawDocument(jurisdiction="fr", title="Loi", url="https://law.example/fr",
                      country="fr"))
    s.commit()
    r = law_coverage_report(s, enumerations=_ENUM)
    cov = r["jurisdictions"][0]["coverage"]
    assert cov["state"] == COVERAGE_UNIT_UNDECLARED
    assert cov["official_enumeration"][0]["value"] == 76
    _assert_no_fraction_anywhere(r, tracked=1, enumerated=76)


def test_never_checked_document_does_not_pollute_the_age_stats():
    s = _session()
    s.add(LawDocument(jurisdiction="us", title="Statute", url="https://law.example/us"))
    s.commit()
    r = law_coverage_report(s)
    us = r["jurisdictions"][0]
    assert us["never_checked"] == 1
    assert us["oldest_check_age_hours"] is None and us["newest_check_age_hours"] is None


# ---------------------------------------------------------------------------
# S4 (2026-09-07): the catalog's own dated official counts become real denominators,
# and the report still never divides by them.
# ---------------------------------------------------------------------------


def test_the_three_coverage_states_are_three_different_facts():
    """"we could not look up an enumeration", "we looked and there is none" and "here
    is one" are three distinct answers. Collapsing any two of them into one sentinel is
    the one-key-two-meanings defect, and the middle one is the only one that means
    coverage is genuinely unknown."""
    s = _session()
    s.add_all([
        # states no country -> nothing to look up (the catalog is keyed by country)
        LawDocument(jurisdiction="tl", title="Codigo", url="https://law.example/tl"),
        # a country we know, with no count in the catalog
        LawDocument(jurisdiction="uk", title="Act", url="https://law.example/uk", country="gb"),
        # a country we know, with a count
        LawDocument(jurisdiction="fr", title="Loi", url="https://law.example/fr", country="fr"),
    ])
    s.commit()
    by_jur = {j["jurisdiction"]: j["coverage"]
              for j in law_coverage_report(s, enumerations=_ENUM)["jurisdictions"]}
    assert by_jur["tl"]["state"] == COVERAGE_NO_COUNTRY
    assert by_jur["uk"]["state"] == COVERAGE_NO_ENUMERATION
    assert by_jur["fr"]["state"] == COVERAGE_UNIT_UNDECLARED
    assert len({c["state"] for c in by_jur.values()}) == 3
    for cov in by_jur.values():
        assert cov["reason"], "every state carries its own reason"
        assert cov["official_enumeration"] == [] or cov["state"] == COVERAGE_UNIT_UNDECLARED


def test_the_jurisdiction_code_is_never_read_as_a_country():
    """`uk` documents state country `gb` and the jurisdiction column is deliberately
    "ISO-ish". Joining on the CODE would both miss that pair and risk attaching some
    other country's enumeration to a code that collides with its ISO-2. The join runs
    only through what the documents themselves state.

    The negative twin is the point: `uk` must find the `gb` figure and must NOT find a
    figure filed under the literal string `uk`."""
    s = _session()
    s.add(LawDocument(jurisdiction="uk", title="Act", url="https://law.example/uk", country="gb"))
    s.commit()
    enum = {
        "gb": [{"value": 5, "unit": "acts", "as_of": "2026-07-17", "domain": "gb.example",
                "source_url": "https://gb.example/", "country": "gb",
                "off_domain_source": False}],
        "uk": [{"value": 999, "unit": "decoy", "as_of": "2026-07-17", "domain": "uk.example",
                "source_url": "https://uk.example/", "country": "uk",
                "off_domain_source": False}],
    }
    cov = law_coverage_report(s, enumerations=enum)["jurisdictions"][0]["coverage"]
    assert cov["countries"] == ["gb"]
    assert [f["value"] for f in cov["official_enumeration"]] == [5]


def test_a_measured_zero_is_not_a_missing_enumeration():
    """Nigeria's two figures are 0 because the producing session fetched the platform and
    found it genuinely empty. A zero denominator must read as "enumerated: none exist",
    never fall through to "we have no enumeration" — and it must still not be divided by."""
    s = _session()
    s.add(LawDocument(jurisdiction="ng", title="Act", url="https://law.example/ng", country="ng"))
    s.commit()
    r = law_coverage_report(s, enumerations=_ENUM)
    cov = r["jurisdictions"][0]["coverage"]
    assert cov["state"] == COVERAGE_UNIT_UNDECLARED, "a measured 0 IS an enumeration"
    assert cov["official_enumeration"][0]["value"] == 0
    assert "not an estimate" in cov["official_enumeration"][0]["source_notes"]
    _assert_no_fraction_anywhere(r, tracked=1, enumerated=0)


def test_countries_enumerated_but_untracked_are_named():
    """The gap made legible. Without this the report can only describe jurisdictions
    already being watched, which is the shape that lets a vertical look healthy while
    covering almost nothing."""
    s = _session()
    s.add(LawDocument(jurisdiction="fr", title="Loi", url="https://law.example/fr", country="fr"))
    s.commit()
    en = law_coverage_report(s, enumerations=_ENUM)["enumeration"]
    assert en["countries_with_an_official_count"] == 2
    assert en["countries_enumerated_but_untracked"] == 1
    assert [u["country"] for u in en["untracked"]] == ["ng"]
    assert en["untracked"][0]["official_enumeration"][0]["value"] == 0


def test_the_real_catalog_supplies_dated_sourced_denominators():
    """Deliberately drives the SHIPPED catalog: the figures are the claim, so a unit
    test against a crafted map cannot stand in for them. Every figure must carry the
    as_of and source_url the validator already refuses a count without, so none of them
    can be an estimate."""
    enum = official_enumerations()
    figures = [f for v in enum.values() for f in v]
    assert len(enum) >= 30 and len(figures) >= 39, (len(enum), len(figures))
    for f in figures:
        assert f["as_of"] and f["source_url"] and f["unit"], f
        assert isinstance(f["value"], int)
    # The two disclosure channels, each on a figure that only IT can catch.
    coe = [f for f in enum["int"] if "wikipedia.org" in f["source_url"]]
    assert coe and coe[0]["off_domain_source"] is True, (
        "the Council of Europe count is sourced from Wikipedia, not from coe.int — the "
        "derived off-domain flag is what says so"
    )
    au = [f for f in enum["int"] if f["domain"] == "au.int"]
    assert au and au[0]["off_domain_source"] is False and "manual tally" in au[0]["source_notes"], (
        "the African Union count IS on-domain, so only the row's own notes disclose that "
        "it is a manual tally — carrying them verbatim is the second channel"
    )
    assert [f["value"] for f in enum["ng"]] == [0, 0], "Nigeria's measured zeros survive"
