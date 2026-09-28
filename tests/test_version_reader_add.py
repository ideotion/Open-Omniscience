"""R52's «Add to corpus» in the ONE version reader: any listed Wikipedia version, either store.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's intent, stated with R52: «when a user searches a term present in wikipedia
articles (whether an article or the edit of an article, or a previous version of an
article), the user can incorporate that in its created corpus for analysis». The lane search
offers it for the texts it finds; the version reader lists a page's versions from BOTH
stores -- the tracker's ``wiki_revisions`` (Settings → Wikipedia, «Track now») and the
Wikipedia lane -- and the tracker's revisions are searched nowhere yet. So the reader is
where a tracked revision can be added at all, and this file pins the ways that could be
quietly false: a version stored under the page's own address (overwritten by the next
sync), a second copy of words the corpus already holds, a neighbour's text added in place
of the one asked for, a version without text "added" as an empty article, and a reader that
offers to add what the corpus already holds.

The component's behaviour is driven in node (``tests/version_reader_add_node_test.js``).
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base
from src.versioned.store import create_lane, dispose_all, lane_session

_ROOT = Path(__file__).resolve().parent.parent
_STATIC = _ROOT / "src" / "static"
_COMPONENT = (_STATIC / "ooversions.js").read_text(encoding="utf-8")

T0 = datetime(2025, 5, 1, 9, 30, tzinfo=UTC)


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    try:
        yield
    finally:
        dispose_all()


@pytest.fixture
def corpus(tmp_path):
    """A corpus of the test's own. The app's shared session outlives the test, and pages or
    articles committed there would meet every later test (``LESSONS.md``: endpoint tests
    override ``get_db`` and never seed ``SessionLocal``)."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'corpus.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, future=True)
    engine.dispose()


def _page(db, title: str, texts=None) -> tuple[int, dict[int, str]]:
    """A watched page and its tracked revisions: ``{revid: version id}``. ``texts`` maps a
    revid to its wikitext (``None``: the revision was tracked without its text)."""
    from src.database.models import WikiPage, WikiRevision

    texts = (
        texts
        if texts is not None
        else {
            10: f"'''{title}''' is a page.\n== History ==\nThe old line about the [[refinery]].",
            11: f"'''{title}''' is a page.\n== History ==\nThe new line about the refinery.",
            12: None,
        }
    )
    page = WikiPage(wiki="en", title=title)
    db.add(page)
    db.commit()
    for i, (revid, text) in enumerate(sorted(texts.items())):
        db.add(
            WikiRevision(
                page_id=page.id, revid=revid, timestamp=T0 + timedelta(days=i), full_text=text
            )
        )
    db.commit()
    ids = {r.revid: f"t{r.id}" for r in db.query(WikiRevision).filter_by(page_id=page.id).all()}
    return page.id, ids


def _lane_versions(title: str) -> dict[int, str]:
    """The lane's baseline (revid 20) and a later lane revision (revid 21, and 22 without
    its text) of the same page: ``{revid: version id}``."""
    from src.versioned.adapters.wiki import external_id_for
    from src.versioned.models import VersionedBaseline, VersionedEntity, VersionedRevision

    with lane_session("wiki") as lane:
        ent = VersionedEntity(external_id=external_id_for("en", title), title=title, language="en")
        lane.add(ent)
        lane.flush()
        base = VersionedBaseline(
            entity_id=ent.id,
            revision_ref="20",
            revised_at=T0 + timedelta(days=20),
            content_hash="h20",
            content=f"{title} is a page.\n== Output ==\nTwenty tonnes of saltpetre.",
        )
        rev = VersionedRevision(
            entity_id=ent.id,
            revision_ref="21",
            revised_at=T0 + timedelta(days=21),
            content_hash="h21",
            content=f"{title} is a page.\n== Output ==\nTwenty-one tonnes of saltpetre.",
        )
        bare = VersionedRevision(
            entity_id=ent.id,
            revision_ref="22",
            revised_at=T0 + timedelta(days=22),
            content_hash="h22",
            content=None,
        )
        lane.add_all([base, rev, bare])
        lane.flush()
        return {20: f"b{base.id}", 21: f"l{rev.id}", 22: f"l{bare.id}"}


# ---------------------------------------------------------------------------
# The add itself
# ---------------------------------------------------------------------------


def test_a_tracked_revision_becomes_its_own_article_under_its_own_address(lane, corpus):
    """«Track now»'s revisions are searched nowhere yet, so the reader is where one can be
    added. It is THAT revision: its own ``oldid`` address, its text without the markup,
    the date of its edit -- never the page's own address, which the next sync rewrites."""
    from src.database.models import Article, WikiPage
    from src.wiki.corpus import wiki_article_url, wiki_version_url
    from src.wiki.versions import add_version_to_corpus

    title = "Saltpetre works (tracked)"
    db = corpus()
    try:
        pid, ids = _page(db, title)
        page = db.get(WikiPage, pid)
        out = add_version_to_corpus(db, page, ids[10])
        assert out["status"] == "created"
        assert out["version"] == ids[10] and out["store"] == "tracker"
        art = db.get(Article, out["article_id"])
        assert art.canonical_url == wiki_version_url("en", title, 10)
        assert art.canonical_url != wiki_article_url("en", title), "never the page's own address"
        assert art.source_revision == "10"
        assert art.content == f"{title} is a page.\nHistory\nThe old line about the refinery."
        assert art.published_at.replace(tzinfo=UTC) == T0, "the edit's date, not today"
        again = add_version_to_corpus(db, page, ids[10])
        assert again["status"] == "exists" and again["article_id"] == art.id, "never a second copy"
        # The other revision is a second article beside it, not a replacement.
        newer = add_version_to_corpus(db, page, ids[11])
        assert newer["status"] == "created" and newer["article_id"] != art.id
    finally:
        db.close()


