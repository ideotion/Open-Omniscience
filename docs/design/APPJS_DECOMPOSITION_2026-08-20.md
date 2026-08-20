# Decomposing `src/static/app.js` — the seam map

**Status:** design of record for structural-debt row **S-3** (`docs/ROADMAP.md`).
**Date:** 2026-08-20. **Session:** solo, per the S-3 brief (never run beside another lane).
**Base:** `origin/main` @ `ba49850`.

Every number below is **measured** from the tree at that base, by scripts committed with this
work (`scripts/appjs_decomposition_check.py`, plus the statement inventory described in §2).
Nothing here is estimated, and where a measurement refutes an assumption this document says so.

---

## 1. What S-3 actually is

`docs/ROADMAP.md` records the debt as: *`src/static/app.js` is 21,300 lines / 1,046 functions in
a single indented global scope; the real cost is parse/compile on the 2-core field VMs; splitting
it browser-unverified is the interleaved-shared-helper hazard.* It names the unblocker as a
standing browser harness (R3 / `ui_walk`), which is also 0.3 gate row 8 — and that harness now
exists.

Re-measured today the file is **23,896 lines / 1,474,394 bytes**, carrying **1,436 top-level
statements**: 641 `function`, 448 `async function`, 120 `const`, 182 `let`, and **45 load-time
side-effect statements**. (The ROADMAP's 21,300/1,046 is a stale snapshot, not an error — the
file has grown since. The row's wording is updated by this work.)

The debt is real but the *hazard* turns out to be much smaller than the ledger feared, and the
rest of this document is mostly about proving that before touching a line.

---

## 2. The three measurements that decide the design

### 2.1 There are no duplicate top-level names — **0**

The ledger's standing lesson is that *duplicate top-level JS function names silently override —
grep before declaring*. A statement-level inventory (a string/template/regex/comment-aware
scanner that segments the file into top-level statements and verifies the segments **tile the
file exactly**, zero gaps) finds **zero** duplicate names across all 1,391 named declarations.

That matters because it means a contiguous split cannot change which definition wins: there is
never more than one.

### 2.2 Only **one** construct depends on function hoisting

Splitting one classic script into several changes exactly one thing: hoisting no longer spans
the whole file. So the question is *which load-time code reaches forward to something declared
later*.

Scanning every top-level `const`/`let`/`var` initializer and every side-effect statement for
identifiers evaluated **at load time** (identifiers inside function bodies and arrow bodies are
deferred and therefore safe) finds:

| Kind | Count | Where |
|---|---:|---|
| Forward references to a **function** | **12** | all in `TAB_LOADERS`, one object literal at line 1857 |
| Forward references to a **`const`/`let`** (TDZ) | **0** | — |

`TAB_LOADERS` maps a tab id to its loader as a **bare function reference** (`home: loadHome`),
and eleven of its twelve loaders are declared later in the file. Every *other* registry in the
file — `_ADV_LOADERS`, `_LIB_VIEW_LOADERS`, `LIVE`, and `TAB_LOADERS`' own `library:` entry —
already wraps its target in an arrow (`() => { loadScheduler(); }`), which defers the lookup and
is immune to load order.

So the single prep change this decomposition needs is to make `TAB_LOADERS` consistent with the
four registries beside it. That is one commit, reviewable on its own, and it is **not** a
workaround invented for the split — it is the pattern the file already uses everywhere else.

**Zero TDZ references** is the stronger half of this result: it is what makes cutting between any
two top-level statements safe for `const`/`let`, which cannot be hoisted at all.

### 2.3 ES modules are not viable here — **413 globals** say so

The brief asks for native ES modules *if and only if* they verify clean. They do not, and the
reason is structural rather than a limitation of the harness.

The SPA drives itself through inline handlers: **311** `on*="…"` attributes in `index.html` and
**266** more generated inside `app.js` template strings — **577** in total, naming **413 distinct
functions**. An inline handler resolves its callee against the **global** scope and nothing else.
ES modules are module-scoped, so every one of those 413 names would need an explicit
`window.X = X` re-export, hand-maintained forever, with a missing entry failing only as a dead
click in a browser. `src/static/guis/boot.js` corroborates this independently: it polls for the
`showTab` **global** to know when app.js has booted.

**Decision: ordered plain `<script>` tags, one shared global scope, exactly as today.** No
bundler, no build step, no CDN, no import maps. This preserves the dependency-free loopback
posture the project requires, and — see §3 — it also buys a verification property that a
module rewrite could not offer.

Retiring the 577 inline handlers is a real and separate piece of work (the ledger already tracks
it as browser-verify-gated debt, measured at 556 in the 2026-07-28 GUI audit and at 577 now). It
is a prerequisite for ES modules, not part of this change.

---

## 3. The design: contiguous slices, byte-identical concatenation

Each module is a **contiguous run of whole top-level statements**, in original order. Nothing is
reordered, renamed, re-indented or reformatted. The concatenation of the modules, in load order,
is **byte-identical** to today's `app.js`.

That property is the whole point, and it is what makes this change verifiable rather than
merely tested:

```
cat src/static/app-*.js  ==  the pre-split src/static/app.js   (byte-for-byte)
```

Given byte-parity, the only regressions physically available are:

1. **load order / hoisting** — bounded by §2.2 to the single `TAB_LOADERS` construct, fixed in
   its own prep commit;
2. **a module failing to load** — a 404 or a wrong MIME type, which the browser walk catches as
   a wave of missing globals rather than a subtle behaviour change;
3. **the prep change itself** — one object literal, reviewed on its own.

Everything else — every helper, every closure, every string, every comment — is provably
unchanged, because the bytes are unchanged.

### Why not thematically pure modules

The brief suggests a "chart toolkit" module. **The chart toolkit is not contiguous.** Measured:
`fmtNum`/`_SPARSE_BAR_MAX`/`_FIG_STYLES`/`honestTicks`/`dashChartSvg` sit at ~11216–11900,
*then* markets category tabs, *then* `ooChart`/`sparkSvg` at ~12298, *then* `ooSubtabs` and
`ooTimeScope` at ~12894 — interleaved with the Markets board that grew up around them.

Extracting them into one file requires **reordering declarations**, which forfeits byte-parity
and reintroduces exactly the interleaved-shared-helper hazard the ledger warns about — the
hazard that kept S-3 shut for a year. Function declarations would survive reordering (they
hoist), but `const`/`let` initializers that reference each other would not, and proving the
absence of such a chain across 302 lexical declarations is a much weaker guarantee than "the
bytes did not change".

**So: contiguity wins over thematic purity, and the modules are named for what they actually
contain.** The interleaving is recorded here as a finding. A later, separately-verified pass may
regroup the chart toolkit; it should be its own change with its own browser evidence, not a
rider on this one.

### The 17 modules

| # | Module | Lines | Decls | Load-time stmts | Contents |
|--:|---|--:|--:|--:|---|
| 1 | `app-core.js` | 1830 | 119 | 6 | core helpers (`$`, `esc`, `safeUrl`), frontend error capture, activity/toast, language menu, first-launch guide, airplane + network consent + egress window, adaptive polling, vitals, task manager + job controls, api client + retry/health/crash screen |
| 2 | `app-shell.js` | 603 | 58 | 3 | tab nav + `TAB_LOADERS` + `showTab`, UI prefs/themes/accents/faces, keybindings, Settings categories + advanced foldouts, drawer, command palette + omnibar |
| 3 | `app-home.js` | 1413 | 96 | 0 | Home stats/latest/channels/recent/trends/alerts, briefing + Lead cards + carousel, link preview, research draft, source integrity + annotations |
| 4 | `app-agenda.js` | 1082 | 91 | 0 | Agenda views, calendars/feeds, Bulletin |
| 5 | `app-gov-law.js` | 457 | 26 | 0 | Governments (indicators/countries/map), World Law tracker |
| 6 | `app-settings.js` | 1456 | 87 | 0 | docs/help viewer + health pill, Ollama install + model catalog, LLM prompts, language detection, custom extractors, Settings load/save, keyword filter, card catalog, newsletter + PDF import |
| 7 | `app-backup.js` | 1839 | 73 | 0 | unified export/import dialogs + progress, folder + volume backup, fetch mode, at-rest encryption, uninstall |
| 8 | `app-library.js` | 1121 | 74 | 1 | Library views, storage footprint, metric/qualification/language tiles, composition figures, live poller |
| 9 | `app-sources.js` | 906 | 71 | 0 | coverage map + regions, source management, batch ingest, scheduler + rate mode |
| 10 | `app-markets.js` | 2419 | 110 | 0 | Indices + Commodities boards, feeds/rules, **and the shared chart toolkit** (`dashChartSvg`, `ooChart`, `ooSubtabs`, `ooTimeScope`) — see the interleaving note above |
| 11 | `app-insights.js` | 1112 | 71 | 0 | Insights: families, concept browse, super-groups, keyword explorer, cited sources, convergences, watches |
| 12 | `app-diagnostics.js` | 1710 | 85 | 0 | diagnostics runs, re-index/cleanup, AI sweeps, gold-set + model bench, AI check |
| 13 | `app-corpus.js` | 1427 | 62 | 0 | corpus window, mindmap + graph, keyword rendering, trends + slope/multiples, chart enlarge |
| 14 | `app-map.js` | 2655 | 168 | 0 | ooMap choropleth + lenses, temporal map, region/folder pickers, wiki dumps/pages/changes, OSM regions, official-statistics panels |
| 15 | `app-analysis.js` | 1823 | 123 | 0 | the analysis window (tabs, facets, price/trend/related/mindmap/articles), search, synthesis, bulk LLM |
| 16 | `app-ai-tools.js` | 1719 | 77 | 0 | candidates + qualification gates, AI settings/pill/backends/vLLM, summarize/translate/framing, custody |
| 17 | `app-boot.js` | 324 | 0 | 35 | the boot block: load-time wiring, initial render, subtab construction |

**23,896 lines total — the file, tiled exactly.** All 17 cut points were verified to land on a
top-level statement boundary; the sum of the module lengths equals the file length.

`app-boot.js` must load **last**: it holds 35 of the 45 load-time statements, including
`showTab(...)`, the `ooSubtabs(...)` constructions and the event wiring that assume every
definition already exists.

---

## 4. What else references `app.js`, and what each needs

A grep across the tree (not a guess) finds five classes of reference:

| Referencing | Count | Needs |
|---|--:|---|
| `src/static/index.html` | 1 `<script>` | **replace with 17 ordered tags**, `app-boot.js` last. It is the ONLY page that loads app.js (`taskmanager.html`, `investigate.html`, `unlock.html` load `i18n.js` only) |
| `src/static/sw.js` | `SHELL` precache list | **add the modules and bump `CACHE`**. The worker is network-first and never controls `/`, so an online user self-heals; the list still has to be right for the offline case |
| `scripts/i18n_report.py` | `_AUX_JS = ("app.js", "reader.js")` | **must scan every module.** This is load-bearing: gate 2 (`--max-untranslatable`) and gate 3 (`--max-unkeyed-t-calls`) read these files, and the 2026-07-28 audit's finding I-1 was precisely that the instrument had been pointed at the wrong file. Leaving this unchanged would silently blind both ratchets to ~22k lines of UI engine |
| `tests/` | **151 read sites** across ~10 shapes | **see below** — the sharpest hazard |
| prose in `src/api/main.py`, `src/api/insights.py`, `src/briefing/card_diagnostics.py`, `src/analytics/reindex_job.py`, `src/monitoring/ui_walk*.py`, `guis/boot.js` | comments only | nothing (they name app.js as the place a behaviour lives; still true) |

### 4.1 The test hazard: negative assertions would pass **vacuously**

161 test files assert against JavaScript source; 151 sites read `app.js` directly. If `app.js`
becomes one seventeenth of the UI engine, then:

* a **positive** assertion (`assert "function ooChart" in app`) fails loudly — annoying but safe;
* a **negative** assertion (`assert_absent(app, "…")`, `assert X not in app`) **passes for free**,
  against a file that no longer contains the thing it is checking.

That is the exact vacuity failure `tests/js_source_helper.py` was created to end, and it would be
reintroduced at 151 sites at once, silently.

**The fix:** `read_static("app.js")` returns the **concatenation of the app modules in the order
`index.html` loads them**, derived from `index.html` itself so it cannot drift. For source-
assertion purposes that string is the semantic equivalent of today's file — same content, same
order — so every existing assertion, positive and negative, stays exactly as meaningful as it is
today. Sites that read the path directly are migrated to the helper.

Reading the order from `index.html` rather than a hand-kept list is the same discipline as the
i18n scope guard: a list maintained by hand drifts from the thing it describes, silently.

---

## 5. The verification bar

`scripts/appjs_decomposition_check.py` (committed with this work) drives the real app in Chromium
through the standing `ui_walk` / `ui_walk_playwright` instrument — never a parallel driver — and
answers three questions per wave.

**1. Do all the globals still resolve?** The baseline run records which names actually resolve
**in the browser** (a `typeof` through an indirect `eval`, which reaches the global *lexical*
environment — a bare `window[name]` lookup would miss all 302 top-level `const`s). Every later
run diffs against that frozen set. A module that fails to load, a slice that lost a declaration,
or a load-order mistake surfaces as a **named missing global**, not as a mystery dead click.

**2. Does every surface still render?** The flagship + backlog surfaces, plus every top-level tab
and every subtab of every tab, recording `pageerror` **separately from** `console.error` — the
2026-07-22 lesson, where "384 JS errors" were 100 % rate-limit console lines and zero uncaught
exceptions.

**3. What does parse/compile cost?** Chrome's own `Performance.getMetrics` → `ScriptDuration`,
under CDP CPU throttling, median of N cold loads in fresh contexts (no code-cache carry-over).

### Baseline, measured before any change

| | State B (empty) | State C (populated, 450 articles) |
|---|---|---|
| Steps walked | 52 | 52 |
| `pageerror` | **0** | **0** |
| Navigation errors | **0** | **0** |
| Resolving globals | **1393** | **1393** |

### Scope, stated honestly

Chromium in a remote sandbox, states **B** and **C**. State A (virgin) is deliberately absent: it
renders `unlock.html`, which does not load `app.js` at all, so it cannot exercise this change.
Surfaces verified here graduate to **"Chromium-verified (remote sandbox) · awaiting human UX
pass"** — never the Gecko-verified (VM) bar, and never a substitute for the maintainer's own pass.

A green run proves the app boots, every tab and subtab renders, and every global still resolves.
It does not prove that every one of the 577 inline handlers still does the right thing when
clicked; byte-parity is what covers that, which is why byte-parity is the primary bar and the
browser walk is the check on the things byte-parity cannot cover.

---

## 6. Order of work

Each step is its own commit, and each is independently revertible.

| Step | Change | Bar |
|---|---|---|
| 0 | this document + the check script | — |
| 1 | **prep:** wrap the 12 `TAB_LOADERS` entries in arrows | full walk green; the file is otherwise untouched |
| 2 | **prep:** `read_static("app.js")` returns the module concatenation, read from `index.html`; migrate the 151 direct read sites | full suite green (the concatenation is byte-identical to the file, so nothing should move) |
| 3 | **prep:** widen `i18n_report.py` `_AUX_JS` to the module list | all three i18n gates re-run **separately**, per the recorded lesson that gate 1 passing is no evidence about gate 2 |
| 4–8 | the five extraction waves | per wave: byte-parity of the concatenation, `node --check` on every module, duplicate-name guard, full suite, **full browser walk on both states** |
| 9 | `sw.js` SHELL + `CACHE` bump | walk green |
| 10 | measure parse/compile after; update `ROADMAP` S-3 and `DESIGN.md` | the number, whatever it says |

If a wave's walk regresses anything, that wave is **reverted**, not patched forward — a
half-migrated global scope is the one state in which the byte-parity guarantee does not hold.

---

## 7. Findings recorded along the way

* **The chart toolkit is not contiguous** (§3). Regrouping it is a separate, browser-verified
  change.
* **`TAB_LOADERS` was the only hoisting-dependent construct in 23,896 lines** — and the four
  registries beside it already had the safe shape. The inconsistency, not the pattern, was the
  problem.
* **577 inline handlers naming 413 distinct globals** is the measured blocker for ES modules,
  and the number to watch if that path is ever wanted. It has grown since the 2026-07-28 audit
  measured 556.
* **The ROADMAP's S-3 figures were stale** (21,300 lines / 1,046 functions vs 23,896 / 1,089
  function declarations today). Updated by this work.
