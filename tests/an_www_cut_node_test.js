// Row 397 (anti-capping): the Who / Where / When columns say when they were cut, with
// the same x12 line as the Sources table (row 395). The real renderer is extracted
// from the shipped module.
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
  "let _anFacets = {};",
  "function esc(s) { return String(s == null ? '' : s); }",
  "function fmtNum(v) { return String(v); }",
  "function ooCountryCode(c) { return String(c || '').toUpperCase(); }",
  "function entityLadderHoverText() { return ''; }",
  "function placeUnresolvedText() { return ''; }",
  "function placeNameSourceText() { return ''; }",
  fnSource("_tfn"),
  fnSource("_anWwwHtml"),
  "module.exports = { _anWwwHtml };",
].join("\n");
const M = (() => { const m = { exports: {} }; new Function("module", "exports", SRC)(m, m.exports); return m.exports; })();

const who = [{ name: "A", class: "person", articles: 3 }, { name: "B", class: "person", articles: 2 }];
const places = [{ name: "Paris", country: "fr", kind: "city", articles: 4 }];
const years = [{ year: "2001", articles: 2 }, { year: "2002", articles: 1 }];
const SHOWN = / of \d+ shown\./g;

// 1. Each cut column says how many values the set holds.
{
  const html = M._anWwwHtml({
    caveat: "Deduced from article text, never confirmed; counts only.",
    who: { entities: who, count: 2, total: 300, truncated: true },
    where: { places, count: 1, total: 57, truncated: true },
    when: { years, count: 2, total: 9, truncated: true },
  });
  assert.ok(html.includes("2 of 300 shown."), "Who did not say it was cut: " + html);
  assert.ok(html.includes("1 of 57 shown."), "Where did not say it was cut");
  assert.ok(html.includes("2 of 9 shown."), "When did not say it was cut");
  // the deduced-from-text caveat still shows above the columns
  assert.ok(html.includes("Deduced from article text, never confirmed"), "the caveat was lost");
}
// 2. NEGATIVE SPACE: only the cut column speaks; a whole one and an older payload stay silent.
{
  const html = M._anWwwHtml({
    who: { entities: who, count: 2, total: 2, truncated: false },
    where: { places, count: 1, total: 57, truncated: true },
    when: { years, count: 2 },
  });
  assert.strictEqual((html.match(SHOWN) || []).length, 1, "a whole or older column claimed a cut");
  const old = M._anWwwHtml({ who: { entities: who }, where: { places }, when: { years } });
  assert.ok(!SHOWN.test(old), "a payload without totals claimed a cut");
}

console.log("an_www_cut_node_test.js: OK");
