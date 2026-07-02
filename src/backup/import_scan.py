"""
Import folder discovery — classify what's in a folder for the unified Import dialog.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The unified Import points at a folder, scans it, and asks "what do you want to
import?" over what was ACTUALLY FOUND. This module is that curated discovery: a
read-only classification of a directory's contents into the kinds we can import --
our encrypted corpus volume set(s), large-data blobs (wiki dumps / maps / models),
loose ``.eml`` newsletters, a source-list CSV, and legacy single-file backup(s).

The scan is RECURSIVE (bounded depth, junk/blob trees pruned) so a backup that sits
one or more levels deep in a folder of MIXED backups is still detected -- the field
report where only root-level newsletters + maps were found because the corpus volume
set and the legacy archives lived in subfolders. It is pure filesystem + cheap
(``os.walk`` + globs + a one-line CSV sniff; file CONTENTS are never read), so it is
fully unit-testable with a temp directory.
"""

from __future__ import annotations

import os
from pathlib import Path

# Volume-set manifest filename mirrored from src.backup.volumes.MANIFEST_NAME --
# hardcoded so this discovery module stays crypto-free (importing that module pulls in
# the cryptography stack). A CI test (test_import_scan) asserts it stays in sync.
_VOL_MANIFEST = "volumes.json"

# blob category dir on disk -> (import kind key the dialog shows, the folder-restore
# category name). A blob backup made by the folder engine writes <root>/<catdir>/...
_BLOB_DIRS = {"wiki_dumps": "wiki", "osm_regions": "maps", "models": "models"}
_CATKEY_TO_DIR = {"wiki": "wiki_dumps", "maps": "osm_regions", "models": "models"}

# Directory names we never descend into: VCS/build/cache junk + OS recycle bins. A
# leading-dot dir is also skipped (dotfolders are config/cache, never a backup). This
# keeps a recursive scan from wandering into huge irrelevant trees.
_SKIP_DIRS = frozenset(
    {
        "__pycache__",
        "node_modules",
        "venv",
        ".venv",
        "$RECYCLE.BIN",
        "System Volume Information",
        ".Trash",
        ".Trashes",
        ".git",
    }
)

# Bounded recursion depth (relative to the scan root). Backups nested a few levels
# deep are found; a pathological deep tree can never make the scan run away.
_MAX_DEPTH = 8


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


def scan_import_folder(
    path: str | Path, *, max_eml_scan: int = 200_000, max_depth: int = _MAX_DEPTH
) -> dict:
    """Classify a folder's importable contents, RECURSIVELY. Read-only.

    Returns ``{"path", "found": {...}}`` where ``found`` holds only the kinds present:
      * ``corpus``       -- list of ``{path, manifest, volumes}`` volume-set dirs (each
                            restorable independently; a mixed folder can hold several);
      * ``blobs``        -- aggregated per-category ``{count, bytes}`` (for display);
      * ``blob_roots``   -- list of ``{root, categories, <catkey>: {...}}`` — the actual
                            folder-restore units (one restore call per root dir);
      * ``newsletters``  -- ``{count, capped}`` loose ``.eml`` files;
      * ``source_csv``   -- filenames of source-list CSVs (import stays manual for now);
      * ``legacy_backup``-- list of ``{path, name, bytes}`` single-file backups (now a
                            first-class importable item — restored additively in turn).
    """
    root = Path(path)
    if not root.is_dir():
        raise ValueError(f"{path} is not a folder to import from.")

    corpus_dirs: list[Path] = []
    blob_roots: dict[str, dict] = {}  # parent-dir-str -> {catkey: totals}
    source_csv: list[str] = []
    legacy: list[dict] = []
    eml = 0
    eml_capped = False

    root_depth = len(root.parts)
    for cur, dirnames, filenames in os.walk(root):
        curp = Path(cur)
        depth = len(curp.parts) - root_depth

        # Stop descending past the depth bound, and never enter junk trees.
        if depth >= max_depth:
            dirnames[:] = []
        else:
            keep: list[str] = []
            for d in dirnames:
                if d in _SKIP_DIRS or d.startswith("."):
                    continue
                if d in _BLOB_DIRS:
                    # A blob category dir: record its totals but DON'T descend — walking
                    # thousands of model blobs while hunting for the other kinds is waste.
                    totals = _dir_totals(curp / d)
                    if totals["count"]:
                        blob_roots.setdefault(str(curp), {})[_BLOB_DIRS[d]] = totals
                    continue
                keep.append(d)
            dirnames[:] = keep

        for fn in filenames:
            low = fn.lower()
            if fn == _VOL_MANIFEST:
                corpus_dirs.append(curp)
            elif low.endswith(".eml"):
                if eml < max_eml_scan:
                    eml += 1
                else:
                    eml_capped = True
            elif low.endswith(".csv"):
                if _looks_like_source_csv(curp / fn) and fn not in source_csv:
                    source_csv.append(fn)
            elif fn.startswith("open-omniscience-") and not low.endswith(".oomodels"):
                fp = curp / fn
                if fp.is_file():
                    try:
                        sz = fp.stat().st_size
                    except OSError:
                        sz = 0
                    legacy.append({"path": str(fp), "name": fn, "bytes": sz})

    found: dict = {}

    if corpus_dirs:
        found["corpus"] = [
            {"path": str(d), "manifest": _VOL_MANIFEST, "volumes": _volume_count(d)}
            for d in corpus_dirs
        ]

    if blob_roots:
        agg: dict[str, dict] = {}
        for cats in blob_roots.values():
            for k, tot in cats.items():
                a = agg.setdefault(k, {"count": 0, "bytes": 0})
                a["count"] += tot["count"]
                a["bytes"] += tot["bytes"]
        found["blobs"] = agg
        found["blob_roots"] = [
            {
                "root": rd,
                "categories": [_CATKEY_TO_DIR[k] for k in cats],
                **cats,
            }
            for rd, cats in sorted(blob_roots.items())
        ]

    if eml:
        found["newsletters"] = {"count": eml, "capped": eml_capped}

    if source_csv:
        found["source_csv"] = sorted(source_csv)

    if legacy:
        found["legacy_backup"] = sorted(legacy, key=lambda x: x["name"])

    return {"path": str(root), "found": found}


def _volume_count(d: Path) -> int:
    """Number of encrypted volume files beside a ``volumes.json`` (cheap glob)."""
    try:
        return sum(1 for p in d.glob("*.ooenc*") if p.is_file())
    except OSError:
        return 0
