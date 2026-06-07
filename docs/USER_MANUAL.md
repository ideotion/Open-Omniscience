# Open Omniscience — User Manual

*An open-source, ethical, local-first intelligence platform for investigative
journalism.* This manual is the friendly, end-to-end guide: what the app is, how
to install and run it, and a tour of **every tab, control, setting and workflow**,
followed by a technical reference (data locations, environment variables, the full
HTTP API) and troubleshooting.

> **In one sentence:** Open Omniscience ethically gathers news (and Wikipedia
> edits, and market prices) into one searchable, deduplicated, provenance-tracked
> SQLite database on *your* machine, lets you analyse it (search, trends, maps,
> framing, local-LLM summaries), and can produce **cryptographically signed,
> offline-verifiable evidence** of what it held and when.

**Design promises that shape everything below:**

- **Local-first & private.** Everything runs on `127.0.0.1` (loopback only). No
  accounts, no telemetry, nothing leaves your machine — the only outbound traffic
  is the ethical scraper fetching the sources you point it at (and, if you opt in,
  Wikipedia/OpenTimestamps/Ollama).
- **Honest numbers only.** Every figure is a real `COUNT(*)`, a real on-disk byte
  size, or a real statistical aggregate with its sample size and caveat. The app
  would rather show an error than invent a value. (Several earlier "AI detection"
  features that faked scores were removed — see `docs/SALVAGE_MAP.md`.)
- **Ethical ingestion.** One fetch path. `robots.txt` is respected **fail-closed**
  (if in doubt, it does *not* fetch), every host is rate-limited, and nothing is
  stored unless a real article body was extracted.

---

## Table of contents

