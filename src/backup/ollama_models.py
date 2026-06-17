"""
Companion backup of the local Ollama model store (maintainer-asked 2026-06-17:
"there should be an option to integrate [LLM models in the backup] to avoid
re-downloading models").

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

DESIGN (ledger, the wiki-dump-inclusion family):
  * Models live in OLLAMA's OWN store (``$OLLAMA_MODELS`` or ``~/.ollama/models``),
    OUTSIDE the app's data_dir — so this is a SEPARATE, OPT-IN companion artifact,
    never woven into the signed oo-backup-2 (which stays small + quick).
  * Ollama's store is content-addressed: ``manifests/<host>/<ns>/<model>/<tag>`` is
    a JSON manifest referencing ``blobs/sha256-<hex>`` files. So DEDUP BY CHECKSUM is
    INHERENT (a blob shared by two models is stored once, by its sha256 name) and
    "never overwrite a differing blob" is automatic (same name ⇒ identical content).
  * Restore = copy the manifests + the missing blobs into the target store; existing
    blobs are skipped (already identical). Bit-identical, never destructive.

This module is pure filesystem + zipfile (no network, no Ollama process); the
caller decides WHICH models and WHEN (opt-in). Bandit/zip-slip safe: every archive
member is validated before extraction.
"""

from __future__ import annotations

import json
import os
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

ARCHIVE_SCHEMA = "oo-ollama-models-1"
_MANIFESTS = "manifests"
_BLOBS = "blobs"


def default_store() -> Path:
    """The Ollama model store path (may not exist yet — used as a restore target too).

    Honours ``$OLLAMA_MODELS``; else the per-OS default ``~/.ollama/models``. We never
    bundle models in the repo — this only reads/writes the user's OWN local store.
    """
    env = os.getenv("OLLAMA_MODELS")
    return Path(env) if env else Path.home() / ".ollama" / "models"


def _digest_to_blob(digest: str) -> str | None:
    """``sha256:<hex>`` -> the blob filename ``sha256-<hex>`` (None if malformed)."""
    if not digest or ":" not in digest:
        return None
    algo, hexv = digest.split(":", 1)
    if not algo.isalnum() or not hexv or not all(c in "0123456789abcdefABCDEF" for c in hexv):
        return None
    return f"{algo}-{hexv}"


@dataclass
class ModelEntry:
    ref: str                       # host/ns/model:tag (display)
    manifest_rel: str              # POSIX path under manifests/
    blobs: list[str] = field(default_factory=list)   # blob filenames (sha256-...)
    bytes: int = 0

    def to_dict(self) -> dict:
        return {"ref": self.ref, "manifest_rel": self.manifest_rel, "blobs": self.blobs, "bytes": self.bytes}


def list_models(store: Path) -> list[ModelEntry]:
    """Enumerate installed models by walking ``manifests/``; resolve each one's blobs
    + total size. Malformed/half-written manifests are skipped (best-effort, never
    raises). Returns [] when the store has no manifests."""
    mroot = store / _MANIFESTS
    broot = store / _BLOBS
    out: list[ModelEntry] = []
    if not mroot.is_dir():
        return out
    for mf in sorted(p for p in mroot.rglob("*") if p.is_file()):
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001 - skip unreadable/partial manifests
            continue
        rel_parts = mf.relative_to(mroot).parts
        # <host>/<ns>/<model>/<tag>  ->  host/ns/model:tag
        ref = "/".join(rel_parts[:-1]) + ":" + rel_parts[-1] if len(rel_parts) >= 2 else "/".join(rel_parts)
        digests = []
        cfg = data.get("config") or {}
        if isinstance(cfg, dict) and cfg.get("digest"):
            digests.append(cfg["digest"])
        for layer in data.get("layers") or []:
            if isinstance(layer, dict) and layer.get("digest"):
                digests.append(layer["digest"])
        blobs, total = [], 0
        for d in digests:
            fn = _digest_to_blob(d)
            if not fn:
                continue
            if fn not in blobs:
                blobs.append(fn)
                bp = broot / fn
                if bp.is_file():
                    total += bp.stat().st_size
        out.append(ModelEntry(ref=ref, manifest_rel=mf.relative_to(mroot).as_posix(), blobs=blobs, bytes=total))
    return out


def build_models_archive(dest: Path, store: Path, refs: list[str] | None = None) -> dict:
    """Write an OPT-IN companion archive of selected models (or all) to ``dest``.

    Carries each model's manifest + the blobs it references, DEDUPED across models by
    blob filename (= by sha256), plus a manifest.json inventory. Returns a summary;
    raises FileNotFoundError if the store has no models."""
    models = list_models(store)
    if refs is not None:
        wanted = set(refs)
        models = [m for m in models if m.ref in wanted]
    if not models:
        raise FileNotFoundError("no Ollama models found to back up")

    blob_set: dict[str, int] = {}
    for m in models:
        for fn in m.blobs:
            bp = store / _BLOBS / fn
            if bp.is_file():
                blob_set[fn] = bp.stat().st_size

    manifest = {
        "schema": ARCHIVE_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "models": [m.to_dict() for m in models],
        "blobs": [{"name": fn, "bytes": sz} for fn, sz in sorted(blob_set.items())],
        "total_bytes": sum(blob_set.values()),
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_STORED) as z:  # blobs are already compressed
        z.writestr("manifest.json", json.dumps(manifest, indent=2))
        for m in models:
            src = store / _MANIFESTS / Path(m.manifest_rel)
            if src.is_file():
                z.write(src, f"{_MANIFESTS}/{m.manifest_rel}")
        for fn in blob_set:
            z.write(store / _BLOBS / fn, f"{_BLOBS}/{fn}")
    return {
        "path": str(dest), "models": len(models), "blobs": len(blob_set),
        "total_bytes": manifest["total_bytes"], "archive_bytes": dest.stat().st_size,
    }


def _safe_member(name: str) -> str | None:
    """Validate an archive member path (zip-slip defense): only ``manifests/`` or
    ``blobs/`` members, no absolute paths, no ``..`` traversal. Returns the cleaned
    POSIX relpath, or None to reject."""
    if not name or name.startswith("/") or "\\" in name:
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if any(p == ".." for p in parts):
        return None
    if not parts or parts[0] not in (_MANIFESTS, _BLOBS):
        return None
    return "/".join(parts)


def restore_models_archive(archive: Path, store: Path) -> dict:
    """Restore an oo-ollama-models archive into ``store`` (created if absent).

    Blobs are content-addressed: an existing blob (same sha256 filename) is skipped —
    NEVER overwritten (it is already identical), so a restore is additive + bit-safe.
    Manifests are written (a re-import simply re-points to the same blobs). Returns
    counts. Rejects malformed/traversing members (zip-slip safe)."""
    blobs_added = blobs_skipped = manifests = rejected = 0
    with zipfile.ZipFile(archive, "r") as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            rel = _safe_member(info.filename)
            if rel is None:
                if info.filename != "manifest.json":
                    rejected += 1
                continue
            target = store / rel
            kind = rel.split("/", 1)[0]
            if kind == _BLOBS and target.exists():
                blobs_skipped += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as srcf, open(target, "wb") as out:
                out.write(srcf.read())
            if kind == _BLOBS:
                blobs_added += 1
            else:
                manifests += 1
    return {
        "store": str(store), "models": manifests,
        "blobs_added": blobs_added, "blobs_skipped": blobs_skipped, "rejected": rejected,
    }
