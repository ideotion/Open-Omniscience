// Agenda -> Bulletin across a language switch (K-repaint, K-strings), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The Review panel, the editions list and the status lines were composed at render time
// in the language on screen then -- and much of it in English whatever the language, since
// the section names were raw slugs and the caveat, method and privacy sentences arrived
// from the server unkeyed. A switch left all of it as it was. This drives the SHIPPED
// functions (extracted from app-agenda.js) through a switch from en to fr, with the REAL
// fr.json behind `OOI18N`, and reads back what lands in each host.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const SRC = fs.readFileSync(path.join(STATIC, "app-agenda.js"), "utf8");
const LOC = {
  en: JSON.parse(fs.readFileSync(path.join(STATIC, "locales", "en.json"), "utf8")),
  fr: JSON.parse(fs.readFileSync(path.join(STATIC, "locales", "fr.json"), "utf8")),
};

function extract(name) {
  const at = SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in app-agenda.js -- was it renamed?");
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
// The panel's state declarations, read from the source rather than restated here, so a
// test cannot keep passing over state the shipped file no longer has.
function line(startsWith) {
  const at = SRC.indexOf(startsWith);
  assert.ok(at !== -1, "declaration not found: " + startsWith);
  return SRC.slice(at, SRC.indexOf("\n", at));
}

const code = [
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g," +
    "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "const _els = {}; function $(id){ return _els[id] || (_els[id] = {id, textContent: '', innerHTML: '', hidden: false, children: [], style: {}}); }",
  "var window = {};",
  "var OOI18N;",
  line("let _bulExcludeSections"), line("let _bulExcludeStories"), line("let _bulFile"),
  line("let _bulGate"), line("const _bulMsgs"),
  "const _BUL_CADENCE_LABEL = {};",
  ...["_bulT", "_bulTf", "_bulSay", "_bulPaintMsg", "_bulRepaint", "_bulPaintGate",
      "_bulPaintNarrationGate", "_bulPaintEditions", "_bulUnit", "_bulStoryTermsHtml", "_bulRender", "_bulPaintPrivacy"].map(extract),
  "module.exports = {",
  "  $, _bulSay, _bulRender, _bulRepaint, _bulPaintPrivacy,",
  "  setState(s){ _bulFile = s.file; _bulView = s.view; _bulPrivacyData = s.privacy; _bulEditions = s.editions; },",
  "  setLang(map){ OOI18N = window.OOI18N = { t: (s) => (map[s] == null ? s : map[s]),",
  "    tf: (s, v) => String(map[s] == null ? s : map[s]).replace(/\\{(\\w+)\\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)) }; },",
  "};",
].join("\n");
const B = (() => { const m = { exports: {} }; new Function("module", "exports", code)(m, m.exports); return m.exports; })();

const REVIEW_CAVEAT = "This is a DRAFT until you publish it. Nothing here has left this machine. What you "
  + "exclude is left out of the rendered document and the exclusion is stated in it, so a reader knows "
  + "they are reading a selection.";
const PRIV_WHAT = "The names and domains of the sources that contributed.";
const view = {
  state: "draft", caveat: REVIEW_CAVEAT, method: "", sections: [
    { section: "rising_concepts", rows: 3, window: { days: 14, matches_period: false } },
    { section: "across_channels", rows: 0, skipped: "no rising concepts to attribute for this period" },
  ], stories: [],
};
const privacy = { d: { caveat: "", items: [{ what: PRIV_WHAT, why_it_matters: "", present: true, n: 4 }] } };

// -- English first, as a reader would have it ------------------------------------------
B.setLang(LOC.en);
B.setState({ file: "e.json", view, privacy, editions: [] });
B._bulSay("bulletin-status", "Could not build: {error}", { error: "boom" });
B._bulSay("bul-pub", "Downloaded: the report and {n} annexed article(s).", { n: 2 });
B._bulRender(view);
B._bulPaintPrivacy();
assert.strictEqual(B.$("bulletin-status").textContent, "Could not build: boom");
assert.ok(B.$("bulletin-review").innerHTML.includes("Rising concepts"),
  "the section is named by its raw slug, not the heading the document prints");
assert.ok(B.$("bulletin-review").innerHTML.includes("window: 14 days"));

// -- a switch to French: NOTHING is fetched; everything on screen is said again ----------
B.setLang(LOC.fr);
B._bulRepaint();
const fr = LOC.fr;
assert.strictEqual(B.$("bulletin-status").textContent, fr["Could not build: {error}"].replace("{error}", "boom"),
  "the build status stayed in the language it was written in");
assert.strictEqual(B.$("bul-pub").textContent,
  fr["Downloaded: the report and {n} annexed article(s)."].replace("{n}", "2"),
  "the Review panel's status line was lost or stayed English");
const html = B.$("bulletin-review").innerHTML;
for (const key of ["Rising concepts", "Across channels", "Report only", "Publish", "Preview",
                   "Download report + annexes", "no rising concepts to attribute for this period"]) {
  assert.ok(fr[key] && fr[key] !== key, "fr.json has no real translation of " + JSON.stringify(key));
  assert.ok(html.includes(esc(fr[key])), "the Review did not repaint " + JSON.stringify(key) + " in French");
}
assert.ok(html.includes(esc(fr[REVIEW_CAVEAT])), "the review caveat is still English after the switch");
assert.ok(!html.includes("Rising concepts") && !html.includes("rising concepts"), "an English heading survived: " + html);
assert.ok(B.$("bul-privacy").innerHTML.includes(esc(fr[PRIV_WHAT])),
  "the privacy enumeration (consent text) is still English after the switch");

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
console.log("bulletin_repaint_node_test.js: all assertions passed");
