# Release plan — 0.0.8 ("trustworthy MVP, hardened")

> Execution plan for the **Now** horizon of [ROADMAP.md](ROADMAP.md), written at the close of
> the v0.0.7 audit (PR #56). **Status: PLANNED — execute after the audit PR merges**, on a
> fresh branch cut from the updated `0.07` (or the new `0.08` cycle branch per the project's
> branch ⇒ version convention; bump `pyproject.toml` to `0.0.8` in the cycle's first commit).
> Each work package is one reviewable commit-set with its own acceptance criteria; the audit's
> Evidence Protocol (red → fix → green, regression test per fix) continues to apply.

## Scope decision

Core batch: **WP1–WP6** (RM-03, RM-10, and the five quick deferred findings — all S/M effort).
**WP7 (MAINT-03, the `Mapped[]` ORM migration) is in-cycle but gated as its own PR** — it is the
only XL item, touches every model, and must not share a review unit with feature work.

---

## WP1 — RM-03: gate the external topic-discovery call (S)

**Motivation:** finding ETH-02. The one third-party call in the app (DuckDuckGo topic search)
is documented but not *gated*; for at-risk operators, documentation isn't enough.

**Changes**
- New persisted setting `discovery_external_enabled: bool = False` (alongside the existing
  safety settings in `src/safety/settings.py`, surfaced via `GET/PUT /api/safety/settings` —
  the established pattern for trust-sensitive toggles).
- `POST /api/sources/discover/topic` returns **403 with an honest body** ("external lookup
  disabled; enable in Settings → Safety") when the setting is off. RSS discovery
  (`/discover/rss`) is unaffected — it fetches operator-added sources via the EthicalFetcher.
- UI: Settings → Safety card with the exact text "This sends your topic query to DuckDuckGo
  (an external service)" + the toggle; the Discover button shows the disabled state.
- Docs: `SECURITY.md` exception paragraph updated from "don't use that button" to "off by
  default; opt in".

**Acceptance:** endpoint test — 403 when disabled (default), works when enabled (mocked
`requests.post`); no other endpoint behavior changes; suite green.

## WP2 — RM-10: scheduled security-audit cadence (S)

**Motivation:** the blocking bandit/pip-audit gates (added in the audit) only run on push; a
CVE published during a quiet week stays invisible.

**Changes:** add to `.github/workflows/ci.yml`:
```yaml
on:
  schedule:
    - cron: "0 6 * * 1"   # Mondays 06:00 UTC
```
plus a lightweight `audit-only` job (checkout → install core → `bandit -r src/ -ll` →
`pip-audit`) that runs on `schedule` only, so the weekly run doesn't burn full-suite minutes.

**Acceptance:** YAML parses; first scheduled run appears in Actions; failure notifies via
normal GitHub mechanisms. No external calls beyond PyPI advisories DB.

## WP3 — TEST-04: politeness-delay regression test (S)

**Motivation:** the per-host rate limit is the only §0.5 mechanism without a timing assertion
(tests set `min_interval_s=0`).

**Changes:** in `tests/test_fetcher_limits.py`, a fake-clock test: inject `_sleep`/`_now`
doubles, fetch the same host twice, assert the recorded sleep equals
`max(min_interval_s, robots crawl-delay)`; a second case where crawl-delay > min_interval.

**Acceptance:** test fails if the rate-limit calculation or its invocation is removed.

## WP4 — TEST-05: endpoint tests for the uncovered routers (M)

**Motivation:** keyword_management (8 routes), reporting (2), framing (1) have no dedicated
tests; LLM endpoints are tested only at client level.

**Changes:** new `tests/test_keyword_management_api.py`, `tests/test_reporting_api.py`,
`tests/test_framing_api.py`, `tests/test_llm_api.py` — FastAPI TestClient, seeded in-memory
DB per existing conventions; LLM tests inject a fake `OllamaClient` (dependency pattern
already used in `test_api_ingestion.py`). Cover the happy path + one failure path per route
family (404s, validation 4xx, LLM-unavailable 503).

**Acceptance:** every router in `src/api/` has ≥1 dedicated test module; suite green on both
install profiles (analysis modules skip on core).

## WP5 — BUG-05 remainder: narrow the discovery excepts (S)

**Motivation:** audit deferral — broad `except Exception` in `duckduckgo.py` helpers.

**Changes:** narrow the URL-helper fallbacks to `(ValueError, UnicodeError)` etc.; keep the
outer last-resort handlers but log at warning with context. No behavior change on valid input.

**Acceptance:** existing discovery tests green; one new test that a malformed URL yields a
logged skip, not silence.

## WP6 — MAINT-04: `print()` → logger (S/M)

**Motivation:** ~50 live `print()` calls bypass log levels (cache.py 17, duckduckgo.py 11,
crypto/provenance.py 10, others).

**Changes:** mechanical conversion to module loggers (`logging.getLogger(__name__)`),
preserving message text; debug-level for chatty paths.

**Acceptance:** `grep -rn "^\s*print(" src/ --include='*.py'` returns 0 (excluding scripts/);
suite green.

## WP7 — MAINT-03: `Mapped[]` ORM migration (XL, **own PR**, gated)

**Motivation:** ~103 of ~300 mypy errors are the legacy-`Column` typing false positive; this
migration is the prerequisite for a blocking mypy CI gate (RM-01).

**Approach (one PR, reviewed in model-group chunks):**
1. Convert `models.py` table-by-table to `Mapped[T]` + `mapped_column(...)` — *type-level
   only*; assert zero schema drift with `alembic check` + a before/after
   `CREATE TABLE` dump diff at each chunk.
2. Track the mypy error count per chunk (must fall monotonically; target < 50 total).
3. Final commit: flip mypy from absent to **blocking** in CI (`mypy src/` in the test job).

**Acceptance:** `alembic check` clean; schema dump identical; full suite green on both
profiles; mypy < 50 errors and blocking in CI.

---

## Sequencing & release

1. WP2 (cadence) and WP3 (timing test) first — zero-risk, immediate value.
2. WP1 (DDG gate) — the release's headline trust improvement.
3. WP4–WP6 in any order.
4. WP7 as the cycle's second, standalone PR.
5. Release checklist = the audit's release-readiness checklist
   (`docs/audit/05_DOCS_AND_RELEASE.md` §7) re-run, plus: benchmarks re-run
   (`scripts/benchmark_audit.py` — budgets in ROADMAP §4), `CHANGES.md` 0.0.8 section,
   version bump verified via `/api/health`.

**Risks:** WP7 is the only risky item (mitigated by chunked review + schema-drift assertions);
WP1 touches the UI (keep the toggle within the existing Safety card pattern); the scheduled CI
run can false-alarm on new advisories — that is its purpose, triage rather than mute.
