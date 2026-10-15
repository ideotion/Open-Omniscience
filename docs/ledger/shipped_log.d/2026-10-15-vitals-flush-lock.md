## 2026-10-15 — vitals-history: overlapping flushes of the history file can no longer tear it (PR #1388)

- **2026-10-15 · vitals-history (the export thread; the budget-test failure seen on #1381 in a job that crossed midnight UTC; one independent read, folded; the coordinator's check OK).** The failure read 15 fine rows where
the test had written 577. It was NOT the date: frozen-clock runs around midnight, new year and a leap day give the same member. `flush()` wrote and renamed `vitals_history.json.tmp` under ONE fixed name, so two flushes that
overlapped (the liveness thread's, the clean stop's after a join that gives up at 2 s, the exit flush, a thread a test left running) truncated and renamed it under each other; `start()` read the torn file as none and began an
empty history, losing the 48 hours and the tails of the last sessions. Reproduced in 28 of 150 builds; with the lock 0 of 150.

  **The change.** `_FLUSH_LOCK` (an `RLock`) is held for the whole flush: the `_STARTED` re-check under `_LOCK` in the same hold as the snapshot (a flush that waited across a reset writes nothing), the write, `os.replace`,
the retry bookkeeping. Order `_FLUSH_LOCK`, `_LOCK`, `_LOG_LOCK`; nothing holding `_LOCK` calls `flush`. Not covered, and said in the comment: a nested flush on the same thread, two processes on one data directory. The
member's `method` text and the `_gaps` docstring now say, as three cases, that a recorded clock step can leave its gap unmarked. Tests: two flushing threads against 300 reads of the file the way `start` reads it (skipped on
Windows); a flush that waited across a reset writes nothing; the heaviest member built a second either side of midnight UTC gives the same tables; the isolation-fixture guard reads the fixture from the syntax tree.

  **Evidence.** One independent read (0 block, 0 should-fix, 9 low), folded; the coordinator's check of the folds OK; ruff advisory ratchet 417 of 417; 744 tests in the vitals, wiring, slicing-discipline, repo-invariant,
network-consent, ledger-fragment, slot, package-split, runs-log-sink and secret-filter files on the restarted branch. #1387's Core-only flake (an extra real-clock row in a restart test) was the leaked-thread class of #1380 and
needed nothing here.
