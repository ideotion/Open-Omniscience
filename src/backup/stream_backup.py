"""The oo-volumes-2 STREAMING backup engine — P0.1 backup-at-scale (2026-07-09).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (the 2026-07-09 field event): the previous large-backup path materialized the
WHOLE corpus twice before a single volume was written — a disposable PLAINTEXT
snapshot (decrypt-the-world; an at-rest-encryption violation while staged) and an
oo-backup-2 zip of it — and its Reed-Solomon parity then loaded the whole volume
set into RAM. At the field's 11.7 GB corpus on a 10 GB VM that is a guaranteed
OOM ON THE VERY PATH MEANT TO SAVE THE CORPUS. This engine replaces the container
so that NO step ever holds or writes a whole-corpus copy:

  * MEMBER-STREAMED: each artifact member (corpus, custody, state files, logs,
    annotations, keys, the signed oo-backup-2 manifest) is sliced and encrypted
    DIRECTLY into independently-authenticated OOENC2 volumes. There is no zip.
  * THE CORPUS IS NEVER DECRYPTED AT BACKUP TIME: the live database FILE is
    streamed as-is (raw SQLCipher bytes when the store is encrypted), inside a
    single writer-gate window after a WAL checkpoint — a consistent snapshot with
    ZERO staging disk and bounded RAM (one 4 MiB chunk at a time). A plaintext
    store streams its plaintext bytes; the OOENC2 volume envelope is the at-rest
    protection either way.
  * INCREMENTAL: every volume records the SHA-256 of its plaintext slice, so a
    re-run against the same destination re-emits ONLY changed volumes (checksum
    compared, never size/mtime — a same-length slice with different bytes always
    re-emits). Unchanged SQLCipher pages keep their ciphertext bytes on disk, so
    an append-mostly corpus reuses most volumes. Reuse of an on-disk volume is
    itself checksum-verified against the manifest before it is trusted.
  * RESUMABLE = the same mechanism: an interrupted run leaves its finished
    volumes plus ``volumes.building.json`` (an interim entry log) and NO final
    manifest — so a partial set can never be mistaken for a good backup — and the
    next run re-hashes every slice against the CURRENT database state inside one
    gate window, reusing what still matches and re-emitting the rest. Every
    completed manifest therefore describes ONE consistent database state, never a
    mix of two.
  * PASSPHRASE-BOUND REUSE: the manifest carries a ``key_check`` token; volumes
    written under a different passphrase are never mixed into a new set (a run
    with a new passphrase re-emits everything, stated in the summary notes).
  * VERIFIABLE: :func:`verify_stream_backup` checks the Ed25519-signed volume
    manifest, every data + parity volume checksum and the member/slice structure
    WITHOUT decrypting anything; given the passphrase it additionally
    stream-decrypts every volume into a hash sink (nothing written to disk) and
    cross-checks the signed inner envelope. It names exactly which volumes are
    bad and whether parity can still recover them.

RESTORE: volumes are verified (+ parity-recovered), then stream-decrypted member
by member into a staging dir. An encrypted corpus/custody member is converted to
the plaintext copy the additive merge engine requires — the ONLY point where
plaintext touches disk, inside the transient ``.restore-*`` staging the janitor
reclaims — using the corpus's OWN passphrase (tried in order: the explicit
``corpus_passphrase``, the live unlocked key, the backup passphrase). The merge
itself stays byte-for-byte the additive-only engine (nothing replaced, ever).

HONESTY: the writer gate is HELD while the corpus member streams (that is the
consistency guarantee), so collection writes pause for the duration — reported
as ``gate_held_s`` in the summary and as the "corpus (writes paused)" phase,
never hidden. All wall times and byte counts in the summary are measured.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import secrets
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # runtime import stays lazy (artifact <-> stream_backup seam)
    from src.backup.artifact import StagedArtifact

from src.backup.volumes import (
    MANIFEST_NAME,
    VOLUME_SIZE_DEFAULT,
    VolumeError,
    VolumeStopped,
    _sha256_file,
    load_manifest,
    verify_volume_set,
)
from src.paths import data_dir
from src.safety.crypto import (
    EncryptionError,
    decrypt_bytes,
    decrypt_stream,
    encrypt_bytes,
    encrypt_stream_to_hashed,
)

_LOG = logging.getLogger("backup.stream")

STREAM_KIND = "oo-volumes-2"
BUILDING_NAME = "volumes.building.json"
_BUILDING_KIND = "oo-volumes-2-building"
_CHUNK = 4 * 1024 * 1024
_KEY_CHECK_PLAINTEXT = b"oo-volumes-2 key check"
_CHECKPOINT_WAIT_S = 30.0
_SAFE_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

_COMMITMENT_METHOD = (
    "sha256-chain-v1: sha256 over the per-article "
    "sha256(canonical_bytes({id,hash})) leaves in hash order (streamed, O(1) memory)"
)


# --------------------------------------------------------------------------- #
#  Active-staging registry (Z4): the janitor must NEVER sweep a live job's dirs.
# --------------------------------------------------------------------------- #
_ACTIVE_STAGING: set[str] = set()
_ACTIVE_LOCK = threading.Lock()


@contextmanager
def active_staging(path: Path | str) -> Iterator[None]:
    """Mark ``path`` as belonging to a RUNNING backup/restore job for the duration."""
    key = str(Path(path).resolve())
    with _ACTIVE_LOCK:
        _ACTIVE_STAGING.add(key)
    try:
        yield
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE_STAGING.discard(key)


def is_active_staging(path: Path | str) -> bool:
    """True when ``path`` is (or lives inside) a registered live job's staging."""
    s = str(Path(path).resolve())
    with _ACTIVE_LOCK:
        return any(s == a or s.startswith(a + os.sep) for a in _ACTIVE_STAGING)


_TEMP_DIR_PREFIXES = (".bak-build-", ".restore-")
_TEMP_FILE_SUFFIXES = (".oopart", ".reassembling")


def sweep_stale_backup_temps(root: Path | str, *, max_age_hours: float = 24.0) -> int:
    """Remove ORPHANED backup/restore temps under ``root`` (non-recursive):
    ``.bak-build-*`` / ``.restore-*`` staging dirs and ``*.oopart`` /
    ``*.reassembling`` files older than ``max_age_hours``. A LIVE job's paths are
    protected twice over — the active-staging registry and the age guard (a dir
    being written has a fresh mtime). Never touches volumes, manifests or the
    resume log (``volumes.building.json``). Returns the number removed."""
    rootp = Path(root)
    if not rootp.is_dir():
        return 0
    removed = 0
    cutoff = time.time() - max_age_hours * 3600
    try:
        entries = list(rootp.iterdir())
    except OSError:  # pragma: no cover - unreadable root
        return 0
    for p in entries:
        try:
            if is_active_staging(p):
                continue
            if p.is_dir() and p.name.startswith(_TEMP_DIR_PREFIXES):
                # A dir's own mtime can stay old while files are written INSIDE it —
                # age-guard on the newest entry within, so a live tree is never swept.
                newest = p.stat().st_mtime
                for sub in p.rglob("*"):
                    try:
                        newest = max(newest, sub.stat().st_mtime)
                    except OSError:  # pragma: no cover
                        continue
                if newest < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
                    removed += 1
            elif p.is_file() and p.name.endswith(_TEMP_FILE_SUFFIXES):
                if p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
                    removed += 1
        except OSError:  # pragma: no cover - fs race; janitor is best-effort
            continue
    return removed


