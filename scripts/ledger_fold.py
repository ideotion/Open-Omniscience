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

    docs/ledger/lessons.d/<date>-<slug>.md        one lesson, written ``## <date> — <title>`` + body
    docs/ledger/shipped_log.d/<date>-<slug>.md    one verbatim shipped-log entry

    python scripts/lessons.py --new SLUG          create a lesson fragment (lessons.py reads them)
    python scripts/ledger_fold.py new-log SLUG    create a shipped-log fragment
    python scripts/ledger_fold.py check           every fragment is well formed (see FORMAT) and within its size cap
    python scripts/ledger_fold.py fold            append the fragments to the archives, delete them,
                                                  and set _LESSONS_LINE_CEILING to the real line count

FORMAT of a fragment (``check`` enforces it; a fragment that fails ``check`` fails the PR's tests): the file
name is ``<YYYY-MM-DD>-<slug>.md`` with a real date; the FIRST line is ``## <date> — <title>`` (a lesson's
heading starts with the file's own date) and a lesson has no second heading outside a code fence; UTF-8, LF line
ends, a trailing newline, balanced code fences, no conflict markers, no ``#NNNN`` or ``PR pending`` placeholder,
none of the untouched ``--new`` / ``new-log`` template text, and a title no other fragment or archive entry has.

FOLD IS CRASH-SAFE AND RE-RUNNABLE: it checks everything before touching anything, writes each archive to a
temporary file and ``os.replace``s it, deletes fragments only after BOTH archives are written, skips a fragment
whose exact text an archive already holds (so a run interrupted after the writes never appends it twice), and
moves the ceiling last -- and only when the number changes.

``fold`` is for the maintainer or a release ritual, NEVER for a feature PR: it rewrites the shared files
this convention exists to stop touching, and it is the one place the ceiling moves. Between folds the
ceiling does not move at all, because nothing is appended to LESSONS.md.

THE SIZE CAP. ``LESSON_FRAGMENT_MAX_LINES`` bounds ONE fragment. What it protects: a lesson stays a
lesson -- something ``lessons.py --show`` prints on a screen or two and a session actually reads --
rather than a report that happens to sit in the lessons folder. Measured over the 158 heading lessons
already in LESSONS.md the median is 14 lines, the 95th percentile 51 and the largest 226, so 200 is a bound
only the rare giant reaches. It protects ONE ENTRY'S size and nothing else: it does not make the archive's
growth visible (the ceiling did, and it is gone from a PR's diff), and a lesson that needs more than 200 lines
is two lessons, or belongs in a design note that the lesson points to.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
from pathlib import Path

import lessons as _lessons

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "ledger"
LESSONS_D = LEDGER / "lessons.d"
SHIPPED_LOG_D = LEDGER / "shipped_log.d"
LESSONS = LEDGER / "LESSONS.md"
SHIPPED_LOG = LEDGER / "SHIPPED_LOG.md"
INVARIANTS = ROOT / "tests" / "test_repo_invariants.py"

LESSON_FRAGMENT_MAX_LINES = 200
_NAME = re.compile(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})-(" + _lessons.SLUG.pattern + r")\.md$")
_MARKER = re.compile(r"^(<<<<<<<|=======$|>>>>>>>)")
_CEILING = re.compile(r"^(_LESSONS_LINE_CEILING = )([0-9]+)$", re.MULTILINE)
_FENCE = re.compile(r"^\s*(```|~~~)")
_PLACEHOLDER = re.compile(r"#NNNN|\bPR pending\b", re.IGNORECASE)
LOG_TEMPLATE_BODY = "(The verbatim shipped-log entry. Put the real PR number in the heading once it exists.)"


def _files(d: Path) -> list[Path]:
    return sorted(f for f in d.glob("*.md") if f.is_file()) if d.is_dir() else []


def _archive(path: Path) -> tuple[bytes, set[str]]:
    """The archive's bytes and its ``## `` titles (empty when it cannot be read)."""
    try:
        raw = path.read_bytes()
        return raw, {ln.strip() for ln in raw.decode("utf-8").splitlines() if ln.startswith("## ")}
    except (OSError, UnicodeDecodeError):
        return b"", set()


def _fragment_problems(
    f: Path, label: str, seen: dict[str, str], archive_raw: bytes, archive_titles: set[str]
) -> list[str]:
    where = f"{label}/{f.name}"
    m = _NAME.match(f.name)
    if not m:
        return [f"{where}: the name must be <YYYY-MM-DD>-<slug>.md (lowercase, digits, hyphens)"]
    out: list[str] = []
    if not _lessons.valid_date(m.group(1)):
        out.append(f"{where}: {m.group(1)} is not a real date")
    try:
        text = f.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        return out + [f"{where}: not valid UTF-8 ({exc.reason})"]
    if "\r" in text:
        out.append(f"{where}: CRLF line ends; fragments are LF only (the archives are)")
    lines = text.rstrip("\n").split("\n")
    lesson = label == "lessons.d"
    if not lines[0].startswith("## "):
        out.append(f"{where}: the first line must be a '## ' heading (one entry per file)")
    else:
        title = lines[0].strip()
        if title in seen:
            out.append(f"{where}: the same title as {seen[title]}")
        elif title in archive_titles and not _already_in(archive_raw, f):  # an interrupted fold leaves it in both
            out.append(f"{where}: the same title as an entry already in the archive")
        seen.setdefault(title, where)
    if lesson and not lines[0].startswith("## " + m.group(1)):
        out.append(f"{where}: the heading must start with the file's date ({m.group(1)})")
    in_fence = False
    second = 0
    for n, ln in enumerate(lines, 1):
        if _FENCE.match(ln):
            in_fence = not in_fence
            continue
        if not in_fence and n > 1 and ln.startswith("#") and not ln.startswith("# ") and not second:
            second = n  # test_lessons_index's rule: a line starting with # (not "# ") is a heading
    if in_fence:
        out.append(f"{where}: an unclosed code fence (after a fold it would swallow every later entry)")
    if second and lesson:
        out.append(f"{where}: one lesson per file; a second heading at line {second} belongs in its own file")
    if lesson and len(lines) > LESSON_FRAGMENT_MAX_LINES:
        out.append(
            f"{where}: {len(lines)} lines, over the {LESSON_FRAGMENT_MAX_LINES}-line cap for one lesson "
            "(split it, or move the detail to a design note and point to it)"
        )
    if any(_MARKER.match(ln) for ln in lines):
        out.append(f"{where}: an unresolved merge-conflict marker")
    if not text.endswith("\n"):
        out.append(f"{where}: must end with a newline")
    if _PLACEHOLDER.search(text):
        out.append(f"{where}: a placeholder ('#NNNN' or 'PR pending'); write the real PR number")
    if _lessons.TEMPLATE_BODY in text or LOG_TEMPLATE_BODY in text:
        out.append(f"{where}: the untouched template text; write the entry")
    return out


def _already_in(raw: bytes, frag: Path) -> bool:
    return b"\n" + _block(frag) in b"\n" + raw


def problems() -> list[str]:
    """Every defect in every fragment, as one line each; empty means the fragments are fit to merge."""
    out: list[str] = []
    for d, label, archive in ((LESSONS_D, "lessons.d", LESSONS), (SHIPPED_LOG_D, "shipped_log.d", SHIPPED_LOG)):
        seen: dict[str, str] = {}
        raw, archive_titles = _archive(archive)
        for f in _files(d):
            out += _fragment_problems(f, label, seen, raw, archive_titles)
    return out


def _new_log(slug: str, day: str | None) -> int:
    if not _lessons.SLUG.fullmatch(slug):
        print("the slug must be lowercase letters, digits and hyphens (3-81 characters)", file=sys.stderr)
        return 2
    day = day or _dt.datetime.now(_dt.UTC).strftime("%Y-%m-%d")
    if not _lessons.valid_date(day):
        print("--date must be a real date, YYYY-MM-DD", file=sys.stderr)
        return 2
    return _lessons.create_exclusive(
        SHIPPED_LOG_D / f"{day}-{slug}.md",
        f"## {day} \u2014 {slug.replace('-', ' ')} (PR #NNNN)\n\n{LOG_TEMPLATE_BODY}\n",
    )


def _atomic_write(path: Path, data: bytes) -> None:
    """Replace ``path`` in one step: a crash leaves the old file or the new one, never a torn prefix."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)  # binary + LF: the archives are not rewritten through a text round trip
    os.replace(tmp, path)


def _remove(path: Path) -> None:
    path.unlink()


def _block(frag: Path) -> bytes:
    return frag.read_bytes().rstrip(b"\n") + b"\n"


def _fold() -> int:
    bad = problems()
    if bad:
        print("\n".join(bad), file=sys.stderr)
        print("fix these before folding", file=sys.stderr)
        return 1
    for need in (LESSONS, SHIPPED_LOG, INVARIANTS):
        if not need.is_file():
            print(f"{need} is missing; nothing was changed", file=sys.stderr)
            return 1
    src = INVARIANTS.read_text(encoding="utf-8")
    if len(_CEILING.findall(src)) != 1:
        print("could not find _LESSONS_LINE_CEILING in tests/test_repo_invariants.py exactly once; "
              "nothing was changed", file=sys.stderr)
        return 1
    plan: list[tuple[Path, bytes, list[Path]]] = []
    for archive, d in ((LESSONS, LESSONS_D), (SHIPPED_LOG, SHIPPED_LOG_D)):
        files = _files(d)
        raw = archive.read_bytes()
        out = raw if raw.endswith(b"\n") else raw + b"\n"
        for f in files:
            block = _block(f)
            if _already_in(raw, f):  # already folded by an interrupted run: delete, never append twice
                continue
            out += b"\n" + block
        plan.append((archive, out if out != raw else raw, files))
    for archive, data, _ in plan:
        if data != archive.read_bytes():
            _atomic_write(archive, data)
    moved = 0
    for _, _, files in plan:
        for f in files:  # only now, with BOTH archives written
            _remove(f)
            moved += 1
    n = LESSONS.read_bytes().count(b"\n")
    new = _CEILING.sub(lambda m: f"{m.group(1)}{n}", src, count=1)
    if new != src:  # last, and only when the number moves
        _atomic_write(INVARIANTS, new.encode("utf-8"))
    print(f"folded {moved} fragment(s); LESSONS.md is {n} lines and _LESSONS_LINE_CEILING says so")
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
