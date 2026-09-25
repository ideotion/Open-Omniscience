# Security

## Model

Open Omniscience targets a **single local user** on a **Qubes OS Debian AppVM**:

- Binds to **127.0.0.1 only** (loopback). It must never be exposed on a network
  interface; there is intentionally no authentication/RBAC for this deployment.
- **No telemetry. No data leaves the machine.** LLM inference is local (Ollama, HTTP).
- **Article collection** goes through the single ethical fetcher and nothing else:
  robots.txt is honoured and **fail-closed** (if it can't be confirmed, the URL is not
  fetched), per-host rate-limited, identifying User-Agent. As of the v0.0.7 audit
  (finding ETH-01) this includes RSS-feed **discovery** — same fetcher, same guards.
  *Outside* collection the app can also reach the endpoints enumerated below; three of
  them do not use the ethical fetcher and each says so on its own row. **That table is
  the complete answer to "what can this app contact"** — it is derived from the tree by
  a sweep a repo test re-runs, not from anyone's memory.
- **One documented exception, now opt-in** (audit finding ETH-02, gated in 0.0.8 per
  RM-03): *Discover by topic* sends your topic query to **DuckDuckGo** (an external
  service) to find candidate outlets. It is **disabled by default** — the endpoint
  refuses with an honest message until you knowingly enable it in **Settings → Advanced → Safety →
  External topic discovery**, which states plainly that the query leaves your machine
  (`OO_DISCOVERY_EXTERNAL=1` for headless use). It is strictly user-triggered — never
  part of ingestion, the scheduler, or any default path. (The browser-rendered `/docs` Swagger page also
  references a CDN for its own assets; the app itself never fetches it.)
