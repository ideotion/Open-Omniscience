/**
 * PRH-31: a daily sparkline drawn on the WINDOW, not on its own points.
 *
 * THE DEFECT. `daily_series` / `_window_daily_series` omit days that carry no
 * mentions -- honest about the DATA, and a lie about TIME the moment a renderer
 * places points by index. `dashChartSvg`'s default X is `padL + plotW * i/(n-1)`,
 * so a series holding day 1 and day 5 draws them ADJACENT and a reader sees a run
 * where there was a four-day gap. The backlog's own words: "the index axis
 * compresses -- day 1 and day 5 render adjacent".
 *
 * WHY NOT THE ZERO-FILL THE BACKLOG SUGGESTED. The same renderer already carries
 * the opposite convention on the same surface -- it prints "The line breaks where
 * nothing was recorded -- a gap is not a zero" -- and it already implements a real
 * calendar axis (`opts.t0`/`opts.t1`) built for exactly this. Filling zeros would
 * put two conventions on one quantity and would also defeat invariant #16's
 * sparse-series rule, since a 30-day window would always carry 31 points and the
 * bar mode (n < 10) could never fire again.
 *
 * This suite drives the REAL `dashChartSvg` extracted from the shipped modules.
 * A re-typed copy would pass while the shipped chart was broken.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const APP = require("./app_source.js").appJs();

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

// The real renderer plus the helpers it closes over, all extracted from the shipped
// source. Anything genuinely external (esc, i18n, the toolkit's number formatting)
// is stubbed at the boundary -- never the geometry under test.
const sandbox = {};
new Function(
  "const _SPARSE_BAR_MAX = " + (APP.match(/_SPARSE_BAR_MAX\s*=\s*(\d+)/) || [, "10"])[1] + ";\n"
  + "function esc(s){ return String(s == null ? '' : s); }\n"
  // Number FORMATTING is not the geometry under test; the axis labels only have to
  // exist for the SVG to assemble. Stubbing these at the boundary keeps the slice
  // small without touching a single coordinate.
  + "function fmtNum(v){ return String(v); }\n"
  + "function _govCompact(v){ return String(v); }\n"
  + "const window = { OOI18N: null };\n"
  + APP.slice(APP.indexOf("const _missing = (v) =>"), APP.indexOf("const _GAP_FACTOR")) + "\n"
  + "const _GAP_FACTOR = " + (APP.match(/const _GAP_FACTOR = (\d+)/) || [, "3"])[1] + ";\n"
  + extract("function _seriesRuns(") + "\n"
  + extract("function honestTicks(") + "\n"
  + extract("function _allInteger(") + "\n"
  + extract("function _axisNum(") + "\n"
  + extract("function _timeLabelFmt(") + "\n"
  + extract("function _chartAria(") + "\n"
  + extract("function _chartSrTable(") + "\n"
  + extract("function dashChartSvg(") + "\n"
  + "this.dashChartSvg = dashChartSvg;"
).call(sandbox);

const { dashChartSvg } = sandbox;

/**
 * The CENTRE x of every mark the chart drew.
 *
 * Centres, not left edges: a bar is drawn from `cx - bw/2` CLAMPED to the plot,
 * so the first and last bar's left edge is pinned to the padding and reading
 * `x=` directly reports a spacing the chart did not use. Measuring left edges
 * made the evenly-spaced index case look uneven (113 vs 124) -- an artefact of
 * the clamp, not of the placement under test.
 */
function xs(svg) {
  const out = [];
  for (const r of svg.match(/<rect x="([0-9.]+)"[^>]*width="([0-9.]+)"/g) || []) {
    const m = r.match(/x="([0-9.]+)"[^>]*width="([0-9.]+)"/);
    out.push(parseFloat(m[1]) + parseFloat(m[2]) / 2);
  }
  for (const p of svg.match(/points="([^"]+)"/g) || []) {
    for (const pair of p.match(/points="([^"]+)"/)[1].trim().split(/\s+/)) {
      out.push(parseFloat(pair.split(",")[0]));
    }
  }
  for (const c of svg.match(/<circle cx="([0-9.]+)"/g) || []) {
    out.push(parseFloat(c.match(/cx="([0-9.]+)"/)[1]));
  }
  return out;
}

