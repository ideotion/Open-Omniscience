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
  - **Backups MUST include the downloaded Wikipedia dumps (ruled 2026-06-13,
    maintainer — REVERSES design D3).** The offline Wikipedia downloads in
    `data_dir()/wiki_dumps/` are today DELIBERATELY EXCLUDED from oo-backup-2
    (D3 "re-downloadable", listed in `_excluded_inventory()`,
    `src/backup/artifact.py`). That is now overruled: a restoring user must NOT
    have to re-download an entire Wikipedia library (multi-GB to tens of GB,
    brutal over Tor). MARKED FOR FUTURE DEVELOPMENTS — not implemented this
    session, per the maintainer's "implement now or mark it". Open design
    decisions when built: (a) **dedup by checksum** across backups so an
    unchanged dump is never re-stored, and decide whether dumps ride the MAIN
    artifact or a **separate companion artifact** so a user can still take a
    small/quick state-only backup honestly (the manifest stating which it is);
    (b) the **additive-restore merge must place FILE members** into `wiki_dumps`
    (the merge engine today merges DB tables, not on-disk files) — bit-identical
    dedup, never overwrite a differing local dump; (c) the **encrypted-artifact
    key rule still holds** (members protected by the artifact's OOENC1 envelope);
    (d) the manifest keeps listing what IS and ISN'T carried. Cross-refs: the
    superseding "edition-wide auto-track after a dump download" ruling (a dump is
    becoming the corpus BASELINE, which strengthens the case to preserve it) and
    the additive-only restore ruling.
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
tale). **RESOLVED 2026-06-16 (fork-2) — NOW ACTIVE: build the FULL "Watches view +
history" UX.** A saved watch (a conjunction over real stored signals) is evaluated
LOCALLY by the existing background analytics pass and surfaces a Lead card on a match;
PLUS a dedicated Watches panel — saved watches · match history · per-watch
enable/edit/delete. Off by default, local-only, NO notifications / network / telemetry.
The convergence frontend VIEW + the shipped `GET /api/insights/convergences` endpoint
(#231) are its substrate.

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

## Reliable Tor & per-source transport (maintainer concept + question 2026-06-13)

**The concept:** integrate a reliable, up-to-date Tor connection into the app
via an open-source library, enabling *per-source transport* — clearnet for
sources that block Tor, Tor for the rest — "to protect the user ID from other
sources." My honest, critical, scientific assessment (recorded for memory):

**1. The library landscape (honest maturity).** There is **no pure-Python
Tor** — Tor is C (or Rust via Arti). Python libraries *control* a Tor process,
they don't embed the network logic:
- **Stem** — the **official** Tor Project controller library (LGPLv3). Mature,
  reliable; can launch/manage a `tor` subprocess and read its bootstrap state.
  You still need a `tor` binary (user-installed, or bundled ~few MB like Tor
  Browser does). This is the pragmatic, reliable path **today**.
- **txtorcon** — Twisted/async Tor controller; same "controls a process" model.
- **Arti** — the Tor Project's **Rust rewrite**, an *embeddable* client crate
  (`arti-client`). This is the long-term answer to "embed Tor as a library."
  **But** as of the Jan-2026 knowledge cutoff its **Python bindings are
  nascent** and not a widely-used, battle-tested dependency — *verify current
  maturity before betting on it* (do not assert it's production-ready).
- **PySocks** (already a dependency) is only the SOCKS5 *client* — it talks to
  a Tor proxy, it is not Tor.

**2. The current model is the correct ethical baseline.** Today the user runs
and *trusts* a SOCKS proxy (e.g. Tor at `127.0.0.1:9050`); the app *uses* and
*verifies* it but **never claims to provide anonymity**. Embedding/managing Tor
would only **lower the setup barrier** (a real UX win) — it would NOT change the
guarantees, which still depend on Tor's properties + the user's opsec.

**3. The hybrid intuition — partly right, with caveats that forbid fabricated
security.** Per-source compartmentalisation is real: a clearnet source sees the
user; a Tor source does not. BUT clearnet for source A reveals, irreducibly:
the user's **real IP**, that they **run this specific app** (our honest bot UA
fingerprints it), and **their topic interest** — to A, to A's CDN/trackers, and
to the **ISP/network observer**. Cross-transport behaviour can also be
**correlated/linked**. So "protect the user from other sources" is only true for
the *Tor* sources; the *clearnet* sources fully identify the user. This is
exactly why **"never silently downgrade transport"** is a non-negotiable:
clearnet-for-some must be **explicit, per-source, consented, last-resort**, with
the UI **brutally honest** about what each choice exposes — never automatic,
never the default, never the headline feature.

**4. The superior alternative for "protect from other sources":** per-source
**Tor stream/circuit isolation** (`IsolateSOCKSAuth` — already our primitive,
used for parallel dumps) gives each source its own circuit, compartmentalising
*without any clearnet exposure*. Prefer this; it achieves the user's protective
intent without the deanonymisation cost.

**Direction (proposed, not yet scheduled):** (a) make Tor *easier* — an optional
in-app Tor setup (Stem-controlled `tor` process, à la the planned Ollama
installer), bootstrap progress shown, still "we use+verify, never guarantee";
(b) per-source circuit isolation **by default** when on Tor; (c) clearnet for
Tor-hostile sources only as an **explicit, per-source, consented opt-in** with
the full exposure stated; (d) keep the transport-aware verdict taxonomy (T4) so
a Tor block is surfaced honestly rather than auto-evaded. **Open questions:**
bundle `tor` vs require it vs wait for Arti's Python bindings to mature; whether
the honest bot UA should differ on a user-consented clearnet fetch; how to
visualise per-source transport state without implying anonymity we can't give.

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
**WIRED INTO ANALYTICS 2026-06-16 (slice 1):** `src/analytics/equivalence.py` is
the live consumer the file always lacked — équivalents merge inside the grouped
`top_terms` (`/api/insights/top?group=true`), `trending`/`trending-windows`, and
`associations`/`graph` (keyword + family levels), so `fr:élection + en:election +
de:wahl` is ONE concept. Honesty held: a keyword joins a ring only when its
EFFECTIVE language matches the member's (stored `Keyword.language`, else the
dominant `language_signature` — the signature-supported join, so en-dominant
"main" stays out of the fr `hand` ring); per-language counts stay visible
(`language_breakdown` + `members`); a user `KeywordFamilyOverride` split keeps a
member out; `OO_KEYWORD_EQUIV=0` disables. `tests/test_keyword_equivalence.py`.
REMAINING: the cross-country case (split a ring's trend per source country); the
map view; surfacing `language_breakdown` in the frontend; the local LLM PROPOSING
candidate rings (a human confirms) — the analyzer (PR #279) already emits ring
candidates from the diagnostics logs.

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

**RULED 2026-06-12 (the mandate made concrete; supersedes question 2 and
question 4 of this section — both answered YES):** Wikipedia articles appear
in GENERAL search results like any article; same keyword aggregator + same
When×Where×Who anchoring; the article PRESENTED is always the LATEST version
(default) with the change history available beneath it; an audit/track-change
ENGINE receives edits and materializes the latest version on demand; and the
wiki-article UI gains a DEDICATED tracked-changes tab — an interface for
scrolling through, discovering, exploiting and analyzing edits through time —
intuitive, genuinely smart, interactive, beautiful, and carrying every core
ethical principle (informed consent, math/science proof).

**BRIDGE SLICE SHIPPED (2026-06-12):** watched pages now enter THE corpus as
first-class articles — newest text (tracker-refreshed `latest_text`, revid
anchored, baseline fallback), one Article per page under a per-edition
"Wikipedia (xx)" source, bounded wikitext→plain strip (stated), indexed
through the one `index_article` hook so keywords + When×Where×Who follow
every edit; `POST /api/wiki/corpus/sync` backfills existing watchlists
locally. **The storage question (#3) is now the blocking one:** stored
revision diffs are truncated summaries, not reconstructable patches — past
versions cannot be materialized locally. Proposed default: per-revision FULL
TEXT (compressed; version-anchored analytics for free), with checkpoints+
patches as the lean alternative if storage proves heavy. The dedicated
tracked-changes tab is the named next slice (own session-grade attention).

**SUPERSEDING RULING (maintainer, 2026-06-12 — recorded for later, NOT
current work):** once a user has downloaded a language dataset (a dump), the
ENTIRE Wikipedia corpus of that edition is tracked **automatically — by
design and by default**. Per-article tracking is to be **retired**: "it will
not be used." The watch-a-page flow becomes unnecessary; downloading the
resource IS the consent-and-scope act.

*Filed comments & questions for when this is picked up (per instruction,
not asked now):*
1. **Scale honesty first.** "Track the entire edition" decomposes cleanly:
   the dump is the BASELINE for every page; the MediaWiki `recentchanges`
   feed is the DELTA stream (one polite poll covers the whole edition — no
   per-page requests). enwiki runs ≈80–160k edits/day; storing *metadata*
   for all of them is feasible on the reference VM (~tens of MB/day
   compressed), but per-revision FULL TEXT for the whole firehose is not.
   Proposed tiering (to confirm): metadata+flags for ALL edits; full text
   per revision only for pages that are IN the analytical corpus (cited by
   the user's articles, matching their keywords, or user-opened) — the
   corpus-drives-depth principle already adopted for weather.
2. **What does "tracked" mean for analytics?** All-pages keyword indexing
   of an entire edition = millions of articles through the extractor —
   likely a staged, visible, resumable job with disk/time estimates stated
   up front (the dump reader already proves local page access; indexing is
   the heavy half).
3. **Consent surface:** the download consent popup should SAY "downloading
   this edition starts automatic change-tracking for it" (one consent, the
   T15 pattern); the task manager shows the tracker as a visible job.
4. **Retirement path for per-article watching:** keep read-compatibility
   for existing watchlists (their data migrates into the edition-wide
   model); the Desk lesson applies — capabilities (flagged-edit review,
   ORES enrichment) survive the UI that exposed them.
5. **Politeness:** recentchanges polling cadence per edition, and whether
   Wikimedia EventStreams (SSE) is acceptable within the single-fetch-path
   ethics (it is HTTP, robots-checkable, one connection — likely yes).

## Offline LLM kit (RM-08 release artifact)

A checksummed GitHub *release artifact* (never repo content): Ollama binary +
one small model, provisioned on a connected machine, carried by USB to
`~/.ollama/models`. The principled path for Tor/air-gapped operators (model
downloads don't work over Tor; inference is loopback and unaffected).

### In-app Ollama + model installer (maintainer ask 2026-06-13) — PROMOTED TO ACTIVE 2026-06-16

**Build now as a dedicated Settings SUBTAB** (the 2026-06-16 rulings Q7=B / Q8 / Q9 /
Q10 in CLAUDE.md apply): download + verify (checksum/signature) + RUN the official
per-OS Ollama installer behind consent + a VISIBLE elevation step (never silent); a
curated dated catalog PLUS a consented searchable live-ollama.com-library browse filtered
to app-applicable text-generation models that fit the measured hardware; pull / run /
remove streaming real bytes (task-manager jobs); the active model becomes a stored UI
setting; clearnet-via-the-ollama-process is disclosed at consent.

Settings should let the user **install Ollama and pull models from the GUI**
— no terminal. Design intent:

- A **Settings → LLM** panel: detect whether Ollama is installed and running
  (loopback probe, already done by `src/llm/ollama.py`); if absent, offer a
  guided install (download the official binary per-OS, checksum-verified,
  consented like any network action), then a model **catalog picker** (the
  existing date-stamped `CATALOG_AS_OF` catalog: size, RAM need, license,
  language coverage shown per model — never a quality score).
- **Pull progress is a task-manager job** (reuse the download subsystem /
  task-manager window from SCRAPING_AUTOMATION_PLAN.md — model pulls are just
  another download kind: queue, pause, progress, honest verdicts).
- **Honesty:** clearnet is a stated prerequisite for model downloads
  (non-negotiable: no bundling models in the repo, 100 MB limit); the
  Tor/air-gapped path stays the USB kit above. Hardware fit is **measured,
  never asserted** (probe RAM/cores, warn honestly before a too-big pull).
- **Guardrails:** the Ollama binary is fetched through the one guarded
  socket factory (consent + kill switch + checksum); inference stays
  loopback-only; nothing auto-installs.

---

## In-app self-update — keep the corpus and settings safe (maintainer ask 2026-06-13) — PROMOTED TO ACTIVE 2026-06-16 (MECHANICS ONLY)

**Build now: the gated snapshot→verify→staged-migrate→atomic-swap→rollback MECHANICS,
default OFF.** The 5 OPEN QUESTIONS below remain a maintainer ruling and are SKIPPED by
the unsupervised session — a fully verified auto-updater needs a maintainer-supplied
trust root / signing key, so it cannot be completed unattended.

"Can the app update itself through the GUI — download the updated GitHub
repo, launch the reinstall, keep the database and all settings safe?"
Yes, and it fits the existing reliability machinery. Designed-only; the
data-safety bar is the same as the backup/restore mandate ("if it's not
entirely reliable, it should not exist").

**The shape:**

- **Check** (consented, on-click, never silent): query the GitHub Releases
  API / the repo's tags for a newer version than the running one (version is
  single-sourced from pyproject — the comparison is honest). Show the
  changelog (`docs/CHANGES.md`) for what would change. Through the one
  guarded socket factory; off by default; zero-network boot preserved.
- **Pre-update safety net (non-negotiable):** before touching code, take the
  **signed oo-backup-2 artifact** (the shipped backup engine) of the corpus
  + custody + settings, and snapshot the current install (so a failed update
  rolls back to the exact prior tree). The user's data dir lives *outside*
  the code tree already, so code replacement never touches it.
- **Apply:** fetch the new release (checksum/signature-verified — we already
  sign artifacts; verifying our own releases is the same Ed25519 path),
  install into a new tree, run DB migrations **on a staged copy first** (the
  alembic-on-staged-files discipline already shipped — never migrate the live
  DB in place), verify (schema + FTS count + a boot smoke), then atomic-swap
  and relaunch. On any failure: roll back to the snapshot, surface the honest
  verdict, never leave a half-updated tree.
- **Settings & keys survive by construction:** settings/annotations/events
  are being migrated into DB tables (D1/D4 riders) which the backup already
  captures; signing keys are re-wrapped by the encrypt tool. The encrypted
  corpus is never silently decrypted across an update (the crown invariant).
- **Migration direction is forward-only and reversible-by-snapshot:** we do
  not promise down-migrations; we promise the pre-update snapshot restores
  the prior version byte-for-byte.

**Open questions (for maintainer):** (1) update channel — track the default
branch, tagged releases only, or a user choice? (2) signature trust root —
ship the maintainer's public key in-tree so releases are verified offline?
(3) auto-check cadence vs. fully manual? (4) for `curl|bash` installs vs.
git clones, does update re-run `install.sh` or do an in-place tree swap? (5)
how does self-update interact with the Open Commons Mirror's tamper-evident
ethos — should each update anchor its release hash?

---

## Geo / offline mapping (PROMOTED TO ACTIVE 2026-06-16)

Two pieces, both LOCAL-first and zero-network at boot:
- **OSM per-region download manager** — download OpenStreetMap extracts (e.g. Geofabrik
  region PBFs) managed EXACTLY like the Wikipedia dump downloads: its own task-manager
  job, files (no DB-writer contention), parallel, a reorderable single-download queue,
  per-job rate / % / ETA / pause / resume / prioritize / bandwidth-cap, and INLINE DATED
  size estimates (a bundled `OSM_SIZES_AS_OF` table + freshness test — the model-catalog
  pattern; NO N network probes at open) with one consented "refresh exact sizes" call
  through the guarded factory. Robots / kill-switch / honest-UA inherited; clearnet stated.
- **Hand-rolled offline vector map renderer** — render the downloaded extracts (and the
  existing bundled Natural-Earth coastline + gazetteer pins) with a LIGHTWEIGHT,
  HAND-ROLLED canvas 2.5D / CSS-3D approach — NO WebGL, NO Three.js, NO map-tile CDN
  (parity with the 3D-keyword-explorer fork + local-first). Deterministic; the temporal
  map's projection (`lon2x`/`lat2y`) is reused, not forked.
- **Temporal-map remainder:** the linear/log time-scale toggle (labelled ticks, no
  hidden warp) + feed the mention layer with EVENT-places (today it plots
  article-mention places only).

Honesty: an offline extract is a SNAPSHOT (dated, stated); never presented as live.

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

### Blockchain — the maintainer's initial intention (recorded 2026-06-12)

**Recorded:** the long-term server approach was initially conceived on
**blockchain technology**, for tamper-proof reliability. The instinct is
right — and the honest engineering read keeps it useful:

- **The math above already IS blockchain-class.** Hash chains, Merkle
  trees, signed append-only logs, agreement on the current head — a
  permissioned blockchain and a witness-cosigned transparency log are
  close cousins; Certificate Transparency is essentially "a blockchain
  without the token": named, accountable witnesses instead of anonymous
  consensus. Choosing the transparency-log formulation is choosing the
  same cryptography with fewer moving parts, not rejecting the idea.
- **The strongest, cheapest blockchain use: ANCHOR INTO one, don't run
  one.** OpenTimestamps-style commitment of the log's root hash into
  Bitcoin (and optionally other public chains) buys existence-before-T
  proofs backed by a security budget (the chain's accumulated work) this
  project could never fund itself — no tokens, no validators to govern,
  one cheap transaction anchoring unlimited documents per batch, and the
  proof verifies forever without trusting us OR the timestamping service.
- **A DEDICATED chain is the option that must justify itself, not the
  default.** The data cannot live on-chain either way (terabytes — every
  chain design stores hashes and keeps bytes off-chain, which is exactly
  the content-addressed store + log above). Proof-of-work at small scale
  buys no security; proof-of-stake imports governance-by-wealth; a
  permissioned BFT chain among known institutions ≈ witness cosigning
  with extra machinery. The scenario that would genuinely demand a chain
  — Byzantine agreement among mutually-distrusting anonymous operators —
  is not the federation described here (named libraries, universities,
  press organizations). Revisit if that changes.
- **Wording discipline regardless of substrate** (the no-fabricated-
  security rule applies to marketing too): the public claim is "tampering
  is publicly DETECTABLE — proofs anyone can recheck — and practically
  infeasible to hide", never "tamper-proof"/"impossible". No real system,
  blockchain included, earns the absolute.

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
8. **Blockchain anchoring (added with the blockchain intention):** which
   public chain(s) to anchor log roots into and at what cadence
   (OpenTimestamps batches make daily anchoring ~free); and is there any
   concrete federation scenario — mutually-distrusting anonymous
   operators — that would justify a dedicated chain over witness-cosigned
   transparency logs?

---

## User-centric reflections — scenarios, contradictions, deduced features (maintainer-asked 2026-06-12)

> The brief: step back from the build queue, reason from USERS — especially
> users *without* a scientifically sound approach — through contradictory,
> critical reflection, and deduce what the app still owes them. Companion
> piece: `docs/audit/07_TRANSVERSAL_AUDIT_V01.md` (the systems half).
> **THE ACTION PLANS live canonically in
> `docs/product/V01_ALPHA_ACTION_PLANS.md`** — both plans in full, every
> step with its rationale + commentary + acceptance criteria, plus the
> maintainer's verbatim commission for recall. This section keeps the
> REFLECTIONS (scenarios + contradictions) the plan was deduced from.

### The scenarios reasoned from

- **S1 — The journalist** (the design persona): traces a claim to its
  origin, exports signed evidence. Well served by custody/lineage/links;
  still lacks a CLAIM-level workspace (the unit of an investigation is a
  claim, not a keyword).
- **S2 — The curious citizen** (the maintainer's stated focus): arrives
  with "I saw X — is it true?", no method training, no patience for
  statistics. TODAY the app answers with instruments (trends, cards,
  corpora) but not with a GUIDED PATH from question to defensible answer.
  This persona carries the app's biggest risk AND its mission.
- **S3 — The researcher/analyst:** wants reproducibility, method notes,
  exports, multiple-comparison discipline. Mostly served; needs versioned/
  saved analyses ("what I ran, on which corpus state").
- **S4 — The at-risk user:** safety mode, Tor honesty, at-rest encryption
  exist; needs workflow-level guidance more than more switches.
- **S5 — The educator/student:** the app is a media-literacy instrument
  that doesn't yet know it — guided comparative exercises are one recipe
  away.
- **S6 — The non-Anglophone / Global-South user:** 12 locales and
  de-US-centring help; the deeper gaps are analytical (see audit: tone
  analysis is English-only; CJK keywords effectively absent).

### The contradictions faced honestly

- **C1 · A sample sold as a world.** Local-first means every corpus is a
  SAMPLE shaped by one person's choices, while the app's promise sounds
  like "the world as it really is." The tension is permanent; the cure is
  not more data but PERMANENT VISIBILITY of the sample's shape.
- **C2 · A bubble-amplifier wearing honesty labels.** The user picks the
  sources; the analytics then faithfully describe the bubble. Method
  labels do not break the loop — only making the corpus's skew IMPOSSIBLE
  TO MISS does (and even then, gently: selection stays the user's).
- **C3 · No verdicts, but users came for verdicts.** Refusing trust scores
  is right and non-negotiable; S2 still deserves an ANSWER-SHAPED output.
  The resolution: answer with a structured EVIDENCE TRAIL (who claims,
  how independent the paths are, what corroborates, what tenses, what is
  missing) — a verdict's rigor without a verdict's arrogance.
- **C4 · Caveats by design vs cognitive room.** Already ruled (layering,
  hover bubbles); the remaining duty is rhythm: first-contact surfaces
  must breathe, depth one hover away.
- **C5 · Words are not meaning.** Lexical extraction counts "no drought"
  as a drought mention, counts quotation as endorsement, and misses
  sarcasm entirely. Cheap fixes don't exist; HONEST LABELING and modest
  heuristics (negation windows, quoted-speech flags) do.
- **C6 · Every consented fetch is also a disclosure.** Fetching weather
  for the places your corpus mentions tells the weather host what your
  corpus mentions. The consent popup names the action; it should also
  name THE SHADOW (what the queried host could infer).

### Deduced features (Action Plan A — the user-guidance track)

A1. **The Claim Workspace** *(flagship; S2/S1; resolves C3).* One entry:
    paste/select a claim → the app walks a stated pipeline: ① find related
    corpus articles (FTS) → ② group them by INDEPENDENCE (lineage + shared-
    origin links: three echoes of one wire = one path, said) → ③ timeline
    of who-said-what-when → ④ corroboration offers (weather now;
    statistics/IPCC later; each consented) → ⑤ the "what's missing"
    checklist (which countries/languages/source types are silent; what
    data WOULD discriminate the claim) → ⑥ export the trail (signed).
    Every step carries its method sentence; the output is an evidence
    trail, never a verdict. Most of the machinery exists — this is
    composition, not invention.
A2. **The corpus passport.** A constant compact strip on every analytics
    surface: n articles · sources · countries · languages · date-span of
    WHAT THIS VIEW WAS COMPUTED ON (resolves C1; extends the n-shown
    discipline from numbers to identity).
A3. **"Your lens" view** *(resolves C2).* One dedicated surface unifying
    the existing diet/coverage signals: composition vs DECLARED baselines,
    single-origin share (links substrate), wire-dependence share
    (lineage), echo share, collection-time regularity — descriptive,
    never auto-corrective, with one-click "broaden" suggestions from the
    catalog's under-represented regions.
A4. **Guided investigations as TEACHING recipes** *(S5/S2).* Narrated
    multi-step recipes chaining real tools ("Follow a story to its
    origin", "Watch one event through five countries", "Test a folk
    belief with FDR discipline" — the lunar framework as curriculum).
A5. **The Socratic empty state.** Wherever data cannot answer, say what
    WOULD be needed (sources, time, places) instead of showing thin
    results that invite over-reading; generalizes the power-style
    "what's missing" already queued for evidence-tiered cards.
A6. **Mention-context honesty** *(C5).* Slice 1: a stated lexical-limits
    caveat on keyword surfaces (cheap, ×12). Slice 2: negation-window and
    quoted-speech FLAGS on mentions (heuristic, per-language, labeled as
    heuristics; counts shown split). Research note filed for further.
A7. **The metadata-shadow line in consent popups** *(C6):* one sentence
    naming what the queried host could infer from the request pattern.
A8. **Saved analyses with corpus-state stamps** *(S3):* a re-runnable
    record (query, params, corpus passport at run time) — reproducibility
    for one's own past conclusions; pairs with the signed evidence path.
A9. **"What changed since I last looked"** *(S2 retention, honestly):* a
    since-last-visit diff of the corpus (new sources' first articles, new
    flagged edits, watch-rule hits when those land) — facts, not a feed
    of opinions.

*The full ACTION PLAN built from these features — step order, rationale
per decision, my commentary, acceptance criteria, dependencies — lives in
`docs/product/V01_ALPHA_ACTION_PLANS.md` (Plan A).*

---

## Elections & the civic vertical — evidence trails, never a verdict (maintainer concept 2026-06-15; designed-only)

**The concept (maintainer):** make elections the flagship civic use case for the
everyday person — list upcoming election dates and campaign windows in the agenda,
and a LOCAL, LLM-LESS analytics layer (keyword + When×Where×Who + the corpora
flagship) to help a citizen detect trends and stories and broaden their OWN
perspective on a vote (candidates, candidate-corpora, framing). Audience-widening;
deeply on-mission (press-freedom, anti-single-origin, "History must not be silently
rewritten"). Builds almost entirely on EXISTING substrate (agenda dates, WWW
extraction, the corpora window, trends, links/lineage, source-competitive) — a
COMPOSITION plus a curated data layer, not a new engine.

**Three framing INVERSIONS (the honesty conditions; without them the feature
betrays the constitution):**
1. NOT "politically neutral" → **plural & transparent about its OWN bias.** The
   transversal audit §5 already ruled neutrality undefinable; never claim it. An
   election corpus inherits every known app bias (US-centric catalog, English-only
   VADER, robots-permissive survivorship, install-time recency) and in elections
   those can move votes. The banner is REPRESENTATION-against-declared-baselines —
   the "Your lens" dashboard (feature A3) applied to the election corpus — never
   "neutral". A tool that BELIEVES it is neutral stops disclosing: more dangerous
   than one that knows it is biased.
2. NOT "tell the user what's happening / their voting implications" → **evidence
   trails they navigate themselves** (the Claim Workspace, feature A1). The app is
   a lens, never a verdict, never voting advice. The LLM-less constraint is the
   ASSET: no generated synthesis = no smuggled slant; the user synthesizes, the
   app sources + does the math.
3. NOT "detect candidates / sentiment / momentum" → **curated sourced scaffolding
   + descriptive, caveated analytics.** NO horse-race number ever; NO auto-detected
   candidate lists; NO per-candidate sentiment verdict; NO poll-of-polls forecast.

**Mention-volume must be FOUGHT, not footnoted.** The analytics stack measures
coverage volume + keyword momentum; an everyday reader reads "Candidate X has 3× the
articles, rising" as "X is winning / better". That is popularity + recency bias
weaponised — in elections even correlation misleads (more coverage = more
controversy / media access / incumbency, not support). The honest line is **name the
shape, never prescribe it**: show the distribution + concentration (Gini/entropy),
single-origin-discounted, and explicitly DECLINE to divide by any "should" baseline,
because none is honest for candidate coverage (poll share is circular; last-vote
share bakes in incumbency; equal-time is the false-balance fallacy). Naming the
refusal IS the honesty, not an omission.

**Candidate rosters are CURATED, never deduced.** The entity extractor is lexical,
no disambiguation, "deduced, never confirmed" — auto-listing candidates would merge
same-names, surface pundits/family as candidates, over-rank the incumbent, hide
minor candidates; omitting or mis-ranking a candidate is itself a political act. The
roster is the SAME two-class model as the reader header: each candidate carries a
STATUS (presumed / declared / officially-nominated / withdrawn / disqualified) +
PROVENANCE (who says so, as of when, which source). Handles captured electoral
commissions (the state source is ONE claim among several, never ground truth) and
pre-nomination "presumed" runners (France 2027 today: zero officially nominated,
obvious presumed runners). Candidacy itself becomes evidence, not fact.

**The honest first slice (lowest risk, highest certainty, pure data):** a sourced
**elections calendar** in `configs/world_events.yml` — a new `elections` calendar,
`category: political`, `tags: [election, democracy, <ISO2>]`, each entry the
electoral-commission `official_url`, `confirmed: false` + a `note` for not-yet-fixed
exact dates (the summits pattern), movable-marked. Gives "France 2027 presidential —
campaign window open" in the agenda today, subscribable as a smart-calendar tag query
("all elections in Africa"), with zero fabrication. SCOPE DISCIPLINE: a wrong date
the user trusts is worse than no date — ship a sourced DATE calendar before
pretending to hold candidate registers for 190 countries; pilot ONE election
end-to-end (France 2027) before generalising, because the per-country
contested-source problem is exactly where honesty breaks.

**"Election-window integrity desk" (the 10th scenario card) — DROP the branding,
keep the capability.** "Integrity" presupposes integrity-to-measure and rings the
bell for fraud-narrative crowds; the same data (reports of irregularities,
single-origin-discounted, claims-as-claims) is SAFER served by the general
claim-provenance / single-origin tooling (the manipulation-pattern cards below)
applied to election claims, with NO special "integrity" label. The word is the
liability.

**The everyday-person PARADOX (recorded honestly):** the honest tool withholds the
simple confident answer ("who's winning") the everyday audience walks in for — it is
cognitively HEAVIER for exactly the audience the feature means to add. Resolution:
CHANGE THE PROMISE from "tells you who's winning" to "shows you how to read the
coverage yourself, and catches the manipulation aimed at you", delivered through the
guided Claim-Workspace layer + informed-consent-by-layering. If that guided layer is
not excellent the feature fails its own goal (the user reads the volume chart as a
scoreboard anyway). The UX is the ethical load-bearing wall, not polish.

---

## Poll analysis — auditing METHOD (near-neutral), never adjudicating RESULTS (maintainer concept 2026-06-15; designed-only)

**The seam that makes it tractable:** critiquing a poll's METHODOLOGY rests on survey
science (Schuman & Presser, AAPOR), not political values — "double-barrelled" is a
linguistic fact, "3 favourable options vs 1" is arithmetic, "a +2 'lead' inside ±3
MoE" is statistics. So for METHOD the app gets closer to neutral than anywhere else.
Touch RESULTS (is 42% right, who is "really" ahead) and neutrality is gone. The whole
design stays strictly on the method side of that seam.

**The build is a TIER STACK; build Tier 2 FIRST — it is the substrate the rest
stands on** (Tier 4 can't judge a within-margin "lead" without the margin, which is a
Tier-2 disclosure field; when the margin is absent, Tier 4's only honest output IS a
Tier-2 finding):
- **Tier 1 — Provenance & funding** (factual, high confidence): commissioner vs
  field house; sponsor type (campaign / PAC / advocacy / media / academic); how many
  outlets reported it and whether they trace to one press release (links/lineage
  single-origin); house effects computed EMPIRICALLY from the corpus over time (the
  trend/concentration machinery — measured, not asserted).
- **Tier 2 — Transparency scorecard + verbatim question/answer DISPLAY** (the
  foundation, the most-neutral layer, and its OWN everyday hook). A CHECKLIST (never
  a composite score — CardSchemaError) against a bundled sourced standard (AAPOR
  Transparency Initiative / British Polling Council / ESOMAR — provenance per rule):
  sponsor, field house, n, frame, mode, field dates, MoE, FULL QUESTION WORDING,
  ANSWER OPTIONS, weighting, crosstabs — each present/absent. AND, when the data
  allows it (maintainer-prioritised 2026-06-15), DISPLAY the verbatim question + the
  answer-set STRUCTURE: amount of options, type (binary / Likert / forced-choice),
  balance (favourable vs unfavourable count), presence/absence of a neutral middle
  and of "don't know". This is a FACT, not a judgement — countable, language-AGNOSTIC,
  judgement-light — so it belongs in the foundation (displaying ≠ judging) and is the
  strongest honest signal there is. Headline example: the missing "don't know" /
  forced binary manufactures false certainty and almost nobody notices.
- **Tier 3 — Wording semantics** (loaded language, leading frames, push-poll
  signature): lexical, English-first (the same wall as VADER), HIGHER risk →
  layered/deferred. Each flag = pattern + the cited methodological principle + the
  exact text, "you judge"; never "this poll is biased".
- **Tier 4 — Result-reporting integrity** (catch journalism over-reading a tie: a
  within-MoE gap reported as "surges ahead"; a trend claimed from noise; a
  cherry-picked crosstab). Pure statistics (|A−B| vs MoE), the most everyday-useful,
  but it points the lens at JOURNALISTS not pollsters → build AFTER Tier 2 earns
  even-handed-method-auditor credibility, on the same metadata extractor Tier 2
  builds.

**Load-bearing rules (the honesty spec):**
- **No composite "poll quality score"** — a checklist + flags, never a number
  (CardSchemaError).
- **Non-disclosure ALWAYS outranks disclosed-imperfection.** The disqualifier is
  OPACITY, never disclosed-ugliness: a pollster who PUBLISHES an embarrassingly
  leading question is MORE useful than one who hides everything (you can SEE the
  leading question). "Bring useless polls up front" = bring the OPAQUE/unprovenanced
  ones up front, never the ones whose flaws we could only find because they were
  honest enough to show their work. Otherwise we punish transparency and reward
  hiding — exactly backwards.
- **Never LABEL a poll "useless"** — surface a glanceable DISCLOSURE FLOOR (named
  funder, published wording, stated MoE, real n, >1 independent report) and let the
  user conclude in two seconds. The two halves cover every case: wording published →
  lead with the verbatim question + answer-structure facts; wording absent → the
  floor catches it and "wording not published" IS the front-and-centre finding.
- **Per-language capability caveat** on anything semantic (Tier 3 / sentiment).
- A "poll" is an INSTANCE of the worldwide official-statistics ingestion pattern
  (methodology-ref per figure; VINTAGES = a pollster's series over time = its house
  effect; comparability guards = never compare phone-vs-online silently;
  triangulation side-by-side NEVER averaged = why there is no forecast). Not a
  bespoke subsystem.

---

## Manipulation-pattern card models — detect STRUCTURE, never deception (maintainer ask 2026-06-15; designed-only)

**The necessary reframe** (the literal premise "autonomously detect disinformation"
is both impossible and unethical): you cannot detect manipulation/deception with
keywords + sentiment — nor reliably with frontier AI — because it is a claim about
INTENT + TRUTH, which are not in the text; any tool that LABELS content
"disinformation" is a censorship engine that floods false positives (satire,
advocacy, honest-but-emotional reporting) while missing every well-written lie. So
the app NEVER detects deception. It detects STRUCTURE and PROPAGATION — observable,
countable, reproducible facts about how content is shaped and how it moves — and
shows them; the user supplies the interpretation. This single shift delivers three
requirements at once:
- **It is why this can be AI-FREE, and AI-free is the ETHICAL ASSET here:**
  structural signals are fully explainable/auditable; an AI detector is a black box
  encoding its trainers' bias. A centralised AI disinformation-detector is itself one
  of the "superpowers" to fear (a single point deciding truth for everyone,
  capturable). The local / transparent / reproducible / verdict-incapable
  architecture IS the ethical answer to that threat.
- **It is where NEUTRALITY actually comes from:** structural signals are politically
  INVARIANT by construction (a double-barrelled question is double-barrelled whoever
  wrote it; near-identical text from a hidden common origin is that regardless of
  side). Forbid any detector that keys on a TOPIC or viewpoint word. SELF-AUDIT the
  flag distribution (does it disproportionately fire on one country/language/side? =
  a hidden detector bias) like the catalog-bias self-audit — neutrality MEASURED, not
  asserted.
- **A description cannot be a false accusation:** "47 sources, near-identical text,
  common origin not disclosed, within 12 min" is simply true.

Sentiment is the JUNIOR partner: English-only VADER, no negation/sarcasm → never a
primary flag, only baseline-relative + secondary, useless outside English until
per-language lexicons exist. Keywords + structure carry the load.

**THE SHARED SPINE** (all nine cards reuse four statistics — few primitives =
auditable, itself an FP/FN defence):
1. **Effective independent origins `r`, never the article count `n`** (the maths
   heart of the anti-false-triangulation ruling). Over a cluster's duplication +
   citation graph, `r` = articles NOT reducible to the dominant origin (graph roots
   with in-cluster in-degree 0, counted by distinct source). Corroboration strength =
   `r`; the honest headline is "n=15 reports, r=1 origin". Cheap approximation
   `r ≈ s·(1−ρ)` (s distinct sources, ρ single-origin share); exact from `lineage.py`.
2. **Benjamini–Hochberg FDR control across the daily scan** (the load-bearing FP
   defence at scale). Thousands of clusters/terms/phrases per day ⇒ the look-elsewhere
   effect fires spurious hits at any fixed threshold; rank the day's candidate
   p-values, apply BH at a stated q, surface only survivors, print "1 of N candidates
   scanned".
3. **Surprise vs the CORPUS'S OWN baseline — a tail probability or z-score, never an
   absolute threshold** (the only honest baseline a local-first app has). Poisson
   upper tail `P(X≥k | μ=λw)` for bursts; z for shares/sentiment; surprisal bits for
   phrase rarity; wrap proportions in `proportion_ci_wilson` so small-n degrades
   loudly.
4. **Convergence is a logical GATE (AND of independent tests), not a multiplied
   probability** (the signals correlate; multiplying p-values fabricates precision).
   Require each independent test to clear its threshold; report the COMPONENTS, never
   a joint "probability of manipulation" — the no-score rule enforced by maths.

**THE NINE CARDS** (each: statistic → fires-when gate → `signal` components (no blend
→ passes `assert_no_score_fields`) → bucket → caveat naming the innocent twin). New
PRODUCERS feeding EXISTING buckets, not a new subsystem.
1. **Manufactured consensus / astroturf** → `overtold`. MinHash/Jaccard cluster
   (θ≥0.8) + Poisson burst surprise of k near-identical pieces in window w vs topic
   rate λ + single-origin share ρ→r. Fires: k≥k_min ∧ w≤w_max ∧ r≤r_max ∧
   origin ∉ disclosed-wire whitelist (BH-survived). signal{sources s, window_min w,
   independent_origins r, jaccard θ}. Caveat: undeclared wire / shared press release.
2. **Talking-point distribution (copypasta)** → `overtold`. Phrase surprisal
   I(g)=−log₂P(g) from corpus k-gram freq (k=6–10), m distinct non-syndicated
   sources, EXCLUDING quoted-attributed spans. Fires: I(g)≥τ ∧ m≥m_min.
   signal{phrase_len k, sources m, surprisal_bits I}. Caveat: shared unquoted
   statement / stock phrase; rarity from your corpus only.
3. **Manufactured emergence (zero-to-everywhere)** → `rising` (recipe →
   `investigate`). Born-wide ratio β=day1_sources/peak_sources, pre-onset 30-day
   baseline≈0, anchoring-event check vs the WWW substrate. Fires: prior_30d≈0 ∧
   β≥β_min ∧ no datable primary anchor. signal{first_day_sources a, peak_sources b,
   breadth_ratio β, prior_30d 0}. Caveat: viral events also spike; a missing anchor
   may = we didn't ingest it (FN honesty).
4. **Flood / bury** → `overtold` / `undertold`. Flood: topic-share
   z=(p_now−μ_p)/σ_p vs the source's OWN history (`concentration.py`). Bury: coverage
   breadth = covering/active sources alongside a real external trigger. Fires: flood
   z≥z_min; bury breadth≤b_min ∧ trigger. signal{share_zscore z, share_now p,
   baseline μ}. Caveat: volume ≠ importance; big stories legitimately dominate.
5. **Recycled / zombie claim** → `watch`. Temporal displacement
   Δ=D_pub−median(mentioned_dates) (`dateextract.py`), tightness via IQR, optional
   near-dup match >Δ months old. Fires: Δ≥T_months ∧ tight cluster.
   signal{displacement_months Δ, mentioned_median d, published_at D_pub}. Caveat:
   normal for retrospectives/anniversaries; flags age, not intent.
6. **Source laundering / citogenesis** → `investigate` (FLAGSHIP — purest structure,
   zero language dependence). Directed citation graph; independent origins r =
   distinct-source roots; cycle detection (DFS) for news↔wiki loops. Fires: r=1
   (single root) ∨ cycle present, n≥n_min. signal{articles n, independent_origins r,
   cycle_present bool}. Caveat: single-origin is common for genuine scoops; it means
   corroboration is weaker than the count, not that the claim is false.
7. **Headline–body mismatch (clickbait)** → `debunk`. Lexical divergence
   d_lex=1−|H∩B_top|/|H|; sentiment gap Δs=|sent(H)−sent(B)| (English only). Fires:
   d_lex≥d_min ∨ Δs≥g. signal{lexical_div d_lex, sentiment_gap Δs, lang}. Caveat:
   summarising/metaphorical headlines do this innocently; sentiment English-only.
8. **Outrage intensity (sentiment anomaly)** → `investigate` (SECONDARY — annotates,
   never fires alone). Baseline-relative z=(|sent|−μ_{|sent|,T})/σ_{|sent|,T} vs the
   corpus's absolute-valence distribution for topic T; per-source volatility. Fires:
   z≥z_min, English only, AND only attached to another card. signal{sentiment_zscore
   z, lang en}. Caveat: atrocity reporting is also charged; emotion ≠ manipulation;
   meaningless outside English.
9. **Event-timed operation (October surprise)** → `watch` (COMPOSITION of #3+#6+the
   agenda). Proximity E−O days (election date E, term onset O) gated by emergence
   (#3) ∧ single-origin (#6) ∧ entity ∈ the agenda candidate roster. Fires:
   O∈[E−d,E] ∧ #3 ∧ #6 ∧ agenda actor. signal{days_before_event E−O, breadth_ratio β,
   independent_origins r}. Caveat: real late news exists; timing alone means nothing.

**FALSE-POSITIVE / FALSE-NEGATIVE DISCIPLINE (what "ethically impeccable" means as a
spec):**
- ASYMMETRIC by design + STATED: a false positive here is a defamation that detonates
  neutrality; a false negative leaves the user where they started ⇒ the SURFACING is
  precision-biased (when in doubt, stay silent).
- Recall is not sacrificed, it is RELOCATED: separate what the app PROACTIVELY
  surfaces (high bar — the convergence gate) from what it lets you EXPLORE (full
  recall — every similarity score, timestamp, graph drillable). High bar to push at
  you; zero bar to go look.
- No single-signal cards (the gate). Always show the base rate / denominator. Show
  the INNOCENT EXPLANATION next to the pattern (state the null hypothesis; never
  collapse to one reading). Reproducible-or-it-doesn't-ship (exact
  articles/phrases/timestamps/edges shown). Target-blind + self-audited flag
  distribution. n + caveats, never a probability (no "87% fake").

**THE HONEST CEILING (state it as loudly as any flag):** a single well-written lie is
invisible (no structural anomaly); the detectors are EVADABLE and the adversary
adapts (vary phrasing beats near-dup, stagger timing beats bursts, fake origins beat
single-origin) ⇒ print "the absence of a flag is not the absence of manipulation" on
every producer; the language gap concentrates misses exactly where the app claims
most coverage (sentiment English-only; CJK keyword extraction nonfunctional) ⇒
disclose detector capability PER LANGUAGE (the audit §5/§6 honesty matrix). This is a
manipulation-pattern MICROSCOPE (makes structure visible/explorable), never a
DETECTOR (never certifies is/isn't manipulation).

**BUILD ORDER:** card #6 (citation graph) + #1 (near-dup cluster) FIRST — purest,
most language-agnostic, highest-signal, primitives already in `src/signals/`
(`lineage.py`, `near_dup.py`, `concentration.py`); the rest are increments on the same
four statistics.

**OPEN QUESTIONS (parked, maintainer "not sure" 2026-06-15):** (a) how hard to lean
on Tier 4 / the journalist-facing lens; (b) whether to ever use the words "push poll"
or only describe the mechanic ("this item embeds a negative claim inside the
question"); (c) whether the everyday-person promise should answer "who's winning"
more directly than the evidence-trail-only stance.
