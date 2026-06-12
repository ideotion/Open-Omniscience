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
RULED 2026-06-12: caveats by design — visible by default, "informed consent" app-wide; translated hover bubbles carry the long form (layering, never hiding).

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

## Wikipedia as a first-class LIVING source — the law model (maintainer concept 2026-06-12; supersedes the earlier stub)

**The maintainer's concept (recorded):** Wikipedia articles must be ingested
with the SAME aggregation rules as journal-sourced articles — rich metadata,
content deduction (when × where × who), keywords/mentions, reader, corpora
membership. The structural difference: journal articles are write-once;
**Wikipedia articles are AMENDABLE over time — like the law**. Every change
must be reliably traceable, with perfect audit control.

**Honest current state (code-verified 2026-06-12, the gap that surfaced the
concept):** downloaded dumps are FILES only — never parsed into the corpus;
no keywords, no mentions, no deduction. Only WATCHED pages get the
baseline → revision → diff → flag treatment (wiki_pages/wiki_revisions),
and those revisions are tracking records, not corpus articles either.

**Design map (assistant, same date):**
- **One identity, many versions** — generalize the law vertical's model
  (document → revisions with content hashes, observed_at, diffs): a wiki
  page is ONE corpus identity whose VERSIONS are first-class, append-only,
  hash-chained (the custody discipline). Never overwrite: an amendment is a
  new revision, the old text remains evidence.
