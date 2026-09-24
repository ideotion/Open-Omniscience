# The segmented derived index — the 0.5 design for the 1 TB target (§9.2 item 7)

**Status:** DESIGN, for 0.5. One half of §9.2 item 7 of
[`docs/audit/15_FIELD_INSTANCE_SLOWNESS_2026-09-21.md`](../audit/15_FIELD_INSTANCE_SLOWNESS_2026-09-21.md)
("the segmented derived index for the 1 TB target"). The other half — *carrying mention rows
from same-engine backups instead of re-extracting them* (`R24`) — **was built in the same PR**,
and §6 records what building it taught, because two of those findings are inputs to this design.
Nothing in §2–§5 is built. The open choices are `D47` in
[`DECISIONS_2026-09-22_BETA_PATHWAY.md`](./DECISIONS_2026-09-22_BETA_PATHWAY.md).

**It sits on the storage plan of record and does not replace it.**
[`STORAGE_5TB_PLAN.md`](./STORAGE_5TB_PLAN.md) and its refresh
[`STORAGE_5TB_REFRESH_2026-09-07.md`](./STORAGE_5TB_REFRESH_2026-09-07.md) cover the article
TEXT (Phase C, the packed blob store), the full-text index (Phase B) and hash-sharding past
64 TiB; [`5TB_ARCHITECTURE_REVIEW.md`](./5TB_ARCHITECTURE_REVIEW.md) §E covers the derived
READ model (the D1 persisted columnar cache). None of them covers the derived rows' WRITE path —
how `keyword_mentions` and its siblings are *written* once they are billions of rows — and that
is the path the field instance is stuck on. This document is that missing piece.

Claims are tagged **[MEASURED]** (with where), **[ARITHMETIC]**, **[CODE-READ]** or
**[DESIGN]** (a proposal, not a fact).

---

## 1. The problem, in the field instance's own numbers

- **[MEASURED]** (audit §2, §9) the 27.7 GB instance drains its re-index at **~870 articles an
  hour** — 61 days for its 1,282,083-article backlog — and the governor reads
  `writer-saturated` in 200 of 200 samples. It is **write-bound**, not CPU-bound.
- **[ARITHMETIC]** (audit Appendix A) 1 TB holds ~20–25 M fully indexed articles; at ~92
  mentions an article that is **~2 billion `keyword_mentions` rows**.
