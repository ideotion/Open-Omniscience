# Changelog

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
  [OPEN_QUESTIONS.md](OPEN_QUESTIONS.md) capturing in-flight design decisions
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
  worldwide markets catalog. See [MARKETS.md](MARKETS.md).
- **Worldwide source catalog:** a **data-derived generator** (Wikidata CC0 +
  optional GDELT/Media Cloud) for news + institutions per country, coverage report,
  and **CSV import/export** of the source list. See [WORLD_NEWS_CATALOG.md](WORLD_NEWS_CATALOG.md).
- **Insights — keyword & entity analytics:** extraction at ingest (people/orgs/
  places as single units; opt-in spaCy), a mention store with context, and
  trends / PMI associations / per-country-city map. See [INSIGHTS.md](INSIGHTS.md).
- **Wikipedia change-tracking (foundation):** per-language editions, delta storage
  (diffs not re-copies), and honest large-edit/revisionism flagging (incl. ORES).
  See [WIKIPEDIA.md](WIKIPEDIA.md).

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
- Documented in [CHAIN_OF_CUSTODY.md](CHAIN_OF_CUSTODY.md); endpoints added to
  [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

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
fixes). See [AUDIT_2026-06.md](AUDIT_2026-06.md). 400+ tests, all green.

## 0.01–0.03 (historical)

Early concept releases (forked from HTTrack). Largely non-functional / design-only;
superseded by the 0.4 rebuild. Retained only in git history.