- **Version-anchored analytics (the audit-control heart):** every keyword
  mention, deduction and analysis records WHICH revision it saw ("as of
  revid N"). Re-indexing on change updates the live layer while the
  revision trail preserves what any past analysis was looking at.
- **Dumps become an ingestion source**: stream-parse the downloaded XML into
  the SAME ingestion pipeline (idempotent per (wiki, title, revid); bounded
  batches; a visible job with progress in the task manager). The dump's
  revid is the version anchor; the watched-pages live checks then diff
  FORWARD from it.
- **Same rules, stated provenance**: wiki-derived articles carry
  source-type "encyclopedia" with the wiki + revid + dump-of date; the
  reader's two-class header (source-asserted vs app-deduced) applies
  unchanged; self-name suppression and stoplists apply unchanged.

**QUESTIONS FOR THE MAINTAINER (answer when convenient — deliberately not
asked mid-session, per instruction):**
1. **Scope of dump ingestion:** ALL pages of a downloaded dump (enwiki ≈
   millions — would dwarf the news corpus and strain the 2-core reference
   VM), or a chosen subset (watched pages + their categories + top-N +
   search-hit-on-demand)? A measured tier table would come first either way.
2. **Analytics mixing:** should wiki keywords flow into the SAME trend/
   association pools as news by default (volume would dominate), or ship as
   a per-source-type layer the user can merge/split (the per-language-counts
   discipline applied to source types)?
3. **Version storage depth:** full text per revision seen (the law model;
   storage-heavy at wiki scale) or baseline + diffs with periodic full
   checkpoints?
4. **Change feed:** does the watched-pages tracker become THE change feed
   for ingested pages (watch = ingest), or stay a separate monitoring layer?
5. **Backups:** dump-derived articles are reconstitutable from the dump
   file — carry them fully in oo-backup-2, or reference the dump + carry
   only revisions/deductions?

Interacts with: the database mandate (versions must ride backups
faithfully), When×Where×Who at ingest (deductions per revision), and the
task manager (dump-parse as a visible, cancellable job).

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

---

## Voice-only mode — accessibility-first, useful to everyone (maintainer input 2026-06-12; designed-only, NOT committed work)

**The ask (maintainer, recorded):** a "voice only" mode designed for disabled
and handicapped users and useful for everyone. A big ask deserving deep
thought. It must carry **all the ethical constraints the GUI has** (informed
consent, honesty by construction, local-first). It must **not saturate** the
user with repetitive meta-information ("say X for more…") — rely on the
user's memory plus a single word, **"help"**, for contextual assistance.
Powered by **local models through/alongside Ollama** (speech-to-text and
text-to-speech exist today); users are guided through current technology's
limits (e.g. "don't speak until the listening tone"). Hardware limits and
prerequisites need serious thinking. Priority stays on current work.

**Design thinking (assistant, same date — a starting map, not a plan):**

- **The microphone is a consent surface.** Push-to-talk (or an explicit
  spoken session) is the default; never always-listening without a visible
  AND audible state. Earcons carry state honestly: one tone = "listening",
  another = "thinking", silence = "off". The webcam-light honesty rule
  applies verbatim: software can never equal a hardware mic LED, and we say
  so wherever the mode is explained. Hardware mute always wins.
- **Informed consent, spoken — once, not nagged.** Consequential actions
  (going online, deleting, merging) get a terse spoken consent with
  repeat-back ("Start a collection pass — say yes to confirm"), the voice
  analogue of `ensureOnline`. Caveats are spoken the FIRST time a surface is
  used in a session, then compressed to a single word marker; **"help"**
  re-reads the full contextual layer on demand.
- **One source of layered information.** The hover-bubble convention
  (invariant #17) and the voice "help" should read the SAME translated
  `title` strings — the GUI's layered-info corpus becomes the spoken
  assistance for free, ×12 locales by construction.
- **Honest tech-limits onboarding (spoken, once):** wait for the tone;
  numbers and proper nouns transcribe imperfectly; noisy rooms degrade
  recognition; per-language STT quality varies — the mode states which of
  the 12 locales its installed models actually support instead of implying
  parity (the language-parity honesty rule).
- **Local-only pipeline:** STT (Whisper-class), TTS (Piper-class), optional
  LLM intent parsing via Ollama — all installed like the offline LLM kit
  (clearnet stated as an install prerequisite; runtime stays loopback).
  Prototype path needs NO LLM: a small command grammar over the existing API
  (tabs, search, collect, readouts) + earcons; LLM intent parsing is a later
  layer, never a dependency for the basics.
- **Privacy:** audio is processed in memory and never persisted by default;
  transcripts are opt-in, stored like annotations (and then ride backups).
  NOTE: voice transcripts are PERSONAL data — the same no-recovery
  contingency recorded for newsletters applies here and must be revisited
  before transcripts ship.
- **Hardware prerequisites — measure, never assert:** concurrent STT + TTS
  (+ optional LLM) is the real budget; tiers must be MEASURED on reference
  shapes (the maintainer's 2-core Qubes VM is the floor: likely tiny-model
  STT with queued processing) and published as a minimum-spec table with
  method, not marketing numbers. Audio-stack portability (Linux/Windows/
  macOS) rides the universal-portability mandate; wake-word engines (e.g.
  openWakeWord-class, fully local) are optional and off by default.
- **Sequencing:** after the corpora/task-manager flagships; depends on the
  offline LLM kit (RM-08) for the principled model-install path. Candidate
  first slice: spoken readout of Home cards + search + "help", push-to-talk,
  one language, measured on the reference VM.


---

## IPCC as a source + prediction-tracking (maintainer concept 2026-06-12; designed-only)

**The ask (recorded):** ingest IPCC material as articles — reliable-seeming
but treated like ANY other source (the Wikipedia discipline: no assumed
authority), with the same When×Where×Who extraction. IPCC is climate-focused
and publishes MODELS/projections that may or may not come true: the app
could analyze **whether their anticipations were right after all**.

**Design thinking (assistant):**
- **Ingestion**: IPCC reports are large PDFs + HTML summaries on ipcc.ch —
  needs a PDF-to-text path (new capability; robots/politeness apply as
  everywhere). Chapters/sections become articles with full provenance
  (report, AR cycle, working group, chapter, page anchors).
- **Predictions as first-class dated claims**: the date extractor already
  finds future dates; a PREDICTION layer would store (claim text, horizon
  date/range, scenario label e.g. SSP/RCP, confidence wording AS PRINTED —
  the IPCC's own calibrated language, never our score).
- **The retrospective lens** (the maintainer's framing): when a horizon
  arrives, the promises-due pattern (shipped, 0.0.8) surfaces the claim with
  what the corpus + climate datasets show — co-occurrence and the record,
  NEVER a verdict; the reader judges. Scenario-conditional claims ("under
  RCP8.5…") must carry their condition — judging an unconditional miss on a
  conditional claim would be dishonest.
- **Data link**: the bundled climate dataset (El Niño episodes, shipped
  2026-06-12 with verification flags) is the first reality-series such
  claims can sit next to; more series (NOAA/Copernicus) only as
  provenance-carrying bundled datasets or official CSV feeds.
- **QUESTIONS FOR THE MAINTAINER (answer later):** which IPCC products
  first (AR6 SPMs? full WG reports? special reports)? PDF ingestion is a
  new dependency surface (pypdf?) — acceptable? Are predictions extracted
  automatically (lexical, noisy) or operator-curated from a suggested list?

## Agenda ↔ Wikipedia linking (maintainer ask 2026-06-12; designed-only)

Each agenda entry (astronomy, climate episodes, world events) can carry an
optional wiki page reference: one click opens the LOCAL wiki baseline (if
watched/ingested) or offers to WATCH the page (consented fetch) — never an
silent external jump (invariant #6/#7 apply). Builds on the
Wikipedia-as-living-source design; the event→page mapping ships as data
(per-locale page titles where they exist), with the usual provenance.


---

## Lunar-effects testing framework (maintainer concept 2026-06-12; series shipped, framework designed)

**The ask (recorded):** people around the maintainer are certain the moon
affects mood; old agricultural practice plants/harvests by waxing/waning.
The app should let users TEST such concepts against large datasets of
potential correlations between astronomical events and earth events.

**SHIPPED same day:** the daily lunar-phase series
(`/api/events/astronomy/lunar-series`): synodic age, illuminated fraction
(age approximation, ~2% — method stated), waxing/waning flag — one honest
variable derived from the verified Meeus engine, carrying the
correlation≠causation caveat in its own payload.

**The framework (designed; the scientific discipline is the product):**
- Correlate ANY daily series in the app (keyword mention volume, article
  counts, hazard counts, commodity prices) against the lunar series:
  Pearson/Spearman + a phase-bucket contrast (full±2d vs new±2d), always
  with n, p-value, effect size, method — the existing /api/analysis tools.
- **Multiple-comparisons control is NON-OPTIONAL for screening**: testing
  many series against the moon guarantees spurious hits; a screening run
  must apply Benjamini–Hochberg FDR (already queued for evidence tiers) and
  SAY how many tests were run. One-off tests state the same risk.
- **Pre-registration spirit**: the UI invites the user to state the
  hypothesis (which series, which phase contrast, which window) BEFORE
  running; the report records it verbatim (the methods-appendix pattern).
- **The honest posture**: the app neither endorses nor debunks — it runs
  the user's test on the user's data and reports real statistics. Published
  large-N studies on lunar effects (sleep, mood, births) mostly find null
  or tiny effects; the app must NOT bake that prior in — the user's corpus
  speaks for itself, with the stats discipline keeping it honest.
- Agricultural calendars (waxing/waning planting rules) become testable the
  same way once yield/series data exists locally; the lunar series is the
  shared substrate.

---

## Worldwide official-statistics ingestion (maintainer concept 2026-06-12; designed-only)

**The ask (recorded):** ingest government and international statistical data
worldwide — BLS (US), INSEE (France), Eurostat (EU), the World Bank, the
IMF, and deliberately also agencies tied to BRICS, Africa, and the
forgotten parts of the world. ALL statistical data is treated as
controversial and possibly politically oriented — like any other source —
with data source, date, and the producing state on every figure. The
approach must be mathematically oriented, scientifically sound, and
ethically impeccable.

**Design map (assistant, same date):**

1. **Source skepticism as schema.** Every series datapoint carries:
   producing agency, producing STATE or bloc, publication date, methodology
   reference (the agency's own published definition), unit, and the
   adjustment flags below. No series is ground truth; an agency's number is
   an ASSERTION with provenance — the reader's two-class discipline
   (asserted vs deduced) extends naturally: here everything is asserted,
   and BY WHOM is always one glance away (hover convention).
2. **Vintage honesty (the revision problem).** Official statistics are
   REVISED — GDP and employment figures change after first publication, and
   the revisions are themselves politically interesting. Store VINTAGES:
   the value as-published on each publication date (the law/wiki versioning
   model again — one identity, append-only versions). "What did the agency
   say X was, as of date D" becomes answerable; silent overwrites never
   happen.
3. **Comparability guards (the epidemiological discipline).** Definitions
   differ across producers (unemployment ILO vs national; deficit
   Maastricht vs national accounts). Cross-country/cross-agency charts must
   FLAG definitional mismatches and adjustment mismatches — seasonally
   adjusted vs raw (SA/NSA stated per series), index base years, nominal vs
   PPP, calendar effects — instead of silently comparing incomparable
   denominators. A comparison the data cannot support renders with the
   warning, or not at all.
4. **Acquisition: official machine-readable endpoints FIRST, scraping
   last.** SDMX (Eurostat, IMF, OECD, ECB, BIS), the BLS API, the World
   Bank API, INSEE's API — the markets CSV-feed pattern generalizes
   (catalog-driven configs/stats_sources.yml, per-feed robots/policy
   verdicts, transport-aware failures, retry discipline as shipped in T4).
   HTML scraping only where no machine endpoint exists, under the same
   EthicalFetcher rules.
5. **De-centring applied from day one.** The catalog deliberately includes
   BRICS-tied producers (IBGE, Rosstat, NBS China, MoSPI India, StatsSA),
   African national statistics offices + AfDB/UNECA, Pacific/Caribbean
   community statistics — and the coverage REPORT discipline (the
   de-US-centring acceptance metric) extends to the stats catalog:
   per-continent producer coverage is measured, gaps named.
6. **Triangulation, never averaging.** The same indicator from multiple
   producers (IMF vs national office vs Eurostat) renders SIDE BY SIDE with
   per-producer provenance — divergence is a SIGNAL to investigate, never
   noise to smooth away (the conflicts-keep-both rule from the merge
   engine, applied to statistics).
7. **Forecast tracking.** Agencies publish PROJECTIONS (IMF WEO, OECD
   outlooks, central-bank forecasts). These join the prediction-tracking
   lens designed for the IPCC: claim + horizon + conditions as printed;
   when the horizon arrives, projection sits next to outturn — the record
   speaks, the app never issues a verdict.
8. **Statistical hygiene everywhere:** SI/metric + the shared smart
   formatter; n and method on every aggregation; correlation screens
   against news/keywords inherit the lunar framework's rules (FDR control
   mandatory for screening, stated test counts, pre-registration spirit).
9. **Storage:** series generalize the commodity-price substrate (symbol →
   indicator code; market → producer), so the chart toolkit, the corpora
   correlation entries and the backup engine apply unchanged.

**QUESTIONS FOR THE MAINTAINER (answer later):** which producers/indicators
first (a starter set: CPI, unemployment, GDP, population from ~10 producers
across 5 continents?); vintage depth (all revisions vs first+latest);
SDMX needs an XML/JSON parser dependency — acceptable; storage budget at
the reference VM scale.

---

## Open-Meteo weather context — the When×Where corroboration layer (maintainer concept 2026-06-12; designed-only)

**The ask (recorded):** ingest Open-Meteo data into the when/where/who
approach — when articles talk about a drought, the claim might be checked
against this additional source. Keywords extracted from the DATA
automatically, associated with dates and locations; present in the back,
brought to the user's attention.

**HONEST OPINION FIRST (assistant, as asked):** "ingest the entire dataset"
is the one part to amend. Open-Meteo's historical archive is a global,
hourly, multi-variable GRIDDED REANALYSIS (ECMWF ERA5-based) — terabytes;
mirroring it contradicts local-first on the reference 2-core VM and would
duplicate a public archive for no analytical gain. The RATIONAL inversion:
**the corpus drives the weather, not the reverse.** T12 just persisted
exactly the keys needed — article_mentioned_places × mentioned dates — so
the app fetches bounded (place, window) SLICES on demand, caches them
locally, and grows its weather shadow only where the corpus looks. Value
stays, cost collapses, and every cached slice is provenanced.

**Honesty constraints specific to this source:**
- Open-Meteo historical = REANALYSIS: a model assimilating observations,
  not raw station readings — provenance must say "ERA5 reanalysis via
  Open-Meteo, grid ~25 km (11 km ERA5-Land)", and grid-cell vs city-point
  mismatch is stated.
- **"Confirm" is the wrong verb** — the layer CORROBORATES or shows
  tension, never confirms: "12 articles mention drought in X during May;
  the reanalysis shows precipitation at 31% of the 1991–2020 baseline over
  the prior 90 days (method, n)". Consistency of evidence, not truth.
- Anomalies, not raw values: drought-like signals need a STATED baseline
  (e.g., 1991–2020 climatology) and window; raw millimetres mislead.

**Keywords FROM data (the automatic extraction, ruled by explicit rules):**
threshold crossings on anomaly series generate DEDUCED signal-keywords —
"drought-conditions", "heat-anomaly", "extreme-precipitation" — each
carrying the exact rule note ("precip < 40% of baseline over 90 d"), the
(date, place) anchor BY CONSTRUCTION, extractor="open-meteo-derived", and a
distinct kind ("signal") so they never silently mix with text-extracted
keywords; ×12 display names via the locale mechanism. The When×Where×Who
joins then come free: text says drought (WHO said it) × data shows deficit
(measured) — the convergence engine's first cross-domain corroboration pair.

**Surfacing (back-stage by default, attention when it earns it):**
- The READER's deduced block gains a "weather context" row for articles
  with place+date (cached slice; consented fetch when absent).
- A Home producer: corpus-claim × data-signal co-occurrences ("drought
  mentions cluster in X while the deficit signal is active") — counts, n,
  method, the correlation≠causation line; CardSchemaError discipline.
- The temporal map can overlay the signal layer; the corpus window's Trend
  tab can overlay the anomaly series (ooChart multi-series exists).
- Never auto-fetched at boot; the collect pass gains an OPT-IN weather
  layer; every fetch is a visible job under the consent framework; the
  socket perimeter extends via the guarded path, not a new importer.

**QUESTIONS FOR THE MAINTAINER (answer later):** variables first
(precipitation, temperature, soil moisture?); baseline period (1991–2020?);
cache budget per corpus place; ToS posture (Open-Meteo is free
non-commercial, no key — fits, but stated); should signal-keywords feed
trends by default or as a toggleable layer (the wiki-mixing question again)?

**SLICE 1 SHIPPED (2026-06-12, maintainer-asked same day): the
if-this-then-SUGGEST corroboration cards.** A curated multilingual
climate-event vocabulary (`configs/corroboration_rules.yml`, provenance
in-file) is matched — locally, zero network — against indexed keywords ×
T12 place mentions × article dates; a qualifying cluster (≥3 articles, one
place, one window) produces a Home card in the *investigate* bucket that
OFFERS the check: "N articles mention drought near X in window W —
independent weather data could corroborate or challenge this." The fetch
happens only from the card's button, behind the one consent popup, as ONE
bounded (place, window) reanalysis slice through the single ethical fetch
path (kill switch, robots fail-closed, protected-mode proxy inherited);
results render per-variable (one chart per unit — mixed units on one axis
would be a fabricated comparison) with the CC BY 4.0 attribution, the
reanalysis-not-station-truth note, and the cache disclosed. Failures come
back as the T4 transport verdicts. This is the consent-first precursor of
the co-occurrence producer designed above: the producer never fetches; the
user always chooses.

---

## The Open Commons Mirror — a SISTER PROJECT (maintainer vision 2026-06-12; recorded, NOT committed work)

**The vision (maintainer, recorded):** if computing and storage were not a
limitation — a server-based approach where ALL cumulative open data is
reliably stored, with a reliable interface to the copied-and-guaranteed raw
data, carrying every tool this app has and will have; a web-based UI *and*
the offline local-first app over the same corpus; ambition explicitly on
the scale of archive.org, as a SEPARATE project branched from this one; a
business plan and fund-raising if that is what permanence costs. Intent,
verbatim in spirit: *bring the world an honest, unbiased, truth-seeking
tool that incorporates as much open data as possible and helps users figure
out what the truth is about events and the reality surrounding them.*

**The RELIABLE-MEMORY pillar (maintainer, 2026-06-12 — the project's
deepest stated intention, now told):** citizens cannot indefinitely trust
all governments with their data; data must be protected from manipulation
and tampering, voluntary or involuntary. A printed book, re-read years
later, is the same book — print cannot be silently rewritten. Digital data
on editable media is **unreliable by nature, not by design**; in this era
History — capital H, the science of understanding and deducing what
actually happened — needs a memory that cannot be quietly edited. The
local/offline design of THIS app was always the untold half of that
intention: a copy outside anyone else's reach, able to confront the web
when the web changes. "History is written by those who win wars" — the
project exists so that stops being true for the foreseeable future.

### Honest opinion (assistant, as asked — agreement first, then two amendments)

The vision is sound and the timing is right: the app's entire discipline
(provenance on every row, custody chains, signed evidence, vintages,
fail-closed ethics) IS a preservation architecture in miniature. But two
framings need amending to keep the project honest with itself:

1. **"The one and only source of reliable information" is the wrong target
   — on the project's own ethics.** A single authority is a single point of
   failure (technical, legal, governance) and a single point of CAPTURE —
   the exact structure the app's anti-single-origin/triangulation rules
   exist to detect. archive.org is the cautionary tale as much as the
   model: one organization, one jurisdiction — lawsuits (Hachette v.
   Internet Archive), a 2024 breach and DDoS, one board between the record
   and whoever wants it changed. The honest reformulation: **the most
   VERIFIABLE mirror, not the only one** — a federation where trust comes
   from anyone's ability to recompute the hashes, not from the operator's
   reputation. Aim to be the reference implementation and the first node,
   and to make node #2 trivially cloneable. "One and only" wins by
   monopoly; a commons wins by reproducibility. The METHOD is the ethics.

2. **The hosting non-negotiable survives intact — because OPEN data and
   USER data are different objects.** The ruling "give the software away
   free; NEVER host the users' data" is not contradicted by a mirror of
   PUBLIC open data (feeds, dumps, statistics, archives). The line to keep
   bright forever: the mirror stores what was already published to the
   world; user corpora, watchlists, annotations, queries stay local —
   the mirror must never even SEE them (verification must be possible by
   downloading, never by uploading the user's state). A sister project, a
   separate repo, a separate threat model; this app remains complete
   without it.

### The printed-book property, formalized (the math-based approach asked for)

Digital permanence is not achieved by trusting better hardware; it is
achieved by making tampering DETECTABLE first and IMPRACTICAL second.
Each mechanism below is standard, public mathematics — no novelty risk:

- **Tamper-EVIDENT (detection):** every object stored under its
  cryptographic hash (content addressing): any single-bit change changes
  the name. Collision resistance of SHA-256 is the printed page.
  *The app already does this* (article hashes, backup manifests).
- **Attribution:** signatures over manifests (who vouched for this capture,
  when) — the custody-chain discipline, generalized.
- **Append-only by proof, not by promise:** a Merkle-tree transparency log
  (the Certificate Transparency model, RFC 6962): inclusion proofs ("this
  capture is in the log") and consistency proofs ("today's log extends
  yesterday's — nothing was rewritten") are O(log n) and publicly
  checkable. Rewriting history then requires forking the log in front of
  every witness who holds an old root hash.
- **Tamper-RESISTANT (impracticality):** independent replication — LOCKSS'
  literal insight, "Lots Of Copies Keep Stuff Safe": one library's book
  can be doctored or burned; ten thousand copies across independent
  custodians cannot all be. Every local-first install of THIS app is
  already one such copy of what it captured. Witness cosigning (multiple
  parties co-sign log roots) makes a silent fork require collusion.
- **Existence-before-T:** anchoring log roots in external timestamp
  systems (OpenTimestamps-style) proves a capture existed before a date
  without trusting the mirror at all.
- **Against INVOLUNTARY tampering** (bit rot, media death, format
  obsolescence — decay is also an editor): scheduled fixity audits
  (re-hash and compare, statistically sampled), erasure coding across
  media and sites, format migration with the original bytes kept forever
  alongside any migrated rendering.
- **Vintages, never overwrites:** the law/wiki/official-statistics model
  generalized — a changed upstream is a NEW version next to the old one;
  revisions are evidence, deletion is an event to record, not perform.

**Honest limits, stated up front (no fabricated security — the ledger
rule applies to archives too):**
- The mirror proves *"source X published bytes B at time T"* — never that
  B is TRUE. Capture-time provenance is not veracity; propaganda archived
  perfectly is still propaganda (the triangulation tools exist for that).
- Nothing proves what existed BEFORE capture began; the record starts
  when the recording starts. (Reason to start early; not a flaw, a fact.)
- Signatures prove who signed, not that the signer was honest; the trust
  root is people and process — publish both.
- A single jurisdiction can compel one operator; only multi-jurisdiction
  federation answers that, and even it bows to coordinated force. The
  claim is "tampering is detectable and expensive", never "impossible".

### Relation to this app (the bridge, both directions)

- This app's users form the distributed library: opt-in, consented
  **capture contribution** (what a user chose to collect, minus anything
  personal, license-permitting) could seed the mirror — design later,
  consent-first, default OFF, nothing leaves without an explicit act.
- The mirror gives this app: a **verify-against-mirror** action (does my
  copy's hash match the public log? — divergence is a FINDING, the
  confront-the-web intention made one-click); a remote corpus backend
  CHOICE for users who want breadth beyond local disk (pointed at any
  node, self-hostable); and bulk open-data slices (the Open-Meteo /
  official-statistics scale problem) served from infrastructure built
  for it.
- Everything already shipped that generalizes: oo-backup-2 signed
  manifests + Merkle roots, custody chains imported verified-not-trusted,
  staged migrations, the vintage model, robots-first ethical acquisition.

### Sustainability (the business plan asked about, honestly)

Permanence is an endowment problem, not a revenue problem. Aligned models:
nonprofit foundation + open membership; grants (digital-preservation,
journalism, internet-health funders — e.g. NLnet/NGI-class, press-freedom
funds); memberships/donations (the Wikimedia/IA pattern); paid SERVICES
never paid DATA (priority API lanes, hosted analysis compute, support —
the data itself stays free forever, snapshots torrentable). Misaligned:
VC equity (exit pressure contradicts a permanence promise), advertising,
anything that monetizes reader behavior. If funds are raised, the
permanence promise must be structural (endowment, data escrowed across
independent nodes), not a pledge. Publish the business plan in the open.

### Node 0 — the maintainer's own machine (maintainer addition 2026-06-12)

**The decision recorded:** the maintainer offers a personal computer as the
first server — a cheap way to have a local solution, accessible through the
web, with **air-gapped, future-proof backups**; the whole idea lives in a
**NEW repository, a fork of this project — created only once the current
project is MATURE** (the maintainer's own sequencing gate; V0.1-and-beyond
comes first, the fork waits).

Why node-0-at-home is actually the RIGHT first step, on the project's own
terms: it proves the entire stack (capture → content addressing → signed
log → snapshot export → independent verification) at zero infrastructure
cost, and a self-hosted node is the purest expression of "we control our
copy". The **air-gapped backup is the strongest layer in the whole design**
— an offline disk cannot be remotely tampered with at all; it turns the
printed-book property literal (write, disconnect, shelve; fixity-check on a
schedule). Honest implications to design for, stated now so they are never
surprises:

- **Residential hosting realities:** asymmetric upload bandwidth, ISP terms
  (many forbid servers on consumer lines), dynamic IP, power/uptime — fine
  for node 0 + snapshot seeding (torrents tolerate downtime by design),
  wrong for "the" always-on public endpoint. Publish SNAPSHOTS + log roots
  rather than promising 24/7 interactive service from a home line.
- **Exposure:** a public server on a home connection points the world at
  the maintainer's house — IP, DDoS surface, and the personal-liability
  question land on one person. Mitigations to weigh: a cheap tunnel/CDN
  front (changes the trust story — state it), publishing through an
  existing host (torrent + IA + university mirrors) while the home machine
  stays the SIGNING origin, and moving legal exposure to a foundation
  before the node is loud. The home machine as quiet origin-of-truth +
  public distribution elsewhere is the sane v0 split.
- **Security posture for the box itself:** the server hosts OPEN data +
  signing keys — the keys are the crown jewels, not the data; keep signing
  on an offline/air-gapped step where practical (sign snapshots, then
  publish), so even a compromised web-facing box cannot rewrite history
  silently (the log + external witnesses catch it).
- **The fork inherits the constitution:** robots-first acquisition, honest
  provenance, no user data EVER (the web UI it serves must work without
  accounts; analytics-free), GPL, the no-fabricated-security rule — the
  fork is a deployment shape, never an ethics fork.

### QUESTIONS FOR THE MAINTAINER (answer when the sister project starts)

1. **Scope of "all open data" v1:** news feeds + Wikipedia dumps +
   official statistics + weather reanalysis are four very different
   beasts (size, license, churn). Which corpus FIRST proves the model?
2. **Legal home:** which jurisdiction(s) for the foundation and the first
   nodes? (This decides more about tamper-resistance than any algorithm.)
3. **Licensing posture:** mirror only license-clean open data, or also
   robots-permitted news HTML the way the local app does (a much harder
   copyright position at public scale)?
4. **Federation protocol:** plain rsync/torrent snapshots first (boring,
   provable), or content-addressed p2p (IPFS-class) from day one?
5. **Name and relationship:** branded as Open-Omniscience infrastructure,
   or a neutral commons several apps (including non-OO tools) can cite?
6. **The first witness set:** which independent parties co-sign log roots
   at launch — universities, press-freedom orgs, libraries?
7. **Node 0 specifics (added with the self-hosting decision):** which
   machine/OS and disk budget; tunnel/CDN front vs direct exposure vs
   quiet-origin+public-mirrors; the air-gap rotation cadence (how many
   disks, how often, stored where); and what "current project is mature"
   means concretely — the V0.1 RC gate, or a later milestone?
