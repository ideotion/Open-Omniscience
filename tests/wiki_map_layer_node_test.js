// Q819 step 1's map layer, EXECUTED against the shipped projection seam.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The ruling's whole point is that this layer goes THROUGH `project(lon, lat)` rather
// than owning a projection: a page and a country border drawn on two different worlds
// is the failure, and step 2 (0.5) can only be a join because both sides pass through
// the same function. A source-text assertion cannot show that — the recorded lesson is
// that `assert_present(source, "s.tags")` stayed green against a mutant that read the
// field and threw it away. So both functions are EXTRACTED from the shipped module and
// RUN, and the markers' coordinates are compared against the seam's own output.

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

// The Equal Earth constants the seam reads, EXTRACTED as the shipped declaration block
// rather than re-typed: a re-typed copy would let this file pass while the real
// projection said something else. Taken as a SLICE because the module declares several
// of them per line (`const EE_A1 = …, EE_A2 = …;`), which a per-name regex cannot see —
// the first version of this file asked for EE_A2 by name and could not find it.
const CONSTS = (function () {
  const from = APP.indexOf("const EE_A1");
  assert.ok(from !== -1, "the map module no longer declares EE_A1");
  const to = APP.indexOf("const MAP_H");
  assert.ok(to > from, "the map module no longer declares MAP_H after EE_A1");
  const end = APP.indexOf("\n", to);
  const block = APP.slice(from, end);
  for (const name of ["EE_A2", "EE_A3", "EE_A4", "EE_M", "EE_X_MAX", "EE_Y_MAX", "MAP_W"]) {
    assert.ok(new RegExp("\\b" + name + "\\b").test(block), "the slice lost " + name);
  }
  return block;
})();

function build() {
  const sandbox = { esc: (s) => String(s), console };
  const body = CONSTS + "\n"
    + extract("_eeFwd") + "\n"
    + extract("project") + "\n"
    + extract("_ooWikiLayer") + "\n"
    + "return { project, layer: _ooWikiLayer };";
  const fn = new Function("esc", body);
  return fn(sandbox.esc);
}

const { project, layer } = build();

// --------------------------------------------------------------------------- //
// It draws THROUGH the seam.
// --------------------------------------------------------------------------- //
(function markersLandWhereTheSeamSaysTheyShould() {
  const pt = { external_id: "en:p1", title: "Rome", edition: "en", lat: 41.9, lon: 12.5, qid: "Q220", joinable: true };
  const out = layer({ measured: true, points: [pt] });
  const want = project(pt.lon, pt.lat);
  const cx = /cx="([-\d.]+)"/.exec(out.markup);
  const cy = /cy="([-\d.]+)"/.exec(out.markup);
  assert.ok(cx && cy, "the layer drew no circle at all: " + out.markup);
  assert.strictEqual(cx[1], want.x.toFixed(1), "x came from somewhere other than project()");
  assert.strictEqual(cy[1], want.y.toFixed(1), "y came from somewhere other than project()");
})();

(function twoDifferentPlacesLandInDifferentPlaces() {
  // The mutation this catches: a layer that projects nothing and puts every marker at
  // one point still satisfies "it drew a circle".
  const out = layer({
    measured: true,
    points: [
      { external_id: "a", lat: 41.9, lon: 12.5, joinable: true },
      { external_id: "b", lat: -33.9, lon: 151.2, joinable: true },
    ],
  });
  const xs = [...out.markup.matchAll(/cx="([-\d.]+)"/g)].map((m) => m[1]);
  assert.strictEqual(xs.length, 2);
  assert.notStrictEqual(xs[0], xs[1], "both markers landed on the same x");
})();

// --------------------------------------------------------------------------- //
// Every marker is the SAME SIZE. The lane knows a page has a coordinate and nothing
// else about it; sizing by anything would encode a quantity the operator reads as
// importance.
// --------------------------------------------------------------------------- //
(function noMarkerIsSizedByAnything() {
  const out = layer({
    measured: true,
    points: [
      { external_id: "a", lat: 0, lon: 0, joinable: true },
      { external_id: "b", lat: 10, lon: 10, joinable: false },
      { external_id: "c", lat: 20, lon: 20, joinable: true },
    ],
  });
  const radii = new Set([...out.markup.matchAll(/ r="([\d.]+)"/g)].map((m) => m[1]));
  assert.strictEqual(radii.size, 1, "markers differ in size: " + [...radii].join(", "));
})();

// --------------------------------------------------------------------------- //
// The QID distinction is FILL, and it is the only one.
// --------------------------------------------------------------------------- //
(function joinableIsFilledAndUnjoinableIsHollow() {
  const joined = layer({ measured: true, points: [{ external_id: "a", lat: 1, lon: 1, joinable: true }] });
  const lone = layer({ measured: true, points: [{ external_id: "b", lat: 1, lon: 1, joinable: false }] });
  assert.ok(/fill="var\(--accent\)"/.test(joined.markup), "a joinable point is not filled");
  assert.ok(/fill="transparent"/.test(lone.markup), "an unjoinable point is not hollow");
  assert.ok(!/fill="transparent"/.test(joined.markup));
})();

// --------------------------------------------------------------------------- //
// NOTHING IS THINNED, and an absence draws nothing rather than something.
// --------------------------------------------------------------------------- //
(function everyPointHandedInIsDrawn() {
  const points = [];
  for (let i = 0; i < 250; i++) points.push({ external_id: "p" + i, lat: (i % 80) - 40, lon: (i % 170) - 85, joinable: i % 2 === 0 });
  const out = layer({ measured: true, points });
  const drawn = [...out.markup.matchAll(/<circle /g)].length;
  assert.strictEqual(drawn, 250, "the layer thinned the set: drew " + drawn + " of 250");
  assert.strictEqual(out.n, 250);
})();

(function anAbsentLayerDrawsNothing() {
  for (const payload of [null, undefined, false, {}, { measured: false }, { measured: true }]) {
    const out = layer(payload);
    assert.strictEqual(out.markup, "", "an absent payload drew markup: " + JSON.stringify(payload));
    assert.strictEqual(out.n, 0);
  }
})();

(function aPointWithNoNumericCoordinateIsSKIPPEDnotDrawnAtZero() {
  const out = layer({
    measured: true,
    points: [
      { external_id: "bad", lat: null, lon: 12.5, joinable: true },
      { external_id: "alsobad", lat: "41.9", lon: 12.5, joinable: true },
      { external_id: "good", lat: 41.9, lon: 12.5, joinable: true },
    ],
  });
  const drawn = [...out.markup.matchAll(/<circle /g)].length;
  assert.strictEqual(drawn, 1, "a point with no numeric coordinate reached the map");
})();

// --------------------------------------------------------------------------- //
// The marker carries the page's own name, so a reader can tell what they are hovering.
// --------------------------------------------------------------------------- //
(function theTitleNamesThePageAndItsEdition() {
  const out = layer({ measured: true, points: [{ external_id: "en:p1", title: "Rome", edition: "en", lat: 41.9, lon: 12.5, joinable: true }] });
  assert.ok(/<title>Rome \(en\)<\/title>/.test(out.markup), out.markup);
})();

console.log("wiki map layer: all checks passed");
