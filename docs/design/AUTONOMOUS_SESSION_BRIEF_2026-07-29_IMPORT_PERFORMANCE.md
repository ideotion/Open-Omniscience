# Autonomous session brief — backup-import performance + the multi-import UI (2026-07-29)

**Status:** PLANNING ONLY. Nothing in this brief has been built. It is the operating manual for
one autonomous Claude Code session (the maintainer will run it with **Opus 5 + ultracode**, so
subagent fan-outs and adversarial verification are expected, not optional).

**Origin.** Maintainer field report 2026-07-29, two remarks: (1) importing a 50,000-article backup
showed a *4000-minute* re-index estimate, and collecting while importing slowed the import by a
further 3–5×; (2) importing a folder of six backups shows one shared progress bar with no per-item
identity, no true rate, no pause, no stop. Twenty follow-up questions were put and answered the
same day; §2 records the rulings verbatim in substance.

**Evidence base.** Every claim below carries a `file:line` anchor read during a 10-agent read-only
fan-out (7 recon + 3 adversarial skeptics, 0 errors). Where an agent could not verify something it
is marked UNVERIFIED and the brief says so rather than guessing. Two findings **refuted** the
premises this session started with — see §3 and §4. That is the point of the exercise: do not
re-derive them, and do not skip the re-decision in §3.

---

## 0. Working mode (read every session, non-negotiable)

