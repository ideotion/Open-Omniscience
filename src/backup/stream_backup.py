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

A BACKUP NEVER CARRIES A RESIDUAL WRITE-AHEAD LOG (2026-10-01). The live file is
streamed only when it alone is a complete image: every committed frame of the
log is in the main file (the checkpoint's own result row says so, not the size
of the ``-wal`` file). When a long reader keeps frames only in the log, the
corpus is COPIED first through SQLite's own read-transaction snapshot onto the
destination drive, the copy is sized and refused for before it is made, and the
member streams from the copy; the summary reports the copy's seconds and bytes
beside ``gate_held_s``. Old archives that carry a ``corpus-wal`` member still
restore (the restore side is unchanged).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import platform
import re
import secrets
import shutil
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack, contextmanager
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
#: How long the in-window drain waits for a reader to leave before the corpus is copied
#: instead. It protects ONE case: a transient reader. Up to this many seconds of paused
#: writers spare a copy of minutes when the reader goes away; against a persistent reader the
#: whole wait buys nothing (src/scheduler/hygiene.py measured a pinned TRUNCATE returning the
#: same busy flag after the full timeout), which is why a free PASSIVE step runs first and a
#: reader that only holds the END of the log never spends it. Chosen, not measured.
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
_OWNER_MARKER = ".owner.json"
_DESTS_FILE = "backup-temp-dests.json"
_DESTS_KEEP = 16
_DESTS_LOCK = threading.Lock()  # the export thread and the boot sweep both rewrite the file
# How many times each destination has been remembered in this process (under ``_DESTS_LOCK``): a
# sweep that found a drive empty drops it only if no export remembered it again since.
_DESTS_SEQ: dict[str, int] = {}


def _machine_tag() -> str | None:
    """A stable tag of THIS machine, beside its hostname: two machines that share a default name
    (``raspberrypi``, ``ubuntu``) and one backup folder on a NAS would otherwise judge each other's
    pids. The machine id is hashed with this app's own label (a raw ``/etc/machine-id`` is meant to
    stay on the machine, and the marker is written to a drive that may be shared); ``None`` where
    the system keeps none (Windows, macOS), where the hostname alone applies."""
    for name in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            raw = Path(name).read_text(encoding="ascii").strip()
        except (OSError, ValueError):
            continue
        if raw:
            return hashlib.sha256(f"open-omniscience-backup-owner:{raw}".encode()).hexdigest()[:16]
    return None


