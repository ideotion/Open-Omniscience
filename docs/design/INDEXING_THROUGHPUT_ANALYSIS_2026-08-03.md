# Indexing throughput — analysis and strategy board (2026-08-03)

**Status: ANALYSIS ONLY. Nothing here is built.** Maintainer report that prompted it:
*"on a good and sufficiently powerful machine, indexing articles takes a very long time
whilst not using much of the system's resources."*

Produced by an orchestrating session (inline benchmarks) plus a ten-agent fan-out
(six read-only recon, three adversarial critics, one synthesis). Every load-bearing
claim was re-verified against the working tree; the one bug claim was live-reproduced
before being written down, per the standing reproducer-first rule.

## The answer in one paragraph

There is no single slow function. There are **four serial paths** through
`index_article`, and only **one** — the restore-merge — ever received the process pool,
the timing instrumentation and the batched commits built during the 2026-07-29 →
2026-08-02 arc. The whole-corpus re-index job, the automatic `backfill_corpus` top-up
and live ingest all run the full per-article CPU on one core, and two of them hold the
process-wide write gate while doing it, so sibling threads sit in `Condition.wait()`
consuming no CPU. That is exactly "a long time, not much resource use". Underneath
that, the *automatic* path carries a permanent-skip bug that no amount of acceleration
cures.

## Measurements taken this session

4-core sandbox, ~12 KB synthetic **English** articles, plaintext SQLite,
load-bracketed against a raw-`ProcessPoolExecutor` control measured in the same minute.

| | |
|---|---|
| `index_article` end-to-end | ~215 ms/article |
| pure CPU share of that | **~88%** |
| `precompute_batch`, like-for-like, 4 workers | **3.48x** (control: 3.5x) |
| end-to-end with the pool + `commit_batch=50` | 4.3 -> 9.4-11.0 art/s (**2.1-2.6x**) |
| per-term keyword lookup, SQLAlchemy ORM | 235 us |
| the same lookup in raw SQL, 3M keywords, **encrypted** | **25 us** |
| `cache_size` 64 MB -> 512 MB | within run-to-run noise |
| `commit_batch` alone, no pool | ~8% |

Two conclusions worth keeping. The keyword lookup is **not** codec-bound — ~93% of it is
SQLAlchemy Python overhead, and it is nearly flat in table size. And more RAM is not a
lever: the working set already fits, and on the collector path SQLite never sees
contention at all, because the serialisation is an application-level Python mutex.

### A correction, recorded because it nearly shipped as a finding

The first measurement put `precompute_batch` at **1.02x** and I was ready to call the
pool defective. It is not. `_compute_one` (serial) **deliberately skips** when/where/who
while `_worker_compute` (pooled) performs it, so the naive comparison pits two different
workloads against each other and understates the pool by roughly 2x. Like-for-like it
delivers 3.48x. A wall-clock A/B across a code path whose two branches do different
amounts of work measures nothing until that is ruled out.

### And a limit on all of the above

These numbers are synthetic English prose at 12 KB on 4 plaintext cores. Real articles
run 25-50 KB, the corpus is encrypted and strongly non-Anglophone, and the machine has
more cores. See F6 and M1 below: VADER's cost varies **270x** with lexicon density and
only runs on English at all, so **no per-article CPU *ranking* from this session should
be quoted** — including the tempting one that sentiment is the largest term.


## 1. Corrections to the established-facts list

