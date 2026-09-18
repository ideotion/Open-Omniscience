"""The Stage B splice: admit on agreement, defer the rest, block what is flagged.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1119 = a (admit where both judges agree; defer the ~15 % contested band), Q1112 = b (a
`restricted_namespace` trip cannot be spliced without a written override; never a silent
drop), Q1117 = a (Czech municipalities admitted, tagged with the vendor path, the balance
shift disclosed) and Q1116 = a (a bare identifier is resolved or the row is declined).

THE DEFECT THESE WERE WRITTEN AFTER, because it is the one worth guarding: a first cut read
"admit where both judges agree" literally and admitted every agreeing row — including the 623
rows both judges agree are institutions and agree are NOT primary sources. That would have
asserted into `official_sources.yml`, which is a list of primary sources, the exact opposite
of what both judges said, and it nearly doubled the reported admissions (1,471 against the
807 actually earned). **Agreement is necessary and not sufficient**, and rejecting those rows
is equally wrong, because Q1110 = a defers the `primary_source` axis rather than rejecting it.
So they are deferred under their own reason, and that reason is asserted by name below.
"""

from __future__ import annotations

import pytest

from src.catalog.stage_b_splice import (
    ADMITTED,
    BLOCKED,
    DECLINED,
    DEFERRED,
    REASON_KIND,
    REASON_NOT_PRIMARY,
    REASON_ONE_JUDGE,
    REASON_PRIMARY,
    REASON_RESTRICTED,
    ROUTED,
    balance_shift,
    splice,
    vendor_path_tag,
)

BUCKETS = (ADMITTED, DEFERRED, BLOCKED, DECLINED, ROUTED)


def _j(domain, kind="institution", primary=True, language="en"):
    return {"domain": domain, "kind": kind, "primary_source": primary, "language": language}


@pytest.fixture
def decided() -> dict:
    """One row per outcome the rulings name, so every assertion has a case of its own."""
    a = [
        _j("agree-primary.cz"),                       # -> admitted
        _j("agree-not-primary.fr", primary=False),    # -> deferred (Q1110 defers the axis)
        _j("kind-clash.de"),                          # -> deferred
        _j("primary-clash.it"),                       # -> deferred
        _j("flagged.gob.ve"),                         # -> blocked (both judges agree!)
        _j("unnamed.pl"),                             # -> declined (bare id, unresolved)
        _j("named.pt"),                               # -> admitted, renamed
        _j("a-journal.se", kind="academic"),          # -> routed
        _j("lonely.no"),                              # -> deferred (one judge only)
    ]
    b = [
        _j("agree-primary.cz"),
        _j("agree-not-primary.fr", primary=False),
        _j("kind-clash.de", kind="news"),
        _j("primary-clash.it", primary=False),
        _j("flagged.gob.ve"),
        _j("unnamed.pl"),
        _j("named.pt"),
        _j("a-journal.se", kind="academic"),
    ]
    return splice(
        a, b,
        integrity_tiers={"flagged.gob.ve": "restricted_namespace", "other.gov.id": "restricted_namespace"},
        names={"unnamed.pl": "Q987654", "named.pt": "Q111"},
        resolved_labels={"Q111": "Câmara Municipal"},
        rss_urls={"agree-primary.cz": "https://agree-primary.cz/uredni-deska?action=atom"},
    )


def _where(decided: dict, domain: str) -> str:
    found = [b for b in BUCKETS if any(r["domain"] == domain for r in decided[b])]
    assert len(found) == 1, f"{domain} landed in {found}, must be exactly one bucket"
    return found[0]


def test_every_row_lands_in_exactly_one_bucket_and_they_sum(decided: dict) -> None:
    """Anti-vacuity and anti-loss at once: a row that fell out of every bucket would be a
    candidate silently dropped, which is the one thing Q1112 names by its own words."""
    rep = decided["report"]
    total = sum(len(decided[b]) for b in BUCKETS)
    assert total == rep["paired_rows"] + rep["single_judge_rows"] == 9
    domains = [r["domain"] for b in BUCKETS for r in decided[b]]
    assert len(domains) == len(set(domains)), "a row appeared in two buckets"


