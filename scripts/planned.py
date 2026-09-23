#!/usr/bin/env python3
"""Ask what has ALREADY been decided about a file, before changing it.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

    python scripts/planned.py src/config/memory_budget.py
    python scripts/planned.py --diff                 # every path this branch changes
    python scripts/planned.py --diff --strict        # CI: fail on a blocked/forbidden path

WHY (maintainer-asked 2026-09-22). Thirty-eight slice briefs, seven gate files and 400-odd
rulings already decide things about files a session is free to open at any time, and the
only instruction to consult them says to do it "before asking the maintainer anything" --
never "before editing a file". The cost is recorded: `LESSONS.md` holds a session that
trusted a stale code comment and spent one of the maintainer's decisions re-ratifying a
setting the ledger had already ruled.

WHAT IT DOES NOT DO. It never judges whether your change CONTRADICTS a plan -- it says what
the plan is and where to read it. A tool that guessed would be a composite verdict over
prose, and its false negatives ("nothing is planned here") would be the expensive ones.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

#: The two statuses that mean "do not decide this yourself": a brief that forbids the file,
#: and a ruling that names it and is itself unanswered. ``--strict`` exits non-zero on these
#: and on nothing else -- a lint that fires on every planned file is one every session
#: learns to pass with --no-verify.
#:
#: A SLICE being blocked is NOT one of them. That means the slice cannot START; it never
#: means the file is untouchable. Conflating the two made the first cut fail on
#: `src/static/index.html`, which nearly every PR edits.
_HARD = ("must-not-touch", "pending-ruling")

#: Strict only looks at code. The ledger, the gate files and the briefs are the RECORD of
#: decisions, not their subject -- and editing them in the turn a ruling is given is what
#: THE PROTOCOL requires, so failing a PR for doing it would be the tool arguing with the
#: rule it exists to serve.
_CODE_ROOTS = ("src/", "tests/", "scripts/", "alembic/", "configs/", ".github/")

_MARK = {
    "must-not-touch": "FORBIDDEN ",
    "pending-ruling": "UNANSWERED",
    "slice-blocked": "SLICE HELD",
    "row-blocked": "ROW OPEN  ",
    "precondition": "WAITS ON  ",
    "open": "OPEN      ",
    "planned": "PLANNED   ",
    "ruled": "RULED     ",
    "more": "...       ",
}


def rows() -> list[dict[str, str]]:
    """Build the index NOW rather than reading a committed copy.

    NO LOCKFILE, DELIBERATELY. A checked-in index would be a third thing to remember to
    regenerate, in a repository whose ledger changes every session -- so it would be stale
    most of the time, and a stale answer here is worse than no tool, because it reads as
    authoritative. Generation is a quarter of a second against the whole tree, which is
    cheaper than the staleness would be."""
    import planned_index

    return [
        {"path": e.path, "id": e.id, "kind": e.kind,
         "status": e.status, "title": e.title, "where": e.where}
        for e in planned_index.build()
    ]


def lookup(paths: list[str], index: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Exact match, plus any DIRECTORY entry that contains the path.

    A brief that says it owns ``src/versioned/`` owns every file under it, and a session
    editing one of those files is exactly the reader this exists for."""
    out: dict[str, list[dict[str, str]]] = {}
    for p in paths:
        hits = [r for r in index if r["path"] == p
                or (r["path"].endswith("/") and p.startswith(r["path"]))]
        if hits:
            out[p] = hits
    return out


def changed_paths(base: str) -> list[str]:
    try:
        merge_base = subprocess.run(["git", "merge-base", base, "HEAD"], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout.strip()
        diff = subprocess.run(["git", "diff", "--name-only", merge_base, "HEAD"], cwd=ROOT,
                              capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError as exc:
        print(f"could not read the diff against {base}: {exc}", file=sys.stderr)
        return []
    return [ln for ln in diff.split("\n") if ln.strip()]


def acknowledged(base: str) -> set[str]:
    """Ids this branch's commit messages already ACK, e.g. ``ACK Q823``.

    An acknowledgement is not permission -- it is the author saying, in the permanent
    record, that they read the blocked decision before touching its file."""
    try:
        merge_base = subprocess.run(["git", "merge-base", base, "HEAD"], cwd=ROOT,
                                    capture_output=True, text=True, check=True).stdout.strip()
        log = subprocess.run(["git", "log", "--format=%B", f"{merge_base}..HEAD"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        return set()
    import re
    return set(re.findall(r"\bACK\s+([A-Za-z0-9.\- ]{2,30}?)\s*(?:$|[,.\n])", log, re.M))


def report(found: dict[str, list[dict[str, str]]]) -> None:
    for path, hits in sorted(found.items()):
        print(f"\n{path}")
        for r in hits:
            print(f"  {_MARK.get(r['status'], r['status']):<10} {r['id']:<22} {r['title'][:96]}")
            print(f"  {'':<10} {'':<22} -> {r['where']}")


def main(argv: list[str]) -> int:
    index = rows()
    if not index:
        return 1
    strict = "--strict" in argv
    argv = [a for a in argv if a != "--strict"]

    if "--diff" in argv:
        i = argv.index("--diff")
        base = argv[i + 1] if len(argv) > i + 1 and not argv[i + 1].startswith("-") else "origin/main"
        paths = changed_paths(base)
        acks = acknowledged(base)
    else:
        paths, base, acks = argv, "", set()

    if not paths and "--diff" in sys.argv:
        # A SILENT PASS IS A LIE HERE. A shallow CI checkout with no common history makes
        # the diff unreadable, and the check would otherwise report success having looked
        # at nothing. Say so; the exit stays 0 because an unreadable diff is not evidence
        # of a blocked path, but the log must not read as a clean run.
        print("DID NOT RUN: no changed paths could be determined (shallow checkout, or no "
              "common history with the base). This check looked at nothing.")
        return 0
    if not paths:
        print(__doc__.split("WHY")[0].strip())
        return 0

    found = lookup(paths, index)
    if not found:
        print(f"nothing planned for {len(paths)} path(s) -- but the index is generated from "
              f"prose, so ABSENCE IS WEAKER EVIDENCE THAN PRESENCE; grep the ledger if the "
              f"change is load-bearing.")
        return 0

    report(found)
    hard = [(p, r) for p, hits in found.items() for r in hits
            if r["status"] in _HARD and r["id"] not in acks and p.startswith(_CODE_ROOTS)]
    print(f"\n{sum(len(v) for v in found.values())} entries over {len(found)} of "
          f"{len(paths)} changed path(s); {len(hard)} need a decision that does not exist yet.")
    if hard and strict:
        print("\nFAIL (--strict): these paths carry a decision that is blocked or forbidden.")
        for p, r in hard:
            print(f"  {p}: {r['status']} by {r['id']} -- {r['where']}")
        print("\nIf you read them and are proceeding anyway, say so in the commit message:")
        print("  ACK " + ", ".join(sorted({r['id'] for _p, r in hard})))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
