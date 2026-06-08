# Future developments — persistent design memory

> A durable record of *intended directions* so they survive across sessions and
> contributors. This is a north star, **not** committed work. Each item states the
> intent, why it matters, the hooks that already exist in the code, the hard
> problems, and the honesty constraints that must hold. Nothing here is implemented
> yet.

---

## Guiding principle (decided) — selection is **user-driven**

**The tool informs and guides; the user decides.** We do **not** algorithmically
cap, auto-balance, or silently filter which sources are included. Coverage facts
(gaps, geographic/linguistic skew, ownership concentration, echo/synchrony) are
**surfaced** for the user to act on — never enforced.

This is itself a Munich-Charter safeguard: a tool that decides *for* the user which
sources count becomes an editorial gatekeeper — the very bias we exist to expose.
Any "balancing" is a **suggestion the user can ignore**.

> Note: the catalog generator's `limit:` is a *technical* per-query row bound (to
> avoid timeouts), not an editorial cap on how much any country/owner is
> represented. The two must never be conflated.

---

## 1. Source-uniformity & media-concentration analysis

**The problem.** Apparent diversity ≠ real diversity of viewpoint. Ownership is
concentrated: e.g. in **France, ~7 billionaires control ~90%** of the major news
outlets. Many nominally "independent" sources may carry the **same line at the same
time** — sometimes to amplify a political message. A reader counting outlets is
fooled; a reader who sees *who owns whom* and *who is echoing whom* is not.

**Goal.** Detect and **surface** uniformity: "these 12 sources share one owner,"
"this framing spiked across 40 outlets in 6 hours," "this cluster maps to one bloc."

**Approach (honest, measurable, cheap enough for one machine):**
- **Ownership graph** — map outlets → owners / parent groups. Data: Wikidata
  *owned by* (P127) / *parent organization* (P749) *(verify QIDs)*, public
  media-ownership-monitor datasets, and manual entries. Surfaces concentration.
- **Near-duplicate / co-publication detection** — the same story across outlets in a
  time window (cheap hashing: MinHash/SimHash, not heavy ML).
- **Synchrony / herding metric** — the same keywords/framing spiking across many
  outlets simultaneously, weighted by ownership concentration.

## 2. Trace to the **primal / original** source

**Goal.** For information echoed by N outlets, identify the **original report** (or
the wire / primary document) and **foreground original reporting**, while
**lowering the weight of derivative commentary** — which may be opinionated,
influenced, manipulated, or unintentionally biased.

**Approach.**
- **Provenance / lineage tracing** — earliest timestamp, explicit citations
  ("according to X"), wire attribution (AFP/Reuters/AP), and the underlying primary
  source (court filing, government release, dataset, preprint).
- **Classify the act**: *original reporting* vs *aggregation* vs *op-ed* vs
  *syndication* (syndication is detectable as near-identical wire text).
- **Present a "story lineage"** — primary document → first report → echoes, with
  timestamps — so the user sees the chain, not just the chorus.

**Honesty constraints.** "Earliest we saw" ≠ "the truth." The tool shows *lineage
and structure*; the human judges. It must **never** auto-label anything "true" or
"fake," and down-weighting derivative sources must be **transparent, tunable, off by
default, and reversible** — surface, don't suppress (suppression would itself be a
bias).

## 3. Guided, user-driven source selection

The app may **suggest, when pertinent**: e.g. "your results on topic X are 80% from
one owner / one country / one language — consider these under-represented sources,"
or "9 of these 10 articles trace to a single AFP wire." Always **suggestive,
explained, and overridable**; the user can dismiss it. No silent filtering, ever.

---

## 4. The Home briefing — surfaced intelligence as "cards"

**The reframe.** Today Home shows at-a-glance stats. The intended Home is a
**triage feed**: the app gathers and analyses in the background, then surfaces
*candidate stories* as **cards** — the most-used tab, where intelligence is
concentrated. The app does the gathering; **the human judges**. Each card is one
measurable signal + the evidence links + a caveat, pre-sorted into an editorial
bucket. A card **surfaces a signal; it never renders a verdict** (no "biased",
no "propaganda", no "true/fake").

