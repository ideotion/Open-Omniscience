// The advanced-search builder's pure half, run as REAL code (S05-01).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What is driven: the chips' two-way edit of the query box (Q602), the permalink
// round-trip (Q616), the saved-search stored form (Q606) and the timescale snapping
// (Q609). Each function is EXTRACTED from the shipped modules, so a renamed or broken
// function fails here rather than passing against a re-typed copy.

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
// A top-level `const NAME = ...;` statement, up to the first `;` at line end.
function constDecl(name) {
  const at = APP.indexOf("const " + name + " =");
  assert.ok(at !== -1, "const " + name + " not found");
  const end = APP.indexOf(";\n", at);
  return APP.slice(at, end + 1);
}

const src = [
  constDecl("_TS_DAY"),
  constDecl("ADV_KEYS"), constDecl("ADV_UI_KEYS"), constDecl("ADV_URL_KEYS"),
  constDecl("ADV_NEAR_SERVER_DEFAULT"), constDecl("_ADV_TOKEN_RE"), constDecl("TS_SCALES"),
  ...["_advClean", "_advLegacy", "_advTabKey", "_advToParams", "_advPick", "_advPermalink",
    "_advToWatchFilters", "_advFromWatchFilters", "_advTokens", "_advParse", "_advQuoteVal",
    "_advFieldToken", "_advNearToken", "_advSplice", "_advAppend", "_tsSnap", "_tsStep",
    "_tsParse", "_tsIso"].map(extract),
  "module.exports = {_advClean, _advLegacy, _advTabKey, _advPick, _advPermalink," +
  " _advToWatchFilters, _advFromWatchFilters, _advParse, _advFieldToken, _advNearToken," +
  " _advSplice, _advAppend, _tsSnap, _tsStep, _tsParse, _tsIso};",
].join("\n");
const h = (() => { const m = {exports: {}}; new Function("module", "exports", src)(m, m.exports); return m.exports; })();

let passed = 0;
const ok = (name, fn) => { fn(); passed++; };

ok("a chip edits its own span and nothing else (two-way, Q602)", () => {
  const q = 'climate AND title:"heat wave" AND NOT url:example.com';
  const chips = h._advParse(q);
  assert.strictEqual(chips.length, 2);
  assert.deepStrictEqual([chips[0].field, chips[0].mode, chips[0].value, chips[0].neg], ["title", "contains", "heat wave", false]);
  assert.deepStrictEqual([chips[1].field, chips[1].neg], ["url", true]);
  // Switch the title chip to "starts with": only its span changes.
  const c = Object.assign({}, chips[0], {mode: "prefix"});
  const q2 = h._advSplice(q, c.start, c.end, h._advFieldToken(c));
  assert.strictEqual(q2, 'climate AND title:"heat wave"* AND NOT url:example.com');
  assert.strictEqual(h._advParse(q2)[0].mode, "prefix");
});

ok("the three modes round-trip through the box", () => {
  for (const mode of ["contains", "prefix", "exact"]) {
    for (const value of ["heat", "heat wave", "a*b", "x*"]) {
      const tok = h._advFieldToken({field: "author", mode, value, neg: false});
      const back = h._advParse(tok)[0];
      assert.deepStrictEqual([back.field, back.mode, back.value], ["author", mode, value], tok);
    }
  }
});

ok("a NEAR chip keeps its words and its distance; the stepper rewrites only the number", () => {
  const q = "flood NEAR(dam \"river bank\", 5)";
  const n = h._advParse(q)[0];
  assert.deepStrictEqual([n.kind, n.items, n.dist], ["near", ["dam", "river bank"], 5]);
  const q2 = h._advSplice(q, n.start, n.end, h._advNearToken(Object.assign({}, n, {dist: 12})));
  assert.strictEqual(q2, 'flood NEAR(dam "river bank", 12)');
  // No distance written: the reader's default applies server-side.
  assert.strictEqual(h._advParse("NEAR(a b)")[0].dist, null);
  // A comma-free body of any length parses in linear time (the regex this replaced did not).
  const long = "NEAR(" + "a ".repeat(20000) + ")";
  const t0 = Date.now(); h._advParse(long); assert.ok(Date.now() - t0 < 2000);
});

