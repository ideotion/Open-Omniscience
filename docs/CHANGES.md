# Changelog

> The repository’s **default branch is the active cycle branch** (currently `0.09`); each cycle branch `0.0N` produces release `0.0.N`.

## 0.09 — deeper sense-making (in progress)

The `0.09` cycle is open (the `0.08` cycle below shipped in full, including the
June 2026 live-test hardening batches). On its slate, from the parked queue:
space-time convergence detection + the watch-rule attention engine, SQLCipher
at-rest encryption with the backup redesign, the corpora system (hand- and
tag-selected), the global-search rework, agenda calendar views + catalog depth,
and the i18n long tail. See [`docs/FUTURE_DEVELOPMENTS.md`](FUTURE_DEVELOPMENTS.md).

- **Performance batch (maintainer field report 2026-06-12: 6.4k articles /
  228k keywords / 243 MB corpus got "very slow"; the keyword export failed).**
  Measured on a synthetic corpus of exactly that shape (`scripts/perf_harness.py`,
  deterministic, in-process, zero network), fixed, re-measured — same machine,
  comparative numbers: **keyword diagnostics export 14.1 s → 4.0 s** (encrypted
  profile 33.8 s → 7.8 s) and **streamed** (bounded memory, immediate first
  byte; envelope byte-compatible, contract-tested); **Home briefing recompute
  36.6 s → 1.5 s** (the MinHash inner loop was 95% of it: exact numpy
  vectorisation with a parity-tested pure fallback + a memo across the three
  producers that cluster the same window, audit finding F-005); insights map
  ~550 ms → ~215 ms (tuple aggregation instead of ORM entities). Mechanics
  shipped: a covering index on `keyword_mentions` (model + migration
  `e2f3a4b5c6d7` + boot self-heal for installs that never run alembic);
  per-language cap applied BEFORE the work (semantics unchanged); statement
  deadlines on the heavy read path (typed 503 — "aborted after N s" — never a
  hung UI; `OO_STATEMENT_TIMEOUT_S`, default 60); `PRAGMA optimize` + bounded
  first-boot ANALYZE at startup; `mmap_size` for PLAINTEXT stores only (never
  through the SQLCipher codec — that speed-up cannot exist, so it is not
  claimed); Library/coverage counts cached 30 s with `computed_at`/`cache_ttl_s`
  disclosed in the response; and a **Settings → Database maintenance** tool
  (VACUUM + optimize) reporting real freed bytes, with "reclaimable space" from
  `PRAGMA freelist_count` (+8 chrome strings ×12 locales).

- **Markets/indices: transport-aware honesty (the 2026-06-12 Tor diagnosis).**
  Feed failures now carry a **verdict taxonomy over the real error**:
  *refused* (connection refused/reset — over Tor commonly one exit's refusal;
  the live log imported 21/28 FRED series while others failed in the same
  run) ≠ *robots-disallowed* (the host's choice, honored, never retried or
  evaded) ≠ *dead-series* (HTTP 404/410 — the catalog entry needs a verified
  replacement; retrying cannot help) ≠ *unreachable* ≠ *offline* (kill switch
  engaged). Transient verdicts get ONE bounded feed-level retry on top of the
  fetcher's own backoff; policy verdicts never. The Indices/Markets boards
  list each failure with its verdict and honest note, and a **Retry failed
  feeds** button re-runs exactly the honestly-retryable keys
  (`import-all?keys=`). The dead World-Bank-monthly FRED ids
  (PGOLDUSDM/PSILVUSDM/PSAWMUSDM) now surface as *dead-series* instead of
  undifferentiated failures — replacements await clearnet verification (this
  build environment cannot reach FRED to verify; honesty over speed).
  USER_MANUAL gains the "Running over Tor" chapter. +5 chrome strings ×12.

- **Settings: backup v2 becomes the UI's primary path (the OS-grade mandate's
  last user-facing mile).** Data & backup now leads with the signed archive:
  one passphrase-encrypted file carrying everything (plaintext only as a
  deliberate, explained choice that excludes signing keys), and **Restore =
  merge with a preview**: upload → dry-run plan table per data domain (new /
  already present / conflicts-kept-local, with conflict samples), the
  verification verdict up front, Apply disabled when verification fails (the
  engine would refuse anyway — the UI does not invite it), one-shot commit
  token, safety snapshot stated, import history visible. The legacy
  replace-style tools are demoted into a collapsed "older tools" block —
  available, never silently lost. ~36 chrome strings ×12 locales; UI contract
  pinned by tests.

- **Network switch → airplane mode + online consent (field report #2 item 1).**
  The sidebar toggle is now ONE constant airplane glyph whose **fill is the
  state** (filled = offline engaged) — action glyphs no longer label state.
  **Every offline→online transition passes a single consent popup**: it names
  the action ("Start a collection pass…", "Fetch market and index data…",
  "Download a Wikipedia dump"…) and lists the machine's **local interface
  addresses** read from the kernel's tables (`/api/system/interfaces`,
  psutil) — never a public-IP echo before consent, because that would itself
  be a network call; the popup says honestly that the public address is
  whatever the ISP/VPN presents, unchecked. Scheduler responses now carry the
  network state, so the toggle repaints **immediately** on implicit
  transitions (collect-start clears the kill switch) instead of waiting for
  the 5 s poll. Kill-switch reliability gains a build-failing **socket-importer
  ratchet**: exactly six modules may import an HTTP client (the guarded fetch
  path, loopback Ollama, the gated discovery channel, three wiki fetchers);
  any new direct importer fails the suite until consciously routed through the
  fetch path. UI invariant #14 enforces all of it; +15 chrome strings ×12
  locales.

