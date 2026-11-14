# Blob store benchmark (2026-11-14)

Measured, not estimated. Script: `scripts/blob_store_bench.py` (PR #1992). Design it informs:
[`BLOB_STORE_PHASE_C_DESIGN_2026-11-14.md`](BLOB_STORE_PHASE_C_DESIGN_2026-11-14.md). The raw JSON of
every run is kept in the project's shared folder (`lanes-2026-11-14/blob-store-bench-raw/`), not in the
repository; the commands at the end regenerate it.

## sqlite3mc: NOT MEASURED

The `apsw-sqlite3mc` wheel could not be installed: the sandbox's safety check refused the download,
and it was not worked around. There is therefore no wheel, version or sha256 to record. The script
carries two sqlite3mc engines (`sqlite3mc-chacha20`, `sqlite3mc-sqlcipher`, through `apsw`) and reports
them as skipped, with the reason, when `apsw` is not the sqlite3mc build. **Those two code paths have
never been executed.** The raw AEAD figures below do NOT stand in for the engine comparison: SQLCipher's
per-page cost is AES-256-CBC plus HMAC-SHA512, and sqlite3mc's ChaCha20 cipher differs in its MAC and
KDF too, so even on an AES-NI machine the engines could differ. The trial stays open (design note Q-W8).

## Machine and versions

Intel Xeon @ 2.10 GHz, 4 vCPU, AES-NI present, 15 GB RAM, Linux 6.18, Python 3.13.18.
sqlcipher3 0.6.5 (SQLCipher 4.20.0 community, SQLite 3.54.1); stdlib sqlite3 on SQLite 3.53.1;
cryptography 50.0.2. Container disk; the OS page cache could not be dropped between phases, so "fresh
connection" means an empty SQLite page cache, not a cold disk.

## Corpus and method

- 50,000 synthetic articles (seeded Zipf words over a 30,000-word vocabulary), body length lognormal,
  median 3,109 bytes, 233 MB of body text in all. In the main run 20% of bodies are byte-identical
  copies of an earlier body under a different URL (syndication; the rate is an assumption,
  `--dup-rate`). No real data.
- Throwaway secrets generated in process (`secrets`), never printed, logged, written or put in argv.
  Each run has its own temp dir, deleted at the end.
- App pragmas on every store: page size 16384, auto_vacuum INCREMENTAL, WAL, synchronous NORMAL,
  64 MiB cache, temp_store MEMORY; mmap only on the plaintext store (as the app does).
- 3 runs per engine, median reported. Spread across the 3 runs: ingest within ±7%; read latencies vary
  much more (fresh-connection p50 up to about ±40%, e.g. sqlcipher 36/52/37 µs), so differences under
  ~50% in a read row are not meaningful. The 64 KiB prototype's fresh reads (56-94 µs over all runs)
  sit above every sqlcipher run (30-52 µs), which is why the 1.8x below is read as real.
- Workloads: ingest in 200-article transactions (row + FTS row; for the prototype also the dedup lookup
  and the staging row); unlock = open + key + count(*); read = 2,000 random ids, title + full body;
  feed = newest 100 by published_at, metadata only (200x); search = FTS MATCH on one term, top 50 by
  rank, then the bodies of the top 10 (20 terms).

Engines: `sqlite` (no encryption, the floor); `sqlcipher` (the current store); `blobpack-4m` and
`blobpack-64k`, the Phase-C prototype: metadata and a contentless FTS index in SQLCipher, bodies
HMAC-addressed and deduplicated, staged in SQL and then sealed into fixed-size 8 MiB OOPACK1 packs
(OOENC2's AES-256-GCM STREAM framing, a per-pack HKDF subkey, the header as associated data, zero
padding inside the AEAD), crash-ordered writes with fsync of file and directories, and an address
check on every read; with 4 MiB or 64 KiB frames.

## Results (median of 3, 50,000 articles, 20% duplicate bodies)

| | sqlite (no enc) | sqlcipher (today) | prototype, 4 MiB frames | prototype, 64 KiB frames |
|---|---|---|---|---|
| ingest, articles/s | 3,179 | 2,267 | 2,001 | 2,143 |
| seal + incremental_vacuum, s | – | – | 3.7 + 1.7 | 3.5 + 1.5 |
| unlock, s | 0.001 | 0.139 | 0.145 | 0.114 |
| read, fresh connection, p50 / p95 µs | 8 / 15 | 37 / 69 | 1,769 / 2,110 | 65 / 147 |
| read, warm, p50 / p95 µs | 4 / 8 | 5 / 9 | 1,696 / 2,141 | 48 / 92 |
| feed, p50 / p95 µs | 62 / 84 | 60 / 92 | 51 / 71 | 60 / 80 |
| search + 10 bodies, p50 / p95 ms | 37 / 94 | 31 / 76 | 44 / 93 | 31 / 64 |
| disk, MB | 432 | 434 | 346 (db 153 + packs 193) | 346 (db 153 + packs 193) |

Variants, each run against sqlcipher in the same command:

| | sqlcipher | prototype 64 KiB, zlib-6 | | sqlcipher, no duplicates | prototype 64 KiB, no duplicates |
|---|---|---|---|---|---|
| ingest, articles/s | 2,436 | 2,072 | | 2,420 | 2,063 |
| read, fresh connection, p50 / p95 µs | 37 / 75 | 78 / 163 | | 37 / 70 | 67 / 158 |
| read, warm, p50 / p95 µs | 5 / 9 | 68 / 149 | | 5 / 8 | 57 / 107 |
| disk, MB | 434 | 246 (db 153 + packs 92) | | 433 | 389 (db 154 + packs 235) |

Raw AEAD throughput (cryptography 50.0.2, this CPU, AES-NI; NOT the engine comparison, see above):

| | 16 KiB buffer | 64 KiB buffer |
|---|---|---|
| AES-256-GCM | 6,887 MB/s | 8,999 MB/s |
| ChaCha20-Poly1305 | 2,223 MB/s | 2,842 MB/s |

## What the numbers say

1. **Frame size is the decisive pack parameter.** With the backup default of 4 MiB frames every
   single-article read decrypts a whole 4 MiB frame: about 1.7 ms, nearly 50x the current store. At
   64 KiB a fresh-connection read is about 1.8x today's (65 vs 37 µs), and about 2x with zlib.
2. **Warm reads lose SQLCipher's decrypted page cache**: 5 µs today, about 50 µs in the prototype,
   which decrypts and authenticates on every read and checks the body against its address. Both are far
   below anything a person notices; a small decrypted-frame cache would close the gap at the cost of more
   plaintext in memory.
3. **Disk.** With no duplicates the prototype is 10% smaller (389 vs 433 MB): the cost of text in
   16 KiB-page rows, minus the pack padding. 20% duplicates gives -20% (346 vs 434); zlib on top gives
   -43% (246). Today's `articles.content` is stored uncompressed; the optional `compressed_content`
   column was not modelled. Padding cost here: 6.6 MB over 23 packs, from the last pack of the run.
4. **Ingest is within ~15% of today** (2,143 vs 2,267 articles/s, plus sealing at ~0.07 ms per article
   and a vacuum). An earlier version of the prototype keyed the staging table WITHOUT ROWID by a random
   32-byte address, which halved ingest; a rowid table with a unique address column removed that. Both are
   far above field ingest rates (30-80k articles/day, under 1 article/s).
5. **Feed and search do not change**: feed reads metadata only, and search is dominated by FTS ranking.
6. **What encryption costs today** (sqlite → sqlcipher): ingest -29%, fresh-connection read 8 → 37 µs,
   unlock 0.14 s (PBKDF2-HMAC-SHA512 x256,000, by design).
7. **AES-GCM vs ChaCha20-Poly1305 on this CPU**: AES is 3-3.2x faster with AES-NI. ChaCha at ~2.8 GB/s is
   of the order of a fast NVMe drive, not far above it, so on such a disk the cipher could show; but this
   is the raw AEAD, not either database engine.

## Reproduce

    python scripts/blob_store_bench.py --n 50000 --repeat 3 --json main.json
    python scripts/blob_store_bench.py --n 50000 --repeat 3 --engines sqlcipher,blobpack-64k --codec zlib --json zlib.json
    python scripts/blob_store_bench.py --n 50000 --repeat 3 --engines sqlcipher,blobpack-64k --dup-rate 0 --json nodup.json

With `apsw-sqlite3mc` installed, the two sqlite3mc engines run in the first command automatically.
