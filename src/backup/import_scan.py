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
import re
import stat
from collections.abc import Callable
from pathlib import Path

from src.backup.hf_layout import HF_LAYOUT, hf_member_allowed
from src.backup.links import is_link, is_link_stat
from src.backup.manifest_file import read_manifest_json

# Volume-set manifest filename mirrored from src.backup.volumes.MANIFEST_NAME --
# hardcoded so this discovery module stays crypto-free (importing that module pulls in
# the cryptography stack). A CI test (test_import_scan) asserts it stays in sync.
_VOL_MANIFEST = "volumes.json"

# Large-data folder-backup manifest, mirrored from folder_backup.MANIFEST_NAME. When a
# large-data (wiki/maps/models) backup completes, the engine writes this JSON at the
# backup ROOT listing exactly which categories it carries and their per-file sizes. We
# anchor detection on it so a completed folder backup is ALWAYS recognised — the plain
# dir-name walk can miss a category if the on-disk layout is unusual, but the manifest
# is authoritative (field report 2026-07-02: wiki/maps/models "not recognised" on
# import). A CI test asserts this filename stays in sync with the backup engine.
_FOLDER_MANIFEST = "oo-folder-backup.json"

# blob category dir on disk -> (import kind key the dialog shows, the folder-restore
# category name). A blob backup made by the folder engine writes <root>/<catdir>/...
# R777: ``hf_models`` (the Hugging Face cache vLLM reads) has been written by the folder backup since it
# learned that category, but the scan never listed it, so no restore ever asked for it. It is its own
# kind here, shown beside ``models`` as the one "LLM models" line, and restored like the others: files
# only, never downloaded, an existing file never overwritten.
_BLOB_DIRS = {"wiki_dumps": "wiki", "osm_regions": "maps", "models": "models", "hf_models": "hf_models"}
_CATKEY_TO_DIR = {"wiki": "wiki_dumps", "maps": "osm_regions", "models": "models", "hf_models": "hf_models"}

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


# Row 293: why a large-data count is a lower bound, or leaves something out. Whole sentences and locale keys (the
# Import checklist passes them through t()), so the reason reads in the person's language on the hover.
SCAN_UNREAD = "Some files or folders here could not be read, so this count includes only the ones that could."
SCAN_LINKS = "Links in this backup folder are not counted: a restore never follows a link, so they are never restored."
SCAN_UNSIZED = "This file's size could not be read."
# R780: never call the manifest proof of origin -- it is signed with a key it carries itself.
SCAN_UNLISTED = (
    "Some files here are not listed in this backup's current manifest; they may come from an earlier or interrupted "
    "backup pass. They are restored like the others, without a recorded checksum to check them against. Anyone who can "
    "write to this backup folder could also have placed them there, or listed files of their own: the manifest carries "
    "its own signing key."
)
# The suffix of a copy in progress (src.backup.folder_backup._PART_SUFFIX): a restore skips it, so the scan does too.
_PART_SUFFIX = ".oopart"


# R779: what a category folder that is a link holds for a restore: nothing, and why.
SCAN_LINKED_CATEGORY = (
    "This folder in the backup is a link, and a restore never follows a link, so nothing in it will be restored. "
    "To restore it, copy the real folder into the backup in place of the link."
)


def _LINKED_CATEGORY() -> dict:  # noqa: N802 - reads as the constant it stands for, built fresh each time
    return {"count": 0, "bytes": 0, "linked": True, "reason": SCAN_LINKED_CATEGORY}


