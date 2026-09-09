# Theme / locale / responsive matrix — live results (2026-09-08)

> One of five per-workflow syntheses from the live visual audit. See
> [`../11_VISUAL_UI_AUDIT_2026-09-08.md`](../11_VISUAL_UI_AUDIT_2026-09-08.md) for method and scope.
> **Report-only.**
>
> **CORRECTION BY THE ORCHESTRATING SESSION — this synthesis under-reports its own workflow's
> coverage, and the cause is a defect in the workflow script rather than in any agent.** The script
> passed the stream results to the synthesis agent as `JSON.stringify(ok).slice(0, 220000)`. The blob
> exceeded that, so **four of the ten streams never reached the synthesiser** and it reported, in good
> faith, on the six it could see. Three statements in its section 1 are therefore false about the
> workflow that produced it:
>
> | its claim | what actually ran |
> |---|---|
> | "365 live combinations" | **599** across ten streams |
> | "None of the 8 GUI-gallery skins were tested by any agent in this batch" | both skin agents ran — **164 combinations, 16 findings**, including the assessment that the Command skin is pure overhead with a CSP-violating code path |
> | "`reduced_motion`, `prefers-contrast` and any browser-zoom/reflow test were never exercised" | the `media-prefs-a11y` stream exercised **all three**, plus greyscale and colour-blind simulation and a full `axe` pass — **72 combinations, 16 findings**, including the Observatory's WCAG 1.4.10 reflow failure at 200% zoom |
>
> The missing streams are `gui-skins-a`, `gui-skins-b`, `density-typeface` and `media-prefs-a11y`;
> **all 49 of their findings are present in [`findings.csv`](findings.csv)** and are drawn on in the
> master report. Everything the synthesis *does* report below stands — its root-cause analysis is the
> best in the audit. Only its coverage section is short, and it is short because of my script.

*Synthesis of 6 matrix agents (themes-dark, themes-light, responsive-narrow, responsive-wide, rtl-arabic, cjk-and-expansion) and their adversarial verify passes. Severities below are **post-verification** — the verify pass's `adjustedSeverity` where one ran, the original rating where it did not (cjk-and-expansion shipped with no verify block in this batch and is flagged accordingly throughout).*

## 1. Coverage: what was actually rendered and measured

**365 live (theme×locale×viewport×surface) combinations** were rendered in Chromium across the six streams (72 + 64 + 65 + 90 + 14 + 60), each independently re-measured by a second adversarial agent for five of the six streams.

Surfaces touched at least once: `home, feed, insights, observatory, settings, search, agenda, library, help, markets, timemap, law, analyze, custody` — **14 of the 16 reachable surfaces**. **`indices` and `integrity` were never opened by any agent in this batch.**

Themes: all **9 confirmed-dark** themes (ink, slate, midnight, cyber, forest, aubergine, garnet, terminal, contrast) plus all **8 nominally-"light"** themes were rendered — but code-level probing (themes-light F8, CONFIRMED) showed 3 of those 8 (**arctic, solar, sepia**) actually render as dark themes (`color-scheme:dark`, near-black background, dark-mode `--caveat`). Net honest count: **12 dark-rendering + 5 light-rendering = all 17 catalogued themes measured**, just mis-bucketed by the assignment. Accent override was checked on only 2 of 17 themes (ink, contrast). Density (compact) was spot-checked on 2 widths, 2-3 surfaces. Font-face picker was never driven directly. **None of the 8 GUI-gallery skins (`ui_skin=`) were tested by any agent in this batch.**

Locales: `en` (all streams), `ar` (dedicated RTL stream, 1440×900 only), `zh`/`ja` (CJK stream), `de`/`ru`/`hi`/`bn` (expansion locales) — 7 of 12 shipped locales got a dedicated pass; `fr, es, pt, id` were never independently exercised.

Viewports: 320/360/375/414/480 (narrow), 600/601/700/860/900 (sidebar-invariant checkpoints), 900–2560 in six steps (wide), 1440×900 fixed for RTL/CJK. **No mobile-width × non-English, no mobile-width × non-ink-theme, and no RTL × narrow-viewport combination was ever tested** — three axes of this matrix (locale, viewport, theme) were each swept independently but never crossed with each other.

