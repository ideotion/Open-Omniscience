# Phase 2 — Quality audit: correctness, security, tests & standards

**Date:** 2026-06-09 · **Branch:** `claude/laughing-bohr-mzqflp` · **Register:** [findings.csv](findings.csv) · **Raw tool output:** [raw/](raw/)

> No code was changed in this phase. This is the findings register that Phases 3–5 burn down.
> Tool versions: ruff 0.15.16, mypy 2.1.0, bandit 1.9.4, pip-audit (latest), vulture (latest),
> radon 6.x, pytest 9.0.3 + coverage 7.x. All run in `.venv-audit` (Python 3.13.12). Every
> finding carries evidence; bugs carry reproduction.

---

## 1. Severity dashboard

29 findings (24 new in Phase 2 + ARCH-01/ARCH-06 promoted from Phase 1 because they are reliability
defects, not just architecture observations).

| category | Critical | High | Medium | Low | total |
|---|---|---|---|---|---|
| security | 0 | 0 | 1 (SEC-01) | 4 (SEC-02..05) | 5 |
| ethics-invariant | 0 | 1 (ETH-01) | 1 (ETH-02) | 0 | 2 |
| correctness | 0 | 1 (BUG-01) | 2 (BUG-03,05*) | 0 | 3 |
| reliability | 0 | 1 (ARCH-01) | 3 (BUG-02, ARCH-06, BUG-05) | 1 (BUG-04) | 5 |
| performance | 0 | 0 | 2 (PERF-01,02) | 0 | 2 |
| maintainability | 0 | 1 (MAINT-01) | 2 (MAINT-02,03) | 1 (MAINT-04) | 4 |
| test-gap | 0 | 1 (TEST-06) | 3 (TEST-01,02,03) | 2 (TEST-04,05) | 6 |
| docs | 0 | 0 | 2 (DOC-01,02) | 1 (DOC-03) | 3 |
| **total** | **0** | **6** | **15** | **8** | **29** |

**No Critical findings.** The app boots, the §0.5 invariants hold *in the primary fetch path*, there
is no RCE/SQLi/unsafe-deserialization, and no data-loss defect. This is a markedly healthier register
than the audit brief anticipated — consistent with Phase 0's finding that the quarantine cycle already
did much of this work. The serious items cluster around a **second, less-careful fetch path**
(discovery), **dead code that pollutes tests and SAST**, and **the optional-extra test contract**.

## 2. Automated sweep results

- **bandit** (`raw/bandit.txt`): only 3 issues, all benign or dead. SHA1 cache-key (SEC-03, not a
  security boundary), MD5 in the dead `ingestor` package (SEC-04), and a bind-all `0.0.0.0` *default*
  on an unused config field (SEC-05). No injection/SSRF/deserialization flagged. Manual review (§3)
  confirms no `eval`/`exec`/`pickle`/`yaml.load`/`shell=True`/`os.system` anywhere in `src/`.
- **pip-audit** (`raw/pip_audit.txt`): **zero CVEs in project dependencies.** The only 4 advisories
  are against `pip` itself (25.3 → 26.x), i.e. the toolchain, not a runtime dependency. Clean.
- **ruff** (`raw/ruff_check.txt`, `raw/ruff_stats.txt`): 1055 lint errors — dominated by 284 E402
  (import-not-at-top, largely from the `sys.path` test hacks and module-level guards), 234 F401
  unused-import, 150 UP006 + 107 UP035 (old typing syntax). 7 bare `except` (E722), 15 B904
  (raise-without-from). 259 files would reformat. CI runs ruff as `continue-on-error`. → MAINT-02.
- **mypy** (`raw/mypy.txt`): 317 errors in 55 files; at least one real boundary smell
  (`main.py:803` passes a `Column[int]` where `int` is expected). → MAINT-03.
- **vulture** (`raw/vulture.txt`): unused imports/vars concentrated in the dead packages (§MAINT-01)
  and the salvaged analysis modules. → folds into MAINT-01/02.
- **radon** (`raw/radon_cc.txt`, `raw/radon_mi.txt`): one E-grade function (`build_families` 31,
  `analytics/families.py:111`), one live D (`BaselineExtractor._entities` 30), ~18 C-grade; MI all A
  except `briefing/producers.py` (B). Localized, addressed in Phase 4.

## 3. Manual correctness review (hot paths)

