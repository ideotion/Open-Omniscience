# Audit remediation — autonomous action plan (2026-06-14)

> **Scope.** Address *every* open finding in the `docs/audit` corpus, with the
> comprehensive `AUDIT_LOG_2026-06-14.md` (30 `OO-D*` findings; supersedes
> `00…07` + `findings.csv`) as the spine, **plus** the `07_TRANSVERSAL_AUDIT_V01.md`
> **B1 disclosure sweep** (RC-gate calls it BLOCKING-proposed). Delivered as ONE
> comprehensive PR for maintainer review.
>
> **Frame note.** The audit was pinned at `ba61162`; this work is on the `0.09`
> tip (HEAD `6b4ff13`), which already includes PR #158 ("docs: claim sweep").
> Per the audit's §8.1 instruction, **every finding was re-verified at HEAD**
> before acting; items the claim sweep already closed are marked
> *Already-fixed-at-HEAD* with evidence and not re-touched.
>
> **Environment advantage.** Unlike the original audit (Python 3.11 sandbox, no
> deps, could not run anything), this session has **Python 3.13 + all extras
> installed + node 22**. Baseline established green: **1160 passed, 6 skipped**;
> `mypy` 114 (CI baseline 127); `bandit -ll` clean; `i18n_report` 100% ×12.
> Every code/test/CI change here is **verified by re-running** the relevant suite.
> The one thing still unavailable is a **headless browser** — so findings that
> require visual/interaction verification of rendered HTML are handled
> conservatively (see WP-4).

## Autonomy policy applied

The user authorized working on *every* aspect autonomously and holding questions
for review. So the audit's three tiers map as:

- **Safe-to-auto** → fixed and verified here.
- **Needs-operator-sign-off** → implemented the honest, reversible version and
  verified it; the *judgement call* is called out in the PR for the maintainer.
- **Discuss-before-touching** → only the inline-handler→CSP migration
  (D12-001/D2-002, 295 inline on*= as of 2026-06-15) lands here, because it is large **and** unverifiable without a
  browser. We ship the safe, additive sibling fixes and the groundwork, and
  document the full migration as the single deferred item with its plan — rather
  than push a blind rewrite that could break the UI (faithful-reporting rule).

## Disposition table (every finding)

Legend: ✅ fixed+verified · 🟡 partial (groundwork/tooling shipped, heavy run or
ruling remains) · 📝 documented decision (maintainer call surfaced) · ⏭️ already
fixed at HEAD.

