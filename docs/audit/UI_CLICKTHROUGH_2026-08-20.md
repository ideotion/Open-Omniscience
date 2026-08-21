# UI click-through 2026-08-20 — the browser-verification matrix expansion

**Status: EXECUTED.** This is the follow-up the 2026-08-13 report's §8 ordered worklist asked
for: gate row 8 closed on 2026-08-13 against its own literal wording, and the fuller matrix —
the standalone Reader, the a11y axis, the 17-theme floor, the lens/sub-panel drills, the
automatable honesty-rule checks — was recorded as a **stretch target, not a condition**. This
session executed that stretch target and fixed the two findings the worklist named with a
defined shape (the 375px top-bar overflow; the post-import screen's untested content path).

Artifacts: this report ·
[`ui-clickthrough-2026-08-20/findings.csv`](ui-clickthrough-2026-08-20/findings.csv) ·
[`coverage.csv`](ui-clickthrough-2026-08-20/coverage.csv) ·
[`evidence/`](ui-clickthrough-2026-08-20/evidence/) — the run produced 69 evidence files;
following the 2026-08-13 precedent, the **committed** set is the 15 the findings and this
report cite as load-bearing (the T1 before/after pairs, the mid-drag greyscale capture,
the state-A virgin flow, the state-D post-import pair, the Reader, the RTL locale, the
state-B empty state, the bulletin review screen); the full set regenerates by re-running
`scripts/ui_clickthrough_run.py`. The runner remains merged source
(`scripts/ui_clickthrough_run.py` over `src/monitoring/ui_walk.py` +
`ui_walk_playwright.py`), now covered by **46 regression tests**
(`tests/test_ui_walk_playwright.py` 30 · `tests/test_ui_walk.py` 9 ·
`tests/test_ui_matrix_20260820.py` 7), re-runnable by any future session.

### Methodology

**Four** live app instances (the 2026-08-13 run's three, plus a new one), each a fresh
`OO_DATA_DIR` with `OO_NO_SCHEDULER=1 OO_LLM_AUTOSTART=0 OO_AIRPLANE_SOCKET_GUARD=1`
(airplane engaged throughout):

- **STATE A** (virgin, 8001) — the first-launch lifecycle (language → legal → create),
  wiped and relaunched fresh before the final walk (its virginity is single-use).
- **STATE B** (empty, catalog-seeded, 8002) — empty-state honesty. `OO_DB_PLAINTEXT=1`.
- **STATE C** (populated, 8000) — the 453-article synthetic corpus seeded through the real
  `index_article` chokepoint (`scripts/ui_clickthrough_seed.py`), extended this session with
  a **deduced-future-event specimen** (3 articles / 2 sources naming 2026-10-12, through the
  real date extractor) so the T5 agenda drill has something a seeded corpus can exhibit.
- **STATE D** (import fixture, 8003) — **new (T2)**: a fresh instance that receives a REAL
  volume-backup import through the real Import dialog, so the post-import screen's CONTENT
  path renders a genuine run's summary. The artifact is a `--mini` seeded corpus (24
  articles, 4 languages, qualified sources — the same chokepoint discipline) exported by the
  real `write_volume_backup` engine; nothing touches any live corpus at any point.

The final walk: 53 walk steps, **179 coverage rows** (171 verified · 6 partial · 2 blocked —
every non-verified row carries its reason in the CSV), **23 findings** (15 positive
confirmations · 7 P2 · 1 P1 re-check · **0 new P0/P1 outstanding**). Axes: the 5 flagship +
9 backlog surfaces, every Analysis/Insights/Settings/Library subtab + the World map's 4
lenses, **17 themes** (T4), 4 breakpoints + a **per-flagship-surface 375px walk** (T1's
acceptance), 4 switch-tested locales (en/fr/ar/zh — the brief's floor; ja/hi/bn additionally
rendered by the T7 uppercase audit), the Reader's 11 tabs (T3), five lens/sub-panel drills
(T5), the a11y axis (T6), and five automatable honesty-rule checks (T7).

**The honesty-critical result, stated first: across the entire run, zero requests reached any
host other than 127.0.0.1.** Every state booted and stayed offline for its whole walk.

**A methodology caveat in the 2026-07-22 tradition:** this harness's own request volume can
trip the app's rate limiter (a feature under test, not noise). Two artifacts of that are
recorded as harness observations, not app findings: the AI pill's `live-state` row reads
`partial` because the SPA's single boot-time `/api/llm/health` read raced the walk's storm
and the pill stayed unpainted for that page's life (a fresh, quiet page paints `ai-off` in
~2s — verified live, three times); and an earlier discarded run lost its whole Reader drill
to one 429 that outlived a 12s backoff (fixed by discovering the article id from the DOM the
browser already rendered). The single-shot-at-boot health read with no periodic re-poll is a
real liveness edge worth knowing about, but the load pattern that exposes it is this
harness's own, so it is not counted as a finding.

