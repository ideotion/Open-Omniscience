#!/usr/bin/env python3
"""Pick the checks to run BEFORE the first push of a branch, from what the branch and main changed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

    python scripts/guards_for_diff.py                  # print the plan and the commands
    python scripts/guards_for_diff.py --run            # run it; exit 1 if any step fails
    python scripts/guards_for_diff.py --base origin/main --files   # the test files only, one per line

WHY (2026-10-16, a measured miss). A branch that changes a call site is red in CI for a test it never touched: the test
belongs to somebody else's PR, or walks the whole tree. The branch had run "the tests I changed" and "the tests about my
module", and both were green. CI found, on the first push, ``tests/test_sink_sweep_records.py``, a file ``main`` had
added a day earlier and that the merge had brought in. A CI cycle here is about fifty-five minutes, so one miss is an hour
and one more review round. Three kinds of test fail for a change they never mention, and this picks all three:

1. TESTS MAIN ADDED OR CHANGED SINCE THIS BRANCH LEFT IT. For each merge of another line into this branch, the files under
   ``tests/`` that line changed from the point it left this branch: they are in the working tree only because of the
   merge, and nobody ran them against THIS branch's edits.
2. TESTS THIS BRANCH ADDS OR CHANGES, committed or not (including a new file that is not yet tracked).
3. TREE-WIDE GUARDS: the test files that walk ``src/`` (or the whole tree) and judge every file in it. They fail for a file
   anyone changed and are found by what they do, because no change names them. The pattern is in :data:`TREE_WIDE`.

And the two lint steps CI runs before the tests, so a red there does not cost the same cycle: the blocking ``ruff`` lane
(correctness) and the style ratchet, whose ceiling is READ from ``.github/workflows/ci.yml`` rather than copied here, so
lowering it in one place cannot leave the other behind.

WHAT IT DOES NOT DO. It does not run the whole suite (CI does; that is the point of picking), it does not know a test that
fails for a reason no pattern finds (a test that imports the module under change is one you pick by hand), and an empty
group means "nothing matched the rule", not "nothing is affected". When the base is ahead of the branch it says so: the
tests ``main`` has added since are not in this tree, and a green run here is a run of a tree that is not the one that will merge.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: A test file that judges the tree: it walks the Python files of ``src`` (or everything) and asserts something of each. Found by
#: pattern, so a heuristic: it names a way of walking, not a proof that the walk is a guard.
TREE_WIDE = re.compile(r"""rglob\("\*\.py"\)|os\.walk|glob.*src""")

#: The CI step that carries the style ratchet's ceiling.
_CEILING = re.compile(r"scripts/ruff_ratchet\.py\s+--max\s+(\d+)")

#: The blocking lint lane, exactly as ``ci.yml`` runs it.
_RUFF_BLOCKING = ("--select=F,B", "--extend-ignore=B008", "src/", "tests/")


class PlanError(RuntimeError):
    """The plan cannot be made honestly (no such base, no ceiling in the workflow): a named stop, never a guess."""


@dataclass
class Plan:
    base: str
    ceiling: int
    behind: int
    #: ``test file -> why it was picked``, in the order the groups are listed.
    main_added: list[str] = field(default_factory=list)
    own: list[str] = field(default_factory=list)
    tree_wide: list[str] = field(default_factory=list)
    conftest_changed: bool = False

    def files(self) -> list[str]:
        seen: dict[str, None] = {}
        for group in (self.main_added, self.own, self.tree_wide):
            for path in group:
                seen.setdefault(path, None)
        return list(seen)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if done.returncode != 0:
        raise PlanError(f"git {' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip() or done.returncode}")
    return done.stdout


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _is_test_module(path: str) -> bool:
    """A file pytest collects under ``tests/`` (``python_files`` in ``pyproject.toml``: ``test_*.py`` and ``*_test.py``), at any depth."""
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") and name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def _exist(root: Path, paths: list[str]) -> list[str]:
    return sorted({p for p in paths if _is_test_module(p) and (root / p).is_file()})


def ceiling_from_ci(root: Path) -> int:
    """The style ratchet's ceiling, read from the workflow that enforces it."""
    workflow = root / ".github" / "workflows" / "ci.yml"
    try:
        found = _CEILING.findall(workflow.read_text(encoding="utf-8"))
    except OSError as exc:
        raise PlanError(f"cannot read {workflow}: {exc.__class__.__name__}") from None
    if len(found) != 1:
        raise PlanError(f"expected exactly one `ruff_ratchet.py --max N` step in {workflow}, found {len(found)}")
    return int(found[0])


