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
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from src.backup import lane_merge
from src.database.models import Base, LawDocument, LawRevision
from src.law.lane_models import LawDocumentMeta, LawIdentity, LawProvision
from src.versioned import store
from tests._app_engine import app_sqlite_engine


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
    engine = app_sqlite_engine(":memory:", future=True, connect_args={"check_same_thread": False})
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


def _snap_of(b, use, tmp_path, seed) -> Path:
    use(b)
    with store.lane_session("law") as s:
        seed(s)
        s.commit()
    snap = tmp_path / "snap" / "law.db"
    lane_merge.snapshot_lane_for_backup("law", snap)
    store.dispose_lane("law")
    return snap


def test_a_version_this_machine_holds_keeps_its_own_parse_whole(machines, tmp_path, corpus):
    """Security read on PR 2: provisions merge per VERSION, never per address."""
    a, b, use = machines

    def seed_b(s):
        ident = _identity(s, "loi-1")
        _meta(s, "k-shared", ident)
        s.add_all([
            LawProvision(revision_lane_key="r1", document_lane_key="k-shared", address="art-1", text="new", content_hash="x"),
            LawProvision(revision_lane_key="r1", document_lane_key="k-shared", address="art-3", text="three", content_hash="x"),
        ])

    snap = _snap_of(b, use, tmp_path, seed_b)
    use(a)
    with store.lane_session("law") as s:
        _meta(s, "k-shared", _identity(s, "loi-1"))
        s.add_all([
            LawProvision(revision_lane_key="r1", document_lane_key="k-shared", address="art-1", text="old", content_hash="o"),
            LawProvision(revision_lane_key="r1", document_lane_key="k-shared", address="art-2", text="two", content_hash="t"),
        ])
        s.commit()
    rep = lane_merge.merge_lane_file("law", snap, [None])
    # Both backup rows are set aside: art-3, and art-1 whose text differs from this machine's.
    assert rep["tables"]["law_provisions"] == {"inserted": 0, "not_linked": 0, "kept_local_parse": 2}
    with store.lane_session("law") as s:
        got = sorted((p.address, p.text) for p in s.scalars(select(LawProvision)))
    assert got == [("art-1", "old"), ("art-2", "two")]


def test_a_new_version_s_provisions_carry_a_hash_of_their_own_text(machines, tmp_path, corpus):
    import hashlib

    a, b, use = machines

    def seed_b(s):
        _meta(s, "k-shared", _identity(s, "loi-1"))
        s.add(LawProvision(revision_lane_key="r1", document_lane_key="k-shared", address="art-1",
                           text="Article 1", content_hash="forged", num="x" * 65))

    snap = _snap_of(b, use, tmp_path, seed_b)
    _seed_a(a, use)
    lane_merge.merge_lane_file("law", snap, [None])
    with store.lane_session("law") as s:
        p = s.scalars(select(LawProvision)).one()
        assert p.content_hash == hashlib.sha256(b"Article 1").hexdigest()
        assert p.num is None  # longer than the column: not copied, never truncated


def test_a_backup_identity_the_model_would_not_write_is_not_inserted(machines, tmp_path, corpus):
    """Security read on PR 2: the triple must be in normal form and the vocabularies closed."""
    a, b, use = machines

    def seed_b(s):
        bad = LawIdentity(identity_scheme="ELI ", jurisdiction_alpha3="fra", document_identity="LOI-1",
                          jurisdiction_level="<img src=x>", doc_type="bill", legal_system="pwned", status="x")
        s.add(bad)
        s.flush()
        _meta(s, "k-new", bad)

    snap = _snap_of(b, use, tmp_path, seed_b)
    _seed_a(a, use)
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_identities"]["inserted"] == 0
    assert rep["tables"]["law_document_meta"]["inserted"] == 0
    assert rep["tables"]["law_document_meta"]["not_linked"] == 1
    assert [i[0] for i in _state()["ids"]] == ["loi-1"]


def test_an_unknown_status_or_legal_system_is_stored_as_unknown(machines, tmp_path, corpus):
    a, b, use = machines

    def seed_b(s):
        _meta(s, "k-new", _identity(s, "loi-2", status="Weird-Status", legal_system="pwned"))

    snap = _snap_of(b, use, tmp_path, seed_b)
    _seed_a(a, use)
    lane_merge.merge_lane_file("law", snap, [None])
    with store.lane_session("law") as s:
        ident = s.scalars(select(LawIdentity).where(LawIdentity.document_identity == "loi-2")).one()
        assert (ident.status, ident.legal_system) == ("unknown", "unknown")


def test_a_bare_identity_row_fills_nothing_on_a_law_it_does_not_link(machines, tmp_path, corpus):
    """Security read on PR 2: identity triples are public, so a fill needs a linked version."""
    a, b, use = machines

    def seed_b(s):
        _identity(s, "loi-1", repealed_on="1999-01-01", issuing_body="x" * 300)  # no version at all

    snap = _snap_of(b, use, tmp_path, seed_b)
    _seed_a(a, use)
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_identities"]["filled"] == 0
    assert _state()["ids"] == [("loi-1", None, None)]


