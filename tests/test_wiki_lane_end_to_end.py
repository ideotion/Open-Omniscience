"""The whole lane on a fixture: stream -> substrate -> wiki.db -> corpus. No sockets.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q1018 = a: "every lane's pipeline runs end-to-end in CI without a socket". This file
is the proof for the STREAM path, and the airplane socket guard is armed for the
whole of it — so the assertion is not "we mocked the network" but "with the
process-wide guard installed, nothing resolved a name or opened a connection".

Q715 (identity on ``(wiki, pageid)``), Q703 (namespace 0, no redirects), Q705 (the
metadata list, absent when unanswered), Q708 (every edit a row), Q713 (log events)
and Q727 (a gap the lane PUBLISHES) are all visible in one pass here, because the
thing worth testing is that they hold TOGETHER.
"""

from __future__ import annotations

import pytest

from src.ingest import activate_kill_switch, clear_kill_switch
from src.testing.wiki_fixture import FixtureWikiClient
from src.testing.wiki_stream_fixture import FixtureStreamSession
from src.versioned.adapters.base import ReadBudget
from src.versioned.models import (
    VersionedChange,
    VersionedCursor,
    VersionedEntity,
    VersionedEntityFact,
    VersionedGap,
    VersionedRevision,
)
from src.versioned.pipeline import run_feed_once
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki.identity import external_id_for, legacy_external_id_for, parse_external_id
from src.wiki.lane import StreamBuffer, WikiStreamAdapter
from src.wiki.stream import WikiEventStream

EDITION = "oo"
FEED = f"stream:{EDITION}"
ALPHA, BETA, GAMMA, DELTA, EPSILON = 101, 102, 103, 104, 105


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A real, isolated ``wiki.db`` through the ONE keyed factory.

    The CORPUS stays on the suite's own shared database (conftest binds one
    ``OO_DATA_DIR`` at import and the engine is built from it), because the recorded
    rule is that a test needing corpus rows seeds through the real path rather than
    rebinding a process-global engine underneath the rest of the suite. Only the LANE
    is redirected, and ``lane_path`` reads the environment per call, so that is free.
    """
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
def corpus_ready():
    """The corpus schema, for the two tests that put a version INTO it."""
    from src.database.session import init_db

    init_db()


def _drive(adapter, *, cut_after=None):
    session = FixtureStreamSession(cut_after=cut_after)
    stream = WikiEventStream(session=session, editions=(EDITION,), sleep=lambda _s: None)
    stream.run(
        adapter.offer,
        max_connections=1 if cut_after is None else 2,
        on_position=adapter.note_position,
    )
    return stream


def _adapter(**kw):
    return WikiStreamAdapter(client=FixtureWikiClient(), editions=(EDITION,), **kw)


# --------------------------------------------------------------------------- #
# One pass, everything.
# --------------------------------------------------------------------------- #
def test_the_whole_pass_resolves_ZERO_names_with_the_socket_guard_installed(
    lane, corpus_ready, monkeypatch
):
    """Q1018's bar, measured rather than asserted.

    The airplane socket guard is INSTALLED and the kill switch is CLEAR, which is the
    combination that proves something: the guard is transparent while online, so a
    pass that completes here completes exactly as it would in production — and the
    resolution counter says whether any of it reached for the network. A DNS resolve
    is itself egress, so counting HTTP requests would not be the same claim.
    """
    import socket

    from src.ingest.airplane import install_airplane_socket_guard

    install_airplane_socket_guard()
    resolutions: list[tuple] = []
    real = socket.getaddrinfo
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **k: (resolutions.append(a), real(*a, **k))[1]
    )

    adapter = _adapter()
    _drive(adapter)
    with lane_session("wiki") as session:
        session.add(
            VersionedEntity(
                external_id=external_id_for(EDITION, ALPHA), title="Fixture Alpha", language=EDITION
            )
        )
        session.flush()
        result = run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=5))

    assert result.changes_recorded > 0, "the pass must actually have done the work"
    assert result.errors == []
    assert resolutions == [], f"the lane resolved {len(resolutions)} name(s): {resolutions}"


def test_the_same_pass_is_REFUSED_BY_NAME_once_airplane_mode_is_engaged(lane):
    """The other half. A gate is only proven against a state you put it in explicitly."""
    from src.wiki.stream import StreamStopped

    activate_kill_switch()
    try:
        with pytest.raises(StreamStopped, match="kill switch"):
            _drive(_adapter())
    finally:
        clear_kill_switch()


def test_every_edit_becomes_a_row_and_no_two_share_a_ref(lane):
    """Q708 = b: "Every edit as a row for every page.\""""
    adapter = _adapter()
    _drive(adapter)
    with lane_session("wiki") as session:
        run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=0))
        rows = session.query(VersionedChange).all()
        assert len(rows) == 15, "the recorded fixture's kept events, all of them"
        refs = [r.change_ref for r in rows]
        assert len(set(refs)) == len(refs)


