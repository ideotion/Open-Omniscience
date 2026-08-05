"""The merge's page-cache budget, and Stop landing INSIDE a long step.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Field 2026-08-03, from the app's own run journal: a ~35-42 GB corpus merging into
a 2.49 GB one on an 8.3 GB box spent 15.9 HOURS inside merge step 3 of 19
("articles") without finishing. Not deadlocked -- CPU accrued continuously to
33,925 s -- but RSS held 6.4 GB, all 1 GB of swap was pinned from minute 55, and
throughput decayed from ~0.9 core to ~0.4. The same code merged 20k-45k-article
backups in 17-91 SECONDS.

Two defects, and the first is the interesting one because the code's own comment
argued for it:

  1. import_cache_mb() SCALED UP with RAM, on the stated belief that an open
     transaction pins its dirty pages until COMMIT. SQLite spills them as the
     cache fills. Memory tracks cache_size, not transaction size -- so the rule
     turned a residency dial UP on the machines least able to pay.
  2. should_stop was read only BETWEEN the 14 steps, so during the step that
     takes the time, Stop did nothing and the journal's counter could not move.
"""

from __future__ import annotations

import re
import sqlite3

import pytest

from src.backup import merge as m


# --------------------------------------------------------------------------- #
#  The cache budget
# --------------------------------------------------------------------------- #
def test_the_budget_only_ever_scales_down(monkeypatch):
    """The ceiling decides on any ordinary machine; the RAM shares exist to come
    DOWN from it on a small one. The old rule did the opposite."""
    monkeypatch.delenv("OO_IMPORT_CACHE_MB", raising=False)

    # The field machine: 8.3 GB total, ~5.8 GB available. Old rule gave 989 MB.
    monkeypatch.setattr(m, "_total_ram_mb", lambda: 8300)
    monkeypatch.setattr(m, "_available_ram_mb", lambda: 5812)
    assert m.import_cache_mb() == m._IMPORT_CACHE_CEIL_MB == 256

    # A big machine gets no more than the small one: the merge's working set is
    # the whole incoming corpus at any size, so the hit rate is ~0 either way.
    monkeypatch.setattr(m, "_total_ram_mb", lambda: 128_000)
    monkeypatch.setattr(m, "_available_ram_mb", lambda: 120_000)
    assert m.import_cache_mb() == 256

    # A small machine gets less, proportionally.
    monkeypatch.setattr(m, "_total_ram_mb", lambda: 1024)
    monkeypatch.setattr(m, "_available_ram_mb", lambda: 900)
    assert m.import_cache_mb() == 128  # an eighth of total

    # ...but never below the floor, however tiny the box.
    monkeypatch.setattr(m, "_total_ram_mb", lambda: 64)
    monkeypatch.setattr(m, "_available_ram_mb", lambda: 16)
    assert m.import_cache_mb() == m._IMPORT_CACHE_FLOOR_MB == 32


def test_unreadable_ram_falls_back_to_the_measured_value_not_a_guess(monkeypatch):
    monkeypatch.delenv("OO_IMPORT_CACHE_MB", raising=False)
    monkeypatch.setattr(m, "_total_ram_mb", lambda: None)
    monkeypatch.setattr(m, "_available_ram_mb", lambda: None)
    assert m.import_cache_mb() == m._IMPORT_CACHE_CEIL_MB


def test_the_operator_override_still_wins_in_both_directions(monkeypatch):
    monkeypatch.setattr(m, "_total_ram_mb", lambda: 8300)
    monkeypatch.setattr(m, "_available_ram_mb", lambda: 5812)
    monkeypatch.setenv("OO_IMPORT_CACHE_MB", "4096")
    assert m.import_cache_mb() == 4096, "an explicit number is never second-guessed"
    monkeypatch.setenv("OO_IMPORT_CACHE_MB", "8")
    assert m.import_cache_mb() == 8
    monkeypatch.setenv("OO_IMPORT_CACHE_MB", "not-a-number")
    assert m.import_cache_mb() == 256, "a junk override falls back, never crashes an import"


def test_the_reasoning_that_produced_the_old_rule_is_corrected_in_place():
    """The old comment argued dirty pages "cannot be evicted until the final
    COMMIT". Leaving that standing would invite the next author to scale it back
    up -- the ledger's own rule that a repeated mistake is a documentation
    failure, not just a code one."""
    import inspect

    src = inspect.getsource(m)
    # The old claim survives ONLY as a quoted, explicitly-refuted premise -- so a
    # future reader meets the correction, not the belief.
    i_claim = src.index("cannot be evicted until the final")
    assert "WHAT THE PREVIOUS VERSION CLAIMED, AND WHY IT WAS WRONG" in src[:i_claim]
    assert "SPILLS dirty pages" in src
    assert "bounded by ``cache_size``, NOT by" in src


