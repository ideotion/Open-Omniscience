"""A connection opened before an encryption swap, and a status that knows about keys (rows 148 and 149, the R742 follow-ups).

Row 148: encrypting a store replaces its file. A custody log or a lane connection opened on the plaintext file before the swap keeps
its handle on the REPLACED file, which is then overwritten and removed: a save through it would land nowhere anyone reads. Each such
connection now carries the identity of the file it opened (``src/database/file_identity.py``) and is refused, loudly and before
anything is written, once its path names another file.

Row 149: the at-rest status opens each encrypted store with the passphrase the app holds, so a store encrypted under another
passphrase reads as that (``not_this_key``), never as "encrypted" and never as plain or unreadable; an unreadable store says why.

Every case runs on real SQLite and SQLCipher files, through the product's own swap (``encrypt_tool.encrypt_store``).
"""

from __future__ import annotations

import json
import sqlite3
import sys
import threading
from pathlib import Path

import pytest

import src.api.unlock as unlock_mod
from src.custody.log import CustodyAction, CustodyLog
from src.custody.signing import HybridSigner
from src.database import at_rest_state, encrypt_tool, file_identity
from src.database.connect import connect, is_encrypted_file, set_passphrase
from src.database.writer import write_gate
from src.versioned import store
from src.versioned.lanes import all_lanes
from src.versioned.models import VersionedEntity

_KEY = "a-long-enough-passphrase-for-r148-9Wd"
#: Windows refuses to replace a file SQLite holds open, so there the swap itself is refused (the store stays plaintext and pending,
#: R742) and no connection can straddle it: the cases that keep one open across the swap describe POSIX file systems.
_POSIX_SWAP = pytest.mark.skipif(sys.platform == "win32", reason="Windows refuses the replace of a file held open; nothing straddles it")
_OTHER = "another-long-enough-passphrase-3Hq"


@pytest.fixture(autouse=True)
def _clean():
    write_gate._reset_for_tests()
    store.dispose_all()
    at_rest_state._probed.clear()
    yield
    store.dispose_all()
    set_passphrase(None)
    at_rest_state._probed.clear()
    write_gate._reset_for_tests()


@pytest.fixture()
def data(tmp_path, monkeypatch):
    """A data folder of the test's own, plaintext, with the corpus these paths resolve to (``main_db_path`` patched, as
    tests/test_versioned_at_rest.py explains)."""
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OO_DB_PLAINTEXT", "1")
    main = tmp_path / "open_omniscience.db"
    c = sqlite3.connect(str(main))
    c.execute("CREATE TABLE t(a)")
    c.commit()
    c.close()
    monkeypatch.setattr(unlock_mod, "main_db_path", lambda: main)
    return tmp_path


def _signer(tmp_path: Path) -> HybridSigner:
    return HybridSigner(ed25519_path=tmp_path / "keys" / "k.pem", mldsa_path=tmp_path / "keys" / "k.key", use_pqc=False)


def _encrypted_with(path: Path, key: str) -> list[str]:
    c = connect(path, key=key, check_same_thread=False)
    try:
        return [r[0] for r in c.execute("SELECT item_id FROM custody_entries ORDER BY seq")]
    finally:
        c.close()


# --- row 148: the custody log -------------------------------------------------------------------------------------------


@_POSIX_SWAP
def test_a_custody_log_opened_before_the_swap_is_refused_and_writes_nothing(data, monkeypatch):
    db = data / "custody_log.db"
    log = CustodyLog(db_path=str(db), signer=_signer(data), anchoring_mode="local")
    log.record("article:1", "a" * 64, CustodyAction.INGEST, actor="pipeline")
    assert not log.replaced(), "control: the log's own file"

    encrypt_tool.encrypt_store("custody", db, _KEY, main=data / "open_omniscience.db")
    assert is_encrypted_file(db) is True

    assert log.replaced()
    with pytest.raises(file_identity.StoreReplacedError) as refused:
        log.record("article:2", "b" * 64, CustodyAction.INGEST, actor="pipeline")
    assert str(refused.value) == file_identity.REPLACED_WORDS
    with pytest.raises(file_identity.StoreReplacedError):
        log.all_entries()
    log.close()
    # the encrypted log holds what was saved before the swap, and nothing the refused log tried after it
    assert _encrypted_with(db, _KEY) == ["article:1"]