# --------------------------------------------------------------------------- #
#  Small helpers
# --------------------------------------------------------------------------- #
def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


_SAFE_VOL_NAME = re.compile(r"^[A-Za-z0-9._-]+$")


def _require_safe_member_name(name: str) -> None:
    """Member names come from a manifest ANYONE can self-sign — the reassembly
    must never write outside its staging dir (the zip path's _safe_extract
    equivalent). Absolute paths, drive letters, backslashes and '..' refuse."""
    p = Path(name)
    if (
        not name
        or p.is_absolute()
        or "\\" in name
        or ".." in p.parts
        or name.startswith("/")
        or ":" in name.split("/", 1)[0]
    ):
        raise VolumeError(f"unsafe member path in the volume manifest: {name!r}")


def _require_safe_volume_name(name: str) -> None:
    """Volume file names must be plain basenames — never a path that could make
    verify/restore read or write outside the set directory."""
    if not name or not _SAFE_VOL_NAME.match(name):
        raise VolumeError(f"unsafe volume file name in the volume manifest: {name!r}")


def _require_safe_manifest_names(m: dict[str, Any]) -> None:
    """Reject traversal/absolute names ANYWHERE a manifest names a file. A
    signature only proves internal consistency with the EMBEDDED key — anyone
    can self-sign — so verify, parity recovery and reassembly all guard names
    BEFORE touching the filesystem. This MUST cover every manifest field that
    becomes a path: the volume registry, parity volumes, member names AND their
    per-member volume references, plus the top-level ``corpus_member`` /
    ``wal_member`` (the restore corpus-fold path turns those into ``staging /
    <name>`` and unlinks them — an unguarded ``..`` escapes the staging dir into
    the data dir, i.e. an arbitrary-file delete of the live corpus)."""
    for v in m.get("volumes") or []:
        _require_safe_volume_name(str(v.get("name") or ""))
    for pv in (m.get("parity") or {}).get("volumes") or []:
        _require_safe_volume_name(str(pv.get("name") or ""))
    for mm in m.get("members") or []:
        _require_safe_member_name(str(mm.get("name") or ""))
        for vname in mm.get("volumes") or []:
            _require_safe_volume_name(str(vname or ""))
    if m.get("corpus_member") is not None:
        _require_safe_member_name(str(m.get("corpus_member")))
    if m.get("wal_member") is not None:
        _require_safe_member_name(str(m.get("wal_member")))


def _vol_name(member: str, i: int, run_token: str) -> str:
    """Filesystem-safe volume name for (member, slice), unique PER RUN for newly
    emitted volumes. A refresh never overwrites a file the previous complete
    manifest references (reused volumes keep their recorded names; superseded
    ones are garbage-collected only AFTER the new manifest is finalized) — so an
    interrupted or cancelled refresh leaves the previous backup fully restorable."""
    tag = hashlib.sha256(member.encode("utf-8")).hexdigest()[:12]
    return f"vol-{tag}-{i:05d}-{run_token}.ooenc"


def _key_check(passphrase: str) -> str:
    return encrypt_bytes(_KEY_CHECK_PLAINTEXT, passphrase).hex()


def _key_check_ok(token: str | None, passphrase: str) -> bool:
    if not token:
        return False
    try:
        return decrypt_bytes(bytes.fromhex(token), passphrase) == _KEY_CHECK_PLAINTEXT
    except (EncryptionError, ValueError):
        return False


def _manifest_signature_state(m: dict[str, Any]) -> str:
    """verified | bad-signature | unsigned — over the manifest minus its signature."""
    sig = m.get("signature")
    if not isinstance(sig, dict) or not sig.get("signature") or not sig.get("public_key"):
        return "unsigned"
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        from src.reporting.evidence import canonical_bytes

        body = {k: v for k, v in m.items() if k != "signature"}
        pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(sig["public_key"]))
        pub.verify(bytes.fromhex(sig["signature"]), canonical_bytes(body))
        return "verified"
    except Exception:  # noqa: BLE001 - any failure is exactly "bad-signature"
        return "bad-signature"


def _sign_manifest(m: dict[str, Any]) -> dict[str, str]:
    from src.reporting.evidence import (
        canonical_bytes,
        load_or_create_signing_key,
        public_key_hex,
    )

    key = load_or_create_signing_key()
    body = {k: v for k, v in m.items() if k != "signature"}
    return {
        "algorithm": "ed25519",
        "public_key": public_key_hex(key),
        "signature": key.sign(canonical_bytes(body)).hex(),
    }


# --------------------------------------------------------------------------- #
#  Corpus source (the live default + a seam for tests/benches)
# --------------------------------------------------------------------------- #
@dataclass
class CorpusSource:
    """What the corpus member streams from. ``freeze()`` yields the residual WAL
    path (or None) with the file guaranteed stable for the duration. ``facts_key``
    opens the store for the descriptive stats when the ambient process key is not
    its key (test/bench corpora); the live store always opens with the ambient key."""

    path: Path
    member_name: str
    encrypted: bool
    freeze: Callable[[], Any]  # context manager -> Path | None (residual wal)
    facts_key: str | None = None


@contextmanager
def _no_freeze() -> Iterator[None]:
    yield None


