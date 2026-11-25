"""Row 438 (R839, amended by R840): files with another name elsewhere on the disk (a hard link) in the erase.

A file is overwritten whatever its other name only when it is positively the app's own: its key material, a store's page 1, the
columnar cache's salt, a segment or a database copy a record names by identity, a plaintext store's log whose own header ties it
to the pinned store. Any other file with a second name is never written: its name is removed, it is counted, and the result says
its contents may remain under that other name. A possible copy of the corpus that is not positively the app's is left whole and
said so. The link count is read through the handle about to be written. Counts only, never a file name (R806).
"""

from __future__ import annotations

import json
import os
import sqlite3
import struct
import sys
from pathlib import Path

import pytest

from src.database import at_rest_state
from src.database.connect import connect, have_driver
from src.safety import crypto_erase

posix_only = pytest.mark.skipif(os.name != "posix", reason="hard links and folder handles (POSIX)")
sqlcipher_only = pytest.mark.skipif(not have_driver(), reason="sqlcipher3 not installed")
_PW = "row-438-r839-test-passphrase"


def _erase(data: Path) -> dict:
    return crypto_erase.quick_crypto_erase(confirm=True, data_dir=data)


def _own(tmp_path: Path) -> Path:
    data = tmp_path / "OOS data"
    data.mkdir()
    return data


def _outside(tmp_path: Path, body: bytes = b"the operator's own file " * 300) -> Path:
    p = tmp_path / "zq-operator-file.bin"
    p.write_bytes(body)
    return p


