"""Files of at most one megabyte, numbered, each valid on its own (the diagnostics channel).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. The diagnostics are how evidence gets from the maintainer to whoever is diagnosing, and
the channel refuses files of about 1.2 MB and up (measured by the maintainer, 2026-09-30:
uploads of ~5 MB zips failed, one-by-one zipped uploads worked). A diagnostic that cannot be
sent is a diagnostic that does not exist, so the size of every file the maintainer is handed is
a correctness property here, not a convenience.

THE SHAPE, as asked (2026-10-01): every file is at most ``UPLOAD_PART_BYTES``; the files of one
export are numbered ``<stem>-part-03-of-12.zip``; each part opens on its own in any unzip tool,
because the cut falls between RECORDS (a keyword entry, a family, a log line), never in the
middle of one; and a small ``<stem>-manifest.zip`` lists every part with its size and SHA-256 so
a set can be confirmed complete. This module is the machinery; the keyword export
(:mod:`src.analytics.keyword_log_export`) and the all-diagnostics bundle
(:mod:`src.api.diagnostics_volumes`) are its two users.

HOW A PART IS FILLED (the coordinator's check of the first plan, 2026-10-01): records STREAM into
one deflate stream per member, a chunk at a time. Before a chunk is committed it is compressed on
a ``copy()`` of the compressor state and flushed, so the exact size of the part if it were closed
now is known; if the chunk fits (bytes so far + the chunk + the zip directory + the ``part.json``
that is appended at the end) the copy becomes the compressor, and if not the part is closed and
the chunk opens the next one. Nothing is predicted from a ratio, nothing is compressed twice and
redone: on real keyword shards a guessed-chunk builder filled parts 52-74%, this fills them to
the cap. Memory is one chunk and two compressor states, flat however large the export is. The zip
is written by this module (about a hundred lines: local headers patched at the end of each member,
a central directory) because ``zipfile`` cannot snapshot its compressor; every part is checked
against ``zipfile`` in the tests.

THE ONE THING THAT MUST NEVER HAPPEN is a part over the cap. A record (or JSON value) larger than
a part is therefore never written whole: it goes out as consecutive byte pieces
``<name>.oversizeNNNN-of-MMMM``, each under the cap, named in the manifest with the way to rejoin
them. Nothing is dropped, nothing exceeds the cap. A finished part over the cap is an error that
stops the export, not a file handed over.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import struct
import time
import zipfile
import zlib
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

#: The most any file handed to the maintainer may weigh. The maintainer's number, and what it
#: protects is their UPLOADS: files of about 1.2 MB and up failed to upload (2026-09-30); 1,000,000
#: bytes and not 2**20 keeps a margin under that. It is not a memory or disk limit, and it bounds
#: each FILE, never the total (an export asking for no total cap is simply more files). The one
#: thing that moves it is an operator's own override of the diagnostics set's cap
#: (``OO_DIAG_VOLUME_MAX_MB``, in MiB, so ``1`` is 1,048,576 bytes, and the manifest zips of that
#: set follow it); the default, every keyword set and its manifest zips are this number.
UPLOAD_PART_BYTES = 1_000_000

PART_KIND = "oo-upload-part-1"
MANIFEST_KIND = "oo-upload-parts-manifest-1"

#: The fraction of a part's cap that ONE json piece or oversize byte piece may weigh raw. Below 1
#: because deflate's worst case is a hair LARGER than its input and a part also carries its own
#: zip headers and index: at 0.8 a piece that does not compress at all still fits a part alone.
PIECE_FRACTION = 0.8

#: The least a piece may weigh, and the least a part may leave for one. What it protects: below
#: this a piece is mostly the zip structure around it, so a cap that small is refused (``ValueError``)
#: rather than written as thousands of files that each hold a line.
_MIN_PIECE_BYTES = 256

#: How much of the room a part has left, after its own structure, one piece may take. What it
#: protects: a piece is never what puts a part over the cap, whatever the compressor does with it
#: (deflate's worst case is a little LARGER than its input). A tenth is generous on purpose: the
#: post-check that refuses an over-cap part stays a backstop that nothing is expected to reach.
_PIECE_ROOM_SHARE = 0.9

#: Bytes allowed for the name of a member in the structure a part carries. A name is stored twice
#: (local header and central directory), and the ones this module writes are 30 to 60 bytes
#: (``keywords/<language>.from-NNNNNN.json`` and its numbered pieces); 96 leaves room for a long one.
_MEMBER_NAME_ALLOWANCE = 96

#: The widest position and total a part's own index (part.json) is MEASURED with, as in
#: ``part-999999-of-999999``: the index is sized before the number of parts is known, so it is
#: sized for the widest, and the room reserved for it is an upper bound whatever the final
#: numbering. A million parts of a megabyte is a terabyte, past anything an export writes.
_WIDEST_PART_NUMBER = 999_999

#: The widest record index and count a part's per-group entry is measured with, for the same
#: reason: a thousand million records is far past any corpus (the largest measured holds about
#: 410 thousand keywords).
_WIDEST_RECORD_NUMBER = 999_999_999

#: A dict child no larger than this share of a piece joins its siblings in one "shell" piece
#: instead of being split on its own (many small children are one document, not many).
_SHELL_SHARE = 8

#: Records compressed and committed together. What it protects: the trial compresses one chunk on
#: a copy of the compressor, so the chunk bounds both the memory held and how much of a part a
#: failed trial wastes (nothing is wasted in the files: only the trial's CPU). At ~230 B an entry
#: a chunk is ~115 KB raw, about 8 KB deflated: a part ends within that of the cap.
_CHUNK_RECORDS = 500

#: Room held back for the end of the member now streaming: the closing JSON of a records file
#: (``],"slice_to":N,"count":N}``, under 100 bytes) and deflate's final block. What it protects
#: is the cap itself: the trial's size check has to include what closing the member will add.
_MEMBER_TAIL = 160

#: Zip structure per member beyond its name: the local header (30 bytes) and central directory
#: entry (46 bytes), and the end-of-directory record (22 bytes) once per file.
_LOCAL_FIXED, _CENTRAL_FIXED, _END_FIXED = 30, 46, 22

#: Bytes kept for the framing of a small deflated member, added where a member is counted raw
#: (the part.json, whose real deflated size is smaller than the raw count). A constant, not zlib's
#: n/1000 bound: ``finish`` re-measures every part, so a constant that was wrong would be an error,
#: never an oversize file.
_DEFLATE_SLACK = 16

#: Names a reader can rely on inside every part.
PART_INDEX_NAME = "part.json"

_NAME_RE = re.compile(r"^(?P<stem>.+)-part-(?P<i>\d+)-of-(?P<n>\d+)\.zip$")


# ------------------------------------------------------------------ names
def part_file_name(stem: str, index: int, total: int) -> str:
    """``oo-keyword-log-20261001-0412-part-03-of-12.zip``: position and total, zero-padded to
    the width of the total (at least two digits) so the files sort in order in any file list."""
    width = max(2, len(str(total)))
    return f"{stem}-part-{index:0{width}d}-of-{total:0{width}d}.zip"


def manifest_file_name(stem: str) -> str:
    return f"{stem}-manifest.zip"


def parse_part_name(name: str) -> tuple[str, int, int] | None:
    """``(stem, index, total)`` of a part's file name, or ``None`` for any other name."""
    m = _NAME_RE.match(name)
    if not m:
        return None
    return m.group("stem"), int(m.group("i")), int(m.group("n"))


