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
import logging
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import time
from pathlib import Path

import pytest
from fastapi import HTTPException

import src.api.unlock as unlock_mod
from src.database import connect as connect_mod
from src.database import encrypt_tool
from src.database.connect import (
    SNAPSHOT_LEFT_ON_DISK,
    SNAPSHOT_WORK_PREFIX,
    SnapshotLeftOnDisk,
    snapshot_to_plaintext,
)
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


def _inner(dest: Path) -> Path | None:
    """The copy's file while it is written: ``dest``'s name inside its private folder (R799)."""
    return next(iter(dest.parent.glob(f"{SNAPSHOT_WORK_PREFIX}*/{dest.name}")), None)


def _work_dirs(folder: Path) -> list[Path]:
    return sorted(folder.glob(f"{SNAPSHOT_WORK_PREFIX}*"))


def _is_inner(path, dest: Path) -> bool:
    p = Path(path)
    return p.name == dest.name and p.parent.name.startswith(SNAPSHOT_WORK_PREFIX)


class _SrcProxy:
    """The source connection of the plaintext branch: its backup runs one page per step, and fails after some pages have
    landed in the destination (a full disk part-way through)."""

    def __init__(self, real: sqlite3.Connection, dest: Path, during) -> None:
        self._real, self._dest, self._during = real, dest, during

    def backup(self, target, **_kw):
        def progress(_status, remaining, total):
            if total - remaining >= total // 2:
                self._during(_inner(self._dest))
                raise OSError(28, "No space left on device")

        self._real.backup(target, pages=1, progress=progress)

    def close(self):
        self._real.close()


def _fail_mid_copy(monkeypatch, src: Path, dest: Path, *, encrypted: bool, during=lambda _d: None) -> None:
    """Make the next ``snapshot_to_plaintext(src, dest)`` fail once part of the copy is written; ``during`` gets the copy's file."""
    if encrypted:
        real_connect = connect_mod.connect

        def keyed(path, *a, **kw):
            conn = real_connect(path, *a, **kw)
            if Path(path) == src:
                calls = [0]

                def handler():
                    calls[0] += 1
                    inner = _inner(dest)
                    if inner is not None and inner.exists() and inner.stat().st_size > 0 and calls[0] > 50:
                        during(inner)
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
            if _is_inner(path, dest):
                conn.execute("PRAGMA cache_size = 1")  # pages spill to the file as they are copied: a real partial on disk
            return _SrcProxy(conn, dest, during) if Path(path) == src else conn

    monkeypatch.setattr(connect_mod, "sqlite3", _Sqlite())


def _refuse_unlinks(monkeypatch) -> None:
    """Every removal of the snapshot's own files fails (by name or relative to its folder)."""

    def refuse(_p, *_a, **_k):
        raise PermissionError(13, "Permission denied")

    scope_os(monkeypatch, connect_mod, unlink=refuse)


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
    seen: list[tuple[int, int]] = []
    _fail_mid_copy(
        monkeypatch, src, dest, encrypted=encrypted,
        during=lambda d: seen.append((d.stat().st_size, stat.S_IMODE(d.parent.stat().st_mode))),
    )
    with pytest.raises(Exception) as failed:
        snapshot_to_plaintext(src, dest)
    assert not isinstance(failed.value, SnapshotLeftOnDisk)
    assert seen and seen[0][0] > 0, "the failure came after part of the copy was written"
    if os.name != "nt":
        assert seen[0][1] == 0o700, "the copy is written inside an owner-only private folder (R799)"
    assert not dest.exists() and _work_dirs(tmp_path) == [], "the whole private folder is gone"
    assert stale_index.read_bytes() == b"x" * 64
    assert neighbour.read_bytes() == b"SQLite format 3\x00 an older partial"


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "sqlcipher"])
def test_a_whole_copy_is_still_returned_and_its_private_folder_is_gone(tmp_path, encrypted):
    src = tmp_path / "store.db"
    (_encrypted_store if encrypted else _plain_store)(src)
    out = snapshot_to_plaintext(src, tmp_path / "snap.db")
    assert out == tmp_path / "snap.db" and not out.is_symlink() and _work_dirs(tmp_path) == []
    c = sqlite3.connect(str(out))
    try:
        assert c.execute("SELECT COUNT(*) FROM t").fetchone()[0] == (_ROWS_ENCRYPTED if encrypted else _ROWS)
    finally:
        c.close()


