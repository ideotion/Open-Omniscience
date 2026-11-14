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
from src.custody.signing import HybridSigner, PostQuantumUnavailable, PublicIdentity, canonical_bytes
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
#: The export format (R714). Format 2's signed head commits to every entry hash in the bundle, so no entry can be
#: swapped, added or removed anywhere in it -- in a one-item bundle too, whose entries are not linked to each other.
#: A bundle whose signed head names no format is format 1 (development builds between the signed head and this
#: change): its head commits only to the count and the last entry. Exports are written in format 2 only; format 1 is still read, and said to be weaker.
BUNDLE_FORMAT = 2
LEGACY_FORMAT_NOTE = (
    "This bundle is in an older export format, which gives a weaker guarantee: its signed head commits "
    "only to how many entries it holds and to its last entry, not to each entry. In a one-item bundle, whose entries "
    "are not linked to each other, any entry but the last could be swapped for another entry signed by the same key, "
    "or one removed and another added in its place, without this check seeing it (a whole-log bundle's links still "
    "cover each entry). Export the bundle again from the app for the full check."
)

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


UNRECORDED_KEY_CHANGE_NOTE = (
    "the signing key changed here with no key-rotation record. A key re-created before this version wrote those records "
    "(before 0.5.1) leaves exactly this mark, and the append-only log cannot be given the record afterwards; a tail "
    "signed by someone else's key reads the same. An exported bundle is refused here."
)


def rotation_payload(previous_ed25519_pub: str, identity: dict, prev_entry_hash: str,
                     previous_ml_dsa: tuple[str | None, str | None] | None = None) -> dict:
    """What the PREVIOUS key signs to endorse the next one: both keys and the place in the chain, so an endorsement
    cannot be lifted onto another log or another point of this one.

    ``previous_ml_dsa`` is the previous identity's ``(variant, pub)`` -- ``(None, None)`` when it had no post-quantum
    half. Records written since 0.5.1 carry it (row 43): without it the endorsement bound only the previous Ed25519
    key, so its ML-DSA half could be anyone's. A record written before carries none, and its payload is the old one."""
    payload = {
        "kind": "oo-custody-key-rotation",
        "log_version": LOG_VERSION,
        "previous_ed25519_pub": previous_ed25519_pub,
        "ed25519_pub": identity.get("ed25519_pub"),
        "ml_dsa_variant": identity.get("ml_dsa_variant"),
        "ml_dsa_pub": identity.get("ml_dsa_pub"),
        "prev_entry_hash": prev_entry_hash,
    }
    if previous_ml_dsa is not None:
        payload["previous_ml_dsa_variant"], payload["previous_ml_dsa_pub"] = previous_ml_dsa
    return payload


def _records_previous_ml_dsa(md: dict) -> bool:
    """Whether a key-rotation record names the previous identity's ML-DSA half (written since 0.5.1, row 43). Such a
    record is written for EVERY change of identity, the post-quantum half included, so a log that carries one has no
    unrecorded identity change after it."""
    return "previous_ml_dsa_pub" in md