def test_an_identity_fill_copies_only_well_formed_values(machines, tmp_path, corpus):
    a, b, use = machines

    def seed_b(s):
        ident = _identity(s, "loi-1", issuing_body="x" * 300, enacted_on="not a date", published_on="2019-03-01")
        _meta(s, "k-shared", ident)

    snap = _snap_of(b, use, tmp_path, seed_b)
    _seed_a(a, use)
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_identities"]["filled"] == 1
    with store.lane_session("law") as s:
        ident = s.scalars(select(LawIdentity)).one()
        assert (ident.issuing_body, ident.enacted_on, ident.published_on) == (None, None, "2019-03-01")


def test_a_row_reached_by_both_meta_fills_counts_once(machines, tmp_path, corpus):
    a, b, use = machines

    def seed_b(s):
        _meta(s, "k-shared", _identity(s, "loi-1"), title="Loi", translated_by="Body", licence_id="unknown")

    snap = _snap_of(b, use, tmp_path, seed_b)
    use(a)
    with store.lane_session("law") as s:
        _meta(s, "k-shared", _identity(s, "loi-1"), licence_id="unknown")
        s.commit()
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_document_meta"]["filled"] == 1
    with store.lane_session("law") as s:
        m = s.scalars(select(LawDocumentMeta)).one()
        assert (m.title, m.translated_by) == ("Loi", "Body")


def test_new_version_values_are_copied_only_in_the_shape_the_app_writes(machines, tmp_path, corpus):
    a, b, use = machines

    def seed_b(s):
        _meta(s, "k-new", _identity(s, "loi-1"), licence_id=" licence-ouverte-2.0 ",
              source_url="javascript:alert(1)", title="t" * 600)

    snap = _snap_of(b, use, tmp_path, seed_b)
    _seed_a(a, use)
    lane_merge.merge_lane_file("law", snap, [None])
    with store.lane_session("law") as s:
        m = s.scalars(select(LawDocumentMeta).where(LawDocumentMeta.lane_key == "k-new")).one()
        # The licence is a catalogue key or nothing, exactly as register_document takes it.
        assert (m.licence_id, m.source_url, m.title) == ("unknown", None, None)


def test_a_law_member_with_a_timestamp_this_build_cannot_read_is_refused(machines, tmp_path, corpus):
    """Opus read on PR 2: an integer timestamp would break every later read of the row."""
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    before = _state()
    con = sqlite3.connect(snap)
    con.execute("UPDATE law_identities SET created_at = 0")
    con.commit()
    con.close()
    with pytest.raises(lane_merge.LaneMergeError):
        lane_merge.merge_lane_file("law", snap, [None])
    assert _state() == before


def test_a_backup_from_a_build_without_some_columns_still_merges(machines, tmp_path, corpus):
    """Opus read on PR 2: an override must not read a column the backup does not have."""
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    con = sqlite3.connect(snap)
    con.execute("ALTER TABLE law_document_meta DROP COLUMN source_authority")
    con.execute("ALTER TABLE law_identities DROP COLUMN legal_system")
    con.execute("ALTER TABLE law_provisions DROP COLUMN ordinal")
    con.commit()
    con.close()
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_document_meta"]["inserted"] == 1
    assert rep["tables"]["law_provisions"]["inserted"] == 1


def test_a_linked_provision_the_model_could_not_have_stored_is_counted(machines, tmp_path, corpus):
    a, b, use = machines

    def seed_b(s):
        _meta(s, "k-shared", _identity(s, "loi-1"))
        s.add(LawProvision(revision_lane_key="r1", document_lane_key="k-shared", address="a" * 600,
                           text="x", content_hash="x"))

    snap = _snap_of(b, use, tmp_path, seed_b)
    _seed_a(a, use)
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_provisions"] == {"inserted": 0, "not_linked": 0, "refused": 1}


def test_an_identity_with_whitespace_the_model_collapses_is_not_inserted(machines, tmp_path, corpus):
    a, b, use = machines

    def seed_b(s):
        _meta(s, "k-new", _identity(s, "loi\n1"))

    snap = _snap_of(b, use, tmp_path, seed_b)
    _seed_a(a, use)
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_identities"]["inserted"] == 0
    assert rep["tables"]["law_document_meta"]["not_linked"] == 1


def test_a_version_under_a_document_key_the_corpus_holds_twice_links_no_provision(machines, tmp_path, corpus):
    with corpus() as db:
        db.add(LawDocument(jurisdiction="fr", title="Copie", url="https://law.test/4", lane_key="k-shared"))
        db.commit()
    a, b, use = machines
    snap = _seed_b(b, use, tmp_path)
    _seed_a(a, use)
    rep = lane_merge.merge_lane_file("law", snap, [None])
    assert rep["tables"]["law_provisions"] == {"inserted": 0, "not_linked": 2}
