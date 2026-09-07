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

    _OTS_IMPORTED = True
except Exception as _exc:  # noqa: BLE001
    _OTS_IMPORTED = False
    _OTS_IMPORT_ERROR = f"{type(_exc).__name__}: {str(_exc)[:160]}"


def _probe_ots() -> tuple[bool, str]:
    """CAN IT BUILD AND READ A PROOF? -- not "does it import?". ``(available, reason)``.

    The same class as ``PQC_AVAILABLE`` (D7): a flag set by a bare import answers
    whether the module loaded, and every caller below reads it as "this build can
    produce and parse an OpenTimestamps proof". Those are different questions, and the
    pqcrypto near-miss is what a library that answers the first and fails the second
    costs -- there, a renamed function and a changed return contract left a whole
    honest-degrade machine unreachable while the flag said everything was fine.

    OFFLINE BY CONSTRUCTION, and that is the design point. The round trip exercises the
    exact API both production paths use -- :func:`anchor`'s
    ``Timestamp`` -> ``DetachedTimestampFile(OpSHA256(), ...)`` -> serialize, and
    :func:`ots_info`'s deserialize -> ``all_attestations()`` -- and stops there.
    ``RemoteCalendar`` is imported and never called: submitting to a calendar is real
    egress under explicit consent, so a capability probe must never perform it, and a
    probe that needed the network could not tell a missing library from a closed port.

    NEVER RAISES -- the negative direction the tests pin.
    """
    if not _OTS_IMPORTED:
        return False, f"opentimestamps is not usable ([timestamping] extra): {_OTS_IMPORT_ERROR}"
    digest = hashlib.sha256(b"open-omniscience ots capability probe").digest()
    try:
        ts = Timestamp(digest)
        # An EMPTY timestamp cannot be serialized -- the library refuses it by name
        # ("An empty timestamp can't be serialized"), which the first run of this probe
        # discovered. That refusal is correct and it is also not the production shape:
        # `anchor` merges a calendar's attestations into `ts` before serializing, so a
        # real proof always carries at least one. A local PendingAttestation reproduces
        # that shape with NO network -- and without it this probe would have reported
        # OTS unavailable on every install that has it, a FABRICATED FAILURE, exactly as
        # dishonest as the fabricated pass being fixed and much easier to believe.
        ts.attestations.add(PendingAttestation("https://probe.invalid"))
        ctx = BytesSerializationContext()
        DetachedTimestampFile(OpSHA256(), ts).serialize(ctx)
        blob = ctx.getbytes()
        back = DetachedTimestampFile.deserialize(BytesDeserializationContext(blob))
        if back.timestamp.msg != digest:
            return False, "a serialized proof did not deserialize back to the same digest"
        # ots_info walks exactly this, and isinstance-tests each attestation. The
        # probe's own PendingAttestation comes back through it, so the walk is
        # genuinely exercised rather than returning an empty list for free.
        if not any(isinstance(a, PendingAttestation) for _m, a in back.timestamp.all_attestations()):
            return False, "a serialized attestation did not survive the round trip"
    except Exception as exc:  # noqa: BLE001 - nothing escapes a capability probe
        return False, f"{type(exc).__name__}: {str(exc)[:160]}"
    return True, "detached-proof round trip verified (build, serialize, deserialize, read)"


#: Set from the CAPABILITY, never from the import; the reason places the blame.
OTS_AVAILABLE, OTS_REASON = _probe_ots()


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
