"""The law metadata model (brief S04-10 S2) — the synthetic jurisdiction, end to end.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Q906 = a's shape (document → versions → provisions with a metadata block), Q908's one
identity with N language versions, Q901's NOTE (each translation its OWN tracked
document, linked both ways), Q904's granularity, Q905's observed-dating label, Q902's
document types and Q927's licence — measured on the `ZZZ` synthetic jurisdiction
(Q1018 = a), which runs the whole pipeline without a socket.

WHAT THE SKEPTIC MATRIX IS AIMED AT. Every guard below exists because the failure it
describes is SILENT and PLAUSIBLE:

* a translation labelled as the original text of a law;
* two countries' "Act 5 of 2020" merged into one document because the identifier was
  unique-looking;
* one law's licence shown under another law's title after a restore renumbered rows;
* a capture date printed as the date a text came into force;
* a closed vocabulary that a near-miss spelling walks straight through, because the
  index guarding it compares bytes.

None of those raises. Each is a page that reads correctly and says something false.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision
from src.law import lane_sync
from src.law.adapters import Provision
from src.law.adapters.clml import parse_clml
from src.law.lane_models import LawDocumentMeta, LawIdentity, LawProvision
from src.law.model import (
    DOC_TYPES,
    LICENCES,
    TRANSLATION_KINDS,
    LawModelError,
    document_identity_for,
    ensure_identity,
    identity_group,
    licence_of,
    mint_lane_key,
    provenance_of,
    provisions_for,
    redistribution_state,
    register_document,
    remint_identity,
    set_translation_kind,
    store_provisions,
)
from src.law.track import track_document
from src.versioned import store

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "law" / "synthetic"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, body: bytes) -> None:
        self.raw_content = body
        self.content = body.decode("utf-8")
        self.content_type = "application/xml"


class _ScriptedFetcher:
    """Answers each fetch with the next fixture. Never touches the network."""

    def __init__(self, names: list[str]) -> None:
        self._bodies = [(_FIXTURES / f"{n}.clml.xml").read_bytes() for n in names]
        self.calls = 0

    def fetch(self, _url, **_kw):
        body = self._bodies[min(self.calls, len(self._bodies) - 1)]
        self.calls += 1
        return _Result(body)


@pytest.fixture
def corpus(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'corpus.db'}",
        future=True,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, future=True)
    engine.dispose()


@pytest.fixture
def lane(tmp_path, monkeypatch):
    """A real ``law.db`` in a throwaway data directory.

    ``dispose_all`` on the way IN as well as out: the engine map is process-global, so a
    lane another test left open would hold a connection to a directory this one is about
    to replace — the recorded hazard that makes lane tests flaky in a full-suite run.
    """
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        store.create_lane("law")
        yield tmp_path
    finally:
        store.dispose_all()


def _doc(session, **kw) -> LawDocument:
    fields = {
        "jurisdiction": "ZZZ",
        "title": "Measurement Standards Act",
        "url": "https://gazette.zzz.test/act/2019/7/data.xml",
        "official_url": "https://gazette.zzz.test/act/2019/7",
        "category": "legislation",
        "consolidated": True,
        "language": "zxx",
        **kw,
    }
    doc = LawDocument(**fields)
    session.add(doc)
    session.commit()
    return doc


def _identity(session, **kw) -> LawIdentity:
    fields = {
        "scheme": "act-number",
        "jurisdiction_alpha3": "ZZZ",
        "value": "2019/7",
        "doc_type": "statute",
        "jurisdiction_level": "national",
        **kw,
    }
    return ensure_identity(session, **fields)


# ---------------------------------------------------------------------------
# The synthetic jurisdiction, end to end (the slice's acceptance)
# ---------------------------------------------------------------------------


def test_the_synthetic_jurisdiction_runs_versions_AND_provisions_end_to_end(corpus, lane):
    """Two captures of one Act: two versions, each with its own provisions at addresses.

    Driven through the REAL tracker, never by inserting rows — the point of an
    end-to-end fixture is that the wiring is what is being measured.
    """
    with corpus() as session:
        doc = _doc(session)
        first = track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        second = track_document(session, _ScriptedFetcher(["act.v2"]), doc)
        assert first["status"] == "baseline"
        assert second["status"] == "changed"
        revs = (
            session.query(LawRevision)
            .filter_by(document_id=doc.id)
            .order_by(LawRevision.id)
            .all()
        )
        assert len(revs) == 2
        keys = [r.lane_key for r in revs]
        doc_key = doc.lane_key

    assert doc_key, "the tracker must mint the document's lane key"
    assert all(keys), "every revision needs its own lane key: provisions hang off it"
    assert keys[0] != keys[1], "two versions sharing one key would share one provision set"

    with store.lane_session("law") as ls:
        v1 = provisions_for(ls, keys[0])
        v2 = provisions_for(ls, keys[1])
        assert [p.address for p in v1] == [
            "Part 1 Preliminary/1",
            "Part 1 Preliminary/2",
            "Part 2 Duties/3",
        ]
        assert [p.address for p in v2] == [
            "Part 1 Preliminary/1",
            "Part 1 Preliminary/2",
            "Part 2 Duties/3",
            "Part 2 Duties/4",
        ]
        by_address_v1 = {p.address: p for p in v1}
        by_address_v2 = {p.address: p for p in v2}
        # THE POINT OF PER-PROVISION STORAGE: the amendment touched one section and added
        # one. A whole-document byte delta cannot say that, and a fixture where every
        # provision changed could not tell the two apart.
        assert by_address_v1["Part 1 Preliminary/1"].content_hash == (
            by_address_v2["Part 1 Preliminary/1"].content_hash
        )
        assert by_address_v1["Part 2 Duties/3"].content_hash == (
            by_address_v2["Part 2 Duties/3"].content_hash
        )
        assert by_address_v1["Part 1 Preliminary/2"].content_hash != (
            by_address_v2["Part 1 Preliminary/2"].content_hash
        )
        assert "Part 2 Duties/4" not in by_address_v1
        # Every provision names the DOCUMENT as well as the version, so "everything this
        # document ever said" is one query in this file.
        assert {p.document_lane_key for p in (*v1, *v2)} == {doc_key}


def test_a_translation_is_its_own_tracked_document_linked_BOTH_WAYS(corpus, lane):
    """Q901's NOTE, verbatim: each translation individually tracked, with links.

    "Linked both ways" is checked by reading the group from EACH member, because a link
    that only resolves from the original is exactly the half-built version of this.
    """
    with corpus() as session:
        original = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), original)
        translation = _doc(
            session,
            title="Loi sur les normes de mesure",
            url="https://gazette.zzz.test/act/2019/7/fr/data.xml",
            official_url="https://gazette.zzz.test/act/2019/7/fr",
            language="zxx-fr",
        )
        track_document(session, _ScriptedFetcher(["act.translation"]), translation)
        original_key, translation_key = original.lane_key, translation.lane_key
        # Each is a document in its own right, with its own revision history.
        assert session.query(LawRevision).filter_by(document_id=original.id).count() == 1
        assert session.query(LawRevision).filter_by(document_id=translation.id).count() == 1

    with store.lane_session("law") as ls:
        metas = {m.lane_key: m for m in ls.query(LawDocumentMeta).all()}
        assert set(metas) == {original_key, translation_key}
        # Both fixtures state act-number 2019/7 in ZZZ, so they land on ONE identity —
        # which is Q908's "one document identity, N language versions" happening by
        # construction rather than by a link somebody remembered to write.
        assert len({m.identity_id for m in metas.values()}) == 1

        set_translation_kind(metas[original_key], "original")
        set_translation_kind(metas[translation_key], "official")
        metas[translation_key].translated_by = "Office of the Government Translator"
        ls.flush()

        for key, other in ((original_key, translation_key), (translation_key, original_key)):
            group = identity_group(ls, metas[key].identity_id)
            assert group is not None
            assert other in {m.lane_key for m in group.members}, (
                f"reading the group from {key} must find {other}: a link that resolves "
                "in one direction only is half of Q901's note"
            )
        group = identity_group(ls, metas[original_key].identity_id)
        assert group.original_state == "tracked"
        assert group.original.lane_key == original_key
        assert [m.lane_key for m in group.translations] == [translation_key]
        assert provenance_of(metas[translation_key]) == (
            "An official translation",
            "Office of the Government Translator",
        )


# ---------------------------------------------------------------------------
# The identity — the two failure directions Q908 has
# ---------------------------------------------------------------------------


def test_two_jurisdictions_cannot_share_one_act_number():
    a = document_identity_for("act-number", jurisdiction_alpha3="ZZZ", value="5 of 2020")
    b = document_identity_for("act-number", jurisdiction_alpha3="YYY", value="5 of 2020")
    assert a != b, "'Act 5 of 2020' is not unique on Earth; the jurisdiction is part of the key"


def test_one_identifier_cannot_FRAGMENT_across_two_spellings():
    """The other direction, and the worse one: two identities for one law.

    A merge is visible (two laws under one title); a fragmentation is not — the second
    adapter simply creates a second law, and the language group silently holds one
    member.
    """
    written_two_ways = {
        document_identity_for("celex", jurisdiction_alpha3="EUU", value="32019L0790"),
        document_identity_for("celex", jurisdiction_alpha3="eu u".replace(" ", ""), value=" 32019l0790 "),
    }
    assert len(written_two_ways) == 1


@pytest.mark.parametrize("bad", ["", "   ", "GB", "GBRA", "12"])
def test_a_jurisdiction_that_is_not_alpha3_is_refused(bad):
    with pytest.raises(LawModelError):
        document_identity_for("eli", jurisdiction_alpha3=bad, value="x")


def test_an_empty_identifier_is_refused():
    with pytest.raises(LawModelError, match="empty"):
        document_identity_for("eli", jurisdiction_alpha3="ZZZ", value="   ")


# ---------------------------------------------------------------------------
# The closed vocabularies — and the index that cannot protect them
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("spelling", ["Original", "ORIGINAL", " original ", "oRiGiNaL"])
def test_near_miss_spellings_of_a_kind_are_NORMALISED_not_stored(spelling, lane):
    """A partial unique index on ``translation_kind = 'original'`` compares BYTES.

    So ``Original`` is not "an invalid original" to the database — it is a row the
    index's predicate never sees, and a second original walks in beside the first. The
    setter is the only thing standing there.
    """
    with store.lane_session("law") as ls:
        identity = _identity(ls)
        meta = register_document(
            ls,
            lane_key=mint_lane_key(),
            identity=identity,
            language="en",
            translation_kind=spelling,
        )
        assert meta.translation_kind == "original"


@pytest.mark.parametrize("bogus", ["authoritative", "machine", "", "orig"])
def test_a_kind_outside_the_vocabulary_is_REFUSED(bogus, lane):
    with store.lane_session("law") as ls:
        identity = _identity(ls)
        with pytest.raises(LawModelError):
            register_document(
                ls,
                lane_key=mint_lane_key(),
                identity=identity,
                language="en",
                translation_kind=bogus,
            )


@pytest.mark.parametrize(
    ("refused", "because"),
    [("bill", "post-beta"), ("draft", "post-beta"), ("case-law", "not chosen")],
)
def test_the_doc_types_this_slice_may_not_record_are_refused_BY_NAME(refused, because, lane):
    """Q902's (c) and (e). The refusal NAMES the ruling, so a future session reads why.

    A bare "not in the vocabulary" would look like an oversight and invite somebody to
    add it; the message says a decision was made and where.
    """
    with store.lane_session("law") as ls:
        with pytest.raises(LawModelError) as excinfo:
            _identity(ls, doc_type=refused, value=f"2020/{refused}")
        assert "Q902" in str(excinfo.value)
        assert because in str(excinfo.value)


def test_subnational_is_refused_naming_the_CONFLICT(lane):
    """Q903 is a recorded CONFLICT, never resolved. Storing one would pick a side."""
    with store.lane_session("law") as ls:
        with pytest.raises(LawModelError) as excinfo:
            _identity(ls, jurisdiction_level="subnational")
        assert "Q903" in str(excinfo.value)
        assert "CONFLICT" in str(excinfo.value)


def test_the_vocabularies_hold_the_states_that_mean_NOBODY_SAID():
    """``unspecified`` and ``unrecorded`` are states, not categories — and not defaults
    that happen to be harmless. Each exists so the model can decline to answer."""
    assert "unspecified" in DOC_TYPES
    assert "unrecorded" in TRANSLATION_KINDS
    assert "original" in TRANSLATION_KINDS


# ---------------------------------------------------------------------------
# What the bridge refuses to guess
# ---------------------------------------------------------------------------


def test_a_tracked_document_is_NEVER_defaulted_to_being_the_original(corpus, lane):
    """The fabrication this model is most likely to commit.

    A document fetched from a national gazette usually IS the untranslated text — and
    "usually" is how a translation ends up carrying the authenticity of a law. The
    tracker records ``unrecorded`` and the group reports NO original, which is true.
    """
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        key = doc.lane_key

    with store.lane_session("law") as ls:
        meta = ls.query(LawDocumentMeta).filter_by(lane_key=key).one()
        assert meta.translation_kind == "unrecorded"
        identity = ls.get(LawIdentity, meta.identity_id)
        assert identity.doc_type == "unspecified", (
            "the legacy `category` column says 'legislation', which is not one of Q902's "
            "categories and does not imply one"
        )
        group = identity_group(ls, meta.identity_id)
        assert group.original_state == "absent"
        assert group.original is None
        assert provenance_of(meta)[0] == (
            "Whether this is the original text or a translation is not recorded"
        )


def test_an_unresolvable_jurisdiction_records_NOTHING_rather_than_junk(corpus, lane):
    """`country_display_code` returns an unrecognised value unchanged, by contract.

    Storing that in the column the whole identity is keyed on would put junk at the root
    of the model, so the bridge declines and says which document.
    """
    with corpus() as session:
        doc = _doc(session, jurisdiction="not-a-country")
        # The key is minted here rather than by the tracker, so this measures the
        # JURISDICTION guard. The first draft left it unset and got `no-lane-key` — a
        # green-looking assertion about a guard it never reached.
        doc.lane_key = mint_lane_key()
        session.commit()
        outcome = lane_sync.record_document(doc, None, None)
    assert outcome == "no-jurisdiction"
    with store.lane_session("law") as ls:
        assert ls.query(LawDocumentMeta).count() == 0


def test_a_document_with_no_lane_key_records_nothing(corpus, lane):
    with corpus() as session:
        doc = _doc(session)
        assert doc.lane_key is None
        assert lane_sync.record_document(doc, None, None) == "no-lane-key"


def test_a_LANE_FAILURE_NEVER_BREAKS_TRACKING(corpus, lane, monkeypatch):
    """The rule the bridge exists to keep. The corpus write is the primary record."""

    def _boom(_kind):
        raise RuntimeError("the lane file is on fire")

    monkeypatch.setattr(lane_sync, "create_lane", _boom)
    with corpus() as session:
        doc = _doc(session)
        result = track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        assert result["status"] == "baseline"
        assert session.query(LawRevision).filter_by(document_id=doc.id).count() == 1
        assert doc.latest_text, "the text is stored whatever the lane did"


# ---------------------------------------------------------------------------
# Q905 — a date and the method that produced it are ONE fact
# ---------------------------------------------------------------------------


def test_a_stated_date_is_labelled_official_and_an_unstated_one_observed(corpus, lane):
    with corpus() as session:
        dated = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), dated)
        rev = session.query(LawRevision).filter_by(document_id=dated.id).one()
        assert rev.valid_on == "2019-06-01"
        assert rev.valid_on_dating == "official"

        undated = _doc(
            session,
            url="https://gazette.zzz.test/act/2019/8",
            official_url="https://gazette.zzz.test/act/2019/8",
        )
        body = (
            "<html><body><main><p>An Act with no dates stated anywhere in its text. </p>"
            "<p>" + "This section restates an obligation in unchanged words. " * 8 + "</p>"
            "</main></body></html>"
        )

        class _Html:
            raw_content = body.encode("utf-8")
            content = body
            content_type = "text/html"

        class _F:
            def fetch(self, _u, **_k):
                return _Html()

        track_document(session, _F(), undated)
        rev2 = session.query(LawRevision).filter_by(document_id=undated.id).one()
        assert rev2.valid_on is None, "no date was stated; inventing one is the defect"
        assert rev2.valid_on_dating == "observed"


# ---------------------------------------------------------------------------
# Q927 — the licence, and the three states of what you may do with the text
# ---------------------------------------------------------------------------


def test_the_licence_registry_is_the_ONLY_place_a_licence_is_described(lane):
    with store.lane_session("law") as ls:
        meta = register_document(
            ls,
            lane_key=mint_lane_key(),
            identity=_identity(ls),
            language="en",
            translation_kind="unrecorded",
            licence_id="ogl-3.0",
        )
        assert licence_of(meta).name == "Open Government Licence v3.0"
        assert redistribution_state(meta) == "permitted"
        # No name, url or redistribution column exists on the row: a copy per document is
        # a copy that can disagree about what OGL v3.0 says.
        columns = {c.name for c in LawDocumentMeta.__table__.columns}
        assert "licence_name" not in columns
        assert "redistribution" not in columns


def test_forbidden_and_unknown_are_DIFFERENT_answers():
    """Q927's V1-3 exclusion turns on ``forbidden`` alone.

    Collapsing the two into one falsy value is how a forbidden source gets redistributed
    by a caller writing ``if not licence.permitted``.
    """
    assert LICENCES["all-rights-reserved"].redistribution == "forbidden"
    assert LICENCES["unknown"].redistribution == "unknown"
    assert LICENCES["all-rights-reserved"].redistribution != LICENCES["unknown"].redistribution


def test_an_unregistered_licence_token_degrades_rather_than_raising(lane):
    """Read on a rendering path: a reader should see "not recorded", never a 500."""
    with store.lane_session("law") as ls:
        meta = register_document(
            ls,
            lane_key=mint_lane_key(),
            identity=_identity(ls),
            language="en",
            translation_kind="unrecorded",
            licence_id="a-licence-nobody-registered",
        )
        assert meta.licence_id == "unknown"
        assert licence_of(meta).licence_id == "unknown"
        assert redistribution_state(meta) == "unknown"


# ---------------------------------------------------------------------------
# The group, the remint, and the provisions
# ---------------------------------------------------------------------------


def test_two_documents_claiming_to_be_the_original_still_render(lane, caplog):
    """A real defect (two adapters, one law). Picking one SILENTLY would hide it."""
    with store.lane_session("law") as ls:
        identity = _identity(ls)
        for language in ("en", "de"):
            register_document(
                ls,
                lane_key=mint_lane_key(),
                identity=identity,
                language=language,
                translation_kind="original",
            )
        with caplog.at_level("WARNING"):
            group = identity_group(ls, identity.id)
        assert group.original is not None
        assert len(group.members) == 2
        assert "claiming translation_kind='original'" in caplog.text


def test_a_remint_moves_a_lone_document_and_REFUSES_to_split_a_group(lane):
    with store.lane_session("law") as ls:
        provisional = _identity(ls, scheme="local", value="https://gazette.zzz.test/act/2019/7")
        alone = register_document(
            ls,
            lane_key=mint_lane_key(),
            identity=provisional,
            language="en",
            translation_kind="unrecorded",
        )
        real = _identity(ls, scheme="eli", value="zzz/act/2019/7")
        moved = remint_identity(
            ls, alone, scheme="eli", jurisdiction_alpha3="ZZZ", value="zzz/act/2019/7"
        )
        assert moved.id == real.id
        assert alone.identity_id == real.id

        # Now a group of two: moving ONE of them would split the law in half.
        grouped_a = register_document(
            ls, lane_key=mint_lane_key(), identity=real, language="fr", translation_kind="official"
        )
        register_document(
            ls, lane_key=mint_lane_key(), identity=real, language="de", translation_kind="official"
        )
        _identity(ls, scheme="celex", value="32019L0007")
        with pytest.raises(LawModelError, match="other language version"):
            remint_identity(
                ls, grouped_a, scheme="celex", jurisdiction_alpha3="ZZZ", value="32019L0007"
            )


def test_storing_provisions_REPLACES_a_version_rather_than_merging(lane):
    """A re-parse with a better adapter must leave exactly what the new parse says."""
    rev_key, doc_key = mint_lane_key(), mint_lane_key()
    with store.lane_session("law") as ls:
        store_provisions(
            ls,
            document_lane_key=doc_key,
            revision_lane_key=rev_key,
            provisions=[Provision(number="1", heading=None, text="one"),
                        Provision(number="2", heading=None, text="two")],
        )
        assert {p.address for p in provisions_for(ls, rev_key)} == {"1", "2"}
        store_provisions(
            ls,
            document_lane_key=doc_key,
            revision_lane_key=rev_key,
            provisions=[Provision(number="1", heading=None, text="one, revised")],
        )
        left = provisions_for(ls, rev_key)
        assert [p.address for p in left] == ["1"], "a merge would leave section 2 orphaned"
        assert left[0].text == "one, revised"


def test_a_duplicate_address_is_dropped_and_the_COUNT_says_so(lane, caplog):
    """``Provision.identifier`` falls back to the heading and then the element name, so
    two unnumbered provisions under one path genuinely collide. The count returned is
    the count STORED, so a caller comparing it against what it handed in sees the loss."""
    rev_key, doc_key = mint_lane_key(), mint_lane_key()
    twins = [
        Provision(number=None, heading=None, text="first", element="P1"),
        Provision(number=None, heading=None, text="second", element="P1"),
    ]
    with store.lane_session("law") as ls, caplog.at_level("WARNING"):
        stored = store_provisions(
            ls, document_lane_key=doc_key, revision_lane_key=rev_key, provisions=twins
        )
    assert stored == 1 < len(twins)
    assert "duplicate provision address" in caplog.text


# ---------------------------------------------------------------------------
# The schema itself
# ---------------------------------------------------------------------------


def test_the_law_tables_land_in_law_db_and_NOT_in_another_lane(tmp_path, monkeypatch):
    """Importing the law models registers them on the SHARED lane metadata.

    So a bare ``metadata.create_all`` would put three empty law tables into every
    operator's ``wiki.db`` — including operators who never tracked a law.
    """
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        store.create_lane("law")
        store.create_lane("wiki")
        from sqlalchemy import inspect

        law_tables = set(inspect(store.lane_engine("law")).get_table_names())
        wiki_tables = set(inspect(store.lane_engine("wiki")).get_table_names())
    finally:
        store.dispose_all()
    assert {"law_identities", "law_document_meta", "law_provisions"} <= law_tables
    assert {"law_identities", "law_document_meta", "law_provisions"}.isdisjoint(wiki_tables)
    assert "versioned_entities" in wiki_tables and "versioned_entities" in law_tables


def test_no_law_table_widens_the_measured_column_ceiling():
    """``tests/test_versioned_models.py`` pins the widest lane table with EXACT equality,
    so a law table at 16 columns would not merely be wide — it would redefine what that
    ratchet measures, in a file that never mentions the law."""
    from tests.test_versioned_models import COLUMN_CEILING

    for model in (LawIdentity, LawDocumentMeta, LawProvision):
        assert len(model.__table__.columns) <= COLUMN_CEILING, model.__tablename__


def test_the_provision_address_is_never_a_position():
    """A section inserted above would silently re-point every address below it."""
    early = Provision(number="2", heading=None, text="x", path=("Part 1",))
    later = Provision(number="2", heading=None, text="x", path=("Part 1",))
    assert early.identifier == later.identifier == "Part 1/2"
    assert "0" not in early.identifier and early.identifier != "1"


def test_the_parsed_fixtures_state_what_the_end_to_end_test_relies_on():
    """A fixture wrong in the code's favour is the recorded way a green suite lies."""
    v1 = parse_clml((_FIXTURES / "act.v1.clml.xml").read_bytes())
    v2 = parse_clml((_FIXTURES / "act.v2.clml.xml").read_bytes())
    assert (v1.document_number, v1.year) == ("7", "2019")
    assert (v2.document_number, v2.year) == ("7", "2019")
    assert v1.valid_on == "2019-06-01" and v2.valid_on == "2024-01-01"
    assert len(v1.provisions) == 3 and len(v2.provisions) == 4
    unchanged = {"Part 1 Preliminary/1", "Part 2 Duties/3"}
    by1 = {p.identifier: p.text for p in v1.provisions}
    by2 = {p.identifier: p.text for p in v2.provisions}
    assert all(by1[a] == by2[a] for a in unchanged), (
        "the fixture must hold two provisions CONSTANT across the amendment, or the "
        "per-provision assertions cannot distinguish a real timeline from a whole-document one"
    )


