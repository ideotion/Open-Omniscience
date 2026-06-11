# Database reliability batch — deliverable 1: gap analysis

> **0.09 cycle · maintainer mandate 2026-06-11** ("like the backup/restore
> function of an OS. If it's not entirely reliable, it should not exist, and
> I'd like it to exist"). This document is the first deliverable of the
> dedicated session: a **code-verified inventory** of what today's
> backup/restore actually covers, measured against the mandate's
> "EVERYTHING + merge-only import that cannot corrupt + encrypted by
> default" requirements (`docs/FUTURE_DEVELOPMENTS.md` §Database reliability
> mandate). It contains **no design** — deliverable 2 (the design doc)
> follows maintainer review of these gaps. Every claim below carries a
> `file:line` reference; the critical ones were hand-re-verified, not taken
> from tooling output (the 0.0.9 audit lesson).

---

## 1. What exists today (verified)

**Backup of the main database — sound at its core, narrow in scope.**

- `POST /api/database/backup` (`src/api/database.py:202`) streams a snapshot
  of the **main SQLite file only**, produced by the SQLite *online backup
  API* (`src/backup/sqlite_backup.py:76` — `Connection.backup()`), so the
  snapshot is internally consistent even mid-scrape with WAL active. Plain
  `.db`, no integrity envelope, no version stamp, no side files.
- `POST /api/safety/backup/encrypted` (`src/api/safety.py:63`) wraps the same
  snapshot in **AES-256-GCM under a scrypt-derived key** (n=2¹⁵, r=8, p=1),
  self-describing `OOENC1` header (`src/safety/crypto.py:24-44`). Wrong
  passphrase / tampering fails loudly via the GCM tag. Same scope: main DB
  only.

**Restore — replace-only, and the two paths have drifted apart.**

- Plain restore `POST /api/database/restore` →
  `restore_from_bytes()` (`src/backup/sqlite_backup.py:135-182`) is
  *defensively built*: stage upload in the data dir → validate on the temp
  copy (`PRAGMA quick_check` + required tables, read-only URI,
  `sqlite_backup.py:98-132`) → snapshot the live DB via the online backup
  API → dispose the engine pool → delete stale `-wal`/`-shm` → atomic
  `os.replace` → `init_db()` reconcile. Good machinery — **but it replaces;
  it never merges.**
- Encrypted restore `restore_encrypted_backup()` (`src/safety/backup.py:39-72`)
  decrypts and validates, then **diverges from the plain path** — see the
  defect list in §4.

**Merge exists nowhere.** The only "merge-ish" import surfaces are
domain-specific: source-catalog CSV upsert by domain
(`src/api/source_io.py:177`), signed annotation bundles per author
(`src/annotations/store.py:105`), commodity CSV / market feed imports,
calendar feed imports with in-family dedup (`src/events/feeds.py:217`).
None of them merges a *corpus* (articles/keywords/mentions/wiki/law).

**Existing integrity machinery worth building on** (not invented for this
batch — already in the schema):

| Mechanism | Where | Note |
|---|---|---|
| `articles.hash` (SHA-256, UNIQUE) | `src/database/models.py:480` | ingest-time dedup; exactly the bit-level key the merge needs |
| `source_articles.content_hash` (UNIQUE) | `models.py:874` | same |
| `law_documents.baseline_hash`/`last_hash`, `law_revisions.content_hash` (UNIQUE per doc) | `models.py:1508-1509,1527+` | change detection |
| wiki natural keys `(wiki,title)`, `(page_id,revid)` | `models.py:1391+,1434+` | merge keys for wiki domain |
| custody log: hash-chained, signed entries | `src/custody/log.py:59-95` | append-only; offline-verifiable |
| evidence/annotation bundles: Merkle + Ed25519(+ML-DSA), pinned keys | `src/reporting/evidence.py:93-129`, `src/annotations/bundle.py:85-116` | the "verify, don't trust" pattern the mandate asks for |
| versioned export envelope `oo-export-1` | `src/utils/export_envelope.py:17` | precedent for a backup manifest |

---

## 2. Coverage matrix — the mandate's "EVERYTHING" vs. today's artifact

The backup artifact is *the main SQLite file*. Everything inside it is
covered by backup (but not by merge); everything outside it is **silently
absent** from every backup ever taken.

