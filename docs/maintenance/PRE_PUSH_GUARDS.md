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
```

It picks four groups of test files and prints, in the order CI runs them, the blocking `ruff` lane, the style ratchet and one
`pytest` command over the picked files (the command is shell-quoted, so a file name with a space pastes back as one argument):

1. **Tests `main` added or changed since this branch left it.** For each merge into the branch, the `tests/` files the merged
   line changed from the point it left the branch; the line brought is the parent already inside the base, which is the first
   parent when the merge was made the other way round (`git checkout main && git merge feature`). They are in your tree only
   because of the merge, and nobody ran them against your edits. **A rebase leaves no merge to find them by:** after one, name
   the state you last tested with `--since REF` (`ORIG_HEAD`, or the old remote branch) and it adds what the base changed from there.
2. **Tests this branch adds or changes**, committed or not, including a new untracked file.
3. **Tests that use a changed support file.** A helper module, a `*_node_test.js` or a data file under `tests/` is not a test, so a
   change to one picks nothing by itself: the tests whose text names it (the module name, or the whole file name) are picked, and
   a deleted helper counts, because its importers fail on import. A changed `conftest.py` or `__init__.py` picks every test below
   its directory; one at `tests/` or at the repository root says to run the whole suite. A support file no test names is printed
   with that fact, so an empty pick is never silent.
4. **Tree-wide guards**: the test files that walk `src/` or the whole tree and judge every file in it (`rglob("*.py")`,
   `os.walk`, `glob` over `src`, a star-led `rglob` on a repository-rooted receiver such as `(_ROOT / "src").rglob("*")`; a
   scratch directory's `tmp_path.rglob("*")` is not one). They fail for a file anyone changed and no change names them.

The style ratchet's ceiling is read from `.github/workflows/ci.yml`, never copied, so lowering it in one place cannot leave the
other behind. Paths come from git with `-z`, so a name with a space or a non-ASCII letter is picked like any other.

**What it does not do.** It does not run the whole suite (CI does), and it does not find a test that fails for a reason no
pattern names (a test that imports the module you changed, without naming a changed file, is one you pick by hand). An empty
group means "nothing matched the rule", not "nothing is affected". When the base is ahead of the branch it says so, because the
tests `main` has added since are not in your tree: merge first, then run it, or a green run is a run of a tree that is not the
one that will merge.

Also run before a push, as CI does and this script does not: `python -m mypy src/` for the modules you changed, and
`python scripts/planned.py --diff`. The selection is tested in `tests/test_guards_for_diff.py` against a throwaway git repository.
