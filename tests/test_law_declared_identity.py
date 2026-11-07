"""A treaty's language versions share ONE identity because the catalogue SAYS so (v0.6.0 C-L2; Q908, Q901's note).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The brief's done-when for the treaty row is "one treaty ingested in six languages, aligned". A
treaty page publishes no number an adapter can read, so before this slice each language
version was recorded as its own ``local`` identity keyed on its own URL: six pages, six unrelated
laws, and Q908's one-identity-N-languages promise broken for the one kind of instrument that is
published in several languages by construction.

EVERYTHING HERE RUNS ON THE SYNTHETIC TREATY in ``tests/fixtures/law/synthetic/treaty/`` -- invented
text, ``zxx-<lang>`` tags, hosts on the reserved ``.test`` TLD. Nothing in this file proves what the
UN Treaty Collection or WIPO Lex serve (neither is reachable from the build sandbox, and no live
treaty URL is in the tree). It proves that, given a catalogue that declares an identity, the tracker
aligns the versions it is told are one law, and ONLY those.

WHAT THE SKEPTIC MATRIX IS AIMED AT (each fails silently and reads correctly):

* two treaties merged into one because they shared a host or a URL prefix;
* the same declared value in two jurisdictions merged into one law;
* a typo in a declaration half-applied -- the doc_type recorded, the identity dropped -- so a
  language version is filed under the wrong law with nothing to say so;
* a later pass that declares nothing erasing the ``treaty`` category an earlier pass recorded;
* a document whose identity depends on whether an adapter happened to parse it that day.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.database.models import Base, LawDocument, LawRevision
from src.law import catalog as law_catalog
from src.law import lane_sync
from src.law.declared import (
    DECLARATION_KEYS,
    Declared,
    consistency_problems,
    declaration_problems,
    declared_for,
    declared_of,
)
from src.law.lane_models import LawDocumentMeta, LawIdentity
from src.law.model import LawModelError, ensure_identity, identity_group, register_document
from src.law.track import track_document
from src.law.versions import reader_payload
from src.versioned import store

_ROOT = Path(__file__).resolve().parents[1]
_TREATY = _ROOT / "tests" / "fixtures" / "law" / "synthetic" / "treaty"
_CATALOGUE = _TREATY / "catalogue.yml"
_LANGS = ("en", "fr", "es", "ru", "ar", "zh")
_URL = "https://treaties.zzz.test/mtdsg/xviii-1/{lang}"
_PROTOCOL_URL = "https://treaties.zzz.test/mtdsg/xviii-2/en"
_UNDECLARED_URL = "https://treaties.zzz.test/mtdsg/undeclared/en"
_VALUE = "mtdsg:xviii-1"

# What the synthetic catalogue states for each language version's translation kind. ``ar`` and ``zh`` state
# none, and the model must record them as the state they are rather than promote them to anything.
_KINDS = {
    "en": "original",
    "fr": "official",
    "es": "official",
    "ru": "intergovernmental",
    "ar": "unrecorded",
    "zh": "unrecorded",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, body: bytes) -> None:
        self.raw_content = body
        self.content = body.decode("utf-8")
        self.content_type = "text/html; charset=utf-8"


class _UrlFetcher:
    """Answers each URL with its fixture body. Never touches the network."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self.asked: list[str] = []

    def fetch(self, url, **_kw):
        self.asked.append(url)
        return _Result((_TREATY / self._pages[url]).read_bytes())


def _fetcher() -> _UrlFetcher:
    pages = {_URL.format(lang=lang): f"treaty.{lang}.html" for lang in _LANGS}
    pages[_PROTOCOL_URL] = "treaty.en.html"
    pages[_UNDECLARED_URL] = "treaty.en.html"
    return _UrlFetcher(pages)


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
    """A real ``law.db`` in a throwaway data directory (see ``test_law_metadata_model.lane``)."""
    store.dispose_all()
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    try:
        store.create_lane("law")
        yield tmp_path
    finally:
        store.dispose_all()


@pytest.fixture
def synthetic_catalogue(tmp_path, monkeypatch):
    """The synthetic catalogue is THE catalogue for the test: lane_sync reads it exactly as it reads the real one."""
    monkeypatch.setattr(law_catalog, "LEGAL_CATALOG_PATH", _CATALOGUE)
    monkeypatch.setattr(law_catalog, "GENERATED_CATALOG_PATH", tmp_path / "no-generated-file.yml")
    return _CATALOGUE