---

## 1. T1 — the 375px overflow, fixed and walked on all five flagship surfaces

The 2026-08-13 report's P1 recorded `scrollWidth=452` at 375px and attributed it to "the top
bar's contents cumulatively". **Measured live this session, the mechanism is narrower and
different** (the standing re-derive-the-mechanism rule): `.topbar` itself wraps fine — the
2026-07-22 fix holds — and the one universal culprit is `#statusCluster`'s nowrap min-content
(the 160px `.act-host` slot + 110px `#health` footprint + 46px `#llm` + gaps = 434px),
present exactly while the activity chip is visible, which is why the symptom looked
intermittent. A second, agenda-only overflow (the tab-page grid's content-sized `auto` track
resolving to 486px from the controls' intrinsic widths) was masked behind it.

**Strategy: collapse + wrap at ≤600px** (the existing mobile breakpoint), chosen over
hiding controls (controls are commitments) and over fluid footprints (invariant #3's real
property — a text change never reflows its neighbours — holds per breakpoint only while the
footprints are constants). The phone block: the status cluster wraps internally; `.act-host`
and `#health` collapse to smaller *constants* (`#health` ellipsizes, full text on its hover
title); the tab-page grid track pins to `minmax(0,1fr)`; row children get `min-width:0` and
form controls `max-width:100%`; `#agenda-monthbar` wraps (`!important` beats its
non-important inline nowrap). Two traps are recorded in the CSS comments and pinned OUT by
comment-stripped guards: `contain:inline-size` zero-widths any no-grow auto-basis wrapper
(measured: the Insights Explore button protruding from a 0px box), and a percentage
`max-width` is ignored during ancestor intrinsic sizing (why the grid-track clamp is the
fix, not `max-width:100%` alone).

**The walk then found one more, on the brief's own acceptance axis:** navigating each
flagship surface and measuring at 375px caught `source_management` at 478px — the
discovery-candidates table in `#candidates-list` has no overflow wrapper (`#src-table` has
one), so its 443px min-content scrolled the page. Fixed with a generic phone rule: every
Settings > Advanced section table becomes a self-scrolling block (the stylesheet's own
`.prose`-table convention), honouring the repo-wide rule that wide content scrolls inside
its own container, never the page.

**Acceptance met:** the final walk stamps zero horizontal overflow at 375px on **all five
flagship surfaces** (`ui-clickthrough-topbar-fixed-375-{home_leads, analysis_window,
post_import_screen, source_management, diagnostics_panel}`), plus the four global
breakpoints. Before/after screenshots: `evidence/before-375-{home,agenda}.png` →
`after-375-{home,agenda}.png`. Guards: `tests/test_ui_matrix_20260820.py` (5 T1 guards, each
mutation-checked; comment-stripped so the CSS comments recording the traps cannot satisfy or
trip them).

A harness lesson worth its line: the first walk of this acceptance NAVIGATED at 375px (the
viewport the previous check left) and three surfaces read blocked — the settings gear is
legitimately off-canvas below 600px (invariant #2's own floor). The claim under test is "the
surface, once open, does not overflow at 375", not "navigation at 375" — the walk now
navigates at desktop width and then measures.

## 2. T2 — the post-import screen's real content path (state D)

The 2026-08-13 run's only P0 was this surface: no import had ever run under the harness, so
the redesigned post-import screen had never rendered its content in a browser. State D
closes it end-to-end through the REAL flow: scan the artifact folder in the real Import
dialog (`ux-import`), check the corpus member, enter the passphrase, run, and read
`#ux-imp-summary` when the queue lands.

**`post-import-redesign-renders-live` (POSITIVE):** all six content markers of the
2026-07-20 post-import redesign rulings render from a genuine import — the Articles-first
headline ("grew by … articles"), the labeled "database records, all types" row-sum, the
BEFORE/AFTER corpus delta, qualification carried (the criteria version shown), the
work-induced indexing note, and the additive-restore statement ("replaced or deleted:
nothing"). First line: `✓ Import successful`. The flagship surface's own anchor moved from
the by-construction-empty `#ux-imp-summary` (which Playwright reads as not-visible — the
2026-08-13 P0's mechanical half) to the dialog itself, with the note in
`src/monitoring/ui_walk.py` explaining the split: the flagship row claims REACHABILITY, the
state-D fixture claims the CONTENT.

The fixture is reusable: `scripts/ui_clickthrough_seed.py --mini` builds the import-source
corpus; the walk takes `OO_UIWALK_IMPORT_ARTIFACT`/`OO_UIWALK_IMPORT_PASS` and self-skips
with an honest blocked row when unset (recorded, never silently skipped).

## 3. T3 — the Reader, the largest named-surface gap, closed

`reader_surface(article_id)` (new in `src/monitoring/ui_walk.py`) reaches the standalone
server-rendered page at `/api/articles/{id}/view` — a navigation path outside the SPA's
nav/subtab grammar entirely. The walk discovers a real article id from the rendered DOM (a
reader link on the analysis Articles list — zero extra requests) and drills:

- **All 11 tabs individually** (`read · summary · translation · keywords · mindmap ·
  sentiment · subjectivity · related · source · links` + the pane content read per tab) —
  every pane renders, zero console errors. **The Loaded-language pane** (the brief's named
  check, `data-rtab="subjectivity"`) renders.
- **The two-class provenance headings** — "From the source" and "Deduced by this app — less
  reliable" both render; the AI-derived third class is absent because no `ai_keyword` rows
  exist for the article, which is the honest state, not a defect (the note says so).
- The reader joined the **axe matrix** (one serious finding filed, §6) and the **keyboard
  traversal** (22 stops, 4 distinct, zero focus stops without a visible indicator).

`ui-clickthrough-reader-covered` (POSITIVE) closes the 2026-08-13 report's single largest
named gap.

## 4. T4 — the theme floor: 5 → all 17, and the find that pays for the axis

Both live contrast checks now run on **every one of the 17 concrete themes** (ink slate
midnight arctic cyber forest aubergine garnet solar sepia terminal contrast light mist dawn
mint paper — the full light cluster included, clearing the brief's ≥9 floor to the full
set). The `--warn-fg` warn-pill fix and the `--caveat` fix hold on all 17 (worst cases:
pill.warn 5.78:1 on solar; card-caveat 6.29:1 on paper — the full 34-row table is in
coverage.csv).

**The widening immediately found what every 5-theme run had missed.** The AI pill's
`ai-off` "AI" label was raw `var(--err)` over the rule's own 8%-err pill tint — computed per
theme from the declared tokens, that fails WCAG AA 4.5:1 text contrast on **13 of 17
themes** (worst: solar 2.41:1, dawn 3.80, sepia 3.94). The check that surfaced it was itself
a lookalike first (§9a — it accused the `--warn-fg` token, which was innocent), and the
correctly-scoped measurement then stood. **Fixed** with the established theme-derived
repair — the same mix-toward-`--fg` the pill's diagonal bar and state marks already carry:
55% is the smallest 5-point step clearing 4.5:1 on every theme (worst case 4.82:1, solar),
the red hue survives, and the state was never colour-only anyway (the bar + hover title
carry it; the 2026-08-02 ruling's own design). Guard: mutation-checked both directions in
`test_ui_matrix_20260820.py`. The sibling `ai-starting` state's `var(--accent)` label is
**unmeasured** (the state is unreachable on this backend-less sandbox and was never forced —
an untested path is not a pass); it is on the follow-up list.

## 5. T5 — the lens and sub-panel drills

**(a) World map in-panel sub-controls** — one level below the 4 lenses the 2026-08-13 run
walked: all four dimension-picker buttons (sources/articles/keywords/**sentiment** — the
diverging-scale dimension) re-render the map with zero errors; granularity
Continent↔Country toggles with `aria-pressed` state; the Places overlay arrives WITH its
"deduced, never confirmed" caveat visible (informed consent travels with the layer); the
Signals layer renders its in-map focus slider, driven by KEYBOARD (ArrowLeft ×5 — the real
user path, never a scripted `.value` write).

**(b) Task manager sub-panels** — the ledger's named four (Active·Queue·System·Schedule)
no longer exist by those names: the page carries **five** (`processes · performance · queue
· schedule · history`), each drilled individually — panel visible, all others hidden, real
content read (the rename is recorded here per follow-the-anchor; the capability set is a
superset of the ledger's four).

**(c) The AI pill / Settings-AI third state** — the pill's real state on this backend-less
sandbox is `ai-off`; `ai-starting` and serving are **honestly blocked** ("unreachable
without a local backend — recorded honestly, never forced via a class edit"). The
Settings > AI panel names its prerequisite/backend state rather than drawing a decoy
roster (the 2026-08-09 panel-ordering lesson, verified live). The pill's `live-state` row
in the final walk is the §-Methodology race artifact, not a state misread — the classifier
now waits for a painted state class and refuses to read the static initial as "serving"
(the second walk's misread, fixed).

**(d) The Bulletin — Settings section AND the review screen, via the real path.** The
hardware gate refuses on this GPU-less machine (the gate text renders); the walk then takes
the REAL operator path: `llm_allow_impractical_hw=true` via the settings API (the shipped
override, not a DOM hack), the controls appear, **a real Layer-A edition generates**
(deterministic SQL — no model call), the edition lists ("COVERS THROUGH 2026-08-19 ·
weekly"), and **the review screen opens and renders** — browser-verified for the first time
(`ui-clickthrough-bulletin-review-covered`, POSITIVE). The override is flipped back and its
restoration is its own coverage row, so no later check ran under a mutated setting.

**(e) Agenda glyphs + deduced-event provenance — and a real find.** The month grid's moon
glyphs render with their method+accuracy titles (2 moons, both titled). The deduced-event
drill initially found n=0 **with the seeded specimen live in `AG.events`** — the mechanism:
`#agenda-subonly` ("subscribed only") defaults CHECKED and `agFiltered`'s bypass named only
`imported`, so corpus-DEDUCED events — whose synthetic "deduced" calendar can never be
subscribed — were invisible in **every agenda view at default settings**, while the category
filter still offered "deduced" as an empty lens. The 2026-06-16 design maps them "like
imported events"; the bypass now carries both (`e.imported || e.deduced`), verified live at
the default checked state (pill renders, titled), guarded by a mutation-checked
comment-stripped source test. A filter must never offer a category its default state
structurally suppresses.

## 6. T6 — the a11y axis, built from zero

**axe-core 4.13.0 vendored locally** at `scripts/vendor/axe-core/` (MPL-2.0, GPL-3.0-
compatible; fetched once from the npm registry and verified against the registry's own
attested sha1+sha512 digests before extraction; sha256-pinned in
`configs/external_artifacts.yml` as `vendored-axe-core` in the same commit, per the
external-artifact rule). It is harness tooling under `scripts/vendor/` — deliberately never
`src/static/`; the app gains no dependency and nothing fetches at runtime.

**axe over six surfaces** (home · settings-models · agenda · analysis · tasks · the reader):

- **Fixed in-session:** `aria-tooltip-name` [serious] on `#oo-tip` — the shared hover
  bubble idles EMPTY at `opacity:0` with `role="tooltip"`, still in the accessibility tree,
  so a nameless tooltip was exposed on every page (three surfaces flagged the same element).
  It now carries `aria-hidden="true"` while idle; `show()`/`hide()` toggle it, so when
  visible its textContent IS its accessible name. Verified live (idle→hover→leave) and by
  the final walk's axe pass: the rule is gone from all six surfaces.
- **Filed (P2 each, real axe targets in findings.csv):** `color-contrast` on Home's
  card-back chips/flip-hints and `.tier-badge` (×6 nodes); `link-in-text-block` on the
  agenda list's inline `.ext-link`s (×124 — links distinguishable only by colour inside
  text); `nested-interactive` on `.an-tab` (the close control inside the tab button);
  `color-contrast` on the tasks page (`#llm`, `#tm-conn`, `#jobs-body > .muted` — the tasks
  top bar grounds differ from the panel the SPA checks measure against); `color-contrast`
  on the reader (`.deduced > h3`, `.dup-pill`). Each sits outside this session's territory
  or is a design call (the agenda one is a convention question — underlines vs the current
  hint styling); none is fixed blind.
- **Clean:** settings-models — zero serious/critical.

**Keyboard-only traversal** (new driver instrument, hermetically proven on discriminating
fixtures first): Home — 40 stops, 11 distinct, **zero stops without a visible focus
indicator**, no trap; the reader — 22 stops, 4 distinct, zero unindicated. **prefers-contrast
emulation** (the G-3 block, measured live under `emulate_media(contrast="more")` rather than
re-read from source): the block applies — hint colour and icon borders measurably change.
The Playwright fact worth keeping: `emulate_media(contrast=None)` is a silent NO-OP; the
reset tokens are `"null"`/`"no-override"` (both behaviourally clear it — probed; the driver
uses the stub-typed `"null"`).

## 7. T7 — the automatable honesty-rule checks

Five of the brief's nine §5 techniques are now standing checks; rule 5 (an untested path is
not a pass) is a discipline this whole report practices rather than a check; **rule 9 —
adversarial screenshot reading — is explicitly out of scope for this runner**: it is a
different posture (independent critics reading pixels), not an assertion a walk can make
about itself.

- **Class-with-no-rule sweep** (the recorded `class="small"` lesson, automated): 15
  used-but-unstyled class names across 4 surfaces; 7 look presentational and are filed as
  TRIAGE CANDIDATES, not verdicts (`ag-evtitle`×153, `an-panel`×13, `adv-collect`×12,
  `bk-context`×6, `tm-panel`×5, `note-amber`, `pal-hint`) — most unstyled names are
  legitimate JS/state hooks (`note-amber`'s styling, for instance, is inline beside it);
  each needs a human read before any rule is added.
- **Greyscale captured MID-interaction**: the ONE live brush-enabled chart (Insights
  explore's per-term trend — the only `ooChart` caller passing `onSelectRange`), reached via
  the real path (a top term through `pickTerm`, the in-chart "Select a period" chip, then a
  real drag), screenshot taken while the mouse button is DOWN, judged at PIXEL level from
  the greyscaled capture: band-region luminance delta **16.7** against a null baseline of
  0.3 — the selection band is visible without colour, measured, not assumed
  (`evidence/greyscale-middrag-brush.png`).
- **RTL bidi isolates by rendered x-position**: the instrument reads per-character
  `Range.getClientRects()` x positions (its discriminating hermetic fixture proves a bare
  offset-joined timestamp genuinely reorders in Chromium and an FSI/PDI-isolated one does
  not). Live under Arabic, two specimens measure MONOTONIC (logical order preserved): a
  date run on Home and the bulletin edition table's `2026-08-19`. Honest limits stated: the
  app's shared formatter localises dates nearly everywhere, so bare-ISO live specimens are
  rare, and the offset-joined class that actually reorders had no live specimen on this
  seeded corpus — that class is pinned by the hermetic test.
- **Uppercase-is-a-no-op across ar/zh/ja/hi/bn**: zero elements carry rank by case alone on
  Home in any of the five locales — every uppercase element also steps on size or weight,
  so hierarchy survives translation (the 2026-08-11 fix, confirmed live per locale).
- **The exact-text-node i18n walker** (fr, over Home/Settings/Agenda): **zero** keyed
  strings rendering as their exact English value — no welded/frozen/unwalked nodes among
  the keyed set on the probed surfaces. (This measures the keyed set; strings with no key
  at all are the 2026-07-28 audit's separate, known gap class.)

## 8. T8 — the two known-open items, re-checked with fresh evidence

- **Governments defaults to Countries, not Law** — confirmed still present live
  (`lands on subtab='countries'`), the known-open 2026-07-22 item, deliberate/documented
  per its triage. Not counted as new; not fixed here (Lane 1 territory).
- **`ins-map-cjk-sentence-keywords`** — **could not be reproduced** against the seeded zh
  corpus (60 pills sampled at Insights > Map, country=cn; none long-unsegmented). This
  matches the 2026-08-13 run's identical non-reproduction, so two independent runs now
  agree: either the seeded corpus's zh yield for this surface is thinner than the original
  2026-07-22 run's, or the underlying gap narrowed. Neither is confirmed — an honest
  non-reproduction twice over, **not** a verified fix; the finding stays formally open on
  its original evidence.

## 9. The harness corrections — five instrument lookalikes, none an app defect

Extending a measuring instrument found the usual crop of ways the instrument itself can
lie; each was found live, fixed, and (where a guard exists) mutation-checked. Recorded
because a future session extending this driver needs the shapes:

1. **The first match of a class selector can be an element whose classes mean something
   else.** `querySelector(".pill.warn")` grabbed the AI pill — which carries `pill warn`
   for footprint styling while its state rules override the colour per state — and filed a
   P1 naming the `--warn-fg` token, whose fix was intact (5.78:1 on the accused theme). The
   check now excludes it (`:not(#llm)`) and measures the pill's state label as its OWN
   claim (which is how §4's real find surfaced).
2. **An anchor on a by-construction-empty element fails the reachability walk it serves.**
   `#ux-imp-summary` is empty until an import completes; Playwright reads an empty
   zero-size div as not-visible. The flagship anchor is now the dialog; state D claims the
   content (§2).
3. **A breakpoint walk that navigates at the small width tests a different claim.** §1's
   lesson — navigate at desktop, measure the opened surface at 375.
4. **A derived CSS selector is the non-unique-needle trap wearing new clothes.** The RTL
   specimen-search derived `td` from the found node — which `querySelector` resolves to
   the DOCUMENT's first `td`, so the reader measured the wrong node and the check found
   "nothing" while two visible specimens existed. The found node is now tagged with a probe
   attribute and addressed by it.
5. **A sidecar API probe shares 127.0.0.1 with the harness's own browser**, so the app's
   rate limiter can 429 it past any polite backoff — article ids now come from the DOM the
   browser already rendered, with the bounded-retry `_get_json` as fallback.

Plus the Python trap that produced two of these twice: in a multi-line
`page.evaluate(f"... {{ ..." "... }}")`, the **plain**-string continuation line's `}}`
stays a literal `}}` (only f-strings collapse braces) — a JS SyntaxError. Fixed in one
evaluate, then found AGAIN in a sibling drill in the same file: fixing a property in one
place is not fixing it.

## 10. Reconciliation against the brief's full matrix

| Axis | 2026-08-13 | This run |
|---|---|---|
| Named surfaces | 9 of 15 full, 5 partial, Reader not at all | **15 of 15 touched**; the Reader fully drilled (11 tabs); all five T5 drills one level deeper |
| Themes | 5 of ≥9 floor | **17 of 17** |
| Locales | 4 (the stated floor) | 4 switch-tested + ja/hi/bn rendered by the uppercase audit (7 distinct); the full 12-locale switch matrix remains open |
| Breakpoints | 4 global | 4 global + **375 per flagship surface** (5/5 pass) |
| a11y axis | not built | axe (6 surfaces) + keyboard/focus (2) + prefers-contrast |
| Honesty techniques (§5's nine) | 2 of 9 | **7 of 9** (rule 5 practiced; rule 9 out of scope, stated) |
| Post-import content | P0, untested | rendered from a real import, 6/6 markers (POSITIVE) |
| States | 3 | **4** (the import fixture state) |

**Still open after this session** (the honest remainder): the full 12-locale switch matrix;
axe/keyboard over the remaining surfaces (6 of ~15 axe'd here); the `ai-starting` label's
contrast (unreachable without a backend); the five filed axe P2s; the class-sweep triage;
rule 9's adversarial-critic posture (a different instrument); and the maintainer's own
hand click-through, which no automated matrix replaces.

## 11. Ordered follow-up worklist

1. The five filed axe P2s, each a scoped slice in its owner's territory: Home card-back
   chip/tier-badge contrast · agenda inline-link distinguishability (a convention
   decision) · `.an-tab` nested-interactive · the tasks top bar's grounds (`#llm`,
   `#tm-conn`, `.muted`) · reader `.deduced > h3`/`.dup-pill` contrast.
2. The `ai-starting` label (`var(--accent)` over the accent tint) — measure per theme the
   way §4 measured `ai-off`, on a machine where the state is reachable (or by computation).
3. The SPA's single-shot `/api/llm/health` boot read — consider a bounded re-poll so
   chrome cannot stay unpainted for a page's whole life after one failed read.
4. The class-sweep triage (7 candidates, human read each).
5. Widen the locale switch matrix toward 12; extend axe/keyboard to the remaining surfaces.
6. The maintainer click-through (gate row 8's §-note stands: automated stamps are
   "Chromium-verified (remote sandbox) · awaiting human UX pass", never the Gecko-verified
   (VM) bar).
