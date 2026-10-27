// Two enum words the UI used to print raw, now through t() (R291, qual): the weather refusal verdict
// (app-home.js) and the corpus keyword kind (app-corpus.js). Run against the real functions.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What must hold: every word of the closed set goes through t() and the raw token never survives; a word the
// page has no entry for is shown exactly as the route sent it (so a newer server is never mislabelled); an
// inherited property name is not a word; an absent verdict is an empty string, never "undefined".

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
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}

const src = extractConst("_WX_VERDICT_WORDS") + "\n" + extract("_wxVerdictLabel") + "\n" + extract("kwKindLabel") + "\n" +
  "module.exports = {_WX_VERDICT_WORDS, _wxVerdictLabel, kwKindLabel};";
const sandbox = { OOI18N: { t: (s) => "T[" + s + "]" } };
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", "window", "OOI18N", src)(m, m.exports, sandbox, sandbox.OOI18N);
  return m.exports;
})();

const t = (s) => "T[" + s + "]";
assert.strictEqual(R._WX_VERDICT_WORDS.length, 9, "the closed set is the nine verdicts the route can send");
for (const v of R._WX_VERDICT_WORDS) {
  assert.strictEqual(R._wxVerdictLabel(v, t), "T[" + v + "]", v + " must go through t()");
}
assert.strictEqual(R._wxVerdictLabel("a-verdict-from-a-newer-server", t), "a-verdict-from-a-newer-server");
assert.strictEqual(R._wxVerdictLabel("toString", t), "toString", "an inherited name is not a verdict word");
assert.strictEqual(R._wxVerdictLabel(undefined, t), "");
assert.strictEqual(R._wxVerdictLabel(null, t), "");

for (const [k, en] of [["person", "Person"], ["org", "Organisation"], ["location", "Place"], ["entity", "Entity"], ["term", "Term"]]) {
  assert.strictEqual(R.kwKindLabel(k), "T[" + en + "]", k);
}
assert.strictEqual(R.kwKindLabel("zzz"), "zzz", "a kind with no word is shown as sent");
assert.strictEqual(R.kwKindLabel("toString"), "toString", "an inherited name is not a kind");
assert.strictEqual(R.kwKindLabel(undefined), "");

console.log("raw token labels: all checks passed");
