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
as we can get".

The 16 MiB point disagreed with both its neighbours at the same segment count, which
is the signature of noise rather than of a curve — and the default only rests on
**1 MiB (what FTS5 does today) against 64 MiB (what this ships)**, so that pair was
repeated, interleaved so a machine drifting warmer over the run could not be mistaken
for one arm being faster:

| run | 1 MiB | 64 MiB |
|---|---:|---:|
| 1 | 11.84 s | 8.17 s |
| 2 | 11.97 s | 8.64 s |
| 3 | 12.05 s | 8.34 s |
| **median** | **11.97 s** | **8.34 s** |

**1.44×, with non-overlapping ranges.** The 16 MiB reading was noise; this pair is
not.

### 2.2b The mechanism, measured against the field's own dominant statement

The two sections above are wall-clock. This is the link to the field: the beat shows
`DELETE FROM 'main'.'article_fts_data' WHERE id>=? AND id<=?` — FTS5's
`fts5DataRemoveSegment` — in flight in **3,382 of 3,405** sampled beats. So the claim
"`hashsize` is the lever" is testable directly: raising it must cut the **number of
times that statement runs**. Counted with a trace callback:

| base + new | hashsize | seconds | **segment deletes** | ratio |
|---|---:|---:|---:|---:|
| 30k + 30k | 1 MiB | 6.37 | **304** | |
| 30k + 30k | **64 MiB** | 3.79 | **0** | 1.68× |
| 60k + 60k | 1 MiB | 12.62 | **624** | |
| 60k + 60k | **64 MiB** | 9.32 | **0** | 1.35× |
| 120k + 120k | 1 MiB | 27.20 | **1264** | |
| 120k + 120k | **64 MiB** | 21.80 | **0** | 1.25× |

At the default the count is **linear in documents loaded** (304 → 624 → 1264, each
doubling with the corpus). At 64 MiB, at every scale measured here, the field's
dominant statement runs **zero times** — the load fits in few enough flushes that no
crisis merge fires at all.

**What this does and does not license, and the part that cuts against me.** It
confirms the mechanism is the one the field's beat shows, which the wall-clock
numbers alone could not. But read the ratio column: **the wall-clock advantage
shrinks as the corpus grows** — 1.68× → 1.35× → 1.25× — even though the delete count
stays at zero throughout. The reason is arithmetic rather than mysterious:
eliminating crisis merges removes a fixed *category* of work, and as the corpus grows
the remaining b-tree writes grow with it, so the eliminated share falls. This is the
opposite of the direction a claim like "this will be much bigger in the field" would
need.

So the field effect is bounded from **above**, not below, by these numbers, and I am
not going to guess where it lands. Two further reasons it will be smaller than 1.25×
in kind: at ~1.3M documents on a ~10 GB index a 64 MiB budget cannot reach zero
flushes, so crisis merges still fire (fewer, larger); and merging fewer, larger
segments does not reduce merged *bytes* in proportion to merged *passes*. What the
change is defensible on is the mechanism plus the fact that it costs nothing on the
query side (§2.3) — not on a projected multiplier. The counter shipped alongside it
(§3) is what will actually measure the field.

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

**The two halves scale in opposite directions, and this is the one projection I will
make.** The `hashsize` half shrinks with scale (§2.2b: 1.68× → 1.25×) because it
removes a fixed category of work while the rest grows. The `'optimize'` half grows
with scale, because its cost is set by the **live corpus** — every article already
there, not just the ones arriving — so on a 1.3M-article index it rewrites ~8× more
than it did at 162k, for an import of the same size. Do not read the shrinking
`hashsize` ratio as the trend of the whole change: at field scale the dominant term
is the one that was scaling the wrong way, and it is now simply gone.

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
  answering.

  **The free win I went looking for is not there.** I suspected its 2 MB default page
  cache: `quick_check` walks b-trees rather than reading the file in order, so a
  bigger cache might have paid for itself with nothing about the check changing.
  Measured on a 1,966 MB plaintext corpus with the OS cache dropped between runs:
  **10.04 s at 2 MB, 10.53 s at 64 MB** — no benefit, and the larger cache is
  marginally worse. Refuted, recorded with its numbers so nobody re-chases it.

  What the same probe does show is *why* the field's number is what it is: 196 MB/s
  here on a file that fits in RAM, against **17 MB/s** on the field's 32 GB artifact.
  That is an 11× gap, and it is the cost of walking b-trees across a file far larger
  than memory — inherent to the check, not a tuning miss.

