// The OpenStreetMap brands / contact channels / freshness view, run as REAL code (v0.6.0 B3b, S06-01 S3).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What this view must NOT do is most of what it is, so most checks below are refusals:
//
//   * a ranking lists EVERY row it was handed and says "N of M shown"; "Show more" exists only while there is more to show
//     and the server's cap has not been reached;
//   * an operator is its own row, never folded into a brand; a social service is named as its own (untranslated) name;
//   * a zero is drawn as 0 (the mix shows all five buckets); an unknown share is a dash, never 0 %;
//   * a lane with no date to measure ages from says so and draws NO age table (no invented age);
//   * the three sources -- now, the daily change files, the planet's past -- are three blocks, never one;
//   * the caveat is VISIBLE, the method is on hover;
//   * one listener per host: the bodies are rewritten as reads arrive, so nothing is bound inside them;
//   * a read that finishes after a newer load began is discarded;
//   * dates go through ooIsoDate, a country through the label helper.
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
  "_osmCompShare", "_osmTrendTable", "_osmTrendLead", "_osmProfileCacheKey", "_osmProfileShare", "_osmProfileLabel", "_osmProfileSnapBrands", "_osmProfileSnapChannels",
  "_osmProfileSnapFreshness", "_osmPriorSource", "_osmProfileBlock", "_osmProfilePicker", "_osmProfileBody", "_osmProfileDraw", "_osmProfileFill", "_osmProfileShowTab",
  "_renderOsmProfile", "_osmProfileFetch", "loadOsmProfile",
];
const src =
  extractConst("esc") + "\n" +
  "var window = {};\n" +
  "var drawn = [], apiCalls = [], apiAnswer = (u) => ({ status: 'ok' }), els = {};\n" +
  "function $(id) { return els[id]; }\n" +
  "async function api(u) { apiCalls.push(u); return apiAnswer(u); }\n" +
  "function ooChart(host, series, opts) { drawn.push({ host, series, opts }); }\n" +
  "var subtabs = [];\n" +
  "function ooSubtabs(nav, cb) { const h = { nav, cb, painted: [], paint(k) { h.painted.push(k); } }; subtabs.push(h); return h; }\n" +
  "function ooIsoDate(s) { return 'D(' + String(s == null ? '' : s).slice(0, 10) + ')'; }\n" +
  "function fmtNum(v) { return String(v); }\n" +
  "function osmCompTf(s, v) { return s.replace(/\\{(\\w+)\\}/g, (_, k) => v[k]); }\n" +
  "function _osmPickLabel(cc, name) { return 'LABEL(' + cc + ')'; }\n" +
  "var priorAsks = [];\n" +
  "function _osmPriorEnsure(a3, prior) { priorAsks.push(a3); }   // the request for a summary has its own test (osm_prior_summary_node_test.js)\n" +
  extractConst("OSM_COMP_KEYS", "];\n") + "\n" +
  extractConst("OSM_PROFILE_TABS", "];\n") + "\n" +
  extractConst("OSM_SOCIAL_NAMES", "};\n") + "\n" +
  extractConst("OSM_AGE_LABELS", "];\n") + "\n" +
  extractConst("OSM_FRESH_FIELDS", "];\n") + "\n" +
  "const OSM_PROFILE_MAX = 2000;\n" +
  "var _osmProfileDone = [], _osmProfileCache = {}, _osmProfileTab = 'brands', _osmProfileKeys = { brands: 'brand', channels: 'facebook' };\n" +
  "var _osmProfileLimit = 100, _osmProfileSeq = 0, _osmProfileNavs = [], _osmProfileFlight = {};\n" +
  "var bodies = {}, chartHosts = [];\n" +
  "var document = { querySelector(sel) { const m = /data-osm-profile-body=\"(\\d+)\"/.exec(sel); return m ? (bodies[m[1]] = bodies[m[1]] || { innerHTML: '' }) : null; },\n" +
  "  querySelectorAll(sel) { return chartHosts.filter((h) => sel.indexOf('=\"' + h.idx + '\"') !== -1); } };\n" +
  FUNCS.map(extract).join("\n") + "\n" +
  "module.exports = { " + FUNCS.join(", ") + ", drawn, apiCalls, subtabs, bodies, els,\n" +
  "  set(o) { if ('done' in o) _osmProfileDone = o.done; if ('cache' in o) _osmProfileCache = o.cache; if ('tab' in o) _osmProfileTab = o.tab; if ('keys' in o) _osmProfileKeys = o.keys;\n" +
  "    if ('limit' in o) _osmProfileLimit = o.limit; if ('seq' in o) _osmProfileSeq = o.seq; if ('navs' in o) _osmProfileNavs = o.navs; if ('hosts' in o) chartHosts = o.hosts; if ('answer' in o) apiAnswer = o.answer; },\n" +
  "  get() { return { tab: _osmProfileTab, keys: _osmProfileKeys, limit: _osmProfileLimit, seq: _osmProfileSeq, cache: _osmProfileCache }; } };";
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
const LANE = { alpha3: "ZZZ", name: "Zedland" };
const tracked = { since: "2025-01-11T00:00:00+00:00", through: "2025-01-12T00:00:00+00:00", files: 2, days: ["2025-01-11", "2025-01-12"], unobserved: [] };
const vintage = { extract: "2025-01-10T00:00:00+00:00", last_diff: "2025-01-12T00:00:00+00:00", reference: "2025-01-12T00:00:00+00:00" };
const zero = (keys, extra) => Object.assign(Object.fromEntries(keys.map((k) => [k, 0])), extra || {});
const BK = ["brand", "brand:wikidata", "operator", "operator:wikidata"];
const brandsData = (over) => Object.assign({
  status: "ok", vintage,
  snapshot: {
    n: 5, limit: 100, method: "M-snap <b>", caveat: "C-snap",
    tags: [
      { key: "brand", present: 3, share: 0.6, group: "brand" }, { key: "brand:wikidata", present: 2, share: 0.4, group: "brand" },
      { key: "operator", present: 1, share: 0.2, group: "operator" }, { key: "operator:wikidata", present: 0, share: 0, group: "operator" },
    ],
    rankings: [
      { key: "brand", total: 3, shown: 3, rows: [{ value: "Acme", places: 2 }, { value: "acme", places: 1 }, { value: "Zed & Co", places: 1 }] },
      { key: "brand:wikidata", total: 1, shown: 1, rows: [{ value: "Q1", places: 2 }] },
    ],
  },
  changes: { status: "ok", tracked, keys: BK.map((k) => ({ key: k, reads: [k] })), n: 3, method: "M-changes", caveat: "C-changes",
    series: [{ bucket: "2025-01-11", gained: zero(BK, { brand: 2, operator: 1 }), lost: zero(BK) }, { bucket: "2025-01-12", gained: zero(BK), lost: zero(BK) }] },
  prior: { available: false, reason: "no-history-cut" },
}, over || {});
const load = (tab, data, lane) => {
  R.set({ done: [lane || LANE], tab, cache: { [R._osmProfileCacheKey((lane || LANE).alpha3, tab)]: data } });
  return R._osmProfileBody(0);
};

