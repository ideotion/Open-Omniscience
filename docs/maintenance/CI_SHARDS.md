# CI shards: how the `test` and `core-only` jobs are split, and how to keep them honest

Written 2026-11-05 with C10 (decision 27, R412); the artifacts and the measured legs below are the follow-up of the same day (R433). The two full-suite CI jobs each ran the whole suite in one process, 70 to 80 minutes, and a PR waited for the
slower of the two. Each is now **three jobs** that each run a third of the test files.

## What runs where

| check (as branch protection names it) | job id | what it is |
|---|---|---|
| `test` | `test-all` | an aggregator: green only if all three `Test (shard N of 3)` legs and the `static` job are |
| `Core-only install (no [analysis] extra)` | `core-only-all` | an aggregator: green only if all three `Core-only install, shard N of 3 (no [analysis] extra)` legs are |
| `Test (shard N of 3)` | `test` (matrix) | install, plan, pytest on a third of the files, nothing else |
| `Static checks (...)` | `static` | since R668 (2026-11-13), the static steps that leg 1 used to run (ruff, style ratchet, planned-work index, i18n gates, migration drift, mypy, bandit, pip-audit), beside the legs on a runner of its own; required through `test` |
| `Core-only install, shard N of 3 (no [analysis] extra)` | `core-only` (matrix) | the same thirds without the `[analysis]` extra, no static steps |

The required checks keep the names they had before the split, so nothing in branch protection changed. **Never name a matrix leg `test` or the Core-only
name**, and never make an aggregator skippable: a job whose `needs` failed is skipped unless it says `if: always()`, and a skipped required check counts as passing.
`tests/test_ci_shards.py` pins all of this, with a mutant for each property.

## How a test file gets its shard

`scripts/ci_shard.py`, from the cost table `configs/ci_shard_costs.json` (`path -> seconds`):

