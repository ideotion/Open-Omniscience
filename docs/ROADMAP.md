# Roadmap, plans & open questions

The forward-looking record: the persistent design memory (north star), the phased build plan + status, the per-vertical designs, the coverage ledger, and open questions.

## Contents
- [Future developments — persistent design memory](#future-developments-persistent-design-memory)
- [Open-Omniscience — Action Plan](#open-omniscience-action-plan)
- [Email & Newsletter Intelligence Implementation Plan](#email-newsletter-intelligence-implementation-plan)
- [Worldwide source catalog — strategy & runbook](#worldwide-source-catalog-strategy-runbook)
- [Known gaps — the coverage ledger](#known-gaps-the-coverage-ledger)
- [Open Questions & Design Notes (for the next work session)](#open-questions-design-notes-for-the-next-work-session)


---

## Future developments — persistent design memory

> A durable record of *intended directions* so they survive across sessions and
> contributors. This is a north star, **not** committed work. Each item states the
> intent, why it matters, the hooks that already exist in the code, the hard
> problems, and the honesty constraints that must hold. Nothing here is implemented
> yet.

> **This is the guiding document for the `0.06` cycle ("the intelligence layer").**
> It holds the *what & why*; the phased *how* lives in
> [`ROADMAP.md` → "0.06 — The Intelligence Layer"](ROADMAP.md). Read both
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

### Guiding principle (decided) — selection is **user-driven**

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

### 1. Source-uniformity & media-concentration analysis

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

### 2. Trace to the **primal / original** source

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

### 3. Guided, user-driven source selection

The app may **suggest, when pertinent**: e.g. "your results on topic X are 80% from
one owner / one country / one language — consider these under-represented sources,"
or "9 of these 10 articles trace to a single AFP wire." Always **suggestive,
explained, and overridable**; the user can dismiss it. No silent filtering, ever.

---

### 4. The Home briefing — surfaced intelligence as "cards"

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

#### Domains covered (one engine, many family axes)

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

#### Card catalog

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

#### Keyword & entity dynamics cards

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

#### People / prominence dynamics cards

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

#### Keyword-conditioned tone & emotion cards

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

#### Belief / ideology as one more source-family axis

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

#### Markets / commodity / rare-earth cards

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

#### IP / legal & corporate-control cards

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

#### From card to draft (the newsletter workflow)

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

### 5. World-law corpus & change-tracking (a "Wikipedia for the law")

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

**Status: shipped (`0.06`).** Implemented as `src/law/` + `/api/law/*` + the **World law**
GUI tab + a `law` scheduler mode, with a **worldwide catalog of real official sources**
(`configs/legal_sources.yml`) seeded **by default** and a curated set of trackable
consolidated-law documents (baseline → normalised-text diff → honest flag, reusing the
wiki engine). Cross-jurisdiction near-dup surfaces **model legislation**. See
[`USER_MANUAL.md`](USER_MANUAL.md). The remaining refinements are *structured* per-edit diffs
(Akoma Ntoso / ELI) and patent/docket parsing — not the tracking machinery, which now
exists; and the not-legal-advice / licence discipline, which is enforced and documented.

---

### 6. Source integrity & anti-amplification — the "garbage in" problem

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

### Common substrate — mutualise these internals

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
[`USER_MANUAL.md`](USER_MANUAL.md), [`USER_MANUAL.md`](USER_MANUAL.md), [`USER_MANUAL.md`](USER_MANUAL.md).

---

### Hooks already in the codebase (this is not from scratch)

- **Dedup / canonicalization:** `src/ingestor/duplicate_detector.py`,
  `deduplicator.py`, `url_utils.py` (content hashing, URL canonicalisation) — the
  seed of near-duplicate and syndication detection.
- **Analytics substrate:** keyword/entity mention store, PMI associations, trend
  time-series (`src/analytics/*`), and framing/tone (`src/awareness/framing.py`,
  `src/api/framing.py`) — the basis for synchrony/echo metrics.
- **Provenance tags:** ownership (`state-media` / `public-broadcaster` /
  `wire-agency`) and leaning tags in `configs/sources_spectrum.yml`;
  `reliability_score`. Wire-agency tags already help spot syndication.
- **Coverage ledger:** `docs/ROADMAP.md` — where "surface, don't enforce" lives.

### Hard problems & risks (named honestly)

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

### Status

Vision / persistent memory — the **guiding document for `0.06`**; the phased build
is in [`ROADMAP.md` → "0.06 — The Intelligence Layer"](ROADMAP.md).

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


---

## Open-Omniscience — Action Plan

**Target environment:** Qubes OS · Debian AppVM · Python 3.13 · single primary user · loopback-only.
**Working branch:** `0.05` (direct, per owner's instruction).
**Companion doc:** [`DESIGN.md`](DESIGN.md) (what we're building & why).

> ## Implementation status (v0.0.6)
> **Phases 0–5 implemented and tested** on the `claude/kind-lovelace-ulpTc` branch
> (full suite green; see [`QUICKSTART.md`](QUICKSTART.md)):
> - **Phase 0/1 — Trustworthy core ✅:** single 3.13 manifest; clean DB session
>   layer (no import-time side effects); one ethical fetch path (robots fail-closed)
>   → trafilatura extraction → dedup/provenance; FTS5 Boolean search with correct
>   precedence; CSV/JSON export; offline vanilla UI; safe Qubes installer; honest
>   docs; security blocklist & silent fallbacks removed; fabricated detectors quarantined.
> - **Phase 2 — Local LLM ✅:** Ollama HTTP client (real model catalog, loud 503
>   degradation); summarize persists with provenance.
> - **Phase 3 — Commodity vertical ✅:** price time-series; correct unit conversion;
>   REAL scipy correlation (coefficient + p-value + n), no fabricated stats.
> - **Phase 4 — Enrichers ✅ (partial):** real source-uptime monitoring + z-score
>   anomalies; email (IMAP) into the unified corpus. Metadata/EXIF still deferred.
> - **Phase 5 — Defensible reporting ✅:** Merkle + Ed25519 signed evidence bundles;
>   standalone offline verifier (`scripts/verify_evidence.py`).
>
> Live integration of the whole flow verified against a running server. Remaining:
> live runs needing the operator's machine (real Ollama model, real scrape targets,
> real IMAP), metadata/EXIF revival, and burning down legacy lint debt.

### Operating rules for this plan

- **Trustworthy core first.** No pillar work until the spine (ingest → store → search → export) is
  genuinely working and tested. A small thing that works beats six that pretend to.
- **Delete before you build.** Fabricated/placeholder code is a liability; quarantine or remove it so it
  can't be mistaken for working functionality.
- **Every task has an acceptance check.** "Done" means the check passes, demonstrably, in the AppVM.
- **No silent failure.** Missing dep/model/source → explicit, visible status. Ever.
- **Commit in small, honest increments** on `0.05`. Commit messages describe *what changed and why*, not
  "fixed everything." Run tests before each commit.
- **Provenance everywhere.** If data enters the store, it carries source + timestamp + hash.

Legend: `[ ]` todo · `[~]` in progress · `[x]` done. Audit refs like `(P0-1)` map to the audit report.

---

### Phase 0 — Environment & ground truth

Goal: a clean, reproducible 3.13 environment in the AppVM, a single dependency manifest, and the
fabricated code quarantined so the core can be built on solid ground.

#### 0.1 Qubes / TemplateVM system preparation
> Qubes reminder: packages installed in the **AppVM** vanish on reboot. Install system deps in the
> **TemplateVM**, then reboot the AppVM. App + venv + data live in the AppVM's `/home` (persistent).

- [ ] In the **TemplateVM** (e.g. `debian-12`/`debian-13`-based), install system deps:
  ```bash
  sudo apt update
  sudo apt install -y python3.13 python3.13-venv python3.13-dev \
      build-essential git sqlite3 ca-certificates curl
  # (Optional, for LLM later) install Ollama in the TEMPLATE so the binary persists:
  #   verify checksum, then install — NOT a blind curl|sh (see 2.1)
  ```
  - [ ] Confirm `python3.13 --version` is available. If the Debian release lacks 3.13, document the
        source (deadsnakes-equivalent / backport) used.
- [ ] Shut down the TemplateVM; **reboot the AppVM** so new system packages are visible.
- [ ] **Acceptance:** in the AppVM, `python3.13 --version` works and survives an AppVM reboot.

#### 0.2 App location & virtualenv (persistent)
- [ ] Clone/locate the repo under `/home/user/` (persists). Recommended app/data root:
      `/home/user/open-omniscience` with data in `/home/user/open-omniscience/data`.
- [ ] Create the venv **inside `/home`**: `python3.13 -m venv .venv && . .venv/bin/activate`.
- [ ] **Acceptance:** venv activates; `python -V` shows 3.13; venv path is under `/home`.

#### 0.3 Repo inventory & branch
- [ ] Confirm on branch `0.05`. Snapshot current state (`git status`, `git log -1`).
- [ ] Produce a one-page module map: what's real vs fabricated (use the audit's P1-8 table).
- [ ] **Acceptance:** a checked-in `docs/HISTORY.md` listing keep / fix / delete per module.

#### 0.4 Quarantine fabricated subsystems (don't ship lies)
- [ ] Move out of the import/runtime path (a `quarantine/` dir or clearly-marked `experimental/`):
  - `pillar3/src/analysis/deepfake_detector.py`, `propaganda.py`, `cognitive_bias.py`, `bot_detector.py`
    (fabricated detection) — **keep** `metadata_validator.py` (real EXIF work) for later.
  - `pillar4/` simulated monitoring + nonexistent threat-intel (P1-8) — keep only genuinely-real bits.
  - `pillar5/`, `pillar6/` — design-only (0% per their READMEs); park until Phase 3.
- [ ] Remove the `src/main_pipeline.py` raw `requests.get` double-fetch + fallback (P1-1, P1-2).
- [ ] **Acceptance:** `python -c "import src.api.main"` succeeds with the quarantined code absent; no
      endpoint references a fabricated analyzer.

#### 0.5 Dependency reset → one 3.13 manifest
- [ ] Delete the six conflicting manifests (`requirements*.txt`, `pillar*/requirements.txt`,
      `configs/python/requirements.txt`) and the misplaced `configs/python/pyproject.toml` (P2-6).
- [ ] Author a **single root `pyproject.toml`**:
  - `requires-python = ">=3.13"`.
  - Core deps only: `fastapi`, `uvicorn[standard]`, `sqlalchemy>=2`, `pydantic>=2`, `pydantic-settings`,
    `requests`, `httpx`, `beautifulsoup4`, `feedparser`, `python-dateutil`, `structlog`, `slowapi`.
  - Robust extraction lib (verify 3.13 wheel): `trafilatura` **or** `readability-lxml` (pick in 1.3).
  - Optional extras: `[llm]` (just `httpx` — Ollama is external), `[analysis]` (`numpy`,`pandas`,`scipy`,
    `scikit-learn`,`statsmodels` — all 3.13-OK), `[dev]` (`pytest`,`pytest-cov`,`ruff`,`mypy`,`hypothesis`).
  - **Remove entirely:** `torch`, `onnx`, `onnxruntime`, `tensorflow`, `pyAudioAnalysis`, `transformers`,
    `librosa`, `opencv-python`, the `jose` (keep only `python-jose` *if* auth is ever needed), `dbpool`,
    `requests-rotating-proxy`, and all the AI-"corrective" comment pins (P2-5, P2-7, P2-8).
- [ ] `pip install -e ".[analysis,dev]"` in the AppVM venv.
- [ ] **Acceptance:** clean install on 3.13 with **no resolver errors**; `pytest` collects (even if 0
      tests yet); `ruff check` runs.

#### 0.6 `.python-version` & config truth
- [ ] Set `.python-version` to `3.13`. Make a single source of truth for the app version string (one
      value used by README, API `version=`, `/api/health`) (P2-2).
- [ ] **Acceptance:** `grep -r` shows one consistent version; `.python-version` == 3.13.

---

### Phase 1 — Trustworthy Core (the spine)

Goal: add a source → ethically scrape → dedup/normalize → store with provenance → search (correct
Boolean) → export. Running in the AppVM at `127.0.0.1:8000`, covered by behavioral tests.

#### 1.1 Database layer
- [ ] Remove the **duplicate** `get_session()` in `src/database/models.py` (keep one) (P1-11).
- [ ] Remove **import-time side effects**: no `create_all`, no monitor thread on import; move to an
      explicit `init_db()` called from the app lifespan (P0-11, B8).
- [ ] Provide a FastAPI **`Depends`-based session** (`yield`), used by every endpoint; delete manual
      `get_session()/try/finally` patterns (P1-11, B4).
- [ ] SQLite: enable **WAL**, sane timeouts; DB file under `/home/.../data/`. Drop
      `check_same_thread=False` global-session pattern (P0-10).
- [ ] **Acceptance:** unit test opens a session via the dependency, writes & reads a row, closes cleanly;
      importing `models` starts **no** threads and creates **no** tables.

#### 1.2 One ethical fetch path
- [ ] Make `src/compliance/ethical_scraper.py` the **only** fetch path; wire it into the pipeline (P1-3).
- [ ] Delete the double-fetch and the blocked-URL raw fallback in `main_pipeline._ingest` (P1-1, P1-2).
- [ ] robots.txt: **cache** per host, handle http+https, **fail-closed** on fetch error (don't scrape)
      (P0-… ethics; A6, A7). Per-source rate limiting actually enforced (A4).
- [ ] Remove the dead robots methods / false "respects robots" claims in
      `link_analyzer/source_scraper.py` or route it through the ethical scraper (P1-4).
- [ ] **Acceptance:** test with a stub robots.txt disallowing a path → that URL is **never** fetched
      (assert no HTTP call); a 2nd fetch of the same host reuses cached robots; rate-limit sleep invoked.

#### 1.3 Robust content extraction
- [ ] Replace generic CSS selectors with a real extractor (`trafilatura`/`readability`) producing
      title/body/date/lang; **no silent "No Title/No Content"** — failed extraction is recorded as an
      explicit error, not stored as junk (P1-10).
- [ ] **Acceptance:** test against 3 saved HTML fixtures (real article, paywalled stub, empty page):
      correct extraction for the article; explicit failure status for the others.

#### 1.4 Dedup, normalization, provenance
- [ ] Content-hash + canonical-URL dedup; never insert duplicates.
- [ ] Every stored record carries `{source, original_url, fetched_at, content_hash, raw_ref}` (§8 of
      synthesis).
- [ ] **Acceptance:** ingesting the same URL twice yields one row; provenance fields populated; test proves it.

#### 1.5 Search rewrite (the headline bug area)
- [ ] Delete `sanitize_sql_input` and its use in the query path (P0-8) — it corrupts queries and is fake
      security.
- [ ] Remove the `bindparam` string-concat hacks and the parenthesis-stripping parser (P1-5, P1-6, P1-7).
- [ ] Implement search via **SQLite FTS5 `MATCH`** (preferred: native Boolean + ranking) **or** a real
      parser (e.g. `pyparsing`) → SQLAlchemy AST. Must honor `AND/OR/NOT`, quoted phrases, and
      **parenthesised precedence**. All values parameterized by SQLAlchemy/FTS.
- [ ] **Acceptance (property/behavioral tests):**
  - `a OR b` returns the **union**; `a AND b` the intersection; `a NOT b` excludes b.
  - `(a OR b) AND c` ≠ `a OR (b AND c)` on a crafted fixture.
  - searching `"AT&T"` and `"oil prices DROP"` returns the right rows (no keyword stripping).

#### 1.6 API hardening
- [ ] Replace `@app.on_event("startup")` with a **lifespan** context manager; add graceful shutdown
      (dispose engine) (P3-11, D1).
- [ ] Bind to `127.0.0.1` only; mount `/metrics` on loopback (P0-5).
- [ ] Fix deprecated `datetime.utcnow()`; consistent timezone-aware timestamps.
- [ ] **Acceptance:** app starts/stops cleanly via lifespan; `ss -ltnp` shows listener only on 127.0.0.1.

#### 1.7 Installer rewrite for Qubes
- [ ] New installer with **two clearly-separated steps**: (a) *TemplateVM* system deps (printed
      instructions or a `--template` mode), (b) *AppVM* venv + app under `/home` (`--appvm` mode).
- [ ] Safety: **no unconfirmed `rm -rf`** (back up to timestamped dir, confirm interactively) (P0-1);
      **no unverified `curl | sh`** (download → checksum → run) (P0-2); **never** discard pkg stderr
      (P0-3). Check OS **before** touching anything.
- [ ] Real model tag for any LLM hint (no `gemma4:e2b`) (P2-4).
- [ ] **Acceptance:** dry-run on a fresh AppVM: app installs to `/home`, survives AppVM reboot; re-running
      the installer does **not** destroy existing data without an explicit confirm.

#### 1.8 Front-end cleanup
- [ ] Vendor all assets (fonts, any JS libs) under `/static`; remove **all** CDN references (P2-10).
- [ ] Remove Tkinter/desktop remnants and `python3-tk` (web UI only).
- [ ] Single canonical `index.html`; service worker only caches existing local files.
- [ ] **Acceptance:** load the UI with the NetVM detached → no failed external requests in devtools.

#### 1.9 Tests + honest CI/local runner
- [ ] Behavioral test suite for 1.1–1.8 (pytest); coverage threshold that's *real* (start modest, e.g.
      60% of `src/`, and meaningful).
- [ ] Replace the dead CI (missing `requirements-all.txt`, `.pre-commit-config.yaml`, `mkdocs.yml`,
      `main`/`master` split) with either a working GH Actions workflow **or** a documented local
      `make test` / `make lint` that actually runs on 3.13 (P3-10).
- [ ] Delete/replace the fictional QA reports so they can't mislead (the README already says
      "not functional" — make docs tell one true story).
- [ ] **Acceptance:** `pytest` green locally in the AppVM; `ruff`/`mypy` run; no test references
      quarantined code.

#### ✅ Phase 1 Definition of Done
Demonstrate end-to-end in the AppVM: add a source via the UI/API → trigger scrape → see deduped,
provenance-tagged articles → run a Boolean search with parentheses → export CSV+JSON matching the
filter — with the whole flow covered by passing tests and the server bound to loopback.

---

### Phase 2 — Local LLM + Scientific Rigor

Goal: local, honest AI analysis over the stored corpus; numeric outputs carry real uncertainty.

#### 2.1 Ollama integration (HTTP only, CPU-first)
- [ ] App talks to Ollama over HTTP (`httpx`); **no** `torch`/`transformers` in the app.
- [ ] Real, existing model catalog; default a **small CPU model** (`gemma2:2b` / `llama3.2:3b` /
      `qwen2.5:1.5b`); large models opt-in.
- [ ] Installer/setup pulls the default model **into `/home`** (persistent) with progress + checksum.
- [ ] **Loud degradation:** if Ollama unreachable or model missing → explicit `503` with a clear message,
      never a fake result.
- [ ] Endpoints are **non-blocking**: plain `def` (Starlette threadpool) or true async `httpx`; remove
      fake-async/`get_event_loop`/per-request executors (P3-1..5).
- [ ] **Acceptance:** with a pulled model, `generate`/`summarize`/`translate`/`extract` work on a stored
      article; with Ollama stopped, the API returns an explicit unavailable status (tested).

#### 2.2 LLM wired to the corpus
- [ ] LLM operations run on selected stored articles (summarize, translate, extract entities) and write
      results back **with provenance** (model, prompt version, timestamp).
- [ ] **Acceptance:** summarize a stored article; result persisted and linked to the source record.

#### 2.3 Pillar 2 — Scientific Rigor as the "honesty gate"
- [ ] Harden the real stats (scipy/statsmodels); every number surfaced to the user passes through
      uncertainty reporting (CI / n / method).
- [ ] Remove hardcoded confidences anywhere they remain (`confidence=0.8` etc.) (P1-8).
- [ ] **Acceptance:** any analytic value in an API response includes its method + uncertainty basis;
      tests assert no constant-confidence outputs.

---

### Phase 3 — One vertical + correlation (pick ONE)

Goal: prove the cross-reference experience on a *thin but real* slice. **⚠️ DECIDE: financial (Pillar 5)
or commodity (Pillar 6) first.**

- [ ] Minimal real scraper for the chosen vertical (a *few* sources, daily values), ethical path reused.
- [ ] Store time-series alongside articles in the unified DB with link table.
- [ ] Correlation surfaced as a **candidate** relationship with an honest, defined measure; clearly label
      "correlation ≠ causation"; **no fabricated p-values** (P1-8).
- [ ] If commodity: fix the unit-normalization bug (oz→kg factor) and add currency conversion (P1-9).
- [ ] **Acceptance:** for one instrument/element, the UI shows price moves with temporally-nearby
      articles and a stated, reproducible correlation measure.

---

### Phase 4 — Enrichers (one at a time, each real)

- [ ] **Email (P1):** IMAP + RSS-to-email only for v1; parse/clean → into the corpus; encrypted
      credential storage; consent/retention documented (defer Substack/Mailchimp APIs).
- [ ] **Monitoring (P2):** *real* source-uptime checks (actual HTTP, not `sleep; HEALTHY`) (P1-8) +
      anomaly alerts on corpus volume. Defer STIX/TAXII, SMS, chat.
- [ ] **Verification (P2):** ship only the genuine `metadata_validator` (EXIF/ID3) — clearly scoped as
      "metadata checks," not "deepfake detection."
- [ ] **Acceptance (each):** the feature works against a real fixture and is tested; absent deps degrade
      loudly.

---

### Phase 5 — Defensible reporting

- [ ] Wire the existing crypto modules into a **real** chain-of-custody: signed, tamper-evident export
      manifest (hashes + Merkle/GPG) for evidence bundles (P1-14).
- [ ] Reports bundle findings **with** provenance + method + uncertainty.
- [ ] **Acceptance:** export an evidence bundle; an independent script verifies its signature/hashes.

---

### Cross-cutting (apply throughout)

- **Concurrency hygiene:** `get_running_loop()` not `get_event_loop()`; shared, shut-down executors; no
  per-item pools; bounded `gather` with semaphores; fix the broken manual batching (P3-1..7).
- **Logging:** structured logs under `/home`; no `except: pass`; specific exceptions; visible warnings.
- **Docs discipline:** one true README; kill version drift; retire the fictional QA/debug reports.
- **License:** decide GPLv3 vs AGPL-3.0 and apply consistently (synthesis §9.9).

### First session checklist (start here)

1. [ ] Phase 0.1–0.2 — TemplateVM deps + AppVM venv on 3.13.
2. [ ] Phase 0.4 — quarantine fabricated pillars; remove double-fetch.
3. [ ] Phase 0.5 — single `pyproject.toml`; clean install on 3.13.
4. [ ] Phase 1.1 — DB session DI + no import-time side effects.
5. [ ] Phase 1.5 — search rewrite with Boolean tests (the highest-value correctness fix).

> After each numbered item: run tests, commit on `0.05` with a precise message, move on.

---

## Phase 6 — Path to Functional v1.0 (post-merge upgrade)

Phases 0–5 delivered a *working prototype*. Phase 6 makes the **repository** (not
just the running app) genuinely functional and trustworthy. See
[`HISTORY.md`](HISTORY.md) for the findings that drive this.

Operating rule unchanged: every item ends green and tested; delete-before-build;
no silent failure; honest provenance.

#### 6.1 Purge the dead/fabricated bulk (biggest quality lever)
> ~64% of `src/` is never loaded by the app. Removing it makes the repo readable
> and removes latent footguns. Verify each module is referenced by *no* other
> `src/` or `tests/` file before moving it to `quarantine/` (kept in history).
- [ ] Remove fabricated/over-engineered orphans: `scraper/distributed.py`,
      `llm/optimizer.py`, `database/query_optimizer.py` (also kills its **latent
      SQL injection**), `api/performance.py`, `utils/performance.py`,
      `database/optimization.py`, the superseded `compliance/ethical_scraper.py`.
- [ ] **Keep** legitimately-deferred infra: `database/async_db.py` (future Postgres),
      `database/migrations/*` (Alembic), `main_pipeline.py` (still test-referenced).
- [ ] Decide the fate of the legacy LLM module (`llm/config.py` etc. with the
      hallucinated catalog) — it survives only to satisfy `test_llm.py`. Either
      rewrite those tests against the new `llm/ollama.py` and delete the legacy
      module, or quarantine both together.
- [ ] **Acceptance:** full suite green after each batch; `src/` live-LOC ratio
      rises well above 50%; `ruff check src/` findings drop sharply.

#### 6.2 Immediate utility — seed real, ethical sources
- [ ] Ship a small curated list of **real, robots-friendly RSS feeds** (e.g. major
      wire services / public-interest outlets) as `configs/default_sources.yaml`.
- [ ] `scripts/seed_sources.py` (and an installer `--seed` step) to load them.
- [ ] **Acceptance:** a fresh install can ingest and search real news with zero
      manual setup; tested with a fixture feed.

#### 6.3 Real migration path
- [ ] Wire Alembic to the live models; generate the baseline + a migration for the
      new tables (`article_analyses`, `commodity_prices`). `init_db()` stays for
      fresh installs; existing DBs upgrade via `alembic upgrade head`.
- [ ] **Acceptance:** an old DB (pre-v0.4 schema) upgrades cleanly; tested.

#### 6.4 Harden the live legacy routers
- [ ] Add behavioural tests for the source/keyword/link routers actually wired in
      (`source_management`, `keyword_management`, `keyword_analysis`, `link_analysis`):
      create/list/update/delete a source; extract keywords; classify a link.
- [ ] Fix anything they get wrong (route each through the ethical fetcher; ensure
      parameterized DB access). Replace any remaining `datetime.utcnow()` in *live*
      code with timezone-aware now.
- [ ] **Acceptance:** each live router has at least one happy-path + one error test.

#### 6.5 Pillar 2 as the honesty gate
- [ ] Surface the genuine scientific-rigor utilities (real scipy/statsmodels) so any
      numeric the app returns carries method + uncertainty (extend what the
      commodity correlation already does to other computed values).
- [ ] **Acceptance:** tests assert no constant/hardcoded confidence in live outputs.

#### 6.6 Lint debt burn-down (safe + incremental)
- [ ] Run `ruff --fix` **per-module on live files only**, never repo-wide (a blanket
      fix once removed intentional back-compat re-exports). Add `ruff format`.
- [ ] Flip CI ruff from advisory to blocking once live modules are clean.
- [ ] **Acceptance:** `ruff check src/<live tree>` clean; CI lint blocking.

#### 6.7 Verticals & remaining enrichers (lower priority)
- [ ] One real, thin commodity scraper from an open source (e.g. USGS) feeding the
      existing price/correlation machinery — ethical path reused, fixture-tested.
- [ ] Currency conversion with an explicit, dated FX rate (never a hardcoded guess).
- [ ] Newsletter-API email sources (Substack/Mailchimp) beyond IMAP, if wanted.

### Definition of "Functional v1.0"
A fresh Qubes AppVM install seeds real sources, ingests and searches live news,
summarizes locally via Ollama, exports a verifiable evidence bundle — and the
repository a maintainer opens contains *only code that runs*, is lint-clean on the
live tree, migrates cleanly, and has a test for every exposed endpoint.

---

## 0.06 — The Intelligence Layer: implementation strategy & action plan

**Pairs with** [`ROADMAP.md`](ROADMAP.md) (the *what & why*;
this is the *how*). **Working branch:** `0.06`. Operating rules unchanged: every item
ends green and tested; delete-before-build; no silent failure; honest provenance;
**no card without a method + caveat + evidence link**.

The thesis of 0.06 is **one measurement engine, many domains**. We are *not* building
a dozen features; we are building a *small centralised substrate* and pointing it at
each domain. The whole of §4–§6 composes from four new primitives plus a card
framework — everything else already exists.

### North-star architecture (structural, centralised, mutualised)

```
            ┌──────────────────────────────────────────────────────┐
  corpus →  │  src/signals/  (pure, DB-free, unit-tested primitives)│
            │   concentration · near_dup/coordination · novelty ·   │
            │   (reuse) correlation · anomaly · tone · change-diff   │
            └───────────────┬──────────────────────────────────────┘
                            │  measured facts (+ method + caveat)
            ┌───────────────▼──────────────────────────────────────┐
  src/briefing/  card producers: corpus → [Card]  (one per feature) │
            │   Card = {type,title,signal,method,caveat,bucket,     │
            │           evidence[], n, created_at, dismissible}      │
            └───────────────┬──────────────────────────────────────┘
        scheduler precompute│ (incremental, cached — Home loads instantly)
            ┌───────────────▼───────────┐     ┌──────────────────────┐
            │  /api/briefing (feed)      │ ──▶ │  Home = the briefing  │
            │  /api/sources/{id}/profile │     │  cards → "add to draft"│
            └────────────────────────────┘     │  draft → MD + custody  │
                                               └──────────────────────┘
```

**Design rules that make it mutualised and centralised:**
1. **`src/signals/` primitives are pure** — they take plain inputs (sequences,
   counts, vectors) and return a result object carrying `method`, `caveat`, `n`. No
   primitive touches the DB, the API, or the UI. → trivially unit-testable, reused by
   every domain, never duplicated.
2. **Every feature is a *card producer*** — a function `corpus → [Card]`. Adding a
   capability = registering one producer; it lights up in the *same* Home feed. There
   are **no orphan endpoints**.
3. **One Card schema, one feed, one draft.** The briefing is the single surface; the
   source-profile panel (§6 C) is the only other. This is the GUI-adoption guarantee.
4. **No composite score, ever** — a CI/test guard forbids a `trust_score`/`score`
   field on Card and Source (§6 B is banned in code, not just prose).

### GUI is the product (adoption discipline)

> "If one tool is not used, despite being useful, it is useless."

Therefore 0.06 is **GUI-first**, not API-first:
- **Build the Home briefing FIRST** (Phase A), even with three cards — so every later
  capability has a place to appear and is *seen the day it ships*.
- **A feature is not "done" until it is a card or a panel the user actually sees** —
  acceptance for every later phase includes "renders in the briefing / profile".
- **The payoff loop is visible**: card → *Add to draft* → Markdown + custody receipts.
  The user feels value on day one, not after a backend epic.
- **Always-available escape hatch**: the raw equal-treatment view (no collapse, no
  weighting) is one toggle away on every screen — transparency *is* the UI.

### App efficiency (offline, single machine)

- **Precompute on the existing scheduler, cache, serve cached.** The briefing never
  computes per request; Home reads a cached card set → instant load.
- **Incremental, not full-rescan**: signals update from the ingest delta (new
  articles), reusing the keyword/link indexing hooks that already run on ingest.
- **Hashing & graphs over ML**: near-dup via MinHash + LSH (sublinear), coordination
  as a graph, concentration as counting, novelty as an incremental index lookup. No
  heavy models; no "AI-text detector".
- **Bounded everywhere**: caps on cards per bucket, candidates per query, graph size —
  the same discipline as the bounded crawler.

### Mutualisation map (one engine → many domains)

| New primitive (`src/signals/`) | Reused by |
|---|---|
| `concentration` (Gini / top-share) | §1 ownership · people-prominence · §6 actor share |
| `near_dup` + `coordination` (MinHash/LSH → actor graph) | echo cards · model-legislation (§5) · syndication (§2) · **§6 actor-collapse** |
| `novelty` (surprisal vs corpus) | §6 anti-amplification weighting · "lonely signal" |
| (reuse) `correlation`,`anomaly`,`tone`,`change-diff` | markets · law↔news · spikes · tone cards · stealth-correction |

---

### Phase A — The card + briefing framework (the GUI spine)  ⟵ start here

> **Status: shipped & tested.** `src/briefing/` (Card + registry + producers +
> service/cache + draft), `/api/briefing*`, the scheduler precompute hook, and the
> redesigned **Home** card feed are implemented; the full suite is green incl. the
> `no-score-field` honesty guard (`tests/test_briefing*.py`,
> `tests/test_signals_concentration.py`). See [`USER_MANUAL.md`](USER_MANUAL.md).

- [x] `src/briefing/`: the `Card` dataclass + a producer registry; `/api/briefing`
      assembling cards from producers; scheduler precompute + cache.
- [x] Redesign **Home** as the card feed (triage: keep/dismiss/→draft), grouped by
      bucket (rising/overtold/undertold/investigate/context/trust).
- [x] **Draft accumulator** (pin cards + notes) → **Markdown export** carrying every
      card's evidence links; custody receipts referenced (export a signed evidence
      bundle from Evidence & custody to ship with the issue).
- [x] Seed with **now-status** producers only (no new math): Rising (trending),
      Framing split, Record-reshaped (wiki), Price↔narrative, Stale-data — plus the
      **Diet self-audit** (which exercises the new `concentration` primitive).
- [ ] **Belief/ideology + faith-media source-tag axis** (neutral, contestable,
      editable): extend source tags so family-grouped cards (tone-by-family,
      prominence-by-family, coordination grouping) work. (Generator spec already
      added in 0.05; this tags existing sources.) → §4 belief axis. *(deferred to a
      follow-up; framing_split already groups by source.)*
- [~] **Tone-by-source / tone-by-family** card producer (VADER + `context` window
      already exist — *now/thin*). → §4 tone & emotion. *(per-source tone shipped via
      the Framing-split card; the family-grouped matrix is the follow-up.)*
- [x] **Acceptance:** fresh corpus → Home shows real cards from cached precompute;
      pinning three → exported Markdown with working source links; equal-view toggle
      present; a test asserts no `score` field exists on `Card`.

### Phase B — Signal primitives (`src/signals/`, pure & mutualised)

> **Status: started.** `concentration.py` is implemented, pure, and property-tested
> (`tests/test_signals_concentration.py`); it already powers the Diet self-audit card.
> `near_dup`/`coordination` and `novelty` are intentionally next (the riskiest math —
> do it properly or not at all).

- [x] `concentration.py` (Gini + top-N share, with method/caveat/n).
- [x] `near_dup.py` (MinHash + LSH) → `coordination.py` (actor graph from
      near-dup + lockstep timing + shared host fingerprints).
- [x] `novelty.py` (information contributed vs an incremental corpus index).
- [x] Each primitive: pure, DB-free, property-tested in isolation.
- [x] **Acceptance:** unit tests on crafted fixtures (a known cluster collapses; a
      Gini of a known distribution matches; a pure echo scores ~0 novelty); zero DB
      imports in `src/signals/` (`tests/test_signals_*`).

### Phase C — Source integrity: profile + anti-amplification (§6 C+D)

> **Status: shipped & tested.** `src/integrity/` (actors, user-guided collapse, the
> no-composite profile), `/api/integrity/*`, the **Source integrity** GUI tab, and the
> echo-chamber / lonely-signal / capacity-implausible cards are implemented. The 40-puppet
> acceptance is a passing test (`tests/test_integrity.py`). See [`USER_MANUAL.md`](USER_MANUAL.md).
>
> **User-guided, user-aware, GUI-mediated (§6 non-negotiable).** Anti-amplification is
> never a silent transform the user merely *undoes* — it is **propose → user disposes**,
> expressed through the interface. Default = **"equal but aware"** (raw equal view, with
> manipulation structure *annotated on it*), not silent collapse and not naive equality.
> There is **no headless auto-clean path**: the GUI is a *necessary* interface because the
> human judgment *is* the mechanism.

- [x] **Actor graph + collapse (D):** detect coordinated actors and, **when the user
      applies it**, operate briefing counts (trend/prominence/synchrony) on **actors
      weighted by novelty** rather than raw outlet volume. The app **proposes** a collapse
      with its evidence (shared infra / lockstep timing / near-dup); the user applies it
      **globally or per-cluster**, never auto-applied. Every applied collapse stays
      **visibly flagged**, one click to expand-to-members / treat-as-separate / override.
- [x] **Source profile panel (C):** per source, the measured signals as a panel —
      coordination/actor, novelty ratio, output-capacity plausibility, transparency
      facts, corpus track-record — **no composite** (`/api/integrity/profile` + the GUI
      panel). User-weighting of dimensions is the user's own read; off by default, reversible.
- [x] New cards fall out for free: Echo-chamber, Lonely-signal, Capacity-implausible.
- [x] **Acceptance:** on a synthetic 40-puppet flood, the **default** briefing shows the
      cluster *annotated* (not silently collapsed); the app **proposes** a collapse with
      evidence; **only on the user's action** (global or that one cluster) does the flood
      stop dominating while a genuine single original source *rises*; the applied collapse
      stays flagged and expands to its 40 members; toggling it off reproduces the raw
      equal counts exactly. A test asserts no collapse is applied without an explicit
      user action. *(Collapse merges a coordinated network to **one voice**; an opt-in
      **novelty-weighting** of prominence — off by default, never silent — additionally
      down-weights low-information echoes, `story_prominence(weight_by_novelty=True)`.)*

### Phase D — Crowdsourced annotation bundles (the C scaling answer)

> **Status: shipped & tested.** `src/annotations/` (signed bundle build/verify reusing
> the hybrid custody signer, local store, web-of-trust, transparent aggregation),
> `/api/annotations/*`, and the GUI in the Source integrity tab. See
> [`USER_MANUAL.md`](USER_MANUAL.md); acceptance in `tests/test_annotations.py`.

- [x] Annotation = a signed, portable bundle (reuse the **custody/evidence** machinery)
      of source facts/tags/corrections; **export/import**; opt-in **web-of-trust**
      selection of whose bundles to load.
- [x] **Transparent aggregation:** show *who asserted what*; surface dissent, never
      average it into a hidden number. No server, no accounts, no global score.
- [x] **Acceptance:** export a bundle, verify its signature; import two conflicting
      bundles → the aggregation shows both attributions (dissent surfaced); removing a
      trusted author cleanly removes their annotations; a tampered bundle is refused.

### Phase E — Verticals on the shared engines (lower priority)

> **Status: shipped.** The **world-law change-tracking vertical** is built (`src/law/`,
> `/api/law/*`, the **World law** GUI tab, the `law` scheduler mode) with a **worldwide
> catalog of real official sources** (`configs/legal_sources.yml`) seeded **by default**;
> the composable news-corpus cards (IP/legal pulse, ownership-change) and the
> **emotion-category** card ship too. See [`USER_MANUAL.md`](USER_MANUAL.md);
> `tests/test_law.py`, `tests/test_awareness_emotion.py`.

- [x] **Law change-tracking (§5):** worldwide official sources (UK `legislation.gov.uk`,
      EUR-Lex, Légifrance, govinfo/congress, IP offices, …) seeded by default; tracking on
      the wiki change-tracking pattern (baseline → normalised-text diff → flag) through the
      ethical fetcher; cross-jurisdiction near-dup (Phase B) surfaces **model-legislation**;
      law↔news rides the existing correlation engine. *(Per-edit Akoma Ntoso/ELI structured
      diffs are the next refinement; v1 is normalised-text diff — stated honestly.)*
- [~] **IP/legal primary-source (§4):** IP offices + filing systems (USPTO, EPO, EUIPO,
      WIPO Lex, SEC EDGAR, CourtListener) are seeded and ingestible; structured
      patent/docket *parsing* into a price-feed-style series is the remaining refinement.
- [x] **IP/legal *news* cards (§4):** ownership-change + IP-litigation pulse — deal-verb
      and IP/legal-term producers over the *news* corpus (thin). Deal-lineage / IP↔deal
      co-timing build on these next.
- [x] **Emotion-category card (§4):** anger/fear/joy/… around a keyword via an emotion
      lexicon (`src/awareness/emotion.py`); a minimal English sample ships,
      `OO_EMOTION_LEXICON` overrides; degrades loudly if absent.
- [x] **Acceptance:** a worldwide legal catalog seeds by default; a tracked document goes
      baseline → change → honest flag (tested with a stub fetcher); a model-legislation
      near-dup match is shown across two jurisdictions (tested).

---

### Implications & risks (think before building)

- **The honesty guards must be *in code*, not just docs:** the banned composite score,
  the always-available equal view, **user-applied (never auto) actor-collapse that stays
  flagged and expandable**, and method+caveat+evidence on every card are **acceptance
  criteria and tests**, not conventions.
- **False merges are the worst failure** — Phase C biases toward *under*-merging and
  always shows the evidence for a merge; a wrong collapse must be one click to undo.
- **Migration:** new tables (cards cache, actor graph, annotations) via Alembic
  (§6.3 discipline); `init_db()` for fresh installs, `upgrade head` for existing.
- **Scope honesty:** Phases A–C are the core of 0.06; D and E can slip without
  blocking value. Ship A first — value on day one — then deepen.

### Definition of "0.06 done"
Home greets the user with a real, cached **briefing** of honest cards drawn from the
shared `src/signals/` engine; coordinated floods are **surfaced and annotated by
default**, and — **when the user applies the proposed collapse** — fold into single
low-novelty actors (visibly flagged, expandable, the equal view one toggle away) while
small original sources **rise**; each source has a **no-composite profile** the user
can weight;
annotations are **shared as signed bundles**; and any card the user pins exports to a
**provenance- and custody-carrying draft** — with the whole surface covered by tests,
including a guard that **no trust-score field exists anywhere**.


---

## Email & Newsletter Intelligence Implementation Plan

### 📧 Overview

This document outlines the implementation plan for extending Open-Omniscience to support **email retrieval, archive, and analysis** capabilities. This feature will enable the platform to process both **public and private newsletter intelligence**, significantly enhancing its investigative journalism capabilities.

### 🎯 Objectives

1. **Email Retrieval**: Fetch emails from various sources (IMAP, POP3, API-based newsletters)
2. **Archive Management**: Store and organize email/newsletter data efficiently
3. **Content Analysis**: Extract insights, entities, and patterns from email content
4. **Integration**: Seamlessly integrate with existing Open-Omniscience infrastructure
5. **Privacy & Security**: Ensure ethical handling of private communications

---

### 🏗️ Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    Email & Newsletter Module                    │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │  Retrieval   │  │  Processing  │  │    Analysis         │  │
│  │  Layer      │──▶│  Pipeline    │──▶│    Engine           │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                          │                          │
         ▼                          ▼                          ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│  Email Sources   │  │  Database        │  │  Existing        │
│  - IMAP/POP3     │  │  - Metadata      │  │  Analysis        │
│  - Newsletter APIs│  │  - Content       │  │  - NLP           │
│  - RSS-to-Email  │  │  - Attachments   │  │  - Entity        │
│  - Forwarded     │  │  - Index         │  │  - Link          │
└─────────────────┘  └─────────────────┘  │  │  Analysis        │
                                              └─────────────────┘
```

---

### 📁 Directory Structure

```
src/
├── email_intelligence/
│   ├── __init__.py
│   ├── config.py              # Configuration for email sources
│   ├── models.py              # Database models for emails/newsletters
│   ├── retrieval/
│   │   ├── __init__.py
│   │   ├── imap_client.py      # IMAP email retrieval
│   │   ├── pop3_client.py      # POP3 email retrieval
│   │   ├── api_client.py       # Newsletter API clients (Substack, etc.)
│   │   ├── rss_to_email.py     # Convert RSS feeds to email format
│   │   └── scheduler.py        # Scheduled retrieval
│   ├── processing/
│   │   ├── __init__.py
│   │   ├── parser.py           # Email content parsing (HTML, plain text)
│   │   ├── cleaner.py          # Clean and normalize content
│   │   ├── attachment_handler.py # Handle attachments
│   │   └── pipeline.py         # Processing workflow
│   ├── analysis/
│   │   ├── __init__.py
│   │   ├── metadata_extractor.py # Extract sender, subject, dates, etc.
│   │   ├── content_analyzer.py  # Analyze email content
│   │   ├── entity_extractor.py  # Extract entities (people, orgs, locations)
│   │   ├── sentiment_analyzer.py # Sentiment analysis
│   │   └── network_analyzer.py  # Analyze communication networks
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py         # Database storage operations
│   │   ├── filesystem.py       # Filesystem storage for attachments
│   │   └── search_index.py      # Search indexing
│   └── api/
│       ├── __init__.py
│       ├── routes.py           # API endpoints for email management
│       └── schemas.py          # Pydantic schemas
├── services/
│   └── email_service.py        # Main email service integration
configs/
└── email_sources.yaml         # Configuration for email sources
```

---

### 🔧 Core Components

#### 1. Email Retrieval Layer

##### IMAP/POP3 Client
- **Purpose**: Connect to email servers and fetch messages
- **Features**:
  - SSL/TLS support
  - Incremental fetching (only new emails)
  - Folder/subscription management
  - Error handling and retry logic
  - Rate limiting

##### Newsletter API Clients
- **Supported Services**:
  - Substack (via RSS or API)
  - Mailchimp
  - ConvertKit
  - Revue
  - Ghost
  - Custom RSS feeds

##### Scheduler
- **Purpose**: Manage when and how often to check for new emails
- **Features**:
  - Configurable intervals per source
  - Priority-based scheduling
  - Timezone-aware
  - Manual trigger capability

#### 2. Processing Pipeline

##### Email Parser
- **Input**: Raw email (MIME format)
- **Output**: Structured data
- **Processing**:
  - Extract headers (From, To, Subject, Date, etc.)
  - Parse HTML and plain text content
  - Handle multipart messages
  - Extract attachments
  - Normalize encoding

##### Content Cleaner
- **Purpose**: Prepare content for analysis
- **Features**:
  - Remove boilerplate (signatures, disclaimers)
  - Strip HTML (optional)
  - Normalize whitespace
  - Detect and handle forwarded messages
  - Extract quoted text

##### Attachment Handler
- **Supported Types**:
  - PDF documents
  - Office files (DOCX, XLSX, PPTX)
  - Images (JPEG, PNG, GIF)
  - Archives (ZIP, RAR)
- **Processing**:
  - Text extraction from documents
  - OCR for images
  - Virus scanning (optional)
  - Secure storage

#### 3. Analysis Engine

##### Metadata Extractor
- **Extracts**:
  - Sender/recipient information
  - Timestamps (sent, received, read)
  - Email headers analysis
  - Thread/conversation tracking
  - Domain analysis

##### Content Analyzer
- **Features**:
  - Keyword extraction
  - Topic modeling
  - Language detection
  - Text summarization
  - Duplicate detection

##### Entity Extractor
- **Extracts**:
  - People (names, email addresses)
  - Organizations
  - Locations
  - Dates and times
  - URLs and domains
  - Phone numbers

##### Network Analyzer
- **Analyzes**:
  - Communication patterns
  - Reply chains
  - CC/BCC relationships
  - Domain connections
  - Temporal patterns

#### 4. Storage Layer

##### Database Models
```python
class EmailSource(Base):
    # Configuration for email/newsletter sources
    id: int
    name: str
    source_type: str  # imap, pop3, api, rss
    connection_config: dict  # Server, port, credentials (encrypted)
    enabled: bool
    last_checked: datetime
    next_check: datetime
    error_count: int

class EmailMessage(Base):
    # Stored email messages
    id: str  # Message-ID or UUID
    source_id: int
    message_id: str  # Email Message-ID header
    thread_id: str  # Conversation thread
    in_reply_to: str  # Reference to parent message
    
    # Metadata
    from_address: str
    to_addresses: list
    cc_addresses: list
    bcc_addresses: list
    subject: str
    date_sent: datetime
    date_received: datetime
    
    # Content
    plain_text: str
    html_content: str
    content_hash: str  # For duplicate detection
    
    # Analysis
    language: str
    sentiment_score: float
    entities: list
    topics: list
    
    # Status
    is_read: bool
    is_processed: bool
    is_archived: bool
    
    # Timestamps
    created_at: datetime
    updated_at: datetime

class EmailAttachment(Base):
    # Email attachments
    id: int
    email_id: str
    filename: str
    content_type: str
    file_size: int
    file_hash: str
    storage_path: str
    extracted_text: str  # Text extracted from document
    
    # Analysis
    entities: list
    topics: list
```

##### Filesystem Storage
- **Attachments**: Stored in `data/attachments/` with organized directory structure
- **Raw Emails**: Optional raw email storage for audit
- **Index**: Search index for fast retrieval

---

### 🔐 Security & Privacy Considerations

#### Data Protection
1. **Encryption**:
   - Database encryption for sensitive fields
   - TLS for all email retrieval
   - Encrypted storage of credentials

2. **Access Control**:
   - Role-based access to email sources
   - Audit logging for all access
   - Data retention policies

3. **Privacy Compliance**:
   - GDPR compliance for EU data
   - Right to be forgotten implementation
   - Data minimization principles

#### Ethical Guidelines
1. **Consent**: Only process emails with proper authorization
2. **Transparency**: Clear documentation of what data is collected
3. **Purpose Limitation**: Use data only for intended investigative purposes
4. **Data Minimization**: Collect only necessary data
5. **Retention**: Implement automatic data deletion policies

---

### 📋 Implementation Phases

#### Phase 1: Foundation (Week 1-2)
- [ ] Create directory structure
- [ ] Implement configuration system
- [ ] Create database models
- [ ] Set up basic API endpoints
- [ ] Implement IMAP client
- [ ] Create email parser

#### Phase 2: Core Retrieval (Week 3-4)
- [ ] POP3 client implementation
- [ ] Newsletter API integrations (Substack, Mailchimp)
- [ ] RSS-to-email converter
- [ ] Scheduler implementation
- [ ] Error handling and retry logic

#### Phase 3: Processing Pipeline (Week 5-6)
- [ ] Content cleaning and normalization
- [ ] Attachment handling
- [ ] Duplicate detection
- [ ] Processing workflow orchestration
- [ ] Performance optimization

#### Phase 4: Analysis Engine (Week 7-8)
- [ ] Metadata extraction
- [ ] Content analysis
- [ ] Entity extraction
- [ ] Network analysis
- [ ] Integration with existing analysis modules

#### Phase 5: Integration & Testing (Week 9-10)
- [ ] Web interface integration
- [ ] Search functionality
- [ ] User management integration
- [ ] Comprehensive testing
- [ ] Documentation

---

### 🛠️ Technical Requirements

#### Dependencies
```
## Email protocols
imaplib (built-in)
poplib (built-in)
smtplib (built-in)

## Email parsing
email (built-in)
beautifulsoup4
html2text

## API clients
requests
httpx

## Document processing
pdfminer.six
python-docx
openpyxl
pillow
pytesseract (for OCR)

## Analysis
spacy
nltk
textblob

## Storage
sqlalchemy
alembic
```

#### Configuration
```yaml
## configs/email_sources.yaml
email_sources:
  - name: "Personal Gmail"
    type: imap
    enabled: true
    config:
      server: imap.gmail.com
      port: 993
      username: "user@gmail.com"
      password: "${EMAIL_PASSWORD}"  # From environment
      ssl: true
      folders:
        - INBOX
        - Newsletters
      fetch_since: "2024-01-01"
      interval_minutes: 60

  - name: "Substack Newsletter"
    type: substack
    enabled: true
    config:
      publication: "the-investigator"
      api_key: "${SUBSTACK_API_KEY}"
      interval_hours: 24

  - name: "Company Mailchimp"
    type: mailchimp
    enabled: true
    config:
      list_id: "abc123"
      api_key: "${MAILCHIMP_API_KEY}"
      interval_hours: 12
```

---

### 📊 API Endpoints

```
## Email Sources Management
POST   /api/email/sources              # Create new email source
GET    /api/email/sources              # List all email sources
GET    /api/email/sources/{id}         # Get specific source
PUT    /api/email/sources/{id}         # Update source
DELETE /api/email/sources/{id}         # Delete source
POST   /api/email/sources/{id}/test    # Test connection

## Email Messages
GET    /api/email/messages             # List messages (with filters)
GET    /api/email/messages/{id}        # Get specific message
GET    /api/email/messages/{id}/raw    # Get raw email
POST   /api/email/messages/{id}/reprocess # Reprocess message
DELETE /api/email/messages/{id}        # Delete message

## Email Analysis
GET    /api/email/messages/{id}/analysis # Get analysis results
GET    /api/email/analysis/entities     # Search entities across emails
GET    /api/email/analysis/network     # Get communication network

## Attachments
GET    /api/email/attachments          # List attachments
GET    /api/email/attachments/{id}     # Get attachment metadata
GET    /api/email/attachments/{id}/download # Download attachment

## Scheduler
GET    /api/email/scheduler/status     # Get scheduler status
POST   /api/email/scheduler/run        # Manually trigger retrieval
POST   /api/email/scheduler/pause      # Pause scheduler
POST   /api/email/scheduler/resume     # Resume scheduler
```

---

### 🎨 Web Interface Integration

#### New Pages
1. **Email Sources Management**
   - Add/edit/delete email sources
   - Connection testing
   - Status monitoring

2. **Email Inbox**
   - List of retrieved emails
   - Search and filtering
   - Bulk operations

3. **Email Detail View**
   - Full email content display
   - Attachment preview/download
   - Analysis results visualization

4. **Analysis Dashboard**
   - Email statistics
   - Entity extraction results
   - Communication network visualization
   - Trend analysis

#### Existing Pages Enhancements
1. **Search**: Include email content in global search
2. **Source Management**: Add email sources alongside web sources
3. **Reports**: Include email-based intelligence in reports

---

### 🧪 Testing Strategy

#### Unit Tests
- Email parsing (various formats)
- Content cleaning
- Entity extraction
- API client functionality

#### Integration Tests
- End-to-end email retrieval
- Processing pipeline
- Database operations
- API endpoints

#### Manual Testing
- Various email providers (Gmail, Outlook, etc.)
- Different newsletter services
- Edge cases (large attachments, malformed emails)
- Performance testing with large volumes

---

### 📚 Documentation Requirements

1. **User Guide**: How to set up and use email intelligence
2. **Administrator Guide**: Configuration and management
3. **Developer Guide**: Architecture and extension points
4. **API Documentation**: Complete API reference
5. **Security Guide**: Best practices for secure usage

---

### 🚀 Next Steps

1. **Review this plan** and provide feedback
2. **Prioritize features** based on immediate needs
3. **Assign team members** to different components
4. **Set up development environment** for the new branch
5. **Begin implementation** with Phase 1

---

### 📞 Support & Resources

- **Questions**: Open issues in the repository
- **Discussions**: Use GitHub Discussions for architecture questions
- **Documentation**: Update as implementation progresses
- **Examples**: Create example configurations and usage patterns

---

*Last Updated: $(date)*
*Status: Planning Phase*


---

## Worldwide source catalog — strategy & runbook

Goal: cover the news media **and** official political institutions of **every
country**, so the corpus approximates a genuine digital world view. Social
networks are out of scope for now. The guiding constraint is the project's: the
list must be **real, attributable and refreshable**, not guessed.

### Why data-derived (not hand-typed)

Hand-typing thousands of domains produces wrong/dead entries and can never reach
true global completeness. Instead the catalog is **generated from Wikidata**
(CC0, machine-readable), which has, per entity: an *official website* (P856), a
*country* (P17 / ISO code P297) and a *language* (P407). That's an honest,
attributable backbone we can regenerate on demand and audit.

### How it works

```
configs/catalog_query.yml      # which Wikidata TYPES count as a source (editable)
        │
        ▼
scripts/build_world_news_catalog.py   # queries Wikidata per country (needs network)
        │   • src/catalog/wikidata.py   build per-country SPARQL (keyed on ISO P297)
        │   • src/catalog/normalize.py  registrable domain · drop social hosts · dedup
        │   • src/catalog/build.py      orchestrate · resilient per-country · emit YAML
        ▼
configs/world_news_sources.yml  # generated catalog (seeder picks it up automatically)
        │
        ▼
seed_default_sources()          # merges it with sources.yml + markets_sources.yml,
                                # deduping by domain → the unified store
```

The pure logic (query building, parsing, normalisation, dedup, coverage) is
unit-tested with fixtures and runs anywhere. Only the *fetch* needs network, so it
lives in the CLI — run it on a networked machine/CI; the app sandbox may be egress
restricted.

### Running it

```bash
## Full run (all ISO countries × the configured source types):
python scripts/build_world_news_catalog.py

## A subset while iterating, or a dry run (prints stats, writes nothing):
python scripts/build_world_news_catalog.py --countries fr,jp,ke,br --dry-run
python scripts/build_world_news_catalog.py --source-types news

## Fold in an external export (GDELT / Media Cloud) — a CSV with a url/domain
## column plus optional name/country/language:
python scripts/build_world_news_catalog.py --merge-csv mediacloud_sources.csv
```

It excludes social networks and any domain already shipped in `configs/sources.yml`
or `configs/markets_sources.yml`, then writes `configs/world_news_sources.yml` and
prints a country-coverage summary. Be polite: `--delay` (default 1s) spaces out
Wikidata queries.

### Scale: reaching tens of thousands of sources (target ~50,000+)

The ambition is **at least ~50,000 sources, several dozen per country**. The honest
way there is *generation*, not typing:

- **Wikidata is the engine.** `configs/catalog_query.yml` now runs **~249 countries
  × broad media types** at `limit: 5000` each. Wikidata lists official websites for
  far more outlets than any hand-list could — a full run realistically yields tens
  of thousands of real, attributable, per-country, de-duplicated entries. **Run it
  on a networked machine/CI** (the app sandbox is often egress-restricted) and the
  seeder picks up the result automatically.
- **Fold in open datasets** with `--merge-csv` (e.g. a GDELT or Media Cloud export
  of domains) to push coverage further — still real, attributable URLs.
- **What we will NOT do:** fabricate ~48k plausible-but-dead RSS URLs. That would
  poison the corpus and break the project's core promise (*nothing is guessed*). A
  smaller real catalog beats a huge fake one. The number grows by running the
  generator, not by inventing rows.

### Political-spectrum catalog (`configs/sources_spectrum.yml`)

Wikidata gives breadth but has **no editorial leaning**. So a hand-curated companion
catalog ships ~280 real, well-known outlets across ~95 countries and ~30 languages,
each tagged with:

- a **leaning** (`lean-left`, `lean-center-left`, `lean-center`, `lean-center-right`,
  `lean-right`) — *reputational and contestable*, drawn from widely-cited media-bias
  assessments and each outlet's stance; **or**
- an **ownership** tag (`public-broadcaster`, `state-media`, `wire-agency`) where that
  matters more than slant — so a truth-seeker can weigh provenance (e.g. RT, Xinhua,
  Press TV are tagged `state-media`, not "news" alone);
- plus **topic keywords** (`business`, `investigative`, `tabloid`, `analysis`, …).

These tags are deliberately namespaced and easy to filter (Scheduler "tags"
targeting, Sources filters) and easy to **override** — leaning is an editorial
judgement, offered as a starting point, not a verdict. The file is merged at seed
time, de-duped by domain against the other catalogs.

### Tuning what counts as a source

Edit `configs/catalog_query.yml`. Each spec is a `source_type` + a list of
Wikidata **type item-ids** (subtypes are included automatically). The news ids are
well-established; **verify the institution ids** on <https://www.wikidata.org> for
your needs before a full run — a wrong id simply returns fewer rows, never fake
data. To add a concept: search it on Wikidata, copy its `Q…` id into a spec.

### Augmenting beyond Wikidata

Wikidata misses some small/local outlets. Comparable open sources to fold in via
`--merge-csv`:

- **GDELT** monitored-domain lists — <https://www.gdeltproject.org/>
- **Media Cloud** country source collections — <https://www.mediacloud.org/>
- Any institutional registry you trust, exported to CSV.

### Measuring progress

`GET /api/database/coverage` (and the **Sources & Database → World coverage**
panel) report covered vs total countries, the **missing** country codes, and the
**thin** ones (covered but with very few sources) — computed from the data. Use
the missing/thin lists to target the next generation run (`--countries …`).

### Ethics

Same rules as all ingestion: only public data, robots.txt respected (fail-closed)
and rate-limited at fetch time. The catalog stores only metadata (name, domain,
country, language); nothing is fetched until an ingest runs.


---

## Known gaps — the coverage ledger

> The mission is "understand the world as it really is." A tool that takes that
> seriously must be honest about **what it does not see**. This ledger names our
> blind spots and labels each one **voluntary** (a deliberate scope / ethics /
> resource choice) or **involuntary** (a limit we don't fully control — or don't
> yet measure). Turning unknown unknowns into *known* unknowns is the point.
>
> A smaller corpus whose gaps are documented is more trustworthy than a huge one
> whose biases are hidden. The count of sources is a vanity metric; **this page is
> the real one.**

---

### How to read this

- **Voluntary** = we chose to exclude it. The right response is to *state it*, not
  hide it. Reversible if priorities change.
- **Involuntary** = we can't fully capture it (medium, access, language, or the
  limits of the registries we enumerate from). The right response is to *measure
  its size* so the user can weigh it.

Where a rule is enforced in code, the location is cited so the claim is auditable.

---

### Voluntary exclusions (deliberate)

#### Images & all visual/binary media — *excluded by design*
**We do not collect, download, store, or analyse images, video, or audio.** Only
**text and structured metadata** are ingested. A record may reference an image
*URL* (a short string), but the binary is never fetched or stored.

- **Why (owner's decision):** (1) **storage** — this is a single-user, offline-first
  tool that must fit on one machine the owner can afford; media binaries would
  balloon the database. (2) **Honesty at scale** — credible image work (provenance,
  manipulation/deepfake detection, reverse search) is *not feasible to do well at
  scale here*, and a half-working "image analysis" feature would violate the
  project's core promise (nothing faked, nothing guessed). Better to not pretend.
- **Enforced today:** the crawler skips image/audio/video/binary extensions —
  `_SKIP_SUFFIXES` in `src/ingest/crawl.py` (`.jpg .jpeg .png .gif .svg .webp .ico
  .mp3 .mp4 .avi .mov …`). RSS/article extraction keeps text; any `og:image` is at
  most a URL string, never a download.
- **If ever wanted:** image handling would be a deliberate, clearly-bounded
  **opt-in** (with its own storage budget), never a silent default.

#### Social media & messaging platforms — *excluded for now*
X/Twitter, Facebook/Instagram/Threads, TikTok, YouTube, Reddit, Telegram,
WhatsApp, etc. are dropped. Enforced: `SOCIAL_HOSTS` in `src/catalog/normalize.py`.
Rationale: ToS/scraping friction, ethics, and signal-to-noise. *Cost to note:* a
lot of breaking news and primary-source material now originates there.

#### Paywalled content — *respected, not bypassed*
We do not defeat paywalls or logins. Some major outlets are therefore captured
only by headline/teaser, not full text.

#### robots.txt-disallowed paths — *fail-closed*
If a site disallows crawling, we don't fetch it (per `ETHICS.md`). A deliberate
trade of coverage for legitimacy.

#### Broadcast audio/video & print-only outlets — *out of scope*
No speech-to-text of TV/radio; outlets with no web presence can't be reached at
all. (Overlaps the images/media exclusion above.)

---

### Involuntary gaps (blind spots we should *measure*)

- **Register-bounded enumeration.** We can only seed what some registry lists.
  Wikidata (our generator's backbone) skews Western/English/large-language, so the
  catalog inherits that skew. We can't miss what no register names.
- **Language & script under-coverage.** Smaller languages and non-Latin scripts are
  thinner — both in the registries and in RSS availability.
- **Censored / exile media.** In repressive environments the real reporting may live
  only on blocked, exiled, or social/messaging channels we exclude.
- **The unknown unknowns.** Sources that appear in *none* of the registries we use.

#### How we plan to size the gap (roadmap)
Honest measurement, not a bigger number:
1. **Triangulate registries** — cross-reference Wikidata against GDELT / Media Cloud
   / national press directories / MBFC / AllSides; the *non-overlap* is the gap.
   Tag each source with the register that found it (provenance). ✅ *first step done:*
   the seeder now records provenance as a `via:<curated|spectrum|markets|wikidata>`
   tag (`src/ingest/seed_sources.py`).
2. **Capture–recapture estimate** — if register A has Nₐ, B has N_b, overlapping in
   N_ab, estimated total (incl. never-seen) ≈ Nₐ·N_b / N_ab. This estimates the dark
   matter: "we hold Y; estimated unseen ≈ Z." *(planned.)*
3. **Real denominators** — replace the current "country has ≥1 source = covered"
   measure (`src/catalog/coverage.py`) with coverage *ratios* per country ×
   language × medium × political lean, and surface them in the World-coverage view.
   ✅ *first step done:* **ccTLD inference** (`src/catalog/cctld.py`) backfills missing
   `country`/`language` at seed time (conservative — generic/ambiguous ccTLDs stay
   unknown), lifting country-tagged coverage from ~19% → ~33% so the skew is finally
   *visible*. The remaining unknowns are honestly unknown (mostly `.com`).

---

### Status at a glance

| Gap | Type | Enforced in code? |
|---|---|---|
| Images / video / audio / binaries | Voluntary | ✅ `crawl.py` `_SKIP_SUFFIXES` |
| Social media & messaging | Voluntary | ✅ `normalize.py` `SOCIAL_HOSTS` |
| Paywalls | Voluntary | ✅ fetcher respects them |
| robots.txt-disallowed | Voluntary | ✅ fail-closed fetcher |
| Print-only / broadcast | Voluntary | ✅ (nothing fetches them) |
| Register skew / languages | Involuntary | ⏳ measurement planned |
| Unknown unknowns | Involuntary | ⏳ capture–recapture planned |

*This is a living document. When scope changes, update the ledger in the same
commit — the limits ship with the product.*


---

## Open Questions & Design Notes (for the next work session)

> **Read me first if you're picking this project back up.** This file captures
> in-flight design discussions and decisions that were *not* finalised before a
> session ended, so the thinking isn't lost. Each item states the goal, my current
> understanding, the open questions, and (where useful) a proposed direction —
> clearly marked as a proposal, not a decision. Resolve an item → fold it into the
> real docs and delete it from here.

Last updated: 2026-06-07.

---

### 1. Chain of custody: make it dummy-proof, and automate it into the background

**This is the big one.** Status: **discussed, not yet designed or built.**

#### What the user asked for (paraphrased, preserve the intent)

The **Chain of custody** tab is currently expert-facing. The user wants two things:

1. **Make it understandable and dummy-proof for novices.** *Why* chain of custody
   exists and *how* to use it should be obvious from the interface — either
   self-evident or interface-guided (onboarding, plain-language explanations,
   guided flow), not requiring the user to read `USER_MANUAL.md`.

2. **Automate it / move it to the background.** The framing the user gave:
   *"Investigative journalists don't want to tamper with the boring stuff; they
   want their sources to be automatically trustworthy. This app and its database
   could become 'the' trustworthy source — but only if chain of custody is
   guaranteed, automated, and in the background."*

In other words: chain of custody should become an **always-on guarantee of the
corpus**, not an optional panel the user has to operate. The aspiration is that
"it's in Open Omniscience" comes to *mean* "its provenance and integrity are
cryptographically established."

#### My current understanding of the goal

- Every ingested item should be **automatically** entered into the signed,
  hash-chained custody log at capture time — no manual step.
- The UI should mostly **report a reassuring, plain-language trust status**
  ("✓ All 12,431 items in this corpus are signed and tamper-evident") rather than
  expose knobs. Advanced controls move into an "Advanced" disclosure.
- Verification, anchoring, and export stay available but become secondary.

#### The real tension to resolve (important — don't just bulldoze it)

The existing design made some of this **deliberately opt-in for honest reasons**,
documented in `docs/USER_MANUAL.md`:

- **Auto-log on ingest is off by default** because each entry has a real
  **per-article signing cost**, and turning it on is framed as "an explicit
  evidentiary choice, not silent always-on behaviour." It is also **fail-open** (a
  custody error never breaks ingestion).
- The doc explicitly lists **"no always-on background integrity daemon"** under
  *"What we deliberately did not build."*

So "automate it / always-on background" **directly revisits two prior deliberate
decisions.** That's allowed — the product vision may have moved — but the next
session should reconcile this consciously, not silently contradict the doc. The
honesty invariant ("never show a trust light you can't back up") must survive any
redesign: an automated green "everything is signed" badge must be *true*, including
through restores, imports, and partial/failed signings.

#### Open questions for the user (answer these next session)

1. **Default on?** Should auto-log-on-ingest become the **default** for new
   installs (a setup choice during `install.sh` / first run), or stay opt-in but
   far more prominent and one-click?
2. **Performance budget.** Signing every item costs CPU/time at ingest. Is a small
   per-article cost acceptable always-on, or do we want **batched/Merkle-tree
   signing** (sign a batch root per scheduler run) to keep it cheap? Batching
   changes the granularity of the proof — acceptable?
3. **What exactly is "guaranteed"?** Integrity + provenance + local time are cheap
   and local. Independent *time* proof needs **OpenTimestamps (network egress,
   privacy trade-off)**. Should the "trustworthy" guarantee include third-party
   time by default, or is local-time-by-default fine with OTS as an opt-in upgrade?
   (Note the privacy warning: OTS reveals IP/timing.)
4. **Imports & restores.** A restored or CSV-imported corpus didn't come through
   *our* ethical fetch path. How should the trust badge represent items whose
   custody starts at import rather than original capture? (Proposal: an honest
   "imported, integrity-from-here" provenance class — never claim original capture
   we didn't witness.)
5. **Novice UI shape.** Is the desired end-state a single **trust banner + "verify
   this corpus" button**, with everything else behind "Advanced"? Or a short guided
   wizard the first time?
6. **Scope of "source."** Reconfirm: in this tool a "source" is a *news outlet*,
   not a confidential human source. The trust claim is about *our record of public
   material*, not source protection. Keep messaging from over-promising.

#### Proposed direction (NOT yet approved — a starting point)

- Flip the mental model: custody is a **property of the corpus**, surfaced as a
  calm trust status, with the panel's knobs demoted to "Advanced."
- Default new installs to **auto-log on ingest = on**, using **per-scheduler-run
  batched Merkle signing** to keep the cost negligible, with local time by default
  and OpenTimestamps offered as a clearly-explained, privacy-warned upgrade.
- Add **first-run onboarding copy** on the tab: a one-paragraph "what this is and
  why it matters to a journalist," a live trust badge, and a single **"Verify
  entire corpus"** action.
- Represent imported/restored items with an **honest, distinct provenance class**
  so the badge never overclaims.
- Update `docs/USER_MANUAL.md` to record the reversal of the "no always-on
  daemon / opt-in only" stance *with its rationale*, preserving the honesty
  invariants.

**Before building:** get the user's answers to Q1–Q6 above (use `AskUserQuestion`),
because several touch deliberate prior decisions and a performance/privacy budget.

---

### 2. Language pickers grouped by continent — done for Wikipedia; note on the rest

**Status: largely done.** The user asked to sort *all* language pickers (article
languages, Wikipedia languages, etc.) **by continent** to ease scrolling long
lists, then to **add type-to-filter search** and **more editions**.

- **Done:** the **Wikipedia offline-baseline picker** (the only real `<select>` of
  languages) is now grouped into `<optgroup>`s by continent of origin
  (`src/wiki/languages.py` gained a `region` field + `languages_by_region()`;
  `/api/wiki/languages` returns a `groups` form; the UI renders optgroups). The
  curated catalogue was expanded to **~147 editions** covering all continents
  (incl. Americas/Oceania and a "Constructed" bucket for Esperanto et al.), and the
  picker gained a **type-to-filter box** (matches name, autonym or code) rendered as
  a list box.
- **Deferred (needs a decision):** a *fully dynamic* list of **all 300+ Wikimedia
  editions** pulled live from the dump server / sitematrix. Not done because it adds
  **runtime network egress**, which conflicts with the offline-first default — the
  ~147 curated editions plus the always-available free-text code entry already reach
  any edition. Revisit if comprehensive auto-discovery is wanted despite the egress.
- **Open:** the other "language" inputs — **Search → Language** (`f-lang`),
  **Sources → Language** filter (`src-language`), and **Ingest/scheduler →
  Languages** (`sch-langs`) — are currently **free-text inputs, not dropdowns**, so
  there's no list to group. 

  **Question for the user:** do you want those converted into proper
  continent-grouped dropdowns too (populated from the same region-aware catalogue)?
  That's a reasonable follow-up but it's a behavioural change (free text → picker)
  and the scheduler field accepts multiple comma-separated codes, so it'd need a
  multi-select. Left as-is pending confirmation.

---

### How to use this file

- Add an entry whenever a session ends with an unresolved design decision.
- Keep entries action-oriented: **Goal → Understanding → Open questions →
  Proposal**.
- When resolved, migrate the outcome into the canonical docs and remove the entry.


---

<!-- Merged from docs/NEXT_VERSION.md in the v0.0.7 audit (doc consolidation):
     one strategic-planning doc instead of two overlapping ones. -->

## Next version — action plans for Themes 2–5

> **North star.** The app is `0.0.6` pre-alpha with strong foundations and **no
> real-world validation**. The next version does not chase "more features"; it earns the
> right to be *seen and safely used* by the people who most need it — investigative
> journalists, including those at risk — on the road to a defensible `0.1` public alpha.
> The themes below are **safety, usability, sense-making, and governance**. Each plan is
> phased; the **first increment of each ships in this branch** and is marked ✅ below.
>
> **Discipline that constrains every plan:** local-first (no server, no accounts, no
> telemetry); surface signals, never verdicts; **never ship fake security** — a feature
> that *claims* a protection it does not deliver is worse than its absence; and hold the
> dual-use red lines in [GOVERNANCE.md](GOVERNANCE.md).

---

## Theme 2 — At-risk-user safety

**Why.** An investigative journalist may work under surveillance, face device seizure,
or endanger a source merely by *announcing interest* in a target. The same architecture
that makes the app private (local-first) must be extended so that **the data at rest,
the data in transit, and the act of researching itself** can be protected — honestly,
with each guarantee and its *limits* stated plainly.

**The honest-crypto rule.** Every protection reuses audited primitives (the
`cryptography` AES-256-GCM + scrypt scheme already used for custody keys) and is
labelled with exactly what it does and does **not** guarantee. We never imply anonymity
or at-rest secrecy we cannot deliver. Full-disk encryption remains the host's job
(Qubes/LUKS/Tails); we add *application-level* protections on top, not instead.

### Phase 1 (✅ ships now)
- ✅ **Encrypted, portable backup.** Export the whole corpus as a single
  passphrase-encrypted file (AES-256-GCM, scrypt-derived key); restore by passphrase.
  A wrong passphrase fails loudly; the format self-describes its KDF params. *Use:* carry
  or stash the corpus across a border or a hostile network without exposing it.
- ✅ **Panic wipe.** A deliberate, confirmed action (`open-omniscience panic --yes`, and a
  guarded GUI control) that best-effort-overwrites then deletes the data dir (DB, keys,
  caches), honestly noting that on SSDs/CoW filesystems only full-disk encryption
  guarantees unrecoverability.
- ✅ **Ephemeral mode.** `OO_EPHEMERAL=1` / `--ephemeral` runs against a throwaway temp
  data dir that is wiped on exit — nothing persists. *Use:* a quick, leave-no-trace look.
- ✅ **Protected fetch.** A per-app *fetch mode*: **Transparent** (default — identifying
  UA, robots fail-closed, for broad ethical collection) vs **Protected** (route through a
  user-supplied proxy, e.g. Tor at `socks5://127.0.0.1:9050`, and send a generic UA), so a
  journalist investigating a powerful target need not announce themselves from their real
  IP. The UI states the tradeoff honestly: we *use* your proxy and *verify it is set*; we
  **cannot** guarantee anonymity — you must run and trust the proxy yourself.

### Phase 2 (planned)
- **Encrypted-at-rest live DB** (SQLCipher or equivalent) behind a session passphrase,
  only if it can be done without a fragile native dependency and *honestly* audited.
- **Decoy / hidden-volume** and **duress-passphrase** patterns — *only* if they can be
  made genuinely sound (these are easy to get dangerously wrong; default to "don't ship
  unless provably correct").
- **First-class Tails / Qubes-Whonix integration** (Tor-routed Protected mode by default
  in those environments), with a hardened distribution profile.
- **Auto-lock / inactivity wipe of in-memory secrets.**

**Non-goals / red lines.** No silent network egress; no cloud backup; no telemetry; no
claim of anonymity. Protected mode is opt-in and never the silent default (announcing a
bot is the *ethical* default for general collection).

**Risks & self-criticism.** Crypto/anonymity are easy to get subtly wrong, and false
assurance endangers the very users we mean to protect. Mitigation: reuse audited
primitives, label limits, keep Phase-2 deniability features behind a high "provably
correct" bar, and seek an external review before the `0.1` alpha.

---

## Theme 3 — Usability, accessibility & onboarding

**Why.** An accountability tool that only experts can install, or that excludes disabled
journalists, fails its own values. Reach matters: the audience is global and non-technical.

### Phase 1 (✅ ships now)
- ✅ **Accessibility pass on the GUI:** a skip-to-content link; ARIA landmarks
  (`navigation`/`main`/`complementary`); `aria-label`s on icon-only buttons; `aria-current`
  on the active nav; an `aria-live` region for toasts; visible focus rings; and
  `prefers-reduced-motion` support. (Static a11y; a full screen-reader audit is Phase 2.)
- ✅ **Gentler first-run / empty states:** the briefing, search and library empty states
  now *teach* — one clear next action ("Seed sources & run a first ingestion") and a plain
  explanation of what will happen, so a new user is never staring at a blank panel.
- ✅ **i18n completeness report** (`scripts/i18n_report.py`) so translators can see exactly
  which strings each locale is missing; new Safety/Lineage chrome strings added to the
  maintained locales (en/de/es/fr).

### Phase 2 (planned)
- **One-click packaging** for non-technical users (AppImage/Flatpak) — clearly *separate*
  from the hardened Qubes build, with the security tradeoff documented (convenience ≠
  maximum safety).
- **Full screen-reader + contrast audit** against WCAG 2.1 AA; keyboard-only end-to-end.
- **Finish the stub locales** (ar, zh, ru, ja, hi, bn, pt, id) with reviewed translations,
  including RTL polish for Arabic.
- **Guided tours / contextual help** for the analytical tabs.

**Risks & self-criticism.** Packaging-for-everyone pulls against the Qubes security
center; the resolution is *two clearly-labelled distributions*, not one muddled compromise.
I cannot verify screen-reader behaviour from here, so Phase 1 is honest static a11y, not a
claim of full accessibility.

---

## Theme 4 — Content sense-making & the publishing loop

**Why.** The honest "more useful" is **not** more detectors. It is: help users get *good
coverage in*, make *sense* of it, and get *publishable, verifiable journalism out* — all
in the structural/measurable lane, never as verdicts.

### Phase 1 (✅ ships now)
- ✅ **Story lineage ("trace to the primal source").** For a near-duplicate cluster, order
  by earliest publication, detect **wire attribution** ("according to Reuters/AFP/AP/…",
  "Reuters reported") and explicit citations, and present **primary → first report →
  echoes** as a chain. A briefing **Story-lineage** card surfaces it. Honest caveat:
  *"earliest we saw" ≠ the truth*; it shows lineage and structure, the human judges.
- ✅ **Coverage advisor.** A gentle, dismissible **Diet imbalance** signal: when recent
  collection (or a result set) is dominated by one owner/country/language, surface the
  concentration *with* a few concrete under-represented sources from the catalog to
  consider — *suggestive, explained, overridable; never enforced* (§3 of the design memory).

### Phase 2 (planned)
- **Publish-ready bundle:** the card→draft→Markdown export, plus an attached **signed
  evidence bundle** of every cited article and the relevant annotation bundle — so an issue
  ships *with* its reproducible receipts.
- **Cross-language divergence** and **deal-lineage** cards (existing engines, new framing).
- **Reading ergonomics:** a calmer, faster triage/reading flow for the briefing.

**Risks & self-criticism.** Lineage is genuinely hard (event-clustering + citation tracing);
Phase 1 starts with the cheap, honest signals (wire/near-dup/earliest-timestamp) and says so,
rather than over-claiming "the original source". I must keep "more useful" from smuggling in
unreliable AI fact-checking — the project's refusal to fake detection is its integrity.

---

## Theme 5 — Governance & acceptable use

**Why.** If the app gets popular it becomes a target and a dual-use risk. A short, public
statement of *what it is for*, the *red lines*, and the *governance intent* is cheap and
disproportionately protective — and is itself an ethical act.

### Phase 1 (✅ ships now)
- ✅ **[GOVERNANCE.md](GOVERNANCE.md)** — the statement of purpose, the **dual-use red
  lines** (no individual-person tracking / face-voice recognition / private-message
  ingestion / automated trust score / central server / silent filtering — *absent by
  construction, not configurable*), the legal/ethical posture, funding-independence intent,
  and a misuse-resistance note. Registered in the in-app docs reader.
- ✅ **Red-lines guard test** — a CI test asserting the forbidden capabilities are absent
  from the codebase (no face/voice-recognition or individual-tracking modules), turning the
  promise into an enforced invariant alongside the existing no-trust-score guard.

### Phase 2 (planned)
- **Independent governance** (multi-maintainer, transparent decisions) before any funding.
- **An external security & ethics review** ahead of the `0.1` public alpha.
- **A clear contribution covenant** aligning contributors with the red lines.

**Risks & self-criticism.** A red-lines test can only check for *known* forbidden patterns;
it is a tripwire, not a proof. The real guarantee is culture + review. Stated plainly so no
one mistakes the test for completeness.

---

## Sequencing & what ships in this increment

This branch delivers **Phase 1 of all four themes** — a coherent foundation, each piece
tested and honestly labelled — without over-claiming any theme as "done". The phased
remainder, the validation pilot (Theme 0 from the strategy memo), and the external audit
are the path to the `0.1` alpha. Nothing here weakens the existing guarantees; everything
new is opt-in, reversible, and stated with its limits.
