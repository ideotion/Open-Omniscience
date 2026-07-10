"""
Large-data "Copy to a folder/drive" backup (brief §2.A; maintainer 2026-06-21).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The signed oo-backup-2 artifact is in-memory + 2 GiB-capped + browser-delivered, so it
PHYSICALLY cannot carry the big public re-downloadable blobs: Wikipedia dumps (enwiki
~20 GB), OSM maps (planet ~72 GB) and the Ollama model store. The maintainer chose a
SERVER-SIDE "copy to a folder/drive": the app STREAMS those files (never the browser),
file-by-file, into a destination DIRECTORY the user picks (e.g. an external drive
mounted on the machine), with a manifest + dedup so a second run re-copies nothing
unchanged, and restores them BACK ADDITIVELY.

Design decisions (binding):
  * These blobs are PUBLIC + re-downloadable ⇒ copied AS-IS, NOT whole-file encrypted —
    that is what makes 100 GB feasible. The encrypted CORPUS backup (oo-backup-2) is
    unchanged and stays the private-data path.
  * DEDUP: models live in Ollama's content-addressed store (``blobs/sha256-<hex>``), so a
    blob's NAME *is* its sha256 — presence ⇒ identical, skip is inherent + safe. Wiki
    dumps + OSM extracts are immutable (date/region-named), so name+size is the honest,
    practical dedup (re-hashing tens of GB every run would defeat the point).
  * NEVER overwrite a DIFFERING local file on restore (skip-if-present), so a restore can
    never clobber a dump/blob the user already has.
  * SKIP non-``done`` downloads (a partial file must never ride into a backup) — the
    caller passes only completed files (read from the download managers' own state).
  * Copies are ATOMIC (temp + rename), so a paused mid-file copy never leaves a corrupt
    destination file; a stale ``.oopart`` temp is cleaned on the next run.

Pure filesystem (no network); the caller decides WHEN + drives pause via ``should_stop``
and progress via ``progress_cb``. The pausable task-manager job + endpoints wrap this.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

MANIFEST_NAME = "oo-folder-backup.json"
BACKUP_SCHEMA = "oo-folder-backup-1"
_CATEGORIES = ("wiki_dumps", "osm_regions", "models")
_COPY_BUF = 4 * 1024 * 1024  # 4 MiB streaming buffer
_PART_SUFFIX = ".oopart"  # in-progress temp; cleaned + never backed up


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #
@dataclass
class BackupItem:
    """One file to copy: a category root + a relative path under it + the source file."""

    category: str  # wiki_dumps | osm_regions | models
    rel: str  # POSIX path under <dest>/<category>/
    src: Path
    size: int

    def to_dict(self) -> dict:
        return {"category": self.category, "rel": self.rel, "size": self.size}


def human_bytes(n: int) -> str:
    f = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024 or unit == "TB":
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def free_bytes(path: Path) -> int:
    """Free bytes on the filesystem holding ``path`` (or its nearest existing parent)."""
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return 0


def validate_dest(dest: str | os.PathLike) -> Path:
    """Resolve + validate a destination directory: it must be an existing, writable
    directory (or a creatable one). Raises ValueError with an actionable message."""
    if not str(dest).strip():
        raise ValueError("Choose a destination folder (e.g. an external drive's mount path).")
    p = Path(dest).expanduser()
    try:
        p = p.resolve()
    except OSError:
        pass
    if p.exists():
        if not p.is_dir():
            raise ValueError(f"{p} exists but is not a folder.")
        if not os.access(p, os.W_OK):
            raise ValueError(f"{p} is not writable. Pick a folder you can write to.")
        return p
    parent = p.parent
    if not parent.exists() or not os.access(parent, os.W_OK):
        raise ValueError(f"Cannot create {p} — its parent folder is missing or not writable.")
    return p


# --------------------------------------------------------------------------- #
# Collecting what to back up
# --------------------------------------------------------------------------- #
def collect_dir_items(root: Path, category: str, done_files: Iterable[Path] | None) -> list[BackupItem]:
    """Items for a category directory (wiki_dumps / osm_regions).

    ``done_files`` is the set of COMPLETED files (the caller reads the download
    managers' state — a download writes resumably into its dest, so there is no
    on-disk partial marker; only the manager knows what is finished). When
    ``done_files`` is None every regular file under ``root`` is taken (used in
    tests / when no manager state is available); a ``*.oopart`` temp is never
    included."""
    if not root.is_dir():
        return []
    done = {Path(f).resolve() for f in done_files} if done_files is not None else None
    out: list[BackupItem] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file() or p.name.endswith(_PART_SUFFIX):
            continue
        if done is not None and p.resolve() not in done:
            continue
        out.append(BackupItem(category, p.relative_to(root).as_posix(), p, p.stat().st_size))
    return out


def _done_download_files(get_mgr: Callable[[], object]) -> list[Path]:
    """Completed (status='done') file paths from a download manager. A download writes
    resumably into its dest, so ONLY the manager knows what is finished — never a
    filename heuristic. Best-effort: a manager hiccup yields no files, never raises."""
    try:
        mgr = get_mgr()
        return [
            Path(e["dest"])
            for e in mgr.list()  # type: ignore[attr-defined]
            if e.get("status") == "done" and e.get("dest")
        ]
    except Exception:
        return []


def collect_items(
    *, include_wiki: bool = True, include_osm: bool = True, include_models: bool = True
) -> list[BackupItem]:
    """The completed wiki dumps + OSM extracts + Ollama models eligible for a folder
    backup. Wiki/OSM come from their download managers' DONE state (partials skipped)."""
    from src.paths import data_dir

    items: list[BackupItem] = []
    if include_wiki:
        from src.wiki.dumps import get_manager as _wiki_mgr

        items += collect_dir_items(
            data_dir() / "wiki_dumps", "wiki_dumps", _done_download_files(_wiki_mgr)
        )
    if include_osm:
        from src.geo.osm_downloads import get_manager as _osm_mgr

        items += collect_dir_items(
            data_dir() / "osm_regions", "osm_regions", _done_download_files(_osm_mgr)
        )
    if include_models:
        items += collect_model_items()
    return items


