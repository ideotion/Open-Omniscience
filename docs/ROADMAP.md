# Open Omniscience — Roadmap

The single forward-looking board: current limitations, performance work, known bugs, and
the feature backlog, with a status + priority on every item. Consolidated 2026-07-10 from
the previously-scattered planning docs.

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
  scale set** (see §3). The engines are shipped; the field validation is the remaining gate,
  and **P0.4 (unlock-at-scale) is still unresolved**.
- **Definition of "snappy" (the acceptance bar for 0.2):** every interactive endpoint p95
  **< ~500 ms** at 100 GB · **unlock < 2 s** · no UI action blocks > 1 s without becoming a
  visible job · background work never freezes the UI.

---

## 1. Database — current limitations

| # | Limitation | Detail | Status | Ref |
|---|---|---|---|---|
| DB-1 | **Unlock is slow and worsening at scale** | 60 s @ 2.28 GB → **981 s → 1,645 s (27.4 min)** on consecutive boots; the one-time-migration hypothesis is **refuted** (cost recurs and grows). Suspects: WAL recovery after unclean shutdown, corpus-scaled synchronous `init_db`. | 🚧 root-cause pending live export (P0.4) | SCALE_ROADMAP P0.4 |
| DB-2 | **5 TB single-file SQLCipher unvalidated** | Page cache, VACUUM infeasibility, backup windows, single-writer behaviour at 5 TB never measured. Cross-time recall is sacred — no partitioning that makes old data second-class. | 🎨 design-only | SCALE_ROADMAP P1.7 · `DATA_ARCHITECTURE_SKELETON.md` |
| DB-3 | **Persisted encrypted columnar store (D1) blocked** | The in-memory rollup is rebuilt every boot (dies at scale); the persisted encrypted DuckDB store needs the per-OS **httpfs crypto-extension** bundled. Verified: DuckDB will not write an *authenticated* encrypted file without it. | 🔒 ruling-gated | SCALE_ROADMAP Ruling-gated #2 · `PERSISTED_DUCKDB_HTTPFS.md` |
| DB-4 | **Keyword-table growth is a storage problem** | Heaps β ≈ 0.82–0.95; **zh 46K + th 21K + ja 12K** junk keywords from missing segmentation, ko/vi/mr stoplist gaps. Prune finds 0 orphans — the lever is segmentation, not pruning. | 🔒 ruling-gated (segmenter) | SCALE_ROADMAP P1.5 / Ruling-gated #1 |
| DB-5 | **~120 GB of the data folder unidentified** | `db_bytes` = 11.7 GB but the folder is ~130 GB. Suspects: orphaned plaintext staging (would be an at-rest-encryption violation), wiki/OSM downloads, a runaway `-wal`. Needs a `du -sh` breakdown. | 🚧 diagnostic | SCALE_ROADMAP 2026-07-09 event |
| DB-6 | **dbstat absent on the encrypted store** | The bundled `sqlcipher3` ships without dbstat, so the per-table storage-composition report degrades to PRAGMA totals only on the live encrypted DB. | ✅ shipped w/ honest limit; dbstat-enabled build is the follow-up | SCALE_ROADMAP P1.5 |
| DB-7 | **Corpus-epoch not wired into restore-merge** | `bump_corpus_epoch` ships and is wired into reindex/prune, but not the restore-merge (the one residual mutator). Over-bump harmless; a missed bump is bounded by the serve backstop TTL. | 🚧 residual | SCALE_ROADMAP P1.6 |
| DB-8 | **Alembic stamp behind head** | Self-heal keeps the schema in sync but the DB stamp lags the code head — a latent risk for the next migration / cross-version restore. | ⬜ low priority | field-test 2026-07-08 Item 8 |
| DB-9 | **Backup parity ceiling < 5 TB** | Reed-Solomon over GF(2⁸) caps at N+M < 256 volumes ≈ **128 GB** at 512 MiB volumes; a 5 TB corpus is ~10,000 volumes. Fine at field scale; needs adaptive/larger volume sizing before 5 TB. | 🎨 design-only (fold into P0.1) | SCALE_ROADMAP post-merge audit F6 |
| DB-10 | **Near-dup content growth / eviction posture** | Wire reprints stored whole inflate storage; tiered-retention eviction is designed but not built (default-off, WARC-gated); incremental-vacuum posture at 5 TB undecided. | 🎨 design-only | SCALE_ROADMAP P1.5 |