def test_without_hard_links_the_finished_copy_is_renamed_into_place(tmp_path, monkeypatch):
    src = tmp_path / "store.db"
    _plain_store(src)

    def no_links(*_a, **_k):
        raise PermissionError(1, "Operation not permitted")  # a removable drive's file system

    scope_os(monkeypatch, connect_mod, link=no_links)
    out = snapshot_to_plaintext(src, tmp_path / "snap.db")
    assert out.is_file() and not out.is_symlink() and _work_dirs(tmp_path) == []


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "sqlcipher"])
def test_a_removal_that_fails_is_loud_and_names_the_path(tmp_path, monkeypatch, encrypted):
    src = tmp_path / "store.db"
    (_encrypted_store if encrypted else _plain_store)(src)
    dest = tmp_path / "snap.db"
    _fail_mid_copy(monkeypatch, src, dest, encrypted=encrypted)
    _refuse_unlinks(monkeypatch)
    with pytest.raises(SnapshotLeftOnDisk) as left:
        snapshot_to_plaintext(src, dest)
    (work,) = _work_dirs(tmp_path)
    said = str(left.value)
    assert said == SNAPSHOT_LEFT_ON_DISK.format(path=work)
    assert "incomplete plaintext copy may still be on disk" in said
    assert left.value.__cause__ is None and left.value.__context__ is None, "no driver text travels with the words"
    assert http_detail(left.value, "", _KEY) == said, "the words reach the page whole"
    assert (work / dest.name).exists() and not dest.exists(), "the unfinished copy never had the snapshot's name"


def test_the_private_folder_swapped_for_a_link_mid_copy_is_never_walked_or_returned(tmp_path, monkeypatch):
    src = tmp_path / "store.db"
    _plain_store(src)
    dest = tmp_path / "snap.db"
    victim = tmp_path / "victim-folder"
    victim.mkdir()
    (victim / "keep.txt").write_text("keep me", encoding="utf-8")
    moved = tmp_path / "moved-away"

    def swap(inner: Path) -> None:
        work = inner.parent
        os.replace(work, moved)
        os.symlink(victim, work, target_is_directory=True)

    _fail_mid_copy(monkeypatch, src, dest, encrypted=False, during=swap)
    with pytest.raises(SnapshotLeftOnDisk) as left:
        snapshot_to_plaintext(src, dest)
    (work,) = _work_dirs(tmp_path)
    assert work.is_symlink() and str(work) in str(left.value), "not the folder this call made: left, and said"
    assert sorted(p.name for p in victim.iterdir()) == ["keep.txt"], "nothing removed or written through the link"
    assert not dest.exists()


@pytest.mark.parametrize("encrypted", [False, True], ids=["plaintext", "sqlcipher"])
def test_the_copy_swapped_for_a_link_before_sqlite_opens_it_is_never_given_the_name(tmp_path, monkeypatch, encrypted):
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
    with pytest.raises(OSError) as failed:
        snapshot_to_plaintext(src, dest)
    # SQLite opens by name and follows the link: the identity checks after the copy keep it from ever getting the snapshot's
    # name. R799 narrows where plaintext can land; it does not claim a same-user program cannot redirect it.
    assert not isinstance(failed.value, SnapshotLeftOnDisk)
    assert not dest.exists() and _work_dirs(tmp_path) == []


def test_a_final_name_taken_by_a_link_is_never_replaced_or_written_through(tmp_path, monkeypatch):
    src = tmp_path / "store.db"
    _plain_store(src)
    dest = tmp_path / "snap.db"
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    real_place = connect_mod._place

    def plant_then_place(inner, d):
        os.symlink(victim, d)
        return real_place(inner, d)

    monkeypatch.setattr(connect_mod, "_place", plant_then_place)
    with pytest.raises(FileExistsError):
        snapshot_to_plaintext(src, dest)
    assert dest.is_symlink() and victim.read_text(encoding="utf-8") == "keep me"
    assert _work_dirs(tmp_path) == []