#: Said for a record that only ADDS a post-quantum (ML-DSA) half to the signing identity (row 42): there was no earlier
#: post-quantum key to vouch for it, and the change weakens nothing.
ML_DSA_ONLY_ROTATION_NOTE = (
    "post-quantum signing was turned on here: the signing identity gains an ML-DSA half. The Ed25519 key that signed "
    "the entries before signs this record too, so the change is that key's word; there was no earlier post-quantum key "
    "to vouch for it."
)
#: Said for a record that drops or replaces the ML-DSA half when the previous ML-DSA key was not there to endorse it.
#: Someone able to forge the Ed25519 key alone could write exactly this, so it is refused unless accepted by name.
ML_DSA_UNENDORSED_ROTATION_NOTE = (
    "the post-quantum (ML-DSA) half of the signing identity was dropped or replaced here, and the previous ML-DSA key was "
    "not available to vouch for it: only the Ed25519 key signs this record, and someone able to forge that key alone "
    "could write the same."
)


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
        #: True when this log had to read the custody settings and could not: it then holds the defaults (PQC off,
        #: local anchoring), which are guesses, not the operator's choice, so it signs no entry (see ``record``).
        self.prefs_unreadable = False
        if signer is None or anchoring_mode is None:
            from src.custody.settings import load_settings

            prefs = load_settings()
            self.prefs_unreadable = prefs.store_unreadable
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
        self._refuse_on_unread_prefs()
        meta = metadata or {}
        # Serialise the whole READ-CHAIN-INSERT so concurrent ingest workers can never
        # read the same tail, compute the same seq, and collide / fork the chain.
        with _APPEND_LOCK:
            prev = self._tail_on_signer()
            return self._insert(prev, item_id, item_hash, action_val, actor, meta, timestamp)

    def _refuse_on_unread_prefs(self) -> None:
        """Raise ``CustodySettingsUnreadable`` when this log opened on settings it could not read.

        The caller that read the settings a moment earlier (the ingest pipeline, a drain) may have read them fine: an
        entry signed here would then go out with the post-quantum half off and local anchoring because a second read
        failed, which is not what the operator chose. Refused instead, so the caller keeps the entry owed."""
        if self.prefs_unreadable:
            from src.custody.settings import CustodySettingsUnreadable

            raise CustodySettingsUnreadable(
                "the custody settings could not be read when this log was opened, so it signs nothing under guessed "
                "preferences; the entry stays owed until they can be read"
            )

    def _refresh_signer(self) -> None:
        """Reload the signer when its key file changed since it was loaded (lock held).

        A log kept open for a long time (a collection pass's batch) would otherwise sign with a key the folder no longer
        holds, while every log opened since signs with the new one: the chain would change key back and forth, each time
        with a rotation record saying the previous key was gone when it was not."""
        changed = getattr(self.signer, "key_file_changed", None)
        if changed is not None and changed():
            self.signer = self.signer.reloaded()

    def _tail_on_signer(self) -> CustodyEntry | None:
        """The tail, after a rotation record when the key that signs now did not sign it (lock held).

        Keys re-created after a restore, or a lost key folder: the change is said IN the chain before the new key signs
        anything -- an entry or an export's head -- so a reader can follow it instead of meeting an unexplained new key
        (R-rotation). Nobody here holds the old key, so the record is unendorsed -- except when only post-quantum signing
        was turned off: the ML-DSA key is still in the folder, and the previous identity, both halves, endorses it."""
        self._refresh_signer()
        prev = self._last()
        if prev is not None and not _signed_by(prev, self.signer):
            same_ed = _sig_ed25519_pub(prev.signature) == self.signer.public_identity().ed25519_pub
            if same_ed and _sig_ml_dsa(prev.signature)[1] and getattr(self.signer, "pqc_unavailable_but_requested", False):
                # Post-quantum signing is still wanted, but this machine lacks the library: nobody changed the key, so no
                # permanent record says so (each trip between two machines would add two), and nothing is signed with
                # the Ed25519 half alone, which a pinned check would refuse for good. The entry stays owed.
                raise PostQuantumUnavailable(
                    "post-quantum signing is on and this custody log's key has an ML-DSA half, but the post-quantum "
                    "library is not installed here: nothing is signed until it is (install the 'pqc' extra). Turning "
                    "post-quantum signing off instead is recorded unendorsed, since the old post-quantum key cannot "
                    "vouch for it without the library"
                )
            # Either half of the identity: a change of the post-quantum key alone is recorded too (row 42), or a pinned
            # check would hold every entry to an ML-DSA key the older ones were never signed with.
            # A permanent record: never written under guessed preferences (an export reaches here too).
            self._refuse_on_unread_prefs()
            previous: HybridSigner | None = None
            if same_ed and _sig_ml_dsa(prev.signature)[1]:
                with_pq = getattr(self.signer, "with_existing_post_quantum_key", lambda: None)()
                previous = with_pq if with_pq is not None and _signed_by(prev, with_pq) else None
            prev = self._insert_rotation(prev, previous_signer=previous)
        return prev

    def rotate_signing_key(self, previous_signer: HybridSigner) -> CustodyEntry:
        """Record that this log's signer replaces ``previous_signer``, ENDORSED: the previous key signs the new key's
        identity and the chain position. Call it with the old key still at hand, before the new key signs anything.
        Raises ``ValueError`` when the tail was not signed by ``previous_signer`` (it cannot vouch for what it did not
        sign) or when the two keys are the same."""
        self._refuse_on_unread_prefs()
        with _APPEND_LOCK:
            self._refresh_signer()
            prev = self._last()
            if prev is None:
                raise ValueError("the custody log is empty: there is no previous key to rotate from")
            if not _signed_by(prev, previous_signer):
                raise ValueError("the log's last entry was not signed by the previous key given")
            if _signed_by(prev, self.signer):
                raise ValueError("the new signing key is the same as the previous one")
            return self._insert_rotation(prev, previous_signer=previous_signer)

    def _insert_rotation(self, prev: CustodyEntry, *, previous_signer: HybridSigner | None) -> CustodyEntry:
        """Append the key-rotation record (lock held). Signed by the NEW key; endorsed by the old one when it is given."""
        identity = self.signer.public_identity().to_dict()
        old_pub = _sig_ed25519_pub(prev.signature)
        # The previous identity in full, as the tail's own signature carries it (row 43).
        previous_ml = _sig_ml_dsa(prev.signature)
        payload = rotation_payload(old_pub, identity, prev.entry_hash, previous_ml)
        meta: dict = {
            "previous_ed25519_pub": old_pub,
            "previous_ml_dsa_variant": previous_ml[0],
            "previous_ml_dsa_pub": previous_ml[1],
            "ed25519_pub": identity.get("ed25519_pub"),
            "ml_dsa_variant": identity.get("ml_dsa_variant"),
            "ml_dsa_pub": identity.get("ml_dsa_pub"),
        }
        if previous_signer is not None:
            meta["endorsement"] = previous_signer.sign(canonical_bytes(payload))
            meta["note"] = "The previous custody signing key signed the new key's identity and this place in the chain."
        elif old_pub == identity.get("ed25519_pub"):
            meta["endorsement"] = None
            meta["note"] = ML_DSA_UNENDORSED_ROTATION_NOTE if previous_ml[1] else ML_DSA_ONLY_ROTATION_NOTE
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
        """Produce an offline-verifiable bundle of entries + the signer identity.

        The head is signed by the key that signs now, so a key change the log has not recorded yet (keys re-created,
        nothing logged since) is recorded first, or the bundle would end on one key and be signed by another."""
        with _APPEND_LOCK:
            # Only the rotation check and the choice of signer need the lock: an entry appended after it comes after
            # this bundle's head, and a large log read under it would hold every custody write in the process.
            self._tail_on_signer()
            signer = self.signer
        entries = self.entries_for(item_id) if item_id else self.all_entries()
        if item_id and item_id != ROTATION_ITEM and entries:
            # Every key-rotation record, so the item's entries can be followed to the key that signs the head now --
            # including the rotations after its last entry, or an item untouched since a rotation could never verify.
            rotations = self.entries_for(ROTATION_ITEM)
            entries = sorted(entries + rotations, key=lambda e: e.seq)
        ident = signer.public_identity()
        head = _bundle_head(item_id, entries)
        head_signature = signer.sign(canonical_bytes(head))
        return {
            "log_version": LOG_VERSION,
            "bundle_format": BUNDLE_FORMAT,  # informational: the signed head carries the format the checker goes by
            "item_id": item_id,
            "signer": ident.to_dict(),
            "entry_count": len(entries),
            # Signed at export: how many entries this bundle holds, which one is last, and (format 2, R714) a digest of
            # every entry's hash, so a bundle cut at its end, or with an entry swapped anywhere in it, is refused by name.
            "head": head,
            "head_signature": head_signature,
            "entries": [e.to_dict() for e in entries],
        }

    def verify(self) -> tuple[bool, list[str]]:
        """Verify the full chain held in this database (see :meth:`verify_report`)."""
        report = self.verify_report()
        return report["verified"], report["issues"]

    def verify_report(self) -> dict:
        """``{"verified", "issues", "notes"}`` for the full chain held in this database: hashes, links and signatures
        (:func:`verify_entries`), and the signing key followed through its key-rotation records. A key change with no
        record is refused; an unendorsed rotation is accepted on its record's word -- this is the operator's own store --
        and named in the notes, with every other rotation."""
        entries = self.all_entries()
        ok, issues = verify_entries(entries)
        notes: list[str] = []
        if entries:
            problem, notes = _key_lineage(entries, _sig_ed25519_pub(entries[-1].signature), True,
                                          accept_unrecorded=True)
            if problem:
                ok = False
                issues.append(problem)

        return {"verified": ok, "issues": issues, "notes": notes if ok else []}

    def close(self) -> None:
        self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# --------------------------------------------------------------------------- #