def needed_bytes(dest_root: str | os.PathLike, items: list[BackupItem]) -> int:
    """Bytes that WOULD be copied (items not already present at the same size) — the
    free-disk preflight figure. Cheap (a stat per item, no hashing)."""
    root = Path(dest_root)
    total = 0
    for it in items:
        dst = root / it.category / it.rel
        try:
            if dst.exists() and dst.stat().st_size == it.size:
                continue
        except OSError:
            pass
        total += it.size
    return total


def collect_model_items(store: Path | None = None) -> list[BackupItem]:
    """Items for the Ollama model store: every model's manifest + its referenced blobs,
    DEDUPED by blob filename (= by sha256). Reuses the models-backup enumerator."""
    from src.backup.ollama_models import default_store, list_models

    store = store or default_store()
    if not store.is_dir():
        return []
    items: dict[str, BackupItem] = {}
    for m in list_models(store):
        mf = store / "manifests" / Path(m.manifest_rel)
        if mf.is_file():
            rel = f"manifests/{m.manifest_rel}"
            items[rel] = BackupItem("models", rel, mf, mf.stat().st_size)
        for fn in m.blobs:  # content-addressed: dedup by filename
            bp = store / "blobs" / fn
            if bp.is_file():
                rel = f"blobs/{fn}"
                items[rel] = BackupItem("models", rel, bp, bp.stat().st_size)
    return list(items.values())


