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

THE 1 MB CAP, AND CUTS ON RECORD BOUNDARIES (maintainer-asked 2026-10-01: «cap the size of each
zip to 1MB (same for diagnostics), by splitting and numbering the files adequately»). The
default cap is now :data:`~src.analytics.upload_parts.UPLOAD_PART_BYTES` (1,000,000 bytes; the
9 MB default protected the common attachment limit, and the maintainer's own uploads failed from
about 1.2 MB), volumes are named ``<stem>-part-NN-of-MM.zip`` and the descriptor travels as
``<stem>-manifest.zip`` (a zip: uploads of other formats are the ones that failed; the
``volumes.json`` sidecar stays for the readers that want it). A member too large for a volume is
no longer cut BY BYTES when it can be cut on RECORD boundaries: a JSON document becomes numbered
``<name>.sNNN.json`` pieces that are each valid JSON on their own (see
:func:`~src.analytics.upload_parts.split_json_value`), a line-oriented log (``.jsonl``, ``.txt``,
``.log``, ``.csv``, ...) becomes numbered pieces cut between lines (a CSV's header is repeated),
and the pieces are packed like any other member. Only a member that is neither (binary, or a JSON
document too large for this machine to parse safely) keeps the old byte cut with its explicit
rejoin instructions.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from src.analytics.upload_parts import (
    UPLOAD_PART_BYTES,
    join_json_pieces,
    part_file_name,
    piece_document,
    split_json_value,
    write_manifest_zips,
)

MANIFEST_NAME = "volumes.json"
README_NAME = "volumes-readme.json"
# ``-2``: the 2026-10-01 shape (numbered ``part-NN-of-MM`` names, a manifest zip, members cut on
# record boundaries). A set written under ``-1`` is refused by ``load_manifest`` and rebuilt.
VOLUME_KIND = "oo-diagnostics-volumes-2"

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

#: Members cut between lines rather than parsed: logs and tables. A ``.csv``/``.tsv`` piece after
#: the first repeats the header line, so each piece is a readable table.
_LINE_SUFFIXES = (".jsonl", ".ndjson", ".txt", ".log", ".csv", ".tsv", ".md")
_HEADER_SUFFIXES = (".csv", ".tsv")

#: The share of a volume's budget that one cut piece may cost once deflated. What it protects: a
#: piece is packed beside the other members, and one that cost the whole budget would take a
#: volume to itself and leave the others a gap they cannot use. A chosen margin, not a measurement.
_PIECE_COST_SHARE = 0.6

#: How often a member is re-cut with smaller pieces when a piece comes out dearer than the budget
#: (the member compressed unevenly) before it is left to the byte cut. Each round halves the
#: piece size, so six rounds reach a sixty-fourth of the first guess.
_CUT_ROUNDS = 6

#: Bytes a parsed JSON document holds per raw byte (a list of small dicts, the shape of our
#: reports, measured by ``tracemalloc`` at roughly 6-10 times its text). A member is parsed to be
#: cut only when this many times its size is under half the memory available now: sized from the
#: machine, never a fixed number of megabytes. What it protects: cutting a big report must not
#: be what takes the app down, which is what this module's neighbours exist to prevent.
_PARSE_EXPANSION = 12


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


class VolumeRoomError(VolumeError):
    """Raised when the drive cannot take a volume set (the caller answers 507, not 500)."""


def volume_max_bytes() -> int:
    """The per-volume ceiling: ``UPLOAD_PART_BYTES`` (1,000,000 bytes, the maintainer's number),
    env-tunable via ``OO_DIAG_VOLUME_MAX_MB`` for a channel that takes more. The unit is MiB, as it
    always was, so ``1`` means 1,048,576 bytes: past the default, which is the point of an override.

    It was 9 MiB (under the common 10 MB attachment limit); the maintainer then asked for 1 MB
    files because uploads of about 1.2 MB and up failed.
    """
    try:
        mb = float(os.environ["OO_DIAG_VOLUME_MAX_MB"])
    except (KeyError, ValueError):
        return UPLOAD_PART_BYTES
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


def _member_cost(src: zipfile.ZipFile, name: str) -> tuple[int, int]:
    """``(deflated cost, raw bytes)`` of one member, measured by streaming it through the
    compressor a megabyte at a time: the member is never held whole (some reports are hundreds of
    megabytes), and the number is the real one for the same reason :func:`_deflated_cost`'s is."""
    import zlib

    co = zlib.compressobj(9, zlib.DEFLATED, -15)
    n = raw = 0
    with src.open(name) as fh:
        for blk in iter(lambda: fh.read(1 << 20), b""):
            raw += len(blk)
            n += len(co.compress(blk))
    n += len(co.flush())
    return n + _PER_ENTRY_OVERHEAD, raw


class _Cut:
    """A member cut on record boundaries: its pieces as ``(entry name, deflated cost, raw
    bytes)`` and how to produce piece ``i``'s bytes when the volume that holds it is written.

    ``kind`` is ``"json"`` (each piece a valid JSON document, see ``split_json_value``) or
    ``"lines"`` (each piece a run of whole lines; ``header`` is the first line repeated at the top
    of every piece after the first, for a table)."""

    def __init__(
        self, base: str, kind: str, pieces: list[tuple[str, int, int]],
        render: Callable[[int, _SliceReader], bytes], *, header: bool = False,
    ) -> None:
        self.base, self.kind, self.pieces, self.render, self.header = base, kind, pieces, render, header


def _piece_names(name: str, count: int) -> list[str]:
    suffix = Path(name).suffix
    stem = name[: len(name) - len(suffix)] if suffix else name
    width = max(3, len(str(count)))
    return [f"{stem}.s{i:0{width}d}{suffix}" for i in range(1, count + 1)]


def _close_line_piece(
    buf: bytearray, start: int, spans: list[tuple[int, int]], costs: list[tuple[int, int]],
    header: bytes, budget: int,
) -> bool:
    """Record the piece held in ``buf`` (it began at ``start`` in the member): its span, and its
    deflated cost as it will be written (a table piece after the first carries the header).
    Returns whether it fits ``budget``."""
    rendered = (header if spans else b"") + bytes(buf)
    c = _deflated_cost(rendered)
    spans.append((start, len(buf)))
    costs.append((c, len(rendered)))
    return c <= budget


def _cut_lines(src: zipfile.ZipFile, name: str, raw: int, cost: int, budget: int) -> _Cut | None:
    """Cut a line-oriented member between lines into pieces that each cost at most ``budget``
    deflated, or ``None`` if some line is too dear for that even after several smaller tries."""
    with_header = Path(name).suffix.lower() in _HEADER_SUFFIXES
    limit = max(1024, int(budget * _PIECE_COST_SHARE * raw / max(1, cost)))
    for _round in range(_CUT_ROUNDS):
        header = b""
        spans: list[tuple[int, int]] = []  # (offset in the member, length) of each piece's lines
        costs: list[tuple[int, int]] = []  # (deflated cost, rendered bytes)
        ok = True
        buf = bytearray()
        start = 0
        with src.open(name) as fh:
            for line in fh:
                if with_header and not header:
                    header = line
                extra = len(header) if spans else 0
                if buf and len(buf) + len(line) + extra > limit:
                    ok = _close_line_piece(buf, start, spans, costs, header, budget)
                    start += len(buf)
                    buf = bytearray()
                    if not ok:
                        break
                buf += line
            if ok and (buf or not spans):
                ok = _close_line_piece(buf, start, spans, costs, header, budget)
        if ok:
            return _Cut(
                name, "lines",
                list(zip(_piece_names(name, len(spans)), (c for c, _r in costs),
                         (r for _c, r in costs), strict=True)),
                _line_renderer(name, spans, header), header=with_header and len(spans) > 1,
            )
        limit = max(256, limit // 2)
    return None


def _line_renderer(
    name: str, spans: list[tuple[int, int]], header: bytes
) -> Callable[[int, _SliceReader], bytes]:
    def render(i: int, reader: _SliceReader) -> bytes:
        off, length = spans[i]
        return (header if i else b"") + reader.read(name, off, length)

    return render


def _cut_json(src: zipfile.ZipFile, name: str, raw: int, cost: int, budget: int) -> _Cut | None:
    """Cut a JSON document into pieces that are each valid JSON, or ``None`` when this machine
    cannot parse it safely (see ``_PARSE_EXPANSION``), it does not parse, or one record is dearer
    than a volume."""
    import json as _json

    from src.analytics.keyword_log_scan import available_bytes_now

    free = available_bytes_now()
    # With the memory unreadable nothing is assumed: only a document small enough to parse
    # anywhere is parsed.
    allowed = raw * _PARSE_EXPANSION <= free * 0.5 if free is not None else raw <= 32 * 1024 * 1024
    if not allowed:
        return None
    try:
        value = _json.loads(src.read(name))
    except ValueError:
        return _cut_lines(src, name, raw, cost, budget)
    limit = max(1024, int(budget * _PIECE_COST_SHARE * raw / max(1, cost)))
    for _round in range(_CUT_ROUNDS):
        docs = [piece_document(p) for p in split_json_value(value, limit)]
        if len(docs) > 1:
            costs = [_deflated_cost(d) for d in docs]
            if max(costs) <= budget:
                names = _piece_names(name, len(docs))
                return _Cut(
                    name, "json",
                    [(n, c, len(d)) for n, c, d in zip(names, costs, docs, strict=True)],
                    _render_from(docs),
                )
        limit = max(256, limit // 2)
    return None


def _render_from(docs: list[bytes]) -> Callable[[int, _SliceReader], bytes]:
    """A ``_Cut`` renderer that hands back piece ``i`` of documents already held in memory (the
    JSON pieces are small by construction: each is at most one volume's budget)."""

    def render(i: int, _reader: _SliceReader) -> bytes:
        return docs[i]

    return render


def _cut_member(src: zipfile.ZipFile, name: str, raw: int, cost: int, budget: int) -> _Cut | None:
    suffix = Path(name).suffix.lower()
    if suffix == ".json":
        return _cut_json(src, name, raw, cost, budget)
    if suffix in _LINE_SUFFIXES:
        return _cut_lines(src, name, raw, cost, budget)
    return None


def _ordered_entries(
    src: zipfile.ZipFile, budget: int
) -> tuple[list[tuple[str, int, int]], dict[str, _Cut]]:
    """Archive members as ``(name, deflated_cost, raw_bytes)``, orientation files first, and the
    members that were cut on record boundaries (their pieces stand in the list in the member's
    place, each one a whole entry for the packer).

    Streams every member through the compressor once to measure it, and once more for a member
    that is cut. That doubles the work of a split, which is the price of a volume set that is
    actually under its cap rather than predicted to be.
    """
    infos = {i.filename: i for i in src.infolist() if not i.is_dir()}
    names = [n for n in _FIRST_MEMBERS if n in infos]
    names += [n for n in infos if n not in _FIRST_MEMBERS]
    out: list[tuple[str, int, int]] = []
    cuts: dict[str, _Cut] = {}
    for n in names:
        cost, raw = _member_cost(src, n)
        if cost > budget:
            cut = _cut_member(src, n, raw, cost, budget)
            if cut is not None:
                cuts[n] = cut
                out.extend(cut.pieces)
                continue
        out.append((n, cost, raw))
    return out, cuts


def _set_note(nvols: int, split: list[str], cap: int, cut: list[str] | None = None) -> str:
    lines = [
        f"The all-diagnostics archive, split into {nvols} independently-openable ZIP "
        f"volume(s) of at most {cap} bytes each, so it can be sent through a channel "
        "with an attachment limit.",
        f"Every volume opens on its own in any unzip tool. {README_NAME} (present in "
        "every volume) lists the whole set and which volume carries each member; it "
        f"carries no checksums, because a file cannot contain its own hash -- those "
        f"are in the {MANIFEST_NAME} sidecar written beside the volumes (also sent as the "
        "manifest zip, which lists every volume with its size and SHA-256).",
    ]
    if cut:
        lines.append(
            "ONE OR MORE MEMBERS WERE CUT ON RECORD BOUNDARIES because they were larger than a "
            "volume: " + ", ".join(sorted(cut)) + ". Each is a run of numbered pieces "
            "(<name>.sNNN.<ext>) and every piece is complete on its own: a JSON document's "
            "piece is valid JSON carrying its place in the original (oo_part: path and slice), "
            "a log's piece is a run of whole lines (a table's header is repeated). Nothing "
            "has to be rejoined to be read."
        )
    if split:
        lines.append(
            "ONE OR MORE MEMBERS ARE SPLIT BY BYTES and are NOT readable from a single volume: "
            + ", ".join(sorted(split))
            + " (they are neither a log nor a document this machine could cut safely). Each is "
            "stored as <name>.partNNNNofMMMM entries in consecutive "
            "volumes; extract every part and concatenate them in part order to rebuild "
            "the original file (shell: cat <name>.part* > <name>). Every OTHER member "
            "in those same volumes is whole and directly readable."
        )
    if not split and not cut:
        lines.append("No member is split: every member is complete inside one volume.")
    elif not split:
        lines.append("No member is split by bytes: every volume's files open as they are.")
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
    """``<stem>-part-NN-of-MM.zip``, zero-padded to the width of the total (the one naming
    every numbered set of this app shares: see :func:`src.analytics.upload_parts.part_file_name`)."""
    return part_file_name(stem, idx, total)


def _plan_and_names(
    entries: list[tuple[str, int, int]], cuts: dict[str, _Cut], cap: int, stem: str, reserve: int
):
    plan = plan_volumes(entries, cap=cap, reserve=reserve)
    nvols = len(plan)
    names = [_volume_name(stem, i, nvols) for i in range(1, nvols + 1)]
    pieces = {
        entry: (cut, i)
        for cut in cuts.values()
        for i, (entry, _cost, _raw) in enumerate(cut.pieces)
    }
    members: list[dict[str, Any]] = []
    for vi, vol in enumerate(plan, start=1):
        for entry, _off, length, part_of, stored in vol:
            if part_of and entry.rsplit(".part", 1)[0] in pieces:
                # A reserve that grew after the cut can leave a piece dearer than a volume; the
                # byte cut of a piece would break what a piece promises, so refuse instead.
                raise VolumeError(
                    f"cap of {cap} B is too small for this archive's volume index: a cut piece no "
                    "longer fits a volume. Raise OO_DIAG_VOLUME_MAX_MB."
                )
            record: dict[str, Any] = {
                "name": entry.rsplit(".part", 1)[0] if part_of else entry,
                "entry": entry,
                "volume": vi,
                "bytes": length,
                "part_of": part_of,
                "stored_uncompressed": stored,
            }
            if entry in pieces:
                cut, i = pieces[entry]
                record["name"] = cut.base
                record["cut"] = {
                    "kind": cut.kind, "piece": i + 1, "of": len(cut.pieces),
                    **({"header_repeated": True} if cut.header and i else {}),
                }
            members.append(record)
    return plan, names, members, pieces


def _readme_for(
    *, vi: int, nvols: int, stem: str, src_path: Path, cap: int, members, split_members,
    cut_members: list[str],
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
                "-part-" + "0" * max(2, len(str(nvols))) + "-of-",
                "-part-" + "N" * max(2, len(str(nvols))) + "-of-",
            ),
            "members_in_this_volume": mine,
            "split_members": split_members,
            "cut_members": cut_members,
            "full_member_map": (
                f"not here -- it grows with the volume count; see {MANIFEST_NAME} "
                "written beside the volumes"
            ),
            "checksums": (
                f"not here -- a file cannot contain its own hash; see {MANIFEST_NAME} "
                "written beside the volumes"
            ),
            "note": _set_note(nvols, split_members, cap, cut_members),
        },
        ensure_ascii=False,
        indent=2,
    )


def write_volume_set(
    src_zip: str | os.PathLike[str],
    out_dir: str | os.PathLike[str],
    *,
    cap: int | None = None,
    stem: str | None = None,
) -> dict[str, Any]:
    """Split the finished archive ``src_zip`` into capped volumes under ``out_dir``.

    Returns the sidecar manifest. The source archive is only READ -- it stays where it
    is and keeps working as the single-file download, so this is an additional way to
    collect the same evidence, never a replacement that could strand it. The volumes are named
    ``<stem>-part-NN-of-MM.zip`` (``stem`` defaults to the archive's own name, timestamp
    included, so the files of two bundles never mix) and the manifest is also written as
    ``<stem>-manifest.zip``.

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
    stem = stem or src_path.stem

    with zipfile.ZipFile(src_path) as src:
        reserve = _overhead_reserve(cap)
        # Cut once, against the budget the first reserve leaves: a larger reserve found below
        # can only shrink it, and a piece that no longer fits is refused rather than re-cut.
        entries, cuts = _ordered_entries(src, max(1, cap - reserve))
        for _round in range(_RESERVE_ROUNDS):
            plan, names, members, piece_at = _plan_and_names(entries, cuts, cap, stem, reserve)
            split_members = sorted({m["name"] for m in members if m["part_of"]})
            cut_members = sorted(cuts)
            readmes = [
                _readme_for(
                    vi=vi, nvols=len(names), stem=stem, src_path=src_path, cap=cap,
                    members=members, split_members=split_members, cut_members=cut_members,
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
                        if entry in piece_at:
                            cut, i = piece_at[entry]
                            z.writestr(entry, cut.render(i, reader))
                            continue
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
        "stem": stem,
        "volume_max_bytes": cap,
        "volume_names": names,
        "volume_count": len(names),
        "volumes": volumes,
        "members": members,
        "split_members": split_members,
        "cut_members": cut_members,
        "checksums": "per-volume SHA-256 of the volume file as written",
        "note": _set_note(len(names), split_members, cap, cut_members),
    }
    # The manifest travels as a zip too (uploads of other formats are the ones that failed). A
    # file cannot hold its own hash, so the zip carries the document above and the sidecar adds
    # the zip's own name, size and SHA-256 beside it.
    zip_names = write_manifest_zips(out, stem, manifest, cap, inner=MANIFEST_NAME)
    manifest_files = [
        {"name": n, "sha256": _sha256_file(out / n), "bytes": (out / n).stat().st_size}
        for n in zip_names
    ]
    sidecar = {**manifest, "manifest_files": manifest_files}
    (out / MANIFEST_NAME).write_text(
        json.dumps(sidecar, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return sidecar


def publish_volume_set(
    build_dir: str | os.PathLike[str], out_dir: str | os.PathLike[str]
) -> dict[str, Any]:
    """Move a FINISHED set from ``build_dir`` into ``out_dir``, then retire the files it replaces.

    A set is written in a folder of its own (``write_volume_set(src, build_dir)``) and moved in
    only when it is whole, so the set that is in ``out_dir`` keeps answering through the whole
    split and survives a split that fails: before, the previous files were deleted first and the new
    ones written into the live folder, which left no set (and the half-written volumes) on a full
    disk, and 404 for every name while a split ran. Both folders must be on one drive (a rename).

    THE SIDECAR (``MANIFEST_NAME``) MOVES LAST, because it is what makes a set exist and what the
    download route resolves names against: until it moves, the old sidecar still names old files,
    all of which are still there; after it moves, the new one names new files, all of which are in.
    Only then are the files nothing names any more removed (a file that cannot be removed, such as one
    a download holds open on Windows, is left and swept by the next publish; a leftover is never
    served, as only a name the sidecar lists is). One window remains and is stated: a rebuild of the
    SAME archive under another cap can reuse a file name, and for the moment between that file's
    move and the sidecar's the old sidecar describes a file that has changed; the checksum a person
    compares then fails, which is the honest outcome, and the set is one file-move from right.
    """
    build, out = Path(build_dir), Path(out_dir)
    manifest = load_manifest(build)
    names = [v["name"] for v in manifest["volumes"]] + [
        f["name"] for f in manifest.get("manifest_files", [])
    ]
    out.mkdir(parents=True, exist_ok=True)
    for name in names:
        os.replace(build / name, out / name)
    os.replace(build / MANIFEST_NAME, out / MANIFEST_NAME)
    keep = {*names, MANIFEST_NAME}
    for stale in out.iterdir():
        if stale.name not in keep:
            with contextlib.suppress(OSError):
                stale.unlink()
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
    for v in [*m["volumes"], *m.get("manifest_files", [])]:
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


def reassemble_cut_members(
    out_dir: str | os.PathLike[str], dest_dir: str | os.PathLike[str]
) -> list[str]:
    """Rebuild every member that was CUT ON RECORD BOUNDARIES from a complete volume set.

    Nothing has to be rebuilt to be READ (each piece is whole on its own); this exists to prove,
    and to let an analyst check, that the pieces put back are the original member: a JSON
    document's pieces are joined by their recorded place in it, a log's by concatenation (a
    table's repeated header dropped after the first piece). Refuses a set that does not verify.
    """
    ver = verify_volume_set(out_dir)
    if not ver["ok"]:
        raise VolumeError(f"volume set is incomplete or corrupt: {ver['bad']}")
    m = load_manifest(out_dir)
    out, dest = Path(out_dir), Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for base in m.get("cut_members", []):
        pieces = sorted(
            (e for e in m["members"] if e.get("cut") and e["name"] == base),
            key=lambda e: e["cut"]["piece"],
        )
        kind = pieces[0]["cut"]["kind"]
        datas = []
        for e in pieces:
            with zipfile.ZipFile(out / m["volume_names"][e["volume"] - 1]) as z:
                datas.append(z.read(e["entry"]))
        target = dest / base.replace("\\", "/").replace("/", "__").lstrip(".")
        if kind == "json":
            docs = [json.loads(d) for d in datas]
            value = join_json_pieces([
                {"path": d["oo_part"]["path"], "slice": d["oo_part"]["slice"], "value": d["value"]}
                for d in docs
            ])
            target.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        else:
            with open(target, "wb") as fh:
                for i, d in enumerate(datas):
                    if i and pieces[i]["cut"].get("header_repeated"):
                        d = d.split(b"\n", 1)[1] if b"\n" in d else b""
                    fh.write(d)
        written.append(str(target))
    return written