# --------------------------------------------------------------------------- #
#  The mechanism: SQLite really does spill, and really can be interrupted
# --------------------------------------------------------------------------- #
def _pair(tmp_path, rows=4000, blob_kb=8):
    src, dst = tmp_path / "inc.db", tmp_path / "main.db"
    blob = "x" * (blob_kb * 1024)
    c = sqlite3.connect(src)
    c.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT)")
    c.executemany(
        "INSERT INTO articles(hash,content) VALUES(?,?)",
        [(f"h{i:08d}", blob) for i in range(rows)],
    )
    c.commit()
    c.close()
    con = sqlite3.connect(dst)
    con.isolation_level = None
    con.execute("CREATE TABLE articles(id INTEGER PRIMARY KEY, hash TEXT UNIQUE, content TEXT)")
    con.execute(f"ATTACH DATABASE '{src}' AS inc")
    return con


_BULK = ("INSERT INTO articles(hash,content) SELECT hash,content FROM inc.articles"
         " WHERE NOT EXISTS (SELECT 1 FROM articles m WHERE m.hash=inc.articles.hash)")


def test_an_open_transaction_does_not_pin_its_dirty_pages(tmp_path):
    """THE measurement the whole cache fix rests on, run for real rather than
    asserted: with a small cache, bytes reach the database file WHILE the
    transaction is still open. If SQLite pinned dirty pages until COMMIT this
    would be zero, and scaling the cache up with RAM would have been right."""
    con = _pair(tmp_path)
    try:
        con.execute("PRAGMA cache_size=-64")  # 64 KiB: tiny, so it must spill
        con.execute("BEGIN IMMEDIATE")
        con.execute(_BULK)
        spilled = (tmp_path / "main.db").stat().st_size
        con.execute("COMMIT")
    finally:
        con.close()
    assert spilled > 1_000_000, (
        f"only {spilled} bytes reached the file during an open transaction; "
        "if SQLite really pinned dirty pages, the cache rule would need revisiting"
    )


def test_the_progress_handler_fires_inside_one_long_statement(tmp_path):
    """A single INSERT..SELECT is ONE statement. Between-steps checks cannot see
    inside it; the progress handler can."""
    con = _pair(tmp_path)
    ticks = []
    try:
        con.set_progress_handler(lambda: ticks.append(1) or 0, m._STEP_WATCH_OPS)
        con.execute("BEGIN IMMEDIATE")
        con.execute(_BULK)
        con.execute("COMMIT")
    finally:
        con.set_progress_handler(None, 0)
        con.close()
    assert len(ticks) > 10, f"only {len(ticks)} callbacks inside the statement"


# --------------------------------------------------------------------------- #
#  Stop, landing inside a step
# --------------------------------------------------------------------------- #
def test_stop_interrupts_a_running_step_and_writes_nothing(tmp_path):
    """Ruling 2026-07-29 item 15: a Stop is IMMEDIATE. It was not -- for the 15.9
    hours the field run spent inside step 3, the button was inert."""
    con = _pair(tmp_path, rows=20000)
    try:
        con.execute("BEGIN IMMEDIATE")
        with pytest.raises(m.MergeStepStopped) as ei, m._step_watch(
            con, 3, 19, "articles", lambda: True, None
        ):
            con.execute(_BULK)
        assert "articles" in str(ei.value)
        # SQLite has ALREADY rolled back: an interrupted statement aborts the
        # transaction with it. Asserting that here is the point -- it is why
        # merge_corpus's cleanup ROLLBACK must be allowed to fail harmlessly.
        with pytest.raises(sqlite3.OperationalError, match="no transaction is active"):
            con.execute("ROLLBACK")
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0, (
            "an interrupted step must leave the working copy with nothing written"
        )
    finally:
        con.close()


def test_a_stopped_step_reads_as_the_operator_stopping_not_as_an_error():
    """Subclassing RestoreAborted is load-bearing: the volume job already reports
    that as "stopped-by-operator" with the live corpus byte-identical. A new
    exception class would have surfaced the operator's own Stop as a failure."""
    assert issubclass(m.MergeStepStopped, m.RestoreAborted)


def test_the_watcher_never_catches_someone_elses_database_error(tmp_path):
    """Negative space: only OUR interrupt becomes MergeStepStopped. A genuine
    database fault must propagate unchanged, or a real failure would be reported
    to the user as their own Stop."""
    con = _pair(tmp_path)
    try:
        with pytest.raises(sqlite3.OperationalError) as ei, m._step_watch(
            con, 3, 19, "articles", lambda: False, None
        ):
            con.execute("SELECT * FROM a_table_that_does_not_exist")
        assert not isinstance(ei.value, m.MergeStepStopped)
    finally:
        con.close()