def _dir_totals(d: Path, allow: Callable[[str], bool] | None = None, listed: set[str] | None = None,
               check_listed: bool = False) -> dict:
    """``{count, bytes}`` of what a folder restore would restore from one category folder, plus
    ``unread_entries`` (folders or files it was refused) and ``refused_links`` when non-zero.

    It counts exactly what ``restore_folder_backup`` copies: regular files, never a ``.oopart``,
    never a link (restore refuses every link, file or folder, and never follows one). A refusal
    no longer fails the whole scan (row 293): it is counted, so the page can say the count is a
    lower bound. A file that vanished mid-scan is gone, not unread.

    ``allow`` (R777, the model-cache folder): a file whose path relative to ``d`` it refuses is not
    counted but counted apart in ``refused_layout``, exactly as the restore refuses it.

    R780: ``listed`` is the set of ``rel`` names the backup's current manifest lists for this category
    (``None``: no readable manifest); it is read only when ``check_listed`` is set. A file it does not list is counted in ``unlisted``: it is still
    restored, and the page says so apart from "not content-verified"."""
    count = nbytes = unread = links = refused_layout = unlisted = 0

    def _refused(err: OSError) -> None:
        nonlocal unread
        if not isinstance(err, FileNotFoundError):
            unread += 1

    for dirpath, dirnames, names in os.walk(d, onerror=_refused, followlinks=False):
        # os.walk lists a link to a folder among the folders and never enters it; restore refuses it.
        # A ".oopart" name is skipped by restore before its link check, so it is not a refused link either.
        enter: list[str] = []
        for n in dirnames:
            try:
                linked = is_link(os.path.join(dirpath, n))
            except OSError:
                unread += 1  # a name it may not look at is said, never taken for a plain folder
                continue
            if not linked:
                enter.append(n)  # restore walks into a plain folder whatever its name, ".oopart" too
            elif not n.endswith(_PART_SUFFIX):
                links += 1  # never entered: a junction is pruned here too, whatever os.walk would do
        dirnames[:] = enter
        for name in names:
            if name.endswith(_PART_SUFFIX):
                continue
            try:
                st = os.lstat(os.path.join(dirpath, name))
            except FileNotFoundError:
                continue
            except OSError:
                unread += 1
                continue
            if is_link_stat(st):  # a junction or reparse point too (R779)
                links += 1
            elif stat.S_ISREG(st.st_mode):
                if allow is not None and not allow(Path(os.path.join(dirpath, name)).relative_to(d).as_posix()):
                    refused_layout += 1
                    continue
                count += 1
                nbytes += st.st_size
                if check_listed and (listed is None or Path(os.path.join(dirpath, name)).relative_to(d).as_posix() not in listed):
                    unlisted += 1
    out: dict = {"count": count, "bytes": nbytes}
    if refused_layout:
        out["refused_layout"] = refused_layout
    if unlisted:
        out.update(unlisted=unlisted, unlisted_reason=SCAN_UNLISTED)
    if unread:
        out.update(unread_entries=unread, reason=SCAN_UNREAD)
    if links:
        out["refused_links"] = links
    return out


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
    try:
        is_folder = root.is_dir()
    except OSError:
        # A folder above it refused the look (row 293): the operator's 400, never a 500.
        raise ValueError(f"{path} could not be read, so it cannot be scanned.") from None
    if not is_folder:
        raise ValueError(f"{path} is not a folder to import from.")

    corpus_dirs: list[Path] = []
    blob_roots: dict[str, dict] = {}  # parent-dir-str -> {catkey: totals}
    folder_manifests: list[Path] = []  # dirs holding an oo-folder-backup.json
    source_csv: list[str] = []
    legacy: list[dict] = []
    eml = 0
    eml_capped = False

    root_depth = len(root.parts)
    unread_folders = 0

    def _folder_refused(err: OSError) -> None:
        nonlocal unread_folders
        if not isinstance(err, FileNotFoundError):
            unread_folders += 1  # row 293: said on the page, never silently skipped

    listings: dict[str, dict[str, set[str]] | None] = {}  # R780: each backup folder's manifest, read once
    for cur, dirnames, filenames in os.walk(root, onerror=_folder_refused):
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
                    # R779: a category folder that is itself a link is never walked (``os.walk``
                    # follows its TOP), because a restore refuses it: it is listed with nothing
                    # to restore and the reason, so the preview and the restore agree.
                    try:
                        linked = is_link(curp / d)
                    except OSError:
                        unread_folders += 1
                        continue
                    if linked:
                        totals = _LINKED_CATEGORY()
                    else:
                        if str(curp) not in listings:
                            listings[str(curp)] = _manifest_listing(curp / _FOLDER_MANIFEST)
                        lst = listings[str(curp)]
                        totals = _dir_totals(curp / d, hf_member_allowed if d == "hf_models" else None,
                                             None if lst is None else lst.get(d, set()), check_listed=True)
                    if totals["count"] or totals.get("unread_entries") or totals.get("linked") or totals.get("refused_layout"):
                        blob_roots.setdefault(str(curp), {})[_BLOB_DIRS[d]] = totals
                    continue
                keep.append(d)
            dirnames[:] = keep

        for fn in filenames:
            low = fn.lower()
            if fn == _VOL_MANIFEST:
                corpus_dirs.append(curp)
            elif fn == _FOLDER_MANIFEST:
                folder_manifests.append(curp)
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
                # ONE stat, guarded (row 293): Path.is_file() raises a PermissionError rather than
                # answering False, so it could fail the whole scan from a folder it may list but not enter.
                item: dict = {"path": str(fp), "name": fn}
                try:
                    st = os.stat(fp)
                except FileNotFoundError:
                    continue
                except OSError:
                    item.update(bytes=None, reason=SCAN_UNSIZED)  # unread, never 0; restore says its own error
                    legacy.append(item)
                    continue
                if stat.S_ISREG(st.st_mode):
                    item["bytes"] = st.st_size
                    legacy.append(item)

    # Manifest-anchored blobs: a completed large-data backup declares its categories
    # authoritatively. Merge them in so a folder backup is recognised even if the plain
    # dir-name walk missed a category (the field bug: wiki/maps/models "not recognised").
    # On-disk totals win when the category dir is present; else fall back to the
    # manifest's own counts so the user still sees what the backup carries.
    for mdir in folder_manifests:
        cats = _read_folder_manifest(mdir / _FOLDER_MANIFEST)
        if not cats:
            continue
        root_totals = blob_roots.setdefault(str(mdir), {})
        for catdir, (count, nbytes) in cats.items():
            catkey = _BLOB_DIRS.get(catdir)
            if not catkey:
                continue  # unknown category
            seen = root_totals.get(catkey)
            if seen and (seen["count"] or not seen.get("unread_entries")):
                continue  # the dir-walk already measured it on disk
            if count:
                # Row 293: a category folder the walk could not read at all keeps its reason, and the
                # manifest's declared totals stand in for the 0 it read.
                root_totals[catkey] = {"count": count, "bytes": nbytes, "from_manifest": True,
                                       **({k: seen[k] for k in ("unread_entries", "reason") if k in seen} if seen else {})}
        if not root_totals:  # a manifest with zero non-empty categories: drop the empty root
            blob_roots.pop(str(mdir), None)

    # R784: whether each backup folder carrying the model cache recorded WHICH folder it read. One
    # without the record was made when the backup read ``<parent of HF_HUB_CACHE>/hub``: its models
    # restore to the right place, but a cache folder named otherwise on that computer is not in it.
    for rd, root_cats in blob_roots.items():
        hf = root_cats.get("hf_models")
        if hf is not None and not hf.get("linked"):
            # Only a manifest that was READ can say it predates the record; a folder with no readable
            # manifest (copied by hand) is not called old, since nothing says when it was made.
            data = read_manifest_json(Path(rd) / _FOLDER_MANIFEST)
            if isinstance(data, dict) and isinstance(data.get("categories"), dict):
                hf["layout_recorded"] = data.get("hf_layout") == HF_LAYOUT

    found: dict = {}

    if corpus_dirs:
        found["corpus"] = [
            {
                "path": str(d),
                "manifest": _VOL_MANIFEST,
                "volumes": _volume_count(d),
                # Unencrypted volume copies an interrupted import left here before R686: named, never removed
                # unless the operator asks (POST /api/backup/import-scan/remove-leftover-plaintext).
                "leftover_plaintext": leftover_plaintext(d),
            }
            for d in corpus_dirs
        ]

    if blob_roots:
        agg: dict[str, dict] = {}
        # `root_cats`, not `cats`: the name `cats` is already bound above to
        # _read_folder_manifest's `{catdir: (count, bytes)}` TUPLE mapping, and one
        # name holding two shapes in one function scope is what made the checker read
        # `tot` as a tuple here. Runtime never confused them (the bindings do not
        # overlap in time); the reader and the checker both did.
        for root_cats in blob_roots.values():
            for k, tot in root_cats.items():
                a = agg.setdefault(k, {"count": 0, "bytes": 0})
                a["count"] += tot["count"]
                a["bytes"] += tot["bytes"]
                for extra in ("unread_entries", "refused_links", "refused_layout", "unlisted"):
                    if tot.get(extra):
                        a[extra] = a.get(extra, 0) + tot[extra]
                if tot.get("unread_entries"):
                    a["reason"] = SCAN_UNREAD
                if tot.get("unlisted"):
                    a["unlisted_reason"] = SCAN_UNLISTED
                if k == "hf_models" and tot.get("layout_recorded") is False:
                    a["layout_unrecorded"] = a.get("layout_unrecorded", 0) + 1  # R784, per backup folder
                if tot.get("linked"):
                    # R779: counted per backup folder, since two backups can each hold one.
                    a["linked"] = a.get("linked", 0) + 1
        found["blobs"] = agg
        found["blob_roots"] = [
            {
                "root": rd,
                "categories": [_CATKEY_TO_DIR[k] for k in root_cats],
                **root_cats,
            }
            for rd, root_cats in sorted(blob_roots.items())
        ]

    if eml:
        found["newsletters"] = {"count": eml, "capped": eml_capped}

    if source_csv:
        found["source_csv"] = sorted(source_csv)

    if legacy:
        found["legacy_backup"] = sorted(legacy, key=lambda x: x["name"])

    if unread_folders:
        # Folders the walk was refused: whatever they hold is not listed above.
        found["unread_folders"] = unread_folders

    return {"path": str(root), "found": found}


