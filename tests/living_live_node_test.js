// Living sources follows a language switch (row 367, app-living.js), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Seven renderers in app-living.js wrote t() output into ordinary nodes. Every loading and failure line of the Living
// views is now held (the stream, a diff, the Law changes and evolution panels, the pages, the searches, the
// cross-edition compare), the overview's failure line and a diff's Show/Hide button too. The cached-view repaint of the
// cross-edition compare no longer blanks a loading or failure line it has no answer for.
//
// The functions are EXTRACTED from the shipped app-living.js with the shipped ooLive family; t()/tf() are the shipped
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
const frame = (s, v) => String(s).replace(/\{(\w+)\}/g, (m, k) => (k in v ? String(v[k]) : m));

class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
// A small element: markup written into it makes a child element for every tag with a class, found again by
// querySelector(".cls"); those children leave the page when the markup is replaced. Its text is the markup's text.
class El {
  constructor(tag, cls) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this._connected = true; this._kids = []; this.cls = cls || []; this.title = ""; this.value = ""; this.disabled = false;
    this.hidden = false; this.style = {};
  }
  get isConnected() { return this._connected; }
  hasAttribute(a) { return Object.prototype.hasOwnProperty.call(this.attrs, a); }
  getAttribute(a) { return this.hasAttribute(a) ? this.attrs[a] : null; }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  removeAttribute(a) { delete this.attrs[a]; }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = nodes; this._html = null;
    for (const c of nodes) c.parentNode = this;
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this._drop(); this.replaceChildren(...(v === "" ? [] : [new Text(String(v))])); }
  get innerHTML() { return this._html != null ? this._html : this.textContent; }
  set innerHTML(v) {
    const html = String(v);
    this._drop();
    this.replaceChildren(...(html === "" ? [] : [new Text(html.replace(/<[^>]*>/g, ""))])); this._html = html;
    for (const m of html.matchAll(/<(\w+)([^>]*)>/g)) {
      const cl = /\bclass="([^"]+)"/.exec(m[2]);
      if (cl) this._kids.push(new El(m[1].toUpperCase(), cl[1].split(/\s+/)));
    }
  }
  _drop() { for (const k of this._kids) k._connected = false; this._kids = []; }
  querySelector(sel) { const c = sel.replace(/^\./, ""); return this._kids.find((k) => k.isConnected && k.cls.includes(c)) || null; }
}

const CORE = ["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml",
  "ooLiveRepaint"];
const FNS = ["_livingT", "_livingTf", "_livingFailHtml", "loadLivingOverview", "loadLivingStream", "livingShowDiff", "loadLivingLaw",
  "loadLivingPages", "lawPitSearch", "lawTopicCompare", "renderWikiDivergence", "loadWikiDivergence", "renderWikiAttention",
  "loadWikiAttention", "repaintWikiCompareFromCache", "loadLawWeek", "loadLivingLawDocs", "loadLawFloor", "loadLawThesauri",
  "loadLawVelocity", "loadLawAmendMap", "loadLivingMaps"];
const PANELS = [["loadLawWeek", "living-law-week"], ["loadLivingLawDocs", "living-law-docs"], ["loadLawFloor", "living-law-floor"],
  ["loadLawThesauri", "law-thesauri"], ["loadLawVelocity", "law-velocity"], ["loadLawAmendMap", "law-amend-map"],
  ["loadLivingMaps", "living-osm-regions"]];
const IDS = ["living-status", "living-stream", "living-diff-42", "living-law-changes", "living-pages", "law-pit-results", "law-pit-q",
  "law-pit-on", "law-topic-results", "law-topic-q", "wiki-div-cands", "wiki-div-result", "wiki-att-tools", "wiki-att-result",
  ...PANELS.map((x) => x[1])];