// --- 1. brands: every row, the count of how many, the operator apart ------------------------------------- //
R.set({ limit: 100 });
let html = load("brands", brandsData());
noJunk(html, "brands");
assert.ok(visible(html).includes("Acme 2") && visible(html).includes("acme 1") && visible(html).includes("Zed & Co 1"), "a ranked brand row was lost: " + visible(html));
assert.ok(visible(html).includes("3 of 3 shown.") && visible(html).includes("1 of 1 shown."), "the ranking did not say how many it shows");
assert.ok(!html.includes("data-osm-profile-more"), "Show more offered with nothing more to show");
assert.ok(visible(html).includes("operator 1 20 %") && visible(html).includes("operator:wikidata 0 0 %"), "an operator was folded into a brand, or a zero share was hidden: " + visible(html));
assert.ok(visible(html).includes("brand 3 60 %"));
// a long ranking is complete in the DOM: 500 rows in, 500 rows out
const many = brandsData();
many.snapshot.rankings[0] = { key: "brand", total: 900, shown: 500, rows: Array.from({ length: 500 }, (_, i) => ({ value: "B" + i, places: 500 - i })) };
html = load("brands", many);
const brandTable = html.split("Brands, by number of places")[1].split("Brand identifiers")[0];
assert.strictEqual((brandTable.match(/<tr>/g) || []).length, 501, "the ranking was truncated or padded");
assert.ok(visible(html).includes("500 of 900 shown.") && html.includes("data-osm-profile-more"), "more exists and was not offered");
R.set({ limit: 2000 });
many.snapshot.limit = 2000;
html = load("brands", many);
assert.ok(!html.includes("data-osm-profile-more"), "Show more offered past the server's cap, where it could only ask for the same thing");
R.set({ limit: 100 });

