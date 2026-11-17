#!/usr/bin/env python3
"""
The weekly suite on the lock's own pins (row 114): its constraints file and its one rolling issue.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

The PR test jobs install ``-e ".[...]"`` unbounded, so they run on the NEWEST release of every dependency
(R318/R412 kept that on purpose: a break a new release brings shows on the next PR). A user who installs from
``requirements.lock`` runs on the lock's pins instead, and nothing ran the suite there: on SQLAlchemy 2.0.51 (the
lock) five tests failed that were green in CI on 2.1.x (row 113). ``.github/workflows/lock-suite.yml`` runs the
whole suite once a week with every package the lock names held to its pin, and this script does its two parts:

``constraints LOCK OUT``  writes a pip constraints file of plain ``name==version`` lines from the lock. pip refuses
                          the lock itself as constraints ("Constraints cannot have extras"), and the lock covers only
                          the core and ``[analysis]``, so a package only another extra brings (``[dev]``, ``[ocr]``,
                          ...) still resolves to its newest release: said in the issue, not hidden.
``report DIR``            reads the shards' outcomes and junit files and opens, updates or closes ONE issue (label
                          ``lock-suite``), the shape of ``scripts/freshness_issue.py``. It never fails the workflow.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET  # nosec B405 - parses the run's own junit files, not untrusted input
from pathlib import Path

_LABEL = "lock-suite"
_TITLE = "Suite fails on the requirements.lock pins"
#: A pinned line of a pip-compile lock: ``name==version`` or ``name[extra,...]==version``, then hashes or a comment.
_PIN = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?==([^\s;\\]+)")
#: The most failed test ids the issue lists by name; the count is always whole.
_SHOWN = 40


def constraints_from_lock(text: str) -> list[str]:
    """Every pin of the lock as ``name==version``, in the lock's order: no hashes, no extras, no markers."""
    out = []
    for line in text.splitlines():
        m = _PIN.match(line)
        if m:
            out.append(f"{m.group(1)}=={m.group(2)}")
    return out


