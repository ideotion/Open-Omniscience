# Import performance, 2026-08-08 — what the field bundle says, and what changed

Record of an autonomous session run against the operator's diagnostics export taken
**while the import was still running** (`oo-all-diagnostics-20260808092328`), on the
run `imp-20260807T162750Z-352136`.

Companion to the B1–B6 work merged as #896. Read that first: this is its sequel and
it **corrects one of its decisions**.

---

## 1. Where the time actually goes

The run journal answers this exactly, so nothing here is inferred:

| phase | seconds | note |
|---|---:|---|
| `stage_a:verify_and_parity_recover` | 115 | |
| `stage_a:reassemble` | 167 | |
| `stage_a:prepare_corpus_files` | 663 | |
| `prepare_staged:validate` | 1,839 | `quick_check` over a 32.1 GB artifact |
| `prepare_staged:upgrade` | 13 | |
| `snapshot_working_copy` | 7 | |
| **all 19 merge table steps** | **515** | was 15.9 h in the previous run |
| **`search index`** | **51,116 and counting** | **99% of the merge** |

**B1/B5/B6 worked.** The step that used to hang — step 3, `articles` — now takes
**177.8 seconds**. Every table step together is under nine minutes.

**And the cost moved rather than shrank.** B6 took the FTS work out of the article
step and gave it its own step; that step is now the entire import. The operator saw
this as "we got past 3/19, we're now at 18/19" — which is exactly right, and 18/19
*is* the search index (see §3).

## 2. What was wrong with B6's strategy

Two things, and the first is mine to own.

### 2.1 `'optimize'` — the wrong shape of work

B6 ran `INSERT INTO article_fts(article_fts) VALUES('optimize')` after the bulk
load. `'optimize'` merges the **whole index** into a single b-tree, so its cost
tracks the **corpus**, not the import. Measured on the production engine
(sqlcipher3 3.51.1, `page_size` 16384, `auto_vacuum` INCREMENTAL, cache 256 MiB,
`temp_store` FILE), inserting N documents into an index that already held N:

| documents indexed | insert | `'optimize'` | total | ms/doc |
|---:|---:|---:|---:|---:|
| 25,000 | 3.53 | 2.05 | 6.64 | 0.266 |
| 50,000 | 8.35 | 3.00 | 13.29 | 0.266 |
| 100,000 | 18.06 | 9.31 | 29.46 | 0.295 |
| 150,000 | 28.88 | 13.81 | 44.55 | 0.297 |

The insert column is flat per document. The `'optimize'` column is not — it grows
with the total index. **With eighteen backups queued that is eighteen whole-index
rewrites, each larger than the last**, for a query-speed benefit a bounded
incremental merge buys most of.

### 2.2 `hashsize` — a knob nothing in this repo has ever set

FTS5 holds pending index data in memory and flushes a **new level-0 segment** every
time it exceeds `hashsize`. The default is **1 MiB**. Nothing in the tree sets it
(`grep hashsize src/ tests/` → nothing), so a multi-GB index arrives as thousands of
tiny segments, and collapsing them is the crisis-merge cascade whose
`fts5DataRemoveSegment` is the statement dominating the field beat.

Measured, 60k documents into a 60k index, varying only `hashsize`:

| hashsize | total | segments left |
|---:|---:|---:|
| 1 MiB (today) | 12.33 | 19 |
| 4 MiB | 9.43 | 16 |
| 16 MiB | 13.18 | 4 |
| **64 MiB** | **8.40** | **4** |
| 256 MiB | 8.69 | 4 |

It controls segment count as expected, and 64 MiB is the measured optimum — more is
not better, which is why the shipped default is a measured number and not "as much
as we can get". *(The 16 MiB point is inconsistent with both its neighbours at the
same segment count; that is noise, and §6 records the repeat.)*

### 2.3 What the query side cost — the part that decides whether this is allowed

Dropping `'optimize'` is only defensible if search still works. A faster import
that quietly slows every later search is a transfer, not a win. Measured over six
terms spanning the very common to the rare, bm25-ranked exactly as
`fts.search_ids` runs them, on a reopened connection, at 100k+100k:

| arm | build | query median | query max |
|---|---:|---:|---:|
| B6 (`automerge 0` + `optimize`) | 29.10 s | 74.6 ms | 269.1 ms |
| **`hashsize` 64 + no merge** | **15.39 s** | **74.5 ms** | **262.6 ms** |
| `hashsize` 64 + bounded merge | 17.85 s | 72.7 ms | 255.1 ms |

**Query latency is the same** — the middle row is marginally *faster* than the one
that rewrote the whole index. A bounded incremental merge was written and then
**deleted**: it bought 2–3% on query, inside this measurement's noise, for 16% more
build. Raising `hashsize` already leaves the load with ~4 segments, so there is
very little left for a merge pass to collapse, and `automerge` is restored to 4 so
ordinary ingest goes on tidying — FTS5's designed behaviour, and what this app did
for its whole life before B6.

### 2.4 Together

**1.89× faster** at 100k+100k (29.10 s → 15.39 s), against an index verified
**identical**: same `article_fts_docsize` count, same MATCH row count, on identical
content. The pre-existing equivalence test
(`test_the_deferred_build_matches_what_the_trigger_would_have_produced`) still
passes, which is the guarantee that matters more than the speed.

## 3. The counter was lying, and that is why this run cannot explain itself