- **Every other outbound call is consented and off the default/boot path.** Some are a
  click; several are **ride-alongs that run inside an online collect pass you started**,
  each named below with its own opt-out (or with the honest note that it has none yet).
  The table is the **full set of endpoints the app can reach**, grouped by lane, derived
  from the tree rather than from memory — the sweep that produced it is quoted under *How
  this list is kept true*. Every PR that adds a host adds it **here and to the consent
  popup's hover in the same diff**; `tests/test_security_endpoint_enumeration.py` fails
  otherwise. Last checked **2026-09-16**.

  **One consent, many hosts.** Every offline→online transition passes the ONE consent
  popup (`ensureOnline`, UI invariant #14), whose hover lists exactly the hosts below,
  per lane, so that single decision is an informed one. Every row is gated by the airplane
  kill switch, which is enforced **process-wide at the socket level** — not only inside the
  fetcher — so a row that bypasses `EthicalFetcher` still cannot open a socket while
  offline.

  **Transport (Q1014).** Every row marked *ethical fetcher* goes through the ONE
  `EthicalFetcher` / `guarded_session` path: robots.txt fail-closed, per-host politeness,
  an honest bot User-Agent, bounded redirects re-validated per hop, and the connect-time
  SSRF check. With protected fetch mode on, that path carries your proxy (e.g. Tor), and
  **a lane never silently downgrades Tor → clearnet** — the fetch is refused and the
  refusal is surfaced. The three rows that do *not* use the ethical fetcher say so, and say
  what they use instead.

| Lane | Hosts it can reach | Trigger | Transport | Where in the tree |
|---|---|---|---|---|
| **Press collection** | *A class, never enumerable:* the domains of **the sources you have enabled** — **9,033 distinct hosts** across the bundled directory (`configs/sources.yml`, `configs/academic_sources.yml`, `configs/official_sources.yml`, `configs/sources_spectrum.yml`, `configs/markets_sources.yml`), plus every feed or site **you** add. A source is reached at *two* addresses: its `rss_url` when it has one, and `https://<its domain>` for the crawl and the preflight — which is why a sweep for `https://` literals alone sees only 5,425 of them, and why the guard sweeps the scheme-less `domain:` field too. The sub-rungs stay on the source's own domain: sitemap discovery, the bounded crawl rung (`crawl_per_pass`, default 3) and the archive-backfill rung (`archive_backfill_per_pass`, default 5). | The collect pass you start | ethical fetcher | `src/ingest/__init__.py:529` · `src/ingest/pipeline.py` · `src/ingest/sitemap.py` · `src/ingest/crawl.py` · `src/ingest/archive_backfill.py` · `src/ingest/seed_sources.py` · `src/ingest/crawl.py:149` and `src/monitoring/preflight.py:68` (the `https://{domain}` synthesis) |
| **Source discovery** | `query.wikidata.org` (the SPARQL endpoint), `www.wikidata.org` (the Action API, for entity enrichment) | **Ride-along, default on** — `world_discovery_per_pass` defaults to **2**; set it to `0` to stop it. Candidate *qualification* (`qualification_per_pass`, default 5) reaches the candidate's own domain, i.e. the press class. | ethical fetcher (`guarded_session`) | `src/catalog/wikidata.py:23` · `src/catalog/discover.py:40` · `src/catalog/wikidata_enrich.py:33` · `src/catalog/wikidata_apply.py` · `configs/catalog_query.yml` |
| **Wikipedia / Wikimedia** | `*.wikipedia.org` — the per-edition Action API, one host per language edition you watch — plus `stream.wikimedia.org` (EventStreams: ONE long-lived SSE connection carrying the metadata of every edit in the editions you chose, Q108) and `wikimedia.org` (the Analytics REST API's daily pageview top-1,000 per edition, Q706: one request per edition per day) — plus `ores.wikimedia.org` (revision-quality models) and `dumps.wikimedia.org` (full-edition dumps **and** the size estimate) — plus any alternate **mirror URL an operator adds** for the same artifact, which every shipped catalogue entry leaves empty | Ride-along on a collection pass while the Wikipedia lane is on (default on, Q702's NOTE; the top-bar toggle stops it) — and Click: watching a page, "Estimate size", "Download" | ethical fetcher | `src/wiki/mediawiki.py:26` · `src/wiki/client.py` · `src/wiki/stream.py:EVENTSTREAMS_URL` · `src/wiki/pageviews.py:PAGEVIEWS_HOST` · `src/wiki/ores.py:22` · `src/wiki/dumps.py:140` · `src/wiki/dumps.py:419` (the HEAD behind the estimate) |
| **Maps / OpenStreetMap** | `download.geofabrik.de` (regional extracts), `planet.openstreetmap.org` (the planet file) — plus any alternate **mirror URL an operator adds**, empty in every shipped entry | Click — starting a region or planet download | ethical fetcher | `src/geo/osm_downloads.py:61` · `src/geo/osm_downloads.py:62` · `src/geo/osm_regions.py` |
| **Law** | *A class today:* the **law authorities of the jurisdictions being tracked** — **260 distinct hosts** across `configs/legal_sources.yml` (the curated portals: `eur-lex.europa.eu`, `www.legifrance.gouv.fr`, `www.legislation.gov.uk`, `www.govinfo.gov`, `www.gesetze-im-internet.de`, `laws-lois.justice.gc.ca`, `www.un.org`, `www.wipo.int`) and `configs/legal_sources_generated.yml` (national gazettes and attorney-general chambers). Each file has two halves: its `documents:` are polled by the law tracker, least-recently-checked first, and only the ones you watch; its `sources:` are seeded into the source directory and crawled like any press source. | **Ride-along, always on.** `src/scheduler/runner.py:1250` reads an `auto_track_law` opt-out, but `SchedulerSettings` defines no such field — so the `getattr(…, True)` default always wins and **there is no way to switch it off today** (recorded 2026-09-16; the toggle is owed). | ethical fetcher | `src/law/track.py:455` · `src/scheduler/runner.py:1250` · `src/law/catalog.py` |
| **Official statistics** | `api.worldbank.org`, `ec.europa.eu` (Eurostat), `ourworldindata.org`, and any JSON-stat / PxWeb URL **you** paste in (e.g. IRENA) | Click ("Load standard country data", a figure's fetch) **and a ride-along, default on**: `country_data_per_pass` defaults to **2** and bootstraps the first load of a curated indicator in the background; set it to `0` to stop it. A figure you subscribed re-fetches from its publisher on the markets lane **only while `auto_refresh_stat_subscriptions` is on** (*Refresh the statistics I subscribed to on every pass*; off by default — before Q1020 retired the scheduler `mode`, that refresh ran only in the markets mode, and an install that was in it is migrated to on). | ethical fetcher | `src/stats/fetch.py:54` · `src/stats/fetch.py:56` · `src/stats/fetch.py:63` · `src/api/governments.py:582` · `src/scheduler/runner.py:1394` |
| **Markets & commodities** | `fred.stlouisfed.org`, `www.eia.gov`, `www.imf.org`, `www.worldbank.org` — the bundled commodity and index feed catalogs | **Ride-along, always on** — the markets rung runs on every online pass (a feed fresher than its threshold is skipped). Its budget has no toggle. **Plus the page each of *your own* price-extraction rules names**, fetched on the same lane **only while `auto_run_market_rules` is on** (*Run my price-extraction rules on every pass*; off by default — before Q1020 those rules ran only in the retired markets mode, and an install that was in it is migrated to on). | ethical fetcher | `src/markets/pipeline.py:186` · `src/markets/feed_catalog.py` · `configs/commodity_feeds.yml` · `configs/index_feeds.yml` |
| **Calendars** | The bundled directory `configs/calendar_feeds.yml`: `date.nager.at`, `www.openholidaysapi.org`, `www.officeholidays.com`, `www.calendarlabs.com`, `www.hebcal.com`, `litcal.johnromanodorazio.com`, `worldpublicholiday.com`, `fosdem.org`, `f1calendar.com`, `www.matchesio.com`, `www.rocketlaunch.live`, `pirate.monkeyness.com`, `raw.githubusercontent.com`, `jonamarkin.github.io` — plus any `.ics` URL **you** add. (Four more hosts ship in that file and are **never fetched**; they are named under the table.) | **Ride-along, always on.** `src/scheduler/runner.py:1248` reads an `auto_import_calendars` opt-out that `SchedulerSettings` likewise does not define, so it is **not switchable today** (recorded 2026-09-16). Up to five feeds per pass also have their robots verdict re-verified. | ethical fetcher | `src/events/feeds.py:40` · `src/events/feeds.py:58` · `src/scheduler/runner.py:1300` · `src/monitoring/feed_preflight.py:119` |
| **Hazard feeds** | `earthquake.usgs.gov`, `www.gdacs.org` | **Ride-along, default on, and its opt-out does not work.** `auto_track_signals` is a real `SchedulerSettings` field and `save_settings` honours it — but `SchedulerConfigUpdate`, the request model `PUT /api/scheduler/config` validates against, does not declare it, so Pydantic drops the key and the endpoint returns **200 having changed nothing**. Live-reproduced 2026-09-16. This document has named that route as the opt-out for months; it is corrected here rather than left standing | ethical fetcher | `src/api/hazards.py:27` · `src/api/hazards.py:28` · `src/scheduler/runner.py:1349` |
| **Keyword translations** | `www.wikidata.org` (the Action API: `wbsearchentities` to find one concept's item, then `wbgetentities` for that item's labels and aliases in the app's twelve languages) | Click — *Settings → Advanced → Keyword translations → Load*. Nothing schedules it and no pass rides along; **one request per 10 seconds** (R8), and the load refuses under airplane mode with a refusal that names the kill switch. The rings it writes land in this install's own ring file at the LOWEST precedence, so a hand-curated ring still wins. | ethical fetcher (`guarded_session`) | `src/analytics/wikidata_rings.py:32` · `src/analytics/ring_loader.py` · `src/api/insights.py` (`/api/insights/ring-load`) |
| **Weather** | `archive-api.open-meteo.com` | Click — "fetch" on a corroboration Lead. CC BY 4.0, disclosed at the point of use. | ethical fetcher | `src/weather/openmeteo.py:33` |
| **Discover by topic** | `html.duckduckgo.com` — and only that host; the redirector DuckDuckGo wraps its results in is unwrapped locally and never followed (see under the table) | **Opt-in, off by default** — the endpoint refuses with an honest message until you enable *Settings → Advanced → Safety → External topic discovery* (`OO_DISCOVERY_EXTERNAL=1` headless). Strictly user-triggered: never part of ingestion, the scheduler, or any default path. | ethical fetcher | `src/services/duckduckgo.py:60` · `src/services/duckduckgo.py:227` (the refusal) |
| **Local AI install & weights** | `api.github.com` (the official Ollama installer and its attested `sha256`) and the release-asset host that API names, today `objects.githubusercontent.com` — a value read from the response, not a URL we build; `huggingface.co` (vLLM model weights), `pypi.org` (installing vLLM into the managed venv) — plus whatever registry **Ollama's own daemon** contacts for a model pull (see Transport) | Click, through the **separate AI-egress consent window** — a third state in which the kill switch stays engaged, the collector stays stopped, and only the install is exempted | **Mixed.** `api.github.com` is a guarded fetch. The other three are performed by a **spawned process** — `pip`/`uv` and `huggingface_hub` — over **clearnet, not through this app's fetcher or proxy**. A model pull is a loopback `POST /api/pull` to the Ollama daemon, which then egresses on its own: this app neither builds that URL nor can name the host, and saying so is more honest than guessing one. Every `ollama.com` literal in our source is a **page we link you to**, never a page we fetch. Disclosed at the consent step. | `src/llm/installer.py:61` · `src/llm/ollama.py:751` (the loopback `POST /api/pull` that asks the daemon to fetch) · `src/llm/vllm_lifecycle.py:3321` · `src/llm/vllm_lifecycle.py:3510` · `src/llm/weights_pin.py` |
| **Newsletter mailbox** | The **mail server you configure** (IMAP/POP3) | Click — only when you trigger a pull | **Not the ethical fetcher:** raw `imaplib`/`poplib` (mail protocols have no robots.txt or HTML to parse). Its own explicit kill-switch check refuses while offline is engaged. | `src/ingest/email.py` · `POST /api/newsletters/mailbox` |
| **Chain of custody** | `a.pool.opentimestamps.org`, `b.pool.opentimestamps.org`, `alice.btc.calendar.opentimestamps.org` | **Opt-in, off by default** — the "opentimestamps" anchoring mode. All three reachable paths are consent-gated (invariant #14f): the "Anchor root" button, the endpoint itself (`consent: true`), and turning the setting on (`ots_consent: true`, demanded once on the local→OTS transition, never re-stamped on every save). | **Not the ethical fetcher:** the OpenTimestamps client library's own HTTP calls. `ots_stamp()` refuses **by name** when the kill switch is on. | `src/custody/timestamp.py:40` |

  **No key-gated source, and Wikimedia Enterprise in particular (Q718 = a).** This app
  reaches Wikimedia only through the public, anonymous endpoints named in the Wikipedia
  row above. It does not use **Wikimedia Enterprise** — the paid, contract-and-API-key
  service — and it holds no API key, account or credential for any Wikimedia property.
  That is a V1-2 constraint applied deliberately, not an omission waiting to be filled:
  a key-gated source ties a local-first app to an account somebody administers, makes
  the operator's traffic attributable to that account, and cannot be reproduced by a
  reader who wants to check the same source themselves. The practical cost is stated
  rather than hidden: the anonymous Action API serves **50 pages per request** where a
  client holding `apihighlimits` is served 500, so this app's reads are ten times more
  numerous and correspondingly slower — and it stays inside the etiquette the service
  publishes for anonymous clients. Enforced by `tests/test_wiki_no_keyed_apis.py`.

  **The four calendar hosts that are never fetched.** `configs/calendar_feeds.yml` still
  ships `calendar.google.com`, `www.webcal.guru`, `cantonbecker.com` and
  `space.floern.com`, each with its dated record — and `src/events/feeds.py:58` filters all
  four out of the loaded directory entirely, because their robots.txt disallows the paths
  in question (field-verified). They are removed, not merely skipped, so they never appear
  in the UI, the preflight or the auto-import. That is the host's own choice, surfaced
  rather than worked around.

  **The DuckDuckGo redirector is refused, not followed.** A result comes back wrapped in
  `duckduckgo.com/l/?uddg=…`. The app extracts the real target **from the query string,
  locally**, and refuses the redirector itself (`src/services/duckduckgo.py:227`) — so the
  host is never fetched and never registered as a source.

  **What an OpenTimestamps submission reveals** is your IP and timing, to the calendar
  operator — the *act of submitting*, not the content: only an opaque SHA-256 digest of
  your content is sent, never the content itself. Route it over Tor if you are a source
  who needs anonymity.

  **The preview is gated too (invariant #14e).** After gating an action, every estimate,
  preview, validation, reachability check and autocomplete that runs *before* it is gated
  as well, because those egress first. That is why "Estimate size" is named on the dumps
  row, and why the robots **preflight** (`src/monitoring/feed_preflight.py:119`) is named
  on the calendar and market rows whose hosts it reads. A refusal by the kill switch is
  reported as a kill-switch refusal, never as the remote server's failure.

  **Two endpoints that exist only because they are switched off.** DuckDB would fetch
  its own extensions from its extension repository on first use; the columnar store opens
  every connection with `autoinstall_known_extensions`, `autoload_known_extensions` and
  `enable_external_access` all **false** (`src/analytics/columnar.py`), and the one
  extension we use is loaded from a locally bundled, SHA-256-verified binary.
  `huggingface_hub` pings its own telemetry endpoint by default; the weight-download
  subprocess sets `HF_HUB_DISABLE_TELEMETRY=1` (`src/llm/vllm_lifecycle.py`). Both are
  worth stating because "we do not contact it" is a property of a setting here, not of
  the absence of code, and a dependency upgrade can quietly change a default.

  **⚠ Three ride-alongs cannot be switched off today, for two different reasons.**
  `auto_import_calendars` and `auto_track_law` are read through
  `getattr(settings, …, True)` (`src/scheduler/runner.py:1248,1250`) against a
  `SchedulerSettings` that defines neither, so the default always wins.
  `auto_track_signals` is worse in kind: the field exists and is honoured, but the API's
  request model omits it, so an operator who turns it off is told the change succeeded
  and it was not. A refusal is honest; a **silently discarded** consent control is not,
  which is why it is stated here rather than waiting for the fix. All three are recorded
  as open work, with the reproduction, in `docs/ledger/OPEN_QUEUE.md` (2026-09-16).

  **Named here because the running app never fetches them.** These host names are in the
  tree and are *not* endpoints: the GPL licence URL `www.gnu.org` in every file header;
  `github.com/ideotion/Open-Omniscience` in the bot User-Agent's contact field and in docs
  links; `publicsuffix.org` and `db-ip.com`, recorded as the provenance of lists that ship
  **bundled in the repo** and are never downloaded; `graphml.graphdrawing.org`, an XML
  namespace URI; `open-meteo.com`, the CC BY 4.0 attribution the weather note carries;
  `wiki.openstreetmap.org` and `astral.sh`, named by a comment and by a docstring that
  explains what the code deliberately does *not* do; `origin.cpc.ncep.noaa.gov` and `www.naturalearthdata.com`, named by a
  parser docstring and by the artifact registry for files an **operator** supplies; the
  ~30 agency home pages in `src/stats/agencies.py`, which are descriptive metadata reduced
  to a registrable domain locally; the `en.wikipedia.org` citation links in
  `configs/world_timeline.yml` and `configs/world_events.yml`; and the fixture hosts in
  docstrings and self-tests. **Installers, maintainer tooling and CI** —
  `./install.sh`, `./install.ps1`, `scripts/` and `.github/workflows/` — reach `pypi.org`, the
  platform's package mirror, `api.github.com`, `raw.githubusercontent.com`,
  `api.nuget.org`, `query.wikidata.org`, `api.worldbank.org`, `download.db-ip.com` and
  `origin.cpc.ncep.noaa.gov`. That is a developer's machine, an operator installing the
  app, or a CI runner — never the installed app at runtime. `./install-offline.sh` makes
  zero network requests by design.

  **How this list is kept true.** The enumeration is derived, not remembered:

  ```
  grep -rnoE 'https?://[A-Za-z0-9._{}%$()-]+' src/ configs/ scripts/
  grep -rnE '^[A-Z_]*(BASE|URL|ENDPOINT|HOST|API|MIRROR|CALENDAR|FEED|DOMAIN)[A-Z_]*\s*[:=]' src/ --include=*.py
  grep -rnE '^\s*-?\s*domain:' configs/            # scheme-less; a URL grep cannot see these
  ```

  The third line is not decoration. `configs/markets_sources.yml` carries 112 sources as
  bare `domain:` values with no `rss_url` at all, so **a sweep for `https://` literals sees
  none of them** — and `src/ingest/crawl.py:149` still reaches every one at
  `https://<domain>`. Any future guard that greps only for URLs inherits that blindness.

  `tests/test_security_endpoint_enumeration.py` re-runs that sweep on every CI run and
  fails when a host literal in the tree is absent from this table, when a URL-bearing
  config file is not named here, or when this table and the consent popup's hover disagree.
  Every exemption in that test states its reason in a sentence a reviewer can disagree with.

## Data at rest & airplane mode

- **Encrypted by default (SQLCipher 4).** A new corpus is created encrypted, opened with
  a passphrase the user chooses at first launch and re-enters at every start. Running a
  **plaintext** store is an explicit opt-out that requires typed confirmation of the risk.
- **No recovery.** There is no recovery and no decryption alternative for the passphrase.
  A lost passphrase costs re-collection time — the corpus is rebuilt from the web, not
  from us — so no recovery key (a second decryption surface) is added.
- **Threat model.** At-rest encryption protects a **seized or copied file** (a machine
  that is off, or a stolen disk image). It **cannot** protect a **compromised, running
  session** — once the store is unlocked the key is in memory. There is deliberately no
  wrong-passphrase rate-limiting: an attacker who can brute-force already has the file and
  works offline, so backoff would only punish the honest fat-finger user; the honest lever
  is passphrase length, which the create flow guides.
- **Airplane mode is a socket-level kill switch, not just a per-call convention.** When
  offline is engaged, `src/ingest/airplane.py` installs a process-wide guard over
  `socket.getaddrinfo` / `create_connection` / `socket.connect(_ex)` — and, since
  2026-07-25, over `http.client.HTTPConnection._tunnel` and PySocks' `socksocket.connect`
  as well, because a proxied connection negotiates its REAL destination at an
  application-protocol layer the first three never see. Any **non-loopback** target raises
  `AirplaneModeError` **before** a real socket is opened, so no missed call
  site, third-party library, or DNS prefetch can egress. Loopback (127/8, ::1, `localhost`)
  and AF_UNIX always pass through (the app's own server, a loopback Ollama, the file DB).
  It is transparent while online. `OO_AIRPLANE_SOCKET_GUARD=0` disables the backstop; the
  per-call refusals remain as the friendly layer above it. App boot makes zero network calls.
- **The same patch layer carries a second, independent gate: the connect-time SSRF check**
  (`src/ingest/ssrf_guard.py`, 2026-09-07). It is inert except inside an `EthicalFetcher`
  request on the thread making it, where it refuses any non-public address the request
  resolves to or connects to — closing the window between the pre-fetch check's `getaddrinfo`
  and the one `requests` performs at connect time. One patch layer, two gates, so a call site
  cannot meet one and miss the other; each has its own opt-out
  (`OO_SSRF_CONNECT_GUARD=0` here), and neither flag disables the other.

## Data integrity / chain of custody

- Stored items carry provenance (source, original URL, canonical URL, content hash,
  fetch time).
- Evidence bundles are **Merkle-rooted (domain-separated) + Ed25519-signed**. Verify
  with `scripts/verify_evidence.py <bundle.json> [signer_public_key]` — pass the
  signer's key to prove *provenance*, not just integrity. Verification needs nothing
  but the bundle + key (no DB, no trust in this tool).
- An append-only, hash-chained, **signed custody log** (`src/custody/`) records
  ongoing actions on an item; verify offline with `scripts/verify_custody.py`.
  Signatures are **hybrid Ed25519 + post-quantum ML-DSA** when the `pqc` extra is
  installed (honestly labelled `ed25519` otherwise; hybrid verification requires
  *both* components — never a silent downgrade). Independent time comes from
  **OpenTimestamps** (Bitcoin-anchored); a self-asserted local time is the offline
  default. See `docs/USER_MANUAL.md` for the full model and its limits.
- **Configurable from the UI:** post-quantum signing, anchoring mode
  (local vs OpenTimestamps), and auto-logging on ingest are operator-controlled at
  runtime from the **Chain of custody** panel (or `GET/PUT /api/custody/settings`),
  persisted to `custody_settings.json`. A toggle is a *request*: the UI and API always
  surface the **effective** state, so post-quantum / OpenTimestamps can never appear
  "on" when the supporting extra is not installed.
- **Privacy caveat:** anchoring to a public blockchain is permanent publication and
  can deanonymise; it is opt-in, defaults to the offline local provider, and is
  documented with a warning. Custody auto-logging on ingest is off by default
  (defaulting to the legacy `OO_CUSTODY_ON_INGEST=1` flag until a UI preference is saved).

## Hardening already in place

*(Current state, re-derived from the tree on 2026-09-07 — the 2026-06 audit report further
down is a RECORD of that date and carries its own disposition table.)*

- **Injection sinks.** Parameterized DB access only (no string-built SQL on the live path);
  FTS5 `MATCH` is fully bound, and an injection-style search returns 400 or an empty match,
  never a 500. `bleach` allowlist for any HTML; `bcrypt` required for hashing (no silent
  fallback). No `eval`/`exec`/`pickle`/`yaml.load` sinks, asserted by a repo invariant.
  Untrusted XML (Wikipedia dumps, sitemaps) parses through `defusedxml`.
- **Ingested URLs.** `sanitize_url` strips whitespace before the scheme check, and
  `safe_href` allowlists http(s) before any ingested URL is rendered as a link, so a
  `javascript:` URL in a feed is inert text. Both catch `ValueError` only — an unexpected
  exception reaches the caller instead of becoming an empty string that reads as "unsafe".
- **The fetch path.** Robots fail-closed, per-host rate limits, an honest bot User-Agent,
  bounded redirects re-validated per hop on the page *and* robots fetches, a declared
  `Content-Length` refused up front, and the streamed body aborted mid-read once it exceeds
  the cap (so a gzip bomb never materialises). SSRF is checked twice: the target is resolved
  and validated before the fetch, and — since 2026-09-07 — every address the request actually
  resolves or connects to is validated as it happens, closing the DNS-rebinding window
  between the two (`src/ingest/ssrf_guard.py`).
- **The local API.** A cross-origin state-changing request is refused (403) on `Origin`/
  `Referer`; a `Host` header that does not name this loopback API is refused (421, a
  DNS-rebinding guard); every non-Swagger response carries `nosniff`,
  `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a `default-src 'self'` CSP with
  `frame-ancestors 'none'`. CORS ships `allow_credentials=False`.
- **At rest.** The data dir is created `0700` (best-effort, POSIX-only) so another local user
  cannot read the corpus, signing keys or custody log; signing keys are `0600`. Full at-rest
  encryption remains the host's job (Qubes/LUKS) — this bounds a shared host, not a seized one.
- **Exported data.** CSV cells beginning `= + - @` or a control character are neutralised
  before export (spreadsheet formula injection).

## At-risk-user safety (Settings → Advanced → Safety, and → Uninstall & wipe)

For journalists working under pressure. Each tool states its honest limit — we never
imply a protection we cannot deliver.

- **Encrypted backup/restore** (`src/safety/crypto.py`, `backup.py`): a passphrase-derived
  AES-256-GCM key (scrypt KDF, per-file salt + nonce) over a live SQLite snapshot. The same
  audited primitives used elsewhere — no bespoke crypto. A wrong passphrase or any tampering
  fails *loudly* (`EncryptionError`); a correctly-decrypted but non-Open-Omniscience payload
  is refused before it can overwrite the corpus.
- **Panic wipe** (`src/safety/panic.py`, under **Advanced → Uninstall & wipe** — kept in a
  section of its own, apart from the tools above, because it cannot be undone):
  best-effort overwrite-then-delete of the whole data dir, requiring an explicit confirmation. **Honest limit:** overwrite-in-place does *not*
  guarantee unrecoverability on SSD/flash or copy-on-write filesystems — only full-disk
  encryption (LUKS/Qubes/Tails) plus key destruction does. Also exposed as a `panic` CLI and
  an `--ephemeral` mode (RAM-only data dir, wiped on process exit).
- **Protected fetch mode** (`src/safety/settings.py`, `fetcher.py`): routes every fetch
  through a proxy you run and sends a generic User-Agent that does not name the tool. **Honest
  limit:** this cannot guarantee anonymity — you must run and trust the proxy (e.g. Tor)
  yourself. Refuses to enable without a proxy URL. HTTP/HTTPS proxies work out of the box;
  **SOCKS** proxies (e.g. `socks5://127.0.0.1:9050` for Tor) additionally need **PySocks**
  (`pip install pysocks`) — there is no packaged extra for it.

These are local and loopback-only; the destructive/state-changing routes are protected by the
same cross-origin refusal middleware as the rest of the API.

## Reporting a vulnerability

**Please do not open a public issue for a security vulnerability.** Report it
privately by email to **open-omniscience@ideotion.com** with steps to reproduce;
we aim to acknowledge within a few days. A public GitHub issue is appropriate only
for non-sensitive, already-public security-hardening discussion.

Because the app is loopback/single-user, the main risk surface is the
ethical-fetch path and the evidence-verification guarantees above.

---

# Application-security audit (2026-06)

> ## ⚠ Disposition — this report is a RECORD of 2026-06-08, not a list of open findings
>
> **Every Medium and Low finding below has since been closed in code**, and the report
> was never updated, so it has been reading as a live to-do list for over a year. It is
> kept in full because its threat model, data-flow map and reasoning are still the best
> description of this app's attack surface — but the table below, not the sections after
> it, is the current state. Each verdict was re-derived from the tree on **2026-09-07**
> (`main`, the anchors are what proves it), never taken from a status line.
>
> | # | 2026-06 finding | State on 2026-09-07 | Anchor |
> |---|---|---|---|
> | S-001 | SSRF (CWE-918) | **Closed, including the residual.** Resolve-then-validate on the target, manual bounded redirects re-validated per hop on the page *and* robots paths. The `OO-D2-003` DNS-rebinding TOCTOU the report left open — the one thing "pin to the validated IP" was for — was live-reproduced and closed on 2026-09-07 by validating the address the connection *actually reaches*, not by pinning. | `src/ingest/__init__.py::_guard_target`, `::_guarded_redirect_get`, `src/ingest/ssrf_guard.py`, `tests/test_ssrf_connect_guard.py` |
> | S-002 | Decompression-bomb / size DoS | **Closed.** `Content-Length` refused up front; the real (streamed) body is read in chunks against a running ceiling, so a gzip bomb is aborted mid-read rather than after materialising. | `src/ingest/__init__.py::_read_body` |
> | S-003 | CSRF on no-body POSTs | **Closed.** A middleware refuses any state-changing method whose `Origin`/`Referer` is not loopback (403). A separate `Host`-header guard refuses a DNS-rebinding host with 421. | `src/api/main.py::csrf_and_security_headers` |
> | S-004 | CSV formula injection | **Closed.** Exported cells beginning `= + - @` or a control char are prefixed with `'`. | `src/utils/security.py::csv_safe_cell`, `tests/test_security_hardening.py` |
> | S-005 | `javascript:` URI in an `href` | **Closed.** A strict http(s) scheme allowlist runs on every ingested URL rendered as a link, server-side and in the reader. | `src/utils/security.py::safe_href` (call sites: `src/api/main.py`, `src/api/law.py`, `src/services/duckduckgo.py`) |
> | S-006 | No CSP / security headers | **Closed except one clause.** `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer` and a `default-src 'self'` CSP with `frame-ancestors 'none'` ship on every non-Swagger response. **Residual, tracked as NET-04:** `script-src` still carries `'unsafe-inline'`, because the UI still has roughly 590 inline `on*=` handlers; landing a nonce-based CSP before they are retired would break the app. | `src/api/main.py::_CSP` |
> | S-007 | CORS `allow_credentials=True` | **Closed.** The app passes `allow_credentials=False`. (`src/config/settings.py` still declares a `cors_allow_credentials` default of `True`; nothing reads it — recorded here rather than changed, because removing a config field is a surface change, not a security fix.) | `src/api/main.py` CORS middleware |
> | S-008 | XXE (residual) | **Posture asserted.** Both untrusted-XML readers parse through `defusedxml`. | `src/wiki/dumpread.py`, `src/ingest/sitemap.py` |
> | S-011 | At-rest file permissions | **Closed at the level that bounds access.** The whole data dir is `chmod 0700` on creation, which is what stops another local user reading the corpus, keys and custody log; individual files keep their umask mode inside it. Best-effort and POSIX-only by design — full at-rest encryption remains the host's job (Qubes/LUKS), as the report itself says. | `src/paths.py::_ensure` |
> | S-009 | SQL/FTS injection — SAFE | **Still safe, and now guarded.** An injection-style search returns 400 or an empty match, never a 500. | `tests/test_security_hardening.py::test_injection_style_search_returns_400_not_500` |
> | S-010 | No eval/exec/pickle sinks | **Still true, and now guarded.** | `tests/test_repo_invariants.py::test_no_dangerous_eval_or_deserialization_sinks` |
> | S-012 | Indirect prompt injection — bounded | **Unchanged posture** (local model, no tools, output escaped and labelled as AI-derived). | — |
>
> The remediation roadmap in §5 is therefore **spent**: items 1–8 are done, apart from the
> `script-src 'unsafe-inline'` clause of item 5.

The defensive security review of the ingest→store→process→present data path, its findings, and the hardening applied.

**In this part:**
- [Security report — Open Omniscience](#security-report--open-omniscience)


---

## Security report — Open Omniscience

**Target:** `/home/user/Open-Omniscience` @ `5780172` · **Date:** 2026-06-08 ·
**Mode:** defensive, read-only assessment (no code changed) · **Network:** OFF (no live
external target contacted; benign markers only) · **Proof trail:** [`HISTORY.md`](HISTORY.md) ·
**Machine-readable:** [`security_findings.json`](archive/security_findings.json) / [`security_findings.csv`](archive/security_findings.csv)

---

### 1. Executive summary & risk posture

Open Omniscience ingests **untrusted web content** (pages, RSS/Atom feeds, emails, market
pages, legal documents) into a local SQLite corpus, analyses it, and renders it in a
loopback-bound browser UI — a classic *hostile-input → store → process → present* pipeline.

**Overall posture: solid core, with defense-in-depth gaps at the edges.** The two highest-risk
classic sinks are correctly handled: **SQL/FTS injection is parameterized and proven safe**
(S-009, Verified PoC — SQL keywords become literal data and injection-style queries are
rejected with HTTP 400), and there are **no command/code-injection or insecure-deserialization
sinks** (S-010 — no shell/eval/exec/pickle/`yaml.load`). The GUI escapes ingested fields, the
ethical fetcher fails **closed** on robots uncertainty, signing keys are `0600`, and no secrets
live in code. **No Critical or High findings.**

The weaknesses that matter are **edge controls around hostile input**, all Medium:

1. **SSRF (S-001) — substantially closed; one residual.** The fetcher resolves and
   validates every target against private / loopback / link-local / `169.254.169.254`
   (cloud metadata), and follows redirects **manually with a per-hop re-validation on
   BOTH the page fetch and the robots.txt fetch** (the robots redirect chain was the
   last gap — it used `allow_redirects=True` and is closed by OO-D2-001).
   **Residual (OO-D2-003, Low/Rare):** a DNS-rebinding TOCTOU window between the
   guard's `getaddrinfo` check and `requests`' connect-time re-resolution. Closing it
   needs connect-time IP pinning (a custom `requests` adapter) and is tracked as
   hardening; it is mitigated by the public-IP-literal block and the curated catalog.
2. **Decompression-bomb / size DoS (S-002):** the 10 MiB cap is checked **after** the whole
   (auto-gunzipped) body is in memory.
3. **CSRF on no-body POST endpoints (S-003):** no token/Origin check; a visited web page can
   trigger scrapes (amplifying S-001), reseeds, or an actor-collapse on the local instance.
4. **CSV/spreadsheet formula injection (S-004, Verified PoC):** ingested titles/content are
   exported unneutralized.
5. **No CSP / security headers (S-006):** no backstop if any escape is missed, and the UI is
   frameable.

Plus Lows: a `javascript:`-URI link vector (S-005), permissive `allow_credentials` CORS (S-007),
at-rest file permissions (S-011), and bounded indirect prompt injection (S-012).

**Coverage statement.** I traced the ingest→store→process→present data path and every query,
render, and export sink, with safe local PoCs for the FTS and CSV paths. I did **not** perform
any **live external fetch** (network off) — so the SSRF redirect-bypass and the decompression
bomb are reasoned from the code + library behaviour and marked by their static confidence
(Inferred), not fired against a real host; I did not run a live cross-origin CSRF page against
the server (reachability is read from route signatures + the CORS config); and I did not read
all 236 modules (prioritised the data path and sinks).

---

### 2. Threat model & data-flow

**Assets:** the corpus + its provenance/integrity (a poisoned corpus → poisoned intelligence);
signing keys & the custody chain; the operator's host & privacy; the GUI session.

**Adversaries:** a malicious website/feed author serving hostile pages; a disinfo actor poisoning
the corpus; a web page the operator merely visits (CSRF); a crafted document/media file; a local
user on a shared host.

**Trust boundaries & STRIDE focus:**

```
 internet ──(B1)──> EthicalFetcher ──(B2)──> parsers ──(B3)──> SQLite corpus
   hostile           [S-001 SSRF,             feedparser/        [S-009 SQL: SAFE;
   pages/feeds        S-002 DoS]              trafilatura         S-004 CSV export]
                                              S-008 XXE(resid)]        │
                                                                       ▼
        browser <──(B5)── FastAPI render ◀──(B4)── analytics + local LLM
        [S-005 js: URI,    [S-006 no CSP,            [S-012 prompt-injection,
         S-003 CSRF]        S-007 CORS]               bounded — no tools]
```
- **B1 internet↔ingestion:** Tampering/DoS/SSRF — **S-001, S-002**.
- **B2/B3 parse↔store:** Injection — **S-009 (safe)**, **S-008 (residual)**; export **S-004**.
- **B4 process/model:** **S-012** (indirect prompt injection, bounded).
- **B5 present↔user:** XSS/CSRF/clickjacking — **S-005, S-006, S-003, S-007**.
- **at rest:** **S-011**.

---

### 3. Findings by severity

> Full schema (attack_vector, impact, evidence, fix, effort/risk) in `security_findings.json`.

#### Critical — none. · High — none.

#### Medium

- **S-001 · Ingestion · SSRF · CWE-918 · Inferred/Likely.** Fetcher checks only the scheme;
  `allow_redirects=True` with no re-validation; robots checked on the original URL only →
  redirect to loopback/RFC1918/`169.254.169.254`. *Fix:* resolve-then-validate (deny internal
  ranges + non-HTTP), manual bounded redirects re-validated per hop, pin to the validated IP.
- **S-002 · Ingestion · Decompression-bomb/DoS · CWE-400/776 · Inferred.** `max_bytes` checked
  after the full (gunzipped) body is materialised. *Fix:* `stream=True` + chunked read with a
  running ceiling; Content-Length precheck; bounded decompression.
- **S-003 · Presentation · CSRF · CWE-352 · Inferred/Likely.** No token/Origin check;
  no-body POSTs (`/api/sources/{id}/ingest`, scheduler, `/api/briefing/refresh`,
  `/api/law/track|seed`, `/api/integrity/collapse/apply_all`) are simple requests executable
  cross-origin. *Fix:* require a custom header (forces preflight) or validate Origin/Referer =
  loopback on all state-changing methods.
- **S-004 · Storage(export) · CSV formula injection · CWE-1236 · Verified (PoC).** Exported
  article cells not neutralized (`=OOAUDIT_MARKER()` survives). *Fix:* prefix cells starting with
  `= + - @`/control chars with `'` in both CSV exporters.
- **S-006 · Presentation · Missing CSP/headers · CWE-16/1021 · Verified (absent).** No CSP,
  `X-Frame-Options`, or `X-Content-Type-Options`. *Fix:* a header middleware with a strict
  `default-src 'self'` CSP (feasible — the UI is dependency-free), `nosniff`, `frame-ancestors
  'none'`, `Referrer-Policy: no-referrer`.

#### Low

- **S-005 · Presentation · `javascript:` URI in href · CWE-79/80 · Inferred/Likely.** Stored
  article URL rendered as `href` without a scheme allowlist (client + server `view_article`);
  `esc()` doesn't block the scheme. *Fix:* allowlist http/https before rendering; else inert text.
- **S-007 · Cross-cutting · CORS `allow_credentials=True` · CWE-942 · Verified.** Unnecessary
  (no cookies/auth); latent if origins widen. *Fix:* set `allow_credentials=False`.
- **S-011 · Storage · At-rest perms · CWE-311/732 · Inferred.** DB/cache/custody files use umask
  (often `0644`); only keys are `0600`. *Fix:* `0700` data dir, `0600` DB/custody/annotations;
  keep documenting host-level (Qubes/LUKS) encryption.
- **S-008 · Ingestion · XXE (residual) · CWE-611 · Hypothesis.** feedparser is entity-safe by
  default; no raw XML parser found. *Fix:* assert the posture; use `defusedxml` for any future XML.

#### Info (positive controls to preserve)

- **S-009 · SQL/FTS injection — SAFE (Verified PoC).** Parameterized `MATCH :q`; terms quoted;
  malformed → 400; ORM filters parameterized; no identifier/ORDER BY interpolation; no
  second-order query building found. *Keep* + add a 400-not-500 regression test.
- **S-010 · No injection/deser sinks; robots fail-closed; output encoding; keys 0600; no secrets.**
  *Keep as invariants* (extend `test_repo_invariants.py` to assert no `eval/exec/pickle/yaml.load`).
- **S-012 · Indirect prompt injection — bounded** (local model, no tools, output displayed escaped).
  *Keep the no-tools posture*; delimit data vs instructions; label model output as derived.

---

### 4. Data-flow / taint summary (source → sink verdict)

| Untrusted source | Sink | Neutralized? |
|---|---|---|
| GUI search/filter text | SQLite FTS5 `MATCH` / ORM filters | **Yes** — bound param + quoted terms (S-009, PoC) |
| GUI sort/identifier | — | n/a — no dynamic identifier/ORDER BY interpolation found |
| ingested URL / redirect target | `requests.get` (fetcher) | **No** — scheme-only check, redirects unvalidated (S-001) |
| ingested response body | memory (size cap) | **Partial** — cap applied post-download (S-002) |
| ingested feed XML | feedparser | **Yes (default)** — entity-safe library (S-008 residual) |
| ingested title/content | CSV export cell | **No** — formula injection (S-004, PoC) |
| ingested title/content/source | GUI `innerHTML` | **Yes** — `esc()` / `html.escape` on the rendered paths (S-010) |
| ingested URL | GUI/server `href` | **No** — scheme not allowlisted; `javascript:` survives (S-005) |
| ingested text | local LLM prompt | **Partial** — bounded (no tools); output displayed escaped (S-012) |
| cross-origin web page | state-changing POST | **Partial** — JSON endpoints preflight-gated; no-body POSTs are not (S-003) |
| stored data re-read | new query | **Yes** — no second-order query construction found |

---

### 5. Remediation roadmap (by exploitability × impact)

1. **S-004** (S/Low) — neutralize CSV export cells. *Verified, trivial, real operator impact.*
2. **S-003** (M/Low) — Origin/custom-header check on state-changing requests. *Closes CSRF; blunts S-001 amplification.*
3. **S-001** (M/Med) — resolve-then-validate + manual bounded redirects in the fetcher. *Closes SSRF; centralised in one path.*
4. **S-002** (M/Low) — streamed, bounded, decompression-capped fetch.
5. **S-006** (M/Med) — security-header middleware with a strict CSP. *Backstops any future XSS + clickjacking.*
6. **S-005** (S/Low) — http/https scheme allowlist on rendered links.
7. **S-007** (S/Low) — `allow_credentials=False`. · **S-011** (S/Low) — `0600`/`0700` file perms.
8. **S-009/S-010** (S/Low) — regression tests: search injection → 400 (not 500); no eval/exec/pickle in `src/`.

**Quick wins:** S-004, S-005, S-007 are each a few lines and low-risk; S-009/S-010 regression
tests turn the positive controls into guardrails.

---

### 6. Residual risk & assumptions

- **Host/isolation is load-bearing.** The design assumes a **single-user, loopback-only Qubes
  AppVM**. SSRF (S-001) and at-rest exposure (S-011) are substantially mitigated by that boundary;
  the risk rises sharply if the app is run on a multi-user host, a cloud VM with an IMDS, or
  bound beyond loopback.
- **No auth by design.** CSRF (S-003) is the price of a no-auth local API; the right control is an
  Origin/header check, not adding accounts.
- **Untested live behaviour.** SSRF redirect-bypass, the decompression bomb, and cross-origin CSRF
  were reasoned from code/library behaviour, not fired against a live host (network off). They are
  marked Inferred; a follow-up with a controlled local fixture server (operator-confirmed) would
  promote them to Verified.
- **Corpus integrity ≠ truth.** The product is intelligence; a determined actor can still *poison*
  the corpus (flood/echo) within the rules. The 0.06 source-integrity layer surfaces this; it is a
  mitigation of impact, not a barrier to ingestion (by deliberate design).

*Read-only assessment: no source was modified. Every claim traces to a line in
`HISTORY.md`. No weaponized payloads or secrets are included.*

