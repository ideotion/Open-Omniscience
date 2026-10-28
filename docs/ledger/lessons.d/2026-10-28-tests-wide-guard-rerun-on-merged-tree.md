## 2026-10-28 — a guard that scans all of `tests/` is re-run on the MERGED tree when main gained test files after the head's CI

**What was found (#1610, R372).** Q's widened os-patch guard reads every `.py` under `tests/`, so its verdict depends on the files that exist, not only on the PR's own diff. The head's CI ran before #1605 landed `tests/test_job_writer_flags.py` on main, so a green on the head said nothing about that new file: a whole-tree scanner is green on a tree that no longer exists once main moves.

**The rule.** When a PR adds or widens a check that scans a whole directory, and main gained files in that directory after the head's CI, re-run the check on the merged tree (`git merge-tree --write-tree`, then the guard on the result) before the go. It is a different question from «do the two file lists overlap» (R357): there is no shared file, and the interaction is still real.

**How it was settled.** The coordinator re-ran the guard on the merged tree before merging #1610 (`681746c16`); `tests/test_job_writer_flags.py` was not flagged. Measured, not assumed: the guard found 2 places in 1,535 files before the change, one fixed and one allowlisted with its reason.
