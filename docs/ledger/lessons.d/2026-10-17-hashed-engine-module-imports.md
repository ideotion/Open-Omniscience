## 2026-10-17 — a module the index engine hashes must not import the ingest layer

PR #1432 changed `src/analytics/equivalence.py` (a hashed engine module) to read the keyword ring files through `seed_sources._load_safe_yaml`, imported lazily inside the function "so the module keeps no ingest import at load time". The lazy import only moved the cost: the first call still loaded the seeder's whole chain (`catalog/cctld`, `catalog/normalize`, `database/source_identity`, `ingest/__init__`, `ingest/seed_plan`, `ingest/seed_sources`, `ingest/ssrf_guard`, `ingest/urllib3_log`, `monitoring/activity`: nine modules), and a full index pass reads the rings, so `tests/test_index_engine_stamp.py::test_every_module_a_pass_loads_is_hashed_or_triaged` failed on main.

What it cost: main red after the merge. It was not seen before the merge for two reasons, both mine. The tests I chose to run for the change were the ones named after the file (ring loader, ledger, rollup) and did not include the closure test, which lives in a file named for the engine stamp, not for `equivalence`; and the PR was merged before its full suite finished.

The rules it gives:
1. Before changing any file in `ENGINE_MODULES` run `tests/test_index_engine_stamp.py` (it is the only test that sees the closure), whatever else the change is about.
2. A hashed module's imports are part of the engine. If it needs something from the ingest layer, move that something into a module with no project imports and hash that module (`src/utils/safe_yaml.py`, which holds the safe YAML loader class choice), rather than exempting the chain: every exemption needs a reason that is true, and "the YAML loader decides how the ring file parses" is not an exemption reason.
3. A lazy import is not a way to keep a dependency out of a closure measured by running the code.

Follow-up PR: the fix (`src/utils/safe_yaml.py`, hashed in `ENGINE_MODULES`). Hashing the new module changes the engine identity for everyone, as any edit to a hashed file does; it is the same change `equivalence.py` itself already made.
