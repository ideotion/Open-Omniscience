# Phase 1 — Architecture analysis: inventory, wiring & mental model

**Date:** 2026-06-09 · **Branch:** `claude/laughing-bohr-mzqflp` · **Baseline:** [00_BASELINE.md](00_BASELINE.md)

> Methods: AST-based import graph (`/tmp/import_graph.py`, run in-session), runtime route enumeration
> against the live FastAPI app, `radon cc/mi` 6.x, `git`-derived metrics, and four targeted
> source-reading passes (ingestion, LLM+data model, quarantine, configs/deploy/docs). Every
> load-bearing claim was verified directly in source; file:line citations included. Diagrams in
> [diagrams/](diagrams/).

---

## 1. Executive summary — one app or six?

**One application.** The 2025-era "six mini-projects sharing a repo" architecture is gone. What
exists today is a single FastAPI application (`src/api/main.py` assembles ~30 routers/packages into
one process serving both API and UI), one SQLite store behind one SQLAlchemy session module, one
ethical fetch path, and one test suite. The former pillars 2–6 live in `quarantine/` (~47.7k LOC),
**imported by nothing** — and that isolation is *enforced by a test*
(`tests/test_repo_invariants.py:45-52` fails if live code imports `quarantine`). Pillar 1 was never
lost: its intent (ingestion) is the live `src/ingest/` + `src/database/` spine, per the Pillar
Intent Map in `docs/DESIGN.md`.

The honest architectural concerns are no longer "is this one app" but: residual dead code *inside*
`src/` (§3), config/documentation drift around env vars and `settings.yaml` (§7), CI push triggers
pinned to an old branch (§8), and a de-facto-SQLite-only reality wearing optional-Postgres clothes
(§6). Ranked risks in §10.

## 2. Quantified structure

LOC measured by `wc -l` over `git ls-files` (no tool like cloc available; numbers are raw line
counts including comments/blank lines):

| Tree | Python LOC | Other | Notes |
|---|---|---|---|
| `src/` | 35,594 (38 packages, ~190 files) | 7,783 JS/CSS/HTML (`src/static/`: `index.html` 4,839, `desk.html` 2,832, `i18n.js` + 12 locales) | the live app |
| `tests/` | 13,641 (104 files, 813 tests) | — | single suite, hermetic via `OO_DATA_DIR` tempdir (conftest.py) |
| `scripts/` | 8,210 | bootstrap/launch/install shell | incl. one-off catalog generators |
| `migrations/` | 1,004 | — | Alembic, 8 versions |
| `quarantine/` | **74,064** | — | 2× the size of the live app; zero imports (enforced) |
| `configs/` | — | 16 YAML files, 35,461-line `sources.yml` (~935 sources) | data, not code |
| `docs/` | — | 15 MD + `archive/` (**~69 MB** of prior-audit JSON; largest file 62.9 MB) | see §9 |

Largest live-code files: `src/static/index.html` (4,839), `src/database/models.py` (1,476),
`src/api/main.py` (1,119). 23 Python files exceed 500 lines. 16 functions exceed 75 lines (worst:
`view_article` 197 lines at `src/api/main.py:713`, `ingest_source` 165 at
`src/ingestor/pipeline.py:150` — in a dead package, see §3). `radon` grades only ~20 functions C or
worse across `src/`; single E: `build_families` (31) at `src/analytics/families.py:111`; single D
in live code: `BaselineExtractor._entities` (30) at `src/analytics/extract.py:144`. Maintainability
index: every file A except `src/briefing/producers.py` (B). **For 35k LOC this is a modest and
localized complexity profile.**

## 3. Module catalog & import graph

AST import graph of `src/` packages (cross-package edges only):

| Package | LOC | Imports | Imported by | Role / notes |
|---|---|---|---|---|
| `api` | 6,362 (34 files) | 30 | 0 | composition root: 38 routers, 217 routes, serves UI |
| `database` | 4,142 | 3 | **15** | ORM (26 tables), session, FTS5 — the legitimate god-module |
| `utils` | 2,476 | 0 | 7 | url_utils (canonicalize/hash), security, compression |
| `paths` | 82 | 0 | 13 | data-dir resolution (`OO_DATA_DIR` → repo `data/` → XDG) |
| `ingest` | 1,262 | 7 | 6 | EthicalFetcher + pipeline + bounded crawler + email |
| `services` | 1,845 | 2 | 5 | duckduckgo discovery, link analyzer (honest rebuild) |
| `analysis` | 1,743 | 0 | 1 | scipy statistics (salvaged Pillar 2) — needs `[analysis]` |
| `custody`/`crypto`/`integrity` | 3,054 | — | — | chain of custody, signing, source-integrity views |
| `scheduler` | 465 | 8 | 1 | daemon-thread scraper (`OO_NO_SCHEDULER` kill switch) |
| domain packages (`markets`, `wiki`, `law`, `events`, `timemap`, `briefing`, `analytics`, `signals`, `catalog`, …) | ~8,000 | 0–3 each | 1–3 each | clean: each owns its tables/logic, wired only via its router |

