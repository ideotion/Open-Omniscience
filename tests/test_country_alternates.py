"""A country code written INSIDE a recorded difference follows the store's form (0.5 row B1, the read of the B1 head).

An alternate (``metadata_alternates``) keeps the other value of a deduced item as JSON text: its ``fields`` (what a swap writes
back) and its ``identity`` (how a law item is found again: ``jurisdiction`` is one of its keys). No column holds those codes, so
a column rewrite never reached them; left in the old form a swap wrote ``fr`` into an alpha-3 store (which the next migration
run then refused as "still holds alpha-2"), a law identity stopped matching ("the row is gone", false) and a second restore of
the same backup recorded the same difference again.

Every store here is a scratch file built for the test.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup import country_migration as cm  # noqa: E402
from src.backup.alternates import swap  # noqa: E402
from src.backup.country_codes import (  # noqa: E402
    alternate_country_keys,
    convert_alternate_countries,
    normalise_staged_country_codes,
)
from src.backup.merge import merge_corpus  # noqa: E402
from src.database import country_form as cf  # noqa: E402
from src.database.models import (  # noqa: E402
    Base,
    LawDocument,
    LawRevision,
    LawRevisionSummary,
    Place,
)

_META = {"artifact_kind": "oo-backup-3", "origin_fingerprint": "machine-B", "app_version": "0.5.0", "alembic_rev": "head", "manifest": None}
_T0 = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)
_T1 = _T0 + timedelta(days=9)
_PARIS = "node/17807753"


@pytest.fixture(autouse=True)
def _small_windows(monkeypatch):
    monkeypatch.setattr(cm, "BATCH_ROWIDS", 9)


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _bind(monkeypatch, db: Path) -> None:
    """Make ``store_form()`` read THIS file, as it reads the live store in an install."""
    from src.config import kv_store

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db}")
    kv_store.kv_invalidate()


def _place(**kw):
    base = {"id": _PARIS, "qid": "Q90", "kind": "city", "name": "Paris", "country": "fr", "country_alpha3": "FRA",
            "population": 2_100_000, "as_of": _T0}
    base.update(kw)
    return Place(**base)


def _law(tag: str, at):
    def f(s):
        doc = LawDocument(jurisdiction="fr", title="Loi", url="https://example.fr/loi")
        s.add(doc)
        s.flush()
        rev = LawRevision(document_id=doc.id, observed_at=_T0, content_hash="ch1", full_text="T")
        s.add(rev)
        s.flush()
        s.add(LawRevisionSummary(revision_id=rev.id, summary=f"L-{tag}", model="m", prompt_version="v1",
                                 prompt_text=f"LP-{tag}", created_at=at))
    return f


def _two(tmp_path, incoming, local, name="live"):
    inc, live = tmp_path / "inc.db", tmp_path / f"{name}.db"
    with cf.writing_in("alpha2"):  # side files made with create_all carry no marker: they are alpha-2, and are written so
        with _corpus(inc)() as s:
            incoming(s)
            s.commit()
        with _corpus(live)() as s:
            local(s)
            s.commit()
    counts, batch = merge_corpus(inc, live, _META)
    return counts, batch, live, inc


def _alts(path: Path) -> list[dict]:
    con = sqlite3.connect(path)
    try:
        return [{"id": i, "table": t, "identity": json.loads(idn), "fields": json.loads(f)}
                for i, t, idn, f in con.execute("SELECT id, table_name, identity, fields FROM metadata_alternates ORDER BY id")]
    finally:
        con.close()


def _raw(path: Path, sql: str):
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


# ---- which keys hold a country ------------------------------------------------------------------------------------ #
def test_the_keys_that_hold_a_country_come_from_the_two_registries():
    assert alternate_country_keys("law_revision_summaries") == (("jurisdiction",), ())
    assert alternate_country_keys("places") == ((), ("country",))
    assert alternate_country_keys("keyword_translations") == ((), ())
    assert alternate_country_keys("not_a_table") == ((), ())


def test_every_alternate_table_that_shows_a_typed_column_is_covered():
    """A table added to the swap's ``shown`` list with a typed country column must not be missed by the conversion."""
    from src.backup.provenance import ALTERNATE_SPECS

    typed = set(cm.migration_columns())
    for table, spec in ALTERNATE_SPECS.items():
        shown = {c for c in (*spec["shown"], *spec["differs"]) if (table, c) in typed}
        assert shown == set(alternate_country_keys(table)[1]), f"{table}: a typed column the swap writes is not converted"
        if spec["scope"] == "law":
            assert ("law_documents", "jurisdiction") in typed


# ---- the conversion itself ----------------------------------------------------------------------------------------- #
def _alt_row(con, table, identity, fields):
    con.execute(
        "INSERT INTO metadata_alternates (batch_id, table_name, identity, local_row_id, fields, provenance, origin, status, created_at)"
        " VALUES (1, ?, ?, 1, ?, '{}', 'o', 'pending', '2026-09-01')", (table, identity, fields))


