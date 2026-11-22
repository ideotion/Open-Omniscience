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

import errno
import functools
import hashlib
import json
import os
import re
import shutil
import stat
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from src.backup.hf_layout import HF_LAYOUT, hf_live_rel, hf_member_allowed
from src.backup.links import is_link, is_link_stat, link_on_the_way, stays_inside
from src.backup.manifest_file import read_manifest_json
from src.backup.regular_file import NotARegularFile, create_new, open_regular
from src.monitoring.secret_scrub import log_failure, record_text
from src.shared_text import said

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
    from src.llm.model_store import hf_hub_cache

    # R784: the hub cache folder ITSELF (HF_HUB_CACHE when set, whatever it is named). The old
    # ``hf_home() / "hub"`` named the PARENT of HF_HUB_CACHE plus "hub": a cache folder named
    # anything else was never backed up. ``home`` (tests, callers with their own home) keeps HF's
    # own layout below it. The backup still writes it as ``hub/...``: that folder name is the
    # cache folder, recorded in the manifest as ``hf_layout``.
    hub = home / "hub" if home is not None else hf_hub_cache()
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
def _write_manifest_atomically(path: Path, text: str) -> None:
    """Write the folder backup's manifest through a temp file, fsync and rename (audit recheck P5).

    Written in place, a crash mid-write left the folder backup with no readable manifest, and
    the previous one already gone; now a reader sees the old manifest or the new one, whole."""
    import secrets

    tmp = path.with_name(f"{path.name}.{secrets.token_hex(4)}{_PART_SUFFIX}")
    try:
        with create_new(tmp) as fh:  # never through a link at the temporary name (row 313)
            fh.write(text.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    try:  # the rename itself is durable only once its directory is (POSIX; not available on Windows)
        fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_copy(
    src: Path,
    dst: Path,
    *,
    should_stop: Callable[[], bool] | None = None,
    digest: "hashlib._Hash | None" = None,
    nofollow_src: bool = False,
    expect: os.stat_result | None = None,
    opener: Callable[[], int] | None = None,
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
    # R779: a leftover ``.oopart`` is removed and the temp file is CREATED, never opened if it is
    # there. ``open(tmp, "wb")`` follows a link, so a ``.oopart`` planted as a link to another file
    # had the copy written through it. ``unlink`` removes a link itself, never what it points at.
    tmp.unlink(missing_ok=True)
    binary = getattr(os, "O_BINARY", 0)
    try:
        # A restore reads from an untrusted folder: where the system can, the source is opened without
        # following a link, so a member swapped for one after it was checked is refused, not read.
        try:
            # O_NONBLOCK too: a member swapped for a named pipe would otherwise block this open for
            # ever, before the fstat below could refuse it. It changes nothing for a regular file.
            guard = (getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)) if nofollow_src else 0
            # R783: where the system can, the caller hands an opener that walks to the file by folder
            # handle (``_open_member_fd``); it raises the refusals itself.
            src_fd = opener() if opener is not None else os.open(src, os.O_RDONLY | binary | guard)
        except (SourceChanged, SourceUnreadable):
            raise
        except OSError as exc:
            if nofollow_src and _now_a_link(src):  # the name is now a link: refused, never read
                raise SourceChanged("the file became a link after it was checked") from None
            if not nofollow_src or not _process_can_open():
                raise  # a backup's own copy, or the whole process out of files or memory: stop, as before
            # R778: the SOURCE could not be opened. Raised as one of the fixed classes below, so the
            # restore counts it as not read and goes on; the system's own words are never kept.
            raise _unread_of(type(exc)) from None
        with os.fdopen(src_fd, "rb") as r:
            if expect is not None:
                # The file opened must be the one that was checked: a regular file with the same
                # device and inode. This also catches a FOLDER on the way swapped for a link, which
                # O_NOFOLLOW alone does not (it only guards the last name).
                try:
                    got = os.fstat(r.fileno())
                except OSError as exc:
                    if not _process_can_open():
                        raise
                    raise _unread_of(type(exc)) from None
                if not stat.S_ISREG(got.st_mode) or not (_same_file(got, expect) or _same_file_again(got, expect, Path(src))):
                    raise SourceChanged("the file changed after it was checked")
                if nofollow_src and hasattr(os, "set_blocking"):
                    # Opened with O_NONBLOCK so a pipe could not hang the open; a regular file is read
                    # blocking, so a file system that honours the flag can never end a read early (an
                    # empty read is taken as the end of the file).
                    try:
                        os.set_blocking(r.fileno(), True)
                    except OSError:
                        pass
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | binary, 0o666)
            with os.fdopen(fd, "wb") as w:
                while True:
                    if should_stop is not None and should_stop():
                        w.close()
                        tmp.unlink(missing_ok=True)
                        return False
                    try:
                        chunk = r.read(_COPY_BUF)
                    except OSError as exc:
                        if not nofollow_src or not _process_can_open():
                            raise
                        # R778: a read that fails part-way (a bad sector, a drive pulled) leaves no
                        # partial file: the temp is removed below and the live name never appears.
                        raise _unread_of(type(exc)) from None
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
    m = read_manifest_json(root / MANIFEST_NAME)  # a link, a pipe, a huge or deeply nested file: none
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


def _manifest_listing(root: Path) -> dict[str, set[str]] | None:
    """``category -> {rel}`` for every file the backup's CURRENT manifest lists, or ``None`` when there
    is no manifest that can be read (R780). Unlike :func:`_recorded_digests` it keeps an entry with no
    checksum too: the question here is only "is this file listed", never "is it verified".

    The manifest is signed with a key it carries itself, so it is tamper-EVIDENCE, never proof of
    where a file came from: a file it does not list is still restored, and counted as unlisted."""
    m = read_manifest_json(root / MANIFEST_NAME)  # a link, a pipe, a huge or deeply nested file: none
    cats = m.get("categories") if isinstance(m, dict) else None
    if not isinstance(cats, dict):
        return None
    out: dict[str, set[str]] = {}
    for c, lst in cats.items():
        if isinstance(lst, list):
            out[str(c)] = {e["rel"] for e in lst if isinstance(e, dict) and isinstance(e.get("rel"), str)}
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
    root_real = os.path.realpath(root)
    # Row 313: the backup folder is a place someone else may have prepared. A category or sub folder
    # there that is a link would carry the copy (and its folder creation) to wherever the link points,
    # so EVERY item's way is checked before the first byte is copied, and a link stops the backup with
    # the folder, where it points and what to do. Checked again per item below, against a folder
    # swapped for a link while the copy runs. A link AT a file's own name is not followed either: it
    # never counts as the file already present, and the copy's rename replaces the link itself.
    for it in items:
        if (found := _linked_way(root, root_real, it)) is not None:
            raise LinkedBackupFolder(
                f"The large-data backup stopped before copying anything: the folder {found[0]} inside the "
                f"backup folder is a link to {found[1]}, and a backup never writes through a link. Replace the "
                f"link with a real folder, or choose a backup folder on that other drive."
            )
    for it in items:
        dst = root / it.category / it.rel
        if (found := _linked_way(root, root_real, it)) is not None:
            raise LinkedBackupFolder(
                f"The large-data backup stopped: the folder {found[0]} inside the backup folder became a link "
                f"to {found[1]} while it ran, and nothing was written through it. Replace the link with a real "
                f"folder, or choose a backup folder on that other drive."
            )
        if not is_link(dst) and dst.exists() and dst.stat().st_size == it.size:
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
        # R784: ``hf_models/hub/`` is the Hugging Face hub cache folder itself; a restore places it in
        # the hub cache folder of the computer it runs on. A manifest without it was written when the
        # backup read ``<parent of HF_HUB_CACHE>/hub``, which missed a cache folder named otherwise.
        "hf_layout": HF_LAYOUT,
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
        _write_manifest_atomically(root / MANIFEST_NAME, json.dumps(manifest, indent=2))
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


def live_targets(overrides: dict[str, Path] | None = None) -> dict[str, Path]:
    """The live directory each category is restored INTO.

    Hoisted out of :func:`restore_folder_backup` when the volume artifact learned to carry
    the same files (S6.2): two restore paths resolving "where do models live" separately
    is how one of them ends up writing an older backup's ``manifests/`` somewhere new.
    One owner, both callers."""
    tgt = dict(overrides or {})
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
        # R784: the hub cache folder ITSELF, as it resolves on THIS computer; a member's leading
        # ``hub/`` is that folder (``hf_live_rel``).
        from src.llm.model_store import hf_hub_cache

        tgt.setdefault("hf_models", hf_hub_cache())
    return tgt


#: R784: why the Hugging Face cache folder cannot take a restore here. Fixed codes, never the system's
#: words; the page says each one in the person's language.
HF_TARGET_UNRESOLVED = "unresolved"  # no absolute folder could be worked out, or it could not be looked at
HF_TARGET_NOT_FOLDER = "not-a-folder"  # its path, or a folder above it, is taken by something that is not a folder
HF_TARGET_NOT_WRITABLE = "not-writable"  # the folder (or the nearest one above it that exists) cannot be written


