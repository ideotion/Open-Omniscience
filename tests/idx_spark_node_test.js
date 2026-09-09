/**
 * The indices tile's compact sparkline, driven for real.
 *
 * It is a SECOND renderer beside dashChartSvg, and it had independently
 * reproduced three things the shared toolkit exists to refuse:
 *
 *   1. INDEX placement. `x = i => (i/(n-1))*w`. An end-of-day index series skips
 *      weekends and holidays by nature, so this is not a rounding error on a
 *      financial board -- it is the difference between "closed on Monday" and
 *      "no gap at all".
 *   2. ONE path straight through a hole, which is the fabricated measurement the
 *      app's own convention names: "a gap is not a zero".
 *   3. A LINE through as few as two points -- the interpolation invariant #16
 *      forbids (n < 10 renders as bars, Item Y).
 *
 * All three now come from the SAME helpers the big renderer uses. This suite
 * extracts the REAL function from the shipped module: a re-typed copy would pass
 * while the shipped tile drew a smooth line across a fortnight of nothing.
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

const sandbox = {};
new Function(
  "const _SPARSE_BAR_MAX = " + (APP.match(/_SPARSE_BAR_MAX\s*=\s*(\d+)/) || [, "10"])[1] + ";\n"
  + "const _GAP_FACTOR = " + (APP.match(/const _GAP_FACTOR = (\d+)/) || [, "3"])[1] + ";\n"
  + APP.slice(APP.indexOf("const _missing = (v) =>"), APP.indexOf("const _GAP_FACTOR")) + "\n"
  + extract("function _seriesRuns(") + "\n"
  + extract("function idxSpark(") + "\n"
  + "this.idxSpark = idxSpark;"
).call(sandbox);

const { idxSpark } = sandbox;

const counts = (svg) => ({
  paths: (svg.match(/<path/g) || []).length,
  rects: (svg.match(/<rect/g) || []).length,
  circles: (svg.match(/<circle/g) || []).length,
});
// Captures ANY x value, not just a numeric one. A `[0-9.]+` class silently SKIPS
// `x="NaN"`, so a mark placed at NaN vanished from the sample instead of failing
// it -- the mutation that removes the per-point date fallback survived twice on
// exactly that blindness. A guard must be able to SEE the bad value to reject it.
const rectXRaw = (svg) => [...svg.matchAll(/<rect x="([^"]*)"/g)].map((m) => m[1]);
const rectX = (svg) => rectXRaw(svg).map((v) => Math.round(parseFloat(v)));

const dense = [];
for (let d = 1; d <= 14; d++) dense.push(["2026-09-" + String(d).padStart(2, "0"), 100 + d]);

const gapped = [];
for (let d = 1; d <= 6; d++) gapped.push(["2026-09-0" + d, 100 + d]);
for (let d = 24; d <= 29; d++) gapped.push(["2026-09-" + d, 120 + d]);

const sparse = [["2026-09-01", 100], ["2026-09-02", 104], ["2026-09-20", 96]];

test("a continuous series is still ONE unbroken line", () => {
  const c = counts(idxSpark(dense, 1));
  assert(c.paths === 1, "expected one path, got " + JSON.stringify(c));
  assert(c.rects === 0, "a dense series must not fall back to bars");
});

test("a hole in the series breaks the line instead of crossing it", () => {
  const c = counts(idxSpark(gapped, 1));
  assert(c.paths === 2,
    "an 18-day hole must split the line into its two runs, got " + JSON.stringify(c));
});

test("a sparse series draws marks, never a curve through them", () => {
  const c = counts(idxSpark(sparse, 1));
  assert(c.rects === 3, "n=3 is below _SPARSE_BAR_MAX and must draw marks: " + JSON.stringify(c));
  assert(c.paths === 0, "a line through three points is the interpolation #16 forbids");
});

test("marks sit at their REAL dates, not at even index positions", () => {
  const xs = rectX(idxSpark(sparse, 1));
  assert(xs.length === 3, "expected three marks, got " + JSON.stringify(xs));
  const oneDay = xs[1] - xs[0];         // 2026-09-01 -> 09-02
  const eighteen = xs[2] - xs[1];       // 2026-09-02 -> 09-20
  assert(eighteen > oneDay * 8,
    "the 18-day gap must dwarf the 1-day step; index placement would make them " +
    "equal. got " + JSON.stringify(xs));
});

test("the index-placed shape is genuinely gone -- the guard is not vacuous", () => {
  // Under the old renderer these three points sat at 0, w/2 and w.
  const xs = rectX(idxSpark(sparse, 1));
  const evenly = [0, 140, 280];
  assert(JSON.stringify(xs) !== JSON.stringify(evenly),
    "the marks are still evenly spaced: " + JSON.stringify(xs));
});

test("a series whose dates cannot be read falls back rather than vanishing", () => {
  const junk = [["not-a-date", 1], ["also-not", 2], ["nope", 3]];
  const svg = idxSpark(junk, 1);
  assert(svg.indexOf("<svg") !== -1, "an unparseable date must still render a figure");
  assert(counts(svg).rects === 3, "and must still draw every point");
});

test("ONE unreadable date among readable ones is placed, not sent to NaN", () => {
  // The case the all-junk fixture above cannot reach: the endpoints parse, so the
  // renderer IS in timed mode, and only an interior stamp is broken. Without the
  // per-point isFinite fallback that mark's x becomes NaN and the browser drops the
  // rect silently -- a datapoint that exists and is not drawn, which is the quiet
  // half of the same dishonesty as a datapoint drawn in the wrong place.
  // (This mutant SURVIVED the first round for exactly that reason.)
  const mixed = [["2026-09-01", 100], ["oops", 104], ["2026-09-20", 96]];
  const svg = idxSpark(mixed, 1);
  assert(counts(svg).rects === 3, "every point must be drawn: " + JSON.stringify(counts(svg)));
  const raw = rectXRaw(svg);
  assert(raw.length === 3, "expected three x values, got " + JSON.stringify(raw));
  assert(raw.every((v) => v !== "" && Number.isFinite(parseFloat(v))),
    "an unreadable interior date must fall back to its index position, not NaN: " +
    JSON.stringify(raw));
});

test("fewer than two points is an honest empty state, not an empty chart", () => {
  assert(idxSpark([], 1).indexOf("idx-spark-empty") !== -1, "empty series");
  assert(idxSpark([["2026-09-01", 100]], 1).indexOf("idx-spark-empty") !== -1, "one point");
});

console.log(`\n${passed} passed`);