def _manifest_listing(p: Path) -> dict[str, set[str]] | None:
    """``{catdir: {rel}}`` of every file a folder-backup manifest lists, or ``None`` when there is none
    that can be read (R780; mirrors ``folder_backup._manifest_listing``, kept here so this discovery
    module stays crypto-free and import-light)."""
    data = read_manifest_json(p)  # a link, a pipe, a huge or deeply nested file: no listing
    cats = data.get("categories") if isinstance(data, dict) else None
    if not isinstance(cats, dict):
        return None
    return {
        str(c): {e["rel"] for e in items if isinstance(e, dict) and isinstance(e.get("rel"), str)}
        for c, items in cats.items()
        if isinstance(items, list)
    }


def _read_folder_manifest(p: Path) -> dict[str, tuple[int, int]]:
    """Parse a folder-backup manifest into ``{catdir: (file_count, total_bytes)}``.

    The manifest's ``categories`` maps each category dir (wiki_dumps/osm_regions/models)
    to a list of ``{rel, size}`` items. Returns only categories that carry files. Any
    parse error yields ``{}`` (best-effort — never let a stray file break the scan)."""
    data = read_manifest_json(p)  # a link, a pipe, a huge or deeply nested file: nothing
    cats = data.get("categories") if isinstance(data, dict) else None
    if not isinstance(cats, dict):
        return {}
    out: dict[str, tuple[int, int]] = {}
    for catdir, items in cats.items():
        if not isinstance(items, list) or not items:
            continue
        # A size that is not a whole number (text, null, a list) counts as 0, never stops the scan.
        nbytes = sum(it["size"] for it in items
                     if isinstance(it, dict) and isinstance(it.get("size"), int) and not isinstance(it["size"], bool))
        out[catdir] = (len(items), nbytes)
    return out


