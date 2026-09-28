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


def test_a_snippet_finds_the_word_through_case_accents_and_arabic_folding():
    parts = S.snippet("Le Café de Flore", ["cafe"])
    assert {"text": "Café", "hit": True} in parts
    arabic = "ذهب إلى المَدرسة صباحا"
    parts = S.snippet(arabic, ["المدرسة"])
    assert any(p["hit"] and p["text"] == "المَدرسة" for p in parts)
    assert S.snippet_literals('grain AND "red wheat" NOT barley') == ["grain", "red wheat"]


def test_a_hindi_word_is_one_word_so_a_vowel_sign_never_splits_it(lane):
    """R39's tokenizer from the index's first day: 'किताब' is not the three letters around
    its vowel signs, so a search for one of them must not find it."""
    _warm(title="हिन्दी पृष्ठ", latest=(980, "यह किताब अच्छी है।", T0))
    _index()
    assert _hits("किताब") == [("warm", 980, "full")]
    assert _hits("त") == [], "a letter between two vowel signs is not a word"


def test_a_query_finds_arabic_written_with_or_without_its_vowel_marks(lane):
    _warm(title="صفحة", latest=(990, "ذهب إلى المَدرسة صباحا", T0))
    _index()
    assert _hits("المدرسة") == [("warm", 990, "full")]


# --------------------------------------------------------------------------- #
# faults: a text that cannot be read is set aside and retried; a lane fault writes nothing
# --------------------------------------------------------------------------- #
def _corrupt_latest(row_id):
    with _session() as db:
        # Straight to the column, as a damaged file would be: no feeder fires on it.
        db.execute(text("UPDATE wiki_warm_pages SET latest_text = :b WHERE id = :id"), {"b": b"\x00not-compressed", "id": row_id})


def test_an_unreadable_text_is_set_aside_counted_and_the_rest_of_the_batch_goes_on(lane):
    bad = _warm(title="Damaged", latest=(1101, "Damaged text.", T0))
    good = _warm(title="Healthy", latest=(1102, "Healthy text.", T0))
    _corrupt_latest(bad)
    out = _index()
    assert out.failed == 1 and out.settled == 2
    assert _queue() == [("warm", bad, True)], "set aside, not dropped: a failure is never out for good"
    assert _hits("Healthy") == [("warm", 1102, "full")]
    assert [d for d in _docs() if d[1] == 1101] == [], "nothing of the failed page was written"
    status = _search("Healthy")
    assert status["pending"] == 0 and status["failed"] == 1
    assert _index().settled == 0, "a set-aside item is not retried in every batch"
    assert good


def test_a_set_aside_item_is_retried_when_the_lane_next_starts_or_the_page_changes(lane):
    bad = _warm(title="Damaged later", latest=(1201, "Words.", T0))
    _corrupt_latest(bad)
    _index()
    assert _queue() == [("warm", bad, True)]
    with _session() as db:
        assert S.retry_failed(db) == 1
    assert _queue() == [("warm", bad, False)]
    _index()
    assert _queue() == [("warm", bad, True)]
    with _session() as db:
        # The page's next fetch, written without loading the damaged text back.
        db.execute(
            update(WikiWarmPage).where(WikiWarmPage.id == bad).values(
                latest_revid=1202, latest_text="Fresh words.", latest_revised_at=T0 + timedelta(days=1)
            )
        )
    assert _queue() == [("warm", bad, False)], "the page's next change makes it pending again"
    _index()
    assert _queue() == [] and _hits("Fresh") == [("warm", 1202, "full")]


def test_the_indexer_retries_set_aside_items_once_per_start_never_every_window(lane):
    bad = _warm(title="Retry page", latest=(1301, "Words.", T0))
    _corrupt_latest(bad)
    indexer = _indexer()
    first = indexer.index_for(60)
    assert first.failed == 1
    again = indexer.index_for(60)
    assert again.retried == 0 and again.failed == 0, "one attempt per start, never a loop"
    assert _indexer().index_for(60).retried == 1, "a new start tries it once more"


