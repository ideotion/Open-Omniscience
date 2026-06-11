# Future developments

> Forward-looking ideas that are **not** committed work yet — a place to elaborate a
> direction before it earns a `ROADMAP.md` slot. Nothing here is promised. Each idea is
> held to the same bar as shipped work: **honest by construction** (real, provenanced
> data with as-of dates; predictions clearly labelled as such), **local-first / offline**,
> and **the user disposes** (we surface, never fabricate or decide).
>
> **Revised 2026-06-11 (maintainer-ordered reality check):** everything verified
> against the code; shipped material was REMOVED rather than carried as stale
> STATUS notes (git history and `docs/CHANGES.md` keep the record). Two earlier
> claims were corrected in the process: the ten-scenario-cards section said
> "SHIPPED" when only 3 of 10 cards became recipes, and the two-hop keyword
> graph stub said "future" when the layered graph had in fact shipped.
> Shipped-and-gone from this file: events agenda core + feeds A/B design +
> event-family dedup; personality/easter eggs; keyword super-groups; offline
> vector map (bundled coastline + gazetteer pins); two-hop layered graph;
> LLM catalog decisions; diagnostics keyword log slice 1; temporal map layers
> 1–2; hazards relay; offline discovery channels (RM-19 slice); evidence-tier
> slice 1; trans-language groundwork (signatures + curated rings); the v0.0.7
> session-handoff notes (dead).

---

## The 0.0.9 sequencing (maintainer-agreed 2026-06-11)

1. **Database reliability batch** — the mandate below, designed TOGETHER with
   SQLCipher at-rest encryption (standing ruling: a fresh, dedicated session;
   crypto and data-integrity deserve full attention, not a session tail).
   Deliverables: gap analysis → design doc → implementation with a torture-test
   suite (interrupted imports, duplicate floods, cross-version restores).
2. **Newsletter scraper** — only after (1) is solid (see its section below).
3. **Convergence flagship** (space-time layers 3+4) built on the
   When×Where×Who ingest-time anchoring substrate.
4. **Audit remediation queue** — `docs/audit/06_FULL_AUDIT_0_0_9.md` (ranked;
   two items await a maintainer ruling: the "stays on this machine" wording and
   caveats-visible-by-default vs calm UI). Rides along in normal sessions.
5. Standing queue items (CLAUDE.md) continue as session work between batches:
   agenda views/depth, corpora system, global search rework, download/task
   manager, interactive charts + SI formatter, i18n long tail.

---

## DATABASE RELIABILITY MANDATE — backup/restore as an OS-grade tool (maintainer-ruled 2026-06-11)

> **The ruling (verbatim intent):** before any personal data is scraped
> (newsletters), the database tooling must be *absolutely reliable* — "it's like
> the backup/restore function of an OS. If it's not entirely reliable, it should
> not exist, and I'd like it to exist."

