// Q803 (0.5 row L): the maps open on OpenStreetMap's border convention, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What is pinned here is the DEFAULT and its refusals, none of which a diff shows:
//   * with the OSM country file, a map that was never told otherwise opens on OSM's
//     convention (the ruling);
//   * without it -- or with one that is undated, or that predates `held_by` -- it opens
//     on "contested", which assigns nothing: Natural Earth's de-facto policy is not OSM's,
//     and calling it OSM's would be the silent pick the same ruling forbids;
//   * the operator's own choice always wins, and a saved "osm" on an install without the
//     file falls back instead of drawing nothing;
//   * under OSM's convention every contested area is still hatched with every claim, and
//     an area inside no country's border, or inside several, is attributed to NO ONE.
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
function constLine(prefix) {
  const at = APP.indexOf(prefix);
  assert.ok(at !== -1, prefix + " not found");
  return APP.slice(at, APP.indexOf("\n", at));
}

const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "var window = {};\n" +
  "var _ooMapOsmAdmin = { admin0: { vintage: '2026-09-01' } };\n" +
  "var _OO_POV_REGION = { ko: 'kr' };\n" +
  "function ooRegionName(c){ return ({fr:'France', de:'Germany'})[String(c).toLowerCase()] || String(c).toUpperCase(); }\n" +
  "function ooCountryCode(c){ return String(c).toUpperCase(); }\n" +
  "function ooCountryName(c){ return ''; }\n" +
  "function ooCountryCompare(a,b){ return String(a).localeCompare(String(b)); }\n" +
  "function _ooMapPath(rings){ return (rings && rings.length) ? 'M0 0Z' : ''; }\n" +
  constLine("const OOMAP_WORLDVIEW_DEFAULT = ") + "\n" +
  constLine("const OOMAP_WORLDVIEW_OSM = ") + "\n" +
  extract("ooLabelText") + "\n" +
  extract("_ooDisputedName") + "\n" +
  extract("_ooOsmConvention") + "\n" +
  extract("_ooEffectiveWorldview") + "\n" +
  extract("_ooWorldviewLabel") + "\n" +
  extract("_ooWorldviewOrder") + "\n" +
  extract("_ooOsmContestedLayer") + "\n" +
  "module.exports = { _ooOsmConvention, _ooEffectiveWorldview, _ooWorldviewLabel, _ooWorldviewOrder, _ooOsmContestedLayer, OOMAP_WORLDVIEW_DEFAULT };";
const F = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const sq = [[[1, 1], [2, 1], [2, 2], [1, 1]]];
const admin0 = {
  vintage: "2026-09-01",
  contested: [
    { id: "r1", name: "Held once", claims: [{ code: "FR", a2: "fr" }, { code: "DE", a2: "de" }], complete: true,
      held_by: [{ a2: "fr", a3: "FRA" }], rings: sq },
    { id: "r2", name: "Held twice", claims: [{ code: "FR", a2: "fr" }, { code: "DE", a2: "de" }], complete: true,
      held_by: [{ a2: "de", a3: "DEU" }, { a2: "fr", a3: "FRA" }], rings: sq },
    { id: "r3", name: "Held by none", claims: [{ code: "FR", a2: "fr" }], complete: false, held_by: [], rings: sq },
  ],
};

// --- THE DEFAULT ----------------------------------------------------------- //
{
  const conv = F._ooOsmConvention(admin0);
  assert.ok(conv && conv.vintage === "2026-09-01", "a dated OSM file with held_by is not recognised");
  assert.strictEqual(F._ooEffectiveWorldview(null, conv), "osm", "the map does not open on OSM's convention");
  assert.strictEqual(F.OOMAP_WORLDVIEW_DEFAULT, "contested");
  // Without the file, the default assigns nothing.
  assert.strictEqual(F._ooEffectiveWorldview(null, null), "contested");
  for (const bad of [null, false, {}, { vintage: "2026-09-01" }, { contested: [] },
                     { vintage: "someday", contested: [] },
                     { vintage: "2026-09-01", contested: [{ id: "x", claims: [], rings: sq }] }]) {
    assert.strictEqual(F._ooOsmConvention(bad), null, "treated as OSM's convention: " + JSON.stringify(bad));
    assert.strictEqual(F._ooEffectiveWorldview(null, F._ooOsmConvention(bad)), "contested");
  }
  // The operator's choice wins; a saved "osm" without the file falls back.
  assert.strictEqual(F._ooEffectiveWorldview("contested", conv), "contested");
  assert.strictEqual(F._ooEffectiveWorldview("in", conv), "in");
  assert.strictEqual(F._ooEffectiveWorldview("osm", null), "contested");
}

// --- the picker: OSM's convention leads, with its date ---------------------- //
{
  assert.deepStrictEqual(F._ooWorldviewOrder(["iso", "tlc", "de"], true), ["osm", "contested", "iso", "tlc", "de"]);
  assert.deepStrictEqual(F._ooWorldviewOrder(["iso", "tlc", "de"]), ["contested", "iso", "tlc", "de"],
    "OSM's convention was offered without the file");
  assert.strictEqual(F._ooWorldviewLabel("osm"), "OpenStreetMap's convention, as of 2026-09-01");
}

// --- the layer: every claim, and no silent pick ------------------------------ //
{
  const fillFor = (v) => "#f" + v;
  const out = F._ooOsmContestedLayer(F._ooOsmConvention(admin0), fillFor, { fr: 7, de: 3 });
  assert.strictEqual(out.shown, 3, "a contested area was dropped");
  const path = (id) => (out.markup.match(new RegExp('<path[^>]*data-oomap-disputed="' + id + '"[^>]*>')) || [""])[0];
  for (const id of ["r1", "r2", "r3"]) {
    assert.ok(path(id).includes('fill="url(#oomap-contested)"'), id + " is not hatched as contested");
    assert.ok(path(id).includes('data-oomap-convention="osm"'), id);
  }
  // Held by exactly one: that country's fill beneath and its click.
  assert.ok(path("r1").includes('data-iso="fr"'), "the held area lost its country's click");
  assert.ok(out.markup.includes('fill="#f7" stroke="none"'), "the held area is not drawn in its country's fill");
  assert.ok(path("r1").includes("France / Germany"), "a claim is missing from the hover: " + path("r1"));
  // Held by several, or none: attributed to NO ONE -- no click, no fill.
  assert.ok(!path("r2").includes("data-iso="), "an area inside two borders was given to one of them");
  assert.ok(path("r2").includes("inside several countries"), path("r2"));
  assert.ok(!path("r3").includes("data-iso="), "an area inside no border was given to someone");
  assert.ok(path("r3").includes("inside no country"), path("r3"));
  assert.ok(path("r3").includes("OpenStreetMap names only one party"), "the single-party claim is not marked");
  assert.ok(!out.markup.includes('fill="#f3"'), "Germany's fill was painted under an area OSM does not give it");
  assert.deepStrictEqual(F._ooOsmContestedLayer(null, fillFor, {}), { markup: "", shown: 0 });
}

console.log("oomap_osm_convention_node_test.js: all assertions passed");
