# Solo session — PR stack manifest (2026-06-15 → 06-16)

Two phases: an initial audit + bug-fix batch, then (on the maintainer's "continue
autonomously, implement everything" directive) a backlog-implementation batch. Merge
**oldest-first**. #222 is independent (docs-only). The code PRs are one **linear
stack** (each cut from the previous head) — merge in number order; GitHub auto-retargets
a stacked PR's base to `0.09` as each parent merges.

| # | PR | Branch | Purpose | Base | Gate |
|---|---|---|---|---|---|
| 1 | **#222** | `claude/solo-audit-2026-06-15` | Run-verified audit + docs-honesty fixes (README sidebar, RC-gate reconciliation) + session docs | `0.09` | docs-only; CI green |
| 2 | **#223** | `claude/solo-item-v-airplane-paused` | **Honesty bug (Item V):** airplane-mode ON paints a *paused* (grounded, not green) "Collecting paused" chip | `0.09` | full gate green |
| 3 | **#224** | `claude/solo-item-r-sidebar-expand` | **Quick win (Item R):** collapsed sidebar gets a discoverable expand affordance (two CSS-toggled buttons) | #223 | full gate green |
| 4 | **#225** | `claude/solo-item-z-keyword-digest` | **Diagnostics usability (Item Z):** `/api/diagnostics/keywords?digest=1` — aggregates + top-N sample instead of the 60 MB full log; default byte-unchanged | #224 | 1307 passed |
| — | ~~#226~~ | ~~`claude/solo-b2-fixity-audit`~~ | ~~B2 fixity audit~~ | — | **CLOSED — redundant** (B2 already shipped at 0.09; hand-verify caught the dup) |
| 5 | **#228** | `claude/solo-item-y-bar-charts` | **Charts ruling (Item Y):** n<10 → honest BAR graphs (amends invariant #16); baseline-honesty resolved | #225 | 1308 passed |
| 6 | **#231** | `claude/solo-convergence-endpoint` | **Flagship substrate:** `GET /api/insights/convergences` exposes `find_convergences` read-only | #228 | 1308 passed |

(#226 was re-based out: #228 and #231 were re-pointed onto #225 so nothing redundant reaches `0.09`.)

## Dependencies & guarantees
- **#222 ⟂ the code stack** (docs-only; touches no code/`CLAUDE.md`) — merges any time.
- **#223 → #224 → #225 → #228 → #231** share `index.html` / locales / `CLAUDE.md` /
  diagnostics+insights — strict number order; each diff is only its own increment.
- No migrations, no network/security/encryption surface, **no invariant weakened**
  (invariant #16 was AMENDED by ruling, with its test updated in the same PR). No
  composite scores introduced (every new endpoint carries method+caveat, counts only).
- New locale strings AI-drafted (flagged for native review), English authoritative,
  Arabic RTL. i18n stayed 100% ×12 throughout.

## The honesty record (the judgment calls — read `SOLO_SESSION_DECISIONS.md`)
- **Item H (PR4 planned)** was found ALREADY shipped at HEAD → **cancelled**, not
  shipped as a redundant fix (D-06 / OO-D14-012).
- **B2 fixity (#226)** was built then found to **duplicate** an existing 0.09 feature
  (`src/verification/fixity.py` + `/api/integrity/fixity` + the `runFixity()` UI) →
  **closed + re-based out** (D-10). Both are the verify-before-implement lesson working.
- **Item Y baseline-honesty** (was deferred D-04) → **resolved + shipped** (#228):
  bars anchor to the labeled baseline (true-zero for counts, window-min for levels)
  with a value-cap so no point is invisible.

## Remaining work (NOT done this session — with the honest reason each was not)
The backlog is genuinely many sessions; "everything" cannot land in one. What's left,
grouped by *why* it wasn't done autonomously:

- **Needs a maintainer ruling (Class C — must not decide alone):** the convergence
  **watch-rule alert engine** (its UX); the **"Trust" tab dissolution** (Item N, "help
  me decide"); the **two-analysis-windows consolidation** (canonical-window choice);
  the **newsletter scraper** / encryption-recovery questions; custody-on-ingest default
  flip; the privacy-headline final wording; the version/branding 0.0.9→0.1 sweep.
- **Needs a browser to verify (frontend, visual):** the large UI flagships — the
  analysis-window/reader-tabs build-out, the **convergence frontend view** (substrate
  now shipped; convergences already surface on Home via the producer), the
  **temporal-map linear/log scale toggle**, the **agenda content** (recurrence, world
  calendars, El Niño month-span banners, astronomy-as-default-events),
  Home-cards-all-clickable. Shippable but should be visually field-tested.
- **Needs network / the maintainer's machine:** the de-US-centring **Wikidata gap
  run**; the **dead default-feed prune** (the google-hol-* robots-disallowed claim is
  unverifiable here); the 100k-scale measured run; translated-docs drafting.
- **Large new verticals (multi-session each):** elections/civic, official-statistics
  ingestion, mass `.eml` newsletter import, Tor integration, the Open Commons Mirror.
- **i18n long-tail:** ~337 chrome strings remain untranslatable; AI-drafting thousands
  ×12 in one PR risks quality — best done in reviewed, themed batches.

## Acceptance per shipped PR
- **#222:** RC rows reconciled match code; README sidebar matches the nav; audit
  artifacts present; suite green.
- **#223:** airplane-on chip reads "Collecting paused" (grounded, spinner stopped),
  never green; invariants green; i18n 100%.
- **#224:** collapsed rail exposes a translated "Expand sidebar" affordance; #2 intact.
- **#225:** `?digest=1` returns aggregates + top-N sample + `keywords_digest`; default
  byte-identical; new test green.
- **#228:** both renderers render n<10 as labeled-baseline bars with a value-cap;
  invariant #16 updated; caveat string gone.
- **#231:** `/api/insights/convergences` exposes the honest gates + caveat; the
  distinct-sources independence gate flows through the API (test-proven).