| Mandate domain | Lives in | In backup today? | Merge on restore? |
|---|---|---|---|
| Articles + content + FTS | main DB (`articles`, `article_fts` rebuilt) | ✅ | ❌ replace |
| Keywords, mentions, families/overrides, super-groups | main DB (`keywords`, `keyword_mentions`, `keyword_family_overrides`, `keyword_supergroups(+members)`) | ✅ | ❌ |
| Wiki tracked pages + baselines + revisions | main DB (`wiki_pages`, `wiki_revisions`) | ✅ | ❌ |
| Law documents + revisions | main DB (`law_documents`, `law_revisions`) | ✅ | ❌ |
| Financial/commodity/index series + extraction rules | main DB (`commodity_prices`, `market_extraction_rules`) | ✅ | ❌ |
| Sources catalog + groups + metadata + candidates | main DB | ✅ | CSV upsert exists, separate path |
| Link graph / external sources / analyses / mentioned dates | main DB | ✅ | ❌ |
| **Custody log** | **`data/custody_log.db` — a second SQLite file** (`src/custody/log.py:125`) | ❌ | ❌ |
| **Signing keys** (custody, evidence, annotations × Ed25519 + ML-DSA) | **`data/keys/*.pem`,`*.key`** (`signing.py:149-150`, `evidence.py:45`, `bundle.py:125-126`) | ❌ | n/a — losing them breaks re-signing identity forever |
| **Annotations** (mine + imported authors) | **`data/annotations/mine.json`, `imported/*.json`** (`store.py:37-42`) | ❌ | per-author import exists, separate path |
| **Settings** (app, scheduler, custody, safety) | **`data/*.json`** (`app_settings.py:56`, `scheduler/settings.py:63`, `custody/settings.py:61`, `safety/settings.py:59`) | ❌ | ❌ |
| **Imported calendar events + feed verdicts** | **`data/calendar_feed_imports.json`, `calendar_feed_checks.json`** (`events/feeds.py:108-112`) | ❌ | ❌ |
| **Event subscriptions** | **browser localStorage `oo.agenda.subs`** (`index.html:2655`) — the server never sees them | ❌ impossible today | ❌ |
| Other client prefs (UI state `oo.ui`, language, timemap prefs, briefing toggle) | browser localStorage | ❌ impossible today | ❌ |
| Operational logs (`scheduler_runs`, `import_results`, `app_errors`, `feed_preflight`, `field_test` `.jsonl`) | `data/*.jsonl` | ❌ | ❌ |
| Offline wiki dumps | `data/wiki_dumps/` (multi-GB) + state JSON (`wiki/dumps.py:64`) | ❌ | ❌ |
| User-edited curation YAML (equivalence rings `keyword_equivalents.yml`; seeds for super-groups/events) | repo `configs/` — seeds live in DB after first boot, but ring edits are *only* in the YAML | ❌ | ❌ |
| Newsletters (future domain) | — | the mandate exists *because* of this | — |

**Summary: one of the three persistent stores is covered.** The main DB is
backed up well; the custody-log DB and the entire `data/` side-file
population (keys, settings, annotations, event imports, logs) are not, and
two classes of state (localStorage, user-edited YAML) are currently
*unreachable* by any server-side backup.

---

## 3. Mandate requirement → gap, point by point

| Mandate requirement | Today | Gap |
|---|---|---|
| Backup carries everything | main DB only | §2 — custody DB, keys, settings, annotations, events, (decision: dumps/logs/localStorage) |
| Merge-only import, never replace | both restores replace | no merge engine exists for any corpus domain |
| Bit-level dedup (content hash + byte compare) | hashes exist at ingest (§1 table) | never consulted by restore; no byte-compare fallback; tables without content hashes (mentions, settings…) have no dedup key defined |
| FK remapping | n/a (whole-file swap) | required for merge: `articles.id`, `keywords.id`, `source_id`, `page_id`, `document_id`… all collide between two real corpora |
| Dry-run preview | none | — |
| Work on a copy + atomic swap | plain restore: yes; encrypted restore: **no** (§4) | merge must inherit the plain path's discipline |
| Post-merge verification (counts + hash spot-checks + FTS rebuild check) | none; `init_db()` runs `ensure_fts` but verifies nothing | — |
| Cross-version restore | **broken by design today**: `restore_from_bytes` → `init_db()` → `create_all` (`session.py:94-113`) creates *missing tables only* — it cannot add columns; nothing in `src/` ever runs `alembic upgrade` (manual `make migrate` only); `stamp_if_unstamped` leaves an old stamp alone | restoring an older-schema backup yields a DB the current app crashes on (first query touching a newer column); no schema-rev check at validation (`_REQUIRED_TABLES` is just `articles`,`sources`, `sqlite_backup.py:38`) |
| Export encrypted (default) AND plaintext | both exist (for the main DB) | encrypted is *not* the default in the UI flow; artifact has no manifest/version; scope too narrow (§2) |
| Article content hash + authentication hash across the export boundary | content hash ✅; authentication (signed) hash ❌ | evidence bundles sign Merkle roots but are a separate export, not the backup |
| Provenance safeguards on merged rows (never laundered; incoming custody sigs verified not trusted) | nothing — no origin column anywhere in the main schema for "arrived via merge from corpus X" | custody/annotation verification primitives exist to build on (§1) |
| At-rest encryption by default, passphrase at start, no recovery, doctor attests | working DB plaintext; keys plaintext by default (scrypt-wrap only if `OO_KEY_PASSPHRASE` set — and the **evidence key is always plaintext**, `evidence.py:55-61`); custody DB plaintext; no prompt; no doctor attestation | the SQLCipher layer (gate zero passed, §6) |

