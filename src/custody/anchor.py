"""
Anchoring providers: publish a Merkle root to an external witness.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Signing and a local hash chain prove integrity and *self-asserted* time. An
*anchor* adds an external, after-the-fact-unforgeable witness that a given Merkle
root existed no later than time T -- without trusting this tool's clock or key.

Providers implement a small interface. Two are shipped:

* :class:`LocalAnchorProvider` -- records the root in a local SQLite "anchor book".
  Offline, always available. Honest about what it proves: only that *this tool*
  recorded the root locally (useful for internal audit, not third-party proof).

* :class:`OpenTimestampsAnchorProvider` -- anchors the root into Bitcoin via the
  OpenTimestamps calendars. Independent, no wallet, no per-item fee; needs network.

Public-blockchain providers (Ethereum / IPFS / Arweave) are intentionally **not**
shipped as silent stubs (PR #18 shipped ones whose verify() always returned
False). They are represented by :class:`UnavailableAnchorProvider`, which raises
with a clear message and a pointer to the docs -- and a blunt privacy warning,
because publishing to a public chain is *permanent publication* and, done
naively (a funded wallet, a logged RPC endpoint), can deanonymise a source.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime

from src.custody.timestamp import (
    OTS_AVAILABLE,
    TimestampProof,
    TimestampUnavailable,
    ots_info,
    ots_stamp,
)

PRIVACY_WARNING = (
    "Anchoring to a PUBLIC blockchain is permanent publication of a hash + timestamp. "
    "If you also expose a funded wallet address or an un-proxied network connection, "
    "this can correlate to your identity. For a source needing anonymity, prefer the "
    "local + OpenTimestamps providers and route traffic through Tor."
)


class AnchorError(RuntimeError):
    pass


class AnchorUnavailable(AnchorError):
    """The provider cannot anchor here (not implemented / offline / not configured)."""


@dataclass
class AnchorReceipt:
    provider: str
    merkle_root: str
    created_at: str
    locator: str | None  # provider-specific id/proof (e.g. base64 .ots, tx hash)
    detail: str

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "merkle_root": self.merkle_root,
            "created_at": self.created_at,
            "locator": self.locator,
            "detail": self.detail,
        }


class AnchorProvider(ABC):
    name: str = "abstract"

    @abstractmethod
    def anchor(self, merkle_root: str, metadata: dict | None = None) -> AnchorReceipt: ...

    @abstractmethod
    def verify(self, receipt: AnchorReceipt) -> tuple[bool, str]: ...


# --------------------------------------------------------------------------- #
# Local anchor book (offline, default)
# --------------------------------------------------------------------------- #


class LocalAnchorProvider(AnchorProvider):
    name = "local"

    def __init__(self, db_path: str | None = None):
        if db_path is None:
            from src.paths import data_dir

            db_path = str(data_dir() / "anchors.db")
        self.db_path = db_path
        # Audit finding 2026-07-17 (L1): a raw sqlite3.connect() always created the
        # anchor book UNENCRYPTED regardless of the main corpus's own encryption
        # setting -- even though it carries caller-supplied custody metadata. Use
        # the ONE connection factory instead, mirroring CustodyLog's exact
        # precedent (src/custody/log.py) for its sibling custody_log.db: opens
        # encrypted under THE SAME passphrase when the corpus is encrypted +
        # unlocked; a FRESH anchor book follows the main store's own at-rest
        # state, so a plaintext-opt-out setup never hits a lock on first use.
        from src.database.connect import connect as _db_connect
        from src.database.connect import get_passphrase, is_encrypted_file

        create_enc: bool | None = None
        if get_passphrase() is None:
            from src.paths import data_dir as _dd

            if is_encrypted_file(_dd() / "open_omniscience.db") is False:
                create_enc = False
        self.conn = _db_connect(db_path, create_encrypted=create_enc)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS anchors (
                merkle_root TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def anchor(self, merkle_root: str, metadata: dict | None = None) -> AnchorReceipt:
        created = datetime.now(UTC).isoformat()
        self.conn.execute(
            "INSERT OR IGNORE INTO anchors (merkle_root, created_at, metadata_json) VALUES (?, ?, ?)",
            (merkle_root, created, json.dumps(metadata or {}, sort_keys=True)),
        )
        self.conn.commit()
        return AnchorReceipt(
            provider=self.name,
            merkle_root=merkle_root,
            created_at=created,
            locator=None,
            detail="Recorded in the local anchor book. Proves this tool stored the "
            "root locally; NOT independent third-party proof.",
        )

    def verify(self, receipt: AnchorReceipt) -> tuple[bool, str]:
        row = self.conn.execute(
            "SELECT created_at FROM anchors WHERE merkle_root = ?", (receipt.merkle_root,)
        ).fetchone()
        if not row:
            return False, "merkle root not present in the local anchor book"
        return True, f"present in local anchor book since {row[0]} (local-only evidence)"

    def close(self) -> None:
        self.conn.close()


# --------------------------------------------------------------------------- #
# OpenTimestamps anchor (Bitcoin, independent; network required)
# --------------------------------------------------------------------------- #


class OpenTimestampsAnchorProvider(AnchorProvider):
    name = "opentimestamps"

    def anchor(self, merkle_root: str, metadata: dict | None = None) -> AnchorReceipt:
        try:
            digest = bytes.fromhex(merkle_root)
        except ValueError as exc:
            raise AnchorError(f"merkle_root must be hex: {exc}") from exc
        try:
            proof: TimestampProof = ots_stamp(digest)
        except TimestampUnavailable as exc:
            raise AnchorUnavailable(str(exc)) from exc
        return AnchorReceipt(
            provider=self.name,
            merkle_root=merkle_root,
            created_at=datetime.now(UTC).isoformat(),
            locator=proof.proof_b64,
            detail=proof.detail,
        )

    def verify(self, receipt: AnchorReceipt) -> tuple[bool, str]:
        if not receipt.locator:
            return False, "no OpenTimestamps proof attached"
        if not OTS_AVAILABLE:
            return False, "cannot verify: OpenTimestamps not installed (install 'timestamping')"
        proof = TimestampProof(
            kind="opentimestamps",
            digest=receipt.merkle_root,
            asserted_time=None,
            proof_b64=receipt.locator,
            detail="",
        )
        info = ots_info(proof)
        if not info["matches_claim"]:
            return False, "proof digest does not match the receipt's merkle root"
        if info["confirmed"]:
            return True, f"confirmed in Bitcoin block(s) {info['bitcoin_block_heights']}"
        return True, (
            "pending Bitcoin confirmation; accepted by "
            f"{len(info['pending_calendars'])} calendar(s). Upgrade the proof later "
            "for a block-anchored result."
        )


# --------------------------------------------------------------------------- #
# Public-chain providers -- declared, not faked
# --------------------------------------------------------------------------- #


class UnavailableAnchorProvider(AnchorProvider):
    """A named-but-unimplemented public-chain provider that refuses honestly."""

    def __init__(self, name: str):
        self.name = name

    def anchor(self, merkle_root: str, metadata: dict | None = None) -> AnchorReceipt:
        raise AnchorUnavailable(
            f"The {self.name!r} anchor provider is not implemented in this build. "
            "See docs/USER_MANUAL.md for how to add it. " + PRIVACY_WARNING
        )

    def verify(self, receipt: AnchorReceipt) -> tuple[bool, str]:
        return False, f"{self.name!r} provider unavailable; cannot verify"


_PUBLIC_CHAIN_NAMES = ("ethereum", "ipfs", "arweave")


def available_providers() -> dict[str, str]:
    """Map provider name -> short status, for honest UI/listing."""
    return {
        "local": "available (offline; local-only evidence)",
        "opentimestamps": (
            "available (Bitcoin-anchored, network required)"
            if OTS_AVAILABLE
            else "needs the 'timestamping' extra"
        ),
        **dict.fromkeys(
            _PUBLIC_CHAIN_NAMES,
            "not implemented (see docs); public-chain anchoring has privacy risks",
        ),
    }


def get_provider(name: str, **kwargs) -> AnchorProvider:
    """Factory. Unknown/public-chain names yield an honest, refusing provider."""
    if name == "local":
        return LocalAnchorProvider(**kwargs)
    if name == "opentimestamps":
        return OpenTimestampsAnchorProvider()
    if name in _PUBLIC_CHAIN_NAMES:
        return UnavailableAnchorProvider(name)
    raise AnchorError(f"unknown anchor provider: {name!r}")