def _register_and_track(corpus, urls, fetcher=None):
    """Register the catalogue (the real path), then track the documents at ``urls`` and return their ids by URL."""
    fetcher = fetcher or _fetcher()
    with corpus() as session:
        law_catalog.register_documents(session, _CATALOGUE, _CATALOGUE.parent / "absent.yml")
        ids = {}
        for url in urls:
            doc = session.query(LawDocument).filter_by(url=url).one()
            track_document(session, fetcher, doc)
            ids[url] = doc.id
    return ids


def _treaty_urls():
    return [_URL.format(lang=lang) for lang in _LANGS]


# ---------------------------------------------------------------------------
# The slice's acceptance: one treaty, six languages, aligned
# ---------------------------------------------------------------------------


def test_one_treaty_in_six_languages_is_ONE_identity_with_six_tracked_documents(corpus, lane, synthetic_catalogue):
    ids = _register_and_track(corpus, _treaty_urls())

    with corpus() as session:
        docs = {d.url: d for d in session.query(LawDocument).filter(LawDocument.id.in_(ids.values())).all()}
        # Each language version is its OWN tracked document with its own baseline (Q901's note) ...
        assert {d.language for d in docs.values()} == {f"zxx-{lang}" for lang in _LANGS}
        assert all(session.query(LawRevision).filter_by(document_id=d.id).count() == 1 for d in docs.values())
        assert len({d.lane_key for d in docs.values()}) == 6

    with store.lane_session("law") as ls:
        identities = ls.query(LawIdentity).all()
        # ... and they are ONE law (Q908), by the catalogue's declaration, in the scheme the model already has.
        assert len(identities) == 1
        ident = identities[0]
        assert (ident.identity_scheme, ident.jurisdiction_alpha3, ident.document_identity) == (
            "act-number",
            "INT",
            _VALUE,
        )
        assert ident.doc_type == "treaty"
        assert ident.jurisdiction_level == "international"

        metas = {m.language: m for m in ls.query(LawDocumentMeta).all()}
        assert set(metas) == {f"zxx-{lang}" for lang in _LANGS}
        assert {m.identity_id for m in metas.values()} == {ident.id}
        assert {lang: metas[f"zxx-{lang}"].translation_kind for lang in _LANGS} == _KINDS

        # Readable from ANY member: a link that resolves from one side only is half of Q901's note.
        for meta in metas.values():
            group = identity_group(ls, meta.identity_id)
            assert {m.lane_key for m in group.members} == {m.lane_key for m in metas.values()}
        group = identity_group(ls, ident.id)
        assert group.original_state == "tracked"
        assert group.original.language == "zxx-en"
        assert sorted(m.language for m in group.translations) == sorted(f"zxx-{lang}" for lang in _LANGS if lang != "en")


def test_the_reader_of_each_version_lists_the_FIVE_others(corpus, lane, synthetic_catalogue):
    ids = _register_and_track(corpus, _treaty_urls())

    with corpus() as session:
        for lang in _LANGS:
            doc = session.get(LawDocument, ids[_URL.format(lang=lang)])
            payload = reader_payload(session, doc)
            assert payload["identifier"]["scheme"] == "act-number"
            assert payload["identifier"]["value"] == _VALUE
            assert payload["identifier"]["jurisdiction"] == "INT"
            languages = payload["languages"]
            assert sorted(entry["language"] for entry in languages) == sorted(f"zxx-{x}" for x in _LANGS)
            assert [entry["language"] for entry in languages if entry["current"]] == [f"zxx-{lang}"]
            # Every sibling is reachable because this instance tracks it, not listed as "not held".
            assert all(entry["id"] is not None for entry in languages)
            assert {entry["language"]: entry["kind"] for entry in languages} == {
                f"zxx-{x}": _KINDS[x] for x in _LANGS
            }


def test_a_second_pass_changes_nothing_and_the_category_survives(corpus, lane, synthetic_catalogue):
    """The steady state: tracking again must not fragment the group or reset what the first pass recorded."""
    fetcher = _fetcher()
    _register_and_track(corpus, _treaty_urls(), fetcher)
    with corpus() as session:
        for url in _treaty_urls():
            track_document(session, fetcher, session.query(LawDocument).filter_by(url=url).one())

    with store.lane_session("law") as ls:
        assert ls.query(LawIdentity).count() == 1
        assert ls.query(LawIdentity).one().doc_type == "treaty"
        assert ls.query(LawDocumentMeta).count() == 6


