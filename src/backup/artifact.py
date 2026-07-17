"""
The oo-backup-2 artifact: one container that carries EVERYTHING.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Design: docs/design/DB_RELIABILITY_02_DESIGN.md §2. A backup is a single ZIP:

    manifest.json     signed inventory (per-member sha256, corpus stats, schema
                      revision, Merkle root over article hashes, exclusions + why)
    corpus.db         online-backup snapshot of the main database
    custody_log.db    online-backup snapshot of the custody chain (when present)
    <state files>     settings JSONs, annotations, imported-event stores
    logs/...          operational .jsonl logs (D5)
    keys/...          signing keys -- ENCRYPTED ARTIFACTS ONLY (D2): a plaintext
                      backup must never hand out the operator's signing identity

The encrypted variant is the same ZIP passed through the existing OOENC1
AES-256-GCM envelope (src/safety/crypto.py) -- one self-describing format, no
fork. Deliberate exclusions are *listed in the manifest* (wiki dumps, D3),
never silently dropped: an artifact says what it is and what it is not.

Honest limit: the OOENC1 envelope is one-shot AES-GCM, so the encrypted flow
holds the artifact in memory once (the same profile as the pre-existing
encrypted backup). Stated here, not hidden.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import re
import secrets
import sqlite3
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.paths import data_dir

_LOG = logging.getLogger("backup.artifact")

BACKUP_SCHEMA = "oo-backup-2"

# Data-dir-relative state files carried by every artifact (gap analysis §2 --
# the side files that previously lived OUTSIDE every backup ever taken).
_STATE_FILES = (
    "app_settings.json",
    "scheduler_settings.json",
    "custody_settings.json",
    "safety_settings.json",
    "calendar_feed_checks.json",
    "calendar_feed_imports.json",
)
_LOG_FILES = (
    "feed_preflight.jsonl",
    "field_test.jsonl",
    "app_errors.jsonl",
    "import_results.jsonl",
    "scheduler_runs.jsonl",
)
_ANNOTATIONS_DIR = "annotations"
_KEYS_DIR = "keys"
_CUSTODY_DB = "custody_log.db"
_WIKI_DUMPS_DIR = "wiki_dumps"
_OSM_DIR = "osm_regions"  # offline-map downloads (src/geo/osm_downloads.py)

# Source domains under which imported newsletters live (src/api/ingestion.py). A
# backup can EXCLUDE them (maintainer 2026-06-21: re-import fixed .eml to replace
# faulty ones), so the corpus snapshot is filtered to drop their articles.
_NEWSLETTER_DOMAINS = ("newsletters.import.local", "mailbox.import.local")
_SAFE_TABLE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # guard table names from the schema

_SQLITE_MAGIC = b"SQLite format 3\x00"
_ZIP_MAGIC = b"PK\x03\x04"


class ArtifactError(RuntimeError):
    """Raised when an artifact cannot be built or read safely."""


class BackupSpaceError(ArtifactError):
    """Raised by the disk-space preflight when a backup/restore lacks room to complete —
    so it refuses LOUDLY up front instead of failing mid-write on a full disk (H3)."""


# Safety factor for the single-file CREATE preflight: the corpus DB is snapshotted into a
# temp dir (1x), zipped STORED (~1x), then the encrypted output written (~1x), so peak disk
# is a few times the corpus size. 3x is a conservative floor (state/log/annotation members
# are tiny beside the corpus DB).
_BUILD_SPACE_FACTOR = 3


def preflight_free_space(target: Path, needed: int, *, what: str) -> None:
    """Refuse LOUDLY (BackupSpaceError, needs-X-vs-Y-free) if ``target``'s filesystem lacks
    ``needed`` bytes, BEFORE any write starts — never a mid-write ENOSPC crash (H3).

    Reuses the folder-backup free-space probe (fails safe to 0 on an unreadable path, so an
    unmountable target fails the preflight rather than being silently written to)."""
    from src.backup.folder_backup import free_bytes, human_bytes

    free = free_bytes(target)
    if needed > free:
        raise BackupSpaceError(
            f"Not enough free space for the {what}: needs about {human_bytes(needed)}, "
            f"only {human_bytes(free)} free at {target}. Free up space or choose another "
            "location, or use the large-data/volume backup for a big corpus."
        )


@dataclass
class Member:
    name: str  # zip member name == data-dir-relative path (corpus.db is virtual)
    role: str  # corpus | custody | state | annotations | logs | keys
    path: Path  # source file on disk
    sha256: str = ""
    bytes: int = 0


@dataclass
class StagedArtifact:
    """A verified, unpacked artifact staged on disk -- nothing touched yet."""

    kind: str  # oo-backup-2 | legacy-db | legacy-ooenc
    staging_dir: Path
    corpus_path: Path
    custody_path: Path | None
    manifest: dict | None
    signature_state: str  # verified | bad-signature | unsigned
    origin_fingerprint: str  # signer pubkey hex or "unsigned"
    members: list[dict] = field(default_factory=list)
    hash_failures: list[str] = field(default_factory=list)
    # True when the uploaded artifact was OOENC1-wrapped (AES-256-GCM at rest) and
    # had to be decrypted to read it. Surfaced in the restore preview so the operator
    # can SEE a backup is genuinely encrypted (field test 2026-06-19 P0-2 doubt).
    encrypted: bool = False

    def member_paths(self, role: str) -> list[tuple[str, Path]]:
        out = []
        for m in self.members:
            if m.get("role") == role:
                p = self.staging_dir / m["name"]
                if p.exists():
                    out.append((m["name"], p))
        return out


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def snapshot_sqlite(src: Path, dest: Path) -> Path:
    """Consistent PLAINTEXT snapshot of ANY store (WAL-safe; encrypted sources
    are exported -- artifact members are portable plaintext by design, the
    artifact's own OOENC1 envelope being their at-rest protection)."""
    from src.database.connect import snapshot_to_plaintext

    return snapshot_to_plaintext(src, dest)


def _corpus_stats(corpus_snapshot: Path) -> dict:
    """Per-table counts + the Merkle root over (id, hash) of every article --
    the artifact-level authentication hash for the article set (design §2)."""
    from src.crypto.merkle_tree import compute_merkle_root
    from src.reporting.evidence import canonical_bytes

    conn = sqlite3.connect(f"file:{corpus_snapshot}?mode=ro", uri=True)
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' AND name NOT LIKE 'article_fts%'"
            )
        ]
        counts = {}
        for t in tables:
            counts[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]  # noqa: S608  # nosec B608 - identifier from the fixed member map, never input
        leaves = [
            hashlib.sha256(canonical_bytes({"id": rid, "hash": h})).hexdigest()
            for rid, h in conn.execute("SELECT id, hash FROM articles ORDER BY id")
        ]
        root = compute_merkle_root(leaves) if leaves else None
    finally:
        conn.close()
    return {"tables": counts, "articles_merkle_root": root}


