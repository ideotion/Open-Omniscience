// The reader's port of the keyword label (M7), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The standalone reader (/api/articles/{id}/view) does not load the SPA bundle, so its
// Keywords tab drew the bare stored word: a French keyword stayed French in the English
// reader while the analysis window translated it. reader.js now carries a small port of
// `kwLabelParts`. What must hold is WHICH WORD LANDS ON SCREEN, per tier, so this drives
// the shipped functions rather than grepping for them.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "reader.js"), "utf8");

function extract(name) {
  const at = SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in reader.js -- was it renamed?");
  let i = SRC.indexOf("(", at), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "(") depth++;
    else if (SRC[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = SRC.indexOf("{", i);
  let d = 0, j = open;
  for (; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return SRC.slice(at, j);
}

const code =
  // The page's own `esc` builds a DOM node; the sandbox has no DOM, so an equivalent.
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}\n" +
  "var window = {}; var localStorage = {getItem: function(){ return null; }}; var _langDN = {};\n" +
  ["T", "TF", "uiLang", "langName", "langList", "countsLine", "rdLabel", "rdLabelHtml"]
    .map(extract).join("\n") + "\n" +
  "module.exports = { rdLabel, rdLabelHtml, langName, setUi: function (c) { window.OOI18N = {current: function () { return c; }}; } };";
const R = (() => { const m = { exports: {} }; new Function("module", "exports", code)(m, m.exports); return m.exports; })();

R.setUi("en");
// VERIFIED: the translation is the visible term; the tag names the language by NAME.
{
  const out = R.rdLabelHtml({ term: "climat", normalized: "climat", translation: "climate",
    translation_tier: "verified", translation_source_lang: "fr", translation_qid: "Q7942" });
  assert.ok(/>climate</.test(out) && !/>climat</.test(out), "the translation is not the visible term: " + out);
  assert.ok(/translated from French/.test(out), "the tag is missing or printed a code: " + out);
  assert.ok(/Original: climat/.test(out) && /Q7942/.test(out), "the hover lost the original or the QID: " + out);
  assert.ok(/data-i18n-dyn/.test(out), "the keyword is exposed to the i18n walker: " + out);
}
// UNTRANSLATED: shows itself, tagged with what it is.
{
  const out = R.rdLabelHtml({ term: "haushalt", translation_tier: "untranslated", translation_source_lang: "de" });
  assert.ok(/>haushalt</.test(out) && /in German/.test(out) && !/translated from/.test(out), out);
}
// SAME LANGUAGE: no tag at all.
{
  const out = R.rdLabelHtml({ term: "budget", translation_tier: "same_language", translation_source_lang: "en" });
  assert.ok(!/r-kw-tag/.test(out), "a word in the reader's own language draws a tag: " + out);
}
// SPLIT (M11): the reader's language among the mention languages -> never "foreign".
{
  const out = R.rdLabelHtml({ term: "software", translation_tier: "untranslated",
    translation_source_lang: "es", mention_languages: { es: 40, en: 30 } });
  assert.ok(/in Spanish and English/.test(out), "the split is not named: " + out);
  assert.ok(/Mentions by language: Spanish 40 · English 30/.test(out), out);
}
// Another UI language: names and list grammar follow it.
R.setUi("fr");
{
  const out = R.rdLabelHtml({ term: "Wahl", translation: "élection", translation_tier: "verified",
    translation_source_lang: "de" });
  assert.ok(/>élection</.test(out) && /translated from allemand/.test(out), out);
}
// The reader's own Intl owner (the alpha-3 guard names it): a raw region tag is reduced
// to the house key, and an echoed code is printed as a code, never offered as a name.
R.setUi("en");
assert.strictEqual(R.langName("en-US"), "English", "the region tag was not reduced to its base");
assert.strictEqual(R.langName("FR"), "French");
assert.strictEqual(R.langName(""), "");
console.log("reader_label_node_test.js: OK");
