# AUDIT_TRAIL.md

Append-only ledger of audit runs against this repository. Newest first.
Each entry: date, commit, scope, headline findings, and a pointer to the full log.

---

## 2026-07-22 · Systematic GUI test & critical review (100-agent Chromium pass)

- **Base commit:** `main` tip at session start; brief:
  [`docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_GUI_SYSTEMATIC_TEST.md`](docs/design/AUTONOMOUS_SESSION_BRIEF_2026-07-22_GUI_SYSTEMATIC_TEST.md).
- **Method:** a 100-agent orchestrated run (14 walk/lifecycle/cross-cutting/perf agents →
  86 raw findings → a fresh-load adversarial skeptic re-verification of every candidate → 72
  merged findings after cross-group dedup) driving a **real Chromium browser** against the
  app across all three test states, on a synthetic corpus seeded through the real
  `index_article` chokepoint. All 5 P0s + 4 sampled P1s were additionally HAND-re-verified by
  the orchestrating session (source citations + fresh live reproduction) — 9/9 confirmed,
  zero false positives.
- **Headline positive:** the airplane-mode zero-egress guarantee held perfectly across
  thousands of requests under adversarial concurrent load — no agent, of 100, ever reached a
  non-loopback host.
- **5 P0s found** (see the full report for detail): the reader's "Related in your corpus" +
  near-dup badge query a dead legacy table with zero live writers; the `#net-coach` onboarding
  coachmark pointer-blocks the airplane toggle it points at; a rejected first-launch
  passphrase hides the whole create-passphrase form; at 375px several top-bar controls are
  pushed off-screen with no scroll affordance; the Settings text-size slider has no accessible
  label. Plus 24 P1 / 38 P2 / 5 optional findings, and 3 independently-confirmed-already-fixed
  known-open items.
- **Verification stamp convention introduced:** passing surfaces carry "Chromium-verified
  (remote sandbox) · awaiting human UX pass" — explicitly NOT the queued Gecko-verified(VM)
  bar, and it does not replace a maintainer click-through.
- **Full log:** [`docs/audit/GUI_TEST_REPORT_2026-07-22.md`](docs/audit/GUI_TEST_REPORT_2026-07-22.md)
  + machine-readable companions
  [`findings.csv`](docs/audit/gui-test-2026-07-22/findings.csv) (72 merged) ·
  [`coverage.csv`](docs/audit/gui-test-2026-07-22/coverage.csv) (179 rows) ·
  [`killed_findings.csv`](docs/audit/gui-test-2026-07-22/killed_findings.csv) (7 refuted).
- **Follow-up:** the report's 5 P0s were the seed of PR #740/#744's remediation, itself
  addressed across several later sessions (see `docs/ledger/shipped.csv`).

---

## 2026-07-21 · Transversal audit, 0.3 edition (delta audit vs 07)

- **Base commit:** `main` tip at session start; scoped as a *delta* against
  [`07_TRANSVERSAL_AUDIT_V01.md`](docs/audit/07_TRANSVERSAL_AUDIT_V01.md) (2026-06-12), per
  **THE 0.3 CLOSE GATE, row 2** in `CLAUDE.md`, not a re-derivation from scratch.
- **Scope:** (a) disposition of 07's own Action Plan B, checked against
  `docs/ledger/shipped.csv`; (b) a transversal pass (method/truth/disclosure, tamperability,
  scale, missing data, neutrality, bias) over every surface that shipped since 07, incl. the
  new law vertical and the super-groups/GROUPS hierarchy layer.
