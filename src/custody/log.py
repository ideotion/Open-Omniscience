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
    KEY_ROTATION = "key_rotation"


#: The item a key-rotation record is filed under: it is about the log, not about an article.
ROTATION_ITEM = "custody:signing-key"


def rotation_payload(previous_ed25519_pub: str, identity: dict, prev_entry_hash: str) -> dict:
    """What the PREVIOUS key signs to endorse the next one: both keys and the place in the chain, so an endorsement
    cannot be lifted onto another log or another point of this one."""
    return {
        "kind": "oo-custody-key-rotation",
        "log_version": LOG_VERSION,
        "previous_ed25519_pub": previous_ed25519_pub,
        "ed25519_pub": identity.get("ed25519_pub"),
        "ml_dsa_variant": identity.get("ml_dsa_variant"),
        "ml_dsa_pub": identity.get("ml_dsa_pub"),
        "prev_entry_hash": prev_entry_hash,
    }


UNENDORSED_ROTATION_NOTE = (
    "The custody signing key changed and the previous key was not available on this machine to vouch for the new "
    "one, so nothing but this record links them. Entries after it are signed by the new key."
)


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
        if action_val == CustodyAction.KEY_ROTATION.value or item_id == ROTATION_ITEM:
            # Only this log writes its key-rotation records (``_insert_rotation``): one written from outside would name
            # keys of the caller's choosing, and every later export of the log would be refused for good.
            raise ValueError("key-rotation records are written by the custody log itself, never through record()")
        meta = metadata or {}
        # Serialise the whole READ-CHAIN-INSERT so concurrent ingest workers can never
        # read the same tail, compute the same seq, and collide / fork the chain.
        with _APPEND_LOCK:
            prev = self._last()
            if prev is not None and _sig_ed25519_pub(prev.signature) != self.signer.public_identity().ed25519_pub:
                # The key that signs now is not the one that signed the tail (keys re-created after a restore, or a
                # lost key folder): say so IN the chain before signing anything with it, so a reader can follow the
                # change instead of meeting an unexplained new key (R-rotation). Nobody here holds the old key.
                prev = self._insert_rotation(prev, previous_signer=None)
            return self._insert(prev, item_id, item_hash, action_val, actor, meta, timestamp)

    def rotate_signing_key(self, previous_signer: HybridSigner) -> CustodyEntry:
        """Record that this log's signer replaces ``previous_signer``, ENDORSED: the previous key signs the new key's
        identity and the chain position. Call it with the old key still at hand, before the new key signs anything.
        Raises ``ValueError`` when the tail was not signed by ``previous_signer`` (it cannot vouch for what it did not
        sign) or when the two keys are the same."""
        old_pub = previous_signer.public_identity().ed25519_pub
        with _APPEND_LOCK:
            prev = self._last()
            if prev is None:
                raise ValueError("the custody log is empty: there is no previous key to rotate from")
            if _sig_ed25519_pub(prev.signature) != old_pub:
                raise ValueError("the log's last entry was not signed by the previous key given")
            if old_pub == self.signer.public_identity().ed25519_pub:
                raise ValueError("the new signing key is the same as the previous one")
            return self._insert_rotation(prev, previous_signer=previous_signer)

    def _insert_rotation(self, prev: CustodyEntry, *, previous_signer: HybridSigner | None) -> CustodyEntry:
        """Append the key-rotation record (lock held). Signed by the NEW key; endorsed by the old one when it is given."""
        identity = self.signer.public_identity().to_dict()
        old_pub = _sig_ed25519_pub(prev.signature)
        payload = rotation_payload(old_pub, identity, prev.entry_hash)
        meta: dict = {
            "previous_ed25519_pub": old_pub,
            "ed25519_pub": identity.get("ed25519_pub"),
            "ml_dsa_variant": identity.get("ml_dsa_variant"),
            "ml_dsa_pub": identity.get("ml_dsa_pub"),
        }
        if previous_signer is not None:
            meta["endorsement"] = previous_signer.sign(canonical_bytes(payload))
            meta["note"] = "The previous custody signing key signed the new key's identity and this place in the chain."
        else:
            meta["endorsement"] = None
            meta["note"] = UNENDORSED_ROTATION_NOTE
        item_hash = sha256(canonical_bytes(payload)).hex()
        # A local time: the record must not wait on, or be refused by, a calendar submission.
        return self._insert(prev, ROTATION_ITEM, item_hash, CustodyAction.KEY_ROTATION.value, "custody", meta, None,
                            local_only=True)

    def _insert(self, prev: CustodyEntry | None, item_id: str, item_hash: str, action_val: str, actor: str | None,
                meta: dict, timestamp: TimestampProof | None, *, local_only: bool = False) -> CustodyEntry:
        """Sign and insert one entry after ``prev`` (``_APPEND_LOCK`` held by the caller)."""
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
        ts = (timestamp or (local_timestamp(digest) if local_only else self._default_timestamp(digest))).to_dict()
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
        if item_id and item_id != ROTATION_ITEM and entries:
            # The key-rotation records up to the item's last entry, so its key changes can be followed.
            rotations = [e for e in self.entries_for(ROTATION_ITEM) if e.seq < entries[-1].seq]
            entries = sorted(entries + rotations, key=lambda e: e.seq)
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
    pinned_by_seq: dict[int, PublicIdentity | None] | None = None,
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

    ``pinned_by_seq`` pins each entry to its own identity (``None`` = unpinned) in place of ``pinned``: a bundle that
    crosses a key rotation has one identity per stretch of the chain.
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
            e.signature, canonical_bytes({**e.signable_core()}),
            pinned=pinned_by_seq.get(e.seq) if pinned_by_seq is not None else pinned,
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
    "one item's entries: each entry's hash, signature and timestamp were checked, and that one key signed them all and "
    "their order, but not the links between them, which run through other items' entries"
)
WHOLE_LOG_SCOPE = (
    "the whole log, from its first entry to the last entry its signed head names, all signed by the bundle's signer "
    "key; compare that key with the real signer's to know who signed it"
)
#: The same two, for a bundle whose signing key changed: then not every entry carries the signer key.
ITEM_SCOPE_NOTE_ROTATED = (
    "one item's entries: each entry's hash, signature and timestamp were checked, and their order, but not the links "
    "between them, which run through other items' entries. The signing key changed at the key rotations named below; "
    "each entry carries the key in use at its place in the chain, and the last of those keys is the bundle's signer key"
)
WHOLE_LOG_SCOPE_ROTATED = (
    "the whole log, from its first entry to the last entry its signed head names. The signing key changed at the key "
    "rotations named below and ends on the bundle's signer key; compare that key with the real signer's to know who "
    "signed the entries after the last rotation, and read each rotation's note for how the keys before it are linked"
)


