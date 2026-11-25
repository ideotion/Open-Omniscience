"""
Row 332 (R797): the erase's whole-file rewrite is sparse-aware and disk-safe, in the panic wipe and the uninstall watcher.

Before this row a whole rewrite wrote every byte of a file's LOGICAL size: a sparse file (a 1 TiB logical, 2 MiB real virtual
disk or dump kept in the data folder) had every hole filled, and the erase could fill the disk -- the app's own volume, mid
panic. Now:

(a) salt and key pages, and the logs that hold copies of the salt page, are written first and whole, never held to a cap;
(b) the rest is rewritten only where it holds data (``SEEK_DATA``/``SEEK_HOLE``); where that cannot be read, by logical size,
    but never leaving less than the fixed reserve free nor growing the file's disk use by more than it;
(c) any stop is logged and reported as "partially overwritten", bytes done of bytes known, never "destroyed"; the result is
    "may be incomplete";
(d) the delete goes on regardless;
(e) disk use never grows past what the file holds plus the reserve.

The "nearly full file system" cases simulate the free-space reading (a real one needs a mount, which a test runner cannot
make); the sparse cases use a real sparse file on the test's own file system, and skip where it keeps no holes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.database.connect import have_driver
from src.safety import crypto_erase

MiB = 1024 * 1024
_HOLE = 96 * MiB  # past the reserve, so filling it would cross (e)


def _sparse(path: Path) -> tuple[bytes, bytes]:
    """A real sparse file: 1 MiB of data, a hole of ``_HOLE``, 1 MiB of data. Skips where the file system keeps no holes."""
    head, tail = b"H" * MiB, b"T" * MiB
    with open(path, "wb") as f:
        f.write(head)
        f.seek(MiB + _HOLE)
        f.write(tail)
    st = os.stat(path)
    if not hasattr(st, "st_blocks") or st.st_blocks * 512 > 8 * MiB:
        pytest.skip("this file system keeps no holes")
    return head, tail


def _filling_disk():
    """A drive with room for one chunk past the reserve, then none: the first chunk is written, the next one stops."""
    calls = {"n": 0}

    def free(fd: int) -> int:
        calls["n"] += 1
        return crypto_erase._DISK_RESERVE + (crypto_erase._CHUNK if calls["n"] == 1 else 0)

    return free


def _held(path: Path) -> int:
    return os.open(path, os.O_RDONLY)  # read after the erase: the unlinked file through this descriptor


def _regions_kept(fd: int) -> bool:
    """The hole is still a hole: no data from just after the first region to just before the second."""
    try:
        return os.lseek(fd, MiB, os.SEEK_DATA) >= MiB + _HOLE
    except OSError:
        return True


@pytest.mark.skipif(not hasattr(os, "SEEK_DATA"), reason="no SEEK_DATA on this platform")
def test_a_sparse_file_s_data_is_overwritten_and_its_hole_never_filled(tmp_path):
    blob = tmp_path / "disk.img"
    head, tail = _sparse(blob)
    fd = _held(blob)
    try:
        blocks = os.fstat(fd).st_blocks
        assert crypto_erase._overwrite(blob, keyed=False) is True
        assert os.pread(fd, MiB, 0) != head and os.pread(fd, MiB, MiB + _HOLE) != tail
        assert os.fstat(fd).st_blocks <= blocks + 64  # (e): nothing grew beyond what it held (64 blocks of slack for metadata)
        assert _regions_kept(fd)
    finally:
        os.close(fd)


def test_a_nearly_full_disk_stops_the_rewrite_reports_it_partial_and_still_deletes(tmp_path, monkeypatch):
    """No SEEK_DATA (the fallback: logical size) on a disk with less than the reserve free: the rewrite stops as soon as the file
    grows, the file is still deleted, and the erase says "partially overwritten" and "may be incomplete"."""
    data = tmp_path / "OOS data"
    data.mkdir()
    blob = data / "dump.bin"
    _sparse(blob)
    monkeypatch.setattr(crypto_erase, "_data_regions", lambda fd, limit: None)
    monkeypatch.setattr(crypto_erase, "_fd_free_bytes", _filling_disk())
    fd = _held(blob)
    try:
        report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
        grown = os.fstat(fd).st_blocks * 512
    finally:
        os.close(fd)
    assert not blob.exists()  # (d)
    assert report["partially_overwritten"] == 1, report
    assert 0 < report["partial_bytes_done"] < report["partial_bytes_known"] == 2 * MiB + _HOLE, report
    assert "partially overwritten" in report["limit"] and "unrecoverable regardless" not in report["limit"], report
    assert str(blob) in report["overwrite_failures"]
    assert report["not_overwritten"] == 0, report  # a partial file is said once, under its own caveat (Revision 3)
    assert grown <= 2 * MiB + crypto_erase._DISK_RESERVE + crypto_erase._CHUNK  # (e)


def test_key_files_and_logs_are_never_held_to_the_reserve(tmp_path, monkeypatch):
    """(a): with the disk reported full, a key file and a log are still written whole."""
    data = tmp_path / "OOS data"
    (data / "keys").mkdir(parents=True)
    key = data / "keys" / "custody_ed25519.pem"
    key.write_bytes(b"PRIVATE KEY" * 1000)
    wal = data / "open_omniscience.db-wal"
    wal.write_bytes(b"SALT-COPY-" * 50_000)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    monkeypatch.setattr(crypto_erase, "_data_regions", lambda fd, limit: None)
    monkeypatch.setattr(crypto_erase, "_fd_free_bytes", lambda fd: 0)  # every capped write would stop at once
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert "custody_ed25519.pem" in report["keys_destroyed"], report
    assert str(wal) not in report["overwrite_failures"], report
    assert report["partially_overwritten"] == 0, report


@pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="a real sparse file and a store held open, Linux only")
@pytest.mark.parametrize("full", [False, True])
def test_an_encrypted_store_beside_a_sparse_file(tmp_path, monkeypatch, full):
    """Encrypted: the salt page goes first and whole either way; a sparse file beside it never has its hole filled, and on a
    nearly full disk is reported partial."""
    from tests.test_crypto_erase_second_process import _store

    data, salt = _store(tmp_path)
    (data / "wiki_dumps").mkdir()
    blob = data / "wiki_dumps" / "enwiki-latest-pages-articles.xml.bz2"  # a large file the app keeps in its own folder (row 378 shape)
    _sparse(blob)
    if full:
        monkeypatch.setattr(crypto_erase, "_data_regions", lambda fd, limit: None)
        monkeypatch.setattr(crypto_erase, "_fd_free_bytes", _filling_disk())
    fd = _held(blob)
    try:
        report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
        if not full:
            assert _regions_kept(fd)
    finally:
        os.close(fd)
    assert crypto_erase._MAIN_DB in report["headers_destroyed"], report
    assert report["encrypted_corpus"] is True
    assert report["partially_overwritten"] == (1 if full else 0), report
    assert not blob.exists()


def test_a_plaintext_store_beside_a_sparse_file(tmp_path):
    data = tmp_path / "OOS data"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"SQLite format 3\x00" + b"P" * 8176)
    blob = data / "vm.img"
    _sparse(blob)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["encrypted_corpus"] is not True
    assert report["partially_overwritten"] == 0 and report["overwrite_failures"] == [], report
    assert not blob.exists()


def test_the_panic_page_and_the_cli_say_partially_overwritten():
    from tests.js_source_helper import python_function_source

    js = Path("src/static/app-backup.js").read_text(encoding="utf-8")
    assert 'const clean = holder === "none" && unlisted === 0 && partial === 0 && failed === 0 && ' in js
    assert "Some files could not be overwritten before they were deleted (files: {n}; the app log names them)" in js
    assert "Some files were only partially overwritten before they were deleted (files: {n}; {done} of {known})" in js
    import src.api.main as main

    cli = python_function_source(Path(main.__file__).read_text(encoding="utf-8"), "_panic_cli")
    assert 'report.get("partially_overwritten")' in cli and 'report.get("not_overwritten")' in cli


# ---- the uninstall watcher, run as the detached script it is
_FULL_DISK = r"""
import os
if hasattr(os, "SEEK_DATA"):
    del os.SEEK_DATA