# ------------------------------------------------------------------ json pieces
def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _size(value: Any) -> int:
    return len(_dumps(value).encode("utf-8"))


def piece_limit(cap: int = UPLOAD_PART_BYTES) -> int:
    """Raw bytes one piece may weigh so that it fits a part on its own."""
    return max(_MIN_PIECE_BYTES, int(cap * PIECE_FRACTION))


def split_json_value(value: Any, limit: int, path: tuple[str, ...] = ()) -> Iterator[dict]:
    """Cut ``value`` into pieces of at most ``limit`` serialised bytes, on record boundaries.

    Each piece is ``{"path": [...], "slice": {...} | None, "value": ...}``: a dict at ``path``
    holding some of its keys (a SHELL, ``slice`` None), a list at ``path`` holding items
    ``from``..``to`` of ``of`` (``slice`` set), or a leaf. :func:`join_json_pieces` puts them
    back, and every piece is a valid JSON document by itself. A container smaller than ``limit``
    is one piece. A value that cannot be cut (one string, or one list item, larger than
    ``limit``) is emitted ALONE and flagged ``"oversize": true``: it is never cut inside, because
    half a record is not a record.
    """
    if _size(value) <= limit:
        yield {"path": list(path), "slice": None, "value": value}
        return
    if isinstance(value, dict):
        shell: dict[str, Any] = {}
        shell_size = 2
        big: list[tuple[str, Any]] = []
        for key, child in value.items():
            cost = _size(child) + len(_dumps(key).encode("utf-8")) + 2
            if cost > limit // _SHELL_SHARE:
                big.append((key, child))
                continue
            if shell and shell_size + cost > limit:
                yield {"path": list(path), "slice": None, "value": shell}
                shell, shell_size = {}, 2
            shell[key] = child
            shell_size += cost
        if shell:
            yield {"path": list(path), "slice": None, "value": shell}
        for key, child in big:
            yield from split_json_value(child, limit, (*path, key))
        return
    if isinstance(value, list):
        total = len(value)
        start = 0
        chunk: list[Any] = []
        chunk_size = 2
        for i, item in enumerate(value):
            cost = _size(item) + 1
            if chunk and chunk_size + cost > limit:
                yield {
                    "path": list(path), "slice": {"from": start, "to": i, "of": total},
                    "value": chunk,
                }
                start, chunk, chunk_size = i, [], 2
            chunk.append(item)
            chunk_size += cost
            if len(chunk) == 1 and cost > limit:
                yield {
                    "path": list(path), "slice": {"from": start, "to": i + 1, "of": total},
                    "value": chunk, "oversize": True,
                }
                start, chunk, chunk_size = i + 1, [], 2
        if chunk:
            yield {
                "path": list(path), "slice": {"from": start, "to": total, "of": total},
                "value": chunk,
            }
        return
    yield {"path": list(path), "slice": None, "value": value, "oversize": True}


