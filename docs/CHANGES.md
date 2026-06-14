# Changelog

> The repository’s **default branch is the active cycle branch** (currently `0.09`); each cycle branch `0.0N` produces release `0.0.N`.

## 0.09 — deeper sense-making (in progress)

The `0.09` cycle is open (the `0.08` cycle below shipped in full, including the
June 2026 live-test hardening batches). On its slate, from the parked queue:
space-time convergence detection + the watch-rule attention engine, SQLCipher
at-rest encryption with the backup redesign, the corpora system (hand- and
tag-selected), the global-search rework, agenda calendar views + catalog depth,
and the i18n long tail. See [`docs/FUTURE_DEVELOPMENTS.md`](FUTURE_DEVELOPMENTS.md).

- **Restore is now ADDITIVE-ONLY — the destructive replace path is gone.** A
  journalist's corpus is evidence; a restore must never overwrite it (maintainer
  ruling 2026-06-13). The two destructive "replace the live database" restore
  paths — `POST /api/database/restore` and `POST /api/safety/restore/encrypted`,
  both via `restore_from_bytes` (which did an `os.replace` of the live file) —
  have been **removed entirely** (not merely demoted), along with the functions
  behind them (`restore_from_bytes`, `restore_encrypted_backup`). The **merge
  engine is now the ONLY restore** (`/api/backup/v2/restore/{preview,commit}`):
  it complements the corpus duplicate-lessly, keeps your local version on a
  conflict, and can refuse — but never replaces. The legacy "Restore
  (destructive)" buttons and their "replaces the current corpus" wording are
  retired from Settings (backup *creation* — the raw `.db` and encrypted
  snapshot downloads — stays). A new guard test
  (`tests/test_additive_restore_only.py`) fails the build if any replace-restore
  endpoint or function ever reappears, so the guarantee can't silently regress.
  The torture suite (SIGKILL-mid-merge, atomic swap, crown no-silent-decrypt) is
  unchanged and green — the merge restore it covers is untouched.

- **Downloaded Wikipedia dumps can feed the corpus (the living-source path).**
  Until now a downloaded multistream dump could be *read* one page at a time but
  never *entered the corpus*. `ingest_dump_pages(wiki, titles)` (and the
  `POST /api/wiki/dumps/corpus-ingest` endpoint) now read a **bounded,
  operator-chosen list of titles** from the local dump (offline — no network) and
  upsert each as a corpus article through the **same `index_article` hook** the
  watched-page sync uses (keywords + When×Where×Who follow). Articles are keyed
  on the canonical wiki URL, so a page ingested from a dump and later refreshed by
  the live tracker update the **same row** — no duplicate; per-edition source
  (`Wikipedia (xx)`, `xx.wikipedia.org`) keeps them filterable. The shared upsert
  is factored out of the watched-page sync (`upsert_wiki_corpus_article`), so both
  paths are identical by construction. The list is bounded on purpose — a full
  edition is millions of pages, so whole-dump streaming stays a later slice; honest
  per-title reasons (`no-multistream-dump`, `title-not-in-index`) come straight from
  the reader. `tests/test_dump_corpus.py` builds a tiny, format-faithful dump and
  proves create / idempotent-unchanged / honest-skip.