def _excluded_inventory() -> list[dict]:
    """What this artifact deliberately does NOT contain, and why (manifest-listed,
    never silent -- D3).

    Large, re-downloadable artifact directories are excluded BY CONSTRUCTION (never
    collected as members), which ALSO means an in-progress download (a partial file in
    one of these dirs) can never end up in a backup half-written (maintainer 2026-06-21:
    ongoing downloads must not be backed up to avoid corruption). They are listed here
    so the omission is transparent + re-fetchable after restore.
    """
    out: list[dict] = []
    for name, why in (
        (_WIKI_DUMPS_DIR, "re-downloadable offline Wikipedia dumps (design D3); "
                          "re-download via Settings after restore"),
        (_OSM_DIR, "re-downloadable offline-map (OSM) region extracts; in-progress "
                   "downloads are never backed up — re-download via Settings after restore"),
    ):
        d = data_dir() / name
        if d.is_dir():
            files = [p for p in d.rglob("*") if p.is_file()]
            if files:
                out.append(
                    {
                        "name": name,
                        "reason": why,
                        "files": len(files),
                        "bytes": sum(p.stat().st_size for p in files),
                    }
                )
    return out


def _delete_in(cur: sqlite3.Cursor, table: str, col: str, ids: list[int]) -> None:
    """DELETE FROM <table> WHERE <col> IN (ids), chunked under SQLite's variable cap.
    ``table``/``col`` come from the schema (PRAGMA), validated as plain identifiers."""
    if not (_SAFE_TABLE.match(table) and _SAFE_TABLE.match(col)):
        return
    for i in range(0, len(ids), 900):
        chunk = ids[i : i + 900]
        q = ",".join("?" * len(chunk))
        cur.execute(f"DELETE FROM {table} WHERE {col} IN ({q})", chunk)  # noqa: S608  # nosec B608 - table/col validated against _SAFE_TABLE; values are bound params


