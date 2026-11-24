// Insights follows a language switch (row 367, app-insights.js), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Fifteen renderers wrote t() output into ordinary nodes, so their words stayed in the language that was active when
// they were drawn. Now the watches' message line and list states, the keyword explorer (its facets, its rows' buttons,
// a hidden keyword and the per-keyword tag editor, keeping what is being typed), the groups list and its basis chip,
// the two-tier concept browse (drawn again by repaintConceptBrowse), the ring gap and the ring-load status (with its
// hover), the convergences, the lunar screen and single test, and the citation scan line are held.
//
// The WHOLE shipped app-insights.js is run, with the shipped ooLive family EXTRACTED from the engine; t()/tf() are the
// shipped i18n engine over the shipped locales. Only the network and helpers from other files are stubs.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

const INSIGHTS_JS = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-insights.js"), "utf-8");

function extract(name) {
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
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
  return APP.slice(at0, j);
}
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));
const FR = locale("fr"), DE = locale("de");
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");

class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
// A small element: markup written into it makes a child element for every tag with an id or a class, found again by
// $(id), querySelector(".cls") and querySelectorAll(".cls"); those children leave the page when the markup is replaced.
class El {
  constructor(tag, cls) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this.style = {}; this.value = ""; this._connected = true; this._kids = []; this.cls = cls || [];
    this.listeners = {}; this.dataset = {}; this.disabled = false; this.title = "";
    this.classList = { add: (c) => { if (!this.cls.includes(c)) this.cls.push(c); }, toggle() {}, contains: (c) => this.cls.includes(c) };
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
    this.replaceChildren(new Text(html)); this._html = html;
    for (const m of html.matchAll(/<(\w+)([^>]*)>/g)) {
      const id = /\bid="([^"]+)"/.exec(m[2]), cl = /\bclass="([^"]+)"/.exec(m[2]);
      if (!id && !cl) continue;
      const el = new El(m[1].toUpperCase(), cl ? cl[1].split(/\s+/) : []);
      el.parentEl = this;
      for (const at of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) {
        el.attrs[at[1]] = at[2] == null ? "" : at[2];
        if (at[1].startsWith("data-")) el.dataset[at[1].slice(5).replace(/-(\w)/g, (_, c) => c.toUpperCase())] = at[2] == null ? "" : at[2];
      }
      this._kids.push(el);
      if (id) REGISTRY.fresh(id[1], el);
    }
  }
  _drop() { for (const k of this._kids) { k._connected = false; k._drop(); } this._kids = []; }
  _all() { return this._kids.flatMap((k) => [k, ...k._all()]); }
  closest(sel) { let n = this; const c = sel.replace(/^\./, ""); while (n) { if (n.cls && n.cls.includes(c)) return n; n = n.parentEl; } return null; }
  insertAdjacentElement(where, el) { this.after = el; }
  get nextElementSibling() { return this.after || null; }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) { const c = sel.replace(/^\./, ""); return this._all().filter((k) => k.isConnected && k.cls.includes(c)); }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  fire(ev, target) { (this.listeners[ev] || []).forEach((fn) => fn({ target: target || this, preventDefault() {} })); }
  focus() {}
  remove() { this._connected = false; }
  getElementsByTagName() { return this._all().filter((k) => k.isConnected); }
  getBoundingClientRect() { return { left: 0, width: 100 }; }
}
let REGISTRY = null;

const CORE = ["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml",
  "ooLiveRepaint", "_tfn", "ooKeywordUndoButton"];

