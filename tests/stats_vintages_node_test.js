// Statistics: every stored version of one published figure, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// GET /api/stats/figures/vintages had no button (R684): the figures table shows the
// LATEST vintage only, so a value the producer later revised was stored and unreachable.
// Each row now has a "Versions" button. What this pins, by driving the shipped code
// through its own delegated click listener:
//   - the request names the ONE observation the row shows (agency, series, area, period);
//   - the trail is drawn oldest first, with the store's caveat visible beside it (R685);
//   - a change is shown only between two versions on the same unit / adjustment / base
//     year -- across a basis change it is "—", never a difference of two quantities;
//   - a language switch redraws it with no second request; a second click closes it;
//   - a fresh load of the table forgets a trail it may no longer show.
// Every function is EXTRACTED from the shipped modules, never re-typed.

"use strict";

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
function slice(from, to) {
  const a = APP.indexOf(from), b = APP.indexOf(to, a);
  assert.ok(a !== -1 && b !== -1, "could not slice " + from);
  return APP.slice(a, b);
}

const I18N = {
  lang: "fr",
  t(s) { return "«" + I18N.lang + ":" + s + "»"; },
  tf(s, v) { return I18N.t(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)); },
  current() { return "en"; },
};

const BOXES = {};
function $(id) {
  if (!BOXES[id]) {
    BOXES[id] = { id, innerHTML: "", value: "", textContent: "", listeners: [],
      addEventListener(type, fn) { this.listeners.push([type, fn]); } };
  }
  return BOXES[id];
}
// A click on the row's button, delivered the way the browser would: to the box's
// delegated listener, with a target whose closest() finds the button.
function clickVersions(i) {
  const box = $("statfig-table");
  assert.ok(box.innerHTML.includes('data-statvint="' + i + '"'), "no Versions button for row " + i);
  const btn = { dataset: { statvint: String(i) } };
  const target = { closest: (sel) => (sel === "button[data-statvint]" ? btn : null) };
  const clicks = box.listeners.filter(([t]) => t === "click");
  assert.strictEqual(clicks.length, 1, "one delegated listener, wired once");
  clicks[0][1]({ target });
}
let API_CALLS = [];
const API_ANSWERS = {};
async function api(path) {
  API_CALLS.push(path);
  // An EXACT route match: "/api/stats/figures" must not answer "/api/stats/figures/vintages".
  const key = Object.keys(API_ANSWERS).find((k) => path.split("?")[0] === k);
  if (!key) throw new Error("unexpected request " + path);
  return JSON.parse(JSON.stringify(API_ANSWERS[key]));
}
const tick = () => new Promise((r) => setTimeout(r, 0));

const src = [
  "function ooLtrIsolate(s){return String(s==null?'':s);}",
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function ooAreaCell(v){return '<span>' + esc(v) + '</span>';}",
  extract("fmtNum"),
  extract("fmtDateTime"),
  extract("_mapTf"),
  extract("_statfigFmt"),
  extract("_statAreaLocal"),
  slice("let _statFigLast = null", "function _statIso"),
  extract("_statIso"),
  "async " + extract("loadStatFigures"),
  "async " + extract("_statLoadVintages"),
  extract("repaintStatTablesFromCache"),
  "return { loadStatFigures, repaintStatTablesFromCache };",
].join("\n");
const mod = new Function("window", "OOI18N", "$", "api", src)({ OOI18N: I18N }, I18N, $, api);

let n = 0;
async function test(name, fn) { await fn(); n++; console.log("ok  - " + name); }

