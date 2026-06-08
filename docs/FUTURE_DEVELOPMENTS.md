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
**user-driven selection, no capping.**