# ---------------------------------------------------------------------------
# Negative space: what must NOT be aligned
# ---------------------------------------------------------------------------


def test_a_different_treaty_on_the_same_host_and_an_undeclared_row_stay_APART(corpus, lane, synthetic_catalogue):
    ids = _register_and_track(corpus, [*_treaty_urls(), _PROTOCOL_URL, _UNDECLARED_URL])

    with store.lane_session("law") as ls:
        rows = {(i.identity_scheme, i.document_identity): i for i in ls.query(LawIdentity).all()}
        # Three laws, not one: the treaty, a second declared treaty on the same host, and the undeclared row.
        assert set(rows) == {
            ("act-number", _VALUE),
            ("act-number", "mtdsg:xviii-2"),
            ("local", _UNDECLARED_URL),
        }
        # The undeclared row is recorded EXACTLY as it was before this slice existed: local, URL-keyed,
        # nobody-said for both fields, and never promoted to a treaty because its neighbours are one.
        undeclared = rows[("local", _UNDECLARED_URL)]
        assert undeclared.doc_type == "unspecified"
        meta = ls.query(LawDocumentMeta).filter_by(identity_id=undeclared.id).one()
        assert meta.translation_kind == "unrecorded"
        protocol_meta = ls.query(LawDocumentMeta).filter_by(identity_id=rows[("act-number", "mtdsg:xviii-2")].id).all()
        assert [m.language for m in protocol_meta] == ["zxx-en"]
    assert len(ids) == 8


def test_the_same_declared_value_in_another_jurisdiction_is_NOT_the_same_law(corpus, lane, tmp_path, monkeypatch):
    twin = {
        "sources": [],
        "documents": [
            {
                "jurisdiction": jurisdiction,
                "title": f"Synthetic twin ({jurisdiction})",
                "category": "legislation",
                "consolidated": False,
                "country": jurisdiction,
                "language": "zxx-en",
                "url": f"https://twin.zzz.test/{jurisdiction}/en",
                "identity": {"scheme": "act-number", "value": "5 of 2020"},
                "doc_type": "treaty",
            }
            for jurisdiction in ("INT", "ZZZ")
        ],
    }
    path = tmp_path / "twin.yml"
    path.write_text(yaml.safe_dump(twin), encoding="utf-8")
    monkeypatch.setattr(law_catalog, "LEGAL_CATALOG_PATH", path)
    monkeypatch.setattr(law_catalog, "GENERATED_CATALOG_PATH", tmp_path / "absent.yml")
    pages = {d["url"]: "treaty.en.html" for d in twin["documents"]}
    fetcher = _UrlFetcher(pages)

    with corpus() as session:
        law_catalog.register_documents(session, path, tmp_path / "absent.yml")
        for doc in session.query(LawDocument).all():
            track_document(session, fetcher, doc)

    with store.lane_session("law") as ls:
        got = sorted((i.jurisdiction_alpha3, i.document_identity) for i in ls.query(LawIdentity).all())
        assert got == [("INT", "5 of 2020"), ("ZZZ", "5 of 2020")]


def test_a_malformed_declaration_is_UNDECLARED_not_half_applied(corpus, lane, tmp_path, monkeypatch, caplog):
    """A typo in the scheme must not leave the doc_type applied and the identity dropped, or the reverse."""
    bad = {
        "sources": [],
        "documents": [
            {
                "jurisdiction": "INT",
                "title": "Synthetic typo",
                "category": "legislation",
                "consolidated": False,
                "country": "INT",
                "language": "zxx-en",
                "url": "https://typo.zzz.test/en",
                "identity": {"scheme": "act-numbr", "value": _VALUE},
                "doc_type": "treaty",
                "translation_kind": "original",
            }
        ],
    }
    path = tmp_path / "bad.yml"
    path.write_text(yaml.safe_dump(bad), encoding="utf-8")
    monkeypatch.setattr(law_catalog, "LEGAL_CATALOG_PATH", path)
    monkeypatch.setattr(law_catalog, "GENERATED_CATALOG_PATH", tmp_path / "absent.yml")

    with caplog.at_level(logging.WARNING), corpus() as session:
        law_catalog.register_documents(session, path, tmp_path / "absent.yml")
        doc = session.query(LawDocument).one()
        track_document(session, _UrlFetcher({"https://typo.zzz.test/en": "treaty.en.html"}), doc)

    assert any("treated as undeclared" in r.getMessage() for r in caplog.records)
    with store.lane_session("law") as ls:
        ident = ls.query(LawIdentity).one()
        assert (ident.identity_scheme, ident.document_identity) == ("local", "https://typo.zzz.test/en")
        assert ident.doc_type == "unspecified"
        assert ls.query(LawDocumentMeta).one().translation_kind == "unrecorded"


