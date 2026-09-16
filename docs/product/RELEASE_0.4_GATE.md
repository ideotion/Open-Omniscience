# Release gate — v0.4.0

**Status: OPEN — RULED 2026-09-15 (rows A–F), and grown to rows G–V by the answered roadmap sheet.**
This is the checkable inventory for closing the `0.4`
cycle. It exists now, before the `0.3` tag, because [`RELEASE_0.3_GATE.md`](RELEASE_0.3_GATE.md)
§5 says in its own words that the `0.4` board *"starts from this list"*, and a postponed
data-safety demonstration nobody writes down becomes one that never happens.

**What is ruled here and what is not.** Rows **A, B and C** were moved off the `0.3` board by
explicit maintainer rulings (2026-08-13 and 2026-08-23) that named them **required in 0.4, not
merely deferred** — those are carried, not proposed. Rows **D, E and F** are this session's
**proposals**, marked as such: they are work `0.3` leaves behind, not decisions anyone has
made. A proposed row is not a bar until the maintainer says it is; declining one is a
legitimate outcome and belongs in §3 with its reason.

**AMENDED 2026-09-15 — the board is now RULED, and it grew.** The maintainer's answered roadmap sheet
([`docs/design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md`](../design/ROADMAP_ANSWER_SHEET_2026-09-12_BETA_PATHWAY.md),
indexed line by line in [`docs/ledger/RULINGS_INDEX.md`](../ledger/RULINGS_INDEX.md)) settled this board:
**Q117 = a** makes rows **D and E bars** (no longer proposals) and **closes row F as-is** on **Q1128 = a**
(Chromium in the sandbox + the maintainer's click-through = verified; Gecko stays best-effort). **Q105 = a**
amends the release's CONTENTS while keeping its theme — rows **G–V** below are the sixteen slices the answers
put in 0.4 (the 0.3 close first), each row citing the question IDs it implements (Q112), each with a session
brief under [`docs/plans/2026-09-12-beta-pathway/`](../plans/2026-09-12-beta-pathway/00_INDEX.md) (Q113).
**Q110 = c: no target dates**, on this board or any later one. **Q115 = c:** the operator-time budget per
release is unbounded — the V1 train's "a few hours" assumption is retired, and operator rows are listed
without apology. **Q116 = a:** three lanes as today (planning, build, verification). A row is *ruled* when its
origin is a question ID; anything marked *proposed placement* is the planning session's sequencing, not a
ruling; the ⛔ questions left blank (Q823, Q925, Q1009, Q1113) are named on the rows they touch and are never
assumed. Row order is dependency order, not priority: K (the format bump) precedes the 0.5 storage half by
ruling (Q301 = c), O (the substrate) precedes P and Q by construction.

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
| D | Row B's evidence is readable from one artifact | session | *proposed* → **BAR, ruled 2026-09-15 (Q117 = a)** | **BUILT, and DRIVEN end to end at fixture scale 2026-09-15** — four of six blocks measured, the other two `measured: false` with a reason; still awaiting a ≥ 72 h run to read |
| E | Row A's demonstration has tooling that can state its own result | session | *proposed* → **BAR, ruled 2026-09-15 (Q117 = a)** | **PARTIAL** — built, riding the bundle, and driven end to end 2026-09-15 in BOTH directions (clean → `consistent`; seeded laundering → `inversions-found`, named); the RUN is Row A's |
| F | The browser bar reaches a human, a second engine, or is closed as-is | shared | *proposed* → **closed as-is, ruled 2026-09-15 (Q117 = a on Q1128 = a)** | **CLOSED 2026-09-15** — the bar is Chromium-in-sandbox + the maintainer's click-through; Gecko best-effort. The citable sentence lives in §2 row F behind `<!-- release-notes: verification-bar -->`, and the release notes quote it from there |
| G | `0.3` closed and the version flipped | operator | ruled 2026-09-15 (Q109 = a) · brief `S03-01` | **OPEN — waiting on the operator**; `RC01` blank ⇒ ASSUMPTION (b), so the version stays `0.3.0` until 0.3 row 5 is run (re-checked 2026-09-15, not flipped) |
| H | `docs/SECURITY.md` enumerates every host; the consent hover lists them per lane | session | ruled (Q1001, Q1002) · `S04-01` | **BUILT 2026-09-16, awaiting the maintainer's own click-through** — the enumeration (14 lanes, PR #1135), the hover, and `tests/test_security_endpoint_enumeration.py`; Chromium-verified in the sandbox (en/ar/zh, 900px and 375px), recorded in `docs/audit/net-consent-hosts-2026-09-16/`. Three broken ride-along opt-outs found and DISCLOSED, not fixed — the fix needs a ruling on where it lands (`OPEN_QUEUE.md`, 2026-09-16) |
| I | The import lifecycle: fresh page, four visible stages, one poll chain, K = 3, one API path | session | ruled (R1–R3; Q201–Q207, Q214, Q216, Q217, Q221, Q222) · `S04-02` | **OPEN** |
| J | The export: dated `OpenOmniscience_Backup` folder, completion panel, `BACKUP_SUMMARY.md`, verify-after-write | session | ruled (R4, R5; Q208–Q213, Q218–Q220, Q1008) · `S04-03` | **OPEN** |
| K | ONE backup-format bump: the alpha-3 restore normaliser, all rings, the tentative-translation table, the fetch/scrape-history member with its trust toggle | session + operator (the real-restore proof) | ruled (Q215, Q310, Q313, Q404, Q409, Q701 note) · `S04-04` | **OPEN** |
| L | ISO 3166-1 alpha-3 step 1: display + boundary, the loader normalises, the filename rule | session | ruled (R6; Q301 = c step 1, Q302, Q303, Q307–Q309, Q311, Q312; Q306 display step *proposed placement*) · `S04-05` | **OPEN** |
| M | Keywords in the UI language: the label grammar, the three-tier ladder, auto-loaded rings at 1 / 10 s, lemmatisation, per-mention language | session (+ one operator ritual per tag) | ruled (R7, R8; Q401–Q404, Q406–Q408, Q410–Q414, Q416, Q418) · `S04-06` | **OPEN** — the stoplist merge (Q1103/Q1104) is HELD on a CONFLICT |
| N | Cross-language search through the rings in every tab; CJK segmenters; Arabic folding; the literal toggle | session | ruled (R10; Q417, Q501–Q504, Q506–Q512, Q514–Q516) · `S04-07` | **OPEN** |
| O | The versioned-source substrate; one encrypted database file per lane; lanes replace the scheduler mode; the Living sources view; reference-VM budgets | session | ruled (Q716, Q719, Q720, Q926, Q1003–Q1007, Q1010, Q1011, Q1014–Q1016, Q1018, Q1020) · `S04-08` | **OPEN** |
| P | The Wikipedia lane: EventStreams metadata for every edit in twelve editions, HOT full text, the top-bar toggle (default on), the wizard, disclosure | session + operator (the ≥ 72 h run) | ruled (R12; Q108, Q702–Q715, Q717, Q718, Q721, Q725–Q728, Q819 steps 1–2) · `S04-09` | **OPEN** |
| Q | The law metadata model, the L0 defects, translations as tracked documents, the first bulk adapters, the vetting board | session + operator (the 44-row board; live adapter checks) | ruled (R14, R15; Q107, Q901, Q902, Q904–Q910, Q914 1–2, Q915, Q917, Q919, Q921–Q924, Q927) · `S04-10` | **OPEN** — the adapter ORDER (Q925 ⛔) is PENDING |
| R | Equal Earth on all five map surfaces; Natural Earth 50m; OSM's border convention, CONTESTED both-claims, a worldview toggle | session | ruled (R13; Q801–Q803, Q826) · `S04-11` | **OPEN** |
| S | Sources: `qualified` ⇒ `enabled`, the hatch retired, the overlay editor, the institutions moves, the Stage B splice, the stratified round-robin | session + operator (the shortlist run) | ruled (Q1101, Q1105–Q1112, Q1114–Q1119, Q1156) · `S04-12` | **OPEN** — the embassy platforms (Q1113 ⛔) are PENDING |
| T | Network budgets and politeness: the per-process bandwidth budget, the persisted Crawl-delay cap, the loopback rate limit, the airplane titles, the net-coach weights, weight digests | session | ruled (Q1012, Q1013, Q1125, Q1126, Q1132, Q1148) · `S04-13` | **OPEN** |
| U | UI, i18n and the small rulings: the 470-string remainder, the religious-calendar feature dropped, the encrypted click-through variant, the `diagnostics.py` split, the FUTURE_DEVELOPMENTS reality check, newsletter attach | session | ruled (Q1124, Q1130, Q1135, Q1139, Q1141, Q1149, Q1151, Q1152) · `S04-14` | **OPEN** |
| V | The release ritual and the allowlist: release notes from `shipped.csv` + the no-telemetry re-check; the session environment's egress allowlist | operator | ruled (Q111, Q114 ⛔ = a, Q116) · `S04-15` | **OPEN — the generator half SHIPPED 2026-09-15** (`scripts/release_notes.py`, wired into `release.yml`); the allowlist and the per-surface click-through records are the operator's |

Rows A–C are the substance. D and E exist because A and B are both **operator** rows whose
closing clauses ask for a number nobody currently has a single place to read — and a row whose
evidence has to be assembled by hand is a row that closes on somebody's memory.

**The exit (amended 2026-09-15).** `v0.4.0` is tagged when rows A–E and G–V are CLOSED on named artifacts
(F is closed), the three i18n gates and the whole-tree guards are green on the tagged tree, and the release
notes carry the no-telemetry re-check (row V). A PENDING ⛔ question blocks only the row that names it:
Q925 blocks nothing on row Q beyond the adapter order; Q1113 blocks nothing on row S (the status quo
excludes those hosts); Q823 and Q1009 are `0.5` matters. No date (Q110 = c).

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
2. **The qualification admission gate over every source that is not the curated catalogue,
   and the six-month re-check over the catalogue itself.** *Amended 2026-09-10:* the
   maintainer ruled the curated catalogue **qualified at seed** ("make the curated catalogue
   qualified, and as with any other qualified sources, they should go through the same
   periodic re-qualification process"), which supersedes the 2026-07-20 no-grandfathering
   clause this item carried. What the row now demonstrates is that the stamp's basis
   survives the import as `curated` (never laundered into a measured verdict), that the
   catalogue's re-checks actually run, and that a catalogue source whose re-check fails is
   disqualified like any other — still a **catalog-review** signal, not a source to exempt.
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

**New in this window, and worth a glance while it runs (P6, 2026-09-11):** every
`collect_perf.jsonl` sample now carries a `loop` block — the API server's own event-loop lag,
as the share of a 10 s window that was blocked. It is *not* a gate condition and closes
nothing here; it is recorded because the bench that motivated it could not make the collector
starve the server (a synchronous handler cost 3.4-3.5 ms at p50 whether 0 or 32 workers were
collecting), and a three-day run at release scale is the first thing that could contradict
that. `loop_lag_ticks` in the pass summary is 0 on a healthy pass by design, so a non-zero one
is the signal — and if the accompanying note says the back-off *stood down*, the loop was
being blocked by something that is not the collector.

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

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies.** `RC08.3` asked where register ruling
**E1** («Automate this in the diagnostic bundle.») lands. It came back blank, so its stated default is taken
as a labelled **ASSUMPTION: (a) — `month-occupancy.json` becomes a member of THIS row's bundle**, sampled as
the ruling specifies, with no operator script run; PROMPT_06 slice 3 (the date-aware month block and its
re-index) reads it from the bundle rather than from a hand-run measurement. This adds ONE member to the
bundle and changes no bar: the row still closes on a `complete: true` coverage block with every member
non-zero — which the new member must therefore satisfy too. The re-index remains the operator's. Reversed by
writing a letter at `ANSWER RC08.3`.

---

### Row D — row B's evidence is readable from one artifact · *proposed* · BUILT

**Why it is a row.** Row B's bar is a property of a three-day window, and until now no single
artifact answered *"did the soak pass"*. The instruments existed — `collect_perf`, the memory
guard, the write gate, the `wal_bytes` hourly series, the latency reservoir, the error log,
session forensics — with **different and mostly undocumented windows**, several of them far
shorter than three days. Assembling the answer by hand is how a two-hour reading acquires a
three-day label.

**Built in this PR:** `GET /api/diagnostics/soak-window`, riding the all-diagnostics bundle
as `soak-window.json`. It adds no sampler. It composes the durable readings that already exist
and states, per block, **the window it actually read**:

| Block | Reading | Its window |
|---|---|---|
| `window` | process uptime, and whether it reaches 72 h | the soak's own clock |
| `memory_guard` | engage cycles per day, paused share | process-cumulative, aligns with the clock |
| `wal` | the `wal_bytes` maximum inside the window | hourly snapshots, infinite retention, filtered down to it |
| `write_gate` | busy share, contention | process-cumulative, aligns with the clock |
| `database_stats_latency` | the `/api/database/stats` p95 | the last ≤512 requests — **not** the soak |
| `interrupted` | statements aborted mid-flight | a rolling 2,000-record log — a **floor** at capacity |

Three counters had to become durable for this to be possible at all: the write gate now
accumulates `total_held_s` on release (an in-flight hold stays in `held_for_s`), the memory
guard counts `engagements` and `total_engaged_s` (closed episodes only), and the error log
recognises both shapes of an aborted statement — the typed `StatementTimeout` and SQLite's raw
`interrupted` — and publishes its own `records_cap` beside every count, so the retention that
bounds them travels with them.

It is **verdict-free** on purpose: `window.reaches_bar` is a fact about the window's *length*,
and what the numbers inside it mean is the maintainer's reading. It does not re-derive P0.3's
RSS verdict — that stays P0's — and it publishes no composite.

**Closes when:** one soak-window report from a run of ≥ 72 h exists and is read alongside the
P0.3 report. Until a real soak happens, this row is *built, unread* — the honest state, and
not the same as closed.

**DRIVEN END TO END AT FIXTURE SCALE (2026-09-15).** A synthetic corpus seeded through the real
`index_article` (`scripts/ui_clickthrough_seed.py`, 440 articles), the app served on loopback,
and the report read twice — once from `GET /api/diagnostics/soak-window` and once as
`soak-window.json` out of the 73-member `GET /api/diagnostics/all` archive, which is the "ONE
artifact" this row is named for. Per block, what fixture scale could and could not reach:

| Block | At fixture scale | What it needs from row B |
|---|---|---|
| `window` | **measured** — 0.01 h, `reaches_bar: false` | the 72 h itself: only a real soak can make that `true` |
| `write_gate` | **measured** — 1 grant, `busy_share` 0.0098, 0 contended | nothing; the counters are process-cumulative and already live |
| `interrupted` | **measured** — 0 this session, 9 log records, `at_capacity: false` | nothing; a long run is what makes `at_capacity` meaningful |
| `database_stats_latency` | **measured after one call** — p95 12.8 ms at `window_n: 1` | volume: it reads a 512-request reservoir, so its `window_n` is what makes a p95 readable, and the payload already says the window is not the soak |
| `memory_guard` | **unmeasured** — "uptime is 77.9 s, under the 300 s floor a per-day rate needs to mean anything" | any run over five minutes clears the floor |
| `wal` | **unmeasured** — "`wal_bytes` has never been recorded on this install" | the hourly, off-peak recorder has to have run, i.e. a scheduler up for hours against a real corpus |

So **the mechanism is proven and the window is not**: nothing in the tree can make
`reaches_bar` true, and `memory_guard` / `wal` leave `unmeasured` for the same reason —
elapsed time on the operator's machine. The two blocks that report `measured: false` do so with
a reason and are listed in `unmeasured`, which is the honest shape and not a reading of zero.

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

**BUILT 2026-09-07** (prompt 07 S5, `src/catalog/qualification_integrity.py` +
`GET /api/diagnostics/qualification-integrity`, a member of the all-diagnostics bundle as
`qualification-integrity.json`). It answers the closing clause and does **not** need the
before/after pairing this row asked for, because of one property of the data: the attempt log
**is** the "before". `source_qualification_attempts` is append-only, it is carried by the merge
with ids remapped, and `evaluate_and_stamp` writes the attempt row and `Source.status` in the
same transaction — so for any judged source the two must agree, and

    status == the verdict of its NEWEST judging attempt

A violation is exactly the 2026-07-24 inversion. That makes the clause answerable **after** an
import rather than only around one, so an operator who has already run it can still answer this
row months later from the corpus itself.

**What it publishes:** both directions kept apart (`laundered` — judged disqualified, no longer
disqualified, the direction Row A names; `demoted` — the same stamp loss starving a source out
of collection), each **named** up to a cap with the exact total beside it; the disqualified
sources it examined, named (Row E's "state its own result"); and `checked.with_judging_attempt`
as the denominator, because a corpus with no judgements reports `not-measurable-here` rather
than a clean bill of health — "nothing wrong" and "nothing to look at" are opposite findings.

**What it cannot see, stated in the payload:** a regression that dropped the stamp columns *and*
the attempt rows together leaves the receiving instance no "before" either. That is what the
denominator is for.

**Still open on this row:** the RUN. The check is Row A's instrument, so it closes when Row A
does — read `qualification-integrity.json` out of an all-diagnostics bundle taken after the
committed import, and the clause is answered by a number naming the sources.

**DRIVEN END TO END AT FIXTURE SCALE, IN BOTH DIRECTIONS (2026-09-15).** On the same seeded
instance as row D, read through `GET /api/diagnostics/qualification-integrity` and out of the
`GET /api/diagnostics/all` archive:

- **Clean corpus** → `verdict: "consistent"`, *"Every one of the 14 judged sources still carries
  the verdict its own attempt history last recorded"*, with `checked.with_judging_attempt: 14`
  against `sources_total: 18` and the one currently-disqualified source NAMED
  (`verified_disqualified_sample: ["prefcentre.example"]`). The denominator is the point: it is
  what separates *nothing wrong* from *nothing to look at*.
- **Seeded inversion** (that source's live status flipped to `qualified` while its newest
  judging attempt still reads `disqualified` — the exact 2026-07-24 shape) → `verdict:
  "inversions-found"`, `laundered_total: 1`, `demoted_total: 0`, and the row named in full:
  `{domain: prefcentre.example, live_status: qualified, last_judged: disqualified, judged_at:
  2026-08-11T17:54:21+00:00, criteria_version: v1}`. The finding arrives intact in the archive
  member, not only from the function — `test_the_bundle_member_carries_the_finding_not_a_stub`
  pins that layer, and this run confirms the HTTP layer above it.

So **"tooling that can state its own result" is true today**: it states a verdict, both
directions apart, names the sources, and refuses to read a corpus with no judgements as a clean
bill of health. **What it needs from row A is the IMPORT** — this check cannot supply one, and
a `consistent` verdict on a corpus that has not been imported into says nothing about the
merge. Row A's operator step is: take an all-diagnostics bundle AFTER the committed import and
read this member; the clause is answered by `inversions_total` with the sources named beside
it, whichever way it goes.

---

### Row F — the browser bar reaches a human, a second engine, or is closed as-is · *proposed* · CLOSED as-is 2026-09-15

**THE VERIFICATION BAR — the sentence every surface cites, and the one place it lives.** Ruled
2026-09-15, **Q1128 = a** (`RULINGS_INDEX.md`), which **Q117 = a** used to close this row as-is:

<!-- release-notes: verification-bar -->
> Chromium in the sandbox + the maintainer's click-through = verified; Gecko best-effort.

It is quoted from HERE and nowhere else — `scripts/release_notes.py` reads it out of this file
behind the marker above rather than carrying a copy, because a mirrored copy fails in the
safe-looking direction: reword the gate and a copy goes on quoting the old wording while every
check still passes. `docs/plans/2026-09-12-beta-pathway/_WORKING_MODE.md` §3 carries the same
sentence verbatim as the instruction to a building session; this block is the citable form.

**Both halves, or neither.** A surface that a session drove in Chromium and no human has opened
is stamped *"Chromium-verified (remote sandbox) · awaiting human UX pass"* — that is not
*verified*, and the stamp may not be shortened to it. A Gecko run is a strengthening nobody is
owed: its absence never blocks a row, and its presence is recorded as *"Gecko-verified (VM)"*
beside the Chromium record, never instead of the click-through.

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

**What the 2026-09-08/09 live visual audit + fix pass added, and what it did not close (2026-09-09).**
Two of the three open items above moved:

- **The 12-locale sweep is done.** All 12 locales were driven live, crossed with all 17 themes and 5
  viewports, plus `prefers-reduced-motion`, `prefers-contrast`, greyscale and colour-blind simulation
  (`docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md`, §7). The four-locale gap this row records is closed.
- **Honesty rule 9 (adversarial screenshot reading) ran in a different form than the rule imagines.**
  Rather than one pass re-reading its own screenshots, three independent adversarial re-verifiers
  re-derived every fix against pre-fix code and were asked specifically for fixes that do NOT work.
  They found one real regression (a French-locale mixed-language screen), confirmed its repair by
  revert-reproduce-restore, and reported two residuals the fix pass had missed. That is the *function*
  rule 9 exists for; whether it satisfies the rule as written is a maintainer call.

**Neither closes the row.** The Gecko/AppVM bar is untouched, and every stamp still reads
*"Chromium-verified (remote sandbox) · awaiting human UX pass"* — deliberately, because no human has
used the app. The three ways this closes are unchanged. What the audit does change is the cost of the
third option: a ruling that "Chromium-in-sandbox plus the audit is the bar" is now a ruling about a
much larger body of evidence than it was on 2026-08-20, and §0.1b of that report is the honest
counterweight — the instrument itself was wrong twice, and both times the error ran toward a false
pass.

---

## 2b. The rows added 2026-09-15 (G–V) — from the answered roadmap sheet

Every row below is **ruled** by the question IDs it cites (labels verbatim in `docs/ledger/RULINGS_INDEX.md`);
sentences marked *proposed placement* or *design note* are the planning session's and bind nobody. "Closes
when" names an artifact a later reader can re-open. Where the sandbox cannot measure a bar the row says so
and names the operator step (`not-measurable-here` is a legitimate state, `pass` on a proxy is not).

### Row G — `0.3` closed and the version flipped · ruled (Q109 = a) · OPEN

**What it must demonstrate.** The `0.3` board's row 5 (the Tier-A quarantine run, 8 articles — the four
commands in `RELEASE_0.3_GATE.md` §7.1) is run from the maintainer's machine and the `v0.3.0` tag exists;
then `pyproject.toml` flips to `0.4.0` (the 0.2→0.3 sequence: pass → tag → flip). **Closes when** the tag is
on the remote and `main` reads `0.4.0`. **Operator:** both steps. Brief `S03-01`.

**PREMISE CHECK (2026-09-15, found while writing brief `S03-01`; hand-verified):** the remote ALREADY carries
`refs/tags/v0.3.0` at `917e8095` — the 2026-08-23 merge of PR #979 — and a published GitHub release `v0.3.0`
(`prerelease: true`, created 2026-08-23T12:39Z, wheel + sdist + `SHA256SUMS` uploaded by the release
workflow), cut BEFORE row 5 was run and before this board or the answer sheet were written; the 0.3 gate's
§7.3 says "do not start this until row 5 is ticked", `README.md:8` still reads "latest tagged release:
`v0.2.0`", and the 0.3 gate's §1/§3 record no tag. So the sheet's "the `v0.3.0` tag from your machine" and
this row's "then the tag" describe a step that is ALREADY DONE as a pre-release; what remains is row 5 (the
quarantine run), the maintainer's word on whether that pre-release IS the 0.3 tag or is to be superseded by a
full release once row 5 is run (a tag cannot be moved; a second release can be published), the README /
0.3-gate records, and the version flip. Q109 = a stands as answered; its premise is corrected here and in
the brief, per the recorded rule that a plan's premise is checked in the tree, never accepted from the
document that states it.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC01` asked whether the version flip may proceed on the
existing `v0.3.0` pre-release without row 5. It came back blank, so its stated default is taken as a labelled
**ASSUMPTION: (b) — this row keeps waiting on 0.3 row 5.** The version stays `0.3.0` until the maintainer runs
the quarantine; A1 stays `deferred` with no date; the premise check above is unchanged and still describes the
pre-release. Reversed by writing a letter at `ANSWER RC01`.

### Row H — `docs/SECURITY.md` enumerates every host; the consent hover lists them per lane · ruled (Q1001 = a, Q1002 = a) · BUILT, awaiting the maintainer's click-through

**What it must demonstrate.** The "full set of endpoints the app can reach" section names the hosts the tree
already reaches and the section omits today (the Wikidata Query Service the default-on discovery ride-along
reaches, the Wikipedia Action API, ORES / Lift Wing, the Wikimedia dumps host, the OSM mirrors), and from
then on every PR that adds a host adds it there **and** to the consent popup's hover in the same diff, with a
repo test that greps the fetch sites against the list (Q1001). The one popup stays; its hover lists, per lane,
the hosts that lane will contact, and its body names the lanes that are on (Q1002). **Closes when** the test
exists and is green on the tree that tags, and a Chromium click-through of the popup hover is recorded
(Q1128). Docs-only first (the SECURITY.md half ships as its own PR, per Q1001's "now"). Brief `S04-01`. *Premise check (brief `S04-01`):* two more hosts the tree reaches are absent from the list — `www.wikidata.org/w/api.php` (`src/catalog/wikidata_enrich.py:33`) and `huggingface.co` (`src/llm/weights_pin.py:30`, `vllm_lifecycle.py:241`); the consent dialog has no hover `title` today (`index.html:3133–3149`); no test references `SECURITY.md`.

### Row I — The import lifecycle · ruled (R1–R3; Q201–Q207, Q214, Q216, Q217, Q221, Q222) · OPEN

**What it must demonstrate.** Four stages shown as four rows with their own progress (Q202); the three safety
statements at the moments ruled — files removable after the swap, close/update safe after the swap (a durable
cursor resumes stages 3–4 on the next boot), analytics complete after stage 4 (Q203); stage 4 (the deferred
re-index) inside the import experience as its own row, progress from the existing resume status endpoint, a
link to the task manager (Q204), auto-resuming on boot with "resuming re-index (N left)" (Q205); ONE poll
chain, ONE bar owner, rows patched in place (Q206) — the blinking and overlap R2 named are a defect and their
absence is a bar; a fresh page on reopen (R1) with one quiet "Last import · date · N articles · open report"
line linking the persisted import report (Q201 — this SUPERSEDES the 2026-07-16 `_uxShowLastCompletedSummary`
behaviour); the "Details" block removed (Q207, an ASSUMPTION at the sheet's default, supported by R2);
`import-queue/*` is the one path — `v2/restore/*` deleted after anything only it does moves into the queue,
`reindex-*` wired (Q214); verify + swap once per **K = 3** backups (Q216 ⛔ = a — a checkpoint the code counts:
a two-item group reuses the working copy, `merge_batches` 2 vs 1, per the recorded 2026-09-07 measure);
prefetch only if the first real `verify_copy` timing shows "prepare" still dominating (Q217 — measure first);
each lane's import is a row with the same four stages when lanes exist (Q221); history lives in Settings →
Backup (Q222 = b). **Closes when** (1) a recorded Chromium click-through shows the four rows, the three
statements at their stages and the fresh page with its one line; (2) a test kills the app between stages 3
and 4 and proves the resume; (3) a repo test asserts the `v2/restore` routes are gone (anchored to the router
definitions, never the app singleton's live route table, per the recorded flakiness lesson). Brief `S04-02`. *Premise check (brief `S04-02`):* the durable cursor exists (`reindex_job.json`, the resume endpoint) but boot only LOGS the backlog and an interrupted run is parked PAUSED — the auto-resume Q205 names is the delta, not a fact; the sheet's "zero frontend callers" holds.

### Row J — The export · ruled (R4, R5; Q208–Q213, Q218–Q220, Q1008) · OPEN

**What it must demonstrate.** The folder `YYYYMMDDHHMM_OpenOmniscience_Backup` (Q212 = c spells the token
out, amending R5's literal `OOS`), local time (Q210), `_2`, `_3` … on collision (Q211); **always a full new
backup, no reuse** (Q213 = c — the incremental reuse pool is not consulted by exports; state the cost in the
panel: every export writes every volume); the completion panel listing volumes · total bytes · per-table counts
with articles first · files copied per category (dumps, models, newsletters) · elapsed · destination ·
encryption state · schema version · app version · the licence lines that apply (Q208, Q1008 — the press
lines now; OSM lines wait on Q823 ⛔); `BACKUP_SUMMARY.md` beside `volumes.json` with the same facts (Q209);
re-read every volume after writing and check its checksum, default ON, the panel says "verified" (Q218);
never a scheduled export (Q220 = c); the Wikipedia, OSM and law lanes as opt-in members with their sizes shown
before the export starts (Q219 — the member hook now, members as the lanes land). **Closes when** an export
produced on the reference VM shows the folder name, a `BACKUP_SUMMARY.md` whose figures equal `volumes.json`'s,
and a panel reading "verified"; the artifact is the folder listing + the summary file quoted in the PR.
Brief `S04-03`. *Premise check (brief `S04-03`):* the sheet's "no `OOS` string exists in the tree" is FALSE — `src/bulletin/annexes.py:122–130` (`YYYYMMDD_OOS_Bulletin_<cadence>`, `_2` and up), `src/bulletin/evidence.py:232` (`-OOS-…-evidence.zip`), `src/bulletin/store.py:19–60`; whether Q212 = c's spelled-out token also renames the bulletin, evidence and store names is an OPEN DETAIL for the maintainer (the brief lists it, never decides it).

### Row K — ONE backup-format bump · ruled (Q215 ⛔ = a, Q310, Q313, Q404, Q409, the Q701 note) · OPEN

**What it must demonstrate.** One format-version bump carrying five payloads, so the 0.5 storage half has one
format to exercise (Q301 = c makes this row its precondition): (1) the restore path normalises alpha-2 →
alpha-3 while importing, so every older backup stays restorable forever, and the gate proves it with a
duplicate-key scan after restoring a PRE-migration backup (Q310); (2) ALL rings ride the backup, shipped ones
included (Q409 = b) — *design note:* a restored backup's shipped rings must never override a newer release's
shipped rings, so the member carries the ring file's version and the newer wins; (3) the `keyword_translations`
table (term, source lang, target lang, text, model, prompt version, created), never the trusted index, always
≈ (Q404 🔒 = a); (4) **the fetch / scrape history of everything the app downloads** — press feeds, the
Wikipedia lane, and later OSM and law — rides the backup so a fresh install restored from an old backup does not
re-download the same pages and prioritises other fetches, with a **"trust the backup scrapping history"** toggle
offered at install and at import (the Q701 note, verbatim intent; the toggle's copy ×12 and its caveat
visible per the informed-consent non-negotiable); (5) the legacy single-file restore half is kept forever,
as its docstring commits (Q215 ⛔ = a — register C1 closed); exports carry both `country` and `country_iso3`
for this one release (Q313). **Closes when** the maintainer restores a real pre-migration backup on their
machine and the duplicate-key scan reports 0 duplicates (operator; the scan's output is the artifact), the P0
data-safety trio is re-run green on the new format (the `0.3` runbook), and a CI restore of a fixture backup
proves each of the five members round-trips. `not-measurable-here` for the real-restore half. Brief `S04-04`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC02` ⛔ (C1 «a, but wait for version 0.7» against
Q215 = a) came back blank on a ⛔ question, so it **stays PENDING and is never defaulted**. Payload (5) is
unchanged: the legacy single-file restore half is kept forever as its docstring commits, `S04-04` builds on
Q215 = a, and no 0.7 removal row exists. Nothing in this row moved.

### Row L — ISO 3166-1 alpha-3, step 1 · ruled (R6; Q301 ⛔ = c, Q302, Q303, Q307–Q309, Q311, Q312) · OPEN

**What it must demonstrate.** The DISPLAY + BOUNDARY half of Q301 = c (FULL, staged): every code the user sees
is alpha-3; **the code is displayed and the full country name, in the UI language, is in the hover bubble**
(Q302 as the maintainer wrote it — the note inverts the option label; the hover is the #oo-tip convention,
invariant #17); World-Bank-compatible codes for non-countries (`EUU`, `XKX`, `ANT` legacy only, `GBR` for the
law `uk`, app-defined `INT`), each disclosed in the hover as "not an ISO code" (Q303); payloads gain
`country_iso3` beside `country` and every parameter accepts both forms through `normalize_country` (the 0.4
shape of Q304; the flip is 0.5); the loader normalises the 5,803 `country:` / `jurisdiction:` config lines
without rewriting the files (Q305 "follows Q301" — step 1); flags derived internally alpha-3 → alpha-2
(Q307); pickers ordered by localised name with the code as a secondary column (Q308); the filename rule — a
filename carrying a country uses uppercase alpha-3 — enforced by a repo test over the `data/` naming helpers
(Q309); external contracts stay alpha-2 behind converters, with `P298` fetched in the catalog query as a
cross-check (Q311); timing 0.4 (Q312). The two frontend mechanisms that break silently on alpha-3
(`Intl.DisplayNames` at `app-map.js:91–99`, the `/^[A-Z]{2}$/` flag gate at `app-agenda.js:981–985`) are
fixed and browser-checked. *Proposed placement:* the ISO 639-2/3 language-code move (Q306 = b) takes the same
two steps — display here, storage in 0.5 — because the two normalisations share a branch at `csv_io.py:130`.
**Closes when** a Chromium click-through record shows codes + hovers on every surface that shows a country
(map, agenda, sources, markets, laws, wiki), the filename-rule test exists, and the 0.4 exports carry both
columns. Brief `S04-05`.

### Row M — Keywords in the UI language, "translated from X" · ruled (R7, R8; Q401–Q404, Q406 ⛔ = b, Q407, Q408, Q410–Q414, Q416, Q418) · OPEN

**What it must demonstrate.** The translation is the visible term, a small "translated from French" tag
follows it, the hover shows the original, the ring's other members with counts and the source (Q401); the
source language is named in the UI language (Q402); the three-tier ladder — verified (ring) · tentative (LLM,
always ≈) · untranslated (tagged, still searchable) — through ONE display helper on every keyword surface,
the seven endpoints gaining `target_lang`, `_annotate_translations` gaining `translation_source_lang`,
`translation_tier`, `senses` (Q403); the `keyword_translations` table (Q404, row K); **rings auto-load
without review** at ≤ 1 request / 10 s (Q406 ⛔ = b; the generator's 0.2 s spacing changes to 10 s) — *design
note:* an auto-loaded ring is disclosed as "from Wikidata, unreviewed" and stays editable in Settings, and the
consent/visible-job rules apply to the fetch; growth from the gap digest (Q407) through `wbsearchentities` then
`wbgetentities` per item, 10 s apart (Q408); the shipped rings regenerated on the maintainer's machine before
each tag, top 2,000 keywords per language (Q410 — an operator ritual, recorded in the release notes); cards
translate the term as a ruled exception to the "data never translates" note at `i18n.js:162` (Q411 — the
comment is amended in the same change); the 91 collision terms get "several senses" + a sense picker and
`translate_term` gains the refusal path (Q412); the source language is the ring member's effective language and
the `reconcile_keyword_language` pass **runs in this gate** (Q413 — the report is the artifact); language
stored per mention with the keyword's language derived as the majority (Q414); `simplemma` in core, lemmatise
at extraction, a migration job re-normalises existing keywords (Q416); the hover bubble contents (Q418).
**HELD:** the triage-derived stoplist merge — Q1103 = b ("Never; the shipped stoplists are frozen", with a
note asking for a stopword diagnostic and per-release growth) against Q1104 = a ("Yes, through the review
surface, batch by batch") is a recorded CONFLICT; the row ships without any merge until the maintainer picks,
and the stopword DIAGNOSTIC the note asks for may ship (it decides nothing). **Closes when** every keyword
surface renders a tier tag (a Chromium click-through record across the eleven silent surfaces), the reconcile
report exists, a fixture proves the 10 s spacing and the refusal on the kill switch, and `simplemma` is in
`pyproject` core with its registry entry. Brief `S04-06`. *Premise check (brief `S04-06`):* `simplemma` is ALREADY a dependency — `pyproject.toml:147` under the `[analysis]` extra, used display-time only (`OO_FAMILY_LEMMA`, `src/analytics/families.py`), with no registry entry; the delta Q416 asks for is core + at-extraction + the migration, not a new package.

### Row N — Cross-language search through the rings, everywhere · ruled (R10; Q417, Q501–Q504, Q506 🔒 = b, Q507–Q512, Q514–Q516) · OPEN

**What it must demonstrate.** `resolve_concept(term, ui_lang, sense)` computed once per analysis tab and passed
to both the FTS path and the keyword-keyed aggregates; "only the words I typed" is one toggle persisted in the
tab seed and the URL (Q501, Q504); stacked per-language series with a legend (Q502); the 40-literal cap, most
frequent first, disclosed — **with a user toggle to deactivate it, cap on by default** (Q503 note); the
segmenter dependency for zh / ja (`jieba`, `sudachipy`) (Q506 🔒 = b — registered, optional-extra or core per
Q1015's rule, with the re-index job it implies; the zh emphasis of the Q911 note applies); Arabic
`remove_diacritics=2` + alef / teh-marbuta / yeh folding at index and query time (Q507); results interleaved by
date with a language chip **and a group-by-language option** (Q508 note); per-language counts on the chip
**plus the single total** (Q509 note); a watch on "climate" watches the ring (Q510); bulletin sections built
from keywords use the ring, **and a new bulletin annexe carries all ring analytics and details** (Q511 note);
the ring is the mind-map centre, each language an arm (Q512); tentative translations never expand a search
unless the user opts in per query (Q514); **exact, uncapped totals** (Q515 = b — state the cost on the
ring-size extremes); the Observatory, the map and the sources tab read the same resolution (Q516); rising /
trends / top computed per ring with a per-language breakdown in the hover (Q417). **Closes when** "every
analysis tab agrees with the Articles list on the same concept" is demonstrated on the reference corpus (a
recorded comparison, numbers in the PR), the CJK and Arabic re-index has run on it (the fixture and the
reference corpus, counts before/after), and the toggles are Chromium-verified. Brief `S04-07`. *Premise check (brief `S04-07`):* the FTS tokenizer is already `unicode61 remove_diacritics 2` (`src/database/fts.py:254`; also `src/wiki/dump_index.py:84`), so Q507's first half exists and only the alef / teh-marbuta / yeh folding is new; and the tree's `[segmentation]` extra (`pyproject.toml:193–195`) already carries `jieba` + `janome` (ja) + `pythainlp` on the keyword-extraction path, where Q506 = b's label names `sudachipy` for ja — which library serves the FTS path is an OPEN DETAIL for the maintainer, never substituted by a session.

### Row O — The versioned-source substrate and the lanes · ruled (Q716, Q719 🔒, Q720 🔒, Q926, Q1003–Q1007, Q1010, Q1011, Q1014–Q1016, Q1018, Q1020) · OPEN

**What it must demonstrate.** `src/versioned/` shared by the wiki, law and OSM lanes, the wiki adapter first
(Q1003): identity `(kind, external_id)` + QID, an immutable baseline, a change feed with cursor, gap detection,
budget and politeness, a revision store, the latest as an Article, point in time, disclosure. One database file
per lane — `corpus.db` + `wiki.db` + `osm.db` + `law.db` — each encrypted alike, each an opt-in backup member,
linked by ids (Q1004, Q719, Q926); encrypted with the same passphrase and threat model, no per-lane plaintext
(Q1005, Q720); **SQLite for everything**, DuckDB not used for the lane tables (Q1007 = b, Q811 = b) — the
PostgreSQL-parity aspiration stands (Q1140) and no table widens past Postgres's column limit (the Q1140 note,
*design note*). Wikipedia becomes a lane beside RSS; `mode="wiki"` is retired with a migration; `POST
/api/wiki/pages` survives as "pin this page to HOT" (Q716, Q1020): the scheduler runs lanes (press, wiki, osm,
law, hazards, discovery) under one online consent, one governor, per-lane budgets. Each lane declares its
transport in the consent hover and never downgrades Tor → clearnet (Q1014). Dependencies: compiled code only in
optional extras, pure Python in core, SSE hand-rolled over the guarded session, every addition registered
(Q1015). Settings → Storage shows each lane's size, budget, the honest growth arithmetic and the disk left,
budgets published and sized for the 2-core / 3.5 GB reference VM (Q1006, Q1010); the app reads cores, RAM and
free disk at boot — no network — and proposes budgets from a published table (Q1011). Synthetic fixtures — a
wiki edition, an OSM extract, a jurisdiction — so every lane's pipeline runs end-to-end in CI without a socket
(Q1018). The Living sources view — timeline of changes, diff, coverage, freshness, budget — replaces the
tracked-changes modal (Q1016; **open detail:** "a main tab or a Home family — your call in a NOTE": no NOTE
was given, so the brief proposes a main tab and asks in its PR body; invariant #2's tab roster grows by one if
so). **Closes when** the CI fixtures run green with the socket guard armed (the airplane socket guard proves
zero resolutions), a wiki page round-trips baseline → change → revision → Article on the fixture, the lane
files exist encrypted with the corpus passphrase, and the `mode` migration is exercised on a real settings
store. Brief `S04-08`.

### Row P — The Wikipedia lane: the stream and the HOT tier · ruled (R12; Q108, Q702 ⛔, Q703–Q715, Q717, Q718, Q721, Q725–Q728, Q819) · OPEN

**What it must demonstrate.** EventStreams (a persistent SSE connection, hand-rolled) delivering metadata for
every edit in all twelve editions, resumed with `Last-Event-ID`, falling back to `list=recentchanges` per
edition when a gap exceeds the stream's retention and recording an honest gap otherwise (Q727); **a dedicated
Wikipedia toggle in the top bar, DEFAULT ON — like the AI toggle, with a nice and consistent animation — letting
the user stop / start / halt / resume the streaming** (Q702 ⛔ as the maintainer wrote it; the label's "default
off" is overridden by the note; the one online consent still gates the first egress, invariant #14; the new
element keeps a constant footprint, invariant #3, and its strings ship ×12). Namespace 0 without redirects,
with disambiguation and list pages (Q703); wikitext stored + a derived plain text for FTS (Q704); the metadata
list confirmed (Q705: pageid · QID · sitelink count · categories · length · revision count · protection ·
last editor class · infobox fields · coordinates · image / external-link / citation-needed counts · assessment
class · creation date · edition); pageviews: the daily top-1,000 per edition + per-article daily views for HOT
pages (Q706); three tiers under a per-edition daily budget the wizard sets, default 20 GB total, published
(Q707); **every edit as a row for every page, kept raw** (Q708 = b, Q709 = b — the FROM-MEMORY figure is
250–300 k rows / day; this row MEASURES it); retention HOT every version, WARM latest + previous, counters and
metadata forever (Q710 🔒); the diff against the previous ingested version, section-aware, revid-anchored
(Q711); analytics 1–3 in 0.4 — edit velocity per topic / country / language, contested pages by revert rate,
newly created pages as emerging topics (Q712); creation / deletion / move from the log events (Q713); separate
lane counts everywhere, the "articles" headline stays press (Q714); identity `WikiPage(wiki, pageid)` + `qid`,
the Article carrying `wiki_pageid`, `qid`, `source_revision`, `source_type="wikipedia"`, the edition as
language (Q715); ORES / Lift Wing verified, opt-in, ≈ (Q717); Wikimedia Enterprise excluded under V1-2 (Q718);
HOT pages' Articles ride the corpus backup, the lane is an opt-in member (Q721); the first-run wizard: edition
choice (default all twelve) + the storage budget + the plain statement of what the lane contacts (Q725);
disclosure in `SECURITY.md`, the robots exemption stated the way `stats/fetch.py:22–25` does, the reader shows
the CC BY-SA 4.0 attribution with a link to the page history (Q726); the modal becomes the Living sources view,
the dump machinery stays as an opt-in offline reader, the dump→corpus endpoint is retired (Q728); Wikipedia
page coordinates become a map layer and OSM objects tagged `wikidata` / `wikipedia` resolve to the same Place
(Q819 steps 1–2 — step 2 completes with the Place entity in 0.5). Transport: the stream follows the user's
transport setting, never downgraded (Q722 = b, Q1014). **Closes when** the lane has run **≥ 72 h on the
reference VM inside its budget** with all twelve editions and the run's own counters are read from one
artifact (rows / day, bytes / day, gap history — the intake's exit row, now with the measured figures replacing
the FROM-MEMORY ones), the toggle and wizard are Chromium-verified + click-through, and the fixture pipeline of
row O carries the stream. `not-measurable-here` for the 72 h run; **operator:** that run. Brief `S04-09`.

### Row Q — Laws: the metadata model, the L0 defects, the first bulk adapters · ruled (R14, R15; Q107, Q901, Q902, Q904–Q910, Q914, Q915, Q917, Q919, Q921–Q924, Q927) · OPEN, the adapter order PENDING

**What it must demonstrate.** The L0 defects first, before anything else in the section (Q917); the internal
model — Akoma-Ntoso-lite: document → versions → provisions with stable addresses + a metadata block, one adapter
per source format, text-only sources filling one provision (Q906); the metadata fields confirmed (Q907:
identifiers ELI / CELEX / ECLI / act number / gazette reference · title ×languages · issuing body · dates ·
status · legal system · jurisdiction alpha-3 + level · language + translation provenance · licence · source
authority + URL · amends / amended-by · topics); point-in-time consolidated versions with `valid_from` /
`valid_to`, an observed snapshot dated by observation and labelled so (Q905); act / code level by default,
per-provision rows where a source arrives pre-split (Q904); **"formally translated" admits official
translations, intergovernmental bodies' translations, and any government's translation of another state's law
— and each translation is its own document with rich metadata, individually tracked for changes, linked to the
other translations and to the original** (Q901 = a, b, c with the note); in scope: constitutions / statutes /
codes, executive instruments, treaties (`INT`); bills and drafts recorded for post-beta (Q902 note); one
document identity with N language versions aligned by identity, no ring needed (Q908); bulk open data first,
then enumeration adapters, then gazette feeds (Q909); account-gated bulk data treated as key-gated and excluded
under V1-2 — EU law through the open per-document API, the Cellar SPARQL endpoint and the weekly public RDF
bulk (Q910); cadence daily / weekly / on-demand within the adaptive per-pass budget (Q915); every law authority
a `Source` row with `source_type="law"` (Q919); `counts_documents` declared per official count (Q921); `[pdf]`
in the default install — 63 of 275 sources are PDF-only (Q922); each source carries `verified: live | fixture |
unverified` with a date, shown in the UI (Q924); the licence recorded per document, shown in the reader, stated
at every export point, a source whose terms forbid redistribution excluded (Q927); analytics 1–2 on the small
corpus — the per-provision diff timeline and amendment velocity per jurisdiction (Q914). **The 44-row vetting
board is run as the 0.4 law operator step** (Q923; `docs/product/LAW_VETTING_BOARD.md`). **PENDING:** the
adapter ORDER and the first managed dataset (Q925 ⛔, blank) — this row builds the adapter framework and feeds it
with the CLML adapter that exists; no second adapter is chosen by the session. Live adapter checks need the
allowlist (row V) or the maintainer's machine. **Closes when** the L0 fixes have tests, a fetched CLML document
round-trips into the model and the reader shows its latest text with the licence line, the vetting-board run's
report exists (operator), and the fixture jurisdiction of row O exercises versions + provisions end-to-end.
Brief `S04-10`.

### Row R — Maps: Equal Earth and the borders · ruled (R13; Q801–Q803, Q826) · OPEN

**What it must demonstrate.** Equal Earth on all five map surfaces through the one `project(lon, lat)` seam
(the current projection is plate carrée at `app-map.js:21–24`, not Mercator), no toggle, named in the legend
("Equal Earth · equal-area") (Q801) — the polynomial's coefficients are FROM MEMORY in the sheet (A₁ 1.340264,
A₂ −0.081106, A₃ 0.000893, A₄ 0.003796) and **must be confirmed against a published source by the building
session** (proj.org was egress-blocked here); Natural Earth 50m now, the OSM-derived admin artifacts replacing
it from 0.5 (Q802); OSM's border convention as of a stated date, every disputed area rendered CONTESTED showing
both claims, the convention named in the legend, **with toggles letting the user see the difference between
conventions, OSM's as the default** (Q803 note); contested borders never a silent pick (Q826); the ooMap
embed on When / Where stays (Q1150). **Closes when** a Chromium click-through record shows the five surfaces
on Equal Earth with the legend, the CONTESTED rendering and the worldview toggle, and the `world_countries.json`
count test still pins the ring inventory. Brief `S04-11`.

### Row S — Sources: admission, identity, the institutions docket, the splice · ruled (Q1101 ⛔ = a, Q1105–Q1112, Q1114–Q1119, Q1156) · OPEN, the embassy platforms PENDING

**What it must demonstrate.** A `qualified` verdict flips `enabled=True` and the `scrape_unqualified` hatch is
retired (Q1101 ⛔ = a — qualification IS the admission gate; the audit view's undo is the safety valve; the
per-pass hardware budget bounds Tor use); the 64,910 `kind_overrides` proposals as a worklist, never
auto-applied (Q1105); the `source_qualification.yml` overlay editor (adopt / export / revert) in Settings
(Q1106); `PATHOLOGY_ABS_FLOOR` kept at 0.5 and recorded unreachable (Q1107); the 6-month re-verification reads
the last 6 months (Q1108); research institutes to `academic_sources.yml` **plus a written strategy to grow that
list comprehensively** (Q1109 = b with the note); `primary_source` deferred-not-rejected and rewritten as an
observable (Q1110); the 16 mis-shelved journals moved (Q1111); a candidate tripping `restricted_namespace`
cannot be spliced without a written override, never a silent drop (Q1112); **THE number = `enabled AND
qualified`** everywhere a headline count is shown, the other predicates labelled (Q1114); a diagnostic proposes
country-vs-domain corrections for review (Q1115); bare QID names resolved at the polite rate or declined
(Q1116); the 116 Czech municipalities admitted, tagged with the vendor path (Q1117); the shortlist (3,031) run
next, the remainder and the religious lists after the splice review (Q1118 — operator / session run); the Stage
B splice admits where both judges agree, defers the ~15 % contested band (Q1119); the stratified round-robin
kept with the singleton strata's order randomised across passes (Q1156). **PENDING:** the compromised embassy
platforms (Q1113 ⛔, blank) — they stay excluded by the existing flag, nothing is published, nobody is
contacted; that is today's state, not a decision. **Closes when** the flip + hatch removal has its data-safety
review and tests, the overlay editor is Chromium-verified, the moves land as catalogue diffs, the splice report
exists with its agree / defer counts, and one headline count on each surface is proven to be `enabled AND
qualified` by a test that reads the shipped predicate. Brief `S04-12`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** Three assumptions land here, each reversible.
**`RC05` → (a): no tool.** The 64,910 `kind_overrides` proposals stay a design-doc measurement and the
worklist Q1105 = a funds is NOT built in `S04-12` — the register's B4 side, taken as §0's later-channel
default; the CONFLICT with Q1105 stays recorded on both rows. **`RC06` → (a): 90 days BESIDE the
whole-history verdict**, never replacing it — two verdicts per source, each with its own n, rather than
Q1108 = a's six months instead of the whole history; the CONFLICT stays recorded. **`RC07` → (b):** B7's
article-revision-tracking note is placed as its own 0.5 slice on the finished row O substrate — a PLACEMENT
assumption only; the feature itself is ruled. B5 and B6 are unaffected. The embassy platforms (Q1113 ⛔)
remain PENDING for their own reason.

### Row T — Network budgets and politeness · ruled (Q1012, Q1013, Q1125, Q1126 ⛔ = a, Q1132, Q1148) · OPEN

**What it must demonstrate.** A per-PROCESS bandwidth budget composed with the collection-speed governor
(`#rate-toggle`), never a second rate authority; per-job caps stay omitted (Q1012 — CLAUDE.md invariant #20
amended 2026-09-15); a per-host next-allowed-at persisted beside the robots cache, an inline wait beyond a few
minutes refused with a named deferral counted as its own bucket, the ride-along and the trial fetch inheriting
both (Q1013 — the 2026-09-10 pending ruling, now ruled); the guarded-route rate limit raised to 1,000 / hour
for loopback UI calls, 100 kept for anything else (Q1148); `#net-coach`'s two actions at equal visual weight
(Q1125); the task-manager airplane title aligned to "every new network request will be refused", re-translated
×12 (Q1126 ⛔ = a — consent copy; the three i18n gates are the bar); model-weight digests pinned in the
external-artifact registry and verified on pull (Q1132). **Closes when** each has a behavioural test (the
deferral bucket appears in the pass summary on a fixture host declaring a long `Crawl-delay`; the budget
composes with the governor in one place), the ×12 strings pass all three i18n gates run separately, and the
net-coach weights are Chromium-verified. Brief `S04-13`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC15` came back blank → **ASSUMPTION (a): L4's
«most ethical» is the app's own loopback guard**, so Q1148's figures stand exactly as this row already states
them (1,000 / hour for loopback UI calls, 100 for anything else) and the per-host egress politeness
(Q1013 = a, the other clause of this row) is NOT re-opened. Nothing in this row changed; the assumption is
recorded so that a later reading of L4 as the egress knob is a reversal rather than a discovery.

### Row U — UI, i18n and the small rulings · ruled (Q1124, Q1130, Q1135, Q1139, Q1141, Q1149, Q1151, Q1152) · OPEN

**What it must demonstrate.** The i18n remainder — 470 strings — keyed ×12 in 0.4 (Q1152), the
`--audit-chrome` ratchet lowered by the measured amount in the same PR; **the religious calendars and the
eclipse canon feature dropped** (Q1135 = b — name the loss in the PR: the 2026-06-17 "you will provide the
dates" ruling is superseded; the agenda's other categories are untouched); the synthetic click-through corpus
gains an encrypted variant (Q1149); `src/api/diagnostics.py` split mechanically into a package, routes
unchanged, proven by a route-table equality test read from the router definitions (Q1139); a full
`docs/FUTURE_DEVELOPMENTS.md` reality check against the tree, stale claims corrected in place (Q1141); the
newsletter attach go-ahead built (Q1151); only the `via:*` provenance prefixes filtered from topical displays
(Q1130); the Patterns lens flips on only when the corpus is ≥ 100 k articles and a labelled sample shows a
false-positive rate ≤ 5 %, both numbers on the toggle (Q1124 — no flip in 0.4 unless measured). **Closes when**
the three i18n gates are green at the lowered numbers, the removal PR names what went, the route-equality
test exists, and the reality-check PR lists every corrected claim. Brief `S04-14`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** Three assumptions land here. **`RC13` → (b): the
religious calendars are NOT dropped** — a dedicated networked session researches the dates from published
calendars and authorities and implements them, dated, sourced, method stated, ×12, nothing fabricated (the
register's G8 side; the CONFLICT with Q1135 = b stays recorded). **The eclipse canon is the half this
assumption does not reach:** `RC13` asks for `+ eclipses` or `− eclipses` after the letter and nothing was
written, so the eclipse canon is neither dropped nor funded and this row no longer reads it as dropped —
that clause of Q1135 = b is UNSTATED pending the letter, and no session may decide it. **`RC17` → (a):** the
coverage-state prefixes (data-gap, thin-coverage, fragmented, …) are filtered from topical displays ALONGSIDE
the `via:*` provenance prefixes, widening Q1130 = a's `via:*`-only clause; the judgement words stay reported
and the CONFLICT with Q1130 stays recorded. **`RC08.6` → (a):** L5's `_SPARSE_BAR_MAX` extension to
`commodityOverlaySvg` only is PLACED in this row; invariant #16 is unchanged. Every other clause of this row
(Q1124, Q1139, Q1141, Q1149, Q1151, Q1152) is untouched.

### Row V — The release ritual and the allowlist · ruled (Q111, Q114 ⛔ = a, Q116) · OPEN

**What it must demonstrate.** Every alpha tag ships with GitHub release notes generated from `shipped.csv` since
the previous tag + the no-telemetry re-check stated in the notes (Q111 — the per-release ritual already in
`CLAUDE.md`); the session environment's egress allowlist gains the hosts named in Q114 (legislation.gov.uk,
eur-lex.europa.eu, gesetze-im-internet.de, laws.e-gov.go.jp, echanges.dila.gouv.fr, dumps.wikimedia.org,
stream.wikimedia.org, *.wikipedia.org, wikidata.org, query.wikidata.org, download.geofabrik.de,
planet.openstreetmap.org, api.worldbank.org, sdmx.oecd.org, api.imf.org, extensions.duckdb.org, proj.org)
(Q114 ⛔ = a — an OPERATOR step in the environment settings, nothing in the tree); three lanes as today
(Q116). **Closes when** the `v0.4.0` release notes carry both items and a session's probe to
`dumps.wikimedia.org` returns an HTTP status rather than `000` (the recorded 2026-09-07 probe shape) — until
then every live-verification step reads `not-measurable-here`. Brief `S04-15`.

**RC round 2026-09-15 — BLANK, so the round's §0 rule applies and nothing here is resolved.** `RC10` ⛔ (does F1's «add them» include
`dumps.wikimedia.org`?) came back blank on a ⛔ question, so it **stays PENDING and is never defaulted**:
that one host is CARVED OUT of the Q114 list above and is not added to the session environment's allowlist.
Every other host in the list stands under Q114 = a / F1. The consequence is unchanged and stated rather than
worked around: PROMPT_06's sense inventory and ambiguity map (slices 4 and 6) stay operator-side, and this
row's closing probe to `dumps.wikimedia.org` still reads `not-measurable-here`.

---

## 3. Amendment log

Every change to a row's status or bar lands here with its date, its source, and what it costs.
The `0.3` gate's own log is the format.

| Date | Change | Source |
|---|---|---|
| 2026-09-07 | Board created from `RELEASE_0.3_GATE.md` §5. Rows A/B/C carried under their existing rulings; D/E/F proposed | session |
| 2026-09-07 | **Row D BUILT** — `GET /api/diagnostics/soak-window` + the `soak-window.json` bundle member. It adds no sampler: it composes the durable readings that already existed and states, per block, the window it actually read. The row stays open because *built* is not *read* — it closes on one report from a run of ≥ 72 h | session |
| 2026-09-09 | **Row F ADVANCED, not closed** — the live visual audit + fix pass closed two of its three open items (the 12-locale sweep is done; honesty rule 9 ran as three adversarial re-verifiers rather than one screenshot re-read). The Gecko/AppVM bar is untouched and every stamp still reads "awaiting human UX pass" | session |
| 2026-09-09 | **Row F ADVANCED again, and the browser bar is now measured at three widths** — the open-queue burn-down swept axe-core at 1440×900, 768×1024 and 390×844 across every main surface, the palette, the analysis window, `/tasks` and all eight Help documents, and closed every finding (the 768 sweep found a CRITICAL that the 1440 sweep could not see: the icon rail hid every nav label from the accessibility tree). Still ONE engine: Chromium only. The Gecko/AppVM bar is untouched, and every stamp still reads "awaiting human UX pass" — a passing axe sweep is a conformance measurement, not a human judging whether the thing is usable | session |
| 2026-09-15 | **Rows D and E become BARS; row F CLOSED as-is** — the answered roadmap sheet, Q117 = a on Q1128 = a: the verification bar is Chromium in the sandbox plus the maintainer's click-through, Gecko best-effort. Every stamp reading "awaiting human UX pass" now closes on the maintainer's click-through of that surface, recorded per surface; no second engine is owed | maintainer (answer sheet, 2026-09-15) |
| 2026-09-16 | **Row U ADVANCED — the `diagnostics.py` split half only (Q1139 = a, J1)**, and the row stays OPEN: `src/api/diagnostics.py` (6,741 lines, 131 routes — recounted at `a962ea1b`; the brief said 6,741/131, the answer sheet 6,200/126) is now `src/api/diagnostics/`, 18 contiguous slices. Behaviour-neutral is MEASURED, not asserted: the 131-route table (path · method · name · endpoint · ORDER) is byte-identical to a snapshot taken from the pre-split module, read from the ROUTER's own definitions, and the manifest's `excluded` block is untouched. The split also found a REGRESSION it would have shipped silently — the runtime coverage report read `pathlib.Path(__file__)`, which after a split is one slice, so it saw 28 of 131 routes and reported `complete` — now fixed and pinned. What row U still owes: the i18n remainder (Q1152), the religious-calendar clause (Q1135, and its RC13 conflict), the encrypted click-through variant (Q1149), the FUTURE_DEVELOPMENTS reality check (Q1141), the newsletter attach (Q1151), `via:*` (Q1130) and the Patterns-lens numbers (Q1124) | session |
| 2026-09-16 | **Row C's E1 clause is VERIFIED-PRESENT, not a build — and the half that was missing is now pinned.** The staleness guard was run before writing any code and the mechanism RC08.3 places here already ships: `month-occupancy.json` is an all-diagnostics member produced automatically at `sample=400` (`src/api/diagnostics.py:4045`), classified in `_DIAG_COVERAGE_MAP` (`:4412`), landed by commit `6e4ca524`, with a test that drives the REAL member generator rather than the route signature. What was NOT pinned was the ruled NUMBER: the guard asserted `isinstance(requested_sample, int)` — satisfied by any int — so 400 was true of the code and asserted by nothing, and PROMPT_06 slice 3 reads this file to decide whether the month-name ban becomes date-aware. Now `== 400`, mutation-checked (sample→41 reddens it by name). No operator run is owed for this clause; row C's own bar (one ~1M-instance bundle reading `complete: true`) is untouched and still operator-gated | session |
| 2026-09-15 | **Rows G–V ADDED** — the sixteen 0.4 slices from the answered sheet (Q105 = a: contents amended, theme kept), each citing its question IDs, each with a brief under `docs/plans/2026-09-12-beta-pathway/`. No target dates (Q110 = c); operator time unbounded (Q115 = c) | maintainer (answer sheet) · rows written by the session |
| 2026-09-15 | **Premise corrections from the brief-writing pass, hand-verified:** `v0.3.0` already exists as a 2026-08-23 pre-release (row G); the `OOS` token lives in the bulletin / evidence / store names (row J); `simplemma` is already in the `[analysis]` extra (row M); the FTS tokenizer already folds diacritics and the `[segmentation]` extra carries `janome`, not `sudachipy` (row N); boot only logs the re-index backlog (row I); `SECURITY.md` also omits `wikidata.org/w/api.php` and `huggingface.co` (row H). No ruling changes; the open details are named for the maintainer | session (briefs S03-01, S04-01, S04-02, S04-03, S04-06, S04-07) |
| 2026-09-15 | **The exit clause written** (§1): rows A–E, G–V closed on named artifacts; the pending ⛔ questions block only the rows that name them | session, from Q110/Q112 |
| 2026-09-15 | **The 2026-09-06 register's 65 answers (rulings artifact, 15:02–16:00Z; recorded in `QUESTIONS_FOR_THE_MAINTAINER.md` in place, `OPEN_QUEUE.md` head entry, `RULINGS_INDEX.md` rows A1–L10) — effects on this board, nothing resolved by the session:** row G — A1 `deferred` (the operator step; `RC01` asks whether the version flip may proceed on the existing pre-release); row K — C1 «a, but wait for version 0.7» CONFLICTS with Q215 = a (⛔, `RC02`; nothing removed meanwhile); row M — B3's method (a seeded stratified sample per batch, furniture words only, open-class refused) recorded; the Q1103/Q1104 CONFLICT stays; row Q — L6 «Promote [pdf] into the default» (pyproject; both venv profiles re-verified; the coverage report's «without [pdf]» wording retired); row S — B5 (the source-qualification export + merge run automated inside the diagnostics), B6 (`high_link_density` as the second, measured criterion beside the kept 0.5), B4 CONFLICT (no tool vs Q1105's worklist surface, `RC05`), B7 window CONFLICT (90 days beside the whole-history verdict vs Q1108's 6 months instead, `RC06`; B7's article-revision-tracking note placed by `RC07`); row T — L4 qualifies Q1148 (`RC15`); row U — G8 CONFLICTS with Q1135 = b (drop vs a dedicated networked session, `RC13`), L10 CONFLICTS with Q1130 on the coverage-state prefixes (`RC17`), L5 proposed here (`RC08.6`), A4's actions (banner + archive, never merge) beside Q1141's depth, L1/L3/L7 consistent; row V — F1 «add them» confirms Q114 = a; E2's host undecided (`RC10` ⛔). | maintainer (the register, 2026-09-15) · reconciled by the session; the confirmation round is `docs/design/RULINGS_CONFIRMATION_2026-09-15_REGISTER_ROUND.md` |
| 2026-09-15 | **The RC confirmation round came back UNANSWERED — 0 of 22 `ANSWER` lines carry a letter — processed per its own §0; nothing resolved by the session.** Effects on this board, all reversible by writing a letter: row G — `RC01` ASSUMPTION (b), the flip keeps waiting on 0.3 row 5; row K — `RC02` ⛔ PENDING, the legacy restore half untouched; row S — `RC05` ASSUMPTION (a) no tool, `RC06` ASSUMPTION (a) 90 days beside the whole-history verdict, `RC07` ASSUMPTION (b) article revision tracking to its own 0.5 slice; row T — `RC15` ASSUMPTION (a), Q1148's figures stand; row U — `RC13` ASSUMPTION (b) the religious dates get a networked session **and the ECLIPSE CANON is left UNSTATED** (the `± eclipses` suffix was not written, so this row no longer reads it as dropped), `RC17` ASSUMPTION (a) the coverage-state prefixes filtered too, `RC08.6` ASSUMPTION (a) L5 placed here; row V — `RC10` ⛔ PENDING, `dumps.wikimedia.org` carved out of the Q114 allowlist. Eight of the assumptions sit on CONFLICT questions and follow the later channel exactly as §0 directs; BOTH answers stay recorded on their `A1`–`L10` and `Qnnn` rows. **No row changed status.** | maintainer (the round, left blank) · §0's blank rules applied by the session |
| 2026-09-15 | **The 0.4 board re-verified against the tree at today's `main` (`0d6e4708`): rows G–V, every §2 staleness anchor of all sixteen briefs re-run by grep, never from memory. 127 anchors; 126 live; ONE wrong.** The one: brief `S03-01` (row G) cites `docs/product/RELEASE_0.3_GATE.md:33` for the 0.3 board's row 5 — `:33` is row **6** (the DB-10 page-size bench, CLOSED 2026-08-13); row 5 is at **`:32`**. The text the brief quotes («**OPEN** — criteria **agreed 2026-08-23**; the pass has not been run») is row 5's, verbatim and still exact, and the 0.3 gate has not changed since the briefs were written — `git diff bebcef4..origin/main` on that file is EMPTY and row 5 sat at `:32` at `bebcef4` too, so **the anchor did not drift: it was mis-cited when written**. Corrected in the brief in this PR. **No ruling changes and no row changes status** — row G still waits on row 5 (`RC01`'s assumption), and row G's own 2026-09-15 premise check about the existing `v0.3.0` pre-release is re-confirmed unchanged. The other 126 anchors were checked against the claim each brief quotes beside them rather than against the nearest identifier: an earlier, looser pass flagged eleven and **nine of those were the checker's own false positives** (it matched a neighbouring backticked name instead of the brief's claim), hand-re-verified one by one before anything was recorded — `folder_backup.py:48`, `artifact.py:48`/`:650`, `main.py:1450–1455`, `source_tags.py:441`, `models.py:786`, `runner.py:744–761`, `fts.py:254`, `qualification.py:230` and `calendar_feeds.yml:3288` are all exact. | session (grep-verified at `0d6e4708`) |
| 2026-09-15 | **Row G re-checked and NOT flipped — the version stays `0.3.0`.** The session that shipped row V's generator re-read the two rulings row G turns on rather than inheriting them from a brief: `A1` reads `deferred` (the operator step — the Tier-A quarantine run with `include_prose_gate=false`, the re-index, the count under `nav-soup-v2`, the `v0.3.0` tag — deferred by the maintainer, no date, Q110 = c), and `RC01` came back BLANK on a round whose §0 turns a blank non-⛔ into a labelled ASSUMPTION at the stated default, which here is **(b): keep waiting on 0.3 row 5**. So the flip's precondition is unmet and nothing of `S03-01` was built — not `pyproject.toml`, not the README `**Version:**` line or its stale "latest tagged release: `v0.2.0`" note, not `docs/CHANGES.md`, not the 0.3 gate's §1/§3 tag record. **What this row waits on is the operator, in this order:** (1) their word on whether the 2026-08-23 `v0.3.0` pre-release at `917e8095` IS the 0.3 close (it is a LIGHTWEIGHT tag where §7.3 prescribed annotated, and it was cut BEFORE row 5 was run — a session never moves, deletes or re-cuts a tag); (2) 0.3 row 5's four `curl` calls from their machine; (3) the flip PR. Reversed the moment a letter is written at `ANSWER RC01` — `a` would let the flip proceed on the existing pre-release. | session (rulings re-read at `338dc868`, nothing decided) |
| 2026-09-15 | **Row V PART-SHIPPED: the release-notes generator exists and the workflow calls it.** `scripts/release_notes.py` (Q111 = a) reads `docs/ledger/shipped.csv` in BINARY, resolves the previous `v*` tag, groups the rows and emits Markdown in which every line traces to a row. It REFUSES rather than degrading on: a dirty tree, a clone still shallow after one `--unshallow` (rule 5b), an unswept `PR pending` in a row it would CITE (column-aware, because a whole-file grep matches the ledger row that records the phrase's own removal), an `_ALLOWED_SOCKET_IMPORTERS` shape its AST reader cannot parse, and a missing verification-bar marker. `.github/workflows/release.yml` gains `fetch-depth: 0` on the release checkout, a dev install, and a `python scripts/release_notes.py` call before the fixed install / SHA-256 heredoc — the `v*` trigger, the 0.x pre-release rule, the tag-vs-`pyproject` refusal and the idempotent create/upload/edit path are untouched and pinned by test. 37 guards in `tests/test_release_notes_generator.py`; 21 mutations, 21 killed (two survived the first matrix: one was a finding about the MUTANT, one about a test whose `…` needle was satisfied by the disclosure sentence that quotes it). **Remaining on row V:** the allowlist (operator, Q114 = a with `dumps.wikimedia.org` carved out by `RC10` ⛔), and the per-surface click-through records the notes cite — the generator has none to read and says so rather than listing any. | session |
| 2026-09-15 | **Rows D and E driven END TO END at fixture scale; both stay OPEN on their operator runs.** A 440-article synthetic corpus seeded through the real `index_article`, served on loopback, and both reports read from their endpoints AND out of the one 73-member `/api/diagnostics/all` archive. **Row D:** four of six blocks measured (`window`, `write_gate`, `interrupted`, and `database_stats_latency` once the route is called); `memory_guard` and `wal` report `measured: false` WITH a reason and appear in `unmeasured`. What they need is elapsed time on the operator's machine — the 300 s rate floor and the at-most-hourly `wal_bytes` recorder — and only row B's ≥ 72 h run can make `window.reaches_bar` true. **Row E:** driven in BOTH directions — a clean corpus answers `consistent` over `with_judging_attempt: 14` of 18 sources with the one disqualified source named, and a seeded 2026-07-24-shaped laundering answers `inversions-found` naming `prefcentre.example` with its live status, its last judged verdict and the date, arriving intact in the archive member. So the TOOLING states its own result today; what it needs from row A is the committed IMPORT, which it cannot supply. Neither row's status changes: *built and exercised* is not *read from a run*. | session (fixture-scale drive, Chromium not required — JSON artifacts) |
| 2026-09-15 | **The verification bar (Q1128 = a) now has ONE citable home** — a marked block in row F's section, which `scripts/release_notes.py` READS rather than mirrors, so a reword reaches the release notes with no second edit and a deleted marker is a loud refusal. `_WORKING_MODE.md` §3 already carried the same sentence verbatim and is unchanged; a test pins the two against each other, because a drift between what a BUILDING session is told and what a RELEASE claims is how a surface gets stamped against a bar the release does not make. Row F's status is unchanged: CLOSED as-is. | session |
| 2026-09-16 | **Row H BUILT in two PRs, and the sweep that built it found three defects.** The enumeration is now a fourteen-lane table derived from the tree (PR #1135, docs-only per Q1001's "now"); the consent hover reads the same hosts out of ONE table, `src/static/net-hosts.js`, which `tests/test_security_endpoint_enumeration.py` pins against the document in both directions. **Hosts the section had never named:** `query.wikidata.org`, `www.wikidata.org`, the per-edition `*.wikipedia.org` API, `ores.wikimedia.org`, `dumps.wikimedia.org`, `download.geofabrik.de`, `planet.openstreetmap.org`, 260 law-authority hosts, four markets-feed hosts, fourteen calendar-feed hosts, `huggingface.co`, `pypi.org`, `objects.githubusercontent.com` and the operator-added mirror class. **Three findings, all disclosed and none fixed here:** (1) the section claimed ONE automatic opt-out exception; six ride-alongs run on every online pass. (2) `auto_import_calendars` and `auto_track_law` are read via `getattr(…, True)` against a `SchedulerSettings` that defines neither, so they cannot be switched off. (3) worse — `auto_track_signals` IS a field and IS honoured, but `SchedulerConfigUpdate` does not declare it, so `PUT /api/scheduler/config` answers **200 having changed nothing** (live-reproduced); this document and CLAUDE.md invariant #14 have both named that route as the hazard feeds' opt-out for months. The fix is settings-API and UI work outside `S04-01`'s stated file scope and wants a ruling on its home (row T is the natural one) — recorded in `OPEN_QUEUE.md`. **Also measured:** a URL-literal sweep is blind to `configs/markets_sources.yml`'s 112 scheme-less `domain:` sources, which `crawl.py:149` reaches at `https://<domain>`; counting both halves takes the press class from 5,425 hosts to 9,033. **What remains on this row:** the maintainer's own click-through (Q1128 = a) and their word on the lane grouping names (a design note, binding nobody). | session (Chromium-verified in the sandbox; the operator pass is theirs) |

---

## 4. Not in this gate

Kept explicit so nothing drifts in by assumption:

- **The `v0.3.0` tag.** It is the `0.3` gate's §7.3, and this board does not gate it.
- **The version flip to `0.4.0`.** It follows the `v0.3.0` tag, mechanically.
- **The 5M-article framing.** Withdrawn 2026-07-30 and not reinstated here; it returns as a
  later-cycle target once the throughput work makes it reachable.
- **Everything the answers put in `0.5` or later** (see `RELEASE_0.5_GATE.md` … `RELEASE_0.9_GATE.md`):
  the advanced search (R11), the storage half of alpha-3 (Q301 = c step 2, Q304, Q305), the entity spine
  and the Place entity, the OSM lane seed and its admin artifacts, the Wikipedia WARM tier and the tail
  walk (Q701 = c), the law evolution surface, the feed-key source identity migration (Q1102, *proposed
  placement* 0.5), the inline-handler retirement + CSP and the theme cull (Q1127, Q1123), the AI
  translation sweep (Q405, Q513).
- **The four ⛔ questions left blank** — Q823 (ODbL), Q925 (adapter order), Q1009 (storage round-2 rows
  3–6), Q1113 (the embassy platforms) — are not decided here and not defaulted anywhere.
- **The stoplist merge** (Q1103 = b vs Q1104 = a, a CONFLICT recorded 2026-09-15) — held until the
  maintainer picks; row M ships without it.
- **Row 5's Tier B** (the 451 index pages above the word guard). Not proposed for `0.3` and not
  proposed here: their prose is unmeasured. The `0.3` PR made that measurable
  (`criteria-calibration.json`'s prose arm now advances and can be pointed at that population),
  so a `0.4` decision on Tier B would at least have evidence — but it is a decision, and nobody
  has made it.
