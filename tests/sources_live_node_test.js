// The Sources section follows a language switch (row 367, app-sources.js), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Eight renderers in app-sources.js wrote t() output into ordinary nodes, so their words stayed in the language that was
// active when they were drawn. Now the filter summaries ("Any", "N selected"), the AI check (its button and its result
// line), the source trail panel, the import's unreadable-country sentence, the single and batch feed results (their
// hovers and the batch table), the batch picker's empty and capped lines and the retired-mode notice are held. A panel the
// reader opened something inside, or a list drawn over a held line, is let go rather than redrawn.
//
// The functions are EXTRACTED from the shipped app-sources.js with the shipped ooLive family; t()/tf() are the shipped
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
// The text of markup: tags removed until none is left (one pass can leave a tag that two halves made).
function stripTags(html) {
  let h = String(html), prev;
  do { prev = h; h = h.replace(/<[^>]*>/g, ""); } while (h !== prev);
  return h;
}
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
    this.replaceChildren(...(html === "" ? [] : [new Text(stripTags(html))])); this._html = html;
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
const FNS = ["updateMselSummary", "qualifyAssist", "toggleSourceTrail", "importSources", "tally", "tallyHover",
  "_srcAirplaneNothing", "_srcFeedResultLine", "_srcBatchResultLine", "_srcTrailToggleClass", "ingestSource", "renderBatchPicker", "batchIngestStatusWords", "ingestBatch", "renderRetiredMode"];
const IDS = ["imp-result", "ingest-result", "ing-source", "bi-list", "bi-count", "bi-capped", "bi-status", "bi-results",
  "sch-retired", "sch-retired-text"];

