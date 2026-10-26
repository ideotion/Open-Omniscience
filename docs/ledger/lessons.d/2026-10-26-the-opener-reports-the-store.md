## 2026-10-26 — the opener reports which store it opened: a fallback that returns the same type as the success is a lie the caller cannot detect

**Found by the Opus reads of #1510 and #1515.** `columnar.connect` returned a DuckDB connection both for the persisted encrypted store and for the in-memory store it fell back to when the encryption gate failed or the persisted open raised, and `None` only when the engine was off. A caller that asked for the persisted store (`_refresh_persisted_build`) recorded whatever it got as the persisted store and the dispatcher reported it built; the in-memory build, in turn, read `None` ("engine off") as "built". The second one was reachable in the field: `serve_enabled()` did not honour `OO_COLUMNAR=0`, which `connect` does.

**Rules.**
1. When a function can fall back to a weaker variant of what was asked for, the RETURN says which one it got (`OpenedStore(con, kind, fallback_reason)`), reported by the code that made the choice. A caller must never have to infer it (no `:memory:` sniffing, no attribute probe): inference is what failed here, for years, because the two connections look the same.
2. The old function stays as a thin wrapper over the new one, so its other callers and every test stub are unchanged; only the caller that needs the truth moves.
3. A caller that did not get the store it asked for closes what it was handed and declines, with the reason as a CODE in the status (never the exception's text, the sink sweep's rule).
4. `None` in a return that also means "success" is a trap: give the "nothing was built" case its own record (here `engine-off`, a decline with no hold, because a setting is not a stop), and make the gate that decides whether to try honour the same switch as the code it gates (`serve_enabled()` and `OO_COLUMNAR=0`).
5. Read the callee before writing its behaviour in a comment (the first fix of this family named the wrong cause; see the early-return lesson).

**Limits, stated.** The persisted store is dormant in shipped code (blank httpfs pins), so the persisted half is read from code and exercised through patched gate, attach and opener; the engine-off half is the reachable one. `map_serve.serve_enabled` had the same gate gap and is fixed in the same change; its build already returned quietly on a `None` connection, so only the gate needed the switch.
