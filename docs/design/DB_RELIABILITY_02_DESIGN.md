# Database reliability batch — deliverable 2: design

> **0.09 cycle · follows `DB_RELIABILITY_01_GAP_ANALYSIS.md`.** The maintainer
> instructed "continue from where you left off" after the gap analysis was
> delivered; the seven decision points (D1–D7) are therefore resolved here
> **per the leanings stated in the gap analysis** — each resolution below is
> explicitly marked `**[D# — veto point]**` and can be reversed before its
> implementing PR lands. The torture-test suite (§7) is the acceptance
> metric: **a failed torture test blocks the feature.**

---

## 0. Principles (restated, binding)

1. **One restore path.** Encryption is an envelope, never a fork
   (the `EthicalFetcher` lesson; the encrypted-restore drift found in the gap
   analysis §4 is the proof). *Already enforced as of this batch's first
   commit: `restore_encrypted_backup` now delegates to `restore_from_bytes`.*
2. **The live database is sacred.** Every operation that could fail works on
   a staged or working copy; the live file changes only via one atomic
   `os.replace` (or not at all).
3. **Honesty by construction.** The artifact says what it contains and what
   it deliberately excludes; restore says what it got, what it merged, what
   it skipped and why; encryption claims state their threat model (protects
   a seized/off machine, NOT a compromised running session); the passphrase
   prompt ships in the same PR as the working crypto, never before.
4. **Merged data is never laundered.** Rows arriving via import keep a
   queryable origin; incoming custody signatures are verified, never trusted;
   evidence exports distinguish first-party ingest from merged material.

---

## 1. Decisions adopted

- **[D1 — veto point] Orphan state migrates INTO the main database.**
  New tables (one migration): `app_state` (namespaced KV with schema-version
  rows replacing `app_settings.json`, `scheduler_settings.json`,
  `custody_settings.json`, `safety_settings.json` — the JSON files become
  read-once legacy sources, imported on first boot after upgrade, then
  renamed `*.migrated`), `annotations_mine`, `annotation_authors` +
  `annotations_imported`, `event_imports` + `event_feed_verdicts` (replacing
  the two calendar JSONs). Result: the main DB carries *all* corpus and
  functional state; SQLCipher then covers it all for free. The custody log
  **stays a separate file by design** (append-only evidence log with its own
  chain; mixing it into the corpus DB would couple evidence integrity to
  corpus churn). Wiki dumps stay files (D3).
- **[D2 — veto point] Plaintext exports NEVER contain private keys.**
  The encrypted artifact carries `keys/`; the plaintext artifact omits it,
  records `"keys_included": false` in the manifest, and the UI says loudly:
  *"Plaintext backups exclude your signing keys — anyone holding them could
  sign as you. Use an encrypted backup to carry your identity."*
- **[D3 — veto point] Offline wiki dumps are excluded** from artifacts. The
  manifest records their existence, languages and sizes; restore surfaces
  "N dumps were present (X GB) — re-download via Settings → Wikipedia".
- **[D4 — veto point] Functional client state moves server-side.** Agenda
  subscriptions (`oo.agenda.subs`) move into `app_state` (REST-backed, the
  localStorage value imported once and kept as fallback); cosmetic prefs
  (theme variant, pane sizes, text size, language) stay client-side and are
  documented as device-local. The line: *if losing it changes what the app
  collects or shows as data, it is functional → server; if it only changes
  how things look on this screen, it is cosmetic → client.*
- **[D5 — veto point] Operational `.jsonl` logs ARE included** (small,
  diagnostic value, the field-log protocol depends on them). Merge = append
  new lines deduplicated by line hash; never interleaved silently — merged
  segments carry a `# merged-from <artifact-id>` marker line.
- **[D6 — veto point] SQLCipher covers all three stores.** Main DB and
  `custody_log.db` are SQLCipher-encrypted; key files keep the existing
  scrypt+AES-GCM wrap (`custody/signing.py`) — with `OO_KEY_PASSPHRASE`
  defaulting to THE passphrase so one secret unlocks everything (each store
  still derives via its own KDF: SQLCipher's internal PBKDF2 per database,
  scrypt for key wraps). The evidence key's `NoEncryption` gap is closed in
  the same PR.
- **[D7 — veto point] Cross-version floor = the 0.0.8 baseline schema**
  (`6ae5766d3136`). The staged copy is `alembic upgrade`-ed to head before
  any merge; artifacts older than the floor, or *newer than the running
  app*, are refused with the artifact's revision named in the error.
  Legacy artifacts (bare `.db`, v1 `.ooenc`) remain restorable forever:
  they enter the same pipeline as "corpus-only, no manifest" with that fact
  stated in the preview.

---

## 2. The artifact: `oo-backup-2`

