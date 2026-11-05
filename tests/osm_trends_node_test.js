// The OpenStreetMap trends view's renderers, run as REAL code (v0.6.0 B3a, S06-01 S3).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What this view must NOT do is most of what it is, so most checks below are refusals:
//
//   * the table beside a chart lists EVERY day it was handed -- no truncation, no top-N;
//   * a count of zero is drawn as 0 and a day with no change file is not drawn at all
//     (the server omits it; the view must not invent a row for it);
//   * the tracked window and the planet's prior are two blocks with two tables, never one;
//   * the caveat is VISIBLE (a .card-caveat), the method is on hover;
//   * a country that was never updated, or whose trends could not be read, says so in words,
//     and draws no chart and no row of zeros;
//   * a country is named through the alpha-3 label helper, never printed raw;
//   * a gap in the observation says "Not observed", never a zero;
//   * dates go through ooIsoDate (bidi-isolated under RTL), never a raw slice.
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
function extractConst(name, end) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  const stop = end || ";\n";
  return APP.slice(at, APP.indexOf(stop, at) + stop.length - 1);
}

const FUNCS = ["_osmTrendLabel", "_osmTrendFields", "_osmTrendTable", "_osmTrendBlock", "_osmTrendCountry", "_osmTrendPrior", "_osmTrendDrawAll", "_osmTrendShowTab"];
const src =
  extractConst("esc") + "\n" +
  "var window = {};\n" +
  "var drawn = [];\n" +
  "function ooChart(host, series, opts) { drawn.push({ host, series, opts }); }\n" +
  "function ooIsoDate(s) { return 'D(' + String(s == null ? '' : s).slice(0, 10) + ')'; }\n" +
  "function fmtNum(v) { return String(v); }\n" +
  "function osmCompTf(s, v) { return s.replace(/\\{(\\w+)\\}/g, (_, k) => v[k]); }\n" +
  "function _osmPickLabel(cc, name) { return 'LABEL(' + cc + ')'; }\n" +
  extractConst("OSM_COMP_KEYS", "];\n") + "\n" +
  extractConst("OSM_TREND_TABS", "];\n") + "\n" +
  extractConst("OSM_OPEN_FIELDS", "];\n") + "\n" +
  "var _osmTrends = null, _osmTrendTab = 'adoption', _osmTrendKey = 'opening_hours', _osmTrendNavs = [];\n" +
  "var fakePanels = [];\n" +
  "var document = { querySelectorAll(sel) { return sel.indexOf('panel') !== -1 ? fakePanels : fakeHosts; } };\n" +
  "var fakeHosts = [];\n" +
  FUNCS.map(extract).join("\n") + "\n" +
  "module.exports = { " + FUNCS.join(", ") + ", set(o) { if ('trends' in o) _osmTrends = o.trends; if ('tab' in o) _osmTrendTab = o.tab; if ('key' in o) _osmTrendKey = o.key; if ('hosts' in o) fakeHosts = o.hosts; if ('navs' in o) _osmTrendNavs = o.navs; if ('panels' in o) fakePanels = o.panels; }, tab() { return _osmTrendTab; }, drawn };";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();
const noJunk = (html, what) => {
  for (const bad of ["undefined", "null", "NaN", "[object Object]"]) assert.ok(!visible(html).includes(bad), `${what} drew "${bad}": ${html}`);
};
const KEYS = [{ key: "opening_hours" }, { key: "website" }, { key: "email" }, { key: "phone" }];
const day = (bucket, g, l) => ({ bucket, gained: Object.assign({ opening_hours: 0, website: 0, email: 0, phone: 0 }, g), lost: Object.assign({ opening_hours: 0, website: 0, email: 0, phone: 0 }, l) });
const open = (bucket, o) => Object.assign({ bucket, created: 0, deleted: 0, left_class: 0, disused: 0, vacant: 0, closed: 0 }, o);

const tracked = { since: "2025-01-11T00:00:00+00:00", through: "2025-03-01T00:00:00+00:00", files: 3, days: ["2025-01-11", "2025-01-12", "2025-03-01"], unobserved: [] };
const ok = {
  status: "ok", lane: { alpha3: "ZZZ", name: "Zedland" }, tracked,
  adoption: { keys: KEYS, n: 5, method: "M-adoption <b>", caveat: "C-adoption", series: [day("2025-01-11", { website: 2 }, { phone: 1 }), day("2025-01-12", {}, {}), day("2025-03-01", { opening_hours: 1 }, {})] },
  openings: { fields: ["created", "deleted", "left_class", "disused", "vacant", "closed"], n: 4, method: "M-open", caveat: "C-open", series: [open("2025-01-11", { created: 3 }), open("2025-03-01", { deleted: 1 })] },
  prior: { available: false, reason: "no-history-cut" },
};