- **Keyword policy: the three systemic findings from field report #4.**
  (1) **Source self-names are suppressed at extraction** as a per-article
  rule, never a stoplist: a keyword equal to the article's OWN outlet name
  ("The Moscow Times" ×213 in the live export) or domain label is byline/
  footer boilerplate and is skipped — while the same term mentioned by OTHER
  sources stays a real keyword, so coverage *about* an outlet is untouched.
  Re-indexing applies it retroactively (indexing replaces an article's
  mentions). (2) The diagnostics export gains **per_source_concentration**:
  keywords whose articles sit ≥90% in one source while covering ≥25% of that
  source's articles (both sides ≥10) are listed as boilerplate/navigation
  suspects — the Swedish "alla artiklar" ×118 shape — with real counts and
  stated thresholds, strongest first, capped at 200; flagged, never
  auto-hidden. (3) Every exported keyword carries **language_mismatch**:
  true when the stored language disagrees with the signature's dominant
  article language (the de-tagged-English attribution noise) — evidence for
  the operator, never a silent correction.

- **A permanent language switcher in the top bar.** All 12 locales in one
  menu — conventional flag as a visual cue only, the **native name** is the
  identifier (flags ≠ languages); one click re-translates the entire UI
  through the one exact-match engine, keeps the Settings selector in sync,
  and persists locally. Constant top-bar footprint; RTL-aware menu placement.
  UI invariant #15 enforces it.

- **The one chart toolkit (`ooChart`), slice 1.** Interactive charts as
  ruled: cursor-anchored **wheel zoom through time**, **drag-pan**,
  hover/click → exact **pinned X/Y readout**, double-click reset, legend
  chips that toggle series — with the detailed-curves rules built into the
  component: the **full-resolution series always renders** within the visible
  window (never downsampled), and **sparse series render as honest points**
  (n shown, early-corpus caveat, a line only when ≥8 points support it — no
  curve interpolated through 3 dots). Labelled discrete gridlines via the
  shared formatter; ISO week/month buckets parsed natively. Wired first onto
  the markets symbol chart and the Insights keyword trend; UI invariant #16
  enforces the rules. +4 chrome strings ×12.

- **The universal "hover for information" convention.** One consistent,
  theme-aware affordance across the whole UI: anything carrying layered
  information shows a **dotted accent underline** (text) or a **tiny accent
  corner dot** (buttons, pills, icons), and opens one shared styled bubble on
  hover, **keyboard focus, or touch long-press** — capabilities the native
  tooltip never had. Marking is automatic (driven by the translated `title`
  mechanism + a MutationObserver), so new surfaces inherit it and it cannot
  be forgotten; the bubble re-reads the live translated text, so all 12
  languages work by construction. One delegated listener and pure CSS —
  no per-element handlers, no animation loops. UI invariant #17 enforces it.

- **Task manager + download arbitration, slice 1 (the twice-repeated ask).**
  Every network task is now a **visible job**: `/api/jobs` aggregates live
  from the owning systems — the collection pass, every Wikipedia dump with
  its real queue position, the fetch currently on the wire (domain only) —
  deliberately keeping no shadow state, so the view cannot disagree with
  reality. The dump downloader becomes a **true queue** (one download at a
  time; later requests genuinely queue, persisted across restarts) with
  **operator reordering** — the "fr before en" case works end-to-end (↑↓
  buttons + API, tested). The activity-chip popover is now **Tasks &
  collection**: jobs with progress bars and Stop/Pause/Cancel (stopping
  collection states its kill-switch side effect — informed consent), the
  detailed collection panel, hardware vitals as the compact bottom row. New
  heavy starts **ask** when another network task runs (who is busy, proceed
  or wait) — never a silent pile-up. +18 chrome strings ×12.

- **De-US-centring the source catalog (the cycle's KEY POINT, first batch).**
  Three real defects fixed at the root: (1) `Source.country` had a silent
  `default="US"` — every source created without an explicit country was labelled
  American (the live-test "US = 1,553" inflation; the canonicalised catalog's real
  US share is ~14%). The default is gone; unknown is now honestly NULL. (2) Mixed
  country encodings ("US" / "us" / "united-states") across five tables. (3) The
  keyword-mention indexer truncated legacy values into *wrong* codes
  ("china"→`ch`=Switzerland, "germany"→`ge`=Georgia), corrupting the temporal
  map's geography. **One conversion layer** (`src/catalog/countries.py`: all 249
  ISO 3166-1 codes + names + aliases + continents, iso-codes-derived, dependency-
  free) now canonicalises every write path (seed, CSV import, metadata, mention
  indexing) to lowercase ISO-2 and renders **full country names** everywhere
  user-facing. Migration `a3b4c5d6e7f8` canonicalises existing databases,
  re-derives default-suspect US values from the catalog/ccTLD (else NULL — the
  value was never asserted), and rebuilds mention geography from the corrected
  sources. The shipped catalogs (1,750 entries) are rewritten canonical, with a
  regression test rejecting any drift. The Library tab's World coverage panel
  gains **Regional balance** — per-continent sources + countries-covered against
  the working floors in `configs/catalog_targets.yml` (labelled aspirations,
  drafted from the real catalog shape) and a top-country **concentration guard**;
  `scripts/catalog_coverage_report.py` prints the same acceptance metric offline.
  Sources/coverage APIs return `country_name`/regions and accept full-name
  filters; the tab anchor is now `#library` (legacy `#database` links redirect);
  the coverage panel polls live (Refresh button retired). +14 chrome strings ×12
  locales.

