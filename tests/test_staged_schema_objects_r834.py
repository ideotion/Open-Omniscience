"""R829 A1 / R834: the schema check of a staged corpus knows every trigger, view and virtual table the app makes.

The check reads a fixed list (``staged_key._CORPUS_OBJECTS``), never the live store: read from the live store, the
verdict on a foreign file depended on the user's own (a store missing a trigger refused a backup that had it). This
ratchet keeps the list complete: every such object the source creates is either in it or named as living in another
store (``_NOT_CORPUS_OBJECTS``).
"""

from __future__ import annotations

import re
from pathlib import Path

from src.backup import staged_key

_ROOT = Path(__file__).resolve().parents[1]
_CREATE = re.compile(
    r"CREATE\s+(?:TEMP\s+|TEMPORARY\s+)?(TRIGGER|VIEW|VIRTUAL\s+TABLE)\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?([A-Za-z_{][A-Za-z_0-9{}]*)",
    re.IGNORECASE,
)


#: Files whose CREATE statements build a scratch database of their own, never a corpus.
_SCRATCH_ONLY = {"src/monitoring/merge_diag.py"}  # a diagnostic over an in-memory copy it makes itself


def _templates() -> dict[str, str]:
    from src.database import fts_title
    from src.database.models import MENTIONS_VIEW

    return {"{TABLE}": fts_title.TABLE, "{MENTIONS_VIEW}": MENTIONS_VIEW}


def _created_names() -> set[str]:
    subs = _templates()
    names = set()
    for top in ("src", "migrations"):
        for path in (_ROOT / top).rglob("*.py"):
            if path.relative_to(_ROOT).as_posix() in _SCRATCH_ONLY:
                continue
            for _kind, name in _CREATE.findall(path.read_text(encoding="utf-8")):
                for k, v in subs.items():
                    name = name.replace(k, v)
                if name.upper() in {"IF", "AS"} or "{" in name:
                    continue
                names.add(name.lower())
    return names


def test_every_object_the_source_creates_is_known_or_named_as_another_stores():
    created = _created_names()
    assert "article_fts_ai" in created and "keyword_mentions_all" in created  # the scan is not blind
    unknown = created - set(staged_key._CORPUS_OBJECTS) - staged_key._NOT_CORPUS_OBJECTS
    assert not unknown, f"add these to _CORPUS_OBJECTS or _NOT_CORPUS_OBJECTS in src/backup/staged_key.py: {unknown}"


def test_the_lists_do_not_overlap_and_the_check_reads_no_live_store(monkeypatch):
    assert not set(staged_key._CORPUS_OBJECTS) & staged_key._NOT_CORPUS_OBJECTS

    class _Broken:
        def connect(self):
            raise AssertionError("the check read the live store")

    monkeypatch.setattr("src.database.session.engine", _Broken())
    assert staged_key._known_objects() == staged_key._CORPUS_OBJECTS


# --------------------------------------------------------------------------- the security read's findings (PR #2390)


def _file_with(tmp_path, *ddl: str):
    import sqlite3

    p = tmp_path / "foreign.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, domain TEXT)")
    for d in ddl:
        con.execute(d)
    con.commit()
    con.close()
    return p


import pytest  # noqa: E402


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE /*x*/ VIRTUAL TABLE zz USING fts4(a)",  # a comment hides the kind from a text match
        "CREATE VIRTUAL TABLE articles USING fts4(title)",  # an app table name, but virtual
        "CREATE VIRTUAL TABLE article_fts USING /* fts5 */ fts4(a)",  # the module behind a comment
        "CREATE VIRTUAL TABLE article_fts -- fts5\n USING rtree(id, a, b)",
    ],
)
def test_a_virtual_table_is_known_by_its_missing_root_page_not_by_its_text(tmp_path, ddl):
    p = _file_with(tmp_path, ddl)
    con = staged_key.open_staged(p)
    try:
        with pytest.raises(staged_key.StagedKeyError, match="virtual table"):
            staged_key.check_staged_schema(con)
    finally:
        con.close()


def test_the_apps_own_search_index_still_passes(tmp_path):
    p = _file_with(tmp_path, "CREATE VIRTUAL TABLE article_fts USING fts5(title, content)")
    con = staged_key.open_staged(p)
    try:
        staged_key.check_staged_schema(con)
    finally:
        con.close()


