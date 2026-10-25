## 2026-10-17 — A `Retry-After` IS A PROMISE ABOUT THE OTHER SIDE'S TIME: SEND A MEASURED FIGURE OR NONE, NEVER THE CALLER'S OWN WAIT

(1) **The shape.** The 503 for a settings save refused during a restore's hold carried `Retry-After: 30`. The 30 is `KV_WRITE_WAIT_S`, how long the SAVE waits before it gives up; it says nothing about the restore. Two different refusals shared it: a thread that holds the single-writer gate is refused AT ONCE (the hold is mid-flight), and any other save is refused after waiting the full 30 s (the hold has already outlasted that).

(2) **What was measured** (`restore-hold-2026-10-17`, 7 runs per cell, plain and SQLCipher, 65 MB / 0.5 GB / 1 GB, one ext4 virtual disk, a writer thread beside half of them): the whole hold 0.04 to 1.95 s; `os.replace` frees the old file's blocks, about 0.5 s per GiB (0.26 / 0.62 / 0.90 s over an existing 1 GiB file, 5 runs). So a refusal at once gets `ceil(1 s + 0.5 s per GiB)`; the refusal after the full wait gets NO header, because what remains is unknown and nothing measured supports a number.

(3) **Inferred, said so.** Above 1 GiB the figure is the same rate extrapolated; nothing was measured on Windows (the replace waits up to 300 s for a handle another process holds), with a large `-wal`, or on a real store. The constants' comment and the PR body say so.

(4) **Check who reads it before spending effort on the number.** In `src/static/*.js` only the 429 path reads `Retry-After`; the settings-save 503 does not, so this changes nothing a user sees. A header that nothing reads is still a statement to any other client of the API, and a constant that is wrong is worse than none.

(5) **A read before any lock, and no call in a `finally`.** The size is read once at the start of the hold, inside the `try` and before any lock (the hold lock is bookkeeping only, never across file I/O), and cleared with the hold in the release block that already holds the lock. Real SIGALRM interrupts on `hold_writes(0)`: 0 of 128,429 left the hold set (see the stuck-lock lesson, section 5, for why the release makes no call before its take).