def test_a_custody_log_opened_after_the_swap_writes_to_the_encrypted_file(data, monkeypatch):
    """Positive control: the check refuses the old file only."""
    db = data / "custody_log.db"
    with CustodyLog(db_path=str(db), signer=_signer(data), anchoring_mode="local") as log:
        log.record("article:1", "a" * 64, CustodyAction.INGEST, actor="pipeline")
    encrypt_tool.encrypt_store("custody", db, _KEY, main=data / "open_omniscience.db")
    set_passphrase(_KEY)
    with CustodyLog(db_path=str(db), signer=_signer(data), anchoring_mode="local") as log:
        assert not log.replaced()
        log.record("article:2", "b" * 64, CustodyAction.INGEST, actor="pipeline")
    assert _encrypted_with(db, _KEY) == ["article:1", "article:2"]


def test_the_check_and_the_swap_are_ordered_by_the_append_lock():
    """The custody swap holds the append lock, and the identity is checked under it before the tail is read and before the
    insert: the two cannot interleave (a lock and an order, not a counter)."""
    import inspect

    from src.custody import log as log_mod

    store_src = inspect.getsource(encrypt_tool.encrypt_store)
    assert "_APPEND_LOCK" in store_src and "with guard" in store_src
    insert_src = inspect.getsource(log_mod.CustodyLog._insert)
    assert insert_src.index("_refuse_if_replaced()") < insert_src.index("INSERT INTO custody_entries")
    assert "_refuse_if_replaced()" in inspect.getsource(log_mod.CustodyLog._last)


@_POSIX_SWAP
def test_the_ingest_batch_opens_a_fresh_log_when_its_file_was_replaced(data, monkeypatch):
    from src.custody.settings import load_settings
    from src.ingest.pipeline import _CustodyBatch

    monkeypatch.setattr("src.custody.log.HybridSigner", lambda **_kw: _signer(data))
    set_passphrase(_KEY)  # the retry case: the key was already held, so the batch's settings do not change across the swap
    db = data / "custody_log.db"
    # the batch's first log opens a plaintext file, which the swap then replaces
    plain = sqlite3.connect(str(db))
    plain.execute("CREATE TABLE x(a)")
    plain.commit()
    plain.close()
    prefs = load_settings()
    with _CustodyBatch() as batch:
        first = batch.log(prefs)
        first.record("article:1", "a" * 64, CustodyAction.INGEST, actor="pipeline")
        encrypt_tool.encrypt_store("custody", db, _KEY, main=data / "open_omniscience.db")
        second = batch.log(prefs)
        assert second is not first and batch.opened == 2
        second.record("article:2", "b" * 64, CustodyAction.INGEST, actor="pipeline")
    assert _encrypted_with(db, _KEY) == ["article:1", "article:2"]


# --- row 148: the lanes --------------------------------------------------------------------------------------------------


def _lane_ids() -> list[str]:
    with store.lane_session("wiki") as s:
        return sorted(e.external_id for e in s.query(VersionedEntity).all())


@_POSIX_SWAP
def test_a_lane_save_that_began_before_the_swap_is_refused_at_commit_and_lands_nowhere(data):
    path = store.create_lane("wiki")
    with store.lane_session("wiki") as s:
        s.add(VersionedEntity(external_id="oo:Before"))
    s = store.lane_engine("wiki")
    from sqlalchemy.orm import Session

    session = Session(s)
    session.add(VersionedEntity(external_id="oo:Straddling"))
    session.flush()  # written into the old file's log, not committed
    encrypt_tool.encrypt_store("lane:wiki", path, _KEY, main=data / "open_omniscience.db")
    with pytest.raises(file_identity.StoreReplacedError):
        session.commit()
    session.close()
    set_passphrase(_KEY)
    assert _lane_ids() == ["oo:Before"], "the straddling save reached the encrypted lane, or the earlier one was lost"


