/**
 * Behavioural node test for ooSky, the Observatory's polar renderer
 * (docs/design/OBSERVATORY_DESIGN.md, maintainer-ruled 2026-07-18).
 *
 * ooSky's pure half is REQUIRED directly rather than extracted from app.js: it is
 * its own dual node/browser module (the ooviz.js shape), so `require` gets the
 * shipped bytes and a re-typed copy cannot pass while the real file is broken --
 * which is the property the extract-by-name convention exists to buy elsewhere.
 *
 * MOST OF THIS SUITE IS THE NEGATIVE SPACE, deliberately. The positive space --
 * "galaxies land somewhere sensible" -- passes on its own and proves very little.
 * What the recorded logY defect teaches is that a renderer fails by drawing an
 * axis the data cannot support, and that the guard against it reads as defensive
 * coding while doing the opposite. So the assertions below are mostly about what
 * must NOT be drawn: no log scale under one decade, no coordinate for a zero, no
 * tick a count cannot take, no legend star smaller than the smallest real star.
 *
 * Run by tests/test_observatory_ui.py (and standalone: `node tests/oosky_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";
const S = require("../src/static/oosky.js");

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

function galaxy(name, domain, measures, extra) {
  return Object.assign(
    {id: name.length, name: name, domain: domain, measures: measures,
     languages: {}, rate: {growth: 0, growth_is_ratio: false},
     dominance: null, cross_group_overlap: {}},
    extra || {}
  );
}
function payload(galaxies, nebula) {
  return {
    galaxies: galaxies,
    clusters: [],
    nebula: nebula || {covered_keywords: 1, nebula_keywords: 0, total_keywords: 1},
  };
}

// --------------------------------------------------------------------------- //
//  THE LOG REFUSAL — the defect this renderer was written against
// --------------------------------------------------------------------------- //

test("a sub-decade domain refuses the log radius and falls back to linear", () => {
  // The live corpus's own numbers: distinct_sources topped out at SEVEN across
  // all 77 galaxies. log10(7) is 0.845, so a log radius would spread five sixths
  // of a decade over the whole sky and label orbits nothing can occupy.
  const s = S.radialScale([7, 6, 4, 1]);
  assert(s.mode === "linear", "a max of 7 must not get a log radius, got " + s.mode);
  assert(s.hi === 7, "the domain top must be the real maximum");
});

test("a domain spanning a decade or more does get the log radius", () => {
  // The other direction matters as much: a fabricated-axis fix that quietly
  // removes a real capability is its own defect. `mentions` really does span
  // decades (263 on the live corpus) and must keep the scale it deserves.
  const s = S.radialScale([263, 150, 10, 1]);
  assert(s.mode === "log", "a max of 263 must get the log radius, got " + s.mode);
  assert(s.ticks[0] === 1 && s.ticks.indexOf(10) > 0 && s.ticks.indexOf(100) > 0,
    "log orbits must be the decades: " + JSON.stringify(s.ticks));
  assert(s.ticks[s.ticks.length - 1] === 263, "the maximum itself must be a labelled orbit");
});

test("the boundary is exactly one decade, from both sides", () => {
  assert(S.radialScale([9]).mode === "linear", "9 is under a decade");
  assert(S.radialScale([10]).mode === "log", "10 is one full decade");
});

test("no scale at all when nothing has a positive value, and r is null not a function", () => {
  // 52 of 77 galaxies sat at zero on the live corpus, so the all-zero corpus is
  // a real state, not a hypothetical. A caller that ignored `mode` must not be
  // able to plot anyway -- hence r is null rather than a function returning 0.
  const s = S.radialScale([0, 0, 0]);
  assert(s.mode === "none", "an all-zero set has no scale");
  assert(s.r === null, "there must be no radius function to accidentally call");
  assert(s.zeros === 3 && s.positives === 0, "the populations must still be counted");
  assert(S.radialScale([]).mode === "none", "an empty set has no scale either");
});

test("a zero never gets a coordinate on any scale, and neither does a gap", () => {
  for (const vals of [[7, 6, 1], [263, 10, 1]]) {
    const s = S.radialScale(vals);
    assert(s.r(0) === null, "zero must not be placed on the " + s.mode + " scale");
    assert(s.r(null) === null, "a null must not be placed on the " + s.mode + " scale");
    assert(s.r(undefined) === null, "an undefined must not be placed");
    assert(s.r(NaN) === null, "a NaN must not be placed");
    assert(s.r(-3) === null, "a negative must not be placed");
  }
});

test("linear orbit ticks are integers and never include the unplottable zero", () => {
  const s = S.radialScale([7, 3, 1]);
  assert(s.ticks.length > 0, "a linear scale still needs labelled orbits");
  for (const t of s.ticks) {
    assert(Number.isInteger(t), "a count axis cannot print " + t);
    assert(t > 0, "a 0 orbit can never be drawn (r(0) is null) so it must not be advertised");
    assert(s.r(t) !== null, "every advertised orbit must be drawable, " + t + " was not");
  }
});

test("centre is the maximum and the scale is monotone outward", () => {
  const s = S.radialScale([100, 10, 1], {rInner: 40, rOuter: 300});
  assert(Math.abs(s.r(100) - 40) < 1e-6, "the maximum sits at the inner radius");
  assert(s.r(1) > s.r(10) && s.r(10) > s.r(100), "smaller values must sit further out");
});

// --------------------------------------------------------------------------- //
//  DETERMINISM (honesty rule H5)
// --------------------------------------------------------------------------- //

test("the same corpus produces the same sky, twice, to the last coordinate", () => {
  const p = payload([
    galaxy("Elections & democracy", "Politics & governance", {distinct_sources: 7, mentions: 263}),
    galaxy("Public finance", "Economy & finance", {distinct_sources: 6, mentions: 150}),
    galaxy("Mathematics", "Physical sciences", {distinct_sources: 0, mentions: 0}),
  ]);
  const a = S.skyLayout(p, {measure: "distinct_sources"});
  const b = S.skyLayout(p, {measure: "distinct_sources"});
  const key = (L) => JSON.stringify(L.galaxies.map((g) => [g.name, g.x, g.y, g.star]));
  assert(key(a) === key(b), "the layout must be deterministic — change is the signal");
  assert(a.galaxies.length === 2 && a.unplaced.length === 1, "the zero galaxy must be unplaced");
  assert(a.unplaced[0].name === "Mathematics", "the unplaced one must be the zero one");
  assert(a.unplaced[0].reason === "zero", "and it must say why");
  assert(a.unplaced[0].radius === undefined, "an unplaced galaxy must carry NO radius");
});

test("the hash is stable across processes, not merely within one run", () => {
  // A per-run seed would still pass the twice-in-one-process test above while
  // reshuffling the sky between sessions, which is exactly what the design
  // forbids: the user's spatial memory is what makes a new bright star legible.
  assert(S.hash32("Elections & democracy") === 1212166780,
    "the FNV-1a hash changed: every user's sky would move, got " + S.hash32("Elections & democracy"));
  assert(S.hash32("") === 2166136261, "the empty-string basis must be the FNV offset");
  const u = S.stableUnit("Public finance");
  assert(u >= 0 && u < 1, "the jitter must be a unit interval, got " + u);
});

test("jitter stays inside its own wedge and never lands on a boundary", () => {
  const names = ["a", "bb", "ccc", "dddd", "eeeee", "Elections & democracy", "Zzz"];
  const p = payload(names.map((n) => galaxy(n, "D", {distinct_sources: 5, mentions: 5})));
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  const arc = L.domains[0];
  const wedge = arc.a1 - arc.a0;
  for (const g of L.galaxies) {
    const off = (g.angle - arc.a0) / wedge;
    assert(off > 0 && off < 1, g.name + " escaped its wedge");
    assert(off >= S.WEDGE_MARGIN - 1e-9 && off <= 1 - S.WEDGE_MARGIN + 1e-9,
      g.name + " landed in the boundary margin at " + off);
  }
});

// --------------------------------------------------------------------------- //
//  THE SIZE CHANNEL — area, and the floor it saturates at
// --------------------------------------------------------------------------- //

test("star radius is sqrt of the value, so AREA is what carries the quantity", () => {
  const p = payload([
    galaxy("big", "D", {distinct_sources: 1, mentions: 400}),
    galaxy("small", "D", {distinct_sources: 1, mentions: 100}),
  ]);
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  const big = L.galaxies.find((g) => g.name === "big");
  const small = L.galaxies.find((g) => g.name === "small");
  // 4x the mentions must be 2x the RADIUS (4x the area), never 4x the radius.
  assert(Math.abs(big.star / small.star - 2) < 1e-6,
    "radius must scale as sqrt: got a ratio of " + big.star / small.star);
});

test("no reference star is drawn smaller than the smallest real star can be", () => {
  // The legend teaches a scale; if its smallest sample is 0.8px while nothing on
  // the canvas is under MIN_STAR, it teaches a scale the sky does not use.
  const p = payload([galaxy("g", "D", {distinct_sources: 1, mentions: 263})]);
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  assert(L.referenceStars.length > 0, "a size channel owes a legend");
  for (const s of L.referenceStars) {
    assert(s.r >= S.MIN_STAR - 1e-9, "reference star " + s.value + " is under the floor at " + s.r);
  }
  const floored = L.referenceStars.filter((s) => s.saturated);
  assert(floored.length > 0 && floored.every((s) => s.r === S.MIN_STAR),
    "a sample the channel cannot separate must be FLAGGED saturated");
});

test("the size floor is reported so the surface can disclose it", () => {
  const p = payload([galaxy("g", "D", {distinct_sources: 1, mentions: 263})]);
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  assert(L.sizeFloorValue !== null && L.sizeFloorValue > 1,
    "the value at which the area channel saturates must be published");
  // and it must be honest: a value at the floor really is drawn at the floor
  assert(Math.max(S.MIN_STAR, L.sizeFn(L.sizeFloorValue - 1)) === S.MIN_STAR,
    "a value below the reported floor must really be drawn at the minimum");
  assert(L.sizeFn(L.maxMentions) > S.MIN_STAR, "the largest star must not be at the floor");
});

test("no size floor is claimed when the floor never bites", () => {
  const p = payload([galaxy("g", "D", {distinct_sources: 1, mentions: 1})]);
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  assert(L.sizeFloorValue === null, "a corpus whose top star is 1 has no floor to disclose");
});

// --------------------------------------------------------------------------- //
//  CONSTELLATION EDGES — measured, never proximity
// --------------------------------------------------------------------------- //

test("an edge is drawn only from a shared member, and carries the members it shares", () => {
  const p = payload([
    galaxy("Mathematics", "Physical sciences", {distinct_sources: 3, mentions: 9},
      {cross_group_overlap: {logic: ["Philosophy"]}}),
    galaxy("Philosophy", "Culture & heritage", {distinct_sources: 2, mentions: 4}),
    galaxy("Sport", "Sport & infrastructure", {distinct_sources: 2, mentions: 4}),
  ]);
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  assert(L.edges.length === 1, "exactly one measured overlap exists, got " + L.edges.length);
  assert(L.edges[0].n === 1 && L.edges[0].shared[0] === "logic",
    "the edge must name what it was drawn from");
  const names = [L.edges[0].a.name, L.edges[0].b.name].sort();
  assert(names[0] === "Mathematics" && names[1] === "Philosophy", "wrong pair joined");
});

test("no edge is invented between galaxies that merely sit near each other", () => {
  const p = payload([
    galaxy("A", "D", {distinct_sources: 5, mentions: 5}),
    galaxy("B", "D", {distinct_sources: 5, mentions: 5}),
  ]);
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  assert(L.edges.length === 0, "same wedge, same orbit, no shared member — no edge");
});

test("an overlap whose partner is unplaced draws no dangling edge", () => {
  // The live corpus hit exactly this: the only overlapping pair (Mathematics /
  // Philosophy) both had a zero measure, so neither was placed. A half-edge to
  // a galaxy that has no coordinate would have to invent one.
  const p = payload([
    galaxy("Mathematics", "Physical sciences", {distinct_sources: 3, mentions: 9},
      {cross_group_overlap: {logic: ["Philosophy"]}}),
    galaxy("Philosophy", "Culture & heritage", {distinct_sources: 0, mentions: 0}),
  ]);
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  assert(L.edges.length === 0, "an edge to an unplaced galaxy must not be drawn");
});

// --------------------------------------------------------------------------- //
//  THE CANONICAL ORDER + the empty corpus
// --------------------------------------------------------------------------- //

test("the ranked order holds every galaxy, placed ones first, unplaced ones last", () => {
  // Anti-capping: the table is the canonical view, so nothing may fall out of it.
  const p = payload([
    galaxy("mid", "D", {distinct_sources: 4, mentions: 4}),
    galaxy("top", "D", {distinct_sources: 9, mentions: 9}),
    galaxy("none", "D", {distinct_sources: 0, mentions: 0}),
  ]);
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  const ranked = S.rankedGalaxies(L);
  assert(ranked.length === 3, "every galaxy must appear, got " + ranked.length);
  assert(ranked[0].name === "top" && ranked[1].name === "mid", "placed ones rank by value");
  assert(ranked[2].name === "none", "an unplaced galaxy is listed, at the end");
});

test("an empty corpus lays out cleanly instead of throwing", () => {
  const L = S.skyLayout(payload([]), {measure: "distinct_sources"});
  assert(L.galaxies.length === 0 && L.unplaced.length === 0, "nothing to place");
  assert(L.scale.mode === "none", "and no scale to draw");
  assert(L.referenceStars.length === 0, "and no legend to teach");
  assert(S.rankedGalaxies(L).length === 0, "and an empty table");
});

test("a missing measures block is a gap, not a zero-valued galaxy on the axis", () => {
  const p = payload([galaxy("g", "D", {})]);
  const L = S.skyLayout(p, {measure: "distinct_sources"});
  assert(L.galaxies.length === 0 && L.unplaced.length === 1, "an absent measure cannot be plotted");
  assert(L.unplaced[0].reason === "missing", "and it must be told apart from a measured zero");
  assert(L.unplaced[0].value === null, "an unmeasured value must not surface as 0");
});

console.log("\n" + passed + " ooSky checks passed.");
