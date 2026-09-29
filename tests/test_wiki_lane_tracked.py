"""R54: the versions «Track now» stores are searchable, indexed in the Wikipedia lane's own file.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The old page tracker keeps each page's stored versions in ``corpus.db``
(``wiki_revisions.full_text``); R54 (2026-09-29) makes them searchable from the one search box,
indexed in the lane's own ``wiki.db`` beside its other texts. The texts stay where they are.
The ways this could be quietly false, and so the spine of this file: a version the index never
learns about, one it keeps finding after the tracker dropped it, a newest version found twice
(once as the corpus article, once here), an older version re-derived on every scan, a locked
tracker that sets pages aside for good, and a hit that names a version the tracker cannot read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.database import fts_norm
from src.database.fts import ensure_fts
from src.database.models import Base, WikiPage, WikiRevision
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki import lane_search as S
from src.wiki.lane_models import WIKI_LANE_MODELS, WikiLaneDoc, WikiLaneIndexQueue, WikiLaneTracked

EDITION = "oo"
T0 = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
CAPS = fts_norm.ARABIC


#: The tracker's database for the running test: its own, in memory, so no test sees another's
#: pages (the process-wide corpus engine is shared by the whole suite).
_TRACKER = {"maker": None}


@pytest.fixture
def lane(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    create_lane("wiki")
    eng = create_engine(
        "sqlite:///:memory:", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(eng)
    ensure_fts(eng)
    _TRACKER["maker"] = sessionmaker(bind=eng, future=True)
    try:
        yield
    finally:
        _TRACKER["maker"] = None
        eng.dispose()
        dispose_all()


def _session():
    return lane_session("wiki")


def _corpus():
    return _TRACKER["maker"]()


_PAGES = iter(range(700_000, 800_000))


def _track(title, versions, *, pageid=None, latest=None):
    """A tracked page as the tracker keeps one: ``versions`` are ``(revid, text, at)``.

    ``latest`` is the revision the tracker recorded as the page's newest text (``None``: none)."""
    db = _corpus()
    try:
        page = WikiPage(wiki=EDITION, title=title, pageid=pageid or next(_PAGES), latest_text_revid=latest)
        db.add(page)
        db.flush()
        for revid, body, at in versions:
            db.add(WikiRevision(page_id=page.id, revid=revid, timestamp=at.replace(tzinfo=None), full_text=body))
        db.commit()
        return page.id
    finally:
        db.close()


def _add_version(page_id, revid, body, at, *, latest=None):
    db = _corpus()
    try:
        db.add(WikiRevision(page_id=page_id, revid=revid, timestamp=at.replace(tzinfo=None), full_text=body))
        if latest is not None:
            db.get(WikiPage, page_id).latest_text_revid = latest
        db.commit()
    finally:
        db.close()


def _pass(limit=50):
    """One scan, then one batch: the indexer's tracker phase without the clock."""
    db = _corpus()
    reader = S._TrackerReader(db)
    try:
        with _session() as lane_db:
            queued = S.scan_tracked(lane_db, reader)
        reader.release()
        with _session() as lane_db:
            out = S.index_tracked_batch(lane_db, reader, limit=limit, caps=CAPS)
        return queued, out
    finally:
        db.close()


def _docs():
    with _session() as db:
        return sorted(
            (d.source, d.revid, d.extent, d.successor_revid)
            for d in db.execute(select(WikiLaneDoc)).scalars()
        )


def _mirror():
    with _session() as db:
        return sorted(
            (m.owner_id, m.revid, m.successor_revid, m.has_text)
            for m in db.execute(select(WikiLaneTracked)).scalars()
        )


def _search(q, **kw):
    db = _corpus()
    try:
        with _session() as lane_db:
            return S.search(lane_db, q, corpus=db, **kw)
    finally:
        db.close()


def test_the_mirror_is_one_of_the_lanes_derived_tables():
    assert WikiLaneTracked in WIKI_LANE_MODELS


def test_an_older_version_is_found_by_the_lines_a_later_edit_removed_and_the_newest_in_full(lane):
    pid = _track(
        "Tracked page",
        [
            (3001, "Alphaword stays.\nOldword only in the first version.\n", T0),
            (3002, "Alphaword stays.\nMiddleword only in the second.\n", T0 + timedelta(days=1)),
            (3003, "Alphaword stays.\nNewestword is the latest.\n", T0 + timedelta(days=2)),
        ],
    )
    queued, out = _pass()
    assert queued == 1 and out.settled == 1 and out.failed == 0
    assert _docs() == [
        ("tracked", 3001, "dropped", 3002),
        ("tracked", 3002, "dropped", 3003),
        ("tracked", 3003, "full", None),
    ]
    hits = {h["revid"]: h for h in _search("Oldword")["items"]}
    assert set(hits) == {3001}
    assert hits[3001]["source"] == "tracked" and hits[3001]["owner_id"] == pid
    assert hits[3001]["which"] == "earlier" and hits[3001]["successor_revid"] == 3002
    assert "Oldword" in "".join(p["text"] for p in hits[3001]["snippet"] if p["hit"])
    newest = _search("Newestword")["items"]
    assert [(h["revid"], h["which"]) for h in newest] == [(3003, "newest")]
    assert _search("Alphaword")["total"] == 1, "a word every version kept is found once, in the newest"