def _write_owner_marker(staging: Path) -> None:
    """Record WHICH process made this staging dir (pid + its start time), so a sweep can tell
    a dead owner's leftover from a live job's dir without waiting a day. A backup that made a
    temporary copy of the corpus and then crashed left 8 to 40 GB on the user's drive, and the
    24 h age rule meant a retry within a day was refused for lack of the very space it held.
    Best-effort: a dir without a marker keeps the age rule."""
    try:
        import psutil

        proc = psutil.Process()
        (staging / _OWNER_MARKER).write_text(
            json.dumps(
                {
                    "pid": proc.pid,
                    "started": round(proc.create_time(), 3),
                    "host": platform.node(),
                    "machine": _machine_tag(),
                }
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001 - the age rule still covers a dir with no marker
        _LOG.debug("backup: could not write the staging owner marker", exc_info=True)


def _owner_state(staging: Path) -> str:
    """``"alive"`` / ``"dead"`` for a dir whose marker names a process on THIS machine,
    ``"unknown"`` for a dir with no readable marker, a marker from another machine (a shared
    drive: its pid means nothing here, and the hostname alone does not tell machines apart, so the
    machine tag is compared too when both sides have one) or the marker of THIS process itself
    (a live job of it is protected by the registry; then only the age rule applies). A recycled pid
    is told apart by the process start time recorded beside it, and that includes this process's own
    pid: a container or a service that is given the same pid at every start finds its dead
    predecessor's marker naming the same pid with another start time, and that is a dead owner."""
    try:
        data = json.loads((staging / _OWNER_MARKER).read_text(encoding="utf-8"))
        pid, started = int(data["pid"]), float(data["started"])
        host = data.get("host")
        machine = data.get("machine")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return "unknown"
    if host is not None and str(host) != platform.node():
        return "unknown"  # another machine's job on a shared drive
    if machine is not None and machine != _machine_tag():
        return "unknown"  # the same name on another machine, or a tag this one cannot read
    try:
        import psutil

        if pid == os.getpid():
            if abs(psutil.Process().create_time() - started) < 1.0:
                return "unknown"  # a live job of this process is protected by the registry, not here
            return "dead"  # the same pid with another start time: this process's dead predecessor
        if not psutil.pid_exists(pid):
            return "dead"
        return "alive" if abs(psutil.Process(pid).create_time() - started) < 1.0 else "dead"
    except Exception as exc:  # noqa: BLE001 - psutil.NoSuchProcess is "dead", the rest "unknown"
        return "dead" if type(exc).__name__ == "NoSuchProcess" else "unknown"


def remember_snapshot_destination(dest: Path | str) -> None:
    """Remember a destination that was given a temporary copy of the corpus, in the data dir, so
    the boot janitor can sweep a crash's leftover there even if the user never exports to that
    drive again (:func:`sweep_remembered_destinations`). Best-effort, bounded."""
    try:
        path = data_dir() / _DESTS_FILE
        d = str(Path(dest).resolve())
        with _DESTS_LOCK:
            try:
                known = [str(x) for x in json.loads(path.read_text(encoding="utf-8"))]
            except (OSError, ValueError, TypeError):
                known = []
            known = [d] + [x for x in known if x != d]
            _DESTS_SEQ[d] = _DESTS_SEQ.get(d, 0) + 1
            _write_json_atomic(path, known[:_DESTS_KEEP])
    except Exception:  # noqa: BLE001 - a missed entry costs only the next-export sweep
        _LOG.debug("backup: could not remember the snapshot destination", exc_info=True)


def sweep_remembered_destinations() -> int:
    """Boot janitor for a crash that left a temporary corpus copy on a backup drive: sweep each
    remembered destination (dead-owner dirs at once, unmarked ones by age), drop the ones that
    hold nothing more, and SKIP a destination that is not mounted (kept for later). Returns the
    number of staging dirs removed."""
    path = data_dir() / _DESTS_FILE
    try:
        known = [str(x) for x in json.loads(path.read_text(encoding="utf-8"))]
    except (OSError, ValueError, TypeError):
        return 0
    removed, done = 0, {}
    for d in known:
        root = Path(d)
        if not root.is_dir():
            continue  # an unmounted drive: kept, look again at the next boot
        with _DESTS_LOCK:
            seen_seq = _DESTS_SEQ.get(d, 0)
        removed += sweep_stale_backup_temps(root)
        try:
            left = any(
                p.is_dir() and p.name.startswith(".bak-build-") for p in root.iterdir()
            )
        except OSError:
            left = True
        if not left:
            done[d] = seen_seq
    if done:
        # Re-read under the lock and drop only what THIS sweep emptied: an export that remembered
        # a new drive while the sweep ran (it can take minutes on a slow mount) keeps its entry,
        # and so does a drive an export remembered AGAIN after the sweep had found it empty (its
        # staging dir is live, and a crash would leave it with no entry to be swept from).
        try:
            with _DESTS_LOCK:
                try:
                    now = [str(x) for x in json.loads(path.read_text(encoding="utf-8"))]
                except (OSError, ValueError, TypeError):
                    now = []
                keep = [x for x in now if x not in done or _DESTS_SEQ.get(x, 0) != done[x]]
                if keep != now:
                    _write_json_atomic(path, keep)
        except Exception:  # noqa: BLE001
            _LOG.debug("backup: could not update the remembered destinations", exc_info=True)
    return removed


_REMEMBERED_SWEEP_LOCK = threading.Lock()
_REMEMBERED_SWEEP: threading.Thread | None = None


def sweep_remembered_destinations_in_background() -> threading.Thread | None:
    """Run :func:`sweep_remembered_destinations` on a daemon thread, one at a time.

    On its own thread because the first thing it does to a destination is ask whether it is there,
    and a backup drive that is a stale network mount can hold that one call for minutes: the boot
    path and the maintenance pass that call the janitor must never wait on somebody else's drive.
    Returns the thread (``None`` when a sweep is already running), so a test can join it. A mount
    that never answers holds that one thread, and with it every later sweep, until the process
    ends; being a daemon it never delays the exit."""
    global _REMEMBERED_SWEEP
    with _REMEMBERED_SWEEP_LOCK:
        if _REMEMBERED_SWEEP is not None and _REMEMBERED_SWEEP.is_alive():
            return None

        def run() -> None:
            try:
                n = sweep_remembered_destinations()
                if n:
                    _LOG.info("backup: removed %d leftover temporary copy dir(s) from a backup drive", n)
            except Exception:  # noqa: BLE001 - a janitor never takes anything down
                _LOG.warning("backup: the remembered-destination sweep failed", exc_info=True)

        t = threading.Thread(target=run, name="oo-backup-remembered-sweep", daemon=True)
        _REMEMBERED_SWEEP = t
        t.start()
        return t


def sweep_stale_backup_temps(root: Path | str, *, max_age_hours: float = 24.0) -> int:
    """Remove ORPHANED backup/restore temps under ``root`` (non-recursive):
    ``.bak-build-*`` / ``.restore-*`` staging dirs and ``*.oopart`` /
    ``*.reassembling`` files older than ``max_age_hours``. A LIVE job's paths are
    protected twice over — the active-staging registry and the age guard (a dir
    being written has a fresh mtime). A ``.bak-build-*`` dir that carries an owner marker
    is judged by its OWNER instead: a dead owner's leftover goes at once whatever its age,
    a live owner's dir stays. Never touches volumes, manifests or the
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
                owner = _owner_state(p) if p.name.startswith(".bak-build-") else "unknown"
                if owner == "alive":
                    continue
                if owner == "dead":
                    shutil.rmtree(p, ignore_errors=True)
                    removed += 0 if p.exists() else 1  # a read-only drive removes nothing
                    continue
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
                    removed += 0 if p.exists() else 1
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
def _write_json_atomic(path: Path, payload: Any) -> None:
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


def _require_safe_file_category(category: str) -> None:
    """A file member's destination root is CHOSEN, never composed. An allowlist is the
    right shape here (unlike ``rel``, where any relative path is legitimate): the set of
    live directories a restore may write into is fixed and known, so anything else is a
    manifest describing a placement this build does not perform."""
    from src.backup.folder_backup import _CATEGORIES

    if category not in _CATEGORIES:
        raise VolumeError(f"unknown file-member category in the volume manifest: {category!r}")


def _require_safe_manifest_names(m: dict[str, Any]) -> None:
    """Reject traversal/absolute names ANYWHERE a manifest names a file. A
    signature only proves internal consistency with the EMBEDDED key — anyone
    can self-sign — so verify, parity recovery and reassembly all guard names
    BEFORE touching the filesystem. This MUST cover every manifest field that
    becomes a path: the volume registry, parity volumes, member names AND their
    per-member volume references, plus the top-level ``corpus_member`` /
    ``wal_member`` (the restore corpus-fold path turns those into ``staging /
    <name>`` and unlinks them — an unguarded ``..`` escapes the staging dir into
    the data dir, i.e. an arbitrary-file delete of the live corpus).

    ``file_members`` adds TWO more path-bearing fields and they are the reason the
    2026-07-10 lesson is quoted above: the placement step composes ``targets[category] /
    rel`` into the LIVE data directory, so a field not called "name" becomes a path there.
    ``category`` is checked against a fixed allowlist rather than for traversal — it
    selects a destination root, so the only safe values are the ones we know, and an
    unknown one is refused rather than joined."""
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
    for fm in m.get("file_members") or []:
        _require_safe_member_name(str(fm.get("name") or ""))
        _require_safe_member_name(str(fm.get("rel") or ""))
        _require_safe_file_category(str(fm.get("category") or ""))


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
class SnapshotCopy:
    """A temporary copy of the corpus, made because the live file alone was not a complete
    image (a long reader kept committed frames only in the write-ahead log). It lives in the
    export's staging dir on the destination drive; the corpus member streams from it."""

    path: Path
    bytes: int  # the copy's size on disk
    seconds: float  # how long the copy took (collection stayed paused, writes were not gated)
    gate_held_s: float  # how long the write gate was held by the window that decided to copy


@dataclass
class CorpusSource:
    """What the corpus member streams from. ``freeze()`` yields the residual WAL
    path (or None) with the file guaranteed stable for the duration, OR a
    :class:`SnapshotCopy` when the live file alone was not a complete image and the
    corpus was copied inside the freeze (the member then streams from the copy).
    ``facts_key`` opens the store for the descriptive stats when the ambient process
    key is not its key (test/bench corpora); the live store always opens with the
    ambient key. ``logical_bytes`` is the live store's real size through the log
    (``page_count`` x ``page_size``), which the sizing and the free-space check use
    instead of the main file's size; ``snapshot`` is set when the copy was already made
    before the sizing."""

    path: Path
    member_name: str
    encrypted: bool
    freeze: Callable[[], Any]  # context manager -> Path | SnapshotCopy | None
    facts_key: str | None = None
    logical_bytes: int | None = None
    snapshot: SnapshotCopy | None = None
    #: The corpus volumes are re-emitted in full whatever the destination already holds (a copy
    #: re-encrypts an encrypted store with fresh IVs), so they earn no reuse credit in the check.
    rewrites_corpus: bool = False


def _noop(*_a: Any, **_k: Any) -> None:
    return None


def _no_credit(_member: str) -> int:
    return 0


@dataclass
class _LiveHooks:
    """What the live source needs from the export that built it, so a copy can be sized,
    refused for, labelled, journalled and cancelled from inside the freeze. The defaults
    make ``_live_corpus_source`` callable on its own (tests, benches)."""

    side_bytes: int = 0
    parity_fraction: float = 0.1
    should_stop: Callable[[], bool] | None = None
    set_phase: Callable[[str], None] = _noop
    milestone: Callable[..., None] = _noop
    on_stopped: Callable[[], None] = _noop
    #: bytes of the destination's existing volumes that this run can still reuse, for every member
    #: EXCEPT the named corpus member (its volumes are rewritten after a copy, so they earn no credit)
    reuse_credit: Callable[[str], int] = _no_credit


@contextmanager
def _no_freeze() -> Iterator[None]:
    yield None


_CKPT_SQL = {
    "PASSIVE": "PRAGMA wal_checkpoint(PASSIVE)",
    "TRUNCATE": "PRAGMA wal_checkpoint(TRUNCATE)",
}


def _wal_row(mode: str) -> tuple[int, int, int] | None:
    """The result row ``(busy, log frames, checkpointed frames)`` of ``PRAGMA wal_checkpoint``
    in ``mode`` (``PASSIVE`` never waits for a reader or a writer; ``TRUNCATE`` waits for readers
    up to the connection's busy timeout), run through a pooled connection. ``None`` when the
    call raised or answered something unreadable: UNKNOWN, never "complete"."""
    from src.database.session import engine

    try:
        with engine.connect() as conn:
            row = conn.exec_driver_sql(_CKPT_SQL[mode]).fetchone()
        if row is None or len(row) < 3:
            return None
        return int(row[0]), int(row[1]), int(row[2])
    except Exception:  # noqa: BLE001 - checkpoint is best-effort; the caller treats None as unknown
        _LOG.warning("backup: WAL checkpoint (%s) failed", mode, exc_info=True)
        return None


def _wal_complete(db_path: Path, row: tuple[int, int, int] | None) -> bool | None:
    """Whether the MAIN FILE ALONE is a complete image of the committed state: ``True``, ``False``
    (frames remain only in the log) or ``None`` (cannot tell).

    The decision is the checkpoint's own row, not the size of the ``-wal`` file: a reader that
    started after the last commit leaves ``(0, 104, 104)`` from a PASSIVE probe (``(1, 104, 104)``
    from a TRUNCATE) and a 428 KB ``-wal`` whose frames are ALL in the main file (a main-file-only
    copy had every row), while a reader older than a later commit leaves ``(0, 206, 104)`` (PASSIVE;
    ``busy`` is 1 for a TRUNCATE) and an unusable main file. A negative log count is a store
    that is not in WAL mode ONLY WHEN ``busy`` is 0: ``(1, -1, -1)`` is what SQLite answers when
    ANOTHER connection holds the checkpoint lock (measured: a TRUNCATE busy-waiting on an old
    reader makes a PASSIVE probe and a second TRUNCATE both read it, while a main-file-only copy
    lacked its tables), so it is UNKNOWN, and unknown copies. With no row (the call raised) only an
    EMPTY or missing ``-wal`` is proof of completeness."""
    if row is not None:
        busy, log, checkpointed = row
        if log < 0:
            return None if busy else True
        return checkpointed >= log
    wal = db_path.with_name(db_path.name + "-wal")
    try:
        return True if (not wal.exists() or wal.stat().st_size == 0) else None
    except OSError:
        return None


def _drain_wal(db_path: Path) -> Path | None:
    """Fold the WAL into the main file, and say whether the main file ALONE is now a complete
    image. Returns ``None`` when it is, else the ``-wal`` path (frames remain only in the log:
    a reader older than a later commit holds them, or the checkpoint could not run and the log is
    not empty). The caller never carries that WAL: it copies the corpus through a read
    transaction instead.

    A free PASSIVE step first: when it already shows every frame in the main file, nothing is
    gained by waiting for the log to reset (a backup does not need the file reset), so a reader
    that holds only the END of the log no longer costs the 30 s hold. Otherwise TRUNCATE, which
    waits for readers up to the pooled connection's busy timeout (one wait, not sixty retries),
    re-read after each try until ``_CHECKPOINT_WAIT_S``; a call that raised ends the retrying."""
    wal = db_path.with_name(db_path.name + "-wal")
    if _wal_complete(db_path, _wal_row("PASSIVE")):
        return None
    deadline = time.monotonic() + _CHECKPOINT_WAIT_S
    while True:
        row = _wal_row("TRUNCATE")
        if _wal_complete(db_path, row):
            return None
        if row is None or time.monotonic() >= deadline:
            _LOG.info(
                "backup: the main file is not a complete image (checkpoint row %s)", row
            )
            return wal
        time.sleep(0.5)


def _logical_db_bytes(path: Path) -> int:
    """The store's size through the log: ``PRAGMA page_count`` x ``page_size``, never less than
    the main file. A log that holds growth leaves the main file short (measured: main file 8,192
    bytes, logical size 8,220,672), so sizing or refusing from ``stat()`` under-counts exactly the
    case a copy exists for."""
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    try:
        from src.database.session import engine

        with engine.connect() as conn:
            pages = int(conn.exec_driver_sql("PRAGMA page_count").scalar() or 0)
            page_size = int(conn.exec_driver_sql("PRAGMA page_size").scalar() or 0)
        return max(size, pages * page_size)
    except Exception:  # noqa: BLE001 - fall back to the file size, as before
        return size


@contextmanager
def _collection_paused(notes: list[str]) -> Iterator[None]:
    """Pause background collection while the corpus is copied, and resume it after.

    The copy holds the single-writer gate for its whole duration, which on a
    multi-gigabyte corpus going to an external drive is a long time. Every collector
    worker that reaches its next write meanwhile queues on that gate from inside
    ``before_flush``, on a session that ALREADY holds a pooled connection -- so on the
    small tier (6 + 6) the workers plus the indexer filled the pool, and the task
    manager's own poll (``GET /api/scheduler/activity``) waited out the 30 s pool
    timeout and returned 500 for the rest of the copy (field terminal extract,
    2026-09-29, v0.4.0). Restore already pauses collection for the same reason; the
    export never did.

    Paused BEFORE the gate is taken, so a pass winds down through its normal writes
    rather than piling up behind the copy. :func:`exclusive_window` is re-entrant and
    restores what it found, so an export nested in an outer window (a release run, a
    diagnostics bundle) never resumes collection early. Best-effort, like restore's:
    a pause that fails is noted and the export continues, because the gate -- not
    this pause -- is what keeps the snapshot consistent."""
    with ExitStack() as stack:
        try:
            from src.scheduler.runner import exclusive_window

            was_paused = stack.enter_context(exclusive_window())
        except Exception:  # noqa: BLE001 - the pause is a courtesy, never load-bearing
            _LOG.warning("backup: pausing background collection failed", exc_info=True)
            notes.append(
                "background collection could not be paused for the corpus copy; the "
                "copy is still consistent (the write gate holds), but the app may be "
                "slow to answer until it finishes"
            )
        else:
            if was_paused:
                notes.append(
                    "background collection was paused while the corpus was copied, "
                    "and resumed afterwards"
                )
        yield


_SNAPSHOT_NOTE = "a temporary copy of your data was made so this backup is complete"
_GATE_OFF_NOTE = (
    "WARNING: OO_WRITE_GATE=0 — the write gate was disabled, so the "
    "corpus was NOT streamed under a write pause. If collection was "
    "active this snapshot may be inconsistent; re-enable the gate (or "
    "stop collection) for a guaranteed-consistent backup."
)


def _snapshot_file(live: Path, dest: Path, should_stop: Callable[[], bool] | None) -> None:
    """One read-transaction copy of the live corpus (the backup API for a plaintext store,
    ``sqlcipher_export`` for an encrypted one, KEYED with the live key: no plaintext lands on
    disk). ``should_stop`` is passed only when there is one, so a spy of the two-argument call
    keeps working."""
    from src.database import connect as _connect

    if should_stop is None:
        _connect.snapshot_preserving(live, dest)
    else:
        _connect.snapshot_preserving(live, dest, should_stop=should_stop)


def _take_snapshot(
    live: Path,
    tmp_dir: Path,
    member: str,
    hooks: _LiveHooks,
    *,
    gate_held_s: float,
    side_written: bool = False,
) -> SnapshotCopy:
    """Copy the live corpus into ``tmp_dir`` (on the DESTINATION drive), after refusing for lack
    of room BEFORE a byte is written. Runs under the collection pause the caller already holds
    and with NO write gate: the copy is one read transaction, so it is a consistent image
    whatever commits meanwhile, and holding the gate for it would stall every writer for minutes
    (the incident tests/test_export_pauses_collection.py records). A stop interrupts an encrypted
    copy within about a second; a plaintext copy (the backup API) cannot be interrupted and the
    stop takes effect when it ends. ``side_written`` is True for a LATE copy, taken after the side
    members and blobs were written (or reused) at the destination: their bytes are already on disk,
    so the check must not ask for them a second time."""
    copy_bytes = _logical_db_bytes(live)
    _preflight_snapshot(
        tmp_dir.parent,
        copy_bytes,
        hooks.side_bytes,
        hooks.parity_fraction,
        side_written=side_written,
        credit=hooks.reuse_credit(member),
    )
    remember_snapshot_destination(tmp_dir.parent)
    hooks.set_phase("snapshot")
    hooks.milestone("stage_begin", "export:snapshot", copy_bytes=copy_bytes)
    snap = tmp_dir / member
    t0 = time.monotonic()
    from src.database.connect import SnapshotStopped

    try:
        _snapshot_file(live, snap, hooks.should_stop)
    except SnapshotStopped:
        hooks.on_stopped()
        raise VolumeStopped("volume backup stopped") from None
    seconds = time.monotonic() - t0
    size = snap.stat().st_size
    hooks.milestone("stage_end", "export:snapshot", seconds=round(seconds, 3), bytes=size)
    return SnapshotCopy(path=snap, bytes=size, seconds=seconds, gate_held_s=gate_held_s)


def _clean_source(
    live: Path,
    tmp_dir: Path,
    member: str,
    enc: bool,
    notes: list[str],
    hooks: _LiveHooks,
    logical_bytes: int,
) -> CorpusSource:
    """The live file, streamed under the pause and the gate once the drain says the main file
    alone is a complete image: today's sequence. If the drain finds frames only in the log (a
    reader appeared after the probe: the gap holds the side members and the blobs and can last
    hours) the corpus is copied HERE, late, under the same pause window, instead of failing the
    export or carrying the log."""

    @contextmanager
    def freeze() -> Iterator[Path | SnapshotCopy | None]:
        from src.database.writer import gate_enabled, write_lock

        with _collection_paused(notes), ExitStack() as gate:
            gate_t0 = time.monotonic()
            gate.enter_context(write_lock())
            if _drain_wal(live) is None:
                if not gate_enabled():
                    # The write gate IS the snapshot-consistency guarantee: collection
                    # writes pause while the corpus streams. Under OO_WRITE_GATE=0 the
                    # lock is a no-op, so a concurrent commit could tear the streamed
                    # image while the summary still reports a "writes paused" phase.
                    # Degrade LOUDLY — never present a possibly-inconsistent backup as
                    # a paused-and-consistent one.
                    notes.append(_GATE_OFF_NOTE)
                yield None
                return
            gate_s = time.monotonic() - gate_t0
            gate.close()  # collection stays paused; the copy is a read transaction
            copy = _take_snapshot(
                live, tmp_dir, member, hooks, gate_held_s=gate_s, side_written=True
            )
            notes.append(_SNAPSHOT_NOTE)
            yield copy

    return CorpusSource(
        path=live, member_name=member, encrypted=enc, freeze=freeze, logical_bytes=logical_bytes
    )


def _live_corpus_source(
    tmp_dir: Path,
    include_newsletters: bool,
    notes: list[str],
    hooks: _LiveHooks | None = None,
) -> CorpusSource:
    from src.backup.sqlite_backup import live_db_path
    from src.database.connect import is_encrypted_file

    hooks = hooks or _LiveHooks()
    live = live_db_path()
    enc = bool(is_encrypted_file(live))
    member = "corpus.db.sqlcipher" if enc else "corpus.db"
    if include_newsletters:
        logical = _logical_db_bytes(live)
        clean = _clean_source(live, tmp_dir, member, enc, notes, hooks, logical)
        # THE PROBE: one PASSIVE row, no pause and no gate (PASSIVE waits for nobody). A main
        # file that is already a complete image takes today's sequence, unchanged.
        if _wal_complete(live, _wal_row("PASSIVE")):
            return clean
        # A reader older than a commit (or an unreadable row): the EARLY WINDOW decides BEFORE the
        # sizing, so the volume sizing, the free-space check and the facts all see the copy. One
        # pause window covers the drain and the copy; the notes it writes are kept only if a
        # copy was made (a reader that left costs nothing and leaves no false sentence behind).
        from src.database.writer import write_lock

        early_notes: list[str] = []
        copy: SnapshotCopy | None = None
        with _collection_paused(early_notes):
            gate_t0 = time.monotonic()
            with write_lock():
                residual = _drain_wal(live)
            gate_s = time.monotonic() - gate_t0
            if residual is not None:
                copy = _take_snapshot(live, tmp_dir, member, hooks, gate_held_s=gate_s)
        if copy is None:
            return clean
        notes.extend(early_notes)
        notes.append(_SNAPSHOT_NOTE)
        return CorpusSource(
            path=copy.path,
            member_name=member,
            encrypted=enc,
            freeze=_no_freeze,
            snapshot=copy,
            rewrites_corpus=True,
        )

    # Newsletter exclusion needs a modifiable copy: a DISPOSABLE snapshot that
    # PRESERVES the at-rest encryption state (never a plaintext staging), filtered
    # in place, streamed instead of the live file. An encrypted copy is re-encrypted with fresh
    # IVs, so its corpus volumes are never reused; a plaintext one still is (the filtered copy of
    # an unchanged corpus hashes the same), so only the encrypted case withholds the credit.
    from src.database.connect import snapshot_preserving

    # Refused for lack of room BEFORE a byte is copied, like the other copy paths.
    _preflight_snapshot(
        tmp_dir.parent,
        _logical_db_bytes(live),
        hooks.side_bytes,
        hooks.parity_fraction,
        credit=hooks.reuse_credit(member),
    )
    snap = tmp_dir / member
    # The copy is one read transaction (``snapshot_preserving`` without ``allow_file_copy``
    # takes NO write gate), so it gets the collection pause only. The filtering below works
    # on the private copy.
    remember_snapshot_destination(tmp_dir.parent)  # a crash's leftover is swept at the next boot
    with _collection_paused(notes):
        snapshot_preserving(live, snap)
    _drop_newsletters_in_file(snap)
    notes.append(
        "newsletters excluded: the corpus was copied and filtered"
        + (" (an encrypted corpus is re-encrypted by the copy, so its volumes are rewritten)" if enc else "")
    )
    return CorpusSource(
        path=snap, member_name=member, encrypted=enc, freeze=_no_freeze, rewrites_corpus=enc
    )


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


#: Member-name prefix for the optional large public blobs. A namespace of its own so a
#: blob can never collide with a side member's name, and so the restore's placement step
#: can be keyed on the manifest rather than on a name convention.
_BLOB_PREFIX = "blobs"


def collect_blob_members(categories: Iterable[str]) -> list[tuple[MemberFile, dict[str, Any]]]:
    """The wiki dumps / OSM extracts / model weights, as artifact members.

    S6.2, the top parked item of the 2026-07-12 closeout: one portable artifact should be
    able to carry these, so that a restore of a machine needs one thing rather than an
    encrypted artifact PLUS a folder copy whose association with it is the operator's
    memory.

    Enumeration is ``folder_backup.collect_items`` unchanged, which is what makes the
    skip-non-``done`` rule true here by construction rather than by a second
    implementation: it reads each download manager's OWN done state, so a partial file is
    never a member, and the model stores are deduped by content-addressed name.

    OPT-IN, and the reason is a ruling rather than caution. The 2026-06-21 large-data
    design copies these AS-IS, never encrypted, because that is what makes a 100 GB backup
    feasible and what keeps the in-app path at plain-folder-copy parity. Putting them in
    the volume artifact encrypts and parity-codes public, re-downloadable bytes -- which
    buys one artifact and costs the whole point of that ruling. Both are legitimate and
    they are not the same trade, so the caller chooses and the default is the behaviour
    that shipped: no categories, byte-identical output.

    Returns each member WITH its placement entry rather than leaving the caller to derive
    one from the member name: the name is built here from the pair, so splitting it back
    apart later would be re-deriving a fact this function already holds, and the two could
    drift the day the naming changes.

    THE SOURCES ARE LIVE FILES, not staged copies -- unlike every other member. In
    practice they are immutable (a completed download is never rewritten; model blobs are
    content-addressed), so the stability :func:`_emit_member` requires holds. A file
    DELETED mid-backup (an operator removing a model) fails the run loudly rather than
    writing an artifact whose index names bytes it does not carry, which is the direction
    to fail in: the run is repeatable, a quietly incomplete artifact is not.
    """
    from src.backup.folder_backup import _CATEGORIES, collect_items

    cats = [c for c in categories if c in _CATEGORIES]
    if not cats:
        return []
    items = collect_items(
        include_wiki="wiki_dumps" in cats,
        include_osm="osm_regions" in cats,
        include_models="models" in cats,
        include_hf="hf_models" in cats,
    )
    out: list[tuple[MemberFile, dict[str, Any]]] = []
    for it in items:
        name = f"{_BLOB_PREFIX}/{it.category}/{it.rel}"
        out.append(
            (
                MemberFile(name, "blob", it.src),
                {"name": name, "category": it.category, "rel": it.rel},
            )
        )
    return out


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
                if st.volumes:  # never replace the previous run's resume log with an empty one
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
    include_blobs: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Build (or incrementally refresh / resume) an oo-volumes-2 set at ``dest_dir``.

    See the module docstring for the guarantees. ``corpus_source``/``side_members``
    are seams for tests and benches; production uses the live store + data dir.
    Returns a measured summary (volumes reused/emitted, gate-held seconds, wall).

    ``include_blobs`` (S6.2, default none) names the large public categories to carry
    INSIDE the artifact -- see :func:`collect_blob_members` for why it is opt-in and what
    it costs. Passing none leaves the output byte-identical to before it existed."""
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
    _write_owner_marker(tmp_dir)  # a crash's leftover is told from a live job's dir by its owner
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
            # Export stage boundaries into the run journal. The export's only
            # measurements today are wall_s and gate_held_s for the WHOLE run, both
            # returned in memory on the success path -- so "the export seems fine"
            # has never been checked against anything. durable=False inside the
            # freeze window: those milestones fire while the process-wide write gate
            # is held (see runlog._write).
            def _ms(ev: str, name: str, **kw) -> None:
                from src.backup import runlog

                runlog.milestone(ev, name=name, durable=kw.pop("durable", True), **kw)

            _ms("stage_begin", "export:collecting")
            st.phase = "collecting"
            st.progress()
            # Materialise the signing key BEFORE the side members are collected, as the
            # zip writer does (artifact._build_backup_zip): a first-ever export on an
            # install that has no key yet must carry the very key that signs it. The
            # envelope creates it anyway, but only AFTER collection -- so the first
            # export had one volume fewer than every later one, and a restore of it
            # onto a new machine did not carry the identity that signed it (J4).
            from src.reporting.evidence import load_or_create_signing_key

            load_or_create_signing_key()
            side = side_members if side_members is not None else _collect_side_members(tmp_dir)
            # Blobs ride the SAME emit path as any other member -- sliced, encrypted,
            # parity-covered, checksum-verified on reassembly -- so nothing about the
            # artifact's guarantees is special-cased for them. They are collected apart
            # only so the manifest can carry the placement index the restore needs.
            blob_pairs = collect_blob_members(include_blobs or ())
            blobs = [mf for mf, _ in blob_pairs]
            side_sizes = [m.path.stat().st_size for m in side]
            blob_sizes = [m.path.stat().st_size for m in blobs]
            # Blob bytes enter BOTH the adaptive volume sizing and the disk preflight.
            # They are the largest members by orders of magnitude, so omitting them from
            # the sizing would blow the GF(2^8) N+M ceiling that sizing exists to respect,
            # and omitting them from the preflight would promise a backup the drive cannot
            # hold -- a refusal after 20 GB of writing is not a refusal.
            side_sizes = [*side_sizes, *blob_sizes]
            side_bytes = sum(side_sizes)

            def _set_phase(label: str) -> None:
                st.phase = label
                st.progress()

            def _on_stopped() -> None:
                # A run that emitted nothing yet must not overwrite the previous run's resume log
                # with an empty one: a stop during the copy would cost the next run every volume
                # the stopped run before it had written.
                if st.volumes:
                    st.save_building()

            run_side_members = {m.name for m in side} | {m.name for m in blobs}

            def _reuse_credit(corpus_member: str) -> int:
                """Bytes of existing volumes this run COULD reuse as they are: every pool entry of a
                side member or blob this run carries (not the corpus, not a member it no longer
                has, not the old envelope, which is always re-emitted) whose file is still on the
                drive. A member that changed is counted and then re-emitted, so this is a bound."""
                total = 0
                for (member, _slice), v in pool.items():
                    if member == corpus_member or member not in run_side_members:
                        continue
                    try:
                        total += (dest / str(v.get("name", ""))).stat().st_size
                    except OSError:
                        continue
                return total

            src = (
                corpus_source
                if corpus_source is not None
                else _live_corpus_source(
                    tmp_dir,
                    include_newsletters,
                    notes,
                    _LiveHooks(
                        side_bytes=side_bytes,
                        parity_fraction=parity_fraction,
                        should_stop=should_stop,
                        set_phase=_set_phase,
                        milestone=_ms,
                        on_stopped=_on_stopped,
                        reuse_credit=_reuse_credit,
                    ),
                )
            )
            # The live store's size THROUGH the log, not the main file's: a log that holds
            # growth leaves the file short (see _logical_db_bytes). A source without one (an
            # injected test/bench source) is its file.
            corpus_bytes = (
                src.logical_bytes
                if src.logical_bytes is not None
                else src.path.stat().st_size
            )
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
                dest,
                corpus_bytes,
                side_bytes,
                parity_fraction,
                # After a copy the corpus volumes earn no credit (an encrypted copy re-encrypts
                # with fresh IVs, and the previous set stays on disk until the final swap), but
                # the volumes of every other member are reused as they are and still do.
                reuse_possible=bool(pool),
                credit_except_corpus=(
                    _reuse_credit(src.member_name)
                    if (src.snapshot is not None or src.rewrites_corpus)
                    else None
                ),
            )

            _ms("stage_end", "export:collecting")
            members_out: list[dict[str, Any]] = []
            _ms("stage_begin", "export:side_members", n=len(side))
            st.phase = "members"
            for mf in side:
                e = _emit_member(st, mf)
                members_out.append(e)

            _ms("stage_end", "export:side_members")

            # THE PLACEMENT INDEX. `members` carries the bytes (and is what reassembly
            # reads); `file_members` says where each one goes back on a restore. Kept as
            # a separate block rather than extra keys on `members` so the restore's
            # placement step iterates exactly the members it is allowed to place -- a
            # loop over `members` filtered by role would place whatever a hostile manifest
            # chose to label "blob", including the corpus.
            file_members: list[dict[str, Any]] = []
            if blob_pairs:
                _ms("stage_begin", "export:blob_members", n=len(blob_pairs))
                st.phase = "large files"
                for mf, where in blob_pairs:
                    e = _emit_member(st, mf)
                    members_out.append(e)
                    file_members.append(
                        {
                            **where,
                            "bytes": e["plaintext_bytes"],
                            "sha256": e["plaintext_sha256"],
                        }
                    )
                _ms("stage_end", "export:blob_members")
                notes.append(
                    f"{len(blob_pairs)} large public files ("
                    + ", ".join(sorted({fm["category"] for fm in file_members}))
                    + ") ride inside this artifact; they are encrypted and parity-covered "
                    "like every other member, which is what makes it one portable thing "
                    "and what it costs over copying them as-is"
                )
            st.phase = "corpus (writes paused)"
            st.progress()
            # THE GATE WINDOW, split three ways. It is one `with src.freeze()`
            # spanning the corpus member, the residual WAL member and _corpus_facts
            # -- and _corpus_facts runs full table counts plus a hash chain, all
            # while the process-wide write lock is held. Reported as one number,
            # there is no way to tell which of the three the operator waited on.
            _ms("stage_begin", "export:gate_window")
            gate_t0 = time.monotonic()
            wal_member: str | None = None
            with src.freeze() as frozen:
                # A late copy (a reader appeared after the probe) replaces the live file as the
                # stream; an old-format source still yields a residual WAL path (or None).
                late_copy = frozen if isinstance(frozen, SnapshotCopy) else None
                wal_path = None if late_copy is not None else frozen
                corpus_path = late_copy.path if late_copy is not None else src.path
                if late_copy is not None:
                    st.phase = "corpus (from a temporary copy)"
                    st.progress()
                _ms("stage_begin", "export:corpus_member", durable=False)
                ce = _emit_member(st, MemberFile(src.member_name, "corpus", corpus_path))
                ce["sqlcipher"] = src.encrypted
                members_out.append(ce)
                _ms("stage_end", "export:corpus_member", durable=False)
                if wal_path is not None:
                    _ms("stage_begin", "export:wal_member", durable=False)
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
                    _ms("stage_end", "export:wal_member", durable=False)
                _ms("stage_begin", "export:corpus_facts", durable=False)
                stats, arev = _corpus_facts(corpus_path, key=src.facts_key)
                _ms("stage_end", "export:corpus_facts", durable=False)
            gate_held_s = time.monotonic() - gate_t0
            # A copy was made (before the sizing, or late inside the freeze): the gate was held
            # only by the window that decided to copy, not for the copy or the stream, so say
            # that figure, and report the copy's own seconds and bytes beside it.
            snap = late_copy or src.snapshot
            if snap is not None:
                gate_held_s = snap.gate_held_s
            _ms("stage_end", "export:gate_window", seconds=round(gate_held_s, 3))

            _ms("stage_begin", "export:finalizing")
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
                "file_members": file_members,
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
                _ms("stage_begin", "export:parity")
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
                _ms("stage_end", "export:parity")

            # Sign LAST so the signature covers the parity block too, then swap
            # the canonical manifest atomically as the single commit point.
            vman.pop("signature", None)
            vman["signature"] = _sign_manifest(vman)
            _write_json_atomic(dest / MANIFEST_NAME, vman)
            final = vman
            _ms("stage_end", "export:finalizing")
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
                "snapshot_s": round(snap.seconds, 3) if snap is not None else None,
                "snapshot_bytes": snap.bytes if snap is not None else None,
                "wall_s": round(time.monotonic() - t0, 3),
                "notes": notes,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _volumes_need(corpus_bytes: int, side_bytes: int, parity_fraction: float) -> int:
    """What the finished volume set needs on the destination. ``(1 + parity)``: the data volumes
    plus the Reed-Solomon parity volumes. ``1.02``: generic slack (the envelope's own overhead is
    about 16 bytes per 4 MiB chunk, ~0.0004 %, so this is not that). ``64 MiB``: the fixed small
    members (manifest, key check, metadata). A BOUND, not a prediction."""
    needed = int((corpus_bytes + side_bytes) * (1.0 + max(0.0, parity_fraction)) * 1.02)
    return needed + 64 * 1024 * 1024


def _preflight_snapshot(
    dest: Path,
    copy_bytes: int,
    side_bytes: int,
    parity_fraction: float,
    *,
    side_written: bool = False,
    credit: int = 0,
) -> None:
    """Refuse loudly BEFORE the temporary copy of the corpus is made, so a drive that cannot hold
    it is told so now and not after twelve minutes of copying. The copy and the volume set exist
    at the same time (the copy goes in the ``finally`` at the end of the run, not before the
    parity step, so this is a safe upper bound). The corpus volumes earn no reuse credit (the copy
    re-encrypts an encrypted store with fresh IVs, and the previous set stays on disk until the
    final swap), but the volumes of every OTHER member, which an incremental run reuses as they
    are, do: ``credit`` is their size, so a destination already holding hundreds of GB of reusable
    blobs is not asked for them again (never more than the side members' own size). A LATE copy
    (``side_written``) is taken after the side members and blobs are on the drive, so their bytes
    are not asked for again either, and ``credit`` does not apply to it: it counts those same
    bytes. The message
    is ``preflight_free_space``'s own shape: how much is needed, how much is free and where, and
    what to do (free space or choose another location)."""
    from src.backup.artifact import preflight_free_space

    need = _volumes_need(copy_bytes, side_bytes, parity_fraction)
    side_part = int(side_bytes * 1.02)
    # The side members and blobs are either already on the drive (a LATE copy: their bytes are
    # written, and the old volumes that ``credit`` counts are those same bytes) or, early, are
    # reused as they are up to their own size. One of the two, never both: taking both off asked
    # for the copy alone, then the corpus volumes and the parity hit a full drive.
    need -= side_part if side_written else min(max(0, credit), side_part)
    needed = copy_bytes + need
    preflight_free_space(
        dest, needed, what="volume backup (it first makes a temporary copy of your data)"
    )


def _preflight_dest(
    dest: Path,
    corpus_bytes: int,
    side_bytes: int,
    parity_fraction: float,
    *,
    reuse_possible: bool,
    credit_except_corpus: int | None = None,
) -> None:
    """Refuse loudly up front when the destination clearly lacks room. Existing
    volumes count toward the budget ONLY when they can actually be reused — a
    passphrase change (or an unreadable manifest) re-emits everything while the
    previous set stays on disk until the finalize garbage-collects it, so the
    budget must then cover both generations at once. After a temporary copy of the corpus
    (``credit_except_corpus`` given) only the volumes of the OTHER members are credited."""
    from src.backup.artifact import preflight_free_space

    needed = _volumes_need(corpus_bytes, side_bytes, parity_fraction)
    if reuse_possible:
        existing = 0
        if credit_except_corpus is not None:
            existing = credit_except_corpus
        else:
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
) -> StagedArtifact:
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
            # The placement index travels with the staged artifact so the caller that
            # commits the restore can put the large files back without re-reading (or
            # re-trusting) the volume manifest. The bytes themselves are already in
            # staging AND already checksum-verified by the reassembly loop above.
            staged.file_members = list(m.get("file_members") or [])
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
