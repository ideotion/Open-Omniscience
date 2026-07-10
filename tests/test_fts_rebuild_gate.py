"""The P0.4 unlock-at-scale fix: ``ensure_fts`` rebuilds the index ONLY when needed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

``ensure_fts`` runs from ``init_db`` on EVERY unlock. It used to unconditionally run the
external-content FTS5 ``'rebuild'`` — a full re-read of every article's title+content
through the SQLCipher codec — which is corpus-scaled and RECURRED on every boot (the
measured 981 s → 1,645 s field unlock at 130 GB). The index is maintained incrementally by
the sync triggers, so a steady-state boot must SKIP the rebuild. These tests pin exactly
that: which decision is made, that a skip really does not run the rebuild SQL, and that
search stays correct across a skipped boot (the triggers are trusted, correctly).
"""

from __future__ import annotations

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database.fts import ensure_fts, search_ids
from src.database.models import Article, Base, Source


def _engine():
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )


def _schema(eng):
    Base.metadata.create_all(eng)


def _seed(eng, n, *, start=0):
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        if s.get(Source, 1) is None:
            s.add(Source(name="S", domain="x.test"))
            s.commit()
        for i in range(start, start + n):
            s.add(
                Article(
                    url=f"u{i}",
                    canonical_url=f"u{i}",
                    source_id=1,
                    title=f"Story {i}",
                    content=f"election inflation economy report number {i}",
                    hash=f"h{i}",
                    language="en",
                )
            )
        s.commit()


class _SqlSpy:
    """Capture every statement executed on an engine (to prove a rebuild did/did not run)."""

    def __init__(self, eng):
        self.stmts: list[str] = []
        event.listen(eng, "before_cursor_execute", self._rec)

    def _rec(self, conn, cursor, statement, parameters, context, executemany):
        self.stmts.append(statement)

    @property
    def rebuilt(self) -> bool:
        return any("'rebuild'" in s for s in self.stmts)


# --------------------------------------------------------------------------- #
# The decision table                                                          #
# --------------------------------------------------------------------------- #


def test_fresh_table_with_existing_articles_rebuilds_once():
    """Schema-upgrade path: articles already present, FTS created here -> populate once."""
    eng = _engine()
    _schema(eng)
    _seed(eng, 5)  # articles inserted with NO FTS table -> triggers never saw them
    spy = _SqlSpy(eng)
    assert ensure_fts(eng) == "rebuilt"
    assert spy.rebuilt is True
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        assert len(search_ids(s, "inflation") or []) == 5  # the one-time rebuild indexed them


def test_steady_state_boot_skips_the_rebuild():
    """THE FIX. A second ensure_fts on a present+populated index must NOT run 'rebuild'."""
    eng = _engine()
    _schema(eng)
    ensure_fts(eng)  # create the table+triggers first
    _seed(eng, 5)  # triggers populate the index incrementally
    spy = _SqlSpy(eng)
    assert ensure_fts(eng) == "skipped"  # the recurring per-boot call
    assert spy.rebuilt is False  # the corpus-scaled codec rebuild did NOT run
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        assert len(search_ids(s, "inflation") or []) == 5  # search still exact


def test_search_stays_correct_across_a_skipped_boot():
    """After a skipped boot, an article inserted via triggers is searchable — the
    trigger-maintained index is trusted, correctly (the whole basis of skipping)."""
    eng = _engine()
    _schema(eng)
    ensure_fts(eng)
    _seed(eng, 3)
    assert ensure_fts(eng) == "skipped"  # steady-state boot
    _seed(eng, 2, start=100)  # new ingest AFTER the skipped boot, via the AI trigger
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        assert len(search_ids(s, "inflation") or []) == 5  # old 3 + new 2 all searchable


def test_present_but_empty_index_with_articles_self_heals():
    """An interrupted past rebuild leaves the table present but its index EMPTY while
    articles exist. auto must rebuild to repair it (never leave search silently broken).
    The index-population probe is the docsize shadow table, since ``SELECT ... FROM
    article_fts`` reads the content table on an external-content index."""
    eng = _engine()
    _schema(eng)
    ensure_fts(eng)  # create table+triggers
    _seed(eng, 4)  # triggers index them
    with eng.begin() as c:  # now empty the INDEX only, leaving the articles present
        c.execute(text("INSERT INTO article_fts(article_fts) VALUES ('delete-all')"))
    spy = _SqlSpy(eng)
    assert ensure_fts(eng) == "rebuilt"  # present-but-empty-with-articles -> repair
    assert spy.rebuilt is True
    Session = sessionmaker(bind=eng, future=True)
    with Session() as s:
        assert len(search_ids(s, "inflation") or []) == 4


def test_empty_store_fresh_table_skips_nothing_expensive():
    """Fresh install: no articles yet. auto 'rebuilds' but over an empty base = a no-op;
    a subsequent boot skips. Neither touches article content."""
    eng = _engine()
    _schema(eng)
    assert ensure_fts(eng) == "rebuilt"  # freshly created (empty rebuild = no-op)
    assert ensure_fts(eng) == "skipped"  # steady state, still empty


# --------------------------------------------------------------------------- #
# Explicit modes + guards                                                     #
# --------------------------------------------------------------------------- #


def test_always_forces_rebuild_and_never_forbids_it():
    eng = _engine()
    _schema(eng)
    ensure_fts(eng)
    _seed(eng, 3)
    spy = _SqlSpy(eng)
    assert ensure_fts(eng, rebuild="always") == "rebuilt"
    assert spy.rebuilt is True

    eng2 = _engine()
    _schema(eng2)
    _seed(eng2, 3)  # articles present, no FTS yet
    spy2 = _SqlSpy(eng2)
    assert ensure_fts(eng2, rebuild="never") == "skipped"  # DDL only, never a rebuild
    assert spy2.rebuilt is False


def test_invalid_rebuild_mode_raises():
    eng = _engine()
    _schema(eng)
    try:
        ensure_fts(eng, rebuild="sometimes")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for an unknown rebuild mode")


def test_non_sqlite_engine_is_a_noop():
    class _FakeDialect:
        name = "postgresql"

    class _FakeEngine:
        dialect = _FakeDialect()

    assert ensure_fts(_FakeEngine()) == "skipped-non-sqlite"  # type: ignore[arg-type]
