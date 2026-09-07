# Prompt 20 — Structural debt, dependencies and test hygiene

> **Scope:** module structure, the dependency set, the parked quality backlog, CI lanes.
> **Gated on:** J1 (the diagnostics split), J2 (`structlog`), J3 (SQLite-only), L8.
> **Sequencing:** independent, and a good candidate for a session that has to interleave with others —
> almost every slice is behaviour-neutral.

## 0. Working mode

Read `_WORKING_MODE.md`, then `PARKED.md` and `docs/ROADMAP.md` §4.

`PARKED.md` carries an internal contradiction and two dead paths, so read it as a claim like everything else:
it discusses a mypy ratchet that no longer exists (the gate is blocking at zero), it names
`src/discovery/duckduckgo.py` which is now `src/services/duckduckgo.py`, it points at
`docs/audit/raw/radon_cc.txt` which was archived, and its `view_article` complexity figure is stale (that
function is roughly 611 lines now, not 197). MAINT-03 is done — 448 `Mapped[]` uses, zero legacy. MAINT-04's
`print(` migration set is **empty**: all 84 remaining are blessed by the AST guard.

## 1. Slices

### S1 — J1: split `src/api/diagnostics.py`

6,200 lines and 126 routes. The split is behaviour-neutral and the **all-diagnostics completeness ratchet is
what proves nothing was lost** — every GET route on the router must be a bundle member or a documented
exemption, so the ratchet is both the safety net and the acceptance test. Keep the exemption reasons attached
to the routes they exempt, not to the package.

### S2 — S-2: the import cycles

Six modules import `src.api.main` — diagnostics, llm, ai, insights, unlock, scale_bench.
`tests/test_import_graph.py` holds `TRUE_CYCLE_CEILING = 0`, so these survive as annotated lazy imports.
Four unannotated cycle-breaking lazy imports remain in `src/ingest/__init__.py`, `src/safety/settings.py` and
`src/backup/volumes.py`. **PRH-26:** `src/api/main.py` still holds inline endpoints that belong in the `core`
router, and `observability.py` (the Prometheus globals plus middleware order) was scoped for extraction and
never extracted — that extraction is also what would fix the duplicate-registration collision that makes
several test files fail when they share a process.

### S3 — J2: `structlog`

Declared in `pyproject.toml` with **zero** call sites; the codebase uses stdlib `logging` at roughly 612
sites. Adopt or drop — dropping is a dependency change, so re-verify both venv profiles and the lockfile
resolve lane.

### S4 — S-4: the ad-hoc slicer budget

`_ADHOC_SLICER_BUDGET = 232` with zero slack. Lower it by routing hand-rolled source slices through
`tests/js_source_helper.py`, which carries brace-, bracket-, array- and object-literal matching with each
failure mode pinned. **Prefer being stopped by this ratchet over lowering it** — that is the recorded rule,
and it earned itself when its own author reintroduced the class three days after building it.

While here, the class this ratchet exists for is worth one pass: a 14-agent sweep found 41 guards that could
not fail for the reason they were named, in five shapes — the tautology, the wrong operand, the
comment-satisfied positive, the non-unique needle and the mis-slice. Roughly 1,063 individual source
assertions have never been audited beyond that sweep's 41.

### S5 — The parked quality backlog

- **PRH-03:** `_clean_url` (`src/services/duckduckgo.py`) strips the query string **before** validation, so
  every real DuckDuckGo `/l/?uddg=<target>` redirect result loses its target and is discarded as scheme-less.
  The existing test asserts only `isinstance(results, list)`, which is why it survived. This is a behaviour
  change — it makes the one sanctioned external channel work — so it wants its own before/after.
- **PRH-04:** `scripts/setup_llm.py::start_ollama` calls a method on a module that no longer exists. Delete
  or repair.
- **NET-02:** `safe_href` in `src/utils/security.py` still holds a broad `except` in `_clean_url`'s chain. It
  is the app-wide sanitizer, so it is its own reviewed slice.
- **STR-05:** the `view_article` and `build_families` refactors, and the rest of the cc≥C list.
- **PRH-27:** `tests/test_installer.py` leaves an `oo.env` behind in the checkout when it runs.

### S6 — Test hygiene: the order-dependent pollution family

Long-standing and never fixed: running `test_a2_job_endpoints.py` before
`test_diagnostics.py::test_doctor_healthy_returns_zero` in a subset makes `run_doctor()` fail. It reproduces
on a clean base and is green in full-suite order, so per-PR CI and the full run never hit it. The first
suspect in this family is a lifespan-driven `TestClient` fixture mutating process-global state — `with
TestClient(app)` runs the app's **real** startup and shutdown (engine init and dispose, the airplane socket
guard, source seeding), all process-global.

Siblings: `test_export_sources_to_yaml` asserting against the legacy shared `database.models.engine`;
`test_get_source_statistics`; the prometheus duplicate-registration collisions (see S2); the port-8001
ordering collision between two vLLM test files.

### S7 — J3 and the CI lanes

**J3:** document SQLite-only and remove the implication of dual Postgres support, or commit to parity
(PARKED ARCH-06). **PRH-29:** the Windows `pytest` lane hangs — 3 h 21 m to failure, about 6 h to
cancellation — and deserves a bisect against the suite as its own task. The advisory ruff lane sits in the
high hundreds; decide whether it converges or stays advisory, and record which.

## 2. Scope fence

Behaviour-neutral means behaviour-neutral: if a refactor changes an output, it is not this prompt's. Do not
lower a ratchet to make a change fit. Do not delete a test that fails for an environmental reason without
first making it runnable — a name-diff is evidence only about tests that actually execute.