**The three shapes.** Almost every card is one of: **convergence** (sources agree
too fast / too uniformly → *overtold*), **divergence** (sources or data disagree →
*investigate / debunk*), or **absence** (something moved but nobody covered it →
*undertold*). That triad is the editorial engine — and it maps directly to a
newsletter: debunk the overtold, surface the undertold, contextualise the rest.

### Card catalog

Status legend: **now** = composes endpoints that already return real numbers;
**thin** = a small generalisation of existing code; **new** = real new analysis
(do it properly or not at all — see §1–2).

| Card | Surfaces | Bucket | Powered by | Status |
|---|---|---|---|---|
| Rising now | trending keywords/entities | rising | `/api/insights/trending` | now |
| Echo chamber | one story across N outlets, weighted by owner concentration | overtold | dedup/canonical hash + `sources_spectrum.yml` owner tags | new |
| Lonely signal | single-source story that did *not* echo | undertold | inverse echo + `KNOWN_GAPS` coverage ledger | new |
| Framing split | same event, opposite tone/emphasis per source | debunk | `awareness/framing.py` (VADER + terms) | now |
| Record reshaped | large/burst/anon Wikipedia edits on a topic | watch | wiki flagging | now |
| Stealth correction | an outlet quietly rewrote a published piece | watch | content-hash change on re-fetch | new (hooks exist) |
| Cross-language divergence | domestic vs foreign framing of one event | debunk | i18n locales × framing | thin |
| Diet self-audit | "70% of your week traces to one wire / one owner" | context | corpus concentration over provenance tags | thin |

### Keyword & entity dynamics cards

Cards driven by the *behaviour of the keywords/entities themselves* — when a term
**appears**, how its **volume** moves, and how its relations shift. All ride the
Insights analytics substrate (`src/analytics/queries.py`: `trend`, `trending`,
`associations`, `top_terms`, `map_data`) plus the z-score `volume_anomalies`
(`monitoring/anomaly.py`). Each `KeywordMention` records a first-occurrence offset
and its article (with `published_at`), so *appearance* and *volume-over-time* are
real aggregates, never invented. The three shapes still apply: spike/echo →
overtold, association-shift/framing-split → investigate, went-quiet/hum → undertold.

