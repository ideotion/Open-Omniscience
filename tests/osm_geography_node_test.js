// The OpenStreetMap geography axis (choropleth by country and by admin-1 region), run as REAL code (v0.6.0 B3c, S06-01 S4, Q816 = a).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What this view must NOT do is most of what it is, so most checks below are refusals:
//
//   * an area with no figure is ABSENT from the values handed to the map (ooMap hatches it as «no data») and is explained in words --
//     never a zero: a measure that needs a date the country does not state, a window nobody observed, a split counted before the
//     measure existed, a share of no places;
//   * the share form is raw / n * 100 and is never offered for «all the places» (it would be 100 % everywhere);
//   * by region, «a tag changed in the window» is NOT drawn (a change row has no region) and the page says why;
//   * every map states its vintage -- the extract's date and the newest change file applied -- per country;
//   * the caveat is VISIBLE and the method goes to the map (hover);
//   * a region split that is not complete says so by name and draws no map;
//   * one listener per host; a read that finishes after a newer load began is discarded.
//
// EXTRACTED from the shipped module rather than re-typed.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const asyncAt = APP.lastIndexOf("async ", at);
  const start = asyncAt !== -1 && at - asyncAt === 6 ? asyncAt : at;
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
  return APP.slice(start, j);
}
function extractConst(name, end) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  const stop = end || ";\n";
  return APP.slice(at, APP.indexOf(stop, at) + stop.length - 1);
}

const FUNCS = [
  "loadOsmGeography", "_osmGeogSigOf", "_osmGeogRepaint", "_osmGeogVintage", "_osmGeogShare", "_osmGeogFigures", "_osmAdmin1Label", "_osmGeogDraw", "_renderOsmGeography",
];
const src =
  extractConst("esc") + "\n" +
  "var window = {};\n" +
  "var els = {}, mapCalls = [], apiCalls = [], apiAnswer = () => ({ status: 'unreadable' });\n" +
  "function $(id) { return els[id]; }\n" +
  "async function api(u) { apiCalls.push(u); return apiAnswer(u); }\n" +
  "async function ooMap(host, opts) { mapCalls.push({ host, opts }); }\n" +
  "function ooIsoDate(s) { return 'D(' + String(s == null ? '' : s).slice(0, 10) + ')'; }\n" +
  "function fmtNum(v, d) { return String(Math.round(v * 10) / 10); }\n" +
  "function osmCompTf(s, v) { return s.replace(/\\{(\\w+)\\}/g, (_, k) => v[k]); }\n" +
  "function _osmPickLabel(cc, name) { return 'LABEL(' + cc + ')'; }\n" +
  extractConst("OSM_ADMIN1_SAY", "};\n") + "\n" +
  extractConst("OSM_GEOG_MEASURES", "];\n") + "\n" +
  "var _osmComp = [];\n" +
  "var out = { innerHTML: '', mapHost: {}, querySelector(sel) { return sel === '[data-osm-geog-map]' ? out.mapHost : null; } };\n" +
  "var document = { querySelector(sel) { return sel === '[data-osm-geog-out]' ? out : null; } };\n" +
  "let _osmGeog = null, _osmGeogLevel = 'countries', _osmGeogMeasure = 'places', _osmGeogForm = 'count', _osmGeogSeq = 0;\n" +
  "let _osmGeogDone = [], _osmGeogSig = '';\n" +
  FUNCS.map(extract).join("\n") + "\n" +
  "module.exports = { " + FUNCS.join(", ") + ", mapCalls, apiCalls, els, out,\n" +
  "  set(o) { if ('geog' in o) _osmGeog = o.geog; if ('level' in o) _osmGeogLevel = o.level; if ('measure' in o) _osmGeogMeasure = o.measure; if ('form' in o) _osmGeogForm = o.form;\n" +
  "    if ('comp' in o) _osmComp = o.comp; if ('answer' in o) apiAnswer = o.answer; if ('seq' in o) _osmGeogSeq = o.seq; },\n" +
  "  get() { return { level: _osmGeogLevel, measure: _osmGeogMeasure, form: _osmGeogForm, geog: _osmGeog, seq: _osmGeogSeq }; } };";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();

