> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — the CREATE-time seam (`auto_vacuum`/`page_size`) this whole plan sequences after is still unwired in `src/database/connect.py` (see the 5TB_ARCHITECTURE_REVIEW banner) — Phase B/C and the KDF hierarchy remain correctly not-yet-due. `journal_size_limit` is now set (`src/database/session.py:137`), confirmed shipped. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Storage at 5 TB+ — the PLAN OF RECORD (v1, 2026-07-12)

**Status:** DESIGN-ONLY (no code from this doc yet). This is the reconciled successor of the
"A→B→C" storage sketch from the 2026-07-12 maintainer↔Fable-5 planning session — corrected by
the internet-connected research report
([`docs/research/storage/STORAGE_5TB_RESEARCH_2026-07-12.md`](../research/storage/STORAGE_5TB_RESEARCH_2026-07-12.md),
"the report" below) and re-grounded against the tree as of S3's merge
(`docs/design/5TB_ARCHITECTURE_REVIEW.md` = S2.6, `docs/design/DB10_RETENTION_VACUUM_MEMO.md`
= S3.4, `src/scheduler/hygiene.py`, `src/backup/stream_backup.py`). The original A→B→C sketch
was never committed; **this doc is its first repo artifact, with the report's corrections
baked in from the start** — do not resurrect the uncorrected sketch from memory.

**How to use this doc (future sessions):** the STALENESS GUARD applies — re-verify every
"exists/absent" claim against the tree before building; this doc records the state at
2026-07-12. Read the report for the primary-source citations; read `5TB_ARCHITECTURE_REVIEW.md`
for the measured field numbers; read the DB-10 memo for the vacuum/retention decision space.
Nothing here is buildable before its listed gate.

---

## 0. Verdict summary

The report's five headline findings were hand-verified and are ACCEPTED (two were correctness
bugs in the sketch, not tuning): (1) WAL forfeits cross-file transaction atomicity across
ATTACHed databases → the corpus/index file split is REDRAWN along the disposable/non-disposable
axis; (2) FTS5 external-content cannot cross ATTACH boundaries → the split-out FTS index must
be CONTENTLESS-DELETE; (3) a default-page SQLCipher file caps at ~17.5 TB → text offload
(Phase C) is MANDATORY and moves ahead of the file split in priority; (4) FTS5 beyond ~15 M
docs is undocumented territory → hash-sharding is CORE design, prototyped before commitment;
(5) plaintext-SHA-256 file names leak a CONFIRMATION-ATTACK surface and one-file-per-article
is a small-file catastrophe → the blob store becomes PACKED + KEYED-addressed.

Two places where OUR empirical record OVERRIDES the report (§2 below): DuckDB's "native
encryption" (refuted-in-practice for writes by our P2.4 test — the httpfs gate stays), and
age-vs-our-own-OOENC2 for pack encryption (we already own a shipped, tested streaming AEAD).

The report's most important external finding stands: **no project on record satisfies all four
of {local-first, multi-TB, encrypted-at-rest, full-text search} at once.** We are building in
unoccupied territory; prototypes outrank precedent.

---

## 1. Constraints (unchanged, restated so this doc is self-contained)

Single machine · no server processes · one passphrase, no recovery, copy→ciphertext (a copied
data folder must yield ONLY ciphertext, including metadata like file names) · GPLv3-compatible
components only · append-heavy ingest (30–80 K articles/day at field rates) concurrent with
always-on read analytics · FTS over everything · **cross-time recall is SACRED** (no design may
make old data second-class; time-partitioning is BANNED — `test_cross_time_recall_is_sacred_
no_time_partitioned_corpus_tables` enforces) · field anchors: 11.7 GB DB = 268,241 articles /
3.06 M keywords / 20.9 M mentions (~44 KB DB/article, ~78 mention rows/article) · target
5–50 TB ≈ ~117 M–1.1 B articles / ~9.2 B+ mentions (extrapolation, `5TB_ARCHITECTURE_REVIEW.md`
§B.1).

An honesty note the report insisted we state: old data is never second-class BY DESIGN, but on
any encrypted store larger than RAM it is slower BY CACHE ECONOMICS (every cold page fault pays
decrypt+HMAC). The mitigation is keeping the hot metadata/index small (Phase C) and index-only
plan shapes — never a partitioning trick.

---

## 2. Where OUR empirical record overrides the report (do not re-import these errors)

