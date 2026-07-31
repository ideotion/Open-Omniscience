# The import/export run journal

*What it records, where it lives, and how to send it back.*

## Why

Field night 2026-07-31. A 686,896-article import sat on `15/19 ·
3000/686896` for seven hours. Answering *"is it stuck or is it slow?"* took
manual `ps` sampling by hand, over several rounds — and the first verdict was
wrong. When the run was finally killed it left **no report at all**: import #14
does not exist.

Not because the import path is uninstrumented. It is well instrumented, and
every number it produces is correct. They are all held **in memory** and written
**once, at the end, on the success path** — so a run that never reaches its end
leaves nothing behind.

The journal is the missing sink. It writes while the run is in flight.

## It is on by default

Nothing to enable, no button. Every volume import and every volume export opens
a journal for itself; the import **queue** drives the same code path, so each
queued item gets its **own** run (eight ten-hour imports under one id would wrap
the heartbeat ring and lose the early hours of all but the last).

`OO_RUN_JOURNAL=0` turns it off. The escape hatch is the thing you have to ask
for, not the recording — a flight recorder you must remember to arm is off
precisely on the flight worth recording.

## Where it lives

```
<data_dir>/run_logs/
  imp-20260731T041200Z-a1b2c3.jsonl        milestones — append-only, fsync'd, never trimmed
  imp-20260731T041200Z-a1b2c3.beat.jsonl   heartbeat  — newest-wins ring (~24 h at 15 s)
```

Two files rather than one, for one reason: milestones must never be trimmed
away, heartbeats must be. One file means either an unbounded log or a ring that
eventually eats the `run_begin` line.

## How to send it

It rides the existing one-button download: **Settings → Diagnostics → all
diagnostics**, as two members —

- `run-journal.json` — the summary for each run: stages and their seconds,
  outcome, the knobs it resolved, errors, the last heartbeat.
- `run-journal-raw.json` — the raw lines behind that, bounded to the newest few
  runs. The summary is the answer; this is the evidence, and a stall is a
  *shape* across hundreds of beats (swap climbing while CPU flatlines, the write
  gate held with waiters piling up) that no summary substitutes for.

## What a heartbeat carries

Every 15 s, and none of it touches the database:

| field | what it answers |
|---|---|
| `cpu_s`, `d_cpu_s` | cumulative process CPU, and the delta since the last beat |
| `kids`, `kids_cpu_s`, `d_kids_cpu_s` | the same for the pool's worker processes — **the field that actually settles "stuck or slow?" during the re-index**, because a healthy parent is idle there too |
| `rss_mb`, `kids_rss_mb_upper` | parent RSS, and the children's sum (an upper bound — forked workers share pages) |
| `mem_avail_mb`, `swap_used_mb`, `disk_free_mb` | the system-level readings that needed a `/proc/meminfo` paste before |
| `wal_mb` | WAL growth during the merge |
| `gate` | write gate: held, waiters, max wait |
| `phase`, `counter`, `done`, `total`, `d_done`, `moving` | progress — see below |
| `d_prog_seq` | how many times progress was published since the last beat (a liveness signal that exists in *every* phase) |
| `bc_ms` | what the beat itself cost. Measured, not assumed — and above a threshold the child walk turns itself off and says so |

## What it refuses to say

**`moving` is emitted only when the active phase owns a real progress counter
and two consecutive beats both read it.** `prepare_staged` is 54 % of a large
import and publishes a phase and nothing else; a rule of "no movement in the
counter means stuck" would print `moving: false` for ninety minutes of perfectly
healthy work — a fabricated stall verdict in the exact field built to answer
"stuck?". When there is no counter the beat says `counter:
"none-in-this-phase"` and stays quiet about movement.

**An unmeasurable field is omitted, with its reason in `unmeasured`.** Never
zeroed. `kids_n: 0` reads as *"no worker processes"* — the exact inverse of what
an `AccessDenied` on a hardened kernel means.

**A run with no `run_end` line is reported as `incomplete`, not as a crash.** A
journal muted mid-run by a full disk leaves the identical signature, and the two
are not distinguishable from the file. At the next boot such a run is marked
with a `promoted` event — deliberately *not* a synthesised `run_end`, because
overloading the token whose absence is the evidence would spend that evidence on
the first restart.

**A rate needs two samples and a non-zero window**, or it is absent with the
reason — never `0.0`. Spans anchor on the **last observed beat**, so a
forty-minute stall on a machine that was then switched off does not read as
three days.

**An interrupted run's report never headlines a success.** The plan is computed
before the commit point, so an aborted run carries one; printing it unconditionally
put *"**686,896 new articles**"* at the top of a run that committed nothing. The
outcome now comes first, and the plan appears under a heading that says it is
what the run *would* have merged.

## Safety

The journal must never break, block, or deadlock the run it observes.

- Every write is wrapped; the first failure disables that stream for the rest of
  the run. A resilience sidecar that can abort a hard-won ten-hour import is
  worse than no sidecar. If that happens, the closing line says
  `journal_truncated: true`, so a run that *did* finish is not later mistaken
  for a killed one.
- Milestones and heartbeats have separate handles and separate locks: a blocked
  write on one cannot stall the other.
- `os.register_at_fork` quiesces both locks across a fork and disables the
  journal in the child, and the PID guard is checked **before** the lock. The
  re-index forks a process pool; a child blocking on an inherited lock with no
  owner alive to release it is precisely the deadlock of 2026-07-31, and it
  would be a poor joke to reintroduce it via the journal built to diagnose it.
- The heartbeat never opens a database connection.
- `progress()` sits on a ~700,000-call path and is two attribute stores: no
  lock, no clock read, no allocation, no I/O.
- Milestones fired while the write gate is held (the fourteen merge steps, the
  export's freeze window) flush without `fsync`. On the failing disk this system
  exists to diagnose, an `fsync` can block for seconds — and every other writer
  would feel it.

## What it still cannot tell you

- Whether a run with no `run_end` was killed or merely muted. Stated, not guessed.
- Anything about the *contents* of a killed import: no plan counts, no corpus
  delta, no re-index rates. Those are computed at the end, and that end never
  came. What a killed run leaves is which stage it died in, and the trajectory
  that led there.
- Per-child CPU on a machine that denies `/proc` access. The field is omitted
  with the reason rather than filled in.
