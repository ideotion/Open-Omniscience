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

from src.backup.regular_file import NotARegularFile, create_new, open_regular
from src.monitoring.secret_scrub import passphrase_bytes

# Self-describing container so a file can be decrypted years later without out-of-band
# parameters:  MAGIC(8) | n(4) | r(4) | p(4) | salt(16) | nonce(12) | ciphertext+tag.
_MAGIC = b"OOENC1\x00\x00"
_N, _R, _P = 2**15, 8, 1  # conservative, matches custody key wrapping

# A single AES-GCM call caps its input at 2**31-1 bytes (~2 GiB); `cryptography` raises a
# CRYPTIC `OverflowError: "Data too long. Max 2**31-1 bytes"` above it. We PRE-CHECK and
# raise an honest, actionable EncryptionError instead (field test 2026-06-24: a 6 GB corpus
# hit this). The STREAMING path (OOENC2: encrypt_file / write_volume_backup) has NO cap and
# never holds the whole archive in RAM -- that is the answer for a large corpus.
_GCM_MAX_BYTES = 2**31 - 1  # 2_147_483_647


class EncryptionError(RuntimeError):
    """Raised when decryption fails (wrong passphrase, truncated/tampered data)."""


def _derive(passphrase: bytes, salt: bytes, n: int, r: int, p: int) -> bytes:
    # The cost comes out of the FILE's header on the read paths, so a crafted header could ask for an enormous scrypt (memory n*r*128 bytes, time linear in p).
    # Every container this app has ever written carries exactly (_N, _R, _P) (git history of this module), so the reader accepts exactly that and refuses anything else
    # as malformed BEFORE any work is done. WHAT THE BOUND PROTECTS: the memory of one derivation, n*r*128 = 32 MiB, measured 32.8 MiB peak growth and 0.11 s on this build;
    # a header can no longer make a restore allocate more. WRITER AND READER SHARE ONE CONSTANT: the tuple accepted here IS the one the writers pack (_N, _R, _P), so changing the
    # writer's cost changes what this accepts and a build can never refuse its own new files; the files an OLDER build wrote with other parameters would need their own entry here,
    # in the commit that changes the constant (tests/test_crypto_header_bounds.py derives the accepted tuple from the constant and pins both directions).
    if (n, r, p) != (_N, _R, _P):
        raise EncryptionError("malformed encrypted header (unsupported key-derivation parameters)")
    return Scrypt(salt=salt, length=32, n=n, r=r, p=p).derive(passphrase)


def _key_bytes(passphrase: str) -> bytes:
    """The passphrase as the bytes a key is derived from. One that cannot be written as UTF-8 (a lone surrogate) is an
    :class:`EncryptionError` with fixed words: Python's own error names the character at fault and holds the whole
    passphrase (``secret_scrub.passphrase_bytes``)."""
    return passphrase_bytes(passphrase, error=EncryptionError)


def encrypt_bytes(data: bytes, passphrase: str) -> bytes:
    """Encrypt ``data`` under ``passphrase`` into a self-describing container.

    Single-shot AES-GCM: the whole ``data`` is held in RAM and capped at ~2 GiB. Above the
    cap it raises a clear :class:`EncryptionError` pointing at the streaming/volume path,
    NOT a cryptic ``OverflowError``.
    """
    if not passphrase:
        raise EncryptionError("a non-empty passphrase is required")
    if len(data) > _GCM_MAX_BYTES:
        raise EncryptionError(
            f"data is {len(data)} bytes — above the ~2 GiB single-shot AES-GCM limit "
            f"({_GCM_MAX_BYTES} bytes). Use the streaming/volume backup (encrypt_file / "
            "write_volume_backup), which has no cap and never holds the whole archive in RAM."
        )
    import os

    salt, nonce = os.urandom(16), os.urandom(12)
    key = _derive(_key_bytes(passphrase), salt, _N, _R, _P)
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
    if len(ct) > _GCM_MAX_BYTES:
        # An honest error before AES-GCM raises its cryptic OverflowError on decrypt.
        raise EncryptionError(
            f"ciphertext is {len(ct)} bytes — above the ~2 GiB single-shot AES-GCM limit. "
            "This container was not produced by this build's streaming path; a volume set "
            "(read_volume_backup) is the large-archive path."
        )
    key = _derive(_key_bytes(passphrase), salt, n, r, p)
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
    aes = AESGCM(_derive(_key_bytes(passphrase), salt, _N, _R, _P))
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
    with open(src, "rb") as fin, create_new(dst) as fout:  # never through a link at dst (row 313)
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
    with create_new(dst) as fout:  # a volume is created, never written through a link at its name (row 313)
        fout.write(header)
        return _encrypt_stream(fin, fout, aes, prefix, chunk_size, limit)


