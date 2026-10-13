## 2026-10-06 — wal-disk-pool/damaged-database-e2

- **2026-10-06 · wal-disk-pool/damaged-database-e2 (WAL / disk thread, slice E2 of the damaged-database plan).**
After an unexpected stop the app now reads each table of the corpus, Wikipedia and law files once, with `PRAGMA quick_check(<table>)` on its own read-only connection, before collection writes to the file again
(`src/database/verify.py`). It runs when the previous session's end was recorded as unclean (an unknown end is not a reason) or an earlier check was left unfinished (at most three starts in a row), armed as the start-up upkeep's first statement
(before its slow steps) and run as the boot sequence's first step, and recorded as owed from the arming (a boot that stays locked records it too) so a session closed before it began does not cancel it; from the arming until it ends collection, the Wikipedia lane and off-peak maintenance wait (`admit()` answers `"verifying"`, phase `paused-verifying`),
"Resume anyway" is refused with a sentence, and the task manager and the vitals panel show "table N of M" in 12 languages. A table is `damaged` only when the check reports a problem or the driver raises `SQLITE_CORRUPT`; busy, locked, I/O errors,
a wrong or missing passphrase and a stop are `unchecked`, never damage. A damaged table latches its file through the same door a corruption error uses (the scope is the search index only when every damaged table is the full-text index's). The record
`data/database-damage.json` gains a per-file `verification` block (verdict and seconds per table, the file's own page facts, the trigger, the attempts), carried by the diagnostics member and cut to the verdicts when the member must be small.
Not built: repair and salvage (E3), an operator skip. Lesson: `lessons.d/2026-10-06-a-check-that-holds-collection-must-always-end.md`.