def test_a_newest_version_the_corpus_article_already_is_not_indexed_twice(lane):
    from src.wiki.corpus import upsert_wiki_corpus_article

    _track(
        "Covered page",
        [(3101, "Firstword goes.\nKept line.\n", T0), (3102, "Kept line.\nCoveredword is the newest.\n", T0 + timedelta(days=1))],
        latest=3102,
    )
    db = _corpus()
    try:
        upsert_wiki_corpus_article(db, wiki=EDITION, title="Covered page", plain="Kept line.\nCoveredword is the newest.", revid=3102)
    finally:
        db.close()
    _pass()
    assert _docs() == [("tracked", 3101, "dropped", 3102)], "the corpus search finds the newest"
    assert _search("Coveredword")["total"] == 0


def test_a_new_version_makes_the_previous_newest_an_older_one_and_leaves_the_rest_alone(lane):
    pid = _track(
        "Growing page",
        [(3201, "Zeroword goes.\nKept.\n", T0), (3202, "Kept.\nFirstnewest lives.\n", T0 + timedelta(days=1))],
    )
    _pass()
    with _session() as db:
        first_doc = db.execute(select(WikiLaneDoc.id).where(WikiLaneDoc.revid == 3201)).scalar()
    assert _docs() == [("tracked", 3201, "dropped", 3202), ("tracked", 3202, "full", None)]
    _add_version(pid, 3203, "Kept.\nSecondnewest lives.\n", T0 + timedelta(days=2))
    queued, _ = _pass()
    assert queued == 1, "the tracker grew, so the page is queued again"
    assert _docs() == [
        ("tracked", 3201, "dropped", 3202),
        ("tracked", 3202, "dropped", 3203),
        ("tracked", 3203, "full", None),
    ]
    with _session() as db:
        assert db.execute(select(WikiLaneDoc.id).where(WikiLaneDoc.revid == 3201)).scalar() == first_doc, (
            "an older version whose successor did not change is not derived again"
        )
    assert _search("Firstnewest")["total"] == 1 and _search("Secondnewest")["total"] == 1


def test_a_second_scan_with_nothing_new_queues_nothing(lane):
    _track("Quiet page", [(3301, "Quietword one.\n", T0), (3302, "Quietword two.\n", T0 + timedelta(days=1))])
    assert _pass()[0] == 1
    queued, out = _pass()
    assert (queued, out.settled) == (0, 0)


def test_a_removed_version_and_a_removed_page_stop_being_found(lane):
    pid = _track(
        "Shrinking page",
        [(3401, "Goneword dies.\nKept.\n", T0), (3402, "Kept.\nMidword.\n", T0 + timedelta(days=1)), (3403, "Kept.\nEndword.\n", T0 + timedelta(days=2))],
    )
    _pass()
    assert _search("Goneword")["total"] == 1
    db = _corpus()
    try:
        db.delete(db.query(WikiRevision).filter_by(page_id=pid, revid=3401).one())
        db.commit()
    finally:
        db.close()
    _pass()
    assert _search("Goneword")["total"] == 0
    assert 3401 not in {m[1] for m in _mirror()}
    db = _corpus()
    try:
        db.delete(db.get(WikiPage, pid))
        db.commit()
    finally:
        db.close()
    queued, _ = _pass()
    assert queued == 1
    assert _docs() == [] and _mirror() == [], "the page went from the tracker, and from the index"


def test_a_version_the_tracker_stored_no_text_for_is_counted_and_never_indexed(lane):
    db = _corpus()
    try:
        page = WikiPage(wiki=EDITION, title="Textless page", pageid=next(_PAGES))
        db.add(page)
        db.flush()
        db.add(WikiRevision(page_id=page.id, revid=3501, timestamp=T0.replace(tzinfo=None), full_text=None))
        db.add(WikiRevision(page_id=page.id, revid=3502, timestamp=(T0 + timedelta(days=1)).replace(tzinfo=None), full_text="Solitaryword here."))
        db.commit()
        pid = page.id
    finally:
        db.close()
    _pass()
    assert _docs() == [("tracked", 3502, "full", None)]
    assert _mirror() == [(pid, 3501, None, 0), (pid, 3502, None, 1)], "counted, so a scan can compare"
    assert _pass()[0] == 0