1. **DuckDB "native at-rest encryption since 1.4"** — the report recommends an encrypted DuckDB
   read-sidecar citing the duckdb.org announcements. Our P2.4 verification (2026-06-25, DuckDB
   1.5.4, recorded in CLAUDE.md + `columnar.py`'s EMPIRICAL FINDING) **refuted the write path**:
   the built-in crypto module is READ-ONLY; an encrypted WRITE requires `LOAD httpfs` (OpenSSL)
   or the explicitly-unsafe `force_mbedtls_unsafe` (= forbidden fabricated security). So the
   `secure_crypto_available()` gate STAYS, exactly as S3.1's pin-and-verify httpfs loader
   implements it. Also: the sidecar is not a proposal — the columnar sidecar (D1/D2/D3,
   `keyword_daily` rollups) is our SHIPPED architecture; the report independently re-derived it,
   which is corroboration, not news.
2. **age for pack encryption** — optional, not necessary. We already own OOENC2
   (`src/safety/crypto.py`: chunked AES-GCM streaming container, nonce = prefix|counter|final-flag,
   truncation/reorder/extension all fail auth; proven in `tests/test_crypto_streaming.py`).
   Packs can reuse OOENC2 under the §5 KDF hierarchy — one fewer dependency, already tested.
   age's X25519 machinery buys nothing in a single-passphrase symmetric world. age (BSD-3,
   audited, ChaCha20-Poly1305 = no AES-NI dependency) remains the recorded FALLBACK if OOENC2
   ever needs replacing; the choice is a maintainer ruling (§8).
3. **Backup-vs-live-DB warnings** — largely already paid: the P0.1 streaming backup engine
   exists precisely to kill whole-corpus materialization, checkpoints the WAL
   (`stream_backup.py:337`), deliberately scans by index not heap (`_corpus_facts`), and uses
   run-unique names + atomic manifest swap. Residual verify item (§7): confirm the live-read
   path's reader semantics amount to a consistent snapshot (checkpoint+quiesce or
   online-backup-API-equivalent), not a racing raw copy.

---

## 3. The phases, v1 of record

### Phase A — the single file, hardened (NOW-ish; most of it already exists)

What already exists in the tree (verified 2026-07-12): `journal_mode=WAL`,
`synchronous=NORMAL`, `busy_timeout=30000` (`src/database/session.py`); the process-wide
single-writer gate (`src/database/writer.py`); inter-pass `PRAGMA wal_checkpoint(TRUNCATE)`
through `write_lock()` (`src/scheduler/hygiene.py`, the P0.3 fix) + collector-idle maintenance
(S2.2 `run_idle_maintenance`); collector write-batching (P1.8) — the biggest FTS-segment lever,
since every commit creates a level-0 FTS segment; no-bare-`SCAN` plan discipline
(`slowquery.py` + the S2.6 rule); `storage_composition` now reporting `auto_vacuum` +
`free_bytes_note` (S3.4); VACUUM correctly banned at scale (DB-10 §2).

**The genuine Phase-A deltas (small, buildable next wave):**
- **`journal_size_limit` is set NOWHERE** (grep-verified 2026-07-12) — set it alongside the
  existing TRUNCATE checkpoints so the WAL file has a resting ceiling between passes.
- **Checkpoint-starvation honesty:** the official hazard is "always at least one active
  reader ⇒ no checkpoint completes ⇒ WAL grows without bound" — precisely our workload
  (continuous ingest + always-on UI polls/analytics). The inter-pass TRUNCATE takes the
  write gate (blocks writers) but LONG READERS can still starve it. Delta: measure it (the
  GAMMA `wal_bench` already tracks `wal_peak_bytes` vs post-checkpoint) and, if starvation is
  observed live, add a bounded checkpoint-retry/reader-quiesce window in idle maintenance.
  Degrade loudly: surface WAL size in the storage diagnostic so an unbounded `-wal` is VISIBLE.
- **The two irreversible CREATE-time seams** are OWNED BY THE DB-10 MEMO (S3.4) — this plan
  defers to it as the decision doc: **`auto_vacuum=INCREMENTAL` for NEW corpora (DB-10 §1a,
  recommended; maintainer ruling pending)** and **`page_size`/`cipher_page_size` (DB-10 §1b,
  measure 4K vs 16K on GAMMA before deciding; NOT a substitute for Phase C — inflating pages
  to dodge the 17.5 TB ceiling would tax small-row reads; offload text instead)**.
  RECONCILIATION NOTE, recorded for honesty: the planning conversation briefly leaned
  "auto_vacuum: no — append-mostly workloads recycle free pages." The DB-10 memo's
  churn evidence supersedes that lean: the delete-then-reinsert on EVERY re-index +
  `prune_orphan_keywords` + newsletter re-imports produce real, recurring freelist churn, and
  the seam is one-way (a corpus created without it can never reclaim at scale). INCREMENTAL
  (never FULL — that puts reclaim on the commit path) at ~0.2% overhead is the right call for
  new stores; existing stores honestly keep the full-VACUUM-or-nothing path (stated in the UI).

