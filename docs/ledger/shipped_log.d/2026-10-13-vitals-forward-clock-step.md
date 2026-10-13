## 2026-10-13 — vitals-history: a forward step of the wall clock is recorded against the boot-time clock (PR #1379)

- **2026-10-13 · vitals-history (the export thread; finding 6 of the vitals read; the coordinator's go on Design A, one independent read and one delta read).** A wall clock moved forward (a time
correction, a virtual machine brought up to date after a pause) left a gap in the five-minute rows that read as down time, and nothing in the member told the two apart. `tick()` now takes the wall clock's advance
beyond the boot-time clock's between consecutive ticks (`CLOCK_BOOTTIME` through `session_history.boottime()`, no second reader): 0 for a stalled thread, a frozen process and a suspend the kernel measured, a number only
where the wall clock itself was moved. The step joins the `clock_steps` list the steps back already use (`forward_s`, newest 20 of both kept) and counts in `clock_stepped_forward`, which is never capped;
a gap next to a step still in the list is marked `clock_step`. No cause is claimed (a clock that was set, a time correction and a virtual machine caught up after a pause read the same).

  **The threshold.** The first design recorded steps from 600 s, derived as "605 s of wall advance opens a gap on the worst alignment, minus the tick's 5 s". The independent read showed that holds only for ticks on a 5 s
grid that lines up with the buckets: a tick can be the last of its bucket at any phase and can come late, and probes with the clocks injected as the tests inject them left a 600 s unmarked gap with nothing recorded at
offset 299.9 / step 595.5, offset 299.5 / step 596, offset 297 / step 599, and a tick 20 s late / step 585. The sweep and the parametrisation had used only multiples of 5. The rule is now decided per tick: a step is
recorded from 600 s (the span `_gaps` lists a gap from, whatever the phase) or, below that, from 1 s where it is what opened a listed gap, tested as "the gap would not exist with the step taken out", and ONE helper
(`_opens_gap`) feeds both `_gaps` and `tick` so the two cannot disagree. A step inside a gap the process's absence opened anyway is deliberately not recorded under 600 s (the gap is down time first, and recording every
step inside a stall's gap would mark a suspend's gap for a 2 s time-sync correction); the member's `method` lists it among the reasons a gap can be unmarked, with a step the list no longer holds, no boot-time clock, and a restart.

  **Not measured is not zero.** `clock_stepped_forward` is `null` until a tick has had a boot-time clock to compare with (a platform without one, a file of a build that did not measure it), then 0; both counters clamp at 0 on
restore. `tick(now=, mono=)` without `boot=` means no boot-time clock (a real reading beside an injected wall clock would invent steps in every existing test); only a bare `tick()` reads it, on both sides of the wall
read, and uses the midpoint only when the two readings are within 0.1 s (a tenth of the 1 s floor, so the midpoint's error cannot make a floor-sized step; a pause between the reads, by the interpreter lock, a frozen
process or a suspend, would otherwise be a step of its own length). Linux only; not measured across a restart or on a session's first tick.

  **Size.** A forward record is 78 bytes; the method text is 3.7 KB; the member keeps about 13 KB under its 260,000-byte budget and `_fit` never drops `clock_steps` or the counters.

  **Checks.** 36 mutants of the rule, the null counter, the two-sided read, the floor, the skew bound, the text clauses and the restore all fail the tests (one first reported as surviving only because the runner's filter did
not select its test). 768 tests in the ten files that touch the module. Lesson in `docs/ledger/lessons.d/2026-10-13-forward-step-threshold-per-event.md`.