| # | Established fact | Correction |
|---|---|---|
| 5 | "`reindex_all_batch` … used by the UI Clean-up-keywords job and by `/api/insights`" | **Both halves need qualifying.** The UI button passes `scope="keywords"` (`/home/user/Open-Omniscience/src/static/app.js:12824` → `_startReindexJob(true,"keywords")`), which skips **both** sentiment (`store.py:266`) and the whole when/where/who block (`store.py:380`). And `POST /api/insights/reindex-all` (`/home/user/Open-Omniscience/src/api/insights.py:525`) has **no `scope` parameter at all**, so it always runs `scope="full"` — but it is **unreachable from the UI**: its client loop `_reindexAllLoop` is defined at `app.js:12761` and never called; it survives only because `tests/test_repo_invariants.py:255` asserts the string is present. |
| — | *(missing from the list)* | There is a **third serial path, and it is the automatic one**: `backfill_corpus` (`/home/user/Open-Omniscience/src/analytics/store.py:451`), driven by the 6-second Insights poll (`app.js:12708` → `autoIndexInsights` → `POST /api/insights/reindex`). It runs `index_article` at the default `scope="full"`, with no pool, no cursor, and no task-manager job surface. |
| — | *(missing)* | **Live ingest is a fourth serial path** and the only one where extraction runs *inside* an already-held write gate — `_flush_batched` flushes (acquiring the gate) *before* the indexing loop and commits after it, per its own comment at `/home/user/Open-Omniscience/src/ingest/batch.py:298-309`. |
| 6 | "`OO_REINDEX_COMMIT_BATCH`, default `1`" | Correct **for the re-index job only**. The collector has a separate knob, `OO_COLLECT_COMMIT_BATCH`, default **8** (`/home/user/Open-Omniscience/src/ingest/batch.py:71-74`). "One commit per article" is not a live-ingest problem. |
| — | Ledger claim: columnar rollup serve is `OO_COLUMNAR_SERVE=1`, **off by default** | **STALE.** `serve_enabled()` returns True whenever duckdb imports; its docstring says "AUTOMATIC by default … no flag to flip" (`/home/user/Open-Omniscience/src/analytics/rollup_serve.py:98`), and `columnar` is in the default install extras (`/home/user/Open-Omniscience/install.sh:180`). This makes §S8 below a live cost, not a dormant one. |
| — | Ledger claim: "~200 terms/article" | **STALE.** Hard ceiling is 160 — `_DEFAULT_MAX_TERMS = 80` + `_DEFAULT_MAX_ENTITIES = 80` (`/home/user/Open-Omniscience/src/analytics/extract.py:68-69`), applied at `:559` and `:479`. Every per-term cost estimate in the ledger is ~2.5× high. |
| — | `reindex_parallel.py:39` docstring: pooled half is "~36 ms" | **Understated for English articles.** That figure is only reachable when `score_article` short-circuits on a non-English body (`sentiment.py:66`). It does not invalidate the fix, but the serial/parallel ratio the fix was sized against was wrong in the *opposite* direction to what was believed. |

---

## 2. Surviving objections that constrain the work

These are not caveats. Each one **forbids a specific implementation** of a strategy below.

### F1 — A keyword-id cache scoped wider than one `index_article` call silently corrupts data
`keywords.normalized_term` has **no unique index** (`/home/user/Open-Omniscience/src/database/models.py:872`, only the plain `Index` at `:934`), and SQLite reuses the rowid of a rolled-back INSERT. Live-reproduced: keyword `sanctions` gets id 1 → a later article in the batch raises → `session.rollback()` (`store.py:698`, `:932`) → `football` gets id 1 → the redo writes `(article, 'football')`. **No exception.** The loud variant (id points at a deleted keyword) raises `IntegrityError`, which `is_locked_error` returns False for, so `run_write_with_retry` does not retry and the article is marked failed with zero keywords.
→ **Constrains S3: the prewarm must be per-`index_article`-call, never per-batch or per-window.**

### F2 — The same cache on the collector path is worse
`_index_one` wraps the whole `index_article` in `with self._session.begin_nested()` (`/home/user/Open-Omniscience/src/ingest/batch.py:353-360`), so a per-article SAVEPOINT rollback destroys keyword rows while the outer batch transaction stays alive and the loop continues. A batch-scoped cache is then stale for every remaining article, and `_index_one` swallows the resulting FK error — so a fault in article 3 costs article 4 **all** its keywords.
→ **Constrains S5.**

### F3 — Overlapping precompute with apply, or reordering a window, breaks the resume cursor
`/home/user/Open-Omniscience/src/backup/merge.py:2588` stamps `ids[done - 1]` — a **count mapped back to an id by position** — and the resume keeps only `i > watermark`. This is safe today only because `_apply_window` iterates the window rebuilt in caller order (`store.py:748-752`) and `pool.map` yields in submission order. Switch to `as_completed`, or size-sort the window for pool balance, and articles below the stamped watermark are **permanently skipped and never revisited**. The guard test for exactly this property (`tests/test_analytics_store.py:729`) runs at `workers=0` and **would stay green**.
→ **Constrains S4: keep strict load→precompute→apply phasing and caller ordering, or replace the positional cursor first.**

### F4 — The pool silently ignores extractor configuration
`_worker_init` reconstructs via `get_extractor(name, gazetteer=...)` only (`/home/user/Open-Omniscience/src/analytics/reindex_parallel.py:336-340`); `max_terms`/`max_entities` are dropped. Measured: `BaselineExtractor(max_terms=5)` yields 5 terms serial, 80 pooled — same object, same batch. The guard at `tests/test_reindex_parallel.py:101` only rejects a *differently-named* extractor, so a configured `BaselineExtractor` sails through. Latent today (every production site uses `get_extractor("baseline")`), live landmine for any port.
→ **Constrains S4.**