// --- 1. the full table, every day, zeros as zeros ------------------------------------------ //
let html = R._osmTrendCountry(ok, 0);
noJunk(html, "ok country");
const rows = (html.match(/<tr>/g) || []).length;
// adoption table: header + 3 days; openings table: header + 2 days (both panels are in the DOM, one hidden)
assert.strictEqual(rows, 4 + 3, "a table lost or invented a row: " + rows);
assert.ok(visible(html).includes("D(2025-01-12) 0 0"), "a day of zero changes (a file WAS applied) must read 0, not vanish");
assert.ok(!visible(html).includes("2025-02"), "a day with no change file got a row");
assert.ok(html.includes("LABEL(ZZZ)"), "the country was not named through the label helper");
assert.ok(!html.includes(">ZZZ<"), "a raw alpha-3 was printed");

assert.ok(visible(html).includes("Change files applied: 3, dated D(2025-01-11) to D(2025-03-01)."), "the window's span was not said through ooIsoDate");

// --- 2. caveat visible, method on hover (escaped) --------------------------------------------- //
assert.ok(html.includes('<div class="card-caveat" style="margin-top:4px">C-adoption</div>'), "the caveat is not visible text");
assert.ok(html.includes('title="M-adoption &lt;b&gt;"'), "the method is not on hover, or not escaped");
assert.ok(!/title="[^"]*C-adoption/.test(html), "the caveat was hidden behind a hover");

// --- 3. the prior is its own block, never added ---------------------------------------------- //
assert.ok(visible(html).includes("Not available: the full-history planet has not been read for this country."));
const withPrior = Object.assign({}, ok, { prior: {
  available: true, method: "M-prior",
  adoption: { keys: KEYS, n: 1, caveat: "C-prior", series: [day("2020-03", { website: 1 }, {})] },
  openings: { fields: ["created", "deleted", "disused", "vacant", "closed"], n: 1, caveat: "C-prior", series: [{ bucket: "2020-05", created: 1, deleted: 0, disused: 0, vacant: 0, closed: 0 }] },
} });
R.set({ tab: "adoption" });
html = R._osmTrendCountry(withPrior, 0);
assert.strictEqual((html.match(/data-osm-trend-month="1"/g) || []).length, 2, "the prior should be one block per kind");
assert.strictEqual((html.match(/data-osm-trend-month="0"/g) || []).length, 2, "the window should be its own blocks");
assert.ok(visible(html).includes("D(2020-03)"), "the prior's month is missing from its table");
assert.ok(html.split("osm-trend-0-prior")[0].indexOf("2020-03") === -1, "the prior leaked into the window's table");
assert.strictEqual((html.match(/class="card-caveat"/g) || []).length, 4, "a block lost its caveat");
assert.ok(html.includes(">C-prior<"), "the planet's block does not show its own caveat");
// the planet's history has no "stopped qualifying": no column, so no zero stands in for it
const priorOpen = html.split('data-osm-trend-panel="openings"')[1].split("osm-trend-0-prior-openings")[1];
assert.ok(!priorOpen.includes("Stopped qualifying"), "the planet's table drew a column it cannot measure");
assert.ok(html.split('data-osm-trend-panel="openings"')[1].split("osm-trend-0-prior-openings")[0].includes("Stopped qualifying"), "the window lost its column");

// --- 4. no files / unreadable / old lane say so and draw nothing -------------------------------- //
for (const [status, words] of [
  ["unreadable", "This country's trends could not be read."],
  ["not-cut", "This country's trends could not be read."],
  ["lane-never-run", "This country's trends could not be read."],
  ["old-lane", "Not available: this lane was cut by an older build and lacks the table."],
]) {
  html = R._osmTrendCountry({ status, lane: { alpha3: "ZZZ", name: "Zedland" } }, 0);
  assert.ok(visible(html).includes(words), status + " did not say so: " + visible(html));
  assert.ok(!html.includes("<table") && !html.includes("data-osm-trend-chart"), status + " drew a table or a chart");
  noJunk(html, status);
}
// A country with no change file yet says so and still offers the planet's past, on BOTH tabs and with the key picker.
html = R._osmTrendCountry({ status: "no-daily-files", lane: { alpha3: "ZZZ", name: "Zedland" }, prior: withPrior.prior }, 0);
assert.ok(visible(html).includes("No daily change file has been applied to this country yet, so there are no trends to show."));
assert.ok(html.includes("data-osm-trend-tabs") && html.includes('data-osm-trend-panel="openings"') && html.includes("data-osm-trend-key"), "the planet's past was left on one view");
assert.strictEqual((html.match(/data-osm-trend-month="0"/g) || []).length, 0, "a window was drawn from no file");
assert.strictEqual((html.match(/data-osm-trend-month="1"/g) || []).length, 2);
noJunk(html, "no-daily-files");