**Dead weight inside the live tree** (imported by nothing in `src/`, not routed, not packaged-out):

| Package | LOC | Evidence |
|---|---|---|
| `src/ingestor` | 2,507 | superseded by `src/ingest` + `src/utils/url_utils`; only referenced by `tests/test_url_utils.py:34` and `tests/test_scraper.py:43` via `sys.path.append(...'src')` hacks that import `ingestor.url_utils` directly — they test the *legacy copy*, not the live code path |
| `src/custom_types` | 407 | zero references outside itself |
| `src/compliance` | 162 | zero references |
| `src/audit` | 114 | zero references (and was shadowed by the `.gitignore` `audit/` pattern until Phase 0 fixed it) |
| `src/reports` | 91 | zero references (`src/reporting` is the live one) |

≈3,280 LOC of quarantine-grade code sitting un-quarantined. → ARCH-02.

## 4. The pillar question — resolved

| Pillar | Declared purpose | Where it is now | LOC | Verdict |
|---|---|---|---|---|
| 1 — Data ingestion | ethical crawl → provenance store | **live**: `src/ingest`, `src/database`, `src/catalog` | — | **REAL** (the spine; 0.0.6/0.0.7 core) |
| 2 — Scientific rigor | statistical validation, reproducibility | salvaged into `src/analysis` (scipy/statsmodels, real tests); original tree in `quarantine/pillars/pillar2` | 1,998 | **SALVAGED/REAL** |
| 3 — Deception defense | deepfake/propaganda/bot detection | `quarantine/pillar3_analysis` + `pillars/pillar3`: ONNX session never `.run()`, hardcoded confidences (0.8/0.9/0.75), bot detection = `len(followers)>1000` | 4,650+2,252 | **FABRICATED** (quarantined; honest EXIF replacement lives at `src/verification/metadata.py`) |
| 4 — Real-time monitoring | 24/7 alerting, threat intel | `quarantine/pillars/pillar4`; health checks literally `sleep; return HEALTHY` | 14,851 | **DESIGN-ONLY** |
| 5 — Financial intelligence | 50+ exchanges, OHLC | `quarantine/pillars/pillar5`; 0% implemented | 10,320 | **DESIGN-ONLY** (honest subset rebuilt as live `src/markets`) |
| 6 — Rare-earth intelligence | 17 elements, forecasting | `quarantine/pillars/pillar6`; 0% implemented | 15,876 | **DESIGN-ONLY** (subset → `src/commodity` + CSV feeds) |

Integration answer: pillars are **not** imported by the app and cannot be (test-enforced). The
`PYTHONPATH=pillarN` pattern is dead. Notable quarantine artifacts: `fabricated_sources.md`
(6 fake source entries removed from `sources.yml`, with evidence) and `configs_models.yml`
(an aspirational ML-model catalog with never-measured "accuracy" numbers — kept as a record).
The quarantine policy (its README) is explicit: nothing returns without a real method + honest
tests + deliberate rewiring.

## 5. Data & control flow

### 5.1 Ingestion (diagram: [diagrams/ingestion.mmd](diagrams/ingestion.mmd))

One mandatory fetch path: `EthicalFetcher` (`src/ingest/__init__.py`). Verified in source this
session: scheme allowlist http/https (`:156`); SSRF guard resolving DNS and blocking
private/loopback/link-local/metadata/reserved IPs, re-checked per redirect hop, max 5 redirects
(`:87-96, :199-228, :245`); **robots.txt fail-closed** — 401/403/5xx/network error ⇒
`RobotsUnavailable`, disallow ⇒ `RobotsDisallowed`, 404/410 ⇒ allowed per RFC, 1h cache
(`:303-345`); per-host rate limit = max(1s default, robots crawl-delay) (`:347-362`); honest UA
`OpenOmniscienceBot/<version> (+repo URL; ethical research crawler)` (`:43-46`); 30s timeout,
10 MB streamed body cap (`:111-112, :260-273`). `respect_robots=True` default, and **no caller or
config flag disables it** (grep verified). Markets rules, CSV feeds, law tracker and the bounded
crawler (depth clamp 0–6, pages 1–500, registrable-host same-domain check) all call this same
fetcher. Two deliberate exceptions: email ingest (IMAP, no HTTP) and the wiki tracker
(`src/wiki/client.py` — MediaWiki Action API with its own UA + maxlag etiquette). Pipeline:
canonical-URL pre-check → trafilatura extraction (≥200 chars or nothing stored) → SHA-256
content-hash check + DB `UNIQUE(hash)` race backstop (`src/ingest/pipeline.py:63-124`,
`models.py:475`) → best-effort keyword/link indexing → optional custody-log entry.

