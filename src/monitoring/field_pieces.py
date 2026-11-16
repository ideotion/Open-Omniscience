"""
Join the numbered pieces the Field data button cuts a large file into, for the offline analysis scripts.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

Every file the button saves is at most 200 KB (maintainer 2026-11-15); a larger one is saved as
``name-part-001-of-003.zip`` ... ``name-part-003-of-003.zip``, byte pieces that join back by plain concatenation in
order (``cat name-part-*.zip > name.zip``). This lets the scripts take the pieces as they are: give them any piece, or
the folder they sit in, and a COMPLETE set is joined in memory. An incomplete set is never guessed at: it is reported
with the piece numbers that are missing. Stdlib only, no I/O beyond reading the pieces; loaded by path from scripts/.
"""

from __future__ import annotations

import re
from pathlib import Path

PIECE = re.compile(r"^(?P<stem>.+)-part-(?P<k>\d{3,})-of-(?P<n>\d{3,})(?P<ext>\.[A-Za-z0-9]+)?$")


def piece_of(path: Path) -> tuple[str, int, int, str] | None:
    """``(joined name, piece number, piece count, extension)`` when ``path`` is a numbered piece, else None."""
    m = PIECE.match(path.name)
    if not m:
        return None
    k, n = int(m["k"]), int(m["n"])
    if not 1 <= k <= n:
        return None
    ext = m["ext"] or ""
    return m["stem"] + ext, k, n, ext


def join_set(any_piece: Path) -> tuple[str, bytes]:
    """The joined name and bytes of the set ``any_piece`` belongs to; ValueError names the missing pieces."""
    info = piece_of(any_piece)
    if info is None:
        raise ValueError(f"{any_piece.name}: not a numbered piece")
    joined, _k, n, ext = info
    width = len(PIECE.match(any_piece.name)["n"])  # type: ignore[index]
    stem = joined[: len(joined) - len(ext)] if ext else joined
    parts = [any_piece.with_name(f"{stem}-part-{k:0{width}d}-of-{n:0{width}d}{ext}") for k in range(1, n + 1)]
    missing = [k for k, p in enumerate(parts, 1) if not p.is_file()]
    if missing:
        raise ValueError(f"{joined}: pieces {', '.join(map(str, missing))} of {n} missing")
    return joined, b"".join(p.read_bytes() for p in parts)


def sets_in(paths: list[Path]) -> tuple[dict[str, Path], list[Path]]:
    """Split ``paths`` into one representative piece per set (keyed by joined path) and the files that are not pieces."""
    sets: dict[str, Path] = {}
    plain: list[Path] = []
    for p in paths:
        info = piece_of(p)
        if info is None:
            plain.append(p)
        else:
            sets.setdefault(str(p.with_name(info[0])), p)
    return sets, plain