def test_the_conversion_changes_only_codes_and_writes_json_the_way_a_capture_does(tmp_path):
    db = tmp_path / "a.db"
    _corpus(db)
    con = sqlite3.connect(db)
    _alt_row(con, "places", '{"place_id":"node/1"}', '{"country":"fr","name":"Paris"}')
    _alt_row(con, "law_revision_summaries", '{"jurisdiction":"fr","document_url":"u","model":"m"}', '{"summary":"s"}')
    _alt_row(con, "law_revision_summaries", '{"jurisdiction":"uk","document_url":"u2","model":"m"}', '{"summary":"s"}')
    _alt_row(con, "places", '{"place_id":"node/2"}', '{"country":null,"name":"X"}')
    _alt_row(con, "places", '{"place_id":"node/3"}', "not json")
    _alt_row(con, "keyword_translations", '{"term":"fr"}', '{"text":"fr","country":"fr"}')
    con.commit()
    out = convert_alternate_countries(con, schema="main", form="alpha3")
    con.commit()
    assert out == {"converted": 2, "left_unreadable": 1,
                   "left_as_stored": {"law_revision_summaries.identity.jurisdiction": {"uk": 1}}}, "an unmapped code is counted and listed"
    rows = {r[0]: r[1:] for r in con.execute("SELECT id, identity, fields FROM metadata_alternates")}
    assert rows[1] == ('{"place_id":"node/1"}', '{"country":"FRA","name":"Paris"}'), "minified, like json_object"
    assert rows[2][0] == '{"jurisdiction":"FRA","document_url":"u","model":"m"}'
    assert rows[3][0].startswith('{"jurisdiction":"uk"'), "a value with no alpha-3 stays as it was"
    assert rows[4][1] == '{"country":null,"name":"X"}'
    assert rows[5][1] == "not json", "a value that cannot be read is left, and counted"
    assert rows[6] == ('{"term":"fr"}', '{"text":"fr","country":"fr"}'), "a table with no typed column is untouched"
    assert convert_alternate_countries(con, schema="main", form="alpha3")["converted"] == 0, "idempotent"
    assert convert_alternate_countries(con, schema="main", form="alpha2")["converted"] == 2, "and it follows the form it is given"
    assert con.execute("SELECT fields FROM metadata_alternates WHERE id = 1").fetchone()[0] == '{"country":"fr","name":"Paris"}'
    con.close()


def test_a_backup_without_the_table_or_the_columns_has_nothing_to_convert(tmp_path):
    con = sqlite3.connect(tmp_path / "old.db")
    assert convert_alternate_countries(con, schema="main", form="alpha3") == {"converted": 0, "left_unreadable": 0, "left_as_stored": {}}
    con.execute("CREATE TABLE metadata_alternates (id INTEGER PRIMARY KEY, table_name TEXT)")
    assert convert_alternate_countries(con, schema="main", form="alpha3") == {"converted": 0, "left_unreadable": 0, "left_as_stored": {}}
    con.close()


def test_the_restore_converts_a_staged_copys_alternates_toward_the_store_it_merges_into(tmp_path):
    staged, live = tmp_path / "staged.db", tmp_path / "live.db"
    for p in (staged, live):
        _corpus(p)
    con = sqlite3.connect(staged)
    _alt_row(con, "law_revision_summaries", '{"jurisdiction":"fr","document_url":"u","model":"m"}', '{"summary":"s"}')
    _alt_row(con, "law_revision_summaries", '{"jurisdiction":"uk","document_url":"u2","model":"m"}', '{"summary":"s"}')
    con.commit()
    con.close()
    con = sqlite3.connect(live)
    cf.write_form(con, "alpha3", by="test")
    con.commit()
    con.execute("ATTACH DATABASE ? AS inc", (str(staged),))
    report = normalise_staged_country_codes(con, schema="inc")
    assert report["target_form"] == "alpha3" and report["alternates"]["converted"] == 1
    assert report["alternates"]["left_as_stored"] == {"law_revision_summaries.identity.jurisdiction": {"uk": 1}}
    assert json.loads(con.execute("SELECT identity FROM inc.metadata_alternates ORDER BY id").fetchone()[0])["jurisdiction"] == "FRA"
    con.close()


# ---- the migration carries them --------------------------------------------------------------------------------- #
def test_a_place_difference_captured_before_the_migration_swaps_into_an_alpha3_store_as_alpha3(tmp_path, monkeypatch):
    _, _, live, _ = _two(tmp_path, lambda s: s.add(_place(name="Paname", country="de", country_alpha3="DEU")), lambda s: s.add(_place()))
    [alt] = _alts(live)
    assert alt["fields"]["country"] == "de" and alt["identity"] == {"place_id": _PARIS}

    rep = cm.migrate(live, backup_dir=tmp_path / "bk")
    assert rep.state == "done" and rep.alternates["converted"] == 1
    assert _alts(live)[0]["fields"]["country"] == "DEU", "the code inside the difference moved with the store"
    assert _raw(live, "SELECT country FROM places")[0][0] == "FRA"

    _bind(monkeypatch, live)
    with _corpus(live)() as s:
        assert swap(s, alt["id"])["status"] == "swapped"
    assert _raw(live, "SELECT name, country FROM places") == [("Paname", "DEU")], "no alpha-2 written into an alpha-3 store"
    assert _alts(live)[0]["fields"]["country"] == "FRA", "the row's old value is kept beside it, in the store's form"
    with _corpus(live)() as s:
        assert swap(s, alt["id"])["status"] == "pending"
    assert _raw(live, "SELECT name, country FROM places") == [("Paris", "FRA")]
    # and the store still holds nothing the next run would refuse
    assert cm.migrate(live, backup_dir=tmp_path / "bk2").state == "already-done"


