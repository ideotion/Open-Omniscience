// Row 259 (0.6 gate, section 1's exit text): every map states the date of its OpenStreetMap data,
// and a contested border renders as contested. Run as REAL code, extracted from the shipped module.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What is pinned here is what the legend SAYS, for every source the map can draw its borders from:
//   * Natural Earth alone says Natural Earth and claims no OSM date;
//   * the built OSM border files say "as of" their date, and a partial cover names both sources;
//   * the downloaded-region preview, whose countries replace Natural Earth's, is said with ITS
//     date, or with "date not stated in the extract" -- never credited to Natural Earth, never
//     today's date (it was credited to Natural Earth, undated, until this row);
//   * the lane's object and cluster views state each country's extract date and last diff;
//   * under the default worldview, every disputed area of the SHIPPED asset is hatched contested
//     and none is attributed to a claimant.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
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
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "var window = {};\nvar document = { documentElement: { dir: 'ltr' } };\n" +
  "function fmtNum(n){ return String(n); }\n" +
  "function ooRegionName(c, n){ return n || String(c).toUpperCase(); }\n" +
  "function _ooMapPath(rings){ return (rings && rings.length) ? 'M0 0Z' : ''; }\n" +
  extract("ooIsoDate") + "\n" + extract("ooLabelText") + "\n" + extract("_mapTf") + "\n" +
  extract("_ooBoundarySource") + "\n" + extract("_ooOsmPreviewDated") + "\n" +
  extract("_ooOsmLaneVintage") + "\n" +
  extract("_ooDisputedName") + "\n" + extract("_ooDisputedClaims") + "\n" +
  extract("_ooDisputedViewNote") + "\n" + extract("_ooDisputedLayer") + "\n" +
  "module.exports = { _ooBoundarySource, _ooOsmPreviewDated, _ooOsmLaneVintage, _ooDisputedLayer };";
const F = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

// --- the border source, for every source the borders can come from ---------- //
{
  const ne = F._ooBoundarySource(null, null, 0, 0, false, 200);
  assert.strictEqual(ne.label, "Borders: Natural Earth 50m");
  assert.ok(!/as of/.test(ne.label + ne.title), "Natural Earth was given an OSM date");

  const admin0 = { vintage: "2026-09-01" };
  const all = F._ooBoundarySource(admin0, null, 240, 0, false, 0);
  assert.strictEqual(all.label, "Borders: OpenStreetMap, as of 2026-09-01");
  assert.ok(all.title.includes("© OpenStreetMap contributors (ODbL 1.0)"), all.title);
  const part = F._ooBoundarySource(admin0, null, 3, 0, false, 197);
  assert.strictEqual(part.label, "Borders: OpenStreetMap, as of 2026-09-01 · Natural Earth 50m elsewhere",
    "a partial cover read as one source");
  // Only regions built: the region file's date is the one said.
  const regions = F._ooBoundarySource(null, { vintage: "2026-08-15", counts: { regions: 9, tagged: 8, fallback: 1 } }, 0, 9, false, 200);
  assert.ok(regions.label.startsWith("Borders: OpenStreetMap, as of 2026-08-15"), regions.label);
  // An OSM file without a date is never given one.
  assert.ok(F._ooBoundarySource({}, null, 1, 0, false, 0).label.includes("as of ?"));
}

// --- the downloaded-region preview: OSM data, with its own date --------------- //
{
  const dated = F._ooBoundarySource(null, null, 0, 0, false, 199, { n: 1, date: "2026-11-02" });
  assert.strictEqual(dated.label, "Borders: Natural Earth 50m · Offline OSM preview, as of 2026-11-02",
    "the preview's borders were credited to Natural Earth or left undated");
  assert.ok(dated.title.includes("1 country drawn from the offline OSM preview"), dated.title);
  const many = F._ooBoundarySource(null, null, 0, 0, false, 190, { n: 10, date: "2026-11-02" });
  assert.ok(many.title.includes("10 countries drawn from the offline OSM preview"), many.title);
  for (const unknown of ["unknown", "", null, undefined, "today"]) {
    const u = F._ooBoundarySource(null, null, 0, 0, false, 199, { n: 2, date: unknown });
    assert.strictEqual(u.label, "Borders: Natural Earth 50m · Offline OSM preview, date not stated in the extract",
      "an undated extract was given a date: " + JSON.stringify(unknown));
  }
  // Beside built OSM borders, both dates are said.
  const both = F._ooBoundarySource({ vintage: "2026-09-01" }, null, 5, 0, false, 190, { n: 1, date: "2026-11-02" });
  assert.ok(both.label.includes("as of 2026-09-01") && both.label.includes("Offline OSM preview, as of 2026-11-02"), both.label);
  // No preview borders drawn: nothing said about a preview.
  assert.strictEqual(F._ooBoundarySource(null, null, 0, 0, false, 200, { n: 0, date: "2026-11-02" }).label, "Borders: Natural Earth 50m");
  // The overlay's own legend line says the same date.
  assert.strictEqual(F._ooOsmPreviewDated("2026-11-02"), "Offline OSM preview, as of 2026-11-02");
}

// --- the lane's views: each country's extract date and last diff --------------- //
{
  const line = F._ooOsmLaneVintage({ vintage: [
    { alpha3: "FRA", extract_date: "2026-10-01T00:00:00+00:00", last_diff: "2026-11-20T00:00:00+00:00" },
    { alpha3: "ZZZ", extract_date: null, last_diff: null },
  ] });
  assert.strictEqual(line, "Extract date FRA: 2026-10-01. Last applied diff FRA: 2026-11-20. "
    + "Extract date ZZZ: not stated in the extract. No daily diff applied since the extract.");
  assert.strictEqual(F._ooOsmLaneVintage({}), "");
}

// --- contested, under the default worldview, on the SHIPPED asset --------------- //
{
  const disputed = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "world_disputed.json"), "utf8"));
  assert.ok(disputed.areas.length >= 20, "the disputed-areas asset shrank: " + disputed.areas.length);
  const out = F._ooDisputedLayer(disputed, "contested", (v) => "#f" + v, {});
  const paths = out.markup.match(/<path [^>]*data-oomap-disputed="[^"]*"[^>]*>/g) || [];
  assert.strictEqual(paths.length, out.shown);
  assert.strictEqual(out.shown, disputed.areas.filter((a) => a.rings && a.rings.length).length, "a disputed area was dropped");
  for (const p of paths) {
    assert.ok(p.includes('fill="url(#oomap-contested)"'), "not hatched as contested: " + p.slice(0, 120));
    assert.ok(!p.includes("data-iso="), "the default worldview gave an area to a claimant: " + p.slice(0, 160));
    assert.ok(/title="[^"]*contested/.test(p), "the hover does not say contested: " + p.slice(0, 160));
  }
}

console.log("map_vintage_r259_node_test.js: all assertions passed");