def test_a_page_the_operator_does_NOT_watch_still_gets_its_changes_recorded(lane):
    """"a lane that only counts what it already follows cannot say how much it is not following"."""
    adapter = _adapter()
    _drive(adapter)
    with lane_session("wiki") as session:
        run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=0))
        assert session.query(VersionedEntity).count() == 0, "a feed never creates a watch"
        unattributed = (
            session.query(VersionedChange).filter(VersionedChange.entity_id.is_(None)).count()
        )
        assert unattributed == 15


# --------------------------------------------------------------------------- #
# Q715: identity survives a move.
# --------------------------------------------------------------------------- #
def test_a_MOVE_keeps_one_entity_because_the_key_is_the_page_id_not_the_title(lane):
    """The fixture moves page 101 to a new title. A title-keyed store would split it."""
    adapter = _adapter()
    _drive(adapter)
    with lane_session("wiki") as session:
        session.add(
            VersionedEntity(
                external_id=external_id_for(EDITION, ALPHA), title="Fixture Alpha", language=EDITION
            )
        )
        session.flush()
        run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=0))
        alpha = (
            session.query(VersionedEntity)
            .filter(VersionedEntity.external_id == external_id_for(EDITION, ALPHA))
            .one()
        )
        attributed = (
            session.query(VersionedChange).filter(VersionedChange.entity_id == alpha.id).all()
        )
        kinds = sorted(c.change_kind for c in attributed)
        assert "move" in kinds, "the move is attributed to the SAME entity"
        assert kinds.count("edit") + kinds.count("create") == 3
        assert session.query(VersionedEntity).count() == 1, (
            "a title-keyed store would now hold two entities for one page"
        )


def test_a_LEGACY_title_keyed_entity_is_reconciled_when_the_stream_names_both(lane):
    """No network, no migration that has to invent a mapping it cannot know offline."""
    from src.wiki.identity import reconcile_to_page_id

    with lane_session("wiki") as session:
        session.add(
            VersionedEntity(
                external_id=legacy_external_id_for(EDITION, "Fixture Beta"),
                title="Fixture Beta",
                language=EDITION,
            )
        )
        session.flush()
        new_id = reconcile_to_page_id(session, wiki=EDITION, title="Fixture Beta", page_id=BETA)
        assert new_id == external_id_for(EDITION, BETA)
        assert parse_external_id(new_id).page_id == BETA


def test_reconciliation_REFUSES_to_merge_when_both_forms_already_exist(lane):
    """Merging means choosing a surviving baseline unlogged, on a background thread."""
    from src.wiki.identity import reconcile_to_page_id

    with lane_session("wiki") as session:
        session.add(
            VersionedEntity(external_id=legacy_external_id_for(EDITION, "Fixture Beta"), language=EDITION)
        )
        session.add(VersionedEntity(external_id=external_id_for(EDITION, BETA), language=EDITION))
        session.flush()
        assert reconcile_to_page_id(session, wiki=EDITION, title="Fixture Beta", page_id=BETA) is None
        assert session.query(VersionedEntity).count() == 2, "both survive, visibly"