// A seven-day window in which only days 1, 2 and 6 carry mentions -- exactly the
// shape the omit-zero-days series produces.
const GAPPED = [
  { observed_on: "2026-09-01", price: 4 },
  { observed_on: "2026-09-02", price: 6 },
  { observed_on: "2026-09-06", price: 5 },
];
// The window opens two days BEFORE the first point on purpose: a mark sitting
// exactly on the plot edge has its bar clamped, and the clamp would then be
// measured as if it were placement. The gap ratio under test is between the
// second and third marks, which no clamp touches either way.
const WINDOW = { t0: "2026-08-30", t1: "2026-09-08" };

test("without a window the three days are drawn EVENLY -- the recorded defect", () => {
  const drawn = xs(dashChartSvg(GAPPED, ""));
  assert(drawn.length >= 3, "expected at least three marks, got " + drawn.length);
  const uniq = [...new Set(drawn.map(v => Math.round(v)))].sort((a, b) => a - b);
  const gaps = uniq.slice(1).map((v, i) => v - uniq[i]);
  const spread = Math.max(...gaps) - Math.min(...gaps);
  assert(spread <= 2,
    "index placement should space the three marks evenly (that IS the defect); " +
    "gaps were " + JSON.stringify(gaps));
});

test("with the window, the four-day hole is four days wide", () => {
  const drawn = xs(dashChartSvg(GAPPED, "", WINDOW)).map(v => Math.round(v));
  const uniq = [...new Set(drawn)].sort((a, b) => a - b);
  assert(uniq.length >= 3, "expected three distinct positions, got " + JSON.stringify(uniq));
  const d12 = uniq[1] - uniq[0];          // 2026-09-01 -> 2026-09-02, one day
  const d26 = uniq[2] - uniq[1];          // 2026-09-02 -> 2026-09-06, four days
  const ratio = d26 / d12;
  assert(ratio > 3.4 && ratio < 4.6,
    "the 4-day hole must be about 4x the 1-day step; got " + ratio.toFixed(2) +
    " from " + JSON.stringify(uniq));
});

test("the two placements genuinely differ -- the guard above is not vacuous", () => {
  const a = xs(dashChartSvg(GAPPED, "")).map(v => Math.round(v)).join(",");
  const b = xs(dashChartSvg(GAPPED, "", WINDOW)).map(v => Math.round(v)).join(",");
  assert(a !== b, "index and calendar placement produced identical coordinates (" + a + ")");
});

test("a gap in a WINDOWED series breaks the line and says so", () => {
  // Ten points so the renderer is in line mode (invariant #16: n >= 10), with a
  // real hole in the middle.
  const dense = [];
  for (let d = 1; d <= 6; d++) dense.push({ observed_on: `2026-09-0${d}`, price: d });
  for (let d = 20; d <= 23; d++) dense.push({ observed_on: `2026-09-${d}`, price: d });
  const svg = dashChartSvg(dense, "", { t0: "2026-09-01", t1: "2026-09-24" });
  const polylines = (svg.match(/<polyline/g) || []).length;
  assert(polylines >= 2,
    "a windowed series with a two-week hole must draw one run per side, got " + polylines);
  assert(svg.indexOf("a gap is not a zero") !== -1,
    "the break has to be explained where it is drawn");
});

test("a windowed series with NO hole draws one unbroken run", () => {
  const dense = [];
  for (let d = 1; d <= 12; d++) {
    dense.push({ observed_on: "2026-09-" + String(d).padStart(2, "0"), price: d });
  }
  const svg = dashChartSvg(dense, "", { t0: "2026-09-01", t1: "2026-09-12" });
  assert((svg.match(/<polyline/g) || []).length === 1,
    "a continuous series must not be split into fabricated runs");
  assert(svg.indexOf("a gap is not a zero") === -1,
    "the break note must appear only when a break was actually drawn");
});

test("the sparse rule survives: three points still render as BARS, not a line", () => {
  const svg = dashChartSvg(GAPPED, "", WINDOW);
  assert((svg.match(/<rect/g) || []).length >= 3,
    "n=3 is below _SPARSE_BAR_MAX and must draw bars (invariant #16, Item Y)");
  assert((svg.match(/<polyline/g) || []).length === 0,
    "a line through three points is the interpolation invariant #16 forbids -- " +
    "which is also why zero-FILLING the series was the wrong repair: it would " +
    "have made every window dense enough to draw one");
});

test("an absent window falls back to index placement rather than throwing", () => {
  // The renderers pass {} when a payload carries no series_window; the chart must
  // degrade to what it always did, never to an exception or an empty figure.
  const svg = dashChartSvg(GAPPED, "", {});
  assert(svg.indexOf("<svg") !== -1, "an empty opts must still render a figure");
});

console.log(`\n${passed} passed`);
