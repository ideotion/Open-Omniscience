"""The version anchor: which revision an article's stored text came from.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A VERSIONED SOURCE is an Article whose text is amendable, and the standing ruling
is that its audit trail is only meaningful if an analytic result can name the
version it was computed against. ``Article.source_revision`` is that anchor.

Every guard here is written against the direction that would be DISHONEST: a
revision beside text it did not produce, a NULL rendered as a version, an
overwrite of a recorded anchor, or a link into a history this machine does not
hold.
"""

from __future__ import annotations

import bz2
from pathlib import Path

import pytest

from src.database.models import Article, Source, WikiPage
from src.database.session import SessionLocal, init_db
from src.wiki.corpus import (
    ingest_dump_pages,
    upsert_wiki_corpus_article,
    wiki_article_url,
    wiki_page_ref,
)


# --------------------------------------------------------------------------- #
# the anchor travels with the text it describes
# --------------------------------------------------------------------------- #


def _upsert(session, *, title, plain, revid):
    return upsert_wiki_corpus_article(
        session, wiki="zz", title=title, plain=plain, revid=revid
    )


def _article(session, title):
    return (
        session.query(Article)
        .filter(Article.canonical_url == wiki_article_url("zz", title))
        .one()
    )


def test_the_anchor_is_recorded_with_the_text_it_describes():
    init_db()
    s = SessionLocal()
    try:
        _upsert(s, title="Anchor A", plain="Elections in Kenya during 2026.", revid=101)
        assert _article(s, "Anchor A").source_revision == "101"
    finally:
        s.close()


def test_new_text_replaces_the_anchor():
    init_db()
    s = SessionLocal()
    try:
        _upsert(s, title="Anchor B", plain="First body about oil markets.", revid=201)
        _upsert(s, title="Anchor B", plain="Second body about wheat markets.", revid=202)
        assert _article(s, "Anchor B").source_revision == "202"
    finally:
        s.close()


def test_new_text_with_no_revision_clears_the_anchor_rather_than_keeping_a_stale_one():
    """The negative-space twin of the test above, and the one that matters.

    Keeping the previous revid beside DIFFERENT text would publish a version that
    provably did not produce that body -- a fabricated anchor, which is worse than
    an honest absence, because a reader can check an absence and cannot check a
    plausible wrong number.
    """
    init_db()
    s = SessionLocal()
    try:
        _upsert(s, title="Anchor C", plain="Body one about protests in Paris.", revid=301)
        assert _article(s, "Anchor C").source_revision == "301"
        _upsert(s, title="Anchor C", plain="Body two about floods in Kenya.", revid=None)
        assert _article(s, "Anchor C").source_revision is None
    finally:
        s.close()


def test_unchanged_text_fills_a_missing_anchor_but_never_overwrites_a_recorded_one():
    """Two directions, one branch. Filling a NULL is information gain about text we
    already hold; replacing a recorded revision from an IDENTICAL body would
    silently rewrite what a past analysis was anchored to, and two revisions can
    legitimately strip to the same text."""
    init_db()
    s = SessionLocal()
    try:
        body = "Stable body about elections in Kenya."
        _upsert(s, title="Anchor D", plain=body, revid=None)
        assert _article(s, "Anchor D").source_revision is None

        out = _upsert(s, title="Anchor D", plain=body, revid=401)
        assert out["status"] == "unchanged"
        assert _article(s, "Anchor D").source_revision == "401"

        # A second, different revid over the SAME body must not displace it.
        _upsert(s, title="Anchor D", plain=body, revid=999)
        assert _article(s, "Anchor D").source_revision == "401"
    finally:
        s.close()


def test_an_article_from_no_versioned_source_has_no_anchor():
    """NULL means "came from no versioned source", not "revision unknown" -- so a
    plain scraped article must never acquire one."""
    init_db()
    s = SessionLocal()
    try:
        src = Source(name="Example", domain="example.org")
        s.add(src)
        s.flush()
        a = Article(url="https://example.org/x", canonical_url="https://example.org/x",
                    source_id=src.id, title="Plain", content="A news body.",
                    hash="deadbeef-version-anchor")
        s.add(a)
        s.commit()
        assert s.query(Article).filter_by(hash="deadbeef-version-anchor").one().source_revision is None
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# the offline dump path carries it too -- it is the path with no WikiPage row
# --------------------------------------------------------------------------- #


