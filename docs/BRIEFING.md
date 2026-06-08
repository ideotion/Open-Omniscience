# The Home briefing — intelligence as honest "cards"

> **Status:** `0.06` Phase A (the GUI spine) — shipped and tested. The phased plan
> lives in [`ACTION_PLAN.md` → "0.06 — The Intelligence Layer"](ACTION_PLAN.md); the
> *what & why* in [`FUTURE_DEVELOPMENTS.md`](FUTURE_DEVELOPMENTS.md).

The **Home** tab is no longer just at-a-glance stats. It is a **triage feed**: the
app gathers and measures in the background, then surfaces *candidate stories* as
**cards**. The app does the gathering; **you judge**. Each card is **one measurable
signal + the evidence links + a caveat**, sorted into an editorial bucket.

A card **surfaces a signal; it never renders a verdict.** There is no "biased", no
"propaganda", no "true/fake", and — by design and *enforced in code* — **no composite
trust score** (see "Honesty guards" below).

---

## What you see

The briefing groups cards into **buckets** (display order):

| Bucket | Means | Editorial use |
|---|---|---|
| **Rising now** | something is moving / new | lead candidates |
| **Overtold** | sources agree too fast / too uniformly | debunk the chorus |
| **Undertold** | something moved but little/nobody covered it | surface the gap |
| **Worth investigating** | sources or data disagree | dig in |
| **Check the framing** | the same event framed in opposing ways | verify the claim |
| **Keep watching** | a change worth an eye (e.g. a reshaped record) | monitor |
| **Context** | background / self-audit / standing facts | contextualise |
| **Data integrity** | hygiene signals about the corpus itself | fix the pipeline |

The triad behind them is the engine: **convergence → overtold**, **divergence →
investigate/debunk**, **absence → undertold**.

Every card shows its **title**, a one-line **summary**, the **measured signal**
(e.g. `growth_ratio = 4.2`, `n=6`), and **evidence links** back into your corpus.
Toggle **"Show method & caveat"** to reveal, on every card, exactly how the figure
was computed and what it does *not* mean. That toggle is the point: **transparency is
the interface.**

> **Equal view.** In this version every source is counted once and **no source is
> de-amplified**. The source-integrity / anti-amplification layer (collapsing
> coordinated floods into single actors, novelty-weighting) is the next phase and is
> **user-guided** — the app will *propose*, you will *dispose*. Until then the
> briefing is, honestly, the raw equal-treatment view.

---

## The card → draft → newsletter loop

The payoff loop is visible from day one:

1. On any card, click **+ Add to draft**.
2. Open the **Newsletter draft** panel; add your own note to each pinned card.
3. **Export Markdown** (or **Copy**). Each claim ships **with its source links,
   method and caveat** — reproducible journalism by design.

For a *signed, tamper-evident* copy of the underlying articles, export an **evidence
bundle** from **Evidence & custody** — the receipts can ship with your issue.

---

## How the cards are produced (Briefing v0)

Each card is made by a **producer**: a function `corpus → [Card]`. Producers compose
analytics that *already return real numbers* — nothing is invented. A producer that
lacks its inputs or an optional `[analysis]` dependency **returns nothing and logs
why** (loud degradation); it never fabricates a card.

| Card | Bucket | Powered by | Status |
|---|---|---|---|
| **“X” is rising** | rising | `insights.trending` (recent vs prior-period ratio) | now |
| **Framing split** | check the framing | per-source VADER tone of a trending term | now¹ |
| **Record reshaped** | keep watching | Wikipedia large/flagged-edit detection | now |
| **Price ↔ narrative** | context | honest scipy correlation (coef + p + n) | now¹ |
| **Stale data** | data integrity | market extraction-rule `last_run_at` / `last_status` | now |
| **Diet self-audit** | context | `signals.concentration` (Gini + top-3 share over your sources) | now |
| **Echo chamber** | overtold | `signals.coordination` actor graph (near-dup + timing + host) | new |
| **Lonely signal** | undertold | single-source near-dup cluster that did not echo | new |
| **Capacity implausible** | investigate | articles/day vs corpus median | new |
| **Emotion profile** | context | emotion lexicon over a keyword's context windows | new² |
| **IP / legal pulse** | context | rising IP/legal terms in the news corpus | thin |
| **Ownership change** | investigate | deal-verb language (acquired/merger/divested) in recent news | thin |