# ---------------------------------------------------------------------------
# The identity inputs and the two model rules this slice changed
# ---------------------------------------------------------------------------


def _doc(**kw):
    fields = {"jurisdiction": "INT", "url": "https://treaties.zzz.test/x", "official_url": None, "id": 1}
    fields.update(kw)
    return SimpleNamespace(**fields)


def test_a_declared_identity_WINS_over_a_number_the_adapter_read():
    """Otherwise one document would change identity between passes depending on whether a parse succeeded."""
    parsed = SimpleNamespace(document_number="7", year="2019")
    declared = Declared(scheme="act-number", value=_VALUE)
    assert lane_sync._identity_inputs(_doc(), parsed, declared)[:2] == ("act-number", _VALUE)
    assert lane_sync._identity_inputs(_doc(), None, declared)[:2] == ("act-number", _VALUE)


def test_no_declaration_is_the_behaviour_that_existed_before():
    parsed = SimpleNamespace(document_number="7", year="2019")
    assert lane_sync._identity_inputs(_doc(), parsed, None) == ("act-number", "2019/7", "INT", "international")
    assert lane_sync._identity_inputs(_doc(), parsed) == lane_sync._identity_inputs(_doc(), parsed, Declared())
    assert lane_sync._identity_inputs(_doc(), None, None) == (
        "local",
        "https://treaties.zzz.test/x",
        "INT",
        "international",
    )
    # A declaration of only a doc_type states no identity, so it leaves the identity alone.
    assert lane_sync._identity_inputs(_doc(), None, Declared(doc_type="treaty"))[0] == "local"


def test_a_pass_that_states_no_doc_type_leaves_a_recorded_one_and_an_explicit_unspecified_takes_it_back(lane):
    with store.lane_session("law") as ls:
        kwargs = {"scheme": "act-number", "jurisdiction_alpha3": "INT", "value": _VALUE, "jurisdiction_level": "international"}
        # A new identity whose first caller states no category reads "unspecified", as it always did.
        assert ensure_identity(ls, doc_type=None, **kwargs).doc_type == "unspecified"
        assert ensure_identity(ls, doc_type="treaty", **kwargs).doc_type == "treaty"
        # The identity is shared by every language version: one that states nothing must not undo one that does.
        assert ensure_identity(ls, doc_type=None, **kwargs).doc_type == "treaty"
        # Saying something DOES change it, including saying "unspecified": that is how a category is taken back.
        assert ensure_identity(ls, doc_type="unspecified", **kwargs).doc_type == "unspecified"
        assert ensure_identity(ls, doc_type="treaty", **kwargs).doc_type == "treaty"
        assert ensure_identity(ls, doc_type="statute", **kwargs).doc_type == "statute"
        assert ls.query(LawIdentity).count() == 1
        # And the vocabulary is still checked BEFORE any write.
        with pytest.raises(LawModelError):
            ensure_identity(ls, doc_type="bill", **kwargs)
        assert ls.query(LawIdentity).one().doc_type == "statute"


def test_a_translation_kind_is_per_version_so_the_pass_writes_exactly_what_it_is_given(lane):
    """Retraction by omission depends on this: a version's kind is its own, so a pass that states none writes `unrecorded`."""
    with store.lane_session("law") as ls:
        ident = ensure_identity(
            ls,
            scheme="act-number",
            jurisdiction_alpha3="INT",
            value=_VALUE,
            doc_type="treaty",
            jurisdiction_level="international",
        )
        meta = register_document(ls, lane_key="k1", identity=ident, language="zxx-fr", translation_kind="original")
        assert meta.translation_kind == "original"
        assert register_document(ls, lane_key="k1", identity=ident, language="zxx-fr", translation_kind="unrecorded").translation_kind == "unrecorded"


# ---------------------------------------------------------------------------
# A declaration is taken back by editing the catalogue
# ---------------------------------------------------------------------------


