#!/usr/bin/env python3
"""Diff the "Installed versions" blocks of two CI job logs: which packages were added, removed or changed, and whether the runner moved.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

WHY (R349, R364, R380). Two runs of the same code once disagreed (green, then red, no merge between) because pytest 9.2.0 had been published in between and
CI installs ``pytest>=8.2`` unpinned. Finding that took a comparison of the installed versions of a green job and a red one, and the install step prints
them at the HEAD of a log several thousand lines long, which the only available reader (``get_job_logs``, the last N lines) never reaches. The ``Installed
versions`` step (``.github/workflows/ci.yml``, in ``test`` and ``core-only``) therefore prints the list again at the END of the job, on red as well as
green; this script is the other half: the comparison, done the same way every time, so "diff the package versions first" (R349) is one command and not a
by-eye pass over two hundred lines.

WHAT IT READS. Two job logs (or two step summaries), as files or ``-`` for standard input. Each is the raw log text, with or without the runner's
timestamps, or the JSON that ``get_job_logs`` returns (its ``logs_content``). In each it finds the one block the step prints::

    ### Installed versions
    python 3.13.16, runner image ubuntu24 20261023.334.3, Linux 6.17.0-1022-azure
    ```
    pytest==9.2.0
    ...
    ```

and prints the packages that were added, removed or changed (names compared the way pip compares them: case-insensitive, ``-``, ``_`` and ``.`` alike),
and what moved in the environment line (Python, runner image, kernel).

WHAT IT REFUSES TO GUESS. A log with no such block, a block with no closing fence, an empty block, and a log with more than one block are each an error
that names the log (OLD or NEW) and what was seen, never a comparison against an empty list: a missing block would otherwise read as "every package was
removed". A line inside the block that is not ``name==version`` is listed, not dropped. The step lists what ``pip`` reports, not what the code imported,
and not the packages of the other jobs: it says which pins differ, not which of them caused a failure.

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

_TIMESTAMP = re.compile(r"^\ufeff?\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z ")
_PIN = re.compile(r"^([A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?)==(\S+)$")
_ENVIRONMENT = re.compile(r"^python (?P<python>[^,]+), runner image (?P<image>[^,]+), (?P<kernel>.+)$")


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


def log_lines(text: str) -> list[str]:
    """The log as plain lines: the ``get_job_logs`` JSON unwrapped, the runner's timestamps and trailing whitespace removed."""
    stripped = text.lstrip("\ufeff \t\r\n")
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped)
        except ValueError:
            data = None
        if isinstance(data, dict):
            content = data.get("logs_content")
            if not isinstance(content, str):
                raise BlockError("it is a JSON object without a string `logs_content` (the shape get_job_logs returns)")
            text = content
    return [_TIMESTAMP.sub("", line, count=1).rstrip() for line in text.splitlines()]


def read_block(text: str, label: str) -> Block:
    """The one ``Installed versions`` block in a log; raises BlockError, naming ``label``, when there is not exactly one complete block."""
    try:
        lines = log_lines(text)
    except BlockError as err:
        raise BlockError(f"{label}: {err}") from None
    headings = [i for i, line in enumerate(lines) if line == HEADING]
    if not headings:
        raise BlockError(
            f"{label}: no '{HEADING}' line in {len(lines)} lines. The step prints it after the test run in the test and Core-only jobs; a reader "
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
    while i < len(lines) and lines[i] != FENCE:
        line = lines[i]
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
    if i >= len(lines):
        raise BlockError(f"{label}: the block at line {at + 1} is cut off: no closing {FENCE} after {len(block.pins)} package lines")
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

    @property
    def same(self) -> bool:
        return not (self.environment or self.changed or self.added or self.removed)


def _environment_fields(line: str | None) -> dict[str, str]:
    if line is None:
        return {}
    match = _ENVIRONMENT.match(line)
    if match is None:
        return {"environment line": line}
    return {"python": match["python"], "runner image": match["image"], "kernel": match["kernel"]}


def compare(old: Block, new: Block) -> Diff:
    before, after = _environment_fields(old.environment), _environment_fields(new.environment)
    environment = []
    for what in [*before, *(k for k in after if k not in before)]:
        was, now = before.get(what, "(not printed)"), after.get(what, "(not printed)")
        if was != now:
            environment.append((what, was, now))
    changed = [
        (new.pins[key][0], old.pins[key][1], new.pins[key][1]) for key in sorted(old.pins.keys() & new.pins.keys()) if old.pins[key][1] != new.pins[key][1]
    ]
    added = [(new.pins[key][0], new.pins[key][1]) for key in sorted(new.pins.keys() - old.pins.keys())]
    removed = [(old.pins[key][0], old.pins[key][1]) for key in sorted(old.pins.keys() - new.pins.keys())]
    unchanged = len(old.pins.keys() & new.pins.keys()) - len(changed)
    return Diff(environment=environment, changed=changed, added=added, removed=removed, unchanged=unchanged)


def render(old: Block, new: Block, diff: Diff) -> str:
    out = []
    for block in (old, new):
        out.append(f"{block.label}: block at line {block.heading_line}, {len(block.pins)} packages; {block.environment or 'no environment line'}")
    if diff.environment:
        out.append("environment: " + "; ".join(f"{what} {was} -> {now}" for what, was, now in diff.environment))
    else:
        out.append("environment: unchanged")
    out.append(
        f"packages: {len(diff.changed)} changed, {len(diff.added)} added, {len(diff.removed)} removed, {diff.unchanged} unchanged"
    )
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
            out.append(f"{side}: {len(block.unparsed)} lines in the block are not name==version and were not compared:")
            out += [f"  {line}" for line in block.unparsed]
        if block.duplicates:
            out.append(f"{side}: a name listed twice (the first was kept): {', '.join(block.duplicates)}")
    if diff.same:
        out.append("no difference in the environment line or in any package version")
    return "\n".join(out)


def _read(source: str) -> tuple[str, str]:
    """(label, text) of a path or ``-``; an unreadable path raises BlockError."""
    if source == "-":
        return "<stdin>", sys.stdin.read()
    try:
        return source, Path(source).read_text(encoding="utf-8", errors="replace")
    except OSError as err:
        raise BlockError(f"{source}: cannot be read ({err.strerror or err})") from None


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2 or args.count("-") > 1:
        print("usage: diff_installed_versions.py OLD NEW   (each a log file or '-' for standard input; at most one '-')", file=sys.stderr)
        return 2
    blocks: dict[str, Block] = {}
    errors = []
    for side, source in zip(("OLD", "NEW"), args, strict=True):
        try:
            label, text = _read(source)
            blocks[side] = read_block(text, f"{side} ({label})")
        except BlockError as err:
            errors.append(str(err) if str(err).startswith(side) else f"{side}: {err}")
    if errors:
        for line in errors:
            print(line, file=sys.stderr)
        return 2
    old, new = blocks["OLD"], blocks["NEW"]
    diff = compare(old, new)
    print(render(old, new, diff))
    return 0 if diff.same else 1


if __name__ == "__main__":
    sys.exit(main())
