# CI shards: how the `test` and `core-only` jobs are split, and how to keep them honest

Written 2026-11-05 with C10 (decision 27, R412). The two full-suite CI jobs each ran the whole suite in one process, 70 to 80 minutes, and a PR waited for the
slower of the two. Each is now **three jobs** that each run a third of the test files.

## What runs where

| check (as branch protection names it) | job id | what it is |
|---|---|---|
| `test` | `test-all` | an aggregator: green only if all three `Test (shard N of 3)` legs are |
| `Core-only install (no [analysis] extra)` | `core-only-all` | an aggregator: green only if all three `Core-only install, shard N of 3 (no [analysis] extra)` legs are |
| `Test (shard N of 3)` | `test` (matrix) | install, plan, pytest on a third of the files; leg 1 also runs the static steps (ruff, style ratchet, planned-work index, i18n gates, migration drift, mypy, bandit, pip-audit) |
| `Core-only install, shard N of 3 (no [analysis] extra)` | `core-only` (matrix) | the same thirds without the `[analysis]` extra, no static steps |

The required checks keep the names they had before the split, so nothing in branch protection changed. **Never name a matrix leg `test` or the Core-only
name**, and never make an aggregator skippable: a job whose `needs` failed is skipped unless it says `if: always()`, and a skipped required check counts as passing.
`tests/test_ci_shards.py` pins all of this, with a mutant for each property.

## How a test file gets its shard

`scripts/ci_shard.py`, from the cost table `configs/ci_shard_costs.json` (`path -> seconds`):

* files the table names are dealt out longest first, each to the shard with the least work so far (shard 1 starts with `overhead_seconds`, the static steps);
  the result depends on the table alone, so adding or deleting a test file moves none of the files the table names;
* a file the table does not name (a new test file) goes to `crc32(path) % N + 1`: the same in every process, no edit needed in the PR that adds it, spread
  evenly in the long run. The plan step prints how many files the table does not name.

Each leg's plan step writes `--ignore=<file>` for every test file that belongs to another shard, and `pytest ... @"$RUNNER_TEMP/shard.args"` reads it (an
argument file, pytest 8.2 and later); pytest still collects `tests` itself. **Why it ignores the others instead of naming its own files:** a path named on the
command line is not subject to `collect_ignore` in `tests/conftest.py`, which is how a core-only install keeps the analysis tests out. The first sharded Core-only
leg named its files, collected `test_confidence_intervals.py` and `test_statistical_tests.py` and died at import. Ignoring the others leaves every rule of the
one-process run (`collect_ignore`, `norecursedirs`, `python_files`) in force. A plan that runs nothing, or ignores nothing while N > 1, is refused; a shard that
ignores everything ends in "no tests ran" (exit 5, red), where an empty list of files would have run the whole suite.

Run one shard by hand: `python scripts/ci_shard.py plan --shard 2/3 --out /tmp/shard.args && python -m pytest -q @/tmp/shard.args`.
`python scripts/ci_shard.py check` says whether the files of the tree are a partition.

## Refreshing the cost table

The table is a measurement of one tree and it ages: the plan step's "N not in the table" and each leg's real time (the step summary) say how far. To refresh it,
run the suite once in the `test` environment with `--junitxml=junit.xml` and

    python scripts/ci_shard.py costs --min-seconds 0.5 junit.xml

which rewrites the table (modules under half a second fall to the hash, which spreads the many small ones evenly; `--table OTHER.json` rewrites OTHER.json, the
table it read, and `--stdout` prints instead of writing). The table was last measured on run 41995058978 of PR #1726 (head 07ec3eaf8; 794 modules of half a second or more, 4960 s), the run that is also named in its `source` field.
Look at the legs' times on the next run; the tests pin that the table deals the shards to within 3 % of each other, not that the legs take equal time.

