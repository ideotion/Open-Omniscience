"""Audit 0.5.0 A-015: the scrypt cost in an encrypted file's header is bounded to what this app writes.

A crafted OOENC1/OOENC2 header asked for any (n, r, p) and `_derive` passed it to scrypt, whose memory is n*r*128 bytes. The reader now accepts exactly the parameters
every writer has used and refuses the rest as a malformed header before any key derivation.
"""

from __future__ import annotations

import struct

import pytest

from src.safety import crypto


def _no_scrypt(monkeypatch):
    """After the file under test was written (writing derives a key): from here no key may be derived."""

    def boom(*a, **k):
        raise AssertionError("a key was derived from a header that should have been refused")

    monkeypatch.setattr(crypto, "Scrypt", boom)


@pytest.mark.parametrize("params", [(2**31, 8, 1), (2**15, 2**20, 1), (2**15, 8, 2**20), (2**15 * 2, 8, 1), (1, 1, 1), (0, 0, 0)])
def test_a_container_header_with_other_key_derivation_costs_is_refused_before_any_work(monkeypatch, params):
    good = crypto.encrypt_bytes(b"x", "pw")
    _no_scrypt(monkeypatch)
    blob = good[:8] + struct.pack(">III", *params) + good[20:]
    with pytest.raises(crypto.EncryptionError, match="malformed encrypted header"):
        crypto.decrypt_bytes(blob, "pw")


def test_a_streaming_file_with_an_oversize_cost_is_refused_before_any_work(tmp_path, monkeypatch):
    src, enc = tmp_path / "p.bin", tmp_path / "p.enc"
    src.write_bytes(b"x" * 100)
    crypto.encrypt_file(src, enc, "pw")
    raw = enc.read_bytes()
    _no_scrypt(monkeypatch)
    enc.write_bytes(raw[:8] + struct.pack(">III", 2**31, 8, 1) + raw[20:])
    with pytest.raises(crypto.EncryptionError, match="malformed encrypted header"):
        crypto.decrypt_file(enc, tmp_path / "out.bin", "pw")


def test_what_the_writers_write_still_round_trips(tmp_path):
    assert crypto.decrypt_bytes(crypto.encrypt_bytes(b"hello", "pw"), "pw") == b"hello"
    src, enc, out = tmp_path / "p.bin", tmp_path / "p.enc", tmp_path / "o.bin"
    src.write_bytes(b"y" * 1000)
    crypto.encrypt_file(src, enc, "pw")
    crypto.decrypt_file(enc, out, "pw")
    assert out.read_bytes() == src.read_bytes()


def test_the_accepted_tuple_is_the_writers_own_constant_not_a_literal(monkeypatch):
    """Writer and reader share (_N, _R, _P): change the writer's cost and a file it writes is read back; a file written at the OLD cost is refused until the constant
    that changed it also names it. A build cannot refuse its own new files."""
    old = crypto.encrypt_bytes(b"old", "pw")
    monkeypatch.setattr(crypto, "_N", 2**14)
    assert crypto.decrypt_bytes(crypto.encrypt_bytes(b"new", "pw"), "pw") == b"new"
    with pytest.raises(crypto.EncryptionError, match="malformed encrypted header"):
        crypto.decrypt_bytes(old, "pw")
