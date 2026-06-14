# Grouped backlog — the 2026-06-13 build plan

> **Status:** living synthesis (maintainer-asked 2026-06-13 "I'd prefer the list
> in groups"). One PR per item, stacked onto `0.09`, foundations first. Detail
> for each group lives in the named design docs (`SCRAPING_AUTOMATION_PLAN.md`,
> `UI_SHELL_REDESIGN_PLAN.md`, `FUTURE_DEVELOPMENTS.md`) and the CLAUDE.md ledger.
> Legend: ✅ shipped (PR) · 🔨 in progress / next · ⬜ queued · 🐛 bug.

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
- ⬜ **mypy ratchet pay-down** toward 0 (ongoing); **Win/macOS portability
  lanes → green** then graduate to required. 🔨 IN PROGRESS: the Windows
  `UnicodeDecodeError` class (text `open()` without `encoding="utf-8"`) is fixed
  + ratcheted (`tests/test_utf8_file_io.py`). REMAINING Windows classes:
  `install.sh` tests run `bash` under WSL (no distro on the runner — should skip
  on native Windows), `WinError 32` file-in-use on SQLite temp unlinks, and the
  `/tmp`↔`/private/tmp` / `D:\tmp` path-canonicalization tests (also the macOS
  pair). Tackle per-class; not locally verifiable on the Linux box.

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
- ⬜ **Collect tab → Settings → Download** (test-gated removal). (Step 6)
- ⬜ **Drop guaranteed-fail default feeds** (Google holiday calendars 100%
  robots-denied, webcal.guru, etc.). (log E)
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

- ⬜ **Dedicated tabbed window** (Active · Queue · Sources/Schedule · History ·
  System), replacing the vitals popover; minimized animated indicator opens it.
- ⬜ **Per-job controls**: rate · % · speed · bandwidth cap · ETA · pause ·
  resume · prioritize · de-prioritize.
- ⬜ **Download-manager arbitration**: every network task a visible job;
  new requests queue, never a swallowed modal. (SCRAPING plan Step 7)

## D. First-launch & install UX

- ⬜ **Auto-launch the app** when install completes (fluid finish).
- ⬜ **Encryption choice → the app's initial screen** (primary path; terminal
  prompt demotes to headless fallback).
- ⬜ **Unlock screen uses THE canonical eye** (invariant #5; extend the test).
- ⬜ **Guided setup wizard** (keystone #6) — language · encryption · sources by
  theme (from the catalog tag taxonomy) · country/language emphasis · consented
  first collect. Replaces the onboard card.
- 🔨 **Card strings into i18n** — onboard "corpus is empty" card DONE (h2/p/
  button keyed ×12; the i18n engine auto-translates the static card once keyed).
  REMAINING: the server-built card titles (template-translation design).

## E. The UI shell & navigation grammar

- ⬜ **Universal subtab component** (keystone #3).
- ⬜ **Minimal top bar** — only: search · status · task-manager · help ·
  language · airplane (everything else below the subtabs).
- ⬜ **Airplane button → top bar**, no text (hover only), distinct online/offline
  transition colors coherent with the icon state.
- ✅ **Airplane-mode onboarding coachmark** — `#net-coach`: a dismissible bubble
  anchored to the airplane button inviting "switch off airplane mode to go online
  and start collecting"; invitation layer only (routes through the consent popup,
  never bypasses it — `test_ui_invariants` #14b); prominent → subtle → retired,
  ×12 locales. Follows the button when the top-bar move lands. (ruling 2026-06-13)
- 🔨 **Home redesign** — hero card REMOVED (✅ 2026-06-14: block + greeting JS +
  `.hero` CSS deleted; Home opens on the Briefing). REMAINING: at-a-glance stats
  strip pinned on top; remove quick-actions; full-width denser cards (4+); family
  colors as vertical subtabs with an "All cards" default.
- ⬜ **Insights** — auto-index in the background (remove the "Index corpus"
  button); present sections as subtabs.

## F. The analysis window (corpora system — the flagship)

- ⬜ **Enter → corpus-of-articles window** with consistent sub-tabs (keyword ·
  mindmap · link · source · When/Where/Who · sentiment · related) + the
  search-only **Advanced search** tab. (keystone #4)
- ⬜ **Search bar** — bigger, always-on; remove the visible Ctrl-K hint;
  permanent **Advanced** button; shortcuts list → Help + editable in Settings.
- ⬜ **The seven entries** into the same window (hand-select, tag-click,
  keyword-click, date-keyword, commodity-click, search-enter, …).
- ⬜ **Invariant #6e sweep** — external links open the local preview everywhere
  (reader, search rows, markets/law/wiki), not just Home cards.

## G. Markets / commodities

- ⬜ **Split graphs into category tabs** (universal subtabs).
- ⬜ **Time-scope picker** replaces the 5-choice range (begin/end/timescale,
  built once, shared with search).
- ✅ **Sparse-series data-point bug** — the `<2`-points fallback that dumped full
  history (so "1 month" paradoxically showed the most points) is gone:
  `renderDashboard` respects the window and `dashChartSvg` renders honestly — a
  line only when dense (`lineMin=8`), else discrete dots with `n` + the
  early-corpus caveat. (invariant #16; `test_ui_invariants`)
- ⬜ **Click a graph → the analysis window** (group F), not bottom-of-page;
  price curve with the article timeline overlaid.
- ⬜ **S&P500 reclassify** as an index; expand feeds.

## H. Wikipedia (content-first + living source)

- ⬜ **Auto-watch all 12 UI-language editions by default.**
- ⬜ **Wikipedia tab → Settings** (test-gated).
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

- ⬜ **In-app Ollama + model installer** — detect/install, catalog picker (size/
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

- ⬜ **USER_MANUAL** gains Agenda, Indices, and Task-manager sections.
- ⬜ **SECURITY.md** stale "v0.0.7" → current.
- ⬜ **RC-gate** kill-switch row is stale (T2 shipped it) — sweep neighbours.
- ⬜ **Ledger figure drift** (test count 961 → 1056; chrome tail 473 → 434).

---

## Proposed order (foundations → content-first → polish)

A (writer queue, polling) → B (parallel, auto-collect) → C (task manager) →
D (wizard + install) → E (shell + Home) → F (analysis window + search) →
G/H (markets + Wikipedia, which reuse E/F) → I/J (backup + settings) →
K/L (bugs + docs, folded in as each group lands). Designed-only items
(self-update, Ollama installer, Open Commons Mirror, voice mode, newsletter)
stay documented until explicitly scheduled.
