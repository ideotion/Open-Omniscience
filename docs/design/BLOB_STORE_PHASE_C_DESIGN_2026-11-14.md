# Phase C blob store — design note (2026-11-14)

**Status: DESIGN AND BENCHMARK ONLY. Nothing in the production store changes.** Opened by the
coordinator's ruling R700 (2026-11-14, under the maintainer's standing "use your best judgement"
rule) on the four storage rulings the maintainer answered on 2026-09-29 as Q1009 = RC03 =
`y, OOENC2, y, y`: blob dedup ON (row 3), OOENC2 for the pack AEAD (row 4), keyed-HMAC addressing
with opaque pack names (row 5), and the sqlite3mc benchmark trial (row 6, benchmark only).

Read with: [`STORAGE_5TB_PLAN.md`](STORAGE_5TB_PLAN.md) §3-C and §5 (the primitives),
[`STORAGE_5TB_REFRESH_2026-09-07.md`](STORAGE_5TB_REFRESH_2026-09-07.md) (Phase C is
ruling-gated, no longer mandatory: one file caps at 64 TiB at the ruled page size), and
[`STORAGE_RULINGS_ROUND2_2026-09-07.md`](STORAGE_RULINGS_ROUND2_2026-09-07.md) (why rows 3 and 5
are one argument). The benchmark is `scripts/blob_store_bench.py`; its method and numbers are in
§9 below. Nothing here is buildable until the coordinator rules the open questions in §10.

## 1. What exists today

- Article text lives in `articles.content` (`src/database/models.py`, plain `Text`; the optional
  `compressed_content` column is separate) inside the one SQLCipher file, and the FTS5 index is
  external-content on that column (`src/database/fts.py`, `content='articles'`).
- OOENC2 (`src/safety/crypto.py`) is used only by backups: a STREAM-framed AES-256-GCM container,
  nonce = prefix(7) | counter(4) | final(1), 4 MiB frames, key from scrypt over the passphrase
  with the salt in the header.
- Panic wipe (`src/safety/panic.py` → `crypto_erase.quick_crypto_erase`) destroys the SQLCipher
  salt page, so the corpus key can never be derived again, then removes the data directory.
- There is no `blob_store`, no pack file and no sqlite3mc anywhere in `src/` or `scripts/`.

## 2. Shape

```
<data dir>/
  corpus.db (SQLCipher)          articles(..., blob_addr), blobs, packs, blob_staging, blob_keys
  blobs/<2 hex>/<32 hex>         immutable packs, ~8 MiB of bodies each, names random
```

Three tables join the SQLCipher file. `blobs(addr PK, pack_id, off, len, codec)` maps an address
to its place in a pack. `packs(id, name, frame, n_frames, plain_len, …)` names each pack.
`blob_staging(addr PK, body)` holds bodies that are not yet sealed. The address → place map
exists ONLY inside the encrypted file; on disk an observer sees pack files with random names and
roughly equal sizes, nothing else.

## 3. Keys — one passphrase, no second key surface

- At store creation a random 256-bit **blob master key** (BMK) is generated and written into a
  `blob_keys` row **inside the SQLCipher file**. It is therefore encrypted at rest by the same
  page encryption as every article, and the passphrase remains the one thing a person needs.
- Two working keys come from it through HKDF-SHA-256 with fixed domain labels:
  `oo/v1/blob-address` (the HMAC key) and `oo/v1/pack-aead` (the pack key; per pack, a subkey
  `HKDF(pack key, info = pack name)`, see §4). A later dictionary registry would take
  `oo/v1/dict-integrity`.