| Card | Surfaces | Bucket | Powered by | Status |
|---|---|---|---|---|
| First sighting | an entity/term seen for the first time ("first in *your corpus*", not the world) | rising | earliest `KeywordMention` per keyword | thin |
| New pairing | two entities co-occurring for the first time | investigate | `associations` + first-co-occurrence date | new |
| Geographic debut | a term appearing only from one country/language | undertold | `map_data` + provenance country | now/thin |
| Spike | a term's daily mentions ≥ Nσ of *its own* history (vs the trending ratio) | rising | `trend` + `volume_anomalies` | thin |
| Acceleration | volume's 2nd derivative — "going parabolic", not just up | rising | `trend` series | thin |
| Went quiet | a steady term drops to ~zero (dropped story at term level — a *question*) | undertold | `trend` | thin |
| Persistent hum | low but steady over a long window — the quiet ongoing story | undertold | `trend` mean/variance | thin |
| Half-life | how fast a term decays after a spike (flash vs enduring) | context | `trend` decay | thin/new |
| Association shift | an entity whose co-occurring set changed between windows | investigate | windowed `associations` diff | new |
| Entity-mix imbalance | a topic dominated by orgs vs named people (who it's *about*) | context | `top_terms` by kind | thin |
| Variant convergence | one entity under several surface forms spiking together (user merges) | trust | mention store + string similarity | new |
| Framing-word tracker | volume of chosen loaded/neutral pairs by source/time (counts, never a verdict) | debunk | `trend` per-source + curated term list | thin |
| Echoed keyword | a term spiking where most articles cite the *same* source | overtold | `trend` × `/api/links` co-citation | new |

### Keyword-conditioned tone & emotion cards

Tone/emotion measured on the words *surrounding* a keyword (its `context()`
window), not the whole article — then grouped **by source and by source-family**.
The substrate exists: VADER tone (`awareness/framing.py`), the keyword context
slicer (`analytics/queries.py:context`), and rich family tags already in
`configs/sources_spectrum.yml` (`lean-left…lean-right`, `state-media`,
`public-broadcaster`, `wire-agency`, plus `country`/`region`/`reliability_score`).

> **Bright line — sentiment ≠ stance.** Negative tone around "climate" may be
> alarm, grief, *or* skepticism: opposite stances, identical valence. So these
> cards map **how charged** a family's coverage of a topic is and **which words it
> co-occurs with** — they **never** auto-label a source "climate-skeptic" or
> "war-optimist." Surface the measured pattern + snippets; the human attributes
> (per `framing.py`: never a bias score, never "biased"; per the spectrum file:
> leaning tags are reputational and contestable). Stance is read from *vocabulary*
> (`associations`) more honestly than from valence.
>
> **Limits:** VADER is **English-only** (cross-language tone needs per-language
> analyzers — locales exist, analyzers don't yet); richer **emotions**
> (anger/fear/joy/trust) need an emotion lexicon we don't ship — those cards are
> **new**, not thin. Every cell carries its `n` and the context-window size used.

| Card | Surfaces | Bucket | Powered by | Status |
|---|---|---|---|---|
| Keyword tone | mean tone of the words *around* a keyword (not the whole piece) | context | `context` window + VADER | thin |
| Tone by source | the same, per outlet, with snippet links | debunk | per-source `context` + VADER | thin |
| Tone by source-family | grouped by spectrum/ownership/country tags ("state-media vs wire-agency on X") | debunk | family tags + tone | thin/new |
| Tone divergence | spread of tone across sources for a keyword = how *contested* it is | investigate | variance of per-source tone | thin |
| Tone drift | a keyword's tone trending over weeks | context | `trend` buckets + VADER | thin/new |
| Stance-vocabulary signal | charged co-occurring terms per source/family + tone (a signal to *read*, never a label) | debunk | `associations` per family + curated charged lexicon | new |
| Emotion profile | emotion categories (anger/fear/joy/…) around a keyword | context | emotion lexicon (degrades loudly if absent) | new |
| Family tone-map | keywords × source-families matrix, each cell = mean context tone (+ n, snippets) | overtold/undertold | composition of the above | new |

### Belief / ideology as one more source-family axis

The coordination cards above are **domain-agnostic**: a message coordinated across
many outlets — in many languages, in a tight window — produces the *same*
measurable signature (echo, cross-language synchrony, co-citation, ownership/funding
concentration, tone-by-family) whether it is political, commercial, **or belief-
aligned**. So religious/ideological influence needs **no new card type** — only the
same treatment political leaning already gets: one more **family axis** to group by.

Today the spectrum file tags political leaning and ownership richly but belief
alignment barely at all, and the worldwide generator samples no faith-based
channels — so this dimension is *under-sampled*, not unsupported. The fix is data,
not new analysis: a neutral, contestable belief/ideology tag axis (like the existing
`lean-*` tags) + faith-based organisation types in the generator
(`configs/catalog_query.yml`).

> **Bright line (the whole point).** The tool surfaces **coordination** — synchrony,
> diffusion, concentration — and the **human** decides what it means. It must
> **never** label a faith (or any belief group) as malign, or emit a "stance score".
> "Religious war" is an *interpretation*, not a measurement; the tool stops at the
> measurable pattern. Tags are descriptive, contestable, editable — never a verdict.
>
> **Scope limits (honest):** the tool ingests **web text only** — it cannot see
> physical-world messaging (e.g. street posters/graffiti), only web/news sources
> *writing about* them. And it has **no funding-flows dataset** — it sees reporting
> *about* money, not financial records; "concentration" is only as good as the
> sourced reporting behind it.

### Markets / commodity / rare-earth cards

The commodity vertical already does **honest** stats (`commodity/correlation.py`:
scipy Pearson/Spearman with coefficient + real two-sided p-value + n + insufficient-
data handling), exact mass-unit conversion (`commodity/units.py`), z-score anomalies
(`monitoring/anomaly.py`), and rule outcomes that store a number **only** when a
selector lands on one (`markets/pipeline.py`). These cards reuse that machinery —
every figure sourced, with method + caveat, and **no invented FX** (cross-currency
stays explicitly un-converted until a dated rate exists).

| Card | Surfaces | Bucket | Powered by | Status |
|---|---|---|---|---|
| Price ↔ narrative | price move vs news volume on shared dates | context | `correlate_price_with_news` (coef + p + n) | now |
| Anomalous move | a daily move ≥ Nσ of its own volatility, with nearby articles | context | z-score anomaly, volume→price | thin |
| Silent move | a price anomaly with near-zero coverage | undertold | anomaly × low article volume | thin |
| Narrative-without-data | heavy "shortage" coverage while the series is flat | debunk | coverage volume vs measured series divergence | thin |
| Venue divergence | same instrument, two venues/publishers, different numbers | investigate | two extraction rules compared (discrepancy flagged, not adjudicated) | new |
| Cross-series co-movement | two related series moving together | context | same Pearson engine, price↔price | thin |
| Stale-data / integrity | "feed N days cold" / "rule selector stopped matching" | trust | `RuleOutcome.status` + `last_run_at` | now |
| Unit/currency hygiene | unit/currency mismatch when comparing prices | trust | `units.py` (within-currency only; FX is future work) | now |

### From card to draft (the newsletter workflow)

A card carries a **"→ Add to draft"** action into a simple accumulator (pinned
cards + the user's notes) that exports **Markdown** — each claim already carrying
its source links and, optionally, the signed/timestamped chain-of-custody receipts.
The differentiator is *reproducible* journalism: the receipts ship with the issue.

**Build order (de-risk first).** Ship a *Briefing v0* of only the **now** cards
(Rising, Framing split, Record reshaped, Price↔narrative, Stale-data) + the draft
accumulator + Markdown export — proving the idea→draft loop before investing in the
harder **new** analysis (echo/synchrony, lineage). A `/api/briefing` endpoint
assembles cards from the existing queries on the scheduler; the redesigned Home
renders them.

**Honesty constraints (same as §1–2, restated for cards):** surface, don't
suppress; every card links to its evidence and states its method + caveat; any
down-weighting (e.g. derivative-source de-emphasis) is transparent, tunable, **off
by default, and reversible**; the tool is never an arbiter of truth.

---

## Hooks already in the codebase (this is not from scratch)

- **Dedup / canonicalization:** `src/ingestor/duplicate_detector.py`,
  `deduplicator.py`, `url_utils.py` (content hashing, URL canonicalisation) — the
  seed of near-duplicate and syndication detection.
- **Analytics substrate:** keyword/entity mention store, PMI associations, trend
  time-series (`src/analytics/*`), and framing/tone (`src/awareness/framing.py`,
  `src/api/framing.py`) — the basis for synchrony/echo metrics.
- **Provenance tags:** ownership (`state-media` / `public-broadcaster` /
  `wire-agency`) and leaning tags in `configs/sources_spectrum.yml`;
  `reliability_score`. Wire-agency tags already help spot syndication.
- **Coverage ledger:** `docs/KNOWN_GAPS.md` — where "surface, don't enforce" lives.

## Hard problems & risks (named honestly)

- **"Same initial information"** is event-clustering + near-dup + citation tracing —
  non-trivial. Start simple (wire/syndication + exact/near-dup) before semantic
  clustering.
- **Ownership data is patchy and shifts** — it must be sourced and attributable, not
  guessed, and dated.
- **Down-weighting can backfire** — suppressing legitimate analysis is its own bias.
  Hence: transparent, tunable, off by default, reversible.
- **Never an arbiter of truth** (Munich Charter) — show *who said it first, who owns
  whom, who is echoing* — and stop there.
- **Offline / single machine** — favour hashing and counting over heavy models.

## Status

Vision / persistent memory only — not implemented. Decided principle on this page:
**user-driven selection, no capping.** §4 (Home briefing / cards) is the intended
surface for §1–3 plus the markets vertical; its **now**-status cards are the
lowest-risk first slice.
