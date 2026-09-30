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
  "var OOMAP_ADMIN1_VERTEX_CAP = 1000, OOMAP_LOD_FETCH_MULT = 4;\n" +   // a small budget keeps the fixtures small
  "var OOMAP_DETAIL_TEMPLATE = 'osm_borders/detail/{a3}.json';\n" +
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
  "var _ooMapDetailCache = new Map(), _ooMapDetailHeld = 0;\n" +
  "var navigator = { deviceMemory: 1 };\n" +
  "function fetch(u){ return globalThis.__fetch(u); }\n" +
  extract("_ooLodDetailLoader") + "\n" +
  extract("_ooLodBoxOf") + "\n" +
  extract("_ooLodHit") + "\n" +
  extract("_ooLodAttach") + "\n" +
  "module.exports = { _ooMapPath, _ooStrideRings, _ooLodStep, _ooLodDecimals, _ooLodViewBox, _ooLodAttach, _ooRingsVertices, _ooLodDetailLoader, _ooMapDetailCache, held: () => _ooMapDetailHeld, resetHeld: () => { _ooMapDetailHeld = 0; } };";
const L = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

// The fixture's multiplier and template are the shipped ones (a change there must change this).
assert.ok(/const OOMAP_LOD_FETCH_MULT = 4;/.test(APP), "the fetch multiplier the fixtures assume is the shipped one");
assert.ok(/const OOMAP_DETAIL_TEMPLATE = "osm_borders\/detail\/\{a3\}\.json";/.test(APP), "the template the loader accepts is the one the split writes");

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
    assert.ok(d >= prev && d <= 5, "decimals never fall as the view narrows, and stop at 5: " + w);
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
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
let writes = 0;
const mkEl = (attrs) => {
  const a = Object.assign({}, attrs);
  return {
    a, tagName: "path", previousElementSibling: null,
    attributes: { getNamedItem: (k) => (k in a ? { value: a[k] } : null) },
    getAttribute: (k) => a[k] ?? null,
    setAttribute: (k, v) => { a[k] = String(v); if (k === "d") writes++; },
  };
};
const grid = (lon0, lat0, n) => [Array.from({ length: n }, (_, i) => [lon0 + i * 0.001, lat0 + (i % 2) * 0.001])];
const vertices = (el) => (el.a.d.match(/[ML]/g) || []).length;

async function whole() {          // a build WITHOUT the split: the file is read whole, as before
  const near = { rings: grid(10, 10, 900) };     // in sight when the view sits on lon/lat ~ (10, 10)
  const far = { rings: grid(-120, -40, 900) };   // out of sight then
  const contested = { id: "c1", rings: [[[10.0004, 10.0004], [10.0014, 10.0004], [10.0014, 10.0014]]] };
  const world = (r) => L._ooMapPath(L._ooStrideRings(r.rings, 2), 1);
  const els = {
    near: mkEl({ "data-oomap-region": "NEAR", d: world(near) }),
    far: mkEl({ "data-oomap-region": "FAR", d: world(far) }),
    disp: mkEl({ "data-oomap-disputed": "c1", d: L._ooMapPath(contested.rings) }),
    under: mkEl({ d: L._ooMapPath(contested.rings) }),
  };
  els.disp.previousElementSibling = els.under;
  const label = { dataset: {}, _t: "base", getAttribute() { return this._t; }, setAttribute(k, v) { this._t = v; } };
  const svg = {
    isConnected: true,
    querySelectorAll: (sel) => sel.startsWith("path[data-oomap-region]") ? [els.near, els.far]
      : sel.startsWith("path[data-oomap-disputed]") ? [els.disp] : [],
  };
  const host = { _ooLodSrc: { regions: { NEAR: near, FAR: far }, countries: {}, disputed: { c1: contested } }, querySelector: () => label };
  const lod = L._ooLodAttach(host, svg);
  assert.ok(lod, "a map with OSM-drawn outlines gets the behaviour");
  assert.strictEqual(L._ooLodAttach({ querySelector() {} }, svg), null, "a map without them gets none");
  const run = async (vb) => { lod.view(vb); await wait(250); };
  writes = 0;
  lod.now({ x: 0, y: 0, w: 720, h: 350 });
  assert.strictEqual(writes, 0, "the load-time pass redraws nothing: the world view was already drawn");
  assert.ok(label._t.includes("T:Borders are drawn thinner"), "the legend says so at load, before any zoom");
  await run({ x: 375, y: 150, w: 10, h: 5 });
  assert.strictEqual(vertices(els.near), 900, "in sight and under the budget: the file's own rings");
  assert.ok(vertices(els.far) < 900, "out of sight: the coarse outline, not the file: " + vertices(els.far));
  assert.ok(!label._t.includes("thinner"), "nothing in sight is thinner than the file, so the legend does not say so");
  assert.ok(/\.\d{3}/.test(els.near.a.d), "zoomed in keeps three decimals");
  assert.strictEqual(els.disp.a.d, els.under.a.d, "the contested hatch and its fill move together");
  assert.ok(/\.\d{3}/.test(els.disp.a.d), "the contested outline sits on the same grid as the borders it shares");
  await run({ x: 0, y: 0, w: 720, h: 350 });
  assert.ok(vertices(els.near) < 900, "zoomed out again: strided");
  assert.ok(!/\.\d{2}/.test(els.disp.a.d), "and the contested outline is back on the world grid");
  const before = writes;
  lod.view({ x: 375, y: 150, w: 10, h: 5 });
  L._ooLodAttach(host, svg);
  await wait(250);
  assert.strictEqual(writes, before, "a stale redraw is cancelled by the next attach");
}

