# Audit report — Open Omniscience

**Target:** `/home/user/Open-Omniscience` @ `f275a76` (merged `0.06` line) · **Date:** 2026-06-08 ·
**Mode:** read-only / non-destructive · **Env:** `.venv`, Python 3.13.12, network OFF ·
**Proof trail:** [`AUDIT_LOG.md`](AUDIT_LOG.md) · **Machine-readable:** [`findings.json`](findings.json) / [`findings.csv`](findings.csv)

---

## 1. Executive summary

Open Omniscience is a **local-first, single-user, loopback-only** intelligence platform
for investigative journalism (Python 3.13 / FastAPI / SQLite, dependency-free vanilla
web UI): ethical scraping → unified provenance store → Boolean FTS search → keyword/entity
analytics, Wikipedia & world-law change-tracking, markets correlation, a Home "briefing"
of honest signal cards, source-integrity/anti-amplification, signed evidence + annotation
bundles. ~31.8k LOC in `src/`, ~11.7k in `tests/`, 236 Python modules.

**Overall health: good, and unusually honest for its domain.** Dynamic verification
passed: the **full test suite is green (691 passed, 6 skipped)** on Python 3.13, the
Alembic chain applies cleanly, the documented offline evidence verifier runs, and the
project's stated safety posture holds up under direct checks — **no hardcoded secrets in
live code, no leakage of DBs/keys into git history, the fabricated "detector" modules are
quarantined and imported by nothing live, and `datetime.utcnow()` is fully eliminated**
(F-008). The 0.06 intelligence-layer code is lint-clean and well-tested.

**What matters most (the short list):**
1. **One real correctness bug** in the newest code — the opt-in *novelty-weighting* in
   `story_prominence` mis-keys its representative and silently defaults some stories'
   novelty to 1.0 (F-002, Verified, **Medium**). Small, surgical fix.
2. **Test hygiene** — a dead legacy scraper whose tests reach the **real network**
   (F-003), and **non-hermetic app tests** that write to the working-tree `data/` dir and
   are order-sensitive (F-004). Both are git-ignored/contained, but they erode trust in
   the suite.
3. **Lint debt is large but advisory** (~530 ruff findings in legacy `src/`; CI lint is
   non-blocking) (F-001) — known and documented, but it lets regressions hide.

There are **no Critical or High findings**: no data-loss path, no security breach, no
false safety/security claim, and no major feature observed broken.

**Coverage statement.** I prioritised: dynamic verification (full suite, migration,
ruff), the freshly-authored 0.06 surface (treated as highest-risk), entry points,
security/ethics-sensitive paths, and documentation fidelity (in-app docs, runnable
examples, seed counts). I did **not**: read all 236 modules line-by-line; perform any
**live network** access (so the curated deep law URLs' liveness is unverified — F-010,
and the **ML-DSA post-quantum signing path** is unexercised — F-006); or run a UI
accessibility audit beyond static reading. Everything unverified is labelled as such.

---

## 2. Confidence and limitations

- **Network OFF (self-imposed default).** No live scraping or law-fetching was performed.
  Consequences: the `documents:` deep URLs in the law catalog are **unverified-live**
  (F-010); the legacy scraper's network behaviour is inferred from logs, not re-run.
- **Optional deps absent.** `pqcrypto` (ML-DSA) and `opentimestamps` are not installed →
  6 honest skips. The **hybrid/post-quantum signature path is unverified here** (F-006);
  annotation bundles were verified Ed25519-only.
- **Self-authored code.** The 0.06 layer was written by this same agent in prior sessions;
  per protocol it was treated as the *most* suspect surface, and one real bug (F-002) was
  reproduced rather than assumed away.
- **Static-only dimensions.** Usability/a11y of the HTML UI was assessed by reading, not
  by a screen-reader/contrast tool.

---

## 3. Findings by severity

> Full schema for each finding (observation vs interpretation, evidence, root cause,
> recommendation, effort/risk) is in `findings.json` / `findings.csv`. Summary below.

### Critical — none.
### High — none.

### Medium

**F-001 · Maintainability · Verified — ~530 ruff findings in `src/`; CI lint advisory.**
`ruff check src` → 213 E402, 177 F401, 72 UP035, 27 B033, 15 B904, … ; `ci.yml:30`
`continue-on-error: true`. The 0.06 trees pass clean. *Fix:* per-module burn-down +
`per-file-ignores` for intentional re-exports, then make CI lint blocking on cleaned trees.