#: The suffix the old reassembly gave a decrypted volume it wrote INTO the backup folder (before R686).
LEFTOVER_PLAIN_SUFFIX = ".plain"


#: The only volume names the oo-volumes-1 writer ever made (``vol-00001.ooenc`` ...), mirrored from src.backup.volumes so this
#: module stays crypto-free. A leftover is only ever ``<one of these>.plain``.
_V1_VOLUME_NAME = re.compile(r"\Avol-[0-9]{5,}\.ooenc\Z")


def looks_like_leftover(name: str) -> bool:
    """Whether ``name`` has the shape of a leftover copy (``vol-NNNNN.ooenc.plain``), without looking at any folder."""
    return name.endswith(LEFTOVER_PLAIN_SUFFIX) and bool(_V1_VOLUME_NAME.match(name[: -len(LEFTOVER_PLAIN_SUFFIX)]))
_V1_KIND = "oo-volumes-1"


def _leftovers_from(manifest_text: str, entries: dict[str, bool]) -> list[str]:
    """The leftover copies one folder holds, from its manifest's text and its own listing (R686, R692).

    ``entries`` maps each name the folder lists to whether it is a regular file that is not a link. Pure: no path is
    built or opened here, so a name in a crafted manifest can only ever be compared with what the folder already
    lists. A name is offered only when the manifest is an oo-volumes-1 manifest (the only format that ever wrote such
    a copy), lists the volume under a name that writer gives (``vol-NNNNN.ooenc``, so never a path, a drive letter, a
    stream name, a trailing newline or a file of the user's), the copy is not itself a listed volume in any letter
    case (a case-insensitive drive treats ``VOL-00001.OOENC.PLAIN`` and ``vol-00001.ooenc.plain`` as one file), and the
    folder lists it as a regular file."""
    import json

    try:
        m = json.loads(manifest_text)
    except ValueError:
        return []
    if not isinstance(m, dict) or m.get("kind") != _V1_KIND:
        return []
    vols = m.get("volumes")
    names = [str(v.get("name") or "") for v in vols if isinstance(v, dict)] if isinstance(vols, list) else []
    listed = {n.casefold() for n in names}
    out: set[str] = set()
    for n in names:
        cand = n + LEFTOVER_PLAIN_SUFFIX
        if _V1_VOLUME_NAME.match(n) and cand.casefold() not in listed and entries.get(cand) is True:
            out.add(cand)
    return sorted(out)


