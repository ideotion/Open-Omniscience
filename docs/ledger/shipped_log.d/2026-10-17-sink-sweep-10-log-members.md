## 2026-10-17 — record files that leave the install or join the live logs are scrubbed whole-line first (sink sweep 10)

The audit of file-content readers (`rc-diagnostics/file-content-readers-audit-2026-10-16/AUDIT.md`, 143 reads of `src/`, read-only) found the first sinks outside exception text that put a log's CONTENT somewhere raw. The earlier sweeps scrubbed what an exception said; these copy what a file holds.

- **Single-file backup** (`src/backup/artifact.py` `_collect_members`): the five `logs/*.jsonl` members are now staged copies from `secret_scrub.scrubbed_copy`, hashed and zipped from the copy; the live log is not rewritten.
- **Volume backup** (`src/backup/stream_backup.py` `_collect_side_members`): the `logs` role goes through the same copy; every other role keeps `copy2`.
- **Restore merge** (`src/backup/merge.py` `merge_side_files`): a restored backup's log lines are scrubbed whole before they join the live log (a backup an older build made can hold a key).
- **Failed qualification bundle** (`src/catalog/qualification_merge.py`): the sidecar's quoted reason was cut at 2,000 bytes and stripped before any scrub; it is now read up to a memory bound (1 MB, over it not quoted, said so), scrubbed whole, then stripped and cut.
- **Standalone session-forensics route** (`src/api/diagnostics/system.py`): the kernel-log and journal text it serves, JSON and text download, passes `scrubbed_value` / `scrubbed`; only the bundle member had a net.
- **`scrubbed_copy(src, dst)`** (`src/monitoring/secret_scrub.py`): whole line before anything is written, line endings kept, a line over 1 MB replaced by a marker that counts its bytes (never copied in part), an invalid byte becomes U+FFFD, a line it cannot check is withheld by `scrubbed`. A passphrase that holds a line break cannot match across two lines (stated limit).
- **Tests:** `tests/test_log_member_scrub.py` (9), each site mutation-checked red without its fix.