def test_a_fault_in_the_lane_itself_leaves_the_whole_batch_pending_and_nothing_written(lane, monkeypatch):
    """No savepoints: on this driver a released SAVEPOINT commits, so a per-unit savepoint
    would have kept the first unit's writes after the batch failed. The batch is ONE
    transaction, and a lane fault takes all of it back."""
    a = _warm(title="First", latest=(1401, "First words.", T0))
    b = _warm(title="Second", latest=(1402, "Second words.", T0))
    real = S._apply
    calls = []

    def flaky(lane_, plan):
        calls.append(plan.owner_id)
        if len(calls) == 2:
            raise OperationalError("INSERT", {}, Exception("disk I/O error"))
        return real(lane_, plan)

    monkeypatch.setattr(S, "_apply", flaky)
    with pytest.raises(OperationalError):
        _index()
    assert calls == [a, b]
    assert _docs() == [], "the first page's entry went back with the batch"
    assert _queue() == [("warm", a, False), ("warm", b, False)], "every row it took is still pending"
    with _session() as db:
        assert db.execute(text("SELECT count(*) FROM wiki_lane_fts WHERE wiki_lane_fts MATCH 'First'")).scalar() == 0


def test_a_released_savepoint_commits_on_this_driver_which_is_why_there_are_none(tmp_path):
    """The measurement index_batch's docstring rests on, kept as a test so a driver that
    changes it is noticed."""
    import sqlite3

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    path = tmp_path / "sp.db"
    eng = create_engine(f"sqlite:///{path}", future=True)
    with eng.begin() as c:
        c.exec_driver_sql("CREATE TABLE t(x INT)")
    s = Session(eng)
    s.execute(text("SELECT 1")).all()
    sp = s.begin_nested()
    s.execute(text("INSERT INTO t VALUES (1)"))
    sp.commit()
    s.rollback()
    other = sqlite3.connect(path)
    assert other.execute("SELECT count(*) FROM t").fetchone()[0] == 1
    other.close()
    s.close()
    eng.dispose()
    assert not S.index_batch.__code__.co_names.count("begin_nested")


# --------------------------------------------------------------------------- #
# the indexer: the budget, the deadline, the segmenters, the runner's order
# --------------------------------------------------------------------------- #
class Clock:
    def __init__(self, step=0.0):
        self.t = 1000.0
        self.step = step

    def __call__(self):
        self.t += self.step
        return self.t


def _plenty():
    return budget_state(total_gb=20, disk_bytes=0, editions=1)


def _spent():
    return budget_state(total_gb=1, disk_bytes=2 * 1024**3, editions=1)


def _indexer(budget=_plenty, batch=100, clock=None, caps=lambda: CAPS):
    return S.LaneIndexer(lane_session=_session, budget=budget, batch=batch, caps=caps,
                         monotonic=clock or Clock())


def test_a_spent_budget_pauses_the_indexer_by_name_and_it_writes_nothing(lane):
    from src.wiki.walk import PAUSED_BUDGET

    _warm(title="Budget page", latest=(1501, "Words.", T0))
    indexer = _indexer(budget=_spent)
    report = indexer.index_for(60)
    assert report.paused == PAUSED_BUDGET and report.settled == 0
    assert indexer.status()["state"] == S.STATE_PAUSED and indexer.status()["reason"] == PAUSED_BUDGET
    assert _docs() == [] and len(_queue()) == 1


def test_the_indexer_stops_at_its_deadline_but_always_moves_forward(lane):
    for n in range(3):
        _warm(title=f"Deadline {n}", latest=(1600 + n, "Words.", T0))
    with _session() as db:
        out = S.index_batch(db, limit=100, caps=CAPS, deadline=0.0, monotonic=lambda: 5.0)
    assert out.stopped_early and out.settled == 1, "one unit, then the deadline"
    report = _indexer().index_for(60)
    assert report.settled == 2 and _queue() == []
    assert _indexer().status()["state"] == S.STATE_NOT_STARTED


def test_the_indexer_says_when_it_has_caught_up(lane):
    _warm(title="Caught up", latest=(1701, "Words.", T0))
    indexer = _indexer(batch=1)
    report = indexer.index_for(60)
    assert report.settled == 1 and indexer.status()["state"] == S.STATE_CAUGHT_UP
    assert indexer.status()["entries_this_process"] == 1


