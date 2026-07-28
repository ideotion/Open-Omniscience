# GUI audit — translation coverage, graphical quality, visual data representation

**Date:** 2026-07-28 · **Status:** ANALYSIS + PLAN ONLY — nothing was fixed in this pass
(the maintainer's instruction was verbatim *"Don't fix anything yet, analyze, document and
prepare a PR for another autonomous session"*).
**Branch of record:** `claude/gui-audit-2026-07-28` · **Base:** `origin/main` @ `8965de1`
**Machine-readable worklist:** [`docs/audit/gui-audit-2026-07-28/i18n_missing_keys.csv`](../audit/gui-audit-2026-07-28/i18n_missing_keys.csv)
**Re-measurement scripts:** [`docs/audit/gui-audit-2026-07-28/probes/`](../audit/gui-audit-2026-07-28/probes/)

---

## 0. What this is, and what it deliberately is not

This is a **static, source-level** audit of the frontend across three axes the maintainer
named: (i) UI omitted from translation, (ii) graphical enhancements, (iii) visual data
representations and their unrealised potential.

**It composes with, and does not duplicate,** the two existing records:

| Document | What it established | Relationship to this audit |
|---|---|---|
| [`docs/audit/GUI_TEST_REPORT_2026-07-22.md`](../audit/GUI_TEST_REPORT_2026-07-22.md) | 72 skeptic-verified **behavioural** findings from a real Chromium run (5 P0 · 24 P1 · 38 P2 · 5 OPT) | Its own §9 item 9 asks for *"a dedicated i18n sweep, given the pattern in §2/§6 is systemic"* — **§1 below is that sweep, quantified.** Its item 10 asks for the `var(--warn)` contrast fix — **§2.1 below measures it per theme.** Every other P0/P1 there stays that report's to fix; this audit does not restate them. |
| [`docs/design/OBSERVATORY_DESIGN.md`](OBSERVATORY_DESIGN.md) | The night-sky keyword explorer (design-only, browser-gated) | §3 below deliberately **excludes** the Observatory. It is already specified, already sequenced behind its own prerequisites, and re-planning it here would be duplicate work. |

**Honest limits of this pass — stated up front:**

- **No browser was run.** Every claim below is derived from reading source, the locale
  files, and arithmetic over them. Contrast ratios are *computed* from the CSS variables
  (the same method the shipped invariant-#23 `--caveat` fix used), not sampled from
  rendered pixels.
- **Static string matching under-counts.** The probes catch literals in a fixed set of
  syntactic shapes (`<th>`, `<button>`, `placeholder=`, `title=`, `aria-label=`,
  `.textContent =`, `toast(`, `confirm(`, `alert(`). Template-literal-interpolated
  strings and strings assembled across lines are **not** counted. **Every number below is
  therefore a floor, not a total.** Where that matters it is repeated inline.
- **No severity is asserted from taste.** Each finding carries its measurement and the
  rule it is measured against.

---

## 1. Translation coverage — the largest and best-specified gap

### 1.1 First, correct the mental model (a first-pass error, recorded so it is not repeated)

A natural assumption — *"a string not wrapped in `t()` is untranslated"* — is **wrong for
this codebase**, and acting on it would produce hundreds of pointless edits.

Reading [`src/static/i18n.js`](../../src/static/i18n.js) establishes the real rule:

- `apply()` walks **text nodes** and the `ATTRS = ["placeholder", "title", "aria-label"]`
  attributes, translating any value whose trimmed, whitespace-collapsed form **exactly
  matches a locale key**.
- A `MutationObserver` (120 ms debounce) re-runs it, so **dynamically-inserted DOM is
  covered too**. A `<th>Jurisdiction</th>` built inside `app.js` and injected via
  `innerHTML` *is* translated today — because `"Jurisdiction"` happens to be a key.
- Therefore **the gap is a missing locale KEY, not a missing `t()` wrapper.**

One consequence needed correcting mid-audit and is worth recording: `toast()` does
`n.textContent = msg` on a node appended to the plain `#toast` div, which is inside
`<body>`, is not `SKIP`-listed (`DIV`), and is not marked `data-i18n-dyn`. **The observer
reaches it.** So a bare `toast("Preferences saved.")` — whose key *does* exist, translated
in all 12 locales — is **not** an untranslated string; it is a **~120 ms English flash**
before the observer's next tick. That is a real polish item but a far smaller one, and
mis-filing it as "translations that are never shown" would have been a fabricated finding.

The only strings the walker can **never** reach are those that never become DOM:
`window.confirm()` / `alert()` arguments (native browser chrome).

### 1.2 Measured coverage

Probe: [`probes/i18n_gap.py`](../audit/gui-audit-2026-07-28/probes/i18n_gap.py), run over
`app.js`, `reader.js`, `index.html`, `taskmanager.html`, `unlock.html`, `investigate.html`.

| Class | Count | Meaning | Fix |
|---|---:|---|---|
| **Already keyed** | **471** | DOM-reachable, key exists → **translated today in all 12 locales.** The engine works. | — |
| **A — no locale key** | **319** (272 distinct) | DOM-reachable but no key → **permanently English in all 11 non-English locales.** | Add the key ×12 |
| **B — native dialog** | **6** (6 distinct) | `confirm()`/`alert()` argument → walker can never reach it | Wrap in `t()` **and** add the key ×12 |
| **C — keyed but bare** | **539** | Key exists, literal at the call site | ~120 ms English flash; wrap in `t()` to remove it (cosmetic, low priority) |

**A + B = 325 rows / 278 distinct strings** — the actionable worklist, shipped as
[`i18n_missing_keys.csv`](../audit/gui-audit-2026-07-28/i18n_missing_keys.csv).

Class A by file: `app.js` 213 · `index.html` 94 · `reader.js` 5 · `investigate.html` 5 ·
`taskmanager.html` 2.
Class A by shape: `toast` 87 · `<button>` 54 · `<th>` 50 · `placeholder` 48 · `title=` 48 ·
`.textContent` 26 · `aria-label` 6.

### 1.3 Finding I-1 — the gate is structurally blind to the UI engine *(highest leverage)*

`scripts/i18n_report.py` sets `_UI = src/static/index.html` (line 38) and opens **nothing
else**. Consequences, both verified:

- `--min 100` reports **2130/2130 (100.0 %) for all 12 locales — green**, and
  `--audit-chrome` reports *"1069 UI strings, 801 keyed, 268 untranslatable"*. Both
  numbers describe `index.html` alone.
- **`app.js` is 18,536 lines and is the actual UI engine.** Its 213 permanently-English
  strings are invisible to both commands, as are `reader.js`, `taskmanager.html`,
  `unlock.html`, `investigate.html`, and the 8 skins under `src/static/guis/`.

This is why the coverage number has read "100 %" while the maintainer keeps meeting
untranslated surfaces. **Extending the gate's file scope is the single change that stops
this class of gap from silently regrowing** — and it must land *with* the key additions,
or the newly-widened gate immediately reddens CI.

### 1.4 Finding I-2 — the reader's two-class provenance headings are unkeyed *(non-negotiable breach)*

The server-rendered reader (`src/api/main.py`) does load `i18n.js` (line 1983), so the
same key rule applies. Ten of its headings have **no key**, including the ones that
*implement* the project's stated honesty model:

| `main.py` | String | Why it matters |
|---:|---|---|
| 1606 | `From the source` | the **asserted** class label |
| 1607 | `Deduced by this app — less reliable` | the **deduced** class label |
| 1632 | `AI-derived — unreliable` | the **AI** class label |
| 1675 | `Sources this article cites` | |
| 1765 | `Dates mentioned in this text` | |
| 1748 / 1750 | `confirm` / `reject` | the confirm-within-the-lens controls |
| 1991 / 1992 / 1996 | `Summary` / `Translation` / `Loaded language` | reader tabs |

The standing **INFORMED CONSENT** non-negotiable states caveats are visible by default and
*"Every consent/caveat string ships ×12 locales."* A reader in any of the 11 non-English
locales currently sees the article's metadata correctly grouped but the **grouping labels
that carry the reliability claim in English only** — i.e. the honesty layering degrades
exactly where it is load-bearing. Verified absent by exact and substring lookup against
`en.json`.

**This should lead the fix session.** It is ten keys.

### 1.5 Finding I-3 — 33 near-identical error strings want one `tf()` template

Class A's largest single family is `"<Verb> failed: " + e.message`: `Save failed:`,
`Track failed:`, `Uninstall failed:`, `Panic wipe failed:`, `Batch ingest failed:` … —
**33 distinct strings**, each needing its own key ×12 (= 396 translation entries) if
handled naively.

`OOI18N.tf()` exists precisely for this: a fixed keyable template plus untranslated data.
One key — `"{action} failed: {error}"` — ×12 replaces all 33, and the verb becomes a
short keyed noun reused elsewhere. Same treatment for the `"… unavailable: "` and
`"Could not …: "` families.

**Two cautions the executing session must respect**, both already-recorded project
lessons: a `{placeholder}` with no matching var renders literally, so validate at
construction; and adding a template key to `en.json` alone **reddens `--min 100`** — every
new key must land in all 12 locale files in the same commit.

### 1.6 What I-1..I-3 do *not* cover

The probes do not read the 8 `guis/` skins' DOM (they are CSS-only skins over the same
`index.html` DOM — checked: **zero** CSS `content:` text literals, so they inherit whatever
`index.html` and `app.js` achieve), nor `sw.js`, nor template-literal-interpolated strings.
A `tf()`-oriented follow-up sweep over interpolated rows is a known remainder.

---

## 2. Graphical quality

### 2.1 Finding G-1 — `--warn` fails WCAG AA on 6 of 17 themes *(quantifies the prior report's item 10)*

Computed with the same method as the shipped invariant-#23 `--caveat` fix (relative
luminance → contrast ratio, `--warn` against each theme's own `--panel`, inheriting
`:root` where a theme does not redefine the variable):

