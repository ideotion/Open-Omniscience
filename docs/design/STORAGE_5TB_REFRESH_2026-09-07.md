# Storage at 5 TB+ — REFRESH v2 (2026-09-07)

**Status:** DESIGN REFRESH of [`STORAGE_5TB_PLAN.md`](./STORAGE_5TB_PLAN.md) (the v1 plan of
record, 2026-07-12). No Phase-B or Phase-C code ships from this document. What ships alongside
it is one regression guard (`tests/test_db10_migration_mechanism.py`) pinning the C5 mechanism
findings below, because two of them contradict instructions the v1 plan currently gives.

**Why a refresh rather than a build.** Prompt 22 sequences a design refresh ahead of the build,
and re-deriving first turned out to be the right call: **the plan's central justification for
Phase C rests on a number that the DB-10 §1b ruling quadrupled seven weeks ago**, and its
second migration mechanism silently destroys data on every corpus created since that same
ruling. Both are §1 below. Neither is visible from the v1 text, which is exactly what the
staleness guard exists for.

Every quantitative claim here is **[MEASURED]** on this sandbox's bundled sqlcipher3
(SQLCipher **4.12.0 community**, SQLite **3.51.1**, provider **openssl**), **[ARITHMETIC]**, or
**[EXTRAPOLATION]**. Probe scripts are named at each finding.

---

## 0. What changed, what did not — the short version

| v1 claim | Verdict | §  |
|---|---|---|
| "a default-page SQLCipher file caps at ~17.5 TB ⇒ Phase C is MANDATORY" | **Premise retired.** The cap is 64.00 TiB at the ruled page size | §1 |
| "`sqlcipher_export()` into an ATTACHed target **or** `VACUUM INTO` with pragmas set" | **Half refuted.** The first works in every direction; the second silently writes an unopenable file | §2 |
| Phase C shrinks the hot working set via cache economics | **Mechanism corrected** (still true, for a different and stronger reason) | §3 |
| Phase C's GC is "mark-and-sweep over SQL references" | **Amended:** must be windowed by construction | §3 |
| FTS split-out saves a second on-disk copy of article text | **False** — external-content already banks that; the split now costs more than it saves | §4 |
| Hash-sharding honours cross-time recall | **Confirmed by measurement**, 100% recall in 44/44 cells | §5 |
| Cross-shard BM25 rank-merge is approximate | **True, and quantified** — the divergence is per-shard *thinness*, and it shrinks as shards fatten | §5 |
| "prototype at 50–100 M synthetic documents before commitment" | **Not achievable here**, and now costed: 89.6 GiB and 5.2 h *per arm* at 50 M | §5 |
| §7 open verification items 1 and 3 | **Answered** | §6 |
| The ATTACH corpus/index split is dead (WAL forfeits cross-file atomicity) | **Unchanged** | §7 |
| Packed-not-scattered · keyed HMAC addressing · blob-first write ordering | **Unchanged** | §7 |
| DuckDB encryption refuted for writes | **Unchanged** (re-probe per version bump) | §7 |

---

## 1. The ceiling premise is retired — Phase C is no longer mandatory *by size*

v1 §0 lists as headline finding (3): *"a default-page SQLCipher file caps at ~17.5 TB → text
offload (Phase C) is MANDATORY and moves ahead of the file split in priority."* That sentence
is why Phase C outranks everything else in the v1 sequencing.

**[MEASURED]** (`probe_storage.py`, arm B) the bundled sqlcipher3 compiles
`MAX_PAGE_COUNT=0xfffffffe` — so the runtime limit is the absolute one, 4,294,967,294 pages,
and `PRAGMA max_page_count` is already at it on a fresh store. There is no separate,
lower default limit to worry about. The ceiling is therefore exactly `4,294,967,294 × page_size`:

| page size | ceiling **[ARITHMETIC]** | |
|---|---|---|
| 4,096 | 16.00 TiB (17.59 TB) | what v1 measured against |
| **16,384** | **64.00 TiB (70.37 TB)** | **what every corpus created since 2026-08-13 actually is** |

DB-10 §1b shipped `_FRESH_PAGE_SIZE = 16384` (`src/database/connect.py`), ratified 2026-08-13.
**It quadrupled the ceiling as a side effect, and nothing recorded that.** Against the mandate:

- the **5 TB** milestone sits at **7.1%** of a single file's capacity, not 28%;
- v1 §4's "top-end honesty" states *"50 TB is not reachable by any single-file design"*. At the
  ruled page size, 50 TB is **71%** of one file. On the size axis alone it is reachable.

**What this does and does not mean.** It does *not* make Phase C worthless — §3 restates the
argument that survives. It *does* retire the claim that Phase C is a prerequisite for the 5 TB
milestone, which is the claim that put it ahead of everything else. **Phase C is re-scoped from
"MANDATORY, first" to "the largest single lever on the hot working set, gated on a footprint
measurement nobody has taken yet"** (DB-10 §6; see §8).

Two honest riders. Sharding the durable store is still the answer past ~64 TiB, so v1's redraw
is not wasted — it is deferred by roughly 4×. And a ceiling is not a target: nothing here says a
64 TiB single file would be *pleasant*, only that it would not be *refused*.

---

## 2. C5 — the migrate operation: one mechanism verified, one refuted

v1 §9 and the 2026-07-18 folder-copy-parity ruling both describe the honest DB-10 migration as a
store rebuild into a fresh-pragma target, naming two mechanisms: `sqlcipher_export()` into an
ATTACHed target, **or** `VACUUM INTO` with pragmas set. The prompt's verify-before-build gate
says to confirm empirically that the target honours `auto_vacuum` and `cipher_page_size` under
SQLCipher, and never to assert it from documentation. Both were run.

### 2.1 `sqlcipher_export()` into an ATTACHed target — VERIFIED, all four directions

**[MEASURED]** (`probe_storage.py` arm C, `probe_storage2.py` arm C-bis; now pinned by
`tests/test_db10_migration_mechanism.py`). ATTACH the target with its key, **declare**
`cipher_page_size` and `auto_vacuum` on the alias, then export:

| direction | result |
|---|---|
| legacy → ruled (4096/NONE → 16384/INCREMENTAL) | target is 16384/INCREMENTAL, all rows |
| ruled → legacy (16384/INCREMENTAL → 4096/NONE) | target is 4096/NONE, all rows |
| rekey **and** repage in one pass (→ 8192/INCREMENTAL under a new passphrase) | target is 8192/INCREMENTAL, all rows; the **old** key correctly does not open it |
| **declare nothing** | target takes the **compile default 4096/NONE** — neither pragma is inherited |

The last row is the load-bearing one and it is why `connect._match_source_pragmas` exists. It
also means a migration that declares `cipher_page_size` and *forgets* `auto_vacuum` silently
down-migrates a corpus off the reclaimable path — a one-way loss with no error.

**Note on the fixture, because it nearly went wrong here.** The first run of this arm used a
4096 source against a compiled default of 4096, so "inherited from the source" and "took the
compile default" produced the same answer and the negative-space claim could not be tested at
all. Re-run from a 16384 source it discriminates. The guard now carries an anti-vacuity
assertion that the source differs from the compile default *in both dimensions*, because the
mutation matrix confirmed a coincident fixture makes the test pass for the wrong reason.

### 2.2 `VACUUM INTO` — REFUTED on an encrypted store, and it fails toward success

**[MEASURED]** `VACUUM INTO` writes its product at the compiled-in `DEFAULT_PAGE_SIZE` (4096)
**regardless of the source's real page size, and reports success either way**:

```
source  1,024 -> ran -> product does not open at any page size, under the correct key
source  2,048 -> ran -> product does not open
source  4,096 -> ran -> product opens, all rows, auto_vacuum preserved
source  8,192 -> ran -> product does not open
source 16,384 -> ran -> product does not open      <-- the ruled default
source 32,768 -> ran -> product does not open
```