def _drain_wal(db_path: Path) -> Path | None:
    """Fold the WAL into the main file (TRUNCATE checkpoint, retried briefly).
    Returns the WAL path if frames REMAIN (a long reader held them) — the caller
    then carries the WAL as a member instead of blocking forever."""
    from src.database.session import engine

    wal = db_path.with_name(db_path.name + "-wal")
    deadline = time.monotonic() + _CHECKPOINT_WAIT_S
    while True:
        try:
            with engine.connect() as conn:
                conn.exec_driver_sql("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:  # noqa: BLE001 - checkpoint is best-effort; the wal member covers it
            _LOG.warning("backup: WAL checkpoint failed", exc_info=True)
            break
        if not wal.exists() or wal.stat().st_size == 0:
            return None
        if time.monotonic() >= deadline:
            break
        time.sleep(0.5)
    return wal if wal.exists() and wal.stat().st_size > 0 else None


def _live_corpus_source(
    tmp_dir: Path, include_newsletters: bool, notes: list[str]
) -> CorpusSource:
    from src.backup.sqlite_backup import live_db_path
    from src.database.connect import is_encrypted_file

    live = live_db_path()
    enc = bool(is_encrypted_file(live))
    member = "corpus.db.sqlcipher" if enc else "corpus.db"
    if include_newsletters:

        @contextmanager
        def freeze() -> Iterator[Path | None]:
            from src.database.writer import gate_enabled, write_lock

            if not gate_enabled():
                # The write gate IS the snapshot-consistency guarantee: collection
                # writes pause while the corpus streams. Under OO_WRITE_GATE=0 the
                # lock is a no-op, so a concurrent commit could tear the streamed
                # image while the summary still reports a "writes paused" phase.
                # Degrade LOUDLY — never present a possibly-inconsistent backup as
                # a paused-and-consistent one.
                notes.append(
                    "WARNING: OO_WRITE_GATE=0 — the write gate was disabled, so the "
                    "corpus was NOT streamed under a write pause. If collection was "
                    "active this snapshot may be inconsistent; re-enable the gate (or "
                    "stop collection) for a guaranteed-consistent backup."
                )
            with write_lock():
                yield _drain_wal(live)

        return CorpusSource(path=live, member_name=member, encrypted=enc, freeze=freeze)

    # Newsletter exclusion needs a modifiable copy: a DISPOSABLE snapshot that
    # PRESERVES the at-rest encryption state (never a plaintext staging), filtered
    # in place, streamed instead of the live file. Snapshot pages are re-encrypted
    # with fresh IVs, so incremental reuse does not apply to filtered runs.
    from src.database.connect import snapshot_preserving

    snap = tmp_dir / member
    snapshot_preserving(live, snap)
    _drop_newsletters_in_file(snap)
    notes.append(
        "newsletters excluded: the corpus was snapshotted and filtered, so "
        "incremental volume reuse does not apply to this run"
    )
    return CorpusSource(path=snap, member_name=member, encrypted=enc, freeze=_no_freeze)


def _drop_newsletters_in_file(db_path: Path) -> int:
    """Drop imported-newsletter articles from a DISPOSABLE snapshot, plaintext or
    SQLCipher (opened through the one factory with the ambient key)."""
    from src.backup.artifact import _drop_newsletter_rows
    from src.database.connect import connect

    con = connect(db_path, check_same_thread=False)
    try:
        return _drop_newsletter_rows(con)
    finally:
        con.close()


def _corpus_facts(path: Path, key: str | None = None) -> tuple[dict[str, Any], str | None]:
    """Table counts + a streamed article commitment + the alembic revision, read
    through the ONE connection factory (plaintext or SQLCipher with the ambient
    key). Bounded memory: the commitment is a running hash chain, never a list.

    Degrades honestly: an unreadable store (e.g. a bench file that is not an OO
    corpus) yields empty counts and a null commitment rather than failing the
    backup — the member checksums still protect the bytes themselves."""
    from src.database.connect import connect

    counts: dict[str, int] = {}
    commitment: dict[str, Any] | None = None
    rev: str | None = None
    try:
        conn = connect(path, key=key, check_same_thread=False)
    except Exception:  # noqa: BLE001 - stats are descriptive; bytes are still protected
        _LOG.warning("backup: could not open the corpus for stats", exc_info=True)
        return {"tables": counts, "articles_commitment": None}, None
    try:
        cur = conn.cursor()
        try:
            tables = [
                r[0]
                for r in cur.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'article_fts%'"
                ).fetchall()
            ]
            for t in tables:
                if _SAFE_ID.match(t):
                    cur.execute(f'SELECT COUNT(*) FROM "{t}"')  # noqa: S608  # nosec B608 - identifier from sqlite_master, validated against _SAFE_ID; no user input
                    counts[t] = int(cur.fetchone()[0])
            if "articles" in counts:
                from src.reporting.evidence import canonical_bytes

                h = hashlib.sha256()
                n_rows = 0
                # hash order rides the unique hash index (index-only scan) — an
                # id-ordered scan would drag whole article rows (content included)
                # through the SQLCipher codec (the measured column-order trap).
                cur.execute("SELECT id, hash FROM articles ORDER BY hash")
                while True:
                    rows = cur.fetchmany(10_000)
                    if not rows:
                        break
                    for rid, ahash in rows:
                        h.update(
                            hashlib.sha256(canonical_bytes({"id": rid, "hash": ahash})).digest()
                        )
                        n_rows += 1
                commitment = {
                    "method": _COMMITMENT_METHOD,
                    "value": h.hexdigest(),
                    "n": n_rows,
                }
            try:
                cur.execute("SELECT version_num FROM alembic_version")
                row = cur.fetchone()
                rev = row[0] if row else None
            except Exception:  # noqa: BLE001 - unstamped file: honest None
                rev = None
        finally:
            cur.close()
    except Exception:  # noqa: BLE001 - stats stay descriptive, never fail the backup
        _LOG.warning("backup: corpus stats failed", exc_info=True)
    finally:
        conn.close()
    return {"tables": counts, "articles_commitment": commitment}, rev


# --------------------------------------------------------------------------- #
#  Members
# --------------------------------------------------------------------------- #
@dataclass
class MemberFile:
    name: str  # artifact member name (zip-member-style relative path)
    role: str
    path: Path  # stable source file on disk


def _collect_side_members(tmp_dir: Path) -> list[MemberFile]:
    """Stage every non-corpus member into ``tmp_dir`` (small copies, stable while
    they hash + encrypt). Custody is snapshotted PRESERVING its encryption state —
    plaintext never touches disk at backup time. Keys are always included (the
    volume backup is always encrypted; D2)."""
    from src.backup.artifact import _ANNOTATIONS_DIR, _CUSTODY_DB, _KEYS_DIR
    from src.backup.artifact import _LOG_FILES as LOG_FILES
    from src.backup.artifact import _STATE_FILES as STATE_FILES
    from src.database.connect import snapshot_preserving

    base = data_dir()
    members: list[MemberFile] = []

    custody_src = base / _CUSTODY_DB
    if custody_src.exists():
        snap = tmp_dir / _CUSTODY_DB
        snapshot_preserving(custody_src, snap)
        members.append(MemberFile(_CUSTODY_DB, "custody", snap))

    def _stage(rel: str, role: str, src: Path) -> None:
        dst = tmp_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        members.append(MemberFile(rel, role, dst))

    for name in STATE_FILES:
        p = base / name
        if p.exists():
            _stage(name, "state", p)
    for name in LOG_FILES:
        p = base / name
        if p.exists():
            _stage(f"logs/{name}", "logs", p)
    ann = base / _ANNOTATIONS_DIR
    if ann.is_dir():
        for p in sorted(ann.rglob("*.json")):
            _stage(str(p.relative_to(base)), "annotations", p)
    keys = base / _KEYS_DIR
    if keys.is_dir():
        for p in sorted(keys.iterdir()):
            if p.is_file():
                _stage(str(p.relative_to(base)), "keys", p)
    return members


# --------------------------------------------------------------------------- #
#  Emit
# --------------------------------------------------------------------------- #
@dataclass
class _EmitState:
    dest: Path
    passphrase: str
    volume_size: int
    chunk_size: int
    pool: dict[tuple[str, int], dict[str, Any]]
    building_path: Path
    key_check: str
    should_stop: Callable[[], bool] | None
    progress_cb: Callable[[dict[str, Any]], None] | None
    run_token: str = ""
    phase: str = "members"
    reused: int = 0
    emitted: int = 0
    bytes_reused: int = 0
    bytes_emitted: int = 0

    def __post_init__(self) -> None:
        self.volumes: list[dict[str, Any]] = []

    def progress(self) -> None:
        if self.progress_cb is not None:
            self.progress_cb(
                {
                    "phase": self.phase,
                    "volumes_written": self.reused + self.emitted,
                    "volumes_reused": self.reused,
                    "volumes_emitted": self.emitted,
                    "bytes_written": self.bytes_emitted,
                    "bytes_reused": self.bytes_reused,
                }
            )

    def save_building(self) -> None:
        _write_json_atomic(
            self.building_path,
            {
                "kind": _BUILDING_KIND,
                "key_check": self.key_check,
                "volume_size": self.volume_size,
                "chunk_size": self.chunk_size,
                "volumes": self.volumes,
            },
        )


