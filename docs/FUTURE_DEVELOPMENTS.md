# Future developments

> Forward-looking ideas that are **not** committed work yet — a place to elaborate a
> direction before it earns a `ROADMAP.md` slot. Nothing here is promised. Each idea is
> held to the same bar as shipped work: **honest by construction** (real, provenanced
> data with as-of dates; predictions clearly labelled as such), **local-first / offline**,
> and **the user disposes** (we surface, never fabricate or decide).
>
> Some source comments reference numbered sections of this document (e.g. the world-law
> vertical as "§5", which has since shipped). Those numbers are historical; new ideas are
> added by title below.

---

## Events agenda / world calendar

**Idea.** A curated, searchable **agenda of major scheduled world events** — the
forward-looking complement to the corpus's record of what already happened. Examples:

- **Political** — elections & referendums, summits (Davos/WEF, G7/G20, COP, UN GA),
  legislative sessions, treaty signing/ratification deadlines.
- **Economic / markets** — central-bank rate decisions (Fed/ECB/BoE), **IPOs** and
  listings, major earnings, OPEC+ meetings, index rebalancings, options expiries.
- **Technology** — flagship product launches and developer conferences, standards
  deadlines, large infrastructure/launch windows.
- **Legal / institutional** — scheduled court hearings & rulings, regulatory
  effective-dates (e.g. an EU regulation's date of application), sanctions reviews.

**Why it fits.** Open Omniscience's macro layer today answers *"what is happening"*
(keyword trends, market series, law diffs, citations). A calendar adds the **time axis
forward**: *"what is coming, and what should I prepare for."* It lets a journalist
anticipate coverage, pre-stage sources, and — most valuably — **correlate the corpus
with the calendar**: did a keyword spike, a market move, or a law change cluster around
a scheduled event? That's a real sense-making capability, not a planner gimmick.

**Honesty constraints (non-negotiable).**
- Every event comes from an **official / verifiable source** with `official_url`,
  `source`, and an **as-of date** — exactly like the commodity, index, and legal
  catalogs. Nothing is scraped-and-guessed.
- **Confirmed vs. expected** dates are distinct and labelled. A "likely Q4 2026 IPO" is
  never rendered as a hard date; an electoral-commission-published date is.
- **Offline-first**: a curated catalog ships (a `configs/world_events.yml`, mirroring
  `commodity_feeds.yml` / `legal_sources.yml`), plus optional **import of official
  iCal/CSV feeds** (electoral commissions, central banks, exchanges, WEF) through the
  same ethical fetch path. No third-party calendar SaaS, no tracker beacons.

**Sketch — data model.** An `Event(title, category, start_at, end_at, confirmed: bool,
region/jurisdiction, official_url, source, captured_at, related_keywords[],
related_entities[], related_symbols[])`. Reuses the existing provenance discipline; the
related-* links are what make it *cross-cutting* rather than a standalone planner.

**Sketch — integration.**
- A **Calendar / Agenda** view (list + month/timeline), filterable by category, region,
  and confirmed-only.
- **Cross-links** into the rest of the app: an election → its country + candidate
  entities (Insights); an IPO → its ticker (Indices/Commodities); a regulation's
  effective-date → its tracked law (World Law).
- **Correlation**: overlay scheduled events on Insights trend charts and market
  sparklines; surface "events near this keyword's spike." This is the payoff.

**Phasing (when/if it graduates to the roadmap).**
- **P0** — curated `world_events.yml` catalog + a read-only agenda view (honest as-of /
  confirmed labels). No network needed.
- **P1** — import official **iCal/CSV** feeds (per-source, ethical fetch, idempotent),
  the way market/law feeds already import.
- **P2** — cross-linking to keywords/entities/symbols/laws + event↔signal correlation.
- **P3** — opt-in local reminders/alerts for watched events (no external push; loopback
  only, in keeping with the threat model).

**Open questions.** Curation scale (which events clear the "major" bar, and who decides);
de-duplication and date-change tracking (treat like the law tracker — an event whose date
moves is itself a signal); time-zone honesty; and avoiding a US/EU bias in the starter
catalog.

### How the calendar gets populated — two complementary feeds

Both are feasible, and they reinforce each other: aggregated official calendars are the
**trustworthy backbone**; corpus-extracted dates are a **soft signal layer** that suggests
events and powers comparative-over-time analysis. They reconcile — a date a reporter
mentions that lands on a confirmed calendar event corroborates coverage.

**A. Aggregate openly-accessible calendars → a new source *type*.** Most authorities
already publish machine-readable calendars: **iCal (`.ics`)** and CSV/JSON feeds from
electoral commissions, parliaments, central banks (Fed/ECB meeting calendars), exchanges
(IPO/earnings/expiry calendars), the UN, standards/sports bodies, conference organisers.
The right shape is a **new source type** — `events`/`calendar` — handled with its own
peculiarities, exactly the way financial data (FRED/Stooq CSV) and legal catalogs are
their own kinds of source. Concretely: an `EventSource` (curated `configs/world_events.yml`
+ user-added feeds) and an **iCal/CSV importer** through the same ethical, robots-respecting
fetch path, idempotent per `(source, uid)`, every event provenanced with `official_url` +
`captured_at`. High trust, low risk — this is the **P1** backbone.

**B. Extrapolate dates *from* articles → comparative-over-time analysis.** Run temporal
expression extraction on article text: absolute dates, and **relative expressions**
("next Tuesday", "last week", "by year-end") resolved against the article's *publication
date* as the anchor (baseline: a `dateparser`/regex pass; richer: a HeidelTime/SUTime-style
normaliser if a dependency is ever warranted). This yields, per article, the **event
date(s) it references** — distinct from when it was published. The payoff is exactly the
comparative analysis asked for: bucket and **align the corpus on the event-time axis** so
you can compare *how different outlets covered the same moment/event*, and correlate that
with the existing Insights trends / market / law signals.
- **Honesty (critical here).** An extracted date is *an assertion in the text, attributed
  to that article* — never ground truth. Confidence is graded (explicit ISO date ≫ resolved
  relative expression ≫ vague), stored alongside provenance. Unresolvable/ambiguous → left
  out, never guessed.
- **Feeds the calendar semi-automatically, not silently.** Article-extracted event-dates
  become **candidate** calendar entries (clustered across corroborating articles, linked to
  their sources) that the user confirms or dismisses. We never auto-publish a corpus-derived
  date as a confirmed fact — that would betray the verification mission. Full automation is
  acceptable only for *suggestion/ranking*, with a human (or a confirmed official-feed
  match) closing the loop. This is the **P2** enrichment.

**Verdict.** Ship **A** first (official iCal/CSV aggregation as a new source type — clean,
high-trust, mirrors the markets/law catalog pattern); add **B** as a corpus-derived signal
layer that suggests events and unlocks the comparative-over-time view, kept honest with
provenance + confidence + human-in-the-loop confirmation.

---

## Other ideas captured this cycle (stubs)

Brief placeholders so they aren't lost; each deserves its own elaboration before any
commitment.

- **Keyword super-groups** — a user-curatable hierarchy above keyword *families*
  (groups-of-groups) for sorting/discovery; doubles as the cluster layer the mind-map
  zooms in and out of, and as a home for cross-kind groupings (e.g. `russia` + `russian`).
- **Offline vector world map** — bundled simplified country outlines (Natural Earth,
  public domain) rendered as SVG with city labels at high zoom; **no tile-server calls**
  (privacy + offline), unlike Leaflet/OSM raster tiles.
- **Non-destructive backup merge** — import-only-what's-new (dedup by article content
  hash + source domain) with FK remapping, a preview before commit, and **provenance
  safeguards**: merged rows keep their origin and are never laundered into
  authenticated first-party evidence; incoming custody signatures are *verified*, not
  trusted.
