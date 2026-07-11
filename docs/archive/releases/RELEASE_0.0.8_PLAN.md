# Release plan — 0.0.8 ("trustworthy MVP, hardened")

> Execution plan for the **Now** horizon of [ROADMAP.md](../archive/roadmaps/RICE_BACKLOG_pre-0.2.md), written at the close of
> the v0.0.7 audit (PR #56).
>
> **STATUS: EXECUTED — all nine work packages delivered** (PRs #59, #60, #61 on branch
> `0.08`), with one honest re-scope per WP noted in the commits: WP8's producer set was
> swapped to the three recipes whose data already flows, and WP7's "<50 then blocking"
> became a CI ratchet (mypy 303 → 128; the count can never rise). The audit findings
> register closed at **29/29 FIXED**. Release verification (re-run at cycle close, fresh
> venv): install clean, 225 routes boot, `/api/health` reports 0.0.8, full suite
> **858 passed / 6 skipped**, core-only **754 / 6**, bandit **0**, pip-audit **clean**,
> benchmarks within budget (recency p50 1.32 ms on the index; near-dup linear ~5 ms/doc).
>
> *(Original plan below, kept verbatim for the record. It said: execute after the audit PR
> merges, on a*
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

## WP8 — RM-20 phase 1: investigation recipes on Home cards (M)

**Motivation:** the ten space-time scenarios (`docs/FUTURE_DEVELOPMENTS.md`) mapped onto the
existing briefing engine (`USE_CASES.md` §"From scenarios to Home-screen cards"). Maintainer
decision: committed for 0.0.8.

**Changes**
- `Card` gains an optional `recipe: dict | None` — `{"view": "<recipe-id>", "params": {...}}`
  (e.g. `{"view": "silent-disaster", "params": {"lat": .., "lon": .., "window": [t0, t1],
  "event_id": ..}}`). The schema guard (`CardSchemaError`) is extended: a recipe may carry
  *parameters*, never embedded conclusions or composite scores.
- First **3 producers** (prove the pattern before scaling to all ten — pick the three whose
  data already flows): *promises due* (mentioned future dates arriving), *silent disasters*
  (hazards event × zero corpus coverage), *law takes effect* (tracked effective-dates).
  Each follows the house contract: one measured signal + method + caveat + evidence + n.
- Home UI: cards with a recipe render an **"Open investigation ↗"** button with
  `target="_blank"` → `/investigate?...` (WP9), so the main UI stays put and several
  investigations can run in parallel tabs — explicitly per the maintainer's design intent.
- Settings → a **Recipes** card: which producers are active (all default-on, individually
  off-switchable, like the existing card types).

**Acceptance:** producer unit tests (condition fires / doesn't fire on seeded data); schema
guard test (a recipe carrying a "score" raises); cards appear and dismiss like existing ones;
suite green.

## WP9 — RM-20 phase 2: the `/investigate` dashboard (L)

**Motivation:** a deep-link into a generic tab loses the card's narrative. Each recipe opens
a dedicated, card-adjusted dashboard — modern, user-oriented, with everything related
auto-assembled and honest "go deeper" suggestions. **Opens in a new browser tab/window** so
the main UI keeps working (multi-tab is already the app's model: `/` and `/desk` share one
server and one corpus; `/investigate` is the third page in that family).

**Architecture (follows the house pattern exactly)**
- One new route `GET /investigate` serving one new static page
  (`src/static/investigate.html`) — same dependency-free rules as Console/Desk: no CDN, no
  framework, shared design tokens (themes/accent/density from Settings → Appearance apply).
- The page reads `?view=<recipe-id>&<params>` and composes **panels**, each of which is a
  view over an *existing* API (nothing new server-side beyond the recipe manifest):
  `timemap` window · article list (search API, pre-filtered) · timeline density strip ·
  near-dup cluster view · wiki revision burst · law diff · price chart + correlation ·
  custody/evidence actions.
- A small client-side **recipe manifest** declares each dashboard:
  `{panels: [{type, api, params}...], suggestions: [...]}` — adding a recipe = adding a
  manifest entry + (usually) a producer, no new page.

**Per-recipe composition (the three from WP8):**
| Recipe | Auto-assembled panels | Suggestions strip |
|---|---|---|
| Promises due | the original article (reader) · the promised-date tag with snippet · search results for topic+place since the promise · timeline strip of coverage | "Search variants of the promise wording" · "Add follow-up set to briefing" · "Log original to custody" |
| Silent disaster | map window on the event cell · the hazard feed entry (source's severity, linked) · "0 matching articles" panel with the exact query used · nearest covered events for contrast | "Widen the window ±N days" · "Search neighbouring regions" · "Add the region's outlets from the catalog" (ties into RM-19 later) |
| Law takes effect | the law diff (baseline → current) · jurisdiction map window · coverage list for the law's keywords since the date · density before/after strip | "Correlate with related market series" · "Track sibling regulations" · "Export the coverage set" |

**The suggestions strip — rules (this is where honesty lives or dies):**
- A suggestion is always **an action the user could perform manually in the main UI** (a
  pre-filled search, a correlation run, an export, a briefing add) — never an automated
  conclusion. Clicking one *shows the parameters before running*.
- Analytics suggestions only ever invoke **real methods that exist** (the scipy endpoints,
  near-dup, correlation) and render with their method + caveat + n, like everywhere else.
- The dashboard is **read-only by default**; the only mutating actions are the explicit,
  labelled ones (briefing add, custody log, export) — the same loopback-CSRF-protected
  endpoints as the main UI.
- Every dashboard carries the parent card's caveat verbatim at the top. No panel may
  synthesize a composite verdict from the others.

**Acceptance:** `/investigate` renders each WP8 recipe from a URL alone (shareable/
re-openable — parameters fully in the query string, no hidden state); works in a second
browser tab while the main UI is in use; JS parses (the existing console-JS check); panel
APIs are the existing tested ones; a UI smoke test per recipe; suite green.

---

## Sequencing & release

1. WP2 (cadence) and WP3 (timing test) first — zero-risk, immediate value.
2. WP1 (DDG gate) — the release's headline trust improvement.
3. WP4–WP6 in any order.
4. **WP8 → WP9** (investigation recipes, then the `/investigate` dashboard) — the release's
   headline *user-facing* feature; WP9 starts only when WP8's three producers are green.
5. WP7 as the cycle's second, standalone PR.
6. Release checklist = the audit's release-readiness checklist
   (`docs/audit/05_DOCS_AND_RELEASE.md` §7) re-run, plus: benchmarks re-run
   (`scripts/benchmark_audit.py` — budgets in ROADMAP §4), `CHANGES.md` 0.0.8 section,
   version bump verified via `/api/health`.

**Risks:** WP7 is the only risky item (mitigated by chunked review + schema-drift assertions);
WP1 touches the UI (keep the toggle within the existing Safety card pattern); the scheduled CI
run can false-alarm on new advisories — that is its purpose, triage rather than mute.
