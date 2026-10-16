"""R52's lane search: held Wikipedia texts found from the one search box, added as THAT version.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The maintainer's intent, stated with the ruling: «when a user searches a term present in
wikipedia articles (whether an article or the edit of an article, or a previous version of
an article), the user can incorporate that in its created corpus for analysis». So the spine
of this file is the ways that could be quietly false: a held text the index never learns
about, a text it keeps finding after the lane stopped holding it, a hit that names the wrong
version, a count that is really a limit, a fault that half-writes a page, and an «Add to
corpus» that stores a different text than the one found -- or stores it twice.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import OperationalError

from src.database import fts_norm
from src.versioned.pipeline import ensure_entity
from src.versioned.revisions import capture_baseline, record_revision
from src.versioned.store import create_lane, dispose_all, lane_path, lane_session
from src.wiki import lane_search as S
from src.wiki.identity import external_id_for
from src.wiki.lane_models import WikiLaneDoc, WikiLaneIndexQueue, WikiLaneIndexState, WikiWarmPage
from src.wiki.tiers import budget_state

EDITION = "oo"
T0 = datetime(2026, 3, 11, 12, 0, tzinfo=UTC)
#: No segmenter, so every machine the suite runs on indexes these texts the same way.
CAPS = fts_norm.ARABIC


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
def no_lane(tmp_path, monkeypatch):
    """A machine where the lane has never run: no file at all."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    monkeypatch.setenv("OO_NO_SCHEDULER", "1")
    dispose_all()
    try:
        yield
    finally:
        dispose_all()


def _session():
    return lane_session("wiki")


_PAGES = iter(range(5000, 10_000_000))


def _warm(*, title, latest, previous=None, page_id=None):
    """A WARM row as WARM keeps one. ``latest``/``previous`` are ``(revid, wikitext, at)``."""
    with _session() as db:
        row = WikiWarmPage(edition=EDITION, page_id=page_id or next(_PAGES), title=title)
        if previous is not None:
            row.previous_revid, row.previous_text, row.previous_revised_at = previous
        row.latest_revid, row.latest_text, row.latest_revised_at = latest
        db.add(row)
        db.flush()
        return row.id


def _refetch(row_id, latest):
    """WARM's third fetch (Q710): the latest moves to previous and the older text is dropped."""
    with _session() as db:
        row = db.get(WikiWarmPage, row_id)
        row.previous_revid, row.previous_text = row.latest_revid, row.latest_text
        row.previous_revised_at = row.latest_revised_at
        row.latest_revid, row.latest_text, row.latest_revised_at = latest


def _hot(versions, *, title="Followed page", page_id=None):
    """A followed page: the first version its baseline, the rest revisions. Returns its id."""
    pid = page_id or next(_PAGES)
    with _session() as db:
        entity = ensure_entity(db, external_id_for(EDITION, pid), title=title)
        db.flush()
        (revid, body, at), rest = versions[0], versions[1:]
        capture_baseline(db, entity, revision_ref=str(revid), text=body, revised_at=at)
        for revid, body, at in rest:
            record_revision(db, entity, revision_ref=str(revid), text=body, revised_at=at)
        return entity.id


def _add_revision(entity_id, revid, body, at):
    from src.versioned.models import VersionedEntity

    with _session() as db:
        record_revision(db, db.get(VersionedEntity, entity_id), revision_ref=str(revid), text=body, revised_at=at)


def _index(limit=1000, caps=CAPS):
    with _session() as db:
        return S.index_batch(db, limit=limit, caps=caps)


def _search(q, **kw):
    with _session() as db:
        return S.search(db, q, **kw)


def _queue():
    with _session() as db:
        return sorted(
            (k, r, f is not None)
            for k, r, f in db.execute(
                select(WikiLaneIndexQueue.kind, WikiLaneIndexQueue.ref, WikiLaneIndexQueue.failed_at)
            ).all()
        )


def _docs():
    with _session() as db:
        return sorted(
            (d.source, d.revid, d.extent, d.successor_revid)
            for d in db.execute(select(WikiLaneDoc)).scalars()
        )


def _hits(q):
    return [(i["source"], i["revid"], i["extent"]) for i in _search(q, snippets=False)["items"]]


# --------------------------------------------------------------------------- #
# the schema: the index exists from the lane's creation, and an older lane gets it
# --------------------------------------------------------------------------- #
def test_the_index_and_its_feeders_are_created_with_the_lane(lane):
    with _session() as db:
        names = {r[0] for r in db.execute(text("SELECT name FROM sqlite_master"))}
    assert S.FTS_TABLE in names
    assert set(S._TRIGGERS) <= names
    with _session() as db:
        assert S.index_available(db) is None
    from src.versioned.store import lane_engine

    assert S.ensure_index(lane_engine("wiki")) == "ready", "idempotent, and cheap when present"


