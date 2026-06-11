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

## When × Where × Who anchoring — persist the extractors at ingest (maintainer question 2026-06-11)

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
  switcher (the tab has only the list).
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

## Hosting & mobile — the standing stance (ruled 2026-06-10)

> **Give away the software for free; never host the users' data.** No SaaS, no
> central server, no accounts, no telemetry. The forward path for reach is a PWA
> + one-click self-host (BYO-home tunnel as an option); centralized hosting is
> rejected. Any future mobile/remote-access work starts from this ruling.
