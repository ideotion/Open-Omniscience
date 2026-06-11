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
import secrets
import sqlite3
import zipfile
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

_SQLITE_MAGIC = b"SQLite format 3\x00"
_ZIP_MAGIC = b"PK\x03\x04"


class ArtifactError(RuntimeError):
    """Raised when an artifact cannot be built or read safely."""


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
    """Consistent online-backup snapshot of ANY SQLite file (WAL-safe)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dest))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()
    return dest


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
            counts[t] = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]  # noqa: S608
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
    never silent -- D3)."""
    out: list[dict] = []
    dumps = data_dir() / _WIKI_DUMPS_DIR
    if dumps.is_dir():
        files = [p for p in dumps.rglob("*") if p.is_file()]
        if files:
            out.append(
                {
                    "name": _WIKI_DUMPS_DIR,
                    "reason": "re-downloadable offline Wikipedia dumps (design D3); "
                    "re-download via Settings after restore",
                    "files": len(files),
                    "bytes": sum(p.stat().st_size for p in files),
                }
            )
    return out


def _collect_members(include_keys: bool, tmp_dir: Path) -> list[Member]:
    """Snapshot the databases into tmp_dir and inventory every side file."""
    from src.backup.sqlite_backup import live_db_path

    members: list[Member] = []

    corpus_snap = tmp_dir / "corpus.db"
    snapshot_sqlite(live_db_path(), corpus_snap)
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
def write_backup_v2(dest: Path, passphrase: str | None = None) -> dict:
    """Build a complete oo-backup-2 artifact at ``dest``.

    ``passphrase`` set -> the ZIP is wrapped in the OOENC1 envelope and the
    signing keys ARE included; plaintext (no passphrase) -> keys are EXCLUDED
    and the manifest says so (D2). Returns the manifest envelope.
    """
    from src.reporting.evidence import (
        canonical_bytes,
        load_or_create_signing_key,
        public_key_hex,
    )
    from src.utils.export_envelope import app_version

    include_keys = passphrase is not None
    # Materialise the signing key BEFORE collecting members: a first-ever encrypted
    # backup must carry the very key that signs its manifest.
    key = load_or_create_signing_key()
    tmp_dir = dest.parent / f".bak-build-{secrets.token_hex(6)}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        members = _collect_members(include_keys, tmp_dir)
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
    if not blob:
        raise ArtifactError("empty upload")

    was_encrypted = blob[:8] == b"OOENC1\x00\x00"
    if was_encrypted:
        if passphrase is None:
            raise ArtifactError("this artifact is encrypted: a passphrase is required")
        from src.safety.crypto import decrypt_bytes

        blob = decrypt_bytes(blob, passphrase)  # loud on wrong passphrase/tamper

    staging = (staging_root or data_dir()) / f".restore-{secrets.token_hex(8)}"
    staging.mkdir(parents=True, exist_ok=False)

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
        )

    if blob[:4] != _ZIP_MAGIC:
        raise ArtifactError("not an Open Omniscience backup (unknown format)")

    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        names = set(zf.namelist())
        if "manifest.json" not in names or "corpus.db" not in names:
            raise ArtifactError("zip is not an oo-backup-2 artifact (missing manifest/corpus)")
        _safe_extract(zf, staging)

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
    )


def cleanup_staging(staged: StagedArtifact) -> None:
    """Remove a staging directory (after merge, or on any failure path)."""
    import shutil

    shutil.rmtree(staged.staging_dir, ignore_errors=True)


def cleanup_stale_staging(max_age_hours: float = 24.0) -> int:
    """Boot-time janitor: remove .restore-* staging dirs older than max_age_hours
    (a crashed restore must not leak gigabytes silently). Returns count removed."""
    import shutil
    import time

    removed = 0
    cutoff = time.time() - max_age_hours * 3600
    for p in data_dir().glob(".restore-*"):
        try:
            if p.is_dir() and p.stat().st_mtime < cutoff:
                shutil.rmtree(p, ignore_errors=True)
                removed += 1
        except OSError:  # pragma: no cover
            continue
    return removed
