# Phase C blob store — design note (2026-11-14)

**Status: DESIGN AND BENCHMARK ONLY. Nothing in the production store changes, and nothing here
authorises building the store; that is a separate decision after 0.5.1.** Opened by the
coordinator's ruling R700 (2026-11-14, under the maintainer's standing "use your best judgement"
rule) on the four storage rulings the maintainer answered on 2026-09-29 as Q1009 = RC03 =
`y, OOENC2, y, y`: blob dedup ON (row 3), OOENC2 for the pack AEAD (row 4), keyed-HMAC addressing
with opaque pack names (row 5), and the sqlite3mc benchmark trial (row 6, benchmark only).

> **The design choices in §3-§8 are PROVISIONAL, COORDINATOR-RULED (R707, 2026-11-14), and the
> maintainer has not reviewed them.** §10 lists each one with its ruling and condition.

Read with: [`STORAGE_5TB_PLAN.md`](STORAGE_5TB_PLAN.md) §3-C and §5 (the primitives),
[`STORAGE_5TB_REFRESH_2026-09-07.md`](STORAGE_5TB_REFRESH_2026-09-07.md) (Phase C is
ruling-gated, no longer mandatory: one file caps at 64 TiB at the ruled page size), and
[`STORAGE_RULINGS_ROUND2_2026-09-07.md`](STORAGE_RULINGS_ROUND2_2026-09-07.md) (why rows 3 and 5
are one argument). The benchmark is `scripts/blob_store_bench.py`; its method and full tables are
in [`BLOB_STORE_BENCH_2026-11-14.md`](BLOB_STORE_BENCH_2026-11-14.md), summarised in §9.

This note was read by an Opus correctness read, two security reads and the backup lane (Lane B);
their findings are folded in, and the ones that change a requirement are marked *(review)*.

## 1. What exists today

- Article text lives in `articles.content` (`src/database/models.py`, plain `Text`; the optional
  `compressed_content` column is separate) inside the one SQLCipher file, and the FTS5 index is
  external-content on that column (`src/database/fts.py`, `content='articles'`).
- OOENC2 (`src/safety/crypto.py`) is used only by backups: a STREAM-framed AES-256-GCM container,
  nonce = prefix(7) | counter(4) | final(1), 4 MiB frames, key from scrypt over the passphrase
  with the salt in the header. Its reader refuses any scrypt parameters other than the writer's.
- Panic wipe (`src/safety/panic.py` → `crypto_erase.quick_crypto_erase`) overwrites the first
  4 KiB (the salt page) of each SQLCipher file and its sidecars, so the corpus key can never be
  derived again, then fully overwrites and unlinks every other file under the data directory.
- There is no passphrase-change (`PRAGMA rekey`) path in `src/`.
- There is no blob store, pack file or sqlite3mc use anywhere in `src/`.

## 2. Shape

```
<data dir>/
  corpus.db (SQLCipher)          articles(..., blob_addr), blobs, packs, blob_staging, blob_keys
  blobs/<2 hex>/<32 hex>         immutable packs, every one exactly the same size, names random
```

Four tables join the SQLCipher file. `blobs(addr PK, pack_id, off, len, codec)` maps an address
to its place in a pack. `packs(id, name, epoch, frame, n_frames, plain_len, ct_len)` describes
each pack, including the exact ciphertext length it must have. `blob_staging(id, addr UNIQUE,
body)` holds bodies not yet sealed. `blob_keys(epoch, key)` holds the master keys (§3). The
address → place map exists ONLY inside the encrypted file.

**What a person who copies the disk learns** *(review: the first draft said "nothing else")*:
the number of packs (so, in steps of one pack, the total stored volume); each pack's creation and
modification time and its inode order (an ingest timeline at pack granularity); when packs were
rewritten or removed by GC (when deletions happened, roughly how much); and, where the filesystem
records it, access time (which packs were read recently). Mitigations the build must apply:
packs are created `0600` in `0700` directories; the mtime is set to a constant after the write;
reads open with `O_NOATIME` where the platform has it; the packer seals on a fixed timer rather
than per collection pass. ctime cannot be set and stays a residual leak, stated.