# --------------------------------------------------------------------------- #
# Q713: log events.
# --------------------------------------------------------------------------- #
def test_a_DELETED_page_keeps_its_text_and_is_marked_missing(lane, corpus_ready):
    """Q713 = a: "a deleted page keeps its last text and is marked deleted.\""""
    adapter = _adapter()
    _drive(adapter)
    with lane_session("wiki") as session:
        gamma = VersionedEntity(
            external_id=external_id_for(EDITION, GAMMA), title="Fixture Gamma", language=EDITION
        )
        session.add(gamma)
        session.flush()
        # A version stored BEFORE the delete is what must survive it.
        from src.versioned.revisions import record_revision

        record_revision(session, gamma, revision_ref="1008", text="gamma text before deletion")
        session.flush()
        run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=5))
        session.refresh(gamma)
        kept = session.query(VersionedRevision).filter(VersionedRevision.entity_id == gamma.id).all()
        assert any(r.content for r in kept), "the last text survives the deletion"
        assert gamma.deleted_at is not None, "the page is MARKED, not silently unchanged"


# --------------------------------------------------------------------------- #
# Q705: the facts, and the absence.
# --------------------------------------------------------------------------- #
def test_a_fact_the_source_never_answered_has_NO_ROW_rather_than_a_zero(lane):
    """The whole reason the facts table is a row per fact."""
    from src.wiki.pagefacts import facts_from_page, read_facts, store_facts

    client = FixtureWikiClient()
    pages = client.fetch_hot_pages(EDITION, [ALPHA])
    page = pages[ALPHA]
    facts = facts_from_page(page, wikitext=page["text"])
    with lane_session("wiki") as session:
        entity = VersionedEntity(external_id=external_id_for(EDITION, ALPHA), language=EDITION)
        session.add(entity)
        session.flush()
        store_facts(session, entity.id, facts, revision_ref=str(page["revid"]))
        stored = read_facts(session, entity.id)
    assert "length_bytes" in stored, "a field the fixture DOES answer"
    for never_answered in ("qid", "coordinates", "assessment_class", "sitelink_count"):
        assert never_answered not in stored, (
            f"{never_answered} was never answered; a row for it would make a gap "
            "indistinguishable from a measured zero"
        )


def test_a_measured_zero_is_STORED_as_a_zero(lane):
    """The other half. An over-tight gate reads as conservative while deleting data."""
    from src.wiki.pagefacts import facts_from_page

    facts = facts_from_page({"images": [], "extlinks": []})
    assert facts["image_count"] == 0
    assert facts["external_link_count"] == 0


def test_a_fact_name_outside_the_vocabulary_is_REFUSED(lane):
    """A typo'd fact is one nothing will read again and nothing will report missing."""
    from src.wiki.pagefacts import UnknownFactError, store_facts

    with lane_session("wiki") as session:
        entity = VersionedEntity(external_id=external_id_for(EDITION, ALPHA), language=EDITION)
        session.add(entity)
        session.flush()
        with pytest.raises(UnknownFactError, match="not a Q705 fact"):
            store_facts(session, entity.id, {"populaton": 5})
        assert session.query(VersionedEntityFact).count() == 0


# --------------------------------------------------------------------------- #
# The cursor and the gap.
# --------------------------------------------------------------------------- #
def test_the_cursor_is_STORED_so_a_restart_resumes_rather_than_replaying(lane):
    adapter = _adapter()
    _drive(adapter)
    with lane_session("wiki") as session:
        run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=0))
        cursor = session.query(VersionedCursor).filter(VersionedCursor.feed == FEED).one()
        assert cursor.token, "a lane with no stored token replays from the service's head"


def test_a_SECOND_pass_over_the_same_stream_records_duplicates_not_new_rows(lane):
    """Dedup on ``change_ref`` is what makes a replayed overlap free."""
    adapter = _adapter()
    _drive(adapter)
    with lane_session("wiki") as session:
        first = run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=0))
    second_adapter = _adapter(buffers=adapter.buffers)
    _drive(second_adapter)
    with lane_session("wiki") as session:
        second = run_feed_once(session, second_adapter, FEED, budget=ReadBudget(max_versions=0))
        assert second.changes_recorded == 0
        assert second.changes_duplicate == first.changes_recorded
        assert session.query(VersionedChange).count() == first.changes_recorded


