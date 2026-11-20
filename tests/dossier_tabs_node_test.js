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
             "_dossierRailSource", "_dossierRailBody", "_dossierTabsHtml", "_dossierRailPanel", "dossierHtml", "_dossierPaint"];
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
  rails: keys.map((k) => ({key: k, joined: true, articles: 0, count: 0, lane: {available: true}, series: [], events: []})),
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
  check(at !== -1 && html.slice(at - 40, at).includes("hidden") === false, k + " panel present");
  check(/dossier-source">From /.test(panel), k + " panel opens with where its rows come from");
}
check(/data-panel="overview">/.test(html) && /data-panel="news" hidden>/.test(html), "only Overview shows at first");
// the method and the caveat sit after every panel, so no subtab can hide them
const lastPanel = html.lastIndexOf("dossier-panel");
check(html.indexOf("THE-CAVEAT") > html.indexOf("</div>", html.indexOf("data-panel=\"elections\"")), "the caveat is below the panels");
check(html.indexOf("THE-METHOD") > lastPanel && html.indexOf("THE-CAVEAT") > lastPanel, "the method and caveat are outside every panel");

// _dossierPaint: the subtab component drives the panels and keeps the open tab across a repaint
function fakeDom() {
  const panels = keys.concat(["overview"]).map((k) => ({k, hidden: true, getAttribute() { return k; }}));
  H.EL["dossier-title"] = {}; H.EL["dossier-qid"] = {};
  H.EL["dossier-tabs"] = {nav: true};
  H.EL["dossier-body"] = {set innerHTML(v) {}, querySelectorAll() { return panels; }};
  return panels;
}
let panels = fakeDom(), selected = [];
const comp = (nav, onSelect) => ({select(k) { if (![...keys, "overview"].includes(k)) return false; selected.push(k); onSelect(k); return true; }});
H.set(d, "stats", comp);
R._dossierPaint();
check(selected.join() === "stats", "the open tab survives a repaint");
check(panels.filter((p) => !p.hidden).map((p) => p.k).join() === "stats", "exactly the chosen panel shows");
panels = fakeDom(); selected = [];
H.set(d, "gone", comp);
R._dossierPaint();
check(selected.join() === "overview" && H.tab() === "overview", "a tab the item does not have falls back to Overview");
panels = fakeDom();
H.set(d, "stats", undefined);
R._dossierPaint();
check(panels.every((p) => !p.hidden), "without the subtab component every panel shows, never none");
console.log(n + " checks, all checks passed");
