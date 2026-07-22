> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — the highest-value confirmed gap: `auto_vacuum=INCREMENTAL` + `page_size=16384` are STILL not set on the fresh-file creation path (`src/database/connect.py:86`), despite §1a being formally ruled (2026-07-17) and §1b's evidence being delivered ("16384 wins every dimension at scale", PR #726). Adaptive backup volume sizing, D2/D3 rollups, the cross-time-recall invariant test, and `journal_size_limit` are all confirmed SHIPPED (this doc was stale on those). See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# 5 TB Architecture — Verify-Before-Trust Review (A14 / P1.7)

**Status:** design review · INPUT for autonomous Session 3 (D1/D2/D3 persisted columnar
store + adaptive backup volume sizing) · every quantitative claim is tagged **[MEASURED]**
(with source), **[ARITHMETIC]** (a shown calculation), or **[EXTRAPOLATION]** (a labelled
projection past what has been measured). The sandbox this was drafted in can only round-trip
a ~6 GB encrypted corpus (see §G), so **all 50 GB / 100 GB / 5 TB figures are extrapolations**
until an operator runs the GAMMA harness.

> Authored by S2 (2026-07-12) from the four sources below + a code audit; every load-bearing
> claim (auto_vacuum never set, the GF(2⁸) 128 GiB parity ceiling, mmap disabled under the
> codec, volume_size plumbed end-to-end, the GAMMA harness) was **re-verified against the tree**
> before this doc was placed. It supersedes nothing in `CLAUDE.md`; it feeds S3.

This review does the thing `docs/design/DATA_ARCHITECTURE_SKELETON.md` deferred: it holds the
skeleton's decisions up against the **5 TB** mandate and the **measured** 2026-07-09 field
failures, and names — concretely, with file:line — what the skeleton is *silent* on, what the
shipped code already does, and the ordered set of changes S3 should make.

---

## A. Purpose + the acceptance bar

**The mandate** (`docs/product/SCALE_ROADMAP.md:7-12`, maintainer verbatim): a live 4–5-day run
grew the corpus to **~100–130 GB**; the app "must therefore be designed to handle **5 TB
databases** with proper indexing, staying **snappy** — snappiness/responsiveness is quite
important, otherwise it will slow or block user adoption, and this app is useless if it is not
used."

**The snappy bar** (`SCALE_ROADMAP.md:105-107`, `docs/ROADMAP.md:43-45`), which every proposal
here is measured against:

- every interactive endpoint p95 **< ~500 ms at 100 GB**;
- **unlock < 2 s**;
- **no UI action blocks > 1 s** without becoming a visible background job;
- background work never freezes the UI.

**The binding constraint carried through everything** (`DATA_ARCHITECTURE_SKELETON.md`,
principle 2+3): *performance must never depend on hiding data*, and *cross-time recall is
sacred* — no feature may bias toward recent data or make old data second-class. §F enumerates
exactly what that forbids at 5 TB.

**Why this review is now on the critical path.** The 2026-07-09 field event was at **11.7 GB**
(`SCALE_ROADMAP.md:30-34`) — 0.23% of the 5 TB target — and it already produced: an OOM crash,
unlock at **981 s then 1,645 s**, `trending-windows` at **467 s/call**, and a backup path that
could not run at all. The target is **~437×** that corpus. A design that is merely "faster" is
not enough; the design must be *slope-flat* in the dimensions that OOM or scan (§G).

---

## B. Single-file SQLCipher at 5 TB — the analysis the skeleton omits

The skeleton commits to "one canonical encrypted SQLite/SQLCipher store" and correctly abandons
time-partitioning, but it never analyses the *physical* behaviour of a **5 TB single SQLCipher
file**. That gap is this section.

### B.1 The corpus at 5 TB (extrapolation from the field ratios)

Field anchors **[MEASURED, `SCALE_ROADMAP.md:32-34` / `corpus_gen.py`]**: 11.7 GB db =
268,241 articles / 3.06 M keywords / 20.9 M mentions.

Linear extrapolation **[EXTRAPOLATION — assumes the field shape holds; the real slope must be
measured per §G]**, ×437.6 to reach 5 TiB:

| Quantity | 11.7 GB (measured) | per GB | **5 TB (extrapolated)** |
|---|---|---|---|
| Articles | 268,241 | ~22,900 | **~117 million** |
| Keywords | 3.06 M | ~262,000 | **~1.34 billion** |
| Mentions | 20.9 M | ~1.79 M | **~9.2 billion** |
| Pages (4 KiB default) | ~2.9 M | — | **~1.3 billion** |

