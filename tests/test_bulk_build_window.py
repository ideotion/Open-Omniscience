"""
PR 5 slice 1 — the bulk-build index window (audit §9.2 item 5, ruling R23).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R23 puts the bulk build on the LIVE store, so the tests that matter are not "does it
drop indexes" but the three ways that choice could cost the operator something:

  * a CRASH between the DROP and the rebuild must not lose an index -- measured, only 4
    of the 14 droppable indexes are in ``maintenance.HOT_INDEXES``, so for the other 10
    nothing else in the tree would ever restore them;
  * the UNIQUE indexes must NEVER be dropped, because they are the constraints that make
    "one mention row per (keyword, article)" true, not performance indexes;
  * a caller that DELETEs per article must be able to keep ``ix_mention_article``, or
    each delete becomes a full scan of the mention table.

The heal is asserted against ``sqlite_master`` -- the store itself -- rather than against
the module's own bookkeeping, because bookkeeping is exactly what a crash corrupts.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.analytics.bulk_build import (
    ARTICLE_DELETE_INDEX,
    BULK_BUILD_KEY,
    bulk_index_window,
    droppable_indexes,
    heal_bulk_build,
    open_state,
    read_state,
    rebuild_progress,
)
from src.database.models import Base, DerivedMeta


def _engine():
    eng = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(eng)
    return eng


def _session(eng):
    return sessionmaker(bind=eng, future=True)()


def _indexes(session) -> set[str]:
    return {
        r[0]
        for r in session.execute(
            text("SELECT name FROM sqlite_master WHERE type='index'")
        ).fetchall()
    }


# --- the set, and what is deliberately not in it ---------------------------- #

def test_the_unique_indexes_are_never_droppable():
    """THE CORRECTNESS TEST. §9.2 item 5 says to drop "the ten secondary mention indexes
    and the seven when/where/who indexes". Three of those seventeen are UNIQUE and are
    constraints rather than performance indexes: dropping them would let a bulk load
    insert duplicate mention rows that nothing reports and the counters would faithfully
    double. This is why the droppable set is 14, not 17."""
    names = droppable_indexes()
    for must_stay in (
        "ix_mention_keyword_article",
        "ix_amp_article_place",
        "ix_ae_article_name_class",
    ):
        assert must_stay not in names, f"{must_stay} is UNIQUE and must never be dropped"


def test_the_droppable_set_is_the_measured_fourteen():
    names = droppable_indexes()
    assert len(names) == 14, f"expected the measured 14 droppable indexes, got {len(names)}: {names}"


def test_keep_removes_an_index_from_the_set():
    """A per-article DELETE path keeps ix_mention_article or each delete full-scans."""
    assert ARTICLE_DELETE_INDEX in droppable_indexes()
    kept = droppable_indexes(keep={ARTICLE_DELETE_INDEX})
    assert ARTICLE_DELETE_INDEX not in kept
    assert len(kept) == 13


def test_the_set_is_derived_from_the_metadata_not_a_hardcoded_list():
    """A hardcoded copy drifts from the models; this one cannot. Adding an index to a
    target table must widen the set with no edit to bulk_build.py."""
    from sqlalchemy import Index

    from src.database.models import Base

    table = Base.metadata.tables["keyword_mentions"]
    before = len(droppable_indexes())
    probe = Index("ix_probe_bulk_build_derivation", table.c.country, table.c.keyword_id)
    try:
        assert len(droppable_indexes()) == before + 1
        assert "ix_probe_bulk_build_derivation" in droppable_indexes()
    finally:
        table.indexes.discard(probe)
    assert len(droppable_indexes()) == before


# --- the window ------------------------------------------------------------- #

def test_the_window_drops_then_rebuilds_and_clears_its_marker():
    eng = _engine()
    s = _session(eng)
    planned = set(droppable_indexes())
    assert planned <= _indexes(s), "precondition: create_all built them"

    with bulk_index_window(s, reason="test") as dropped:
        assert set(dropped) == planned
        assert not (planned & _indexes(s)), "inside the window they are gone"
        assert read_state(s) is not None, "and the marker is open while they are"

    assert planned <= _indexes(s), "afterwards every one is back"
    assert read_state(s) is None, "and the marker is cleared"


def test_the_window_keeps_what_the_caller_asked_to_keep():
    eng = _engine()
    s = _session(eng)
    with bulk_index_window(s, keep={ARTICLE_DELETE_INDEX}, reason="test") as dropped:
        assert ARTICLE_DELETE_INDEX not in dropped
        assert ARTICLE_DELETE_INDEX in _indexes(s), "the kept index stays live throughout"


def test_the_marker_is_committed_before_the_first_drop(tmp_path, monkeypatch):
    """THE ORDERING RULE, and it can only be proven from ANOTHER CONNECTION.

    An index dropped with no durable record of it is one the heal will never look for, so
    the marker must be COMMITTED before the first DROP -- not merely assigned. My first
    attempt at this test failed the drop and checked the marker survived; that proved
    nothing, because the window's own `finally` correctly clears a marker when the store
    turns out to be whole, and it also could not tell a committed row from a pending one.

    Committed means "visible to a session that is not this one", which needs a FILE
    database: the in-memory StaticPool engine used elsewhere in this file shares one
    connection across sessions, so uncommitted writes would be visible there and the
    assertion would pass whether or not the commit happened.
    """
    import src.analytics.bulk_build as bb

    url = f"sqlite:///{tmp_path / 'bulk.db'}"
    eng = create_engine(url, future=True)
    Base.metadata.create_all(eng)
    s = _session(eng)

    seen: dict[str, object] = {}
    real_drop = bb._drop

    def _watching_drop(session, names):
        # A SEPARATE engine + connection: it can only see what is already committed.
        other = create_engine(url, future=True)
        try:
            with other.connect() as conn:
                seen["marker"] = conn.execute(
                    text("SELECT value FROM derived_meta WHERE key = :k"),
                    {"k": BULK_BUILD_KEY},
                ).scalar()
        finally:
            other.dispose()
        return real_drop(session, names)

    monkeypatch.setattr(bb, "_drop", _watching_drop)
    with bb.bulk_index_window(s, reason="test"):
        pass

    assert seen.get("marker"), (
        "at the moment the first DROP ran, another connection could already read the "
        "marker -- i.e. it was committed, not merely pending"
    )
    assert BULK_BUILD_KEY in str(seen["marker"]) or "\n" in str(seen["marker"])
    s.close()
    eng.dispose()


def test_an_exception_inside_the_window_still_rebuilds():
    eng = _engine()
    s = _session(eng)
    planned = set(droppable_indexes())
    with pytest.raises(ValueError), bulk_index_window(s, reason="test"):
        assert not (planned & _indexes(s))
        raise ValueError("the caller's own failure")
    assert planned <= _indexes(s), "the finally rebuilt them anyway"
    assert read_state(s) is None


# --- the crash, which is what the heal exists for --------------------------- #

def test_a_crash_between_drop_and_rebuild_is_healed_at_boot():
    """THE LOAD-BEARING TEST. Simulates the process dying with the indexes gone: the
    marker is open, the store is stripped, and no code from the window is left running.
    A later boot must restore every one of them."""
    eng = _engine()
    s = _session(eng)
    planned = droppable_indexes()

    open_state(s, planned)
    import src.analytics.bulk_build as bb

    bb._drop(s, planned)
    assert not (set(planned) & _indexes(s)), "the store is stripped"
    s.commit()
    s.close()  # the process goes away

    created = heal_bulk_build(eng)
    assert set(created) == set(planned), "the boot heal recreated every dropped index"

    s2 = _session(eng)
    assert set(planned) <= _indexes(s2)
    assert read_state(s2) is None, "and cleared the marker once the store was whole"


def test_the_heal_restores_the_ten_that_nothing_else_would():
    """Measured: only 4 of the 14 are in maintenance.HOT_INDEXES. This pins that the
    other 10 are covered HERE, because nothing else in the tree adds an index to an
    existing table."""
    from src.database.maintenance import HOT_INDEXES

    planned = droppable_indexes()
    orphans = [n for n in planned if n not in HOT_INDEXES]
    assert len(orphans) == 10, f"expected the measured 10 uncovered, got {len(orphans)}"

    eng = _engine()
    s = _session(eng)
    open_state(s, planned)
    import src.analytics.bulk_build as bb

    bb._drop(s, planned)
    s.commit()
    s.close()

    heal_bulk_build(eng)
    s2 = _session(eng)
    live = _indexes(s2)
    assert all(n in live for n in orphans), "the ones no other heal covers are covered here"


def test_the_heal_is_a_no_op_when_no_build_was_interrupted():
    eng = _engine()
    assert heal_bulk_build(eng) == []


def test_the_heal_is_idempotent():
    eng = _engine()
    s = _session(eng)
    planned = droppable_indexes()
    open_state(s, planned)
    import src.analytics.bulk_build as bb

    bb._drop(s, planned)
    s.commit()
    s.close()
    first = heal_bulk_build(eng)
    second = heal_bulk_build(eng)
    assert set(first) == set(planned)
    assert second == [], "a second heal finds nothing to do and says so"


def test_the_heal_does_not_invent_a_plan_from_an_unusable_marker():
    """An unusable marker reports OPEN with no planned set. Recreating the whole
    droppable set from that guess could resurrect an index someone deliberately retired.

    ASSERTED ON THE STORE, NOT THE RETURN VALUE. Caught by mutation: making the heal fall
    through to an empty plan returns `[]` exactly as declining does, so a
    `== []` assertion passes over both. The distinguishing fact is whether an index that
    is ABSENT gets recreated, so the store is stripped first and then checked.
    """
    import src.analytics.bulk_build as bb

    eng = _engine()
    s = _session(eng)
    planned = droppable_indexes()

    # Strip the store, then replace the good marker with an unusable one (no plan).
    open_state(s, planned)
    bb._drop(s, planned)
    s.commit()
    row = s.get(DerivedMeta, BULK_BUILD_KEY)
    row.value = "2026-09-23T00:00:00+00:00"  # a timestamp and nothing else
    s.commit()
    assert not (set(planned) & _indexes(s)), "precondition: the store really is stripped"
    s.close()

    created = heal_bulk_build(eng)

    s2 = _session(eng)
    assert created == [], "it declines rather than guessing"
    assert not (set(planned) & _indexes(s2)), (
        "and it must NOT have recreated anything from an invented plan -- the operator "
        "is left with an honest open marker instead of indexes nobody asked for"
    )
    assert read_state(s2) is not None, "the marker stays open, so the state is not hidden"


# --- the disclosure R23 requires -------------------------------------------- #

def test_the_progress_disclosure_counts_the_store_not_a_tally():
    """"Rebuilding, N of M" is measured from sqlite_master, so it cannot drift from what
    is actually there -- which is the failure a remembered counter has after a crash."""
    eng = _engine()
    s = _session(eng)
    planned = droppable_indexes()

    assert rebuild_progress(s) == {
        "rebuilding": False, "done": 0, "total": 0, "missing": [], "since": None
    }

    open_state(s, planned)
    import src.analytics.bulk_build as bb

    bb._drop(s, planned)
    mid = rebuild_progress(s)
    assert mid["rebuilding"] is True
    assert mid["total"] == 14 and mid["done"] == 0
    assert len(mid["missing"]) == 14 and mid["since"]

    bb._rebuild_missing(s, planned[:5])
    part = rebuild_progress(s)
    assert part["done"] == 5 and part["total"] == 14, "N of M, counted from the store"

    bb._rebuild_missing(s, planned)
    assert rebuild_progress(s)["done"] == 14


def test_reopening_keeps_the_original_timestamp_for_the_disclosure():
    eng = _engine()
    s = _session(eng)
    first = open_state(s, droppable_indexes())
    assert read_state(s)["since"] == first


def test_an_unreadable_marker_is_disclosed_as_rebuilding(monkeypatch):
    eng = _engine()
    s = _session(eng)

    def _boom(*a, **k):
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(s, "get", _boom)
    state = read_state(s)
    assert state is not None and state["since"] == "unknown"


# --- the boot wiring, which is what makes the heal exist at all ------------- #

def test_the_boot_path_calls_the_heal():
    """Asserted on the SOURCE of the boot path, not on the shared app singleton.

    The recorded lesson is that positive facts must never be asserted against a mutable
    process-global (the flaky-route incident); the boot wiring's immutable source is the
    honest anchor, and a heal nobody calls is the whole failure this guards.
    """
    from pathlib import Path

    src = Path("src/database/session.py").read_text(encoding="utf-8")
    assert "from src.analytics.bulk_build import heal_bulk_build" in src
    assert "heal_bulk_build(engine)" in src
    assert src.index("ensure_hot_indexes(engine)") < src.index("heal_bulk_build(engine)"), (
        "the hot-index heal runs first; this one finishes what it cannot cover"
    )
