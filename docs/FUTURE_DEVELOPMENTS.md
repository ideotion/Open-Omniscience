# Future developments — persistent design memory

> A durable record of *intended directions* so they survive across sessions and
> contributors. This is a north star, **not** committed work. Each item states the
> intent, why it matters, the hooks that already exist in the code, the hard
> problems, and the honesty constraints that must hold. Nothing here is implemented
> yet.

> **This is the guiding document for the `0.06` cycle ("the intelligence layer").**
> It holds the *what & why*; the phased *how* lives in
> [`ACTION_PLAN.md` → "0.06 — The Intelligence Layer"](ACTION_PLAN.md). Read both
> together. The unifying idea: **one measurement engine, many domains.** Every
> section below is a *family axis* or a *vertical* pointed at the same shared
> internals (entity analytics, change-tracking, signal primitives, the card
> framework) — so favour **mutualisation** over per-feature code.

**Map of this document**
- **Guiding principle** — user-driven selection, no capping.
- **§1–3** — uniformity/concentration · trace-to-primal-source · guided selection.
- **§4** — the Home **briefing** and the **card** catalog (editorial, keyword
  dynamics, people, tone, belief axis, markets, IP/legal) → newsletter draft.
- **§5** — world-law corpus & change-tracking vertical.
- **§6** — **source integrity & anti-amplification** (the garbage-in problem; C+D;
  crowdsourced annotations) — *the keystone that arranges all the rest.*
- **Common substrate · Hooks · Hard problems · Status.**

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

### Domains covered (one engine, many family axes)

Every "war"/domain raised is addressed by the **same** measurement engine pointed at a
different *family axis* — not a separate detector each. Nothing was dropped:

| Domain | Where it is addressed |
|---|---|
| Political | spectrum `lean-*` tags · framing · synchrony/echo (§1, §4 tone) |
| Information / disinfo | §6 source integrity & anti-amplification · echo/synchrony cards |
| Technological / AI-trust | §6 (capacity-implausible, synthetic-volume) · markets (tech) |
| Industrial / economic | §4 markets/commodity/rare-earth cards |
| IP / legal | §4 IP/legal & corporate-control cards + primary-source vertical |
| Religious / belief | §4 belief/ideology family axis |
| (people, law) | §4 people-prominence · §5 world-law vertical |

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

### People / prominence dynamics cards

"People" are just entities of `kind=person` (the NER already tags `PERSON→person`),
so most of this is the keyword-dynamics cards above **pointed at persons** — nearly
free. It adds **one** genuinely new metric: *prominence concentration over time*
(Gini / top-N share over person-mention volume) — the measurable form of "the list
of prominent people keeps concentrating," and the **same concentration math as the
§1 media-ownership analysis**, applied to people.

| Card | Surfaces | Bucket | Powered by | Status |
|---|---|---|---|---|
| Rising star | a person with the steepest mention growth | rising | Spike/Acceleration, `kind=person` | now/thin |
| Fading / forgotten | a person decaying toward zero mentions | undertold | Went-quiet/Half-life, `kind=person` | thin |
| First sighting (person) | a name appearing for the first time | rising | earliest `KeywordMention`, `kind=person` | thin |
| Staying power | a person's mention half-life (flash vs durable figure) | context | `trend` decay, `kind=person` | thin/new |
| Prominence concentration | Gini / top-N share of person-mentions, tracked over time | context | new inequality metric (reuses §1 concentration) | new |
| Co-prominence | who rises *alongside* whom (proximity to power) | investigate | person co-occurrence / association-shift | new |
| Prominence by family/geography | who's prominent in state-media vs independent, or one bloc vs another | debunk | `kind=person` × family tags / `map_data` | thin |

> **Bright line (sharpest here).** This measures **coverage prominence of public
> figures already written about** — *attention, not importance or merit* (scandal
> inflates mentions). It is **never** a "most important person", a "power score", or
> a profiling/watchlist tool on private individuals (`src/compliance/gdpr.py` is the
> guardrail). Prominence reflects *your* source set — a skewed corpus skews who
> looks important (the diet-self-audit caveat). Namesakes/variants are the hard part
> (see Variant convergence).

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

### IP / legal & corporate-control cards

The pattern "a firm is acquired by a foreign player, then divested — stripped of its
IP" is, measurably, a **sequence of reported corporate events over time**. The
entity store + deal-verb keywords + the new country provenance already make most of
this reachable; it reuses the **New pairing**, **Association shift** and **Variant
convergence** cards (entity resolution across name variants/subsidiaries is the hard
part those name).