function harness(answers) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  for (const id of IDS) nodes[id] = new El("DIV");
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
    "let _livingOverview = null, _livingStreamOffset = 0, _livingStreamLast = null, _livingLawLast = null, _livingPagesLast = null;",
    "let _lawPitLast = null, _lawTopicLast = null, _wikiDivLast = null, _wikiDivCands = null, _wikiAttLast = null;",
    "let _lawWeekLast = null, _lawDocsLast = null, _lawFloorLast = null, _lawThesauriLast = null, _lawVelocityLast = null;",
    "let _lawMapLast = null, _livingMapsLast = null;",
    "const _LIVING_STREAM_PAGE = 50; const _livingDiffs = new Map(); const _WIKI_LANE_STATES = {};",
    ...CORE.map(extract), ...FNS.map(extract),
    "return { fns: {" + FNS.join(",") + ", ooLiveRepaint} };",
  ].join("\n");
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console, esc, $: (id) => nodes[id] || null, api,
    ooLabelText: (a, b) => a + ": " + b, renderLivingOverview() {}, renderLivingStream() {}, _livingStreamCap() {},
    livingStreamRowsHtml: () => "<div>ROWS</div>", livingDiffBoxHtml: () => "<div>DIFF</div>", renderLivingLaw() {},
    renderLivingPages() {}, renderLawPit() {}, renderLawTopic() {}, _wikiCompareWire() {},
    wikiDivCandidatesHtml: () => "", wikiDivergenceHtml: () => "<div>DIV</div>", wikiAttentionHtml: () => "<div>ATT</div>",
    ooLangCode: (e) => e, renderLawWeek() {}, renderLivingLawDocs() {}, renderLawFloor() {}, renderLawThesauri() {},
    renderLawVelocity() {}, renderLawAmendMap: async () => {}, renderLivingMaps() {},
  };
  const out = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns: out.fns, nodes, held, calls, $: (id) => nodes[id],
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      out.fns.ooLiveRepaint();                 // app-boot's ONE oo:langchange listener: every held node first,
      out.fns.repaintWikiCompareFromCache();   // then the cached Living views (repaintLivingFromCache's compare part)
    },
  };
}
const has = (el, s) => el.innerHTML.includes(s) || el.textContent.includes(s);
const fail = (loc, why) => esc(loc["Could not load"] + ": " + why);
const button = (label) => { const b = new El("BUTTON"); b.textContent = label; return b; };

