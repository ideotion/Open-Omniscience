#!/usr/bin/env python3
"""Consult docs/ledger/LESSONS.md by grep, through a generated index (PF11 = b, 2026-09-30).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. Protocol rule (1) said to read LESSONS.md in full, every session. At 1.08 MB that is
obeyable only by skimming -- the failure mode the rule exists to prevent, and the second
time it happened (the CLAUDE.md split of 2026-09-07 was the first). The maintainer's ruling
(PF11 = D07 = b, with a size ratchet on top) makes it CONSULT-BY-GREP, like OPEN_QUEUE.md:
CLAUDE.md alone stays mandatory in full, and this tool is how a session finds the lessons
that bear on the work at hand.

THE INDEX IS GENERATED, NEVER COMMITTED -- the same reasoning as ``scripts/planned.py``
(protocol rule (7)): a checked-in copy is stale whenever a lesson is added or moved, in a
repo whose ledger changes every session, and a stale index reads as authoritative. Two
parallel lesson PRs would also both rewrite it and conflict on every line after the first.

USAGE
    python scripts/lessons.py word [word ...]   entries containing ALL the words (any case)
    python scripts/lessons.py --index           one line per entry: line number + title
    python scripts/lessons.py --show LINE       print the whole entry that starts at LINE
    python scripts/lessons.py --stats           entry count and file size

An ENTRY is either a bullet whose text opens with a bold title (``- **TITLE (date):** text``,
at any indent) or a heading of level 2-6 (``## title`` / ``### title`` -- every lesson written
after 2026-09-11 uses one). Lines inside a code fence never start an entry. An entry's own text
runs to the next entry, so a hit is attributed to the most specific entry and never to the
enclosing "Lessons harvested" bullet that nests two thirds of them. A query with no words is
refused (it would match everything), and so is an unknown ``--flag``.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

LESSONS = Path(__file__).resolve().parent.parent / "docs" / "ledger" / "LESSONS.md"
_ENTRY = re.compile(r"^(\s*)- \*\*(.*)$")
_HEADING = re.compile(r"^#{2,6}\s+(.*\S)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TITLE_MAX = 150


@dataclass(frozen=True)
class Entry:
    line: int  # 1-based line the entry starts on
    end: int  # 1-based line of its last own line (inclusive)
    title: str


def _title(lines: list[str], i: int, first: str) -> str:
    """The bold title, which may wrap: join lines until its closing ``**``."""
    text = first
    j = i
    while "**" not in text and j + 1 < len(lines) and j - i < 6:
        j += 1
        text += " " + lines[j].strip()
    text = text.split("**", 1)[0]
    text = " ".join(text.split())
    return text if len(text) <= _TITLE_MAX else text[: _TITLE_MAX - 1].rstrip() + "…"


def parse(text: str) -> list[Entry]:
    lines = text.split("\n")
    starts: list[tuple[int, str]] = []
    in_fence = False
    for i, ln in enumerate(lines):
        if _FENCE.match(ln):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = _ENTRY.match(ln)
        if m:
            starts.append((i, _title(lines, i, m.group(2))))
            continue
        h = _HEADING.match(ln)
        if h:
            text = " ".join(h.group(1).replace("**", "").split())
            if len(text) > _TITLE_MAX:
                text = text[: _TITLE_MAX - 1].rstrip() + "…"
            starts.append((i, text))
    out: list[Entry] = []
    for k, (i, title) in enumerate(starts):
        nxt = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
        out.append(Entry(line=i + 1, end=nxt, title=title))
    return out


def load() -> tuple[list[str], list[Entry]]:
    text = LESSONS.read_text(encoding="utf-8")
    return text.split("\n"), parse(text)


def search(lines: list[str], entries: list[Entry], words: list[str]) -> list[tuple[Entry, list[str]]]:
    needles = [w.lower() for w in words if w]
    hits: list[tuple[Entry, list[str]]] = []
    for e in entries:
        body = lines[e.line - 1 : e.end]
        low = "\n".join(body).lower()
        if all(n in low for n in needles):
            shown = [
                " ".join(b.split())[:170]
                for b in body[1:]
                if any(n in b.lower() for n in needles)
            ][:2]
            hits.append((e, shown))
    return hits


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    lines, entries = load()
    if argv[0] == "--index":
        for e in entries:
            print(f"L{e.line:<6} {e.title}")
        return 0
    if argv[0] == "--stats":
        print(f"{len(entries)} entries · {len(lines) - 1} lines · {LESSONS.stat().st_size} bytes")
        return 0
    if argv[0] == "--show":
        if len(argv) != 2 or not argv[1].lstrip("L").isdigit():
            print("usage: lessons.py --show LINE", file=sys.stderr)
            return 2
        at = int(argv[1].lstrip("L"))
        for e in entries:
            if e.line == at:
                print("\n".join(lines[e.line - 1 : e.end]).rstrip())
                return 0
        print(f"no entry starts at line {at} (see --index)", file=sys.stderr)
        return 1
    if argv[0].startswith("--"):
        print(f"unknown option {argv[0]} (see --help)", file=sys.stderr)
        return 2
    if not any(w.strip() for w in argv):
        print("give at least one word to search for (an empty query matches everything)", file=sys.stderr)
        return 2
    hits = search(lines, entries, argv)
    for e, shown in hits:
        print(f"L{e.line:<6} {e.title}")
        for s in shown:
            print(f"          … {s}")
    print(f"{len(hits)} entr{'y' if len(hits) == 1 else 'ies'} of {len(entries)} contain: {' + '.join(argv)}")
    return 0 if hits else 1


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except BrokenPipeError:  # `| head` closed the pipe: not an error
        sys.stderr.close()
        sys.exit(0)