def test_a_lane_file_an_earlier_build_wrote_gets_the_index_with_every_held_text_queued(lane):
    warm_id = _warm(title="Kept page", latest=(11, "Kept words here.", T0))
    eid = _hot([(21, "one\n", T0), (22, "two\n", T0 + timedelta(hours=1))])
    # What a 0.4 lane file looks like: the texts, and no index, feeders or queue at all.
    with _session() as db:
        db.execute(text("DROP TABLE wiki_lane_fts"))
        for name in S._TRIGGERS:
            db.execute(text(f'DROP TRIGGER "{name}"'))
        db.execute(text("DELETE FROM wiki_lane_index_queue"))
    dispose_all()
    create_lane("wiki")  # what the lane's own open runs
    with _session() as db:
        from src.versioned.models import VersionedRevision

        rev_ids = [r for (r,) in db.execute(select(VersionedRevision.id).where(VersionedRevision.entity_id == eid))]
    assert _queue() == sorted([("warm", warm_id, False)] + [("hot", r, False) for r in rev_ids])
    _index()
    assert _hits("Kept") == [("warm", 11, "full")]


def test_a_stale_format_is_rebuilt_rather_than_trusted(lane):
    _warm(title="Format page", latest=(31, "Format words.", T0))
    _index()
    assert _docs()
    with _session() as db:
        db.get(WikiLaneIndexState, S.STATE_KEY).format_version = 0
    from src.versioned.store import lane_engine

    assert S.ensure_index(lane_engine("wiki")) == "rebuilt"
    assert _docs() == [], "an entry of the old format is never kept"
    assert len(_queue()) == 1, "and everything held is queued again"
    _index()
    assert _hits("Format") == [("warm", 31, "full")]


def test_an_older_sqlite_gets_a_named_refusal_and_never_a_half_built_index(no_lane, monkeypatch):
    assert S.sqlite_supports_index("3.43.0") and S.sqlite_supports_index("3.51.1")
    assert not S.sqlite_supports_index("3.42.9")
    assert not S.sqlite_supports_index("")
    monkeypatch.setattr(S, "MIN_SQLITE", (99, 0, 0))
    create_lane("wiki")
    with _session() as db:
        names = {r[0] for r in db.execute(text("SELECT name FROM sqlite_master"))}
        assert S.FTS_TABLE not in names and not set(S._TRIGGERS) & names
        assert S.index_available(db) == S.UNAVAILABLE_SQLITE
    out = _search("anything")
    assert out["available"] is False and out["reason"] == S.UNAVAILABLE_SQLITE
    assert out["total"] is None, "an index that cannot exist never answers 0"


# --------------------------------------------------------------------------- #
# the feeders: every text change is queued in its own transaction, and nothing else is
# --------------------------------------------------------------------------- #
def test_a_warm_text_is_queued_in_the_same_transaction_as_the_write(lane):
    with pytest.raises(RuntimeError), _session() as db:
        db.add(WikiWarmPage(edition=EDITION, page_id=77, title="T", latest_revid=1, latest_text="x"))
        db.flush()
        assert len(db.execute(select(WikiLaneIndexQueue)).all()) == 1
        raise RuntimeError("the write is rolled back")
    assert _queue() == [], "the queue row went with the text it was for"


def test_only_a_text_change_queues_a_warm_page_again(lane):
    row_id = _warm(title="Quiet page", latest=(41, "Quiet words.", T0))
    _index()
    assert _queue() == []
    with _session() as db:
        row = db.get(WikiWarmPage, row_id)
        row.due_since = T0  # WARM's own bookkeeping: no text changed
        row.wanted_revid = 42
    assert _queue() == [], "an ORM update names every column it sets; the feeder reads OLD"
    _refetch(row_id, (42, "Quiet words, amended.", T0 + timedelta(days=1)))
    assert _queue() == [("warm", row_id, False)]


def test_a_page_known_only_by_title_is_not_queued_until_it_has_text(lane):
    with _session() as db:
        db.add(WikiWarmPage(edition=EDITION, page_id=78, title="Waiting"))
    assert _queue() == [], "a page WARM has not fetched yet has nothing to index"


# --------------------------------------------------------------------------- #
# WARM pages: the latest in full, the previous by what the latest removed
# --------------------------------------------------------------------------- #
def test_a_changed_page_is_found_by_its_latest_text_and_by_its_title(lane):
    _warm(title="Harbour of Zorbia", latest=(101, "The port handles grain and timber.", T0))
    _index()
    assert _hits("grain") == [("warm", 101, "full")]
    assert _hits("Zorbia") == [("warm", 101, "full")], "the title is indexed with the latest"


