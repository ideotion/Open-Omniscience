# Release gate — v0.4.0

**Status: OPEN, and not yet ruled.** This is the checkable inventory for closing the `0.4`
cycle. It exists now, before the `0.3` tag, because [`RELEASE_0.3_GATE.md`](RELEASE_0.3_GATE.md)
§5 says in its own words that the `0.4` board *"starts from this list"*, and a postponed
data-safety demonstration nobody writes down becomes one that never happens.

**What is ruled here and what is not.** Rows **A, B and C** were moved off the `0.3` board by
explicit maintainer rulings (2026-08-13 and 2026-08-23) that named them **required in 0.4, not
merely deferred** — those are carried, not proposed. Rows **D, E and F** are this session's
**proposals**, marked as such: they are work `0.3` leaves behind, not decisions anyone has
made. A proposed row is not a bar until the maintainer says it is; declining one is a
legitimate outcome and belongs in §3 with its reason.

**How a row closes** (inherited from the `0.3` gate, unchanged): only when there is a **named
artifact** — a report file, a merged PR, a measured number — that a later reader can re-open
and check. "It was built" is not closure; *merged ≠ green ≠ verified*. A row that cannot be
measured here says so and names the operator step, rather than passing on no evidence.

**The version.** `pyproject.toml` reads `0.3.0` and stays there until `v0.3.0` is tagged; the
flip to `0.4.0` follows the tag, as it did at `0.2`→`0.3` (the 2026-07-18 sequence: P0 pass →
tag → flip). Nothing on this board touches the version.

---

## 1. The board

| # | Row | Owner | Origin | Status |
|---|---|---|---|---|
| A | A committed full import that re-checks **all** sources | operator | ruled 2026-08-13, moved from 0.3 row 4 | **OPEN** |
| B | A multi-day (≥72 h) collector soak | operator | ruled 2026-08-23, moved from 0.3 row 7b | **OPEN** |
| C | Diagnostics on the ~1M-article instance | operator | ruled 2026-08-23, moved from 0.3 row 3's earlier bar | **OPEN** |
| D | Row B's evidence is readable from one artifact | session | *proposed* | **BUILT — awaiting a run to read** |
| E | Row A's demonstration has tooling that can state its own result | session | *proposed* | **OPEN** |
| F | The browser bar reaches a human, a second engine, or is closed as-is | shared | *proposed* | **OPEN** |

Rows A–C are the substance. D and E exist because A and B are both **operator** rows whose
closing clauses ask for a number nobody currently has a single place to read — and a row whose
evidence has to be assembled by hand is a row that closes on somebody's memory.

---

## 2. The rows

### Row A — a committed full import that re-checks all sources

**Carried verbatim in substance from `0.3` §5.** Was row 4 of the `0.3` gate. Moved
2026-08-13: the full source re-check *"will take ages"*.

**What it must demonstrate** — three things, and the ordering matters, because each later one
depends on the earlier one having actually run:

1. **A committed merge at scale.** Every P0 restore so far ran `committed=false` — a
   self-restore in which every row reads as a duplicate. The committed write path at ~1M
   articles has never been exercised in the field.
2. **The qualification admission gate over every source**, the curated catalog included — no
   grandfathering (ruled 2026-07-20). A catalog source that fails is a **catalog-review**
   signal, not a source to exempt.
3. **The qualification stamp surviving a restore.** This is the load-bearing one. On
   2026-07-24 `_merge_sources`' column allowlist dropped the three stamp columns and
   `source_qualification_attempts` had no handler, so a merged-in source arrived
   `unqualified` — a plausible legal value, therefore invisible — and a **disqualified**
   source was laundered back into the trial queue with its backoff ladder reset. It is fixed
   and unit-covered; what is missing is the field proof.

**Closes when:** one committed import at release scale reports the source verdicts it stamped,
**and a spot-check confirms a previously-disqualified source is still disqualified afterwards.**
That last clause is the whole point — a pass that only counts `qualified` rows cannot see the
inversion this row exists to catch.