## 3. Keys — one passphrase, no second key surface

- At store creation a random 256-bit **blob master key** (BMK) is generated and written into
  `blob_keys` **inside the SQLCipher file**. It is encrypted at rest by the same page encryption
  as every article, and the passphrase remains the one thing a person needs. This is the
  KEK-wrap that STORAGE_5TB_PLAN §5 asked for, with SQLCipher as the wrap, rather than §5's
  deterministic derivation from the passphrase.
- Working keys come from it through HKDF-SHA-256 with fixed, versioned labels:
  `oo/v1/blob-address` (the HMAC key), `oo/v1/pack-aead` (the pack key), and per pack
  `oo/v1/pack-subkey\0 || pack name (16 raw bytes)` (§4). A later dictionary registry would
  take `oo/v1/dict-integrity`. The build ships test vectors for every label.
- **Why stored rather than derived** — the differentiator is **panic wipe**: destroying the salt
  page makes the BMK unreadable, so every pack is noise at once, and a passphrase obtained later
  (coerced, say) recovers nothing from the packs. A passphrase-derived pack key would survive the
  wipe for anyone who later learns the passphrase. A second, smaller reason: a passphrase
  change, if one is ever added, would be a SQLCipher rekey and would re-wrap the BMK with it.
- **Key epochs** *(review)*. A rekey that keeps the same BMK would be a regression: anyone with an
  OLD copy of `corpus.db` (or an old backup) and the OLD passphrase would get the BMK and could
  read every pack written AFTER the change, given a later copy of `blobs/`. So a passphrase change
  creates a new epoch: a fresh BMK for new packs, recorded in `packs.epoch`; older BMKs stay
  inside the database to read older packs; an optional background re-seal retires an old epoch.
  **Stated exposure that remains:** packs of an old epoch stay readable by anyone holding an old
  copy plus the old passphrase until they are re-sealed.