# ---------------------------------------------------------------------------
# The reader — what the model puts on screen
# ---------------------------------------------------------------------------


def _client(maker):
    from src.api.main import app
    from src.database.session import get_db

    def _db():
        d = maker()
        try:
            yield d
        finally:
            d.close()

    app.dependency_overrides[get_db] = _db
    return app


def _read(maker, doc_id: int) -> str:
    from fastapi.testclient import TestClient

    app = _client(maker)
    try:
        with TestClient(app) as c:
            return c.get(f"/api/law/documents/{doc_id}/view").text
    finally:
        app.dependency_overrides.clear()


def test_the_reader_shows_the_licence_the_provenance_and_the_identity(corpus, lane):
    """Q927 says the licence is "shown in the reader"; Q901's note says the provenance is.

    Both are read from ``law.db`` through the ONE path, and both are rendered as the
    states they are — including "not recorded", which is the answer most documents have.
    """
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        doc_id, key = doc.id, doc.lane_key

    with store.lane_session("law") as ls:
        meta = ls.query(LawDocumentMeta).filter_by(lane_key=key).one()
        meta.licence_id = "ogl-3.0"
        set_translation_kind(meta, "official")
        meta.translated_by = "Office of the Government Translator"

    body = _read(corpus, doc_id)
    assert "Licence" in body and "Open Government Licence v3.0" in body
    assert "This licence permits redistribution" in body
    assert "An official translation" in body
    # The body NAME is data beside the phrase, in its own element — a name folded into
    # the sentence would freeze the whole line in English in all eleven other locales.
    assert "<span>An official translation</span>" in body
    assert "Office of the Government Translator" in body
    assert "act-number:ZZZ:2019/7" in body


