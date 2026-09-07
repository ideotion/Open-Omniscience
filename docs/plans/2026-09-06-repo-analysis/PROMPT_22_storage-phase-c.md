# Prompt 22 — Storage: Phase C and the road to 5 TB

> **Scope:** the storage architecture — the text-offload store, the FTS split, sharding.
> **⛔ Gated on C4 (storage-plan rulings 3–6) and C5 (the DB-10 migrate operation). Do not build without them.**
> **Sequencing:** a design-refresh session first; the build is a later cycle. It is a prerequisite for
> prompt 18's whole-edition ingest.

## 0. Working mode

Read `_WORKING_MODE.md`, then `docs/design/STORAGE_5TB_PLAN.md` in full, then
`docs/design/5TB_ARCHITECTURE_REVIEW.md` and `docs/design/DB10_RETENTION_VACUUM_MEMO.md`.

This is the one prompt whose honest first deliverable may be **an updated design rather than code**. The plan
was written 2026-07-12 against a corpus an order of magnitude smaller than today's, and several of its inputs
have since been measured. Re-derive before building.

## 1. What the plan already settled, and what measurement has since added

Settled: the corpus/index `ATTACH` split is **dead** (WAL forfeits cross-time atomicity — one durable file;
only disposable or immutable pieces split out). A split-out FTS index must be **contentless-delete**
(snippet-safety verified). Phase C text-offload is **mandatory** against a ~17.5 TB ceiling, as a packed,
HMAC-keyed-addressed (the confirmation-attack fix), OOENC2-encrypted, per-source-zstd store with a versioned
encrypted dictionary registry, blob-first writes and mark-and-sweep GC. FTS **hash-sharding** is core because
it is time-neutral and therefore honours cross-time recall — and it must be prototyped at 50–100M synthetic
documents before commitment. A documented KDF hierarchy derives every crypto domain from the one passphrase.

Empirical overrides that stand against the report: DuckDB encryption remains **refuted for writes** (it
refuses an encrypted write without `LOAD httpfs`, and the only no-httpfs write path is the explicitly-unsafe
mbedtls — the forbidden fabricated-security path), so re-probe per version bump rather than re-reading the
docs. OOENC2 over `age` for the packs, with `age` recorded as the fallback.

Since measured and belonging in the refresh: SQLite **spills dirty pages as the cache fills**, so `cache_size`
is a residency dial rather than a throughput lever and an open transaction does not pin pages (that belief was
written into a comment and was false). The bundled sqlcipher3 compiles `SQLITE_TEMP_STORE=2`, so temps default
to **RAM** on the encrypted store and to disk everywhere else — invisible from `PRAGMA temp_store`, which
returns 0 meaning "the compile default". FTS5 `hashsize` is the bulk-load lever and is **not monotonic** (64
MiB beat 256 MiB in measurement) and it **persists** to the index config. And DB-10 §1a and §1b are both
ruled and wired: fresh files get `auto_vacuum=INCREMENTAL` and `page_size=16384`, with 16384 winning every
dimension at scale and the 4K point-lookup win at 3 GB inverting at 22 GB as a cache-fit artifact.

## 2. Slices

### S1 — Refresh the plan against the measurements above, then re-scope

Explicitly: does Phase C's shape change now that the page-cache belief is corrected and the temp-store default
is known? State what changed and what did not. A plan whose premises moved is worth an hour before it is worth
a sprint.

### S2 — C5: the DB-10 migrate operation

A byte-copy preserves the create-time seam, so `cp` cannot migrate `auto_vacuum` or `page_size`; and the
row-level restore-merge is not the migration either. The honest operation is a **store rebuild into a
fresh-pragma target** — `sqlcipher_export()` into an ATTACHed target created with the new pragmas, or
`VACUUM INTO` with pragmas set — which is the same machinery `connect.py` already uses for encryption
conversion, and which is `cp`-class cost (hours plus a spare drive) at any size. The page-size bench is the
mechanism proof and its `rebuild.seconds` is the measured migration cost at that corpus size (roughly
10–17 s/GB: about 4–6 minutes at 22 GB, about 30 minutes at 100 GB).

**Verify before building:** confirm empirically that the attached or `INTO` target honours `auto_vacuum` and
`cipher_page_size` under SQLCipher. Never assert it from documentation — that is a P2.4-style probe, and P2.4
is why this rule exists. The operation must state its cost and its app-stopped, gate-held posture honestly.

### S3 — C4: rulings 3–6

Dedup on or off; OOENC2 versus `age`; keyed addressing; and the `sqlite3mc` benchmark trial. Each is recorded
in §8 with its trade-off; none should be defaulted silently, which is why this prompt is gated rather than
recommended.

### S4 — The hash-sharding prototype

At 50–100M synthetic documents, before commitment, because the plan says so and because a sharding decision
taken on a small corpus is a decision taken on the wrong regime. The recorded lesson applies directly: a probe
that refutes a hypothesis is a claim about the fixture until it is shown to be a claim about the system, and
that mistake has already cost three field imports in this repository.

### S5 — DAT-05 / C6: the httpfs binaries

D1, D2 and D3 (the persisted columnar store) are built and **gated** behind a per-OS httpfs crypto extension
whose registry pins ship deliberately blank, because `extensions.duckdb.org` is egress-blocked here and a
fabricated checksum is forbidden. Recommended: park it explicitly with the reason rather than leaving it
reading as pending work — the in-memory serve is correct and the persisted store is a durability win, not a
correctness one.

## 3. Scope fence

Never a plaintext derived file. Never a second key surface. Never a fabricated checksum. Cross-time recall is
sacred, which is what rules out time-partitioning and what makes hash-sharding the right shape. Performance
must not depend on hiding data.