# --------------------------------------------------------------------------- #
# Copy + restore (atomic, idempotent, skip-if-present)
# --------------------------------------------------------------------------- #
def _atomic_copy(src: Path, dst: Path, *, should_stop: Callable[[], bool] | None = None) -> bool:
    """Stream ``src`` to ``dst`` via a temp file + rename (so a paused copy never leaves
    a corrupt destination). Returns True if it completed, False if ``should_stop`` fired
    mid-copy (the temp is removed). Never partially overwrites an existing ``dst``."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + _PART_SUFFIX)
    try:
        with open(src, "rb") as r, open(tmp, "wb") as w:
            while True:
                if should_stop is not None and should_stop():
                    w.close()
                    tmp.unlink(missing_ok=True)
                    return False
                chunk = r.read(_COPY_BUF)
                if not chunk:
                    break
                w.write(chunk)
            w.flush()
            os.fsync(w.fileno())
        os.replace(tmp, dst)  # atomic on the same filesystem
        return True
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_folder_backup(
    dest_root: str | os.PathLike,
    items: list[BackupItem],
    *,
    progress_cb: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Copy ``items`` into ``dest_root/<category>/<rel>`` with dedup + a manifest.

    Dedup: an existing destination file of the SAME SIZE is skipped (models are
    content-addressed so same-name ⇒ identical; dumps/maps are immutable). Atomic
    per-file. ``progress_cb`` gets a live tally after each file; ``should_stop``
    pauses cleanly between (and within) files — a paused run leaves a partial backup
    that the NEXT run resumes (already-copied files are skipped). Returns a summary."""
    root = Path(dest_root)
    root.mkdir(parents=True, exist_ok=True)
    total_bytes = sum(it.size for it in items)
    copied = skipped = copied_bytes = 0
    stopped = False
    for it in items:
        dst = root / it.category / it.rel
        if dst.exists() and dst.stat().st_size == it.size:
            skipped += 1
        else:
            if not _atomic_copy(it.src, dst, should_stop=should_stop):
                stopped = True
                break
            copied += 1
            copied_bytes += it.size
        if progress_cb is not None:
            progress_cb(
                {
                    "files_total": len(items),
                    "files_done": copied + skipped,
                    "bytes_total": total_bytes,
                    "bytes_copied": copied_bytes,
                    "copied": copied,
                    "skipped": skipped,
                }
            )
    by_cat: dict[str, list[dict]] = {c: [] for c in _CATEGORIES}
    for it in items:
        by_cat.setdefault(it.category, []).append(it.to_dict())
    manifest = {
        "schema": BACKUP_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "categories": {c: by_cat.get(c, []) for c in _CATEGORIES},
        "total_bytes": total_bytes,
        "files": len(items),
        "note": (
            "Public, re-downloadable blobs copied as-is (NOT encrypted) — the private "
            "corpus stays in the encrypted oo-backup-2 backup. Restore is additive."
        ),
    }
    if not stopped:  # only finalise the manifest on a complete pass
        (root / MANIFEST_NAME).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return {
        "dest": str(root),
        "files": len(items),
        "copied": copied,
        "skipped": skipped,
        "bytes_total": total_bytes,
        "bytes_copied": copied_bytes,
        "stopped": stopped,
        "complete": not stopped,
    }


