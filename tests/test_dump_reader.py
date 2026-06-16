"""
Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later (full notice in sibling tests).

---

T14 — the offline dump reader (the elevated field-report-#4 gap: downloaded
dumps were files the app could not open) + the RULED language-limited dump
list ("Esperanto was fun but quite unnecessary"). The reader works on a
synthetic multistream dump built in-test: real bz2 streams, real index lines,
zero network — exactly the format Wikimedia publishes.
"""

from __future__ import annotations

import bz2
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _build_multistream(base: Path, wiki: str = "zz") -> dict:
    """A tiny but format-faithful multistream pair: header stream, two page
    streams (bare <page> elements, ≤100 pages each), closing stream, and the
    companion offset:pageid:title index."""
    s0 = bz2.compress(b"<mediawiki><siteinfo><sitename>T</sitename></siteinfo>")
    pages1 = (
        b"<page><title>Alpha</title><ns>0</ns><id>1</id>"
        b"<revision><id>11</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        b"<text>Alpha body \xc3\xa9text</text></revision></page>"
        b"<page><title>Beta</title><ns>0</ns><id>2</id>"
        b"<revision><id>22</id><text>Beta body</text></revision></page>"
    )
    s1 = bz2.compress(pages1)
    pages2 = (
        b"<page><title>Gamma Ray</title><ns>0</ns><id>3</id>"
        b"<revision><id>33</id><text>Gamma body</text></revision></page>"
    )
    s2 = bz2.compress(pages2)
    tail = bz2.compress(b"</mediawiki>")
    off1, off2 = len(s0), len(s0) + len(s1)

    from src.wiki.dumps import dump_filename

    (base / dump_filename(wiki, "pages-articles-multistream")).write_bytes(
        s0 + s1 + s2 + tail
    )
    index = f"{off1}:1:Alpha\n{off1}:2:Beta\n{off2}:3:Gamma Ray\n"
    (base / dump_filename(wiki, "pages-articles-multistream-index")).write_bytes(
        bz2.compress(index.encode())
    )
    return {"off1": off1, "off2": off2}


def test_find_page_exact_match(tmp_path):
    from src.wiki.dumpread import find_page

    _build_multistream(tmp_path)
    r = find_page("zz", "Beta", base_dir=tmp_path)
    assert r["found"] is True
    assert r["wikitext"] == "Beta body"
    assert r["match"] == "exact"
    assert r["pageid"] == 2
    assert "no network" in r["method"]
    assert "unrendered" in r["note"]


def test_find_page_second_stream_and_unicode(tmp_path):
    from src.wiki.dumpread import find_page

    _build_multistream(tmp_path)
    r = find_page("zz", "Gamma Ray", base_dir=tmp_path)
    assert r["found"] is True and r["wikitext"] == "Gamma body"
    r2 = find_page("zz", "Alpha", base_dir=tmp_path)
    assert r2["found"] is True and "étext" in r2["wikitext"]
    assert r2["rev_timestamp"] == "2026-01-01T00:00:00Z"


def test_find_page_case_insensitive_is_labelled(tmp_path):
    from src.wiki.dumpread import find_page

    _build_multistream(tmp_path)
    r = find_page("zz", "gamma ray", base_dir=tmp_path)
    assert r["found"] is True
    assert r["title"] == "Gamma Ray"
    assert r["match"] == "case-insensitive"  # said, never silent


def test_find_page_absent_title_reports_scan(tmp_path):
    from src.wiki.dumpread import find_page

    _build_multistream(tmp_path)
    r = find_page("zz", "Delta", base_dir=tmp_path)
    assert r["found"] is False
    assert r["reason"] == "title-not-in-index"
    assert r["index_lines_scanned"] == 3


def test_legacy_single_stream_reported_honestly(tmp_path):
    from src.wiki.dumpread import find_page
    from src.wiki.dumps import dump_filename

    (tmp_path / dump_filename("zz", "pages-articles")).write_bytes(b"x")
    r = find_page("zz", "Alpha", base_dir=tmp_path)
    assert r["found"] is False
    assert r["reason"] == "no-multistream-dump"
    assert r["legacy_file_present"] is True


def test_readable_wikis_requires_the_pair(tmp_path):
    from src.wiki.dumpread import readable_wikis
    from src.wiki.dumps import dump_filename

    _build_multistream(tmp_path, wiki="aa")
    # data file without its index -> not readable
    (tmp_path / dump_filename("bb", "pages-articles-multistream")).write_bytes(b"x")
    assert readable_wikis(tmp_path) == ["aa"]


def test_dump_page_endpoint_round_trip(client):
    from src.paths import data_dir

    base = data_dir() / "wiki_dumps"
    base.mkdir(parents=True, exist_ok=True)
    _build_multistream(base, wiki="zz")
    try:
        d = client.get("/api/wiki/dumps/page", params={"wiki": "zz", "title": "Alpha"}).json()
        assert d["found"] is True and d["wikitext"].startswith("Alpha body")
        ready = client.get("/api/wiki/dumps/readable").json()
        assert "zz" in ready["wikis"]
        assert client.get("/api/wiki/dumps/page", params={"wiki": "zz", "title": ""}).status_code == 400
    finally:
        for f in base.glob("zzwiki-latest-*"):
            f.unlink()


def test_dump_language_list_is_limited_to_app_languages(client):
    """The RULED limit: scope=dumps serves only the app's languages; the
    watched-pages picker (invariant #1) keeps the full curated list."""
    from src.wiki.languages import APP_LANGUAGE_CODES

    full = client.get("/api/wiki/languages").json()
    dumps = client.get("/api/wiki/languages", params={"scope": "dumps"}).json()
    full_codes = {lang["code"] for lang in full["languages"]}
    dump_codes = {lang["code"] for lang in dumps["languages"]}
    assert dump_codes <= APP_LANGUAGE_CODES
    assert dump_codes < full_codes
    assert "eo" in full_codes  # the full picker keeps Esperanto...
    assert "eo" not in dump_codes  # ...the heavy dump surface does not
    assert {"en", "fr", "ar", "zh"} <= dump_codes
    # Invariant #1 amendment (2026-06-16): the by-continent groups are GONE — the
    # endpoint emits ONE flat list (both scopes), so the dump scope no longer
    # carries a `groups` form to cross-check.
    assert "groups" not in dumps and "groups" not in full


def test_multistream_is_the_default_and_index_rides_along(client, tmp_path, monkeypatch):
    """Starting a dump download queues the data file AND its index."""
    import src.wiki.dumps as dumps_mod

    mgr = dumps_mod.DumpDownloadManager(
        base_dir=tmp_path,
        http_get=lambda u, h: (_ for _ in ()).throw(AssertionError("no network in tests")),
    )
    # Hold the queue closed so start() only QUEUES (no thread, no fetch).
    monkeypatch.setattr(mgr, "max_concurrent", 0)
    monkeypatch.setattr(dumps_mod, "get_manager", lambda: mgr)
    d = client.post("/api/wiki/dumps/start", json={"wiki": "fr"}).json()
    assert d["kind"] == "pages-articles-multistream"
    assert d["index_queued"] is True
    keys = {e["key"] for e in mgr.list()}
    assert "fr:pages-articles-multistream" in keys
    assert "fr:pages-articles-multistream-index" in keys
    assert d["url"].endswith("frwiki-latest-pages-articles-multistream.xml.bz2")