def test_the_reader_lists_the_OTHER_language_versions(corpus, lane):
    with corpus() as session:
        original = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), original)
        translation = _doc(
            session,
            title="Loi sur les normes de mesure",
            url="https://gazette.zzz.test/act/2019/7/fr/data.xml",
            official_url="https://gazette.zzz.test/act/2019/7/fr",
            language="zxx-fr",
        )
        track_document(session, _ScriptedFetcher(["act.translation"]), translation)
        original_id, translation_id = original.id, translation.id

    original_body = _read(corpus, original_id)
    assert "Other language versions" in original_body
    assert "Loi sur les normes de mesure" in original_body
    # And the other way round, because a link that resolves in one direction only is
    # half of what Q908 asks for.
    translation_body = _read(corpus, translation_id)
    assert "Measurement Standards Act" in translation_body


def test_a_document_with_no_lane_metadata_renders_WITHOUT_those_rows(corpus, lane):
    """The metadata is an ADDITION to the document. A reader that 500s because a second
    database is absent has made the text of a law unreachable over a fact about its
    licence."""
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        doc_id = doc.id
        doc.lane_key = None  # as a pre-S2 row is: tracked, with no model row
        session.commit()

    body = _read(corpus, doc_id)
    assert "Measurement Standards Act" in body, "the document still renders"
    assert "Licence" not in body, "an absent fact gets no row, rather than an empty one"


