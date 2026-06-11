# CLAUDE.md — long-term session memory (maintainer-mandated)

**THE PROTOCOL (meta-rule, maintainer-mandated):** this file is the single
ledger of every maintainer ruling. (1) Read it in full before any work, every
session. (2) Record every new ruling HERE in the same turn it is given —
shipped things under invariants, pending things under the queue. (3) If the
maintainer repeats feedback, that is a ledger failure: fix the gap AND the
ledger. (4) Critical invariants are ALSO enforced by
`tests/test_repo_invariants.py::test_ui_invariants` — extend that test whenever
one is added here. It exists because work regressed between sessions (the
Wikipedia dropdown became a text input) and the maintainer had to repeat
earlier rulings.

## Shipped rulings (do not regress; details in git history / docs)
Eye logo everywhere · sidebar always visible (rail ≥601px) · constant top-bar
footprints · persistent vitals strip, no version in chrome · network kill
switch on Stop · source preflight + shareable JSONL log · wiki edition dropdown
· local-first article links + related-by-keywords in the reader · Home never
blank (fail-safe producers + explanatory empty state) · 12 complete locales ·
date-stamped freshness-tested model catalog + live picker + clearnet notice ·
external topic discovery off-by-default · all 0.0.8 features documented in
USER_MANUAL · **Console/Desk FINAL verdict (ruled 2026-06-10, superseding the
same-day consolidation ruling): Desk is RETIRED ENTIRELY — one interface, the
Console, which is the default and adapts to window size (sidebar → icon rail).**
`desk.html` deleted (git history keeps it); `/desk` 308-redirects to `/`;
`launch.sh` opens `/` for any argument; the installer makes one launcher and
removes old Desk icons. Fold Desk's best ideas (task-framed home, ⌘K, calm)
into the Console over time — never resurrect a second chrome.

**Temporal map + Agenda are NOT lost** (maintainer feared this 2026-06).
Both shipped in the 0.07 cycle and are alive on 0.08: world map + time
slider + anchors + geocoded corpus + hazards layer = PRs #51/#52/#54
(`src/timemap/`, `GET /api/timemap`); world-events calendar with
subscribe/facet/group + event-family dedup = PRs #43/#47/#50/#53
(`src/events/`, `configs/world_events.yml`). 23 dedicated tests pass.
Root cause of the live-test scare: the maintainer was in the **Desk** view,
whose NAV lacked timemap/agenda/law/integrity — Desk is now retired entirely.

