> **Status update (2026-08-20, perf/diagnostics burn-down):** re-verified item by item
> against live `main` @82fb74b, in the CODE rather than from this file's own text. **Five
> of the seven are closed; one is closed with its premise retracted; the two that were
> genuinely open were fixed or instrumented this pass.** Per-item verdicts are inline below. The headline
> correction is that this doc's own 2026-07-22 banner ("still fully unaddressed") went
> stale within days: items 2 and 5's building blocks landed 2026-07-23, and item 1's
> map-coverage half landed in the same wave.
>
> | # | Verdict (2026-08-20) | Anchor |
> |---|---|---|
> | 1 map-coverage | **CLOSED** | `idx_article_source_sentiment` (`models.py:730`) + boot self-heal (`maintenance.py:81`), 2026-07-23 |
> | 1 omni | **root-caused; 3 of 4 fixed this pass** | `search_omni.py`, `fts.py:search_total`; the NOCASE index is characterised + handed over (`maintenance.py`, blocked on an alembic/expression-index decision) |
> | 2 rising `article_ids` | **CLOSED** | `producers.py:305`; shipped.csv 2026-07-23 "9.1 rising_now article_ids" |
> | 3 stall cluster | **not answerable retroactively; answered FORWARD** | `src/monitoring/stall_forensics.py` + `/api/diagnostics/stall-forensics` (new this pass) |
> | 4 vocabulary/nav-soup | **CLOSED** | prose gate + `non_article_scan` quarantine shipped 2026-07-23 |
> | 5 non-article contamination | **CLOSED** (execution is a maintainer-gated operator step, by ruling) | S3.2/S3.3 quarantine, shipped.csv 2026-07-23 |
> | 6 five 100%-outlier sources | **PREMISE RETRACTED** | the 100% figures were a degenerate-cohort artifact: `source_audit.py:278-296,521`, fixed 2026-08-02 |
> | 7 schema/FTS clean | informational, unchanged | — |
>
> **Item 6 deserves the emphasis.** The five sources were not evidence of five broken
> scrapes: `source_audit`'s tail test is `value > p90`, and on a cohort with zero spread
> p90 is exactly 0.0, so the test degenerated to `value > 0` and ONE pathological article
> in a couple of thousand read as a 100% outlier rate. That was root-caused and fixed
> 2026-08-02 (`PATHOLOGY_ABS_FLOOR` plus the degenerate-cohort guard). Building the
> "hand-check these five" tool this brief proposes would have been building on a
> withdrawn signal — so it was deliberately not built, and this note replaces it.

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

> **2026-08-20 — map-coverage CLOSED; omni root-caused, three of its four defects fixed.** The suspects this
> item lists were both wrong, which is worth recording. map-coverage was not falling
> back to the live scan under some condition: its cost was the per-source-country
> `GROUP BY` reading `sentiment_score` off the heap, closed 2026-07-23 by
> `idx_article_source_sentiment`. And omni's slow path was not "a term with very high
> mention count" hitting the FTS — it was the **keyword** group. `normalized_term LIKE
> 'abc%'` cannot use SQLite's LIKE optimization unless the index carries NOCASE
> collation (whenever `case_sensitive_like` is off, the default), and
> `idx_keyword_normalized_term` is BINARY — so every debounced keystroke traversed all
> ~5M keys, twice. Measured on a 2M-row fixture with this table's real index set:
> 126.7 ms → 0.02 ms (count) and 140.8 ms → 0.22 ms (top-3). **That index is
> characterised and NOT shipped:** wiring it into the boot self-heal alone flips
> `alembic_stamp_align` to `schema-behind` (the check compares the live schema against
> the models), and mirroring it on the model does not help because `COLLATE NOCASE`
> makes it an expression index, which alembic's autogenerate cannot compare and reports
> as permanently changed. It needs a migrations-layer decision and is handed over with
> its DDL, measurement and blocker in `src/database/maintenance.py`. Two further
> findings in the same endpoint DID ship: the articles group reported `len(ids)` as its
> **total**, and `ids` is
> capped at 20000 — a cap wearing a count's name on any large corpus, which the
> 2026-07-18 "never capped figures" ruling forbids and whose sweep this is a result of;
> and the articles and wiki groups each ran the same ranked FTS fetch, so it now runs
> once per keystroke instead of twice.

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

> **2026-08-20 — STILL OPEN, and the question this item asks can no longer be answered
> retroactively.** What ran that day is not recoverable from the tree, and the
> instruments that would have said so are windowed: `collect_perf` keeps roughly one
> pass and the latency reservoir is a rolling sample. So the honest form of this item is
> not "find out what happened on 2026-07-11" but "make the NEXT one attributable".
> Partly mitigated since: the diagnostics path did get the deadline/threadpool
> discipline this item guessed at (PR #727, then the S8 debug-bundle budget), and
> `latency.py` now carries an event-loop-lag watchdog plus a per-route p95 verdict.
> What is still missing is the piece this item actually needs — a per-REQUEST cause
> class when a request blows its deadline (writer-gate wait vs codec read vs FTS vs
> CPU). **BUILT this pass** as `src/monitoring/stall_forensics.py`, hooked at
> `latency.record()` and surfaced at `/api/diagnostics/stall-forensics` (a bundle
> member): a request over `OO_STALL_THRESHOLD_MS` is filed with a point-in-time reading
> of `write_gate.stats()`, the loop-block watchdog and the slow-query log, plus the
> cause classes those readings SUPPORT. Correlation, never proof — and a stall none of
> the three can see is filed `undetermined` rather than assigned to the nearest class.
> It cannot answer 2026-07-11; it is what makes the next one answer itself.

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

> **2026-08-20 — PREMISE RETRACTED. Do not hand-check these five on this basis.** The
> reasoning below ("a 100% rate across a real sample is much more consistent with broken
> extraction … so 100% is a strong signal") is exactly the inference the auditor's own
> arithmetic made unsafe. `robust_stats` p90 is nearest-rank, and on a cohort whose
> members are all clean the p90 IS 0.0 — so the outlier test `value > p90` degenerates
> to `value > 0`, and a single pathological article out of ~2,000 scores 100%. The field
> run that produced this list flagged 63 sources that way, each of them orders of
> magnitude below its own absolute floor. Root-caused and fixed 2026-08-02
> (`source_audit.py:278-296` and the comment at `:521`; `PATHOLOGY_ABS_FLOOR` gives the
> high-confidence criterion a floor that fires independently of the cohort). The five
> named sources may or may not be healthy — the point is that THIS measurement never
> said they were broken, so the next word on them should come from a re-run of the
> fixed auditor, not from this list.

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
