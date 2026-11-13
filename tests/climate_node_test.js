// The Climate tab's renderers, run as REAL code (R661, R662; 0.6 gate row A).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Most checks are refusals, because what this view must NOT do is most of what it is:
//
//   * a value from the server is text, never markup (a refused line from a publisher's
//     file is quoted back verbatim, and that file is not ours);
//   * a fetch that never happened reads "never fetched on this machine", never a date;
//   * a count the record does not carry is not printed as zero;
//   * a gap is counted as a gap, never as a value;
//   * no verdict words ("stale", "healthy", "risk score"...) anywhere;
//   * every dataset has a visible caveat and a method for the hover.
//
// EXTRACTED from the shipped modules rather than re-typed: a re-typed copy would pass
// while the real renderer was broken.

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
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}

const CLIMATE = [
  "climateText", "climateParamLabel", "climateSeriesLabel", "climateUnitLabel", "_climateWhen", "_climateFact",
  "climateFactsHtml", "climateDiagnosticsHtml", "climateSeriesNote", "climateStationOk",
  "climatePlaceDefaults", "climatePlaceRound", "climatePlaceProblem", "climatePlaceVarLabel", "climatePlaceResultHtml",
];
const src =
  extractConst("esc") + "\n" + extractConst("_LTR_ISOLATE") + "\n" + extract("_ltrIsolate") + "\n" +
  extract("fmtNum") + "\n" + extract("ooIsoDateTime") + "\n" + extract("ooLabelText") + "\n" +
  "var window = {};\nvar document = { documentElement: { dir: \"ltr\" } };\n" +
  CLIMATE.map(extract).join("\n") + "\n" +
  "module.exports = {" + CLIMATE.join(", ") + "};";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"")
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/[⁨⁩]/g, "").replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();
const noJunk = (html, what) => {
  for (const bad of ["undefined", "null", "NaN", "[object Object]"]) assert.ok(!visible(html).includes(bad), what + " shows " + bad + ": " + visible(html));
};
const VERDICTS = /\b(stale|outdated|healthy|unhealthy|risk score|danger|alarming|good|bad)\b/i;

const IDS = ["gistemp", "nsidc", "oni", "usgs", "owid", "ghcnd"];

// Every dataset carries a title, a description, a VISIBLE caveat and a method.
for (const id of IDS) {
  const x = R.climateText(id, t);
  for (const k of ["title", "desc", "caveat", "method"]) assert.ok(x[k] && x[k].length > 20, id + " lacks " + k);
  assert.ok(!VERDICTS.test(x.caveat + x.desc), id + " carries a verdict word");
}

const unit = (over) => Object.assign({
  dataset: "gistemp", param: "GLB", host: "data.giss.nasa.gov",
  source_page: "https://data.giss.nasa.gov/gistemp/", licence: "NASA GISS, public domain",
  documented_as_of: "2026-11", stored: { stored_rows: 0, vintages: 0 }, last_fetch: null,
}, over || {});

// Never fetched: says so, and invents no date or count.
{
  const h = R.climateFactsHtml(unit(), t, tf);
  assert.ok(visible(h).includes("never fetched on this machine"), visible(h));
  assert.ok(!visible(h).includes("Stored"), "no stored line for nothing stored");
  const link = /<a\b[^>]*>([\s\S]*?)<\/a>/.exec(h);
  assert.ok(link, "the source page is a link");
  assert.strictEqual(visible(link[1]), unit().source_page, "the link's visible text is the full URL (#6)");
  assert.ok(visible(h).includes("NASA GISS, public domain"), "the licence is named");
  noJunk(h, "never fetched");
}

// Fetched: the time in UTC, the stored count, and the tally of the last fetch.
{
  const h = R.climateFactsHtml(unit({
    stored: { stored_rows: 4321, vintages: 2, newest_vintage: "2026-11-02T10:00:00+00:00" },
    last_fetch: { fetched_at: "2026-11-02T10:00:00+00:00", tally: { new: 0, revised: 3, unchanged: 1700, gaps: 2, withdrawn: 0 }, diagnostics: {} },
  }), t, tf);
  const v = visible(h);
  assert.ok(v.includes("2026-11-02 10:00 UTC"), v);
  assert.ok(v.includes("4 321 values from 2 fetches"), v);
  assert.ok(v.includes("0 new, 3 revised, 1 700 unchanged values; 2 published gaps"), v);
  assert.ok(!v.includes("no longer in the publisher's file"), "zero withdrawn is not a line");
  noJunk(h, "fetched");
  assert.ok(!VERDICTS.test(v), "a verdict word in " + v);
}

