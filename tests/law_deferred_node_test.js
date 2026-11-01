// A host's own Crawl-delay is a DEFERRAL on the Law table and in the "Track changes now" toast, run as REAL code (R406, Q1013 = a).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Before: the tally said `deferred: 2, errors: 0` while the table badged the same two documents "fetch error", and the toast never read
// `deferred`, so a pass where every host deferred said "Tracked 0 law(s) ... 0 errors." and nothing about why nothing was fetched.
// After: the pill reads "deferred" (neutral, the stored reason still on hover) and the toast counts the deferrals in a clause of their own.
//
// EXTRACTED from the shipped module (a re-typed copy would pass while the real code was broken).

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function sliceBalanced(open, startAt) {
  let depth = 0, j = startAt;
  for (; j < APP.length; j++) {
    if (APP[j] === open) depth++;
    else if (APP[j] === (open === "{" ? "}" : ")")) { depth--; if (depth === 0) { j++; break; } }
  }
  return j;
}
function extract(name) {
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  const at = APP.slice(at0 - 6, at0) === "async " ? at0 - 6 : at0;
  const afterParams = sliceBalanced("(", APP.indexOf("(", at0));
  const open = APP.indexOf("{", afterParams);
  return APP.slice(at, sliceBalanced("{", open));
}
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = {");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  return APP.slice(at, sliceBalanced("{", APP.indexOf("{", at))) + ";";
}

const ESC = "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}";

// A tiny translation table, so a label that bypasses the translator cannot pass.
const DE = { "deferred": "zurückgestellt", "fetch error": "Abruffehler",
  "{n} deferred (the host's own Crawl-delay)": "{n} zurückgestellt (das eigene Crawl-delay des Hosts)" };

function badge(row, translated) {
  const win = translated ? "{ OOI18N: { t: (s) => DE[s] || s } }" : "{}";
  const f = new Function("DE", "var window = " + win + "; var OOI18N = window.OOI18N;\n" + [ESC, extractConst("_LAW_VERDICT_PILL"), extract("lawVerdictBadge"), "return lawVerdictBadge;"].join("\n"));
  return f(DE)(row);
}

function sandbox(response, translated) {
  const log = { toasts: [], laws: 0 };
  const els = {};
  const el = (id) => (els[id] = els[id] || { set textContent(v) {}, get textContent() { return ""; }, set innerHTML(v) {}, disabled: false });
  const win = translated
    ? "{ OOI18N: { t: (s) => DE[s] || s, tf: (s, v) => (DE[s] || s).replace(/\\{(\\w+)\\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m) } }"
    : "{}";
  const src = ["var window = " + win + "; var OOI18N = window.OOI18N;", "function _failMsg(t, e){return t;}", extract("_govT"), extract("_govTf"), extract("lawTrack"), "return { lawTrack };"].join("\n");
  const f = new Function("DE", "$", "api", "toast", "loadLaw", "loadLawChanges", src);
  const h = f(DE, el, async () => response, (m, k) => log.toasts.push([m, k || "ok"]), () => { log.laws++; }, () => {});
  return { h, log };
}
const base = { documents: 0, baselines: 0, changed: 0, flagged: 0, errors: 0, unchanged: 0 };

(async () => {
  // ---- the pill ----------------------------------------------------------------------------------------------------------
  const STORED = "deferred: Crawl-delay 3600 s: not before 2026-11-01T12:00:00+00:00";
  assert.strictEqual(badge({ verdict: "deferred", last_status: STORED }),
    `<span class="pill " title="${STORED}">deferred</span>`,
    "neutral (no warn, no ok) and the stored reason stays on hover");
  assert.ok(!/warn|ok/.test(badge({ verdict: "deferred", last_status: STORED }).match(/class="([^"]*)"/)[1]), "a deferral is neither a warning nor a success");
  assert.ok(badge({ verdict: "deferred", last_status: STORED }, true).includes(">zurückgestellt<"), "the label goes through the translator");
  assert.ok(badge({ verdict: "error", last_status: "fetch error: timed out" }).includes('class="pill warn"'), "a real failure still warns");
  assert.ok(badge({ verdict: "error", last_status: "fetch error: timed out" }, true).includes(">Abruffehler<"));

  // ---- the toast ---------------------------------------------------------------------------------------------------------
  {
    const { h, log } = sandbox({ ...base, deferred: 2 });
    await h.lawTrack(null);
    assert.deepStrictEqual(log.toasts, [["Tracked 0 law(s): 0 baselines, 0 changed, 0 flagged, 0 errors. 2 deferred (the host's own Crawl-delay)", "ok"]],
      "a pass where every host deferred says so, and still counts no error");
    assert.strictEqual(log.laws, 1, "the list is reloaded, its statuses changed");
  }
  {
    const { h, log } = sandbox({ ...base, documents: 3, baselines: 1, errors: 1, deferred: 1 });
    await h.lawTrack(null);
    assert.strictEqual(log.toasts[0][0], "Tracked 3 law(s): 1 baselines, 0 changed, 0 flagged, 1 errors. 1 deferred (the host's own Crawl-delay)");
  }
  {
    const { h, log } = sandbox({ ...base, documents: 2, errors: 2 });
    await h.lawTrack(null);
    assert.deepStrictEqual(log.toasts, [["Tracked 2 law(s): 0 baselines, 0 changed, 0 flagged, 2 errors.", "ok"]], "no deferral, no clause: the old figures are untouched");
  }
  {
    const { h, log } = sandbox({ ...base, deferred: 2 }, true);
    await h.lawTrack(null);
    assert.ok(log.toasts[0][0].endsWith("2 zurückgestellt (das eigene Crawl-delay des Hosts)"), "the clause is a keyed template: " + log.toasts[0][0]);
  }
  console.log("law_deferred_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