@_POSIX_SWAP
def test_a_statement_after_the_swap_on_an_earlier_connection_is_refused(data):
    path = store.create_lane("wiki")
    from sqlalchemy import text
    from sqlalchemy.orm import Session

    session = Session(store.lane_engine("wiki"))
    session.execute(text("SELECT 1"))  # the connection is checked out before the swap
    encrypt_tool.encrypt_store("lane:wiki", path, _KEY, main=data / "open_omniscience.db")
    with pytest.raises(file_identity.StoreReplacedError):
        session.add(VersionedEntity(external_id="oo:After"))
        session.flush()
    session.close()


@_POSIX_SWAP
def test_a_pooled_connection_from_before_the_swap_is_dropped_at_checkout_and_the_lane_reads_with_the_key(data):
    path = store.create_lane("wiki")
    with store.lane_session("wiki") as s:
        s.add(VersionedEntity(external_id="oo:Kept"))
    # the engine is NOT disposed: its idle connection still holds the plaintext file
    encrypt_tool.encrypt_store("lane:wiki", path, _KEY, main=data / "open_omniscience.db")
    set_passphrase(_KEY)
    assert _lane_ids() == ["oo:Kept"]
    with store.lane_session("wiki") as s:
        s.add(VersionedEntity(external_id="oo:New"))
    store.dispose_all()
    assert _lane_ids() == ["oo:Kept", "oo:New"], "the new save went to the encrypted file"


# --- row 148: the open itself -------------------------------------------------------------------------------------------


def _replace_with_copy(path: Path) -> None:
    tmp = path.with_name(path.name + ".new")
    tmp.write_bytes(path.read_bytes())
    tmp.replace(path)


@_POSIX_SWAP
def test_an_open_across_a_swap_is_opened_again_once_then_refused(tmp_path):
    p = tmp_path / "s.db"
    sqlite3.connect(str(p)).close()
    calls = []

    def swaps_once():
        calls.append(1)
        conn = sqlite3.connect(str(p))
        if len(calls) == 1:
            _replace_with_copy(p)
        return conn

    conn, ident = file_identity.open_pinned(p, swaps_once)
    assert len(calls) == 2 and ident == file_identity.identity(p)
    conn.close()

    def always_swaps():
        conn = sqlite3.connect(str(p))
        _replace_with_copy(p)
        return conn

    with pytest.raises(file_identity.StoreReplacedError):
        file_identity.open_pinned(p, always_swaps)


# --- row 149: the status knows about keys -------------------------------------------------------------------------------


def _row(st: dict, name: str) -> dict:
    return next(r for r in st["stores"] if r["store"] == name)


def _plain_table(path: Path) -> None:
    """A plaintext store with one table, its connection CLOSED before anything swaps it: on Windows a connection still open
    (one left to garbage collection) refuses the replace (WinError 5), which is the product's held path, not these cases."""
    c = sqlite3.connect(str(path))
    try:
        c.execute("CREATE TABLE x(a)")
        c.commit()
    finally:
        c.close()


def _encrypt_file(path: Path, key: str) -> None:
    encrypt_tool.encrypt_database(path, key, library=False)


def _all_encrypted(data: Path, key: str, lane_key: str | None = None) -> None:
    main = data / "open_omniscience.db"
    _encrypt_file(main, key)
    _plain_table(data / "custody_log.db")
    _encrypt_file(data / "custody_log.db", key)
    for spec in all_lanes():
        lp = data / spec.filename
        _plain_table(lp)
        _encrypt_file(lp, lane_key if (lane_key and spec.kind == "wiki") else key)
    # R821: what the encrypt tool does once the library read back with the key; the corpus is "encrypted" on that record (or a
    # keyed open held in this process), never on its header alone
    at_rest_state.record_encrypted("corpus", main)


def test_a_lane_under_another_passphrase_reads_as_that_and_is_never_complete(data, monkeypatch):
    _all_encrypted(data, _KEY, lane_key=_OTHER)
    set_passphrase(_KEY)
    st = at_rest_state.status()
    assert _row(st, "lane:wiki")["state"] == "not_this_key"
    assert st["not_this_key"] == ["lane:wiki"]
    assert "lane:wiki" not in st["pending"], "nothing here encrypts a store under a second key"
    assert st["complete"] is False
    custody = _row(st, "custody")
    assert custody["state"] == "encrypted" and custody["key_checked"] is True and custody.get("cipher")
    # the finish leaves it as it is
    wiki = next(data / spec.filename for spec in all_lanes() if spec.kind == "wiki")
    before = wiki.read_bytes()
    assert at_rest_state.finish_pending(_KEY) == {"finished": [], "still_pending": []}
    assert wiki.read_bytes() == before


