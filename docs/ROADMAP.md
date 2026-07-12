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

- `pyproject` version is **`0.2.0`**; the default branch is **`0.2`**.
- The **`v0.2.0` tag is HELD** — gated on the maintainer's live-corpus validation of the **P0
  scale set** (see §2). All four P0 engines are now shipped **including P0.4 unlock-at-scale
  (root-caused + fixed on the synthetic harness)** — the maintainer's live-corpus run is the
  one remaining gate.
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
| DB-3 | **Persisted encrypted columnar store (D1) blocked** | The bundling attempt ran (A13, ruling 3a) and hit a hard wall: `extensions.duckdb.org` is **not in the network egress allowlist** (403) — no checksum fabricated, the in-memory fallback stays. Needs a **networked machine** (or an allowlist entry) to fetch + pin the per-OS httpfs binaries; D2/D3 stay gated behind it. | 🛠 operational (was ruling-gated; ruling given, attempt blocked) | SCALE_ROADMAP Ruling-gated #2 · `PERSISTED_DUCKDB_HTTPFS.md` |
| DB-4 | **Keyword-table junk growth** | SEGMENTER SHIPPED (B1): zh/ja/th word segmentation via the optional `[segmentation]` extra (jieba MIT · janome Apache-2.0 · pythainlp Apache-2.0 — pure-local, dicts in-wheel, zero network) + ko/vi/mr (and fa/hu/…) stoplists vendored; graceful degrade without the extra. | 🔧 shipped — remaining: **install the extra + "Clean up keywords" re-index on the live corpus** to apply retroactively and measure the real junk reduction | SCALE_ROADMAP P1.5 / Ruling-gated #1 (executed) |
| DB-5 | **~120 GB of the data folder unidentified** | The instruments are now shipped: the A12 `du`-style data-dir breakdown + the A12b/B14 itemized storage footprint (incl. the external Ollama store). The mystery itself is still unnamed. | 🔧 diagnostics shipped — **awaiting the maintainer's next field export** to name the 120 GB | SCALE_ROADMAP 2026-07-09 event |
| DB-6 | **dbstat absent on the encrypted store** | The bundled `sqlcipher3` ships without dbstat, so the per-table storage-composition report degrades to PRAGMA totals only on the live encrypted DB. | ✅ shipped w/ honest limit; dbstat-enabled build is the follow-up | SCALE_ROADMAP P1.5 |
| DB-9 | **Backup parity ceiling < 5 TB** | Reed-Solomon over GF(2⁸) caps at N+M < 256 volumes ≈ **128 GB** at 512 MiB volumes; a 5 TB corpus is ~10,000 volumes. Fine at field scale; needs adaptive/larger volume sizing before 5 TB. | 🎨 design-only (fold into P0.1) | SCALE_ROADMAP post-merge audit F6 |
| DB-10 | **Near-dup content growth / eviction posture** | Wire reprints stored whole inflate storage; tiered-retention eviction is designed but not built (default-off, WARC-gated); incremental-vacuum posture at 5 TB undecided. | 🎨 design-only | SCALE_ROADMAP P1.5 |

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
| **P0.1** | Backup at 100 GB+ — the `oo-volumes-2` streaming engine (no plaintext corpus snapshot, no zip, bounded RAM incl. banded parity, incremental changed-volume re-emit, resumable, verifiable) | 🔧 engine shipped — **awaiting the maintainer's live-corpus validation** (the v0.2.0 gate item) |
| **P0.2** | Restore/import at scale — streams member-by-member, disk-preflights staging, hands to the unchanged additive merge | 🔧 engine half shipped — full-scale proof gated on an operator run |
| **P0.3** | Crash root-cause — OOM in a 21.6-h crawl pass (**RSS 10.6 GB > VM RAM**); fix = pass recycling + an RSS memory guard + inter-pass WAL checkpoints | 🔧 collector fix shipped — awaiting live-run validation |
| **P0.4** | **Unlock at scale** — ROOT-CAUSED + fixed (Session A, `claude/a-scale-backend-p04-9faxvb`): `init_db`→`ensure_fts` ran the FTS5 `'rebuild'` (a corpus-scaled codec re-read) UNCONDITIONALLY on EVERY boot; the sync triggers already maintain the index, so it now rebuilds only when needed. Measured on a 112k/2.7 GB **encrypted** synthetic corpus: 28.6 s → **0.002 s** per boot; G2 warm unlock **0.012 s** (acceptance <2 s). | 🔧 **fixed on synthetic — awaiting the maintainer's live-corpus validation** (the standing v0.2 gate item; never claim closed on synthetic) |
| **P0.5** | Scale test harness (GAMMA: synthetic-corpus generator + benchmark runner + CI smoke tier) | ✅ shipped (#601) |

### P1 — snappiness at scale (adoption-critical)

| Item | What | Status |
|---|---|---|
| **P1.1** | **Death-spiral fix**: server-side deadlines + client single-flight polling + a concurrency cap (requests stacked without cancellation; one endpoint was in-flight 217 s) | ✅ shipped (the `heavy.py` admission guard + honest 429 client retry); the last uncovered reads — integrity profile/actors/prominence/fixity — are now guarded too (#628) |
| **P1.2** | Job-ify heavy sync handlers (enrich-source-types 8.5 min · governments 2.9 min · diagnostics `/all` 36 min — all background jobs now; heavy reads guarded) | ✅ largely shipped — residual: audit `corpus-www` (28 s) / `corpus-sentiment` (18 s) for individual guards |
| **P1.3** | `count(*)` from maintained counters (`SELECT count(*) FROM keyword_mentions` = 724 ms × 172 = 124 s) | 🚧 partial — the `/status` data-aware cache shipped (count stays EXACT); a sweep of the remaining `count(*)` call sites is unverified |
| **P1.4** | `/insights/latest` (40 s @ 268 K → near-dup bounded) | ✅ shipped — re-measure on next field export |
| **P1.5** | Storage-composition diagnostic | ✅ shipped (dbstat-limited on encrypted store) + the itemized all-stores footprint (A12b/B14 ⏳ #625) |
| **P1.6** | Corpus-epoch mechanism | ✅ shipped — **now incl. the restore-merge wiring** (A7) |
| **P1.7** | 5 TB architecture verify-before-trust review | 🎨 design-only (the A14 if-time item — not reached) |
| **P1.8** | Collector-path write batching (writer gate: 847,351 s cumulative wait / 22% of worker-time / max 438 s) | ✅ shipped |
| **P1.9** | Job-ify the diagnostics `/all` export (was 36+ min blocking the loop) | ✅ complete — backend (#600 D2) + the UI job button (B6, #622) |
| **P1.10** | trending-windows cold path (467 s/call; 62 calls / 3,286 s) — stale-but-disclosed serve + change-gated refresh | ✅ shipped — D1 persisted store still pending (see DB-3) |
| **P1.11** | Flip on the D4 map serve (map GROUP BY was 748 s total / ~150 s per call) | ✅ shipped |
| **P1.12** | Background maintenance under the job/deadline regime (counter-reconcile 86–104 s/pass; prune 32 s) | ✅ **complete** — deadline+watermark half shipped earlier; **off-peak scheduling shipped S2.2 (A10, 2026-07-12)**: `src/scheduler/maintenance.py:run_idle_maintenance` runs the budgeted reconcile/prune slices in the collector-IDLE window (scheduler-owned `_run_off_peak_maintenance`, holds `_run_lock` so it is never concurrent with a pass, throttled `OO_MAINT_INTERVAL_S`=300 s, skipped under memory pressure, `_stop`-interruptible), DECOUPLED from the pass-tail `warm_cache`; freshness gates + `complete:false` disclosure unchanged; surfaced in scheduler `status().last_maintenance`. |

**Heavy-endpoint sweep status (was the ⬜ list from the 2026-07-08 field test):**
`signals/alerts`/`flood`/`bury` + `insights/lunar-correlation` + `server-locations` +
briefing/trending/associations — **guarded** ✅; integrity reads (profile/actors/prominence/
fixity) — **guarded** ✅ (#628); residual to verify under load: `diagnostics/keywords`
(100–184 s), `debug-bundle` (69 s), `/api/articles` p95 25 s. 🚧

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
| **FLOOD card polluted by leaked common words** | `signals/flood` surfaces Dutch filler ("kijk"/"zien") as topics. Deliberately NOT hand-stoplisted (open-class words need the **measured** keyword-log sweep / lemmatization track, per the ledger discipline); the words are flagged for the next keyword-log review. | ⬜ open — the honest lever is `analyze_keyword_log --generic-terms` on a fresh export 🛠 |
| **Date-extraction recall — the broader tail** | hu/fa relative-day words shipped (B4, #617 — measure-first found the field figures 0%/22% were STALE); the residual `date-like-but-unextracted` classes + CJK dates remain. | 🚧 residual (P2) |
| **`diagnostics/keywords` + `debug-bundle` under load** | 100–184 s / 69 s in the field export — verify the guard/job coverage catches them at scale. | ⬜ verify next field run |

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
- **Date-extraction recall — the residual tail** — hu/fa relative-day words shipped (B4); the remaining `date-like-but-unextracted` classes + CJK dates (now unblocked by the segmenter). 🚧
- **Open-class stoplist sweep** — the measured `analyze_keyword_log --generic-terms` loop over a fresh export (kills the FLOOD filler + "rising"-card leaks; never a hand-guess). 🛠 operational
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

### Agenda & calendars
- **Eclipse canon** from a bundled public table (moons + seasons already shipped). 🎨
- **Deduced events as first-class agenda entries** with keyword links (RC-blocking-era item). ⬜
- **Worldwide calendar preloads** — bank holidays; Islamic computed with the ±1-day caveat; Hindu/Buddhist from sourced tables; fix Christian-centring. 🎨
- **One recurrence model** (RULE + dated INSTANCES + `since:` origin year) · **month-span events** ("Dry January") · **full iCal import** · **saved-filter "smart calendars"** · **catalog depth flood** (elections/summits/central banks/courts/UN days) · **agenda i18n** · **temporal-map player speeds** 0.05×–16×. 🎨

### LLM / AI
- **LLM language detection for unknown-language articles** — ✅ **BUILT (B15)** ⏳ #626: opt-in, detector-first, a third clearly-labelled "AI-derived · unreliable" provenance class, never overwrites the asserted/detector channels, garbage answers store nothing, visible abortable job. Remaining 🛠: browser click-through + run it on the live corpus.
- **LLM-assisted perception** — who/where/when extraction (dates/places/orgs, no "what") as confirmable candidates in the AI layer, distinct toggleable layers. 🎨
- **Eval-first harness** — difficulty-tiered, phenomenon-tagged, ×12 langs; precision/recall/hallucination per stratum; the gate for every perception/sentiment change. 🎨
- **Multilingual sentiment** — **DECIDED (B12, ruling 3a executed): the model path is deferred** (pyproject bans torch/onnx/transformers), pivot to a rule-based **subjectivity/loaded-language** signal feeding the manipulation cards. Build pending: license-clean per-language subjectivity lexicons. ⬜ decided, not built
- **Offline LLM USB kit** (checksummed Ollama binary + one small model — the air-gapped path) · **hardware-tier messaging** · **live ollama.com library browse**. 🎨
- **LLM-as-grader / attributed-claims + embedding novelty** — recorded, not approved (leaning against a composite grade). ⬜ open

### Sources, statistics & diversity
- **`stat_indicators.yml`** curated dated series + freshness test · **more parsers** (OECD SDMX-JSON 1.0, IMF 3.0, WHO OData, FAOSTAT) · **SDMX live-verify** (networked). 🎨/🛠
- **`ooViz` honest-chart family** (small multiples, dumbbell/slope for vintages + CIs, association scatter with no regression line, treemap, histogram/box, Sankey, availability heatmap, population pyramid, error bars) with the reject-list gate. Primitives exist, not wired to a surface. 🎨
- **News / plural-stance source diversity** — 105 verified `enabled:false` rows filling Caribbean/Pacific/sub-Saharan/Central-Asia/MENA gaps; dedup `statssa.gov.za`. The `global`/`transnational` region value is ✅ **BUILT** (B12 ⏳ #621: `int`/`eu` → "Global", never fabricated); populating individual International sources with `int` is the follow-up curation. 🎨
- **De-US-centring remainder** — run the Wikidata generator for the 73 named gaps; raise the located share (≈49% of domains carry no country). 🛠
- **Content-provenance class** — ✅ found SHIPPED end-to-end (ingestion stamps `source_type` + backfill; `insights_source_types` facet; reading-diet-by-channel in `concentration.py`) — S6 verify-marks against the design doc's acceptance. 
- **Secondary-source `cited` provenance class — remaining slices** (background job at scale, denormalize `citing_source_id`, surface the citing trail, wire dormant `external_sources`). 🚧 partial
- **DuckDuckGo query discovery channel** (off-by-default, per-query logging, budgeted) + Wikidata generator as a scheduled refresh. 🎨
- **Expand commodity feeds** (oil, gas, LNG, sand, cereals, sugar) — needs clearnet-verified robots-permitting sources. 🛠 · **Rare earths: DECIDED (B12) = USGS Mineral Commodity Summaries SUPPLY data** (production/reserves/net-import-reliance, explicitly not spot prices — no free spot source exists); the stats-agency + annual-supply parser is the build (→ S5.1). ⬜ · S&P500-is-an-index reclassification — ✅ found done (`idx_sp500` + the commodities board excludes `index` symbols per the recorded ruling in `markets.py`).

### Manipulation cards & the civic vertical
- **FLOOD/BURY cards — remaining quality** — both cards exist; BURY gained same-language cohort scoping (B3 ⏳ #620). Remaining: the FLOOD open-class filler (the measured stoplist sweep, §"Keyword engine") + the full same-language *denominator* rescoping with ring-translation bridging (labelled follow-up). 🚧
- **Event-timed-operation card** ("October surprise" = emergence + source-laundering + agenda; needs an elections roster). 🎨
- **Elections & civic vertical** — sourced `elections` calendar (France 2027 pilot, movable-marked), curated candidate rosters with provenance, "name the shape, never prescribe". 🎨
- **Poll analysis** — a method-audit tier stack (Tier 2 transparency checklist + verbatim question display first); no composite score, non-disclosure outranks disclosed-imperfection. 🎨
- **Evidence-tiered cards — remaining** (power-style "what's missing" inversions; Benjamini–Hochberg once p-values exist; card-diagnostics export — NOTE: dismiss-with-reason appears SHIPPED in the 2026-07-03 batch-E commit; verify-first before building any of this row). 🚧 partial

### Convergence, watches & alerting
- **New Home producers** — "Converging now" (`space_time_convergence`) + "watch-rules fired" (`watch_matches`) ✅ exist and register; the TWO missing: **"On the horizon"** (agenda ∩ watched keywords) + **"Through time / anniversary"** → S6.4. 🚧
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
- **Guided-setup wizard remaining slices** (encryption-choice + sources-by-theme steps). ⬜
- **Onboarding & training** — first-run tour as dismissible Home cards + contextual "why" notes + a supervised training curriculum (in-repo, never hosted). 🎨
- **i18n long tail** — the 44 new B5/B14/B15 strings are now keyed ×12 (B10, #629) ✅; remaining: the pre-existing ~105–140 chrome tail + server-built Home-card **title** translation design + composite-string format support. 🚧 ongoing
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
8. **`global`/`transnational` region value** — ✅ **BUILT (B12** ⏳ #621): `int`/`eu` → "Global"; follow-up = curate `int` onto the International sources.

**Decided, build pending:**
3. **Rare-earths** — **USGS Mineral Commodity Summaries supply data** (not spot prices). Parser/agency build ⬜.
9. **Multilingual sentiment** — model path **deferred** (no-torch/onnx constraint); pivot to a rule-based subjectivity/loaded-language lexicon. Lexicon sourcing ⬜.

**Attempted, honestly blocked:**
2. **httpfs crypto-extension bundling** — the fetch hit the network egress allowlist (403 on `extensions.duckdb.org`); **no checksum fabricated**, in-memory fallback stays. Needs a networked machine or an allowlist entry. 🛠 (see DB-3)

**Still with the maintainer:**
4. **`v0.2.0` tag** — HELD until the P0 live-corpus validation (all four P0 engines now shipped; the live run is the last gate). 🛠
6. **Lemmatization default-on** — measure-gated on the maintainer-made gold set. 🛠
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