def _emit_member(st: _EmitState, mf: MemberFile) -> dict[str, Any]:
    """Slice ``mf`` into volumes: hash each plaintext slice, REUSE the existing
    volume when both the slice hash and the on-disk ciphertext hash match the
    pool (checksum, never size/mtime), else encrypt + emit. The source file must
    be stable for the duration (side members are staged copies; the corpus is
    frozen by the writer gate)."""
    size = mf.path.stat().st_size
    n_slices = max(1, math.ceil(size / st.volume_size)) if size else 1
    whole = hashlib.sha256()
    vol_names: list[str] = []
    with open(mf.path, "rb") as fh:
        for i in range(n_slices):
            if st.should_stop is not None and st.should_stop():
                st.save_building()
                raise VolumeStopped("volume backup stopped")
            offset = i * st.volume_size
            slice_len = max(0, min(st.volume_size, size - offset))
            sh = hashlib.sha256()
            fh.seek(offset)
            remaining = slice_len
            while remaining:
                b = fh.read(min(st.chunk_size, remaining))
                if not b:
                    raise VolumeError(f"{mf.path} shrank while being backed up")
                sh.update(b)
                whole.update(b)
                remaining -= len(b)
            psha = sh.hexdigest()
            pooled = st.pool.get((mf.name, i))
            reuse_path = st.dest / str(pooled.get("name", "")) if pooled else None
            if (
                pooled is not None
                and reuse_path is not None
                and pooled.get("plaintext_sha256") == psha
                and int(pooled.get("plaintext_bytes", -1)) == slice_len
                and reuse_path.exists()
                and _sha256_file(reuse_path) == pooled.get("sha256")
            ):
                entry = {
                    "name": reuse_path.name,
                    "member": mf.name,
                    "slice": i,
                    "sha256": pooled["sha256"],
                    "bytes": reuse_path.stat().st_size,
                    "plaintext_bytes": slice_len,
                    "plaintext_sha256": psha,
                }
                st.reused += 1
                st.bytes_reused += slice_len
            else:
                # A run-unique name: never overwrite a volume the previous
                # complete manifest still references (crash-safe refresh).
                vname = _vol_name(mf.name, i, st.run_token)
                vpath = st.dest / vname
                tmp = st.dest / (vname + ".oopart")
                fh.seek(offset)
                consumed, csha = encrypt_stream_to_hashed(
                    fh, tmp, st.passphrase, limit=slice_len, chunk_size=st.chunk_size
                )
                if consumed != slice_len:
                    tmp.unlink(missing_ok=True)
                    raise VolumeError(f"{mf.path} changed size while being backed up")
                os.replace(tmp, vpath)
                entry = {
                    "name": vname,
                    "member": mf.name,
                    "slice": i,
                    "sha256": csha,
                    "bytes": vpath.stat().st_size,
                    "plaintext_bytes": slice_len,
                    "plaintext_sha256": psha,
                }
                st.emitted += 1
                st.bytes_emitted += slice_len
            st.volumes.append(entry)
            vol_names.append(str(entry["name"]))
            st.save_building()
            st.progress()
    return {
        "name": mf.name,
        "role": mf.role,
        "plaintext_bytes": size,
        "plaintext_sha256": whole.hexdigest(),
        "volumes": vol_names,
    }


def _load_reuse_pool(
    dest: Path, passphrase: str
) -> tuple[dict[tuple[str, int], dict[str, Any]], list[str]]:
    """Entries from a previous complete manifest + a previous run's building log,
    ONLY when their ``key_check`` proves the same passphrase (mixing passphrases
    would poison the set: reused volumes would not decrypt with the new one)."""
    pool: dict[tuple[str, int], dict[str, Any]] = {}
    notes: list[str] = []
    for fname in (MANIFEST_NAME, BUILDING_NAME):
        p = dest / fname
        if not p.exists():
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            notes.append(f"unreadable {fname} at the destination ignored")
            continue
        kind = m.get("kind")
        if kind not in (STREAM_KIND, _BUILDING_KIND):
            notes.append(
                f"existing {kind or 'unknown'} set at the destination: no incremental "
                "reuse (older format); volumes are fully re-written"
            )
            continue
        if not _key_check_ok(m.get("key_check"), passphrase):
            notes.append(
                f"existing volumes ({fname}) were written under a DIFFERENT passphrase: "
                "nothing reused, full re-emission"
            )
            continue
        for v in m.get("volumes") or []:
            if all(k in v for k in ("member", "slice", "sha256", "plaintext_sha256")):
                pool[(str(v["member"]), int(v["slice"]))] = v
    return pool, notes


def _gc_orphan_volumes(dest: Path, manifest: dict[str, Any]) -> int:
    """After a successful finalize, remove volume/parity files the manifest does
    not reference (superseded generations from a refresh, slices of a shrunk
    member, an older format, a changed passphrase) plus leftover ``.oopart``
    temps. Runs ONLY once the new manifest is atomically in place — until then
    every file of the previous complete set stays untouched (crash-safe refresh).
    The manifest is the single source of truth for what the set contains."""
    referenced = {v["name"] for v in manifest.get("volumes") or []}
    par = manifest.get("parity") or {}
    referenced |= {pv["name"] for pv in par.get("volumes") or []}
    removed = 0
    for pattern in ("*.ooenc", "*.oopar", "*.oopart"):
        for p in dest.glob(pattern):
            if p.name not in referenced:
                p.unlink(missing_ok=True)
                removed += 1
    return removed


def cleanup_cancelled_build(dest: Path | str) -> int:
    """An explicitly CANCELLED build's cleanup: remove the resume log and every
    volume/parity/temp file NOT referenced by the last COMPLETE, SIGNED manifest —
    so a first backup's partials vanish entirely (a partial set must never be
    mistaken for a good one), while cancelling an incremental REFRESH leaves the
    previous complete backup fully intact and restorable."""
    destp = Path(dest)
    referenced: set[str] = set()
    try:
        m = load_manifest(destp)
        if m.get("kind") != STREAM_KIND or _manifest_signature_state(m) == "verified":
            # a legacy (v1) or verified v2 set survives a cancelled refresh
            referenced = {v["name"] for v in m.get("volumes") or []}
            referenced |= {
                pv["name"] for pv in (m.get("parity") or {}).get("volumes") or []
            }
        else:
            (destp / MANIFEST_NAME).unlink(missing_ok=True)  # unsigned index: not a set
    except (VolumeError, OSError, ValueError):
        (destp / MANIFEST_NAME).unlink(missing_ok=True)
    removed = 0
    for pattern in ("*.ooenc", "*.oopar", "*.oopart"):
        for p in destp.glob(pattern):
            if p.name not in referenced:
                p.unlink(missing_ok=True)
                removed += 1
    (destp / BUILDING_NAME).unlink(missing_ok=True)
    return removed


