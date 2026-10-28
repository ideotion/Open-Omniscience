#!/usr/bin/env python3
"""Write the real PR number into the ledger fragments THIS BRANCH added, once the number exists.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY. A PR's number exists only after the PR is opened, and a number guessed from GitHub's counter is a
guess (it matched once and is not to be relied on). So a branch's ledger fragments carry the template
placeholder on the first push and the real number goes in right after, in one small sweep commit. This
script is that sweep, so nobody rewrites the same three tokens by hand across a handful of files:

    python scripts/sweep_pr_number.py 1636              # rewrite, print every change
    python scripts/sweep_pr_number.py 1636 --dry-run    # print what it would change, write nothing
    python scripts/sweep_pr_number.py 1636 --base REF   # REF defaults to origin/main (see WHICH FILES)

WHAT IT REWRITES, and only this: the placeholders ``scripts/ledger_fold.py`` and the ledger tests already
refuse -- ``PR pending`` becomes ``PR #1636`` and ``#NNNN`` becomes ``#1636``.

    docs/ledger/lessons.d/*.md and docs/ledger/shipped_log.d/*.md   prose only, where "prose" is exactly
        ``ledger_fold._prose``'s rule and no better: a line that starts with three backticks or three tildes
        opens or closes a fence (whatever the character or length, so a backtick fence quoted inside a ``~~~``
        block is read as prose), and `inline code` is one pair of single backticks (a double-backtick span is
        read as prose). A lesson may quote a placeholder inside what that rule keeps; anything else is rewritten.
    docs/ledger/shipped.d/*.csv                                      the ``refs`` cell only (protocol rule
        (5b) and ``test_the_real_fragments_are_well_formed_and_carry_no_placeholder`` both look nowhere
        else). The other cells are byte-for-byte what they were, whatever quoting the row was written with.

WHICH FILES. Fragments the branch ADDED relative to ``git merge-base BASE HEAD`` (``--diff-filter=A``, no
rename detection), and no other. A fragment that is already on BASE is another PR's and is never touched,
even if it carries a placeholder; a fragment that is not committed yet is not seen at all (commit it, then
sweep: the sweep reads what the branch has added and rewrites the working-tree copy). A branch STACKED on
another unmerged branch passes that branch as ``--base``; the list is printed with the merge-base so the
choice is visible. ``origin/main`` is whatever the clone last fetched: ``git fetch origin main`` first.

IT REFUSES, touching nothing, when the number is not a positive integer (``1636``, not ``#1636``); when BASE
does not resolve; when the branch added no fragment at all; when a fragment is a symlink, not UTF-8, or (a
csv) not the ledger's header plus exactly one row or one the csv module cannot read; when a path runs through
a symlink or a file name is not UTF-8; when a markdown fence is never closed; when a placeholder would SURVIVE the
rewrite -- judged by the ledger's own test, ``ledger_fold._PLACEHOLDER`` over the WHOLE prose (so a token split
by a line break is found) and, in a csv, by the shipped.d guard's rule that no ``pending`` stays in ``refs``: a
token this script has no rule for (add it to ``_RULES``), or one split by a line break, a code span or a quote
(edit it by hand); or when the rewritten csv differs from the original in any cell other than ``refs``. A branch
whose fragments carry no placeholder is not an error: it says so and exits 0, so the script is safe to run twice.

EXIT: 0 swept (or nothing to sweep), 2 refused before writing anything, 1 a write failed part-way (the
files already replaced are named; run it again, which finishes the rest).
"""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:  # `python -I` and an importlib load do not put scripts/ on the path
    sys.path.insert(0, str(_HERE))
import ledger_fold as _fold  # noqa: E402
import ledger_shipped as _shipped  # noqa: E402

