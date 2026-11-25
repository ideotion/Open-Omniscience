"""Row 432: no trigger or view body a backup carries ever runs in the import, whatever its name.

The schema check (R829 A1) knows the NAMES the app makes, and a name says nothing about a body: a backup could carry
``article_fts_au`` with any SQL in it, and it ran on the merge's country-code write. ``staged_key.disarm_staged`` drops
every trigger and view from our staged copy once it is staged, before anything writes to it. Shown with a planted body
under a known name (with the undisarmed run as the control, so the test is not blind), on the merge's write and on the
newsletter filter's DELETE, plus a planted view; then that the merge's result on an ordinary backup is the same with and
without the drop. Also the custody log's schema refusal on the sealing path (A2) left out as on the keyed one (A1), and
the seal's refusal chosen by SQLite's result code, never by the driver's words.
"""

from __future__ import annotations

import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.backup import staged_key

_META = {"artifact_kind": "oo-backup-2", "origin_fingerprint": "t", "app_version": "0.6", "alembic_rev": "head",
         "manifest": None}
_NEWS = "newsletters.import.local"


def _build(path: Path, n: int, country: str | None, *, newsletters: int = 0) -> None:
    from sqlalchemy.orm import sessionmaker

    from src.database.models import Article, Base, Source
    from tests._app_engine import app_sqlite_engine

    engine = app_sqlite_engine(path, future=True)
    Base.metadata.create_all(engine)
    with sessionmaker(bind=engine, future=True)() as s:
        src = Source(name="s", domain="s.example")
        news = Source(name="n", domain=_NEWS)
        s.add_all([src, news])
        s.flush()
        for i in range(n):
            s.add(Article(url=f"https://s.example/{i}", canonical_url=f"https://s.example/{i}", source_id=src.id,
                          title=f"t{i}", content=f"body {i}", hash=f"h{i}", language="en", country=country,
                          created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        for i in range(newsletters):
            s.add(Article(url=f"https://{_NEWS}/{i}", canonical_url=f"https://{_NEWS}/{i}", source_id=news.id,
                          title=f"n{i}", content=f"letter {i}", hash=f"n{i}", language="en", country=None,
                          created_at=datetime(2026, 1, 1, tzinfo=UTC)))
        s.commit()
    engine.dispose()
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=DELETE")
    con.close()


def _plant(path: Path, *ddl: str) -> None:
    con = sqlite3.connect(path)
    try:
        for d in ddl:
            con.execute(d)
        con.commit()
    finally:
        con.close()


#: A body under the app's own name for the update trigger of the search index: it rewrites the row the merge reads.
_PLANTED_UPDATE = (
    "DROP TRIGGER IF EXISTS article_fts_au",
    "CREATE TRIGGER article_fts_au AFTER UPDATE ON articles BEGIN UPDATE articles SET title = 'planted' "
    "WHERE id = new.id; END",
)
#: Under the app's name for the delete trigger: it adds a source to the copy the merge then reads.
_PLANTED_DELETE = (
    "DROP TRIGGER IF EXISTS article_fts_ad",
    "CREATE TRIGGER article_fts_ad AFTER DELETE ON articles BEGIN INSERT OR IGNORE INTO sources (name, domain) "
    "VALUES ('planted', 'planted.example'); END",
)


def _rows(path: Path, sql: str) -> list:
    con = sqlite3.connect(path)
    try:
        return con.execute(sql).fetchall()
    finally:
        con.close()


def _names(path: Path, typ: str) -> set[str]:
    return {r[0] for r in _rows(path, f"SELECT name FROM sqlite_master WHERE type = '{typ}'")}  # noqa: S608  # nosec B608 # typ from the test


@pytest.mark.parametrize("sealed", [False, True], ids=["plaintext", "keyed"])
@pytest.mark.parametrize("disarmed", [True, False], ids=["disarmed", "control"])
def test_a_planted_trigger_under_a_known_name_never_runs_on_the_merges_write(tmp_path, sealed, disarmed):
    from src.backup.merge import merge_corpus

    work, inc = tmp_path / "work.db", tmp_path / "inc.db"
    _build(work, 0, None)
    _build(inc, 5, "FRA")  # alpha-3 into an alpha-2 store: the country-code step updates every article of inc
    _plant(inc, *_PLANTED_UPDATE)
    if sealed:
        staged_key.seal_plaintext(inc)
    try:
        if disarmed:
            assert staged_key.disarm_staged(inc) >= 1
            con = staged_key.open_staged(inc)
            try:
                left = con.execute("SELECT count(*) FROM sqlite_master WHERE type IN ('trigger', 'view')").fetchone()
            finally:
                con.close()
            assert left == (0,)
        merge_corpus(inc, work, _META, cache_mb=8)
    finally:
        staged_key.forget(inc)
    titles = {r[0] for r in _rows(work, "SELECT title FROM articles")}
    assert {r[0] for r in _rows(work, "SELECT country FROM articles")} == {"fr"}  # the step did write the copy
    if disarmed:
        assert "planted" not in titles and titles == {f"t{i}" for i in range(5)}
    else:
        assert titles == {"planted"}, "the control: undisarmed, the planted body runs (the test is not blind)"


@pytest.mark.parametrize("disarmed", [True, False], ids=["disarmed", "control"])
def test_a_planted_trigger_never_runs_on_the_newsletter_filters_delete(tmp_path, disarmed):
    from src.backup.artifact import _drop_newsletter_articles

    inc = tmp_path / "inc.db"
    _build(inc, 2, None, newsletters=3)
    _plant(inc, *_PLANTED_DELETE)
    if disarmed:
        staged_key.disarm_staged(inc)
    assert _drop_newsletter_articles(inc) == 3
    planted = _rows(inc, "SELECT count(*) FROM sources WHERE domain = 'planted.example'")[0][0]
    assert planted == (0 if disarmed else 1)
    assert _rows(inc, "SELECT count(*) FROM articles")[0][0] == 2  # the filter itself still removed the letters


def test_a_planted_view_under_a_known_name_is_dropped(tmp_path):
    from src.database.models import MENTIONS_VIEW

    inc = tmp_path / "inc.db"
    _build(inc, 1, None)
    _plant(inc, f"DROP VIEW IF EXISTS {MENTIONS_VIEW}", f"CREATE VIEW {MENTIONS_VIEW} AS SELECT 'planted' AS x")
    assert MENTIONS_VIEW in _names(inc, "view")
    staged_key.disarm_staged(inc)
    assert _names(inc, "view") == set() and _names(inc, "trigger") == set()


def test_an_unknown_name_is_still_refused_and_nothing_is_dropped(tmp_path):
    inc = tmp_path / "inc.db"
    _build(inc, 1, None)
    _plant(inc, "CREATE TRIGGER evil AFTER INSERT ON sources BEGIN SELECT 1; END")
    before = inc.read_bytes()
    with pytest.raises(staged_key.StagedSchemaRefused, match="trigger"):
        staged_key.disarm_staged(inc)
    assert inc.read_bytes() == before


def _content(path: Path) -> dict[str, list]:
    con = sqlite3.connect(path)
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        out = {}
        for t in tables:
            cols = [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')]
            if not cols:  # a virtual table's shadow layout is read through its own tables
                continue
            order = ", ".join(f'"{c}"' for c in cols)
            out[t] = con.execute(f'SELECT * FROM "{t}" ORDER BY {order}').fetchall()  # noqa: S608  # nosec B608 # names from the file's own schema
        return out
    finally:
        con.close()


def test_the_merged_result_is_the_same_with_and_without_the_drop(tmp_path):
    """Nothing the merge reads from the staged copy is maintained by its triggers: an ordinary backup (the app's own
    triggers, a country-code rewrite on every article) merges to the same working copy either way."""
    from src.backup.merge import merge_corpus

    results = []
    for case in ("kept", "dropped"):
        d = tmp_path / case
        d.mkdir()
        work, inc = d / "work.db", d / "inc.db"
        _build(work, 3, "FR")
        _build(inc, 40, "FRA", newsletters=0)
        if case == "dropped":
            assert staged_key.disarm_staged(inc) >= 3
        merge_corpus(inc, work, _META, cache_mb=8)
        results.append(_content(work))
    kept, dropped = results
    for run_record in ("merge_batches", "screening_pending"):  # the run's own record: its time, not the backup's data
        kept.pop(run_record), dropped.pop(run_record)
    assert kept.keys() == dropped.keys()
    differing = [t for t in kept if kept[t] != dropped[t]]
    assert not differing, differing
    assert len(kept["articles"]) == 40  # the three the store already had (same urls) are matched, not added


def test_a_custody_log_refused_for_its_schema_on_the_sealing_path_is_left_out_as_on_the_keyed_one(tmp_path):
    from src.backup.artifact import StagedArtifact, seal_staged_members
    from src.backup.merge import merge_custody

    staging = tmp_path / "st"
    staging.mkdir()
    corpus, custody = staging / "corpus.db", staging / "custody.db"
    _build(corpus, 1, None)
    con = sqlite3.connect(custody)
    con.execute("CREATE TABLE custody_entries (id INTEGER PRIMARY KEY)")
    con.execute("CREATE TRIGGER evil AFTER INSERT ON custody_entries BEGIN SELECT 1; END")
    con.commit()
    con.close()
    staged = StagedArtifact(kind="oo-backup-2", staging_dir=staging, corpus_path=corpus, custody_path=custody,
                            manifest={}, signature_state="unsigned", origin_fingerprint="unsigned")
    try:
        seal_staged_members(staged)  # the import goes on: no ArtifactError
        assert staged.custody_path is None and not custody.exists()
        assert staged_key.is_keyed(corpus)
        # A1's words: the merge's own refusal of a keyed custody log holding the same trigger.
        keyed = tmp_path / "keyed.db"
        con = sqlite3.connect(keyed)
        con.execute("CREATE TABLE custody_entries (id INTEGER PRIMARY KEY)")
        con.execute("CREATE TRIGGER evil AFTER INSERT ON custody_entries BEGIN SELECT 1; END")
        con.commit()
        con.close()
        a1 = merge_custody(keyed, "unsigned")
        assert staged.custody_refused == a1["refused"]
        report: dict = {}
        from src.backup import merge as M

        monkey = M.merge_side_files
        M.merge_side_files = lambda s: None  # this test reads the custody half only
        try:
            M._merge_side_files_and_custody(staged, report)
        finally:
            M.merge_side_files = monkey
        assert report["custody"] == a1
    finally:
        staged_key.forget_under(staging)


class _Disk:
    """``shutil.disk_usage`` that reports a full disk from its ``full_after``-th call on (0: at once)."""

    def __init__(self, full_after: int):
        import shutil

        self.real, self.calls, self.full_after = shutil.disk_usage, 0, full_after

    def __call__(self, path):
        self.calls += 1
        u = self.real(path)
        return type(u)(u.total, u.used, 0) if self.calls > self.full_after else u


def _page_limited(monkeypatch):
    """The seal's copy given a four-page limit: its export fails part-way with a real SQLite error (SQLITE_ERROR, code 1,
    as sqlcipher_export reports any failure inside it)."""
    real = staged_key._driver

    class _Conn:
        def __init__(self, inner):
            self._c = inner

        def __getattr__(self, name):
            return getattr(self._c, name)

        def execute(self, sql, *a):
            out = self._c.execute(sql, *a)
            if sql.startswith("PRAGMA sealed.auto_vacuum"):
                self._c.execute("PRAGMA sealed.max_page_count = 4")
            return out

    class _Driver:
        DatabaseError = real().DatabaseError
        Error = real().Error

        @staticmethod
        def connect(*a, **k):
            return _Conn(real().connect(*a, **k))

    monkeypatch.setattr(staged_key, "_driver", lambda: _Driver)


@pytest.mark.parametrize("full", [True, False], ids=["disk-full", "page-limit-only"])
def test_a_failed_seal_is_called_a_full_disk_only_when_the_disk_is_full(tmp_path, monkeypatch, full):
    import shutil

    p = tmp_path / "inc.db"
    _build(p, 200, None)
    _page_limited(monkeypatch)
    if full:
        monkeypatch.setattr(shutil, "disk_usage", _Disk(full_after=1))  # room at the start, none when the export fails
    with pytest.raises(staged_key.StagedKeyError) as refused:
        staged_key.seal_plaintext(p)
    assert str(refused.value) == (staged_key.DISK_FULL if full else staged_key.DAMAGED)
    assert not staged_key.is_keyed(p) and not (tmp_path / "inc.db.sealing").exists()


def test_a_disk_without_room_for_the_copy_is_refused_before_a_byte_is_written(tmp_path, monkeypatch):
    import shutil

    p = tmp_path / "inc.db"
    _build(p, 5, None)
    before = p.read_bytes()
    created = []
    import src.backup.regular_file as rf

    real_create = rf.create_new
    monkeypatch.setattr(rf, "create_new", lambda *a, **k: created.append(a) or real_create(*a, **k))
    monkeypatch.setattr(shutil, "disk_usage", _Disk(full_after=0))
    with pytest.raises(staged_key.StagedKeyError) as refused:
        staged_key.seal_plaintext(p)
    assert str(refused.value) == staged_key.DISK_FULL and not created and p.read_bytes() == before


def test_the_seal_refusal_reads_evidence_never_the_words(tmp_path):
    import sqlcipher3.dbapi2 as sqc

    p = tmp_path / "inc.db"
    _build(p, 1, None)

    def err(words: str, code: int | None):
        e = sqc.OperationalError(words)
        if code is not None:
            e.sqlite_errorcode = code
        return e

    refusal = staged_key._seal_refusal
    assert refusal(err("database or disk is full", None), p, 0) == staged_key.DAMAGED  # words alone: no
    assert refusal(err("database is locked", None), p, 0) == staged_key.DAMAGED
    assert refusal(err("anything", 13), p, 0) == staged_key.DISK_FULL
    assert refusal(err("anything", 13 | (1 << 8)), p, 0) == staged_key.DISK_FULL  # an extended code
    assert refusal(err("anything", 5), p, 0) == staged_key.IN_USE
    assert refusal(err("anything", 6), p, 0) == staged_key.IN_USE
    assert refusal(err("full", 11), p, 0) == staged_key.DAMAGED  # SQLITE_CORRUPT, whatever it says


def test_a_source_another_connection_is_writing_is_called_in_use(tmp_path):
    import sqlcipher3.dbapi2 as sqc

    p = tmp_path / "inc.db"
    _build(p, 1, None)
    holder = sqlite3.connect(p, isolation_level=None)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        assert staged_key._seal_refusal(sqc.OperationalError("x"), p, 0) == staged_key.IN_USE  # code 1: the probe decides
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    assert staged_key._seal_refusal(sqc.OperationalError("x"), p, 0) == staged_key.DAMAGED


#: Every function the app registers on the merge's host connection, by name: what an expression in the staged schema
#: (CHECK, DEFAULT, generated column, index expression) can still call there (row 432's residual). Each is pure. A new
#: registration is added here on purpose, with a reason, or this test fails.
_HOST_FUNCTIONS = {
    "oo_inc_feed_key": "src/backup/merge.py:_merge_sources: a lookup in a dict of the incoming sources' keys",
    "oo_fts_norm": "src/database/fts_norm.py: a text as the search index stores it (folding, segmentation); pure",
    "oo_fts_used": "src/database/fts_norm.py: which normalisers a text needs, a mask; pure",
    "oo_fts_caps": "src/database/fts_norm.py: the normalisers this install has, a constant",
    "oo_search_fold": "src/database/fts_norm.py: the advanced search's case and accent fold; pure",
}


@pytest.mark.parametrize("sealed", [False, True], ids=["plaintext", "keyed"])
def test_the_merge_host_registers_only_pure_functions_and_loads_no_extension(tmp_path, monkeypatch, sealed):
    import src.backup.merge as M

    work, inc = tmp_path / "work.db", tmp_path / "inc.db"
    _build(work, 0, None)
    _build(inc, 3, None)
    if sealed:
        staged_key.seal_plaintext(inc)
    seen: dict[str, object] = {}
    real = M._merge_sources

    def watching(con, *a, **k):
        real(con, *a, **k)  # after the merge's own registration
        # The driver's own and its compiled-in extensions' (FTS5, R*Tree, geopoly) are read off a fresh connection of
        # the same driver: what is left is what the app registered.
        fresh = sys.modules[type(con).__module__].connect(":memory:")
        try:
            base = {r[0] for r in fresh.execute("PRAGMA function_list")}
        finally:
            fresh.close()
        seen["functions"] = {r[0] for r in con.execute("PRAGMA function_list")} - base
        try:
            con.execute("SELECT load_extension('oo_no_such_library')").fetchall()
            seen["extension"] = "loaded"
        except Exception as exc:  # noqa: BLE001 - the refusal is the point
            seen["extension"] = "not authorized" if "not authorized" in str(exc) else type(exc).__name__

    monkeypatch.setattr(M, "_merge_sources", watching)
    try:
        M.merge_corpus(inc, work, _META, cache_mb=8)
    finally:
        staged_key.forget(inc)
    assert seen["functions"] == set(_HOST_FUNCTIONS), seen["functions"]
    assert seen["extension"] == "not authorized"