def test_the_previous_text_is_found_by_the_lines_the_latest_removed_and_only_by_them(lane):
    previous = "Opening line kept.\nThe mayor resigned over the quarry.\nClosing line kept."
    latest = "Opening line kept.\nClosing line kept.\nA new paragraph about tourism."
    _warm(title="Mining town", latest=(202, latest, T0 + timedelta(days=1)), previous=(201, previous, T0))
    _index()
    assert _hits("quarry") == [("warm", 201, "dropped")], "the removed line leads to the version that had it"
    assert _hits("Opening") == [("warm", 202, "full")], "a kept line is found once, with the newer version"
    assert _hits("tourism") == [("warm", 202, "full")]
    hit = _search("quarry", snippets=False)["items"][0]
    assert hit["successor_revid"] == 202, "the hit names the edit that removed it"
    assert hit["url"].endswith("&oldid=201"), "and its address is that version's own"


def test_a_third_fetch_stops_the_oldest_text_being_found(lane):
    row_id = _warm(
        title="Rotating page",
        latest=(302, "Second text.", T0 + timedelta(days=1)),
        previous=(301, "First text with the word obsidian.", T0),
    )
    _index()
    assert _hits("obsidian") == [("warm", 301, "dropped")]
    _refetch(row_id, (303, "Third text.", T0 + timedelta(days=2)))
    _index()
    assert _hits("obsidian") == [], "Q710 dropped that text; the index must drop it too"
    assert _hits("Second") == [("warm", 302, "dropped")]
    assert _hits("Third") == [("warm", 303, "full")]


# --------------------------------------------------------------------------- #
# followed (HOT) pages: every version but the newest, by what the next one removed
# --------------------------------------------------------------------------- #
def test_the_newest_version_of_a_followed_page_is_never_indexed_here(lane):
    _hot([(401, "Only version about basalt.\n", T0)])
    _index()
    assert _docs() == []
    assert _hits("basalt") == [], "the corpus article is that text, and is searched there"


def test_an_older_version_of_a_followed_page_is_found_by_the_lines_its_successor_removed(lane):
    _hot([
        (501, "Stable intro.\nThe bridge collapsed in 1931.\n", T0),
        (502, "Stable intro.\nThe bridge was rebuilt.\n", T0 + timedelta(days=1)),
    ])
    _index()
    assert _hits("collapsed") == [("hot", 501, "dropped")]
    assert _hits("Stable") == [], "kept in the newest, which the corpus holds"
    assert _hits("rebuilt") == [], "the newest itself"


def test_a_new_revision_makes_the_one_before_it_older_and_findable(lane):
    eid = _hot([(601, "Alpha line.\n", T0), (602, "Alpha line.\nBeta line.\n", T0 + timedelta(days=1))])
    _index()
    assert _hits("Beta") == []
    _add_revision(eid, 603, "Alpha line.\n", T0 + timedelta(days=2))
    _index()
    assert _hits("Beta") == [("hot", 602, "dropped")]


def test_a_version_that_arrives_out_of_order_is_placed_by_its_date(lane):
    eid = _hot([(701, "one\ntwo\nthree\n", T0), (703, "one\n", T0 + timedelta(days=3))])
    _index()
    assert _hits("two") == [("hot", 701, "dropped")] and _hits("three") == [("hot", 701, "dropped")]
    # A backfill brings the version that sat between them.
    _add_revision(eid, 702, "one\ntwo\n", T0 + timedelta(days=1))
    _index()
    assert _hits("three") == [("hot", 701, "dropped")], "701 -> 702 removed 'three'"
    assert _hits("two") == [("hot", 702, "dropped")], "and 702 -> 703 removed 'two'"
    with _session() as db:
        succ = {d.revid: d.successor_revid for d in db.execute(select(WikiLaneDoc)).scalars()}
    assert succ == {701: 702, 702: 703}


def test_an_older_version_whose_successor_text_is_not_held_is_indexed_in_full(lane):
    from src.versioned.models import VersionedRevision

    eid = _hot([(801, "Granite quarry history.\n", T0), (802, "Later text.\n", T0 + timedelta(days=1)),
                (803, "Newest text.\n", T0 + timedelta(days=2))])
    with _session() as db:
        db.execute(select(VersionedRevision).where(VersionedRevision.revision_ref == "802")).scalar_one().content = None
    assert len(_queue()) == 2 and eid
    _index()
    assert _hits("Granite") == [("hot", 801, "full")], "nothing else would cover it"


# --------------------------------------------------------------------------- #
# search: an exact total, named absences, and snippets that mark the right letters
# --------------------------------------------------------------------------- #
def test_the_total_is_exact_whatever_the_limit(lane):
    for n in range(5):
        _warm(title=f"Page {n}", latest=(900 + n, f"Common term lignite, number {n}.", T0))
    _index()
    first = _search("lignite", limit=2, snippets=False)
    assert first["total"] == 5, "a cap may bound the examples, never the number"
    assert len(first["items"]) == 2
    last = _search("lignite", limit=2, offset=4, snippets=False)
    assert last["total"] == 5 and len(last["items"]) == 1
    ids = {i["revid"] for i in first["items"]} | {i["revid"] for i in _search("lignite", limit=2, offset=2, snippets=False)["items"]}
    assert len(ids | {i["revid"] for i in last["items"]}) == 5, "the pages do not overlap"


