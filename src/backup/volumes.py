"""Multi-volume encrypted backup codec — split a large archive into <600 MB volumes.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

A single AES-GCM call caps at ~2 GiB and needs the whole archive in RAM, so a 6 GB
corpus backup fails (field test 2026-06-24). This codec reads the archive ONCE and
slices it into independently-authenticated OOENC2 volumes (default 512 MiB plaintext,
comfortably < 600 MB), each a self-contained encrypted file, plus a manifest carrying
each volume's ciphertext SHA-256 and the whole-archive plaintext SHA-256.

Resilience (maintainer choice 2026-06-24 "volumes + parity"):
  * Each volume is independently encrypted + GCM-authenticated, so corruption is
    localised and the manifest's per-volume SHA-256 names exactly which volume is bad.
  * Distinct backup members (corpus / custody / each dump / map / model) live in
    different volumes, so a corrupt non-corpus volume never loses the corpus.
  * SLICE 2 adds Reed-Solomon erasure parity so a corrupt/lost volume — including a
    corpus volume — can be REBUILT. This module exposes the seam (``parity`` in the
    manifest, ``recover`` hook in :func:`read_volume_set`); until parity lands a corrupt
    volume is reported loudly, never silently skipped.

HONEST LIMIT carried to the UI: a database is monolithic — without parity, a corrupt
corpus volume means the corpus cannot be partially imported (other members still can).
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.backup.bounded_hash import LongerThanListed, sha256_read
from src.backup.regular_file import NotARegularFile, create_new, open_regular, replace_with
from src.safety.crypto import decrypt_file, encrypt_stream_to

MANIFEST_NAME = "volumes.json"
VOLUME_KIND = "oo-volumes-1"
# The member-streamed successor (src/backup/stream_backup.py) shares the manifest
# file name and the flat ``volumes`` list contract (so parity + verify work on
# both); load_manifest accepts either kind, the per-format readers check theirs.
_KNOWN_KINDS = (VOLUME_KIND, "oo-volumes-2")
VOLUME_SIZE_DEFAULT = 512 * 1024 * 1024  # 512 MiB plaintext/volume (< 600 MB encrypted)
_CHUNK = 4 * 1024 * 1024
_COPY_BUF = 1 << 20


class VolumeError(RuntimeError):
    """Raised when a volume set is malformed, corrupt, or fails its checksum."""


_LongerThanListed = LongerThanListed  # row 336; shared with the folder-backup check (row 342)


def member_in_use(name: str) -> str:
    """Row 156: the refusal for a staged member another program holds right now: in use, try again; never "no key opens it"."""
    return (
        f"another program is using the staged backup member {name} right now, so it could not be opened; "
        "try again in a moment"
    )


class _HashingReader:
    """Wrap an open reader so every byte consumed also updates a running hash."""

    def __init__(self, fh: Any, h: Any) -> None:  # h: a hashlib hash object
        self._fh = fh
        self._h = h

    def read(self, n: int) -> bytes:
        b = self._fh.read(n)
        self._h.update(b)
        return b


def _sha256_file(path: Path, max_bytes: int | None = None) -> str:
    """The SHA-256 of a regular file. A link, a pipe or a device raises :class:`NotARegularFile` without a byte read
    (row 312): a volume's name in a backup folder may be any of them.

    ``max_bytes`` (row 336) is the size the manifest lists: a file that holds more raises :class:`_LongerThanListed`
    after reading at most one byte past it, so a volume swapped for a huge sparse file, or one that keeps growing, is
    never hashed to its end."""
    with open_regular(path) as f:
        return sha256_read(f, max_bytes, chunk=_COPY_BUF)


def _plain_volume_name(name: object) -> bool:
    """Whether a name a manifest gives is one file directly in the set's folder: never a path (``../x``,
    ``sub/link/x``), a drive letter or a stream name. A crafted manifest is read before its names are checked
    anywhere else, so a verify that hashed ``../x`` read outside the folder (row 312)."""
    return isinstance(name, str) and name not in {"", ".", ".."} and not any(c in name for c in "/\\:\0")


def _digest_matches(path: Path, expected: object, *, max_bytes: int | None) -> bool:
    """Whether ``path`` is a regular file whose SHA-256 is ``expected``, read no further than ``max_bytes``: the size
    the manifest lists (:func:`listed_bytes`, row 336). A name that is a link, a pipe or a device is a volume that does
    not match: reported as bad, so a re-copy or parity recovery deals with it, never read (row 312). A file longer than
    listed does not match and is read at most one byte past it. A size of None (the entry lists none that is a whole
    number of bytes) does not match either: the size sits in the same manifest as the volumes, so whoever can swap in a
    huge file can also drop the size, and a missing size must not switch the bound off. Every build that writes a
    volume set has recorded ``bytes`` since the first one. Any other read error raises as before."""
    if max_bytes is None:
        return False
    try:
        return _sha256_file(path, max_bytes) == expected
    except (NotARegularFile, _LongerThanListed):
        return False


def listed_bytes(v: object) -> int | None:
    """The size a manifest entry lists for a file, or None when it lists none that is a whole number of bytes."""
    return volume_expectation(v)["expect_bytes"] if isinstance(v, dict) else None


class VolumeStopped(VolumeError):
    """Raised when a volume operation is asked to stop (``should_stop``) mid-flight.

    On a BUILD (``write_volume_set``) the partial set is incomplete and the caller
    cleans it up + marks the job cancelled. On a READ (``read_volume_set``,
    2026-07-29) nothing was published at all -- the reassembled archive only ever
    appears via the closing atomic ``os.replace``, so an aborted read leaves the
    source set untouched and no partial destination behind."""


def write_volume_set(
    src: str | os.PathLike[str],
    out_dir: str | os.PathLike[str],
    passphrase: str,
    *,
    volume_size: int = VOLUME_SIZE_DEFAULT,
    chunk_size: int = _CHUNK,
    should_stop: Callable[[], bool] | None = None,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Split ``src`` into encrypted volumes under ``out_dir`` and write the manifest.

    Streams the source once (never the whole file in RAM, no 2 GiB ceiling). Returns
    the manifest dict. ``parity`` is left ``None`` here; the caller adds it. ``should_stop``
    (checked between volumes) raises :class:`VolumeStopped`; ``progress_cb`` reports
    {phase, volumes_written, bytes_written} after each volume (for the task-manager job)."""
    if volume_size < 1024:
        raise VolumeError("volume size too small")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    whole = hashlib.sha256()
    volumes: list[dict[str, Any]] = []
    total = 0
    with open(src, "rb") as raw:
        reader = _HashingReader(raw, whole)
        idx = 1
        while True:
            if should_stop is not None and should_stop():
                raise VolumeStopped("volume backup stopped")
            vpath = out / f"vol-{idx:05d}.ooenc"
            consumed = encrypt_stream_to(
                reader, vpath, passphrase, limit=volume_size, chunk_size=chunk_size
            )
            if consumed == 0:
                # An empty trailing volume (source was an exact multiple of volume_size,
                # or the source is empty). Drop it — it carries no data.
                vpath.unlink(missing_ok=True)
                break
            volumes.append(
                {
                    "name": vpath.name,
                    "sha256": _sha256_file(vpath),
                    "bytes": vpath.stat().st_size,
                    "plaintext_bytes": consumed,
                }
            )
            total += consumed
            if progress_cb is not None:
                progress_cb(
                    {"phase": "volumes", "volumes_written": len(volumes), "bytes_written": total}
                )
            idx += 1
            if consumed < volume_size:
                break

    manifest = {
        "kind": VOLUME_KIND,
        "volume_size": volume_size,
        "chunk_size": chunk_size,
        "plaintext_bytes": total,
        "plaintext_sha256": whole.hexdigest(),
        "volumes": volumes,
        "parity": None,  # slice 2: Reed-Solomon erasure parity
    }
    # Through a temporary file and a rename: a link planted at the manifest's name in the destination is replaced, never
    # written through (row 313).
    replace_with(out / MANIFEST_NAME, json.dumps(manifest, indent=1).encode("utf-8"))
    return manifest


