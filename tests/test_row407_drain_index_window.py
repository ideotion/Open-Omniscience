"""Row 407 (R825, R824 step 2): the index window over ONE post-import re-index drain run.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

R23 built the window, its marker and its heal; nothing called them. R825 opens it over one exclusive
post-import re-index drain run, past a measured break-even, and Plan's conditions are what these tests
pin, each by its number:

  1. the window opens only past ``DRAIN_WINDOW_MIN_FRACTION`` and only when the rebuild's memory and
     disk were READ and suffice;
  2. ``ix_mention_article`` and the unique indexes stay; the marker is committed before any drop; a KILL
     mid-drain, and a kill DURING the heal, are healed;
  3. nothing outside a drain opens it, and opening the store never rebuilds inline (R825 (b));
  4. the rebuild's sort stays in memory (SQLCipher writes a FILE sort's spill in the clear), and when
     memory or space is short the marker stays and the task manager says so (R825 (c));
  5. search and Explore read the same answers with the indexes dropped and after the heal.

Plus (a): the marker lives in the store file, so a copy taken during an open window carries it and the
copy's indexes come back.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import textwrap
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

import src.analytics.bulk_build as bb
from src.analytics.bulk_build import (
    ARTICLE_DELETE_INDEX,
    DRAIN_KEEP,
    drain_window_plan,
    droppable_indexes,
    finish_window,
    heal_bulk_build,
    open_window,
    read_state,
)
from src.database.models import Base
from tests._app_engine import app_sqlite_engine

ROOT = Path(__file__).resolve().parents[1]


def _file_engine(path: Path):
    eng = app_sqlite_engine(path)
    Base.metadata.create_all(eng)
    return eng


def _indexes(session_or_conn) -> set[str]:
    return {r[0] for r in session_or_conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'")).fetchall()}


@pytest.fixture()
def roomy(monkeypatch):
    """Memory and disk read, and plenty of both."""
    monkeypatch.setattr("src.database.article_indexes._available_ram_bytes", lambda: 64 * 10**9)
    monkeypatch.setattr("src.database.article_indexes._free", lambda _p: 10**12)
    monkeypatch.setattr("src.database.article_indexes._floor_bytes", lambda: 10**6)


def _stamp(session, n: int, *, per_article: int = 10) -> None:
    """``n`` indexed articles of ``per_article`` mention rows each: the break-even share's denominator is the
    mention rows, and its mentions per article come from the corpus."""
    session.execute(text("PRAGMA foreign_keys=OFF"))
    for i in range(1, n + 1):
        session.execute(
            text("INSERT INTO articles (id, url, canonical_url, source_id, content, hash) VALUES (:a, :u, :u, 1, 'x', :u)"),
            {"a": i, "u": f"https://x.test/{i}"},
        )
        for k in range(per_article):
            session.execute(
                text("INSERT INTO keyword_mentions (keyword_id, article_id, count) VALUES (:k, :a, 1)"),
                {"k": k + 1, "a": i},
            )
    session.commit()


def _backlog(session, n: int, start: int = 1000) -> int:
    """``n`` imported articles still waiting for their re-index (no mention rows yet)."""
    for i in range(start, start + n):
        session.execute(
            text("INSERT INTO articles (id, url, canonical_url, source_id, content, hash) VALUES (:a, :u, :u, 1, 'x', :u)"),
            {"a": i, "u": f"https://x.test/{i}"},
        )
    session.commit()
    return n


# --- 1. the threshold and the readings ------------------------------------------------------------------- #

def test_the_break_even_constant_is_measured_and_cited():
    src = (ROOT / "src/analytics/bulk_build.py").read_text(encoding="utf-8")
    assert 0 < bb.DRAIN_WINDOW_MIN_FRACTION <= 1
    assert 0 < bb.DRAIN_WINDOW_MIN_FRACTION_OVER_RAM < bb.DRAIN_WINDOW_MIN_FRACTION
    assert bb.RAM_BYTES_PER_MENTION > 0 and bb.DISK_BYTES_PER_MENTION > 0
    assert "scripts/bench_bulk_window.py" in src and (ROOT / "scripts/bench_bulk_window.py").is_file()
    assert "__FRACTION__" not in src and "__RAM__" not in src and "__DISK__" not in src


@pytest.mark.parametrize(
    "ram_mb, basis, share",
    [
        (1e-6, "store_larger_than_ram", "over"),  # a store file bigger than physical RAM
        (64 * 1024.0, "store_fits_in_ram", "default"),
        (None, "ram_unread", "default"),  # unread RAM never lowers the share: the window is optional
    ],
)
def test_the_share_depends_on_whether_the_store_fits_in_ram(tmp_path, roomy, monkeypatch, caplog, ram_mb, basis, share):
    """Row 407c: 0.15 only when the main store file is larger than physical RAM, read at the run's start; 1.0 when it
    fits or when RAM is unread. A 20% backlog opens the window only in the first case. The choice is logged."""
    import logging

    monkeypatch.setattr("src.config.memory_budget.budget_ram_mb", lambda: (ram_mb, "test"))
    eng = _file_engine(tmp_path / "r.db")
    s = sessionmaker(bind=eng, future=True)()
    try:
        _stamp(s, 100)
        with caplog.at_level(logging.INFO, logger=bb._LOG.name):
            plan = drain_window_plan(s, _backlog(s, 20))
        expected = bb.DRAIN_WINDOW_MIN_FRACTION_OVER_RAM if share == "over" else bb.DRAIN_WINDOW_MIN_FRACTION
        assert plan["threshold"]["basis"] == basis and plan["min_fraction"] == expected
        assert plan["threshold"]["store_bytes"] and plan["threshold"]["store_bytes"] > 0
        assert abs(plan["fraction"] - 0.2) < 0.01
        assert plan["open"] is (share == "over"), plan["reason"]
        assert plan["reason"] == ("open" if share == "over" else "below_break_even"), "declined by the share, not by the room"
        assert any(basis in r.getMessage() for r in caplog.records), "the chosen share and its reason are logged"
    finally:
        s.close()
        eng.dispose()


def test_an_unreadable_store_size_keeps_the_default_share(monkeypatch):
    """An in-memory store (no file to stat) keeps 1.0 even when RAM reads tiny."""
    monkeypatch.setattr("src.config.memory_budget.budget_ram_mb", lambda: (1e-6, "test"))
    eng = app_sqlite_engine(":memory:")
    s = sessionmaker(bind=eng, future=True)()
    try:
        t = bb.drain_threshold(s)
        assert t["basis"] == "store_size_unread" and t["min_fraction"] == bb.DRAIN_WINDOW_MIN_FRACTION
    finally:
        s.close()
        eng.dispose()


def test_a_backlog_below_the_break_even_keeps_the_live_indexes(tmp_path, roomy):
    eng = _file_engine(tmp_path / "a.db")
    s = sessionmaker(bind=eng, future=True)()
    try:
        _stamp(s, 200)
        below = int(200 * bb.DRAIN_WINDOW_MIN_FRACTION) - 1
        plan = drain_window_plan(s, _backlog(s, below))
        assert plan["open"] is False and plan["reason"] == "below_break_even"
        assert plan["fraction"] < bb.DRAIN_WINDOW_MIN_FRACTION
        at = drain_window_plan(s, _backlog(s, 3, start=5000) + below)
        assert at["open"] is True and at["reason"] == "open" and at["fraction"] >= bb.DRAIN_WINDOW_MIN_FRACTION
    finally:
        s.close()
        eng.dispose()


def test_an_unread_memory_or_disk_figure_declines_the_window(tmp_path, monkeypatch):
    """Opening is optional, so an unknown declines it rather than gamble on a sort that may not fit."""
    monkeypatch.setattr("src.database.article_indexes._available_ram_bytes", lambda: None)
    monkeypatch.setattr("src.database.article_indexes._free", lambda _p: None)
    eng = _file_engine(tmp_path / "a.db")
    s = sessionmaker(bind=eng, future=True)()
    try:
        _stamp(s, 10)
        plan = drain_window_plan(s, _backlog(s, 10))
        assert plan["open"] is False and plan["reason"] == "room_not_measured"
    finally:
        s.close()
        eng.dispose()


@pytest.mark.parametrize("unread", ["memory", "disk"])
def test_one_unread_reading_declines_the_window(tmp_path, monkeypatch, unread):
    """Both readings must have been made: plenty of disk says nothing about whether the sort fits in memory."""
    monkeypatch.setattr("src.database.article_indexes._available_ram_bytes", lambda: None if unread == "memory" else 64 * 10**9)
    monkeypatch.setattr("src.database.article_indexes._free", lambda _p: None if unread == "disk" else 10**12)
    eng = _file_engine(tmp_path / "a.db")
    s = sessionmaker(bind=eng, future=True)()
    try:
        _stamp(s, 10)
        plan = drain_window_plan(s, _backlog(s, 10))
        assert plan["open"] is False and plan["reason"] == "room_not_measured"
    finally:
        s.close()
        eng.dispose()


def test_short_memory_declines_the_window_and_says_so(tmp_path, monkeypatch):
    monkeypatch.setattr("src.database.article_indexes._available_ram_bytes", lambda: 1)
    monkeypatch.setattr("src.database.article_indexes._free", lambda _p: 10**12)
    eng = _file_engine(tmp_path / "a.db")
    s = sessionmaker(bind=eng, future=True)()
    try:
        _stamp(s, 10)
        plan = drain_window_plan(s, _backlog(s, 10))
        assert plan["open"] is False and plan["reason"] == "not_enough_room"
        assert plan["preflight"]["short_on"] == ["memory"]
    finally:
        s.close()
        eng.dispose()


# --- 2. what stays, and the order -------------------------------------------------------------------------- #

def test_the_drain_keeps_the_delete_index_and_every_unique_index(tmp_path):
    eng = _file_engine(tmp_path / "a.db")
    s = sessionmaker(bind=eng, future=True)()
    try:
        planned = open_window(s, keep=DRAIN_KEEP, reason="test")
        left = _indexes(s)
        assert ARTICLE_DELETE_INDEX in left and ARTICLE_DELETE_INDEX not in planned
        for unique in ("ix_mention_keyword_article", "ix_amp_article_place", "ix_ae_article_name_class"):
            assert unique in left
        assert not set(planned) & left
        assert read_state(s) is not None and set(read_state(s)["planned"]) == set(planned)
    finally:
        s.close()
        eng.dispose()


_KILL_CHILD = textwrap.dedent(
    """
    import os, sys
    sys.path.insert(0, sys.argv[1])
    from sqlalchemy.orm import sessionmaker
    from tests._app_engine import app_sqlite_engine
    import src.analytics.bulk_build as bb

    eng = app_sqlite_engine(sys.argv[2])
    s = sessionmaker(bind=eng, future=True)()
    if sys.argv[3] == "drain":
        bb.open_window(s, keep=bb.DRAIN_KEEP, reason="killed drain")
        os._exit(9)  # killed mid-drain: the indexes are gone, nothing of the run is left
    # killed during the heal: after the FIRST index of the rebuild
    def _die(done, total):
        if done >= 1:
            os._exit(9)
    bb._rebuild_missing(s, bb.read_state(s)["planned"], on_progress=_die)
    """
)


def _kill_child(db: Path, what: str) -> None:
    env = {**os.environ, "OO_NO_SCHEDULER": "1"}
    r = subprocess.run([sys.executable, "-c", _KILL_CHILD, str(ROOT), str(db), what], env=env, capture_output=True, timeout=120)
    assert r.returncode == 9, r.stderr.decode()[-2000:]


def test_a_kill_mid_drain_and_a_kill_during_the_heal_are_both_healed(tmp_path, roomy):
    """THE CRASH TEST, with real kills: a process that dies with the indexes dropped, then a heal that dies
    part way. The next heal finds the marker and the store's own index list, and finishes."""
    db = tmp_path / "k.db"
    eng = _file_engine(db)
    eng.dispose()

    _kill_child(db, "drain")
    eng = app_sqlite_engine(db)
    s = sessionmaker(bind=eng, future=True)()
    planned = list(read_state(s)["planned"])
    assert planned and not set(planned) & _indexes(s), "the kill left the indexes dropped and the marker open"
    s.close()
    eng.dispose()

    _kill_child(db, "heal")
    eng = app_sqlite_engine(db)
    s = sessionmaker(bind=eng, future=True)()
    some = set(planned) & _indexes(s)
    assert some and set(planned) - _indexes(s), "the heal died part way: some back, some not"
    assert read_state(s) is not None, "and the marker is still open"

    out = finish_window(s)
    assert out["complete"] is True
    assert set(planned) <= _indexes(s) and read_state(s) is None
    s.close()
    eng.dispose()