def _build_dump(base: Path, wiki: str = "zy") -> None:
    from src.wiki.dumps import dump_filename

    s0 = bz2.compress(b"<mediawiki><siteinfo><sitename>T</sitename></siteinfo>")
    pages = (
        b"<page><title>Gamma</title><ns>0</ns><id>1</id>"
        b"<revision><id>7654</id><timestamp>2026-01-01T00:00:00Z</timestamp>"
        b"<text>Gamma covers elections in Kenya and protests in Paris during 2026.</text>"
        b"</revision></page>"
    )
    s1 = bz2.compress(pages)
    tail = bz2.compress(b"</mediawiki>")
    off1 = len(s0)
    (base / dump_filename(wiki, "pages-articles-multistream")).write_bytes(s0 + s1 + tail)
    (base / dump_filename(wiki, "pages-articles-multistream-index")).write_bytes(
        bz2.compress(f"{off1}:1:Gamma\n".encode())
    )


def test_a_dump_ingested_article_carries_the_dumps_revision(tmp_path):
    """The dump path is the one with NO WikiPage row, so before this column the
    revision it read was returned to its caller and dropped: nothing on disk could
    say which version the corpus text came from."""
    init_db()
    _build_dump(tmp_path)
    s = SessionLocal()
    try:
        res = ingest_dump_pages(s, "zy", ["Gamma"], base_dir=tmp_path)
        assert res["created"] == 1
        art = (
            s.query(Article)
            .filter(Article.canonical_url == wiki_article_url("zy", "Gamma"))
            .one()
        )
        assert art.source_revision == "7654"
        # And no WikiPage exists for it -- which is exactly why the article-level
        # anchor is the only place this fact could live.
        assert s.query(WikiPage).filter_by(wiki="zy", title="Gamma").first() is None
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# the URL <-> (wiki, title) inverse, verified by round trip
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "wiki,title",
    [
        ("en", "Climate change"),
        ("fr", "Élection présidentielle"),
        ("zh", "中国"),
        # The shapes a hand-written character rule gets wrong. The first draft of
        # wiki_page_ref refused every slash-bearing title, which would have
        # withheld the history link from real pages while looking correct.
        ("en", "A/B testing"),
        ("en", "OS/2"),
        ("en", "100% renewable"),
        ("en", "C++"),
    ],
)
def test_the_url_inverse_round_trips(wiki, title):
    assert wiki_page_ref(wiki_article_url(wiki, title)) == (wiki, title)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/x",
        "http://en.wikipedia.org/wiki/X",          # not https: not a URL we mint
        "https://en.evil.org/wiki/X",              # not the wikipedia host
        "https://en.wikipedia.org/wiki/",          # no title
        "https://en.wikipedia.org/wiki/A%2FB",     # over-escaped: we never mint this
        "https://en.wikipedia.org/wiki/100%",      # a stray percent
        "https://en.wikipedia.org/w/index.php?title=X",
        "",
    ],
)
def test_the_url_inverse_refuses_anything_this_app_would_not_have_minted(url):
    assert wiki_page_ref(url) is None


# --------------------------------------------------------------------------- #
# the reader: the version is shown, an absence is not dressed as one
# --------------------------------------------------------------------------- #


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def _seed_wiki_article(session, *, title, revid, with_page: bool):
    upsert_wiki_corpus_article(
        session, wiki="zw", title=title, plain=f"{title} covers elections in Kenya.", revid=revid
    )
    art = (
        session.query(Article)
        .filter(Article.canonical_url == wiki_article_url("zw", title))
        .one()
    )
    if with_page:
        session.add(WikiPage(wiki="zw", title=title, watched=True))
        session.commit()
    return art


def test_the_reader_states_the_version_and_what_it_claims(client):
    init_db()
    s = SessionLocal()
    try:
        art = _seed_wiki_article(s, title="Reader One", revid=5150, with_page=False)
        aid = art.id
    finally:
        s.close()
    html = client.get(f"/api/articles/{aid}/view").text
    assert "5150" in html
    assert "Version (this stored text)" in html
    # The claim is narrow and VISIBLE, not behind a hover: a later edit is not
    # reflected until the text is re-synced, and this is not "the newest revision".
    assert "does not claim to be the newest revision" in html


def test_the_reader_offers_the_local_history_only_when_this_machine_holds_one(client):
    """A link to a history that does not exist here is the dead-end shape: it looks
    like a capability and answers nothing. A dump-ingested page has no tracked
    revisions and says so instead."""
    init_db()
    s = SessionLocal()
    try:
        with_page = _seed_wiki_article(s, title="Reader Tracked", revid=11, with_page=True)
        without = _seed_wiki_article(s, title="Reader Untracked", revid=22, with_page=False)
        page_id = s.query(WikiPage.id).filter_by(wiki="zw", title="Reader Tracked").scalar()
        a_with, a_without = with_page.id, without.id
    finally:
        s.close()

    tracked = client.get(f"/api/articles/{a_with}/view").text
    assert f"/?wikitc={page_id}" in tracked

    untracked = client.get(f"/api/articles/{a_without}/view").text
    assert "wikitc=" not in untracked
    assert "no tracked revisions stored here" in untracked


