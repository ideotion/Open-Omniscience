# S05-09 — The UI shell: rings, the handler retirement, the theme cull · 0.5, `RELEASE_0.5_GATE.md` row I

> **Scope:** the sidebar / tab registry (`src/static/index.html`, `app-shell.js`, `app-boot.js`), a Ring
> dial in Settings, the first-run wizard's depth question, the Activity Ledger's grammar (Graft 2), the
> inline-handler retirement across `index.html` + `app-*.js` with its ratchet, the CSP at
> `src/api/main.py:571–572`, the theme catalogue in `src/static/app.css` and its pin in
> `tests/test_repo_invariants.py`. Must NOT: amend invariants #2, #4, #13, #20 or #22 on a session's own
> word (the design plan proposes them; only #12 was amended on 2026-09-15), drop `'unsafe-inline'` from
> `style-src` (Q1127 is about handlers, i.e. `script-src`), translate Help's body (0.6), delete markup an
> invariant test pins.
> **Implements:** Q1120, Q1121, Q1123, Q1127 (none ⛔, none 🔒).
> **Gated on:** nothing PENDING; the design of record
> `docs/design/UI_COMPLEXITY_AND_AUTOMATION_PLAN_2026-09-08.md` §6–§8; the 2026-09-09 axe sweep record.
> **Sequencing:** the ratchet FIRST (every other 0.5 slice adds markup); the cull and its test pin in ONE
> PR; the Ring dial after the ratchet; the CSP drop last, at count zero.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q1120** — **(a)** «(a) "Rings, not gates" as the spine (a Ring controls what is pinned, never what is
  reachable) with the two grafts from "Works while you sleep".»
- **Q1121** — **(a)** «(a) Standard (Ring 1) when the depth question is skipped; Essentials only by explicit
  choice.»
- **Q1123** — **(b)** «(b) Cull the near-duplicates to ≥ 10 with an amendment to invariant #12.»
  [placement: amends invariant #12 — CLAUDE.md amended 2026-09-15; the test pin moves in the same PR as
  the cull, not before]
- **Q1127** — **(a)** «(a) Fund a retirement slice in 0.5 with a ratchet that fails on any new inline
  handler; drop `'unsafe-inline'` when it reaches zero.»

**Register round 2026-09-15 (H3, H4, H5):** H4 = `default`: one module per slice, `app-boot.js` first — the method
for Q1127 = a. H3 = `default`: remove `#ins-term` + `exploreTerm` behind the omnibar-absorption test — proposed for
this slice (`RC08.5`). H5: the 3D explorer is retired in favour of the Observatory (no build).

## 2. Where this stands in the tree — the staleness guard, with anchors

- Inline handlers: 335 in `index.html` + 278 across `app-*.js` = 613 on 2026-09-11 "with an explicit
  handler-name pattern", up from 590 five days earlier (`OPEN_QUEUE.md`, register H4). Re-measured in this
  brief with a quoted `on<event>=` attribute pattern over a 40-event list: 336 + 266 = 602 (grep-verified:
  a Python scan of `src/static/index.html` and `src/static/app-*.js`) — the two patterns differ, so the
  ratchet publishes ONE pattern and pins ITS count. The CSP: `script-src 'self' 'unsafe-inline'` ("UI is
  inline-heavy; nonce-based CSP is future work") and `style-src 'self' 'unsafe-inline'` at
  `src/api/main.py:571–572` (grep-verified).
- Themes: 16 `html[data-theme="…"]` blocks in `src/static/app.css` — arctic, aubergine, contrast, cyber,
  dawn, forest, garnet, light, midnight, mint, mist, paper, sepia, slate, solar, terminal — plus Ink in
  `:root` and System JS-only = 17 named themes (grep-verified; invariant #12); the pin
  `assert html.count('html[data-theme="') >= 16` at `tests/test_repo_invariants.py:2166` (grep-verified).
  The audit's measurement (`OPEN_QUEUE.md`, 2026-09-08, Q-VIS-4): slate, midnight, aubergine, garnet (and
  mildly forest) cluster as accent presets of one dark base; light / mist are near-duplicates.
- The IA design of record, `docs/design/UI_COMPLEXITY_AND_AUTOMATION_PLAN_2026-09-08.md` (grep-verified
  `sed -n '168,232p;256,262p'`): §6 line 170 the spine ("Rings control what is *pinned*, never what is
  *reachable*"; ethical and safety surfaces pinned identically at every tier); lines 174–175 the grafts —
  Graft 1 the Explore merge (Search + Analyze → one sidebar surface), Graft 2 the Ledger's grammar-enforced
  vocabulary (every automated action writes one append-only entry in a fixed shape); lines 190–201 the ring
  table (Home, Feed, Trust, Task Manager at Ring 0; Explore, Insights, Observatory, World map, Governments,
  Agenda, Indices, Commodities, Library at Ring 1; Settings tunables at Ring 2); §7 lines 210–222 PROPOSES
  amending invariants #2, #4, #13, #20 and superseding #22; §8 line 228 Phase 2 = `Settings → General →
  "Interface depth: Essentials · Standard · Full"`, existing installs defaulting to Full; line 230 Phase 3
  = the Explore merge ("real UX design work").
- No interface-depth or ring setting exists (grep-verified:
  `grep -rn -i 'interface depth\|interface_depth\|ui_ring' src/` → nothing). The first-run entry is the
  guided wizard (`app-backup.js:1947–1965`, ruled 2026-06-13; `firstRun` at `:1961`); the airplane
  coachmark at `index.html:3175` (grep-verified).
- The axe sweep shape: the audit's viewport table at `docs/audit/11_VISUAL_UI_AUDIT_2026-09-08.md:158–166`
  (375 × 812, 768 × 1024, 1024 × 800, 1440 × 900, 1920 × 1080); `LESSONS.md` 2026-09-09: zero violations
  at 1440 × 900 and a CRITICAL on every surface at 768 × 1024 — widen a sweep before deepening it. Tests
  present: `tests/test_theme_contrast_and_donut_guard.py`, `tests/test_gui_alternatives.py` (invariant #30:
  8 skins × the theme palette), `tests/test_ui_walk_playwright.py`.
- Lesson (`LESSONS.md`, 2026-09-09, the `onclick="cap"` grep): a handler pattern that needs the whole
  opening tag undercounts — the ratchet's pattern is proven against the known count and mutation-checked.

## 3. Slices — what to build, in order

### S1 — The inline-handler ratchet (Q1127)
- **What:** one published pattern (its event list in the test), the count pinned per file at the measured
  number with ZERO slack, failing by name on any new inline handler; a conversion lowers the pin in the
  same PR.
- **Acceptance:** the ratchet exists at the measured count (the gate's clause); mutation-checked (add one
  `onclick=` → reddens by name; remove one → the pin must be lowered).

### S2 — The retirement and the CSP drop (Q1127)
- **What:** handlers converted to `addEventListener` module by module (the GUI gallery's own rule,
  invariant #30), each PR lowering the pin; at zero, `'unsafe-inline'` dropped from `script-src` ONLY;
  if a residue remains, the row records the measured residue and why (the gate's clause).
- **Acceptance:** count zero or the recorded residue; the CSP change Chromium-verified across the themes at
  three widths (S4's record); `node --check` on every converted block.

### S3 — The theme cull with invariant #12's pin (Q1123 = b)
- **What:** re-measure the 17 themes' panel / card / border / background distances (the audit's method);
  cull the near-duplicates to ≥ 10; name each culled theme with its nearest survivor (the gate's clause);
  lower the `>= 16` pin at `tests/test_repo_invariants.py:2166` in the SAME PR; map a stored culled-theme
  preference to its survivor — never silently to the default; the GUI-gallery test and the contrast guard
  green over the survivors.
- **Acceptance:** the culled → survivor table in the PR body; the pin and the catalogue change in one PR.

### S4 — The Ring dial and the skipped default (Q1120, Q1121)
- **What:** `Settings → General → "Interface depth: Essentials · Standard · Full"`; existing installs
  default to Full (nothing un-pinned on upgrade); a new install's skipped depth question → Standard (Ring
  1); Essentials only by explicit choice; a Ring controls what is PINNED, never what is REACHABLE — the
  palette, Search and a permanent "Show more (N surfaces)" row keep every surface reachable; the
  ethical / safety surfaces pinned identically at every ring. Essentials un-pins Ring-1 tabs, which
  touches invariant #2's "lists all tabs": the PR carries the amendment text citing Q1120 = a and Q1121 =
  a for the maintainer's review; the Essentials ring is not merged before that word (§6).
- **Acceptance:** the dial driven at all three depths in the Chromium record in `en` and `ar`; the "Show
  more" row never collapses to an icon without text; strings ×12.

### S5 — Graft 2: the Ledger's grammar (Q1120)
- **What:** every automated action writes one append-only entry in the fixed shape of the plan §6
  (`what_happened / why / touched / caveat / budget / …`) — a record of decisions (invariant #8: data, not
  plumbing) — shown as a lens inside the EXISTING task-manager window, so invariants #4 and #20 are not
  touched; vocabulary grammar-enforced by a test.
- **Acceptance:** an automated action without a Ledger entry fails the grammar test; strings ×12.

### S6 — Graft 1: the Explore merge (Q1120) — after the maintainer's word
- **What:** Search + Analyze as one surface (the plan's Phase 3). It supersedes invariant #22 ("never a
  sidebar entry, retired 2026-06-20"); Q1120 = a owes that amendment, but the 2026-09-15 turn amended only
  #12 — the session records the question in `OPEN_QUEUE.md`, writes the amendment text, and builds Explore
  only once the maintainer confirms in review.
- **Acceptance:** the confirmation recorded in `CLAUDE.md` on the maintainer's word; then the merged surface
  in the Chromium record.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the
ratchet's mutation check (S1); `node --check` on every converted `<script>` block; the three i18n gates; the
whole-tree guard set (`tests/test_repo_invariants.py` carries the pins this slice moves); the GUI-gallery
test and the contrast guard over the survivors; the Chromium click-through across the 17-then-≥ 10 themes at
the three widths of the 2026-09-09 sweep (read its record for the exact set; the audit table lists five)
with an axe pass at each — the gate's clause; the dial at Essentials / Standard / Full in `en` and `ar`
(the RTL sidebar); stamped "Chromium-verified (remote sandbox) · awaiting human UX pass".

## 5. Operator steps

1. The click-through of the dial, the culled themes and the CSP-dropped build (Q1128 = a) → the record.
2. In review: the maintainer's word on the invariant amendments the spine requires (#2 for Essentials, #22
   for Explore; #4 / #13 / #20 only if the session finds them unavoidable) — a ruling the session then
   records in `CLAUDE.md` and `OPEN_QUEUE.md` in the same turn.

## 6. What this slice may not decide

- The invariant amendments the plan §7 proposes (#2, #4, #13, #20, #22): none recorded; the session ships
  what needs none (S1–S3, S5, the dial at Standard / Full) and asks for the rest before un-pinning a tab
  or merging Search into a sidebar surface.
- `style-src 'unsafe-inline'` — not ruled; untouched. Which themes are culled — measured, then named.
- The exact "Show more (N surfaces)" wording; the Explore surface's result model (the plan's own warning);
  the Trust group's Ring-0 slots (plan §10 item 3 — not asked by the sheet); Help's body ×12 (0.6, Q1122).

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
