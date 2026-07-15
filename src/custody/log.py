"""
Append-only, hash-chained, signed chain-of-custody log.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every meaningful action on an item (ingest, access, export, redact, ...) is
recorded as a custody entry that is:

* **chained** -- each entry stores the hash of the previous entry, so removing,
  reordering, or editing any *interior* entry is detectable; detecting truncation
  of the most recent entries additionally requires an external anchor
  (OpenTimestamps, below) -- a hash chain alone cannot prove nothing was dropped
  from its tail;
* **signed** -- each entry is signed with Ed25519 (plus post-quantum ML-DSA when
  the optional ``[pqc]`` extra is installed and enabled), so entries cannot be
  forged or altered without the signing key;
* **timestamped** -- each entry carries a timestamp proof (self-asserted local by
  default; optionally an independent OpenTimestamps anchor).

The log is *append-only on the live path*: there is no update or delete method.
Verification is fully offline and self-contained -- :func:`verify_export` needs
only an exported bundle and (optionally) the signer's pinned public identity, not
this database or the running app.

This is the honest realisation of PR #18's "Chain of Custody": same intent, but
with no fake timestamps, no OR-semantics signatures, and reusing the audited
crypto already in the tree.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from enum import Enum

from src.custody import signing
from src.custody.signing import HybridSigner, PublicIdentity, canonical_bytes
from src.custody.timestamp import (
    TimestampProof,
    TimestampUnavailable,
    local_timestamp,
    ots_stamp,
    sha256,
)

GENESIS_PREV = "0" * 64
LOG_VERSION = "oo-custody-1"

# PROCESS-WIDE append lock (field report 2026-07-02: 34 `UNIQUE constraint failed:
# custody_entries.seq` under 50-way parallel ingest with auto-log-on-ingest default-on).
# Each caller opens its OWN CustodyLog()/connection, so a per-instance lock cannot
# serialise them — and record() is a READ-CHAIN-INSERT (read the last entry for its hash,
# chain a new hash to it, insert the next seq): two concurrent appends both read the same
# tail, compute the same seq + prev_hash, and collide on the unique seq / FORK the hash
# chain. This module-level lock serialises every custody append in the process so the
# chain stays single-threaded and gap-free. Custody is a headline integrity guarantee; a
# dropped/forked entry is not acceptable.
_APPEND_LOCK = threading.RLock()


class CustodyAction(str, Enum):
    INGEST = "ingest"
    ACCESS = "access"
    EXPORT = "export"
    VERIFY = "verify"
    ANNOTATE = "annotate"
    REDACT = "redact"
    DELETE = "delete"
    ANCHOR = "anchor"


def _entry_digest(core: dict) -> str:
    """Hash of the entry's signable core (everything except signature/entry_hash)."""
    return sha256(canonical_bytes(core)).hex()


@dataclass
class CustodyEntry:
    seq: int
    item_id: str
    item_hash: str
    action: str
    actor: str | None
    metadata: dict
    prev_entry_hash: str
    entry_hash: str
    signature: dict
    timestamp: dict  # TimestampProof.to_dict()

    def signable_core(self) -> dict:
        """The deterministic payload that entry_hash is computed over and signed."""
        return {
            "version": LOG_VERSION,
            "seq": self.seq,
            "item_id": self.item_id,
            "item_hash": self.item_hash,
            "action": self.action,
            "actor": self.actor,
            "metadata": self.metadata,
            "prev_entry_hash": self.prev_entry_hash,
            "timestamp": self.timestamp,
        }

    def to_dict(self) -> dict:
        d = self.signable_core()
        d["entry_hash"] = self.entry_hash
        d["signature"] = self.signature
        return d

    @classmethod
    def from_dict(cls, d: dict) -> CustodyEntry:
        return cls(
            seq=d["seq"],
            item_id=d["item_id"],
            item_hash=d["item_hash"],
            action=d["action"],
            actor=d.get("actor"),
            metadata=d.get("metadata", {}),
            prev_entry_hash=d["prev_entry_hash"],
            entry_hash=d["entry_hash"],
            signature=d["signature"],
            timestamp=d["timestamp"],
        )


