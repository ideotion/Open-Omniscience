// Markets' "Coverage that moves with a commodity" panel, run as REAL code (Lane M's routes
// list: GET /api/signals/supply-chain-ripple had no button).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Guarded here, by running the shipped functions: nothing is fetched until the reader
// asks; the short co-occurrence caveat is drawn visible in every state (R685); an empty
// answer says WHY in a keyed sentence and how many pairs were tested; a pair's Articles
// button opens exactly that pair's article ids; and an earlier request's late reply never
// paints over a later one.

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
  const head = APP.slice(Math.max(0, at - 6), at);
  return (head.endsWith("async ") ? "async " : "") + APP.slice(at, j);
}
function block(startsWith) {
  const at = APP.indexOf(startsWith);
  assert.ok(at !== -1, "declaration not found: " + startsWith);
  return APP.slice(at, APP.indexOf("};", at) + 2);
}
function line(startsWith) {
  const at = APP.indexOf(startsWith);
  assert.ok(at !== -1, "declaration not found: " + startsWith);
  return APP.slice(at, APP.indexOf("\n", at));
}

const NAMES = ["mktRippleLoad", "mktRippleOpen", "paintMktRipple"];
const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  line("let _mktRipple = null") + "\n" + block("const _MKT_RIPPLE_NOTES") + "\n" +
  NAMES.map(extract).join("\n") + "\nreturn { " + NAMES.join(", ") + " };";

const host = {innerHTML: ""};
const calls = [], pending = [], opened = [];
function api(url) { calls.push(url); return new Promise((res, rej) => pending.push({res, rej})); }
const window = {};
const M = new Function("$", "api", "window", "openAnalysisForIds", "ooLtrIsolate", src)(
  (id) => (id === "mkt-ripple" ? host : null), api, window, (ids, label) => opened.push({ids, label}), (v) => String(v));

const CAVEAT = "Coverage moving together, never proof that one causes the other.";
const caveatVisible = () => /<p class="card-caveat"[^>]*>Coverage moving together, never proof that one causes the other\.<\/p>/.test(host.innerHTML);

(async () => {
  // --- first paint: caveat + button, and NO fetch --------------------------- //
  M.paintMktRipple();
  assert.strictEqual(calls.length, 0, "the scan must not run until the reader asks");
  assert.ok(caveatVisible(), "the short caveat is visible before anything is asked");
  assert.ok(host.innerHTML.includes('data-on-click="mktRippleLoad(this)"'));

  // --- an empty answer says why, in a keyed sentence, with the pairs tested -- //
  const btn = {disabled: false};
  let p = M.mktRippleLoad(btn);
  assert.strictEqual(calls[0], "/api/signals/supply-chain-ripple");
  assert.ok(btn.disabled && host.innerHTML.includes("Comparing daily coverage"));
  pending.shift().res({items: [], tests: 0, window_days: 90, note: "no tracked commodity resolves to a keyword", caveat: "LONG", method: "M"});
  await p;
  assert.strictEqual(btn.disabled, false);
  assert.ok(host.innerHTML.includes("No tracked commodity matches a keyword in your corpus yet."), host.innerHTML);
  assert.ok(!host.innerHTML.includes("resolves to a keyword"), "the server's raw note must not reach the page");
  assert.ok(host.innerHTML.includes("Pairs tested: 0 · shown: 0 · window: 90 days"));
  assert.ok(caveatVisible());
  assert.ok(host.innerHTML.includes('title="LONG"'), "the long caveat rides the hover");

  // --- survivors: a row per pair, and Articles opens exactly its ids ---------- //
  p = M.mktRippleLoad(btn);
  pending.shift().res({tests: 40, window_days: 90, caveat: "LONG", method: "M", items: [
    {commodity: "Gold", keyword: "inflation", correlation: 0.71, fdr_qvalue: 0.012, distinct_sources_commodity: 5,
     distinct_sources_keyword: 9, article_ids: [3, 4, 5], n_articles: 3},
    {commodity: "<b>x</b>", keyword: "drought", correlation: -0.2, fdr_qvalue: 0.04, article_ids: [8], n_articles: 1}]});
  await p;
  const h = host.innerHTML;
  assert.ok(h.includes("+0.71") && h.includes("-0.20") && h.includes("0.012") && h.includes("5 / 9"), h);
  assert.ok(h.includes("Pairs tested: 40 · shown: 2"));
  assert.ok(!h.includes("<b>x</b>") && h.includes("&lt;b&gt;x&lt;/b&gt;"), "a label is escaped");
  assert.ok(h.includes('<td data-i18n-dyn>Gold</td>'), "corpus labels opt out of the key walker");
  assert.ok(caveatVisible());
  M.mktRippleOpen(0);
  assert.deepStrictEqual(opened[0].ids, [3, 4, 5]);
  assert.ok(opened[0].label.includes("Gold") && opened[0].label.includes("inflation"));

  // --- a late reply from an earlier request never paints over a later one ---- //
  const p1 = M.mktRippleLoad(btn), first = pending.shift();
  const p2 = M.mktRippleLoad(btn), second = pending.shift();
  second.res({items: [], tests: 7, window_days: 90});
  await p2;
  first.res({items: [], tests: 99, window_days: 90});
  await p1;
  assert.ok(host.innerHTML.includes("Pairs tested: 7"), host.innerHTML);
  assert.ok(!host.innerHTML.includes("Pairs tested: 99"));
  M.paintMktRipple();  // a repaint (a language switch) draws from the kept state
  assert.ok(host.innerHTML.includes("Pairs tested: 7"), "the stale reply overwrote the kept state");

  // --- a failure is said, and the caveat stays ------------------------------- //
  p = M.mktRippleLoad(btn); pending.shift().rej(new Error("boom")); await p;
  assert.ok(host.innerHTML.includes("Could not compare coverage: boom"));
  assert.ok(caveatVisible());

  console.log("markets ripple: all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