**F-002 · Implementation correctness · Verified — novelty-weighting mis-keys the story representative.**
In `src/integrity/collapse.py` `story_prominence(weight_by_novelty=True)`, `novelty_of` is
keyed by `sorted(members, key=int)[0]` but read via `sorted(members)[0]`; for ids like
`{2,11}` these differ → lookup miss → novelty defaults to `1.0`, so an echo can rank as an
original. Default (off) path is unaffected. *Repro:* `sorted({'2','11'})[0]=='11'` vs
`key=int → '2'`. *Fix:* compute `rep = min(members, key=int)` once; add a regression test
with mismatching ids.

**F-004 · Maintainability · Verified — non-hermetic tests + shared DB engine.**
App-level tests write a seeded 610 KB DB, custody DB, keys and cache into the repo `data/`
dir; the engine is bound at import so per-test `OO_DATA_DIR` doesn't always re-bind →
order-dependence (seen as `test_law_api` count drift). Git-ignored, so no repo leakage.
*Fix:* autouse fixture forcing an isolated data dir; lazy/rebindable engine.

### Low

**F-003 · Reliability/Ethics · Verified — dead legacy scraper hits the network; robots fail-open.**
`src/scraper/scraper.py` is unused by the live app; `test_scraper_logging`/`test_rate_limiting`
call `scrape_all_sources()` unmocked → real DNS to `test-source-1/2.com` (errors.log);
`scraper.py:174` returns `True` when robots.txt is unreachable (fail-OPEN), contradicting
the project's fail-closed value — but only in dead code (live `src/ingest` is fail-closed).
*Fix:* quarantine it or mock the two tests.

**F-005 · Footprint · Inferred — duplicate near-dup passes per briefing refresh.**
`echo_chamber` and `lonely_signal` each recompute the near-dup clustering over the same
recent-news set (`producers.py:377,426`); `model_legislation` a third over law docs.
Bounded + cached → no user latency. *Fix:* memoise the corpus graph once per refresh.

**F-007 · Doc fidelity · Corroborated — README seed-count understates reality.**
`README.md:172` "~1,780 sources" predates folding spectrum (278) + markets + legal (51)
into the default seed. *Fix:* "~2,100+ across news, markets, spectrum and law/IP".

**F-009 · DX · Inferred — redundant `resolve_keyword()` calls** in `emotion_profile_card`
and neighbours (producers.py). Correct, just wasteful. *Fix:* bind once.

**F-010 · Doc fidelity · Hypothesis — deep law URLs not live-verified** (network off). A
moved URL makes a document untrackable; failure mode is **safe** (records a fetch error,
fabricates nothing). *Fix:* a one-off liveness check with network enabled; prefer ELI URLs.

### Info

**F-006 · Security/coverage · Verified — PQC hybrid path unexercised** (pqcrypto absent;
annotation bundles verified Ed25519-only). Not a defect (honest degradation by design).
*Fix:* a CI lane with the `[pqc]` extra.

**F-008 · Security · Verified — positive controls confirmed** (no secrets in src; runtime
artifacts git-ignored; quarantine not imported; all 12 in-app docs exist; evidence
verifier runs; `utcnow()`=0; migration clean; suite green). *Keep as CI invariants.*

---

## 4. Documentation-fidelity summary

Checked both directions; runnable examples executed where feasible (network-free).

| Documented claim / artifact | Reality | Status |
|---|---|---|
| 12 in-app docs registered in `_DOCS` (USER_MANUAL…LAW, BRIEFING, INTEGRITY, ANNOTATIONS) | all 12 files exist on disk | **matches** |
| `scripts/bootstrap.sh` (README one-line installer) | present | **matches** |
| `scripts/verify_evidence.py` (offline verifier, CHAIN_OF_CUSTODY) | exists, runs, prints usage | **matches** (ran) |
| `open-omniscience` console entry | `pyproject [scripts] = src.api.main:main` | **matches** |
| Alembic `upgrade head` (DATABASE/migration docs) | applies law migration cleanly | **matches** (ran) |
| README "auto-seeds ~1,780 sources" | default seed now also adds spectrum/markets/legal | **drifted** (F-007) |
| ANNOTATIONS/CHAIN_OF_CUSTODY "hybrid Ed25519 + ML-DSA" | ML-DSA path not run here (pqcrypto absent) | **unverified** (F-006) |
| "robots.txt fail-closed" (ETHICS/README, central value) | live path fail-closed; **legacy dead scraper fails OPEN** (scraper.py:174) | **drifted in dead code** (F-003) |
| Law catalog `documents:` deep URLs | not fetched (network off) | **unverified** (F-010) |
| BRIEFING/INTEGRITY/ANNOTATIONS/LAW cards & APIs | endpoints present; producers/tests exercise them | **matches** |