def encrypt_stream_to_hashed(
    fin,
    dst: str | os.PathLike[str],
    passphrase: str,
    *,
    limit: int,
    chunk_size: int = _CHUNK_DEFAULT,
) -> tuple[int, str]:
    """:func:`encrypt_stream_to` that ALSO returns the SHA-256 of the CIPHERTEXT
    file it wrote, hashed while writing — so a volume writer never needs a second
    read pass over multi-GB output just to checksum it (P0.1 bounded-IO)."""
    import hashlib

    header, prefix, aes = _header_and_cipher(passphrase, chunk_size)
    h = hashlib.sha256()

    class _HashingOut:
        def __init__(self, fh) -> None:
            self._fh = fh

        def write(self, b: bytes) -> int:
            h.update(b)
            return self._fh.write(b)

    with create_new(dst) as fout:  # never through a link at its name (row 313)
        out = _HashingOut(fout)
        out.write(header)
        consumed = _encrypt_stream(fin, out, aes, prefix, chunk_size, limit)
    return consumed, h.hexdigest()


def _open_stream_header(fin, passphrase: str) -> tuple[AESGCM, bytes, int]:
    """Read an OOENC2 header from ``fin`` and derive its key: ``(cipher, nonce prefix, sealed chunk size)``."""
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
    return AESGCM(_derive(_key_bytes(passphrase), salt, n, r, p)), prefix, chunk_size + _TAG


def _open_sealed(src: str | os.PathLike[str]):
    """An encrypted file opened to be read, as a regular file or not at all (row 312).

    A backup's volumes sit on a drive anyone may write to: a named pipe in a volume's place held a restore on its
    open for ever, and a link to ``/dev/zero`` was read without end. A link is followed (the app's own files may
    live behind one; the backup readers refuse links in the folder before they get here), but what it reaches must
    be a regular file, and the open never blocks. Anything else is the same refusal as a file that is not ours."""
    try:
        return open_regular(src, follow_links=True)
    except NotARegularFile:
        raise EncryptionError("not an Open Omniscience encrypted file (not a regular file); nothing was read") from None


def decrypt_stream(
    src: str | os.PathLike[str],
    write,
    passphrase: str,
) -> int:
    """Stream-decrypt an OOENC2 file, passing each plaintext chunk to ``write``
    (a ``bytes -> Any`` callable: a file's ``write``, a hasher's ``update``, …).

    The sink form lets a VERIFY pass prove a volume decrypts and checksum its
    plaintext WITHOUT writing anything to disk. Returns the plaintext byte count.
    Raises loudly on a wrong passphrase, tamper, truncation, reordering or an
    extended stream -- never silently yields a partial archive."""
    total = 0
    with _open_sealed(src) as fin:
        aes, prefix, block = _open_stream_header(fin, passphrase)
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
            write(pt)
            total += len(pt)
            counter += 1
            if final:
                break
            prev = cur
    return total


def stream_key_opens(src: str | os.PathLike[str], passphrase: str) -> bool:
    """Whether ``passphrase`` opens the FIRST chunk of an OOENC2 file, reading only the header and that chunk.

    A quick key check before a long pass, never a verification of the file: True says the key is right for this
    file, False says the first chunk's tag failed (a wrong key, or a damaged first chunk -- the caller tells the two
    apart, for example by the file's checksum). A malformed header raises :class:`EncryptionError` as
    :func:`decrypt_stream` does. Nothing decrypted is kept."""
    with _open_sealed(src) as fin:
        aes, prefix, block = _open_stream_header(fin, passphrase)
        first = fin.read(block)
        final = not fin.read(1)  # a one-chunk file seals its only chunk as the final one
    try:
        aes.decrypt(_chunk_nonce(prefix, 0, final), first, None)
    except InvalidTag:
        return False
    return True


def decrypt_file(
    src: str | os.PathLike[str],
    dst: str | os.PathLike[str],
    passphrase: str,
) -> None:
    """Stream-decrypt an OOENC2 file written by :func:`encrypt_file`.

    Raises loudly on a wrong passphrase, tamper, truncation, reordering or an
    extended stream -- never silently yields a partial archive."""
    with create_new(dst) as fout:  # never through a link at its name (row 313)
        decrypt_stream(src, fout.write, passphrase)