def tests_main_added(root: Path, base: str) -> list[str]:
    """Test files another line changed, for each merge into this branch since it left ``base``.

    ``base..HEAD`` on the first-parent line lists the merges this branch made; for each extra parent ``P`` of a merge ``M``, the
    changes ``P`` brought are ``merge-base(M^1, P)..P``. A plain fast-forward or a branch that never merged anything yields none."""
    merges = _lines(_git(root, "rev-list", "--first-parent", "--merges", f"{base}..HEAD"))
    picked: list[str] = []
    for merge in merges:
        parents = _git(root, "rev-list", "--parents", "-n", "1", merge).split()[1:]
        if len(parents) < 2:
            continue
        for other in parents[1:]:
            fork = _git(root, "merge-base", parents[0], other).strip()
            picked += _lines(_git(root, "diff", "--name-only", "--diff-filter=ACMR", fork, other, "--", "tests"))
    return _exist(root, picked)


def tests_this_branch_changed(root: Path, base: str) -> list[str]:
    """Test files that differ from the point this branch left ``base`` (the working tree included), plus new untracked ones."""
    fork = _git(root, "merge-base", base, "HEAD").strip()
    changed = _lines(_git(root, "diff", "--name-only", "--diff-filter=ACMR", fork, "--", "tests"))
    changed += _lines(_git(root, "ls-files", "--others", "--exclude-standard", "--", "tests"))
    return _exist(root, changed)


def tree_wide_guards(root: Path) -> list[str]:
    """Every collected test file whose text walks the tree (see :data:`TREE_WIDE`)."""
    found: list[str] = []
    for path in sorted((root / "tests").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if not _is_test_module(rel):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if TREE_WIDE.search(text):
            found.append(rel)
    return found


def build_plan(root: Path = ROOT, base: str = "origin/main") -> Plan:
    try:
        _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    except PlanError:
        raise PlanError(f"no such base `{base}`: fetch it first (git fetch origin main) or name another with --base") from None
    behind = int(_git(root, "rev-list", "--count", f"HEAD..{base}").strip() or 0)
    fork = _git(root, "merge-base", base, "HEAD").strip()
    conftest = bool(_lines(_git(root, "diff", "--name-only", fork, "--", "tests/conftest.py")))
    return Plan(
        base=base,
        ceiling=ceiling_from_ci(root),
        behind=behind,
        main_added=tests_main_added(root, base),
        own=tests_this_branch_changed(root, base),
        tree_wide=tree_wide_guards(root),
        conftest_changed=conftest,
    )


def commands(plan: Plan) -> list[list[str]]:
    """The steps, in the order CI runs them: blocking lint, the style ratchet, then the picked tests."""
    steps = [
        [sys.executable, "-m", "ruff", "check", *_RUFF_BLOCKING],
        [sys.executable, "scripts/ruff_ratchet.py", "--max", str(plan.ceiling)],
    ]
    files = plan.files()
    if files:
        steps.append([sys.executable, "-m", "pytest", "-q", *files])
    return steps


def render(plan: Plan) -> str:
    out: list[str] = []
    if plan.behind:
        out.append(
            f"WARNING: {plan.base} is {plan.behind} commit(s) ahead of this branch. The tests main added since are not in this tree, "
            f"so a green run here is not a run of what will merge: `git merge {plan.base}` first."
        )
    if plan.conftest_changed:
        out.append("NOTE: tests/conftest.py changed on this branch; every test sees it, so run the whole suite (python -m pytest -q).")
    for title, group in (
        ("tests main added or changed since this branch left it", plan.main_added),
        ("tests this branch adds or changes", plan.own),
        ("tree-wide guards (test files that walk the tree)", plan.tree_wide),
    ):
        out.append(f"{title} ({len(group)}):")
        out += [f"  {path}" for path in group] or ["  (none matched)"]
    out.append(f"{len(plan.files())} distinct test file(s); style ceiling {plan.ceiling} (read from .github/workflows/ci.yml).")
    out.append("")
    out += [" ".join(step) for step in commands(plan)]
    return "\n".join(out)


def run(plan: Plan, root: Path = ROOT) -> int:
    """Run every step, in order, even after one fails (so one run names every red), and return 1 if any did."""
    failed: list[str] = []
    for step in commands(plan):
        print(f"\n$ {' '.join(step)}", flush=True)
        if subprocess.run(step, cwd=root).returncode != 0:
            failed.append(step[1] if step[1] != "-m" else step[2])
    if failed:
        print(f"\nFAILED: {', '.join(failed)}", file=sys.stderr)
        return 1
    print("\nall steps passed")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--base", default="origin/main", help="the ref this branch will merge into (default origin/main)")
    parser.add_argument("--run", action="store_true", help="run the steps instead of printing them")
    parser.add_argument("--files", action="store_true", help="print only the picked test files, one per line")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(ROOT, args.base)
    except PlanError as exc:
        print(f"guards_for_diff: {exc}", file=sys.stderr)
        return 2
    if args.files:
        print("\n".join(plan.files()))
        return 0
    print(render(plan))
    return run(plan, ROOT) if args.run else 0


if __name__ == "__main__":
    raise SystemExit(main())
