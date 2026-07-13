# Architecture & technical reference

The technical companion to the User Manual: the database/configuration, the HTTP API map, and internationalisation.

## Contents
- [Database Configuration for Open Omniscience](#database-configuration-for-open-omniscience)
- [API Reference](#api-reference)
- [Internationalisation (i18n) — making the app multilingual](#internationalisation-i18n-making-the-app-multilingual)


---

## Database Configuration for Open Omniscience

> **Status (verified in the v0.0.7 audit, `docs/archive/audits/00_BASELINE.md`):** the database layer
> **works and is tested** — the server boots, creates/uses the SQLite store, applies Alembic
> migrations, and the full test suite (800+) passes against it. The old "early concept —
> not functional" banner that used to sit here described a pre-rebuild state and was long
> out of date.

### 🗃️ SQLite — the supported store

SQLite is the **default and the only supported, tested backend**. It fits the product's
local-first, single-operator design.

- **Zero configuration:** the database is created automatically at first run, at
  `<data dir>/open_omniscience.db`. The data dir is `OO_DATA_DIR` if set, else the repo's
  `data/` in a source checkout, else `$XDG_DATA_HOME/open-omniscience` (see `src/paths.py`).
- **Tuned automatically:** the engine applies `WAL` journal mode, `foreign_keys=ON`,
  `busy_timeout=30000` and `synchronous=NORMAL` on every connection
  (`src/database/session.py`) — you do not need to set these yourself.
- **Full-text search** is SQLite **FTS5** (`article_fts`, external-content, kept in sync by
  triggers — `src/database/fts.py`).
- **Override the location** with the `DATABASE_URL` environment variable (do **not** edit
  source files): `DATABASE_URL=sqlite:////absolute/path/to/your.db`
- **Maintenance:** an occasional `sqlite3 <db> "VACUUM;"` reclaims space (the v0.0.7 audit
  also removed a redundant index that was ~63% of the file on large corpora; run `make
  migrate` once after upgrading to drop it from existing databases).

### 🐘 PostgreSQL — experimental scaffolding, NOT supported

Honesty over aspiration (audit finding ARCH-06): the engine layer *recognises* a
PostgreSQL `DATABASE_URL` (connection pooling via `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`), **but**

- **full-text search does not exist on PostgreSQL** — the FTS5 setup deliberately no-ops on
  non-SQLite engines, so the Search tab would be dead;
- the test suite never runs against PostgreSQL, and no CI covers it;
- no published deployment has used it.

Treat PostgreSQL as **untested scaffolding for a possible future**, not a choice you can
make today. If multi-writer scale ever becomes a real requirement, the roadmap item is a
`tsvector` search path plus a PostgreSQL CI matrix — until that lands, this page will not
pretend.

### 🔄 Migrations

Alembic is configured at the **repository root** (`alembic.ini`, `migrations/`). Alembic is
installed with the app (it is a core dependency — no separate install).

- **Fresh databases** are created complete (`create_all` + FTS) and stamped with the current
  migration head automatically at startup.
- **Upgrading an existing database:**
  ```bash
  make migrate          # = alembic upgrade head, from the repo root
  ```
- **Creating a migration** (contributors): edit `src/database/models.py`, then
  ```bash
  alembic revision --autogenerate -m "your message"
  alembic upgrade head
  ```
  and check the generated file — autogenerate misses FTS virtual tables (those live in
  `src/database/fts.py`, applied at startup).
- **Rolling back:** `alembic downgrade -1`.

---

### 📊 Database Schema

#### Tables:

##### `sources`
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `name` | STRING(100) | Name of the source (e.g., "BBC News") |
| `domain` | STRING(255) | Domain of the source (e.g., "bbc.com") |
| `rss_url` | STRING(500) | URL of the RSS feed (if available) |
| `rate_limit_ms` | INTEGER | Delay between requests in milliseconds |
| `enabled` | BOOLEAN | Whether the source is active for scraping |
| `priority` | INTEGER | Priority level (1 = high, 3 = low) |
| `tags` | STRING(500) | Comma-separated list of tags |

##### `articles`
| Column | Type | Description |
|--------|------|-------------|
| `id` | INTEGER | Primary key |
| `url` | STRING(1000) | Original URL of the article |
| `canonical_url` | STRING(1000) | Canonicalized URL (for duplicate detection) |
| `source_id` | INTEGER | Foreign key to `sources` |
| `title` | STRING(500) | Title of the article |
| `content` | TEXT | Full text content of the article |
| `published_at` | DATETIME | Publication date/time (ISO format) |
| `language` | STRING(10) | Language code (e.g., "en", "fr") |
| `hash` | STRING(64) | SHA-256 hash of the content (for duplicate detection) |
| `created_at` | DATETIME | Timestamp when the article was ingested |

> The columns above are the core fields; the live schema (`src/database/models.py`)
> and the Alembic migrations under `migrations/versions/` are the source of truth.
> `articles` also carries provenance/analysis fields (author, word_count, region,
> country, sentiment) and a compressed-content column.

##### Other tables (see models / migrations for full columns)

| Table | Purpose |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | Source grouping + geo/robots metadata |
| `commodity_prices` | Observed price points (symbol, date, price, currency, **unit**, market, source) — charts + price↔news correlation |
| `market_extraction_rules` | Per-source rule (CSS selector / attribute / regex) locating one instrument's price on one page; category financial/stock/commodity |
| `keywords` | Distinct keyword/entity term (normalized, language, `is_entity`/`entity_type`, **`extractor`** provenance) |
| `keyword_mentions` | One per (article, keyword): count + first char offset + denormalised `observed_on`/`country`/`city` — powers Insights trends, associations, context, map |
| `wiki_pages` | A tracked Wikipedia page in one language edition; holds **one** compressed full-text baseline |
| `wiki_revisions` | One tracked edit: **diff + signed byte delta** + flags/tags (not a re-copy), optional ORES scores, honest large-edit flag + reasons |
| `article_analyses` | Derived LLM results (summary/translation) with model + prompt provenance |
| `keyword_categories`, `external_sources`, `article_links`, … | Keyword categorisation + link/source-relationship tracking |

#### Indexes:
- `idx_article_hash`: Unique index on `hash` (for duplicate detection).
- `idx_article_canonical_url`: Index on `canonical_url` (for URL lookups).
- `idx_article_source_id`: Index on `source_id` (for source-based queries).
- `idx_article_content`: Index on `content` (for full-text search).

---

### 🔍 Full-Text Search

For advanced full-text search, consider the following:

#### SQLite:
SQLite has built-in full-text search (FTS) capabilities. To enable:
1. Create a virtual table:
   ```python
   from sqlalchemy import text
   session.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS articles_fts USING fts5(title, content)"))
   ```
2. Insert data into the FTS table (trigger-based or manually).

#### PostgreSQL:
PostgreSQL has excellent full-text search support. Example query:
```python
from sqlalchemy import func
results = session.query(Article).filter(
    func.to_tsvector('english', Article.content).match('your & search & query')
).all()
```

---

### 📉 Monitoring and Maintenance

#### SQLite:
- **Check database size**:
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **Check table sizes**:
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```

#### PostgreSQL:
- **Check database size**:
  ```bash
  psql -U open_omniscience -d open_omniscience -c "SELECT pg_size_pretty(pg_database_size('open_omniscience'));"
  ```
- **Check table sizes**:
  ```bash
  psql -U open_omniscience -d open_omniscience -c "SELECT table_name, pg_size_pretty(pg_total_relation_size(table_name)) FROM information_schema.tables WHERE table_schema='public';"
  ```
- **Monitor connections**:
  ```bash
  psql -U open_omniscience -d open_omniscience -c "SELECT * FROM pg_stat_activity;"
  ```

---

### 🚨 Troubleshooting

#### Common Issues:

##### SQLite:
- **"Database is locked"**:
  - SQLite only allows one writer at a time. WAL mode is enabled by default
    (`src/database/session.py`) and a process-wide single-writer gate
    (`src/database/writer.py`) serialises in-app writes, so concurrent ingest +
    import no longer collide. A persistent lock means another *process* is writing.

- **"Too many open files"**:
  - SQLite opens a new connection for each thread. Limit the number of threads or use connection pooling.

##### PostgreSQL:
- **"Connection refused"**:
  - Ensure PostgreSQL is running:
    ```bash
    sudo systemctl status postgresql
    ```
  - Check the connection string (host, port, username, password).

- **"Permission denied"**:
  - Verify the user has permissions on the database:
    ```sql
    GRANT ALL PRIVILEGES ON DATABASE open_omniscience TO open_omniscience;
    ```

- **"Relation does not exist"**:
  - Run the migrations:
    ```bash
    alembic upgrade head
    ```

---

### 📌 Best Practices

1. **Backup Regularly**:
   - **SQLite**: Copy the `open_omniscience.db` file.
   - **PostgreSQL**: Use `pg_dump`:
     ```bash
     pg_dump -U open_omniscience -d open_omniscience > open_omniscience_backup.sql
     ```

2. **Test Migrations**:
   - Always test migrations on a backup of your database before applying to production.

3. **Monitor Performance**:
   - Use tools like `pgAdmin` (PostgreSQL) or `sqlite3` CLI to monitor query performance.

4. **Optimize Queries**:
   - Use `EXPLAIN ANALYZE` (PostgreSQL) or `.explain()` (SQLite) to analyze slow queries.

5. **Limit Data Retention**:
   - Regularly archive or delete old articles to keep the database manageable.
   - Example: Delete articles older than 1 year:
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
*Copyright © 2026 Ideotion. Licensed under the GNU General Public License v3.0
or later (GPL-3.0-or-later) — see [LICENSE](../LICENSE). This is free software;
you may redistribute and modify it under those terms.*


---

## API Reference

The live, always-accurate API reference is generated by the app itself:

- **Swagger UI:** http://127.0.0.1:8000/docs
- **OpenAPI JSON:** http://127.0.0.1:8000/openapi.json

The app binds to loopback only and (for a single local user) requires no auth.

### Endpoint groups

This is a **map of the key groups, not an exhaustive list** — the live
`/openapi.json` (above) is always authoritative. The routers are wired in
`src/api/main.py` via `include_router(...)`; groups marked **[analysis]** require
the `[analysis]` extra (the app still boots without it, those endpoints disabled).

| Prefix | What it does |
|--------|--------------|
| `GET /api/health` | Liveness + version |
| `GET /api/articles`, `/api/articles/export` | Boolean full-text search (FTS5) + CSV/JSON export |
| `POST /api/ingest`, `/api/sources/{id}/ingest`, `/api/sources/{id}/ingest-email` | Ethical ingestion: single URL, RSS feed, IMAP mailbox |
| `… /api/sources`, `/api/sources/...` | Source + group + metadata management |
| `POST /api/sources/seed-defaults` | Seed the curated source catalogs (news + markets + generated world catalog) |
| `GET /api/database/stats`, `/coverage`, `/countries` | Corpus row counts + on-disk size; country coverage; per-country source counts + topic keywords |
| `GET /api/database/backup` | Consistent SQLite snapshot download (SQLite only) |
| `POST /api/database/v2/restore/preview`, `/v2/restore/commit`, `/api/backup/v2/*` | **Additive-only** restore via the signed `oo-backup-2` artifact: preview the merge plan, then commit. Restore **never overwrites your corpus** — it merges duplicate-lessly, keeping local values on conflict (the destructive replace path was removed on 2026-06-13) |
| `GET/PUT /api/settings` | GUI preferences (theme, default result limit) |
| `… /api/scheduler/...` | Background ingester: status, start, stop, run-now, config (modes: rss / crawl / markets) |
| `… /api/markets/rules`, `/rules/{id}/run`, `/overview` | Per-source price-extraction rules + a "test" run + Markets overview |
| `GET /api/markets/feeds`, `POST /feeds/{key}/import`, `/feeds/import-url` | Official CSV price-feed catalog + import (FRED/World Bank/EIA) + custom-URL import |
| `GET /api/catalog/export.csv`, `/template.csv`, `/columns`, `POST /api/catalog/import` | Source-list CSV export / template / columns / upsert-by-domain import |
| `… /api/insights/...` | Keyword & entity analytics: status, reindex, top, trending, trend, associations (PMI), context, map |
| `GET /api/timemap`, `/timemap/range` | Space-time signals on one map+time-axis (anchors + geocoded corpus + opt-in hazards/mentioned-dates); `?kinds`, `?start`/`?end` fractional-year window, `?hazards`, `?articles`, `?mentions`, `?days` |
| `… /api/article-dates/...` | Extracted dates mentioned in article text as human-confirmable per-article tags: list/extract per article, confirm/reject, batch index, by-date corpus filter |
| `GET/POST /api/llm/...` | Local LLM (Ollama): health, models, generate, summarize an article |
| `… /api/commodities/...` | Commodity prices (import / CSV / list) + honest price↔news correlation |
| `POST /api/analysis/...` | Scientific-rigor stats: t-test, correlation, ANOVA, Mann-Whitney, CI |
| `GET /api/monitoring/...` | Real source-uptime health + corpus-volume anomalies |
| `POST /api/verify/image-metadata` | Honest image EXIF/metadata extraction |
| `POST /api/reports/evidence`, `/evidence/verify` | Signed, tamper-evident evidence bundles |
| `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`, `GET /api/custody/export`, `POST /api/custody/verify` | Append-only, hash-chained signed chain-of-custody log + offline verification |
| `GET/PUT /api/custody/settings` | Runtime custody preferences (post-quantum signing, anchoring mode, auto-log) — reports *effective*, availability-aware state |
| `POST /api/custody/anchor`, `GET /api/custody/providers` | Anchor a Merkle root (local / OpenTimestamps) + provider availability |
| `… /api/keywords/...`, `/api/analysis/articles/similarity` | **[analysis]** Keyword extraction + article similarity |
| `GET /api/search/omni` | Index-backed federated omnibar (articles FTS5 + keywords + sources + wiki/law) |
| `… /api/jobs/...` | Task-manager job aggregation (collect pass, in-flight fetch, wiki-dump queue + reorder) |
| `… /api/system/...` | System vitals + network state/consent (airplane-mode kill switch, local interface IPs) |
| `… /api/safety/...` | Safety controls: kill switch, discovery gate, restore-from-encrypted-artifact |
| `… /api/briefing/...` | Home briefing producers (evidence-tiered cards; method+caveat+n) |
| `… /api/insights/...`, `/api/insights/who`, `/where` | Keyword/entity analytics + corpus-wide Who/Where aggregation |
| `… /api/links/...` (shared, preview) | Shared-outbound-link / citation-graph analysis + local link-preview dialog |
| `… /api/events/...`, `/api/events/astronomy`, `/climate` | Agenda events incl. locally-computed astronomy (Meeus) + El Niño table |
| `POST /api/weather/context` | Consented, bounded Open-Meteo reanalysis slice for corroboration |
| `… /api/law/...` | Tracked legislation/primary-source change feed |
| `… /api/integrity/...` | Echo / coordination / lineage signals |
| `… /api/annotations/...` | Local, optionally signed article annotations |
| `… /api/wiki/...` | Wikipedia editions, watched pages, dump download/read, corpus sync |
| `… /api/hazards/...`, `/api/timemap` | Hazard overlays + space-time map |
| `GET /unlock`, `POST /api/unlock`, `/create-db`, `/doctor`, `/encrypt-db` | At-rest encryption: locked-boot unlock screen, create encrypted/plaintext store, header attestation, one-way encrypt tool |

Routers marked **[analysis]** (commodities, statistics, keywords, framing)
require the `[analysis]` extra; without it the app still boots with the core
spine and those endpoints are disabled.

Behaviour notes:
- Ingestion fetches through the ethical fetcher only (robots.txt fail-closed, rate
  limited); LLM endpoints return **503** if Ollama is unavailable (never a fake answer).
- Evidence verification: pass the signer's public key to prove provenance, not just
  integrity (see [QUICKSTART](QUICKSTART.md) and `scripts/verify_evidence.py`).
- Custody settings are *preferences*, not guarantees: `GET/PUT /api/custody/settings`
  always report the **effective** state (preference **and** library availability), so
  post-quantum / OpenTimestamps never appear enabled when the supporting extra is
  absent. Anchoring defaults to the offline `local` provider; OpenTimestamps and
  public-chain anchoring carry a privacy warning (see
  [CHAIN_OF_CUSTODY](USER_MANUAL.md)).


---

## Internationalisation (i18n) — making the app multilingual

> Goal: the **entire UI** (and, over time, the **documentation**) available in ~a
> dozen languages, to widen open access toward "almost all humans." Done the
> project's way: **offline, no CDN, no runtime translation API, no telemetry**, and
> **honest** about translation quality (we don't ship machine guesses as if they were
> authoritative).

---

### The dozen languages (Phase 1 set)

Chosen for reach (native + second-language speakers) and to deliberately include the
Global South (per `ROADMAP.md`’s anti-bias goal):

| Code | Language | Native name | Script / dir | Status |
|---|---|---|---|---|
| `en` | English | English | LTR | **source** (complete) |
| `fr` | French | Français | LTR | **complete** (vouched) |
| `es` | Spanish | Español | LTR | **complete** (vouched) |
| `de` | German | Deutsch | LTR | **complete** (vouched) |
| `zh` | Chinese (Mandarin) | 中文 | LTR | stub → community |
| `hi` | Hindi | हिन्दी | LTR | stub → community |
| `ar` | Arabic | العربية | **RTL** | stub → community |
| `bn` | Bengali | বাংলা | LTR | stub → community |
| `ru` | Russian | Русский | LTR | stub → community |
| `pt` | Portuguese | Português | LTR | stub → community |
| `id` | Indonesian | Bahasa Indonesia | LTR | stub → community |
| `ja` | Japanese | 日本語 | LTR | stub → community |

Easy next additions for reach: **Swahili (`sw`)**, **Urdu (`ur`, RTL)**, Italian
(`it`), Turkish (`tr`), Vietnamese (`vi`).

**Honesty stance.** A *stub* makes a language **selectable now** and falls back to
English for any untranslated string — so the dozen are "available" without pretending
they're translated. We mark each locale `complete | draft | stub`. The maintainer
ships only what they can vouch for; everything else is filled by **community
contribution** (this is precisely how open-source widens access).

---

### Architecture (offline, dependency-free)

`src/static/i18n.js` + `src/static/locales/<code>.json`. No build step, no network.

- **English is the key.** Locale files map the **English UI string → its translation**
  (e.g. `"Search the corpus": "Rechercher dans le corpus"`). This lets us retrofit the
  existing UI without tagging every element, and keeps English as the canonical
  source.
- **`OOI18N.setLang(code)`** loads `locales/<code>.json`, persists the choice in
  `localStorage` (`oo.lang`), sets `document.documentElement.lang` and `dir` (RTL for
  `ar`/`ur`), then **`apply()`** walks the DOM — translating text nodes whose trimmed
  text matches a key, plus `placeholder`/`title`/`aria-label` attributes. Unknown
  strings are left as-is (English fallback) — nothing ever breaks.
- **Dynamic content** (data: article titles, source names, counts) is **never**
  translated — only the chrome. JS-rendered chrome (command palette, drawer) calls
  `OOI18N.apply()` after it renders.
- Each locale carries `_meta` (`name`, `native`, `dir`, `status`).

#### Integrating it (Phase 2 — shipped; Desk has since been retired)

Two lines in `index.html` (and, before its 2026-06-10 retirement, `desk.html`),
then a language picker:

```html
<script src="/static/i18n.js"></script>
<!-- after first render and on each view change: --> OOI18N.apply();
```

The **Language** selector lives in Settings and calls `OOI18N.setLang(code)`,
persisted alongside the other local UI prefs.

---

### Documentation in many languages

Docs are long and translation quality matters more than for short UI strings, so:

- Structure: `docs/i18n/<code>/<DOC>.md` mirrors `docs/`.
- The **English docs remain canonical**; translations are community/maintainer work,
  each marked with its translation date and the English commit it tracks.
- We do **not** auto-machine-translate docs and present them as authoritative — that
  would violate the project's honesty principle. Start with the highest-value, shortest
  docs (QUICKSTART, the "What you'll see first" tour, ETHICS) per language.

---

### Contribution workflow (open access by design)

1. Copy `locales/en.json` → `locales/<code>.json`, translate values, set `_meta.status`.
2. For RTL languages set `_meta.dir: "rtl"`.
3. Run the (planned) key-coverage check: report missing/extra keys vs `en.json`.
4. Submit. Untranslated keys simply fall back to English until filled.

---

### Status

**Phase 1 (done):** the i18n engine (`i18n.js`), the locale scaffold for all 12
languages, and complete reference translations for **en/fr/es/de**; the rest are
selectable stubs (English fallback).

**Phase 2 (done — pending a real browser pass):** `i18n.js` is included in
`index.html` (and was in `desk.html` until Desk's 2026-06-10 retirement); a
**Language** picker (`#oo-lang-select`) is in Settings and auto-wired; dynamically-rendered chrome is translated automatically by
a debounced `MutationObserver` (no scattered `apply()` calls); switching to English
restores originals; RTL via `<html dir>`. Structure/syntax are validated, but
behaviour should still be eyeballed in a browser.

**Phase 3 (next):** extend `en.json` to the *full* string catalogue (it currently
covers the high-traffic chrome), complete the stub locales (community), and polish
RTL layout for `ar`/`ur`.


## Export contract (versioned)

Machine-readable exports carry a stable, self-describing contract (schema `oo-export-1`,
0.0.8 part 2 / RM-15) so downstream pipelines never guess:

- **JSON** (`/api/articles/export?format=json`, `/api/links/export.json`): an envelope —
  `{export_schema, kind, app_version, generated_at, query, count, articles|data}`. The
  `query` object is the verbatim generating selection; provenance travels with the data.
- **CSV** (`/api/articles/export?format=csv`): the columns are unchanged (a comment line
  would break naive readers); the same envelope rides as HTTP headers
  (`X-OO-Export-Schema`, `X-OO-App-Version`, `X-OO-Generated-At`, `X-OO-Query`).
- **Citation graph** (`/api/links/export.graphml`, `.json`): the who-cites-whom graph
  (stored articles → external registrable domains). **Counts only — no inferred
  credibility, no scores**; the caveat is embedded in the file itself. GraphML opens in
  Gephi/yEd/NetworkX.

Schema changes bump `oo-export-N`; existing fields are never silently repurposed.