- **Draft PRs only.** Nothing self-merges. The maintainer's review is the gate.
- **Staleness guard FIRST.** This area moved a lot in the last two weeks (Session A §4 "import
  owns the machine", C13 bulk mention insert, the corpus-delta view). Before building any slice,
  re-verify its anchors against the tree. Several items in the older ledger prose are already
  shipped; do not rebuild them.
- **Reproducer-first for every claimed defect.** §4 in particular is a *read-verified but not
  reproduced* bug. Reproduce it, then fix it, then keep the reproducer as the test.
- **Skeptics complete before `git push`,** with the negative-space lens mandatory on S5, S7 and S9
  (the data-safety-relevant slices). "Draft PR" is not a review gate in this repo.
- **CI gates (all blocking):** `ruff check --select=F,B --extend-ignore=B008` · `mypy` ratchet
  ≤ 127 · `bandit==1.9.4 -r src/ -ll -q` · `python scripts/i18n_report.py --min 100` ·
  full `pytest -q` on py3.13 · `node --check` on every edited `<script>` block.
- **i18n trap, inverted from the usual assumption** (`scripts/i18n_report.py:167-186`): the
  blocking `--min 100` gate reads *only* the locale JSONs. A new `t("…")` with no locale entry is
  gate-safe; what reddens CI is adding a key to `en.json` **alone**. New keys must land in all 12
  locale files in the same commit.
- **Frontend is browser-unverified here** (no browser in-session, per fork-3): ship conservative,
  extend the invariant tests, and flag every UI slice "browser-unverified, needs click-through".

---

## 1. What the field report actually is (root causes, ranked)

### 1.1 The dominant cost: an uncached per-term keyword lookup

`_get_or_create_keyword` runs `session.query(Keyword).filter_by(normalized_term=…).first()` for
**every kept term of every article** (`src/analytics/store.py:72`, called at `:331`). Verified: this
is always a real DB round-trip — SQLAlchemy's identity map short-circuits primary-key lookups only,
and `SessionLocal` is `autoflush=False` (`src/database/session.py:149`), so no flush-then-cache
effect masks it. At roughly 200 kept terms per article × 50,000 articles that is ~10 million
individual index probes through the SQLCipher codec, against a keywords table that on the
maintainer's largest machine holds ~6.9M rows.

**Not yet measured.** The mechanism is verified; the *share* of wall time it accounts for is not.
S2 exists to measure it before S7 claims a speedup.

### 1.2 The restore re-indexes with one fsync per article

`volume_job.py:269-278` passes `reindex_workers` and `merge_cache_mb` but **never passes
`reindex_commit_batch`**, so `merge.py:1737` falls back to `OO_REINDEX_COMMIT_BATCH`, whose default
is `"1"` (`merge.py:1664`) — one commit per article. Against the documented WAL-starvation finding
(single-row commits measured 2–11 s average, peaks to 341 s, on all 7 field machines) this alone
could dominate.

### 1.3 The 4000-minute figure is itself inflated — a real ETA bug

`_uxPoll` captures `startMs` **once for the whole job** (`app.js:5753`) while `view.frac` resets to
~0 when the phase flips from merging to re-indexing (`app.js:5729-5740`). `_uxRuleOfThree`
(`app.js:5669`) therefore computes
`(verify + reassemble + merge + re-index-so-far) × (1−f)/f` instead of
`re-index-so-far × (1−f)/f`. Early in the re-index (`f` just past the 3% floor) that overstates by
roughly the ratio of total elapsed to re-index elapsed — easily 5–15×. The real number is still
bad; it is not 4000 minutes.

### 1.4 The "import owns the machine" pause is real but bounded and leaky

`pause_for_exclusive_operation()` is wired on the volume path (`volume_job.py:208`) and correctly
also claims `hold_exclusive()` so a manual "Run now" cannot slip through. But its own docstring
(`scheduler/runner.py:1915-1927`) states `_do_run` **has no internal stop-check mid-pass** — only
between passes. `stop(timeout=10)` therefore returns while a pass already inside a fetch keeps
running to completion, which over Tor is easily 30+ minutes of full contention. Worse for the
maintainer's case: `_uxImRun`'s per-backup loop means `resume_after_exclusive_operation` **restarts
collection between every backup** (`volume_job.py:284-290` runs in a `finally` per restore), so a
6-backup run re-opens the race five times.

### 1.5 No engine-fingerprint skip

`merge_batches` already carries `app_version` and `alembic_rev` from the verified manifest
(`models.py:2159-2160`), and `merged_rows` records only genuinely-new rows via a rowid watermark
(`merge.py:240-243`), so no work is wasted on duplicates. But nothing compares engines, so importing
a backup produced by *the same build* pays a full re-index to recompute byte-identical values.

### 1.6 The multi-import UI, confirmed point by point

- `_uxImRun` (`app.js:6111-6190`) is a **client-side sequential loop** over four kinds, all writing
  into the **same** `#ux-imp-bar` and `#ux-imp-progress`, distinguished only by a constant text
  prefix (`t("Corpus")` at `:6146`). No index, no folder name, no per-item bar.
- **Pause and stop do not exist for imports.** `_run_restore` (`volume_job.py:182-304`) never reads
  `self._stop` — only `_run_backup` does (`:126`). `pause()`/`cancel()` set flags the restore
  ignores; `/v2/volumes/cancel` is build-only. Any pause button today would be fabricated capability.
- Reload kills the sequencing — the code says so at `app.js:6196`.
- Dialog sizing is inline (`index.html:1641`, `max-width:560px`); `app.css` contains **zero**
  `dialog` rules, so widening means editing that attribute or introducing the first dialog rule.
- Ten ids and several function names are pinned by tests, including a **literal source-substring**
  anchor at `tests/test_unified_backup_ui.py:246` — the project's own recorded stale-anchor hazard.
  Any rename updates those tests in the same commit.

---

## 2. The rulings (maintainer, 2026-07-29)

1. **Defer the re-index off the blocking import path** — yes.
2. **The re-index is autonomous and visible**, integrated in the backup UI **as the last backup
   stage** with its own progress. **Articles not yet re-indexed must not be part of analytics.**
   *(This ruling's premise was refuted — see §3. It needs one re-decision before building.)*
3. **Extraction fingerprint in the manifest**; a match skips the re-index — yes.
4. **A mismatch means a full re-index** — no partial/heuristic path.
5. **Keyword cache: decision deferred to the risk memo** — see §5, which recommends a narrowed GO.
6. **Extend the cache to the collector ingest path** — yes (sequenced after the re-index path).
7. **`commit_batch` ≈ 200 when the import owns the machine**, 1 otherwise — approved.
8. **WAL/checkpoint state is not a user-facing surface**; it belongs in all-diagnostics.
   *(Already largely built — see §6.)*
9. **Collector stop must be immediate.**
10. **Collection does not resume between backups** — a multi-backup run is ONE import.
11. **Legacy single-file imports are being removed soon** — do not invest in them; the removal is
    recorded in `docs/FUTURE_DEVELOPMENTS.md`.
12. **The UI states that collection is paused for the import.**
13. **Server-side import queue confirmed** — and it does not replace the UI changes in remark 2.
14. **Rate display:** the honest unit for the current phase, plus a cumulative line.
15. **Stop/abort is immediate, losing the current import and everything related to it.**
    *(Achievable pre-swap; post-swap there is no undo — see §7.)*
16. **A "Show details" panel, persisting across a reload** — yes to both.
17. **Per-phase ETA, and the number of remaining phases visible.**
18. **Do the quick wins and the architecture** — both.
19. **Add the instrumentation** — data-driven decisions.
20. The session runs on Opus 5 with ultracode.

---

## 3. ⚠ THE ONE RE-DECISION — ruling 2's premise was refuted

**Do not implement ruling 2 as a per-article "pending" flag. Two independent agents concluded it
would be both dishonest and expensive, and the fact it rests on is wrong.**

**The refutation.** Merged articles are **already fully present in analytics before any re-index**:
`_merge_keyword_mentions` copies the incoming corpus's `keyword_mentions` rows straight into the
live DB during the merge (`merge.py:693`, `:726`). The post-merge re-index is a **refresh** that
overwrites those rows with current-engine output (`store.py:479-480`), not an admission gate. So
"exclude until re-indexed" would not withhold *unanalysed* articles — it would delete an entire
imported corpus from analytics to fix bounded engine-version staleness. Imported corpora skew old,
so that is a direct hit on the cross-time-recall non-negotiable.

**Why the flag is also expensive and would be applied inconsistently:**

- The hot corpus-wide `top_terms` reads **only** the denormalised counters and never touches
  `Article` at all (`queries.py:300-317`) — a per-article flag has nothing to filter on there.
- **Fifteen** further analytics paths aggregate `keyword_mentions` without joining `Article`
  (`queries.py:334`, `:254`, `:1340`, `:1763`, `:1967`, `:1005`, `:436`, `:2238`, `:2325`;
  `columnar.py:802`; `rollup_serve.py`; `briefing/producers.py:494`). Adding that join is the
  documented SQLCipher codec trap (`queries.py:1941-1946`), worst in the columnar builder which
  streams every mention row.
- The precedent proves the divergence risk empirically: `Article.quarantined` appears in **zero**
  analytics files, and already produces two disagreeing corpus totals (`main.py:951` vs
  `queries.py:2191`, the latter's own docstring claiming "REAL, EXACT").
- If the re-index never finishes, a marker strands an arbitrary subset **permanently invisible** —
  `reindex_articles` returns aggregate counts only and stamps no per-article completion
  (`store.py:506`). That converts today's graceful degradation into silent data loss.

### The recommended way to satisfy the ruling instead: **don't merge the derived rows**

Stop copying the incoming `keyword_mentions` (and the sibling derived tables) during the merge, and
let the post-import re-index **produce** them. "Not yet re-indexed" then means "has no mentions",
which every analytics path already honours **structurally** — no gate, no flag, no join, no
fifteen-path sweep, no codec trap, no rollup problem. It is localised to the merge step tuple
(`merge.py:315-330`).

**Hand-re-verified** (per the standing "agent findings get hand-re-verified before shipping" rule),
the five load-bearing claims of this section were each read directly by the authoring session:
`_merge_keyword_mentions`' `INSERT OR IGNORE INTO keyword_mentions … SELECT … FROM inc.keyword_mentions`
(`merge.py:726-731`); `_merge_keywords`' INSERT column list, which carries
`term, normalized_term, language, frequency, category_id, is_ngram, ngram_size, is_entity,
entity_type, relevance_score, extractor, created_at, updated_at` and **no counter columns**, under a
`WHERE NOT EXISTS` that never updates an existing keyword (`merge.py:629-644`); the absence of
`unique=True` on `Index("idx_keyword_normalized_term", …)` (`models.py:934`); `top_terms`'
counter-only corpus-wide branch (`queries.py:311-318`); and `old_contrib` being read from the live
`KeywordMention` rows (`store.py:295-301`).

**A bonus the verification surfaced, which decides the hot path in design B's favour.** The
corpus-wide `top_terms` filters `Keyword.mention_count > 0`, and its own comment states this
"reproduces the inner-join's *has mentions* filter (a counter is 0 iff the keyword has no
mentions)" (`queries.py:311-318`). Under design B, keywords merged without their mentions land at
the server default 0 and are therefore **already excluded from the hot path with no new code at
all** — the exact query a per-article flag could not gate, because it never touches `Article`. This
is the strongest single argument that design B is the honest implementation of ruling 2 rather than
a workaround for it.

It is also the right answer for remark 1, three times over:

- The merge stops writing the single largest table (~10M rows for a 50k-article backup).
- The re-index stops doing delete-then-reinsert against rows it is about to replace.
- **It fixes the counter-drift bug in §4 by construction** — with no merged mentions present,
  `old_contrib` reads empty and the re-index's counter deltas become correct.

**Its honest cost, which must be stated in the UI and the docs:** between merge and re-index an
imported article has *no* keywords rather than *stale* keywords. That is only acceptable with a
hard requirement:

> **S5 must ship a durable per-article re-index cursor.** An aborted, crashed or stopped re-index
> must resume exactly where it left off and must surface its own backlog at boot. Without that,
> design B trades a bounded staleness for an unbounded invisibility, and the skeptic's objection
> stands.

**Maintainer decision needed before S5 is built** (state it in the PR, do not assume):

- **(a) RECOMMENDED** — don't merge derived rows; re-index produces them; resumable cursor +
  disclosure. Satisfies ruling 2, speeds up the import, fixes the counters.
- **(b)** Keep merging derived rows and **decline** the exclusion; disclose pending refreshes from
  `merged_rows` instead ("N imported articles still carry their source engine's keywords"). This is
  what the skeptic recommends on cross-time-recall grounds. Smallest change; no import speedup.
- **(c)** The per-article flag as originally framed — **not recommended**; the brief documents why.

---

## 4. ⚠ A probable real bug found while attacking §3 — reproduce it first

**Claim (read-verified, NOT reproduced):** keyword counters never absorb a merged corpus.

- `_merge_keywords`' INSERT column list omits `mention_count`/`article_count`, so new keywords land
  at server default 0; existing keywords are matched by `NOT EXISTS` and never updated
  (`merge.py:631`).
- No `backfill_keyword_counters` call exists anywhere in the restore path — its only caller in the
  tree is `src/ingest/email.py:756`.
- `merge.py:2025-2027` explicitly reconciles `Source.article_count` for exactly this reason
  ("a wrong count shown as exact") and does **not** do the same for keyword counters.
- At re-index, `old_contrib` is read from the **live** mention rows — which after a merge *are* the
  imported rows (`store.py:294-301`) — so the delta is ≈0 and the re-index **subtracts a
  contribution that was never added**.

`maybe_reconcile_counters` in off-peak idle maintenance would eventually repair it
(`scheduler/maintenance.py:83`), but it requires the app to be **online with the collector idle** —
so an airplane-first user who imports and browses offline sits on drifted counters indefinitely,
undisclosed.

**Slice S4:** merge a small backup on a scratch corpus, compare `Keyword.mention_count` against the
live `GROUP BY` before and after the re-index, and only then fix it (an explicit reconcile at the
end of `run_restore`, mirroring the `Source` one three lines away, and also on the skipped/aborted
re-index paths). Keep the parity assertion as the regression test. Note design B in §3 makes this
correct by construction — but the fix is still owed for the `reindex_imported=False` path and for
corpora already imported.

---

## 5. Answer to ruling 5 — the keyword-cache risk, and a narrowed GO

The adversarial pass **could not find the naive proposal safe**, and the decisive break is a
documented contract, not a subtle race. Three deterministic holes (no timing luck required):

1. **Stale ids survive rollback.** Rollback-then-redo fallbacks re-enter `index_article`
   (`store.py:597`, `:613`, `:639`, `:576`; `batch.py:260`; `pipeline.py:282`). A cache that
   survives the rollback hands the redo ids for rows the rollback destroyed. Foreign keys are ON
   (`session.py:101`) with a real FK (`models.py:1752`), so the bulk mention insert raises
   `IntegrityError` — which `is_locked_error` deliberately never retries (`write.py:95`). The redo
   reuses the poisoned cache, so every batch-mate sharing that term fails too, destroying the
   no-loss guarantee `_redo_committed` exists to provide.
2. **The savepoint variant is silent.** `batch.py:353-369` wraps all of `index_article` in
   `begin_nested()` and swallows non-lock errors. Poisoning happens with only a warning log, then
   every later article containing that term loses its indexing quietly.
3. **It violates `run_write_with_retry`'s stated contract** (`write.py:20`): the work "must
   re-query whatever state it needs". Three call sites wrap `index_article` in it.

Plus, structurally: **there is no UNIQUE index on `keywords.normalized_term`** (`models.py:934`;
baseline migration `unique=False`; `merge.py:614-617` calls the absence *deliberate*). So a cache
bug produces a **silent duplicate row**, not an `IntegrityError` — and the standard
`except IntegrityError: re-SELECT` recovery idiom **cannot fire here**. Duplicates already exist in
the wild (the merge's natural key is `(normalized_term, language)`, wider than the lookup's), and
`.first()` has no `ORDER BY`.

Two more that any implementation must handle: the **entity-upgrade branch mutates an existing row**
(`store.py:93-97`) — an id-only cache silently kills every upgrade with nothing failing loudly —
and one `IN (…)` over a window's terms blows SQLite's ~999 variable ceiling.

### Recommendation: GO, but only in this narrowed form

**Warm the READ side only. Leave the create path exactly as it is.**

- A **bulk `SELECT id, normalized_term, is_entity, entity_type … WHERE normalized_term IN (…)`**,
  chunked to ≤ 900 parameters, warms a dict before a window is applied.
- **Misses still go through the existing per-term `session.add` + `session.flush()`** path. That
  keeps `baseline_tags` (`:88-92`), first-write-wins `language` (`:78`), and the load-bearing flush
  (`:87`) byte-identical, and avoids the bulk-create id-recovery problem entirely. On a re-index
  nearly every term already exists, so the read side is essentially the whole win.
- The cache stores **`(id, is_entity)`**, and the entity-upgrade branch updates its own copy.
- **Transaction-scoped, invalidated on rollback** — registered on `after_rollback` *and* on nested
  rollback. `writer.py:275`'s parent-is-None discrimination must **not** be copied here.
  **Empirically probe first** whether SQLAlchemy fires those events for SAVEPOINT rollbacks; the
  recon flagged this as unverified and it is the hinge of the whole guard.
- **Deterministic tie-break** on duplicate `normalized_term` (`MIN(id)`, matching `merge.py:638`'s
  own convention) — arguably better than today's unordered `.first()`.
- **Sequence:** re-index path first (post-swap, import owns the machine, smallest concurrency
  surface), then the collector path (ruling 6) once proven, with the rollback guard in place from
  day one — never the other way round.

If the empirical probe shows savepoint rollbacks are not observable, **stop**: scope the cache to
the re-index path only, where the transaction shape is known, and leave the collector alone.

---

## 6. Answer to ruling 8 — WAL is already in all-diagnostics

The staleness guard paid off: **the assumption that it is missing was wrong.** All three facts are
in an export today:

- **WAL size** — four independent members: `storage-composition.json` (`wal_bytes`,
  `storage.py:106`), `session-forensics.json` (`totals.wal_bytes`, `forensics.py:171`),
  `storage-footprint.json` (`forensics.py:353`), and unlock's `wal_bytes_before_open`
  (`forensics.py:266`).
- **`journal_size_limit`** — `storage-composition.json` (`storage.py:96-97`), with SQLite's `-1`
  honestly normalised to `None`.
- **Checkpoint starvation** — a heuristic `wal_note` when `wal_bytes > 4 × journal_size_limit`
  (`storage.py:107-112`) *and* a hard per-pass measurement (`busy`, `log_frames`,
  `checkpointed_frames`, before/after bytes) from `checkpoint_wal()` (`hygiene.py:225-236`),
  persisted into `scheduler_runs.jsonl` and reaching the export via
  `debug-bundle.json → payload.scheduler.recent_runs[].hygiene.wal_checkpoint`.

The WAL fields are computed **before** the dbstat walk, so they survive on SQLCipher builds where
dbstat is absent — the documented per-build capability trap is already handled.

**Three small gaps worth closing (S11, cheap):** `PRAGMA wal_autocheckpoint` is never read anywhere
in production (add one line beside `storage.py:96-97`); the last `wal_checkpoint` record is not
surfaced inside `storage-composition.json` (discoverability only — the data exists); and there is no
historical WAL series (`ALL_METRICS` is counts-only). The periodic-checkpoint-during-re-index idea
from the earlier question list is **not** proposed here: with design B and batched commits the
re-index stops being the WAL-bloat driver, so measure (S2) before adding a checkpoint call.

---

## 7. Answer to ruling 15 — what "stop immediately" can honestly mean

The pipeline splits into two regimes at exactly one line.

**Before `os.replace(working, target)` (`merge.py:1985`): abort is free and complete.** Stage A,
`prepare_staged`, `snapshot_working_copy`, `merge` and `verify` all run on a disposable
`.restore-<hex>` staging dir and a `working.db` copy; the merge is one `BEGIN IMMEDIATE` /`COMMIT`
(`merge.py:295`, `:353-362`). Killing it leaves only staging, reclaimed by `cleanup_staging`
(`artifact.py:725`) or `sweep_stale_backup_temps` (`stream_backup.py:147`).

Two caveats the brief must not gloss over: "live untouched" actually ends one stage **earlier** than
the swap — `side_files_and_custody` (`merge.py:1950`) writes calendar/state files into `data_dir()`
and imports custody chains into a separate `custody_log.db`, outside both the swap and the snapshot.
And **there is no abort hook at all today**: `run_restore` takes no `should_stop`, and all three
progress callbacks swallow exceptions by design (`merge.py:333`, `timing.py:51`, `store.py:523`),
so an abort raised through a callback would be silently eaten.

**After the swap: no undo exists, and building one is not safe.** A `merged_rows`-based delete is
unsound — the re-index delete-then-reinserts mentions so recorded ids go dangling
(`store.py:304`); `map_articles` joins on hash so a batch legitimately attaches rows to
**pre-existing** articles (`merge.py:601-604`); no path repairs `Keyword`/`Source` counters after
such a delete; and the raw `connect()` used by the merge sets no `foreign_keys` pragma, so cascades
would silently not fire. Snapshot-undo is safer but incomplete, and `_SNAPSHOT_KEEP = 3`
(`merge.py:59`) means in a 6-backup run item 1's snapshot is already gone by item 4.

**Therefore the honest semantics — and they get *better* because of §3:**

- **Pre-swap:** Stop = abort now, full undo, nothing touched. This is ruling 15 exactly.
- **Post-swap:** Stop = stop all *remaining* work; the merged data stays. The UI must say so
  plainly at the moment it becomes true ("this import is committed — stopping now leaves it in
  place and cancels the remaining N items").
- **The swap itself is uninterruptible** and must be explicitly non-cancellable: it unlinks the
  live `-wal`/`-shm` before `os.replace`, and the repo's own docstring (`runner.py:1915-1927`)
  states the swap is never gate-protected.

**The convergence worth noticing:** once S5 moves the re-index out of the import (ruling 1), the
post-swap window shrinks to a handful of cheap stages. So "stop immediately loses this import"
becomes true for nearly the whole duration in practice — ruling 1 is what makes ruling 15 honest.

---

## 8. The slices

Sequenced so every later slice rests on measured ground. Each is independently shippable as its own
draft PR.

### Phase A — quick wins, no architectural risk (do these first, they change what you observe)

**S1 — honest ETA + phase counter.** Reset the rule-of-three baseline **per phase** rather than per
job (`app.js:5753`, `:5669`), and show which phase the estimate belongs to. For ruling 17's
remaining-phase count: `M` is **not** a constant — the authoritative sequence is `run_restore`'s 16
`timings.stage()` calls plus 3 manager phases, minus `reindex` when `reindex_imported` is false, and
a dry-run stops after `corpus_delta_before` (so M is 19 / 18 / 8). Compute `phase_index`/
`phase_total` **server-side** where `commit` and `reindex_imported` are known, and send them in the
progress payload. A hardcoded M would be a fabricated number.
*Anchors:* `app.js:5679-5704`, `merge.py:1839-2141`, `volume_job.py:29-32`.

**S2 — re-index rate instrumentation (ruling 19).** `StageTimings` is float-only and
`_uxTimingsView` formats every value as a duration, so a rate must be a **sibling report key**, not
a `stages` entry. Whole-stage articles/sec is already derivable
(`report["reindexed"]` ÷ `stages["reindex"]`); what needs new code is the
load+decompress / precompute / apply / commit split — `reindex_articles`' window loop has three
clean boundaries (`store.py:651-673`). `precompute_batch` must also report **which path ran** (pool
vs serial short-circuit vs pool-failure fallback), or a timing cannot distinguish CPU work from a
silent serial degradation. Mirror `search_timing.py` for the JSONL. New report keys ride into the
persisted import report for free (`import_reports.py`), but the Markdown renderer needs a
conditional section, and the bundle-completeness ratchet likely needs the new member registered.

**S3 — pass `reindex_commit_batch` (ruling 7).** `volume_job.py:269-278` gains it; ~200 when
`was_paused` is true (the same condition already gating `all_cores_worker_count()` and
`import_cache_mb()`), 1 otherwise. Note the gate is held across a batch, which is fine precisely
because the import owns the machine.

**S11 — the three WAL diagnostics gaps** from §6. Small, isolated, no user-facing surface.

### Phase B — correctness before speed

**S4 — the counter-drift bug.** Reproducer first (§4), then the explicit reconcile at the end of
`run_restore`, then the parity test.

**S5 — the re-index becomes an autonomous, resumable, visible job** (rulings 1, 2, 12) **plus the
§3 decision.** Requirements:

- `run_restore` already has the seam: `reindex_imported: bool = False` (`merge.py:1782`) and
  `reindex_imported_articles(batch_id)` looks its work up from `merged_rows` in a **fresh session
  after the swap** (`merge.py:1740-1748`) — so a deferred job can find its work at any later time
  with no new bookkeeping.
- **A durable per-article cursor is mandatory** (§3). `reindex_articles` currently returns aggregate
  counts and stamps nothing per article (`store.py:506`).
- Surfaced as the **final stage of the import UI** with its own progress (ruling 2), and in the task
  manager as a resumable job. Mirror `NewsletterImportManager`'s persisted-cursor discipline
  (`import_job.py:71`, `:99-108`, `:133-137`, `:340-352`).
- Auto-starts. A re-index the user must remember to run would make design B unsafe.

**S6 — extraction fingerprint (rulings 3, 4).** An additive nullable column on `merge_batches`
(which already carries `app_version`/`alembic_rev`, `models.py:2159-2160`) plus a manifest field.
The fingerprint must hash **more than the app version** — extractor name, stoplist digests,
segmenter availability, the lemma setting — because stoplists are data files that change without a
version bump. A version-only check would be a fabricated equivalence claim. Mismatch ⇒ full
re-index (ruling 4). Under design B the "skip" path must still *produce* the derived rows, so the
fingerprint match short-circuits to **merging the derived rows as-is** rather than to doing nothing.
Alembic revision ids must be genuinely random 12-hex and confirmed free (`python -m alembic heads`
for the real head — a regex scan of the versions dir has fooled a past session).

### Phase C — the measured optimisation

**S7 — the keyword resolution cache**, exactly in the narrowed form of §5, re-index path first, then
the collector (ruling 6). Gate the claim on S2's before/after numbers.

### Phase D — the import queue and its UI

**S8 — immediate collector stop + one exclusive window (rulings 9, 10, 12).** Give the collect pass
a **cooperative between-source stop check** so `pause_for_exclusive_operation` stops it in seconds
rather than waiting out a full pass (`runner.py:1915-1927` documents the gap). Hold the exclusive
window across the **whole import queue** instead of releasing per item (`volume_job.py:284-290`).
Render the already-sent `own_the_machine` flag so the user is told collection is paused.

**S9 — the server-side import queue (ruling 13).** Closest fit is a **hybrid**, per the precedent
audit: skeleton from `DumpDownloadManager` (`wiki/dumps.py:121` — the only manager with N items,
per-item state and a persisted order: `{entries, queue_order}` written tmp+replace under a save
lock at `:192-210`, `_pump()` at `:233-256`, `reorder()` at `:258-268`, stale-`downloading`→`paused`
on load at `:183-190`), per-run discipline from `NewsletterImportManager`. Genuinely new: capacity
pinned to 1 *with* persistence; per-item state plus the active item's sub-progress persisted
together; heterogeneous item kinds; **pause only between items** (the merge is atomic — advertise
actions honestly, `jobs.py:25-39`); serialising on `VolumeBackupManager`'s singleton 409
(`volume_job.py:56-71`); server-side accumulated summaries via `persist_import_report`; and wiring
(`_import_queue_jobs()`, a third reorder route, cancel/resume branches, adding the kind to
`_DB_WRITER_KINDS` at `jobs.py:470-474` — pinned by a repo invariant).

**S10 — the import dialog redesign (rulings 13, 14, 16, 17).** Mirror `_renderOsmList`
(`app.js:15337-15385`) — it already solves per-row state + progress + per-row controls, and its CSS
exists (`.osm-region-row` `app.css:789`, `.cap-bar` `app.css:359`), so per-item import rows need no
new styles. Widen the dialog by editing the inline `max-width:560px` (`index.html:1641`) or
introducing the first `dialog` rule in `app.css`. Add: per-item rows with name + state + its own
bar; the phase-honest rate plus a cumulative line (ruling 14); a "Show details" panel carrying the
per-stage timings that already ride the report (ruling 16); pause/stop mirroring the export's
4-part pattern (`_uxPhase` `app.js:5805` → button at `:5856` → `_uxPauseResume` `:5903` →
`_uxShowPaused` `:5895`), but **only offering the actions the backend truly honours**. State
persists across a reload because the queue is now server-side.

---

## 9. Scope fences (do NOT do these here)

- **Do not touch the legacy single-file import path** (ruling 11). It is being removed; the removal
  note is in `docs/FUTURE_DEVELOPMENTS.md`. It is also the one row that can never show real
  progress (a single blocking POST with no status endpoint, `app.js:6154`).
- **Do not build a post-swap undo.** §7 explains why it is unsound.
- **Do not add a `UNIQUE` index on `keywords.normalized_term`.** Its absence is deliberate
  (`merge.py:614-617`); changing it is a separate, ruling-gated decision.
- **Do not implement ruling 2 as a per-article flag** without the §3 re-decision.
- **Do not claim a speedup S2 has not measured.**
- No new network behaviour anywhere in this brief.

---

## 10. Definition of done (per slice)

- Green on all CI gates in §0, plus a targeted regression test that **fails against the pre-fix
  code** (stash-verify it — the project has a recorded case of a guard that passed against both the
  code it meant to reject and the code it meant to accept).
- Every user-visible number carries its method; no fabricated ETA, rate, phase count or pass.
- Any renamed/removed id or function name updates `tests/test_unified_backup_ui.py`,
  `tests/test_repo_invariants.py` and `tests/test_backup_ux_corpus_gate.py` in the same commit.
- Frontend slices flagged "browser-unverified, needs click-through".
- A `docs/ledger/shipped.csv` row per slice; reusable lessons also appended to
  `docs/ledger/SHIPPED_LOG.md` and copied into the CLAUDE.md Session-rituals "Lessons" list.

---

## 11. Open items for the maintainer

1. **§3 — the (a)/(b)/(c) decision.** Everything in S5 depends on it. (a) is recommended.
2. **§5 — confirm the narrowed cache GO** (read-side warm only, transaction-scoped,
   rollback-invalidated), and accept that the empirical savepoint-rollback probe may downgrade it
   to the re-index path only.
3. **§4 — confirm the counter reconcile belongs at the end of `run_restore`** rather than being
   left to the online idle pass.
4. Whether imported articles should also be hidden from **search** during the re-index window, or
   only from analytics. The recon could find no code evidence of intent either way; design B leaves
   them searchable, which seems right (an article you can read but whose keywords are still being
   computed) — but it is the maintainer's call.
