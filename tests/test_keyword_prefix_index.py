"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

The omnibar's keyword group runs a PREFIX match per debounced keystroke. SQLite's
LIKE optimization -- the rewrite that turns ``x LIKE 'abc%'`` into a range scan --
only fires when the indexed column uses NOCASE collation (whenever
``case_sensitive_like`` is off, which is the default). The pre-existing
``idx_keyword_normalized_term`` is BINARY, so the optimization could never fire and
the query read EVERY key: measured 125.5 ms (count) and 131.3 ms (top-3, a BARE
table scan plus a temp B-tree) on a 2,000,000-row fixture, against 0.02 ms / 0.20 ms
with the NOCASE index present. The field corpus carries ~5M keywords.

These tests assert the PLAN of the statements the PRODUCTION path actually emits --
captured with a ``before_cursor_execute`` listener rather than hand-written here,
because a hand-written lookalike differs from the shipped query in ways that move
the planner (this repo has been burned by exactly that).
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

pytest.importorskip("sqlalchemy")

NOCASE_INDEX = (
    "CREATE INDEX IF NOT EXISTS idx_keyword_normterm_nocase "
    "ON keywords (normalized_term COLLATE NOCASE)"
)


def _production_keyword_statements(db_path: str) -> list[tuple[str, dict]]:
    """Drive the REAL ``_keywords_group`` query shapes and capture what they emit."""
    from src.database.models import Base, Keyword

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    captured: list[tuple[str, dict]] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _cap(conn, cursor, statement, parameters, context, executemany):  # noqa: ANN001
        if "keywords" in statement and "normalized_term" in statement:
            captured.append((statement, parameters))

    with Session(engine) as s:
        # Byte-for-byte the two queries src/api/search_omni.py:_keywords_group runs.
        pat = "abc%"
        base = s.query(Keyword).filter(Keyword.normalized_term.like(pat, escape="\\"))
        base.count()
        base.order_by(
            Keyword.frequency.desc().nullslast(), Keyword.normalized_term
        ).limit(3).all()

    # Dispose BEFORE anyone EXPLAINs: pysqlite caches compiled statements per
    # connection and the pool hands the same one back, so a plan taken through this
    # engine could report an index that no longer exists. The raw connection below
    # shares no cache with it.
    engine.dispose()
    return captured


def _plans(db_path: str, statements: list[tuple[str, dict]]) -> list[list[str]]:
    raw = sqlite3.connect(db_path)
    try:
        return [
            [r[-1] for r in raw.execute("EXPLAIN QUERY PLAN " + stmt, params)]
            for stmt, params in statements
        ]
    finally:
        raw.close()


def test_the_shipped_prefix_queries_become_range_searches_with_the_nocase_index(tmp_path):
    """The positive half: both production statements use the index as a RANGE scan."""
    db = str(tmp_path / "kw.db")
    stmts = _production_keyword_statements(db)
    assert len(stmts) == 2, stmts

    raw = sqlite3.connect(db)
    raw.execute(NOCASE_INDEX)
    raw.commit()
    raw.close()

    for plan in _plans(db, stmts):
        joined = " ".join(plan)
        assert "idx_keyword_normterm_nocase" in joined, plan
        # A range SEARCH, not a SCAN. Note the repo's own recorded rule: SQLite says
        # "SCAN" for BOTH a bare table scan and an index-only scan, so the meaningful
        # assertion is the SEARCH form with its range bounds -- that is the LIKE
        # optimization firing, which is the whole point of the NOCASE collation.
        assert "SEARCH" in joined, plan
        assert "normalized_term>?" in joined, plan


def test_without_the_nocase_index_the_same_queries_fall_back_to_scans(tmp_path):
    """The negative half, and the one that makes the positive half mean anything.

    Neutering the fix must change the plan. Without it this file would pass just as
    happily against a build that never gained the index -- the shape this repo's
    2026-08-04 sweep found 41 times.
    """
    db = str(tmp_path / "kw_noidx.db")
    stmts = _production_keyword_statements(db)

    plans = _plans(db, stmts)  # NOCASE index deliberately never created
    for plan in plans:
        joined = " ".join(plan)
        assert "idx_keyword_normterm_nocase" not in joined, plan
        # The PROPERTY, not an incidental plan shape: without NOCASE the LIKE
        # optimization cannot fire, so nothing bounds the traversal by a term range.
        # Which full traversal the planner picks instead (a bare table scan, or a
        # full scan of some other index) depends on table statistics and on the exact
        # ORDER BY form -- measured both ways while writing this -- so asserting one
        # of them would pin an accident rather than the thing the fix changes.
        assert "normalized_term>?" not in joined, plan


def test_the_index_is_proposed_but_deliberately_not_wired_yet(tmp_path):
    """This index is CHARACTERISED here and NOT shipped -- the file says why.

    Wiring it into the boot self-heal alone flips ``alembic_stamp_align``'s verdict to
    "schema-behind", because every entry in that dict is mirrored on its model and an
    index the live DB has but the model does not declare reads as drift. Mirroring it
    does not resolve it either: ``COLLATE NOCASE`` makes it an EXPRESSION index, which
    alembic's autogenerate cannot compare ("should either skip expression indexes or
    provide a custom implementation") and then reports as permanently changed. That
    needs a migrations-layer decision, which is another lane's territory this wave.

    So this asserts the CURRENT state rather than the desired one -- an honest pin, and
    one that fails the moment somebody wires it, which is exactly when this note and
    the tests above need re-reading rather than deleting.
    """
    from src.database.maintenance import HOT_INDEXES

    assert "idx_keyword_normterm_nocase" not in HOT_INDEXES, (
        "the NOCASE index is now wired -- re-read the block above it in maintenance.py: "
        "it needs a model mirror AND a decision about alembic and expression indexes, "
        "and this test should become the registration assertion it used to be"
    )
    # The measurement that justifies it is not lost: the two tests above prove the plan
    # changes, against the statements the production path really emits.
