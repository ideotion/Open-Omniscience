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
