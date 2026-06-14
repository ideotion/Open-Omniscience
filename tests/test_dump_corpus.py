"""Offline dump → corpus ingestion: downloaded Wikipedia pages become articles.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The living-source path (CLAUDE.md): a bounded list of titles is read from a
DOWNLOADED multistream dump (no network) and upserted into the corpus through the
one index_article hook, keyed on the canonical wiki URL so a later live sync of
the same page updates the SAME row. Built on a tiny, format-faithful in-test dump.
"""

from __future__ import annotations

import bz2
from pathlib import Path

from src.database.models import Article
from src.database.session import SessionLocal, init_db
from src.wiki.corpus import ingest_dump_pages, wiki_article_url


def _build_dump(base: Path, wiki: str = "zz") -> None:
    """A tiny, format-faithful multistream dump pair (header + page stream +
    closing) plus its offset:pageid:title index — real bz2, real offsets."""
    from src.wiki.dumps import dump_filename

    s0 = bz2.compress(b"<mediawiki><siteinfo><sitename>T</sitename></siteinfo>")
    pages = (
        b"<page><title>Alpha</title><ns>0</ns><id>1</id>"
        b"<revision><id>11</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        b"<text>Alpha covers elections in Kenya and protests in Paris during 2026.</text>"
        b"</revision></page>"
        b"<page><title>Beta</title><ns>0</ns><id>2</id>"
        b"<revision><id>22</id><text>Beta is about oil markets and prices in London.</text>"
        b"</revision></page>"
    )
    s1 = bz2.compress(pages)
    tail = bz2.compress(b"</mediawiki>")
    off1 = len(s0)
    (base / dump_filename(wiki, "pages-articles-multistream")).write_bytes(s0 + s1 + tail)
    index = f"{off1}:1:Alpha\n{off1}:2:Beta\n"
    (base / dump_filename(wiki, "pages-articles-multistream-index")).write_bytes(
        bz2.compress(index.encode())
    )


def test_ingest_dump_pages_creates_corpus_articles(tmp_path):
    init_db()
    _build_dump(tmp_path)
    s = SessionLocal()
    try:
        res = ingest_dump_pages(s, "zz", ["Alpha", "Beta", "Missing"], base_dir=tmp_path)
        assert res["created"] == 2
        assert res["skipped"] == 1  # "Missing" -> title-not-in-index
        # The article exists, keyed on the canonical wiki URL, with the dump text.
        art = (
            s.query(Article)
            .filter(Article.canonical_url == wiki_article_url("zz", "Alpha"))
            .one()
        )
        assert art.title == "Alpha"
        assert "elections" in art.content
        # Per-edition source, filterable forever.
        assert art.source.domain == "zz.wikipedia.org"
        # Idempotent: re-ingesting the unchanged page touches nothing.
        res2 = ingest_dump_pages(s, "zz", ["Alpha"], base_dir=tmp_path)
        assert res2["unchanged"] == 1
    finally:
        s.close()


def test_ingest_dump_pages_honest_when_no_dump(tmp_path):
    init_db()
    s = SessionLocal()
    try:
        # No dump built in tmp_path -> the reader says so; nothing is invented.
        res = ingest_dump_pages(s, "zz", ["Alpha"], base_dir=tmp_path)
        assert res["skipped"] == 1
        assert res["results"][0]["status"] == "no-multistream-dump"
    finally:
        s.close()
