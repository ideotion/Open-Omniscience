"""
"Existed no later than T" timestamp proofs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A signature proves *who* vouched for some data and that it has not changed. It
says nothing trustworthy about *when*: the signer controls their own clock. For
legal defensibility you often need the orthogonal claim -- "this content existed
**no later than** time T" -- backed by something the operator cannot back-date.

This module offers two honest mechanisms and refuses to fake a third:

* :class:`LocalTimestamp` -- a *self-asserted* time from the machine's own clock.
  Its integrity comes from being signed inside a custody entry, but it is **not**
  independent third-party proof, and it says so in plain words. Fully offline.

* :func:`ots_stamp` -- **OpenTimestamps**: submits only an opaque SHA-256 digest
  to public calendar servers, which (over the following hours) anchor it into the
  Bitcoin blockchain. The resulting ``.ots`` proof shows the content existed no
  later than a specific Bitcoin block -- verifiable by anyone, with no trust in
  this tool, no wallet, and no per-item cost. This requires network egress; when
  it is unavailable we raise :class:`TimestampUnavailable` rather than inventing a
  time. (PR #18's RFC-3161 path returned ``datetime.now()`` and called it a
  trusted timestamp -- exactly the dishonesty we avoid here.)

PRIVACY: OpenTimestamps publishes only a hash, but the *act* of submitting reveals
your IP and the timing to the calendar operators. For a source who needs anonymity,
route this through Tor (set ``HTTPS_PROXY``) or skip it and rely on local + signing.
"""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime

# Public OpenTimestamps calendar servers (operated by the OTS project & community).
DEFAULT_CALENDARS = (
    "https://a.pool.opentimestamps.org",
    "https://b.pool.opentimestamps.org",
    "https://alice.btc.calendar.opentimestamps.org",
)

try:  # pragma: no cover - availability is environment-dependent
    from opentimestamps.calendar import RemoteCalendar  # type: ignore
    from opentimestamps.core.notary import (  # type: ignore
        BitcoinBlockHeaderAttestation,
        PendingAttestation,
    )
    from opentimestamps.core.op import OpSHA256  # type: ignore
    from opentimestamps.core.serialize import (  # type: ignore
        BytesDeserializationContext,
        BytesSerializationContext,
    )
    from opentimestamps.core.timestamp import (  # type: ignore
        DetachedTimestampFile,
        Timestamp,
    )

    OTS_AVAILABLE = True
except Exception:  # noqa: BLE001
    OTS_AVAILABLE = False


class TimestampError(RuntimeError):
    """Base class for timestamping problems."""


class TimestampUnavailable(TimestampError):
    """A third-party timestamp could not be obtained (offline / lib missing / refused)."""


@dataclass
class TimestampProof:
    """A timestamp claim attached to a digest.

    ``kind`` is ``"local"`` or ``"opentimestamps"``. For ``local`` the time is
    self-asserted (trust derives from the enclosing signature). For OTS, ``proof_b64``
    is the ``.ots`` detached proof and ``asserted_time`` is left ``None`` until the
    proof is verified against Bitcoin by an independent verifier.
    """

    kind: str
    digest: str  # hex of the timestamped digest
    asserted_time: str | None
    proof_b64: str | None
    detail: str

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "digest": self.digest,
            "asserted_time": self.asserted_time,
            "proof_b64": self.proof_b64,
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TimestampProof:
        return cls(
            kind=d["kind"],
            digest=d["digest"],
            asserted_time=d.get("asserted_time"),
            proof_b64=d.get("proof_b64"),
            detail=d.get("detail", ""),
        )


def sha256(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


# --------------------------------------------------------------------------- #
# Local (self-asserted) timestamp -- offline, always available
# --------------------------------------------------------------------------- #


def local_timestamp(digest: bytes) -> TimestampProof:
    """A self-asserted UTC time for ``digest``. Honest about its own weakness."""
    return TimestampProof(
        kind="local",
        digest=digest.hex(),
        asserted_time=datetime.now(UTC).isoformat(),
        proof_b64=None,
        detail=(
            "Self-asserted by this machine's clock; trustworthy only insofar as the "
            "enclosing signature is. NOT independent third-party proof of time."
        ),
    )


# --------------------------------------------------------------------------- #
# OpenTimestamps -- independent, Bitcoin-anchored (network required)
# --------------------------------------------------------------------------- #


def ots_stamp(
    digest: bytes,
    *,
    calendars: tuple[str, ...] = DEFAULT_CALENDARS,
    timeout: float = 10.0,
) -> TimestampProof:
    """Submit ``digest`` to OpenTimestamps calendars and return a ``.ots`` proof.

    Raises :class:`TimestampUnavailable` if the library is absent or no calendar
    could be reached -- never returns a fabricated time.
    """
    if not OTS_AVAILABLE:
        raise TimestampUnavailable(
            "OpenTimestamps is not installed (install the 'timestamping' extra)."
        )
    if len(digest) != 32:
        raise TimestampError("OpenTimestamps expects a 32-byte SHA-256 digest.")

    ts = Timestamp(digest)
    reached = 0
    errors: list[str] = []
    for url in calendars:
        try:
            cal_ts = RemoteCalendar(url).submit(digest, timeout=timeout)
            ts.merge(cal_ts)
            reached += 1
        except Exception as exc:  # noqa: BLE001 - calendars are best-effort
            errors.append(f"{url}: {exc}")
    if reached == 0:
        raise TimestampUnavailable(
            "No OpenTimestamps calendar could be reached: " + "; ".join(errors)
        )

    detached = DetachedTimestampFile(OpSHA256(), ts)
    ctx = BytesSerializationContext()
    detached.serialize(ctx)
    proof_b64 = base64.b64encode(ctx.getbytes()).decode("ascii")
    return TimestampProof(
        kind="opentimestamps",
        digest=digest.hex(),
        asserted_time=None,
        proof_b64=proof_b64,
        detail=(
            f"Submitted to {reached}/{len(calendars)} OpenTimestamps calendar(s); "
            "pending Bitcoin confirmation. Verify the .ots proof independently with "
            "the `ots` client or a Bitcoin node."
        ),
    )


def ots_info(proof: TimestampProof) -> dict:
    """Inspect an OTS proof's attestations honestly (pending vs Bitcoin-confirmed).

    Does NOT contact the network and does NOT itself prove Bitcoin inclusion -- it
    reports what the proof currently carries. A ``"bitcoin"`` attestation names the
    block height the digest is anchored in; ``"pending"`` means a calendar has it
    but it is not yet in a block.
    """
    if proof.kind != "opentimestamps" or not proof.proof_b64:
        raise TimestampError("not an OpenTimestamps proof")
    if not OTS_AVAILABLE:
        raise TimestampUnavailable("OpenTimestamps is not installed; cannot parse the proof.")

    blob = base64.b64decode(proof.proof_b64)
    detached = DetachedTimestampFile.deserialize(BytesDeserializationContext(blob))
    pending: list[str] = []
    bitcoin: list[int] = []
    for _msg, att in detached.timestamp.all_attestations():
        if isinstance(att, BitcoinBlockHeaderAttestation):
            bitcoin.append(att.height)
        elif isinstance(att, PendingAttestation):
            pending.append(att.uri.decode("utf-8") if isinstance(att.uri, bytes) else att.uri)
    return {
        "file_digest": detached.timestamp.msg.hex(),
        "matches_claim": detached.timestamp.msg.hex() == proof.digest,
        "bitcoin_block_heights": bitcoin,
        "pending_calendars": pending,
        "confirmed": bool(bitcoin),
    }