def test_a_plain_article_gets_no_version_row_at_all(client):
    """The negative twin: NULL must not render as a version, an "unknown", or an
    empty row -- a news article has no revision and the question does not apply."""
    init_db()
    s = SessionLocal()
    try:
        src = (
            s.query(Source).filter_by(domain="example.org").first()
            or Source(name="Example", domain="example.org")
        )
        s.add(src)
        s.flush()
        a = Article(
            url="https://example.org/plain-reader",
            canonical_url="https://example.org/plain-reader",
            source_id=src.id,
            title="Plain reader", content="A news body.", hash="hash-plain-reader-anchor",
        )
        s.add(a)
        s.commit()
        aid = a.id
    finally:
        s.close()
    html = client.get(f"/api/articles/{aid}/view").text
    assert "Version (this stored text)" not in html
    assert "does not claim to be the newest revision" not in html


# --------------------------------------------------------------------------- #
# the deep link, and the tracked-changes view it opens
# --------------------------------------------------------------------------- #


def test_the_reader_deep_link_has_a_handler_that_opens_the_tracked_changes_view():
    """The reader is a STANDALONE page, so a link into the SPA is only a capability
    if the SPA hydrates it. Asserting the href alone would pass with no handler --
    the dead-end shape one layer up."""
    from tests.js_source_helper import app_js, function_body, strip_comments

    body = strip_comments(function_body(app_js(), "_hydrateWikiTrackedChanges"))
    assert 'get("wikitc")' in body
    assert "openWikiTC(" in body


def test_the_deep_link_selects_the_subtab_through_the_component():
    """Invariant #18: the component owns the strip's visible state, so a bare
    showSetCat would leave .active / aria-selected out of step."""
    from tests.js_source_helper import app_js, function_body, strip_comments

    body = strip_comments(function_body(app_js(), "_hydrateWikiTrackedChanges"))
    assert "_setSubtabs.select(" in body


def test_the_tracked_changes_view_behaves(tmp_path):
    """The view itself, DRIVEN rather than read.

    Its first guard here was a source check that ``d.page.title`` appears in
    ``loadWikiTC`` -- and it survived the mutation that disables the branch,
    because the identifier goes on sitting inside dead code. A view's honesty is
    in what it does with LESS than a full answer (an empty page, a windowed slice,
    a revision with no diff, a caller that knows only an id), and none of that is
    provable from source, so the assertions live in
    ``tests/wiki_tracked_changes_node_test.js`` and this is its driver.
    """
    import pathlib
    import subprocess

    root = pathlib.Path(__file__).resolve().parents[1]
    r = subprocess.run(
        ["node", str(root / "tests" / "wiki_tracked_changes_node_test.js")],
        capture_output=True, text=True, cwd=str(root),
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "all assertions passed" in r.stdout


# --------------------------------------------------------------------------- #
# the merge: a column added after an explicit allowlist is silently dropped
# --------------------------------------------------------------------------- #


def test_the_merge_carries_the_version_anchor():
    """The recorded 2026-08-03 defect: an explicit column list drops every column
    added after it, and a nullable one arrives as a plausible NULL nothing reports.
    Asserted against the real INSERT's parsed column list, not by reading it."""
    import ast
    import pathlib

    src = pathlib.Path("src/backup/merge.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name == "_merge_articles"):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if "INSERT INTO articles" in sub.value:
                    found = True
        # The statement is built from adjacent literals the parser folds, so join
        # every string constant in the function and require BOTH halves.
        joined = "".join(
            c.value for c in ast.walk(node)
            if isinstance(c, ast.Constant) and isinstance(c.value, str)
        )
        assert "source_revision)" in joined or " source_revision," in joined, (
            "the articles INSERT does not carry source_revision"
        )
        assert "i.source_revision" in joined, "the SELECT half does not carry it either"
    assert found, "could not find the articles INSERT to check"


def test_the_version_anchor_is_declared_adoptable_or_not_but_never_forgotten():
    """The completeness pair exists so a new column is a loud choice rather than a
    quiet loss. This pins WHICH side it landed on, so flipping it is deliberate."""
    from src.backup.merge import _ADOPTABLE_ARTICLE_COLUMNS, _NOT_ADOPTABLE_ARTICLE_COLUMNS

    adoptable = {c for _a, cols in _ADOPTABLE_ARTICLE_COLUMNS for c in cols}
    assert "source_revision" in adoptable
    assert "source_revision" not in _NOT_ADOPTABLE_ARTICLE_COLUMNS


def test_the_boot_self_heal_declares_the_column():
    """Not every install runs alembic, and create_all never ALTERs an existing
    table -- without the self-heal a pre-column store raises "no such column" on
    the first wiki sync."""
    from src.database.maintenance import SELF_HEALED_COLUMNS

    assert "source_revision" in SELF_HEALED_COLUMNS["articles"]