| Card | Surfaces | Bucket | Powered by | Status |
|---|---|---|---|---|
| Ownership-change event | a company reported acquired/divested/sold (parties + countries) | context | entity mentions + deal-verb keywords + provenance country | thin |
| Cross-border control shift | acquirer and target in different countries | investigate | entity co-occurrence + `ccTLD`/country | thin/new |
| Deal lineage | one firm's timeline: acquisition → restructuring → divestiture | investigate | §2 story-lineage applied to corporate events | new |
| IP-litigation pulse | patent/injunction/licensing/lawsuit volume around an entity or sector | context | `trend` over IP/legal terms + entity | thin |
| IP ↔ deal co-timing | IP-transfer/litigation mentions clustering around an ownership change | investigate | event co-timing (reported events, not a verdict) | new |

> **Bright line.** The tool sees *reporting about* deals — it does **not** read
> filings, so it never asserts "the IP was stripped." It shows the **sequence +
> links** and foregrounds the primary document; the human confirms.
>
> **The high-value extension (→ §2).** The sources that *would* confirm it —
> patent grants (USPTO/EPO/WIPO), court dockets, SEC/EDGAR filings, merger
> notifications — are **structured, official, ingestible** primary sources. An
> **IP/legal primary-source vertical** would ingest them as first-class,
> provenance-tagged records (structurally identical to the markets CSV-feed
> vertical: a record stored only from a real source, never guessed), then correlate
> the *primary record* against the *news narrative* — the honest realisation of §2's
> "trace to the primal source" for corporate-control stories.

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

## 5. World-law corpus & change-tracking (a "Wikipedia for the law")

**Intent.** Aggregate the **law** — statutes/legislation/official gazettes — from
every jurisdiction that publishes it, and **track its changes over time** for
offline analysis. Law is public in many countries and changes by amendment, so the
data *is the diff*: what changed, when, via which instrument.