const GEOG = {
  status: "ok", measures: ["places", "brand", "checked", "edited_1y", "changed"], method: "METHOD", caveat: "CAVEAT", not_cut: [],
  areas: [
    { alpha3: "ZZZ", alpha2: "ZZ", name: "Zedland", n: 5, values: { places: 5, brand: 3, checked: 4, edited_1y: 1, changed: 2 }, reasons: {},
      vintage: { extract: "2025-01-10T00:00:00+00:00", last_diff: "2025-01-12T00:00:00+00:00", reference: "2025-01-12T00:00:00+00:00" } },
    { alpha3: "YYY", alpha2: "YY", name: "Yland", n: 0, values: { places: 0, brand: 0, checked: 0, edited_1y: null, changed: null },
      reasons: { edited_1y: "no-reference", changed: "no-daily-files" },
      vintage: { extract: null, last_diff: null, reference: null } },
  ],
};
const DONE = [{ alpha3: "ZZZ", name: "Zedland", vintage: "2025-01-10T00:00:00+00:00", diff_timestamp: "2025-01-12T00:00:00+00:00" }, { alpha3: "YYY", name: "Yland", vintage: null, diff_timestamp: null }];

function fresh(over) {
  R.mapCalls.length = 0;
  R.out.innerHTML = "";
  R.set(Object.assign({ geog: GEOG, level: "countries", measure: "places", form: "count", comp: [] }, over || {}));
}
const lastMap = () => R.mapCalls[R.mapCalls.length - 1];