ok("removing a chip leaves no dangling operator", () => {
  const q = "climate AND title:heat";
  const c = h._advParse(q)[0];
  assert.strictEqual(h._advSplice(q, c.start, c.end, ""), "climate");
  const q2 = "title:heat AND climate";
  const c2 = h._advParse(q2)[0];
  assert.strictEqual(h._advSplice(q2, c2.start, c2.end, ""), "climate");
  const q3 = "NOT source:blog";
  const c3 = h._advParse(q3)[0];
  assert.strictEqual(h._advSplice(q3, c3.start, c3.end, ""), "", "the chip's own NOT goes with it");
});

ok("the permalink carries the whole search and reads back identically (Q616)", () => {
  const adv = {langs: "fr,de", lang_basis: "asserted", sources: "3,7", start_date: "2026-01-01",
    collected_to: "2026-09-01", words_min: "300", sentiment: "negative", include_quarantined: "true",
    exact: "true", near: "4", published_scale: "month"};
  const qs = h._advPermalink("élection NEAR(vote fraude, 3)", adv, {sort_by: "words", sort_dir: "asc", view: "list"});
  const sp = new URLSearchParams(qs);
  assert.strictEqual(sp.get("analyze"), "élection NEAR(vote fraude, 3)");
  assert.deepStrictEqual(h._advPick(sp), h._advClean(adv));
  assert.strictEqual(sp.get("sort_by"), "words");
  assert.strictEqual(sp.get("view"), "list");
  // Same search, same identity: the tab key is order-independent.
  const shuffled = {};
  Object.keys(adv).reverse().forEach((k) => { shuffled[k] = adv[k]; });
  assert.strictEqual(h._advTabKey("x", adv), h._advTabKey("x", shuffled));
  assert.notStrictEqual(h._advTabKey("x", adv), h._advTabKey("x", {}));
});

ok("defaults are not filters: an empty basis, a day scale and a lone basis drop out", () => {
  assert.deepStrictEqual(h._advClean({lang_basis: "asserted"}), {});
  assert.deepStrictEqual(h._advClean({langs: "fr", lang_basis: "any"}), {langs: "fr"});
  assert.deepStrictEqual(h._advClean({published_scale: "day", words_min: ""}), {});
});

ok("a saved search stores the same filters it re-opens with (Q606)", () => {
  const adv = h._advClean({langs: "fr", lang_basis: "detected", sources: "3,7", start_date: "2026-01-01",
    end_date: "2026-02-01", words_max: "900", sentiment: "positive,neutral", exact: "true", near: "10"});
  const f = h._advToWatchFilters(adv);
  assert.deepStrictEqual(f.source_ids, [3, 7]);
  assert.strictEqual(f.published_from, "2026-01-01");
  assert.strictEqual(f.near, 10, "an explicit distance is kept even when it is the grammar's default");
  assert.deepStrictEqual(h._advFromWatchFilters(f), adv);
  // The Search tab's single asserted language becomes the same filter in stored form.
  assert.deepStrictEqual(h._advToWatchFilters({language: "en"}), {langs: ["en"], lang_basis: "asserted"});
});

ok("a tab saved before the advanced search keeps its filters", () => {
  assert.deepStrictEqual(h._advLegacy({src: "Le Monde", lang: "fr", from: "2026-01-01", to: ""}),
    {source: "Le Monde", language: "fr", start_date: "2026-01-01"});
});

ok("the timescale snaps each bound to its period (Q609)", () => {
  const d = h._tsParse;
  // 2026-09-16 is a Wednesday: its ISO week runs Monday 14th to Sunday 20th.
  assert.strictEqual(h._tsIso(h._tsSnap(d("2026-09-16"), "week", "start")), "2026-09-14");
  assert.strictEqual(h._tsIso(h._tsSnap(d("2026-09-16"), "week", "end")), "2026-09-20");
  assert.strictEqual(h._tsIso(h._tsSnap(d("2024-02-10"), "month", "end")), "2024-02-29");
  assert.strictEqual(h._tsIso(h._tsSnap(d("2026-09-16"), "year", "start")), "2026-01-01");
  assert.strictEqual(h._tsSnap(d("2026-09-16"), "day", "start"), d("2026-09-16"));
  // One keyboard step is one whole period, landing on a period edge.
  assert.strictEqual(h._tsIso(h._tsStep(d("2026-09-01"), "month", 1, "start")), "2026-10-01");
  assert.strictEqual(h._tsIso(h._tsStep(d("2026-09-30"), "month", -1, "end")), "2026-08-31");
  assert.strictEqual(h._tsIso(h._tsStep(d("2026-01-01"), "year", -1, "start")), "2025-01-01");
});

console.log(`advanced_search_node_test: ${passed} passed`);
