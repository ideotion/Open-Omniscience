<!--
PROVENANCE: verbatim output of the maintainer's internet-connected research session
(prompt authored by the 2026-07-12 Fable-5 planning session; delivered by the maintainer
2026-07-12). Stored UNCHANGED per the docs/research/ convention — verify-before-trust
applies: source-quality labels (OFFICIAL/FORUM/BLOG/HEARSAY/DERIVED/ASSESSMENT) are the
analyst's own. This repo's reconciliation — including the places where OUR empirical
record OVERRIDES this report (DuckDB encryption, P2.4) — lives in
docs/design/STORAGE_5TB_PLAN.md. Do not act on this report directly; act on the plan.
-->

# Storage Architecture for >5 TB Encrypted Local Corpora — Research & Critical Review

**Project:** Open-Omniscience (local-first, GPLv3, single-machine intelligence platform for investigative journalists)
**Prepared:** 2026-07-12
**Scope:** Web research + critical review of the A→B→C storage plan. No code.
**Reference target:** single Debian machine · ~10 GB RAM reference VM · one-passphrase at-rest encryption (SQLCipher 4 today) · no server processes · no cloud/telemetry · append-heavy ingest (30–80 K articles/day, ~44 KB/article, ~78 mention rows/article) · FTS5 over everything · heavy cross-time read analytics · today 11.7 GB DB / 268 K articles / 20.9 M mentions · target 5–50 TB over 1–5 years.

**Source-quality labels used throughout:** `OFFICIAL` = sqlite.org / vendor / project-authored docs, specs, release logs, and core-developer forum posts. `FORUM/BLOG` = third-party forums, GitHub issues, independent engineering blogs. `HEARSAY` = secondary/uncorroborated. `DERIVED` = computed from a spec. `ASSESSMENT` = the analyst's own reasoning, not a cited fact. Every factual claim carries an inline URL. Benchmarks and version facts are never invented; where a thing could not be verified it is said so, in the Uncertainty section.

---

## 0. Executive summary (bottom line up front)

The A→B→C plan is directionally sound and, for the near term (single-digit TB, a few years), largely workable. But research surfaced **five hard facts that the plan appears to under-price**, two of which are correctness bugs rather than performance tuning:

1. **WAL breaks cross-file transaction atomicity — confirmed by three primary SQLite sources.** Phase B's ATTACH split (`corpus.db` + `index.db` + `fts.db`) under WAL means a single transaction touching multiple files is **not** crash-atomic across files. A crash mid-ingest can leave an article in `corpus.db` with its mentions missing from `index.db`. You cannot have both WAL concurrency (which this workload needs) and cross-file atomicity. This is the sharpest finding. (§1.5, §6)

2. **FTS5 external-content indexes cannot cross ATTACH boundaries** — the content table must be "within the same database" (official). So `fts.db` cannot be an external-content index over `corpus.db.articles`. It must instead be **contentless** (`content=''`, ideally `contentless_delete=1`), which happens to be the right choice for a disposable, rebuildable index anyway — but if the team assumed external-content, that assumption is wrong. (§2.3, §6)

3. **A single default-page SQLite/SQLCipher file caps at ~17.5 TB** (281 TB only at the maximum 64 KiB page size). With article text kept in SQL, you hit this wall before the 50 TB target — making **Phase C (text offload) effectively mandatory, not optional**, and arguing for doing it earlier. (§1.2, §6)

4. **FTS5 at 100 M+ documents is undocumented territory.** The best real-world reports top out at ~1–15 M rows, and even at 15 M practitioners already shard and accept multi-second latency. The target (114 M–1 B+ articles) is off the map of published experience. The plan's "contingency E2" hash-sharding is therefore **not a contingency — it is core design**, and it is the single biggest un-derisked risk. (§5.7, §6)

5. **Phase C's "one SHA-256-named age file per article" has two problems:** (a) at 114 M–1 B+ files it is a small-file catastrophe every comparable tool (Perkeep, restic, Borg) avoids by **packing** blobs into bounded containers; and (b) naming files by `SHA-256(plaintext)` leaks a **confirmation-attack** surface — an adversary who has a candidate document can test its presence in the corpus, and duplicate structure is exposed — which violates the spirit of "copying the files yields only ciphertext." restic's fix (address on-disk by ciphertext hash, keep the plaintext-hash map inside the encrypted index; or use a keyed/HMAC address) should be adopted. (§3, §6)

**One-line recommendation:** keep Phase A with explicit WAL-checkpoint governance; **re-draw the Phase B split along the disposable/non-disposable line** (keep `corpus.db`+`index.db` in one file for atomicity; split out only the disposable contentless FTS index and the blob store); **bring Phase C forward and make it a packed, keyed, content-addressed store** rather than one-file-per-article; and **treat FTS index hash-sharding as core**, prototyping FTS5 at 50–100 M docs before committing. Details in §7.

The most important external finding: **no project on record satisfies all four of {local-first, multi-TB, encrypted-at-rest, full-text search} at once.** You are building in genuinely unoccupied territory (§5), which raises the value of prototyping over trusting precedent.

---

## 1. SQLite / SQLCipher empirical limits at multi-terabyte scale (Q1)

### 1.1 Who actually runs SQLite this big

SQLite's own guidance is cautious about the terabyte range. `OFFICIAL`: "For device-local storage with low writer concurrency and less than a terabyte of content, SQLite is almost always a better solution," but "when the size of the content looks like it might creep into the terabyte range, it would be good to consider a centralized client/server database" (https://sqlite.org/whentouse.html). This is SQLite telling you that multi-TB single-file use is *out of its comfort zone* — worth quoting honestly in an internal design doc.

The strongest real multi-TB single-file datapoint is `FORUM/BLOG` (vendor engineering): Expensify's "Scaling SQLite to 4M QPS on a Single Server" benchmarks a **10 B-row (447 GB)** and a **30 B-row (1.3 TB)** SQLite database — "larger than the physical RAM of the bare metal machine" (1 TB RAM) — and reports that with the 1.3 TB DB "25% of the reads go to disk" with "negligible impact on total performance," reaching ~4 M QPS (https://use.expensify.com/blog/scaling-sqlite-to-4m-qps-on-a-single-server). **Crucial caveats for us:** it is a *server*, *unencrypted*, and does *point/range queries, not full-text search* — three steps removed from our problem. It runs WAL "to get fantastic read concurrency" plus a custom page-locking branch.

