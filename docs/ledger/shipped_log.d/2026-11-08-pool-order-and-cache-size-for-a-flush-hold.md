## 2026-11-08 — the pool hands out the last-returned connection, the gate counts its holders' CPU, and the machine record names the SQLCipher build (R458, R470; PR #@@PR@@)

**What was found.** Long write-gate holds on the Windows run (36 to 68 s, 83 to 97 percent thread CPU) had no explained cause. A scratch measurement on a Linux VM showed the cache size and the auto-checkpoint threshold are not the lever and the pool's first-in-first-out order costs every flush a cold cache; the one lever with a plausible large effect on Windows, SQLCipher memory security, had never been read from the running build.

**What changed.** Three small, disjoint commits. `src/database/writer.py`: `stats()["total_hold_cpu_s"]`, the holder threads' CPU summed over every finished hold, `None` where the OS cannot give it. `src/database/session.py`: `pool_use_lifo=True`. `src/monitoring/machine_record.py`: `versions.sqlcipher_build` with `provider`, `provider_version` and `memory_security`, each a string or `{"unavailable": <exception class>}`, read through a keyed throwaway in-memory database (random raw key kept nowhere, never the corpus passphrase), failing closed; +154 bytes in the bundle, at most +416 (R470 exception, R473).

**Pinned by** `tests/test_write_gate_hold_cpu.py` (11), `tests/test_pool_lifo.py` (4), `tests/test_machine_record_sqlcipher_build.py` (18; 12 mutants killed, including an empty pragma answer read as a value).

**Stated limits.** Not measured on Windows. `soak_window`'s copy of the gate figures does not carry `total_hold_cpu_s`. Release-notes lines (R319): drafted in the diff list.