def test_a_change_of_segmenters_queues_every_held_text_again(lane):
    _warm(title="Seg page", latest=(1801, "Words.", T0))
    _hot([(1802, "a\n", T0), (1803, "b\n", T0 + timedelta(days=1))])
    _indexer().index_for(60)
    assert _queue() == []
    with _session() as db:
        assert db.get(WikiLaneIndexState, S.STATE_KEY).segmenters == 0
    report = _indexer(caps=lambda: CAPS | fts_norm.ZH_JIEBA).index_for(60)
    assert report.requeued == 2, "the WARM page and the one revision"
    assert report.settled == 2 and _queue() == []
    with _session() as db:
        assert db.get(WikiLaneIndexState, S.STATE_KEY).segmenters == fts_norm.ZH_JIEBA
    assert _indexer(caps=lambda: CAPS | fts_norm.ZH_JIEBA).index_for(60).requeued == 0, "once"


def test_the_counts_are_the_entries_own_and_survive_a_replacement(lane):
    row_id = _warm(title="Counted", latest=(1901, "abc", T0))
    _index()
    with _session() as db:
        state = db.get(WikiLaneIndexState, S.STATE_KEY)
        assert (state.docs, state.chars) == (1, len("Counted") + len("abc"))
    _refetch(row_id, (1902, "abcdef", T0 + timedelta(days=1)))
    _index()
    with _session() as db:
        state = db.get(WikiLaneIndexState, S.STATE_KEY)
        n = db.execute(select(func.count()).select_from(WikiLaneDoc)).scalar()
        assert state.docs == n == 2, "the latest, and the previous by its removed line"
        status = S.index_status(db)
    assert status["entries"] == 2 and status["available"] is True and status["pending"] == 0


def test_the_runner_gives_the_index_its_share_of_the_idle_time_first(lane):
    from src.wiki.runner import WikiLaneRunner

    order: list[tuple[str, float]] = []

    class Indexer:
        def index_for(self, seconds, *, should_stop):
            order.append(("index", seconds))
            raise RuntimeError("an index bug")

        def status(self):
            return {"state": "indexing"}

    class Warm:
        def warm_for(self, seconds, *, should_stop):
            order.append(("warm", seconds))
            from src.wiki import warm as M

            return M.WarmReport()

        def status(self):
            return {"state": "off"}

    slept: list[float] = []
    runner = WikiLaneRunner(
        adapter=None, stream=None, lane_session=_session, state_of=lambda: "running",
        hot_sets=dict, budget=_plenty, warm=Warm(), indexer=Indexer(), sleep=slept.append,
        monotonic=lambda: 0.0, drain_interval_s=30.0,
    )
    runner.idle(30.0)
    assert [name for name, _ in order] == ["index", "warm"], "texts already held become findable first"
    assert order[0][1] == 30.0 * S.INDEX_SHARE, "and for its share only"
    assert runner.last_index == {"error": "RuntimeError"}, "a broken index never ends the lane"
    assert slept == [30.0]
    assert runner.index_status()["last_window"] == {"error": "RuntimeError"}


# --------------------------------------------------------------------------- #
# the routes: absences by name, one version read back, and «Add to corpus»
# --------------------------------------------------------------------------- #
def test_the_search_route_on_a_machine_without_the_lane_creates_nothing(no_lane):
    from src.api import wiki_lane_search as R

    out = R.lane_search(q="anything", limit=20, offset=0)
    assert out["available"] is False and out["reason"] == "lane-never-run"
    assert out["total"] is None
    assert not lane_path("wiki").exists(), "a search never brings the lane file into being"


def test_the_version_route_reads_back_exactly_the_version_a_hit_named(lane):
    from fastapi import HTTPException

    from src.api import wiki_lane_search as R

    row_id = _warm(
        title="Two versions",
        latest=(2002, "Now it says ''tin''.", T0 + timedelta(days=1)),
        previous=(2001, "Once it said ''copper''.", T0),
    )
    old = R.lane_version(source="warm", owner_id=row_id, revid=2001)
    assert old["text"] == S.plain_text("Once it said ''copper''.") and "copper" in old["text"]
    assert "tin" not in old["text"] and old["revid"] == 2001
    assert old["revised_at"] == T0.isoformat() and old["url"].endswith("&oldid=2001")
    with pytest.raises(HTTPException) as exc:
        R.lane_version(source="warm", owner_id=row_id, revid=1999)
    assert exc.value.status_code == 404 and exc.value.detail == "not-held"