- **[CODE-READ]** each article's apply inserts ~92 rows into `keyword_mentions`, and every one
  of them lands in **each of the table's secondary indexes** (ten, `src/database/models.py`) at
  a position set by its key, not by time. In a B-tree much larger than the page cache, that is a
  random leaf read and a random leaf write per index per row — the shape the write-bound
  measurement describes. It gets worse as the tree grows, which is why the drain rate falls
  over a long run (audit §9.2 item 5's premise).
- **[CODE-READ]** everything corpus-sized follows the same curve: a re-index after an engine
  change rewrites every row in place; the keyword counters relocate ~100 entries of an
  11 M-entry index per article (`R22`, measured 1.37×–3.70× from deferring them).

PR 5 (`R23`) built the **bulk-build window** — drop the secondary indexes, load in key order,
rebuild once — and could not give it a caller (`D46`), because on a single monolithic table
every choice of span either rebuilds a 2-billion-row index per batch or leaves the live store
without its indexes for days. **That dilemma is a property of the monolith, not of bulk
building.** A segmented index is the shape in which bulk building is the normal write, and
`D46` stops being a question (§4.3).

## 2. The constraint that decides the shape: cross-time recall is sacred

[`5TB_ARCHITECTURE_REVIEW.md`](./5TB_ARCHITECTURE_REVIEW.md) §F forbids *"time-partitioned
tables that default to a recent window"*, *"recency-biased indexes"*, and *"year-sharded storage
a full-corpus query must fan-out-and-miss"*. The refresh (§5.2) then **measured** why
hash-sharding is allowed and time-partitioning is not: *"the fan-out visits every shard with no
per-shard cutoff … Recall of the matching set: 100% in all 44 cells."*

So, **[DESIGN]**, three rules this design never bends:

1. **Every query reads every segment.** No segment is optional, cold, archived, or skipped by
   default; there is no "recent" view.
2. **Segments are cut by WRITE ORDER, and nothing reads that order as time.** Article-insertion
   order correlates with age, which is exactly why no query may use it as a filter.
3. **The segment count is bounded** (compaction, §3.5), so a query's fan-out cost does not grow
   with the age of the corpus. Old rows are not slower per row; they are in bigger segments.

## 3. The design [DESIGN]

### 3.1 A segment

A **segment** holds the derived rows of a SET OF ARTICLES — their `keyword_mentions`,
`article_mentioned_places`, `article_entities` and `article_index_stamps` — together with that
set's **per-keyword summary** (`keyword_id → mention_count, article_count`), in tables of its
own inside the one encrypted store. One article's rows are always in exactly one segment.

**`article_mentioned_dates` stays OUT of segments.** It carries a human verdict
(`datestore.set_status`, confirm/reject) that must stay updatable forever, and it is small. The
merge already treats it apart for the same reason (`_MERGE_NOT_CARRIED`'s rule: *a derived table
may be left to the re-index only while it carries no human decision*).

**Where they live — the refresh already decided it.** *"The corpus/index `ATTACH` split is dead:
WAL forfeits cross-file transaction atomicity. Only disposable or immutable pieces split out."*
A sealed segment IS immutable, so a file-per-sealed-segment layout is not ruled out — but the
first build puts segments as **tables in the main file**, because sealing then commits in one
transaction and nothing has to be recovered. Files are a later option (`D47` (a)).

### 3.2 The head, and sealing

- **The head** is the one mutable segment. Live ingest, the drain and every re-index write
  there, through today's `index_article` unchanged except for which tables it names. Its
  B-trees are small enough to stay resident, which is the whole point: the per-article apply is
  fast again because its indexes fit, not because it did less work.
- **Sealing** turns the head into an immutable segment when it reaches a size (`D47` (c)):
  copy its rows into a new segment's tables **in key order**, build that segment's indexes ONCE
  after the load, compute its per-keyword summary with one `GROUP BY`, register it in a small
  segment catalog, and empty the head — one transaction. **This is `R23`'s bulk build, with a
  bounded span**: the index build is over one head's worth of rows, on a table nothing is
  reading yet, and the live corpus keeps every index it had throughout.

### 3.3 Reads

- **One view per derived table**, `UNION ALL` over the head and every sealed segment, replacing
  the table name in the read paths. SQLite pushes `WHERE` into each branch of a `UNION ALL`
  view, so a keyword lookup becomes one index probe per segment.
- **The read paths that aggregate mentions** — fifteen of them, counted when option (a) was
  ruled (`OPEN_QUEUE.md`, 2026-07-29) — keep their SQL and change their table name. The first
  build step (§5, step 0) introduces the view over ONE segment (today's table), so the rename
  is proved behaviour-neutral before a second segment exists.
- **Counters**: `keywords.mention_count/article_count` stays the global, maintained figure the
  hot paths read. The head keeps per-keyword deltas in a small table; sealing folds them into
  the global in one sorted pass. The honesty envelope (`counter_envelope`) already distinguishes
  *exact* from *estimated*; a head whose deltas are not yet folded is disclosed the way `R22`'s
  open deferral already is, never read as exact.

### 3.4 Re-index, deletion, and an engine change

- **An article in a sealed segment that must change** (re-indexed, deleted, re-stamped) gets a
  **tombstone** — one row, `article_id` — and its new rows go to the head. The views anti-join
  tombstones out of sealed segments. Compaction drops the dead rows for real.
- **An engine change** (the case that today means "re-index everything, in place, for two
  months") becomes **segment-by-segment rebuilds**: build S′ from S's articles under the new
  engine, in bulk, then swap S′ for S in one catalog transaction. The corpus stays fully
  queryable throughout — S serves until S′ replaces it — and `R23`'s disclosure becomes
  *"rebuilding, segment N of M"*, which is a true statement at every moment.
- **The per-article stamp built for `R24`** (§6) is what tells the rebuild which articles are
  already current: a segment whose every article carries the current engine stamp is skipped.

### 3.5 Compaction

Tiered, by size: merge the smallest segments of similar size into one, so the count stays
logarithmic in the corpus. A merge is itself a bulk build (sorted load, indexes once, summary by
`GROUP BY`) and drops tombstoned rows. It is **windowed and resumable** from the first line —
the refresh's amendment to Phase C's GC (§3.2 there: *"a bounded windowed sweep … never one
statement over all references"*) applies here for the same reason, and so does
`temp_store=FILE` on its own connection.

### 3.6 Imports, and where `R24` lands

A **same-engine backup's certified articles** (§6) become **a new sealed segment** directly:
their rows are loaded in key order into fresh tables and indexed once, instead of being
inserted row by row into anyone's B-trees. That is `R24`'s own wording — *"carry their mention
rows in sorted bulk"* — made literal. A foreign-engine backup's articles are re-extracted into
a segment the same way the drain would build one (extract in parallel → sorted runs → bulk
load), which is audit §9.2 item 5's plan with a home to land in.

### 3.7 What it does to backups

With segments as tables in one file (the first build), a backup still copies one file — no
change. With sealed segments as immutable files (`D47` (a) (ii)), a backup copies only segments
it has not copied before, which is the review's recommendation 7 (*"back up only changed
pages"*) at segment granularity, and a restore of a same-engine backup could attach its sealed
segment files without re-writing them at all. That is the strongest argument for files, and it
is a later step for the atomicity reason in §3.1.

## 4. What this resolves elsewhere in the ledger

1. **`D46` dissolves.** "What does a bulk-build window span?" has no good answer on a monolith;
   here every seal and every compaction is a bulk build of a bounded, known size on tables the
   live corpus is not reading. The live store never loses an index.
2. **`D45` (the article-row rewrite) is unaffected** — it is about `articles`, not the derived
   rows — but option (c) there (move `content` out) is the refresh's Phase C, and the two
   compose: Phase C shrinks every article row, segmentation localises every derived-row write.
3. **The drain changes order of magnitude** by becoming segment builds instead of per-article
   applies into a monolith — the audit's §9.2 item 5 claim, which this design gives a place to
   run without stripping the live store.
4. **D1 (the persisted columnar cache) gets a natural unit of refresh:** a sealed segment's
   rollup never changes, so only the head's contribution is recomputed.

## 5. Build order — one PR each, each measured on the operator's instance before the next

0. **The view over one segment.** Every reader of the derived tables goes through a view that
   today covers exactly the current tables; a repo-invariant test fails on any new direct
   reference. No behaviour change, and it is the step that makes the rest reviewable.
1. **Head + seal**, with the catalog, the per-keyword summaries and the counter fold; sealing
   manual at first.
2. **Tombstones**, and re-index/delete of an article in a sealed segment.
3. **Compaction**, windowed and resumable.
4. **Segment-granular engine rebuild**, with *"rebuilding, segment N of M"*.
5. **`R24` as segment import** (§3.6), replacing today's row-by-row carry.
6. **Only then, and only if measured worth it: immutable segment files** (§3.7).

## 6. What building `R24` taught — the inputs to this design

`R24` (2026-09-22) ruled that *"same-engine backups carry their mention rows … option (a)
stays for a FOREIGN engine"*. Built (PR 7; `src/backup/merge.py` `_plan_derived_carry` /
`_carry_derived_rows`, `src/analytics/engine_identity.py`, table `article_index_stamps`), it
needed three refinements the ruling's wording did not contain:

1. **Engine identity is per ARTICLE, not per backup.** A manifest can only name the engine the
   exporter runs *now*; an instance upgraded half-way through its life holds rows from several
   engines under one version string, and nothing recorded which. So `index_article` stamps the
   article in the pass that writes its rows. The identity is a hash of the **bytes** of the
   extraction modules and data files, the optional dictionaries' versions and the switches —
   no hand-bumped constant — with a test that runs a real pass in a fresh interpreter and fails
   on any module or data file it reads that the hash does not cover.
2. **...and per INPUTS.** An article's text, title, languages, date, country and source name can
   change after it is indexed without it being indexed again. The stamp records a digest of what
   the pass read; the merge recomputes it from the incoming row. A stamp is then a statement that
   stays true for ever.
3. **The local dictionary decides which keyword row a mention lands on**, and it resolves by
   term alone while the merge's own map is by term and language. The carry follows the indexer;
   two things a stamp cannot see (an entity upgrade, a collision) are refused instead.

**The acceptance test is a differential** — the same backup restored with the carry and with
option (a) + a re-index must produce identical rows, to the keyword row. Every future segment
operation in §5 should be held to the same bar: *a sealed segment's rows must equal what a
re-index into the head would have written.*

**What `R24` does NOT do, stated so it is not over-read:** no backup made before it carries
anything (none has stamps), so the field instance's **9.86 M orphan keywords (F8)** are not
reached by it; the drain or the prune removes those. What it does reach is every backup made
from now on — most valuably a **fresh-install restore of one's own backup**, which until now
re-extracted every article: on the field instance, the 61-day drain again.

## 7. What this design will not do

- No time-partitioned serving, no recency defaults, no "archive" tier for derived rows (§2).
- No segment skipped by a query, ever — including for speed.
- No second source of truth: the segments ARE the derived rows; the D1 columnar cache stays a
  disposable cache over them.
- No cross-file transaction pretending to be atomic in WAL mode (§3.1).

## 8. What must be measured before step 1 — operator-gated

- **The head size that stays resident** on the field VM's RAM tier: mentions per article, bytes
  per index entry, and the page-cache size the tier gives (64 MB on large). This sets `D47` (c).
- **The fan-out cost**: query latency against the number of segments, on the hot read paths,
  so the compaction target in `D47` (b) is a measurement rather than a guess.
- **A seal's cost** at the chosen head size (sorted load + ten index builds + one `GROUP BY`),
  against the per-article apply it replaces.
- The refresh's still-untaken **DB-10 §6 footprint split** (how the store's bytes divide
  between `articles.content`, the FTS index and the derived rows), because it decides whether
  Phase C or this design is the larger lever on the field instance first.
