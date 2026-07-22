> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — D2 (`keyword_daily`), D3 (incremental refresh + epoch-bump guard), and D4 (`source_coverage`) are all confirmed SHIPPED in `src/analytics/columnar.py`. D1 remains blocked on the httpfs binaries (see PERSISTED_DUCKDB_HTTPFS.md); D5 (Roaring co-occurrence bitmaps) is correctly still deferred, as designed. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Scaling the derived layer to 1000× (data-architecture workstream 5A-bis)

> **Source of truth + test plan for the derived-layer scaling work.** The deep fix for the
> "Insights freeze at 60K articles / 932K keywords" (field remark 8). It EXTENDS the shipped
> seam — `src/analytics/readmodel.py` (the read seam, v1 delegates to `queries`),
> `src/analytics/columnar.py` (the encrypted-or-in-memory DuckDB store: `connect()`,
> `keyword_agg`, `oo_meta`, `encryption_gate`, `secure_crypto_available()`,
> `build_keyword_read_model`, `top_terms_raw`, `refresh_persisted_read_model`), and the
> `ix_mention_date_keyword (observed_on, keyword_id, count)` covering index — and NEVER
> recreates them.

## The principle (binding, from CLAUDE.md)

ONE canonical encrypted SQLite/SQLCipher store is the source of truth. Everything here is the
**disposable, rebuildable derived layer** behind the read seam. The canonical store is NEVER
time-partitioned (**cross-time recall is sacred** — no recency bias). Any partitioning lives
only INSIDE the derived DuckDB file (year zonemaps), never as plaintext on disk. Performance
must NOT depend on hiding data — every article stays fully present + searchable. Maintained
aggregates carry the honesty envelope `{value, basis: exact|estimated|columnar(upper bound),
as_of, method, n}` (basis is a DISCLOSURE, not a score; `assert_no_score_fields` still holds).

## Why the freeze happens (measured)

`top_terms(group=True)` = 17 s / 50 rows on the live 61,635-article / 932,031-keyword corpus;
windowed `trending_windows` runs a `SUM(count) … WHERE observed_on IN [lo,hi) GROUP BY
keyword_id` over ~2.4M mention rows, each in-range row paying a SQLCipher page decrypt. The
`ix_mention_date_keyword` covering index (shipped) makes that an index-only scan, but the
decrypt cost over a multi-GB index range is still the floor. The structural fix is to NOT scan
the mention table on the read path at all — read a maintained **rollup**.

## The rollups (new DuckDB tables in the derived store)

### `keyword_daily` — the windowed-aggregation rollup (workstream D2)

```sql
CREATE TABLE keyword_daily (
  keyword_id       BIGINT,
  day              DATE,          -- = keyword_mentions.observed_on
  mentions         BIGINT,        -- = SUM(keyword_mentions.count) for (keyword_id, day)
  articles_on_day  BIGINT,        -- = COUNT(DISTINCT article_id) for (keyword_id, day)
  PRIMARY KEY (keyword_id, day)
);
```

Serves `readmodel.most_mentioned` / `rising_terms` (the windowed top/trending) by summing a
keyword's `mentions` over the requested `[lo, hi)` day range — a tiny aggregation over the
rollup, never the mention table.

### `source_coverage` — per-country coverage rollup (workstream D4)

```sql
CREATE TABLE source_coverage (
  country     VARCHAR,           -- normalized ISO-2 or '' for unlocated
  source_id   BIGINT,
  articles    BIGINT,
  mentions    BIGINT,
  first_day   DATE,
  last_day    DATE,
  PRIMARY KEY (country, source_id)
);
```

Serves per-country coverage (the World/Library map) without scanning the mention table.

## The full build — stream from SQLCipher INTO DuckDB, group THERE (D2)

DuckDB **cannot read a SQLCipher file**, and a SQLite `GROUP BY` over the billions-row mention
table is exactly the freeze. So the full build:

