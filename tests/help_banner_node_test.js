// The Help reader's coverage banner (S06-05 S2), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What is guarded is a set of refusals a diff does not show: an English reader gets NO banner; a non-English reader who is
// served the English original is told why (the mixed-language-document lesson), not left to guess; a figure that could not be
// measured is ABSENT with its reason, never a guessed number; a draft with more headings than the English is never "more than
// complete"; and the language's own name is escaped. EXTRACTED from the shipped module, not re-typed.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
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
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "var window = globalThis.__win; var OOI18N = window.OOI18N;\n" +
  extract("docSections") + "\n" + extract("docBannerHtml") + "\n" +
  "module.exports = { docSections, docBannerHtml };";
function load(win) {
  globalThis.__win = win;
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
}
const bare = load({});                       // OOI18N absent: the boot-time state, English templates
const text = (html) => html.replace(/<[^>]+>/g, "");

// --- docSections: the unit is the ATX heading, fenced code ignored ---------- //
{
  const md = "# A\n\ntext\n## B\n```\n# not a heading\n## nor this\n```\n#nospace\n### C\n~~~\n# fenced too\n~~~\n";
  assert.strictEqual(bare.docSections(md), 3, "headings counted wrongly: " + bare.docSections(md));
  assert.strictEqual(bare.docSections(""), 0);
  assert.strictEqual(bare.docSections(null), 0);
}

// --- an English reader reading English draws nothing ------------------------ //
assert.strictEqual(bare.docBannerHtml("en", "en", null, null, "English"), "");
assert.strictEqual(bare.docBannerHtml("", "en", null, null, ""), "");

// --- a draft states its language, the authority and the figure, in a named unit
{
  const out = text(bare.docBannerHtml("fr", "fr", 8, 17, "Français"));
  assert.ok(/Machine-drafted translation \(Français\)/.test(out), out);
  assert.ok(/8 of the 17 headings/.test(out), "the figure is missing or in no unit: " + out);
  assert.ok(/English original is authoritative/.test(out), out);
  assert.ok(bare.docBannerHtml("fr", "fr", 8, 17, "Français").includes('data-doc-banner="draft"'));
}

// --- a draft with extra headings is never more than complete --------------- //
assert.ok(/17 of the 17 headings/.test(text(bare.docBannerHtml("fr", "fr", 23, 17, "Français"))));

// --- an unmeasurable figure is absent WITH its reason, never a number ------- //
for (const [done, total] of [[8, null], [null, 17], [null, null]]) {
  const out = text(bare.docBannerHtml("fr", "fr", done, total, "Français"));
  assert.ok(/could not be measured/.test(out), "no reason given: " + out);
  assert.ok(!/\d/.test(out), "a number was drawn without a measurement: " + out);
}

// --- a non-English reader served English is told why ------------------------ //
{
  const html = bare.docBannerHtml("ja", "en", null, null, "日本語");
  assert.ok(html.includes('data-doc-banner="fallback"'), html);
  assert.ok(/no draft in this language yet \(日本語\), so the English original is shown\./.test(text(html)), text(html));
}

// --- the language name is data: escaped, and never translated --------------- //
{
  const html = bare.docBannerHtml("fr", "fr", 1, 2, "<b>x</b>");
  assert.ok(!html.includes("<b>x</b>") && html.includes("&lt;b&gt;x&lt;/b&gt;"), html);
}

// --- the frame translates and the data does not (OOI18N.tf in the loop) ----- //
{
  const map = { "This document has no draft in this language yet ({language}), so the English original is shown.": "Pas de version {language} pour l'instant." };
  const tr = load({ OOI18N: { tf: (s, v) => (map[s] || s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)) } });
  assert.ok(text(tr.docBannerHtml("fr", "en", null, null, "Français")).startsWith("Pas de version Français pour"), "the frame was not looked up");
}

// --- the unit is the same one the translated-documents guard counts --------- //
const docs = path.join(__dirname, "..", "docs");
const counts = {};
for (const f of ["USER_MANUAL", "QUICKSTART", "ETHICS", "GOVERNANCE", "SECURITY", "DESIGN", "ROADMAP", "ARCHITECTURE", "CONTRIBUTING", "CHANGES"]) {
  counts[f + ".md"] = bare.docSections(fs.readFileSync(path.join(docs, f + ".md"), "utf8"));
}
counts["fr/QUICKSTART.md"] = bare.docSections(fs.readFileSync(path.join(docs, "i18n", "fr", "QUICKSTART.md"), "utf8"));
console.log("COUNTS " + JSON.stringify(counts));
console.log("all assertions passed");