**Crawler / ingestion — strong, with one gap.** The primary `EthicalFetcher` is genuinely careful
(verified in Phase 1 and re-read here): robots fail-closed, SSRF guard with per-redirect
re-validation, per-host rate limiting, 30s timeout, 10 MB body cap, 5-redirect cap, honest UA. **But
the discovery feature is a second fetch path that bypasses all of it** (ETH-01): `duckduckgo.py`
uses raw `requests.get/head` with no robots check, no SSRF guard, and only a global (not per-host)
2s delay. It fetches operator-added source URLs (so not arbitrary attacker input) but still violates
"ethical scraping by construction, not silently bypassable." Topic discovery additionally calls
DuckDuckGo (ETH-02) — opt-in and outside the default path, so local-first holds, but it is a cloud
call living in the app. **No retry/backoff** on the main path despite `max_retries` config and a
`tenacity` dependency (BUG-02).

**Dedup — solid.** Two stages (canonical-URL pre-check, SHA-256 content hash) backed by a real DB
`UNIQUE(hash)` constraint and an `IntegrityError` race backstop. Canonicalization strips tracking
params and normalizes scheme/host. Well-tested.

**Storage — solid.** Clean session discipline (`session_scope` context manager + `get_db` dependency,
no globals); WAL + foreign_keys + busy_timeout pragmas; FTS5 kept in sync by triggers. The one
swallow-all is `close_session` (BUG-04, cosmetic). No N+1 patterns spotted on the core list paths,
but list-endpoint latency at scale is unverified (PERF-02).

**API layer — good.** Pydantic request models, consistent error shapes, `/api/articles` paginated by
default (verified Phase 0). CORS is loopback-only (not wildcard); a CSRF middleware refuses
cross-origin state-changing requests by Origin/Referer check (`main.py:300`) and sets
CSP/nosniff/X-Frame-Options. No endpoint executes user-controlled strings; no string-built SQL
(SQLAlchemy ORM throughout; FTS uses a parameterized `text()` bind).

**LLM layer — good.** Graceful degradation verified (503 with honest detail when Ollama absent, no
crash); no auto-download in code; provenance stored. Model name is passed through without an
allowlist but this is local-only and low-risk; article text enters prompts unsanitized (inherent
LLM-injection surface, capped at 6000 chars) — noted, not a finding at this severity.

**Error handling.** 7 bare `except` (all in `scripts/`, one analyzer), a handful of
`except Exception: pass` in `src/` — the load-bearing ones (`session.py:127`, `duckduckgo.py:232/351`)
are captured as BUG-04/BUG-05. The custody and config fallbacks use deliberate, commented
`# noqa: BLE001` swallows that are defensible (never let optional config block custody).

## 4. Invariant violations (§0.5)

| Invariant | Status | Evidence |
|---|---|---|
| Local-first / no cloud in default path | **HOLD** (with caveat) | Default ingest/scheduler path makes zero external calls; the only cloud call is opt-in topic discovery (ETH-02) and Swagger CDN on `/docs` |
| Ethical scraping not silently bypassable | **PARTIAL VIOLATION** | Primary path is exemplary, but discovery bypasses robots/SSRF/per-host limiting (**ETH-01, High**) |
| robots.txt on by default, fail-closed | **HOLD** (primary path) | `src/ingest/__init__.py:303-345` verified; violated only on the discovery path (ETH-01) |
| Per-domain rate limiting | **HOLD** (primary) / **PARTIAL** (discovery uses global delay) | `__init__.py:347-362` vs `duckduckgo.py:101` |
| Honest UA, no operator leak | **HOLD** | `OpenOmniscienceBot/<v> (+repo; ethical research crawler)`; discovery uses a `Mozilla/5.0 (compatible; OpenOmniscience…)` UA — honest about being the tool |
| Auditability (ingest/transform/delete logged) | **WEAK** | Real-time activity monitor + *optional* custody log; no persistent structured ingest-audit trail when custody logging is off (noted §3, carried) |
| Provenance & integrity | **HOLD** | url/canonical/hash/fetch-time stored; LLM results carry model+prompt_version |
| Deduplication | **HOLD** | invoked in pipeline, DB-enforced |
| Config-driven design | **WEAK** | half-dead settings.yaml + stale .env.example (DOC-01/02) |
| FOSS-only, no telemetry | **HOLD** | GPLv3 deps; no analytics; pip-audit clean |
| Operator privacy | **HOLD** | no operator-identifying leakage found |

## 5. Top 10 must-fix issues

