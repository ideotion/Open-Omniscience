// The Governments and Law tabs follow a language switch (row 367, app-gov-law.js), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Ten renderers in app-gov-law.js wrote t() output into ordinary nodes, so their words stayed in the language that was
// active when they were drawn. Now the loading and failure lines of Countries, Compare, Aggregates, Groups and the map
// are held; the map's "Latest available" year keeps the year the reader picked across a switch; the Law pointer holds
// its words and its hover; and the buttons of "Load standard country data", "Summarize this change" and "Add & track"
// hold their busy words and give back their own label when the work ends. A list drawn over a held line is NOT redrawn
// by the hold. The consent (ensureOnline) still comes before any request.
//
// The functions are EXTRACTED from the shipped app-gov-law.js with the shipped ooLive family; t()/tf() are the shipped
// i18n engine over the shipped locales. Only the network and the DOM are stubs.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

function extract(name) {
  const at0 = APP.search(new RegExp("(?:async )?function " + name + "\\("));
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  const start = APP.lastIndexOf("\n", at0) + 1;
  let i = APP.indexOf("(", at0), depth = 0;
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
  return APP.slice(start, j);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));
const FR = locale("fr"), DE = locale("de");
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
class El {
  constructor(tag) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this._connected = true; this.title = ""; this.value = ""; this.disabled = false;
  }
  get isConnected() { return this._connected; }
  hasAttribute(a) { return Object.prototype.hasOwnProperty.call(this.attrs, a); }
  getAttribute(a) { return this.hasAttribute(a) ? this.attrs[a] : null; }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  removeAttribute(a) { delete this.attrs[a]; if (a === "title") this.title = ""; }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = nodes; this._html = null;
    for (const c of nodes) c.parentNode = this;
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(...(v === "" ? [] : [new Text(String(v))])); }
  get innerHTML() { return this._html != null ? this._html : this.textContent; }
  set innerHTML(v) {
    const html = String(v);
    // the text a browser would read out of the markup, so a foreign write is told by its text, as in app-core.js
    this.replaceChildren(...(html === "" ? [] : [new Text(html.replace(/<[^>]*>/g, ""))])); this._html = html;
  }
  closest() { return null; }
}

const CORE = ["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml",
  "ooLiveRepaint"];
const FNS = ["_govTf", "loadGovCountries", "renderGovCompare", "loadGovAggregate", "renderGovGroup", "loadGovMap", "renderGovMap",
  "govLoadStandard", "_lawPointerLine", "loadLawPointer", "_lawFailedText", "lawSummarize", "lawVerdictLabel", "lawAddDocument"];
const IDS = ["gov-country", "gov-country-data", "gov-law-pointer", "gov-cmp-a", "gov-cmp-b", "gov-cmp-body", "gov-agg-body",
  "gov-grp-pick", "gov-grp-ind", "gov-grp-year", "gov-grp-body", "gov-map-ind", "gov-map-year", "gov-map-host",
  "gov-map-caveat", "law-add-msg", "law-add-jur", "law-add-title", "law-add-url", "law-add-official"];

function harness(answers, extra) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  for (const id of IDS) nodes[id] = new El(id.endsWith("-year") || id === "gov-country" || id.endsWith("-ind") ? "SELECT" : "DIV");
  const held = [], calls = [];
  const api = (url, o) => {
    const key = ((o && o.method) || "GET") + " " + url;
    calls.push(key);
    const a = answers[key];
    if (a === "hold") return new Promise((resolve, reject) => held.push({ resolve, reject }));
    if (a === undefined) return Promise.reject(new Error("unexpected call " + key));
    if (a instanceof Error) return Promise.reject(a);
    return Promise.resolve(a);
  };
  const document = { getElementById: (id) => nodes[id] || null, createElement: (tag) => new El(tag.toUpperCase()) };
  const window = { OOI18N };
  const src = [
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    "let _govCountriesInit = false, _govCountryLast = null, _govCmpLast = null, _govAggLast = null, _govGrpLast = null;",
    "let _govMapLast = null, _govMapData = null, _govMapInit = true, _govInds = [], _govSubtabs = null;",
    ...CORE.map(extract), ...FNS.map(extract),
    "return { fns: {" + FNS.join(",") + ", ooLiveRepaint} };",
  ].join("\n");
  const env = Object.assign({
    window, OOI18N, document, MutationObserver: undefined, console, esc, $: (id) => nodes[id] || null, api,
    toast() {}, fmtNum: (x) => String(x), ooCountryCompare: (a, b) => (a < b ? -1 : 1), _govPickLabel: (c) => c,
    loadGovIndicators: async () => {}, loadGovCountry() {}, _govCompareHtml: () => "<table>CMP</table>",
    _govAggHtml: () => "<div>AGG</div>", _govGroupHtml: () => "<div>GRP</div>", _govMapDraw: async () => {},
    lawAiSummaryHtml: () => "SUMMARY", loadLaw() {}, ensureOnline: async () => { calls.push("consent"); return true; },
    pollJobStatus: async () => ({ state: "done", result: { stored: 1 } }), _jobStillRunning: () => false,
    openTaskManager: null,
  }, extra || {});
  const out = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns: out.fns, nodes, held, calls, $: (id) => nodes[id],
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      out.fns.ooLiveRepaint();   // app-boot's ONE oo:langchange listener
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));
const has = (el, s) => el.innerHTML.includes(s) || el.textContent.includes(s);
const button = (label) => { const b = new El("BUTTON"); b.textContent = label; return b; };