- **Wikipedia as a first-class source** — make the offline Wikipedia corpus searchable
  and indexed like articles (keyword associations, LLM summarise, read, explore its own
  links), while keeping its special-case handling for scale.
- **Two-hop / within-article keyword graphs** — neighbours sprout their own associations
  (real clusters), plus an intra-article co-occurrence lens to compare against the
  corpus-wide PMI.
- **i18n completeness** — route the remaining hard-coded UI strings (Settings/Safety,
  backup, network-mode, etc.) through the translation layer so a non-English locale is
  fully translated.

---

## Personality: easter eggs + a journalism quotes/fun-facts library

**Idea.** Give the UI a little soul: a small, tasteful set of **easter eggs** plus a
curated library of **famous journalistic quotes and verifiable fun facts** that surface
in quiet corners of the interface (empty states, the loading/onboarding screens, an
"about" flourish, the occasional console banner). The point is warmth and craft-pride —
this is a tool made *by and for* people who believe in the work — without ever
undermining the seriousness of what at-risk users are doing.

**Why it fits.** Personality builds affinity and signals care. A well-placed line from
a great reporter ("Comfort the afflicted and afflict the comfortable"; the
[reporting credo of getting it *right*, not just first]) reinforces the mission every
time the app is opened, and makes empty/loading states feel intentional rather than
dead.

