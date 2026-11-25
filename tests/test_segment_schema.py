"""R826 stage 3b (row 409): a segment holds the per-article tables, derived from the models with the cross-file foreign keys
dropped, and the two search indexes; the writer inserts articles with ids from the segment's range and refuses any row that
names a shared-file row the shared file does not have (the check that stands in for those foreign keys)."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

import pytest

from src.database import at_rest_state, segment_open, segment_write
from src.database import segments as sg
from src.database.connect import have_driver
from src.database.segment_schema import SEGMENT_TABLES, SHARED_REFERENCES, segment_table_ddl
from src.database.segments import SegmentError
from tests._app_engine import app_sqlite_engine

_PW = "r826-stage-3b-segment-schema-test-passphrase"
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
posix_only = pytest.mark.skipif(os.name != "posix", reason="links and inode checks (POSIX)")


@pytest.fixture()
def data(tmp_path, monkeypatch) -> Path:
    d = tmp_path / "OOS data"
    d.mkdir()
    (d / at_rest_state.RECORD_NAME).write_text(json.dumps({"version": 1, "stores": {}}), encoding="utf-8")
    monkeypatch.setenv("OO_DATA_DIR", str(d))
    import src.api.unlock as unlock

    monkeypatch.setattr(unlock, "main_db_path", lambda **_: d / "open_omniscience.db")
    monkeypatch.setattr(segment_open, "SEGMENT_WRITES_ENABLED", True)
    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: False)
    return d


@pytest.fixture()
def shared(data):
    from src.database.models import Base

    path = data / "open_omniscience.db"
    eng = app_sqlite_engine(path)
    Base.metadata.create_all(eng)
    eng.dispose()
    con = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    con.execute("INSERT INTO sources (id, name, domain) VALUES (7, 's', 's.test')")
    con.execute("INSERT INTO keywords (id, term, normalized_term) VALUES (3, 'harbour', 'harbour')")
    yield con
    con.close()


def _article(n: int, **extra) -> dict:
    return {
        "url": f"https://s.test/{n}",
        "canonical_url": f"https://s.test/{n}",
        "source_id": 7,
        "title": f"Harbour report {n}",
        "content": f"The harbour authority published figures {n}.",
        "hash": f"h{n}",
        **extra,
    }


def test_every_foreign_key_to_a_shared_table_is_listed_and_dropped():
    from src.database.models import Base

    to_shared = {
        (name, fk.parent.name)
        for name in SEGMENT_TABLES
        for fk in Base.metadata.tables[name].foreign_keys
        if fk.column.table.name not in SEGMENT_TABLES
    }
    assert to_shared <= set(SHARED_REFERENCES), "a new reference to the shared file must be listed and checked in code"
    ddl = "\n".join(segment_table_ddl())
    assert "REFERENCES sources" not in ddl and "REFERENCES keywords" not in ddl
    assert "REFERENCES articles" in ddl, "references inside the segment stay constraints"


@posix_only
@pytest.mark.parametrize("encrypted", [False, pytest.param(True, marks=sqlcipher_only)])
def test_a_segment_has_the_per_article_tables_and_both_search_indexes(data, shared, monkeypatch, encrypted):
    monkeypatch.setattr(segment_open, "_shared_is_encrypted", lambda: encrypted)
    key = _PW if encrypted else None
    w = segment_write.open_writer(shared, key=key)
    try:
        names = {r[0] for r in w._con.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view')")}
        assert set(SEGMENT_TABLES) | {"segment_meta", "article_fts", "article_fts_title"} <= names
        with w.transaction() as t:
            ids = t.add_articles([_article(1), _article(2, title="Weather")])
            t.add_rows("keyword_mentions", [{"keyword_id": 3, "article_id": ids[0], "source_id": 7, "count": 2}])
        assert ids == [w.seg.id_lo, w.seg.id_lo + 1]
        hits = w._con.execute("SELECT rowid FROM article_fts WHERE article_fts MATCH 'figures' ORDER BY rowid").fetchall()
        assert [h[0] for h in hits] == ids, "the search index follows the segment's own articles"
        title = w._con.execute("SELECT rowid FROM article_fts_title WHERE article_fts_title MATCH 'harb*'").fetchall()
        assert [h[0] for h in title] == [ids[0]]
        created = w._con.execute("SELECT created_at FROM articles WHERE id = ?", (ids[0],)).fetchone()[0]
        assert created is not None and "T" not in created and "+" not in created, "stored the way SQLAlchemy stores it"
    finally:
        w.close()
    segment_open.open_segment(next(s for s in sg.registry(shared) if s.seg_no == 1), key=key).close()


@posix_only
@pytest.mark.parametrize(
    ("table", "row"),
    [
        ("articles", _article(1, source_id=999)),
        ("keyword_mentions", {"keyword_id": 999, "article_id": None, "count": 1}),
        ("keyword_mentions", {"keyword_id": 3, "article_id": None, "source_id": 999, "count": 1}),
    ],
)
def test_a_row_naming_a_missing_shared_row_is_refused_and_nothing_is_written(data, shared, table, row):
    w = segment_write.open_writer(shared)
    try:
        with w.transaction() as t:
            first = t.add_articles([_article(1)])[0]
        before = w._con.execute("SELECT next_id, generation FROM segment_meta").fetchone()
        with pytest.raises(SegmentError), w.transaction() as t:
            if table == "articles":
                t.add_articles([row])
            else:
                t.add_rows(table, [{**row, "article_id": first}])
        assert w._con.execute("SELECT next_id, generation FROM segment_meta").fetchone() == before
        assert w._con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 1
        assert w._con.execute("SELECT COUNT(*) FROM keyword_mentions").fetchone()[0] == 0
    finally:
        w.close()


@posix_only
def test_a_derived_row_must_name_an_article_of_this_segment(data, shared):
    w = segment_write.open_writer(shared)
    try:
        with pytest.raises(sqlite3.IntegrityError), w.transaction() as t:
            t.add_rows("keyword_mentions", [{"keyword_id": 3, "article_id": 1, "count": 1}])
        assert w._con.execute("SELECT COUNT(*) FROM keyword_mentions").fetchone()[0] == 0
    finally:
        w.close()


@posix_only
@pytest.mark.parametrize(
    "call",
    [
        lambda t: t.add_articles([{**_article(1), "id": 5}]),
        lambda t: t.add_articles([{**_article(1), "no_such_column": 1}]),
        lambda t: t.add_rows("sources", [{"name": "x", "domain": "x"}]),
        lambda t: t.add_rows("articles", [_article(1)]),
        lambda t: t.add_articles([_article(1, source_id="7")]),
    ],
)
def test_ids_columns_and_tables_are_the_segments_to_decide(data, shared, call):
    w = segment_write.open_writer(shared)
    try:
        with pytest.raises(SegmentError), w.transaction() as t:
            call(t)
        assert w._con.execute("SELECT COUNT(*) FROM articles").fetchone()[0] == 0
    finally:
        w.close()


# --- Plan's ruling for 3b: segment opens never create and never follow a link; every other caller unchanged ------------------


@posix_only
def test_sqlite_has_no_nofollow_uri_parameter_so_the_lstat_is_the_refusal(tmp_path):
    """Measured, both drivers: ``nofollow=1`` in a URI is ignored (SQLITE_OPEN_NOFOLLOW is an open_v2 flag Python cannot
    pass). If a driver ever honours it, this fails and the URI can carry it as a second refusal."""
    real = tmp_path / "real.db"
    sqlite3.connect(real).execute("CREATE TABLE t(x)").connection.close()
    link = tmp_path / "l.db"
    os.symlink(real, link)
    drivers = [sqlite3]
    if have_driver():
        from sqlcipher3 import dbapi2 as sqc

        drivers.append(sqc)
    for driver in drivers:
        con = driver.connect(f"file:{link}?mode=rw&nofollow=1", uri=True)
        try:
            assert con.execute("SELECT COUNT(*) FROM t").fetchone() == (0,)
        finally:
            con.close()


@posix_only
@pytest.mark.parametrize("encrypted", [False, pytest.param(True, marks=sqlcipher_only)])
def test_an_existing_only_open_refuses_a_link_and_a_missing_file_and_creates_nothing(tmp_path, encrypted):
    from src.database.connect import connect

    real = tmp_path / "real.db"
    key = _PW if encrypted else None
    con = connect(real, key=key, create_encrypted=encrypted)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    before = real.read_bytes()
    link = tmp_path / "seg-1.db"
    os.symlink(real, link)
    with pytest.raises(FileNotFoundError):
        connect(link, key=key, existing_no_follow=True)
    missing = tmp_path / "seg-2.db"
    with pytest.raises(FileNotFoundError):
        connect(missing, key=key, existing_no_follow=True)
    assert not missing.exists() and real.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["real.db", "seg-1.db"]
    con = connect(real, key=key, existing_no_follow=True)
    try:
        con.execute("INSERT INTO t VALUES (1)")
        con.commit()
    finally:
        con.close()


def test_every_other_caller_opens_exactly_as_before(tmp_path, monkeypatch):
    """The default open of an existing plaintext file is still ``connect(str(path))``, a read-only open still ``mode=ro``,
    and a missing file is still created by the default open: the option changes nothing it is not asked for."""
    from src.database import connect as connect_mod

    seen: list[tuple] = []
    real_connect = sqlite3.connect

    def spy(target, *a, **k):
        seen.append((str(target), bool(k.get("uri"))))
        return real_connect(target, *a, **k)

    p = tmp_path / "store.db"
    real_connect(p).execute("CREATE TABLE t(x)").connection.close()
    monkeypatch.setattr(connect_mod.sqlite3, "connect", spy)
    connect_mod.connect(p).close()
    connect_mod.connect(p, read_only=True).close()
    connect_mod.connect(p, existing_no_follow=True).close()
    fresh = tmp_path / "fresh.db"
    connect_mod.connect(fresh, create_encrypted=False).close()
    assert seen[0] == (str(p), False)
    assert seen[1][1] and seen[1][0].endswith("?mode=ro")
    assert seen[2][1] and seen[2][0].endswith("?mode=rw")
    assert seen[3] == (str(fresh), False) and fresh.exists()


@posix_only
def test_a_link_swapped_in_after_the_lstat_is_caught_by_the_identity_check(data, shared, tmp_path, monkeypatch):
    """SQLite follows a link it is handed; one swapped in between the lstat and the open makes the name lead to another file,
    which the writer's identity check refuses before any row is read or written."""
    from src.database import connect as connect_mod

    segment_write.open_writer(shared).close()
    p = data / "corpus" / "seg-1.db"
    other = tmp_path / "other.db"
    other.write_bytes(p.read_bytes())  # a valid-looking copy elsewhere
    before = other.read_bytes()
    real = connect_mod._refuse_unless_regular

    def swap(path):
        real(path)
        if Path(path) == p:
            os.replace(p, tmp_path / "moved.db")
            os.symlink(other, p)

    monkeypatch.setattr(connect_mod, "_refuse_unless_regular", swap)
    seg = next(s for s in sg.registry(shared) if s.seg_no == 1)
    with pytest.raises(segment_open.SegmentUnavailable) as e:
        segment_write.SegmentWriter.open(shared, seg)
    assert e.value.reason in ("changed_while_opening", "not_a_segment_file")
    assert other.read_bytes() == before