// --- 2. the three sources are three blocks; caveat visible, method on hover ------------------------------------ //
html = load("brands", brandsData());
assert.ok(html.includes('<div class="card-caveat" style="margin-top:4px">C-snap</div>'), "the caveat is not visible text");
assert.ok(html.includes('title="M-snap &lt;b&gt;"') && !/title="[^"]*C-snap/.test(html), "the method is not on hover, or the caveat was hidden behind one");
assert.ok(html.includes('data-osm-profile-month="0"') && !html.includes('data-osm-profile-month="1"'), "the window is one block and there is no prior to draw");
assert.ok(visible(html).includes("Counted from the extract of D(2025-01-10), with change files applied through D(2025-01-12)."), "the vintage was not stated: " + visible(html));
assert.ok(visible(html).includes("Change files applied: 2, dated D(2025-01-11) to D(2025-01-12)."));
assert.ok(visible(html).includes("Not available: the full-history planet has not been read for this country."));
const changesTable = html.split("What the daily change files changed")[1];
assert.ok(visible(changesTable).includes("D(2025-01-12) 0 0 0 0 0 0 0 0"), "a day with a file and no change must read 0, not vanish");
assert.ok(!visible(changesTable).includes("D(2025-01-13)"), "a day with no file got a row");
const withPrior = brandsData({ prior: { available: true, bucket: "month", method: "M-prior", caveat: "C-prior", keys: BK.map((k) => ({ key: k, reads: [k] })), n: 1, series: [{ bucket: "2020-03", gained: zero(BK, { brand: 1 }), lost: zero(BK) }] } });
html = load("brands", withPrior);
assert.strictEqual((html.match(/data-osm-profile-month="1"/g) || []).length, 1, "the planet's past should be one block of its own");
assert.ok(visible(html).includes("D(2020-03)") && html.split("osm-profile-0-prior")[0].indexOf("2020-03") === -1, "the prior leaked into the window");
assert.ok(html.includes(">C-prior<"), "the planet's block lost its caveat");
// no change file yet: the snapshot and the past stay, and no window is drawn from nothing
html = load("brands", brandsData({ changes: { status: "no-daily-files" }, prior: withPrior.prior }));
assert.ok(visible(html).includes("No daily change file has been applied to this country yet, so there are no trends to show."));
assert.ok(!html.includes('data-osm-profile-month="0"') && html.includes('data-osm-profile-month="1"') && visible(html).includes("Acme 2"));
html = load("brands", brandsData({ changes: { status: "old-lane", reason: "x", missing: ["osm_tag_changes"] } }));
assert.ok(visible(html).includes("Not available: this lane was cut by an older build and lacks the table.") && !html.includes('data-osm-profile-month="0"'));
html = load("brands", brandsData({ vintage: { extract: null, last_diff: null, reference: null } }));
assert.ok(visible(html).includes("Counted from the extract of Not recorded; no change file has been applied since."), "an unknown extract date was invented");
noJunk(html, "no vintage");

