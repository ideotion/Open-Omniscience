## 2026-10-15 — a check you re-implement must be run on a real file of the size it exists for: the lock-byte page only exists past 1 GiB (PR #1397)

**What was found.** The engine's `PRAGMA cipher_integrity_check` wraps its offset at 2^32 bytes, so on a main file longer than 4 GiB it reports a false failing row for every page from 262,145 (at 16 KiB) onward — 4,925 false rows on a
healthy 4,375,658,496-byte store, in 10.9 s. The verifier therefore withheld every verdict past that size (R100, "a measured verdict never gives way"). R134 ruled option A: check the page tags on the app's own side. The check is
small — a SQLCipher 4 page is `[ciphertext][IV 16][HMAC-SHA512 tag 64]`, the tag is HMAC-SHA512 over the page minus the tag plus the 4-byte little-endian page number, page 1 starts at byte 16 because the first 16 bytes are the
salt — and a 4 KiB-page store of a few hundred pages matched the engine page for page. Every one of the tests passed. A real run on a 4.37 GB store then reported page 65,537 as damaged on a HEALTHY file. That page is the **lock-byte
page**: SQLite never writes the page that holds byte offset 2^30 (`sqlite3PendingByte`, 0x40000000; page `2^30 // page_size + 1` — 65,537 at 16 KiB, 262,145 at 4 KiB, 16,385 at 64 KiB), so it is all zeros, which FAILS the tag like any
zeroed page, and the engine skips it. A file shorter than 1 GiB has no such page, so no small-store test, mutant or parity check could have seen it. Only the real file did — and the page did the damage a check must never do: it
invented a finding on a healthy store. After the skip, the same real run was `ok` over 267,068 pages (the lock-byte page counted separately) in 8.4–8.7 s warm, 17.2 s cold, 53 MB peak RSS; with 8 bytes inverted at pages 65,536–65,538,
262,144–262,146, 267,000 and 267,069 it named 7 and not the eighth (65,537, the lock-byte page, which nothing judges), and the second read agreed.

**The rules.**
1. **When you re-implement a check, run the new one on a real file of the size the old one failed on, before the tests are trusted.** Parity with the engine on small stores proved the formula; it could not prove the file layout,
   because the layout has features that appear only at scale. Here the feature was a page the format deliberately leaves empty. The cheap way to find it is the one thing the small tests cannot do: make the big file (a sparse
   file is not enough for a tag check — it must hold real pages) and compare page for page with what the engine says on the part of the file the engine still gets right.
2. **A check that can say "damaged" must be unable to invent a finding.** The design that came out of this makes three things `unchecked` with a stated reason, never `damaged`: a calibration mismatch (page 1 failing, or every one of
   pages 2–9 failing beside a good page 1 — the passphrase, the settings or the format are not what the check was measured on), an unreadable first page, and an unread page (a page the drive would not give is counted as unread, never
   as failing). `damaged` is reserved for a page that WAS read and whose tag does not hold, and R100's second read still has to agree before the verdict stands.
3. **Hold the derived key, never the passphrase, and wipe what you hold.** The tag key is derived once from the same holder the connection reads, the passphrase reference is dropped at once, the key lives in a `bytearray`, and
   every secret buffer (the UTF-8 passphrase bytes, the encryption key, the tag key) is overwritten in place in a `finally` — on success, mismatch, EIO, a stop, and a derivation that raises. A spy test fails if the wipe goes (a
   mutant that skips the wipe is killed by it), and the sink tests plant a marker passphrase and the derived key bytes and look for both in the logs, `app_errors`, the storage-events journal, the Diagnostics zip and every exception
   text on both the success and the failure paths. The limits are stated, not hidden: `hashlib.pbkdf2_hmac` returns immutable `bytes` and `bytearray(str, "utf-8")` makes a temporary copy that Python cannot wipe, and the OpenSSL HMAC
   state is released rather than wiped — all inside the threat model (a copied or seized file, never a compromised running session), and this path only verifies: no decryption, no recovery.
4. **A byte offset past 2^32 is testable without writing 4 GiB.** A virtual file object that fabricates pages on read (with a tag fabricator written independently of the code under test and validated against the engine) and a real
   sparse file (seek past the hole, write the pages that matter) both put a corrupted page past the boundary in milliseconds. Keep one of each: the first for the exact boundary arithmetic, the second for the real `open`/`seek`/`readinto` path.
5. **Cut source with `ast` line spans, not string anchors, in repo code and tests** (the 230-site `.index/.find/.split` budget in `tests/test_source_slicing_discipline.py` counts them).