**This reuses the Wikipedia vertical almost wholesale.** `src/wiki/track.py` +
`dumps.py` + `flagging.py` already do baseline-snapshot → diffs/deltas →
large/burst-change flagging → offline resumable downloader, all provenance-tagged.
A legal source is just another tracked source whose *edits are the data*. Also
reused unchanged: the ethical fetcher (robots fail-closed, rate-limited), FTS5
Boolean search, the offline baseline downloader, and — valuably — **chain of
custody**: signed, timestamped legal snapshots ("the law as it stood on date X,
cryptographically attestable").

**Feeds the §4 cards.** Cross-jurisdiction **near-duplicate** detection (the §1/§2
MinHash machinery) surfaces **model legislation** — near-identical bills copy-pasted
across countries/states (measurable lobbying/diffusion); plus **law ↔ news
correlation** (a statute changes as coverage spikes) and **quiet amendment**
(changed with little coverage = undertold).

**Where the data genuinely is (pilot jurisdictions first):** UK
`legislation.gov.uk` (API, Open Government Licence, *native point-in-time
amendments* — the ideal pilot); EU **EUR-Lex** with **ELI** + **Akoma Ntoso** XML
(the international legal-document standard); France **Légifrance** / LEGI open data
(DILA); US **govinfo**. **WIPO Lex** (IP laws of ~200 countries) ties this directly
to §4's IP/legal vertical — the law corpus is the *statutory* half of that
primary-source layer, with patents/dockets/filings as the case half.

**Honesty constraints (law is high-stakes):**
- **Not legal advice, not the authoritative source.** The aggregated copy is a
  *research mirror*; every record links back to the official gazette, and the UI
  says so. Track and surface; never interpret legality or judge a law.
- **"Public" ≠ "freely redistributable."** Licenses vary even where text is public
  — respect each, attribute, store provenance, robots fail-closed (as for news).
- **Translation is a separate, clearly-labelled layer** (local LLM as an aid) —
  never presented as an authoritative legal translation.
- **Scope honestly.** "Every country" is the north star, not v1: start with the few
  open, structured jurisdictions above. Akoma Ntoso/ELI give structure where
  adopted; crude text-diff elsewhere — and say which you have. Distinguish
  *consolidated* vs *point-in-time* text explicitly.

**Status:** vision. New vertical parallel to Wikipedia/Markets; pilot = UK +
EUR-Lex. The genuine work is heterogeneous formats, licensing, and the
not-legal-advice discipline — not the tracking machinery, which already exists.

---

## 6. Source integrity & anti-amplification — the "garbage in" problem

**The keystone.** The other sections surface signals; this one decides *whose
signal counts*, and it does so without becoming an arbiter of truth. It is the
principle that arranges all the rest.

**The surprise (why "treat every source equally" is not neutral).** Trending,
prominence, synchrony and "what's covered" all **count outlets and volume**. So
equal-treatment-of-outlets, applied to a volume metric, has a built-in bias: *whoever
produces the most wins.* A well-resourced actor who spins up 40 agencies (or troll
farms, or LLM content mills) converts capital directly into apparent consensus, and
**dilutes** honest single-source stories into nothing — ghosting the public. Doing
nothing is therefore *not* neutral; it subsidises the flooder. The resolution is not
"score sources" — it is to define neutrality over the right **unit**: equal treatment
of *independent actors weighted by the new information they contribute*, not of
*outlets*. **Counting sock-puppets as voices is a measurement error, not neutrality.**

**The distinction the whole design pivots on.**
- **(A) Veracity/quality scoring** — "is this source truthful / good?" Subjective,
  the arbiter-of-truth move; bakes the scorer's worldview into a false-objective
  number. **Forbidden to automate.** (This is what the owner's caveat rightly fears:
  scoring "garbage" down will eventually score a good-but-unusual source down too.)
- **(B) Authenticity / structure signals** — "is this source what it claims to be?
  one node of a coordinated network? does it *originate* or only *echo*? is its
  output within human capacity? is it transparent about who runs it?" These are, to
  a real degree, **measurable structural facts**, not value judgments. *All viable
  design lives in (B).*

**Decided direction: C + D, and B is forbidden.** (Scenario labels from the session
brainstorm; A=do-nothing, B=single trust score, E=external refs, F=disconfirmation
workflow.)
- **D — actor-collapse + anti-amplification (the structural backbone).** Don't score
  sources; change the *unit of influence*. (1) Collapse coordinated / near-duplicate
  networks into single **actors** (40 puppets = 1 voice in every trend/prominence/
  synchrony computation); (2) weight influence by **independent information
  contributed** (novelty / surprisal vs what the corpus already holds), not raw
  volume. This attacks the *exploit* (volume + coordination), never the content, and
  is information-theoretically clean: the 1000th repost isn't called *false*, it is
  *not new* — which is simply true. **It inverts the feared failure mode:** under
  novelty-weighting the small, original, independent source *rises* relative to the
  manufactured flood — the lonely-signal/undertold source is the winner, not the
  casualty. **The app only ever *proposes* a collapse (with its evidence); the user
  disposes** — see the user-guided principle below.
- **C — multi-dimensional transparent profile (the interface).** Per source, a panel
  of measured signals (coordination/actor membership, novelty ratio, output-capacity
  plausibility, transparency facts, plural external refs §E, corpus track-record) —
  **no single composite score.** The user weights *which dimensions matter into their
  own view* — off by default, theirs not ours, reversible, with the raw
  equal-treatment view always one click away.
- **Forbidden: B (a single automated 0–100 trust score).** False precision over
  incommensurable dimensions; bakes in bias as objectivity; Goodhart-gameable; a
  single point of capture/censorship; *will* misclassify small/foreign/new/dissident
  sources. Written down here so no future contributor builds it by reflex.

**Anti-amplification is user-guided, user-aware, and GUI-mediated (non-negotiable).**
D must never be a silent transform the app performs and the user merely *undoes* —
that would make the app the arbiter §6 forbids. The model is **propose → the user
disposes**, expressed *through the interface*:
- **Default = "equal but aware", not silent collapse and not naive equality.** The
  raw equal-treatment view is the baseline, but manipulation structure is **always
  annotated on it** ("this trend is carried by a 40-source coordinated cluster —
  why?"). Awareness is the default; de-amplification is an *action the user takes*.
- **The app proposes with evidence; the user disposes.** A suggested collapse shows
  *why* (shared infrastructure, lockstep timing, near-dup text) and is applied only
  by the user's choice — globally *or per-cluster* — never auto-applied behind their
  back. Every applied collapse stays visibly flagged and one click to expand/override.
- **The GUI is a *necessary* interface, by design.** Because the human judgment *is*
  the mechanism, there is no headless "auto-clean" path: anti-amplification exists as
  interactive briefing affordances (expand actor · treat as separate · why? · weight),
  and a user's tuning persists as *their* editorial choice, always re-inspectable and
  reversible. This is §3 ("guided, user-driven selection") applied to amplification:
  suggestive, explained, overridable — surface, never enforce.

**Crowdsourcing is required (the owner's key correction).** C's "user weighting" is
impossible for one person — nobody can neutrally assess thousands of sources alone.
So the weighting must be **collective**, and the honest, local-first, non-centralised
way to do that is **signed, shareable annotation bundles**: a user publishes their
source annotations (coordination tags, transparency facts, corrections) as a
**custody-signed, verifiable, portable bundle** (reusing the evidence-bundle
machinery — *mutualisation*); other users **import** the bundles they choose to
trust (opt-in **web-of-trust**, never a central authority), aggregated **transparently**
(you can always see *who asserted what*, and dissent is shown, not averaged away).
No server, no accounts, no global score — federation by signed exchange.

**The honest, realistic goal.** Not "detect all garbage" (impossible; it is an
adversarial arms race and *claiming* detection would be the dishonest move) but
**strip garbage of its mechanical advantages so it cannot automatically dominate,
and raise the cost of manipulation.** Success = the 40-agency play *stops paying
off*, not a verdict on its content.

**Hard problems & residual risks (named).**
- **Arms race / Goodhart** — every published signal becomes an optimisation target;
  rely on defence-in-depth, never claim completeness.
- **False merges hurt the innocent** — collapsing "coordination" could wrongly fuse
  independent allies that share a stance or a CMS; must be high-precision,
  evidence-shown, **reversible**, biased toward *under*-merging.
- **Capture** — any shipped mechanism could itself be biased/captured; mitigate by
  shipping **mechanisms not verdicts**, defaulting to the transparent equal view, and
  letting the user override everything.
- **Asymmetry cuts both ways** — there is more garbage than signal, so filtering is
  *usually* right, but the cost of the rare false-negative (silencing a real
  whistleblower outlet) is severe: **annotate and de-amplify, never suppress.**
- **Targeted-disinfo blind spot** — individualised micro-targeted disinformation
  lives in private feeds/DMs/ads; a *public-corpus* tool cannot see it. Map the
  public manipulation infrastructure; do not overpromise the private.
- **Offline / single machine** — favours hashing, graphs and counting over heavy ML
  (which is *also* why we lean on structural/behavioural signals rather than
  unreliable "AI-text detectors").

---

## Common substrate — mutualise these internals

Almost everything above composes from a *small* set of shared engines. Build these
once, well, and point them at each domain; do **not** re-implement per feature.

| Shared engine | Status | Powers |
|---|---|---|
| Entity/keyword analytics (`src/analytics`) | exists | §4 keyword/people/tone cards, IP entities, §6 novelty |
| Change-tracking (baseline→diff→flag, `src/wiki`) | exists | Wikipedia, §5 law, stealth-correction card |
| Correlation (Pearson/Spearman + p + n, `commodity/correlation`) | exists | price↔news, law↔news, IP↔deal co-timing |
| Anomaly (z-score, `monitoring/anomaly`) | exists | volume spikes, price/term spikes |
| Tone (VADER + `context` window) | exists | tone/framing cards, §6 not used for stance |
| Provenance + custody (signed, timestamped) | exists | every record; **§6 crowdsourced annotation bundles** |
| **Concentration metric** (Gini / top-share) | **built** (`src/signals/concentration.py`) | §1 ownership, people-prominence, §6 actor share |
| **Near-dup / coordination** (MinHash + LSH → actor graph) | **built** (`src/signals/near_dup.py`, `coordination.py`) | echo cards, model-legislation, syndication, **§6 actor-collapse** |
| **Novelty / surprisal** (info contributed vs corpus) | **built** (`src/signals/novelty.py`) | §6 anti-amplification weighting |
| **Card + briefing framework** (signal+evidence+method+caveat → feed → draft) | **built** (`src/briefing/`, Phase A) | the entire §4 surface, the GUI spine |

The four primitives (concentration, near-dup/coordination, novelty, the card
framework) are the whole of `0.06`'s genuinely new code; everything else is
composition. **All four are now shipped and tested.** On top of them: the
source-integrity layer (`src/integrity/`, §6 C+D — profile + user-guided actor-collapse)
and crowdsourced **signed annotation bundles** (`src/annotations/`, §6 D). See
[`BRIEFING.md`](BRIEFING.md), [`INTEGRITY.md`](INTEGRITY.md), [`ANNOTATIONS.md`](ANNOTATIONS.md).

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

Vision / persistent memory — the **guiding document for `0.06`**; the phased build
is in [`ACTION_PLAN.md` → "0.06 — The Intelligence Layer"](ACTION_PLAN.md).

> **Implementation progress.** **Phases A–D are shipped and tested.** Home is a triage
> feed of honest cards (A) with a card→draft→Markdown loop; the full `src/signals/`
> substrate — concentration, near-dup/coordination, novelty (B) — is built and pure;
> the source-integrity layer (C) gives every source a **no-composite profile** and
> **user-guided actor-collapse** (propose → you dispose; the 40-puppet acceptance is a
> passing test); and **signed annotation bundles** with a web of trust (D) let the
> weighting be collective. Phase E ships the composable news-corpus cards (emotion,
> IP/legal). The §6 *no-composite-score* ban is enforced **in code**. Remaining: the
> **law / IP primary-source change-tracking verticals** (§5, §4) — they reuse the
> existing engines but need live external ingestion, so they are not faked.

Decided principles on this page: **user-driven selection, no capping** (guiding
principle); **C + D, B forbidden** for source integrity (§6); **mutualise the shared
substrate** (one engine, many domains). The lowest-risk first slice is the **card +
briefing framework** (the GUI spine) rendering §4's **now**-status cards; the four
new primitives (concentration, near-dup/coordination, novelty, card framework) are
the only genuinely new code the rest composes from.