### WP-1 — Honesty / disclosure sweep (docs)
| ID | Sev | Decision | Status |
|---|---|---|---|
| OO-D14-001 | S1 | ETHICS.md deps section → present tense; deps table rebuilt from real `pyproject`; dates refreshed | ✅ |
| OO-D14-005 | S3 | ETHICS.md "Last Updated" ×2 → 2026-06-14 | ✅ |
| OO-D14-003 | S2 | ARCHITECTURE.md `POST /api/database/restore` → v2 additive-merge restore | ✅ |
| OO-D14-004 | S2 | ARCHITECTURE.md API map regenerated from `app.routes` (+ pointer to `/openapi.json`) | ✅ |
| OO-D14-006 | S2 | ARCHITECTURE.md "© … All rights reserved" → GPLv3 notice | ✅ |
| OO-D14-007 | S3 | DESIGN.md leftover AI-collaboration meta-notes removed (×2) | ✅ |
| OO-D9-001 | S3 | `models.py` docstring qualified to SQLite-supported; docs grep for dual-backend claims | ✅ |
| OO-D14-002 | S2 | README source count | ⏭️ already fixed at HEAD ("~3,200", #158) |
| OO-D3-002 | S1 | "stays on this machine" qualified ×12 ("; fetching follows your Network mode") | ✅ + 📝 (exact wording is the maintainer's to refine) |

### WP-2 — CI breadth & determinism
| ID | Sev | Decision | Status |
|---|---|---|---|
| OO-D15-001 | S2 | Blocking CI step `i18n_report.py --min 100` | ✅ |
| OO-D15-004 | S3 | Pin `pip-audit==<v>` in all three lanes | ✅ |
| OO-D15-005 | S2 | Broaden conftest optional-extra probe (generic ImportError-at-collection guard) | ✅ |
| OO-D15-006 | S2 | Fake-clock the real-`sleep` flakiness vector (`test_cache.py`) | ✅ |
| OO-D15-002 | S2 | ruff blocking: burn-down is 236 errors + 89 files → too large/noisy for a review PR; reduce safe noise, document the flip | 📝 |
| OO-D15-003 | S2 | win/mac graduation: cannot verify those OSes here | 📝 |

### WP-3 — Fetcher SSRF hardening
| ID | Sev | Decision | Status |
|---|---|---|---|
| OO-D2-001 | S2 | robots.txt fetched with `allow_redirects=False`, hops re-validated through the shared guarded loop; regression test | ✅ |
| OO-D2-003 | S3 | DNS-rebinding TOCTOU: connect-time IP pinning is non-trivial with `requests`; documented as a tracked residual with the mitigations already in place | 📝 |

### WP-6 — Config hygiene
| ID | Sev | Decision | Status |
|---|---|---|---|
| OO-D3-001 | S3 | Remove dead `auto_download_models`/`download_default_models` (field+env+YAML); no live consumer | ✅ |
| OO-D5-002 | S3 | Remove vestigial `audit_enabled`/`audit_log_dir`/`get_audit_dir()` (only a test consumed it) | ✅ |
| OO-D10-001 | S3 | `Config.get_data_dir()` delegates to `src.paths.data_dir()` (kills the divergence); ollama fields annotated | ✅ |
| OO-D10-002 | S3 | Repo-invariant test: `credibility_score`/`political_bias` never serialized to any API response | ✅ |

### WP-8 — Reliability
| ID | Sev | Decision | Status |
|---|---|---|---|
| OO-D7-001 | S3 | `upsert_sources` commits per-row with savepoints so a mid-batch error never drops staged rows | ✅ |

### WP-4 — Frontend hardening & a11y
| ID | Sev | Decision | Status |
|---|---|---|---|
| OO-D12-002 | S3 | `collapseAction()` signature wrapped in `esc()` (consistency/defense-in-depth) | ✅ |
| OO-D13-001 | S2 | Palette + task-manager dialogs: `aria-modal`, focus save/restore, Tab trap | ✅ (node-checked) |
| OO-D13-002 | S3 | Recipe/family checkboxes get `aria-label` | ✅ (node-checked) |
| OO-D12-001 | S2 | 295 inline handlers → `data-*`+delegation: large **and** browser-unverifiable here | 📝 deferred w/ plan |
| OO-D2-002 | S2 | Drop CSP `'unsafe-inline'`: blocked on D12-001 | 📝 deferred (depends on D12-001) |

### WP-5 / WP-7 / D6 — rulings, scale, licenses
| ID | Sev | Decision | Status |
|---|---|---|---|
| OO-D5-001 | S2 | Custody opt-in default: do NOT unilaterally flip (perf+behavior). Make docs honest about opt-in | 📝 maintainer call |
| OO-D8-001 | S2 | 100k-scale proof: ship the harness profile capability; the measured run is heavy (maintainer/CI) | 🟡 tooling |
| OO-D6-001 | S3 | Verify `[pqc]`/`[timestamping]` extra licenses; record in deps note | ✅ |

### B1 — transversal disclosure sweep (audit 07)
| Item | Decision | Status |
|---|---|---|
| VADER English-only | label at the tone display surface + manual | ✅ |
| LLM output "model artifact — verify" | label on LLM-output surfaces + manual | ✅ |
| Lexical-limits caveat on keyword surfaces | shared caveat string | ✅ |
| Text-only modality statement | docs/manual | ✅ |
| CJK-segmentation capability honesty | docs/manual + capability note | ✅ |
| Permissive-host survivorship | one sentence on coverage surfaces + manual | ✅ |
| "record begins YYYY-MM" on trends | manual note (UI stamp = follow-up) | 🟡 |
| Wikipedia systemic-bias note | manual | ✅ |

## Verification protocol (run after every batch)
- `pytest -q` (targeted, then full before push) — must stay green.
- `mypy src/` ≤ 127; `bandit -r src/ -ll` clean.
- `node --check` each edited `<script>` block.
- `scripts/i18n_report.py --min 100` after any locale change.
- Re-grep docs for each stale string after a doc fix.

## Resolution log (executed 2026-06-15, branch `claude/great-galileo-l2kfmn`)

Each finding re-verified at HEAD before acting (the audit was pinned at `ba61162`;
HEAD `6b4ff13` already included the #158 claim sweep). Commit → findings:

| Commit | Findings resolved |
|---|---|
| `9569490` | OO-D2-001 (robots-redirect SSRF + 2 regression tests) |
| `135f77b` | OO-D3-001, OO-D5-002, OO-D7-001, OO-D10-001, OO-D10-002 |
| `822c7a4` | OO-D14-001, -003, -004, -005, -006, -007, OO-D9-001, OO-D6-001 |
| `b71341e` | OO-D15-001, -004, -005, -006 |
| `a460448` | OO-D13-001, OO-D13-002, OO-D12-002 |
| `5d9c6e2` | OO-D3-002, audit-07 B1 (VADER framing caveat, LLM verify label, limits) |
| `261bc22` | OO-D8-001 (tooling), OO-D5-001 (docs), OO-D2-003 (docs/true-up) |

**Re-verification corrections (the hand-verify lesson):**
- **OO-D14-002** (README "~2,100") — *already fixed at HEAD* by #158 (now "~3,200"); not re-touched.
- **OO-D13-002** — the recipe-toggle checkboxes are already wrapped in `<label>`
  (implicit association = accessible); only the `fam-pick` checkbox genuinely
  lacked a name. Half the finding was a false positive; the real half is fixed.
- **OO-D14-001 / D9-001** — the ETHICS GPLv3 "becomes functional" line and the
  ARCHITECTURE PostgreSQL section were *already* corrected at HEAD; the remaining
  ETHICS deps section + the models docstring were the open parts, now fixed.
- **audit-07 B1 VADER** — already disclosed on corpus-sentiment at HEAD; the open
  gap was the *framing* surface (empty caveat), now fixed + test-enforced.

**Deferred (with reason), surfaced as questions below:**
- **OO-D12-001 / OO-D2-002** — the inline-handler→`data-*` migration + CSP
  `unsafe-inline` drop. Large *and* unverifiable without a headless browser (a
  blind rewrite risks breaking the whole UI). The safe sibling fixes shipped
  (a11y, esc()); the full migration is a dedicated browser-verified PR.
- **OO-D15-002 / OO-D15-003** — ruff-blocking (236 lint + 89 format files = a
  review-drowning diff; sign-off item) and win/mac graduation (not verifiable
  here). Documented; recommended as their own PRs.
- **OO-D8-001 run** — the harness now measures the named paths; the actual 100k
  measurement is a heavy maintainer/CI run.

## Open questions for the maintainer (held for review, per instruction)
1. **D3-002 wording** — exact phrasing of the qualified privacy headline ×12.
2. **D5-001** — flip custody-on-ingest to a lightweight always-on default, or
   keep opt-in (now documented + discoverable)?
3. **D15-002 / D15-003** — schedule the ruff burn-down (flip to blocking) and
   the win/mac graduation as their own PRs?
4. **D12-001 / D2-002** — green-light the inline-handler→CSP migration as a
   dedicated, browser-verified PR.