No documented feature was found *missing in code*; no user-facing 0.06 capability was
found *undocumented*.

---

## 5. Dimension scorecard

| Dimension | Verdict | Evidence |
|---|---|---|
| Intent & rationale | **Strong.** Unusually rich design docs (FUTURE_DEVELOPMENTS, ACTION_PLAN, per-feature guides); code matches stated intent. | docs read; producer/engine structure |
| Implementation correctness | **Good, 1 real bug.** Suite green; F-002 novelty mis-key (Verified). | pytest 691; F-002 repro |
| Stability & reliability | **Good in the live path; test isolation weak.** F-003 network-in-tests, F-004 non-hermetic. | errors.log; data/ artifacts |
| Security & privacy | **Strong for a local-first tool.** No secrets; ignores correct; PQC degrades honestly. | secret scan; git-ignore; F-006 |
| Documentation fidelity | **High, minor drift.** One stale count, two unverified claims (env-bound). | §4 table |
| Usability & DX | **Good.** Makefile, clear module boundaries in 0.06, runnable verifier; minor redundancy (F-009). | Makefile; producers read |
| User scenarios | **Covered.** Briefing→draft→export, integrity collapse, law tracking all have happy-path tests. | test_briefing/integrity/law |
| Accessibility & onboarding | **Good onboarding** (one-line installer, autoseed, offline). UI a11y not audited. | bootstrap; QUICKSTART |
| Affordability & footprint | **Local/offline by design.** Minor wasted compute (F-005); no paid APIs in the core path. | producers; no external paid calls in core |
| Ethics & dual-use | **Strong & self-aware.** Robots fail-closed (live), research-mirror/not-legal-advice discipline, no composite trust score (enforced in code), GDPR guardrail referenced. | ETHICS; law caveats; integrity profile |
| Values alignment & project health | **High coherence.** Honesty guards are in code + tests, not just prose; full CI + contribution docs. | card no-score guard; ci.yml |
| Maintainability & debt | **Mixed.** New code clean & tested; legacy lint debt large but advisory (F-001), legacy dead modules linger (F-003). | ruff histogram; grep |

---

## 6. Prioritized recommendations (sequenced)

1. **Fix F-002** (S/Low) — single-rep in `story_prominence` + regression test. *Correctness; smallest, highest-value.*
2. **Quick wins F-007, F-009** (S/Low) — README seed count; bind `resolve_keyword` once.
3. **Harden test isolation F-004** (M/Med) — autouse isolated-data-dir fixture; lazy engine. *Stops order-dependence and working-tree pollution.*
4. **De-network the legacy tests F-003** (M/Low) — mock or quarantine `src/scraper/scraper.py`. *Makes the suite offline-deterministic.*
5. **PQC coverage F-006** (S/Low) — a CI lane with `[pqc]` so the post-quantum claim is exercised.
6. **Lint burn-down F-001** (L/Low) — per-module, then flip CI ruff to blocking on cleaned trees.
7. **Briefing memoisation F-005** (M/Low) — compute the corpus near-dup graph once per refresh.
8. **Law URL liveness F-010** (S/Low, needs network) — one-off check; prefer ELI URLs.

## 7. Quick wins (safe, high-value, low-effort)

- F-002 representative fix (one line + a test) — closes the only real correctness defect.
- F-007 README count update.
- F-009 bind `resolve_keyword` once.
- Promote the F-008 positive controls to **CI invariants** (secret scan, "quarantine not
  imported" assertion, in-app-doc existence test) so they can't silently regress.

---

*Read-only audit: no repository source was modified. The four deliverables above
(`AUDIT_LOG.md`, `AUDIT_REPORT.md`, `findings.json`, `findings.csv`) are the only files
written. Every claim here is traceable to a numbered line in `AUDIT_LOG.md`.*
