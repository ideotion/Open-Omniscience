#!/usr/bin/env python3
"""One-file-per-entry fragments for the two big ledger archives, so parallel PRs never share a line.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (maintainer-approved 2026-10-06, protocol rule (5a)(b) amended). A PR that shipped something with a
lesson used to APPEND to the tail of docs/ledger/LESSONS.md and docs/ledger/SHIPPED_LOG.md and raise
``_LESSONS_LINE_CEILING``. Every such PR therefore touched the same tail and the same number, so every
landing re-conflicted every other open PR in those three places (measured on 2026-10-06: five open PRs,
each pair conflicting, each owner paying a merge, a push and a full CI run per landing). The shipped
rows already moved to one-file-per-row (``scripts/ledger_shipped.py``, 2026-09-30) and stopped that
for ``shipped.csv``; this is the same convention for the other two archives:

    docs/ledger/lessons.d/<date>-<slug>.md        one lesson, written ``## <date> -- <title>`` + body
    docs/ledger/shipped_log.d/<date>-<slug>.md    one verbatim shipped-log entry

    python scripts/lessons.py --new SLUG          create a lesson fragment (lessons.py reads them)
    python scripts/ledger_fold.py new-log SLUG    create a shipped-log fragment
    python scripts/ledger_fold.py check           every fragment is well formed and within its size cap
    python scripts/ledger_fold.py fold            append the fragments to the archives, delete them,
                                                  and set _LESSONS_LINE_CEILING to the real line count

``fold`` is for the maintainer or a release ritual, NEVER for a feature PR: it rewrites the shared files
this convention exists to stop touching, and it is the one place the ceiling moves. Between folds the
ceiling does not move at all, because nothing is appended to LESSONS.md.

THE SIZE CAP. ``LESSON_FRAGMENT_MAX_LINES`` bounds ONE fragment. What it protects: a lesson stays a
lesson -- something ``lessons.py --show`` prints on a screen or two and a session actually reads --
rather than a report that happens to sit in the lessons folder. Measured over the 158 heading lessons
already in LESSONS.md the median is 14 lines and the 95th percentile 63, so 200 is a bound no ordinary
lesson reaches; an entry that needs more is two lessons, or belongs in a design note that the lesson
points to. It replaces the ceiling as the thing that makes growth visible in a diff, and unlike the
ceiling it is the same number on every branch, so it cannot conflict.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "ledger"
LESSONS_D = LEDGER / "lessons.d"
SHIPPED_LOG_D = LEDGER / "shipped_log.d"
LESSONS = LEDGER / "LESSONS.md"
SHIPPED_LOG = LEDGER / "SHIPPED_LOG.md"
INVARIANTS = ROOT / "tests" / "test_repo_invariants.py"

LESSON_FRAGMENT_MAX_LINES = 200
_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9][a-z0-9-]{2,80}\.md$")
_MARKER = re.compile(r"^(<<<<<<<|=======$|>>>>>>>)")
_CEILING = re.compile(r"^(_LESSONS_LINE_CEILING = )(\d+)$", re.MULTILINE)


def _files(d: Path) -> list[Path]:
    return sorted(d.glob("*.md")) if d.is_dir() else []


def problems() -> list[str]:
    """Every defect in every fragment, as one line each; empty means the fragments are fit to merge."""
    out: list[str] = []
    for d, label in ((LESSONS_D, "lessons.d"), (SHIPPED_LOG_D, "shipped_log.d")):
        for f in _files(d):
            where = f"{label}/{f.name}"
            m = _NAME.match(f.name)
            if not m:
                out.append(f"{where}: the name must be <YYYY-MM-DD>-<slug>.md (lowercase, digits, hyphens)")
                continue
            text = f.read_text(encoding="utf-8")
            lines = text.rstrip("\n").split("\n")
            if not lines[0].startswith("## "):
                out.append(f"{where}: the first line must be a '## ' heading (one entry per file)")
            if not lines[0].startswith("## " + m.group(1)) and label == "lessons.d":
                out.append(f"{where}: the heading must start with the file's date ({m.group(1)})")
            extra = [n for n, ln in enumerate(lines[1:], 2) if re.match(r"^#{1,2} ", ln)]
            if extra and label == "lessons.d":
                out.append(f"{where}: one lesson per file; a second heading at line {extra[0]} belongs in its own file")
            if label == "lessons.d" and len(lines) > LESSON_FRAGMENT_MAX_LINES:
                out.append(
                    f"{where}: {len(lines)} lines, over the {LESSON_FRAGMENT_MAX_LINES}-line cap for one lesson "
                    "(split it, or move the detail to a design note and point to it)"
                )
            if any(_MARKER.match(ln) for ln in lines):
                out.append(f"{where}: an unresolved merge-conflict marker")
            if not text.endswith("\n"):
                out.append(f"{where}: must end with a newline")
    return out


def _new_log(slug: str, day: str | None) -> int:
    import datetime as _dt

    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{2,80}", slug):
        print("the slug must be lowercase letters, digits and hyphens (3-81 characters)", file=sys.stderr)
        return 2
    day = day or _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        print("--date must be YYYY-MM-DD", file=sys.stderr)
        return 2
    path = SHIPPED_LOG_D / f"{day}-{slug}.md"
    if path.exists():
        print(f"{path} already exists", file=sys.stderr)
        return 1
    SHIPPED_LOG_D.mkdir(exist_ok=True)
    path.write_text(
        f"## {day} — {slug.replace('-', ' ')} (PR #NNNN)\n\n"
        "(The verbatim shipped-log entry. Put the real PR number in the heading once it exists.)\n",
        encoding="utf-8",
    )
    print(path)
    return 0


def _fold() -> int:
    bad = problems()
    if bad:
        print("\n".join(bad), file=sys.stderr)
        print("fix these before folding", file=sys.stderr)
        return 1
    moved = 0
    for archive, d in ((LESSONS, LESSONS_D), (SHIPPED_LOG, SHIPPED_LOG_D)):
        files = _files(d)
        if not files:
            continue
        raw = archive.read_bytes()
        if not raw.endswith(b"\n"):
            raw += b"\n"
        for f in files:
            raw += b"\n" + f.read_bytes().rstrip(b"\n") + b"\n"
        archive.write_bytes(raw)  # binary + LF: the archives are not rewritten through a text round trip
        for f in files:
            f.unlink()
        moved += len(files)
    n = LESSONS.read_bytes().count(b"\n")
    src = INVARIANTS.read_text(encoding="utf-8")
    new, hits = _CEILING.subn(lambda m: f"{m.group(1)}{n}", src)
    if hits != 1:
        print("could not find _LESSONS_LINE_CEILING in tests/test_repo_invariants.py exactly once", file=sys.stderr)
        return 1
    INVARIANTS.write_text(new, encoding="utf-8")
    print(f"folded {moved} fragment(s); LESSONS.md is {n} lines and _LESSONS_LINE_CEILING now says so")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("WHY")[0].strip())
    sub = ap.add_subparsers(dest="cmd", required=True)
    nl = sub.add_parser("new-log", help="create a shipped-log fragment")
    nl.add_argument("slug")
    nl.add_argument("--date")
    sub.add_parser("check", help="validate every fragment")
    sub.add_parser("fold", help="append the fragments to the archives and delete them (release ritual)")
    args = ap.parse_args(argv)
    if args.cmd == "new-log":
        return _new_log(args.slug, args.date)
    if args.cmd == "check":
        bad = problems()
        if bad:
            print("\n".join(bad), file=sys.stderr)
            return 1
        print(f"{len(_files(LESSONS_D))} lesson fragment(s) and {len(_files(SHIPPED_LOG_D))} shipped-log fragment(s): ok")
        return 0
    return _fold()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
