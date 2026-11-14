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
  4 KiB (the salt page) of the main, custody and lane databases and their sidecars, so the
  corpus key can never be derived again, then fully overwrites and unlinks every other file
  under the data directory.
- Backup and restore stage **plaintext** copies of the corpus by design: `.restore-*` holds the
  decrypted volumes and corpus, `.oo-backup-*` and a killed backup's `.bak-build-*` hold full
  plaintext snapshots (`src/backup/stream_backup.py`), and merge-restore attaches its staged
  members as plaintext (`src/backup/merge.py`). `.bak-build-*` sits at the backup destination,
  often outside the data directory.
- There is no passphrase-change (`PRAGMA rekey`) path in `src/`.
- There is no blob store, pack file or sqlite3mc use anywhere in `src/`.

## 2. Shape

```
<beside the database>/           (wherever main_db_path() resolves, which may be outside the data dir)
  corpus.db (SQLCipher)          articles(..., blob_addr), blobs, packs, blob_staging, blob_keys
  blobs/<2 hex>/<32 hex>         immutable packs, every one exactly the same size, names random
```

Four tables join the SQLCipher file. `blobs(addr PK, pack_id, off, len, codec)` maps an address
to its place in a pack. `packs(id, name, epoch, frame, n_frames, plain_len, ct_len)` describes
each pack, including the exact ciphertext length it must have. `blob_staging(id, addr UNIQUE,
body)` holds bodies not yet sealed. `blob_keys` holds the master keys per epoch and the one
address key (§3). `pack_intents(name)` records a pack about to be written (§6). The address →
place map exists ONLY inside the encrypted file. `pack_pins(name, snapshot)` keeps the packs a retained rollback snapshot references (§8).
`blobs/` lives beside the database file, not
at an assumed `<data dir>`, because `main_db_path()` honours `DATABASE_URL`; panic wipe resolves
it the same way.

**What a person who copies the disk learns** *(review: the first draft said "nothing else")*:
the number of packs (so, in steps of one pack, the total stored volume); each pack's creation and
modification time and its inode order (an ingest timeline at pack granularity); when packs were
rewritten or removed by GC (when deletions happened, roughly how much); and, where the filesystem
records it, access time (which packs were read recently); the shard directories' mtime and ctime,
which change on every pack added; and the growth of the database file and its WAL as bodies are
staged. Mitigations the build must apply: packs are created `0600` in `0700` directories; pack
and shard-directory mtimes are reset to a constant after each seal and each GC unlink; reads open with `O_NOATIME`
where the platform has it; **the packer seals only at fixed timer ticks** (it seals every full
pack it has at a tick, and a padded partial one only once the oldest staged body reaches the
maximum age), never when a pack happens to fill, so pack times record the timer and not the
ingest rate. Residual leaks, stated: ctime and creation time (btime, not settable on ext4 or
btrfs), the per-tick pack count, and database/WAL growth between two views of the disk.

## 3. Keys — one passphrase, no second key surface

- At store creation a random 256-bit **blob master key** (BMK) is generated and written into
  `blob_keys` **inside the SQLCipher file**. It is encrypted at rest by the same page encryption
  as every article, and the passphrase remains the one thing a person needs. This is the
  KEK-wrap that STORAGE_5TB_PLAN §5 asked for, with SQLCipher as the wrap, rather than §5's
  deterministic derivation from the passphrase.
- Working keys come from it through HKDF-SHA-256 with fixed, versioned labels:
  `oo/v1/pack-aead` from an epoch's BMK gives that epoch's pack key, and each pack's subkey is
  `HKDF(pack key, "oo/v1/pack-subkey\0" || pack name (16 raw bytes))` (§4). A later dictionary
  registry would take `oo/v1/dict-integrity`. The build ships test vectors for every label.
- **The address key does not rotate** *(review)*. It is one random key stored in `blob_keys`
  beside the epochs, never re-derived per epoch: if it changed with the epoch, dedup would split
  across epochs and a GC re-seal into a new epoch would make the read check fail on old
  addresses. Its exposure is the dedup leak of §5, already confined to passphrase holders.