- **The Back button navigates tabs instead of escaping to the passphrase
  screen.** Tab switching used `history.replaceState`, so it left no history
  entries; and a locked API response did `location.href = "/unlock"`. The only
  prior entry was therefore `/unlock`, so the browser Back button landed the user
  on the passphrase screen. Now each user tab-switch **pushes** a history entry
  (a `popstate` handler re-renders the tab on Back/Forward; the initial load
  still *replaces*, so the first tab isn't a dead Back), and every hop to/from
  `/unlock` uses `location.replace` — the locked redirect and the post-unlock
  return both replace — so the unlock screen never sits in the back stack.
  `tests/test_back_button_nav.py` pins the contract.

- **Corpus-wide WHO: people & organisations across the whole corpus.** The
  When/Where/Who substrate (T12) persists the deduced people and organisations
  per article; a new aggregation now rolls them up to the **whole corpus** —
  `GET /api/insights/who` (and `queries.who_aggregate`) returns the most-seen
  names with **honest counts only**: distinct-article **spread** and summed
  in-text **mentions**, ordered by spread. Filterable by class
  (`person` | `organization`), by window (`days`), and by `country`; `min_articles`
  hides one-offs; `coverage_articles` states the denominator (how many articles
  carry any who-extraction at all). There is **no score** — names are lexical
  surface forms the extractor does **not** disambiguate (same-name people merge;
  a name is not a confirmed identity), so every figure ships with a `method`
  string and the standing caveat *"Deduced from text, never confirmed."* This is
  the ruled corpus-wide WHO aggregation remainder of When/Where/Who.
  `tests/test_who_aggregate.py` proves the counts, ordering, class/window/country
  filters, the `min_articles` HAVING, and the honesty (no score, method+caveat).

- **Parallel collection: fetch many hosts at once, politely; write serially.**
  The collect pass can now fetch **different hosts concurrently** via a bounded
  worker pool (`collect_parallelism`, default **1 = sequential, unchanged**;
  raise it to opt in). This is the remaining half of the Tor speedup (parallel
  *dumps* shipped earlier): N concurrent fetches over Tor = N circuits = aggregate
  throughput multiplies — and it composes with per-host stream isolation so each
  concurrent host is on its **own circuit**. The binding guardrail holds by
  construction: the `EthicalFetcher` now takes a **per-host lock** around the
  robots check + rate-limit + GET + body read, so **one host is hit by at most
  one request at a time** (politeness is never traded for speed) while different
  hosts run in parallel. Writes stay safe — each worker uses its **own** DB
  session and writes **serialise through the single-writer gate**, so "parallel
  fetch, serial write" is achieved without a separate writer thread; aggregation
  runs on the consuming thread (no shared-counter races). Kept **opt-in (default
  1)** until field-validated; the task manager will tune it. Exposed in the
  scheduler config API. `tests/test_parallel_collect.py` proves same-host
  serialisation (the politeness guarantee), different-host concurrency, that the
  pool covers every source, and the setting round-trip.

- **Per-host Tor stream isolation: each source rides its own circuit.** Over a
  SOCKS (Tor) proxy, the `EthicalFetcher` now gives **each host its own Tor
  circuit** — a per-host SOCKS username triggers Tor's `IsolateSOCKSAuth`, the
  same primitive the parallel dump downloads use (#110), now applied to ordinary
  collection. This is the safe answer to "protect the user from other sources":
  no exit node or circuit observer can link the user's activity **across**
  different sources, and it needs **no clearnet exposure** (it's Tor Browser's
  "isolate by first-party domain" model). A host's page fetch **and** its
  `robots.txt` share that host's circuit, so the isolation is complete (robots
  is never leaked onto a shared base circuit). It's automatic and on by default
  when a SOCKS proxy is configured (`OO_TOR_STREAM_ISOLATION=0` disables it), and
  a **no-op** for an HTTP proxy or no proxy — the isolation is computed once from
  the *original* host so every redirect hop stays on the one circuit. No new
  anonymity is claimed; this only compartmentalises what the user's proxy already
  provides. The complementary clearnet-for-Tor-hostile-sources hybrid stays an
  explicit, consented, per-source choice (never automatic) — see
  `FUTURE_DEVELOPMENTS.md` → "Reliable Tor & per-source transport".
  `tests/test_tor_stream_isolation.py` proves per-host circuits, distinct
  circuits per host, the robots+page sharing, and the disabled/non-SOCKS no-ops.

- **The single-writer gate: writers serialise, so two never collide on the
  SQLite lock (keystone #1).** The store is single-writer by design, but two
  *writers* still race at the SQLite layer, and a long collection pass could
  hold the writer past `busy_timeout` — the loser then raised "database is
  locked" and historically discarded fetched data (the field-log copper/nickel
  loss; `run_write_with_retry` was the surgical band-aid). The proper fix is now
  in place: a process-wide, reentrant write gate (`src/database/writer.py`)
  through which every write queues *in Python* — only one thread is ever inside
  a write transaction, so SQLite never sees two concurrent writers and the
  timeout never fires. It is wired automatically via SQLAlchemy session events
  (acquire on a session's first `flush`, release on `commit`/`rollback`), so the
  ORM write paths — ingest, markets, wiki, law, the API write endpoints — need
  **no call-site change**; the handful of raw-SQL writes that bypass the ORM
  (VACUUM) take the gate explicitly. The gate is reentrant (a thread can hold it
  across nested sessions), observable (honest `grants`/`contended`/wait-time
  counters that will feed the task-manager System view), SQLite-only (a server
  PostgreSQL backend keeps its own MVCC), and disableable via `OO_WRITE_GATE=0`
  as a field escape hatch. Readers are untouched — a read-only transaction never
  takes the gate, so WAL concurrency is preserved. This supersedes the retry as
  the primary mechanism (the retry stays as defense-in-depth) and is the
  prerequisite for safe **parallel collection** (parallel fetch, serial write).
  New `tests/test_write_gate.py` proves the contract and that six threads
  writing a real file-backed store concurrently never lock and are serialised.

- **Collection efficiency & honesty from the field log (RSS conditional GET +
  discovery commerce filter).** Two fixes from the 2026-06-13 field analysis:
  - **RSS conditional GET (finding F).** At 1-minute collection intervals ~93%
    of feed items were duplicates — the feeds had not changed, yet each was
    re-downloaded and re-parsed every pass. The fetcher now sends
    `If-None-Match` / `If-Modified-Since` (from per-feed validators) and treats
    **`304 Not Modified` as a valid result** (empty body, not a `FetchError`);
    `ingest_source` stores the `ETag`/`Last-Modified` per feed in a new
    `feed_fetch_state` table and **skips parsing entirely on a 304**. The table
    is separate from `sources` on purpose — `create_all` materialises a missing
    *table* on every existing database at boot, so there is no ADD COLUMN
    migration to run and no "no such column" risk in the collection hot path
    (validators are opaque HTTP tokens, stored and echoed verbatim, never
    parsed). Backward compatible: a plain fetch sends no conditional headers and
    behaves exactly as before. (Per-feed *backoff* for feeds that never send an
    ETag is deferred to the continuous-collection batch, where the scheduling
    lives.)
  - **Discovery no longer suggests storefronts (finding D).** Citation discovery
    had surfaced `shop.popsci.com`, `store.popsci.com` and
    `popularscienceprints.com` — merch, not journalism. A conservative,
    explainable filter (`is_commerce_domain`) drops candidates with a leftmost
    `shop.`/`store.`/`buy.` label, a `.shop`/`.store` commercial gTLD, or a
    `…prints` name. Discovery candidates are never auto-enabled, so the only
    cost of a rare false positive is one un-suggested domain.

- **Continuous collection + airplane-mode boot + per-country fair ordering
  (content-first, the field-test "scraping stopped" fix).** Three linked changes
  realise the maintainer's ruling that *"scraping should never stop"* and the app
  should *"boot offline, then collect continuously once the operator says go"*:
  - **The app now boots in AIRPLANE MODE (offline) every time** — startup engages
    the offline state explicitly, so nothing scrapes until the operator crosses
    online once (the one consent, `POST /api/scheduler/start`). Zero-network boot
    was already a non-negotiable; it is now *explicit and visible* in the airplane
    toggle. The old "autostart at boot" is retired by this ruling (boot is always
    offline). Gated by `OO_NO_SCHEDULER`, so tests/headless setups are untouched.
  - **When online, collection is CONTINUOUS.** The scheduler no longer runs one
    pass and then idles `interval_minutes` (which is exactly why a field tester
    saw scraping "stop" — it was idling, not crashing). With `continuous=true`
    (the new default) passes run back-to-back with only a short, interruptible
    gap, so while online the corpus fills permanently. `continuous=false` restores
    the old run-once-then-wait cadence.
  - **Per-country round-robin ordering** (`round_robin_interleave`) reorders each
    pass so every country gets a turn before any country gets a second — one
    source per country, then repeat. This breaks the US-volume bias *structurally*
    (equal turns per country, not turns proportional to how many sources a country
    has). Within-country order is preserved; sources without a country share one
    bucket; nothing is ever dropped. The activity/plan preview reflects this order
    honestly. (Parallel fetch, the onboarding country/language picker, and demoting
    the cross-kind arbitration modal to a silent queue are the next Group-B slices.)

- **Parallel, circuit-isolated dump downloads (the Tor speed fix for dumps).**
  Dump downloads ran strictly one at a time (`max_concurrent = 1`), so over Tor
  a single slow circuit was the ceiling — 56K-modem speeds. Now up to
  `max_concurrent` dumps download **in parallel** (default 3, env-tunable via
  `OO_DUMP_CONCURRENCY`); dumps write files, not the DB, so there's no
  single-writer contention. Crucially, each download carries a **per-stream
  SOCKS token** (its URL), so Tor's `IsolateSOCKSAuth` gives each its own
  circuit instead of sharing one — aggregate throughput actually multiplies.
  The T9 reorderable queue is **preserved**: when more dumps are requested than
  the capacity, the excess queues and stays prioritisable (fr-before-en still
  works). Slot accounting is race-safe (a slot is claimed under the lock before
  launch), and a stale `downloading` status from a killed process is demoted to
  `paused` (resumable) on reload. Bounded + conservative because dumps share one
  host — per-host politeness is never traded for speed.

- **No per-run source cap — collection covers EVERY source.** The scheduler
  capped each pass at `max_sources_per_run` (clamped 1–1000), which silently
  *selected* which sources to skip — a selection that can't be justified
  (maintainer 2026-06-13). The cap now defaults to **0 = unbounded**: rss/crawl
  passes, market rules, and watched wiki/law items all cover everything, every
  pass; a positive value is still honoured as an explicit soft cap. The
  "Max sources / run" control is removed from the UI. (Ordering still decides
  what runs *first* — the bandwidth priority ladder — but nothing is excluded.)
  Implemented via a shared `capped()` guard (`src/database/query.py`) because
  SQLite `LIMIT 0` returns nothing, the opposite of "no limit".

- **One guarded socket factory: the kill switch and proxy now cover every
  fetch path (closes a transport leak).** Four paths — Wikipedia dump
  downloads, the MediaWiki API client, ORES scoring, and the gated DuckDuckGo
  discovery — built their own bare `requests` sessions, so **airplane mode did
  not stop them** and, worse, the in-app proxy was **not applied**: a user who
  set Tor only in the app (not the OS) would have had multi-GB dump downloads
  egress over **clearnet** — a silent transport downgrade the project forbids.
  They now all route through `src.safety.fetcher.guarded_session`, a
  `requests.Session` subclass that checks the global kill switch on **every**
  verb (so it cannot be forgotten) and applies the protected-mode proxy. The
  stale hardcoded `OpenOmniscienceBot/0.4` User-Agent is replaced by the honest
  version from pyproject (Wikimedia's API mandates a descriptive bot UA, kept
  even over Tor; the DuckDuckGo HTML endpoint keeps its browser UA). The
  socket-importer ratchet allowlist shrinks **6 → 3** (only the EthicalFetcher,
  loopback Ollama, and the factory itself may import an HTTP client now).
  New `tests/test_guarded_session.py` pins the three guarantees and proves all
  four consumers are wired through the factory.

- **No fetched data is lost to a transient database lock.** A field session
  (2026-06-13) caught commodity prices that were **fetched successfully over
  Tor and then discarded** — copper, aluminum, nickel, zinc all stored with
  `OperationalError: database is locked` because the import's commit lost the
  single-writer race against a long-running collection pass (which can hold the
  writer past the 30 s `busy_timeout`), and the import gave up on the first
  error. The write is now wrapped in `run_write_with_retry`
  (`src/database/write.py`): on a transient lock it rolls back and re-runs the
  idempotent unit of work with exponential backoff + jitter, so the points
  persist instead of vanishing. Non-lock errors still surface immediately;
  this is the safety net ahead of the single-writer queue that will remove the
  contention entirely.

- **CI made deterministically green again (pinned tools + real fixes).** Two
  unpinned linters had drifted and were reddening **every** PR with no code
  change, each masking the next:
  - **mypy** (unpinned floor) reported one extra error (129 > 128). Pinned to
    `mypy==2.1.0`; baseline lowered to **127** after fixing the two genuine
    latent bugs the type errors flagged — the HTTP 429 handler read
    `exc.retry_after`, absent on slowapi's `RateLimitExceeded` (the handler
    meant to degrade gracefully would itself raise `AttributeError`), and an
    article metadata row called `html.escape()` on a possibly-`None` region.
  - **bandit** (unpinned) then failed on `B314`: `src/wiki/dumpread.py` parsed
    Wikipedia dump XML with the stdlib parser, vulnerable to entity-expansion /
    XXE attacks. Fixed for real — the dump (untrusted network input) is now
    parsed with **`defusedxml`** (a genuine defense, not a suppressed warning),
    and bandit is pinned (`bandit==1.9.4`).

- **Installer: the passphrase moment, fixed live.** The one-line
  `curl | bash` install crashed at "Initialising the database" on a fresh
  machine — encryption-by-default means a new store NEEDS the user's
  passphrase choice, which a blind non-interactive init cannot make. The
  installer now: tries env-driven init first (existing stores,
  `OO_DB_PLAINTEXT`/`OO_DB_PASSPHRASE`); otherwise **asks on a real
  terminal** (reading `/dev/tty`, so it works under `curl | bash`):
  encrypted with confirm-twice, the honest no-recovery warning and length
  guidance, or plaintext behind a typed `PLAINTEXT` confirmation with the
  risk stated, or defer; with no terminal it **defers honestly to the
  in-app first-launch prompt** — starter sources seed themselves at the
  first unlocked boot, so nothing is lost. Never a traceback, never a
  silent default.

- **V0.1 alpha preparation: the reflective plans (docs).** Two
  maintainer-commissioned analyses landed: **user-centric reflections**
  (FUTURE_DEVELOPMENTS — six personas, six contradictions faced honestly,
  deduced features A1–A9 with the Claim Workspace as flagship: a guided
  evidence-trail pipeline answering "is this true?" without ever issuing a
  verdict) and the **transversal audit 07**
  (`docs/audit/07_TRANSVERSAL_AUDIT_V01.md` — tool-by-tool science/truth/
  disclosure table, tamperability incl. source-side cloaking, long-use
  performance unknowns, ranked missing sources, neutrality as
  representation-vs-declared-baselines, ten named aggregator biases and
  which updates can fix, steps B0–B7). Plus the recorded superseding
  Wikipedia ruling: edition-wide automatic tracking after a dump download
  (per-article tracking to be retired) — design + filed questions, not yet
  implemented, per instruction.

- **Wikipedia pages become first-class corpus articles (the living-source
  bridge, maintainer-ruled 2026-06-12).** Watched pages now enter THE corpus:
  one article per page (canonical wiki URL) under a per-edition "Wikipedia
  (xx)" source, carrying the **newest version** of the text — the tracker
  refreshes `latest_text` (+ the revid it corresponds to) whenever edits
  land, and the corpus row re-indexes idempotently through the one
  `index_article` hook, so **general full-text search, the keyword
  aggregator and When×Where×Who all follow the latest version
  automatically**. Wikitext is reduced to plain text by a bounded, stated
  lexical strip. `POST /api/wiki/corpus/sync` backfills existing watchlists
  locally (zero network). Migration `b6c7d8e9f0a1`. Honest gap recorded as
  now-blocking for the full version engine: stored revision diffs are
  truncated summaries, not reconstructable patches — the per-revision
  storage decision (full text vs patches+checkpoints) is elevated in
  FUTURE_DEVELOPMENTS, and the dedicated tracked-changes tab is the named
  next slice.

- **Local-first link previews on Home cards (T16 slice 1 — invariant #6
  extended, first target).** External evidence links on Home cards no longer
  jump straight out: they open a **local preview** first — what your database
  already knows about the URL (known source, a stored local copy with the
  reader link, how many of your own articles cite it with examples, tracked
  law/Wikipedia matches, the local copy's top keywords) — built from local
  reads only and saying so. The outbound anchor's **visible text is the full
  URL**, and clicking it still passes the external-link confirmation popup
  (layered consent). Enforced in the invariants suite (#6e). +12 chrome
  strings ×12 locales.

- **Offline dump reader (T14 slice 1) + the ruled dump-list limit.** New
  Wikipedia dump downloads default to the **multistream** form and its tiny
  companion index rides along automatically — that pair is what makes a
  downloaded dump *readable*: Settings → Wikipedia gains **"Read a page from
  a downloaded dump"**, which scans the index for the title, decompresses one
  small block at its byte offset, and shows the page's raw wikitext entirely
  on this machine (zero network; scan stats shown; a case-insensitive match
  is offered and labelled; legacy single-stream files are honestly reported
  as non-seekable with a re-download hint). The dump-download language list
  is now **limited to the app's languages** (the 12 UI locales + the
  stoplist-evidenced corpus languages) per the maintainer ruling — the
  watched-pages edition picker keeps the full curated list. +17 chrome
  strings ×12 locales; 9 new tests against a format-faithful synthetic
  multistream dump built in-test.

- **The omnibar (T13 slice 1).** The Ctrl/⌘-K command palette now federates
  over the corpus itself: `/api/search/omni` serves the first three hits per
  group — articles (FTS5, relevance-ordered), keywords (indexed prefix),
  sources, watched Wikipedia pages, tracked law documents — **with the true
  totals disclosed in each group header** (the display bound never hides the
  magnitude). Index-backed only, never scan-on-type; a half-typed Boolean
  ("drought AND") falls back to a phrase match instead of erroring
  mid-keystroke. Article hits open the LOCAL reader first; keyword hits open
  their corpus window; "Run the full Boolean search" hands off to the Search
  tab prefilled — nothing the Search tab does is lost. A discreet Boolean
  reminder sits at the palette's foot (hover carries the long form). +8
  chrome strings ×12.

- **Weather corroboration cards — "if this, then SUGGEST user to fetch"
  (maintainer-asked 2026-06-12).** When ≥3 collected articles mention the same
  climate-event word (curated 12-language seed vocabulary,
  `configs/corroboration_rules.yml`, provenance in-file) together with the same
  deduced place inside one time window, a Home card in the *investigate* bucket
  OFFERS an independent check — it is computed locally and states "this card
  made no network call". The fetch is one bounded (place, window) Open-Meteo
  ERA5 reanalysis slice (`POST /api/weather/context`), triggered only from the
  card's button behind the one consent popup, through the single ethical fetch
  path (kill switch, robots fail-closed, protected-mode proxy inherited);
  results render one chart per variable (mixed units on one axis would be a
  fabricated comparison) with CC BY 4.0 attribution, the
  reanalysis-not-station-truth note and the disk cache disclosed; transport
  failures return the honest verdict taxonomy. +7 chrome strings ×12 locales.
  Slice 1 of the Open-Meteo layer (see FUTURE_DEVELOPMENTS). Alongside it, the
  **Open Commons Mirror sister project** (server-scale open-data preservation,
  the "reliable memory" pillar — tamper-evident by hashes and transparency
  logs, tamper-resistant by independent replication) is recorded as a designed
  concept with the maintainer's intent and open questions.

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

- **Agenda astronomy layer (T11 slice 1).** Full and new moons computed
  **locally** with the standard Meeus algorithm (ch. 49, periodic + planetary
  corrections) — zero network, zero data files — and **verified against gold
  references in the test suite**: the book's own worked example (49.a, the
  February 1977 new moon) to within ~26 seconds, and the published 2024
  almanac full-moon dates. `/api/events/astronomy?year=` serves the phases
  with `method` and `accuracy` fields (ΔT non-application stated, never
  hidden); the agenda month grid shows moon glyphs whose hover bubble carries
  the method — informed consent down to the moon. +2 chrome strings ×12.

- **When×Where×Who persists at ingest (T12, the convergence substrate).**
  The date/place/entity extractors — reader-only until now — persist their
  deduced candidates **at indexing time** through the one `index_article`
  hook, so live ingest, re-index and backfill all anchor them: new
  `article_mentioned_places` and `article_entities` tables (people and
  organizations separate by design), every row carrying **snippet provenance
  and the rule note** that decided it, idempotent per article, and a
  deduction failure never blocks keyword indexing (tested). Deduced stays
  labelled deduced — never promoted to fact.

- **Seasons + the climate record (T11 slice 2).** Equinoxes and solstices
  computed locally (Meeus ch. 27, verified against the book's example 27.a
  to ~9 s and the published 2024 dates) with **hemisphere-honest naming** —
  "June solstice", never "summer solstice": seasons are opposite across
  hemispheres and undefined at the equator, and the payload says so. The
  bundled **El Niño episode dataset** (`/api/events/climate`) follows the
  NOAA CPC ONI convention with per-file provenance and an explicit
  **verification-pending flag** — drafted entries are never presented as
  verified before the clearnet check. IPCC-as-a-source with
  prediction-tracking ("were their anticipations right after all?") and
  agenda↔Wikipedia linking recorded as designed concepts with filed
  questions.

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

- **The corpora system, slice 1 — the Links substrate + the window.** A
  keyword now opens as a **corpus window** (⊞ Corpus next to the resolved
  term): Trend (the interactive toolkit), member Articles, and **Links** —
  the anti-false-triangulation view: which member articles **share outbound
  links**, with per-URL independence notes ("a shared origin means agreement
  is ONE path, not independent confirmation") and distinct-source counts.
  `/api/links/shared` serves counts and structure only, never a credibility
  verdict; the method travels in the response. +12 chrome strings ×12.

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