These numbers are the reason "no full scan on any hot path" (`SCALE_ROADMAP.md:78`) is not a
guideline but a hard invariant: any operation whose cost is O(rows) touches ~10⁹ rows.

### B.2 Page cache + the codec: what stays fast vs what dies

Confirmed PRAGMA reality (`src/database/session.py`):

- `journal_mode=WAL`, `foreign_keys=ON`, `busy_timeout=30000`, `synchronous=NORMAL`,
  `temp_store=MEMORY`.
- **`cache_size` = 64 MiB per connection** by default (`OO_SQLITE_CACHE_MB`), and it is **per
  connection** — worst case ≈ `cache_mb × (pool_size 8 + max_overflow 64)` = **72 × 64 MiB ≈
  4.6 GB** of page cache if every pooled connection is held warm.
- **`mmap_size` is disabled under the SQLCipher codec** — set only when `"sqlcipher" not in
  type(conn).__module__` (`session.py:124-127`). This is correct and load-bearing: **every page
  read passes the AES decrypt** (there is no mmap fast path through the codec). A page cache miss
  = a decrypt.

At 5 TB the page cache is a **rounding error**: 64 MiB caches ~16,384 of ~1.3 billion pages
(**~0.001%**) **[ARITHMETIC]**. Raising `cache_size` does not change the asymptotics — the lever
is *plan shape*, not cache size. Concretely:

**Stays fast at 5 TB** (cost independent of corpus size, or index-only):
- **Counter reads** — `Keyword.mention_count` / `article_count` are maintained columns, O(1) per
  keyword.
- **Index-only / covering range scans** — `ix_mention_date_keyword (observed_on, keyword_id,
  count)` and `ix_mention_covering (keyword_id, article_id, count, observed_on)`
  (`src/database/maintenance.py`) turn the trending aggregation into an index-only range scan (no
  heap page = no decrypt per row). `ix_article_observed` on `coalesce(published_at, created_at)`
  makes the date-range probe index-only.
- **FTS5 MATCH** — an inverted-index lookup, not a scan.