def piece_document(piece: dict) -> bytes:
    """The bytes of one piece as a file: ``{"oo_part": {...}, "value": ...}``."""
    head = {"path": piece["path"], "slice": piece["slice"]}
    if piece.get("oversize"):
        head["oversize"] = True
    return (_dumps({"oo_part": head, "value": piece["value"]})).encode("utf-8")


def join_json_pieces(pieces: Iterable[dict]) -> Any:
    """Put pieces from :func:`split_json_value` back into the value they were cut from.

    Refuses (``ValueError``) a list whose slices do not follow each other, or a container whose
    pieces disagree about its type: a document rebuilt with a hole in it must say so."""
    holder: dict[str, Any] = {}  # the root lives under one key so every path has a parent
    for piece in pieces:
        path, sl, value = piece["path"], piece.get("slice"), piece["value"]
        parent: Any = holder
        key: str = "root"
        for step in path:
            child = parent.setdefault(key, {})
            if not isinstance(child, dict):
                raise ValueError(f"piece path {path!r} crosses a non-object")
            parent, key = child, step
        if sl is not None:
            target = parent.setdefault(key, [])
            if not isinstance(target, list):
                raise ValueError(f"piece at {path!r} is a list slice into a non-list")
            if sl["from"] != len(target):
                raise ValueError(
                    f"slices of {path!r} do not follow each other: expected item {len(target)}, "
                    f"got {sl['from']}"
                )
            target.extend(value)
        elif isinstance(value, dict):
            target = parent.setdefault(key, {})
            if not isinstance(target, dict):
                raise ValueError(f"piece at {path!r} is an object piece into a non-object")
            target.update(value)
        else:
            parent[key] = value
    return holder.get("root")


# ------------------------------------------------------------------ hashing
def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


# ------------------------------------------------------------------ a zip written as it streams
_LOCAL = struct.Struct("<IHHHHHIIIHH")
_CENTRAL = struct.Struct("<IHHHHHHIIIHHHHHII")
_END = struct.Struct("<IHHHHIIH")
_LOCAL_SIG, _CENTRAL_SIG, _END_SIG = 0x04034B50, 0x02014B50, 0x06054B50
_FLAG_UTF8 = 0x0800  # names are UTF-8 (the keyword language files and ours are ASCII, but a name may not be)
_METHOD_DEFLATE = 8
_LEVEL = 6  # zipfile's own default for deflate, so a part weighs what zipfile would have written


class _Member:
    """One finished (or streaming) member of a part: where its local header starts and what the
    directory must say about it."""

    __slots__ = ("crc", "csize", "name", "offset", "usize")

    def __init__(self, name: str, offset: int) -> None:
        self.name, self.offset = name, offset
        self.crc = self.csize = self.usize = 0