def _drop_newsletter_articles(db_path: Path) -> int:
    """Remove imported-newsletter articles from a PLAINTEXT corpus snapshot copy.

    Operates ONLY on the disposable backup snapshot (never the live DB). Deletes the
    newsletter-source articles AND every dependent row (any table with an ``article_id``
    column — all FKs to articles.id use that name), so the restore's foreign_key_check
    finds no orphans. The empty source rows are LEFT (harmless; a future re-import of
    fixed .eml re-attaches to them). Returns the number of articles dropped.
    """
    con = sqlite3.connect(str(db_path))
    try:
        return _drop_newsletter_rows(con)
    finally:
        con.close()


def _drop_newsletter_rows(con) -> int:
    """The connection-level core of :func:`_drop_newsletter_articles`, so the
    streaming backup can filter an ENCRYPTED disposable snapshot through a keyed
    SQLCipher connection (plaintext never staged at backup time). The caller owns
    (and closes) the connection."""
    cur = con.cursor()
    marks = ",".join("?" * len(_NEWSLETTER_DOMAINS))
    src_ids = [r[0] for r in cur.execute(
        f"SELECT id FROM sources WHERE domain IN ({marks})", _NEWSLETTER_DOMAINS)]  # noqa: S608  # nosec B608 - marks is only ?-placeholders; domains are bound params
    if not src_ids:
        return 0
    sq = ",".join("?" * len(src_ids))
    art_ids = [r[0] for r in cur.execute(
        f"SELECT id FROM articles WHERE source_id IN ({sq})", src_ids)]  # noqa: S608  # nosec B608 - sq is only ?-placeholders; ids are bound params
    if not art_ids:
        return 0
    tables = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for t in tables:
        if t == "articles" or not _SAFE_TABLE.match(t):
            continue
        cols = [c[1] for c in cur.execute(f"PRAGMA table_info({t})")]  # noqa: S608  # nosec B608 - t validated against _SAFE_TABLE (from the schema, not input)
        if "article_id" in cols:
            _delete_in(cur, t, "article_id", art_ids)
    _delete_in(cur, "articles", "id", art_ids)
    con.commit()
    cur.execute("VACUUM")
    con.commit()
    return len(art_ids)


def _collect_members(
    include_keys: bool, tmp_dir: Path, include_newsletters: bool = True
) -> list[Member]:
    """Snapshot the databases into tmp_dir and inventory every side file."""
    from src.backup.sqlite_backup import live_db_path

    members: list[Member] = []

    corpus_snap = tmp_dir / "corpus.db"
    snapshot_sqlite(live_db_path(), corpus_snap)
    if not include_newsletters:
        _drop_newsletter_articles(corpus_snap)  # filter the disposable copy only
    members.append(Member("corpus.db", "corpus", corpus_snap))

    custody_src = data_dir() / _CUSTODY_DB
    if custody_src.exists():
        custody_snap = tmp_dir / _CUSTODY_DB
        snapshot_sqlite(custody_src, custody_snap)
        members.append(Member(_CUSTODY_DB, "custody", custody_snap))

    base = data_dir()
    for name in _STATE_FILES:
        p = base / name
        if p.exists():
            members.append(Member(name, "state", p))
    for name in _LOG_FILES:
        p = base / name
        if p.exists():
            members.append(Member(f"logs/{name}", "logs", p))
    ann = base / _ANNOTATIONS_DIR
    if ann.is_dir():
        for p in sorted(ann.rglob("*.json")):
            members.append(Member(str(p.relative_to(base)), "annotations", p))
    if include_keys:
        keys = base / _KEYS_DIR
        if keys.is_dir():
            for p in sorted(keys.iterdir()):
                if p.is_file():
                    members.append(Member(str(p.relative_to(base)), "keys", p))
    return members