def test_every_store_under_the_held_key_is_complete_and_checked(data):
    """Positive control for the test above: the same files, one key."""
    _all_encrypted(data, _KEY)
    set_passphrase(_KEY)
    st = at_rest_state.status()
    assert st["complete"] is True and st["not_this_key"] == [] and st["pending"] == []
    for r in st["stores"][1:]:
        assert r["state"] == "encrypted" and r["key_checked"] is True, r


def test_the_doctor_says_what_the_status_says_for_every_store(data):
    _all_encrypted(data, _KEY, lane_key=_OTHER)
    set_passphrase(_KEY)
    out = unlock_mod.doctor()
    assert out["lanes"]["wiki"]["state"] == "not_this_key"
    assert out["at_rest"]["not_this_key"] == ["lane:wiki"] and out["at_rest"]["complete"] is False
    assert out["custody_log"]["state"] == "encrypted" and out["custody_log"]["key_checked"] is True
    st = at_rest_state.status()
    for spec in all_lanes():
        assert out["lanes"][spec.kind]["state"] == _row(st, f"lane:{spec.kind}")["state"]


def test_an_unreadable_store_says_why_and_is_never_absent(data, monkeypatch):
    lp = data / all_lanes()[0].filename
    lp.write_bytes(b"short")
    st = at_rest_state.status()
    row = _row(st, f"lane:{all_lanes()[0].kind}")
    assert row == {**row, "state": "unreadable", "reason": "short_header"}

    class _Held(PermissionError):
        winerror = 32

    real_header_file = at_rest_state._header_file

    def refusing(path, *a, **kw):
        if Path(path) == lp:
            raise _Held(13, "held")
        if Path(path).name == "custody_log.db":
            raise PermissionError(13, "denied")
        return real_header_file(path, *a, **kw)

    _plain_table(data / "custody_log.db")
    monkeypatch.setattr(at_rest_state, "_header_file", refusing)
    st = at_rest_state.status()
    # Row 153: a file another program holds is in use right now, not unreadable and not pending.
    assert _row(st, f"lane:{all_lanes()[0].kind}")["state"] == "busy"
    assert st["busy"] == [f"lane:{all_lanes()[0].kind}"]
    assert _row(st, "custody") == {**_row(st, "custody"), "state": "unreadable", "reason": "permission"}
    assert set(at_rest_state.UNREADABLE_REASONS) == {"permission", "short_header", "io"}


def test_the_probe_stands_aside_while_a_store_is_swapped(data):
    """A status read during a swap never opens the store (on Windows that would refuse the replace): it says not checked yet."""
    _all_encrypted(data, _KEY)
    set_passphrase(_KEY)
    entered, release = threading.Event(), threading.Event()

    def hold():
        with at_rest_state.probes_held():
            entered.set()
            release.wait(10)

    t = threading.Thread(target=hold)
    t.start()
    try:
        assert entered.wait(10)
        st = at_rest_state.status()
        # R821: not tried with the key and not on the record: it only LOOKS encrypted
        assert _row(st, "custody") == {**_row(st, "custody"), "state": "looks_encrypted", "key_checked": False}
        assert "custody" in st["unchecked"]
        assert st["complete"] is False, "with a key held, a store it was not tried on is never counted as complete"
    finally:
        release.set()
        t.join(10)
    assert at_rest_state.status()["complete"] is True, "positive control: the same files, checked"
    assert "probes_held()" in __import__("inspect").getsource(encrypt_tool._export_and_swap)