Gap worth carrying to Phase 2: ingest **audit logging** is real-time only
(`src/monitoring/activity.py` snapshot) plus the *optional* custody log — there is no persistent
structured "who ingested what when from where" record beyond `articles.created_at/source_id` when
custody logging is off. Also `src/services/duckduckgo.py` (RSS/topic discovery) calls an external
search service — user-triggered only, but it is a non-loopback dependency to keep on the Phase 2
checklist.

### 5.2 LLM (diagram: [diagrams/llm.mmd](diagrams/llm.mmd))

5 endpoints (`src/api/llm.py`) → `OllamaClient` (`src/llm/ollama.py`) → local Ollama over HTTP
(`OO_OLLAMA_URL`, default loopback :11434; httpx, 120s timeout). Ollama down ⇒ 503 with honest
detail; model missing ⇒ 503 "run: ollama pull …" (**no auto-download in code** — despite
`AUTO_DOWNLOAD_MODELS=true` sitting in `.env.example`, see §7); other errors ⇒ 502. Results stored
in `article_analyses` with model + prompt_version provenance. No batch/fan-out endpoints. Model
parameter is passed through without an allowlist (`ollama.py:96`) — low severity locally, but
Phase 2 will assess. Article text flows into prompts unsanitized (inherent LLM-injection surface,
6,000-char cap).

### 5.3 Data model (diagram: [diagrams/data_model.mmd](diagrams/data_model.mmd))

26 tables (`src/database/models.py`). Core: `sources` (UNIQUE domain, per-source `rate_limit_ms`,
priority, tags) ↔ `articles` (UNIQUE `hash`; `canonical_url` indexed but deliberately not unique;
provenance columns url/canonical/source/fetch-time) + FTS5 external-content `article_fts` kept in
sync by AFTER INSERT/UPDATE/DELETE triggers (`src/database/fts.py:211-239`). Domain clusters:
keywords/mentions/families/supergroups; links + external_sources; commodity_prices +
market_extraction_rules; wiki_pages/revisions and law_documents/revisions (both delta-compressed
with honest codec headers); article_analyses (LLM provenance); article_mentioned_dates. Schema
creation is dual-path: fresh installs `create_all` + `ensure_fts` + alembic stamp
(`session.py:93-112`); upgrades via 8 Alembic revisions. Session discipline: `sessionmaker` +
`session_scope()` context manager + FastAPI `get_db()` dependency — no scoped/global sessions.

**SQLite vs Postgres:** the engine branch supports Postgres (pooling, env-tunable), but FTS — the
search feature — is SQLite-FTS5 only (`ensure_fts` no-ops on other dialects, `fts.py:249`), the
suite never runs against Postgres, and WAL/busy-timeout pragmas are SQLite-only. **The product is
de facto SQLite-only**; the Postgres path is untested scaffolding. → ARCH-06.

## 6. API surface

217 routes enumerated at runtime (vs README/docs which describe features rather than endpoint
tables — no endpoint-table drift exists because no endpoint tables exist; `docs/ARCHITECTURE.md`
maps the major groups accurately). Distribution by prefix: sources/groups/catalog 45 · insights/
keywords 30 · briefing 12 · custody/safety/integrity/verify 22 · markets/commodities 19 · wiki 14 ·
law 8 · llm 5 · analysis 9 · annotations 8 · articles/ingest/search 8 · events/hazards/timemap 5 ·
database/system/monitoring/settings/scheduler 17 · docs/UI 6. All mounted under one app; UI served
from the same process (`/` Console, `/desk` Desk — two HTML files, no build step, no CDN). The only
external asset reference in the whole UI surface is FastAPI's default Swagger CDN on `/docs`
(carried from Phase 0).

## 7. Configuration & environment surface

