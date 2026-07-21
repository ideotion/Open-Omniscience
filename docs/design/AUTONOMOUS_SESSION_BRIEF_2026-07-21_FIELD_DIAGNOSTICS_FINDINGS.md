# Autonomous session brief — field diagnostics findings (2026-07-21)

Status: **findings only, nothing implemented.** This brief packages what a real diagnostics
export from the live app (operator-run, not synthetic) surfaced, so a future session can pick
up whichever items the maintainer greenlights without re-deriving the numbers. Source data:
three exports pulled 2026-07-21 (`oo-diagnostics-20260721-0750.zip`,
`oo-keyword-log-20260721-0740.zip`, `oo-source-quality-20260721-0724.zip`) against the live
corpus, **474,556 articles** (`debug-bundle.json`'s `data.corpus.articles`) — real but roughly
an order of magnitude below the 0.3 CLOSE GATE's ≥5M-article bar, so nothing here closes that
gate. These are operational findings from the current corpus, independent of the gate.

Each item below is a candidate for its own scoped PR — do not bundle them. None require corpus
growth to investigate or fix; all are reproducible against the current ~475K-article corpus.

## 1. Two endpoints have a severe slow long-tail (highest priority — user-facing)

`GET /api/insights/map-coverage` (`src/api/insights.py:1161`, backed by
`src/analytics/map_serve.py:235` / `queries.source_country_counts` fallback): p50=20ms
(healthy) but **p95=117s, p99=264s, max=335s** across 1,397 logged calls. `GET
/api/search/omni` (`src/api/search_omni.py:290`): p50=4.5s but **p95/p99/max≈291s** across 31
calls. Most requests are fine — a specific query shape or corpus state is triggering a path
that takes minutes. Suspects to check first: whether `map_serve.map_coverage` is falling back
to the live `source_country_counts` scan (rather than serving from its in-memory/duckdb cache)
under some condition, and whether `search_omni.omni` has a query-shape-dependent slow path
(e.g. a term with very high mention count, or a query that misses an index). Start from
`request-latency.json`'s per-route breakdown and `slow-queries.json`'s EXPLAIN QUERY PLAN
output for whichever queries these two routes actually run.

## 2. "Rising" Lead cards never got hard-linked to their exact articles

Every other Home Lead card type observed (echo_chamber, flooded_topic, source_laundering,
copypasta, framing, emotion, etc.) hard-links to its exact corpus results — the "F1 follow-up
(2026-07-01): hard-link the exact articles" comments at `src/briefing/producers.py:338` and
`:1085` mark where sibling producers got this. `rising_now` (`producers.py:193-269`) computes
`rows = _articles_for_term(...)` and uses it for `evidence=_evidence_from_articles(rows)`, but
**never passes `article_ids=` to `Card(...)`** the way the hard-linked producers do — so the
Home diagnostics (`oo-home-cards-*.json`) show 5/5 "rising" cards falling back to fuzzy search
instead of an exact link. This reads as a straightforward, scoped fix: thread `article_ids`
(likely `[r["id"] for r in rows]` or equivalent, matching the sibling producers' exact pattern)
through to the `Card(...)` call. Verify against `src/api/diagnostics.py`'s `home-cards`
diagnostic (it's the thing that caught this) after the fix.

## 3. A cluster of 503s and event-loop stalls, all on 2026-07-11

The watchdog logged in-flight requests stuck for hours on 2026-07-11 (`home-cards` and
`rollup-benchmark` both multi-hour that day per `request-latency.json`), and
`frontend-errors.json` shows repeated 503s on `/api/insights/corpus-keywords`,
`/api/insights/latest`, and `/api/insights/corpus-www` within the same 11:40–13:41 window —
1,980 total logged problems that day, 8 of them "locked" errors. Reading as one heavy
diagnostic/ingest job choking the single worker and taking user-facing search/insights down
with it. Action: check what ran on 2026-07-11 (a diagnostics export, a large import, a
reindex?) against the timeline in that day's logs, and confirm whether this is the same
"heavy sync work on the event loop" class of bug the S8 lesson and the DIAGNOSE-THE-
DIAGNOSTICS deadline work (just shipped in PR #727) are meant to prevent going forward — if
so, this may already be mitigated for the *diagnostics* path; check whether an equivalent
deadline/threadpool discipline is missing on whatever ran that day.

## 4. Vocabulary isn't saturating — concrete evidence for the planned nav-soup/prose-gate work

Total keywords = 5,041,833 across 474,556-477,122 articles (per `oo-keyword-growth-*.json`).
The most recent growth window's marginal rate (~9.7 new distinct keywords per new article,
window 124,467→477,122 articles / 2026-05-30→07-16) is essentially flat versus the cumulative
average (~10.6/article) — near-Heaps-linear, not bending toward saturation. This is the
signature the project already associates with markup/boilerplate contamination rather than
healthy topic reuse (see `viewKeywordGrowth`'s own tooltip in `index.html`). Directly feeds
the still-unbuilt nav-soup prose gate (0.3 gate row 5 building block, not yet implemented per
recon as of 2026-07-20) — this is the empirical case for why it's worth building, and a
before/after metric to check the fix against once it ships.

## 5. Non-article contamination: measured, bounded, ready to quarantine

`oo-non-article-scan-*.json`: **6,825 / 474,556 (1.44%)** flagged — 4,121 tag-listing pages,
1,186 bare homepages, 755 section landings (rest: other reasons). This is exactly what
`src/analytics/non_article_scan.py`'s reversible-quarantine scan already measures (shipped
2026-07-13); the number gives a concrete, small, bounded first quarantine batch to run once
the maintainer signs off on the cleanup strategy (0.3 gate row 5 — execution needs explicit
maintainer agreement per the ledger's own ruling, not something to just run).

## 6. Source health: 6% degraded/failing, with a few outright-broken standouts

`oo-source-audit-*.json`: of 1,957 sources, 1,563 healthy, 276 watch, 90 degraded, 28 failing.
Five sources show **100% outlier_rate** (every sampled article flagged): `subseaworldnews.com`,
`biospectrumasia.com`, `jota.info`, `24heures.ch`, `suspilne.media`. A 100% rate across a real
sample is much more consistent with broken extraction (wrong DOM selector, or the source now
serves stub/paywall pages) than with legitimately atypical content — the auditor's own design
explicitly never demotes for terse-but-real prose, so 100% is a strong signal. Good first
candidates to hand-check manually (fetch a live URL from each, compare to what the extractor
stored) before the source-requalification work (0.3 gate row 1) has to build the automated
version of this judgment call.

## 7. Clean, for contrast

Schema has zero drift (migration head matches live DB, no missing table/column/index per
`schema-drift.json`). FTS is healthy with zero staleness (`integrity.json`). Worth noting so a
future session doesn't waste time re-checking these.

## Not investigated in this pass

The two larger exports (`oo-keyword-log-20260721-0740.zip`, 6.3MB; `oo-source-quality-
20260721-0724.zip`, 13.8MB) were only skimmed for summary-level shape, not read exhaustively —
if a future session wants per-source or per-keyword granular detail beyond what's summarized
above, those raw exports (if still available on the machine that pulled them) are the source.
