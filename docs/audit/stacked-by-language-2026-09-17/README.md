# Q502's stacked bands and Q417's aggregate hover, in a browser — 2026-09-17

**Status: Chromium-verified (remote sandbox) · awaiting human UX pass.**
Q1128 = a's bar is *Chromium in the sandbox **plus** the maintainer's own click-through*.
This is the first half only.

- `walk.py` — the walk, with its reasoning in the docstring
- `report.json` — everything read back off the rendered page
- `stacked-<lg>.png` — the stacked view in each of the five locales
- `aggregate-hover-<lg>.png` — the Insights term-bar rows

Ran against a seeded store at `127.0.0.1:8010`, 1280×900, five locales
(`en · ar · zh · ja · hi`).

## What it measured, and why each thing needed a browser

`tests/stacked_series_node_test.js` drives the stack's arithmetic, its five refusals and
its two-dimensional hit test as real code; `tests/term_bars_hover_node_test.js` drives the
hover string. Neither can see a canvas, a real pointer, or a translated page.

**The canvas is read back as PIXELS.** A chart that paints nothing satisfies every source
assertion ever written about it, so the walk samples the canvas on a coarse grid and
counts distinct colours covering a real area. Every locale: **7 area colours over 1,335
painted samples**, no stack refusal, no page errors, `overflow_px: 0`, `ar` at `dir=rtl`.

**And looking at the picture is what caught the biggest defect in this slice.** The first
rendering drew filled BANDS — polygons between measured points — so this corpus' two
timestamps became six wedges sweeping diagonally across a week, a trend the corpus never
measured. That is precisely what invariant #16's sparse rule exists to prevent (*"NEVER
interpolation faking a curve through 3 points"*), and no assertion in either node suite
could see it: the arithmetic was right, the refusals were right, and the picture was a
lie. A stack now obeys the same `_SPARSE_BAR_MAX` threshold as every other series in the
component and is drawn as stacked COLUMNS at the timestamps that exist. The pixel count
falling from 18,136 to 1,335 is that fabricated area being removed.

**The hit test is exercised against the projection `draw()` actually built**, at the real
device-pixel ratio, from a real pointer event — the only place it and the node suite's
arithmetic can disagree. Two points at the same x and different heights, in every locale:

| | reported |
|---|---|
| low (y = 92 % of the plot) | `eng: 7 mentions · running total 7 · 2026-09-14` |
| high (y = 30 %) | `fra: 5 mentions · running total 12 · 2026-09-14` |

Different bands, correct running totals. Before this slice's fix the two were identical:
the pick compared TIME only, every band shares the timestamp grid, so it tied on every
point and answered with the first series iterated — **the bottom band, wherever the reader
pointed**.

**Every new string renders in the reader's own language** (`caveat_is_english: false` in
all five). The long overlap caveat, the running-total readout and the "By language" control
were each read back off the page, not inferred from the catalogue files.

**Q417's breakdown reaches the bubble, not just the DOM.** 24 rows in Insights → Trends,
**2** carrying a breakdown — selective, as the ruling needs it to be: a breakdown on every
row would train the reader to ignore the one that means something. The bubble, read back on
both the mouse and the keyboard path:

```
climate — 22 mentions · 7 articles · trend: 22 mentions — new in this period …
  — Across languages: English 9 · French 7 · German 3 · Spanish 3
climate — 22 إشارات · 7 مقالة · الاتجاه: … — عبر جميع اللغات: الإنجليزية 9 · الفرنسية 7 …
```

This is the defect the walk existed to catch. The breakdown was first put in the row's
`title`, which is true in the DOM at render time and **destroyed by the first hover**:
these rows carry `data-kwstat`, and `ooKwStatInit.applyTo` overwrites both the title and
the bubble text with live keyword stats. It now rides `data-oo-tip-extra`, which that
handler appends rather than replaces.

## What the walk got wrong about itself, twice

Recorded because a walk that reports a product defect it does not have is worse than one
that reports nothing.

1. **`hi` "did not offer the view".** It did. Chasing it found a REAL race behind it —
   `loadAnalysis` built the lens one line above the `await OOI18N.ready` it had just been
   given, so `hi` issued the trend request twice, once without `ui_lang`, and a Trend click
   inside that window rendered from `null` params (the literal word, with no lens). Both
   fixed; `hi` now issues one request.
2. **`window._insSubtabs` is not a thing.** It is a module-level `let`, which in a classic
   script is not a window property, so the navigation silently did nothing and the walk
   reported **0 rows** as if the surface were empty. It clicks the button now. The same
   shape cost the first bubble read: a `wait_for_function` whose regex was broken by a
   raw-string escape resolved instantly, and the read landed before the stats fetch
   returned. The walk now reads the bubble's whole state — class, computed style and text —
   so an empty string can never again be mistaken for a convention that did not fire.

## Not covered

The refusal paths (`gap`, `indexed`, `log`, `one-series`) are driven in the node suite;
this corpus stacks cleanly, so `dataset.stackRefusal` is absent in every locale here and
the refusal SENTENCES were not seen on screen. One engine only (Chromium). The Arabic ring
form `المناخ` still appears as its own separate row with no breakdown — that is the gap
`S8`/Q507's folding exists to close, measured here as a before.
