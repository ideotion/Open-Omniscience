/**
 * The commodity Price x coverage overlay, driven for real (RC08.6 / register L5).
 *
 * The overlay used to draw a polyline from TWO price points -- the curve faked
 * through a handful of points that invariant #16 forbids everywhere else. It now
 * reads the SAME shared `_SPARSE_BAR_MAX` the rest of the app uses.
 *
 * The Python side guards that the threshold is READ in the source. This suite is
 * the half a grep cannot do: a source assertion cannot tell a line that is GATED
 * on the threshold from one that merely mentions it, so this EXECUTES the shipped
 * `commodityOverlaySvg` and reads the SVG back. Extracted from the shipped module
 * by name -- a re-typed copy would pass while the real renderer drew a line.
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
  // Start brace-matching at the BODY brace, not the first `{` after the name: a
  // default parameter carries its own braces and would end the slice at the
  // signature (the recorded ooChart trap).
  let i = APP.indexOf("{", APP.indexOf(")", at));
  let depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces in " + head);
}

// _SPARSE_BAR_MAX is read out of the SHIPPED source, never re-typed here -- the
// whole point of the ruling is that this renderer shares the one threshold.
const THRESH = Number((APP.match(/_SPARSE_BAR_MAX\s*=\s*(\d+)/) || [])[1]);
assert(Number.isFinite(THRESH) && THRESH > 1, "could not read _SPARSE_BAR_MAX from the engine");

const overlay = new Function(
  "window",
  'const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"\']/g,'
  + ' c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","\'":"&#39;"}[c])));\n'
  + "const fmtNum = (x) => String(x);\n"
  + "const _SPARSE_BAR_MAX = " + THRESH + ";\n"
  + extract("function commodityOverlaySvg(")
  + "\nreturn commodityOverlaySvg;"
)({});

const price = (n) => Array.from({ length: n }, (_, i) => ({
  observed_on: `2026-0${1 + (i % 9)}-0${1 + (i % 9)}`, price: 100 + i,
}));
const cov = [{ date: "2026-02-02", count: 4 }, { date: "2026-03-03", count: 7 }];

test("a sparse price series renders BARS, never a polyline", () => {
  const svg = overlay(price(3), cov, "USD/kg");
  assert(!/<polyline/.test(svg), "3 price points must not be joined into a line");
  // the coverage bars are muted; the price bars carry the accent fill
  const accentBars = (svg.match(/<rect[^>]*fill="var\(--accent\)"/g) || []).length;
  assert(accentBars >= 3, "each sparse price point owes a value cap (got " + accentBars + ")");
});

test("a dense price series renders the FULL-RESOLUTION line", () => {
  const svg = overlay(price(THRESH), cov, "USD/kg");
  assert(/<polyline/.test(svg), "at the threshold the series must draw its line");
  const pts = (svg.match(/points="([^"]*)"/) || [])[1].trim().split(/\s+/).length;
  assert(pts === THRESH, "the line must carry every point, not a thinned set (got " + pts + ")");
});

test("the threshold is the boundary, checked on both sides of it", () => {
  assert(!/<polyline/.test(overlay(price(THRESH - 1), cov, "u")), "below the threshold: bars");
  assert(/<polyline/.test(overlay(price(THRESH), cov, "u")), "at the threshold: line");
});

test("a single point is VISIBLE -- a flush-min bar would be zero-height", () => {
  const svg = overlay(price(1), cov, "u");
  const caps = (svg.match(/<rect[^>]*height="2"[^>]*fill="var\(--accent\)"/g) || []).length;
  assert(caps === 1, "the 2px value cap must mark the single point (got " + caps + ")");
});

test("an all-equal window still shows every bar", () => {
  const flat = [{ observed_on: "2026-01-01", price: 50 },
                { observed_on: "2026-02-01", price: 50 },
                { observed_on: "2026-03-01", price: 50 }];
  const svg = overlay(flat, [], "u");
  const caps = (svg.match(/height="2"/g) || []).length;
  assert(caps === 3, "a flat series owes one visible cap per point (got " + caps + ")");
});

test("no price data still renders the coverage side rather than throwing", () => {
  const svg = overlay([], cov, "u");
  assert(/<svg/.test(svg) && !/<polyline/.test(svg), "coverage-only must still draw");
});

console.log(`\n${passed} passed`);