def test_a_busy_store_reads_as_busy_never_as_another_passphrase_or_pending_and_is_not_cached(data):
    """A store another connection holds is not "another passphrase": SQLCipher answers both the same way unless the cause is read.
    Row 153: it reads "busy" (in use, try again), never a read error, never pending, and never complete."""
    _all_encrypted(data, _KEY)
    set_passphrase(_KEY)
    db = data / "custody_log.db"
    holder = connect(db, key=_KEY, check_same_thread=False)
    try:
        holder.execute("BEGIN EXCLUSIVE")
        holder.execute("CREATE TABLE held(a)")
        st = at_rest_state.status()
        row = _row(st, "custody")
        assert row["state"] == "busy" and row["key_checked"] is False and "reason" not in row, row
        assert st["busy"] == ["custody"] and "custody" in st["unchecked"]
        assert "custody" not in st["pending"], "a store in use is not 'still unencrypted'"
        assert st["complete"] is False
    finally:
        holder.rollback()
        holder.close()
    assert _row(at_rest_state.status(), "custody")["state"] == "encrypted", "the busy answer was cached"


def test_a_probe_never_creates_a_store_that_went_missing(data):
    _all_encrypted(data, _KEY)
    lane = next(data / spec.filename for spec in all_lanes() if spec.kind == "wiki")
    lane.unlink()
    out = at_rest_state._probe(lane, _KEY)
    assert out["state"] == "unreadable" and not lane.exists()


def test_a_file_system_without_inodes_disables_the_guard_rather_than_refusing_every_save(tmp_path):
    p = tmp_path / "s.db"
    sqlite3.connect(str(p)).close()
    assert file_identity.same(p, (file_identity.identity(p) or (0, 0))[:1] + (0,))
    assert not file_identity.same(p, None)
    assert not file_identity.same(tmp_path / "gone.db", (1, 2)), "a path that names no file is not the same file"


def test_a_refused_save_answers_409_with_the_fixed_words():
    import asyncio

    from src.api import main

    resp = asyncio.run(main.store_replaced_handler(None, file_identity.StoreReplacedError()))
    assert resp.status_code == 409
    assert json.loads(resp.body) == {"detail": file_identity.REPLACED_WORDS}


def test_the_probe_cache_holds_no_secret(data):
    _all_encrypted(data, _KEY)
    set_passphrase(_KEY)
    at_rest_state.status()
    assert at_rest_state._probed
    flat = json.dumps([[list(map(str, k)), v] for k, v in at_rest_state._probed.items()])
    assert _KEY not in flat


# --- the words reach the page in every language -----------------------------------------------------------------------


def test_every_new_sentence_is_keyed_in_every_locale_and_the_page_uses_the_states():
    root = Path(__file__).resolve().parents[1] / "src" / "static"
    keys = [
        file_identity.REPLACED_WORDS,
        # R821: "encrypted" only on evidence; a header alone, or a key that does not open it, never says "encrypted"
        "Encrypted, per this installation's record (not yet checked with your key)",
        "Looks encrypted; not yet checked with your key",
        "This passphrase does not open it (it may be encrypted with another passphrase, or damaged)",
        "Cannot be read: {why}",
        "These stores do not open with this passphrase (another passphrase, or a damaged file) and are left as they are: {names}.",
        "In use right now, try again in a moment",
        "Not checked yet against this passphrase: {names} (in use, being encrypted, or a read error). Until then, do not count them as encrypted. Open this panel again in a moment.",
        *at_rest_state.UNREADABLE_REASONS.values(),
    ]
    py_keys = [unlock_mod.NOTHING_LEFT_BUT_UNCHECKED, unlock_mod.NOTHING_LEFT_BUT_NOT_THIS_KEY, unlock_mod.NOTHING_LEFT]
    js = (root / "app-backup.js").read_text(encoding="utf-8")
    for k in keys[1:]:
        assert k in js, k
    assert 's.state === "not_this_key"' in js and "ar.not_this_key" in js
    for loc in sorted((root / "locales").glob("*.json")):
        d = json.loads(loc.read_text(encoding="utf-8"))
        for k in keys + py_keys:
            assert d.get(k), f"{loc.name} lacks {k[:40]!r}"
        assert "{n} store(s) do not open with this passphrase (another passphrase, or a damaged file). They are left as they are." not in d
    assert 's.state === "busy"' in js and "ar.key_held" in js and "ar.busy" in js


# --- row 153: the #2113 follow-ups ------------------------------------------------------------------------------------