class _St:
    f_bavail = 1; f_frsize = 1
os.fstatvfs = lambda fd: _St()
"""


def _watch(tmp_path: Path, plan: dict, prelude: str = "") -> str:
    from src.safety.uninstall import _WATCHER_SRC

    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    home = tmp_path / "home" / "jane.doe"
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    subprocess.run([sys.executable, "-c", prelude + _WATCHER_SRC, str(dead.pid), json.dumps(plan)], timeout=120, check=True,
                   env=env)
    return (tmp_path / "audit.log").read_text(encoding="utf-8")


def test_the_watcher_says_partially_overwritten_on_a_nearly_full_disk(tmp_path):
    data = tmp_path / "home" / "jane.doe" / "oo-data"
    data.mkdir(parents=True)
    _sparse(data / "dump.bin")
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    text = _watch(tmp_path, {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log")}, _FULL_DISK)
    assert "partially overwritten <data>/.../dump.bin (" in text and "stopped: disk" in text, text
    assert "salt pages destroyed" not in text and "THE ERASE MAY BE INCOMPLETE" in text, text
    assert not (data / "dump.bin").exists()
    for leak in (str(tmp_path), "jane.doe"):
        assert leak not in text, (leak, text)


_MEASURE = r"""
import os
_rm = os.remove
def _remove(p, *a, **k):
    if os.path.basename(p) == "dump.bin":
        with open(os.environ["OO_T_OUT"], "w") as f: f.write(str(os.stat(p).st_blocks))
    return _rm(p, *a, **k)
