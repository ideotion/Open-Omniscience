#!/usr/bin/env python3
"""Say whether a pull request changes documentation only, so CI can take its fast path (R462).

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

    python scripts/ci_changed_kind.py BASE_SHA HEAD_SHA      # prints docs_only=true|false (also the line the workflow appends to $GITHUB_OUTPUT)
    git diff --name-only A...B | python scripts/ci_changed_kind.py --stdin

FAILS OPEN. Anything this script cannot decide is ``docs_only=false``, which runs the full matrix: an empty change list, a git error, a path
outside the allowlist, a path that is not plain text. The fast path may only be taken on positive evidence. The workflow adds the cases that are
not about paths (a push to main, the weekly run, workflow_dispatch and the ``ci-full`` label are never fast-pathed).

THE ALLOWLIST is deliberately short: everything under ``docs/``, the Markdown files at the repository root, and the two GitHub templates. A file
that code loads at run time lives under ``docs/`` (the legal texts, the user manual served by the app); the fast path still runs every test that
names ``docs/``, ``CLAUDE.md`` or the ledger, and the merge to main runs the whole matrix.
"""

from __future__ import annotations

import fnmatch
import subprocess
import sys

ALLOWED = ("docs/*", "*.md", ".github/ISSUE_TEMPLATE/*", ".github/PULL_REQUEST_TEMPLATE.md")


def is_doc(path: str) -> bool:
    """True for a path the fast path may skip tests for. A path with a parent hop, a NUL or a leading slash is never one."""
    if not path or "\x00" in path or path.startswith("/") or ".." in path.split("/"):
        return False
    if "/" in path and path.endswith(".md") and not path.startswith(("docs/", ".github/")):
        return False  # a Markdown file below the root outside docs/ (configs/, scripts/) ships with code: not a doc change
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in ALLOWED)


def docs_only(paths: list[str]) -> bool:
    """True only when there is at least one path and every path is a documentation path."""
    names = [p.strip() for p in paths if p.strip()]
    return bool(names) and all(is_doc(p) for p in names)


def changed_paths(base: str, head: str) -> list[str] | None:
    """The paths ``base...head`` changes, or None when git cannot say (renames are shown as delete + add so both sides are judged)."""
    done = subprocess.run(["git", "diff", "--name-only", "--no-renames", f"{base}...{head}"], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        return None
    return done.stdout.splitlines()


def main(argv: list[str]) -> int:
    if argv == ["--stdin"]:
        paths: list[str] | None = sys.stdin.read().splitlines()
    elif len(argv) == 2:
        paths = changed_paths(argv[0], argv[1])
    else:
        print(__doc__)
        return 2
    verdict = paths is not None and docs_only(paths)
    print(f"docs_only={'true' if verdict else 'false'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