**The 3.8 MB → 2.3 MB download delta is NOT lost work** (investigated
2026-06-10 at the maintainer's request, with timestamps): the drop is exactly
PR #56 (audit cycle, merged 22:57 UTC 2026-06-09) deleting four NON-code files
— three stale machine-generated audit reports in `docs/archive/` (QUBS JSON
alone was 62.9 MB raw) + stale NEXT_VERSION.md. All feature code intact; the 6
dead packages were RENAMED to `quarantine/dead_src/` (100% similarity), not
deleted. Everything remains recoverable from git (`git show a006e3f:<path>`).
Before fearing loss from an archive-size change, run
`git diff --numstat <old> <new>` — sizes lie, diffs don't.

## Non-negotiables (project §0.5 + maintainer rulings)
- Local-first, loopback-only; the ONLY external service call is the gated,
  off-by-default DuckDuckGo topic discovery. Producers/briefing/discovery NEVER
  touch the network. App boot makes zero network calls.
- robots.txt fail-closed, per-host politeness, honest bot UA, single fetch path
  (`EthicalFetcher`), **global network kill switch** (`src/ingest`
  activate/clear_kill_switch — the Collect Stop button trips it).
- Honesty by construction: no composite trust/quality scores (CardSchemaError
  enforces); every signal carries method + caveat + n; degrade loudly.
- Whole roadmap ships under cycle branch `0.08` ⇒ release 0.0.8 (maintainer:
  do NOT open 0.09 until told). Version single-sourced from pyproject.
- No bundling of Ollama/models in the repo (GitHub 100 MB limit; decided
  2026-06). Model catalog must stay date-stamped (`CATALOG_AS_OF` + freshness
  test). Clearnet is a stated install prerequisite for model downloads.
- **Hosting stance (ruled 2026-06-10, adopting the PR #37 memo):** give the
  software away free; NEVER host the users' data. No SaaS, no central server,
  no accounts, no telemetry — the forward path is PWA + one-click self-host.

## UI invariants (maintainer-ruled; do not regress)
1. **Wikipedia edition picker is a `<select>` dropdown** (id `wiki-lang`), fed
   by `/api/wiki/languages` with continent `<optgroup>`s. Never a free-text input.
2. **Left sidebar lists all tabs and stays visible** — it may collapse to an
   icon rail, but must never disappear off-canvas above 600 px width.
3. **Top bar elements have constant footprints**: `.act-host` keeps its 160 px
   slot even when empty; `#llm` and `#health` have fixed min-widths; nothing on
   the right may shift as fetch hosts/labels change.
4. **A persistent compact vitals strip** (`#vitals-mini`: CPU · RAM · ↓ rate)
   lives in the top bar; the version number is NOT displayed in the chrome.
5. **The brand mark is the ASCII eye** (`assets/logo.txt`) as vector — the
   pointed-oval + grid-iris SVG in `index.html` and `assets/icon.svg`.
6. Article links in analytics/insights lead to the LOCAL reader
   (`/api/articles/{id}/view`) first; the external original is a secondary
   "source ↗" link. The reader shows "Related in your corpus" (shared-keyword
   overlap counts).
   **EXTENDED (ruled 2026-06-10, pending implementation): no bare "official
   source ↗" shortcuts ANYWHERE.** Every such link opens a local popup page
   first — the database extraction with all related metadata + keywords — and
   THAT page carries a transparent outbound link whose visible text IS the
   full URL (never hidden behind a label). Applies homogeneously to every
   section (articles, law documents, wiki diffs, market/commodity sources,
   events, hazards). Sweep carefully surface-by-surface; the external-link
   confirm guard (#7) stays as the second layer. **FIRST TARGET (maintainer
   repeat 2026-06-10): Home-card evidence links** — wiki-diff and law cards
   deep-link externally when no local article exists; build the local
   extraction popup (title + metadata + keywords + transparent full URL).
   Mindmap layers ✓ shipped; settings duplicate ✓ removed (same day).

7. **External links ALWAYS confirmed with a popup before opening** (ruled
   2026-06-10): delegated capture-phase `_externalLinkGuard` in BOTH UIs;
   loopback links exempt; message translated via `OOI18N.t`.

- **Home must never go blank-and-silent**: producer registration is fail-safe
  (core first, recipe pack additive in try/except); zero cards renders the
  explanatory empty state with Collect/Recompute actions — never an empty div.
- **Maintainer flag (live test): comprehensive Home-cards remake wanted** —
  treat the card feed as a flagship surface. DONE 2026-06-10 (first pass): all
  16 producers audited; young-corpus gates added (`_YOUNG_CORPUS_ARTICLES=200`:
  trending min_recent 3→2, diet 10→5 articles, coverage 10→5) with the honest
  "Early-corpus note: only N article(s)…" caveat appended — counts stay real.
  Event-driven producers (wiki/law/echo/lineage/capacity) keep strict gates by
  design. Remaining for the remake: visual/UX treatment of the feed itself.

- **TEMPORARY field-test mode (maintainer-ruled 2026-06-10; REMOVE when the
  live-test cycle ends):** `src/monitoring/field_test.py` (default ON,
  `OO_FIELD_TEST=0` opts out) auto-exercises every fetch surface inside the
  operator's collect passes — calendar verification in 50-feed batches until
  all 511 are checked, markets+indices import-all once, one law track, one
  wiki track — verbatim outcomes in `data/field_test.jsonl`, included in the
  debug bundle. Purpose (documented in the module + USER_MANUAL, because the
  repo is public): recurring self-improvement of the default lists; logs are
  local-only, shared only by the operator's click. Boot stays offline.

- **Naming (maintainer 2026-06-10): app-opened browser tabs are suffixed
  "· FOOS" = Free Open OmniScience** — the alpha working name, explained in
  the Help tab + USER_MANUAL; a proper rename is expected later (keep the
  suffix mechanism centralized enough to swap in one pass).

- **FIELD LOG #1 PROCESSED (2026-06-11, the maintainer's overnight run):**
  corpus 1,349 articles / 53k keywords (en 70k·fr 8.1k·de 1.2k signature
  volume); 26/26 runs ok; 511/511 calendars verified by field-test mode.
  Fixed from it: family over-merge guards (single-token ambiguity, clean
  2–3-token parents only, honorific-equality direct merge, junk labels) —
  validated by replaying the log; FRENCH stoplist block was entirely missing
  (dans/plus/pas leaked as top entities) + months/weekdays + elision
  stripping (d'euros→euros); first REAL equivalence ring batch (10 rings);
  catalog pruned from live verdicts (13 defunct WPH codes, 8 empty families,
  4 Stooq indices robots-denied, Wilshire 404; gold/silver → Pink Sheet
  monthlies). KNOWN: calendar.google.com + webcal.guru robots-disallow their
  feed paths (verdicts shown honestly; WPH is the working holiday provider);
  FRED bursts intermittently refused (transient conn errors — retry exists);
  'database is locked' under concurrent import+scrape = the download-manager
  arbitration item (queued, unchanged); preflight covers 50 sources/run —
  batch it like calendars (queued).

- **LIVE-TEST BATCH 2026-06-11 — all five items SHIPPED same day:**
  (1) Mind-maps follow MIND-MAP RULES now (maintainer-stated): centre → arms →
  always outward; deterministic radial tree, leaves hang off their strongest
  relative, no cross-tangle; family/supergroup levels use weight-ranked rings.
  The cloud stayed as a SECOND VIEW (golden-angle spiral, weight-ordered).
  Both have the date-spectrum control (all time/week/month/year/custom from-to
  threaded down to windowed PMI — method says "within the selected window"),
  ⛶ Enlarge (generic .mm-big) and a text-size slider (uniform multiplier:
  font size keeps meaning weight). (2) Super-groups ship PRE-CREATED:
  configs/keyword_supergroups.yml (8 groups drafted from field log #1,
  members verified present), idempotent startup seed, user edits always win.
  (3) Keyword log cap is PER LANGUAGE (5000) — maintainer: a global cap
  anglicises the export; corpus header reports exported_per_language +
  capped_languages. (4) Temporal map usability: precise Focus-date input,
  Time-span from/to REMAPPING the slider (play sweeps only that period),
  play speed 0.5–4×, ±2-months/±1-month/±1-week windows, pins now have fat
  transparent hit discs (fill=none was edge-only clickable), wheel zoom,
  in-map overlay controls (the Google-Maps "inside the map" principle —
  apply to future map-like surfaces), ⛶ Enlarge. (5) Settings → Wikipedia
  dumps language list never loaded: DUPLICATE loadWikiLanguages definition
  (the later tab-picker one overwrote the Settings one) → renamed
  loadDumpLanguages; the editions select is now MULTI-select and Download
  queues all picked editions sequentially. Lesson: duplicate top-level JS
  function names silently override — grep before declaring.

- **Article reader rework — TABS (maintainer-ruled 2026-06-11):** the dedicated
  article window gains tabs: Mindmap (this article's keyword graph) · Related
  articles · Source description · Keyword analysis · Sentiment analysis. The
  two-class metadata header SHIPPED same day (source-asserted vs app-deduced,
  dashed amber box + "never a confirmed fact" note, with extracted event dates
  AND places); the tabs are the next reader batch.
- **Article CORPORA (maintainer-ruled 2026-06-11, the flagship analysis ask):**
  select several articles anywhere in the app → "create a corpus" → opens its
  own window/tab with the SAME tabs as the reader rework but computed over all
  member articles, PLUS a corpus-only tab: **source competitive analysis** —
  how each source approaches a concept (angle, framing, sentiment, volume,
  timing), with real visual representations. Single articles don't get that
  tab (n=1 has no competition). Joins the queued tag-driven corpora as one
  corpora system: tag-selection and hand-selection are two entries to the
  same object.
- **Location extractor SHIPPED (2026-06-11):** src/timemap/locextract.py —
  gazetteer cities (case-sensitive, source-country disambiguated, says which
  rule decided) + curated multilingual country table (~90 forms); lexical,
  bounded, snippet provenance, "deduced" notes. Surfaced in the reader's
  deduced-metadata block next to extracted event dates. NEXT: feed the
  temporal map's mention layer with text locations (event site, not just
  coverage origin) + extend the country table from field logs.
- **Entity extractor SHIPPED (2026-06-11, the maintainer's WHO axis):**
  src/timemap/entextract.py — PEOPLE and ORGANIZATIONS as two SEPARATE classes
  by design (maintainer: "We should treat people and companies/organizations
  separately"). Rules, all explainable + noted per entry: honorific+name
  (high precision), lowercase-word-preceded Firstname-Lastname shape (weakest,
  says so), TitleCase phrase ending in an org word (leading determiners
  stripped), repeated acronyms (≥2 occurrences, stoplisted common caps out);
  a word claimed by an org never doubles as a person. Reader deduced block
  gains "People in text" + "Organizations in text" rows with ×N mention
  counts. NEXT: aggregate entities corpus-wide (the people/org layer for
  analytics + the future corpus tabs). btop ruled OUT as a vitals dependency
  (maintainer "OK for Btop, good call" 2026-06-11): Apache-2.0 C++ TUI binary,
  wrong shape — the CPU bug was psutil per-core normalization, fixed in-app.
- **The WHAT axis (maintainer musing 2026-06-11, answer recorded):** after
  when/where/who, the maintainer asked about "what" — then offered "maybe the
  article is the what". Assistant position: the article is the TESTIMONY of
  the what, not the what itself (many articles ↔ one event; that asymmetry is
  what echo/event-family detection already exploits). The WHAT has no extractor
  because it is not a surface feature — it EMERGES as the intersection of the
  other axes: articles sharing a time window + place + people/orgs + keyword
  family ARE an event, presented as overlap counts, never an event-type
  classification score. Concretely: the parked-for-0.0.9 convergence detection
  (PR #51 layers 3+4) becomes the WHAT engine, strengthened by the new WHO
  axis. No ruling yet — awaiting maintainer's direction before building.

## Session rituals
- Verify with BOTH venv profiles when deps change; `pytest -q` full suite must
  stay green; mypy ratchet ≤ baseline in CI; `node --check` every `<script>`
  block after UI edits; locale files must stay 100% (scripts/i18n_report.py)
  when adding chrome strings (12 languages, Arabic is RTL).
- Maintainer merges PRs fast: after `git push`, if the output says
  "[new branch]", the previous PR was merged — open a NEW PR onto `0.08`.
- Never use backticks inside `git commit -m` heredocs (shell substitution).

## Open queue (when maintainer says proceed)
- **Agenda views (maintainer 2026-06-10; RECONFIRMED 2026-06-11 — "I did NOT
  have a chance to see the calendar format"): NOT BUILT YET, the tab only has
  the list.** Build the switcher: list / week / month / trimester / semester /
  year / decade. PLUS (2026-06-11): MONTH-SPANNING events ("Dry January",
  "Movember") — the event model needs a duration/whole-month kind rendered as
  a banner across the month, not a single-day pin; world_events.yml schema
  gains an optional span (start/end or month=whole). Also: the Agenda tab is
  currently NOT translated at all (chrome-audit long tail — prioritize).
- **Agenda depth (maintainer 2026-06-10): only 4 categories — "we should be
  flooded; it's the point of datamining".** Expand `configs/world_events.yml`
  massively: many more calendars (elections worldwide, summits, central banks,
  parliaments, courts, UN observances, religious/civic holidays, fiscal dates,
  major sport/science events…) + ship the designed iCal import (official feeds
  → exact dates; PR #50's "next step"). Keep honesty: every entry sourced;
  movable dates marked; subscribe-default stays off-flood (user opts into the
  flood via subscriptions).
- **i18n long tail (462 unkeyed chrome strings, audit-tracked):** maintainer
  keeps hitting untranslated surfaces live (Settings ✓ done, Indices ✓ done,
  Agenda ← next, plus fragments). Burn down per-tab each session via
  `scripts/i18n_report.py --audit-chrome`.
- **Global search rework (maintainer 2026-06-10, design agreed in chat):** the
  ⌘K palette must become a FULL app-wide search or go — maintainer prefers
  keep+extend: instant ("Apple-like", index-backed, never scan-on-type),
  federated over corpus articles (FTS5 — already indexed), keywords/families,
  sources, events, docs full-text, AND the UI itself (tabs, settings labels,
  actions, notices — a generated registry, not the current ~20 static items).
  UX: top-10 grouped balloon while typing; Enter opens a full search popup
  with per-type facets. SECURITY stance (answered honestly): a UI/menu index
  holds nothing sensitive; corpus content already lives in FTS5 INSIDE the
  same SQLite file — encrypting only the new index would be theater. The
  index inherits the corpus's at-rest posture (documented stance: full-disk
  encryption LUKS/Qubes/Tails; encrypted backups exist). True at-rest DB
  encryption (SQLCipher-class) = design with the backup redesign, not ad hoc.
  **EXTENDED (maintainer 2026-06-10): once the advanced global search ships,
  REMOVE the Search tab from the sidebar** — the top omnibar becomes the
  single search entry, and its design must be careful, intuitive, elegant.
  Sequencing rule (the Desk lesson): the Enter-popup must FIRST absorb every
  Search-tab capability (boolean queries, source/date filters, result export,
  signed-evidence export, LLM synthesize) — only then does the tab go. Never
  silently lose a tool.
- **Temporal map: logarithmic time scale (maintainer idea 2026-06-10):** event
  density grows toward the present, so a log-scaled axis (dense recent years,
  compressed antiquity) is the intuitive default — agreed in chat; offer
  linear/log toggle, keep the slider honest (labelled ticks, no hidden warp).
- **Home cards → dedicated investigation GUIs (maintainer repeat 2026-06-10):**
  partially live — RM-20's /investigate exists with 3 views (promise/edit-war/
  quiet-region); whole-card click now opens it where a recipe exists; Home
  bucket titles + card actions now translated (×12). REMAINING: a dedicated
  /investigate view per card TYPE (rising→trend+associations+articles;
  diet/coverage→sources; echo→integrity; law/wiki→reader) so EVERY card is
  clickable; card TITLES are still server-built English (template-based
  title translation needs a design — titles carry data values).
- **Insights mindmap**: multi-layer zoom (keyword → family → supergroup) —
  data exists (`keyword_supergroups`, families API); needs zoomable rendering +
  proper legend on the trend graph above it. (Maintainer expected this; treat
  as the next feature item.)
- **World stock indices don't download** in live test — NARROWED 2026-06-10:
  only Dow Jones + S&P 500 arrive (FRED partially OK); Nikkei (FRED) and ALL
  Stooq-fed indices (DAX/FTSE/Hang Seng) fail. Suspect robots fail-closed on
  stooq.com or a feed-format change. Fix = per-index verdicts shown in the
  Indices UI (degrade loudly, like the feed directory) + honest diagnosis;
  never bypass robots. Ask the maintainer for the import response if needed.
- **Interactive charts** (maintainer, live test): commodity/markets graphs need
  zoom (wheel/drag) + discrete per-graph adjustable legends — "the user should
  feel closer to the data". Same treatment for the Insights trend graph.
- **Commodities cards detail (maintainer 2026-06-10, NEXT UP):** initial cards'
  graphs show only 5 points — they must render a detailed curve (then DROP the
  "· 5 pts" suffix as useless); detailed both axes + a legend + very discrete
  horizontal gridlines so curve-crossing X/Y points are identifiable.
- **Collector: cumulative runs + progress (maintainer 2026-06-10):** allow one
  Collect pass to CUMULATIVELY do RSS + recursive crawl + markets download +
  wiki watched pages; a progress bar visible THROUGHOUT the UI (the top-bar
  activity chip is the natural host). Maintainer also floated default-watching
  the top-1000 Wikipedia pages in all languages, bundled — needs a design
  answer first (network cost at first boot vs zero-network-boot non-negotiable;
  likely ship the LIST bundled + one-click opt-in, never auto-fetch).
- **NETWORK MODE first-class (maintainer-ruled 2026-06-11, SHIPPED same day):**
  the kill switch is now a top-bar ▶ Online / ⏸ Offline play-pause button —
  never buried in a sub-tab. Loud-but-beautiful state: pulsing red button,
  red top-bar underline, radial flash on toggle; honest toast ("one in-flight
  request may finish" — an open socket can't be un-sent, which is why it
  isn't strictly instantaneous; new requests refuse immediately). Endpoints
  GET/POST /api/system/network; state synced via the 5s vitals poll. Also
  FIXED: process CPU% was PER-CORE (psutil) and read higher than the whole
  OS — now normalized by core count (cpu_cores reported). btop (maintainer
  asked): Apache-2.0, GPLv3-compatible one-way, but unnecessary — it's a
  C++ TUI binary, and our bug was normalization, not the data source.
- **Task manager view (maintainer-ruled 2026-06-11, ELEVATES the download
  manager):** the vitals panel becomes minimized-but-visible animated main
  indicators; CLICK opens a dedicated window/tab — an OS-style task manager:
  what scrapes next, wiki-dump progress, queued jobs with tweak/cancel/
  reorder, organized in tabs if dense. Build together with the queue/
  prioritize/cancel arbitration below (one system).
- **Download manager + user arbitration (maintainer-ruled 2026-06-10, the
  live-test "load indices while scraping" confusion):** every network task
  (scrape pass, indices refresh, markets load, wiki track, offline-wiki dump)
  must be a VISIBLE JOB. When a new fetch action is requested while another
  runs, ASK the user: queue it / prioritize it / cancel the running one — never
  silently swallow the click. A DEDICATED downloads view (own tab/popup, like
  /investigate) shows: running job + progress, the queue (reorderable), done/
  failed history; what downloads NOW and NEXT must always be obvious. The
  activity panel (below) is the quick-glance surface; it links to the full view.
- **Activity chip → Collection activity panel (maintainer-ruled 2026-06-10):**
  clicking the top-bar "Collecting…" chip must open a DETAILED collection view,
  not hardware vitals: live scrape progress (sources done/total, current host
  as DOMAIN ONLY — never full URLs), schedule state + next run, upcoming
  targets (domain chips), honest theoretical pass-time estimates (sources ×
  politeness delays × last-run pages/source, method stated), and — now known
  possible — discrete per-source ↓ rates measured from the fetcher's own
  responses (bytes/duration per request; not OS counters). Hardware vitals
  stay: the persistent #vitals-mini strip (invariant #4) + a compact row at
  the panel's bottom. Beautiful, intuitive, no URL dumps.
- **Units/precision principle (maintainer-ruled 2026-06-10, apply APP-WIDE):**
  never print raw float tails ("3654.015384615385 USD/t" with a two-digit
  evolution next to it). One shared smart formatter: sensible significant
  digits scaled to the magnitude (e.g. 3 654.0, 111.6, 13 483.8), unit-aware.
  Sweep every surface that prints numbers.
  **PLUS (ruled same day): the entire app prioritizes scientific/SI metric
  units** — never imperial (no pounds, inches, ounces, °F, miles). Where a
  data source reports imperial, convert to SI for display and keep the
  original in the provenance/metadata.
- **Tag-driven corpora** (maintainer): multi-tag selection in Sources (selected
  tags change colour; AND-combination) and a "make this selection a corpus"
  flow -- per-corpus article counts, keyword trends, analyses.
- **Commodities depth**: 1-month windows say "not enough points" (fix window/
  interpolation honesty); S&P500 is an INDEX not a commodity (reclassify);
  expand feeds: rare earths, oil, natural gas, LNG, sand, corn/cereals, sugar.
- **Library tab**: anchor should be #library not #database; drop the Refresh
  button if data is live; country data must be stored ISO-2 and DISPLAYED as
  full names via one conversion (US=1553 vs "United States"=210 split shows
  mixed encodings today).
- **SQLCipher at-rest encryption — RULED GO (maintainer 2026-06-10): next
  MAJOR batch, do first in a fresh session (crypto deserves full attention,
  not a session tail).** Design agreed in chat: sqlcipher3 driver + SQLAlchemy
  engine key wiring (PRAGMA key on connect); passphrase asked ELEGANTLY in the
  installer GUI (whiptail box + plain-prompt fallback, confirm twice, honest
  'lost passphrase = lost corpus' warning, optional skip = plaintext with
  stated risk); launcher prompts for the passphrase at start (env
  OO_DB_PASSPHRASE for scripted runs); one-way migration tool for existing
  plaintext DBs (sqlcipher_export, snapshot first, never destructive);
  doctor attests encryption state; threat model documented (protects a
  seized/off machine, NOT a compromised session). Design TOGETHER with the
  backup redesign below — one coherent key story.
- **Backup redesign** (maintainer, ruled): encryption is the DEFAULT flow
  (Download backup -> passphrase -> download; Browse -> passphrase -> restore);
  restore must be NON-DESTRUCTIVE (merge, never replace) with bit-level
  duplicate detection (byte/hash comparison, no offline DB tweaking), and each
  article carries content hash + an authentication hash (second integrity
  level proving no tampering). Big feature -- design before code.
- **Custody tab UX**: most users won't get it -- rename/explain/guided steps.
- Offline LLM kit (RM-08 release artifact). DuckDuckGo discovery channel only
  after RM-03 gate UX proves out.
- **Diagnostics channel — THREE logs shipped (2026-06-10):** Settings → Data &
  backup offers (1) the keyword log, (2) the NETWORK log (`/api/diagnostics/
  network`: every robots + reachability verdict for default sources, market
  feeds and calendar feeds — `data/feed_preflight.jsonl` is written ONCE
  before the first scrape, robots per distinct host + 3-feeds-per-provider
  sample; full coverage via the Agenda directory's "Verify next 25"), and
  (3) the DEBUG BUNDLE (`/api/diagnostics/debug-bundle`: runtime facts,
  corpus shape, scheduler history, network verdicts, per-click import
  outcomes from `data/import_results.jsonl`, law/wiki tracking states, and
  the rolling WARNING+ error log `data/app_errors.jsonl` installed at app
  startup, self-healing). Maintainer's protocol: click through the app, send
  the bundle. NEVER auto-transmitted; on-click only.
- **Temporal map is PRECONFIGURED (shipped 2026-06-10):** the public-domain
  Natural Earth coastline outline (64 KB, 121 rings) is now BUNDLED as
  `src/static/world_outline.json` — the map renders real coastlines out of
  the box, no download at install; invariant-tested. (The maintainer saw
  dots-only because the asset previously required a manual build step.)
- **Trans-language keyword equivalence (maintainer 2026-06-10, groundwork
  SHIPPED):** language signatures (distinct articles per ARTICLE language) now
  ride every keyword in the diagnostics log — the disambiguation evidence for
  hand/main rings; `configs/keyword_equivalents.yml` holds language-qualified
  curated rings (fr:main ≠ en:main, reasoning notes). NEXT: build rings from
  the maintainer's first log batch; then the trans-language family layer.
  **ELEVATED (maintainer 2026-06-10): rings feed the LIVE analytics, not just
  display** — équivalents merge inside grouped trends/trending/associations/
  graph levels, so fr:élections + en:elections count as ONE concept; the
  cross-country recognition case ("country A discusses country B's
  elections") is served by splitting a ring's trend per source country/
  language (mentions carry both). Guards stay: only language-qualified
  members merge, a keyword joins a ring only when its language signature
  supports it (dominant-language threshold, else flagged ambiguous +
  unmerged), per-language counts always visible, user can split any ring.
  Design in FUTURE_DEVELOPMENTS.
- **Keyword diagnostics log — SHIPPED first slice (2026-06-10, maintainer asked):**
  Settings → Data & backup → "Diagnostics log" downloads
  `GET /api/diagnostics/keywords` (oo-export-1 envelope: all keywords with real
  counts + hidden flag, computed families, merge/split overrides, supergroups,
  corpus header; on-demand only, bounded at 5000). Future slices: other agreed
  back-end syntheses (the maintainer↔assistant channel) — design in
  FUTURE_DEVELOPMENTS.
- **Evidence-tiered cards — RULED GO (2026-06-10); slice 1 SHIPPED same day.**
  Maintainer requirements: every "Why am I seeing this?" leads with a PLAIN-
  ENGLISH sentence for non-math readers, the exact equations beneath — and it
  must be properly translated throughout the UI. Shipped: `Card.trigger`
  ({plain, math:[{label,value}]}; plain + labels are CONSTANT strings so the
  exact-match i18n engine translates them; values are numbers/symbols only),
  `src/signals/intervals.py` (closed-form Wilson + Katz 95% CIs, no scipy),
  trending() returns scan size, 7 producers instrumented (rising/diet/coverage/
  capacity/stale/echo/lonely), `<details class="why">` rendering, invariant #9.
  Remaining slices: instrument the other 9+recipe producers; corpus tier header
  (early/developing/established); power-style "what's missing"; BH-FDR later.
- **i18n chrome audit (maintainer live-test 2026-06-10, French paste):**
  `scripts/i18n_report.py --audit-chrome` extracts every UI text node/attribute
  and diffs vs en.json — the gap is now a NUMBER (was 503; 206 keys at 100%
  ×12 after the priority batch; 473 in the long tail, many are fragments split
  by inline markup). Keep translating in batches each session until ~0; never
  add chrome without locale keys (ritual).
- **Translated documentation (ruled 2026-06-10): SHIPPED infrastructure.**
  `docs/i18n/<lang>/<FILE>.md` served by `/api/docs/{slug}?lang=` (validated,
  no traversal; X-OO-Doc-Lang header), reader auto-requests the UI language and
  shows the honest "machine-drafted — English is authoritative" banner;
  `scripts/translate_docs.py` drafts all docs ×11 langs with the LOCAL Ollama
  (chunked by headings, provenance banner, resumable). French QUICKSTART is a
  hand-seeded full translation. TODO: run the drafting tool on a machine with
  a model to fill the other languages/docs; users perfect via PRs.
- **Parked for 0.0.9 (ruled 2026-06-10):** space-time layers 3+4 from the
  PR #51 design — convergence detection (space-time co-occurrence, never
  causation) + the user-defined "if-this-then-WATCH" alert engine (explainable,
  off by default, local-only). Also still designed-only from the docs PRs:
  event-family merge/split UI (#53), saved-filter "smart calendars" (#50),
  offline vector map, Wikipedia-as-a-source, two-hop keyword graphs (#43),
  autonomous onboarding track (#49). All recorded in FUTURE_DEVELOPMENTS.