def _variant(tmp_path, monkeypatch, edit):
    """Point the catalogue at a copy of the synthetic one with each row passed through ``edit(row)``."""
    data = yaml.safe_load(_CATALOGUE.read_text(encoding="utf-8"))
    for row in data["documents"]:
        edit(row)
    path = tmp_path / "variant.yml"
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(law_catalog, "LEGAL_CATALOG_PATH", path)
    return path


def _repass(corpus, urls):
    fetcher = _fetcher()
    with corpus() as session:
        for url in urls:
            track_document(session, fetcher, session.query(LawDocument).filter_by(url=url).one())


def _kinds():
    with store.lane_session("law") as ls:
        return {m.language: m.translation_kind for m in ls.query(LawDocumentMeta).all()}


def test_moving_the_original_to_another_version_leaves_exactly_one_original(corpus, lane, synthetic_catalogue, tmp_path, monkeypatch, caplog):
    """The reviewer's scenario: en declared `original`, then the operator moves it to fr. The database must follow."""
    _register_and_track(corpus, _treaty_urls())
    assert _kinds()["zxx-en"] == "original"

    def move(row):
        if row["language"] == "zxx-en":
            row.pop("translation_kind", None)
        if row["language"] == "zxx-fr":
            row["translation_kind"] = "original"

    _variant(tmp_path, monkeypatch, move)
    _repass(corpus, _treaty_urls())

    kinds = _kinds()
    assert kinds["zxx-en"] == "unrecorded" and kinds["zxx-fr"] == "original"
    assert list(kinds.values()).count("original") == 1
    with caplog.at_level(logging.WARNING), store.lane_session("law") as ls:
        group = identity_group(ls, ls.query(LawIdentity).one().id)
        assert group.original.language == "zxx-fr"
    assert not [r for r in caplog.records if "claiming translation_kind='original'" in r.getMessage()]


def test_an_explicit_unrecorded_takes_a_kind_back_too(corpus, lane, synthetic_catalogue, tmp_path, monkeypatch):
    _register_and_track(corpus, _treaty_urls())
    _variant(tmp_path, monkeypatch, lambda row: row.update(translation_kind="unrecorded"))
    _repass(corpus, _treaty_urls())
    assert set(_kinds().values()) == {"unrecorded"}


def test_a_category_is_taken_back_by_declaring_unspecified_and_NOT_by_omitting_it(corpus, lane, synthetic_catalogue, tmp_path, monkeypatch):
    _register_and_track(corpus, _treaty_urls())

    _variant(tmp_path, monkeypatch, lambda row: row.pop("doc_type", None))
    _repass(corpus, _treaty_urls())
    with store.lane_session("law") as ls:
        # Omitting it makes no statement, so the identity keeps what the other passes recorded ...
        assert ls.query(LawIdentity).one().doc_type == "treaty"

    _variant(tmp_path, monkeypatch, lambda row: row.update(doc_type="unspecified"))
    _repass(corpus, _treaty_urls())
    with store.lane_session("law") as ls:
        # ... and saying `unspecified` outright is a statement, which takes it back.
        assert ls.query(LawIdentity).one().doc_type == "unspecified"


def test_a_version_that_omits_doc_type_does_not_trade_the_column_back_and_forth_with_the_others(corpus, lane, synthetic_catalogue, tmp_path, monkeypatch):
    """Five versions declare `treaty`, one declares nothing: any pass order must leave `treaty`."""
    _register_and_track(corpus, _treaty_urls())
    _variant(tmp_path, monkeypatch, lambda row: row.pop("doc_type", None) if row["language"] == "zxx-zh" else None)
    for order in (_treaty_urls(), list(reversed(_treaty_urls()))):
        _repass(corpus, order)
        with store.lane_session("law") as ls:
            assert ls.query(LawIdentity).one().doc_type == "treaty"


def test_changing_the_identity_re_files_that_version_and_leaves_the_others(corpus, lane, synthetic_catalogue, tmp_path, monkeypatch):
    _register_and_track(corpus, _treaty_urls())

    def refile(row):
        if row["language"] == "zxx-zh":
            row["identity"] = {"scheme": "act-number", "value": "mtdsg:xviii-9"}

    _variant(tmp_path, monkeypatch, refile)
    _repass(corpus, [_URL.format(lang="zh")])
    with store.lane_session("law") as ls:
        by_value = {
            i.document_identity: sorted(m.language for m in ls.query(LawDocumentMeta).filter_by(identity_id=i.id))
            for i in ls.query(LawIdentity).all()
        }
    assert by_value == {_VALUE: sorted(f"zxx-{x}" for x in _LANGS if x != "zh"), "mtdsg:xviii-9": ["zxx-zh"]}