def test_a_final_name_taken_between_the_check_and_the_link_is_still_refused(tmp_path, monkeypatch):
    src = tmp_path / "store.db"
    _plain_store(src)
    dest = tmp_path / "snap.db"
    victim = tmp_path / "victim.txt"
    victim.write_text("keep me", encoding="utf-8")
    real_link = os.link

    def race(a, b, *args, **kw):
        os.symlink(victim, b)  # after the name was checked, before the link
        return real_link(a, b, *args, **kw)

    scope_os(monkeypatch, connect_mod, link=race)
    with pytest.raises(FileExistsError):
        snapshot_to_plaintext(src, dest)
    assert dest.is_symlink() and victim.read_text(encoding="utf-8") == "keep me"
    assert _work_dirs(tmp_path) == []


def test_an_interrupt_mid_copy_is_passed_on_and_the_copy_removed(tmp_path, monkeypatch):
    src = tmp_path / "store.db"
    _plain_store(src)
    dest = tmp_path / "snap.db"

    def stop(_d):
        raise KeyboardInterrupt

    _fail_mid_copy(monkeypatch, src, dest, encrypted=False, during=stop)
    with pytest.raises(KeyboardInterrupt):
        snapshot_to_plaintext(src, dest)
    assert not dest.exists() and _work_dirs(tmp_path) == []


def test_an_interrupt_whose_copy_could_not_be_removed_is_never_removed_by_name_later(tmp_path, monkeypatch):
    store = tmp_path / "custody_log.db"
    _plain_store(store)
    real = connect_mod.snapshot_to_plaintext

    def stop(_d):
        raise KeyboardInterrupt

    def cut(src, dest):
        _fail_mid_copy(monkeypatch, Path(src), Path(dest), encrypted=False, during=stop)
        _refuse_unlinks(monkeypatch)
        return real(src, dest)

    monkeypatch.setattr(encrypt_tool, "snapshot_to_plaintext", cut)
    with pytest.raises(KeyboardInterrupt) as stopped:
        encrypt_tool.encrypt_database(store, _KEY, keep_snapshot_on_failure=False)
    (work,) = _work_dirs(tmp_path)
    assert stopped.value.oo_snapshot_left == work and work.is_dir()
    assert sorted(tmp_path.glob("pre-encrypt-*")) == []


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
    assert sorted(tmp_path.glob("pre-encrypt-*")) == [] and _work_dirs(tmp_path) == []
    assert connect_mod.is_encrypted_file(store) is False


def test_the_encrypt_tool_leaves_a_snapshot_it_could_not_remove_alone_and_says_so(tmp_path, monkeypatch):
    store = tmp_path / "custody_log.db"
    _plain_store(store)
    real = connect_mod.snapshot_to_plaintext

    def cut(src, dest):
        _fail_mid_copy(monkeypatch, Path(src), Path(dest), encrypted=False)
        _refuse_unlinks(monkeypatch)  # only the snapshot's own removal fails
        return real(src, dest)

    monkeypatch.setattr(encrypt_tool, "snapshot_to_plaintext", cut)
    with pytest.raises(SnapshotLeftOnDisk) as said:
        encrypt_tool.encrypt_database(store, _KEY, keep_snapshot_on_failure=False)
    (work,) = _work_dirs(tmp_path)
    assert work.is_dir() and str(work) in str(said.value)


# --- crash leftovers (R799) ---------------------------------------------------------------------------------------------------


def _leftover(folder: Path, name: str, *, age_s: float = 3600.0) -> Path:
    work = folder / (SNAPSHOT_WORK_PREFIX + name)
    work.mkdir()
    inner = work / "snap.db"
    inner.write_bytes(b"SQLite format 3\x00 plaintext left by a crash")
    old = time.time() - age_s
    os.utime(inner, (old, old))
    os.utime(work, (old, old))
    return work


@pytest.fixture()
def data(tmp_path, monkeypatch):
    folder = tmp_path / "data"
    folder.mkdir()
    monkeypatch.setattr("src.paths.data_dir", lambda: folder)
    return folder


def test_a_crash_leftover_in_the_data_folder_is_removed_and_logged_masked(data, caplog):
    work = _leftover(data, "crash1")
    caplog.set_level(logging.INFO, logger="database.connect")
    assert connect_mod.sweep_snapshot_leftovers(data) == 1
    assert not work.exists()
    assert "<data>/" in caplog.text and str(data) not in caplog.text