def _dos_stamp(ts: float) -> tuple[int, int]:
    t = time.localtime(max(ts, 315532800))  # the DOS clock starts in 1980
    dos_time = (t.tm_hour << 11) | (t.tm_min << 5) | (t.tm_sec // 2)
    dos_date = ((t.tm_year - 1980) << 9) | (t.tm_mon << 5) | t.tm_mday
    return dos_time, dos_date


def _raw_deflater() -> Any:
    return zlib.compressobj(_LEVEL, zlib.DEFLATED, -15)


def _local_header(name: str, m: _Member, stamp: tuple[int, int]) -> bytes:
    nb = name.encode("utf-8")
    return _LOCAL.pack(
        _LOCAL_SIG, 20, _FLAG_UTF8, _METHOD_DEFLATE, stamp[0], stamp[1],
        m.crc, m.csize, m.usize, len(nb), 0,
    ) + nb


def _directory(members: list[_Member], offset: int, stamp: tuple[int, int]) -> bytes:
    """The central directory and the end record, for members whose data end at ``offset``."""
    out = bytearray()
    for m in members:
        nb = m.name.encode("utf-8")
        out += _CENTRAL.pack(
            _CENTRAL_SIG, (3 << 8) | 20, 20, _FLAG_UTF8, _METHOD_DEFLATE, stamp[0], stamp[1],
            m.crc, m.csize, m.usize, len(nb), 0, 0, 0, 0, 0o100644 << 16, m.offset,
        ) + nb
    out += _END.pack(_END_SIG, 0, 0, len(members), len(members), len(out), offset, 0)
    return bytes(out)


def _directory_size(names: Iterable[str]) -> int:
    return _END_FIXED + sum(_CENTRAL_FIXED + len(n.encode("utf-8")) for n in names)


# ------------------------------------------------------------------ the writer
class RecordGroup:
    """A run of records written as ONE json file per part that holds some of them:
    ``{**head, "slice_from": a, "slice_of": total, key: [records...], "slice_to": b, "count": k}``.

    The head names where the slice starts and the tail where it ends, so a part cut short (a
    failed copy) has no tail and says so. ``total`` is how many records the group has in all;
    ``start`` is the position of its first record in that run (a page that starts at record
    5,000 says 5,000)."""

    def __init__(self, name: str, head: dict, key: str, total: int, start: int = 0) -> None:
        self.name, self.head, self.key, self.total = name, head, key, total
        self.emitted = start  # records already written, here and in earlier parts

    def member_name(self, start: int) -> str:
        """The file name of the slice that begins at record ``start``: the group's name with the
        position in it, so no two files of a set share a name (unzipping every part into one folder
        loses nothing, and a part that holds the same group twice never repeats a name)."""
        stem, dot, ext = self.name.rpartition(".")
        width = max(6, len(str(self.total)))
        return f"{stem}.from-{start:0{width}d}.{ext}" if dot else f"{self.name}.from-{start:0{width}d}"


class _PartFile:
    """One part being written: the file, its finished members, the member now streaming."""

    def __init__(self, path: Path, stamp: tuple[int, int]) -> None:
        self.path, self.stamp = path, stamp
        self.fh = path.open("wb")
        self.members: list[_Member] = []
        self.meta: list[dict] = []  # what part.json will say each member holds
        self.cur: _Member | None = None
        self.comp: Any = None
        self.group: RecordGroup | None = None
        self.cur_from = 0
        self.cur_count = 0
        self.records = 0
        self.dir_offset = 0
        self.pj_reserve = 0
        self.front = False

    def content_count(self) -> int:
        return len(self.members) + (1 if self.cur is not None else 0)


class PartWriter:
    """Write numbered zip parts of at most ``cap`` bytes each, streaming.

    Feed it :meth:`add_record` / :meth:`add_records` (records of a :class:`RecordGroup`),
    :meth:`add_file` (a whole small file) and the orientation documents
    (:meth:`add_front_json_document`: numbered first however late they are produced), then call
    :meth:`finish`. Parts are written under ``out_dir`` as temporary names and given their final
    ``-part-NN-of-MM`` names once the total is known; the manifest zip is written last.

    ``check`` and ``disk_watch`` run once per part opened (the export's memory stop and drive
    watch). ``order_note`` says in what order the records come, and is written into every
    ``part.json`` and the manifest.
    """

    def __init__(
        self, out_dir: Path, *, stem: str, cap: int = UPLOAD_PART_BYTES,
        check: Callable[[], None] | None = None,
        disk_watch: Callable[[], None] | None = None,
        describe: dict | None = None, order_note: str = "",
    ) -> None:
        self.out_dir, self.stem, self.cap = Path(out_dir), stem, cap
        self.check = check or (lambda: None)
        self.disk_watch = disk_watch or (lambda: None)
        self.describe = dict(describe or {})
        self.order_note = order_note
        self._stamp = _dos_stamp(time.time())
        self._buf: list[str] = []
        self._buf_group: RecordGroup | None = None
        self._buf_raw = 0
        self._part: _PartFile | None = None
        self._done: list[_PartFile] = []
        self._front: list[tuple[str, str, bytes]] = []  # ("file" | "oversize", name, data)
        self._serial = 0
        self._records = 0
        self._oversize: list[dict] = []
        self._pj_final_name = part_file_name(stem, _WIDEST_PART_NUMBER, _WIDEST_PART_NUMBER)
        # What a part costs before it holds anything: part.json, two members' zip structure and
        # names, the end record. A piece must leave room for it, whatever the cap.
        self._fixed = (
            len(self._part_json_bytes([], _WIDEST_PART_NUMBER, _WIDEST_PART_NUMBER, self._pj_final_name))
            + 2 * (_LOCAL_FIXED + _CENTRAL_FIXED + _MEMBER_NAME_ALLOWANCE) + _END_FIXED + _MEMBER_TAIL
        )
        self._piece_limit = min(piece_limit(cap), int((cap - self._fixed) * _PIECE_ROOM_SHARE))
        if self._piece_limit < _MIN_PIECE_BYTES:
            needed = self._fixed + math.ceil(_MIN_PIECE_BYTES / _PIECE_ROOM_SHARE)
            raise ValueError(
                f"a part cap of {cap} bytes is too small: a part's own index needs {self._fixed}, a piece "
                f"needs at least {_MIN_PIECE_BYTES}, and a piece may take at most {_PIECE_ROOM_SHARE:.0%} "
                f"of what is left, so the cap needs at least {needed}"
            )
        self.out_dir.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- feeding
    def add_record(self, group: RecordGroup, record: str) -> None:
        if self._buf_group is not group:
            self._flush_buffer()
            self._buf_group = group
        self._buf.append(record)
        self._buf_raw += len(record) + 1
        self._records += 1
        if len(self._buf) >= _CHUNK_RECORDS or self._buf_raw >= self.cap:
            self._flush_buffer()

    def add_records(self, group: RecordGroup, records: Iterable[str]) -> None:
        for record in records:
            self.add_record(group, record)

    def add_file(self, name: str, data: bytes) -> None:
        self._flush_buffer()
        self._place_file(name, data, {"member": name, "kind": "file"})

    def add_json_document(self, name: str, value: Any) -> None:
        """A document that may be larger than a part: one file when it fits a piece, else numbered
        pieces ``<name stem>.sNNN.<ext>`` that are each valid JSON (see :func:`split_json_value`)."""
        for member, data, oversize in self._json_files(name, value):
            if oversize:
                self._flush_buffer()
                self._place_oversize(member, data)
            else:
                self.add_file(member, data)

    def add_front_json_document(self, name: str, value: Any) -> None:
        """A document that belongs at the START of the set however late it is produced (the
        summary and the export's own manifest: what this is and what ran). It is held until
        :meth:`finish`, then written into parts of their own that are numbered first (or, when
        the whole export is one part and they fit beside it, into that part)."""
        for member, data, oversize in self._json_files(name, value):
            self._front.append(("oversize" if oversize else "file", member, data))

    def _json_files(self, name: str, value: Any) -> list[tuple[str, bytes, bool]]:
        # A quarter of a piece is left for the ``oo_part`` header a piece document adds around its value.
        pieces = list(split_json_value(value, self._piece_limit * 3 // 4))
        if len(pieces) == 1 and pieces[0]["slice"] is None and not pieces[0]["path"] \
                and not pieces[0].get("oversize"):
            return [(name, _dumps(value).encode("utf-8"), False)]
        stem, dot, ext = name.rpartition(".")
        out = []
        for i, piece in enumerate(pieces, start=1):
            member = f"{stem}.s{i:03d}.{ext}" if dot else f"{name}.s{i:03d}"
            data = piece_document(piece)
            out.append((member, data, len(data) > self._piece_limit))
        return out

    # ---------------------------------------------------------------- one part
    def _open_part(self, *, front: bool = False) -> _PartFile:
        self.check()
        self.disk_watch()
        self._serial += 1
        part = _PartFile(self.out_dir / f".part-{self._serial:06d}.zip.tmp", self._stamp)
        part.front = front
        part.pj_reserve = len(self._part_json_bytes([], _WIDEST_PART_NUMBER, _WIDEST_PART_NUMBER, self._pj_final_name)) \
            + _LOCAL_FIXED + len(PART_INDEX_NAME) + _DEFLATE_SLACK
        self._part = part
        return part

    def _head_bytes(self, group: RecordGroup) -> bytes:
        head = _dumps({**group.head, "slice_from": group.emitted, "slice_of": group.total})
        return (head[:-1] + f',{_dumps(group.key)}:[').encode("utf-8")

    def _meta_for(self, group: RecordGroup, lo: int, hi: int, member: str | None = None) -> dict:
        return {"member": member or group.member_name(lo), "kind": "records", "group": group.name,
                "from": lo, "to": hi,
                "of": group.total, **group.head}

    def _flush_buffer(self) -> None:
        if not self._buf:
            return
        group, texts = self._buf_group, self._buf
        self._buf, self._buf_group, self._buf_raw = [], None, 0
        assert group is not None
        size = _CHUNK_RECORDS
        i = 0
        while i < len(texts):
            chunk = texts[i:i + size]
            if self._try_chunk(group, chunk):
                i += len(chunk)
            elif self._part is not None and self._part.content_count():
                if len(chunk) > 1:
                    size = max(1, len(chunk) // 2)  # top the part up with a smaller chunk
                else:
                    self._close_part()  # full to within one record: the next chunk opens the next part
                    size = _CHUNK_RECORDS
            elif len(chunk) > 1:
                size = max(1, len(chunk) // 2)  # not even an empty part takes it: a smaller chunk
            else:
                self._close_part()
                self._place_oversize(
                    f"{group.member_name(group.emitted)}.record", chunk[0].encode("utf-8"),
                    note="a keyword record larger than a part",
                    group=group.name, index=group.emitted,
                )
                group.emitted += 1  # keeps the slice numbers true: the record is in the pieces
                i += 1

    def _try_chunk(self, group: RecordGroup, chunk: list[str]) -> bool:
        part = self._part or self._open_part()
        opening = part.cur is None or part.group is not group
        body = ",".join(chunk).encode("utf-8")
        if opening:
            comp = _raw_deflater()
            payload = self._head_bytes(group) + body
            name = group.member_name(group.emitted)
        else:
            comp = part.comp.copy()
            payload = b"," + body
            name = part.cur.name if part.cur is not None else group.name
        out = comp.compress(payload) + comp.flush(zlib.Z_SYNC_FLUSH)
        names = [m.name for m in part.members]
        pj = part.pj_reserve
        if part.cur is not None:
            names.append(part.cur.name)
        if opening:
            names.append(name)
            pj += len(_dumps(self._meta_for(group, _WIDEST_RECORD_NUMBER, _WIDEST_RECORD_NUMBER))) + 1
        names.append(PART_INDEX_NAME)
        final = (
            part.fh.tell() + len(out) + _MEMBER_TAIL + _directory_size(names) + pj
            + (_LOCAL_FIXED + len(name.encode("utf-8")) if opening else 0)
            + (_MEMBER_TAIL if opening and part.cur is not None else 0)
        )
        if final > self.cap:
            return False
        if opening:
            if part.cur is not None:
                self._end_member(part)
            part.cur = _Member(name, part.fh.tell())
            part.fh.write(_local_header(name, part.cur, self._stamp))
            part.group, part.cur_from, part.cur_count = group, group.emitted, 0
            part.pj_reserve = pj
        member = part.cur
        assert member is not None
        part.comp = comp
        part.fh.write(out)
        member.csize += len(out)
        member.usize += len(payload)
        member.crc = zlib.crc32(payload, member.crc)
        part.cur_count += len(chunk)
        part.records += len(chunk)
        group.emitted += len(chunk)
        return True

    def _end_member(self, part: _PartFile) -> None:
        """Finish the streaming records member: its closing JSON, the end of its deflate stream,
        and its real CRC and sizes patched into the header written when it began."""
        m, group = part.cur, part.group
        assert m is not None and group is not None
        tail = f'],"slice_to":{part.cur_from + part.cur_count},"count":{part.cur_count}}}'.encode()
        out = part.comp.compress(tail) + part.comp.flush(zlib.Z_FINISH)
        part.fh.write(out)
        m.csize += len(out)
        m.usize += len(tail)
        m.crc = zlib.crc32(tail, m.crc)
        end = part.fh.tell()
        part.fh.seek(m.offset + 14)
        part.fh.write(struct.pack("<III", m.crc, m.csize, m.usize))
        part.fh.seek(end)
        part.members.append(m)
        part.meta.append(self._meta_for(group, part.cur_from, part.cur_from + part.cur_count, m.name))
        part.cur = part.comp = part.group = None

    def _place_file(
        self, name: str, data: bytes, meta: dict, *, front: bool = False, piece: bool = False
    ) -> None:
        """A whole file in the open part if it fits, else in the next one; a file that does not
        fit even an empty part goes out as oversize pieces (``piece``: it is one of those already,
        so that cannot happen: the writer's own accounting is wrong)."""
        while True:
            part = self._part or self._open_part(front=front)
            co = _raw_deflater()
            body = co.compress(data) + co.flush()
            names = [m.name for m in part.members] + ([part.cur.name] if part.cur else []) \
                + [name, PART_INDEX_NAME]
            pj = part.pj_reserve + len(_dumps(meta)) + 1
            final = (
                part.fh.tell() + _LOCAL_FIXED + len(name.encode("utf-8")) + len(body)
                + (_MEMBER_TAIL if part.cur is not None else 0)
                + _directory_size(names) + pj
            )
            if final <= self.cap:
                break
            if part.content_count():
                self._close_part()
                continue
            # Not even an empty part takes it.
            if piece:
                raise RuntimeError(f"an oversize piece of {len(data)} bytes does not fit a part")
            self._close_part()
            self._place_oversize(name, data)
            return
        if part.cur is not None:
            self._end_member(part)
        m = _Member(name, part.fh.tell())
        m.crc, m.csize, m.usize = zlib.crc32(data), len(body), len(data)
        part.fh.write(_local_header(name, m, self._stamp))
        part.fh.write(body)
        part.members.append(m)
        part.meta.append(meta)
        part.pj_reserve = pj

    def _place_oversize(
        self, name: str, data: bytes, *, note: str = "", group: str = "", index: int | None = None
    ) -> None:
        """``data`` is larger than a part can take whole: write it as byte pieces, each in a part
        of its own, and record them for the manifest. Nothing exceeds the cap and nothing is lost."""
        self._close_part()
        limit = self._piece_limit
        count = max(1, -(-len(data) // limit))
        width = max(4, len(str(count)))
        pieces = []
        for i in range(count):
            piece_name = f"{name}.oversize{i + 1:0{width}d}-of-{count:0{width}d}"
            chunk = data[i * limit:(i + 1) * limit]
            self._place_file(piece_name, chunk, {
                "member": piece_name, "kind": "oversize-piece", "of_record": name,
                "piece": i + 1, "pieces": count,
            }, piece=True)
            self._close_part()
            pieces.append(piece_name)
        self._oversize.append({
            "name": name, "bytes": len(data), "pieces": pieces,
            "sha256": hashlib.sha256(data).hexdigest(), **({"why": note} if note else {}),
            **({"group": group, "record_index": index} if group else {}),
            "rejoin": "concatenate the pieces in order (shell: cat <name>.oversize* > <name>); "
                      "each piece is a plain byte slice, not a document",
        })

    def _close_part(self) -> None:
        part = self._part
        self._part = None
        if part is None:
            return
        if part.cur is not None:
            self._end_member(part)
        part.dir_offset = part.fh.tell()
        part.fh.write(_directory(part.members, part.dir_offset, part.stamp))
        part.fh.close()
        if part.members:
            self._done.append(part)
        else:
            with contextlib.suppress(OSError):
                part.path.unlink()

    # ---------------------------------------------------------------- the end
    def _part_json_bytes(
        self, meta: list[dict], position: int, total: int, file_name: str
    ) -> bytes:
        return _dumps({
            "kind": PART_KIND, "set": self.stem, "file": file_name,
            "position": position, "total": total, "contents": meta,
            **({"order": self.order_note} if self.order_note else {}),
            "neighbours": (
                f"{self.stem}-part-NN-of-{total:0{max(2, len(str(total)))}d}.zip for every NN from "
                f"1 to {total}; the manifest is {manifest_file_name(self.stem)}"
            ),
            "note": (
                "One part of a numbered set. Every file in it is complete on its own: the cut "
                "between parts falls between records. A set is complete when every neighbour "
                "named here is present and matches the SHA-256 in the manifest."
            ),
        }).encode("utf-8")

    def _append(
        self, part: _PartFile, items: list[tuple[str, bytes, dict]], *, force: bool, extra: int = 0
    ) -> bool:
        """Add members after the last one of a finished part and rewrite its directory. Returns
        False, touching nothing, when they would not fit under the cap (unless ``force``)."""
        bodies = []
        for name, data, meta in items:
            co = _raw_deflater()
            bodies.append((name, data, co.compress(data) + co.flush(), meta))
        names = [m.name for m in part.members] + [n for n, _d, _b, _m in bodies]
        new_size = part.dir_offset + _directory_size(names) + sum(
            _LOCAL_FIXED + len(n.encode("utf-8")) + len(b) for n, _d, b, _m in bodies
        )
        if new_size + extra > self.cap and not force:
            return False
        with part.path.open("r+b") as fh:
            fh.seek(part.dir_offset)
            for name, data, body, meta in bodies:
                m = _Member(name, fh.tell())
                m.crc, m.csize, m.usize = zlib.crc32(data), len(body), len(data)
                fh.write(_local_header(name, m, part.stamp))
                fh.write(body)
                part.members.append(m)
                part.meta.append(meta)
            part.dir_offset = fh.tell()
            fh.write(_directory(part.members, part.dir_offset, part.stamp))
            fh.truncate()
        return True

    def finish(self) -> dict:
        """Write what is pending, give the parts their numbers, write the manifest; returns it."""
        self._flush_buffer()
        self._close_part()
        front_items = self._front
        self._front = []
        merged = False
        if (
            front_items and len(self._done) == 1 and not self._oversize
            and all(kind == "file" for kind, _n, _d in front_items)
        ):
            # The whole export is one part: the orientation documents ride in it when they fit
            # beside it (and the part.json that still has to be added), so a small export is ONE
            # file and not an orientation file plus one of records.
            only = self._done[0]
            metas = [{"member": n, "kind": "file"} for _k, n, _d in front_items]
            extra = (
                len(self._part_json_bytes(only.meta + metas, _WIDEST_PART_NUMBER, _WIDEST_PART_NUMBER, self._pj_final_name))
                + _LOCAL_FIXED + len(PART_INDEX_NAME) + _DEFLATE_SLACK
                + _CENTRAL_FIXED + len(PART_INDEX_NAME)
            )
            merged = self._append(
                only, [(n, d, m) for (_k, n, d), m in zip(front_items, metas, strict=True)],
                force=False, extra=extra,
            )
        front_parts: list[_PartFile] = []
        if front_items and not merged:
            first_record_part = len(self._done)
            for kind, name, data in front_items:
                if kind == "oversize":
                    self._place_oversize(name, data)
                else:
                    self._place_file(name, data, {"member": name, "kind": "file"}, front=True)
            self._close_part()
            front_parts = self._done[first_record_part:]
            for p in front_parts:
                p.front = True
            self._done = self._done[:first_record_part] + front_parts
        if not self._done:
            # An export with nothing in it still hands over one valid part saying so.
            self._place_file("empty.json", b"{}", {"member": "empty.json", "kind": "file"})
            self._close_part()
        ordered = [p for p in self._done if p.front] + [p for p in self._done if not p.front]
        total = len(ordered)
        parts: list[dict] = []
        for position, part in enumerate(ordered, start=1):
            final = part_file_name(self.stem, position, total)
            self._append(part, [(
                PART_INDEX_NAME,
                self._part_json_bytes(part.meta, position, total, final),
                {"member": PART_INDEX_NAME, "kind": "index"},
            )], force=True)
            os.replace(part.path, self.out_dir / final)
            size = (self.out_dir / final).stat().st_size
            if size > self.cap:
                raise RuntimeError(
                    f"{final} is {size} bytes, over the {self.cap} cap: the writer's size "
                    "accounting is wrong; nothing was handed over"
                )
            parts.append({
                "name": final, "position": position, "bytes": size,
                "sha256": sha256_file(self.out_dir / final),
                "members": [m for m in part.meta if m["kind"] != "index"],
            })
        manifest = {
            "kind": MANIFEST_KIND, "stem": self.stem, "part_max_bytes": self.cap,
            "part_count": total, "records": self._records, "parts": parts,
            **({"order": self.order_note} if self.order_note else {}),
            **({"oversize_records": self._oversize} if self._oversize else {}),
            **self.describe,
            "note": (
                f"{total} part(s) of at most {self.cap} bytes each. A set is complete when every "
                f"name from {part_file_name(self.stem, 1, total)} to "
                f"{part_file_name(self.stem, total, total)} is present and its SHA-256 matches "
                "the one listed here. Each part opens on its own."
            ),
        }
        manifest_files = self.write_manifest(manifest)
        return {**manifest, "manifest_files": manifest_files}

    def write_manifest(self, manifest: dict) -> list[str]:
        """The manifest as ``<stem>-manifest.zip`` (see :func:`write_manifest_zips`)."""
        return write_manifest_zips(self.out_dir, self.stem, manifest, self.cap)

    def abort(self) -> None:
        """Remove everything this writer has written (the export failed or was refused)."""
        part, self._part = self._part, None
        if part is not None:
            with contextlib.suppress(OSError):
                part.fh.close()
        for p in self.out_dir.glob(".part-*.zip.tmp"):
            with contextlib.suppress(OSError):
                p.unlink()


def write_manifest_zips(
    out_dir: Path, stem: str, manifest: dict, cap: int, *, inner: str = "manifest.json"
) -> list[str]:
    """``manifest`` as ``<stem>-manifest.zip`` (a zip, like the parts: uploads of other formats
    are the ones that failed) holding one file called ``inner``; returns the file names written.
    A manifest too large for one file (thousands of parts at a few hundred bytes each) is cut like
    any other document into ``<stem>-manifest-NN-of-MM.zip``, every one of them valid on its own
    (``<inner stem>.sNNN.json`` pieces: see :func:`split_json_value`)."""
    out_dir = Path(out_dir)
    name = manifest_file_name(stem)
    with zipfile.ZipFile(out_dir / name, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr(inner, json.dumps(manifest, ensure_ascii=False, indent=1))
    if (out_dir / name).stat().st_size <= cap:
        return [name]
    (out_dir / name).unlink()
    limit = piece_limit(cap)
    groups: list[list[dict]] = [[]]
    used = 0
    for piece in split_json_value(manifest, limit):
        doc_len = len(piece_document(piece))
        if groups[-1] and used + doc_len > limit:
            groups.append([])
            used = 0
        groups[-1].append(piece)
        used += doc_len
    names = [f"{stem}-manifest-{i:02d}-of-{len(groups):02d}.zip" for i in range(1, len(groups) + 1)]
    istem, dot, ext = inner.rpartition(".")
    for n, group in zip(names, groups, strict=True):
        with zipfile.ZipFile(out_dir / n, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
            for i, piece in enumerate(group, start=1):
                z.writestr(f"{istem}.s{i:03d}.{ext}" if dot else f"{inner}.s{i:03d}",
                           piece_document(piece))
    for n in names:
        # the parts and the volumes are checked once written; the manifest files are too, so that a
        # file over the cap is an error here and never a download the person's upload refuses
        if (out_dir / n).stat().st_size > cap:
            raise RuntimeError(f"manifest file {n} is over its {cap}-byte cap")
    return names


# ------------------------------------------------------------------ the reader
def verify_parts(out_dir: Path, manifest: dict) -> dict:
    """``{ok, bad, missing, total}`` of a set against its manifest: ``bad`` is every part that is
    absent or whose size or SHA-256 differs, i.e. exactly what has to be sent again. Size is
    checked before the hash so a truncated transfer is caught without reading the file."""
    bad: list[str] = []
    missing: list[str] = []
    for p in manifest["parts"]:
        f = Path(out_dir) / p["name"]
        if not f.exists():
            bad.append(p["name"])
            missing.append(p["name"])
        elif f.stat().st_size != p["bytes"] or sha256_file(f) != p["sha256"]:
            bad.append(p["name"])
    return {"ok": not bad, "bad": bad, "missing": missing, "total": len(manifest["parts"])}


def read_group_records(
    paths: Iterable[Path], member_name: str, key: str, start: int = 0,
    manifest: dict | None = None,
) -> list[Any]:
    """Every record of ``member_name`` across parts, in set order (for the analyzer and tests):
    the slices are checked to follow each other, so a missing part is an error, not a short list.
    A record the manifest lists under ``oversize_records`` lives in byte pieces, not here: its
    index is expected to be absent (pass the manifest), and is the only gap that is not an error."""
    absent = {
        r["record_index"] for r in (manifest or {}).get("oversize_records", [])
        if r.get("group") == member_name
    }
    out: list[Any] = []
    expect = start
    stem, dot, ext = member_name.rpartition(".")
    prefix, suffix = (f"{stem}.from-", f".{ext}") if dot else (f"{member_name}.from-", "")
    for path in sorted(paths, key=lambda p: (parse_part_name(p.name) or ("", 0, 0))[1]):
        with zipfile.ZipFile(path) as z:
            names = sorted(
                n for n in z.namelist()
                if n.startswith(prefix) and n.endswith(suffix) and n[len(prefix):-len(suffix) or None].isdigit()
            )
            for name in names:
                doc = json.loads(z.read(name))
                while expect in absent:
                    expect += 1
                if doc["slice_from"] != expect:
                    raise ValueError(
                        f"{member_name}: {name} in {path.name} starts at record {doc['slice_from']} "
                        f"but record {expect} was expected next: a part is missing or out of order"
                    )
                if len(doc[key]) != doc.get("count") or doc.get("slice_to") != doc["slice_from"] + len(doc[key]):
                    raise ValueError(f"{name} in {path.name} is cut short (its tail does not match)")
                out.extend(doc[key])
                expect = doc["slice_to"]
    return out