- **Why stored rather than derived** — one erase point and a free re-wrap. Everything a pack
  needs is inside the SQLCipher file, so destroying its salt page is the single act that makes
  every pack noise, and a passphrase obtained later (coerced, say) recovers nothing from the
  packs. (A pack key derived from the passphrase with a salt kept on page 1 would die with the
  wipe too; one derived without such a salt would not.) And a passphrase change, if one is ever
  added, would be a SQLCipher rekey that re-wraps the stored keys without touching a pack.
- **Key epochs** *(review)*. A rekey that keeps the same BMK would be a regression: anyone with an
  OLD copy of `corpus.db` (or an old backup) and the OLD passphrase would get the BMK and could
  read every pack written AFTER the change, given a later copy of `blobs/`. So a passphrase change
  creates a new epoch: a fresh BMK for new packs, recorded in `packs.epoch`; older BMKs stay
  inside the database to read older packs; an optional background re-seal retires an old epoch.
  **Stated exposure that remains:** packs of an old epoch stay readable by anyone holding an old
  copy plus the old passphrase until they are re-sealed. A rekey must also checkpoint and
  truncate the WAL so no frame under the old key remains (Q-W11).
- **What a backup copy of the database file alone gives** (R707's condition): without the
  passphrase, nothing (the keys are under SQLCipher's encryption like any article). With the
  passphrase, the BMK of every epoch the copy knew, and so **every pack of those epochs, including
  packs written long AFTER the copy was made**, given a later copy of `blobs/`. Because epochs
  rotate only on a passphrase change, and there is no passphrase change today, a copy taken on
  day one reaches forward for the life of the store. That is wider than today, where an old copy
  reaches only the text it holds. Rotating the epoch on a schedule or at every backup (a new BMK
  for new packs only, cheap) caps that reach; Q-W14 asks for the cadence.
- **Plaintext stores** *(review)*. Under `OO_DB_PLAINTEXT=1` the database is not encrypted, so a
  BMK stored in it would lie in the clear beside the packs: encrypted-looking packs under a
  plaintext key would be fabricated security. The store therefore follows the database's at-rest
  state: on a plaintext database, packs are written unencrypted and labelled so (or the store is
  not created at all, open question Q-W9). Never AEAD packs under a plaintext key.
- The BMKs and their derived keys exist in process memory only while the store is unlocked and
  are dropped at lock. They are never written outside the encrypted file, never logged, never
  put in argv. **This conflicts with today's plaintext staging** *(review)*: a plaintext staging
  copy of a database that holds `blob_keys` would hold every epoch key and the address key in
  clear. So once this store exists, every staging conversion leaves `blob_keys` out (keys are
  read through an encrypted connection to the source instead), or the staging copies stay
  SQLCipher-encrypted; Q-W17 asks which. The memory caveat is the existing one, stated rather than improved: SQLCipher's
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
  read from 4 MiB frames decrypts a whole 4 MiB frame, about 1.7 ms per article. Each frame adds a
  16-byte tag, 0.02 % at 64 KiB.
- **Every pack is exactly one fixed size** *(review)*: bodies, then zero padding, all inside the
  AEAD, to the target (8 MiB). The first draft let the last pack of every seal be partial, and
  compression is deterministic, so a pack holding one body would have given away that body's
  compressed length: an observer could compress a known document and look for a pack of that
  size, which is the confirmation attack row 5 exists to stop. Padding closes it; the residual
  leak is the pack count (§2). Bodies wait in staging until a timer tick (§2). **The size
  equation:** file size = header + n_frames × (frame + 16), with n_frames fixed by the pack size,
  and the trailer, the bodies and the padding together fill exactly the fixed plaintext size; the
  trailer is budgeted inside it before padding, never appended after it *(review)*, or the
  length would vary with the number of bodies. A body larger than one pack is split across
  fixed-size packs rather than given a larger size class, because a size class would announce
  "a body over 8 MiB exists", the rare large document a confirmation attack looks for (Q-W10).
  A split body needs a segment table (`blob_segments(addr, seq, pack_id, off, len)`) and segment
  entries in the trailers; all its segments are sealed in one commit, and the address check runs
  on the reassembled body *(review)*.
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
  a watched feed) and can inspect the disk before and after could watch for growth. In the packs
  this resolves only to "a pack was or was not added" at a timer tick, mixed with every other
  body of the interval; but a staged body also grows the database and its WAL by whole pages,
  which is a finer signal between two views of the disk. Weak, not zero; stated, not fixed.
- `articles.hash` stays as it is. This is dedup of identical bodies under different rows
  (syndication), beneath the row-level rule. Near-duplicate folding stays a separate decision.

## 6. Write path and crash safety

Two consistency domains (SQL and the filesystem) are ordered so a crash can only leave garbage,
never a dangling reference:

1. **Ingest** writes the article row, its FTS row and the body into `blob_staging`, in ONE SQL
   transaction (R707, Q-W4). Readers find a staged body there. Nothing touches the filesystem at
   ingest, so ingest atomicity is exactly today's.
2. **The packer** (a background `is_writer` job that holds the writer gate from its first commit
   to its last) first commits a `pack_intents(name)` row for a freshly drawn random name, with
   `synchronous=FULL` so the intent cannot be lost while its pack survives *(review)*, then writes
   the pack to `<name>.tmp` (`0600`), fsyncs it, renames it **without replacing** (link then
   unlink, or `RENAME_NOREPLACE`), so a name collision with a quarantined pack fails loudly,
   fsyncs its directory and **every directory it created on the way** *(review)*, and only THEN
   commits one SQL transaction that inserts the `packs` and `blobs` rows, deletes the staging rows
   and deletes the intent. A retry after a crash always draws a NEW name, never one read back
   from an intent row, so a nonce key is never reused.

**The staging window** (R707's condition): between ingest and sealing, a body sits in
`blob_staging` as a row of the SQLCipher file, and after sealing its old pages sit on the
freelist and in WAL frames until reused or vacuumed. All of that is inside the SQLCipher file and
under its page encryption, exactly as `articles.content` is today; nothing in the window is
plaintext on disk. With fixed-size packs and a maximum age, the window is bounded by that age.

| Crash point | State after restart | Repair |
|---|---|---|
| during ingest | transaction rolled back | none |
| pack temp written, not renamed | a `.tmp` file and an intent row | the orphan sweep deletes the `.tmp` and the intent |
| pack renamed, SQL not committed | a whole pack named by an intent row; bodies still staged | the orphan sweep deletes that pack and its intent; the packer re-seals the staged bodies under a new name |
| after SQL commit | consistent | none |

**The orphan sweep deletes only what an intent names** *(review)*: `.tmp` files, and packs whose
name sits in `pack_intents` with no `packs` row. Any OTHER pack the database does not reference
is reported and quarantined, never deleted automatically. Even an intent-named pack is read
through its trailer first and quarantined instead if any address in it is referenced by
`articles.blob_addr` but present in neither `blobs` nor `blob_staging` (a salvaged database can
keep the intent and lose the rows) *(review)*. All of this matters because an unreferenced pack
also arises from a
database opened at an older state, a repair or salvage output that lost rows, or a lost commit
(§7), and in each of those the "unreferenced" packs are live data, exactly what the trailer
rebuild exists to recover. The sweep runs **under the writer gate** *(review)*, so it never sees
a running packer's window between rename and commit.

## 7. Garbage collection and deletion

Mark-and-sweep: every address referenced by `articles.blob_addr` is live; any other `blobs` row is
dead. A pack whose live bytes fall below a threshold is rewritten (live bodies copied into a new
pack through the same crash-ordered path), its old row deleted in the same SQL transaction that
points the bodies at the new pack, and its file unlinked only after that commit **is durable**
*(review)*. The app runs WAL with `synchronous=NORMAL`, under which a committed transaction can
be lost to a power cut; losing the packer's commit only leaves an orphan pack and staged bodies,
but losing a GC commit after the unlink would leave rows pointing at a deleted pack, the bodies
gone for good. So every commit that precedes an unlink (GC rewrite, purge) runs with
`synchronous=FULL` or is followed by a durable checkpoint before the unlink, and a
fault-injection test drops the un-fsynced WAL tail after the commit and checks nothing is lost.
GC is an `is_writer` job, so R659's restore refusal covers it.

**Deletion retention, stated** *(review)*: a deleted article's body stays decryptable inside its
pack, to a passphrase holder, until that pack is rewritten, and even after the rewrite the old
pack's blocks can survive on disk after the unlink, still decryptable under the live epoch key.
Staged bodies linger in freelist and WAL pages, and the contentless FTS index keeps a deleted
article's tokens until a merge. "I deleted it" is therefore not true of the bytes. A
user-initiated purge forces the rewrite of every affected pack, runs with `secure_delete=ON` and
an FTS merge (as the newsletter purge in `src/backup/newsletter_export.py` already does), and
states the remaining limit on the old pack blocks. A stronger option, giving each pack its own
random key stored in its `packs` row so that deleting the row crypto-shreds the pack, costs the
trailer rebuild its independence from the database (Q-W15). The trailer rebuild never
resurrects (§4).

## 8. Backup, restore, panic wipe

Lane B read this section for Q-W5 (R707) and asked for the gaps below; they are folded in.

- **Packs travel inside the encrypted backup volumes**, as their own member category in the
  volume manifest with size and checksum, never copied raw beside it *(review)*: raw copies with
  random names and sizes would link a backup to the live store and show ingest volume per period.
  The volume manifest is plaintext JSON today, so pack members get **opaque per-backup ids**,
  checksums are taken over the backup's own volume bytes rather than the pack ciphertext (which
  is identical in both places), and the map from member id to pack name lives only inside the
  encrypted stream *(review)*.
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
  tied to its job, so a dead backup cannot block GC for ever; a live backup renews it by
  heartbeat, since a multi-TB backup can outlast any fixed expiry, and before finalising it checks
  that every pack its snapshot references is in the volumes, refusing by name if one is not.
- **Replace-restore**: the restore first records the names of the packs it will write as intents
  in the live database (durably), writes and verifies them (size, checksum, header) BEFORE the
  database swap, and makes the swap durable (the new database file, its WAL and the parent
  directory fsynced) before anything else changes. A crash before the swap leaves intent-named
  packs the sweep may remove; a restore removes no pack itself. Packs count in the restore's
  preflight and in its declared-size bound. A referenced pack that is missing, the wrong length
  (`packs.ct_len`) or fails authentication makes the restore refuse and name it; a
  full-authenticate pass is offered.
- **Rollback pins** *(Lane B must-fix, completed by review)*: at the swap, the names of every pack
  the retained `pre-restore-<ts>.db` snapshot references are written into `pack_pins` in the new
  database and kept until that snapshot is pruned. GC, purge and the orphan sweep all skip pinned
  packs, so rolling back to the snapshot never finds rows pointing at a deleted pack, even for
  bodies the restored database considers dead. A test covers it.
- **At open**, the same missing-pack check runs and names the pack and how many articles it
  affects, in the UI rather than the plaintext log, rather than failing on the first read.
- **Merge-restore (row-level)**: the source corpus has its own BMKs, so its addresses and packs
  mean nothing in the target. The merge reads each body through the source's keys (held in
  memory, read through an encrypted connection, never from a plaintext staged copy: §3),
  and re-ingests it into the target's staging (new address, new pack). Its preflight counts the
  staging growth and the new packs. Cost scales with the merged text.
