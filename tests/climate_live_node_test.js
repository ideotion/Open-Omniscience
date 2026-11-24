// The Climate tab follows a language switch (row 367, app-climate.js), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The tab was written once with t() output into ordinary nodes, so it stayed in the language that was active when it
// was drawn. It now draws through ooLive/ooLiveHtml from what it holds: a view is built bare once per read and its parts
// are held one by one, so a switch redraws the text, the status line, the place form and its result, and the charts
// (from the points they were drawn with) with no request, and a field the operator typed in keeps what was typed.
//
// The WHOLE shipped app-climate.js is run, with the shipped ooLive family and text helpers EXTRACTED from the engine;
// t()/tf() are the shipped i18n engine over the shipped locales. Only the network and the chart canvas are stubbed.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

const CLIMATE_JS = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-climate.js"), "utf-8");

function extract(name) {
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  const at = APP.slice(at0 - 6, at0) === "async " ? at0 - 6 : at0;
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
  return APP.slice(at, j);
}
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));
const FR = locale("fr"), DE = locale("de");
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&#39;/g, "'").replace(/&amp;/g, "&");

class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
let REGISTRY = null;
class El {
  constructor(tag) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this.style = {}; this.value = ""; this._connected = true;
  }
  get isConnected() { return this._connected; }
  hasAttribute(a) { return Object.prototype.hasOwnProperty.call(this.attrs, a); }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  removeAttribute(a) { delete this.attrs[a]; }
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
    // the elements this markup held are gone from the page, and so is every element under them
    REGISTRY.detach(this);
    this.replaceChildren(new Text(html)); this._html = html;
    // every element with an id is a new node; an input takes its value from its value attribute, as a browser does
    for (const m of html.matchAll(/<(\w+)([^>]*)>/g)) {
      const id = /\bid="([^"]+)"/.exec(m[2]);
      if (!id) continue;
      const el = REGISTRY.fresh(id[1], this);
      const val = /\bvalue="([^"]*)"/.exec(m[2]);
      if (val) el.value = decode(val[1]);
    }
  }
  addEventListener() {}
}

const CORE = ["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml",
  "ooLiveRepaint", "ooLabelText", "_ltrIsolate", "ooLtrIsolate", "fmtNum", "ooRoundPlace", "ooIsoDateTime"];

function harness(answers, opts = {}) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  const owner = new Map();   // node -> the element whose markup created it
  REGISTRY = {
    fresh(id, parent) {
      if (nodes[id]) nodes[id]._connected = false;
      const el = new El("DIV"); nodes[id] = el; owner.set(el, parent); return el;
    },
    detach(parent) {
      const gone = [];
      for (const [el, p] of owner) {
        let up = p;
        while (up) { if (up === parent) { gone.push(el); break; } up = owner.get(up); }
      }
      for (const el of gone) { el._connected = false; owner.delete(el); }
    },
  };
  for (const id of ["climate-body", "climate-status"]) nodes[id] = new El("DIV");
  const calls = { api: [], charts: [], consent: [] };
  const api = async (url, o) => {
    const key = ((o && o.method) || "GET") + " " + url;
    calls.api.push(key);
    let a = answers[key] !== undefined ? answers[key] : answers[url];
    if (typeof a === "function") a = a(o);
    a = await a;
    if (a instanceof Error) throw a;
    if (a === undefined) throw new Error("unexpected call " + key);
    return a;
  };
  const store = {};
  const src = [
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    extractConst("esc"), extractConst("_LTR_ISOLATE"),
    ...CORE.map(extract),
    CLIMATE_JS,
    "return { showClimateView, renderClimate, renderClimatePlace, climatePlaceShow, climateFetch, climateChartsRepaint," +
    " ooLiveRepaint, loadClimateUnits, pick: _climatePick };",
  ].join("\n");
  const document = { createElement: (tag) => new El(tag.toUpperCase()), documentElement: { dir: "ltr" } };
  const window = { OOI18N };
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console,
    $: (id) => nodes[id] || null, api,
    // the chart draws the labels it is handed; the canvas is not what is tested here
    ooChart: (el, series) => calls.charts.push({ el, labels: series.map((s) => s.label + " [" + s.unit + "]"), n: series.map((s) => s.points.length) }),
    ooSubtabs: () => ({ select() {} }),
    ensureOnline: async (what) => { calls.consent.push(what); return opts.consent !== false; },
    ooAskToSendPlace: async () => { calls.consent.push("place"); return opts.consent !== false; },
    pollJobStatus: async () => opts.job || { state: "done", result: {} },
    _jobStillRunning: (j) => j.state === "running",
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = String(v); } },
  };
  const fns = new Function(...Object.keys(env), src)(...Object.values(env));
  if (opts.saved) store["oo.climate.place"] = JSON.stringify(opts.saved);
  return {
    fns, nodes, calls, $: (id) => nodes[id],
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      // app-boot's ONE oo:langchange listener: the charts first, then every held node
      fns.climateChartsRepaint();
      fns.ooLiveRepaint();
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));
const settle = async () => { for (let i = 0; i < 10; i++) await tick(); };

