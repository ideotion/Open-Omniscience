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
_CATEGORIES = ("wiki_dumps", "osm_regions", "models", "hf_models")
_COPY_BUF = 4 * 1024 * 1024  # 4 MiB streaming buffer
_PART_SUFFIX = ".oopart"  # in-progress temp; cleaned + never backed up
#: A recorded checksum is 64 hex characters or it is not one. Manifest values are
#: untrusted external-drive input, so a malformed one is DISCARDED (unverifiable),
#: never compared against and never reported as a match.
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


# --------------------------------------------------------------------------- #
# Items
# --------------------------------------------------------------------------- #
@dataclass
class BackupItem:
    """One file to copy: a category root + a relative path under it + the source file."""

    category: str  # wiki_dumps | osm_regions | models | hf_models
    rel: str  # POSIX path under <dest>/<category>/
    src: Path
    size: int

    def to_dict(self, *, sha256: str | None = None) -> dict:
        """The manifest entry. ``sha256`` is OMITTED when unknown rather than written as
        an empty string: "not hashed" and "hashed to nothing" are different facts, and a
        reader that cannot tell them apart reports an unverifiable file as verified."""
        d = {"category": self.category, "rel": self.rel, "size": self.size}
        if sha256:
            d["sha256"] = sha256
        return d


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
    *,
    include_wiki: bool = True,
    include_osm: bool = True,
    include_models: bool = True,
    include_hf: bool = True,
) -> list[BackupItem]:
    """The completed wiki dumps + OSM extracts + local model weights eligible for a
    folder backup. Wiki/OSM come from their download managers' DONE state (partials
    skipped). Model weights come from BOTH stores — Ollama's and the Hugging Face cache
    vLLM serves from — because "my models" means the ones this machine can run, not the
    ones one backend happens to keep."""
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
    if include_hf:
        items += collect_hf_model_items()
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


#: Files huggingface_hub leaves behind mid-download or for locking. Never model data.
_HF_SKIP_SUFFIXES = (".incomplete", ".lock", _PART_SUFFIX)


def collect_hf_model_items(home: Path | None = None) -> list[BackupItem]:
    """Items for the Hugging Face weights cache — the models vLLM serves.

    THE GAP THIS CLOSES (field report 2026-08-11: "vLLM models were not saved, only
    ollama models"). The ``models`` category above enumerates the OLLAMA store and
    nothing else, so on a machine that serves with vLLM the large-data backup carried
    no weights at all — and said "Backup complete", because from its own point of view
    it had copied everything it knew about. Same shape as the 2026-08-11 lesson one
    store over: an enumerator that does not list a location the app itself writes to
    makes the app blind to its own data.

    WHY THE SNAPSHOT FILES AND NOT ``blobs/``. An HF repo keeps its bytes once, in
    ``blobs/<sha>``, and ``snapshots/<rev>/<name>`` is a SYMLINK to it. Backing up both
    would store every multi-GB weight file TWICE, because :func:`_atomic_copy` opens its
    source and therefore follows the link. Backing up ``blobs/`` alone would restore
    bytes nothing can find. So the snapshot entries are copied (resolving the link) and
    ``blobs/`` is skipped: one copy, and the restored tree is a cache of plain files —
    which is exactly the layout ``huggingface_hub`` itself produces where symlinks are
    unavailable, not one invented here.

    THAT CHOICE IS ALSO WHAT KEEPS THE RESTORE SAFE. :func:`restore_folder_backup`
    REFUSES symlinks outright — a 2026-07-25 fix for a live-reproduced arbitrary-file
    copy out of an editable backup folder — so storing links and recreating them would
    have meant reopening that hole for the convenience of a cache layout. Nothing here
    writes a link, and nothing on the way back reads one.

    HONEST LIMIT: two revisions of one repo that share a blob are stored once per
    revision. A cache normally holds one revision per model, and the alternative costs
    the symlink guard, so the duplication is accepted rather than hidden.
    """
    from src.llm.model_store import hf_home

    home = home or hf_home()
    hub = home / "hub"
    if not hub.is_dir():
        return []
    items: list[BackupItem] = []
    try:
        repos = sorted(d for d in hub.iterdir() if d.is_dir() and d.name.startswith("models--"))
    except OSError:
        return []
    for repo in repos:
        # refs/ names which revision is current -- tiny, real files, and without them a
        # restored cache has weights that nothing resolves to.
        for sub in ("refs", "snapshots"):
            root = repo / sub
            if not root.is_dir():
                continue
            for p in sorted(root.rglob("*")):
                if p.name.endswith(_HF_SKIP_SUFFIXES):
                    continue
                try:
                    if not p.is_file():  # follows the link: a dangling one is not a file
                        continue
                    size = p.stat().st_size  # the TARGET's size, which is what gets copied
                except OSError:
                    continue
                items.append(BackupItem("hf_models", f"hub/{p.relative_to(hub).as_posix()}", p, size))
    return items