**Dies at 5 TB** (O(rows) heap reads, each a decrypt):
- **Any bare `SCAN <table>`** on `articles`/`keyword_mentions`. The measured proof: the date-range
  probe wrote a bare `SCAN articles`, dragging every ~35 KB article row (the `content` column)
  through the codec — **4,775 ms × 154 calls = 735 s** at 11.7 GB (`maintenance.py`, #588).
  Classification rule to keep (slowquery lesson, `CLAUDE.md`): `SCAN … USING [COVERING] INDEX` is
  healthy; a **bare `SCAN`** is the smell.
- **Any `COUNT(*)` over a corpus-scaled table** — measured `SELECT count(*) FROM keyword_mentions`
  = 724 ms × 172 = 124 s (`ROADMAP.md`, P1.3). Must be served from the maintained counters, never
  computed.
- **Any Python-side full-row materialization** — the keyword→articles join that pulls whole
  article rows through the codec (the "column-order trap," `CLAUDE.md` Lessons; the backup's own
  `_corpus_facts` deliberately scans `articles ORDER BY hash` = the index, *not* `ORDER BY id` =
  heap, `stream_backup.py:449-451`, exactly to avoid this).

Tie to the field failures: `trending-windows` 467 s, map/ring GROUP BY ~150 s/call, `map-coverage`
24 s, `/latest` 12.6 s — all are the "dies" class, and all have since been moved to
counter/rollup/index serve (P1.4/P1.10/P1.11). The **rule for S3**: before any new hot-path read
ships, its `EXPLAIN QUERY PLAN` must show no bare `SCAN` of a corpus-scaled table.

### B.3 A CREATE-time seam the skeleton missed: `page_size`

`page_size` is **never set** anywhere in the tree — grep finds it only *read*
(`storage.py`, `api/database.py`, `diagnostics.py`, `benchmark.py`), never written. So every
corpus is created at the SQLCipher default **4096 bytes**. A larger page (8192 / 16384) means
fewer pages, shallower b-trees, and fewer codec ops per range scan — but like `auto_vacuum` (§C)
**it can only be set before the first table is created**. This is an irreversible CREATE-time seam
and belongs in the same decision as §C. **Ruling flagged for S3 / maintainer** — it is cheap now
(a PRAGMA in `connect.py`'s fresh-file branch) and infeasible to retrofit at 5 TB (needs a full
VACUUM). Recommendation: measure 4K vs 16K on the GAMMA range-scan p95 before committing, since
bigger pages also inflate the per-connection cache's byte cost.

### B.4 The write path at 5 TB

- **Single-writer gate** (`src/database/writer.py`, wired in `session.py`): all ORM writes
  serialise through one in-process mutex; raw writes (VACUUM, FTS rebuild) take `write_lock()`.
  This is the correct model at any scale (SQLite is single-writer regardless), and it is what makes
  the backup's "writes paused" window meaningful (§D).
- **Writer-gate saturation is already the measured field pain** — 847,351 s cumulative write-wait /
  **22% of worker-time** / 234,551 contentions / max single wait **438 s** (`SCALE_ROADMAP.md:28`,
  P0.3/P1.8). Fixed by collector write-batching (P1.8, shipped) — one write transaction per batch,
  `index_article(commit=False)`. At 5 TB the batching stays load-bearing; S3 must not regress it.
- **WAL growth under continuous collection** — the P0.3 fix added an inter-pass
  `wal_checkpoint(TRUNCATE)` via `write_lock()`. At 5 TB an un-checkpointed WAL is a runaway (the
  GAMMA `wal_bench` measures `wal_peak_bytes` vs `wal_bytes_after_checkpoint`). Keep TRUNCATE (not
  PASSIVE) between passes so the WAL floor resets.
- **Encrypted-page fsync cost** — `synchronous=NORMAL` (safe with WAL) is correct; every committed
  page is re-encrypted with a fresh IV on write, so incremental backup reuse (§D) applies to
  **unmodified** pages only.

---

## C. VACUUM infeasibility + the `auto_vacuum` hygiene gap (DB-10)

This is the sharpest **irreversible-seam** finding in the review.

### C.1 Full VACUUM is infeasible at 5 TB

`vacuum_database()` (`src/database/maintenance.py`) does a real `VACUUM`: it **rebuilds the entire
file**, takes the writer gate for the whole duration, and needs **~2× the file size in free disk**
(SQLite writes a full copy then swaps). At 5 TB that is a ~10 TB scratch demand and a multi-hour
exclusive-writer stall — infeasible and blocking. So the app's only space-reclaim tool does not work
at the target scale. The UI still exposes it ("Compact database (VACUUM)", `index.html`) — S3 should
gate/hide it above some size and point at incremental vacuum instead.

### C.2 `auto_vacuum` / `incremental_vacuum` are NOT set anywhere — space never comes back

**[MEASURED — grep, re-verified 2026-07-12]** there is **no `auto_vacuum` or `incremental_vacuum`
PRAGMA anywhere** in `src/` (only the full-VACUUM tool and read-only `freelist_count` reporting).
The telltale is in the storage diagnostic itself: `src/monitoring/storage.py` computes
`free_bytes = page_size * freelist` with the comment **"reclaimable only via (in)cremental
vacuum"** — i.e. the code *knows* those pages are stranded.

Consequence at scale: deleted pages — from **pruned keywords** (`prune_orphan_keywords`), the
**delete-then-reinsert** on every re-index (`CLAUDE.md` "delete-then-reinsert epoch trap"),
**near-dup churn**, and newsletter re-imports — go on the freelist and **never return to the
filesystem**. This is **DB-10** (`ROADMAP.md`). At 5 TB, with continuous re-indexing, the freelist
is a monotonically growing dead-weight the app cannot reclaim. Growth itself becomes a scale bug
(`SCALE_ROADMAP.md:109`: "130 GB in days ⇒ growth itself is a scale bug").

### C.3 Why this must be decided NOW (the irreversible part)

`auto_vacuum` (and `page_size`, §B.3) **can only be set on an empty database, before the first
table is created** — retrofitting requires a full VACUUM, which §C.1 just showed is infeasible at
5 TB. So the choice is genuinely one-way: a corpus created without `auto_vacuum=INCREMENTAL` **can
never get bounded reclaim** without a rebuild it cannot afford. Every new field corpus created
before S3 lands is permanently stuck on the full-VACUUM-or-nothing path.

**Ruling flagged for S3 / maintainer (this is the highest-leverage decision in the review):**

- Set **`PRAGMA auto_vacuum = INCREMENTAL`** in `connect.py`'s fresh-file creation branch, before
  any table exists, alongside the `page_size` decision (§B.3). `INCREMENTAL` (not `FULL`) so reclaim
  is a *bounded, scheduled* `PRAGMA incremental_vacuum(N)`, never an unbounded auto-rewrite on every
  commit.
- Add a bounded, off-peak `PRAGMA incremental_vacuum(N)` to the maintenance/deadline regime (P1.12,
  now shipped as the collector-idle maintenance — S2.2) so the freelist is drained in slices under a
  soft budget — the same resumable-watermark shape the reconcile/prune passes already use.
- **Honest limit to document:** this fixes **new** corpora only. Existing field corpora keep the
  full-VACUUM-or-nothing path; there is no honest cheap retrofit at scale. That asymmetry is itself
  the argument for deciding before 0.2 tags and more corpora exist in the wild.

---

## D. Backup windows + the parity ceiling (DB-9 / F6) — the adaptive volume sizing S3 will build

### D.1 The concrete ceiling (measured code + arithmetic)

The Reed-Solomon erasure code is over **GF(2⁸)** (`src/backup/parity.py:44`): at most **255**
data+parity volumes, enforced by `_GF_LIMIT = 256` and a `VolumeError` when `n + m >= 256`. Parity
count **M = `parity_count` or `max(1, ceil(parity_fraction · N))`** with default `parity_fraction =
0.1` (`parity.py:250`). Volume size default = **512 MiB** (`VOLUME_SIZE_DEFAULT`, `volumes.py:43`).

**[ARITHMETIC]** At 512 MiB/volume the ceiling is **255 × 512 MiB = 127.5 GiB ≈ 128 GB** (confirmed
in the module comment, `parity.py:44`). Data-volume counts at fixed 512 MiB:

| Corpus | N = corpus ÷ 512 MiB | M = ⌈0.1N⌉ | N+M | vs 255 |
|---|---|---|---|---|
| 11.7 GB (field) | ~24 | 3 | 27 | ok |
| 100 GB | ~200 | 20 | 220 | ok (at the edge) |
| 1 TB | ~2,000 | 200 | 2,200 | **FAIL — `VolumeError`** |
| 5 TB | ~10,000 | — | — | **FAIL — `VolumeError`** |

This is **DB-9 / F6** (`ROADMAP.md`, `SCALE_ROADMAP.md:216-222`). Precise failure mode today: above
~128 GB the backup **raises at the `write_parity` step**; because finalize is crash-safe (it builds
the signed+parity manifest in memory and swaps the canonical manifest in one atomic replace,
`stream_backup.py:879-911`), **the previous backup survives** — but you get **no new backup** above
the ceiling. Not data loss; a silent inability to make a fresh backup.

### D.2 What is already plumbed (so Option A is cheap)

`volume_size` flows end-to-end already: `write_stream_backup(volume_size=…)` (`stream_backup.py:766`)
→ `_EmitState.volume_size` (:543) → `_emit_member` slices by `st.volume_size` (:593-602). Two
properties make larger volumes free of the usual costs:

- **OOENC2 has no 2 GiB cap** — it is a chunked STREAM container; slicing/encryption is a 4 MiB-chunk
  stream (`_CHUNK`), so a 25 GiB volume costs the same RAM as a 512 MiB one.
- **Parity RAM is band-bounded, independent of volume size** — 32 MiB bands, `(M+1)` bands to encode
  / `(erased+1)` to decode (`parity.py`). Bigger volumes do **not** raise parity RAM.

So the only thing standing between the code and 5 TB is *how `volume_size` is chosen* — today it
defaults and never adapts.

### D.3 Option A (RECOMMENDED, cheap) — adaptive volume sizing

Choose the volume size so the **volume count stays bounded** rather than the size:

```
TARGET_VOLUME_COUNT = 200          # env OO_BACKUP_TARGET_VOLUMES
volume_size = max(VOLUME_SIZE_DEFAULT, ceil(corpus_bytes / TARGET_VOLUME_COUNT))
```

Compute it in `write_stream_backup` after `corpus_bytes`/`side_bytes` are known
(`stream_backup.py:817-818`), before building `_EmitState`. **[ARITHMETIC]** with
`TARGET_VOLUME_COUNT = 200`:

| Corpus | volume_size | N (≈) | M = ⌈0.1N⌉ | N+M | vs 255 |
|---|---|---|---|---|---|
| ≤ 100 GB | 512 MiB (floor) | ≤ 200 | ≤ 20 | ≤ 220 | ok — **byte-identical to today** below 100 GB |
| 1 TB | ~5.12 GiB | ~200 | 20 | 220 | ok |
| 5 TB | ~25.6 GiB | ~200 | 20 | 220 | ok |

The elegant invariant: **N stays ~200 and N+M ~220 at every scale**, comfortably under 255, while
RAM stays flat (§D.2). Add a **hard safety guard**: if `N + M` would exceed a margin (e.g. 240 —
leaving headroom for a higher `parity_fraction`), grow `volume_size` further, and only if that is
undesirable fall to Option B. Below 100 GB the floor keeps behaviour byte-identical, so no existing
test or field backup changes.

**The trade-off, quantified (state it honestly):**

- **Coarser incremental re-emit granularity.** Reuse is per-slice by `plaintext_sha256`
  (`stream_backup.py:614-660`): a single changed 4 KiB page forces re-emit of its *whole volume*.
  **[ARITHMETIC]** at 512 MiB a change-cluster costs 512 MiB re-emitted; at 25.6 GiB (5 TB) it costs
  25.6 GiB — **50× coarser**. For a continuously-collecting corpus whose writes scatter
  (keyword/mention churn), an incremental backup that re-emits a few hundred MiB at field scale could
  re-emit **tens of GiB** at 5 TB. Bounded above by `N × volume_size` = a full re-emit; the win over
  "no incremental" is still large, just coarser.
- **Larger corrupt-volume blast radius (only past the parity budget).** Parity still recovers ≤ M =
  20 lost/corrupt volumes exactly; the concern is the **> M** tail, where an unrecoverable volume now
  loses 25.6 GiB instead of 512 MiB.

Neither trade-off is a correctness risk; both are efficiency/robustness. Option A is the right default
because it is a ~10-line change on already-plumbed machinery and fixes DB-9 outright.

### D.4 Option B (fallback, bigger rewrite) — GF(2¹⁶) erasure

Widen the field to **GF(2¹⁶)** → **65,535-volume ceiling**, letting 5 TB keep **512 MiB–2 GiB**
volumes (~2,500–10,000 volumes) and thus **fine incremental granularity**. Cost: rewrite
`parity.py`'s field arithmetic (16-bit log/exp tables, 2-byte symbols, ~2× parity compute and band
memory, a 16-bit Cauchy inverse). Keep this **only as the fallback** if the GAMMA measurement (§G)
shows Option A's coarse re-emit is unacceptable on a real continuously-collecting 5 TB corpus. Do not
build it speculatively.

