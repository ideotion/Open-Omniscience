#!/usr/bin/env python3
"""Diff the "Installed versions" blocks of two CI job logs: which packages were added, removed or changed, and whether the runner moved.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (R349, R364, R380). Two runs of the same code once disagreed (green, then red, no merge between) because pytest 9.2.0 had been published in between and
CI installs ``pytest>=8.2`` unpinned. Finding that took a comparison of the installed versions of a green job and a red one, and the install step prints
them at the HEAD of a log several thousand lines long, which the only available reader (``get_job_logs``, the last N lines) never reaches. The ``Installed
versions`` step (``.github/workflows/ci.yml``, in ``test`` and ``core-only``) therefore prints the list again straight after the test run, on red as well
as green (the last lines of a red job; 3,500 lines from the end of a green ``test`` job, which runs mypy, bandit and pip-audit after it); this script is the
other half: the comparison, done the same way every time, so "diff the package versions first" (R349) is one command and not a by-eye pass over a hundred
lines.

WHAT IT READS. Two job logs (or two step summaries), as files or ``-`` for standard input. Each is the raw log text, with or without the runner's
timestamps, or the JSON that ``get_job_logs`` returns (its ``logs_content``). In each it finds the one block the step prints::

    ### Installed versions
    python 3.13.16, runner image ubuntu24 20261023.334.3, Linux 6.17.0-1022-azure
    ```
    pytest==9.2.0
    ...
    ```

and prints the packages that were added, removed or changed (names compared the way pip compares them: case-insensitive, runs of ``-``, ``_`` and ``.``
alike), and what moved in the environment line (Python, runner image, kernel). Bytes that are not UTF-8 are replaced, not refused, wherever they sit: a log
carries arbitrary output from the tests, and a replaced byte inside a pin line shows in the report as the replacement character.

WHAT IT REFUSES TO GUESS. A log with no such block, a block with no opening fence, a block with no closing fence before the log ends or before the next
step starts (a ``##[`` line or ``Post job cleanup.``), an empty block, a log with more than one block, JSON of another shape, and a source that cannot be
read are each an error that names the log (OLD or NEW) and what was seen, never a comparison against an empty list: a missing block would otherwise read as
"every package was removed". When both are bad, both errors are printed. A line inside the block that is not ``name==version``, and a name listed twice,
are listed in the report, never dropped, and they make the answer "different" (exit 1, "not compared" lines named) unless the two sides carry the very same
such lines: the exit status 0 is "no difference in what could be compared and nothing that could not". The step lists what ``pip`` reports, not what the code
imported, and not the packages of the other jobs: it says which pins differ, not which of them caused a failure.

Usage: ``python scripts/diff_installed_versions.py OLD NEW`` (each a file path or ``-``; at most one ``-``). Exit 0 when the two environments are identical,
1 when they differ (the report says how), 2 when a log cannot be compared (the error says which one and why). Standard library only; no network.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: The three literals the ``Installed versions`` step in ``.github/workflows/ci.yml`` prints; ``tests/test_diff_installed_versions.py`` runs that step's own
#: shell and parses what it prints, so a change to the step that this script cannot read fails there.
HEADING = "### Installed versions"
FENCE = "```"

_BOM = "﻿"
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ")
_PIN = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)==(\S+)$")
_ENVIRONMENT = re.compile(r"^python (?P<python>[^,]+), runner image (?P<image>[^,]+), (?P<kernel>.+)$")
#: A line the runner prints between steps; one inside a block means the block was cut off.
_STEP_BOUNDARY = ("##[", "Post job cleanup.")


class BlockError(Exception):
    """A log whose block cannot be compared; the message names the log and what was found."""


@dataclass
class Block:
    label: str
    heading_line: int
    environment: str | None
    pins: dict[str, tuple[str, str]]  # normalised name -> (name as printed, version)
    unparsed: list[str] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)


def normalise(name: str) -> str:
    """pip's name comparison (PEP 503): case-insensitive, runs of ``-``, ``_`` and ``.`` alike."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _without_bom(text: str) -> str:
    return text[1:] if text.startswith(_BOM) else text