**Same ethical bar (non-negotiable).**
- **Quotes are sourced and attributed.** Each entry carries author + (where known)
  publication/year; misattributed-but-famous lines are either omitted or flagged as
  *attribution disputed* — we do not launder folklore as fact (that would be hypocritical
  for a verification tool). Public-domain or clearly fair-use snippets only.
- **Fun facts are *facts*** — verifiable, with a source — not "did you know" filler. If
  we can't cite it, it doesn't ship. Same provenance discipline as everything else.
- **Dismissible, off-switch, never intrusive.** A single setting disables all flourishes;
  easter eggs never interrupt a task, fire during sensitive actions (panic, encrypted
  backup, protected-mode fetch), or appear in evidence/export artifacts. Respect
  reduced-motion. Nothing phones home — purely local, bundled content.
- **No dark patterns.** Personality, not gamification: no streaks, badges, or nudges that
  manipulate. Tasteful and rare beats cute and constant.

**Sketch.** A bundled, inspectable `configs/quotes.yml` (and `fun_facts.yml`) — `{text,
author, source, year, public_domain|fair_use, attribution: confirmed|disputed}` — read
the same way as the other curated catalogs; the UI picks one at random for an empty/idle
slot. Easter eggs live behind harmless triggers (a Konami-style key sequence, a long-press
on the logo, a date like Press Freedom Day) and are documented in the code so they're
reviewable, never hidden surprises in a security tool.

---

## Space–time: the agenda as the anchoring layer for *all* information

**The reframe.** The agenda is not "a list of upcoming events." It is the **time spine**
of a deeper idea: *every signal the app holds is anchored in **time** (when) and **space**
(where), and the meaning often lives in their **synchronicity**.* Tensions over oil →
a war (a place, a timeline of escalation). Tensions over chips → Taiwan between China and
the US (a strait, a sequence of moves). Climate → Arctic ice melt → new passages → a
"useless" place becomes a pivotal chokepoint and a rare-earth frontier. These are not
separate stories; they are **the same story read along time and across space**. An
election is a *place* (a polity) + a *time* (the vote, the mandate). A war is a *geography*
(borders, terrain, routes) + a *time* (emergence → casualties → tech adoption → settlement).
The tool should let a journalist **anchor everything in space and time, then see what
converges.**

**The data is already space-time-stamped.** Keyword mentions carry `observed_on` +
`country` + `city`; articles carry dates + source geography + extracted places; market
series are dated; law changes carry `observed_at` + `jurisdiction`; events carry
date/window + country/region + tags. What's missing is a **unifying read model** and the
**views + detectors** that treat them as one fabric.

