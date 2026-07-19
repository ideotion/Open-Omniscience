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
| **P1.2** | Job-ify heavy sync handlers (enrich-source-types 8.5 min · governments 2.9 min · diagnostics `/all` 36 min — all background jobs now; heavy reads guarded) | ✅ largely shipped — **S2.4 sweep (2026-07-12): `corpus-www`/`corpus-sentiment` CONFIRMED already `_deadlined`**; the sweep then guarded the previously-raw corpus-scaled reads — the 8 raw insights endpoints (who/where/convergences/ring-countries/source-laundering/recycled-claims/reading-diet-by-type/keyword-tags-keywords), the 6 cache-only ones upgraded to `_deadlined` (4 manipulation cards + source-types + map-coverage), the per-keystroke `omni` (degraded-not-429 so the omnibar never blanks), and the link OOM-risk endpoints (stats/top-cited/articles-by-link/citation-graph whole-table materializations, now deadline-bounded). **Carry-over** (on-demand, not polled — lower snappy priority): `source_io/sources` (real fix = a maintained per-Source counter), `framing` (cap only), `monitoring/anomalies` + `commodity/correlation` (grouped-SQL rewrite), `link/corpus`+`shared` (already corpus-bounded via `_resolve_corpus` cap). |
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
- **Lemmatization default-on** — `OO_FAMILY_LEMMA` (73 of top-500 would merge) — stays measure-gated on the maintainer-made gold set (re-confirmed by ruling 3a execution). 🔒
- **Keyword-log-driven catalog pruning** as a repeatable workflow. 🛠 operational