function harness(answers, opts) {
  opts = opts || {};
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  REGISTRY = { fresh(id, el) { if (nodes[id]) nodes[id]._connected = false; nodes[id] = el; } };
  for (const id of ["wt-msg", "wt-list", "wt-name", "wt-query", "wt-threshold", "wt-window", "kx-facets", "kx-keywords",
    "sg-list", "sg-basis", "sg-concept-supers", "sg-concept-groups", "sg-concept-crumb", "ring-gaps", "ring-status",
    "ring-limit", "cv-list", "cv-method", "cv-window", "lunar-list", "lunar-limit", "lunar-fdr", "lunar-single",
    "lunar-term", "lunar-direction", "cs-promote-result"]) nodes[id] = new El("DIV");
  const calls = { api: [] };
  const api = async (url, o) => {
    const key = ((o && o.method) || "GET") + " " + url;
    calls.api.push(key);
    const a = answers[key] !== undefined ? answers[key] : answers[url];
    if (a === undefined) throw new Error("unexpected call " + key);
    if (a instanceof Error) throw a;
    return a;
  };
  const src = [
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    extractConst("esc"),
    ...CORE.map(extract),
    "function fmtNum(x) { return String(x); }",
    extract("_patT"),
    INSIGHTS_JS,
    "return { createWatch, evaluateWatches, loadWatches, loadKeywordExplorer, kxShowTag, kxRenderTags, kxHide, loadSuperGroups," +
    " renderConceptBrowse, repaintConceptBrowse, selectConceptBucket, loadRingGaps, ringLoadStart, loadConvergences, loadLunar," +
    " lunarTestTerm, promoteCitedSources, ooLiveRepaint };",
  ].join("\n");
  const document = { createElement: (tag) => new El(tag.toUpperCase()), documentElement: { dir: "ltr" }, querySelectorAll: () => [],
    getElementById: () => null };
  const window = { OOI18N, addEventListener() {}, devicePixelRatio: 1 };
  const t = (s) => OOI18N.t(s);
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console, __calls: calls,
    $: (id) => nodes[id] || null, api, toast() {}, extLink: (u, l) => l, confirm: () => true,
    ensureOnline: async () => true, _failMsg: (k, e) => e.message,
    pollJobStatus: async () => opts.job || { state: "done", result: {} },
    _jobStillRunning: (j) => j.state === "running",
    ooSaidText: (o, f) => t("Server text, in English") + ": " + (o[f] || ""),
    ooLangName: (c) => c, ooLangCell: (c) => c, ooCountryCell: (c) => c, ooIsoDate: (d) => d, fmtDateTime: (d) => d,
    uiLangCode: () => lang, tgtLangParam: () => "", lvlTitle: (l) => t("Super-group"), lvlBreadcrumb: () => "",
    kwLabelHtml: (m) => esc(m.term), _kwTf: (s, v) => OOI18N.tf(s, v), kwSensesAfterHtml: () => "", kwQidHtml: () => "",
    kwLabelParts: () => ({}), growthFallback: () => "", trendRateText: () => "", dashChartSvg: () => "",
    basisChip: (c) => `<span>${esc(t("basis"))}</span>`,
    showTab() {}, _insSubtabsSelect() {},
  };
  const fns = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns, nodes, calls, $: (id) => nodes[id],
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      // app-boot's ONE oo:langchange listener: the concept browse is drawn again, then every held node
      fns.repaintConceptBrowse();
      fns.ooLiveRepaint();
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));
const has = (el, s) => el.innerHTML.includes(s) || el.textContent.includes(s);

