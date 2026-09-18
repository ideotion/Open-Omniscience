# The Wikipedia lane's ≥ 72 h run — the operator's half of gate row P

**Audience:** the operator, on the reference VM (2 cores / 3.5 GB), with a networked
machine. **Companion:** [`UNATTENDED_RUN_RUNBOOK.md`](UNATTENDED_RUN_RUNBOOK.md) for
leaving a machine working, and [`RELEASE_0.4_GATE.md`](RELEASE_0.4_GATE.md) row P.

`S04-09`'s operator step 1, in full: *"Run the lane ≥ 72 h on the reference VM inside
its budget with all twelve editions; read its OWN counters from ONE artifact (rows /
day, bytes / day, gap history), written where the soak bundle reads; quote it in the
PR; the measured figures replace the sheet's FROM MEMORY ones in the ledger."*

---

## 0. Why this cannot be run from the build sandbox

Every Wikimedia host answers `000` from it (probed 2026-09-17; `api.github.com`
answers `200` as the control). So the whole lane is proven here against a **recorded
fixture stream** under the airplane socket guard, with **zero name resolutions** —
which proves the pipeline and proves nothing about Wikimedia's live behaviour. The
scale figures the answer sheet carries (enwiki ≈ 80–160 k edits/day, "the other eleven
together are of the same order", 250–300 k rows/day, EventStreams retention "7 days by
default; the service can extend to 31") are **FROM MEMORY** and are what this run
replaces with measurements.

## 1. Before you start

1. **Set the lane up.** Settings → Wikipedia → *Editions and storage budget…*, or the
   first-run wizard on a fresh corpus. Leave the defaults to reproduce the reference
   configuration: **all twelve editions, 20 GB total** (Q707's published default).
2. **Check the disk.** 20 GB for the lane, plus room for the corpus the HOT tier feeds.
   The lane lives in `wiki.db` beside `corpus.db`, and it is encrypted alike.
3. **Note the start time.** `GET /api/wiki/lane/counters` reads a 7-day window, so a
   72-hour run sits inside it with room at both ends — but the window is measured from
   *now*, so read it before it has slid past your start.
4. **Decide about the scoring endpoint.** ORES is opt-in and off unless you asked for
   it. If you turn it on, see §5 — this run is the chance to answer Q717.

## 2. Starting it

The lane starts when you **go online**, and only then: the app boots into airplane mode
and makes zero calls, so the top-bar airplane button (or any consented action that
crosses online) is what starts collection — the same one consent popup as everything
else. The Wikipedia toggle beside it stops, halts and resumes the lane itself:

| control | what it does |
|---|---|
| click the Wikipedia toggle | **halt** ↔ **resume** — the connection closes, the cursor is kept, and a resume continues from the stored `Last-Event-ID` |
| shift-click it | **stop** — nothing reconnects. The cursor still survives; what you give up is the PROMISE that a later start finds it inside EventStreams' retention |
| the airplane button | stops the lane with everything else |

**Leave it running for at least 72 hours.** A restart in the middle is fine and is worth
doing at least once: every counter below is computed from stored rows rather than from a
process counter, precisely so a restart does not erase the run.

## 3. What to read, and where

**ONE artifact**, two doors onto it — both call the same function, so they cannot drift:

- `GET /api/diagnostics/soak-window` → the `wiki_lane` block (this is the one the soak
  bundle collects, and the one row D reads);
- `GET /api/wiki/lane/counters?window_days=7` → the same figures on their own.

### The counters the diagnostics member must show

| block | what it is | what an absence means |
|---|---|---|
| `rows_per_day` | `versioned_changes` per day, counted by the day **this app recorded them** — not the day the edit happened, because a resumed stream replays yesterday and that would report a quiet day you in fact spent working | `measured: false` = the whole window is empty. A single day at `0` inside a measured window is a real zero |
| `bytes_per_day` | growth between the first and last **file size samples** in the window (`stat` + `-wal`/`-shm`), sampled at most hourly | `measured: false` with a reason = fewer than two samples. **A rate needs two readings; one reading is not a small rate** |
| `gaps` | every gap the lane PUBLISHED, newest first, with its reason (`retention` · `disconnect` · `budget` · `refused`) | never a percentage: a lane cannot know how much it missed, only that it missed a named stretch |
| `entities` | pages followed, grouped by **why** each was admitted (`pinned` · `tracked` · `corpus_mention` · `pageview_top`), plus how many the source has marked deleted | `unrecorded` means the row predates the column, not that no rule applied |
| `file_bytes` | the lane file on disk, sidecars included | `null` = the lane has never run. **That is not zero** |

Read `GET /api/wiki/lane/status` too — it carries the Home strip's own figure (pages
followed, changes today) and is the number Q714 keeps separate from your article count.

### And the two figures that are NOT the same number

`bytes_per_day` is the **file on disk**. The per-edition figures elsewhere are
**uncompressed text bytes** summed from rows. On a compressed lane the second is a
multiple of the first; neither is derived from the other, and each carries its method.

## 4. What to quote back

1. **rows / day**, overall and per edition — against the sheet's 250–300 k/day.
2. **bytes / day**, and the lane file's size at the end — against the 20 GB budget.
3. **The gap history** — every gap, with its reason. A `retention` gap is the one worth
   arguing about: it means the stream's retention is shorter than your outage.
4. **Whether the budget was reached**, and what the app did when it was: text stops and
   says so, metadata keeps flowing (Q108's whole point). If yours behaved otherwise,
   that is a finding.
5. **The editions that collected nothing** — a zero for a quiet edition and a zero for a
   broken one look identical in a count, and the gap rows are what tell them apart.

## 5. The two things only a networked machine can confirm

- **EventStreams' retention.** FROM MEMORY: "7 days by default; the service can extend
  to 31." The way to measure it: halt the lane, wait past the suspected boundary, resume,
  and read whether the lane published a `retention` gap. Quote the wait and the answer.
- **The scoring endpoint (Q717).** Wikimedia announced a migration from ORES to Lift
  Wing; this app has **not** confirmed whether the v3 path still answers. Turn ORES on
  and watch the log: a `404`/`410` is reported as `endpoint_gone` with a warning naming
  the migration. Either outcome is the answer the ruling asks for, and neither was
  guessed at from here.

## 6. What this run does not close

The maintainer's own click-through (Q1128's human half), the Living sources view
(S04-08's, and Q728's other half depends on it), and the WARM/COLD tiers and tail walk
(0.5). None of those are blocked on this run; they are simply not what it measures.