async function split() {          // a build WITH the split: world outlines now, a country's detail on demand
  const fullNear = grid(10, 10, 900), fullNear2 = grid(10.5, 10, 900), fullFar = grid(-120, -40, 900);
  const lonlat = (lon, lat, wLon) => ({ x: (lon + 180) / 360 * 720, y: (90 - lat) / 180 * 350, w: wLon / 360 * 720, h: wLon / 360 * 720 / 2 });
  const coarse = (rings) => [rings[0].filter((_, i) => i % 30 === 0)];          // 30 vertices each
  const regions = {
    "AA-1": { country: "AAA", rings: coarse(fullNear), full_vertices: 900 },
    "AA-2": { country: "AAA", rings: coarse(fullNear2), full_vertices: 900 },
    "BB-1": { country: "BBB", rings: coarse(fullFar), full_vertices: 900 },
    "r9": { country: null, rings: coarse(fullNear), full_vertices: 30 },        // no country: nothing to fetch
    // The world outline lost this country's far island (it sits at lon ~49.5); full_bbox still knows.
    "II-1": { country: "III", rings: [[[30, 20], [30.5, 20], [30.5, 20.5]]], full_vertices: 900, full_bbox: [30, 20, 49.6, 20.5] },
    // Four more countries' worth, so a wide view holds more than the fetch multiple at full size.
    "DD-1": { country: "DDD", rings: coarse(grid(60, 20, 900)), full_vertices: 900 },
    "DD-2": { country: "DDD", rings: coarse(grid(60.5, 20, 900)), full_vertices: 900 },
    "DD-3": { country: "DDD", rings: coarse(grid(61, 20, 900)), full_vertices: 900 },
    "DD-4": { country: "DDD", rings: coarse(grid(61.5, 20, 900)), full_vertices: 900 },
    "DD-5": { country: "DDD", rings: coarse(grid(62, 20, 900)), full_vertices: 900 },
    "EE-1": { country: "EEE", rings: coarse(grid(-60, 50, 900)), full_vertices: 900 },
  };
  const els = Object.fromEntries(Object.keys(regions).map((k) => [k, mkEl({ "data-oomap-region": k, d: L._ooMapPath(regions[k].rings, 1) })]));
  const svg = { isConnected: true, querySelectorAll: (sel) => sel.startsWith("path[data-oomap-region]") ? Object.values(els) : [] };
  const label = { dataset: {}, _t: "base", getAttribute() { return this._t; }, setAttribute(k, v) { this._t = v; } };
  const fetched = [];
  globalThis.__fetch = (u) => {
    fetched.push(u);
    const a3 = /\/([A-Z]{3})\.json$/.exec(u)[1];
    if (a3 === "BBB") return Promise.resolve({ ok: false });
    const body = { schema: 1, vintage: "V1", a3, regions: { "AA-1": { rings: fullNear }, "AA-2": { rings: fullNear2 },
      "II-1": { rings: [[[30, 20], [30.5, 20], [30.5, 20.5], [49.5, 20.2]]] }, "EE-1": { rings: grid(-60, 50, 900) } } };
    if (a3 === "EEE") return new Promise((res) => { globalThis.__releaseEEE = () => res({ ok: true, json: async () => body }); });
    return Promise.resolve({ ok: true, json: async () => body });
  };
  L._ooMapDetailCache.clear();
  const detail = L._ooLodDetailLoader("osm_borders/detail/{a3}.json", "V1");
  assert.strictEqual(L._ooLodDetailLoader("../etc/{a3}.json"), null, "a template outside osm_borders/ is refused");
  assert.strictEqual(L._ooLodDetailLoader("osm_borders/../x/{a3}.json"), null);
  assert.strictEqual(L._ooLodDetailLoader("osm_borders/other/{a3}.json"), null, "only the one path the split writes is accepted");
  assert.strictEqual(L._ooLodDetailLoader("osm_borders/detail/{a3}.json?x=1"), null);
  assert.strictEqual(await detail("../x"), false, "only three capitals ever name a file");
  assert.deepStrictEqual(fetched, []);
  const host = { _ooLodSrc: { regions, countries: {}, disputed: {}, detail }, querySelector: () => label };
  const lod = L._ooLodAttach(host, svg);
  writes = 0;
  lod.now({ x: 0, y: 0, w: 720, h: 350 });
  assert.strictEqual(writes, 0, "the world view is what was drawn: nothing rewritten, nothing fetched");
  assert.deepStrictEqual(fetched, [], "a world view fetches no detail");
  assert.ok(label._t.includes("T:Borders are drawn thinner"), "the world outline is thinner than the file, and says so");

  // Narrow to a view holding only AA-1 (and the country-less r9): their full sizes, 900 + 30, fit the
  // budget of 1000, so the detail of AAA -- and only AAA -- is fetched, once.
  const narrow = { x: 380, y: 155.4, w: 0.2, h: 0.2 };
  lod.view(narrow); await wait(450);
  assert.deepStrictEqual(fetched, ["/static/osm_borders/detail/AAA.json"], "only the country in sight is fetched, once");
  assert.strictEqual(vertices(els["AA-1"]), 900, "its detail is drawn, the file's own rings");
  assert.ok(/\.\d{4}/.test(els["AA-1"].a.d), "at the zoom's own decimals");
  assert.ok(vertices(els["AA-2"]) < 900 && vertices(els["BB-1"]) < 900, "what is out of sight stays the world outline");
  assert.ok(!label._t.includes("thinner"), "everything in sight is at the file's full detail, so the legend does not say otherwise");
  lod.view(narrow); await wait(250);
  assert.strictEqual(fetched.length, 1, "a second pass over the same view fetches nothing");

  // MID-ZOOM: two regions, 1,800 vertices at full size, over the budget of 1,000 but within the fetch
  // multiple. Their detail is used, strided by the SAME step (2), so neither neighbour is drawn at a
  // different detail from the other, and it is finer than the 30-vertex world outline.
  const both = { x: 379, y: 155.2, w: 6, h: 3 };
  lod.view(both); await wait(300);
  assert.strictEqual(vertices(els["AA-1"]), 450, "over the budget but within the multiple: full rings strided by 2");
  assert.strictEqual(vertices(els["AA-2"]), 450, "its neighbour on the same stride");
  assert.ok(label._t.includes("thinner"), "still thinner than the file, and the legend says so");
  assert.strictEqual(fetched.filter((u) => u.includes("AAA")).length, 1, "the cached detail was reused, not fetched again");

  // BEYOND THE MULTIPLE (5,400 vertices of DDD's regions alone against 4,000): nothing is fetched and
  // the world outline is what is drawn.
  const wide = lonlat(61, 20.5, 6);
  lod.view(wide); await wait(300);
  assert.ok(!fetched.some((u) => u.includes("DDD")), "more than the multiple in sight: no detail is fetched");
  assert.ok(vertices(els["DD-1"]) <= 30, "and the world outline is drawn");

  // A FAR ISLAND THE WORLD OUTLINE LOST: the view at lon 49.5 is outside the world rings' box but
  // inside full_bbox, so the country's detail is fetched and the island is drawn.
  lod.view(lonlat(49.5, 20.2, 0.5)); await wait(450);
  assert.ok(fetched.includes("/static/osm_borders/detail/III.json"), "full_bbox makes a dropped island reachable");
  assert.strictEqual(vertices(els["II-1"]), 4, "and its full rings are drawn");

  // THE VIEW NOW, NOT THE ONE THAT ASKED: EEE's file is slow. The view moves back to AA-1 before it
  // arrives; when it does, EEE is out of sight and must not be drawn at full detail.
  lod.view(lonlat(-60, 50.02, 0.4)); await wait(300);
  lod.view(narrow); await wait(200);
  globalThis.__releaseEEE(); await wait(450);
  assert.ok(vertices(els["EE-1"]) < 900, "a late detail answer does not redraw an outline that left the view: " + vertices(els["EE-1"]));
  assert.strictEqual(vertices(els["AA-1"]), 900, "and the view in force is the one drawn");

  // LEAVE AND COME BACK: AA-1's detail is dropped from the map's hands when it leaves, and asked for
  // again (from the cache: no new request) when it returns.
  lod.view(lonlat(-120, -40.05, 0.4)); await wait(450);
  assert.ok(vertices(els["AA-1"]) < 900, "out of sight: back to the world outline");
  const nAAA = fetched.filter((u) => u.includes("AAA")).length;
  lod.view(narrow); await wait(450);
  assert.strictEqual(vertices(els["AA-1"]), 900, "back in sight: drawn at full detail again");
  assert.strictEqual(fetched.filter((u) => u.includes("AAA")).length, nAAA, "from the cache, with no new request");

  // A country whose detail file is missing keeps its world outline, is asked for once, and the map says so.
  const far = { x: 120, y: 252.7, w: 0.2, h: 0.2 };                               // lon ~ -120, lat ~ -40
  lod.view(far); await wait(450);
  assert.strictEqual(fetched.filter((u) => u.includes("BBB")).length, 1, "the missing country was asked for");
  assert.ok(vertices(els["BB-1"]) < 900 && label._t.includes("thinner"), "its world outline stays and the legend keeps saying so");
  lod.view(far); await wait(250);
  assert.strictEqual(fetched.filter((u) => u.includes("BBB")).length, 1, "a missing file is never asked for twice");
  return { els, label, lod, fetched };
}

