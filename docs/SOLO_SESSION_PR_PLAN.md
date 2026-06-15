# Solo session — PR stack manifest (2026-06-15)

Merge **oldest-first**. PR 1 is independent (docs-only) and merges any time. PRs 2→3
are a linear stack (3 cut from 2's head); merge them in order. GitHub auto-retargets a
stacked PR's base to `0.09` when its parent merges. **PR 4 was planned then CANCELLED**
(Item H proved already-shipped at HEAD — see the note below).

| # | PR | Branch | Purpose | Base | Merge order | Gate |
|---|---|---|---|---|---|---|
| 1 | #222 | `claude/solo-audit-2026-06-15` | Run-verified audit + docs-honesty fixes (README sidebar, RC-gate reconciliation) + session docs | `0.09` | any time | docs-only; CI green |
| 2 | #223 | `claude/solo-item-v-airplane-paused` | **Honesty bug (Item V):** airplane-mode ON paints a *paused* (grounded, not green) "Collecting paused" chip instead of fabricated green "Collecting…" | `0.09` | head of the stack | full gate green (1306 passed) |
| 3 | #224 | `claude/solo-item-r-sidebar-expand` | **Quick win (Item R):** collapsed sidebar gets a discoverable expand affordance (two CSS-toggled buttons) | #223 head | after #223 | full gate green (1306 passed) |
| ~~4~~ | — | ~~`claude/solo-item-h-stat-labels`~~ | ~~Item H stat labels + empty-state~~ | — | **CANCELLED** | Item H already resolved at HEAD |

## Dependencies & notes

- **PR 1 (#222) ⟂ PRs 2–3** by construction — PR 1 touches no code/`CLAUDE.md`, so it
  never conflicts with the stack and can merge before or after it.
- **PRs 2 → 3** share `index.html` / locales / `CLAUDE.md` → strict order. PR 3's base
  is `claude/solo-item-v-airplane-paused`, so its diff is only its own increment.
- No migrations, no API contract changes, no network/security/encryption surface in
  any PR. No invariant weakened. New locale strings are AI-drafted (flagged for native
  review), English authoritative, Arabic RTL.
- **PR 4 (Item H) was cancelled** after verify-before-implement found the code already
  does it at HEAD (`HOME_STAT_LABELS` human labels ×12 + the all-zero empty-state +
  live self-update). The honest move was *not* to ship a redundant diff (OO-D14-012:
  the field-test ledger is substantially stale vs the fast-merged code).
- Deferred (recorded in `SOLO_SESSION_DECISIONS.md`): Item Y (bar charts — Class-C
  baseline question), Item N (Trust tabs — Class C), Item X (needs live repro), Item
  Z (keyword-log digest — backend, own PR), plus the carried-forward 06-14 maintainer
  calls.

## Acceptance per PR

- **PR 1:** RC-gate rows reconciled match code at HEAD; README sidebar sentence
  matches the shipped nav; audit artifacts present; full suite still green.
- **PR 2:** with airplane mode ON during a scheduled pass, the chip reads "Collecting
  paused" (grounded/muted, spinner stopped), never green; `test_repo_invariants`
  (incl. #14) green; `node --check` clean; i18n 100% ×12.
- **PR 3:** collapsed rail exposes `#sb-expand` (right chevron, translated "Expand
  sidebar"); expanded shows `#sb-collapse`; invariant #2 intact; i18n 100% ×12.
