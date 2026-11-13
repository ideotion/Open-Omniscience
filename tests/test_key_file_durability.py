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
    flushed: list[str] = []
    real = keyfile._flush_folder
    monkeypatch.setattr(keyfile, "_flush_folder", lambda folder, what: (flushed.append(Path(folder).name), real(folder, what)))

    assert keyfile.replace_in_place(key, lambda: b"SEALED", lambda b: None, None, "test key") is True

    assert not alias.exists()
    assert flushed == ["keys", keyfile.PENDING]


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
    held_at_key_shred: list[bool] = []
    real_shred = crypto_erase._shred

    def shred(path: Path, **kw):
        if path.parent == keys:
            # another thread cannot take the lock while the erase holds it
            got: list[bool] = []
            t = threading.Thread(target=lambda: got.append(keyfile.KEY_FILES_LOCK.acquire(timeout=0.05)))
            t.start()
            t.join()
            if got and got[0]:
                keyfile.KEY_FILES_LOCK.release()
            held_at_key_shred.append(not got[0])
        return real_shred(path, **kw)

    monkeypatch.setattr(crypto_erase, "_shred", shred)
    crypto_erase.quick_crypto_erase(confirm=True, data_dir=tmp_path)

    assert held_at_key_shred and all(held_at_key_shred), held_at_key_shred
    # released at the end: a later key-file change is not blocked for good
    assert keyfile.KEY_FILES_LOCK.acquire(timeout=1)
    keyfile.KEY_FILES_LOCK.release()