(async () => {
  // 1. The overview's failure line, the stream's loading and failure lines, the Law changes' and the pages' failure lines.
  {
    const h = harness({ "GET /api/living/overview": new Error("gone"), "GET /api/wiki/lane/changes?limit=50&offset=0": "hold",
      "GET /api/law/changes?limit=50": new Error("gone"), "GET /api/wiki/pages": new Error("gone") });
    await h.fns.loadLivingOverview();
    const p = h.fns.loadLivingStream(false);
    await h.fns.loadLivingLaw();
    await h.fns.loadLivingPages();
    h.switchTo("fr");
    assert.strictEqual(h.$("living-status").textContent, FR["Could not load"] + ": gone", "the overview's failure follows a switch");
    assert.ok(has(h.$("living-stream"), esc(FR["Loading…"])), "the stream's loading line follows a switch");
    assert.ok(has(h.$("living-law-changes"), fail(FR, "gone")), "the Law changes' failure follows a switch");
    assert.ok(has(h.$("living-pages"), fail(FR, "gone")), "the pages' failure follows a switch");
    h.held[0].reject(new Error("later")); await p;
    h.switchTo("de");
    assert.ok(has(h.$("living-stream"), fail(DE, "later")), "the stream's failure follows a switch");
  }

  // 2. A diff: its loading line and its button follow a switch; a closed diff's button says Show diff.
  {
    const h = harness({ "GET /api/wiki/lane/revisions/42": "hold" });
    const btn = button("Show diff");
    const p = h.fns.livingShowDiff(42, btn);
    h.switchTo("fr");
    assert.ok(has(h.$("living-diff-42"), esc(FR["Loading…"])), "the diff's loading line follows a switch");
    h.held[0].resolve({}); await p;
    h.switchTo("de");
    assert.strictEqual(btn.textContent, DE["Hide diff"], "the open diff's button follows a switch");
    assert.strictEqual(h.$("living-diff-42").innerHTML, "<div>DIFF</div>", "the drawn diff is not redrawn by the old hold");
    await h.fns.livingShowDiff(42, btn);
    h.switchTo("fr");
    assert.strictEqual(btn.textContent, FR["Show diff"], "the closed diff's button follows a switch");
  }

  // 3. The point-in-time and topic searches: the prompt, the loading line and the failure follow a switch.
  {
    const h = harness({ "GET /api/law/versions/search?q=water": "hold", "GET /api/law/topics?q=water": new Error("gone") });
    await h.fns.lawPitSearch();
    h.switchTo("fr");
    assert.ok(has(h.$("law-pit-results"), esc(FR["Type the words to find."])), "the prompt follows a switch");
    h.$("law-pit-q").value = "water"; h.$("law-topic-q").value = "water";
    const p = h.fns.lawPitSearch();
    await h.fns.lawTopicCompare();
    h.switchTo("de");
    assert.ok(has(h.$("law-pit-results"), esc(DE["Loading…"])), "the search's loading line follows a switch");
    assert.ok(has(h.$("law-topic-results"), fail(DE, "gone")), "the topic search's failure follows a switch");
    h.held[0].reject(new Error("x")); await p;
    h.switchTo("fr");
    assert.ok(has(h.$("law-pit-results"), fail(FR, "x")), "the search's failure follows a switch");
  }

  // 4. Cross-edition compare: a loading or failure line is not blanked by the cached-view repaint; a result still is drawn.
  {
    const h = harness({ "GET /api/wiki/lane/attention": "hold", "GET /api/wiki/lane/divergence": new Error("gone") });
    const p = h.fns.loadWikiAttention("", true);
    await h.fns.loadWikiDivergence("");
    h.switchTo("fr");
    assert.ok(has(h.$("wiki-att-result"), esc(FR["Loading…"])), "the attention loading line survives and follows a switch");
    assert.ok(has(h.$("wiki-div-result"), fail(FR, "gone")), "the divergence failure survives and follows a switch");
    h.held[0].resolve({}); await p;
    h.switchTo("de");
    assert.strictEqual(h.$("wiki-att-result").innerHTML, "<div>ATT</div>", "a result is drawn by the cached-view repaint");
  }

  // 5. Every other Living panel's failure line, a diff's failure, the Law changes' loading line, the topic search's prompt
  //    and loading line, and the attention failure follow a switch (no answer is canned, so every read fails).
  {
    const h = harness({ "GET /api/law/changes?limit=50": "hold", "GET /api/law/topics?q=water": "hold" });
    for (const [fn] of PANELS) await h.fns[fn]();
    await h.fns.livingShowDiff(42, null);
    const law = h.fns.loadLivingLaw();
    await h.fns.lawTopicCompare();
    h.switchTo("fr");
    assert.ok(has(h.$("law-topic-results"), esc(FR["Type the words to find."])), "the topic prompt follows a switch");
    h.$("law-topic-q").value = "water";
    const topic = h.fns.lawTopicCompare();
    await h.fns.loadWikiAttention("", true);
    h.switchTo("de");
    for (const [fn, id] of PANELS) assert.ok(has(h.$(id), esc(DE["Could not load"])), fn + "'s failure follows a switch: " + h.$(id).innerHTML);
    assert.ok(has(h.$("living-diff-42"), esc(DE["Could not load"])), "a diff's failure follows a switch");
    assert.ok(has(h.$("living-law-changes"), esc(DE["Loading…"])), "the Law changes' loading line follows a switch");
    assert.ok(has(h.$("law-topic-results"), esc(DE["Loading…"])), "the topic search's loading line follows a switch");
    assert.ok(has(h.$("wiki-att-result"), esc(DE["Could not load"])), "the attention failure follows a switch");
    h.held.forEach((x) => x.reject(new Error("x"))); await law; await topic;
  }

  const own = (loc, name, keys) => keys.forEach((k) => assert.ok(loc[k] && loc[k] !== k, name + " has its own words for " + k));
  own(FR, "fr", ["Could not load", "Loading…", "Type the words to find.", "Show diff"]);
  own(DE, "de", ["Hide diff", "Could not load", "Loading…"]);
  console.log("living_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
