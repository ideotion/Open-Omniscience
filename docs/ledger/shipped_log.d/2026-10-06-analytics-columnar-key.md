## 2026-10-06 — analytics/columnar-key

- **2026-10-06 · analytics/columnar-key (release candidate diagnostics, PR #MMMM, plan A of the RC thread; closes finding (2) of the 2026-09-17 entry "Two findings DISCLOSED, not fixed": CodeQL `py/weak-sensitive-data-hashing` at `src/analytics/columnar.py`).**
The persisted DuckDB cache was opened with `sha256("oo-columnar-v1:" + passphrase)`, one fast hash of the one passphrase that opens the corpus too behind PBKDF2-HMAC-SHA512 x 256,000. `_derive_key` is now
`hashlib.pbkdf2_hmac("sha512", passphrase, salt, 256_000, dklen=32)` (the count is SQLCipher 4's own; `tests/test_columnar_key_derivation.py` reads it back from a live connection and pins the derivation
against two answers computed by OpenSSL, one with non-ASCII text) with a random 16-byte salt per store in the sidecar `analytics.duckdb.kdf` (a v2 JSON record written to a sibling, fsynced and moved into
place, readable by its owner, under a lock; on `crypto_erase._DUCK_FILES` and the uninstall watcher's two lists, which also name the engine's log `analytics.duckdb.wal`). A store without a valid v2 sidecar is removed with its log before a new sidecar is written and
rebuilt, never opened or migrated. The key is a BOUND PARAMETER of the `ATTACH` (`ENCRYPTION_KEY ?`) and the path's quotes are doubled, because MEASURED with DuckDB 1.4.4 and 1.5.5 a path holding an apostrophe
ended the literal early and the parse error quoted the first 16 to 24 characters of the key written after it, which an exact-match scrub does not find; a store made under a bound key opens under the same key
written as a literal and under no other (a real encrypted attach on 1.5.5 with DuckDB's software backend). `encryption_gate(path)` no longer takes the passphrase, probes with a random key and attaches the way the
store does; `connect`, `encryption_gate` and `refresh_persisted_read_model` write their failures through `log_failure` (`connect` names the passphrase and the derived key, the gate the probe's key it made and the refresh the
passphrase; each also takes out every passphrase the process holds), and `tests/test_p0_validation.py` holds the module (thirteen modules now; `encryption_key` a
secret's name, `columnar.py` out of `_NOT_GUARDED`). `tests/test_passphrase_hashing_guard.py` walks every `.py` under `src/` and `scripts/` (760 files; 113 fast hashes, none reaching a passphrase-like name, and the
cache's one stretching call) and fails on a fast hash (`hashlib` but `pbkdf2_hmac` and `scrypt`, `hmac`, a hash object's `update`) of a name that says passphrase, password, pw or secret or of anything made from it,
with an empty allow-list. A derivation costs about 0.21 s (measured), paid by the persisted branch only, which no shipped build reaches (the secure backend is not bundled). The CI-only httpfs round trip
now tells the persisted store from the in-memory fallback (it used to assert only that a connection came back) and holds a canary row that the store's bytes must not show, a real-engine test with the
software backend runs the statement in a directory with an apostrophe where DuckDB has one, two more measure what the engine does with a bound key (a lowercase-hex `str` is never quoted
by a failing ATTACH's error; a `str` with a character outside ASCII or a backslash is quoted WHOLE by the STRING-to-BLOB cast error, and the failure's record takes it out), and the `columnar` lane now names `tests/test_columnar_key_derivation.py` (its 24 engine tests were skips in every lane until the `columnar`
lane, which has DuckDB, named it). Sixty-one mutations of the derivation, the sidecar, the statement, the gate, the erase lists and the walker are each caught (seven of the first fifty-two were not, and each is a test now), and
twelve more for the fold of the read's findings (the stretching rule, the failed open's drop, the lists that name the log, the lane) and four for the gate's record and the echo tests
(the gate back to `exc_info`, without the probe's key, the key bound as bytes, the failed open's record without the key) are each caught too: seventy-seven in all. What stays outside is in
`OPEN_QUEUE.md` (the entry "THE COLUMNAR CACHE'S KEY IS STRETCHED LIKE THE CORPUS'S"): no build reads the store yet, the bound key's equivalence to a literal was proven on 1.5.5 only, no derived-key cache,
the guard reads names and not values (a `secret`, `pw` or `pwd` name that is not the passphrase is flagged too: two scripts' Playwright handle `pw` was renamed), CodeQL's verdict is read from the PR, the
scrub is an exact match of the shapes the code writes, and the gate's keyless-open step accepts any failure. Lesson: `LESSONS.md`, the entry "A KEY STRETCHED FROM THE PASSPHRASE
COSTS WHAT THE STRONGEST FILE THE SAME PASSPHRASE OPENS COSTS, AND THE KEY STAYS OUT OF THE STATEMENT THAT CARRIES IT".
