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

### De-duplication across calendars — events as "event families"

Subscribe to several calendars/feeds and the *same* real-world event arrives more than
once (World Press Freedom Day is in both our `civic` and `un_days` calendars; an election
appears in a national feed *and* an aggregator; two iCal sources carry the same summit).
The elegant fix is **not a new mechanism — it's the one we already have for keywords**:
treat duplicate events as an **event family** (auto-group, list members, user disposes).

- **Fingerprint.** A stable key per event: `normalize(title) + when + country` (for movable
  events, `normalize(title) + month + country`). `normalize` lowercases, strips
  punctuation and parenthetical source-suffixes ("(UN)"). Within an iCal feed the UID is
  authoritative; the fingerprint catches *cross-feed* duplicates the UID can't.
- **Collapse to one, keep provenance.** Matching events merge into a single display row
  that lists every calendar/feed it came from — *"World Press Freedom Day · also in: UN
  Days, civic."* One entry, all sources preserved (and all official links).
- **Disagreements are a signal, not noise.** If two sources give *different* dates for the
  "same" event, we do **not** silently pick one — we surface the discrepancy
  (*"date varies: 14 Jul (UN) / 15 Jul (gov)"*), exactly as the law tracker treats a moved
  date as information. Honesty over tidiness.
- **The user disposes** (mirrors keyword merge/split, so the mental model is identical): a
  wrongly-merged pair can be **split** ("these are different"), a missed pair **merged**;
  a "show duplicates" toggle expands the collapsed set. Auto-merge by fingerprint is the
  default; overrides are stored and reversible.
- **Source precedence** for the merged row's canonical fields: prefer the most authoritative
  subscribed source (a confirmed official feed over an aggregator), but never drop the
  others' links.

This keeps the agenda readable as subscriptions multiply, reuses a proven pattern, and
holds the line: we **surface and group, never fabricate or silently discard**.

### Tagging every event — the faceting backbone (how a vast catalog stays digestible)

Once the catalog scales (every country's national day, every UN "world day", elections,
cultural/religious/scientific/tech events worldwide), a single `category` collapses. The
answer is to give **every event a multi-dimensional tag set** — tags are simultaneously
the **filter/group axis** and the **cross-link to the corpus**. Two kinds:

**Structural facets — a controlled vocabulary (reliable filtering & grouping):**
- **Type** — election · referendum · summit · observance ("world day") · national-day ·
  independence · commemoration/anniversary · religious · cultural · scientific ·
  tech-launch · conference · economic (central-bank · IPO · earnings) · sporting · legal
  (ruling · regulation-effective-date).
- **Geography** — `country` (ISO-3166) · region/continent · `global`.
- **Scope & significance** — global · regional · national · local, plus a **tier**
  (major/minor) so minor events collapse by default (density control).
- **Recurrence** — one-off · annual-fixed · annual-movable · periodic.
- **Confidence** — confirmed vs. expected (already modelled).
- **Calendar/source** — which bundled or subscribed iCal calendar it came from.

**Topical & entity tags — the cross-link layer:**
- **Topics** (controlled-ish vocab) — press-freedom · human-rights · climate · security ·
  finance · AI/tech · health · religion · space · sport …
- **Linked entities** — countries, orgs, people → connect an event to Insights
  entities/keywords, market tickers, tracked laws. This is what powers the correlation
  ("did coverage / a price / a law change cluster around this event").

**How tags deliver "selectable · groupable · filterable":**
- **Filter** by any facet (multi-select); **group** by any dimension (month · country ·
  type · topic · calendar).
