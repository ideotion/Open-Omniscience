## 2026-10-15 — two writers to one fixed temp name tear the file: serialize the flush, and read DURING the overlap to test it (PR #1388)

**What was found.** The budget test of the heaviest vitals member failed once on #1381, in a job that crossed midnight UTC: it read 15 fine rows where it had written 577. Midnight was the obvious suspect and was wrong. With `time.time`
frozen a second either side of midnight, of new year, of a leap day and with a clock running 600 times fast across midnight, the member was the same 577 fine, 337 coarse and 3 tails every time. The failure's own fingerprint named the
cause: 15 rows from the base of the third session, `clock_stepped_back` 0 — a history that STARTED FRESH because `start()` read a damaged file as none. `flush()` wrote `vitals_history.json.tmp` and renamed it, always under the
same temporary name, so two flushes that overlapped (a leaked liveness thread's first-tick flush and the test's own) opened it with truncation under each other and renamed it away from under each other. A scratch test with a
thread ticking the real clock reproduced it in 28 of 150 builds; with the lock, 0 of 150. In production the same overlap is the liveness thread's periodic flush against the flush at a clean stop (whose join gives up at 2 s) and
the exit flush.

**The rules.**
1. **Write-temp-then-rename is atomic for ONE writer.** With a fixed temporary name, two overlapping writers can tear the file and the loser of the rename fails. Serialize the writer (a lock held across the snapshot, the write, the
   rename and the bookkeeping) or give each writer its own temporary name. A lock was right here because the snapshot and the retry bookkeeping belong with the write, and the `_STARTED` re-check must sit in the SAME hold as the
   snapshot: a flush that waited for the lock across a reset must write nothing. Re-entrant only so a flush on the same thread does not wait for itself; say in the comment what that does not cover (a nested flush can still
   tear; two processes on one directory are not serialized) rather than imply more.
2. **A test of a race must read DURING the overlap.** After both flushes finish the file is intact, so "run both, join, check" can never fail. Two flushing threads plus hundreds of reads of the file the way production reads it
   (without the lock 5 to 21 of 300 loads were torn, 8 of 8 runs), seeded with a complete file first or the first read is the empty one. A rename over a file another thread has open fails on Windows whatever the lock does, so
   that test skips there instead of claiming a guarantee it cannot test.
3. **A timestamp hypothesis is tested by freezing the clock on both sides, and a cause is named only after the exact fingerprint is reproduced.** "It crossed midnight" was a coincidence of the CI timestamp until a frozen
   clock failed to reproduce it; the 15 rows and the base were the evidence that did. Keep the cheap pin anyway (the member built a second either side of midnight gives the same tables) so the question is closed in the tests.
4. **An extra row at the real clock's five-minute floor, in a test that injects its clock, is a stray real-clock writer, not a clock crossing a bucket.** #1387's Core-only run showed bucket 1791968700 (09:05:00Z) in a restart
   test that only ever calls `tick(now=…)`; the only real-clock caller is the liveness thread a test left running, the class #1380 stops. Name the actor that could write into the test before pinning a clock the test already fakes.
