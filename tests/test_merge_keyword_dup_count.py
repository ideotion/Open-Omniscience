"""The keyword step's duplicate count is read off ``map_keywords``, not from a pass of its own.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FIELD (2026-11-07, two Qubes VMs of ~3 GB with their swap full): the keyword step's separate
``SELECT COUNT(*) FROM inc.keywords i WHERE EXISTS (...)`` ran 7,588 s on one import and 11,555 s
on the other, a third of the step, to produce a number the id map the step builds anyway already
holds. These tests pin that the number is unchanged (the old statement's answer, computed here on
the pre-merge state, over a corpus built to hit every edge: a NULL language that COALESCEs to
'en', duplicates inside the incoming corpus, duplicates inside the target, a gap in the target's
ids) and that the old statement no longer runs.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.backup.merge as merge_mod
from src.backup.merge import merge_corpus
from src.database.models import Base, Keyword

_META = {
    "artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0",
    "alembic_rev": "head", "manifest": None,
}

_OLD_COUNT = (
    "SELECT COUNT(*) FROM inc.keywords i WHERE EXISTS (SELECT 1 FROM keywords m WHERE "
    "m.normalized_term = i.normalized_term AND COALESCE(m.language,'en') = COALESCE(i.language,'en'))"
)


def _corpus(path: Path, rows: list[tuple[str, str | None]], *, drop_ids: tuple[int, ...] = ()) -> None:
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        for term, lang in rows:
            s.add(Keyword(term=term, normalized_term=term.lower(), language=lang))
        s.commit()
    engine.dispose()
    if drop_ids:
        con = sqlite3.connect(path)
        con.executemany("DELETE FROM keywords WHERE id = ?", [(i,) for i in drop_ids])
        con.commit()
        con.close()


def _old_answer(working: Path, staged: Path) -> int:
    """What the removed statement answered, on the state it used to run against."""
    con = sqlite3.connect(working)
    try:
        con.execute("ATTACH DATABASE ? AS inc", (str(staged),))
        return int(con.execute(_OLD_COUNT).fetchone()[0])
    finally:
        con.close()


def _build(tmp_path: Path) -> tuple[Path, Path]:
    working, staged = tmp_path / "working.db", tmp_path / "staged.db"
    _corpus(
        working,
        [
            ("Petrol", "en"), ("petrol", "en"),  # a duplicate inside the TARGET
            ("Paris", None),  # NULL language: matches an incoming 'en'
            ("Berlin", "de"), ("Gone", "en"), ("Rome", "it"),
        ],
        drop_ids=(5,),  # a gap: the bound is MAX(id), never COUNT(*)
    )
    _corpus(
        staged,
        [
            ("Petrol", "en"),  # already there (twice)
            ("Paris", "en"),  # COALESCE(NULL,'en') = 'en': already there
            ("Berlin", "en"),  # same term, other language: new
            ("Gone", "en"),  # its target row was deleted: new
            ("Lisbon", "pt"), ("lisbon", "pt"),  # new, and a duplicate inside the INCOMING corpus
            ("Rome", "it"), ("rome", "it"),  # already there, duplicated incoming
            ("Oslo", None),  # new, NULL language
        ],
    )
    return working, staged


def test_the_duplicate_count_is_unchanged(tmp_path) -> None:
    working, staged = _build(tmp_path)
    expected = _old_answer(working, staged)
    assert expected == 4, "the fixture hits the cases it says it does"
    counts, _batch = merge_corpus(staged, working, _META)
    assert counts["keywords"]["duplicate"] == expected
    # and the new rows are what they were: one per new (term, language) group
    assert counts["keywords"]["new"] == 4


def test_the_count_matches_on_a_carried_copy_that_already_holds_an_earlier_merge(tmp_path) -> None:
    """A checkpoint group merges several backups into one working copy: what the first one
    inserted is "already there" for the second, exactly as the old statement saw it."""
    working, staged = _build(tmp_path)
    merge_corpus(staged, working, _META)
    second = tmp_path / "second.db"
    shutil.copy(staged, second)
    expected = _old_answer(working, second)
    counts, _batch = merge_corpus(second, working, _META)
    assert counts["keywords"]["duplicate"] == expected == 9
    assert counts["keywords"]["new"] == 0


def test_the_separate_existence_pass_no_longer_runs(tmp_path, monkeypatch) -> None:
    """Recorded at ``_count``, the one helper every count of the merge goes through (a trace
    callback would be replaced by the merge's own statement watch)."""
    seen: list[str] = []
    real = merge_mod._count

    def spy(con, sql, params=()):  # noqa: ANN001, ANN202
        seen.append(sql)
        return real(con, sql, params)

    monkeypatch.setattr(merge_mod, "_count", spy)
    working, staged = _build(tmp_path)
    merge_corpus(staged, working, _META)
    assert not [s for s in seen if "FROM inc.keywords" in s]
    assert [s for s in seen if 'FROM temp."map_keywords" WHERE new <=' in s]
