## 2026-10-13 — a thread a test leaves running ticks the next test on the real clock: stop it in the autouse fixture, and keep the last good reading across a refusal (PR #1380)

**What was found.** Once, on #1375's `test` job, `test_one_wrong_typed_field...[minutes-None]` failed with a vitals history whose first `fine` row was the real-time sample and whose injected 2023 ticks read as a
multi-year step back. Nothing in the test or the module was wrong. `session_history.record_boot` starts a daemon thread (`oo-session-liveness`, `start_liveness`, unless `OO_SESSION_LIVENESS=0`) that is stopped only by
`record_end`; any test that boots a session and does not end it leaves the thread running, and that thread calls `vitals_history.tick()` every 5 s with the real clock into whatever recorder the NEXT test has just started.
The autouse fixture reset the recorder between tests but never the thread, so the failure needed a particular order, a 5 s boundary and a test that injects an old date: it showed once in many runs and not on a laptop.
It reproduced on demand with a scratch test that starts the recorder, leaves the thread and lets a second test inject a 2023 tick.

**The rules.**
1. **A background thread started as a side effect of an import-time or boot-time call is global state a fixture has to reset, like a module-level list.** The fixture that isolates a recorder isolates its writers too. Stop the
   thread first (set its stop event, join with a timeout, drop the handle only when it is gone), BEFORE the recorder reset; use the bare stop event and not the public `stop_liveness()`, which flushes the recorder the
   fixture is about to discard. A source-level test pins that the fixture calls the helper and that the helper runs first, and a behavioural test pins that a left-running thread is stopped and an already-stopped one is
   left alone, so the guard cannot go unnoticed.
2. **A flake that shows once is a question about shared state, not about timing.** Reproduce it by naming the actor that could write into the test (here a thread with the real clock), not by raising the repeat count.
3. **A refusal should not erase what was good.** The forward clock-step baseline was cleared when one tick's boot-time readings were unusable, so a step that happened across that tick was not measured by the next one. The last
   usable `(wall, boot)` pair is kept instead: the difference of the two clocks' advances does not depend on how long ago the pair was taken, so a step in between is not lost. Count the refusal (`clock_boot_pairs_refused`;
   a MISSING reading is not a refusal, it is absence) so the operator can see how often a measurement was lost, and persist the counter like the others.
4. **Guard the baseline with the previous tick's own pair when the answer depends on the previous tick.** Crediting a step with having made a gap is only sound when the baseline is the immediately preceding tick: across ticks
   without a usable pair that tick's bucket may already hold the step and the gap behind it is the absence's. The condition is `base_wall == _LAST_WALL`, and the held-step test is laid out so that it fails when the
   condition goes (a layout that passes without the guard is not a test of it).
5. **Run the repo-wide ratchets, not only the files that touch the module.** The first push of this PR failed `test_source_slicing_discipline` on CI: the fixture guard sliced the conftest source with a literal anchor
   (`text.split("def _vitals_history_isolated", 1)`), which is one more hand-rolled site against a budget of 230, and the ten test files run locally did not include the file that counts them. Read a fixture or a
   module through the syntax tree (`ast.parse`, find the `FunctionDef`, compare the line numbers of its calls) and not by slicing text; and before a push run every test that counts a pattern across the tree
   (`test_source_slicing_discipline`, the repo invariants, the socket-importer ratchet), because they fail on a file nobody opened.
