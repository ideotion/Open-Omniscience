"""
Tests for timestamp proofs (src/custody/timestamp.py).

The core guarantee under test: the module never fabricates a third-party time.
- local_timestamp() is offline and labels itself as self-asserted.
- ots_stamp() raises TimestampUnavailable when OTS is missing or no calendar is
  reachable, instead of inventing a time.
- ots_info() parses a real proof's attestations honestly.

A live network stamp is only exercised when OO_TEST_OTS_LIVE=1 (calendar servers
are external and flaky; we don't gate CI on them).
"""

from __future__ import annotations

import os

import pytest

from src.custody import timestamp as ts
from src.custody.timestamp import (
    TimestampProof,
    TimestampUnavailable,
    local_timestamp,
    ots_info,
    ots_stamp,
    sha256,
)

DIGEST = sha256(b"evidence bytes")


def test_local_timestamp_is_offline_and_honest():
    p = local_timestamp(DIGEST)
    assert p.kind == "local"
    assert p.digest == DIGEST.hex()
    assert p.asserted_time is not None
    assert "not independent" in p.detail.lower()


def test_local_proof_roundtrips_through_dict():
    p = local_timestamp(DIGEST)
    p2 = TimestampProof.from_dict(p.to_dict())
    assert p2 == p


def test_ots_stamp_raises_when_unavailable(monkeypatch):
    """When the library is absent, we refuse -- we do not return a fake time."""
    monkeypatch.setattr(ts, "OTS_AVAILABLE", False)
    with pytest.raises(TimestampUnavailable):
        ots_stamp(DIGEST)


def test_ots_stamp_rejects_wrong_digest_length():
    if not ts.OTS_AVAILABLE:
        pytest.skip("opentimestamps not installed")
    with pytest.raises(Exception):
        ots_stamp(b"too short")


def test_ots_stamp_raises_when_no_calendar_reachable(monkeypatch):
    """All calendars unreachable -> TimestampUnavailable, not a fabricated proof."""
    if not ts.OTS_AVAILABLE:
        pytest.skip("opentimestamps not installed")

    class _DeadCalendar:
        def __init__(self, url):
            self.url = url

        def submit(self, digest, timeout=None):
            raise OSError("network down")

    monkeypatch.setattr(ts, "RemoteCalendar", _DeadCalendar)
    with pytest.raises(TimestampUnavailable):
        ots_stamp(DIGEST, calendars=("https://x", "https://y"))


def test_ots_info_on_constructed_proof(monkeypatch):
    """Build a proof with a known pending attestation (no network) and inspect it."""
    if not ts.OTS_AVAILABLE:
        pytest.skip("opentimestamps not installed")
    import base64

    from opentimestamps.core.notary import PendingAttestation
    from opentimestamps.core.op import OpSHA256
    from opentimestamps.core.serialize import BytesSerializationContext
    from opentimestamps.core.timestamp import DetachedTimestampFile, Timestamp

    t = Timestamp(DIGEST)
    t.attestations.add(PendingAttestation("https://a.pool.opentimestamps.org"))
    det = DetachedTimestampFile(OpSHA256(), t)
    ctx = BytesSerializationContext()
    det.serialize(ctx)
    proof = TimestampProof(
        kind="opentimestamps",
        digest=DIGEST.hex(),
        asserted_time=None,
        proof_b64=base64.b64encode(ctx.getbytes()).decode(),
        detail="test",
    )
    info = ots_info(proof)
    assert info["matches_claim"] is True
    assert info["confirmed"] is False
    assert info["pending_calendars"] == ["https://a.pool.opentimestamps.org"]


@pytest.mark.skipif(os.getenv("OO_TEST_OTS_LIVE") != "1", reason="live OTS network test (opt-in)")
def test_ots_stamp_live():
    proof = ots_stamp(DIGEST)
    assert proof.kind == "opentimestamps"
    info = ots_info(proof)
    assert info["matches_claim"] is True
    assert info["pending_calendars"]  # at least one calendar accepted it