1. **ETH-01 (High)** — discovery fetch path bypasses robots.txt + SSRF guard + per-host rate limiting. The headline finding: a real, if narrow, breach of the product's defining invariant.
2. **MAINT-01 (High)** — ~3,280 LOC of dead packages inside `src/` (`ingestor`, `custom_types`, `compliance`, `audit`, `reports`); 0% coverage, SAST noise, contributor confusion.
3. **BUG-01 (High)** — two tests validate the dead `ingestor.url_utils` via `sys.path` hack instead of the live `src/utils/url_utils`; dedup/canonicalization regressions in live code can pass CI.
4. **TEST-06 (High)** — suite is red on a core-only install (analysis-extra tests fail instead of skipping); the "extras are optional" contract is false.
5. **ARCH-01 (High)** — CI push-trigger excludes the default branch `0.07`; direct pushes ship unchecked.
6. **SEC-01 (Medium)** — `.env.example` dangerous defaults (`0.0.0.0` binds, `OLLAMA_ORIGINS=*`) contradict the loopback-only posture.
7. **BUG-02 (Medium)** — no retry/backoff on the main fetch path despite `max_retries` config + `tenacity` dependency; transient failures silently drop articles.
8. **ARCH-06 (Medium)** — Postgres is untested scaffolding while search is SQLite-FTS5-only; docs imply dual support.
9. **TEST-01/02/03 (Medium)** — body-size cap, redirect cap, and DNS-rebinding are implemented but untested; the last is also a residual TOCTOU SSRF gap.
10. **DOC-01/BUG-03 (Medium)** — `.env.example` omits all 21 real `OO_*` vars; version reported three ways (0.02/0.03/0.0.7).

## 6. Test-suite audit

- **Coverage: 68.3% overall** (10,241 / 14,443 statements; `raw/coverage.json`). With the dead
  packages excluded the live-code figure is meaningfully higher — the biggest 0% blocks are exactly
  the dead modules (`ingestor/*`, `custom_types`, `database/async_db` 380 stmts unused-future-Postgres,
  `scraper/source_monitor` — though the latter *is* imported by the dead `ingestor/pipeline`).
- **Quality is good, not padded** (independent read): substantive assertions, no mock-the-unit-under-test
  anti-patterns, hermetic isolation via the `conftest.py` `OO_DATA_DIR` tempdir, no live network, no
  ordering dependence. The "813 passing tests" claim is real and the tests largely exercise real
  behavior — a genuine strength.
- **Gaps** become TEST-01..06: untested body-size/redirect/DNS-rebinding edges on the fetcher (the
  design is right; the edges are unproven), the core-install red suite (TEST-06, the only High), and
  endpoint-coverage holes in keyword_management/reporting/framing/llm.

## 7. Standards & consistency

README promises "PEP 8, type hints, docstrings, atomic commits." Reality: docstrings are pervasive and
good; type hints are widespread but 317 mypy errors show they're not checked in CI; PEP 8 is ~1055 ruff
violations from clean and ruff is advisory-only in CI. Logging is mostly the configured logger/structlog,
but 91 `print()` calls remain (mostly in dead or discovery code). The cross-pillar style divergence the
brief warned about is gone with the pillars. Net: the *intent* is met, the *enforcement* is not — which
is Phase 4's job.

## 8. Remediation sequencing (recommended Phase 3 batch)

Phase 3 (stabilize, correctness/safety/invariants) should take, in order:

1. **ETH-01** (+ BUG-05) — route discovery through the EthicalFetcher (or add robots+SSRF to it). The one invariant violation; do it first, with a regression test proving robots/SSRF now apply.
2. **BUG-01 → MAINT-01** — repoint the two legacy tests at `src/utils/url_utils`, then `git rm` the dead packages (depends_on chain in the register). This also clears SEC-04 and much of MAINT-04.
3. **TEST-06** — make analysis tests skip without the extra (importorskip/marker), so a core install is green.
4. **SEC-01/02/05** — tighten `.env.example` and Config to safe-by-default (loopback, drop fake auth secrets).
5. **ARCH-01** — fix the CI push trigger.
6. **BUG-02, BUG-03, BUG-04** — retry/backoff decision, single-source the version, log-before-swallow.
7. **TEST-01/02/03** — add the fetcher-edge regression tests (each closes a test-gap and hardens an invariant; TEST-03 may also motivate IP-pinning to close the TOCTOU).

`depends_on` edges to respect: BUG-01 → MAINT-01; SEC-04 → MAINT-01; BUG-05 → ETH-01; MAINT-04 → MAINT-01.
Performance items (PERF-01/02), formatting/typing (MAINT-02/03), the Postgres decision (ARCH-06), and
doc truth-up (DOC-01/02/03) are deliberately deferred to Phases 4–5.