- **What a backup copy of the database file alone gives** (R707's condition): with the
  passphrase, the BMK of every epoch the copy knew, and so every pack of those epochs, wherever
  those packs are later found; without the passphrase, nothing (the BMK is under SQLCipher's
  encryption like any article). That is the same reach the copy already has over the article
  text it holds today; it adds the packs written under the epochs it knew.
- **Plaintext stores** *(review)*. Under `OO_DB_PLAINTEXT=1` the database is not encrypted, so a
  BMK stored in it would lie in the clear beside the packs: encrypted-looking packs under a
  plaintext key would be fabricated security. The store therefore follows the database's at-rest
  state: on a plaintext database, packs are written unencrypted and labelled so (or the store is
  not created at all, open question Q-W9). Never AEAD packs under a plaintext key.
- The BMKs and their derived keys exist in process memory only while the store is unlocked and
  are dropped at lock. They are never written outside the encrypted file, never logged, never
  put in argv. The memory caveat is the existing one, stated rather than improved: SQLCipher's
  `cipher_memory_security` is OFF by default (measured 2026-09-07), Python cannot reliably zero
  a `bytes` object, and decompressed bodies sit in Python memory outside any mlock. A compromised
  running session can read these keys and bodies, exactly as it can read the SQL key today. The
  threat model is unchanged: a seized or copied machine, never a live one.

## 4. Envelope — OOPACK1: OOENC2's construction, sized for single-article reads

- Packs carry their own magic, **`OOPACK1`** plus a version byte (R707, Q-W2), and reuse the
  OOENC2 STREAM construction unchanged in its security argument (counter nonce, final flag binds
  the end, so truncation, reordering and extension fail authentication). A separate magic means
  no backup reader ever treats a pack as an OOENC2 file and tries to derive a key from it.
- Header: magic, version, frame size, frame count, pack name. The header is the **associated
  data of every frame**, and the reader compares it to the `packs` row before decrypting.
- **Per-pack subkey** `HKDF(pack key, "oo/v1/pack-subkey\0" || name)`: a nonce can never repeat
  across packs whatever their number, and a frame or a whole pack moved under another name fails
  authentication. Names are never reused, including by GC rewrites.
- **Frame size 64 KiB, not the 4 MiB backup default** (R707, Q-W3). Measured (§9): a single-article
  read from 4 MiB frames decrypts a whole 4 MiB frame, about 1.6 ms per article. Each frame adds a
  16-byte tag, 0.02 % at 64 KiB.
- **Every pack is exactly one fixed size** *(review)*: bodies, then zero padding, all inside the
  AEAD, to the target (8 MiB). The first draft let the last pack of every seal be partial, and
  compression is deterministic, so a pack holding one body would have given away that body's
  compressed length: an observer could compress a known document and look for a pack of that
  size, which is the confirmation attack row 5 exists to stop. Padding closes it; the residual
  leak is the pack count (§2). Bodies wait in staging until a pack fills, or until a maximum age
  after which a padded pack is sealed. A body larger than one pack needs size classes (Q-W10).
- **Every read checks the body against its address** *(review)*: `HMAC(k_addr, body) == addr`,
  a few µs, so a wrong offset, a snapshot paired with the wrong pack set or a rebuilt index can
  never return the wrong text silently.
- Each pack ends with an encrypted **trailer** listing its `(addr, off, len, codec)` entries, so
  the index can be rebuilt from packs and keys alone (the Perkeep property). A rebuild only
  re-attaches bodies to article rows that exist, so it can never bring back a deleted article
  (§7). Not in the prototype.
- Compression (zstd, zlib fallback) runs per body, below encryption, so no length leak crosses
  bodies. Per-source dictionaries are deferred: they need the versioned registry the 5TB plan
  describes, and a lost dictionary makes its bodies unreadable.

## 5. Addressing and dedup

- Address = `HMAC-SHA-256(k_addr, body bytes)` over the body before compression, so a codec
  change does not split identical bodies.
- Dedup: an ingest whose address already exists in `blobs` or `blob_staging` stores nothing new
  and points the article row at the existing address. No refcount is stored; reachability is
  decided by the GC's mark phase over `articles.blob_addr`.
- **The leak, stated as the maintainer ruled it:** a person who holds the passphrase can see
  which articles share a body and every body's length. A person who copies the disk sees
  neither: the addresses live inside the encrypted file, pack names are random, and every pack
  has the same size. A copier cannot test "is this leaked document here?" without the key.
- **Active dedup oracle, stated:** someone who can get a document collected (by publishing it to
  a watched feed) and can inspect the disk before and after could watch for growth; with
  fixed-size packs this resolves only to "a pack was or was not added", which mixes with every
  other body sealed in the same interval. Weak, not zero.
- `articles.hash` stays as it is. This is dedup of identical bodies under different rows
  (syndication), beneath the row-level rule. Near-duplicate folding stays a separate decision.

## 6. Write path and crash safety

Two consistency domains (SQL and the filesystem) are ordered so a crash can only leave garbage,
never a dangling reference:

1. **Ingest** writes the article row, its FTS row and the body into `blob_staging`, in ONE SQL
   transaction (R707, Q-W4). Readers find a staged body there. Nothing touches the filesystem at
   ingest, so ingest atomicity is exactly today's.
2. **The packer** (a background `is_writer` job, under the writer gate) writes a pack to
   `<name>.tmp` (`0600`), fsyncs it, renames it, fsyncs its directory and **every directory it
   created on the way** *(review)*, and only THEN commits one SQL transaction that inserts the
   `packs` and `blobs` rows and deletes the staging rows.

**The staging window** (R707's condition): between ingest and sealing, a body sits in
`blob_staging` as a row of the SQLCipher file, and after sealing its old pages sit on the
freelist and in WAL frames until reused or vacuumed. All of that is inside the SQLCipher file and
under its page encryption, exactly as `articles.content` is today; nothing in the window is
plaintext on disk. With fixed-size packs and a maximum age, the window is bounded by that age.

| Crash point | State after restart | Repair |
|---|---|---|
| during ingest | transaction rolled back | none |
| pack temp written, not renamed | a `.tmp` file nobody references | the orphan sweep deletes it |
| pack renamed, SQL not committed | a whole pack nobody references; bodies still staged | the orphan sweep deletes it; the packer re-seals the staged bodies |
| after SQL commit | consistent | none |

The orphan sweep runs **under the writer gate** *(review)*, so it can never see the window
between a running packer's rename and commit; a grace period alone could be outlasted by a
suspended packer.

## 7. Garbage collection and deletion

Mark-and-sweep: every address referenced by `articles.blob_addr` is live; any other `blobs` row is
dead. A pack whose live bytes fall below a threshold is rewritten (live bodies copied into a new
pack through the same crash-ordered path), its old row deleted in the same SQL transaction that
points the bodies at the new pack, and its file unlinked only after that commit. GC is an
`is_writer` job, so R659's restore refusal covers it.

**Deletion retention, stated** *(review)*: a deleted article's body stays decryptable inside its
pack, to a passphrase holder, until a rewrite of that pack. "I deleted it" is therefore not true
of the bytes until then. A user-initiated purge forces the rewrite of every affected pack at
once; ordinary deletes wait for the threshold. The trailer rebuild never resurrects (§4).

## 8. Backup, restore, panic wipe

Lane B read this section (R707, Q-W5 pending their read) and asked for the gaps below.

- **Packs travel inside the encrypted backup volumes**, as their own member category in the
  volume manifest with size and checksum, never copied raw beside it *(review)*: raw copies with
  random names and sizes would link a backup to the live store and show ingest volume per period.
  This is a backup-format bump through the S04-04 normaliser path, in both directions: an older
  reader refuses a pack-bearing backup by name, and an older backup restores through the Q-W7
  migration.
- **Every backup set carries every pack its snapshot references** *(Lane B must-fix)*. "Copy only
  new packs" would make a newer set depend on packs held only by an older one, and deleting the
  old set would silently break the newer. An incremental chain may come later only if it is
  explicit and the restore refuses, by name, a set whose chain is broken.
- **GC lease** *(Lane B must-fix)*: the backup takes it before the snapshot and holds it until the
  last pack is in the volumes. Taking it waits for any in-flight GC compaction to finish both its
  commit and its unlinks, and also stops the orphan sweep. A persisted lease carries an expiry
  tied to its job, so a dead backup cannot block GC for ever.
- **Replace-restore**: packs are written and verified (size, checksum, header) BEFORE the database
  swap, so a crash leaves only orphan packs. Packs count in the restore's preflight and in its
  declared-size bound. A referenced pack that is missing, the wrong length (`packs.ct_len`) or
  fails authentication makes the restore refuse and name it; a full-authenticate pass is
  offered. The packs the pre-restore rollback snapshot references are treated as live, so the
  orphan sweep cannot delete them *(Lane B must-fix)*.
- **At open**, the same missing-pack check runs and names the pack and how many articles it
  affects, rather than failing on the first read.
- **Merge-restore (row-level)**: the source corpus has its own BMKs, so its addresses and packs
  mean nothing in the target. The merge reads each body through the source's keys, in memory only,
  and re-ingests it into the target's staging (new address, new pack). Its preflight counts the
  staging growth and the new packs. Cost scales with the merged text.
- **Panic wipe**: the guarantee is the destroyed salt: once page 1 of `corpus.db` is overwritten,
  every BMK and so every pack is unreadable. But the current quick pass then FULLY OVERWRITES
  every remaining file under the data directory, on the premise that those are small side files;
  a multi-TB `blobs/` would turn the instant erase into hours. **Required change** *(review)*:
  after the salt is gone, `blobs/` is only unlinked, never overwritten, and a test proves the
  erase stays fast with a large pack tree; the optional free-space scrub covers the freed blocks
  as it does today. **A test also proves that after the quick pass no pack can be decrypted**
  (R707's condition). Honest limits: a backup copy elsewhere still holds its own keys, and an
  inherited issue in the current erase (the `-wal` sidecar is overwritten only in its first
  4 KiB, while later copies of page 1 with the salt can sit deeper in it) is reported separately
  and must be fixed before this store relies on the wipe.

## 9. Benchmark (measured)

Machine: 4-vCPU Xeon with AES-NI, SQLCipher 4.20.0 (sqlcipher3 0.6.5). 50,000 synthetic
articles, median body 3.1 KB, 233 MB of text, 20 % byte-identical bodies; medians of 3 runs.
Method, variants and spread: [`BLOB_STORE_BENCH_2026-11-14.md`](BLOB_STORE_BENCH_2026-11-14.md).

| | today (SQLCipher) | prototype, 4 MiB frames | prototype, 64 KiB frames |
|---|---|---|---|
| ingest, articles/s | 2,267 | 2,001 | 2,143 (+ seal 0.07 ms/article, then a vacuum) |
| read one article, fresh connection, p50 | 37 µs | 1,769 µs | 65 µs (78 µs with zlib) |
| read one article, warm, p50 | 5 µs | 1,696 µs | 48 µs |
| feed (newest 100) / search + 10 bodies, p50 | 60 µs / 31 ms | 51 µs / 44 ms | 60 µs / 31 ms |
| disk | 434 MB | 346 MB | 346 MB (246 MB with zlib; 389 MB with no duplicates) |

What it decides: the frame size (§4: 4 MiB frames cost nearly 50x per read); that a 64 KiB read
is about 1.8x today's from a fresh connection and about 10x warm, because SQLCipher's decrypted
page cache has no counterpart yet (all under 0.2 ms); that the disk win is dedup plus
compression plus the row overhead of text in 16 KiB pages (-10 % with no duplicates at all,
-20 % at 20 % duplicates, -43 % with zlib); and that ingest stays within ~15 % of today.

**sqlite3mc was NOT measured.** The sandbox's safety check refused the `apsw-sqlite3mc`
download and it was not worked around; the script's two sqlite3mc engines have never been
executed. The raw AEAD figures in the bench file (AES-256-GCM about 3x ChaCha20-Poly1305 on this
AES-NI CPU) are not a substitute for the engine comparison: the engines differ in MAC and KDF as
well as cipher.

## 10. Rulings (provisional, coordinator-ruled R707, maintainer has not reviewed) and open questions

| # | Question | R707 | Condition |
|---|---|---|---|
| Q-W1 | BMK random, stored inside SQLCipher vs derived from the passphrase | stored | both security reads agree; §3 states what a DB copy alone gives; panic wipe tested to kill packs |
| Q-W2 | Pack header | new magic `OOPACK1` with OOENC2 framing | – |
| Q-W3 | Pack frame size | 64 KiB | – |
| Q-W4 | Ingest stages in SQL, background packer seals | yes | §6 states the staging window and its encryption |
| Q-W5 | Backup format: packs inside volumes, GC lease, format bump | yes, pending Lane B | Lane B's read is folded into §8 |
| Q-W6 | FTS conversion to contentless-delete | ships WITH the Phase B FTS split, not before | – |
| Q-W7 | Migration | default-off seam, resumable background move, bounded `incremental_vacuum`; default-on only after a field corpus round-trips backup and restore | – |
| Q-W8 | sqlite3mc | on the maintainer's optional list | "not measured" stated plainly (§9) |

Open, not yet ruled, raised by the reviews:

- **Q-W9 — Plaintext stores.** Write packs unencrypted and labelled on an `OO_DB_PLAINTEXT=1`
  store, or refuse to create the blob store there. Recommend: refuse (one less mode to test).
- **Q-W10 — Bodies larger than one pack.** Split across packs, or a few coarse size classes of
  pack. Recommend size classes (8 MiB, 64 MiB), each padded.
- **Q-W11 — Key epochs.** Confirm that a passphrase change (none exists today) must create a new
  epoch, and whether old epochs are re-sealed automatically or only on request.
- **Q-W12 — Packer maximum age.** How long a body may wait in staging before a padded pack is
  sealed. Recommend 24 h: at field rates one 8 MiB pack is hours of bodies.
- **Q-W13 — Whole-store rollback.** Restoring an older database together with its older packs is
  undetectable by design (there is no external anchor). Recommend: accepted, stated.
