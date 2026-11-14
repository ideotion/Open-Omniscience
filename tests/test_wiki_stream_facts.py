"""The stream writes Q705's facts with each version it stores (Lane M's finding, 2026-11-14).

The Living sources coordinates layer reads ``versioned_entity_facts``, and nothing in
production wrote it: ``WikiStreamAdapter.fetch_version`` already asked for the Q705
props and then kept only the text. These tests pin the wiring:

* ``fetch_version`` fills ``FetchedVersion.facts`` from the SAME response (no new request);
* the pipeline hands them back to the adapter's ``store_facts`` hook INSIDE the version's
  savepoint, so a failed fact write rolls the version back with it;
* a field the source did not answer has no row; a lane without the hook stores nothing.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import pytest

from src.testing.wiki_fixture import FixtureWikiClient
from src.versioned.adapters.base import FetchedVersion, ReadBudget
from src.versioned.models import VersionedEntity, VersionedEntityFact, VersionedRevision
from src.versioned.pipeline import _store_facts, run_feed_once
from src.versioned.store import create_lane, dispose_all, lane_session
from src.wiki.identity import external_id_for
from src.wiki.lane import WikiStreamAdapter
from tests.test_wiki_lane_end_to_end import ALPHA, DELTA, EDITION, FEED, _drive


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


class _Client(FixtureWikiClient):
    """The fixture client, with coordinates and a Wikidata item on one page, as a real HOT response carries them."""

    def fetch_hot_pages(self, wiki, pageids, *, with_assessments=False):
        pages = super().fetch_hot_pages(wiki, pageids, with_assessments=with_assessments)
        for pid, page in pages.items():
            if pid == DELTA and not page.get("missing"):
                page = dict(page)
                page["coordinates"] = [{"lat": 48.8606, "lon": 2.3376, "primary": True, "globe": "earth"}]
                page["pageprops"] = {"wikibase_item": "Q19675"}
                pages[pid] = page
        return pages


def _facts(session, entity_id):
    from src.wiki.pagefacts import read_facts

    return read_facts(session, entity_id)


def test_fetch_version_reads_the_facts_from_the_same_response():
    adapter = WikiStreamAdapter(client=_Client(), editions=(EDITION,))
    v = adapter.fetch_version(external_id_for(EDITION, DELTA))
    assert v is not None and v.facts
    assert v.facts["coordinates"] == {"lat": 48.8606, "lon": 2.3376}, "lat/lon only, the globe is not Q705's"
    assert v.facts["qid"] == "Q19675"
    assert "length_bytes" in v.facts


def test_a_page_the_source_answered_without_coordinates_carries_none():
    adapter = WikiStreamAdapter(client=_Client(), editions=(EDITION,))
    v = adapter.fetch_version(external_id_for(EDITION, ALPHA))
    assert v is not None
    assert "coordinates" not in (v.facts or {}) and "qid" not in (v.facts or {})


def test_a_pass_stores_the_facts_with_the_version(lane):
    adapter = WikiStreamAdapter(client=_Client(), editions=(EDITION,))
    _drive(adapter)
    with lane_session("wiki") as session:
        entity = VersionedEntity(external_id=external_id_for(EDITION, DELTA), title="Fixture Delta", language=EDITION)
        session.add(entity)
        session.flush()
        result = run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=5))
        assert result.baselines_captured + result.revisions_stored >= 1
        stored = _facts(session, entity.id)
        assert stored["coordinates"] == {"lat": 48.8606, "lon": 2.3376}
        assert stored["qid"] == "Q19675"
        rows = session.query(VersionedEntityFact).filter(VersionedEntityFact.entity_id == entity.id).all()
        assert rows and all(r.revision_ref for r in rows), "each fact names the version that answered it"
        for never_answered in ("assessment_class", "sitelink_count"):
            assert never_answered not in stored


def test_a_failed_fact_write_rolls_the_version_back_with_it(lane, monkeypatch):
    adapter = WikiStreamAdapter(client=_Client(), editions=(EDITION,))
    _drive(adapter)

    def _boom(self, lane_session_, entity_id, version):
        raise RuntimeError("disk full")

    monkeypatch.setattr(WikiStreamAdapter, "store_facts", _boom)
    with lane_session("wiki") as session:
        entity = VersionedEntity(external_id=external_id_for(EDITION, DELTA), title="Fixture Delta", language=EDITION)
        session.add(entity)
        session.flush()
        result = run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=5))
        assert any("store" in e for e in result.errors)
        assert session.query(VersionedRevision).filter(VersionedRevision.entity_id == entity.id).count() == 0
        assert session.query(VersionedEntityFact).count() == 0


def test_the_substrate_stores_nothing_for_a_lane_without_the_hook_or_without_facts():
    calls = []

    class _NoHook:
        kind = "law"

    class _Hook:
        kind = "wiki"

        def store_facts(self, lane, entity_id, version):
            calls.append(entity_id)

    entity = VersionedEntity(external_id="x", language="en")
    entity.id = 7
    with_facts = FetchedVersion(external_id="x", revision_ref="1", text="t", facts={"length_bytes": 1})
    without = FetchedVersion(external_id="x", revision_ref="1", text="t")
    _store_facts(None, _NoHook(), entity, with_facts)
    _store_facts(None, _Hook(), entity, without)
    assert calls == []
    _store_facts(None, _Hook(), entity, with_facts)
    assert calls == [7]


# --------------------------------------------------------------------------- #
# A fact the page LOSES is cleared, but only when the source was asked for it.
# --------------------------------------------------------------------------- #
class _LostCoords(_Client):
    """The same page answered later WITHOUT coordinates or a Wikidata item: it lost them."""

    def fetch_hot_pages(self, wiki, pageids, *, with_assessments=False):
        pages = FixtureWikiClient.fetch_hot_pages(self, wiki, pageids, with_assessments=with_assessments)
        return {pid: {k: v for k, v in p.items() if k not in ("coordinates", "pageprops")} for pid, p in pages.items()}


def test_a_requested_prop_answered_absent_is_named_unanswered():
    from src.wiki.pagefacts import unanswered_facts

    assert unanswered_facts({}, requested_props=("pageprops", "coordinates")) == ("qid", "coordinates")
    assert unanswered_facts({"qid": "Q1"}, requested_props=("pageprops",)) == ()
    assert unanswered_facts({}, requested_props=()) == (), "nothing asked, nothing answered"
    # assessments were not asked of this edition: their absence is a gap
    assert "assessment_class" not in unanswered_facts({}, requested_props=("pageprops", "coordinates", "categories"))


def test_the_id_path_asks_for_the_props_it_will_clear():
    """The adapter's ``requested`` set is the HOT builder's own; drift between them would clear on a gap."""
    from src.wiki import mediawiki as mw

    asked = set(mw.build_hot_pages_params([1])["prop"].split("|"))
    assert set(mw.HOT_PROPS) == asked
    assert {"pageprops", "coordinates", "categories"} <= asked


def test_a_lost_coordinate_and_qid_are_cleared_on_the_next_pass(lane):
    first = WikiStreamAdapter(client=_Client(), editions=(EDITION,))
    _drive(first)
    with lane_session("wiki") as session:
        entity = VersionedEntity(external_id=external_id_for(EDITION, DELTA), title="Fixture Delta", language=EDITION)
        session.add(entity)
        session.flush()
        run_feed_once(session, first, FEED, budget=ReadBudget(max_versions=5))
        assert "coordinates" in _facts(session, entity.id)
        entity_id = entity.id

    later = WikiStreamAdapter(client=_LostCoords(), editions=(EDITION,))
    v = later.fetch_version(external_id_for(EDITION, DELTA))
    assert v is not None and set(v.facts_unanswered) >= {"coordinates", "qid"}
    with lane_session("wiki") as session:
        _store_facts(session, later, session.get(VersionedEntity, entity_id), v)
        stored = _facts(session, entity_id)
    assert "coordinates" not in stored and "qid" not in stored, "the page left the map"
    assert "length_bytes" in stored, "a fact still answered is kept"


def test_the_title_path_never_clears(lane, monkeypatch):
    """By title the request's props are not known here, so an absence is a gap and nothing goes."""
    adapter = WikiStreamAdapter(client=_LostCoords(), editions=(EDITION,))
    monkeypatch.setattr(
        _LostCoords, "fetch_current_text", lambda self, wiki, title: {"title": title, "revid": 5, "text": "plain text"}, raising=False
    )
    v = adapter.fetch_version(f"{EDITION}:Some title")
    assert v is not None and v.facts_unanswered == ()