def _row(**over):
    row = {
        "jurisdiction": "INT",
        "url": "https://treaties.zzz.test/x",
        "identity": {"scheme": "act-number", "value": _VALUE},
        "doc_type": "treaty",
        "translation_kind": "official",
    }
    row.update(over)
    return row


def test_a_well_formed_declaration_has_no_problems_and_normalises():
    assert declaration_problems(_row()) == []
    got = declared_of(_row(identity={"scheme": " Act-Number ", "value": "  MTDSG:XVIII-1 "}, doc_type="Treaty"))
    assert got == Declared("act-number", _VALUE, "treaty", "official")
    assert got.has_identity


def test_a_row_that_declares_nothing_declares_nothing():
    row = {"jurisdiction": "INT", "url": "u", "title": "t", "language": "en"}
    assert not any(key in row for key in DECLARATION_KEYS)
    assert declaration_problems(row) == []
    assert declared_of(row) is None


@pytest.mark.parametrize(
    ("over", "needle"),
    [
        ({"identity": {"scheme": "act-numbr", "value": _VALUE}}, "identity.scheme"),
        ({"identity": {"scheme": "act-number", "value": "  "}}, "identity.value is empty"),
        ({"identity": {"scheme": "act-number"}}, "identity.value must be a string"),
        ({"identity": {"scheme": "act-number", "value": 1.1}}, "identity.value must be a string"),
        ({"identity": {"scheme": "act-number", "value": True}}, "identity.value must be a string"),
        ({"identity": {"scheme": 5, "value": _VALUE}}, "identity.scheme must be a string"),
        ({"identity": {"scheme": "act-number", "value": _VALUE, 1: "a", None: "b", "extra": "c"}}, "unknown keys"),
        ({"doc_type": 5}, "doc_type must be a string"),
        ({"translation_kind": True}, "translation_kind must be a string"),
        ({"identity": {"scheme": "act-number", "value": _VALUE, "language": "fr"}}, "unknown keys"),
        ({"identity": _VALUE}, "must be a mapping"),
        ({"identity": None}, "must be a mapping"),
        ({"jurisdiction": "Atlantis", "identity": {"scheme": "act-number", "value": _VALUE}}, "alpha-3"),
        ({"jurisdiction": 123, "identity": {"scheme": "act-number", "value": _VALUE}}, "alpha-3"),
        ({"jurisdiction": True, "identity": {"scheme": "act-number", "value": _VALUE}}, "alpha-3"),
        ({"doc_type": "bill"}, "bills and drafts"),
        ({"doc_type": "case-law"}, "case law"),
        ({"doc_type": "agreement"}, "doc_type"),
        ({"doc_type": None}, "doc_type"),
        ({"translation_kind": "Original text"}, "translation_kind"),
        ({"translation_kind": None}, "translation_kind"),
    ],
)
def test_every_unusable_declaration_is_named(over, needle):
    problems = declaration_problems(_row(**over))
    assert problems, f"{over} should have been refused"
    assert any(needle in p for p in problems), problems
    # And it is then treated as ABSENT as a whole, never half-applied.
    assert declared_of(_row(**over)) is None


def test_the_lookup_is_by_the_rows_own_jurisdiction_and_url_and_nothing_looser():
    catalog = {"documents": [_row(), _row(url="https://treaties.zzz.test/y", identity={"scheme": "act-number", "value": "other"})]}
    assert declared_for(catalog, jurisdiction="INT", url="https://treaties.zzz.test/x").value == _VALUE
    assert declared_for(catalog, jurisdiction="int", url="https://treaties.zzz.test/x").value == _VALUE  # stored spelling
    assert declared_for(catalog, jurisdiction="INT", url="https://treaties.zzz.test/y").value == "other"
    # Neighbours are other documents: a prefix, a host-only match, a trailing slash, another jurisdiction.
    for jurisdiction, url in (
        ("INT", "https://treaties.zzz.test/"),
        ("INT", "https://treaties.zzz.test/x/"),
        ("INT", "https://treaties.zzz.test/xx"),
        ("INT", "https://treaties.zzz.test/x?lang=fr"),
        ("ZZZ", "https://treaties.zzz.test/x"),
        ("INT", ""),
        (None, "https://treaties.zzz.test/x"),
    ):
        assert declared_for(catalog, jurisdiction=jurisdiction, url=url) is None, (jurisdiction, url)
    assert declared_for(None, jurisdiction="INT", url="https://treaties.zzz.test/x") is None
    assert declared_for({}, jurisdiction="INT", url="https://treaties.zzz.test/x") is None