# --------------------------------------------------------------------------- #
#  DB-9: adaptive volume sizing (the parity ceiling)
# --------------------------------------------------------------------------- #
# The Reed-Solomon erasure parity is over GF(2^8) (src/backup/parity.py), so a set holds at
# most 255 data+parity volumes; at a FIXED 512 MiB that caps the corpus at ~128 GB — under
# the 5 TB mandate. Instead of fixing the SIZE, bound the COUNT: choose the volume size so the
# data-volume count N stays ~TARGET, keeping N+M comfortably under the ceiling at ANY scale
# while parity RAM stays band-bounded (independent of volume size). Below ~100 GB the 512 MiB
# floor wins, so the size — and every emitted volume — is BYTE-IDENTICAL to today.
TARGET_VOLUME_COUNT = 200        # data volumes to aim for; env OO_BACKUP_TARGET_VOLUMES
_NM_SAFETY_MARGIN = 240          # grow the size until N+M <= this (headroom under the 255 ceiling)


def _target_volume_count() -> int:
    try:
        return max(1, int(os.getenv("OO_BACKUP_TARGET_VOLUMES", str(TARGET_VOLUME_COUNT))))
    except ValueError:
        return TARGET_VOLUME_COUNT


def _adaptive_volume_size(
    member_sizes: list[int], parity_fraction: float, *, reserve_members: int = 2
) -> int:
    """Volume size that keeps the Reed-Solomon data+parity volume count (N+M) under the
    GF(2^8) 255-volume ceiling at ANY corpus size.

    The engine slices EACH member independently (``_emit_member``: ceil(size_m / vsize) per
    member), so the real data-volume count is the SUM of per-member ceils, NOT
    ceil(total/size) — a single division undercounts by up to one volume per member.
    ``member_sizes`` is every member known at sizing time (the corpus file + each side file);
    ``reserve_members`` covers members emitted AFTER sizing that are not in the list (the
    manifest.json member, a possible residual WAL member). M = max(1, ceil(parity_fraction *
    N)) mirrors write_parity (which always emits >= 1 parity volume).

    Start at max(512 MiB floor, ceil(total/TARGET)) so N is ~TARGET, then grow the size
    (shrinking every member's slice count) until N+M <= the safety margin. Below ~100 GB the
    floor wins -> byte-identical to the fixed 512 MiB behaviour. Terminates: the size only
    grows, capped at total (every member -> 1 slice; if the member COUNT alone exceeds the
    margin — hundreds of members — no size can help, and write_parity's own N+M<256 guard +
    the crash-safe finalize catch it without touching the previous backup)."""
    sizes = [s for s in member_sizes if s > 0]
    total = sum(sizes)
    if total <= 0:
        return VOLUME_SIZE_DEFAULT
    target = _target_volume_count()
    frac = max(0.0, parity_fraction)
    reserve = max(0, reserve_members)
    vsize = max(VOLUME_SIZE_DEFAULT, math.ceil(total / target))
    while True:
        n = sum(max(1, math.ceil(s / vsize)) for s in sizes) + reserve
        m = max(1, math.ceil(frac * n))
        if n + m <= _NM_SAFETY_MARGIN or vsize >= total:
            return vsize
        vsize = int(vsize * 1.1) + 1  # grow ~10% to shrink each member's slice count