(async () => {
  // ---- country level: the values, keyed by alpha-2, are the counts -------------------------------------------------
  fresh();
  await R._osmGeogDraw(DONE);
  let m = lastMap();
  assert.deepStrictEqual(m.opts.values, { zz: 5, yy: 0 }, "a place count of 0 is a real zero and is drawn");
  assert.strictEqual(m.opts.regionValues, undefined, "a country map was handed region values");
  assert.strictEqual(m.opts.method, "METHOD", "the method does not reach the map's hover");
  assert.ok(visible(R.out.innerHTML).includes("CAVEAT"), "the caveat is not visible by default");
  assert.strictEqual(m.opts.valueLabel("zz", 5), "5 places", "the count of all the places is not «N of N»");
  const cav = /<div class="card-caveat"([^>]*)>/.exec(R.out.innerHTML);
  assert.ok(cav && !/hidden|display:\s*none/.test(cav[1]), "the caveat sits behind a hidden attribute or a display:none");

  // ---- the vintage is stated on the map, for every country ----------------------------------------------------------
  const text = visible(R.out.innerHTML);
  assert.ok(text.includes("LABEL(ZZZ): Counted from the extract of D(2025-01-10), with change files applied through D(2025-01-12)."), text);
  assert.ok(text.includes("LABEL(YYY): Counted from the extract of Not recorded; no change file has been applied since."), "a country without a date says so");

  // ---- a measure with no figure is ABSENT, named, and never zero -----------------------------------------------------
  fresh({ measure: "changed" });
  await R._osmGeogDraw(DONE);
  m = lastMap();
  assert.deepStrictEqual(m.opts.values, { zz: 2 }, "a window nobody observed was drawn as a number");
  assert.ok(visible(R.out.innerHTML).includes("LABEL(YYY): No daily change file has been applied to this country yet."));
  fresh({ measure: "edited_1y" });
  await R._osmGeogDraw(DONE);
  assert.deepStrictEqual(lastMap().opts.values, { zz: 1 });
  assert.ok(visible(R.out.innerHTML).includes("LABEL(YYY): Not available: neither the extract nor a change file states a date to measure the ages from."));

  // ---- the share form: raw / n * 100, never for «all the places», a share of no places is no figure ------------------
  fresh({ measure: "brand", form: "share" });
  await R._osmGeogDraw(DONE);
  m = lastMap();
  assert.deepStrictEqual(m.opts.values, { zz: 60 }, "the share is 3 of 5 places");
  assert.ok(visible(R.out.innerHTML).includes("LABEL(YYY): No places were counted here, so there is no share."), "a share of 0 places was drawn as 0 %");
  assert.strictEqual(m.opts.valueLabel("zz", 60), "3 of 5 places (60 %)");
  assert.ok(m.opts.label.includes("Share of the area's places"));
  fresh({ measure: "places", form: "share" });
  await R._osmGeogDraw(DONE);
  assert.deepStrictEqual(lastMap().opts.values, { zz: 5, yy: 0 }, "the share of all the places (always 100 %) was drawn");

  // ---- nothing to draw: no map at all, not an empty one ------------------------------------------------------------
  fresh({ measure: "changed", geog: Object.assign({}, GEOG, { areas: [GEOG.areas[1]] }) });
  await R._osmGeogDraw(DONE);
  assert.strictEqual(R.mapCalls.length, 0, "a map with nothing in it was drawn");

  // ---- a country whose cut did not finish is named, not mapped -----------------------------------------------------
  fresh({ geog: Object.assign({}, GEOG, { not_cut: ["QQQ"] }) });
  await R._osmGeogDraw(DONE);
  assert.ok(visible(R.out.innerHTML).includes("Not drawn, because their cut did not finish: QQQ."));

  // ---- region level -------------------------------------------------------------------------------------------------
  const REG = (over) => Object.assign({ country: "ZZZ", admin1: { status: "complete", regions: [
    { key: "ZZ-W", name: "West", names: { fr: "Ouest" }, n: 2, measures: { brand: 2, checked: 2, edited_1y: 1 } },
    { key: "ZZ-E", name: "East", names: {}, n: 1, measures: { brand: 1, checked: 1, edited_1y: 0 } },
    { key: "ZZ-X", name: "Empty", names: {}, n: 0, measures: { brand: 0, checked: 0, edited_1y: 0 } },
    { key: "ZZ-O", name: "Old", names: {}, n: 3, measures: null },
  ] } }, over || {});
  fresh({ level: "ZZZ", measure: "brand", comp: [REG()] });
  await R._osmGeogDraw(DONE);
  m = lastMap();
  assert.deepStrictEqual(m.opts.regionValues, { "ZZ-W": 2, "ZZ-E": 1, "ZZ-X": 0 }, "regions are keyed by their code; a region counted before the measure existed is absent");
  assert.strictEqual(m.opts.values, undefined, "a region map was handed country values");
  let t2 = visible(R.out.innerHTML);
  assert.ok(t2.includes("Old: Counted before this measure existed: count the regions again to add it."), "an old split read as zeros");
  assert.ok(t2.includes("LABEL(ZZZ): Counted from the extract of D(2025-01-10), with change files applied through D(2025-01-12)."), "the region map has no vintage");
  assert.ok(!t2.includes("Yland"), "another country's vintage was stated on this country's map");

  fresh({ level: "ZZZ", measure: "places", comp: [REG()] });
  await R._osmGeogDraw(DONE);
  assert.deepStrictEqual(lastMap().opts.regionValues, { "ZZ-W": 2, "ZZ-E": 1, "ZZ-X": 0, "ZZ-O": 3 }, "places per region are the split's n");

  fresh({ level: "ZZZ", measure: "brand", form: "share", comp: [REG()] });
  await R._osmGeogDraw(DONE);
  assert.deepStrictEqual(lastMap().opts.regionValues, { "ZZ-W": 100, "ZZ-E": 100 }, "an empty region has no share");
  assert.ok(visible(R.out.innerHTML).includes("Empty: No places were counted here, so there is no share."));

  fresh({ level: "ZZZ", measure: "changed", comp: [REG()] });
  await R._osmGeogDraw(DONE);
  assert.strictEqual(R.mapCalls.length, 0, "a change was attributed to a region");
  assert.ok(visible(R.out.innerHTML).includes("A change row records the country a place was in, not its region, so this measure is drawn by country only."));

  for (const [status, say, btn] of [["not-counted", "Per region: not counted yet.", "Count per region"], ["stale", "Per region: counted from an earlier read", "Count again"],
    ["no-admin1-file", "Per region: the region outlines are not built on this install", null], ["counting", "Per region: counting…", null]]) {
    fresh({ level: "ZZZ", measure: "brand", comp: [REG({ admin1: { status } })] });
    await R._osmGeogDraw(DONE);
    assert.strictEqual(R.mapCalls.length, 0, status + ": a map was drawn from a split that is not complete");
    const html = R.out.innerHTML;
    assert.ok(visible(html).includes(say), status + ": " + visible(html));
    assert.strictEqual(html.includes("osmCountAdmin1("), btn !== null, status + ": the button");
    if (btn) assert.ok(visible(html).includes(btn));
  }
  fresh({ level: "ZZZ", measure: "brand", comp: [REG({ admin1: { status: "weird" } })] });
  await R._osmGeogDraw(DONE);
  assert.ok(visible(R.out.innerHTML).includes("Per region: the count could not be read."), "an unknown status has no sentence");

  // a split counted without a reference date has its measures but no edited_1y: the reason is the country level's, not «Not recorded»
  fresh({ level: "ZZZ", measure: "edited_1y", comp: [REG({ admin1: { status: "complete", regions: [
    { key: "ZZ-W", name: "West", names: {}, n: 2, measures: { brand: 2, checked: 2 } }, { key: "ZZ-E", name: "East", names: {}, n: 1, measures: { brand: 1, checked: 1, edited_1y: 1 } }] } })] });
  await R._osmGeogDraw(DONE);
  assert.deepStrictEqual(lastMap().opts.regionValues, { "ZZ-E": 1 });
  assert.ok(visible(R.out.innerHTML).includes("West: Not available: neither the extract nor a change file states a date to measure the ages from."), visible(R.out.innerHTML));

  // ---- the 2 s count poll: the figures are redrawn only when the level in view has something new, and the controls are left alone ----
  const pHost = { innerHTML: "", attrs: {}, getAttribute(k) { return this.attrs[k] || null; }, setAttribute(k, v) { this.attrs[k] = v; }, addEventListener() {}, querySelector() { return { disabled: false }; } };
  R.els["osm-geography-body"] = pHost;
  const counting = REG({ admin1: { status: "counting" } });
  fresh({ level: "ZZZ", measure: "brand", comp: [counting] });
  R._renderOsmGeography(DONE);
  await new Promise((r) => setTimeout(r, 0));
  const controls = pHost.innerHTML, before = R.mapCalls.length;
  R._osmGeogRepaint(DONE); R._osmGeogRepaint(DONE);
  await new Promise((r) => setTimeout(r, 0));
  assert.strictEqual(pHost.innerHTML, controls, "a poll tick rebuilt the controls (an open dropdown closes)");
  assert.strictEqual(R.mapCalls.length, before, "a poll tick with nothing new redrew the map");
  R.set({ comp: [REG()] });   // the count finished
  R._osmGeogRepaint(DONE);
  await new Promise((r) => setTimeout(r, 0));
  assert.strictEqual(pHost.innerHTML, controls, "the finished count rebuilt the controls");
  assert.deepStrictEqual(lastMap().opts.regionValues, { "ZZ-W": 2, "ZZ-E": 1, "ZZ-X": 0 }, "a finished count did not reach the map");
  assert.strictEqual(R.mapCalls.length, before + 1, "the finished count drew more than once");

  // ---- the shell: levels, one listener, a vanished country, stale loads ----------------------------------------------
  const listeners = [];
  const host = { innerHTML: "", attrs: {}, getAttribute(k) { return this.attrs[k] || null; }, setAttribute(k, v) { this.attrs[k] = v; },
    addEventListener(ev, fn) { listeners.push(ev); }, querySelector() { return { disabled: false }; } };
  R.els["osm-geography-body"] = host;
  fresh({ level: "GONE" });
  R._renderOsmGeography(DONE);
  assert.strictEqual(R.get().level, "countries", "a country that is no longer held stayed selected");
  const html = host.innerHTML;
  assert.ok(html.includes('value="countries" selected'), "the level picker does not offer Countries first");
  assert.ok(html.includes('<option value="ZZZ">Regions of LABEL(ZZZ)</option>') && html.includes('<option value="YYY">Regions of LABEL(YYY)</option>'));
  assert.ok(html.includes('data-osm-geog="form" disabled'), "the share was offered for «all the places»");
  R._renderOsmGeography(DONE);
  assert.deepStrictEqual(listeners, ["change"], "a listener per render, or none");

  R.set({ geog: { status: "unreadable" } });
  R._renderOsmGeography(DONE);
  assert.strictEqual(visible(host.innerHTML), "OpenStreetMap: the view could not be read.", "an unreadable geography drew controls, or named the trends");

  // a read that finishes after a newer load began is discarded
  const sec = { hidden: true };
  R.els["osm-geography"] = sec;
  let release;
  const slow = new Promise((r) => { release = r; });
  R.set({ geog: null, answer: () => slow });
  const older = R.loadOsmGeography(DONE);
  R.set({ answer: () => GEOG });
  await R.loadOsmGeography(DONE);
  assert.strictEqual(R.get().geog.status, "ok");
  release({ status: "ok", areas: [], measures: [], method: "OLD", caveat: "OLD" });
  await older;
  assert.strictEqual(R.get().geog.method, "METHOD", "an older read overwrote a newer one");
  await R.loadOsmGeography([]);
  assert.strictEqual(sec.hidden, true);
  assert.strictEqual(R.get().geog, null, "an empty lane kept its old geography");
  assert.deepStrictEqual(R.apiCalls.filter((u) => !u.endsWith("/api/osm/geography")), [], "the view read something other than its own route");

  console.log("all checks passed");
})().catch((e) => { console.error(e); process.exit(1); });