# --- 3. nothing outside a drain, and no inline rebuild at open --------------------------------------------- #

def test_only_the_drain_opens_the_window():
    """Every caller of ``open_window`` / ``bulk_index_window`` in ``src/`` is the drain."""
    import re

    callers = []
    pattern = re.compile(r"(?:\bbb\.|\b_bb\.|bulk_build\.|^\s*from src\.analytics\.bulk_build import .*)(?:open_window|bulk_index_window)\b|\bbulk_index_window\(", re.M)
    for path in (ROOT / "src").rglob("*.py"):
        if path.name == "bulk_build.py":
            continue
        if pattern.search(path.read_text(encoding="utf-8")):
            callers.append(path.relative_to(ROOT).as_posix())
    assert callers == ["src/api/backup_v2.py"]


def _create_index_names(statements: list[str]) -> set[str]:
    out = set()
    for st in statements:
        up = st.upper()
        if "CREATE" in up and "INDEX" in up:
            for name in droppable_indexes():
                if name in st:
                    out.add(name)
    return out


def test_opening_the_store_with_an_open_marker_builds_nothing_inline(tmp_path):
    """R825 (b): ``heal_bulk_build(inline=False)`` and the hot-index heal at open run no CREATE INDEX for an
    index the marker owes; the background heal does."""
    from src.database.maintenance import ensure_hot_indexes

    eng = _file_engine(tmp_path / "b.db")
    s = sessionmaker(bind=eng, future=True)()
    planned = open_window(s, keep=DRAIN_KEEP, reason="test")
    s.close()

    seen: list[str] = []
    event.listen(eng, "before_cursor_execute", lambda _c, _cur, st, *_a: seen.append(st))
    assert heal_bulk_build(eng, inline=False) == []
    ensure_hot_indexes(eng, include_deferred=False)
    assert not _create_index_names(seen), "nothing owed was built at open"
    s = sessionmaker(bind=eng, future=True)()
    assert not set(planned) & _indexes(s) and read_state(s) is not None
    s.close()
    eng.dispose()


