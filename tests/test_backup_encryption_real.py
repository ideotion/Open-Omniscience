"""Prove backup encryption is REAL ciphertext, not a header over plaintext.

P0-2 (field test 2026-06-19, #O-4): the maintainer saw an encrypted and a plaintext
backup report the SAME size and reasonably asked "is it actually encrypted?".

The answer (proven here): yes. AES-256-GCM adds a fixed 64-byte overhead (the OOENC1
header + scrypt params + salt + nonce + GCM tag), so a 326 MB backup grows by ~64
bytes and rounds to the same MB in the UI — the size match is EXPECTED, not a bug.
These tests prove the body is high-entropy ciphertext (a no-op or header-over-plaintext
would keep the low entropy of a compressible input), never leaks the plaintext, and
round-trips exactly, with a wrong passphrase failing loudly.
"""

from __future__ import annotations

import math
import zipfile

import pytest
from fastapi.testclient import TestClient

from src.safety.crypto import EncryptionError, decrypt_bytes, encrypt_bytes

# OOENC1 header(8) + n,r,p(12) + salt(16) + nonce(12) + GCM tag(16) = 64 bytes.
_GCM_OVERHEAD = 64


def _shannon_bits_per_byte(data: bytes) -> float:
    if not data:
        return 0.0
    counts = [0] * 256
    for b in data:
        counts[b] += 1
    n = len(data)
    return -sum((c / n) * math.log2(c / n) for c in counts if c)


def test_encrypt_bytes_produces_high_entropy_ciphertext():
    """A low-entropy plaintext must become high-entropy ciphertext. If 'encryption'
    were a no-op (or magic+plaintext), the entropy would stay near zero."""
    plaintext = b"AAAA-SECRET-NEWSLETTER-CONTENT-" * 5000  # ~150 KB, very compressible
    assert _shannon_bits_per_byte(plaintext) < 5.0  # genuinely low-entropy input

    blob = encrypt_bytes(plaintext, "correct horse battery staple")

    assert blob[:8] == b"OOENC1\x00\x00", "missing the AES-GCM envelope magic"
    body = blob[8:]
    assert _shannon_bits_per_byte(body) > 7.9, "ciphertext is not high-entropy — not encrypted"
    assert b"SECRET-NEWSLETTER" not in blob, "plaintext leaked into the 'encrypted' blob"


def test_encrypted_size_is_plaintext_plus_exactly_64_bytes():
    """Explains the maintainer's observation: encrypted ≈ plaintext size by design.
    The GCM overhead is a fixed 64 bytes regardless of payload size, so a big backup
    rounds to the same MB."""
    for n in (0, 1, 1000, 1_000_000):
        blob = encrypt_bytes(b"x" * n, "pw")
        assert len(blob) == n + _GCM_OVERHEAD


def test_decrypt_round_trips_exactly_and_wrong_passphrase_is_loud():
    data = b"the corpus, byte for byte \x00\x01\x02\xff" * 1000
    blob = encrypt_bytes(data, "right-pass")
    assert decrypt_bytes(blob, "right-pass") == data
    with pytest.raises(EncryptionError):
        decrypt_bytes(blob, "wrong-pass")  # GCM tag mismatch -> loud, never garbage


def test_end_to_end_encrypted_backup_is_ciphertext_and_plaintext_is_not(tmp_path):
    """The real backup builder: an encrypted artifact is high-entropy OOENC1 ciphertext
    that decrypts to a valid zip; a plaintext artifact is a bare zip (no OOENC1)."""
    from src.api.main import app

    with TestClient(app):  # triggers init_db so the corpus DB exists to snapshot
        from src.backup.artifact import read_artifact, write_backup_v2

        # Audit finding 2026-07-17: this used to be a hand-rolled tempfile.mkdtemp()
        # whose finally-block only unlinked the two known files inside it, never the
        # directory itself (or any other file write_backup_v2 might leave behind) --
        # a leaked directory per test run. pytest's own tmp_path fixture is a real
        # per-test directory it cleans up on its own retention policy, so no manual
        # cleanup is needed at all.
        enc = tmp_path / "enc.oobak.ooenc"
        plain = tmp_path / "plain.oobak"
        write_backup_v2(enc, passphrase="proof-pw-123")
        write_backup_v2(plain, passphrase=None)

        enc_blob = enc.read_bytes()
        plain_blob = plain.read_bytes()

        # Encrypted artifact: OOENC1 + high-entropy body that decrypts to a zip.
        assert enc_blob[:8] == b"OOENC1\x00\x00"
        assert _shannon_bits_per_byte(enc_blob[64:65000]) > 7.5
        inner = decrypt_bytes(enc_blob, "proof-pw-123")
        assert inner[:4] == b"PK\x03\x04", "encrypted artifact did not decrypt to a zip"
        assert zipfile.is_zipfile(__import__("io").BytesIO(inner))

        # Plaintext artifact: a bare zip, never OOENC1.
        assert plain_blob[:8] != b"OOENC1\x00\x00"
        assert plain_blob[:4] == b"PK\x03\x04"

        # The honest verdict the preview surfaces.
        assert read_artifact(enc_blob, passphrase="proof-pw-123").encrypted is True
        assert read_artifact(plain_blob).encrypted is False


def test_restore_preview_reports_encrypted_verdict():
    """The preview report carries the encryption verdict so the UI can confirm it."""
    from src.api.main import app

    with TestClient(app) as c:
        import os
        import tempfile
        from pathlib import Path

        from src.backup.artifact import write_backup_v2

        fd, tmp = tempfile.mkstemp(suffix=".ooenc")
        os.close(fd)
        dest = Path(tmp)
        dest.unlink(missing_ok=True)
        write_backup_v2(dest, passphrase="verdict-pw")
        blob = dest.read_bytes()
        dest.unlink(missing_ok=True)
        prev = c.post(
            "/api/backup/v2/restore/preview",
            files={"file": ("b.ooenc", blob, "application/octet-stream")},
            data={"passphrase": "verdict-pw"},
        )
        assert prev.status_code == 200, prev.text
        assert prev.json()["encrypted"] is True
