## 2026-10-15 — page check past 4 GiB, on the app's own side (R134 option A) (PR #1397)

`PRAGMA cipher_integrity_check` wraps at 2^32 bytes, so the verifier used to withhold every verdict on a main file longer than 4 GiB (`PAGE_PASS_LIMIT_BYTES`, the old `_OVER_LIMIT_REASON`). New `src/database/page_auth.py` checks the
SQLCipher 4 page tags itself (HMAC-SHA512 of each page minus its tag, plus the page number, under a key derived once from the passphrase holder `connect._apply_key` reads) in 4 MiB chunks, wired into `verify._tag_pass` for files over
the limit; the pragma path below 2^32 is unchanged.

- **Calibration, so it cannot invent damage:** page 1 failing, or every one of pages 2–9 failing beside a good page 1, is `unchecked` ("the check does not match this file"), never `damaged`; an unreadable first page, a missing passphrase,
  a stop and any unread page are `unchecked` with a reason; only a page that was read and whose tag does not hold is `damaged`, and R100's second read still confirms it before the verdict stands. Non-default cipher settings are refused
  in fixed words before the file is read.
- **The lock-byte page:** SQLite never writes the page holding byte 2^30 (65,537 at 16 KiB), so it is zeros and fails the tag; the engine skips it and so does the check (counted as `lock_byte_page`). Found only on a real 4.37 GB store.
- **Key hygiene:** derived key held in a bytearray, passphrase reference dropped at once, every secret buffer wiped in a `finally` on every path; errors are class + errno name only; tests plant a marker passphrase and the derived key bytes
  and assert neither reaches logs, `app_errors`, the storage-events journal, the Diagnostics zip or an exception text.
- **Measured on a healthy 4,375,658,496-byte store:** the pragma gives 4,925 false rows in 10.9 s; the own check is `ok` over 267,068 pages in 8.4–8.7 s warm (17.2 s cold), 53 MB peak RSS; 8 inverted bytes (65,536–65,538, 262,144–262,146,
  267,000, 267,069) → 7 named (one past the end), second read agreed, 16.4 s.
- **Tests:** `tests/test_page_auth.py` (engine parity, calibration, unread vs failing, stop, boundary via a virtual file and a real sparse file, lock-byte page, zeroing spy, AST guard on imports/calls); verify-side mapping and sink tests in
  `tests/test_database_verify_pages.py`; 38 mutants (28 + 10), all killed. Also carried: two positional-only-default plants in `tests/test_runs_log_sinks.py`.