def test_both_agreeing_on_a_primary_source_institution_is_admitted(decided: dict) -> None:
    assert _where(decided, "agree-primary.cz") == ADMITTED


def test_both_agreeing_it_is_NOT_a_primary_source_is_deferred_not_admitted(
    decided: dict,
) -> None:
    """THE DEFECT, pinned. `official_sources.yml` is a list of primary sources: admitting a row
    both judges called not-primary would assert the opposite of what both said. And rejecting
    it would decide the very axis Q1110 = a defers while it is rewritten as an observable."""
    assert _where(decided, "agree-not-primary.fr") == DEFERRED
    row = next(r for r in decided[DEFERRED] if r["domain"] == "agree-not-primary.fr")
    assert row["reason"] == REASON_NOT_PRIMARY
    assert "Q1110" in REASON_NOT_PRIMARY, "the reason must name the ruling it rests on"


@pytest.mark.parametrize(
    ("domain", "reason"),
    [("kind-clash.de", REASON_KIND), ("primary-clash.it", REASON_PRIMARY),
     ("lonely.no", REASON_ONE_JUDGE)],
)
def test_the_contested_band_and_the_unpaired_rows_are_deferred(
    decided: dict, domain, reason
) -> None:
    assert _where(decided, domain) == DEFERRED
    assert next(r for r in decided[DEFERRED] if r["domain"] == domain)["reason"] == reason


def test_a_flagged_namespace_is_blocked_EVEN_WHERE_BOTH_JUDGES_AGREE(decided: dict) -> None:
    """The order is the design. The judges were reading the CLAIMED identity, which is exactly
    the thing the flag says the fetched content contradicts — so their agreement cannot clear
    it, and a block reachable only for rows nobody agreed about would be decorative."""
    assert _where(decided, "flagged.gob.ve") == BLOCKED
    row = next(r for r in decided[BLOCKED] if r["domain"] == "flagged.gob.ve")
    assert row["reason"] == REASON_RESTRICTED
    assert row["integrity_tier"] == "restricted_namespace"


def test_a_written_override_is_the_only_thing_that_lifts_a_block() -> None:
    """Q1112's 'never a silent drop' cuts both ways: the block is visible in the report, and
    lifting it is visible in the inputs."""
    rows = [_j("flagged.gob.ve")]
    tiers = {"flagged.gob.ve": "restricted_namespace"}
    blocked = splice(rows, rows, integrity_tiers=tiers)
    assert [r["domain"] for r in blocked[BLOCKED]] == ["flagged.gob.ve"]

    lifted = splice(rows, rows, integrity_tiers=tiers,
                    written_overrides=["flagged.gob.ve"])
    assert lifted[BLOCKED] == []
    assert [r["domain"] for r in lifted[ADMITTED]] == ["flagged.gob.ve"]
    assert lifted[ADMITTED][0]["overridden"] is True, "an override must be visible on the row"
    assert lifted["report"]["restricted_namespace"]["overridden"] == 1


def test_the_blocked_count_never_reads_as_every_flagged_domain(decided: dict) -> None:
    """Anti-capping on the number most likely to be misread. `other.gov.id` is flagged and is
    not in this splice's population, so it is neither blocked here nor cleared here."""
    rn = decided["report"]["restricted_namespace"]
    assert rn["flagged_in_total"] == 2
    assert rn["inside_this_splice"] == 1
    assert rn["blocked_here"] == 1
    assert "not every flagged domain" in rn["note"]