- **Panic wipe**: the guarantee is the destroyed salt, and it holds only if EVERY keyed copy of
  the database loses its salt *(review)*: `corpus.db` and its WAL, but also the retained
  `pre-restore-<ts>.db` snapshots (kept 3 deep and 168 h; 25.8 GB each in the field) and any keyed
  copy left in `.restore-` or `.bak-build-` staging. Today step 1 head-shreds only the main,
  custody and lane databases; the snapshots are reached only by step 6's full overwrite, which is
  slow and can be cut short, and each one would hold every BMK of its time. **Required change:**
  step 1 head-shreds every SQLCipher file under the data directory, by registry or pattern,
  before `blobs/` is touched. **Plaintext staging copies are not SQLCipher files**, so a head
  overwrite destroys nothing in them: if any survive (`.restore-*`, `.oo-backup-*`,
  `.bak-build-*`, including at destinations outside the data directory recorded in
  `backup-temp-dests.json`), the wipe fully overwrites them first, and §3's rule keeps `blob_keys`
  out of them in the first place. The current quick pass also FULLY OVERWRITES
  every remaining file under the data directory, on the premise that those are small side files;
  a multi-TB `blobs/` would turn the instant erase into hours. **Required change** *(review)*:
  after the salt is gone, `blobs/` is only unlinked, never overwritten, and a test proves the
  erase stays fast with a large pack tree; the optional free-space scrub covers the freed blocks
  as it does today. **A test also proves that after the quick pass no pack can be decrypted**
  (R707's condition), with a pre-restore snapshot, a plaintext staging copy (inside and outside
  the data directory) and a WAL holding a deep page-1 frame all seeded first. Honest limits: a backup copy elsewhere still holds its own keys; the
  inherited `-wal` issue (the sidecar is overwritten only in its first 4 KiB, while later copies
  of page 1 with the salt can sit deeper in it) is reported separately and must be fixed before
  this store relies on the wipe; and the whole guarantee rests on one 4 KiB byte overwrite, which
  SSD wear-levelling or a copy-on-write filesystem can leave recoverable. With `blobs/` only
  unlinked, one recovered 16-byte salt plus a coerced passphrase would open the whole store, so
  that limit is stated beside the existing `_LIMIT_NOTE`, with higher stakes than today.

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
| Q-W1 | BMK random, stored inside SQLCipher vs derived from the passphrase | stored | both security reads agree (both found the stored key sound, with the epoch, address-key and wipe requirements now in §3 and §8); §3 states what a DB copy alone gives; panic wipe tested to kill packs |
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
- **Q-W10 — Bodies larger than one pack.** Split across fixed-size packs, or a few coarse size
  classes. Recommend splitting: a size class announces that a large body exists.
