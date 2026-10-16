#!/usr/bin/env python3
"""Pick the checks to run BEFORE the first push of a branch, from what the branch and main changed.

Open Omniscience - Global Intelligence Platform for Investigative Journalism
Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

    python scripts/guards_for_diff.py                  # print the plan and the commands
    python scripts/guards_for_diff.py --run            # run it; exit 1 if any step fails
    python scripts/guards_for_diff.py --base origin/main --files   # the test files only, one per line
    python scripts/guards_for_diff.py --since ORIG_HEAD            # a rebased branch: also main's tests since that state

WHY (2026-10-16, a measured miss). A branch that changes a call site is red in CI for a test it never touched: the test
belongs to somebody else's PR, or walks the whole tree. The branch had run "the tests I changed" and "the tests about my
module", and both were green. CI found, on the first push, ``tests/test_sink_sweep_records.py``, a file ``main`` had
added a day earlier and that the merge had brought in. A CI cycle here is about fifty-five minutes, so one miss is an hour
and one more review round. Four kinds of test fail for a change they never mention, and this picks all four:

1. TESTS MAIN ADDED OR CHANGED SINCE THIS BRANCH LEFT IT. For each merge of another line into this branch (whichever parent
   is the line already in the base), the files under ``tests/`` that line changed from the point it left this branch: they
   are in the working tree only because of the merge, and nobody ran them against THIS branch's edits. A rebased branch has
   no merge to find them by: ``--since REF`` names the state you last tested and adds what the base changed from there.
2. TESTS THIS BRANCH ADDS OR CHANGES, committed or not (including a new file that is not yet tracked).
3. THE TESTS THAT USE A CHANGED SUPPORT FILE. A helper module, a ``*_node_test.js`` or a data file under ``tests/`` is not a
   test, so a change to one picks nothing by itself: the tests whose text names the file are picked, and a changed
   ``conftest.py`` or ``__init__.py`` picks every test below its directory (the whole suite when it sits at ``tests/`` or the root).
4. TREE-WIDE GUARDS: the test files that walk ``src/`` (or the whole tree) and judge every file in it. They fail for a file
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
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: A test file that judges the tree: it walks the files of ``src`` (or everything) and asserts something of each. Found by
#: pattern, so a heuristic: it names a way of walking, not a proof that the walk is a guard. The third alternative is a
#: star-led ``rglob`` on a repository-rooted receiver (``(_ROOT / "src").rglob("*")``, which a suffix filter follows): the
#: receiver is part of the pattern because ``tmp_path.rglob("*")`` walks a scratch directory, not the tree.
TREE_WIDE = re.compile(
    r"""rglob\("\*\.py"\)|os\.walk|glob.*src|(?:ROOT|REPO|_SRC|SRC_|_STATIC|\bSRC\b)[^\n]*\.rglob\(\s*["']\*"""
)

#: Files that scope a whole directory: a change reaches every test below it, whatever the test says.
_DIRECTORY_SCOPED = ("conftest.py", "__init__.py")

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
    #: changed support file under ``tests/`` (a helper, a ``*_node_test.js``, a data file) -> the tests whose text names it.
    support: dict[str, list[str]] = field(default_factory=dict)
    #: changed ``conftest.py`` / ``__init__.py`` below ``tests/`` -> every test below its directory.
    scoped: dict[str, list[str]] = field(default_factory=dict)
    tree_wide: list[str] = field(default_factory=list)
    #: a ``conftest.py`` / ``__init__.py`` at ``tests/`` or the repository root changed, on the branch or in a merge.
    conftest_changed: bool = False
    since: str | None = None

    def uses_changed_support(self) -> list[str]:
        seen: dict[str, None] = {}
        for group in (*self.support.values(), *self.scoped.values()):
            for path in group:
                seen.setdefault(path, None)
        return list(seen)

    def files(self) -> list[str]:
        seen: dict[str, None] = {}
        for group in (self.main_added, self.own, self.uses_changed_support(), self.tree_wide):
            for path in group:
                seen.setdefault(path, None)
        return list(seen)


def _git(root: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, encoding="utf-8", errors="surrogateescape")
    if done.returncode != 0:
        raise PlanError(f"git {' '.join(args)} failed: {done.stderr.strip() or done.stdout.strip() or done.returncode}")
    return done.stdout


def _succeeds(root: Path, *args: str) -> bool:
    return subprocess.run(["git", *args], cwd=root, capture_output=True).returncode == 0


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _paths(root: Path, *args: str) -> list[str]:
    """A path list from git, NUL-separated: without ``-z`` git quotes a name with a non-ASCII byte (``"tests/test_caf\\303\\251.py"``)
    and the quoted text matches no file, so the test was dropped without a word."""
    return [path for path in _git(root, *args).split("\0") if path]


def _is_test_module(path: str) -> bool:
    """A file pytest collects under ``tests/`` (``python_files`` in ``pyproject.toml``: ``test_*.py`` and ``*_test.py``), at any depth."""
    name = path.rsplit("/", 1)[-1]
    return path.startswith("tests/") and name.endswith(".py") and (name.startswith("test_") or name.endswith("_test.py"))


def _exist(root: Path, paths: list[str]) -> list[str]:
    return sorted({p for p in paths if _is_test_module(p) and (root / p).is_file()})


def _is_support(path: str) -> bool:
    """Something under ``tests/`` that is not a test module, or a ``conftest.py`` at the repository root."""
    return (path.startswith("tests/") and not _is_test_module(path)) or path == "conftest.py"


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


#: What a diff is asked about: the tests and everything that can change how they run (a root ``conftest.py``).
_WATCHED = ("tests", "conftest.py")
#: Every status but a delete for test modules (a deleted test has nothing to run); support files keep deletes, because a test
#: that imports a deleted helper fails on import.
_NOT_DELETED = "--diff-filter=ACMR"
_ANY_STATUS = "--diff-filter=ACMRD"


def changed_by_merges(root: Path, base: str) -> list[str]:
    """Paths the line merged into this branch changed, for each merge since the branch left ``base``.

    ``base..HEAD`` on the first-parent line lists the merges this branch made. The line a merge BROUGHT is the parent already
    contained in ``base`` (``git merge-base --is-ancestor``): usually the second, but a branch merged the other way round
    (``git checkout main && git merge feature``, then the branch moved to the result) has main's tip as the FIRST parent, and
    reading the second parent as main's line picks the branch's own tests as main's and nothing of main's. A merge whose parents
    are ALL inside ``base`` (a branch with no commit of its own that merged a newer main) or ALL outside it (another feature line)
    keeps the plain reading: the first parent is the branch, the others were brought.
    For a brought parent ``P`` and the branch's parent ``B`` the changes are ``merge-base(B, P)..P``."""
    merges = _lines(_git(root, "rev-list", "--first-parent", "--merges", f"{base}..HEAD"))
    picked: list[str] = []
    for merge in merges:
        parents = _git(root, "rev-list", "--parents", "-n", "1", merge).split()[1:]
        if len(parents) < 2:
            continue
        inside = [p for p in parents if _succeeds(root, "merge-base", "--is-ancestor", p, base)]
        outside = [p for p in parents if p not in inside]
        if inside and outside:
            brought, branch = inside, outside[0]
        else:  # every parent in the base (a branch with no commits of its own) or none (another feature line): first parent is the branch
            brought, branch = parents[1:], parents[0]
        for other in brought:
            fork = _git(root, "merge-base", branch, other).strip()
            picked += _paths(root, "diff", "--name-only", "-z", _ANY_STATUS, fork, other, "--", *_WATCHED)
    return picked


def changed_since(root: Path, base: str, since: str) -> list[str]:
    """Paths ``base`` changed from the point ``since`` (the state last tested, for a rebased branch: ``ORIG_HEAD`` or the old
    remote branch) left it. A rebase leaves no merge to find main's changes by."""
    try:
        _git(root, "rev-parse", "--verify", "--quiet", f"{since}^{{commit}}")
    except PlanError:
        raise PlanError(f"no such ref `{since}` for --since: name the state you last tested") from None
    fork = _git(root, "merge-base", since, base).strip()
    return _paths(root, "diff", "--name-only", "-z", _ANY_STATUS, fork, base, "--", *_WATCHED)


def changed_on_branch(root: Path, base: str) -> list[str]:
    """Paths that differ from the point this branch left ``base`` (the working tree included), plus new untracked ones."""
    fork = _git(root, "merge-base", base, "HEAD").strip()
    changed = _paths(root, "diff", "--name-only", "-z", _ANY_STATUS, fork, "--", *_WATCHED)
    changed += _paths(root, "ls-files", "-z", "--others", "--exclude-standard", "--", *_WATCHED)
    return changed


def tests_main_added(root: Path, base: str) -> list[str]:
    """Test files another line changed, for each merge into this branch since it left ``base`` (see :func:`changed_by_merges`)."""
    return _exist(root, changed_by_merges(root, base))


def tests_this_branch_changed(root: Path, base: str) -> list[str]:
    """Test files that differ from the point this branch left ``base`` (the working tree included), plus new untracked ones."""
    return _exist(root, changed_on_branch(root, base))


def _collected(root: Path) -> dict[str, str]:
    """Every test module pytest collects under ``tests/``, with its text."""
    texts: dict[str, str] = {}
    for path in sorted((root / "tests").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        if not _is_test_module(rel):
            continue
        try:
            texts[rel] = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
    return texts


def tree_wide_guards(root: Path) -> list[str]:
    """Every collected test file whose text walks the tree (see :data:`TREE_WIDE`)."""
    return [rel for rel, text in _collected(root).items() if TREE_WIDE.search(text)]


def _names(name: str) -> re.Pattern[str]:
    """A file name as a whole word in a test's text (a stem such as ``_util`` must not match ``_utility``)."""
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])")