function harness(answers, extra) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  for (const id of IDS) nodes[id] = new El("DIV");
  const held = [], calls = [], toasts = [];
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
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;", "const _srcTrailData = {};",
    "const BI = { sources: [], selected: new Set(), capped: false, failed: false };",
    "function _biFiltered() { return BI.sources; }",
    ...CORE.map(extract), ...FNS.map(extract),
    "return { fns: {" + FNS.join(",") + ", ooLiveRepaint}, BI };",
  ].join("\n");
  const env = Object.assign({
    window, OOI18N, document, MutationObserver: undefined, console, esc, $: (id) => nodes[id] || null, api,
    // No global tf here, as on the page: importSources must bring its own.
    toast: (m, k) => toasts.push([m, k || "ok"]), fmtNum: (x) => String(x),
    mselValues: () => [], ooCountryCode: (c) => c.toUpperCase(), ooLangCode: (c) => c,
    _srcTrailHtml: () => `<div class="trail">${esc(OOI18N.t("Discovery"))}</div>`, srcIpsHtml: () => "",
    _apiErrorMessage: (e) => String(e), _failMsg: (s) => s, doSearch() {}, loadManagedSources() {}, loadSources() {},
    loadDbStats() {}, loadCoverage() {}, ooLangName: (x) => x, ooRegionName: (x) => x, ooSourceName: (s) => ({ label: s.name }),
    ooLabelHtml: (a, b) => a + " " + b, fetch: async () => ({ ok: true, json: async () => ({}) }),
  }, extra || {});
  const out = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns: out.fns, BI: out.BI, nodes, held, calls, toasts, $: (id) => nodes[id],
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
  // 1. A filter's summary: "Any" and "N selected" follow a switch; a single value stays the code.
  {
    const vals = { "src-msel-tag": [], "src-msel-country": ["fr", "de"], "src-msel-language": ["fr"] };
    const dets = {};
    for (const id of Object.keys(vals)) {
      const sum = new El("SUMMARY"); sum.textContent = "Any";
      dets[id] = { querySelector: (sel) => (sel === "summary" ? sum : null), sum };
    }
    const h = harness({}, { $: (id) => dets[id] || null, mselValues: (id) => vals[id] });
    Object.keys(vals).forEach(h.fns.updateMselSummary);
    h.switchTo("fr");
    assert.strictEqual(dets["src-msel-tag"].sum.textContent, FR["Any"], "'Any' follows a switch");
    assert.strictEqual(dets["src-msel-country"].sum.textContent, "2 " + FR["selected"], "'N selected' follows a switch");
    assert.strictEqual(dets["src-msel-language"].sum.textContent, "fr", "a single value is shown as its code");
  }

  // 2. The AI check: the busy word, the result line (its canary warning first) and the button's own label follow a switch.
  {
    const h = harness({ "POST /api/diagnostics/qualification-assist/run": "hold" });
    const row = new El("TR"); row.style.display = "none"; row.firstElementChild = new El("TD");
    h.nodes["src-trail-5"] = row;
    const btn = button("AI check");
    const p = h.fns.qualifyAssist(5, btn);
    h.switchTo("fr");
    assert.strictEqual(btn.textContent, FR["Checking…"], "the busy word follows a switch");
    h.held[0].resolve({ checked: 3, article_count: 2, junk_count: 1, unparseable_count: 0, canary: { ok: false } }); await p;
    h.switchTo("de");
    const cell = row.firstElementChild;
    assert.ok(has(cell, esc(DE["The canary check FAILED — treat this run's numbers as unreliable."])), "the canary warning follows a switch");
    const line = frame(DE["AI check: {checked} checked — {articles} read as articles, {junk} as navigation soup, {unreadable} unreadable — a proposal only; nothing about this source was changed."],
      { checked: 3, articles: 2, junk: 1, unreadable: 0 });
    assert.ok(has(cell, esc(line)), "the result line follows a switch: " + cell.innerHTML);
    assert.strictEqual(btn.textContent, DE["AI check"], "the button's label follows a switch");
    assert.strictEqual(btn.disabled, false);
  }

  // 3. The source trail: the loading line and the panel follow a switch; a drill list opened inside lets it go.
  {
    const h = harness({ "GET /api/sources/9/provenance": "hold",
      "GET /api/sources/9/citation-tally": { qualified: [{ domain: "x.org", sample_article_ids: [1] }] },
      "GET /api/sources/9/observed-ips": null });
    const row = new El("TR"); row.style.display = "none"; const cell = new El("TD");
    row.querySelector = () => cell;
    h.nodes["src-trail-9"] = row;
    const p = h.fns.toggleSourceTrail(9);
    h.switchTo("fr");
    assert.ok(has(cell, esc(FR["Loading…"])), "the trail's loading line follows a switch");
    h.held[0].resolve({}); await p;
    h.switchTo("de");
    assert.ok(has(cell, esc(DE["Discovery"])), "the trail panel follows a switch");
    cell.innerHTML = "<div>DRILL</div>";   // a drill list opened inside the panel changes its text
    h.switchTo("fr");
    assert.strictEqual(cell.innerHTML, "<div>DRILL</div>", "what the reader opened is not closed by a switch");
    // The drill list itself sits where the walker does not go: it is held, and its hover is keyed.
    const drill = new El("SPAN"); drill.style = {}; h.nodes["src-trail-cls-9"] = drill;
    h.fns._srcTrailToggleClass(9, "qualified");
    h.switchTo("de");
    assert.ok(has(drill, `title="${esc(DE["Open the articles that cite this domain"])}"`), "the drill's hover follows a switch: " + drill.innerHTML);
  }

  // 4. Import: the unreadable-country sentence follows a switch.
  {
    const h = harness({}, { fetch: async () => ({ ok: true,
      json: async () => ({ created: 1, updated: 0, skipped: 0, unreadable_country: { count: 2 } }) }) });
    h.nodes["imp-file"] = { files: [{ name: "x.csv" }] };
    await h.fns.importSources();
    const span = h.$("imp-result").querySelector(".imp-unread");
    assert.ok(span, "the sentence has its own node");
    h.switchTo("fr");
    const key = "{n} country value(s) in the sheet are not a country code or name: kept as typed, and a country already stored is never overwritten.";
    assert.strictEqual(span.textContent, frame(FR[key], { n: 2 }), "the sentence follows a switch");
  }

  // 5. One feed: the airplane refusal, and the result line with its hover, follow a switch.
  {
    const h = harness({ "POST /api/sources/7/ingest": { tally: { skipped_offline: 1 } } });
    h.$("ing-source").value = "7";
    await h.fns.ingestSource();
    h.switchTo("fr");
    const air = "Airplane mode is on: nothing was fetched. Click the plane in the top bar to go online, then try again.";
    assert.strictEqual(h.$("ingest-result").textContent, FR[air], "the airplane refusal follows a switch");
    const h2 = harness({ "POST /api/sources/7/ingest": { tally: { stored: 3, stopped_unwalked: 2 } } });
    h2.$("ing-source").value = "7";
    await h2.fns.ingestSource();
    h2.switchTo("de");
    const res = h2.$("ingest-result");
    assert.ok(res.textContent.startsWith(DE["Feed result —"]) && res.textContent.includes(DE["new articles stored"]),
      "the result line follows a switch: " + res.textContent);
    assert.ok(DE[Object.keys(DE).find((k) => k.startsWith("Stop was pressed while this feed"))] === res.title,
      "the hover follows a switch");
    assert.ok(res.hasAttribute("data-i18n-dyn"), "the line is marked, so the walker leaves its hover to the render");
  }

  // 6. The batch picker: the empty and failed lines, and the capped line, follow a switch; the cap is let go when gone.
  {
    const h = harness({});
    h.BI.failed = true;
    h.fns.renderBatchPicker();
    h.switchTo("fr");
    assert.ok(has(h.$("bi-list"), esc(FR["Could not load the source catalogue."])), "the failed line follows a switch");
    h.BI.failed = false; h.BI.sources = [{ id: 1, name: "A", rss_url: "https://a/" }]; h.BI.capped = true;
    h.fns.renderBatchPicker();
    h.switchTo("de");
    const capKey = "Showing the first {n} matching sources. Refine the filters to reach the rest of the catalogue.";
    assert.strictEqual(h.$("bi-capped").textContent, frame(DE[capKey], { n: 1 }), "the capped line follows a switch");
    assert.ok(!has(h.$("bi-list"), esc(DE["Could not load the source catalogue."])), "a list drawn over the held line is not redrawn");
    h.BI.capped = false;
    h.fns.renderBatchPicker();
    h.switchTo("fr");
    assert.strictEqual(h.$("bi-capped").textContent, "", "the capped line is let go when the cap is gone");
    assert.strictEqual(h.$("bi-capped").hidden, true);
  }

  // 7. The batch ingest: the busy line, the result line and its hover, and the table follow a switch.
  {
    const h = harness({ "POST /api/sources/ingest-batch": "hold" });
    h.BI.selected = new Set([1, 2]);
    const btn = button("Ingest");
    const p = h.fns.ingestBatch(btn);
    h.switchTo("fr");
    const busy = "Fetching feeds: {n}… (polite and rate-limited; this may take a while)";
    assert.strictEqual(h.$("bi-status").textContent, frame(FR[busy], { n: 2 }), "the busy line follows a switch");
    h.held[0].resolve({ ingested: 2, requested: 2, aggregate: { stored: 1, stopped_unwalked: 1 },
      results: [{ source: "A", status: "ok", tally: { stored: 1 } }, { source_id: 2, status: "no_feed" }] });
    await p;
    h.switchTo("de");
    const st = h.$("bi-status");
    assert.ok(st.textContent.startsWith(frame(DE["Done: {fetched} of {requested} fetched"], { fetched: 2, requested: 2 })),
      "the result line follows a switch: " + st.textContent);
    assert.ok(st.title && st.title !== "" && DE[Object.keys(DE).find((k) => k.startsWith("Stop was pressed while this feed"))] === st.title,
      "the hover follows a switch");
    const tbl = h.$("bi-results");
    assert.ok(has(tbl, esc(DE["Source"])) && has(tbl, esc(DE["Result"])) && has(tbl, esc(DE["No feed to fetch"])),
      "the table follows a switch: " + tbl.innerHTML);
    assert.ok(st.hasAttribute("data-i18n-dyn"), "the line is marked, so the walker leaves its hover to the render");
    assert.strictEqual(btn.disabled, false);
  }

  // 8. The retired-mode notice: the server's sentences, keyed, follow a switch.
  {
    const h = harness({});
    h.fns.renderRetiredMode({ retired: ["Any", "selected"] });
    h.switchTo("fr");
    assert.strictEqual(h.$("sch-retired-text").textContent, FR["Any"] + " " + FR["selected"], "the notice follows a switch");
    assert.strictEqual(h.$("sch-retired").hidden, false);
  }

  const own = (loc, name, keys) => keys.forEach((k) => assert.ok(loc[k] && loc[k] !== k, name + " has its own words for " + k));
  own(FR, "fr", ["Any", "selected", "Checking…", "Loading…", "Could not load the source catalogue."]);
  own(DE, "de", ["AI check", "Discovery", "Feed result —", "Source", "Result", "No feed to fetch"]);
  console.log("sources_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