ROOT = _HERE.parent
_NUMBER = re.compile(r"[1-9][0-9]{0,8}")
# The tokens this script rewrites, each with what it becomes. ``ledger_fold._PLACEHOLDER`` is the list of what
# the ledger REFUSES; a token it learns that is not here survives the rewrite, and the survivor check below
# refuses it by name instead of leaving it.
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bPR\s+pending\b", re.IGNORECASE), "PR #{n}"),
    (re.compile(r"#NNNN(?!\w)", re.IGNORECASE), "#{n}"),  # not `#NNNNN`: a typo is refused by name, never turned into `#1636N`
)
_REFS = _shipped.HEADER.index("refs")
_SHOWN = 110  # characters of a survivor printed in a refusal
_CONTEXT = 45  # characters printed on each side of the first change in a changed line


class Refused(Exception):
    """A precondition failed; nothing was written."""


class GitMissing(Refused):
    """``git`` itself could not be started: no later message may blame the ref."""


def _constant(value: str) -> Callable[[re.Match[str]], str]:
    """A replacement taken literally (a plain string would read ``\\`` and ``\\1`` as template syntax)."""
    return lambda _match: value


def _sub(text: str, number: str) -> str:
    for rx, becomes in _RULES:
        text = rx.sub(_constant(becomes.format(n=number)), text)
    return text


def _count(text: str) -> int:
    return sum(len(rx.findall(text)) for rx, _ in _RULES)


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(  # nosec B603 B607 -- fixed argv, no shell; the one user-supplied ref is checked below
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="surrogateescape",  # a file name that is not UTF-8 reaches added_fragments, which refuses it by name
            check=False,
        )
    except OSError as exc:
        raise GitMissing(f"git could not be run ({exc.strerror or exc})") from None
    if done.returncode:
        raise Refused(f"git {' '.join(args[:2])} failed: {done.stderr.strip() or 'no message'}")
    return done.stdout


def _base_sha(root: Path, base: str) -> str:
    if base.startswith("-"):
        raise Refused(f"--base {base!r} is not a ref")
    try:
        _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    except GitMissing:
        raise
    except Refused:
        raise Refused(f"{base!r} does not resolve to a commit here; `git fetch origin main` or pass --base REF") from None
    try:
        return _git(root, "merge-base", base, "HEAD").strip()
    except GitMissing:
        raise
    except Refused:
        raise Refused(
            f"{base!r} and HEAD have no common ancestor here: a shallow clone (`git fetch --unshallow`) or the wrong --base"
        ) from None


def _kinds() -> dict[str, str]:
    """Each fragment directory, relative to the repository root, with the kind of file in it."""
    here = _fold.ROOT
    return {
        _fold.LESSONS_D.relative_to(here).as_posix(): ".md",
        _fold.SHIPPED_LOG_D.relative_to(here).as_posix(): ".md",
        _shipped.fragment_dir(_shipped.LEDGER / "shipped.csv").relative_to(here).as_posix(): ".csv",
    }


def added_fragments(root: Path, merge_base: str) -> list[str]:
    kinds = _kinds()
    out = _git(root, "diff", "--name-only", "--no-renames", "--diff-filter=A", "--relative", "-z",
               merge_base, "HEAD", "--", *kinds)
    keep = []
    for rel in sorted(p for p in out.split("\0") if p):
        parent, _, name = rel.rpartition("/")
        if kinds.get(parent) and name.endswith(kinds[parent]):
            if any("\udc80" <= ch <= "\udcff" for ch in rel):
                raise Refused(f"{rel!r}: the file name is not valid UTF-8; rename it")
            keep.append(rel)
    return keep


def sweep_markdown(name: str, text: str, number: str) -> tuple[str, list[tuple[int, str, str]]]:
    """The text with each placeholder outside a fence and outside `inline code` rewritten, plus the changed lines."""
    changes: list[tuple[int, str, str]] = []
    out: list[str] = []
    in_fence = False
    for n, line in enumerate(text.split("\n"), 1):
        if _fold._FENCE.match(line):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue
        new, pos, parts = line, 0, []
        for code in _fold._INLINE_CODE.finditer(line):
            parts += [_sub(line[pos:code.start()], number), code.group(0)]
            pos = code.end()
        parts.append(_sub(line[pos:], number))
        new = "".join(parts)
        if new != line:
            changes.append((n, line, new))
        out.append(new)
    if in_fence:
        raise Refused(f"{name}: an unclosed code fence; the rest of the file cannot be told from quoted text")
    return "\n".join(out), changes


