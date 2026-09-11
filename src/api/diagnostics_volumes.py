"""Split a finished diagnostics archive into size-bounded, independently-openable ZIPs.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY THIS EXISTS (field session 2026-09-11, maintainer-reported). The all-diagnostics
archive is the maintainer->developer channel, and it had outgrown the channel: the
bundle would not upload, and neither would ``keyword-log-digest.json`` extracted and
re-zipped on its own. The evidence for a diagnosis could not reach the person making
it -- which makes the archive's size a correctness problem, not an ergonomics one.

The cap on the digest itself (shipped separately) fixes the one member that had no
ceiling. This module fixes the SHAPE: whatever the bundle grows to, it can be handed
over in pieces that each fit an attachment limit.

WHAT THIS IS NOT. It deliberately does NOT reuse :mod:`src.backup.volumes`, despite
solving a similar-sounding problem, and the difference is the whole point. That codec
slices one ciphertext stream into encrypted volumes that must ALL be present and
reassembled before a single byte is readable -- correct for a backup, useless here,
because an analyst handed volume 3 of 5 could open nothing at all. This one packs
WHOLE MEMBERS into plain zips: every volume opens in any unzip tool, on its own,
today, and the members inside it are complete and readable. What is borrowed is the
manifest SHAPE (``kind`` + a flat ``volumes`` list of ``{name, sha256, bytes}`` + a
set-completeness check returning ``{ok, bad, missing, total}``), so an operator who
has verified a backup volume set already knows how to read this one.

THE ONE CASE THAT CANNOT BE PACKED, and how it is handled rather than hidden. A
single member can be larger than the whole per-volume budget. Bin-packing has no
answer for that, and the two dishonest answers are to drop it or to quietly emit an
over-cap volume and let the upload fail again at the other end. So such a member is
SPLIT BY BYTES across consecutive volumes as ``<name>.partNNNNofMMMM`` entries, each
volume stays under the cap, and the manifest says -- per member and in prose -- that
this one needs reassembly and exactly how (concatenate the parts in order; see
:func:`reassemble_split_members`). Every other member in those same volumes is still
whole and directly readable. A split member is the exception the manifest NAMES, not
a silent property of the set.

TWO DESCRIPTORS, AND WHY IT IS NOT ONE. A file cannot contain its own SHA-256, so a
single manifest carrying both the per-volume checksums and a copy inside every volume
is not a design choice, it is a contradiction -- the first attempt at this module
wrote the checksums, appended the manifest, and thereby invalidated every checksum it
had just recorded. So the two jobs are separated by name:

  * ``volumes-readme.json``, inside EVERY volume -- the set's SHAPE (how many volumes,
    how they are named, which members are split and how to rejoin them) plus THIS
    volume's own contents. A reader holding ONE volume can still answer "what am I
    missing, and what are the missing ones called?". Everything in it is bounded by what
    the volume already holds, which is not a style preference: the first version embedded
    the whole set's cross-volume member map, that map GROWS as the cap shrinks, and at a
    20 KB cap it made every one of 2164 volumes 39 KB -- the index alone twice the cap.
    It carries no checksums, and says where they are.
  * ``volumes.json``, a sidecar BESIDE the volumes -- the full cross-volume member map,
    plus each volume's SHA-256 and byte count, which is what :func:`verify_volume_set`
    checks. It is the only descriptor that grows with the set, and it never has to fit
    inside one.

ORDERING is deliberate: ``manifest.json`` (and the bundle journal) are placed FIRST,
in volume 1, because they are what tells a reader what the run did. A reader who
receives only the first volume still learns the shape of the whole run.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import zipfile
from pathlib import Path
from typing import Any

MANIFEST_NAME = "volumes.json"
README_NAME = "volumes-readme.json"
VOLUME_KIND = "oo-diagnostics-volumes-1"

# Members written into volume 1 ahead of everything else, in this order, when present.
# These are the "what is this and what ran" files; a reader holding only the first
# volume should still be able to answer both questions.
_FIRST_MEMBERS = ("manifest.json", "bundle-journal.jsonl")

# Per-volume overhead that is NOT member payload: the zip central directory, per-entry
# headers, and the readme written into every volume. Reserved out of the cap so a volume
# packed right up to the budget still lands UNDER it rather than a few hundred bytes over
# -- the exact failure this module exists to prevent.
_ZIP_OVERHEAD_MAX = 64 * 1024

# Per-entry zip structure charged to a member: local file header (30 B) + central
# directory entry (46 B) + the filename stored twice, rounded up generously. Small, but
# a bundle is dozens of members and the reserve should not be silently spending itself.
_PER_ENTRY_OVERHEAD = 256

# How many times the reserve may be re-solved before the cap is declared too small.
_RESERVE_ROUNDS = 5


def _overhead_reserve(cap: int) -> int:
    """Bytes held back from ``cap`` for zip structure and the readme.

    SCALED, not a constant: a flat 64 KiB reserve is right at the 9 MB default and
    catastrophic below it -- at a 52 KB cap it exceeds the cap outright, collapsing the
    budget to 1 byte and shattering every member into thousands of parts. That is not a
    hypothetical: it is what the first draft of this module did, found by running it.
    """
    return max(1024, min(_ZIP_OVERHEAD_MAX, cap // 8))


class VolumeError(RuntimeError):
    """Raised when a diagnostics volume set is malformed or incomplete."""


def volume_max_bytes() -> int:
    """The per-volume ceiling, env-tunable via ``OO_DIAG_VOLUME_MAX_MB``.

    Default 9 MB, matching ``_keyword_zip_max_bytes`` for the same reason: it keeps a
    volume UNDER the common 10 MB attachment limit that the maintainer actually hit.
    """
    try:
        mb = float(os.environ.get("OO_DIAG_VOLUME_MAX_MB", "9"))
    except ValueError:
        mb = 9.0
    # Floored at 4 KiB only to forbid a zero/negative cap. The small floor is what
    # makes the split-member path testable without generating a 9 MB fixture.
    return max(4096, int(mb * 1024 * 1024))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(1 << 20), b""):
            h.update(blk)
    return h.hexdigest()


def _part_name(name: str, idx: int, total: int) -> str:
    """``foo.json`` part 2 of 3 -> ``foo.json.part0002of0003``.

    THE PAD WIDTH FOLLOWS ``total``, and a fixed one was a silent corruption bug found
    by running this at its smallest cap. At 4 digits, part 10000 is written ``10000``
    while part 9999 is ``9999``, and ``"10000" < "9999"`` lexicographically -- so a
    member of 10,000+ parts reassembled in the WRONG ORDER, under both the shell glob
    this module documents (``cat <name>.part* > <name>``) and its own reader. Nothing
    would have reported it: the checksums cover the volumes, not the rejoined member.

    Minimum 4 so the common case keeps its familiar shape.
    """
    width = max(4, len(str(total)))
    return f"{name}.part{idx:0{width}d}of{total:0{width}d}"


def plan_volumes(
    entries: list[tuple[str, int, int]], *, cap: int, reserve: int | None = None
) -> list[list[tuple[str, int, int, int, bool]]]:
    """Assign ``entries`` to volumes so no volume exceeds ``cap`` bytes.

    ``entries`` is ``[(name, cost, raw)]`` in the order they should be considered --
    ``cost`` is what the member costs a volume once DEFLATED, ``raw`` its uncompressed
    length. The return is one list per volume of
    ``(entry_name, offset, length, part_of, stored)``: ``part_of`` is 0 for a whole
    member and the total part count for a split one, and ``stored`` asks the writer for
    ZIP_STORED rather than deflate.

    PACKING ON THE DEFLATED COST is the difference between a usable set and a useless
    one. Diagnostics members are JSON and logs, which compress about 8x; packing on raw
    bytes would emit roughly eight times more volumes than the cap requires, each one
    about an eighth full, for an operator who is splitting the archive precisely because
    sending things is the hard part.

    THE SPLIT PATH IS THE EXCEPTION AND IS DELIBERATELY UNCOMPRESSED. A member whose
    deflated cost exceeds a whole empty volume is cut into raw byte slices STORED
    without compression, so a slice's cost to a volume is exactly its length and the
    arithmetic is exact rather than a prediction about how a fragment will compress.
    Two alternatives were rejected: slicing raw bytes and hoping each part deflates
    small enough can emit a volume over the cap, which is the one outcome this module
    exists to prevent; and slicing the member's DEFLATE STREAM would make the parts
    concatenate into a compressed blob rather than the original file, breaking the plain
    ``cat <name>.part* > <name>`` promise the manifest makes. Bigger set, exact bound,
    directly usable parts -- and only for a member that is already an outlier.

    PURE and separately testable on purpose: the packing decision holds the interesting
    edge cases (a zero-byte member, one exactly at the budget, one many times it), and
    those should be checkable without writing a single zip to disk.

    First-fit in the GIVEN order rather than largest-first: the caller's order carries
    meaning (orientation files first), and a packer that reordered to save a volume
    would scatter a reader's bearings to save a file. A member that does not fit the
    current volume but would fit an empty one starts the next volume whole; each part of
    a split member occupies a volume alone, so part N is always in volume (first + N-1).
    """
    if cap <= 0:
        raise ValueError("cap must be positive")
    budget = max(1, cap - (_overhead_reserve(cap) if reserve is None else reserve))
    vols: list[list[tuple[str, int, int, int, bool]]] = []
    cur: list[tuple[str, int, int, int, bool]] = []
    used = 0

    def _flush() -> None:
        nonlocal cur, used
        if cur:
            vols.append(cur)
            cur = []
            used = 0

    for name, cost, raw in entries:
        if cost <= budget:
            if used + cost > budget:
                _flush()
            cur.append((name, 0, raw, 0, False))
            used += cost
            continue
        _flush()
        nparts = max(1, -(-raw // budget))  # ceil
        off = 0
        for i in range(nparts):
            length = min(budget, raw - off)
            cur.append((_part_name(name, i + 1, nparts), off, length, nparts, True))
            off += length
            _flush()
    _flush()
    return vols


def _deflated_cost(data: bytes) -> int:
    """What ``data`` will cost a volume once deflated, plus its per-entry zip headers.

    MEASURED, not estimated from a ratio: the members differ wildly (a JSON log at 10x,
    an already-compressed payload at 1x), and a ratio wrong in the optimistic direction
    produces a volume over the cap. ``zlib`` at level 9 with ``wbits=-15`` is the raw
    deflate stream ``zipfile`` stores, so this is the real number rather than a proxy.
    """
    import zlib

    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    n = len(co.compress(data)) + len(co.flush())
    # Local file header (30 B) + central directory entry (46 B) + the name twice, plus
    # slack. Counted because a volume of many small members is structure, not payload.
    return n + _PER_ENTRY_OVERHEAD


def _ordered_entries(src: zipfile.ZipFile) -> list[tuple[str, int, int]]:
    """Archive members as ``(name, deflated_cost, raw_bytes)``, orientation files first.

    Reads and compresses every member once to measure it. That doubles the work of a
    split (measure, then write), which is the price of a volume set that is actually
    under its cap rather than predicted to be.
    """
    infos = {i.filename: i for i in src.infolist() if not i.is_dir()}
    names = [n for n in _FIRST_MEMBERS if n in infos]
    names += [n for n in infos if n not in _FIRST_MEMBERS]
    out: list[tuple[str, int, int]] = []
    for n in names:
        data = src.read(n)
        out.append((n, _deflated_cost(data), len(data)))
    return out


def _set_note(nvols: int, split: list[str], cap: int) -> str:
    lines = [
        f"The all-diagnostics archive, split into {nvols} independently-openable ZIP "
        f"volume(s) of at most {cap} bytes each, so it can be sent through a channel "
        "with an attachment limit.",
        f"Every volume opens on its own in any unzip tool. {README_NAME} (present in "
        "every volume) lists the whole set and which volume carries each member; it "
        f"carries no checksums, because a file cannot contain its own hash -- those "
        f"are in the {MANIFEST_NAME} sidecar written beside the volumes.",
    ]
    if split:
        lines.append(
            "ONE OR MORE MEMBERS ARE SPLIT and are NOT readable from a single volume: "
            + ", ".join(sorted(split))
            + ". Each is stored as <name>.partNNNNofMMMM entries in consecutive "
            "volumes; extract every part and concatenate them in part order to rebuild "
            "the original file (shell: cat <name>.part* > <name>). Every OTHER member "
            "in those same volumes is whole and directly readable."
        )
    else:
        lines.append("No member is split: every member is complete inside one volume.")
    return " ".join(lines)


class _SliceReader:
    """Serves ``(member, offset, length)`` slices from an archive, reading each member
    at most once when the slices arrive in order.

    A ``ZipExtFile`` over a deflated member is not reliably seekable across the Python
    versions this app supports, so reaching offset N means decompressing N bytes. Doing
    that per part makes a split QUADRATIC in the number of parts: measured here, a
    3 MB member at a small cap spent minutes re-decompressing the same bytes, and a
    19 MB one did not finish. Since :func:`plan_volumes` emits a split member's parts in
    consecutive order, keeping the reader open turns that back into one linear pass.

    The out-of-order case is still CORRECT, just slow -- it reopens and skips forward.
    Correctness does not depend on the caller's ordering; only speed does.
    """

    def __init__(self, src: zipfile.ZipFile) -> None:
        self._src = src
        self._name: str | None = None
        self._fh: Any = None
        self._pos = 0

    def _close(self) -> None:
        if self._fh is not None:
            self._fh.close()
        self._fh = None
        self._name = None
        self._pos = 0

    def read(self, name: str, off: int, length: int) -> bytes:
        if self._name != name or self._pos > off:
            self._close()
            self._fh = self._src.open(name)
            self._name = name
            self._pos = 0
        while self._pos < off:
            got = self._fh.read(min(1 << 20, off - self._pos))
            if not got:
                break
            self._pos += len(got)
        data = self._fh.read(length)
        self._pos += len(data)
        return data

    def __enter__(self) -> _SliceReader:
        return self

    def __exit__(self, *exc: Any) -> None:
        self._close()


def _volume_name(stem: str, idx: int, total: int) -> str:
    return f"{stem}.{idx:03d}of{total:03d}.zip"


def _plan_and_names(src: zipfile.ZipFile, cap: int, stem: str, reserve: int):
    plan = plan_volumes(_ordered_entries(src), cap=cap, reserve=reserve)
    nvols = len(plan)
    names = [_volume_name(stem, i, nvols) for i in range(1, nvols + 1)]
    members = [
        {
            "name": entry.rsplit(".part", 1)[0] if part_of else entry,
            "entry": entry,
            "volume": vi,
            "bytes": length,
            "part_of": part_of,
            "stored_uncompressed": stored,
        }
        for vi, vol in enumerate(plan, start=1)
        for (entry, _off, length, part_of, stored) in vol
    ]
    return plan, names, members


def _readme_for(
    *, vi: int, nvols: int, stem: str, src_path: Path, cap: int, members, split_members
) -> str:
    """The orientation document carried INSIDE volume ``vi``.

    BOUNDED BY CONSTRUCTION, and that is not a style preference -- it is the fix for a
    measured defect. The first version embedded the whole set's member map in every
    volume. That map grows as the cap SHRINKS (more volumes, more part entries), so at a
    20 KB cap every one of 2164 volumes came out at 39 KB: the readme alone was double
    the cap, and the module's single guarantee was false in exactly the regime it was
    meant for. So a volume now carries the set's SHAPE (how many volumes, how they are
    named, which members are split) plus ITS OWN contents -- all bounded by what is
    already in the volume -- and the full cross-volume map lives only in the sidecar.

    A reader holding one volume still answers both questions that matter: what am I
    missing, and what are the missing ones called.
    """
    mine = [m for m in members if m["volume"] == vi]
    return json.dumps(
        {
            "kind": VOLUME_KIND,
            "source": src_path.name,
            "volume_max_bytes": cap,
            "volume_index": vi,
            "volume_count": nvols,
            "volume_name": _volume_name(stem, vi, nvols),
            "volume_name_pattern": _volume_name(stem, 0, nvols).replace(
                ".000of", ".NNNof"
            ),
            "members_in_this_volume": mine,
            "split_members": split_members,
            "full_member_map": (
                f"not here -- it grows with the volume count; see {MANIFEST_NAME} "
                "written beside the volumes"
            ),
            "checksums": (
                f"not here -- a file cannot contain its own hash; see {MANIFEST_NAME} "
                "written beside the volumes"
            ),
            "note": _set_note(nvols, split_members, cap),
        },
        ensure_ascii=False,
        indent=2,
    )


def write_volume_set(
    src_zip: str | os.PathLike[str],
    out_dir: str | os.PathLike[str],
    *,
    cap: int | None = None,
    stem: str = "oo-all-diagnostics",
) -> dict[str, Any]:
    """Split the finished archive ``src_zip`` into capped volumes under ``out_dir``.

    Returns the sidecar manifest. The source archive is only READ -- it stays where it
    is and keeps working as the single-file download, so this is an additional way to
    collect the same evidence, never a replacement that could strand it.

    THE RESERVE IS SOLVED, NOT GUESSED. Each volume carries a readme whose size depends
    on the plan, and the plan depends on how much room the readme leaves: a circle. It
    is closed by measuring rather than by estimating -- plan, build the readmes, measure
    the largest, and if it does not fit the reserve, re-plan with a reserve that holds
    it, up to a few rounds. Then, whatever the arithmetic concluded, every written
    volume is CHECKED against the cap and the whole set is refused if one is over. A
    volume over the cap is the one outcome this module exists to prevent, so it is
    verified against the bytes on disk instead of trusted to the planner.
    """
    cap = volume_max_bytes() if cap is None else cap
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    src_path = Path(src_zip)

    with zipfile.ZipFile(src_path) as src:
        reserve = _overhead_reserve(cap)
        for _round in range(_RESERVE_ROUNDS):
            plan, names, members = _plan_and_names(src, cap, stem, reserve)
            split_members = sorted({m["name"] for m in members if m["part_of"]})
            readmes = [
                _readme_for(
                    vi=vi, nvols=len(names), stem=stem, src_path=src_path, cap=cap,
                    members=members, split_members=split_members,
                )
                for vi in range(1, len(names) + 1)
            ]
            need = max(_deflated_cost(r.encode()) for r in readmes) + _PER_ENTRY_OVERHEAD
            if need <= reserve:
                break
            # Grow past what is needed so the next round's slightly different plan does
            # not tip straight back over; converges in one or two rounds in practice.
            reserve = min(cap - 1, int(need * 1.5) + _PER_ENTRY_OVERHEAD)
        else:
            raise VolumeError(
                f"cap of {cap} B is too small: a volume's own index needs {need} B. "
                "Raise OO_DIAG_VOLUME_MAX_MB."
            )

        with _SliceReader(src) as reader:
            for vi, (vol, vname) in enumerate(zip(plan, names, strict=True), start=1):
                with zipfile.ZipFile(
                    out / vname, "w", zipfile.ZIP_DEFLATED, compresslevel=9
                ) as z:
                    z.writestr(README_NAME, readmes[vi - 1])
                    for entry, off, length, part_of, stored in vol:
                        base = entry.rsplit(".part", 1)[0] if part_of else entry
                        payload = reader.read(base, off, length)
                        if stored:
                            z.writestr(entry, payload, compress_type=zipfile.ZIP_STORED)
                        else:
                            z.writestr(entry, payload)

    volumes = [
        {"name": n, "sha256": _sha256_file(out / n), "bytes": (out / n).stat().st_size}
        for n in names
    ]
    over = [v for v in volumes if v["bytes"] > cap]
    if over:
        # Refuse the whole set rather than publish a volume that will fail to send --
        # the operator would discover it at the far end of the channel, which is where
        # this module's whole reason for existing already went wrong once.
        for v in volumes:
            with contextlib.suppress(OSError):
                (out / v["name"]).unlink()
        raise VolumeError(
            f"{len(over)} of {len(volumes)} volumes exceeded the {cap} B cap "
            f"(largest {max(v['bytes'] for v in over)} B); nothing was published"
        )

    manifest = {
        "kind": VOLUME_KIND,
        "source": src_path.name,
        "source_bytes": src_path.stat().st_size,
        "volume_max_bytes": cap,
        "volume_names": names,
        "volume_count": len(names),
        "volumes": volumes,
        "members": members,
        "split_members": split_members,
        "checksums": "per-volume SHA-256 of the volume file as written",
        "note": _set_note(len(names), split_members, cap),
    }
    (out / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def load_manifest(out_dir: str | os.PathLike[str]) -> dict[str, Any]:
    p = Path(out_dir) / MANIFEST_NAME
    if not p.exists():
        raise VolumeError(f"no volume manifest ({MANIFEST_NAME}) in {out_dir}")
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("kind") != VOLUME_KIND:
        raise VolumeError(f"not a diagnostics volume set (kind={m.get('kind')!r})")
    return m


def verify_volume_set(out_dir: str | os.PathLike[str]) -> dict[str, Any]:
    """Check every volume against the manifest. Returns ``{ok, bad, missing, total}``.

    Deliberately the same return shape as :func:`src.backup.volumes.verify_volume_set`.
    ``bad`` names volumes that are absent or whose bytes no longer match -- exactly the
    set that has to be re-sent. Size is checked before the hash so a truncated transfer
    (the likely failure for a set that exists because of an upload limit) is caught
    without reading the whole file.
    """
    m = load_manifest(out_dir)
    out = Path(out_dir)
    bad: list[str] = []
    missing: list[str] = []
    for v in m["volumes"]:
        p = out / v["name"]
        if not p.exists():
            bad.append(v["name"])
            missing.append(v["name"])
        elif p.stat().st_size != v["bytes"] or _sha256_file(p) != v["sha256"]:
            bad.append(v["name"])
    return {"ok": not bad, "bad": bad, "missing": missing, "total": len(m["volumes"])}


def reassemble_split_members(
    out_dir: str | os.PathLike[str], dest_dir: str | os.PathLike[str]
) -> list[str]:
    """Rebuild every split member from a COMPLETE volume set into ``dest_dir``.

    Raises :class:`VolumeError` if the set does not verify, rather than producing a
    silently truncated file -- a diagnostics member short by one part that does not say
    so is worse than one that is absent, because it will be read and believed.
    """
    ver = verify_volume_set(out_dir)
    if not ver["ok"]:
        raise VolumeError(f"volume set is incomplete or corrupt: {ver['bad']}")
    m = load_manifest(out_dir)
    out, dest = Path(out_dir), Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for base in m.get("split_members", []):
        # Ordered by the recorded PART INDEX, not by the entry name. The names are
        # padded to sort correctly (see _part_name), but the order the bytes must be
        # joined in is a fact the manifest already states, and reading it from there
        # cannot be broken by a future change to the naming.
        parts = sorted(
            (e for e in m["members"] if e["part_of"] and e["name"] == base),
            key=lambda e: (e["volume"], e["entry"]),
        )
        # FLATTENED, and distinctly. Taking only ``Path(base).name`` would keep a
        # rebuilt member out of a directory it should not reach, but it would also make
        # ``a/x.json`` and ``b/x.json`` land on the same file and silently overwrite one
        # -- trading a traversal for a lost member. Separators become "__" instead, so
        # the write stays inside ``dest`` AND every member keeps its own file.
        target = dest / base.replace("\\", "/").replace("/", "__").lstrip(".")
        with open(target, "wb") as fh:
            for part in parts:
                with zipfile.ZipFile(out / m["volume_names"][part["volume"] - 1]) as z:
                    fh.write(z.read(part["entry"]))
        written.append(str(target))
    return written
