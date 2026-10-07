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
    python scripts/lessons.py --new SLUG        write a new lesson FRAGMENT (see below)
    python scripts/lessons.py --new SLUG --date 2026-10-07   (the date defaults to today, UTC)

A NEW LESSON IS A NEW FILE (protocol rule (5a)(b), amended 2026-10-06): ``docs/ledger/lessons.d/
<date>-<slug>.md``, one lesson per file, never a paragraph appended to LESSONS.md. Appending put
every parallel PR's text at the SAME tail and moved one shared ceiling number, so each landing
re-conflicted every other open PR in LESSONS.md and in ``_LESSONS_LINE_CEILING``. A fragment is
searched, indexed and shown exactly like an archive entry; ``scripts/ledger_fold.py fold`` merges
the fragments into LESSONS.md at a release. A fragment is shown whole by its file name
(``--show 2026-10-06-foo.md``), because a line number in a set of files that grows is not stable.

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
FRAGMENTS = LESSONS.parent / "lessons.d"
_ENTRY = re.compile(r"^(\s*)- \*\*(.*)$")
_HEADING = re.compile(r"^#{2,6}\s+(.*\S)\s*$")
_FENCE = re.compile(r"^\s*(```|~~~)")
_TITLE_MAX = 150
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{2,80}")  # the ONE slug rule, shared with ledger_fold.py
TEMPLATE_BODY = "(One lesson, one file. Say what was found, what it cost, and the rule it gives; name the PR once it exists.)"


@dataclass(frozen=True)
class Entry:
    line: int  # 1-based line the entry starts on (in the archive, then each fragment in file-name order)
    end: int  # 1-based line of its last own line (inclusive)
    title: str
    source: str = ""  # "" for the archive (LESSONS.md); a fragment's file name otherwise


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


def fragment_files() -> list[Path]:
    return sorted(f for f in FRAGMENTS.glob("*.md") if f.is_file() and not f.is_symlink()) if FRAGMENTS.is_dir() else []


def load() -> tuple[list[str], list[Entry]]:
    """The archive, then every fragment in file-name order, as ONE list of lines.

    The fragments are appended after the archive with their own line numbers continuing from it, so
    an entry's ``line``/``end`` index the returned list exactly as they did when there was only the
    archive. A fragment's entries carry its file name in ``source``; those line numbers are NOT
    stable across a growing set of files and are never printed -- ``--show`` takes the file name."""
    text = LESSONS.read_text(encoding="utf-8")
    lines = text.split("\n")
    entries = parse(text)
    for f in fragment_files():
        try:
            raw = f.read_bytes().decode("utf-8")
        except UnicodeDecodeError as exc:
            print(f"lessons.py: skipping lessons.d/{f.name}: not valid UTF-8 ({exc.reason}); "
                  "`python scripts/ledger_fold.py check` names it", file=sys.stderr)
            continue
        chunk = raw.replace("\r\n", "\n").rstrip("\n").split("\n")
        at = len(lines)  # the fragment's first line is line at + 1; the archive's last entry ends at `at`
        lines = lines + chunk
        entries += [
            Entry(line=e.line + at, end=e.end + at, title=e.title, source=f.name)
            for e in parse("\n".join(chunk))
        ]
    return lines, entries


_TEMPLATE = "## {date} \u2014 {title}\n\n" + TEMPLATE_BODY + "\n"


def valid_date(day: str) -> bool:
    """A real calendar date written YYYY-MM-DD (ASCII digits only)."""
    import datetime as _dt

    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", day):
        return False
    try:
        _dt.datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def create_exclusive(path: Path, text: str) -> int:
    """Create ``path`` with ``text``; 0 on success, 1 if it (or a symlink of that name) already exists.

    ``open(path, "x")`` is one atomic step, so two creators cannot both succeed and a dangling symlink is
    refused instead of written through; the LF newline keeps the fragment byte-identical on Windows."""
    path.parent.mkdir(exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    except FileExistsError:
        print(f"{path} already exists", file=sys.stderr)
        return 1
    print(path)
    return 0


def _new(slug: str, day: str | None) -> int:
    import datetime as _dt

    if not SLUG.fullmatch(slug):
        print("the slug must be lowercase letters, digits and hyphens (3-81 characters)", file=sys.stderr)
        return 2
    day = day or _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    if not valid_date(day):
        print("--date must be a real date, YYYY-MM-DD", file=sys.stderr)
        return 2
    return create_exclusive(FRAGMENTS / f"{day}-{slug}.md", _TEMPLATE.format(date=day, title=slug.replace("-", " ")))


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
            print(f"{e.source or 'L' + str(e.line):<7} {e.title}")
        return 0
    if argv[0] == "--stats":
        frags = fragment_files()
        print(
            f"{len(entries)} entries · {len(lines) - 1} lines · {LESSONS.stat().st_size} bytes in LESSONS.md"
            f" + {len(frags)} fragment(s) in lessons.d/"
        )
        return 0
    if argv[0] == "--new":
        rest = argv[1:]
        day = None
        if "--date" in rest:
            k = rest.index("--date")
            if k + 1 >= len(rest):
                print("usage: lessons.py --new SLUG [--date YYYY-MM-DD]", file=sys.stderr)
                return 2
            day = rest[k + 1]
            rest = rest[:k] + rest[k + 2 :]
        if len(rest) != 1:
            print("usage: lessons.py --new SLUG [--date YYYY-MM-DD]", file=sys.stderr)
            return 2
        return _new(rest[0], day)
    if argv[0] == "--show":
        if len(argv) != 2:
            print("usage: lessons.py --show LINE | FRAGMENT-FILE-NAME", file=sys.stderr)
            return 2
        want = argv[1]
        if want.endswith(".md"):
            path = FRAGMENTS / want
            if "/" in want or "\\" in want or not path.is_file():
                print(f"no fragment named {want} (see --index)", file=sys.stderr)
                return 1
            try:
                print(path.read_bytes().decode("utf-8").replace("\r\n", "\n").rstrip())
            except UnicodeDecodeError as exc:
                print(f"lessons.d/{want} is not valid UTF-8 ({exc.reason})", file=sys.stderr)
                return 1
            return 0
        if not want.lstrip("L").isdigit():
            print("usage: lessons.py --show LINE | FRAGMENT-FILE-NAME", file=sys.stderr)
            return 2
        at = int(want.lstrip("L"))
        for e in entries:
            if e.line == at and not e.source:
                print("\n".join(lines[e.line - 1 : e.end]).rstrip())
                return 0
        print(f"no archive entry starts at line {at} (see --index)", file=sys.stderr)
        return 1
    if argv[0].startswith("--"):
        print(f"unknown option {argv[0]} (see --help)", file=sys.stderr)
        return 2
    if not any(w.strip() for w in argv):
        print("give at least one word to search for (an empty query matches everything)", file=sys.stderr)
        return 2
    hits = search(lines, entries, argv)
    for e, shown in hits:
        print(f"{e.source or 'L' + str(e.line):<7} {e.title}")
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
