// The ONE projection seam, run as REAL code (Q801, 2026-09-15).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Every map surface in this app draws through `project(lon, lat)`. The properties
// below are the ones a source grep cannot tell apart from their opposites, so they
// are EXECUTED against the shipped function rather than asserted about its text:
//
//   * that it is EQUAL-AREA at all -- the entire reason the projection was changed.
//     A choropleth drawn on an area-distorting projection makes a high-latitude
//     country's fill look like more evidence than an equatorial one carrying the
//     same number, which is the projection silently editing the data.
//   * that the Newton INVERSE actually inverts it, measured by ROUND TRIP rather
//     than by a formula rule (a character rule fails toward silence).
//   * that it is VIEW-INDEPENDENT. The cheap focus-redraw path in app-map.js is
//     sound only while the projection ignores zoom and pan; if that ever stops
//     holding, the failure is MISPLACED markers, not stale ones, and it reads as a
//     data bug rather than a rendering one.
//   * that the coefficients are the PUBLISHED ones.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

// The seam itself, lifted verbatim from the shipped module. A re-typed copy would
// pass while the real map drew something else.
const _from = APP.indexOf("const EE_A1");
const _to = APP.indexOf("// The projected outline of the whole sphere");
assert.ok(_from !== -1 && _to > _from,
  "the projection seam was not found -- did project()/EE_A1 move or get renamed?");
const SEAM = APP.slice(_from, _to);

const src = SEAM + "\nmodule.exports = { project, unproject, _mapGraticule, "
  + "MAP_W, MAP_H, MAP_ASPECT, MAP_MIN_W, EE_A1, EE_A2, EE_A3, EE_A4, EE_M, EE_X_MAX, EE_Y_MAX };\n";
const mod = { exports: {} };
new Function("module", "exports", src)(mod, mod.exports);
const {
  project, unproject, _mapGraticule,
  MAP_W, MAP_H, MAP_ASPECT, EE_A1, EE_A2, EE_A3, EE_A4, EE_Y_MAX,
} = mod.exports;

const RAD = Math.PI / 180;

let pass = 0, fail = 0;
function check(name, fn) {
  try { fn(); pass++; console.log("ok   - " + name); }
  catch (e) { fail++; console.log("FAIL - " + name + ": " + e.message); }
}

// ---- the coefficients ------------------------------------------------------------ //

check("the coefficients are the published Equal Earth ones", () => {
  // Savric, Patterson & Jenny (2018), DOI 10.1080/13658816.2018.1504949, as carried
  // identically by OSGeo PROJ (src/projections/eqearth.cpp) and d3-geo
  // (src/projection/equalEarth.js). Confirmed against both on 2026-09-16.
  assert.strictEqual(EE_A1, 1.340264);
  assert.strictEqual(EE_A2, -0.081106);
  assert.strictEqual(EE_A3, 0.000893);
  assert.strictEqual(EE_A4, 0.003796);
});

check("EE_Y_MAX is DERIVED and reproduces PROJ's own documented MAX_Y", () => {
  // PROJ hardcodes MAX_Y = 1.3173627591574 for a unit sphere. Ours is computed from
  // the polynomial, so agreement is an independent check on the whole forward form,
  // not a transcription of the same constant.
  assert.ok(Math.abs(EE_Y_MAX - 1.3173627591574) < 1e-12,
    "derived pole y = " + EE_Y_MAX + " but PROJ documents 1.3173627591574");
});

// ---- the box ---------------------------------------------------------------------- //

check("the box is the projection's OWN aspect, not a chosen rectangle", () => {
  assert.strictEqual(MAP_W, 720);
  // 2.0546:1, not the old 2:1 of a 720x360 plate-carree box.
  assert.ok(Math.abs(MAP_ASPECT - 2.0545821300028537) < 1e-9, "aspect = " + MAP_ASPECT);
  assert.ok(Math.abs(MAP_H - MAP_W / MAP_ASPECT) < 1e-9, "MAP_H must follow MAP_W and the aspect");
  assert.ok(Math.abs(MAP_H - 350.4362222789312) < 1e-6, "MAP_H = " + MAP_H);
  assert.notStrictEqual(MAP_H, 360, "360 would be the retired plate-carree box");
});

// ---- known point -> known pixel --------------------------------------------------- //

