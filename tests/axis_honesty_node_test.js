/**
 * Behavioural node test for the AXIS-HONESTY pass (field impressions 2026-08-01,
 * ruling 10). The maintainer's report, verbatim: on a fresh install the "law
 * documents tracked" tile showed a y-axis of 23 and 23.5, an x-axis whose two
 * ticks were both "2026-07", and an "n=2" that could not be told apart from the
 * value -- "are there 23 law documents tracked with 2 data-points, or are there
 * 2 tracked law documents?".
 *
 * Root cause was ONE expression in each renderer: `span = (max - min) || 1`.
 * For a constant series it fabricated a span, so the gridline VALUES became
 * [23, 23.5, 23] (dashChartSvg -- min and max labels also landing on top of each
 * other at the plot bottom) and [23, 23.33, 23.67, 24] (ooChart -- a top tick no
 * data ever reaches). Neither renderer had integer snapping, so a COUNT axis
 * could print a fractional count.
 *
 * The functions are EXTRACTED FROM THE REAL app.js by name -- a re-typed copy
 * would pass while the shipped code was broken (the sibling-test convention).
 * Run by tests/test_axis_honesty.py (and standalone: `node tests/axis_honesty_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const fs = require("fs");
const path = require("path");

const APP = fs.readFileSync(
  path.join(__dirname, "..", "src", "static", "app.js"), "utf-8");

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

function extract(name, decl) {
  const head = decl || ("function " + name + "(");
  const at = APP.indexOf(head);
  assert(at !== -1, "could not find " + head + " in app.js");
  // Start at the BODY brace, not the first brace: `function f(a, opts = {})` has
  // a `{}` in its default parameter, and matching from there truncates the body
  // to nothing (this test caught exactly that on ooChart).
  let p = 0, i = -1;
  for (let j = APP.indexOf("(", at); j < APP.length; j++) {
    if (APP[j] === "(") p++;
    else if (APP[j] === ")") { p--; if (p === 0) { i = APP.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

// The three pure helpers the whole pass rests on.
const sandbox = {};
new Function(
  extract("_allInteger") + "\n" + extract("honestTicks") + "\n" +
  extract("_timeLabelFmt") + "\n" + extract("_msLabel") + "\n" +
  "this._allInteger = _allInteger; this.honestTicks = honestTicks;" +
  "this._timeLabelFmt = _timeLabelFmt; this._msLabel = _msLabel;"
).call(sandbox);
const {_allInteger, honestTicks, _timeLabelFmt, _msLabel} = sandbox;

// --------------------------------------------------------------------------- //
// The reported defect, both directions.
// --------------------------------------------------------------------------- //
test("a FLAT series gets exactly ONE tick at its real value (the 23 / 23.5 report)", () => {
  const ticks = honestTicks(23, 23, 3, true);
  assert(ticks.length === 1, "flat series must not fabricate ticks, got " + JSON.stringify(ticks));
  assert(ticks[0] === 23, "the one tick must be the real value, got " + ticks[0]);
});

test("a COUNT axis never prints a fractional tick", () => {
  for (const [lo, hi] of [[23, 24], [0, 23], [1, 7], [100, 137], [0, 3]]) {
    for (const want of [3, 4]) {
      const ticks = honestTicks(lo, hi, want, true);
      for (const v of ticks) {
        assert(Number.isInteger(v),
          `fractional tick ${v} on an integer axis ${lo}..${hi} (want=${want})`);
      }
    }
  }
});

test("ticks never invent a value outside the data's own range", () => {
  for (const [lo, hi] of [[23, 24], [0, 23], [-5, 5], [0.5, 2.5]]) {
    for (const v of honestTicks(lo, hi, 4, false)) {
      assert(v >= lo - 1e-9 && v <= hi + 1e-9,
        `tick ${v} outside ${lo}..${hi} — the old (max-min)||1 fallback did exactly this`);
    }
  }
});

test("the real extremes are always tick values (the reader sees the true range)", () => {
  const ticks = honestTicks(0, 23, 3, true);
  assert(ticks[0] === 0, "first tick must be the real min");
  assert(ticks[ticks.length - 1] === 23, "last tick must be the real max");
});

test("ticks are sorted, unique, and collapse rather than repeat", () => {
  const ticks = honestTicks(23, 24, 3, true);   // mid would round onto an endpoint
  assert(ticks.length === new Set(ticks).size, "duplicate ticks: " + JSON.stringify(ticks));
  for (let i = 1; i < ticks.length; i++) assert(ticks[i] > ticks[i - 1], "unsorted ticks");
  assert(JSON.stringify(ticks) === JSON.stringify([23, 24]),
    "23..24 integer must collapse to [23,24], got " + JSON.stringify(ticks));
});

test("a non-integer series keeps real fractional ticks", () => {
  const ticks = honestTicks(0.5, 2.5, 3, false);
  assert(ticks.length === 3 && ticks[1] === 1.5, "got " + JSON.stringify(ticks));
});

test("_allInteger is true only for genuinely integer data", () => {
  assert(_allInteger([1, 2, 3]) === true);
  assert(_allInteger([1, 2.5]) === false);
  assert(_allInteger([]) === false, "an empty series must not claim integer-ness");
});

test("degenerate inputs never throw or fabricate", () => {
  assert(honestTicks(NaN, 3, 3, true).length === 0);
  assert(honestTicks(5, 3, 3, true).length === 1, "max<min collapses to one tick");
});

// --------------------------------------------------------------------------- //
// X labels: granularity follows the span, and duplicates are dropped by TEXT.
// --------------------------------------------------------------------------- //
test("two hourly points in one month do NOT both render '2026-07'", () => {
  const f = _timeLabelFmt("2026-07-15T13:00:00", "2026-07-15T14:00:00");
  const a = f("2026-07-15T13:00:00"), b = f("2026-07-15T14:00:00");
  assert(a !== b, `both labels rendered as "${a}" — the exact reported defect`);
});

test("label granularity widens with the span", () => {
  const hourly = _timeLabelFmt("2026-07-15T13:00:00", "2026-07-16T01:00:00");
  const monthly = _timeLabelFmt("2024-01-01T00:00:00", "2026-07-15T00:00:00");
  const daily = _timeLabelFmt("2026-06-01T00:00:00", "2026-07-15T00:00:00");
  assert(hourly("2026-07-15T13:00:00").includes(" "), "a <=2d span needs an hour label");
  assert(daily("2026-06-05T00:00:00") === "2026-06-05", "a <=92d span needs a day label");
  assert(monthly("2024-03-05T00:00:00") === "2024-03", "a multi-year span uses months");
});

test("_msLabel (ooChart's epoch axis) follows the same rule", () => {
  const base = Date.UTC(2026, 6, 15, 13, 0, 0);
  const hour = _msLabel(base, 36e5), month = _msLabel(base, 400 * 864e5);
  assert(hour !== month, "granularity must react to the span");
  assert(month === "2026-07", "a long span uses YYYY-MM, got " + month);
  assert(/\d\d-\d\d \d\d:\d\d/.test(hour), "a short span needs MM-DD HH:MM, got " + hour);
});

// --------------------------------------------------------------------------- //
// Source-level guards: the fabrication vectors must stay gone.
// --------------------------------------------------------------------------- //
function bodyOf(head) {
  const at = APP.indexOf(head);
  assert(at !== -1, "missing " + head);
  // Start at the BODY brace, not the first brace: `function f(a, opts = {})` has
  // a `{}` in its default parameter, and matching from there truncates the body
  // to nothing (this test caught exactly that on ooChart).
  let p = 0, i = -1;
  for (let j = APP.indexOf("(", at); j < APP.length; j++) {
    if (APP[j] === "(") p++;
    else if (APP[j] === ")") { p--; if (p === 0) { i = APP.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  return "";
}

test("dashChartSvg draws its gridlines from honestTicks, not min/mid/max", () => {
  const body = bodyOf("function dashChartSvg(");
  assert(body.includes("honestTicks("), "dashChartSvg must use honestTicks");
  assert(!body.includes("[minY, minY + span/2, maxY]"),
    "the fabricated min/mid/max gridline triple is back");
});

test("ooChart draws its gridlines from honestTicks and sizes to its container", () => {
  const body = bodyOf("function ooChart(");
  assert(body.includes("honestTicks("), "ooChart must use honestTicks");
  assert(!/yMin \+ ySpan \* g \/ 3/.test(body), "the fabricated 4-tick loop is back");
  assert(!/Math\.max\(320,\s*Math\.min\(el\.clientWidth \|\| 680/.test(body),
    "the fixed 320px floor / 680px hidden-element fallback is back (the overflow vector)");
  assert(body.includes("ResizeObserver"),
    "a not-yet-laid-out host must re-render on width, never guess a size");
});

test("the library count tiles pass zeroBase, a neutral colour, a unit and an n-unit", () => {
  const body = bodyOf("async function _libGraphTile(");
  assert(body.includes("zeroBase: true"), "count series need a true zero base (Item Y)");
  assert(body.includes("neutral: true"), "a neutral metric must not use market up=green/down=red");
  assert(body.includes("LIB_METRIC_UNIT_KEYS"), "the axis unit must be stated");
  assert(body.includes("nUnit"), "n= must carry what it counts");
});

console.log("\n" + passed + " axis-honesty checks passed");