### Phase B — REDRAWN: split along the disposable/non-disposable axis (was: role split)

The original sketch's `corpus.db` + `index.db` + `fts.db` role split is **DEAD** — under WAL a
crash mid-ingest could commit the article file and not the mentions file (report §1.5/§6.2,
three primary SQLite sources; and rollback-journal mode, which restores cross-file atomicity
via the super-journal, would serialize readers against the writer — unacceptable for this
workload). The redraw:

- **ONE durable SQLCipher file** keeps everything referentially coupled: articles (metadata),
  keyword mentions, analytics/provenance rows. An ingest transaction stays genuinely atomic.
- **Split out ONLY the disposable/immutable:**
  - **`fts.db`** — the corpus FTS index in its own encrypted file, as
    `CREATE VIRTUAL TABLE … USING fts5(…, content='', contentless_delete=1)`. Rowid = article
    id; text resolves from the durable file (or the Phase-C store) on demand. Disposable by
    contract: crash-desync is repaired by RE-FEEDING from source, never by cross-file
    atomicity. Bonuses: no second on-disk copy of article text (a content-owning FTS table
    stores one — report §2.1); backups exclude it as rebuildable; the boot-time
    `ensure_fts` rebuild-risk class (the A1 unlock bug family) retires — but note
    **contentless tables have NO internal `'rebuild'`**, so the self-heal path becomes
    "re-feed from source," which must be a resumable background job, not a boot blocker.
  - **The Phase-C blob packs** (immutable by construction — see below).
- **Verified facts easing this** (2026-07-12): the corpus index is external-content today
  (`fts.py:219`, `content='articles'` — same-file, legal); the ONLY FTS5 `snippet()` consumer
  is the SEPARATE wiki `dump_pages` index (`src/wiki/dump_index.py:258`), so converting the
  ARTICLE index to contentless is snippet-safe (the timemap `_snippet()`s are plain Python);
  stdlib SQLite here is 3.45.1 ≥ the 3.43 `contentless_delete` floor. OPEN verify item (§7):
  the bundled sqlcipher3 build's SQLite version (expected ≥3.43; one-liner in the py3.13 venv).
- Each ATTACHed file has its OWN `-wal`/`-shm` and checkpoint cycle — the Phase-A governance
  applies per file.
- If the durable file itself must someday split for size, it splits by **hash-sharding**
  (§3-bis), where each shard is internally atomic — never by role under ATTACH.

### Phase C — BROUGHT FORWARD + re-primitived: the packed, keyed, content-addressed text store

Phase C is what keeps SQL under the ~17.5 TB default-page ceiling, shrinks the hot
metadata/index working set, and is the generalization of the DB-10 §4 tiered-retention escape
hatch + the K5 WARC seam (raw text relocates; the index + every mention/analytic/metadata row
stays HOT, so "since 1995" costs the same reachability as "last 30 days"). It is MANDATORY at
the target scale, so it outranks the old Phase-B ambitions. Primitives (all changed from the
sketch, per report §3/§6.3 — modeled on restic/Perkeep/Borg, all GPLv3-compatible):

- **PACK, never scatter:** many article-text blobs per bounded (~8–16 MB) immutable container
  with a recoverable per-pack manifest (Perkeep-blobpacked-style: data recoverable from packs
  alone if the index is lost) + a shallow 2-hex-fanout directory over PACKS. One file per
  article at 10⁸–10⁹ articles is an ext4/readdir/fsck/rsync catastrophe — banned.
- **KEYED addressing (the confirmation-attack fix):** the internal blob address is
  **HMAC-SHA-256 under a passphrase-derived key**, and on-disk pack names are opaque/random.
  The plaintext-hash→(pack, offset) map lives ONLY inside the encrypted SQL. This preserves
  deterministic dedup while making it impossible for someone who copies the disk to (a) test
  "is this leaked document in the journalist's archive?" or (b) see duplicate structure.
  Source-protection threat model, first-class. (The K1 content-multihash INSIDE the encrypted
  DB is unaffected — the leak was only ever about on-disk names.)
- **Encrypt PACKS, not blobs**, with **OOENC2** (our shipped streaming AEAD) under the §5 KDF
  hierarchy — per-pack random nonce-prefix/subkey; age-on-packs is the recorded fallback
  (maintainer ruling, §8). Never plain AES-GCM with ad-hoc nonces (the ~2³²-message
  nonce-collision cliff is why the framed construction exists).