// --- 5. an unobserved stretch is a sentence, never a zero ------------------------------------------ //
const gapped = Object.assign({}, ok, { tracked: Object.assign({}, tracked, { unobserved: [
  { kind: "rebaseline", from_time: "2025-02-01T00:00:00+00:00", to_time: "2025-02-20T00:00:00+00:00" },
  { kind: "hand_recut", from_time: null, to_time: "2025-02-25T00:00:00+00:00" },
  { kind: "other", from_time: "2025-02-26T00:00:00+00:00", to_time: "2025-02-27T00:00:00+00:00" },
] }) });
html = R._osmTrendCountry(gapped, 0);
assert.ok(visible(html).includes("Not observed between D(2025-02-01) and D(2025-02-20): the mirror no longer held the change files, so the country was cut again."));
assert.ok(visible(html).includes("Not observed between Not recorded and D(2025-02-25): the country was cut again by hand."));
assert.ok(visible(html).includes("Not observed between D(2025-02-26) and D(2025-02-27)."), "a gap of an unknown kind was given a cause");

// --- 6. the charts take the picked key, and are given the counts as they are --------------------- //
const host = { getAttribute: (a) => ({ "data-osm-trend-chart": "0", "data-osm-trend-kind": "adoption", "data-osm-trend-month": "0" })[a] };
R.set({ trends: [ok], hosts: [host], key: "website" });
R.drawn.length = 0;
R._osmTrendDrawAll();
assert.strictEqual(R.drawn.length, 1);
const [gained, lost] = R.drawn[0].series;
assert.deepStrictEqual(gained.points.map((p) => p.v), [2, 0, 0]);
assert.deepStrictEqual(lost.points.map((p) => p.v), [0, 0, 0]);
assert.deepStrictEqual(gained.points.map((p) => p.t), ["2025-01-11", "2025-01-12", "2025-03-01"], "the chart's days are the table's days");
assert.strictEqual(R.drawn[0].opts.zeroBase, true, "a count chart must anchor at zero");
// the planet's prior is monthly: the chart gets a first-of-month instant, the table keeps the month
R.drawn.length = 0;
const mhost = { getAttribute: (a) => ({ "data-osm-trend-chart": "0", "data-osm-trend-kind": "adoption", "data-osm-trend-month": "1" })[a] };
R.set({ trends: [withPrior], hosts: [mhost], key: "website" });
R._osmTrendDrawAll();
assert.deepStrictEqual(R.drawn[0].series[0].points, [{ t: "2020-03-01", v: 1 }]);
// a block with no points draws nothing (no empty chart)
R.drawn.length = 0;
R.set({ trends: [Object.assign({}, ok, { adoption: Object.assign({}, ok.adoption, { series: [] }) })], hosts: [host] });
R._osmTrendDrawAll();
assert.strictEqual(R.drawn.length, 0, "an empty block drew a chart");

// a chart in a hidden tab is not drawn (it could not measure its width); showing the tab draws it
const hiddenPanel = { style: { display: "none" }, getAttribute: () => "openings" };
const hhost = { getAttribute: host.getAttribute, closest: () => hiddenPanel };
R.drawn.length = 0;
R.set({ trends: [ok], hosts: [hhost], key: "website" });
R._osmTrendDrawAll();
assert.strictEqual(R.drawn.length, 0, "a chart was drawn in a hidden panel");
hiddenPanel.style.display = "block";
R._osmTrendDrawAll();
assert.strictEqual(R.drawn.length, 1);

// --- 7. switching tabs re-renders nothing: panels toggle, every country's tabs are painted, the visible charts draw --------- //
const painted = [];
const panels = ["adoption", "openings"].map((k) => ({ style: { display: k === "adoption" ? "block" : "none" }, getAttribute: () => k }));
R.set({ navs: [{ paint: (k) => painted.push("a:" + k) }, { paint: (k) => painted.push("b:" + k) }, null], panels, hosts: [] });
R._osmTrendShowTab("openings");
assert.strictEqual(R.tab(), "openings");
assert.deepStrictEqual(panels.map((p) => p.style.display), ["none", "block"]);
assert.deepStrictEqual(painted, ["a:openings", "b:openings"], "another country's tabs disagree with the one shown");

console.log("osm trends: all checks passed");
