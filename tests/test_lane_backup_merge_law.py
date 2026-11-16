"""Living sources in a backup: the law lane's additive merge (R729, PR 2).

Two "machines" are two data directories, as in ``test_lane_backup_merge.py``. The live
corpus is an in-memory database standing in for ``corpus.db`` after the corpus merge:
the law lane links into it by minted strings, and only rows whose string it holds merge.
"""

from __future__ import annotations

import contextlib
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from src.backup import lane_merge
from src.database.models import Base, LawDocument, LawRevision
from src.law.lane_models import LawDocumentMeta, LawIdentity, LawProvision
from src.versioned import store


def _at(h: int) -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC).replace(hour=h)


@pytest.fixture
def machines(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()

    def use(which: Path) -> None:
        monkeypatch.setenv("OO_DATA_DIR", str(which))
        store.create_lane("law")

    yield a, b, use
    store.dispose_all()


@pytest.fixture
def corpus(monkeypatch):
    """The live corpus after the corpus merge: two documents, one version."""
    engine = create_engine("sqlite:///:memory:", future=True, connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, future=True)
    with factory() as db:
        shared = LawDocument(jurisdiction="fr", title="Loi", url="https://law.test/1", lane_key="k-shared")
        new = LawDocument(jurisdiction="fr", title="Loi (fr)", url="https://law.test/2", lane_key="k-new")
        db.add_all([shared, new])
        db.flush()
        db.add(LawRevision(document_id=shared.id, content_hash="h1", lane_key="r1"))
        db.commit()

    @contextlib.contextmanager
    def scope():
        s = factory()
        try:
            yield s
            s.commit()
        finally:
            s.close()

    monkeypatch.setattr("src.database.session.session_scope", scope)
    return factory


def _identity(s, ident: str, **kw) -> LawIdentity:
    row = LawIdentity(
        identity_scheme="eli", jurisdiction_alpha3="FRA", document_identity=ident,
        jurisdiction_level="national", doc_type="statute", **kw,
    )
    s.add(row)
    s.flush()
    return row


def _meta(s, key: str, identity: LawIdentity, **kw) -> None:
    s.add(LawDocumentMeta(lane_key=key, identity_id=identity.id, language="fr", translation_kind="original", **kw))


def _seed_b(b, use, tmp_path) -> Path:
    use(b)
    with store.lane_session("law") as s:
        filler = _identity(s, "loi-1", issuing_body="Parlement", enacted_on="2018")
        stray = _identity(s, "loi-orphan")  # only an unlinked version belongs to it
        _identity(s, "loi-empty")  # no version at all
        _meta(s, "k-shared", filler, title="Loi relative", source_url="https://law.test/1")
        _meta(s, "k-new", filler, title="Loi (texte)", licence_id="licence-ouverte-2.0")
        _meta(s, "k-orphan", stray, title="Nowhere")
        s.add(LawProvision(revision_lane_key="r1", document_lane_key="k-elsewhere", address="art-1",
                           text="Article 1", content_hash="p1"))
        s.add(LawProvision(revision_lane_key="r9", document_lane_key="k-orphan", address="art-1",
                           text="Article 1 bis", content_hash="p9"))
        s.commit()
    snap = tmp_path / "snap" / "law.db"
    entry = lane_merge.snapshot_lane_for_backup("law", snap)
    assert entry["name"] == "lanes/law.db"
    store.dispose_lane("law")
    return snap


def _seed_a(a, use) -> None:
    use(a)
    with store.lane_session("law") as s:
        local = _identity(s, "loi-1")
        _meta(s, "k-shared", local, title=None, source_url="https://law.test/local")
        s.commit()


def _state() -> dict:
    with store.lane_session("law") as s:
        return {
            "ids": sorted((r.document_identity, r.issuing_body, r.enacted_on) for r in s.scalars(select(LawIdentity))),
            "meta": sorted((r.lane_key, r.title, r.source_url, r.licence_id) for r in s.scalars(select(LawDocumentMeta))),
            "prov": sorted((r.revision_lane_key, r.document_lane_key, r.address) for r in s.scalars(select(LawProvision))),
        }


def test_law_lane_merges_only_what_the_corpus_links(machines, tmp_path, corpus):
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    rep = lane_merge.merge_lane_file("law", snap, [None])
    t = rep["tables"]
    # The identity is filled, never replaced; an identity no merged version belongs to stays out.
    assert t["law_identities"] == {"inserted": 0, "filled": 1}
    assert t["law_document_meta"] == {"inserted": 1, "filled": 1, "not_linked": 1}
    assert t["law_provisions"] == {"inserted": 1, "not_linked": 1}
    st = _state()
    assert st["ids"] == [("loi-1", "Parlement", "2018")]
    assert st["meta"] == [
        ("k-new", "Loi (texte)", None, "licence-ouverte-2.0"),
        # A value already here is kept (the local source_url), a gap is filled (the title).
        ("k-shared", "Loi relative", "https://law.test/local", "unknown"),
    ]
    # The provision's document is the corpus's own, never the backup's.
    assert st["prov"] == [("r1", "k-shared", "art-1")]
    # The new version joined the local identity group.
    with store.lane_session("law") as s:
        ids = {m.identity_id for m in s.scalars(select(LawDocumentMeta))}
    assert len(ids) == 1

    before = _state()
    again = lane_merge.merge_lane_file("law", snap, [None])
    assert _state() == before
    assert again["tables"]["law_document_meta"]["inserted"] == 0
    assert again["tables"]["law_provisions"]["inserted"] == 0


def test_a_failed_law_merge_leaves_the_lane_as_it_was(machines, tmp_path, corpus, monkeypatch):
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    before = _state()

    def boom(conn, out):
        raise RuntimeError("late failure")

    monkeypatch.setitem(lane_merge._STEPS, "law", (*lane_merge._STEPS["law"], boom))
    staging = tmp_path / "staging"
    (staging / "lanes").mkdir(parents=True)
    shutil.copy2(snap, staging / "lanes" / "law.db")
    rep = lane_merge.merge_staged_lanes(staging, [{"name": "lanes/law.db", "kind": "law"}], [None])
    assert rep["lanes"][0]["state"] == "failed"
    assert _state() == before


def test_a_wiki_member_is_not_merged_as_law(machines, tmp_path, corpus, monkeypatch):
    a, b, use = machines
    monkeypatch.setenv("OO_DATA_DIR", str(b))
    store.create_lane("wiki")
    snap = tmp_path / "snap" / "wiki.db"
    lane_merge.snapshot_lane_for_backup("wiki", snap)
    store.dispose_all()
    _seed_a(a, use)
    before = _state()
    with pytest.raises(lane_merge.LaneMergeError):
        lane_merge.merge_lane_file("law", snap, [None])
    assert _state() == before


def test_a_new_law_joins_with_its_own_identity_and_honest_vocabularies(machines, tmp_path, corpus, monkeypatch):
    """Opus read on PR 2: the new-identity insert, the id remap, unknown vocabularies stored as
    the honest unknown, future dates clamped, and provenance fields filled only across the same
    provenance."""
    a, b, use = machines
    use(b)
    with store.lane_session("law") as s:
        _identity(s, "pad-1")  # shifts the backup's ids away from this machine's
        _identity(s, "pad-2")
        other = _identity(s, "loi-2", issuing_body="Sénat")
        s.add(LawDocumentMeta(lane_key="k-new", identity_id=other.id, language=" FR ", translation_kind=" Original",
                              licence_id="made-up-licence", granularity="chapter", title="Loi 2",
                              first_seen_at=datetime(2999, 1, 1, tzinfo=UTC), updated_at=datetime(2999, 1, 1, tzinfo=UTC)))
        loi1 = _identity(s, "loi-1")
        s.add(LawDocumentMeta(lane_key="k-shared", identity_id=loi1.id, language="fr", translation_kind="foreign-government",
                              translated_by="Government of X", source_authority="Catalogue X"))
        s.commit()
    snap = tmp_path / "snap" / "law.db"
    lane_merge.snapshot_lane_for_backup("law", snap)
    store.dispose_lane("law")
    use(a)
    with store.lane_session("law") as s:
        local = _identity(s, "loi-1")
        s.add(LawDocumentMeta(lane_key="k-shared", identity_id=local.id, language="fr", translation_kind="official"))
        s.commit()

    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_identities"]["inserted"] == 1
    with store.lane_session("law") as s:
        ident = s.scalars(select(LawIdentity).where(LawIdentity.document_identity == "loi-2")).one()
        new = s.scalars(select(LawDocumentMeta).where(LawDocumentMeta.lane_key == "k-new")).one()
        shared = s.scalars(select(LawDocumentMeta).where(LawDocumentMeta.lane_key == "k-shared")).one()
        assert new.identity_id == ident.id and ident.issuing_body == "Sénat"
        assert (new.language, new.translation_kind, new.licence_id, new.granularity) == ("fr", "original", "unknown", "act")
        assert new.first_seen_at.year < 2999 and new.updated_at.year < 2999
        # The local row says "official, body not recorded": another provenance's body is not put beside it.
        assert (shared.translation_kind, shared.translated_by, shared.source_authority) == ("official", None, None)
        assert s.scalars(select(LawIdentity).where(LawIdentity.document_identity.like("pad-%"))).all() == []
    before = _state()
    lane_merge.merge_lane_file("law", snap, [None])
    assert _state() == before


def test_a_version_key_the_corpus_holds_twice_links_no_provision(machines, tmp_path, corpus):
    with corpus() as db:
        new = db.scalars(select(LawDocument).where(LawDocument.lane_key == "k-new")).one()
        db.add(LawRevision(document_id=new.id, content_hash="h2", lane_key="r1"))
        db.commit()
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_provisions"] == {"inserted": 0, "not_linked": 2}


def test_a_law_member_with_a_view_under_a_law_table_is_refused(machines, tmp_path, corpus):
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    before = _state()
    con = sqlite3.connect(snap)
    con.execute("DROP TABLE law_provisions")
    con.execute("CREATE VIEW law_provisions AS SELECT 'r1' AS revision_lane_key, 'x' AS document_lane_key, 'a' AS address")
    con.commit()
    con.close()
    with pytest.raises(lane_merge.LaneMergeError):
        lane_merge.merge_lane_file("law", snap, [None])
    assert _state() == before


def test_a_document_key_the_corpus_holds_twice_links_nothing(machines, tmp_path, corpus):
    with corpus() as db:
        db.add(LawDocument(jurisdiction="fr", title="Copie", url="https://law.test/3", lane_key="k-new"))
        db.commit()
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_document_meta"]["inserted"] == 0
    assert rep["tables"]["law_document_meta"]["not_linked"] == 2