def test_init_db_builds_no_owed_index_inline():
    """The real ``init_db`` against the suite's scratch store, with a window left open."""
    from src.database import session as sess

    sess.init_db()  # the scratch store exists whole first, whatever ran before this test
    with sess.session_scope() as s:
        planned = open_window(s, keep=DRAIN_KEEP, reason="test")
    seen: list[str] = []

    def _watch(_c, _cur, st, *_a):
        seen.append(st)

    event.listen(sess.engine, "before_cursor_execute", _watch)
    try:
        sess.init_db()
        assert not _create_index_names(seen), "init_db ran a CREATE INDEX the marker owes"
    finally:
        event.remove(sess.engine, "before_cursor_execute", _watch)
        heal_bulk_build(sess.engine)  # put the scratch store back
    with sess.session_scope() as s:
        assert set(planned) <= _indexes(s) and read_state(s) is None


def test_the_boot_sequence_starts_the_heal_only_when_the_drain_does_not(monkeypatch):
    from src.api import boot_sequence as bs

    started: list[str] = []
    monkeypatch.setattr(bb, "start_heal", lambda *a, **k: started.append("heal") or "started")
    monkeypatch.setattr(bs, "_queue_title_index", lambda: None)
    monkeypatch.setattr(bs, "_queue_day_counts", lambda: None)

    monkeypatch.setitem(bs._STATE, "reindex_pending", None)
    with pytest.raises(bs._Skipped):
        bs._start_reindex()
    assert started == ["heal"], "no drain to run: the heal starts"

    started.clear()
    monkeypatch.setitem(bs._STATE, "reindex_pending", 5)
    monkeypatch.setattr("src.backup.volume_job.start_reindex_drain", lambda: (True, "started"))
    bs._start_reindex()
    assert started == [], "the drain adopts the marker and rebuilds at its end"