def test_the_newest_followed_version_says_the_corpus_already_has_it(lane):
    from src.api import wiki_lane_search as R

    eid = _hot([(2101, "old\n", T0), (2102, "new\n", T0 + timedelta(days=1))])
    assert R.lane_version(source="hot", owner_id=eid, revid=2102)["newest_followed"] is True
    assert R.lane_version(source="hot", owner_id=eid, revid=2101)["newest_followed"] is False


def _corpus():
    from src.database.session import SessionLocal, init_db

    init_db()
    return SessionLocal()


def test_add_to_corpus_stores_that_version_under_its_own_address_date_and_revision(lane):
    from src.api import wiki_lane_search as R
    from src.api.wiki_lane_search import AddVersion
    from src.database.models import Article
    from src.wiki.corpus import wiki_article_url, wiki_version_url

    at = T0 - timedelta(days=400)
    row_id = _warm(
        title="Add me page",
        latest=(2202, "The newer text of the add me page.", T0),
        previous=(2201, "The older text of the add me page, about saltpetre.", at),
    )
    db = _corpus()
    try:
        out = R.add_to_corpus(AddVersion(source="warm", owner_id=row_id, revid=2201), db=db)
        assert out["status"] == "created" and out["revid"] == 2201
        art = db.get(Article, out["article_id"])
        assert art.canonical_url == wiki_version_url(EDITION, "Add me page", 2201)
        assert art.canonical_url != wiki_article_url(EDITION, "Add me page"), "never the page's own address"
        assert art.source_revision == "2201"
        assert art.content == "The older text of the add me page, about saltpetre."
        assert art.published_at.replace(tzinfo=UTC) == at, "the date the wiki gave that version, not today"
        again = R.add_to_corpus(AddVersion(source="warm", owner_id=row_id, revid=2201), db=db)
        assert again == {**again, "status": "exists", "article_id": art.id}, "never a second copy"
    finally:
        db.close()


def test_add_to_corpus_names_the_article_that_already_has_the_same_words(lane):
    from src.api import wiki_lane_search as R
    from src.api.wiki_lane_search import AddVersion
    from src.wiki.corpus import upsert_wiki_corpus_article

    words = "Identical words in the corpus already, about vermilion."
    db = _corpus()
    try:
        upsert_wiki_corpus_article(db, wiki=EDITION, title="Same words page", plain=words, revid=2300)
        row_id = _warm(title="Same words page", latest=(2301, words, T0))
        out = R.add_to_corpus(AddVersion(source="warm", owner_id=row_id, revid=2301), db=db)
        assert out["status"] == "same_text" and out["title"] == "Same words page"
    finally:
        db.close()


def test_add_to_corpus_refuses_a_version_not_held_or_a_page_without_a_title(lane):
    from fastapi import HTTPException

    from src.api import wiki_lane_search as R
    from src.api.wiki_lane_search import AddVersion

    db = _corpus()
    try:
        with pytest.raises(HTTPException) as exc:
            R.add_to_corpus(AddVersion(source="warm", owner_id=999_999, revid=1), db=db)
        assert exc.value.status_code == 404
        untitled = _warm(title=None, latest=(2401, "No title here.", T0))
        with pytest.raises(HTTPException) as exc:
            R.add_to_corpus(AddVersion(source="warm", owner_id=untitled, revid=2401), db=db)
        assert exc.value.status_code == 409 and exc.value.detail == "no-title"
    finally:
        db.close()


def test_a_version_address_reads_back_to_exactly_what_it_was_built_from():
    from src.wiki.corpus import wiki_page_ref, wiki_version_ref, wiki_version_url

    for title in ("Plain", "With spaces", "AT&T", "Q&A?", "C#", "Épée", "東京", "a=b", "100%"):
        url = wiki_version_url("en", title, 12345)
        assert wiki_version_ref(url) == ("en", title, 12345), url
        assert wiki_page_ref(url) is None, "a version address is never the page's own"
    assert wiki_version_url("en", None, 7) == "https://en.wikipedia.org/w/index.php?oldid=7"
    assert wiki_version_ref("https://en.wikipedia.org/w/index.php?oldid=7") is None
    assert wiki_version_ref("https://en.wikipedia.org/w/index.php?title=X&oldid=7&x=1") is None
    assert wiki_version_ref("https://evil.example/w/index.php?title=X&oldid=7") is None
    assert wiki_version_ref("https://en.wikipedia.org/w/index.php?title=X&oldid=0") is None


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    from src.api.main import app

    with TestClient(app) as c:
        yield c