def failures_from_junit(paths: list[Path]) -> tuple[list[str], list[str]]:
    """``(failed test ids, junit files that could not be read)``. A failure and an error both count."""
    failed: list[str] = []
    unreadable: list[str] = []
    for p in paths:
        try:
            root = ET.parse(p).getroot()  # nosec B314 - the run's own junit output
        except (OSError, ET.ParseError):
            unreadable.append(str(p))
            continue
        for case in root.iter("testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                cls = case.get("classname", "")
                failed.append(f"{cls}::{case.get('name', '')}" if cls else case.get("name", ""))
    return sorted(set(failed)), unreadable


def build_issue_body(
    outcomes: dict[str, str], failed: list[str], unreadable: list[str], run_url: str, pins: dict[str, str]
) -> tuple[bool, str]:
    """``(actionable, markdown)``. Actionable when any shard did not succeed: a red, cancelled or skipped shard is a
    week the lock's pins were not shown to pass, which is the one thing this run exists to say."""
    bad = {s: o for s, o in sorted(outcomes.items()) if o != "success"}
    actionable = bool(bad) or not outcomes
    lines = [
        "_Automated by `.github/workflows/lock-suite.yml` (weekly). One rolling issue; it closes itself when every "
        "shard passes on the lock's pins._",
        "",
        f"Run: {run_url}" if run_url else "Run: (no URL)",
        "",
    ]
    if not outcomes:
        lines += ["No shard reported an outcome.", ""]
    else:
        lines.append("| Shard | Outcome |")
        lines.append("|---|---|")
        lines += [f"| {s} | {o} |" for s, o in sorted(outcomes.items())]
        lines.append("")
    if failed:
        lines.append(f"### {len(failed)} failed test(s)")
        lines += [f"- `{t}`" for t in failed[:_SHOWN]]
        if len(failed) > _SHOWN:
            lines.append(f"- ... and {len(failed) - _SHOWN} more (the run's junit artifacts list them all)")
        lines.append("")
    elif bad:
        lines += ["No failed test was read from the junit files: a shard that did not finish has none.", ""]
    if unreadable:
        lines += [f"<sub>junit not readable: {', '.join(unreadable)}</sub>", ""]
    if pins:
        lines.append("Pins of note: " + ", ".join(f"{k} {v}" for k, v in sorted(pins.items())) + ".")
        lines.append("")
    lines.append(
        "These tests pass on the PR jobs, which install every dependency at its newest release. A failure here "
        "is a behaviour of an OLDER release a user installing from `requirements.lock` runs: fix the test or the "
        "code so both hold, or move the lock (`docs/maintenance/EXTERNAL_DEPENDENCIES.md`). Packages the lock does "
        "not name (only the `[dev]`, `[segmentation]`, `[pdf]`, `[ocr]` and `[geo]` extras bring them) resolve to "
        "their newest release here too."
    )
    return actionable, "\n".join(lines)


def _gh(args: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)  # nosec B603 B607 - fixed argv
        return p.returncode, (p.stdout or p.stderr).strip()
    except Exception as e:  # noqa: BLE001 - gh missing / not authed (a local run)
        return 127, f"gh unavailable: {e}"


def _existing_issue() -> int | None:
    _gh(["label", "create", _LABEL, "--color", "D93F0B", "--description", "Suite fails on the lock's pins", "--force"])
    rc, out = _gh(["issue", "list", "--label", _LABEL, "--state", "open", "--json", "number", "--jq", ".[0].number"])
    return int(out) if rc == 0 and out.strip().isdigit() else None


def report(directory: Path) -> int:
    """Read ``outcomes.json`` (shard -> outcome) and every ``**/junit.xml`` under ``directory``; sync the issue."""
    try:
        outcomes = json.loads((directory / "outcomes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        outcomes = {}
    failed, unreadable = failures_from_junit(sorted(directory.glob("**/junit.xml")))
    pins = {}
    lock = Path("requirements.lock")
    if lock.exists():
        for pin in constraints_from_lock(lock.read_text(encoding="utf-8")):
            name, ver = pin.split("==", 1)
            if name.lower() in {"sqlalchemy", "fastapi", "pydantic", "starlette"}:
                pins[name] = ver
    run_url = ""
    if os.environ.get("GITHUB_RUN_ID"):
        run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
    actionable, body = build_issue_body(outcomes, failed, unreadable, run_url, pins)
    print(body)
    body_file = directory / "lock_suite_issue_body.md"
    body_file.write_text(body, encoding="utf-8")
    if os.environ.get("GITHUB_ACTIONS") != "true":
        # A local run never touches the repository's issues or labels: only the workflow does.
        print(f"not on GitHub Actions: issue left alone (actionable={actionable}); body in {body_file}")
        return 0
    existing = _existing_issue()
    if actionable:
        if existing:
            _rc, out = _gh(["issue", "edit", str(existing), "--body-file", str(body_file)])
            print(f"updated issue #{existing}: {out}")
        else:
            _rc, out = _gh(["issue", "create", "--title", _TITLE, "--label", _LABEL, "--body-file", str(body_file)])
            print(f"created issue: {out}")
    elif existing:
        _rc, out = _gh(["issue", "close", str(existing), "--comment", "Every shard passes on the lock's pins again."])
        print(f"closed issue #{existing}: {out}")
    else:
        print("every shard passed on the lock's pins; no open issue.")
    return 0  # a watch must not fail the workflow


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[0] == "constraints":
        pins = constraints_from_lock(Path(argv[1]).read_text(encoding="utf-8"))
        if not pins:
            print(f"no pins read from {argv[1]}", file=sys.stderr)
            return 1
        Path(argv[2]).write_text("\n".join(pins) + "\n", encoding="utf-8")
        print(f"{len(pins)} pins from {argv[1]} -> {argv[2]}")
        return 0
    if len(argv) == 2 and argv[0] == "report":
        return report(Path(argv[1]))
    print("usage: lock_suite.py constraints LOCK OUT | report DIR", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