# --------------------------------------------------------------------------- #
# Copy + restore (atomic, idempotent, skip-if-present)
# --------------------------------------------------------------------------- #
def _atomic_copy(
    src: Path,
    dst: Path,
    *,
    should_stop: Callable[[], bool] | None = None,
    digest: "hashlib._Hash | None" = None,
) -> bool:
    """Stream ``src`` to ``dst`` via a temp file + rename (so a paused copy never leaves
    a corrupt destination). Returns True if it completed, False if ``should_stop`` fired
    mid-copy (the temp is removed). Never partially overwrites an existing ``dst``.

    ``digest`` is updated with every byte written. Hashing HERE is what makes recorded
    checksums affordable at a hundred gigabytes: the bytes are already in the buffer, so
    the copy that has to happen anyway pays for the integrity value -- as against a
    separate pass, which would double the read and is exactly the cost this module's own
    design notes give as the reason wiki dumps and OSM extracts had no checksum at all.
    A stopped copy leaves the digest partial; the caller discards it with the temp."""
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
                if digest is not None:
                    digest.update(chunk)
            w.flush()
            os.fsync(w.fileno())
        os.replace(tmp, dst)  # atomic on the same filesystem
        return True
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _sign_folder_manifest(m: dict) -> dict:
    """Ed25519 over the manifest minus its signature — the SAME machinery, key and
    canonicalisation the volume manifest uses (``stream_backup._sign_manifest``), so a
    folder backup and a volume backup written to one destination are signed by one key
    and a reader has one thing to check."""
    from src.backup.stream_backup import _sign_manifest

    return _sign_manifest(m)


def folder_manifest_signature_state(m: dict) -> str:
    """verified | bad-signature | unsigned.

    ``unsigned`` is the honest verdict for a backup written before signing existed, not a
    failure: those manifests are real backups and refusing them would strand data. It is
    reported, never silently upgraded."""
    from src.backup.stream_backup import _manifest_signature_state

    return _manifest_signature_state(m)