def test_the_reader_carries_the_licence_and_the_revision_for_an_added_version(lane, client):
    from src.api import wiki_lane_search as R
    from src.api.wiki_lane_search import AddVersion
    from src.wiki.attribution import LICENCE_NAME

    row_id = _warm(title="Licensed version", latest=(2501, "Text of a licensed version.", T0))
    db = _corpus()
    try:
        aid = R.add_to_corpus(AddVersion(source="warm", owner_id=row_id, revid=2501), db=db)["article_id"]
    finally:
        db.close()
    html = client.get(f"/api/articles/{aid}/view").text
    assert LICENCE_NAME in html, "Wikipedia text under its licence, whichever version it is"
    assert "oldid=2501" in html


def test_the_omnibar_wiki_group_carries_the_lane_hits_beside_the_corpus(lane):
    import sqlalchemy as sa
    from sqlalchemy.orm import sessionmaker

    from src.api.search_omni import _wiki_group
    from src.database.fts import ensure_fts
    from src.database.models import Base

    _warm(title="Omnibar page", latest=(2601, "The omnibar finds molybdenum.", T0))
    _index()
    eng = sa.create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng, future=True)()
    try:
        ensure_fts(s.get_bind())
        s.commit()
        g = _wiki_group(s, "molybdenum")
    finally:
        s.close()
        eng.dispose()
    assert g["lane"]["available"] is True and g["lane"]["total"] == 1
    assert g["lane"]["items"][0]["revid"] == 2601
    assert g["lane"]["items"][0]["snippet"] is None, "per keystroke: no snippets here"
    assert g["lane"]["caveat"] == S.CAVEAT


def test_a_lane_whose_index_is_not_built_yet_says_so_rather_than_answering_zero(lane):
    """A search opens the lane without ``create_lane``, so on a lane file this process has not
    started yet (the lane switched off, say) the index may not exist: that is its own reason."""
    from src.api import wiki_lane_search as R

    with _session() as db:
        db.execute(text("DROP TABLE wiki_lane_fts"))
    dispose_all()
    out = R.search_lane("anything", limit=20)
    assert out["available"] is False and out["reason"] == S.UNAVAILABLE_NOT_BUILT
    assert out["total"] is None
    with _session() as db:
        names = {r[0] for r in db.execute(text("SELECT name FROM sqlite_master"))}
    assert S.FTS_TABLE not in names, "a search reads; it never builds the index"


def test_the_search_tab_answer_says_what_it_looked_through(lane, monkeypatch):
    """R52's owed line: a search with no Wikipedia hit must never read as «Wikipedia does not
    say this». The answer names the editions, how many pages hold a text, and WARM's switch."""
    from src.api import wiki_lane_search as R
    from src.wiki.lane_models import WikiWarmEdition

    monkeypatch.setattr(R, "_warm_enabled", lambda: False)
    _warm(title="Covered page", latest=(2701, "Covered words.", T0))
    with _session() as db:
        db.add(WikiWarmEdition(edition=EDITION, pages_with_text=1))
    _hot([(2702, "a\n", T0), (2703, "b\n", T0 + timedelta(days=1))], page_id=2702)
    _index()
    out = R.lane_search(q="nowhere", limit=20, offset=0)
    assert out["total"] == 0
    cov = out["coverage"]
    assert cov["editions"] == [EDITION]
    assert cov["changed_pages"] == {"pages": 1, "editions": [{"edition": EDITION, "pages": 1}]}
    assert cov["stream_pages"] == {"pages": 1, "editions": [{"edition": EDITION, "pages": 1}]}
    assert cov["pending"] == 0 and cov["failed"] == 0 and cov["entries"] == 2
    assert cov["warm_enabled"] is False, "so the tab can say WARM's texts are not being fetched"
    assert "this machine" in cov["method"]


def test_the_omnibar_skips_the_queue_count_it_runs_per_keystroke(lane):
    from src.api.wiki_lane_search import search_lane

    _warm(title="Keystroke page", latest=(2801, "Keystroke words.", T0))
    _index()
    quick = search_lane("Keystroke", limit=5, snippets=False, queue=False)
    assert quick["total"] == 1 and "pending" not in quick and "coverage" not in quick
    full = search_lane("Keystroke", limit=5, coverage=True)
    assert full["pending"] == 0 and "coverage" in full
