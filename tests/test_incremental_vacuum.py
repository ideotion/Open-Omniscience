"""
DB-10 §1a/§3: the off-peak incremental-vacuum pass — reclaims a bounded slice of
the freelist via ``PRAGMA incremental_vacuum(N)`` in the scheduler's idle window,
freshness-gated, and an honest no-op on a store not yet on the ruled
``auto_vacuum=INCREMENTAL`` mode (a pre-seam corpus).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine


def _engine_at(path):
    """A minimal SQLAlchemy engine bound to ``path`` via the ONE connection
    factory (mirrors src.database.session._build_engine's creator pattern),
    isolated from the process-global test engine."""
    from src.database.connect import connect

    return create_engine(
        f"sqlite:///{path}",
        future=True,
        creator=lambda: connect(path, check_same_thread=False),
    )


def test_noop_on_a_pre_seam_corpus_reports_the_real_mode(tmp_path):
    """A store created before the auto_vacuum ruling (or by any path bypassing
    connect()'s fresh-file branch) keeps auto_vacuum=NONE — the incremental
    pass must not silently do nothing; it must say so, with the real mode."""
    from src.database.maintenance import maybe_incremental_vacuum

    legacy = tmp_path / "legacy.db"
    raw = sqlite3.connect(str(legacy))
    raw.execute("CREATE TABLE t(x)")
    raw.commit()
    raw.close()

    engine = _engine_at(legacy)
    try:
        out = maybe_incremental_vacuum(engine)
    finally:
        engine.dispose()
    assert out == {"skipped": "not-incremental-mode", "auto_vacuum": 0}


def test_reclaims_pages_on_an_incremental_mode_store_and_persists_a_marker(tmp_path, monkeypatch):
    """A fresh store (auto_vacuum=INCREMENTAL by the §1a ruling) with real
    freelist pages actually reclaims some of them, and the marker records it
    (visible in the diagnostics logs, mirroring keyword_cleanup_state)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.database.connect import connect
    from src.database.maintenance import incremental_vacuum_state, maybe_incremental_vacuum

    db = tmp_path / "corpus.db"
    seed = connect(db, key=None, create_encrypted=False)
    seed.execute("CREATE TABLE t(x TEXT)")
    # Padded rows spanning many pages, then a CONTIGUOUS tail delete (by rowid)
    # so whole pages empty out — SQLite frees at page granularity, not per row;
    # an interleaved delete leaves every page still partly occupied.
    pad = "a" * 500
    seed.executemany("INSERT INTO t VALUES (?)", [(pad,) for _ in range(2000)])
    seed.commit()
    seed.execute("DELETE FROM t WHERE rowid > 1000")
    seed.commit()
    freelist_before_close = int(seed.execute("PRAGMA freelist_count").fetchone()[0])
    seed.close()
    assert freelist_before_close > 0, "fixture didn't actually produce free pages"

    assert incremental_vacuum_state() == {"last_run": None}  # nothing has run yet

    engine = _engine_at(db)
    try:
        out = maybe_incremental_vacuum(engine)
    finally:
        engine.dispose()

    assert out["freelist_pages_before"] == freelist_before_close
    assert out["pages_reclaimed"] > 0
    assert out["freelist_pages_after"] < out["freelist_pages_before"]
    assert out["at"]

    state = incremental_vacuum_state()
    assert state["last_run"] == out["at"]
    assert state["last_tally"]["pages_reclaimed"] == out["pages_reclaimed"]


def test_is_freshness_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_INCREMENTAL_VACUUM_HOURS", "6")
    from src.database.connect import connect
    from src.database.maintenance import maybe_incremental_vacuum

    db = tmp_path / "corpus.db"
    seed = connect(db, key=None, create_encrypted=False)
    seed.execute("CREATE TABLE t(x)")
    seed.commit()
    seed.close()

    engine = _engine_at(db)
    try:
        first = maybe_incremental_vacuum(engine)
        assert first.get("skipped") != "fresh"
        second = maybe_incremental_vacuum(engine)
        assert second["skipped"] == "fresh"
        assert second["last_run"] == first["at"]
    finally:
        engine.dispose()


def test_unsupported_backend_is_an_honest_noop():
    from src.database.maintenance import maybe_incremental_vacuum

    class _FakeURL:
        def get_backend_name(self):
            return "postgresql"

    class _FakeEngine:
        url = _FakeURL()

    assert maybe_incremental_vacuum(_FakeEngine()) == {"skipped": "unsupported-backend"}


def test_never_raises_on_a_locked_or_broken_store(tmp_path):
    """Best-effort background safety net: an engine pointed at a genuinely
    unreadable file must degrade to {"skipped": "error"}, never raise."""
    from src.database.maintenance import maybe_incremental_vacuum

    bogus = tmp_path / "not_a_db.db"
    bogus.write_bytes(b"not a sqlite file at all")
    engine = create_engine(f"sqlite:///{bogus}", future=True)
    try:
        out = maybe_incremental_vacuum(engine)
    finally:
        engine.dispose()
    assert out == {"skipped": "error"}


def test_wired_into_run_idle_maintenance(monkeypatch):
    """The scheduler's idle-maintenance pass calls the new step alongside the
    existing keyword/counter housekeeping, and its report rides ``out``."""
    from src.database.session import init_db
    from src.scheduler import maintenance as maint_mod

    init_db()
    monkeypatch.setattr(
        "src.analytics.store.maybe_reconcile_counters", lambda s: {"skipped": "fresh"}
    )
    monkeypatch.setattr(
        "src.analytics.store.maybe_cleanup_keywords", lambda s, **k: {"skipped": "fresh"}
    )
    called = {}

    def _fake(engine):
        called["engine"] = engine
        return {"skipped": "fresh"}

    monkeypatch.setattr("src.database.maintenance.maybe_incremental_vacuum", _fake)
    out = maint_mod.run_idle_maintenance()
    assert out["incremental_vacuum"] == {"skipped": "fresh"}
    assert "engine" in called


def test_surfaced_in_the_integrity_diagnostics(monkeypatch):
    """Mirrors the existing auto_cleanup surfacing: visible in the corpus
    integrity report, never crashing the report on a bad read."""
    from src.database.session import init_db, session_scope
    from src.monitoring import integrity

    init_db()
    monkeypatch.setattr(
        "src.database.maintenance.incremental_vacuum_state",
        lambda: {"last_run": "2026-07-20T00:00:00", "last_tally": {"pages_reclaimed": 3}},
    )
    with session_scope() as session:
        report = integrity.corpus_integrity(session)
    assert report["auto_incremental_vacuum"]["last_run"] == "2026-07-20T00:00:00"


@pytest.mark.parametrize("hours_env", ["not-a-number"])
def test_bad_env_hours_falls_back_to_default(hours_env, monkeypatch):
    monkeypatch.setenv("OO_INCREMENTAL_VACUUM_HOURS", hours_env)
    from src.database.maintenance import _incremental_vacuum_hours

    assert _incremental_vacuum_hours() == 1.0
