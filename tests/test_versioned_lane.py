"""S1: one fixture page round-trips baseline -> change -> revision -> Article.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The brief's S1 acceptance clause is the first test here, and the rest are the
properties that clause is only meaningful alongside: that a null edit does not
invent a revision, that a deletion is a fact and not an error, that a budget refusal
is NAMED and is not a gap, that a retention gap is real when the window genuinely
cannot reach the cursor, and — Q1018's own bar — that the whole pass runs with ZERO
name resolutions.

WHY ZERO RESOLUTIONS RATHER THAN ZERO REQUESTS. A DNS lookup hands a resolver the
list of things this app is about to read, which is egress whether or not any HTTP
request follows. The recorded rule is explicit about it, and it is also the only
counter that catches a client that fails to connect: a request count would read zero
for a fetch that resolved a host and then timed out.
"""

from __future__ import annotations

import socket
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from src.database.models import Article, KeywordMention
from src.database.session import SessionLocal, init_db
from src.testing.wiki_fixture import FixtureWikiClient
from src.versioned import pipeline, revisions, store
from src.versioned.adapters import ReadBudget, WikiLaneAdapter, external_id_for
from src.versioned.feed import open_gaps, stored_token
from src.versioned.models import VersionedChange, VersionedEntity

EDITION = "oo"
FEED = f"recentchanges:{EDITION}"
DAY4 = datetime(2026, 3, 4, tzinfo=UTC)
WATCHED = ("Fixture Alpha", "Fixture Beta", "Fixture Gamma")


#: Every corpus Article this fixture edition can produce lives under this prefix.
#: ``oo.wikipedia.org`` does not resolve, which is the fixture's own safety property.
CORPUS_PREFIX = "https://oo.wikipedia.org/"


def _forget_fixture_articles() -> None:
    """Remove the fixture edition's Articles from the SHARED corpus.

    MEASURED, and the reason this function exists: ``OO_DATA_DIR`` re-pointing does
    NOT move the corpus. ``src/database/session.py`` builds its engine at IMPORT time
    (session.py:124) and ``conftest`` sets the variable once for the whole run, so
    ``SessionLocal`` is bound to one session-wide database no matter what a
    function-scoped ``monkeypatch.setenv`` says. The LANE re-points (its engine cache
    is keyed on the resolved path); the corpus does not.

    WHAT THIS SWEEP IS AND IS NOT WORTH, measured rather than asserted. Removing it
    reddens NOTHING today: four randomized runs of this file stayed green without it,
    because the upsert is keyed on the canonical URL (so leftovers are updated, never
    duplicated) and each test's FIRST pass rewrites ``source_revision`` back to the
    baseline before the second advances it — the assertions are re-earned each time.
    It is kept as insulation, not as a fix, and that distinction is written here so a
    later reader does not infer a defect that was never observed. What IS measured is
    the paragraph above: the corpus does not follow ``OO_DATA_DIR``, which makes every
    corpus row in this file shared state whether or not it currently bites.

    Run on BOTH edges, because a test that fails midway must not leave the next one
    that inheritance.
    """
    with SessionLocal() as corpus:
        ids = list(
            corpus.execute(
                select(Article.id).where(Article.canonical_url.like(f"{CORPUS_PREFIX}%"))
            ).scalars()
        )
        if ids:
            corpus.query(KeywordMention).filter(KeywordMention.article_id.in_(ids)).delete(
                synchronize_session=False
            )
            corpus.query(Article).filter(Article.id.in_(ids)).delete(synchronize_session=False)
            corpus.commit()


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A lane file of this test's own, plus the (shared) corpus, swept clean."""
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    store.create_lane("wiki")
    init_db()
    _forget_fixture_articles()
    with store.lane_session("wiki") as session:
        for title in WATCHED:
            pipeline.ensure_entity(
                session, external_id_for(EDITION, title), title=title, language=EDITION
            )
    try:
        yield
    finally:
        _forget_fixture_articles()
        store.dispose_all()