Explicitly **not reached** and honestly flagged by the agents themselves:
- `axe()` (automated WCAG rule scan) ran only in themes-light and partially in the verify passes; themes-dark, responsive-narrow, responsive-wide's own primary sweep, and cjk-and-expansion never ran it.
- `reduced_motion`, `prefers-contrast: more`, and any browser-zoom/reflow test were never exercised by any agent, despite `oohelp.App` supporting all three.
- Real keyboard interaction (arrow-key roving tabindex in RTL, Tab-order through an open mobile drawer) was attempted once and aborted after a shared-host resource crash; the drawer focus-trap gap it did catch (§6) is a live defect, not a null result.
- The populated Observatory ranked table at 2560px, a real chain-of-custody entry with actual hashes, and the dedicated local-reader overlay for an Arabic article were each attempted and blocked by shared-host memory pressure, not skipped by choice.
- cjk-and-expansion's findings did not receive an adversarial verify pass in the data available for this synthesis; they are reported below as **self-reported, cross-corroborating** evidence rather than independently confirmed.

## 2. The root causes (grouped defects, highest leverage first)

Fourteen "findings" across the six agents collapse into **eight root causes**. Fixing each closes every symptom listed under it, in every theme/locale where it was observed.

### RC-1 (P1) — Card/producer content has no i18n mechanism at all
`src/briefing/card.py`'s `Card` dataclass fields (`summary`, `method`, `caveat`, `trigger`) carry **no `_i18n` sibling**, and of 34 registered producers only 1 (`rising_now`) uses the optional `title_i18n` path that does exist. Every Home briefing lead card — title, pattern badge, full explanatory paragraph, exact-math footer, disclosure line — is built as a raw English f-string.
- Confirmed live in **Arabic** (rtl-7, CONFIRMED P1: chip/paragraph/math/footer all English, one stray translated "الطريقة:" label mid-block) and independently in **zh, de, ja, ru, hi, bn** (cjk-and-expansion F2, self-reported but corroborating, same code citation). One fix (add `_i18n`/vars fields to `Card` and wire all 34 producers through it, the way `--caveat` was already fixed) closes the single largest untranslated block on the app's most-visited surface, in **11 of 12 shipped locales at once**. This is the most severe finding in the whole audit: it contradicts the "every string ships ×12" non-negotiable and invariant #23 directly, and two independent agents in two locale families reached the same source-code cause.

### RC-2 (P1) — Observatory domain-wedge labels are drawn on canvas, never through `t()`
`src/static/oosky.js` (~line 495) calls `ctx.fillText(da.domain, lx, ly)` directly on the raw backend taxonomy string; a canvas has no DOM node for the app's own i18n walker to reach, and the `oo:langchange` re-render (which does correctly refresh other Observatory chrome) never touches this call.
- Confirmed independently in **ar** (rtl-4, CONFIRMED P1 — all 12 wedge labels English while the surrounding chrome, paragraph, and axis pickers are fully Arabic) and in **zh** (cjk F3, code-level: a zh key for "Technology" already sits unused in the locale file, proving this is a routing omission, not a missing translation). Affects every one of the 11 non-English locales on the app's flagship new surface, permanently, on every load.

