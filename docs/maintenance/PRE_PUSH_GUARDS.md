# Before the first push of a branch: `scripts/guards_for_diff.py`

A branch that changes a call site can be red in CI for a test it never touched. A CI cycle here is about fifty-five minutes, so
a miss costs an hour and a review round. The measured case (2026-10-16): a branch ran the tests it had changed and the tests
about its module, both green, and CI failed on `tests/test_sink_sweep_records.py`, a file `main` had added a day earlier that the
merge had brought in.

```
python scripts/guards_for_diff.py            # print the plan and the commands
python scripts/guards_for_diff.py --run      # run them; exit 1 if any step failed (every step still runs)
python scripts/guards_for_diff.py --files    # only the picked test files, one per line
python scripts/guards_for_diff.py --base origin/main
python scripts/guards_for_diff.py --since ORIG_HEAD   # after a rebase (see group 1)
python scripts/guards_for_diff.py --onto origin/main --run   # the same picks, run on this branch MERGED onto main (see below)
```

It picks four groups of test files and prints, in the order CI runs them, the blocking `ruff` lane, the style ratchet and one
`pytest` command over the picked files (the command is shell-quoted, so a file name with a space pastes back as one argument):

1. **Tests `main` added or changed since this branch left it.** For each merge into the branch, the `tests/` files the merged
   line changed from the point it left the branch; the line brought is the parent already inside the base, which is the first
   parent when the merge was made the other way round (`git checkout main && git merge feature`), and every merge since the
   base counts, not only the last. They are in your tree only
   because of the merge, and nobody ran them against your edits. **A rebase leaves no merge to find them by:** after one, name
   the state you last tested with `--since REF` (`ORIG_HEAD`, or the old remote branch) and it adds what the base changed from there.
2. **Tests this branch adds or changes**, committed or not, including a new untracked file.
3. **Tests that use a changed support file.** A helper module, a `*_node_test.js` or a data file under `tests/` is not a test, so a
   change to one picks nothing by itself: the tests whose text names it (the module name, or the whole file name) are picked, and
   a deleted helper counts, because its importers fail on import. A changed `conftest.py` or `__init__.py` picks every test below
   its directory; one at `tests/` or at the repository root makes the pick the whole suite (`tests`), in the printed plan, in
   `--files` and in `--run`. A rename is read as a delete and an add (whatever `diff.renames` says), so the tests that still import
   the old name are picked. A support file no test names is printed with that fact, so an empty pick is never silent.
4. **Tree-wide guards**: the test files that walk `src/` or the whole tree and judge every file in it (`rglob("*.py")`,
   `os.walk`, `glob` over `src`, a star-led `rglob` on a repository-rooted receiver such as `(_ROOT / "src").rglob("*")`, and a
   one-directory `glob("*.py")` or `glob("*/data")` on any receiver, which also picks a scratch `tmp_path.glob("*.py")` at the
   cost of one cheap file; a scratch directory's `tmp_path.rglob("*")` is not one). They fail for a file anyone changed and no
   change names them.

The style ratchet's ceiling is read from `.github/workflows/ci.yml`, never copied, so lowering it in one place cannot leave the
other behind. Paths come from git with `-z`, so a name with a space or a non-ASCII letter is picked like any other.

**What it does not do.** It does not run the whole suite (CI does), and it does not find a test that fails for a reason no
pattern names (a test that imports the module you changed, without naming a changed file, is one you pick by hand). An empty
group means "nothing matched the rule", not "nothing is affected". When the base is ahead of the branch it says so, because the
tests `main` has added since are not in your tree: merge first, then run it, or a green run is a run of a tree that is not the
one that will merge.

## At merge time: `--onto REF`, the merged tree

Everything above judges *this branch's* tree. When a PR is about to be merged the question is the other one: does the tree that
will exist after the merge pass what guards the tree? `main` moves every ten minutes or so, and merging it into the branch while CI runs
costs the cycle again, so the head CI green-lit is not the tree that merges. `--onto REF` answers it without touching the branch:

```
python scripts/guards_for_diff.py --onto origin/main            # print the plan of the merged tree
python scripts/guards_for_diff.py --onto origin/main --run      # run it there; exit 1 if any step fails
python scripts/guards_for_diff.py --onto origin/main --files    # the picked files, one per line (paths in the merged tree)
python scripts/guards_for_diff.py --onto origin/main --run --keep   # leave the worktree in place, to look at a red
```

It makes a scratch `git worktree` of REF in the temporary directory, merges this branch's **committed HEAD** into it (the merge is a
commit of the worktree alone, on a detached HEAD, with a scratch identity and no hook, signing, signature check or rerere of yours; no branch or ref
of the repository moves), builds the plan there (so "tests main added" are the files REF changed since the branch left it, and "tests this branch adds" the
files the merge result differs from REF in), runs it there, and removes the worktree. `--onto` replaces `--base` and `--since`. A branch that
does not merge is a named stop that lists the conflicting files (merge REF into the branch and resolve it first). The rest of your git
configuration (rename detection, merge drivers) still applies, and a file that both sides changed and that `.gitattributes` marks `merge=union`
(`docs/ledger/shipped.csv`) is merged with that rule here but not by GitHub, which reports a conflict: a NOTE names such a file.

**The steps run with the tree they run in first on `PYTHONPATH`** (in the plain mode too). A test that starts a child process (a restore, a
boot, a helper) imports `src` in the child from wherever the editable install points, which on a machine whose install was made in another
checkout is another tree. Measured on 2026-10-28, on ONE tree: four `tests/test_restore_collector_exit.py` tests were red in a scratch
worktree and red in the checkout itself, and the eight restore and WAL files that start children were 115 of 115 green with the tree on
`PYTHONPATH`. CI gets that for free, because there the install points at the checkout.