def _pass(*, as_of=None, max_rc=50, budget=None, index=True):
    """One lane pass over the fixture. Returns ``(result, client)``."""
    client = FixtureWikiClient(max_recentchanges=max_rc, as_of=as_of)
    adapter = WikiLaneAdapter(client=client, editions=(EDITION,))
    with store.lane_session("wiki") as lane_session, SessionLocal() as corpus:
        result = pipeline.run_feed_once(
            lane_session,
            adapter,
            FEED,
            corpus=corpus if index else None,
            budget=budget,
        )
        corpus.commit()
    return result, client


def test_a_page_round_trips_baseline_then_change_then_revision_then_ARTICLE(lane):
    """THE S1 ACCEPTANCE CLAUSE, driven end to end through the real ``index_article``.

    Two passes, because the round trip is only a round trip if the second pass sees
    the first one's state: pass one captures the baseline of every watched page,
    pass two stores the later revision and re-indexes the corpus Article onto it.
    """
    first, _ = _pass(as_of=DAY4)
    assert first.baselines_captured == 3, first.as_dict()
    assert first.revisions_stored == 0, "a first read has no previous version to diff"
    assert first.articles_indexed == 3

    second, _ = _pass()
    assert second.revisions_stored == 1, second.as_dict()
    assert second.articles_indexed == 1

    with SessionLocal() as corpus:
        alpha = corpus.query(Article).filter(Article.title == "Fixture Alpha").one()
        # The ARTICLE follows the newest version, which is what "the latest as an
        # Article" means — and ``source_revision`` is what makes that checkable.
        assert alpha.source_revision == "1011"
        assert alpha.keyword_indexed_at is not None, "the real index_article never ran"
        assert corpus.query(KeywordMention).filter_by(article_id=alpha.id).count() > 0

    with store.lane_session("wiki") as session:
        entity = (
            session.query(VersionedEntity)
            .filter_by(external_id=external_id_for(EDITION, "Fixture Alpha"))
            .one()
        )
        baseline = revisions.baseline_for(session, entity.id)
        assert baseline.revision_ref == "1001", "the baseline moved"
        rows, total = revisions.timeline(session, entity.id)
        assert total == 1
        row = rows[0]
        assert row.revision_ref == "1011"
        assert row.diff_from_ref == "1001", "the diff is not against the previous held version"
        assert row.diff_method == "unified"
        assert (row.diff_added, row.diff_removed) == (2, 1)
        assert row.article_id == alpha.id, "the lane revision does not name its Article"


def test_a_point_in_time_read_returns_what_the_lane_HELD_then(lane):
    """Point in time reads: before the revision it is the baseline, after it the revision."""
    _pass(as_of=DAY4)
    _pass()
    with store.lane_session("wiki") as session:
        entity = (
            session.query(VersionedEntity)
            .filter_by(external_id=external_id_for(EDITION, "Fixture Alpha"))
            .one()
        )
        early = revisions.version_at(session, entity.id, datetime(2026, 3, 5, tzinfo=UTC))
        assert early.is_baseline is True
        assert early.held.revision_ref == "1001"

        late = revisions.version_at(session, entity.id, datetime(2026, 3, 30, tzinfo=UTC))
        assert late.is_baseline is False
        assert late.held.revision_ref == "1011"

        # Before anything was held at all: an honest absence, never the oldest text.
        before = revisions.version_at(session, entity.id, datetime(2026, 1, 1, tzinfo=UTC))
        assert before.held is None


def test_a_NULL_EDIT_stores_no_revision_and_is_counted_as_unchanged(lane):
    """``Fixture Beta``'s revert restores a byte-identical body under a NEW revid.

    Storing it would put a row in the timeline whose diff a reader opens and finds
    empty, with nothing to say why. Refusing it silently would be worse — hence the
    counter.
    """
    _pass(as_of=DAY4)
    second, _ = _pass()
    assert second.revisions_unchanged == 1, second.as_dict()

    with store.lane_session("wiki") as session:
        entity = (
            session.query(VersionedEntity)
            .filter_by(external_id=external_id_for(EDITION, "Fixture Beta"))
            .one()
        )
        _, total = revisions.timeline(session, entity.id)
        assert total == 0, "the revert was stored as a revision"
        # The CHANGES were still recorded — the lane knows the edits happened.
        assert session.query(VersionedChange).filter_by(entity_id=entity.id).count() >= 2, (
            "the edits behind the revert were not recorded"
        )