def test_the_interrupt_is_recognised_whatever_the_driver_calls_its_exception(tmp_path):
    """The merge connection is SQLCIPHER3 on any real corpus, and
    sqlcipher3.OperationalError is NOT sqlite3.OperationalError -- the
    cross-driver trap that once left the "database is locked" retry net dead on
    encrypted stores. The watcher must key on its own flag, not on a class."""
    import inspect

    src = inspect.getsource(m._step_watch)
    assert "except Exception as exc:" in src
    assert "sqlcipher3" in src, "the reason must be stated where the next author will look"

    # The fact itself, pinned: if these ever became one class hierarchy, the
    # cross-driver precautions here and in merge_corpus could be simplified --
    # and until then they must not be.
    try:
        from sqlcipher3 import dbapi2 as _sq
    except ImportError:  # pragma: no cover - core install
        pass
    else:
        assert not issubclass(_sq.Error, sqlite3.Error), (
            "sqlcipher3 exceptions are no longer foreign to sqlite3 -- revisit "
            "every driver-class catch in the merge"
        )

    class _OtherDriverError(Exception):
        """Stands in for sqlcipher3.OperationalError: a foreign class."""

    class _Capturing:
        """A connection whose driver hands the watcher's tick back to us, so the
        test can invoke it exactly as SQLite would and then fail the way a
        NON-sqlite3 driver reports an interrupt."""

        def __init__(self): self.tick = None
        def set_progress_handler(self, fn, _n): self.tick = fn
        def execute(self, *_a, **_k): raise AssertionError("not used")

    con = _Capturing()
    with pytest.raises(m.MergeStepStopped) as ei, m._step_watch(
        con, 3, 19, "articles", lambda: True, None
    ):
        assert con.tick is not None, "the watcher never installed a handler"
        assert con.tick() == 1, "a live stop must ask SQLite to abort the statement"
        raise _OtherDriverError("interrupted")

    assert "articles" in str(ei.value)
    assert isinstance(ei.value.__cause__, _OtherDriverError), (
        "the foreign driver error must be preserved as the cause, not swallowed"
    )


def test_a_foreign_driver_error_is_NOT_claimed_as_a_stop_when_none_was_asked_for():
    """Negative space for the above: the flag is the authority in BOTH
    directions. Without a stop, a foreign error stays exactly what it was."""

    class _OtherDriverError(Exception):
        pass

    class _Capturing:
        def __init__(self): self.tick = None
        def set_progress_handler(self, fn, _n): self.tick = fn

    con = _Capturing()
    with pytest.raises(_OtherDriverError), m._step_watch(
        con, 3, 19, "articles", lambda: False, None
    ):
        assert con.tick() == 0
        raise _OtherDriverError("a genuine database fault")


# --------------------------------------------------------------------------- #
#  The tick: liveness, never a fabricated percentage
# --------------------------------------------------------------------------- #
def test_the_tick_reports_elapsed_seconds_and_never_a_fraction():
    """The handler counts VDBE operations, which bear no honest relation to rows
    remaining. A percentage derived from them would be invented."""
    import inspect

    src = inspect.getsource(m._step_watch)
    assert "step_cb(index, total, name, round(now - t0, 1))" in src
    # Behavioural, not a word-grep: the prose legitimately DISCUSSES percentages
    # in order to rule them out. What matters is the payload.
    seen: list[tuple] = []
    with sqlite3.connect(":memory:") as c:
        with m._step_watch(c, 3, 19, "articles", None, lambda *a: seen.append(a)):
            c.execute("SELECT 1")
    for call in seen:
        assert len(call) == 4 and isinstance(call[3], float), call
        assert 0 <= call[3] < 10, "the 4th argument is elapsed SECONDS, nothing else"

    caller = inspect.getsource(m.run_restore)
    assert "merge_step_tick" in caller
    assert "step_elapsed_s" in caller


def test_a_raising_stop_predicate_never_aborts_an_hours_long_import(tmp_path):
    """A broken predicate must read as "do not stop". Aborting a 16-hour import
    because a callback threw would be the sidecar-breaks-the-operation failure."""
    con = _pair(tmp_path, rows=200)

    def _boom():
        raise RuntimeError("predicate is broken")

    try:
        con.execute("BEGIN IMMEDIATE")
        with m._step_watch(con, 3, 19, "articles", _boom, None):
            con.execute(_BULK)
        con.execute("COMMIT")
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 200
    finally:
        con.close()