def can_scan_by_handle() -> bool:
    """Whether this platform reads a folder and the files in it through one no-follow folder handle (POSIX)."""
    return (
        hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW")
        and os.open in os.supports_dir_fd
        and os.scandir in os.supports_fd
    )


def leftovers_in_handle(dir_fd: int) -> list[str]:
    """``leftover_plaintext`` for a folder already opened as a no-follow handle: the manifest and the listing are both
    read through it, so they describe the very folder a removal through the same handle acts on. Never raises."""
    try:
        fd = os.open(_VOL_MANIFEST, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=dir_fd)
        with os.fdopen(fd, "r", encoding="utf-8") as fh:
            text = fh.read()
        with os.scandir(dir_fd) as it:
            entries = {e.name: e.is_file(follow_symlinks=False) for e in it}
        return _leftovers_from(text, entries)
    except Exception:  # noqa: BLE001 - a scan must not fail on an unreadable folder
        return []


def open_folder_handle(d: str | os.PathLike[str]) -> int:
    """Open a backup folder as a no-follow directory handle. Resolved first: a folder reached through the operator's own
    shortcut is still that folder; the handle then pins it, so a swap after this point cannot redirect what is read
    or removed through it. Raises ``OSError``; the caller closes the handle."""
    return os.open(Path(d).resolve(), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def leftover_plaintext(d: str | os.PathLike[str]) -> list[str]:
    """Decrypted volume copies an interrupted restore left in this backup folder (R686), by file name.

    Before R686 the oo-volumes-1 reassembly decrypted each volume to ``<volume>.plain`` beside it and removed it
    after; a crash or a kill in between left that PLAINTEXT on the backup drive. What is offered is decided by
    ``_leftovers_from`` from the folder's own manifest and its own listing; a link is never offered (R692). Read-only
    and crypto-free (it reads the manifest's names, nothing else); never raises."""
    try:
        if can_scan_by_handle():
            fd = open_folder_handle(d)
            try:
                return leftovers_in_handle(fd)
            finally:
                os.close(fd)
        folder = Path(d)  # Windows: no folder handles, so one manifest read and one listing of the folder
        text = (folder / _VOL_MANIFEST).read_text(encoding="utf-8")
        with os.scandir(folder) as it:
            entries = {e.name: e.is_file(follow_symlinks=False) and not e.is_symlink() for e in it}
        return _leftovers_from(text, entries)
    except Exception:  # noqa: BLE001 - a scan must not fail on an unreadable folder
        return []


def _volume_count(d: Path) -> int:
    """Number of encrypted volume files beside a ``volumes.json`` (cheap glob)."""
    try:
        return sum(1 for p in d.glob("*.ooenc*") if p.is_file())
    except OSError:
        return 0
