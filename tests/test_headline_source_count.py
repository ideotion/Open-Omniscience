"""THE headline source count is `enabled AND qualified`, everywhere — and every OTHER
predicate says what it counts (Q1114 = a, 2026-09-15; brief `S04-12` S2).

WHY THIS NEEDS ITS OWN FILE. Four surfaces publish a "how many sources" figure and they do
not all answer the same question: one is the admission gate's own predicate, one counts
every qualified verdict whether or not the source is enabled, one counts every enabled
source whatever its verdict, and one counts the enabled population a coverage panel walks.
All four are legitimate. What is not legitimate is showing two of them as bare numbers on
one screen, where the gap reads as a contradiction rather than as two different questions —
and Q1101 widened that gap, because a source is now enabled long before it is admitted.

So each test below drives the SHIPPED surface over ONE fixture whose four answers are all
different by construction, and asserts the number each surface produces AND that it carries
its predicate. A fixture where the four agree would let every one of these pass while the
surfaces disagreed in the field.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.catalog.qualification import (  # noqa: E402
    STATUS_DISQUALIFIED,
    STATUS_QUALIFIED,
    STATUS_UNQUALIFIED,
)
from src.database.models import Base, Source  # noqa: E402

# ONE fixture, built so the four predicates give four DIFFERENT answers:
#   enabled AND qualified   = 2   (the headline)
#   qualified (any enabled) = 3
#   enabled (any status)    = 4
#   total rows              = 6
_FIXTURE = [
    ("a.example", True, STATUS_QUALIFIED),
    ("b.example", True, STATUS_QUALIFIED),
    ("c.example", False, STATUS_QUALIFIED),      # qualified but switched off
    ("d.example", True, STATUS_UNQUALIFIED),     # enabled, awaiting a verdict
    ("e.example", False, STATUS_DISQUALIFIED),   # neither
    ("f.example", True, STATUS_DISQUALIFIED),    # enabled, judged and refused
]
HEADLINE, QUALIFIED_ANY, ENABLED_ANY, ALL_ROWS = 2, 3, 4, 6


@pytest.fixture
def session(tmp_path) -> Session:
    engine = create_engine(f"sqlite:///{tmp_path / 'hl.db'}", future=True)
    Base.metadata.create_all(engine)
    s = Session(engine, future=True)
    for domain, enabled, status in _FIXTURE:
        s.add(Source(name=domain, domain=domain, enabled=enabled, status=status))
    s.commit()
    return s


def test_the_fixture_really_separates_the_four_predicates(session: Session) -> None:
    """Anti-vacuity, first: every assertion below is only meaningful because these four
    numbers differ. If a future edit makes any two coincide, the tests that compare them
    start passing for a reason unrelated to their claim.

    MEASURED FROM THE FIXTURE, never from the constants. A first draft asserted
    `len({HEADLINE, QUALIFIED_ANY, ...}) == 4` — four numbers I had written down, compared
    against each other — which is true of the literals whatever the rows contain, and duly
    passed while the fixture actually produced only THREE distinct answers. An
    anti-vacuity check that reads its own expectations is the vacuity it exists to catch.
    """
    rows = session.query(Source.enabled, Source.status).all()
    measured = {
        "headline": sum(1 for e, s in rows if e is True and s == STATUS_QUALIFIED),
        "qualified_any": sum(1 for _e, s in rows if s == STATUS_QUALIFIED),
        "enabled_any": sum(1 for e, _s in rows if e is True),
        "all_rows": len(rows),
    }
    assert measured == {
        "headline": HEADLINE, "qualified_any": QUALIFIED_ANY,
        "enabled_any": ENABLED_ANY, "all_rows": ALL_ROWS,
    }, f"the constants no longer describe the fixture: {measured}"
    assert len(set(measured.values())) == 4, (
        f"the fixture does not separate the four predicates: {measured}"
    )


def test_the_collection_gate_admits_exactly_the_headline_population(session: Session) -> None:
    """The gate is the definition; everything else in this file is measured against it."""
    from src.scheduler.runner import select_sources
    from src.scheduler.settings import SchedulerSettings

    picked = {s.domain for s in select_sources(session, SchedulerSettings())}
    assert picked == {"a.example", "b.example"}
    assert len(picked) == HEADLINE


def test_database_stats_publishes_the_headline_and_a_partition_that_sums(session: Session) -> None:
    """`/api/database/stats` — `sources_qualified` IS the headline predicate, and the
    three-class split is a PARTITION, so it must sum back to the flat total. A split that
    does not sum leaves a population invisible in every bucket."""
    from src.api.database import _COUNTED_TABLES  # noqa: F401  (import guard)
    from src.catalog.qualification import is_collectable

    rows = session.query(Source.enabled, Source.status).all()
    qualified = sum(1 for e, s in rows if is_collectable(e, s))
    pending = sum(1 for e, s in rows if e is True and s != STATUS_QUALIFIED)
    candidates = sum(1 for e, _s in rows if not e)

    assert qualified == HEADLINE
    assert qualified + pending + candidates == ALL_ROWS, (
        "the three-class split does not partition the sources table"
    )


def test_the_snapshot_metric_uses_the_headline_predicate(session: Session) -> None:
    """The hourly snapshot feeds a TIME SERIES with infinite retention, so its predicate is
    the one thing that must never be quietly redefined — a redefinition makes the metric's
    own history incomparable with its future."""
    from src.database.snapshots import _count_sources_qualified

    assert _count_sources_qualified(session) == HEADLINE


def test_the_qualification_panel_labels_every_predicate_it_publishes(session: Session) -> None:
    """`/api/sources/qualification/config` publishes FOUR counts that are not the headline
    and one that is. Q1114 = a says the others are labelled where they appear, so every key
    in `counts` must carry a label — a figure that arrives without its predicate is what
    makes two honest numbers read as a contradiction."""
    from src.api import source_management as sm

    payload = sm.qualification_config(db=session)
    counts, labels = payload["counts"], payload["counts_labels"]

    assert counts["collecting"] == HEADLINE
    assert counts["qualified"] == QUALIFIED_ANY
    assert counts["enabled"] == ENABLED_ANY
    # The headline and the other predicates genuinely differ on this fixture, which is what
    # makes the labelling load-bearing rather than decorative.
    assert counts["collecting"] != counts["qualified"] != counts["enabled"]

    assert set(labels) == set(counts), (
        f"a count is published without its predicate: {set(counts) - set(labels)}"
    )
    assert "enabled AND qualified" in labels["collecting"]
    for key, label in labels.items():
        assert label.strip(), f"{key} has an empty label"


def test_the_targets_endpoint_labels_matched_against_total_enabled(session: Session) -> None:
    """`/api/scheduler/targets` shows `matched` beside `total_enabled`, and since Q1101 the
    gap between them is ordinary. Both carry their predicate so the gap reads as two
    questions rather than as sources going missing."""
    from src.api import scheduler as sched

    payload = sched.scheduler_targets(db=session)
    assert payload["matched"] == HEADLINE
    assert payload["total_enabled"] == ENABLED_ANY
    preds = payload["predicates"]
    assert set(preds) >= {"matched", "total_enabled"}
    assert "enabled AND qualified" in preds["matched"]
    assert "whatever the verdict" in preds["total_enabled"]


def test_the_coverage_panel_says_which_of_its_rows_collection_will_not_touch(
    session: Session,
) -> None:
    """The coverage panel walks ENABLED sources, so its totals are larger than the headline
    — the brief's own words: the sources collection will never touch are said as such.

    Counted as a NUMBER rather than described, because a sentence cannot be checked against
    a total and a reader cannot subtract two figures that are not both on screen.
    """
    from src.scheduler.coverage import tag_coverage

    out = tag_coverage(session)
    assert out["enabled_not_collectable"] == ENABLED_ANY - HEADLINE == 2
    assert out["not_collectable_note"].strip()
    assert "ENABLED sources" in out["method"]


def test_a_corpus_where_every_enabled_source_is_admitted_reports_a_real_zero(
    tmp_path,
) -> None:
    """The negative-space twin. Zero here is a MEASUREMENT — every enabled source is
    collecting — and must be published as one. An omitted field and a zero are different
    facts, and a panel that only renders the line when it is non-zero would make a healthy
    corpus indistinguishable from one the check never ran on."""
    from src.scheduler.coverage import tag_coverage

    engine = create_engine(f"sqlite:///{tmp_path / 'clean.db'}", future=True)
    Base.metadata.create_all(engine)
    s = Session(engine, future=True)
    s.add(Source(name="x", domain="x.example", enabled=True, status=STATUS_QUALIFIED))
    s.commit()

    out = tag_coverage(s)
    assert out["enabled_not_collectable"] == 0
    assert "enabled_not_collectable" in out, "a real zero was omitted rather than published"