def hf_target_refusal(target: Path | str | None) -> str | None:
    """Why the hub cache folder ``target`` cannot take a restore, or ``None`` (R784).

    Looked at before anything is placed, so a cache folder this computer cannot use is said as ONE
    named reason and the category is left out -- never one write error per model file. The folder may
    not exist yet (a computer that never downloaded a model): then the nearest folder above it that
    exists must be one this process can write into. The folder may be a link the person made (a cache
    moved to another disk); that is their choice and is followed, as the other live folders are. A
    write that still fails later stops the restore with an error, as before.

    STATED LIMIT: on Windows ``os.access`` does not read folder permissions (ACLs), so a folder it calls
    writable can still refuse the first write -- which then stops the restore with that error."""
    if target is None:
        return HF_TARGET_UNRESOLVED
    # Checked exactly as given, never expanded here: the path checked must be the path written to, and
    # ``hf_hub_cache`` already expands ``~`` the way Hugging Face does.
    raw = os.fspath(target)
    if not raw or not os.path.isabs(raw):
        return HF_TARGET_UNRESOLVED  # a relative HF_HUB_CACHE would mean whatever folder a process started in
    p = Path(raw)
    probe = p
    while True:
        try:
            st = os.stat(probe)
        except FileNotFoundError:
            if os.path.islink(probe):
                return HF_TARGET_NOT_FOLDER  # a link to nothing: the write would fail, so it is said now
            if probe.parent == probe:
                return HF_TARGET_UNRESOLVED
            probe = probe.parent
            continue
        except NotADirectoryError:
            return HF_TARGET_NOT_FOLDER
        except (OSError, ValueError):
            return HF_TARGET_UNRESOLVED
        break
    if not stat.S_ISDIR(st.st_mode):
        return HF_TARGET_NOT_FOLDER
    if not os.access(probe, os.W_OK | os.X_OK):
        return HF_TARGET_NOT_WRITABLE
    return None


def hf_restore_target() -> dict:
    """The Hugging Face hub cache folder a restore would write to on THIS computer, and why it cannot
    when it cannot (R784) -- what the import checklist shows before the person chooses."""
    try:
        path: Path | None = live_targets().get("hf_models")
    except Exception:  # noqa: BLE001 - any failure to work the folder out is that, said as one reason
        path = None
    return {"path": None if path is None else os.fspath(path), "refused": hf_target_refusal(path)}


def _unsafe_placement_reason(name: str, rel: str) -> str | None:
    """Why this entry may not be placed, or None. Both fields become paths -- ``name``
    under the staging dir (an arbitrary READ), ``rel`` under a live directory (an
    arbitrary WRITE) -- so both are checked, and the answer says WHICH one was wrong."""
    for label, value in (("name", name), ("rel", rel)):
        if not value:
            return f"empty {label}"
        p = PurePosixPath(value.replace("\\", "/"))
        if (
            p.is_absolute()
            or ".." in p.parts
            or value.startswith("/")
            or "\\" in value
            or ":" in value.split("/", 1)[0]
        ):
            return f"unsafe {label}"
    return None


#: The errors that say a member's NAME cannot exist here, not that writing failed (R787 reads).
_NAME_ERRNOS = frozenset({errno.ENAMETOOLONG, errno.ENOTDIR, errno.EEXIST, errno.EISDIR})


def place_artifact_file_members(
    staging_dir: str | os.PathLike,
    file_members: Iterable[dict],
    *,
    targets: dict[str, Path] | None = None,
    should_stop: Callable[[], bool] | None = None,
    place_hf: bool = False,
) -> dict:
    """Put an oo-volumes-2 artifact's large public files back into their live homes.

    R787: the Hugging Face models an artifact carries are placed only when ``place_hf`` is true -- the
    person ticked them on the import checklist, which showed the folder they go to on this computer.
    Otherwise they stay in the artifact, counted in ``hf_not_chosen``, and nothing of them is written.
    When the cache folder here cannot take them, the restore says so (``refused_targets``) and is
    ``incomplete``, never complete.

    The counterpart of :func:`restore_folder_backup` for the files that rode INSIDE the
    signed artifact (S6.2). Same additive rule -- an existing destination file is never
    overwritten -- and the same atomic temp-then-rename, so an interrupted placement
    leaves no half-written dump for the app to read as its own.

    IT DOES NOT RE-HASH, and that is a statement about where the check happened rather
    than a gap: ``read_stream_backup`` reassembles every member from its volumes and
    refuses the whole restore unless the bytes match the ``plaintext_sha256`` the manifest
    recorded, so a file reaching ``staging_dir`` has already been verified against a
    SIGNED index. The folder backup hashes here because its files are copied as-is onto an
    editable drive and nothing verified them earlier; these were verified earlier.

    THE PATH GUARDS ARE THE POINT (the 2026-07-10 lesson). ``category`` and ``rel`` come
    from a manifest anyone can self-sign and are composed into the LIVE data directory --
    a field not called "name" becoming a path is exactly how that class failed before.
    ``_require_safe_manifest_names`` refuses traversal in ``rel``/``name`` and an unknown
    ``category`` before a restore ever reaches here -- and this function re-checks all of
    it anyway, because a guard that has to be reached from somewhere else is not a guard
    on this function, and this one is public. ``name`` matters as much as ``rel``: it is
    joined onto the staging dir to find the bytes, so an unguarded one is an arbitrary
    READ copied into the live data directory under an innocuous destination name. The
    composed destination is then checked for CONTAINMENT (``is_relative_to``, never a
    string prefix -- a sibling directory shares one).

    Every refusal carries its OWN reason. Reporting "unknown category" for an entry whose
    category was fine and whose path was hostile sends a reader looking for the wrong
    thing -- the same mislabelling the pre-swap barriers were fixed for."""
    staging = Path(staging_dir)
    tgt = live_targets(targets)
    placed = skipped = 0
    placed_bytes = 0
    refused: list[dict] = []
    missing: list[dict] = []
    stopped = False
    hf_refused: str | None = None  # R784: looked at once, the first time a model-cache member comes up
    hf_not_chosen = 0  # R787
    refused_targets: dict[str, str] = {}
    for fm in file_members:
        if should_stop is not None and should_stop():
            stopped = True
            break
        category, rel, name = (
            str(fm.get("category") or ""),
            str(fm.get("rel") or ""),
            str(fm.get("name") or ""),
        )
        root = tgt.get(category)
        if root is None:
            refused.append({"category": category, "rel": rel, "why": "unknown category"})
            continue
        why = _unsafe_placement_reason(name, rel)
        if why is not None:
            refused.append({"category": category, "rel": rel, "why": why})
            continue
        src_path = staging / name
        place_rel = rel
        if category == "hf_models":
            if not place_hf:
                # R787: never placed unasked. Counted, so the result can say what stayed in the artifact.
                hf_not_chosen += 1
                continue
            # R784: ``hub/`` is the hub cache folder itself, and only the cache's own shape is placed
            # (R777's rule, which this path now applies too).
            live_rel = hf_live_rel(rel)
            if live_rel is None:
                refused.append({"category": category, "rel": rel, "why": "outside the model cache's layout"})
                continue
            place_rel = live_rel
            if hf_refused is None:
                hf_refused = hf_target_refusal(root) or ""
            if hf_refused:
                # R787: one fixed code for the whole category, said once on screen in the person's language.
                refused_targets["hf_models"] = hf_refused
                refused.append({"category": category, "rel": rel, "why": f"model cache folder {hf_refused}"})
                continue
        dst = root / place_rel
        try:
            contained = dst.resolve().is_relative_to(root.resolve())
        except (OSError, ValueError):  # pragma: no cover - defensive
            contained = False
        if not contained:
            refused.append({"category": category, "rel": rel, "why": "outside its category"})
            continue
        # R779's destination rule, on this path too (R784 security read): a link anywhere between the live
        # folder and the file is never written through. A real Hugging Face cache is made of links, and a
        # DANGLING one (a deleted blob) reads as absent to ``exists()``, so it would have been replaced.
        # R787 reads: a link AT the file's own name is that file already present here (a cache's
        # snapshot entries are links into its blobs), so it is kept and counted as skipped; a link in a
        # folder on the way is still refused. A name the system cannot look at (too long, a file where
        # a folder is needed) refuses that one member and never stops the others.
        try:
            parent_link = link_on_the_way(root, Path(place_rel).parent)
            own_link = not parent_link and os.path.islink(dst)
        except (OSError, ValueError):
            refused.append({"category": category, "rel": rel, "why": "a name that cannot be used here"})
            continue
        if parent_link:
            refused.append({"category": category, "rel": rel, "why": "a link on the way in your data folder"})
            continue
        if own_link:
            skipped += 1  # never overwrite a local file, and never write through a link
            continue
        if not src_path.is_file():
            # The member is named in the index but its bytes are not in staging. The
            # reassembly would have raised on a checksum failure, so this is an index
            # that names a member the artifact does not carry -- reported, never invented.
            missing.append({"category": category, "rel": rel})
            continue
        if dst.exists():
            skipped += 1  # never overwrite a local file
            continue
        try:
            copied = _atomic_copy(src_path, dst, should_stop=should_stop)
        except OSError as exc:
            # R787 reads: a NAME this system cannot hold (too long, or a file where the artifact needs a
            # folder) refuses that one member; any other failure (a full disk) still stops, as before.
            if exc.errno not in _NAME_ERRNOS:
                raise
            refused.append({"category": category, "rel": rel, "why": "a name that cannot be used here"})
            continue
        if not copied:
            stopped = True
            break
        placed += 1
        placed_bytes += src_path.stat().st_size
    return {
        "placed": placed,
        "placed_bytes": placed_bytes,
        "skipped": skipped,
        "refused": refused[:_PROBLEM_CAP],
        "refused_total": len(refused),
        "missing": missing[:_PROBLEM_CAP],
        "missing_total": len(missing),
        "stopped": stopped,
        # R787: what the person did not tick stays in the artifact; a cache folder that could not take
        # the models makes the restore incomplete, as does any refused or missing member.
        "hf_not_chosen": hf_not_chosen,
        "refused_targets": refused_targets,
        "incomplete": bool(refused or missing or stopped),
        "method": (
            "Files carried inside the artifact are placed additively: an existing local "
            "file is kept and counted in `skipped`, never replaced. Their bytes were "
            "checksum-verified against the signed manifest during reassembly, so they "
            "are not re-hashed here."
        ),
    }