| Theme | `--warn` | `--panel` | ratio | AA 4.5:1 |
|---|---|---|---:|---|
| paper | `#d9a441` | `#fbf8f1` | **2.12** | FAIL |
| dawn | `#ea9d34` | `#fffaf3` | **2.16** | FAIL |
| solar | `#cb4b16` | `#073642` | **2.82** | FAIL |
| mist | `#b07a17` | `#f9fafc` | **3.56** | FAIL |
| light | `#b07a17` | `#fff` | **3.72** | FAIL |
| mint | `#a8761a` | `#f8fbf8` | **3.82** | FAIL |
| *(11 dark themes)* | `#d9a441` / `#ffd400` | — | 7.17–13.83 | PASS |

**Every failure is a light theme** — the identical signature the `--caveat` fix already
solved (it failed 8/17 before its theme-aware value landed). The fix is the same shape: a
theme-aware `--warn` with a darker light-mode value, verified by re-running
[`probes/contrast.py`](../audit/gui-audit-2026-07-28/probes/contrast.py) across all 17.

Caveat: this is *computed from the variables*, not sampled from rendered pixels; any rule
that overrides `--warn` with a literal colour at a specific call site is not captured.

### 2.2 Finding G-2 — the inline-handler debt is ~1.9× the recorded figure