### Layer 1 — a unifying "signal" model (when × where × what)
A thin, read-only projection: every domain exposes a common shape —
`Signal(domain, title, when[date|window], where[country/region/(lat,lon)], entities[],
tags[], magnitude?, link)`. Articles, keyword spikes, market moves, law diffs, events all
become Signals. No new storage of substance — just a uniform lens over what exists.

### Layer 2 — the two spines made navigable
- **Timeline (the agenda, generalised):** overlay events **+** keyword-trend spikes **+**
  market moves **+** law changes on one time axis. The agenda becomes the backbone other
  domains plot onto — "what is converging this quarter."
- **Map + time slider:** the existing map gains a temporal control, so you scrub space
  *through* time (the Arctic-route scenario is literally a map cell changing meaning over
  years).
- **A space-time cell** = (region × window). It is the unit of convergence.

### Layer 3 — synchronicity / convergence detection (honest, not oracular)
Scan for **space-time cells where several *independent* domains light up at once** — e.g.
an upcoming OPEC date **+** a spike in "sanctions/oil" keywords **+** a crude-price move
**+** a sanctions-law change, all in one region/window. That convergence is itself worth a
human's eye. **It is reported as real co-occurrence (counts, dates, the actual signals) —
never as causation or prediction.** Correlation ≠ causation is stated; sample sizes shown.

