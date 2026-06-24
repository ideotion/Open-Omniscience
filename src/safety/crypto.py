"""
Passphrase encryption for portable, at-rest protection (the same audited scheme as keys).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

AES-256-GCM with a scrypt-derived key — the *exact* primitive already used to wrap the
custody signing keys (``src/custody/signing.py``), generalised here so a journalist can
encrypt a corpus backup with a passphrase. A wrong passphrase fails **loudly** (GCM auth
tag mismatch), never silently returns garbage. This is application-level encryption for
transport/stash; it is not a substitute for full-disk encryption of the live machine.
"""

from __future__ import annotations

import os
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

# Self-describing container so a file can be decrypted years later without out-of-band
# parameters:  MAGIC(8) | n(4) | r(4) | p(4) | salt(16) | nonce(12) | ciphertext+tag.
_MAGIC = b"OOENC1\x00\x00"
_N, _R, _P = 2**15, 8, 1  # conservative, matches custody key wrapping


class EncryptionError(RuntimeError):
    """Raised when decryption fails (wrong passphrase, truncated/tampered data)."""


def _derive(passphrase: bytes, salt: bytes, n: int, r: int, p: int) -> bytes:
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase)


def encrypt_bytes(data: bytes, passphrase: str) -> bytes:
    """Encrypt ``data`` under ``passphrase`` into a self-describing container."""
    if not passphrase:
        raise EncryptionError("a non-empty passphrase is required")
    import os

    salt, nonce = os.urandom(16), os.urandom(12)
    key = _derive(passphrase.encode("utf-8"), salt, _N, _R, _P)
    ct = AESGCM(key).encrypt(nonce, data, None)
    return _MAGIC + struct.pack(">III", _N, _R, _P) + salt + nonce + ct


def decrypt_bytes(blob: bytes, passphrase: str) -> bytes:
    """Decrypt a container produced by :func:`encrypt_bytes`. Raises on any failure."""
    if not blob.startswith(_MAGIC):
        raise EncryptionError("not an Open Omniscience encrypted file")
    try:
        n, r, p = struct.unpack(">III", blob[8:20])
        salt, nonce, ct = blob[20:36], blob[36:48], blob[48:]
    except struct.error as exc:
        raise EncryptionError("truncated or malformed encrypted file") from exc
    key = _derive(passphrase.encode("utf-8"), salt, n, r, p)
    try:
        return AESGCM(key).decrypt(nonce, ct, None)
    except InvalidTag as exc:
        raise EncryptionError("wrong passphrase or the file has been altered") from exc


# --------------------------------------------------------------------------- #
#  Streaming (chunked) AEAD for large archives  (OOENC2)
# --------------------------------------------------------------------------- #
# A single AES-GCM call caps at 2**31-1 bytes (~2 GiB) AND requires the whole
# archive in RAM -- so a 6 GB corpus backup fails with "Data too long. Max
# 2**31-1 bytes" (field test 2026-06-24). We frame the archive into fixed-size
# chunks, each its OWN AES-GCM (nonce, tag), streamed straight to/from disk. This
# is the standard STREAM online-AEAD construction: the per-chunk 12-byte nonce is
# prefix(7) | counter(4, big-endian) | final-flag(1). The counter makes every
# nonce unique under the per-file key; the final-flag binds the last chunk, so a
# TRUNCATED, REORDERED or EXTENDED stream fails authentication instead of silently
# decrypting to a partial archive. Header (47 bytes):
#   MAGIC2(8) | n(4) | r(4) | p(4) | salt(16) | nonce_prefix(7) | chunk_size(4)
_MAGIC2 = b"OOENC2\x00\x00"
_HEADER2_LEN = 47
_CHUNK_DEFAULT = 4 * 1024 * 1024                  # 4 MiB plaintext per chunk
_CHUNK_MIN, _CHUNK_MAX = 1024, 256 * 1024 * 1024  # sane bounds when trusting a header
_TAG = 16                                          # AES-GCM tag length


def _chunk_nonce(prefix: bytes, counter: int, final: bool) -> bytes:
    return prefix + struct.pack(">I", counter) + (b"\x01" if final else b"\x00")


def is_streaming_magic(prefix: bytes) -> bool:
    """True when ``prefix`` (the first >= 8 bytes of a file) is an OOENC2 container."""
    return prefix[:8] == _MAGIC2