Other anchors: sqlite.org runs on SQLite (~400–500 K HTTP req/day, 15–20% hitting the DB) `OFFICIAL` (https://sqlite.org/whentouse.html); the "35% Faster Than The Filesystem" study shows SQLite reads/writes small blobs ~35% faster than individual files and uses ~20% less disk than one-file-per-blob `OFFICIAL` (https://sqlite.org/fasterthanfs.html) — a point that actually argues *for* keeping small article text in a DB rather than one-file-per-article (see the Phase C small-file critique, §3/§6). No primary source was found for the occasionally-cited "NYTimes multi-TB SQLite" claim; it is not asserted here.

### 1.2 Hard size limits — the ~17.5 TB default-page ceiling

`OFFICIAL` (https://sqlite.org/limits.html): maximum database size is `page_size × max_page_count`. `SQLITE_MAX_PAGE_COUNT` defaults to **4294967294** (also the hard default since 3.45.0, 2024-01-15). Therefore: **"When used with the default page size of 4096 bytes, this gives a maximum database size of about 17.5 terabytes. If the page size is increased to the maximum of 65536 bytes, then the database file can grow to be as large as about 281 terabytes."** The 281 TB figure is explicitly *untested* ("developers do not have access to hardware capable of reaching this limit").

Consequence for the plan: **at the out-of-the-box 4 KiB page size, a single SQLCipher file cannot exceed ~17.5 TB.** If article text stays inside SQL, you reach that wall well before 50 TB. Escapes: (a) set a larger `page_size`/`cipher_page_size` *at database creation* (it cannot be changed afterward without rewriting the whole file — a now-or-never decision), or (b) move the bulk (text) out of SQL — i.e., Phase C. This is the strongest structural argument that Phase C is mandatory rather than optional.

Related limits: default page size **4096 bytes**, max **65536** `OFFICIAL` (https://sqlite.org/compile.html, https://sqlite.org/limits.html). `SQLITE_MAX_ATTACHED` is **10 by default, max 125** — the Phase B three-file ATTACH is well within this (https://sqlite.org/limits.html). `SQLITE_MAX_SQL_LENGTH` defaults to **1 GB**; use bound parameters, not giant literal batches (https://sqlite.org/limits.html).

### 1.3 Page cache behaviour when the DB ≫ RAM

`OFFICIAL` (https://sqlite.org/pragma.html, https://sqlite.org/compile.html): `cache_size` default is **-2000 = ~2 MB per open database connection**. Against a multi-TB database that is trivially small, so random reads over cold data are dominated by cache-miss page faults to disk. mmap I/O is **off by default** (`mmap_size = 0`) and, even when enabled, "all current implementations map the first N bytes … and use legacy xRead() calls for any content beyond N bytes" `OFFICIAL` (https://sqlite.org/mmap.html) — so mmap cannot cover a multi-TB file. The forum-stated default hard cap on mmap is ~2 GB (the `0x7fff0000` constant), which I **could not confirm in the official docs fetched** — treat the exact number as build/platform-dependent `FORUM/BLOG` (https://sqlite.org/forum/info/e664376003e1de649effaaa1193887c8e42da57745250d4b4445eddb3c5118d5). The practical read: the effective working-set ceiling is OS file-cache + whatever `cache_size` you configure, not any SQLite default.

### 1.4 WAL at scale — checkpoint starvation is the near-term hazard

All `OFFICIAL` (https://sqlite.org/wal.html, https://sqlite.org/pragma.html): auto-checkpoint fires when the WAL reaches **1000 pages** (`wal_autocheckpoint` default). But "a checkpoint can only complete when no other transactions are running," and — the headline risk for our exact workload — **"If a database has many concurrent overlapping readers and there is always at least one active reader, then no checkpoints will be able to complete and hence the WAL file will grow without bound."** Continuous ingest + always-on analytics reads is precisely "always at least one active reader." The WAL also does not shrink on its own ("The checkpoint does not normally truncate the WAL file unless the journal_size_limit pragma is set"; `journal_size_limit` default is **-1 = no limit**); forcing it requires `PRAGMA wal_checkpoint(TRUNCATE)`. A bloated WAL also *slows readers*, who must locate the newest version of each page within it. This is a concrete "what breaks first" that the plan's "banned sweeps / budgeted merges" does not address (those target FTS merges, not WAL checkpointing).

### 1.5 ATTACH atomicity across files — the load-bearing finding

Three official sources agree, and draw a sharp line between rollback-journal mode and WAL mode.

**WAL mode — NOT atomic across files (verbatim, `OFFICIAL`, https://sqlite.org/wal.html):** *"Transactions that involve changes against multiple ATTACHed databases are atomic for each individual database, but are not atomic across all databases as a set."*

**ATTACH docs — same rule as a precondition (verbatim, `OFFICIAL`, https://sqlite.org/lang_attach.html):** *"Transactions involving multiple attached databases are atomic, assuming that the main database is not ':memory:' and the journal_mode is not WAL."* … *"If the main database is ':memory:' or if the journal_mode is WAL, then transactions continue to be atomic within each individual database file."* … *"But if the host computer crashes in the middle of a COMMIT where two or more database files are updated, some of those files might get the changes where others might not."*

**Rollback-journal mode — atomic across files via the super-journal (`OFFICIAL`, https://www.sqlite.org/atomiccommit.html §5):** a "super-journal" (formerly "master journal") lists the rollback journals of every participating database; deleting it is the single instant of multi-file commit. But that same document states up front that it "applies only when SQLite is operating in 'rollback mode' … SQLite still supports atomic commit when write-ahead logging is enabled, but it accomplishes atomic commit by a different mechanism" — and that different mechanism is per-file only (the WAL doc above). The super-journal is also **omitted under `PRAGMA synchronous=OFF` or `journal_mode=MEMORY`**, forfeiting cross-file atomicity.

**The bind:** this workload needs WAL for read/write concurrency (append-heavy ingest concurrent with heavy analytics). WAL forfeits cross-file atomicity. Rollback-journal mode restores it but serialises readers against the writer. **You cannot have both.** Full consequences for Phase B in §6.

### 1.6 SQLCipher specifics

All `OFFICIAL` (Zetetic). Design (https://www.zetetic.net/sqlcipher/design/): **AES-256 in CBC mode**, a **random IV per page** stored at the page end, and **a per-page HMAC (HMAC-SHA512 in v4)** of ciphertext+IV — "This validation involves considerable additional processing overhead whenever pages are read or written." When encrypted "the entire database file appears to contain random data" — copying it yields only ciphertext, with no readable header/schema (satisfies the threat-model requirement). Memory is locked via mlock/VirtualLock and wiped before free; the default state of `cipher_memory_security` I **could not confirm** from a primary source.

Performance (https://www.zetetic.net/sqlcipher/performance/): **"It's not unusual to see as little as 5-15% overhead for SQLCipher encryption"** — note "as little as": this is a best case for cache-friendly workloads. Key derivation "is very expensive, by design" (do not open/close connections repeatedly). Default `cipher_page_size` **4096**; larger pages favour bulk ops, smaller favour small-row access. Index your columns or SQLCipher "will need to execute full database scans across large numbers of pages."

Version facts, SQLCipher 4.0.0 release notes (https://www.zetetic.net/blog/2018/11/30/sqlcipher-400-release/): PBKDF2 iterations **256,000** (up from 64,000); KDF **PBKDF2-HMAC-SHA512**; page HMAC **HMAC-SHA512**; default page size **4096** (up from 1024). SQLCipher 4 will not open v3 databases without explicit `cipher_compatibility`/pragmas.

**Multi-TB caveat (`ASSESSMENT`):** SQLCipher inherits every SQLite limit above (including WAL cross-file non-atomicity) and adds per-page AES+HMAC on every page read/write. At multi-TB with a working set far exceeding RAM, that per-page crypto is paid on **every cache-miss page fault** — so 5–15% is a floor for cache-friendly access, not a ceiling for cold cross-time analytics. No Zetetic TB-scale benchmark exists to quantify this; it is flagged in Uncertainty.

### 1.7 Failure modes at scale

All `OFFICIAL` (https://www.sqlite.org/howtocorrupt.html unless noted): consumer drives that lie about fsync corrupt on power loss (worsened by `synchronous=OFF`); **network filesystems (esp. NFS) have buggy locking → keep the DB and its `-wal`/`-shm` on local disk** (§2.1); with large `mmap_size`, "a stray pointer that overwrites any part of that mapped space will immediately corrupt the database file" and an I/O error on mmapped pages raises a signal/crash rather than a catchable error (§5; https://sqlite.org/mmap.html); **naively `cp`-ing a live DB without its journal/WAL, or between databases, "are all likely to lead to corruption"** (§1.3–1.4) — backups of a live multi-TB DB must use the online-backup API or copy DB+WAL+SHM consistently. `SQLITE_CORRUPT`/"database disk image is malformed" is the runtime symptom of these causes.

---

## 2. FTS5 at scale + CJK tokenization (Q2)

### 2.1 Index size ratios

The FTS5 documentation's own benchmark `OFFICIAL` (https://www.sqlite.org/fts5.html, "The detail Option"): indexing a 1636 MiB email set produced an FTS index of **743 MiB with `detail=full`, 340 MiB with `detail=column`, 134 MiB with `detail=none`** — i.e. **≈45% / 21% / 8%** of source text, index-only. FTS5's author Dan Kennedy, on the Enron corpus `OFFICIAL`-forum (https://sqlite.org/forum/info/3baccecae55769ff): default settings put "FTS data … just under 32% of the total database"; `detail=none` "around 7.6%." Ratios are content-dependent (one apparent 70× blow-up in that thread was a data-ingestion bug embedding binary blobs, not FTS overhead).

The dominant size lever is the `content` option `OFFICIAL` (https://www.sqlite.org/fts5.html, "The content Option"): a **normal (content-owning) FTS5 table stores the full-text index *plus a private copy of the row text*** ("FTS5 makes a copy of the original row content"), so total on-disk exceeds 100% of the text. **Contentless (`content=''`) and external-content (`content='table'`) store only the index, no text copy** — so at Phase C, where article text lives in the blob store, a contentless index avoids a second on-disk copy of every 44 KB article. Option effects: `detail=column` drops phrase/NEAR queries; `detail=none` also drops column-filter queries; each `prefix=` length "creates an additional index on disk"; `columnsize=0` saves a little but disables the token counts bm25 ranking uses.

### 2.2 Incremental merge under continuous append

All `OFFICIAL` (https://www.sqlite.org/fts5.html): **every committed transaction writes a new level-0 b-tree ("segment").** At 30–80 K articles/day, committing per-article would generate a flood of small segments (and query cost rises with segment count, since each term lookup scans segments newest-first). Merging is governed by `automerge` (begin merging once **M** same-level b-trees exist; default **4**, max 16, 0 disables), `crisismerge` (once **C** b-trees on a level, merge them *immediately*; default **16**), and `usermerge` (min segments a positive `merge` combines; default **4**). The explicit `INSERT INTO ft(ft, rank) VALUES('merge', N)` command "merges b-tree structures together until roughly N pages of merged data have been written"; a **negative N drives toward a fully optimized index**, and the docs give a `total_changes()`-based loop as the incremental equivalent of `optimize`. `FORUM/BLOG` structural teardown (https://darksi.de/13.sqlite-fts5-structure/, https://gist.github.com/indutny/ae44fd93dde2736205609d19a21b87cc): merges act only within a level, promoting the result one level up (~64× larger each level); work is scheduled in 64-leaf-page units and **page-streamed, so merge memory stays bounded** even for large indexes.

**Best practice for this workload (`ASSESSMENT`, grounded in the official options):** batch many articles per transaction (the single biggest lever — fewer, larger level-0 segments); keep `automerge=4` with `crisismerge=16` as the backstop; run incremental `merge` with a small positive N in quiet windows; **avoid a full `optimize` on a multi-TB index** (it is one enormous transaction — see §2.6). This validates the plan's "budgeted merges" instinct — the mechanism exists and is the right tool.

### 2.3 External-content across ATTACHed databases — not supported

**Independently confirmed against the primary docs.** `OFFICIAL` (https://www.sqlite.org/fts5.html, "The content Option"): an external-content table is set "to the name of a table, virtual table or view … **within the same database**," and FTS5's content-fetch query uses the **bare, unqualified** table name (`SELECT <rowid>, <cols> FROM <content> WHERE <rowid>=?`) — no schema/attached-database qualifier is documented or shown, and the FTS5 shadow tables live in the one database that owns the virtual table. Targeted searches of the FTS5 forum threads on external content surfaced **no** working `content='attached.table'` configuration. **Therefore `fts.db` cannot be an external-content index over `corpus.db.articles`.** The buildable path is a **contentless** index (see §2.4), resolving article text yourself from the blob store / `corpus.db` by rowid = article ID. (The separate-file recommendation is `ASSESSMENT`; the "same database" constraint is the cited fact.)

### 2.4 Contentless and contentless-delete

`OFFICIAL` (https://www.sqlite.org/fts5.html; https://www.sqlite.org/releaselog/3_43_0.html): a plain contentless table (`content=''`) stores no text (all columns except rowid read back NULL) and supports neither UPDATE nor DELETE. **Contentless-delete** (`content=''`, `contentless_delete=1`), added in **SQLite 3.43.0 (2023-08-24)**, additionally supports DELETE and `INSERT OR REPLACE`, and UPDATE if all columns are supplied — deletions are tracked internally as tombstones (no need to re-supply the original text). The docs recommend it: "new code should prefer contentless-delete tables to contentless tables." Limits: still no stored column values; **`rebuild` is unavailable** (nothing to rebuild from — you re-feed from the source); tombstones accumulate until a merge cleans them. For an append-mostly corpus with occasional retractions, **`content='' , contentless_delete=1` is the correct configuration for the disposable `fts.db`.**

### 2.5 CJK tokenizers that actually exist

`OFFICIAL` (https://www.sqlite.org/fts5.html): FTS5 ships **exactly four built-in tokenizers — `unicode61` (default), `ascii`, `porter`, `trigram` — and NO built-in `icu` tokenizer** (ICU tokenization existed only in FTS3/FTS4, compile-time `SQLITE_ENABLE_ICU`). `unicode61` treats every Han/Kana glyph as a letter and only breaks on separators, so space-free CJK text collapses into one giant token — demonstrated on the SQLite list: FTS5+unicode61 indexes `为什么不支持中文` as **one token** `OFFICIAL`-list (https://www.mail-archive.com/sqlite-users@mailinglists.sqlite.org/msg112032.html); Signal hit the same (https://github.com/signalapp/Signal-iOS/issues/6169). The built-in escape hatch is **`trigram`** (added 3.34.0, 2020-12-01), which gives CJK substring matching but requires **≥3-character queries** and produces a substantially larger index.

Real open-source CJK tokenizer extensions (all are **loadable extensions** — you must ship and load the binary and enable extension loading; none is compiled into stock SQLite):

| Project | Segmentation | License | GPLv3 fit | Maturity |
|---|---|---|---|---|
| **wangfenjin/simple** (https://github.com/wangfenjin/simple) | **cppjieba** (Chinese dict) + Pinyin | **Dual MIT OR GPLv3-or-later** | **Clean** — MIT branch is permissive | **Most mature CJK option** (~800★, prebuilt binaries, wrappers for Rust/Flutter; widely shipped in note/journalism-style apps) |
| signalapp/Signal-FTS5-Extension (https://github.com/signalapp/Signal-FTS5-Extension) | Unicode TR29 word-boundary (no dictionary) | AGPLv3 | See note below | Thin repo, but production-used in Signal |
| hotchpotch/sqlite-vaporetto (https://github.com/hotchpotch/sqlite-vaporetto) | Vaporetto (**Japanese only**) | MIT OR Apache-2.0 | Clean | v0.4.0, small |
| lindera-sqlite (https://lib.rs/crates/lindera-sqlite) | Lindera morphological (JA+ZH+KO) | AGPL-3.0-only | See note | Early |
| cwt/fts5-icu-tokenizer (https://github.com/cwt/fts5-icu-tokenizer) | ICU boundaries (pan-CJK+Thai) | MIT | Clean | Small; fills the missing FTS5-ICU gap |

**Recommendation for Chinese:** **wangfenjin/simple** (cppjieba, dual MIT/GPLv3) is the mature, permissively-licensed, widely-bundled choice. For Japanese, sqlite-vaporetto (MIT/Apache). For pan-CJK via ICU, cwt/fts5-icu-tokenizer (MIT). **License nuance on the AGPL options (`ASSESSMENT`):** an initial license screen flagged Signal's and lindera's AGPLv3 as a "red flag" — that framing is for *closed-source/SaaS* products. For a **GPLv3 open-source, local-first** application with no network service, AGPLv3's extra network-source clause is essentially never triggered, and AGPLv3↔GPLv3 are FSF-compatible for combination. So AGPL is *usable* here — but wangfenjin/simple is both more mature and license-cleaner, so it remains the pick. No first-party pip wheel exists for wangfenjin/simple; bundle the loadable `.so` (verify it loads under SQLCipher — see Uncertainty).

### 2.6 FTS5 known scale problems

`OFFICIAL` (https://www.sqlite.org/fts5.html) + `ASSESSMENT`: `optimize` rewrites the entire index as a single transaction, so peak on-disk usage and journal/WAL size spike — a real `SQLITE_FULL` exposure on a constrained volume at multi-TB (the docs' own mitigation is to prefer incremental `merge`). `rebuild` re-tokenizes the whole corpus and is **unavailable on contentless tables**, so with a contentless `fts.db` you have no cheap "repair the index" button — you re-ingest from source. The old external-content/contentless `delete` command (re-supply original values, or "the results may be unpredictable") is a footgun that `contentless_delete=1` exists to remove. Merges are memory-bounded (§2.2). External-content JOINs "are very slow" at scale `FORUM` (https://sqlite.org/forum/info/509bdbe534f58f20) — relevant to any design that re-fetches column values per matched rowid. A claim that "FTS5 is dramatically faster than FTS4" at equal settings is `HEARSAY` (no cited benchmark found); FTS5's real edge is the `detail=` size knobs and structured merge, not raw speed.

---

## 3. Blob-store / content-addressed designs for Phase C (Q3)

**License bottom line (target must be GPLv3-compatible):** Perkeep (Apache-2.0), restic (BSD-2), Borg (BSD-3), age (BSD-3), and zstd (elect its BSD option) are all GPLv3-compatible. **git-annex is AGPLv3+ — the one copyleft outlier**: fine to invoke as an external binary, but reusing its *code* in a non-AGPL GPLv3 work would force the whole thing to AGPL.

### 3.1 What the comparable tools get right

**git-annex** `OFFICIAL` (https://git-annex.branchable.com/): keys of the form `BACKEND-s<size>--<hash>` (default **SHA256E** = SHA-256 + extension); objects under a **two-level hash-directory fanout** (`xx/yy/KEY`) to avoid too many files per directory, stored read-only with fsck verification. Chunking is **fixed-size** (`chunk=1MiB`+), remote-oriented, and buffers a whole chunk in RAM. AGPLv3+ (https://git-annex.branchable.com/license/).

**Perkeep** `OFFICIAL` (https://perkeep.org/doc/terms): a blob is "an immutable sequence of bytes"; a blobRef is `hashname-hexdigest` (default **SHA-224**). Its **blobpacked** layer is the canonical answer to the small-blob problem: it "rearranges … small blobs into … large packed blobs" that are **valid ZIP files, each ≤ 16 MB**, each carrying a **manifest** and per-part `wholeRef`/`wholeSize`/`wholePartIndex` so **data is recoverable from the raw zips even if the metadata index is lost** (https://github.com/perkeep/perkeep/issues/532). Apache-2.0.

**restic** `OFFICIAL` (https://restic.readthedocs.io/en/stable/100_references.html): **content-defined chunking** via Rabin fingerprint (64-byte window; **min 512 KiB / max 8 MiB / ~1 MiB average**; a **per-repository random polynomial** resists watermarking); blobs grouped into **pack files** under a **256-way fanout** (`data/xx/`, first 2 hex of SHA-256). Encryption is **AES-256-CTR + Poly1305-AES MAC** (encrypt-then-MAC, `IV||ciphertext||MAC`, 32-byte overhead), master key wrapped by a **scrypt**-derived key. Independent review by Filippo Valsorda calls the self-rolled AEAD "a bit of a yellow flag (but not a red flag)" and notes blob-size leakage via dedup `FORUM/BLOG` (https://words.filippo.io/restic-cryptography/). BSD-2.

**BorgBackup** `OFFICIAL` (https://borgbackup.readthedocs.io/en/stable/internals/): **buzhash** CDC (min 512 KiB / max 8 MiB / ~2 MiB target); compression none/lz4/zstd/zlib applied **after** dedup; **AES-256-CTR + HMAC-SHA-256** (or keyed BLAKE2b) per chunk, encrypt-then-MAC, with **durable CTR-counter reservation to prevent nonce reuse across crashes**; passphrase → PBKDF2-HMAC-SHA256. BSD-3.

**The pattern all three converge on:** SHA-256-class content addressing + shallow hash fanout + **packing many small blobs into bounded (~8–16 MB) containers** + per-object/per-chunk AEAD. Packing is not an optimization detail — it is the thing that makes millions of small objects tractable.

### 3.2 The "too many small files" problem is real at our scale

`OFFICIAL` (https://docs.kernel.org/filesystems/ext4/directory.html) + `HEARSAY` (https://en.wikipedia.org/wiki/Ext4): an ext4 directory uses a hashed b-tree (htree) index, normally ≤2 levels (**~10–12 M entries and a 2 GB per-directory cap**), extended to 3 levels (~6 billion) only with the `large_dir` feature (Linux 4.12+); max **4 billion files per filesystem**, fixed at mkfs. `DERIVED`: at ~44 KB/article, **5 TB ≈ 114 M articles and 50 TB ≈ ~1.1 B articles.** One OS file per article is therefore infeasible at the top of the range (readdir, fsck, rsync, and backup all die long before the hard limits). git (256-way), git-annex (`xx/yy`), and restic (256-way) all fan out; but the stronger lesson is Perkeep/restic/Borg **packing**. A two-hex-level fanout (`ab/cd/…`, 65 536 buckets) keeps leaf directories small even at tens of millions of *packs* — but you want packs, not raw per-article files.

### 3.3 Per-blob encryption: age vs AES-GCM streaming

**age** `OFFICIAL` (spec: https://github.com/C2SP/C2SP/blob/main/age.md; impl: https://github.com/FiloSottile/age, BSD-3; Rust `rage`: https://github.com/str4d/rage): header = version line + recipient stanza(s) + HMAC-SHA-256 line; **X25519** recipients wrap a random 16-byte file key with ChaCha20-Poly1305; a **scrypt passphrase** recipient (must be the only stanza) supports passphrase mode; the **STREAM** payload is 64 KiB chunks, each ChaCha20-Poly1305 with an 11-byte counter + 1 flag byte nonce and a 16-byte tag. `DERIVED`: single-X25519 header ≈ **~200 bytes**, plus 16-byte nonce + 16-byte tag per 64 KiB chunk. `ASSESSMENT`: the ~200-byte header is minor against multi-KB articles, but the **per-file X25519 scalar-mult, multiplied by 114 M–1 B files**, is a real CPU/entropy cost and still produces one small file per blob. Mitigation: **encrypt packed containers, not each tiny blob** (amortizes both header and X25519), or use age's symmetric/passphrase path. age's virtues: audited, stable, license-clean, ChaCha20-Poly1305 (no AES-NI dependency), STREAM already solves nonce framing.

**AES-GCM streaming** `OFFICIAL` (https://developers.google.com/tink/streaming-aead): plain AES-GCM safely encrypts only ~64 GiB per (key,nonce) and risks nonce-collision past ~2³² random-nonce messages — and **GCM nonce reuse is catastrophic** — so many independent blobs need a framed construction with a **per-file random salt → HKDF sub-key** (exactly what age and Tink both do). Tink's AES-GCM-HKDF-Streaming (1 MB segments recommended) or a nonce-misuse-resistant mode (AES-GCM-SIV / miscreant) are the options. `ASSESSMENT`: symmetric streaming avoids age's per-file asymmetric op (cheaper per blob) at the cost of owning nonce/salt uniqueness. For a single-machine store of millions of blobs, **a symmetric streaming AEAD with per-file random salt (or age applied to packs) is the efficient shape**; add SIV only if salt uniqueness can't be guaranteed.

### 3.4 zstd dictionary compression — validated, with an operational tail

`OFFICIAL` (https://github.com/facebook/zstd, https://github.com/facebook/zstd/blob/dev/programs/zstd.1.md): dictionaries supply the shared context small inputs lack, with benefit concentrated in the first few KB — "Dictionary compression greatly improves efficiency on small files and messages." Train with `zstd --train` (**>100 samples, weigh ~100× the dictionary size ≈ 10 MB of samples per ~110 KB dict**; only the first 128 KiB of each sample is used); **decompression requires the identical dictionary**; **`--maxdict` default ≈ 110 KB**. "There is no universal dictionary" — they are most effective **specialized per data type**, which directly validates Phase C's **per-source dictionaries**. `ASSESSMENT`: the operational tail is that you must **retain every dictionary forever** (losing one makes those blobs undecompressable), version them as a source's vocabulary drifts, and store the dictionary registry itself inside the encrypted store and back it up. zstd is dual **BSD OR GPLv2** — **elect BSD** for GPLv3 compatibility (the GPLv2-only path would not be GPLv3-compatible, but the dual license lets you choose).

---

## 4. Did we wrongly reject anything? Steelman of the alternatives (Q4)

**The gate every candidate must clear:** (1) single machine, (2) no server process, (3) at-rest encryption under one passphrase (copy → ciphertext), (4) GPLv3-compatible license, (5) pip-installable or trivially bundled, (6) FTS + heavy read analytics + append-heavy ingest, (7) 5–50 TB.

**Meta-finding: no single embedded engine clears all seven,** because requirement (6) bundles three things — OLAP read analytics, append-heavy ingest, *and* incremental FTS — that no encrypted embedded engine does well together. The honest question is which engine is a *strict upgrade* over the incumbent "SQLCipher + ATTACH + blob store." **Two are worth a serious second look — `sqlite3mc` and `libSQL` — and one (DuckDB) is worth adding as a sidecar.** The plan's explicit rejections (RocksDB, DuckDB-as-primary, local Postgres, filesystem encryption) were each *correct as stated*; the gap is what the plan did **not** name.

**License ground truth** (FSF standing classifications, https://www.gnu.org/licenses/license-list.en.html; the pivotal OpenLDAP-2.8 ruling corroborated against the fetched license text at https://www.openldap.org/software/release/license.html): MIT, ISC, BSD-2/3, the PostgreSQL License, and public-domain dedications are GPLv3-compatible. **Apache-2.0 is GPLv3-compatible but not GPLv2-compatible.** Proprietary licenses cannot ship inside a distributed GPLv3 program.

### 4.1 Memory-mapped KV stores — LMDB, libmdbx

**LMDB** (OpenLDAP Public License 2.8, **GPLv3-compatible**): fastest-in-class zero-copy reads, ~128 TB map on 64-bit, and — correcting a common belief — it **shipped native at-rest encryption in LMDB 1.0.0 (2026-06-30)** via `mdb_env_set_encrypt()` (per-page encryption + optional MAC) `OFFICIAL` (https://github.com/openldap/openldap/blob/master/libraries/liblmdb/CHANGES, https://www.openldap.org/lists/openldap-devel/201708/msg00002.html). **But:** the cipher is bring-your-own (LMDB ships no algorithm), it is **twelve days old** with a recent page-layout bug `FORUM` (https://lists.openldap.org/hyperkitty/list/openldap-bugs@openldap.org/thread/TWRDMFNG7OQYJZ7OUEECXEHLSFUZOLFE/), the mainstream `pip install lmdb` (py-lmdb) does **not** expose it `OFFICIAL` (https://pypi.org/project/lmdb/), and — decisively — **LMDB is a raw key-value store: no SQL, no FTS, no analytics** (you would rebuild all of that). Classic pathologies remain: copy-on-write write amplification and long-lived-reader free-list bloat `FORUM` (https://github.com/erigontech/erigon/wiki/LMDB-freelist-illustrated-guide). **Fails (6).**

**libmdbx** (Apache-2.0, **GPLv3-compatible**): a hardened LMDB successor (auto-geometry, LIFO reclaim, slow-reader eviction) — but it has **no native encryption at all** (its docs point you to LUKS/dm-crypt, a threat-model change you've explicitly rejected) `OFFICIAL` (https://github.com/erthink/libmdbx/blob/master/README.md), and ~8 TiB max at the default 4 KB page (128 TiB only at 64 KB). **Fails (3) and (6).** Verdict: the KV engines were **correctly not chosen** — no FTS/analytics, and encryption is either DIY, brand-new, or absent.

### 4.2 SQLite encryption/compression forks — the one under-weighted option lives here

SQLite itself is public domain (https://www.sqlite.org/copyright.html), and FTS5 works transparently under any whole-file codec. Among the encryption layers:

- **SQLite Encryption Extension (SEE)** and **ZIPVFS** (page compression) are official but **proprietary ($2 k / $4 k)** — **fail (4)**, correctly excluded.
- **`sqlite3-multiple-ciphers` (sqlite3mc, Ulrich Telle) — MIT, and a genuine drop-in the plan should weigh.** Transparent whole-file encryption offering AES-128/256-CBC, **ChaCha20-Poly1305, SQLCipher-compatible AES-256, sqleet-compatible**, plus modern Ascon/AEGIS; actively maintained; **pip-installable via `pip install apsw-sqlite3mc`** (self-contained wheels) `OFFICIAL` (https://utelle.github.io/SQLite3MultipleCiphers/docs/ciphers/cipher_overview/, https://github.com/utelle/apsw-sqlite3mc). It can *read the existing SQLCipher format*, and its **ChaCha20-Poly1305 cipher needs no AES-NI** — directly relevant to the "journalists' aging laptops" constraint (older/low-end CPUs without AES acceleration pay a heavy penalty for SQLCipher's AES-CBC). Encryption only — **no page compression**.
- **sqleet** (Unlicense) is **unmaintained** and redirects users to sqlite3mc. **CEVFS** (MIT) is the only open VFS doing *both* compress+encrypt but ships no algorithms, has no WAL mode, and is dormant since 2020. **sqlite_zstd_vfs** (Apache-2.0) does compression only.
- **No mature open package delivers encryption AND page-compression together** — the only "both" path is proprietary (SEE+ZIPVFS), and page-level encryption destroys page-level compressibility anyway unless ordered compress-then-encrypt. This is a further argument to get compression from **content-level zstd in the blob store (Phase C)**, not from the SQL codec.

### 4.3 Embedded Postgres — correctly rejected

**pglite** (Apache-2.0/PostgreSQL) is genuinely serverless (Postgres in WASM) but **single-user, memory-bound (~2 GiB), no encryption, alpha** `OFFICIAL` (https://pglite.dev/docs/about, https://github.com/electric-sql/pglite/issues/406) — **fails (3),(7)**. The **embedded-postgres binaries** (zonky, fergusstrange, pgserver) all **spawn a real `postgres` server process** and run stock Postgres with **no at-rest encryption** — **fail (2),(3)**. Postgres TDE exists only in **forks/extensions that require a running daemon and key off a KMS/keyring, not one passphrase** (Percona `pg_tde`, Cybertec, EDB — several proprietary) `OFFICIAL` (https://www.postgresql.org/docs/current/encryption-options.html, https://github.com/percona/pg_tde). **No embedded Postgres is both serverless and single-passphrase-encrypted.** The rejection stands.

### 4.4 Other embedded encrypted stores

- **libSQL / Turso (MIT) — the closest thing to a strict upgrade over SQLCipher.** An open-source SQLite fork, "100% compatibility with the SQLite API" (so FTS5, ATTACH, file format all carry over), with **native single-key encryption at rest** (key held in memory only, data pages + WAL encrypted, ~6% read / ~14% write overhead) `OFFICIAL` (https://turso.tech/blog/introducing-fast-native-encryption-in-turso-database, https://docs.turso.tech/sdk/python/reference). Notably, the mature **C libSQL fork implements its encryption by bundling a copy of `sqlite3mc`** (AES-256) `FORUM`-maintainer (https://github.com/tursodatabase/libsql/issues/893), while the newer Rust engine adds codec-free AEGIS-256/AES-GCM — so §4.2's `sqlite3mc` recommendation and this one share the same battle-tested crypto core. It beats the incumbent on **license (MIT vs BSD-3), encryption ergonomics (native, nothing to bolt on), and active maintenance** — but it is the **same row-store**, so it does *not* beat SQLCipher on analytics. **Caveat:** native encryption lives in the newer Rust engine (beta/pre-1.0); the mature C `libSQL` still lists it as roadmap — **pin the build and verify the version** before depending on it.
- **DuckDB (MIT) — genuinely wins the analytics half, loses the ingest half.** Columnar/vectorized OLAP with a BM25 FTS extension, pip-installable, single-file, no server, and **native at-rest encryption since v1.4.0 (2025-09-16)** (AES-256-GCM, WAL + temp files encrypted, copy → ciphertext) `OFFICIAL` (https://duckdb.org/2025/09/16/announcing-duckdb-140, https://duckdb.org/2025/11/19/encryption-in-duckdb). **But** it is **single-writer** ("Writing to DuckDB from multiple processes is not supported… not a primary design goal"), its **FTS index is not incremental** (must be rebuilt after inserts), and its encryption is ten months old and self-described as **"does not yet meet the official NIST requirements"** `OFFICIAL` (https://duckdb.org/2025/11/19/encryption-in-duckdb, https://github.com/duckdb/duckdb/discussions/15291). The plan rejected DuckDB *as primary* (correct); it did not consider DuckDB *as a read-only encrypted analytics sidecar*, which is the role it actually fits (see §7 caveats — it cannot directly read an encrypted SQLCipher/libSQL file, so a sidecar means a second encrypted store to populate and keep in sync).
- **RocksDB** — encryption is only a framework with a **placeholder cipher** (maintainer: "ROT13 is not real cryptography"); dual GPLv2+Apache-2.0 (take the Apache arm for GPLv3-compat); no SQL/FTS. **Fails (3),(6)** — correctly rejected.
- **BadgerDB** (Apache-2.0) has built-in AES but is **pure Go → not pip-embeddable** (would need a separate Go process) and is KV-only. **ObjectBox** ships a **closed-source proprietary core engine** (only bindings are Apache-2.0) — **fails (4)/(5)**. **Realm** is an Apache-2.0 mobile object DB with AES-256, but no Python/SQL/OLAP and its sync ecosystem hit **end-of-life in Sept 2025**. All three **fail (5)/(6)**.

### 4.5 Verdict on "did we wrongly reject anything?"

**No hard rejection was wrong** — every explicitly-rejected engine fails a non-negotiable constraint (RocksDB: no real encryption; DuckDB-as-primary: single-writer + non-incremental FTS; local Postgres: server process + no passphrase encryption; filesystem encryption: threat-model change). **But three options were under-considered and deserve a place in the design conversation:**

1. **`sqlite3mc` (MIT)** as a SQLCipher replacement/complement — more permissive license, `pip install apsw-sqlite3mc`, reads the SQLCipher format, and **ChaCha20-Poly1305 for the aging-laptop / no-AES-NI case**. Lowest-risk upgrade.
2. **`libSQL` (MIT)** as a SQLCipher successor — native modern encryption, SQLite-compatible — **once its encryption engine reaches a stable release** (track it; don't bet the corpus on a beta yet).
3. **An encrypted DuckDB sidecar (MIT)** for the heavy-read-analytics half the row-store serves poorly — with eyes open to (a) DuckDB's young encryption, (b) single-writer, non-incremental FTS, and (c) that it means a *second* encrypted analytical store to populate, not a free attach over the primary.

The steelman's real lesson: the incumbent was **right to be SQLite-family**, but "SQLCipher" specifically is the weakest-licensed, AES-only member of that family, and the analytics requirement is served by a columnar sidecar, not the row-store. The strongest honest reframing of the incumbent is **"(libSQL or sqlite3mc for encrypted ingest+FTS) + (DuckDB for encrypted analytics) + blob store"** — no *monolithic* engine satisfies all seven constraints.

---

## 5. Has anyone solved exactly this? (Q5)

### 5.0 The negative result (the most important finding of this section)

**No documented case exists of a genuinely local-first (one user's machine), multi-terabyte, encrypted-at-rest document corpus with full-text search.** The constraint set {local-first, multi-TB, encrypted-at-rest, FTS} has only ever been satisfied *two or three at a time*:

- multi-TB + FTS, but *server clusters, unencrypted* → ICIJ, OCCRP, DocumentCloud;
- local-first + encrypted, but *MB-to-low-GB scale* → Signal, Anytype, Standard Notes, Joplin;
- multi-TB in one SQLite file, but *server, unencrypted, no FTS* → Expensify/Bedrock.

You are building in essentially unoccupied territory. That is a finding, not a gap in the search — and it raises the value of prototyping over trusting precedent.

### 5.1 ICIJ Datashare — the closest analog, and instructive

The journalist desktop tool used for Panama/Pandora workflows `OFFICIAL` (https://github.com/ICIJ/datashare, https://icij.gitbook.io/datashare/local-mode/about-the-local-mode, https://github.com/ICIJ/datashare/wiki/0016-introduce-persistence-system-for-datashare): search/index is **Elasticsearch** (extraction via Apache Tika, "a heavy process — it can take 5mn for one file"); relational metadata is **PostgreSQL in server mode, SQLite in local mode** — SQLite holds only annotations/tags/prefs, **not** the search index. Even "local mode" launches a **full local Elasticsearch + Redis + DB**. **No at-rest encryption is a documented feature.** Scale: the big leaks (Panama **2.6 TB**, Paradise **1.4 TB**, Pandora **2.94 TB**) were indexed across **up to 10 servers** `OFFICIAL` (https://icij.gitbook.io/datashare/server-mode/performance-considerations, https://www.icij.org/inside-icij/2020/01/how-icij-will-rock-its-tech-in-2020/). **Lesson:** the domain experts closest to our problem chose Elasticsearch (not SQLite FTS) for search, used SQLite only for small local metadata, added no at-rest encryption, and scaled to multi-server clusters at TB. Their "SQLite for metadata, dedicated engine for search" split is exactly the division §6/§7 recommends.

### 5.2 OCCRP Aleph / OpenAleph — server-based, but the FTS-at-scale lessons transfer

`OFFICIAL` (https://docs.aleph.occrp.org/developers/explanation/architecture/, https://docs.aleph.occrp.org/developers/explanation/search/): **two PostgreSQL instances + Elasticsearch**, FollowTheMoney entity model, server-based; public instance cites **4.5 B records** (https://www.occrp.org/en/announcement/occrp-announces-a-new-chapter-for-its-investigative-data-platform-aleph-pro). Documented FTS-at-scale gotchas: **prefix searches on large indexes can silently miss results**; snippet gaps for Pages entities; wildcard/fuzzy/regex "can result in very slow queries, high resource usage or timeouts"; manual per-entity **sharding** is required. **Lesson:** even a mature, server-class FTS stack hits subtle correctness cliffs at scale and needs explicit sharding — a caution for any FTS5-at-100M-docs ambition.

### 5.3 DocumentCloud (MuckRock)

`OFFICIAL` (https://github.com/MuckRock/documentcloud): hosted, server-side, Django, **S3-compatible object storage** (MinIO locally). The common attribution of **Apache Solr** for search could **not be verified against a live primary source this session** (the help page 403'd) — treat as `HEARSAY`/unverified. **Lesson:** the mainstream "millions of documents + FTS" journalism tool is again server-hosted with a Lucene-family engine and object storage.

### 5.4 Signal Desktop — the local-first + encrypted reference point

`OFFICIAL` (https://github.com/signalapp/sqlcipher, https://github.com/signalapp/Signal-FTS5-Extension): **SQLCipher** message DB + a **custom FTS5 tokenizer** (`signal_tokenizer`). Runs at **MB-to-single-GB** scale. Reported pain is dominated by **UI/Electron rendering** (a "laggy UI at 100–200 MB DB" issue was fixed via `--disable-gpu`; a maintainer's 2.4 GB folder stayed responsive) `FORUM` (https://github.com/signalapp/Signal-Desktop/issues/3713), plus **FTS5 tokenizer/format edge cases** (CJK failures https://github.com/signalapp/Signal-iOS/issues/6169; "invalid fts5 file format" crashes https://github.com/signalapp/Signal-Android/issues/13685) — **not** crypto throughput. Critically, researchers showed Signal Desktop **stored the SQLCipher key in plaintext next to the DB**; Signal's response was that "at-rest encryption is not something Signal Desktop is currently trying to provide," and they later adopted OS-keychain storage `HEARSAY`/analysis (https://mjtsai.com/blog/2024/07/08/signal-for-macs-encrypted-database/). **Lesson:** the most-deployed local encrypted SQLite+FTS5 app in the world runs *small*, and *its encryption was only as good as its key storage.* Open-Omniscience's **one-passphrase, no-key-on-disk** model is materially *stronger* than Signal's here — but it inherits FTS5 tokenizer/corruption handling as real work.

### 5.5 Local-first PKM tools hit walls far below TB

`FORUM` (with on-record team statements): **Obsidian** — a team member on "Terabyte size, million notes vaults?" says "this is beyond what we can currently and also likely in the future handle" (~10 GB reported OK) (https://forum.obsidian.md/t/terabyte-size-million-notes-vaults-how-scalable-is-obsidian/66674). **Logseq** stalls at hundreds of blocks per page (in-memory Datalog) (https://discuss.logseq.com/t/very-slow-performance-with-large-local-graph/1484). **Joplin** (SQLite) users routinely raise DB-size concerns (https://discourse.joplinapp.org/t/mybase-to-joplin-sqlite-too-large/24833). **Anytype** is local-first *and* encrypted (encrypted `flatfs` fragments over a private IPFS) `OFFICIAL` (https://doc.anytype.io/anytype-docs/advanced/data-and-security/data-storage-and-deletion) — the architecturally closest local+encrypted example — but exposes **no FTS-at-scale story and no size limits**; any TB+FTS capability is speculative. **Datasette** (Simon Willison) calls an **11 GB SQLite DB "at the upper end of what I've comfortably explored,"** with `count(*)`/full-table scans the dominant pain and a hard "never scan more than 10,000 rows" rule as the fix `OFFICIAL` (https://simonwillison.net/2024/Aug/22/optimizing-datasette/). **Lesson:** in every local-first example the **app/index/scan layer breaks before the SQLite file format does** — budget row/scan-bounding and pagination discipline from day one.

### 5.6 The one real >1 TB embedded-SQLite datapoint

Expensify/Bedrock (§1.1): a **1.3 TB** SQLite DB at ~4 M QPS — but *server, unencrypted, point/range queries not FTS,* on 1 TB RAM / 192 cores, and they note "almost nothing scales to handle this kind of hardware well" `FORUM/BLOG` (https://use.expensify.com/blog/scaling-sqlite-to-4m-qps-on-a-single-server). Three steps removed from our problem.

### 5.7 FTS5 at tens-to-hundreds of millions of documents — unproven

The best public reports top out far below "hundreds of millions": **15 M rows sharded into 16 SQLite DBs** with common-term queries taking ~3 s `FORUM` (https://news.ycombinator.com/item?id=41207085); **1.73 M patent records** where FTS5 gave ~3 ms queries and grew the DB ~40% `HEARSAY` (https://media.patentllm.org/blog/ai/nemotron-fts5-patent-speedup). **No credible first-hand account of a single FTS5 index working well at tens-to-hundreds of millions of documents was found.** Real deployments top out around **1–15 M rows and already shard**, accepting multi-second common-term latency. Our target (114 M–1.1 B articles) is **off the documented map** — plan for FTS-at-scale as a research risk, not a solved pattern. The 15 M-in-16-shards figure implies ~1 M docs/shard is a sane unit → **~100–1000+ shards at our target scale**, which makes a fan-out-and-merge query layer unavoidable (see §6/§7).

---

## 6. Critique of the A→B→C plan — what breaks first, what is underestimated

The plan's instincts are mostly right: single encrypted file first, offload the disposable index, move bulk text to a content-addressed store, hash-shard (never time-shard) as the escape hatch. The problems are in the fine print, and two of them are correctness bugs, not tuning.

**Ranked "what breaks first" (soonest/most-certain at the top):**

1. **WAL checkpoint starvation (Phase A, near-term, before any TB milestone).** Continuous ingest concurrent with heavy analytics is the textbook "always at least one active reader" case in which "the WAL file will grow without bound" (§1.4). This bites at gigabytes, not terabytes. The plan's "banned sweeps / budgeted merges" governs FTS merges, **not** WAL checkpointing — a gap.
2. **Phase B cross-file atomicity loss (correctness, on the first crash mid-batch after the split).** Under WAL, a transaction spanning `corpus.db` + `index.db` is not crash-atomic across files (§1.5). This is a silent-inconsistency bug, not a slowdown.
3. **FTS5 scaling wall somewhere in the tens of millions of docs (§5.7),** well before 50 TB — forces sharding.
4. **SQLCipher cold-page decryption tax vs cross-time recall (gradual, compounding as the DB passes RAM; §1.6, below).**
5. **The ~17.5 TB single-file ceiling (only if text stays in SQL; Phase C avoids it; §1.2).**
6. **Small-file / confirmation-attack problems in a naive one-file-per-article Phase C (§3.2, below).**

### 6.1 Phase A — solid, with two unpriced costs

Phase A (single SQLCipher file, no VACUUM, budgeted merges) is the right start and fine for the single-digit-TB / few-year horizon. Two costs are unpriced:

- **WAL checkpointing is not addressed.** Add explicit governance now: a single-writer discipline, `journal_size_limit` set, scheduled `PRAGMA wal_checkpoint(TRUNCATE)` in maintenance windows, and a checkpointer that does not starve behind long analytical reads. Otherwise the `-wal` grows unbounded and *also* slows readers.
- **Banning VACUUM has a permanent consequence the plan doesn't name: free-page fragmentation never reclaims.** Banning VACUUM is correct (it needs ~2× space and rewrites the whole file — impossible at TB). But every delete/retract/update then leaks free pages forever, bloating the file and hurting locality over years. The only real mitigations are (a) enforce append-only discipline (minimize in-place churn) and (b) decide `auto_vacuum=INCREMENTAL` **at creation time** — like `page_size`, it **cannot be enabled later without a full VACUUM**, so it is a now-or-never call that should be made deliberately, not by default.
- **`page_size`/`cipher_page_size` is also now-or-never (§1.2).** If there is any chance text stays in SQL near the top of the range, a larger page size raises the 17.5 TB ceiling — but it also increases per-page crypto cost and read amplification for small rows. Better to resolve this by *offloading text* (Phase C) than by inflating pages.

### 6.2 Phase B — the split is drawn along the wrong axis

This is the sharpest critique. Two independent, primary-sourced facts break Phase B *as described*:

- **Cross-file atomicity is lost under WAL (§1.5).** The plan splits into `corpus.db` (metadata) + `index.db` (mentions/analytics) + `fts.db` (disposable). Under WAL, a single ingest transaction that writes an article to `corpus.db` and its ~78 mentions to `index.db` is **not** atomic across the two files: a crash can commit one and not the other, yielding an article with no mentions or orphaned mentions. For append-heavy ingest that will crash mid-batch eventually, this is a *when*, not an *if*. And you cannot fix it by turning off WAL — this workload needs WAL's concurrency; rollback-journal mode (which *does* give cross-file atomicity via the super-journal) serialises readers against the writer. **The split axis is the bug:** `corpus.db` and `index.db` are the *durable, referentially-coupled* data, so splitting them across files is exactly the thing WAL cannot keep consistent. The disposable/rebuildable data (`fts.db`) is the only piece whose non-atomicity is harmless (you rebuild it). **Re-draw the split along the disposable/non-disposable line, not metadata/mentions** (see §7).
- **`fts.db` cannot be external-content over `corpus.db` (§2.3).** FTS5 external-content requires the content table "within the same database." So the disposable index must be **contentless** (`content=''`, `contentless_delete=1`), returning rowid = article ID and resolving text from the blob store. This is actually the *better* design (no second copy of text), but if the team assumed external-content across ATTACH, the plan is not buildable as written. Also note: a contentless index **cannot be `rebuild`-ed** internally (§2.6) — "rebuild" means re-feeding from source — which is consistent with treating `fts.db` as disposable, but means the source of truth for re-indexing must always be present and complete.
- Minor: each ATTACHed DB has its own `-wal`/`-shm` and checkpoint cycle, so three files = three checkpoint cycles to govern; and `SQLITE_MAX_ATTACHED` (10 default) is not a concern at three.

### 6.3 Phase C — right direction, wrong primitives, plus a threat-model leak

Phase C is arguably the *most important* phase (it is what keeps SQL under the 17.5 TB ceiling and shrinks the FTS/analytics DB), and it should probably come **earlier**. But "content-addressed, SHA-256-keyed, age-encrypted **files**" has three problems:

- **One file per article is a small-file catastrophe at scale (§3.2).** 114 M–1.1 B files is infeasible on ext4 in practice (readdir/fsck/rsync/backup collapse long before the 4-billion-file hard limit). Every comparable tool — Perkeep blobpacked (≤16 MB ZIPs), restic pack files, Borg — **packs many blobs into bounded containers** precisely to avoid this. Pack, don't scatter.
- **Naming files by `SHA-256(plaintext)` leaks a confirmation-attack surface — a real problem under a source-protection threat model.** If on-disk names are plaintext hashes, anyone who merely *copies the store* can (a) see which articles are byte-identical (duplicate structure) and (b) **confirm whether a specific document they already hold is in the corpus** by computing its hash — "is *this* leaked file in the journalist's archive?" That violates the spirit of "copying the data files must yield only ciphertext" (filenames are metadata that leak). restic avoids exactly this: on-disk artifacts are named by hash of *ciphertext*, while the plaintext-hash blob IDs live only inside the *encrypted* index (§3.1, confirmed from restic's design doc). **Adopt that:** address on-disk by opaque/ciphertext-derived names, keep the plaintext-hash→location map inside the encrypted SQL, and/or use a **keyed content hash (HMAC-SHA-256 under a passphrase-derived key)** as the address — which preserves deterministic dedup while making the address uncomputable (and confirmation impossible) without the passphrase.
- **age's per-file cost fights the file-per-article design (§3.3).** age adds ~200 bytes header **and one X25519 op per file**; at 10⁸–10⁹ files that asymmetric cost is significant. Packing fixes this too: age (or a symmetric streaming AEAD) applied to ~8–16 MB packs, with a per-pack random salt→HKDF sub-key, amortizes it away. age remains a license-clean, audited choice — for packs, not per article.
- **Dedup is a double-edged sword worth a conscious decision.** News corpora carry heavy wire/syndicated duplication (AP/Reuters reprinted across outlets), so content-addressing yields *real* space wins. But dedup inherently leaks equality and (via pack/blob sizes) length — the exact leakage Filippo's restic review flags (§3.1). Decide deliberately: dedup (space win, small metadata leak) vs no-dedup (no equality leak). Probably worth dedup, but document it, and prefer keyed addressing so the leak is only to a passphrase holder.
- **Per-source zstd dictionaries are validated (§3.4) but create a hard new dependency:** every dictionary must be retained forever and versioned, or its blobs become undecompressable. The dictionary registry becomes critical infrastructure that must itself live inside the encrypted store and be backed up.
- **The blob store is a *second consistency domain* outside SQL's transactions.** Writing an article now means: write blob/pack (filesystem) + write metadata (SQL). Those are not one transaction — the same cross-domain atomicity gap as §6.2, but SQL↔filesystem. Use content-addressed idempotence: write the (immutable) blob first, then reference it from SQL; a crash leaves at worst an *orphaned* blob, reclaimed later by a mark-and-sweep GC over SQL references (the discipline git uses). Name this explicitly in the design.

### 6.4 Cross-cutting issues the plan underestimates

- **FTS5 at 100 M+ docs is the biggest un-derisked risk (§5.7).** There is no published evidence it works well; real deployments shard by ~1 M docs and accept multi-second latency. **Contingency E2 (hash-sharding) is not a contingency — it is core design.** Reframe it now, design the fan-out-and-merge query layer, and prototype FTS5 at 50–100 M docs before committing the architecture. Hash-sharding also has a virtue worth stating: it is **time-neutral** (shard = hash(id), independent of date), so it *satisfies* the "cross-time recall is sacred / no time-partitioning" constraint — unlike time-sharding. This is a point in the plan's favour.
- **"No design makes old data second-class" is logically achievable but physically strained by encryption + DB≫RAM.** Cross-time recall means queries routinely touch old, cache-evicted pages; with SQLCipher every such cold page pays AES-256-CBC decrypt + HMAC-SHA512 verify on the fault (§1.6). Old data isn't second-class *by design*, but it is unavoidably slower *by cache economics* — true of any encrypted store larger than RAM. Be honest about this in the design docs; the mitigation is warm-cache/working-set management and keeping the hot metadata/index small (which Phase C helps), not a partitioning trick.
- **Key management and the single passphrase.** The one-passphrase, no-recovery-key, no-key-on-disk model is a *strong* threat-model choice — materially better than Signal's plaintext-key episode (§5.4). But: (a) you now have **two crypto domains** (SQLCipher and the blob store) that must both derive deterministically from the *one* passphrase — design and document the KDF hierarchy (passphrase → KDF → SQLCipher key *and* → blob-store key/identity) explicitly. (b) **No recovery key means a forgotten passphrase = total loss of a multi-TB corpus** — the stated ethic, but operationally brutal at TB scale; record it as an accepted risk. (c) Memory hygiene must extend to the blob path: plaintext transits process memory during ingest/query regardless of SQLCipher's mlock.
- **Backup and "copying yields only ciphertext" interact badly with a live DB.** The at-rest file is ciphertext, yes — but a naive `cp` of a *live* SQLCipher DB (with `-wal`/`-shm`) can capture a torn state or corrupt (§1.7). Backups must checkpoint+quiesce or use the SQLite online-backup API and copy DB+WAL+SHM consistently. At multi-TB the SQL backup is genuinely hard; the **content-addressed, immutable blob store is the easy part** (incremental `rsync` of new packs). Design backup around that asymmetry.

---

## 7. Recommendation

**Keep the SQLite-family, local-first, one-passphrase shape — it is correct, and the steelman confirmed no monolithic engine beats it (§4).** Keep the A→B→C progression too. But make the following changes, ordered by priority (the first two fix correctness bugs; the rest reduce risk).

**7.1 Re-draw the Phase B split along the disposable/non-disposable axis (fixes the WAL atomicity bug).** Do **not** put `corpus.db` (metadata) and `index.db` (mentions) in separate ATTACHed files while relying on cross-file transactions — WAL cannot keep them atomic (§1.5, §6.2). Instead:
- Keep the **durable, referentially-coupled data (article metadata + mentions) in one SQLCipher file**, so an ingest transaction (article + its ~78 mentions) is genuinely atomic.
- Split out only what is **disposable or immutable**: the FTS index (`fts.db`) and the blob store. A crash that desyncs a disposable index from the truth is repaired by rebuilding/re-feeding, not by cross-file atomicity.
- If the single durable file must itself be split for size later, do it by **hash-sharding** (§7.5), where each shard is internally atomic — not by role-splitting under ATTACH.

**7.2 Make `fts.db` a contentless-delete index (fixes the external-content misconception).** FTS5 external-content cannot cross ATTACH boundaries (§2.3), so `fts.db` must be `CREATE VIRTUAL TABLE … USING fts5(…, content='', contentless_delete=1)` (SQLite ≥ 3.43.0). It stores only the index (no second copy of text — good), returns rowid = article ID, resolves text from the blob store, and supports retraction/DELETE without re-supplying the original text. Accept that it is rebuilt by re-feeding from source (contentless tables have no internal `rebuild`), which is consistent with treating it as disposable.

**7.3 Harden Phase A now.** Add explicit **WAL checkpoint governance** (single-writer discipline, `journal_size_limit` set, scheduled `PRAGMA wal_checkpoint(TRUNCATE)` in maintenance windows, a checkpointer that doesn't starve behind long analytical reads) — otherwise the `-wal` grows without bound under continuous ingest + always-on reads (§1.4). Make the two **now-or-never creation-time decisions deliberately**: `page_size`/`cipher_page_size` (affects the 17.5 TB ceiling and per-page crypto cost) and `auto_vacuum=INCREMENTAL` (the only way to reclaim space without VACUUM, which is correctly banned) — neither can be changed later without rewriting the whole file. Enforce append-only discipline to minimize the unreclaimable fragmentation that a no-VACUUM policy guarantees.

**7.4 Bring Phase C forward and change its primitives (fixes the small-file catastrophe and the confirmation-attack leak).** Phase C is what keeps SQL under the 17.5 TB ceiling and shrinks the FTS/analytics footprint; it is effectively mandatory, so prioritize it. Change "one SHA-256-named age file per article" to a **packed, keyed, content-addressed store** modeled on restic/Perkeep/Borg (§3):
- **Pack** many article blobs into bounded (~8–16 MB) containers with a recoverable manifest; do not create 10⁸–10⁹ individual files.
- **Address on-disk by opaque or ciphertext-derived names**, and keep the plaintext-hash→location map inside the *encrypted* SQL. Better still, use a **keyed content hash — HMAC-SHA-256 under a passphrase-derived key** — as the internal address: this preserves deterministic dedup (valuable for wire/syndicated news duplicates) while making the address uncomputable, and confirmation attacks impossible, without the passphrase.
- **Encrypt the packs, not each blob** — age applied to packs (BSD-3, audited, ChaCha20-Poly1305, no AES-NI dependency), or a symmetric streaming AEAD with per-pack random-salt→HKDF. This amortizes age's per-file X25519 cost away.
- Keep **per-source zstd dictionaries** (validated, §3.4) but build a **versioned, encrypted, backed-up dictionary registry** — losing a dictionary makes its blobs undecompressable.
- Treat the blob store as a second consistency domain: write the immutable blob first, reference it from SQL second, and GC orphaned blobs by mark-and-sweep over SQL references.

**7.5 Treat FTS hash-sharding as core design, not "contingency E2" (addresses the biggest unknown).** FTS5 at 100 M+ documents is undocumented territory (§5.7); every real deployment past ~10–15 M rows shards. Design the **fan-out-and-merge query layer now**, target ~1 M docs/shard (⇒ ~100–1000+ shards at the top of the range), and **prototype FTS5 at 50–100 M docs before committing** — this is the single most important thing to de-risk empirically. Hash-sharding is also **time-neutral** (shard = hash(id)), so it *honors* the "cross-time recall is sacred / no time-partitioning" constraint — a genuine point in the plan's favor; state it explicitly as the reason time-sharding is banned but hash-sharding is not.

**7.6 Weigh the licensing/encryption upgrades the steelman surfaced (§4).** These are optional but real:
- **Adopt or trial `sqlite3mc` (MIT, `pip install apsw-sqlite3mc`) in place of / alongside SQLCipher.** Same whole-file-encryption model, more permissive license, reads the SQLCipher format, and — importantly for "journalists' aging laptops" — offers **ChaCha20-Poly1305, which needs no AES-NI** (SQLCipher's AES-CBC is slow on older CPUs without AES acceleration). Lowest-risk improvement.
- **Track `libSQL` (MIT)** as the eventual SQLCipher successor (native encryption, SQLite-compatible) — but only adopt once its encryption engine ships a stable, non-beta release; its C fork's encryption is the same `sqlite3mc` core anyway (§4.4).
- **Consider an encrypted DuckDB (MIT) analytics sidecar** for the heavy-read-analytics half the row-store serves poorly (aggregations over billions of mention rows). Eyes open: DuckDB is single-writer with non-incremental FTS (so it is a *read* sidecar, not the ingest engine), its at-rest encryption is < 1 year old and "does not yet meet NIST requirements" (use ≥ 1.4.2), and — critically — **it cannot directly read an encrypted SQLCipher/libSQL file**, so a sidecar means a *second* encrypted analytical store to populate and keep in sync via ETL. Justify it only if analytics latency on the row-store proves inadequate in prototyping.

**7.7 Design the key hierarchy and backup strategy explicitly.** Derive both the SQL-engine key and the blob-store key deterministically from the one passphrase via a documented KDF hierarchy (two crypto domains, one secret). Extend memory hygiene (mlock/zeroization) to the blob path. Design backup around the asymmetry: the immutable content-addressed blob store is trivially incremental (`rsync` new packs); the live SQL requires the online-backup API or a checkpoint-and-quiesce snapshot (never a naive `cp` of a live DB — §1.7). Record the accepted risk that no recovery key means a forgotten passphrase is total, irreversible loss of a multi-TB corpus.

**Target architecture in one line:** *`sqlite3mc`-or-SQLCipher single file holding article metadata + mentions (atomic ingest, WAL-governed, hash-sharded when it must grow) + a disposable contentless-delete FTS5 index (sharded, prototyped at scale) + a packed, keyed, content-addressed, age-on-packs, per-source-zstd blob store for text — with an optional encrypted DuckDB read-sidecar if row-store analytics prove too slow.* This keeps every hard constraint (local-first, one passphrase, copy→ciphertext, GPLv3, no server) while fixing the two correctness bugs and de-risking the FTS scaling wall.


## 8. Uncertainty — what could not be verified

Honest limits of this research. None of the recommendations should be committed to code before the empirical items are prototyped.

**Empirical gaps (no primary data exists — must prototype):**
- **SQLCipher/sqlite3mc overhead at multi-TB with a cold, cross-time working set is unmeasured.** The "5–15%" figure is Zetetic's own best case ("as little as") for cache-friendly access; the per-page decrypt+HMAC cost on cold page faults over a DB ≫ RAM (§1.6) is *reasoned*, not measured. No vendor TB-scale benchmark was found.
- **FTS5 beyond ~15 M documents is undocumented (§5.7).** No credible first-hand account of a single FTS5 index at tens-to-hundreds of millions of docs, working well or badly, was found. Both the risk and the sharding unit (~1 M docs/shard) are extrapolations from the one 15 M-in-16-shards datapoint. This is the largest unknown.
- **Whether SQLCipher + a loadable CJK tokenizer (wangfenjin/simple) compose cleanly at scale is untested.** Loadable extensions + an encrypted DB *should* work (extension loading must be explicitly enabled), but I found no confirmation for these specific tokenizers under SQLCipher, and no first-party pip wheel for wangfenjin/simple (bundle the `.so`).
- **age-on-packs vs symmetric-streaming throughput, and contentless-delete tombstone accumulation at target scale, are unbenchmarked.**
- **DuckDB-sidecar ETL cost and its young encryption's real-world soundness are unproven** for this use.

**Version/spec facts I could not confirm from an authoritative page:**
- Exact `SQLITE_MAX_MMAP_SIZE` default (forum says ~2 GB / `0x7fff0000`; not confirmed in the official compile-options page fetched).
- `PRAGMA cipher_memory_security` default on/off state.
- libSQL's *exact default cipher* on the embedded `encryption_key` path (AES-256 is supported via bundled sqlite3mc; the precise default was not stated on a loaded official page). Its native-encryption maturity (C fork "roadmap" wording vs shipping Rust engine) needs version-pinning verification.
- BadgerDB AES-CTR mode, Realm AES-CBC mode, ObjectBox cipher — the mode strings were not printed on the primary pages fetched (these engines are rejected on other grounds anyway, so this is immaterial).
- `rage` (Rust age) and Tink exact licenses were not independently fetched (commonly MIT/Apache-2.0 and Apache-2.0 respectively — treat as `HEARSAY` until checked).
- The `sqlite-jieba-tokenizer` crate's license was not verified.

**Attributions flagged as unverified this session:**
- **DocumentCloud = Apache Solr** could not be confirmed against a live primary source (help page returned 403); treat as `HEARSAY`.
- FSF GPLv3-compatibility rulings rely on the FSF's standing license list (gnu.org resisted automated fetching); the pivotal OpenLDAP-2.8 ruling was corroborated against the fetched license text, but other verdicts (MIT, BSD, Apache-2.0, PostgreSQL License) rely on the FSF's well-established standing classifications rather than a page fetched this session.
- The FTS5-index-size ratios (§2.1) are from SQLite's own email/Enron benchmarks; your news-article ratios will differ — measure on your own corpus.

**Reasoning explicitly labeled as inference, not citation:** the capacity math (114 M–1.1 B articles at 5–50 TB), the "what breaks first" ordering (§6), the confirmation-attack analysis (§6.3, derived by applying restic's documented design to Phase C's stated scheme), and all `ASSESSMENT`-tagged prose are the analyst's judgment, not sourced fact. They are arguments to test, not findings to trust.

**A claim marked HEARSAY and left as such:** "FTS5 is dramatically faster than FTS4 at equal settings" — no benchmark found; not relied upon.


## 9. Appendix — license verification and sources

**Per-claim citations are inline throughout** (every factual statement carries its URL and an `OFFICIAL`/`FORUM/BLOG`/`HEARSAY`/`DERIVED`/`ASSESSMENT` tag). This appendix consolidates the license check the brief required for everything *proposed*.

### 9.1 GPLv3-compatibility of every component recommended or referenced

| Component | Role in recommendation | License | GPLv3-compatible? | Source |
|---|---|---|---|---|
| SQLite (core) | base engine | Public domain | Yes | https://www.sqlite.org/copyright.html |
| SQLCipher | incumbent encryption | BSD-3-Clause | Yes | https://github.com/sqlcipher/sqlcipher |
| **sqlite3mc** (apsw-sqlite3mc) | **proposed encryption upgrade** | **MIT** | **Yes** | https://github.com/utelle/SQLite3MultipleCiphers |
| **libSQL** | **proposed successor (track)** | **MIT** | **Yes** | https://github.com/tursodatabase/libsql/blob/main/LICENSE.md |
| **DuckDB** | **proposed analytics sidecar** | **MIT** | **Yes** | https://github.com/duckdb/duckdb/blob/main/LICENSE |
| **age** (FiloSottile/age) | **proposed pack encryption** | **BSD-3-Clause** | **Yes** | https://github.com/FiloSottile/age |
| rage (Rust age) | alt. impl. | MIT/Apache-2.0 (unverified this session) | Yes (if as stated) | https://github.com/str4d/rage |
| **zstd** | **proposed compression** | **BSD OR GPLv2 (elect BSD)** | **Yes (elect BSD)** | https://github.com/facebook/zstd |
| **wangfenjin/simple** (cppjieba) | **proposed CJK tokenizer** | **MIT OR GPLv3** | **Yes** | https://github.com/wangfenjin/simple |
| restic | design reference (CAS) | BSD-2-Clause | Yes | https://github.com/restic/restic |
| Perkeep | design reference (blobpacked) | Apache-2.0 | Yes | https://github.com/perkeep/perkeep |
| BorgBackup | design reference (chunking/crypto) | BSD-3-Clause | Yes | https://github.com/borgbackup/borg |
| Tink | AEAD reference | Apache-2.0 (unverified this session) | Yes (if as stated) | https://developers.google.com/tink/streaming-aead |

**Rejected / not-recommended, for the record:** SEE and ZIPVFS (proprietary — cannot ship in GPLv3); git-annex (AGPLv3+ — external binary only, do not link its code); Signal-FTS5-Extension and lindera-sqlite (AGPLv3 — usable in a GPLv3 local-first app but wangfenjin/simple is cleaner); ObjectBox (proprietary native core); RocksDB (dual GPLv2/Apache — take Apache arm, but rejected for no real cipher/no FTS). All GPLv3-compatibility verdicts follow the FSF standing classifications at https://www.gnu.org/licenses/license-list.en.html.

### 9.2 Load-bearing primary sources (the claims the recommendation rests on)

- **WAL breaks cross-file atomicity:** https://sqlite.org/wal.html · https://sqlite.org/lang_attach.html · https://www.sqlite.org/atomiccommit.html
- **17.5 TB default-page ceiling & limits:** https://sqlite.org/limits.html · https://sqlite.org/compile.html
- **WAL checkpoint starvation:** https://sqlite.org/wal.html · https://sqlite.org/pragma.html
- **SQLCipher design/overhead/KDF:** https://www.zetetic.net/sqlcipher/design/ · https://www.zetetic.net/sqlcipher/performance/ · https://www.zetetic.net/blog/2018/11/30/sqlcipher-400-release/
- **FTS5 external-content "same database", contentless-delete, merge:** https://www.sqlite.org/fts5.html · https://www.sqlite.org/releaselog/3_43_0.html
- **FTS5 index-size ratios:** https://www.sqlite.org/fts5.html · https://sqlite.org/forum/info/3baccecae55769ff
- **CJK tokenizer (recommended):** https://github.com/wangfenjin/simple
- **CAS design references:** https://restic.readthedocs.io/en/stable/100_references.html · https://github.com/perkeep/perkeep/issues/532 · https://borgbackup.readthedocs.io/en/stable/internals/
- **age spec:** https://github.com/C2SP/C2SP/blob/main/age.md
- **zstd dictionaries:** https://github.com/facebook/zstd/blob/dev/programs/zstd.1.md
- **Prior-art / negative result:** https://icij.gitbook.io/datashare/local-mode/about-the-local-mode · https://docs.aleph.occrp.org/developers/explanation/search/ · https://simonwillison.net/2024/Aug/22/optimizing-datasette/ · https://use.expensify.com/blog/scaling-sqlite-to-4m-qps-on-a-single-server
- **Steelman upgrades:** https://github.com/utelle/apsw-sqlite3mc · https://turso.tech/blog/introducing-fast-native-encryption-in-turso-database · https://duckdb.org/2025/11/19/encryption-in-duckdb

---

*Report ends. Methodology: web research via five parallel research streams plus independent primary-source verification of the load-bearing claims (WAL/ATTACH atomicity, FTS5 external-content, SQLCipher facts, restic blob-ID scheme) by the analyst. No benchmarks or version facts were invented; unverifiable items are enumerated in §8.*