def test_a_DELETION_is_its_own_counter_and_not_an_error(lane):
    """``Fixture Gamma`` is deleted. The history stays and nothing reads as a failure.

    Filing a deletion under ``errors`` would make a lane that is working correctly
    look like one that is failing — and would bury a real failure among them.
    """
    _pass(as_of=DAY4)
    second, _ = _pass()
    assert second.deleted_reported == 1, second.as_dict()
    assert second.errors == [], second.errors

    with store.lane_session("wiki") as session:
        entity = (
            session.query(VersionedEntity)
            .filter_by(external_id=external_id_for(EDITION, "Fixture Gamma"))
            .one()
        )
        assert revisions.baseline_for(session, entity.id) is not None, (
            "a deletion destroyed the evidence this lane had already gathered"
        )


def test_a_BUDGET_refusal_is_NAMED_and_is_not_a_gap(lane):
    """A budget stops the lane FETCHING TEXT; it does not put a hole in the feed.

    The two are separate columns for a reason: merging them would let a lane under a
    tight budget report holes in its KNOWLEDGE when it has holes only in its
    STORAGE — and would let a real retention gap hide among them.
    """
    result, client = _pass(as_of=DAY4, budget=ReadBudget(max_versions=1))
    assert result.baselines_captured == 1, result.as_dict()
    assert result.text_deferred == 2, result.as_dict()
    assert result.gap_recorded is False, "a budget was recorded as a coverage gap"

    with store.lane_session("wiki") as session:
        assert open_gaps(session, FEED) == []
        # Every change is recorded whether or not its text was fetched — the figure
        # that makes "we were told and did not fetch" a countable fact.
        deferred = (
            session.query(VersionedChange)
            .filter(VersionedChange.ingested_revision_id.is_(None))
            .count()
        )
        assert deferred > 0

    # And the budget was honoured in REQUESTS, not merely in the returned number.
    assert client.calls.get("fetch_current_text", 0) == 1, client.calls


def test_a_retention_window_that_cannot_reach_the_cursor_IS_a_gap(lane):
    """A REAL gap, produced by a real short window — never a fabricated one.

    The first pass leaves a cursor in the middle of the fixture's history. The
    second serves a window of two changes, both newer than that cursor, so the
    window provably did not reach back to where the lane left off.
    """
    _pass(as_of=DAY4)
    with store.lane_session("wiki") as session:
        assert stored_token(session, FEED) is not None

    result, _ = _pass(max_rc=2)
    assert result.gap_recorded is True, result.as_dict()

    with store.lane_session("wiki") as session:
        gaps = open_gaps(session, FEED)
        assert len(gaps) == 1
        gap = gaps[0]
        assert gap.reason == "retention", gap.reason
        # Both ends named, in the feed's own vocabulary rather than in ours.
        assert gap.from_token and gap.to_token
        assert gap.from_time is not None and gap.to_time is not None


def test_a_full_pass_makes_ZERO_NAME_RESOLUTIONS(lane):
    """Q1018's bar: the pipeline runs end to end in CI without a socket.

    Counts RESOLUTIONS, not requests: a DNS lookup hands a resolver the list of
    things this app is about to read, which is egress whether or not any HTTP
    request follows — and a request counter reads zero for a fetch that resolved a
    host and then failed to connect.
    """
    resolved: list[tuple] = []
    real = socket.getaddrinfo

    def _spy(*args, **kwargs):
        resolved.append(args[:2])
        return real(*args, **kwargs)

    socket.getaddrinfo = _spy
    try:
        first, _ = _pass(as_of=DAY4)
        second, _ = _pass()
    finally:
        socket.getaddrinfo = real

    # Anti-vacuity: the pass must have DONE something, or zero resolutions is free.
    assert first.baselines_captured == 3, first.as_dict()
    assert second.revisions_stored == 1, second.as_dict()
    assert resolved == [], f"the lane resolved {len(resolved)} name(s): {resolved[:5]}"


