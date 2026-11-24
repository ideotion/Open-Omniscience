// Row 372(b): app-map.js renderers that drew t()/tf() output into ordinary nodes now draw through ooLive /
// ooLiveHtml, so a live language switch redraws them -- run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Each renderer is EXTRACTED from the shipped modules, with the shipped ooLive helpers (app-core.js) and the shipped
// t()/tf() engine over the shipped locales. A renderer is driven once in English, the language is switched to French
// the way setLang() does (the map swapped, then the oo:langchange listener's ooLiveRepaint()), and the node must now
// read French -- with no second request. On the old code each of these nodes kept its English after the switch.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

function extractFrom(src, name) {
  const at = src.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  let d = 0, j = open;
  for (; j < src.length; j++) {
    if (src[j] === "{") d++;
    else if (src[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  const async = src.slice(Math.max(0, at - 6), at) === "async " ? "async " : "";
  return async + src.slice(at, j);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));

// ---- a DOM just large enough for the helper: text nodes, elements, attributes, connection ----
class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
}
class El {
  constructor(tag) { this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null; this.disabled = false; this.value = ""; }
  get isConnected() { return true; }
  hasAttribute(a) { return Object.prototype.hasOwnProperty.call(this.attrs, a); }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  getAttribute(a) { return this.hasAttribute(a) ? this.attrs[a] : null; }
  removeAttribute(a) { delete this.attrs[a]; }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = nodes; this._html = null;
    for (const c of nodes) c.parentNode = this;
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(...(v === "" ? [] : [new Text(String(v))])); }
  get innerHTML() { return this._html != null ? this._html : this.textContent; }
  set innerHTML(v) { this.replaceChildren(new Text(String(v))); this._html = String(v); }
}

const map = {};
let lang = "en";
const OOI18N = engine(map, () => lang);
function switchTo(l) {   // setLang() as shipped: swap the map, then the one oo:langchange listener's repaint
  lang = l; for (const k of Object.keys(map)) delete map[k];
  if (l !== "en") { const d = locale(l); for (const k in d) if (k !== "_meta") map[k] = d[k]; }
  M.ooLiveRepaint();
}

const DOM = {};
const $ = (id) => DOM[id] || null;
let API = () => ({});
const calls = [];
const src = [
  "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
  ...["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml", "ooLiveRepaint"].map((n) => extractFrom(APP, n)),
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function fmtNum(v){ return String(v); }",
  "function ooIsoDate(s){ return String(s).slice(0, 10); }",
  "const _OO_OSM_STREET_STYLE = [];",
  "let _fpState = { inputId: null, requireWritable: true, current: null };",
  ...["_failMsg", "_mapTf", "_govT", "_govTf", "_ooOsmLaneVintage", "_ooOsmLaneLegend", "fetchStatFigure", "runSeriesCorpus", "_fpNav"].map((n) => extractFrom(APP, n)),
  "return { ooLiveRepaint, nodes: _ooLiveNodes, _ooOsmLaneLegend, fetchStatFigure, runSeriesCorpus, _fpNav };",
].join("\n");
const M = new Function("window", "OOI18N", "document", "MutationObserver", "$", "api", "ensureOnline", "loadStatFigures", "setTimeout", src)(
  { OOI18N }, OOI18N, { createElement: (tag) => new El(tag.toUpperCase()) }, undefined, $,
  async (url, opts) => { calls.push(url); return API(url, opts); }, async () => true, () => {}, (fn) => fn());