**A new dealing is a new set of neighbours.** Which tests share a process changes with the table, so the check that no test leans on a neighbour was made for the
table that ships. After a refresh that moves many files, or a change of shard count, run it again: put the three `PARITY` jobs back (their text is
`git show 0d8047c91:.github/workflows/ci.yml`, the head of PR #1726 that carried them), read the legs, and remove them again.

## Changing the number of shards

`shards` in the table, `shard: [1, 2, 3]` in both matrices, `/3` in both plan steps and in the leg names must all change together; `tests/test_ci_shards.py`
names whichever you forgot.

## What the split does not prove, and how it was checked once

The old single process ran every file in one order, and nothing proved that no test leaned on a neighbour. Sharding is not an isolation model. On the head that
introduced the split, temporary jobs ran the whole suite in one process and compared each shard with it, module by module and outcome by outcome
(`python scripts/ci_shard.py parity`; it refuses a comparison in which neither side holds a named module, which is what a conftest import error looks like).
Result of the run on the shipped table (run 42014873848, head 0d8047c91, the PR merged onto main `c0c66ffd8`):

| | modules compared | passed | skipped | xfailed | failed | differences |
|---|---|---|---|---|---|---|
| unsharded, one process | 1580 | 29315 | 353 | 1 | 0 | |
| shard 1 | 533 | 11142 | 151 | 0 | 0 | 0 |
| shard 2 | 523 | 8545 | 157 | 0 | 0 | 0 |
| shard 3 | 524 | 9628 | 45 | 1 | 0 | 0 |
| the three together | 1580 | 29315 | 353 | 1 | 0 | 0 |

The first parity run (the previous table) found exactly one order dependence: `test_scheduler_runs.py` failed right after `test_scheduler_pause_resume.py`, whose two
tests ended on `run_now() is True` and joined nothing, so the `oo-scrape-now` thread wrote its report into the next test's data directory. Unsharded the neighbour
was another file and never noticed. It was fixed at the leaker (the teardown of `test_scheduler_pause_resume.py` now joins the thread and fails a test that leaves one).

Core-only was not compared with an unsharded Core-only run: its legs use the same planner and table and must be green, and the real core install collects the
whole suite once and each shard's plan (`python scripts/ci_shard.py collected`): 29440 tests in 1555 modules, the shards 528 + 514 + 513 modules, 0 differences.
A test that is order-dependent shows up as a red leg that is green alone; the fix is in the test.

`release.yml` still runs the suite in one process at a tag, and the macOS/Windows `portability` observation lane is unchanged.

## How long it takes, and what limits it

Measured on the same run (job time from start to end, which includes the install, about two minutes, and for leg 1 of `test` the static steps):

| | shard 1 | shard 2 | shard 3 |
|---|---|---|---|
| `Test (shard N of 3)` | 28:12 | 25:34 | 26:59 |
| `Core-only install, shard N of 3` | 17:46 | 28:22 | 25:54 |

The required `test` check was green 29:51 after the run was created (before: the one-process job, 70 to 80 minutes; the same job here took 79:36 as the unsharded
oracle). The goal was about 25 minutes and the slowest leg took 28:22. Even perfectly balanced, `test`'s three legs (80:45 together) would take 26:55 each, so three
shards do not reach 25 for `test`. Two known imbalances, both left alone because moving the dealing means proving the new neighbours again:

* `test` leg 1 is the slowest, about two minutes over the mean of the other two; its static steps, which the table models as 80 s (`overhead_seconds`), are the
  likely reason (the per-step times were not read);
* Core-only deals from a table measured in the `test` environment, where the analysis tests run; in a core-only install they are skipped or ignored, so its shard 1 is
  light (17:46) and shard 2 heavy (28:22). Balanced, the three legs' 72 minutes would be 24 each (arithmetic on the times above, not a measurement), which a Core-only
  table of its own, measured the same way, would aim at.

Four shards is the next step if the wall time matters more than the number of runners; it has not been measured.