check("known points project to known pixels", () => {
  const at = (lon, lat) => { const p = project(lon, lat); return [+p.x.toFixed(3), +p.y.toFixed(3)]; };
  assert.deepStrictEqual(at(0, 0), [360, 175.218], "null island sits at the centre of the box");
  assert.deepStrictEqual(at(180, 0), [720, 175.218], "the antimeridian is the widest point");
  assert.deepStrictEqual(at(-180, 0), [0, 175.218]);
  assert.deepStrictEqual(at(0, 90), [360, 0], "the north pole");
  assert.deepStrictEqual(at(0, -90), [360, 350.436], "the south pole");
  // Three real cities, so a sign flip or a swapped axis cannot hide behind symmetry.
  assert.deepStrictEqual(at(2.3522, 48.8566), [363.916, 52.405], "Paris");
  assert.deepStrictEqual(at(-74.006, 40.7128), [229.406, 70.533], "New York");
  assert.deepStrictEqual(at(139.6917, 35.6895), [613.971, 82.4], "Tokyo");
});

check("the pole is a LINE, not a point -- Equal Earth is pseudocylindrical", () => {
  // Measured, and worth pinning because it is counter-intuitive and it constrains the
  // sphere outline: the meridians do NOT converge to a point, so (-180, 90) and
  // (180, 90) are different pixels for the same place. An implementation that drew a
  // pole point would be a different projection.
  const w = (project(180, 90).x - project(-180, 90).x) / MAP_W;
  assert.ok(Math.abs(w - 0.5925) < 0.001, "pole line is " + w.toFixed(4) + " of the equator");
  // The centre meridian still runs down the middle at every latitude.
  for (const lat of [-90, -45, 0, 45, 90]) {
    assert.ok(Math.abs(project(0, lat).x - MAP_W / 2) < 1e-9, "centre meridian bent at lat " + lat);
  }
  // North and south are symmetric.
  assert.ok(Math.abs(project(180, 90).x - project(180, -90).x) < 1e-9);
});

// ---- THE property ----------------------------------------------------------------- //

check("it is EQUAL-AREA: a cell's drawn area is proportional to its true area", () => {
  // Shoelace over the four projected corners of a 1-degree cell, against the exact
  // spherical area of the same cell. Equal-area means the RATIO is constant; any
  // drift is the projection editing the data.
  const cell = (lon, lat, d) => {
    const c = [[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d]]
      .map(([x, y]) => project(x, y));
    let s = 0;
    for (let i = 0; i < 4; i++) { const p = c[i], q = c[(i + 1) % 4]; s += p.x * q.y - q.x * p.y; }
    return Math.abs(s) / 2;
  };
  const truth = (lat, d) => d * RAD * (Math.sin((lat + d) * RAD) - Math.sin(lat * RAD));
  const ratios = [];
  for (let lat = -80; lat <= 80; lat += 10) ratios.push(cell(0, lat, 1) / truth(lat, 1));
  const lo = Math.min(...ratios), hi = Math.max(...ratios);
  // The residue is the 1-degree cell discretisation, not the projection.
  assert.ok((hi - lo) / lo < 1e-4,
    "area ratio drifts by " + ((hi - lo) / lo * 100).toFixed(4) + "% across latitude");
});

check("and the projection it replaced was NOT equal-area, so the change is load-bearing", () => {
  // The retired plate carree inflated a 70N cell threefold against the equator. This
  // check exists so "equal-area" above cannot pass vacuously against a scale factor.
  const pc = (lon, lat) => ({ x: (lon + 180) / 360 * 720, y: (90 - lat) / 180 * 360 });
  const cell = (lat, d) => {
    const c = [[0, lat], [d, lat], [d, lat + d], [0, lat + d]].map(([x, y]) => pc(x, y));
    let s = 0;
    for (let i = 0; i < 4; i++) { const p = c[i], q = c[(i + 1) % 4]; s += p.x * q.y - q.x * p.y; }
    return Math.abs(s) / 2;
  };
  const truth = (lat, d) => d * RAD * (Math.sin((lat + d) * RAD) - Math.sin(lat * RAD));
  const inflation = (cell(70, 1) / truth(70, 1)) / (cell(0, 1) / truth(0, 1));
  assert.ok(inflation > 2.9, "plate carree inflation at 70N measured " + inflation.toFixed(2) + "x");
});

// ---- the inverse ------------------------------------------------------------------ //