### F5 — `precomputed_www` with `[]` instead of `None` is a silent delete
`store_places_for_article` and `store_entities_for_article` (`/home/user/Open-Omniscience/src/timemap/whostore.py:33`, `:121`) DELETE first, then insert `precomputed`. Only `None` means "not precomputed". The defensive-looking line `{"places": www.get("places", [])}` **deletes every place and entity row** with no error and no counter movement. Four separate docstrings in the tree warn about this, which is itself evidence of how tempting it is. Dates are safe (additive, skips existing keys).
→ **Constrains S4 and S5.**

### F6 — No per-article CPU ranking in this investigation is trustworthy
Three agents measured the *same quantity* (per-article CPU at 35 KB) as **642 ms / 772 ms / 394 ms**, all labelled `[measured]`. The spread is dominated by VADER, which was measured at **5.0 ms → 1352.8 ms on identical 35 KB bodies** purely by varying lexicon-word density — a 270× spread. Compounding: `score_article` returns `(None, None)` unless the language is `en` (`sentiment.py:66`), and this corpus is documented as strongly non-Anglophone, so VADER may be a minority-of-articles cost corpus-wide. `extract_dates` by contrast measured content-*insensitive* (138 → 170 ms across a 30× change in date density), so the dates/places figures are the comparatively trustworthy ones.
→ **Do not quote any "sentiment is the biggest term" ranking.** See §5 M1.

### F7 — The Amdahl argument against porting the pool rests on one uncorroborated line
"apply is 94% of wall clock" appears in exactly two places (`/home/user/Open-Omniscience/src/analytics/store.py:707` and `tests/test_import_hot_stages.py:246`) and is the **same observation quoted twice**; there is no committed script that produced it. It was measured on the restore path, at `scope="full"`, encrypted, ~6.9M keywords, **with the pool already active**. A sandbox measurement of the same function gave 46% precompute / 54% apply — a 1.8× ceiling, not 1.06×. Both are probably right in their own regime.
→ **Neither "port the pool" nor "don't bother" is currently justified. See §5 M2.**

---

## 3. THE BOARD

Ranked by evidence strength × effect × safety.

---

### ① Fix the `backfill_corpus` permanent-skip wedge
**Not an acceleration — a bug that produces the reported symptom and that no acceleration cures.**

| | |
|---|---|
| **Path** | The automatic Insights top-up (`POST /api/insights/reindex`). Most likely referent of the user report. |
| **Evidence** | **measured** (live-reproduced by a critic) + **code-read** (I confirmed the mechanism this session) |
| **Size** | Small–medium (needs a design decision, see risk) |

**What it is.** `_unindexed_query` is `~Article.id.in_(distinct KeywordMention.article_id)` ordered by id and limited (`/home/user/Open-Omniscience/src/analytics/store.py:445-467`). There is **no cursor**. An article that legitimately yields **zero kept terms** never leaves that set, so it is re-selected on every pass forever, and everything behind it is never reached.