1. Stream canonical mention rows out of the app's SQLCipher connection in batches
   (`SELECT keyword_id, observed_on, count, article_id FROM keyword_mentions` — column-projected,
   the covering index serves it; never `SELECT *`, never the decrypt-heavy article join).
2. `INSERT` each batch into a DuckDB **staging** relation, then `INSERT INTO keyword_daily
   SELECT keyword_id, observed_on, SUM(count), COUNT(DISTINCT article_id) FROM staging GROUP BY
   1, 2` — the GROUP BY runs in DuckDB (columnar, fast), not in SQLite.
3. The full build streams ~10^10 rows through Python → it is a **resumable BATCH job**
   scheduled WITH the re-index, NEVER on the query path.

Mirror `build_keyword_read_model` (the existing `keyword_agg` builder) for the connection +
staging plumbing.

## Incremental refresh — the correctness-critical part (D3)

Keep two keys in `oo_meta`: `keyword_daily.last_mention_id` and `keyword_daily.built_epoch`.
`keyword_mentions.id` is a monotonic autoincrement PK (verified), so the row TAIL
(`id > last_mention_id`) is the set of mentions added since the last refresh.

**Refresh decision:**
- If `corpus_epoch != built_epoch` → **FULL rebuild** (reset watermark to `MAX(id)`, set
  `built_epoch = corpus_epoch`).
- Else → **incremental**: `MERGE INTO keyword_daily USING (SELECT keyword_id, observed_on AS
  day, SUM(count) AS m, COUNT(DISTINCT article_id) AS a FROM <tail> GROUP BY 1,2) t ON
  (keyword_id, day)` — MATCHED → `mentions += t.m, articles_on_day += t.a`; NOT MATCHED →
  INSERT. Then advance `last_mention_id = MAX(id)` processed.

### THE TRAP (grounded in this repo) — why MERGE-ADD is APPEND-only

`index_article` does **delete-then-reinsert** of an article's mentions
(`src/analytics/store.py:248` deletes, then re-adds). So the id-watermark MERGE-ADD is correct
ONLY for APPEND (new articles → strictly higher new ids that the tail captures once). EVERY
path that re-runs `index_article` over an EXISTING article — `reindex_all_batch`,
`reindex_articles`, `reindex_imported_articles` (restore), the clean-up-keywords flow — AND
`prune_orphan_keywords` (deletes rows) MUST **bump the corpus epoch** and force a FULL rebuild,
never an incremental MERGE, or the rollup double-counts (the old rows already in
`keyword_daily` + the re-inserted rows in the tail = a fabricated number).

**Normal new-article ingest must NOT bump the epoch** (or you full-rebuild every pass, killing
the win). So `corpus_epoch` is bumped by exactly the re-index/prune/restore mutators, and a
small `bump_corpus_epoch()` helper (writing an `oo_meta`-equivalent on the CANONICAL side, e.g.
a row in a tiny `derived_meta` table or a settings key) is called from each. The append path
leaves it untouched.

### Seam wiring (D2 + D3)

`readmodel.most_mentioned`/`rising_terms` serve from `keyword_daily` ONLY when: the persisted
store is present, `secure_crypto_available()` is true, AND `built_epoch == corpus_epoch`. Else
fall back to the live query. Carry the basis flag: `columnar@epoch N` vs `live` (slower, never
wrong). **Build + prove parity IN-MEMORY now** (DuckDB in-memory connect) even though the perf
win needs the persisted store (D1) — parity is provable in-memory; the seam guards on
`secure_crypto_available()` + epoch so the in-memory path stays a correctness scaffold, not a
silent slow default.

## D5 (OPTIONAL, off the critical path) — Roaring co-occurrence bitmaps

For SET-INTERSECTION queries the rollups don't help (co-occurrence / mind-map / actor-collapse):
a per-keyword article-id Roaring bitmap (pyroaring) stored as an encrypted-DuckDB blob;
`co-occurrence(X,Y) = popcount(bmp[X] AND bmp[Y])` in Python; precompute top-K neighbours
offline for all-pairs. Behind a NEW optional extra (graceful-degrade if absent, like
VADER/numpy), with a `configs/external_artifacts.yml` entry, rebuilt on epoch bump. Build only
when the graph queries actually need it.

