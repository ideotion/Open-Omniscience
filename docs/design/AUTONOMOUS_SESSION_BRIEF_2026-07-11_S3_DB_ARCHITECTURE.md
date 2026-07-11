# SESSION 3 of 6 — TIER 2: database & scale architecture

**Mission:** the storage/derived-layer architecture that lets a decade-scale corpus stay
fast and safe. Cross-time recall is SACRED — no design may make old data second-class; the
canonical encrypted SQLCipher store stays the source of truth; every derived store is a
disposable, rebuildable cache that is encrypted or in-memory, NEVER a plaintext file. Read
`SESSIONS_2026-07-11_CONVENTIONS.md` §0 first, then **absorb S2's carry-overs** (including
the 5 TB review doc — it is your input).

**Maintainer ruling 2026-07-11 #2 (binding): build D1/D2/D3 NOW, gated.** The per-OS httpfs
crypto binaries cannot be fetched here (egress-blocked; recorded A13 blocker). Build the
full machinery behind the existing `secure_crypto_available()` gate: in CI the tests may
`INSTALL httpfs` (network exists there); locally they skip with an honest reason; the
feature ACTIVATES the moment the maintainer drops the sha256-pinned binaries in from a
networked machine. Never relax the gate; never fabricate a checksum; the in-memory fallback
stays the degrade path.

## Queue (top-down)

### S3.1 — D1: the persisted encrypted DuckDB columnar store
Per `docs/design/PERSISTED_DUCKDB_HTTPFS.md` + `SCALING_DERIVED_LAYER_1000X.md`:
- One `connect()` path under the SAME passphrase (no second key surface); the EMPIRICAL
  encryption gate is test-enforced (sentinel absent from raw bytes · won't open without the
  key · opens with it).
- A verify-before-LOAD step for the extension binary, with the CI story made explicit
  (the current registry entry carries a VERSION coupling, no sha256 — and you cannot add
  real ones offline): (a) the verify MECHANISM is proven against a local fixture
  "extension" whose sha256 IS pinned in a test fixture registry; (b) refuse-on-missing /
  refuse-on-mismatch are themselves pinned tests (so the local sandbox refuses honestly);
  (c) the CI httpfs lane runs under a clearly-marked CI-only trust path (checksum computed
  in-lane, asserted stable across the run, NEVER promoted into `external_artifacts.yml`);
  (d) the real per-OS sha256 fields stay ABSENT until the operator's networked fetch+pin
  step — the registry `duckdb-crypto-extension` floor == pyproject `[columnar]` floor stays
  test-enforced.
- Lifecycle: build-once persist, survive restarts, invalidate on corpus-epoch change,
  excluded from backups (rebuildable), cold/missing → live query fallback (slower, never
  wrong). `OO_` env kill-switch.
- CI test lane: mark the persisted-store tests to install httpfs in CI; local runs skip
  honestly. Prove byte-parity with the in-memory path on a fixture corpus.

### S3.2 — D2 + D3: the persisted `keyword_daily` rollup + incremental refresh
- **D2:** stream-build `keyword_daily` (+`keyword_meta`) into the D1 store (the SQLCipher →
  DuckDB stream+group path; parity functions already exist — reuse
  `windowed_term_counts`/`keyword_daily_parity`).
- **D3:** incremental merge of the new mention tail, **epoch-gated full rebuild** — the
  delete-then-reinsert double-count trap lesson is BINDING (any re-index/prune/restore-merge
  bumps the epoch → full rebuild, never an incremental merge across it; the epoch now also
  bumps on restore-merge, shipped A7). Gate on epoch AND an append-id tail (pure epoch gates
  freeze during collection — the THETA lesson); read the epoch with a COLUMN query, never
  `session.get`.
- Wire `rollup_serve` to PREFER the persisted store when the gate is open (in-memory stays
  the fallback); parity tests order-insensitive at tie boundaries (the D2 tie lesson);
  `basis` disclosure (as_of/stale) travels.

### S3.3 — DB-9: adaptive backup-volume sizing (the parity ceiling)
Reed-Solomon over GF(2⁸) caps at N+M < 256 volumes ≈ 128 GB at 512 MiB — under the 5 TB
mandate. Implement adaptive volume sizing in the streaming engine (size volumes so
N+M stays < 256 with headroom; preserve incremental changed-volume reuse semantics across a
size-tier change — a corpus crossing a tier must not silently orphan its previous set;
state the migration behaviour honestly in the manifest). **This is the most dangerous code
in the repo** — the ZETA lessons are binding (run-unique names, atomic manifest swap, the
previous complete backup must survive ANY failure mid-refresh, traversal-guard every
name→path, test the real path), and the skeptic pass must include an interrupted-refresh +
tier-crossing torture matrix. GAMMA-tier proof at the sandbox's disk cap.
**Validation-staleness handoff:** this changes the engine the v0.2.0 tag's live validation
covers. If the maintainer's live P0.1 run happened before this merges, your closeout MUST
say the S1 validation job needs a RE-RUN before tag-day (the S1 report is engine-version-
stamped precisely so this staleness is detectable).

### S3.4 — DB-10: the retention/eviction + incremental-vacuum DECISION MEMO
Design-only (the posture is ruling-gated on the maintainer's footprint numbers): a decision
memo laying out the measured options — tiered retention (raw text → local archive while ALL
indexes/mentions stay hot; reversible; performance must never DEPEND on it), incremental-
vacuum posture at scale, near-dup storage folding — each with its honesty implications and
what the next field export must measure to decide. No code beyond cheap instrumentation.

### S3.5 — (stretch) D5: Roaring co-occurrence bitmaps
Only if the queue above is genuinely done: per-keyword article bitmaps in the D1 store +
precomputed top-K co-occurrence neighbours (pyroaring as an optional extra, registry entry,
graceful degrade). Off the critical path; skip without guilt.

## Explicitly NOT yours
Fetching the httpfs binaries (networked — operator) · the dbstat sqlcipher build (networked)
· product/UX (S4) · rulings builds (S5) · backlog features (S6).

## Closeout
Ledger rows (+ the SHIPPED_LOG lesson if the CI-installs-extension pattern teaches one) +
ROADMAP flips (DB-3 → machinery-built-awaiting-binaries · DB-9 → shipped · DB-10 → memo) +
CARRY-OVER for S4, and an explicit OPERATOR note: the one-time networked step that turns
D1 on (fetch + pin the binaries per `EXTERNAL_DEPENDENCIES.md`).