1. [Install & first run](#1-install--first-run)
2. [The 60-second tour](#2-the-60-second-tour)
3. [The tabs, one by one](#3-the-tabs-one-by-one)
   - [Search](#31-search) · [Ingest](#32-ingest) · [Sources](#33-sources) ·
     [Database](#34-database) · [Markets](#35-markets) · [Insights](#36-insights) ·
     [Wikipedia](#37-wikipedia) · [Chain of custody](#38-chain-of-custody) ·
     [Settings](#39-settings)
4. [Common workflows (how-to)](#4-common-workflows-how-to)
5. [Technical reference](#5-technical-reference)
   - [Where your data lives](#51-where-your-data-lives) ·
     [Environment variables](#52-environment-variables) ·
     [Optional extras](#53-optional-extras) ·
     [The HTTP API](#54-the-http-api)
6. [Troubleshooting](#6-troubleshooting)
7. [Glossary](#7-glossary)

---

## 1. Install & first run

Open Omniscience targets **Python 3.13** on Debian-based Linux (it is designed for
a **Qubes OS** Debian AppVM, but runs on any modern Linux). It is a single-user,
local-first app.

### Easiest: the one-line installer

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

This clones the repo and runs `./install.sh`, a small menu where you choose:

- **Core** — scrape, store, search, export (always installed).
- **Analysis tools** — statistics, keyword/entity analytics, market correlation
  (the `[analysis]` extra; pulls in scipy/scikit-learn, optionally spaCy for real
  named-entity recognition).
- **Local LLM tools** — Ollama plus a model, for on-device summarise/translate.

Re-run `install.sh` any time to add extras. It also creates an **Open Omniscience**
launcher in your apps menu and on the Desktop — double-click it to start the app
and open your browser at `http://127.0.0.1:8000`.

> Always inspect a script before piping it to a shell. The
> [`bootstrap.sh`](../scripts/bootstrap.sh) is tiny; you can also clone the repo
> and run `./install.sh` yourself.

**On Qubes:** run `sudo ./install.sh --template` inside the TemplateVM, reboot the
AppVM, then run `./install.sh` in the AppVM.

### Developer / manual install

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"     # core + analysis + test tooling
pytest -q                            # full suite should be green
open-omniscience                     # serves http://127.0.0.1:8000
```

On first launch the app **auto-seeds a worldwide catalog (~1,780 sources)** so you
have something to ingest immediately, initialises the SQLite database and FTS
index, and (if enabled) starts the background scheduler.

### What you'll see first

If your corpus is empty, a **welcome banner** appears above the tabs with a single
button: **"Seed sources & run a first ingestion."** Click it and the app registers
the curated catalog and runs one ingestion pass — after which **Search** has real
articles in it. You can dismiss the banner at any time.

The **header bar** (always visible) shows the version, a health pill
(`healthy`/`offline`), an **LLM** pill (`LLM ✓ (N models)` / `LLM offline`), and an
**API docs** link to the interactive OpenAPI page at `/docs`.

---

## 2. The 60-second tour

The core loop is:

> **Pick/add a source → Ingest → Search → (analyse) → Export / sign.**

1. **Sources** — a worldwide catalog is already seeded; add your own if you like.
2. **Ingest** — fetch a source's RSS feed or paste a single article URL. Or let
   the **scheduler** do it automatically on an interval.
3. **Search** — Boolean full-text search across everything you've gathered.
4. **Insights / Markets / Wikipedia** — optional analysis layers on top of the
   corpus.
5. **Export** — CSV/JSON, or a **signed evidence bundle** anyone can verify
   offline.

Everything is tab-based, the active tab refreshes itself live (every few seconds)
while it's on screen, and actions confirm with small toast notifications in the
corner. Destructive actions always ask first.

---

## 3. The tabs, one by one

The nav has nine tabs, in this order: **Search · Ingest · Sources · Database ·
Markets · Insights · Wikipedia · Chain of custody · Settings.**

### 3.1 Search

**What it's for:** finding articles in your corpus.

- **Boolean query** — supports `AND` / `OR` / `NOT`, `"exact phrases"`, and
  parentheses with correct precedence, e.g.
  `(climate OR energy) AND policy NOT opinion`. Backed by SQLite FTS5 and fully
  parameterised (no injection).
- **Filters:** Source (exact name), Language (code like `en`), and a **From/To**
  date range. All optional.
- **Search** runs the query; the results table shows **Title · Source · Published ·
  Language**, and a count (`N result(s)`, and how many are shown if truncated).
- **Per-row actions:** **open** (a clean offline copy of the stored article),
  **source ↗** (the original URL), **Summarize** and **Translate** (local LLM, if
  Ollama is available).
- **Exports:** **Export CSV**, **Export JSON**, and **Export signed evidence** — a
  tamper-evident, signed bundle of exactly the articles matching your query (see
  [Chain of custody](#38-chain-of-custody)).

### 3.2 Ingest

**What it's for:** getting articles into the corpus — automatically or manually.

**A. Automatic ingestion (the scheduler).** A background worker that ingests on a
timer. Controls:

- **Start / Stop / Scrape now** — run continuously, halt, or run a single pass
  immediately. The status pill shows `running` / `running — scrape in progress` /
  `stopped` and the next run time; the line below shows the last run's tally.
- **Interval (minutes)**, **Max sources / run**.
- **Mode:** *RSS feeds*, *Recursive crawl*, *Markets (price rules)*, or *Wikipedia
  (watched pages)*. Choosing **crawl** reveals **Crawl depth** and **Max pages /
  source** (the crawler stays inside each source's own domain, honours robots.txt
  fail-closed, is rate-limited, and is hard-bounded — it *discovers* articles, it
  does not mirror sites).
- **Targeting:** **Languages**, **Source types**, and **Tags/keywords (match any)**
  narrow which sources a run touches. **Preview targets** shows exactly how many
  sources match (with a breakdown by language and type) *before* you run.
- **Start automatically on launch** + **Save schedule** persist the configuration.

**B. Manual ingest.**

- **Ingest a source's RSS feed** — pick a source, click **Fetch feed**.
- **…or ingest a single article URL** — paste a URL, click **Ingest URL**.

Either way the result line shows a tally: stored, duplicates skipped, blocked by
robots, etc. Fetching is always ethical (robots fail-closed, rate-limited).

### 3.3 Sources

**What it's for:** registering and curating the outlets you gather from.

- **Add a source:** Name, Domain, RSS URL, Tags → **Add source**. Or **Seed
  starter sources** to register the curated public-interest set.
- **Manage sources (table):** filter by search text, country, language, type, tag,
  and enabled-state. Columns are **sortable** (Name, Domain, Type, Country, Lang,
  Priority, Articles). Inline you can change **Priority** (1–3), toggle **Enabled**,
  and **Delete** (with confirmation). Paginated, with a `N source(s)` count.
- **Import / Export (CSV):** **Export all (CSV)**, **Download template**, and
  **Import CSV**. Columns: `name`, `domain` (required), plus `rss_url`,
  `source_type`, `country` (2-letter), `language`, `region`, `tags`
  (comma-separated), `priority` (1–3), `rate_limit_ms`, `enabled`,
  `reliability_score` (1–10). Import **upserts by domain** — new rows created,
  existing updated — and **bad rows are reported, not silently dropped**.

### 3.4 Database

**What it's for:** an honest look at what you actually hold, and how widely your
sources reach.

- **Database stats:** live, animated counts (articles, sources, unique domains,
  …), plus the backend and the **on-disk size and path** of the database. Every
  figure is a real count or byte size — nothing estimated. **Refresh** re-reads.
- **World coverage:** how many countries your source catalog reaches, scored
  against ISO 3166 — `covered/total countries`, `coverage %`, count *not* covered,
  and count "thin" (below threshold). The table lists each country with its source
  count and **topic-keyword pills** (from source tags). **Click a country code or a
  keyword** to jump to Sources filtered to exactly those sources. A gap report
  lists the countries with no source yet.

### 3.5 Markets

**What it's for:** tracking **real** commodity / currency / energy prices and
relating them to news volume.

- **Market trends dashboard:** a card per price series — symbol, % change, latest
  price (currency/unit), point count, and a mini sparkline. A **Time scale**
  selector (1 month → all) reshapes every card. Click a card for a full chart plus
  a **price↔news correlation** (real Pearson/Spearman coefficient, p-value and
  sample size — never a guessed number). **Load / refresh market data** imports the
  curated official feeds.
- **Configure data sources** (collapsible — most users won't need it):
  - **Official price feeds** (FRED, which carries the **World Bank "Pink Sheet"**
    and **EIA** series): one-click **Import**, plus **Chart**.
  - **Price-extraction rules:** add a rule (Source, Symbol, Label, Page URL, **CSS
    selector**, optional attribute/regex, currency, unit, market). The golden rule:
    **a number is stored only where your selector actually lands on one — never
    guessed.** Use **Test** to fetch the page once and see the exact value found, or
    the exact reason it didn't match, before relying on it.
  - **Custom feed (any CSV URL):** point at any CSV (default mapping is column 1 =
    date, column 2 = value, the FRED convention); missing values are skipped, never
    stored as zero.

See [`docs/MARKETS.md`](MARKETS.md) for the full extraction-rule reference.

### 3.6 Insights

**What it's for:** keyword & entity analytics over the **text of ingested
articles**. *(Requires the `[analysis]` extra; real named-entity recognition is
opt-in via the spaCy `[nlp]` extra.)*

- **Status & indexing:** a pill shows `indexed/total articles · keywords (entities)
  · mentions · remaining`. Click **Index corpus** to extract keywords/entities in
  batches (people, organisations and places are kept as single units). Indexing is
  resumable and the bar updates live.
- Three sub-tabs:
  - **Explore** — type a keyword or entity (e.g. *inflation*, *Emmanuel Macron*,
    *Rio Tinto*) to get: a **trend** line over time; an **associations mind-map**
    (PMI-ranked co-occurring terms — edge width = co-occurrence, distance =
    strength; click a node to recenter); a **framing** table (how each outlet's
    tone differs, via VADER, with the terms it emphasises); and **in-context**
    snippets with source/place/date links.
  - **Trends** — **Rising** (keywords growing fastest, recent vs. baseline window)
    and **Top** (most-mentioned), filterable by kind (terms/entities/people/orgs/
    places) and country. Click any term to Explore it; click ✕ to exclude it.
  - **Map** — a zoomable, pannable world map with city pins sized by mention count
    (real lat/lon from a Wikidata gazetteer), plus per-country and per-city tables.

Every figure is a real aggregate with its sample size and a caveat. See
[`docs/INSIGHTS.md`](INSIGHTS.md). To tune which keywords appear, use the
[keyword filter in Settings](#39-settings).

### 3.7 Wikipedia

**What it's for:** watching specific Wikipedia pages and **flagging suspicious
edits** — the *edits* are the data, not a copy of the article.

- Add a page to watch by **Edition** (language code, e.g. `en`, `fr`, `ar`),
  **Article title**, and an optional **Watchlist** label. The app stores **one
  baseline snapshot**, then only **diffs/deltas** of each new edit — so cosmetic
  changes cost almost nothing.
- **Track now** (optionally **using ORES scores**) pulls new revisions and flags
  large or suspicious ones: big size deltas, revert/blank tags, anonymous edits,
  edit bursts, and — if enabled — ORES damaging/good-faith ML scores. Candidates
  are *surfaced for you to judge*; nothing is labelled "disinformation."
- **Flagged changes** lists edits (When · Edition · Page · Editor · Δ bytes ·
  Reasons · ORES), with a **Diff** viewer and a **live** link to Wikipedia.
  Filter by *flagged only* and by edition.

Heavy **offline full-text baselines** (whole-edition dumps) are *separate* and live
in **Settings → Wikipedia** — you don't need them for change-tracking. See
[`docs/WIKIPEDIA.md`](WIKIPEDIA.md).

### 3.8 Chain of custody

**What it's for:** proving — to a sceptical third party, offline — that your corpus
held *this* item, with *this* content, at *this* time, and that the record hasn't
changed since. It is **not** a whistleblower/SecureDrop system; a "source" here is a
news outlet, not a confidential human.

The panel has three parts:

- **Settings & status.** Toggles for **Post-quantum signatures** (add an ML-DSA /
  FIPS-204 signature alongside Ed25519), **OpenTimestamps anchoring** (anchor to
  Bitcoin for independent proof of time), **Auto-log on ingest** (append a signed
  entry on every successful ingest), and a **Default actor** label. Crucially, the
  status always shows the **effective** state, not just your wish: if you enable PQC
  or OpenTimestamps but the supporting library isn't installed, it says *"requested,
  library not installed"* and stays Ed25519-/local-only — **it never shows a green
  light it can't back up.** Key protection is shown too (`aes256gcm-scrypt` if you
  set `OO_KEY_PASSPHRASE`, otherwise `unencrypted`).
- **View & verify chain.** Enter an item id (e.g. `article:42`) to **View chain**
  (sequence, action, actor, time, signature algorithm), **Verify** (re-checks chain
  links, hashes, signatures, timestamps), or **Export bundle** (an
  offline-verifiable file).
- **Anchor Merkle root.** Paste a Merkle root to anchor via the configured provider.

> **Privacy warning shown in-app:** anchoring to a public blockchain publishes a
> hash permanently and reveals your IP/timing to the calendar operators. Prefer
> local + OpenTimestamps over funded on-chain wallets; route via Tor (`HTTPS_PROXY`)
> if you need anonymity; or stay local-only (the default leaks nothing).

Verify a bundle anywhere, without this app:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
python scripts/verify_evidence.py bundle.json [signer_pubkey]
```

The full design — and exactly what each mechanism does and does **not** prove — is
in [`docs/CHAIN_OF_CUSTODY.md`](CHAIN_OF_CUSTODY.md). *(A planned overhaul to make
this tab dummy-proof and largely automatic is captured in
[`docs/OPEN_QUESTIONS.md`](OPEN_QUESTIONS.md).)*

### 3.9 Settings

**What it's for:** preferences and maintenance. Everything is stored locally; no
telemetry.

- **Preferences:** **Theme** (System/Dark/Light) and **Default search results**.
- **Keyword filtering:** "dumb" function words (the, you, not, …) are removed by a
  built-in multilingual stoplist. Tune it: set **minimum keyword length**, **drop
  purely numeric terms**, toggle the built-in stoplist, and maintain an **excluded
  keywords** list (one per line or comma-separated). Excluding hides a term
  everywhere but is reversible — stored mentions are kept. (You can also click ✕
  beside any keyword in Insights.)
- **Wikipedia offline baselines:** pick a **language edition** — the picker is
  **grouped by continent** (Europe, Asia, Africa, …), largest editions first within
  each, and you can type any edition code that isn't listed — then **Estimate size**
  (reads the *exact* current dump size from the server; nothing guessed) and
  **Download** (resumable, with pause/resume and a progress table). These offline
  dumps are heavy and optional, and are only for offline reading/search — live
  change-tracking (the Wikipedia tab) doesn't need them.
- **Backup & restore:** **Download backup (.db)** takes a consistent live snapshot
  via SQLite's online-backup API. **Restore** *replaces* your corpus with an
  uploaded file — but only after validating it's a genuine Open Omniscience
  database, and after snapshotting your current corpus to a `pre-restore-*.db`
  beside the database, so the operation is reversible.

---

## 4. Common workflows (how-to)

**Gather news on a topic and search it**
1. **Sources** → confirm relevant sources are enabled (filter by country/tag).
2. **Ingest** → either click **Fetch feed** per source, or set the **scheduler** to
   RSS mode with your **Tags/keywords** and **Start**.
3. **Search** → Boolean query → **Export CSV/JSON** if needed.

**Continuously monitor a beat in the background**
1. **Ingest** → scheduler **Mode: RSS feeds**, set **Languages**/**Tags**, **Preview
   targets**, set an **Interval**, tick **Start automatically on launch**, **Save**.
2. Optionally enable **Chain of custody → Auto-log on ingest** so each capture is
   signed as it lands.

**Produce court-/editor-defensible proof of an article**
1. **Search** for the article(s).
2. **Export signed evidence** (or **Chain of custody → Export bundle** for an item).
3. Hand the recipient the bundle and `scripts/verify_evidence.py` /
   `verify_custody.py`; they verify offline, without trusting you or this tool.
4. For independent *time* proof, enable **OpenTimestamps** and anchor the bundle's
   Merkle root (mind the privacy warning).

**Watch a contested Wikipedia article for tampering**
1. **Wikipedia** → add the page (edition + title), tick **use ORES**, **Track now**.
2. Review **Flagged changes**; open **Diff** on anything suspicious.

**Track a commodity price against news**
1. **Markets** → **Load / refresh market data** (curated feeds), or add a
   **price-extraction rule** and **Test** it.
2. Click the series card → read the chart and the **correlation** with a news query.

**Move your corpus to another machine**
1. **Settings → Download backup (.db)**.
2. On the new machine, **Settings → Restore** that file.

---

## 5. Technical reference

### 5.1 Where your data lives

Resolved by `src/paths.py`, in this precedence:

1. **`OO_DATA_DIR`** if set (always wins).
2. **Source checkout** — if running from a writable repo (dev/editable/Qubes
   `$HOME` install), data lives in `<repo>/data/`.
3. **Per-user** — otherwise XDG: `$XDG_DATA_HOME/open-omniscience` or
   `~/.local/share/open-omniscience`.

In that directory you'll find: `open_omniscience.db` (the corpus, SQLite/WAL),
`app_settings.json` (theme, result limit), `custody_settings.json` (custody
preferences), custody keys, downloaded Wikipedia dumps, and any `pre-restore-*.db`
snapshots.

### 5.2 Environment variables

| Variable | Purpose |
|---|---|
| `OO_DATA_DIR` | Override the data directory (see above). |
| `OO_HOST` / `OO_PORT` | Bind address/port (default `127.0.0.1:8000`). |
| `OO_AUTOSEED` | Seed the worldwide catalog on first run (default on; `0` to disable). |
| `OO_NO_SCHEDULER` | Set `1` to never autostart the background scheduler. |
| `OO_NO_INDEX` | Set `1` to skip automatic Insights indexing. |
| `OO_CUSTODY_ON_INGEST` | Legacy default for auto-logging custody on ingest (the UI preference overrides it once saved). |
| `OO_KEY_PASSPHRASE` | Encrypt custody private keys at rest (AES-256-GCM via scrypt). Without it, keys are written `0600` in the clear and reported honestly as `plaintext-0600`. |
| `OO_FETCH_TIMEOUT` / `OO_FETCH_MIN_INTERVAL` | Tune the ethical fetcher's timeout and per-host minimum interval. |
| `OO_LLM_MODEL` / `OO_OLLAMA_URL` (or `OLLAMA_BASE_URL`) | Default local model and Ollama endpoint. |
| `HTTPS_PROXY` | Route outbound traffic (e.g. OpenTimestamps) through a proxy/Tor. |

### 5.3 Optional extras

Install with `pip install -e ".[extra]"`:

- **`analysis`** — statistics, keyword/entity analytics, market correlation.
- **`nlp`** — spaCy models for real named-entity recognition in Insights.
- **`pqc`** — post-quantum ML-DSA signing for Chain of custody.
- **`timestamping`** — OpenTimestamps (Bitcoin) anchoring.
- **`dev`** — test/lint tooling.

If an extra is missing, the dependent feature **degrades loudly** (a clear error or
a `503`, an honest "not installed" status) — it never silently fakes the capability.

### 5.4 The HTTP API

The app is a FastAPI server on `127.0.0.1:8000`; the web UI is a single
dependency-free `index.html` served at `/`. Interactive docs live at **`/docs`**;
Prometheus metrics at `/metrics`. There is **no authentication** by design
(loopback-only, single user). All endpoints are **rate-limited** (roughly: reads
100/hr, writes/exports 50/hr, deletes 20/hr, bulk imports 10/hr; `429` with
`Retry-After` when exceeded).

A condensed inventory (see `/docs` for the authoritative, always-current schema and
`docs/API_DOCUMENTATION.md` for prose):

**Core & search** — `GET /api/health`; `GET /api/articles` (FTS + filters);
`GET /api/articles/export` (csv|json); `GET /api/articles/{id}/view` (offline HTML);
`GET /api/sources`.

**Ingestion** — `POST /api/sources/seed-defaults`;
`POST /api/sources/{id}/ingest`; `POST /api/sources/{id}/ingest-email` (IMAP);
`POST /api/ingest` (single URL).

**Sources & catalog** — full CRUD under `/api/sources/…` (incl. batch ops, groups,
tag-based groups, metadata, discovery, YAML import/export, stats, search); CSV
catalog at `/api/catalog/sources`, `/export.csv`, `/template.csv`, `POST /import`.

**Scheduler** — `GET /api/scheduler/status|config|targets`;
`PUT /api/scheduler/config`; `POST /api/scheduler/start|stop|run-now`.

**Database** — `GET /api/database/stats|coverage|countries`;
`GET /api/database/backup`; `POST /api/database/restore`.

**Insights** — `GET/PUT /api/insights/filter`; `POST /api/insights/exclude|include`;
`GET /api/insights/status`; `POST /api/insights/reindex`;
`GET /api/insights/top|trending|trend|associations|context|map`.
**Framing** — `GET /api/framing`.

**Markets & commodities** — `/api/markets/rules` (CRUD + `/run`),
`/api/markets/overview|series|feeds`, `/api/markets/feeds/{key}/import`,
`/import-all`, `/import-url`; `/api/commodities/{symbol}/prices` (+ `/import-csv`,
`/correlation`).

**Wikipedia** — `GET /api/wiki/status|pages|changes`; `POST /api/wiki/pages`,
`/track-now`, `/pages/{id}/track`; `GET /api/wiki/revisions/{id}`;
`GET /api/wiki/languages` (now returns both a flat list **and** continent-grouped
`groups`); dumps under `/api/wiki/dumps…`.

**Chain of custody** — `POST /api/custody/log`; `GET /api/custody/{item}` (+
`/verify`); `POST /api/custody/verify`; `GET /api/custody/export`;
`GET /api/custody/providers`; `POST /api/custody/anchor`;
`GET/PUT /api/custody/settings`. **Evidence** — `POST /api/reports/evidence`
(+ `/verify`).

**LLM (local Ollama)** — `GET /api/llm/health|models`; `POST /api/llm/generate`;
`POST /api/llm/articles/{id}/summarize|translate`.

**Other** — `/api/analysis/*` (t-tests, correlation, ANOVA, …);
`/api/keywords/*` (extraction utilities); `/api/monitoring/health|anomalies`;
`POST /api/verify/image-metadata` (EXIF/GPS).

---

## 6. Troubleshooting

- **The page won't load.** Confirm the process is running and bound to
  `127.0.0.1:8000` (or your `OO_HOST`/`OO_PORT`). The header health pill turns
  `offline` if the API isn't reachable.
- **Search is empty.** You haven't ingested yet — use the welcome banner's one-click
  first run, or **Ingest → Fetch feed**.
- **An ingest stored nothing.** That's often correct and ethical: the page may be
  blocked by `robots.txt` (fail-closed), rate-limited, a duplicate, or have no
  extractable body. The result tally tells you which.
- **Insights/Markets controls are missing or erroring.** The `[analysis]` extra
  isn't installed — re-run `install.sh` and enable Analysis tools.
- **LLM pill says offline.** Ollama isn't running/reachable; start it or set
  `OLLAMA_BASE_URL`. Summarise/translate return a clear `503` when unavailable.
- **Custody shows "requested, library not installed".** Install the `pqc` and/or
  `timestamping` extra; the effective state will flip once the library is present.
- **Restore refused my file.** By design — it must be a genuine Open Omniscience
  SQLite database. Your current corpus is untouched.
- **Wikipedia dump is huge.** `enwiki` is tens of GB. Use **Estimate size** first;
  most editions are far smaller, and you don't need a dump for change-tracking.

---

## 7. Glossary

- **Corpus** — your local SQLite database of gathered articles.
- **Provenance** — the stored origin of each item (source, URL, canonical URL,
  content hash, fetch time) used for dedup and trust.
- **FTS5** — SQLite's full-text search, powering Boolean queries.
- **Ethical fetch** — the single, robots-respecting, rate-limited fetch path.
- **Chain of custody** — append-only, hash-chained, signed log proving an item's
  integrity, provenance and time.
- **Evidence bundle** — a signed, Merkle-rooted, offline-verifiable export of
  selected articles.
- **OpenTimestamps** — a way to anchor a hash into Bitcoin as independent proof of
  "existed no later than" a block.
- **ML-DSA** — FIPS-204 post-quantum signature scheme (used in *hybrid* mode
  alongside Ed25519).
- **ORES** — Wikimedia's ML service scoring edits for damage / good faith.
- **PMI** — pointwise mutual information; ranks how strongly two terms co-occur
  beyond chance (the Insights "mind-map").
- **VADER** — a lexicon-based tone/sentiment scorer (the Insights "framing" view).

---

*See also:* [QUICKSTART](QUICKSTART.md) · [CHAIN_OF_CUSTODY](CHAIN_OF_CUSTODY.md) ·
[INSIGHTS](INSIGHTS.md) · [MARKETS](MARKETS.md) · [WIKIPEDIA](WIKIPEDIA.md) ·
[DATABASE](DATABASE.md) · [API_DOCUMENTATION](API_DOCUMENTATION.md) ·
[SECURITY](SECURITY.md) · [PRODUCT_SYNTHESIS](PRODUCT_SYNTHESIS.md) ·
[OPEN_QUESTIONS](OPEN_QUESTIONS.md).

*© 2026 Ideotion — built for investigative journalism, honestly. GPLv3.*