// Restored elsewhere: figures stored, no fetch record on this machine -- said, not invented.
{
  const v = visible(R.climateFactsHtml(unit({ stored: { stored_rows: 10, vintages: 1, newest_vintage: "2026-10-01T00:00:00+00:00" } }), t, tf));
  assert.ok(v.includes("not recorded on this machine; newest stored values from 2026-10-01 00:00 UTC"), v);
}

// A value from the publisher's file is TEXT: markup in it is escaped, never rendered.
{
  const h = R.climateFactsHtml(unit({
    licence: "<img src=x onerror=alert(1)>", source_page: "https://x.example/\"><script>",
    last_fetch: { fetched_at: "2026-11-02T10:00:00+00:00", tally: {}, diagnostics: { columns_missing: ["<b>co2</b>"] } },
  }), t, tf);
  assert.ok(!h.includes("<img") && !h.includes("<script>") && !h.includes("<b>co2"), "unescaped markup: " + h);
}

// Diagnostics: each count only when the record carries it; withdrawn periods are said as kept.
{
  const h = R.climateDiagnosticsHtml(unit({ last_fetch: { tally: { new: 5, withdrawn: 2 }, diagnostics: {
    refused_total: 3, coverage_gap_days: 7, excluded_non_earthquake: 4, unreviewed: 9, quality_flagged_total: 11, trace_days: 1,
  } } }), t, tf);
  const v = visible(h);
  for (const s of ["2 stored periods are no longer in the publisher's file; they are kept, not deleted.",
    "3 lines refused by the parser", "7 days with part of the pole not observed.", "4 events that were not earthquakes",
    "9 counted events are not reviewed yet", "11 days failed NOAA's quality checks", "1 days of trace precipitation"]) {
    assert.ok(v.includes(s), "missing: " + s + " in " + v);
  }
  const quiet = visible(R.climateDiagnosticsHtml(unit({ last_fetch: { tally: { new: 1 }, diagnostics: { unreviewed: null } } }), t, tf));
  assert.ok(!/refused|pole|earthquakes|reviewed|quality/.test(quiet), "a count not carried is not printed: " + quiet);
  assert.strictEqual(R.climateDiagnosticsHtml(unit(), t, tf), "", "no record, no diagnostics");
}

// The n line: values and gaps are separate counts, and a revision is named.
{
  const s = R.climateSeriesNote({ points: [{ t: "1950-01-15", v: 1 }, { t: "1950-02-15", v: null }], n: 1, gaps: 1, first: "1950-DJF", last: "1950-JFM", periods_with_several_vintages: 1 }, t, tf);
  assert.ok(s.includes("n = 1 values, 1 gaps, from 1950-DJF to 1950-JFM"), s);
  assert.ok(s.includes("1 periods revised by the publisher (latest value shown)"), s);
  assert.strictEqual(R.climateSeriesNote({ points: [] }, t, tf), "Nothing stored for this series yet.");
}

// Station ids: the shape the server checks, so a typo never reaches the consent popup.
for (const ok of ["USW00094728", "usw00094728", " ASN00086071 "]) assert.ok(R.climateStationOk(ok), ok);
for (const bad of ["", "USW0009472", "USW000947288", "../etc/pass", "1SW00094728", "USW0009472!"]) assert.ok(!R.climateStationOk(bad), bad);

// Units read as a reader expects; an unknown one is shown as the publisher wrote it.
assert.strictEqual(R.climateUnitLabel("degC", t), "°C");
assert.strictEqual(R.climateUnitLabel("Mkm2", t), "million km²");
assert.strictEqual(R.climateUnitLabel("Mt CO2", t), "Mt CO2");

