## 2026-11-01 — the Run now route answers 409 and logs it when the run's thread cannot start (R393 / R386 / R407; PR #1689)

**What was found.** `POST /api/scheduler/run-now` mapped nothing when `BackgroundScheduler.run_now()` could not make its thread (the process or the machine out of threads): measured status 500 `internal error: can't start new thread`, the only log line the global handler's, no run active afterwards, kill switch cleared. The Start button's route was mapped by #1677; this one is the next route in the same file.

**What changed.** `scheduler_run_now` (`src/api/scheduler.py`) catches `RuntimeError` around `run_now()`, writes a WARNING (`run now refused: the scheduler thread could not start`, with the scrubbed exception) and answers 409 with the exception's words; the Wikipedia lane is not resumed as if a run had begun. An interrupt and any other error are not mapped; a run already in flight is still a 200 with `started: false`. `runner.py` is untouched.

**Pinned by** four new tests, one new entry in the interrupt test and one in the log test, in `tests/test_failed_thread_start_routes_answer_409.py`; 13 mutants of the mapping, all killed; the new 409 test and the log test are red on the unchanged route.

**Stated limits.** R407: what the route did before the start stays done, as after a refused `/start` (kill switch cleared and the crossing online noted, memory-guard and storage-guard latches reset, database-damage pauses released, and the storage-guard supervisor `run_now` may have started keeps running); nothing fetches without a run or a loop, and the next click retries. Not observed in the field: driven by tests that inject the failure.