def test_a_version_the_stream_also_holds_is_not_repeated_from_the_tracker(lane):
    from src.versioned.pipeline import ensure_entity
    from src.versioned.revisions import capture_baseline, record_revision
    from src.wiki.identity import external_id_for

    page_id = next(_PAGES)
    _track(
        "Both stores",
        [(3601, "Sharedgone here.\nKept.\n", T0), (3602, "Kept.\nTrackednewest.\n", T0 + timedelta(days=1))],
        pageid=page_id,
    )
    with _session() as db:
        entity = ensure_entity(db, external_id_for(EDITION, page_id), title="Both stores")
        db.flush()
        capture_baseline(db, entity, revision_ref="3601", text="Sharedgone here.\nKept.\n", revised_at=T0)
        record_revision(db, entity, revision_ref="3602", text="Kept.\nTrackednewest.\n", revised_at=T0 + timedelta(days=1))
    with _session() as db:
        S.index_batch(db, limit=100, caps=CAPS)
    _pass()
    assert [d for d in _docs() if d[0] == "tracked"] == [], "the stream's own entries are the ones found"
    assert _search("Sharedgone")["total"] == 1


def test_an_unreadable_text_sets_only_its_page_aside_and_a_locked_tracker_only_waits(lane, monkeypatch):
    good = _track("Readable tracked", [(3701, "Readableword.\n", T0)])
    bad = _track("Damaged tracked", [(3711, "Damagedword.\n", T0)])
    real = S._tracked_text

    def picky(reader, version):
        if version.revid == 3711:
            raise ValueError("cannot decompress")
        return real(reader, version)

    monkeypatch.setattr(S, "_tracked_text", picky)
    queued, out = _pass()
    assert queued == 2 and (out.settled, out.failed) == (2, 1)
    with _session() as db:
        rows = {ref: failed for ref, failed in db.execute(select(WikiLaneIndexQueue.ref, WikiLaneIndexQueue.failed_at).where(WikiLaneIndexQueue.kind == "tracked"))}
    assert rows == {bad: rows[bad]} and rows[bad] is not None, "only the damaged page stays, set aside"
    assert _search("Readableword")["total"] == 1 and _search("Damagedword")["total"] == 0
    assert _pass()[0] == 0, "a set-aside page is not queued again by every scan"
    assert good not in rows

    # A tracker that cannot be read is not a bad text: nothing is set aside, the page waits.
    monkeypatch.setattr(S, "_tracked_text", real)
    _add_version(good, 3702, "Readableword two.\n", T0 + timedelta(days=1))
    real_chain = S._tracked_chain

    def locked(reader, page_id):
        raise S._TrackerUnavailable("database is locked")

    monkeypatch.setattr(S, "_tracked_chain", locked)
    with _session() as db:
        db.execute(text("INSERT INTO wiki_lane_index_queue(kind, ref) VALUES ('tracked', :r) ON CONFLICT DO NOTHING"), {"r": good})
    dbc = _corpus()
    try:
        with _session() as lane_db:
            out = S.index_tracked_batch(lane_db, S._TrackerReader(dbc), caps=CAPS)
    finally:
        dbc.close()
    assert out.deferred and out.settled == 0
    with _session() as db:
        pending = db.execute(select(WikiLaneIndexQueue.failed_at).where(WikiLaneIndexQueue.kind == "tracked", WikiLaneIndexQueue.ref == good)).scalar_one()
    assert pending is None, "still pending, not set aside"
    monkeypatch.setattr(S, "_tracked_chain", real_chain)
    _pass()
    assert _search("Readableword")["total"] >= 1


def test_the_lanes_own_batch_leaves_the_trackers_queue_rows_alone(lane):
    _track("Own batch", [(3801, "Ownword.\n", T0)])
    with _session() as db:
        db.execute(text("INSERT INTO wiki_lane_index_queue(kind, ref) VALUES ('tracked', 1)"))
    with _session() as db:
        out = S.index_batch(db, limit=100, caps=CAPS)
    assert out.settled == 0, "the tracker's rows are the tracker phase's, not an unknown kind to drop"
    with _session() as db:
        assert db.execute(select(WikiLaneIndexQueue.kind)).scalars().all() == ["tracked"]


