// The map's borders follow the VIEW (browser walk of 0.5, 2026-09-30), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Before, the region layer was strided ONCE at load for the whole map and the country outlines
// were not budgeted at all, and every coordinate was rounded to one decimal of a 720-unit map
// (~5 km): zooming in could never show the detail the file carries. What is pinned here:
//   * a wide view is strided to the budget, a ring too short to stride is kept whole (no island
//     vanishes), and a view whose outlines fit the budget draws the FILE's own rings;
//   * only what is IN SIGHT counts against the budget, so zooming in sharpens;
//   * what left the view goes back to the coarse world outline (the DOM does not creep up to
//     the whole file over a few pans);
//   * decimals grow with the zoom and the whole map keeps one;
//   * the legend says "thinner than the file" only while something in sight is.
// EXTRACTED from the shipped module, never re-typed.

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

const src =
  "var OOI18N = { t: (x) => 'T:' + x };\n" +
  "var window = { OOI18N };\n" +
  "var MAP_W = 720, MAP_H = 350;\n" +
  "var OOMAP_ADMIN1_VERTEX_CAP = 1000;\n" +                     // a small budget keeps the fixtures small
  // A linear stand-in for the projection: the LOD logic only needs project/unproject to agree.
  "function project(lon, lat){ return { x: (lon + 180) / 360 * MAP_W, y: (90 - lat) / 180 * MAP_H }; }\n" +
  "function unproject(px, py){ return { lon: px / MAP_W * 360 - 180, lat: 90 - py / MAP_H * 180 }; }\n" +
  extract("_ooMapPath") + "\n" +
  extract("_ooStrideRings") + "\n" +
  extract("_ooRingsVertices") + "\n" +
  extract("_ooLodStep") + "\n" +
  extract("_ooLodDecimals") + "\n" +
  extract("_ooLodViewBox") + "\n" +
  "var _ooLodBoxes = new WeakMap();\n" +
  extract("_ooLodBoxOf") + "\n" +
  extract("_ooLodHit") + "\n" +
  extract("_ooLodAttach") + "\n" +
  "module.exports = { _ooStrideRings, _ooLodStep, _ooLodDecimals, _ooLodViewBox, _ooLodAttach, _ooRingsVertices };";
const L = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

// --- 1. stride ------------------------------------------------------------- //
{
  const ring = Array.from({ length: 100 }, (_, i) => [i, i]);
  const tiny = [[0, 0], [1, 0], [1, 1]];
  const out = L._ooStrideRings([ring, tiny], 10);
  assert.strictEqual(out[0].length, 10, "a long ring keeps every 10th vertex");
  assert.strictEqual(out[1].length, 3, "an island too short to stride is kept whole");
  assert.strictEqual(L._ooStrideRings([ring], 1)[0], ring, "step 1 draws the file's own ring");
  assert.strictEqual(L._ooLodStep([400, 500], 1000), 1, "what fits the budget is not strided");
  assert.strictEqual(L._ooLodStep([1500, 500], 1000), 2);
  assert.strictEqual(L._ooLodStep([], 1000), 1);
}

// --- 2. decimals ----------------------------------------------------------- //
{
  assert.strictEqual(L._ooLodDecimals(720), 1, "the whole map keeps one decimal");
  assert.strictEqual(L._ooLodDecimals(undefined), 1);
  let prev = 1;
  for (const w of [400, 100, 30, 10, 1]) {
    const d = L._ooLodDecimals(w);
    assert.ok(d >= prev && d <= 4, "decimals never fall as the view narrows, and stop at 4: " + w);
    prev = d;
  }
  assert.ok(L._ooLodDecimals(28.8) >= 3, "the tightest zoom keeps a ~55 m grid");
}

// --- 3. the view's box ----------------------------------------------------- //
{
  assert.strictEqual(L._ooLodViewBox({ x: 0, y: 0, w: 720, h: 350 }), null, "the whole map has no box");
  const b = L._ooLodViewBox({ x: 360, y: 175, w: 36, h: 17.5 });
  assert.ok(b[0] < 0 && b[2] > 19 && b[1] < -9 && b[3] > 0, "the box covers the view, padded: " + b);
}

// --- 4. the attached behaviour, on a fake svg ------------------------------ //
{
  const mkEl = (attrs) => { const a = Object.assign({}, attrs); return { a, getAttribute: (k) => a[k] ?? null, setAttribute: (k, v) => { a[k] = String(v); } }; };
  const grid = (lon0, lat0, n) => [Array.from({ length: n }, (_, i) => [lon0 + i * 0.001, lat0 + (i % 2) * 0.001])];
  const near = { rings: grid(10, 10, 900) };     // in sight when the view sits on lon/lat ~ (10, 10)
  const far = { rings: grid(-120, -40, 900) };   // out of sight then
  const els = { near: mkEl({ "data-oomap-region": "NEAR" }), far: mkEl({ "data-oomap-region": "FAR" }) };
  const label = { dataset: {}, _t: "base", getAttribute() { return this._t; }, setAttribute(k, v) { this._t = v; } };
  const svg = { querySelectorAll: (sel) => sel.startsWith("path[data-oomap-region]") ? [els.near, els.far] : [] };
  const host = { _ooLodSrc: { regions: { NEAR: near, FAR: far }, countries: {} }, querySelector: () => label };
  const lod = L._ooLodAttach(host, svg);
  assert.ok(lod, "a map with OSM-drawn outlines gets the behaviour");
  assert.strictEqual(L._ooLodAttach({ querySelector() {} }, svg), null, "a map without them gets none");
  const vertices = (el) => (el.a.d.match(/[ML]/g) || []).length;
  const run = (vb) => new Promise((res) => { lod.view(vb); setTimeout(res, 200); });
  (async () => {
    await run({ x: 0, y: 0, w: 720, h: 350 });
    assert.ok(vertices(els.near) + vertices(els.far) <= 1000 + 2, "the world view is strided to the budget: " + (vertices(els.near) + vertices(els.far)));
    assert.ok(label._t.includes("T:Borders are drawn thinner"), "the legend says the outline is thinner than the file");
    // Zoom to lon/lat ~ (10, 10): x = 190/360*720 = 380, y = 80/180*350 ~ 155.6. Only NEAR is in sight.
    await run({ x: 375, y: 150, w: 10, h: 5 });
    assert.strictEqual(vertices(els.near), 900, "in sight and under the budget: the file's own rings");
    assert.ok(vertices(els.far) < 900, "out of sight: the coarse outline, not the file: " + vertices(els.far));
    assert.ok(!label._t.includes("thinner"), "nothing in sight is thinner than the file, so the legend does not say so");
    assert.ok(/\.\d{3}/.test(els.near.a.d), "zoomed in keeps three decimals");
    // Zoom back out: the coarse outline again, and the same key means no needless redraw.
    await run({ x: 0, y: 0, w: 720, h: 350 });
    assert.ok(vertices(els.near) < 900, "zoomed out again: strided");
    console.log("oomap_lod_node_test.js: all assertions passed");
  })().catch((e) => { console.error(e); process.exit(1); });
}