os.remove = _remove
"""


@pytest.mark.skipif(not hasattr(os, "SEEK_DATA"), reason="no SEEK_DATA on this platform")
def test_the_watcher_never_fills_a_hole(tmp_path, monkeypatch):
    data = tmp_path / "oo-data"
    data.mkdir()
    _sparse(data / "dump.bin")
    before = os.stat(data / "dump.bin").st_blocks
    out = tmp_path / "blocks.txt"
    monkeypatch.setenv("OO_T_OUT", str(out))
    text = _watch(tmp_path, {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log")}, _MEASURE)
    assert "partially overwritten" not in text and "salt pages destroyed" in text, text
    assert int(out.read_text()) <= before + 64, (before, out.read_text())  # measured after its rewrite, before its delete


# ---- Revision 3: a file the erase could not overwrite at all makes the result "may be incomplete", counted once
def _refuse_open(names: set[str]):
    real = os.open

    def call(path, *a, **k):
        if os.path.basename(os.fspath(path)) in names:
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real(path, *a, **k)

    return call


def test_a_key_file_it_could_not_overwrite_makes_the_panic_result_unclean(tmp_path, monkeypatch):
    from tests.os_scope import scope_os

    data = tmp_path / "OOS data"
    (data / "keys").mkdir(parents=True)
    (data / "keys" / "custody_ed25519.pem").write_bytes(b"PRIVATE KEY")
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    scope_os(monkeypatch, crypto_erase, open=_refuse_open({"custody_ed25519.pem"}))  # as a read-only key file answers
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["keys_destroyed"] == [] and report["not_overwritten"] == 1, report
    assert crypto_erase._FAILED_SENTENCE in report["limit"] and "unrecoverable regardless" not in report["limit"], report
    assert report["unlisted_folders"] == 0 and report["partially_overwritten"] == 0, report


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="needs file permissions that bind (POSIX, not root)")
def test_a_real_read_only_key_file(tmp_path):
    data = tmp_path / "OOS data"
    (data / "keys").mkdir(parents=True)
    key = data / "keys" / "custody_ed25519.pem"
    key.write_bytes(b"PRIVATE KEY")
    key.chmod(0o444)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["not_overwritten"] >= 1 and "may be incomplete" in report["limit"], report


def test_a_file_in_a_folder_it_could_not_check_is_not_counted_twice(tmp_path, monkeypatch):
    from tests.os_scope import scope_os

    data = tmp_path / "OOS data"
    locked = data / "bulletin"
    locked.mkdir(parents=True)
    (locked / "x.db").write_bytes(b"S" * 8192)

    def refuse(fn):
        def call(path, *a, **k):
            if Path(os.fspath(path)).parent == locked:
                raise PermissionError(13, "Permission denied", os.fspath(path))
            return fn(path, *a, **k)
        return call

    scope_os(monkeypatch, crypto_erase, lstat=refuse(os.lstat), stat=refuse(os.stat), open=refuse(os.open))
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["unlisted_folders"] == 1 and report["not_overwritten"] == 0, report


def test_a_clean_erase_has_nothing_not_overwritten(tmp_path):
    data = tmp_path / "OOS data"
    data.mkdir()
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    report = crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)
    assert report["not_overwritten"] == 0 and report["partially_overwritten"] == 0, report
    assert crypto_erase._FAILED_SENTENCE not in report["limit"] and crypto_erase._PARTIAL_SENTENCE not in report["limit"], report


# ---- row 371: the first-page fallback never waits on a FIFO swapped in at the store's name after the pin
@pytest.mark.skipif(not hasattr(os, "mkfifo") or not hasattr(os, "O_NONBLOCK"), reason="needs a FIFO and O_NONBLOCK")
def test_the_first_page_fallback_never_waits_on_a_fifo(tmp_path, monkeypatch):
    import threading

    db = tmp_path / "open_omniscience.db"
    db.write_bytes(b"SQLite format 3\x00" + b"P" * 8176)
    pin = crypto_erase._pin_file(db)
    assert isinstance(pin, tuple)
    db.unlink()
    os.mkfifo(db)  # swapped in after the pin: no writer will ever open it, so a blocking open would never return
    monkeypatch.setattr(crypto_erase, "_pin_file", lambda p: pin)
    out: dict = {}
    worker = threading.Thread(target=lambda: out.update(rec=crypto_erase._first_page_fallback(db, pin)), daemon=True)
    worker.start()
    worker.join(20)
    if worker.is_alive():  # free the blocked open before failing, so the test run is not left hanging
        fd = os.open(db, os.O_WRONLY | os.O_NONBLOCK)
        os.close(fd)
        worker.join(5)
        pytest.fail("the fallback blocked on a FIFO at the store's name")
    rec = out["rec"]
    assert rec["header"] is None and rec["state"] != "first_page", rec


# ---- security read B: the first page before any reserve check; held bodies stay capped; Windows free space
def test_on_a_full_disk_a_capped_rewrite_still_writes_the_first_page(tmp_path, monkeypatch):
    blob = tmp_path / "anchors.db"
    body = b"E" * (2 * MiB)
    blob.write_bytes(body)
    monkeypatch.setattr(crypto_erase, "_fd_free_bytes", lambda fd: 0)
    monkeypatch.setattr(crypto_erase.shutil, "disk_usage", lambda p: (_ for _ in ()).throw(OSError(5, "no")))
    fd = _held(blob)
    try:
        assert crypto_erase._overwrite(blob, keyed=False) is False  # stopped: partially overwritten, never True
        after = os.pread(fd, 2 * MiB, 0)
    finally:
        os.close(fd)
    assert after[:4096] != body[:4096] and after[4096:] == body[4096:]


def test_a_held_segment_body_stays_held_to_the_reserve_in_the_closing_pass(tmp_path, monkeypatch):
    blob = tmp_path / "seg-1.db"
    body = b"B" * (2 * MiB)
    blob.write_bytes(body)
    monkeypatch.setattr(crypto_erase, "_fd_free_bytes", lambda fd: 0)
    monkeypatch.setattr(crypto_erase.shutil, "disk_usage", lambda p: (_ for _ in ()).throw(OSError(5, "no")))
    fd = os.open(blob, os.O_RDWR)
    generation = crypto_erase.new_hold_generation()
    with crypto_erase._HELD_LOCK:
        crypto_erase._HELD[generation] = [(fd, "whole", 4 * MiB)]
        crypto_erase._WHOLE_HEADS[generation] = {fd}
    probe = os.open(blob, os.O_RDONLY)
    try:
        crypto_erase.rescrub_held(close=True, generation=generation, settle=False)
        after = os.pread(probe, 2 * MiB, 0)
    finally:
        os.close(probe)
    assert after[:4096] != body[:4096] and after[4096:] == body[4096:]  # page 1 only: the body kept the reserve


def test_free_space_falls_back_to_the_folder_where_fstatvfs_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(crypto_erase, "_fd_free_bytes", lambda fd: None)
    fd = os.open(tmp_path, os.O_RDONLY)
    try:
        assert crypto_erase._free_space(fd, str(tmp_path)) == crypto_erase.shutil.disk_usage(tmp_path).free
        assert crypto_erase._free_space(fd, None) is None
    finally:
        os.close(fd)


def test_shared_scope_key_files_are_never_held_to_the_reserve():
    src = Path(crypto_erase.__file__).read_text(encoding="utf-8")
    assert "_destroy_app_keys_in_foreign(keys_dir, _track_key," in src
    assert "_hf_token_pass(base, walk_fd, shared=app_only, track=_track_key)" in src


_HEAD_ON_REMOVE = r"""
import os
_rm2 = os.remove
def _remove2(p, *a, **k):
    if os.path.basename(p) == "seg-1.db":
        with open(p, "rb") as f: head = f.read(16)
        with open(os.environ["OO_T_HEAD"], "wb") as f: f.write(head)
    return _rm2(p, *a, **k)
