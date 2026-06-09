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