`_step_watch(con, total, total, "search index", …)` reported the search index
against a denominator that **excluded it**. Its tick publishes `done = index − 1`,
so it published `18` — the same number the last table step (`watches`) publishes on
completion. "18/19" therefore meant either *watches finished* or *the search index
has been running for fourteen hours*, and the journal could not tell them apart. The
run timeline duly reported `stuck_at: 18` with the reading *"workers were idle —
consistent with a wedge or with nothing running"*, which is the wrong story.

Worse, the step's own row progress was invisible: `_window_tick` published through
`runlog.statement`, the **same slot** the per-statement trace overwrites within
milliseconds. So the one step that genuinely knows how far it has got — it walks a
known list of article ids — published nothing that survived.

Both fixed. The search index is now counted as a step of its own, and its tick
carries `N/M articles (phase)`.

## 4. ⚠ What is still unexplained

**The measurements above do not account for the field's numbers, and this must not
be read as a solved problem.**

At any scale measured here the whole search-index step costs ~0.16 ms per document.
The field spent **51,116 seconds and had not finished**. Even assuming the largest
plausible incoming corpus (~1.4M articles, from 32.1 GB staged at the live corpus's
22.5 KB/article), that is roughly **150× more per document** than anything measured
here predicts.

What was ruled out, with the evidence:

- **Not the read side.** `WHERE id IN (20,000 params)` plans as
  `SEARCH articles USING INTEGER PRIMARY KEY (rowid=?)` — a clean seek, verified.
- **Not `'optimize'` running long.** The segment-delete statement is in flight from
  the *first* beat of the step (el 3331.7, ten seconds in), so the cost is the
  insert loop's own crisis merges, not the tail.
- **Not document size.** The corpus's own length report gives mean 660 words
  (~4 KB), which is what the fixture used.
- **Not I/O.** `cpu_s_per_wall_s` is 1.206 and the operator reports the disk near
  idle — this is CPU inside SQLite/SQLCipher, single-threaded.

The leading remaining hypothesis is **absolute index size**: the field's working
copy is ~35 GB against 11.4 GB of RAM (~6.9 GB free), where this sandbox's largest
fixture was 2.4 GB against 15 GB — the whole file fits in the page cache here and
cannot there. That is a *hypothesis*. It was not reproduced, and it is recorded as
one rather than asserted.

**This is the same trap as B6's own lesson, one turn later: a probe's scale is part
of the lookalike.** The instrument in §3 is what settles it — the next run reports
how many articles it has indexed and how fast, so the question stops needing a
guess.

## 5. Deliberately not changed

- **`prepare_staged:validate` (1,839 s per backup).** It is a `quick_check` over
  every page of the artifact. The manifest signature and member hashes prove the
  file is byte-identical to what the *source* wrote; `quick_check` asks the
  different question of whether the source's own database was structurally sound.
  It is 3.5% of the current per-backup cost, it protects irreplaceable data, and
  changing two data-safety-adjacent things in one session is how a corpus is lost.
  Recorded as the next candidate once the FTS cost is measured on real hardware —
  at which point it becomes the *largest* remaining per-backup cost, so it will need
  answering. §6 records a probe of whether its 2 MB default page cache is costing it,
  which would be a free win that changes nothing about the check.

- **The merge direction.** The working copy is built from the *live* corpus and the
  (much larger) incoming one is merged into it, so the FTS index is rebuilt for
  ~1.3M incoming articles while the incoming file **already contains an index for
  them**. Inverting it — base the working copy on the incoming corpus, merge the
  162k live articles in — would cut the FTS work ~8×. It also inverts conflict
  resolution, id remapping and the "the live corpus is never touched" guarantee.
  Recorded as a design note for a cycle that can give it a full skeptic matrix, not
  attempted here.

- **Anything about the 47-ruling 2026-08-07 field-feedback brief.** Different work.

## 6. Probes run and what they settled

| probe | question | answer |
|---|---|---|
| `ftsbench` ladder | do the strategies differ, and does it hold with scale? | yes; 1.6–1.9× across 25k–150k, and B6's per-doc cost is the only one *climbing* |
| `ftsseg` | does `hashsize` control segment count and cost? | yes; 19 → 4 segments, 64 MiB the measured optimum (256 MiB is worse) |
| `ftsquery` | what does skipping `'optimize'` cost at search time? | **nothing measurable** — 74.5 vs 74.6 ms median |
| `ftsrepeat` | is the 1 MiB vs 64 MiB result repeatable? | interleaved n=3; see the PR |
| `ftsvac` | does `auto_vacuum=INCREMENTAL` cost the load? | see the PR |
| `qcheck` | is `validate` slow because of its 2 MB page cache? | see the PR |

Every probe ran on the **production engine** — real sqlcipher3, real pragmas — and
each arm's index was checked for identical document and MATCH counts before its
time was believed.

## 7. Answering "the hardware is idle"

It is, and the reason is structural rather than a missing knob: **the merge is
single-threaded by construction** — one SQLite connection, one writer, one thread.
1.2 cores of 8 is ~15%, which with the sampler threads reads as the 20–30% observed.
RAM at 40% is deliberate: the 2026-08-03 lesson is that the page cache is a
residency dial rather than a throughput lever, and scaling it with RAM is what killed
an earlier field run. Disk idle plus CPU-bound says the work is inside SQLite and the
SQLCipher codec.

So the lever is **less work**, not more parallelism — SQLite permits one writer per
file, and FTS5 has no parallel build and no index-merge API. The post-merge
re-index, which the operator has not yet reached, is the phase that *does* use all
eight cores.
