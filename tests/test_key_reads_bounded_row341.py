"""Row 341: a key file read is bounded, never blocks, and reads only a regular file.

A FIFO put at the evidence key's name (by anyone who can write the data folder) hung the export
review and every own-key check on an unbounded ``read_bytes``; a link to ``/dev/zero`` would read
forever. The shared key reader (``keyfile.read_once``, behind ``read_settled``) now opens without
blocking, refuses anything ``fstat`` does not call a regular file, and stops one byte past the
largest key file; the review's ``existing_public_key_hex`` uses that reader, so each of those reads
as "the own key could not be read" instead of a hang.
"""

from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

import pytest

from src.custody import keyfile as kf
from src.reporting import evidence as ev

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="FIFOs and /dev/zero are POSIX")


def _within(seconds: float, fn, *args):
    """Run ``fn`` on a thread and return (finished, result, error): a hang shows as not finished."""
    out: dict = {}

    def run():
        try:
            out["result"] = fn(*args)
        except BaseException as exc:  # noqa: BLE001 - the test inspects it
            out["error"] = exc

    t = threading.Thread(target=run, daemon=True)
    t.start()
    t.join(seconds)
    return (not t.is_alive()), out.get("result"), out.get("error")


def _unblock(path: Path) -> None:
    """Open the FIFO for writing once, so a reader stuck on it (the old code) can finish."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
    except OSError:
        return
    os.close(fd)


@posix_only
def test_a_fifo_at_the_key_name_reads_as_no_key_and_never_hangs(tmp_path):
    key = tmp_path / "evidence_ed25519.pem"
    os.mkfifo(key)
    try:
        done, result, error = _within(5, ev.existing_public_key_hex, key)
        assert done, "the review hung on a FIFO at the key's name"
        assert error is None and result is None
        done, state, error = _within(5, ev.signing_key_state, key)
        assert done and error is None and state == ("unreadable", None)
    finally:
        _unblock(key)


@posix_only
def test_the_loader_refuses_a_fifo_and_makes_no_key_over_it(tmp_path):
    key = tmp_path / "evidence_ed25519.pem"
    os.mkfifo(key)
    try:
        done, _result, error = _within(5, ev.load_or_create_signing_key, key)
        assert done, "the key loader hung on a FIFO"
        assert isinstance(error, kf.KeyFileNotReadable)
        assert not isinstance(error, FileNotFoundError)
        assert key.is_fifo(), "nothing was written over the name"
    finally:
        _unblock(key)


@posix_only
def test_a_link_to_a_device_is_refused_without_reading_it(tmp_path):
    if not Path("/dev/zero").exists():
        pytest.skip("no /dev/zero")
    key = tmp_path / "evidence_ed25519.pem"
    key.symlink_to("/dev/zero")
    done, _r, error = _within(5, kf.read_once, key)
    assert done and isinstance(error, kf.KeyFileNotReadable)
    done, result, error = _within(5, ev.existing_public_key_hex, key)
    assert done and error is None and result is None


def test_a_file_longer_than_any_key_is_refused(tmp_path):
    key = tmp_path / "evidence_ed25519.pem"
    with key.open("wb") as fh:
        fh.truncate(kf.MAX_KEY_FILE_BYTES + 1)
    with pytest.raises(kf.KeyFileNotReadable):
        kf.read_once(key)
    assert ev.existing_public_key_hex(key) is None


def test_a_file_that_grows_past_the_bound_while_read_stops_one_byte_past_it(tmp_path, monkeypatch):
    """``fstat`` said small, the file then grew: the read takes at most one byte past the bound."""
    key = tmp_path / "evidence_ed25519.pem"
    key.write_bytes(b"x")
    asked: list[int] = []
    real_read = os.read

    def endless(fd, n):
        asked.append(n)
        return b"\0" * n

    monkeypatch.setattr(kf.os, "read", endless)
    with pytest.raises(kf.KeyFileNotReadable):
        kf.read_once(key)
    assert sum(asked) == kf.MAX_KEY_FILE_BYTES + 1
    monkeypatch.setattr(kf.os, "read", real_read)


def test_the_largest_key_file_written_fits_the_bound():
    from src.custody import signing

    # a wrapped ML-DSA-65 pair (public 1952 + secret 4032 bytes) is the largest form written
    wrapped = signing._wrap(os.urandom(1952 + 4032), b"a passphrase held")
    assert len(wrapped) <= kf.MAX_KEY_FILE_BYTES


def test_a_real_key_and_a_linked_one_still_load(tmp_path):
    key = ev.load_or_create_signing_key(tmp_path / "evidence_ed25519.pem")
    pub = ev.public_key_hex(key)
    assert ev.existing_public_key_hex(tmp_path / "evidence_ed25519.pem") == pub
    if sys.platform != "win32":
        link = tmp_path / "linked.pem"
        link.symlink_to(tmp_path / "evidence_ed25519.pem")
        assert ev.existing_public_key_hex(link) == pub


def test_a_missing_key_is_still_missing(tmp_path):
    with pytest.raises(FileNotFoundError):
        kf.read_once(tmp_path / "absent.pem")
    assert ev.signing_key_state(tmp_path / "absent.pem") == ("none", None)


def test_the_review_reads_through_the_shared_reader():
    src = Path(ev.__file__).read_text(encoding="utf-8")
    body = src.split("def existing_public_key_hex", 1)[1].split("\ndef ", 1)[0]
    assert "keyfile.read_once(" in body and "read_bytes(" not in body
