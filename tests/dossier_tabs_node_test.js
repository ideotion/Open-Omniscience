// The dossier's rails as subtabs (0.8 row A, brief S08-01 S2, row 178 PR 5; invariant #18).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Mostly refusals: a rail without rows keeps its tab and says so on it; a rail's panel never
// opens without its provenance line; the method and the caveat never sit inside a panel, so no
// subtab hides them; the server's rail order is the tab order; and without the subtab component
// every panel stays visible rather than none. EXTRACTED from the shipped module, not re-typed.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-dossier.js"), "utf-8");

function extract(name) {
  const at = SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
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

const FNS = ["_dossierChannel", "_dossierRailName", "_dossierNotJoinedReason", "_dossierLaneAbsence", "passportLine",
             "_dossierRailSource", "_dossierRailCount", "_dossierItemsHtml", "_dossierRailBody", "_dossierTabsHtml", "_dossierRailPanel", "dossierHtml", "_dossierPaint"];
const harness = `
  let _dossierLast = null, _dossierTab = "overview";
  const EL = {};
  function $(id) { return EL[id]; }
  function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
  function ooCountryCode(c) { return String(c).toUpperCase(); }
  function ooPlaceKind(k) { return {text: String(k || '')}; }
  function _dossierT() { return (s) => s; }
  function _dossierTf() { return (s, v) => s.replace(/\\{(\\w+)\\}/g, (_, k) => v[k]); }
  let ooSubtabs;
  ${FNS.map(extract).join("\n")}
  module.exports = {EL, FNS: {${FNS.join(", ")}},
    set(d, tab, subtabs) { _dossierLast = d; _dossierTab = tab; ooSubtabs = subtabs; },
    tab() { return _dossierTab; }};
`;
const m = {exports: {}};
new Function("module", harness)(m);
const H = m.exports, R = H.FNS;
const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);

let n = 0;
function check(cond, msg) { assert.ok(cond, msg); n++; }

const keys = ["news", "wikipedia", "law", "places", "map", "stats", "climate", "agenda", "elections"];
const d = {
  qid: "Q142", item: {label: "France"}, routes: {}, passport: {articles: 0},
  rails: keys.map((k) => ({key: k, joined: true, articles: 0, count: {places: 1, stats: 3}[k] || 0, lane: {available: true}, series: [], events: []})),
  not_joined: [{key: "markets", joined: false}],
  availability: {joined: 9, with_rows: 2, rails_with_rows: ["places", "stats"]},
  method: "THE-METHOD", caveat: "THE-CAVEAT", article_ids: [],
};
const html = R.dossierHtml(d, t, tf);

