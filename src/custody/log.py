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
from collections.abc import Iterable
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
from src.monitoring.secret_scrub import record_text

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

        EXCEPT WHEN THE FAILURE WAS A STOP (R618). A submission the network kill switch refused or cut -- ``ots_stamp``'s own refusal,
        by type, whatever the switch reads now; engaged now; or pressed and cleared again since the epoch taken before it (R614) -- says
        nothing about the calendars, and a local proof written in its place is permanent: the log is append-only, so that entry could
        never carry an independent anchor. So nothing is written: the refusal is raised (``TimestampRefusedOffline``, a
        ``TimestampUnavailable`` naming the switch, ``ENTRY_REFUSED_OFFLINE``) before the entry is inserted. Ingestion is still never broken: its auto-log is fail-open and queues the entry as owed
        (``src.custody.pending``), and the drain at the end of a later collection pass writes it, marked late, with the anchor this mode
        asks for. A direct caller is told why. Only a submission that could have been made: with OpenTimestamps not installed the switch
        is not why it failed, and the local proof below is written as before. The cost: a genuine calendar failure that shares its
        window with a Stop is asked again. And the repayment is slow: the owed queue has no size limit, and the end of each collection
        pass writes at most ``DRAIN_PER_PASS`` (200) of it, each entry with up to three calendar submissions (``DEFAULT_CALENDARS``,
        10 s timeout each) made while ``_APPEND_LOCK`` is held, so a large backlog slows the end of collection passes for a while once
        the switch is cleared.
        """
        if self.anchoring_mode == "opentimestamps":
            from src.custody import timestamp as _timestamp
            from src.ingest import kill_switch_engaged_since, kill_switch_epoch

            epoch = kill_switch_epoch()  # before the submission and its own kill-switch check (R618, R614)
            try:
                return ots_stamp(digest)
            except TimestampUnavailable as exc:
                # The switch's refusal BY TYPE (``ots_stamp``'s own check: a switch engaged before the epoch was taken and cleared
                # before this read moves neither), or a Stop the epoch saw (a cut submission, or one pressed and cleared again).
                if isinstance(exc, _timestamp.TimestampRefusedOffline) or (
                    _timestamp.OTS_AVAILABLE and kill_switch_engaged_since(epoch)
                ):
                    raise _timestamp.TimestampRefusedOffline(_timestamp.ENTRY_REFUSED_OFFLINE) from None
                proof = local_timestamp(digest)
                proof.detail = (
                    "OpenTimestamps was requested but unavailable (" + record_text(exc) + "); "
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
        head = _bundle_head(item_id, entries)
        return {
            "log_version": LOG_VERSION,
            "item_id": item_id,
            "signer": ident.to_dict(),
            "entry_count": len(entries),
            # Signed at export: how many entries this bundle holds and which one is last, so a bundle cut at its end
            # (the one cut the chain links cannot show, since every remaining link still holds) is refused by name.
            "head": head,
            "head_signature": self.signer.sign(canonical_bytes(head)),
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


def _bundle_head(item_id: str | None, entries: list[CustodyEntry]) -> dict:
    """The part of an export its signer commits to: the bundle's scope, its size and its last entry."""
    last = entries[-1] if entries else None
    return {
        "log_version": LOG_VERSION,
        "item_id": item_id,
        "entry_count": len(entries),
        "last_seq": last.seq if last else None,
        "last_entry_hash": last.entry_hash if last else None,
    }


def verify_entries(
    entries: Iterable[CustodyEntry],
    *,
    pinned: PublicIdentity | None = None,
    max_issues: int | None = None,
    chained: bool = True,
) -> tuple[bool, list[str]]:
    """Re-validate custody entries: hashes, chain links, and signatures.

    Returns ``(ok, issues)``. ``issues`` is empty iff every check passes. Pass
    ``pinned`` to additionally require that every entry was signed by that exact
    public identity (proving provenance, not merely internal consistency).

    ``entries`` may be any iterable and is walked once, so a caller holding a chain of
    millions of entries can stream it instead of building the list (a restore's custody
    import did, and ran a 7 GB machine out of memory, 2026-09-27). ``max_issues`` keeps
    the first N issues and ends the list with a count of the rest, so a chain broken
    near its start cannot grow a list as long as itself; ``ok`` still counts every one.

    ``chained=False`` is for a ONE-ITEM export: its entries are a selection from the whole log, so their seqs skip and
    their ``prev_entry_hash`` points at entries of other items. Each entry's hash, signature and timestamp proof are
    still checked, and the seqs must rise; the links between them cannot be, and the caller says so.
    """
    issues: list[str] = []
    dropped = 0

    def _issue(msg: str) -> None:
        nonlocal dropped
        if max_issues is not None and len(issues) >= max_issues:
            dropped += 1
        else:
            issues.append(msg)

    expected_prev = GENESIS_PREV
    expected_seq = 1
    last_seq = 0
    for e in entries:
        if not chained:
            if e.seq <= last_seq:
                _issue(f"seq reorder at entry {e.seq} (after {last_seq})")
            last_seq = e.seq
        elif e.seq != expected_seq:
            _issue(f"seq gap/reorder at entry {e.seq} (expected {expected_seq})")
        if chained and e.prev_entry_hash != expected_prev:
            _issue(
                f"broken chain at seq {e.seq}: prev_entry_hash does not match the "
                "previous entry (an entry was altered, inserted, or removed)"
            )
        recomputed = _entry_digest(e.signable_core())
        if recomputed != e.entry_hash:
            _issue(f"entry_hash mismatch at seq {e.seq} (entry contents altered)")
        # Signature covers the full core (including the entry's timestamp proof).
        ok, reason = signing.verify(
            e.signature, canonical_bytes({**e.signable_core()}), pinned=pinned
        )
        if not ok:
            _issue(f"signature invalid at seq {e.seq}: {reason}")
        # The timestamp proof must be over this entry's pre-timestamp digest.
        if e.timestamp.get("digest"):
            partial = {k: v for k, v in e.signable_core().items() if k != "timestamp"}
            if e.timestamp["digest"] != sha256(canonical_bytes(partial)).hex():
                _issue(f"timestamp digest does not match entry at seq {e.seq}")
        expected_prev = e.entry_hash
        expected_seq += 1
    if dropped:
        issues.append(f"... and {dropped} more issue(s) not listed")
    return (not issues), issues