def test_a_lane_version_is_added_the_same_way_from_either_lane_table(lane, corpus):
    from src.database.models import Article, WikiPage
    from src.wiki.corpus import wiki_version_url
    from src.wiki.versions import add_version_to_corpus

    title = "Saltpetre works (lane)"
    lane_ids = _lane_versions(title)
    db = corpus()
    try:
        pid, _ids = _page(db, title)
        page = db.get(WikiPage, pid)
        base = add_version_to_corpus(db, page, lane_ids[20])
        rev = add_version_to_corpus(db, page, lane_ids[21])
        assert (base["status"], base["store"]) == ("created", "lane")
        assert (rev["status"], rev["store"]) == ("created", "lane")
        b, r = db.get(Article, base["article_id"]), db.get(Article, rev["article_id"])
        assert b.canonical_url == wiki_version_url("en", title, 20) and b.source_revision == "20"
        assert r.canonical_url == wiki_version_url("en", title, 21) and r.source_revision == "21"
        assert r.published_at.replace(tzinfo=UTC) == T0 + timedelta(days=21)
        assert "Twenty-one tonnes" in r.content and "Twenty-one" not in b.content
    finally:
        db.close()


def test_the_same_words_are_never_stored_twice(lane, corpus):
    """Two revisions whose edit changed only markup reduce to the same words: the second
    add names the article that already holds them (``Article.hash`` is unique, and a second
    row would count the words twice in every figure)."""
    from src.database.models import WikiPage
    from src.wiki.versions import add_version_to_corpus

    db = corpus()
    try:
        pid, ids = _page(
            db,
            "Salt works (markup only)",
            texts={30: "'''Salt''' works (markup only).", 31: "Salt works (markup only)."},
        )
        page = db.get(WikiPage, pid)
        first = add_version_to_corpus(db, page, ids[30])
        second = add_version_to_corpus(db, page, ids[31])
        assert first["status"] == "created"
        assert second["status"] == "same_text" and second["article_id"] == first["article_id"]
    finally:
        db.close()


def test_nothing_to_add_is_refused_by_name_and_never_swapped_for_a_neighbour(lane, corpus):
    from src.database.models import WikiPage
    from src.wiki.versions import NothingToAdd, add_version_to_corpus

    title = "Saltpetre works (refusals)"
    lane_ids = _lane_versions(title)
    db = corpus()
    try:
        pid, ids = _page(db, title)
        other, other_ids = _page(
            db, "Another page (refusals)", texts={40: "Another page's own text."}
        )
        page = db.get(WikiPage, pid)
        for bare in (ids[12], lane_ids[22]):
            with pytest.raises(NothingToAdd, match="text-not-held"):
                add_version_to_corpus(db, page, bare)
        with pytest.raises(LookupError):
            add_version_to_corpus(db, page, "t999999")
        with pytest.raises(LookupError):
            # Another page's revision is not this page's version, whatever its id says.
            add_version_to_corpus(db, page, other_ids[40])
        assert other != pid
    finally:
        db.close()


def test_only_a_listed_copy_can_be_added_when_both_stores_hold_one_edit(lane, corpus):
    """One edit held in both stores is listed once (the reader's dedup), so the id the
    reader does not show is not an addable version of the page either."""
    from src.database.models import WikiPage
    from src.wiki.versions import add_version_to_corpus, reader_payload

    title = "Saltpetre works (both stores)"
    lane_ids = _lane_versions(title)
    db = corpus()
    try:
        pid, ids = _page(db, title, texts={20: f"{title}: revision 20, as the tracker stored it."})
        page = db.get(WikiPage, pid)
        listed = {v["id"] for v in reader_payload(db, page)["versions"]}
        assert ids[20] in listed and lane_ids[20] not in listed
        with pytest.raises(LookupError):
            add_version_to_corpus(db, page, lane_ids[20])
        assert add_version_to_corpus(db, page, ids[20])["status"] == "created"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# What the reader is told
# ---------------------------------------------------------------------------