## D1 (the unblock) — the persisted encrypted DuckDB store

Without it the columnar layer is RAM-bound and gives no gain over the counters (CLAUDE.md
already found this for `build_keyword_read_model`). The offline-LOAD code is OURS to write; the
per-OS/arch static-OpenSSL httpfs binaries are the maintainer's networked build. Full design +
the security analysis (autoload off, SHA-256 pin-and-verify before LOAD, GCM-only ATTACH never
CTR, the `encryption_gate` probe) live in `docs/design/PERSISTED_DUCKDB_HTTPFS.md` (workstream
5B). Until those binaries exist, the store is in-memory and the seam falls back to the live
query — slower, never wrong.

## Honesty guardrails

- `articles_on_day` summed over a window is an **UPPER BOUND** on distinct articles when a
  `(keyword, article)` pair spans multiple days (re-observation). Carry the basis flag
  `columnar (upper bound)` vs `live (exact)`. The live-exact escape is cheap **per-keyword
  only** (one keyword's mention rows), never corpus-wide.
- The rollup spans ALL history — never recency-biased (cross-time recall is sacred).
- Counts + basis flag only, never a composite score (`assert_no_score_fields`).
- Cold / missing / epoch-stale store → the seam falls back to the live query, identical
  results, basis `live`.

## VERIFY checklist (lift into tests; CI runs them)

1. `keyword_daily` `SUM(mentions)` == `SUM(count)` over `keyword_mentions` for a sampled
   keyword set (EXACT).
2. windowed most-mentioned == live ranking for a sampled window (EXACT on mentions).
3. windowed `COUNT(DISTINCT article_id)`: columnar upper-bound vs live exact differ ONLY where
   re-observation creates multi-day pairs; the gap is reported, never hidden.
4. incremental refresh after a new batch == a full rebuild (MERGE-add correctness).
5. a late-arriving historical-dated batch lands on the correct day after incremental
   (id-watermark).
6. a simulated re-index (epoch bump) forces a FULL rebuild, not incremental (the trap).
7. `analytics.duckdb` is unreadable as plaintext (encryption_gate passes with the OpenSSL
   backend). *(D1-gated)*
8. network blocked → opening the store + loading bundled httpfs makes ZERO outbound
   connections (autoload off). *(D1-gated)*
9. the bundled httpfs binary matches its pinned SHA-256 before LOAD. *(D1-gated)*
10. no ATTACH cipher other than the default authenticated GCM is ever requested. *(D1-gated)*
11. cold/missing `analytics.duckdb` → the seam falls back to the live query with the correct
    basis flag, identical results.
12. Roaring `co-occurrence(X,Y)` == the live two-keyword article-intersection count for a
    sampled pair (EXACT). *(D5-gated)*

## Build order

D2 (`keyword_daily` + the streamed full build + in-memory parity tests + seam wiring, basis
flag) → D3 (incremental refresh + the epoch-bump-on-mutate guard, with VERIFY 4/5/6) → D4
(`source_coverage`) → D1 (persisted store, gated on the binaries) → D5 (optional). The full
payoff is gated on D1, so build D2–D4 + parity tests + seam now and do NOT block the rest of
the to-do on it.

## Rejected (the research red-teamed these — do NOT wander to them)

chDB / ClickHouse (unauthenticated AES-CTR / LUKS-punt — loses in-engine authenticated
encryption); Turso/libSQL (solves write-concurrency we don't have, costs SQLCipher); Tantivy
(FTS5 scales to tens of millions of docs — keep it); ATTACH per-period partitions of the
canonical store (WAL has no cross-attach atomicity); time-partitioning the canonical store
(abandoned — cross-time recall). Keep **DuckDB + FTS5 + ONE canonical SQLite file**. In-engine
vectors (sqlite-vec) are orthogonal (semantic search) — defer. Single-node is by intent;
multi-writer is the separate Open Commons Mirror project, not a scaling lever here.