const GISTEMP = {
  dataset: "gistemp", param: "GLB", host: "data.giss.nasa.gov", area: "",
  stored: { stored_rows: 12, last_fetched_at: "2026-11-01T10:00:00Z" },
  charts: [[{ series_id: "gistemp.monthly", unit: "degC" }]],
};
const SERIES = { points: [["2026-01", 1.1], ["2026-02", 1.2]], n: 2, gaps: 0, first: "2026-01", last: "2026-02" };
const answersFor = (units) => ({
  "/api/climate/datasets": { units, hosts: { gistemp: "data.giss.nasa.gov", ghcnd: "www.ncei.noaa.gov" } },
  "POST /api/climate/fetch": { started: true },
  "/api/climate/series?dataset=gistemp&series_id=gistemp.monthly&area=&param=GLB": SERIES,
});

(async () => {
  // 1. A dataset view: its title, caveat and buttons, the chart's legend and the note under it follow a switch, from
  //    what was read; the switch sends no request.
  {
    const h = harness(answersFor([GISTEMP]));
    h.fns.showClimateView("gistemp");
    await settle();
    const main = h.$("climate-main");
    assert.ok(main.innerHTML.includes("<h3 class=\"lib-sub\">"), main.innerHTML);
    assert.strictEqual(h.calls.charts.length, 1, "one chart drawn: " + JSON.stringify(h.calls.charts));
    assert.ok(h.calls.charts[0].labels[0].startsWith("Monthly anomaly"), h.calls.charts[0].labels[0]);
    const note = h.$("climate-note-0");
    assert.ok(note.textContent.startsWith("Monthly anomaly: n = 2 values"), note.textContent);
    const enMain = main.innerHTML, sent = h.calls.api.length;
    h.switchTo("fr");
    assert.notStrictEqual(main.innerHTML, enMain, "the view's text follows a switch");
    assert.ok(main.innerHTML.includes(esc(FR["Global"])), "the parameter buttons are translated: " + main.innerHTML);
    assert.strictEqual(h.calls.charts.length, 2, "the chart is drawn again on a switch");
    assert.ok(h.calls.charts[1].labels[0].startsWith(FR["Monthly anomaly"]), "the legend follows a switch: " + h.calls.charts[1].labels[0]);
    assert.deepStrictEqual(h.calls.charts[1].n, [2], "from the points it was drawn with");
    assert.ok(note.textContent.startsWith(FR["Monthly anomaly"] + ": n = 2 "), "the note follows a switch: " + note.textContent);
    assert.strictEqual(h.calls.api.length, sent, "a switch sends no request");
    // another view replaces the chart: the old one is not drawn again
    h.fns.renderClimate();
    await settle();
    const drawn = h.calls.charts.length;
    h.switchTo("de");
    assert.strictEqual(h.calls.charts.length, drawn + 1, "only the chart on screen is drawn again");
    // a view with no chart (the place form) replaces it: a switch draws no chart at all
    h.fns.showClimateView("place");
    await settle();
    const before = h.calls.charts.length;
    h.switchTo("fr");
    assert.strictEqual(h.calls.charts.length, before, "a chart no longer on the page is not drawn again");
  }

  // 2. The station field keeps what the operator typed through a switch; a new read draws it empty.
  {
    const h = harness(answersFor([]));
    h.fns.showClimateView("ghcnd");
    await settle();
    assert.strictEqual(h.$("climate-station").value, "");
    h.$("climate-station").value = "USW00094728";
    h.switchTo("fr");
    assert.strictEqual(h.$("climate-station").value, "USW00094728", "typed text survives a switch");
    assert.ok(h.$("climate-main").innerHTML.includes(esc(FR["Station id"])), h.$("climate-main").innerHTML);
    h.fns.renderClimate();
    assert.strictEqual(h.$("climate-station").value, "", "a new draw starts from the stored value");
  }

  // 3. The fetch status line follows a switch: a refused station id (before any consent), then a finished fetch.
  {
    const h = harness(answersFor([GISTEMP]), { job: { state: "done", result: { figures: 5, tally: { new: 3, revised: 1, unchanged: 1 } } } });
    h.fns.showClimateView("gistemp");
    await settle();
    const st = h.$("climate-status");
    await h.fns.climateFetch("ghcnd", "bad");
    assert.strictEqual(h.calls.consent.length, 0, "a bad station id never reaches the consent");
    assert.ok(st.textContent.startsWith("A GHCN station id is 11 characters"), st.textContent);
    h.switchTo("fr");
    assert.strictEqual(st.textContent, FR["A GHCN station id is 11 characters: two letters, then nine letters or digits (for example USW00094728)."]);
    await h.fns.climateFetch("gistemp", "GLB");
    await settle();
    assert.strictEqual(h.calls.consent.length, 1, "the fetch asked the one consent");
    const want = (L) => L["Fetched {n} values: {new} new, {revised} revised, {unchanged} unchanged."]
      .replace("{n}", "5").replace("{new}", "3").replace("{revised}", "1").replace("{unchanged}", "1");
    assert.strictEqual(st.textContent, want(FR));
    h.switchTo("de");
    assert.strictEqual(st.textContent, want(DE), "the tally follows a switch");
  }
  {
    // a declined consent sends nothing and draws nothing
    const h = harness(answersFor([GISTEMP]), { consent: false });
    h.fns.showClimateView("gistemp");
    await settle();
    const n = h.calls.api.length;
    await h.fns.climateFetch("gistemp", "GLB");
    assert.strictEqual(h.calls.api.length, n, "no request without consent");
    assert.strictEqual(h.$("climate-status").textContent, "");
  }

  // 4. "Your place": the form keeps typed values through a switch, the held result is not wiped by it and follows it,
  //    and the status line under it follows it too.
  {
    const held = {
      held: true, license: "CC BY 4.0", provenance: {},
      results: [{ variable: "precipitation_sum", kind: "ratio", value: 80, unit: "mm", window_value: 40, baseline_value: 50, years_used: 30 }],
    };
    const answers = {};
    answers[`/api/weather/anomaly/held?lat=48.9&lon=2.4&start_date=2026-10-01&end_date=2026-10-30`] = held;
    answers[`/api/weather/anomaly/held?lat=50.1&lon=2.4&start_date=2026-10-01&end_date=2026-10-30`] = { held: false };
    answers["POST /api/weather/anomaly"] = Object.assign({}, held, { held: false });
    const h = harness(answers, { saved: { lat: 48.9, lon: 2.4, start: "2026-10-01", end: "2026-10-30" } });
    h.fns.showClimateView("place");
    await settle();
    const out = h.$("climate-place-out"), form = h.$("climate-place-form");
    assert.ok(out.innerHTML.includes("<th>Measure</th>"), "the held result is drawn: " + out.innerHTML);
    assert.strictEqual(h.$("climate-place-lat").value, "48.9");
    h.$("climate-place-lat").value = "50.12";
    h.switchTo("fr");
    assert.strictEqual(h.$("climate-place-lat").value, "50.12", "typed latitude survives a switch");
    assert.ok(form.innerHTML.includes(">" + esc(FR["Show"]) + "</button>"), form.innerHTML);
    assert.ok(out.innerHTML.includes("<th>" + esc(FR["Measure"]) + "</th>"), "the result is kept and follows a switch: " + out.innerHTML);
    await h.fns.climatePlaceShow(false, false);
    assert.strictEqual(h.calls.consent.length, 1, "a new place asks first");
    // the same place again, read from this machine
    h.$("climate-place-lat").value = "48.9";
    await h.fns.climatePlaceShow(false, false);
    assert.strictEqual(h.$("climate-status").textContent, FR["Read from this machine; nothing was sent."]);
    h.switchTo("de");
    assert.strictEqual(h.$("climate-status").textContent, DE["Read from this machine; nothing was sent."]);
    // a refused query: the sentence follows a switch
    h.$("climate-place-lat").value = "";
    await h.fns.climatePlaceShow(false, false);
    h.switchTo("fr");
    assert.strictEqual(h.$("climate-status").textContent, FR["Type a latitude and a longitude in decimal degrees, for example 48.85 and 2.35."]);
  }

  console.log("climate_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