def _same_file(opened: os.stat_result, checked: os.stat_result) -> bool:
    """Whether the file opened is the one that was checked.

    Device and inode on POSIX. On Windows ``lstat`` and ``fstat`` can read the file id by two routes
    that need not agree on every file system (ReFS, Dev Drive), and a mismatch there would refuse every
    member of a sound backup, so the size stands in; the real-path and link-on-the-way checks made just
    before the open carry the rest there."""
    if os.name == "nt":
        return opened.st_size == checked.st_size
    return (opened.st_dev, opened.st_ino) == (checked.st_dev, checked.st_ino)


def _same_file_again(opened: os.stat_result, checked: os.stat_result, src: Path) -> bool:
    """A second look by name when the inode moved (POSIX): FAT32, exFAT, a CIFS share mounted
    ``noserverino`` or a FUSE file system without ``use_ino`` make an inode number up when a file is
    loaded, and it can change if the kernel drops the file in between -- likely while tens of GB are
    copied. A sound member would then be refused at random. So the name is looked at again: it must
    still not be a link, be a regular file on the same device as the one checked, with the size
    checked, and now carry the inode that was opened. A swap would have to win this look too, which
    is the same race as the stated limit, never a wider one."""
    if os.name == "nt" or opened.st_dev != checked.st_dev or opened.st_size != checked.st_size:
        return False
    try:
        now = os.lstat(src)
    except OSError:
        return False
    return (stat.S_ISREG(now.st_mode) and not is_link_stat(now)
            and (now.st_dev, now.st_ino) == (opened.st_dev, opened.st_ino))


def _linked_way(root: Path, root_real: str, it: BackupItem) -> tuple[str, str] | None:
    """The first folder below ``root`` on ``it``'s way that is a link, or that leads out of ``root``:
    ``(its path inside the backup folder, where it really points)``. ``None`` when the way is plain."""
    rel_parent = Path(it.category) / Path(it.rel).parent
    if not link_on_the_way(root, rel_parent) and stays_inside(root / rel_parent, root_real):
        return None
    cur = root
    for part in rel_parent.parts:
        cur = cur / part
        if is_link(cur) or not stays_inside(cur, root_real):
            break
    return (cur.relative_to(root).as_posix(), os.path.realpath(cur))


class LinkedBackupFolder(OSError):
    """A folder inside the chosen backup folder is a link: the backup stops rather than write through it."""


class SourceChanged(OSError):
    """A restore member is no longer the file that was checked (R779): it was swapped after the look."""


class SourceUnreadable(OSError):
    """A restore member that could not be READ (R778). Never a destination failure: a full disk or a
    live folder that cannot be written still stops the restore with an error, because every file after
    it would fail the same way. Each subclass is one fixed reason; the system's own words are dropped."""


class UnreadDenied(SourceUnreadable):
    """The system refused to let the file be read (permissions, or a file another program holds locked)."""


class UnreadGone(SourceUnreadable):
    """The file was listed, then was no longer there when it was read."""


class UnreadNotAFile(SourceUnreadable):
    """The name no longer stands for a regular file."""


class UnreadFailed(SourceUnreadable):
    """Reading failed part-way, or for another reason (a damaged drive, a disconnected device)."""


#: R778's fixed reason codes, by class. A folder that could not be listed has its own code.
UNREAD_WHY: dict[type, str] = {
    UnreadDenied: "denied",
    UnreadGone: "gone",
    UnreadNotAFile: "not-a-file",
    UnreadFailed: "read-failed",
}
UNREAD_FOLDER = "folder-unlisted"


def _unread_of(cls: type) -> SourceUnreadable:
    """The fixed R778 class for an ``OSError`` class met while READING a member."""
    if issubclass(cls, PermissionError):
        return UnreadDenied("permission denied")
    if issubclass(cls, FileNotFoundError):
        return UnreadGone("no longer there")
    if issubclass(cls, (IsADirectoryError, NotADirectoryError)):
        return UnreadNotAFile("not a file")
    return UnreadFailed("could not be read")


def _process_can_open() -> bool:
    """Whether this process can still open a file at all. Asked only after a source failed: when the
    process itself is out of file handles, every file after this one would fail the same way, so the
    restore stops with that error instead of marking the rest unread one by one. Answered by trying,
    since the error's own number is not read (the sink rule). Stated limit: an open refused for lack of
    memory is not told apart this way (opening the null device usually still succeeds), so it is
    counted against that one file."""
    try:
        fd = os.open(os.devnull, os.O_RDONLY)
    except OSError:
        return False
    os.close(fd)
    return True


def _now_a_link(path: Path) -> bool:
    """``is_link`` for a name whose open just failed; a name that cannot even be looked at is not
    known to be a link, and its open failure is reported as such."""
    try:
        return is_link(path)
    except OSError:
        return False


#: R783: whether this system can walk a folder by handle and open every name relative to its folder
#: without following a link (the pieces ``os.fwalk`` and ``openat`` stand on: handle-relative open, stat
#: and listing, O_NOFOLLOW, O_DIRECTORY). Decided by what the system offers, never by its name: where any
#: piece is missing (Windows has no ``dir_fd``), the restore keeps R779's checks by path and their stated
#: limit.
_FD_RELATIVE = bool(
    os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.scandir in os.supports_fd
    and os.stat in os.supports_follow_symlinks
    and getattr(os, "O_NOFOLLOW", 0)
    and getattr(os, "O_DIRECTORY", 0)
)


def _fd_open_error(name: str, dir_fd: int, cls: type) -> OSError | None:
    """What a failed fd-relative open of ``name`` (raising ``cls``) means for the restore: a link there is
    refused, as R779 refuses it (``SourceChanged``); anything else is counted as not read with R778's fixed
    reason; ``None`` when the process itself is out of file handles, and the restore stops with the error."""
    try:
        if is_link_stat(os.stat(name, dir_fd=dir_fd, follow_symlinks=False)):
            return SourceChanged("a name on the way became a link after it was checked")
    except OSError:
        pass
    if not _process_can_open():
        return None
    return _unread_of(cls)


def _open_member_fd(backup_root: Path, cat: str, cat_st: os.stat_result, rel: PurePosixPath) -> int:
    """R783: open one restore member ONE NAME AT A TIME from the category folder, each name opened relative
    to the folder handle before it and never followed if it is a link (``O_NOFOLLOW``; ``O_DIRECTORY`` for
    the folders on the way). A folder swapped for a link between the walk and this open is refused here, by
    the system, at the moment of the open -- not by a look made before it, which is the window R779 could
    only narrow.

    The category folder is opened by its path, without following it, and must be the folder that was
    walked (the backup folder above it is the place the person chose and may be a link, as R779 measures
    it; only passing through it is needed). At most two handles are held at once, whatever the depth, and
    every one but the returned one is closed."""
    dir_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        cur = os.open(backup_root / cat, dir_flags)
    except OSError as exc:
        if _now_a_link(backup_root / cat):
            raise SourceChanged("the category folder became a link after it was walked") from None
        if not _process_can_open():
            raise
        raise _unread_of(type(exc)) from None
    try:
        try:
            same = os.path.samestat(os.fstat(cur), cat_st)
        except OSError:
            same = False
        if not same and not _same_folder_again(cur, cat_st, backup_root / cat):
            raise SourceChanged("the category folder changed after it was walked")
        for name in rel.parent.parts:
            try:
                nxt = os.open(name, dir_flags, dir_fd=cur)
            except OSError as exc:
                err = _fd_open_error(name, cur, type(exc))
                if err is None:
                    raise
                raise err from None
            os.close(cur)
            cur = nxt
        flags = os.O_RDONLY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
        try:
            return os.open(rel.name, flags, dir_fd=cur)
        except OSError as exc:
            err = _fd_open_error(rel.name, cur, type(exc))
            if err is None:
                raise
            raise err from None
    finally:
        os.close(cur)