(async () => {
  // 1. Compare: the loading line and the failure line follow a switch; a table drawn over the hold is left alone.
  {
    const h = harness({ "GET /api/governments/country/FR": "hold", "GET /api/governments/country/DE": "hold" });
    h.$("gov-cmp-a").value = "FR"; h.$("gov-cmp-b").value = "DE";
    const p = h.fns.renderGovCompare();
    h.switchTo("fr");
    assert.ok(has(h.$("gov-cmp-body"), esc(FR["Loading…"])), "Compare's loading line follows a switch");
    h.held[0].reject(new Error("x")); await p;
    h.switchTo("de");
    assert.ok(has(h.$("gov-cmp-body"), esc(DE["Could not load these countries."])), "Compare's failure line follows a switch");
    const h2 = harness({ "GET /api/governments/country/FR": {}, "GET /api/governments/country/DE": {} });
    h2.$("gov-cmp-a").value = "FR"; h2.$("gov-cmp-b").value = "DE";
    await h2.fns.renderGovCompare();
    h2.switchTo("fr");
    assert.strictEqual(h2.$("gov-cmp-body").innerHTML, "<table>CMP</table>", "a table drawn over the hold is not redrawn by it");
  }

  // 2. Aggregates and Groups: their failure lines follow a switch.
  {
    const h = harness({ "GET /api/governments/aggregate/EUU": new Error("x"),
      "GET /api/governments/group-aggregate?group=g7&indicator=i": new Error("x") });
    await h.fns.loadGovAggregate("EUU");
    h.$("gov-grp-pick").value = "g7"; h.$("gov-grp-ind").value = "i";
    await h.fns.renderGovGroup(false);
    h.switchTo("fr");
    assert.ok(has(h.$("gov-agg-body"), esc(FR["Could not load this aggregate."])), "the Aggregates failure line follows a switch");
    assert.ok(has(h.$("gov-grp-body"), esc(FR["Could not compute this group."])), "the Groups failure line follows a switch");
  }

  // 3. Countries with an empty store, and the Law pointer: the empty line, the pointer's words and its hover.
  {
    const h = harness({
      "GET /api/law/status": { documents: 23, tracked: 0, changes: 4 },
      "GET /api/governments/map?indicator=SP.POP.TOTL": { by_country: [] },
      "GET /api/governments/map?indicator=NY.GDP.MKTP.CD": { by_country: [] },
    });
    await h.fns.loadGovCountries(); await tick();
    h.switchTo("fr");
    const empty = "Country data loads automatically in the background when online — or use “Load standard country data” to fetch it now.";
    assert.ok(has(h.$("gov-country-data"), esc(FR[empty])), "the empty Countries line follows a switch");
    const ptr = h.$("gov-law-pointer");
    const frame = FR["Law: {documents} tracked · {baselined} baselined · {changes} changes"];
    assert.ok(frame && frame.includes("{documents}"));
    assert.ok(has(ptr, esc("⚖ " + frame.replace("{documents}", "23").replace("{baselined}", "0").replace("{changes}", "4"))),
      "the pointer's words follow a switch: " + ptr.innerHTML);
    assert.strictEqual(ptr.title, FR["Open the Law subtab — change tracking for statutes, gazettes and IP records."],
      "the pointer's hover follows a switch");
    assert.ok(ptr.hasAttribute("data-i18n-dyn"), "the pointer is marked, so the walker leaves the hover to the render");
  }

  // 4. The map: "Latest available" follows a switch and the year the reader picked stays picked; an empty map's line
  //    follows a switch.
  {
    const h = harness({ "GET /api/governments/map?indicator=SP.POP.TOTL": { years: ["2019", "2020"], by_country: [{ country: "FRA" }] } });
    h.$("gov-map-ind").value = "SP.POP.TOTL";
    await h.fns.loadGovMap();
    const ysel = h.$("gov-map-year");
    assert.ok(ysel.innerHTML.includes('<option value="" selected>Latest available</option>'), ysel.innerHTML);
    ysel.value = "2020";
    h.switchTo("fr");
    assert.ok(ysel.innerHTML.includes(`<option value="">${esc(FR["Latest available"])}</option>`), "the first option follows a switch");
    assert.ok(ysel.innerHTML.includes('<option value="2020" selected>2020</option>'), "the picked year stays picked: " + ysel.innerHTML);
    const h2 = harness({ "GET /api/governments/map?indicator=X": { by_country: [] } });
    h2.$("gov-map-ind").value = "X";
    await h2.fns.loadGovMap();
    h2.switchTo("de");
    assert.ok(has(h2.$("gov-map-host"),
      esc(DE["Country data loads automatically in the background when online — the map fills in once it lands."])),
      "the empty map line follows a switch");
  }

  // 5. Load standard country data: consent first; the busy words and the progress follow a switch; the label comes back.
  {
    let progress = null, finish = null;
    const h = harness({ "POST /api/governments/load-standard": { started: true }, "GET /api/law/status": new Error("x"),
      "GET /api/governments/map?indicator=SP.POP.TOTL": { by_country: [] }, "GET /api/governments/map?indicator=NY.GDP.MKTP.CD": { by_country: [] } },
    { pollJobStatus: (url, o) => { progress = o.onProgress; return new Promise((r) => { finish = r; }); } });
    const btn = button("Load standard country data");
    const p = h.fns.govLoadStandard(btn);
    await tick();
    assert.strictEqual(h.calls[0], "consent", "the consent comes before any request");
    h.switchTo("fr");
    assert.strictEqual(btn.textContent, FR["Loading…"], "the busy word follows a switch");
    progress({ done: 3, total: 10 });
    h.switchTo("de");
    const de = DE["Loading… {done} of {total}"].replace("{done}", "3").replace("{total}", "10");
    assert.strictEqual(btn.textContent, de, "the progress follows a switch");
    assert.strictEqual(btn.disabled, true);
    finish({ state: "done", result: { stored: 2 } }); await p;
    assert.strictEqual(btn.textContent, "Load standard country data", "the button's own label comes back");
    assert.strictEqual(btn.disabled, false);
    h.switchTo("fr");
    assert.strictEqual(btn.textContent, "Load standard country data", "a released button is the walker's again, not the hold's");
  }

  // 6. Summarize this change: the busy word follows a switch; a failure gives the button its label back.
  {
    const h = harness({ "POST /api/law/revisions/7/summarize": "hold" });
    const btn = button("Summarize this change");
    const p = h.fns.lawSummarize(7, btn);
    h.switchTo("fr");
    assert.strictEqual(btn.textContent, FR["Summarizing locally…"], "the busy word follows a switch");
    h.held[0].reject(new Error("x")); await p;
    assert.strictEqual(btn.textContent, "Summarize this change");
    assert.strictEqual(btn.disabled, false);
  }

  // 7. Add & track: the required line, the busy word and the result line (its robots words included) follow a switch.
  {
    const h = harness({ "POST /api/law/documents": "hold" });
    await h.fns.lawAddDocument(button("Add & track"));
    h.switchTo("fr");
    assert.strictEqual(h.$("law-add-msg").textContent, FR["Jurisdiction, title and URL are all required."],
      "the required line follows a switch");
    assert.ok(!h.calls.includes("consent"), "nothing is asked before the form is complete");
    h.switchTo("en");
    h.$("law-add-jur").value = "FR"; h.$("law-add-title").value = "Code"; h.$("law-add-url").value = "https://e.org/a";
    const btn = button("Add & track");
    const p = h.fns.lawAddDocument(btn);
    await tick();
    assert.deepStrictEqual(h.calls.slice(0, 2), ["consent", "POST /api/law/documents"], "the consent comes before the request");
    h.switchTo("fr");
    assert.strictEqual(btn.textContent, FR["Adding & tracking…"], "the busy word follows a switch");
    h.held[0].resolve({ track_result: { robots: "blocked", status: "x" } }); await p;
    assert.strictEqual(btn.textContent, "Add & track", "the button's own label comes back");
    h.switchTo("de");
    assert.strictEqual(h.$("law-add-msg").textContent,
      `${DE["Added."]} ${DE["Status:"]} ${DE["blocked by the site's robots.txt"]}`, "the result line follows a switch");
  }

  const own = (loc, name, keys) => keys.forEach((k) => assert.ok(loc[k] && loc[k] !== k, name + " has its own words for " + k));
  own(FR, "fr", ["Could not load these countries.", "Could not load this aggregate.", "Could not compute this group.",
    "Latest available", "Summarizing locally…", "Adding & tracking…", "Jurisdiction, title and URL are all required."]);
  own(DE, "de", ["Loading… {done} of {total}", "Added.", "blocked by the site's robots.txt",
    "Country data loads automatically in the background when online — the map fills in once it lands."]);
  console.log("govlaw_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