**Already resolved (this cycle):** expression index on `coalesce(published_at,created_at)`
(was 735 s of full scans → index-only, #588) ✅ · corpus-epoch mechanism (`derived_meta`) ✅ ·
covering mention indexes / FTS optimize / batched commits / the single-writer gate ✅ ·
storage-composition diagnostic ✅.

---

## 2. Performance & scale — the P0 / P1 board

The deep detail (measured numbers, acceptance criteria, session territories) lives in
[`docs/product/SCALE_ROADMAP.md`](product/SCALE_ROADMAP.md). This is the status summary.

### P0 — data safety at scale (the release blockers — attended sessions)

| Item | What | Status |
|---|---|---|
| **P0.1** | Backup at 100 GB+ — the `oo-volumes-2` streaming engine (no plaintext corpus snapshot, no zip, bounded RAM incl. banded parity, incremental changed-volume re-emit, resumable, verifiable) | 🔧 engine shipped — **awaiting the maintainer's live-corpus validation** (the v0.2.0 gate item) |
| **P0.2** | Restore/import at scale — streams member-by-member, disk-preflights staging, hands to the unchanged additive merge | 🔧 engine half shipped — full-scale proof gated on an operator run |
| **P0.3** | Crash root-cause — OOM in a 21.6-h crawl pass (**RSS 10.6 GB > VM RAM**); fix = pass recycling + an RSS memory guard + inter-pass WAL checkpoints | 🔧 collector fix shipped — awaiting live-run validation |
| **P0.4** | **Unlock at scale (ESCALATED, still the standing blocker)** — 1,645 s at scale; instrumentation merged (#596/#599) but the phase is not yet named/fixed | 🚧 unresolved |
| **P0.5** | Scale test harness (GAMMA: synthetic-corpus generator + benchmark runner + CI smoke tier) | ✅ shipped (#601) |

### P1 — snappiness at scale (adoption-critical)

| Item | What | Status |
|---|---|---|
| **P1.1** | **Death-spiral fix**: server-side deadlines + client single-flight polling + a concurrency cap (requests stacked without cancellation; one endpoint was in-flight 217 s) | 🚧 in progress (ALPHA A1) |
| **P1.2** | Job-ify heavy sync handlers (enrich-source-types 8.5 min · governments 2.9 min · corpus-www 28 s · sentiment 18 s · top 20 s …) | 🚧 in progress (ALPHA A2) |
| **P1.3** | `count(*)` from maintained counters (`SELECT count(*) FROM keyword_mentions` = 724 ms × 172 = 124 s) | 🚧 in progress (ALPHA A3) |
| **P1.4** | `/insights/latest` (40 s @ 268 K → near-dup bounded) | ✅ shipped — re-measure on next field export |
| **P1.5** | Storage-composition diagnostic | ✅ shipped (dbstat-limited on encrypted store) |
| **P1.6** | Corpus-epoch mechanism | ✅ shipped (not yet wired into restore-merge — see DB-7) |
| **P1.7** | 5 TB architecture verify-before-trust review | 🎨 design-only |
| **P1.8** | Collector-path write batching (writer gate: 847,351 s cumulative wait / 22% of worker-time / max 438 s) | ✅ shipped |
| **P1.9** | Job-ify the diagnostics `/all` export (was 36+ min blocking the loop) | ✅ backend shipped — UI wiring remaining |
| **P1.10** | trending-windows cold path (467 s/call; 62 calls / 3,286 s) — stale-but-disclosed serve + change-gated refresh | ✅ shipped — D1 persisted store still pending (see DB-3) |
| **P1.11** | Flip on the D4 map serve (map GROUP BY was 748 s total / ~150 s per call) | ✅ shipped |
| **P1.12** | Background maintenance under the job/deadline regime (counter-reconcile 86–104 s/pass; prune 32 s) | ✅ deadline half shipped — off-peak scheduling remains |

**New heavy endpoints still needing rollup/cache/deadline (from the 2026-07-08 field test):**
`signals/flood` (66–151 s), `signals/bury` (27–111 s), `insights/lunar-correlation`
(57–142 s), `diagnostics/keywords` (100–184 s), plus slow diagnostic exports (`debug-bundle`
69 s, `integrity` 62 s, `briefing` 30–37 s, `/api/articles` p95 25 s). ⬜

**Deferred perf riders (post-merge audit):** F13 batched collector flush holds the write gate
across per-article *extraction* (not just the write) · F10/F11 backup↔collector gate-hold
ordering · F14 markets `run_rule` dirty session holds the gate across a CSV fetch. ⬜ (low/med)

---

## 3. Known bugs & data-safety issues (still open)

| Bug | Impact | Status |
|---|---|---|
| **App OOM crash under load** | A crash in a disposable VM = **total corpus loss**. Collector fix shipped; needs the live-run validation. | 🔧 fix shipped, awaiting validation (P0.3) |
| **Disposable-VM durability** | The DispVM crash vaporized a ~60K-article corpus. Fix = easy opt-in **persistent data_dir** (bind-mount) + an honest note — *not* "stop using DispVMs". | ⬜ design |
| **Backup UI reports false "NetworkError / Backup failed"** | `api()`/`_uxPoll` has no timeout/retry; one dropped `/volumes/status` poll aborts the UI though the job keeps running. Fix = treat job-state as truth, retry with backoff. | ⬜ root-caused, fix pending |
| **No standalone "Verify this backup" action** | `verify_volume_set` exists but is un-exposed; the only check today is attempting a restore. Must cover both the volumes manifest and the folder manifest. | ⬜ backend fn exists, no endpoint/UI |
| **Indices board empty on most continents** | The OECD `SPASTT01<ISO3>M661N` feed ids use 3-letter codes but FRED uses 2-letter → every OECD feed 404s (empty Europe/Asia/Africa/S.America/Oceania). A 19-row correction table exists. | ⬜ fix planned |
| **FLOOD card polluted by leaked common words** | `signals/flood` surfaces Dutch filler ("kijk"/"zien") as topics — nl open-class stoplist gaps + cards inherit keyword junk. Needs language-aware scoping. | ⬜ design finding |
| **BURY card dominated by language artifacts** | `signals/bury` flags non-English sources for "burying" English keywords they simply write in their own language. Needs same-language cohort scoping. | ⬜ design finding |
| **Date-extraction recall gaps** | Overall 62.1%; **Persian (fa) 0%** (calendar/numerals unhandled — a real bug), Hungarian 22%. | ⬜ (P2) |
| **Dead default calendar feeds** | Several bundled holiday/religious feeds are robots-disallowed or dead — drop from the shipped defaults. | ⬜ minor |
| **FTS present/absent probe contradiction** | The integrity sweep can report `fts.present:false` (deadline-interrupted) vs schema-drift `fts_present:true`; verify search works / re-index heals. | ⬜ low |

**Recently fixed (this cycle):** restore arbitrary-file-DELETE from a hostile backup (traversal
guard) ✅ · finalize could destroy a complete backup mid-swap (atomic manifest replace) ✅ ·
mindmap 503 at 974K keywords (bounded + deadline, never 503) ✅ · alert-strip 24 s → sub-ms
(memo cache) ✅ · autoflush held the write gate across a fetch (the 438 s signature) ✅.

---

## 4. Feature backlog & add-ons (by area)

Design rationale for most of these lives in [`docs/FUTURE_DEVELOPMENTS.md`](FUTURE_DEVELOPMENTS.md);
this is the tracked list. Items already shipped are omitted (see the ledger).

### Keyword engine & quality
- **zh / ja / Thai segmentation** — vendor an offline, license-clean, no-network segmenter (jieba/pkuseg/MeCab class). Now **scale-critical** (junk keyword storage). 🔒 ruling-gated
- **Date-extraction recall** — raise from 62% (fa 0%, hu 22%); CJK dates tie to segmentation. ⬜
- **`reconcile_keyword_language` + evidence-grown stoplists** — kill "rising"-card leaks (annons/koji/ali) and open-class filler. ⬜
- **Trans-language equivalence — remaining** — the cross-country map view + surfacing `language_breakdown` in the frontend; local-LLM proposing candidate rings. 🚧 partial (slice 1 shipped)
- **Lemmatization default-on** — `OO_FAMILY_LEMMA` (73 of top-500 would merge) — enable after a gold-set measure. 🔒 ruling-gated #6
- **Keyword-log-driven catalog pruning** as a repeatable workflow. 🛠 operational

### Backup, import / export & data-safety
- **Backups include downloaded Wikipedia dumps** — dedup-by-checksum, additive restore must place FILE members into `wiki_dumps`. 🎨 (reverses design D3)
- **Remove the legacy single-file backup RESTORE** once the format is fully retired (keep the additive-merge engine). 🎨
- **Unified Import + unified Export/Backup dialogs** on the streaming-volume path — one entry each, options pop-up, live progress. 🚧 partial (design in `UNIFIED_IMPORT_EXPORT.md`)
- **Collector write-batching** (the risky keystone-#1 refactor) — `index_article(commit=False)` + batch + per-article fallback + no-loss test. 🎨 (`COLLECTOR_WRITER_BATCHING.md`)

### Database / scaling (columnar & rollups)
- **D1 persisted encrypted DuckDB store** — blocked on per-OS httpfs binaries. 🔒 (see DB-3)
- **D2 `keyword_daily` rollup** (gated on D1) + **D3 incremental refresh + epoch full-rebuild gate**. 🎨
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
- **LLM-assisted perception** — who/where/when extraction (dates/places/orgs, no "what") as confirmable candidates in the AI layer, distinct toggleable layers. 🎨
- **Eval-first harness** — difficulty-tiered, phenomenon-tagged, ×12 langs; precision/recall/hallucination per stratum; the gate for every perception/sentiment change. 🎨
- **Multilingual sentiment** to replace English-only VADER (XLM-R ONNX, per-language gated) — *or* pivot to a subjectivity/loaded-language signal feeding the manipulation cards. ⬜ open
- **Offline LLM USB kit** (checksummed Ollama binary + one small model — the air-gapped path) · **hardware-tier messaging** · **live ollama.com library browse**. 🎨
- **LLM-as-grader / attributed-claims + embedding novelty** — recorded, not approved (leaning against a composite grade). ⬜ open

### Sources, statistics & diversity
- **`stat_indicators.yml`** curated dated series + freshness test · **more parsers** (OECD SDMX-JSON 1.0, IMF 3.0, WHO OData, FAOSTAT) · **SDMX live-verify** (networked). 🎨/🛠
- **`ooViz` honest-chart family** (small multiples, dumbbell/slope for vintages + CIs, association scatter with no regression line, treemap, histogram/box, Sankey, availability heatmap, population pyramid, error bars) with the reject-list gate. Primitives exist, not wired to a surface. 🎨
- **News / plural-stance source diversity** — 105 verified `enabled:false` rows filling Caribbean/Pacific/sub-Saharan/Central-Asia/MENA gaps; schema needs a `global`/`transnational` region value; dedup `statssa.gov.za`. 🎨
- **De-US-centring remainder** — run the Wikidata generator for the 73 named gaps; raise the located share (≈49% of domains carry no country). 🛠
- **Content-provenance class** — descriptive `source_type` controlled vocab + backfill (fixes newsletters mislabeled as news) → facet → reading-diet-by-type. 🎨
- **Secondary-source `cited` provenance class — remaining slices** (background job at scale, denormalize `citing_source_id`, surface the citing trail, wire dormant `external_sources`). 🚧 partial
- **DuckDuckGo query discovery channel** (off-by-default, per-query logging, budgeted) + Wikidata generator as a scheduled refresh. 🎨
- **Expand commodity feeds** (rare earths, oil, gas, LNG, sand, cereals, sugar) — needs clearnet-verified robots-permitting sources. 🛠 · fix the S&P500-is-an-index reclassification. ⬜

### Manipulation cards & the civic vertical
- **Flood/BURY card — the BURY half** (a source under-covering a topic big elsewhere; needs a real external trigger). 🎨
- **Event-timed-operation card** ("October surprise" = emergence + source-laundering + agenda; needs an elections roster). 🎨
- **Elections & civic vertical** — sourced `elections` calendar (France 2027 pilot, movable-marked), curated candidate rosters with provenance, "name the shape, never prescribe". 🎨
- **Poll analysis** — a method-audit tier stack (Tier 2 transparency checklist + verbatim question display first); no composite score, non-disclosure outranks disclosed-imperfection. 🎨
- **Evidence-tiered cards — remaining** (power-style "what's missing" inversions; Benjamini–Hochberg once p-values exist; dismiss-with-reason feedback; card-diagnostics export). 🚧 partial

### Convergence, watches & alerting
- **New Home producers** ("Converging now", "On the horizon" = agenda ∩ watched keywords, "Through time / anniversary", "Your watch-rules fired"). 🎨
- **Severity-tiered local alert layer** (info/watch/urgent from hazard severity + fresh-news tag-families + watch matches; urgent = a Home banner; local-only, user-owned thresholds). 🎨
- **Seven remaining space-time scenario cards** (news-desert atlas, disputed-chronology detector, silent-disasters, law-takes-effect watch, story-propagation tracer, supply-chain ripple, election-window desk) + a per-card `/investigate` view. 🎨

### Wikipedia as a living source
- **Dedicated tracked-changes tab** — scroll/discover/analyze edits through time. 🎨
- **Dumps → corpus ingestion path** — stream-parse downloaded XML into the pipeline (idempotent, bounded, visible job). 🎨
- **Edition-wide auto-track after a dump download** (retire per-article watching; dump = baseline, `recentchanges` = delta). 🎨 (superseding ruling, explicitly not current work)
- **Auto-watch all 12 UI-language editions by default** · **Wikipedia tab → Settings** (test-gated) · **agenda ↔ wiki linking**. ⬜/🎨

### UI / UX & onboarding
- **Home → dashboard / helicopter view — remaining** (top ooChart graphs, a pausable/a11y synthesized-Leads carousel, dynamic commodity-when-trending sections, most-recent-by-tag). 🚧 partial
- **"Latest in your corpus"** recency lens with a transparent substance filter (min words + cited-sources, script-aware length, near-dup collapse; the S0 length diagnostic shipped). 🎨
- **Clickable in-article keywords — stats hover bubble** (mention count/spread, trend rate, translation, co-occurrences; counts only, method visible). 🎨
- **Remove the Insights search bar** once the omnibar absorbs term-exploration · **editable keybindings panel** in Settings · **guided-setup wizard remaining slices** (encryption-choice + sources-by-theme steps). ⬜
- **Onboarding & training** — first-run tour as dismissible Home cards + contextual "why" notes + a supervised training curriculum (in-repo, never hosted). 🎨
- **i18n long tail** — ~105–140 remaining chrome strings + server-built Home-card **title** translation design + composite-string format support. 🚧 ongoing
- **Human click-through of all browser-unverified UI**. 🛠

### Network / transport / Tor
- **Reliable Tor & per-source transport** — optional in-app Stem-controlled `tor` process; per-source circuit isolation by default; clearnet-for-Tor-hostile sources only as an explicit consented per-source opt-in. 🎨
- **OS-layer network kill** (`oo-netcut`, opt-in, privileged, interface-agnostic firewall drop-all + `ip link down` + rfkill; Windows/macOS behind one helper). 🎨
- **Continuous-collection remainder** — the first-run country/language emphasis picker + an explainable "which country next & why" schedule panel (background auto-collect + stratified interleave already shipped). ⬜

### Weather / IPCC / lunar
- **Open-Meteo remainder** — anomaly baselines, deduced signal-keywords, a reader weather-context row, a temporal-map overlay (slice 1 suggest-to-fetch cards shipped). 🚧 partial
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

## 5. Pending maintainer rulings (nothing moves until picked)

1. **zh/ja/th segmenter + ko/mr stoplist artifacts** — which library/wordlist to vendor + license. *Highest-value single ruling* (now scale-critical for storage).
2. **httpfs crypto-extension bundling** (per-OS) — unblocks the D1 persisted encrypted columnar store the 5 TB target needs. *Second-highest.*
3. **Rare-earths price source** — USGS supply data (recommended) / free proxy / authorized paid assessor / defer.
4. **`v0.2.0` tag** — held until the P0 live-corpus scale validation lands (esp. P0.4 unlock). The version+docs flip is done; the branch rename is done.
5. **Keyword hover-stats** — which stats to show (Slice 2 of clickable keywords).
6. **Lemmatization default-on** — needs the gold-set measure first.
7. **Retention / eviction posture** — after the P1.5 storage-composition numbers are in.
8. **`global` / `transnational` region value** in the source schema.
9. **Multilingual sentiment classifier vs subjectivity pivot.**

---

## 6. Version policy & shipped work

Development cycles are named after the version they produce (`0.09 → 0.1 → 0.2`; branch renamed
to match at each flip). The version is single-sourced from `pyproject.toml`. What already
shipped is tracked as rows in [`docs/ledger/shipped.csv`](ledger/shipped.csv) (index) with
verbatim detail + reusable lessons in [`docs/ledger/SHIPPED_LOG.md`](ledger/SHIPPED_LOG.md);
release notes are in [`docs/CHANGES.md`](CHANGES.md). Binding rulings and the live Open queue
are in [`../CLAUDE.md`](../CLAUDE.md) — this board is a readable summary of it, not a
replacement.