def test_only_its_own_kind_of_leftover_is_removed(data, tmp_path, monkeypatch, caplog):
    recent = _leftover(data, "recent", age_s=10)  # may be a copy still running in another process
    target = tmp_path / "not-ours"
    target.mkdir()
    (target / "keep.txt").write_text("keep me", encoding="utf-8")
    link = data / (SNAPSHOT_WORK_PREFIX + "link")
    os.symlink(target, link, target_is_directory=True)
    plain_file = data / (SNAPSHOT_WORK_PREFIX + "file")
    plain_file.write_bytes(b"x")
    other = data / "unrelated-folder"
    other.mkdir()
    caplog.set_level(logging.INFO, logger="database.connect")
    assert connect_mod.sweep_snapshot_leftovers(data) == 0
    assert recent.is_dir() and link.is_symlink() and plain_file.is_file() and other.is_dir()
    assert (target / "keep.txt").read_text(encoding="utf-8") == "keep me"
    assert caplog.text.count("left as it is") == 3 and str(tmp_path) not in caplog.text


def test_a_leftover_owned_by_another_user_is_left(data, monkeypatch):
    work = _leftover(data, "theirs")
    if not hasattr(os, "getuid"):
        pytest.skip("no owner on this system: nothing is removed, which the sweep's own rule already says")
    scope_os(monkeypatch, connect_mod, getuid=lambda: os.getuid() + 1)
    assert connect_mod.sweep_snapshot_leftovers(data) == 0 and work.is_dir()


def test_a_leftover_outside_the_data_folder_is_never_swept(data, tmp_path):
    elsewhere = tmp_path / "usb-stick"
    elsewhere.mkdir()
    work = _leftover(elsewhere, "away")
    assert connect_mod.sweep_snapshot_leftovers(elsewhere) == 0 and work.is_dir()


def test_the_next_snapshot_in_the_data_folder_sweeps_and_never_takes_its_own_folder(data):
    old = _leftover(data, "crash2")
    src = data / "store.db"
    _plain_store(src)
    out = snapshot_to_plaintext(src, data / "pre-encrypt-x-store.db")
    assert out.is_file() and not old.exists() and _work_dirs(data) == []


def test_the_start_sweeps_the_data_folder():
    from tests.js_source_helper import python_function_source

    body = python_function_source((ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8"), "_run_startup_upkeep")
    assert "sweep_snapshot_leftovers(" in body


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


def test_a_failure_right_after_the_name_was_given_removes_that_name_too(tmp_path, monkeypatch):
    src = tmp_path / "store.db"
    _plain_store(src)
    dest = tmp_path / "snap.db"
    real_place = connect_mod._place

    def place_then_stop(inner, d):
        real_place(inner, d)
        raise KeyboardInterrupt  # after the link, before the call could say so

    monkeypatch.setattr(connect_mod, "_place", place_then_stop)
    with pytest.raises(KeyboardInterrupt):
        snapshot_to_plaintext(src, dest)
    assert not dest.exists() and _work_dirs(tmp_path) == [], "no plaintext copy is left at a name the call never returned"


def test_a_running_copy_in_a_data_folder_reached_through_a_link_is_never_swept(tmp_path, monkeypatch):
    real = tmp_path / "real-data"
    real.mkdir()
    linked = tmp_path / "linked-data"
    os.symlink(real, linked, target_is_directory=True)
    monkeypatch.setattr("src.paths.data_dir", lambda: linked)
    monkeypatch.setattr(connect_mod, "_LEFTOVER_QUIET_S", 0)  # only the running-copy guard can keep it
    src = real / "store.db"
    _plain_store(src)
    swept: list[int] = []

    def sweep_during(_inner: Path) -> None:
        swept.append(connect_mod.sweep_snapshot_leftovers(real))
        assert _inner.exists(), "the sweep took the running copy's folder"

    _fail_mid_copy(monkeypatch, src, linked / "snap.db", encrypted=False, during=sweep_during)
    with pytest.raises(OSError):
        snapshot_to_plaintext(src, linked / "snap.db")
    assert swept == [0]


def test_the_off_peak_maintenance_sweeps_snapshot_leftovers_again():
    from tests.js_source_helper import python_function_source

    body = python_function_source((ROOT / "src" / "scheduler" / "maintenance.py").read_text(encoding="utf-8"), "run_idle_maintenance")
    assert "sweep_snapshot_leftovers(data_dir())" in body
