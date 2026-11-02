"""The merge suspends the titles-only trigger and says the title index is behind.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Measured on a 100k + 100k merge: the live title trigger cost +50% wall clock, so the merge drops it
(beside ``article_fts_ai``) and records, in the merge's own transaction, which ids the background
backfill still owes. Behavioural: real merges, real triggers, the real backfill afterwards.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.backup import merge as merge_mod
from src.backup.merge import merge_corpus
from src.database import fts_title
from src.database.fts import ensure_fts
from src.database.models import Article, Base, Source

_META = {"artifact_kind": "oo-backup-2", "origin_fingerprint": "t", "app_version": "0.5.0",
         "alembic_rev": "head", "manifest": None}


def _corpus(path: Path, *, articles: int, first: int = 0, built: bool = False) -> None:
    eng = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(eng)
    ensure_fts(eng)
    now = datetime.now(UTC)
    with sessionmaker(bind=eng, future=True)() as s:
        src = Source(name="Wire", domain="wire.example")
        s.add(src)
        s.flush()
        for i in range(first, first + articles):
            s.add(Article(url=f"https://wire.example/{i}", canonical_url=f"https://wire.example/{i}",
                          source_id=src.id, title=f"headline {i} zebra", content=f"body {i}",
                          hash=f"h{i:08d}", language="en", created_at=now))
        s.commit()
    if built:
        with eng.begin() as c:
            while not fts_title.backfill_step(c)["done"]:
                pass
    eng.dispose()


def _raw(path: Path, sql: str):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _trigger(path: Path) -> bool:
    return bool(_raw(path, "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name='article_fts_title_ai'"))


def _finish_backfill(path: Path) -> dict:
    eng = create_engine(f"sqlite:///{path}", future=True)
    try:
        with eng.begin() as c:
            while not fts_title.backfill_step(c, batch=7, budget_s=0.0)["done"]:
                pass
        with eng.begin() as c:
            return fts_title.status(c)
    finally:
        eng.dispose()


def test_a_merge_leaves_the_title_index_behind_then_the_backfill_catches_up(tmp_path) -> None:
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=5, built=True)
    _corpus(staged, articles=30, first=1000)
    assert _raw(working, "SELECT cursor, frozen_max, done FROM article_fts_title_state") == [(5, 5, 1)]

    merge_corpus(staged, working, _META)

    assert _trigger(working), "the title trigger was not restored"
    # Behind, in the merge's own transaction: the old top is the cursor, the new top the end.
    assert _raw(working, "SELECT cursor, frozen_max, done FROM article_fts_title_state") == [(5, 35, 0)]
    assert _raw(working, "SELECT count(*) FROM article_fts_title_docsize") == [(5,)]
    st = _finish_backfill(working)
    assert st["complete"] and st["covered"] == 35 and st["articles"] == 35


def test_a_never_built_title_index_is_left_to_its_own_first_build(tmp_path) -> None:
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=3)
    _corpus(staged, articles=10, first=500)
    merge_corpus(staged, working, _META)
    assert _trigger(working)
    assert _raw(working, "SELECT count(*) FROM article_fts_title_state") == [(0,)]
    assert _finish_backfill(working)["covered"] == 13


def test_a_failed_merge_puts_the_title_trigger_back_and_changes_no_state(tmp_path, monkeypatch) -> None:
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, articles=4, built=True)
    _corpus(staged, articles=12, first=900)

    def _boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(merge_mod, "_fts_index_merged_articles", _boom)
    with pytest.raises(RuntimeError, match="boom"):
        merge_corpus(staged, working, _META)
    assert _trigger(working), "the title trigger is gone after a failed merge"
    assert _raw(working, "SELECT cursor, frozen_max, done FROM article_fts_title_state") == [(4, 4, 1)]
    assert _raw(working, "SELECT count(*) FROM articles") == [(4,)]


def test_mark_behind_keeps_an_unfinished_backfill_cursor() -> None:
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE articles (id INTEGER PRIMARY KEY, title TEXT)")
    con.execute(f"CREATE TABLE {fts_title.STATE_TABLE} (id INTEGER PRIMARY KEY CHECK (id = 1), cursor INTEGER, frozen_max INTEGER, done INTEGER)")
    con.executemany("INSERT INTO articles(id, title) VALUES (?, 't')", [(i,) for i in range(1, 21)])
    con.execute(f"INSERT INTO {fts_title.STATE_TABLE} VALUES (1, 3, 10, 0)")
    fts_title.mark_behind(con, 10)
    assert con.execute(f"SELECT cursor, frozen_max, done FROM {fts_title.STATE_TABLE}").fetchall() == [(3, 20, 0)]