# --------------------------------------------------------------------------- #
#  Write
# --------------------------------------------------------------------------- #
def _build_backup_zip(
    tmp_dir: Path, *, include_keys: bool, include_newsletters: bool
) -> tuple[Path, dict]:
    """Collect members, build + Ed25519-sign the manifest, and write the oo-backup-2 ZIP
    into ``tmp_dir``. Returns (zip_path, signed envelope). Shared by the single-file
    backup (write_backup_v2) and the volume-set backup (write_volume_backup)."""
    from src.reporting.evidence import (
        canonical_bytes,
        load_or_create_signing_key,
        public_key_hex,
    )
    from src.utils.export_envelope import app_version

    # Materialise the signing key BEFORE collecting members: a first-ever encrypted
    # backup must carry the very key that signs its manifest.
    key = load_or_create_signing_key()
    members = _collect_members(include_keys, tmp_dir, include_newsletters)
    for m in members:
        m.sha256 = _sha256_file(m.path)
        m.bytes = m.path.stat().st_size

    from src.database.migrate import file_revision

    corpus_snap = next(m for m in members if m.role == "corpus").path
    manifest = {
        "backup_schema": BACKUP_SCHEMA,
        "app_version": app_version(),
        "alembic_rev": file_revision(corpus_snap),
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "encrypted": include_keys,
        "keys_included": include_keys,
        "members": [
            {"name": m.name, "role": m.role, "sha256": m.sha256, "bytes": m.bytes}
            for m in members
        ],
        "excluded": _excluded_inventory(),
        "corpus": _corpus_stats(corpus_snap),
    }
    envelope = {
        "manifest": manifest,
        "signature": key.sign(canonical_bytes(manifest)).hex(),
        "public_key": public_key_hex(key),
        "algorithm": "ed25519",
    }

    zip_path = tmp_dir / "artifact.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps(envelope, ensure_ascii=False, indent=1),
            compress_type=zipfile.ZIP_DEFLATED,
        )
        for m in members:
            # Databases are stored uncompressed (they hash cheaply and barely
            # compress); text members deflate.
            ctype = (
                zipfile.ZIP_STORED
                if m.role in ("corpus", "custody")
                else zipfile.ZIP_DEFLATED
            )
            zf.write(m.path, m.name, compress_type=ctype)
    return zip_path, envelope


