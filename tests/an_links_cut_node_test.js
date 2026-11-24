// Row 404 (anti-capping): the Explore Links lists say when they were cut, and a branch
// from a shared origin opens every citing article (the server's article_ids), with a cut
// label only when the server says the set is incomplete. The real functions are
// extracted from the shipped module.
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
  "let answer = null, opened = [];",
  "let _anRelatedLinks = [{ domain: 'agency.example', normalized_url: 'https://agency.example/r' }];",
  "async function api() { return answer; }",
  "function esc(s) { return String(s == null ? '' : s); }",
  "function fmtNum(v) { return String(v); }",
  "function extLink(u, label) { return label; }",
  "function toast() {}",
  "function openAnalysisForIds(ids, label) { opened.push({ ids, label }); }",
  fnSource("_tfn"),
  fnSource("_anLinksCutHtml"),
  fnSource("_anFurnitureHtml"),
  fnSource("_anLinksHtml"),
  fnSource("_anCitingIds"),
  fnSource("_anCitingCut"),
  fnSource("branchFromOrigin"),
  "module.exports = { _anLinksHtml, branchFromOrigin, set: (a) => { answer = a; }, get opened() { return opened; } };",
].join("\n");
const M = (() => { const m = { exports: {} }; new Function("module", "exports", SRC)(m, m.exports); return m.exports; })();
const item = (u) => ({ normalized_url: u, domain: "x.example", citations: 3, citing_sources: 2, independence: "single_origin" });
const furn = (u) => ({ normalized_url: u, domain: "f.example", carried_by: 30 });
const SHOWN = / of \d+ shown\./g;

(async () => {
  // 1. Cut lists say how many there are; the furniture summary counts them all.
  {
    const html = M._anLinksHtml({ items: [item("a"), item("b")], items_total: 57,
      furniture_items: [furn("f")], furniture_total: 9, truncated: true });
    assert.ok(html.includes("2 of 57 shown."), "a cut Links table did not say so");
    assert.ok(html.includes("1 of 9 shown."), "a cut furniture list did not say so");
    assert.ok(/9 link\(s\) that one outlet carries/.test(html), "the furniture summary counted only the listed ones");
  }
  // 2. NEGATIVE SPACE: whole lists, and an older payload, claim no cut.
  {
    const whole = M._anLinksHtml({ items: [item("a")], items_total: 1, furniture_items: [furn("f")], furniture_total: 1 });
    assert.ok(!SHOWN.test(whole), "a whole list claimed a cut");
    const old = M._anLinksHtml({ items: [item("a")], furniture_items: [furn("f")] });
    assert.ok(!/ of \d+ shown\./.test(old), "an older payload claimed a cut");
  }
  // 3. More than the 200 listed, at most 5000: every id opens, and no cut label.
  {
    const ids = Array.from({ length: 250 }, (_, i) => i + 1);
    M.set({ count: 250, articles: ids.slice(0, 200).map((id) => ({ id })), article_ids: ids, ids_complete: true });
    await M.branchFromOrigin(0);
    const o = M.opened[0];
    assert.strictEqual(o.ids.length, 250, "the branch opened only the listed articles");
    assert.strictEqual(o.label, "agency.example · 250");
  }
  // 4. Past 5000 the label says how many of how many.
  {
    const ids = Array.from({ length: 5000 }, (_, i) => i + 1);
    M.set({ count: 7000, articles: [], article_ids: ids, ids_complete: false });
    await M.branchFromOrigin(0);
    assert.strictEqual(M.opened[1].label, "agency.example · 5000 · 5000 of 7000 shown.");
  }
  // 5. An older payload falls back to the listed articles.
  {
    M.set({ count: 2, articles: [{ id: 7 }, { id: 8 }] });
    await M.branchFromOrigin(0);
    assert.deepStrictEqual(M.opened[2].ids, [7, 8]);
    assert.strictEqual(M.opened[2].label, "agency.example · 2");
  }
  // 6. The multi-select branch unions the full sets too.
  assert.ok(/_anCitingIds\(d\)/.test(fnSource("branchSelectedRelated")), "the multi-select branch lost the full set");
  console.log("an_links_cut_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