**What the merged-tree run proves:** the guards this script picks (the four groups above, with the guards that walk the *test files*
(`glob("test_*.py")`) among the tree-wide ones) pass on the committed HEAD merged onto REF as REF was when you fetched it, with the tree's own `src`
imported by the children the tests start *that inherit the environment* (a child started with `-I`, or with `PYTHONPATH` removed, still imports the
installed package). **What it does not:**
it is not the whole suite (CI is); uncommitted changes are named in a NOTE and are not in the merged tree; it is a scratch-worktree run, which
the project accepts as the merged-tree check **only for a branch that touches no `src/`** (a worktree is not the checkout the app runs from;
for a branch that does, merge REF into the branch and run the plain `--run` in the checkout, and the NOTE says so); and a green run is not CI
(the runner, the Python patch level and the installed versions are the machine's own). The worktree is a full checkout of the tracked tree,
so it needs that much disk while it exists; a SIGTERM or SIGHUP during a step removes it too, a SIGKILL cannot (then `git worktree list` shows the
leftover, and `git worktree remove --force <path>` removes it).

## After the PR is opened: `scripts/sweep_pr_number.py`

A PR's number exists only once the PR does, and a number read off GitHub's counter before that is a guess. So the ledger fragments
(`lessons.d`, `shipped_log.d`, `shipped.d`) carry the template placeholder (`PR pending`, `#NNNN`) on the first push, and the number goes in
straight after: open the PR, run `python scripts/sweep_pr_number.py <number>` (`--dry-run` prints the changes and writes nothing), then
`python scripts/ledger_fold.py check`, `python scripts/ledger_shipped.py check` and `python -m pytest -q tests/test_ledger_shipped_fragments.py`
(the last is the only guard that looks at a csv row's `refs` for a leftover `pending`), commit and push. A branch pushed without a PR starts no CI, and the push to the PR cancels the run that
opening it started, so the sweep costs one effective CI run.

**What it rewrites:** `PR pending` becomes `PR #<number>` and `#NNNN` becomes `#<number>`, in the fragments this branch **added**
(`git merge-base BASE HEAD`, renames off; BASE is `origin/main` unless `--base REF`, which is what a branch stacked on another unmerged branch
passes). In the two markdown directories only prose is touched, where "prose" is `ledger_fold._prose`'s rule and no better: a line that starts
with three backticks or three tildes opens or closes a fence (any character, any length, so a backtick fence quoted inside a `~~~` block is
read as prose), and `inline code` is one pair of single backticks (a double-backtick span is read as prose too). A lesson may quote a
placeholder inside what that rule keeps; anywhere else it is rewritten.
In a `shipped.d` csv only the `refs` cell is touched, and every other byte of the file stays as it was whatever quoting it was written with.
**What it refuses** (exit 2, nothing written): a number that is not a positive integer (`1636`, not `#1636`), a base that does not resolve or
shares no history with `HEAD` (a shallow clone: `git fetch --unshallow`), a branch that added no fragment, a symlink or a path that runs
through one, a file name or text that is not UTF-8, a markdown fence that is never closed, a csv that is not the ledger's header plus one row
or that the `csv` module cannot read, a rewrite that would change any cell but `refs`, and **any placeholder still there after the rewrite**,
judged the way the ledger judges it (`ledger_fold._PLACEHOLDER` over the whole prose, so `PR` at the end of a line and `pending` at the start of
the next counts; in a csv also any `pending` left in `refs`, which is what `test_ledger_shipped_fragments.py` refuses). That covers a token the
script has no rule for (`_RULES` is the list, so a token added to `ledger_fold._PLACEHOLDER` needs its line in both), one split by a line
break, a code span or a quote (edit those by hand), and `#NNNN` run on into more letters, which is a typo and is never turned into `#1636N`. A second run says there is nothing to sweep and exits 0. **What it does not do:** it reads what the
branch has *committed* as added (commit the fragments, then sweep), it does not fetch (`git fetch origin main` first), and CI never runs it on a real PR (`tests/test_sweep_pr_number.py` runs it against throwaway repositories).

## When CI is red or the environment moved: compare, do not eyeball

A check that went red on a tree that was green, with no source change in between, is an environment change until a diff says otherwise, and
the first thing to look at is the package versions. Two scripts take the by-eye work out of it; neither touches the network.

* `python scripts/diff_installed_versions.py OLD NEW` compares the `### Installed versions` blocks that the `test` and Core-only jobs print
  at the end of their logs (`ci.yml`, step "Installed versions (kept on red as well as green)"). Each argument is a log file, the JSON that
  the log API returns, or `-` for standard input. It prints the packages changed, added and removed under pip's own name rule, and which of
  Python, the runner image and the kernel moved. **Exit 0: identical. Exit 1: different. Exit 2: not comparable** (no block, a block that
  was cut off, an unreadable file), with the reason, and never a comparison against an empty list. Read the environment line as well as the
  package list: two Core-only runs on 2026-10-28 had the same 87 pins and three different environment fields.
* `python scripts/check_wheel_layout.py dist/<wheel>.whl` is the other triage step of that kind, for a built wheel: exit 0 clean, 1 with one
  sentence per missing file, 2 on a usage error. CI runs it in the lock-file job on the wheel built from the sdist.

Also run before a push, as CI does and this script does not: `python -m mypy src/` for the modules you changed, and
`python scripts/planned.py --diff`. The selection is tested in `tests/test_guards_for_diff.py` against a throwaway git repository.