def write_backup_v2(
    dest: Path, passphrase: str | None = None, *, include_newsletters: bool = True
) -> dict:
    """Build a complete oo-backup-2 artifact at ``dest`` (the SINGLE-FILE path).

    ``passphrase`` set -> the ZIP is wrapped in the OOENC1 envelope and the
    signing keys ARE included; plaintext (no passphrase) -> keys are EXCLUDED
    and the manifest says so (D2). ``include_newsletters=False`` filters the
    corpus snapshot to drop imported-newsletter articles (maintainer 2026-06-21).
    Returns the manifest envelope.

    NOTE: the encrypted single-file path is one-shot AES-GCM (~2 GiB cap, whole
    archive in RAM) -- fine for small corpora + browser download. A corpus that
    exceeds the cap uses :func:`write_volume_backup` (server-side volume set).
    """
    include_keys = passphrase is not None
    # H3 disk-space preflight: refuse loudly before snapshotting if there is not enough room
    # for the staged snapshot + zip + encrypted output, instead of failing mid-write on a
    # full disk. Estimate from the live corpus DB (+ custody) size, times a peak-usage factor.
    from src.backup.sqlite_backup import live_db_path

    corpus_bytes = live_db_path().stat().st_size if live_db_path().exists() else 0
    custody = data_dir() / _CUSTODY_DB
    corpus_bytes += custody.stat().st_size if custody.exists() else 0
    preflight_free_space(
        dest.parent, corpus_bytes * _BUILD_SPACE_FACTOR, what="backup"
    )
    tmp_dir = dest.parent / f".bak-build-{secrets.token_hex(6)}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        zip_path, envelope = _build_backup_zip(
            tmp_dir, include_keys=include_keys, include_newsletters=include_newsletters
        )
        dest.parent.mkdir(parents=True, exist_ok=True)
        if passphrase is not None:
            from src.safety.crypto import encrypt_bytes

            blob = encrypt_bytes(zip_path.read_bytes(), passphrase)
            tmp_out = dest.with_name(dest.name + ".tmp")
            tmp_out.write_bytes(blob)
            os.replace(tmp_out, dest)
        else:
            os.replace(zip_path, dest)
        return envelope
    finally:
        import shutil

        shutil.rmtree(tmp_dir, ignore_errors=True)


def write_volume_backup(
    dest_dir: Path,
    passphrase: str,
    *,
    include_newsletters: bool = True,
    volume_size: int | None = None,
    parity_fraction: float = 0.1,
    should_stop: "Callable[[], bool] | None" = None,
    progress_cb: "Callable[[dict], None] | None" = None,
) -> dict:
    """Build the LARGE encrypted backup as a SET of <600 MB volumes + parity into the
    server-side directory ``dest_dir``.

    Since the P0.1 scale rework (2026-07-09) this delegates to the oo-volumes-2
    STREAMING engine (:mod:`src.backup.stream_backup`): members are sliced and
    encrypted DIRECTLY into volumes — no plaintext corpus snapshot (the corpus
    streams as its at-rest bytes inside one writer-gate window), no intermediate
    zip, bounded RAM end to end, INCREMENTAL (only changed volumes re-emit) and
    RESUMABLE (an interrupted run continues; a partial set can never be mistaken
    for a complete one — it has no final manifest). Always encrypted (a passphrase
    is required). ``should_stop``/``progress_cb`` drive the task-manager job.
    Returns a measured summary dict."""
    from src.backup.stream_backup import write_stream_backup

    if not passphrase:
        raise ArtifactError("the volume backup is always encrypted: a passphrase is required")
    return write_stream_backup(
        Path(dest_dir),
        passphrase,
        include_newsletters=include_newsletters,
        volume_size=volume_size,
        parity_fraction=parity_fraction,
        should_stop=should_stop,
        progress_cb=progress_cb,
    )


def read_volume_backup(
    src_dir: Path,
    passphrase: str,
    staging_root: Path | None = None,
    *,
    corpus_passphrase: str | None = None,
    include_merge_budget: bool = True,
) -> StagedArtifact:
    """Verify + (parity-)recover + reassemble a volume-set backup from the server-side
    directory ``src_dir``, then stage it like any oo-backup-2 artifact. Streams the
    reassembly to disk (never the whole archive in RAM, no 2 GiB cap). Raises loudly on
    unrecoverable corruption (named volumes) or a checksum/signature failure.

    Dispatches on the manifest kind: oo-volumes-2 (member-streamed, the current
    writer — an encrypted corpus member is converted with ``corpus_passphrase``,
    falling back to the live key then the backup passphrase) or the legacy
    oo-volumes-1 zip reassembly (read forever, D7)."""
    import shutil

    from src.backup.stream_backup import STREAM_KIND, read_stream_backup
    from src.backup.volumes import load_manifest, read_volume_set

    if load_manifest(src_dir).get("kind") == STREAM_KIND:
        return read_stream_backup(
            src_dir,
            passphrase,
            staging_root,
            corpus_passphrase=corpus_passphrase,
            include_merge_budget=include_merge_budget,
        )

    staging = (staging_root or data_dir()) / f".restore-{secrets.token_hex(8)}"
    staging.mkdir(parents=True, exist_ok=False)
    temp_zip = staging / "_reassembled.zip"
    try:
        read_volume_set(src_dir, passphrase, temp_zip)  # verify + parity recover + checksum
        with open(temp_zip, "rb") as fh:
            if fh.read(4) != _ZIP_MAGIC:
                raise ArtifactError("reassembled archive is not an oo-backup-2 zip")
        with zipfile.ZipFile(temp_zip) as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names or "corpus.db" not in names:
                raise ArtifactError("zip is not an oo-backup-2 artifact (missing manifest/corpus)")
            _safe_extract(zf, staging)
        temp_zip.unlink(missing_ok=True)
        return _finalize_staged(staging, was_encrypted=True)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