def _same_folder_again(fd: int, walked: os.stat_result, path: Path) -> bool:
    """The category folder's second look when its inode moved, as ``_same_file_again`` does for a file:
    FAT32, exFAT, a CIFS share mounted ``noserverino`` or FUSE without ``use_ino`` make a folder's inode
    number up again when the kernel drops it, likely during a long copy, which would refuse every member of
    a sound backup. Accepted only on the same device, with the name still a folder and not a link, carrying
    the inode of the folder just opened. A swap would have to win this look too."""
    try:
        opened = os.fstat(fd)
        now = os.lstat(path)
    except OSError:
        return False
    return (opened.st_dev == walked.st_dev and stat.S_ISDIR(now.st_mode) and not is_link_stat(now)
            and (now.st_dev, now.st_ino) == (opened.st_dev, opened.st_ino))


def _open_dir_chain(root_fd: int, parts: tuple[str, ...]) -> int | None:
    """The folder ``parts`` below ``root_fd``, opened one name at a time without following a link, holding
    at most two handles; ``None`` when any name on the way cannot be opened as a folder (a link included)."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    cur = root_fd
    try:
        for p in parts:
            nxt = os.open(p, flags, dir_fd=cur)
            if cur != root_fd:
                os.close(cur)
            cur = nxt
    except OSError:
        if cur != root_fd:
            os.close(cur)
        return None
    return cur


def _fd_walk(top: str):
    """R783: ``os.walk``'s shape (top-down, ``dirnames`` pruned in place), walked BY HANDLE. Every folder is
    reached from the category folder's handle one name at a time with ``O_NOFOLLOW | O_DIRECTORY`` and
    listed through its own handle. Yields ``(dirpath, dirnames, names, dir_fd)``; ``dir_fd`` is valid until
    the next item.

    Written here rather than taken from ``os.fwalk`` (the reads of this change): ``os.fwalk`` RAISES where
    ``os.walk`` passes over -- a category folder that cannot be opened, a listing that fails part-way on a
    damaged drive, a folder nested deeper than the process has handles for, since it holds one handle per
    level. Here, as with ``os.walk``, a folder that cannot be opened or listed is never handed back and the
    caller counts it as not listed (R778); and each folder is reopened from the category folder's handle
    rather than kept open below its parent, so at most three handles are open whatever the depth. An entry
    is sorted by its own type, never by what a link points at, so a link always lands in ``names``, where
    the caller counts it; an entry whose type cannot be read lands there too and is counted as unread by
    the caller's look."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0)
    try:
        root = os.open(top, flags)
    except OSError:
        return
    try:
        stack: list[tuple[str, ...]] = [()]
        while stack:
            parts = stack.pop()
            fd = root if not parts else _open_dir_chain(root, parts)
            if fd is None:
                if not _process_can_open():  # asked while the walk still holds its handles
                    raise OSError("this process could not open any file while listing the backup")
                continue  # never handed back: the caller counts it as not listed
            try:
                dirnames: list[str] = []
                names: list[str] = []
                try:
                    with os.scandir(fd) as it:
                        for entry in it:
                            try:
                                is_dir = entry.is_dir(follow_symlinks=False)
                            except OSError:
                                is_dir = False
                            (dirnames if is_dir else names).append(entry.name)
                except OSError:
                    if not _process_can_open():
                        raise OSError("this process could not open any file while listing the backup") from None
                    continue  # could not be listed: never handed back, as os.walk does
                yield os.path.join(top, *parts), dirnames, names, fd
                stack.extend(parts + (n,) for n in reversed(dirnames))
            finally:
                if fd != root:
                    os.close(fd)
    finally:
        os.close(root)


def _category_swapped(cat_root: Path, cat_real: str) -> bool:
    """Whether the category folder is now a link, or (where the system gives folders a stable identity)
    no longer the folder its resolved path names. A folder that cannot be looked at counts as swapped."""
    try:
        st = os.lstat(cat_root)
        if is_link_stat(st):
            return True
        return os.name != "nt" and not os.path.samestat(st, os.stat(cat_real))
    except OSError:
        return True