- **Q-W11 — Key epochs.** Confirm that a passphrase change (none exists today) must create a new
  epoch and checkpoint-and-truncate the WAL, and whether old epochs are re-sealed automatically
  or only on request.
- **Q-W12 — Packer maximum age.** How long a body may wait in staging before a padded pack is
  sealed. Recommend 24 h: at field rates one 8 MiB pack is hours of bodies.
- **Q-W13 — Whole-store rollback.** Restoring an older database together with its older packs is
  undetectable by design (there is no external anchor). Recommend: accepted, stated.
- **Q-W14 — Epoch rotation cadence.** A database copy plus the passphrase reaches every pack of
  its epochs, including later ones (§3). Rotate the epoch at every backup, on a schedule, or only
  on a passphrase change. Recommend at every backup: it bounds what any one backup's keys can
  open to the packs that existed when it was taken, and costs one new key. That holds only with
  this order: the snapshot is taken under the writer gate, THEN the new epoch is committed before
  the next seal (a key inserted before the snapshot would reach forward again); and a GC rewrite
  always seals into the current epoch, never the source pack's. The address key stays fixed: the
  addresses live only inside the database, so an old copy gains nothing from it.
- **Q-W17 — Keys and plaintext staging.** Staging conversions leave `blob_keys` out and read
  source keys through an encrypted connection (recommended: it keeps today's plaintext staging
  design), or staging copies become SQLCipher-encrypted once this store exists.
- **Q-W15 — Purge strength.** Rewrite affected packs plus `secure_delete` and an FTS merge, with
  the old-block limit stated (recommended for a first build), or a per-pack random key in the
  `packs` row so deleting the row crypto-shreds the pack, at the cost of a trailer rebuild that
  needs the database.
- **Q-W16 — Unreferenced packs outside an intent.** Quarantine and report (recommended, §6), or
  also offer a manual "delete quarantined packs" action with a confirm naming the count and size.

**What the prototype does not model**, so the measurements say nothing about it: key storage in
SQLCipher and epochs, the address key in `blob_keys`, the trailer, `pack_intents` and the orphan
sweep, timer-tick sealing, constant mtimes and `O_NOATIME`, GC and purge, the durable-commit rule,
backup and restore, and panic wipe.