---

## 4. Defects found in the *existing* paths (hand-verified; fix in this batch)

These are not "missing features" — they are weaknesses in what already ships:

1. **Encrypted restore writes the live DB non-atomically** —
   `dest.write_bytes(plaintext)` (`src/safety/backup.py:69`). A crash
   mid-write leaves a truncated live DB. The plain path got this right
   (`os.replace`, `sqlite_backup.py:169`); the encrypted path never adopted it.
2. **Encrypted restore leaves stale `-wal`/`-shm` files** — the old WAL can
   be replayed against the *new* file on next open: a textbook SQLite
   corruption vector. (Plain path removes them, `sqlite_backup.py:165-168`.)
3. **Encrypted restore never disposes the engine pool** — live connections
   keep file handles on the replaced inode; mixed old/new reads until restart.
4. **Encrypted restore's pre-restore snapshot is `dest.read_bytes()`**
   (`safety/backup.py:66-68`) — a naive copy of the main file *while WAL is
   active*, so the "safety net" itself can miss the newest commits. The plain
   path snapshots via the online backup API (`sqlite_backup.py:161`).
5. **Encrypted restore skips `init_db()`** — no FTS/schema reconcile after
   swap (plain path does it, `sqlite_backup.py:173`).
6. **`calendar_feed_imports.json` is written non-atomically**
   (`events/feeds.py:104` `write_text`) — a crash mid-write loses *all*
   imported events. (The settings stores got atomic temp+replace right,
   e.g. `app_settings.py:89-121`; this one didn't.)
7. **Backup validation accepts any SQLite file containing `articles` +
   `sources`** — no schema revision check, no app-version stamp in the
   artifact, so a cross-version or truncated-but-valid-SQLite file is only
   discovered when the app breaks later.
8. **Pre-restore snapshots accumulate forever** (`pre-restore-*.db` /
   `*.pre-restore-*.bak`) — never pruned, never surfaced in the UI; on small
   disks repeated restores can fill the volume (minor, but "OS-grade" tools
   manage their own safety nets).
9. **Two restore implementations drift** — the single-fetch-path lesson
   (`EthicalFetcher`) applies verbatim: one restore path, with encryption as
   an envelope, not a fork.

---

## 5. At-rest encryption — current state vs. the ruling

| Store | At rest today |
|---|---|
| Main DB `open_omniscience.db` | plaintext SQLite (WAL) |
| Custody log `custody_log.db` | plaintext SQLite |
| Signing keys | plaintext PEM/raw, `0600`; scrypt-wrapped **only** if `OO_KEY_PASSPHRASE` env set (`signing.py:84-99`); evidence key **always** plaintext (`evidence.py:55-61`) |
| Backup blob | the only encrypted artifact (`OOENC1`, opt-in endpoint) |
| Passphrase UX | none — no prompt, no first-launch note, no doctor attestation |

So the ruling's target state (working DB encrypted by default, one
passphrase at start, honesty gate: prompt ships *with* crypto) is entirely
unbuilt — but cleanly buildable: scrypt/AES-GCM precedents exist in-tree
(`safety/crypto.py`), and the engine has a single creation point
(`session.py:48-66`) where `PRAGMA key` wiring belongs.

---

## 6. Gate zero — sqlcipher3 portability checkpoint: **PASSED**

Verified today (2026-06-11), per the standing portability checkpoint:

- **PyPI `sqlcipher3` 0.6.2** ships cp313 wheels for **all three OSes**:
  `manylinux_2_28`/`musllinux` x86_64+aarch64+i686, `macosx_10_13_x86_64` /
  `11_0_arm64` / `universal2`, and `win32`/`win_amd64`/`win_arm64`
  (requires-python ≥3.9; we are 3.13-only).