(async () => {
  API_ANSWERS["/api/stats/figures/vintages"] = {
    agency: "worldbank", series_id: "NY.GDP.MKTP.CD", ref_area: "FRA", time_period: "2023", count: 3,
    vintages: [
      { extracted_at: "2026-03-01T10:00:00", value: 100, unit: "USD", adjustment: "NSA", base_year: null },
      { extracted_at: "2026-06-01T10:00:00", value: 104, unit: "USD", adjustment: "NSA", base_year: null },
      { extracted_at: "2026-09-01T10:00:00", value: 99000, unit: "EUR", adjustment: "NSA", base_year: null },
    ],
    caveat: "Revisions are preserved as evidence; no vintage is treated as the single truth.",
  };
  API_ANSWERS["/api/stats/figures"] = {
    shown: 2, count: 2,
    caveat: "c.",
    figures: [
      { agency: "worldbank", series_id: "NY.GDP.MKTP.CD", ref_area: "DEU", time_period: "2023", value: 7, unit: "USD" },
      { agency: "worldbank", series_id: "NY.GDP.MKTP.CD", ref_area: "FRA", time_period: "2023", value: 99000, unit: "EUR" },
    ],
  };

  await test("each row has a Versions button, closed, through one delegated listener", async () => {
    API_CALLS = [];
    await mod.loadStatFigures();
    const html = $("statfig-table").innerHTML;
    assert.ok(html.includes('data-statvint="0"') && html.includes('data-statvint="1"'), html);
    assert.ok(html.includes('aria-expanded="false"') && !html.includes('aria-expanded="true"'), html);
    assert.ok(!html.includes("data-on-click"), "no inline handler on the new buttons");
    assert.ok(html.includes("«fr:Versions»</th>") && html.includes("«fr:Show»</button>"), "the column and its button are keyed");
    assert.ok(!html.includes("statfig-vint"), "no trail drawn before a click");
    // A second load wires nothing more.
    await mod.loadStatFigures();
    assert.strictEqual($("statfig-table").listeners.length, 1);
  });

  await test("a click asks for THAT row's observation and draws its trail oldest first", async () => {
    API_CALLS = [];
    clickVersions(1);
    assert.ok($("statfig-table").innerHTML.includes("«fr:Loading…»"), "a loading state while it reads");
    await tick();
    assert.deepStrictEqual(API_CALLS, ["/api/stats/figures/vintages?agency=worldbank"
      + "&series_id=NY.GDP.MKTP.CD&ref_area=FRA&time_period=2023"]);
    const html = $("statfig-table").innerHTML;
    const trail = html.slice(html.indexOf("statfig-vint"));
    // ONE keyed frame, its count isolated (R7).
    assert.ok(/«fr:\u20683\u2069 stored versions of NY\.GDP\.MKTP\.CD · FRA · 2023, oldest first»/.test(trail), trail);
    for (const h of ["Stored on", "Value", "Change in value", "Unit", "SA/NSA", "Base yr"]) {
      assert.ok(trail.includes("«fr:" + h + "»"), "header " + h + " not keyed");
    }
    assert.ok(trail.indexOf(">100<") < trail.indexOf(">104<") && trail.indexOf(">104<") < trail.indexOf("99"),
      "the versions are drawn oldest first: " + trail);
    assert.ok(html.includes('data-statvint="1" aria-expanded="true"'), "the open row says so");
    // The caveat sits visibly beside the numbers (R685), keyed.
    assert.ok(trail.includes('<p class="card-caveat"') && trail.includes(
      "«fr:Revisions are preserved as evidence; no vintage is treated as the single truth.»"), trail);
  });

  await test("a change is shown only on the same basis, never across a unit change", () => {
    const html = $("statfig-table").innerHTML;
    const rows = html.slice(html.indexOf("statfig-vint")).split("<tr>").slice(2);   // header, then rows
    assert.strictEqual(rows.length, 3, rows.join("\n"));
    const changeCell = (r) => r.split("</td>")[2];
    assert.ok(/>—$/.test(changeCell(rows[0])), "the first version has nothing before it: " + rows[0]);
    assert.ok(/>4$/.test(changeCell(rows[1])), "100 -> 104 on one basis is a change of 4: " + rows[1]);
    assert.ok(/>—$/.test(changeCell(rows[2])), "USD -> EUR is a different quantity, not a change: " + rows[2]);
  });

  await test("a language switch redraws the trail with no second request", async () => {
    I18N.lang = "ar";
    API_CALLS = [];
    mod.repaintStatTablesFromCache();
    await tick();
    assert.strictEqual(API_CALLS.length, 0, API_CALLS.join(", "));
    const html = $("statfig-table").innerHTML;
    assert.ok(html.includes("«ar:Stored on»") && !html.includes("«fr:"), "the trail kept French");
  });

  await test("a second click closes it, and a fresh load forgets it", async () => {
    API_CALLS = [];
    clickVersions(1);
    await tick();
    assert.strictEqual(API_CALLS.length, 0, "closing must not fetch");
    assert.ok(!$("statfig-table").innerHTML.includes("statfig-vint"));
    clickVersions(0);
    await tick();
    assert.ok($("statfig-table").innerHTML.includes("statfig-vint"));
    await mod.loadStatFigures();
    assert.ok(!$("statfig-table").innerHTML.includes("statfig-vint"), "a fresh load keeps a stale trail");
  });

  await test("a failed read says so in words, and keeps the table", async () => {
    const saved = API_ANSWERS["/api/stats/figures/vintages"];
    delete API_ANSWERS["/api/stats/figures/vintages"];
    clickVersions(0);
    await tick();
    const html = $("statfig-table").innerHTML;
    assert.ok(html.includes("«ar:Could not load the versions: unexpected request"), html);
    assert.ok(html.includes('data-statvint="1"'), "the table itself stays");
    API_ANSWERS["/api/stats/figures/vintages"] = saved;
  });

  console.log(`\n${n} statistics-versions checks passed`);
})().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
