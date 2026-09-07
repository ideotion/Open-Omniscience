# Open Omniscience — Roadmap

The single forward-looking board: current limitations, performance work, known bugs, and
the feature backlog, with a status + priority on every item. Consolidated 2026-07-10 from
the previously-scattered planning docs; **reconciled 2026-07-11 after the parallel A+B
autonomous wave** (Session A = scale backend, Session B = product/UX — ~25 items shipped;
see the 2026-07-10/11 rows in the ledger).

> **Where each kind of information lives** (read this first — it is the map):
>
> | Concern | Canonical home |
> |---|---|
> | **What's next + status** (this board) | **`docs/ROADMAP.md`** ← you are here |
> | **Binding maintainer rulings, UI invariants, the live Open queue** | **`CLAUDE.md`** (root) — the source of truth; this board summarizes it |
> | **Design intent / rationale** (the *why* behind big features) | **`docs/FUTURE_DEVELOPMENTS.md`** |
> | **Deep scale/stability detail** (P0/P1 acceptance, session territories) | **`docs/product/SCALE_ROADMAP.md`** |
> | **Per-feature design-of-record specs** | **`docs/design/*.md`** |
> | **The long-horizon V1 pathway** (version train 0.2→1.0 · the recursive self-improvement strategy · the new verticals) | [`docs/design/V1_PATHWAY_2026-07-14.md`](design/V1_PATHWAY_2026-07-14.md) |
> | **The improvement-cycle protocol** (how one measure→compare→plan→build→verify→record cycle is run) | [`docs/process/IMPROVEMENT_CYCLE.md`](process/IMPROVEMENT_CYCLE.md) |
> | **What already shipped** (index + verbatim log with lessons) | **`docs/ledger/shipped.csv`** + **`docs/ledger/SHIPPED_LOG.md`** |
> | **Release notes / history** | **`docs/CHANGES.md`** (changelog) · **`docs/HISTORY.md`** (narrative history) |
>
> Historical roadmaps (the pre-0.2 design-memory dump, the RICE backlog, the 2026-06-13
> grouped backlog) were archived to [`docs/archive/roadmaps/`](archive/roadmaps/) — nothing
> was deleted; their still-live items are folded into the sections below.

**Status legend:** ✅ shipped · 🔧 engine shipped, awaiting live-corpus validation · 🚧 in
progress · ⬜ planned/pending · 🎨 design-only (spec exists, not built) · 🔒 blocked on a
maintainer ruling · 🛠 operational (maintainer runs it — networked machine / live corpus).

> **Reconciliation note (2026-09-07, docs-hygiene + reality-check pass).** The header above still says
> "reconciled 2026-07-11", and that is the last time this board was walked row by row. This pass did
> **not** repeat that walk — it corrected the rows the 2026-09-06 repo analysis and this session had
> independently verified against the tree, and lifted three carry-overs that existed only inside a
> design doc onto this board (marked *lifted 2026-09-07*). **So treat a row's status as evidence of
> what was true when it was written, not of what is true now** — the tree is the authority, and the
> single most expensive recurring mistake in this repository is trusting a status line over a grep.
> A full row-by-row reconciliation is still owed; `docs/plans/2026-09-06-repo-analysis/INVENTORY.md`
> is the nearest thing to a current picture.

---

## 0. Where we are — the 0.2 "data safety at scale" cycle

A live 4–5-day run grew the corpus to **~100–130 GB** (the target is designed toward **5 TB**).
That exposed the theme of the whole cycle: **the app works, but does not yet scale — and the
scaling failures now cause crashes and data loss, not just slowness.** So 0.2's north star is
*"the version that survives a 100 GB field run."*

- `pyproject` version is **`0.3.0`**; the default branch is **`main`** (permanent since
  2026-07-15 — branch name and version are independent).
- The **`v0.2.0` tag is DONE** — the maintainer ran the in-app P0 validation job on the
  live corpus and tagged (2026-07 — see `docs/CHANGES.md` 0.2.0). The P0 scale set (§2)
  is thereby live-validated; the 0.3 cycle (measured & verified) is open.
- **Definition of "snappy" (the acceptance bar for 0.2):** every interactive endpoint p95
  **< ~500 ms** at 100 GB · **unlock < 2 s** · no UI action blocks > 1 s without becoming a
  visible job · background work never freezes the UI.
- **Just merged (the parallel A+B wave):** the Session B chain **#620–#627** + Session A's
  **#628** (integrity heavy-read guards) + **#629** (B10 i18n keying of the new strings) are
  all on `0.2`. The ⏳-marked items below reference those PRs and are now shipped.

---

## 1. Database — current limitations

