// What scopes a Methods appendix / signed Evidence bundle — run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// /api/reports/methods and /api/reports/evidence have always accepted
// `article_ids | query` (one _select_articles serves both). The client sent only
// `{query}`, so on an id-seeded #an corpus — the exact set behind a Lead, a facet
// drill, anything from openAnalysisForIds — both buttons refused, and refused with
// advice that was false there ("Run a search first" to someone already looking at a
// Lead's articles). The buttons render unconditionally, so the surface claimed a
// capability it declined on click.
//
// Executed rather than grepped, for the reason recorded the same day: a source
// assertion that `article_ids` is MENTIONED survives a resolver that reads the field
// and drops it.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", at));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}

// $() is the app's id lookup; the two ids this resolver can touch are stubbed.
function build(stubs) {
  const src =
    "const _els = " + JSON.stringify(stubs) + ";\n" +
    "function $(id){ return Object.prototype.hasOwnProperty.call(_els, id)" +
    " ? {textContent: _els[id], value: _els[id]} : null; }\n" +
    extract("_reportScope") + "\nreturn _reportScope;";
  return new Function(src)();
}

// --- an id-seeded corpus reaches the endpoint that was already waiting for it --- //
const withIds = build({"an-query": "“Rare earth supply”"});
const ids = withIds(new URLSearchParams("article_ids=4,17,102"));
assert.deepStrictEqual(ids.article_ids, [4, 17, 102],
  "the exact article set must travel as article_ids");
assert.ok(!("query" in ids), "an id set must not also claim a query it does not have");
assert.strictEqual(ids.case_name, "Rare earth supply",
  "the corpus's own visible label names the bundle -- never a fabricated name");

// --- the label's typographic quotes are stripped, not carried into the bundle --- //
assert.strictEqual(build({"an-query": '"Plain quotes"'})(
  new URLSearchParams("article_ids=1,2")).case_name, "Plain quotes");

// --- no label is honest silence, never an invented case name ------------------- //
const unlabelled = build({"an-query": ""})(new URLSearchParams("article_ids=9"));
assert.strictEqual(unlabelled.case_name, null,
  "with nothing to name it, the bundle carries no case name rather than a made-up one");
assert.deepStrictEqual(unlabelled.article_ids, [9]);

// --- a query-defined corpus is unchanged --------------------------------------- //
const q = build({})(new URLSearchParams("query=lithium+mining&source=x"));
assert.deepStrictEqual(q, {query: "lithium mining", case_name: "lithium mining"});
assert.ok(!("article_ids" in q));

// --- the Search tab's own call shapes keep working exactly ---------------------- //
assert.deepStrictEqual(build({q: "cobalt"})(undefined),
  {query: "cobalt", case_name: "cobalt"}, "no argument reads the Search tab input");
assert.deepStrictEqual(build({q: "  cobalt  "})(undefined).query, "cobalt");
assert.deepStrictEqual(build({})("typed string"),
  {query: "typed string", case_name: "typed string"}, "a bare string still scopes");

// --- nothing to scope returns null, so the CALLER owns its own message ---------- //
assert.strictEqual(build({q: ""})(undefined), null);
assert.strictEqual(build({q: "   "})(undefined), null);
assert.strictEqual(build({})(new URLSearchParams("source=reuters")), null,
  "filters alone scope nothing -- a source filter is not a corpus");
assert.strictEqual(build({})(new URLSearchParams("query=")), null);

// --- a malformed id list does not silently become an empty set ------------------ //
assert.strictEqual(build({})(new URLSearchParams("article_ids=,,")), null,
  "no parsable id and no query is nothing to scope -- never an empty bundle");
assert.deepStrictEqual(
  build({"an-query": "x"})(new URLSearchParams("article_ids=5,bad,7")).article_ids, [5, 7],
  "unparsable entries are dropped, the real ids still travel");

console.log("report_scope_node_test: all assertions passed");