- **Headline:** 07's two core truths still hold (the honesty discipline is the right spine;
  labels alone don't make outputs true or understood). The corpus moved from a synthetic
  6.4k-article sample (07's T1) to a live ~500k-article corpus, an order of magnitude past
  it. Two concrete deltas flagged: the DB-10 §1b page-size A/B bench found and fixed a real
  encrypted-reopen defect but is **still pending its large-corpus run** (carried into the 0.3
  close gate as open); 07's proposed 100k-article `perf_harness.py` extension was **not
  done** — the only evidence at 500k scale is qualitative (maintainer field reports), not a
  repeatable harness run.
- **Full log:** [`docs/audit/08_TRANSVERSAL_AUDIT_0.3.md`](docs/audit/08_TRANSVERSAL_AUDIT_0.3.md)

---

## 2026-07-15 · External audit — full transversal / bug-bounty / docs-vs-reality

- **Commit audited:** `da393591` (branch `main`, fetched fresh from `origin`).
- **Auditor:** an autonomous AI audit session (1 lead + 3 parallel specialist sub-agents:
  security, code-quality, docs-verification).
- **Scope, stated honestly:** full static analysis of `src/` (ruff default + the security
  ruleset, with manual tracing of every suppressed warning), manual review of the four
  highest-stakes subsystems (SQL construction, the ethical-fetcher egress chokepoint, the
  custody-log crypto, secrets/config handling), `pip-audit`, secret-pattern scanning, 18
  documentation claims extracted from README.md and checked against source, and a CI-gate
  reality check. Explicitly NOT performed: live DAST/pentest, load/fuzz testing, container/
  cloud scanning (no such infrastructure exists for this local-first app), and a second-pass
  peer review of the report itself.
- **Two HIGH findings, both since RESOLVED:**
  - **OO-01** — a SQL-injection primitive in the backup-restore path (`src/backup/merge.py`):
    a table name from an untrusted restore artifact was interpolated into a quoted identifier
    with a `nosec` comment whose trust claim was factually wrong for that call site. **Fixed**
    (an allowlist-validated `_ident()` + `_SAFE_TABLE_NAME`, referenced inline at the fix site
    — "audit OO-01").
  - **OO-02** — the panic-wipe / secure-uninstall path overwrote only the first 4 MiB of each
    file regardless of size, leaving most of a multi-GB corpus unerased — directly undermining
    the feature's own threat model. **Fixed** via a two-phase crypto-erase
    (`src/safety/crypto_erase.py`): the quick pass destroys the SQLCipher salt page, making the
    encrypted corpus permanently unrecoverable at ANY size, with an optional full free-space
    scrub as defence-in-depth; the byte-overwrite-vs-SSD/CoW limitation stays honestly
    disclosed rather than falsely promised away.
  - Also found: a Medium supply-chain defect (a pinned `numpy` version not resolvable on
    public PyPI) and several Informational/Low docs-vs-reality gaps (the mypy ratchet vs. an
    implied zero-error gate, PQC signing off-by-default, a stale git-remote-tracking note).
- **Full log:** [`docs/audit/EXTERNAL_AUDIT_2026-07-15.md`](docs/audit/EXTERNAL_AUDIT_2026-07-15.md)

---

## 2026-07-13 · Cumulative integrity audit (0.2 cycle, S1–S6 all merged)

- **Base commit:** `a25e5ca2` (tip of `origin/0.2`, S1–S6 all merged).
- **Scope:** verify that everything the project CLAIMS shipped is present + correct in the
  current tree, *cumulatively* — i.e. not silently reverted by a later merge (the #548
  hazard). Read-only. Claim set: the 324 `docs/ledger/shipped.csv` rows + the `docs/ROADMAP.md`
  ✅ rows + the merged-PR history they reference.
- **Method:** a breadth scan (scripted) of every row's `key_paths`/referenced test file
  against the tree, plus a deep-verify agent fan-out over 16 curated high-value/high-risk
  claims (each independently skeptic-refuted; only survivors kept). Environment: py3.13 venv
  without sqlcipher3, so the encrypted-store + httpfs lanes honestly SKIP rather than being
  claimed as run.
- **Headline: the tree has HIGH cumulative integrity — no #548-style silent revert found.**
  Of 324 claims, only 1 absent artifact surfaced, and it was a documented, deliberate
  retirement (a superseded single-file backup CREATE path) rather than a regression; the one
  BUG-classed finding was a swallowed-exception diagnosability hole in seed CI-red, not a
  correctness regression. 0 vacuous tests found; the core honesty guards
  (`assert_no_score_fields`, `install_airplane_socket_guard`, the single-writer `WriterGate`)
  all confirmed present and import-time-enforced.
- **Full log:** [`docs/audit/CUMULATIVE_INTEGRITY_AUDIT_2026-07-13.md`](docs/audit/CUMULATIVE_INTEGRITY_AUDIT_2026-07-13.md)

---

## 2026-06-18 · Comprehensive audit + remediation (0.09 / v0.0.9)

- **Base commit:** `b75100e` (tip of the protected default `0.09`, PR #394 merged).
- **Branch:** `claude/eloquent-mayer-ouec0d` (at the `0.09` tip) → one draft PR onto `0.09`.
- **Environment advantage:** a real **Python 3.13.12** + pip were available (unlike the
  3.11-only assumption), so a `.venv313` was built (latest deps: starlette 1.3.1, sqlalchemy
  2.0.51, pytest 9.1.0) and **every gate was executed, not inferred**.
- **Static/boot gates GREEN as-found:** app boots (60 routes), ruff F+B pass, i18n 100% ×12,
  single alembic head (`a2b3c4d5e6f7`), mypy 120 ≤ 127, bandit clean, compileall clean,
  `node --check` clean, `test_repo_invariants` 70 passed.
- **Headline finding — the full test suite was NOT green as-found: 3 failed, 1748 passed, 6
  skipped.** All three reproduce in isolation and are unrelated to this PR's docs; **fixed** here
  (suite green after: **1751 passed, 6 skipped, 0 failed**, and 3.3× faster):
  - **A18-TEST-01 (S1):** `test_convergences_endpoint` — the catalog auto-seed was moved into
    `run_deferred_startup` (2026-06-18, `main.py:120`), so it fires on every TestClient lifespan and
    its auto-increment ids collide with the test's pinned `Source(id=901/902)` (`UNIQUE constraint
    failed: sources.id`). Fix: `OO_AUTOSEED=0` in `tests/conftest.py` (matches `OO_NO_SCHEDULER=1`
    + the existing `test_law.py:205` precedent; direct-seed tests unaffected).
  - **A18-TEST-02 (S2):** `test_disable_unmanaged_languages_endpoint` — a thread-unsafe
    `:memory:` engine shared across the TestClient portal thread ("no such table: sources"). Fix:
    `StaticPool` + `check_same_thread=False` (the pattern `test_convergence.py` already uses).
  - **A18-TEST-03 (S2):** `tests/test_ollama_store_detection.py:32` did `write_text` without
    `encoding="utf-8"` — flagged by the repo's own portability meta-test. Fix: add the encoding.
- **A18-CI-01 (S2, was RED → maintainer-authorized → FIXED):** these landed undetected because **CI
  never completes on `0.09`** — the tip `b75100e7` run sat `queued` and the prior 8 push-runs were
  all `cancelled` (`concurrency: cancel-in-progress` + rapid merges, `.github/workflows/ci.yml:13`).
  Fix: `cancel-in-progress` is now conditional (`github.ref_name != repository.default_branch`) so
  the default/release branch's own push runs run to completion (gate restored) while PRs and feature
  branches still cancel superseded runs. YELLOW trade-off (more runner minutes on the default branch).
- **Two S3 documentation contradictions FIXED (GREEN):** the UI tab renamed *Temporal map → World
  map* (2026-06-18) was stale in `README.md`/`docs/USER_MANUAL.md`, whose nav lists also still
  carried the dissolved **Source integrity** + retired **Search**/**System** sidebar entries.
  Reconciled to ground truth (`src/static/index.html`); historical/planning docs left as records.
- **Verified FALSE POSITIVE (no change):** supergroup `article_count` uses `max()` — the documented
  "articles = max member" honest convention (`src/api/insights.py:854`), not a bug.
- **Known/tracked, unchanged:** CSP `unsafe-inline` (`OO-D12-001`), Ollama clearnet pull (by
  design), SSRF TOCTOU (`OO-D2-003`), `ALLOWED_ORIGINS` env (S3).
- **Full log:** [`docs/archive/audits/AUDIT_LOG_2026-06-18.md`](docs/archive/audits/AUDIT_LOG_2026-06-18.md)
- **Source files changed:** `tests/conftest.py`, `tests/test_managed_languages.py`,
  `tests/test_ollama_store_detection.py` (test-baseline), `README.md`, `docs/USER_MANUAL.md`
  (docs-coherence). The closed 29-finding `findings.csv` ledger was intentionally not touched.

---

## 2026-06-15 · Autonomous solo session — run-verified audit + docs-honesty fixes

- **Base commit:** `00923bb` (tip of `0.09`, PR #221 merged).
- **Branch:** `claude/solo-audit-2026-06-15` → PR onto `0.09` (docs-only).
- **Environment advantage:** Python 3.13.12 + all extras + node 22, so **every gate
  was executed**, not inferred. Baseline RE-ESTABLISHED green: **1306 passed / 4
  skipped**; mypy 114 ≤ 127; bandit clean; pip-audit clean; i18n 100% ×12; alembic
  applies + no drift; `compileall` clean; 0 `TODO/FIXME` in `src`. ruff 239 (advisory,
  `continue-on-error`). vulture/radon not installed → not run (noted, not asserted).
- **Headline findings (both honesty / D14, both *under*-stating reality — no
  overstatement violation, but misleading):**
  - **OO-D14-010 (S2):** the RC gate `RELEASE_0.1_RC_GATE.md` understates shipped
    progress — agenda views, corpus sub-tabs, indices-on-`ooChart`, `ooTimeScope`,
    reader-reads-stored-rows and convergence slice 1 are all shipped in code yet
    listed ⬜/🔶. Reconciled conservatively (only code-spot-checked rows advanced).
  - **OO-D14-011 (S3):** the README sidebar sentence is stale (lists a "System" group
    + a "Search" sidebar tab + a "Help/docs reader" sidebar entry that no longer match
    the shipped nav — System group removed 2026-06-15; search is the top-bar omnibar;
    Help is the top-bar `?`). Code is correct; the doc was fixed.
  - **No new S0/S1 code finding.** The single-fetcher / kill-switch / no-composite-score
    / robots-fail-closed / loopback-bind / zero-network-boot controls re-confirmed by
    the passing invariant suite.
- **Backlog triage:** `field-test-2026-06-15/LEDGER.md` items A–AC re-grounded; three
  well-diagnosed, low-risk maintainer-reported bugs shipped as their own PRs this
  session (V airplane-paused-status, R sidebar-expand, H stat-labels). Item Y (bar
  charts) DEFERRED on a real bar-baseline honesty question; Item N (Trust tabs) is a
  Class-C "help me decide" left untouched; Item X (TM doesn't open) not reproducible
  statically (likely stale build).
- **Full log:** [`docs/archive/audits/AUDIT_LOG_2026-06-15_solo.md`](docs/archive/audits/AUDIT_LOG_2026-06-15_solo.md)
- **Action plan / decisions / PR stack:**
  [`docs/archive/audits/ACTION_PLAN_2026-06-15_solo.md`](docs/archive/audits/ACTION_PLAN_2026-06-15_solo.md) ·
  [`docs/archive/SOLO_SESSION_DECISIONS.md`](docs/archive/SOLO_SESSION_DECISIONS.md) ·
  [`docs/archive/SOLO_SESSION_PR_PLAN.md`](docs/archive/SOLO_SESSION_PR_PLAN.md)

---

## 2026-06-15 · Audit remediation pass (acts on the 2026-06-14 findings)

- **Base commit:** `6b4ff13` (tip of `0.09`; the #158 claim sweep already landed).
- **Branch:** `claude/great-galileo-l2kfmn` → PR onto `0.09`.
- **Environment advantage:** unlike the read-only audit, this pass had Python 3.13
  + all extras + node 22, so every fix was **verified by running** the suite
  (baseline 1160 passed / 6 skipped green; mypy 114 ≤ 127; bandit clean; i18n 100%
  ×12). No headless browser — frontend changes are `node --check`'d + test-pinned,
  not visually verified.
- **Plan:** [`docs/archive/audits/ACTION_PLAN_2026-06-14.md`](docs/archive/audits/ACTION_PLAN_2026-06-14.md)
  (every finding → decision → status → resolving commit).
- **Resolved (verified):** OO-D2-001 (robots-redirect SSRF + tests), OO-D3-001/
  OO-D5-002/OO-D10-001 (dead-config prune + data-dir divergence), OO-D7-001
  (savepoint upsert), OO-D10-002 (credibility-column serialization guard test),
  OO-D9-001/OO-D14-001/-003/-004/-005/-006/-007/OO-D6-001 (docs honesty sweep),
  OO-D15-001/-004/-005/-006 (i18n CI gate, pin pip-audit, generic extra-probe,
  fake-clock cache), OO-D13-001/-002/OO-D12-002 (a11y focus + esc()), OO-D3-002
  (privacy claim qualified ×12) + audit-07 **B1** (VADER framing caveat, LLM verify
  label, USER_MANUAL disclosures), OO-D8-001 (harness measures the named paths),
  OO-D5-001 + OO-D2-003 (auditability + SSRF-residual disclosures).
- **Re-verify corrections:** OO-D14-002 already fixed at HEAD; OO-D13-002
  recipe-toggles already labelled (only `fam-pick` needed it); audit-07 B1 VADER
  already disclosed on corpus-sentiment (the *framing* surface was the gap).
- **Deferred (with reason, raised as questions):** OO-D12-001 + OO-D2-002 (the
  199-handler→CSP migration — large + browser-unverifiable here), OO-D15-002/-003
  (ruff-blocking burn-down; win/mac graduation), the actual 100k perf run.
- **Pointer:** this remediation is one comprehensive PR; the 2026-06-14 log below
  remains the read-only finding source of truth.

---

## 2026-06-14 · Comprehensive read-only audit & handoff (0.09 / v0.0.9)

- **Commit:** `ba61162fedd02bd1787c7c15bc957526da2909d7`
- **Branch:** `claude/vibrant-fermi-15pxby` (tip of the `0.09` line)
- **As of:** 2026-06-14, 15:36 Central European Time
- **Auditor:** Claude Code (read-only role) — static-first; the app could not be
  run dynamically (sandbox Python 3.11 vs the project's >=3.13; deps not installed),
  so all dynamic checks are marked Unverified and replaced with static verification,
  a `compileall` syntax sweep, CI-as-evidence, and the existing test corpus.
- **Scope:** all 16 audit dimensions (D1–D16) across the core (`src/api`, ingest/
  fetcher, database/migrations, backup, llm, custody, safety), the frontend
  (`src/static`), config/installer (`install.sh`, `scripts/bootstrap.sh`,
  `pyproject.toml`, `.env.example`), CI (`.github/workflows/ci.yml`), and docs; plus
  the five constitution invariants. Five parallel sub-audits + hand-verification of
  the security/privacy/ethics-critical paths.

- **Headline findings:**
  - **The application is FUNCTIONAL and mature at 0.09.** Every stale `0.04` lead
    (non-functional build; `pillar2…6` fragmentation; competing `requirements*.txt`;
    dual master-index docs; `OLLAMA_HOST=0.0.0.0` / `OLLAMA_ORIGINS=*` /
    `AUTO_DOWNLOAD_MODELS=true`; curl|bash stale `0.03` branch; muddled Python target)
    was checked and found **resolved**. The pillars were deliberately **quarantined**
    (honest `quarantine/README.md`) for "pretending to work."
  - **No S0 blockers and no outright constitution violations.** All five invariants
    conform (auditability conforms *with caveat* — the tamper-evident custody trail
    is opt-in by default).
  - **Top open items:** ETHICS.md still future-tense ("when the software becomes
    functional" / "when implemented") — OO-D14-001 (S1); the unqualified "stays on
    this machine" claim vs proxy/Tor modes — OO-D3-002 (S1, awaits ruling); robots.txt
    redirects not SSRF-re-validated — OO-D2-001 (S2); docs describe a removed
    `POST /api/database/restore` — OO-D14-003 (S2); no i18n gate in CI — OO-D15-001
    (S2); 199 inline handlers + `unsafe-inline` CSP — OO-D12-001/OO-D2-002 (S2);
    palette/task-manager dialogs miss aria-modal/focus — OO-D13-001 (S2).
  - **Verified-strong:** the single mandatory `EthicalFetcher` (robots fail-closed,
    SSRF guard, kill switch, honest UA, Tor isolation); the import-time no-composite-
    score enforcement; CSV formula-injection defense + SQL parameterization + linear
    migration chain + single-writer transaction safety; loopback CORS/CSRF/bind;
    fully-local Ollama (no auto-download); zero-network airplane-mode boot; the gated,
    off-by-default DuckDuckGo channel.
  - 30 findings filed (mostly S2/S3; two S1 honesty items; one S0 = none). 8 themed
    remediation work packages, sequenced and dependency-aware.

- **Full log:** [`docs/archive/audits/AUDIT_LOG_2026-06-14.md`](docs/archive/audits/AUDIT_LOG_2026-06-14.md)
- **Note:** This run modified no source file. Only this trail entry and the audit log
  were written (and committed as audit-artifacts-only to persist in the ephemeral
  environment). In-flight PRs #150 (guided wizard) and #151 (task-manager Schedule
  subtab) were noted and excluded from the roadmap.