So the statement is usable at exactly one page size: **the one every corpus had before
2026-08-13, and the one no corpus created since has.** That coincidence is the entire reason
this was never noticed, and the ruling that removed it is the ruling that made the documented
mechanism dangerous.

The obvious repair does not work either. Setting `cipher_page_size` on a live keyed connection
re-configures the codec mid-flight, so the next statement fails with `file is not a database`
— **naming the source**, which reads as corpus corruption that has not happened. The stdlib
spelling `PRAGMA page_size` is worse: it is accepted silently and the failure surfaces one
statement later.

**Not a plaintext leak**, checked rather than assumed: the unopenable product contains no
plaintext body runs, no table name, and differs from the source in 261,051 of 262,144 bytes.
**The source survives every variant**, which is what makes this a trap rather than a
catastrophe. And **there is no live `VACUUM INTO` call site in the tree** (grep across `.py`,
`.js`, `.sh`) — so this is a documented instruction that would produce a data-destroying
operation, not a shipped bug.

Scoped, so the finding cannot be over-read: on a **plaintext** store `VACUUM INTO` honours
declared `page_size` and `auto_vacuum` exactly as documented. That is what the retired page-size
bench used, and it is why the Open-queue's "EMPIRICALLY PROVEN in-sandbox for plaintext" is both
true and never was evidence about the encrypted path. A twin test pins that half.

### 2.3 What C5 still needs before it is a user-facing operation

The mechanism is proven; the operation is not built, deliberately. What a build owes:

- **a free-disk preflight** — a rebuild needs a second full copy, and there is no disk check
  anywhere on the existing full-`VACUUM` endpoint either (§8, carry-over);
- **the app-stopped, gate-held posture stated up front**, with the cost in the operator's own
  units. From the retired bench's `rebuild.seconds`: **~10–17 s/GB** — ≈4–6 min at 22 GB,
  ≈30 min at 100 GB, ≈14–24 h at 5 TB **[EXTRAPOLATION from two measured field runs]**;
- **a self-verify** that reads the target's pragmas back (with `int()` — some builds return the
  read-back as TEXT) and refuses on mismatch;
- **the `auto_vacuum` declaration**, not just `cipher_page_size`, per §2.1.

**The instrument that measured the cost no longer exists.** `src/monitoring/pagesize_bench.py`
and its endpoints were removed under the 2026-07-31 ruling 6 once §1b was ratified. The
10–17 s/GB figure survives only in the ledger. A C5 build re-creates the measurement or cites
the ledger explicitly — it must not present the number as something the tree can reproduce.

---

## 3. Does Phase C's shape change? — the prompt's direct question

**Yes in two places, no in the rest.** Taking the two corrected beliefs in turn.

### 3.1 The page-cache correction changes Phase C's *argument*, not its design

SQLite spills dirty pages as the cache fills, so `cache_size` is a residency dial and an open
transaction does not pin pages. v1 (and the architecture review §B.2) justified Phase C's second
benefit — a smaller hot metadata/index working set — through cache economics: *"the mitigation
is keeping the hot metadata/index small."*

At 5 TB that argument was always weak, and the review said so itself: 64 MiB caches ~0.001% of
the pages. With the correction it is weaker still — the cache cannot be made to hold a
meaningful fraction of anything at this scale, so "shrink the working set so more of it fits"
is not the mechanism.

**The mechanism that survives is stronger and is already measured elsewhere in this repo:
bytes-per-row through the codec.** `articles.content` sits ahead of the small columns in row
order, so any heap access drags the whole ~22 KB row through AES — the recorded column-order
trap, which cost 26 s of a 32 s wall on a single query at field scale, and 4,775 ms × 154 calls
on the date-range probe. Relocating `content` shortens every heap row that *must* be read,
whatever the cache does. That is a per-access saving with no cache assumption in it at all.

