"""Streaming (chunked) AEAD — OOENC2 (src/safety/crypto.py).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The large-backup encryptor: no 2 GiB ceiling, never the whole file in RAM. Pins the
round-trip across many chunks (incl. empty + exact-multiple), and that a wrong
passphrase, a tampered byte, a TRUNCATED stream and a REORDERED stream all fail loudly
(the STREAM construction's truncation/reorder protection) rather than yield a partial
archive. Uses a small chunk size to exercise multi-chunk paths on tiny inputs.
"""

import os

import pytest

from src.safety.crypto import (
    EncryptionError,
    decrypt_file,
    encrypt_file,
    encrypt_stream_to,
    is_streaming_magic,
)

CS = 1024  # smallest valid chunk size -> many chunks on a few KB


def _enc(tmp_path, data: bytes):
    src, enc, dec = tmp_path / "in", tmp_path / "enc", tmp_path / "dec"
    src.write_bytes(data)
    encrypt_file(src, enc, "pw", chunk_size=CS)
    return src, enc, dec


@pytest.mark.parametrize("n", [0, 1, 1023, 1024, 2048, 3000, 5000])
def test_round_trip_sizes(tmp_path, n):
    data = os.urandom(n)
    _src, enc, dec = _enc(tmp_path, data)
    assert is_streaming_magic(enc.read_bytes()[:8])
    decrypt_file(enc, dec, "pw")
    assert dec.read_bytes() == data


def test_wrong_passphrase_fails_loudly(tmp_path):
    _src, enc, dec = _enc(tmp_path, os.urandom(3000))
    with pytest.raises(EncryptionError):
        decrypt_file(enc, dec, "WRONG")


def test_tampered_byte_is_rejected(tmp_path):
    _src, enc, dec = _enc(tmp_path, os.urandom(3000))
    b = bytearray(enc.read_bytes())
    b[60] ^= 1  # flip a bit inside the first ciphertext chunk
    enc.write_bytes(bytes(b))
    with pytest.raises(EncryptionError):
        decrypt_file(enc, dec, "pw")


def test_truncated_stream_is_rejected(tmp_path):
    # 3000 bytes @ CS=1024 -> chunks 1024,1024,952; drop the final (952+16) chunk.
    _src, enc, dec = _enc(tmp_path, os.urandom(3000))
    full = enc.read_bytes()
    enc.write_bytes(full[: -(952 + 16)])
    with pytest.raises(EncryptionError):
        decrypt_file(enc, dec, "pw")


def test_reordered_chunks_are_rejected(tmp_path):
    _src, enc, dec = _enc(tmp_path, os.urandom(3000))
    raw = enc.read_bytes()
    H, B = 47, CS + 16  # header, full ciphertext block
    c0, c1, rest = raw[H : H + B], raw[H + B : H + 2 * B], raw[H + 2 * B :]
    enc.write_bytes(raw[:H] + c1 + c0 + rest)  # swap two non-final chunks
    with pytest.raises(EncryptionError):
        decrypt_file(enc, dec, "pw")


def test_empty_passphrase_refused(tmp_path):
    src = tmp_path / "in"
    src.write_bytes(b"x")
    with pytest.raises(EncryptionError):
        encrypt_file(src, tmp_path / "enc", "", chunk_size=CS)


def test_stream_slicing_into_independent_volumes(tmp_path):
    """encrypt_stream_to slices an open reader into standalone OOENC2 volumes that each
    decrypt independently and reassemble byte-identically (the volume-codec primitive)."""
    data = os.urandom(5000)
    src = tmp_path / "in"
    src.write_bytes(data)
    sizes, out = [], b""
    with open(src, "rb") as fin:
        i = 0
        while True:
            v = tmp_path / f"vol{i}"
            n = encrypt_stream_to(fin, v, "pw", limit=2048, chunk_size=CS)
            if n == 0:
                v.unlink()
                break
            sizes.append(n)
            i += 1
            if n < 2048:
                break
    assert sizes == [2048, 2048, 904]
    for j in range(len(sizes)):
        vd = tmp_path / f"vol{j}.d"
        decrypt_file(tmp_path / f"vol{j}", vd, "pw")
        out += vd.read_bytes()
    assert out == data
