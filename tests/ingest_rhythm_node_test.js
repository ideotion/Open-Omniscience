/**
 * Node test for the ingest-rhythm heatmap (field impressions 2026-08-01, ruling 10:
 * "I think that overall the app has too little data visualization creativity").
 *
 * The honesty problem this visual had to solve: an empty cell is ambiguous. The
 * backend returns an hourly bucket ONLY for hours that have articles, so a missing
 * hour inside the observed span is a true zero -- but a weekday/hour slot that has
 * not come round yet (a three-day-old corpus has no second Tuesday) is NOT a zero,
 * it is unobserved. Blending the two would invent quiet periods that never happened.
 *
 * The aggregator is EXTRACTED FROM THE REAL app.js -- a re-typed copy would pass
 * while the shipped code was broken.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const fs = require("fs");
const path = require("path");
// The engine is several ordered modules since 2026-08-20 (S-3); the helper reads the
// module list out of index.html, so this suite cannot come to read a subset of it.
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
new Function(extract("function _ingestRhythm(") + "\nthis._ingestRhythm = _ingestRhythm;").call(sandbox);
const { _ingestRhythm } = sandbox;

// 2026-01-05 is a Monday (UTC).
const H = (iso, n) => ({ t: iso, n: n });

test("counts land in the right weekday/hour slot (UTC, Monday-first)", () => {
  const g = _ingestRhythm([H("2026-01-05T09:00:00", 7)]);
  assert(g.total[0][9] === 7, "Monday 09:00 should hold 7, got " + g.total[0][9]);
});

test("a slot that has not come round is NOT a zero", () => {
  // one single hour observed: every other slot is unobserved, not empty
  const g = _ingestRhythm([H("2026-01-05T09:00:00", 3)]);
  assert(g.seen[0][9] === 1, "the observed slot must be marked seen");
  assert(g.seen[2][14] === 0, "an un-elapsed slot must have zero OCCURRENCES");
  assert(g.total[2][14] === 0, "and no articles -- but the renderer reads `seen` to tell them apart");
});

test("an hour inside the span with no articles IS a real zero", () => {
  // 09:00 and 11:00 have articles; 10:00 elapsed but produced none
  const g = _ingestRhythm([H("2026-01-05T09:00:00", 2), H("2026-01-05T11:00:00", 5)]);
  assert(g.seen[0][10] === 1, "10:00 elapsed, so it was observed");
  assert(g.total[0][10] === 0, "and it genuinely collected nothing");
});

test("occurrences accumulate across weeks so an average is comparable", () => {
  const g = _ingestRhythm([H("2026-01-05T09:00:00", 4), H("2026-01-12T09:00:00", 6)]);
  assert(g.seen[0][9] === 2, "Monday 09:00 came round twice, got " + g.seen[0][9]);
  assert(g.total[0][9] === 10, "totals sum, got " + g.total[0][9]);
});

test("an empty or unparseable series renders nothing rather than an empty grid", () => {
  assert(_ingestRhythm([]) === null);
  assert(_ingestRhythm([{ t: "not-a-date", n: 3 }]) === null);
  assert(_ingestRhythm(null) === null);
});

test("an absurdly long span is refused, never partially drawn", () => {
  const g = _ingestRhythm([H("1990-01-01T00:00:00", 1), H("2026-01-05T09:00:00", 1)]);
  assert(g === null, "a span beyond the walk bound must return null, not a partial grid");
});

test("the renderer distinguishes the two empties and states the method", () => {
  const svg = APP.slice(APP.indexOf("function ingestRhythmSvg("));
  assert(svg.indexOf("rhythm-none") !== -1, "unobserved slots need their own fill");
  assert(svg.indexOf("not observed yet") !== -1, "and must say so in words");
  assert(svg.indexOf("occurrence(s)") !== -1, "the hover must give the real total and occurrences");
  assert(svg.indexOf("card-caveat") !== -1, "the averaging method must be stated visibly");
});

console.log("\n" + passed + " ingest-rhythm checks passed");