// --- 3. states that say so in words and draw nothing ---------------------------------------------------------- //
R.set({ done: [LANE], tab: "brands", cache: {} });
assert.ok(visible(R._osmProfileBody(0)).includes("Loading…") && !R._osmProfileBody(0).includes("<table"), "a read still in flight drew data");
for (const status of ["unreadable", "not-cut", "lane-never-run", "unknown-surface"]) {
  html = load("brands", { status });
  assert.ok(visible(html).includes("This country's trends could not be read.") && !html.includes("<table") && !html.includes("data-osm-profile-chart"), status + " drew data");
}

// --- 4. channels: all five mix buckets, a dash for an unknown share, services by their own names ---------------- //
const SOC = ["facebook", "instagram", "twitter", "youtube", "tiktok", "linkedin", "telegram", "whatsapp"];
const chan = {
  status: "ok", vintage,
  snapshot: {
    n: 5, method: "M-chan", caveat: "C-chan",
    channels: [{ key: "website", present: 1, share: 0.2 }, { key: "phone", present: 2, share: 0.4 }, { key: "email", present: 2, share: 0.4 }, { key: "social", present: 2, share: 0.4 }],
    social: SOC.map((k, i) => ({ key: k, present: i ? 0 : 1, share: i ? 0 : 0.2 })),
    mix: [{ channels: 0, places: 3, share: 0.6 }, { channels: 1, places: 0, share: 0 }, { channels: 2, places: 0, share: 0 }, { channels: 3, places: 1, share: 0.2 }, { channels: 4, places: 1, share: null }],
  },
  changes: { status: "ok", tracked, keys: SOC.map((k) => ({ key: k, reads: ["contact:" + k] })), n: 2, method: "M-cc", caveat: "C-cc",
    series: [{ bucket: "2025-01-11", gained: zero(SOC, { facebook: 1, twitter: 1 }), lost: zero(SOC) }] },
  prior: { available: false, reason: "history-cut-unfinished" },
};
html = load("channels", chan);
noJunk(html, "channels");
assert.ok(visible(html).includes("Facebook 1 20 %") && visible(html).includes("WhatsApp 0 0 %") && visible(html).includes("YouTube 0 0 %"), "a service lost its own name: " + visible(html));
assert.ok(visible(html).includes("Website 1 20 %") && visible(html).includes("Phone number 2 40 %") && visible(html).includes("E-mail address 2 40 %") && visible(html).includes("Social 2 40 %"));
const mix = html.split("Places by number of channels carried")[1].split("What the daily change files changed")[0];
assert.strictEqual((mix.match(/<tr>/g) || []).length, 6, "the mix lost a bucket (a zero is a bucket)");
assert.ok(visible(mix).includes("4 1 —") && visible(mix).includes("1 0 0 %"), "an unknown share was drawn as a number, or a zero bucket vanished: " + visible(mix));
assert.ok(html.includes("data-osm-profile-key") && html.includes('<option value="facebook" selected>Facebook</option>'), "the picker lacks the service chosen");
assert.ok(visible(html).includes("Not available: the full-history read for this country did not finish."));

