"""The low-memory path: an encrypted merge's whole-source groupings in an encrypted scratch file.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

FIELD (2026-11-08, two Qubes VMs of about 3 GB): encrypted imports were refused for memory, or ran
their keyword grouping with swap full for 3 to 6 hours. The groupings now run as an upsert into a
pager-backed table of a scratch database that inherits the working copy's key, when the RAM is
short. Pinned here: the same answer as the in-RAM GROUP BY on every key shape (NULLs, a real 0 next
to a NULL, mixed types, duplicates), a merge that gives the same corpus either way, a scratch file
that is encrypted while it exists and gone afterwards, and a plain store that never takes this path.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlcipher3")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

import src.database.connect as connect_mod  # noqa: E402
from src.backup import merge as merge_mod  # noqa: E402
from src.backup.merge import merge_corpus  # noqa: E402
from src.database.models import Article, ArticleLink, Base, Keyword, Source  # noqa: E402

_KEY = "correct horse battery staple"
_META = {
    "artifact_kind": "oo-backup-2", "origin_fingerprint": "test", "app_version": "0.5.0",
    "alembic_rev": "head", "manifest": None,
}
_GROUPS = {
    "rep_keywords": "SELECT MIN(id) FROM inc.keywords GROUP BY normalized_term, COALESCE(language,'en')",
    "rep_links": "SELECT MIN(id) FROM inc.article_links GROUP BY article_id, url, COALESCE(position,-1)",
    "rep_asr": "SELECT MIN(id) FROM inc.article_source_relationships"
               " GROUP BY article_id, COALESCE(source_id,-1), COALESCE(relationship_type,'')",
}


def test_the_three_group_statements_are_the_ones_the_merge_runs() -> None:
    """The statements below are the merge's own (split across literals there), so the equivalence
    test exercises what the merge runs, not a copy that drifted."""
    src = Path(merge_mod.__file__).read_text(encoding="utf-8")
    for sql in _GROUPS.values():
        head, keys = sql.split(" GROUP BY ")
        assert head in src and f"GROUP BY {keys}" in src, sql


def _raw_tables(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        CREATE TABLE keywords (id INTEGER PRIMARY KEY, normalized_term TEXT, language TEXT);
        CREATE TABLE article_links (id INTEGER PRIMARY KEY, article_id INTEGER, url TEXT, position INTEGER);
        CREATE TABLE article_source_relationships (id INTEGER PRIMARY KEY, article_id INTEGER,
            source_id INTEGER, relationship_type TEXT);
        """
    )
    con.executemany(
        "INSERT INTO keywords (normalized_term, language) VALUES (?, ?)",
        [("a", "en"), ("a", None), ("a", "fr"), ("b", None), ("b", None), (None, "en"), (None, "en"),
         ("0", "en"), (0, "en"), ("a", "en"), ("", None), ("", "en")],
    )
    con.executemany(
        "INSERT INTO article_links (article_id, url, position) VALUES (?, ?, ?)",
        [(1, "u", None), (1, "u", -1), (1, "u", 0), (1, "u", None), (None, "u", 2), (None, "u", 2), (0, "u", 2),  # a real 0 beside NULLs: the flag keeps them apart
         (2, None, 0), (2, None, 0), (2, "u", 0), (1, 0, None), (1, None, None)],
    )
    con.executemany(
        "INSERT INTO article_source_relationships (article_id, source_id, relationship_type) VALUES (?, ?, ?)",
        [(1, None, None), (1, -1, ""), (1, 0, None), (1, None, "cites"), (1, None, "cites"),
         (None, None, None), (None, None, None), (0, None, None), (3, 2, "x")],
    )
    con.commit()
    con.close()


@pytest.mark.parametrize("name", sorted(_GROUPS))
def test_the_scratch_grouping_is_the_group_by_on_every_key_shape(tmp_path, name) -> None:
    staged = tmp_path / "staged.db"
    _raw_tables(staged)
    con = sqlite3.connect(":memory:")
    con.isolation_level = None
    con.execute("ATTACH DATABASE ? AS inc", (str(staged),))
    expected = {r[0] for r in con.execute(_GROUPS[name]).fetchall()}
    con.execute(f'ATTACH DATABASE ? AS "{merge_mod._SCRATCH_SCHEMA}"', (str(tmp_path / "scr.db"),))
    n = merge_mod._materialise_rep(con, name, _GROUPS[name])
    got = {r[0] for r in con.execute(f"SELECT rep_id FROM {name}").fetchall()}
    assert got == expected and n == len(expected)
    assert con.execute(f"SELECT name FROM sqlite_temp_master WHERE name = '{name}'").fetchone() is None
    # and the unqualified name the joins use resolves to it
    assert con.execute(f"SELECT count(*) FROM {merge_mod._SCRATCH_SCHEMA}.{name}").fetchone()[0] == n


def test_a_statement_of_another_shape_is_refused_not_guessed(tmp_path) -> None:
    con = sqlite3.connect(":memory:")
    con.execute(f'ATTACH DATABASE ? AS "{merge_mod._SCRATCH_SCHEMA}"', (str(tmp_path / "scr.db"),))
    with pytest.raises(ValueError):
        merge_mod._materialise_rep(con, "rep_x", "SELECT MAX(id) FROM inc.keywords GROUP BY term")
    with pytest.raises(ValueError):
        merge_mod._split_group_keys("a, COALESCE(b,")