os.remove = _remove2
"""


def test_the_watcher_writes_a_segment_s_first_page_on_a_full_disk(tmp_path, monkeypatch):
    """Security reads A and B: a corpus segment (an encrypted database the watcher rewrites whole) loses its salt page first, even
    when the disk is too full for the rest; the rest is said as partially overwritten."""
    data = tmp_path / "home" / "jane.doe" / "oo-data"
    (data / "corpus").mkdir(parents=True)
    salt = b"SALT-0123456789A"
    (data / "corpus" / "seg-1.db").write_bytes(salt + b"C" * (2 * MiB))
    out = tmp_path / "head.bin"
    monkeypatch.setenv("OO_T_HEAD", str(out))
    text = _watch(tmp_path, {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log")}, _FULL_DISK + _HEAD_ON_REMOVE)
    assert out.read_bytes() != salt, text
    assert "partially overwritten <data>/.../seg-1.db (4096 of" in text and "salt pages destroyed" not in text, text


def test_a_late_held_rewrite_that_stops_short_reaches_the_report(tmp_path, monkeypatch):
    """Security read A / Opus read (row 332): the late pass's whole rewrite of a kept descriptor that stops at the reserve counts
    in the report as partially overwritten, and the clean guarantee is no longer said, as the watcher says it (held_short)."""
    blob = tmp_path / "seg-1.db"
    blob.write_bytes(b"B" * (2 * MiB))
    monkeypatch.setattr(crypto_erase, "_fd_free_bytes", lambda fd: 0)
    monkeypatch.setattr(crypto_erase.shutil, "disk_usage", lambda p: (_ for _ in ()).throw(OSError(5, "no")))
    fd = os.open(blob, os.O_RDWR)
    generation = crypto_erase.new_hold_generation()
    with crypto_erase._HELD_LOCK:
        crypto_erase._HELD[generation] = [(fd, "whole", 4 * MiB)]
        crypto_erase._WHOLE_HEADS[generation] = {fd}
    report = {"limit": crypto_erase._LIMIT_NOTE, "partially_overwritten": 0, "partial_bytes_done": 0,
              "partial_bytes_known": 0, "not_overwritten": 0}
    try:
        crypto_erase.finish_holder_check(report, generation)
        crypto_erase.finish_holder_check(report, generation)  # each file said once
    finally:
        crypto_erase.rescrub_held(close=True, generation=generation, settle=False)
    assert report["partially_overwritten"] == 1, report
    assert report["partial_bytes_done"] == 4096 and report["partial_bytes_known"] == 2 * MiB, report
    assert crypto_erase._PARTIAL_SENTENCE in report["limit"] and crypto_erase._LIMIT_NOTE not in report["limit"], report
    assert generation not in crypto_erase._HELD_SHORT and generation not in crypto_erase._HELD_SHORT_SAID


def test_a_later_full_rewrite_clears_an_earlier_partial(tmp_path):
    """Opus read (row 332): a file one pass rewrote only in part and a later pass rewrote in full is not said as partial."""
    blob = tmp_path / "x-wal"
    blob.write_bytes(b"W" * 8192)
    token = crypto_erase._PARTIALS.set([])
    try:
        st = os.stat(blob)
        crypto_erase._note_partial(blob, 4096, 8192, "write_failed", (st.st_dev, st.st_ino))
        crypto_erase._note_partial(blob, 4096, 8192, "write_failed", (st.st_dev, st.st_ino + 1))  # another file once at the name
        assert crypto_erase._overwrite(blob, keyed=False, capped=False) is True
        assert [e[3] for e in crypto_erase._PARTIALS.get()] == [(st.st_dev, st.st_ino + 1)]
    finally:
        crypto_erase._PARTIALS.reset(token)



def test_the_watcher_writes_a_copy_s_log_whole_on_a_full_disk(tmp_path):
    """Delta read B (row 332): a database copy's log in a subfolder can hold the copy's salt page; the watcher writes it whole on a
    full disk, as the panic erase's step 5b does (R797 (a) parity)."""
    data = tmp_path / "home" / "jane.doe" / "oo-data"
    (data / "backups").mkdir(parents=True)
    (data / "backups" / "x.db-wal").write_bytes(b"L" * (2 * MiB))
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    text = _watch(tmp_path, {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log")}, _FULL_DISK)
    assert "partially overwritten <data>/.../x.db-wal" not in text, text
    assert not (data / "backups" / "x.db-wal").exists()


def test_the_watcher_writes_a_sign_in_token_file_whole_on_a_full_disk(tmp_path):
    """Final-head security read B (row 332): a Hugging Face sign-in token file is never held to the reserve in the watcher, as in
    the panic erase (_track_key)."""
    from src.safety import uninstall

    data = tmp_path / "home" / "jane.doe" / "oo-data"
    hf = data / "models" / "huggingface"
    hf.mkdir(parents=True)
    name = uninstall._hf_token_files()[0]
    (hf / name).write_bytes(b"hf_TOKEN" * 4096)
    (data / "open_omniscience.db").write_bytes(b"S" * 8192)
    plan = {"wipe_data_dir": str(data), "audit_log": str(tmp_path / "audit.log"),
            "hf_token_files": list(uninstall._hf_token_files()), "shaped_spec": uninstall._shaped_spec({"broad": False})}
    text = _watch(tmp_path, plan, _FULL_DISK)
    assert not (hf / name).exists(), text
    assert "partially overwritten" not in text, text


def test_a_plaintext_store_s_log_is_written_whole_in_the_late_rewrite_on_a_full_disk(tmp_path, monkeypatch):
    """Final-head security read (row 332): the late rewrite of a plaintext store writes its log whole on a full disk (R797 (a));
    its body stays held to the reserve."""
    monkeypatch.setattr(crypto_erase, "_data_regions", lambda fd, limit: None)
    monkeypatch.setattr(crypto_erase, "_fd_free_bytes", lambda fd: 0)
    main, wal = tmp_path / "s.db", tmp_path / "s.db-wal"
    main.write_bytes(b"M" * (2 * MiB))
    wal.write_bytes(b"W" * (2 * MiB))
    fds = [os.open(main, os.O_RDWR), os.open(wal, os.O_RDWR)]
    held = []
    for fd, kind in zip(fds, ("head", "whole"), strict=True):
        st = os.fstat(fd)
        held.append([fd, kind, (st.st_dev, st.st_ino), 4096, False])
    rec = {"state": None, "reason": None, "_held": held}
    try:
        crypto_erase._rewrite_plain(rec, may_write=True)
        body, log = os.pread(fds[0], 2 * MiB, 0), os.pread(fds[1], 2 * MiB, 0)
    finally:
        for fd in fds:
            os.close(fd)
    assert b"W" * 4096 not in log  # the log, whole
    assert body[4096:] == b"M" * (2 * MiB - 4096)  # the body kept the reserve (its first page only)
    assert rec["state"] == "partially_overwritten", rec


def test_step_6_writes_a_log_whole():
    src = Path(crypto_erase.__file__).read_text(encoding="utf-8")
    assert 'log = p.name.endswith(("-wal", "-journal"))' in src and "_track(p, keyed=False, capped=not log)" in src