def test_an_undated_version_is_shown_DATED_BY_OBSERVATION(corpus, lane):
    """Q905 = a: such a version is "dated by observation and labelled so".

    The date and the label render as SEPARATE elements — a node holding both could match
    no locale key, so the label would be the one thing on the page that stayed English.
    """
    body_html = (
        "<html><body><main><p>An Act with no dates stated anywhere in its text. </p>"
        "<p>" + "This section restates an obligation in unchanged words. " * 8 + "</p>"
        "</main></body></html>"
    )

    class _Html:
        raw_content = body_html.encode("utf-8")
        content = body_html
        content_type = "text/html"

    class _F:
        def fetch(self, _u, **_k):
            return _Html()

    with corpus() as session:
        doc = _doc(session)
        track_document(session, _F(), doc)
        doc_id = doc.id

    body = _read(corpus, doc_id)
    assert "dated by observation" in body
    assert "<span class='muted'>dated by observation" in body, (
        "the label must be its own element or it can never be translated"
    )


def test_a_dated_version_does_NOT_carry_the_observation_label(corpus, lane):
    """The negative twin, and the one that stops the label being decoration: a page that
    always says "dated by observation" says nothing, and is wrong wherever the publisher
    did state a date."""
    with corpus() as session:
        doc = _doc(session)
        track_document(session, _ScriptedFetcher(["act.v1"]), doc)
        doc_id = doc.id

    body = _read(corpus, doc_id)
    assert "2019-06-01" in body
    assert "dated by observation" not in body


