# The delegated 0.4 re-walk — 2026-09-27 (rows H, I, J, L, M, N, O, P, S, T, U, and R)

The first delegated walk (`../delegated-clickthrough-2026-09-26/`, build `462145c`) failed nine
of eleven rows on 115 confirmed defects. The maintainer ruled that every one is fixed before the
tag (`R36`). The fixes landed in PR #1191, batches B1 to B19. This folder is the walk that checks
them, on the fixed build. It also holds the first Claude walk of **row R** (the five maps), whose
click-through clause stayed in `0.4` when Q803's OSM default moved to `0.5` (`PF06` = a, 2026-09-27).

**Verdict: no row closes yet.** The fixes held: of the 234 first-walk defects the walkers
checked (each row's own, plus other rows' defects on surfaces it walks), 227 are fixed, 3 are
still present (row M's M1, M7 and M14, each partly fixed) and 4 could not be checked in a sandbox.
Every walkable step of rows H, I, J, L, O, T and U passes. Rows M, N, P and S each fail one to
three steps, and row R fails on 2 P2 map defects. But the walkers were told to be as demanding as
the first walk, and on surfaces the first walk only skimmed they found more. An independent
re-checker reproduced every item on its own fresh instance: **119 confirmed items, 1 P1, 23 P2
and 95 P3**. None was judged a harness artifact or by design. Some are listed on several rows
(the Home strip's «server busy», the untranslated briefing prose, the Wikipedia wizard's host line
in Arabic), and 17 are a failing step that restates a defect on the same row, so there are fewer
distinct defects than rows in `defects.csv`.

## How it was run

Exactly as the first walk (see its README), with these differences:

- **Build:** a read-only worktree at `0deff9c4` (PR #1191 after batch B19). Row R ran at the same
  commit; its `src/` is identical to the PR head `60aaf429`.
- **Process:** one workflow of 22 agents for rows H to U, and one of 2 for row R. One walker per
  row re-ran the first walk's steps (`../delegated-clickthrough-2026-09-26/rows/<ROW>.json`),
  checked every confirmed first-walk defect of its row and every other row's defect on a surface
  it walks, and reported anything else broken. An independent re-checker then reproduced each
  failure on its own instance, read the code, and gave a verdict with a root cause.
- **Row R** had no first walk. Its walker fed all five maps data (the app's own
  `parse_worldbank` + `store_figures` for 229 countries, and located articles through
  `index_article`), so no surface was judged on an empty screen, then measured each map scoped to
  its own host: Equal Earth, 229 countries, 28 contested areas, the legend, the caveat, the
  34-option worldview picker, in en, fr, ar and zh and at 375 px.
- **Kept here:** each row's full walk and re-check (`rows/<ROW>.json`) and the confirmed items
  (`defects.csv`, ids `<ROW>-<n>`, with repro, expected, actual, the re-checker's evidence, root
  cause and suggested fix). The Playwright scripts and screenshots stayed in the session's
  scratch folders; the first walk's scripts reproduce the same steps.

## The rows

| Row | Steps | First-walk defects | New confirmed items | Click-through clause |
|---|---|---|---|---|
| H | 8 pass · 2 not measurable | 19 fixed | P2 2 · P3 3 | Steps pass. The lane-host bubble is now drawn over the consent popup for all 15 lanes. Open on the Home strip's false «server busy» and the untranslated topic-discovery line. |
| I | 13 pass · 1 not measurable | 25 fixed | P2 1 · P3 7 | Steps pass. Open on the «Already judged here, kept» over-count and seven wording or RTL items. |
| J | 7 pass · 2 not measurable | 14 fixed | P2 1 · P3 3 | Steps pass. Open on a reload during the corpus phase silently dropping the large-data copy. |
| L | 14 pass | 26 fixed | P2 2 · P3 8 | Steps pass. Open on the Home Lead cards' English prose and eight translation or layout items. |
| M | 6 pass · 3 fail · 2 not measurable | 21 fixed · 3 still present · 2 not checkable | P2 7 · P3 9 | **Fails.** M1 (a folded keyword can still resolve to its emptied row), M7 (the Explore mind map and word cloud draw bare foreign words) and M14 (briefing prose) are only partly fixed. |
| N | 10 pass · 1 fail · 2 not measurable | 21 fixed · 1 not checkable | **P1 1** · P2 3 · P3 4 | **Fails** N11. The P1: the trend's Counts mode labels mention counts as articles, about 3× the real article count. |
| O | 14 pass · 4 not measurable | 21 fixed · 1 not checkable | P3 6 | Steps pass. Open on six P3 items. |
| P | 9 pass · 2 fail · 1 not measurable | 23 fixed | P3 6 | **Fails** P11 (the Wikipedia wizard's host line in Arabic) and the 375 px pass (the Home strip in French). |
| S | 10 pass · 1 fail | 15 fixed | P3 12 | **Fails** the 375 px pass, a regression from the S8 fix. |
| T | 9 pass · 2 not measurable | 21 fixed | P2 1 · P3 8 | Steps pass. Open on nine items. |
| U | 13 pass · 2 not measurable | 21 fixed | P2 1 · P3 10 | Steps pass. Open on eleven items. |
| R | 17 checks pass · 8 fail | (first walk) | P2 5 · P3 19 | **Fails.** Geometry passes on all five surfaces. Contested-area names are English in every locale (the renderer reads `OOI18N.lang`, which does not exist), three of 28 areas name one claimant, a worldview chosen on one map does not reach the others, and two maps do not follow a language switch. |

## What the re-walk says about the process

The first walk's 115 fixes held, and the rows' own steps now pass almost everywhere. The new
items are mostly the same classes the first walk found (a string that is not keyed, a surface
that does not repaint on a live language switch, a path or host drawn right to left, a nowrap
item at 375 px) on surfaces a first pass had not reached. The plan for the next walk of a row is
to check these fixes and the row's steps, not to start a fresh hunt, so that the loop converges.

Row R also cites «the ooMap embed on When / Where stays (Q1150)». That embed was never built:
`docs/ledger/shipped.csv` (2026-09-10) records it as scoped, not built, and Q1150's «Keep» kept
the plan. The gate's row R text is corrected to say so.