| # | Limitation | Detail | Status | Ref |
|---|---|---|---|---|
| DB-1 | **Unlock at scale** | ROOT-CAUSED + FIXED (A1): `ensure_fts` ran the FTS5 `'rebuild'` — a corpus-scaled codec re-read — on EVERY boot; now rebuilds only when needed. Measured on a 112k/2.7 GB encrypted synthetic corpus: 28.6 s → **0.002 s**; warm unlock **0.012 s** (bar < 2 s). | 🔧 fixed on synthetic — **live-corpus validation is the remaining gate** (never claim closed on synthetic) | SCALE_ROADMAP P0.4 |
| DB-2 | **5 TB single-file SQLCipher unvalidated** | Page cache, VACUUM infeasibility, backup windows, single-writer behaviour at 5 TB never measured. Cross-time recall is sacred — no partitioning that makes old data second-class. | 🎨 design-only | SCALE_ROADMAP P1.7 · `DATA_ARCHITECTURE_SKELETON.md` |
| DB-3 | **Persisted encrypted columnar store (D1) — machinery built, gated on the per-OS binaries** | S3 built the D1 offline pin-and-verify httpfs LOADER + the D2/D3 persisted-serve wiring (epoch-gated incremental refresh), all behind `secure_crypto_available()`; the shipped `duckdb-httpfs-extension` registry pins are BLANK so it stays in-memory until the operator fetches + pins the per-OS httpfs binaries (`extensions.duckdb.org` egress-blocked here — the one networked step, per `EXTERNAL_DEPENDENCIES.md`). No checksum fabricated; a CI lane exercises the real path (checksum computed in-lane, never promoted). | 🛠 operational (machinery built + tested; awaiting the operator's networked binary fetch) | SCALE_ROADMAP Ruling-gated #2 · `PERSISTED_DUCKDB_HTTPFS.md` · S3.1/S3.2 |
| DB-4 | **Keyword-table junk growth** | SEGMENTER SHIPPED (B1): zh/ja/th word segmentation via the optional `[segmentation]` extra (jieba MIT · janome Apache-2.0 · pythainlp Apache-2.0 — pure-local, dicts in-wheel, zero network) + ko/vi/mr (and fa/hu/…) stoplists vendored; graceful degrade without the extra. | 🔧 shipped — remaining: **install the extra + "Clean up keywords" re-index on the live corpus** to apply retroactively and measure the real junk reduction | SCALE_ROADMAP P1.5 / Ruling-gated #1 (executed) |
| DB-5 | **~120 GB of the data folder unidentified** | The instruments are now shipped: the A12 `du`-style data-dir breakdown + the A12b/B14 itemized storage footprint (incl. the external Ollama store). The mystery itself is still unnamed. | 🔧 diagnostics shipped — **awaiting the maintainer's next field export** to name the 120 GB | SCALE_ROADMAP 2026-07-09 event |
| DB-6 | **dbstat absent on the encrypted store** | The bundled `sqlcipher3` ships without dbstat, so the per-table storage-composition report degrades to PRAGMA totals only on the live encrypted DB. | ✅ shipped w/ honest limit; dbstat-enabled build is the follow-up | SCALE_ROADMAP P1.5 |
| DB-9 | **Backup parity ceiling < 5 TB** | FIXED (S3.3): adaptive volume sizing bounds the volume COUNT not the size — N stays ~200 so N+M stays under the GF(2⁸) 255 ceiling at any scale (byte-identical below ~100 GB); sizes against the REAL per-member volume count (a skeptic caught + fixed a member-count-gap that could otherwise breach 255). Crash-safety unchanged; torture-tested incl. an interrupted tier-crossing. | ✅ shipped (S3.3) — RE-RUN the S1 P0.1 live validation before tag-day (this changes that engine) | SCALE_ROADMAP post-merge audit F6 · S3.3 |
| DB-10 | **Near-dup growth / eviction / vacuum posture** | Decision MEMO written (S3.4, `docs/design/DB10_RETENTION_VACUUM_MEMO.md`): the IRREVERSIBLE auto_vacuum/page_size CREATE-time seam needs a maintainer ruling BEFORE 0.2 tags (a corpus created without it can never reclaim — full VACUUM infeasible at 5 TB); incremental-vacuum idle pass ready to wire into S2.2; tiered raw-text retention + near-dup folding are footprint-measure-gated. auto_vacuum now visible in the storage diagnostic; cross-time-recall codified as a repo invariant (§F). | 🎨 memo + cheap instrument + invariant (ruling-gated) | SCALE_ROADMAP P1.5 · S3.4 |

**Already resolved (this cycle):** expression index on `coalesce(published_at,created_at)`
(was 735 s of full scans → index-only, #588) ✅ · corpus-epoch mechanism (`derived_meta`) ✅ ·
**corpus-epoch wired into the restore-merge** (was DB-7; A7) ✅ · **alembic stamp self-heals to
head** (was DB-8; A8) ✅ · covering mention indexes / FTS optimize / batched commits / the
single-writer gate ✅ · storage-composition diagnostic ✅.

---

## 2. Performance & scale — the P0 / P1 board

The deep detail (measured numbers, acceptance criteria, session territories) lives in
[`docs/product/SCALE_ROADMAP.md`](product/SCALE_ROADMAP.md). This is the status summary.

### P0 — data safety at scale (the release blockers — attended sessions)

The live-corpus validation of this set is now **push-button**: run the in-app
**P0 data-safety validation** job (Settings → Diagnostics) and follow
[`docs/product/P0_VALIDATION_RUNBOOK.md`](product/P0_VALIDATION_RUNBOOK.md). It
drives the real backup engine, verifies it, probes a staged restore + dry-run
merge preview (never touches the live corpus), and reads the unlock + collector
instrumentation into one report with a per-check verdict. The live RUN and the
`v0.2.0` TAG stay maintainer-only.

| Item | What | Status |
|---|---|---|
| **P0.1** | Backup at 100 GB+ — the `oo-volumes-2` streaming engine (no plaintext corpus snapshot, no zip, bounded RAM incl. banded parity, incremental changed-volume re-emit, resumable, verifiable) | ✅ live-validated (the maintainer's P0 validation run — the v0.2.0 tag) |
| **P0.2** | Restore/import at scale — streams member-by-member, disk-preflights staging, hands to the unchanged additive merge | ✅ live-validated via the P0 validation job's staged-restore probe + dry-run merge preview (the v0.2.0 tag run) |
| **P0.3** | Crash root-cause — OOM in a 21.6-h crawl pass (**RSS 10.6 GB > VM RAM**); fix = pass recycling + an RSS memory guard + inter-pass WAL checkpoints | ✅ live-validated (the v0.2.0 tag run reads the collector instrumentation) |
| **P0.4** | **Unlock at scale** — ROOT-CAUSED + fixed (Session A, `claude/a-scale-backend-p04-9faxvb`): `init_db`→`ensure_fts` ran the FTS5 `'rebuild'` (a corpus-scaled codec re-read) UNCONDITIONALLY on EVERY boot; the sync triggers already maintain the index, so it now rebuilds only when needed. Measured on a 112k/2.7 GB **encrypted** synthetic corpus: 28.6 s → **0.002 s** per boot; G2 warm unlock **0.012 s** (acceptance <2 s). | ✅ live-validated (the v0.2.0 tag run reads the unlock instrumentation) |
| **P0.5** | Scale test harness (GAMMA: synthetic-corpus generator + benchmark runner + CI smoke tier) | ✅ shipped (#601) |

### P1 — snappiness at scale (adoption-critical)

| Item | What | Status |
|---|---|---|
| **P1.1** | **Death-spiral fix**: server-side deadlines + client single-flight polling + a concurrency cap (requests stacked without cancellation; one endpoint was in-flight 217 s) | ✅ shipped (the `heavy.py` admission guard + honest 429 client retry); the last uncovered reads — integrity profile/actors/prominence/fixity — are now guarded too (#628) |
| **P1.2** | Job-ify heavy sync handlers (enrich-source-types 8.5 min · governments 2.9 min · diagnostics `/all` 36 min — all background jobs now; heavy reads guarded) | ✅ largely shipped — **S2.4 sweep (2026-07-12): `corpus-www`/`corpus-sentiment` CONFIRMED already `_deadlined`**; the sweep then guarded the previously-raw corpus-scaled reads — the 8 raw insights endpoints (who/where/convergences/ring-countries/source-laundering/recycled-claims/reading-diet-by-type/keyword-tags-keywords), the 6 cache-only ones upgraded to `_deadlined` (4 manipulation cards + source-types + map-coverage), the per-keystroke `omni` (degraded-not-429 so the omnibar never blanks), and the link OOM-risk endpoints (stats/top-cited/articles-by-link/citation-graph whole-table materializations, now deadline-bounded). **Carry-over** (on-demand, not polled — lower snappy priority): ~~`framing` (cap only)~~ ✅ shipped S10 (`analyzed_n`/`total_n`/`capped` disclosure), ~~`monitoring/anomalies` + `commodity/correlation` (grouped-SQL rewrite)~~ ✅ shipped S9 (`api/monitoring.py:66` groups on `substr(published_at,1,10)`; `api/commodity.py:161` is index-fed), `link/corpus`+`shared` (already corpus-bounded via `_resolve_corpus` cap). **Still open:** `source_io/sources` — the real fix is a maintained per-Source counter with its own reconcile + envelope, which needs an additive `Source` column and so belongs with whoever owns `models.py`/migrations (re-verified open 2026-08-20). |
| **P1.3** | `count(*)` from maintained counters (`SELECT count(*) FROM keyword_mentions` = 724 ms × 172 = 124 s) | ✅ **swept (S2.3, 2026-07-12)** — audit verdict: the maintained keyword counters (`Keyword.mention_count`/`article_count` + `reconcile_keyword_counters` slice-sweep + `counter_envelope`) + the data-version count caches (`/status`, Database/Library stats) are the reference impl and the 3 hottest corpus aggregations already route through counters. The one genuine hot-path residue — the **unfiltered `/api/articles` browse `COUNT(*)`** — is now served from a data-aware `PRAGMA data_version` cache (`_browse_total_cached`, S2.5; stays EXACT, invalidates on any write). **Carry-over:** the reader per-source article count (needs a NEW maintained `Source` counter — a bigger change with its own reconcile+envelope); a corpus-wide `/status` keyword/mention counter is DELIBERATELY gated (needs the basis bound to the corpus epoch, not the reconcile watermark — the queries.status docstring). |
| **P1.4** | `/insights/latest` (40 s @ 268 K → near-dup bounded) | ✅ shipped — re-measure on next field export |
| **P1.5** | Storage-composition diagnostic | ✅ shipped (dbstat-limited on encrypted store) + the itemized all-stores footprint (A12b/B14 ⏳ #625) |
| **P1.6** | Corpus-epoch mechanism | ✅ shipped — **now incl. the restore-merge wiring** (A7) |
| **P1.7** | 5 TB architecture verify-before-trust review | ✅ **shipped (S2.6, 2026-07-12): [`docs/design/5TB_ARCHITECTURE_REVIEW.md`](design/5TB_ARCHITECTURE_REVIEW.md)** — measured/arithmetic/extrapolation-tagged review of single-file SQLCipher at 5 TB (page cache + codec, the auto_vacuum/page_size CREATE-time seams, VACUUM infeasibility, the GF(2⁸) 128 GB parity ceiling with **adaptive volume sizing** `max(512 MiB, ⌈corpus/200⌉)` keeping N≈200 at every scale, the backup gate window, the derived-layer/D1 hand-off, cross-time-recall invariants, a GAMMA slope-measurement plan + a real 960 MB-encrypted sandbox point) — **S3's input** (8 ordered recommendations, each tagged buildable-now / operator-gated / ruling-needed). |
| **P1.8** | Collector-path write batching (writer gate: 847,351 s cumulative wait / 22% of worker-time / max 438 s) | ✅ shipped |
| **P1.9** | Job-ify the diagnostics `/all` export (was 36+ min blocking the loop) | ✅ complete — backend (#600 D2) + the UI job button (B6, #622) |
| **P1.10** | trending-windows cold path (467 s/call; 62 calls / 3,286 s) — stale-but-disclosed serve + change-gated refresh | ✅ shipped — D1 persisted store still pending (see DB-3) |
| **P1.11** | Flip on the D4 map serve (map GROUP BY was 748 s total / ~150 s per call) | ✅ shipped |
| **P1.12** | Background maintenance under the job/deadline regime (counter-reconcile 86–104 s/pass; prune 32 s) | ✅ **complete** — deadline+watermark half shipped earlier; **off-peak scheduling shipped S2.2 (A10, 2026-07-12)**: `src/scheduler/maintenance.py:run_idle_maintenance` runs the budgeted reconcile/prune slices in the collector-IDLE window (scheduler-owned `_run_off_peak_maintenance`, holds `_run_lock` so it is never concurrent with a pass, throttled `OO_MAINT_INTERVAL_S`=300 s, skipped under memory pressure, `_stop`-interruptible), DECOUPLED from the pass-tail `warm_cache`; freshness gates + `complete:false` disclosure unchanged; surfaced in scheduler `status().last_maintenance`. |

**Heavy-endpoint sweep status (was the ⬜ list from the 2026-07-08 field test):**
`signals/alerts`/`flood`/`bury` + `insights/lunar-correlation` + `server-locations` +
briefing/trending/associations — **guarded** ✅; integrity reads (profile/actors/prominence/
fixity) — **guarded** ✅ (#628); the S2.4 sweep guarded the remaining polled/OOM-risk reads
(insights raw-8 + cards + omni + link_analysis) ✅; **`/api/articles` p95 25 s FIXED (S2.5)** —
the 3 handlers moved `async def`→plain `def` (Starlette threadpool, no event-loop freeze) + the
FTS path stopped materializing the whole match (id-only resolve → load the PAGE only; measured
50 ms→11 ms warm at 1,776 matches) + a data-aware browse-count cache. Carry-over: `diagnostics/
keywords` (100–184 s) + `debug-bundle` (69 s) → job/degrade; the S2.4 on-demand tail
(source_io/framing/anomalies/correlation). 🚧

**Perf riders (post-merge audit) — INVESTIGATED & DECLINED (Session A), then REPRODUCER-VERIFIED
& CLOSED (S2.1, 2026-07-12; `tests/test_write_gate_riders.py`):** all four confirmed against the
tree with probes/measurements. **F14 REFUTED by test** — `SessionLocal` is `autoflush=False`, so a
read never flushes a dirty session and the markets freshness query cannot hold the gate across a
feed fetch (`run_rule` also commits every branch); the test pins the property. **F13 REAL hold,
DECLINED** — the batched collector flush holds the gate across per-article keyword EXTRACTION
(measured ~13 ms/article GIL-bound CPU, ~105 ms/batch at batch=8), but splitting `index_article`
(the hottest correctness-critical function) is high-risk and GIL-bounded-marginal (extraction
serialises on the GIL regardless; the only recoverable gain is the already-amortised fsync overlap);
reproducer pins the hold. **F10 REAL, DECLINED** — `_drain_wal` takes the gate then a pool
connection (inverted), but via `engine.connect()` bounded by `pool_timeout` + best-effort (WAL rides
as a member); never a true deadlock. **F11 REAL, DECLINED** — `_corpus_facts` runs under the backup
freeze() gate, but it MUST (the tamper-evidence commitment must match the streamed at-rest bytes) and
it is a rounding error beside the under-gate corpus byte stream (minutes at 100 GB). F10/F11 are P0
backup-path, untouched per risk>gain. ✅ closed (reproducer-first)

---

## 3. Known bugs & data-safety issues (still open)

| Bug | Impact | Status |
|---|---|---|
| **App OOM crash under load** | A crash in a disposable VM = **total corpus loss**. Collector fix shipped (pass recycling + RSS memory guard + WAL checkpoints); needs the live-run validation. | 🔧 fix shipped, awaiting validation (P0.3) |
| **FLOOD card polluted by leaked common words** | `signals/flood` surfaces Dutch filler ("kijk"/"zien") as topics. Deliberately NOT hand-stoplisted (open-class words need the **measured** keyword-log sweep / lemmatization track, per the ledger discipline). **S4.6 (2026-07-12): the `--generic-terms` detector now rides the LIVE keyword-engine report (`engine_report._generic_terms`)** — so the maintainer's routine diagnostics export carries the open-class worklist automatically (POS-free review candidates, never auto-applied). Remaining: the maintainer runs the review loop on a fresh export + applies the reviewed batch. | 🛠 operational (detector in-app; review-loop is the maintainer step) |
| **Date-extraction recall — the broader tail** | hu/fa relative-day words shipped (B4, #617 — measure-first found the field figures 0%/22% were STALE). **S4.1 (2026-07-12): a CJK-numeral date PROBE landed in `datediag`** (context-only, NOT actionable — it MEASURES the CJK recall tail, never asserts a fabricated date). Residual: EXTRACTING those CJK dates (segmenter-dependent follow-up) + the other `date-like-but-unextracted` classes. | 🚧 residual (P2; CJK probe shipped, extraction deferred) |
| **`diagnostics/keywords` + `debug-bundle` under load** | 100–184 s / 69 s in the field export. S2 assessed both (S2.5): `diagnostics/keywords` already streams on a read-only WAL snapshot + threadpool + is deliberately un-deadlined (the maintainer forbade capping the keyword crunch) — the honest fix is collapsing its 3 keyword_mentions passes / serving totals from counters + optional job-ify; `debug-bundle` wants read-only-db + wider `_safe()` + a per-member budget or the all-diagnostics job template. **Carry-over** (both on-demand, not polled). | ⬜ carry-over (S2 assessed; job/collapse) |

**Fixed by the A+B wave (⏳ = in the open PR chain, done pending merge):**
disposable-VM durability — opt-in persistent `data_dir` + honest ephemeral-root note (A11) ✅ ·
backup UI false "NetworkError/Backup failed" — job-state-as-truth polling + capped-backoff
retry + paused-state label + verify/pause-resume wiring (B5) ⏳ #624 ·
standalone backup **verify** — volumes verify job (already shipped) + the **folder-manifest
verify** backend (A6) ✅ + its UI (B5) ⏳ #624 ·
indices board empty on most continents — all 19 OECD FRED ids corrected to 2-letter ISO +
a convention-pinning regression guard (B2, #614) ✅ ·
BURY card language artifacts — same-language cohort scoping (B3) ⏳ #620 ·
dead default calendar feeds filtered from the loaded directory (B7, #619) ✅ ·
FTS present/absent probe contradiction — both probes derive presence from the schema;
a timed-out count reports `count_status=timed_out`, never "absent" (verified B11c) ✅.

**Fixed earlier this cycle:** restore arbitrary-file-DELETE from a hostile backup (traversal
guard) ✅ · finalize could destroy a complete backup mid-swap (atomic manifest replace) ✅ ·
mindmap 503 at 974K keywords (bounded + deadline, never 503) ✅ · alert-strip 24 s → sub-ms
(memo cache) ✅ · autoflush held the write gate across a fetch (the 438 s signature) ✅.

---

## 4. Feature backlog & add-ons (by area)

Design rationale for most of these lives in [`docs/FUTURE_DEVELOPMENTS.md`](FUTURE_DEVELOPMENTS.md);
this is the tracked list. Items already shipped are omitted (see the ledger).

### Keyword engine & quality
- **zh / ja / Thai segmentation** — ✅ **SHIPPED (B1)**: jieba/janome/pythainlp via the optional `[segmentation]` extra (pure-local, dicts in-wheel, zero network, graceful degrade) + ko/vi/mr (and fa/hu/…) stoplists vendored. Remaining 🛠: install the extra on the live box + "Clean up keywords" re-index to apply retroactively; measure the real junk reduction.
- **Date-extraction recall — the residual tail** — hu/fa relative-day words shipped (B4); the CJK-numeral **probe** shipped (S4.1, measure-first/context-only). Remaining: EXTRACTING the CJK dates (segmenter-dependent) + the other `date-like-but-unextracted` classes. 🚧
- **Open-class stoplist sweep** — the measured `analyze_keyword_log --generic-terms` loop over a fresh export (kills the FLOOD filler + "rising"-card leaks; never a hand-guess). **S4.6: the detector now also rides the in-app `engine_report`** (`generic_terms` block), so the diagnostics export carries the worklist automatically; the review-and-apply loop is the maintainer step. 🛠 operational
- **Trans-language equivalence — remaining** — the cross-country ring MAP ✅ shipped in Groups (`showRingMap`, 2026-07-03); residue: the `language_breakdown`/`members` hover on the Trends/Home merged rows (→ S4.2) + local-LLM proposing candidate rings. 🚧
- **Lemmatization default-on** — ✅ **SHIPPED (2026-07-18)**: `OO_FAMILY_LEMMA` flipped to default-ON after a maintainer precision review of the live-corpus `lemma_preview` (35 groups / 71 keywords, clean); the measure-before-trust gate was satisfied by that review, not an IR-harness A/B (lemmatization is a display-layer change, invisible to retrieval). Opt out with `OO_FAMILY_LEMMA=0`; `learn/learning` recorded as a watch item, not pre-denylisted.
- **Keyword-log-driven catalog pruning** as a repeatable workflow. 🛠 operational

### Backup, import / export & data-safety
- **Backups include downloaded Wikipedia dumps** — dedup-by-checksum, additive restore must place FILE members into `wiki_dumps`. 🎨 (reverses design D3)
- **Remove the legacy single-file backup RESTORE** once the format is fully retired (keep the additive-merge engine). 🎨
- **Unified Import + unified Export/Backup dialogs** on the streaming-volume path — shipped earlier; the B5 wave (⏳ #624) added job-state-as-truth polling, the paused-state label and verify/pause-resume wiring. Remaining: click-through 🛠 + key the new strings ×12. 🚧
- **Unified import/export — the browser-gated cleanup** (*lifted 2026-09-07 from `docs/archive/design/UNIFIED_IMPORT_EXPORT.md`, where it was the only live record*) — after a click-through, retire the orphaned volume/folder JS handlers (`folderBackupStart` / `volBackupStart` in `src/static/app-backup.js`, whose panels the unified dialogs replaced) and the capped single-file-CREATE remnant. Verified 2026-09-07: single-file CREATE is already retired (`src/api/backup_v2.py` header); what survives is `POST /legacy/restore` + the 2 GiB `_MAX_RESTORE_BYTES` upload cap, which stay until the legacy format is retired (the row above). Belongs on the browser-verify burn-down, not to a blind removal — the interleaved-shared-helper hazard. 🛠 browser-gated
- **Import performance — the CHECKPOINT INTERVAL K: mechanism shipped 2026-09-07 (PR #1034), the NUMBER is a ruling.** A multi-backup import pays, *per item*, a whole-corpus working-copy snapshot, a whole-file `quick_check` + `foreign_key_check` over it, and an atomic swap. K > 1 carries one working copy across K consecutive backups and pays those once; `verify_copy` split into `verify_merge` (per item — counts, the search index and the sampled comparison against the artifact all need that item's staging tree, which is deleted the moment it returns) and `verify_file` (per checkpoint — `quick_check` + `foreign_key_check` ask about the FILE, so they cover every merge in it). The gate is not weakened; what grows with K is the window in which a crash costs work. **The shipped default is 1 = today's behaviour byte for byte** (`AppSettings.import_checkpoint_k`, range 1..24, refused loudly outside it rather than clamped; `OO_IMPORT_CHECKPOINT_K` for one process; a control in Settings → Data). **Recommendation on record: 3** — at which a kill at item 12 of 18 loses up to two merges' CPU that today it would keep, which is a change to what a Stop costs every operator. 🔒 blocked on a maintainer ruling (§5, *Still with the maintainer*)
- **Import performance — PREFETCH (stage the next backup while the current one merges): PARKED, and this is a finding rather than reluctance.** All three blockers re-verified against `main`@690920e on 2026-09-07: the singleton restore manager is one-job-at-a-time by design (`volume_job.py:196`), `cleanup_staging` sits in a merge-thread `finally` (`volume_job.py:764`) over a tree that is **plaintext** by design — so an orphan is an at-rest hole, not just bytes — and the already-merged digest check runs 94 lines *before* staging (`:456` against `:550`), which the field log says saves 47–56 min on **8 of 18** imports. **Its own gate is also still unmet:** the recommendation was "build only if the first real `verify_copy` number shows prepare still dominating", and no field `verify_copy` has ever completed. Contrast with K, which was the safe half to build: the carried file is a WORKING COPY, encrypted whenever the corpus is. ⬜ gated on the row below
- **The first field `verify_copy` number** — every remaining import-performance estimate rests on it, and both recorded field runs ended before it. It costs nothing to obtain: the sub-timings (`verify:quick_check` / `foreign_key_check` / `counts` / `content_sample`) and `working_copy_bytes` already ship, so the next completed backup converts a wall-clock figure into a rate. Until then, [`docs/design/IMPORT_PERFORMANCE_2026-08-08.md`](design/IMPORT_PERFORMANCE_2026-08-08.md) §5b is a **stand-in measured on sandbox disk** (170–178 MB/s against the field's own 17 MB/s on a 32 GB artifact) and becomes a cross-check the moment a real one lands. 🛠 operational (one completed field import)
- **Checkpoint UI — browser click-through owed** (PR #1034): the Settings → Data interval control and the import queue's new `staged` ("Merged — not yet saved") / `discarded` ("Discarded — import it again") rows. Node-checked, invariant-guarded and keyed ×12, never clicked. 🛠 browser-gated

- **Newsletter publisher ATTACH — the write path** (ruling 2026-06-15 clause (d); the resolver
  shipped ⏳ #1030, the attach deliberately did not) — imported newsletters still all land in one
  bucket source. The decision machinery now exists and is tested: a vendored, digest-verified Public
  Suffix List (`src/catalog/publicsuffix.py`), the ruled ladder (eTLD+1 → exact `Source.domain` →
  alias map → new DISABLED email source, never fuzzy), the platform inversion applied first (measured:
  NO newsletter platform is in either section of the PSL, so the list alone would collapse every
  Substack publisher into one source), `List-Id` parsed and kept, and a read-only preview at
  `GET /api/newsletters/publisher-preview`. **What is left, in this order, because the order is
  load-bearing:** (1) the **provenance columns** — send-domain and the attached source id, an additive
  migration; the ruling's UNDO is only feasible once they exist; (2) the **attach itself**, behind
  them; (3) the **import UI announcing the automated attaches + the undo**. Ruling (d) pairs the
  silent auto-attach with (3), so shipping (2) alone is half a data-placement change. **Note for
  whoever wires it:** `resolve_newsletter_publisher` matches `lower(Source.domain)` deliberately (the
  column is BINARY-collated and stored as typed, and a one-sided normalisation is a match that
  silently never fires) — that is a scan, free for a report and wrong per message; a functional index
  needs a migration AND meets the recorded NOCASE/expression-index problem, so it is a decision, not a
  tidy-up. ⬜
- **Live mailbox pull as a JOB** (plan S7) — `import_mailbox` (`src/api/ingestion.py`) is still a
  SYNCHRONOUS endpoint over a potentially long pull, invisible to the task manager. **I1 (stored,
  encrypted credentials for repeat pulls) stays 🔒 blocked on a maintainer ruling** — it adds a secret
  to the store, which is a real decision and not a convenience. The anonymise-at-ingest guarantees are
  not negotiable in any of it: no recipient identity, no raw `.eml`, no recipient-bearing header,
  tracking-link detox, and never a fetch at import (N files ⇒ zero sockets — the property that stops
  an open-tracking pixel confirming a read). The import-time no-recovery disclosure ×12 needs
  VERIFYING rather than assuming. ⬜ / 🔒
- **Collector write-batching** — ✅ SHIPPED as P1.8 (`src/ingest/batch.py` + `tests/test_collect_batching.py`; this row lagged §2's own ✅) — S6 verify-marks the no-loss battery.

### Database / scaling (columnar & rollups)
- **D1 persisted encrypted DuckDB store** — ruling given 2026-07-11 (#2): **S3 builds the machinery now**, gated behind `secure_crypto_available()` (CI installs the extension; local skips honestly); the per-OS binaries themselves stay a 🛠 networked operator step (see DB-3). 🚧
- **D2 `keyword_daily` rollup + D3 incremental epoch-gated refresh** — S3 builds against the gated D1 store. 🚧
- **D5 Roaring co-occurrence bitmaps** (pyroaring) — optional, off the critical path. 🎨

### Maps & geo
- **Hand-rolled offline vector-map renderer** — canvas 2.5D / CSS-3D, no WebGL/Three.js/tiles. 🎨
- **Temporal-map remainder** — linear/log time-scale toggle + feed the mention layer with **event-places** (the temporal map itself is retired into `ooMap`). ⬜
- **OSM download-manager remainder** — per-job rate/ETA/bandwidth-cap controls, country sub-extracts, one consented exact-size refresh. 🚧 partial
- **OSM as a DATA SOURCE for all maps** (ruled 2026-07-13, Q1a; build DEFERRED to its own session) — an OFFLINE preprocessing job turns OSM extracts into compact simplified geometry (finer admin-0, **sub-national admin-1** for region choropleth, a richer place gazetteer) that replaces/augments Natural Earth on every map surface, fixing the ~75 microstate centroid-fallbacks + coarse borders. Border-honesty: disclose "OSM convention as of `<date>`", surface disputed borders as CONTESTED. no-WebGL stands (live street-level detail is out of scope). Sits behind P0 scale + the sources system. ⬜
- **Observed-IP choropleth as its own DIMENSION** — a map layer keyed on the `server_ip` observations
  must stay DISTINCT from the catalog-ASSERTED country dimension. Asserted origin and observed
  infrastructure are different classes of fact (a publisher's CDN edge is not its country), so
  blending them silently would be the fabrication; two dimensions, each named, or neither. ⬜
- **3D keyword explorer** — formally **DEPRIORITIZED** (ruled 2026-07-13, Q5a; supersedes the 2026-06-16 "do NOT defer the 3D"). The 3-level mind-map (Keywords/Families/Super-groups) stays as-is. ⬜

### Agenda & calendars
- **Eclipse canon** from a bundled public table (all four moon phases + seasons already shipped). 🎨
- **Agenda confidence TIERS** (⏳ #1030 recorded the gap; not built) — the catalog carries ONE boolean
  `confirmed`, and `agRow` renders three pill states from it. The ruled vocabulary needs three:
  `scheduled` (official, sourced) · `window` (a legal window — the France-2027 `confirmed:false`
  pattern) · `projected` (a sourced rule plus last-held). A **passed projected date** is marked
  "status unknown — check the official source" (itself a lead) and is **never silently
  re-projected**; **no sourced rule + no last-held ⇒ no entry at all**, a gap rather than a guess.
  Not started deliberately: it is a schema + display change across `configs/world_events.yml`, the
  catalog loader and the agenda, and half-building a schema is worse than parking it. ⬜
- **Deduced events as first-class agenda entries** with keyword links (RC-blocking-era item). ⬜
- **Worldwide calendar preloads** — bank holidays; Islamic computed with the ±1-day caveat; Hindu/Buddhist from sourced tables; fix Christian-centring. 🎨
- **One recurrence model** — *measured 2026-09-07 (⏳ #1030), and this row was half wrong:* the
  **SCHEMA IS SHIPPED and tested** (`catalog._in_active_range` / `_span_end_date` / `_span_for`, the
  `origin_year`/`until_year`/`end_month`/`end_day` fields, floating nth-weekday recurrence, all pinned
  by `tests/test_event_recurrence.py`). What is missing is the **DISPLAY**: `app-agenda.js` renders
  none of it, so a month-span event ("Dry January") draws as a single day and a `since:` origin year
  is never shown. Still genuinely unbuilt beside it: **RRULE expansion of imported VEVENTs** (no
  `rrule` anywhere in `src/`, verified), **saved-filter "smart calendars"**, **catalog depth flood**
  (elections/summits/central banks/courts/UN days), **agenda i18n**, **temporal-map player speeds**
  0.05×–16×. 🚧 schema shipped, display + iCal RRULE open

### LLM / AI
- **LLM language detection for unknown-language articles** — ✅ **BUILT (B15)** ⏳ #626: opt-in, detector-first, a third clearly-labelled "AI-derived · unreliable" provenance class, never overwrites the asserted/detector channels, garbage answers store nothing, visible abortable job. Remaining 🛠: browser click-through + run it on the live corpus.
- **LLM-assisted perception** — who/where/when extraction (dates/places/orgs, no "what") as confirmable candidates in the AI layer, distinct toggleable layers. 🎨
- **Eval-first harness** — difficulty-tiered, phenomenon-tagged, ×12 langs; precision/recall/hallucination per stratum; the gate for every perception/sentiment change. ✅ **SHIPPED (S6.5)**: `src/analytics/perception_eval.py` (who/where/when; per-stratum precision/recall/HALLUCINATION vs a synthetic ×12-lang gold set; place-string vs coordinate apart; de-US-centring split; no composite) + `run_perception_eval_selftest` + `/api/diagnostics/perception-eval-selftest`. Extraction itself waits for a model to clear it (operator). 🎨→✅
- **Multilingual sentiment** — **DECIDED (B12, ruling 3a executed): the model path is deferred** (pyproject bans torch/onnx/transformers), pivot to a rule-based **subjectivity/loaded-language** signal feeding the manipulation cards. Build pending: license-clean per-language subjectivity lexicons. ⬜ decided, not built
- **Offline LLM USB kit** (checksummed Ollama binary + one small model — the air-gapped path) · **hardware-tier messaging** · **live ollama.com library browse**. 🎨
- **LLM-as-grader / attributed-claims + embedding novelty** — recorded, not approved (leaning against a composite grade). ⬜ open

### Sources, statistics & diversity
- **Self-curating sources — Phase 0 diagnostic + Phase 1 standing AUDITOR** — Phase 0 (the one-shot source-quality diagnostic + zip) ✅ SHIPPED (#655–#657). **Phase 1 the standing auditor ✅ BUILT (omnibus #663, draft):** per-source extraction-VALIDITY status (healthy/watch/degraded/failing) from a cohort-relative criteria panel, NEVER a blended score, audits extraction validity NEVER editorial merit; auto-demote machinery built DEFAULT-OFF (ruling Q2a, flag-only), reversible; `/api/diagnostics/source-audit`. REMAINING (🛠 operator): the idle-maintenance wiring + the Phase-0-calibrated allowlist + enabling auto-demote (gated on the operator's live source-quality zip run). 🚧
- **Self-curating sources — Phase 2 discovery funnel** (ruled 2026-07-13, Q3a/Q4a) — candidate → trial → graduated funnel; graduation passes through the Phase-1 quality gate. ✅ **TWO SLICES SHIPPED (omnibus #667, draft):** (1) the flagship **Wikipedia-references channel** — zero-network, parses the references of the already-stored watched-page wikitext across all editions, registers DISABLED `SourceCandidate`s (editions = the diversity signal); (2) **`external_sources` WIRED** as the resolution table (Q4a — `discovered_via` provenance, idempotent resolve on every discovery, dormancy ended; additive migration + self-heal). REMAINING (the dedicated Phase-2 slice): the **promotion frontier** (candidate → trial → graduated, trial auto-enable DEFAULT-OFF, diversity-weighted, the auditor as the graduation gate — needs its own `SourceCandidate` state columns + the consent-gated trial-enable wiring) + a browser-verified audit view + undo + the citing-trail surface. 🚧
- **`stat_indicators.yml`** curated dated series + freshness test · **more parsers** (OECD SDMX-JSON 1.0, IMF 3.0, WHO OData, FAOSTAT) · **SDMX live-verify** (networked). 🎨/🛠
- **`ooViz` honest-chart family** (small multiples, dumbbell/slope for vintages + CIs, association scatter with no regression line, treemap, histogram/box, Sankey, availability heatmap, population pyramid, error bars) with the reject-list gate. Primitives exist, not wired to a surface. 🎨
- **News / plural-stance source diversity** — 105 verified `enabled:false` rows filling Caribbean/Pacific/sub-Saharan/Central-Asia/MENA gaps; dedup `statssa.gov.za`. The `global`/`transnational` region value is ✅ **BUILT** (B12 ⏳ #621: `int`/`eu` → "Global", never fabricated); populating individual International sources with `int` is the follow-up curation. 🎨
- **De-US-centring remainder** — run the Wikidata generator for the 73 named gaps; raise the located share (≈49% of domains carry no country). 🛠
- **Content-provenance class** — ✅ found SHIPPED end-to-end (ingestion stamps `source_type` + backfill; `insights_source_types` facet; reading-diet-by-channel in `concentration.py`) — S6 verify-marks against the design doc's acceptance. 
- **Secondary-source `cited` provenance class — remaining slices** (background job at scale, denormalize `citing_source_id`, surface the citing trail, wire dormant `external_sources`). 🚧 partial
- **Law-vertical coverage — adapter-first vs breadth-first** (2026-07-24 field-feedback Session A §3, ruled: adapter-first is (a), breadth-first is (b) and gets this ROADMAP row for later): the enumeration-adapter build (`legislation.gov.uk`, `gesetze-im-internet.de`, `EUR-Lex` ELI register — act/code-level `LawDocument`s per jurisdiction's OWN official count) is **BLOCKED this session on egress** — all three endpoints are gateway-policy-denied here (confirmed via both `curl`/`WebFetch`, per the brief's own "MUST NOT ship an unverified adapter endpoint" contingency); build it on a networked machine per the 2026-07-17 law-vertical brief S6. **Breadth-first (b), the alternative/complementary direction**: a shallow track of ONE portal/gazette per country, sourced from the already-committed `configs/legal_sources_generated.yml` (225 sources across ~162 jurisdictions, per-row verification status), rather than a deep per-jurisdiction enumeration — trades completeness (the "France has 76 codes" principle) for FAST worldwide breadth. Shipped this session (A3, buildable without egress): `adaptive_track_budget` (the per-pass tracking budget scales with the watched-doc count, so whichever direction is built next won't crawl at 5/pass forever) + the AI change-summary layer (`LawRevisionSummary`, auto for UI-language-floor jurisdictions via `advance_law_summaries`, on-demand `POST /api/law/revisions/{id}/summarize` for the rest). 🎨/🛠
  - **UPDATE 2026-09-07 (PR #1023) — the ungated half of the law brief SHIPPED; the gated half is unchanged.**
    ✅ **Gazettes as streams (S7/S2):** three of the four catalog `gazette_feed` values now become a real
    `rss_url` — Georgia `matsne.gov.ge`, Vietnam `congbao.chinhphu.vn`, St Vincent `legal.gov.vc`. A feed
    carries its OWN validator-enforced tier (`gazette_feed_verification`, vocabulary `fetched | lead`),
    because the row-level `verification.status` is about the PORTAL: all four rows are `fetched` and
    Uruguay's `impo.com.uy` feed was never fetched — its own notes call it the site's generic WordPress
    news feed — so promoting on the row status would have filed Uruguayan site news as that country's
    official gazette. It ships unwired. ⚠ These three are **not collected on seeding**: `select_sources`
    admits only QUALIFIED sources, so they enter the qualification ladder first; what changed is that
    they can be *judged* at all (`trial_fetch` needs an `rss_url` or a sitemap, and a gazette with
    neither produces no evidence forever).
    ✅ **Coverage denominators (S5/S4):** the catalog's **39** dated official counts across 32 countries
    (the row above and the brief both said 27) now print beside the tracked count in
    `GET /api/diagnostics/law-coverage`, together with the **31 of 32** countries that have a known
    official enumeration and in which this install tracks nothing. **No fraction is computed** — see
    Q-LAW-1 below. The join runs only through the country a document itself states (`uk` documents say
    `gb`), never through the jurisdiction code.
    ✅ **`[pdf]` narrowing said out loud (L6's stated default, applied not decided):** with the extra
    absent — the default-install state — **63 of 275** catalog sources publish PDF only, across 54
    countries, and **6 of the 23** tracked documents are PDFs by URL (all six Timor-Leste). Both counts
    publish as floors; an install that HAS the extra is never told it is degraded.
    ✅ **Vetting board (S6):** `docs/product/LAW_VETTING_BOARD.md`, generated by
    `scripts/law_vetting_board.py` — 44 rows in four sections (2 confirmed gaps · 9 unverified leads with
    a real domain · 29 access-blocked or bot-walled · 4 recorded down). Sections 3–4 are a keyword triage
    over the catalog's own prose and the page says so. North Korea's honest-gap record was a YAML
    *comment* no tool could read; it is a domain-less `lead` row now, beside the comment.
    ✅ **Verified-present, not rebuilt:** S4b (catalog language → `LawDocument` → `Article.language`) and
    A5 (AI change summaries, auto at the `UI_LOCALE_CODES` floor + on demand) were both already shipped
    and were recorded as outstanding. That is the 3rd and 4th law item in a row to turn out
    shipped-when-read — **grep this vertical before building in it.**
  - 🔒 **Q-LAW-1 — the ruling that blocks a real coverage number.** Should each `official_count` entry
    DECLARE whether its unit counts the same objects an act/code-level `LawDocument` is? The units run
    over codes, acts, volumes, gazette issues, treaties and cases, and a volume or a gazette issue holds
    many acts; deciding that from the unit STRING is what ruling 47's extensive/intensive rail forbids.
    Recommendation: an explicit `counts_documents: true|false` on the 39 entries (a closed population,
    reviewable in the diff), after which tracked-vs-enumerated becomes computable for the entries that
    say true. Until then the report is honest but cannot answer "how much of France do we have".
  - 🔒 **Q-LAW-2 (L6) — promote `[pdf]` into the default extras, or keep the disclosure?** The stated
    default was applied, not decided. The disclosure is the right floor either way; promoting is a
    separate call about install weight (`pypdf` only).
  - 🛠 **Q-LAW-3 — the 44 vetting-board rows each want a one-word answer** (enable / adapter / honest gap
    / re-check / drop). Nothing there is scraped around: a robots refusal or bot wall is the host's
    choice, so each blocked domain is an adapter/API path or a recorded gap.
  - 🔒 **Q-LAW-4 — should the per-endpoint verification tier generalise?** `enumeration_url` (107 of them,
    none fetched by anyone) and `structured.api` / `structured.bulk` sit in exactly the position
    `gazette_feed` did. An endpoint field no test can distinguish from a URL somebody wrote down is the
    shape this vertical keeps paying for.
  - ⬜ **The other gazette feeds are still unverified and unwired** — BOE, Dziennik Ustaw, the Federal
    Register and the EUR-Lex OJ daily, named in the brief's S7. No feed was fetched by the 2026-09-07
    session; the three wired ones rest entirely on the producing session's recorded 2026-07-17 evidence.
  - 🛠 **S1 (the live enumeration adapters) is unchanged and still the gate on everything else.**
    Re-probed 2026-09-07 with per-host evidence: `pypi.org` 200 and `github.com` 400 against `000`
    (refused at the tunnel) for `www.legislation.gov.uk`, `eur-lex.europa.eu`,
    `www.gesetze-im-internet.de` **and** `legal.gov.vc`. Unchanged from 2026-08-20. **The one operator
    step:** fetch one CLML `…/data.xml` on a networked machine, run `parse_clml`, and check it clears the
    text-recovery floor with an empty `unknown_elements`. If it does, the schema assumptions hold and the
    enumeration is worth building; if not, the report NAMES what it did not understand.
- **DuckDuckGo query discovery channel** (off-by-default, per-query logging, budgeted) + Wikidata generator as a scheduled refresh. 🎨
- **Expand commodity feeds** (oil, gas, LNG, sand, cereals, sugar) — needs clearnet-verified robots-permitting sources. 🛠 · **Rare earths: DECIDED (B12) = USGS Mineral Commodity Summaries SUPPLY data** (production/reserves/net-import-reliance, explicitly not spot prices — no free spot source exists); the stats-agency + annual-supply parser is the build — ✅ **BUILT (S5.1)** (`us-usgs` + `parse_mcs_csv` + `/api/stats/minerals-supply`; supply-not-prices by construction; real fetch = operator). · S&P500-is-an-index reclassification — ✅ found done (`idx_sp500` + the commodities board excludes `index` symbols per the recorded ruling in `markets.py`).

### Manipulation cards & the civic vertical
- **FLOOD/BURY cards — remaining quality** — both cards exist; BURY gained same-language cohort scoping (B3 ⏳ #620). Remaining: the FLOOD open-class filler (the measured stoplist sweep, §"Keyword engine") + the full same-language *denominator* rescoping with ring-translation bridging (labelled follow-up). 🚧
- **Event-timed-operation card** ("October surprise" = emergence + source-laundering + agenda; needs an elections roster). 🎨
- **Elections & civic vertical** — sourced `elections` calendar (France 2027 pilot, movable-marked), curated candidate rosters with provenance, "name the shape, never prescribe". 🎨
- **Poll analysis** — a method-audit tier stack (Tier 2 transparency checklist + verbatim question display first); no composite score, non-disclosure outranks disclosed-imperfection. 🎨
- **Evidence-tiered cards — remaining** (power-style "what's missing" inversions; Benjamini–Hochberg once p-values exist; card-diagnostics export — NOTE: dismiss-with-reason appears SHIPPED in the 2026-07-03 batch-E commit; verify-first before building any of this row). 🚧 partial

### The Bulletin — the periodic corpus document
Design of record: [`docs/design/BULLETIN_DESIGN_2026-07-31.md`](design/BULLETIN_DESIGN_2026-07-31.md)
(21 sections, 17 maintainer rulings). Build order §21 steps 1–9 ✅ **SHIPPED** (2026-08-01,
PRs #819–#832), extended 2026-08-11/12 — 19 modules in `src/bulletin/`, ~17 ledger rows.
Surface: Settings → Advanced → *Bulletin* (folded, last).
- **Layer A — the deterministic record** ✅ — half-open periods that tile (daily→yearly), a masthead that states the lens (contributing sources, top-3 share, language and country split, days-with-ingest, corpus share), and eight sections: rising concepts · across channels · country coverage · by topic tag · changes of record · alerts · through time · cards. Every section prints the window it actually used, and every exclusion is counted rather than dropped. No model anywhere in it.
- **Layer B — the removable narration** ✅ — a local model writes one paragraph per story cluster; every sentence is checked against the article text the model was shown and dropped if it names a figure or entity that is not there. A paragraph that loses sentences says so; a story that loses all of them falls back to Layer A's own counts and is *not* labelled AI-derived. Turning it off leaves a complete document.
- **The evidence archive** ✅ — owner-only, on demand: every article a figure was computed over, so the counts can be recomputed rather than trusted. Plaintext leaving an encrypted store, disclosed as such.
- **The annexes bundle** ✅ (2026-08-11) — one click yields the report plus a ZIP of one file per cited article, where the report's `[0007]` and `..._Article_0007.md` are guaranteed the same article (one deterministic numberer, called by both the renderer and the bundle builder). Three different dates from three different facts: the bundle takes the creation day, each article file its own publication day, an undated article is named `undated_`.
- **Written in the UI language** ✅ (2026-08-11/12) — a server-side translation layer keyed on the English sentence; 11 locales × 347 entries, mechanically verified complete. A missing translation renders English *and is reported*; a translation whose placeholders differ from its frame is refused rather than printed with a stray brace; copies of the English are counted apart from coverage, so a catalog of copies cannot report itself complete.
- **REMAINING** — the §14 Layer-B `BackgroundJob` with a persisted cursor (narration runs inline today: right for a bounded story cap, wrong for a long run) ⬜ · §18's export-privacy enumeration before a first evidence archive leaves a machine 🔒 · four of the five §20 open questions (section list · introduction · mail sending · review-screen UX) 🔒 · a maintainer click-through of the Settings section and review screen 🛠 (every frontend slice shipped browser-unverified per fork-3) · the §6.3 time budget still rests on a guess until `/llm-bench` is run on a GPU machine and a slow one 🛠.
- **Open question 4** — whether Layer A should be available *below* the hardware gate (a GPU-less operator is currently denied even the deterministic document). It is ONE constant with exactly one read (`src/bulletin/gate.py:LAYER_A_REQUIRES_CAPABLE_HARDWARE`, pinned by a test that counts the reads), so answering it is a one-line change, not an audit. 🔒

### Convergence, watches & alerting
- **New Home producers** — "Converging now" (`space_time_convergence`) + "watch-rules fired" (`watch_matches`) ✅ exist and register; the TWO missing are now ✅ **SHIPPED (S6.4)**: **`on_the_horizon`** (an upcoming agenda date ∩ a currently-trending keyword; bucket watch) + **`through_time`** (anniversary lens: articles published on today's date in earlier years; bucket context; cross-time recall sacred). Neither promoted into an urgent alert (the ruled boundary). 🚧→✅
- **Severity-tiered local alert layer** — ✅ SHIPPED (`src/analytics/alerts.py` + the Home strip; "urgent" = provider-declared ONLY, never a promoted count — the ruled no-escalation boundary). Extension (tag-family spike input, capped at watch/info) → S6.4. 🚧
- **Hazard providers beyond the two** (⏳ #1030 verified the gap; not built) — `src/hazards/parse.py`
  covers **USGS and GDACS only**. Designed and unbuilt: **NWS · ReliefWeb · FEWS NET · EONET · WHO**,
  the **nuclear/radiological urgent tag-family** rule, and relaying official short-horizon forecasts
  WITH provenance. Two constraints carry over unchanged: `_hazard_tier`
  (`src/analytics/alerts.py:71`, *not* under `src/hazards/`) keeps the no-promotion rule — a magnitude
  is a provider-declared BAND, never urgency — and a parser must never be written against a payload
  shape nobody has seen. Every one of these hosts is CONNECT-refused from the build sandbox, so this
  is a 🛠 networked build: capture a real response first, then write the parser against it. ⬜ / 🛠
- **Space-time scenario cards** — disputed-chronology, story-propagation, supply-chain-ripple ✅ SHIPPED (2026-07-03, `tests/test_scenario_cards.py`); remaining: silent-disasters + law-takes-effect (codeable → S6.9 stretch) · news-desert atlas + election-window desk (external baselines/roster — 🛠 operator-gated). 🚧

### Versioned sources as first-class Articles — Wikipedia + laws (maintainer-directed 2026-07-10, future version)
The headline revamp (full design in [`FUTURE_DEVELOPMENTS.md`](FUTURE_DEVELOPMENTS.md) →
"Versioned sources as first-class Articles"; **gated on the P0 scale set — do not start before it lands**):
- **All Wikipedia articles of all UI-language editions auto-ingested as first-class `Article`s** — full
  pipeline (keyword engine + date extraction + When×Where×Who + sentiment), metadata linking to the
  original source, exactly like any scraped article. Bulk mechanism = **dump-as-baseline + `recentchanges`-delta**
  (not per-article scraping — won't scale to ~6M+/edition). 🎨 scale-critical
- **Track-change / version history as a per-article linked layer** keyed by `article_id` — the same pattern
  as a synthesis/translation via `ArticleAnalysis`. Generalize `WikiRevision`/`LawRevision` into this layer. 🎨
- **Country LAWS get the identical treatment** — promote `LawDocument` to a first-class Article
  (keywords/metadata/dates), with `LawRevision` as its linked audit trail (today laws are a separate
  tracked vertical that does NOT flow through `index_article`). 🎨
- Prior sub-items folded in: dumps → corpus ingestion path · edition-wide auto-track after a dump download
  (the 2026-06-12 superseding ruling, now the plan of record) · a dedicated tracked-changes tab ·
  auto-watch all 12 UI editions · Wikipedia tab → Settings · agenda ↔ wiki linking. 🎨
- **2026-09-07 pass (prompt 18) — two shipped, one measured stop.** ✅ The **version anchor**
  (`Article.source_revision`: which upstream revision an article's stored TEXT came from, for both the
  watched-page sync and the dump ingest) and the **reader's way into the history** (the tracked-changes
  view was already built but reachable only from Settings; the reader now states the version and links
  the local history when this machine holds one). ✅ The **consented "Refresh exact sizes"** retires the
  unconsented per-edition probe button. ✅ The wiki strip's **K·N regex bomb** (13.4 s per 400 KB of
  unclosed-`<ref>` spam, on the ingest path) fixed through a shared linear scanner. 🚧 **Whole-edition
  ingest stopped at the seam with its gate MEASURED:** three of the five `STORAGE_5TB_PLAN.md` §9 steps
  preceding it are unbuilt and four of the six §8 rulings unruled. **G10 is two questions, not five** —
  Q2/Q3/Q4 were answered on 2026-06-12 and Q3 shipped the same day; Q1 (ingest scope) and Q5 (backups)
  remain open. 🚧

### UI / UX & onboarding
- **"Database size" shows EVERYTHING** — ✅ **BUILT** (A12b backend ✅ + B14 display ⏳ #625): the Library + System-tab "Storage footprint" panels render the all-stores total (db/wal/wiki/OSM/staging/**Ollama store outside data_dir**) with the private-vs-re-downloadable split visible; lazy-measured + cached, never on the poll. Remaining 🛠: click-through.
- **Library evolution graphs + the hourly snapshot recorder** — ✅ SHIPPED (2026-07-23 S2 + 2026-07-24 A5 + 2026-08-01 rulings 9–10): `/api/library/history` over `StatSnapshot` (infinite retention; `articles_per_hour` derived live from `created_at`), per-tile 7d/30d/90d/All window switcher, hide-flat tiles, the 4-line source-qualification tile with auto-log10, the **five-view subtab restructure** with loaders firing on subtab SELECT (never on tab open), and the **ingest-rhythm heatmap** (weekday × hour; unobserved slots rendered distinctly from real zeros). Remaining 🛠: browser click-through.
- **Chart axis honesty (toolkit-wide)** — ✅ SHIPPED (2026-08-01 ruling 10): `honestTicks` replaces the `(max−min)||1` span fallback in BOTH renderers, so a flat series gets one true tick instead of a fabricated 23/23.5/24, a count axis never prints a fractional count, time labels take their granularity from the plotted span and de-duplicate by TEXT, `n=` carries its unit, count series get a true zero base and a neutral colour, and the fixed-px ooChart canvas (the graphs-overflow-their-box vector) sizes to its container.
- **Home dashboard + "Latest in your corpus"** — ✅ verified SHIPPED (B8: `/api/insights/latest` + `src/analytics/latest.py` with user-set-and-seen gates, near-dup collapse, script-aware length; `#home-latest-panel` + trends + recent-by-tag). Remaining: the **synthesized-Leads carousel** (pausable/a11y — the one deferred nicety). 🚧
- **Clickable in-article keywords — stats hover** — ✅ verified SHIPPED (B9: `keyword-stats` endpoint + reader/SPA #oo-tip hovers; mentions · spread · windowed trend rate · top co-occurrences, counts-only).
- **Editable keybindings panel** — ✅ verified SHIPPED (B11b: Settings → Shortcuts).
- **Remove the Insights search bar** — 🔒 gated (B11a / H3, re-confirmed live 2026-09-07: `#ins-term` and `exploreTerm` are still wired): first verify the omnibar Enter→analysis-window fully absorbs `exploreTerm()`'s 4-endpoint view (trend + associations + context + mindmap); a browser-unverified removal risks losing a tool (the Desk lesson). The hide is additionally blocked by INTERLEAVING, not just absorption: `#ins-explore` mixes the retirable search bar with a NON-searchable corpus-landscape that must stay and with the shared `#mm-kit`, which relocates into the corpus window and back. A blind `display:none` is the interleaved-shared-component hazard. Port, guard the absorption, then hide — with a browser open.
- **Guided-setup wizard remaining slices** — the **sources-by-theme step shipped (S4.7, 2026-07-12)**: real tag taxonomy via loopback `/api/scheduler/coverage`, themes default-all (cover-everything), language emphasis → `language_equilibrium`, loopback config write, never egress. The encryption-choice step is on **unlock.html** (chosen pre-DB at first launch), so it is architecturally moot in the post-unlock wizard. Remaining: a country-emphasis picker (`country_priority` lever exists) + browser click-through. 🚧
- **Onboarding & training** — first-run tour as dismissible Home cards + contextual "why" notes + a supervised training curriculum (in-repo, never hosted). 🎨
- **First-launch data-location chooser** (*lifted 2026-09-07 from `docs/design/FIX_SESSION_PROMPT_2026-07-14.md` Slice 2, where it was the only live record*) — maintainer-asked 2026-07-14: default = the app data folder, or "choose a folder" in which an **"OOS data"** subfolder is created; decided at first launch AFTER language + legal acceptance and BEFORE the passphrase. Reuses the shipped A11 `OO_DATA_DIR`/`oo.env` persistence seam, with an honest writable / free-disk / tmpfs preflight. Verified 2026-09-07: nothing in `unlock.html` or the setup path offers this today. 🎨
- **i18n long tail** — the 44 new B5/B14/B15 strings are keyed ×12 (B10, #629) ✅; **composite-string format support** (`OOI18N.tf` template + interpolation) **and server-built Home-card title translation** (design + first producer) **shipped (S4.5, 2026-07-12)** ✅ — `Card.title_i18n`/`title_vars`, `rising_now` the reference producer, the template key in all 12 locales. Remaining: extend translatable titles to the other producers + key more dynamic JS rows via `tf` + the chrome tail, MEASURED 2026-09-07 rather than estimated — **557 untranslatable UI strings and 297 unkeyed `t("…")` call sites, both ratchets at ZERO SLACK** (`ci.yml`), so any new `title=`/label/paragraph reddens CI unless it is keyed in the same commit. Known specifics: the eight `guis/` skins are outside the gate's scope entirely; `reader.js` calls `t()` zero times; the `{action} failed: {error}` template was considered and REJECTED in favour of full-sentence keys (do not re-propose it); the uninstall dynamic preview/confirm dialogs stay English (PRH-19). Lower a ratchet in the same PR that frees the slack. 🚧 ongoing
- **Human click-through of all browser-unverified UI** — now including the whole B wave (B3/B5/B14/B15 + storage panels + backup dialogs). 🛠

**The browser-verified UI burn-down (prompt 15) — what is left after PR #1029.** The type
scale (PRH-32), dialog theming and the three Library labels (PRH-33) shipped 2026-09-07,
Chromium-verified on all 17 themes. The rest of that prompt is untouched and is tracked here
so it is not re-derived from the prompt file each time:
- **`var(--line)` is defined nowhere the SPA loads — 41 fallback-less references** across ten
  files. A `var()` with no fallback that resolves to nothing voids its WHOLE declaration, so
  each does nothing: measured, all eleven dialogs' declared border computed `0px none`.
  Ratcheted (`tests/test_dialog_theming.py`) so nothing new lands. 🔒 **ruling-gated — the
  question is simply whether those 41 borders were ever wanted**; if yes the repair is one line
  plus a browser pass, if no the declarations should be deleted rather than left looking like
  styling. Full measurement in `docs/ledger/OPEN_QUEUE.md`, 2026-09-07.
- **The five axe-core P2s** from the 2026-08-20 matrix §11.1 — Home card-back chip/tier-badge
  contrast · agenda inline-link distinguishability (a convention decision) · `.an-tab`
  nested-interactive · the tasks top bar's grounds (`#llm`, `#tm-conn`, `.muted`) · reader
  `.deduced > h3` / `.dup-pill`. 🛠
- **No layout media query between 900 px and desktop** — `max-width:900px` is still the widest.
  🎨
- **~590 inline `on*=` handlers** (~331 in `index.html`, ~259 across the `app-*.js` modules)
  against ~103 `addEventListener`. This is what blocks a nonce-based CSP; `'unsafe-inline'`
  stays in `script-src` until it is paid down. The ledger's recorded "295 as of 2026-06-15"
  counted `index.html` only and predates the module split. Do it in bounded passes with
  byte-parity discipline — a green walk does not prove each of 590 handlers works when clicked.
  🚧 browser-gated
- **Dead UI, deleted with a browser open** — the retired temporal-map cluster (`loadTimemap`,
  `renderTimemap`, `showTmapDetail`) is unreachable but INTERLEAVED with live helpers `ooMap`
  still uses (`kindColor`, `TMAP_KINDS`, `fmtYear`, `fmtDate`, `dateToT`, `lon2x`/`lat2y`,
  `tmapFindCoverage`); a wrong deletion passes `node --check` and breaks the map at runtime.
  Also the retired `#corpus-win` modal, the orphaned `loadIndicesData`/`loadMarketData`, the
  orphaned `#onboard` locale keys, and **PRH-14**, the unwired `#vitals-pop` popover, which is
  in the tree and absent from the recorded dead-UI worklist. Do NOT delete `firstRun` — it is
  test-pinned and intentionally retained. 🛠 browser-gated
- **PRH-31 — `_window_daily_series` omits zero-count days**, so the index axis compresses (day 1
  and day 5 render adjacent). Re-confirmed live 2026-09-07 at `src/analytics/queries.py:1714`,
  with `app-corpus.js:1293` carrying a comment that acknowledges the omission. The repair is
  zero-FILLING (for keyword mentions an absent day is a real zero, never a null) and it touches
  the trending sparklines. 🚧
- **Backends with no surface** — Leads 2.0 grading on Home (evidence chips, a sort control wired
  to `sort_leads` with the `explain_order` hover, lifecycle deltas — browser-gated because it
  visibly reorders the flagship feed) · the Conjunction-lens deeper views (conditional trend,
  vocabulary contrast, per-article intensity, lead/lag — needs a payload extension) · the
  subjectivity reader highlight panel (spans are emitted, nothing renders them) · corpus facet
  filters in the Articles subtab, with an id-seeded corpus INTERSECTING rather than clearing on
  refine · eleven unwired `ooViz` primitives (note the recorded correction: the namespace is
  **`ooViz`**, not `ooviz`, and a case-sensitive grep for a name you did not read out of the
  file is not evidence of absence) · **L5**, the `_SPARSE_BAR_MAX` reach decision for
  `commodityOverlaySvg` / `ringDumbbellSvg` / `ooDonut`. 🚧
- **The 2026-07-22 GUI report's residue** — three P1s still open (the Home glance strip mixing
  languages; Lead titles frozen in the locale they first rendered in — the interpolated-`tf()`
  class, where an already-interpolated string is no longer a key, so a render-once surface must
  register with `oo:langchange`; unsegmented zh keywords on the Insights map). **Its P2 tier was
  never closed** — 12 open, 8 partial, 5 unchecked — although a `shipped.csv` row describes that
  report as closed out; correct the row and work the tier. 🚧
- **L2 — settle the verification bar.** Every stamp currently reads "Chromium-verified (remote
  sandbox) · awaiting human UX pass". The 12-locale sweep covers four; rule 9 (adversarial
  screenshot reading) has never run; the Gecko/AppVM bar has never been met. Whatever L2 rules,
  make the stamp mean one thing and apply it consistently. 🔒 ruling-gated

### Network / transport / Tor
- **Reliable Tor & per-source transport** — optional in-app Stem-controlled `tor` process; per-source circuit isolation by default; clearnet-for-Tor-hostile sources only as an explicit consented per-source opt-in. 🎨
- **OS-layer network kill** (`oo-netcut`, opt-in, privileged, interface-agnostic firewall drop-all + `ip link down` + rfkill; Windows/macOS behind one helper). 🎨
- **Continuous-collection remainder** — the first-run country/language emphasis picker + an explainable "which country next & why" schedule panel (background auto-collect + stratified interleave already shipped). ⬜

### Weather / IPCC / lunar
- **Open-Meteo remainder** — *the VERIFY-FIRST this row asked for was done 2026-09-07 (⏳ #1030);
  here is the answer, so nobody re-derives it.* **Signal-keywords: BUILT** —
  `src/analytics/weather_signals.py` derives `kind="signal"` rows from explicit threshold rules into
  a SEPARATE store (its own design note says why it is not the keyword table), read by
  `/api/signals`. **Anomaly baselines: half-built and honest about it** — the module carries the
  anomaly-vs-stated-baseline structure and names the baseline, then publishes the gap ("Not yet
  checked against a baseline: confirming an anomaly requires the consented Open-Meteo reanalysis
  fetch"), so it is 🛠 operator-gated rather than unwritten. **Still absent:** the reader
  weather-context row (no weather reference in `app-corpus.js` / `app-library.js`) and the temporal-map
  overlay. 🚧
- **IPCC as a source + prediction-tracking** — PDF-to-text ingest, predictions as first-class dated claims, a retrospective promises-due lens. 🎨
- **Lunar-effects testing framework** — ✅ **BUILT AND WIRED END TO END** (re-measured 2026-09-07,
  ⏳ #1030; this row read "partial" and understated it): `src/analytics/lunar.py` correlates any
  stored daily series against the moon's illuminated fraction, with Benjamini-Hochberg FDR
  (`src/stats/fdr.py`) **mandatory** on a screen and a DETERMINISTIC circular-shift permutation test
  (no scipy, no RNG) that preserves the autocorrelation of both series; correlation-is-not-causation
  on every result and the null outcome named as the expected one. Served by
  `/api/insights/lunar-correlation` and drawn by `app-insights.js` `loadLunar()` with limit and
  `fdr_q` controls. **REMAINING: only the pre-registration hypothesis UI** — the screen exists,
  "declare what you expect before you look" does not. ✅ / ⬜ pre-registration

### Self-update, portability & voice
- **App self-update** (default OFF) — check → signed backup + snapshot → verify → staged migrate → atomic swap + rollback. 5 open questions (channel, trust root, cadence, curl\|bash vs git, mirror-anchoring). 🎨
- **Universal portability** — single-source Python installer (`install.sh` + `install.ps1` wrapping uv), a GitHub Actions release matrix (+ notarization/signing decision), a PWA layer. Win/mac de-scoped from the alpha. 🎨
- **Voice-only mode** — push-to-talk consent surface, spoken informed-consent + repeat-back, local STT/TTS via the Ollama path, measured hardware tiers. 🎨

### The Open Commons Mirror (sister project — NOT this repo's work)
Server-scale preservation of **public** open data (archive.org-scale), a separate repo/fork
created only once this project is mature. Tamper-evident/tamper-resistant architecture
(content addressing, RFC-6962 transparency logs, LOCKSS replication, OpenTimestamps
anchoring), Node 0 = the maintainer's own machine. **User corpora never touch the mirror.**
8 open maintainer questions recorded. 🎨

### Structural debt — measured 2026-08-04, deferred by ruling

Recorded, not scheduled. Measured during the 2026-08-04 critical review; none is a defect on
its own, and all three are the kind of change this project's own rules say not to attempt
without a browser and a runnable suite in the same session.

| # | Item | Measurement | Why deferred | What would unblock it |
|---|---|---|---|---|
| S-1 | `src/api/diagnostics.py` holds **108 routes / 150 functions in 5,276 lines** — 18 % of the app's 607 endpoints in one module | 108 `@router.*` decorators; next-largest router is `insights.py` at 70 | A split touches the all-diagnostics bundle, its completeness ratchet, and the tests that slice this file by source anchors | `tests/js_source_helper.py` landing first (done 2026-08-04), so anchor-based tests survive a move |
| S-2 | **1,865 function-level `from src.…` imports across 241 of 445 files (54 %)**; only 49 carry a circular-import comment | grep of imports indented ≥4 spaces | Cannot distinguish deliberate lazy-loading (deferring `duckdb` via `columnar` serves the lean-boot goal) from undocumented cycle-breaking without resolving each | An import-graph probe reporting true cycles, so the legitimate lazy imports can be annotated and the rest hoisted |
| S-3 | ~~a single 23,896-line indented global scope~~ **DONE 2026-08-20** — `src/static/app.js` is now **17 ordered modules**, split with byte-identical concatenation and verified in a browser | seam map, evidence and the measured numbers: [`docs/design/APPJS_DECOMPOSITION_2026-08-20.md`](design/APPJS_DECOMPOSITION_2026-08-20.md) | — | — |

| S-4 | **233 hand-rolled source-slicing sites** across the test tree, and **588 UI strings / 307 `t()` literals** with no `en.json` key | AST walk in `test_source_slicing_discipline`; `i18n_report.py --audit-chrome` | None is a defect — each is real debt now *measured* rather than invisible, and each is held by a ratchet that may only fall. The slicing sites were reported as **0** until 2026-08-04, when the detector turned out to be keyed to five helper names | Ordinary attrition: migrate a slice to `tests/js_source_helper`, or key a string ×12, and lower the ratchet in the same PR — the tooling prints the new floor |

| S-5 | **`natural-earth-geometry` carries a BLANK `sha256` in the external-artifact registry** — `configs/external_artifacts.yml` pins `{path: src/static/world_countries.json, sha256: ""}`, so the freshness check confirms the file EXISTS and never that it is the file we vendored (*lifted 2026-09-07; it was recorded only in PR #976's body*) | one entry, one field | Not deferred by ruling — simply never done. Its sibling `vendored-alpine` entry received exactly this one-line fix on 2026-08-22 and its own comment states the reason: *"a BLANK pin left this entry at status `info` ('present') … filled, drift now reports `stale`"* | Measure the digest from the committed file and fill the pin — a real measured value, never a fabricated one, and then `last_verified` moves with it |

**Note on S-4 (2026-09-07).** Both JS i18n ratchets currently sit one slot above the real
count — `--max-untranslatable` 560 against 559, `--max-unkeyed-t-calls` 297 against 296. The
slack arrived with ordinary attrition on `main`, not with any one branch, and it was flagged
rather than silently reclaimed inside a merge commit: tightening it would redden any in-flight
branch that legitimately adds a string, and this repository merges several in parallel. It is
still a free slot for the next drift to land in unseen, so lower it in a PR that owns the
change — the tooling prints the new floor.

**Honest note on S-3 (closed 2026-08-20).** The row is done, and the premise it was written
around — "the real cost is parse/compile on the 2-core field VMs" — turned out to be **half
right, for a reason the row did not name**.

Measured with Chrome's own `Performance.getMetrics`, interleaved A/B, fresh context per load,
both sides serving byte-identical JavaScript (the split side in fact ships 20,812 bytes *more*):
**−38.8 %** main-thread script time on a 6×-throttled 4-core profile, **−17.5 %** with the
browser pinned to two cores, and **+21.6 % — i.e. 14.8 ms slower — with no throttle at all.**
An A/A control lands inside noise, an order swap flips the sign, and a second server on a second
worktree reproduces it, so the effect is real and belongs to the tree.

It is not "less to parse", because the bytes are identical. It is compile work moving off a
throttled main thread onto background threads the throttle does not reach — which is why it
inverts on a fast machine and why it shrinks as cores do. The claim worth carrying forward is
narrow: **roughly a sixth off script time on a weak CPU, a little worse on a fast one.** The
larger, genuinely retired debt is structural: 23,896 lines in one indented global scope is not
reviewable, and now it is seventeen named modules with a duplicate-name guard across them.

Lazy loading — a tab's module fetched on first visit — is the change that would cut bytes rather
than relocate work, and the decomposition is its prerequisite; it is now cheap to try one module
at a time.

The original note still stands: `defer` on the script tags buys little — they already sit at the
end of `<body>`, so they do not block first paint. `guis/boot.js` in `<head>` *is*
render-blocking, but it is 6 KB and exists to avoid a flash of the default skin — that trade is
correct.

**Related, and awaiting a ruling:** the ledger's own size is measured and proposed on in
[`docs/design/LEDGER_RESTRUCTURE_PROPOSAL_2026-08-04.md`](design/LEDGER_RESTRUCTURE_PROPOSAL_2026-08-04.md)
— `CLAUDE.md` is ~215k tokens and rule (1) requires reading it in full every session.

---

## 5. Maintainer rulings — outcome board (reconciled 2026-07-11)

> The 2026-07-10 delegation ("1a 2a 3a 4a") sent most of these into the parallel A+B wave.
> Outcomes below; each executed decision is recorded in `CLAUDE.md`.

**Executed by the wave:**
1. **zh/ja/th segmenter + stoplists** — ✅ **EXECUTED (B1)**: jieba/janome/pythainlp via the `[segmentation]` pip extra + ko/vi/mr (and more) stoplists vendored. 🛠 remaining: live-corpus re-index + measured junk reduction.
5. **Keyword hover-stats** — ✅ **RESOLVED (B9)**: found already shipped with exactly the recommended counts-only set.
8. **`global`/`transnational` region value** — ✅ **BUILT (B12** ⏳ #621): `int`/`eu` → "Global"; follow-up ✅ **DONE (S5.5)**: 22 unambiguous transnational bodies (UN/IGO/EU institutions) hand-verified + tagged `int`/`eu` in the catalog (G7/G20-News dropped — `g7uk.com` is national); reviewable record in `docs/ledger/int_country_curation_2026-07-12.md`.

**Decided → BUILT-AWAITING-DATA (S5):**
3. **Rare-earths** — ✅ **BUILT (S5.1)**: USGS Mineral Commodity Summaries SUPPLY parser (production/reserves/net-import-reliance, explicitly NOT prices; enforced by construction, skeptic-hardened) + `us-usgs` agency + `/api/stats/minerals-supply` + a Markets panel. ⏳ the REAL MCS data fetch is a networked **operator** step.
9. **Multilingual sentiment** — ✅ **BUILT (S5.2)**: the rule-based subjectivity/loaded-language engine (per-language lexicon files, descriptive components + spans, honest gaps, script-mismatch guard) feeding the manipulation card + a deduced per-article surface; seed lexicons ×3 scripts. ⏳ the REAL vetted license-clean lexicons are an **operator** sourcing/vetting step (VADER investigated + NOT reused — valence ≠ subjectivity).

**Attempted, honestly blocked:**
2. **httpfs crypto-extension bundling** — the fetch hit the network egress allowlist (403 on `extensions.duckdb.org`); **no checksum fabricated**, in-memory fallback stays. Needs a networked machine or an allowlist entry. 🛠 (see DB-3)

**Still with the maintainer:**
4. **`v0.2.0` tag** — ✅ DONE (the maintainer ran the P0 live-corpus validation and tagged; 0.3 opens the measured-&-verified cycle).
6. **Lemmatization default-on** — ✅ RULED default-ON 2026-07-18: the maintainer's live-corpus `lemma_preview` precision review (35 groups / 71 keywords, clean) was the coherent gate — per the recorded correction, the IR A/B never was, for a display-layer change. Execution delegated (`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-18_LEMMA_DEFAULT_ON.md`); the graded IR gold set remains wanted for the separate BM25F retrieval decision. 🛠
7. **Retention / eviction posture** — decide after the storage-footprint numbers from the next field export are in. 🔒
- **Import checkpoint interval K** (*added 2026-09-07; not part of the 2026-07-10 delegation, hence unnumbered*) — the mechanism shipped at its no-op default of 1; the number is the ruling. Trading durability for time is not a decision the code can make for the operator, and this operator has killed the import twice. Recommendation on record: **3**. See §4 (Backup, import / export) for the mechanism and `docs/ledger/OPEN_QUEUE.md` for the full entry. 🔒

---

## 6. Version policy & shipped work

Development cycles are named after the version they produce (`0.09 → 0.1 → 0.2`; branch renamed
to match at each flip). The version is single-sourced from `pyproject.toml`. What already
shipped is tracked as rows in [`docs/ledger/shipped.csv`](ledger/shipped.csv) (index) with
verbatim detail + reusable lessons in [`docs/ledger/SHIPPED_LOG.md`](ledger/SHIPPED_LOG.md);
release notes are in [`docs/CHANGES.md`](CHANGES.md). Binding rulings are in
[`../CLAUDE.md`](../CLAUDE.md) and the live Open queue in
[`docs/ledger/OPEN_QUEUE.md`](ledger/OPEN_QUEUE.md) (split out 2026-09-07, ruling A3) — this
board is a readable summary of them, not a replacement.