def test_rows_declaring_one_law_must_agree_about_it():
    base = _row()
    assert consistency_problems([base, _row(url="u2", translation_kind="official")]) == []
    # Different laws may differ freely.
    assert consistency_problems([base, _row(url="u3", identity={"scheme": "act-number", "value": "z"}, doc_type="statute")]) == []

    disagree = consistency_problems([base, _row(url="u2", doc_type="statute")])
    assert len(disagree) == 1 and "doc_type" in disagree[0]

    two_originals = consistency_problems(
        [_row(translation_kind="original"), _row(url="u2", translation_kind="original")]
    )
    assert len(two_originals) == 1 and "original" in two_originals[0]

    # One original and several undeclared kinds is the ordinary, valid shape.
    assert consistency_problems([_row(translation_kind="original"), _row(url="u2", translation_kind="unrecorded")]) == []
    # A row with its own problem is reported by declaration_problems and left out here, not double-counted.
    assert consistency_problems([base, _row(url="u2", doc_type="bill")]) == []


def test_the_yaml_numbers_that_used_to_become_one_identity_are_refused_by_name():
    """The reviewer's probe: unquoted `1.10` and `1.1` are both the float 1.1, and `0123` is the octal 83."""
    loaded = yaml.safe_load("a: {scheme: act-number, value: 1.10}\nb: {scheme: act-number, value: 1.1}\nc: {scheme: act-number, value: 0123}\nd: {scheme: act-number, value: yes}\n")
    assert loaded["a"]["value"] == loaded["b"]["value"] == 1.1 and loaded["c"]["value"] == 83 and loaded["d"]["value"] is True
    for key in "abcd":
        problems = declaration_problems(_row(identity=loaded[key]))
        assert any("must be a string" in p for p in problems), (key, problems)
    # Quoted, the same two numbers are two laws.
    assert declaration_problems(_row(identity={"scheme": "act-number", "value": "1.10"})) == []
    assert declared_of(_row(identity={"scheme": "act-number", "value": "1.10"})).value != declared_of(
        _row(identity={"scheme": "act-number", "value": "1.1"})
    ).value


def test_an_odd_yaml_key_in_the_identity_block_cannot_break_tracking(corpus, lane, tmp_path, monkeypatch):
    """`on:`, `yes:` and `1:` are YAML bool/int keys; sorting them beside a string key raised TypeError out of record_document."""
    odd = {
        "sources": [],
        "documents": [
            {
                "jurisdiction": "INT",
                "title": "Synthetic odd key",
                "category": "legislation",
                "consolidated": False,
                "country": "INT",
                "language": "zxx-en",
                "url": "https://odd.zzz.test/en",
                "identity": {"scheme": "act-number", "value": _VALUE, 1: "a", "extra": "b"},
                "doc_type": "treaty",
            }
        ],
    }
    path = tmp_path / "odd.yml"
    path.write_text(yaml.safe_dump(odd), encoding="utf-8")
    monkeypatch.setattr(law_catalog, "LEGAL_CATALOG_PATH", path)
    monkeypatch.setattr(law_catalog, "GENERATED_CATALOG_PATH", tmp_path / "absent.yml")
    assert any("unknown keys" in p for p in declaration_problems(odd["documents"][0]))

    with corpus() as session:
        law_catalog.register_documents(session, path, tmp_path / "absent.yml")
        doc = session.query(LawDocument).one()
        track_document(session, _UrlFetcher({"https://odd.zzz.test/en": "treaty.en.html"}), doc)
        assert lane_sync.record_document(doc, None) == "recorded"
    with store.lane_session("law") as ls:
        assert ls.query(LawIdentity).one().identity_scheme == "local"