def test_the_payload_names_the_versions_the_corpus_already_holds(lane, corpus):
    """An earlier add (keyed on the version's own address) and the page's own article
    while its text is that revision: both are "already in your corpus", so the reader
    says so instead of offering an add that could only answer ``exists``/``same_text``."""
    from src.database.models import WikiPage
    from src.wiki.corpus import upsert_wiki_corpus_article
    from src.wiki.versions import add_version_to_corpus, reader_payload

    title = "Saltpetre works (already held)"
    db = corpus()
    try:
        pid, ids = _page(db, title)
        page = db.get(WikiPage, pid)
        assert reader_payload(db, page)["corpus_add"] == {"articles": {}}
        added = add_version_to_corpus(db, page, ids[10])["article_id"]
        current = upsert_wiki_corpus_article(
            db, wiki="en", title=title, plain="The page as the stream follows it.", revid=11
        )["article_id"]
        articles = reader_payload(db, page)["corpus_add"]["articles"]
        assert articles == {ids[10]: added, ids[11]: current}
        # Once the page's own article moves on to a revision the reader does not list, the
        # revision it held is no longer in the corpus, and the reader stops saying it is.
        upsert_wiki_corpus_article(db, wiki="en", title=title, plain="A later text.", revid=99)
        assert reader_payload(db, page)["corpus_add"]["articles"] == {ids[10]: added}
    finally:
        db.close()


def test_the_law_reader_is_offered_no_add():
    """Only a Wikipedia payload carries ``corpus_add``; the one component draws the button
    only where it is present, so a law reader never offers an add nothing implements."""
    law = (_ROOT / "src" / "law" / "versions.py").read_text(encoding="utf-8")
    assert "corpus_add" not in law
    assert 'if (!v || !st.d.corpus_add) return "";' in _COMPONENT


# ---------------------------------------------------------------------------
# The route
# ---------------------------------------------------------------------------


@pytest.fixture()
def client(corpus):
    """The app, reading and writing the test's own corpus."""
    from fastapi.testclient import TestClient

    from src.api.main import app
    from src.api.ratelimit import limiter
    from src.database.session import get_db

    def _db():
        d = corpus()
        try:
            yield d
        finally:
            d.close()

    limiter.reset()
    app.dependency_overrides[get_db] = _db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_the_route_adds_and_refuses_by_name(lane, corpus, client):
    from src.database.models import Article

    db = corpus()
    try:
        pid, ids = _page(db, "Saltpetre works (route)")
    finally:
        db.close()
    url = f"/api/wiki/pages/{pid}/versions/{{}}/add-to-corpus"
    made = client.post(url.format(ids[11]))
    assert made.status_code == 200, made.text
    body = made.json()
    assert body["status"] == "created" and body["version"] == ids[11]
    assert client.post(url.format(ids[11])).json()["status"] == "exists"
    bare = client.post(url.format(ids[12]))
    assert bare.status_code == 409 and bare.json()["detail"] == "text-not-held"
    gone = client.post(url.format("t999999"))
    assert gone.status_code == 404 and gone.json()["detail"] == "not-held"
    assert (
        client.post(f"/api/wiki/pages/999999/versions/{ids[11]}/add-to-corpus").status_code == 404
    )
    assert client.post(url.format("x1")).status_code == 422
    assert client.get(url.format(ids[11])).status_code == 405, "an add is never a GET"
    listed = client.get(f"/api/wiki/pages/{pid}/versions").json()
    assert listed["corpus_add"]["articles"] == {ids[11]: body["article_id"]}
    db = corpus()
    try:
        assert db.get(Article, body["article_id"]).source_revision == "11"
    finally:
        db.close()


# ---------------------------------------------------------------------------
# The component
# ---------------------------------------------------------------------------


def test_the_component_behaves():
    proc = subprocess.run(
        ["node", str(_ROOT / "tests" / "version_reader_add_node_test.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "all checks passed" in proc.stdout


def test_the_add_is_wired_through_the_one_delegated_listener():
    assert not re.search(r"\son[a-z]+=", _COMPONENT), (
        "inline handler in ooversions.js (row I's CSP ratchet)"
    )
    assert '"[data-ov],[data-ov-part],[data-ov-lang],[data-ov-add]"' in _COMPONENT
    assert "/add-to-corpus`" in _COMPONENT and '{ method: "POST" }' in _COMPONENT
    # The pickers row I's and row G's guards read are still there, wrapped, not replaced.
    for needle in ('data-ov="from"', 'data-ov="to"', 'data-ov="swap"'):
        assert needle in _COMPONENT, needle


def _table_words(name: str) -> list[str]:
    """The English words a lookup table hands to ``t()``: the literal ``t("...")`` gate
    cannot see them, so they are checked here."""
    at = _COMPONENT.index(f"const {name} = {{")
    body = _COMPONENT[at : _COMPONENT.index("};", at)]
    return re.findall(r':\s*"([^"]+)"', body)


def test_every_word_the_add_draws_is_keyed_in_all_twelve_locales():
    words = [
        "Add to corpus",
        "Open it in the reader",
        "From",
        "To",
        "Adds this exact version to your corpus as its own article.",
        "This version's text was not stored on this machine, so it cannot be added.",
        *_table_words("ADD_SAID"),
        *_table_words("ADD_REFUSED"),
    ]
    assert len(words) == 12, words
    for path in sorted((_STATIC / "locales").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for w in words:
            assert data.get(w), f"{path.name} lacks {w!r}"