def test_an_overflowed_buffer_writes_a_REAL_gap_row_the_operator_can_read(lane):
    """Q727's shape: a stretch we stopped looking at is PUBLISHED, never inferred away."""
    adapter = _adapter(buffers={EDITION: StreamBuffer(maxlen=3)})
    _drive(adapter)
    with lane_session("wiki") as session:
        result = run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=0))
        assert result.gap_recorded is True
        gap = session.query(VersionedGap).filter(VersionedGap.feed == FEED).one()
        assert gap.reason == "budget"
        assert gap.closed_at is None, "an open hole stays open until something closes it"


def test_a_cut_and_resumed_stream_records_EXACTLY_what_an_uninterrupted_one_did(lane):
    """A dropped connection must cost nothing but a reconnect."""
    whole = _adapter()
    _drive(whole)
    with lane_session("wiki") as session:
        uninterrupted = run_feed_once(session, whole, FEED, budget=ReadBudget(max_versions=0))
        refs_uninterrupted = sorted(r.change_ref for r in session.query(VersionedChange).all())
        for row in session.query(VersionedChange).all():
            session.delete(row)
        session.query(VersionedCursor).delete()
        session.flush()

    cut = _adapter()
    _drive(cut, cut_after=12)
    with lane_session("wiki") as session:
        resumed = run_feed_once(session, cut, FEED, budget=ReadBudget(max_versions=0))
        refs_resumed = sorted(r.change_ref for r in session.query(VersionedChange).all())
    assert resumed.changes_recorded == uninterrupted.changes_recorded
    assert refs_resumed == refs_uninterrupted


def test_the_text_of_a_watched_page_reaches_the_CORPUS_through_index_article(lane, corpus_ready):
    """``to_article`` goes through the EXISTING upsert — never a second path in."""
    from src.database.session import session_scope

    adapter = _adapter()
    _drive(adapter)
    with lane_session("wiki") as lane_db, session_scope() as corpus:
        lane_db.add(
            VersionedEntity(
                external_id=external_id_for(EDITION, DELTA), title="Fixture Delta", language=EDITION
            )
        )
        lane_db.flush()
        result = run_feed_once(
            lane_db, adapter, FEED, corpus=corpus, budget=ReadBudget(max_versions=5)
        )
    # The FIRST version of an entity becomes its immutable BASELINE, not a revision —
    # so the property to assert is that the text reached the corpus, not which of the
    # substrate's two tables it landed in. (A proxy assertion stops tracking the
    # property it stood for; this is the property.)
    assert result.articles_indexed >= 1, "the watched page's text reached the corpus"
    assert result.baselines_captured + result.revisions_stored >= 1


def test_EVERY_Q705_field_is_absent_when_the_response_omits_it(lane):
    """The general rule, driven field by field against an EMPTY page object.

    The end-to-end test above checks the fields the fixture never answers — which
    leaves the fields it ALWAYS answers untested for absence, and a mutation matrix
    found exactly that hole: replacing ``if "length" in page`` with
    ``page.get("length", 0)`` changed nothing anywhere, because no test ever handed
    this function a page without a length.

    An empty response is the input that separates "absent" from "zero" for all of
    them at once, so it is the input this asserts on.
    """
    from src.wiki.pagefacts import FACT_NAMES, facts_from_page

    assert facts_from_page({}) == {}, "a response with nothing in it must state nothing"
    for name in FACT_NAMES:
        assert name not in facts_from_page({}), name

    # And the twin, so the gate is not merely over-tight: a field that IS answered,
    # even with a zero, is present.
    answered = facts_from_page({"length": 0, "images": []})
    assert answered["length_bytes"] == 0
    assert answered["image_count"] == 0