def test_a_raising_tick_sink_never_breaks_a_merge(tmp_path):
    con = _pair(tmp_path, rows=200)

    def _boom(*_a):
        raise RuntimeError("journal is on fire")

    try:
        con.execute("BEGIN IMMEDIATE")
        with m._step_watch(con, 3, 19, "articles", lambda: False, _boom):
            con.execute(_BULK)
        con.execute("COMMIT")
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 200
    finally:
        con.close()


def test_a_driver_without_a_progress_handler_still_merges(tmp_path):
    """Degrade to the old between-steps-only behaviour rather than refusing to
    merge on an exotic driver."""
    real = _pair(tmp_path, rows=100)

    class _NoHandler:
        """A driver whose connection has no set_progress_handler at all."""

        def __init__(self, inner): self._inner = inner
        def set_progress_handler(self, *_a, **_k):
            raise AttributeError("this driver has no progress handler")
        def execute(self, *a, **k): return self._inner.execute(*a, **k)

    con = _NoHandler(real)
    try:
        con.execute("BEGIN IMMEDIATE")
        with m._step_watch(con, 3, 19, "articles", lambda: True, None):
            con.execute(_BULK)  # not interruptible here -- and that is the old behaviour
        con.execute("COMMIT")
        assert real.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 100
    finally:
        real.close()


def test_merge_corpus_wires_the_watcher_around_every_step():
    import inspect

    src = inspect.getsource(m.merge_corpus)
    # Anchored on the PROPERTY (the step loop is wrapped in _step_watch, carrying
    # the loop's own index/name and the stop predicate), never on a literal
    # argument list: pinning the exact call text made this test fail the moment
    # `stmt_cb` was added -- a stale source anchor breaking on correct code, which
    # is the failure mode this repo already has a lesson about.
    assert re.search(
        r"with _step_watch\(\s*con,\s*i,\s*total,\s*name,\s*should_stop\b[^)]*\):", src
    ), "the step loop must wrap every step in _step_watch"
    assert "fn(con, batch_id, results)" in src


# --------------------------------------------------------------------------- #
#  Stating the scale before spending an hour on it
#
#  (The orphaned-staging half of this section is gone: a parallel session shipped
#  the same idle sweep on 2026-08-02 as `stale_staging_sweep`, with dedicated
#  coverage in tests/test_pre_restore_snapshot_sweep.py. Two divergent tests of
#  one behaviour is worse than one.)
# --------------------------------------------------------------------------- #
def test_the_scale_of_an_import_is_stated_before_the_expensive_stages(tmp_path, monkeypatch):
    """Everything needed to see the 35 GB / 8.3 GB mismatch coming was on disk at
    run start. None of it was recorded until 16 hours later."""
    corpus = tmp_path / "corpus.db"
    corpus.write_bytes(b"x" * (4 * 1024 * 1024))
    monkeypatch.setattr(m, "_total_ram_mb", lambda: 1)  # 1 MiB of RAM => a big ratio

    facts = m._report_import_scale(corpus)
    assert facts["staged_bytes"] == 4 * 1024 * 1024
    assert facts["staged_to_ram_ratio"] == 4.0
    assert "4.0x this machine's RAM" in facts["note"]
    assert "Nothing is wrong" in facts["note"], (
        "a big import on a small box is slow, not wrong -- the note must not read "
        "as an error"
    )


def test_the_scale_note_is_absent_when_the_import_is_not_outsized(tmp_path, monkeypatch):
    corpus = tmp_path / "corpus.db"
    corpus.write_bytes(b"x" * 1024)
    monkeypatch.setattr(m, "_total_ram_mb", lambda: 8300)
    assert "note" not in m._report_import_scale(corpus)


def test_unreadable_scale_facts_are_omitted_never_guessed(tmp_path, monkeypatch):
    monkeypatch.setattr(m, "_total_ram_mb", lambda: None)
    facts = m._report_import_scale(tmp_path / "does-not-exist.db")
    assert "staged_bytes" not in facts
    assert "ram_total_mb" not in facts
    assert "staged_to_ram_ratio" not in facts and "note" not in facts


def test_reporting_the_scale_never_breaks_an_import(tmp_path, monkeypatch):
    monkeypatch.setattr(
        m, "_total_ram_mb", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    m._report_import_scale(tmp_path / "x.db")  # must not raise


def test_prepare_staged_reports_the_scale_before_validate():
    import inspect

    src = inspect.getsource(m.prepare_staged_corpus)
    # Anchored on the CALL, not on the name -- the docstring mentions the stage
    # too, and matching that would compare a comment against code.
    assert src.index("_report_import_scale(") < src.index('with _sub("prepare_staged:validate")'), (
        "the scale must be recorded BEFORE the 46-minute quick_check, not after"
    )