// --- 5. freshness: no date to age from -> no age table, no invented age; an unreadable check_date is counted ---- //
const fresh = {
  status: "ok", vintage,
  snapshot: {
    n: 5, age_years: [1, 2, 5], method: "M-fresh", caveat: "C-fresh",
    last_edit: { available: true, no_timestamp: 2, buckets: [{ bucket: "within_1y", places: 1, share: 0.2 }, { bucket: "y1_2", places: 1, share: 0.2 }, { bucket: "y2_5", places: 0, share: 0 }, { bucket: "over_5y", places: 1, share: 0.2 }, { bucket: "after", places: 0, share: 0 }] },
    check_date: { available: true, present: 4, share: 0.8, unreadable: 1,
      buckets: [{ bucket: "within_1y", places: 1, share: 0.2 }, { bucket: "y1_2", places: 0, share: 0 }, { bucket: "y2_5", places: 1, share: 0.2 }, { bucket: "over_5y", places: 0, share: 0 }, { bucket: "after", places: 1, share: 0.2 }] },
  },
  changes: { status: "ok", tracked, fields: ["edited", "checked"], n: 4, method: "M-fc", caveat: "C-fc", series: [{ bucket: "2025-01-11", edited: 3, checked: 1 }] },
  prior: { available: false, reason: "no-history-cut" },
};
html = load("freshness", fresh);
noJunk(html, "freshness");
const lastEdit = html.split("Last edited, counted back from the vintage")[1].split("Carrying a check_date")[0];
assert.ok(visible(lastEdit).includes("Within a year 1 20 %") && visible(lastEdit).includes("More than five years 1 20 %") && visible(lastEdit).includes("No timestamp 2 40 %"), "an edit-age row is wrong: " + visible(lastEdit));
assert.ok(visible(lastEdit).includes("After the vintage 0 0 %"), "an edit dated after the vintage has no row, so it would read as recent");
const cd = html.split("Carrying a check_date")[1].split("What the daily change files changed")[0];
assert.ok(visible(cd).includes("4 of 5 places carry a check_date (80.0 %)") || visible(cd).includes("4 of 5 places carry a check_date (80 %)"), "the count line is wrong: " + visible(cd));
assert.ok(visible(cd).includes("After the vintage 1 20 %") && visible(cd).includes("Not a date 1 20 %"), "the future or unreadable check_dates were dropped");
assert.ok(visible(html).includes("D(2025-01-11) 3 1"), "edited and checked are not the two columns");
const noRef = JSON.parse(JSON.stringify(fresh));
noRef.snapshot.last_edit = { available: false, reason: "no-reference" };
noRef.snapshot.check_date = { available: false, reason: "no-reference", present: 4, share: 0.8 };
html = load("freshness", noRef);
noJunk(html, "no reference");
assert.strictEqual((visible(html).match(/Not available: neither the extract nor a change file states a date to measure the ages from\./g) || []).length, 2, "an unmeasurable age was not said so");
assert.ok(!html.split("Counted now")[1].split("What the daily change files changed")[0].includes("<table"), "an age table was drawn with no date to age from");
assert.ok(visible(html).includes("4 of 5 places carry a check_date"), "the count needs no date; it was hidden with the ages");

// --- 6. the charts take the picked key, two series for freshness, a month as its first day, nothing from nothing ---- //
const mk = (idx, month) => ({ idx, getAttribute: (a) => ({ "data-osm-profile-month": month ? "1" : "0" })[a] });
R.set({ done: [LANE], tab: "brands", keys: { brands: "operator", channels: "facebook" }, cache: { [R._osmProfileCacheKey("ZZZ", "brands")]: withPrior }, hosts: [mk(0, false), mk(0, true)] });
R.drawn.length = 0;
R._osmProfileDraw(0);
assert.strictEqual(R.drawn.length, 2);
const [gained, lost] = R.drawn[0].series;
assert.deepStrictEqual(gained.points, [{ t: "2025-01-11", v: 1 }, { t: "2025-01-12", v: 0 }], "the chart's key or days are not the table's");
assert.deepStrictEqual(lost.points.map((p) => p.v), [0, 0]);
assert.ok(gained.label.startsWith("operator"), "the series is not named for the picked tag");
assert.deepStrictEqual(R.drawn[1].series[0].points, [{ t: "2020-03-01", v: 0 }], "a month was not drawn at its first day (brand picked: operator has no gain)");
assert.strictEqual(R.drawn[0].opts.zeroBase, true, "a count chart must anchor at zero");
R.set({ tab: "freshness", cache: { [R._osmProfileCacheKey("ZZZ", "freshness")]: fresh }, hosts: [mk(0, false)] });
R.drawn.length = 0;
R._osmProfileDraw(0);
assert.deepStrictEqual(R.drawn[0].series.map((s) => s.label), ["Edited", "Checked"]);
assert.deepStrictEqual(R.drawn[0].series.map((s) => s.points[0].v), [3, 1]);
R.set({ cache: { [R._osmProfileCacheKey("ZZZ", "freshness")]: Object.assign({}, fresh, { changes: Object.assign({}, fresh.changes, { series: [] }) }) } });
R.drawn.length = 0;
R._osmProfileDraw(0);
assert.strictEqual(R.drawn.length, 0, "an empty block drew a chart");

