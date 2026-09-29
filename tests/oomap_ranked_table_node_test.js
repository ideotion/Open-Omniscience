// Q816 (0.5 row E, S3): the map's ranked table and its region choropleth, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Two refusals are guarded here, and neither shows in a diff:
//   1. the table beside a choropleth is NEVER capped -- every area with a value is a row,
//      however many there are (the Observatory rule, invariant #31(c)); and
//   2. a region the data does not name is drawn as "no data" (the hatch), never as a
//      zero and never as the colour of its neighbour -- the negative-space fixture.
// A source-level assertion cannot tell a capped table from a full one, so this runs the
// functions EXTRACTED from the shipped module (a re-typed copy would pass while the real
// renderer was broken).

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
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "var window = {};\n" +
  "var OOMAP_ADMIN1_VERTEX_CAP = 120000;\n" +
  // The Regions toggle OFF: region mode must draw anyway, because there the layer IS the data.
  "var _ooMapRegionsOn = false;\n" +
  "function _ooMapPath(rings){ return (rings && rings.length) ? 'M0 0Z' : ''; }\n" +
  extract("fmtNum") + "\n" +
  extract("ooLabelText") + "\n" +
  extract("_ooAdmin1Name") + "\n" +
  extract("_ooAdmin1Layer") + "\n" +
  extract("_ooRankedTable") + "\n" +
  "module.exports = { _ooAdmin1Layer, _ooRankedTable };";
const { _ooAdmin1Layer, _ooRankedTable } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const rowsOf = (html) => (html.match(/data-oomap-rank-row/g) || []).length;

// --- 1. the table is never capped ------------------------------------------ //
{
  const n = 1234;                         // far past any "top 10/20/100" a cap would pick
  const rows = Array.from({ length: n }, (_, i) => ({ label: "Area " + i, value: i % 97, text: String(i % 97) }));
  const html = _ooRankedTable(rows, [], {});
  assert.strictEqual(rowsOf(html), n, "the ranked table dropped rows: " + rowsOf(html) + " of " + n);
  // fmtNum groups digits with the locale's separator (a narrow space here); read digits only.
  assert.ok(/Ranked table · 1\D?234 areas with data/.test(html),
    "the summary does not state the full count: " + html.slice(0, 400));
  assert.ok(/<details class="oomap-rank" open/.test(html), "the table is not open by default");
}

// --- ties share a rank; the order is by value -------------------------------- //
{
  const html = _ooRankedTable([
    { label: "B", value: 5, text: "5" }, { label: "A", value: 5, text: "5" }, { label: "C", value: 9, text: "9" },
  ], [], { label: "Articles" });
  const cells = [...html.matchAll(/<tr data-oomap-rank-row><td[^>]*>([^<]*)<\/td><td[^>]*>([^<]*)</g)].map(m => m[1] + ":" + m[2]);
  assert.deepStrictEqual(cells, ["1:C", "2:A", "2:B"], "rank or order wrong: " + cells);
  assert.ok(html.includes(">Articles<"), "the measure's own label is not the value column's header");
  assert.ok(html.includes("Ranked table"), html);
}

// --- a single row reads in the singular -------------------------------------- //
{
  const html = _ooRankedTable([{ label: "X", value: 1, text: "1" }], [], {});
  assert.ok(html.includes("Ranked table · 1 area with data"), html.slice(0, 300));
}

// --- the areas with no value are COUNTED, never listed as zeros --------------- //
{
  const html = _ooRankedTable([{ label: "X", value: 3, text: "3" }], ["Y", "Z"], {});
  assert.strictEqual(rowsOf(html), 1, "a no-data area became a table row");
  assert.ok(html.includes("2 areas with no data: hatched on the map, never counted as zero."), html);
  assert.ok(html.includes('title="Y, Z"'), "the no-data areas are not named in the hover");
  const one = _ooRankedTable([{ label: "X", value: 3, text: "3" }], ["Y"], {});
  assert.ok(one.includes("1 area with no data"), one);
  assert.ok(!_ooRankedTable([{ label: "X", value: 3, text: "3" }], [], {}).includes("no data"),
    "a no-data line was drawn with nothing missing");
}

// --- 2. the negative-space fixture: a region absent from the data is a GAP ----- //
{
  const admin1 = { regions: {
    "FR-IDF": { a2: "FR", name: "Île-de-France", key: "iso3166-2", osm: 8649, rings: [[[2, 48], [3, 48], [3, 49], [2, 48]]] },
    "FR-BRE": { a2: "FR", name: "Bretagne", key: "iso3166-2", osm: 102740, rings: [[[-4, 48], [-3, 48], [-3, 49], [-4, 48]]] },
    "r999":   { a2: "FR", name: "Sans code", key: "osm-relation", osm: 999, rings: [[[5, 45], [6, 45], [6, 46], [5, 45]]] },
  } };
  const fillFor = (v) => "#fill" + v;
  const vlabel = (k, v) => v + " articles";
  const out = _ooAdmin1Layer(admin1, () => "France", { "FR-IDF": 5, "r999": 0 }, fillFor, vlabel);
  assert.strictEqual(out.shown, 3, "a region was not drawn with the Regions toggle off in region mode");
  const pathFor = (code) => (out.markup.match(new RegExp('<path[^>]*data-oomap-region="' + code + '"[^>]*>')) || [""])[0];
  assert.ok(pathFor("FR-IDF").includes('fill="#fill5"'), "a measured region is not filled by its value: " + pathFor("FR-IDF"));
  assert.ok(pathFor("FR-BRE").includes('fill="url(#oomap-nodata)"'), "an unmeasured region is not the no-data hatch: " + pathFor("FR-BRE"));
  assert.ok(pathFor("FR-BRE").includes("no data"), "the unmeasured region's hover does not say no data");
  assert.ok(!pathFor("FR-BRE").includes("#fill0"), "an unmeasured region was painted as a zero");
  // A REAL zero is a value, not a gap: it takes the scale's colour.
  assert.ok(pathFor("r999").includes('fill="#fill0"'), "a measured zero was drawn as no data: " + pathFor("r999"));
  assert.ok(pathFor("FR-IDF").includes('data-iso="fr"'), "the region lost its country's click");
}

// --- outline mode stays an outline, and honours the toggle -------------------- //
{
  const admin1 = { regions: { "FR-IDF": { a2: "FR", name: "Île-de-France", key: "iso3166-2", osm: 1, rings: [[[2, 48], [3, 48], [3, 49], [2, 48]]] } } };
  const off = _ooAdmin1Layer(admin1, () => "France");
  assert.strictEqual(off.markup, "", "the outline layer drew with the Regions toggle off");
}

console.log("oomap_ranked_table_node_test.js: all assertions passed");
