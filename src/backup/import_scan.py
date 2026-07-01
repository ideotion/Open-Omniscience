"""
Import folder discovery — classify what's in a folder for the unified Import dialog.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The unified Import points at a folder, scans it, and asks "what do you want to
import?" over what was ACTUALLY FOUND. This module is that curated discovery: a
read-only classification of a directory's contents into the kinds we can import --
our encrypted corpus volume set, large-data blobs (wiki dumps / maps / models),
loose ``.eml`` newsletters, a source-list CSV, and a legacy single-file backup.

Pure filesystem + cheap (globs + one-line CSV sniff; never reads whole files), so
it is fully unit-testable with a temp directory.
"""

from __future__ import annotations

from pathlib import Path

# Volume-set manifest filename mirrored from src.backup.volumes.MANIFEST_NAME --
# hardcoded so this discovery module stays crypto-free (importing that module pulls in
# the cryptography stack). A CI test (test_import_scan) asserts it stays in sync.
_VOL_MANIFEST = "volumes.json"

# category dir on disk -> the import kind key the dialog shows
_BLOB_DIRS = {"wiki_dumps": "wiki", "osm_regions": "maps", "models": "models"}


def _dir_totals(d: Path) -> dict:
    files = [p for p in d.rglob("*") if p.is_file()]
    return {"count": len(files), "bytes": sum(p.stat().st_size for p in files)}


def _looks_like_source_csv(p: Path) -> bool:
    """A source-list CSV has a 'domain' column in its header (cheap one-line sniff)."""
    try:
        with p.open("r", encoding="utf-8", errors="ignore") as fh:
            header = (fh.readline() or "").lower()
        return "domain" in header
    except OSError:
        return False


def scan_import_folder(path: str | Path, *, max_eml_scan: int = 200_000) -> dict:
    """Classify a folder's importable contents. Read-only.

    Returns ``{"path", "found": {...}}`` where ``found`` holds only the kinds present:
      corpus (volume set), blobs (per-category counts+bytes), newsletters (.eml count),
      source_csv (filenames), legacy_backup (filenames).
    """
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"{path} is not a folder to import from.")

    found: dict = {}

    if (root / _VOL_MANIFEST).is_file():
        found["corpus"] = {"manifest": _VOL_MANIFEST}

    blobs: dict = {}
    for cat, key in _BLOB_DIRS.items():
        d = root / cat
        if d.is_dir():
            totals = _dir_totals(d)
            if totals["count"]:
                blobs[key] = totals
    if blobs:
        found["blobs"] = blobs

    # loose .eml newsletters (bounded stat-walk; contents never read)
    eml = 0
    for _ in root.rglob("*.eml"):
        eml += 1
        if eml >= max_eml_scan:
            break
    if eml:
        found["newsletters"] = {"count": eml, "capped": eml >= max_eml_scan}

    csvs = [p.name for p in sorted(root.glob("*.csv")) if _looks_like_source_csv(p)]
    if csvs:
        found["source_csv"] = csvs

    # legacy single-file backup (the download name convention), never the models one
    legacy = [
        p.name
        for p in sorted(root.glob("open-omniscience-*"))
        if p.is_file() and not p.name.endswith(".oomodels")
    ]
    if legacy:
        found["legacy_backup"] = legacy

    return {"path": str(root), "found": found}