def test_a_restore_that_ends_starts_the_heal(monkeypatch):
    from src.backup import merge

    calls: list[str] = []
    monkeypatch.setattr(bb, "start_heal", lambda *a, **k: calls.append("heal") or "none")
    monkeypatch.setattr("src.scheduler.runner.exclusive_window_open", lambda: False)
    monkeypatch.setattr("src.jobs.background.start_jobs_after_refusal", lambda kinds: list(kinds))
    merge._remember_stopped(["reindex-resume"])
    assert merge.start_jobs_stopped_for_restore() == ["reindex-resume"]
    assert calls == ["heal"]


def test_the_heal_declines_while_the_drain_runs(tmp_path, monkeypatch):
    eng = _file_engine(tmp_path / "c.db")
    s = sessionmaker(bind=eng, future=True)()
    open_window(s, keep=DRAIN_KEEP, reason="test")
    s.close()

    class _Running:
        def status(self):
            return {"state": "running"}

    monkeypatch.setattr("src.jobs.background.get_job", lambda kind: _Running() if kind == "reindex-resume" else None)
    assert bb.start_heal(eng) == "drain"
    eng.dispose()


# --- 4. memory temp, and the waiting line ------------------------------------------------------------------ #

def test_every_rebuild_runs_with_the_sort_in_memory(tmp_path, roomy):
    eng = _file_engine(tmp_path / "d.db")
    s = sessionmaker(bind=eng, future=True)()
    planned = open_window(s, keep=DRAIN_KEEP, reason="test")
    seen: list[str] = []
    event.listen(eng, "before_cursor_execute", lambda _c, _cur, st, *_a: seen.append(st))
    out = finish_window(s)
    assert out["complete"] is True
    creates = [i for i, st in enumerate(seen) if st.upper().startswith("CREATE INDEX")]
    assert len(creates) == len(planned)
    for i in creates:
        before = [st.upper().replace(" ", "") for st in seen[:i]]
        assert "PRAGMATEMP_STORE=MEMORY" in before[-1], "the pragma runs right before each CREATE INDEX"
    s.close()
    eng.dispose()


