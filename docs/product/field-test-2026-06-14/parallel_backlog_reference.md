# Parallel-session remaining-work backlog (supplied by maintainer 2026-06-14)

Source: parallel session's interpretation of docs/product/BACKLOG_GROUPED.md.
Use this as the canonical "already-tracked" list for duplicate detection against
field-test remarks. ✅ done omitted by the maintainer; 🔨 = partly shipped.
NOTE: groups jump A,B,C,D,E,F,G,H,J,L — no Agenda-content group present here.

## A. Foundations & engineering health
- UI polling storm — consolidate ~10k polls/2h (vitals/activity/status/network/jobs)
  into ONE status endpoint on a single timer (or SSE push) + adaptive backoff when
  hidden/idle; lean on scheduler/airplane push.
- keyword_export under contention — exports slow 30→65s sharing the one SQLCipher conn
  with the writer; give exports a read snapshot (separate read conn / WAL snapshot).
- mypy ratchet → 0 + Win/macOS lanes green — keep mypy under baseline; fix Win/macOS
  test classes (WSL-bash skip, WinError 32 temp-unlinks, /tmp canonicalization) until
  observation lanes pass, then require them.

## B. Download / scraping subsystem
- Segmented HTTP-Range — one big dump as parallel byte-range segments, each over its
  own Tor circuit (IsolateSOCKSAuth), reassembled.
- Dump mirror selection — choose among Wikipedia dump mirrors (latency/availability);
  selectable or auto-best.
- Auto-collect remainder — shipped: boot-airplane + continuous loop + round-robin.
  Remaining: first-run country/language emphasis picker; explainable schedule readout
  ("cycle N, X/Y countries, next: cc"); demote cross-kind arbitration modal to a silent
  task-manager queue entry.
- No source cap — remove max_sources_per_run entirely; continuous round-robin covers
  every source over time. Ordering != exclusion.
- Bandwidth priority ladder — under limited bandwidth: markets/commodities/weather →
  interactive DDG → RSS → recursive crawl (headroom only); surfaced + tunable in task
  manager; weight by freshness-due/cost/interactivity.
- Collect tab → Settings → Download — move Collect out of the sidebar into Settings →
  Download (content-first); absorption-test gated.
- Drop guaranteed-fail default feeds — remove 100%-robots-disallowed defaults (Google
  holiday calendars, webcal.guru, etc.); fail-closed stays, don't ship known-dead defaults.
- RSS conditional-GET remainder — shipped: ETag/If-Modified-Since + 304. Remaining:
  per-feed backoff for feeds that never send an ETag.
- DDG-discovered ingest from Advanced search — opt-in "search + scrape top X DDG
  results", ingested as articles via the ethical fetcher + indirect-source provenance
  (query·date·rank·region·"via DDG"); consent + visible job; distinct filterable
  provenance class; rank first-class; bit-for-bit de-dup; ranking-bias disclosed.

## C. Task-manager window
- Dedicated tabbed window — replace vitals popover with OS-style window (Active · Queue
  · Sources/Schedule · History · System); minimized animated top-bar indicator opens it;
  aggregates live from owning systems (no shadow state).
- Per-job controls — rate · % · speed · bandwidth cap · ETA · pause · resume ·
  prioritize · de-prioritize.
- Download-manager arbitration — every network task a visible job; new request while one
  runs QUEUES (never a swallowed modal); DB-writer collisions serialize invisibly.

## D. First-launch & install UX
- Auto-launch the app — install.sh opens the running app when install finishes.
- Encryption choice → app's first screen — in-browser first-launch PRIMARY; terminal
  prompt demotes to headless/env fallback.
