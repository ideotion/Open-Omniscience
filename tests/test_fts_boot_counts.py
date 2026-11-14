"""The boot compares the article and full-text counts (R412, OPEN_QUEUE 2026-10-27 item 9).

``ensure_fts`` used to read ANY document in the index as settled, so a partial index (a missing head, a hole in the middle,
a missing tail) or one holding a document with no article was skipped at every boot. ``fts_status`` could infer only a
missing TAIL, from the ends. The boot now counts both sides (one count each, following the number of rows and never their
text) and rebuilds when they differ. A healthy store, empty texts included, counts equal and is never rebuilt, so the
comparison cannot turn into a rebuild at every boot (the P0.4 slow unlock).
"""

from __future__ import annotations

from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from src.database import fts
from src.database.models import Article
from tests.test_repair_search_index import (
    _EXPORT_ARTICLES,
    _export_findable,
    _export_indexed,
    _export_store,
)


def _index_only(eng, ids) -> None:
    """Empty the index, then index only ``ids``: a state no app writer leaves, which a torn file copy can."""
    with eng.begin() as c:
        c.execute(text("INSERT INTO article_fts(article_fts) VALUES ('delete-all')"))
        c.execute(text("DELETE FROM article_fts_norm"))
        fts.index_articles(c, list(ids))


def _healed(eng) -> None:
    assert fts.ensure_fts(eng) == "rebuilt"
    assert (_export_indexed(eng), _export_findable(eng)) == (_EXPORT_ARTICLES, _EXPORT_ARTICLES)
    assert fts.ensure_fts(eng) == "skipped", "a whole index is not rebuilt again"


def test_a_hole_in_the_middle_is_rebuilt_at_boot():
    eng = _export_store()
    _index_only(eng, [i for i in range(1, _EXPORT_ARTICLES + 1) if not 15 <= i <= 20])
    _healed(eng)


def test_a_missing_head_is_rebuilt_at_boot_though_the_ends_agree():
    """The case the ends cannot see: the highest document id is the highest article id."""
    eng = _export_store()
    _index_only(eng, range(_EXPORT_ARTICLES // 2, _EXPORT_ARTICLES + 1))
    with sessionmaker(bind=eng, future=True)() as s:
        assert fts.fts_status(s)["index_state"] != "partial (inferred)", (
            "precondition: the ends agree"
        )
    _healed(eng)


def test_a_document_with_no_article_is_rebuilt_at_boot():
    eng = _export_store()
    with eng.begin() as c:
        c.execute(
            text("INSERT INTO article_fts(rowid, title, content) VALUES (99999, 'gone', 'gone')")
        )
    assert _export_indexed(eng) == _EXPORT_ARTICLES + 1
    _healed(eng)


def test_empty_texts_count_as_documents_so_a_healthy_store_is_never_rebuilt():
    """Every article is one document, an empty title and content included: else a store with one would rebuild at every boot."""
    eng = _export_store()
    with sessionmaker(bind=eng, future=True)() as s:
        s.add(
            Article(
                url="e",
                canonical_url="e",
                source_id=1,
                title="",
                content="",
                hash="he",
                language="en",
            )
        )
        s.commit()
    assert fts.ensure_fts(eng) == "skipped"
    assert fts.ensure_fts(eng, rebuild="always") == "rebuilt"
    assert fts.ensure_fts(eng) == "skipped", "a full rebuild leaves the two counts equal"


def test_a_steady_boot_counts_once_and_reads_no_text():
    eng = _export_store()
    seen: list[str] = []
    event.listen(eng, "before_cursor_execute", lambda _c, _cur, stmt, *_a: seen.append(stmt))
    assert fts.ensure_fts(eng) == "skipped"
    counts = [s for s in seen if "count(" in s.lower()]
    assert counts == [
        "SELECT (SELECT count(*) FROM articles), (SELECT count(*) FROM article_fts_docsize)"
    ]
    assert not [s for s in seen if fts.REBUILD_MARK in s or "content FROM articles" in s]