def scope_note(bundle: dict, notes: list[str]) -> str:
    """What a "verified" covers for ``bundle``, given the rotation ``notes`` its verification returned."""
    if bundle.get("item_id"):
        return ITEM_SCOPE_NOTE_ROTATED if notes else ITEM_SCOPE_NOTE
    return WHOLE_LOG_SCOPE_ROTATED if notes else WHOLE_LOG_SCOPE


def _signature_shape_problem(sig: object) -> str | None:
    """Why a signature dict cannot be read, or None: checked before anything indexes into it."""
    if not isinstance(sig, dict):
        return "its signature is not an object"
    for part in ("ed25519", "ml_dsa"):
        if part in sig and not isinstance(sig[part], dict):
            return f"its signature's {part} part is not an object"
    if not isinstance(sig.get("ed25519"), dict):
        return "its signature has no ed25519 part"
    return None


def _entry_shape_problem(d: object) -> str | None:
    """Why a raw entry is not a whole record, or None. A file cut mid-record leaves one like this."""
    if not isinstance(d, dict):
        return "it is not an object"
    missing = [k for k in ("seq", "item_id", "item_hash", "action", "prev_entry_hash", "entry_hash", "signature",
                           "timestamp") if k not in d]
    if missing:
        return "it has no " + ", ".join(missing)
    if not isinstance(d["seq"], int) or isinstance(d["seq"], bool):
        return "its seq is not a whole number"
    for k in ("item_id", "item_hash", "action", "prev_entry_hash", "entry_hash"):
        if not isinstance(d[k], str):
            return f"its {k} is not text"
    if not isinstance(d["timestamp"], dict):
        return "its timestamp is not an object"
    if not isinstance(d.get("metadata", {}), dict):
        return "its metadata is not an object"
    return _signature_shape_problem(d["signature"])


