// Two more keyword surfaces through the ONE label (2026-09-27 re-walk M-3/M-5, M-6), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// * `kwKindLabel`: the Explore "Resolved to" pill and the family lists printed the stored
//   kind ("term") raw in every locale. It is a KEY now, and an unknown kind still shows
//   itself rather than a blank.
// * `_bulStoryTermsHtml`: the Bulletin review's "Stories" listed a Russian story's terms
//   bare in a French UI. Each term now carries what it is ("in Russian"), a term in the
//   reader's own language carries nothing, an old record with names only stays untagged
//   rather than tagged with a guess, and every term is data-i18n-dyn so the walker cannot
//   translate a keyword that equals an interface key.
//
// EXTRACTED from the shipped modules rather than re-typed.

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

const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}\n" +
  // A name table that is NOT the identity, so a NAME is told apart from a CODE.
  "var _NAMES = {fr: 'French', ru: 'Russian', es: 'Spanish', en: 'English'};\n" +
  "function ooLangName(code, fb){ return _NAMES[code] || fb || code; }\n" +
  "var window = {}; var OOI18N;\n" +
  "function openLinkPreview(){}\nfunction openAnalysisFor(){}\n" +
  ["_kwTf", "kwLangName", "kwTier", "kwLangBreakdownText", "uiLangCode", "_kwLangCells",
   "_kwScopeTail", "kwMentionLangs", "kwLangListName", "_kwLabelState", "kwLabelParts",
   "kwHoverText", "kwQidHtml", "kwHasTag", "kwTipExtraAttr", "kwSensePickerHtml",
   "kwSensesAfterHtml", "kwPickSense", "kwLabelHtml", "kwKindLabel", "_bulStoryTermsHtml"]
    .map(extract).join("\n") + "\n" +
  "module.exports = { kwKindLabel, _bulStoryTermsHtml,\n" +
  "  setUi: function (c, map) { OOI18N = window.OOI18N = {current: function () { return c; },\n" +
  "    t: function (s) { return (map && map[s] != null) ? map[s] : s; }}; } };";
const K = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

// --- the kind pill is a key ------------------------------------------------------- //
K.setUi("fr", { Term: "Terme", Person: "Personne", Organisation: "Organisation", Place: "Lieu", Entity: "Entité" });
assert.strictEqual(K.kwKindLabel("term"), "Terme", "the stored kind is printed raw (M-6)");
assert.strictEqual(K.kwKindLabel("location"), "Lieu");
assert.strictEqual(K.kwKindLabel("person"), "Personne");
assert.strictEqual(K.kwKindLabel("entity"), "Entité");
assert.strictEqual(K.kwKindLabel("mystery"), "mystery", "an unknown kind must still show itself");
assert.strictEqual(K.kwKindLabel(null), "");

// --- a foreign story's terms say what they are ------------------------------------- //
K.setUi("fr");
const ru = K._bulStoryTermsHtml({
  shared_terms: ["голосов", "избирателей"],
  shared_term_rows: [
    { term: "голосов", normalized: "голосов", language: "ru" },
    { term: "избирателей", normalized: "избирателей", language: "ru" },
  ],
});
assert.strictEqual((ru.match(/class="kw-tag/g) || []).length, 2, "every foreign term is tagged: " + ru);
assert.ok(/in Russian/.test(ru), "the tag names the language, not its code: " + ru);
assert.ok(!/in ru\b/.test(ru), ru);
assert.strictEqual((ru.match(/<span class="kw-term" data-i18n-dyn>/g) || []).length, 2,
  "each term must opt out of the walker: " + ru);

// --- a term in the reader's own language carries no tag ---------------------------- //
const own = K._bulStoryTermsHtml({
  shared_term_rows: [{ term: "élection", normalized: "élection", language: "fr" },
                     { term: "votos", normalized: "votos", language: "es" }],
});
assert.strictEqual((own.match(/class="kw-tag/g) || []).length, 1, own);
assert.ok(/>élection<\/span>, /.test(own), "the native term is shown bare: " + own);
assert.ok(/in Spanish/.test(own), own);

// --- an old record (names only) is untagged, never tagged with a guess -------------- //
const old = K._bulStoryTermsHtml({ shared_terms: ["errors", "código"] });
assert.ok(!/kw-tag/.test(old), "a term with no recorded language must not be tagged: " + old);
assert.ok(/data-i18n-dyn>errors</.test(old), "a keyword equal to a chrome key must stay data: " + old);
assert.strictEqual(K._bulStoryTermsHtml({ shared_terms: [] }), "—");
assert.strictEqual(K._bulStoryTermsHtml(null), "—");

// --- nothing escapes unescaped -------------------------------------------------- //
const evil = K._bulStoryTermsHtml({ shared_term_rows: [{ term: "<img src=x>", language: "ru" }] });
assert.ok(!/<img/.test(evil), evil);

console.log("all assertions passed");
