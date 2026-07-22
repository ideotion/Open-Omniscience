> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — §1a is ruled and §1b's evidence is in, but NEITHER PRAGMA is actually set in `src/database/connect.py` yet — and its two direct follow-ons (the idle `incremental_vacuum` maintenance pass, §3; the VACUUM-button size gate, §2) are confirmed still unbuilt now that §1a is ruled. §4/§5 correctly still wait on a footprint-measurement field export that hasn't happened. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# DB-10 — retention, vacuum & storage-hygiene DECISION MEMO (S3.4)

**Status:** DESIGN-ONLY · ruling-gated on the maintainer's footprint numbers · no code beyond
cheap instrumentation. Produced by autonomous Session 3 (2026-07-12) from the
`docs/design/5TB_ARCHITECTURE_REVIEW.md` §C/§F findings (re-verified against the tree) and the
2026-07-09 field event. Every quantitative claim is tagged **[MEASURED]** (grep/field),
**[ARITHMETIC]** (a shown calc), or **[EXTRAPOLATION]** (a labelled projection).

This memo lays out the measured options for reclaiming space and bounding growth at 5 TB —
each with its honesty implications and what the next field export must MEASURE to decide. It
does **not** ship the irreversible seam (that is the maintainer's call, §1); it ships one
cheap read-only instrument (§7) that makes the central fact visible in the live diagnostic.

---

## 0. Why this is on the critical path

The 2026-07-09 field run grew the data folder to **~130 GB** with an 11.7 GB database and
~120 GB of other growth **[MEASURED, `SCALE_ROADMAP.md`]**. `SCALE_ROADMAP.md:109` states the
constraint bluntly: *"130 GB in days ⇒ growth itself is a scale bug."* Two facts make growth
irreversible today:

1. **`auto_vacuum` / `incremental_vacuum` are set NOWHERE** in `src/`
   **[MEASURED — grep, re-verified 2026-07-12]**: only `PRAGMA page_size` / `freelist_count`
   are *read* (`storage.py`, `api/database.py`, `benchmark.py`, `diagnostics.py`), never
   written. `storage.py` even knows it — the free-bytes line is commented "reclaimable only
   via (in)cremental vacuum."
2. **Full `VACUUM` is infeasible at 5 TB** (§2): `vacuum_database()` rebuilds the entire file,
   holds the writer gate for the whole duration, and needs **~2× the file size** in free disk.
   At 5 TB that is a ~10 TB scratch demand + a multi-hour exclusive-writer stall.

Consequence: deleted pages — from **pruned keywords** (`prune_orphan_keywords`), the
**delete-then-reinsert** on every re-index, **near-dup churn**, and newsletter re-imports — go
on the freelist and **never return to the filesystem**. At 5 TB with continuous re-indexing the
freelist is a monotonically growing dead-weight the app cannot reclaim.

---

## 1. THE IRREVERSIBLE CREATE-TIME SEAM — a maintainer ruling is needed NOW

`auto_vacuum` **and** `page_size` can **only be set on an empty database, before the first
table is created** — retrofitting either requires a full `VACUUM`, which §2 shows is infeasible
at scale. So the choice is genuinely one-way: **a corpus created without
`auto_vacuum=INCREMENTAL` can never get bounded reclaim without a rebuild it cannot afford.**
Every new field corpus created before this is decided is permanently stuck on the
full-VACUUM-or-nothing path. **This is the highest-leverage decision in the DB-10 space, and it
is time-sensitive — it should be decided before `0.2` tags and more corpora exist in the wild.**

The fresh-file creation branch is `src/database/connect.py` (the `if not p.exists() or
p.stat().st_size == 0:` path, ~line 86, before any table / `PRAGMA key`).

### 1a. `auto_vacuum = INCREMENTAL` (recommended)

- **What:** `PRAGMA auto_vacuum = INCREMENTAL` on a fresh store, before the first table.
  `INCREMENTAL` (not `FULL`) means reclaim is a *bounded, scheduled* `PRAGMA
  incremental_vacuum(N)` (§3) — never an unbounded auto-rewrite on every commit.
- **Cost:** a pointer-map page structure (~0.2% overhead) and a small per-commit bookkeeping
  cost. No behaviour change unless `incremental_vacuum(N)` is actually called.
- **Honest limit to document at the UI:** this fixes **new** corpora ONLY. Existing field
  corpora keep the full-VACUUM-or-nothing path; there is no honest cheap retrofit at scale.
  That asymmetry is itself the argument for deciding early.
- **Why not `FULL`:** `auto_vacuum=FULL` rewrites the tail on every commit that frees a page —
  an unbounded per-commit cost on a hot write path. `INCREMENTAL` keeps reclaim off the commit
  path and under a scheduled budget.

### 1b. `page_size` (measure-gated, decide in the same window)

- **What:** the SQLCipher default is **4096 bytes** **[MEASURED — grep: `page_size` is never
  written]**. A larger page (8192 / 16384) means fewer pages, shallower b-trees, and fewer
  codec ops per range scan — but it also inflates the per-connection page-cache byte cost
  (`cache_size` is in KiB, 64 MiB default × up to 72 pooled connections). Also CREATE-time-only.
- **Recommendation:** **measure 4K vs 16K on the GAMMA range-scan p95 before committing**
  (`docs/design/5TB_ARCHITECTURE_REVIEW.md` §B.3 / §G). Do NOT flip it blind — the cache-byte
  trade-off is real and unmeasured on the encrypted store.

**Why not autonomous:** both are IRREVERSIBLE CREATE-time seams that change the maintainer's
data-safety posture for every future corpus. The AskUserQuestion carve-out reserves
irreversible calls for the maintainer, and the S3 brief scopes DB-10 as design-only. So: this
memo flags the ruling; the code is a ~cheap change in `connect.py` once ruled (`auto_vacuum`
now; `page_size` after the GAMMA measurement).

---

## 2. Full VACUUM at 5 TB — gate/hide the UI button

`vacuum_database()` (`src/database/maintenance.py`) does a real `VACUUM` (whole-file rebuild,
writer gate held throughout, ~2× file size in scratch). The UI exposes it as "Compact database
(VACUUM)" (`index.html` / `src/api/database.py`). At 5 TB it is infeasible and blocking.

**Small future change (buildable-now once §1 is ruled):** gate/hide the full-VACUUM button
above a size threshold (e.g. the storage diagnostic's `db_bytes` > a few GB) and point at the
scheduled incremental-vacuum pass instead. Until `auto_vacuum=INCREMENTAL` corpora exist,
there is nothing to point at — hence §1 comes first.

---

## 3. Incremental-vacuum posture (ready to wire, gated on §1)

Once `auto_vacuum=INCREMENTAL` is ruled, a **bounded, off-peak `PRAGMA incremental_vacuum(N)`**
slots into the collector-idle maintenance regime shipped in **S2.2**
(`src/scheduler/maintenance.py:run_idle_maintenance` — idle-gated, throttled,
resumable-watermark). The same slice-budgeted shape as the reconcile/prune passes: drain the
freelist in bounded slices under a soft time/page budget so it never blocks collection.

- On a corpus WITHOUT `auto_vacuum` set, `incremental_vacuum(N)` is a **no-op** — so the pass
  is safe to wire now and simply activates when new corpora are created with the seam. (S3 does
  NOT wire it, to keep DB-10 design-only per the brief; it is a small, safe S4/S5 follow-up.)
- Honesty: the pass reclaims only freelist pages the store already holds; it never touches live
  data, and it is idle-gated so it never competes with a scrape.

---

## 4. Tiered raw-text retention (design-only, the ONE principle-respecting escape hatch)

§F of the review makes cross-time recall SACRED: **no design may make old data second-class.**
Age-based pruning/cold-tiering of *indexable* rows (mentions/analytics/metadata) is therefore
**FORBIDDEN**. The one allowed disk escape hatch:

- **Relocate RAW ARTICLE TEXT to a local archive** (the K5 WARC/BagIt archive, not built) while
  the **search index + every mention/analytic/metadata/provenance row stays HOT**. Opening a
  cold article is a transparent local read; reversible; **performance does not depend on it**
  (default OFF). This relocates *bytes*, never *reachability* — so "since 1995" costs the same
  as "last 30 days."
- **Blocked on:** the WARC archive (K5), which is not S3's job. S3 must not FORECLOSE it — and
  does not (the derived layer + counters are age-agnostic).

This is the honest answer to "the corpus is huge": move the biggest cold bytes (raw text) to a
local archive, keep everything searchable. It is a real design, gated on real footprint numbers
(how much of the DB is raw `articles.content` vs indexes — §6 measures it).

---

## 5. Near-dup content growth folding (DB-10 headline in `ROADMAP.md`)

Wire reprints stored whole inflate storage: the same article body arrives from N syndicating
sources and is stored N times. `src/signals/near_dup.py` (MinHash + LSH) already detects
near-duplicate clusters for the anti-amplification cards. The storage question is whether to
**fold** a near-dup cluster's bodies to one canonical copy + per-source provenance pointers.

- **Honesty constraint:** folding must be REVERSIBLE and never lose a source's independent
  provenance (the anti-amplification signal depends on knowing N sources ran it). So a fold is a
  storage optimisation *under* the provenance layer, never a merge of the sources themselves.
- **Measure first (§6):** what fraction of `articles.content` bytes are near-dup reprints? If
  small, folding is not worth the complexity; if large (a wire-heavy corpus), it is the biggest
  single win. Undecided until the field export measures it.

---

## 6. What the next field export must MEASURE to decide

Each option above is ruling-gated on numbers the app can already produce (all read-only):

| To decide | Measure | Where |
|---|---|---|
| §1 auto_vacuum urgency | freelist growth over time (`free_bytes`), and whether it's a growing fraction of `db_bytes` | `storage_composition` (`free_bytes`, now `auto_vacuum` — §7) |
| §1b page_size | 4K vs 16K range-scan p95 on an ENCRYPTED corpus | the GAMMA harness (`scale_bench`, operator) |
| §2 VACUUM gating threshold | `db_bytes` at which VACUUM's ~2× scratch/time is infeasible | `storage_composition` `db_bytes` |
| §4 tiered retention worth | raw `articles.content` bytes vs index/mention bytes | `storage_composition` per-table `dbstat` (available when the build has `SQLITE_ENABLE_DBSTAT_VTAB`) |
| §5 near-dup folding worth | fraction of article bytes that are near-dup reprints | `src/signals/near_dup.py` cluster sizes × article byte counts (a new small diagnostic, if pursued) |

The consolidated instrument is `src/monitoring/storage.py:storage_composition` — per-table /
per-index byte composition via `dbstat`, degrading honestly to PRAGMA-level totals where dbstat
is not compiled in (the bundled sqlcipher3 lacks it — the operator runs it on a dbstat-enabled
build, or reads the PRAGMA totals which work everywhere).

---

## 7. Instrumentation shipped this session (cheap, read-only)

`storage_composition` now also reports **`auto_vacuum`** (`none` / `full` / `incremental`) — the
central §1 fact made visible in the live diagnostic: an operator (and a future field export) can
SEE whether the corpus is on the reclaimable path at all. When `auto_vacuum=none` and there are
freelist bytes, a `free_bytes_note` states plainly that those bytes are reclaimable ONLY by a
full VACUUM (infeasible at scale) and points here. No score, no recommendation — a fact.

That is the only code DB-10 ships. The seam (§1), the incremental-vacuum pass (§3), the
VACUUM-button gate (§2), and the tiered archive (§4) all wait on the maintainer's ruling +
footprint numbers.

---

## 8. Recommended decision order (for the maintainer)

1. **Rule `auto_vacuum=INCREMENTAL` for NEW corpora now** (§1a) — irreversible, time-sensitive,
   low-cost, high-leverage; a corpus created without it can never reclaim at scale.
2. **Measure `page_size` 4K vs 16K on GAMMA** (§1b) before flipping it (cache-byte trade-off).
3. Then the buildable follow-ups (S4/S5): the incremental-vacuum idle pass (§3), the
   VACUUM-button size gate (§2).
4. Measure raw-text vs near-dup byte fractions (§6) to decide the tiered archive (§4) and
   near-dup folding (§5) — both larger, both genuinely gated on real footprint numbers.