- **Saved filters = "smart calendars"** — subscribing to a *tag query* ("all elections in
  Africa", "all press-freedom days worldwide", "central-bank decisions") is far more
  powerful than per-calendar on/off toggles, and is the natural unit of subscription.
- **Density** — collapse by tag/tier; **personal tags** let a user organise their own way.

**Honesty for tags (same bar as everywhere).** Curated/bundled tags are authored;
auto-derived tags (from the source calendar, the title, or article date-extraction) are
**candidates carrying provenance + confidence**, human-confirmable — never silently
asserted. The structural facets use a **controlled vocabulary** (prevents tag sprawl and
keeps filtering reliable); free-form user tags stay in a separate, personal namespace.

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

## Training & onboarding — two tracks

Even an intuitive tool benefits from deliberate teaching: training is **another channel
for communicating what the app is for and how to use it well** — and for at-risk users it
is itself a **safety control** (the most dangerous mistakes are operational, not UI). We
keep two clearly-distinct tracks, because they answer different needs.

### 1. Notice / guidance — for *autonomous* learning (in-app, self-service)
The learner is alone, possibly offline, possibly under pressure. Goals: get value in
minutes, and absorb the *why* (and the limits) along the way.
- **First-run guided tour** — a short, skippable, dismissible walkthrough of the core
  loop (collect → search → read → insights), resumable from Help, **off by default after
  first run** and never blocking a task.
- **Contextual "why" notes** — the honest one-liners already next to risky/ambiguous
  actions (confirm-before-external, "not legal advice", "association ≠ causation",
  EOD-not-real-time) are *teaching surface*: keep them consistent and discoverable.
- **Task recipes** — short, goal-oriented how-tos ("track a law for changes", "find every
  article citing the same source", "build a keyword super-group"), searchable in the
  in-app docs reader. Fully **offline**.
- **Progressive disclosure** — advanced surfaces stay behind drawers (as today) so a
  newcomer isn't overwhelmed; tooltips/`aria-label`s do double duty as micro-lessons.
- **Self-check** — an optional "are you set up safely?" checklist (fetch mode, backup,
  panic understood) that *informs*, never nags or gates.
- Honesty bar: guidance must teach the tool's **limits**, not just its features — what it
  cannot verify, where a number is a real aggregate vs. a heuristic, why it never decides.

### 2. Supervised training — for *facilitated* learning (workshops, train-the-trainer)
A human teacher with a group (newsroom, NGO, at-risk community). Goals: build correct
mental models, operational-security habits, and **norms of responsible/ethical use** that
no UI can enforce.
- **Curriculum + facilitator guide** — modular sessions (foundations → investigations →
  safety/opsec → ethics & dual-use red lines), with timings, exercises and discussion
  prompts. The **safety/opsec and ethics modules are mandatory**, not optional.
- **Train-the-trainer** material so trusted partners can run it locally, in their own
  language and threat context (ties into i18n).
- **Hands-on exercise corpus** — a small, shareable, *synthetic/public-domain* dataset so
  trainees practise without touching real sensitive material.
- **Threat-model-first framing** — teach when *not* to use a networked feature, how
  protected-fetch/proxy actually works (and its limits), backup/passphrase discipline,
  and the panic-wipe caveats — because for these users a training gap is a security risk.
- Delivered as docs/materials in-repo (and printable), **never** as a hosted service or
  anything that phones home (keeps the GOVERNANCE red lines intact).

**Why the split matters.** Autonomous guidance scales and meets people where they are;
supervised training builds the judgement and safe-use habits that protect sources and
users. The app should make the first effortless and give partners everything they need for
the second — and both are, above all, a way of communicating the project's ethic of
*surfacing structure for a human to judge, never deciding for them.*

---

## Space–time: the agenda as the anchoring layer for *all* information

> **STATUS (maintainer-ruled 2026-06-10):** layers 1–2 of this design shipped
> in 0.07 (the Temporal map tab + the Agenda tab, `src/timemap/` +
> `src/events/`). Layers 3–4 — **convergence detection** (space-time
> co-occurrence, never causation) and the **user-defined "if-this-then-WATCH"
> attention engine** (explainable, off by default, local-only alerts) — are
> **parked for the 0.0.9 cycle**, alongside the other designed-only pieces:
> event-family merge/split UI, saved-filter "smart calendars", offline vector
> map, Wikipedia-as-a-source, two-hop keyword graphs, and the autonomous
> onboarding track.

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


## Automated background source identification & aggregation

**Idea.** The app should shoulder the work of *finding and maintaining sources* so the
operator can focus on **content**, not plumbing. Today, growing the source list is manual
(add a domain, discover its feed, tune it). The proposal: a **background source-discovery
agent** that continuously identifies candidate outlets — expanding coverage toward "as many
sources as manageable" — and aggregates them into the one UI, so multi-source breadth stops
costing operator effort.

**Discovery channels** (all building on machinery that already exists):
- **DuckDuckGo search** for topic/region queries — the natural engine for "find outlets
  covering X". This *is* an external call, so it sits strictly behind the off-by-default
  external-lookup gate (roadmap RM-03 / audit finding ETH-02) and is clearly labelled
  "this query leaves your machine".
- **The corpus itself** (no network): promote frequently-cited external domains
  (`article_links` / `external_sources` already track them) to source candidates.
- **The Wikidata world-catalog generator** (`scripts/build_world_news_catalog.py`) run as a
  scheduled refresh instead of a manual script.
- **Feed discovery** on candidates via the existing ethical-fetcher-routed RSS discovery.

**Full transparency is non-negotiable.** Background must never mean hidden:
- a visible **Discovery activity panel** (what was queried, when, via which channel, what
  was found — same spirit as the live scraping readout), persisted as an auditable log;
- discovered sources land in a **"candidates" staging state** — visibly machine-suggested
  with their evidence (query, citation counts, feed check result) — and are clearly
  distinguished from operator-curated sources. Auto-enable is a setting the operator turns
  on knowingly, never the silent default. (Lesson learned the hard way: see
  `quarantine/fabricated_sources.md` — every entry must be a real, verifiable outlet, so
  candidates get the same liveness/feed checks before they can be promoted.)
- every external query type is individually toggleable; the offline channels work with
  external lookups fully disabled.

**Resource budget — user-controlled (Settings).** A *discovery budget* alongside the
scheduler settings: max queries/fetches per day, time window ("only while idle"), CPU/IO
politeness, and a hard kill switch. Defaults conservative; the activity panel shows budget
consumption so the control is honest, not decorative.

**Why it fits.** It turns the existing pieces (scheduler, discovery service, catalogs,
link-graph) into a coverage engine while keeping the §0.5 invariants intact: ethical
fetching for every probe, provenance on every candidate, locality except the explicitly
gated search channel, and the operator always disposes.

**Build sequence.** (1) candidate staging state + evidence fields on sources, with the
activity log; (2) offline channels (citation-promotion + catalog refresh) in the scheduler;
(3) the gated DuckDuckGo channel with per-query logging; (4) the budget controls in
Settings; (5) optional auto-enable for high-confidence candidates (explicit opt-in).
*(Roadmap slot: RM-19 in `docs/product/ROADMAP.md`; depends on RM-03.)*

## Session handoff — notes from the v0.0.7 audit session (for the next session)

**State at handoff.** The six-phase audit (PR #56) is merged into `0.07`: 24/29 findings
fixed, suite green on both install profiles, CI hardened (core-only job + blocking
bandit/pip-audit), benchmarks recorded as gates (`scripts/benchmark_audit.py`).

**Where to pick up:**
- **`docs/product/RELEASE_0.0.8_PLAN.md`** is the executable next step — WP1–WP6 on a fresh
  branch; WP7 (`Mapped[]` ORM migration) as its own PR. Start with WP2/WP3 (zero-risk).
- **Existing databases need `make migrate` once** (drops the 224 MB redundant index).
- **Pending verification:** the Ollama model-catalog tags were not live-checked (registry
  returned 403 from the audit environment) — verify `llama3.2:3b` / `gemma2:2b` /
  `qwen2.5:3b` / `phi3:mini` from a normal network.
- **Watch for:** the new weekly-CVE posture means pip-audit can legitimately fail CI on a
  fresh advisory — that's the design, triage rather than mute. The deferred findings live in
  `docs/audit/findings.csv` (5 DEFERRED) and `PARKED.md`.
- **RM-19** (automated background source discovery, above) depends on RM-03 (the external-
  lookup gate, WP1 of the 0.0.8 plan) — build the gate first.

## Ten space-time scenario cards — leveraging the map + timeline for honest journalism

The temporal map, mentioned-date tags, geocoded corpus, hazards relay, events agenda, law
tracker and wiki tracker together form a **space-time substrate**. These cards sketch
user-driven scenarios that substrate makes possible — candidates for future USE_CASES
entries and UI "investigation recipes". Each keeps the house bar: surface signals with
provenance, never verdicts; coverage-of-reports, never surveillance of people.

**Card 1 — "The warnings existed" (disaster accountability).** After a flood appears on the
hazards layer, rewind the timeline *at that location*: every stored article geocoded there
from prior years mentioning dams, inspections, budget cuts, zoning. Output: a dated,
sourced "what was known and when" dossier. Honesty: absence of coverage ≠ absence of
warnings — the card says so.

**Card 2 — Promises-due review (anniversary accountability).** Mentioned-date tags include
*future* dates ("the bridge will reopen in March 2027"). When a promised date arrives, the
card resurfaces the original story + location and asks: did follow-up coverage materialize?
Output: a "promises due this month" desk list. Turns slow-news days into accountability.

**Card 3 — Disputed chronology detector (conflict reporting).** For one event, different
outlets often assert different dates/places. Cluster near-duplicate coverage, then surface
where confirmed date-tags or geocodes *disagree* across sources. Output: a chronology with
disputed points explicitly marked (claim A: outlet+date vs claim B). The disagreement is the
journalism.

**Card 4 — News-desert atlas.** Invert the World-coverage view over time: regions where the
corpus consistently has zero or near-zero sources/coverage. Output: a desert map + trend
("this province lost its last covered outlet in 2025"). Doubles as the targeting input for
automated source discovery (RM-19). Honesty: it maps *this corpus's* blind spots, not the
world's press.

**Card 5 — Silent disasters.** Join the hazards feed (GDACS/USGS severity) against local
coverage in the same space-time cell: significant events with *no* corpus coverage within
N days. Output: an under-reported-events queue — assignments, not analytics. Honesty note
built in: "a source we watch didn't report it" ≠ "nobody reported it".

**Card 6 — Law-takes-effect watch.** The law tracker knows effective-dates; the map knows
jurisdictions. When a tracked regulation enters into force, watch coverage in that
jurisdiction for its subject keywords over the following window. Output: "the eviction law
took effect on the 1st — here is reported reality since." Pairs legal text with ground
coverage, honestly time-anchored.

**Card 7 — Story-propagation tracer (press-freedom lens).** For one story cluster, plot
*where* each subsequent report was published over time: local outbreak → national pickup →
border-death. Output: a propagation timeline/map showing where stories stall. A
press-freedom signal when local stories systematically fail to cross a border. Counts and
timestamps only — no inferred intent.

**Card 8 — Edit-war seismograph.** When a geolocated event spikes in the corpus, the wiki
tracker watches the related Wikipedia pages in the same window: revision bursts, reverts,
ORES-flagged edits. Output: a side-by-side "what happened vs how its public record was
fought over" timeline. Documents narrative contestation with diffs as evidence.

**Card 9 — Supply-chain ripple view.** A commodity price move (official CSV series) +
geocoded coverage of the chain's known places (mines, ports, smelters) in the preceding
window. Output: price chart over a strip-map of chain-located coverage, with the standing
correlation caveat (coefficient + p-value + n, never causation).

**Card 10 — Election-window integrity desk.** During an election period, a dedicated
space-time lens: polling-place coverage by region over the voting timeline, official-results
dates from the events agenda, and per-region report density before/after. Output: a
region-hour record of *reported* irregularities with sources, exportable for observers.
Honesty: a density map of reporting, explicitly not a fraud meter.

**Common requirements these cards surface** (feed into roadmap scoring): saved
"investigation recipes" (parameterised queries over space-time), per-card export with the
evidence bundle, and a way to pin a *region + window* the way articles pin to a briefing.

## LLM model catalog & Ollama delivery — open design discussion (maintainer-raised)

**Problems observed (2026-06):** (1) the installer's suggested model list goes stale fast —
operators were prompted to pull models that had long been superseded; (2) the Ollama
*download* path does not work over Tor, so protected-mode operators cannot fetch models the
recommended way; (3) should the repo bundle Ollama and/or a minimal first-run model so the
app needs no model download at all?

**Options on the table (no decision yet — pros/cons honestly):**

1. **Live catalog from the local Ollama** (`/api/tags` lists what is already installed;
   Ollama also exposes search on its registry). In-app model picker: show *installed*
   models always (purely local), and offer a "browse registry" step that is an explicit
   external call (same gating pattern as topic discovery). Pair with a **hardware probe**
   (RAM/VRAM via psutil — already a dependency) that annotates each model with "fits /
   tight / won't fit" rather than choosing for the user. *Pro:* never stale, honest about
   hardware. *Con:* the registry browse is an external call (must be opt-in + labelled).
2. **Curated-but-dated fallback list**: keep a small static list *with its as-of date
   printed* ("suggested as of 2026-06; check ollama.com for newer") so offline installs
   still get a sane default without pretending freshness. Cheap, honest, complements (1).
3. **Bundling Ollama in the repo:** *against* — it is a fast-moving native binary per
   OS/arch (hundreds of MB), bundling makes us its de-facto security maintainer, and a
   stale bundled server is worse than none. Better: the installer keeps offering the
   official install with consent, and documents the offline path (download the binary +
   model on a connected machine, transfer by USB — Ollama models are plain files in
   `~/.ollama/models`, so this works today and suits air-gapped/Qubes use).
4. **Bundling a minimal model:** *against* in-repo (even small models are 100s of MB and
   licence terms vary), but a **wheelhouse-style "offline LLM kit"** — a documented,
   checksummed download bundle (Ollama binary + one small model) produced per release as a
   GitHub release artifact — could serve Tor/air-gapped operators without bloating the
   repo. Fits RM-08 (offline packaging).
5. **Tor note:** model *downloads* failing over Tor is an Ollama-registry limitation;
   inference itself is loopback HTTP and unaffected. The offline kit (4) is the honest
   answer for protected-mode operators.

**Suggested sequence if adopted:** (2) date-stamp the static list now (one line, kills the
"obsolete and doesn't say so" problem) → (1) installed-models picker + hardware annotation
(local-only, no gate needed) → registry browse behind the external-lookup gate → (4) the
offline kit as part of RM-08.

### Decisions taken (0.0.8 maintainer discussion)

1. **No bundling of Ollama/models in the repo** — GitHub rejects >100 MB files and git
   history keeps them forever; a ~1 GB native binary per OS/arch would bloat every clone
   permanently and make us its security maintainer. Settled: never.
2. **Curated list, date-stamped + freshness-test-enforced** — `CATALOG_AS_OF` is shown
   wherever the catalog appears; `test_llm_catalog_freshness` fails once it is >9 months
   old, forcing each cycle to re-verify against ollama.com/library. **DONE.**
3. **Live local picker** — `/api/llm/models` leads with the operator's *installed* models
   (live from Ollama) and annotates the suggested list by hardware fit (RAM via psutil);
   surfaced in Settings → Local models. Informs the choice, never makes it. **DONE.**
4. **Ollama version: attest, don't chase** — `OLLAMA_TESTED_VERSION` + `doctor` shows
   installed-vs-tested, an honest compatibility statement that never goes silently stale.
   **DONE.**
5. **Clearnet a stated prerequisite for model provisioning; Tor unsupported for that
   step** — install.sh alerts up front, and notes the app runs fully offline afterwards
   (sources via Protected-mode proxy; the LLM never networks again). Installing already
   reveals the machine to PyPI/GitHub/Ollama regardless, so this concedes nothing new.
   **DONE.**
6. **Offline LLM kit (RM-08 sub-item, planned)** — a checksummed GitHub *release artifact*
   (NOT repo content): Ollama binary + one small model, provisioned on a connected machine
   and carried by USB to `~/.ollama/models`. The principled fallback for operators who can
   never use clearnet on the work machine. Build with RM-08 packaging.


## Settings → Diagnostics log: a shareable back-end synthesis (maintainer idea, 2026-06-10)

**The problem.** Keyword grouping "is still a bit messy", and improving it requires
seeing the operator's real data — but the corpus is private and local by design.
The maintainer cannot paste their whole database into a debugging session.

**The idea.** A new Settings section that builds **shareable, human-readable
exports of back-end state**, starting with keywords:

- **Keyword log**: the full list of gathered keywords + their families and
  supergroups (with counts and merge/split provenance), exported as a single
  reviewable file. The maintainer hands this to the development assistant, who can
  then propose grouping fixes adjusted to the *actual* vocabulary of the corpus —
  instead of guessing from synthetic examples.
- **Extending further (maintainer-stated):** the same log should grow into an
  agreed set of synthesized snapshots of other important back-end aspects — the
  maintainer↔assistant diagnostics channel. Precedent: `data/source_preflight.jsonl`
  already plays this role for sources, and proved its worth in the first live test.

**Honesty constraints**: exports contain only what the operator chooses to share,
generated on demand (never automatic), clearly labelled with date + corpus size,
and they synthesize — they never editorialise (counts and structures, not scores).

## Hosting & mobile — the stance (maintainer-ruled 2026-06-10)

The PR #37 memo ("hosting & mobile strategy", closed as a deliberation doc)
analyzed five architectures and recommended the hard, aligned path. The
maintainer has now **adopted that recommendation as the official stance**:

> **Give away the software for free; never host the users' data.** No SaaS,
> no central server, no accounts, no telemetry. The forward path for reach is
> a PWA + one-click self-host (BYO-home tunnel as an option) — centralized
> hosting would delete the governance red line and is rejected.

Any future mobile/remote-access work must start from this ruling.

## KEY POINT for 0.0.9 — de-US-centre the default source catalog (maintainer-flagged)

The live test exposed it plainly: the packaged catalog is heavily US-centric (World
coverage showed ~1,553 "US" sources vs hundreds elsewhere — partly inflated by a mixed
country-encoding bug: rows stored as both "US" and "United States" must be normalised to
ISO-2 storage with full-name display). For a *global* intelligence platform this is a
credibility problem, not a cosmetic one. 0.0.9 must treat catalog balance as a first-class
deliverable: per-region source targets, the Wikidata world-catalog generator run for
under-covered countries, the coverage report as the acceptance metric, and the ISO-2
normalisation migration. (Maintainer: "address that specifically with all our attention.")
