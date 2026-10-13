"""A restore never writes into the attached backup when this corpus lacks a table.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

An unqualified table name in SQLite falls through to an ATTACHED file when ``main`` lacks the table.
``init_db``'s ``create_all`` gives ``main`` every ``models.py`` table, so nothing reaches this in
production; these tests drop the tables on purpose to prove the merge names ``main`` (or skips the
domain) rather than writing into the incoming file. Every merge is into a DIFFERENT corpus.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import (  # noqa: E402
    Article,
    ArticleIndexStamp,
    ArticleTitleTranslation,
    Base,
    Place,
    Source,
    WikidataItem,
)

_META = {
    "artifact_kind": "oo-backup-3", "origin_fingerprint": "machine-B", "app_version": "0.5.0",
    "alembic_rev": "head", "manifest": None,
}
_T0 = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)
_TABLES = ("article_index_stamps", "article_title_translations", "wikidata_items", "places")


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _populate_incoming(path: Path) -> None:
    with _corpus(path)() as s:
        src = Source(name="S", domain="s.example")
        s.add(src)
        s.flush()
        a = Article(url="https://s.example/1", canonical_url="https://s.example/1",
                    source_id=src.id, title="T", content="c", hash="h1")
        s.add(a)
        s.flush()
        s.add(ArticleIndexStamp(article_id=a.id, engine="e1", inputs="i1", stamped_at=_T0))
        # A second stamped article: the live corpus holds one article of its own, so the incoming
        # articles land as local ids 2 and 3, and the stamp of incoming article 2 is the one an
        # unqualified DELETE (ids taken from the local merge) would remove from the BACKUP.
        b = Article(url="https://s.example/2", canonical_url="https://s.example/2",
                    source_id=src.id, title="T2", content="c", hash="h2")
        s.add(b)
        s.flush()
        s.add(ArticleIndexStamp(article_id=b.id, engine="e1", inputs="i2", stamped_at=_T0))
        s.add(ArticleTitleTranslation(article_id=a.id, source_lang="fr", target_lang="en",
                                      title="T", summary="s", model="m", prompt_version="v1",
                                      created_at=_T0))
        s.add(WikidataItem(qid="Q1", status="ok"))
        s.add(Place(id="node/1", name="Here"))
        s.commit()


def _seed_live_article(path: Path) -> None:
    """One local article, so the two corpora give the incoming article DIFFERENT ids: with equal ids a
    write meant for ``main`` and the same write into the backup look alike."""
    with _corpus(path)() as s:
        src = Source(name="L", domain="l.example")
        s.add(src)
        s.flush()
        s.add(Article(url="https://l.example/0", canonical_url="https://l.example/0",
                      source_id=src.id, title="L", content="c", hash="h0"))
        s.commit()


def _counts(path: Path) -> dict[str, int]:
    con = sqlite3.connect(path)
    try:
        return {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _TABLES}  # noqa: S608
    finally:
        con.close()


def _drop(path: Path, *tables: str) -> None:
    con = sqlite3.connect(path)
    try:
        for t in tables:
            con.execute(f"DROP TABLE {t}")  # noqa: S608
        con.commit()
    finally:
        con.close()


@pytest.mark.parametrize("missing", _TABLES)
def test_a_table_only_the_backup_has_is_never_written_to(tmp_path, missing):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    _populate_incoming(inc)
    _seed_live_article(live)
    _drop(live, missing)
    before = _counts(inc)
    assert before[missing] >= 1

    counts, _ = merge_corpus(inc, live, _META)

    assert _counts(inc) == before, "the merge only reads the attached backup"
    if missing != "article_index_stamps":
        assert missing not in counts, "a domain is reported only when both sides hold its table"


def test_every_table_missing_at_once_still_merges_the_rest(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    _populate_incoming(inc)
    _seed_live_article(live)
    _drop(live, *_TABLES)
    before = _counts(inc)

    counts, _ = merge_corpus(inc, live, _META)

    assert _counts(inc) == before
    for domain in ("wikidata_items", "places", "article_title_translations"):
        assert domain not in counts, f"{domain} is reported only when both sides hold the table"
    con = sqlite3.connect(live)
    try:
        assert con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 3, "the articles still arrive"
    finally:
        con.close()


def test_the_carry_says_why_it_declined_when_this_corpus_has_no_stamps(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    _populate_incoming(inc)
    _seed_live_article(live)
    _drop(live, "article_index_stamps")

    counts, _ = merge_corpus(inc, live, _META)

    assert counts["_derived_carry"]["reason"] == "this corpus has no stamps table to record a carry in"


def test_an_alternate_for_a_table_this_corpus_lacks_is_deferred_not_fatal(tmp_path):
    """An ordinary backup that carries one alternate for ``places`` reaches the alternates loop; without
    the skip the lookup raises (or, unqualified, finds the BACKUP's row and records a pointer to it)."""
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    _populate_incoming(inc)
    con = sqlite3.connect(inc)
    try:
        con.execute(
            "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields,"
            " provenance, origin, status, created_at) VALUES (1, 'places', ?, 1, ?, ?, 'machine-B',"
            " 'pending', '2026-09-01 00:00:00')",
            ('{"place_id": "node/1"}', '{"name": "There", "kind": null, "qid": null,'
             ' "names_json": null, "population": null}', '{"v": 1, "kind": "x"}'),
        )
        con.commit()
    finally:
        con.close()
    _seed_live_article(live)
    _drop(live, "places")
    before = _counts(inc)

    counts, _ = merge_corpus(inc, live, _META)

    assert counts["metadata_alternates"]["deferred"] == 1
    assert counts["metadata_alternates"]["new"] == 0
    assert _counts(inc) == before


def test_the_alternates_path_reads_the_table_info_of_main():
    """Source pin for the clause a row-level test cannot tell apart (the probe's columns are the same
    in a test corpus): the NOT NULL probe must name ``main``, or a corpus lacking a table would read the
    backup's columns."""
    src = (Path(__file__).resolve().parents[1] / "src" / "backup" / "merge.py").read_text(encoding="utf-8")
    assert 'PRAGMA main.table_info({tbl})' in src
    assert 'PRAGMA table_info({tbl})' not in src