# Stateless verification -- needs only the entries (and optionally a pinned key)
# --------------------------------------------------------------------------- #


def _bundle_head(item_id: str | None, entries: list[CustodyEntry], bundle_format: int = BUNDLE_FORMAT) -> dict:
    """The part of an export its signer commits to: the bundle's scope, its size and its last entry, and (format 2)
    a digest of every entry's seq and hash, in order."""
    last = entries[-1] if entries else None
    head = {
        "log_version": LOG_VERSION,
        "item_id": item_id,
        "entry_count": len(entries),
        "last_seq": last.seq if last else None,
        "last_entry_hash": last.entry_hash if last else None,
    }
    if bundle_format >= 2:
        head["bundle_format"] = bundle_format
        head["entries_digest"] = _entries_digest(entries)
    return head


def _entries_digest(entries: list[CustodyEntry]) -> str:
    return sha256(canonical_bytes({"entries": [[e.seq, e.entry_hash] for e in entries]})).hex()


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


_UNSEEN = object()  # no entry has shown the identity's ML-DSA half yet (see ``_key_lineage``)


def _key_lineage(entries: list[CustodyEntry], signer_key: str, accept_unendorsed: bool,
                 one_item: bool = False, *, accept_unrecorded: bool = False) -> tuple[str | None, list[str]]:
    """Walk the signing key through the entries. Returns ``(problem or None, notes)``; the key must end as
    ``signer_key``. See :func:`verify_export`'s WHICH KEY. ``accept_unrecorded`` is for the operator's own store only
    (the in-app check): a key change with no record is named in the notes instead of refused, on the same footing as an
    unendorsed rotation, since a log written before these records existed can never gain one. Never for a bundle."""
    notes: list[str] = []
    first = entries[0]
    current = _sig_ed25519_pub(first.signature)
    if one_item and first.action == CustodyAction.KEY_ROTATION.value and first.item_id == ROTATION_ITEM:
        # A one-item bundle starts at the earliest rotation before its item's first entry, so no entry in it was signed
        # by the key that rotation replaces: the record's own word names that key. Its endorsement, when there is one,
        # is still checked against it below, and the walk must still end on the signer key.
        named = first.metadata.get("previous_ed25519_pub")
        current = named if isinstance(named, str) else current
        named_ml = first.metadata.get("previous_ml_dsa_pub")
        start = _identity_line(current, named_ml if isinstance(named_ml, str) else None) \
            if _records_previous_ml_dsa(first.metadata) else current
    else:
        start = _identity_line(current, _sig_ml_dsa(first.signature)[1])
    last_full: CustodyEntry | None = None  # the latest record that names the whole identity
    # The ML-DSA key the identity in use has SHOWN since its last record (``None``: none; ``_UNSEEN``: nothing shows it
    # yet). Sticky, so one entry stripped of its post-quantum half -- signed with the Ed25519 key alone -- cannot pass as
    # the previous identity a forged record then names (rows 42-44, the final read's W/Z).
    cur_ml: object = _UNSEEN
    for e in entries:
        k = _sig_ed25519_pub(e.signature)
        if e.action == CustodyAction.KEY_ROTATION.value and e.item_id == ROTATION_ITEM:
            md = e.metadata
            prev_k, new_k = md.get("previous_ed25519_pub"), md.get("ed25519_pub")
            # Since 0.5.1 a record names the previous identity's ML-DSA half too (row 43), and is written when only
            # that half changes (row 42); one written before names Ed25519 keys only and must change that key.
            full = _records_previous_ml_dsa(md)
            if last_full is not None and not full:
                # Every record since 0.5.1 names the whole identity: one that does not, after one that does, would put
                # its stretch back under the old rules (an Ed25519-only endorsement, no post-quantum pin).
                return (f"the key-rotation record at seq {e.seq} names no previous ML-DSA key, though the record at seq "
                        f"{last_full.seq} before it does"), notes
            prev_ml, new_ml = (md.get("previous_ml_dsa_pub") or None) if full else None, md.get("ml_dsa_pub") or None
            if e.seq <= 1 or e.prev_entry_hash == GENESIS_PREV:
                # A log never starts with a rotation: there is no previous key to rotate from.
                return f"the key-rotation record at seq {e.seq} opens the log, where no previous key exists", notes
            same_ed = prev_k == new_k
            if (not isinstance(prev_k, str) or not isinstance(new_k, str) or not new_k
                    or not isinstance(prev_ml, str | None) or not isinstance(new_ml, str | None)
                    or (same_ed and (not full or prev_ml == new_ml))):
                return f"the key-rotation record at seq {e.seq} does not name two different keys", notes
            if prev_k != current:
                return (f"the key-rotation record at seq {e.seq} names a previous key that did not sign the entries "
                        "before it"), notes
            if k != new_k or (full and _sig_ml_dsa(e.signature)[1] != new_ml):
                return f"the key-rotation record at seq {e.seq} is not signed by the key it introduces", notes
            if full and last_full is not None and (last_full.metadata.get("ml_dsa_pub") or None) != prev_ml:
                # Any change of identity since a full record has its own record, so the identity one record leaves
                # must be the one the record before it introduced -- a one-item bundle holds every record.
                return (f"the key-rotation record at seq {e.seq} names a previous ML-DSA key other than the one the "
                        f"record at seq {last_full.seq} introduced"), notes
            # The bundle's own evidence of the previous identity's ML-DSA half: what the entries signed under it since
            # its last record showed (sticky, see ``cur_ml``). The record is written from the entry before it.
            evidence_ml = cur_ml
            if full and evidence_ml is not _UNSEEN and evidence_ml != prev_ml:
                # Or the record could name any post-quantum key -- or none, to pass as post-quantum turned on -- as
                # the previous one.
                if one_item:
                    return (f"the key-rotation record at seq {e.seq} names a previous ML-DSA key the earlier entries in "
                            "this one-item bundle were not signed with (if that key changed before 0.5.1 with no "
                            "record, verify the whole-log export instead)"), notes
                return (f"the key-rotation record at seq {e.seq} names a previous ML-DSA key the entries before it were "
                        "not signed with"), notes
            # A record that names both halves is printed with both, so a reader who knows either can compare it.
            was, now = (_identity_line(prev_k, prev_ml), _identity_line(new_k, new_ml)) if full else (prev_k, new_k)
            endorsement = md.get("endorsement")
            if endorsement is None and same_ed and prev_ml is None:
                # Post-quantum signing turned on: the Ed25519 key that signed the entries before signs this record, and
                # there was no earlier post-quantum key whose protection the change could take away.
                notes.append(f"seq {e.seq}: the signing identity changed from {was} to {now}: {ML_DSA_ONLY_ROTATION_NOTE}")
            elif endorsement is None and same_ed:
                # The ML-DSA half dropped or replaced on the Ed25519 key's word alone: what someone able to forge that
                # key would write to strip the post-quantum protection, so it is an unendorsed rotation.
                if not accept_unendorsed:
                    return (f"the post-quantum (ML-DSA) key changes at seq {e.seq} with no endorsement by the previous "
                            "ML-DSA key: its record says that key was not available, and someone able to forge the "
                            "Ed25519 key alone would write the same. Verify again accepting an unendorsed rotation "
                            "only if you know the post-quantum key was re-created"), notes
                notes.append(f"seq {e.seq}: the signing identity changed from {was} to {now}, accepted on the record's "
                             f"word: {ML_DSA_UNENDORSED_ROTATION_NOTE}")
            elif endorsement is None:
                if not accept_unendorsed:
                    return (f"the signing key changes at seq {e.seq} with no endorsement by the previous key: its record "
                            "says the previous key was not available, and a forged tail would say the same. Verify "
                            "again accepting an unendorsed rotation only if you know the key was re-created"), notes
                notes.append(f"seq {e.seq}: the signing key changed from {was} to {now}, accepted on the record's "
                             f"word: {UNENDORSED_ROTATION_NOTE}")
            else:
                problem = _signature_shape_problem(endorsement)
                if (problem or _sig_ed25519_pub(endorsement) != prev_k
                        or (full and _sig_ml_dsa(endorsement)[1] != prev_ml)):
                    # Both halves, for a record that names both (row 43): an endorsement whose ML-DSA half is some other
                    # key, or was stripped off, is not the previous identity's.
                    return f"the key-rotation record at seq {e.seq} carries an endorsement not made by the previous key", notes
                # An older record names no ML-DSA key, but the entries before it show one when they were signed with both
                # halves: an endorsement without that half is the Ed25519 key's word alone -- what someone able to forge
                # that key would write -- so it counts as unendorsed (an honest one: the old key on a machine without
                # the post-quantum library, before 0.5.1).
                half_vouched = (not full and isinstance(evidence_ml, str)
                                and _sig_ml_dsa(endorsement)[1] != evidence_ml)
                if half_vouched and not accept_unendorsed:
                    return (f"the key-rotation record at seq {e.seq} is endorsed without the post-quantum (ML-DSA) key "
                            "the entries before it were signed with, so only the Ed25519 key vouches for it, as someone "
                            "able to forge that key alone could. Verify again accepting an unendorsed rotation only if "
                            "you know the key was rotated on a machine without the post-quantum library"
                            + (" (or verify the whole-log export)" if one_item else "")), notes
                identity = {"ed25519_pub": new_k, "ml_dsa_variant": md.get("ml_dsa_variant"),
                            "ml_dsa_pub": md.get("ml_dsa_pub")}
                previous_ml = (md.get("previous_ml_dsa_variant"), md.get("previous_ml_dsa_pub")) if full else None
                ok, reason = signing.verify(endorsement, canonical_bytes(rotation_payload(prev_k, identity,
                                                                                          e.prev_entry_hash,
                                                                                          previous_ml)))
                if not ok:
                    return f"the key-rotation record at seq {e.seq} has an invalid endorsement: {reason}", notes
                if half_vouched:
                    notes.append(f"seq {e.seq}: the signing key changed from {was} to {now}, accepted on the record's "
                                 "word: its endorsement carries the Ed25519 half of the previous key only")
                else:
                    notes.append(f"seq {e.seq}: the signing key changed from {was} to {now}, endorsed by the previous key")
            if evidence_ml is _UNSEEN:
                # Nothing before the record in this bundle shows the previous identity's post-quantum half.
                notes.append(f"seq {e.seq}: nothing before this record in the bundle shows which post-quantum (ML-DSA) "
                             "key the previous identity had, so that is the record's own word"
                             + ("; the whole-log check ties it to the entries before the record" if one_item else ""))
            if full:
                last_full = e
            cur_ml = new_ml if full else _UNSEEN
            current = new_k
        elif k != current:
            if not accept_unrecorded:
                return (f"the signing key changes at seq {e.seq} with no key-rotation record: a re-created key and a "
                        "forged tail read the same here, so neither is verified"), notes
            notes.append(f"seq {e.seq}: {UNRECORDED_KEY_CHANGE_NOTE} (from {current} to {k})")
            current = k
            cur_ml = _sig_ml_dsa(e.signature)[1]
        else:
            sig_ml = _sig_ml_dsa(e.signature)[1]
            if cur_ml is _UNSEEN or sig_ml == cur_ml or (cur_ml is None and last_full is None):
                # The first showing, the same key, or post-quantum signing turned on before 0.5.1 (no record then, and
                # it weakens nothing).
                cur_ml = sig_ml
            else:
                # The post-quantum half dropped or replaced with no record: a signature stripped by someone holding the
                # Ed25519 key alone reads the same. Since a 0.5.1 record nothing honest does it (every change is
                # recorded, and nothing is signed without the library); before, post-quantum signing turned off did.
                was_ml = cur_ml if isinstance(cur_ml, str) else None
                change = f"from {_identity_line(current, was_ml)} to {_identity_line(k, sig_ml)}"
                if not (accept_unrecorded or (accept_unendorsed and last_full is None)):
                    return (f"the post-quantum (ML-DSA) key changes at seq {e.seq} with no key-rotation record ({change}):"
                            " an entry signed with the Ed25519 key alone, stripped of its post-quantum half or signed with "
                            "another, reads the same."
                            + (" Verify again accepting an unendorsed rotation only if you know post-quantum signing was "
                               "changed before 0.5.1" if last_full is None else "")), notes
                notes.append(f"seq {e.seq}: the post-quantum (ML-DSA) key changed with no key-rotation record ({change}); "
                             "post-quantum signing turned off or its key re-created before 0.5.1 leaves this mark, and so "
                             "does an entry stripped of its post-quantum half")
                cur_ml = sig_ml
    if current != signer_key:
        return "the entries end on a different key from the bundle's signer key", notes
    if notes:
        # The line of keys, from its first: an endorsement proves something only to a reader who knows one of these
        # keys, and a chain built wholly with someone else's keys reads the same otherwise.
        notes.insert(0, f"the chain starts on key {start}; compare any key you already know with this line of keys")
    return None, notes