16 YAML files in `configs/`; the catalogs (`sources.yml` ~935 entries, `sources_spectrum.yml`
~300 spectrum-tagged, `markets_sources.yml` ~110, legal/feeds/events/timeline/cities/personality)
are data assets with honest schemas (verified spot-reads; e.g. movable events carry
`confirmed: false`, timeline anchors carry `date_precision` + scholarly notes).

**`configs/settings.yaml` is half-dead:** only ~12 of ~25 keys are read by
`src/config/settings.py:_apply_yaml_config`; `frontend.*`, `export.*`, `audit.scrape_log/error_log`,
`logging.max_log_size/backup_count`, `security.cors_allow_methods/headers` are documented but
ignored (hardcoded or runtime-JSON instead). Version strings disagree three ways:
`settings.py:83` defaults `app_version="0.02"`, `settings.yaml:26` says `0.03`, reality is `0.0.7`
(pyproject + `/api/health`, which reads package metadata). Runtime UI prefs live separately in
`data/app_settings.json` (by design).

**`.env.example` is stale in both directions:**
- documents ~10 vars the code never reads (`UVICORN_HOST/PORT/RELOAD`, `POSTGRES_*` (5, superseded
  by `DATABASE_URL`), `CORS_ALLOW_METHODS/HEADERS`, `ARTICLES_PER_PAGE`, `MAX_EXPORT_SIZE`, …);
- omits ~21 vars the code does read — the entire `OO_*` family (`OO_DATA_DIR`, `OO_HOST`, `OO_PORT`,
  `OO_FETCH_MIN_INTERVAL`, `OO_FETCH_TIMEOUT`, `OO_FETCH_MODE`, `OO_HTTP_PROXY`, `OO_NO_INDEX`,
  `OO_NO_SCHEDULER`, `OO_EPHEMERAL`, `OO_AUTOSEED`, `OO_LLM_MODEL`, `OO_OLLAMA_URL`,
  `OO_CUSTODY_ON_INGEST`, `OO_KEY_PASSPHRASE`, …) plus `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`,
  `DATABASE_ECHO`, `RATE_LIMIT_MS`;
- and contains **posture-contradicting values** (verified at `.env.example:56-72`):
  `UVICORN_HOST=0.0.0.0` (unread, but instructs users to bind publicly), `OLLAMA_HOST=0.0.0.0` +
  `OLLAMA_ORIGINS=*` (would expose the local LLM daemon to the network), `AUTO_DOWNLOAD_MODELS=true`
  (no such code path exists), and `SECRET_KEY`/`CSRF_SECRET`/JWT settings for an **auth system that
  does not exist** (no auth routes; `SECRET_KEY` is read into config at `settings.py:145` and used
  nowhere). The real app binds `127.0.0.1` (`OO_HOST` default, `main.py:1108`).

The "config-driven design" invariant is genuinely honoured for behavior that matters (fetch
politeness, scheduler, custody, data dir), but the *documented* config surface no longer matches
the *real* one. → ARCH-03/04.

## 8. Deployment & CI surface (read-only review; nothing executed)

- `install.sh` (22.5k): menu/whiptail TUI; modes `--template`/`--appvm` (Qubes), `--unattended`,
  `--check`, `--uninstall`; creates venv with `python3.13`, installs extras, alembic + seed,
  optional Ollama (consent-gated), desktop launchers. `set -euo`; no blind `curl|sh` for
  third-party software. Matches pyproject reality.
- `scripts/bootstrap.sh` (66 lines): the README's `curl|bash` target — small, readable, clones and
  hands off to `install.sh`. `scripts/launch.sh`: health-check + browser opener (console/desk).
- `Makefile`: install/test/lint/format/typecheck/migrate/seed/run/check — all consistent with
  pyproject.
- **CI drift (verified `ci.yml:8`):** `push` triggers cover `["0.04", "claude/**"]` but the default
  branch is **`0.07`** — direct pushes to 0.05/0.06/0.07 never ran push-CI; only PRs (unrestricted
  `pull_request` trigger) get checked. The workflow's own header says it replaced six legacy
  workflows that "ran on branches this repo does not use" — and then aged into the same bug. Two
  jobs (test: ruff advisory + alembic drift check + pytest; crypto: PQC signing path), both
  Python 3.13. No external calls beyond PyPI. → ARCH-01.
- `configs/nginx/*`: Docker/VM reverse-proxy configs referencing service names (`web:8000`) and a
  Prometheus/Grafana stack that lives in `quarantine/monitoring_infra` — i.e., these configs serve
  a deployment story the repo no longer ships. Harmless but orphaned.