- Unlock screen canonical eye — /unlock draws THE canonical eye (invariant #5); today a
  different double-arc eye; extend the invariant test to unlock.html.
- Guided setup wizard — one-time GUI: language → encryption → sources BY THEME (catalog
  tag taxonomy) + country/language emphasis → consented first collect. Replaces #onboard
  card; ×12; informed-consent layering; one-time state a visible setting.
- Card strings → i18n remainder — onboard card done; remaining: server-built home-card
  TITLES need template-based translation design (titles carry data values), ×12.

## E. UI shell & navigation grammar
- Universal subtab component — IN PROGRESS NOW. One reusable subtab helper (sidebar =
  main tabs; vertical subtabs near top = facets), ARIA/keyboard/i18n/hover-aware,
  unifying Insights/Settings/corpus-window; invariant-tested.
- Minimal top bar — above subtabs ONLY: search · status · task-manager · help · language
  · airplane. Vitals → task-manager System tab; constant footprints; version out of chrome.
- Airplane button → top bar — move up, no text (hover bubble), glyph+FILL=state, but
  DIFFERENT transition colors by direction (offline vs online); today one red transition
  conflates both.
- Home redesign remainder — hero removed; remaining: at-a-glance stats strip pinned
  compact at top; remove Quick actions; denser full-width cards (4+ fit); family-type
  colors as vertical subtabs with "All cards" default.
- Insights auto-index + subtabs — remove "Index corpus" button + palette action; index
  follows ingest with honest "indexed through <time>"; Insights sections as subtabs.

## F. Analysis window (the flagship)
- Enter → corpus-of-articles window — Enter opens ONE analysis window over matched
  articles with sub-tabs (keyword · mindmap · link · source · When/Where/Who · sentiment
  · related) + a search-only Advanced-search tab. Single most-requested piece.
- Search bar bigger + always-on — larger, permanent; remove visible "Ctrl K" hint;
  permanent "Advanced" button; shortcuts → Help + editable Settings keybindings panel.
- The seven entries — all seven routes open the SAME window: hand-select, tag-click,
  keyword-click, date-keyword, commodity-click, search-enter, search-result.
- Invariant #6e sweep — EVERY external link opens the local preview popup first (reader,
  search rows, markets/law/wiki), not just Home cards.

## G. Markets / commodities
- Split graphs into category tabs — commodities board splits into category subtabs via
  the universal subtab component.
- Time-scope picker — replace the 5-choice range select with a real begin/end/timescale
  control, shared with search/corpora.
- Click a graph → analysis window — commodity graph opens the Group-F window (keyword-
  family corpus + price curve with article timeline overlaid; co-occurrence != causation).
- S&P500 reclassify; expand feeds — move S&P500 to Indices; add rare earths, oil, gas,
  LNG, sand, cereals, sugar…

## H. Wikipedia (content-first + living source)
- Auto-watch all 12 UI editions — watched entirely + by default in all 12 UI-language
  editions (auto-watch default, not per-page opt-in).
- Wikipedia tab → Settings — move into Settings (content-first); watched corpus surfaces
  in general search/analysis; absorption-test gated.
- Dumps at first-run; non-blocking; task-manager controls — dump choice in first-run
  wizard (size guidance); never delays scraping (own job); full controls in task manager.
- Dedicated tracked-changes tab — per-article tab to scroll/explore/analyze edits over
  time (on stored per-revision full text).
- Dumps → corpus remainder — bounded title-list ingest shipped; remaining: whole-dump
  streaming ingest + auto-track-the-whole-edition-after-download.

## J. Settings additions
- In-app Ollama + model installer — Settings → LLM panel installs Ollama + pulls models
  (checksum-verified via guarded factory; catalog shows size/RAM/license never a score;
  pulls as task-manager jobs; hardware fit measured; clearnet prerequisite).
- App self-update via GUI — consented: signed backup + install snapshot → verified
  release → staged migration → atomic swap + relaunch → rollback on failure; data/keys
  outside code tree survive; never silently decrypt across update.
- Sources tab → Settings — move into Settings (content-first); absorption-test gated.
- Download config section — Settings → Download home for scraping mechanics (pace,
  politeness, proxy/Tor, parallelism, mirrors, retry, dump languages).

## L. Docs ↔ app reciprocity
- USER_MANUAL sections — add Agenda, Indices, Task-manager chapters.
- SECURITY.md version — bump stale "v0.0.7" to current.
- RC-gate sweep — mark kill-switch row (shipped) + sweep neighbouring stale rows.
- Ledger figure drift — update stale numbers (tests 961→1056+, chrome tail 473→434).

## Parked / designed-only (NOT scheduled until maintainer says)
- App self-update / Ollama installer (designs ready; also in J).
- Open Commons Mirror (server-scale sister project; only once app mature, V0.1+).
- Voice-only mode (accessibility-first; local STT/TTS via Ollama).
- Newsletter scraper (blocked until DB-reliability riders + no-recovery premise revisited).
- Official-statistics ingestion (BLS/INSEE/Eurostat/World Bank/IMF + BRICS/Africa;
  vintages + comparability guards).
- Weather-context remainder (anomaly baselines, signal-keywords, reader row, temporal-map overlay).
- Tor embedding + per-source transport (in-app Stem Tor + per-source circuit isolation;
  clearnet-for-hostile only as consented opt-in).
- Convergence "if-this-then-watch" flagship (space-time co-occurrence; alert engine off by default).
- Backups include Wikipedia dumps (carry data_dir/wiki_dumps/, dedup by checksum).
- Smaller parked: event-family merge/split UI; saved-filter smart calendars; offline
  vector map; two-hop keyword graphs.