def _key_lineage(entries: list[CustodyEntry], signer_key: str, accept_unendorsed: bool) -> tuple[str | None, list[str]]:
    """Walk the signing key through the entries. Returns ``(problem or None, notes)``; the key must end as
    ``signer_key``. See :func:`verify_export`'s WHICH KEY."""
    notes: list[str] = []
    first = entries[0]
    current = _sig_ed25519_pub(first.signature)
    if first.action == CustodyAction.KEY_ROTATION.value and first.item_id == ROTATION_ITEM:
        # A one-item bundle starts at the earliest rotation before its item's first entry, so no entry in it was signed
        # by the key that rotation replaces: the record's own word names that key. Its endorsement, when there is one,
        # is still checked against it below, and the walk must still end on the signer key.
        named = first.metadata.get("previous_ed25519_pub")
        current = named if isinstance(named, str) else current
    for e in entries:
        k = _sig_ed25519_pub(e.signature)
        if e.action == CustodyAction.KEY_ROTATION.value and e.item_id == ROTATION_ITEM:
            md = e.metadata
            prev_k, new_k = md.get("previous_ed25519_pub"), md.get("ed25519_pub")
            if not isinstance(prev_k, str) or not isinstance(new_k, str) or not new_k or prev_k == new_k:
                return f"the key-rotation record at seq {e.seq} does not name two different keys", notes
            if prev_k != current:
                return (f"the key-rotation record at seq {e.seq} names a previous key that did not sign the entries "
                        "before it"), notes
            if k != new_k:
                return f"the key-rotation record at seq {e.seq} is not signed by the key it introduces", notes
            endorsement = md.get("endorsement")
            if endorsement is None:
                if not accept_unendorsed:
                    return (f"the signing key changes at seq {e.seq} with no endorsement by the previous key: its record "
                            "says the previous key was not available, and a forged tail would say the same. Verify "
                            "again accepting an unendorsed rotation only if you know the key was re-created"), notes
                notes.append(f"seq {e.seq}: accepted on the record's word: {UNENDORSED_ROTATION_NOTE}")
            else:
                problem = _signature_shape_problem(endorsement)
                if problem or _sig_ed25519_pub(endorsement) != prev_k:
                    return f"the key-rotation record at seq {e.seq} carries an endorsement not made by the previous key", notes
                identity = {"ed25519_pub": new_k, "ml_dsa_variant": md.get("ml_dsa_variant"),
                            "ml_dsa_pub": md.get("ml_dsa_pub")}
                ok, reason = signing.verify(endorsement, canonical_bytes(rotation_payload(prev_k, identity,
                                                                                          e.prev_entry_hash)))
                if not ok:
                    return f"the key-rotation record at seq {e.seq} has an invalid endorsement: {reason}", notes
                notes.append(f"seq {e.seq}: the signing key changed, endorsed by the previous key")
            current = new_k
        elif k != current:
            return (f"the signing key changes at seq {e.seq} with no key-rotation record: a re-created key and a forged "
                    "tail read the same here, so neither is verified"), notes
    if current != signer_key:
        return "the entries end on a different key from the bundle's signer key", notes
    return None, notes


def _segment_pins(entries: list[CustodyEntry], signer: PublicIdentity) -> dict[int, PublicIdentity | None]:
    """The identity each entry is pinned to when a bundle crosses key rotations (see ``_verify_export``)."""
    rotations = [i for i, e in enumerate(entries)
                 if e.action == CustodyAction.KEY_ROTATION.value and e.item_id == ROTATION_ITEM]
    last = rotations[-1] if rotations else len(entries)
    pins: dict[int, PublicIdentity | None] = {}
    current: PublicIdentity | None = None
    for i, e in enumerate(entries):
        if i >= last:
            pins[e.seq] = signer
            continue
        if i in rotations:
            md = e.metadata
            ml = md.get("ml_dsa_pub")
            current = PublicIdentity(ed25519_pub=str(md.get("ed25519_pub")), ml_dsa_variant=md.get("ml_dsa_variant"),
                                     ml_dsa_pub=ml) if isinstance(ml, str) and ml else None
        pins[e.seq] = current
    return pins


def _sig_ed25519_pub(sig: dict) -> str:
    return str((sig.get("ed25519") or {}).get("pub") or "")


def verify_export(
    bundle: dict, *, require_signer: bool = False, accept_unendorsed_rotation: bool = False
) -> tuple[bool, list[str]]:
    """``(ok, issues)`` of :func:`verify_export_report`."""
    report = verify_export_report(
        bundle, require_signer=require_signer, accept_unendorsed_rotation=accept_unendorsed_rotation
    )
    return report["verified"], report["issues"]


def verify_export_report(
    bundle: dict, *, require_signer: bool = False, accept_unendorsed_rotation: bool = False
) -> dict:
    """``{"verified", "issues", "notes"}`` for an exported bundle; ``notes`` names every key rotation crossed."""
    notes: list[str] = []
    ok, issues = _verify_export(bundle, require_signer, accept_unendorsed_rotation, notes)
    return {"verified": ok, "issues": issues, "notes": notes if ok else []}


