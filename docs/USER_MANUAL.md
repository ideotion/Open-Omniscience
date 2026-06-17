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
  features that faked scores were removed — see `docs/HISTORY.md`.)
- **Ethical ingestion.** One fetch path. `robots.txt` is respected **fail-closed**
  (if in doubt, it does *not* fetch), every host is rate-limited, and nothing is
  stored unless a real article body was extracted.

---

## Table of contents

1. [Install & first run](#1-install--first-run)
2. [The 60-second tour](#2-the-60-second-tour)
3. [The tools, one by one](#3-the-tools-one-by-one)
   - [Home](#30-home) · [Activity & Task manager](#30a-activity--the-task-manager) ·
     [Search](#31-search) · [Collect](#32-collect) ·
     [Sources](#33-sources) · [Library](#34-library) · [Markets](#35-markets) ·
     [Indices](#35a-indices) · [Insights](#36-insights) ·
     [Temporal map](#36a-temporal-map) · [Agenda](#36b-agenda) ·
     [Wikipedia](#37-wikipedia) ·
     [Evidence & custody](#38-evidence--custody) · [Settings](#39-settings) ·
     [Help & docs](#310-help--docs)
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

On first launch the app **auto-seeds a worldwide catalog (~3,180 unique domains
across news, markets, the political-spectrum set and official law/IP portals)** so you
have something to ingest immediately, initialises the SQLite database and FTS
index, and (if enabled) starts the background scheduler.

### The passphrase screen (new corpora are encrypted)

New databases are **SQLCipher-encrypted on disk by default**, so the very first
thing you may see is an **unlock screen** at `/unlock`: pick **THE passphrase** for a
brand-new corpus (or type the one you set). This is one stable secret with **no
recovery** — full rationale and the honest threat model are under
[Settings → Safety](#39-settings). Headless/scripted runs supply it with
`OO_DB_PASSPHRASE`; plaintext operation stays an explicit choice (`OO_DB_PLAINTEXT=1`).
The unlock page is self-contained and offline.

### The first-launch guide & the Home screen

On a fresh install a one-time **guided setup** (a stepped dialog) walks you through
your first choices: it opens on a **Language** step (pick from the 12 interface
languages — the whole UI switches live) and ends on a **Finish** step that states the
app **boots offline** and offers a *"Go online & start collecting"* button. Going
online always passes the network-consent popup (below) — the guide only invites you;
it never connects on its own. *(An encryption-choice step and a sources-by-theme step
are marked "Coming soon" in this build.)* You can re-run the guide any time from
**Settings**.

After that, the app opens on **Home**, which leads with your **Briefing** — a feed of
honest "cards" (see [3.0 Home](#30-home)) — above a compact **at-a-glance** strip of
live counts. When the corpus is empty a **welcome card** offers a single button to
seed the curated catalog and run a first pass, after which **Search** has real
articles in it.

**The shell.** Navigation lives in a **left sidebar**, grouped by what you're trying
to do — *Investigate · Collect · Trust · System* (it collapses to an icon rail on
narrow windows but never disappears). A **minimal top bar** above the content carries:

- **The search / command bar (⌘K / Ctrl-K).** Type to jump to any tool, run a common
  action, open any document — or federated-search your data (see [3.1 Search](#31-search)).
- **Live status** — a backend health dot and an **LLM** pill.
- **Task manager** — a button that opens the [task-manager window](#30a-activity--the-task-manager).
- **Airplane mode** — the one network on/off switch (a plane glyph whose *fill* is the
  state; filled = offline). On first launch, while offline, a small coachmark points at
  it and invites you to go online when ready.
- **Language switcher** — all 12 languages in one menu (the flag is only a cue; the
  native name is the identifier). One click re-translates the whole UI.
- **Help (?)** — opens the in-app documentation reader (this manual and the other
  guides), searchable and fully offline; the raw API page is at `/docs`.
- **Settings (gear)** — preferences and the acquisition surfaces; see
  [3.9 Settings](#39-settings). *(Settings is reached from the top bar, not the sidebar.)*

**Appearance** (**Settings → Appearance**) offers **17 colour themes + System**,
accent, density, text size, a bundled-typeface picker, sidebar collapse, and which
tools appear. Everything is stored locally; nothing is transmitted.

### Recent additions (0.0.8 live-test cycle, June 2026)

- **The network switch is an airplane-mode toggle (top bar):** one constant
  airplane glyph whose **fill is the state** — filled means offline engaged
  (every new network request refused instantly; one in-flight request may
  finish). **Every transition back to online asks first**: a single consent
  popup says which action needs the network and lists your machine's **local
  interface addresses** (read from the kernel's own tables — never a network
  call; the app deliberately does not fetch a "what is my IP" echo, because
  that would itself be traffic). Beyond those local addresses, the internet
  sees whatever public address your ISP or VPN presents. Starting a collection
  pass, importing market feeds, adding a watched Wikipedia page or downloading
  a dump all pass through the same consent when offline, and the toggle
  repaints immediately on every transition — it never waits for the next poll.
- **Layered mind-map & word cloud (Insights):** a true radial mind-map (centre →
  arms → outward leaves) across three zoom layers (keywords ↔ families ↔
  super-groups), with a word-cloud second view, a date-spectrum control, a
  text-size slider and ⛶ Enlarge. Font size always encodes shared-article volume.
- **Pre-created super-groups:** a bundled starter set (drafted from real field
  logs) seeds at startup; your own edits and deletions always win.
- **Temporal map controls:** precise focus-date entry, a from/to time-span that
  remaps the slider (play then sweeps only that period), play speed 0.5–4×,
  fine ±month windows, wheel zoom, in-map controls and ⛶ Enlarge. Pins are
  clickable across their whole disc.
- **Event dates, places, people and organizations extracted from text:** the
  date extractor reads six languages, numeric formats and anchored expressions
  ("yesterday", bare weekdays, "June 11"); the location extractor finds
  gazetteer cities and country names; the entity extractor surfaces **people**
  and **organizations** as two deliberately separate classes (an honorific-led
  name and a repeated acronym answer different questions — each entry records
  which rule found it). All feed the article reader's metadata header, which
  separates **"From the source"** from **"Deduced by this app — less reliable"**
  (dashed box): extractions are lexical candidates with snippet provenance,
  never confirmed facts.
- **Per-language keyword exports:** the diagnostics keyword log caps at 5,000
  keywords *per dominant language*, so minority-language vocabularies are never
  crowded out of analysis by English volume.
- **Wikipedia offline dumps:** the editions list loads correctly again and is
  multi-selectable — download several language editions in one queued run.
- **17 themes and bundled open-source fonts:** nine new colorways (Arctic,
  Solar, Forest, Aubergine, Garnet, Cyber, Mist, Dawn, Mint) join the original
  set, and six SIL-OFL typefaces now ship **inside the app** (Cantarell, Inter,
  Outfit, Manrope, JetBrains Mono, Source Serif 4 — see
  `src/static/fonts/README.md`): nothing to download, no font request ever
  leaves your machine. Some themes pair with a font (Arctic→Inter,
  Cyber→Outfit, Sepia/Paper→Source Serif); the new **Typeface** picker in
  Settings → Appearance overrides any of them, and the article reader uses the
  bundled serif. Form widgets (sliders, checkboxes, native dropdowns) now
  follow the theme too.

**A note on “FOOS”.** Browser tabs the app opens (card investigations, the
local article reader) are suffixed **“· FOOS” — Free Open OmniScience**: short
enough for narrow tab strips while keeping the app identifiable. It is the
alpha working name; a proper rename may come later.

**One icon, one interface.** The installer creates **one launcher** — **Open
Omniscience** → `http://127.0.0.1:8000/` — a discoverable, customizable sidebar
app that adapts smoothly to your window size (the sidebar retracts to an icon
rail on narrower windows). An experimental second interface ("Desk") existed
during earlier cycles and was retired in 0.0.8; its history is in
[`DESIGN.md`](DESIGN.md).

---

## 2. The 60-second tour

The core loop is:

> **Pick/add a source → Collect → Search → (analyse) → Export / sign.**

1. **Settings → Sources** — a worldwide catalog is already seeded; add your own if you like.
2. **Settings → Collect** — fetch a source's RSS feed or paste a single article URL.
   Or let the **scheduler** do it automatically on an interval.
3. **Search** — Boolean full-text search across everything you've gathered.
4. **Analysis / Insights / Temporal map / Commodities / Indices** — optional analysis
   layers on top of the corpus (the corpora window, patterns, space-time, prices).
5. **Export** — CSV/JSON, or a **signed evidence bundle** anyone can verify
   offline.

Pick any tool from the sidebar, or just press **⌘K / Ctrl-K** and type where you
want to go. The active view refreshes itself live (every few seconds) while it's on
screen, and actions confirm with small toast notifications in the corner.
Destructive actions always ask first.

---

## 3. The tools, one by one

The sidebar groups the tools by intent:

- **Investigate** — Home · Search · Analysis · Insights · Temporal map · World law ·
  Agenda · Indices · Commodities *(advanced)*
- **Collect** — Library
- **Trust** — Evidence & custody · Source integrity
- **System** — Help & docs

**Content-first (0.0.9).** The sidebar shows the *data*; the acquisition surfaces
moved into **Settings**: **Collect** (the scheduler + manual ingest), **Sources** (the
catalog) and **Wikipedia** (change-tracking + offline dumps) are now Settings sections,
documented in their own subsections below. **Settings** itself opens from the **top-bar
gear**, not the sidebar.

A few names changed to be plainer (the controls are the same): **Ingest → Collect**,
**Database → Library**, **Chain of custody → Evidence & custody**, **Markets →
Commodities** (with **Indices** split out). You can hide tools you don't use
(Settings → Appearance → "Tools shown"), and jump to any tool with the command palette
(Ctrl/⌘-K).

### 3.0 Home

**What it's for:** your **briefing** — a triage feed plus orientation.

- **Briefing (the feed):** the app gathers and measures in the background, then
  surfaces candidate stories as **cards** grouped into editorial buckets (*rising,
  overtold, undertold, investigate, check-the-framing, watch, context, data
  integrity*). Each card is **one measured signal + evidence links + a caveat** — never
  a verdict, and there is **no "trust score"** (forbidden in code). Toggle **Show
  method & caveat** to see exactly how every figure was computed and what it does not
  mean. **+ Add to draft** pins a card; **Dismiss** hides it (reversible). The feed is
  cached (instant) and refreshes after each scrape — or hit **Refresh**. Full details:
  [USER_MANUAL.md](USER_MANUAL.md).
- **Newsletter draft:** pinned cards + your notes, exported as **Markdown** in which
  every claim already carries its source links, method and caveat — reproducible
  journalism. For a signed copy of the underlying articles, use Evidence & custody.
- **Content-first layout:** a compact **at-a-glance** strip is pinned at the top (live
  counts + whether automatic collection is running), and the cards below can be filtered
  by **family** via vertical subtabs (an **"All cards"** default lens, plus one tab per
  bucket with its own hue). When the corpus is empty a **welcome card** offers the
  one-click first-run seeding. *(The old hero greeting and the "Quick actions" row were
  removed — Home opens straight on the Briefing.)*

### 3.0a Activity & the Task manager

**What it's for:** seeing — and steering — everything the app is doing in the
background, from any tab.

- An **activity chip** in the top bar lights up while work runs (a collect pass, a
  Wikipedia dump, a market import); a persistent **task-manager** button sits beside it
  (it stays reachable even when the app is idle).
- Open the **Task manager** — a proper window (not a popover) with four subtabs:
  - **Active** — every running job: the collect pass, each downloading Wikipedia dump,
    the in-flight fetch (shown as a DOMAIN only), the idle loop, and any paused/failed
    download. Each job shows its real progress and the controls that apply — **Stop** a
    collect pass (this also engages the network kill switch, so you go offline; the
    button says so) and **Pause/Cancel** a dump. No fabricated ETA or rate — only the
    real byte progress the owner reports.
  - **Queue** — jobs waiting their turn: the single-download Wikipedia-dump queue in
    order, with **↑ / ↓** controls to reorder it (pull a small French dump ahead of a
    huge English one).
  - **Schedule** — the real scheduler facts: state (running / idle / stopped),
    current-pass progress (domain only), cadence, last run, and the backend's own
    next-run time shown as honest relative time (the method is in the hover bubble —
    never a fabricated countdown).
  - **System** — live process vitals (CPU, RAM, download rate). *(Vitals moved here out
    of the top bar.)*
- The window reads **live from the systems that own the work**, so it can never
  disagree with what is actually happening — no shadow state.

### 3.1 Search

**What it's for:** finding articles in your corpus.

- **Boolean query** — supports `AND` / `OR` / `NOT`, `"exact phrases"`, and
  parentheses with correct precedence, e.g.
  `(climate OR energy) AND policy NOT opinion`. Backed by SQLite FTS5 and fully
  parameterised (no injection).
- **Filters:** Source (exact name), Language (code like `en`), and a **time-range**
  control — From/To date fields, a draggable range bar, and quick presets
  (1M · 6M · 1Y · 5Y · All) — the *same* control used on Markets, Insights and the
  Analysis window. Left at its full span it excludes nothing; narrow it to scope the
  search to a period. All optional.
- **Search** runs the query; the results table shows **Title · Source · Published ·
  Language**, and a count (`N result(s)`, and how many are shown if truncated).
- **Per-row actions:** **open** (a clean offline copy of the stored article),
  **source ↗** (the original URL), **Summarize** and **Translate** (local LLM, if
  Ollama is available).
- **Exports:** **Export CSV**, **Export JSON**, and **Export signed evidence** — a
  tamper-evident, signed bundle of exactly the articles matching your query (see
  [Evidence & custody](#38-evidence--custody)).

**The omnibar (Ctrl/⌘-K), from anywhere:** the command palette is also a
federated search over your data. From two typed characters it shows the first
three hits per group — **articles** (full Boolean FTS), **keywords** (each opens
its corpus window), **sources**, **watched Wikipedia pages** and **tracked law
documents** — with the *true total* behind each group stated in its header.
Everything is index-backed and searched on this machine only; a half-typed
query is never an error. Choosing *"Run the full Boolean search"* lands you in
this tab with the query prefilled, so every capability above stays one step
away.

### 3.1a Analysis — the corpora window

**What it's for:** turning a *set* of articles, or a single keyword, into an analysis
object you can read from several angles. A keyword is a corpus; a single article is a
corpus of one. The same window opens from several places — clicking a keyword (e.g. in
Insights or the omnibar opens its **⊞ Corpus** window) and the **Analysis** sidebar tab.

The window is a tabbed dialog with a title and the **article count** it was computed
over, and these subtabs (this build):

- **Trend** — the mention/volume trend over time, drawn with the shared interactive
  chart toolkit (zoom by wheel, drag to pan, hover for an exact readout; full-resolution
  within the window, with sparse stretches shown honestly as points + an early-corpus
  caveat rather than a faked curve).
- **Articles** — the member articles, each opening in the offline reader.
- **Links** — which member articles **share outbound links**. This surfaces
  *shared-origin structure* on purpose: three articles citing one origin are one source
  wearing three hats, so convergence counts as corroboration only when the paths are
  independent (links carry an independence note). The goal is the *sources' sources*.

> **Honest status.** This is the first slice of the planned flagship "corpora system."
> The richer subtabs the project intends — mindmap, source/competitive analysis,
> sentiment, When×Where×Who, and an Advanced-search tab on the Enter→window path — and a
> shared time-scope (begin/end/timescale) control are **not yet built here**; see
> [`docs/ROADMAP.md`](ROADMAP.md). What ships today is exactly the three subtabs above.

### 3.2 Collect *(in Settings → Collect)*

> **Where it lives now.** Collection is an acquisition surface, so it moved out of the
> sidebar into **Settings → Collect** (content-first). The controls are unchanged.

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

### 3.3 Sources *(in Settings → Sources)*

> **Where it lives now.** Like Collect, the source catalog moved into **Settings →
> Sources** (content-first). The controls are unchanged.

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

### 3.4 Library

*(Called **Database** before 0.05.)*

**What it's for:** an honest look at what you actually hold, and how widely your
sources reach.

- **Database stats:** live, animated counts (articles, sources, unique domains,
  …), plus the backend and the **on-disk size and path** of the database. Every
  figure is a real count or byte size — nothing estimated.
- **World coverage:** how many countries your source catalog reaches, scored
  against ISO 3166 — `covered/total countries`, `coverage %`, count *not* covered,
  and count "thin" (below threshold). Countries are stored as lowercase ISO-2
  codes and **displayed by their full names** (one conversion layer,
  `src/catalog/countries.py`). A **Regional balance** block compares each
  continent's sources and covered countries against the working floors in
  `configs/catalog_targets.yml` (clearly labelled aspirations, drafted from the
  real catalog shape), plus a top-country **concentration guard** — the 0.0.9
  de-US-centring metric. The table lists each country with its region, source
  count and **topic-keyword pills** (from source tags). **Click a country or a
  keyword** to jump to Sources filtered to exactly those sources. A gap report
  names the countries with no source yet. The panel refreshes live (no Refresh
  button needed); the same metric is available offline via
  `python scripts/catalog_coverage_report.py`.

### 3.5 Markets

**What it's for:** tracking **real** commodity / currency / energy prices and
relating them to news volume.

- **Market trends dashboard:** a card per price series — symbol, % change, latest
  price (currency/unit), point count, and a mini sparkline. A **time-range** control
  — From/To date fields, a draggable range bar, and quick presets (1M · 6M · 1Y ·
  5Y · All) — reshapes every card by an exact start/end window (not a fixed list of
  scales); the full series is always drawn at full resolution within it, never
  thinned. Click a card for a full chart plus
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

See [`docs/USER_MANUAL.md`](USER_MANUAL.md) for the full extraction-rule reference.

### 3.5a Indices

**What it's for:** world stock-market **indices** (S&P 500, NASDAQ, Dow Jones,
VIX, Nikkei 225 …) — kept **separate from Commodities**, because an index is an
index, not a commodity.

- A board of index series with the same detailed, full-resolution charts as
  Markets. **Import / refresh** pulls the curated official feeds (FRED and friends).
- Each feed carries an **honest per-feed verdict** when it can't be fetched —
  *refused* ≠ *robots-disallowed* ≠ *dead series* ≠ *unreachable* ≠ *offline* — so
  a blocked feed degrades loudly instead of showing a fake number. Over Tor some
  feeds are blocked by the host; the verdict says exactly that (see §5.5).

### 3.6 Insights

**What it's for:** keyword & entity analytics over the **text of ingested
articles**. *(Requires the `[analysis]` extra; real named-entity recognition is
opt-in via the spaCy `[nlp]` extra.)*

- **Status & indexing:** a pill shows `indexed/total articles · keywords (entities)
  · mentions · remaining`. **Indexing is automatic** — it follows ingest, and when you
  open Insights a silent background top-up clears any leftover backlog (the "remaining"
  count ticks down to 0 on its own). There is **no "Index corpus" button** — it was
  removed in favour of auto-indexing. People, organisations and places are kept as
  single units; indexing is resumable and the bar updates live. *(Disable the automatic
  indexing with `OO_NO_INDEX=1`.)*
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
[`docs/USER_MANUAL.md`](USER_MANUAL.md). To tune which keywords appear, use the
[keyword filter in Settings](#39-settings).

### 3.6a Temporal map

**What it's for:** seeing *where* and *when* together. A journalist's two oldest
questions are location and time; the Temporal map puts every locatable, datable
signal on one zoomable world map under a **time slider** that sweeps from antiquity
to the near future — so you can watch what clustered, where, and when.

- **What it plots:** a curated set of well-documented historical & scheduled
  **anchors** (e.g. Vesuvius 79 CE → upcoming eclipses and Olympics) ships by
  default. Toggle **my corpus** to add your own articles (placed at the source's
  location on its publication date) and **live hazards** to relay open earthquake/
  disaster feeds (USGS/GDACS). Each kind has a colour in the legend; click a legend
  chip to show/hide it.
- **Moving through time:** drag the slider (or click the density strip beneath it)
  to set the moment in focus; **▶ play** sweeps it forward. Events fade with
  distance in time; **future / unconfirmed** ones are drawn as dashed rings. The
  **window** control (± a year up to all of time) decides how much past/future is
  visible at once.
- **Reading the map:** drag to pan, zoom in to reveal labels (semantic zoom). Click
  any pin for its date, place, source, official link, and a **"Find coverage in your
  corpus"** button that runs a search for that place — closing the loop from a point
  in space-time back to what you've gathered.
- **Coastlines (optional):** the map shows an accurate lat/lon graticule out of the
  box; run `python scripts/build_world_outline.py` once (needs network) to add real
  Natural Earth coastlines. Until then, no coastlines are *invented*.

**Dates a story is *about*:** toggle **dates in text** to extract explicit dates
mentioned in your articles (e.g. a 2024 piece on the *1945* bombing) and plot them at
the source location — drawn as dashed "extracted" pins. These also become **per-article
date tags**: open an article's offline reader to see them listed, **confirm or reject**
each candidate, or **extract** on demand; the corpus can then be filtered by a mentioned
date (`GET /api/article-dates/by-date`). High-precision only — bare years and relative
phrases ("last week") are deliberately not extracted.

**Places your corpus *mentions*:** toggle **📍 places** to plot the locations your
articles *talk about* (not where they were published) — drawn from the When/Where/Who
extracted at ingest and placed at a gazetteer coordinate. Each marker's **area scales
with how many articles mention that place** (raw article spread — never a score);
click one for its name, article spread, total mentions and the **"Deduced from text,
never confirmed."** caveat (the same caveat rides in the layer's legend). Places with
no known coordinate aren't drawn — their count is stated honestly ("N places not
mapped"), never dropped onto (0, 0). The layer is **off by default** (the curated
anchors stay primary; you opt in).

**Honesty by construction:** a pin needs **both** a coordinate and a date — anything
missing one is simply absent, never dropped onto (0, 0), and the caveat says so.
Country-level pins are flagged **approximate** (a stand-in point, not the exact
spot); corpus pins mark **coverage origin on the publication date**, not the event
site; scholarly date doubt (e.g. Pompeii's exact day) rides along in the pin's note.

### 3.6b Agenda

**What it's for:** a calendar of dated events — what's coming, sourced and honest.

- A **month grid** (Monday-start; month/day names in your UI language) is the
  default view, with a **List** view alongside. Days with events are marked; click
  a day for the details.
- **Astronomy, computed locally:** full/new moons and the equinoxes/solstices are
  computed on this machine (Meeus' algorithms, verified against published almanac
  values); each entry states its **method and accuracy** in the hover bubble.
  Seasons are named **hemisphere-honestly** — never a bare "summer".
- **Climate context:** a bundled El Niño / La Niña episode dataset (NOAA CPC ONI
  convention); any entry still awaiting a clearnet cross-check carries a
  verification-pending flag.
- **Movable dates are marked as such** — the app never invents an exact day for an
  event whose date shifts each year.
- **Calendars & feeds** (holiday / religious / astronomy iCal sources) are managed
  in **Settings → Agenda**, not here — the tab shows the data, the plumbing lives
  in Settings; subscriptions stay **off by default** so the grid is never flooded.

### 3.7 Wikipedia *(in Settings → Wikipedia)*

> **Where it lives now.** Wikipedia change-tracking and the offline-dump tools moved
> into **Settings → Wikipedia** (content-first); the watched pages still surface in
> general search and analysis like any article. The controls are unchanged.

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

**Watched pages are corpus articles (the living-source choices, stated):**
every page you watch also joins your corpus as an article under a per-edition
source ("Wikipedia (en)"), so it appears in **general search, keywords and
When×Where×Who like any other article**. The choices the app makes for you,
visibly: (1) what search and analytics see is always the **newest version**
the tracker has fetched, and the exact revision id it corresponds to is
recorded; (2) the **full text of every tracked revision is stored on this
machine** — past versions stay exactly reconstructable (version-anchored
analytics, no diff replay), at the honest cost of storage growing with edit
activity; (3) the analyzed text is wikitext reduced to plain text — never
passed off as the rendered article. Everything stays local; the change
history remains available per page, and a dedicated tracked-changes view is
the named next step.

Heavy **offline full-text baselines** (whole-edition dumps) are *separate* and live
in **Settings → Wikipedia** — you don't need them for change-tracking. See
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

**Reading a downloaded dump (offline):** new dump downloads use the
*multistream* form, and the small companion index downloads with them — that
pair makes the dump seekable. In **Settings → Wikipedia → Read a page from a
downloaded dump**, pick a ready edition, type a page title, and the app scans
the index, decompresses one small block at its byte offset, and shows the
page's **raw wikitext** — entirely on this machine, with the scan stats shown.
What you read is a *snapshot as of the dump date*, not the live article; a
case-insensitive title match is offered and labelled. Older single-stream
files can't be random-accessed — the app says so and suggests a re-download.
The dump **language list is limited to the app's languages** (the 12 interface
languages plus the corpus languages the analyzers support); the watched-pages
edition picker above keeps the full list.

### 3.7a World law

**What it's for:** tracking the **law** — statutes, gazettes, IP records — from official
sources worldwide, and watching how it changes over time. Like Wikipedia tracking, the
*changes are the data*. A **research mirror**, never the authoritative source and **not
legal advice** — every record links back to its official gazette. Full guide:
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

- A **worldwide catalog of real official sources** (national legislation databases,
  gazettes, IP offices — `legislation.gov.uk`, EUR-Lex, Légifrance, govinfo, WIPO Lex,
  USPTO, EPO, …) is **seeded by default**; they ingest and search like any other source.
- **Track changes now** fetches the curated tracked documents through the ethical
  fetcher, storing a baseline then honest **diffs** with a large-change flag.
- **Flagged legal changes** lists changes (jurisdiction · title · Δ bytes · reasons) with
  the diff and a link to the official source. The briefing also surfaces a
  **model-legislation** card when near-identical text appears across jurisdictions.

### 3.8 Evidence & custody

*(The sidebar calls this **Evidence & custody**; the panel heading still reads
**Chain of custody** — same feature.)*

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
in [`docs/USER_MANUAL.md`](USER_MANUAL.md). *(A planned overhaul to make
this tab dummy-proof and largely automatic is captured in
[`docs/ROADMAP.md`](ROADMAP.md).)*

### 3.8a Source integrity

**What it's for:** seeing the *structure* behind your sources — and deciding, yourself,
whose signal counts. There is deliberately **no trust score**; a single number would
bake in bias and silence small, foreign, new or dissident sources. Full guide:
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

- **Anti-amplification (propose → you dispose):** *Scan for coordination* finds
  near-duplicate floods published in lockstep across many sources, with their evidence
  (shared text, timing, host). By default they are only **annotated** — never silently
  collapsed. **Apply collapse** to count a network as **one voice** (in any count that
  measures consensus); it stays flagged, **Expand (revert)** restores the raw equal view
  exactly. Nothing is ever collapsed without your action. Echo-chamber cards on Home
  carry the same action.
- **Source profile:** a panel of measured dimensions — coordination, novelty
  (originates vs echoes), output capacity, transparency facts, track record — each with
  its method and caveat, and **no composite score**.
- **Shared annotations (web of trust):** author descriptive, contestable facts about
  sources (ownership, leaning, coordination, corrections); **export** them as a
  **signed** bundle; **import** the bundles you choose to trust. *Who said what?* shows
  every attribution for a source and surfaces **dissent** — never averaged into a number.
  See [`docs/USER_MANUAL.md`](USER_MANUAL.md).

### 3.9 Settings

**What it's for:** preferences, the acquisition surfaces, and maintenance — organized
into sections via a sub-nav: **Appearance · General · Collect · Sources · Wikipedia ·
Agenda · Models · Statistics · Offline map · Newsletters · Keywords · GUIs · Data &
backup · Safety**. Open Settings from the **top-bar gear** (it is no longer a sidebar
item); the command palette still jumps straight here. Everything is stored locally; no
telemetry. **Collect**, **Sources** and **Wikipedia** are documented above
([3.2](#32-collect-in-settings--collect), [3.3](#33-sources-in-settings--sources),
[3.7](#37-wikipedia-in-settings--wikipedia)); **Agenda** calendars are managed here too.

- **Appearance:** themes, accent colour, density, **text size**, **typeface**, sidebar
  expanded/collapsed, and **which tools show** in the sidebar. (This is the former
  floating "Customize" drawer, now a first-class Settings section — the standalone
  Customize buttons were removed to free up the chrome.)
- **Preferences (General):** **Theme** (System/Dark/Light), **language**, and **Default
  search results**.
- **Keyword filtering:** "dumb" function words (the, you, not, …) are removed by a
  built-in multilingual stoplist. Tune it: set **minimum keyword length**, **drop
  purely numeric terms**, toggle the built-in stoplist, and maintain an **excluded
  keywords** list (one per line or comma-separated). Excluding hides a term
  everywhere but is reversible — stored mentions are kept. (You can also click ✕
  beside any keyword in Insights.)
- **Wikipedia offline baselines:** pick a **language edition** from a **flat list**
  (your UI languages first, then the largest editions), each option leading with the
  **native name** (autonym) — editions are language-based, not country-based, so there
  is no continent grouping. Each dump-eligible edition shows an **inline approximate
  size** (`~X GB`, from a bundled dated table — zero extra network) so you can judge
  before downloading; the exact size is read when the download starts. **Download** is
  resumable (pause/resume + a progress table). These offline dumps are heavy and
  optional, and are only for offline reading/search — live change-tracking (the
  Wikipedia tab) doesn't need them.
- **Models (local LLM):** detect a running Ollama, see installed models and a curated
  dated catalog, **pull** a model (live byte progress; the bytes go over clearnet via
  the Ollama process, **not** Tor — stated at the consent prompt), **remove** one, and
  set the **active model** the summarise/translate/synthesise features use. (The
  optional binary-installer is a later addition.)
- **Statistics (official figures):** a descriptive directory of government + international
  statistical producers (each a *stanced* source, flagged controversial — never a
  credibility score); **register** them as disabled sources; and **fetch official figures**
  from documented machine endpoints (World Bank API / Eurostat SDMX), stored with their
  full provenance and a first-class **vintage** (a re-fetch is a new row, never an
  overwrite). Producers are shown **side by side, never averaged**, and a **Triangulate**
  view flags cells that mix incomparable units / seasonal adjustment / base years. The
  fetch egresses over your configured transport and is refused under airplane mode.
- **Offline map:** pick an OpenStreetMap region (with a dated `~GB` estimate) and download
  it as a resumable, pausable task-manager job (gated by the one network-consent popup).
- **Newsletters:** import a folder of `.eml` files as articles — anonymised at ingest
  (recipient identity and tracking links are stripped; nothing is fetched), with a visible
  count of what was removed.
- **Backup & restore (Data & backup):** **Download backup (.db)** takes a consistent
  live snapshot via SQLite's online-backup API; a **signed `oo-backup-2` archive**
  carries the corpus plus custody and settings members under one manifest (per-member
  sha256 + a Merkle root over article hashes, with any exclusions listed). **Restore is
  additive-only** — it **complements** your corpus and **never replaces** it. You first
  see a **preview**: how many records are new, how many are duplicates (skipped
  bit-for-bit), and how many *conflict* — conflicts **keep your local value and report
  both**, never averaged. **Apply** then runs the *same merge code* that produced the
  preview (so the preview cannot lie), on a verified staged copy with an atomic swap and
  a `pre-restore-*.db` snapshot kept beside the database.
  > **The destructive "replace your corpus" restore was removed entirely** (it is
  > unreachable — the old `/api/database/restore` and encrypted-replace endpoints are
  > gone). No flow can overwrite your data; the merge is the only restore. Restoring an
  > **encrypted** backup never silently decrypts your corpus.
- **Temporary field-test instrumentation (0.0.8 live-test cycle).** During this
  cycle the app automatically exercises each network surface once *inside your
  own collect passes* (calendar-feed verification in polite batches, the market
  and index feed imports, one law track, one wiki track) and records every
  outcome verbatim in `data/field_test.jsonl`, included in the debug bundle.
  **Purpose:** recurring self-improvement of the default install's source,
  feed and calendar lists from real verdicts — the maintainer reinstalls,
  clicks through, and shares the bundle with development. **It is temporary**
  and will be removed when the cycle ends. Nothing is ever transmitted by the
  app: logs stay on this machine until *you* download and share them. Opt out
  any time with `OO_FIELD_TEST=0`. Boot remains fully offline either way.
- **Diagnostics log:** **Download keyword log (.json)** exports how the app sees
  your corpus's vocabulary — every gathered keyword with its real counts, the
  computed keyword families, your merge/split corrections and super-groups —
  so you can share it (only if and with whom you choose) to get keyword-grouping
  improvements fitted to your *actual* data. Generated only when you click;
  counts and structures only, never scores.
- **Safety & at-risk use:** tools for journalists working under pressure, each
  labelled with its **honest limit**:
  - **At-rest encryption (default for new corpora).** New databases are
    SQLCipher-4-encrypted on disk: at every start the app asks for **THE
    passphrase** — one stable secret, like a user ID (`OO_DB_PASSPHRASE` for
    scripted/headless runs). **There is no recovery and no decryption
    alternative**: a lost passphrase costs re-collection time, because the
    corpus is rebuilt from the web — it holds nothing personal beyond what was
    scraped and deduced from public sources. Existing plaintext corpora keep
    working untouched; **Settings → Safety → "Encrypt this corpus…"** converts
    one *in place* (explicit consent, full verification before the swap, and a
    deliberate plaintext snapshot kept as your escape hatch — delete it once
    you've unlocked successfully). The **doctor** (`GET /api/system/doctor`,
    and the same panel) attests the *real* state of every store by reading the
    file headers — corpus, custody log, signing keys — never by assumption.
    **The honest limit:** at-rest encryption protects a *seized or copied
    file*. It cannot protect a compromised running session (the key lives in
    memory while the app runs), and it is independent of full-disk encryption
    only if the two passphrases differ. Plaintext operation remains available
    as an explicit choice (`OO_DB_PLAINTEXT=1`) — the app never shows a lock
    screen over a plaintext file, because that would be fabricated security.
    Backups from an encrypted corpus work unchanged: artifact members are
    portable, the encrypted artifact's own envelope protects them at rest,
    and restores preserve your corpus's encryption (verified by tests).
  - **Encrypted backup** — a passphrase-protected snapshot (AES-256-GCM + scrypt).
    A lost or wrong passphrase means the file cannot be opened: there is no recovery.
    To bring an encrypted backup back, use the **additive merge restore** in
    **Data & backup** (above) — it previews, then complements your corpus without ever
    replacing it, and never silently decrypts your live store. *(The old destructive
    encrypted-replace restore was removed.)*
  - **Database maintenance** — *Compact database (VACUUM)* rebuilds the database
    file: it reclaims the space deletions leave behind (shown as “Reclaimable
    space”, a real `PRAGMA freelist_count` reading) and defragments the indexes.
    It takes time proportional to the file size and pauses collection writes
    while it runs; the result reports the real bytes freed and duration. It
    never interprets or removes data.
  - **Network fetch mode** — *Transparent* (default; polite, names the tool in the
    User-Agent) or *Protected* (generic User-Agent routed through a proxy **you** run,
    e.g. Tor). Protected mode **cannot guarantee anonymity** — you must run and trust
    the proxy yourself; it refuses to enable without a proxy URL.
  - **Panic wipe** — irreversibly deletes the corpus, keys and caches on this machine
    (double-confirmed). **Limit:** overwrite-in-place does *not* guarantee
    unrecoverability on SSD/flash — for that, use full-disk encryption (LUKS/Qubes/Tails)
    and destroy the key. There is also a `panic` CLI and an `--ephemeral` run mode
    (RAM-only data, wiped on exit).
  - **Uninstall the app** — removes the app's **virtualenv** and **desktop launchers**,
    then stops the server (type-confirmed). Your **data is kept** (use Panic wipe first to
    destroy it); the app folder is left in place to delete manually. Equivalent to
    `./install.sh --uninstall` or the **“Uninstall Open Omniscience”** desktop icon the
    installer creates next to the two app launchers.

  Governance and the dual-use red lines that bound all of this are in
  [`GOVERNANCE.md`](GOVERNANCE.md) (also in **Help & docs**).

### 3.10 Help & docs

**What it's for:** reading the documentation **inside the app**, offline. A
left-hand list selects a document (this **User Manual** is the default; the others
go deeper on specific subjects), rendered on the right with **find-on-page**. Open
it from the sidebar (**Help & docs**), the **?** in the top bar, or the command
palette ("Open the User Manual"). The raw, interactive API reference stays at
`/docs`.

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

**Move (or merge) your corpus to another machine**
1. **Settings → Data & backup → Download backup**.
2. On the other machine, **Settings → Data & backup → Restore** that file: review the
   **preview** (new / duplicate / conflict), then **Apply**. The restore is additive —
   it complements that machine's corpus and never replaces it, so you can also use it to
   *merge* two corpora.

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
`docs/ARCHITECTURE.md` for prose):

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

**Database & backup** — `GET /api/database/stats|coverage|countries`;
`GET /api/database/backup`. Restore is the **additive merge** under
`/api/backup/v2`: `POST /api/backup/v2`, `POST /api/backup/v2/restore/preview`,
`POST /api/backup/v2/restore/commit`, `GET /api/backup/v2/batches`. *(The destructive
`POST /api/database/restore` and `/api/safety/restore/encrypted` were removed.)*

**System & network** — `GET /api/system/vitals|network|interfaces`;
`POST /api/system/network` (airplane toggle); `GET /api/system/doctor|lock-state`;
`POST /api/system/unlock|create-db|encrypt-db`. **Jobs / task manager** —
`GET /api/jobs`; `POST /api/jobs/dumps/reorder`; `POST /api/jobs/{id}/cancel`.

**Temporal map** — `GET /api/timemap` (space-time signals; `?kinds`, `?start`/`?end`
fractional-year window, `?hazards`, `?articles`, `?mentions`, `?days`); `GET /api/timemap/range`.

**Article date tags** — `GET/POST /api/article-dates/article/{id}` (list / extract);
`POST /api/article-dates/{tag_id}/confirm|reject`; `POST /api/article-dates/index`;
`GET /api/article-dates/by-date`.

**Insights** — `GET/PUT /api/insights/filter`; `POST /api/insights/exclude|include`;
`GET /api/insights/status`; `POST /api/insights/reindex`;
`GET /api/insights/top|trending|trend|associations|context|map`; corpus-wide
**When×Where×Who** rollups at `GET /api/insights/who|where`.
**Framing** — `GET /api/framing`.

**Search (omnibar)** — `GET /api/search/omni` (index-backed federation over articles,
keywords, sources, watched Wikipedia and tracked law).

**Links** — `GET /api/links/shared` (which member articles share outbound links, with
independence notes); `GET /api/links/preview` (local link-preview extraction).

**Agenda events** — `GET /api/events/calendars|feeds|imported`;
`GET /api/events/astronomy` (locally-computed moons + equinoxes/solstices, verified vs
almanac) and `GET /api/events/climate` (bundled El Niño dataset). **Weather context** —
`POST /api/weather/context` (corpus-driven Open-Meteo reanalysis slices, consented).

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

### 5.5 Running over Tor

The app works over Tor (Protected fetch mode → a Tor proxy you run), with an
honestly smaller reach — measured, not guessed (live log 2026-06-12: 32 of 50
default sources imported over Tor in one pass):

- **Per-connection refusals are normal, not fatal.** Some hosts refuse some
  Tor exits: in the same run, 21/28 FRED series imported while others failed.
  That is why feed failures carry a **transport-aware verdict** — *refused*
  ("connection refused/reset — over Tor this is often a single exit's
  refusal; a retry frequently lands a different circuit") is not *robots
  disallows* (the host's stated policy, which we honor and never retry or
  evade), is not *dead series* (HTTP 404 — the catalog entry needs a
  replacement; retrying cannot help), is not *unreachable*. Transient
  failures are retried once automatically; the **Retry failed feeds** button
  re-runs exactly the honestly-retryable ones.
- **A host's Tor block is the host's choice.** We surface it; we never evade
  robots, blocks or CAPTCHAs. Prefer Tor-tolerant official endpoints where
  they exist.
- **Model downloads don't work over Tor** — the offline LLM kit (release
  artifact) is the principled path; inference itself is loopback and
  unaffected.
- **Anonymity remains yours to manage**: Protected mode cannot guarantee
  anonymity — you run and trust the proxy; the app's part is a generic
  User-Agent and routing every fetch through it.

---

## 5.5 Known limits & honest disclosures

Honesty by construction means stating what the tool *cannot* tell you, not only
what it can. These are the standing limits of the methods (audit-07 "disclosure
sweep"). None is a bug; each shapes how to read a result.

- **Keyword/trend counts are lexical, not semantic.** They measure how often
  words appear, not what was meant. Negation ("not a crisis"), quotation,
  sarcasm and irony are counted at face value. Volume is coverage, never
  importance or truth.
- **Sentiment/tone is VADER, an English-lexicon method.** Scores for non-English
  articles are unreliable; the Sentiment and Framing surfaces disclose this and
  show the English-scored share. Tone is a measurable signal, never a verdict
  that an outlet is biased.
- **LLM summaries/translations are model artifacts.** A local model can be
  fluent and wrong. Every generated cell is labelled "verify against the stored
  article"; treat its output as a lead, and check it against the original text
  you collected.
- **The app is text-only.** It analyses article text. Images carry EXIF/metadata
  honesty only (no forensic/deepfake claims); there is no audio or video
  analysis. A claim that lives only in a video or image is outside what the tool
  can see.
- **CJK word segmentation is not implemented.** Keyword extraction relies on
  whitespace tokenisation, so Chinese and Japanese keyword analysis is
  effectively non-functional even though the interface ships in those languages.
  Stoplists exist for 16 languages; the *analytical depth* per language varies,
  and this is the largest current gap.
- **Permissive-host survivorship bias.** Because robots.txt is fail-closed, the
  corpus over-represents sites that *allow* crawling and structurally
  under-represents paywalled or crawl-restrictive journalism. This cannot be
  "fixed" ethically — it is mitigated by preferring official APIs/archives and is
  disclosed here so you read coverage accordingly.
- **Your record begins when you started collecting.** Trends and "rising" signals
  are bounded by your collection window; the tool has no history from before you
  began. Wikipedia dumps and (future) archives extend the past; otherwise read
  early-corpus results with the n-shown caveats.
- **Wikipedia carries its own systemic biases.** Watched/ingested Wikipedia
  imports the well-documented editorial and coverage skews of each edition.
  Per-edition sources (`xx.wikipedia.org`) keep it filterable, and it is
  triangulable like any other source — never an oracle.
- **Catalog selection bias is measured, not hidden.** The source catalog is a
  human-curated, de-US-centring-in-progress set; the **World coverage** view
  shows which countries are and aren't represented so you can see the shape of
  what you are (and aren't) collecting.

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
- **Restore refused my file / the preview won't Apply.** By design — it must be a
  genuine Open Omniscience backup, and **Apply** stays disabled if the staged
  verification fails. Your current corpus is untouched either way; restore only ever
  *adds*, never replaces.
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

*See also:* [QUICKSTART](QUICKSTART.md) · [CHAIN_OF_CUSTODY](USER_MANUAL.md) ·
[INSIGHTS](USER_MANUAL.md) · [MARKETS](USER_MANUAL.md) · [WIKIPEDIA](USER_MANUAL.md) ·
[DATABASE](ARCHITECTURE.md) · [API_DOCUMENTATION](ARCHITECTURE.md) ·
[SECURITY](SECURITY.md) · [PRODUCT_SYNTHESIS](DESIGN.md) ·
[OPEN_QUESTIONS](ROADMAP.md).

*© 2026 Ideotion — built for investigative journalism, honestly. GPLv3.*

---

# Feature deep-dives

Reference depth for each tool, consolidated from the former per-feature guides. The tour in Parts 1–6 above stays the quickest orientation; this part is the detail.

**In this part:**
- [The Home briefing — intelligence as honest "cards"](#the-home-briefing-intelligence-as-honest-cards)
- [Source integrity & anti-amplification](#source-integrity-anti-amplification)
- [Shared source annotations — signed, portable, federated by trust](#shared-source-annotations-signed-portable-federated-by-trust)
- [Insights — keyword & entity analytics](#insights-keyword-entity-analytics)
- [Wikipedia change-tracking](#wikipedia-change-tracking)
- [World law — change-tracking for statutes, gazettes & IP](#world-law-change-tracking-for-statutes-gazettes-ip)
- [Markets: financial, stock-exchange, and commodity/rare-earth intelligence](#markets-financial-stock-exchange-and-commodityrare-earth-intelligence)
- [Chain of Custody](#chain-of-custody)


---

## The Home briefing — intelligence as honest "cards"

> **Status:** `0.06` Phase A (the GUI spine) — shipped and tested. The phased plan
> lives in [`ROADMAP.md` → "0.06 — The Intelligence Layer"](ROADMAP.md); the
> *what & why* in [`ROADMAP.md`](ROADMAP.md).

The **Home** tab is no longer just at-a-glance stats. It is a **triage feed**: the
app gathers and measures in the background, then surfaces *candidate stories* as
**cards**. The app does the gathering; **you judge**. Each card is **one measurable
signal + the evidence links + a caveat**, sorted into an editorial bucket.

A card **surfaces a signal; it never renders a verdict.** There is no "biased", no
"propaganda", no "true/fake", and — by design and *enforced in code* — **no composite
trust score** (see "Honesty guards" below).

---

### What you see

The briefing groups cards into **buckets** (display order):

| Bucket | Means | Editorial use |
|---|---|---|
| **Rising now** | something is moving / new | lead candidates |
| **Overtold** | sources agree too fast / too uniformly | debunk the chorus |
| **Undertold** | something moved but little/nobody covered it | surface the gap |
| **Worth investigating** | sources or data disagree | dig in |
| **Check the framing** | the same event framed in opposing ways | verify the claim |
| **Keep watching** | a change worth an eye (e.g. a reshaped record) | monitor |
| **Context** | background / self-audit / standing facts | contextualise |
| **Data integrity** | hygiene signals about the corpus itself | fix the pipeline |

The triad behind them is the engine: **convergence → overtold**, **divergence →
investigate/debunk**, **absence → undertold**.

Every card shows its **title**, a one-line **summary**, the **measured signal**
(e.g. `growth_ratio = 4.2`, `n=6`), and **evidence links** back into your corpus.
Toggle **"Show method & caveat"** to reveal, on every card, exactly how the figure
was computed and what it does *not* mean. That toggle is the point: **transparency is
the interface.**

> **Equal view.** In this version every source is counted once and **no source is
> de-amplified**. The source-integrity / anti-amplification layer (collapsing
> coordinated floods into single actors, novelty-weighting) is the next phase and is
> **user-guided** — the app will *propose*, you will *dispose*. Until then the
> briefing is, honestly, the raw equal-treatment view.

---

### The card → draft → newsletter loop

The payoff loop is visible from day one:

1. On any card, click **+ Add to draft**.
2. Open the **Newsletter draft** panel; add your own note to each pinned card.
3. **Export Markdown** (or **Copy**). Each claim ships **with its source links,
   method and caveat** — reproducible journalism by design.

For a *signed, tamper-evident* copy of the underlying articles, export an **evidence
bundle** from **Evidence & custody** — the receipts can ship with your issue.

---

### How the cards are produced (Briefing v0)

Each card is made by a **producer**: a function `corpus → [Card]`. Producers compose
analytics that *already return real numbers* — nothing is invented. A producer that
lacks its inputs or an optional `[analysis]` dependency **returns nothing and logs
why** (loud degradation); it never fabricates a card.

| Card | Bucket | Powered by | Status |
|---|---|---|---|
| **“X” is rising** | rising | `insights.trending` (recent vs prior-period ratio) | now |
| **Framing split** | check the framing | per-source VADER tone of a trending term | now¹ |
| **Record reshaped** | keep watching | Wikipedia large/flagged-edit detection | now |
| **Price ↔ narrative** | context | honest scipy correlation (coef + p + n) | now¹ |
| **Stale data** | data integrity | market extraction-rule `last_run_at` / `last_status` | now |
| **Diet self-audit** | context | `signals.concentration` (Gini + top-3 share over your sources) | now |
| **Echo chamber** | overtold | `signals.coordination` actor graph (near-dup + timing + host) | new |
| **Lonely signal** | undertold | single-source near-dup cluster that did not echo | new |
| **Capacity implausible** | investigate | articles/day vs corpus median | new |
| **Emotion profile** | context | emotion lexicon over a keyword's context windows | new² |
| **IP / legal pulse** | context | rising IP/legal terms in the news corpus | thin |
| **Ownership change** | investigate | deal-verb language (acquired/merger/divested) in recent news | thin |
| **Story lineage** | context | `signals.lineage` — a near-dup cluster ordered by publication time + wire attribution | new |
| **Coverage advisor** | context | `signals.concentration` over your sources' country/language (skew, not a cap) | new |
| **Weather check available** | investigate | `analytics.corroboration` — climate-event terms × deduced places × article dates | new |

¹ Needs the `[analysis]` extra (VADER / scipy). Without it those cards simply don't
appear — the rest of the briefing still works.
² Uses an emotion lexicon; a minimal English **sample** ships, point
`OO_EMOTION_LEXICON` at a fuller JSON lexicon for serious use (English-only).

The **echo-chamber**, **lonely-signal** and **capacity-implausible** cards come from the
source-integrity layer — see [`USER_MANUAL.md`](USER_MANUAL.md). Echo-chamber cards carry a
*Collapse to one actor* action (user-guided anti-amplification — propose → you dispose).

The **Diet self-audit** uses the first pure primitive of the shared
[`src/signals/`](../src/signals/) substrate: **concentration** (Gini coefficient +
top-N share). It is the *same maths* intended for media-ownership concentration
(FUTURE_DEVELOPMENTS §1) and people-prominence (§4) — one engine, many domains.

**Story lineage** traces an echoed story toward its **primal source**: for a near-duplicate
cluster across many outlets, it orders the pieces by publication time and detects explicit
**wire attribution** ("according to Reuters", "(AFP)") so original reporting is foregrounded
over derivative echoes. The bright line is honest: *"earliest we saw" ≠ "the truth"* — it
surfaces structure; the human judges. **Coverage advisor** surfaces geographic/linguistic
**skew in your own collection** (e.g. "~80% of what you collected is from one country") as a
gentle suggestion to broaden — it never filters or caps anything; a skewed corpus skews every
downstream signal, so seeing the skew is the point.

**Weather check available** is the first *if-this-then-suggest* card: when several of your
articles mention the same climate-event word (drought, flood, heatwave… — a curated
12-language seed list, `configs/corroboration_rules.yml`) together with the same deduced
place inside one time window, the card **offers** to fetch independent weather data for
exactly that place and window. The card itself is computed locally — it says so — and
nothing is fetched until you click **Fetch weather context**, which passes through the
same network-consent popup as every other online action. What comes back is one bounded
Open-Meteo **reanalysis** slice (CC BY 4.0, attribution shown): a *model estimate*, not a
station record — it can **corroborate or challenge** what the articles say, never prove
it. The slice is cached on disk so re-reading it later is offline; the cached state and
fetch time are always shown.

---

### Performance — precompute, cache, serve cached

The briefing **never computes per request**. The background scheduler refreshes it
after each scrape and writes a cache (`briefing_cache.json` under your data dir);
Home reads the cache and loads instantly. **Refresh** recomputes on demand. Dismissals
(`briefing_dismissed.json`) and the draft (`briefing_draft.json`) are small local JSON
files — single-user, local-first, never transmitted.

---

### Honesty guards (in code, not just docs)

FUTURE_DEVELOPMENTS §6 forbids a single automated trust/quality score (it bakes the
scorer's worldview into a false-objective number and *will* misclassify small, foreign,
new or dissident sources). That ban is enforced **mechanically**:

- `src/briefing/card.py:assert_no_score_fields()` rejects any `Card` field whose name
  implies a composite score (`score`, `trust_score`, `credibility`, `rating`,
  `verdict`, …). It runs at import and a test asserts it holds.
- The numeric a card carries lives in `signal` as **one measured quantity with a
  stated method** — a growth ratio, a Gini value, a correlation coefficient — never a
  blended score over incommensurable dimensions.
- **Surface, don't suppress.** Dismissal is reversible; any future down-weighting will
  be transparent, tunable, off by default, and reversible.

---

### API

All under `/api/briefing` (loopback only, like the rest of the app):

| Method & path | Purpose |
|---|---|
| `GET /api/briefing` | the cached feed, grouped by bucket (`?force=true` to recompute) |
| `POST /api/briefing/refresh` | recompute now |
| `POST /api/briefing/dismiss` · `/restore` · `/dismissed/clear` | manage dismissals |
| `GET /api/briefing/draft` | the current draft (pinned cards + notes + title) |
| `POST /api/briefing/draft/add` · `DELETE /api/briefing/draft/{id}` | pin / unpin a card |
| `PUT /api/briefing/draft/note` · `/title` · `POST /draft/clear` | edit the draft |
| `GET /api/briefing/draft/export.md` | the evidence-carrying Markdown |

---

### Roadmap (status)

Phases A–D are shipped: the card+briefing spine (A), the full `src/signals/` substrate
— concentration, near-dup/coordination, novelty (B), the source-integrity profile +
user-guided anti-amplification (C, see [`USER_MANUAL.md`](USER_MANUAL.md)), and crowdsourced
signed annotation bundles (D, see [`USER_MANUAL.md`](USER_MANUAL.md)). Phase E ships the
composable verticals as cards (emotion, IP/legal news); the **law / IP primary-source
change-tracking verticals** (ingesting `legislation.gov.uk`, EUR-Lex, patents/dockets)
remain the documented next step — they reuse the existing change-tracking and
near-dup/correlation engines but require live external sources. See
[`ROADMAP.md`](ROADMAP.md) Phases B–E.


---

## Source integrity & anti-amplification

> **Status:** `0.06` Phase C — shipped and tested. The keystone of the intelligence
> layer (FUTURE_DEVELOPMENTS §6). Pairs with [`USER_MANUAL.md`](USER_MANUAL.md) and
> [`USER_MANUAL.md`](USER_MANUAL.md).

The other tools surface signals; **this one decides whose signal counts** — *without
becoming an arbiter of truth*. It is the answer to the "garbage in" problem.

### The surprise: treating every source equally is **not** neutral

Trending, prominence, synchrony and "what's covered" all **count outlets and volume**.
So equal-treatment-of-outlets, applied to a volume metric, has a built-in bias:
*whoever produces the most wins.* A well-resourced actor who spins up 40 outlets (or
troll farms, or content mills) converts capital directly into apparent consensus and
**dilutes** honest single-source stories into nothing. Doing nothing is not neutral —
it subsidises the flooder.

The resolution is not to *score* sources. It is to define neutrality over the right
**unit**: equal treatment of *independent actors weighted by the new information they
contribute*, not of *outlets*. **Counting sock-puppets as voices is a measurement
error, not neutrality.**

### What is measured (and what is forbidden)

We live strictly in the **allowed** half of the §6 distinction:

- **(A) Veracity / quality scoring** — "is this source truthful / good?" — is
  **forbidden to automate.** It bakes the scorer's worldview into a false-objective
  number and *will* eventually score a good-but-unusual source down too.
- **(B) Authenticity / structure signals** — "is this source what it claims to be? one
  node of a coordinated network? does it *originate* or only *echo*? is its output
  within human capacity? is it transparent about who runs it?" — these are, to a real
  degree, **measurable structural facts.** All design lives here.

#### The shared engine (`src/signals/`)

| Primitive | Measures | Powers |
|---|---|---|
| `concentration` | Gini + top-N share | ownership/diet concentration, prominence |
| `near_dup` | MinHash + LSH near-duplicate clusters | echo / syndication detection |
| `coordination` | actor graph from near-dup + lockstep timing + shared host | actor-collapse |
| `novelty` | share of word-shingles new to the corpus | originates-vs-echoes weighting |

All four are **pure** (no DB, no network), property-tested, and carry method + caveat.

### Anti-amplification is **user-guided** (propose → you dispose)

Anti-amplification is **never** a silent transform the app performs and you merely
*undo* — that would make the app the arbiter §6 forbids.

- **Default = "equal but aware."** The raw equal-treatment view is the baseline; a
  coordinated flood is **annotated on it** (the *echo-chamber* card), not collapsed.
- **You apply a collapse**, per-cluster or globally. Only then does a coordinated
  network fold into **one voice** in any count that measures consensus (how many
  independent voices carry a story).
- **Every applied collapse stays flagged and reversible.** One click expands it to its
  members; reverting reproduces the raw equal counts **exactly**. *No collapse is ever
  applied without your explicit action* — enforced by a test.

This is the **Source integrity** tab: *Scan for coordination* lists proposed actors
with their evidence (shared text, lockstep timing, shared host); *Apply collapse* /
*Expand (revert)* are yours to choose. The echo-chamber cards on Home carry the same
*Collapse to one actor* action.

### The source profile — measured dimensions, **no composite score**

Per source, a panel of *measured* signals — and **deliberately no single trust
number** (the forbidden "B"). A 0–100 score is false precision over incommensurable
dimensions, Goodhart-gameable, a single point of capture, and *will* misclassify
small / foreign / new / dissident sources. The ban is enforced in code (the profile
returns `no_composite_score: true` and a test asserts no aggregate `*score*` key).

Dimensions (each with its own method + caveat):

- **Coordination** — actor membership, with whom, how many shared stories.
- **Novelty** — does this source originate or mostly echo? (relative to *your* corpus).
- **Output capacity** — articles/day vs the corpus median (a *question*, not a verdict;
  wire agencies and big newsrooms are legitimately prolific).
- **Transparency** — country, language, ownership/leaning tags (reputational,
  contestable, editable), and the operator-set `reliability_score` (not computed here).
- **Track record** — what this source has contributed to your corpus.

You weight which dimensions matter into *your* view — off by default, reversible, the
raw equal view always one click away.

### New briefing cards from this layer

- **Echo chamber** (overtold) — one story carried across N coordinated sources.
- **Lonely signal** (undertold) — a substantive single-source story that did not echo.
- **Capacity implausible** (investigate) — a source publishing far above the corpus norm.

### API

| Method & path | Purpose |
|---|---|
| `GET /api/integrity/profile?source=` | the no-composite measured-signal panel |
| `GET /api/integrity/actors` | proposed coordinated actors, each flagged applied/not |
| `GET /api/integrity/prominence` | story prominence in independent voices, raw vs collapsed |
| `POST /api/integrity/collapse/apply` · `/revert` | apply / undo a collapse (per actor) |
| `POST /api/integrity/collapse/apply_all` · `/revert_all` | collapse / reset globally |

### Honest limits (named)

- **Arms race / Goodhart** — every published signal is an optimisation target; this is
  defence-in-depth, never a claim of completeness.
- **False merges hurt the innocent** — detection is high-precision, biased to
  *under*-merge, always evidence-shown, always reversible.
- **Capture** — we ship *mechanisms, not verdicts*; the default is the transparent
  equal view; you override everything.
- **The goal** is not "detect all garbage" (impossible, and claiming it would be the
  dishonest move) but to **strip garbage of its mechanical advantage** so the 40-agency
  play *stops paying off*.


---

## Shared source annotations — signed, portable, federated by trust

> **Status:** `0.06` Phase D — shipped and tested. The scaling answer to the source
> profile (FUTURE_DEVELOPMENTS §6). Pairs with [`USER_MANUAL.md`](USER_MANUAL.md).

The source profile lets *you* weight which dimensions matter. But **nobody can neutrally
assess thousands of sources alone** — so the weighting must be **collective**. The
honest, local-first, non-centralised way to do that is **signed, shareable annotation
bundles**.

- You publish your source annotations — coordination tags, ownership/transparency
  facts, leaning tags, corrections, notes — as a **custody-signed, verifiable, portable
  bundle** (reusing the same hybrid Ed25519 + ML-DSA signer as the chain of custody —
  *mutualisation*, not a second crypto stack).
- Other users **import** the bundles they choose to trust — an opt-in **web of trust**,
  **never** a central authority.
- Aggregation is **transparent**: you always see *who asserted what*, and **dissent is
  shown, not averaged** into a hidden number.

No server, no accounts, no global score — **federation by signed exchange.**

### What an annotation is (and is not)

An annotation is a **descriptive, contestable fact or tag** about a source. Kinds:
`ownership`, `leaning`, `coordination-tag`, `transparency-fact`, `correction`, `note`.
It is **never** a composite trust/quality score — that is forbidden, by design and in
code (an invalid kind like `trust-score` is rejected).

### Trust model — what a signature does and doesn't prove

Each bundle embeds the author's **public identity** and a signature over the canonical
manifest. Verification **pins** the embedded key, so a tamper-and-re-sign attack cannot
*impersonate* the original author — it merely produces a **different** author. A
verified bundle is therefore always truthfully attributed to whatever key signed it.
You then decide *which keys to trust*; only trusted authors' annotations are aggregated.

This is **web-of-trust, not proof of correctness**: trusting an author means "I want to
see their assertions," not "their assertions are true." Dissent between trusted authors
is surfaced for you to judge, never resolved for you.

### Using it (the Source integrity tab)

1. **Author** annotations (target + kind + value) under *Shared annotations*.
2. **Export signed bundle** → a JSON file you can publish or share.
3. **Import bundle…** → the app **verifies the signature** before storing it (an invalid
   bundle is refused, loudly), then lists the author under *Trusted authors* with a
   trust toggle.
4. **Who said what?** → aggregate every assertion about a source from you + trusted
   authors, with attributions and dissent shown.

Untrusting an author excludes their annotations; removing one deletes them cleanly.

### API

| Method & path | Purpose |
|---|---|
| `GET /api/annotations/mine` · `POST` · `DELETE /mine/{i}` | your authored annotations |
| `GET /api/annotations/export` | a signed, portable bundle of your annotations |
| `POST /api/annotations/import` | verify + store an imported bundle (refused if invalid) |
| `GET /api/annotations/authors` · `PUT /authors/trust` · `DELETE /authors/{id}` | the web of trust |
| `GET /api/annotations/for?target=` | transparent aggregation — who asserted what |

### Honesty constraints

- **No averaging, no consensus number, no score.** Aggregation returns attributed
  claims and names *dissent*; it never collapses disagreement into a figure.
- **Local-first.** Everything is a file under your data dir; nothing is transmitted and
  there is no server or account.
- **Contestable by construction.** Every annotation is a tag/fact you and others can
  disagree about — visibly.


---

## Insights — keyword & entity analytics

### Intent

Turn the unified corpus from a search box into an analytical instrument. Keywords
and entities are extracted from **ingested article text**, stored with their
occurrences and context, and surfaced so an investigative journalist can ask:
*what is being talked about, where, when, by whom, and together with what?*

Everything here is a **real aggregate** over stored data with a stated method and
sample size — never a fabricated score (PRODUCT_SYNTHESIS §3.5).

### How it works

```
ingest an article ──► extract (baseline / opt-in spaCy) ──► KeywordMention rows
                          terms + entities, offsets        (count + first offset +
                                                            denormalised date/country/city)
                                                                   │
                          Insights tab / /api/insights  ◄──────────┘
                          trends · associations (PMI) · context · map
```

- **Extraction** (`src/analytics/extract.py`): topical n-gram **terms**
  (stopword-filtered) plus **entities** — people, companies/orgs, places — as
  single units. The baseline (no dependencies) detects entities as multi-word
  Title-Case sequences and assigns a `person`/`org`/`location` kind only from a
  gazetteer (otherwise the honest generic `entity`); an opt-in **spaCy** `[nlp]`
  extra adds real `PERSON`/`ORG`/`GPE` NER. Every keyword records **which extractor
  labelled it** — an entity type is a *labelled-by-X assertion*, not ground truth.
  Best for space-delimited scripts; CJK/Arabic segmentation is a known later step.
- **Storage** (`src/analytics/store.py`): one `KeywordMention` per (article,
  keyword) — occurrence count + first char offset (the context sentence is sliced
  from the stored article on read, so the DB stays lean) + denormalised
  `observed_on` / `country` / `city` from the source. Indexing runs best-effort at
  ingest (fast baseline, fail-open) and can be **back-filled** over the existing
  corpus from the Insights tab ("Index corpus").

### Functions (Insights tab + `/api/insights`)

| View | Endpoint | What it shows |
|------|----------|---------------|
| Explore — trend | `GET /trend?term=&bucket=` | Mention volume over time (day/week/month), with the resolved keyword + kind |
| Explore — mind-map | `GET /associations?term=` | Co-occurring keywords ranked by **PMI** (pointwise mutual information) with sample sizes + a "association ≠ causation" caveat; click a node to recenter |
| Explore — context | `GET /context?term=` | Recent mention snippets sliced from article text, with article/source links + country/city/date |
| Trends | `GET /trending`, `GET /top` | Rising terms (recent-vs-prior **ratio**, a labelled measure) and top terms, filterable by window / kind / country |
| Map | `GET /map?days=&kind=` | Top keywords **per country and per city** (source-based region signal) |
| Indexing | `GET /status`, `POST /reindex?limit=` | Indexed/remaining counts; chunked corpus backfill |

`kind` filters: `term`, `entity`, `person`, `org`, `location`.

### Honesty guarantees

- Trends/top are real counts; "rising" is a defined recent-vs-prior **ratio**,
  explicitly *not* a significance test.
- Associations use **PMI** over article co-occurrence, returned with `n` and the
  caveat that small samples are noisy.
- Entity kinds carry extractor provenance; the baseline never claims a precise
  person/org/place type it cannot justify.
- Region on the map is the **source's** country/city (the reliable signal). The
  Map view now includes an **interactive equirectangular SVG** (zoom/pan, city
  labels on zoom) plotting cities by real lat/lon from a **gazetteer**: a small
  sample ships (`configs/cities.sample.yml`); the full set is generated from
  Wikidata (`scripts/build_city_gazetteer.py` → `configs/cities.yml`). A city with
  no gazetteer match keeps its keyword data but **no plotted position** (never a
  fabricated location). Country/city tables remain alongside the map.


---

## Wikipedia change-tracking

### Intent

Wikipedia is contested ground: articles are continuously edited, and in the LLM
era removing or rewriting history is easier than ever. This tool treats each
Wikipedia **language edition** as a tracked source whose *edits* are the data, so
a journalist can **detect and document** large-scale or revisionist changes —
e.g. prove that a sentence existed on a given date and was removed by a given
account.

> Editions are per-**language** (`en`, `fr`, `ar`, `ru`, `zh`, …), not
> per-country (there is no national Wikipedia); the UI maps languages to countries.

### Why this is not "regular article" ingestion

Articles change over time, so they cannot be stored as one-shot `Article` rows.
Two design choices follow:

1. **Use the MediaWiki Action API, not page scraping** — `revisions`,
   `recentchanges` (with byte deltas), and `compare` (server-computed diffs). This
   is the efficient, ToS-friendly, change-oriented path.
2. **Store deltas, not re-copies** — keep **one** compressed full-text baseline
   per page (`wiki_pages.baseline_text`); every edit after is a `wiki_revisions`
   row holding the **diff + signed byte delta + flags**, never the whole new
   article. Any historical version is reconstructable by replaying diffs.

**This answers the redundancy/disk question:** a cosmetic edit is a tiny diff
carrying MediaWiki's `minor` flag and is filtered by a size/minor threshold, so it
costs almost nothing. Storage scales with **edit activity on watched pages**, not
with the multi-GB article corpus — you never need the full dump for tracking.

### Detecting large-scale / suspicious edits (honest)

`src/wiki/flagging.py` flags an edit and records **reason codes** — it surfaces
*candidates*, it does not pronounce "disinformation":

- `large_removal` / `large_addition` — byte delta beyond a threshold
- `revert` / `blank` — MediaWiki change tags (`mw-reverted`, `mw-undo`, `mw-blank`…)
- `anon_large` — a medium+ edit from an anonymous IP
- `burst` — many edits to one page in a short window
- `ores_damaging` — optional **Wikimedia ORES** "damaging" probability, presented
  as a *labelled-by-ORES* assertion (like our entity provenance)

Minor cosmetic edits are never flagged. Each flagged edit is documented with its
diff + provenance (revid, editor, timestamp), which plugs into the existing
**chain-of-custody** for signed/timestamped evidence.

### Two clearly-separated subsystems (UX)

1. **Watch & track** (lightweight, instant, the default): a watchlist of pages /
   categories per language edition; poll revisions on the in-app scheduler; store
   revisions + diffs + flags; a diff viewer + per-page timeline. No bulk download.
2. **Offline baseline** (heavy, optional): lives in **Settings → Wikipedia
   offline baselines** (deliberately out of the way of the lightweight tracker). A
   **selectable list of language editions** (curated, largest-first, with each
   language's own name and a coarse size tier) replaces free-text code entry; the
   exact current dump size is read from the server on demand (`Estimate size`),
   then download / pause / resume / delete. The list comes from
   `GET /api/wiki/languages`; the downloader still accepts any edition code.
   (Size reality: current-text enwiki ≈ 22 GB compressed; full history is
   terabytes — only needed for offline historical diffs.)

### Status

- **Done:** schema (`wiki_pages`, `wiki_revisions`; migration `d4e5f6a7b8c9`);
  the MediaWiki API parser + live client (`mediawiki.py`, `client.py`); the
  edit-flagging logic (`flagging.py`); ORES client (`ores.py`); the tracking
  orchestrator (`track.py`, baseline + delta storage); the scheduler `wiki` mode;
  the **API** (`/api/wiki/*`) and the **Wikipedia tab** (watchlist, track now,
  flagged-changes feed, diff viewer); the **offline baseline downloader**
  (`dumps.py` — per-language, resumable, size probe) now driven by a **language
  picker** (`languages.py`, `GET /api/wiki/languages`) relocated to **Settings →
  Wikipedia offline baselines**. All pure logic + orchestration unit-tested with
  fixtures (no network).
- **Next:** cross-link wiki diffs into the Insights keyword analytics; optional
  EventStreams firehose; evidence-export of a flagged diff via chain-of-custody.

### Ethics

All fetching honours the MediaWiki API usage policy (identifying User-Agent,
`maxlag`, rate limits) — more considerate than scraping. We store only public
revision data; nothing is fetched until tracking runs.


---

## World law — change-tracking for statutes, gazettes & IP

> **Status:** `0.06` Phase E — shipped. The §5 vertical: a "Wikipedia for the law."
> Reuses the change-tracking engine (`src/wiki`) and the shared `src/signals/` engines.

Aggregate the **law** — statutes, legislation, official gazettes, IP records — from
official sources worldwide, and **track how it changes over time**. Law is public in
many countries and changes by amendment, so the data *is the diff*: what changed, when.

### On by default — a worldwide catalog of real official sources

`configs/legal_sources.yml` ships a curated, worldwide set of **real official primary
sources** — national legislation databases (`legislation.gov.uk`, EUR-Lex, Légifrance,
`gesetze-im-internet.de`, `congress.gov`/`govinfo.gov`, `legislation.gov.au`,
`indiacode.nic.in`, `elaws.e-gov.go.jp`, `law.go.kr`, …), official gazettes, IP offices
(WIPO Lex, USPTO, EPO, EUIPO, JPO, …) and open case-law/filing systems (CourtListener,
SEC EDGAR). On first run these are seeded as ordinary **ingestible, searchable** sources
(`source_type` legal/ip), so they flow through the *same* ethical pipeline as news.

A curated subset of stable, well-known **consolidated-law documents** (e.g. the UK Human
Rights Act, the EU GDPR, the US Constitution) is registered for **change-tracking** out
of the box.

### How tracking works (reuses the Wikipedia engine)

For each tracked document, the first successful fetch is the immutable **baseline**
("the law as it stood on date X"). Every later fetch whose *normalised visible text*
differs records a revision carrying the byte delta, a capped unified **diff** against the
baseline, and an honest **large-change flag** (reusing the wiki flagging thresholds).
Run it from the **World law** tab ("Track changes now") or on the background scheduler
(`law` mode). All fetching is through the **ethical, robots-fail-closed** path.

### Briefing cards from the law corpus

- **Law changed** (watch) — a flagged change to a tracked legal document.
- **Model legislation** (investigate) — near-identical legal text across two or more
  jurisdictions (the §1/§2 near-dup engine), a measurable diffusion pattern.

Plus, because legal text is in the unified corpus, **law ↔ news** correlation and
keyword analytics work over it like any other source.

### API

| Method & path | Purpose |
|---|---|
| `GET /api/law/status` | coverage: documents per jurisdiction, change/flag totals |
| `GET /api/law/documents` | tracked documents (optionally `?jurisdiction=`) |
| `GET /api/law/documents/{id}` | one document with its change history (diffs) |
| `GET /api/law/changes` | recent (flagged) legal changes, newest first |
| `POST /api/law/track` | fetch all watched documents now (ethical fetcher) |
| `POST /api/law/seed` | (re)seed the worldwide catalog + register documents |

### Honesty constraints (law is high-stakes)

- **Not legal advice, not the authoritative source.** The aggregated copy is a
  *research mirror*; every record links back to the official gazette, and the UI says so.
  Track and surface; never interpret legality or judge a law.
- **"Public" ≠ "freely redistributable."** Licences vary even where text is public —
  each is respected, attributed, with provenance stored, robots fail-closed (as for news).
- **Scope honestly.** "Every country" is the north star, not v1: the catalog is broad but
  curated, and change-tracking is by normalised-text diff (consolidated-text portals give
  the cleanest signal). Structured formats (Akoma Ntoso / ELI) per-edit diffs are the next
  refinement; the tool says which it has.
- **Translation** (via the local LLM) is a separate, clearly-labelled aid — never an
  authoritative legal translation.


---

## Markets: financial, stock-exchange, and commodity/rare-earth intelligence

Open Omniscience ships a **curated, worldwide catalog of market sources** so it is
ready to ingest financial-market coverage out of the box, and a Markets tab that
turns *configured* pages into a real, chartable price series correlated with news.

This document explains what's pre-packaged, what isn't, and why — because the
honest boundary here matters more than a long feature list.

### What is pre-packaged (ready to run as-is)

`configs/markets_sources.yml` is seeded automatically alongside the news catalog
(`configs/sources.yml`) on first launch and via **Sources & Database → Seed
starter sources**. It contains ~110 curated entries identified by stable primary
domain:

- **Stock & securities exchanges** worldwide (Americas, Europe, Asia-Pacific,
  Middle East, Africa) — NYSE, Nasdaq, LSE, Euronext, Deutsche Börse, JPX, HKEX,
  SSE/SZSE, NSE/BSE India, SGX, ASX, B3, Tadawul, JSE, and many more.
- **Commodity / metals / energy / derivatives exchanges** — CME Group, ICE, LME,
  SHFE, DCE, ZCE, INE, **GFEX** (rare-earth & industrial-silicon futures), MCX,
  Eurex, MGEX.
- **Commodity & rare-earth price/data sources** — Shanghai Metals Market, Kitco,
  USGS, World Bank Pink Sheet, EIA, IEA, OPEC, Fastmarkets, Argus, Benchmark
  Mineral Intelligence, S&P Global Commodity Insights.
- **Financial news & data publishers** — Bloomberg, Reuters, FT, WSJ, CNBC,
  MarketWatch, Nikkei Asia, Caixin, and others.

These are ordinary **sources**: they feed the unified corpus through the same
ethical fetcher (robots.txt fail-closed, rate-limited). Each carries a
`source_type` (`stock_exchange` / `commodity` / `financial`), region, country and
tags, so you can filter them in **Sources & Database** and attach price rules in
**Markets**.

> RSS feeds are intentionally left blank for these entries (a wrong feed URL is
> just noise). Ingest them with the recursive crawler, or add a verified RSS feed
> per source from the Sources tab.

### Getting real price numbers

A price series is only produced where you tell the app **exactly where the number
is** — there is no magic page-reading, by design. Two honest paths:

#### 1. Per-page extraction rules (Markets tab)

Add a rule (source, symbol, page URL, **CSS selector**, optional attribute /
value-regex, currency, unit), then press **Test**. Test fetches the page once and
shows the *exact* value found — or the *exact* reason it didn't match — so you can
tune the selector with real feedback. Matching rules store one `CommodityPrice`
per day, which the inline charts and price↔news correlation read.

Templates to copy: `configs/market_rules.example.yml`.

**Caveat (read this):** most exchange/quote pages render prices with JavaScript,
so the number is *not* in the static HTML the fetcher receives and a selector will
find nothing. This is why working selectors are **not** pre-shipped — guessing
them would mean fabricated numbers. Server-rendered pages (many official/statistical
sites, some data tables) work well; heavily client-rendered quote widgets do not.

#### 2. Official CSV feeds (recommended — reliable, ships with a catalog)

For trustworthy numeric history, import a machine-readable CSV series from an
official source. This is the reliable path and the app ships a starter catalog
(`configs/commodity_feeds.yml`) you can import in one click from
**Markets → Official price feeds**, or via the API:

```
GET  /api/markets/feeds                # list curated feeds + how many points each has
POST /api/markets/feeds/{key}/import   # import one (e.g. copper, wti_crude, brent_crude)
POST /api/markets/feeds/import-url      # import ANY CSV URL you supply (user-customizable)
```

**Primary provider — FRED** (Federal Reserve Bank of St. Louis): a stable,
no-API-key CSV endpoint, `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`,
which **redistributes the World Bank "Pink Sheet" commodity series** (the
"Global price of …" IDs — copper `PCOPPUSDM`, brent `POILBREUSDM`, etc.) and
**EIA** energy series (`DCOILWTICO`, `DHHNGSP`, …). First column is the date,
second the value; missing values (`.`) are skipped, never stored as zero. Import
is idempotent per `(symbol, market, date)`.

**Comparable sources** you can add as a custom feed (URL + optional column names):
- **World Bank** Commodity Markets ("Pink Sheet"): the `.xlsx` is at
  <https://www.worldbank.org/en/research/commodity-markets>; the same series in
  clean CSV come via the FRED feeds above.
- **U.S. EIA** energy open data: <https://www.eia.gov/opendata/>
- **IMF** Primary Commodity Prices: <https://www.imf.org/en/Research/commodity-prices>
- **USGS** mineral commodity data (rare earths): <https://www.usgs.gov/centers/national-minerals-information-center>

The default column mapping is column 1 = date, column 2 = value (the FRED
convention); name `date_column` / `value_column` explicitly for other layouts.

There is also a direct file-upload path for a CSV you already have:

```
POST /api/commodities/{symbol}/prices/import-csv      (multipart file upload)
```

> If a provider renames or retires a series, the import fails **loudly** (HTTP
> error / no usable rows) rather than inventing data — fix the URL in
> `configs/commodity_feeds.yml` or use a custom feed.

### Why no auto-extracted prices on day one?

Because a number with no verifiable origin is worse than no number. Everything in
this tool is built so that a figure shown to the user came from a real
measurement: a selector that actually matched, or a CSV that was actually
imported. The catalog gets you the *sources* instantly; you decide, per page, when
a price is trustworthy enough to record.


---

## Chain of Custody

Open Omniscience makes a deliberately *narrow and honest* evidentiary claim:

> **This corpus contained _this_ item, with _this_ content, recorded at _this_
> time, and the record has not been altered since — and here is cryptographic
> proof you can check yourself, offline, without trusting this tool.**

That is genuinely useful for an investigative journalist: it defends against
"you fabricated this," "you back‑dated this," or "you quietly edited it after the
fact," and it lets you show you reported something *before* a source page was
changed or deleted. It is **not** a whistleblower submission system (like
SecureDrop), and a "source" in this tool is a *news outlet*, not a confidential
human source. Keep that scope in mind when reasoning about protection.

This document describes the real mechanisms (`src/custody/`, `src/reporting/`) and
is explicit about what each one does and does **not** prove.

---

### The three properties, and how we get each one honestly

| Property | Mechanism | What it proves | What it does **not** prove |
|---|---|---|---|
| **Integrity** | Ed25519 (+ optional ML‑DSA) signatures over a canonical serialization; Merkle root over all provenance fields | The bytes have not changed since signing; everything is covered, not just the content | — |
| **Provenance** | **Pinning** the signer's known public key | The record was signed by *that* signer | Anything, if you don't pin a key — a valid signature alone only means "signed by the key embedded in the bundle" |
| **Time** | `local` (self‑asserted) **or** OpenTimestamps (Bitcoin‑anchored) | Local: a time the tool asserts. OTS: the content existed *no later than* a Bitcoin block | Local time proves nothing to a third party; OTS proves a *ceiling* on time, not the exact moment |

We refuse to fake any of these. If a real third‑party timestamp can't be obtained
(offline, or the library isn't installed) the code raises rather than inventing a
time — the failure mode the project's charter forbids (PRODUCT_SYNTHESIS §3.7).

---

### Components

#### 1. Signed evidence bundles — `src/reporting/evidence.py`
A point‑in‑time export of selected articles, each with its provenance and a content
hash, bound by a **domain‑separated Merkle root** and an **Ed25519 signature**.
Verify offline with `scripts/verify_evidence.py <bundle.json> [signer_pubkey]`.
Exposed at `POST /api/reports/evidence` and `/api/reports/evidence/verify`.

#### 2. Hybrid signatures — `src/custody/signing.py`
Combines **Ed25519** (fast, classical) with **ML‑DSA** (FIPS 204, post‑quantum,
the standardised successor to CRYSTALS‑Dilithium). Two rules make this honest:

- **Honest labels.** A signature is labelled `hybrid` only when an ML‑DSA key was
  actually used. Without the `pqc` extra installed, signing produces an `ed25519`
  signature and says so — it never claims quantum resistance it didn't produce.
- **Hybrid means AND.** A `hybrid` signature verifies only if **both** components
  verify. A verifier that lacks the post‑quantum library cannot check the ML‑DSA
  half and therefore **fails loudly** — it never silently passes on the classical
  half alone. (A scheme that accepts *either* signature is worthless once the
  classical one is broken.)

Private keys are encrypted at rest with AES‑256‑GCM under a scrypt‑derived key
when `OO_KEY_PASSPHRASE` is set; otherwise they are written `0600` in the clear
and the protection level is reported truthfully as `plaintext-0600`.

#### 3. Custody log — `src/custody/log.py`
An **append‑only** SQLite ledger. Each action (`ingest`, `access`, `export`,
`redact`, …) becomes an entry that is **hash‑chained** to its predecessor,
**signed**, and **timestamped**. `verify()` re‑checks sequence order, chain links,
per‑entry hashes, signatures, and timestamp digests. Exports verify offline:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
```

REST: `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`,
`GET /api/custody/export`, `POST /api/custody/verify`.

Opt‑in auto‑logging on ingest: set `OO_CUSTODY_ON_INGEST=1`
(`Config.custody_on_ingest`). It is **off by default** — an explicit evidentiary
choice with a small per‑article signing cost, not silent always‑on behaviour.
It is fail‑open: a custody error never breaks ingestion.

#### 4. Anchoring — `src/custody/anchor.py`
Publishes a Merkle root to an external witness so its existence time doesn't rest
on your own clock or key:

- **`local`** (default, offline): records the root in a local anchor book. Proves
  only that *this tool* stored it — internal audit, not third‑party proof.
- **`opentimestamps`** (network): anchors an opaque hash into Bitcoin. No wallet,
  no fee, independently verifiable. Falls back to an explicit *unavailable* error
  when offline — never a fake receipt.
- **`ethereum` / `ipfs` / `arweave`**: declared but **not implemented**. They
  refuse with a clear error rather than shipping as stubs whose `verify()` always
  returns false.

REST: `POST /api/custody/anchor`, `GET /api/custody/providers`.

#### 5. Settings — `src/custody/settings.py` (GUI‑configurable)
Custody behaviour is operator‑controlled at runtime, not just via env/YAML.
Preferences persist to `custody_settings.json` under the data dir and are edited
from the **Chain of custody** panel in the web UI (or the REST API):

- **`pqc_enabled`** — request hybrid Ed25519 + ML‑DSA signing.
- **`anchoring_mode`** — `local` (default) or `opentimestamps`.
- **`auto_log_on_ingest`** — append a signed entry on every successful ingest
  (defaults to the legacy `OO_CUSTODY_ON_INGEST` flag until a preference is saved).
- **`default_actor`** — optional actor label for auto‑logged entries.

**Honesty invariant.** A toggle is a *request*, not a guarantee. The API and GUI
always surface the **effective** state (preference **AND** library availability):
if PQC is enabled but `pqcrypto` is not installed, the signer stays Ed25519‑only
and the UI says so — it never shows a green "hybrid" light it cannot back up. Same
for OpenTimestamps without the `timestamping` extra.

REST: `GET /api/custody/settings`, `PUT /api/custody/settings`.

A typical "maximum proof" workflow:

```
export evidence bundle  ->  take its merkle_root  ->  POST /api/custody/anchor
  (POST /api/reports/evidence)                         {merkle_root, "opentimestamps"}
```

---

### ⚠️ Privacy: anchoring can deanonymise you

Anchoring to a **public** blockchain is **permanent publication** of a hash and a
timestamp. The hash itself reveals nothing about the content, but the *act* of
submitting reveals your IP and timing to the calendar/RPC operators, and a funded
on‑chain wallet creates a money trail. For anyone who needs anonymity:

- Prefer **local + OpenTimestamps** over public‑chain wallets.
- Route OpenTimestamps submissions through **Tor** (e.g. `HTTPS_PROXY`).
- Or skip external anchoring entirely and rely on local timestamps + signing.

Confidentiality and public‑chain anchoring are in tension. The default
configuration (offline local provider, self‑asserted local time) leaks nothing.

---

### What we deliberately did **not** build

- **No fake RFC‑3161 TSA.** Returning `datetime.now()` and calling it a "trusted
  timestamp" is theatre. Use OpenTimestamps (real) or local (honestly labelled).
- **No OR‑semantics hybrid signatures.** See "Hybrid means AND" above.
- **No always‑on background integrity daemon, no unencrypted key store advertised
  as "encrypted."** Keys say how they're protected; verification is on demand.

### Threat model in one paragraph

The tool runs as a **single local user, loopback‑only, on Qubes** (see
`docs/SECURITY.md`). The custody system defends the *integrity and provenance of
your own evidence trail* against later tampering and against "you made this up"
challenges. It does not, and cannot, protect a human source's identity by itself,
and naive public‑chain anchoring can actively *harm* anonymity — so anchoring is
opt‑in, defaults to offline, and ships with the warning above.


---

# What shipped in 0.0.8 — the roadmap cycle

Everything below is available now, entirely from the browser UI. Each feature states its
honest limit where it appears.

## Investigation recipes (Home) and the `/investigate` dashboard

The Home briefing now watches your own corpus for **space-time signals** and raises cards —
all computed locally, never from the network:

- **Promises due** — an article mentioned a date that was *in the future* when it was
  published; that date has now arrived. Time to ask what actually happened.
- **Edit-war burst** — a Wikipedia page you track is being edited at ≥3× its own recent
  weekly rate; its public record is in motion.
- **Region gone quiet** — a country that reliably produced articles for you (almost)
  stopped. The caveat is built in: this measures *your corpus*, not the region — a dead
  feed looks identical to real silence, so check the sources first.
- **Source candidates await review** — see *Discovery candidates* below.

Cards with an **"Open investigation ↗"** button open a dedicated dashboard **in a new
browser tab** (the main app keeps working; open several at once). The dashboard
auto-assembles the related panels — the original article with its provenance snippets, a
pre-filled follow-up search, the stored revision list, coverage context — carries the
card's caveat verbatim at the top, and ends with a **"Go deeper"** strip where every
suggestion is a normal action with its parameters shown. The page's whole state lives in
its URL: bookmark it, reopen it, share it between your own machines.

Switch individual recipes off under **Settings → General → Investigation recipes on Home**.

## Methods appendix (Search)

**Search → Methods appendix** downloads a Markdown document recording *how* your current
selection was produced: the app version, the verbatim Boolean query, result counts, corpus
context, and one provenance row per article (title · source · published · URL · content
SHA-256). It records selection only and asserts no conclusion — the analytical claims stay
yours, checkable against the rows. Built for fact-check verdicts and peer review; pair it
with a signed evidence bundle (Evidence & custody) when you need document + proof together.

## Synthesize results (Search)

**Search → Synthesize results** runs ONE local-model pass across your top results (at most
20; the response says when it truncated) and returns shared facts, points of disagreement
and open questions, citing member articles by number. The synthesis is stored with model +
prompt-version provenance per member article, and the caveat travels with it: this is
reading assistance over the listed members only — never a verdict. Requires Ollama, like
the other LLM features; without it you get an honest "not reachable" message.

## Versioned exports and the citation graph

- Machine-readable exports now carry a stable contract (`oo-export-1`): JSON exports are
  self-describing envelopes (schema, app version, generated-at, the exact query, count);
  CSV columns are unchanged, with the same provenance as `X-OO-*` HTTP headers.
- The **citation graph** — which external domains your stored articles cite, counts only,
  no inferred credibility — exports as GraphML (`/api/links/export.graphml`) for
  Gephi/yEd/NetworkX, or JSON.

## Scheduler run log and the drop-folder export (Collect)

Every scheduler run — success or failure — appends one line to a local, auditable run log
(`scheduler_runs.jsonl`), so the corpus can answer "what ran while I was away?". Optionally,
set a **Drop-folder export** path in the Collect scheduler card: each run then writes the
new-articles delta as an envelope-JSON file into that local folder for your own pipeline to
watch. Blank = off (the default); nothing new = no file.

## Discovery candidates (Sources)

The app now suggests sources on its own — **offline only**: domains your stored articles
repeatedly cite, and packaged-catalog outlets for countries your corpus covers thinly.
Suggestions are staged, never acted on: each carries its evidence in the **Discovery
candidates** panel (Sources tab), runs are capped by the scheduler's discovery budget and
recorded in the run log, and a Home card tells you when candidates await review.
**Promote** creates a *disabled* source you still have to enable; **Dismiss** is remembered
and never re-suggested. The DuckDuckGo-powered topic search remains separate, **off by
default**, and gated behind Settings → Safety (see below).

## External topic discovery is opt-in (Settings → Safety)

*Discover by topic* is the one feature that contacts an external service: it sends your
topic query to DuckDuckGo. It is now **disabled by default** and refuses with an honest
message until you enable **Settings → Safety → External topic discovery** ("Your query
leaves this machine"). Discovering RSS feeds for sources you added yourself stays on the
local ethical-fetch path and is not affected.

## Languages

The interface now ships **complete translations in 12 languages** (English, العربية, বাংলা,
Deutsch, Español, Français, हिन्दी, Bahasa Indonesia, 日本語, Português, Русский, 中文),
including right-to-left layout for Arabic. Pick yours from the language selector; the
translations are machine-generated first drafts — corrections are welcome contributions
(see `docs/ARCHITECTURE.md` → Internationalisation).