def test_a_swap_converts_a_code_recorded_in_the_other_form(tmp_path, monkeypatch):
    """Defence beside the migration: a difference whose JSON is in the other form (a hand-edited or older record) is written in
    the form THIS store holds, because the swap is a raw UPDATE the column type never sees."""
    _, _, live, _ = _two(tmp_path, lambda s: s.add(_place(name="Paname", country="de")), lambda s: s.add(_place()))
    cm.migrate(live, backup_dir=tmp_path / "bk")
    con = sqlite3.connect(live)
    con.execute("UPDATE metadata_alternates SET fields = json_set(fields, '$.country', 'de')")
    con.commit()
    con.close()
    _bind(monkeypatch, live)
    with _corpus(live)() as s:
        swap(s, _alts(live)[0]["id"])
    assert _raw(live, "SELECT country FROM places") == [("DEU",)]


def test_a_law_difference_captured_before_the_migration_is_still_found_after_it(tmp_path, monkeypatch):
    counts, _, live, inc = _two(tmp_path, _law("A", _T1), _law("B", _T0))
    assert counts["metadata_alternates"].get("new", 0) == 0 and counts["law_revision_summaries"]["conflict"] == 1
    [alt] = _alts(live)
    assert alt["identity"]["jurisdiction"] == "fr"

    assert cm.migrate(live, backup_dir=tmp_path / "bk").state == "done"
    [alt] = _alts(live)
    assert alt["identity"]["jurisdiction"] == "FRA"

    _bind(monkeypatch, live)
    with _corpus(live)() as s:
        assert swap(s, alt["id"])["status"] == "swapped", "the row is found by its identity in the store's own form"
        assert s.query(LawRevisionSummary).one().summary == "L-A"

    # restoring the same backup again records nothing new: the identity it would capture is the one already kept
    merge_corpus(inc, live, _META)
    assert len(_alts(live)) == 1, "the same difference was recorded a second time"


def test_alternates_from_an_alpha2_backup_attach_to_an_alpha3_store(tmp_path, monkeypatch):
    # machine B: an alpha-2 store that holds a recorded law difference (the backup that will be restored)
    _, _, backup, _ = _two(tmp_path, _law("A", _T1), _law("B", _T0), name="backup")
    assert _alts(backup)[0]["identity"]["jurisdiction"] == "fr"
    # machine C: a migrated alpha-3 store holding the same law item with a third reading
    other = tmp_path / "c.db"
    with cf.writing_in("alpha2"), _corpus(other)() as s:
        _law("C", _T0)(s)
        s.commit()
    assert cm.migrate(other, backup_dir=tmp_path / "bk-c").state == "done"
    _bind(monkeypatch, other)
    counts, _ = merge_corpus(backup, other, _META)
    got = counts["metadata_alternates"]
    assert got.get("deferred", 0) == 0 and got["new"] == 1, f"a carried difference was left behind: {got}"
    assert {a["identity"]["jurisdiction"] for a in _alts(other)} == {"FRA"}, "no alpha-2 identity in an alpha-3 store"
    assert len(_alts(other)) == 2


def test_a_law_identity_in_the_other_form_still_finds_its_document(tmp_path, monkeypatch):
    """Defence beside the conversion: the swap's lookup and the restore's matcher bind the recorded jurisdiction in the form the
    store holds, so a record the conversion never saw (the other form, written by hand) is not reported as "gone"."""
    from src.backup.merge import _alternate_local_match
    from src.backup.provenance import ALTERNATE_SPECS

    _, _, live, _ = _two(tmp_path, _law("A", _T1), _law("B", _T0))
    assert cm.migrate(live, backup_dir=tmp_path / "bk").state == "done"
    con = sqlite3.connect(live)
    con.execute("UPDATE metadata_alternates SET identity = json_set(identity, '$.jurisdiction', 'fr')")
    con.commit()
    identity = _alts(live)[0]["identity"]
    assert identity["jurisdiction"] == "fr"
    where, params = _alternate_local_match(con, ALTERNATE_SPECS["law_revision_summaries"], identity)
    assert where is not None, "the restore's matcher missed a document that is there"
    con.close()
    _bind(monkeypatch, live)
    with _corpus(live)() as s:
        assert swap(s, _alts(live)[0]["id"])["status"] == "swapped"