- **Compression BELOW encryption, per-source zstd dictionaries** (validated by the report:
  dictionaries are the payoff for small same-shape texts; "no universal dictionary") — with a
  **versioned dictionary REGISTRY inside the encrypted store, carried by backups**: losing a
  dictionary = its blobs are undecodable forever, so the registry is critical infrastructure
  (registry entry per dictionary, external-artifacts-style discipline). This is also where
  corpus compression comes from — NOT from the SQL codec (no mature open package does
  encryption+page-compression together; page encryption kills page compressibility).
- **The blob store is a second consistency domain** (SQL↔filesystem, same non-atomicity family
  as §Phase-B): write the immutable pack/blob FIRST, reference it from SQL SECOND; a crash
  leaves at worst an orphaned blob, reclaimed by a **mark-and-sweep GC over SQL references**
  (git's discipline). Never the reverse order.
- **Dedup: ON, consciously** (ruling to confirm, §8): wire/syndication duplication makes the
  space win real; the residual equality/length leak is confined to passphrase holders by keyed
  addressing + is disclosed in the design docs (degrade loudly ethic). NOTE the interaction
  with DB-10 §5 near-dup folding: content-addressing gives EXACT-duplicate folding for free;
  NEAR-dup folding (different bytes, same story) stays a separate, measure-gated decision.
- **Reader/UX contract:** opening a cold article is a transparent local read; default posture
  keeps recent text hot; performance never DEPENDS on the store (it's a bytes relocation, not
  a reachability change).

### Phase-bis (CORE, not contingency): FTS hash-sharding + the fan-out-merge layer

Promoted from "contingency E2" per report §5.7 (the single biggest un-derisked risk: published
FTS5 experience tops out ~1–15 M docs, already sharded, with multi-second common-term latency;
our target is 10–100× beyond that).

- **Shard = hash(article_id) mod N** — time-neutral by construction, which is exactly why
  time-sharding is banned but hash-sharding is not (cross-time recall preserved: every query
  fans out to ALL shards ALWAYS; no shard is "old").
- Starting hypothesis ~1 M docs/shard (the one public datapoint) ⇒ 100–1000+ shards at the top
  of the range; each shard its own contentless-delete FTS file with per-shard budgeted merges.
- **Fan-out-and-merge honesty item to design in:** BM25 scores are computed per-shard from
  per-shard term statistics, so cross-shard rank-merge is APPROXIMATE unless global term stats
  are maintained. Either maintain global stats or DISCLOSE the approximation (method + n, the
  house style). Also budget the fan-out cost: N shards × per-shard query must stay within the
  snappy bar — measure, don't assume.
- **PROTOTYPE BEFORE COMMITTING (the plan's most valuable next empirical step):** FTS5 at
  50–100 M synthetic docs — single index vs sharded, query latency knee, merge behavior,
  tombstone accumulation. The GAMMA corpus generator + the AppVM recursive environment
  (see `PLANNING_2026-07-12_OPTIMIZATION_PROGRAM.md` §6) are the venue. No architecture
  commitment until this has numbers.

---

## 4. Top-end honesty

Even with text offloaded, ~1.1 B articles ⇒ ~9.2 B+ mention rows in the durable file — it
approaches the 17.5 TB ceiling from the mentions side at the extreme top of the range. The
redraw already accommodates the answer (hash-shard the durable store; each shard internally
atomic), but state it plainly: **50 TB is not reachable by any single-file design**; the plan
gets there by sharding, and the 5 TB milestone should be treated as the proving ground.

---

## 5. The KDF hierarchy (design item — one passphrase, several crypto domains)

One passphrase must deterministically derive EVERY key, domain-separated (HKDF with explicit
info strings, documented + test-vectored): the SQLCipher key (as today) · the pack AEAD key ·
the HMAC blob-address key · the dictionary-registry integrity key. Rules: no second key
surface, no recovery key (the standing no-recovery ethic — record the accepted risk that a
forgotten passphrase is total loss of a multi-TB corpus); memory hygiene (locking/zeroization)
extends to the blob path, where plaintext transits process memory outside SQLCipher's mlock;
rekey/passphrase-change = re-wrap strategy must be designed WITH the hierarchy (a passphrase
change must not force re-encrypting 50 TB of packs — wrap per-domain keys under a
passphrase-derived KEK so only the wrapping re-derives).

---

## 6. Watch list (no action now; conditions stated)

- **sqlite3mc** (MIT; `pip install apsw-sqlite3mc`; reads the SQLCipher format;
  ChaCha20-Poly1305 = no AES-NI dependency — the aging-laptop case): BENCHMARK-ONLY for now.
  Gate for going further: a measured ChaCha20-vs-AES-CBC comparison on a no-AES-NI CPU (the
  AppVM/an old laptop), plus a full migration design (the connect factory, unlock flow, and
  every crypto assumption re-audited). The format read-compat keeps the door open cheaply.
- **libSQL** (MIT): track until its encryption engine ships STABLE (the C fork's encryption is
  the same sqlite3mc core; the Rust engine is pre-1.0). Never bet the corpus on a beta.
- **DuckDB encryption**: the gate stays per P2.4 (§2.1). Re-verify the write-path claim at
  each major DuckDB version bump — if a future version genuinely writes AES-256-GCM without
  httpfs, the gate's empirical probe (`encryption_gate`) will pass and D1 unblocks by itself;
  that is the point of gating on a probe, not a version string.
- **wangfenjin/simple** (dual MIT/GPLv3; cppjieba) as an FTS5 CJK TOKENIZER — a genuinely new
  find, complementary to the B1 EXTRACTION segmenter (jieba/janome extras): the extraction
  side has words, but FTS search over zh/ja text still runs unicode61 (one-giant-token for
  space-free scripts). Gate: the loadable-extension-under-SQLCipher composition test + a
  bundling story (no first-party wheel; sha256-pinned vendored `.so`, external-artifacts
  registry entry). Cheap to adopt later: a tokenizer swap on a DISPOSABLE index is a re-feed,
  not a migration. Japanese alt: sqlite-vaporetto (MIT/Apache); pan-CJK: cwt/fts5-icu-tokenizer
  (MIT). AGPL options (Signal's, lindera) are usable-in-GPLv3 but not preferred.

---

## 7. Open verification items (cheap, do before the relevant slice)

1. Bundled sqlcipher3's SQLite version ≥ 3.43 (`python -c "import sqlcipher3;
   print(sqlcipher3.dbapi2.sqlite_version)"` in the py3.13 venv; expected 3.44+).
2. Backup live-read consistency semantics (§2.3) — confirm checkpoint+quiesce equivalence.
3. `PRAGMA cipher_memory_security` default (the report couldn't source it; check Zetetic docs
   or the sqlcipher3 build).
4. Loadable FTS5 tokenizer extensions compose with SQLCipher (extension loading must be
   explicitly enabled; untested with these specific tokenizers — report §8).
5. WAL starvation in the field: does the inter-pass TRUNCATE actually complete under live
   reader load? (`wal_bench` + a WAL-size line in the storage diagnostic.)

## 8. Rulings needed (maintainer) — each with the standing recommendation

| # | Ruling | Recommendation | Owner doc |
|---|---|---|---|
| 1 | `auto_vacuum=INCREMENTAL` for NEW corpora | YES (DB-10 §1a; one-way seam, decide before more field corpora exist) | DB-10 memo |
| 2 | `page_size` 4K vs 16K at creation | MEASURE on GAMMA first (DB-10 §1b); do not flip blind | DB-10 memo |
| 3 | Blob-store dedup ON (equality/length leak confined by keyed addressing, disclosed) | YES | this doc §3-C |
| 4 | Pack AEAD: OOENC2 (reuse, tested, no new dep) vs age (audited external, no-AES-NI) | OOENC2, age recorded as fallback | this doc §2.2/§3-C |
| 5 | Keyed HMAC blob addressing + opaque pack names (the confirmation-attack fix) | YES (should be uncontroversial — it strengthens the stated threat model) | this doc §3-C |
| 6 | sqlite3mc: authorize the benchmark trial (no migration) | YES, benchmark-only | this doc §6 |

## 9. Sequencing (post-S1–S6 program; nothing here preempts the running sessions)

1. **Phase-A deltas** (journal_size_limit + WAL visibility + starvation measurement) — small,
   next coding wave; pairs with the DB-10 §3 incremental-vacuum idle pass once ruling #1 lands.
2. **CREATE-time seams** in `connect.py`'s fresh-file branch, once rulings #1/#2 land.
3. **FTS split-out** (`fts.db`, contentless-delete, re-feed self-heal as a background job,
   backup exclusion) — the safe half of the old Phase B, independently valuable.
4. **FTS sharding PROTOTYPE at 50–100 M synthetic docs** (AppVM + GAMMA) — before any sharding
   code ships.
5. **Phase C spike** (pack format + KDF hierarchy + keyed addressing + GC over a synthetic
   corpus), then the real store behind a default-off seam, then default-on when proven.
6. Watch-list re-checks ride whatever session touches the neighboring code.