**Requirements (maintainer-stated):**
- **Everything included.** A backup must carry the WHOLE app state — articles,
  keywords + mentions + families/super-groups/overrides, Wikipedia snapshots and
  tracked pages, newsletters, financial/commodity/index series, law documents and
  revisions, events/subscriptions, custody log, annotations, settings. Today's
  backup is the SQLite file snapshot (which does hold all tables) — but **import/
  merge, dedup and verification do not cover every domain**, and side files
  (keys, configs/overrides, data/*.jsonl logs) live outside it. The gap analysis
  is the first deliverable.
- **Import with duplicate handling that cannot corrupt.** Merge-import (never
  replace), bit-level duplicate detection (content hash + byte comparison), FK
  remapping, a dry-run preview before commit, and a post-merge integrity
  verification pass (counts + hash spot-checks + FTS rebuild check). A failed or
  interrupted import must leave the original database untouched (work on a copy,
  swap atomically).
- **Export both encrypted and plaintext**, the encrypted flow being the default
  (passphrase → download); restore accepts both, says which it got, and verifies
  before touching anything. Each article keeps its content hash + an
  authentication hash (tamper evidence across the export boundary).
- **Provenance safeguards** (from the earlier backup-merge stub, now folded in):
  merged rows keep their origin and are never laundered into first-party
  evidence; incoming custody signatures are *verified*, not trusted.
- **LOCAL at-rest encryption by default (maintainer-refined 2026-06-11 — "not
  just on export, locally"; UI SIMPLIFIED by ruling same day):** the working
  database FILE on disk is SQLCipher-encrypted; a copied or seized `*.db`
  without the key is random bytes. **The start-up UX (maintainer-specced):**
  when the app starts it asks for THE passphrase — one stable secret, "like a
  user ID", same every time — and unlocks the storage. At FIRST launch, a
  plain note: choose something unique and remember it; **there is no recovery
  and no decryption alternative.** Maintainer's recorded rationale for
  no-recovery: the database can be reconstituted from the web's corpus — it
  holds no personal information beyond what was scraped and algorithmically
  deduced from public sources, so a lost passphrase costs re-collection time,
  not unique data. (The earlier recovery-key rider is superseded by this
  ruling.) `OO_DB_PASSPHRASE` env for scripted/headless runs.
  **Recorded contingency:** this premise EXPIRES when the newsletter domain
  ships — mailbox content is personal and NOT reconstitutable — so the
  no-recovery choice must be consciously revisited before newsletters land
  (options then: optional recovery key, or a re-key/export checkpoint).
  **Honesty constraint on sequencing:** the passphrase prompt ships TOGETHER
  WITH the encryption, never before it — a lock screen over a plaintext file
  would be fabricated security, the exact thing this project forbids.
  **Layering note (maintainer question 2026-06-11, answered):** DB-level
  encryption is NOT redundant under full-disk encryption — the two cover
  different machine states. FDE protects only the powered-OFF disk; once
  booted/unlocked it is transparent to every process. The encrypted DB file
  stays ciphertext in exactly the states FDE doesn't cover: a machine stolen
  while running/suspended, an unlocked machine inspected, malware or sync
  copying files off a live system. The layers are independent only if their
  passphrases differ (same secret = one layer); and NO at-rest layer protects
  a compromised running session (keys live in RAM) — stated wherever shown.
  Existing databases: a one-way encrypt tool, snapshot first, explicit consent
  — never a silent conversion on upgrade. Portability checkpoint: sqlcipher3
  wheels verified on Linux+Windows+macOS before committing to the driver.

**Sequencing (standing rulings combined):** design TOGETHER with SQLCipher
at-rest encryption (ruled GO, own fresh session — one coherent key story), and
**the newsletter scraper waits until this is done.**

---

## Newsletter scraper — email/newsletter intelligence (gated on the mandate above)

**The goal (maintainer-stated 2026-06-11):** ingest the operator's newsletters
as a first-class corpus domain. A detailed implementation plan already exists in
`docs/ROADMAP.md` ("Email & Newsletter Intelligence"); `scripts/import_eml.py`
is the manual seed of the path. What makes this different from web sources — and
why it is **deliberately blocked behind the database mandate** — is that it is
**personal data**: a mailbox identifies the operator, their subscriptions and
their reading life. The bar:
- **Local-only, operator's own mailbox, explicit opt-in** — fetched via the
  operator's credentials (IMAP/.eml import), never a hosted relay; credentials
  stored like the custody keys, never in plaintext config.
- **Newsletters ride the same substrate**: provenance (sender, list-id, fetch
  time, content hash), dedup, keywords/mentions, the reader, and — critically —
  **backups and merge-import carry them with full fidelity** (the mandate's
  "everything" clause is what unblocks this).
- **Privacy asymmetry stated in the UI**: newsletter content may embed tracking
  pixels/links — strip/neutralise them at ingest (no remote-image fetches), and
  say so honestly.
- At-rest encryption (SQLCipher batch) matters MORE here than anywhere; another
  reason the sequencing is what it is.

---

## When × Where × Who anchoring — persist the extractors at ingest (maintainer question 2026-06-11; CONFIRMED GO in field report #2 same day — at scrape for every article incl. wiki, + backfill; sequenced after the DB batch)

**Honest state today (code-verified):** every keyword mention is anchored to an
article + a time (`observed_on`) + the SOURCE's place (country/city — coverage
origin, corrected by the 0.09 migration). The When/Where/Who extractors
(`src/timemap/dateextract|locextract|entextract`) exist and are honest — but
they run **at read time, per article, in the reader view only**; their output is
not persisted, so nothing anchors extracted event-dates, event-places, people or
organisations to keywords or to the map/analytics layers.

**The development:** run the three extractors **at ingest** (and via a backfill
pass), persist their output with snippet provenance + rule notes (the existing
"deduced, never confirmed" discipline), and anchor them:
- per **article**: stored event-dates/places/entities (the reader stops
  recomputing; the corpus becomes queryable by them);
- per **keyword mention**: optional event-place (distinct from coverage origin)
  feeding the temporal map's mention layer (the standing "NEXT" item);
- per **entity**: a corpus-wide people/organisations layer (counts, languages,
  co-occurrence with keywords) — the WHO axis the convergence engine needs.

Cost honesty: extraction is lexical and bounded, so ingest overhead is small;
backfill is a one-time scheduled job with progress. Every stored deduction keeps
its method note and is displayed as deduced — never promoted to fact.

---

## Space–time layers 3+4 — convergence detection + the watch-rule engine (the 0.0.9 flagship)

> Layers 1–2 (the unified Signal lens over map + timeline) shipped in 0.07.
> What remains is the payoff. Strengthened since the original design by the new
> WHO axis (above) and the corrected mention geography.

### Layer 3 — synchronicity / convergence detection (honest, not oracular)
Scan for **space-time cells (region × window) where several *independent* domains
light up at once** — an upcoming agenda event **+** a keyword spike **+** a market
move **+** a law change. Reported as real co-occurrence (counts, dates, the
actual signals, sample sizes) — **never** causation or prediction, and the
correlation ≠ causation line is printed with it.

### Layer 4 — "if-this-then-WATCH" rules (forecasting-adjacent, so hard guardrails)
A user-defined, fully transparent rule engine — an *attention director*, not an
oracle. A rule is a conjunction over **real stored signals**; a match surfaces
**exactly which conditions hold** (explainable, auditable). The "then" is the
user's labelled hypothesis, presented as a prompt to investigate. Rules are
user-owned, editable, reversible; example rules ship **off by default**; no
black-box scoring (the quarantined credibility analyzer remains the cautionary
tale).

### New Home producers once 3+4 exist
"Converging now" · "On the horizon" (agenda ∩ tracked keywords) · "Through
time / anniversary lens" · "Your watch-rules fired" — each listing the real
contributing signals.

**Build sequence:** (1) convergence scan over the existing Signal model;
(2) the two read-only producers; (3) the rule engine + "rules fired";
(4) the alert tiers below.

---

## Hazard & news alerting layer (parked from the climate/weather vertical)

The hazards relay (GDACS/USGS, map layer) shipped in 0.07. Still future: the
**local, severity-tiered alert layer** — triggers from high-severity hazard
entries, tag-families firing in fresh news (`nuclear`/`outbreak`/`coup`…),
watch-rule matches and convergence cells. Tiers info · watch · urgent; urgent
surfaces as a Home banner. Guardrails unchanged and non-negotiable: **local
only** (no external push, ever), explainable (every alert cites its real
triggering signals), user-owned thresholds, severity from the *source's* scoring,
and the honest coverage line: "a source we watch reported this", never "this is
everything happening". Also still future from that vertical: official
short-horizon forecast relay (Open-Meteo/NWS, with issuer + issue-time +
horizon), and ReliefWeb/FEWS NET/WHO humanitarian channels.

---

## Events agenda — the open remainder

The agenda core shipped (catalog, subscriptions, facets, event-family dedup,
verified feed directory). Still genuinely future, all queued in CLAUDE.md:
- **Calendar VIEWS**: list / week / month / trimester / semester / year / decade
  switcher (the tab has only the list). **Field report #2 (2026-06-11): the
  DEFAULT becomes a month GRID — 4–5 week rows, brief event descriptions,
  like a regular agenda — with customizable view options.**
- **Month-spanning events** ("Dry January"): a duration/whole-month kind in the
  schema, rendered as a banner across the month, not a single-day pin.
- **Catalog depth** ("we should be flooded; it's the point of datamining"):
  elections worldwide, summits, central banks, parliaments, courts, UN
  observances, fiscal dates… every entry sourced, movable dates marked,
  subscribe-default stays off-flood.
- **Full iCal import into the agenda** (feeds → exact dated events, idempotent
  per (source, uid)) — the verified directory covers discovery; import is the
  missing half.
- **Saved-filter "smart calendars"**: subscribing to a *tag query* ("all
  elections in Africa") as the natural subscription unit.
- **Agenda tab translation** (currently the worst i18n surface).

### Recurrence + world calendars + the astronomy layer (field report #2, 2026-06-11)

The maintainer saw "Independence Day (Mexico) 2026" as a one-off — root
cause verified: the bundled `world_events.yml` is already recurrence-based
(`cadence: annual, month, day`) and simply has no Mexico entry; **imported
ICS feeds store year-pinned instances**, which is where single-dated
"recurring" events come from. The design that unifies it all:

- **One recurrence model**: an event is a RULE (annual fixed-date; movable
  with method; span) plus optional dated INSTANCES (from feeds), plus an
  optional `since:` origin year (Mexico: 1810 — render "since 1810", and the
  temporal map can show it on every year it existed, not one pin).
- **Worldwide preloads, honestly**: bank holidays via the existing verified
  feed directory + a bundled computed set; **Islamic (moon-based) dates
  computed from the tabular calendar and labelled "computed — actual
  observance may differ by ±1 day (moon sighting)"**; Hindu/Buddhist major
  observances from *published, sourced date tables* (movable-marked) — we do
  NOT fabricate a panchanga engine; regional variation is stated. The
  current catalog's Christian-centring is a coverage bug, treated like the
  source catalog's US-centring: measured, then balanced.
- **The astronomy layer — a reliable LOCAL mathematical model**: full moons
  (and phases) computed with the standard Meeus algorithms (accuracy
  ~minutes; unit-tested against published almanac values, the same pattern
  as the model-catalog freshness test); solar/lunar **eclipses from a
  bundled public canon table** (provenance + license recorded) rather than a
  half-right computation — type, magnitude and "visibility is
  location-dependent; not computed for your location" stated per event.
  Every astronomical entry carries `method` + `accuracy`. Zero network at
  boot: all of it bundles as data; nothing auto-fetches.
- Speeds on the temporal map player extend to **0.05×–16×**, log-stepped
  (the maintainer's calibration: today's 0.1 is about the useful 1×).

---

## Network switch — layered guarantees, stated honestly (field report #2, 2026-06-11)

The maintainer asked for airplane-mode clarity and "physical kill-switch"
reliability, including no *inbound* packets, "linked to the hardware driver
like a webcam light". The honest layering this becomes:

1. **In-app (what the button truly controls today):** the kill switch gates
   the single fetch path; airtight is achievable and testable — every
   outbound socket must route through one guarded factory, with a test that
   fails the build if any module opens its own. Inbound: the app binds
   loopback only and, when offline, holds no outbound sockets — there is
   nothing addressed to it to receive. The button copy says exactly this
   scope.
2. **UI semantics (ruled):** airplane-mode pattern — one constant
   icon+label whose FILL is the state (filled = offline engaged); never an
   action glyph as a state label. State repaints immediately on every
   transition including implicit ones (a collect run clears the kill switch
   server-side — api/scheduler.py:73-75 — and the UI must not wait for the
   5s poll). **Every transition to online first shows ONE consent popup**:
   what is about to happen, which hosts/categories will be contacted, and
   the machine's LOCAL interface IPs. We never fetch a public-IP echo
   before consent — that would itself be a network call while "offline";
   the popup says the public IP is whatever the ISP/VPN exposes.
3. **OS layer (opt-in, privileged, never silent) — INTERFACE-AGNOSTIC
   (maintainer correction 2026-06-11):** we hold no dom0/hypervisor
   privileges from inside an AppVM/DispVM — NetVM-detach is not ours to
   perform, and Qubes must not be special-cased. The cut operates on the
   interfaces the app's OWN environment exposes — the same enumeration the
   consent popup lists as local IPs — and works identically whatever
   stands behind them (a NetVM's virtual NIC, a direct router, a VPN
   tunnel):
   - **firewall drop-all** (nftables/iptables table added/removed by the
     helper): blocks **both directions, inbound included** — the precise
     answer to "we shouldn't receive packets either" — and re-enables
     cleanly without link flapping;
   - **`ip link set <iface> down`** for every non-loopback interface
     (takes VPN tun devices down with the rest);
   - `rfkill` demoted to a bare-metal *radio* bonus (virtual NICs have no
     radios);
   - Windows (`netsh interface set interface … disable` /
     `Disable-NetAdapter`) and macOS (`networksetup` / `ifconfig down`)
     equivalents behind the **one helper** (`oo-netcut`), per the
     universal-portability mandate.
   Elevation is explicit and narrowly scoped: a single operator-installed
   sudoers line for the helper, documented, never silent; where elevation
   is unavailable the button honestly shows app-level scope only.
4. **Honest limits, always stated:** we control the interfaces OUR
   environment exposes; whatever sits beneath (host OS, NetVM, router,
   VPN server) may remain online — the button names the layer it
   controls. A userspace app can never equal a hardware-wired webcam
   light, because software below it can be compromised; we say so
   wherever the switch is explained (same threat-model honesty as the
   at-rest encryption).

---

## Continuous collection & fair ordering (field report #2, 2026-06-11)

"The intent of this app is to scrap everything. Scraping should never stop"
— background auto-collect becomes the default **after an explicit first-run
approval** (one consent design with the network popup above; zero-network
boot is untouched — nothing moves before the operator says go).

- **Ordering (maintainer's question, answer adopted):** per-country
  round-robin, ONE source per country then repeat — country order shuffled
  each cycle (no alphabetical bias), least-recently-scraped source chosen
  within a country, per-host politeness delays untouched (rotation also
  spreads load across hosts — good citizenship). This breaks the US-volume
  bias structurally: equal turns per country, not per source count.
- **Explainable schedule:** the activity panel / task manager shows which
  country is next and why ("round-robin cycle 14, 37 of 92 countries
  served, next: ke — least-recently-scraped: nation.africa").
- **Onboarding picker (BOTH, not either):** a first-run step where the
  operator picks countries/languages to emphasise (weights, not
  exclusions — excluded regions are a coverage hole, stated as such in the
  Library's regional-balance panel). Feeds the same scheduler.
- Builds on the de-US-centred catalog (ISO-2 canonical countries) and lands
  together with the download-manager/task-manager arbitration so a
  continuous background pass and user-clicked jobs negotiate visibly.

---

## Seven remaining space-time scenario cards (3 of 10 shipped)

Shipped as recipes: **Promises-due** (card 2), **Edit-war seismograph** (card 8),
**Region gone quiet** (card 4's corpus-blind-spot core). Still future — each a
candidate recipe over the existing substrate, same bar (signals with provenance,
never verdicts):
1. **"The warnings existed"** — rewind the timeline at a hazard's location.
3. **Disputed chronology detector** — where outlets' date/place assertions
   disagree, surfaced as claims side by side.
4b. **News-desert atlas** (the map view of card 4; the producer shipped).
5. **Silent disasters** — hazard severity vs zero local coverage in the cell.
6. **Law-takes-effect watch** — effective-date → coverage window in that
   jurisdiction.
7. **Story-propagation tracer** — where each subsequent report appears over
   time; a press-freedom lens.
9. **Supply-chain ripple view** — commodity move + chain-located coverage.
10. **Election-window integrity desk** — region-hour record of *reported*
    irregularities, exportable.

Plus the standing queue item: a dedicated /investigate view per card TYPE so
every Home card is clickable into a dashboard.

---

## Article corpora — the flagship analysis object (maintainer-ruled 2026-06-11)

The reader rework and the corpora system are ONE design (ledger entries
2026-06-11): the dedicated article window gains tabs — **Mindmap · Related
articles · Source description · Keyword analysis · Sentiment analysis** (the
two-class metadata header already shipped). Then: select several articles
anywhere in the app → "create a corpus" → its own window with the SAME tabs
computed over all members, PLUS the corpus-only tab: **source competitive
analysis** — how each source approaches a concept (angle, framing, sentiment,
volume, timing) with real visual representations; single articles never get
that tab (n=1 has no competition). Tag-driven corpora (multi-tag AND-selection
in Sources → "make this a corpus") and hand-selection are two entries to the
same object. Honesty: every per-source figure carries method + caveat + n; no
composite "source quality" number ever (CardSchemaError discipline extends to
corpus views).

---

## Evidence-tiered cards — remaining slices

Slice 1 shipped (Card.trigger plain+math, Wilson/Katz CIs, 7 producers
instrumented). Remaining: instrument the other producers + recipes; the corpus
tier header (early/developing/established) on Home; power-style "what's missing"
inversions when a card does NOT fire; optional Benjamini–Hochberg once p-values
exist; the dismiss-with-reason local feedback loop and the card-diagnostics
export slice (the app's honest observational study of its own card quality).
Open ruling (audit U3): caveats visible by default vs the calm-UI toggle.

---

## Trans-language keyword equivalence — the LIVE-analytics layer

Groundwork shipped (language signatures in the diagnostics log; curated
`configs/keyword_equivalents.yml`; first 10 real rings from field log #1).
**Not yet built (verified): rings do NOT feed analytics.** The elevated design:
équivalents merge inside grouped trends/trending/associations/graph levels
(fr:élections + en:elections = ONE concept), with the cross-country case served
by splitting a ring's trend per source country/language. Guards: only
language-qualified members merge; a keyword joins a ring only when its language
signature supports it (else flagged ambiguous + unmerged); per-language counts
always visible; the user can split any ring. The local LLM may PROPOSE candidate
rings; a human confirms.

---

## Automated source discovery — the gated external channel

Offline channels shipped (citation promotion + catalog refresh, staged
candidates, budgets, activity log). Still future, by ruling only after the
staging UX proves out: the **DuckDuckGo query channel** behind the off-by-default
external-lookup gate, clearly labelled "this query leaves your machine",
per-query logging, individually toggleable, budgeted. Also future: running the
Wikidata catalog generator as a *scheduled refresh* instead of a manual script.

---

## Training & onboarding — two tracks (designed only)

Unchanged design, still unbuilt; revisit within 0.0.9:
1. **Autonomous in-app guidance** — first-run tour as dismissible Home cards
   reusing recipe deep-links; contextual "why" notes per tab (i18n-keyed); task
   recipes in the docs reader; an optional "are you set up safely?" checklist
   that informs, never gates. Guidance must teach the tool's LIMITS, not just
   features.
2. **Supervised training** — modular curriculum + facilitator guide (foundations
   → investigations → safety/opsec → ethics, the last two mandatory),
   train-the-trainer material, a synthetic exercise corpus, threat-model-first
   framing. In-repo and printable, never hosted.

---

## Wikipedia as a first-class source (still future, verified)

Make the offline Wikipedia corpus searchable and indexed like articles (FTS,
keyword associations, LLM summarise, link exploration) while keeping its
special-case handling for scale. Interacts with the database mandate above
(wiki snapshots must ride backups faithfully).

---

## Offline LLM kit (RM-08 release artifact)

A checksummed GitHub *release artifact* (never repo content): Ollama binary +
one small model, provisioned on a connected machine, carried by USB to
`~/.ollama/models`. The principled path for Tor/air-gapped operators (model
downloads don't work over Tor; inference is loopback and unaffected).

---

## Diagnostics channel — future slices

The keyword log + network log + debug bundle shipped. The pattern to extend
(maintainer↔assistant channel, always on-click, never automatic, counts and
structures never scores): per-vertical state snapshots (law/wiki/markets
tracking), the card-diagnostics slice (above), and field-log-driven catalog
pruning as a repeatable workflow.

---

## De-US-centring — the remainder (KEY POINT, first batch shipped 2026-06-11)

Remaining: run the Wikidata generator for the 73 named gaps (network step,
maintainer's machine — `scripts/catalog_coverage_report.py` prints the exact
targets); raise the located share (49% of domains carry no country); maintainer
ratification of the drafted `configs/catalog_targets.yml` floors; longer term,
extend the multilingual country-alias table from field logs.

---

## i18n completeness (ongoing)

The exact-match engine is sound; the long tail is tracked by
`scripts/i18n_report.py --audit-chrome` (burn down per-tab; Agenda first). Two
structural items from the audit: format-string support for composite strings
(`"${n} source(s)"` class, ~5% of chrome), and per-key translation provenance
(human-reviewed vs machine-drafted) in the locale `_meta`.

---

## Universal portability — Linux + Windows + macOS from ONE codebase (maintainer-ruled 2026-06-11)

**The ask:** available to all Linux, Windows and Apple users WITHOUT maintaining
three versions — a universal installer, a universal interface, and every fix
covering all supported OSes at once.

**Achievable? Yes — and the architecture already did the hardest part.** The
Console is a browser UI (universal on every OS today); the backend is Python
3.13 + FastAPI + SQLite (cross-platform by construction); the data directory is
already centralised (`src.paths`); assets/fonts are bundled. The honest
reframe of "universal installer": executable formats differ per OS — no project
escapes that — so the deliverable is **one codebase, one test gate, one release
action that emits all three installers automatically**. A bug fixed once is
fixed everywhere *by construction*, because CI proves the same code on all
three before any release exists.

**What is actually OS-specific today (audited 2026-06-11):** `install.sh` /
`launch.sh` (bash + whiptail), Linux `.desktop` launcher creation
(`src/diagnostics.py`, `src/safety/uninstall.py`), and two native-wheel
checkpoints to verify per-OS: `pqcrypto` (the optional PQC extra — Ed25519-only
fallback already degrades honestly) and the future SQLCipher driver (factor
this into the database batch's design!). Ollama exists on all three OSes; its
install path differs and the installer must adapt.

**The plan (phased, each honest and testable):**
- **P0 — CI matrix is the keystone.** Run the full suite on
  ubuntu + windows + macos runners. *The rule: an OS is "supported" when the
  suite is green there — no claim before that.* Fix what the matrix exposes
  (path separators, file-locking on Windows SQLite, signal handling). Cheap,
  do first; it converts "should work" into measured truth.
- **P1 — single-source installer.** Move the installer's LOGIC into the package
  itself (a `setup`/`doctor`-style Python command, written ONCE), leaving only
  two thin bootstraps whose sole job is "get Python, run the package installer":
  `install.sh` (POSIX) and `install.ps1` (Windows) — both wrapping `uv`
  (a single static binary per OS that provisions Python itself). The launcher
  layer becomes one Python module emitting `.desktop` (Linux) / Start-menu
  shortcut (Windows) / `.app` stub (macOS).
- **P2 — release automation.** A GitHub Actions release matrix builds and
  checksums per-OS artifacts from one tag. Honesty checkpoint: unsigned apps
  trigger Gatekeeper/SmartScreen warnings; Apple notarization and Windows
  signing cost money and identity — decide explicitly later, and document the
  checksum-verification path either way (this audience verifies hashes).
- **P3 — the PWA layer** (per the hosting stance) for interface install UX on
  every OS, the server still strictly local.

**Rejected paths, with reasons:** an Electron/Tauri wrapper (the UI is already
universal; a native shell per OS is exactly the triple maintenance the ruling
refuses); Docker as the primary path (wrong audience; fine as an extra);
bundling Python/runtimes in the repo (the 100 MB rule — release artifacts only).

---

## Hosting & mobile — the standing stance (ruled 2026-06-10)

> **Give away the software for free; never host the users' data.** No SaaS, no
> central server, no accounts, no telemetry. The forward path for reach is a PWA
> + one-click self-host (BYO-home tunnel as an option); centralized hosting is
> rejected. Any future mobile/remote-access work starts from this ruling.