# --------------------------------------------------------------------------- #
#  Read / stage
# --------------------------------------------------------------------------- #
def _safe_extract(zf: zipfile.ZipFile, staging: Path) -> None:
    """Extract with zip-slip protection: every member must resolve inside staging."""
    root = staging.resolve()
    for info in zf.infolist():
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts:
            raise ArtifactError(f"unsafe member path in artifact: {name!r}")
        target = (staging / name).resolve()
        if not str(target).startswith(str(root)):
            raise ArtifactError(f"unsafe member path in artifact: {name!r}")
    zf.extractall(staging)


def read_artifact(
    blob: bytes, passphrase: str | None = None, staging_root: Path | None = None
) -> StagedArtifact:
    """Detect, decrypt (if needed), unpack and VERIFY an uploaded artifact.

    Accepts, forever (D7): oo-backup-2 zips (plain or OOENC1-wrapped), legacy
    bare SQLite backups, and legacy v1 .ooenc files (OOENC1 around a bare DB).
    Returns a StagedArtifact; raises ArtifactError/EncryptionError on anything
    that cannot be staged safely. Nothing outside the staging dir is touched.
    """
    import shutil

    if not blob:
        raise ArtifactError("empty upload")

    was_encrypted = blob[:8] == b"OOENC1\x00\x00"
    if was_encrypted:
        if passphrase is None:
            raise ArtifactError("this artifact is encrypted: a passphrase is required")
        from src.safety.crypto import decrypt_bytes

        blob = decrypt_bytes(blob, passphrase)  # loud on wrong passphrase/tamper

    # H3 disk-space preflight: the members are extracted to the staging filesystem; the
    # corpus DB (the bulk) is stored uncompressed in the zip, so the extracted size is at
    # least the (decrypted) blob size. Refuse loudly before staging on a full disk.
    root = staging_root or data_dir()
    preflight_free_space(root, len(blob), what="restore")

    staging = root / f".restore-{secrets.token_hex(8)}"
    staging.mkdir(parents=True, exist_ok=False)

    # Anything below this point that raises (a malformed zip, a missing member, a
    # signature/hash mismatch in _finalize_staged...) must not leave the extracted
    # -- potentially plaintext -- corpus copy behind on disk indefinitely. Sibling
    # restore paths (read_volume_backup, read_stream_backup) already clean up on
    # failure; this path did not (audit finding 2026-07-17).
    try:
        if blob[:16] == _SQLITE_MAGIC:
            corpus = staging / "corpus.db"
            corpus.write_bytes(blob)
            return StagedArtifact(
                kind="legacy-ooenc" if was_encrypted else "legacy-db",
                staging_dir=staging,
                corpus_path=corpus,
                custody_path=None,
                manifest=None,
                signature_state="unsigned",
                origin_fingerprint="unsigned",
                members=[{"name": "corpus.db", "role": "corpus"}],
                encrypted=was_encrypted,
            )

        if blob[:4] != _ZIP_MAGIC:
            raise ArtifactError("not an Open Omniscience backup (unknown format)")

        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            names = set(zf.namelist())
            if "manifest.json" not in names or "corpus.db" not in names:
                raise ArtifactError("zip is not an oo-backup-2 artifact (missing manifest/corpus)")
            _safe_extract(zf, staging)
        return _finalize_staged(staging, was_encrypted)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _finalize_staged(
    staging: Path,
    was_encrypted: bool,
    *,
    verified_absent: frozenset[str] = frozenset(),
) -> StagedArtifact:
    """Validate the manifest, verify its signature + member hashes, and build the
    StagedArtifact for an ALREADY-EXTRACTED oo-backup-2 staging dir. Shared by the
    in-memory upload path (read_artifact) and the volume-set paths (read_volume_backup).

    ``verified_absent`` names members whose bytes the STREAMING reassembly already
    checksum-verified and then removed or converted (an encrypted corpus/custody
    member becomes the plaintext copy the merge reads; keeping both would double
    the staging disk at corpus scale) — they are exempt from the missing/hash
    check here, having passed the equivalent check upstream."""
    envelope = json.loads((staging / "manifest.json").read_text("utf-8"))
    manifest = envelope.get("manifest") or {}
    if manifest.get("backup_schema") != BACKUP_SCHEMA:
        raise ArtifactError(
            f"unsupported backup schema {manifest.get('backup_schema')!r} "
            f"(this build reads {BACKUP_SCHEMA})"
        )

    # Verify the manifest signature with the EMBEDDED key: this proves integrity
    # and binds an origin fingerprint -- it does NOT make the content trusted.
    signature_state = "unsigned"
    fingerprint = "unsigned"
    if envelope.get("signature") and envelope.get("public_key"):
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        from src.reporting.evidence import canonical_bytes

        try:
            pub = Ed25519PublicKey.from_public_bytes(bytes.fromhex(envelope["public_key"]))
            pub.verify(bytes.fromhex(envelope["signature"]), canonical_bytes(manifest))
            signature_state = "verified"
            fingerprint = envelope["public_key"]
        except (InvalidSignature, ValueError):
            signature_state = "bad-signature"

    hash_failures: list[str] = []
    for m in manifest.get("members", []):
        if m["name"] in verified_absent:
            continue  # checksum-verified during streamed reassembly, then converted
        p = staging / m["name"]
        if not p.exists():
            hash_failures.append(f"{m['name']}: missing from archive")
        elif _sha256_file(p) != m.get("sha256"):
            hash_failures.append(f"{m['name']}: sha256 mismatch (corrupted or altered)")

    custody = staging / _CUSTODY_DB
    return StagedArtifact(
        kind=BACKUP_SCHEMA,
        staging_dir=staging,
        corpus_path=staging / "corpus.db",
        custody_path=custody if custody.exists() else None,
        manifest=manifest,
        signature_state=signature_state,
        origin_fingerprint=fingerprint,
        members=manifest.get("members", []),
        hash_failures=hash_failures,
        encrypted=was_encrypted,
    )


def cleanup_staging(staged: StagedArtifact) -> None:
    """Remove a staging directory (after merge, or on any failure path)."""
    import shutil

    shutil.rmtree(staged.staging_dir, ignore_errors=True)


def cleanup_stale_staging(max_age_hours: float = 24.0) -> int:
    """Boot-time janitor: remove orphaned backup/restore temps in the data dir —
    ``.restore-*`` AND ``.bak-build-*`` staging dirs plus ``*.oopart`` /
    ``*.reassembling`` files older than ``max_age_hours``. A crashed backup must
    not leak gigabytes silently (2026-07-09 field event: ~120 GB of unidentified
    data-dir growth, prime suspect = orphaned staging — which for the OLD format
    contained a PLAINTEXT corpus snapshot, an at-rest-encryption violation on top).
    Age-guarded and registry-guarded: a LIVE job's staging is never touched
    (src.backup.stream_backup.active_staging). Returns count removed."""
    from src.backup.stream_backup import sweep_stale_backup_temps

    return sweep_stale_backup_temps(data_dir(), max_age_hours=max_age_hours)