## 0.08 part 2 — the sense-making horizon

Part 2 of the `0.08` cycle (the whole roadmap push ships under `0.08` per maintainer
direction; plan: [`docs/product/RELEASE_0.0.8_PLAN_PART2.md`](product/RELEASE_0.0.8_PLAN_PART2.md),
WP1–WP5 all delivered):

- **Methods appendix** (*Search → Methods appendix*): one click turns the current search
  into a Markdown document carrying the app version, the **verbatim** query, and a
  provenance row per article (source · date · URL · content SHA-256) — optionally with the
  signed evidence bundle in the same response, so a fact-checker hands over document +
  proof together. Records selection only; asserts no conclusion (and says so).
- **Versioned export contract** (`oo-export-1`): JSON exports are self-describing envelopes
  (schema, app version, generated-at, the exact generating query, count); CSV columns stay
  byte-identical with the same provenance as `X-OO-*` headers. Plus a **citation-graph
  export** (`/api/links/export.graphml` / `.json`): the who-cites-whom graph, counts only,
  the no-inferred-credibility caveat embedded in the file; opens in Gephi/yEd/NetworkX.
- **Scheduler accountability**: every run — success *and* failure — appends one auditable
  line to `scheduler_runs.jsonl` (served by `/api/scheduler/runs`); an **opt-in drop-folder
  export** writes each run's new-articles delta as envelope JSON into a local folder a
  newsroom pipeline can watch (empty = off, the default).
- **Corpus synthesis** (*Search → Synthesize results*): one local-model call across ≤ 20
  articles — shared facts, disagreements, open questions, with numbered citations back to
  the members; stored per member with model + prompt-version provenance; "assistance,
  never a verdict" travels with the output.
- **Offline source discovery** (RM-19, first increment): the app stages source
  *candidates* from two network-free channels — domains your articles repeatedly cite, and
  packaged-catalog outlets for thinly-covered countries. Transparent by construction:
  every candidate carries its evidence, runs are budgeted (`discovery_per_run`) and logged,
  a Home card announces what awaits review, and **promotion still creates a disabled
  source you must enable**. The DuckDuckGo channel deliberately does not exist yet — it
  ships only behind the external-lookup gate once this staging UX has proven itself.
- New table `source_candidates` (migration `a9b8c7d6e5f4`); +33 tests across the part.

## 0.08 — executing the product roadmap: trust gates + investigation recipes

The `0.08` cycle executed the post-audit product roadmap
([`docs/product/RELEASE_0.0.8_PLAN.md`](product/RELEASE_0.0.8_PLAN.md), WP1–WP9 all
delivered) and closed **every remaining audit finding — the register reads 29/29 FIXED**.

- **Investigation recipes (the headline).** The Home briefing gains three space-time
  scenario cards, computed entirely from your own corpus (producers never touch the
  network): **Promises due** (an article mentioned a date that was *in the future* when
  published — it has now arrived), **Edit-war burst** (a tracked Wikipedia page editing at
  ≥3× its own prior weekly rate), and **Region gone quiet** (a usually-covered country
  stopped arriving — honestly caveated as a fact about *your corpus*, not the region).
  Each card carries an **"Open investigation ↗"** button that opens a dedicated dashboard
  (`/investigate`) **in a new browser tab** — related panels auto-assembled from existing
  APIs, the card's caveat verbatim at the top, and a "Go deeper" strip where every
  suggestion is a manual action with its parameters shown. Fully URL-parameterised:
  shareable, re-openable, several investigations in parallel while the main UI stays free.
  The card schema guard extends to recipes: score/verdict-shaped parameters are
  mechanically rejected. Per-recipe switches live in **Settings → General**.
- **The one external call is now opt-in.** *Discover by topic* (the only feature that
  contacts a third-party service — it sends your topic query to DuckDuckGo) is **disabled
  by default** and refuses with an honest message until enabled in **Settings → Safety →
  External topic discovery** ("Your query leaves this machine"); `OO_DISCOVERY_EXTERNAL=1`
  for headless use. RSS discovery of your own sources stays local-path and ungated.
- **Weekly security cadence.** CI runs bandit + pip-audit every Monday on a schedule, so a
  freshly published CVE surfaces without waiting for a push.
- **`Mapped[]` ORM migration.** All 296 columns across the 26 models moved to SQLAlchemy
  2.0 typed mappings with **zero schema drift, proven** (byte-identical before/after schema
  dumps, committed as evidence). mypy fell 303 → 128 errors, and CI gained a **type-check
  ratchet**: the error count can never rise again.
- **Test depth.** +42 tests: the politeness-delay arithmetic (fake clock), endpoint
  coverage for the last untested routers (reporting — including evidence-bundle **tamper
  detection** — LLM HTTP layer, framing, keyword management), the discovery gate, the
  recipes, and a new repo invariant: **no `print()` in library code** (CLI surfaces
  allowlisted), enforced forever.
- Suites at cycle close: **858 passed / 6 skipped** (full) and **754 / 6** (core-only).

## 0.07 — full audit cycle (hardening, truth-up, performance)

