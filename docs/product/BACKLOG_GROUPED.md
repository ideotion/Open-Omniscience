# Grouped backlog — the 2026-06-13 build plan

> **Status:** living synthesis (maintainer-asked 2026-06-13 "I'd prefer the list
> in groups"). One PR per item, stacked onto `0.09`, foundations first. Detail
> for each group lives in the named design docs (`SCRAPING_AUTOMATION_PLAN.md`,
> `UI_SHELL_REDESIGN_PLAN.md`, `FUTURE_DEVELOPMENTS.md`) and the CLAUDE.md ledger.
> Legend: ✅ shipped (PR) · 🔨 in progress / next · ⬜ queued · 🐛 bug.

> **2026-06-16 — AUTONOMOUS 'EVERYTHING' BATCH** (full ruling: CLAUDE.md "AUTONOMOUS
> 'EVERYTHING' BATCH"). Scope = the V0.1 RC mandate in full + promotions. The UI RETHINK
> is now the ACTIVE CENTERPIECE — nav-to-top facet strip + Home→dashboard + Insights
> overview / Trends (24h · week · MONTH) + the 3D keyword explorer land in Group E; the
> named parallel Analysis tabs + the #an↔#corpus-win CONSOLIDATION land in Group F. The
> offline READER stays STANDALONE (#246, fork-1). The convergence WATCH engine = the full
> "Watches view + history" (fork-2). Two NEW groups below: **M** geo/offline map, **N**
> official-statistics. Browser-unverifiable UI ships conservative + flagged (fork-3); the
> MAINTAINER MERGES EVERYTHING (fork-4 — drafts stack). Recently shipped since this doc
> was written: Item V airplane-red (#245), Reader-tabs slice 1 (#246), exact-article-id
> card seeding (#241/#242), .eml importer (#237), convergence endpoint (#231), Item Y
> (n<10→bars).
>
> **AUTONOMOUS SESSION 2026-06-16 — draft PRs #248–254 onto `0.09` (CI runner-backlogged
> the whole session, so each gated on the FULL local suite: pytest green · mypy 112≤127 ·
> node --check · i18n 100% ×12). Shipped:** (1) **#248** flat Wikipedia edition picker —
> drop the continent optgroups, one flat UI-locales-first list, `/api/wiki/languages` no
> longer emits `groups` (invariant #1 amendment). (2) **#249** inline DATED dump-size
> estimates in the picker (`src/wiki/dump_sizes.py` + `DUMP_SIZES_AS_OF` + freshness test;
> zero-network). (3) **#250** the reader-tabs FLAGSHIP completed (RC-BLOCKING → ✅):
> **Mindmap** tab via `/api/insights/graph?article_ids=` + `queries.article_graph` radial,
> and a server-rendered **Source** profile tab; reader stays standalone. (4) **#251**
> `queries.trending_windows` + `/api/insights/trending-windows` (24h/7d/30d substrate).
> (5) **#252** the **LEADS** rename — briefing "cards" → "Leads" user-facing ×12 (worktree
> agent + hand-verified). (6) **#253** Insights **Trends** frontend slice 1 — the three
> preset windows side by side (`#trd-windows`, additive). (7) **#254** the network-consent
> popup now states WHICH LAYER airplane mode controls (RC §4 threat-model honesty). Per-PR
> ledger entries in CLAUDE.md are authoritative. NEXT (this batch, unstarted): the UI-rethink
> nav-to-top + Home→dashboard + 3D explorer; Markets category subtabs + click→analysis;
> agenda content; task-manager remainder; in-app Ollama installer; geo/OSM (Group M);
> official-statistics (Group N); convergence Watches view; Win/mac install + release eng.

## The keystones (shared building blocks that unblock many items)

Almost everything below reduces to **six reusable pieces**. Building these well
makes the rest fall out cheaply:

1. **Single-writer queue** — serialises all DB writes; fixes the lock contention
   AND makes parallel collection safe. (Group A)
2. **The download subsystem** — guarded factory → parallel → segmented → task
   manager. (Groups A/B/C)
3. **Universal subtab component** — lateral = main tabs, vertical = subtabs;
   reused by Home, Insights, Settings, Markets, the analysis window. (Group E)
4. **The analysis window (corpora system)** — one window with consistent
   sub-tabs; serves search, commodities, keywords, articles. (Group F)
5. **The task-manager window** — one live jobs view; serves downloads, dumps,
   model pulls. (Group C)
6. **The guided first-launch wizard** — language, encryption, sources-by-theme,
   first collect. (Group D)

---

## A. Foundations & engineering health

- ✅ **CI hygiene** (PR #106) — pin mypy + bandit (kill the tool drift that was
  reddening every PR); fix the 429-handler `AttributeError` + `escape(None)`;
  fix the dump-XML `B314` with `defusedxml`.
- ✅ **Data-loss: retry transient DB lock** (PR #107) — `run_write_with_retry`
  so commodity imports never discard fetched-over-Tor prices to "database is
  locked".
- ✅ **Guarded socket factory** (PR #108) — kill switch + proxy + honest UA on
  every fetch path; ratchet allowlist 6 → 3; closes the clearnet transport leak.
- ✅ **Single-writer queue** (keystone #1) — `src/database/writer.py`: a
  reentrant, observable write gate wired via SQLAlchemy session events (zero
  call-site churn); writers queue in-process so two never collide on the SQLite
  lock (no "database is locked", no lost data). Prerequisite for safe parallel
  collection — now in place.
- ⬜ **UI polling storm** — ~10k polls / 2 h (vitals ×4120, activity ×2747…)
  contend with the encrypted DB; consolidate to one status poll / SSE + adaptive
  backoff. (log finding B)
- ⬜ **keyword_export under contention** — 29→65 s during a live scrape; read
  snapshot for exports. (log finding C)
- 🔨 **mypy ratchet pay-down** toward 0 (ongoing); **Win/macOS portability
  lanes → green** then graduate to required. SHIPPED so far: `UnicodeDecodeError`
  (text `open()` without `encoding`) + ratchet. **#136 fixes the three remaining
  failure classes (diagnosed from the live observation-lane logs):** (1) the
  `/tmp`↔`/private/tmp` (macOS) / `D:/tmp` (Windows) **path-canonicalization** test
  now compares against `Path(base).resolve()` (no-op on Linux); (2) **`install.sh`
  under the Windows WSL stub** — `test_installer.py` skips on `win32` (a POSIX
  script; the runner only has a distro-less WSL `bash`), and the Linux-only XDG
  `.desktop` launcher test skips on non-Linux; `test_uninstall` launcher-discovery
  skips on `win32`; (3) **`WinError 32`** (delete-open-file) — the three backup
  temp-`.db` sites (`database.py`, `safety/backup.py`, `backup_v2.py`) now
  `os.close(fd)` from `mkstemp` **before** unlinking. Verified non-regressive on
  Linux; should green both lanes (verify in CI, then graduate to required).

## B. The download / scraping subsystem (content-first)

- ✅ **Parallel downloads** — dumps `max_concurrent` 1 → N (shipped #110) **+ a
  bounded fetch worker pool for collect** (`collect_parallelism`, default 1 =
  opt-in): parallel fetch across hosts (each its own Tor circuit), single writer
  via the gate, per-host lock keeps politeness. The Tor-speed fix: N circuits,
  not one. (SCRAPING plan Step 2) REMAINING: raise the default after field
  validation; the task manager surfaces/tunes it.
- ✅ **Per-host Tor stream isolation for collect** — each host rides its own Tor
  circuit (`IsolateSOCKSAuth`, per-host SOCKS user) so no exit/observer links the
  user across sources; page + robots share the host circuit; on by default over
  SOCKS, no-op otherwise (`OO_TOR_STREAM_ISOLATION=0` disables). The safe answer
  to "protect from other sources" — no clearnet exposure. (Tor concept 2026-06-13)
- ⬜ **Segmented HTTP-Range** over multiple circuits + `IsolateSOCKSAuth` (one
  big dump, fast). (Step 3)
- ⬜ **Dump mirror selection**. (Step 4)
- 🔨 **Auto-collect after one consent; boot in airplane mode; permanent when
  online**; demote the cross-kind arbitration modal → silent queue. (Step 5)
  SHIPPED: boot-in-airplane-mode (offline every boot, autostart-at-boot retired),
  CONTINUOUS collection loop (`continuous` default on — back-to-back passes, no
  interval idle: the "scraping stopped" fix), per-country round-robin ordering
  (`round_robin_interleave` — breaks the US-volume bias). REMAINING: the
  onboarding country/language picker, the explainable "cycle N, X/Y countries,
  next: cc" detail, and demoting the arbitration modal (frontend).
- ⬜ **No source cap — remove `max_sources_per_run`** (any cap = unjustifiable
  selection); cover every source + all modes via continuous round-robin.
  (maintainer 2026-06-13; Step 5)
- ⬜ **Bandwidth priority ladder** (ordering ≠ exclusion): markets/commodities/
  weather → interactive DDG → RSS → recursive crawl (headroom only); surfaced +
  tunable in the task manager. (maintainer 2026-06-13; Steps 2/5/7)
- ✅ **Collect tab → Settings (PR #145)** — the Collect tab left the sidebar; its
  scheduler/manual/batch controls now live under **Settings → Collect** (`#set-collect`).
  `showTab('ingest')` redirects → Settings + the Collect subtab, so the palette, the
  "Collect now" buttons, and old `#ingest` links keep working. Absorption-tested
  (`test_collect_tab_moved_into_settings`). NEXT: Sources, then Wikipedia. (Step 6)
- ✅ **Drop guaranteed-fail default feeds** — resolved BY DESIGN (verified
  2026-06-14): the preflight checks robots ONCE per host and never samples where
  robots said no (`feed_preflight._sample`), so `google-hol-*` (all on
  `calendar.google.com`) + `webcal.guru` cost one robots check each, not per-feed;
  the directory still SHOWS every source with its honest verdict (the anti-hiding
  principle — removing them would hide sources). No wasted per-feed cycles to
  remove. (log E)
- 🔨 **RSS conditional GET** (ETag/If-Modified-Since) — shipped: `feed_fetch_state`
  table + fetcher sends conditional headers + 304 handled as a valid result, so
  unchanged feeds are skipped (93% duplicate rate). (log F) REMAINING: per-feed
  backoff for feeds that never send an ETag → folds into continuous collection.
- ✅ **Discovery: filter commerce/storefront candidates** (shop./store./*prints)
  — `is_commerce_domain` drops storefront candidates from the citation channel.
  (log D)
- ⬜ **DDG-discovered ingest from Advanced search** (maintainer 2026-06-13) —
  "search + scrape the top X DuckDuckGo results", ingested as articles + an
  indirect-source provenance record (query · date · rank · region · "via DDG").
  Guardrails: EthicalFetcher per result (robots fail-closed, kill switch,
  proxy), consent + visible job, a distinct filterable provenance class, rank
  as a first-class signal, bit-for-bit de-dup (already-present ⇒ multi-path
  provenance), and the ranking-bias disclosure. Entry lives in Group F's
  Advanced-search tab. (CLAUDE.md ledger has the full ruling.)

## C. The task manager (a window, not a bubble)

- 🔨 **Dedicated tabbed window** (Active · Queue · Sources/Schedule · History ·
  System), replacing the vitals popover; minimized animated indicator opens it.
  SLICE 1 SHIPPED (#130): the popover is now a wider tabbed WINDOW via `ooSubtabs`
  (Tasks + System) opened from the activity chip; render/poll reused unchanged
  (`test_ui_invariants` #20). REMAINING: split Tasks → Active/Queue, add
  History + Sources/Schedule, and the per-job controls below.
- 🔨 **Per-job controls**: pause · resume · cancel · ↑/↓ reorder SHIPPED for BOTH
  bulk-download kinds (wiki dumps + OSM regions) via the ONE `_jobRow` renderer
  (Item 2, 2026-06-16; resume routes through `ensureOnline`, invariant #14;
  `_dl_actions` makes paused/failed offer Resume; `test_ui_invariants` #20d +
  `tests/test_jobs_resume.py`). REMAINING: % is shown; rate · speed · ETA ·
  bandwidth cap are DEFERRED — the owners report only bytes/percent, so an honest
  rate/ETA needs owner-measured bytes-over-time in the managers (never a
  client-side guess across the adaptive poll) and the cap needs a throttling
  backend that does not exist yet.
- ⬜ **Download-manager arbitration**: every network task a visible job;
  new requests queue, never a swallowed modal. (SCRAPING plan Step 7)

## D. First-launch & install UX

- ⬜ **Auto-launch the app** when install completes (fluid finish).
- ⬜ **Encryption choice → the app's initial screen** (primary path; terminal
  prompt demotes to headless fallback).
- ✅ **Unlock screen uses THE canonical eye** (#134) — `unlock.html` now draws the
  pointed-oval + #-grid iris, identical to index.html / `assets/icon.svg`; the old
  double-arc eye is gone. `test_ui_invariants` #5 extended to `unlock.html`.
- ⬜ **Guided setup wizard** (keystone #6) — language · encryption · sources by
  theme (from the catalog tag taxonomy) · country/language emphasis · consented
  first collect. Replaces the onboard card.
- 🔨 **Card strings into i18n** — onboard "corpus is empty" card DONE (h2/p/
  button keyed ×12; the i18n engine auto-translates the static card once keyed).
  REMAINING: the server-built card titles (template-translation design).

## E. The UI shell & navigation grammar

- ✅ **Universal subtab component** (keystone #3) — `ooSubtabs(nav, onSelect)`:
  one reusable `<nav.tabs>`+`data-tab` helper owning ARIA (tablist/tab/aria-selected),
  keyboard nav + roving tabindex, click, and `{select,paint}` for programmatic
  switches; no inline onclick; labels auto-translated ×12; hover-bubble aware.
  Reused on 3 surfaces (Insights, Settings, corpus window — the divergent
  data-ins/data-set/data-ctab impls unified). `test_ui_invariants` #18. Next
  adopters: Home families, Markets categories, the analysis window.
- ✅ **Minimal top bar (§2, #143)** — search · status (health/llm) · a PERSISTENT
  task-manager button (#tm-open) · help · language · airplane. The always-visible
  vitals strip moved into the task-manager window's System tab (amends invariant #4,
  ruled 2026-06-14); the raw `/docs` link left the chrome (kept in the ⌘K palette +
  the Help tab). The 5 s chrome poll is now network-only.
- ✅ **Airplane button → top bar**, no text (hover only), distinct online/offline
  transition colors. #133: direction-aware transition flash (go-on = live accent,
  go-off = calm/grounded) — `test_ui_invariants` #14c. #139: the button MOVED to
  the top-bar status cluster, icon-only (label dropped; FILL + hover convey state;
  consent + coachmark unchanged) — invariant #14 refined (glyph+FILL, not label).
- ✅ **Airplane-mode onboarding coachmark** — `#net-coach`: a dismissible bubble
  anchored to the airplane button inviting "switch off airplane mode to go online
  and start collecting"; invitation layer only (routes through the consent popup,
  never bypasses it — `test_ui_invariants` #14b); prominent → subtle → retired,
  ×12 locales. Follows the button when the top-bar move lands. (ruling 2026-06-13)
- ✅ **Home redesign** (2026-06-14) — hero removed (#126); compact at-a-glance
  strip pinned at the TOP; Quick actions removed (#128); denser cards (4+) + card
  families as vertical subtabs via `ooSubtabs` with an "All cards" default lens +
  family-color accents (#129). `test_ui_invariants` #19/#19b.
- ✅ **Insights** — sections already presented as subtabs (via `ooSubtabs`, #127);
  the "Index corpus" button + palette action are removed and replaced by a silent
  background top-up that runs on Insights open when behind (`autoIndexInsights`),
  on top of the existing index-at-ingest hook (#132). `test_ui_invariants` #21.
- ✅ **Trends → click-to-enlarge interactive chart** (Item 1) — each Trends 3-window
  sparkline carries a ⛶ → `enlargeTrend(wi,ti)` → the reusable
  `chartEnlarge(title,seriesList,caveat)` modal `<dialog id="chart-enlarge">`, opening
  the term's daily series as a full interactive `ooChart` (invariant #16: zoom/pan/
  readout/legend; Item-Y bars when n<10). No extra fetch (series already in the
  `_trending-windows` payload); zero new i18n; caveat visible. `test_ui_invariants`
  #21b++. REMAINING: the wider Trends redesign (remove the Insights search bar once the
  omnibar absorbs term-exploration).

## F. The analysis window (corpora system — the flagship)

- 🔨 **Enter → corpus-of-articles window** (keystone #4) — SLICE 1 SHIPPED: a
  full-screen `#analyze` tab (sidebar + Search-tab "Analyze →" button) driven by
  `ooSubtabs` with **Keywords** (new article-set endpoint
  `/api/insights/corpus-keywords` → `queries.corpus_keywords`, bounded+disclosed,
  counts-only) and **Articles** subtabs; keyword chips open the existing keyword
  corpus window. `test_ui_invariants` #22 + `test_corpus_keywords`. REMAINING:
  When/Where/Who · mindmap · links · source-competitive · sentiment subtabs (each
  its own article-set aggregation), the Advanced-search tab, and search-Enter wiring.
- ⬜ **Search bar** — bigger, always-on; remove the visible Ctrl-K hint;
  permanent **Advanced** button; shortcuts list → Help + editable in Settings.
- ⬜ **The seven entries** into the same window (hand-select, tag-click,
  keyword-click, date-keyword, commodity-click, search-enter, …).
- 🔨 **Invariant #6e sweep** — one `extLink()` helper now routes EVERY outbound
  source link through the local preview: search rows, markets board, world-law,
  agenda/events, insights context (8 sites converted; `test_ui_invariants`
  guards no bare `source ↗` remains). REMAINING: the standalone reader page
  (`/api/articles/{id}/view`) if it renders its own external links server-side.

## G. Markets / commodities

- ✅ **Split graphs into category tabs** (universal subtabs) — `renderDashboard`
  groups by `s.category` into `ooSubtabs` (`_mktCatTabs` / `selectCommodityCat`),
  data-driven (only present categories), "All" default lens, skip when one category.
- ✅ **Time-scope picker** replaces the 5-choice range (begin/end/timescale,
  built once as `ooTimeScope`, shared with search; PR #197).
- ✅ **Sparse-series data-point bug** — the `<2`-points fallback that dumped full
  history (so "1 month" paradoxically showed the most points) is gone:
  `renderDashboard` respects the window and `dashChartSvg` renders honestly — a
  line only when dense (`lineMin=8`), else discrete dots with `n` + the
  early-corpus caveat. (invariant #16; `test_ui_invariants`)
- ✅ **Click a graph → the analysis window** (Item 3, Group F) — the card title ⊞ +
  "Analyse ↗" open `openAnalysisFor` (the bottom-of-page `#mkt-chart` price detail stays,
  the Desk lesson). The **price curve + article-timeline OVERLAY** ships as a
  commodity-gated **Price** subtab (`#an-price`): `commodityOverlaySvg` draws a
  time-aligned DUAL-AXIS SVG — price line (left axis, real sample dots) over corpus
  coverage bars (right axis) on a shared time X, each on its OWN labelled scale (no
  magnitude conflation). Seed map = `COMMODITY_QUERY`; co-occurrence never causation
  (visible); reuses existing endpoints; `test_ui_invariants` #22b. Browser-unverified.
- ✅ **S&P500 reclassify** — already an index: it lives in `index_feeds.yml`
  (category `index`) and `list_series` excludes index symbols from the commodities
  board; the dashboard filters `category !== "index"`. Test-guarded now. REMAINING
  (separate): expand commodity feeds (rare earths, oil, gas, LNG, sand, cereals,
  sugar…) — needs clearnet-verified, robots-permitting sources (maintainer-machine
  step; dev sandbox blocks FRED).

## H. Wikipedia (content-first + living source)

- ✅ **Flat edition picker** (invariant #1, amended 2026-06-16) — both pickers
  (`wiki-lang` watched + `dump-lang` dumps) drop the continent `<optgroup>`
  grouping and render ONE flat list, UI-locales-first then largest-edition-first
  (`languages_ui_first()`); labels lead with the native name (autonym, #15).
  `/api/wiki/languages` no longer emits `groups`. `tests/test_wiki_languages.py`
  pins the flat/UI-first/`no groups` contract.
- ⬜ **Auto-watch all 12 UI-language editions by default.**
- ⬜ **Wikipedia tab → Settings** (test-gated).
- 🔨 **Inline auto size estimates** (invariant ruling 2026-06-16) — BUNDLED-TABLE
  HALF SHIPPED: `src/wiki/dump_sizes.py` (`DUMP_SIZES_AS_OF` + per-edition approx
  multistream sizes + freshness test) feeds `/api/wiki/languages?scope=dumps`
  (`size_estimate_bytes` + `size_estimate_as_of`); the picker shows `· ~X GB`
  inline + a dated caveat (×12), zero-network. REMAINING: drop the per-edition
  "Estimate size" probe, replace with ONE consented single-call dumpstatus refresh.
- ⬜ **Dumps decided at first run; non-blocking; task-manager controls**
  (rate/%/speed/cap/ETA/pause/resume/prioritize).
- ⬜ **Dedicated tracked-changes tab** (the full-attention GUI).
- 🔨 **Dumps → corpus ingestion path** (the living-source design) — shipped a
  bounded slice: `ingest_dump_pages(wiki, titles)` + `POST /api/wiki/dumps/
  corpus-ingest` read an operator-chosen title list from the local dump (offline)
  and upsert via the shared `upsert_wiki_corpus_article` (one index hook; canonical
  URL keys it so live sync updates the same row). REMAINING: whole-dump streaming
  ingest (the millions-of-pages baseline) + the auto-track-after-download design.

## I. Backup / restore

- ✅ **Restore is additive-only** — the destructive replace paths
  (`/api/database/restore`, `/api/safety/restore/encrypted`, `restore_from_bytes`,
  `restore_encrypted_backup`) are REMOVED; the merge engine is the ONLY restore.
  Legacy "Restore (destructive)" UI retired; guard test forbids any replace path
  returning. Torture suite still 10/10.

## J. Settings additions

- 🔨 **In-app Ollama + model installer** — backend slice 1 SHIPPED: `OllamaClient.pull`
  (streams ollama's real /api/pull progress) + `.remove`; `POST /api/llm/pull` (NDJSON
  StreamingResponse) + `POST /api/llm/remove`; kill-switch + loopback + model-name
  validation; tests in test_llm_ollama.py.
  SETTINGS LLM SUBTAB UI SHIPPED 2026-06-16 (conservative, browser-unverified): a dedicated
  Settings → **Models** subtab (`data-tab="models"` / `#set-models`, Q6=A — the read-only
  panel moved out of General) with explicit actions over the existing endpoints — **pull**
  (raw `fetch` reading the NDJSON stream → live status/percent, invariant #20), **remove**,
  and the **active-model** picker (`Set active` → `PUT /api/settings {llm_model}`, Q10) +
  per-catalog-row Pull buttons + a free-text "pull any tag" box (Q8). Pulling is gated by
  the ONE consent (`ensureOnline`, #14) with a VISIBLE clearnet-egress disclosure (the
  bytes go over clearnet via the Ollama process, NOT Tor — Q9); +27 i18n ×12;
  `test_ui_invariants` #28. REMAINING: the binary installer (Q7=B — BLOCKED offline: needs
  real per-OS installer checksums verified against clearnet, can't fabricate; do on a
  networked machine), the live ollama.com library browse (Q8), pulls as task-manager jobs.
- ⬜ **In-app Ollama + model installer (orig note)** — detect/install, catalog picker (size/
  RAM/license, never a score), pulls as task-manager jobs. (designed)
- ⬜ **App self-update via the GUI** — signed backup → install snapshot → staged
  migration → atomic swap → rollback; data/keys survive by construction.
  (designed in FUTURE_DEVELOPMENTS)
- ⬜ **Sources tab → Settings** (test-gated).
- ⬜ **Download config section** — the scraping mechanics' home (pace, politeness,
  proxy/Tor, parallelism, mirrors, retry, dump languages).

## K. Bugs (diagnosed this session)

- ✅ **Back button → passphrase** — FIXED: tab nav now `pushState`s (+ a popstate
  handler re-renders; initial load replaces), and every hop to/from `/unlock`
  uses `location.replace`, so Back navigates tabs and never returns to the
  unlock screen. `tests/test_back_button_nav.py` pins it.
- 🐛 **"Scraping stopped"** = the interval scheduler idling, not a crash —
  resolved by continuous collection (group B).

## L. Docs ↔ app reciprocity

- ✅ **USER_MANUAL** gains Agenda, Indices, and Task-manager sections (#135) —
  §3.0a Activity & Task manager, §3.5a Indices, §3.6b Agenda + TOC links.
- ✅ **SECURITY.md** — the current-version line is now version-agnostic (no more
  stale "v0.0.7"); the historical "v0.0.7 audit" reference is kept as a record.
- ✅ **RC-gate** kill-switch row marked ✅ (T2 shipped it: invariant #14 +
  tests/test_network_consent.py).
- ✅ **Ledger figure drift** — test count → 1118 (collected 2026-06-14); chrome
  tail → ~423 untranslatable (263 keyed of 686).

## M. Geo / offline mapping (promoted active 2026-06-16)

- 🔨 **OSM per-region download manager** — Geofabrik-style extracts managed like wiki
  dumps (task-manager job, parallel, reorderable, rate/%/ETA/pause/resume/cap, inline
  dated `OSM_SIZES_AS_OF` size table + one consented refresh). (CLAUDE.md geo ruling)
  CATALOG SUBSTRATE SHIPPED 2026-06-16: `src/geo/osm_regions.py` (`OSM_SIZES_AS_OF` +
  continent/planet extracts with approx dated `.osm.pbf` sizes + path-safe code
  validation + freshness test, mirroring `wiki/dump_sizes`) + `GET /api/geo/regions`
  (zero-network, largest-first, dated caveat). tests/test_osm_regions.py.
  DOWNLOAD-MANAGER BACKEND SHIPPED 2026-06-16: `src/geo/osm_downloads.py`
  (`OsmDownloadManager`, a self-contained mirror of `wiki.dumps.DumpDownloadManager`
  keyed on region code — resumable HTTP-Range, persisted reorderable queue, parallel up
  to `OO_OSM_CONCURRENCY` (default 2) with the excess QUEUING, pause/resume/cancel; every
  fetch through `guarded_session` so the kill switch refuses it + per-URL Tor circuit
  isolation; planet → the OSM planet mirror, continents → Geofabrik) + the additive
  endpoints in `src/api/geo.py` (`GET /downloads`, `POST /downloads/start|pause|resume`,
  `DELETE /downloads`, `POST /downloads/reorder`; catalog-validated → 404 for unknown
  regions, path-safe → 400). tests/test_osm_downloads.py (19: URL/path-safety, the
  download loop, parallel+queue+reorder, reload demotion, the guarded-token transport,
  the API). SETTINGS FRONTEND SHIPPED 2026-06-16 (conservative, browser-unverified):
  a new **Settings → Offline map** subtab (`data-tab="offlinemap"` / `#set-offlinemap`,
  in `showSetCat`) with a zero-network region picker over `/api/geo/regions` (dated `~X GB`
  estimates) + a resumable download-job table over `/api/geo/downloads` (`loadOsmMap` /
  `loadOsmDownloads` / `startOsmDownload` / `pauseOsm` / `resumeOsm` / `deleteOsm`, mirroring
  the wiki dump UI); STARTING a download passes the ONE consent popup (`ensureOnline`,
  invariant #14) so it is refused under airplane mode; +9 i18n keys ×12; `test_ui_invariants`
  #27 asserts the panel + loader + endpoints + the ensureOnline gate.
  TASK-MANAGER JOBS WIRING SHIPPED 2026-06-16: `_osm_jobs()` in `src/api/jobs.py` surfaces
  OSM region downloads in the unified `/api/jobs` view alongside wiki dumps (kind
  `osm-map`, real queue_position, progress, actions) — aggregated live, no shadow state;
  a downloading extract writes a FILE so it never trips the DB-writer arbitration ask;
  `cancel_job` handles `osm:` ids (pause, resumable) + `POST /api/jobs/osm/reorder`.
  PER-JOB UI CONTROLS SHIPPED 2026-06-16 (Item 2): the task-manager `_jobRow` now
  renders OSM downloads with pause/↑↓-reorder/cancel + a RESUME button for paused/failed
  jobs (kind-aware reorder; `jobResume` → `ensureOnline` → `POST /api/jobs/{id}/resume`,
  backed by new `OsmDownloadManager.resume` / `DumpDownloadManager.resume`); see Group C.
  tests/test_osm_jobs.py. REMAINING: the per-job rate/%/ETA/cap CONTROLS in the
  task-manager window UI (frontend), country sub-extracts, the consented exact-size
  refresh, and the hand-rolled offline map renderer.
- ⬜ **Hand-rolled offline vector map** — canvas 2.5D / CSS-3D, NO WebGL/Three.js; reuse
  the bundled Natural-Earth coastline + the temporal-map projection.
- ⬜ **Temporal-map remainder** — linear/log toggle + mention layer fed by event-places.

## N. Official-statistics ingestion (promoted active 2026-06-16)

- 🔨 Gov + international agencies as CONTROVERSIAL sources; producing-state + agency +
  pub-date + methodology-ref per figure; VINTAGES; comparability guards (SA/NSA/base
  year); SDMX/API before scraping; triangulate side-by-side never averaged; forecasts
  join IPCC-tracking; per-continent coverage; deliberately BRICS/Africa/forgotten-region.
  (FUTURE_DEVELOPMENTS design)
  DATA-LAYER SUBSTRATE SHIPPED 2026-06-16: `src/stats/agencies.py` (a curated, global
  directory — IGOs + national producers across all 6 inhabited continents, BRICS +
  Africa deliberately included; each flagged `controversial`, descriptive only, no
  figures/scores/network) + `GET /api/stats/agencies` (+ `continents_covered` coverage
  metric). tests/test_stat_agencies.py.
  INGEST-AS-SOURCES SHIPPED 2026-06-16: `src/stats/ingest.py`
  (`ingest_agencies_as_sources`) registers each agency as a DISABLED `Source`
  (`enabled=False`, `source_type="statistics"`, low priority, country lowercased / None
  for IGOs, `language=None`, tags `official-statistics,controversial,<region-slug>`;
  `reliability_score` left NULL — never fabricated) keyed by `registrable_domain`;
  ADDITIVE + IDEMPOTENT (existing domains untouched, never clobbered); caller owns the
  txn (single-writer gate). `POST /api/stats/sources/ingest` runs it (LOCAL DB write, no
  network/consent). tests/test_stats_ingest.py (11: disabled/controversial/no-score,
  idempotent, skip-existing-without-clobber, endpoint).
  SETTINGS FRONTEND SHIPPED 2026-06-16 (conservative, browser-unverified): a Settings →
  **Statistics** subtab (`data-tab="stats"` / `#set-stats`) — a DESCRIPTIVE directory over
  `GET /api/stats/agencies` (name/acronym/scope/country/region + a per-row `controversial`
  pill + the continents-covered coverage line; home URLs via `extLink` so they open the
  LOCAL preview, invariant #6; no figures/score) + a one-click "Register as sources" button
  over `POST /api/stats/sources/ingest` (idempotent local DB write, no consent gate, tally +
  caveat shown); +19 i18n ×12; test_ui_invariants.
  SDMX/WORLD-BANK PARSER CORE SHIPPED 2026-06-16 (Item 5, offline): `src/stats/sdmx.py` —
  a PURE (network-free) parser turning already-decoded official responses into
  provenance-rich `StatFigure` rows. `parse_worldbank` (World Bank API v2 JSON
  `[meta,[obs]]`) + `parse_sdmx_json` (SDMX-JSON 2.1 data message, Eurostat/IMF — resolves
  each series+observation key back to its dimension value ids: ref_area / indicator /
  time_period, surfacing unit/adjustment/base_year ONLY when stated). Honesty enforced in
  code: NO score/ranking, never averages producers; `extracted_at` is the caller-stamped
  VINTAGE (verbatim, never overwritten); a published gap → `value=None` (Eurostat's `:`
  too) — never 0, never dropped. `tests/test_sdmx_parse.py` (9: both shapes, gaps, absent
  vs present comparability, base-year-only-when-stated, vintage stamping, no-score). The
  LIVE fetch through the guarded factory + consent + a visible job, the figure-level
  provenance/vintages DB schema, side-by-side triangulation, and the filterable registered-
  sources view are the REMAINING follow-up slices (this PR is the offline, fixture-tested
  parser only).

---

## Proposed order (foundations → content-first → polish)

A (writer queue, polling) → B (parallel, auto-collect) → C (task manager) →
D (wizard + install) → E (shell + Home) → F (analysis window + search) →
G/H (markets + Wikipedia, which reuse E/F) → I/J (backup + settings) →
K/L (bugs + docs, folded in as each group lands). Designed-only items
(self-update, Ollama installer, Open Commons Mirror, voice mode, newsletter)
stay documented until explicitly scheduled.
