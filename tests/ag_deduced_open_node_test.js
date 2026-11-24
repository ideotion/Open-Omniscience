// Row 399 (invariant 13b): a deduced date whose inline ids are not all of them reads its
// full set before it opens the analysis; past the analysis window's cap the label says
// how many of how many. The real functions are extracted from the shipped module.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

"use strict";
const assert = require("assert");
const APP = require("./app_source.js").appJs();

function fnSource(name) {
  const m = new RegExp("(?:async\\s+)?function\\s+" + name + "\\s*\\(").exec(APP);
  assert.ok(m, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", m.index));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(m.index, j);
}

const SRC = [
  "const window = {};",
  "let answer = null, opened = [], toasts = [], asked = [];",
  "async function api(u) { asked.push(u); if (answer instanceof Error) throw answer; return answer; }",
  "function toast(m) { toasts.push(m); }",
  "function _failMsg(s, e) { return s.replace('{error}', e.message); }",
  "function fmtNum(v) { return String(v); }",
  "function openAnalysisForIds(ids, label) { opened.push({ ids, label }); }",
  fnSource("_tfn"),
  fnSource("mapDeducedToAgenda"),
  fnSource("agOpenDeduced"),
  "module.exports = { mapDeducedToAgenda, agOpenDeduced, set: (a) => { answer = a; },",
  "  get opened() { return opened; }, get toasts() { return toasts; }, get asked() { return asked; } };",
].join("\n");
const M = (() => { const m = { exports: {} }; new Function("module", "exports", SRC)(m, m.exports); return m.exports; })();

(async () => {
  // 1. The flag rides through the mapping; an older payload stays complete.
  assert.strictEqual(M.mapDeducedToAgenda({ date: "2026-04-01", n_articles: 500, article_ids: [1], ids_complete: false }).ids_complete, false);
  assert.strictEqual(M.mapDeducedToAgenda({ date: "2026-04-01", n_articles: 2, article_ids: [1, 2] }).ids_complete, true);

  // 2. A full set under the cap opens exactly, with the plain title.
  M.set({ date: "2026-04-01", article_ids: [1, 2, 3], total: 3, complete: true });
  await M.agOpenDeduced("2026-04-01", "3 articles mention this date");
  assert.strictEqual(M.asked[0], "/api/events/deduced/ids?date=2026-04-01");
  assert.deepStrictEqual(M.opened[0], { ids: [1, 2, 3], label: "3 articles mention this date" });

  // 3. Past the cap the label says how many of how many.
  M.set({ date: "2026-04-01", article_ids: [1, 2], total: 9000, complete: false });
  await M.agOpenDeduced("2026-04-01", "9000 articles mention this date");
  assert.strictEqual(M.opened[1].label, "9000 articles mention this date · 2 of 9000 shown.");

  // 4. A failed read opens nothing and says so.
  M.set(new Error("boom"));
  await M.agOpenDeduced("2026-04-01", "x");
  assert.strictEqual(M.opened.length, 2, "a failed read still opened an analysis");
  assert.ok(/boom/.test(M.toasts[0]));

  // 5. The row routes an incomplete date through the full read, a complete one as before.
  const row = fnSource("agRow");
  assert.ok(/e\.ids_complete === false[\s\S]*agOpenDeduced\(/.test(row), "agRow no longer reads the full set first");
  assert.ok(row.includes("openAnalysisForIds("), "a complete date lost its direct open");

  console.log("ag_deduced_open_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