def test_the_indexer_reads_the_tracker_in_its_window_and_says_when_it_is_caught_up(lane):
    _track("Windowed", [(3901, "Windowword gone.\nKept.\n", T0), (3902, "Kept.\nWindownew.\n", T0 + timedelta(days=1))])
    indexer = S.LaneIndexer(
        lane_session=_session, budget=lambda: object(), tracker_session=_corpus, caps=lambda: CAPS,
    )
    report = indexer.index_for(30)
    assert indexer.state == S.STATE_CAUGHT_UP and report.settled == 1 and report.written == 2
    assert _search("Windowword")["total"] == 1
    again = indexer.index_for(30)
    assert again.settled == 0, "nothing changed: the probe skips the scan"
    assert S.LaneIndexer(lane_session=_session, budget=lambda: object(), caps=lambda: CAPS).index_for(5).settled == 0, (
        "without a tracker session the older sources behave as before"
    )


def test_a_new_index_and_a_segmenter_change_make_the_tracker_read_again(lane):
    _track("Rebuilt", [(4001, "Rebuiltword gone.\nKept.\n", T0), (4002, "Kept.\nRebuiltnew.\n", T0 + timedelta(days=1))])
    _pass()
    assert _mirror()
    with _session() as db:
        S.requeue_all(db)
    assert _mirror() == [], "what was read is forgotten, so the next scan queues the page again"
    queued, _ = _pass()
    assert queued == 1 and len(_docs()) == 2
    assert _search("Rebuiltword")["total"] == 1, "replaced, never doubled"


def test_the_coverage_line_counts_tracked_pages_and_their_editions(lane):
    _track("Covered by tracker", [(4101, "Coverword.\n", T0)])
    _track("Textless tracked", [])
    _pass()
    with _session() as db:
        cov = S.search_coverage(db)
    assert cov["tracked_pages"] == {"pages": 1, "editions": [{"edition": EDITION, "pages": 1}]}
    assert EDITION in cov["editions"]


def test_a_tracked_version_opens_and_is_added_to_the_corpus_as_that_version(lane):
    from src.api import wiki_lane_search as R
    from src.api.wiki_lane_search import AddVersion
    from src.database.models import Article
    from src.wiki.corpus import wiki_version_url

    pid = _track(
        "Openable page",
        [(4201, "Openword in the older text.\nKept.\n", T0 - timedelta(days=400)), (4202, "Kept.\nNewer text.\n", T0)],
    )
    _pass()
    db = _corpus()
    try:
        held = R.lane_version(source="tracked", owner_id=pid, revid=4201, db=db)
        assert held["which"] == "earlier" and held["newest_followed"] is False
        assert held["title"] == "Openable page" and held["revised_at"].startswith("2025-")
        assert held["url"] == wiki_version_url(EDITION, "Openable page", 4201)
        newest = R.lane_version(source="tracked", owner_id=pid, revid=4202, db=db)
        assert newest["which"] == "newest" and newest["newest_followed"] is False, "no article is it yet"
        out = R.add_to_corpus(AddVersion(source="tracked", owner_id=pid, revid=4201), db=db)
        assert out["status"] == "created" and out["source"] == "tracked"
        art = db.get(Article, out["article_id"])
        assert art.canonical_url == wiki_version_url(EDITION, "Openable page", 4201)
        assert art.source_revision == "4201" and "Openword" in art.content
        again = R.add_to_corpus(AddVersion(source="tracked", owner_id=pid, revid=4201), db=db)
        assert again["status"] == "exists" and again["article_id"] == art.id
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            R.lane_version(source="tracked", owner_id=pid, revid=999, db=db)
        assert exc.value.status_code == 404
    finally:
        db.close()


def test_a_tracked_newest_the_article_holds_is_named_as_followed(lane):
    from src.api import wiki_lane_search as R
    from src.wiki.corpus import upsert_wiki_corpus_article

    pid = _track("Followed newest", [(4301, "Old.\n", T0), (4302, "New text here.\n", T0 + timedelta(days=1))], latest=4302)
    db = _corpus()
    try:
        upsert_wiki_corpus_article(db, wiki=EDITION, title="Followed newest", plain="New text here.", revid=4302)
        _pass()
        held = R.lane_version(source="tracked", owner_id=pid, revid=4302, db=db)
        assert held["newest_followed"] is True
    finally:
        db.close()


def test_search_without_the_tracker_still_lists_a_tracked_hit(lane):
    _track("Listed anyway", [(4401, "Anywayword.\n", T0)])
    _pass()
    with _session() as db:
        out = S.search(db, "Anywayword")
    assert out["total"] == 1 and out["items"][0]["source"] == "tracked"
    assert out["items"][0]["snippet"] is None, "no tracker to read the text back from"
