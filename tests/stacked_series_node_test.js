// Q502 — the stack's arithmetic, and the four things it refuses to be asked.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// A stack is a PART-TO-WHOLE statement, which is a much stronger claim than a set of
// lines on shared axes — so what is driven here is mostly what it declines to draw.
// Every refusal below is a way a stacked chart can state something nobody computed, and
// each is a branch a rendering test cannot reach because the canvas never runs.
//
// EXTRACTED from the shipped module rather than re-typed.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = APP.indexOf("(", at), depth = 0;
  for (; i < APP.length; i++) {
    if (APP[i] === "(") depth++;
    else if (APP[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = APP.indexOf("{", i);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}

const src = extract("_stackSeries") + "\n" + extract("_stackPick")
  + "\nmodule.exports = { _stackSeries, _stackPick };";
const { _stackSeries, _stackPick } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const S = (label, pts) => ({ label, color: "#000", vis: pts });
const P = (t, v, gapBefore) => ({ t, v, gapBefore: !!gapBefore });

// 1. THE ARITHMETIC. Each band sits on the one below it, at the same timestamp, and the
//    top of the last band is the total. Read back band by band rather than trusting one
//    summary number, because an off-by-one in the running sum shows up as a plausible
//    picture with the wrong parts.
{
  const out = _stackSeries([S("en", [P(1, 3), P(2, 7)]), S("fr", [P(1, 2), P(2, 5)])], {});
  assert.ok(out.bands, out.refusal);
  assert.deepStrictEqual(out.times, [1, 2]);
  const [en, fr] = out.bands;
  assert.deepStrictEqual(en.pts.map(p => [p.lo, p.hi]), [[0, 3], [0, 7]]);
  assert.deepStrictEqual(fr.pts.map(p => [p.lo, p.hi]), [[3, 5], [7, 12]]);
  assert.strictEqual(out.top, 12, "the axis top is not the largest total");
}

// 2. A BUCKET A SERIES DID NOT REPORT contributes zero — which is what the caller
//    declares by asking for a stack — and is MARKED as unreported, so the hover can say
//    so rather than presenting a fabricated zero as a measurement.
{
  const out = _stackSeries([S("en", [P(1, 3), P(2, 4)]), S("fr", [P(2, 5)])], {});
  const fr = out.bands[1];
  assert.deepStrictEqual(fr.pts.map(p => p.t), [1, 2], "the band is not densified to the union");
  assert.strictEqual(fr.pts[0].v, 0);
  assert.strictEqual(fr.pts[0].measured, false,
    "an unreported bucket is not distinguishable from a measured zero");
  assert.strictEqual(fr.pts[1].measured, true);
  // ... and the band below it is unaffected: a densified zero must not move anything.
  assert.deepStrictEqual(out.bands[0].pts.map(p => p.hi), [3, 4]);
}

// 3. A PUBLISHED GAP REFUSES THE STACK. This is the one that matters most: filling a
//    real hole with zero turns "nobody measured this bucket" into "we measured none
//    here" AND shifts every band above it, so two lies for the price of one.
{
  const out = _stackSeries([S("en", [P(1, 3), P(3, 4, true)]), S("fr", [P(1, 2), P(3, 5)])], {});
  assert.strictEqual(out.refusal, "gap", "a published gap was stacked as a zero");
  assert.ok(!out.bands);
}

// 3b. A gap BEFORE the first visible point is not one: it means the hole is outside the
//     window, and refusing there would make any zoomed-in view unstackable.
{
  const out = _stackSeries([S("en", [P(1, 3, true), P(2, 4)]), S("fr", [P(1, 2), P(2, 5)])], {});
  assert.ok(out.bands, `a leading gap marker refused the stack: ${out.refusal}`);
}

// 4. NOT UNDER `indexed`: each series is rebased to 100 at its own first value, so the
//    bands would sum rebasings — a number with no referent.
{
  assert.strictEqual(
    _stackSeries([S("a", [P(1, 1)]), S("b", [P(1, 2)])], { indexed: true }).refusal, "indexed");
}

// 5. NOT UNDER `logY`: heights on a log axis do not add, so a stack drawn on one is a
//    picture of an addition that never happened.
{
  assert.strictEqual(
    _stackSeries([S("a", [P(1, 1)]), S("b", [P(1, 2)])], { logY: true }).refusal, "log");
}

// 6. NOT FOR ONE SERIES: a single band is an area chart wearing a stack's clothes.
{
  assert.strictEqual(_stackSeries([S("a", [P(1, 1)])], {}).refusal, "one-series");
  assert.strictEqual(_stackSeries([], {}).refusal, "one-series");
  assert.strictEqual(_stackSeries(null, {}).refusal, "one-series");
}

// 7. EVERY refusal is NAMED. A boolean "no" leaves the caller with nothing to tell the
//    reader, and the reader then sees lines under a control labelled "stacked".
{
  for (const r of ["gap", "indexed", "log", "one-series", "empty"]) {
    assert.strictEqual(typeof r, "string");
  }
  const empty = _stackSeries([S("a", []), S("b", [])], {});
  assert.strictEqual(empty.refusal, "empty");
}

// 8. ORDER IS THE CALLER'S, and it is preserved: the caller sorts by size so the reader
//    meets the largest band first, and a stack that re-ordered itself between draws
//    would make the picture move without the data moving.
{
  const out = _stackSeries([S("z", [P(1, 1)]), S("a", [P(1, 1)])], {});
  assert.deepStrictEqual(out.bands.map(b => b.s.label), ["z", "a"]);
}

// 9. THE HIT TEST, which is where a stack most easily names the WRONG part. Every band
//    shares the timestamp grid, so a time-only test ties on every point and the first
//    band iterated wins -- which would make every hover over a stack report the bottom
//    one. The y-projection is handed in, so this runs with no canvas.
{
  const out = _stackSeries([S("en", [P(1, 3), P(2, 7)]), S("fr", [P(1, 2), P(2, 5)])], {});
  // A plot 100px tall over a 0..12 axis, y growing downward as on a canvas.
  const yOf = (v) => 100 - (v / 12) * 100;
  // Pointing inside the LOWER band at t=1 (value 0..3 -> y 100..75): y = 90.
  const lo = _stackPick(out, yOf, 1, 90);
  assert.strictEqual(lo.band.s.label, "en", "the pointer inside the bottom band found " +
    (lo && lo.band.s.label));
  // ...and inside the UPPER band at the same timestamp (3..5 -> y 75..58.3): y = 65.
  const hi = _stackPick(out, yOf, 1, 65);
  assert.strictEqual(hi.band.s.label, "fr",
    "the hover reports the BOTTOM band wherever the reader points, so a stack names the " +
    "wrong part: got " + (hi && hi.band.s.label));
  // The two answers differ, so neither assertion above passed for a degenerate reason.
  assert.notStrictEqual(lo.band.s.label, hi.band.s.label);
  // TIME still dominates: a pointer deep inside one band but nearer another timestamp
  // answers with that timestamp, because the readout prints the time it names.
  assert.strictEqual(_stackPick(out, yOf, 1.9, 90).p.t, 2);
  // A pointer far ABOVE the whole stack still answers -- the nearest band, not nothing:
  // a readout that goes blank when the reader drifts off the ink is a chart that looks
  // broken.
  assert.strictEqual(_stackPick(out, yOf, 1, -50).band.s.label, "fr");
  // A refusal has no bands, so there is nothing to pick and the caller falls back.
  assert.strictEqual(_stackPick({refusal: "log"}, yOf, 1, 90), null);
  assert.strictEqual(_stackPick(out, null, 1, 90), null);
}

console.log("stacked_series_node_test: all assertions passed");