// --- 7. fetching: the surface and the limit are asked for, a cached read is not repeated, a stale read is discarded ---- //
(async () => {
  R.set({ done: [LANE, { alpha3: "YYY", name: "Yland" }], tab: "channels", limit: 100, seq: 7, cache: {}, answer: (u) => ({ status: "ok", url: u }) });
  R.apiCalls.length = 0;
  await R._osmProfileFetch(7);
  assert.deepStrictEqual(R.apiCalls, ["/api/osm/countries/ZZZ/profile/channels?limit=100", "/api/osm/countries/YYY/profile/channels?limit=100"]);
  await R._osmProfileFetch(7);
  assert.strictEqual(R.apiCalls.length, 2, "a cached read was asked for again");
  // a read that finishes after a newer load began must not be kept
  R.set({ cache: {}, seq: 7, answer: (u) => { R.set({ seq: 8 }); return { status: "ok" }; } });
  R.apiCalls.length = 0;
  await R._osmProfileFetch(7);
  assert.strictEqual(Object.keys(R.get().cache).length, 0, "a stale read overwrote a newer load");
  // a read already in flight is not asked for again (a tab clicked away and back), and its result still lands on the screen
  R.set({ done: [LANE], tab: "brands", cache: {}, seq: 3, answer: () => ({ status: "ok" }) });
  R.apiCalls.length = 0;
  await Promise.all([R._osmProfileFetch(3), R._osmProfileFetch(3)]);
  assert.strictEqual(R.apiCalls.length, 1, "two loops asked for the same country twice");
  assert.ok(!R.bodies[0].innerHTML.includes("Loading…"), "a skipped read was never drawn");
  // a failed read is a named state, not a hole
  R.set({ done: [LANE, { alpha3: "YYY", name: "Yland" }], tab: "channels", cache: {}, seq: 1, answer: () => { throw new Error("boom"); } });
  await R._osmProfileFetch(1);
  assert.deepStrictEqual(Object.values(R.get().cache).map((d) => d.status), ["unreadable", "unreadable"]);
  // loading with no country hides the section and keeps nothing; with some, shows it and reads the active tab only
  const sec = { hidden: false };
  R.els["osm-profile"] = sec;
  await R.loadOsmProfile([]);
  assert.strictEqual(sec.hidden, true);
  R.els["osm-profile-body"] = { innerHTML: "", _attrs: {}, _listeners: [], querySelectorAll: () => [], getAttribute(a) { return this._attrs[a] || null; }, setAttribute(a, v) { this._attrs[a] = v; }, addEventListener(t) { this._listeners.push(t); } };
  R.set({ answer: () => ({ status: "ok" }), seq: 0, tab: "brands" });
  R.apiCalls.length = 0;
  await R.loadOsmProfile([LANE]);
  assert.strictEqual(sec.hidden, false);
  assert.deepStrictEqual(R.apiCalls, ["/api/osm/countries/ZZZ/profile/brands?limit=100"], "a tab that was not opened was read");
  // two renders, one set of listeners
  R._renderOsmProfile();
  assert.deepStrictEqual(R.els["osm-profile-body"]._listeners, ["change", "click"], "the host was given listeners again (or none)");
  // changing the tab paints every country's tabs, rewrites each body, and reads what is not cached
  const painted = [];
  R.set({ navs: [{ paint: (k) => painted.push("a:" + k) }, { paint: (k) => painted.push("b:" + k) }, null], done: [LANE], cache: {} });
  R.apiCalls.length = 0;
  R._osmProfileShowTab("freshness");
  assert.strictEqual(R.get().tab, "freshness");
  assert.deepStrictEqual(painted, ["a:freshness", "b:freshness"]);
  assert.ok(R.bodies[0].innerHTML.includes("Loading…"), "the body was not rewritten for the new tab");
  await new Promise((r) => setTimeout(r, 0));
  assert.deepStrictEqual(R.apiCalls, ["/api/osm/countries/ZZZ/profile/freshness?limit=100"]);
  console.log("all checks passed");
})().catch((e) => { console.error(e); process.exit(1); });