- **Why not derive the BMK from the passphrase** (the 5TB plan §5's sketch): (a) a passphrase
  change today is a SQLCipher rekey; with a passphrase-derived pack key it would mean
  re-encrypting every pack, which §5 itself says must not happen. A key stored inside the
  database is re-wrapped by the rekey for free. (b) **Panic wipe keeps working unchanged:**
  destroying the salt page makes the BMK unreadable, so every pack becomes noise at once. A
  passphrase-derived pack key would survive the wipe for anyone who later obtains the passphrase.
- The BMK and its derived keys exist in process memory only while the store is unlocked, and are
  dropped at lock. They are never written outside the encrypted file, never logged, never put in
  argv. The memory caveat is the existing one, stated rather than improved: SQLCipher's
  `cipher_memory_security` is OFF by default (measured 2026-09-07), and Python cannot reliably
  zero a `bytes` object, so a compromised running session can read these keys, exactly as it can
  read the SQL key today. The threat model is unchanged: a seized or copied machine, never a
  live one.

## 4. Envelope — OOENC2 framing, sized for single-article reads

- Packs use the OOENC2 STREAM construction unchanged in its security argument (counter nonce,
  final-flag binds the end, so truncation, reordering and extension fail authentication).
- **Frame size 64 KiB, not the 4 MiB backup default.** Measured (§9): reading one article from a
  4 MiB-frame pack decrypts the whole 4 MiB frame and costs about 1.5 ms per article; at 64 KiB
  the cost matches the current store. Each frame adds 16 bytes of tag, 0.02 % at 64 KiB.
- **Per-pack subkey** `HKDF(pack key, info = pack name)` rather than one key with a random 7-byte
  prefix per pack. With per-pack subkeys a nonce can never repeat across packs, whatever the
  pack count, and a frame copied from one pack into another fails authentication.
- The OOENC2 header carries scrypt parameters and a salt for its passphrase key. A pack's key
  comes from the hierarchy instead, so the header needs a way to say so (open question Q-W2).
- Each pack ends with an encrypted **trailer** listing its `(addr, off, len, codec)` entries, so
  the index can be rebuilt from the packs and the BMK alone if the tables are ever lost (the
  Perkeep "recoverable from packs" property the 5TB plan asks for). Not in the prototype.
- Compression (zstd, zlib fallback) runs per body, below encryption. Per-source dictionaries
  are deferred: they need the versioned registry the 5TB plan describes, and a lost dictionary
  makes its bodies unreadable, so they get their own design.

## 5. Addressing and dedup

- Address = `HMAC-SHA-256(k_addr, body bytes)`, taken over the body before compression so that
  a codec change does not split identical bodies.
- Dedup: an ingest whose address already exists in `blobs` or `blob_staging` stores nothing new
  and points the article row at the existing address. No refcount is stored; reachability is
  decided by the GC's mark phase over `articles.blob_addr`.
- **The leak, stated as the maintainer ruled it:** a person who holds the passphrase can see
  which articles share a body and every body's length. A person who copies the disk sees
  neither, because the addresses live inside the encrypted file, the pack names are random, and
  a pack's size says nothing about which bodies are in it. A copier cannot test "is this leaked
  document here?" without the key: that is the confirmation-attack fix (row 5).
- `articles.hash` stays as it is (unique per row). This is dedup of identical bodies under
  different rows (syndication), beneath the row-level rule, not a replacement for it.
  Near-duplicate folding stays a separate decision.

## 6. Write path and crash safety

Two consistency domains (SQL and the filesystem) are ordered so that a crash can only leave
garbage, never a dangling reference:

1. **Ingest** writes the article row, its FTS row and the body into `blob_staging`, in ONE SQL
   transaction. Readers find a staged body there. Nothing touches the filesystem at ingest, so
   ingest atomicity is exactly today's.
2. **The packer** (background, under the writer gate) takes staged bodies, writes a pack to
   `<name>.tmp`, fsyncs it, renames it, fsyncs the directory, and only THEN commits one SQL
   transaction that inserts the `packs` and `blobs` rows and deletes the staging rows.

| Crash point | State after restart | Repair |
|---|---|---|
| during ingest | transaction rolled back | none |
| pack temp written, not renamed | a `.tmp` file nobody references | the sweep deletes `.tmp` files older than a grace period |
| pack renamed, SQL not committed | a whole pack nobody references; bodies still staged | the sweep deletes packs absent from `packs` older than the grace period; the packer re-seals the staged bodies |
| after SQL commit | consistent | none |

The grace period exists so the sweep can never delete a pack in the window between rename and
commit of a packer that is still running.

## 7. Garbage collection

Mark-and-sweep: mark every address referenced by `articles.blob_addr`, then any `blobs` row not
marked is dead. A pack whose live bytes fall below a threshold is rewritten (live bodies copied
into a new pack through the same crash-ordered path), and the old pack row is deleted in the same
SQL transaction that points its bodies at the new pack. The old file is unlinked only after that
commit. GC never runs while a backup holds its lease (§8).

## 8. Backup, restore, panic wipe

- **Backup** = the SQLCipher snapshot it takes today, plus the packs that snapshot references.
  Packs are immutable ciphertext, so they are copied byte for byte with no re-encryption; their
  key travels inside the snapshot. The backup holds a **GC lease** from before the snapshot until
  the last pack is copied, so no pack the snapshot names can be deleted mid-copy. A pack copied
  once never changes, so later backups copy only new packs. The volumes format needs a new member
  category for packs (open question Q-W5).
- **Restore (replace)** puts back the snapshot and its packs together. A restore that finds a
  referenced pack missing must refuse and name it, never open a store whose bodies are partly
  absent.
- **Restore (merge, row-level)**: the source corpus has its own BMK, so its addresses and packs
  mean nothing in the target. The merge reads each body through the source's keys and re-ingests
  it into the target's staging (new address, new pack). Its cost scales with the merged text.
- **Panic wipe** needs no new mechanism: the quick pass destroys the SQLCipher salt page, which
  makes the BMK, and so every pack, unreadable at once; the `blobs/` directory is then removed
  with the rest of the data dir, and the optional free-space scrub covers its freed blocks as it
  covers the database's. The honest limit is the existing one: a backup copy elsewhere still
  holds its own key.

## 9. Benchmark (measured)

Method, machine and the full tables: `/mnt/project-files/lanes-2026-11-14/blob-store-bench.md`
(project folder) and `scripts/blob_store_bench.py --help`. Summary of the 50,000-article run:

Machine: 4-vCPU Xeon with AES-NI, SQLCipher 4.20.0 (sqlcipher3 0.6.5). 50,000 synthetic
articles, median body 3.1 KB, 233 MB of text, 20 % byte-identical bodies; medians of 3 runs.

| | today (SQLCipher) | prototype, 4 MiB frames | prototype, 64 KiB frames |
|---|---|---|---|
| ingest, articles/s | 2,489 | 1,259 | 1,282 (+ 0.15 ms/article sealing) |
| read one article, fresh connection, p50 | 38 µs | 1,638 µs | 45 µs |
| read one article, warm, p50 | 7 µs | 1,665 µs | 43 µs |
| feed (newest 100) / search + 10 bodies, p50 | 104 µs / 39 ms | 66 µs / 56 ms | 62 µs / 35 ms |
| disk | 434 MB | 340 MB | 340 MB (243 MB with zlib) |

What it decides: the frame size (§4); that warm reads lose SQLCipher's decrypted page cache
(43 µs instead of 7, still invisible to a person); that the disk win is dedup plus compression
plus the row overhead of text in 16 KiB pages (-11 % with no duplicates at all); and that
prototype ingest halves, mostly from per-row Python, still three orders of magnitude above field
ingest rates. **sqlite3mc was not measured:** the sandbox's safety check refused the wheel
download and it was not worked around; the script runs it automatically where `apsw-sqlite3mc`
is installed. Raw AEAD on this CPU: AES-256-GCM 7.4-10.6 GB/s, ChaCha20-Poly1305 2.2-2.7 GB/s,
both far above disk speed, so only a CPU without AES-NI can answer row 6.

## 10. Open questions for the coordinator

- **Q-W1 — BMK stored inside SQLCipher (recommended) vs derived from the passphrase.** §3 gives
  the two reasons (free rekey, panic wipe). The 5TB plan §5 sketched a passphrase-derived KEK;
  this note recommends the stored key and asks for the ruling to say so.
- **Q-W2 — How the pack header names its key source.** (a) OOENC2 magic with the scrypt fields
  zeroed meaning "key from the hierarchy"; (b) a new magic (`OOPACK1`) that reuses OOENC2
  framing. Recommend (b): a backup reader that sees OOENC2 must never try to derive a key from
  zeroed scrypt fields, and Q1009's "OOENC2" ruling is about the construction, which (b) keeps.
- **Q-W3 — Frame size 64 KiB for packs** (backups keep 4 MiB). Recommend yes, on the measured
  read cost.
- **Q-W4 — Ingest stages bodies in SQL and a packer seals them later** (recommended, keeps
  ingest atomic and filesystem-free) vs writing packs synchronously at ingest.
- **Q-W5 — Backup format:** a new volumes member category for packs plus the GC lease, as a
  backup-format bump through the S04-04 normaliser path. Needs the backup lane's read.
- **Q-W6 — FTS conversion.** A blob store makes `content='articles'` impossible (the text leaves
  the row), so the article index must become contentless-delete (5TB plan Phase B) in the same
  migration, and every snippet path must fetch the body from the store. Confirm that the FTS
  split is in scope of the first build, or that the store waits for it.
- **Q-W7 — Migration of existing corpora:** a resumable background job moves `articles.content`
  into staging and through the packer in bounded batches, then a bounded `incremental_vacuum`
  returns the space. Default-off seam first; default-on only after a field corpus has round-
  tripped through backup and restore. Confirm the order.
- **Q-W8 — sqlite3mc.** Not measured here (§9). The trial needs either the person's own
  approval of the `apsw-sqlite3mc` wheel download in this sandbox, or a run of the script on
  another machine, ideally one WITHOUT AES-NI, which is the only case the trial was authorised to
  answer. Nothing in this design depends on it: packs use OOENC2 whatever the SQL engine is.
