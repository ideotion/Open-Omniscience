"""R71 (b), Q823 = a: Places and Wikidata items ride a restore, and never overwrite the local row.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Until 2026-09-30 these two tables were deliberately NOT carried while the ODbL question (Q823)
was open. It was answered "a" -- OSM data may leave the machine with OSM's credit and the ODbL
line -- so a restore carries them under the rule every deduced item follows (R61): what this
corpus lacks is added, what it holds with other values keeps its own and the backup's values
wait in ``metadata_alternates``. Every test merges into a DIFFERENT corpus: a self-restore sees
every row as a duplicate and never reaches the interesting branch.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from src.backup.alternates import discard, keep, list_alternates  # noqa: E402
from src.backup.merge import _MERGE_HANDLED, _MERGE_NOT_CARRIED, merge_corpus  # noqa: E402
from src.backup.provenance import provenance_tag  # noqa: E402
from src.database.models import (  # noqa: E402
    Article,
    Base,
    MetadataAlternate,
    Place,
    Source,
    WikidataItem,
)

_META = {
    "artifact_kind": "oo-backup-3",
    "origin_fingerprint": "machine-B",
    "app_version": "0.5.0",
    "alembic_rev": "head",
    "manifest": None,
}
_T0 = datetime(2026, 9, 1, tzinfo=UTC).replace(tzinfo=None)
_T1 = datetime(2026, 9, 20, tzinfo=UTC).replace(tzinfo=None)
_PARIS = "node/17807753"


def _corpus(path: Path):
    engine = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _place(pid=_PARIS, **kw):
    base = dict(
        id=pid, qid="Q90", kind="city", name="Paris", names_json='{"fr": "Paris", "en": "Paris"}',
        country="fr", country_alpha3="FRA", admin_path_json='["relation/7444"]',
        geometry_ref=f"osm.db:{pid}", lat=48.8566, lon=2.3522, population=2_100_000,
        gazetteer_vintage="2026-09", as_of=_T0,
    )
    base.update(kw)
    return Place(**base)


def _item(qid="Q90", **kw):
    base = dict(
        qid=qid, status="ok", resolved_qid=None, labels_json='{"en": "Paris"}',
        descriptions_json='{"en": "capital of France"}', claims_json='{"P17": ["Q142"]}',
        lastrevid=1234, fetched_at=_T0,
    )
    base.update(kw)
    return WikidataItem(**base)


def _two(tmp_path, incoming, local):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(inc)() as s:
        incoming(s)
        s.commit()
    with _corpus(live)() as s:
        local(s)
        s.commit()
    counts, batch = merge_corpus(inc, live, _META)
    return counts, batch, live, inc


def _nothing(_s):
    return None


def _alts(live):
    with _corpus(live)() as s:
        return [
            (a.table_name, json.loads(a.identity), json.loads(a.fields),
             json.loads(a.provenance), a.status)
            for a in s.query(MetadataAlternate).order_by(MetadataAlternate.id)
        ]


def test_the_two_tables_are_carried_not_left_behind():
    assert {"places", "wikidata_items"} <= _MERGE_HANDLED
    assert not {"places", "wikidata_items"} & set(_MERGE_NOT_CARRIED)


def test_a_fresh_install_restore_carries_every_column_of_both_tables(tmp_path):
    def inc(s):
        s.add(_place())
        s.add(_item())

    counts, batch, live, _ = _two(tmp_path, inc, _nothing)

    assert counts["places"]["new"] == 1 and counts["wikidata_items"]["new"] == 1
    with _corpus(live)() as s:
        got = s.get(Place, _PARIS)
        want = _place()
        for col in Place.__table__.columns.keys():
            if col == "article_id":
                continue  # asserted on its own below
            assert getattr(got, col) == getattr(want, col), f"places.{col} was dropped"
        assert got.article_id is None
        item = s.get(WikidataItem, "Q90")
        for col in WikidataItem.__table__.columns.keys():
            assert getattr(item, col) == getattr(_item(), col), f"wikidata_items.{col} was dropped"
        # merged_rows records the arrival by rowid, so the tag can say where the row came from
        rid = s.execute(text("SELECT rowid FROM places WHERE id = :i"), {"i": _PARIS}).scalar()
        tag = provenance_tag(s, "places", rid)
        item_rid = s.execute(text("SELECT rowid FROM wikidata_items WHERE qid = 'Q90'")).scalar()
        item_tag = provenance_tag(s, "wikidata_items", item_rid)
    assert tag["origin"] == "machine-B" and tag["arrived"]["batch"] == batch
    assert tag["kind"] == "extractor" and tag["producer"] == "OpenStreetMap gazetteer 2026-09"
    assert item_tag["producer"] == "Wikidata" and item_tag["version"] == "1234"
    assert item_tag["arrived"]["batch"] == batch
    assert _alts(live) == []


def test_a_place_the_corpus_lacks_is_added_beside_the_one_it_has(tmp_path):
    def inc(s):
        s.add(_place())
        s.add(_place("node/1", name="Lyon", qid="Q456"))

    counts, _, live, _ = _two(tmp_path, inc, lambda s: s.add(_place()))

    with _corpus(live)() as s:
        assert {p.id for p in s.query(Place)} == {_PARIS, "node/1"}
    assert counts["places"]["new"] == 1 and counts["places"]["duplicate"] == 1
    assert counts["places"]["conflict"] == 0
    assert _alts(live) == []


def test_a_contradicting_place_is_kept_beside_the_local_one(tmp_path):
    counts, batch, live, _ = _two(
        tmp_path,
        lambda s: s.add(_place(name="Paname", kind="town", population=1)),
        lambda s: s.add(_place()),
    )

    with _corpus(live)() as s:
        mine = s.get(Place, _PARIS)
        assert (mine.name, mine.kind, mine.population) == ("Paris", "city", 2_100_000)
    [(table, identity, fields, prov, status)] = _alts(live)
    assert table == "places" and identity == {"place_id": _PARIS} and status == "pending"
    assert fields["name"] == "Paname" and fields["kind"] == "town" and fields["population"] == 1
    assert fields["country_alpha3"] == "FRA", "the shown fields carry the whole picture"
    assert prov["origin"] == "machine-B" and prov["arrived"]["batch"] == batch
    assert counts["places"]["conflict"] == 1 and counts["places"]["duplicate"] == 0


def test_a_place_that_differs_only_in_where_and_when_is_not_a_contradiction(tmp_path):
    """The same place measured twice: the coordinates and the vintage are not what the
    restore compares."""
    counts, _, live, _ = _two(
        tmp_path,
        lambda s: s.add(_place(lat=48.9, lon=2.4, gazetteer_vintage="2027-01", as_of=_T1)),
        lambda s: s.add(_place()),
    )
    assert _alts(live) == []
    assert counts["places"]["conflict"] == 0 and counts["places"]["duplicate"] == 1


def test_restoring_the_same_backup_twice_records_a_place_difference_once(tmp_path):
    _, _, live, inc = _two(
        tmp_path, lambda s: s.add(_place(name="Paname")), lambda s: s.add(_place())
    )
    merge_corpus(inc, live, _META)
    assert len(_alts(live)) == 1


def test_a_contradicting_wikidata_item_is_kept_and_the_local_one_stays(tmp_path):
    counts, _, live, _ = _two(
        tmp_path,
        lambda s: s.add(_item(labels_json='{"en": "Paris (city)"}', lastrevid=9999, fetched_at=_T1)),
        lambda s: s.add(_item()),
    )
    with _corpus(live)() as s:
        assert s.get(WikidataItem, "Q90").labels_json == '{"en": "Paris"}'
    [(table, identity, fields, prov, _)] = _alts(live)
    assert table == "wikidata_items" and identity == {"qid": "Q90"}
    assert json.loads(fields["labels_json"]) == {"en": "Paris (city)"}
    assert fields["lastrevid"] == 9999, "the newer revision is shown so the operator can see which"
    assert prov["producer"] == "Wikidata"
    assert counts["wikidata_items"]["conflict"] == 1


def test_a_places_body_article_is_remapped_or_left_empty_never_foreign(tmp_path):
    def inc(s):
        src = Source(name="S", domain="s.example")
        s.add(src)
        s.flush()
        art = Article(url="https://s.example/p", canonical_url="https://s.example/p",
                      source_id=src.id, title="Paris", content="c", hash="h-body")
        s.add(art)
        s.flush()
        s.add(_place(article_id=art.id))
        s.add(_place("node/2", name="Ghost", article_id=987654))  # points at nothing in the backup

    def loc(s):
        src = Source(name="Other", domain="o.example")
        s.add(src)
        s.flush()
        for n in range(3):  # shift the local ids so a copied id would be wrong
            s.add(Article(url=f"https://o.example/{n}", canonical_url=f"https://o.example/{n}",
                          source_id=src.id, title="x", content="c", hash=f"h-loc-{n}"))

    _, _, live, _ = _two(tmp_path, inc, loc)
    with _corpus(live)() as s:
        body = s.query(Article).filter_by(hash="h-body").one()
        assert s.get(Place, _PARIS).article_id == body.id
        assert s.get(Place, "node/2").article_id is None


def test_an_incoming_alpha3_country_reaches_the_store_in_its_own_form(tmp_path):
    """`places.country` goes through the country-code normaliser; `country_alpha3` is alpha-3
    by design and is left as written."""
    _, _, live, _ = _two(
        tmp_path, lambda s: s.add(_place(country="FRA", country_alpha3="FRA")), _nothing
    )
    with _corpus(live)() as s:
        got = s.get(Place, _PARIS)
        assert (got.country, got.country_alpha3) == ("fr", "FRA")


def test_a_backup_that_predates_the_tables_reports_neither_domain(tmp_path):
    inc, live = tmp_path / "inc.db", tmp_path / "live.db"
    with _corpus(inc)() as s:
        s.add(_place())
        s.commit()
    eng = create_engine(f"sqlite:///{inc}", future=True)
    with eng.begin() as con:
        con.execute(text("DROP TABLE places"))
        con.execute(text("DROP TABLE wikidata_items"))
    _corpus(live)
    counts, _ = merge_corpus(inc, live, _META)
    assert "places" not in counts and "wikidata_items" not in counts


def test_the_operator_can_keep_or_discard_and_the_local_place_never_moves(tmp_path):
    _, _, live, _ = _two(
        tmp_path, lambda s: s.add(_place(name="Paname")), lambda s: s.add(_place())
    )
    with _corpus(live)() as s:
        out = list_alternates(s)
        [item] = out["items"]
        # the local side is found by identity through the rowid, and both tags are present
        assert item["table"] == "places"
        assert item["local"]["name"] == "Paris" and item["imported"]["name"] == "Paname"
        assert item["differing"] == ["name"]
        assert item["local_provenance"]["origin"] == "local"
        assert item["imported_provenance"]["origin"] == "machine-B"
        assert keep(s, item["id"])["status"] == "kept"
        assert s.get(Place, _PARIS).name == "Paris"
        assert discard(s, item["id"])["discarded"] is True
        assert s.get(Place, _PARIS).name == "Paris"
        assert s.query(MetadataAlternate).count() == 0


def test_the_arrival_of_a_text_keyed_row_is_found_by_its_key_not_its_rowid(tmp_path):
    """VACUUM may renumber the rowid of a table with no integer key, so the provenance lookup for
    places and Wikidata items goes through ``merged_rows.row_key``. Simulated by making the
    recorded rowids wrong: the tag must still name the right batch for the right row."""
    def inc(s):
        s.add(_place())
        s.add(_place("node/2", name="Lyon", qid="Q456"))
        s.add(_item())

    def loc(s):
        s.add(_place("node/3", name="Nice", qid="Q33"))   # a local row: no arrival

    _, batch, live, _ = _two(tmp_path, inc, loc)
    eng = create_engine(f"sqlite:///{live}", future=True)
    with eng.begin() as con:
        keys = {r[0] for r in con.execute(text(
            "SELECT row_key FROM merged_rows WHERE table_name IN ('places', 'wikidata_items')"))}
        assert keys == {_PARIS, "node/2", "Q90"}
        con.execute(text("UPDATE merged_rows SET row_id = row_id + 1000"
                         " WHERE table_name IN ('places', 'wikidata_items')"))
    with _corpus(live)() as s:
        def tag(table, pk, val):
            rid = s.execute(text(f"SELECT rowid FROM {table} WHERE {pk} = :v"), {"v": val}).scalar()  # noqa: S608
            return provenance_tag(s, table, rid)
        assert tag("places", "id", "node/2")["arrived"]["batch"] == batch
        assert tag("places", "id", _PARIS)["origin"] == "machine-B"
        assert tag("wikidata_items", "qid", "Q90")["arrived"]["batch"] == batch
        local = tag("places", "id", "node/3")
        assert local["origin"] == "local" and local["arrived"] is None


def test_an_older_store_gets_the_row_key_column_and_keeps_its_rows(tmp_path):
    """Not every install runs alembic: the boot self-heal adds ``merged_rows.row_key`` to a store
    that predates it, changes no row, and is idempotent."""
    from src.database.maintenance import ensure_merged_rows_row_key_column

    path = tmp_path / "old.db"
    eng = create_engine(f"sqlite:///{path}", future=True)
    with eng.begin() as con:
        con.execute(text(
            "CREATE TABLE merged_rows (batch_id INTEGER, table_name VARCHAR(64), row_id INTEGER,"
            " PRIMARY KEY (batch_id, table_name, row_id))"))
        con.execute(text("INSERT INTO merged_rows VALUES (1, 'articles', 7)"))
    assert ensure_merged_rows_row_key_column(eng) == ["row_key"]
    assert ensure_merged_rows_row_key_column(eng) == []
    with eng.begin() as con:
        assert con.execute(text("SELECT batch_id, table_name, row_id, row_key FROM merged_rows")).fetchall() == [
            (1, "articles", 7, None)]


@pytest.mark.skipif(
    __import__("subprocess").run(["which", "node"], capture_output=True).returncode != 0,
    reason="node is not installed",
)
def test_a_places_kind_is_shown_in_the_interface_language():
    """Item 14 (R71 b): OSM's `place=*` word is translated for display in all 12 languages;
    an unknown kind is shown as OSM wrote it. Driven against the real renderer and locales."""
    import subprocess
    import sys

    proc = subprocess.run(
        ["node", str(Path(__file__).with_name("place_kind_node_test.js"))],
        capture_output=True, text=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_a_row_the_local_job_rewrote_after_the_restore_is_no_longer_tagged_as_arrived(tmp_path):
    """``materialise`` and ``store_items`` rewrite a row in place by its key and stamp it afresh, so
    the values are no longer the restore's: the tag must say local, not "arrived from machine-B"."""
    _, batch, live, _ = _two(tmp_path, lambda s: (s.add(_place()), s.add(_item())), _nothing)
    with _corpus(live)() as s:
        def tag(table, pk, val):
            rid = s.execute(text(f"SELECT rowid FROM {table} WHERE {pk} = :v"), {"v": val}).scalar()  # noqa: S608
            return provenance_tag(s, table, rid)
        assert tag("places", "id", _PARIS)["arrived"]["batch"] == batch
        s.execute(text("UPDATE places SET as_of = '2999-01-01 00:00:00' WHERE id = :i"), {"i": _PARIS})
        s.execute(text("UPDATE wikidata_items SET fetched_at = '2999-01-01 00:00:00' WHERE qid = 'Q90'"))
        s.commit()
        for table, pk, val in (("places", "id", _PARIS), ("wikidata_items", "qid", "Q90")):
            t = tag(table, pk, val)
            assert t["origin"] == "local" and t["arrived"] is None