### Backup, import / export & data-safety
- **Backups include downloaded Wikipedia dumps** — dedup-by-checksum, additive restore must place FILE members into `wiki_dumps`. 🎨 (reverses design D3)
- **Remove the legacy single-file backup RESTORE** once the format is fully retired (keep the additive-merge engine). 🎨
- **Unified Import + unified Export/Backup dialogs** on the streaming-volume path — shipped earlier; the B5 wave (⏳ #624) added job-state-as-truth polling, the paused-state label and verify/pause-resume wiring. Remaining: click-through 🛠 + key the new strings ×12. 🚧
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
- **3D keyword explorer** — formally **DEPRIORITIZED** (ruled 2026-07-13, Q5a; supersedes the 2026-06-16 "do NOT defer the 3D"). The 3-level mind-map (Keywords/Families/Super-groups) stays as-is. ⬜

### Agenda & calendars
- **Eclipse canon** from a bundled public table (moons + seasons already shipped). 🎨
- **Deduced events as first-class agenda entries** with keyword links (RC-blocking-era item). ⬜
- **Worldwide calendar preloads** — bank holidays; Islamic computed with the ±1-day caveat; Hindu/Buddhist from sourced tables; fix Christian-centring. 🎨
- **One recurrence model** (RULE + dated INSTANCES + `since:` origin year) · **month-span events** ("Dry January") · **full iCal import** · **saved-filter "smart calendars"** · **catalog depth flood** (elections/summits/central banks/courts/UN days) · **agenda i18n** · **temporal-map player speeds** 0.05×–16×. 🎨

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
- **DuckDuckGo query discovery channel** (off-by-default, per-query logging, budgeted) + Wikidata generator as a scheduled refresh. 🎨
- **Expand commodity feeds** (oil, gas, LNG, sand, cereals, sugar) — needs clearnet-verified robots-permitting sources. 🛠 · **Rare earths: DECIDED (B12) = USGS Mineral Commodity Summaries SUPPLY data** (production/reserves/net-import-reliance, explicitly not spot prices — no free spot source exists); the stats-agency + annual-supply parser is the build — ✅ **BUILT (S5.1)** (`us-usgs` + `parse_mcs_csv` + `/api/stats/minerals-supply`; supply-not-prices by construction; real fetch = operator). · S&P500-is-an-index reclassification — ✅ found done (`idx_sp500` + the commodities board excludes `index` symbols per the recorded ruling in `markets.py`).

### Manipulation cards & the civic vertical
- **FLOOD/BURY cards — remaining quality** — both cards exist; BURY gained same-language cohort scoping (B3 ⏳ #620). Remaining: the FLOOD open-class filler (the measured stoplist sweep, §"Keyword engine") + the full same-language *denominator* rescoping with ring-translation bridging (labelled follow-up). 🚧
- **Event-timed-operation card** ("October surprise" = emergence + source-laundering + agenda; needs an elections roster). 🎨
- **Elections & civic vertical** — sourced `elections` calendar (France 2027 pilot, movable-marked), curated candidate rosters with provenance, "name the shape, never prescribe". 🎨
- **Poll analysis** — a method-audit tier stack (Tier 2 transparency checklist + verbatim question display first); no composite score, non-disclosure outranks disclosed-imperfection. 🎨
- **Evidence-tiered cards — remaining** (power-style "what's missing" inversions; Benjamini–Hochberg once p-values exist; card-diagnostics export — NOTE: dismiss-with-reason appears SHIPPED in the 2026-07-03 batch-E commit; verify-first before building any of this row). 🚧 partial

### Convergence, watches & alerting
- **New Home producers** — "Converging now" (`space_time_convergence`) + "watch-rules fired" (`watch_matches`) ✅ exist and register; the TWO missing are now ✅ **SHIPPED (S6.4)**: **`on_the_horizon`** (an upcoming agenda date ∩ a currently-trending keyword; bucket watch) + **`through_time`** (anniversary lens: articles published on today's date in earlier years; bucket context; cross-time recall sacred). Neither promoted into an urgent alert (the ruled boundary). 🚧→✅
- **Severity-tiered local alert layer** — ✅ SHIPPED (`src/analytics/alerts.py` + the Home strip; "urgent" = provider-declared ONLY, never a promoted count — the ruled no-escalation boundary). Extension (tag-family spike input, capped at watch/info) → S6.4. 🚧
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

### UI / UX & onboarding
- **"Database size" shows EVERYTHING** — ✅ **BUILT** (A12b backend ✅ + B14 display ⏳ #625): the Library + System-tab "Storage footprint" panels render the all-stores total (db/wal/wiki/OSM/staging/**Ollama store outside data_dir**) with the private-vs-re-downloadable split visible; lazy-measured + cached, never on the poll. Remaining 🛠: click-through.
- **Home dashboard + "Latest in your corpus"** — ✅ verified SHIPPED (B8: `/api/insights/latest` + `src/analytics/latest.py` with user-set-and-seen gates, near-dup collapse, script-aware length; `#home-latest-panel` + trends + recent-by-tag). Remaining: the **synthesized-Leads carousel** (pausable/a11y — the one deferred nicety). 🚧
- **Clickable in-article keywords — stats hover** — ✅ verified SHIPPED (B9: `keyword-stats` endpoint + reader/SPA #oo-tip hovers; mentions · spread · windowed trend rate · top co-occurrences, counts-only).
- **Editable keybindings panel** — ✅ verified SHIPPED (B11b: Settings → Shortcuts).
- **Remove the Insights search bar** — 🔒 gated (B11a): first verify the omnibar Enter→analysis-window fully absorbs `exploreTerm()`'s 4-endpoint view (trend + associations + context + mindmap); a browser-unverified removal risks losing a tool (the Desk lesson).
- **Guided-setup wizard remaining slices** — the **sources-by-theme step shipped (S4.7, 2026-07-12)**: real tag taxonomy via loopback `/api/scheduler/coverage`, themes default-all (cover-everything), language emphasis → `language_equilibrium`, loopback config write, never egress. The encryption-choice step is on **unlock.html** (chosen pre-DB at first launch), so it is architecturally moot in the post-unlock wizard. Remaining: a country-emphasis picker (`country_priority` lever exists) + browser click-through. 🚧
- **Onboarding & training** — first-run tour as dismissible Home cards + contextual "why" notes + a supervised training curriculum (in-repo, never hosted). 🎨
- **i18n long tail** — the 44 new B5/B14/B15 strings are keyed ×12 (B10, #629) ✅; **composite-string format support** (`OOI18N.tf` template + interpolation) **and server-built Home-card title translation** (design + first producer) **shipped (S4.5, 2026-07-12)** ✅ — `Card.title_i18n`/`title_vars`, `rising_now` the reference producer, the template key in all 12 locales. Remaining: extend translatable titles to the other producers + key more dynamic JS rows via `tf` + the pre-existing ~105–140 chrome tail. 🚧 ongoing
- **Human click-through of all browser-unverified UI** — now including the whole B wave (B3/B5/B14/B15 + storage panels + backup dialogs). 🛠

### Network / transport / Tor
- **Reliable Tor & per-source transport** — optional in-app Stem-controlled `tor` process; per-source circuit isolation by default; clearnet-for-Tor-hostile sources only as an explicit consented per-source opt-in. 🎨
- **OS-layer network kill** (`oo-netcut`, opt-in, privileged, interface-agnostic firewall drop-all + `ip link down` + rfkill; Windows/macOS behind one helper). 🎨
- **Continuous-collection remainder** — the first-run country/language emphasis picker + an explainable "which country next & why" schedule panel (background auto-collect + stratified interleave already shipped). ⬜

### Weather / IPCC / lunar
- **Open-Meteo remainder** — anomaly baselines, deduced signal-keywords, a reader weather-context row, a map overlay (slice 1 suggest-to-fetch cards shipped; the 2026-07-03 batch-E commit mentions "weather signals" — VERIFY-FIRST what remains before building). 🚧 partial
- **IPCC as a source + prediction-tracking** — PDF-to-text ingest, predictions as first-class dated claims, a retrospective promises-due lens. 🎨
- **Lunar-effects testing framework** — correlate any daily series vs the lunar series (Pearson/Spearman + phase-bucket contrast, mandatory BH-FDR, pre-registration UI). 🚧 partial

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

---

## 6. Version policy & shipped work

Development cycles are named after the version they produce (`0.09 → 0.1 → 0.2`; branch renamed
to match at each flip). The version is single-sourced from `pyproject.toml`. What already
shipped is tracked as rows in [`docs/ledger/shipped.csv`](ledger/shipped.csv) (index) with
verbatim detail + reusable lessons in [`docs/ledger/SHIPPED_LOG.md`](ledger/SHIPPED_LOG.md);
release notes are in [`docs/CHANGES.md`](CHANGES.md). Binding rulings and the live Open queue
are in [`../CLAUDE.md`](../CLAUDE.md) — this board is a readable summary of it, not a
replacement.