check("the Newton inverse inverts it, verified by ROUND TRIP over the whole sphere", () => {
  let worst = 0, at = null;
  for (let lon = -180; lon <= 180; lon += 5) {
    for (let lat = -90; lat <= 90; lat += 5) {
      const p = project(lon, lat), q = unproject(p.x, p.y);
      const d = Math.max(Math.abs(q.lon - lon), Math.abs(q.lat - lat));
      if (d > worst) { worst = d; at = [lon, lat]; }
    }
  }
  assert.ok(worst < 1e-9, "worst round-trip error " + worst + " deg at " + JSON.stringify(at));
});

check("the inverse stays inside the sphere for a point outside the lens", () => {
  // The corners of the BOX are not map. A pointer there must still yield a usable
  // latitude rather than a NaN, because the caller feeds it straight into a readout.
  for (const [x, y] of [[0, 0], [MAP_W, 0], [0, MAP_H], [MAP_W, MAP_H]]) {
    const q = unproject(x, y);
    assert.ok(isFinite(q.lat) && Math.abs(q.lat) <= 90.000001, "lat " + q.lat + " at " + x + "," + y);
    assert.ok(isFinite(q.lon), "lon " + q.lon + " at " + x + "," + y);
  }
});

// ---- view independence ------------------------------------------------------------ //

check("project() is VIEW-INDEPENDENT -- the precondition the cheap focus path rides on", () => {
  // Behavioural, not a grep: mutate a module-level viewBox the way a zoom/pan would
  // and require the projected coordinate to be byte-identical. A grep for "MAP_VB"
  // inside project() would pass just as well against code that read it and threw the
  // value away.
  // SEAM already declares MAP_VB; the probe only needs a handle to reassign it.
  const probe = new Function("module", "exports",
    SEAM + "\nmodule.exports = { project, setVB: (v) => { MAP_VB = v; } };");
  const m2 = { exports: {} };
  probe(m2, m2.exports);
  const before = m2.exports.project(30, 45);
  m2.exports.setVB({ x: 111, y: 222, w: 7, h: 3 });
  const after = m2.exports.project(30, 45);
  assert.deepStrictEqual(after, before, "the projection moved when the viewBox did");
});

check("project() is pure: same input, byte-identical output", () => {
  assert.deepStrictEqual(project(12.5, -33.25), project(12.5, -33.25));
});

// ---- the graticule ---------------------------------------------------------------- //

check("meridians are drawn CURVED, never as a straight line between their endpoints", () => {
  // In Equal Earth a meridian genuinely bows; drawing it straight would be a
  // fabricated shape. The midpoint of the real meridian must not sit on the chord.
  const lon = 90;
  const a = project(lon, -90), b = project(lon, 90), mid = project(lon, 0);
  const chordX = a.x + (b.x - a.x) * ((mid.y - a.y) / (b.y - a.y));
  assert.ok(Math.abs(mid.x - chordX) > 1,
    "the 90E meridian is within " + Math.abs(mid.x - chordX).toFixed(3) + "px of its chord");
  const g = _mapGraticule(30, "0.3");
  assert.ok(g.includes("<polyline"), "meridians must be polylines, not <line>");
});

check("parallels are straight, and SHORTER toward the poles", () => {
  const width = (lat) => project(180, lat).x - project(-180, lat).x;
  assert.ok(Math.abs(width(0) - MAP_W) < 1e-9, "the equator spans the full box");
  // Measured against the shipped seam: 0.9354 at 30, 0.7534 at 60, 0.5925 at the pole.
  assert.ok(Math.abs(width(60) / width(0) - 0.7534) < 0.001,
    "60N measured " + (width(60) / width(0)).toFixed(4) + " of the equator");
  assert.ok(width(85) < width(60) && width(30) < width(0),
    "meridians must keep converging toward the pole");
  // Straight: both endpoints of a parallel share a y, so a <line> is honest here.
  assert.ok(Math.abs(project(-180, 60).y - project(180, 60).y) < 1e-9);
});

check("the graticule is drawn by ONE builder, so no surface can re-derive it", () => {
  const g = _mapGraticule(30, "0.25");
  assert.ok(g.includes('stroke-width="0.25"'), "the caller's stroke width must reach the output");
  assert.ok(!g.includes("NaN"), "a NaN in a path silently drops the whole element");
});

console.log("\n" + pass + " passed, " + fail + " failed");
process.exit(fail ? 1 : 0);