The ledger records *"295 inline `on*=` as of 2026-06-15"*, counted in `index.html` only.
Measured now:

| Source | Count |
|---|---:|
| `index.html` | **317** (`onclick` 240 · `onchange` 42 · `onkeydown` 17 · `oninput` 15 · other 3) |
| `app.js` generated markup | **239** (`onclick` 220 · `onchange` 10 · `onkeydown` 6 · other 3) |
| **Total** | **556** |
| `addEventListener` (app.js) | 103 |

The `app.js` half has never been counted. This matters for the retirement pass because
handlers inside generated HTML strings resolve against **top-level function names** — the
project's own recorded lesson is that duplicate top-level names silently override, so
retiring them is a correctness change, not only hygiene. It remains **browser-verify-gated**
(fork-3) and is *not* proposed for the fix session.

### 2.3 Finding G-3 — responsive and preference coverage is thin

`app.css` is 1024 lines with **5 layout media queries** total (`max-width` 900 / 860 / 600 /
460, plus one `min-width:601px` band). Two `prefers-reduced-motion` blocks exist (one
global `* { animation:none !important }`), and **`prefers-contrast` is not handled at all**
(0 occurrences) despite a dedicated `contrast` theme existing.

`index.html` carries 22 `role=`, 60 `aria-*`, **3** `tabindex`, **0** `.sr-only`, **0**
`alt=`. The absence of `.sr-only` in the static shell is notable given `ooMap` builds an
`.sr-only` fallback list in JS — i.e. the screen-reader affordance exists for the map but
has no counterpart for the static chrome.

This corroborates, from source, the prior report's live P0 finding that the top bar loses
reachability below ~1024 px: **there is no media query between 900 px and the desktop
layout at all.** Its fix (an overflow menu or wrapping) is that report's item 4; this audit
adds only the confirmation and the `prefers-contrast` gap.