#: The largest manifest read. A manifest lists the volumes and the members (a name and a digest each), so a real one is far
#: smaller; the cap keeps a planted ``/dev/zero`` link or a huge file from filling memory.
MANIFEST_MAX_BYTES = 256 * 1024 * 1024


def load_manifest(out_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """The volume set's manifest. Read only when it is a REGULAR file in the folder (never a link, a FIFO or a device: a FIFO
    would block the read for ever, a link could point anywhere) and at most :data:`MANIFEST_MAX_BYTES` long."""
    import stat as _stat

    p = Path(out_dir) / MANIFEST_NAME
    try:
        st = p.lstat()
    except FileNotFoundError:
        raise VolumeError(f"no volume manifest ({MANIFEST_NAME}) in {out_dir}") from None
    except OSError as exc:  # the folder is a file, a link loop, unreadable: a refusal, never a bare OSError
        raise VolumeError(f"the volume manifest ({MANIFEST_NAME}) in {out_dir} cannot be examined ({type(exc).__name__})") from None
    if not _stat.S_ISREG(st.st_mode):
        raise VolumeError(f"the volume manifest ({MANIFEST_NAME}) in {out_dir} is not a regular file (a link or a device is never read)")
    if st.st_size > MANIFEST_MAX_BYTES:
        raise VolumeError(f"the volume manifest ({MANIFEST_NAME}) in {out_dir} is larger than {MANIFEST_MAX_BYTES} bytes")
    # O_NOFOLLOW and O_NONBLOCK exist on POSIX only; O_BINARY on Windows only (without it a Windows descriptor opens in
    # TEXT mode, which turns CRLF into LF and stops at a Ctrl-Z byte).
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(p, flags)
    except OSError as exc:  # swapped for a link after the lstat (ELOOP), or gone: refused
        raise VolumeError(f"the volume manifest ({MANIFEST_NAME}) in {out_dir} cannot be opened ({type(exc).__name__})") from None
    try:
        # Checked on the raw descriptor, before any file object exists, so a refusal still closes it (a directory swapped in
        # after the lstat opens on Linux and would make fdopen raise with the descriptor left open).
        fst = os.fstat(fd)
        if not _stat.S_ISREG(fst.st_mode):
            raise VolumeError(f"the volume manifest ({MANIFEST_NAME}) in {out_dir} is not a regular file")
        # The file OPENED is the file EXAMINED. Where there is no O_NOFOLLOW (Windows), this is what refuses a name swapped for
        # a link between the lstat and the open: the link's target is another file. A filesystem that reports no inode (0)
        # cannot be compared and is read as before. lstat and fstat come from different Windows calls, which on FAT/exFAT or
        # an SMB share may give the same file's identity at different widths, so a mismatch is confirmed by a second look at
        # the NAME: refused only when it is no longer the regular file first examined.
        if (st.st_ino and fst.st_ino) and (fst.st_dev, fst.st_ino) != (st.st_dev, st.st_ino):
            try:
                again = p.lstat()
            except OSError:
                again = None
            if again is None or not _stat.S_ISREG(again.st_mode) or (again.st_dev, again.st_ino) != (st.st_dev, st.st_ino):
                raise VolumeError(f"the volume manifest ({MANIFEST_NAME}) in {out_dir} changed while it was being opened")
        if fst.st_size > MANIFEST_MAX_BYTES:
            raise VolumeError(f"the volume manifest ({MANIFEST_NAME}) in {out_dir} is larger than {MANIFEST_MAX_BYTES} bytes")
        # Read as it is: O_NONBLOCK changes nothing for a regular file, so the descriptor is never switched back to blocking.
        # ``os.set_blocking`` was called here, and on Windows it works on pipes only: every manifest read there failed
        # (row 124, the Windows observation leg).
        with os.fdopen(fd, "rb", closefd=False) as fh:
            raw = fh.read(MANIFEST_MAX_BYTES + 1)
    except OSError as exc:
        raise VolumeError(f"the volume manifest ({MANIFEST_NAME}) in {out_dir} cannot be read ({type(exc).__name__})") from None
    finally:
        os.close(fd)
    if len(raw) > MANIFEST_MAX_BYTES:
        raise VolumeError(f"the volume manifest ({MANIFEST_NAME}) in {out_dir} is larger than {MANIFEST_MAX_BYTES} bytes")
    m = json.loads(raw.decode("utf-8"))
    if m.get("kind") not in _KNOWN_KINDS:
        raise VolumeError(f"not an Open Omniscience volume set (kind={m.get('kind')!r})")
    return m


def verify_volume_set(
    out_dir: str | os.PathLike[str],
    *,
    progress_cb: Callable[[dict[str, Any]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Check every volume's ciphertext SHA-256 against the manifest WITHOUT decrypting.

    Returns ``{ok, bad, missing, total, checked}`` — ``bad`` names volumes that are
    missing or whose bytes no longer match (corruption/bit-rot), the exact set a
    re-copy or (slice 2) parity recovery must address.

    ``progress_cb`` and ``should_stop`` exist for Q218's verify-after-write, which
    re-reads every byte of a multi-gigabyte set off a removable drive: without
    progress that pass reads as a hang at 100%, and without a stop the operator
    cannot cancel the slowest part of their own export. ``should_stop`` raises
    :class:`VolumeStopped` — the CALLER decides what a cancelled verification means,
    because after a successful write it means "not re-read", never "not written".

    ``checked`` counts the volumes actually hashed, so a stopped run cannot be
    mistaken for a complete one by a reader who only looks at ``bad``."""
    m = load_manifest(out_dir)
    out = Path(out_dir)
    bad: list[str] = []
    missing: list[str] = []
    total = len(m["volumes"])
    checked = 0
    for v in m["volumes"]:
        if should_stop is not None and should_stop():
            raise VolumeStopped("stopped while verifying the volume set")
        if not _plain_volume_name(v.get("name") if isinstance(v, dict) else None):
            bad.append(str(v.get("name") if isinstance(v, dict) else v))  # never joined to the folder, never read
            checked += 1
            continue
        p = out / v["name"]
        if not p.exists():
            bad.append(v["name"])
            missing.append(v["name"])
        elif not _digest_matches(p, v.get("sha256"), max_bytes=listed_bytes(v)):
            bad.append(v["name"])
        checked += 1
        if progress_cb is not None:
            progress_cb(
                {"phase": "verifying", "volumes_verified": checked, "volumes_total": total}
            )
    return {
        "ok": not bad,
        "bad": bad,
        "missing": missing,
        "total": total,
        "checked": checked,
    }


def volume_expectation(v: dict[str, Any]) -> dict[str, Any]:
    """The digest and size a decrypt holds a volume to (row 329), from its manifest entry: the ones the checksum pass
    checked. A missing digest is ``""`` (no file matches it, so the volume is refused); a size that is not a whole
    number of bytes is no bound."""
    n = v.get("bytes")
    size = n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else None
    return {"expect_sha256": str(v.get("sha256") or ""), "expect_bytes": size}


def require_unique_volumes(names: Any) -> None:
    """Refuse a manifest that names one volume twice (R686): read twice, it is written twice, and no
    size the manifest declares bounds that."""
    seen: set[str] = set()
    for name in names:
        n = str(name or "")
        # FAT, exFAT, NTFS and APFS treat names that differ only by case or by a trailing dot or space as one file.
        key = n.casefold().rstrip(". ")
        if key in seen:
            raise VolumeError(f"the volume manifest lists the volume {n} more than once; refusing to restore from it")
        seen.add(key)


def remove_leftover_plaintext(out_dir: str | os.PathLike[str], names: list[str]) -> dict[str, list[str]]:
    """Remove the named leftover plaintext copies, and only those the folder's manifest explains (R686).

    Called only when the operator asked for it: nothing of ours deletes from a backup drive on its own. A name
    that is not a current leftover is ignored. Answers ``{"removed": [...], "failed": [...]}`` by file name, so a
    copy the system would not let go of (a file open elsewhere on Windows) is named and the rest still go.

    Where the platform allows it the folder is opened once without following a link and each copy is removed
    relative to that handle, so a folder swapped for a link between the check and the removal cannot redirect it."""
    from src.backup.import_scan import (
        can_scan_by_handle,
        leftover_plaintext,
        leftovers_in_handle,
        looks_like_leftover,
        open_folder_handle,
    )

    removed: list[str] = []
    failed: list[str] = []
    if can_scan_by_handle() and os.unlink in os.supports_dir_fd:
        # One handle for the scan and the removal: what is checked is what is removed (R692).
        try:
            dir_fd = open_folder_handle(out_dir)
        except OSError:
            # The folder cannot be opened, so nothing can be checked or removed: every name shaped like a leftover
            # copy is reported as not removed, never silently dropped, so the operator knows the copies may remain.
            return {"removed": [], "failed": [n for n in dict.fromkeys(names) if looks_like_leftover(n)]}
        try:
            allowed = set(leftovers_in_handle(dir_fd))
            for name in [n for n in dict.fromkeys(names) if n in allowed]:
                try:
                    os.unlink(name, dir_fd=dir_fd)
                    removed.append(name)
                except FileNotFoundError:
                    continue
                except OSError:
                    failed.append(name)
        finally:
            os.close(dir_fd)
        return {"removed": removed, "failed": failed}
    # Windows: no folder handles. The loop walks the SCAN's own names and keeps those asked for (in the order asked),
    # so the name joined to the folder is always one the scan found, never text from the request.
    wanted = list(dict.fromkeys(names))
    for name in sorted((n for n in leftover_plaintext(out_dir) if n in wanted), key=wanted.index):
        try:
            # os.unlink, the one call both branches make (Path.unlink reaches os through pathlib, past this module's own os).
            os.unlink(Path(out_dir) / name)
            removed.append(name)
        except FileNotFoundError:
            continue
        except OSError:
            failed.append(name)
    return {"removed": removed, "failed": failed}


def read_volume_set(
    out_dir: str | os.PathLike[str],
    passphrase: str,
    dest: str | os.PathLike[str],
    *,
    recover: Callable[[dict[str, Any], list[str]], list[str]] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Verify, (optionally) recover, then decrypt + reassemble the archive into ``dest``.

    Reassembly is streamed (a volume at a time, never the whole archive in RAM) and the
    result is checked against the manifest's whole-archive plaintext SHA-256, so a silent
    mis-reassembly is impossible. If volumes are corrupt and ``recover`` cannot repair
    them, raises :class:`VolumeError` naming exactly which volumes failed.

    ``recover`` is the slice-2 parity hook: given the manifest and the bad-volume list it
    rebuilds them on disk and returns the volumes it could NOT repair.

    ``should_stop`` (2026-07-29, ruling item 15 "stop is IMMEDIATE"): polled before
    each volume. Reassembling a large set is one of the longest phases of an import,
    so a Stop that could not reach it would leave the operator waiting out the very
    work they cancelled. Raises :class:`VolumeStopped`; the half-written ``dest`` is
    a ``.reassembling`` temp that the ``finally`` below removes, so an aborted
    reassembly leaves NO partial archive anywhere -- the atomic ``os.replace`` at the
    end is the only thing that ever publishes one."""
    m = load_manifest(out_dir)
    if m.get("kind") != VOLUME_KIND:
        raise VolumeError(
            f"this is an {m.get('kind')!r} member-streamed set — read it with "
            "src.backup.stream_backup.read_stream_backup (the volume restore "
            "dispatches automatically)"
        )
    out = Path(out_dir)
    # Before anything is read or repaired (R686): plain volume names, each volume once (by name the way the disk
    # compares names, never through a link, never two names for one file), and a real declared size to bound by.
    from src.backup.stream_backup import _require_each_volume_read_once, _require_safe_volume_name

    for v in m.get("volumes") or []:
        _require_safe_volume_name(str((v or {}).get("name") or ""))
    _require_each_volume_read_once(m, out)
    declared = m.get("plaintext_bytes")
    if isinstance(declared, bool) or not isinstance(declared, int) or declared <= 0:
        raise VolumeError("the volume manifest declares no plaintext size; refusing to reassemble an unbounded archive")
    status = verify_volume_set(out_dir)
    if status["bad"]:
        if recover is not None:
            unrepaired = recover(m, status["bad"])
        elif m.get("parity"):
            # Auto-recover from Reed-Solomon parity (slice 2). Lazy import so the volume
            # codec keeps NO hard dependency on parity/numpy (a core install is volumes-only).
            from src.backup.parity import recover_volumes

            unrepaired = recover_volumes(m, status["bad"], out_dir=out_dir)
        else:
            unrepaired = status["bad"]
        if unrepaired:
            raise VolumeError(
                "corrupt or missing volumes that could not be recovered: "
                + ", ".join(sorted(unrepaired))
            )

    # Free space for what is really written: the archive itself plus ONE decrypted volume at a time,
    # which a volume's ciphertext size bounds from above (R686).
    from src.backup.artifact import preflight_free_space

    largest = max((((out / v["name"]).stat().st_size) for v in m["volumes"]), default=0)
    preflight_free_space(Path(dest).parent, declared + largest, what="restore staging")

    whole = hashlib.sha256()
    written = 0
    tmp = Path(dest).with_name(Path(dest).name + ".reassembling")
    try:
        # Never through a link at the working copy's name (row 313); owner-only, as it is the whole plaintext archive (R829 B).
        with create_new(tmp, mode=0o600) as outf:
            for v in m["volumes"]:
                if should_stop is not None and should_stop():
                    raise VolumeStopped("stopped while reassembling the backup")
                # The decrypted working copy goes beside ``dest`` (the restore's own staging, on the app's data volume,
                # removed with it), NEVER into the backup's folder: a crash there left plaintext on the user's backup
                # drive, where nothing of ours would ever clean it up (R686).
                vtmp = Path(dest).with_name(f".{v['name']}.{secrets.token_hex(4)}.plain")
                try:
                    # Never through a link, and only bytes whose checksum is the one the check above found (row 329).
                    decrypt_file(
                        out / v["name"], vtmp, passphrase, follow_links=False, mode=0o600, **volume_expectation(v)
                    )
                    with open(vtmp, "rb") as vf:
                        while True:
                            blk = vf.read(_COPY_BUF)
                            if not blk:
                                break
                            written += len(blk)
                            if written > declared:
                                raise VolumeError(
                                    "the backup's volumes hold more data than its manifest declares; refusing to go on"
                                )
                            outf.write(blk)
                            whole.update(blk)
                finally:
                    vtmp.unlink(missing_ok=True)
        if whole.hexdigest() != m["plaintext_sha256"]:
            raise VolumeError("the reassembled archive failed its plaintext checksum")
        os.replace(tmp, dest)
    finally:
        tmp.unlink(missing_ok=True)
    return {"plaintext_bytes": m["plaintext_bytes"], "volumes": len(m["volumes"])}
