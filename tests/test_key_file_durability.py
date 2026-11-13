"""The key files' names survive a power cut, and an erase cannot be undone by a wrap in flight (OPEN_QUEUE item 41(c)).

Two windows of ``src/custody/keyfile.py``, each pinned here by a test that fails on the code before the fix:

* no folder flush after ``os.replace`` / ``os.link`` / the alias removal: the file's bytes were flushed, but the NAME change is a change to
  the folder, so a power cut right after a plaintext key was wrapped in place could bring the plaintext file back, on exactly the switched-off
  machine the at-rest encryption is for;
* the check that the key file is still the one that was read, and the ``os.replace`` that acts on it, were two steps an erase could fall
  between: the erase destroyed the key, then the replace put the same key (wrapped) back under its name.
"""

from __future__ import annotations

import os
import stat
import threading
import time
from pathlib import Path

import pytest

from src.custody import keyfile
from src.safety import file_lock
from tests.os_scope import scope_os


def _folder_flushes(monkeypatch: pytest.MonkeyPatch, watch: Path) -> list[bytes | None]:
    """Record, for every ``fsync`` of a FOLDER, what ``watch`` holds at that moment (``None``: absent). Scoped to ``file_lock``'s ``os``."""
    seen: list[bytes | None] = []
    real = os.fsync

    def spy(fd: int) -> None:
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            seen.append(watch.read_bytes() if watch.exists() else None)
        real(fd)

    scope_os(monkeypatch, file_lock, fsync=spy)
    return seen


@pytest.mark.skipif(os.name == "nt", reason="a folder is not flushed on Windows (stated, named once)")
def test_replace_in_place_flushes_the_keys_folder_after_the_new_name_is_in_place(tmp_path, monkeypatch):
    key = tmp_path / "keys" / "k.pem"
    key.parent.mkdir()
    key.write_bytes(b"PLAINTEXT")
    flushes = _folder_flushes(monkeypatch, key)

    assert keyfile.replace_in_place(key, lambda: b"SEALED", lambda b: None, None, "test key") is True

    assert key.read_bytes() == b"SEALED"
    # at least one folder flush saw the NEW bytes under the name: the rename was flushed after it happened
    assert b"SEALED" in flushes, flushes


@pytest.mark.skipif(os.name == "nt", reason="hard links and folder flushes are POSIX here")
def test_replace_in_place_flushes_the_pending_folder_when_it_removed_a_plaintext_alias(tmp_path, monkeypatch):
    keys = tmp_path / "keys"
    (keys / keyfile.PENDING).mkdir(parents=True)
    key = keys / "k.pem"
    key.write_bytes(b"PLAINTEXT")
    alias = keys / keyfile.PENDING / "k.pem.1.2.abc.new"
    os.link(key, alias)  # a creation that died between its link and the removal of its private name
    seen: list[tuple[str, bool]] = []
    real = os.fsync

    def spy(fd: int) -> None:
        st = os.fstat(fd)
        if stat.S_ISDIR(st.st_mode):
            pending = keys / keyfile.PENDING
            seen.append(("pending" if pending.exists() and st.st_ino == pending.stat().st_ino else "other", alias.exists()))
        real(fd)

    scope_os(monkeypatch, file_lock, fsync=spy)

    assert keyfile.replace_in_place(key, lambda: b"SEALED", lambda b: None, None, "test key") is True

    assert not alias.exists()
    # the alias's folder was flushed AFTER the alias was gone: a power cut cannot bring the plaintext name back
    assert ("pending", False) in seen, seen


@pytest.mark.skipif(os.name == "nt", reason="a folder is not flushed on Windows (stated, named once)")
def test_create_new_flushes_the_keys_folder_after_the_link(tmp_path, monkeypatch):
    key = tmp_path / "keys" / "k.pem"
    key.parent.mkdir()
    flushes = _folder_flushes(monkeypatch, key)

    keyfile.create_new(key, b"NEWKEY")

    assert key.read_bytes() == b"NEWKEY"
    assert b"NEWKEY" in flushes, flushes


def test_a_folder_flush_failure_never_turns_a_done_replace_into_a_refusal(tmp_path, monkeypatch):
    key = tmp_path / "keys" / "k.pem"
    key.parent.mkdir()
    key.write_bytes(b"PLAINTEXT")

    def broken(folder: Path) -> None:
        raise OSError(5, "EIO")

    monkeypatch.setattr(file_lock, "flush_folder", broken)

    # the new bytes ARE in place: the caller must not be told the wrap failed, or it would try again over its own result
    assert keyfile.replace_in_place(key, lambda: b"SEALED", lambda b: None, None, "test key") is True
    assert key.read_bytes() == b"SEALED"


def test_an_erase_between_the_check_and_the_replace_is_never_undone(tmp_path):
    """The erase takes the key-file lock; a wrap that checked its copy before the erase began must not land after it."""
    key = tmp_path / "keys" / "k.pem"
    key.parent.mkdir()
    key.write_bytes(b"PLAINTEXT")
    holding = threading.Event()
    erased = threading.Event()

    def erase() -> None:
        with keyfile.KEY_FILES_LOCK:
            holding.set()
            time.sleep(0.2)  # the wrap reaches its replace while the erase holds the lock
            key.unlink()
        erased.set()

    def check(copy: bytes) -> None:
        # the wrap's own check passed; the erase starts now, before the replace
        threading.Thread(target=erase, name="test-erase").start()
        assert holding.wait(5)

    replaced = keyfile.replace_in_place(key, lambda: b"SEALED", check, None, "test key")

    assert erased.wait(5)
    assert replaced is False
    assert not key.exists(), "the erased key was put back by the wrap that was in flight"
    leftovers = list((key.parent / keyfile.PENDING).glob("*")) if (key.parent / keyfile.PENDING).exists() else []
    assert leftovers == [], leftovers