### 2.4 Not re-litigated

Theme count (17 + default), the `color-mix` theme-derivation pattern (54 uses), and the
`#oo-tip` hover convention are all working as designed and are **not** proposed for change.

---

## 3. Visual data representation

### 3.1 Finding V-1 — 8 built, tested viz primitives have zero call sites *(the biggest opportunity)*

`src/static/ooviz.js` (594 lines) is loaded by `index.html` (line 2785) and exposes ~14
pure primitives. `app.js` calls **6**: `choroplethData`, `gridLayout`, `linearScale`,
`niceTicks`, `slopeGeometry`, `statChartGeometry`.

**Unused — but implemented and covered by `tests/test_ooviz.py` + `tests/ooviz_node_test.js`:**

| Primitive | Enables | Natural home |
|---|---|---|
| `binCounts1D` | **histogram** | article-length distribution; keyword-frequency shape; qualification-attempt spread |
| `fiveNumberSummary` | **box plot** | per-source article length; per-language keyword density |
| `bin2D` | **heatmap** | keyword × time; source × language; hour-of-day publishing |
| `sqrtAreaScale` + `symbolRadii` | **proportional symbols** | the ruled levels-not-normalised map path (choropleth is normalised-only by invariant) |
| `pathWithGaps` | gap-honest line | any series with missing periods — **draws a break instead of bridging it**, which is the honest rendering |
| `statSeriesPaths` | multi-series with gaps | stat-figure vintages |
| `setupCanvas` | HiDPI canvas | prerequisite for any canvas-based surface |

This is unusually cheap capability: the maths is written, the honesty semantics are
already encoded (`pathWithGaps` refuses to bridge a gap; `choroplethData`/`symbolRadii`
carry the normalised-only gate asserted in `test_repo_invariants.py`), and the tests pass.
**What is missing is call sites.**

### 3.2 Finding V-2 — 35 render functions emit a table and never a chart

Parsing all 941 top-level functions in `app.js` and classifying each by whether it builds
`<table>`/`<tr>`/`<th>` and whether it calls any renderer: **87 call a renderer, 35 are
table-only.** The largest (by body length) are the strongest candidates:

| Function | Lines | Data shape | Suggested representation |
|---|---:|---|---|
| `renderCorpusCompetitive` / `renderAnCompetitive` | 96 / 70 | source × (volume, tone, timing, emphasis) | **small multiples** (`gridLayout`, already used elsewhere) — the descriptive, no-ranking framing is preserved |
| `renderCorpusKeywords` | 56 | term × count × spread | **dot plot / sorted bars**; histogram of the count distribution via `binCounts1D` |
| `loadLunar` | 49 | dated phase series | a compact timeline strip |
| `loadStatAgencies` / `loadStatFigures` / `triangulateStatSeries` | 35 / 20 / 23 | vintaged figures, producers side by side | **`statSeriesPaths` + `pathWithGaps`** — exactly what they were written for; triangulation is inherently a multi-series-never-averaged comparison |
| `loadMineralsSupply` | 30 | production / reserves per country | proportional symbols on the map, or sorted bars |
| `renderCoverageTable` / `renderCoverageRegions` | 35 / 27 | region × sources × floor | sorted bars against the floor line |
| `_uxCorpusDeltaView` / `_uxTimingsView` | 48 / 24 | before→after per dimension; per-stage durations | **slope chart** (`slopeGeometry`, already used) / a stacked duration bar |

**These are candidates, not a mandate.** The house rules constrain every one of them:
counts only, no composite score, method + caveat visible, `n` shown, sparse series render
as bars (`_SPARSE_BAR_MAX = 10`), full resolution never downsampled. A table that is
*already* the honest representation should stay a table — and per invariant #8 and the Desk
lesson, **a chart must be added beside the table, never replace it.**

### 3.3 Finding V-3 — the sparse-data honesty rule does not reach every renderer

`_SPARSE_BAR_MAX = 10` (the ruled *n<10 → bars, never a curve through sparse points*) is
honoured by `ooChart`, `dashChartSvg`, `slopeChartSvg`, and `smallMultiplesSvg`. It is
**absent** from `ringDumbbellSvg` (`app.js:10223`), `commodityOverlaySvg` (`:16336`), and
`ooDonut` (`:7469`).