class CustodyLog:
    """SQLite-backed append-only custody log."""

    def __init__(
        self,
        db_path: str | None = None,
        signer: HybridSigner | None = None,
        anchoring_mode: str | None = None,
    ):
        if db_path is None:
            from src.paths import data_dir

            db_path = str(data_dir() / "custody_log.db")
        self.db_path = db_path
        # Honour the operator's GUI-configured preferences when not overridden.
        # The signer's PQC use and the default anchoring mode both come from the
        # persisted custody settings unless explicitly passed in (tests / callers).
        if signer is None or anchoring_mode is None:
            from src.custody.settings import load_settings

            prefs = load_settings()
            if signer is None:
                signer = HybridSigner(use_pqc=prefs.pqc_enabled)
            if anchoring_mode is None:
                anchoring_mode = prefs.anchoring_mode
        self.signer = signer
        self.anchoring_mode = anchoring_mode
        # The one connection factory: opens encrypted custody logs with THE
        # passphrase (D6 -- one secret covers both stores), plaintext ones as
        # before. A FRESH custody log follows the main store's at-rest state,
        # so a plaintext-opt-out setup never hits a lock on first custody use.
        from src.database.connect import connect as _db_connect
        from src.database.connect import get_passphrase, is_encrypted_file

        create_enc: bool | None = None
        if get_passphrase() is None:
            from src.paths import data_dir as _dd

            if is_encrypted_file(_dd() / "open_omniscience.db") is False:
                create_enc = False
        self.conn = _db_connect(self.db_path, create_encrypted=create_enc)
        # Under concurrent ingest (the field's 50-way parallel case) many CustodyLog
        # instances open the SAME file at once. Two hardening steps make that reliable:
        # (1) an explicit busy_timeout so a writer WAITS for the lock instead of raising
        # "database is locked" immediately (belt-and-suspenders on the DBAPI timeout);
        # (2) NO per-open WAL journal-mode transition. Every write already serialises on
        # the process-wide append lock (_APPEND_LOCK), so WAL buys no concurrency here —
        # while 40 connections opening WAL + auto-checkpointing on every commit created a
        # lock storm (each commit could block on another connection's read mark and wait
        # out the busy_timeout, turning a ~3s job into ~150s). The default rollback
        # journal + the append lock + busy_timeout is both correct and fast: writes are
        # serialised, reads (export/verify) wait briefly rather than error. The DDL init
        # runs under the append lock so concurrent opens don't race CREATE-TABLE.
        try:
            self.conn.execute("PRAGMA busy_timeout=30000")
        except Exception:  # noqa: BLE001 - the DBAPI timeout still applies
            pass
        with _APPEND_LOCK:
            self._init_db()

    def _init_db(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custody_entries (
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                item_id TEXT NOT NULL,
                item_hash TEXT NOT NULL,
                action TEXT NOT NULL,
                actor TEXT,
                metadata_json TEXT NOT NULL,
                prev_entry_hash TEXT NOT NULL,
                entry_hash TEXT NOT NULL UNIQUE,
                signature_json TEXT NOT NULL,
                timestamp_json TEXT NOT NULL
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_custody_item ON custody_entries(item_id)")
        self.conn.commit()

    # -- write ------------------------------------------------------------- #
    def _last(self) -> CustodyEntry | None:
        row = self.conn.execute(
            "SELECT * FROM custody_entries ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return self._row_to_entry(row) if row else None

    def record(
        self,
        item_id: str,
        item_hash: str,
        action: CustodyAction | str,
        *,
        actor: str | None = None,
        metadata: dict | None = None,
        timestamp: TimestampProof | None = None,
    ) -> CustodyEntry:
        """Append a signed, chained custody entry and return it.

        ``timestamp`` defaults to a local (self-asserted) proof over the entry
        digest. Pass an OpenTimestamps proof to anchor the entry independently.
        """
        action_val = action.value if isinstance(action, CustodyAction) else str(action)
        meta = metadata or {}
        # Serialise the whole READ-CHAIN-INSERT so concurrent ingest workers can never
        # read the same tail, compute the same seq, and collide / fork the chain.
        with _APPEND_LOCK:
            prev = self._last()
            prev_hash = prev.entry_hash if prev else GENESIS_PREV
            seq = (prev.seq + 1) if prev else 1

            # Build the signable core, hash it, timestamp that digest, then re-hash so
            # the timestamp is itself covered by entry_hash + signature.
            partial = {
                "version": LOG_VERSION,
                "seq": seq,
                "item_id": item_id,
                "item_hash": item_hash,
                "action": action_val,
                "actor": actor,
                "metadata": meta,
                "prev_entry_hash": prev_hash,
            }
            digest = sha256(canonical_bytes(partial))
            ts = (timestamp or self._default_timestamp(digest)).to_dict()
            core = {**partial, "timestamp": ts}
            entry_hash = _entry_digest(core)
            sig = self.signer.sign(canonical_bytes(core))

            self.conn.execute(
                """
                INSERT INTO custody_entries
                    (seq, item_id, item_hash, action, actor, metadata_json,
                     prev_entry_hash, entry_hash, signature_json, timestamp_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    seq,
                    item_id,
                    item_hash,
                    action_val,
                    actor,
                    json.dumps(meta, sort_keys=True),
                    prev_hash,
                    entry_hash,
                    json.dumps(sig),
                    json.dumps(ts),
                ),
            )
            self.conn.commit()
        return CustodyEntry(
            seq=seq,
            item_id=item_id,
            item_hash=item_hash,
            action=action_val,
            actor=actor,
            metadata=meta,
            prev_entry_hash=prev_hash,
            entry_hash=entry_hash,
            signature=sig,
            timestamp=ts,
        )

    def _default_timestamp(self, digest: bytes) -> TimestampProof:
        """Pick the timestamp proof for a new entry per the configured anchoring mode.

        ``local`` (default) is offline and always available. ``opentimestamps``
        attempts an independent Bitcoin-anchored proof; if that is unavailable
        (library missing / offline) we fall back to a local proof whose ``detail``
        says so plainly -- we never fabricate an OTS proof, and ingestion is never
        broken by an unreachable calendar.
        """
        if self.anchoring_mode == "opentimestamps":
            try:
                return ots_stamp(digest)
            except TimestampUnavailable as exc:
                proof = local_timestamp(digest)
                proof.detail = (
                    "OpenTimestamps was requested but unavailable (" + str(exc) + "); "
                    "recorded a local self-asserted time instead. NOT independent "
                    "third-party proof."
                )
                return proof
        return local_timestamp(digest)

    # -- read -------------------------------------------------------------- #
    @staticmethod
    def _row_to_entry(row) -> CustodyEntry:
        return CustodyEntry(
            seq=row[0],
            item_id=row[1],
            item_hash=row[2],
            action=row[3],
            actor=row[4],
            metadata=json.loads(row[5]),
            prev_entry_hash=row[6],
            entry_hash=row[7],
            signature=json.loads(row[8]),
            timestamp=json.loads(row[9]),
        )

    def all_entries(self) -> list[CustodyEntry]:
        rows = self.conn.execute("SELECT * FROM custody_entries ORDER BY seq ASC").fetchall()
        return [self._row_to_entry(r) for r in rows]

    def entries_for(self, item_id: str) -> list[CustodyEntry]:
        rows = self.conn.execute(
            "SELECT * FROM custody_entries WHERE item_id = ? ORDER BY seq ASC",
            (item_id,),
        ).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def export(self, item_id: str | None = None) -> dict:
        """Produce an offline-verifiable bundle of entries + the signer identity."""
        entries = self.entries_for(item_id) if item_id else self.all_entries()
        ident = self.signer.public_identity()
        return {
            "log_version": LOG_VERSION,
            "item_id": item_id,
            "signer": ident.to_dict(),
            "entry_count": len(entries),
            "entries": [e.to_dict() for e in entries],
        }

    def verify(self) -> tuple[bool, list[str]]:
        """Verify the full chain held in this database (see :func:`verify_entries`)."""
        return verify_entries(self.all_entries())

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# --------------------------------------------------------------------------- #
# Stateless verification -- needs only the entries (and optionally a pinned key)
# --------------------------------------------------------------------------- #


def verify_entries(
    entries: list[CustodyEntry],
    *,
    pinned: PublicIdentity | None = None,
) -> tuple[bool, list[str]]:
    """Re-validate a list of custody entries: hashes, chain links, and signatures.

    Returns ``(ok, issues)``. ``issues`` is empty iff every check passes. Pass
    ``pinned`` to additionally require that every entry was signed by that exact
    public identity (proving provenance, not merely internal consistency).
    """
    issues: list[str] = []
    expected_prev = GENESIS_PREV
    expected_seq = 1
    for e in entries:
        if e.seq != expected_seq:
            issues.append(f"seq gap/reorder at entry {e.seq} (expected {expected_seq})")
        if e.prev_entry_hash != expected_prev:
            issues.append(
                f"broken chain at seq {e.seq}: prev_entry_hash does not match the "
                "previous entry (an entry was altered, inserted, or removed)"
            )
        recomputed = _entry_digest(e.signable_core())
        if recomputed != e.entry_hash:
            issues.append(f"entry_hash mismatch at seq {e.seq} (entry contents altered)")
        # Signature covers the full core (including the entry's timestamp proof).
        ok, reason = signing.verify(
            e.signature, canonical_bytes({**e.signable_core()}), pinned=pinned
        )
        if not ok:
            issues.append(f"signature invalid at seq {e.seq}: {reason}")
        # The timestamp proof must be over this entry's pre-timestamp digest.
        if e.timestamp.get("digest"):
            partial = {k: v for k, v in e.signable_core().items() if k != "timestamp"}
            if e.timestamp["digest"] != sha256(canonical_bytes(partial)).hex():
                issues.append(f"timestamp digest does not match entry at seq {e.seq}")
        expected_prev = e.entry_hash
        expected_seq += 1
    return (not issues), issues


def verify_export(bundle: dict, *, require_signer: bool = False) -> tuple[bool, list[str]]:
    """Verify an exported custody bundle (offline, no DB).

    If ``require_signer`` is true, pin verification to the signer identity embedded
    in the bundle -- i.e. require that all entries were signed by that identity.
    (Pinning to a *bundle-embedded* key only proves internal consistency; to prove
    provenance against a *known* signer, compare ``bundle['signer']`` to the
    signer's independently-known public identity first.)
    """
    entries = [CustodyEntry.from_dict(d) for d in bundle.get("entries", [])]
    pinned = None
    if require_signer and bundle.get("signer"):
        s = bundle["signer"]
        pinned = PublicIdentity(
            ed25519_pub=s["ed25519_pub"],
            ml_dsa_variant=s.get("ml_dsa_variant"),
            ml_dsa_pub=s.get("ml_dsa_pub"),
        )
    return verify_entries(entries, pinned=pinned)