async function cache() {          // the detail cache: kept for a revisit, sized from the machine, newest never evicted
  const docs = { AAA: 250000, BBB: 250000, CCC: 250000, DDD: 900000 };
  const seen = [];
  globalThis.__fetch = (u) => {
    const a3 = /\/([A-Z]{3})\.json$/.exec(u)[1]; seen.push(a3);
    if (a3 === "OLD") return Promise.resolve({ ok: true, json: async () => ({ a3, vintage: "V0", country: { rings: [[[0, 0]]] }, regions: {} }) });
    if (a3 === "ERR") return Promise.resolve({ ok: false });
    return Promise.resolve({ ok: true, json: async () => ({ a3, vintage: "V1", country: { rings: [Array.from({ length: docs[a3] }, () => [0, 0])] }, regions: {} }) });
  };
  L._ooMapDetailCache.clear(); L.resetHeld();
  const detail = L._ooLodDetailLoader("osm_borders/detail/{a3}.json", "V1");  // deviceMemory 1 -> room for 600,000 vertices
  await detail("AAA"); await detail("AAA");
  assert.deepStrictEqual(seen, ["AAA"], "a revisit is free");
  await detail("BBB");
  assert.deepStrictEqual([...L._ooMapDetailCache.keys()], ["AAA", "BBB"], "500,000 vertices fit the room: both kept");
  await detail("AAA");                                                          // touch: AAA is now the most recently used
  await detail("CCC");
  assert.deepStrictEqual([...L._ooMapDetailCache.keys()], ["AAA", "CCC"], "over the room, the LEAST recently used goes (BBB), not the oldest fetched");
  await detail("DDD");
  assert.deepStrictEqual([...L._ooMapDetailCache.keys()], ["DDD"], "a country larger than the whole room is still kept: the newest is never dropped");
  assert.strictEqual(L.held(), 900000, "the count is the vertices the cache really holds");
  // An entry evicted WHILE it loads is not counted (it would leak the counter for the session).
  let release;
  const slow = globalThis.__fetch;
  globalThis.__fetch = (u) => /AAA/.test(u) ? new Promise((r) => { release = () => r({ ok: true, json: async () => ({ a3: "AAA", vintage: "V1", country: { rings: [Array.from({ length: 250000 }, () => [0, 0])] }, regions: {} }) }); }) : slow(u);
  const pending = detail("AAA");
  L._ooMapDetailCache.delete("AAA");                                            // what an eviction does to a pending entry
  release(); await pending;
  assert.strictEqual(L.held(), 900000, "a late arrival that is no longer in the cache adds nothing");
  globalThis.__fetch = slow;
  // Another vintage's detail is not this world file's: refused.
  assert.strictEqual(await detail("OLD"), false, "a detail file of another build is refused");
  // A miss is not remembered for the session: the next map retries it.
  const before = seen.length;
  await detail("ERR"); await detail("ERR");
  assert.strictEqual(seen.length - before, 2, "a failed read is retried, not cached as missing");
}

(async () => {
  await whole();
  const r = await split();
  await cache();
  console.log("oomap_lod_node_test.js: all assertions passed");
  void r;
})().catch((e) => { console.error(e); process.exit(1); });
