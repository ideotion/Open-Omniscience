// A 503 that names a scan pause reaches the Home strip and the map as that text, never as "No data" or an empty panel.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The REAL catch blocks are run: `loadHomeTrends` and `loadMap` are lifted out of the shipped engine and driven with a
// fake `api` that rejects the way api() does (an Error with .status and .message = the server's detail).

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function fnSource(name, asyncFn) {
  const head = (asyncFn ? "async function " : "function ") + name + "(";
  const at = APP.indexOf(head);
  assert.ok(at >= 0, name + " must be in the engine");
  let i = APP.indexOf("{", APP.indexOf(")", at)), depth = 0;
  for (let j = i; j < APP.length; j++) {
    if (APP[j] === "{") depth++;
    else if (APP[j] === "}") { depth--; if (depth === 0) return APP.slice(at, j + 1); }
  }
  throw new Error("unbalanced " + name);
}

const WORDS = "Scans are paused while the database log is being checkpointed (WAL pause); try again shortly.";
function refusal(status, message) { const e = new Error(message); e.status = status; return e; }

const els = {};
function el(id) { return els[id] || (els[id] = {id, hidden: false, innerHTML: "", value: ""}); }
const env = {
  $: el, esc: (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;"),
  uiLangCode: () => "en", tgtLangParam: () => "", toast: () => {}, _failMsg: (t, e) => t.replace("{error}", e.message),
  _renderOverviewTrends: () => {}, _syncHomeSubtabs: () => {}, MAP_W: 1, MAP_H: 1,
};
const trendBlock = APP.slice(APP.indexOf("const _HOME_TRENDS_BASE_MS"), APP.indexOf("async function loadHomeTrends()"));
function load(apiImpl) {
  const names = Object.keys(env);
  const body = trendBlock + "\n" + fnSource("loadHomeTrends", true) + "\n" + fnSource("loadMap", true)
    + "\nreturn {loadHomeTrends, loadMap, homeTrendsBackoff};";
  return new Function(...names, "api", "window", "document", body)(...names.map((n) => env[n]), apiImpl, {}, {});
}
let n = 0;
async function test(name, fn) { await fn(); n++; console.log("ok - " + name); }

(async () => {
  await test("Home shows the pause's words, visibly, instead of hiding the strip", async () => {
    els["home-trends-panel"] = {hidden: true, innerHTML: ""}; els["home-trends"] = {innerHTML: ""};
    const m = load(async () => { throw refusal(503, WORDS); });
    await m.loadHomeTrends();
    assert.strictEqual(els["home-trends-panel"].hidden, false);
    assert.ok(els["home-trends"].innerHTML.includes(WORDS), "the named pause must be on screen");
    assert.ok(!/No data/i.test(els["home-trends"].innerHTML));
  });

  await test("a 503 is a refusal for Home's back-off: the gap doubles", async () => {
    const m = load(async () => { throw refusal(503, WORDS); });
    await m.loadHomeTrends(); await m.loadHomeTrends();
    assert.strictEqual(m.homeTrendsBackoff().fails, 2);
  });

  await test("a failure that is not a 503 still hides the strip as before", async () => {
    els["home-trends-panel"] = {hidden: false, innerHTML: ""}; els["home-trends"] = {innerHTML: "stale"};
    const m = load(async () => { throw refusal(404, "not found"); });
    await m.loadHomeTrends();
    assert.strictEqual(els["home-trends-panel"].hidden, true);
    assert.strictEqual(els["home-trends"].innerHTML, "");
  });

  await test("the map puts the pause's words in both tables, not the empty-state text", async () => {
    els["map-days"] = {value: "30"}; els["map-kind"] = {value: ""}; els["map-countries"] = {innerHTML: ""}; els["map-cities"] = {innerHTML: ""};
    const m = load(async () => { throw refusal(503, WORDS); });
    await m.loadMap();
    for (const id of ["map-countries", "map-cities"]) {
      assert.ok(els[id].innerHTML.includes(WORDS), id + " must name the pause");
      assert.ok(!/No data/i.test(els[id].innerHTML));
    }
  });

  await test("the map leaves its tables alone for a failure that is not a 503", async () => {
    els["map-countries"] = {innerHTML: "kept"}; els["map-cities"] = {innerHTML: "kept"};
    const m = load(async () => { throw refusal(500, "boom"); });
    await m.loadMap();
    assert.strictEqual(els["map-countries"].innerHTML, "kept");
  });

  console.log(n + " checks");
})().catch((e) => { console.error(e); process.exit(1); });
