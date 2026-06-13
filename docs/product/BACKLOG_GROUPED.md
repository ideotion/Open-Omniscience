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
- ⬜ **Single-writer queue** (keystone #1) — supersedes the retry; serialises
  writes; prerequisite for safe parallel collection.
- ⬜ **UI polling storm** — ~10k polls / 2 h (vitals ×4120, activity ×2747…)
  contend with the encrypted DB; consolidate to one status poll / SSE + adaptive
  backoff. (log finding B)
- ⬜ **keyword_export under contention** — 29→65 s during a live scrape; read
  snapshot for exports. (log finding C)
- ⬜ **mypy ratchet pay-down** toward 0 (ongoing); **Win/macOS portability
  lanes → green** then graduate to required.

## B. The download / scraping subsystem (content-first)

- 🔨 **Parallel downloads** (next) — dumps `max_concurrent` 1 → N (file writes,
  no DB contention) + a bounded fetch worker pool for collect (parallel fetch,
  single writer). The Tor-speed fix: N circuits, not one. (SCRAPING plan Step 2)
- ⬜ **Segmented HTTP-Range** over multiple circuits + `IsolateSOCKSAuth` (one
  big dump, fast). (Step 3)
- ⬜ **Dump mirror selection**. (Step 4)
- ⬜ **Auto-collect after one consent; boot in airplane mode; permanent when
  online**; demote the cross-kind arbitration modal → silent queue. (Step 5)
- ⬜ **Collect tab → Settings → Download** (test-gated removal). (Step 6)
- ⬜ **Drop guaranteed-fail default feeds** (Google holiday calendars 100%
  robots-denied, webcal.guru, etc.). (log E)
- ⬜ **RSS conditional GET** (ETag/If-Modified-Since) + per-feed backoff (93%
  duplicate rate). (log F)
- ⬜ **Discovery: filter commerce/storefront candidates** (shop./store./*prints).
  (log D)

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
- ⬜ **Card strings into i18n** — the onboard "corpus is empty" card and the
  server-built card titles (template-translation design). ×12 locales.

## E. The UI shell & navigation grammar

- ⬜ **Universal subtab component** (keystone #3).
- ⬜ **Minimal top bar** — only: search · status · task-manager · help ·
  language · airplane (everything else below the subtabs).
- ⬜ **Airplane button → top bar**, no text (hover only), distinct online/offline
  transition colors coherent with the icon state.
- ⬜ **Home redesign** — at-a-glance stats strip pinned on top; remove the hero
  card; remove quick-actions; full-width denser cards (4+); family colors as
  vertical subtabs with an "All cards" default.
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
- 🐛 **Sparse-series data-point bug** — the <2-points fallback dumps full
  history, so "1 month" paradoxically shows the most points; respect the window,
  render sparse as honest points. (invariant #16)
- ⬜ **Click a graph → the analysis window** (group F), not bottom-of-page;
  price curve with the article timeline overlaid.
- ⬜ **S&P500 reclassify** as an index; expand feeds.

## H. Wikipedia (content-first + living source)

- ⬜ **Auto-watch all 12 UI-language editions by default.**
- ⬜ **Wikipedia tab → Settings** (test-gated).
- ⬜ **Dumps decided at first run; non-blocking; task-manager controls**
  (rate/%/speed/cap/ETA/pause/resume/prioritize).
- ⬜ **Dedicated tracked-changes tab** (the full-attention GUI).
- ⬜ **Dumps → corpus ingestion path** (the living-source design).

## I. Backup / restore

- ⬜ **Restore is additive-only** — never replaces the corpus; remove the legacy
  replace path entirely (the merge engine already behaves additively).

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

- 🐛 **Back button → passphrase** — tab nav uses `replaceState` + a locked API
  hard-navigates to `/unlock`; fix = `pushState` for tabs + `replaceState` to
  "/" after unlock.
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