// the tabs: Overview, then the rails in the server's order
const tabs = [...html.matchAll(/data-tab="([^"]+)"/g)].map((x) => x[1]);
check(JSON.stringify(tabs) === JSON.stringify(["overview", ...keys]), "the tab order is the rail order: " + tabs);
check(/<nav class="tabs dossier-tabs" id="dossier-tabs"/.test(html), "one <nav class=tabs> for ooSubtabs");
check(!/onclick|data-on-/.test(html.slice(html.indexOf("<nav"), html.indexOf("</nav>"))), "no inline handler on a tab");
// a gap is a gap: a rail without rows keeps its tab and says so on it
const tabOf = (k) => html.slice(html.indexOf(`data-tab="${k}"`), html.indexOf("</button>", html.indexOf(`data-tab="${k}"`)));
check(tabOf("news").includes("none here") && tabOf("news").includes("No rows on this machine"), "a gap says so on its tab");
check(!tabOf("stats").includes("none here"), "a rail with rows does not");
// every rail panel carries its provenance line, and is hidden until chosen; Overview is not
for (const k of keys) {
  const at = html.indexOf(`data-panel="${k}"`);
  const panel = html.slice(at, html.indexOf(`data-panel=`, at + 5) === -1 ? undefined : html.indexOf(`data-panel=`, at + 5));
  check(at !== -1 && html.slice(at, html.indexOf(">", at)) === `data-panel="${k}" hidden`, k + " panel present and hidden until chosen");
  check(/dossier-source">From /.test(panel), k + " panel opens with where its rows come from");
}
check(/data-panel="overview">/.test(html) && /data-panel="news" hidden>/.test(html), "only Overview shows at first");
// the Overview keeps every rail's count on the first screen; a gap reads as one
const ov = html.slice(html.indexOf('data-panel="overview"'), html.indexOf('data-panel="news"'));
check(ov.includes('<strong>Statistics</strong> <span class="">{n} rows</span>'.replace("{n}", "3")) && ov.includes("dossier-summary"), "the overview lists every rail with its count");
check((ov.match(/none here/g) || []).length === 7, "seven rails without rows read as none here in the overview");
// an unknown rail still opens with a provenance line
check(R._dossierRailSource("law_versions", t).startsWith("From "), "an unknown rail gets the generic line");
// the method and the caveat sit after every panel, so no subtab can hide them
const lastPanel = html.lastIndexOf("dossier-panel");
check(html.indexOf("THE-CAVEAT") > html.indexOf("</div>", html.indexOf("data-panel=\"elections\"")), "the caveat is below the panels");
check(html.indexOf("THE-METHOD") > lastPanel && html.indexOf("THE-CAVEAT") > lastPanel, "the method and caveat are outside every panel");

// Row 200: a corpus rail lists its rows. Each opens the LOCAL reader first (invariant #6), names how it
// joined (never a weight), keeps an undated row undated, and the rail says how many are not listed.
const items = [
  {id: 7, title: "A <b>title</b>", domain: "zz.example", published_at: "2026-03-01", joined_by: ["entities", "places"]},
  {id: 8, title: "", domain: "law.zz", published_at: null, joined_by: ["keywords", "made-up"]},
];
const listed = R._dossierRailBody({key: "news", articles: 30, by_channel: {web: 30}, items}, d, t, tf);
check(listed.includes('href="/api/articles/7/view"') && listed.includes('href="/api/articles/8/view"'), "each row opens the local reader");
check(!/https?:\/\//.test(listed), "no row links to the original first");
check(listed.includes("A &lt;b&gt;title&lt;/b&gt;"), "a title is escaped");
check(listed.includes("(untitled)") && listed.includes("undated"), "an empty title and a missing date are said, never invented");
check(listed.includes("joined through: a person or organisation named · a place named"), "both routes named for a row reached twice");
check(listed.includes("joined through: a keyword") && !listed.includes("made-up"), "an unknown route code is never shown raw");
check(listed.includes("2 of 30 shown"), "the rail says how many rows are not listed");
const all = R._dossierRailBody({key: "law", articles: 2, items}, d, t, tf);
check(!all.includes("of 2 shown"), "no cut line when every row is listed");
check(R._dossierRailBody({key: "wikipedia", articles: 0, items: [], lane: {available: true, pages: []}}, d, t, tf).indexOf("dossier-items") === -1,
      "a rail with no articles lists none");

// _dossierPaint with the REAL ooSubtabs (app-markets.js) over a minimal DOM: the component drives the
// panels, keeps the open tab across a repaint, and falls back to Overview for a tab the item lacks.
const MK = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-markets.js"), "utf-8");
const msrc = MK.slice(MK.indexOf("function ooSubtabs("));
let dd = 0, e = msrc.indexOf("{");
for (; e < msrc.length; e++) { if (msrc[e] === "{") dd++; else if (msrc[e] === "}") { dd--; if (dd === 0) { e++; break; } } }
global.document = {activeElement: null};
const realSubtabs = new Function(msrc.slice(0, e) + "; return ooSubtabs;")();
function fakeDom() {
  const all = ["overview", ...keys];
  const panels = all.map((k) => ({k, hidden: k !== "overview", getAttribute() { return k; }}));
  const buttons = all.map((k, i) => {
    const cls = new Set(i === 0 ? ["active"] : []);
    return {dataset: {tab: k}, attrs: {}, tabIndex: 0, type: "button",
      classList: {contains: (c) => cls.has(c), toggle: (c, on) => (on ? cls.add(c) : cls.delete(c))},
      setAttribute(a, v) { this.attrs[a] = v; }, getAttribute(a) { return this.attrs[a] || (a === "type" ? "button" : null); },
      focus() { global.document.activeElement = this; }, closest() { return this; }};
  });
  const nav = {listeners: {}, scrollWidth: 0, clientWidth: 0, querySelectorAll: () => buttons,
    setAttribute() {}, addEventListener(type, fn) { this.listeners[type] = fn; }, contains: () => true};
  H.EL["dossier-title"] = {}; H.EL["dossier-qid"] = {};
  H.EL["dossier-tabs"] = nav;
  H.EL["dossier-body"] = {set innerHTML(v) {}, querySelectorAll() { return panels; }};
  return {panels, buttons, nav};
}
const shown = (dom) => dom.panels.filter((p) => !p.hidden).map((p) => p.k).join();
let dom = fakeDom();
H.set(d, "stats", realSubtabs);
R._dossierPaint();
check(shown(dom) === "stats", "the open tab survives a repaint: " + shown(dom));
check(dom.buttons.find((b) => b.dataset.tab === "stats").attrs["aria-selected"] === "true", "the component marks the open tab");
dom.nav.listeners.click({target: dom.buttons.find((b) => b.dataset.tab === "news")});
check(shown(dom) === "news" && H.tab() === "news", "a click on a tab shows exactly its panel");
global.document.activeElement = dom.buttons.find((b) => b.dataset.tab === "news");
dom.nav.listeners.keydown({key: "End", preventDefault() {}});
check(shown(dom) === "elections", "End reaches the last rail");
dom = fakeDom();
H.set(d, "gone", realSubtabs);
R._dossierPaint();
check(shown(dom) === "overview" && H.tab() === "overview", "a tab the item does not have falls back to Overview");
dom = fakeDom();
H.set(d, "stats", undefined);
R._dossierPaint();
check(dom.panels.every((p) => !p.hidden), "without the subtab component every panel shows, never none");
console.log(n + " checks, all checks passed");
