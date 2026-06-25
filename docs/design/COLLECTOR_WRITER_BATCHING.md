# Collector writer-bound — batched-commit design (ledger P1-C)

> **Status: DESIGN, not built.** The implementation is a change to the data-loss-critical
> single-writer hot path (keystone #1). Its *perf benefit* can only be validated on the live
> corpus (the motivating metric is a live measurement), and its *failure-mode correctness*
> needs the full pytest suite to execute — neither is runnable in the autonomous-session
> sandbox (py3.11, no project deps; the repo needs py3.13). Per the project's "if it's not
> entirely reliable, it should not exist" non-negotiable, this is deferred to a session that
> can run the suite + measure on the live corpus. This doc is the safe design + the no-loss
> test plan so that implementation is confident.

## The contention (field report; CLAUDE.md P1-C)

The collector runs up to `collect_parallelism` (default 50) parallel fetch workers, each on
its own session against the **one** SQLite writer, serialized by the single-writer gate
(`src/database/writer.py`, keystone #1). Per article, the collect path takes the gate and
commits **twice or three times**:

1. `store_fetched` (`src/ingest/pipeline.py:124`): `session.add(article)` → `session.commit()`
   (gate cycle #1, one INSERT).
2. `_maybe_index_keywords` → `index_article` (`src/analytics/store.py:180`): a bulk
   `KeywordMention.delete()` (gate via `do_orm_execute`) + ~100–500 mention adds + the
   denormalised counter deltas + when/where/who + `session.commit()` (gate cycle #2).
3. `_maybe_index_links`: outbound-link rows + a commit (gate cycle #3, when links exist).

At 50 workers × N new articles each, that is `2–3N` gate acquisitions and `2–3N` fsyncs per
pass. The field metric: ~532,772 s cumulative gate-wait / 8,294 s max on the live corpus.

**Already taken (so NOT the lever):** `synchronous=NORMAL` in WAL + `busy_timeout=30000`
(`src/database/session.py:100-103`) — the cheap fsync-mode win is in place. The remaining
cost is the **number** of commits/fsyncs and the gate-acquire churn, not the per-fsync cost.

## The safe design — batch the per-source store+index into one transaction

Within ONE source's ingest (one worker, one session — articles of a source are processed
sequentially; the parallelism is *across* sources), accumulate `B` articles and commit once,
covering both the store and the index for the whole batch:

```
for entry in source_entries:
    article = build + dedup (the _exists hash check + in-batch hash set)
    session.add(article); session.flush()          # id assigned, gate acquired, NOT committed
    index_article(session, article, ..., commit=False)   # mentions + counters + WWW, NO commit
    if len(batch) >= B:
        _flush_batch()                               # ONE commit = ONE fsync for B articles
_flush_batch()                                       # the tail
```

This requires **one additive change** to `index_article`: a `commit: bool = True` parameter
(default `True` = byte-identical to every existing caller — re-index, backfill, reindex jobs).
The collect path passes `commit=False`; the batch wrapper does the single commit.

### Why it's correct by construction

- **Counters.** `index_article` computes `old_contrib`/`new_contrib` per article and applies
  the net delta to `Keyword.mention_count`/`article_count` (`_apply_keyword_counter_deltas`,
  store.py:290). Two batched articles touching the same keyword call it twice before one
  commit. Whether the deltas are ORM increments on the same in-session `Keyword` object OR a
  bulk `UPDATE ... SET mention_count = mention_count + :d`, both accumulate correctly within a
  **single** transaction (SQLite read-your-own-writes within a txn). So the batched commit ==
  the sum of the per-article commits, exactly.
- **The bulk DELETE** (store.py:248) targets only the article's own `article_id`, so batched
  articles never interfere; for NEW collect articles it is a no-op (no prior mentions).
- **Idempotency.** `index_article` is delete-then-reinsert, so re-running it reproduces the
  full result — the basis for the fallback below.

### Failure path = no data loss (mirror `ingest_emails`)

On a batch commit failure (a hash collision that slipped past the in-batch dedup, or a
transient `database is locked`), **roll back the whole batch and redo per-article** — the
exact proven pattern from `ingest_emails._flush` / `_commit_one` (`src/ingest/email.py:421`).
The per-article redo IS the current behaviour (store commit, then `index_article` under
`run_write_with_retry`), so a batch failure degrades to today's guarantees. No article and no
mention is ever dropped. The WWW lock re-raise (store.py:320) must abort the batch (not be
swallowed) so the fallback re-runs it — same reasoning as the existing per-article comment.

### The gate-hold tradeoff (the thing to MEASURE)

Batching reduces the *number* of gate acquisitions and fsyncs (≈ `2N → N/B + 1` per source)
but **increases the hold time per acquisition** (one worker holds the gate across a batch's
work). For a modest `B` (start at 10, env `OO_COLLECT_COMMIT_BATCH`, default... see below) the
fsync reduction should dominate, but the gate-monopolization-vs-throughput balance is exactly
what the live corpus must confirm. Ship it **default `B=1` (byte-identical current behaviour,
zero regression risk)** and let the maintainer raise it and measure via the existing
`src/monitoring/collect_perf.py` bottleneck log (which already reports gate-wait), OR adopt a
measured default once validated.

## Interaction with the 5A-bis keyword_daily rollup (forward note)

When the `keyword_daily` rollup (workstream 5A-bis D2/D3) lands, its **incremental** refresh
keys on the `keyword_mentions.id` watermark and assumes APPEND-only for new articles. Batched
collect is still append-only (new articles → new higher mention ids), so the watermark MERGE
stays correct. No epoch bump needed for batched collect (it only bumps for re-index/prune of
*existing* articles). Keep these two consistent.

## No-loss test plan (extend `tests/test_write_gate_dataloss.py`)

A sibling of `test_parallel_index_article_loses_no_keyword_or_date_rows`:

1. **Batched == per-article (exact).** Ingest M articles with shared keywords once with `B=1`
   and once with `B=10`; assert identical `KeywordMention` rows, identical
   `Keyword.mention_count`/`article_count` (the killer assert: counters == the live `GROUP BY`
   join), identical `ArticleMentionedDate` rows.
2. **Failure fallback loses nothing.** Inject a forced `IntegrityError` on one article mid-batch
   (e.g. a duplicate hash); assert the batch rolls back and the per-article redo stores every
   non-colliding article + the counters stay exact (no half-batch).
3. **Concurrency.** 6 workers × 15 articles each, batched, racing on the real `SessionLocal`;
   assert ZERO dropped rows, ZERO `database is locked`, exact counters, and
   `write_gate.stats()["held"]` is False at the end (no gate leak).
4. **A transient lock mid-batch retries the batch, not loses it** (force one lock, assert
   recovery via the fallback).

These run in CI (full deps). Build only when they can be executed + the live perf is measured.

## Rejected alternatives

- **Fold store + index into one per-article transaction (2→1 commit).** Changes the resilience
  guarantee: today the article is committed *first*, so a permanent index failure keeps the
  article (keywords backfilled later). Coupling them means a persistent index/extractor bug
  silently drops articles every pass. Not worth the regression.
- **`synchronous=OFF` / `wal_autocheckpoint` tuning.** Durability posture change beyond the
  collector; `NORMAL` is already the safe WAL setting.
- **A process pool for the parse stage.** Orthogonal (CPU, not the writer) — only if a future
  `collect_perf` log shows CPU-bound, not writer-bound.