// Every charted series has words of its own, never its machine id.
for (const sid of ["gistemp.monthly", "gistemp.annual_jd", "nsidc.sea_ice_extent_daily", "oni.anom", "ghcnd.TMAX", "ghcnd.PRCP",
  "co2.co2", "co2.total_ghg", "energy.renewables_share_elec", "usgs.quakes.count.m6.0", "usgs.quakes.max_mag.m6.0"]) {
  assert.notStrictEqual(R.climateSeriesLabel(sid, t), sid, "no label for " + sid);
}
assert.strictEqual(R.climateParamLabel("gistemp", "NH", t), "Northern hemisphere");
assert.strictEqual(R.climateParamLabel("nsidc", "S", t), "Antarctic");


// ---- Your place (R675) ----
// The browser rounds exactly as the server does, so the consent popup names what is sent.
assert.strictEqual(R.climatePlaceRound("48.85661"), 48.9);
assert.strictEqual(R.climatePlaceRound(2.35222), 2.4);
assert.ok(Object.is(R.climatePlaceRound(-0.04), 0), "no -0 in the popup");
// The window ends a week ago and spans 30 days, from today's UTC date.
assert.deepStrictEqual(R.climatePlaceDefaults(new Date(Date.UTC(2026, 10, 13, 23, 0))), {start: "2026-10-08", end: "2026-11-06"});
// Every query the server would refuse is refused here in words, before any popup.
const today = new Date(Date.UTC(2026, 10, 13));
const okQ = {lat: "48.85", lon: "2.35", start: "2026-10-01", end: "2026-10-30"};
assert.strictEqual(R.climatePlaceProblem(okQ, today, t), "");
for (const [over, word] of [[{lat: ""}, "latitude"], [{lat: "abc"}, "latitude"], [{lat: "91"}, "Latitude"], [{lon: "-181"}, "Longitude"],
  [{end: "2026-09-01"}, "before"], [{start: "2024-01-01"}, "366"], [{start: "1939-12-31", end: "1940-01-05"}, "1940"], [{end: "2026-11-20"}, "past"], [{start: "x"}, "first"]]) {
  const why = R.climatePlaceProblem(Object.assign({}, okQ, over), today, t);
  assert.ok(why && why.includes(word), JSON.stringify(over) + " -> " + why);
}
// The result: units, a sign, the years used, a missing value said with its reason, markup escaped, no verdict word.
{
  const d = {results: [
    {variable: "temperature_2m_max", kind: "mean", unit: "°C", value: 1.24, window_value: 21.3, baseline_value: 20.06, years_used: 29, years_excluded: 1},
    {variable: "precipitation_sum", kind: "sum", unit: "mm", value: 140, window_value: 70, baseline_value: 50, years_used: 30, years_excluded: 0},
    {variable: "temperature_2m_min", value: null, reason: "<b>2 of 3 window days have no value</b>"},
  ], license: "Open-Meteo open data, CC BY 4.0", provenance: {window: {fetched_at: "2026-11-13T10:00:00+00:00"}, baseline: {}}};
  const h = R.climatePlaceResultHtml(d, t, tf), v = visible(h);
  assert.ok(v.includes("+1.2 °C") && v.includes("140% of the average") && v.includes("29 of 30 years used") && v.includes("1 excluded for a missing day"), v);
  assert.ok(v.includes("Not computed") && v.includes("2 of 3 window days have no value") && !h.includes("<b>2 of 3"), "a reason is text: " + h);
  assert.ok(v.includes("2026-11-13 10:00 UTC") && v.includes("not recorded"), "fetch times as recorded, never invented: " + v);
  assert.ok(v.includes("CC BY 4.0"), "the licence is named");
  assert.ok(!VERDICTS.test(v), "a verdict word in " + v);
  noJunk(h, "place result");
  assert.ok(visible(R.climatePlaceResultHtml(Object.assign({}, d, {kept: false}), t, tf)).includes("could not be kept"), "an unkept result says so");
  assert.ok(!v.includes("could not be kept"), "a kept result does not");
  assert.ok(visible(R.climatePlaceResultHtml(Object.assign({}, d, {results: [Object.assign({}, d.results[0], {window_in_baseline_period: true})]}), t, tf)).includes("part of the average"));
}
assert.strictEqual(R.climatePlaceResultHtml(null, t, tf), "");

console.log("climate renderers: all checks passed");