def test_short_memory_keeps_the_marker_and_the_task_manager_says_why(tmp_path, monkeypatch):
    monkeypatch.setattr("src.database.article_indexes._available_ram_bytes", lambda: 5_000_000)
    monkeypatch.setattr("src.database.article_indexes._free", lambda _p: 10**12)
    monkeypatch.setattr("src.database.article_indexes._floor_bytes", lambda: 10**9)
    eng = _file_engine(tmp_path / "e.db")
    s = sessionmaker(bind=eng, future=True)()
    planned = open_window(s, keep=DRAIN_KEEP, reason="test")
    s.close()

    @contextlib.contextmanager
    def _scope():
        ss = sessionmaker(bind=eng, future=True)()
        try:
            yield ss
            ss.commit()
        finally:
            ss.close()

    monkeypatch.setattr("src.database.session.session_scope", _scope)

    class _Ctx:
        def __init__(self):
            self.progress: list[dict] = []

        def set_progress(self, **kw):
            self.progress.append(kw)

    ctx = _Ctx()
    out = bb._heal_worker(ctx)
    assert out["complete"] is False and out["waiting"]["short_on"] == ["memory"]
    last = ctx.progress[-1]["detail"]
    assert getattr(last, "i18n", None) == bb.FRAME_WAITING_MEMORY, "memory was short, and only memory is named"
    s = sessionmaker(bind=eng, future=True)()
    assert read_state(s) is not None and not set(planned) & _indexes(s), "never claimed rebuilt"
    s.close()

    # The job has ended (a finished job is not listed), so the task manager's own row carries the line.
    from src.api import jobs as jobs_api

    monkeypatch.setattr("src.database.session.engine", eng)
    monkeypatch.setitem(jobs_api._kw_index_cache, "at", 0.0)
    monkeypatch.setitem(jobs_api._kw_index_cache, "value", None)
    monkeypatch.setattr(jobs_api, "_KW_INDEX_TTL_S", -1.0)
    rows = jobs_api._keyword_index_rows()
    assert len(rows) == 1 and rows[0]["kind"] == bb.HEAL_JOB_KIND and rows[0]["state"] == "paused"
    assert rows[0]["detail_i18n"] == bb.FRAME_WAITING_MEMORY and set(rows[0]["detail_vars"]) == {"free", "needed"}
    eng.dispose()


def test_a_storage_guard_wait_shows_in_the_task_manager(tmp_path, monkeypatch, roomy):
    """Row 411: memory and disk suffice, but the storage guard holds writes, so the heal waits. The job ends (a
    finished job is not listed), and the task manager's own row names the guard rather than showing nothing."""
    from src.scheduler.storage_guard import storage_guard

    monkeypatch.setattr(storage_guard, "engaged_now", lambda: True)
    eng = _file_engine(tmp_path / "g.db")
    s = sessionmaker(bind=eng, future=True)()
    planned = open_window(s, keep=DRAIN_KEEP, reason="test")
    s.close()

    @contextlib.contextmanager
    def _scope():
        ss = sessionmaker(bind=eng, future=True)()
        try:
            yield ss
            ss.commit()
        finally:
            ss.close()

    monkeypatch.setattr("src.database.session.session_scope", _scope)

    class _Ctx:
        def __init__(self):
            self.progress: list[dict] = []

        def set_progress(self, **kw):
            self.progress.append(kw)

    ctx = _Ctx()
    out = bb._heal_worker(ctx)
    assert out["complete"] is False and out["reason"] == "storage_guard_engaged"
    assert getattr(ctx.progress[-1]["detail"], "i18n", None) == bb.FRAME_WAITING_GUARD
    s = sessionmaker(bind=eng, future=True)()
    assert read_state(s) is not None and not set(planned) & _indexes(s), "the marker is kept, nothing claimed rebuilt"
    s.close()

    from src.api import jobs as jobs_api

    monkeypatch.setattr("src.database.session.engine", eng)
    monkeypatch.setitem(jobs_api._kw_index_cache, "at", 0.0)
    monkeypatch.setitem(jobs_api._kw_index_cache, "value", None)
    monkeypatch.setattr(jobs_api, "_KW_INDEX_TTL_S", -1.0)
    rows = jobs_api._keyword_index_rows()
    assert len(rows) == 1 and rows[0]["state"] == "paused" and rows[0]["detail_i18n"] == bb.FRAME_WAITING_GUARD
    assert "memory" not in rows[0]["detail"] and "disk" not in rows[0]["detail"], "nothing was short"

    monkeypatch.setattr(storage_guard, "engaged_now", lambda: False)
    monkeypatch.setitem(jobs_api._kw_index_cache, "at", 0.0)
    assert jobs_api._keyword_index_rows() == [], "memory and disk suffice once the guard lets go: no waiting row"
    eng.dispose()