A six-phase, evidence-driven audit of the whole repository (baseline → architecture →
quality → stabilize → optimize → docs; reports in [`docs/audit/`](audit/), findings in
[`docs/audit/findings.csv`](audit/findings.csv)). 29 findings: 20 fixed, 9 deferred with
rationale. Highlights:

- **Ethics invariant restored (ETH-01, the audit's one real invariant breach):** RSS-feed
  *discovery* used to fetch pages with raw `requests`, bypassing robots.txt, the SSRF
  guard, and per-host rate limiting. It now goes through the same `EthicalFetcher` as all
  ingestion, with regression tests proving robots-fail-closed and SSRF refusals apply.
  The one remaining external call — *Discover by topic* querying DuckDuckGo — is now
  explicitly documented as a user-triggered, opt-in exception (`docs/SECURITY.md`).
- **Safe-by-default config:** `.env.example` rewritten to the real `OO_*` surface
  (previously advertised `0.0.0.0` binds, a wildcard Ollama CORS, an auto-download that
  doesn't exist, and JWT/auth secrets for an auth system that doesn't exist); Config
  defaults now loopback; the app version is single-sourced from package metadata
  (was reported three ways: 0.02 / 0.03 / 0.0.7).
- **Performance (measured, `scripts/benchmark_audit.py`):** dropped a B-tree index over
  the full article body that no query used — **a 50k-article DB shrinks 354 → 130 MB
  (−63%)** (migration `f1a2b3c4d5e6`; run `make migrate` on existing databases).
  Recency-browse verified at p50 1.3 ms on 50k rows; near-duplicate clustering verified
  linear (no O(n²)).
- **Reliability:** the fetcher now retries *transient* failures (network errors, 429,
  5xx) with bounded backoff — never 4xx or robots/SSRF refusals — staying rate-limit
  polite. New regression tests for the body-size cap, redirect cap, and DNS-rebinding
  refusal.
- **A core-only install is now green:** analysis-dependent tests skip (instead of
  failing) when the `[analysis]` extra is absent.
- **Dead code quarantined:** six packages (~4,400 LOC: `ingestor`, `scraper`,
  `custom_types`, `compliance`, `audit`, `reports`) moved to `quarantine/dead_src/`;
  `bandit -r src/` now reports zero issues.
- **CI:** runs on every pushed branch (the old trigger was pinned to `0.04` and silently
  skipped pushes to the default branch); adds a core-only-install job, plus bandit and
  pip-audit gates.
- **Docs truth-up:** `docs/ARCHITECTURE.md`'s fossil "NOT FUNCTIONAL / conceptual only"
  database section replaced with the verified reality (SQLite supported and tested;
  PostgreSQL honestly labelled untested scaffolding with no search); doc sprawl
  consolidated (`NEXT_VERSION` merged into `ROADMAP`, presentation archived, ~68 MB of
  legacy audit dumps pruned from the tree — retrievable from git history).
- Lint/format: `ruff --fix` + `ruff format` across the tree (887 → 312 advisory
  remainder); style debt no longer obscures diffs.

## 0.07 — space & time, and a calmer GUI

The `0.07` cycle threads the separate verticals (news · insights · law · markets) onto a
shared **space-time** spine and tidies the interface. *(This entry covers the space-time /
GUI slice; other `0.07` work — events agenda, hazards relay, keyword super-groups,
personality, i18n — ships in sibling pull requests.)* Nothing weakens the local-first,
no-server, no-telemetry posture; every new surface states its limits.

- **Temporal map (new tab).** Every locatable, datable signal on one zoomable
  equirectangular world map under a **time slider** from antiquity to the near future:
  curated historical/scheduled **anchors** (`configs/world_timeline.yml`), your **geocoded
  corpus** (publication date), **dates mentioned in article text** (extracted), and opt-in
  live **hazards**. Density strip + play, per-kind legend, semantic-zoom labels, persisted
  layer/window prefs, click-for-detail with a **"Find coverage in your corpus"** cross-link
  and a **"Near in space & time"** panel (co-occurrence, *never* cause). **Honest by
  construction:** a pin needs *both* a coordinate and a date (no coordinate → no pin);
  country-level pins flagged approximate; scholarly date doubt carried in the note.
  Offline **coastlines** via `scripts/build_world_outline.py` (public-domain Natural Earth;
  lat/lon graticule fallback — never fabricated). `GET /api/timemap` (+ `/range`).
- **Article date-tags.** A high-precision extractor (`src/timemap/dateextract.py` — explicit
  dates only; no bare years or relative phrases) turns the dates a story is *about* into
  **per-article tags** in a dedicated table (`article_mentioned_dates`), each a **candidate
  with its provenance snippet**, **confirmable/rejectable** in the offline article reader and
  **filterable** across the corpus (`GET /api/article-dates/by-date`). `/api/article-dates/...`.
- **Customize → Settings.** The floating "Customize" drawer becomes a first-class
  **Settings → Appearance** section; Settings is reorganized into **Appearance · General ·
  Wikipedia · Data & backup · Safety**. Both standalone Customize buttons removed to free the
  chrome; the sidebar footer gains a **Settings** shortcut.
- **Discoverability.** A Home **"See it in space & time"** scenario card and an Insights-map →
  Temporal-map link.

## 0.06 — Phase B: safety, sense-making, accessibility & governance

A second slice of the `0.06` work, organised around four themes from
the "Next version — action plans" section of [`ROADMAP.md`](ROADMAP.md). Each ships an honest Phase 1 today; none weakens the
local-first, no-server, no-telemetry posture. See [`GOVERNANCE.md`](GOVERNANCE.md).

- **At-risk-user safety (`src/safety/`).** New **Settings → Safety** panel and `/api/safety`
  routes: a passphrase **encrypted backup/restore** (AES-256-GCM + scrypt — reuses the
  audited crypto primitives; a wrong passphrase or tampered file fails *loudly*, never
  silently); a **panic wipe** that overwrites-then-deletes the corpus, keys and caches
  (honest about the SSD/copy-on-write limit — only full-disk encryption guarantees a true
  wipe); and a **Protected fetch mode** that sends a generic User-Agent through a proxy you
  run (e.g. Tor), labelled with its honest limit — *we cannot guarantee anonymity*. Also a
  `panic` CLI and an `--ephemeral` run mode (RAM-only data dir, wiped on exit).
- **Story lineage — "trace to the primal source" (`src/signals/lineage.py`).** For a
  near-duplicate cluster echoed across many outlets, reconstruct the **primary → first
  report → echoes** chain by publication time, detect **wire attribution** ("according to
  Reuters", "(AFP)"), and surface the structure so original reporting is foregrounded over
  derivative echoes. Honest bright line: *"earliest we saw" ≠ "the truth"* — it shows
  structure; the human judges. New Home producers **Story lineage** and **Coverage advisor**
  (surfaces geographic/linguistic skew in *your* collection — a suggestion, never a filter).
- **Accessibility & i18n.** A keyboard **skip-to-content** link, ARIA landmarks/labels on
  navigation and icon-only buttons, a polite **live region** for toasts, `aria-current` on
  the active tab, and a keyboard-operable command palette. New chrome strings translated to
  the complete locales (de/es/fr now 100%); `scripts/i18n_report.py` measures locale
  coverage and can gate CI.
- **Governance & acceptable use ([`GOVERNANCE.md`](GOVERNANCE.md)).** A statement of purpose
  and explicit **dual-use red lines** (no individual tracking, no biometric ID, no
  private-channel ingestion, no automated verdicts, no central server, no silent filtering —
  *absent by construction, not configurable*), enforced by a **red-lines tripwire test** in
  `tests/test_repo_invariants.py`.

## 0.06 — the intelligence layer (Phase A: the Home briefing)

The first slice of the `0.06` "intelligence layer" — the **GUI spine**. The unifying
idea is *one measurement engine, many domains*; this ships the engine's framework and
its first pure primitive, and turns **Home into a triage briefing**. Guiding docs:
[`ROADMAP.md`](ROADMAP.md) (what & why) and
[`ROADMAP.md`](ROADMAP.md) (how); user guide: [`USER_MANUAL.md`](USER_MANUAL.md).

- **`src/signals/` — pure, DB-free measurement primitives.** First shipped:
  `concentration` (Gini coefficient + top-N share), property-tested with exact
  hand-computed values and honest *undefined → None* behaviour (no fabricated zeros).
  The *same maths* intended for media-ownership and people-prominence concentration.
- **`src/briefing/` — the card + briefing framework.** A `Card` is one measured signal
  + evidence + method + caveat, sorted into an editorial bucket. A **producer registry**
  makes every feature `corpus → [Card]`, so new capabilities appear in the *same* feed.
  Producers **degrade loudly** (return nothing + log) when inputs/optional deps are
  absent — never a fabricated card.
- **Home is now the briefing:** cards grouped by bucket (*rising · overtold · undertold
  · investigate · check-the-framing · watch · context · data-integrity*), with triage
  (dismiss/restore, reversible) and a **method & caveat** transparency toggle. Built on
  the existing tested shell — same element IDs, no functional regression.
- **"Now"-status producers (no new math, real numbers):** Rising (trending),
  Framing-split (per-source VADER tone of a trending term), Record-reshaped (Wikipedia
  flagging), Price↔narrative (honest scipy correlation), Stale-data (market-rule
  freshness), and **Diet self-audit** (the new `concentration` primitive over *your*
  sources).
- **Card → draft → newsletter:** pin cards into a draft accumulator (+ your notes) and
  **export Markdown** in which every claim carries its source links, method and caveat —
  reproducible journalism. Custody receipts referenced via Evidence & custody.
- **Performance:** precompute → cache → serve cached. The briefing never computes per
  request; the scheduler refreshes it after each scrape (`briefing_cache.json`).
  Dismissals/draft are small local JSON files — single-user, local-first, never sent.
- **Honesty guard *in code*:** `assert_no_score_fields()` rejects any `Card` field that
  implies a composite trust/quality score (the §6 ban) — enforced at import and by a
  test. Numeric values live in `signal` as a single measured quantity with a method,
  never a blended score.
- **API:** `/api/briefing` (cached feed), `/refresh`, `/dismiss`·`/restore`, and the
  `/draft` accumulator with `GET /draft/export.md`. New in-app doc `USER_MANUAL.md`.
- **Tests:** `test_signals_concentration.py`, `test_briefing.py`, `test_briefing_api.py`
  — full suite green; no regressions.

### Phases B–E — the signal substrate, source integrity, annotations, verticals

- **`src/signals/` complete (Phase B):** the pure, DB-free measurement substrate —
  `near_dup` (MinHash + LSH near-duplicate clustering), `coordination` (an actor graph
  from near-dup co-publication + lockstep timing + shared host), and `novelty`
  (information contributed vs an incremental corpus index). Property-tested on crafted
  fixtures (a syndicated story collapses; an independent original stays separate; a pure
  echo scores ~0 novelty).
- **Source integrity & anti-amplification (Phase C, `src/integrity/`):** the §6 keystone.
  A per-source **profile of measured dimensions with NO composite score** (enforced by a
  test); **user-guided actor-collapse** — the app *proposes* collapsing a coordinated
  flood with its evidence, the user *disposes* (per-cluster or global), every applied
  collapse stays flagged + expandable, reverting reproduces the raw equal counts exactly,
  and **no collapse is applied without an explicit action**. The 40-puppet-flood
  acceptance is a passing test. New cards: **echo-chamber**, **lonely-signal**,
  **capacity-implausible**. New **Source integrity** GUI tab. See `USER_MANUAL.md`.
- **Crowdsourced signed annotation bundles (Phase D, `src/annotations/`):** publish
  source annotations (ownership/leaning/coordination/corrections) as a **hybrid-signed,
  portable bundle** (reusing the custody signer); import the bundles you trust (opt-in
  **web of trust**); **transparent aggregation** shows *who asserted what* and surfaces
  dissent, never averaging it into a score. A tampered bundle is refused. See
  `USER_MANUAL.md`.
- **World-law change-tracking vertical (§5, `src/law/`):** a **worldwide catalog of real
  official primary sources** (national legislation databases, official gazettes, IP
  offices, open case-law/filing systems — `configs/legal_sources.yml`) seeded **by
  default**, ingestible/searchable through the same ethical pipeline. A curated set of
  consolidated-law documents is tracked for change (baseline → normalised-text diff →
  honest large-change flag, reusing the Wikipedia engine), exposed via `/api/law/*`, a new
  **World law** GUI tab, and a `law` scheduler mode. New cards: **law-change** (watch) and
  **model-legislation** (cross-jurisdiction near-dup). New `LawDocument`/`LawRevision`
  tables via Alembic migration. A research mirror, never legal advice — every record links
  to its official gazette. See `USER_MANUAL.md`.
- **Phase E (composable cards):** **emotion-category** measurement around a keyword
  (`src/awareness/emotion.py`, lexicon-based, ships a minimal English sample, overridable
  via `OO_EMOTION_LEXICON`, degrades loudly); **IP/legal news cards** (IP-litigation
  pulse + ownership-change deal-language).
- **Novelty-weighting (§6 D, opt-in):** `story_prominence(weight_by_novelty=True)` and
  `/api/integrity/prominence?weight_by_novelty=true` additionally down-weight
  low-information echoes — off by default (anti-amplification stays user-guided, never
  silent), the equal view reproduced exactly when off.
- **Honesty guards everywhere in code:** no composite trust score on a Card, a Source
  profile, or an annotation kind; anti-amplification is never silent; aggregation never
  averages dissent.
- **i18n:** new chrome strings added to the maintained locales (en/de/es/fr); the
  English-fallback design keeps every other locale working.
- **Tests:** `test_signals_near_dup.py`, `test_integrity.py` (incl. novelty-weighting),
  `test_annotations.py`, `test_awareness_emotion.py`, `test_law.py` (+ A's tests). Full
  suite green.

## 0.05 — full interface redesign (now the default branch)

A ground-up redesign of everything the user sees, built on top of the existing,
tested data layer (same endpoints, same element IDs — no functional regression).
Reasoned from the personas outward in [`docs/DESIGN.md`](DESIGN.md).

- **New shell:** a collapsible **sidebar grouped by intention** (Investigate ·
  Collect · Trust · System) replaces the flat tab strip; a slim top bar carries
  live status and the command-palette trigger.
- **Renamed for humans:** *Ingest → Collect*, *Database → Library*, *Chain of
  custody → Evidence & custody*; **Markets** is marked advanced and can be hidden.
- **New Home dashboard:** orientation for non-technical users — at-a-glance counts,
  scheduler state, and big quick-action cards.
- **In-app Help/docs reader:** renders the User Manual (and other guides) inside the
  app, offline, with find-on-page — backed by a new read-only, allow-listed
  `/api/docs` endpoint.
- **Command palette (Ctrl/⌘-K):** jump to any tool, run common actions, or open any
  doc, all by typing.
- **Live customization drawer:** 8 themes, accent swatches, density, text size,
  sidebar collapse, and per-tool visibility — stored locally only, never transmitted.
- **Refined visual system:** token-based theming, depth, motion, accessible focus
  rings, responsive/off-canvas layout — still 100% dependency-free (no CDN, no web
  fonts, no framework), so it runs fully offline.

### Toward 50,000 sources — honestly

- **Political-spectrum catalog (`configs/sources_spectrum.yml`):** ~280 new, real,
  well-known outlets across ~95 countries / ~30 languages, hand-tagged by **leaning**
  (lean-left … lean-right) and **ownership** (public-broadcaster / state-media /
  wire-agency) with topic keywords — the editorial dimension Wikidata can't provide.
  Merged at seed time (de-duped by domain); leanings are reputational, contestable
  and easy to override.
- **Generator tuned for scale:** `configs/catalog_query.yml` now targets ~50k+ —
  ~249 countries × broader media types at `limit: 5000`. The honest path to tens of
  thousands of *real, attributable* sources is running the Wikidata generator (and
  `--merge-csv` for GDELT/Media Cloud), **not** fabricating dead RSS URLs. See
  `docs/ROADMAP.md`.

### A contradictory take + a second interface to compare

- **`docs/DESIGN.md`** argues the *opposite* case — that a polished,
  customizable "console" may be the wrong fit for a sovereign, offline,
  trust-first tool — and proposes an antithesis.
- **"Desk" (`/desk`, `src/static/desk.html`):** a calm, editorial, content-first
  alternative interface. No persistent sidebar (navigation is on-demand via a
  job-framed home + a ⌘K jump overlay), two opinionated themes (Ink/Paper), serif
  typography, a reading-width column, and a persistent "nothing leaves this
  machine" trust line. It shares the *exact* engine and content panels with the
  default ("Console") interface, so the comparison isolates the philosophy.
- **Two installer icons:** `install.sh` now creates **Console** and **Desk**
  launchers (distinct icons); `scripts/launch.sh` takes a `console|desk` argument
  and detects an already-running server, so both can run side by side on the same
  data. New read-only `/desk` route serves the alternative.

### Coverage honesty, branch hygiene & docs alignment

- **`docs/ROADMAP.md` — a coverage ledger.** Names every blind spot and labels it
  *voluntary* (deliberate) or *involuntary* (to be measured). **Images and all
  visual/binary media are now an explicit, documented exclusion** (owner's choice:
  storage on one affordable machine, and honest image analysis isn't feasible at
  scale) — already enforced by the crawler's `_SKIP_SUFFIXES`. Also records the
  social-media exclusion, paywall/robots policy, and the planned register-
  triangulation + capture–recapture method for *sizing* the unknown.
- **No work lost across branches.** `0.05` (branched from `claude/kind-lovelace-ulpTc`)
  already contained the chain-of-custody feature; the only artifact unique to `0.04`
  was `docs/PRESENTATION_PUBLIC.md`, now cherry-picked onto `0.05`.
- **User Manual aligned to the 0.05 interface:** sidebar groups, the command palette
  (⌘K), Customize, the Home dashboard, the in-app Help/docs reader, the two
  interfaces (Console `/` and Desk `/desk`), and the renamed tools (Ingest→Collect,
  Database→Library, Chain of custody→Evidence & custody).

### Multilingual UI, link co-citation, and measurable coverage

- **Multilingual UI wired (i18n Phase 2):** `i18n.js` is now included in both Console
  and Desk, with a **Language** picker (12 languages) in Settings. Dynamically-
  rendered chrome is translated automatically via a debounced `MutationObserver`;
  English fallback for untranslated strings; RTL via `<html dir>`. (Behaviour still
  wants a browser pass.) Complete reference translations ship for en/fr/es/de; the
  rest are selectable English-fallback stubs.
- **Article link detection wired (link analysis P0/P1):** ingest now populates
  `article_links` with outbound **external** links (best-effort, fail-open;
  internal/image/ad/social/tracker excluded; `OO_NO_INDEX=1` disables). New
  read-only `/api/links` endpoints — `stats`, `top-cited` (url|domain, windowed),
  `articles-by-link` — answer "which articles cite the same source." Counts only,
  no scoring (the old fabricated link analyzer stays quarantined).
- **Coverage made measurable:** honest **ccTLD inference** (`src/catalog/cctld.py`)
  backfills missing `country`/`language` at seed time (generic/ambiguous ccTLDs stay
  unknown), lifting country-tagged coverage ~19% → ~33%; and **source provenance** is
  recorded as a `via:<origin>` tag — first steps of the `ROADMAP.md` measurement plan.

## Unreleased — UI polish, live data, and a full user manual

A wave of usability work on top of the feature set below, plus documentation:

- **Live, animated data:** the active tab refreshes itself on an interval while on
  screen — live article/database counts, scheduler state, Insights indexing
  progress, and Wikipedia tracking — with smooth count-up tweens for headline
  numbers.
- **Sources / Database split:** the old combined tab became two — **Sources**
  (add + a filterable, sortable, paginated management table with inline
  enable/priority/delete and CSV import/export) and **Database** (live honest
  stats + clickable World-coverage view).
- **Scheduler-first Ingest tab:** automatic ingestion (start/stop/scrape-now, RSS /
  crawl / markets / Wikipedia modes, language/type/tag targeting with a **Preview
  targets** action) is the primary surface; manual feed/URL ingest sits below.
  Empty-DB onboarding banner with a one-click first run.
- **Markets dashboard:** analysis-first cards with adjustable time scales and
  out-of-the-box curated data; the feed/rule configuration is tucked into a
  collapsible "most users won't need this" section.
- **Offline article view** + framing surfaced in Insights.
- **Insights keyword filtering:** stronger multilingual stopword removal plus a
  user-editable exclusion list (Settings → Keyword filtering, and ✕ in Insights).
- **Wikipedia language picker moved to Settings**, **grouped by continent**
  (Europe/Asia/Africa/…, largest editions first within each), expanded to ~147
  editions across all continents (plus a "Constructed" bucket), with a
  **type-to-filter** search box; it also accepts any free-text edition code.
  `src/wiki/languages.py` gained a `region` field + `languages_by_region()`, and
  `/api/wiki/languages` now returns both a flat list and a continent-grouped
  `groups` form.
- **Docs:** added an extensive end-user manual ([USER_MANUAL.md](USER_MANUAL.md))
  covering every tab, control, setting, workflow, env var and API area, and an
  [ROADMAP.md](ROADMAP.md) capturing in-flight design decisions
  (notably a planned chain-of-custody "automatic, background, dummy-proof"
  redesign — not yet built).

## Unreleased — tabbed UI, markets, worldwide coverage, insights, wiki

A large feature wave (all tested; dependency-free vanilla-JS UI; no fabricated data):

- **Tabbed UI + management:** Sources & Database (live stats, source management,
  world coverage), Settings (theme + SQLite **backup/restore**), in-app
  **scheduler** (start/stop, rss/crawl/markets modes) and a **bounded recursive
  crawler** (same-domain discovery, robots fail-closed, depth/page caps).
- **Markets:** per-source **price-extraction rules** (numbers only from a verified
  CSS selector — `Test` action), **official CSV price feeds** (FRED→World Bank/EIA)
  + custom-URL import, charts and honest price↔news correlation, and a packaged
  worldwide markets catalog. See [USER_MANUAL.md](USER_MANUAL.md).
- **Worldwide source catalog:** a **data-derived generator** (Wikidata CC0 +
  optional GDELT/Media Cloud) for news + institutions per country, coverage report,
  and **CSV import/export** of the source list. See [ROADMAP.md](ROADMAP.md).
- **Insights — keyword & entity analytics:** extraction at ingest (people/orgs/
  places as single units; opt-in spaCy), a mention store with context, and
  trends / PMI associations / per-country-city map. See [USER_MANUAL.md](USER_MANUAL.md).
- **Wikipedia change-tracking (foundation):** per-language editions, delta storage
  (diffs not re-copies), and honest large-edit/revisionism flagging (incl. ORES).
  See [USER_MANUAL.md](USER_MANUAL.md).

New migrations: `b7c1d2e3f4a5` (market rules), `c3d4e5f6a7b8` (keyword mentions),
`d4e5f6a7b8c9` (wiki tracking).

## Unreleased — honest chain of custody (Phase 5)

The deferred "signed chain-of-custody reporting" pillar, built honestly and made
operator-configurable:

- **Custody core (`src/custody/`):** an append-only, hash-chained, **signed** log
  of actions on an item; **hybrid Ed25519 + post-quantum ML-DSA** signatures with
  AND semantics and honest labels (never a silent downgrade); "existed no later
  than T" timestamping via a self-asserted local clock or Bitcoin-anchored
  **OpenTimestamps**; pluggable anchoring (offline `local` default, OpenTimestamps,
  and public-chain providers that refuse honestly rather than faking receipts).
  Offline verification via `scripts/verify_custody.py`.
- **GUI-configurable settings (`src/custody/settings.py`):** post-quantum signing,
  anchoring mode, and auto-log-on-ingest are now runtime-editable from a **Chain of
  custody** web-UI panel and `GET/PUT /api/custody/settings`, persisted to
  `custody_settings.json`. The API/UI always report the **effective** state
  (preference *and* library availability), so PQC/OpenTimestamps can never appear
  enabled when the supporting extra is absent. Auto-log defaults to the legacy
  `OO_CUSTODY_ON_INGEST` flag until a preference is saved.
- Documented in [USER_MANUAL.md](USER_MANUAL.md); endpoints added to
  [ARCHITECTURE.md](ARCHITECTURE.md).

## 0.4 — Trustworthy core + honesty pass

A near-total rebuild around a small, genuinely-working spine, plus a ruthless
audit/debug pass. Highlights:

**Core (Phases 0–1):** single `pyproject.toml` on Python 3.13; clean DB session
layer (no import-time side effects, WAL); one ethical fetch path (robots.txt
fail-closed, rate-limited) → trafilatura extraction → dedup + provenance; real
SQLite **FTS5 Boolean search** (AND/OR/NOT, phrases, precedence); CSV/JSON export;
dependency-free offline web UI; Qubes-aware installer; honest docs.

**Capabilities (Phases 2–5):** local LLM via Ollama (HTTP, loud 503 degradation);
commodity prices + **real scipy correlation** (no fabricated p-values); real
source-uptime monitoring + z-score anomalies; IMAP email into the unified corpus;
honest EXIF metadata verification; **Merkle + Ed25519 signed evidence bundles**
with a standalone verifier.

**Phase 6 — repository honesty:** purged ~19k lines of fabricated/dead code (live
ratio 36%→68%); removed the hallucinated LLM model catalog; auto-seed the full
~1,780-source catalog on first run; Alembic migration path with a CI drift gate;
salvaged Pillar-2's genuine statistics into `src/analysis` and **quarantined the
remaining pillars** (intent preserved — see PILLAR_INTENT_MAP).

**Full re-audit (2026-06):** quarantined the fabricated `link_analyzer` stack;
fixed broken endpoints and salvaged-stat bugs (chi-square crash, regression CI,
odds-ratio); closed the evidence-verification trust hole (pinned key + full-item
Merkle + domain separation); fixed email charset corruption, ingest rollback
isolation, the core-only-install boot, and the whole P2 backlog (DI to
`Depends(get_db)`, shared rate limiter, bounded uploads, cache/url/regex/compression
fixes). See [HISTORY.md](HISTORY.md). 400+ tests, all green.

## 0.01–0.03 (historical)

Early concept releases (forked from HTTrack). Largely non-functional / design-only;
superseded by the 0.4 rebuild. Retained only in git history.
