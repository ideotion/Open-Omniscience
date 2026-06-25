// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Ideotion
//
// honest-charts.test.mjs
// Run: node honest-charts.test.mjs
// Uses only Node's built-in assert (no third-party test framework => stays
// fully open-source and dependency-free).

import assert from "node:assert/strict";
import {
  clamp,
  isMissing,
  linearScale,
  sqrtAreaScale,
  niceTicks,
  mulberry32,
  pathWithGaps,
  binCounts1D,
  bin2D,
  fiveNumberSummary,
} from "./honest-charts.js";

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log("ok  - " + name);
}

test("clamp bounds", () => {
  assert.equal(clamp(5, 0, 10), 5);
  assert.equal(clamp(-3, 0, 10), 0);
  assert.equal(clamp(99, 0, 10), 10);
});

test("isMissing flags only true gaps, never zero", () => {
  assert.equal(isMissing(null), true);
  assert.equal(isMissing(undefined), true);
  assert.equal(isMissing(NaN), true);
  assert.equal(isMissing(0), false); // zero is a value, not a gap
  assert.equal(isMissing(-1.5), false);
});

test("linearScale maps and inverts", () => {
  const s = linearScale(0, 10, 0, 100);
  assert.equal(s(0), 0);
  assert.equal(s(5), 50);
  assert.equal(s(10), 100);
  assert.equal(s.invert(50), 5);
  // zero-width domain must not throw or produce NaN
  const z = linearScale(4, 4, 0, 100);
  assert.equal(Number.isFinite(z(4)), true);
});

test("sqrtAreaScale encodes by AREA (honest bubbles)", () => {
  const r = sqrtAreaScale(100, 20);
  assert.equal(r(0), 0);
  assert.equal(r(100), 20);
  assert.equal(r(25), 10); // sqrt(25/100)=0.5 => half radius, quarter area
  // A value 4x larger must give 2x radius (not 4x), or the chart lies:
  assert.ok(Math.abs(r(40) / r(10) - 2) < 1e-12);
});

test("niceTicks gives clean 1-2-5 steps", () => {
  assert.deepEqual(niceTicks(0, 10, 5), [0, 2, 4, 6, 8, 10]);
  assert.deepEqual(niceTicks(0, 100, 5), [0, 20, 40, 60, 80, 100]);
  assert.deepEqual(niceTicks(0, 1, 5), [0, 0.2, 0.4, 0.6, 0.8, 1]); // no float drift
  // reversed input is handled
  assert.deepEqual(niceTicks(10, 0, 5), [0, 2, 4, 6, 8, 10]);
});

test("mulberry32 is deterministic and seed-sensitive", () => {
  const a = mulberry32(1234);
  const b = mulberry32(1234);
  const seqA = [a(), a(), a()];
  const seqB = [b(), b(), b()];
  assert.deepEqual(seqA, seqB); // same seed => identical pixels (H5)
  const c = mulberry32(5678);
  assert.notDeepEqual([c(), c(), c()], seqA); // different seed => different
  // values are in [0,1)
  const d = mulberry32(1);
  for (let i = 0; i < 50; i++) {
    const v = d();
    assert.ok(v >= 0 && v < 1);
  }
});

test("pathWithGaps breaks the line and never bridges a gap (H2)", () => {
  const id = (v) => v; // identity scales for a pure-logic check
  const pts = [
    { x: 0, y: 1 },
    { x: 1, y: 2 },
    { x: 2, y: null }, // missing -> gap
    { x: 3, y: 4 },
    { x: 4, y: 5 },
  ];
  const d = pathWithGaps(pts, id, id);
  const moves = (d.match(/M/g) || []).length;
  assert.equal(moves, 2); // two subpaths => the gap was honoured
  assert.ok(!d.includes("L3 4") || d.includes("M3 4")); // run after gap starts with M
});

test("binCounts1D buckets correctly and ignores missing", () => {
  const bins = binCounts1D([1, 1, 2, 3, NaN, 4], { min: 1, max: 5, count: 4 });
  // width=1: [1,2)->2, [2,3)->1, [3,4)->1, [4,5]->1 ; NaN ignored
  assert.deepEqual(bins, [2, 1, 1, 1]);
});

test("bin2D reduces points to a grid of counts", () => {
  const pts = [
    { x: 0.1, y: 0.1 },
    { x: 0.2, y: 0.2 },
    { x: 0.9, y: 0.9 },
    { x: NaN, y: 0.5 }, // ignored
  ];
  const g = bin2D(pts, 2, 2, { xmin: 0, xmax: 1, ymin: 0, ymax: 1 });
  assert.equal(g[0][0], 2); // bottom-left cell
  assert.equal(g[1][1], 1); // top-right cell
  assert.equal(g[0][1] + g[1][0], 0);
});

test("fiveNumberSummary uses R-7 quantiles and reports n", () => {
  const s1 = fiveNumberSummary([1, 2, 3, 4, 5]);
  assert.deepEqual([s1.min, s1.q1, s1.median, s1.q3, s1.max, s1.n], [1, 2, 3, 4, 5, 5]);
  const s2 = fiveNumberSummary([4, 2, 1, 3]); // unsorted input
  assert.equal(s2.median, 2.5);
  assert.equal(s2.q1, 1.75);
  assert.equal(s2.q3, 3.25);
  assert.equal(s2.n, 4);
  // n is always present so callers can refuse a box over tiny samples
  assert.equal(fiveNumberSummary([]).n, 0);
});

console.log("\n" + passed + " tests passed.");
