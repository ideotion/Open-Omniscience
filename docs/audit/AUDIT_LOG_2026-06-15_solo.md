# Audit log — 2026-06-15 (autonomous solo session)

> **Role.** Sole engineer, autonomous session, maintainer unavailable. This is a
> *run-verified* audit: unlike the 2026-06-14 read-only pass (Python 3.11 sandbox,
> no deps), this session has **Python 3.13.12 + all extras + node 22**, so every
> gate below was **executed**, not inferred.
>
> **Relationship to prior audits.** The 2026-06-14 read-only audit
> (`AUDIT_LOG_2026-06-14.md`, 30 `OO-D*` findings) and its 2026-06-15 remediation
> (`ACTION_PLAN_2026-06-14.md`) are the spine. This pass does **not** re-file
> already-closed findings; it (1) re-establishes the green baseline by running it,
> (2) records **docs↔code drift** that has accumulated since (the RC gate and README
> now *understate* and *misstate* the shipped surface), (3) triages the freshest
> backlog (`field-test-2026-06-15/LEDGER.md`, items A–AC) into actionable findings,
> and (4) sweeps for net-new issues. New finding IDs continue the `OO-D<dim>-<n>`
> scheme, numbered ≥010 per dimension to avoid colliding with the 06-14 batch.

- **Base commit:** `00923bb` (tip of `0.09`, PR #221 merged).
- **Branch:** `claude/solo-audit-2026-06-15` → PR onto `0.09` (docs-only).
- **Environment:** Python 3.13.12, node v22.22.2, `pip install -e ".[analysis,dev,pqc]"`
  + pinned `bandit==1.9.4` / `pip-audit==2.10.1` (the CI versions).

## 1. Baseline — every gate RUN (the green reference for this session)

| Gate | Command | Result |
|---|---|---|
| Tests | `pytest -q` | **1306 passed, 4 skipped** (282 s) ✅ |
| Type ratchet | `mypy src/` | **114** errors ≤ baseline **127** ✅ |
| SAST | `bandit -r src/ -ll -q` | clean ✅ |
| Deps | `pip-audit --skip-editable` | "No known vulnerabilities found" ✅ |
| i18n | `i18n_report.py --min 100` | **100% ×12** (932/932 keys) ✅ |
| Migrations | `alembic upgrade head` then `alembic check` | applies clean; **no drift** ✅ |
| Syntax sweep | `python -m compileall src` | clean ✅ |
| Lint (advisory) | `ruff check src/ tests/` | **239** findings — `continue-on-error: true` in CI (legacy style debt, burn-down deferred — OO-D15-002) |
| Dead-code / complexity | `vulture` / `radon` | **not run** — not installed in the `[analysis,dev,pqc]` extras; noted, not asserted |

**Verdict:** the repository is **green on every blocking gate**. No S0/S1 *code*
finding in this pass. The codebase is disciplined — **0** `TODO/FIXME/XXX/HACK`
markers in `src/**.py`, a linear migration chain, the single-fetcher / no-composite-score
invariants intact (the 06-14 "verified-strong" controls re-confirmed by the passing
`tests/test_repo_invariants.py`).

## 2. Docs↔code drift (the honesty dimension — D14) — the headline of this pass

The project's whole ethic is honesty about its own maturity. Two living docs have
drifted out of sync with the shipped code. Both **understate or misstate** reality,
so neither is a "claims more than it does" violation — but both are honesty findings
because a reader (or the maintainer planning the RC) is misled about the true state.

### OO-D14-010 (S2) — the RC gate (`RELEASE_0.1_RC_GATE.md`) understates shipped progress

The gate lists as ⬜/🔶 a set of rows that `CLAUDE.md` records as shipped **and that
I verified in code at HEAD**:

| RC-gate row (current) | Reality at HEAD (verified) |
|---|---|
| "Agenda: remaining views (week/trimester/semester/year/decade)" — ⬜ SHOULD | **Shipped** — `index.html` agenda view bar has Month/Week/Trimester/Semester/Year/Decade/List buttons (PR #206 per ledger) |
| "ONE corpora system … REMAINING: full sub-tab set" — 🔶 | Sub-tab set **built out** — `data-tab` for mindmap/sentiment/competitive/keywords/sources present (PRs #214–218) |
| "Interactive charts … REMAINING: commodity-card enlarge + indices board" — 🔶 | Indices detail **rolled onto `ooChart`** (invariant #16 test asserts `ooChart($("idx-chart-oo")`); PR #205) |
| time-scope control "REMAINING" across rows | **Shipped** as the reusable `ooTimeScope` (22 refs; PRs #197–201) |
| "When×Where×Who … REMAINING: reader reads stored rows; WHO aggregation" — 🔶 | **Shipped** — `datestore.for_article` in the reader (PR #202); `/api/insights/who` + `/where` aggregates (per ledger) |
| Convergence "POST … ships in 0.1.x" | **Slice 1 shipped** read-only (`src/analytics/convergence.py` exists; PR #212) |

**Impact:** a maintainer reading the gate to plan the RC sees more open RC-BLOCKING
work than exists. **Fix (this PR):** reconcile the verifiable rows to ✅/🔶-advanced,
add a dated "reconciled against CLAUDE.md + code" note, and state that **`CLAUDE.md`
is the live ledger** and the gate is a periodic snapshot. Conservative by rule — only
rows spot-checked against code are advanced; nothing is marked ✅ on the strength of
the ledger alone.

### OO-D14-011 (S3) — README sidebar description is stale

`README.md` (the "Web UI" bullet) describes the sidebar as *"grouped by intention
(Investigate · Collect · Trust · System) covering Home, **Search**, Analysis, …,
and an in-app **Help/docs reader**."* At HEAD:

- The **System** nav-group was **removed** 2026-06-15 (an explicit comment at
  `index.html:732`: *"System nav-group removed … Help & docs left the …"*; field-test
  Item P). There is no "Help/docs reader" sidebar tab — Help is the top-bar `?`.
- **Search** is **not** a sidebar nav-item (the static nav at `index.html:708–730`
  has no `data-tab="search"`). The `#tab-search` page still exists and is reachable
  via the omnibar's "Run the full Boolean search" (`index.html:3362`) and the palette
  ("Run a search", `:3270`) — **not orphaned** (hand-verified; the Boolean query +
  signed-evidence export are not lost, satisfying the Desk lesson) — but it is no
  longer a sidebar tab.

**Fix (this PR):** correct the README sidebar sentence to match the shipped nav
(Investigate · Collect · Trust groups; Help is the top-bar `?`; search is the
top-bar omnibar). No code change — the code is correct; the doc is stale.

> Note: the README's `0.0.x`-vs-`0.9` versioning, the "What works now" list, the
> quarantine-archive honesty note, and the security model section were all
> re-checked and are **accurate** at HEAD. Only the one sidebar sentence drifted.

## 3. Field-test backlog triage (`field-test-2026-06-15/LEDGER.md`, items A–AC)

The freshest backlog is a maintainer field session: 29 items, most marked
`⏭ capture-only` (diagnosed in code, not yet implemented). These are, in effect,
pre-triaged audit findings. I re-grounded the ones I act on this session against
HEAD; the table records each item's class and my disposition. Items needing a
genuine maintainer ruling (Class C) are **not** decided here — they are recorded for
the maintainer with the conservative default taken.

| Item | One-line | Verified at HEAD | Disposition this session |
|---|---|---|---|
| **V** | Airplane-mode ON still paints green "Collecting…" (should show *paused*) | `_paintActivity` (`:2369`) never reads online state; `_paintNetwork` (`:2578`) knows it | **SHIP** — honesty bug, PR 2 |
| **R** | Sidebar has a collapse button but no discoverable EXPAND affordance | `toggleSidebar` (`:3206`) flips state; collapse btn at `:744`; collapsed rail hides labels | **SHIP** — quick win, PR 3 |
| **H** | Home "at a glance" stats show raw `snake_case` table keys; not translated | `loadHome` (`:3245`) prints `esc(k)` raw; CSS uppercases → "SOURCE_GROUPS" | **SHIP (labels + empty-state)** — i18n/honesty bug, PR 4 |
| F | Home/Briefing auto-refresh (remove Refresh button) | painted only by `loadHome` | defer (live-update mechanism; larger; pairs with H(a)) |
| Y | App-wide chart rule: n<10 → BAR (amends invariant #16) | both renderers identified | **DEFER w/ DEFERRED decision** — has a real bar-baseline honesty question (Class B); needs the invariant-#16 test flipped; recorded for a dedicated slice |
| D, G | dropdown `<option>` labels untranslated (i18n long tail) | confirmed | defer (i18n long-tail sweep; its own batch) |
| X | "Task manager doesn't open" | code path verified correct at HEAD; suspected stale/cached build | **no code change** — cannot reproduce statically; recorded as needs-live-repro |
| W | Move "healthy" indicator into the task-manager System tab | blocked on X | defer (blocked on X) |
| I, K, L | Home cards clickable → analysis window; keyword panels | partially built | defer (Group F flagship; large) |
| N | "Trust" tabs rethink (dissolve/spread) | — | **Class C** — maintainer explicitly "help me decide"; recorded, not touched |
| T, S, U, AA, AB, AC | keyword-quality / trans-language lexicon rework | data-quality | defer (large, design-collaborative) |
| Z, M | diagnostics keyword-log is 60 MB → make a digest | `/keywords` serialises 80k fat entries | defer (good candidate; backend; its own PR) |
| C, E | Agenda space/buttons/flags + auto-populate + source manager | mostly NEW | defer (agenda batch) |
| O | tabs right-clickable → open in new window | NEW | defer (routing rework) |
| Q | in-app docs translated + auto-inherited | translation open | defer |
| P | remove Help & docs sidebar tab | **already shipped** (`:732`) | ✅ done (README catch-up = OO-D14-011) |

## 4. Carried-forward open findings (from 06-14, still open — not re-litigated)

These remain the correct open set; this pass confirms they are unchanged and does
not duplicate them:

- **OO-D12-001 / OO-D2-002 (S2)** — 199 inline handlers → `data-*`/delegation, then
  drop CSP `'unsafe-inline'`. Large **and** browser-unverifiable in this environment
  (no headless browser). Deferred with the same reasoning as 06-15.
- **OO-D15-002 (S2)** — ruff-blocking burn-down (239 findings). Advisory in CI today;
  flipping to blocking is a review-drowning diff. Deferred (own PR).
- **OO-D15-003 (S2)** — graduate the win/mac CI lanes from observation to required.
  Cannot verify those OSes here. Deferred.
- **OO-D8-001 (S2)** — the 100k-article scale run. The harness measures the named
  paths; the heavy measured run is a maintainer/CI job. Deferred.
- **OO-D5-001 (S2)** — custody-on-ingest default (opt-in vs always-on). Behaviour +
  perf trade-off; a **maintainer call**. Not flipped.
- **OO-D3-002 (S1)** — exact wording of the qualified "stays on this machine"
  headline ×12. Default shipped 06-15; final phrasing **awaits the maintainer**.

## 5. Net-new sweep (beyond the ledger)

- **No new S0/S1.** The single-fetcher, kill-switch, no-composite-score, robots
  fail-closed, loopback-bind, zero-network-boot controls are intact (invariant tests
  green; `bandit` clean).
- **vulture/radon not available** ⇒ no dead-code/complexity numbers this pass; the
  06-14 finding that `async_db` is kept-for-future Postgres scaffolding (0 coverage,
  excluded from mypy) is unchanged and already documented.
- **Migration chain**: linear and applies on a fresh DB; `alembic check` clean.
- The five constitution invariants were re-checked against the relevant code paths
  and **conform** (auditability conforms *with the documented opt-in-custody caveat*,
  OO-D5-001).

## 6. Action plan pointer

The disposition of every finding (decision · status · resolving PR) and the
session's whole PR stack are in:
- `docs/audit/ACTION_PLAN_2026-06-15_solo.md`
- `docs/SOLO_SESSION_DECISIONS.md` (every Class B/C call + DEFERRED rulings)
- `docs/SOLO_SESSION_PR_PLAN.md` (the stack manifest, in merge order)
