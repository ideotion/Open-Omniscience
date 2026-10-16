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
```

It picks three groups of test files and prints, in the order CI runs them, the blocking `ruff` lane, the style ratchet and one
`pytest` command over the picked files:

1. **Tests `main` added or changed since this branch left it** (for each merge into the branch, the `tests/` files that line
   changed from the point it left the branch). They are in your tree only because of the merge, and nobody ran them against your edits.
2. **Tests this branch adds or changes**, committed or not, including a new untracked file.
3. **Tree-wide guards**: the test files that walk `src/` or the whole tree and judge every file in it (`rglob("*.py")`,
   `os.walk`, `glob` over `src`). They fail for a file anyone changed and no change names them.

The style ratchet's ceiling is read from `.github/workflows/ci.yml`, never copied, so lowering it in one place cannot leave the
other behind.

**What it does not do.** It does not run the whole suite (CI does), and it does not find a test that fails for a reason no
pattern names (a test that imports the module you changed is one you pick by hand). An empty group means "nothing matched the
rule", not "nothing is affected". When `tests/conftest.py` changed it says to run the whole suite. When the base is ahead of the
branch it says so, because the tests `main` has added since are not in your tree: merge first, then run it, or a green run is a
run of a tree that is not the one that will merge.

Also run before a push, as CI does and this script does not: `python -m mypy src/` for the modules you changed, and
`python scripts/planned.py --diff`. The selection is tested in `tests/test_guards_for_diff.py` against a throwaway git repository.