def log_lines(text: str) -> list[str]:
    """The log as plain lines: the ``get_job_logs`` JSON unwrapped, a leading byte-order mark, the runner's timestamps and trailing whitespace removed.

    Lines are split on ``\\n`` alone (so a reported line number is the one ``grep -n`` shows), and a final newline does not make an extra empty line.
    """
    text = _without_bom(text)
    stripped = text.lstrip(" \t\r\n")
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except (ValueError, RecursionError):
            data = None
        if isinstance(data, dict):
            content = data.get("logs_content")
            if not isinstance(content, str):
                raise BlockError("it is a JSON object without a string `logs_content` (the shape get_job_logs returns)")
            text = _without_bom(content)
    raw = text.split("\n")
    if raw and raw[-1] == "":
        raw.pop()
    return [_TIMESTAMP.sub("", line, count=1).rstrip() for line in raw]


def read_block(text: str, label: str) -> Block:
    """The one ``Installed versions`` block in a log; raises BlockError, naming ``label``, when there is not exactly one complete block."""
    try:
        lines = log_lines(text)
    except BlockError as err:
        raise BlockError(f"{label}: {err}") from None
    headings = [i for i, line in enumerate(lines) if line == HEADING]
    if not headings:
        containing = [i for i, line in enumerate(lines) if HEADING in line]
        seen = (
            f"; {len(containing)} other lines contain that text but not as a line of their own (the first, at line {containing[0] + 1}: {lines[containing[0]]!r}):"
            " the runner echoes the step's script, which does, and a log with another prefix on each line would too"
            if containing
            else ""
        )
        raise BlockError(
            f"{label}: no '{HEADING}' line in {len(lines)} lines{seen}. The step prints it after the test run in the test and Core-only jobs; a reader "
            f"that returns only the last lines of a log may start after it, and other jobs do not print it"
        )
    if len(headings) > 1:
        raise BlockError(f"{label}: {len(headings)} blocks (at lines {', '.join(str(i + 1) for i in headings)}); pass the log of one job")
    at = headings[0]
    i = at + 1
    environment = None
    if i < len(lines) and lines[i] != FENCE:
        environment = lines[i]
        i += 1
    if i >= len(lines) or lines[i] != FENCE:
        found = f"the next line is {lines[i]!r}" if i < len(lines) else "the log ends there"
        raise BlockError(f"{label}: the block at line {at + 1} has no opening {FENCE} after its heading ({found})")
    i += 1
    block = Block(label=label, heading_line=at + 1, environment=environment, pins={})
    while True:
        if i >= len(lines):
            raise BlockError(f"{label}: the block at line {at + 1} is cut off: the log ends after {len(block.pins)} package lines, with no closing {FENCE}")
        line = lines[i]
        if line == FENCE:
            break
        if line.startswith(_STEP_BOUNDARY):
            raise BlockError(
                f"{label}: the block at line {at + 1} is cut off: line {i + 1} ({line!r}) comes after {len(block.pins)} package lines and before any closing {FENCE}"
            )
        i += 1
        if not line:
            continue
        match = _PIN.match(line)
        if match is None:
            block.unparsed.append(line)
            continue
        name, version = match.groups()
        key = normalise(name)
        if key in block.pins:
            block.duplicates.append(name)
        else:
            block.pins[key] = (name, version)
    if not block.pins:
        raise BlockError(f"{label}: the block at line {at + 1} lists no name==version line ({len(block.unparsed)} other lines)")
    return block


@dataclass
class Diff:
    environment: list[tuple[str, str, str]]  # (what, old, new)
    changed: list[tuple[str, str, str]]  # (name, old version, new version)
    added: list[tuple[str, str]]
    removed: list[tuple[str, str]]
    unchanged: int
    #: What could not be compared, as sentences; any of it makes the two sides "different".
    uncompared: list[str] = field(default_factory=list)

    @property
    def same(self) -> bool:
        return not (self.environment or self.changed or self.added or self.removed or self.uncompared)


def _environment_fields(line: str | None) -> dict[str, str] | None:
    """The three fields of the step's environment line, or None when the line is absent or not in the step's shape."""
    match = _ENVIRONMENT.match(line) if line is not None else None
    if match is None:
        return None
    return {"python": match["python"], "runner image": match["image"], "kernel": match["kernel"]}


def _environment_changes(old: str | None, new: str | None) -> list[tuple[str, str, str]]:
    if old == new:
        return []
    before, after = _environment_fields(old), _environment_fields(new)
    if before is None or after is None:
        return [("environment line", old if old is not None else "(not printed)", new if new is not None else "(not printed)")]
    return [(what, before[what], after[what]) for what in before if before[what] != after[what]]


