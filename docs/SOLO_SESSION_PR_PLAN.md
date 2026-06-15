# Solo session — PR stack manifest (2026-06-15)

Merge **oldest-first**. PR 1 is independent (docs-only) and merges any time. PRs 2→3→4
are a linear stack (each cut from the previous head); merge them in order. GitHub
auto-retargets a stacked PR's base to `0.09` when its parent merges.

| # | Branch | Purpose | Base | Merge order | Touches | Gate |
|---|---|---|---|---|---|---|
| 1 | `claude/solo-audit-2026-06-15` | Run-verified audit + docs-honesty fixes (README sidebar, RC-gate reconciliation) + session docs | `0.09` | any time | `AUDIT_TRAIL.md`, `docs/audit/*solo*`, `docs/SOLO_SESSION_*`, `README.md`, `docs/product/RELEASE_0.1_RC_GATE.md` | docs-only; suite re-run green |
| 2 | `claude/solo-item-v-airplane-paused` | **Honesty bug (Item V):** airplane-mode ON paints a *paused* (calm, not green) "Collecting paused" chip instead of fabricated green "Collecting…" | `0.09` | after PR1 (independent files, but merge 1st for the ledger context) | `src/static/index.html`, `src/static/locales/*.json`, `CLAUDE.md` | full gate green |
| 3 | `claude/solo-item-r-sidebar-expand` | **Quick win (Item R):** collapsed sidebar gets a discoverable expand affordance (state-aware toggle: title/aria/glyph flip) | PR 2 head | after PR 2 | `src/static/index.html`, `src/static/locales/*.json`, `CLAUDE.md` | full gate green |
| 4 | `claude/solo-item-h-stat-labels` | **i18n/honesty bug (Item H b+c):** Home stat strip shows human translated labels (not raw `snake_case`) + friendly empty-state on an all-zero corpus | PR 3 head | after PR 3 | `src/static/index.html`, `src/static/locales/*.json`, `CLAUDE.md` | full gate green |

## Dependencies & notes

- **PR 1 ⟂ PRs 2–4** by construction — PR 1 touches no code/`CLAUDE.md`, so it never
  conflicts with the stack and can merge before or after it.
- **PRs 2 → 3 → 4** share `index.html` / locales / `CLAUDE.md` → strict order. Each
  diff is only its own increment.
- No migrations, no API contract changes, no network/security/encryption surface in
  any PR. No invariant weakened. New locale strings are AI-drafted (flagged for native
  review), English authoritative, Arabic RTL.
- Deferred (recorded in `SOLO_SESSION_DECISIONS.md`): Item Y (bar charts — Class-C
  baseline question), Item N (Trust tabs — Class C), Item X (needs live repro), plus
  the carried-forward 06-14 maintainer calls.

## Acceptance per PR

- **PR 1:** RC-gate rows reconciled match code at HEAD; README sidebar sentence
  matches the shipped nav; audit artifacts present; full suite still green.
- **PR 2:** with airplane mode ON during a scheduled pass, the chip reads "Collecting
  paused" in the calm/grounded (go-off) accent, never green; `test_repo_invariants`
  green; `node --check` clean; i18n 100%.
- **PR 3:** collapsed sidebar exposes an expand affordance with a translated
  Expand/Collapse title; invariant #2/#3 intact; i18n 100%.
- **PR 4:** Home strip shows translated human labels; an all-zero corpus shows the
  empty-state; the Database tab keeps the raw keys; i18n 100%.
