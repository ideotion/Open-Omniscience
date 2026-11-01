// The omnibar's instant rung, driven as REAL code: it fires from the FIRST character, a late reply
// never overwrites a newer one, the rows say they are not ranked, and Enter still runs the Analysis.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
"use strict";
const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name, kind) {
  const at = APP.indexOf((kind || "function ") + name + "(");
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

const pending = [];   // fetches the test settles by hand, in any order
const src = `
  const calls = [];
  const els = {"pal-input": {value: ""}, "pal-list": {innerHTML: ""}, "palette": {classList: {contains: () => true}}};
  function $(id) { return els[id]; }
  const document = {querySelectorAll: () => [], querySelector: () => null};
  const window = {open: (u) => calls.push(["open", u])};
  const OOI18N = null;
  function esc(s) { return String(s == null ? "" : s); }
  function ooLabelText(l, v) { return l + ": " + v; }
  function ooIsoDate(x) { return x ? String(x).slice(0, 10) : ""; }
  function showTab() {} function doSearch() {} function openAnalysisInNewTab(q) { calls.push(["analyze", q]); }
  function _advHistRecord() {} function closePalette() {} function _trapTab() {}
  function openClaimWorkspace() {}
  function api() { return Promise.resolve({}); }
  let _omniLive = null; function _omniItems() { return []; } function _omniFetch() {}
  let _palItems = [], _palFiltered = [], _palSel = 0, _palLastRaw = null;
  const fetchCalls = [];
  function AbortController() { this.signal = {}; this.aborted = false; this.abort = () => { this.aborted = true; }; }
  const fetch = (url, init) => new Promise((resolve) => { fetchCalls.push({url, init, resolve}); });
  let _instLive = null, _instSeq = 0, _instAbort = null;
  ${extract("_instFetch", "async function ")}
  ${extract("_instItems")}
  ${extract("renderPalette")}
  ${extract("_palOrder")}
  module.exports = {calls, els, fetchCalls, renderPalette, _instItems, rows: () => _palFiltered, state: () => _instLive};
`;
const h = (() => { const m = {exports: {}}; new Function("module", "exports", src)(m, m.exports); return m.exports; })();
const reply = (i, q, hits, extra) => h.fetchCalls[i].resolve({ok: true, json: async () => Object.assign(
  {q, hits, more: false, index_complete: true}, extra || {})});
const tick = () => new Promise((r) => setImmediate(r));
let passed = 0;

(async () => {
  // 1. ONE character fires a request at once (the ranked omnibar waits for two and for a debounce).
  h.els["pal-input"].value = "z";
  h.renderPalette();
  assert.strictEqual(h.fetchCalls.length, 1);
  assert.ok(h.fetchCalls[0].url.includes("/api/search/instant") && h.fetchCalls[0].url.endsWith("q=z"));
  passed++;

  // 2. The next keystroke aborts the previous request, and a LATE reply to "z" cannot overwrite "zo".
  h.els["pal-input"].value = "zo";
  h.renderPalette();
  assert.strictEqual(h.fetchCalls.length, 2);
  assert.strictEqual(h.fetchCalls[0].init.signal !== h.fetchCalls[1].init.signal, true);
  reply(1, "zo", [{id: 7, title: "Zorblax seven", source: "Gazette", published_at: "2026-10-01T00:00:00"}]);
  await tick();
  reply(0, "z", [{id: 1, title: "STALE ZEBRA", source: "x"}]);
  await tick();
  assert.strictEqual(h.state().q, "zo", "the late reply to an older keystroke was dropped");
  h.renderPalette();
  const labels = h.rows().map((r) => r.label);
  assert.ok(labels.includes("Zorblax seven") && !labels.includes("STALE ZEBRA"));
  passed++;

  // 3. The group header says it is not ranked (visible by default), the row opens the LOCAL reader,
  //    and Enter's row (Analysis) is still row 0.
  const row = h.rows().find((r) => r.label === "Zorblax seven");
  assert.ok(/not ranked/.test(row.grp), "the caveat is in the visible group header");
  assert.strictEqual(h.rows()[0].sub, "↵ ↗", "Enter still runs the Analysis");
  row.run();
  assert.deepStrictEqual(h.calls.filter((c) => c[0] === "open"), [["open", "/api/articles/7/view"]]);
  passed++;

  // 4. Honest coverage: an incomplete index says so and offers the build; "more" says there is more.
  reply(1, "zo", [{id: 7, title: "Zorblax seven"}], {});   // (already settled: a no-op)
  h.els["pal-input"].value = "zor";
  h.renderPalette();
  reply(2, "zor", [{id: 8, title: "Zorblax eight"}], {more: true, index_complete: false});
  await tick();
  h.renderPalette();
  const all = h.rows().map((r) => r.label);
  assert.ok(all.some((l) => /more titles match/.test(l)));
  assert.ok(all.some((l) => /title index does not cover older articles/.test(l)));
  passed++;

  // 5. A failed request leaves the palette as it was (no throw, no blank).
  h.els["pal-input"].value = "q";
  h.renderPalette();
  h.fetchCalls[3].resolve({ok: false, json: async () => ({})});
  await tick();
  h.renderPalette();
  assert.ok(h.rows().length > 0);
  passed++;

  console.log(`instant_rung_node_test: ${passed} passed`);
})().catch((e) => { console.error(e); process.exit(1); });