For the dumbbell this is arguably fine — it plots discrete paired points, not a curve, so
there is no interpolation to forbid. `commodityOverlaySvg` **does** draw a price line and
should be checked against the rule. This is flagged for verification, not asserted as a
defect: the honest statement is *"the rule's coverage is uneven and two of the three cases
need a decision."*

### 3.4 Finding V-4 — `ooDonut` violates the project's own chart-decision framework

`docs/research/dataviz/chart_decision_framework.md` (committed, and the basis for the
`ooviz` primitives) states for part-to-whole: *"Pie/donut only if **≤4–5 slices**, share
labels shown, and precise comparison is not required; otherwise bars"*, and lists
*"many-slice pie"* on its REJECT list.

`ooDonut` (`app.js:7469`) shows share labels (good) but has **no slice-count guard**: it
accepts any number of items and colours them `hsl(i*360/n)`. Its single caller
(`app.js:7559`) feeds it **`unlocated.by_language`** — an unbounded set of language codes.
On the maintainer's corpus that is well past 5 slices, at which point adjacent hues stop
being distinguishable and angle-reading stops being reliable — the exact failure the
framework rejects.

**Suggested resolution:** keep the donut for ≤5 slices and fall back to sorted horizontal
bars above that (the framework's own named replacement), with the remainder grouped into a
labelled "other (n)" — never silently truncated. Both branches already have primitives.

---

## 4. Proposed work for the fix session

Ordered by **severity × ease**, with the cheap honesty-critical work first. Every slice is
independently shippable as its own draft PR.

| # | Slice | Why first | Gate it must pass |
|---|---|---|---|
| **1** | **Reader provenance headings** — 10 keys ×12 (§1.4) | breaches a stated non-negotiable; ten keys | `--min 100` green |
| **2** | **`tf()` templates for the error families** (§1.5) — one template replaces 33 strings | collapses the largest gap family before bulk key-adding | template-vars validated at construction; all 12 locales in the same commit |
| **3** | **Class A key sweep** — the remaining ~239 distinct strings from the CSV (§1.2) | mechanical, worklist already produced | `--min 100` green |
| **4** | **Widen `i18n_report.py`'s scope** (§1.3) — `app.js`, `reader.js`, the three aux HTML pages | stops regrowth; **must land with or after 1–3**, or CI reddens immediately | `--audit-chrome` re-baselined; a repo-invariant pinning the new file list |
| **5** | **`--warn` theme-aware value** (§2.1) | 6 themes below AA; identical to a fix already shipped for `--caveat` | re-run `probes/contrast.py`: 17/17 ≥ 4.5:1 |
| **6** | **`ooDonut` slice-count guard** (§3.4) | a shipped renderer contradicting a committed framework | ≤5 slices → donut; above → sorted bars + labelled remainder |
| **7** | **`prefers-contrast` support** (§2.3) | a `contrast` theme exists but the media feature is unhandled | — |
| **8** | **First `ooviz` activations** (§3.1/§3.2) — pick 2–3 from the V-2 table | dormant tested capability; highest visible payoff | added **beside** the table, never replacing it; counts only, no score, `n` + method visible; sparse → bars |

**Explicitly out of scope for that session** (each has its own owner or gate):
the 72 behavioural findings in `GUI_TEST_REPORT_2026-07-22.md`; the Observatory
(`OBSERVATORY_DESIGN.md`, browser-gated); the inline-handler retirement (§2.2,
browser-verify-gated); the top-bar responsive fix (that report's item 4); and the class-C
flash polish (§1.2 — cosmetic, 539 sites, lowest value per edit).

**Standing constraints that apply throughout:** frontend ships conservative + flagged
(`node --check` + invariant guards + defensive empty states, marked *browser-unverified,
needs click-through*) per fork-3/Q6a; no composite scores; caveats visible by default; a
capability is added beside what exists, never silently removed.

---

## 5. Reproducing every number here

```bash
python3 docs/audit/gui-audit-2026-07-28/probes/i18n_gap.py     # §1.2 classes A/B/C
python3 docs/audit/gui-audit-2026-07-28/probes/contrast.py     # §2.1 per-theme --warn
python3 docs/audit/gui-audit-2026-07-28/probes/viz_map.py      # §3.2 table-only vs charted
```

The probes are stdlib-only, read-only, and take no arguments. They are committed so the
fix session can re-run them as its own before/after evidence rather than trusting this
document's numbers.