def test_an_incomplete_answer_clears_nothing():
    """Lane M's must-fix: a ``continue`` without ``batchcomplete`` leaves props UNANSWERED, not lost."""
    from src.wiki.mediawiki import parse_hot_pages

    page = {"pageid": 104, "title": "Fixture Delta", "revisions": [{"revid": 9, "slots": {"main": {"content": "text"}}}]}
    cut = parse_hot_pages({"continue": {"clcontinue": "104|X", "continue": "||"}, "query": {"pages": [page]}})
    whole = parse_hot_pages({"batchcomplete": True, "query": {"pages": [page]}})
    assert cut[104]["props_complete"] is False
    assert whole[104]["props_complete"] is True
    assert parse_hot_pages({"query": {"pages": [page]}})[104]["props_complete"] is False, "neither is not complete"

    class _Cut(_LostCoords):
        def fetch_hot_pages(self, wiki, pageids, *, with_assessments=False):
            pages = super().fetch_hot_pages(wiki, pageids, with_assessments=with_assessments)
            return {pid: {**p, "props_complete": False} for pid, p in pages.items()}

    v = WikiStreamAdapter(client=_Cut(), editions=(EDITION,)).fetch_version(external_id_for(EDITION, DELTA))
    assert v is not None and v.facts_unanswered == (), "an answer cut short is a gap, never a loss"


def test_a_failed_clear_rolls_the_version_back_with_it(lane, monkeypatch):
    import src.wiki.pagefacts as pf

    adapter = WikiStreamAdapter(client=_LostCoords(), editions=(EDITION,))
    _drive(adapter)

    def _boom(session, entity_id, names):
        raise RuntimeError("disk full")

    monkeypatch.setattr(pf, "clear_facts", _boom)
    with lane_session("wiki") as session:
        entity = VersionedEntity(external_id=external_id_for(EDITION, DELTA), title="Fixture Delta", language=EDITION)
        session.add(entity)
        session.flush()
        result = run_feed_once(session, adapter, FEED, budget=ReadBudget(max_versions=5))
        assert any("store" in e for e in result.errors)
        assert session.query(VersionedRevision).filter(VersionedRevision.entity_id == entity.id).count() == 0
        assert session.query(VersionedEntityFact).count() == 0
