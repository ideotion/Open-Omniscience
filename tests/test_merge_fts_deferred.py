"""The merge builds the search index ONCE, instead of per article via the trigger.

WHY, from the operator's own field beat (imp-20260807T033245Z, a ~1.4M-article
corpus): 1,198 of 1,223 beats in a five-hour merging phase carried FTS5's internal
segment-merge delete in flight -- 98% of the wall clock, single-threaded, while
memory sat comfortable at 1.1-1.5 GB. ``article_fts_ai`` fires per inserted
article and fts.py sets no automerge value, so FTS5 merges b-tree segments
continuously as hundreds of thousands of articles land in an index already holding
hundreds of thousands more.

Measured, on a cache-constrained fixture so the index cannot sit in RAM (which is
the regime an earlier probe missed, and why FTS was wrongly recorded as refuted):

    trigger-live (before)                38.11s insert   -> 1.00x
    drop trigger + 'rebuild' after        3.19s + 54.57s -> 0.66x   WORSE
    drop trigger + index only new rows    1.61s + 26.41s -> 1.36x   this

So the article insert itself is 23.7x faster and the total is 1.36x faster, for an
identical index. These tests are about the IDENTICAL part -- speed is measured, not
asserted, because a timing assertion on shared CI is a flake generator.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backup import merge as merge_mod
from src.backup.merge import merge_corpus, verify_copy
from src.database.fts import _FTS_DDL
from src.database.models import Article, Base, Source

_BATCH_META = {
    "artifact_kind": "oo-backup-2",
    "origin_fingerprint": "test",
    "app_version": "0.3.0",
    "alembic_rev": "head",
    "manifest": None,
}


def _corpus(path: Path, *, articles: int, first: int = 0, fts: bool = True) -> None:
    """A corpus with the real FTS table + triggers, populated THROUGH them."""
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    engine.dispose()
    con = sqlite3.connect(path, isolation_level=None)
    if fts:
        for ddl in _FTS_DDL:
            con.execute(ddl)
    con.close()

    engine = create_engine(f"sqlite:///{path}", future=True)
    now = datetime.now(UTC)
    with sessionmaker(bind=engine, future=True)() as s:
        src = Source(name="Wire", domain="wire.example")
        s.add(src)
        s.flush()
        for i in range(first, first + articles):
            s.add(Article(
                url=f"https://wire.example/{i}", canonical_url=f"https://wire.example/{i}",
                source_id=src.id, title=f"headline {i}",
                content=f"the quick brown fox jumps over article {i} zebra",
                hash=f"h{i:08d}", language="en", created_at=now,
            ))
        s.commit()
    engine.dispose()


def _fts_state(path: Path) -> dict:
    con = sqlite3.connect(path)
    try:
        return {
            "articles": con.execute("SELECT COUNT(*) FROM articles").fetchone()[0],
            "indexed": con.execute("SELECT COUNT(*) FROM article_fts_docsize").fetchone()[0],
            "trigger": bool(con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='article_fts_ai'"
            ).fetchone()),
            "hits_zebra": con.execute(
                "SELECT COUNT(*) FROM article_fts WHERE article_fts MATCH 'zebra'"
            ).fetchone()[0],
        }
    finally:
        con.close()


# --------------------------------------------------------------------------- #
#  the index is complete and the trigger comes back
# --------------------------------------------------------------------------- #
def test_a_merge_indexes_every_article_it_added(tmp_path) -> None:
    """The whole point: the index must be complete afterwards, not deferred.

    verify_copy gates the swap on the index covering every article, so a merge
    that indexed nothing would abort the restore rather than ship a gap -- but
    this asserts the index is RIGHT, not merely that the gate is satisfied.
    """
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=5)
    _corpus(staged, articles=40, first=1000)

    merge_corpus(staged, working, _BATCH_META)

    st = _fts_state(working)
    assert st["articles"] == 45
    assert st["indexed"] == 45, "the search index does not cover every article"
    assert st["hits_zebra"] == 45, "merged articles are not FINDABLE, only counted"
    assert st["trigger"], "the FTS insert trigger was not restored"


def test_the_deferred_build_matches_what_the_trigger_would_have_produced(tmp_path) -> None:
    """THE equivalence check, and the one that would catch a subtly wrong index.

    Merge the same staged corpus twice: once through the new deferred path, once
    with the suspend neutered so the trigger fires per row exactly as before. The
    resulting indexes must agree -- not just in document count (which a broken
    tokenizer setting would still satisfy) but in what they actually MATCH.
    """
    staged = tmp_path / "s.db"
    _corpus(staged, articles=60, first=5000)

    deferred, live = tmp_path / "a.db", tmp_path / "b.db"
    for p in (deferred, live):
        _corpus(p, articles=4)

    merge_corpus(staged, deferred, _BATCH_META)

    # neuter the suspend -> the trigger stays live, i.e. the pre-B6 behaviour
    from contextlib import contextmanager

    @contextmanager
    def _no_suspend(con):
        yield False

    orig = merge_mod._fts_insert_suspended
    merge_mod._fts_insert_suspended = _no_suspend
    try:
        merge_corpus(staged, live, _BATCH_META)
    finally:
        merge_mod._fts_insert_suspended = orig

    a, b = _fts_state(deferred), _fts_state(live)
    assert a["articles"] == b["articles"] == 64
    assert a["indexed"] == b["indexed"] == 64
    assert a["hits_zebra"] == b["hits_zebra"] == 64

    # term-level agreement, not just totals
    def terms(path: Path) -> set:
        con = sqlite3.connect(path)
        try:
            return {
                (r[0], r[1]) for r in con.execute(
                    "SELECT rowid, title FROM article_fts WHERE article_fts MATCH 'headline'"
                )
            }
        finally:
            con.close()

    assert terms(deferred) == terms(live), (
        "the deferred index matches different rows than the trigger-built one"
    )


# --------------------------------------------------------------------------- #
#  the restore paths that must not lose the trigger
# --------------------------------------------------------------------------- #
def test_the_suspend_restores_the_trigger_when_the_body_raises() -> None:
    """The context manager's OWN contract, driven where only the finally can hold.

    THIS TEST EXISTS BECAUSE ITS FIRST VERSION WAS VACUOUS. Driven through
    ``merge_corpus``, removing the ``finally`` changed nothing and the guard still
    passed -- because SQLite's DDL is TRANSACTIONAL, so the merge's own ROLLBACK
    undoes the DROP TRIGGER by itself (verified directly: present=False mid
    transaction, present=True after the rollback). The merge-level test was
    therefore proving the rollback, not the finally.

    So the finally is redundant on the ABORT path and load-bearing on the SUCCESS
    path, where nothing rolls back. Exercised here outside a transaction, which is
    the only arrangement where the finally is the sole thing that can restore it --
    and removing the finally does fail this one.
    """
    con = sqlite3.connect(":memory:", isolation_level=None)
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT, content TEXT)")
    for ddl in _FTS_DDL:
        con.execute(ddl)

    def present() -> bool:
        return bool(con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='article_fts_ai'"
        ).fetchone())

    assert present()
    with pytest.raises(RuntimeError, match="boom"):
        with merge_mod._fts_insert_suspended(con) as suspended:
            assert suspended is True
            assert not present(), "the trigger was not actually suspended"
            raise RuntimeError("boom")
    assert present(), "the finally did not restore the FTS insert trigger"


def test_a_failed_merge_leaves_the_working_copy_able_to_index(tmp_path) -> None:
    """The property that matters at the merge level, claimed at its real strength.

    Restored here by SQLite's transactional DDL (the rollback) rather than by the
    finally -- see the test above. Kept because the PROPERTY is what protects the
    corpus, and it should hold however it is achieved; named for what it proves so
    nobody reads it as evidence about the finally.
    """
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=3)
    _corpus(staged, articles=10, first=2000)

    def boom(con, batch_id, results):
        raise RuntimeError("step exploded")

    steps = merge_mod._merge_steps()
    patched = tuple((n, boom if n == "keywords" else f) for n, f in steps)
    orig = merge_mod._merge_steps
    merge_mod._merge_steps = lambda: patched
    try:
        with pytest.raises(Exception, match="step exploded"):
            merge_corpus(staged, working, _BATCH_META)
    finally:
        merge_mod._merge_steps = orig

    assert _fts_state(working)["trigger"], (
        "a failed merge left the working copy without its FTS insert trigger"
    )


def test_verify_refuses_a_copy_whose_fts_trigger_is_missing(tmp_path) -> None:
    """The net beneath the finally.

    A copy missing the trigger is not visibly broken -- its index is complete at
    that instant, so the coverage check passes. What is broken is the FUTURE: it
    would silently stop indexing new articles. So this must be its own check, and
    it must block the swap.
    """
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=4)
    _corpus(staged, articles=8, first=3000)
    counts, batch_id = merge_corpus(staged, working, _BATCH_META)

    good = verify_copy(working, staged, batch_id)
    assert good["fts_trigger_present"] is True
    assert good["ok"] is True, f"a healthy copy failed verification: {good}"

    con = sqlite3.connect(working, isolation_level=None)
    con.execute("DROP TRIGGER article_fts_ai")
    con.close()

    bad = verify_copy(working, staged, batch_id)
    assert bad["fts_trigger_present"] is False
    assert bad["ok"] is False, "a copy that would stop indexing passed verification"
    # and the coverage check is NOT what caught it -- the index is still complete,
    # which is exactly why this needed its own check
    assert bad["fts_matches_articles"] is True


def test_automerge_is_restored_after_the_bulk_load(tmp_path) -> None:
    """Leaving automerge at 0 would silently degrade every later ingest."""
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=3)
    _corpus(staged, articles=12, first=4000)
    merge_corpus(staged, working, _BATCH_META)

    con = sqlite3.connect(working)
    try:
        val = con.execute(
            "SELECT v FROM article_fts_config WHERE k='automerge'"
        ).fetchone()
    finally:
        con.close()
    # FTS5 stores the default implicitly (no row) and a set value explicitly.
    assert val is None or int(val[0]) == 4, f"automerge left at {val}"


# --------------------------------------------------------------------------- #
#  a corpus with no FTS at all
# --------------------------------------------------------------------------- #
def test_a_corpus_without_fts_is_left_alone(tmp_path) -> None:
    """Never fabricate a trigger we did not find.

    Creating one here would add indexing to a corpus that deliberately had none,
    which is a behaviour change smuggled in under a performance fix.
    """
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=3, fts=False)
    _corpus(staged, articles=9, first=6000, fts=False)

    merge_corpus(staged, working, _BATCH_META)

    con = sqlite3.connect(working)
    try:
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 12
        assert con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE name LIKE 'article_fts%'"
        ).fetchone()[0] == 0, "the merge created an FTS index on a corpus that had none"
    finally:
        con.close()


def test_the_bulk_load_indexes_exactly_the_merged_rows(tmp_path) -> None:
    """It reads merged_rows, not a watermark -- so re-merging an overlapping
    corpus must not double-index, and must not miss the genuinely new rows."""
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=10)
    # half already present (same hashes), half new
    _corpus(staged, articles=20, first=5)

    merge_corpus(staged, working, _BATCH_META)

    st = _fts_state(working)
    assert st["articles"] == 25, "expected 15 genuinely-new articles on top of 10"
    assert st["indexed"] == 25, "the index and the table disagree after a partial overlap"
    assert st["hits_zebra"] == 25


# --------------------------------------------------------------------------- #
#  C2/C3 -- the bulk-load knobs, and the step that reports itself
# --------------------------------------------------------------------------- #
def test_hashsize_is_raised_for_the_load_and_restored_after(tmp_path) -> None:
    """FTS5's default hash budget is 1 MiB, which flushes a level-0 segment every
    megabyte -- the segment explosion whose crisis-merge cascade is the cost. It
    is raised for the load; leaving it raised would change every later ingest's
    memory profile silently, exactly as leaving automerge at 0 would."""
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=3)
    _corpus(staged, articles=12, first=4000)

    seen: list[str] = []
    merge_corpus(
        staged, working, _BATCH_META,
        stmt_cb=lambda i, name, label, secs, begin: (
            seen.append(label) if begin and "hashsize" in label else None),
    )

    assert seen, "hashsize was never set -- FTS5 ran its 1 MiB default"
    assert len(seen) >= 2, f"hashsize set but never restored: {seen}"

    # The PERSISTED value is the load-bearing assertion, not the statement count:
    # FTS5 writes hashsize into its own %_config table (verified), so a merge that
    # forgot to put it back would leave the corpus permanently holding a 64 MiB
    # pending-index budget -- a memory profile the operator never chose, applied
    # to every later ingest.
    con = sqlite3.connect(working)
    try:
        row = con.execute(
            "SELECT v FROM article_fts_config WHERE k='hashsize'").fetchone()
    finally:
        con.close()
    assert row is None or int(row[0]) == 1024 * 1024, (
        f"the corpus was left with hashsize={row[0]}, not FTS5's default")


def test_the_bulk_load_never_runs_optimize(tmp_path) -> None:
    """'optimize' rewrites the WHOLE index, so its cost tracks the corpus rather
    than the import -- measured 2.05s/3.00s/9.31s as the index grew 25k->50k->100k
    documents while the insert beside it stayed flat. With a queue of backups that
    is one whole-index rewrite per backup, each bigger than the last."""
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=3)
    _corpus(staged, articles=12, first=4000)

    ran: list[str] = []
    merge_corpus(
        staged, working, _BATCH_META,
        stmt_cb=lambda i, name, label, secs, begin: (
            ran.append(label) if begin and "optimize" in label else None),
    )

    assert ran == [], f"the merge still runs a whole-index rewrite: {ran}"
    # ...and the index is still complete and searchable without it. A faster
    # build that lost coverage would be no fix at all.
    st = _fts_state(working)
    assert st["indexed"] == 15
    assert st["hits_zebra"] == 15


def test_the_search_index_step_is_counted_and_reports_its_rows(tmp_path) -> None:
    """The field defect this closes: the step reported (total, total) against a
    denominator that EXCLUDED it, so its tick published done = total-1 -- the same
    number the last table step publishes on completion. "18/19" therefore meant
    either "watches finished" or "the search index has been running for fourteen
    hours", and the run journal could not tell them apart."""
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=3)
    _corpus(staged, articles=40, first=7000)

    ticks: list[tuple[int, int, str]] = []
    done: list[tuple[int, int, str]] = []

    merge_corpus(
        staged, working, _BATCH_META,
        step_cb=lambda i, t, name, el: ticks.append((i, t, name)),
        progress_cb=lambda i, t, name: done.append((i, t, name)),
    )

    steps = merge_mod._merge_steps()
    total = len(steps) + 1
    assert all(t == total for _, t, _ in done), (
        f"the denominator must include the search index: {sorted({t for _, t, _ in done})}")
    # the last TABLE step and the search-index step must not share a number
    last_table = [i for i, _, n in done if n == steps[-1][0]]
    assert last_table == [len(steps)]
    assert len(steps) < total, "the search index is not counted as a step"

    fts_ticks = [(i, n) for i, _, n in ticks if n.startswith("search index")]
    if fts_ticks:  # ticks are time-gated; on a tiny fixture there may be none
        assert all(i == total for i, _ in fts_ticks)
        assert any("articles" in n for _, n in fts_ticks), (
            "the search-index step must report rows, not just elapsed seconds")


def test_the_row_counter_reaches_the_full_set(tmp_path) -> None:
    """The counter is the instrument that will answer the still-open field
    question, so it has to be right: it must end at the exact number of articles
    this batch added, not at a batch boundary."""
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=2)
    _corpus(staged, articles=37, first=9000)

    prog: dict = {}
    real = merge_mod._fts_index_merged_articles

    def _capture(con, batch_id, progress=None):
        n = real(con, batch_id, progress=progress)
        if progress is not None:
            prog.update(progress)
        return n

    merge_mod._fts_index_merged_articles = _capture
    try:
        merge_corpus(staged, working, _BATCH_META)
    finally:
        merge_mod._fts_index_merged_articles = real

    assert prog.get("total") == 37, prog
    assert prog.get("done") == 37, prog
    assert prog.get("phase") == "done"