def tests_using(root: Path, support: list[str]) -> tuple[dict[str, list[str]], dict[str, list[str]], bool]:
    """For each changed support file: ``(support -> tests naming it, directory-scoped -> tests below, whole-suite flag)``.

    A helper module is named by its module name (``tests/_util.py`` -> ``_util``), any other file by its whole name
    (``x_node_test.js``, ``data.json``). A ``conftest.py`` or ``__init__.py`` scopes its directory: the tests below it, or the
    whole suite (the flag) when it sits at ``tests/`` or the repository root."""
    named: dict[str, list[str]] = {}
    scoped: dict[str, list[str]] = {}
    whole = False
    texts: dict[str, str] | None = None
    for path in sorted(set(support)):
        directory, _, name = path.rpartition("/")
        if name in _DIRECTORY_SCOPED:
            if directory in ("", "tests"):
                whole = True
            else:
                scoped[path] = sorted(rel for rel in _collected(root) if rel.startswith(directory + "/"))
            continue
        if texts is None:
            texts = _collected(root)
        needle = _names(name[:-3] if name.endswith(".py") else name)
        named[path] = sorted(rel for rel, text in texts.items() if needle.search(text))
    return named, scoped, whole


def build_plan(root: Path = ROOT, base: str = "origin/main", since: str | None = None) -> Plan:
    try:
        _git(root, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    except PlanError:
        raise PlanError(f"no such base `{base}`: fetch it first (git fetch origin main) or name another with --base") from None
    behind = int(_git(root, "rev-list", "--count", f"HEAD..{base}").strip() or 0)
    brought = changed_by_merges(root, base)
    if since:
        brought += changed_since(root, base, since)
    mine = changed_on_branch(root, base)
    named, scoped, whole = tests_using(root, [p for p in (*brought, *mine) if _is_support(p)])
    return Plan(
        base=base,
        ceiling=ceiling_from_ci(root),
        behind=behind,
        main_added=_exist(root, brought),
        own=_exist(root, mine),
        support=named,
        scoped=scoped,
        tree_wide=tree_wide_guards(root),
        conftest_changed=whole,
        since=since,
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
        out.append(
            "NOTE: a conftest.py or __init__.py at tests/ or the repository root changed (on this branch or in a merge); every test sees it, "
            "so run the whole suite (python -m pytest -q)."
        )
    for title, group in (
        ("tests main added or changed since this branch left it" + (f" (and since {plan.since})" if plan.since else ""), plan.main_added),
        ("tests this branch adds or changes", plan.own),
    ):
        out.append(f"{title} ({len(group)}):")
        out += [f"  {path}" for path in group] or ["  (none matched)"]
    out.append(f"changed support files under tests/ and the tests that use them ({len(plan.support) + len(plan.scoped)}):")
    for path, users in {**plan.support, **plan.scoped}.items():
        kind = "everything below it" if path in plan.scoped else "tests naming it"
        out.append(f"  {path}: {len(users)} {kind}" + ("" if users else " -> NONE named it; pick the tests that import it by hand"))
    if not plan.support and not plan.scoped:
        out.append("  (none changed)")
    out.append(f"tree-wide guards (test files that walk the tree) ({len(plan.tree_wide)}):")
    out += [f"  {path}" for path in plan.tree_wide] or ["  (none matched)"]
    out.append(f"{len(plan.files())} distinct test file(s); style ceiling {plan.ceiling} (read from .github/workflows/ci.yml).")
    out.append("")
    out += [shlex.join(step) for step in commands(plan)]
    return "\n".join(out)


def run(plan: Plan, root: Path = ROOT) -> int:
    """Run every step, in order, even after one fails (so one run names every red), and return 1 if any did."""
    failed: list[str] = []
    for step in commands(plan):
        print(f"\n$ {shlex.join(step)}", flush=True)
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
    parser.add_argument(
        "--since",
        metavar="REF",
        help="the state you last tested (after a rebase: ORIG_HEAD or the old remote branch); also pick what the base changed from there",
    )
    parser.add_argument("--run", action="store_true", help="run the steps instead of printing them")
    parser.add_argument("--files", action="store_true", help="print only the picked test files, one per line")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(ROOT, args.base, args.since)
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