def _previous_volume_size(dest: Path) -> int | None:
    """The volume_size recorded by the previous COMPLETE manifest at ``dest`` (for the
    tier-crossing note), or None when there is no readable prior set."""
    p = dest / MANIFEST_NAME
    if not p.exists():
        return None
    try:
        return int(json.loads(p.read_text(encoding="utf-8"))["volume_size"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


# --------------------------------------------------------------------------- #
#  Write
# --------------------------------------------------------------------------- #
def write_stream_backup(
    dest_dir: Path | str,
    passphrase: str,
    *,
    include_newsletters: bool = True,
    volume_size: int | None = None,
    parity_fraction: float = 0.1,
    should_stop: Callable[[], bool] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    corpus_source: CorpusSource | None = None,
    side_members: list[MemberFile] | None = None,
) -> dict[str, Any]:
    """Build (or incrementally refresh / resume) an oo-volumes-2 set at ``dest_dir``.

    See the module docstring for the guarantees. ``corpus_source``/``side_members``
    are seams for tests and benches; production uses the live store + data dir.
    Returns a measured summary (volumes reused/emitted, gate-held seconds, wall)."""
    if not passphrase:
        raise VolumeError("the volume backup is always encrypted: a passphrase is required")
    explicit_vsize = volume_size is not None  # an explicit size is honoured; else DB-9 adapts
    vsize = volume_size or VOLUME_SIZE_DEFAULT
    if vsize < 1024:
        raise VolumeError("volume size too small")
    t0 = time.monotonic()
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    sweep_stale_backup_temps(dest)
    notes: list[str] = []
    pool, pool_notes = _load_reuse_pool(dest, passphrase)
    notes.extend(pool_notes)
    resumed = bool(pool) and (dest / BUILDING_NAME).exists()

    tmp_dir = dest / f".bak-build-{secrets.token_hex(6)}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    gate_held_s = 0.0
    with active_staging(tmp_dir):
        try:
            st = _EmitState(
                dest=dest,
                passphrase=passphrase,
                volume_size=vsize,
                chunk_size=_CHUNK,
                pool=pool,
                building_path=dest / BUILDING_NAME,
                key_check=_key_check(passphrase),
                should_stop=should_stop,
                progress_cb=progress_cb,
                run_token=secrets.token_hex(3),
            )
            st.phase = "collecting"
            st.progress()
            side = side_members if side_members is not None else _collect_side_members(tmp_dir)
            src = (
                corpus_source
                if corpus_source is not None
                else _live_corpus_source(tmp_dir, include_newsletters, notes)
            )
            corpus_bytes = src.path.stat().st_size
            side_sizes = [m.path.stat().st_size for m in side]
            side_bytes = sum(side_sizes)
            if not explicit_vsize:
                # DB-9: size volumes so N+M stays under the GF(2^8) parity ceiling at any scale
                # (byte-identical below ~100 GB where the 512 MiB floor wins). Size against the
                # REAL per-member volume count (each member slices independently), NOT
                # ceil(total/size), which undercounts by up to one volume per member. Update
                # BOTH vsize (recorded in the manifest) and st.volume_size (drives the slicing)
                # BEFORE the first _emit_member, so a torn manifest can never mislabel the size.
                adaptive = _adaptive_volume_size([*side_sizes, corpus_bytes], parity_fraction)
                if adaptive != vsize:
                    prev_vsize = _previous_volume_size(dest)
                    vsize = st.volume_size = adaptive
                    notes.append(
                        f"adaptive volume sizing: {adaptive // (1024 * 1024)} MiB volumes so the "
                        f"Reed-Solomon N+M stays under the GF(2^8) 255-volume ceiling at "
                        f"{(corpus_bytes + side_bytes) / (1024 ** 3):.1f} GiB "
                        f"(target ~{_target_volume_count()} data volumes)"
                    )
                    if prev_vsize is not None and prev_vsize != adaptive:
                        notes.append(
                            f"volume size changed {prev_vsize // (1024 * 1024)} -> "
                            f"{adaptive // (1024 * 1024)} MiB (the corpus crossed a size tier): "
                            "this run re-emits all volumes; the previous complete backup is "
                            "replaced atomically only on success (never orphaned mid-run)"
                        )
            _preflight_dest(
                dest, corpus_bytes, side_bytes, parity_fraction, reuse_possible=bool(pool)
            )

            members_out: list[dict[str, Any]] = []
            st.phase = "members"
            for mf in side:
                e = _emit_member(st, mf)
                members_out.append(e)

            st.phase = "corpus (writes paused)"
            st.progress()
            gate_t0 = time.monotonic()
            wal_member: str | None = None
            with src.freeze() as wal_path:
                ce = _emit_member(st, MemberFile(src.member_name, "corpus", src.path))
                ce["sqlcipher"] = src.encrypted
                members_out.append(ce)
                if wal_path is not None:
                    we = _emit_member(
                        st, MemberFile(src.member_name + "-wal", "corpus-wal", wal_path)
                    )
                    we["sqlcipher"] = src.encrypted
                    members_out.append(we)
                    wal_member = we["name"]
                    notes.append(
                        "the live WAL could not fully checkpoint (a long reader was "
                        "active); the residual WAL rides as a member and is folded "
                        "back in at restore"
                    )
                stats, arev = _corpus_facts(src.path, key=src.facts_key)
            gate_held_s = time.monotonic() - gate_t0

            st.phase = "finalizing"
            st.progress()
            envelope = _build_envelope(members_out, src, stats, arev, notes)
            env_path = tmp_dir / "manifest.json"
            env_path.write_text(
                json.dumps(envelope, ensure_ascii=False, indent=1), encoding="utf-8"
            )
            members_out.append(
                _emit_member(st, MemberFile("manifest.json", "manifest", env_path))
            )

            vman: dict[str, Any] = {
                "kind": STREAM_KIND,
                "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "volume_size": vsize,
                "chunk_size": _CHUNK,
                "key_check": st.key_check,
                "corpus_member": src.member_name,
                "corpus_encrypted": src.encrypted,
                "wal_member": wal_member,
                "plaintext_bytes": sum(int(m["plaintext_bytes"]) for m in members_out),
                "members": members_out,
                "volumes": st.volumes,
                "parity": None,
                "notes": notes,
            }

            # CRASH-SAFE FINALIZE: build the fully-signed (+parity) manifest in
            # memory and swap the canonical dest/volumes.json exactly ONCE. The
            # previous complete backup's signed manifest stays intact at the
            # canonical path until that single atomic replace — so an interrupt,
            # a kill, OR a parity failure (e.g. the GF(2^8) N+M ceiling at very
            # large corpora) leaves the previous backup fully verifiable and
            # restorable, and no UNSIGNED manifest is ever written to the
            # canonical path (which cleanup_cancelled_build would treat as a
            # disposable partial and delete). Volumes carry per-run names, so
            # superseded ones are garbage-collected only AFTER the swap.
            parity: dict[str, Any] | None = None
            from src.backup.parity import parity_available

            if parity_available():
                st.phase = "parity"
                st.progress()
                from src.backup.parity import write_parity

                # Records parity into vman in memory + writes the .oopar files;
                # never touches dest/volumes.json (write_manifest=False).
                parity = write_parity(
                    dest,
                    parity_fraction=parity_fraction,
                    manifest=vman,
                    write_manifest=False,
                )

            # Sign LAST so the signature covers the parity block too, then swap
            # the canonical manifest atomically as the single commit point.
            vman.pop("signature", None)
            vman["signature"] = _sign_manifest(vman)
            _write_json_atomic(dest / MANIFEST_NAME, vman)
            final = vman
            (dest / BUILDING_NAME).unlink(missing_ok=True)
            gc_removed = _gc_orphan_volumes(dest, final)

            return {
                "envelope": envelope,
                "format": STREAM_KIND,
                "volumes": len(st.volumes),
                "volumes_reused": st.reused,
                "volumes_emitted": st.emitted,
                "bytes_reused": st.bytes_reused,
                "bytes_emitted": st.bytes_emitted,
                "plaintext_bytes": vman["plaintext_bytes"],
                "corpus_bytes": corpus_bytes,
                "corpus_encrypted": src.encrypted,
                "parity": parity,
                "parity_available": parity_available(),
                "dest": str(dest),
                "resumed": resumed,
                "orphans_removed": gc_removed,
                "gate_held_s": round(gate_held_s, 3),
                "wall_s": round(time.monotonic() - t0, 3),
                "notes": notes,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _preflight_dest(
    dest: Path,
    corpus_bytes: int,
    side_bytes: int,
    parity_fraction: float,
    *,
    reuse_possible: bool,
) -> None:
    """Refuse loudly up front when the destination clearly lacks room. Existing
    volumes count toward the budget ONLY when they can actually be reused — a
    passphrase change (or an unreadable manifest) re-emits everything while the
    previous set stays on disk until the finalize garbage-collects it, so the
    budget must then cover both generations at once."""
    from src.backup.artifact import preflight_free_space

    needed = int((corpus_bytes + side_bytes) * (1.0 + max(0.0, parity_fraction)) * 1.02)
    needed += 64 * 1024 * 1024
    if reuse_possible:
        existing = 0
        for p in dest.glob("*.ooenc"):
            try:
                existing += p.stat().st_size
            except OSError:  # pragma: no cover
                continue
        needed = max(needed - existing, int(corpus_bytes * max(0.0, parity_fraction)))
    preflight_free_space(dest, needed, what="volume backup")


def _build_envelope(
    members_out: list[dict[str, Any]],
    src: CorpusSource,
    stats: dict[str, Any],
    alembic_rev: str | None,
    notes: list[str],
) -> dict[str, Any]:
    """The signed oo-backup-2 manifest envelope, carried as the ``manifest.json``
    member — same schema as the zip artifact so the staging/merge path reads it
    unchanged; ``container``/``corpus_encrypted`` are additive facts."""
    from src.backup.artifact import BACKUP_SCHEMA, _excluded_inventory
    from src.reporting.evidence import (
        canonical_bytes,
        load_or_create_signing_key,
        public_key_hex,
    )
    from src.utils.export_envelope import app_version

    key = load_or_create_signing_key()
    manifest = {
        "backup_schema": BACKUP_SCHEMA,
        "app_version": app_version(),
        "alembic_rev": alembic_rev,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "encrypted": True,
        "keys_included": True,
        "container": STREAM_KIND,
        "corpus_member": src.member_name,
        "corpus_encrypted": src.encrypted,
        "members": [
            {
                "name": m["name"],
                "role": m["role"],
                "sha256": m["plaintext_sha256"],
                "bytes": m["plaintext_bytes"],
                "sqlcipher": bool(m.get("sqlcipher")),
            }
            for m in members_out
        ],
        "excluded": _excluded_inventory(),
        "corpus": stats,
        "notes": list(notes),
    }
    return {
        "manifest": manifest,
        "signature": key.sign(canonical_bytes(manifest)).hex(),
        "public_key": public_key_hex(key),
        "algorithm": "ed25519",
    }


# --------------------------------------------------------------------------- #
#  Verify
# --------------------------------------------------------------------------- #
def verify_stream_backup(
    src_dir: Path | str, passphrase: str | None = None
) -> dict[str, Any]:
    """End-to-end verification of a volume set WITHOUT touching the live corpus.

    Without a passphrase: manifest signature, every data + parity volume checksum,
    member/slice structure, orphan files — nothing decrypted, nothing written.
    With the passphrase: additionally stream-decrypts EVERY volume into a hash
    sink (still nothing written), checks each member's whole-plaintext checksum,
    and cross-checks the signed inner envelope's member hashes against the volume
    manifest. Reports exactly which volumes are bad and whether parity can still
    recover them."""
    src = Path(src_dir)
    m = load_manifest(src)
    if m.get("kind") == STREAM_KIND:
        _require_safe_manifest_names(m)
    report: dict[str, Any] = {
        "kind": m.get("kind"),
        "ok": True,
        "problems": [],
        "bad_volumes": [],
        "missing_volumes": [],
        "volumes": len(m.get("volumes") or []),
        "signature": None,
        "parity": None,
        "decrypted": False,
        "method": (
            "manifest signature + per-volume ciphertext SHA-256 + structure; "
            "with the passphrase every volume is stream-decrypted into a hash "
            "sink and member/envelope checksums are cross-checked"
        ),
    }

    def _fail(problem: str) -> None:
        report["ok"] = False
        report["problems"].append(problem)

    if m.get("kind") == STREAM_KIND:
        state = _manifest_signature_state(m)
        report["signature"] = state
        if state != "verified":
            _fail(
                f"volume manifest signature: {state} — the set's index cannot be "
                "trusted (an interrupted finalize or tampering); re-run the backup"
            )
    else:
        report["signature"] = "not-applicable (oo-volumes-1 sets are unsigned)"

    status = verify_volume_set(src)
    report["bad_volumes"] = status["bad"]
    report["missing_volumes"] = status["missing"]
    if status["bad"]:
        _fail("corrupt or missing data volumes: " + ", ".join(sorted(status["bad"])))

    par = m.get("parity")
    bad_parity: list[str] = []
    if par:
        for pv in par.get("volumes") or []:
            p = src / pv["name"]
            if not p.exists() or _sha256_file(p) != pv["sha256"]:
                bad_parity.append(pv["name"])
        usable = int(par.get("count", 0)) - len(bad_parity)
        report["parity"] = {
            "volumes": int(par.get("count", 0)),
            "bad": bad_parity,
            "tolerance_remaining": max(0, usable),
        }
        if bad_parity:
            _fail(
                "corrupt parity volumes (data may be intact but protection is "
                "reduced — re-run the backup to regenerate parity): "
                + ", ".join(sorted(bad_parity))
            )
        report["recoverable"] = bool(status["bad"]) and len(status["bad"]) <= max(0, usable)
    else:
        report["recoverable"] = False

    if m.get("kind") == STREAM_KIND:
        vol_by_name = {v["name"]: v for v in m.get("volumes") or []}
        for mm in m.get("members") or []:
            for vname in mm.get("volumes") or []:
                if vname not in vol_by_name:
                    _fail(f"member {mm['name']} references a volume missing from the index: {vname}")
        known = set(vol_by_name) | {pv["name"] for pv in (par or {}).get("volumes") or []}
        orphans = sorted(
            p.name
            for p in list(src.glob("*.ooenc")) + list(src.glob("*.oopar"))
            if p.name not in known
        )
        if orphans:
            report["orphans"] = orphans  # informational: not part of the set

    if passphrase and m.get("kind") == STREAM_KIND and not status["bad"]:
        if not _key_check_ok(m.get("key_check"), passphrase):
            _fail("the passphrase does not match this volume set")
        else:
            report["decrypted"] = True
            envelope_bytes: bytearray | None = None
            for mm in m.get("members") or []:
                h = hashlib.sha256()
                collect: bytearray | None = (
                    bytearray() if mm.get("name") == "manifest.json" else None
                )

                def _sink(b: bytes, _h: Any = h, _c: bytearray | None = collect) -> None:
                    _h.update(b)
                    if _c is not None:
                        _c.extend(b)

                try:
                    for vname in mm.get("volumes") or []:
                        decrypt_stream(src / vname, _sink, passphrase)
                except EncryptionError as exc:
                    _fail(f"member {mm['name']} failed to decrypt: {exc}")
                    continue
                if h.hexdigest() != mm.get("plaintext_sha256"):
                    _fail(f"member {mm['name']} failed its whole-plaintext checksum")
                if collect is not None:
                    envelope_bytes = collect
            if envelope_bytes is not None:
                report.update(_crosscheck_envelope(bytes(envelope_bytes), m))
                if report.get("envelope_signature") == "bad-signature" or report.get(
                    "envelope_mismatches"
                ):
                    _fail("the signed inner envelope does not match the volume index")
    return report


def _crosscheck_envelope(env_bytes: bytes, vman: dict[str, Any]) -> dict[str, Any]:
    """Verify the inner oo-backup-2 envelope signature and tie its member hashes
    to the volume manifest's (the defense against a consistently-rewritten index)."""
    out: dict[str, Any] = {}
    try:
        envelope = json.loads(env_bytes.decode("utf-8"))
    except ValueError:
        return {"envelope_signature": "bad-signature", "envelope_mismatches": ["unparseable"]}
    manifest = envelope.get("manifest") or {}
    state = "unsigned"
    if envelope.get("signature") and envelope.get("public_key"):
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            from src.reporting.evidence import canonical_bytes

            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(envelope["public_key"]))
            pub.verify(bytes.fromhex(envelope["signature"]), canonical_bytes(manifest))
            state = "verified"
        except Exception:  # noqa: BLE001
            state = "bad-signature"
    out["envelope_signature"] = state
    env_members = {mm["name"]: mm for mm in manifest.get("members") or []}
    mismatches: list[str] = []
    for mm in vman.get("members") or []:
        name = mm.get("name")
        if name == "manifest.json":
            continue  # the envelope cannot list itself
        em = env_members.get(name)
        if em is None:
            mismatches.append(f"{name}: absent from the signed envelope")
        elif em.get("sha256") != mm.get("plaintext_sha256"):
            mismatches.append(f"{name}: envelope/index checksum disagreement")
    out["envelope_mismatches"] = mismatches
    return out


# --------------------------------------------------------------------------- #
#  Read / restore staging
# --------------------------------------------------------------------------- #
def read_stream_backup(
    src_dir: Path | str,
    passphrase: str,
    staging_root: Path | None = None,
    *,
    corpus_passphrase: str | None = None,
    include_merge_budget: bool = True,
) -> "StagedArtifact":
    """Verify + (parity-)recover + reassemble an oo-volumes-2 set into a staged
    artifact the additive merge engine consumes. Streams member by member
    (bounded RAM); an encrypted corpus/custody member is converted to the
    plaintext staged copy the merge requires — the only plaintext materialization,
    inside the transient ``.restore-*`` staging. Raises loudly on anything that
    cannot be verified."""
    src = Path(src_dir)
    m = load_manifest(src)
    if m.get("kind") != STREAM_KIND:
        raise VolumeError(f"not an {STREAM_KIND} set (kind={m.get('kind')!r})")
    _require_safe_manifest_names(m)
    sig_state = _manifest_signature_state(m)
    if sig_state == "bad-signature":
        raise VolumeError(
            "the volume manifest fails its signature check — the set's index has "
            "been altered or corrupted; refusing to restore from it"
        )

    # Stage-A timing (field-feedback Session A §4, "instrument first"): the
    # four sub-steps of a volume-set restore have genuinely different cost
    # profiles on a large set -- verify/parity-recover can read the WHOLE set,
    # reassembly is per-volume decrypt+copy, prepare_corpus_files is where the
    # SQLCipher sqlcipher_export() plaintext conversion lives (likely the
    # single most expensive step on a big encrypted corpus), and finalize is
    # the manifest signature + per-member hash re-check.
    stage_a_timings: dict[str, float] = {}
    t0 = time.monotonic()
    status = verify_volume_set(src)
    if status["bad"]:
        from src.backup.parity import recover_volumes

        unrepaired = (
            recover_volumes(m, status["bad"], out_dir=src) if m.get("parity") else status["bad"]
        )
        if unrepaired:
            raise VolumeError(
                "corrupt or missing volumes that could not be recovered: "
                + ", ".join(sorted(unrepaired))
            )
    stage_a_timings["verify_and_parity_recover"] = round(time.monotonic() - t0, 3)

    root = staging_root or data_dir()
    _preflight_staging(root, m, include_merge_budget=include_merge_budget)
    staging = root / f".restore-{secrets.token_hex(8)}"
    staging.mkdir(parents=True, exist_ok=False)
    with active_staging(staging):
        try:
            t1 = time.monotonic()
            vol_by_name = {v["name"]: v for v in m.get("volumes") or []}
            for mm in m.get("members") or []:
                out_path = staging / mm["name"]
                out_path.parent.mkdir(parents=True, exist_ok=True)
                h = hashlib.sha256()
                with open(out_path, "wb") as fout:
                    for vname in mm.get("volumes") or []:
                        if vname not in vol_by_name:
                            raise VolumeError(
                                f"member {mm['name']} references an unknown volume {vname}"
                            )

                        def _sink(b: bytes, _f: Any = fout, _h: Any = h) -> None:
                            _f.write(b)
                            _h.update(b)

                        decrypt_stream(src / vname, _sink, passphrase)
                if h.hexdigest() != mm.get("plaintext_sha256"):
                    raise VolumeError(
                        f"member {mm['name']} failed its plaintext checksum after reassembly"
                    )
            stage_a_timings["reassemble"] = round(time.monotonic() - t1, 3)

            t2 = time.monotonic()
            verified_absent = _prepare_staged_corpus_files(
                staging, m, passphrase, corpus_passphrase
            )
            stage_a_timings["prepare_corpus_files"] = round(time.monotonic() - t2, 3)
            from src.backup.artifact import _finalize_staged

            t3 = time.monotonic()
            staged = _finalize_staged(
                staging, was_encrypted=True, verified_absent=verified_absent
            )
            stage_a_timings["finalize"] = round(time.monotonic() - t3, 3)
            staged.stage_a_timings = stage_a_timings
            return staged
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def _preflight_staging(
    root: Path, m: dict[str, Any], *, include_merge_budget: bool = True
) -> None:
    """Staging needs: every member's plaintext + a plaintext conversion of an
    encrypted corpus/custody member + (in the app's restore flow, where a merge
    follows) the merge's working copy of the live DB. A caller that only STAGES
    (the benchmark's round-trip probe) passes ``include_merge_budget=False`` —
    each step preflights what it will actually do, never less."""
    from src.backup.artifact import preflight_free_space

    members = m.get("members") or []
    total = sum(int(mm.get("plaintext_bytes", 0)) for mm in members)
    if m.get("corpus_encrypted"):
        corpus = next((mm for mm in members if mm.get("role") == "corpus"), None)
        if corpus:
            total += int(corpus.get("plaintext_bytes", 0))
    if include_merge_budget:
        try:
            from src.backup.sqlite_backup import live_db_path

            p = live_db_path()
            total += p.stat().st_size if p.exists() else 0
        except Exception:  # noqa: BLE001 - no live store (fresh install): staging-only
            pass
    preflight_free_space(root, total + 64 * 1024 * 1024, what="restore staging")


def _prepare_staged_corpus_files(
    staging: Path, m: dict[str, Any], passphrase: str, corpus_passphrase: str | None
) -> frozenset[str]:
    """Fold a carried WAL, convert SQLCipher members (corpus/custody) to the
    plaintext staged copies the merge engine reads, and return the member names
    whose bytes were verified during reassembly but then removed to reclaim disk."""
    from src.database.connect import get_passphrase, is_encrypted_file

    verified_absent: set[str] = set()
    corpus_member = str(m.get("corpus_member") or "corpus.db")
    wal_member = m.get("wal_member")
    cpath = staging / corpus_member
    keys = [k for k in (corpus_passphrase, get_passphrase(), passphrase) if k]

    if m.get("corpus_encrypted"):
        plain = staging / "corpus.db"
        # Opening with the right key also replays a carried WAL before export.
        _export_plaintext_with_keys(cpath, plain, keys)
        cpath.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            cpath.with_name(cpath.name + suffix).unlink(missing_ok=True)
        verified_absent.add(corpus_member)
        if wal_member:
            verified_absent.add(str(wal_member))
    elif wal_member and (staging / str(wal_member)).exists():
        _fold_plain_wal(cpath)
        (staging / str(wal_member)).unlink(missing_ok=True)
        cpath.with_name(cpath.name + "-shm").unlink(missing_ok=True)
        verified_absent.add(str(wal_member))
        # folding the WAL legitimately rewrote the staged corpus AFTER its bytes
        # were checksum-verified during reassembly — exempt it from the re-check.
        verified_absent.add(corpus_member)

    custody = staging / "custody_log.db"
    if custody.exists() and is_encrypted_file(custody):
        tmp = staging / "custody_log.db.plain"
        _export_plaintext_with_keys(custody, tmp, keys)
        os.replace(tmp, custody)
        # The plaintext differs from the manifest's (encrypted) member bytes —
        # those were verified during reassembly, before the conversion.
        verified_absent.add("custody_log.db")
    return frozenset(verified_absent)


def _fold_plain_wal(db_path: Path) -> None:
    import sqlite3

    con = sqlite3.connect(str(db_path))
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()
    finally:
        con.close()


def _export_plaintext_with_keys(src: Path, dest: Path, keys: list[str]) -> None:
    """Decrypt a staged SQLCipher member into a plaintext copy, trying each
    candidate key in order. Fails loudly (naming the fix) when none opens it."""
    from src.database.connect import WrongPassphraseError, connect

    last: Exception | None = None
    for key in dict.fromkeys(keys):
        try:
            conn = connect(src, key=key, check_same_thread=False)
        except WrongPassphraseError as exc:
            last = exc
            continue
        except Exception as exc:  # noqa: BLE001 - driver/file trouble: keep the cause
            last = exc
            continue
        try:
            dest.unlink(missing_ok=True)
            conn.execute("ATTACH DATABASE ? AS snap KEY ''", (str(dest),))
            cur = conn.cursor()
            try:
                cur.execute("SELECT sqlcipher_export('snap')")
            finally:
                cur.close()
            conn.execute("DETACH DATABASE snap")
            return
        finally:
            conn.close()
    raise VolumeError(
        "the corpus member is SQLCipher-encrypted and none of the available "
        "passphrases open it — the backup carries the source store's own "
        "encryption; pass that passphrase (corpus_passphrase) to restore"
    ) from last