(async () => {
  // 1. _ooOsmLaneLegend: the OSM lane line under the map (ooLive, text).
  {
    switchTo("en");
    const line = new El("DIV");
    const host = { querySelector: (sel) => (sel === "[data-oomap-osmlane]" ? line : null) };
    M._ooOsmLaneLegend(host, { status: "clusters", total: 12, clusters: [1, 2, 3], caps: {}, vintage: [] }, 5, 7);
    assert.strictEqual(line.textContent, "OpenStreetMap, objects in view: 12. Drawn as clusters: 3.");
    switchTo("fr");
    assert.strictEqual(line.textContent, "OpenStreetMap, objets dans la vue : 12. Dessinés en groupes : 3.",
      "the lane line kept the language it was drawn in");
  }

  // 2. fetchStatFigure: the fetch tally (ooLiveHtml) -- the server's values still escaped, nothing asked again.
  {
    switchTo("en");
    DOM["statfig-source"] = Object.assign(new El("SELECT"), { value: "worldbank" });
    DOM["statfig-series"] = Object.assign(new El("INPUT"), { value: "NY.GDP" });
    DOM["statfig-country"] = Object.assign(new El("INPUT"), { value: "FR" });
    DOM["statfig-view-series"] = new El("INPUT");
    DOM["statfig-fetch"] = new El("BUTTON");
    const msg = DOM["statfig-msg"] = new El("DIV");
    API = () => ({ fetched: 3, stored: 2, duplicate: 1, gaps: 0, caveat: "<b>not a key</b>" });
    calls.length = 0;
    await M.fetchStatFigure();
    assert.ok(msg.innerHTML.startsWith("<b>3</b> fetched · 2 stored"), msg.innerHTML);
    assert.ok(msg.innerHTML.includes("&lt;b&gt;not a key&lt;/b&gt;"), "the server's caveat is escaped: " + msg.innerHTML);
    switchTo("fr");
    assert.ok(msg.innerHTML.startsWith("<b>3</b> récupérés · 2 enregistrés"), "the tally kept its language: " + msg.innerHTML);
    assert.ok(msg.innerHTML.includes("&lt;b&gt;not a key&lt;/b&gt;"), "still escaped after the repaint");
    assert.strictEqual(calls.length, 1, "the switch asked nothing again");
    // the empty-field refusal is a live line too
    switchTo("en");
    DOM["statfig-series"].value = "";
    await M.fetchStatFigure();
    assert.strictEqual(msg.textContent, "Enter an indicator or dataset id first.");
    switchTo("fr");
    assert.strictEqual(msg.textContent, "Saisissez d'abord un identifiant d'indicateur ou de jeu de données.");
  }

  // 3. runSeriesCorpus: the series-corpus tally (ooLive, a tf() frame welded to the counts).
  {
    switchTo("en");
    const msg = DOM["statcorpus-msg"] = new El("DIV");
    DOM["statcorpus-run"] = new El("BUTTON");
    API = (url, opts) => (opts && opts.method === "POST") ? { started: true }
      : { state: "done", result: { created: 4, updated: 1, unchanged: 9, complete: true } };
    await M.runSeriesCorpus();
    assert.strictEqual(msg.textContent, "4 new · 1 updated · 9 already current — every stored series is now in the corpus.");
    switchTo("fr");
    assert.strictEqual(msg.textContent,
      "4 nouvelles · 1 mises à jour · 9 déjà à jour — toutes les séries stockées sont désormais dans le corpus.",
      "the tally kept the language it was drawn in");
  }

  // 4. _fpNav: the folder picker's note (ooLive) and its "Parent folder" row label (ooLive on the row's span,
  //    so the rows keep the click listeners bound to them).
  {
    switchTo("en");
    const parentSpan = new El("SPAN");
    const list = new El("DIV");
    list.querySelector = (sel) => (sel === "[data-fp-parent]" ? parentSpan : null);
    list.querySelectorAll = () => [];
    DOM["fp-list"] = list; DOM["fp-path"] = new El("DIV"); DOM["fp-use"] = new El("BUTTON");
    const note = DOM["fp-note"] = new El("DIV");
    API = () => ({ path: "/data/x", parent: "/data", entries: [{ name: "a", path: "/data/x/a" }], writable: false });
    await M._fpNav("/data/x");
    assert.ok(list.innerHTML.includes("data-fp-parent"), list.innerHTML);
    assert.strictEqual(parentSpan.textContent, "Parent folder");
    assert.strictEqual(note.textContent, "This folder is not writable — pick another for a backup destination.");
    switchTo("fr");
    assert.strictEqual(parentSpan.textContent, "Dossier parent");
    assert.strictEqual(note.textContent,
      "Ce dossier n'est pas accessible en écriture — choisissez-en un autre comme destination de sauvegarde.");
  }

  console.log("app_map_live_i18n_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
