"""
Full-text search over downloaded Wikipedia dumps (item 3).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Proves a term in a downloaded dump BODY is findable by content search, that the index
is a disposable side-file (never the corpus DB / watched-page path), and that building
it does not disturb the existing article FTS.
"""

from __future__ import annotations

import bz2
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _build_multistream(base: Path, wiki: str = "zz") -> None:
    """A format-faithful multistream pair (bare <page> elements + offset index)."""
    base.mkdir(parents=True, exist_ok=True)
    s0 = bz2.compress(b"<mediawiki><siteinfo><sitename>T</sitename></siteinfo>")
    pages1 = (
        b"<page><title>Alpha</title><ns>0</ns><id>1</id>"
        b"<revision><id>11</id><text>Alpha is about photosynthesis in plants.</text>"
        b"</revision></page>"
        b"<page><title>Beta</title><ns>0</ns><id>2</id>"
        b"<revision><id>22</id><text>Beta discusses volcanic eruptions and lava.</text>"
        b"</revision></page>"
    )
    s1 = bz2.compress(pages1)
    pages2 = (
        b"<page><title>Gamma Ray</title><ns>0</ns><id>3</id>"
        b"<revision><id>33</id><text>Gamma rays are high-energy photons from space.</text>"
        b"</revision></page>"
        # A redirect (skipped) and a Talk-namespace page (ns filter drops it).
        b"<page><title>Redir</title><ns>0</ns><id>4</id>"
        b"<revision><id>44</id><text>#REDIRECT [[Alpha]]</text></revision></page>"
        b"<page><title>Talk:Alpha</title><ns>1</ns><id>5</id>"
        b"<revision><id>55</id><text>talkchatter about photosynthesis</text></revision></page>"
    )
    s2 = bz2.compress(pages2)
    tail = bz2.compress(b"</mediawiki>")
    off1, off2 = len(s0), len(s0) + len(s1)

    from src.wiki.dumps import dump_filename

    (base / dump_filename(wiki, "pages-articles-multistream")).write_bytes(s0 + s1 + s2 + tail)
    index = f"{off1}:1:Alpha\n{off1}:2:Beta\n{off2}:3:Gamma Ray\n{off2}:4:Redir\n{off2}:5:Talk:Alpha\n"
    (base / dump_filename(wiki, "pages-articles-multistream-index")).write_bytes(
        bz2.compress(index.encode())
    )


# --------------------------------------------------------------------------- #
# iter_pages — the streaming enumerator
# --------------------------------------------------------------------------- #
def test_iter_pages_streams_all_article_pages(tmp_path):
    from src.wiki.dumpread import iter_pages

    _build_multistream(tmp_path)
    pages = list(iter_pages("zz", base_dir=tmp_path))
    titles = {p["title"] for p in pages}
    # ns=0 only by default: the Talk: page (ns 1) is excluded; the redirect IS yielded
    # here (iter_pages does not judge redirects — the indexer skips them).
    assert titles == {"Alpha", "Beta", "Gamma Ray", "Redir"}
    alpha = next(p for p in pages if p["title"] == "Alpha")
    assert "photosynthesis" in alpha["wikitext"]
    assert alpha["pageid"] == 1


def test_iter_pages_namespace_and_limit(tmp_path):
    from src.wiki.dumpread import iter_pages

    _build_multistream(tmp_path)
    all_ns = list(iter_pages("zz", base_dir=tmp_path, namespaces=None))
    assert "Talk:Alpha" in {p["title"] for p in all_ns}  # every namespace
    limited = list(iter_pages("zz", base_dir=tmp_path, limit=2))
    assert len(limited) == 2


def test_iter_pages_absent_dump_yields_nothing(tmp_path):
    from src.wiki.dumpread import iter_pages

    assert list(iter_pages("qq", base_dir=tmp_path)) == []


# --------------------------------------------------------------------------- #
# build_index + search
# --------------------------------------------------------------------------- #
def test_build_then_search_finds_a_body_term(tmp_path):
    from src.wiki import dump_index as di

    _build_multistream(tmp_path)
    idx = tmp_path / "dump_index.sqlite"
    result = di.build_index("zz", base_dir=tmp_path, index_file=idx)
    # 3 articles indexed; the redirect + the Talk page are skipped.
    assert result["pages"] == 3
    assert result["cancelled"] is False

    hit = di.search("photosynthesis", index_file=idx)
    titles = [it["title"] for it in hit["items"]]
    assert "Alpha" in titles
    # snippet highlights the term and points at the dump edition.
    alpha = next(it for it in hit["items"] if it["title"] == "Alpha")
    assert alpha["wiki"] == "zz"
    assert "photosynthesis" in alpha["snippet"].lower()
    # A body-only term that is NOT any title is still found (true full-text, not titles).
    assert di.search("volcanic", index_file=idx)["items"][0]["title"] == "Beta"