* files the table names are dealt out longest first, each to the shard with the least work so far (a shard starts with its `overhead_seconds`, empty since the static steps left leg 1 for the `static` job in R668; the 80 leg 1 carried until then stayed while a re-deal to 0 exposed two order-dependent tests on its first run, `test_launcher_signals.py` and `test_windowed_group_counts.py`, and went once R674 (PR #1943) had made both independent of their neighbours);
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

The table is a measurement of one tree and it ages: the plan step's "N not in the table" and each leg's real time (the step summary) say how far. **Every leg of
the `test` job (and of the Core-only job) uploads its `junit.xml` as an artifact** (`junit-test-shard-N`, `junit-core-only-shard-N`, kept 14 days, on red runs
too), so any green run of the `test` job refreshes the table without running the suite in one process:

1. open the run's page, download `junit-test-shard-1`, `-2` and `-3`, unzip each into its own folder (each holds a `junit.xml`);
2. `python scripts/ci_shard.py costs --min-seconds 0.5 junit-test-shard-*/junit.xml`

which rewrites the table (modules under half a second fall to the hash, which spreads the many small ones evenly; `--table OTHER.json` rewrites OTHER.json, the
table it read, and `--stdout` prints instead of writing). **Use the three reports of ONE run:** `costs` SUMS the seconds of every report it is given, and the
three legs hold disjoint files, so one run's three reports are the suite once; two runs' reports would double every figure against `overhead_seconds`. The
seconds are the speed of the runners that run's legs happened to get (the same suite took 72 to 90 minutes of `test` job time over three runs, below), so prefer
a run whose three pytest steps ended within a few percent of each other. The report holds test ids, outcomes and seconds, a traceback for a failure and a skip's
reason, which is what the job log already prints. The table was last measured on run 41995058978 of PR #1726 (head 07ec3eaf8; 794 modules of half a second or
more, 4960 s), the run that is also named in its `source` field. The tests pin that the table deals the shards to within 3 % of each other, not that the legs take
equal time (below: they came within 3 % of the table on the last run).

The Core-only legs' reports are kept for a table of their own, which does not exist yet (below).

**A new dealing is a new set of neighbours.** Which tests share a process changes with the table, so the check that no test leans on a neighbour was made for the
table that ships. After a refresh that moves many files, or a change of shard count, run it again: put the three `PARITY` jobs back (their text is
`git show 0d8047c91:.github/workflows/ci.yml`, the head of PR #1726 that carried them), read the legs, and remove them again. The parity jobs are needed for that,
no longer for a plain refresh.

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

Measured on three runs of the PR (job time from start to end, which includes the install and, for leg 1 of `test`, the static steps). Run A is the parity run
(head 0d8047c91 merged onto main `c0c66ffd8`); run B is the next one (head 225975f90 merged onto `7066c4401`, whose new test files are dealt by the hash); run C is the
last one before the merge (head 65e477d35 merged onto `6945d1f3e`, run 42043201924), whose step times were read.

| | run | shard 1 | shard 2 | shard 3 |
|---|---|---|---|---|
| `Test (shard N of 3)` | A | 28:12 | 25:34 | 26:59 |
| `Test (shard N of 3)` | B | 21:21 | 22:33 | 28:23 |
| `Test (shard N of 3)` | C | 29:58 | 29:34 | 30:37 |
| `Core-only install, shard N of 3` | A | 17:46 | 28:22 | 25:54 |
| `Core-only install, shard N of 3` | B | 24:30 | 29:32 | 25:44 (red: the clock race of the lesson `a-tick-list-clock-is-read-by-every-thread-of-the-process`, since fixed) |
| `Core-only install, shard N of 3` | C | 26:46 | 19:19 | 25:31 |

The required `test` check was green 29:51 (A), 28:31 (B) and 40:04 (C) after the run was created; before, the one-process job took 70 to 80 minutes (79:36 as the
unsharded oracle of run A). The goal was about 25 minutes and the slowest leg took 28:22 (A), 29:32 (B) and 30:37 (C): **not reached.**

**A leg's time is not the run's time.** In run C `Test (shard 1)` waited 10:00 between its creation and its start and shard 2 waited 6:38, which is the difference
between 30 and 40 minutes. Both starts came 2 to 3 seconds after a sibling job of the same run ended, while two other PR runs were running: that points to a cap on the
number of concurrent jobs. This is an INFERENCE; the limit of the plan is not visible from the repository. Every PR run now asks for four more jobs than before the split.

**Where a leg's time goes (run C, step times).** The table's prediction is the tests alone; the fixed part is the install and, in leg 1, the static steps.

| leg | before pytest | pytest step | the table predicts | after pytest |
|---|---|---|---|---|
| Test 1 | 132 s (91 install, 41 static) | 1604 s | 1600 s | 62 s (static) |
| Test 2 | 105 s | 1666 s | 1680 s | 3 s |
| Test 3 | 104 s | 1730 s | 1680 s | 3 s |
| Core-only 1 | 46 s | 1556 s | | 4 s |
| Core-only 2 | 33 s | 1122 s | | 4 s |
| Core-only 3 | 35 s | 1492 s | | 1 s |

* **The dealing of `test` is good.** The three pytest steps came within 3 % of what the table predicted (the three add to 5000 s against the table's 4960 s). The
  goal was out of reach for three shards, not for lack of balance: 4960 s over three shards is 27:33 of tests before any install. Four shards would be about
  22 to 23 minutes per leg on the same arithmetic.
* **The runner moves more than the dealing.** The same suite took 80:45 (A), 72:17 (B) and 90:09 (C) of `test` job time, a spread of 25 % between runs, against 3 %
  between the legs of one run; the same leg varied by up to 8:37 (`test` shard 1: 21:21 in B, 29:58 in C).
* **The static steps of leg 1** (until R668 moved them to the `static` job) took about 100 s (41 s before pytest, about 59 s after: mypy 30, bandit 25, pip-audit 4); `overhead_seconds` then modelled 80. The 20 s
  difference moves the dealing by under 7 s per leg, so the number stayed (R433 dropped a measured overhead); it went to none in #1988, once the steps had left leg 1.
* **Core-only is the one imbalance measured:** the pytest steps took 1556, 1122 and 1492 s, a spread of 434 s. The light leg was leg 1 in A and B and leg 2 in C,
  so three runs do not say how much of it is the table (measured where the analysis tests run, which a core-only install skips) and how much is the runner. Dealing
  the 4170 s evenly would give 23:10 against 25:56 for the slowest leg, and only matters in a run where Core-only is the slowest job (B yes, A a tie, C no).

**Held (R433), not done.** A Core-only table of its own (the planner takes `--table`) waits until a Core-only table has been measured from the artifacts above. Four
shards wait until created-to-started times of every leg have been recorded on the next five runs: with a cap on concurrent jobs, two more legs per run may cost more
queue than they save. The macOS portability observation lane holds a runner for about 50 minutes on every PR push and gates nothing; whether it should run on a
schedule only is a question for that lane, flagged here and not changed.