def _category_members(
    cat_root: Path, unread: list[tuple[str, str]] | None = None
) -> tuple[list[tuple[Path, os.stat_result]], int]:
    """The regular files a restore may copy from one category folder, each with the ``lstat`` it was
    checked by, sorted, and the number of links met on the way (R779).

    Walked with ``os.walk`` (or, R783, by handle with ``_fd_walk``) and PRUNED here rather than by the walker's own rule, because ``rglob`` and
    ``os.walk`` both treat a Windows junction as a plain folder and would walk into it. A ``.oopart`` is
    skipped before its link check (a copy in progress, never a member), and a plain folder is entered
    whatever its name. Mirrors ``import_scan._dir_totals``, so the preview and the restore agree.

    R778: what could not be looked at is appended to ``unread`` as ``(relative path, reason code)`` --
    a folder that could not be listed (its files are unknown, so it is one entry), a sub-folder or a
    file whose own look was refused -- and the walk goes on."""
    members: list[tuple[Path, os.stat_result]] = []
    links = 0

    def _note(path: str, why: str) -> None:
        if unread is not None:
            unread.append((Path(path).relative_to(cat_root).as_posix(), why))

    # A folder the walk was told to enter but never handed back is one it could not list. Worked out
    # from the walk's own output rather than its error, so nothing of the system's words is read.
    to_enter: list[str] = [os.fspath(cat_root)]
    listed: set[str] = set()
    # R783: where the system can, the folders are walked BY HANDLE (``_fd_walk``) and every name is
    # looked at relative to its folder's handle, so a folder swapped for a link during the walk cannot
    # send it somewhere else. The files are opened the same way later (``_open_member_fd``).
    walk = (
        _fd_walk(os.fspath(cat_root))
        if _FD_RELATIVE
        else ((dp, dn, fn, None) for dp, dn, fn in os.walk(cat_root, followlinks=False))
    )

    def _look(dirpath: str, n: str, dir_fd: int | None) -> os.stat_result:
        if dir_fd is None:
            return os.lstat(os.path.join(dirpath, n))
        return os.stat(n, dir_fd=dir_fd, follow_symlinks=False)

    try:
        for dirpath, dirnames, names, dir_fd in walk:
            listed.add(dirpath)
            enter: list[str] = []
            for n in dirnames:
                try:
                    if dir_fd is None:
                        linked = is_link(os.path.join(dirpath, n))
                    else:
                        try:
                            linked = is_link_stat(_look(dirpath, n, dir_fd))
                        except FileNotFoundError:
                            linked = False
                except OSError:
                    if not _process_can_open():
                        raise
                    _note(os.path.join(dirpath, n), UNREAD_FOLDER)
                    continue
                if linked:
                    if not n.endswith(_PART_SUFFIX):
                        links += 1  # never follow -- see restore_folder_backup's docstring
                else:
                    enter.append(n)
            dirnames[:] = enter
            to_enter.extend(os.path.join(dirpath, n) for n in enter)
            for n in names:
                if n.endswith(_PART_SUFFIX):
                    continue
                fp = os.path.join(dirpath, n)
                try:
                    st = _look(dirpath, n, dir_fd)
                except FileNotFoundError:
                    continue
                except OSError as exc:
                    if not _process_can_open():
                        raise
                    _note(fp, UNREAD_WHY[type(_unread_of(type(exc)))])
                    continue
                if is_link_stat(st):
                    links += 1
                elif stat.S_ISREG(st.st_mode):
                    members.append((Path(fp), st))
    finally:
        walk.close()  # every folder handle is closed, even when the walk stops part-way
    for d in to_enter:
        if d not in listed:
            # One rule for what disappears while the folder is being LISTED: it was never a member, so
            # it is not counted (a file gone before its look is passed over the same way above). What
            # is gone after it was listed is counted as "no longer there" when its copy is tried.
            try:
                os.lstat(d)
            except FileNotFoundError:
                continue
            except OSError:
                pass
            # Out of file handles, ``os.walk`` passes over every folder it cannot open: that is the
            # process, not the backup, and every folder after it would read the same way. Stop.
            if not _process_can_open():
                raise OSError("this process could not open any file while listing the backup")
            rel = Path(d).relative_to(cat_root).as_posix()
            if unread is not None:
                unread.append(("" if rel == "." else rel, UNREAD_FOLDER))
    members.sort(key=lambda m: m[0])
    return members, links


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
    own ``_safe_member_path`` guard for the identical untrusted-input threat model.

    ONE UNREADABLE FILE DOES NOT STOP THE RESTORE (R778). A member the restore cannot READ -- refused
    by the system, gone since it was listed, no longer a file, a read that fails part-way, or a folder
    that cannot be listed -- is left out, counted in ``unread`` with one fixed reason code (never the
    system's words), and the restore goes on; ``incomplete`` is then true. Nothing of it reaches the
    live folder: the copy goes through a temp file that is removed, and an existing live file is never
    touched, so running the import again restores exactly what was missed. A failure on the WRITING
    side still stops the restore with an error, since every file after it would fail the same way. A
    folder backup holds no critical member: its four categories (``_CATEGORIES``) are wiki dumps, map
    extracts and AI models, never the main store or key material, so nothing here needs to stop the
    whole restore before anything is placed."""
    src = Path(src_root)
    cats = set(categories) if categories is not None else set(_CATEGORIES)
    tgt = live_targets(targets)

    # The checksums this backup recorded when it wrote the bytes. Empty for a backup
    # written before they existed, and for one whose manifest is missing or damaged --
    # in which case every file restores as before and is COUNTED as unverifiable, never
    # silently called sound.
    recorded = _recorded_digests(src)
    # R780: which files the current manifest lists at all. A file it does not list is restored as
    # before and counted per category, apart from "not content-verified".
    listing = _manifest_listing(src)
    unlisted: dict[str, int] = {}

    restored = skipped = refused_symlinks = refused_dest_links = refused_layout = 0
    refused_categories: list[str] = []
    # R784: categories whose LIVE folder cannot take a restore on this computer, with one fixed reason.
    refused_targets: dict[str, str] = {}
    corrupt: list[dict] = []
    # R778: what could not be READ. Counted and named like ``corrupt``, and the restore goes on.
    unread: list[dict] = []
    unread_total = 0
    unread_by_why: dict[str, int] = {}

    unread_folders = 0

    def _shown(rel: str) -> str:
        # A name that is not valid UTF-8 (a foreign drive) comes back from the system with lone surrogates,
        # which the JSON status responses cannot encode: replace them, so the result always renders.
        return rel.encode("utf-8", "surrogateescape").decode("utf-8", "replace")

    def _unread(cat: str, rel: str, why: str) -> None:
        # A folder that could not be listed is ONE entry whose files are unknown: counted apart, so
        # "N files not restored" never counts a folder of forty dumps as one file.
        nonlocal unread_total, unread_folders
        if why == UNREAD_FOLDER:
            unread_folders += 1
        else:
            unread_total += 1
        unread_by_why[why] = unread_by_why.get(why, 0) + 1
        if len(unread) < _PROBLEM_CAP:
            unread.append({"category": cat, "rel": _shown(rel), "why": why})

    unverifiable = 0
    stopped = False
    for cat in _CATEGORIES:
        if cat not in cats:
            continue
        cat_root = src / cat
        dest_dir = tgt.get(cat)
        if dest_dir is None:
            continue
        # R779: the CATEGORY FOLDER ITSELF is checked without following it. ``is_dir()`` and
        # ``rglob`` both follow a link at this level, so a backup whose ``wiki_dumps`` was a link
        # to some other place on the machine had that place's files copied into the live data
        # folder. A junction or other reparse point counts as a link too (Windows).
        try:
            linked_cat = is_link(cat_root)
            is_folder = linked_cat or stat.S_ISDIR(os.stat(cat_root).st_mode)
        except FileNotFoundError:
            continue
        except OSError:
            if not _process_can_open():
                raise  # the process, not the backup: stop
            # R778: the category folder itself could not be looked at. Nothing in it was restored.
            _unread(cat, "", UNREAD_FOLDER)
            continue
        if linked_cat:
            refused_categories.append(cat)
            continue
        if not is_folder:
            continue
        if cat == "hf_models":
            # R784: the hub cache folder as it resolves HERE; one that cannot be used leaves the whole
            # category out with its reason, and the restore is incomplete.
            why_target = hf_target_refusal(dest_dir)
            if why_target is not None:
                refused_targets[cat] = why_target
                continue
        # Containment is measured from where the folders really are: the backup folder the person
        # picked may itself be a link (their choice), and so may a live data folder they moved.
        cat_real = os.path.realpath(cat_root)
        dest_real = os.path.realpath(dest_dir)
        # The folder measured must be the folder that was checked: a drive that swaps the category
        # folder for a link between the check above and the line before would otherwise have the
        # containment measured from the link's target. Checked again after the walk, and the category
        # folder is part of every member's way below (the check-then-open window stays narrowed, not closed).
        if _category_swapped(cat_root, cat_real):
            refused_categories.append(cat)
            continue
        try:
            cat_st = os.lstat(cat_root)
            cat_dev = cat_st.st_dev
        except OSError:
            refused_categories.append(cat)
            continue
        not_listed: list[tuple[str, str]] = []
        members, linked_here = _category_members(cat_root, not_listed)
        if _category_swapped(cat_root, cat_real):
            refused_categories.append(cat)
            continue
        refused_symlinks += linked_here
        for rel_s, why in not_listed:
            _unread(cat, rel_s, why)
        for p, seen in members:
            rel = p.relative_to(cat_root)
            if cat == "hf_models" and not hf_member_allowed(rel.as_posix()):
                refused_layout += 1  # R777: only the model cache's own layout is ever placed
                continue
            # Belt and braces: whatever the walk handed back, no part of the way from the BACKUP folder
            # to the member -- the category folder included -- may be a link, and its real path may not
            # leave the folder.
            # A member on ANOTHER device than the category folder was reached through something that
            # is not a plain folder of the backup: a drive that answers "folder" to the checks and
            # "link" to the walk or the open (a hostile FUSE device can) would otherwise hand over a
            # file from the machine itself, with the open's own identity check agreeing, since both
            # looked at that same file. Refused. R783: where the system can (``_FD_RELATIVE``), the open
            # itself goes from the category folder one name at a time by handle with O_NOFOLLOW, so a folder swapped for a
            # link after these checks is refused AT the open. STATED LIMIT, where it cannot (Windows):
            # a racer on the SAME file system as the files it wants read (any local program) can still
            # swap a folder on the way between these checks and the open.
            if seen.st_dev != cat_dev:
                refused_symlinks += 1
                continue
            try:
                linked_way = link_on_the_way(src, Path(cat) / rel.parent)
            except OSError as exc:
                if not _process_can_open():
                    raise
                _unread(cat, rel.as_posix(), UNREAD_WHY[type(_unread_of(type(exc)))])
                continue
            if linked_way or not stays_inside(p, cat_real):
                refused_symlinks += 1
                continue
            # R784: in the model cache, the leading ``hub/`` is the hub cache folder itself.
            if cat == "hf_models":
                live_rel = hf_live_rel(rel.as_posix())
                if live_rel is None:  # pragma: no cover - hf_member_allowed refused it above
                    refused_layout += 1
                    continue
                rel_live = Path(live_rel)
            else:
                rel_live = rel
            dst = dest_dir / rel_live
            # R779, the destination side: never write THROUGH a link. A link anywhere between the
            # live folder and the file (a sub-folder, or the file's own name) is refused, and the
            # resolved destination must stay inside the live folder.
            # R787 reads: a link AT the file's own name is that file already present (a Hugging Face
            # cache's snapshot entries are links into its blobs): kept and counted as skipped, never
            # written through. A link in a folder on the way is still refused.
            if link_on_the_way(dest_dir, rel_live.parent) or not stays_inside(dst.parent, dest_real):
                refused_dest_links += 1
                continue
            if os.path.islink(dst) or dst.exists():
                skipped += 1  # never overwrite a local file
                continue
            want = recorded.get((cat, rel.as_posix(), seen.st_size))
            # VERIFY WHILE COPYING, and only commit the copy if it matches. The bytes
            # are read either way, so the check is free; the temp file is what makes
            # "refuse" possible at all -- a corrupt member is discarded before it can
            # land in the live data directory. Without this a dump that rotted on the
            # external drive was restored silently, and the app then read it as its own.
            h = hashlib.sha256() if want is not None else None
            try:
                opener: Callable[[], int] | None = None
                if _FD_RELATIVE:  # R783: opened by folder handle, never by the path checked above
                    opener = functools.partial(_open_member_fd, src, cat, cat_st, PurePosixPath(rel.as_posix()))

                done = _atomic_copy(p, dst, should_stop=should_stop, digest=h, nofollow_src=True, expect=seen,
                                    opener=opener)
            except SourceChanged:
                refused_symlinks += 1  # swapped for something else after it was looked at: not read
                continue
            except SourceUnreadable as exc:
                # R778: this one file could not be read. Nothing of it reached the live folder (the
                # temp is gone, the live name never appeared), so a later run restores exactly it.
                _unread(cat, rel.as_posix(), UNREAD_WHY.get(type(exc), "read-failed"))
                continue
            if not done:
                stopped = True
                break
            if h is not None and h.hexdigest() != want:
                dst.unlink(missing_ok=True)
                if len(corrupt) < _PROBLEM_CAP:
                    corrupt.append({"category": cat, "rel": _shown(rel.as_posix())})
                continue
            if want is None:
                unverifiable += 1  # an unlisted file has no recorded checksum either, so it counts here too
            if listing is None or rel.as_posix() not in listing.get(cat, ()):
                unlisted[cat] = unlisted.get(cat, 0) + 1
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
        # R779: category folders that are links. NOTHING in them was restored, so the restore is
        # incomplete -- the person restores them by copying the real folder into the backup.
        "refused_categories": refused_categories,
        # R784: categories whose live folder cannot take a restore here, ``{category: reason code}``
        # (HF_TARGET_*). Nothing of them was restored.
        "refused_targets": refused_targets,
        # R779: files not placed because a link sat on the way to their place in the live folder.
        "refused_dest_links": refused_dest_links,
        # A member link was never written by a backup, but its place in the restore is still empty:
        # any link refusal means the restore did not bring back everything the folder showed.
        "incomplete": bool(refused_categories or refused_targets or refused_dest_links or refused_symlinks or unread_total or unread_folders
                           or refused_layout),
        # R777: files in the model-cache folder outside the shape the backup writes there (hidden names,
        # anything outside hub/models--*/refs|snapshots). Never placed in the Hugging Face home.
        "refused_layout": refused_layout,
        # R778: files (or folders, whose files are unknown) that could not be READ, each with one fixed
        # reason code. Not restored; the rest of the restore went on. Names stay on this machine: the
        # run journal and the diagnostics carry the count only.
        "unread_total": unread_total,  # FILES that could not be read
        "unread_folders": unread_folders,  # folders that could not be listed: their files are unknown
        "unread_by_why": unread_by_why,  # every one counted, past the named list's cap
        "unread": unread,
        # A file whose bytes did not match the checksum this backup recorded for it. NOT
        # restored: the copy is removed again, so the live data directory never receives
        # it. Named, so the operator can re-download exactly those.
        "corrupt_refused": len(corrupt),
        "corrupt": corrupt,
        # Restored, but with no recorded checksum to check against (a pre-2026-09-07
        # backup, or a manifest that could not be read). A gap, published as a gap:
        # these were NOT content-verified and must not be counted as if they were.
        "restored_unverified": unverifiable,
        # R780: restored, but not listed in this backup's CURRENT manifest, per category. They may come
        # from an earlier or interrupted backup pass (a stopped pass keeps the previous manifest, and a
        # file removed from the live folder since an earlier pass stays on the drive); counted apart
        # from "not content-verified", never refused, since the manifest proves no origin.
        "restored_unlisted": unlisted,
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


def _plain_rel(rel: str) -> bool:
    """R791: whether a manifest ``rel`` is a plain member name, the only shape a folder backup writes: forward
    slashes, no empty, ``.`` or ``..`` part, no backslash, no NUL, not absolute (and no colon on Windows). Anything else is refused by
    its name before any look, so a ``..`` that would resolve back inside the folder cannot lead a check, or a
    read, through a link on its way."""
    if not isinstance(rel, str) or not rel or "\x00" in rel or "\\" in rel or rel.startswith("/"):
        return False
    parts = rel.split("/")
    # A drive or stream name (``C:x``, ``f:stream``) means something else on Windows; elsewhere a colon is a letter.
    return all(p not in ("", ".", "..") for p in parts) and not (os.name == "nt" and ":" in rel)


def _member_link(root: Path, category: str, rel: str) -> str | None:
    """R791: the name a restore would refuse this member by, as a path below the category folder (``""`` for
    the category folder itself), or ``None``: the category folder, a folder below it, or the file itself is a
    link, or the file sits on another device than its category folder (a mount point, a FUSE folder: restore
    refuses those with its links). A name that cannot be looked at is not called a link here; the checks
    that follow report it. ``rel`` must already be a plain name (``_plain_rel``)."""
    parts = rel.split("/")
    try:
        if is_link(root / category):
            return ""
        for i in range(1, len(parts) + 1):
            if is_link(root / category / Path(*parts[:i])):
                return "/".join(parts[:i])
        if os.lstat(root / category / Path(*parts)).st_dev != os.lstat(root / category).st_dev:
            return rel
    except (OSError, ValueError):
        return None
    return None


def _linked_member(root: Path, category: str, rel: str) -> bool:
    """Whether ``_member_link`` names a link for this member (a name that is not plain is never one: the
    traversal guard refuses it by its own name)."""
    return _plain_rel(rel) and _member_link(root, category, rel) is not None


def _links_in_category(cat_root: Path, should_stop: Callable[[], bool] | None = None) -> list[str]:
    """R791: every link inside a category folder, as a path below it, found without following any (a link
    to a folder is listed and not entered), and every name on another device than the category folder (a
    mount point or a subvolume: restore refuses what it holds as it refuses a link; listed, not entered). A
    ``.oopart`` is passed over, as restore passes it over. A folder that cannot be listed is passed over too:
    its files are reported by the entries that name them. ``should_stop`` ends the walk between folders."""
    found: list[str] = []
    try:
        cat_dev = os.lstat(cat_root).st_dev
    except OSError:
        return found
    stack = [""]
    while stack:
        if should_stop is not None and should_stop():
            break
        sub = stack.pop()
        try:
            with os.scandir(cat_root / sub if sub else cat_root) as it:
                names = sorted(e.name for e in it)
        except OSError:
            continue
        for n in names:
            if n.endswith(_PART_SUFFIX):
                continue
            rel = f"{sub}/{n}" if sub else n
            try:
                st = os.lstat(cat_root / rel)
            except OSError:
                continue
            if is_link_stat(st) or st.st_dev != cat_dev:
                found.append(rel)
            elif stat.S_ISDIR(st.st_mode):
                stack.append(rel)
    return sorted(found)


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
    """The SHA-256 of a regular file. The verify reaches a member through its name inside the backup folder, so a
    pipe or a device there raises :class:`NotARegularFile` without blocking or reading (row 312), and
    a link is never followed either (no backup we write holds one; one swapped in after the traversal guard looked
    could lead out of the folder), so it reads as a checksum mismatch."""
    h = hashlib.sha256()
    with open_regular(path) as f:
        for chunk in iter(lambda: f.read(_COPY_BUF), b""):
            h.update(chunk)
    return h.hexdigest()


def _hash_fd(fd: int) -> str:
    """The SHA-256 of an open file, read to its end (the handle is closed)."""
    h = hashlib.sha256()
    try:
        f = os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
    with f:
        for chunk in iter(lambda: f.read(_COPY_BUF), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_member(
    root: Path, category: str, rel: str, size: int, entry: dict, verify_model_checksums: bool
) -> tuple[str, dict, bool]:
    """One manifest entry's verdict: ``(status, detail, hashed)``. Never raises (R791): what cannot be looked
    at or read is ``unreadable``, a failure, never a crash and never a pass.

    The order is restore's: a name that is not a plain member name is refused by its name; a link on its way
    (or another device) is "a link, not checked" and is never read; then, where the system can
    (``_FD_RELATIVE``), the file is opened with restore's own opener, one name at a time from the category
    folder by handle without following a link, and its size and bytes are read FROM THAT HANDLE, so a folder
    swapped for a link after the look is refused at the open rather than read through. Where it cannot
    (Windows), the path checks stand, with restore's stated limit."""
    if category not in _CATEGORIES or not _plain_rel(rel):
        return "traversal_refused", {}, False
    if _member_link(root, category, rel) is not None:
        return "link_not_checked", said("why", "a link, not checked"), False
    path = _safe_member_path(root, category, rel)
    if path is None:
        return "traversal_refused", {}, False
    # Two independent stored checksums, and they are not the same evidence. `sha256` is what THIS backup
    # recorded when it wrote the bytes (present since 2026-09-07, and signed with the manifest). The Ollama
    # blob's own name embeds its sha256, which is the publisher's value and is carried by a backup of any
    # age. Where both exist they must BOTH match: a recorded digest that disagrees with the name is exactly
    # the case where trusting either one alone reports a corrupted blob as sound.
    recorded = entry.get("sha256")
    recorded = recorded.lower() if (isinstance(recorded, str) and _SHA256_RE.match(recorded)) else None
    blob_hex = _blob_sha256_from_name(rel) if category == "models" else None
    want = [h for h in (recorded, blob_hex) if h is not None]
    hash_it = bool(want) and (blob_hex is None or verify_model_checksums)
    if _FD_RELATIVE:
        try:
            # Looked at before it is opened: a device node a crafted drive carries is never opened, since an
            # open alone can have effects (row 312's rule). A swap after this look still meets O_NOFOLLOW.
            if not stat.S_ISREG(os.lstat(path).st_mode):
                return "missing", {}, False
        except FileNotFoundError:
            return "missing", {}, False
        except (OSError, ValueError):
            return "unreadable", {}, False
        try:
            cat_st = os.lstat(root / category)
            fd = _open_member_fd(root, category, cat_st, PurePosixPath(rel))
        except SourceChanged:
            return "link_not_checked", said("why", "a link, not checked"), False
        except (FileNotFoundError, UnreadGone, UnreadNotAFile, NotADirectoryError, IsADirectoryError):
            return "missing", {}, False
        except (OSError, ValueError):
            return "unreadable", {}, False
        try:
            st = os.fstat(fd)
            if not stat.S_ISREG(st.st_mode):
                return "missing", {}, False
            if st.st_dev != cat_st.st_dev:
                return "link_not_checked", said("why", "a link, not checked"), False
            if st.st_size != size:
                return "size_mismatch", {"expected_size": size, "actual_size": st.st_size}, False
            if not hash_it:
                return "size_only", {}, False
            # The handle was opened O_NONBLOCK (a pipe never blocks the open); a regular file reads the same.
            owned, fd = fd, -1  # handed over before the call: _hash_fd closes it, whatever happens
            actual_hex = _hash_fd(owned)
        except OSError:
            return "unreadable", {}, hash_it
        finally:
            if fd >= 0:
                os.close(fd)
        return ("ok" if all(actual_hex == h for h in want) else "checksum_mismatch"), {}, True
    try:
        if not path.is_file():
            return "missing", {}, False
        actual = path.stat().st_size
        if actual != size:
            return "size_mismatch", {"expected_size": size, "actual_size": actual}, False
        if not hash_it:
            return "size_only", {}, False
        try:
            actual_hex = _sha256_file(path)
        except NotARegularFile:
            actual_hex = ""  # a link, or swapped for a pipe or a device after the look: never a match
    except (OSError, ValueError):
        return "unreadable", {}, hash_it
    return ("ok" if actual_hex and all(actual_hex == h for h in want) else "checksum_mismatch"), {}, True


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
    manifest = read_manifest_json(root / MANIFEST_NAME)  # a link, a pipe, a huge or deeply nested file: none
    if manifest is None:
        try:
            present = os.path.lexists(root / MANIFEST_NAME)
        except (OSError, ValueError):
            present = False
        out["reason"] = (
            "a manifest is at this path but was refused: it is not a regular file, is too large, or is "
            "not readable JSON -- so there is nothing trustworthy to verify against."
            if present else
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
        "link_not_checked": 0,
        "unreadable": 0,
    }
    problems: list[dict] = []
    checked = checksummed = 0
    stopped = False
    implicated: set[tuple[str, str]] = set()
    for category, e in entries:
        if should_stop is not None and should_stop():
            stopped = True
            break
        rel = str(e.get("rel", ""))
        try:
            size = int(e.get("size", -1))
        except (TypeError, ValueError):
            size = -1
        status, detail, hashed = _verify_member(root, category, rel, size, e, verify_model_checksums)
        if hashed:
            checksummed += 1
        if status == "link_not_checked":
            if (link := _member_link(root, category, rel)) is not None:
                implicated.add((category, link))
        summary[status] += 1
        checked += 1
        if status not in ("ok", "size_only") and len(problems) < _PROBLEM_CAP:
            problems.append({"category": category, "rel": rel, "status": status, **detail})
        if progress_cb is not None:
            progress_cb({"files_total": total, "files_done": checked, "checksummed": checksummed})

    if not stopped:
        # R791: a link anywhere in a category folder leaves a restore incomplete (restore counts every link
        # it meets on its walk, listed or not), so one no manifest entry leads to is found here too, without
        # following it, and fails the verdict the same way.
        for category in sorted(c for c in cats if c in _CATEGORIES):
            cat_root = root / category
            try:
                plain = not is_link(cat_root) and cat_root.is_dir()
            except OSError:
                plain = False
            if not plain:
                continue
            for link in _links_in_category(cat_root, should_stop):
                if (category, link) in implicated:
                    continue
                summary["link_not_checked"] += 1
                if len(problems) < _PROBLEM_CAP:
                    problems.append({"category": category, "rel": link, "status": "link_not_checked",
                                     **said("why", "a link, not in the manifest")})
        if should_stop is not None and should_stop():
            stopped = True  # the walk was cut short: an incomplete verify never claims success
    summary["malformed_entries"] = malformed
    failures = (
        summary["missing"]
        + summary["size_mismatch"]
        + summary["checksum_mismatch"]
        + summary["traversal_refused"]
        + summary["link_not_checked"]  # R791: what a restore refuses is never counted as verified
        + summary["unreadable"]  # R791: a file that could not be read is not a file that was checked
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
            **(
                said(
                    "links",
                    "Not checked: {n}. Each is a link in the backup, or a file reached through one, and "
                    "neither Verify nor a restore follows a link. To check and restore them, copy the real folder or "
                    "file into the backup in place of the link.",
                    n=summary["link_not_checked"],
                )
                if summary["link_not_checked"]
                else {}
            ),
            "method": (
                "Every manifest-listed file must be present with the exact recorded size; "
                "any file carrying a recorded sha256 is streamed-hashed and matched against "
                "it, and content-addressed Ollama model blobs (blobs/sha256-<hex>) are also "
                "matched against the sha256 in their name (both, where both exist). The "
                "manifest's own Ed25519 signature is reported. Manifest paths are "
                "traversal-guarded before any stat/hash. A file reached through a link (its category folder, a folder below it, "
                "or the file itself) is never read and counts as link_not_checked, a failure, because a restore never "
                "follows a link; so does a link in a category folder that no entry names. Where the system allows, each "
                "file is opened one name at a time from its category folder without following a link, and its size and "
                "bytes are read from that handle. A file that cannot be read counts as unreadable, a failure. Counts "
                "only, no score."
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
import contextlib  # noqa: E402  (kept local to the job section)
import threading  # noqa: E402  (kept local to the job section)
import time  # noqa: E402  (same)

from src.backup import restore_marker, runlog  # noqa: E402  (same, beside the manager it serves)
from src.monitoring import storage_events  # noqa: E402  (same)

#: The storage-events journal's kind for each mode: a folder ``backup`` is an ``export`` there, a ``restore`` an ``import``. (The run
#: journal calls them ``folder-export`` and ``folder-import``; the records here carry ``via: folder`` to be matched by.)
_RUN_OF = {"backup": "export", "restore": "import", "verify": "verify"}


def _free_readable(path: Path) -> bool:
    """Whether the free space of ``path``'s volume can be read at all (``free_bytes`` answers 0 when it cannot, which would make a
    backup look refused for want of space that was never measured)."""
    p = path
    try:
        while not p.exists() and p != p.parent:
            p = p.parent
        shutil.disk_usage(p)
    except OSError:
        return False
    return True


def _volume_probe(destp: Path) -> Path | None:
    """The path whose volume a backup to ``destp`` will write to: ``destp`` itself, or its nearest existing parent when the copy has yet
    to make it (``validate_dest`` refused a destination with none). ``None`` when the operating system refuses to look (a mount that
    dropped, a permission): the free-bytes figure is then absent, and the walk never raises into a run that has begun."""
    probe = destp
    try:
        while not probe.exists() and probe != probe.parent:
            probe = probe.parent
    except OSError:
        return None
    return probe


def _verify_counts(res: dict) -> tuple[int | None, int | None]:
    """``(checked, mismatches)`` of a verify's report, or ``(None, None)`` when it holds no counts (no manifest, a damaged one).
    ``verify_folder_backup`` names them ``files_checked`` and ``summary`` and has never had a ``checked`` or a ``mismatches`` key, so the
    run journal's closing line read ``None`` for both until now. A mismatch is a file the manifest lists that is missing, of another
    size, of another checksum, outside the folder, a link or reached through one, or unreadable (R791), a manifest entry that was not one, or a manifest whose signature is bad (the
    failures the verdict counts); a file that is only ``size_only`` is not one. ``mismatches`` can therefore exceed ``checked`` (a
    bad signature checks no file, and a malformed category counts as one entry and checks none)."""
    summary = res.get("summary")
    if not isinstance(summary, dict):
        return None, None
    bad = sum(
        int(summary.get(key) or 0)
        for key in (
            "missing", "size_mismatch", "checksum_mismatch", "traversal_refused", "link_not_checked", "unreadable",
            "malformed_entries",
        )
    )
    if res.get("signature_state") == "bad-signature":
        bad += 1
    return res.get("files_checked"), bad


def _write_export_summary(destp: Path) -> None:
    """Rewrite an export folder's ``BACKUP_SUMMARY.md`` once its large-data copy is done.

    The corpus phase wrote the file already, before this phase started; this rewrite is
    what adds the copied files to it, so the last writer carries both halves. The corpus
    half comes from the volume manager's record of THIS folder (``backup_status_for``),
    not from whatever job it ran last. Only for a dated export folder -- the older folder
    backup dialog writes wherever the operator points it -- and never raising: see
    :func:`src.backup.export_summary.write_summary_for_export_job`.
    """
    from src.backup.export_folder import is_export_folder_name

    if not is_export_folder_name(destp.name):
        return
    try:
        from src.backup.export_summary import write_summary_for_export_job
        from src.backup.volume_job import get_volume_manager

        write_summary_for_export_job(
            destp, volume_status=get_volume_manager().backup_status_for(destp)
        )
    except Exception as exc:  # noqa: BLE001 - a summary is never worth failing a finished copy
        import logging

        log_failure(logging.getLogger(__name__), f"export summary: not rewritten after the copy into {destp}", exc, level=logging.WARNING)


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
        #: Wall-clock start of the current/last job (J1): with the volume manager's own,
        #: it tells a reopened Export dialog which completed export is the later one.
        self._started_at: float | None = None

    def _alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _on_prog(self, p: dict) -> None:
        with self._lock:
            self._progress = p

    def _start_worker(self, thread: threading.Thread) -> None:
        """Start the worker a start has just set the job to ``running`` for. Call under ``self._lock``.

        ``Thread.start()`` raises ``RuntimeError("can't start new thread")`` when the process or the machine is out of threads, and then no
        worker runs. Left alone the job stays ``running``: ``/api/jobs`` lists it with a Pause and a Cancel that act on nothing. It says
        ``error`` with the exception's CLASS (the dialog and ``resume`` both take that state, from the destination and mode the start
        recorded) and the error goes on. Only an ``Exception`` is taken (R393): an interrupt that lands while ``start()`` waits for the new
        thread leaves the OS thread created and about to run the worker."""
        try:
            thread.start()
        except Exception as exc:
            self._state = "error"
            self._error = f"{type(exc).__name__}: could not start the worker thread"
            raise

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
        # R712 (Plan's ruling): a large-data restore -- the import queue's ``blobs`` item and
        # /folder/restore alike -- is refused for the WHOLE time a backup export runs, in every
        # phase, naming it. Checked under the shared restore marker's lock, which the export's
        # own check-and-go holds too, so neither can start past the other; the worker then
        # holds the marker itself (``_run_restore``).
        gate = restore_marker.LOCK if mode == "restore" else contextlib.nullcontext()
        with gate, self._lock, storage_events.run_refusals_net(
            _RUN_OF.get(mode, ""), via="folder", refused_as=storage_events.NOT_A_FOLDER if mode in ("restore", "verify") else ()
        ):
            what = _RUN_OF.get(mode, "")  # "" for a mode that is not one: the journal records no refusal for a kind it does not have
            if mode == "restore":
                from src.backup.merge import export_refusal

                exporting = export_refusal()
                if exporting:
                    storage_events.run_refused(what, "export-running", via="folder")
                    raise RuntimeError(exporting)
            if self._alive():
                storage_events.run_refused(what, "folder-running", via="folder")
                raise RuntimeError("A folder backup is already running.")
            cats = [c for c in categories if c in _CATEGORIES] or (
                # R787 reads: a restore that names no category never places Hugging Face models; only
                # a request that names them (the person's own tick) does.
                [c for c in _CATEGORIES if c != "hf_models"] if mode == "restore" else list(_CATEGORIES)
            )
            items: list[BackupItem] = []
            if mode == "backup":
                try:
                    destp = validate_dest(dest)
                except ValueError as exc:
                    storage_events.run_refused(what, "destination-unusable", failure=type(exc).__name__, via="folder")
                    raise
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
                    # ``free_bytes`` answers 0 when the free space cannot be read: that is not a shortage, and the record says which.
                    storage_events.run_refused(
                        what, "no-space" if _free_readable(destp) else "free-space-unreadable", via="folder"
                    )
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
            self._started_at = time.time()
            target = {
                "backup": self._run_backup,
                "restore": self._run_restore,
                "verify": self._run_verify,
            }[mode]
            self._thread = threading.Thread(
                target=target, args=(destp, items, cats), daemon=True, name="folder-backup"
            )
            self._start_worker(self._thread)
            return self.status()

    def _run_backup(self, destp: Path, items: list[BackupItem], _cats: list[str]) -> None:
        # The large-data (wiki dumps / OSM regions / model blobs) half of an
        # export. Journalled on the SAME terms as the encrypted one: it copies
        # tens of GB across a drive, so "it seems to be stuck" is exactly as
        # askable here, and until now it left nothing behind either.
        with runlog.run("folder-export", label=destp.name, dest=str(destp), items=len(items)):
            # Also kept in the storage-events journal, written OPEN (a process killed in the middle leaves "started, never ended"),
            # with the free bytes of the destination it writes to: numbers and the keys of fixed tables only, never a path.
            note = storage_events.run_started("export", via="folder", files=len(items))
            # A destination that does not exist yet is made by the copy: the volume it will be made on is the one of its nearest
            # existing parent (``validate_dest`` refused a destination with none), so that is stat-ed, never a path that is not there.
            probe = _volume_probe(destp)
            if probe is not None:
                storage_events.run_free_space(note, "dest_free_bytes", probe)
            try:
                res = write_folder_backup(
                    destp, items, progress_cb=self._on_prog, should_stop=self._stop.is_set
                )
                if not res["stopped"]:
                    # BACKUP_SUMMARY.md again, now carrying the copied files too, and
                    # before "done" is published (J2) -- see _write_export_summary.
                    _write_export_summary(destp)
                with self._lock:
                    cancelled = self._cancelled  # read ONCE: the state, the run journal and the storage record must agree
                    if res["stopped"]:
                        self._state = "cancelled" if cancelled else "paused"
                    else:
                        self._state = "done"
                    self._progress = {**self._progress, **res}
                runlog.end(
                    ("cancelled" if cancelled else "paused") if res["stopped"] else "ok",
                    copied=res.get("copied"), skipped=res.get("skipped"),
                    bytes=res.get("bytes_copied"),
                )
                storage_events.run_ended(
                    note,
                    ("cancelled" if cancelled else "paused") if res["stopped"] else "ok",
                    copied=res.get("copied"), skipped=res.get("skipped"), bytes=res.get("bytes_copied"),
                )
            except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
                with self._lock:
                    self._state = "error"
                    self._error = record_text(exc)
                storage_events.run_ended(note, "error", failure=type(exc).__name__)
                raise
            finally:
                storage_events.run_ended(note, "ended-without-a-recorded-outcome")

    @restore_marker.marked  # R712: an export refuses to start or resume while this runs
    def _run_restore(self, srcp: Path, _items: list[BackupItem], cats: list[str]) -> None:
        with runlog.run("folder-import", label=srcp.name, dest=str(srcp), categories=cats):
            # No free-space figure: the files go to the live folders of each category, which can be on several volumes, and one number
            # for the data folder would read as the volume this restore writes to.
            note = storage_events.run_started("import", via="folder")
            try:
                res = restore_folder_backup(
                    srcp,
                    categories=cats,
                    targets=getattr(self, "_targets", None),
                    progress_cb=self._on_prog,
                    should_stop=self._stop.is_set,
                )
                with self._lock:
                    cancelled = self._cancelled  # read ONCE: the state, the run journal and the storage record must agree
                    if res["stopped"]:
                        self._state = "cancelled" if cancelled else "paused"
                    else:
                        self._state = "done"
                    self._progress = {**self._progress, **res}
                runlog.end(
                    ("cancelled" if cancelled else "paused") if res["stopped"] else "ok",
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
                    refused_categories=len(res.get("refused_categories") or []),
                    refused_targets=len(res.get("refused_targets") or {}),  # R784: a count, never the path
                    refused_dest_links=res.get("refused_dest_links"),
                    unread=res.get("unread_total"),
                    unread_folders=res.get("unread_folders"),
                    refused_layout=res.get("refused_layout"),
                    restored_unlisted=sum((res.get("restored_unlisted") or {}).values()),
                )
                storage_events.run_ended(
                    note,
                    ("cancelled" if cancelled else "paused") if res["stopped"] else "ok",
                    restored=res.get("restored"), skipped=res.get("skipped"),
                )
            except Exception as exc:  # noqa: BLE001
                with self._lock:
                    self._state = "error"
                    self._error = record_text(exc)
                storage_events.run_ended(note, "error", failure=type(exc).__name__)
                raise
            finally:
                storage_events.run_ended(note, "ended-without-a-recorded-outcome")

    def _run_verify(self, srcp: Path, _items: list[BackupItem], _cats: list[str]) -> None:
        # A verify is a full read of the whole set -- 1521 s of one field import
        # was verification alone -- so it belongs in the journal for the same
        # reason the copy does.
        with runlog.run("verify", label=srcp.name, dest=str(srcp)):
            note = storage_events.run_started("verify", via="folder")
            try:
                res = verify_folder_backup(
                    srcp, progress_cb=self._on_prog, should_stop=self._stop.is_set
                )
                with self._lock:
                    cancelled = self._cancelled  # read ONCE: the state, the run journal and the storage record must agree
                    if res.get("stopped"):
                        self._state = "cancelled" if cancelled else "paused"
                    else:
                        self._state = "done"
                    self._verify = res
                    self._progress = {**self._progress, "verify": res}
                checked, mismatches = _verify_counts(res)
                runlog.end(
                    ("cancelled" if cancelled else "paused") if res.get("stopped") else "ok",
                    checked=checked, mismatches=mismatches,
                )
                # The set's own verdict only for a verify that ran to its end: a stopped one has no verdict, and ``ok`` False there
                # would read as a bad set.
                storage_events.run_ended(
                    note,
                    ("cancelled" if cancelled else "paused") if res.get("stopped") else "ok",
                    checked=checked,
                    mismatches=mismatches,
                    set_ok=None if res.get("stopped") else bool(res.get("ok")),
                )
            except Exception as exc:  # noqa: BLE001 - surface the failure, never crash the thread
                with self._lock:
                    self._state = "error"
                    self._error = record_text(exc)
                storage_events.run_ended(note, "error", failure=type(exc).__name__)
                raise
            finally:
                storage_events.run_ended(note, "ended-without-a-recorded-outcome")

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

    def forget_paused(self, dest: str) -> None:
        """A PAUSED copy into ``dest`` that its owner (the backup export, R701) has cancelled
        reads ``cancelled`` from now on, so nothing offers to resume it. Nothing else changes."""
        with self._lock:
            if self._state != "paused" or self._mode != "backup" or self._dest is None or self._alive():
                return
            try:
                same = Path(self._dest).resolve() == Path(dest).resolve()
            except OSError:
                same = False
            if same:
                self._state = "cancelled"

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
                "started_at": self._started_at,
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