### RC-3 (P1) — A second, un-reviewed fixed-color system runs parallel to the theme tokens
Three separate "findings" are one bug: `span.chip` (the four trigger-badge hues) and `span.tier-badge` use hardcoded hex values instead of routing through the per-theme-safe pipeline the maintainer already built for `--caveat`.
- **`span.chip` "lonely signal"** (`rgb(129,71,209)`) fails AA on **all 12 dark-rendering themes** (2.75–3.27:1, themes-dark F2 CONFIRMED) and **passes on all 5 light-rendering themes** (4.66–5.12:1, themes-light verify) — a single fixed hue that is simply too dark for a dark panel.
- **The other three chip hues** ("recycled claim", "source laundering", "diet self audit") show the mirror failure: they pass on every dark theme but each fails on some subset of light themes (themes-light F1, PARTIALLY_CONFIRMED — the original claim overstated that all four badges fail identically everywhere; the real pattern is 1–3 of 4 badges failing per theme, whichever hue is closest to that theme's own background lightness).
- **`span.tier-badge`** ("Developing corpus", fixed `rgb(59,130,196)`) fails AA on **all 8 light-rendering themes tested, including its best case** (arctic 4.22:1 — still under 4.5) (themes-light F3, CONFIRMED).
One token-pipeline fix — the same fix the maintainer already shipped for `--caveat` — resolves all three at once, across the full 17-theme catalog, rather than three separate per-theme patches.

### RC-4 (P1/P2) — `var(--line)` is undefined app-wide; the 2026-09-07 dialog fix never reached non-`<dialog>` call sites
`getComputedStyle(document.documentElement).getPropertyValue('--line')` returns `''` on every dark theme tested. The prior session's fix was scoped to a blanket `dialog{border:1px solid var(--border)}` rule; `#oo-tip` and `#net-coach` are plain `<div>`s and render with `border-style:none`/`0px` on **all 9 dark themes tested** (themes-dark F1, CONFIRMED, live-reproduced with forced-visible screenshots). By the same identical CSS shorthand, `.gw-lang` (first-launch language picker) and `.carousel-dot` (Home lead carousel) are provably subject to it too, though neither rendered live in any session this batch (themes-dark notReached/M3). `reader.css` and `index.html` carry 22+ more bare `var(--line)` uses beyond the two confirmed; `taskmanager.html` already uses the safe `var(--line, #232733)` fallback pattern everywhere but 2 uses — the fix is copy that pattern to the remaining call sites in one pass.

### RC-5 (P1) — Five light-rendering themes' own accent/muted tokens sit a few points too pale, failing AA on three unrelated components at once
`solar`, `mist`, `dawn`, `mint`, `paper` independently picked an `--accent` and `--muted` a few percent too light for their own `--panel`. This single per-theme token choice surfaces as three apparently-unrelated findings:
- `button.active` (ooSubtabs, invariant #18's one shared subtab component) fails AA on exactly these 5 themes — 3.47–4.40:1 — while `arctic`(7.81), `sepia`(6.58) and `light`(4.756) pass cleanly (themes-light F4, PARTIALLY_CONFIRMED — original claim wrongly said 8/8 fail; corrected scope is 5/8, and `light`'s own claimed failing number, 4.30, was itself a measurement error — it actually passes at 4.756).
- The persistent left-sidebar nav-item labels fail `axe`'s color-contrast rule on the **same 5-theme set** (themes-light missed-M1, unverified by a second pass but internally corroborating — solar 34 violations, dawn 56, mist 38, mint 28, paper 38 vs. 6–8 on arctic/sepia/light).
- `--muted` itself (chrome meta, `div.k` stat labels, `span.muted` attributions) fails AA on the **same 5 themes** (themes-light F5, PARTIALLY_CONFIRMED — original claim missed `solar`, which fails identically at 3.95:1 once the element's real composited background is used).
One token audit across these five themes' `--accent`/`--muted` values fixes all three symptoms simultaneously, everywhere those tokens are used.

### RC-6 (P1) — `OOI18N` readiness race on Home: intermittent, not permanent, mistranslation
`app-home.js`'s `renderHomeStats`/`renderHomeStatus` gate on `window.OOI18N && OOI18N.t` at first paint and silently fall back to raw English if i18n hasn't initialized yet, with **no re-render once it becomes ready**. Repeated trials from byte-identical harness parameters reproduced both the all-English state and the fully-correct-Arabic state non-deterministically (rtl-3(b)/rtl-8, both downgraded from "100% English" to PARTIALLY_CONFIRMED once this was found; rtl missed-3 names the structural cause). This is more serious than a missing key — it means the Home stat strip and the no-telemetry disclosure sentence (the in-app echo of the project's own privacy claim) can silently ship in the wrong language on an unlucky load, in every locale, with nothing to catch it in a screenshot-based QA pass.

### RC-7 (P1/P2) — A small cluster of strings were simply never wrapped in `t()`, invisible to the 100%-parity locale gate
Confirmed by direct key-lookup against all 12 locale JSON files: Library's 6 stat-tile labels ("Avg words / article" etc.) call `t()` but the key is absent from **every one of the 12 locale files** (deterministic gap, not a race — themes-light did not test this but cjk-and-expansion F4 confirmed it via direct 12-file lookup); Insights' "articles indexed" counter (rtl-6/cjk-F4), Search's result-count line (rtl-9, CONFIRMED — hardcoded ordering also reads as broken word order), and the World Map's empty-state sentence (cjk-F4) are **hardcoded English literals with zero `t()` call**, so they can never translate regardless of locale-file completeness. The project's own `scripts/i18n_report.py` gate checks that all 12 locale files share the same key set (and they do, 3151 keys uniformly) — it has a structural blind spot for strings that were never given a key to begin with.

### RC-8 (P1) — The network-status coach toast has no dismiss-on-navigate and blocks clicks, confirmed in two unrelated sessions
`#net-coach` carries no `pointer-events:none` and stays `show/prominent` across every surface navigation in a session; Playwright's own click-intercept trace ("`<div id="net-coach">` subtree intercepts pointer events") was reproduced **independently in an English 375px session (blocking the Insights Map subtab) and a full Arabic desktop session (blocking Settings' Advanced subtab)** — responsive-narrow F2 (CONFIRMED, though the claimant's own cited log line traced to a different agent's file) and rtl-12 (CONFIRMED). Separately, below 346px viewport width, `#oo-tip`'s positioning has no left-edge clamp (`Math.min(x+12, innerWidth-346)` with no matching `Math.max` floor) and renders at negative-x, visually overpainting and corrupting the coach's own message text (responsive-narrow F1, PARTIALLY_CONFIRMED — the negative-x defect is real and reproduced exactly, but only below ~346px, not across the full 320–480px range as first claimed). Fix: mirror `#net-coach`'s own correct two-sided clamp onto `#oo-tip`, and give the coach an overlap-awareness rule against the active tab's own navigation.

## 3. Contrast & colour

**Per-theme AA status of the components independently re-measured (post-verify numbers):**

| Theme | Renders as | `span.chip` "lonely signal" | `.tier-badge` (blue, light bucket only) | `button.active` (ooSubtabs) | `--muted` vs own panel | `--caveat` | `var(--line)` |
|---|---|---|---|---|---|---|---|
| ink | dark | **FAIL** 2.89 | not tested | not tested | not tested | PASS 8.57+ | **undefined** |
| slate | dark | **FAIL** 2.75 | " | " | " | PASS 8.16+ | undefined |
| midnight | dark | **FAIL** 2.96 | " | " | " | PASS 8.78+ | undefined |
| cyber | dark | **FAIL** 3.13 | " | " | " | PASS 9.27+ | undefined |
| forest | dark | **FAIL** 2.90 | " | " | " | PASS 8.59+ | undefined |
| aubergine | dark | **FAIL** 2.95 | " | " | " | PASS 8.76+ | undefined |
| garnet | dark | **FAIL** 2.97 | " | " | " | PASS 8.82+ | undefined |
| terminal | dark | **FAIL** 3.27 | " | " | " | PASS 9.71 | undefined |
| contrast | dark | **FAIL** 3.24 | " | " | " | PASS 9.6 | undefined |
| arctic | dark (misclassified "light") | **FAIL** 2.79 | **FAIL** 4.22 (best case) | PASS 7.81 | PASS | PASS (0 fail) | untested |
| solar | dark (misclassified "light") | **FAIL** 1.99 | **FAIL** 3.20 (worst) | **FAIL** 3.47 | **FAIL** 3.95 | PASS | untested |
| sepia | dark (misclassified "light") | **FAIL** 2.60 | **FAIL** ~4.0 | PASS 6.58 | PASS | PASS | untested |
| light | light | PASS 4.66–5.12 | **FAIL** ~4.1 | PASS 4.76 | PASS (best of set) | PASS | untested |
| mist | light | PASS | **FAIL** ~3.9 | **FAIL** 3.59 | **FAIL** 4.47 | PASS | untested |
| dawn | light | PASS | **FAIL** ~3.8 | **FAIL** 3.50 | **FAIL** 4.00 | PASS | untested |
| mint | light | PASS | **FAIL** ~4.0 | **FAIL** 4.40 | **FAIL** 4.43 | PASS | untested |
| paper | light | PASS | **FAIL** 3.85–4.06 | **FAIL** 3.94 | **FAIL** 3.85–4.06 | PASS | untested |

**Worst pairs found, by exact number:** `span.chip` "lonely signal" on `solar`, 1.99:1 against a 4.5 requirement — the single worst contrast failure measured anywhere in this audit. `a.skip-link` measured ≈1:1 pre-focus on every theme in every stream, but this is confirmed **intentional off-screen positioning** (`top:-48px`), not a color-matching trick as one agent first guessed (themes-dark F9/rtl missed-M1: the true mechanism is `position:absolute;top:-48px` revealed by `:focus{top:8px}`, and the element's own colors are a normal high-contrast accent pair) — its actual `:focus`-revealed state was never captured in any of the six streams, so this remains an open, not a passed, check. `button.lead-flip-hint.back` ("⟲ رجوع") on a flipped Home card scored **1.04:1** (muted gray on the card's own blue fill) — found only by the RTL verify pass (missed-1) and missed by every primary sweep; worth checking on every theme, not just `ink`.

**The `--caveat` colour check is the cleanest pass in the whole audit**: zero `.card-caveat` contrast failures across all 72 dark-theme combinations and all 64 light-theme combinations, worst-case ratio 8.16:1 (slate) — the maintainer's documented fix for the historical "#c98a1b failed 8/17 themes" regression holds under two independent fresh audits (themes-dark F5, themes-light F10, both POSITIVE and unchallenged by verify).

**Colour-as-only-signal:** Observatory's "Colour = Language" channel was checked for exactly this failure mode and found *not* to violate it — colour is drawn from a per-theme `--fig-1..6` token keyed to a language's stable rank slot, not a fixed data-intrinsic hue and not the only channel (angle + a labelled legend also carry the encoding); the same galaxy renders cyan in `cyber` and green in `forest` while a sibling galaxy in a different rank slot keeps its hue in both — a themed categorical palette, not a "uniform hue wash" as first described (themes-dark M2, refining F4's Observatory characterization).

A tooling note that affects how to read every number above: the shared harness's `backdrop()` compositing function had a real bug — excluding an element's own background-color before scoring its text — that manufactured false "near-1:1" failures on filled buttons (`#net-coach-go`, `.tiny` buttons, the skip-link) in the themes-dark and rtl-arabic streams (themes-dark F3, rtl-11: both PARTIALLY_CONFIRMED/refuted-on-the-headline-claim once the corrected harness — patched the same day, 2026-09-08 — was used). The `--caveat` and chip numbers above post-date that fix and are trustworthy; any *other* raw contrast number cited from a pre-fix run against a filled button/badge should be treated with suspicion until re-checked.

## 4. Layout & responsiveness

**The 900px→desktop gap is real, precisely bounded, and one unconditional CSS rule.** `main > * { max-width:1100px; margin:auto }` (app.css:289) carries no media query and applies to **8 of 9 wide-surfaces tested** (home, feed, insights, observatory, settings, search, library, analyze); at 2560px, whitespace ratio grows monotonically to **0.57** — 57% of the screen is empty gutter (responsive-wide, main-content-1100px-hard-cap, CONFIRMED exactly to 3 decimal places). `#tab-agenda{max-width:none}` is the sole, already-shipped exception, and it demonstrably works: Agenda's content grows to 2270px at 2560px viewport with only a 0.113 whitespace ratio (POSITIVE, proves the fix pattern). The shared `ooChart` toolkit independently hard-caps every chart canvas at exactly 900×200 CSS px regardless of container width — byte-identical across 1280–2560px (ochart-900px-canvas-cap, CONFIRMED) — compounding the column cap with a second, smaller cap inside it. The universal subtab strip (`.subtab-strip`) is **not** subject to the 1100px cap (it sits outside `main > *`), so on every ooSubtabs-driven surface it visibly drifts out of alignment with the capped content panel beneath it once the viewport passes **~1400px** (subtab-strip-panel-misalignment, CONFIRMED, onset corrected from a looser "~1120px" first estimate) — the tab row and the content it labels literally jog apart as the window widens.

**The 900–1024px band is a specific no-man's-land**, hit from three unrelated directions: Observatory overflows the document by 30px at exactly 900–901px, with two of its caveat paragraphs genuinely word-clipped (though one cited example — the section H2 — was checked at the glyph level and is *not* actually clipped despite its box technically overflowing; observatory-900-901-overflow, PARTIALLY_CONFIRMED). Analyze's 12-tab subtab bar wraps to 3 rows at exactly 900–901px (missed by the primary wide-sweep, only caught in verify) while Settings' 9-tab bar wraps to 2 rows at 900/901/1024px (subtab-wrap-midrange, CONFIRMED for Settings, corrected for Analyze once a permanently-hidden zero-rect "Price" tab was filtered out of the count). And the topbar's icon cluster orphans the shutdown button onto its own row at 601px, with the *same* wrap defect recurring worse — 4 icons together — at 900–1024px (responsive-narrow F7, PARTIALLY_CONFIRMED, scope widened by verify).

**Horizontal scroll, confirmed and reproduced exactly:** Help/User-Manual forces real document-level horizontal scroll at **all five tested phone widths (320–480px)**, `scrollWidth` pinned at 781px regardless of viewport — root cause is a bare `1fr` grid track (should be `minmax(0,1fr)`, the pattern already used elsewhere in the same stylesheet) at the `max-width:600px` breakpoint (F3, CONFIRMED exactly). Three components (`#home-tier` badge, a Markets "Custom" chart card, an Insights subtab button) overflow by 9–17px at 320px only, cleanly resolved by 360px (F4, CONFIRMED to the pixel).

**Tap targets:** every topbar icon button (`hamburger`, `rate-toggle`, `net-toggle`, `help`, `app-shutdown`, `tm-open`) measures a fixed 34×34 CSS px at every width — about 60% of the 44×44 guideline area — on controls that gate airplane-mode, shutdown, and the task manager (F9, PARTIALLY_CONFIRMED — the original list wrongly included `lang-switch`, which actually measures 64×39 and *exceeds* the guideline).

**A genuine, previously-unreported keyboard defect:** opening the mobile hamburger drawer does not move focus into it and does not trap Tab — pressing Tab from an open drawer walks through the topbar, then into ordinary Home-page content sitting *visibly behind the dimmed scrim*, and the sidebar's own nav links never receive focus in a 25-step Tab sequence (responsive-narrow missed-1, a WCAG 2.4.3 focus-order failure on every narrow viewport, found only by the verify pass and missed by all seven of the primary sweep's own findings).

## 5. RTL & internationalisation

**Structural RTL mirroring is a genuine, load-bearing strength.** With zero `[dir="rtl"]` CSS overrides anywhere in the codebase, six independently-implemented subtab components, the sidebar, and the Agenda weekday grid all correctly mirror using native flex/grid direction inheritance (rtl-13, CONFIRMED and unchallenged). Punctuation-joined composites (versions, dates, parenthetical ticker codes) rendered in correct visual order everywhere sampled, but this is **accidental, not designed** — the codebase has zero `<bdi>`/`unicode-bidi:isolate` markup, and every safe instance happens to sit in its own isolated DOM node; the first future string that splices a raw date or version into a translated Arabic sentence template has no guardrail (rtl-14, CONFIRMED, flagged as fragile).

**Where RTL and locale content actually break, in order of reach:**
1. **RC-1 and RC-2 above** (Home briefing cards, Observatory domain labels) are the two most severe, each confirmed in **two unrelated locale families** (ar + zh/de/ja/etc.) — the single strongest cross-corroboration in the whole audit.
2. Markets' entire "Minerals supply (USGS)" section — heading plus both method/caveat paragraphs — is 100% untranslated in Arabic, sitting directly under a carefully and correctly translated paragraph one line above it (rtl-5, CONFIRMED).
3. Insights' Trends stat line collapses into an unlabeled, glued pair of numbers ("29,535 2,342") in Arabic — a mix of hardcoded English fragments with no bidi isolation around the interpolated values, actively more misleading than plain untranslated text (rtl-6, CONFIRMED).
4. Agenda's month grid truncates *English* event names from the **front** (dropping the leading letter, e.g. "…ndependence Day (Bra") because `text-overflow:ellipsis` truncates at the RTL container's logical-end, which is backwards for LTR content sitting inside it (rtl-2, CONFIRMED pixel-for-pixel).
5. The "See all →" disclosure arrow keeps its LTR glyph shape in Arabic instead of mirroring to ←, while Search's own "Analyze →"/"تحليل ←" proves the correct mirrored glyph is achievable elsewhere in the same app — root cause is literal-string concatenation *outside* the translated string, and the same anti-pattern recurs in at least 7 more call sites across Home, Analyze, and diagnostics that were never independently screenshotted (rtl-1, CONFIRMED; missed-2 broadens its reach).
6. Two genuinely distinct translation gaps were originally conflated as one "systemic `.stat .k` gap": Library's 6 stat-tile labels are a **deterministic** locale-file omission (absent from all 12 locale JSONs), while Home's stat strip and no-telemetry sentence are an **intermittent i18n-readiness race** (RC-6 above) — different bugs, different fixes, confirmed only by the verify pass teasing them apart (rtl-3, PARTIALLY_CONFIRMED).
7. Search's result-count line ("result(s) (showing 50) 453") is hardcoded English with non-idiomatic word order that will never translate (rtl-9, CONFIRMED).

**The language switcher itself (invariant #15):** live in-session switching works, but Home's "Trending now" panel is the one Home block the `oo:langchange` re-render handler forgets — every *other* Home block (map, sources, briefing titles, composition figures, Observatory, Activity) has an explicit, self-documented re-render call; `loadHomeTrends` does not, so a live switch can leave it showing the prior language for up to the ~15s poll interval (self-reported PLAUSIBLE, not adversarially verified in this batch).

**CJK-specific (self-reported, no independent verify pass in this batch, weight accordingly):** Chinese keyword extraction produces whole *unsegmented sentences* as "keywords" ("分析人士指出" — "analysts point out" — as a single chip) on Insights' per-country table, while every space-delimited script tested (Latin and Arabic) extracts clean short terms in the identical table — strongly suggesting the tokenizer is whitespace-based with no CJK segmentation step at all. CJK glyphs render through whatever CJK font happens to exist on the host OS (this sandbox: WenQuanYi Zen Hei) since the declared font stack names no CJK family — legible here, but uncontrolled and inconsistent across a real userbase (Windows/macOS/Linux will each substitute differently). Against this, Search/Agenda/Settings/Library chrome (query labels, weekday names, month names, theme/font picker names) translate completely and cleanly in `zh`, and `de/ru/hi/bn` held every fixed-footprint chrome element without clipping at 1440×900 — real, positive counter-evidence that the i18n *plumbing* works; the defects cluster in specific, identifiable spots (RC-1, RC-2, RC-7), not a systemic engine failure.

## 6. Accessibility conditions

This axis was the least covered of the six. **`reduced_motion`, `prefers-contrast:more`, and browser zoom/reflow were never tested by any of the six agents**, despite the harness supporting all three — an honest, stated gap, not a clean bill of health.

`axe()` ran in only one stream (themes-light) and turned up two classes of finding no other agent's manual contrast/overflow probes could have caught: sidebar nav-item labels failing `color-contrast` on the same 5 mispaled light themes named in RC-5 (missed-M1, self-reported/unverified), and `heading-order`/`page-has-heading-one` moderate structural violations on Home in every theme tested (missed-M2, self-reported/unverified) — evidence that a manual selector-based sweep, however careful, has a structural blind spot axe would close.

Focus order: the mobile drawer's missing focus trap (§4) is the one confirmed real keyboard-accessibility defect found this session. The skip-link's actual `:focus`-revealed contrast was never captured in any of the 12+ dark/light/RTL theme checks that flagged its pre-focus ~1:1 ratio as (correctly) benign — an open question, not a pass, in every stream that touched it.

## 7. The 8 GUI skins — do they earn their keep?

**Not reached.** None of the six matrix agents in this batch drove `ui_skin=` at all — no screenshot, no contrast check, no overflow check exists for Aurora, Atlas, Command, Field, Focus, Terminal(-skin), Canvas, or Editorial in this audit. This is a genuine gap against the brief's combinatorics question, not a finding of either quality or complexity, and should be treated as fully open pending a dedicated pass.

## 8. The appearance combinatorics: load-bearing vs. choice-paralysis

Of the 17-theme catalog, direct measurement supports a concrete reduction proposal without touching invariant #12 (the catalog itself must never shrink — this is offered as a design observation both source streams explicitly scoped as non-binding):

- **5 dark themes are near-indistinguishable accent recolors of one base** — slate, midnight, aubergine, garnet, and (more mildly) forest share near-identical near-black backgrounds, layout, and body text with `ink`, differing only in a handful of accent-tied elements (link colour, active-tab underline, button fill) (themes-dark F4, CONFIRMED, though ink itself proved just as hard to tell apart from the five as they are from each other — 6 of 9 read as one family in practice).
- **`light` and `mist` are a near-identical pair** among the true-light themes for the same reason (themes-light F9, CONFIRMED).
- **3 of the 8 themes assigned to the "light" sweep are secretly dark themes** (arctic, solar, sepia — RC-nothing, just a classification fact, themes-light F8 CONFIRMED) — meaning any prior "light vs dark" tallying that used this bucket boundary needs re-keying before it's trusted.
- **`terminal` is the one theme that changes more than hue** — it swaps the entire Settings and Home typography to the bundled JetBrains Mono face app-wide, not just in Settings as first scoped, making it "the model for what a real theme should look like" rather than a colour-picker entry wearing a name tag (themes-dark F8, CONFIRMED and broadened).
- Accent override was verified clean on only 2 of 17 themes (`ink`, `contrast`) — it survives without breaking layout, panel colours, or the independently-correct `--caveat` colour, and is properly isolated from the rest of the palette (themes-dark F7, POSITIVE) — but this is a 2-of-17 sample, not a catalog-wide guarantee.
- Density (compact) and the 7-face typeface picker were each touched only incidentally (2 widths, no dedicated findings) — insufficient evidence either way on whether they are load-bearing or redundant.

**Net picture:** roughly half the dark-theme catalog and one light-theme pair could plausibly collapse into accent-preset variants of two or three real bases (ink, terminal, contrast for dark; light/mist-merged, dawn, mint, paper for light) without a perceptible loss for most users, while cutting the CSS/QA/ratchet surface the invariant-#12 test already protects.

## 9. Aesthetic verdict

Below roughly 1100px and within a single theme family, the app looks genuinely considered. `themes-dark/ink-home.png` reads as a tasteful, restrained default — near-black ground, light-grey body text, a cool blue-grey accent that never fights the content. `themes-dark/terminal-settings.png` is the standout: full monospace typography plus a harder green-on-black value structure gives it real, independent character rather than a hue swap. `responsive-narrow/375_drawer_open.png` shows a mobile hamburger drawer that looks deliberately designed — full labels, a dimming scrim, the Settings footer anchored at the bottom — not an afterthought (undercut only by the focus-trap defect in §4/6, which a screenshot alone can't reveal).

The ugliest single frame captured this session is `responsive-narrow/repro_coach.png` / `320x700_home.png`: the `#oo-tip` tooltip overpainting the network-consent coach's own text at 320px, corrupting the wording of the one bubble whose entire job is disclosure (RC-8) — a small technical bug landing on exactly the surface the project is proudest of. `responsive-wide/w2560-settings.png`, `w2560-search.png`, and `w2560-home.png` show the 1100px-cap problem starkly: a narrow strip of interface adrift in the center of an ultrawide, dark field, next to `w2560-agenda.png`, which visibly uses the same width productively — the clearest before/after pair in the whole audit for RC-topic "wide-screen waste." `rtl-arabic/01-home-card-flip-attempt.png` and `cjk-and-expansion/A-zh-home.png` are the two most visually telling screenshots of RC-1: fully-translated chrome wrapped around briefing-card paragraphs that are, verbatim, 100% English — the app reads as "respects your language directionally, was never finished being written in it" (rtl-arabic's own phrase, independently corroborated by the CJK stream). `responsive-wide/chart-w2560-markets.png` vs `chart-w1280-markets.png` are visually identical despite a >2× wider viewport — the ooChart 900px cap made concrete. `themes-light/crop-dawn-chip.png` shows the "lonely signal"/badge contrast problem (RC-3) at a legibility level a raw ratio number understates: pale text that is genuinely hard to read at a glance, not merely "a bit low."

## 10. Refuted / unreproducible, and what remains unverified

**Refuted or materially corrected on adversarial re-check:**
- themes-dark F3 ("harness excludes own-background, manufacturing false failures on filled buttons") — accurate as a historical diagnosis but **not reproducible against the current, same-day-patched harness**; downgraded to informational/P3.
- rtl-11's headline claim (a single dark-on-dark colour pair recurring identically across Feed/Settings/Custody at 1.08:1) — **refuted**: the named elements' real background is a medium blue button fill (~6.65:1, passing), and the claim traces to the same pre-fix harness bug as above. The two Home-surface items in the same finding (the chip and the tier-badge near-miss) *did* independently reproduce and stand.
- responsive-wide's card-caveat-no-measure-cap — the CSS defect and Feed-page numbers reproduced exactly, but its characterization was wrong: the wide `.card-caveat` instance on Feed is a generic page-level UI note, not a per-article trust caveat, and its claimed extension to Home's flip-cards is refuted by direct measurement (those measure 267–307px, nowhere near unbounded).
- responsive-wide's library-overview-sparse-island — direction correct (a fixed-size content island in a mostly-empty page), but both cited magnitude numbers (panel width, remaining whitespace) were arithmetically inconsistent with the claimant's own screenshot dimensions; corrected numbers are smaller but the finding still stands qualitatively.
- Several single-theme or single-width scope claims were narrowed rather than refuted outright: themes-light F4/F5's "8/8 themes fail" corrected to 5/8 (with `solar` swapped in for `light` in F5); responsive-narrow F1's "320–480px" corrected to "<346px only"; responsive-wide's subtab-wrap-midrange per-width tab counts corrected once a permanently-hidden zero-rect tab was found inflating them; responsive-wide's F7/601px scope widened (the same defect recurs worse at 900–1024px) rather than narrowed.

**Remains genuinely unverified**, stated plainly rather than glossed:
- GUI skins gallery (§7), `reduced_motion`, `prefers-contrast`, browser zoom/reflow — zero coverage, any of the six streams.
- The skip-link's actual `:focus` state, anywhere it was checked.
- `.act-host`'s "96px reserved while a collection pass is visible" behavior (invariant #3) — every fixture used was an idle/stopped corpus, so this measured 0×0 everywhere; genuinely untested, not passing.
- `.gw-lang` (first-launch picker) and `.carousel-dot` (Home lead carousel) — inferred subject to RC-4 by shared CSS shorthand, never independently rendered.
- Every RTL×narrow-viewport and every non-English×non-ink-theme combination — three matrix axes were each swept but never crossed.
- The cjk-and-expansion stream's own findings (F1, F5–F9) carry no adversarial verify pass in this batch — treat them as corroborating context for the RTL findings they overlap (RC-1, RC-2, RC-7), not as independently confirmed on their own.