def test_a_query_with_nothing_to_search_for_has_no_total_and_a_bad_one_is_named(lane):
    _warm(title="Anything", latest=(950, "Some words.", T0))
    _index()
    empty = _search("   ")
    assert empty["available"] is True and empty["total"] is None and empty["items"] == []
    bad = _search("(unbalanced")
    assert bad["error"] == "query_invalid" and bad["total"] is None
    assert _search("nothingmatchesthis")["total"] == 0, "0 is a real answer, and only this is"


def test_every_answer_carries_the_caveat_the_method_and_what_is_still_waiting(lane):
    _warm(title="Waiting page", latest=(960, "Words.", T0))
    out = _search("Words")
    assert out["caveat"] == S.CAVEAT and out["method"] == S.METHOD
    assert out["pending"] == 1 and out["total"] == 0, "not indexed YET, and it says so"
    _index()
    out = _search("Words")
    assert out["pending"] == 0 and out["total"] == 1 and out["failed"] == 0


def test_a_snippet_is_parts_around_the_match_never_offsets(lane):
    body = "Filler words before. " * 20 + "The dam on the Vardar river failed. " + "After words. " * 20
    _warm(title="Dam", latest=(970, body, T0))
    _index()
    snip = _search("Vardar")["items"][0]["snippet"]
    assert {"text": "Vardar", "hit": True} in snip
    joined = "".join(p["text"] for p in snip)
    assert joined.startswith("…") and joined.endswith("…") and len(joined) < len(body)
    assert all(set(p) == {"text", "hit"} for p in snip)


_DRIVER_WORDS = "zq-driver-words"
_STATEMENT = "SELECT zq_secret_column FROM t WHERE v = ?"
_BOUND = {"v": "zq-bound-value"}


def _driver_error(code):
    cls = type("DatabaseError", (Exception,), {"__module__": "sqlite3"})
    exc = cls(_DRIVER_WORDS)
    exc.sqlite_errorcode = code
    return exc


@pytest.mark.parametrize(
    "fault, raises",
    [
        # SQLCipher 4.19 answers a damaged page with the real code-11 error, where 4.12 answered an empty MemoryError: both end the search
        (lambda: OperationalError("SELECT 1", {}, _driver_error(11)), True),
        (lambda: MemoryError(), True),
        # a wrong key (26), a lock (5) and a text the decompressor cannot read are not the lane's damage: the hit stands without a snippet
        (lambda: OperationalError("SELECT 1", {}, _driver_error(26)), False),
        (lambda: OperationalError("SELECT 1", {}, _driver_error(5)), False),
        (lambda: ValueError("unreadable text"), False),
    ],
)
def test_a_snippet_read_that_hits_damage_ends_the_search_and_any_other_fault_only_drops_the_snippet(lane, monkeypatch, fault, raises):
    _warm(title="Dam", latest=(971, "The dam on the Vardar river failed.", T0))
    _index()

    def boom(*a, **k):
        raise fault()

    monkeypatch.setattr(S, "_indexed_body", boom)
    if raises:
        with pytest.raises((OperationalError, MemoryError)):
            _search("Vardar")
    else:
        out = _search("Vardar")
        assert out["total"] == 1 and out["items"][0]["snippet"] is None


def test_the_route_answers_a_corruption_raised_by_a_snippet_read_with_the_fixed_unreadable_reason_and_no_driver_text(lane, monkeypatch, caplog):
    """Through the REAL search(): a snippet read that raises a code-11 error ends it, the route answers the fixed reason, and neither the
    response nor the log line carries a word of the driver's text, the statement or a bound value."""
    import logging

    from src.api.wiki_lane_search import search_lane

    _warm(title="Dam", latest=(972, "The dam on the Vardar river failed.", T0))
    _index()

    def boom(*a, **k):
        raise OperationalError(_STATEMENT, _BOUND, _driver_error(11))

    monkeypatch.setattr(S, "_indexed_body", boom)
    with caplog.at_level(logging.DEBUG):
        out = search_lane("Vardar", limit=5)
    assert out["available"] is False and out["reason"] == "lane-unreadable"
    for text in (repr(out), caplog.text):
        assert not any(w in text for w in ("zq-driver-words", "zq_secret_column", "zq-bound-value")), text
    assert any(r.levelno == logging.WARNING for r in caplog.records), "the failure is logged, class-only, at WARNING"