def test_the_retry_409_names_a_busy_store_and_a_store_under_another_passphrase(data, monkeypatch):
    """With nothing pending, the retry's 409 says why, true at the state it names: never "every store is already encrypted" over a
    store that is in use or does not open with this passphrase."""
    words = unlock_mod._nothing_left_words
    assert words({"busy": ["custody"], "not_this_key": ["lane:wiki"]}) == unlock_mod.NOTHING_LEFT_BUT_UNCHECKED
    assert words({"busy": [], "not_this_key": ["lane:wiki"]}) == unlock_mod.NOTHING_LEFT_BUT_NOT_THIS_KEY
    assert words({"busy": [], "not_this_key": []}) == unlock_mod.NOTHING_LEFT == "every store is already encrypted"
    # an encrypted store whose check did not run to its end (a read error after its header) is not "every store is encrypted"
    unchecked = {"busy": [], "not_this_key": [], "key_held": True, "unchecked": ["custody"]}
    assert words(unchecked) == unlock_mod.NOTHING_LEFT_BUT_UNCHECKED
    assert words({**unchecked, "key_held": False}) == unlock_mod.NOTHING_LEFT, "locked: the headers alone answer"
    # an extended busy code (SQLITE_BUSY_SNAPSHOT, 517) is busy too, never a read error
    err = sqlite3.OperationalError("database is locked")
    err.sqlite_errorcode = 517
    assert at_rest_state._is_busy(err)

    _all_encrypted(data, _KEY, lane_key=_OTHER)
    set_passphrase(_KEY)
    st = at_rest_state.status()
    assert not st["pending"] and words(st) == unlock_mod.NOTHING_LEFT_BUT_NOT_THIS_KEY
    from fastapi import HTTPException

    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-encrypted")
    with pytest.raises(HTTPException) as refused:
        unlock_mod.encrypt_db(unlock_mod.EncryptBody(passphrase=_KEY, confirm=_KEY, consent=True))
    assert refused.value.status_code == 409 and refused.value.detail == unlock_mod.NOTHING_LEFT_BUT_NOT_THIS_KEY


def test_the_status_always_tries_the_held_key_and_says_whether_one_is_held(data):
    """The cache is keyed by the held key's generation, so the status takes no other key (the #2113 cache-reuse nit)."""
    import inspect

    assert "key" not in inspect.signature(at_rest_state.status).parameters
    _all_encrypted(data, _KEY)
    assert at_rest_state.status()["key_held"] is False
    set_passphrase(_KEY)
    st = at_rest_state.status()
    assert st["key_held"] is True and st["complete"] is True
    out = unlock_mod.doctor()["at_rest"]
    assert out["key_held"] is True and out["busy"] == []


@_POSIX_SWAP
def test_a_custody_read_racing_a_swap_is_refused_as_replaced_never_a_bare_sqlite_error(data, monkeypatch):
    """The custody reads run outside the append lock (a large read under it would hold every custody write), so a read can race the
    swap: it is refused as replaced, checked again after the read, and a SQLite error met on a replaced file says "replaced"."""
    db = data / "custody_log.db"
    log = CustodyLog(db_path=str(db), signer=_signer(data), anchoring_mode="local")
    log.record("article:1", "a" * 64, CustodyAction.INGEST, actor="pipeline")
    assert [e.item_id for e in log.all_entries()] == ["article:1"], "control"
    real = log.conn

    class _SwapDuringRead:
        def execute(self, *a):
            cur = real.execute(*a)
            rows = cur.fetchall()
            encrypt_tool.encrypt_store("custody", db, _KEY, main=data / "open_omniscience.db")

            class _Done:
                def fetchall(self):
                    return rows

            return _Done()

    log.conn = _SwapDuringRead()
    with pytest.raises(file_identity.StoreReplacedError):
        log.all_entries()
    assert log.replaced()

    class _Failing:
        def execute(self, *a):
            raise sqlite3.DatabaseError("file is not a database")

    log.conn = _Failing()
    with pytest.raises(file_identity.StoreReplacedError):
        log.entries_for("article:1")
    monkeypatch.setattr(log, "replaced", lambda: False)
    with pytest.raises(sqlite3.DatabaseError):
        log.entries_for("article:1")  # a log whose file is its own: the real error, unchanged
    log.conn = real
    log.close()