def _spans(text: str) -> list[list[tuple[int, int]]]:
    """The (start, end) of every field of every record of ``text``, read the way ``csv`` reads it (quotes
    open only at the start of a field, ``""`` is a literal quote, a newline inside quotes is data)."""
    records: list[list[tuple[int, int]]] = []
    fields: list[tuple[int, int]] = []
    start, i, in_quotes, at_start = 0, 0, False, True
    while i < len(text):
        c = text[i]
        if in_quotes:
            if c == '"':
                if text[i + 1:i + 2] == '"':
                    i += 2
                    continue
                in_quotes = False
        elif c == '"' and at_start:
            in_quotes = True
        elif c == ",":
            fields.append((start, i))
            start, at_start, i = i + 1, True, i + 1
            continue
        elif c in "\r\n":
            fields.append((start, i))
            records.append(fields)
            fields = []
            i += 2 if text.startswith("\r\n", i) else 1
            start, at_start = i, True
            continue
        at_start = False
        i += 1
    if start < len(text) or fields:
        fields.append((start, len(text)))
        records.append(fields)
    return records


def _rows(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline="")))


def sweep_csv(name: str, text: str, number: str) -> tuple[str, list[tuple[int, str, str]]]:
    """The fragment with the placeholders in its ``refs`` cell rewritten, every other byte as it was."""
    before = _rows(text)
    spans = _spans(text)
    if before[:1] != [_shipped.HEADER] or len(before) != 2 or len(before[1]) != len(_shipped.HEADER):
        raise Refused(f"{name}: not the ledger header plus exactly one {len(_shipped.HEADER)}-field row")
    if len(spans) != 2 or any(len(r) != len(_shipped.HEADER) for r in spans):
        raise Refused(f"{name}: the fields could not be located the way csv reads them; edit refs by hand")
    a, b = spans[1][_REFS]
    new_text = text[:a] + _sub(text[a:b], number) + text[b:]
    if new_text == text:
        return text, []
    after = _rows(new_text)
    same = [x for k, x in enumerate(before[1]) if k != _REFS] == [x for k, x in enumerate(after[1]) if k != _REFS]
    if after[0] != before[0] or len(after) != 2 or not same or after[1][_REFS] != _sub(before[1][_REFS], number):
        raise Refused(f"{name}: the rewrite would change more than the refs cell; edit refs by hand")
    return new_text, [(2, before[1][_REFS], after[1][_REFS])]


def _prose_placeholders(text: str) -> list[str]:
    """What the ledger's own check finds: ``_PLACEHOLDER`` over the whole prose, so ``PR`` at the end of a line
    and ``pending`` at the start of the next is found as the ledger finds it."""
    return [m.group(0) for m in _fold._PLACEHOLDER.finditer(_fold._prose(text))]


def _shown(text: str) -> str:
    text = text.replace("\n", " ")
    return text if len(text) <= _SHOWN else text[: _SHOWN - 1] + "…"


def _excerpts(was: str, now: str) -> tuple[str, str]:
    """``was`` and ``now`` cut to the same window around the first character that differs."""
    at = next((i for i, (a, b) in enumerate(zip(was, now, strict=False)) if a != b), min(len(was), len(now)))
    lo = max(0, at - _CONTEXT)

    def cut(text: str) -> str:
        end = at + _CONTEXT
        return ("…" if lo else "") + text[lo:end].replace("\n", " ") + ("…" if len(text) > end else "")

    return cut(was), cut(now)


