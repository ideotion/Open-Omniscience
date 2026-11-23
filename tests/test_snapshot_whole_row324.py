"""Row 324 (R794): a plaintext snapshot that fails part-way leaves nothing behind, or says loudly where it is.

``snapshot_to_plaintext`` writes a full PLAINTEXT copy of a store beside it (the encrypt tool's escape hatch, a backup's
members). A copy cut short (a full disk, a driver error, an interrupt) used to stay on the disk under a name that reads as a
snapshot. These tests force the failure MID-COPY on real stores, plaintext and encrypted, and check that:

* the unfinished file is removed, by its exact path and identity, never through a link and never anything else in the folder;
* a removal that fails raises :class:`SnapshotLeftOnDisk`, whose one fixed sentence names the path and says an incomplete
  plaintext copy may still be on disk, with no cause or context (so no driver text travels with it and the words reach the page);
* the encrypt tool never keeps a cut-short snapshot (the operator's run included), and says a leftover to the operator;
* the sentence is keyed in all 12 locales and read back by the page.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path

import pytest
from fastapi import HTTPException

import src.api.unlock as unlock_mod
from src.database import connect as connect_mod
from src.database import encrypt_tool
from src.database.connect import SNAPSHOT_LEFT_ON_DISK, SnapshotLeftOnDisk, snapshot_to_plaintext
from src.database.writer import write_gate
from src.monitoring.secret_scrub import http_detail
from tests.js_source_helper import function_source
from tests.os_scope import scope_os

_KEY = "a-long-enough-passphrase-for-row-324-Wd3"
ROOT = Path(__file__).resolve().parents[1]
_ROWS = 400
_ROWS_ENCRYPTED = 1500


@pytest.fixture(autouse=True)
def _clean():
    write_gate._reset_for_tests()
    yield
    connect_mod.set_passphrase(None)
    write_gate._reset_for_tests()


def _plain_store(path: Path) -> None:
    c = sqlite3.connect(str(path))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t (b BLOB)")
    for _ in range(_ROWS):
        c.execute("INSERT INTO t VALUES (?)", (os.urandom(4000),))
    c.commit()
    c.close()


def _encrypted_store(path: Path) -> None:
    pytest.importorskip("sqlcipher3")
    c = connect_mod.connect(path, key=_KEY, check_same_thread=False, create_encrypted=True)
    c.execute("CREATE TABLE t (b BLOB)")
    # past the export's page cache (2 MB by default), so pages reach the destination file while the copy runs
    for _ in range(_ROWS_ENCRYPTED):
        c.execute("INSERT INTO t VALUES (?)", (os.urandom(4000),))
    c.commit()
    c.close()
    connect_mod.set_passphrase(_KEY)  # the snapshot opens the source with the key the process holds


class _SrcProxy:
    """The source connection of the plaintext branch: its backup runs one page per step, and fails after some pages have
    landed in the destination (a full disk part-way through)."""

    def __init__(self, real: sqlite3.Connection, dest: Path, during) -> None:
        self._real, self._dest, self._during = real, dest, during

    def backup(self, target, **_kw):
        def progress(_status, remaining, total):
            if total - remaining >= total // 2:
                self._during(self._dest)
                raise OSError(28, "No space left on device")

        self._real.backup(target, pages=1, progress=progress)

    def close(self):
        self._real.close()


def _fail_mid_copy(monkeypatch, src: Path, dest: Path, *, encrypted: bool, during=lambda _d: None) -> None:
    """Make the next ``snapshot_to_plaintext(src, dest)`` fail once part of the copy is written."""
    if encrypted:
        real_connect = connect_mod.connect

        def keyed(path, *a, **kw):
            conn = real_connect(path, *a, **kw)
            if Path(path) == src:
                calls = [0]

                def handler():
                    calls[0] += 1
                    if dest.exists() and dest.stat().st_size > 0 and calls[0] > 50:
                        during(dest)
                        return 1  # interrupts sqlcipher_export: "interrupted"
                    return 0

                conn.set_progress_handler(handler, 100)
            return conn

        monkeypatch.setattr(connect_mod, "connect", keyed)
        return

    real_sqlite = connect_mod.sqlite3

    class _Sqlite:
        def __getattr__(self, name):
            return getattr(real_sqlite, name)

        def connect(self, path, *a, **kw):
            conn = real_sqlite.connect(path, *a, **kw)
            if Path(path) == dest:
                conn.execute("PRAGMA cache_size = 1")  # pages spill to the file as they are copied: a real partial on disk
            return _SrcProxy(conn, dest, during) if Path(path) == src else conn

    monkeypatch.setattr(connect_mod, "sqlite3", _Sqlite())


# --- the snapshot itself -----------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "sqlcipher"])
def test_a_copy_cut_short_mid_way_is_removed_and_nothing_else_in_the_folder(tmp_path, monkeypatch, encrypted):
    src = tmp_path / "store.db"
    (_encrypted_store if encrypted else _plain_store)(src)
    neighbour = tmp_path / "pre-encrypt-20200101T000000Z-store.db"  # an older build's partial: untouched, R794
    neighbour.write_bytes(b"SQLite format 3\x00 an older partial")
    dest = tmp_path / "snap.db"
    stale_index = Path(str(dest) + "-shm")
    stale_index.write_bytes(b"x" * 64)  # already there before the copy: not made by it, so never removed by it
    sizes: list[int] = []
    _fail_mid_copy(monkeypatch, src, dest, encrypted=encrypted, during=lambda d: sizes.append(d.stat().st_size))
    with pytest.raises(Exception) as failed:
        snapshot_to_plaintext(src, dest)
    assert not isinstance(failed.value, SnapshotLeftOnDisk)
    assert sizes and sizes[0] > 0, "the failure came after part of the copy was written"
    assert not dest.exists() and not Path(str(dest) + "-journal").exists()
    assert stale_index.read_bytes() == b"x" * 64
    assert neighbour.read_bytes() == b"SQLite format 3\x00 an older partial"
    assert {p.name for p in tmp_path.iterdir()} >= {"store.db", neighbour.name, stale_index.name}
    assert "snap.db" not in {p.name for p in tmp_path.iterdir()}


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "sqlcipher"])
def test_a_whole_copy_is_still_returned(tmp_path, encrypted):
    src = tmp_path / "store.db"
    (_encrypted_store if encrypted else _plain_store)(src)
    out = snapshot_to_plaintext(src, tmp_path / "snap.db")
    c = sqlite3.connect(str(out))
    try:
        assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == (_ROWS_ENCRYPTED if encrypted else _ROWS)
    finally:
        c.close()


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "sqlcipher"])
def test_a_removal_that_fails_is_loud_and_names_the_path(tmp_path, monkeypatch, encrypted):
    src = tmp_path / "store.db"
    (_encrypted_store if encrypted else _plain_store)(src)
    dest = tmp_path / "snap.db"
    _fail_mid_copy(monkeypatch, src, dest, encrypted=encrypted)

    def refuse(path, *a, **kw):
        if Path(path) == dest:
            raise PermissionError(13, "Permission denied")
        return os.unlink(path, *a, **kw)

    scope_os(monkeypatch, connect_mod, unlink=refuse)
    with pytest.raises(SnapshotLeftOnDisk) as left:
        snapshot_to_plaintext(src, dest)
    said = str(left.value)
    assert said == SNAPSHOT_LEFT_ON_DISK.format(path=dest)
    assert str(dest) in said and "incomplete plaintext copy may still be on disk" in said
    assert left.value.__cause__ is None and left.value.__context__ is None, "no driver text travels with the words"
    assert http_detail(left.value, "", _KEY) == said, "the words reach the page whole"
    assert dest.exists(), "the file it could not remove is still there, as the words say"


def test_a_name_that_became_a_link_is_not_removed_through_it(tmp_path, monkeypatch):
    src = tmp_path / "store.db"
    _plain_store(src)
    dest = tmp_path / "snap.db"
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    moved = tmp_path / "moved-away.db"

    def swap(d: Path) -> None:
        os.replace(d, moved)
        os.symlink(victim, d)

    _fail_mid_copy(monkeypatch, src, dest, encrypted=False, during=swap)
    with pytest.raises(SnapshotLeftOnDisk) as left:
        snapshot_to_plaintext(src, dest)
    assert str(dest) in str(left.value), "the copy is not accounted for at its name: said, never assumed gone"
    assert victim.read_text(encoding="utf-8") == "keep me"
    assert dest.is_symlink(), "the link is not the file this call made: left where it is"


def test_an_interrupt_mid_copy_is_passed_on_and_the_copy_removed(tmp_path, monkeypatch):
    src = tmp_path / "store.db"
    _plain_store(src)
    dest = tmp_path / "snap.db"

    def stop(_d):
        raise KeyboardInterrupt

    _fail_mid_copy(monkeypatch, src, dest, encrypted=False, during=stop)
    with pytest.raises(KeyboardInterrupt):
        snapshot_to_plaintext(src, dest)
    assert not dest.exists()


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "sqlcipher"])
def test_a_name_swapped_for_a_link_before_sqlite_opens_it_is_never_returned(tmp_path, monkeypatch, encrypted):
    src = tmp_path / "store.db"
    (_encrypted_store if encrypted else _plain_store)(src)
    dest = tmp_path / "snap.db"
    victim = tmp_path / "elsewhere.db"
    real_make = connect_mod._make_new

    def make_then_swap(d):
        made = real_make(d)
        os.replace(d, tmp_path / "moved.db")
        victim.write_bytes(b"")
        os.symlink(victim, d)
        return made

    monkeypatch.setattr(connect_mod, "_make_new", make_then_swap)
    with pytest.raises(SnapshotLeftOnDisk) as left:
        snapshot_to_plaintext(src, dest)
    # SQLite opens by name and follows the link (its ``nofollow`` URI flag did not refuse one here, measured): the identity check
    # after the copy is what keeps the name from being returned as a snapshot, and the error names it.
    assert str(dest) in str(left.value) and dest.is_symlink()


def test_an_interrupt_whose_copy_could_not_be_removed_is_never_removed_by_name_later(tmp_path, monkeypatch):
    store = tmp_path / "custody_log.db"
    _plain_store(store)
    real = connect_mod.snapshot_to_plaintext

    def stop(_d):
        raise KeyboardInterrupt

    def refuse(_p, *_a, **_k):
        raise PermissionError(13, "Permission denied")

    def cut(src, dest):
        _fail_mid_copy(monkeypatch, Path(src), Path(dest), encrypted=False, during=stop)
        scope_os(monkeypatch, connect_mod, unlink=refuse)
        return real(src, dest)

    monkeypatch.setattr(encrypt_tool, "snapshot_to_plaintext", cut)
    with pytest.raises(KeyboardInterrupt) as stopped:
        encrypt_tool.encrypt_database(store, _KEY, keep_snapshot_on_failure=False)
    left = sorted(tmp_path.glob("pre-encrypt-*"))
    assert len(left) == 1 and stopped.value.oo_snapshot_left == left[0]


# --- the encrypt tool ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("keep", [True, False], ids=["operator-run", "automatic-retry"])
def test_the_encrypt_tool_never_keeps_a_cut_short_snapshot(tmp_path, monkeypatch, keep):
    store = tmp_path / "custody_log.db"
    _plain_store(store)
    real = connect_mod.snapshot_to_plaintext

    def cut(src, dest):
        _fail_mid_copy(monkeypatch, Path(src), Path(dest), encrypted=False)
        return real(src, dest)

    monkeypatch.setattr(encrypt_tool, "snapshot_to_plaintext", cut)
    with pytest.raises(OSError):
        encrypt_tool.encrypt_database(store, _KEY, keep_snapshot_on_failure=keep)
    assert sorted(tmp_path.glob("pre-encrypt-*")) == []
    assert connect_mod.is_encrypted_file(store) is False


def test_the_encrypt_tool_leaves_a_snapshot_it_could_not_remove_alone_and_says_so(tmp_path, monkeypatch):
    store = tmp_path / "custody_log.db"
    _plain_store(store)
    real = connect_mod.snapshot_to_plaintext

    def refuse(_p, *_a, **_k):
        raise PermissionError(13, "Permission denied")

    def cut(src, dest):
        _fail_mid_copy(monkeypatch, Path(src), Path(dest), encrypted=False)
        scope_os(monkeypatch, connect_mod, unlink=refuse)  # only the snapshot's own removal fails
        return real(src, dest)

    monkeypatch.setattr(encrypt_tool, "snapshot_to_plaintext", cut)
    with pytest.raises(SnapshotLeftOnDisk) as said:
        encrypt_tool.encrypt_database(store, _KEY, keep_snapshot_on_failure=False)
    left = sorted(tmp_path.glob("pre-encrypt-*"))
    # The retry's own clean-up (``Path.unlink``, not refused here) would have removed it: it is never touched again by name.
    assert len(left) == 1 and str(left[0]) in str(said.value)


def test_a_later_store_left_on_disk_is_said_beside_the_pending_stores(tmp_path, monkeypatch):
    words = SNAPSHOT_LEFT_ON_DISK.format(path=tmp_path / "pre-encrypt-x-custody_log.db")

    def refuse(name, path, key, **kw):
        raise SnapshotLeftOnDisk(tmp_path / "pre-encrypt-x-custody_log.db")

    monkeypatch.setattr(encrypt_tool, "encrypt_store", refuse)
    reasons: list[str] = []
    pending = encrypt_tool._encrypt_the_rest([("custody", tmp_path / "custody_log.db")], _KEY, tmp_path / "c.db", {}, reasons)
    assert pending == ["custody"] and reasons == [words]


def test_the_route_answers_with_the_words_when_the_library_copy_is_left(monkeypatch, tmp_path):
    monkeypatch.setattr("src.database.session.dispose_engine", lambda: None)
    seen: list[str] = []
    monkeypatch.setattr(connect_mod, "set_passphrase", lambda p: seen.append(p))
    monkeypatch.setattr(unlock_mod, "app_lock_state", lambda: "unlocked-plaintext")
    path = tmp_path / "pre-encrypt-x-corpus.db"

    def left(_key, **_kw):
        raise SnapshotLeftOnDisk(path)

    monkeypatch.setattr(encrypt_tool, "encrypt_all", left)
    with pytest.raises(HTTPException) as refused:
        unlock_mod.encrypt_db(unlock_mod.EncryptBody(passphrase=_KEY, confirm=_KEY, consent=True))
    assert refused.value.status_code == 500
    assert refused.value.detail == SNAPSHOT_LEFT_ON_DISK.format(path=path)
    assert _KEY not in refused.value.detail and seen == []


# --- the page -----------------------------------------------------------------------------------------------------------------

_FRAME = SNAPSHOT_LEFT_ON_DISK.replace('"{path}"', "“{path}”")


def _locale(lang: str) -> dict:
    return json.loads((ROOT / "src" / "static" / "locales" / f"{lang}.json").read_text(encoding="utf-8"))


def test_the_sentence_is_keyed_in_every_locale():
    for lang in ("en", "fr", "de", "es", "pt", "ru", "ar", "zh", "ja", "hi", "bn", "id"):
        said = _locale(lang).get(_FRAME)
        assert said and said.count("{path}") == 1, lang


def test_the_page_reads_the_sentence_back_with_the_path_as_written():
    if shutil.which("node") is None:
        pytest.skip("node is not installed")
    core = (ROOT / "src" / "static" / "app-core.js").read_text(encoding="utf-8")
    size_re = re.search(r'const _OO_SIZE_RE = ("[^"\n]*");', core)
    assert size_re
    fr = _locale("fr")
    path = "/home/me/data/pre-encrypt-20261122T101010Z-open_omniscience.db"
    script = (
        "const FR = " + json.dumps(fr, ensure_ascii=False) + ";\n"
        "globalThis.OOI18N = { t: (s) => FR[s] || s, tf: (s, v) => (FR[s] || s).replace(/\\{(\\w+)\\}/g, (m, k) => v[k] != null ? String(v[k]) : m) };\n"
        "globalThis.window = globalThis;\n"
        "function _sizeText(b) { return String(b); }\n"
        "const _OO_SPACE_WHAT = {}; const _OO_SPACE_RES = [];\n"
        "const _OO_SIZE_RE = " + size_re.group(1) + ";\n"
        + function_source(core, "ooServerText")
        + "\nconsole.log(JSON.stringify(ooServerText(" + json.dumps(SNAPSHOT_LEFT_ON_DISK.format(path=path)) + ")));\n"
    )
    run = subprocess.run(["node", "-"], input=script, capture_output=True, text=True, timeout=60, check=False)
    assert run.returncode == 0, run.stderr[-2000:]
    said = json.loads(run.stdout)
    assert said == fr[_FRAME].replace("{path}", "⁨" + path + "⁩"), said
