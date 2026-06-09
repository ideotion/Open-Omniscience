# Changelog

> `0.05` is the repository's **default branch** — the mainline everything builds on.

## 0.06 — Phase B: safety, sense-making, accessibility & governance

A second slice of the `0.06` work, organised around four themes from
[`NEXT_VERSION.md`](NEXT_VERSION.md). Each ships an honest Phase 1 today; none weakens the
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