## 9. Documentation map

15 root docs in `docs/`, all current (git-touched within 48h), with clear lanes and — unusually —
no major status contradictions: the README's ✅/🚧 split matches what Phase 0 verified. Actions
proposed for Phase 5 (not executed now):

| File(s) | Verdict | Rationale |
|---|---|---|
| README, QUICKSTART, USER_MANUAL (1,602), ARCHITECTURE, DESIGN (954), ETHICS, SECURITY, GOVERNANCE, CONTRIBUTING, CHANGES, ROADMAP (2,110), HISTORY (2,597), FUTURE_DEVELOPMENTS | **KEEP** | distinct purposes, accurate, current |
| NEXT_VERSION.md | **MERGE → ROADMAP** | duplicate 0.0.8 planning lane |
| PRESENTATION_PUBLIC.md | **ARCHIVE** | marketing narrative, not technical doc |
| `docs/archive/*.json` (~69 MB; `QUBS_PHASE2_FULL_REPORT.json` alone 62.9 MB) | **PRUNE/COMPRESS** | keep `findings.csv/json` indexes; the full dumps belong in a release artifact or compressed, not the working tree → ARCH-09 |

Contradictions found (small but real): the version triple-drift (§7); `.env.example` vs actual
posture (§7); `configs/settings.yaml` self-describing as `0.03`. The big 2025-era contradictions
the audit brief expected (pillar phase tables, corrupted test counts, fake model catalog) were
already resolved by the quarantine cycle — the fake-model catalog now exists only *as evidence*
in `quarantine/configs_models.yml`.

## 10. Top architectural risks (diagnosis only; fixes are Phase 3–5 work)

| ID | Risk | Severity (arch) | Evidence |
|---|---|---|---|
| ARCH-01 | CI `push` triggers don't include the default branch (`0.07`) — direct pushes ship unchecked; trigger list rots every cycle rename | High | `.github/workflows/ci.yml:8` |
| ARCH-02 | ~3,280 LOC of dead packages inside live `src/` (`ingestor` 2,507, `custom_types`, `compliance`, `audit`, `reports`); two tests validate the *legacy* `ingestor.url_utils` instead of the live `src/utils/url_utils` | High | import graph; `tests/test_url_utils.py:34`, `test_scraper.py:43` |
| ARCH-03 | `.env.example` contradicts the security posture (`0.0.0.0` binds, `OLLAMA_ORIGINS=*`), documents nonexistent behavior (`AUTO_DOWNLOAD_MODELS`) and a nonexistent auth system, and omits the 21 real `OO_*` vars | High | `.env.example:56-72`; grep matrix §7 |
| ARCH-04 | `configs/settings.yaml` half-dead (13 unread keys; version "0.03"; `app_version` default "0.02") — erodes the config-driven-design invariant | Medium | `src/config/settings.py:83,145,257-260` |
| ARCH-05 | `src/api/main.py` (1,119 lines) mixes app assembly, lifecycle, UI serving, and page-sized handlers (`view_article` 197 lines) | Medium | `main.py:713-910` |
| ARCH-06 | Postgres path is untested scaffolding while search is SQLite-FTS5-only — capability ambiguity in a trust-critical product | Medium | `fts.py:249`; no PG tests |
| ARCH-07 | Suite is red on a core-only install (analysis tests fail rather than skip) — undermines the "extras are optional" contract | Medium | Phase 0 §5 |
| ARCH-08 | Three parallel external-I/O clients (EthicalFetcher, WikiClient, IMAP email) + DuckDuckGo discovery service — politeness/SSRF policy is per-client, risking divergence as clients multiply | Medium | `src/wiki/client.py:25-69`, `src/ingest/email.py:124-154`, `src/services/duckduckgo.py` |
| ARCH-09 | ~69 MB of prior-audit JSON in `docs/archive/` bloats every clone | Low | `ls -la docs/archive` |
| ARCH-10 | Floor-only dependency pins, no lockfile — irreproducible installs for the offline/Qubes target; plus `/docs` Swagger CDN reference (only external asset) | Low/Medium | `pyproject.toml`; Phase 0 §4 |

**Carried to Phase 2 for adversarial verification:** robots/SSRF edge cases (the design is right —
the question is whether tests prove the edges), the missing persistent ingest-audit trail, LLM model
pass-through, `OO_FETCH_MODE`/`OO_HTTP_PROXY` semantics, and the dead-test problem (tests asserting
against legacy copies).
