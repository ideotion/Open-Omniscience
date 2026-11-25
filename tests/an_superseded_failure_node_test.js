// Row 394: a superseded analysis run never writes, on its FAILURE path too.
//
// loadAnalysis bumps _anRunSeq and checks stale() after every await, so a run that a
// newer one replaced drops its answers. A REJECTED await skipped that check: it landed
// in a catch that wrote the old run's error into the panel the newer run had already
// painted, then went on to write "Loading..." into the next panel. The same hole was in
// _anLoadArtFacets (a failure blanked the newer corpus's chips) and loadAnContext (an old
// concordance or its failure landed on the newer chips). The real functions are
// extracted from the shipped modules; only their collaborators are stubs.
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

// Every request is a deferred the test settles by hand, so the order of answers is the
// test's choice and not the event loop's.
const HARNESS = `
  const pending = [];
  function api(url) {
    let res, rej;
    const pr = new Promise((a, b) => { res = a; rej = b; });
    pending.push({ url: String(url), res, rej });
    return pr;
  }
  const els = {};
  function $(id) {
    if (!els[id]) els[id] = { id, innerHTML: "", style: { display: "none" }, dataset: {} };
    return els[id];
  }
  function esc(s) { return String(s == null ? "" : s); }
  function ooLiveHtml(el, render) { if (el) el.innerHTML = String(render()); }
  const window = {};
  let _anRunSeq = 0, _anLastParams = null, _anProvenance = "", _anKwSort = false, _anKwForCount = "";
  let _anArtFacetSel = {}, _anFormCountsLast = {}, _anPanelsLast = {}, _anKwData = null, _anKwHost = null;
  let _anArtFacetData = { sources: [], languages: [] };
  const _anTrend = {}, _anRelated = {}, _anCompetitive = {}, _anMM = {};
  const tag = (u) => (/query=(\\w+)/.exec(u) || [])[1] || "?";
  function _anApplyLens(p) { return p; }
  function tgtLangParam() { return ""; }
  function uiLangCode() { return "en"; }
  function _toggleAnPrice() {}
  function anQuery() { return ""; }
  function renderAnOverview() {} function renderAnTrend() {} function renderAnRelated() {}
  function renderAnCompetitive() {} function renderAnPapers() {}
  function anRenderKwChips() {
    const ctx = _anKwData && _anKwData._context;
    $("an-keywords").innerHTML = "CHIPS:" + (_anKwData ? _anKwData.tag : "-") + (ctx ? "/CTX:" + ctx.term : "");
  }
  function renderAnMindmap(g, mm) { mm.innerHTML = "MM:" + g.tag; }
  function _anWwwHtml(d) { return "WWW:" + d.tag; }
  function _anLinksHtml(d) { return "LINKS:" + d.tag; }
  function _anSentimentHtml(d) { return "SENT:" + d.tag; }
  function _anSourcesHtml(d) { return "SRC:" + d.tag; }
  function anNotCountedYetHtml(d) { return ""; }
  function _anRenderArtFacetChips() {
    $("an-art-facets").innerHTML = "FACETS:" + (_anArtFacetData.sources || []).join(",");
  }
  let articlesCalls = [];
  function _anLoadArticles(p, page, run) { articlesCalls.push(run); }
  function snapshot() { const o = {}; Object.keys(els).forEach((k) => { o[k] = els[k].innerHTML; }); return o; }
  function setKw(d) { _anKwData = d; }
  function runSeq() { return _anRunSeq; }
`;

const SRC = HARNESS
  + fnSource("loadAnalysis") + "\n"
  + fnSource("_anLoadArtFacets") + "\n"
  + fnSource("loadAnContext") + "\n"
  + "module.exports = { loadAnalysis, _anLoadArtFacets, loadAnContext, pending, snapshot, els,"
  + " setKw, runSeq, get articlesCalls() { return articlesCalls; } };";
function fresh() {
  const m = { exports: {} };
  new Function("module", "exports", "require", SRC)(m, m.exports, require);
  return m.exports;
}

const flush = () => new Promise((r) => setImmediate(r));
const payload = (url) => {
  const q = (/(?:query|term)=(\w+)/.exec(url) || [])[1] || "?";
  if (url.indexOf("/api/insights/concept-map") === 0) return null;
  if (url.indexOf("/api/insights/corpus-keywords") === 0) return { tag: q, terms: [{ term: "w" + q }] };
  if (url.indexOf("/api/insights/graph") === 0) return { tag: q };
  if (url.indexOf("/api/insights/corpus-source-language-facets") === 0) return { sources: ["s" + q], languages: [] };
  if (url.indexOf("/api/insights/context") === 0) return { mentions: [], resolved: { term: q } };
  return { tag: q };
};
const isRun = (q) => (c) => c.url.indexOf("query=" + q) >= 0 || c.url.indexOf("term=" + q) >= 0;
async function answerAll(M, q) {
  // Answer every request of one run, as they come, until it asks for nothing more.
  for (let guard = 0; guard < 50; guard++) {
    const i = M.pending.findIndex(isRun(q));
    if (i < 0) { await flush(); if (M.pending.findIndex(isRun(q)) < 0) return; continue; }
    const c = M.pending.splice(i, 1)[0];
    c.res(payload(c.url));
    await flush();
  }
  throw new Error("run " + q + " never finished");
}
async function answerSome(M, q, n) {
  for (let k = 0; k < n; k++) {
    await flush();
    const i = M.pending.findIndex(isRun(q));
    assert.ok(i >= 0, "run " + q + " had no request at step " + k);
    const c = M.pending.splice(i, 1)[0];
    c.res(payload(c.url));
  }
  await flush();
}

