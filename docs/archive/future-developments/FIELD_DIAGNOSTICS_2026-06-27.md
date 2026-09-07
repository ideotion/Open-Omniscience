> **Archived 2026-09-07 from `docs/FUTURE_DEVELOPMENTS.md`, verbatim and unedited.** It is an embedded
> HISTORICAL LEDGER — measured findings from a ~2,259-article live scrape — and it was displacing the design-intent material that document exists
> for. Nothing was condensed or dropped in the move. Its still-open items live on the live boards
> (`CLAUDE.md`'s Open queue and `docs/ROADMAP.md`); read this file as a record of what was observed and
> when, not as a status.

## Field diagnostics 2026-06-27 — measured findings & actionable items (a ~2,259-article live scrape)

> Captured from the maintainer's diagnostic exports (self-test, growth, engine-report, scaling-benchmark,
> performance-report, home-cards, date-diagnostics, debug-bundle) on a live corpus of **2,259 articles /
> 99,662 keywords / 179,395 mentions / 3,177 sources**, DB **103 MB**, **2-core / 4.4 GB Qubes VM**,
> SQLCipher-encrypted, columnar engine **in-memory (D1 unavailable)**. **Headline: the keyword ENGINE is
> healthy** (self-test 42/42; extraction noise 0.5%; Heaps β=0.756 = healthy saturation). The findings
> below are **contention, scale, and one card bug** — recorded here for later implementation. Counts +
> milliseconds only, never a score.

### F1 — BUG (shippable): 6 Home cards LOSE their corpus on click ("no hard-linking")
The card-click diagnostic shows **6 of 25 cards "mismatched":** clicking runs a text search on a
**synthetic seed** that matches **0 articles** though the card is about N — "the exact corpus is LOST."
The four producers that **don't carry `article_ids`:** **`lonely_signal`** (seed = a truncated title →
0), **`ownership_change`** (seed `"ownership-change"` → 0, card n=4), **`recipe_promise`** (seed
`"2294:2026-06-27"` → 0, ×3), **`story_lineage`** (seed `"lineage:1575"` → 0, card n=3). **Fix
(established pattern):** have each producer carry its exact `article_ids` so the click uses
`openAnalysisForIds` (already done for echo_chamber / source_laundering / space_time_convergence /
headline_body_mismatch, which are all hard-linked). **Acceptance:** the home-cards diagnostic reports **0
mismatched.** Backend + producer change; testable. *(A genuine bug, not a design idea — prioritise.)*

### F2 — PERF: live validation of the keyword-engine strategy (record the baseline; build in the strategy)
Two measured problems, both already addressed by `docs/design/KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md` —
the numbers here **validate + unblock** that work, they don't need a new plan:
- **Writer-gate SATURATED during the scrape (validates + UNBLOCKS the deferred COLLECTOR-path
  batching).** `collect_perf`: `adjust_reason:"writer-saturated"`, **34 fetch workers queued** behind the
  one encrypted writer, **max_wait 210 s** for a single write, total_wait 6,716 s, contended 2,127, and
  the scrape **throttled to 161 kbps vs a 500 target** — *write-bound, not network-bound* (the next
  sample hit 1,481 kbps). The `CLAUDE.md` ledger deferred the full COLLECTOR-path write-batching
  "pending a live measurement" — **this IS that measurement.** → build strategy **P1.3** (batched commits
  via the `index_article(commit=False)` primitive + the `COLLECTOR_WRITER_BATCHING` store_fetched
  restructure).
- **Analytics "freeze" at only 2,259 articles** (NOT a big-corpus problem). Measured: `insights_trending`
  **26–29 s**, `keyword_export` **34 s**, `insights_map` 6–16 s, `supergroups` **12 s**,
  `trending_windows` (the **Home poll**) **5–13 s**, `associations` 4–7 s, `layered_graph` 6 s, `map_data`
  4–8 s — while `columnar: available:false` (these hit raw SQLite GROUP-BY over 179 k mentions on 2
  cores, encrypted). Fast paths for contrast: `top_terms_grouped` 69 ms, FTS 12 ms, `/api/articles` 17
  ms, who/where ~100 ms. → build strategy **P2** (maintained `keyword_daily`/`source_coverage` rollups) +
  **P2.4** (verify DuckDB-1.4 GCM → unblock the persisted store, which is `available:false` today).

### F3 — keyword quality: stoplist leaks in "rising" cards
Rising-card terms include **`annons`** (Swedish *advertisement* = ad boilerplate), **`koji`** / **`ali`**
(Serbian function words "which"/"but"). → strategy **P4.2** (`reconcile_keyword_language`) + the
evidence-grown stoplist pass; also a nice tie-in to the "Latest" substance filter (boilerplate is exactly
what length/source gating catches).

### F4 — date-extraction recall gap (When/Where/Who)
Date diagnostics: **36.6 % coverage**, but **401 articles carry date-like text yet got no extraction**
(of 1,500 scanned), including **45 unextracted `cjk_date`** runs. → improve the `dateextract` recall
(and the CJK case ties to the segmentation gap, strategy P4.4). Lower priority than F1/F2.

### F5 — UI polling storm (compounds the contention)
This session accumulated ~**2,192** `GET /api/scheduler/activity` + **1,525** `/api/system/vitals` +
**699** `/api/scheduler/status` requests — thousands of polls contending with the single encrypted
connection (a long-standing finding). → consolidate into one status poll / SSE push + adaptive backoff
when idle (the airplane/scheduler responses already push state to lean on).