def _corpus(path: Path, *, first: int, kw: list[tuple[str, str | None]]) -> None:
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        src = Source(name="Wire", domain="wire.example")
        s.add(src)
        s.flush()
        for i in range(first, first + 3):
            a = Article(url=f"https://wire.example/{i}", canonical_url=f"https://wire.example/{i}",
                        source_id=src.id, title=f"t{i}", content=f"body {i}", hash=f"h{i:08d}", language="en")
            s.add(a)
            s.flush()
            s.add(ArticleLink(article_id=a.id, url="https://x.example/", normalized_url="x.example", position=0))
            s.add(ArticleLink(article_id=a.id, url="https://x.example/", normalized_url="x.example", position=0))
        for term, lang in kw:
            s.add(Keyword(term=term, normalized_term=term.lower(), language=lang))
        s.commit()
    engine.dispose()


def _encrypted(tmp_path: Path, name: str) -> Path:
    plain, enc = tmp_path / f"{name}-plain.db", tmp_path / f"{name}.db"
    _corpus(plain, first=0, kw=[("Petrol", "en"), ("Paris", None)])
    connect_mod.reencrypt_plain_to(plain, enc, _KEY)
    plain.unlink()
    return enc


def _dump(path: Path) -> dict:
    con = connect_mod.connect(path)
    try:
        return {
            t: sorted(map(tuple, con.execute(q).fetchall()))
            for t, q in {
                "keywords": "SELECT normalized_term, language FROM keywords",
                "links": "SELECT article_id, url, position FROM article_links",
                "articles": "SELECT hash FROM articles",
            }.items()
        }
    finally:
        con.close()


@pytest.fixture
def keyed():
    before = connect_mod.get_passphrase()
    connect_mod.set_passphrase(_KEY)
    try:
        yield
    finally:
        connect_mod.set_passphrase(before)


def test_a_merge_through_the_scratch_gives_the_same_corpus_and_leaves_nothing(tmp_path, keyed, monkeypatch) -> None:
    staged = tmp_path / "staged.db"
    _corpus(staged, first=100, kw=[("petrol", "en"), ("Lisbon", "pt"), ("lisbon", "pt"), ("Oslo", None)])
    ram_copy, scr_copy = _encrypted(tmp_path, "ram"), _encrypted(tmp_path, "scr")

    monkeypatch.setattr(merge_mod, "check_memory_for_encrypted_merge", lambda **kw: "memory")
    ram_counts, _ = merge_corpus(staged, ram_copy, _META)

    seen: dict = {}
    real_attach, real_mat = merge_mod._attach_scratch, merge_mod._materialise_rep_in_scratch

    def attach(con, working):  # noqa: ANN001, ANN202
        seen["path"] = real_attach(con, working)
        return seen["path"]

    def mat(con, name, sql):  # noqa: ANN001, ANN202
        n = real_mat(con, name, sql)
        seen.setdefault("names", []).append(name)
        seen["header"] = seen["path"].read_bytes()[:16]
        return n

    monkeypatch.setattr(merge_mod, "check_memory_for_encrypted_merge", lambda **kw: "scratch")
    monkeypatch.setattr(merge_mod, "_attach_scratch", attach)
    monkeypatch.setattr(merge_mod, "_materialise_rep_in_scratch", mat)
    scr_counts, _ = merge_corpus(staged, scr_copy, _META)

    assert sorted(seen["names"]) == ["rep_asr", "rep_keywords", "rep_links"]
    assert seen["header"] != b"SQLite format 3\x00", "the scratch is encrypted while it exists"
    assert seen["path"].parent == scr_copy.parent
    assert not list(tmp_path.glob("*oo-scratch*")), "the scratch is removed after the merge"
    for k in ("keywords", "article_links", "articles"):
        assert scr_counts[k] == ram_counts[k], k
    assert _dump(scr_copy) == _dump(ram_copy)


def test_a_failed_merge_removes_the_scratch_too(tmp_path, keyed, monkeypatch) -> None:
    staged = tmp_path / "staged.db"
    _corpus(staged, first=100, kw=[("Oslo", None)])
    copy = _encrypted(tmp_path, "w")
    monkeypatch.setattr(merge_mod, "check_memory_for_encrypted_merge", lambda **kw: "scratch")

    def boom(con, batch_id, results):  # noqa: ANN001, ANN202
        assert list(tmp_path.glob("*oo-scratch*")), "the scratch exists during the merge"
        raise RuntimeError("stop")

    monkeypatch.setattr(merge_mod, "_merge_keywords", boom)
    with pytest.raises(RuntimeError, match="stop"):
        merge_corpus(staged, copy, _META)
    assert not list(tmp_path.glob("*oo-scratch*"))


def test_a_plain_store_never_takes_the_scratch_path(tmp_path, monkeypatch) -> None:
    import src.database.maintenance as maintenance

    monkeypatch.setattr(maintenance, "_available_mb_now", lambda: 1.0)
    called: list = []
    monkeypatch.setattr(merge_mod, "_attach_scratch", lambda *a: called.append(a))
    working, staged = tmp_path / "w.db", tmp_path / "s.db"
    _corpus(working, first=0, kw=[("a", "en")])
    _corpus(staged, first=100, kw=[("b", "en")])
    merge_corpus(staged, working, _META)
    assert not called
