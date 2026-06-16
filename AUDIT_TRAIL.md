# AUDIT_TRAIL.md

Append-only ledger of audit runs against this repository. Newest first.
Each entry: date, commit, scope, headline findings, and a pointer to the full log.

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
- **Full log:** [`docs/audit/AUDIT_LOG_2026-06-15_solo.md`](docs/audit/AUDIT_LOG_2026-06-15_solo.md)
- **Action plan / decisions / PR stack:**
  [`docs/audit/ACTION_PLAN_2026-06-15_solo.md`](docs/audit/ACTION_PLAN_2026-06-15_solo.md) ·
  [`docs/SOLO_SESSION_DECISIONS.md`](docs/SOLO_SESSION_DECISIONS.md) ·
  [`docs/SOLO_SESSION_PR_PLAN.md`](docs/SOLO_SESSION_PR_PLAN.md)

---

## 2026-06-15 · Audit remediation pass (acts on the 2026-06-14 findings)

- **Base commit:** `6b4ff13` (tip of `0.09`; the #158 claim sweep already landed).
- **Branch:** `claude/great-galileo-l2kfmn` → PR onto `0.09`.
- **Environment advantage:** unlike the read-only audit, this pass had Python 3.13
  + all extras + node 22, so every fix was **verified by running** the suite
  (baseline 1160 passed / 6 skipped green; mypy 114 ≤ 127; bandit clean; i18n 100%
  ×12). No headless browser — frontend changes are `node --check`'d + test-pinned,
  not visually verified.
- **Plan:** [`docs/audit/ACTION_PLAN_2026-06-14.md`](docs/audit/ACTION_PLAN_2026-06-14.md)
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

- **Full log:** [`docs/audit/AUDIT_LOG_2026-06-14.md`](docs/audit/AUDIT_LOG_2026-06-14.md)
- **Note:** This run modified no source file. Only this trail entry and the audit log
  were written (and committed as audit-artifacts-only to persist in the ephemeral
  environment). In-flight PRs #150 (guided wizard) and #151 (task-manager Schedule
  subtab) were noted and excluded from the roadmap.