def test_a_lookup_that_raises_is_logged_and_the_document_is_recorded_undeclared(corpus, lane, synthetic_catalogue, monkeypatch, caplog):
    """`record_document` is documented never to raise; the declaration lookup runs on the collect path outside its guarded block."""

    def boom(*_a, **_k):
        raise RuntimeError("synthetic failure inside the declaration lookup")

    monkeypatch.setattr(lane_sync, "declared_for", boom)
    with caplog.at_level(logging.WARNING), corpus() as session:
        law_catalog.register_documents(session, _CATALOGUE, _CATALOGUE.parent / "absent.yml")
        doc = session.query(LawDocument).filter_by(url=_URL.format(lang="fr")).one()
        track_document(session, _fetcher(), doc)
        assert lane_sync.record_document(doc, None) == "recorded"
    assert any("declaration unreadable" in r.getMessage() for r in caplog.records)
    with store.lane_session("law") as ls:
        assert ls.query(LawIdentity).one().identity_scheme == "local"


# ---------------------------------------------------------------------------
# The catalogue tooling and the committed catalogue
# ---------------------------------------------------------------------------


def test_the_catalogue_validator_reports_a_bad_declaration_and_a_contradiction():
    sys.path.insert(0, str(_ROOT / "scripts"))
    try:
        import validate_legal_catalog as vlc
    finally:
        sys.path.pop(0)

    def _gen(**over):
        doc = {
            "jurisdiction": "INT",
            "title": "Synthetic",
            "url": "https://treaties.zzz.test/x",
            "verification": {"status": "fetched", "retrieved_at": "2026-11-04", "evidence": "synthetic"},
            "identity": {"scheme": "act-number", "value": _VALUE},
            "doc_type": "treaty",
        }
        doc.update(over)
        return doc

    def _report(*docs):
        return vlc.validate({"schema": vlc.SCHEMA, "as_of": "2026-11-04", "sources": [], "documents": list(docs)}, {"sources": [], "documents": []})

    assert _report(_gen())["errors"] == []
    bad = _report(_gen(identity={"scheme": "nope", "value": _VALUE}))["errors"]
    assert any("identity.scheme" in e for e in bad), bad
    clash = _report(_gen(), _gen(url="https://treaties.zzz.test/y", doc_type="statute"))["errors"]
    assert any("doc_type" in e and "one law has one doc_type" in e for e in clash), clash

    # The CURATED file is where an operator will put a treaty, so its rows are checked per row too.
    curated_row = {k: v for k, v in _gen().items() if k != "verification"}
    curated_row["identity"] = {"scheme": "act-numbr", "value": _VALUE}
    curated = vlc.validate(
        {"schema": vlc.SCHEMA, "as_of": "2026-11-04", "sources": [], "documents": []},
        {"sources": [], "documents": [curated_row]},
    )["errors"]
    assert any("curated documents[0]" in e and "identity.scheme" in e for e in curated), curated


def test_the_committed_catalogues_declare_nothing_the_model_would_refuse():
    """Vacuous today (no committed row declares anything), and the reason it exists: the day an operator adds one,
    a typo fails here in CI rather than turning into a quietly ungrouped language version at track time."""
    rows = []
    for path in (law_catalog.LEGAL_CATALOG_PATH, law_catalog.GENERATED_CATALOG_PATH):
        rows.extend(law_catalog._read_catalog_yaml(path)["documents"])
    for row in rows:
        assert declaration_problems(row) == [], (row.get("url"), declaration_problems(row))
    assert consistency_problems(rows) == []


def test_the_synthetic_catalogue_is_labelled_synthetic_and_names_no_real_host():
    """The fixtures stand in for sources nobody has verified; the day one of them is a real URL it is a claim."""
    from urllib.parse import urlparse

    text = _CATALOGUE.read_text(encoding="utf-8")
    assert "SYNTHETIC" in text.splitlines()[0]
    rows = yaml.safe_load(text)["documents"]
    assert len(rows) == 8
    for row in rows:
        for key in ("url", "official_url"):
            if row.get(key):
                host = urlparse(row[key]).hostname or ""
                assert host.endswith(".test"), f"{row[key]}: the synthetic catalogue may only name hosts on the reserved .test TLD"
        assert str(row["language"]).startswith("zxx-")
    for lang in _LANGS:
        body = (_TREATY / f"treaty.{lang}.html").read_text(encoding="utf-8")
        assert "SYNTHETIC FIXTURE" in body and f'lang="zxx-{lang}"' in body


def test_the_synthetic_rows_pass_the_same_check_the_tracker_applies():
    rows = yaml.safe_load(_CATALOGUE.read_text(encoding="utf-8"))["documents"]
    for row in rows:
        assert declaration_problems(row) == [], row["url"]
    assert consistency_problems(rows) == []