def plan(root: Path, rels: list[str], number: str) -> list[tuple[str, bytes, bytes, list[tuple[int, str, str]]]]:
    """(relative path, old bytes, new bytes, changed lines) for every fragment; nothing is written here."""
    out = []
    for rel in rels:
        path = root / rel
        if path.is_symlink() or os.path.normcase(path.resolve()) != os.path.normcase(root.resolve() / rel):
            raise Refused(f"{rel}: a symlink, or reached through one; a fragment is a regular file and a link is never followed")
        if not path.is_file():
            print(f"skipped {rel}: added by the branch but no longer in the working tree")
            continue
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise Refused(f"{rel}: not valid UTF-8 ({exc.reason})") from None
        if rel.endswith(".csv"):
            try:
                _shipped.read_fragment(path)
                new, changes = sweep_csv(rel, text, number)
            except ValueError as exc:
                raise Refused(str(exc)) from None
            except csv.Error as exc:
                raise Refused(f"{rel}: not readable as csv ({exc})") from None
            left = [c[2] for c in changes] or [_rows(new)[1][_REFS]]
            # the shipped.d guard (tests/test_ledger_shipped_fragments.py) refuses ANY `pending` in refs, not only `PR pending`
            survivors = [x for x in left if _fold._PLACEHOLDER.search(x) or "pending" in x.lower()]
        else:
            new, changes = sweep_markdown(rel, text, number)
            survivors = _prose_placeholders(new)
        if survivors:
            raise Refused(
                f"{rel}: a placeholder would remain after the rewrite: {_shown(survivors[0])!r} (a token this script has no rule for, "
                "or one split by a line break, a code span or a quote: add the rule to _RULES, or edit it by hand)"
            )
        out.append((rel, raw, new.encode("utf-8"), changes))
    return out


def _replace(path: Path, data: bytes) -> None:
    """Replace ``path`` in one step (a unique temporary beside it, then ``os.replace``), keeping its mode."""
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".sweep-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        shutil.copymode(path, tmp)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def run(root: Path, number: str, base: str, dry_run: bool) -> int:
    if not _NUMBER.fullmatch(number):
        raise Refused(f"the PR number must be a positive integer such as 1636 (digits only, no '#'), not {number!r}")
    merge_base = _base_sha(root, base)
    rels = added_fragments(root, merge_base)
    if not rels:
        raise Refused(f"this branch adds no ledger fragment since {base} ({merge_base[:12]}); nothing to sweep "
                      "(commit the fragments first: only what the branch has added is swept)")
    print(f"base {base}, merge-base {merge_base[:12]}; {len(rels)} fragment(s) added by this branch")
    todo = plan(root, rels, number)
    changed = [t for t in todo if t[3]]
    for rel, _old, _new, changes in changed:
        print(rel)
        for n, was, now in changes:
            before, after = _excerpts(was, now)
            print(f"  line {n}:\n    - {before}\n    + {after}")
    clean = len(todo) - len(changed)
    placeholders = sum(_count(was) - _count(now) for *_head, ch in changed for _n, was, now in ch)
    if not changed:
        print(f"nothing to sweep: none of the {len(todo)} fragment(s) carries a placeholder")
        return 0
    if dry_run:
        print(f"dry run: would rewrite {placeholders} placeholder(s) in {len(changed)} file(s); {clean} already clean")
        return 0
    done: list[str] = []
    try:
        for rel, _old, new, _changes in changed:
            _replace(root / rel, new)
            done.append(rel)
    except OSError as exc:
        print(f"write failed after {len(done)} of {len(changed)} file(s) ({exc}); replaced: {', '.join(done) or 'none'}; "
              "run it again to finish", file=sys.stderr)
        return 1
    print(f"swept {placeholders} placeholder(s) in {len(changed)} file(s) to #{number}; {clean} already clean")
    print("next: python scripts/ledger_fold.py check && python scripts/ledger_shipped.py check "
          "&& python -m pytest -q tests/test_ledger_shipped_fragments.py, then commit the sweep")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("number", help="the PR's number as GitHub gave it when the PR was opened, digits only")
    ap.add_argument("--base", default="origin/main", help="the branch's base (default origin/main); see WHICH FILES")
    ap.add_argument("--dry-run", action="store_true", help="print the changes, write nothing")
    ap.add_argument("--root", default=str(ROOT), help="the repository to sweep (default: the one this script is in)")
    args = ap.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):  # a console or pipe that cannot encode a changed line must not turn a sweep into a crash
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(errors="backslashreplace")
    try:
        return run(Path(args.root).resolve(), args.number, args.base, args.dry_run)
    except Refused as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