#: Said beside a one-item verdict, so "verified" is never read as the whole log's.
ITEM_SCOPE_NOTE = (
    "one item's entries: each entry's hash, signature and timestamp were checked and their order, but not the links "
    "between them, which run through other items' entries"
)


def verify_export(bundle: dict, *, require_signer: bool = False) -> tuple[bool, list[str]]:
    """Verify an exported custody bundle (offline, no DB). FAILS CLOSED.

    Refused by name, before any entry is judged: a bundle with no entries; an entry that is not a whole record (a file
    cut mid-record leaves one with fields missing); a bundle with no signed head (it cannot show that nothing was cut
    from its end, since every remaining link still holds -- re-export it from the app); a head whose signature does not
    verify; and a bundle whose entries do not match its head (fewer or more than it says, or a different last entry).
    The head must be signed by the key that signed the entries, so cutting the log and rewriting the head needs that
    key. What it cannot show: a log cut BEFORE it was exported (the head commits to what was exported, not to what the
    store once held) -- the full log's chain shows a cut at its start or middle, and a one-item export shows neither.

    A one-item bundle (``item_id`` set) is checked entry by entry (see ``verify_entries``' ``chained``).

    If ``require_signer`` is true, pin verification to the signer identity embedded in the bundle -- i.e. require that
    all entries and the head were signed by that identity. (Pinning to a *bundle-embedded* key only proves internal
    consistency; to prove provenance against a *known* signer, compare ``bundle['signer']`` to the signer's
    independently-known public identity first.)
    """
    if not isinstance(bundle, dict):
        return False, ["not a custody bundle (not a JSON object)"]
    raw = bundle.get("entries")
    if not isinstance(raw, list) or not raw:
        return False, ["empty log: the bundle holds no custody entries, so there is nothing to verify"]
    entries: list[CustodyEntry] = []
    for i, d in enumerate(raw, start=1):
        try:
            if not isinstance(d, dict):
                raise TypeError("not an object")
            entries.append(CustodyEntry.from_dict(d))
        except (KeyError, TypeError, ValueError) as exc:
            return False, [
                f"entry {i} of {len(raw)} is not a whole record ({record_text(exc)}); "
                "a log cut mid-record ends like this"
            ]
    pinned = None
    if require_signer and bundle.get("signer"):
        s = bundle["signer"]
        pinned = PublicIdentity(
            ed25519_pub=s["ed25519_pub"],
            ml_dsa_variant=s.get("ml_dsa_variant"),
            ml_dsa_pub=s.get("ml_dsa_pub"),
        )
    head, head_sig = bundle.get("head"), bundle.get("head_signature")
    if not isinstance(head, dict) or not isinstance(head_sig, dict):
        return False, [
            "no signed head: this bundle cannot show that nothing was cut from its end "
            "(exports before this check carried none; export it again from the app)"
        ]
    # The head must be signed by the key that signed the entries: a head re-signed with any other key would let whoever
    # cut the log vouch for the cut. Pinned to the first entry's own keys when no signer is pinned.
    first = entries[0].signature if isinstance(entries[0].signature, dict) else {}
    head_pin = pinned or PublicIdentity(
        ed25519_pub=(first.get("ed25519") or {}).get("pub", ""),
        ml_dsa_variant=(first.get("ml_dsa") or {}).get("variant"),
        ml_dsa_pub=(first.get("ml_dsa") or {}).get("pub"),
    )
    ok, reason = signing.verify(head_sig, canonical_bytes(head), pinned=head_pin)
    if not ok:
        return False, [f"head signature invalid: {reason}"]
    item_id = bundle.get("item_id")
    expected = _bundle_head(item_id, entries)
    if head != expected:
        if head.get("entry_count") != len(entries):
            return False, [
                f"truncated or padded: the signed head says {head.get('entry_count')} entries, the bundle holds {len(entries)}"
            ]
        return False, ["the bundle's entries do not match its signed head (a different last entry, scope or version)"]
    if item_id and any(e.item_id != item_id for e in entries):
        return False, [f"the bundle is for {item_id!r} but holds entries of other items"]
    return verify_entries(entries, pinned=pinned, chained=not item_id)