def test_the_fixture_client_REFUSES_an_edition_it_does_not_hold(lane):
    """A foreign edition is a loud refusal, never an empty change list.

    An empty list reads as "that wiki had no changes", which is exactly the
    fabricated-quiet result a test would believe — and in production the same call
    would be a fetch.
    """
    from src.testing.wiki_fixture import FixtureNetworkAttempt

    adapter = WikiLaneAdapter(client=FixtureWikiClient(), editions=("en",))
    with store.lane_session("wiki") as session, pytest.raises(FixtureNetworkAttempt):
        pipeline.run_feed_once(session, adapter, "recentchanges:en")


def test_an_entity_the_lane_does_not_WATCH_is_counted_but_never_fetched(lane):
    """A feed reports changes to things nobody asked to follow.

    Those are RECORDED — a lane that only counts what it already follows cannot say
    how much it is not following — and they must not cause an entity to appear by
    itself, because the watch list is the operator's.
    """
    result, client = _pass()
    with store.lane_session("wiki") as session:
        titles = {e.title for e in session.query(VersionedEntity).all()}
        assert titles == set(WATCHED), f"the lane grew its own watch list: {titles}"
        unattached = (
            session.query(VersionedChange).filter(VersionedChange.entity_id.is_(None)).all()
        )
        assert unattached, "changes to unwatched pages were dropped rather than counted"
        # ...and each one still NAMES what changed, so "how much am I not following"
        # can say what it counted — and so these rows attach to the entity if the
        # operator starts watching that page later.
        unwatched = {c.external_id for c in unattached}
        assert external_id_for(EDITION, "Fixture Delta") in unwatched, unwatched
        assert all(c.external_id for c in unattached), "an unattached change names nothing"
    # Delta and Epsilon are unwatched, so their text was never fetched.
    assert client.calls.get("fetch_current_text", 0) <= len(WATCHED)


def test_UNWATCHING_a_page_stops_the_FETCH_and_keeps_the_ATTRIBUTION(lane):
    """``watching`` is where the bandwidth decision lives — and it is the ONLY place.

    An entity the lane already knows keeps receiving attributed change rows after
    the operator unwatches it (throwing the attribution away would lose a fact
    already in hand, and the row would have to be re-attributed by guess if they
    ever watch it again). What stops is the fetch.

    This distinction is load-bearing and was invisible: ``entity_ids`` maps every
    KNOWN entity, watched or not, so without the ``watching`` check one pass would
    quietly fetch the text of every page the operator had turned off.
    """
    with store.lane_session("wiki") as session:
        alpha = (
            session.query(VersionedEntity)
            .filter_by(external_id=external_id_for(EDITION, "Fixture Alpha"))
            .one()
        )
        alpha.watching = False

    result, client = _pass()
    assert client.calls.get("fetch_current_text", 0) == len(WATCHED) - 1, client.calls
    # Of the two still watched, Beta yields a baseline and Gamma is already deleted —
    # so the pass reports 1 and 1, not 2 baselines. Spelled out because the arithmetic
    # is otherwise the kind a reader adjusts until it matches.
    assert result.baselines_captured == 1, result.as_dict()
    assert result.deleted_reported == 1, result.as_dict()

    with store.lane_session("wiki") as session:
        alpha = (
            session.query(VersionedEntity)
            .filter_by(external_id=external_id_for(EDITION, "Fixture Alpha"))
            .one()
        )
        attributed = session.query(VersionedChange).filter_by(entity_id=alpha.id).count()
        assert attributed > 0, "unwatching a page orphaned the changes reported for it"
        assert revisions.baseline_for(session, alpha.id) is None, "an unwatched page was fetched"