def _segment_pins(entries: list[CustodyEntry], signer: PublicIdentity) -> dict[int, PublicIdentity | None]:
    """The identity each entry is pinned to when a bundle crosses key rotations (see ``_verify_export``)."""
    rotations = [i for i, e in enumerate(entries)
                 if e.action == CustodyAction.KEY_ROTATION.value and e.item_id == ROTATION_ITEM]
    last = rotations[-1] if rotations else len(entries)
    pins: dict[int, PublicIdentity | None] = {}
    current: PublicIdentity | None = None
    for i, e in enumerate(entries):
        if i in rotations:
            md = e.metadata
            ml = md.get("ml_dsa_pub")
            if _records_previous_ml_dsa(md):
                # A record written since 0.5.1 names the whole identity, and any later change of it has its own record
                # (row 42): its stretch is held to exactly that identity, an ML-DSA half or none.
                current = PublicIdentity(ed25519_pub=str(md.get("ed25519_pub")), ml_dsa_variant=md.get("ml_dsa_variant"),
                                         ml_dsa_pub=ml if isinstance(ml, str) and ml else None)
                pins[e.seq] = current
                continue
            current = PublicIdentity(ed25519_pub=str(md.get("ed25519_pub")), ml_dsa_variant=md.get("ml_dsa_variant"),
                                     ml_dsa_pub=ml) if isinstance(ml, str) and ml else None
            if i == last and current is None:
                # The last stretch names no ML-DSA key of its own: held to the bundle's signer, which may have gained one.
                current = signer
        # The last stretch too is pinned to the identity its rotation introduced, like every other: pinning it to the
        # signer as it is NOW refused an honest log whose post-quantum half was turned off after the rotation (its
        # rotation record carries the ML-DSA half the signer no longer names).
        pins[e.seq] = current
    return pins