**The cheaper substitute, still available.** A *small* committed backup demonstrates (1) and
(3) in minutes; only (2) genuinely needs the full corpus. This split was **proposed and
declined for 0.3** (maintainer, 2026-08-13: *"mark it as a necessary step for v0.4, we won't do
it today"*) and the row moved undivided. It is recorded here so the option does not have to be
re-invented, not because it has been re-proposed.

---

### Row B — a multi-day (≥72 h) collector soak

**Carried from `0.3` §5.** Was the second half of row 7. Moved 2026-08-23: *"Postpone the >72h
with the other P0 validation to the v0.4 release."* The cold-boot half (7a) stayed, because it
is five minutes and this is three days.

**What it must demonstrate:** memory flat across ≥72 h of continuous collection at release
scale — P0.3 with samples spanning the window and no climb against the 512 MB floor.

**Read both signals, not just the rate.** `collect_perf.jsonl` is a 5,000-line ring — roughly
two hours — so P0.3 only ever sees the recent window; the durable multi-day evidence is the app
**surviving**: the memory guard not stuck engaged, and the previous session ending cleanly in
session forensics. A pass on the rate alone would be a verdict about two hours wearing a
three-day label.

**Closes when** one report shows P0.3 with samples spanning ≥ 72 h and no climb, **and** the
soak-window artifact (row D) shows the process actually stayed up for the window it reports on.

---

### Row C — diagnostics on the ~1M-article instance

**Carried from `0.3` §5.** Was row 3's bar from 2026-07-30 until 2026-08-23, when the
maintainer ruled that the ~1M instance *"is NOT the v0.3 release-scale one"* and the bar moved
with the instance it describes. Row 3 closed instead against the real release-scale instance
(40,260 articles).

**What `0.3` gave up:** every figure in the 2026-08-23 bundle is evidence **at forty thousand
articles**. Anything that only appears an order of magnitude higher — a member that finishes in
19 minutes here and does not there, a query whose plan flips, a memory profile that only bends
at scale — is **unmeasured** for `0.3`, not measured-and-fine. The two members that died in
that bundle are the reminder that the run is where such things surface.

**Closes when:** one bundle from the ~1M instance whose coverage block reads `complete: true`,
on a build carrying the `statement_deadline` fix, with every member non-zero. The P0
data-safety trio has already been read at that scale (2026-08-12: 1,048,725 articles, 21.0 GB,
backup RSS +1.4 %), so what is owed is the *diagnostics* run, not the safety evidence.

---

### Row D — row B's evidence is readable from one artifact · *proposed* · BUILT

**Why it is a row.** Row B's bar is a property of a three-day window, and until now no single
artifact answered *"did the soak pass"*. The instruments existed — `collect_perf`, the memory
guard, the write gate, the `wal_bytes` hourly series, the latency reservoir, the error log,
session forensics — with **different and mostly undocumented windows**, several of them far
shorter than three days. Assembling the answer by hand is how a two-hour reading acquires a
three-day label.

**Built in this PR:** `GET /api/diagnostics/soak-window`, an all-diagnostics bundle member
(`soak-window.json`). It reports the five signals row B needs, each with **its own window and
denominator**, and refuses to certify the bar when the window does not reach it. It does not
re-derive P0.3's RSS verdict — that stays P0's — and it publishes no composite.

**Closes when:** one soak-window report from a run of ≥ 72 h exists and is read alongside the
P0.3 report. Until a real soak happens, this row is *built, unread* — the honest state, and
not the same as closed.

---

### Row E — row A's demonstration has tooling that can state its own result · *proposed*

**Why it is a row.** Row A's closing clause is a **spot-check that a previously-disqualified
source is still disqualified after the import**, and the reason it is worded that way is that
the 2026-07-24 defect was invisible: the merged-in source carried a plausible legal value, not
a NULL and not an error. A spot-check performed by hand, on an instance with tens of thousands
of sources, is exactly the shape of check that gets reported as done without being done.

**What it wants:** a bounded report that names, for a committed import, the source verdicts it
stamped **and** the before/after status of the sources that were disqualified before it —
enough that the closing clause is a number a reader can re-open, not a memory. The measurement
side already exists in pieces (`source_qualification_attempts` carries an append-only history,
and the qualification export was built 2026-09-04); what does not exist is the before/after
pairing across an import.

**Not built here**, and deliberately: it is tooling for a data-safety demonstration, it wants
its own reviewed slice with the full skeptic matrix, and building it in the same PR as the gate
that asks for it would leave nobody to check it against the ask.

---

### Row F — the browser bar reaches a human, a second engine, or is closed as-is · *proposed*

**Where it stands.** `0.3`'s row 8 closed against its literal bar, and the stretch matrix was
executed on 2026-08-20 (`docs/audit/UI_CLICKTHROUGH_2026-08-20.md`): all 17 themes, the Reader
surface, a real import fixture, the a11y axis with vendored axe-core, five lens drills. Every
stamp from it reads **"Chromium-verified (remote sandbox) · awaiting human UX pass"**, which is
the honest wording and also an open loop.

**What that report itself left open:** the 12-locale sweep (4 covered), honesty rule 9
(adversarial screenshot reading), and the Gecko/AppVM bar.

**Three ways this closes, and they are not equivalent:** a human click-through (what the stamp
is waiting for); a second-engine run under the AppVM recursive environment (which would let the
stamps read *"Gecko-verified (VM)"*); or a deliberate ruling that Chromium-in-sandbox plus the
audit is the bar `0.4` ships against, recorded in §3. The third is a legitimate outcome. What
is not legitimate is carrying "awaiting human UX pass" into a second release without saying
which of the three happened.

---

## 3. Amendment log

Every change to a row's status or bar lands here with its date, its source, and what it costs.
The `0.3` gate's own log is the format.

| Date | Change | Source |
|---|---|---|
| 2026-09-07 | Board created from `RELEASE_0.3_GATE.md` §5. Rows A/B/C carried under their existing rulings; D/E/F proposed | session |

---

## 4. Not in this gate

Kept explicit so nothing drifts in by assumption:

- **The `v0.3.0` tag.** It is the `0.3` gate's §7.3, and this board does not gate it.
- **The version flip to `0.4.0`.** It follows the `v0.3.0` tag, mechanically.
- **The 5M-article framing.** Withdrawn 2026-07-30 and not reinstated here; it returns as a
  later-cycle target once the throughput work makes it reachable.
- **Row 5's Tier B** (the 451 index pages above the word guard). Not proposed for `0.3` and not
  proposed here: their prose is unmeasured. The `0.3` PR made that measurable
  (`criteria-calibration.json`'s prose arm now advances and can be pointed at that population),
  so a `0.4` decision on Tier B would at least have evidence — but it is a decision, and nobody
  has made it.
