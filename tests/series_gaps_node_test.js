/**
 * Node test for _seriesRuns -- honest gaps in the ONE chart toolkit (invariant #16).
 *
 * THE DEFECT this pins shut: both renderers drew straight through a hole.
 * dashChartSvg emitted a SINGLE <polyline> over every point, and ooChart dropped
 * non-finite values and then lineTo'd from the point before the hole to the point
 * after it. On a real time axis that is a fabricated measurement -- a smooth line
 * across hours nothing was recorded -- and the project's own chart framework
 * rejects it outright ("Render gaps as gaps; mark 'no data' distinctly").
 *
 * THE OPPOSITE FAILURE IS EQUALLY DISHONEST, so it is pinned just as hard: a
 * fabricated gap invents an outage that never happened. Hence the tests below come
 * in pairs -- every "it breaks here" has a "and it does NOT break there" beside it.
 *
 * The helper is EXTRACTED FROM THE REAL app.js -- a re-typed copy would pass while
 * the shipped code was broken. Brace-matching starts at the BODY brace (after the
 * parentheses balance), because a default parameter carries a `{}` in the signature
 * and the naive extractor truncates the body to nothing, which would make every
 * assertion below pass vacuously (the recorded house lesson).
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
function eq(a, b, msg) { assert(JSON.stringify(a) === JSON.stringify(b), `${msg}: got ${JSON.stringify(a)} want ${JSON.stringify(b)}`); }

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
  "const _GAP_FACTOR = " + (APP.match(/const _GAP_FACTOR = (\d+)/) || [, "3"])[1] + ";\n"
  // _missing is extracted from the real app.js too: its whole point is that the
  // NAIVE check (isFinite) is wrong for null, so a re-typed stand-in here would
  // hide the very trap these tests exist to pin.
  + APP.slice(APP.indexOf("const _missing = (v) =>"), APP.indexOf("const _GAP_FACTOR")) + "\n"
  + extract("function _seriesRuns(") + "\nthis._seriesRuns = _seriesRuns;"
).call(sandbox);
const { _seriesRuns } = sandbox;

const HOUR = 36e5;
// An hourly counter series, the exact shape /api/library/history returns.
const hourly = (n, startMs) => Array.from({length: n}, (_, i) => ({t: (startMs || 0) + i * HOUR, v: 10 + i}));

// --------------------------------------------------------------------------- //
// 1. The line must NOT break where there is no hole. A fabricated gap invents an
//    outage that never happened, which is the same class of lie as bridging one.
// --------------------------------------------------------------------------- //
test("a regular series is ONE run - nothing is split", () => {
  eq(_seriesRuns(hourly(24), {timed: true}).length, 1, "regular hourly series");
});

test("ordinary cadence jitter never splits a line", () => {
  // Real samplers drift; +/-25% wobble must not read as an outage.
  const pts = [];
  let t = 0;
  const wobble = [1.0, 1.22, 0.81, 1.15, 0.9, 1.25, 0.78, 1.05, 0.95, 1.2, 0.85, 1.1];
  wobble.forEach((f, i) => { pts.push({t, v: i}); t += HOUR * f; });
  eq(_seriesRuns(pts, {timed: true}).length, 1, "jittered cadence");
});

test("a cadence guessed from too few intervals is never trusted", () => {
  // Two intervals cannot establish a cadence, so even a wild third one must not
  // split: we refuse to draw a gap on a number we cannot stand behind.
  const pts = [{t: 0, v: 1}, {t: HOUR, v: 2}, {t: 40 * HOUR, v: 3}];
  eq(_seriesRuns(pts, {timed: true}).length, 1, "under the cadence floor");
});

test("an INDEX axis never splits on time - only a real time axis can", () => {
  // Index spacing claims observation ORDER, not elapsed time, so bridging two
  // consecutive observations fabricates nothing. This is what keeps every
  // non-shared dashChartSvg caller byte-identical.
  const pts = hourly(6);
  pts.push({t: 400 * HOUR, v: 99});       // a huge hole in real time
  pts.push({t: 401 * HOUR, v: 98});
  pts.push({t: 402 * HOUR, v: 97});
  pts.push({t: 403 * HOUR, v: 96});
  eq(_seriesRuns(pts, {timed: false}).length, 1, "index axis");
  assert(_seriesRuns(pts, {timed: true}).length === 2, "the SAME data on a time axis must split");
});

// --------------------------------------------------------------------------- //
// 2. ...and it must break where there IS one.
// --------------------------------------------------------------------------- //
test("a real outage splits the line at exactly the outage", () => {
  // 12 hourly points, the app off for 20 hours, then 12 more: the Library
  // evolution graphs' normal shape on a machine that is shut down at night.
  const a = hourly(12);
  const b = hourly(12, a[a.length - 1].t + 20 * HOUR);
  const runs = _seriesRuns(a.concat(b), {timed: true});
  eq(runs.length, 2, "one run each side of the outage");
  eq(runs[0].length, 12, "before the outage");
  eq(runs[1].length, 12, "after the outage");
});

test("a missing value is ALWAYS a hole, on either axis", () => {
  // The official-statistics case: a published gap is a real null, and the call
  // site filtered it out and then drew through it.
  const pts = [{t: 0, v: 1}, {t: HOUR, v: 2}, {t: 2 * HOUR, v: null}, {t: 3 * HOUR, v: 4}, {t: 4 * HOUR, v: 5}];
  for (const timed of [true, false]) {
    const runs = _seriesRuns(pts, {timed});
    eq(runs.length, 2, `null breaks the run (timed=${timed})`);
    eq(runs[0], [0, 1], `run before the null (timed=${timed})`);
    eq(runs[1], [3, 4], `run after the null (timed=${timed})`);
  }
});

test("NaN and undefined are holes too, not zeros", () => {
  const pts = [{t: 0, v: 1}, {t: HOUR, v: NaN}, {t: 2 * HOUR, v: 3}, {t: 3 * HOUR}, {t: 4 * HOUR, v: 5}];
  eq(_seriesRuns(pts, {timed: false}).map(r => r.length), [1, 1, 1], "each survivor isolated");
});

// --------------------------------------------------------------------------- //
// 3. EXACT COVERAGE. A splitter whose output is meant to reconstruct the input is
//    tested by reconstruction, never by per-piece plausibility (the recorded
//    re.split lesson). Every finite point appears exactly once, in order.
// --------------------------------------------------------------------------- //
test("the runs cover every finite point exactly once, in order", () => {
  const shapes = [
    hourly(24),
    hourly(3),
    [{t: 0, v: 1}],
    [],
    hourly(5).concat(hourly(5, 100 * HOUR)),
    [{t: 0, v: 1}, {t: HOUR, v: null}, {t: 2 * HOUR, v: 3}],
    hourly(10).map((p, i) => (i % 3 === 0 ? {t: p.t, v: null} : p)),
  ];
  for (const timed of [true, false]) {
    shapes.forEach((pts, k) => {
      const flat = [].concat(...(_seriesRuns(pts, {timed})));
      // The expectation uses its OWN predicate, deliberately not the extracted
      // _missing: comparing an implementation against itself proves nothing. The
      // first draft of this line wrote `isFinite(pts[i].v)` and FAILED against
      // correct code -- isFinite(null) is true - which is the whole trap in one
      // line, and the reason this spells the rule out instead of borrowing it.
      const finite = (v) => typeof v === "number" && Number.isFinite(v);
      const want = pts.map((p, i) => i).filter(i => pts[i] && finite(pts[i].v));
      eq(flat, want, `shape ${k} (timed=${timed}) must reconstruct exactly`);
      _seriesRuns(pts, {timed}).forEach(r => assert(r.length > 0, `shape ${k}: no empty run`));
    });
  }
});

test("a DROPPED missing value still breaks the line via gapBefore", () => {
  // ooChart drops missing values so the scales and the sparse-bar threshold count
  // real observations only, and marks the survivor after the hole. One dropped
  // point is far too narrow to trip the cadence rule, so without the mark the line
  // would quietly close over it -- which is the fabricated-measurement bug wearing
  // a different hat.
  const pts = [{t: 0, v: 1}, {t: HOUR, v: 2}, {t: 3 * HOUR, v: 4, gapBefore: true}, {t: 4 * HOUR, v: 5}];
  eq(_seriesRuns(pts, {timed: true}), [[0, 1], [2, 3]], "gapBefore splits");
  const same = pts.map(p => ({t: p.t, v: p.v}));            // identical data, no mark
  eq(_seriesRuns(same, {timed: true}).length, 1, "and only the MARK causes it");
});

test("the accessors let one helper serve both renderers", () => {
  // dashChartSvg speaks {observed_on, price}; ooChart speaks {t, v}. One helper,
  // two vocabularies -- so the two renderers can never drift apart on what a gap is.
  const pts = [{observed_on: 0, price: 1}, {observed_on: HOUR, price: null}, {observed_on: 2 * HOUR, price: 3}];
  const runs = _seriesRuns(pts, {timed: true, value: (p) => p.price, time: (p) => p.observed_on});
  eq(runs, [[0], [2]], "custom accessors");
});

console.log(`\n${passed} passed`);