- **Linux, functionally proven in this session** (cp313 wheel, real run):
  SQLCipher **4.12.0 community** on SQLite 3.51.1; `PRAGMA key` works;
  compile options include **`ENABLE_FTS5`** (our search index requirement)
  — FTS5 virtual table created, populated and matched inside an encrypted
  DB; file header is ciphertext (no `SQLite format 3` magic); wrong key
  fails loudly (`DatabaseError`, HMAC check logged); stdlib `sqlite3`
  cannot open the file.
- **Windows + macOS wheels downloaded and inspected**: each contains one
  self-contained extension (5.9–7.1 MB `.pyd`/`.so`) with the SQLCipher
  codec symbols and `fts5` baked in; **no external `libsqlcipher`
  dependency**.
- **SQLAlchemy wiring proven**: `create_engine` with a `creator` +
  `PRAGMA key` on the `connect` event round-trips data and rejects a wrong
  key; SQLAlchemy 2.0's built-in `sqlite+pysqlcipher` dialect already
  resolves `sqlcipher3` as its DBAPI.
- Alternatives ruled out: `sqlcipher3-binary` is Linux-x86_64-only;
  `pysqlcipher3` is source-only. `sqlcipher3` proper is the driver.
- **Honest caveat:** Windows/macOS verified by wheel inspection, not
  execution (no such machines in this environment). The universal-portability
  CI matrix (planned, FUTURE_DEVELOPMENTS §Universal portability) remains
  the *definition* of supported — it should gain a SQLCipher smoke test the
  day the driver lands.

---

## 7. Decisions needed from the maintainer (before/within deliverable 2)

Flagged now so the design doc can resolve them rather than discover them.
One-line recommendations included; nothing here is built yet.

- **D1 — Artifact scope strategy.** Backup "everything" two ways:
  (a) a new multi-file container (manifest + main DB + custody DB + keys +
  side JSONs), or (b) **migrate the orphan state INTO the main DB first**
  (settings, annotations, imported events → tables; custody log stays its
  own file *by design* — append-only evidence log), then one container =
  one DB + custody DB + keys + manifest. *Lean (b): fewer moving parts
  forever after, and SQLCipher then covers settings/annotations/events for
  free. (b) is more migration work up front.*
- **D2 — Private keys in the plaintext export.** An encrypted backup may
  carry the signing keys; a **plaintext** export carrying private keys
  hands the operator's signing identity to anyone who touches the file
  (forged custody entries thereafter). *Recommend: plaintext export
  excludes keys and says so loudly; encrypted carries them.*
- **D3 — Offline wiki dumps** (`data/wiki_dumps/`, multi-GB,
  re-downloadable). *Recommend: excluded; the manifest records their
  existence + sizes and restore says "re-download via Settings".*
- **D4 — localStorage state.** The mandate says "settings" are included;
  agenda subscriptions (`oo.agenda.subs`) are functional state the server
  never sees. *Recommend: migrate agenda subs (and other functional prefs)
  server-side into app settings — also fixes their invisibility to any
  future device migration; cosmetic prefs (theme, pane sizes) stay client.*
  Needs a ruling on where the settings/cosmetics line sits.
- **D5 — Operational `.jsonl` logs** (diagnostics, not corpus).
  *Recommend: include (they are small and the field-test protocol relies on
  them), merge = append-with-dedup by line hash; cheap.*
- **D6 — SQLCipher scope.** Just the main DB, or also `custody_log.db` and
  the key files, all unlocked by THE passphrase (one secret, per the
  ruling; internally derive per-store keys)? *Recommend: all three — one
  passphrase story, no plaintext stragglers holding the same evidence.*
- **D7 — Cross-version floor.** Merge-import must run `alembic upgrade` on
  the *staged copy* before merging (never on the live DB), which bounds how
  old an artifact can be. *Recommend: accept artifacts from the 0.0.8
  baseline schema (`6ae5766d3136`) onward; older = explicit refusal naming
  the artifact's revision.* The artifact manifest must therefore record
  `alembic_rev` + app version.

---

## 8. What deliverable 2 will contain (once §7 is settled)

The unified design: one restore path (encryption as envelope), a
domain-by-domain merge plan keyed on the natural/content keys inventoried
in §1 (with FK remapping and provenance-of-merge columns), the staged-copy
pipeline (stage → migrate → dry-run diff → merge on a copy → verify →
atomic swap), the backup manifest format, the SQLCipher key story
(THE passphrase → per-store keys, first-launch note, doctor attestation,
one-way encrypt tool), and the torture-test suite — which is the
acceptance metric: interrupted imports mid-write, duplicate floods,
wrong-passphrase handling, cross-version restore, plaintext↔encrypted
round trips, merge of two divergent corpora. A failed torture test blocks
the feature.