def _recorded_digests(root: Path) -> dict[tuple[str, str, int], str]:
    """``(category, rel, size) -> sha256`` from the destination's existing manifest.

    Keyed on the SIZE too: the skip that reuses a checksum is itself a size match, so a
    file whose size differs from the recorded one is not the file that was hashed and its
    old digest must not travel. A missing, damaged or foreign manifest is simply an empty
    map — this is a best-effort carry-forward, never a gate."""
    try:
        m = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cats = m.get("categories") if isinstance(m, dict) else None
    if not isinstance(cats, dict):
        return {}
    out: dict[tuple[str, str, int], str] = {}
    for c, lst in cats.items():
        if not isinstance(lst, list):
            continue
        for e in lst:
            if not isinstance(e, dict):
                continue
            sha = e.get("sha256")
            rel = e.get("rel")
            try:
                size = int(e.get("size", -1))
            except (TypeError, ValueError):
                continue
            if isinstance(sha, str) and _SHA256_RE.match(sha) and isinstance(rel, str):
                out[(str(c), rel, size)] = sha.lower()
    return out


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
    # Checksums recorded by the PREVIOUS complete pass, so a refresh that skips an
    # unchanged file keeps its integrity value instead of losing it or re-reading a
    # hundred gigabytes to recover it (the same reuse discipline the volume writer's
    # pool applies to slices). Keyed on (category, rel, size): a size change means the
    # file is not the one that was hashed.
    prior = _recorded_digests(root)
    digests: dict[tuple[str, str], str] = {}
    for it in items:
        dst = root / it.category / it.rel
        if dst.exists() and dst.stat().st_size == it.size:
            skipped += 1
            if (carried := prior.get((it.category, it.rel, it.size))) is not None:
                digests[(it.category, it.rel)] = carried
        else:
            h = hashlib.sha256()
            if not _atomic_copy(it.src, dst, should_stop=should_stop, digest=h):
                stopped = True
                break
            digests[(it.category, it.rel)] = h.hexdigest()
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
        by_cat.setdefault(it.category, []).append(
            it.to_dict(sha256=digests.get((it.category, it.rel)))
        )
    unhashed = sum(
        1 for it in items if digests.get((it.category, it.rel)) is None
    )
    manifest = {
        "schema": BACKUP_SCHEMA,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "categories": {c: by_cat.get(c, []) for c in _CATEGORIES},
        "total_bytes": total_bytes,
        "files": len(items),
        # A gap is published as a gap: an entry with no sha256 is one this pass skipped
        # and whose checksum the previous manifest did not carry (a backup written before
        # checksums existed). Verify reports those as unverifiable rather than counting
        # them as content-checked.
        "files_without_checksum": unhashed,
        "note": (
            "Public, re-downloadable blobs copied as-is (NOT encrypted) — the private "
            "corpus stays in the encrypted oo-backup-2 backup. Restore is additive. "
            "Each entry carries the sha256 of the bytes written, so verify and restore "
            "can check content, not only size."
        ),
    }
    if not stopped:  # only finalise the manifest on a complete pass
        # SIGNED, like the volume manifest and for the same reason: this file lives on an
        # external drive and is editable there, so the checksums it carries are worth
        # exactly as much as the evidence that they are the ones we wrote. The signature
        # proves internal consistency with the EMBEDDED key -- anyone can self-sign, so it
        # is tamper-EVIDENCE against a drive, never trust in an origin -- which is why
        # every name->path field is still traversal-guarded before anything is touched.
        manifest["signature"] = _sign_folder_manifest(manifest)
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
    Only ``categories`` (default: all present) are restored. Atomic per-file.

    CONTENT-VERIFIED WHILE COPYING (2026-09-07). Each file is hashed as it streams and
    the result matched against the sha256 the backup recorded when it WROTE those bytes;
    a mismatch is discarded with its temp file and reported in ``corrupt``, so a member
    that rotted on the external drive is never handed to the live data directory. The
    bytes are read either way, so the check costs nothing. Where no checksum was recorded
    (a backup written before they were), the file restores as before and is counted in
    ``restored_unverified`` -- an honest gap, not a silent pass.

    SYMLINKS ARE ALWAYS REFUSED, NEVER FOLLOWED (fixed 2026-07-25, transversal audit
    09): the backup source is untrusted input — the module's own top docstring states
    "a folder backup on an external drive... can be edited" — and ``write_folder_
    backup``/``_atomic_copy`` above NEVER create a symlink (every entry is a plain
    file written via a temp-file-then-rename). So a symlink discovered here is never
    something WE wrote; it can only be a hostile plant (or filesystem oddity), and
    ``Path.is_file()``/``open()`` both silently FOLLOW a symlink to whatever it points
    at — previously letting an attacker-controlled symlink inside e.g. ``wiki_dumps/``
    have an arbitrary locally-readable file's CONTENT copied into the live data
    directory under an innocuous filename (live-reproduced). ``Path.is_symlink()``
    uses ``lstat`` (never follows), so checking it first costs nothing and touches
    the symlink target not at all — mirroring the sibling ``verify_folder_backup``'s
    own ``_safe_member_path`` guard for the identical untrusted-input threat model."""
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
    if "hf_models" not in tgt:
        # The Hugging Face cache vLLM is spawned pointed at. A SEPARATE category rather
        # than a second root under "models": the existing category's on-disk layout IS
        # the Ollama store root, and folding a second store under it would send an
        # older backup's manifests/ and blobs/ somewhere new on the way back.
        from src.llm.model_store import hf_home

        tgt.setdefault("hf_models", hf_home())

    # The checksums this backup recorded when it wrote the bytes. Empty for a backup
    # written before they existed, and for one whose manifest is missing or damaged --
    # in which case every file restores as before and is COUNTED as unverifiable, never
    # silently called sound.
    recorded = _recorded_digests(src)

    restored = skipped = refused_symlinks = 0
    corrupt: list[dict] = []
    unverifiable = 0
    stopped = False
    for cat in _CATEGORIES:
        if cat not in cats:
            continue
        cat_root = src / cat
        dest_dir = tgt.get(cat)
        if not cat_root.is_dir() or dest_dir is None:
            continue
        for p in sorted(cat_root.rglob("*")):
            if p.name.endswith(_PART_SUFFIX):
                continue
            if p.is_symlink():
                refused_symlinks += 1  # never follow -- see the docstring above
                continue
            if not p.is_file():
                continue
            rel = p.relative_to(cat_root)
            dst = dest_dir / rel
            if dst.exists():
                skipped += 1  # never overwrite a local file
                continue
            want = recorded.get((cat, rel.as_posix(), p.stat().st_size))
            # VERIFY WHILE COPYING, and only commit the copy if it matches. The bytes
            # are read either way, so the check is free; the temp file is what makes
            # "refuse" possible at all -- a corrupt member is discarded before it can
            # land in the live data directory. Without this a dump that rotted on the
            # external drive was restored silently, and the app then read it as its own.
            h = hashlib.sha256() if want is not None else None
            if not _atomic_copy(p, dst, should_stop=should_stop, digest=h):
                stopped = True
                break
            if h is not None and h.hexdigest() != want:
                dst.unlink(missing_ok=True)
                if len(corrupt) < _PROBLEM_CAP:
                    corrupt.append({"category": cat, "rel": rel.as_posix()})
                continue
            if want is None:
                unverifiable += 1
            restored += 1
            if progress_cb is not None:
                progress_cb({"restored": restored, "skipped": skipped})
        if stopped:
            break
    return {
        "src": str(src),
        "restored": restored,
        "skipped": skipped,
        "refused_symlinks": refused_symlinks,
        # A file whose bytes did not match the checksum this backup recorded for it. NOT
        # restored: the copy is removed again, so the live data directory never receives
        # it. Named, so the operator can re-download exactly those.
        "corrupt_refused": len(corrupt),
        "corrupt": corrupt,
        # Restored, but with no recorded checksum to check against (a pre-2026-09-07
        # backup, or a manifest that could not be read). A gap, published as a gap:
        # these were NOT content-verified and must not be counted as if they were.
        "restored_unverified": unverifiable,
        "stopped": stopped,
    }


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
      * EVERY file a 2026-09-07-or-later backup wrote carries a recorded ``sha256``
        (hashed during the copy, so it cost no extra read), and is content-verified
        against it. Wikipedia dumps and OSM extracts were SIZE-ONLY until then, which
        is why an older backup still reports ``size_only`` for them — stated per file
        and in the caveat, never dressed up as a content check.
      * The manifest's own Ed25519 signature is reported (``signature_state``). A
        ``bad-signature`` fails the verdict; ``unsigned`` does not, because a backup
        written before signing existed is a real backup.

    WHAT IT COSTS, stated rather than left to be discovered: a verify of a 2026-09-07-or-
    later backup READS EVERY BYTE it carries, because that is what a content check is. It
    used to read only the model blobs and `stat` the rest, so on a large folder backup this
    is now a full pass over the drive rather than a directory walk — minutes to hours at
    disk speed, bounded in RAM (streamed) and cancellable. That is the price of the check
    being real; there is no cheaper way to learn that a dump on an external drive still
    holds the bytes it was written with.

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
    # Reported, never enforced: an `unsigned` manifest is a backup written before signing
    # existed, and refusing it would strand real data. `bad-signature` is a finding the
    # operator must read -- it means the manifest's own contents (including every recorded
    # checksum) are not the ones this key wrote -- so it fails the verdict below.
    sig_state = (
        folder_manifest_signature_state(manifest) if isinstance(manifest, dict) else "unsigned"
    )
    out["signature_state"] = sig_state

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
            # Two independent stored checksums, and they are not the same evidence.
            # `sha256` is what THIS backup recorded when it wrote the bytes (present
            # since 2026-09-07, and signed with the manifest). The Ollama blob's own
            # name embeds its sha256, which is the publisher's value and is carried by
            # a backup of any age. Where both exist they must BOTH match: a recorded
            # digest that disagrees with the name is exactly the case where trusting
            # either one alone reports a corrupted blob as sound.
            recorded = e.get("sha256")
            recorded = recorded.lower() if (
                isinstance(recorded, str) and _SHA256_RE.match(recorded)
            ) else None
            blob_hex = _blob_sha256_from_name(rel) if category == "models" else None
            want = [h for h in (recorded, blob_hex) if h is not None]
            if want and (blob_hex is None or verify_model_checksums):
                checksummed += 1
                actual_hex = _sha256_file(path)
                status = "ok" if all(actual_hex == h for h in want) else "checksum_mismatch"
            else:
                status = "size_only"  # present + right size; no usable stored checksum
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
        # A manifest that does not verify against its own embedded key is not a manifest
        # to verify files against. `unsigned` is NOT counted: see above.
        + (1 if sig_state == "bad-signature" else 0)
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
                "any file carrying a recorded sha256 is streamed-hashed and matched against "
                "it, and content-addressed Ollama model blobs (blobs/sha256-<hex>) are also "
                "matched against the sha256 in their name (both, where both exist). The "
                "manifest's own Ed25519 signature is reported. Manifest paths are "
                "traversal-guarded before any stat/hash. Counts only, no score."
            ),
            "caveat": (
                "size_only means the manifest recorded no usable checksum for that file — a "
                "backup written before checksums were recorded, or an entry skipped by a "
                "refresh whose earlier manifest had none. A size match is NOT a proof of "
                "content. The signature proves the manifest is consistent with the key "
                "embedded in it; anyone can self-sign, so it is tamper-evidence against an "
                "edited drive, never proof of who wrote the backup."
            ),
        }
    )
    return out


# --------------------------------------------------------------------------- #
# The pausable job (one giant copy at a time, visible in the task manager)
# --------------------------------------------------------------------------- #
import threading  # noqa: E402  (kept local to the job section)

from src.backup import runlog  # noqa: E402  (same, beside the manager it serves)


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
                        include_hf="hf_models" in cats,
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
        # The large-data (wiki dumps / OSM regions / model blobs) half of an
        # export. Journalled on the SAME terms as the encrypted one: it copies
        # tens of GB across a drive, so "it seems to be stuck" is exactly as
        # askable here, and until now it left nothing behind either.
        with runlog.run("folder-export", label=destp.name, dest=str(destp), items=len(items)):
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
                runlog.end(
                    ("cancelled" if self._cancelled else "paused") if res["stopped"] else "ok",
                    copied=res.get("copied"), skipped=res.get("skipped"),
                    bytes=res.get("bytes_copied"),
                )
            except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
                with self._lock:
                    self._state = "error"
                    self._error = str(exc)
                raise

    def _run_restore(self, srcp: Path, _items: list[BackupItem], cats: list[str]) -> None:
        with runlog.run("folder-import", label=srcp.name, dest=str(srcp), categories=cats):
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
                runlog.end(
                    ("cancelled" if self._cancelled else "paused") if res["stopped"] else "ok",
                    # A restore RESTORES; it does not "copy". The field was `copied`
                    # here, which restore_folder_backup has never returned, so every
                    # restore journal carried `copied: null` -- a field that reads as
                    # "nothing was copied" when the truth is that the operation has no
                    # such number. The two refusal counts ride the SAME line as the
                    # successes for the same reason: a journal that records only what
                    # arrived cannot say what was turned away.
                    restored=res.get("restored"), skipped=res.get("skipped"),
                    refused_symlinks=res.get("refused_symlinks"),
                    corrupt_refused=res.get("corrupt_refused"),
                    restored_unverified=res.get("restored_unverified"),
                )
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._state = "error"
                    self._error = str(exc)
                raise

    def _run_verify(self, srcp: Path, _items: list[BackupItem], _cats: list[str]) -> None:
        # A verify is a full read of the whole set -- 1521 s of one field import
        # was verification alone -- so it belongs in the journal for the same
        # reason the copy does.
        with runlog.run("verify", label=srcp.name, dest=str(srcp)):
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
                runlog.end(
                    ("cancelled" if self._cancelled else "paused")
                    if res.get("stopped") else "ok",
                    checked=res.get("checked"), mismatches=res.get("mismatches"),
                )
            except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
                with self._lock:
                    self._state = "error"
                    self._error = str(exc)
                raise

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
