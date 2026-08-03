/**
 * Node test for smallMultiplesSvg -- the renderer the honest-gaps pass MISSED.
 *
 * THE DEFECT. When gaps were fixed across the chart toolkit, dashChartSvg and
 * ooChart were repaired and this one was not, even though its own sibling
 * slopeChartSvg -- thirty lines above it in the same file, written in the same
 * batch -- already breaks at holes ("break at gaps, never bridge"). Left alone,
 * smallMultiplesSvg emitted ONE unbroken <polyline> over every point, and
 * `Y(null)` evaluates to `padT + (h-padT-padB) * (1 - null/maxV)` = the zero
 * baseline. So a period with no data was published as a MEASURED ZERO, which is
 * strictly worse than the bridged line: an invented observation rather than an
 * invented connection.
 *
 * Three further gaps rode along and are pinned here too: a neutral corpus count
 * painted in market up=green/down=red, an `n` that counted array slots rather
 * than real observations, and panels dropped silently so a grid of four read as
 * "these are the four".
 *
 * THE OPPOSITE FAILURE IS EQUALLY DISHONEST -- a fabricated gap invents an outage,
 * an over-eager disclosure invents missing data -- so these come in PAIRS, the
 * doctrine tests/series_gaps_node_test.js already established.
 *
 * The function is EXTRACTED FROM THE REAL app.js, brace-matched from the BODY
 * brace: a re-typed copy would pass while the shipped code stayed broken, and the
 * naive first-brace extractor truncates at a default parameter's `{}` so every
 * assertion would pass vacuously (the recorded house lesson).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const fs = require("fs");
const path = require("path");
const APP = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app.js"), "utf-8");

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

function extract(head) {
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = APP.indexOf("(", at); j < APP.length; j++) {
    if (APP[j] === "(") p++;
    else if (APP[j] === ")") { p--; if (p === 0) { i = APP.indexOf("{", j); break; } }
  }
  let depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces in " + head);
}

const SPARSE = Number((APP.match(/const _SPARSE_BAR_MAX\s*=\s*(\d+)/) || [, "10"])[1]);
assert(Number.isFinite(SPARSE) && SPARSE > 1, "could not read _SPARSE_BAR_MAX from app.js");

const sandbox = {};
new Function(
  "const _GAP_FACTOR = " + (APP.match(/const _GAP_FACTOR = (\d+)/) || [, "3"])[1] + ";\n"
  + "const _SPARSE_BAR_MAX = " + SPARSE + ";\n"
  // Stubs only for things that are NOT under test. _missing and _seriesRuns are
  // extracted from the real file for the same reason the function is: they encode
  // the very trap (isFinite(null) === true) these assertions exist to catch.
  + "const esc = (s) => String(s);\n"
  + "const fmtNum = (v) => String(v);\n"
  + "const ooViz = { gridLayout: (n, o) => ({cols: Math.min(n, (o && o.maxCols) || 4)}),"
  + "               isMissing: (v) => v === null || v === undefined || Number.isNaN(v) };\n"
  + "const window = {};\n"
  + "const openAnalysisFor = () => {};\n"
  + APP.slice(APP.indexOf("const _missing = (v) =>"), APP.indexOf("const _GAP_FACTOR")) + "\n"
  + extract("function _seriesRuns(") + "\n"
  + extract("function smallMultiplesSvg(") + "\nthis.smallMultiplesSvg = smallMultiplesSvg;"
).call(sandbox);
const { smallMultiplesSvg } = sandbox;

const dense = (vals) => vals.map((v, i) => ({date: `2026-07-${String(i + 1).padStart(2, "0")}`, count: v}));
const run = (n, v) => Array.from({length: n}, () => v);
const polylines = (svg) => (svg.match(/<polyline/g) || []).length;
const rects = (svg) => (svg.match(/<rect/g) || []).length;

// --------------------------------------------------------------------------- //
//  A hole is drawn as a hole -- and only where there is one
// --------------------------------------------------------------------------- //
test("a gap BREAKS the line instead of bridging it", () => {
  const pts = dense([...run(6, 5), null, null, ...run(6, 9)]);
  const svg = smallMultiplesSvg([{label: "en", points: pts}]);
  assert(polylines(svg) === 2, `expected two runs around the hole, got ${polylines(svg)}`);
});

test("...and an UNBROKEN series is NOT split (the fabricated-gap twin)", () => {
  const svg = smallMultiplesSvg([{label: "en", points: dense(run(14, 5))}]);
  assert(polylines(svg) === 1, `a complete series must draw ONE line, got ${polylines(svg)}`);
});

test("a null is never plotted at the zero baseline", () => {
  // The whole defect in one assertion: Y(null) lands exactly on baseY, so a
  // published gap became a measured zero. Count the plotted vertices instead of
  // trusting the shape -- 14 slots, 2 of them holes, must plot 12 points.
  const pts = dense([...run(7, 4), null, null, ...run(5, 4)]);
  const svg = smallMultiplesSvg([{label: "en", points: pts}]);
  const verts = (svg.match(/points="([^"]+)"/g) || [])
    .reduce((n, m) => n + m.split(" ").length, 0);
  assert(verts === 12, `expected 12 plotted vertices for 12 observations, got ${verts}`);
});

test("a lone survivor between two holes stays visible", () => {
  // A one-point run has no line to draw; without a mark it would vanish entirely,
  // which reads as "nothing was ever recorded here".
  const pts = dense([...run(5, 3), null, 7, null, ...run(5, 3)]);
  const svg = smallMultiplesSvg([{label: "en", points: pts}]);
  assert(/<circle/.test(svg), "an isolated observation must still be drawn");
});

test("in sparse (bar) mode a gap emits NO bar, not a zero-height one", () => {
  const pts = dense([3, 4, null, 6]);            // below _SPARSE_BAR_MAX -> bars
  const svg = smallMultiplesSvg([{label: "en", points: pts}]);
  assert(rects(svg) === 3, `3 observations must yield 3 bars, got ${rects(svg)}`);
});

// --------------------------------------------------------------------------- //
//  A neutral count is not a market ticker
// --------------------------------------------------------------------------- //
test("opts.neutral paints a corpus count in the accent, not green/red", () => {
  // Fewer articles in a language is not "bad". Same rule, same opt-in, as
  // dashChartSvg's -- which the Library tiles already pass.
  const svg = smallMultiplesSvg([{label: "en", points: dense(run(12, 5))}], {neutral: true});
  assert(svg.includes("var(--accent)"), "neutral series must use the accent colour");
  assert(!svg.includes("var(--ok)") && !svg.includes("var(--err)"),
    "neutral series must not carry up=good/down=bad semantics");
});

test("...while a directional caller keeps its colours (the twin)", () => {
  const rising = smallMultiplesSvg([{label: "en", points: dense([...run(6, 1), ...run(6, 9)])}]);
  assert(rising.includes("var(--ok)"), "a rising directional series stays green");
  const falling = smallMultiplesSvg([{label: "en", points: dense([...run(6, 9), ...run(6, 1)])}]);
  assert(falling.includes("var(--err)"), "a falling directional series stays red");
});

test("direction is read from real observations, not from a gap", () => {
  // `null >= x` coerces to 0, so a trailing hole used to decide the colour --
  // a clearly rising series would have been painted as falling.
  const pts = dense([...run(6, 1), ...run(5, 9), null]);
  const svg = smallMultiplesSvg([{label: "en", points: pts}]);
  assert(svg.includes("var(--ok)"), "a rising series ending in a gap is still rising");
});

// --------------------------------------------------------------------------- //
//  n means observations, and what was dropped is said
// --------------------------------------------------------------------------- //
test("n counts real observations, never array slots", () => {
  const pts = dense([...run(4, 2), null, null, null, ...run(3, 2)]);
  const svg = smallMultiplesSvg([{label: "en", points: pts}]);
  assert(/n=7\b/.test(svg), `n must report the 7 observations, not the 10 slots: ${svg.slice(0, 400)}`);
  assert(!/n=10\b/.test(svg), "n=10 would claim evidence that was never collected");
});

test("a panel with nothing to plot is disclosed, not silently dropped", () => {
  const svg = smallMultiplesSvg([
    {label: "en", points: dense(run(12, 5))},
    {label: "fr", points: dense([null, null, null])},
    {label: "de", points: []},
  ]);
  assert(/not shown: 2/.test(svg), `the two empty panels must be disclosed: ${svg.slice(-300)}`);
});

test("...and nothing is disclosed when nothing was dropped (the twin)", () => {
  const svg = smallMultiplesSvg([
    {label: "en", points: dense(run(12, 5))},
    {label: "fr", points: dense(run(12, 3))},
  ]);
  assert(!/not shown:/.test(svg), "an over-eager disclosure invents missing data");
});

test("an all-empty grid says so rather than rendering an empty box", () => {
  const svg = smallMultiplesSvg([{label: "en", points: []}, {label: "fr", points: dense([null])}]);
  assert(/No series to show yet/.test(svg), "an empty grid needs an honest empty state");
});

console.log(`\n${passed} passed`);


// --------------------------------------------------------------------------- //
//  The caveat may claim only what the data can exhibit
// --------------------------------------------------------------------------- //
test("the gap sentence appears ONLY when the data actually contains a gap", () => {
  // The one shipped caller feeds _window_daily_series, which OMITS zero-count days
  // rather than publishing them as null -- so no hole ever reaches this renderer
  // from it. A caveat advertising gap handling on data that cannot contain a gap is
  // a fabricated assurance, which is the class of claim this function was just
  // fixed to stop making.
  const withGap = smallMultiplesSvg([{label: "en", points: dense([...run(6, 4), null, ...run(6, 4)])}]);
  assert(/drawn as gaps, never as zero/.test(withGap), "a real gap must be disclosed");
  const noGap = smallMultiplesSvg([{label: "en", points: dense(run(13, 4))}]);
  assert(!/drawn as gaps, never as zero/.test(noGap),
    "claiming gap handling on gapless data promises the user something unverifiable");
});

test("a MEASURED zero stays visible and is not mistaken for a gap", () => {
  // In bar mode -- the only mode the shipped caller reaches -- a true 0 renders as
  // height="0.0", pixel-identical to the gap that emits no rect at all. The 2px
  // value-cap marks the real value without inventing height, the same device
  // dashChartSvg uses for a flush minimum.
  const zeroed = smallMultiplesSvg([{label: "en", points: dense([0, 5, 3])}]);
  const gapped = smallMultiplesSvg([{label: "en", points: dense([null, 5, 3])}]);
  assert(rects(zeroed) > rects(gapped),
    "a measured zero must draw something a gap does not");
});