- **The merge direction.** The working copy is built from the *live* corpus and the
  (much larger) incoming one is merged into it, so the FTS index is rebuilt for
  ~1.3M incoming articles while the incoming file **already contains an index for
  them**. Inverting it — base the working copy on the incoming corpus, merge the
  162k live articles in — would cut the FTS work ~8×. It also inverts conflict
  resolution, id remapping and the "the live corpus is never touched" guarantee.
  Recorded as a design note for a cycle that can give it a full skeptic matrix, not
  attempted here.

- **Anything about the 47-ruling 2026-08-07 field-feedback brief.** Different work.

## 5b. ⚠ AMENDED 2026-09-07 — the two non-changes, MEASURED

§5 below left `prepare_staged:validate` and `verify_copy`'s two whole-corpus PRAGMA
checks alone, and every reason given was about RISK. The cost has since become the
majority of what a queued import spends outside the merge, and a decision about
whether to keep paying it cannot be made from an adjective. **Nothing here changes
what those checks do.** They are measured, and the numbers are written down so the
next decision is made on evidence.

### What was measured, and on what

`PRAGMA quick_check` and `PRAGMA foreign_key_check`, on synthetic corpora built
through the project's own `src.testing.corpus_gen`, **plaintext and encrypted**,
**cold** (`/proc/sys/vm/drop_caches` immediately before) and **warm** (immediately
after the cold run, on the same file, while its pages are still resident).
**n = 3 per configuration, interleaved at the round level.** Encrypted arms go
through the real `src.database.connect.connect` factory, so they are real sqlcipher3
at the DB-10 §1b page size.

The two arms differ in PAGE SIZE, and that is faithful rather than a confound: a
staged corpus is exported plaintext and gets SQLite's 4096 default, while the working
copy preserves the live at-rest state and an encrypted store created under DB-10 §1b
is 16384. So "plaintext 4096 versus encrypted 16384" IS the production comparison —
`prepare_staged:validate` walks the first and `verify:quick_check` walks the second.

Machine: 4 cores, 16 GiB RAM, the session sandbox's virtual disk. **That disk is much
faster than the field's**, which is the single most important thing to carry out of
this section — see "what does not transfer" below.

### The numbers