### D.5 The backup write-gate window at 5 TB

The writer gate is held for the **entire corpus member stream** — `with src.freeze()` wraps both
`_emit_member(corpus)` and `_corpus_facts` (`stream_backup.py:829-850`), and `gate_held_s` is the
measured duration reported honestly. Because reuse is content-hash-based, the corpus is **fully read
+ SHA-256'd inside the gate even when nothing changed** (raw SQLCipher bytes, no codec decrypt — the
raw file is streamed as-is).

**[EXTRAPOLATION]** a full 5 TB read+hash at ~500 MB/s ≈ **2.9 hours**; at ~150 MB/s ≈ **9.5 hours**
— collection paused throughout. For an **attended** backup (the P0.1 posture) this is acceptable *if
disclosed*, which it is (`gate_held_s` + the "corpus (writes paused)" phase). Two concrete reductions
for S3 (both are the F10/F11 riders S2.1 traced but declined as backup-path-risk — S3 owns the backup
territory and can revisit them with the ZETA lessons):

1. **Move `_corpus_facts` out of the gate window** (audit F11): today the gate is held across the
   facts' full `COUNT(*)` + `articles` scan too. Note the correctness constraint S2.1 documented: the
   article-hash **commitment must match the streamed at-rest bytes**, so any move must recompute facts
   against the *frozen* snapshot, not the live (moved-on) file. At 5 TB the facts scan is a small
   fraction of the multi-hour byte stream, so the win is modest — measure before spending the risk.