def _encrypted(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = connect(path, key=_PW, create_encrypted=True)
    con.execute("CREATE TABLE t(x)")
    con.executemany("INSERT INTO t VALUES (?)", [("secret-row" * 40,)] * 100)
    con.commit()
    con.close()


@pytest.fixture(params=["handle", "path"])
def walk(request, monkeypatch):
    """Both walks: by the data folder's handle (POSIX) and by path (Windows, and the fallback)."""
    if request.param == "handle" and (sys.platform == "win32" or not hasattr(os, "O_DIRECTORY")):
        pytest.skip("POSIX folder handles")
    if request.param == "path":
        monkeypatch.setattr(crypto_erase, "_walk_fd", lambda hold: None)
    return request.param


# -- the overwrite itself ----------------------------------------------------------------------------------------------------


@posix_only
def test_a_file_with_another_name_is_written_only_when_keyed(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"A" * 8192)
    os.link(f, tmp_path / "b.bin")
    notes: dict[str, set] = {"keyed": set(), "left": set(), "refused": set()}
    token = crypto_erase._LINK_NOTES.set(notes)
    try:
        assert crypto_erase._overwrite(f, keyed=False) is None, "neither done nor failed"
        assert (tmp_path / "b.bin").read_bytes() == b"A" * 8192, "never written through this name"
        assert crypto_erase._overwrite(f, keyed=True) is True
        assert (tmp_path / "b.bin").read_bytes() != b"A" * 8192
    finally:
        crypto_erase._LINK_NOTES.reset(token)
    ident = (f.stat().st_dev, f.stat().st_ino)
    assert notes["left"] == {ident} and notes["keyed"] == {ident}
    assert crypto_erase._link_counts(notes) == {"written": 1, "left": 0, "refused": 0, "keys": 0}, "a file written once is never said as left"


@posix_only
def test_the_link_count_is_read_on_the_handle_at_the_decision(tmp_path, monkeypatch):
    """A second name added after a look by path, before the open, is still seen: the count comes from fstat on the handle."""
    f = tmp_path / "a.bin"
    f.write_bytes(b"A" * 4096)
    real_open = os.open

    def opened(path, flags, *a, **k):
        fd = real_open(path, flags, *a, **k)
        if str(path).endswith("a.bin") and not (tmp_path / "late.bin").exists():
            os.link(f, tmp_path / "late.bin")
        return fd

    from tests.os_scope import scope_os

    scope_os(monkeypatch, crypto_erase, open=opened)
    assert crypto_erase._overwrite(f, keyed=False) is None
    assert (tmp_path / "late.bin").read_bytes() == b"A" * 4096


@posix_only
def test_a_one_name_file_is_written_as_before(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"A" * 4096)
    assert crypto_erase._overwrite(f, keyed=False) is True and f.read_bytes() != b"A" * 4096


# -- the erase: any other file -----------------------------------------------------------------------------------------------


@posix_only
def test_an_other_file_with_a_second_name_is_never_written_and_said(tmp_path, walk):
    data = _own(tmp_path)
    (data / "annotations").mkdir()
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.link(outside, data / "annotations" / "zq-notes.json")
    report = _erase(data)
    assert outside.read_bytes() == before, "never written in 5b or step 6"
    assert not data.exists(), "its name in the data folder is removed"
    assert report["linked_files"] == {"written": 0, "left": 1, "refused": 0, "keys": 0}
    assert crypto_erase._LINKED_LEFT_SENTENCE.format(n=1) in report["limit"]
    assert "zq-" not in json.dumps(report, default=str), "no file name (R806)"
    assert not any("annotations" in f for f in report["overwrite_failures"]), "not a failed overwrite: its own line"


@posix_only
def test_the_anchors_database_with_a_second_name_is_not_written(tmp_path):
    data = _own(tmp_path)
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.link(outside, data / "anchors.db")
    report = _erase(data)
    assert outside.read_bytes() == before
    assert report["linked_files"]["left"] == 1


@posix_only
def test_a_hugging_face_token_with_a_second_name_is_not_written_and_said(tmp_path):
    data = _own(tmp_path)
    home = data / "models" / "huggingface"
    (home / "hub").mkdir(parents=True)
    outside = _outside(tmp_path, b"hf_secret")
    os.link(outside, home / "token")
    report = _erase(data)
    assert outside.read_bytes() == b"hf_secret"
    assert report["hf_token_left"] == ["models/huggingface"], "a sign-in token may remain: the revoke line"
    assert report["linked_files"]["left"] == 1


# -- the erase: the app's own, positively -----------------------------------------------------------------------------------


@posix_only
def test_a_foreign_file_hard_linked_under_a_key_name_is_never_written(tmp_path, monkeypatch):
    """R841 (2): a file under a key name with another name somewhere the app does not keep its keys cannot be shown to be this
    installation's own key: never written, its name here removed, counted and said, and the erase is not complete."""
    data = _own(tmp_path)
    (data / "keys").mkdir()
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.link(outside, data / "keys" / "custody_ed25519.pem")
    report = _erase(data)
    assert outside.read_bytes() == before, "byte-identical through its other name"
    assert not (data / "keys" / "custody_ed25519.pem").exists(), "its name here is removed"
    assert report["linked_files"]["keys"] == 1 and report["linked_files"]["written"] == 0
    assert crypto_erase._LINKED_KEYS_SENTENCE.format(n=1) in report["limit"]
    assert crypto_erase._LIMIT_NOTE not in report["limit"] and "zq-" not in json.dumps(report)


@posix_only
def test_a_foreign_file_hard_linked_under_a_key_name_in_a_shared_folder_is_never_written(tmp_path, monkeypatch):
    monkeypatch.setenv("OO_DATA_DIR", str(tmp_path / "home"))
    home = tmp_path / "home"
    (home / "keys").mkdir(parents=True)
    (home / "holiday.jpg").write_bytes(b"jpeg")
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.link(outside, home / "keys" / "custody_ed25519.pem")
    report = _erase(home)
    assert outside.read_bytes() == before
    assert report["linked_files"]["keys"] == 1


def _pending_name(key: str) -> str:
    return f"{key}.123.456.0123456789ab.new"


@posix_only
def test_an_own_key_with_a_second_name_in_its_pending_folder_is_overwritten_through_both_names(tmp_path):
    """R841 (1): the app links a private copy into place, so its own key has a second name in keys/.pending for a moment; every
    name of it is in the keys folder, so it is verified and overwritten in the key-material-first pass."""
    data = _own(tmp_path)
    (data / "keys" / ".pending").mkdir(parents=True)
    key = data / "keys" / "custody_ed25519.pem"
    key.write_bytes(b"K" * 64)
    os.link(key, data / "keys" / ".pending" / _pending_name("custody_ed25519.pem"))
    fd = os.open(key, os.O_RDONLY)  # the inode itself, whichever name the erase writes it through
    try:
        report = _erase(data)
        assert os.pread(fd, 64, 0) != b"K" * 64, "overwritten"
    finally:
        os.close(fd)
    assert not (data / "keys").exists()
    assert report["linked_files"]["written"] == 1 and report["linked_files"]["keys"] == 0
    assert crypto_erase._LINKED_KEYS_SENTENCE.format(n=1) not in report["limit"]


@posix_only
def test_the_verify_read_is_on_the_descriptor_that_is_then_written(tmp_path, monkeypatch):
    """R841 (6): the verification and the write are on one held descriptor: a name swapped for another file between them changes
    nothing about which file is written (the one verified), and the file swapped in is never written."""
    data = _own(tmp_path)
    (data / "keys" / ".pending").mkdir(parents=True)
    key = data / "keys" / "custody_ed25519.pem"
    key.write_bytes(b"K" * 64)
    os.link(key, data / "keys" / ".pending" / _pending_name("custody_ed25519.pem"))
    held = os.open(key, os.O_RDONLY)
    swap = tmp_path / "zq-swap"
    swap.write_bytes(b"S" * 64)
    swapped: list[int] = []
    real = crypto_erase._KeysHold.verify

    def verify(self, st):
        ok = real(self, st)
        if not swapped and (st.st_dev, st.st_ino) == (os.fstat(held).st_dev, os.fstat(held).st_ino):
            os.replace(swap, key)  # the name now leads to another file, after the descriptor was opened and verified
            swapped.append(os.open(key, os.O_RDONLY))
        return ok

    monkeypatch.setattr(crypto_erase._KeysHold, "verify", verify)
    try:
        _erase(data)
        assert swapped, "the verification ran"
        assert os.pread(held, 64, 0) != b"K" * 64, "the file verified is the file written"
        assert os.pread(swapped[0], 64, 0) == b"S" * 64, "the file swapped in is never written"
    finally:
        os.close(held)
        for f in swapped:
            os.close(f)


@posix_only
@sqlcipher_only
def test_a_segment_with_a_second_name_and_a_matching_record_is_overwritten(tmp_path):
    data = _own(tmp_path)
    seg = data / "corpus" / "seg-1.db"
    _encrypted(seg)
    rec = data / at_rest_state.RECORD_NAME
    doc = {"version": 1, "stores": {}, "binding_key": os.urandom(32).hex()}
    mark = at_rest_state._mark(seg)
    assert mark is not None
    entry = at_rest_state._bound_entry(doc, mark)
    entry.update(read_back_with_key=True)
    doc["stores"][at_rest_state.SEGMENT_PREFIX + "seg-1"] = entry
    rec.write_text(json.dumps(doc), encoding="utf-8")
    twin = tmp_path / "seg-twin"
    os.link(seg, twin)
    head = twin.read_bytes()[:4096]
    report = _erase(data)
    assert twin.read_bytes()[:4096] != head, "its page 1 (the salt) is gone under both names"
    assert report["linked_files"]["written"] == 1 and report["linked_files"]["refused"] == 0
    assert report["corpus_segments"]["left"] == 0


@posix_only
def test_a_segment_with_a_second_name_and_no_record_is_refused_and_said(tmp_path):
    data = _own(tmp_path)
    (data / "corpus").mkdir()
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.link(outside, data / "corpus" / "seg-1.db")
    report = _erase(data)
    assert outside.read_bytes() == before
    assert report["linked_files"]["refused"] == 1 and report["linked_files"]["written"] == 0
    assert crypto_erase._LINKED_REFUSED_SENTENCE.format(n=1) in report["limit"]


@posix_only
@sqlcipher_only
def test_a_copy_with_a_second_name_and_a_matching_record_is_overwritten(tmp_path, monkeypatch):
    import src.database.connect as connect_module

    main, snap = tmp_path / "open_omniscience.db", tmp_path / "pre-restore-20261124T101010Z.db"
    _encrypted(main)
    snap.write_bytes(main.read_bytes())
    monkeypatch.setattr(connect_module, "opened_with_key", lambda ident: True)
    (tmp_path / at_rest_state.RECORD_NAME).write_text(json.dumps({"version": 1, "stores": {}}), encoding="utf-8")
    assert at_rest_state.record_copy(snap, main, "corpus")
    twin = tmp_path.parent / f"{tmp_path.name}-copy-twin.db"
    os.link(snap, twin)
    head = twin.read_bytes()[:4096]
    try:
        report = _erase(tmp_path)
        assert twin.read_bytes()[:4096] != head
        assert report["copies_destroyed"] == {"pre-restore": 1} and not report["copies_not_overwritten"]
        assert report["linked_files"]["written"] >= 1
    finally:
        twin.unlink()


def test_a_copy_with_a_second_name_and_no_record_is_refused_and_said(tmp_path):
    main, snap = tmp_path / "open_omniscience.db", tmp_path / "open_omniscience.salvage-20261124T101010Z.db"
    for p in (main, snap):
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE t(x)")
        con.commit()
        con.close()
    other = tmp_path.parent / f"{tmp_path.name}-victim.db"
    os.link(snap, other)
    before = other.read_bytes()
    try:
        report = _erase(tmp_path)
        assert other.read_bytes() == before
        assert report["linked_files"]["refused"] == 1
        assert crypto_erase._LINKED_REFUSED_SENTENCE.format(n=1) in report["limit"]
    finally:
        other.unlink()


# -- the plaintext store's logs (R840) ---------------------------------------------------------------------------------------


def _wal_header(page_size: int) -> bytes:
    head = struct.pack(">4I", 0x377F0682, 3007000, page_size, 0) + os.urandom(8)
    s0, s1 = crypto_erase._wal_checksum(head, False)
    return head + struct.pack(">2I", s0, s1)


@posix_only
def test_a_log_is_tied_only_by_a_valid_header_with_the_store_s_page_size(tmp_path):
    f = tmp_path / "x-wal"
    f.write_bytes(_wal_header(4096) + os.urandom(4096))
    fd = os.open(f, os.O_RDONLY)
    try:
        assert crypto_erase._log_tied(fd, "-wal", 4096) is True
        assert crypto_erase._log_tied(fd, "-wal", 8192) is False, "another page size: not this store's"
        assert crypto_erase._log_tied(fd, "-wal", None) is False
    finally:
        os.close(fd)
    bad = bytearray(_wal_header(4096))
    bad[25] ^= 0xFF  # its checksum no longer matches
    f.write_bytes(bytes(bad))
    fd = os.open(f, os.O_RDONLY)
    try:
        assert crypto_erase._log_tied(fd, "-wal", 4096) is False
    finally:
        os.close(fd)
    j = tmp_path / "x-journal"
    j.write_bytes(bytes.fromhex("d9d505f920a163d7") + struct.pack(">3I", 0, 1, 0) + struct.pack(">2I", 512, 4096))
    fd = os.open(j, os.O_RDONLY)
    try:
        assert crypto_erase._log_tied(fd, "-journal", 4096) is True
        assert crypto_erase._log_tied(fd, "-wal", 4096) is False
    finally:
        os.close(fd)
    j.write_bytes(bytes(28))  # a zeroed header (journal_mode=PERSIST) ties nothing
    fd = os.open(j, os.O_RDONLY)
    try:
        assert crypto_erase._log_tied(fd, "-journal", 4096) is False
    finally:
        os.close(fd)


@posix_only
def test_a_plaintext_store_s_tied_log_with_a_second_name_is_overwritten(tmp_path):
    data = _own(tmp_path)
    main = data / crypto_erase._MAIN_DB
    con = sqlite3.connect(main)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    page = struct.unpack(">H", main.read_bytes()[16:18])[0]
    wal = main.with_name(main.name + "-wal")
    wal.write_bytes(_wal_header(page) + b"plaintext article " * 500)
    twin = tmp_path / "wal-twin"
    os.link(wal, twin)
    report = _erase(data)
    assert b"plaintext article" not in twin.read_bytes(), "the store's own log: overwritten whatever its other name"
    assert report["linked_files"]["written"] >= 1 and report["linked_files"]["refused"] == 0


@posix_only
def test_a_plaintext_store_s_untied_log_with_a_second_name_is_refused_and_said(tmp_path):
    data = _own(tmp_path)
    main = data / crypto_erase._MAIN_DB
    con = sqlite3.connect(main)
    con.execute("CREATE TABLE t(x)")
    con.commit()
    con.close()
    victim = _outside(tmp_path)
    before = victim.read_bytes()
    os.link(victim, main.with_name(main.name + "-wal"))
    report = _erase(data)
    assert victim.read_bytes() == before
    assert report["linked_files"]["refused"] == 1
    assert crypto_erase._LINKED_REFUSED_SENTENCE.format(n=1) in report["limit"]


# -- the uninstall watcher -----------------------------------------------------------------------------------------------------


def _run_watcher(tmp_path: Path, data: Path) -> str:
    import subprocess

    from src.safety import uninstall

    log = tmp_path / "uninstall-audit.log"
    plan = {"files": [], "venv": None, "app_folder": None, "wipe_data_dir": str(data), "wipe_store_dir": None, "passes": None,
            "enc_names": [], "app_only": uninstall._app_only(None), "keys_spec": uninstall._keys_spec(),
            "hf_token_files": list(uninstall._hf_token_files()), "shaped_spec": uninstall._shaped_spec({"broad": False}),
            "audit_log": str(log)}
    src = uninstall._WATCHER_SRC.replace("__PID_PROBE__", "def pid_alive(p): return False")
    subprocess.run([sys.executable, "-I", "-c", src, "999999999", json.dumps(plan)], check=True, timeout=60, cwd=tmp_path)
    return log.read_text(encoding="utf-8") if log.exists() else ""


@posix_only
def test_a_key_whose_link_count_changes_between_the_count_and_the_write_is_unverified(tmp_path, monkeypatch):
    """R841 (coordinator, 11:07Z): the names are counted against the descriptor's link count; a name made elsewhere after the
    count and before the write cannot be reconciled, so the file is never written."""
    data = _own(tmp_path)
    (data / "keys" / ".pending").mkdir(parents=True)
    key = data / "keys" / "custody_ed25519.pem"
    key.write_bytes(b"K" * 64)
    os.link(key, data / "keys" / ".pending" / _pending_name("custody_ed25519.pem"))
    late = tmp_path / "zq-late-name"
    real = crypto_erase._KeysHold.verify

    def verify(self, st):
        ok = real(self, st)
        if not late.exists():
            os.link(data / "keys" / ".pending" / _pending_name("custody_ed25519.pem"), late)
        return ok

    monkeypatch.setattr(crypto_erase._KeysHold, "verify", verify)
    report = _erase(data)
    assert late.read_bytes() == b"K" * 64, "never written once the count no longer matches"
    assert report["linked_files"]["keys"] == 1
    assert crypto_erase._LINKED_KEYS_SENTENCE.format(n=1) in report["limit"]


@posix_only
def test_the_watcher_never_writes_an_other_file_with_a_second_name(tmp_path):
    data = _own(tmp_path)
    (data / "annotations").mkdir()
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.link(outside, data / "annotations" / "zq-notes.json")
    log = _run_watcher(tmp_path, data)
    assert outside.read_bytes() == before
    assert "may remain under that other name (count: 1): THE ERASE IS NOT COMPLETE" in log
    assert "THE ERASE MAY BE INCOMPLETE" in log and "zq-" not in log


@posix_only
def test_the_watcher_overwrites_the_app_s_store_whatever_its_other_name_and_a_verified_key(tmp_path):
    data = _own(tmp_path)
    (data / "keys" / ".pending").mkdir(parents=True)
    key = data / "keys" / "custody_ed25519.pem"
    key.write_bytes(b"K" * 64)
    os.link(key, data / "keys" / ".pending" / _pending_name("custody_ed25519.pem"))
    store = data / "open_omniscience.db"
    store.write_bytes(b"S" * 8192)
    s2 = tmp_path / "store-twin"
    os.link(store, s2)
    fd = os.open(key, os.O_RDONLY)
    try:
        log = _run_watcher(tmp_path, data)
        assert os.pread(fd, 64, 0) != b"K" * 64, "the app's own key (every name in keys): overwritten"
    finally:
        os.close(fd)
    assert s2.read_bytes()[:4096] != b"S" * 4096
    assert "overwritten all the same (count: 2)" in log


@posix_only
def test_the_watcher_never_writes_a_foreign_file_under_a_key_name(tmp_path):
    data = _own(tmp_path)
    (data / "keys").mkdir()
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.link(outside, data / "keys" / "custody_ed25519.pem")
    log = _run_watcher(tmp_path, data)
    assert outside.read_bytes() == before, "byte-identical through its other name"
    assert "could not be shown to be this installation's own keys" in log and "(count: 1): THE ERASE IS NOT COMPLETE" in log
    assert "zq-" not in log


@posix_only
def test_the_watcher_says_a_segment_with_a_second_name_was_left(tmp_path):
    data = _own(tmp_path)
    (data / "corpus").mkdir()
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.link(outside, data / "corpus" / "seg-1.db")
    log = _run_watcher(tmp_path, data)
    assert outside.read_bytes() == before
    assert "copies that may hold articles and the salt of their key were left" in log and "(count: 1)" in log


@posix_only
def test_a_link_in_the_keys_folder_is_never_followed_and_is_could_not_check(tmp_path):
    """Row 380 (R810 (1)): a link in the keys folder is never written through, and the result is never clean (the folder then
    holds something the app did not write: R806's exact-name pass, which leaves it; one that appears during the walk by the
    folder's handle is said as could not check)."""
    data = _own(tmp_path)
    (data / "keys").mkdir()
    (data / "keys" / "custody_ed25519.pem").write_bytes(b"K" * 64)
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.symlink(outside, data / "keys" / "evidence_ed25519.pem")
    report = _erase(data)
    assert outside.read_bytes() == before
    assert report["folder_kept_foreign"] is True and crypto_erase._LIMIT_NOTE not in report["limit"], "never a clean result"
    assert "zq-" not in json.dumps(report)


@posix_only
def test_the_watcher_never_follows_a_link_at_a_key_name(tmp_path):
    data = _own(tmp_path)
    (data / "keys").mkdir()
    outside = _outside(tmp_path)
    before = outside.read_bytes()
    os.symlink(outside, data / "keys" / "custody_ed25519.pem")
    _run_watcher(tmp_path, data)
    assert outside.read_bytes() == before


# -- the strings ----------------------------------------------------------------------------------------------------------------


def test_the_four_sentences_ship_in_every_language():
    root = Path(__file__).resolve().parents[1] / "src" / "static" / "locales"
    js = (Path(__file__).resolve().parents[1] / "src" / "static" / "app-backup.js").read_text(encoding="utf-8")
    keys = [s.replace("app's", "app’s").replace("installation's", "installation’s") for s in (
        crypto_erase._LINKED_REFUSED_SENTENCE, crypto_erase._LINKED_LEFT_SENTENCE, crypto_erase._LINKED_WRITTEN_SENTENCE,
        crypto_erase._LINKED_KEYS_SENTENCE)]
    for k in keys:
        assert k in js, "the UI line is the report's sentence"
    for f in sorted(root.glob("*.json")):
        loc = json.loads(f.read_text(encoding="utf-8"))
        for k in keys:
            assert "{n}" in loc[k], f.name
            assert "destr" not in loc[k].lower() if f.stem == "en" else True, "never 'destroyed' (R815)"
