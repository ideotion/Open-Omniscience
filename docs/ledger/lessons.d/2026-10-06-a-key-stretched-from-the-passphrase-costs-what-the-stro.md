## 2026-10-06 — A KEY STRETCHED FROM THE PASSPHRASE COSTS WHAT THE STRONGEST FILE THE SAME PASSPHRASE OPENS COSTS, AND THE KEY STAYS OUT OF THE STATEMENT THAT CARRIES IT (release candidate diagnostics, 2026-10-06, PR #MMMM, `src/analytics/columnar.py`, `tests/test_passphrase_hashing_guard.py`)

The persisted DuckDB cache was opened with `sha256("oo-columnar-v1:" + passphrase)`: one fast hash of the ONE passphrase that opens everything, which CodeQL
(`py/weak-sensitive-data-hashing`) flagged and `OPEN_QUEUE.md` had recorded as disclosed, not fixed. **(1) The cost an attacker pays is the cost of the CHEAPEST file the passphrase
opens, not of the one that matters most.** The corpus is stretched by SQLCipher 4 at PBKDF2-HMAC-SHA512 x 256,000; a cache keyed by one SHA-256 beside it is the offline attack on the same
passphrase, and "it is only a disposable cache" is why migrating it costs nothing, not why it may be cheaper. The key is now `hashlib.pbkdf2_hmac("sha512", ..., 256_000)`. The count is
SQLCipher's own, and a test reads it back from a live connection (`PRAGMA kdf_iter`) rather than copying the number, so the two cannot drift; the derivation is pinned against known
answers computed by OpenSSL, an implementation that is not ours. It costs about 0.21 s a derivation (measured, five runs), paid only by the persisted branch (no shipped build reaches it:
the secure backend is not bundled yet), once per process on the serve path (it holds one connection) and once per background refresh. A cache of the derived key was NOT built: it would
keep a second secret in memory that `set_passphrase(None)` and the crypto-erase do not clear. **(2) The salt is per store, random, and beside the file.** It lives in the sidecar
`analytics.duckdb.kdf` (a JSON record with a version, the KDF, the round count and the salt; written to a sibling, fsynced and moved into place, readable by its owner), under a lock, so two
threads opening a new store cannot leave a file under one key and a sidecar naming another. A store with no valid sidecar (an older build's unsalted key, or a lost one) is REMOVED, with its
log, and rebuilt, never opened or migrated; the store goes BEFORE the new sidecar is written, so a crash between the two leaves neither, which is a fresh start, where the other order leaves a
store under a salt nobody recorded. The sidecar is on the crypto-erase and uninstall lists: with it overwritten the key is not derivable even from the right passphrase; so is the engine's own log,
`analytics.duckdb.wal`, which an unclean end leaves beside the cache (the read found it unlisted: ciphertext under the same key, so no plaintext survived, but under an `OO_COLUMNAR_DIR` outside the data
directory the erase walks NAMES, and a file it does not name survives). **(3) The engine
quotes the statement it cannot parse, so the key must not be in it.** MEASURED, with DuckDB 1.4.4 and 1.5.5: an `ATTACH` whose path held an apostrophe ended its literal early, and the
parse error quoted a window of the statement around the failure, which for a short path held the FIRST 16 TO 24 CHARACTERS of the key written after it (none of it for a long path). A scrub
matches the whole secret and cannot find half of one, so the answer is not a better scrub: the key is a bound parameter, `ATTACH '<path>' AS oo (ENCRYPTION_KEY ?)`, and the path's quotes are
doubled. Checked with a real encrypted attach on 1.5.5 (the software backend, test-only): a store made under a bound key opens under the same key as a literal and under no other, and a
literal `?` is a different key; on 1.4.4 the parameter parses and reaches the same refusal the literal does (it cannot encrypt without the bundled backend). The scrub stays as the net: the three
failure records of the module (`connect`, `encryption_gate`, `refresh_persisted_read_model`) go through `log_failure` (`connect` names the passphrase AND the derived key, the gate the probe's key it
made and the refresh the passphrase; each also takes out every passphrase the process holds), and the walk of `test_p0_validation.py` holds the module (`encryption_key` is now a name it reads as a
secret). The gate attaches the same way the store does, so that what it proves is the statement the store uses; its key is a random one made for the call, and it takes no passphrase. **What a BOUND
key escapes, measured** (DuckDB 1.5.5, its software backend; the `columnar` lane measures it again on the version it installs): a lowercase-hex `str` is not quoted by the errors of a directory, a
file that is not a database or a store under another key; a `str` with a character outside ASCII or a backslash fails the engine's STRING-to-BLOB cast, and that error quotes the WHOLE key as it is;
a `bytes` key is quoted by the Binder error in hexadecimal escapes and an `int` in digits. So the derived key has to stay a lowercase-hex `str` (`_derive_key` returns nothing else, and a test pins
the shape), the failure's record takes the key out by name where the engine did quote it (a test makes the engine do it, on the version the lane installs), and the key is held nowhere else, not
beside the passphrase for the global nets, because no text those nets scrub can carry it. **(4) A guard reads the SINK, with an allow-list that is empty.** `tests/test_passphrase_hashing_guard.py`
walks every `.py` file under `src/` and `scripts/` (760)
and fails on a fast hash (`hashlib` other than `pbkdf2_hmac` and `scrypt`, `hmac.new`, `hmac.digest`, `hmac.HMAC`, the `update` of a hash object the scope made) whose arguments are, or were made
from, a name that says passphrase, password, passwd, passcode, pwd, pw or secret, with the taint followed through assignments, tuples, comprehensions, `with` and the walrus inside one function, and NOT
followed through a stretching call: what `pbkdf2_hmac` or `scrypt` makes from the passphrase is not the passphrase (a guess still costs the stretching), so a keyed HMAC of a stretched master key, the ruled
0.5 blob address, passes with no second ruling, while the passphrase named beside it is still flagged. Today it sees 113 fast hashes, none of which reaches one, and one stretching call that takes a secret
(the cache's). What it does not see is stated in its docstring: names, not values; a secret returned from a helper and hashed in another function; a container filled by a method, an alias of a constructor,
a hash object's `.copy()`, a `match` capture and `getpass.getpass()` hashed on the spot; another library; the pages. It reads NAMES, so a name that says secret, pw or pwd without being the passphrase is
flagged too (the repo's own Playwright handle was called `pw`, in two scripts, and was renamed `playwright`; the fix for any other is to rename, not to allow), and each file is read as bytes, because
Python runs a file saved with a UTF-8 byte order mark and `ast.parse` refuses the mark in a decoded text. **(5) The mutation run is where the guards were wrong.** Sixty-one mutants of the derivation, the
sidecar, the statement, the gate, the erase lists and the walker (twelve more for the fold of the read: the stretching rule, the failed open's drop, the three lists of the log and the lane, and four for the gate's record
and the echo tests: the gate back to `exc_info`, without the probe's key, the key bound as bytes, the failed open's record without the key; seventy-seven in all): seven of the first fifty-two survived, and each was a test that passed for a wrong reason: nothing pinned the order of the removal and the sidecar, the rebuild's second attach,
a key unset before the `try` (the handler would have raised out of `connect`: no test failed before the key existed), a keyword argument, a comprehension variable, a walrus (its case named the
passphrase directly, so the taint was never needed) and the file-count floor (the real tree has 760, so no test could fail it: the check is now a function with its own test). The nine added for
the statement, the gate's path and that check include one more survivor, the gate's keyless attach with an unescaped path, which the gate itself could not show: it treats ANY failure of that attach
as "the encrypted store rejected a keyless open", so a parse error would count as proof of encryption; a test now reads the statements instead. **(6) A CI lane
that asserts `con is not None` passes on the fallback.** `test_ci_encrypted_persisted_round_trip` could not tell the persisted store from the in-memory one, which also returns a connection; it now asks the
connection which catalog it is in, reopens, reads a canary row back, and looks for the sidecar and for ciphertext (its first version looked for the gate probe's sentinel, which is written into ANOTHER
file, so the check passed on a plaintext store: a check of the bytes needs text the file itself holds). A real-engine test with DuckDB's own software backend (`force_mbedtls_unsafe`, test-only, skipped
where the setting does not exist) runs the real statement, in a data directory with an apostrophe, in the `columnar` lane, the only one with DuckDB. **(7) A test file that every lane skips is not a test,
and a test whose set-up already causes the outcome it asserts passes for the wrong reason.** The lane ran a fixed list of files that did not name this one, so all 20 of its engine tests were skips in CI
until the read ran it without DuckDB (`36 passed, 20 skipped`): the lane names it now, and a test holds the lane's command to name it. And `assert not store.exists()` after a failed open held because a
store with no sidecar is removed BEFORE the attach is tried, whether or not the failure's handler drops the file; the sidecar is made first now, and a mutation of the handler's drop fails the test.