def _sig_ed25519_pub(sig: dict) -> str:
    return str((sig.get("ed25519") or {}).get("pub") or "")


def _signed_by(entry: CustodyEntry, signer: HybridSigner) -> bool:
    """Whether ``entry`` carries ``signer``'s whole identity: its Ed25519 key, and its ML-DSA key or none."""
    ident = signer.public_identity()
    return (_sig_ed25519_pub(entry.signature) == ident.ed25519_pub
            and _sig_ml_dsa(entry.signature)[1] == (ident.ml_dsa_pub or None))


def _sig_ml_dsa(sig: dict) -> tuple[str | None, str | None]:
    """The ``(variant, pub)`` of a signature's ML-DSA half, ``(None, None)`` for an Ed25519-only signature."""
    if sig.get("algorithm") != "hybrid":
        return None, None
    ml = sig.get("ml_dsa") or {}
    variant, pub = ml.get("variant"), ml.get("pub")
    return (variant if isinstance(variant, str) else None), (pub if isinstance(pub, str) else None)


def _identity_line(ed: str, ml_pub: str | None) -> str:
    """A signing identity in a note: both halves, since a reader who knows one compares both."""
    return f"{ed} (ML-DSA {ml_pub})" if ml_pub else f"{ed} (no ML-DSA key)"


