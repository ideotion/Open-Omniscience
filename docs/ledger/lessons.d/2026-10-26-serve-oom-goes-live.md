## 2026-10-26 — a query layer that swallows every engine error to "empty" must still let the engine's memory wall reach the caller as "ask the live scan"

**What was found.** `columnar.windowed_top_terms_raw` and `windowed_term_counts` caught every engine error, counted a serve fallback and returned `[]` / `{}`. `rollup_serve.windowed_rows` / `windowed_counts` passed that through unless the instance was left unusable (`_drop_if_unusable`, the engine's fatal). `queries.top_terms` and `trending` go live only on `None`. So a plain `OutOfMemoryException` inside the served query (the engine's memory wall, the instance still usable) left an EMPTY most-mentioned list or an empty trending answer, not the live answer. Found by a reviewer reading the merged #1467, which wrongly said the serve "fell back to the live scan (counted as a top-terms fallback)": the counter counted a fallback that never happened. The counter name and the behaviour had drifted apart, and nothing tested the pair.

**What it cost.** Nothing measured in production; at the 1,004 MB tier an out-of-memory answer from the served query showed as "no terms" rather than as slow-but-right.

**Rules it gives.**
1. Where a layer turns an engine error into an empty answer, ask which errors are really "nothing here" and which are "the engine could not answer". The memory wall is the second kind; ruled R194: it answers `None` (live), an ordinary error keeps the empty answer, and the counter still counts both by class.
2. The docstring says which: "empty on error, live only on OOM or a fatal instance". A counter called a *fallback* must be matched by a test that the caller actually fell back.
3. The test is end to end, not only on the unit: `tests/test_serve_out_of_memory_goes_live.py` runs `queries.top_terms` over a rollup whose served query raises the engine's out-of-memory class and asserts the live answer (red on the old code: 4 of 5 fail).

**Correction to the #1467 entry.** That lesson (2026-10-25-top-terms-pre-aggregate) says the serve fell back to the live scan; it answered an empty list until this change.

**Left alone, stated as a fact for the audit.** The persisted (encrypted on-disk) rollup path is dormant on shipped installs: `_persisted_serve_active()` needs a verified bundled httpfs binary, and the `duckdb-httpfs-extension` pin in `configs/external_artifacts.yml` ships blank. Not a defect; a 0.5.1 operator step.