### Layer 4 — "if-this-then-watch" early-signal rules (the forecasting ask, done honestly)
A **user-defined, fully transparent rule engine** — an *attention director*, **not an
oracle**. A rule is a conjunction of conditions over **real stored signals**:
> *IF* `keyword "rare earth" rising in region X` *AND* `an upcoming "shipping/Arctic" event`
> *AND* `a related law/market move` → **flag for attention** (the user's hypothesis "a new
> route may be opening") — **never** an assertion that it will happen.

Guardrails (this is forecasting-adjacent, so they are non-negotiable):
- It surfaces **conditions that currently hold**, computed from real signals, and shows
  **exactly which matched** (explainable, auditable) — it never states a future fact. The
  "then" is *the user's labelled hypothesis*, presented as a prompt to investigate.
- Rules are **user-owned, editable, reversible**; ship a few **example** rules, **off by
  default**. No black-box scoring (the quarantined credibility/relationship analyzer in
  `docs/HISTORY.md` is the cautionary tale: we surface structure, the human decides).

### New Home scenarios (briefing producers) to automate the approach
The Home "cards" engine is the natural home for this. New producers:
- **"Converging now"** — space-time cells where ≥N independent domains are active, with the
  contributing signals listed and linked.
- **"On the horizon"** — an agenda event intersects your *tracked* keywords/region
  ("COP in 12 days; your ‘climate’ coverage is rising 40% vs prior month — prepare").
- **"Through time / anniversary lens"** — a past event recurs (an election cycle, a war's
  onset) and may resurface; bridges the corpus's past to the agenda's forward view.
- **"Your watch-rules fired"** — if-then matches, each showing the real matched conditions.

### Build sequence (each honest and incremental)
1. The **Signal** read-model + put events + keyword spikes + law changes + market moves on
   one timeline (read-only).
2. **Map + time slider.**
3. **"Converging now" + "On the horizon"** Home producers (pure co-occurrence; explainable).
4. The **watch-rule engine** (user-defined, transparent, off by default) + "rules fired".

Depends on the events agenda (P0.5 ✓) and on the event↔keyword/region/market/law
cross-links (events P2). This is the through-line that turns the separate verticals into
one space-time instrument.

---

## Climate & weather events — a live geo-temporal data channel (+ an alert system)

**The idea.** Surface **present-tense weather and natural-hazard events** — heatwaves,
floods, cyclones, earthquakes, droughts, food-security/famine crises — *not* the
climate-change debate. A super-heat-and-humidity wave hitting millions in India is a
**fact at a place and time** that should sit right next to the coverage of it. This is the
purest space-time channel of all (every datum is lat/lon + time), so it plugs straight into
the substrate above — and there is **excellent open data**.

**Why it fits.** Famines and crises are often driven by physical events; putting the
**event** beside the **reporting** is real sense-making, and it makes the convergence view
concrete: a hazard cell lights up *and* article volume rises there in the same window.

**Open, space-time-stamped channels (a new `hazard`/`weather` source *type*, peculiar in
its own way like financial/legal/events data):**
- **Disasters & alerts** — **GDACS** (UN/EC global disaster alerts, severity-scored:
  cyclones, floods, quakes, volcanoes), **USGS** earthquakes (GeoJSON, real-time),
  **NASA EONET** (natural events).
- **Weather & forecast** — **Open-Meteo** (free, no key: forecast + historical),
  NOAA/NWS alerts (US), Copernicus/ECMWF (EU).
- **Humanitarian / food security** — **ReliefWeb** (UN OCHA), **FEWS NET** (famine early
  warning), WHO outbreak news.
All fetched through the ethical path, provenanced (`source`, `official_url`, `as-of`), and
imported idempotently — same discipline as the market/law/events catalogs.

**Honest forecasting — and why it's allowed here.** We refuse to *predict geopolitics*;
but **meteorology is genuinely skillful at 24–48 h**, so a short-horizon forecast is real
information. The line we hold: the app **relays an *official* forecast with its issuer,
issue-time and the provider's own horizon/uncertainty** ("NWS extreme-heat warning for
region X, issued <ts>, valid through <ts>") — it **never generates its own meteorology**.
Relaying a sourced forecast is honest; inventing one is not.

**Correlate to the corpus.** A hazard/weather event becomes a `Signal` (when × where) → the
timeline overlay, the map, the **"Converging now"** card, and a direct *"articles in this
region around this event window"* link. Physical event and its coverage, side by side.

### The alert system (the broader ask: "if there's a nuclear event we should know fast")
A **local, severity-tiered alerting layer** that fires on **any** real trigger:
- a **high-severity hazard-feed entry** (GDACS red, M≥7 quake, severe-weather warning);
- a **tag-family** firing in the news/events (e.g. a `nuclear`/`radiological` family, or
  `outbreak`, `coup`, `mass-casualty`) — exactly the "know quickly" case;
- a **space-time convergence** or a **watch-rule** match (from the section above);
- a **news-classification** hit (certain event types in freshly-ingested articles).

Tiers: **info · watch · urgent**. Urgent surfaces prominently (Home banner + the activity
area), watch collects quietly, info is logged.

**Guardrails (non-negotiable, and especially here):**
- **Local only — no external push service, ever.** Alerts render in-app (loopback), never
  via a third-party notifier; pushing to an external service would leak the user's
  interests and break the threat model.
- **Explainable** — every alert cites the **real triggering signal(s)** (the feed entry,
  the matched tag/keyword, the converging cells) with timestamps and links.
- **User-owned** — which feeds, which tag-families, and the thresholds are all configurable
  and dismissible; severity comes from the **source's** scoring (GDACS/USGS), not invented.
  The `nuclear`/`radiological` family ships as a built-in **urgent** rule, on by default
  but fully editable.
- Honest about coverage: an alert means *"a source we watch reported this,"* never *"this
  is everything happening"* — silence is not safety.

**Build sequence.** (1) `hazard`/`weather` source type + GDACS + USGS importers → space-time
`Signal`s on the map/timeline; (2) corpus correlation (event ↔ articles by region/window);
(3) the **alert layer** (hazard-feed + tag-family + watch-rule + convergence triggers,
local, tiered, explainable); (4) relay **official short-horizon forecasts** (Open-Meteo /
NWS) with full provenance. Builds directly on the space-time substrate above.

