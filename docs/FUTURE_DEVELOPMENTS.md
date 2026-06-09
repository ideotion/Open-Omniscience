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