def test_search_boolean_and_missing_index(tmp_path):
    from src.wiki import dump_index as di

    _build_multistream(tmp_path)
    idx = tmp_path / "dump_index.sqlite"
    di.build_index("zz", base_dir=tmp_path, index_file=idx)
    # Boolean syntax works (same parser as article search).
    assert di.search("photons AND space", index_file=idx)["items"][0]["title"] == "Gamma Ray"
    assert di.search("nonexistentterm", index_file=idx)["items"] == []
    # An unindexed store answers honestly, never crashes.
    empty = di.search("anything", index_file=tmp_path / "nope.sqlite")
    assert empty["items"] == [] and empty["reason"] == "no-index"


def test_reindex_is_idempotent_and_status_reports(tmp_path):
    from src.wiki import dump_index as di

    _build_multistream(tmp_path)
    idx = tmp_path / "dump_index.sqlite"
    di.build_index("zz", base_dir=tmp_path, index_file=idx)
    di.build_index("zz", base_dir=tmp_path, index_file=idx)  # replace=True by default
    # No duplicate rows after re-index (each of the 3 articles appears once).
    assert len(di.search("Alpha OR Beta OR Gamma", index_file=idx)["items"]) == 3
    status = di.index_status(index_file=idx)
    assert status["editions"][0]["wiki"] == "zz"
    assert status["editions"][0]["pages"] == 3
    assert status["total_pages"] == 3


def test_clear_index(tmp_path):
    from src.wiki import dump_index as di

    _build_multistream(tmp_path)
    idx = tmp_path / "dump_index.sqlite"
    di.build_index("zz", base_dir=tmp_path, index_file=idx)
    di.clear_index("zz", index_file=idx)
    assert di.search("photosynthesis", index_file=idx)["items"] == []
    assert di.index_status(index_file=idx)["editions"] == []


def test_cancel_does_not_mark_edition_complete(tmp_path):
    from src.wiki import dump_index as di

    _build_multistream(tmp_path)
    idx = tmp_path / "dump_index.sqlite"
    # Stop immediately: no page is written, and the edition is NOT recorded as indexed.
    result = di.build_index("zz", base_dir=tmp_path, index_file=idx, should_stop=lambda: True)
    assert result["cancelled"] is True
    assert di.index_status(index_file=idx)["editions"] == []


# --------------------------------------------------------------------------- #
# Endpoints + no-regression to article FTS
# --------------------------------------------------------------------------- #
@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_dump_index_endpoints_round_trip(client):
    from src.paths import data_dir
    from src.wiki import dump_index as di

    base = data_dir() / "wiki_dumps"
    _build_multistream(base, wiki="zy")
    try:
        # Unknown/not-downloaded edition -> honest 404.
        assert client.post("/api/wiki/dumps/index", json={"wiki": "qq"}).status_code == 404

        # Kick a background build, then poll to completion (tiny dump = fast).
        started = client.post("/api/wiki/dumps/index", json={"wiki": "zy"})
        assert started.status_code == 200
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            st = client.get("/api/wiki/dumps/index").json()
            if not st["build"]["running"]:
                break
            time.sleep(0.05)
        st = client.get("/api/wiki/dumps/index").json()
        assert st["build"]["state"] == "done"
        assert any(e["wiki"] == "zy" for e in st["editions"])

        # Content search finds a body term (not a title).
        found = client.get("/api/wiki/dumps/fts-search", params={"q": "photosynthesis"}).json()
        assert "Alpha" in [it["title"] for it in found["items"]]
        # Bad query -> 400.
        assert client.get("/api/wiki/dumps/fts-search", params={"q": " "}).status_code == 400

        # Clear it.
        assert client.request("DELETE", "/api/wiki/dumps/index", params={"wiki": "zy"}).status_code == 200
        assert client.get("/api/wiki/dumps/fts-search", params={"q": "photosynthesis"}).json()["items"] == []
    finally:
        di.clear_index(index_file=base / "dump_index.sqlite")
        for f in base.glob("zywiki-latest-*"):
            f.unlink()
        (base / "dump_index.sqlite").unlink(missing_ok=True)


def test_dump_index_does_not_touch_article_fts(client):
    """Building a dump index must not add anything to the article corpus / its FTS."""
    from src.database.session import SessionLocal
    from src.database.fts import search_ids
    from src.paths import data_dir
    from src.wiki import dump_index as di

    base = data_dir() / "wiki_dumps"
    _build_multistream(base, wiki="zx")
    try:
        di.build_index("zx", base_dir=base, index_file=base / "dump_index.sqlite")
        # The article FTS is unchanged: "photosynthesis" is dump-only, so an article
        # search must NOT return it (it never became an Article row).
        with SessionLocal() as s:
            assert search_ids(s, "photosynthesis") in (None, [])
    finally:
        di.clear_index(index_file=base / "dump_index.sqlite")
        for f in base.glob("zxwiki-latest-*"):
            f.unlink()
        (base / "dump_index.sqlite").unlink(missing_ok=True)
