## 2026-10-13 — vitals-history: a leaked liveness thread is stopped between tests, and a refused boot-time pair keeps the last good one (PR #1380)

- **2026-10-13 · vitals-history (the export thread; the CI flake seen on #1375's `test` job and the coordinator's three lows on #1379; one independent read, folded).** Two things in one PR because the three lows
and the fix touch the same tests.

  **The flake.** `session_history.record_boot` starts the `oo-session-liveness` daemon thread (unless `OO_SESSION_LIVENESS=0`), stopped only by `record_end`. A test that boots a session and does not end it leaves the
thread ticking the NEXT test's vitals recorder on the real clock: the first `fine` row was the real-time sample and an injected 2023 tick read as a multi-year step back (`test_one_wrong_typed_field...[minutes-None]`, once,
on #1375). Reproduced with a scratch test. `tests/conftest.py` gains `_stop_leaked_liveness_thread()` (sets the stop event, joins with a timeout, drops the handle only when the thread is gone; no `stop_liveness()`
because that flushes), called FIRST in the `_vitals_history_isolated` teardown. Pinned by a behavioural test (a running thread is stopped, a stopped one left alone, a thread that outlives the wait keeps its handle) and a
source test that the fixture calls it before `reset_for_tests`.

  **The lows.** (1) A tick with no usable boot-time pair (no boot-time clock, a failed read, two readings more than 0.1 s apart) used to clear the forward-step baseline; it now neither compares nor replaces
`_BOOT_BASE`, the last usable `(wall, boot)` pair, so the next tick compares across both and a step of 600 s or more in between is not lost. Pairs read but refused for skew count in `clock_boot_pairs_refused`
(persisted, clamped at 0 on read, reset with a damaged file); a missing reading is not a refusal. (2) The held-step test passed without its guard; it is laid out so a wall-bucket-flagging held tick
(offset 299.9, step 595.5) fails when the guard goes, and the gap-opening case is credited to a step only when the baseline is the PREVIOUS tick's own pair (`base_wall == _LAST_WALL`), which a read of the delta found
missing (a step across ticks without a pair can sit inside a gap the absence opened). (3) The `_gaps` docstring names `FORWARD_STEP_FLOOR_S`. The member's `method` names the new counter, the step that is not lost and
the one gap case that stays unmarked.

  **Evidence.** One independent read (0 block, 1 should-fix, 3 low), folded; 30 mutants killed (the equivalent `_BOOT_BASE = None` in `start()` removed as unreachable); ruff advisory ratchet 417 of 417 (a Yoda
comparison in a new assert would have made it 418); 693 tests in the affected files on the restarted branch.