def verify_export(
    bundle: dict, *, require_signer: bool = False, accept_unendorsed_rotation: bool = False
) -> tuple[bool, list[str]]:
    """``(ok, issues)`` of :func:`verify_export_report`. It DROPS the bundle format: a format-1 bundle answers
    ``(True, [])`` like a format-2 one, so anything shown to a person uses :func:`verify_export_report` and its
    ``format_note`` (R714)."""
    report = verify_export_report(
        bundle, require_signer=require_signer, accept_unendorsed_rotation=accept_unendorsed_rotation
    )
    return report["verified"], report["issues"]


def verify_export_report(
    bundle: dict, *, require_signer: bool = False, accept_unendorsed_rotation: bool = False
) -> dict:
    """``{"verified", "issues", "notes", "format", "format_note"}`` for an exported bundle; ``notes`` names every key
    rotation crossed, and ``format``/``format_note`` say which bundle format the signed head is in and, for format 1,
    what its weaker guarantee does not prove (R714). Show ``format_note`` wherever the verdict is shown."""
    notes: list[str] = []
    try:
        ok, issues = _verify_export(bundle, require_signer, accept_unendorsed_rotation, notes)
    except UnicodeEncodeError:
        # A lone surrogate (JSON "\ud800") has no UTF-8 form, so no signature over it can exist.
        ok, issues = False, ["a text field holds a character with no UTF-8 form (a lone surrogate), so no signature covers it"]
    head = bundle.get("head") if isinstance(bundle, dict) else None
    fmt = head.get("bundle_format", 1) if ok and isinstance(head, dict) else None  # validated by _verify_export
    legacy = fmt == 1
    # R714: an old-format bundle is never reported as equal to a new one -- ``format`` and ``format_note`` say so.
    return {"verified": ok, "issues": issues, "notes": notes if ok else [],
            "format": fmt,
            "format_note": LEGACY_FORMAT_NOTE if legacy else None}