def test_an_unresolved_identifier_is_declined_and_a_resolved_one_is_named(
    decided: dict,
) -> None:
    assert _where(decided, "unnamed.pl") == DECLINED
    assert _where(decided, "named.pt") == ADMITTED
    named = next(r for r in decided[ADMITTED] if r["domain"] == "named.pt")
    assert named["name"] == "Câmara Municipal" and named["renamed_from"] == "Q111"
    # No admitted row may carry an identifier as its name.
    import re
    assert not [r for r in decided[ADMITTED]
                if r.get("name") and re.match(r"^[Qq]\d+$", str(r["name"]))]


def test_agreement_on_a_non_institution_routes_rather_than_rejects(decided: dict) -> None:
    """A journal is not a rejected institution, it is a different catalogue's row."""
    assert _where(decided, "a-journal.se") == ROUTED
    assert decided["report"]["routed_by_kind"] == {"academic": 1}


def test_there_is_no_reject_verdict_anywhere() -> None:
    """The robots ruling's principle, as a structural check: a non-answer is not a no, and
    this module must not grow a bucket that turns one into one."""
    from pathlib import Path

    src = Path("src/catalog/stage_b_splice.py").read_text(encoding="utf-8")
    assert 'REJECTED = "' not in src and 'REJECT = "' not in src
    assert "deliberately no `reject`" in src


def test_the_three_agreement_statistics_have_three_denominators(decided: dict) -> None:
    """The combined figure is necessarily the lowest; reading it against the two-judge run's
    own numbers would manufacture a discrepancy out of a definition, so all three are
    published with what each is over."""
    rep = decided["report"]
    assert rep["kind_agreement_pct"] >= rep["agreement_pct"]
    assert rep["both_called_institution"] <= rep["paired_rows"]
    assert "different denominator" in rep["agreement_note"] or "own denominator" in rep[
        "agreement_note"
    ]


@pytest.mark.parametrize(
    ("url", "tag"),
    [
        ("https://obec.cz/uredni-deska?action=atom", "cms:uredni-deska-atom"),
        ("https://another.cz/uredni-deska/", "cms:uredni-deska-atom"),
        ("https://third.cz/uredni-deska/rss.xml", "cms:uredni-deska-atom"),
        ("https://obec.cz/feed/", None),
        ("https://uredni-deska.cz/feed", None),   # the HOST is not the signal
        (None, None),
    ],
)
def test_the_vendor_tag_matches_the_path_not_the_host(url, tag) -> None:
    """Distinct hosts share one product, so the host is exactly the wrong key."""
    assert vendor_path_tag(url) == tag


def test_the_admitted_czech_row_carries_its_vendor_tag(decided: dict) -> None:
    """Q1117 = a: admitted, and tagged so a supplier outage is ONE visible cause rather than
    dozens of sources going quiet at once for no stated reason."""
    row = next(r for r in decided[ADMITTED] if r["domain"] == "agree-primary.cz")
    assert row["vendor_tag"] == "cms:uredni-deska-atom"
    assert decided["report"]["vendor_tagged"] == 1


def test_the_balance_shift_names_its_largest_mover_in_percentage_points() -> None:
    """The concentration is disclosed to be SEEN, not corrected — so the number has to be
    there before the splice is applied rather than noticed in a country chart months later."""
    before = {"us": 200, "cz": 10, "fr": 90}
    admitted = [{"country": "cz"} for _ in range(100)]
    shift = balance_shift(before, admitted)
    assert shift["before_total"] == 300 and shift["added_total"] == 100
    top = shift["largest_movers"][0]
    assert top["country"] == "cz"
    assert top["shift_pp"] > 0 and top["added"] == 100
    # The others move DOWN in share without losing a row, which is what a share is.
    us = next(r for r in shift["largest_movers"] if r["country"] == "us")
    assert us["added"] == 0 and us["after"] == 200 and us["shift_pp"] < 0
    assert "not a defect" in shift["caveat"]


def test_an_empty_splice_reports_nothing_rather_than_dividing_by_zero() -> None:
    out = splice([], [])
    assert all(out[b] == [] for b in BUCKETS)
    assert out["report"]["agreement_pct"] is None
    assert out["report"]["contested_band_pct"] is None
