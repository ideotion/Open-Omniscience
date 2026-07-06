"""Omnibar folds downloaded-dump content search into the wiki group (#573-deferred).

A query now also searches the BODIES of downloaded Wikipedia dumps (via the dump FTS
index, when built) and returns them as labelled ``dump_items`` opening the LOCAL dump
reader — alongside the corpus/watched-page results. Honest empty state when no dump
index exists (never a fabricated result).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]


def _build_dump_index(data_dir: Path) -> None:
    """A tiny dump FTS index at <data_dir>/wiki_dumps/dump_index.sqlite (the real path
    the omnibar reads), built directly against the module's own schema."""
    from src.wiki import dump_index

    idx = data_dir / "wiki_dumps" / "dump_index.sqlite"
    conn = dump_index._open(idx)  # creates the FTS schema + parent dir
    try:
        conn.executemany(
            "INSERT INTO dump_pages(title, body, wiki, pageid) VALUES (?,?,?,?)",
            [
                ("Photosynthesis", "Plants use chlorophyll to convert sunlight to energy.", "en", 1),
                ("Mount Vesuvius", "A volcano near Naples known for lava and eruptions.", "en", 2),
            ],
        )
        conn.execute(
            "INSERT INTO dump_index_meta(wiki, pages, chars, indexed_at) VALUES (?,?,?,?)",
            ("en", 2, 100, "2026-07-06"),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def db():
    sa = pytest.importorskip("sqlalchemy")
    from sqlalchemy import text
    from sqlalchemy.orm import sessionmaker

    from src.database.fts import ensure_fts
    from src.database.models import Base, Source

    eng = sa.create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    s.add(Source(name="Web", domain="w.test"))
    s.commit()
    ensure_fts(s.get_bind())  # so search_ids works (returns [] with no wiki articles)
    s.execute(text("INSERT INTO article_fts(article_fts) VALUES ('rebuild')"))
    s.commit()
    try:
        yield s
    finally:
        s.close()


def test_wiki_group_includes_dump_content_hits(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _build_dump_index(tmp_path)
    from src.api.search_omni import _wiki_group

    g = _wiki_group(db, "chlorophyll")
    assert g["dump_available"] is True
    assert len(g["dump_items"]) == 1
    it = g["dump_items"][0]
    assert it["dump"] is True
    assert it["title"] == "Photosynthesis"
    assert it["wiki"] == "en"
    assert it["url"] == "/api/wiki/dumps/page?wiki=en&title=Photosynthesis"
    assert it["snippet"] and "chlorophyll" in it["snippet"].lower()
    assert "downloaded-dump content" in g["note"]


def test_dump_hit_url_encodes_titles_with_spaces(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    _build_dump_index(tmp_path)
    from src.api.search_omni import _wiki_group

    g = _wiki_group(db, "lava")
    it = next(i for i in g["dump_items"] if i["title"] == "Mount Vesuvius")
    assert it["url"] == "/api/wiki/dumps/page?wiki=en&title=Mount%20Vesuvius"


def test_dump_more_discloses_additional_matches(db, tmp_path, monkeypatch):
    """When the dump holds more matches than the omnibar shows, dump_more discloses it
    (the 'how much matched is disclosed' contract) without a fabricated total."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.wiki import dump_index

    idx = tmp_path / "wiki_dumps" / "dump_index.sqlite"
    conn = dump_index._open(idx)
    try:
        conn.executemany(
            "INSERT INTO dump_pages(title, body, wiki, pageid) VALUES (?,?,?,?)",
            [(f"Volcano {i}", "eruptions lava and magma volcano", "en", i) for i in range(6)],
        )
        conn.execute(
            "INSERT INTO dump_index_meta(wiki, pages, chars, indexed_at) VALUES (?,?,?,?)",
            ("en", 6, 100, "2026-07-06"),
        )
        conn.commit()
    finally:
        conn.close()
    from src.api.search_omni import _wiki_group

    g = _wiki_group(db, "volcano")
    assert len(g["dump_items"]) == 3  # only the first _PER_GROUP shown
    assert g["dump_more"] is True
    assert "more available" in g["note"]


def test_no_dump_index_is_honest_empty(db, tmp_path, monkeypatch):
    # A fresh data dir with NO dump index -> no dump results, never a fabricated one,
    # and the corpus/watched-page group is otherwise unaffected.
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    from src.api.search_omni import _wiki_group

    g = _wiki_group(db, "chlorophyll")
    assert g["dump_available"] is False
    assert g["dump_items"] == []
    assert "downloaded-dump content" not in g["note"]
    assert g["kind"] == "wiki"  # the group still returns normally


def test_dump_search_failure_degrades_gracefully(db, tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    import src.api.search_omni as omni

    def _boom(*a, **k):
        raise RuntimeError("dump index corrupt")

    monkeypatch.setattr("src.wiki.dump_index.search", _boom)
    g = omni._wiki_group(db, "anything")
    assert g["dump_available"] is False and g["dump_items"] == []


# ------------------------------- wiring --------------------------------------- #

def test_dump_search_is_wired_into_the_omnibar():
    src = (_ROOT / "src" / "api" / "search_omni.py").read_text(encoding="utf-8")
    assert "from src.wiki.dump_index import search as dump_search" in src
    assert "dump_items" in src and "/api/wiki/dumps/page" in src