Live repro at `limit=4` with five un-indexable articles (empty body, whitespace-only, all-stopword, a body equal to the source's own name — killed by self-name suppression at `store.py:328`): four consecutive passes each select ids `[1,2,3,4]`, each report `indexed=4`, `remaining` stays 8, and the three good articles behind them end with **zero mentions, never indexed**.

In production this is `limit=300` looped 40× by `autoIndexInsights` (`app.js:12738`), and its break condition `r.indexed === 0` **never fires** because `indexed` counts *attempts*, not progress. So opening Insights burns 12,000 full-scope `index_article` calls on the same 300 articles. At 794k articles, a zero-term rate above 0.04% wedges it permanently. Each batch also ends with `remaining = _unindexed_query(session).count()` — a `NOT IN` over the whole mentions table.

**Effect.** Currently unbounded — the path may make **zero** forward progress while burning a core indefinitely. Speeding up `index_article` makes the wedge spin faster, not go away.

**Risk.** The obvious fix (add `after_id`) needs a separate *un-indexable* concept, or `done` can never become true. Recommended shape: keep the cursor, and record a per-article "indexed, produced nothing" marker (or simply let the cursor advance and accept that a genuinely-empty article is skipped by the top-up until the next full re-index). Do **not** make `indexed === 0` the break condition without that.

**Reproducer** to keep: `scratchpad/backfill_wedge.py`.

---

### ② Instrument `reindex_all_batch` and give the job a phase field
**Zero speedup. It is ranked #2 because every uncertain strategy below is blocked on it.**

| | |
|---|---|
| **Path** | Whole-corpus re-index (both the job and the endpoint) |
| **Evidence** | **code-read**, confirmed this session |
| **Size** | Small |

Two gaps, both verified:

1. `reindex_all_batch` (`/home/user/Open-Omniscience/src/analytics/store.py:820-827`) accepts **no `stats` parameter** and returns only `{reindexed, failed, last_id, remaining, done}`. Its sibling `reindex_articles` fills `load_s / precompute_s / apply_s / apply_index_s / apply_commit_s / articles_per_second` plus a `by_path` dict naming pool/serial/fallback. **The path the user is complaining about produces no measurement at all.**
2. Even inside `reindex_articles`, `apply_index_s` and `apply_commit_s` are incremented **only in the `commit_batch > 1` branch** (`store.py:681`, `:660`); the `<= 1` branch (`store.py:640-650`) touches neither. And `commit_batch=1` is the default for a non-exclusive import (`merge.py:2202`). **The instrumentation built to answer "is apply staging or commit?" is dead on exactly the configuration where the question is open.**

Additionally: `reindex_job.status()` has **no phase field**; `percent` is derived purely from `articles_done/articles_total`. After the article loop, a long serial post-pass chain runs with the bar pinned at 100% — `prune_orphan_keywords(session, budget_s=0)` (**unbounded**), `reconcile_keyword_language`, `reconcile_keyword_entity_status`, a `while` loop of `reconcile_article_language(limit=500)` over the whole corpus, then `optimize_after_bulk` (FTS5 merge + ANALYZE). Verified at `/home/user/Open-Omniscience/src/analytics/reindex_job.py:239-292`. On a corpus with ~half the articles lacking a language tag, that language loop alone runs a text detector over hundreds of thousands of articles with **zero progress reporting** — this is the project's own recorded "a progress callback wired into only one stage reads as a hang" lesson, live.

**Effect.** No throughput change. Converts every unmeasured claim below into a decidable one, and converts a job that *looks* hung into one that reports its phase.

**Risk.** None material.

---

### ③ Per-call batched keyword lookup
| | |
|---|---|
| **Path** | All four (it is inside `index_article`) |
| **Evidence** | **measured** (independently reproduced twice), with a **regime caveat** |
| **Size** | Small |

**What it is.** `_get_or_create_keyword` (`/home/user/Open-Omniscience/src/analytics/store.py:70`) issues a fresh `session.query(Keyword).filter_by(normalized_term=...).first()` **per kept term**. Measured cost: **276–352 µs/term**, of which only ~18 µs is the database — ~93% is SQLAlchemy per-query Python overhead. Independently reproduced at 288 µs/term (200k keywords) and 320 µs/term (2M keywords) — i.e. **nearly flat in table size**, because it is Python, not I/O.

At the real 80-term cap that is **~26 ms/article**, against **0.76 ms** for one `IN (...)` returning Core tuples — a measured ~28–37× on that step.

**The honest effect statement.** The sandbox measured `apply_s` at 33 ms/article, where this would be two-thirds. The tree's own field log implies apply is **600–1250 ms/article** at real scale — 20–40× larger. Because the lookup cost is *flat* in table size, it does **not** grow to meet that. So at field scale this is worth roughly **4–10% of apply**, not two-thirds. It is cheap, safe and worth doing; it is **not** the fix, and shipping it as the fix would burn the one credible opportunity to find what actually costs 600+ ms.

**Implementation, constrained by F1.** One chunked Core SELECT of `(id, normalized_term, is_entity, entity_type)` for the kept terms, **collapsed to `MIN(id)` per normalized_term** (duplicates exist in the wild — `merge.py:881-894` says so explicitly, and `.first()` has a de-facto `MIN(id)` tie-break that a bare `IN()` does not inherit; `merge.py:912` already uses `MIN(id)` as the precedent). In the loop, take the cached id **only** when the row exists and no entity upgrade is due; otherwise fall through to the untouched `_get_or_create_keyword`. Every side effect is preserved by construction because the slow path *is* the original function. **Scope: one `index_article` call. Nothing wider.**

Five behaviours the fast path must preserve, all in `store.py:69-97`: the returned `.id` (feeds both the mention row and the counter delta); MISS → create with first-surface-form term, first-write-wins language, then flush; MISS → insert baseline `KeywordTag` rows; HIT + entity → **upgrade** `is_entity`/`entity_type` (upgrade-only, never downgrade); the implicit `updated_at` bump. Note the entity-upgrade branch is a cold path with the current extractor (entities keep UPPERCASE forms, terms are lowercased, so they cannot collide) — good for hit rate, still must be handled.

**Also correct the record while doing this.** The tree currently dismisses this area via `tests/test_import_hot_stages.py:246-255` ("a covering index measured 1.9×, ~0.2% of apply"). That arithmetic costed the **raw DB time** (13 µs → 7 µs) and ignored the ~300 µs/term of ORM overhead — a ~23× understatement. The note's *conclusion about a covering index* still holds (an index cannot touch Python overhead), but its premise is wrong, and reusing it as "the keyword lookup is already known irrelevant" would reject this fix on evidence that never measured the thing it removes. Fix the docstring so the next reader inherits the corrected premise.

---

### ④ Cap `extract_dates`' scan
| | |
|---|---|
| **Path** | Every `scope="full"` path (ingest, backfill, restore) |
| **Evidence** | **code-read**, confirmed this session; magnitude **measured** |
| **Size** | Tiny (one line + a disclosure) |

`extract_locations` caps at `_MAX_SCAN = 60_000` (`/home/user/Open-Omniscience/src/timemap/locextract.py:65`, applied `:99`) and `extract_entities` does the same (`entextract.py:19`, `:72`). **`extract_dates` has no cap at all** — I grepped; there is no `_MAX_SCAN` in `/home/user/Open-Omniscience/src/timemap/dateextract.py`, only local slices at `:1141/:1303/:1343`.

Measured: at 35 / 60 / 120 / 240 KB, dates cost **220 / 376 / 741 / 1530 ms** (linear, unbounded) while places plateau at 97 / 161 / 160 / 154 ms and entities at 6 / 9 / 9 / 9 ms.

**Effect.** Bounds the worst per-article case. Does nothing for typical articles. This is a tail fix, and dates are the largest of the three WWW terms (~70%), so it is worth the one line.

**Risk.** Real: dates beyond 60 KB are lost. That is a **recall** change and must be disclosed, not slipped in — the two siblings set the precedent for the bound, not for hiding it.

---

### ⑤ Stop the corpus-epoch churn from re-invalidating the rollups
| | |
|---|---|
| **Path** | Whole-corpus re-index (and it slows the *rest of the app* while it runs) |
| **Evidence** | **code-read** + **inferred** (duckdb absent from this sandbox — unverified end-to-end) |
| **Size** | Small |

`reindex_all_batch` bumps the corpus epoch **once per batch** (`store.py:862-869`), and `reindex_job` uses `_BATCH = 300` — so ~2,650 bumps on a 794k corpus. Two consequences, both live now that the serve is confirmed auto-on (§1):

- The epoch is part of `serve_gate.change_token`, so the P1.10 change gate — built specifically to stop a blind timer rebuilding the rollup every 15 min — is **defeated for the whole run**: the token always differs, so a full rebuild fires every TTL and `refresh_keyword_daily` takes the `needs_full` branch (`columnar.py:1066-1076`).
- `source_country_rollup.served()` returns `None` whenever `built_epoch != _current_epoch` (`/home/user/Open-Omniscience/src/analytics/source_country_rollup.py:158-162`), so `GET /api/database/countries` — the endpoint the 7-instance hardware comparison named the **dominant cost center on every machine** — reverts to its slow live query for the entire re-index. The user must have the UI open to watch the re-index, so the app is simultaneously slow for an unrelated reason.

**Fix shape.** Bump once per *run* (owned by `reindex_job`), not once per batch. The per-batch placement exists so a partially-failing batch still forces a rebuild; a run-level bump at both start and end preserves that.

**Risk.** Must not weaken the D3 double-count guard. Verify by logging `refresh_keyword_daily`'s returned `mode` during a re-index on a duckdb install.

---

### ⑥ Port the precompute pool to `reindex_all_batch` and `backfill_corpus`
| | |
|---|---|
| **Path** | Whole-corpus re-index + the automatic top-up |
| **Evidence** | **code-read** for the gap (certain); **effect is disputed and unmeasured** (F7) |
| **Size** | Medium–large |

The gap is real and has no correctness justification: `git log` over `reindex_parallel.py` shows five commits between 2026-07-29 and 2026-08-02, all framed as import/restore fixes, and none of them touched `reindex_all_batch`. *(Caveat: `.git/shallow` exists — history reaches only 2026-07-27, so this proves "untouched across the perf arc", not "untouched ever".)*

**Do not commit to this until M2 (§5) is measured.** The two available estimates of the ceiling disagree by 1.7× (F7), and if ③ lands first, apply shrinks and the ceiling moves again.

**Hard constraints if it proceeds:**
- **F3** — keep strict load→precompute→apply phasing and the caller-order window rebuild (`store.py:748-752`). Do **not** switch to `as_completed` and do **not** size-sort for pool balance without first replacing the positional cursor at `merge.py:2588`. And note the guard test runs at `workers=0`, so it will not protect you.
- **F4** — the pool drops `max_terms`/`max_entities`. Either thread the config through `_worker_init` or assert the extractor is default-configured.
- **F5** — never pass `[]` for `precomputed_www` places/entities.
- **Scope-awareness** — under `scope="keywords"` the worker would compute and discard sentiment (`_compute_one` scores unconditionally, `reindex_parallel.py:427-435`), and must **not** be handed the 6-tuple WWW context, which `index_article` throws away at `store.py:380`.
- **Accounting** — `reindex_all_batch` counts a deleted-mid-run article as neither reindexed nor failed while still advancing `last_id` (`store.py:873-881`, `:917-923`); `reindex_articles` drops missing ids from the window entirely, which `merge.py:2609` deliberately reads as "stopped early". Keep `reindex_all_batch`'s semantics or the job's percentage and cursor both change meaning.
- **Self-name suppression cannot cross the pool boundary** — `_self_name_forms(article.source)` reads a lazy relationship (`store.py:325`, `models.py:679`), so it must stay in the parent, as it does today. Doing it partially would index the outlet's own name on pooled articles and suppress it on serially-computed ones, in the same corpus, decided by whether a pool timeout happened.

**Two pool defects worth fixing in the same pass:**
- On a timeout, the partial `out` dict is discarded and `_serial` is handed the **full** task list (`reindex_parallel.py:558`, `:590-604`) — a timeout on article 499 of 500 discards 498 good results.
- `_serial` deliberately does **not** compute WWW (`:430-434`, `:486`), so a fallback window returns `www=None` for every article and `index_article` re-extracts it inline in the main process — the most expensive step, moved back onto one core precisely when things are already going badly.
- The 900 s pool timeout is a **total** deadline for the window, not per-item (CPython `Executor.map` computes `end_time` once), and `_serial` has no bound at all (only a 60 s logging watchdog). So a single wedged article turns "hang" into "900 s + hang". This is the exact pathology the field stalls it cites were about.

---

### ⑦ Hoist extraction out of the write gate on the collector path
| | |
|---|---|
| **Path** | Live ingest only |
| **Evidence** | **code-read**, confirmed this session (the code says so in a comment) |
| **Size** | Medium |

`_flush_batched` (`/home/user/Open-Omniscience/src/ingest/batch.py:296-319`) stages rows, calls `session.flush()` — which acquires the gate via `_on_before_flush` (`/home/user/Open-Omniscience/src/database/writer.py:245-251`) — **then** loops `_index_one` over all N articles, **then** commits. Its own comment: *"The ONE gate window for the whole batch opens at this flush … and closes at the commit below."* Batching is the default (`OO_COLLECT_COMMIT_BATCH=8`), so this is the live path.

The gate is a process-wide mutex and collection runs W worker *threads* each with its own session (`/home/user/Open-Omniscience/src/scheduler/runner.py:857-886`), so **at most one worker can be extracting at any instant**; the others block in `Condition.wait()` holding zero CPU. Fetching still parallelises (it happens before the flush); extraction does not. Savepoints do not help — release is gated on `transaction.parent is None` (`writer.py:271-276`).

**Fix shape.** Hoist the pure extraction (extract, sentiment, dates/places/entities) **above** the `session.flush()` and pass it in via the existing `precomputed_*` parameters. No pool required for the first cut; batch-local hoisting alone frees the gate.

**Risk.** **F2** — do not add a batch-scoped keyword cache here. **F5** — `None` vs `[]`. And key any derivative map by content hash or staged-entry index, **never by ORM object identity or `article.id`**: `_store_one` states outright that "a rollback expunges pending objects" and rebuilds a fresh `Article` (`batch.py:390-415`), so an identity-keyed lookup silently misses on exactly the redo path that exists to prevent data loss.

**Corroboration this already shows up in measurement:** `collect_perf._classify()` returns verdict `"writer-bound"` when `max_writer_waiters >= 2 AND writer_total_wait_s_delta > 0` (`/home/user/Open-Omniscience/src/monitoring/collect_perf.py:452-455`), which is exactly this mechanism, and the field logs already report it on the fast box.

---

### ⑧ Raise `OO_REINDEX_COMMIT_BATCH` — but measure it on the real store
| | |
|---|---|
| **Path** | Whole-corpus re-index |
| **Evidence** | **measured on the wrong configuration** |
| **Size** | One environment variable |

Two measured facts that pull in opposite directions:

- `commit_batch=1` is **not** an fsync per article. With WAL + `synchronous=NORMAL`, SQLite defers fsync to checkpoint: strace counted 21 `fsync`/`fdatasync` across ~80 commits on an encrypted store. A/B on `reindex_all_batch`: 181.3 → 167.9 ms/article at `commit_batch=100` — **7.4%**.
- But that was measured on ~7 KB synthetic articles on a plaintext-ish sandbox. The field store is encrypted at 16 KB pages, and `wal_autocheckpoint` is measured in **pages**, so a checkpoint fires after 16 MB of WAL rather than 4 MB. 7% under those non-defaults is not evidence for 7% under the real ones.

**Why it still ranks here:** it is one env var against multi-day builds, and it is the *only* way to populate `apply_commit_s` at all (§2, gap 2). **Risk:** the gate is held across a batch, so a large value hurts a re-index that must interleave with a live scrape — `store.py:846` says so. Keep it modest (100, not 1000).

---

### ⑨ Worker count
| | |
|---|---|
| **Path** | Restore re-index (and anything ⑥ ports it to) |
| **Evidence** | **measured up to 4 workers only** |
| **Size** | One env var to test; a constant to change |

`worker_count` (`/home/user/Open-Omniscience/src/analytics/reindex_parallel.py:180-189`) resolves `OO_REINDEX_WORKERS` first, then returns an **uncapped** `max(0, requested)` if given explicitly, else `min(_MAX_WORKERS_CAP=8, cpu-1)`. **Note the explicit-request branch bypasses the cap entirely** — reading only the constant would mislead you into thinking 8 is a global ceiling. The exclusive import path uses `all_cores_worker_count()` = `min(32, cpu)`.

Measured 91% scaling efficiency at 2/3/4 workers on a 4-core box, which contradicts the cap's stated (unmeasured) rationale — but near-linear scaling to 4 on 4 cores carries almost no information about 16, and the agent that measured it said so before concluding anyway. Also note: on a **2-core** VM, `cpu-1 = 1`, so the pool never engages at all by default.

This moves only the precompute slice, so it is a small lever whichever way it goes.

---

## 4. NON-LEVERS — do not spend effort here

| Non-lever | Why not |
|---|---|
| **A covering index on the per-term keyword lookup** | Measured 1.9× on the *raw* lookup (13 → 7 µs). ~93% of the cost is SQLAlchemy Python overhead, which an index cannot touch. The conclusion holds; its recorded premise does not (see ③). |
| **WAL / `synchronous` / `cache_size` tuning** | `cache_size` at 16× moved end-to-end re-index by **3.6%** (181.3 → 174.7 ms/article) because DB cursor time is only ~5% of the wall clock. And on the collector path SQLite never even sees contention — the serialization is an application-level Python mutex. |
| **Article body decompression** | `compress_content()` has **no callers** anywhere in `src/` — `get_content()` is a plain attribute read. *(Caveat: `merge.py:845` copies the column, so an imported legacy corpus could carry compressed rows.)* |
| **ORM identity-map growth on the long-lived job session** | Measured: `len(session.identity_map)` stayed at **3** across 1,500 articles with per-300 commits. Weak refs + `expire_on_commit` bound it. |
| **Per-article logging** | Every `_LOG` call in `store.py` is inside an exception handler. There is no per-article log line. |
| **The job state-file write** | One small JSON per 300-article batch, not per article. |
| **The `begin_nested` savepoint around when/where/who** | Measured **3.5 µs** of overhead — ~1/100,000 of the extraction cost. It also forces no gate acquisition of its own (the gate is already held) and releases nothing. |
| **IPC / pickling in the pool** | A 35 KB body pickles in 2.9 µs; a 500-article window costs ~1.5 ms of pickling to ship 17.5 MB. The measured 91% pool efficiency is the proof. |
| **Pool spawn churn** | Measured 0.76–1.09 s per 500-article window against ~69 s of work — ~1.2%. Real but small. |
| **Adding collect workers** | Cannot help while extraction is serialized by the gate (⑦). Fix the gate first, *then* revisit. |
| **HTTP/2, more fetch concurrency** | Not the indexing path at all. |
| **`extract_locations` gazetteer cliff — *conditionally*** | Measured 2.6 s/article at ~4,500 cities, but `configs/cities.yml` is **absent** from the tree (only `cities.sample.yml`, 21 cities, ~87 ms). This is a **latent scaling defect**, not a present cost — unless the operator has run `scripts/build_city_gazetteer.py` at its default `--min-pop 100000`. Check before treating it as either. |

---

## 5. What MUST be measured before committing

Each with the cheapest experiment that settles it.

**M1 — What actually dominates per-article CPU on the real corpus.** *Blocks: any prioritisation between VADER, dates, places, and extraction.*
> Sample 200 real articles. Report (a) the share where `normalize_lang(Article.language) == "en"` — i.e. the share that reaches VADER at all — and (b) for those, p50/p95 of `time.perf_counter()` around `score_article`, plus the lexicon-hit count. Then the same per-article timings for `extract_dates` / `extract_locations` / `extractor.extract`. Until (a) exists, no CPU ranking should be quoted (F6).

**M2 — The real precompute/apply split on the *complaining* path.** *Blocks: ⑥.*
> This is ② and needs no separate work: add the `stats` out-parameter to `reindex_all_batch` and run the job over ~500 real articles. Separately, read `apply_index_s`/`apply_commit_s` out of an existing persisted import report — `merge.py:3201` already writes them as `report["reindex_rates"]`. **If they sum to far less than `apply_s`, the dominant cost is neither staging nor commit and the instrumentation itself is incomplete** — which would be the single most important finding available.

**M3 — Both scopes, timed side by side.** *Blocks: knowing which number describes the user's button.*
> Time `index_article` end-to-end on the **same** 200 real articles at `scope="keywords"` and `scope="full"`. The first describes the Clean-up-keywords button; the second describes `backfill_corpus` and live ingest. Note `_resolve_known_language` runs at **both** scopes (`store.py:230-231` docstring: *"The language deduction stays in BOTH"*), so `scope="keywords"` is not as cheap as the ~91% figure implies on a corpus where ~half the articles lack a language tag.

**M4 — `commit_batch` on the encrypted store.** *Blocks: ⑧.*
> Run the background re-index twice over the same 300-article window with `OO_REINDEX_COMMIT_BATCH=1` then `=100`. One env var, no code, and it also populates `apply_commit_s` (which the `=1` run structurally cannot).

**M5 — The worker curve.** *Blocks: ⑨.*
> `OO_REINDEX_WORKERS` bypasses the cap. On the 8-core/20 GB machine, run the same import at `4`, `8`, `16` and read `precompute_s` from `report["reindex_rates"]`. No code change.

**M6 — Gazetteer size.** *Blocks: whether the places cliff is real here.*
> `ls -la configs/cities.yml && .venv/bin/python3.13 -c "from src.catalog.cities import load_cities; print(len(load_cities()))"`

**M7 — The rollup rebuild churn.** *Blocks: ⑤.*
> On a duckdb install, log `refresh_keyword_daily`'s returned `mode` during a re-index, and time `GET /api/database/countries` during vs after.

**M8 — Whether anything is contending for the write gate.** *Blocks: interpreting "low resource use" at all.*
> Sample `write_gate.stats()` (`waiters`, `total_wait_s`) during a re-index with the scheduler running. There is **no mutual exclusion** between the re-index job and `run_idle_maintenance`: `grep -rn 'get_reindex_manager' src/scheduler/` returns nothing, and idle maintenance is gated only on the *collector* being idle. A re-index thread blocked on the gate consumes zero CPU — a second, independent mechanism producing the reported signature, and the two paths can duplicate each other's cleanup work.

---

## 6. Two smaller findings worth recording

**`index_article` writes to the `articles` row and fires the FTS5 sync trigger.** It mutates `sentiment_score`/`sentiment_label` at `scope="full"`, and `_resolve_known_language` sets `detected_language` at **both** scopes. When the value genuinely changes, the `UPDATE articles` fires `article_fts_au` (`/home/user/Open-Omniscience/src/database/fts.py:237-243`) — an FTS5 delete plus re-insert, i.e. the body re-tokenised twice. Measured 3.3–4.6 ms/article at 35 KB on in-memory plaintext (a floor). **It is one-time-per-article, not per-re-index** (verified: a second run on an already-populated article emits no UPDATE) — but that lands squarely on the first big cleanup, and for the ~half of the corpus lacking a language tag it fires at `scope="keywords"` too. Consequence: `optimize_after_bulk`'s docstring claim that FTS optimize is "a near no-op after a keyword-only re-index that never touched articles" is **false** whenever `detected_language` gets written.

**Language deduction never converges for undetectable articles.** `_resolve_known_language` (`store.py:196-205`) persists a result only `if deduced`. Any article the detector cannot classify keeps `detected_language = NULL` forever, so the detector re-runs on it on **every** re-index, permanently. Measured 1.4 ms/article — small, but unbounded repetition that grows with the undetectable tail.

---

## 7. Suggested order of work

1. **①** the backfill wedge — it is a bug, it is the automatic path, and no acceleration fixes it.
2. **②** instrumentation + the job phase field — cheap, and it unblocks M2/M3/M4.
3. **③** the per-call keyword prewarm — safe, measured, and correct the stale test docstring while you are in there.
4. **④** the `extract_dates` cap, **⑤** the epoch churn, **⑧** the `commit_batch` experiment — all small and independent.
5. **Stop and read M1–M4.**
6. Then **⑦** (live ingest gate) and/or **⑥** (pool port) on the evidence, under the F3/F4/F5 constraints.

Nothing above claims a multiplier. The only measured multipliers in this whole investigation are on **isolated steps** (37× on the keyword lookup step; 3.66× on 4 pool workers), and neither has been measured end-to-end at field scale on the path the user is actually running.