(async () => {
  // 1. Watches: the message line in each of its states, and the list's loading and failure lines.
  {
    const h = harness({ "POST /api/watches/evaluate": { count: 2 }, "GET /api/watches": new Error("down") });
    await h.fns.createWatch();
    const msg = h.$("wt-msg");
    assert.strictEqual(msg.textContent, "Enter a condition (search query) first.");
    h.switchTo("fr");
    assert.strictEqual(msg.textContent, FR["Enter a condition (search query) first."], "the prompt follows a switch");
    await h.fns.evaluateWatches();
    await tick();
    h.switchTo("de");
    assert.strictEqual(msg.textContent, DE["{n} watch(es) fired — see Home, or the history below."].replace("{n}", "2"),
      "the check's result follows a switch");
    assert.ok(has(h.$("wt-list"), esc(DE["Could not load watches: {error}"].replace("{error}", "down"))), h.$("wt-list").innerHTML);
    const h2 = harness({ "POST /api/watches/evaluate": new Error("boom") });
    await h2.fns.evaluateWatches();
    h2.switchTo("fr");
    assert.ok(has(h2.$("wt-msg"), esc(FR["Check failed: {error}"].replace("{error}", "boom"))), "the failure follows a switch");
  }

  // 2. The keyword explorer: the facets, the rows' buttons (the rows themselves are not drawn again), a hidden keyword,
  //    and the tag editor, whose field keeps what is typed.
  {
    const h = harness({
      "GET /api/insights/keyword-tags/facets": { axes: ["type", "topic"], facets: { type: [{ tag: "person", keywords: 3 }], topic: [] } },
      "GET /api/insights/keyword-tags/keywords?axis=type&tag=person&limit=200": { total: 1,
        keywords: [{ term: "Ada", normalized: "ada", language: "en", articles: 2, mentions: 5, source: "baseline" }] },
      "POST /api/insights/exclude": {}, "POST /api/insights/include": {},
      "GET /api/insights/keyword-tags?normalized=ada": { tags: { type: ["person"] }, sources: { "type:person": "user" } },
    });
    await h.fns.loadKeywordExplorer();
    const facets = h.$("kx-facets");
    assert.ok(has(facets, esc("none yet — click “Apply baseline tags” above")), facets.innerHTML);
    h.switchTo("fr");
    assert.ok(has(facets, esc(FR["none yet — click “Apply baseline tags” above"])), "the empty facet follows a switch: " + facets.innerHTML);
    h.switchTo("en");
    const box = h.$("kx-keywords");
    await h.fns.kxShowTag({ dataset: { ax: "type", tag: "person" } });
    const tagsB = box.querySelector("kx-tags-b"), hideB = box.querySelector("kx-hide-b");
    assert.strictEqual(tagsB.textContent, "Tags");
    assert.strictEqual(hideB.textContent, "Hide");
    assert.ok(tagsB.hasAttribute("data-i18n-dyn"), "the Tags button's hover is out of the walker's reach");
    h.switchTo("fr");
    assert.strictEqual(box.querySelector("kx-tags-b"), tagsB, "the rows are not drawn again");
    assert.strictEqual(tagsB.textContent, FR["Tags"]);
    assert.strictEqual(tagsB.getAttribute("title"),
      FR["Show this keyword's tags, and add or remove your own. A tag is a LABEL you assert, never a score."], "the hover follows");
    assert.strictEqual(hideB.textContent, FR["Hide"]);
    await h.fns.kxHide(hideB);
    h.switchTo("de");
    assert.strictEqual(hideB.textContent, DE["hidden"], "a hidden keyword says so in the new language");
    assert.ok(hideB.disabled);
    // the shipped Undo beside it: the button says Hide again, and that follows a switch too
    const undo = hideB.nextElementSibling;
    for (const fn of undo.listeners.click) await fn({ isTrusted: true });
    assert.ok(!hideB.disabled);
    h.switchTo("fr");
    assert.strictEqual(hideB.textContent, FR["Hide"], "the label put back by Undo follows a switch");
    h.switchTo("de");
    const tagbox = box.querySelector("kx-tagbox");
    await h.fns.kxRenderTags(tagbox, "ada");
    assert.ok(tagbox.hasAttribute("data-i18n-dyn"), "the editor is out of the walker's reach");
    const val = tagbox.querySelector("kx-tag-val"), add = tagbox.querySelector("kx-tag-add");
    assert.strictEqual(val.getAttribute("placeholder"), DE["new tag"]);
    assert.strictEqual(add.textContent, DE["Add"]);
    assert.ok(has(tagbox.querySelector("kx-tag-chips"), esc(DE["you"])));
    val.value = "mine";
    h.switchTo("fr");
    assert.strictEqual(tagbox.querySelector("kx-tag-val"), val, "the field is not drawn again");
    assert.strictEqual(val.value, "mine", "what is being typed is kept");
    assert.strictEqual(val.getAttribute("placeholder"), FR["new tag"], "the placeholder follows a switch");
    assert.strictEqual(add.textContent, FR["Add"]);
    assert.ok(has(tagbox.querySelector("kx-tag-chips"), esc(FR["you"])), "the provenance follows a switch");
  }

  // 3. Groups: the list (a group with no members) and the basis chip; the concept browse is drawn again only once drawn.
  {
    const h = harness({
      "GET /api/insights/supergroups?series_top=12&window_days=7&target_lang=en": { supergroups: [{ id: 1, name: "G", members: [], count: 0, mentions: 0 }], counts: {} },
      "GET /api/insights/top?group=true&limit=200": { terms: [] },
      "GET /api/insights/rings": { rings: [{ id: "r1", languages: ["en"] }] },
    });
    h.switchTo("fr");
    assert.strictEqual(h.$("sg-concept-supers").innerHTML, "", "a browse never drawn is left alone");
    h.switchTo("en");
    await h.fns.loadSuperGroups();
    const list = h.$("sg-list");
    assert.ok(has(list, esc("No members yet.")), list.innerHTML);
    h.switchTo("fr");
    assert.ok(has(list, esc(FR["No members yet."])), "the group card follows a switch: " + list.innerHTML);
    assert.ok(has(h.$("sg-basis"), esc(FR["basis"] || "basis")));
    assert.ok(has(h.$("sg-concept-supers"), esc(FR["Ungrouped concepts"])), "the browse follows a switch: " + h.$("sg-concept-supers").innerHTML);
    assert.deepStrictEqual(h.calls.api.filter((c) => c.includes("supergroups")).length, 1, "a switch reads nothing");
  }

  // 4. The ring gap and the ring-load status, its hover included.
  {
    const h = harness({
      "GET /api/insights/ring-gaps": { candidates: 4, per_language: { fr: 4 }, method: "m" },
      "POST /api/insights/ring-load?limit=20": {},
    }, { job: { state: "done", result: { written: 3, requested: 4, stopped: true, method: "M", caveat: "C" } } });
    h.$("ring-limit").value = "20";
    await h.fns.loadRingGaps();
    const gaps = h.$("ring-gaps");
    h.switchTo("fr");
    assert.ok(has(gaps, esc(FR["concepts have no ring"])), "the gap line follows a switch: " + gaps.innerHTML);
    assert.ok(has(gaps, esc(FR["Server text, in English"])), "its hover too");
    await h.fns.ringLoadStart();
    const st = h.$("ring-status");
    assert.ok(st.textContent.startsWith(FR["Rings loaded:"]), st.textContent);
    assert.ok(st.hasAttribute("data-i18n-dyn"), "the line's hover is drawn only by the line");
    h.switchTo("de");
    assert.strictEqual(st.textContent, DE["Rings loaded:"] + " 3/4 · " + DE["stopped early"], "the result follows a switch");
    assert.ok(st.title.startsWith(DE["Server text, in English"]), "the hover follows a switch: " + st.title);
    const h2 = harness({ "POST /api/insights/ring-load?limit=20": new Error("refused") });
    h2.$("ring-limit").value = "20";
    await h2.fns.ringLoadStart();
    h2.switchTo("fr");
    assert.strictEqual(h2.$("ring-status").textContent, FR["Ring load failed:"] + " refused");
  }

  // 5. Convergences, the lunar screen and the single test, and the citation scan line.
  {
    const h = harness({
      "GET /api/insights/convergences?window_days=7&limit=20": { clusters: [], min_articles: 3, min_sources: 2, caveat: "c" },
      "GET /api/insights/lunar-correlation?limit=40&fdr_q=0.05": { results: [{ term: "x", r: 0.1, p_value: 0.5, n: 9, active_days: 9, q_value: 0.9, survives: false }], tested: 1, skipped: 0, survivors: 0 },
      "GET /api/insights/lunar-correlation?term=x&expected_direction=positive": { result: { term: "x", r: 0.1, p_value: 0.5, n: 9, active_days: 9, expected_direction: "positive", matches_expectation: false } },
    });
    await h.fns.loadConvergences();
    h.$("lunar-limit").value = "40"; h.$("lunar-fdr").value = "0.05";
    await h.fns.loadLunar();
    h.$("lunar-term").value = "x"; h.$("lunar-direction").value = "positive";
    await h.fns.lunarTestTerm();
    let finish;
    const h2 = harness({ "POST /api/sources/promote-cited?dry_run=true": new Promise((r) => { finish = r; }) });
    const run = h2.fns.promoteCitedSources();
    h.switchTo("fr"); h2.switchTo("fr");
    assert.ok(has(h.$("cv-list"), esc(FR["No convergences yet. A cluster needs at least {a} articles AND at least {s} sources sharing a place within the window."]
      .replace("{a}", "3").replace("{s}", "2"))), "the empty convergence line follows a switch");
    assert.ok(h.$("cv-method").textContent.startsWith(FR["Server text, in English"]), "its caveat line too");
    assert.ok(has(h.$("lunar-list"), esc(FR["No series survived the multiple-testing correction — the honest, expected result."])), "the screen follows");
    assert.ok(has(h.$("lunar-list"), ">" + esc(FR["Term"]) + "</th>"), "its table head too");
    assert.ok(has(h.$("lunar-single"), esc(FR["the measured sign CONTRADICTS your declaration."])), "the single test follows");
    assert.strictEqual(h2.$("cs-promote-result").textContent, FR["Scanning citations…"], "the scan line follows");
    finish({ candidates: [], min_source_citers: 3 });
    await run;
    // the result replaces the scan line for good: a switch does not bring the scan line back
    const after = h2.$("cs-promote-result").textContent;
    assert.ok(!after.includes(FR["Scanning citations…"]), after);
    h2.switchTo("de");
    assert.strictEqual(h2.$("cs-promote-result").textContent, after, "a later line is never reverted by a switch");
  }

  console.log("insights_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