2. **`_drain_wal` connection-before-gate** (audit F10): check out the pool connection before taking
   the gate so the order matches workers (connection→gate), removing the bounded (`pool_timeout`)
   stall under heavy concurrent collection. Best-effort today (WAL rides as a member on failure).

The inherent full-read cost cannot be avoided by content-hash incremental. A future block-dirty-
tracking scheme (SQLite's page change counter, or replaying the WAL frame log) could shrink the gate
window to *changed* pages, but that is a larger design (§H item 7); until then the **interim path
stays**: *app stopped → filesystem-copy the data folder* (encrypted at rest) is the only sub-full-read
backup at 5 TB.

---

## E. The derived layer at 5 TB (hand-off to S3)

The skeleton's speed strategy is "maintained counters + a derived columnar read-model." At 5 TB the
*in-memory* form of that read-model is not viable and the *persisted* form (D1) becomes **required,
not optional** — the roadmap already promoted it (`SCALE_ROADMAP.md:80-82`).

- **Why in-memory dies.** The opt-in in-memory rollup (`rollup_serve`, change-gated per P1.10) is
  built **once per process in a background thread** and serves windowed trending. It reads the whole
  `keyword_mentions` table on build. The field already caught it mid-build: `trending-windows` **467
  s/call while "the in-memory rollup was STILL BUILDING at export"** (`SCALE_ROADMAP.md:46`), and 62
  calls / 3,286 s of TTL churn on the 12:14 boot. At the extrapolated **~9.2 billion mentions** (§B.1)
  a per-boot rebuild is minutes-to-tens-of-minutes of I/O *and* the rollup's own RAM grows with the
  corpus — untenable every unlock.
- **Therefore D1 (persisted encrypted columnar store) is required.** It survives restarts (no per-boot
  rebuild) and refreshes **incrementally**, gated on the **corpus-epoch mechanism that is already
  shipped** (P1.6, `src/analytics/corpus_epoch.py` exists; `derived_meta` + `bump_corpus_epoch` wired
  into re-index/prune) plus the append id-tail (a pure epoch gate would freeze the rollup during
  collection — the shipped serve already gates on epoch OR append-tail, P1.10). So D3's incremental
  refresh has its change-signal already.
- **The blocker is operator-gated, not design-gated (DB-3).** The persisted store needs the per-OS
  **httpfs crypto extension**; the bundling attempt hit `extensions.duckdb.org` **not in the network
  egress allowlist (403)** — no checksum fabricated, in-memory fallback stays (`ROADMAP.md`,
  `SCALE_ROADMAP.md` Ruling-gated #2). The DuckDB-native-GCM hope was **refuted on 1.5.4** (writes
  refuse without `LOAD httpfs`; the only no-httpfs path is the explicitly *unsafe* mbedtls = forbidden,
  `CLAUDE.md` P2.4). So S3 builds the D1/D2/D3 machinery **now, gated behind
  `secure_crypto_available()`** (CI may install the extension; local skips honestly; never relax the
  gate, never fabricate a checksum) — the per-OS binaries themselves stay a networked-operator step.
- **What S3 builds against the gated store:** **D2** `keyword_daily` rollup builder +
  `windowed_top_terms` serve primitives, and **D3** epoch-gated incremental `refresh_keyword_daily`
  (both designed in 5A-bis; the epoch guard is already tested). The persisted store is a **disposable
  cache**: canonical store stays truth, a cold/missing store falls back to the live query (slower,
  never wrong), excluded from backups.

---

## F. Cross-time recall is SACRED — the binding constraint at 5 TB

`DATA_ARCHITECTURE_SKELETON.md` (principle 3) and `ROADMAP.md` make this a hard invariant: *no
partitioning that makes old data second-class.* At 5 TB the pressure to partition by time will be
strong; this section pins what that forbids and what it allows, so S3 can codify it (§H item 8).

**FORBIDDEN** (each would make the historical half of the corpus slower or unreachable):

- **Time-partitioned tables that default to a recent window** — e.g. `keyword_mentions_2026` +
  `_archive`, where a full-corpus query must opt in to reach old shards. The field proves the value at
  stake: dated coverage back to **1995** (`SCALE_ROADMAP.md:61`, "cross-time recall real").
- **Recency-biased indexes / default `WHERE observed_on > cutoff`** on hot paths — anything that makes
  "since 1995" cost more than "last 30 days."
- **Age-based pruning/eviction of *indexable* rows** — dropping or cold-tiering mention / analytic /
  metadata rows by age (that is exactly the "second-class old data" the principle forbids).
- **Year-sharded storage a full-corpus query must fan-out-and-miss** — the abandoned
  time-partitioning, unless provably byte-identical with no recency bias (it is not, so it stays
  abandoned).

**ALLOWED** (all age-agnostic; all present or shipped):

- **Maintained counters** — O(1), no time bias.
- **A fully-present derived columnar read-model** — every article present + searchable at all times;
  the read-model is a *speed cache over the whole corpus*, not a recency filter. Windowed rollups are
  fine because the window is the *user's query*, not a storage boundary.
- **Tiered RAW-TEXT retention to a *local* archive** while the **search index + every
  mention/analytic/metadata/provenance row stays hot** (default OFF): opening a cold article is a
  transparent local read, reversible, and *performance does not depend on it*. This is the one
  disk-space escape hatch that respects the principle — it relocates bytes, never reachability. (Needs
  the K5 WARC archive first; not S3's job, but S3 must not foreclose it.)
- **Incremental vacuum (§C)** and **adaptive volume sizing (§D)** — both age-agnostic.

---

## G. Measurement plan for S3 (what to run on an operator machine)

The GAMMA harness (#601) is the instrument: generator `src/testing/corpus_gen.py` +
`scripts/generate_scale_corpus.py`, runner `src/testing/scale_bench.py` + `scripts/run_scale_bench.py`.
It measures exactly the field failures: **cold+warm unlock wall**, **backup wall + peak RSS +
gate_held_s**, **restore round-trip**, **hot-endpoint p50/p95**, **WAL growth**, and an
`acceptance_gate` that **asserts the corpus is ENCRYPTED** (a plaintext run omits every codec cost and
must never gate a decision).

**Sandbox limit (why 50 GB+ is operator-only).** The S2 sandbox has **~29 GB free** (measured). A full
round-trip needs cold-copy (1×) + backup volumes (~1×) + parity (~0.1×) + restore staging + merge
working copy (~2×) ≈ **3–4× corpus** in scratch, so the sandbox caps at a **~6 GB encrypted** corpus.
**50 GB / 100 GB / 5 TB are operator-machine-only.**

**Run (operator, app stopped, offline):**

```bash
# 1. Generate an ENCRYPTED 50 GB corpus (then repeat at 100 GB):
python scripts/generate_scale_corpus.py \
    --out /mnt/scratch/oo-50gb/open_omniscience.db \
    --target-size 50GB --passphrase "$OO_PASS"

# 2. Full bench with the acceptance gate + an RSS bound:
python scripts/run_scale_bench.py --corpus /mnt/scratch/oo-50gb \
    --corpus-passphrase "$OO_PASS" ...

# 3. The OFFICIAL backup number = a fresh-process backup-only run.
```

(Confirm the exact flags against `scripts/run_scale_bench.py --help` at run time.)

**Numbers to capture (per corpus size):** cold + warm unlock wall (P0.4); backup wall + peak RSS +
`gate_held_s` + `volumes`/`volumes_reused`/`volumes_emitted` (P0.1, and — with Option A — confirm N
stays ~200); restore wall + peak RSS; verify ok; each endpoint's `p50_ms`/`p95_ms`
(`top`/`trending-windows`/`latest`/`graph`/`status`); WAL peak + after-checkpoint bytes.

**How to extrapolate to 5 TB — measure the SLOPE, not the absolute (the discipline that makes this
honest):** run **both** 50 GB and 100 GB and compare.

- **RSS must be FLAT** across 50→100 GB. Backup/restore peak RSS is band-bounded by design (§D.2); if
  it *rises* with corpus size, a whole-set materialization is hiding somewhere and **it will OOM at
  5 TB** — that is the exact 2026-07-09 signature (RSS 10.6 GB > VM). A flat slope is the pass; a
  rising slope fails regardless of the absolute number.
- **Endpoint p95 must be FLAT** across 50→100 GB. If any p95 *grows* with corpus size, a bare `SCAN`
  survives on a hot path and will blow the 500 ms bar at 5 TB. Flat p95 = counter/index/rollup-served
  (the goal); rising p95 = a scan to hunt down.
- **Unlock/backup/restore walls scale ~linearly** with bytes (read-bound), so 5 TB ≈ (100 GB wall) ×
  50 **[EXTRAPOLATION]** — acceptable for attended backup/one-time unlock, *provided* warm unlock is
  < 2 s (the P0.4 fix made `ensure_fts` rebuild-only-when-needed: 28.6 s → **0.002 s**, warm unlock
  **0.012 s** on a 112k/2.7 GB synthetic corpus; the bench's warm re-run must confirm this holds at
  100 GB).

**Acceptance thresholds (the pass/fail S3 records against):** warm unlock **< 2 s**; backup peak RSS
**bounded and flat** (a few hundred MiB, corpus-independent); interrupt+resume proven; verify
`ok:true`; every endpoint **p95 < 500 ms with flat slope**; WAL bounded after checkpoint. The
maintainer's **live-corpus run remains the final gate** — synthetic evidence never closes a P0.

**Sandbox data point [MEASURED, S2, 2026-07-12].** A GAMMA run on a **960 MB ENCRYPTED** synthetic
corpus (40,000 articles / 360,000 keywords / 3.12 M mentions; `acceptance_gate` confirmed
`corpus.encrypted == true`) in the S2 sandbox, via the same `scripts/run_scale_bench.py` operators use:

| Metric | Measured | Bar |
|---|---|---|
| Cold unlock (builds `ix_article_observed` + ANALYZE on a fresh copy) | **7.04 s** | one-time |
| **Warm unlock** | **0.021 s** | < 2 s ✅ |
| Endpoint p95 — `status`/`scheduler`/`top`/`trending-windows`/`latest`/`graph` | **4.97–6.26 ms** (all) | < 500 ms ✅ |
| Backup wall (oo-volumes-2 + parity, 4 volumes) | 28.0 s | attended |
| **Backup peak RSS** (`ru_maxrss` Δ = **99 MB**) | **bounded** (564.9 MB incl. baseline) | flat/bounded ✅ |
| Backup `gate_held_s` (writes paused) | 13.2 s | disclosed |
| WAL peak in a 5,000-write burst / after checkpoint | 4.1 MB / **0 B** | bounded ✅ |

This is a **methodology check + a single-size anchor, not a scale claim** — one corpus size cannot show
the *slope* §G requires, and the machine has RAM > corpus so the cold-unlock disk-I/O term is
understated (the report discloses this). What it *does* confirm: the harness runs end-to-end on an
encrypted corpus; warm unlock and every hot endpoint are already index/counter-served (ms, not the
"dies" class); backup RSS is bounded (banded parity working); WAL checkpoints to zero. The field 100 GB
numbers remain the real anchors; the 50 GB↔100 GB **slope** run (S3, operator) turns this single point
into a 5 TB projection.

---

## H. Recommendations for S3 (ordered; each tagged)

Tags: **[buildable-now]** = S3 can build + test in-repo today · **[operator-gated]** = needs a
networked/large-disk operator machine · **[ruling-needed]** = an irreversible/maintainer call first.

1. **Adaptive volume sizing — Option A** *(fixes DB-9/F6).* **[buildable-now]**
   `volume_size = max(VOLUME_SIZE_DEFAULT, ceil(corpus_bytes / TARGET_VOLUME_COUNT))`,
   `TARGET_VOLUME_COUNT=200` (env `OO_BACKUP_TARGET_VOLUMES`), computed in `write_stream_backup` before
   `_EmitState`; add the `N+M ≤ 240` safety guard that grows `volume_size` further. Byte-identical
   ≤ 100 GB. Pin with a test that forces a high slice count (tiny `volume_size` + many members — no
   real TB needed) and asserts `N+M < 255` and adaptive sizing kicks in above the floor. **Highest
   leverage, lowest cost.**

2. **Shrink the backup gate window** *(audit F10/F11).* **[buildable-now, backup-path — full ZETA
   lessons apply]** Move `_corpus_facts` after `write_lock` release **while preserving the commitment↔
   frozen-bytes match** (S2.1's F11 correctness constraint); check out the pool connection before the
   gate in `_drain_wal`. Re-measure `gate_held_s` in the bench; the win is modest vs the byte stream,
   so measure-first.

3. **`auto_vacuum=INCREMENTAL` (+ decide `page_size`) at CREATE, + a bounded off-peak
   `incremental_vacuum` pass** *(fixes DB-10).* **[ruling-needed]** then **[buildable-now]**. Set the
   PRAGMAs in `connect.py`'s fresh-file branch *before the first table*; add the slice-budgeted reclaim
   pass to the collector-idle maintenance regime (S2.2). **Irreversible seam — decide before more field
   corpora exist.** Document: new corpora only; no cheap retrofit at scale. Gate/hide the full-VACUUM UI
   button above a size threshold.

4. **D1 persisted encrypted columnar store + D2 rollup + D3 epoch-gated refresh.**
   **[buildable-now behind `secure_crypto_available()`]** + **[operator-gated]** for the binaries
   (DB-3). corpus-epoch is already shipped; CI installs httpfs, local skips honestly, never relax the
   gate, never fabricate a checksum. This is the item that makes the derived layer survive at 5 TB
   (§E).

5. **GAMMA slope measurement at 50 GB and 100 GB, encrypted.** **[operator-gated]** Run §G; record
   RSS-slope and p95-slope; a flat slope on both is the 5 TB confidence, a rising slope is a bug to
   file. This also validates recommendation 1's `N≈200` claim on a real corpus.

6. **Option B (GF(2¹⁶) erasure).** **[ruling-needed / deferred]** Build **only if** recommendation 5
   shows Option A's coarse incremental re-emit is unacceptable on a real continuously-collecting 5 TB
   corpus. Not speculative.

7. **Block-dirty-tracked backup (shrink the full-read gate window).** **[design-only / future]**
   Investigate SQLite's page change counter / WAL frame log to back up only *changed* pages, cutting
   the multi-hour §D.5 gate window. Larger design; the interim "app stopped → filesystem copy" path
   stays until it lands.

8. **Codify cross-time recall as a repo invariant + test.** **[buildable-now]** A `test_repo_invariants`
   guard asserting no time-partitioned corpus-scaled table and no recency-defaulting `WHERE` on the hot
   read paths (§F), so the sacred constraint cannot be quietly regressed under 5 TB pressure — the same
   "enforce the principle in a test" discipline the UI invariants already use.

**Not S3's job, noted so it is not lost:** the WARC/BagIt archive + local raw-text cold tier (K5, the
only principle-respecting disk escape hatch, §F); the httpfs per-OS binary fetch (networked operator,
DB-3); the maintainer's live-corpus P0 validation run (the final gate).