¹ Needs the `[analysis]` extra (VADER / scipy). Without it those cards simply don't
appear — the rest of the briefing still works.
² Uses an emotion lexicon; a minimal English **sample** ships, point
`OO_EMOTION_LEXICON` at a fuller JSON lexicon for serious use (English-only).

The **echo-chamber**, **lonely-signal** and **capacity-implausible** cards come from the
source-integrity layer — see [`INTEGRITY.md`](INTEGRITY.md). Echo-chamber cards carry a
*Collapse to one actor* action (user-guided anti-amplification — propose → you dispose).

The **Diet self-audit** uses the first pure primitive of the shared
[`src/signals/`](../src/signals/) substrate: **concentration** (Gini coefficient +
top-N share). It is the *same maths* intended for media-ownership concentration
(FUTURE_DEVELOPMENTS §1) and people-prominence (§4) — one engine, many domains.

---

## Performance — precompute, cache, serve cached

The briefing **never computes per request**. The background scheduler refreshes it
after each scrape and writes a cache (`briefing_cache.json` under your data dir);
Home reads the cache and loads instantly. **Refresh** recomputes on demand. Dismissals
(`briefing_dismissed.json`) and the draft (`briefing_draft.json`) are small local JSON
files — single-user, local-first, never transmitted.

---

## Honesty guards (in code, not just docs)

FUTURE_DEVELOPMENTS §6 forbids a single automated trust/quality score (it bakes the
scorer's worldview into a false-objective number and *will* misclassify small, foreign,
new or dissident sources). That ban is enforced **mechanically**:

- `src/briefing/card.py:assert_no_score_fields()` rejects any `Card` field whose name
  implies a composite score (`score`, `trust_score`, `credibility`, `rating`,
  `verdict`, …). It runs at import and a test asserts it holds.
- The numeric a card carries lives in `signal` as **one measured quantity with a
  stated method** — a growth ratio, a Gini value, a correlation coefficient — never a
  blended score over incommensurable dimensions.
- **Surface, don't suppress.** Dismissal is reversible; any future down-weighting will
  be transparent, tunable, off by default, and reversible.

---

## API

All under `/api/briefing` (loopback only, like the rest of the app):

| Method & path | Purpose |
|---|---|
| `GET /api/briefing` | the cached feed, grouped by bucket (`?force=true` to recompute) |
| `POST /api/briefing/refresh` | recompute now |
| `POST /api/briefing/dismiss` · `/restore` · `/dismissed/clear` | manage dismissals |
| `GET /api/briefing/draft` | the current draft (pinned cards + notes + title) |
| `POST /api/briefing/draft/add` · `DELETE /api/briefing/draft/{id}` | pin / unpin a card |
| `PUT /api/briefing/draft/note` · `/title` · `POST /draft/clear` | edit the draft |
| `GET /api/briefing/draft/export.md` | the evidence-carrying Markdown |

---

## Roadmap (status)

Phases A–D are shipped: the card+briefing spine (A), the full `src/signals/` substrate
— concentration, near-dup/coordination, novelty (B), the source-integrity profile +
user-guided anti-amplification (C, see [`INTEGRITY.md`](INTEGRITY.md)), and crowdsourced
signed annotation bundles (D, see [`ANNOTATIONS.md`](ANNOTATIONS.md)). Phase E ships the
composable verticals as cards (emotion, IP/legal news); the **law / IP primary-source
change-tracking verticals** (ingesting `legislation.gov.uk`, EUR-Lex, patents/dockets)
remain the documented next step — they reuse the existing change-tracking and
near-dup/correlation engines but require live external sources. See
[`ACTION_PLAN.md`](ACTION_PLAN.md) Phases B–E.
