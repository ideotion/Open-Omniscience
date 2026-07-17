"""
Tests for anchoring providers (src/custody/anchor.py).

Core guarantees:
- the local provider round-trips offline and is honest about being local-only;
- public-chain providers REFUSE with a clear error (no silent stub that passes);
- the OpenTimestamps provider surfaces unavailability rather than faking a proof.
"""

from __future__ import annotations

import pytest

from src.custody import anchor as anchor_mod
from src.custody.anchor import (
    AnchorUnavailable,
    LocalAnchorProvider,
    OpenTimestampsAnchorProvider,
    UnavailableAnchorProvider,
    available_providers,
    get_provider,
)

ROOT = "a" * 64  # a sha256-shaped hex root


def test_local_anchor_roundtrip(tmp_path):
    p = LocalAnchorProvider(db_path=str(tmp_path / "anchors.db"))
    receipt = p.anchor(ROOT, {"case": "X"})
    assert receipt.provider == "local"
    ok, reason = p.verify(receipt)
    assert ok
    assert "local" in reason.lower()
    p.close()


def test_local_anchor_verify_unknown_root_fails(tmp_path):
    p = LocalAnchorProvider(db_path=str(tmp_path / "anchors.db"))
    receipt = p.anchor(ROOT)
    receipt.merkle_root = "f" * 64
    ok, _ = p.verify(receipt)
    assert not ok
    p.close()


def test_local_anchor_book_stays_plaintext_when_the_corpus_is(tmp_path):
    """Regression pin for the fix below: with no process passphrase set (the
    default test environment, OO_DB_PLAINTEXT=1), a fresh anchor book is still
    plaintext -- unchanged behaviour for the common/test case."""
    from src.database.connect import is_encrypted_file

    db_path = tmp_path / "anchors.db"
    p = LocalAnchorProvider(db_path=str(db_path))
    p.anchor(ROOT)
    p.close()
    assert is_encrypted_file(db_path) is False


def test_local_anchor_book_encrypts_under_the_corpus_passphrase(tmp_path, monkeypatch):
    """Audit finding 2026-07-17 (L1): LocalAnchorProvider used a raw sqlite3.connect(),
    so the anchor book was ALWAYS written unencrypted regardless of the main corpus's
    own encryption setting -- even though it carries caller-supplied custody metadata.
    Fixed to use the ONE connection factory (mirroring CustodyLog's identical
    precedent for its sibling custody_log.db): with a process passphrase set (the
    unlocked-encrypted-corpus state), a FRESH anchor book must be created encrypted
    under that SAME passphrase, genuinely unreadable without it."""
    from src.database.connect import (
        DatabaseLockedError,
        WrongPassphraseError,
        connect,
        is_encrypted_file,
        set_passphrase,
    )

    # The suite-wide default is OO_DB_PLAINTEXT=1 (tests/conftest.py); a fresh file's
    # ambient plaintext opt-out outranks the process passphrase (connect.py's own
    # documented precedence), so this test opts back IN to encrypted-by-default —
    # the same technique test_sqlcipher.py already uses for the identical reason.
    monkeypatch.delenv("OO_DB_PLAINTEXT", raising=False)
    db_path = tmp_path / "anchors.db"
    set_passphrase("anchor-test-secret")
    try:
        p = LocalAnchorProvider(db_path=str(db_path))
        receipt = p.anchor(ROOT, {"case": "X"})
        p.close()
        assert is_encrypted_file(db_path) is True
        # Round-trips correctly with the SAME key.
        p2 = LocalAnchorProvider(db_path=str(db_path))
        ok, _ = p2.verify(receipt)
        assert ok
        p2.close()
        # Genuinely encrypted, not just superficially: the wrong key raises loudly
        # (connect()'s own HMAC readability check) rather than silently opening.
        with pytest.raises(WrongPassphraseError):
            connect(db_path, key="wrong-secret")
    finally:
        set_passphrase(None)
    # And a LOCKED corpus (passphrase cleared, but the file already exists encrypted)
    # must fail loudly rather than silently falling back to plaintext.
    with pytest.raises(DatabaseLockedError):
        LocalAnchorProvider(db_path=str(db_path))


def test_public_chain_providers_refuse_honestly():
    for name in ("ethereum", "ipfs", "arweave"):
        prov = get_provider(name)
        assert isinstance(prov, UnavailableAnchorProvider)
        with pytest.raises(AnchorUnavailable) as ei:
            prov.anchor(ROOT)
        # The refusal carries a privacy warning, not a fake success.
        assert (
            "privacy" in str(ei.value).lower() or "permanent publication" in str(ei.value).lower()
        )
        ok, _ = prov.verify(type("R", (), {"merkle_root": ROOT})())
        assert ok is False


def test_unknown_provider_raises():
    from src.custody.anchor import AnchorError

    with pytest.raises(AnchorError):
        get_provider("dogecoin")


def test_available_providers_lists_status():
    status = available_providers()
    assert "local" in status and "opentimestamps" in status
    assert all(name in status for name in ("ethereum", "ipfs", "arweave"))


def test_ots_provider_unavailable_is_surfaced(monkeypatch):
    """If OTS can't stamp, the provider raises AnchorUnavailable -- never a fake receipt."""
    monkeypatch.setattr(anchor_mod, "OTS_AVAILABLE", False)

    def _boom(*a, **k):
        from src.custody.timestamp import TimestampUnavailable

        raise TimestampUnavailable("offline")

    monkeypatch.setattr(anchor_mod, "ots_stamp", _boom)
    with pytest.raises(AnchorUnavailable):
        OpenTimestampsAnchorProvider().anchor(ROOT)


def test_ots_provider_rejects_non_hex_root():
    from src.custody.anchor import AnchorError

    with pytest.raises(AnchorError):
        OpenTimestampsAnchorProvider().anchor("not-hex-root")
