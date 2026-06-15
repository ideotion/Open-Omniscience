# Audit action plan — 2026-06-15 (autonomous solo session)

> Maps every finding from `AUDIT_LOG_2026-06-15_solo.md` to a decision, a status,
> and the PR that resolves it. The session shipped a small, **honest, verified**
> stack (audit + three maintainer-reported bug fixes) and recorded every judgment
> call. Quality over quantity: each PR is single-purpose, green on the full gate,
> and reversible.

Legend: ✅ shipped+verified · 📝 documented decision (maintainer call surfaced) ·
⏭️ deferred with reason · 🔁 carried-forward (unchanged from 06-14).

## Disposition

| ID | Sev | Decision | Status | PR |
|---|---|---|---|---|
| OO-D14-010 | S2 | Reconcile the RC gate to shipped reality (conservative, code-spot-checked) + "CLAUDE.md is the live ledger" note | ✅ | PR 1 |
| OO-D14-011 | S3 | Correct the README stale sidebar sentence (no System/Help tab; search is the omnibar) | ✅ | PR 1 |
| Item V | S2 | Airplane-mode ON → activity chip shows a *paused* (calm/grounded, not green) "Collecting paused" — kill the fabricated green | ✅ | PR 2 |
| Item R | S3 | Add a discoverable EXPAND affordance to the collapsed sidebar rail | ✅ | PR 3 |
| Item H(b)(c) | S2 | Map Home stat keys → human, translated labels (UI layer); show the friendly empty-state on all-zeros | ✅ | PR 4 |
| Item H(a) / Item F | S3 | Live Home self-update | ⏭️ | larger; shared mechanism; own PR |
| Item Y | S2 | App-wide n<10 → bar chart (amends invariant #16) | 📝 ⏭️ | DEFERRED — real bar-baseline honesty Q (see D-04); needs the #16 test flipped |
| Item N | — | "Trust" tabs dissolve/spread | 📝 | Class C — maintainer "help me decide"; recorded, untouched |
| Item X | — | Task manager "doesn't open" | ⏭️ | cannot reproduce statically; needs live repro (likely stale build) |
| Item Z/M | S3 | 60 MB keyword-log → local digest | ⏭️ | good candidate; backend; own PR |
| OO-D12-001/D2-002 | S2 | inline-handlers → CSP | 🔁 ⏭️ | large + browser-unverifiable |
| OO-D15-002 | S2 | ruff blocking | 🔁 ⏭️ | review-drowning; own PR |
| OO-D15-003 | S2 | win/mac graduation | 🔁 ⏭️ | not verifiable here |
| OO-D8-001 | S2 | 100k scale run | 🔁 ⏭️ | heavy measured run |
| OO-D5-001 | S2 | custody default flip | 🔁 📝 | maintainer call |
| OO-D3-002 | S1 | privacy headline final wording ×12 | 🔁 📝 | maintainer call |

## What shipped (verified by running the full gate)

| PR | Branch | Touches | Gate |
|---|---|---|---|
| 1 | `claude/solo-audit-2026-06-15` | audit docs, README, RC gate, session docs | docs-only; suite re-run green |
| 2 | `claude/solo-item-v-airplane-paused` | `index.html`, locales ×12, `CLAUDE.md` | full gate green |
| 3 | `claude/solo-item-r-sidebar-expand` | `index.html`, locales ×12, `CLAUDE.md` | full gate green |
| 4 | `claude/solo-item-h-stat-labels` | `index.html`, locales ×12, `CLAUDE.md` | full gate green |

## Verification protocol (run after every PR, before push)

- `pytest -q` full suite green (baseline 1306 passed / 4 skipped).
- `mypy src/` ≤ 127; `bandit -r src/ -ll -q` clean; `pip-audit --skip-editable` clean.
- `node --check` on each edited `<script>` block in `index.html`.
- `scripts/i18n_report.py --min 100` after any locale change.
- `OO_DB_PLAINTEXT=1 alembic check` if a model changed (none did this session).

## Held for the maintainer (the unanswerable-question outputs — see SOLO_SESSION_DECISIONS.md)

1. **Item Y bar-baseline** (D-04): window-min-labeled axis for price-level series vs
   true-zero for count series — the conservative default is recorded; the chart-baseline
   ethics is the maintainer's to confirm before the bar rule ships.
2. **Item N** "Trust" tabs dissolve/spread — explicitly "help me decide"; untouched.
3. The carried-forward 06-14 maintainer calls (custody default, privacy wording,
   ruff-blocking flip, win/mac graduation, the inline-handler/CSP migration).