def _verify_export(
    bundle: dict, require_signer: bool, accept_unendorsed_rotation: bool, notes: list[str]
) -> tuple[bool, list[str]]:
    """Verify an exported custody bundle (offline, no DB). FAILS CLOSED.

    Refused by name, before any entry is judged: a bundle with no entries; an entry that is not a whole record (a file
    cut mid-record leaves one with fields missing or of the wrong kind); a bundle with no signed head (it cannot show
    that nothing was cut from its end, since every remaining link still holds -- the reason says to export it again);
    a head whose signature does not verify or was made with another key; and a bundle whose entries do not match its
    head (fewer or more than it says, or a different last entry).

    WHICH KEY. The head must carry the Ed25519 key the bundle names as its signer, and so must every entry, except
    across a KEY-ROTATION record (``rotate_signing_key`` / the record written when a re-created key first signs): there
    the key may change from the one that signed the entries before it to the one the record names, which signs it.
    An ENDORSED rotation (the previous key signed the new key and this place in the chain) passes and is named in the
    notes. An UNENDORSED one (the previous key was gone) is what a forged tail would also write, so it is refused unless
    the caller passes ``accept_unendorsed_rotation`` -- then it passes on that record's word, said in the notes. Any
    other key change is refused and its seq named. Only the Ed25519 half is compared, so a log whose signer gained the
    post-quantum half later still verifies; each signature is still verified in full. THIS PROVES CONSISTENCY, NOT
    PROVENANCE: anyone can build a whole bundle, head included, with a key of their own. A cut at the end is caught
    only when the signer key is compared with one the reader already knows to be the real signer's.

    What it cannot show: a log cut BEFORE it was exported (the head commits to what was exported, not to what the store
    once held) -- the full log's chain shows a cut at its start or middle, and a one-item export shows neither.

    If ``require_signer`` is true, pin verification to the signer identity embedded in the bundle -- i.e. require that
    the head and all entries were signed by that identity, ML-DSA half included. Across a key rotation each stretch of
    the chain is pinned to the identity that introduced it instead (see the end of this function); the stretch before
    the first rotation is held to its Ed25519 key only, the one identity the bundle names for it. (Pinning to a *bundle-embedded* key only proves internal
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
        problem = _entry_shape_problem(d)
        if problem:
            return False, [f"entry {i} of {len(raw)} is not a whole record ({problem}); a log cut mid-record ends like this"]
        entries.append(CustodyEntry.from_dict(d))  # type: ignore[arg-type]  # shape checked just above
    pinned = None
    if require_signer:
        s = bundle.get("signer")
        if not isinstance(s, dict) or not isinstance(s.get("ed25519_pub"), str):
            return False, ["no signer identity in the bundle to pin to"]
        pinned = PublicIdentity(
            ed25519_pub=s["ed25519_pub"],
            ml_dsa_variant=s.get("ml_dsa_variant"),
            ml_dsa_pub=s.get("ml_dsa_pub"),
        )
    head, head_sig = bundle.get("head"), bundle.get("head_signature")
    if not isinstance(head, dict) or head_sig is None:
        return False, [
            "no signed head: this bundle cannot show that nothing was cut from its end. Exports made before this check "
            "carried none: export it again from the app"
        ]
    problem = _signature_shape_problem(head_sig)
    if problem:
        return False, [f"head signature unreadable: {problem.replace('its signature', 'the head signature')}"]
    item_id = bundle.get("item_id")
    signer = bundle.get("signer")
    key = signer.get("ed25519_pub") if isinstance(signer, dict) else None
    if not isinstance(key, str) or not key:
        return False, ["no signer identity in the bundle: there is no key to hold its entries and head to"]
    if _sig_ed25519_pub(head_sig) != key:
        return False, ["head signature invalid: it was not made with the bundle's signer key"]
    problem, rotation_notes = _key_lineage(entries, key, accept_unendorsed_rotation)
    notes.extend(rotation_notes)
    if problem:
        return False, [problem]
    ok, reason = signing.verify(head_sig, canonical_bytes(head), pinned=pinned)
    if not ok:
        return False, [f"head signature invalid: {reason}"]
    expected = _bundle_head(item_id, entries)
    if head != expected:
        if head.get("entry_count") != len(entries):
            return False, [
                f"truncated or padded: the signed head says {head.get('entry_count')} entries, the bundle holds {len(entries)}"
            ]
        return False, ["the bundle's entries do not match its signed head (a different last entry, scope or version)"]
    if item_id and any(e.item_id not in (item_id, ROTATION_ITEM) for e in entries):
        return False, [f"the bundle is for {item_id!r} but holds entries of other items"]
    if pinned is None or not rotation_notes:
        return verify_entries(entries, pinned=pinned, chained=not item_id)
    # Across a rotation one pin cannot hold every entry: pinning them all to the LAST key would refuse those signed
    # before it. ``_key_lineage`` has held every entry's Ed25519 key to its stretch of the chain; here each stretch is
    # also pinned in full (its ML-DSA half too) to the identity that introduced it -- the stretch after the last rotation
    # to the bundle's signer, a middle stretch to its rotation record's identity when that names an ML-DSA key. The
    # stretch before the first rotation has no identity in the bundle beyond its Ed25519 key, which the lineage checked.
    return verify_entries(entries, pinned_by_seq=_segment_pins(entries, pinned), chained=not item_id)
