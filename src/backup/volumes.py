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
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.safety.crypto import decrypt_file, encrypt_stream_to

MANIFEST_NAME = "volumes.json"
VOLUME_KIND = "oo-volumes-1"
VOLUME_SIZE_DEFAULT = 512 * 1024 * 1024  # 512 MiB plaintext/volume (< 600 MB encrypted)
_CHUNK = 4 * 1024 * 1024
_COPY_BUF = 1 << 20


class VolumeError(RuntimeError):
    """Raised when a volume set is malformed, corrupt, or fails its checksum."""


class _HashingReader:
    """Wrap an open reader so every byte consumed also updates a running hash."""

    def __init__(self, fh: Any, h: Any) -> None:  # h: a hashlib hash object
        self._fh = fh
        self._h = h

    def read(self, n: int) -> bytes:
        b = self._fh.read(n)
        self._h.update(b)
        return b


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(_COPY_BUF), b""):
            h.update(blk)
    return h.hexdigest()


def write_volume_set(
    src: str | os.PathLike[str],
    out_dir: str | os.PathLike[str],
    passphrase: str,
    *,
    volume_size: int = VOLUME_SIZE_DEFAULT,
    chunk_size: int = _CHUNK,
) -> dict[str, Any]:
    """Split ``src`` into encrypted volumes under ``out_dir`` and write the manifest.

    Streams the source once (never the whole file in RAM, no 2 GiB ceiling). Returns
    the manifest dict. ``parity`` is left ``None`` here; slice 2 computes it."""
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
    (out / MANIFEST_NAME).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest


def load_manifest(out_dir: str | os.PathLike[str]) -> dict[str, Any]:
    p = Path(out_dir) / MANIFEST_NAME
    if not p.exists():
        raise VolumeError(f"no volume manifest ({MANIFEST_NAME}) in {out_dir}")
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("kind") != VOLUME_KIND:
        raise VolumeError(f"not an Open Omniscience volume set (kind={m.get('kind')!r})")
    return m


def verify_volume_set(out_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Check every volume's ciphertext SHA-256 against the manifest WITHOUT decrypting.

    Returns ``{ok, bad, missing, total}`` — ``bad`` names volumes that are missing or
    whose bytes no longer match (corruption/bit-rot), the exact set a re-copy or (slice
    2) parity recovery must address."""
    m = load_manifest(out_dir)
    out = Path(out_dir)
    bad: list[str] = []
    missing: list[str] = []
    for v in m["volumes"]:
        p = out / v["name"]
        if not p.exists():
            bad.append(v["name"])
            missing.append(v["name"])
        elif _sha256_file(p) != v["sha256"]:
            bad.append(v["name"])
    return {"ok": not bad, "bad": bad, "missing": missing, "total": len(m["volumes"])}


def read_volume_set(
    out_dir: str | os.PathLike[str],
    passphrase: str,
    dest: str | os.PathLike[str],
    *,
    recover: Callable[[dict[str, Any], list[str]], list[str]] | None = None,
) -> dict[str, Any]:
    """Verify, (optionally) recover, then decrypt + reassemble the archive into ``dest``.

    Reassembly is streamed (a volume at a time, never the whole archive in RAM) and the
    result is checked against the manifest's whole-archive plaintext SHA-256, so a silent
    mis-reassembly is impossible. If volumes are corrupt and ``recover`` cannot repair
    them, raises :class:`VolumeError` naming exactly which volumes failed.

    ``recover`` is the slice-2 parity hook: given the manifest and the bad-volume list it
    rebuilds them on disk and returns the volumes it could NOT repair."""
    m = load_manifest(out_dir)
    out = Path(out_dir)
    status = verify_volume_set(out_dir)
    if status["bad"]:
        unrepaired = recover(m, status["bad"]) if recover else status["bad"]
        if unrepaired:
            raise VolumeError(
                "corrupt or missing volumes that could not be recovered: "
                + ", ".join(sorted(unrepaired))
            )

    whole = hashlib.sha256()
    tmp = Path(dest).with_name(Path(dest).name + ".reassembling")
    try:
        with open(tmp, "wb") as outf:
            for v in m["volumes"]:
                vtmp = out / (v["name"] + ".plain")
                try:
                    decrypt_file(out / v["name"], vtmp, passphrase)
                    with open(vtmp, "rb") as vf:
                        while True:
                            blk = vf.read(_COPY_BUF)
                            if not blk:
                                break
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