**Design impact: none. Argument impact: replace the cache-economics justification wherever it
appears, or the next reader tests the wrong thing** — a Phase-C benchmark built on cache-hit
rate would measure a mechanism that is not the one doing the work.

### 3.2 The temp-store default changes Phase C's GC, by construction

**[MEASURED]** the bundled sqlcipher3 compiles `SQLITE_TEMP_STORE=2`, and `PRAGMA temp_store`
returns `0` — meaning "the compile default", which is not self-describing. So on the encrypted
store every statement journal, temp table and transient index defaults to **RAM**, invisibly,
while every plaintext probe of the same code measures the opposite.

v1 §3-C specifies the blob store's reclaim as *"a mark-and-sweep GC over SQL references"*. At
10⁸–10⁹ blobs the natural implementations of that — an anti-join, a `NOT IN`, a sort over the
blob address space — are exactly the shapes that build a large transient index, i.e. exactly the
shape that just cost a field import 5,937 MB on a 5.5 GB box.

**Amendment to v1 §3-C, and it is a design constraint rather than a tuning note:** Phase C's GC
must be a **bounded windowed sweep over the address space** from the first line, never one
statement over all references, and it must set `temp_store=FILE` for its own connection. The
merge already learned both halves — the pragma is what the measurement supports, the windowing
is what makes it corpus-independent, and they need separate tests or one gets reported as
evidence for the other.

### 3.3 What does *not* change

Packed-not-scattered; HMAC-keyed addressing under a passphrase-derived key with opaque pack
names; OOENC2 per pack; compression below encryption with a versioned encrypted dictionary
registry; blob-first write ordering with SQL second. None of these rest on either corrected
belief — they rest on the confirmation-attack threat model, the small-file argument, and the
two-consistency-domain argument, all untouched.

---

## 4. Phase B's FTS split is now a worse trade than when it was written

Two of the split's stated bonuses do not survive contact with the current tree.

**"No second on-disk copy of article text" is already banked.** v1 §3-B lists it as a bonus of
going contentless. But `src/database/fts.py` already declares `article_fts` with
`content='articles'` — external content, which stores only the index. The split's contribution
on this axis is **zero**.

**The split *costs* `'rebuild'`, and the replacement is expensive now. [MEASURED]**:

```
external-content 'rebuild'   -> OK, reindexed from the base table
contentless-delete 'rebuild' -> REFUSED: "'rebuild' may not be used with a contentless fts5 table"
```