def compare(old: Block, new: Block) -> Diff:
    changed = [
        (new.pins[key][0], old.pins[key][1], new.pins[key][1]) for key in sorted(old.pins.keys() & new.pins.keys()) if old.pins[key][1] != new.pins[key][1]
    ]
    added = [(new.pins[key][0], new.pins[key][1]) for key in sorted(new.pins.keys() - old.pins.keys())]
    removed = [(old.pins[key][0], old.pins[key][1]) for key in sorted(old.pins.keys() - new.pins.keys())]
    uncompared = []
    if sorted(old.unparsed) != sorted(new.unparsed):
        uncompared.append("the lines in the block that are not name==version differ between the two logs, and were not compared as packages")
    if old.duplicates or new.duplicates:
        uncompared.append("a name is listed twice on at least one side, so the comparison of that name is ambiguous (the first listing was kept)")
    return Diff(
        environment=_environment_changes(old.environment, new.environment),
        changed=changed,
        added=added,
        removed=removed,
        unchanged=len(old.pins.keys() & new.pins.keys()) - len(changed),
        uncompared=uncompared,
    )


def render(old: Block, new: Block, diff: Diff) -> str:
    out = []
    for block in (old, new):
        out.append(f"{block.label}: block at line {block.heading_line}, {len(block.pins)} packages; {block.environment or 'no environment line'}")
    if diff.environment:
        out.append("environment: " + "; ".join(f"{what} {was} -> {now}" for what, was, now in diff.environment))
    else:
        out.append("environment: unchanged")
    out.append(f"packages: {len(diff.changed)} changed, {len(diff.added)} added, {len(diff.removed)} removed, {diff.unchanged} unchanged")
    if diff.changed:
        out.append("changed:")
        out += [f"  {name} {was} -> {now}" for name, was, now in diff.changed]
    if diff.added:
        out.append("added (only in NEW):")
        out += [f"  {name}=={version}" for name, version in diff.added]
    if diff.removed:
        out.append("removed (only in OLD):")
        out += [f"  {name}=={version}" for name, version in diff.removed]
    for side, block in (("OLD", old), ("NEW", new)):
        if block.unparsed:
            out.append(f"{side}: {len(block.unparsed)} lines in the block are not name==version and were not compared as packages:")
            out += [f"  {line}" for line in block.unparsed]
        if block.duplicates:
            out.append(f"{side}: a name listed twice (the first was kept): {', '.join(block.duplicates)}")
    out += [f"not compared: {sentence}" for sentence in diff.uncompared]
    if diff.same:
        out.append("no difference in the environment line or in any package version")
    return "\n".join(out)


def _read(source: str) -> str:
    """The text of a path or ``-`` (standard input), decoded as UTF-8 with undecodable bytes replaced; an unreadable source raises BlockError."""
    if source == "-":
        stream = getattr(sys.stdin, "buffer", None)
        if stream is None:
            raise BlockError("standard input is not open")
        return stream.read().decode("utf-8", errors="replace")
    try:
        return Path(source).read_bytes().decode("utf-8", errors="replace")
    except OSError as err:
        raise BlockError(f"cannot be read ({err.strerror or err})") from None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args.count("-") > 1:
        print("usage: diff_installed_versions.py OLD NEW   (each a log file or '-' for standard input; at most one '-')", file=sys.stderr)
        return 2
    blocks: dict[str, Block] = {}
    errors = []
    for side, source in zip(("OLD", "NEW"), args, strict=True):
        label = f"{side} ({'<stdin>' if source == '-' else source})"
        try:
            blocks[side] = read_block(_read(source), label)
        except BlockError as err:
            errors.append(str(err) if str(err).startswith(f"{label}:") else f"{label}: {err}")
        except Exception as err:  # noqa: BLE001 - a crash must not exit 1, which means "different"; the reason is named
            errors.append(f"{label}: could not be compared ({type(err).__name__}: {err})")
    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        return 2
    old, new = blocks["OLD"], blocks["NEW"]
    try:
        diff = compare(old, new)
        report = render(old, new, diff)
    except Exception as err:  # noqa: BLE001 - as above: a crash must not read as "different"
        print(f"the two blocks could not be compared ({type(err).__name__}: {err})", file=sys.stderr)
        return 2
    print(report)
    return 0 if diff.same else 1


if __name__ == "__main__":
    sys.exit(main())
