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
import sys
from dataclasses import dataclass, field
from pathlib import Path

_MANIFESTS = "manifests"
_BLOBS = "blobs"

# The Linux systemd default. The official `curl | sh` install runs Ollama as a
# dedicated ``ollama`` SYSTEM USER, so the store is that user's home —
# /usr/share/ollama/.ollama/models — NOT ~/.ollama/models, and it is owned by the
# ollama user (mode 0700), so the app (running as the human user) cannot read it.
# Backing models up then needs OLLAMA_MODELS pointed at a path the user owns
# (systemctl edit ollama.service -> Environment="OLLAMA_MODELS=/your/path").
_LINUX_SERVICE_STORE = Path("/usr/share/ollama/.ollama/models")


def candidate_stores() -> list[Path]:
    """Ordered, de-duplicated candidate model-store locations, most authoritative
    first: ``$OLLAMA_MODELS`` (explicit), the per-user default ``~/.ollama/models``,
    and (on Linux) the protected systemd-service location. Used to FIND models even
    when the user installed Ollama as a service, and to explain where they are."""
    out: list[Path] = []
    env = os.getenv("OLLAMA_MODELS")
    if env:
        out.append(Path(env))
    out.append(Path.home() / ".ollama" / "models")
    if sys.platform.startswith("linux"):
        out.append(_LINUX_SERVICE_STORE)
    seen: set[str] = set()
    uniq: list[Path] = []
    for p in out:
        if str(p) not in seen:
            seen.add(str(p))
            uniq.append(p)
    return uniq


def _has_manifests(store: Path) -> bool:
    """True if the store holds at least one manifest we can SEE (readable). A
    PermissionError (the protected service store) reads as 'not here for us'."""
    mroot = store / _MANIFESTS
    try:
        return mroot.is_dir() and any(mroot.iterdir())
    except (OSError, PermissionError):
        return False


def default_store() -> Path:
    """The Ollama model store path (may not exist yet — used as a restore target too).

    ``$OLLAMA_MODELS`` always wins (explicit operator intent). Otherwise we pick the
    first candidate that actually holds READABLE models — so a service install whose
    models live in /usr/share/ollama is found, not silently missed — and fall back to
    the per-user default ``~/.ollama/models`` (also the writable restore target). We
    never bundle models in the repo; this only reads/writes the user's OWN store.
    """
    env = os.getenv("OLLAMA_MODELS")
    if env:
        return Path(env)
    for p in candidate_stores():
        if _has_manifests(p):
            return p
    return Path.home() / ".ollama" / "models"


def store_status(store: Path | None = None) -> dict:
    """Honest status of the model store for the backup UI.

    Reports the chosen store, the readable models, AND — crucially — whether a
    PROTECTED store exists that we cannot read (the Linux service install). When
    models can't be reached we degrade LOUDLY with an actionable hint (set
    OLLAMA_MODELS to a path you own), never a silent "no models". No network.
    """
    store = store or default_store()
    models = list_models(store)
    # Look for a candidate that exists but is unreadable to us (protected), so we can
    # explain WHERE the models are and HOW to make them backup-able.
    protected_path: str | None = None
    for p in candidate_stores():
        mroot = p / _MANIFESTS
        try:
            present = mroot.is_dir()
        except OSError:
            present = True  # a stat error usually means a permission wall
        if not present:
            continue
        try:
            readable = any(mroot.iterdir())  # can we actually enumerate it?
            if readable and not list_models(p):
                readable = False
        except (OSError, PermissionError):
            readable = False
        if not readable and not (str(p) == str(store) and models):
            protected_path = str(p)
            break
    hint = None
    if not models:
        if protected_path:
            hint = (
                f"Ollama's models appear to be in a protected location ({protected_path}) "
                "that this app can't read. On Linux the service install runs as the "
                "'ollama' user. To back them up, point OLLAMA_MODELS at a path you own "
                "(systemctl edit ollama.service → Environment=\"OLLAMA_MODELS=/your/path\", "
                "then daemon-reload + restart ollama), or copy the store somewhere readable."
            )
        else:
            hint = (
                "No Ollama models found. Pull a model first, or set OLLAMA_MODELS if your "
                "store is in a custom location."
            )
    return {
        "store": str(store),
        "store_present": (store / _MANIFESTS).is_dir(),
        "models": [m.to_dict() for m in models],
        "total_bytes": sum(m.bytes for m in models),
        "protected_store": protected_path,
        "candidates": [str(p) for p in candidate_stores()],
        "hint": hint,
    }


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
    try:
        files = sorted(p for p in mroot.rglob("*") if p.is_file())
    except (OSError, PermissionError):
        # A protected store (e.g. the ollama-user-owned service dir): we can see the
        # directory but not its contents. Report nothing here; store_status() turns
        # this into honest, actionable guidance rather than a silent empty result.
        return out
    for mf in files:
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