(async () => {
  // 1. EVERY CATCH IN loadAnalysis. Run A answers its first k requests, run B replaces it
  //    and is drawn in full, then A's next request FAILS. Nothing B drew may change, and
  //    A may not go on to write the next panel's "Loading...".
  //    The mind-map stage asks two things at once (graph + concept map), so the request
  //    count is not the stage count: k walks every request A can be stuck on.
  let stagesSeen = 0;
  for (let k = 0; k < 12; k++) {
    const M = fresh();
    M.loadAnalysis(new URLSearchParams("query=a"));
    await answerSome(M, "a", k).catch(() => null);
    await flush();
    const stuck = M.pending.filter(isRun("a"));
    if (!stuck.length) break;   // A had already finished: every stage was covered
    stagesSeen++;
    M.loadAnalysis(new URLSearchParams("query=b"));
    await answerAll(M, "b");
    const before = M.snapshot();
    assert.ok(/CHIPS:b/.test(before["an-keywords"]), "run B drew its chips");
    assert.strictEqual(before["an-sources"], "SRC:b", "run B reached its last panel");
    for (const c of stuck) { M.pending.splice(M.pending.indexOf(c), 1); c.rej(new Error("A-FAILED")); }
    await flush(); await flush();
    assert.deepStrictEqual(M.snapshot(), before,
      "a superseded run's failure at request " + k + " wrote over the newer run");
    assert.strictEqual(M.pending.filter(isRun("a")).length, 0,
      "a superseded run went on asking after its failure (request " + k + ")");
  }
  assert.ok(stagesSeen >= 6, "only " + stagesSeen + " stages exercised -- the walk lost its stages");

  // 2. THE GUARD IS NOT A GAG: a run that is still the newest shows its own failure.
  {
    const M = fresh();
    M.loadAnalysis(new URLSearchParams("query=c"));
    await flush();
    const c = M.pending.shift();
    c.rej(new Error("C-FAILED"));
    await flush();
    assert.ok(/C-FAILED/.test(M.els["an-keywords"].innerHTML), "the current run's failure is shown");
  }

  // 3. _anLoadArtFacets: an old run's failure never blanks the newer corpus's chips.
  {
    const M = fresh();
    M.loadAnalysis(new URLSearchParams("query=d"));   // run 1, left waiting
    await flush();
    const oldRun = M.runSeq();
    M._anLoadArtFacets(new URLSearchParams("query=d"), oldRun);
    M.loadAnalysis(new URLSearchParams("query=e"));   // run 2
    await flush();
    M._anLoadArtFacets(new URLSearchParams("query=e"), M.runSeq());
    await flush();
    const newF = M.pending.find((c) => c.url.indexOf("facets?query=e") >= 0);
    M.pending.splice(M.pending.indexOf(newF), 1); newF.res(payload(newF.url));
    await flush();
    assert.strictEqual(M.els["an-art-facets"].innerHTML, "FACETS:se");
    const oldF = M.pending.find((c) => c.url.indexOf("facets?query=d") >= 0);
    M.pending.splice(M.pending.indexOf(oldF), 1); oldF.rej(new Error("old"));
    await flush();
    assert.strictEqual(M.els["an-art-facets"].innerHTML, "FACETS:se", "an old failure blanked the newer chips");
  }

  // 4. loadAnContext: an old concordance, or its failure, never lands on the newer chips;
  //    a current one still does.
  for (const outcome of ["answer", "failure"]) {
    const M = fresh();
    M.loadAnalysis(new URLSearchParams("query=f"));
    await flush();
    const oldRun = M.runSeq();
    M.setKw({ tag: "f" });
    M.loadAnContext(new URLSearchParams("query=f"), oldRun);
    M.loadAnalysis(new URLSearchParams("query=g"));
    await flush();
    M.setKw({ tag: "g", _context: { term: "g" } });
    M.els["an-keywords"].innerHTML = "CHIPS:g/CTX:g";
    const old = M.pending.find((c) => c.url.indexOf("context?term=f") >= 0);
    M.pending.splice(M.pending.indexOf(old), 1);
    if (outcome === "answer") old.res(payload(old.url)); else old.rej(new Error("old"));
    await flush();
    assert.strictEqual(M.els["an-keywords"].innerHTML, "CHIPS:g/CTX:g", "an old concordance " + outcome + " landed");
  }
  {
    const M = fresh();
    M.setKw({ tag: "h" });
    M.loadAnContext(new URLSearchParams("query=h"), M.runSeq());
    await flush();
    const c = M.pending.find((x) => x.url.indexOf("context?term=h") >= 0);
    c.res(payload(c.url));
    await flush();
    assert.strictEqual(M.els["an-keywords"].innerHTML, "CHIPS:h/CTX:h", "the current run's concordance is drawn");
  }

  // 5. The page clamp keeps the run it was called with.
  assert.ok(/_anLoadArticles\(p, pages - 1, run\)/.test(fnSource("_anLoadArticles")),
    "the page clamp re-fetch dropped its run");

  console.log("an_superseded_failure_node_test.js: OK (" + stagesSeen + " stages)");
})().catch((e) => { console.error(e); process.exit(1); });