def test_a_foreign_trigger_is_refused_before_the_seal_reads_a_row(tmp_path):
    p = _file_with(tmp_path, "CREATE TRIGGER evil AFTER INSERT ON sources BEGIN SELECT 1; END")
    before = p.read_bytes()
    with pytest.raises(staged_key.StagedKeyError, match="trigger"):
        staged_key.seal_plaintext(p)
    assert p.read_bytes() == before and not staged_key.is_keyed(p)
    assert not (tmp_path / "foreign.db.sealing").exists()


def test_a_foreign_trigger_is_refused_before_the_newsletter_filter_deletes(tmp_path):
    from src.backup.artifact import _drop_newsletter_articles

    p = _file_with(tmp_path, "CREATE TRIGGER evil AFTER DELETE ON sources BEGIN SELECT 1; END")
    before = p.read_bytes()
    with pytest.raises(staged_key.StagedKeyError):
        _drop_newsletter_articles(p)
    assert p.read_bytes() == before


def test_a_full_disk_is_not_called_a_damaged_backup(tmp_path, monkeypatch):
    import sqlcipher3.dbapi2 as sqc

    p = _file_with(tmp_path)
    real = staged_key._driver

    class _Conn:
        def __init__(self, inner):
            self._c = inner

        def __getattr__(self, name):
            return getattr(self._c, name)

        def cursor(self):
            class _Cur:
                def execute(self, sql, *a):
                    raise sqc.OperationalError("database or disk is full")

                def close(self):
                    pass

            return _Cur()

    class _Driver:
        DatabaseError = sqc.DatabaseError
        Error = sqc.Error

        @staticmethod
        def connect(*a, **k):
            return _Conn(real().connect(*a, **k))

    monkeypatch.setattr(staged_key, "_driver", lambda: _Driver)
    with pytest.raises(staged_key.StagedKeyError) as refused:
        staged_key.seal_plaintext(p)
    assert str(refused.value) == staged_key.DISK_FULL
    assert not (tmp_path / "foreign.db.sealing").exists()


def test_a_failed_import_forgets_the_keys_of_its_folder(tmp_path, monkeypatch):
    from src.backup import artifact

    sealed: list = []
    real_seal = artifact.seal_staged_members

    def seal_then_fail(staged, timings):
        real_seal(staged, timings)
        sealed.append(staged.corpus_path)
        raise RuntimeError("a later step failed")

    monkeypatch.setattr(artifact, "seal_staged_members", seal_then_fail)
    blob = _file_with(tmp_path).read_bytes()  # a bare database upload, sealed then failed
    with pytest.raises(RuntimeError):
        artifact.read_artifact(blob, None, staging_root=tmp_path / "st")
    assert sealed, "the import never reached the seal"
    for p in sealed:
        assert staged_key.key_for(p) is None


def test_a_keyed_attach_leaves_the_hosts_own_triggers_working(tmp_path):
    """Security read, PR #2390: ``trusted_schema`` is connection-wide, so switching it off for the attached file made
    the host's own triggers, which call the app's registered functions, fail with "unsafe use"."""
    import sqlcipher3.dbapi2 as sqc

    p = _file_with(tmp_path)
    staged_key.seal_plaintext(p)
    host = sqc.connect(str(tmp_path / "host.db"))
    try:
        host.create_function("oo_f", 1, lambda x: x, deterministic=True)
        host.execute("CREATE TABLE a (x)")
        host.execute("CREATE TABLE b (y)")
        host.execute("CREATE TRIGGER a_ai AFTER INSERT ON a BEGIN INSERT INTO b VALUES (oo_f(new.x)); END")
        assert staged_key.attach_staged(host, p, "inc")
        host.execute("INSERT INTO a VALUES (1)")
        assert host.execute("SELECT y FROM b").fetchall() == [(1,)]
        assert host.execute("PRAGMA cell_size_check").fetchone() == (1,)
    finally:
        host.close()
        staged_key.forget(p)


def test_the_erase_leaves_no_staged_key_in_memory():
    import inspect

    from src.safety import crypto_erase

    staged_key.register("/nonexistent/oo-test/corpus.db", staged_key.StagedKey(secret=b"x" * 32, page_size=None,
                                                                             origin="ephemeral"))
    assert staged_key.forget_all() >= 1 and staged_key.key_for("/nonexistent/oo-test/corpus.db") is None
    assert "forget_all()" in inspect.getsource(crypto_erase)  # step 5 calls it beside set_passphrase(None)