v1 records this as a footnote (*"the self-heal path becomes 're-feed from source', which must be
a resumable background job"*). Since it was written, the field corpus passed a million articles
and a full re-index has been measured in **days**, single-core, with its own recorded
data-loss-adjacent bugs around resume cursors. So the self-heal path goes from a
minutes-to-hours engine primitive to a multi-day application-level job — on the surface whose
whole justification is that it is *disposable*.

**What remains genuinely valuable in Phase B:** backups excluding a rebuildable index, and a
separate WAL/checkpoint cycle per file. Both are real. Neither is worth trading `'rebuild'` for
at the current corpus size, and **the trade only ever pays once the FTS index is itself the
scaling problem** — which is the question §5's prototype exists to answer.

**Re-scope: Phase B's FTS split moves behind the sharding prototype**, not ahead of it. If
sharding lands, each shard is a separate file anyway and the split comes free with it; if
sharding does not, the split buys backup exclusion at the price of the self-heal path.

---

## 5. The sharding prototype — what was settled, and what a 50 M run would cost

v1 promotes hash-sharding to core design and requires a 50–100 M-document prototype before
commitment. That prototype **is not achievable in this sandbox**, and the honest form of that
statement is a costing rather than a shrug.

### 5.1 What it would cost — measured, not estimated

**[MEASURED]** (`fts_calibrate.py`, 300,000 synthetic documents of 180–420 words over a
Zipf-shaped vocabulary with a long tail, contentless-delete, `hashsize` 64 MiB, page size
16384): **1,925 bytes of FTS5 index per document**, built at **2,692 docs/s** on 4 cores.

| corpus | index per arm **[EXTRAPOLATION]** | build per arm |
|---|---|---|
| 50 M docs | **89.6 GiB** | **5.2 h** |
| 100 M docs | **179.3 GiB** | **10.3 h** |

A single-vs-sharded comparison needs **two arms**. Against this sandbox's **30 GB** writable
allowance that is short by roughly 6× at 50 M for one arm, 12× for the comparison. This is an
operator job, and it now has numbers rather than a caveat. One rider on the figure: the
synthetic vocabulary is deliberately tail-heavy (2 M distinct tail terms), which pushes
bytes-per-document toward an **upper** bound; real prose recurs more, so an operator should
treat 89.6 GiB as a ceiling and measure their own corpus's ratio first.

### 5.2 What *was* settled here — the part that is not a scale question

Cross-shard ranking is arithmetic over per-shard term statistics, so it depends on shard count
and on how a term's document frequency splits — both controllable at any corpus size.
**[MEASURED]** (`bm25_shard_divergence.py`; 120,000 documents, one index vs the same documents
hash-sharded at K = 2/8/32/128, `shard = hash(id) mod K`, fan-out to every shard always, merged
on the per-shard `bm25()`):

- **Recall of the matching set: 100% in all 44 cells.** This confirms the construction rather
  than discovering it — the fan-out visits every shard with no per-shard cutoff, which is
  precisely why time-partitioning is banned and hash-sharding is not. Cross-time recall is safe
  under sharding, structurally.
- **Ranking diverges**, worst on **mid-frequency** terms (common enough to be in every shard,
  rare enough that per-shard document frequency is noisy) — not, as one might guess, on the
  tails. At K=128 the top-20 overlap with the single index fell to **30%** and the top result
  itself changed.

**And then the control inverted the reading, which is the part worth carrying.** That first run
varied shard *count* over a fixed corpus, so docs-per-shard fell to **940** at K=128 — nothing
like the ~1,000,000 docs/shard v1 proposes. Holding K=32 fixed and fattening the shards
(`bm25_control.py`):

```
docs/shard:        2,000     8,000    32,000
very common          100%      100%       95%
mid                   60%       75%       90%
uncommon              75%       80%       75%
rare tail             40%       75%       95%
```

**The divergence is per-shard statistical thinness, and it shrinks as shards fatten toward the
proposed size.** The alarming K=128 number was a claim about a fixture with 940 documents per
shard. Recording it as a finding about sharding would have been the recorded three-field-imports
mistake; the control cost twelve minutes.

Honest limits on this: one query per cell (each number is n=1, and "uncommon" is visibly
non-monotone as a result), and the largest arm is 32,000 docs/shard — still **31× short** of the
proposal. So the *trend* is measured and the production regime is extrapolated.

### 5.3 The consequence v1 does not state

v1 offers *"either maintain global term stats or DISCLOSE the approximation."* FTS5's `bm25()`
takes column **weights** and nothing else — it scores from the index it is called on and accepts
no external statistics. So "maintain global stats" is **not available inside FTS5**. The real
options are: keep shards fat enough that the divergence is immaterial (what §5.2 measures, and
the direction v1's own 1 M-docs/shard hypothesis already points), disclose the approximation, or
move ranking to a re-scoring layer outside FTS5. The first is the cheapest and the measurement
supports it; the choice belongs in the prototype's report, not here.

---

## 6. v1 §7 open verification items — two answered

1. **Bundled sqlcipher3's SQLite version ≥ 3.43** — **[MEASURED] 3.51.1**, so
   `contentless_delete` is available (and accepted; §4). **CLOSED.**
2. Backup live-read consistency semantics — untouched here. **Still open.**
3. **`PRAGMA cipher_memory_security` default** — the v1 research note says it *"could not be
   confirmed from a primary source"*. **[MEASURED] `0` — OFF by default**, provider `openssl`,
   SQLCipher `4.12.0 community`. **CLOSED**, and it has a consequence: v1 §5 asks that memory
   hygiene "extend to the blob path", implying the SQL path already has it. It does not. Whether
   to turn it on is a separate question with a real cost (it disables some optimisations); what
   matters here is that the KDF-hierarchy design must not *assume* the SQL side is locked.
4. Loadable FTS5 tokenizer extensions under SQLCipher — untouched. **Still open.**
5. WAL starvation in the field — **substantially closed since v1** by the S4.1 work: measured
   that against a pinned WAL the entire cost of `wal_checkpoint(TRUNCATE)` is the busy handler,
   `PASSIVE` is what bounds growth while pinned, and the plan's own predictive gate was refuted
   and pinned as refuted.

---

## 7. Unchanged from v1 — recorded so they are not re-litigated

- The corpus/index **`ATTACH` split is dead**: WAL forfeits cross-file transaction atomicity.
  Only disposable or immutable pieces split out. Nothing measured here touches this.
- A split-out FTS index **must** be contentless-delete (external content cannot cross an ATTACH
  boundary). Confirmed available at 3.51.1; the cost of it is §4.
- **Packed, never scattered**; **HMAC-keyed addressing with opaque pack names** (the
  confirmation-attack fix); **blob-first, SQL-second** write ordering; **OOENC2** over `age` with
  `age` recorded as the fallback. The threat model behind each is unchanged.
- **DuckDB encryption stays refuted for writes** (P2.4): it refuses an encrypted write without
  `LOAD httpfs`, and the only no-httpfs path is the explicitly unsafe mbedtls. Re-probe per
  version bump rather than re-reading the docs; the gate is a probe for exactly this reason.
- **Cross-time recall is sacred.** §5.2 is the first direct evidence that hash-sharding honours
  it rather than merely being argued to.

---

## 8. Re-scoped sequencing

v1 §9's order was set by the ceiling premise. With that retired:

1. **C5's remaining half** — the migrate operation, if and when the maintainer wants one. The
   mechanism is verified and guarded; what is missing is the disk preflight, the self-verify and
   the honest cost statement (§2.3). Ruling-gated, not evidence-gated.
2. **DB-10 §6's footprint measurement** — the per-table `dbstat` split of `articles.content`
   against index and mention bytes. **This has still never been taken**, and it is the gate on
   Phase C's actual value. Two independently recorded field numbers bracket it — ~44 KB of
   database per article overall, ~22 KB average article row on the 32.1 GB field artifact — which
   puts article rows at roughly *half* the store. That is an inference from two measurements, not
   a measurement; a 50% saving and a 90% saving justify very different amounts of Phase C.
3. **The sharding prototype**, as a specified operator job (§5.1) rather than a caveat.
4. **Phase B's FTS split** — behind the prototype now, not ahead of it (§4).
5. **Phase C**, gated on (2), with §3.2's windowed GC baked in from the first line.

**Carry-over found while doing this, in scope for DB-10 but not built here.** DB-10 §2's
VACUUM-button gate is **half shipped**: `app-settings.js:_confirmVacuum` discloses an estimated
duration (from the same 10–17 s/GB figure) before running, which is honest and translated. What
is absent is (a) any **backend** refusal — `POST /api/database/vacuum` will start a full rebuild
on a corpus of any size — and (b) any **free-disk preflight**, though a full `VACUUM` needs ~2×
the file size in scratch and the repo already has a `free_disk_bytes` helper in
`src/safety/data_location.py`. The memo's actual ask — *gate above a threshold and point at the
incremental pass instead* — is also unmet: the incremental pass is wired
(`scheduler/maintenance.py` → `maybe_incremental_vacuum`) and nothing points at it.