# ---------------------------------------------------------------------------
# The model's chrome, ×12
# ---------------------------------------------------------------------------

#: Every phrase the model added to the reader. Guarded the same way S1's was, and for the
#: same reason: this page only became translatable in the previous slice, so an unkeyed
#: string here is a visible defect rather than the status quo — and the informed-consent
#: non-negotiable puts a licence and a provenance claim squarely among the strings that
#: owe twelve locales.
_MODEL_CHROME = (
    "Licence",
    "Redistribution",
    "Provenance",
    "Identity",
    "This licence permits redistribution",
    "This licence forbids redistribution — the text is not exported",
    "The terms are not recorded; this app makes no claim about redistribution",
    "Licence not recorded",
    "All rights reserved — redistribution forbidden",
    "Other language versions",
    "Each language version is tracked as its own document, with its own history. They are "
    "the same law, aligned by identity.",
    "as the document states it",
    "dated by observation — this instance saw the text on this day; the source stated no "
    "date of its own",
    "recorded before this app tracked how the date was determined",
    "Whether this is the original text or a translation is not recorded",
    "The original text as issued",
    "An official translation",
    "An official translation; the publishing body is not recorded",
    "A translation published by an intergovernmental body",
    "A translation published by an intergovernmental body; which one is not recorded",
    "A translation published by another government",
    "A translation published by another government; which one is not recorded",
)