def test_the_two_lines_are_keyed_in_every_language():
    import json

    for loc in sorted((ROOT / "src/static/locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        for key in (bb.FRAME_REBUILDING, bb.HEAL_LABEL, *bb.FRAMES_WAITING):
            assert key in d and d[key].strip(), f"{loc.name}: {key[:40]}"
        assert "{index}" in d[bb.FRAME_REBUILDING] and "{total}" in d[bb.FRAME_REBUILDING]
        for key in (bb.FRAME_WAITING_MEMORY, bb.FRAME_WAITING_DISK):
            assert "{free}" in d[key] and "{needed}" in d[key]
        assert all(v in d[bb.FRAME_WAITING_BOTH] for v in ("{ram_free}", "{ram_needed}", "{disk_free}", "{disk_needed}"))
    js = (ROOT / "src/static/app-core.js").read_text(encoding="utf-8")
    assert 'j.kind === "keyword-indexes"' in js and 'j.kind === "reindex-resume"' in js


# --- (a) the marker travels with a copy of the store ------------------------------------------------------- #

def test_a_copy_taken_during_an_open_window_gets_its_indexes_back(tmp_path, roomy):
    from src.backup.artifact import snapshot_sqlite

    live = tmp_path / "live.db"
    eng = _file_engine(live)
    s = sessionmaker(bind=eng, future=True)()
    planned = open_window(s, keep=DRAIN_KEEP, reason="test")
    s.close()
    copy = snapshot_sqlite(live, tmp_path / "backup.db")
    eng.dispose()

    restored = app_sqlite_engine(copy)
    assert heal_bulk_build(restored, inline=False) == [], "opening the restored copy builds nothing inline"
    s = sessionmaker(bind=restored, future=True)()
    assert read_state(s) is not None, "the marker came with the copy"
    assert finish_window(s)["complete"] is True
    assert set(planned) <= _indexes(s) and read_state(s) is None
    s.close()
    restored.dispose()


def test_a_merge_restore_never_carries_another_stores_marker():
    """A merge restore copies rows, not ``derived_meta``: the live store's own marker (in the working copy)
    is the only one that can ever be open after the swap."""
    from src.backup.merge import _MERGE_NOT_CARRIED

    assert "derived_meta" in _MERGE_NOT_CARRIED


# --- 5. reads stay correct --------------------------------------------------------------------------------- #

def _corpus(session) -> list[int]:
    from src.analytics.extract import BaselineExtractor
    from src.analytics.store import index_article
    from src.database.models import Article, Source

    session.add(Source(name="S", domain="x.test", country="fr"))
    session.commit()
    texts = [
        ("Inflation rose in Paris. Inflation worries grew as sanctions on nickel spread.", "2024-01-03", "fr"),
        ("Sanctions and nickel prices dominated headlines while inflation pressures intensified.", "2024-01-10", "de"),
        ("Central banks discussed inflation, nickel supply and sanctions in Berlin.", "2024-02-02", "de"),
        ("Nickel miners in Jakarta reported sanctions affecting exports and inflation.", "2024-02-20", "id"),
    ]
    ids = []
    for i, (body, when, cc) in enumerate(texts):
        a = Article(
            url=f"https://x.test/{i}", canonical_url=f"https://x.test/{i}", source_id=1, title="T", content=body,
            hash=f"h{i}", country=cc, language="en",
            published_at=datetime.fromisoformat(when).replace(tzinfo=UTC), created_at=datetime.now(UTC),
        )
        session.add(a)
        session.commit()
        index_article(session, a, extractor=BaselineExtractor(), country=cc, city="X")
        ids.append(a.id)
    session.commit()
    return ids


def _reads(session, ids: list[int]) -> dict:
    from src.analytics import queries as q

    return {
        "trend": q.trend(session, "inflation", bucket="week")["points"],
        "top": [t["normalized"] for t in q.top_terms(session, limit=20)["terms"]],
        "explore": q.corpus_keywords(session, article_ids=ids, limit=20),
        "who": q.corpus_who(session, article_ids=ids),
        "where": q.corpus_where(session, article_ids=ids),
        "when": q.corpus_when(session, article_ids=ids),
        "by_date": session.execute(text(
            "SELECT keyword_id, COUNT(*) FROM keyword_mentions WHERE observed_on >= '2024-01-05' GROUP BY keyword_id ORDER BY 1"
        )).fetchall(),
    }


def test_search_and_explore_read_the_same_with_the_indexes_dropped_and_after_the_heal(tmp_path, roomy):
    eng = _file_engine(tmp_path / "r.db")
    s = sessionmaker(bind=eng, future=True)()
    ids = _corpus(s)
    before = _reads(s, ids)
    assert before["trend"] and before["top"], "the corpus is not empty: an empty read would match anything"

    planned = open_window(s, keep=DRAIN_KEEP, reason="test")
    assert not set(planned) & _indexes(s)
    during = _reads(s, ids)
    assert finish_window(s)["complete"] is True
    after = _reads(s, ids)
    assert during == before, "slower is allowed, a different answer is not"
    assert after == before
    s.close()
    eng.dispose()


# --- the drain itself ---------------------------------------------------------------------------------------- #

from tests.test_reindex_drain_settings import _Ctx as _DrainCtx  # noqa: E402
from tests.test_reindex_drain_settings import drain  # noqa: E402,F401 - the fixture, reused


@pytest.fixture()
def real_store(tmp_path, monkeypatch, drain, roomy):  # noqa: F811
    """The drain fixture's fakes, with the window's reads and writes on a real store."""
    from src.api import backup_v2 as bv2

    eng = _file_engine(tmp_path / "drain.db")
    s0 = sessionmaker(bind=eng, future=True)()
    _stamp(s0, 10)  # 100 mention rows; the fixture's backlog of 10 articles projects far past any break-even
    s0.close()

    @contextlib.contextmanager
    def _scope(*_a, **_k):
        ss = sessionmaker(bind=eng, future=True)()
        try:
            yield ss
            ss.commit()
        finally:
            ss.close()

    monkeypatch.setattr("src.database.session.session_scope", _scope)
    state, rec = drain
    seen_during: list[set[str]] = []
    real = bv2.__dict__  # noqa: F841 - the merge fakes are already in place

    import src.backup.merge as merge_mod

    fake_reindex = merge_mod.reindex_imported_articles

    def _reindex(batch_id, **kw):
        with eng.connect() as c:
            seen_during.append(_indexes(c))
        return fake_reindex(batch_id, **kw)

    monkeypatch.setattr("src.backup.merge.reindex_imported_articles", _reindex)
    yield eng, state, rec, seen_during
    eng.dispose()


def _store_state(eng) -> tuple[set[str], object]:
    s = sessionmaker(bind=eng, future=True)()
    try:
        return _indexes(s), read_state(s)
    finally:
        s.close()


def test_the_drain_opens_the_window_and_rebuilds_once_at_its_end(real_store):
    from src.api import backup_v2 as bv2

    eng, state, rec, seen_during = real_store
    ctx = _DrainCtx()
    out = bv2._reindex_resume_worker(ctx)
    planned = set(droppable_indexes(keep=DRAIN_KEEP))
    assert seen_during and all(not planned & during for during in seen_during), "the batches ran with the window open"
    assert all(ARTICLE_DELETE_INDEX in during for during in seen_during)
    present, marker = _store_state(eng)
    assert planned <= present and marker is None
    assert out["index_window"]["complete"] is True
    frames = [getattr(p.get("detail"), "i18n", None) for p in ctx.progress]
    assert bb.FRAME_REBUILDING in frames, "the task manager showed the rebuild"


def test_a_busy_collector_never_opens_the_window(real_store):
    from src.api import backup_v2 as bv2

    eng, state, rec, seen_during = real_store
    state["scheduler_running"] = True
    out = bv2._reindex_resume_worker(_DrainCtx())
    planned = set(droppable_indexes(keep=DRAIN_KEEP))
    assert all(planned <= during for during in seen_during)
    assert "index_window" not in out


def test_a_drain_that_yields_to_an_import_leaves_the_marker_and_the_next_run_adopts_it(real_store):
    """The restore waits 30 s for this drain; a rebuild over a corpus is longer. So the yield leaves the
    marker for the working copy, and the next drain run (or the heal) rebuilds."""
    import src.backup.merge as merge_mod
    from src.api import backup_v2 as bv2

    eng, state, rec, seen_during = real_store
    ctx = _DrainCtx()
    inner = merge_mod.reindex_imported_articles

    def _import_arrives(batch_id, **kw):
        ctx.yielding = True  # an import asks for the machine during the first batch
        return inner(batch_id, **kw)

    merge_mod.reindex_imported_articles = _import_arrives
    try:
        out = bv2._reindex_resume_worker(ctx)
    finally:
        merge_mod.reindex_imported_articles = inner
    assert out["index_window"]["left_open_for_import"] is True
    present, marker = _store_state(eng)
    planned = set(droppable_indexes(keep=DRAIN_KEEP))
    assert marker is not None and not planned & present

    state["batches"] = []  # the next run has nothing to re-index, and still finishes the window
    out2 = bv2._reindex_resume_worker(_DrainCtx())
    present, marker = _store_state(eng)
    assert planned <= present and marker is None
    assert out2["index_window"]["adopted"] is True and out2["index_window"]["complete"] is True


def test_a_run_already_stopping_never_opens_the_window(real_store):
    """A run cancelled (or told to yield) before its first batch drops nothing: dropping 13 indexes only to
    rebuild them at once, or to leave them for an import, is a full sort for nothing."""
    from src.api import backup_v2 as bv2

    eng, state, rec, seen_during = real_store
    out = bv2._reindex_resume_worker(_DrainCtx(stopping=True))
    present, marker = _store_state(eng)
    assert marker is None and set(droppable_indexes(keep=DRAIN_KEEP)) <= present
    assert "index_window" not in out, "no window was opened"


def test_an_operator_stop_mid_run_still_rebuilds(real_store, monkeypatch):
    import src.backup.merge as merge_mod
    from src.api import backup_v2 as bv2

    eng, state, rec, seen_during = real_store
    ctx = _DrainCtx()
    inner = merge_mod.reindex_imported_articles

    def _stop_after(batch_id, **kw):
        ctx.stopping = True  # the operator presses Stop during the first batch
        return inner(batch_id, **kw)

    monkeypatch.setattr("src.backup.merge.reindex_imported_articles", _stop_after)
    out = bv2._reindex_resume_worker(ctx)
    assert seen_during and not set(droppable_indexes(keep=DRAIN_KEEP)) & seen_during[0], "the window was open"
    present, marker = _store_state(eng)
    assert marker is None and set(droppable_indexes(keep=DRAIN_KEEP)) <= present
    assert out["index_window"]["complete"] is True


def test_an_engaged_storage_guard_leaves_the_marker_for_later(real_store, monkeypatch):
    from src.api import backup_v2 as bv2
    from src.scheduler.storage_guard import storage_guard

    eng, state, rec, seen_during = real_store
    ctx = _DrainCtx()
    import src.backup.merge as merge_mod

    inner = merge_mod.reindex_imported_articles
    engaged = {"now": False}

    def _engage_after(batch_id, **kw):
        out = inner(batch_id, **kw)
        engaged["now"] = True  # the guard engages after the last batch, before the rebuild
        return out

    monkeypatch.setattr("src.backup.merge.reindex_imported_articles", _engage_after)
    monkeypatch.setattr(storage_guard, "engaged_now", lambda: engaged["now"])
    monkeypatch.setattr(storage_guard, "wait_if_engaged", lambda *a, **k: False)
    out = bv2._reindex_resume_worker(ctx)
    assert out["index_window"].get("left_open_for_storage_guard") is True
    present, marker = _store_state(eng)
    assert marker is not None and not set(droppable_indexes(keep=DRAIN_KEEP)) & present


def test_the_waiting_line_names_only_what_was_short():
    """Plan's string read: "memory or disk space" only when both were short; otherwise the one that was."""
    base = {"ram_available_bytes": 50_000_000, "ram_needed_bytes": 70_000_000, "ram_floor_bytes": 10_000_000,
            "disk_free_bytes": 3_000_000, "disk_needed_bytes": 4_500_001}
    mem = bb.waiting_line({**base, "short_on": ["memory"]})
    disk = bb.waiting_line({**base, "short_on": ["database"]})
    both = bb.waiting_line({**base, "short_on": ["database", "memory"]})
    assert mem.i18n == bb.FRAME_WAITING_MEMORY and mem.vars == {"free": 50, "needed": 80}
    assert "disk" not in str(mem)
    assert disk.i18n == bb.FRAME_WAITING_DISK and disk.vars == {"free": 3, "needed": 5}, "the need rounds up"
    assert "memory" not in str(disk)
    assert both.i18n == bb.FRAME_WAITING_BOTH and "memory" in str(both) and "disk" in str(both)