| store | bytes | page size | pages | articles | check | cache | median | min–max (n=3) | s/GiB |
|---|---:|---:|---:|---:|---|---|---:|---:|---:|
| 2048MB-plain | 2,171,211,776 | 4,096 | 530,081 | 76,000 | `quick_check` | cold | 12.80 s | 11.47–13.29 s | 6.3 |
| 2048MB-plain | 2,171,211,776 | 4,096 | 530,081 | 76,000 | `quick_check` | warm | 5.20 s | 5.11–6.09 s | 2.6 |
| 2048MB-plain | 2,171,211,776 | 4,096 | 530,081 | 76,000 | `foreign_key_check` | cold | 6.99 s | 6.78–7.07 s | 3.5 |
| 2048MB-plain | 2,171,211,776 | 4,096 | 530,081 | 76,000 | `foreign_key_check` | warm | 3.99 s | 3.99–4.32 s | 2.0 |
| 2048MB-enc | 2,163,949,568 | 16,384 | 132,077 | 76,000 | `quick_check` | cold | 16.45 s | 16.31–17.35 s | 8.2 |
| 2048MB-enc | 2,163,949,568 | 16,384 | 132,077 | 76,000 | `quick_check` | warm | 12.14 s | 12.11–12.82 s | 6.0 |
| 2048MB-enc | 2,163,949,568 | 16,384 | 132,077 | 76,000 | `foreign_key_check` | cold | 6.22 s | 5.82–6.31 s | 3.1 |
| 2048MB-enc | 2,163,949,568 | 16,384 | 132,077 | 76,000 | `foreign_key_check` | warm | 3.88 s | 3.88–3.95 s | 1.9 |
| 4096MB-plain | 4,336,390,144 | 4,096 | 1,058,689 | 150,000 | `quick_check` | cold | 24.39 s | 24.03–28.39 s | 6.0 |
| 4096MB-plain | 4,336,390,144 | 4,096 | 1,058,689 | 150,000 | `quick_check` | warm | 9.64 s | 9.64–9.85 s | 2.4 |
| 4096MB-plain | 4,336,390,144 | 4,096 | 1,058,689 | 150,000 | `foreign_key_check` | cold | 13.41 s | 13.25–13.44 s | 3.3 |
| 4096MB-plain | 4,336,390,144 | 4,096 | 1,058,689 | 150,000 | `foreign_key_check` | warm | 8.09 s | 7.59–8.16 s | 2.0 |
| 4096MB-enc | 4,316,594,176 | 16,384 | 263,464 | 150,000 | `quick_check` | cold | 33.83 s | 33.65–35.25 s | 8.4 |
| 4096MB-enc | 4,316,594,176 | 16,384 | 263,464 | 150,000 | `quick_check` | warm | 24.66 s | 24.00–24.74 s | 6.1 |
| 4096MB-enc | 4,316,594,176 | 16,384 | 263,464 | 150,000 | `foreign_key_check` | cold | 11.27 s | 11.21–12.10 s | 2.8 |
| 4096MB-enc | 4,316,594,176 | 16,384 | 263,464 | 150,000 | `foreign_key_check` | warm | 7.91 s | 7.86–8.31 s | 2.0 |

Codec multiplier — encrypted over plaintext, per byte, medians of n=3:

| nominal size | `quick_check` cold | `quick_check` warm | `foreign_key_check` cold | `foreign_key_check` warm |
|---|---:|---:|---:|---:|
| 2048MB | 1.29x | 2.34x | 0.89x | 0.98x |
| 4096MB | 1.39x | 2.57x | 0.84x | 0.98x |

Worst spread within a configuration across all sixteen: **1.19x** — which is
what says how much a single run of one of them is worth, and it is why the two earlier
passes described below were not enough.

### What they say

1. **Both checks are LINEAR in bytes.** Doubling the corpus doubles both, with the
   per-GiB rate flat to within the noise (`quick_check` encrypted 8.2 → 8.4 s/GiB,
   `foreign_key_check` encrypted 3.1 → 2.8). So a rate, not a duration, is the
   portable form — which is what the 2026-08-08 `working_copy_bytes` instrumentation
   was added to make possible.

2. **`foreign_key_check` costs about a THIRD of `quick_check`, and is CODEC-NEUTRAL.**
   Encrypted over plaintext, per byte, it is 0.84–0.98x in BOTH regimes — it is
   index-driven, so it never walks the pages `quick_check` walks. Encrypted and cold,
   it is the cheaper of the two by a factor of 2.6–3.0, and it is not the place to
   look first.

3. **THE CODEC MULTIPLIER IS A WARM-CACHE NUMBER, and this refines how
   `merge_diag.walk_probe`'s output should be used.** Warm, `quick_check` encrypted is
   **2.34x / 2.57x** plaintext — an independent corroboration of `walk_probe`'s
   recorded 2.40 / 2.39 / 2.42. Cold, the same comparison is **1.29x / 1.39x**,
   because the encrypted store does a QUARTER as many reads, four times as large, and
   once I/O dominates that pays for most of the codec. `walk_probe`'s docstring
   recommends taking the field's own measured `validate` rate and applying this
   multiplier. **The field's validate rate is disk-bound (17 MB/s on a 32 GB
   artifact), so applying a warm-cache multiplier to it OVER-STATES the encrypted walk
   — by about 1.8x** at the sizes measured here. The docstring is amended accordingly.

### Extrapolation, and what does NOT transfer

At this machine's cold encrypted medians:

```
2048MB-enc     quick_check          8.2 s/GiB ->   17.7 min at 130 GiB
2048MB-enc     foreign_key_check    3.1 s/GiB ->    6.7 min at 130 GiB
4096MB-enc     quick_check          8.4 s/GiB ->   18.2 min at 130 GiB
4096MB-enc     foreign_key_check    2.8 s/GiB ->    6.1 min at 130 GiB
```

The brief that asked for this measurement carried "~17 + 7 minutes per item at 130 GB"
as an estimate of unstated provenance; these rates agree with it closely, which is
worth saying and is not the same as knowing where it came from.

**It is a measurement of THIS DISK.** The field's own `prepare_staged:validate` ran at
**17 MB/s** on a 32 GB artifact against **170–178 MB/s** here (the plaintext cold
`quick_check` rows above, which are the same check on the same kind of file), so the
operator's virtual disk is roughly an order of magnitude slower in this regime and the same
130 GiB would be **hours**, not minutes. Two things follow, and only two:

* the RATES above are this machine's and must not be quoted as the field's;
* the RATIOS (fk_check ≈ a third of quick_check; the codec at ~1.3–1.4x cold against
  ~2.3–2.6x warm) are measured in one regime on both arms, so the regime cancels and
  they are what transfers.

`verify_copy` has still never been observed in the field. When one completes, its own
`verify:quick_check` / `verify:foreign_key_check` sub-timings and `working_copy_bytes`
give the operator's real rates directly, and this section becomes a cross-check rather
than a stand-in.

### Two earlier passes, and why they are not the numbers above

Recorded because the failures are the reusable part. **Pass 1** ran one repetition per
configuration while this session was also running pytest, mypy and a mutation matrix;
its cold codec ratios came out 1.51x / 1.08x / 0.95x / 1.58x — no trend, and a story
was nearly written around the 0.95. **Pass 2** interleaved at the CONDITION level (all
four arms cold, then all four arms warm), which spreads machine drift across arms and
destroys any condition that depends on what ran immediately before: by the time the
first arm's "warm" run happened, three later arms had each dropped the page cache and
read gigabytes through it, so its 2 GiB warm `quick_check` measured 14.6 s against a
genuinely-warm 5.2 s. It was stopped at round 0. Pass 3 interleaves one level out — a
round visits every arm, and within an arm cold and warm run back to back — which keeps
both properties.

### What this does NOT decide

Whether either check should be relaxed, moved or made per-run. That is a data-safety
change, it needs its own reviewed slice, and the structural end-state the notes name
(one working copy per queue run, or an in-place merge inside one transaction with
in-transaction verification) is a full-skeptic-matrix slice of its own. **The
2026-09-07 checkpoint interval K takes the first half of it** — one working copy per
GROUP of K backups, so the whole-file walk is paid once per group instead of once per
backup — with the durability cost stated and the number left to the maintainer.

## 6. Probes run and what they settled

| probe | question | answer |
|---|---|---|
| `ftsbench` ladder | do the strategies differ, and does it hold with scale? | yes; 1.6–1.9× across 25k–150k, and B6's per-doc cost is the only one *climbing* |
| `ftsseg` | does `hashsize` control segment count and cost? | yes; 19 → 4 segments, 64 MiB the measured optimum (256 MiB is worse) |
| `ftsquery` | what does skipping `'optimize'` cost at search time? | **nothing measurable** — 74.5 vs 74.6 ms median |
| `ftsrepeat` | is the 1 MiB vs 64 MiB result repeatable? | **yes** — 1.44×, interleaved n=3, non-overlapping ranges |
| `ftsdel` | does `hashsize` cut the **field's own dominant statement**? | **yes, to zero** at every scale (304/624/1264 → 0) — but the wall-clock ratio *shrinks* with scale, 1.68→1.25× |
| `ftsvac` | does `auto_vacuum=INCREMENTAL` cost the load? | **~5%** (30.43 vs 28.83 s; 15.91 vs 15.17 s) — real, small, **not** the answer |
| `qcheck` | is `validate` slow because of its 2 MB page cache? | **no** — 10.04 s at 2 MB vs 10.53 s at 64 MB. Refuted; the free win does not exist |

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