One ZIP (stdlib `zipfile`, STORED for the DBs — they compress poorly and
hash cheaply; DEFLATE for text members), extension `.oobak` (plaintext) or
`.oobak.ooenc` (encrypted = the same ZIP bytes through the existing `OOENC1`
AES-256-GCM envelope, `safety/crypto.py`, unchanged format):

```
manifest.json            oo-backup-2: app_version, alembic_rev, created_at,
                         host fingerprint (pubkey id), per-member sha256 +
                         sizes, corpus stats (per-table counts), members
                         deliberately excluded (wiki dumps, keys-in-plaintext)
                         + WHY, signature block (Ed25519 over the canonical
                         manifest by the evidence key; verify-don't-trust on
                         import)
corpus.db                online-backup snapshot of the main DB (plaintext
                         INSIDE the artifact even when the live DB is
                         SQLCipher'd: the artifact's own envelope provides
                         the at-rest protection; a plaintext export is the
                         operator's explicit choice, D2 warning shown)
custody_log.db           online-backup snapshot of the custody log
keys/…                   encrypted artifact only (D2)
logs/*.jsonl             D5
```

The manifest's signed per-article anchor: `corpus.db`'s article table already
carries per-row `hash` (SHA-256); the manifest records the Merkle root over
`(id, hash)` pairs (reusing `reporting/evidence.py`'s tree). That is the
mandate's "content hash + authentication hash": per-article content hashes,
artifact-level signed root proving the set was not altered after export.

Endpoints: `POST /api/backup/v2` (body: passphrase | `plaintext: true`) and
`POST /api/backup/v2/restore` (multipart; `stage` → preview, `commit` →
merge). The legacy endpoints stay, delegating inward, and are marked
deprecated in the API docs.

---

## 3. The merge pipeline (restore = merge-only)

```
upload → detect (OOENC1? zip? bare sqlite?) → STAGE in data_dir/.restore-<ts>/
  → manifest hash + signature verification (signature failure = warn loudly,
    "unsigned/unverifiable artifact", continue only on explicit consent)
  → quick_check each DB member (read-only URI)
  → alembic upgrade the STAGED corpus copy to head   [D7; never the live DB]
  → DRY-RUN DIFF (always): per-domain counts {new, identical-duplicate,
    conflict, would-remap}, sample rows, size delta → returned as the preview
  → operator confirms (UI dialog / API flag)
  → WORKING COPY: online-backup snapshot of the live DB → all merge writes
    go to the copy inside one transaction per domain batch
  → POST-MERGE VERIFICATION on the copy: PRAGMA foreign_key_check == empty;
    PRAGMA quick_check == ok; expected counts == actual; content-hash spot
    checks (random sample per domain, n≥32); FTS rebuild ('insert into
    article_fts(article_fts) values("rebuild")') + doc-count == articles
    count + a sample MATCH returns the planted row
  → atomic swap (existing discipline: dispose pool, drop stale -wal/-shm,
    os.replace), pre-merge snapshot kept as pre-restore-<ts>.db
  → REPORT (persisted to merge_batches + returned): everything from the
    dry-run plus what actually happened, ms timings, verification verdicts
```

Failure **anywhere** before the swap leaves the live DB byte-identical and
removes the staging directory. A crash **at** the swap is safe by
`os.replace` atomicity. Snapshot retention: keep the newest 3
`pre-restore-*.db`, surface them in Settings → Data & backup with dates and
sizes (gap analysis §4.8).

### 3.1 Per-domain merge semantics

The merge engine is table-driven: each domain registers `(natural_key,
content_key, fk_remaps, conflict_policy)`. Locked policies:

| Domain | Match on | Duplicate test | Conflict policy |
|---|---|---|---|
| sources (+groups, metadata) | `domain` | field-by-field | **local wins**; incoming differences listed in the report, never applied silently |
| articles | `hash` (SHA-256), then `canonical_url` | **byte-compare content on hash match** (the mandate's bit-level clause) | same-hash+same-bytes = skip; same-canonical-url+different-hash = both kept (two observations of a changing page — that is signal) |
| keywords | `(normalized_term, language)` | n/a | keep local row; remap incoming mention/association FKs onto it; `frequency` recomputed, never summed blindly |
| keyword_mentions | `(keyword_id, article_id)` after remap | counts equal | differing counts: keep local, report |
| family overrides / supergroups(+members) | `normalized_term` / `name` | — | **user curation: local always wins**; incoming-new inserted |
| wiki_pages / wiki_revisions | `(wiki,title)` / `(page_id,revid)` after remap | diff bytes | revisions are append-only facts: insert missing, never rewrite |
| law_documents / law_revisions | `(jurisdiction,url)` / `(document_id,content_hash)` | — | as wiki |
| commodity_prices | `(symbol, market, observed_on, source, currency, unit)` | price equality | same key, different price = **disagreement: keep both flagged in report, never averaged** (requires adding this composite UNIQUE index — migration in PR-2) |
| market_extraction_rules | `(source_id→remap, symbol, url)` | — | local wins |
| external_sources / source_articles / links / relationships | `domain` / `url`+`content_hash` / composite | — | dedup, remap |
| article_analyses / mentioned_dates | `(article_id→remap, kind, model)` / `(article_id, mentioned_on, snippet)` | — | insert-missing |
| annotations (post-D1 tables) | author_id + content hash of `(target,kind,value,note,created_at)` | — | signature re-verified at import; unverifiable = refused per author |
| settings (`app_state`) | — | — | **never merged**: local wins entirely; incoming values shown read-only in the report for manual adoption |
| custody log | `entry_hash` | — | §3.2 |
| `.jsonl` logs | line hash | — | append-missing with origin marker (D5) |

### 3.2 Custody: chains are immutable, identities are foreign

Two corpora = two signing identities = two hash chains. They are **never
spliced**. Imported entries land with their chain intact under a
`chain_id` (new column, default = local chain), their signatures verified
against the public keys *embedded in the imported export* at import time —
a broken chain or bad signature imports as `verified: false` with the
reason, loudly visible (never repaired, never re-signed, never silently
dropped: the failure itself is evidence). The custody UI gains a chain
selector ("this machine" / imported chains by fingerprint).

### 3.3 Provenance of merged rows

One new table, no schema churn on domain tables:

```
merge_batches(id, imported_at, artifact_manifest_json, origin_fingerprint,
              counts_json, report_json)
merged_rows(batch_id, table_name, row_id)   -- composite PK, indexed
```

Reader, analytics and evidence exports JOIN against `merged_rows`: merged
articles render a "merged from <fingerprint> on <date>" chip and evidence
bundles carry `"origin": "merged:<batch>"` per item — imported material can
never silently launder into first-party evidence.

---

## 4. SQLCipher at-rest encryption (ON by default)

**Driver:** `sqlcipher3` 0.6.2 (gate zero passed: cp313 wheels Linux ✅
functional / Windows ✅ wheel-inspected / macOS ✅ wheel-inspected; SQLCipher
4.12.0 community, `ENABLE_FTS5`; pinned `>=0.6.2`). New core dependency;
both venv profiles re-verified; the future 3-OS CI matrix gains a SQLCipher
smoke job.

**One connection factory.** A new `src/database/connect.py` owns *every*
SQLite connection in the app: the SQLAlchemy engine (`creator=`), the raw
`sqlite3.connect` sites (`sqlite_backup.py`, `custody/log.py`, FTS helpers)
all route through it. It applies `PRAGMA key` (when the store is encrypted),
then the existing WAL/foreign-key/busy-timeout pragmas. Raw passphrase goes
to SQLCipher's own KDF (PBKDF2-HMAC-SHA512, 256k iterations, v4 defaults —
documented, not reinvented); `PRAGMA key` is issued with a bound parameter
on the cursor, never interpolated into logged SQL.

**Boot UX (the ruled flow).**
- App starts **locked**: the loopback server serves only `/unlock` (and
  static assets) until a passphrase succeeds. `OO_DB_PASSPHRASE` env
  unlocks headless runs (scripts, tests, the installer's first boot).
- First launch (no DB yet): create-passphrase page with the plain note,
  verbatim ruling: *choose something unique and remember it — **there is no
  recovery and no decryption alternative**; a lost passphrase costs
  re-collection time, not unique data* (+ the recorded contingency: this
  premise is revisited before newsletters ship). Typed twice; no strength
  theater beyond a minimum length (8); the threat-model line shown right
  there: *protects this file if the machine is seized or the file is copied
  — it cannot protect a session that is already running and compromised.*
- Wrong passphrase: loud error, unlimited local retries (it is the
  operator's own machine; lockout would be security theater).
- Plaintext opt-out: `OO_DB_PLAINTEXT=1` or an explicit installer choice,
  attested by doctor; the unlock page is then skipped (no lock screen over
  a plaintext file — fabricated security is forbidden).
- **The unlock page, the first-launch note and the doctor line ship in the
  same PR as the working crypto** (honesty gate), with locale keys ×12.

**Existing databases:** `scripts/encrypt_db.py` + a Settings flow — explicit
consent, snapshot first (online backup API), then `sqlcipher_export()` into
a new encrypted file, verify (quick_check + counts + FTS sample under the
key), atomic swap, original kept as `pre-encrypt-<ts>.db` until the operator
deletes it from the UI. One-way as ruled (an operator with the passphrase
can always produce a plaintext *backup*; the tool itself never decrypts in
place). Never silent on upgrade: an existing plaintext DB keeps working and
shows a persistent, dismissable "your corpus is not encrypted at rest"
notice with the one-click path.

**Doctor attests** (`/api/system/doctor` + the Settings panel): per store —
encrypted yes/no, cipher version when yes, plus the threat-model sentence.
Never claims protection it can't verify (it opens the file header and says
what it found).

**Key story in one paragraph (the coherent whole):** THE passphrase (one
stable secret) unlocks: the main DB and custody DB via SQLCipher's KDF, and
the key files via the existing scrypt wrap (`OO_KEY_PASSPHRASE` defaults to
it). Backups ask for a passphrase per export (default: reuse THE passphrase;
choosing a different one is allowed for hand-off scenarios and recorded in
the manifest as `key_hint: per-export`). Nothing stores the passphrase;
nothing can recover it; doctor and the manual say so in those words.

---

## 5. What existing surfaces change

- Settings → Data & backup: encrypted download becomes the **primary**
  button (passphrase dialog), plaintext behind an expander with the D2 keys
  warning; Restore = file picker → staged preview table (the dry-run diff,
  per-domain) → typed confirmation; snapshot list with restore/delete.
- Legacy `.db` / v1 `.ooenc` artifacts: accepted forever (D7), preview
  states "legacy corpus-only artifact — settings/custody/keys not present".
- The reader/evidence/analytics surfaces gain the merged-origin chip (§3.3).
- USER_MANUAL: a rewritten "Backups, restore & encryption" chapter with the
  threat model stated; ETHICS note on merged provenance.
- All new chrome strings keyed ×12 locales (ritual).

## 6. Implementation order (PRs onto `0.09`)

1. **PR-A (shipped with this design):** restore-path unification + atomic
   event-store writes (gap §4 defects) — merged into the batch branch.
2. **PR-B:** D1 migrations (app_state, annotations, event imports) +
   read-once legacy import + commodity composite index + `merge_batches`/
   `merged_rows`; D4 agenda-subs move.
3. **PR-C:** artifact v2 writer + manifest signing + new backup endpoints +
   Settings flow (encrypted-default).
4. **PR-D:** the merge engine + dry-run preview + post-merge verification +
   report persistence; legacy-artifact adapter.
5. **PR-E:** SQLCipher (factory, unlock/create UX, env, doctor, encrypt
   tool, plaintext opt-out) — the crypto PR, self-contained.
6. **PR-F:** torture suite completion + cross-version fixtures + docs/i18n
   sweep. (Torture tests land WITH each PR they gate; PR-F is the
   consolidation + the missing-scenario fill.)

## 7. The torture-test suite (acceptance metric — a failure blocks)

Normal pytest under `tests/torture_db/`, CI-blocking by construction:

- **T1 interrupted import:** subprocess merge killed (SIGKILL) at randomized
  points mid-merge → live DB byte-identical to its pre-merge snapshot;
  staging dir cleaned on next boot.
- **T2 duplicate flood:** the same artifact imported 3×; a 10×-duplicated
  article set; row counts stable after pass 1; report says "all duplicates".
- **T3 wrong passphrase:** artifact decrypt AND DB unlock paths — loud
  typed errors, zero partial state, no plaintext temp left behind.
- **T4 cross-version:** synthesized 0.0.8-baseline artifact (fixture built
  by alembic downgrade scripts) merges after staged upgrade; pre-floor and
  future-revision artifacts refused naming the revision.
- **T5 round trips:** encrypted→restore→plaintext→restore→encrypted; final
  logical dump (ordered per-table rows) identical to the origin's.
- **T6 divergent corpora:** two seeded corpora sharing N articles with
  colliding autoincrement IDs, conflicting keyword IDs, distinct custody
  chains → FK remap correctness (every mention resolves to the right
  article by content), provenance rows complete, custody chains separate
  and verified, conflict report exact.
- **T7 crash at swap:** fault injection around `os.replace` + stale-WAL
  scenarios → opens clean either as old or as new, never as a hybrid.
- **T8 FTS truth:** post-merge FTS doc-count == articles count; a planted
  unique token in a merged article is findable; the rebuild check fails the
  merge if not.
- **T9 custody verification:** tampered imported entry / broken chain →
  imported as `verified:false` with reason, local chain untouched; valid
  foreign chain verifies offline afterward.
- **T10 settings sanctity:** merge never alters local `app_state`.
- **Property tests (hypothesis):** merge idempotence `merge(A, export(A)) = A`;
  count-symmetry `|merge(A,B)| == |merge(B,A)|` per domain.

## 8. Out of scope (recorded so nothing silently rides along)

Newsletter scraper (blocked on this batch, by ruling); the no-recovery
revisit (contingency fires before newsletters); Postgres backends (refused
honestly today, unchanged); key rotation/re-key UX beyond `PRAGMA rekey`
(documented command, UI later); multi-device sync (this is backup/merge,
not sync — saying so in the manual).
