// The dossier's entry points, run through the REAL functions (0.8 row A, brief S08-01 S2, row 178).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Mostly refusals: boolean syntax is not a name and is never asked; a stale search answer adds
// nothing; a name with several items lists them and opens none; a name with no item says so; a
// QID that is not one gets no button. EXTRACTED from the shipped module rather than re-typed.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-dossier.js"), "utf-8");

function extract(name) {
  const at = SRC.search(new RegExp("(async )?function " + name + "\\("));
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = SRC.indexOf("(", SRC.indexOf("function " + name, at)), depth = 0;
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

const FNS = ["_dossierT", "_dossierTf", "_dossierQidOk", "dossierButtonHtml", "_dossierTermOf", "_dossierResolve",
             "openDossierForTerm", "dossierSearchHint"];
const harness = `
  let _dossierSeq = 0, _dossierLast = null;
  const EL = {};
  function $(id) { return EL[id] || (EL[id] = {id, textContent: "", innerHTML: "", open: false,
    showModal() { this.open = true; }, children: [], appendChild(c) { this.children.push(c); }}); }
  const document = {createElement() { return {className: "", innerHTML: ""}; }};
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;'); }
  function _dossierWire() {}
  const opened = [], asked = [];
  function openDossier(q) { opened.push(q); }
  let answers = {};
  async function api(url) { asked.push(url); const term = new URLSearchParams(url.split("?")[1]).get("term");
    if (answers[term] instanceof Error) throw answers[term]; return answers[term] || {}; }
  const window = {};
  ${FNS.map(extract).join("\n")}
  module.exports = {EL, opened, asked, setAnswers(a) { answers = a; }, ${FNS.join(", ")}};
`;
const m = {exports: {}};
new Function("module", harness)(m);
const H = m.exports;

let n = 0;
function check(cond, msg) { assert.ok(cond, msg); n++; }

(async () => {
  // a name, never a query: boolean syntax, field filters, wildcards and overlong text are not asked
  check(H._dossierTermOf("Paris") === "Paris", "a plain name");
  check(H._dossierTermOf('"Emmanuel Macron"') === "Emmanuel Macron", "surrounding quotes are shed");
  for (const q of ["climate AND policy", "(a OR b)", "title:paris", "par*", "x".repeat(121), "", "   "]) {
    check(H._dossierTermOf(q) === "", "not a name: " + q);
  }
  // a button only for a real QID, and its argument is JSON (never a single-quoted value)
  check(H.dossierButtonHtml("Q90").includes("openDossier(&quot;Q90&quot;)"), "the JSON form");
  check(H.dossierButtonHtml("Q90").includes("ooStop(event)"), "a chip's own click does not run behind it");
  for (const bad of ["Q0", "q90", "Q90'", "P31", null, ""]) check(H.dossierButtonHtml(bad) === "", "no button for " + bad);

  // Explore: one item -> one line with its button; several or none -> nothing; a stale answer -> nothing
  H.setAnswers({Paris: {qid: "Q90"}, Mercury: {candidate_qids: ["Q308", "Q925"]}, Nowhere: {}});
  const host = {children: [], appendChild(c) { this.children.push(c); }};
  await H.dossierSearchHint("Paris", host, () => true);
  check(host.children.length === 1 && host.children[0].innerHTML.includes("Q90"), "a search naming one item offers it");
  await H.dossierSearchHint("Mercury", host, () => true);
  await H.dossierSearchHint("Nowhere", host, () => true);
  await H.dossierSearchHint("Paris", host, () => false);
  const before = H.asked.length;
  await H.dossierSearchHint("climate AND policy", host, () => true);
  check(host.children.length === 1, "several items, no item and a stale answer add nothing");
  check(H.asked.length === before, "a query that is not a name is never asked");

  // a Lead: one item opens it; several are listed and none is opened; none says so
  await H.openDossierForTerm("Paris");
  check(H.opened.join() === "Q90", "the one item opens");
  await H.openDossierForTerm("Mercury");
  const body = H.EL["dossier-body"].innerHTML;
  check(body.includes("dossier-candidate") && body.includes("Q308") && body.includes("Q925"), "several are listed");
  check(H.opened.length === 1, "several items open none");
  await H.openDossierForTerm("Nowhere");
  check(H.EL["dossier-body"].innerHTML.includes("No single Wikidata item"), "no item says so");
  check(H.EL["dossier"].open, "the dialog opened to say it");
  H.setAnswers({Broken: new Error("boom")});
  await H.openDossierForTerm("Broken");
  check(H.EL["dossier-body"].innerHTML.includes("Could not open the dossier:"), "a failure is named");
  // a keyword drawn INSIDE a chip button gets the QID link only: a nested <button> would close the chip at parse time
  const CORPUS = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-corpus.js"), "utf-8");
  const kq = CORPUS.slice(CORPUS.indexOf("function kwQidHtml("));
  const kqSrc = kq.slice(0, kq.indexOf("\n    }\n") + 6);
  const K = new Function("esc", "dossierButtonHtml", "window", kqSrc + "; return kwQidHtml;")(
    (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"),
    H.dossierButtonHtml, {});
  check(K({translation_qid: "Q90"}).includes("<button"), "a keyword row offers its dossier");
  check(!K({translation_qid: "Q90"}, {noDossier: true}).includes("<button"), "inside a button: no nested button");
  check(K({translation_qid: "Q90"}, {noDossier: true}).includes(">Q90</a>"), "inside a button: the QID link stays");
  check(K({}) === "", "no QID, nothing");
  // a Lead: the name comes from the title's DATA, never a quoted headline, phrase or watch label
  const HOME = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-home.js"), "utf-8");
  const ce = HOME.slice(HOME.indexOf("function cardEntityName("));
  const E = new Function(ce.slice(0, ce.indexOf("\n    }\n") + 6) + "; return cardEntityName;")();
  check(E({title_vars: {term: "Paris"}}) === "Paris", "a rising term");
  check(E({i18n: {title: [{t: "“{keyword}”: outlets frame it differently", v: {keyword: "NATO"}}]}}) === "NATO", "a framed keyword");
  check(E({title_vars: {title: "Minister resigns after budget vote"}}) === "", "a headline is not a name");
  check(E({i18n: {title: [{t: "Identical wording in {n} sources: “{phrase}”", v: {n: 3, phrase: "we will"}}]}}) === "", "a phrase is not a name");
  check(E({type: "watch_match", i18n: {title: [{t: "Watch “{name}” matched", v: {name: "my watch"}}]}}) === "", "a watch label is not a name");
  check(E({title: "“Paris” is rising"}) === "", "the English title is never regexed");
  console.log(n + " checks, all checks passed");
})().catch((e) => { console.error(e); process.exit(1); });
