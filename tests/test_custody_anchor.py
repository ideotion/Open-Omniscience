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