def restore_folder_backup(
    src_root: str | os.PathLike,
    *,
    categories: Iterable[str] | None = None,
    targets: dict[str, Path] | None = None,
    progress_cb: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Copy a folder backup BACK into the live locations, ADDITIVELY.

    skip-if-present: a destination file that already EXISTS is never overwritten (so a
    differing local dump/blob is preserved). ``targets`` maps a category to its live
    directory (defaults: data_dir/wiki_dumps, data_dir/osm_regions, the Ollama store).
    Only ``categories`` (default: all present) are restored. Atomic per-file."""
    src = Path(src_root)
    cats = set(categories) if categories is not None else set(_CATEGORIES)
    tgt = dict(targets or {})
    if "wiki_dumps" not in tgt or "osm_regions" not in tgt:
        from src.paths import data_dir

        tgt.setdefault("wiki_dumps", data_dir() / "wiki_dumps")
        tgt.setdefault("osm_regions", data_dir() / "osm_regions")
    if "models" not in tgt:
        from src.backup.ollama_models import default_store

        tgt.setdefault("models", default_store())

    restored = skipped = 0
    stopped = False
    for cat in _CATEGORIES:
        if cat not in cats:
            continue
        cat_root = src / cat
        dest_dir = tgt.get(cat)
        if not cat_root.is_dir() or dest_dir is None:
            continue
        for p in sorted(cat_root.rglob("*")):
            if not p.is_file() or p.name.endswith(_PART_SUFFIX):
                continue
            dst = dest_dir / p.relative_to(cat_root)
            if dst.exists():
                skipped += 1  # never overwrite a local file
                continue
            if not _atomic_copy(p, dst, should_stop=should_stop):
                stopped = True
                break
            restored += 1
            if progress_cb is not None:
                progress_cb({"restored": restored, "skipped": skipped})
        if stopped:
            break
    return {"src": str(src), "restored": restored, "skipped": skipped, "stopped": stopped}


# --------------------------------------------------------------------------- #
# Verify (A6): does the folder backup still match its manifest?
# --------------------------------------------------------------------------- #
VERIFY_SCHEMA = "oo-folder-verify-1"
_PROBLEM_CAP = 200
# Ollama content-addressed blob names embed their own sha256: `sha256-<64 hex>` on disk
# (`sha256:<hex>` in some manifests). That is the ONE stored integrity value in a folder
# backup, so a model blob's bytes are verified against its name.
_BLOB_SHA_RE = re.compile(r"^sha256[-:]([0-9a-fA-F]{64})$")


def _safe_member_path(root: Path, category: str, rel: str) -> Path | None:
    """Resolve ``<root>/<category>/<rel>``, refusing any path that escapes ``<root>/<category>``.

    A manifest is untrusted input (a folder backup on an external drive can be edited): every
    name->path field is traversal-guarded before we stat/hash it (the ledger's binding rule)."""
    if category not in _CATEGORIES or not rel:
        return None
    base = root / category
    candidate = base / rel
    try:
        base_r = base.resolve()
        cand_r = candidate.resolve()
    except OSError:
        return None
    if cand_r != base_r and base_r not in cand_r.parents:
        return None
    return candidate


def _blob_sha256_from_name(rel: str) -> str | None:
    """The embedded sha256 hex of a content-addressed Ollama blob, else None (a model
    manifest or an unexpected name has no stored checksum)."""
    m = _BLOB_SHA_RE.match(rel.rsplit("/", 1)[-1])
    return m.group(1).lower() if m else None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_COPY_BUF), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_folder_backup(
    src_root: str | os.PathLike,
    *,
    verify_model_checksums: bool = True,
    progress_cb: Callable[[dict], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict:
    """Verify a folder backup against its manifest — the standalone integrity check the
    volumes backup already has (``/volumes/verify``) but the folder backup lacked.

    HONEST BY DESIGN, matching what a folder backup actually stores:
      * EVERY manifest-listed file must be PRESENT with the exact SIZE recorded.
      * The content-addressed Ollama model blobs (``blobs/sha256-<hex>``) are ALSO
        content-verified: their bytes are streamed-hashed and compared to the sha256 in
        their name (bounded RAM). This is the only stored checksum in a folder backup.
      * Wikipedia dumps + OSM extracts carry NO stored checksum (immutable public
        re-downloads; re-hashing tens of GB every run defeats the point), so they are
        SIZE-verified only — stated per file (``size_only``) and in the caveat, never
        dressed up as a content check.

    ``should_stop`` cancels between files (a stopped run reports ``ok=False`` — an
    incomplete verify can never claim success); ``progress_cb`` gets a live tally.
    Counts only, no score. Never raises — a broken manifest is an honest verdict."""
    root = Path(src_root)
    out: dict = {
        "schema": VERIFY_SCHEMA,
        "dest": str(root),
        "manifest_found": False,
        "ok": False,
    }
    try:
        manifest = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        out["reason"] = (
            "no finalized manifest at this path — an interrupted/incomplete folder backup "
            "never writes one, so there is nothing to verify against."
        )
        return out
    out["manifest_found"] = True
    out["backup_created_at"] = manifest.get("created_at") if isinstance(manifest, dict) else None

    # The manifest is UNTRUSTED external-drive input: a damaged/foreign structure must yield an
    # honest ok=False verdict, NEVER a crash (skeptic finding) and NEVER a false ok=True (a
    # non-list category or a non-dict entry silently dropped would leave files_total=0 = a
    # fake "all clear"). So malformed structure is COUNTED, not ignored.
    cats = manifest.get("categories") if isinstance(manifest, dict) else None
    if not isinstance(cats, dict):
        out["reason"] = (
            "the manifest has no valid 'categories' object — it is not a folder-backup "
            "manifest, or it is damaged; nothing could be verified."
        )
        return out
    entries: list[tuple[str, dict]] = []
    malformed = 0
    for c, lst in cats.items():
        if not isinstance(lst, list):
            malformed += 1  # a category whose value is not a file list = a damaged manifest
            continue
        for e in lst:
            if isinstance(e, dict):
                entries.append((str(c), e))
            else:
                malformed += 1
    total = len(entries)
    summary = {
        "ok": 0,
        "size_only": 0,
        "missing": 0,
        "size_mismatch": 0,
        "checksum_mismatch": 0,
        "traversal_refused": 0,
    }
    problems: list[dict] = []
    checked = checksummed = 0
    stopped = False
    for category, e in entries:
        if should_stop is not None and should_stop():
            stopped = True
            break
        rel = str(e.get("rel", ""))
        try:
            size = int(e.get("size", -1))
        except (TypeError, ValueError):
            size = -1
        path = _safe_member_path(root, category, rel)
        status: str
        detail: dict = {}
        if path is None:
            status = "traversal_refused"
        elif not path.is_file():
            status = "missing"
        elif (actual := path.stat().st_size) != size:
            status = "size_mismatch"
            detail = {"expected_size": size, "actual_size": actual}
        else:
            blob_hex = _blob_sha256_from_name(rel) if category == "models" else None
            if blob_hex is not None and verify_model_checksums:
                checksummed += 1
                status = "ok" if _sha256_file(path) == blob_hex else "checksum_mismatch"
            else:
                status = "size_only"  # present + right size; no stored checksum for this file
        summary[status] += 1
        checked += 1
        if status not in ("ok", "size_only") and len(problems) < _PROBLEM_CAP:
            problems.append({"category": category, "rel": rel, "status": status, **detail})
        if progress_cb is not None:
            progress_cb({"files_total": total, "files_done": checked, "checksummed": checksummed})

    summary["malformed_entries"] = malformed
    failures = (
        summary["missing"]
        + summary["size_mismatch"]
        + summary["checksum_mismatch"]
        + summary["traversal_refused"]
        + malformed  # a structurally-damaged manifest is a failure, never a silent "all clear"
    )
    out.update(
        {
            "ok": (not stopped) and failures == 0,
            "stopped": stopped,
            "files_total": total,
            "files_checked": checked,
            "files_checksummed": checksummed,
            "summary": summary,
            "problems": problems,
            "problems_truncated": max(0, failures - len(problems)),
            "method": (
                "Every manifest-listed file must be present with the exact recorded size; "
                "content-addressed Ollama model blobs (blobs/sha256-<hex>) are additionally "
                "hashed and matched to the sha256 in their name. Manifest paths are "
                "traversal-guarded before any stat/hash. Counts only, no score."
            ),
            "caveat": (
                "Wikipedia dumps and OSM extracts carry no stored checksum (immutable public "
                "re-downloads), so they are size-verified only (size_only) — a size match is "
                "NOT a proof of content. Model blobs ARE content-verified."
            ),
        }
    )
    return out


# --------------------------------------------------------------------------- #
# The pausable job (one giant copy at a time, visible in the task manager)
# --------------------------------------------------------------------------- #
import threading  # noqa: E402  (kept local to the job section)


class FolderBackupManager:
    """ONE pausable folder backup/restore at a time (you don't run two giant copies at
    once). State is IN-MEMORY; the destination directory is the durable progress — a
    paused or interrupted run RESUMES by re-planning (already-copied files are skipped),
    so there is no fragile per-byte cursor to persist or corrupt. A module-level
    singleton (``get_folder_manager``) makes it visible across requests / in /api/jobs."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._state = "idle"  # idle|running|paused|done|error|cancelled
        self._mode = "backup"  # backup|restore|verify
        self._dest: str | None = None
        self._categories: list[str] = []
        self._progress: dict = {}
        self._error: str | None = None
        self._cancelled = False
        self._targets: dict[str, Path] | None = None
        self._verify: dict | None = None

    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _on_prog(self, p: dict) -> None:
        with self._lock:
            self._progress = p

    def start(
        self,
        dest: str,
        categories: list[str],
        *,
        mode: str = "backup",
        _items: list[BackupItem] | None = None,
        _targets: dict[str, Path] | None = None,
    ) -> dict:
        """Validate + preflight, then launch the worker. Raises ValueError on a bad
        destination / insufficient free space; RuntimeError if one is already running.
        ``_items``/``_targets`` are test seams (the production path collects them)."""
        with self._lock:
            if self._alive():
                raise RuntimeError("A folder backup is already running.")
            cats = [c for c in categories if c in _CATEGORIES] or list(_CATEGORIES)
            items: list[BackupItem] = []
            if mode == "backup":
                destp = validate_dest(dest)
                items = (
                    _items
                    if _items is not None
                    else collect_items(
                        include_wiki="wiki_dumps" in cats,
                        include_osm="osm_regions" in cats,
                        include_models="models" in cats,
                    )
                )
                need = needed_bytes(destp, items)
                free = free_bytes(destp)
                if need > free:
                    raise ValueError(
                        f"Not enough free space at {destp}: needs {human_bytes(need)}, "
                        f"only {human_bytes(free)} free."
                    )
            elif mode in ("restore", "verify"):
                destp = Path(dest)
                if not destp.is_dir():
                    verb = "verify" if mode == "verify" else "restore from"
                    raise ValueError(f"{destp} is not a folder to {verb}.")
            else:
                raise ValueError(f"unknown folder-backup mode {mode!r}")
            self._stop.clear()
            self._cancelled = False
            self._state = "running"
            self._mode = mode
            self._dest = str(destp)
            self._categories = cats
            self._error = None
            self._progress = {}
            self._targets = _targets
            self._verify = None
            target = {
                "backup": self._run_backup,
                "restore": self._run_restore,
                "verify": self._run_verify,
            }[mode]
            self._thread = threading.Thread(
                target=target, args=(destp, items, cats), daemon=True, name="folder-backup"
            )
            self._thread.start()
            return self.status()

    def _run_backup(self, destp: Path, items: list[BackupItem], _cats: list[str]) -> None:
        try:
            res = write_folder_backup(
                destp, items, progress_cb=self._on_prog, should_stop=self._stop.is_set
            )
            with self._lock:
                if res["stopped"]:
                    self._state = "cancelled" if self._cancelled else "paused"
                else:
                    self._state = "done"
                self._progress = {**self._progress, **res}
        except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
            with self._lock:
                self._state = "error"
                self._error = str(exc)

    def _run_restore(self, srcp: Path, _items: list[BackupItem], cats: list[str]) -> None:
        try:
            res = restore_folder_backup(
                srcp,
                categories=cats,
                targets=getattr(self, "_targets", None),
                progress_cb=self._on_prog,
                should_stop=self._stop.is_set,
            )
            with self._lock:
                if res["stopped"]:
                    self._state = "cancelled" if self._cancelled else "paused"
                else:
                    self._state = "done"
                self._progress = {**self._progress, **res}
        except Exception as exc:  # noqa: BLE001
            with self._lock:
                self._state = "error"
                self._error = str(exc)

    def _run_verify(self, srcp: Path, _items: list[BackupItem], _cats: list[str]) -> None:
        try:
            res = verify_folder_backup(
                srcp, progress_cb=self._on_prog, should_stop=self._stop.is_set
            )
            with self._lock:
                if res.get("stopped"):
                    self._state = "cancelled" if self._cancelled else "paused"
                else:
                    self._state = "done"
                self._verify = res
                self._progress = {**self._progress, "verify": res}
        except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
            with self._lock:
                self._state = "error"
                self._error = str(exc)

    def pause(self) -> None:
        self._stop.set()  # the worker stops between/within files; state -> paused

    def resume(self) -> dict:
        with self._lock:
            if self._state not in ("paused", "error", "cancelled"):
                raise RuntimeError("Nothing paused to resume.")
            dest, cats, mode = self._dest, list(self._categories), self._mode
        if dest is None:
            raise RuntimeError("No previous folder backup to resume.")
        return self.start(dest, cats, mode=mode)

    def cancel(self) -> None:
        with self._lock:
            self._cancelled = True
        self._stop.set()

    def status(self) -> dict:
        with self._lock:
            out = {
                "state": self._state,
                "mode": self._mode,
                "dest": self._dest,
                "categories": list(self._categories),
                "progress": dict(self._progress),
                "error": self._error,
                "running": self._alive(),
            }
            if self._verify is not None:
                out["verify"] = self._verify  # the last verify verdict (read-only)
            return out


_FOLDER_MANAGER: FolderBackupManager | None = None
_FOLDER_MANAGER_LOCK = threading.Lock()


def get_folder_manager() -> FolderBackupManager:
    """Process-wide singleton so the job is visible across requests + in /api/jobs."""
    global _FOLDER_MANAGER
    with _FOLDER_MANAGER_LOCK:
        if _FOLDER_MANAGER is None:
            _FOLDER_MANAGER = FolderBackupManager()
        return _FOLDER_MANAGER