def test_the_quick_erase_holds_the_key_file_lock_while_it_destroys_the_keys(tmp_path, monkeypatch):
    from src.safety import crypto_erase

    keys = tmp_path / "keys"
    keys.mkdir()
    (keys / "custody_ed25519.pem").write_bytes(b"x" * 64)
    (keys / "evidence_ed25519.pem").write_bytes(b"y" * 64)
    held_at_key_shred: list[bool] = []
    real_shred = crypto_erase._shred

    def shred(path: Path, **kw):
        if keys in path.parents:
            # another thread cannot take the lock while the erase holds it
            got: list[bool] = []

            def probe() -> None:
                ok = keyfile.KEY_FILES_LOCK.acquire(timeout=0.05)
                got.append(ok)
                if ok:  # released by the thread that took it: an RLock belongs to its owner
                    keyfile.KEY_FILES_LOCK.release()

            t = threading.Thread(target=probe)
            t.start()
            t.join()
            held_at_key_shred.append(not got[0])
        return real_shred(path, **kw)

    monkeypatch.setattr(crypto_erase, "_shred", shred)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)

    # both the custody key (step 2) and the evidence key (the keys-folder sweep) went under the lock
    assert len(held_at_key_shred) >= 2 and all(held_at_key_shred), held_at_key_shred
    assert not keys.exists()
    # released at the end: a later key-file change is not blocked for good
    assert keyfile.KEY_FILES_LOCK.acquire(timeout=1)
    keyfile.KEY_FILES_LOCK.release()


def test_a_wrap_whose_key_derivation_overlapped_an_erase_writes_nothing_at_all(tmp_path):
    """The private copy is written under the lock too: an erase that ran while ``make`` derived the key leaves no wrapped
    copy of the destroyed key in ``keys/.pending`` (security read A, S1 of the first head)."""
    keys = tmp_path / "keys"
    keys.mkdir()
    key = keys / "k.pem"
    key.write_bytes(b"PLAINTEXT")

    def make() -> bytes:
        # the erase runs to completion while the slow derivation does
        with keyfile.KEY_FILES_LOCK:
            key.unlink()
        return b"SEALED"

    assert keyfile.replace_in_place(key, make, lambda b: None, None, "test key") is False
    assert not key.exists()
    pending = keys / keyfile.PENDING
    assert not pending.exists() or list(pending.iterdir()) == []


@pytest.mark.skipif(os.name == "nt", reason="a file open here cannot be replaced on Windows; the overwrite is skipped there")
def test_the_bytes_a_wrap_in_place_frees_are_overwritten(tmp_path):
    key = tmp_path / "keys" / "k.pem"
    key.parent.mkdir()
    key.write_bytes(b"PLAINTEXT-KEY-BYTES")
    fd = os.open(key, os.O_RDONLY)  # a reader of the OLD file, as the blocks would be read back
    try:
        assert keyfile.replace_in_place(key, lambda: b"SEALED", lambda b: None, None, "test key") is True
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 64) == b"\0" * len(b"PLAINTEXT-KEY-BYTES")
    finally:
        os.close(fd)
    assert key.read_bytes() == b"SEALED"


@pytest.mark.skipif(os.name == "nt", reason="the overwrite is skipped on Windows")
def test_the_freed_bytes_are_left_alone_when_the_rename_is_not_known_to_be_on_disk(tmp_path, monkeypatch):
    """Zeros under a name a power cut could still hand back would lose the key altogether: no flush, no overwrite (delta read, should-fix 1)."""
    key = tmp_path / "keys" / "k.pem"
    key.parent.mkdir()
    key.write_bytes(b"OLD-FORM-BYTES")
    monkeypatch.setattr(file_lock, "flush_folder", lambda folder: False)  # a filesystem that cannot flush a folder
    fd = os.open(key, os.O_RDONLY)
    try:
        assert keyfile.replace_in_place(key, lambda: b"SEALED", lambda b: None, None, "test key") is True
        os.lseek(fd, 0, os.SEEK_SET)
        assert os.read(fd, 64) == b"OLD-FORM-BYTES"
    finally:
        os.close(fd)


def test_a_reader_never_returns_the_bytes_of_a_file_no_name_holds(tmp_path, monkeypatch):
    key = tmp_path / "k.pem"
    key.write_bytes(b"CURRENT")
    real_fstat = os.fstat
    calls = {"n": 0}

    def fstat(fd):
        st = real_fstat(fd)
        calls["n"] += 1
        if calls["n"] == 1:  # the first open met a file that was replaced while it was read
            return os.stat_result((st.st_mode, st.st_ino, st.st_dev, 0, *tuple(st)[4:10]))
        return st

    scope_os(monkeypatch, keyfile, fstat=fstat)
    raw, st = keyfile.read_once(key)
    assert raw == b"CURRENT" and calls["n"] == 2 and st.st_nlink != 0