def _verify_export(
    bundle: dict, require_signer: bool, accept_unendorsed_rotation: bool, notes: list[str]
) -> tuple[bool, list[str]]:
    """Verify an exported custody bundle (offline, no DB). FAILS CLOSED.

    Refused by name, before any entry is judged: a bundle with no entries; an entry that is not a whole record (a file
    cut mid-record leaves one with fields missing or of the wrong kind); a bundle with no signed head (it cannot show
    that nothing was cut from its end, since every remaining link still holds -- the reason says to export it again);
    a head whose signature does not verify or was made with another key; a head in an unknown bundle format; and a
    bundle whose entries do not match its head (fewer or more than it says, a different last entry, or -- format 2,
    R714 -- any entry swapped, reordered, added or removed, which the head's digest of every entry hash shows).

    WHICH KEY. The head must carry the Ed25519 key the bundle names as its signer, and so must every entry, except
    across a KEY-ROTATION record (``rotate_signing_key`` / the record written when a re-created key first signs): there
    the key may change from the one that signed the entries before it to the one the record names, which signs it.
    An ENDORSED rotation (the previous key signed the new key and this place in the chain) passes and is named in the
    notes. An UNENDORSED one (the previous key was gone) is what a forged tail would also write, so it is refused unless
    the caller passes ``accept_unendorsed_rotation`` -- then it passes on that record's word, said in the notes. Any
    other key change is refused and its seq named. The ML-DSA half is followed too (rows 42-44), by the key each
    identity has SHOWN: dropping or replacing it needs a record. A record since 0.5.1 that only ADDS an ML-DSA half
    passes on the Ed25519 key's word; one that drops or replaces it needs the previous identity's endorsement, both
    halves, or is unendorsed. Such a record names the previous ML-DSA key: an endorsement must carry it and the entries
    before the record must have shown it. An entry that drops or replaces the shown key with no record is refused (before
    any 0.5.1 record, accepted by name with ``accept_unendorsed_rotation``: post-quantum signing turned off before 0.5.1
    left exactly that). Gaining the post-quantum half before 0.5.1 with no record still verifies; each signature is
    still verified in full. THIS PROVES CONSISTENCY, NOT
    PROVENANCE: anyone can build a whole bundle, head included, with a key of their own. A cut at the end is caught
    only when the signer key is compared with one the reader already knows to be the real signer's.

    What it cannot show: a log cut BEFORE it was exported (the head commits to what was exported, not to what the store
    once held) -- the full log's chain shows a cut at its start or middle, and a one-item export shows neither.

    If ``require_signer`` is true, pin verification to the signer identity embedded in the bundle -- i.e. require that
    the head and all entries were signed by that identity: its Ed25519 key, and its ML-DSA key wherever a signature
    carries an ML-DSA half. A head stripped to its Ed25519 half under a signer that names an ML-DSA key is refused
    (row 44); an entry that drops the ML-DSA key its identity had shown is refused by the key lineage in every mode.
    Across a key rotation each stretch of the chain is pinned to the identity that introduced it instead (see the end of
    this function): a record written since 0.5.1 names the whole identity and pins its stretch to exactly that; an
    older record that names no ML-DSA key, and the stretch before the first rotation, hold their stretch to its Ed25519
    key only. (Pinning to a *bundle-embedded* key only proves internal
    consistency; to prove provenance against a *known* signer, compare ``bundle['signer']`` to the signer's
    independently-known public identity first.)
    """
    if not isinstance(bundle, dict):
        return False, ["not a custody bundle (not a JSON object)"]
    raw = bundle.get("entries")
    if not isinstance(raw, list) or not raw:
        if isinstance(raw, list) and isinstance(bundle.get("item_id"), str) and bundle.get("item_id"):
            return False, [f"this item has no custody entries: the bundle for {bundle['item_id']!r} holds none to verify"]
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
    problem, rotation_notes = _key_lineage(entries, key, accept_unendorsed_rotation, one_item=bool(item_id))
    notes.extend(rotation_notes)
    if problem:
        return False, [problem]
    if pinned is not None and pinned.ml_dsa_pub and head_sig.get("algorithm") != "hybrid":
        # Row 44: a signer that names an ML-DSA key signs its head with both halves, so an Ed25519-only head has had its
        # post-quantum half stripped -- and the head is what commits to every entry (R714).
        return False, ["head signature invalid: the signer names an ML-DSA key but the head carries the Ed25519 half "
                       "only, so its post-quantum half was removed"]
    ok, reason = signing.verify(head_sig, canonical_bytes(head), pinned=pinned)
    if not ok:
        return False, [f"head signature invalid: {reason}"]
    fmt = head.get("bundle_format", 1)
    if type(fmt) is not int or fmt not in (1, BUNDLE_FORMAT):
        return False, [f"unknown bundle format {fmt!r}: this checker reads formats 1 and {BUNDLE_FORMAT}"]
    if fmt >= 2 and not isinstance(head.get("entries_digest"), str):
        return False, ["the signed head names bundle format 2 but carries no digest of its entries"]
    expected = _bundle_head(item_id, entries, bundle_format=fmt)
    if head != expected:
        if head.get("entry_count") != len(entries):
            return False, [
                f"truncated or padded: the signed head says {head.get('entry_count')} entries, the bundle holds {len(entries)}"
            ]
        if fmt >= 2 and {k: v for k, v in head.items() if k != "entries_digest"} == {
                k: v for k, v in expected.items() if k != "entries_digest"}:
            return False, ["the bundle's entries do not match the entry hashes its signed head commits to: an entry "
                           "was swapped, reordered, added or removed"]
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
    last_rot = next(e for e in reversed(entries)
                    if e.action == CustodyAction.KEY_ROTATION.value and e.item_id == ROTATION_ITEM)
    rot_ml = last_rot.metadata.get("ml_dsa_pub")
    if _records_previous_ml_dsa(last_rot.metadata) and (rot_ml or None) != (pinned.ml_dsa_pub or None):
        # A record since 0.5.1 is followed by another for any change of identity, so the signer must be its identity.
        return False, [f"the bundle's signer names {_identity_line(pinned.ed25519_pub, pinned.ml_dsa_pub)}, not the "
                       f"identity the key-rotation record at seq {last_rot.seq} introduced, and no record says it changed"]
    if pinned.ml_dsa_pub and isinstance(rot_ml, str) and rot_ml and rot_ml != pinned.ml_dsa_pub:
        # The printed signer is what a reader compares with a key they know: it must be the identity the last stretch is
        # held to, not a post-quantum key no rotation record introduced.
        return False, [f"the bundle's signer names an ML-DSA key other than the one the key-rotation record at seq "
                       f"{last_rot.seq} introduced, and no record says it changed"]
    # An Ed25519-only entry in a stretch a record since 0.5.1 introduced with an ML-DSA key never reaches here: the key
    # lineage has refused it as a change of the post-quantum key with no record (row 44).
    pins = _segment_pins(entries, pinned)
    return verify_entries(entries, pinned_by_seq=pins, chained=not item_id)
