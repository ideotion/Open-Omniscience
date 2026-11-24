// Row 395 (anti-capping): the Sources and Competitive tables say when they were cut,
// and the Competitive corpus span is the server's whole-set span, not the span of the
// rows that made the cut. The real renderers are extracted from the shipped modules.
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
  "const document = { documentElement: { dir: 'ltr' } };",
  "function esc(s) { return String(s == null ? '' : s); }",
  "function fmtNum(v) { return String(v); }",
  "function ooLtrIsolate(s) { return s; }",
  fnSource("ooIsoDate"),
  fnSource("_tfn"),
  fnSource("_anSourceCatalogHtml"),
  fnSource("_anSourcesCutHtml"),
  fnSource("_anSourcesHtml"),
  fnSource("_anCompetitiveHtml"),
  "module.exports = { _anSourcesHtml, _anCompetitiveHtml };",
].join("\n");
const M = (() => { const m = { exports: {} }; new Function("module", "exports", SRC)(m, m.exports); return m.exports; })();

const row = (name, n, first, last) => ({ name, domain: name + ".test", articles: n, mean_tone: null, first, last, tags: [] });
const rows = [row("A", 9, "2026-03-02T00:00:00", "2026-03-03T00:00:00"), row("B", 5, "2026-03-02T00:00:00", "2026-03-04T00:00:00")];
const CUT = "2 of 7 shown.";

// 1. Sources: a cut table says how many sources the set holds.
{
  const html = M._anSourcesHtml({ sources: rows, count: 2, sources_total: 7, truncated: true });
  assert.ok(html.includes(CUT), "a cut Sources table did not say so: " + html);
}
// 2. NEGATIVE SPACE: a whole table, and a payload with no count, say nothing.
{
  const whole = M._anSourcesHtml({ sources: rows, count: 2, sources_total: 2, truncated: false });
  assert.ok(!/ of \d+ shown\./.test(whole), "a whole table claimed a cut");
  const old = M._anSourcesHtml({ sources: rows, count: 2 });
  assert.ok(!/ of \d+ shown\./.test(old), "a payload without the count claimed a cut");
}
// 3. Competitive: the cut line, and the corpus span from the server, not from the rows.
{
  const cs = { sources: rows, count: 2, sources_total: 7, truncated: true, n_articles: 30,
               corpus_first: "2026-01-15T00:00:00", corpus_last: "2026-05-20T00:00:00" };
  const html = M._anCompetitiveHtml(cs, null, "q");
  assert.ok(html.includes(CUT), "a cut Competitive table did not say so");
  assert.ok(html.includes("2026-01-15") && html.includes("2026-05-20"), "the corpus span was not the server's: " + html.slice(-400));
  assert.ok(!html.includes("2026-03-04 "), "the span still came from the shown rows");
}
// 4. An older payload without the span keeps the rows' span (the fallback).
{
  const html = M._anCompetitiveHtml({ sources: rows, n_articles: 14 }, null, "q");
  assert.ok(html.includes("2026-03-02") && html.includes("2026-03-04"), "the fallback span was lost");
  assert.ok(!/ of \d+ shown\./.test(html));
}

console.log("an_sources_cut_node_test.js: OK");
