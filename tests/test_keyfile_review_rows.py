"""The hardening lane's review of #1932, rows 6 to 8 (src/custody/keyfile.py).

Row 6: a wrap's last step removed ``keys/.pending`` OUTSIDE the key-file lock, so it could remove the folder between another wrap's
rename out of it and that wrap's flush of it; the flush then failed and the replaced plaintext key's bytes were never overwritten.
Row 7: the check of a wrapped copy (a second key derivation) ran INSIDE the lock, so an erase waited one derivation per wrap in flight.
Row 8: a creation removed its private name (a second name for the key's bytes) without flushing that removal, so a power cut could
bring a plaintext alias back until the next wrap.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from src.custody import keyfile


def _held() -> bool:
    return keyfile.KEY_FILES_LOCK._is_owned()  # type: ignore[attr-defined]


def _key(tmp_path: Path) -> Path:
    key = tmp_path / "keys" / "k.pem"
    key.parent.mkdir()
    key.write_bytes(b"PLAINTEXT")
    return key


def test_a_wrap_removes_the_pending_folder_only_under_the_lock(tmp_path, monkeypatch):
    key = _key(tmp_path)
    seen: list[bool] = []
    real = keyfile.drop_pending
    monkeypatch.setattr(keyfile, "drop_pending", lambda p: (seen.append(_held()), real(p)))
    assert keyfile.replace_in_place(key, lambda: b"SEALED", lambda b: None, None, "test key") is True
    assert seen and all(seen), seen


def test_the_check_of_a_wrapped_copy_runs_outside_the_lock(tmp_path):
    key = _key(tmp_path)
    seen: list[bool] = []
    assert keyfile.replace_in_place(key, lambda: b"SEALED", lambda b: seen.append(_held()), None, "test key") is True
    assert seen == [False], "an erase would wait out a key derivation"


def test_a_copy_that_does_not_read_back_as_written_is_never_used(tmp_path, monkeypatch):
    key = _key(tmp_path)
    real = keyfile.write_private

    def corrupting(path, kind, data):
        tmp = real(path, kind, data)
        tmp.write_bytes(b"TORN")
        return tmp

    monkeypatch.setattr(keyfile, "write_private", corrupting)
    assert keyfile.replace_in_place(key, lambda: b"SEALED", lambda b: None, None, "test key") is False
    assert key.read_bytes() == b"PLAINTEXT"


def test_a_failed_check_leaves_the_file_and_writes_no_private_copy(tmp_path):
    key = _key(tmp_path)

    def bad(_b: bytes) -> None:
        raise ValueError("does not open")

    assert keyfile.replace_in_place(key, lambda: b"SEALED", bad, None, "test key") is False
    assert key.read_bytes() == b"PLAINTEXT"
    assert not (key.parent / keyfile.PENDING).exists()


@pytest.mark.skipif(os.name == "nt", reason="hard links and folder flushes are POSIX here")
def test_a_creation_flushes_the_removal_of_its_private_name(tmp_path, monkeypatch):
    key = tmp_path / "keys" / "k.pem"
    key.parent.mkdir()
    flushed: list[tuple[str, list[str]]] = []
    real = keyfile.flush_key_folder

    def spy(folder: Path, what: str) -> bool:
        flushed.append((folder.name, sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []))
        return real(folder, what)

    monkeypatch.setattr(keyfile, "flush_key_folder", spy)
    keyfile.create_new(key, b"NEWKEY")
    assert key.read_bytes() == b"NEWKEY"
    pending = [entries for name, entries in flushed if name == keyfile.PENDING]
    assert pending and pending[-1] == [], f"the private name's removal was never flushed: {flushed}"