def _emitted_source() -> str:
    """The two modules that emit this chrome, with adjacent string literals collapsed."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    out = ""
    for name in ("src/api/law.py", "src/law/model.py"):
        out += re.sub(r'"\s*\n\s*(?:f)?"', "", (root / name).read_text(encoding="utf-8"))
    return out


@pytest.mark.parametrize("phrase", _MODEL_CHROME)
def test_every_model_chrome_phrase_is_a_key_in_every_locale(phrase):
    import json
    from pathlib import Path

    locales = Path(__file__).resolve().parent.parent / "src" / "static" / "locales"
    assert phrase in _emitted_source(), (
        f"{phrase!r} is keyed but nothing emits it — a drifted key translates nothing"
    )
    for path in sorted(locales.glob("*.json")):
        table = json.loads(path.read_text(encoding="utf-8"))
        assert phrase in table, f"{path.stem}.json is missing {phrase!r}"
        assert table[phrase].strip(), f"{path.stem}.json has an empty value for {phrase!r}"


def test_the_provenance_phrase_and_its_BODY_stay_separate_all_the_way_to_the_page():
    """``provenance_of`` returns a (phrase, body) PAIR, never a filled template.

    An earlier draft returned ``"An official translation published by {body}"`` and let
    the caller fill it in, which produces a text node matching no key in any locale —
    there is no ``tf`` on a server-rendered page, so the fix was phrases that need none.
    Checked at the contract, because the rendered page only shows the symptom.
    """
    from src.law.lane_models import LawDocumentMeta

    meta = LawDocumentMeta(
        lane_key="k", identity_id=1, language="fr",
        translation_kind="official", translated_by="Office of the Translator",
    )
    phrase, body = provenance_of(meta)
    assert "{" not in phrase and "}" not in phrase, "a template can never match a key"
    assert body == "Office of the Translator"
    assert phrase in _MODEL_CHROME