def _header_and_cipher(passphrase: str, chunk_size: int) -> tuple[bytes, bytes, AESGCM]:
    """Fresh OOENC2 header (random salt + 7-byte nonce prefix) + the cipher keyed for it."""
    if not passphrase:
        raise EncryptionError("a non-empty passphrase is required")
    if not (_CHUNK_MIN <= chunk_size <= _CHUNK_MAX):
        raise EncryptionError("invalid chunk size")
    salt, prefix = os.urandom(16), os.urandom(7)
    aes = AESGCM(_derive(passphrase.encode("utf-8"), salt, _N, _R, _P))
    header = (
        _MAGIC2 + struct.pack(">III", _N, _R, _P) + salt + prefix + struct.pack(">I", chunk_size)
    )
    return header, prefix, aes


def _encrypt_stream(fin, fout, aes: AESGCM, prefix: bytes, chunk_size: int, limit: int | None) -> int:
    """Encrypt up to ``limit`` plaintext bytes (None = to EOF) from ``fin`` into ``fout``
    as OOENC2 chunks; one-block lookahead flags the LAST chunk final (binds the end).
    Returns the plaintext bytes consumed."""
    consumed = 0

    def _read() -> bytes:
        nonlocal consumed
        want = chunk_size if limit is None else min(chunk_size, limit - consumed)
        if want <= 0:
            return b""
        b = fin.read(want)
        consumed += len(b)
        return b

    counter = 0
    prev = _read()
    while True:
        cur = _read()
        final = not cur
        fout.write(aes.encrypt(_chunk_nonce(prefix, counter, final), prev, None))
        counter += 1
        if final:
            break
        prev = cur
    return consumed


def encrypt_file(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    passphrase: str,
    *,
    chunk_size: int = _CHUNK_DEFAULT,
) -> None:
    """Stream-encrypt ``src`` to ``dst`` in the OOENC2 chunked container.

    Never holds the whole file in RAM and has no 2 GiB ceiling. A wrong passphrase
    or any tampering fails loudly on decrypt (per-chunk GCM auth)."""
    header, prefix, aes = _header_and_cipher(passphrase, chunk_size)
    with open(src, "rb") as fin, open(dst, "wb") as fout:
        fout.write(header)
        _encrypt_stream(fin, fout, aes, prefix, chunk_size, None)


def encrypt_stream_to(
    fin,
    dst: str | os.PathLike[str],
    passphrase: str,
    *,
    limit: int,
    chunk_size: int = _CHUNK_DEFAULT,
) -> int:
    """Encrypt exactly ``limit`` plaintext bytes from the OPEN, positioned reader ``fin``
    into a new standalone OOENC2 file ``dst`` (its OWN salt/nonce -> independently
    decryptable). Returns the bytes actually consumed (< limit only at EOF).

    The per-VOLUME encryptor: a large archive is read ONCE and sliced into <600 MB
    volumes, each a self-contained OOENC2 file with its own authentication."""
    header, prefix, aes = _header_and_cipher(passphrase, chunk_size)
    with open(dst, "wb") as fout:
        fout.write(header)
        return _encrypt_stream(fin, fout, aes, prefix, chunk_size, limit)


def decrypt_file(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    passphrase: str,
) -> None:
    """Stream-decrypt an OOENC2 file written by :func:`encrypt_file`.

    Raises loudly on a wrong passphrase, tamper, truncation, reordering or an
    extended stream -- never silently yields a partial archive."""
    with open(src, "rb") as fin:
        header = fin.read(_HEADER2_LEN)
        if len(header) < _HEADER2_LEN or header[:8] != _MAGIC2:
            raise EncryptionError("not an Open Omniscience streaming (OOENC2) file")
        try:
            n, r, p = struct.unpack(">III", header[8:20])
            salt, prefix = header[20:36], header[36:43]
            chunk_size = struct.unpack(">I", header[43:47])[0]
        except struct.error as exc:
            raise EncryptionError("truncated or malformed encrypted header") from exc
        if not (_CHUNK_MIN <= chunk_size <= _CHUNK_MAX):
            raise EncryptionError("malformed encrypted file (bad chunk size)")
        aes = AESGCM(_derive(passphrase.encode("utf-8"), salt, n, r, p))
        block = chunk_size + _TAG
        with open(dst, "wb") as fout:
            counter = 0
            prev = fin.read(block)
            while True:
                cur = fin.read(block)
                final = not cur
                try:
                    pt = aes.decrypt(_chunk_nonce(prefix, counter, final), prev, None)
                except InvalidTag as exc:
                    raise EncryptionError(
                        "wrong passphrase or the file has been altered"
                    ) from exc
                fout.write(pt)
                counter += 1
                if final:
                    break
                prev = cur
