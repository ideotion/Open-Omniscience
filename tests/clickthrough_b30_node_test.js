// The 2026-09-27 re-walk's batch B30 (rows L, M and U), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What a source-level check cannot see: whether a word reaches the translator at all,
// whether a surface drawn in one language is drawn again in the next WITHOUT a second
// request, and whether a picker rebuilt on a switch keeps what the reader picked. A
// MARKING translator ("«fr:…»") shows every string that went through it and which
// language it went through in, so one that skipped it -- or kept the old language -- is
// visible. Every function is EXTRACTED from the shipped modules, never re-typed.

"use strict";

const assert = require("assert");
const path = require("path");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = APP.indexOf("(", at), depth = 0;
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
function slice(from, to) {
  const a = APP.indexOf(from), b = APP.indexOf(to, a);
  assert.ok(a !== -1 && b !== -1, "could not slice " + from);
  return APP.slice(a, b);
}

// The marking translator, switchable. `cur` is what OOI18N.current() answers.
const I18N = {
  lang: "fr", cur: "fr",
  t(s) { return "«" + I18N.lang + ":" + s + "»"; },
  tf(s, v) { return I18N.t(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)); },
  current() { return I18N.cur; },
};
const FSI = "⁨", PDI = "⁩";

// Country names by language, so a cell drawn in one language and not redrawn shows it.
const NAMES = {
  en: { DE: "Germany", FR: "France", AL: "Albania", DZ: "Algeria", BR: "Brazil", RU: "Russia" },
  fr: { DE: "Allemagne", FR: "France", AL: "Albanie", DZ: "Algérie", BR: "Brésil", RU: "Russie" },
};
const A3 = { DE: "DEU", FR: "FRA", AL: "ALB", DZ: "DZA", BR: "BRA", RU: "RUS" };
function ooCountryCode(x) { return A3[String(x).toUpperCase()] || String(x).toUpperCase(); }
function ooCountryName(x, fb) { return (NAMES[I18N.lang] || {})[String(x).toUpperCase()] || fb; }
function ooCountryCompare(a, b) { return ooCountryName(a, a).localeCompare(ooCountryName(b, b), I18N.lang); }
function ooCountryCell(x) { return `<span title="${ooCountryName(x, "")}">${ooCountryCode(x)}</span>`; }

// The DOM this batch's renderers write into. A <select> parses its options the way a
// browser does (value = the `selected` one, else the first); every element derives its
// textContent from its markup, which is what the feed-directory repaint guards on.
const EL = {};
function $(id) {
  if (EL[id]) return EL[id];
  const e = { id, _html: "", value: "", options: [], checked: false, scrolled: 0 };
  Object.defineProperty(e, "innerHTML", {
    get() { return this._html; },
    set(h) {
      this._html = h;
      this.options = [...String(h).matchAll(/<option value="([^"]*)"[^>]*>([^<]*)<\/option>/g)]
        .map((m) => ({ value: m[1], text: m[2] }));
      const sel = /<option value="([^"]*)" selected/.exec(h);
      this.value = sel ? sel[1] : (this.options[0] ? this.options[0].value : "");
    },
  });
  Object.defineProperty(e, "textContent", {
    get() {
      // Drop the tags by walking the string (a regex replace reads to CodeQL as an
      // incomplete sanitizer; this is a test double, not one).
      let out = "", inTag = false;
      for (const ch of this._html) {
        if (ch === "<") inTag = true;
        else if (ch === ">" && inTag) inTag = false;
        else if (!inTag) out += ch;
      }
      return out;
    },
    set(v) { this._html = String(v); },
  });
  Object.defineProperty(e, "firstElementChild", { get() { return /</.test(this._html) ? {} : null; } });
  e.querySelector = (sel) => (new RegExp("<" + sel.split(/[#.\s]/)[0]).test(e._html) ? {} : null);
  e.scrollIntoView = () => { e.scrolled++; };
  EL[id] = e;
  return e;
}
let API_CALLS = [];
const API_ANSWERS = {};
async function api(p) {
  API_CALLS.push(p);
  const key = Object.keys(API_ANSWERS).find((k) => p.startsWith(k));
  if (!key) throw new Error("unexpected request " + p);
  return JSON.parse(JSON.stringify(API_ANSWERS[key]));
}
const OPENED = [];
const WIN = { OOI18N: I18N, open: (u) => { OPENED.push(u); } };
const DOC = { documentElement: { lang: "fr" } };

const src = [
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c]));}",
  "function extLink(u, label){ return '<a href=\"' + esc(u) + '\">' + esc(label) + '</a>'; }",
  "function agFlag(){ return ''; }",
  "function ooRegionName(x, fb){ return fb; }",
  "function safeUrl(u){ return u; }",
  "function kindColor(){ return '#000'; }",
  "function kindLabel(k){ return k; }",
  "function hazardTypeLabel(k){ return k; }",
  "function _ooMapNearby(){ return []; }",
  "function lawVerdictBadge(){ return ''; }",
  "function renderDiff(){ return ''; }",
  "function lawAiSummaryHtml(){ return ''; }",
  "function fmtDateTime(s){ return s; }",
  "function agExcluded(){ return new Set(); }",
  "function buildMapSvg(){ return '<svg></svg>'; }",
  "function wireMapDrag(){}",
  "function toast(){}",
  "function _failMsg(s){ return s; }",
  "const MAP_W = 1, MAP_H = 1; let MAP_VB = null;",
  extract("fmtNum"),
  slice("const _LTR_ISOLATE =", "function _ltrIsolate"),
  extract("_ltrIsolate"),
  extract("ooAreaCell"),
  // app-agenda: the Country picker, the calendar directory, the months, the bulletin's Open
  "const AG = { countries: null };",
  "let _feedDir = null; function _setFeedDir(v){ _feedDir = v; }",
  extract("agLocale"),
  "const _MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];",
  extract("_agMonth"),
  extract("_agFillCountryOptions"),
  extract("_bulT"),
  extract("_bulTf"),
  extract("_bulLang"),
  extract("bulletinOpenFile"),
  slice("const _FEED_KIND_LABEL = {", "function _feedKindLabel"),
  extract("_feedKindLabel"),
  extract("_verdictChip"),
  extract("famStatus"),
  extract("_feedFamName"),
  slice("const _FEED_SORTS = {", "function _feedDirFiltered"),
  extract("_feedDirFiltered"),
  extract("renderFeedDir"),
  extract("repaintFeedDirFromCache"),
  // app-map: the Stories dates and detail, the Insights map tables, the producers
  "const MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];",
  extract("_tmapFmt"),
  extract("fmtYear"),
  extract("fmtDate"),
  slice("let _ooMapDetailLast = null", "function repaintOoMapDetailFromCache"),
  "let _ooMapSigSet = [], _ooMapSigWin = 25;",
  extract("repaintOoMapDetailFromCache"),
  extract("_ooMapCountryDetail"),
  extract("_ooMapSignalDetail"),
  "let _insMapLast = null;",
  "async " + extract("loadMap"),
  extract("_insMapTables"),
  extract("repaintInsMapFromCache"),
  extract("_mapTf"),
  "let _statAgenciesLast = null;",
  extract("repaintStatAgenciesFromCache"),
  "async " + extract("loadStatAgencies"),
  extract("_renderStatAgencies"),
  // app-markets: the minerals board
  "async " + extract("loadMineralsSupply"),
  // app-gov-law: the country pickers and the two law panels
  extract("_govTf"),
  extract("_govPickLabel"),
  extract("_govCountryOptions"),
  extract("_govRepaintCountryPickers"),
  extract("_lawBytes"),
  slice("const _LAW_FLAG_LABEL = {", "function _lawCodeLabel"),
  extract("_lawCodeLabel"),
  extract("_lawFlagReason"),
  "let _lawStatus = null; let _lawDocsById = {};",
  "async " + extract("loadLawChanges"),
  "async " + extract("loadLawDocs"),
  "return { AG, _setFeedDir, _agMonth, _agFillCountryOptions, bulletinOpenFile, _feedKindLabel,"
    + " renderFeedDir, repaintFeedDirFromCache, _feedDirFiltered, _feedFamName, fmtYear, fmtDate, _ooMapCountryDetail,"
    + " _ooMapSignalDetail, repaintOoMapDetailFromCache, loadMap, repaintInsMapFromCache,"
    + " loadStatAgencies, repaintStatAgenciesFromCache, loadMineralsSupply, _govRepaintCountryPickers,"
    + " _lawBytes, _lawCodeLabel, _lawFlagReason, loadLawChanges, loadLawDocs, ooAreaCell };",
].join("\n");
const M = new Function("window", "OOI18N", "document", "$", "api", "ooCountryCode", "ooCountryName",
  "ooCountryCompare", "ooCountryCell", src)(WIN, I18N, DOC, $, api, ooCountryCode, ooCountryName,
  ooCountryCompare, ooCountryCell);

let n = 0;
async function test(name, fn) { await fn(); n++; console.log("ok  - " + name); }

(async () => {
  // --- L-3: the Agenda's Country picker follows a switch, names AND order ---------- //
  await test("L-3: the Agenda Country options are rebuilt in the new language and keep the pick", () => {
    I18N.lang = "en";
    M.AG.countries = ["DZ", "DE", "AL"];
    M._agFillCountryOptions();
    const sel = $("agenda-country");
    assert.deepStrictEqual(sel.options.map((o) => o.text.trim()),
      ["all", "Albania (ALB)", "Algeria (DZA)", "Germany (DEU)"]);
    sel.value = "DE";
    I18N.lang = "fr";
    M._agFillCountryOptions();
    assert.deepStrictEqual(sel.options.map((o) => o.text.trim()),
      ["all", "Albanie (ALB)", "Algérie (DZA)", "Allemagne (DEU)"]);
    assert.strictEqual(sel.value, "DE", "the reader's pick survives the rebuild");
  });

  await test("L-3: a never-loaded Agenda leaves the picker alone", () => {
    const before = $("agenda-country").innerHTML;
    M.AG.countries = null;
    M._agFillCountryOptions();
    assert.strictEqual($("agenda-country").innerHTML, before);
  });

  // --- L-3: the Governments country pickers --------------------------------------- //
  await test("L-3: the three Governments pickers are rebuilt from their own codes, pick kept", () => {
    I18N.lang = "en";
    for (const id of ["gov-country", "gov-cmp-a", "gov-cmp-b"]) {
      $(id).innerHTML = ["AL", "DZ", "DE"].map((c) => `<option value="${c}">x</option>`).join("");
    }
    $("gov-cmp-b").value = "DZ";
    I18N.lang = "fr";
    API_CALLS = [];
    M._govRepaintCountryPickers();
    assert.deepStrictEqual($("gov-country").options.map((o) => o.text),
      ["Albanie (ALB)", "Algérie (DZA)", "Allemagne (DEU)"]);
    assert.strictEqual($("gov-cmp-b").value, "DZ");
    assert.deepStrictEqual(API_CALLS, [], "a repaint never fetches");
  });

  // --- L-3: the Insights map tables and the producers directory ------------------- //
  await test("L-3: the Insights map tables redraw from the payload they drew, with no request", async () => {
    I18N.lang = "en";
    $("map-days").value = "30"; $("map-kind").value = "all";
    API_ANSWERS["/api/insights/map"] = {
      countries: [{ code: "br", top: [{ term: "soja", mentions: 3 }] }], cities: [],
    };
    API_CALLS = [];
    await M.loadMap();
    assert.ok($("map-countries").innerHTML.includes('title="Brazil"'));
    I18N.lang = "fr";
    M.repaintInsMapFromCache();
    assert.ok($("map-countries").innerHTML.includes('title="Brésil"'), $("map-countries").innerHTML);
    assert.strictEqual(API_CALLS.length, 1, "one load, no refetch on the switch");
  });

  await test("L-3: the producers directory redraws from its last payload, with no request", async () => {
    I18N.lang = "en";
    API_ANSWERS["/api/stats/agencies"] = {
      agencies: [{ name: "Rosstat", scope: "national", country: "RU", region: "Europe" }],
      continents_covered: ["Europe"],
    };
    API_CALLS = [];
    await M.loadStatAgencies();
    assert.ok($("stat-agencies").innerHTML.includes('title="Russia"'));
    I18N.lang = "fr";
    M.repaintStatAgenciesFromCache();
    assert.ok($("stat-agencies").innerHTML.includes('title="Russie"'));
    assert.ok($("stat-agencies").innerHTML.includes("«fr:National»"));
    assert.strictEqual(API_CALLS.length, 1);
  });

  await test("L-3: the World map's country detail redraws in place, without scrolling again", () => {
    I18N.lang = "en";
    const host = $("oo-coverage-detail");
    host.scrolled = 0;
    M._ooMapCountryDetail({ country: "DE", sources: 3, articles: 10, keywords: 40 }, "articles");
    assert.ok(host.innerHTML.includes('title="Germany"'));
    assert.strictEqual(host.scrolled, 1);
    I18N.lang = "fr";
    M.repaintOoMapDetailFromCache();
    assert.ok(host.innerHTML.includes('title="Allemagne"'), host.innerHTML);
    assert.ok(host.innerHTML.includes("«fr:Explore sources»"));
    assert.strictEqual(host.scrolled, 1, "a repaint must not move the page");
  });

  // --- L-6: the Stories detail, its dates and its dot hovers ---------------------- //
  await test("L-6: a signal date reads in the app language, through Intl", () => {
    I18N.cur = "fr";
    assert.strictEqual(M.fmtDate({ date: "2027-08-17" }), "17 août 2027");
    I18N.cur = "zh";
    assert.strictEqual(M.fmtDate({ date: "2027-08-17" }), "2027年8月17日");
    I18N.cur = "en";
    assert.strictEqual(M.fmtDate({ date: "2027-08-17" }), "Aug 17, 2027");
  });

  await test("L-6: a year below 100 is never renumbered into the 1900s, nor a year below 1 into an era", () => {
    I18N.cur = "en";
    assert.strictEqual(M.fmtDate({ date: "0079-10-24" }), "Oct 24, 79");
    I18N.cur = "fr";
    assert.ok(/ 79$/.test(M.fmtDate({ date: "0079-10-24" })), M.fmtDate({ date: "0079-10-24" }));
    assert.ok(!/19\d\d/.test(M.fmtDate({ date: "0079-10-24" })));
    assert.strictEqual(M.fmtDate({ date: "-3000-03-01" }), "mars 1, -3000");
    assert.ok(/^janv\. -3000$/.test(M.fmtYear(-3000)), M.fmtYear(-3000));
    assert.strictEqual(M.fmtYear(2001.7), "sept. 2001");
  });

  await test("L-6: the signal detail keys its pill, its link and its caveat, and repaints", () => {
    I18N.lang = "fr"; I18N.cur = "fr";
    const s = { kind: "political", title: "Independence Day (Indonesia)", date: "2027-08-17",
      geocode: "country", country: "ID", place: "Jakarta", lat: -6.2, lon: 106.8,
      source: "agenda", confirmed: true, url: "https://example.org/x" };
    const host = $("oo-coverage-detail");
    host.scrolled = 0;
    M._ooMapSignalDetail(s, [s], 25);
    assert.ok(host.innerHTML.includes("«fr:≈ country»"));
    assert.ok(host.innerHTML.includes("«fr:Official / reference source ↗»"));
    assert.ok(host.innerHTML.includes("17 août 2027"), host.innerHTML);
    assert.ok(!host.innerHTML.includes("Aug 17"));
    I18N.lang = "ar"; I18N.cur = "ar";
    M.repaintOoMapDetailFromCache();
    assert.ok(host.innerHTML.includes("«ar:≈ country»"));
    assert.ok(host.innerHTML.includes("أغسطس"));
    assert.strictEqual(host.scrolled, 1);
    I18N.lang = "fr"; I18N.cur = "fr";
  });

  // --- L-4: the minerals board ---------------------------------------------------- //
  await test("L-4: the minerals board keys its caveat, measures, commodity and units", async () => {
    I18N.lang = "fr";
    API_ANSWERS["/api/stats/minerals-supply"] = {
      available: true,
      caveat: "SUPPLY data — production, reserves, net-import-reliance. NOT market prices: no free rare-earth spot-price source exists and none is fabricated here. A missing value (—) is a published gap. Producers are shown, never averaged.",
      commodities: [{ commodity: "rare-earths", measures: {
        production: [{ ref_area: "US", area_kind: "country", time_period: "2024", value: 45000, unit: "metric tons REO" }],
        net_import_reliance: [{ ref_area: "US", area_kind: "country", time_period: "2024", value: null, unit: "percent" }],
      } }],
    };
    await M.loadMineralsSupply();
    const h = $("mkt-minerals-supply").innerHTML;
    assert.ok(h.includes("«fr:SUPPLY data — production"), "the caveat goes through t()");
    assert.ok(!/None/.test(h), "no Python token reaches the reader");
    assert.ok(h.includes("«fr:Rare earths»"));
    assert.ok(h.includes("«fr:Production»"));
    assert.ok(h.includes("«fr:Net import reliance»"));
    assert.ok(h.includes("«fr:metric tons REO»"));
    assert.ok(h.includes("«fr:percent»"));
    assert.ok(h.includes(">—<"), "a gap is drawn as a dash, never zero");
  });

  // --- L-5: an aggregate's name goes through t() in the one cell every caller shares //
  await test("L-5: an aggregate hover carries the translated name, WLD unchanged", () => {
    I18N.lang = "fr";
    assert.ok(M.ooAreaCell("HIC", "aggregate", "High income").includes('title="«fr:High income» — «fr:published aggregate»"'));
    assert.ok(M.ooAreaCell("WLD", "aggregate", "World").includes('title="«fr:World» — «fr:published aggregate»"'));
  });

  await test("L-5: the level map's caveat and refusal go through the app's translator", () => {
    const V = require(path.join(__dirname, "..", "src", "static", "ooviz.js"));
    const rows = [{ area: "USA", value: 1, unit: "USD", base_year: null, sa: null, period: "2024" }];
    globalThis.OOI18N = I18N;
    I18N.lang = "zh";
    try {
      const lvl = V.choroplethData(rows, { kind: "level" });
      assert.ok(lvl.caveat.startsWith("«zh:A level (count or total)"), lvl.caveat);
      assert.strictEqual(lvl.refusalReason,
        "«zh:A level is not comparable across areas of different size; it is shown as proportional symbols.»");
      const norm = V.choroplethData(rows, { kind: "normalized" });
      assert.ok(norm.caveat.startsWith("«zh:Coloured by comparable values only"));
    } finally { delete globalThis.OOI18N; I18N.lang = "fr"; }
    // Without a translator (node, or a page before i18n.js) the English stands.
    const bare = V.choroplethData(rows, { kind: "level" });
    assert.ok(bare.refusalReason.startsWith("A level is not comparable"));
  });

  // --- L-7 / U-9: the law panels -------------------------------------------------- //
  await test("L-7: the byte delta is one keyed frame with its signed number isolated", () => {
    I18N.lang = "ar";
    assert.strictEqual(M._lawBytes(120), "«ar:" + FSI + "+120" + PDI + " bytes»");
    assert.strictEqual(M._lawBytes(-640), "«ar:" + FSI + "-640" + PDI + " bytes»");
    assert.strictEqual(M._lawBytes(0), "«ar:0 bytes»");
    I18N.lang = "fr";
  });

  await test("L-7: flag and category codes show through labels, the code kept in the hover", () => {
    I18N.lang = "fr";
    assert.strictEqual(M._lawFlagReason("large-removal"),
      '<span data-i18n-dyn title="large-removal">«fr:large removal»</span>');
    assert.strictEqual(M._lawFlagReason("large_addition"),
      '<span data-i18n-dyn title="large_addition">«fr:large addition»</span>');
    assert.strictEqual(M._lawFlagReason("odd_code"), "odd_code", "an unlabelled code shows as stored");
  });

  await test("L-7: the changes list keys its pill, its reader link and its source link", async () => {
    I18N.lang = "fr";
    API_ANSWERS["/api/law/changes"] = { caveat: "", changes: [{ id: 1, document_id: 2, jurisdiction: "GB",
      title: "Walk Act 2026", delta_bytes: 120, flagged: true, flag_reasons: ["large-removal"],
      observed_at: "2026-09-27", official_url: "https://example.org/a", diff: null, ai_summary: null }] };
    await M.loadLawChanges();
    const h = $("law-changes").innerHTML;
    assert.ok(h.includes("«fr:" + FSI + "+120" + PDI + " bytes»"));
    assert.ok(h.includes("«fr:open reader»"));
    assert.ok(h.includes("«fr:official source ↗»"));
    assert.ok(h.includes("«fr:large removal»"));
    assert.ok(!/>\s*open reader\s*</.test(h));
  });

  await test("U-9: the documents table keys its headers, category, flag count and links", async () => {
    I18N.lang = "zh";
    API_ANSWERS["/api/law/documents"] = { documents: [{ id: 7, jurisdiction: "FR", title: "Code civil",
      category: "legislation", revisions: 1200, flagged: 1, watched: true, official_url: "https://example.org/c" }] };
    await M.loadLawDocs();
    const h = $("law-docs").innerHTML;
    for (const k of ["Jurisdiction", "Title", "Category", "Status", "Changes", "reader", "official ↗"]) {
      assert.ok(h.includes("«zh:" + k + "»"), k + " is not keyed: " + h);
    }
    assert.ok(h.includes('title="legislation">«zh:Legislation»'));
    assert.ok(h.includes("«zh:(1 flagged)»"));
    assert.ok(!/>reader</.test(h) && !/>legislation</.test(h));
    I18N.lang = "fr";
  });

  // --- U-3: the calendar directory ------------------------------------------------ //
  await test("U-3: the directory's status, pills, kind and tail are keyed frames over grouped counts", () => {
    I18N.lang = "fr";
    const fams = [];
    for (let i = 0; i < 45; i++) {
      fams.push({ key: "k" + i, name: "Fam " + i, kind: i === 0 ? "community" : "holidays",
        country: i === 0 ? null : "DE", duplicates: i === 1, imported_events: i === 1 ? 1200 : 0,
        feeds: [{ id: "f" + i, provider: "p", url: "https://example.org/" + i,
          verdict: i === 1 ? { status: "ok", events: 1500 } : null }] });
    }
    M._setFeedDir({ total_feeds: 1241, checked: 0, families: fams,
      verification: { unchecked: 1241, method: "Feeds are verified a few at a time on each collection pass, never at startup. A feed that fails is re-checked after 1 month, then 2, 4 and 6 — capped, so it is never written off permanently." } });
    M.renderFeedDir();
    const st = $("feeddir-status").innerHTML;
    assert.ok(st.startsWith("«fr:1 241 feeds · 45 folders · 0 checked»"), st);
    assert.ok(st.includes("«fr:1 241 not checked yet»"));
    assert.ok(st.includes('title="«fr:Feeds are verified'));
    const list = $("feeddir-list").innerHTML;
    assert.ok(list.includes("· «fr:Community»"));
    assert.ok(list.includes("· «fr:Public holidays»"));
    assert.ok(list.includes("«fr:1 200 imported»"));
    assert.ok(list.includes("«fr:1 sources»"));
    assert.ok(list.includes("«fr:reachable» · 1 500"));
    assert.ok(list.includes("«fr:+5 — type to filter»"));
    assert.strictEqual(M._feedKindLabel("space"), "Space");
    assert.strictEqual(M._feedKindLabel("brand_new_kind"), "brand_new_kind");
  });

  await test("U-3: a switch redraws the directory in the new language; a closed one is left alone", () => {
    I18N.lang = "ar";
    M.repaintFeedDirFromCache();
    assert.ok($("feeddir-status").innerHTML.startsWith("«ar:"), $("feeddir-status").innerHTML);
    assert.ok(!$("feeddir-status").innerHTML.includes("«fr:"));
    // A directory loaded by the Agenda's provenance pills but never opened: no status line.
    $("feeddir-status").innerHTML = "";
    M.repaintFeedDirFromCache();
    assert.strictEqual($("feeddir-status").innerHTML, "");
    I18N.lang = "fr";
  });

  await test("U-3: a holidays family's name is drawn from its parts, sorted and searched as shown", () => {
    const fams = [
      { key: "hol-de", name: "Germany — public holidays", kind: "holidays", country: "DE", feeds: [] },
      { key: "hol-fr", name: "France — public holidays", kind: "holidays", country: "FR", feeds: [] },
      { key: "un", name: "UN International Days & Weeks", kind: "civic", country: null, feeds: [] },
      // A shape the frame does not draw, and a code no name resolves for: shown as stored.
      { key: "sub", name: "Germany — public holidays (Bavaria)", kind: "holidays", country: "DE", feeds: [] },
      { key: "xx", name: "Nowhere — public holidays", kind: "holidays", country: "XX", feeds: [] },
    ];
    M._setFeedDir({ total_feeds: 5, checked: 0, families: fams, verification: {} });
    I18N.lang = "fr"; I18N.cur = "fr";
    assert.strictEqual(M._feedFamName(fams[0]), "«fr:Allemagne — public holidays»");
    assert.strictEqual(M._feedFamName(fams[2]), "«fr:UN International Days & Weeks»");
    assert.strictEqual(M._feedFamName(fams[3]), "«fr:Germany — public holidays (Bavaria)»");
    assert.strictEqual(M._feedFamName(fams[4]), "«fr:Nowhere — public holidays»");
    M.renderFeedDir();
    const list = $("feeddir-list").innerHTML;
    assert.ok(list.includes("«fr:Allemagne — public holidays»"), list);
    assert.ok(!list.includes(">Germany — public holidays\n"), "the catalogue's English name was printed");
    // Allemagne before France in French; France before Germany in English.
    const two = () => M._feedDirFiltered().map((f) => f.key).filter((k) => k.startsWith("hol-"));
    assert.deepStrictEqual(two(), ["hol-de", "hol-fr"]);
    I18N.lang = "en"; I18N.cur = "en";
    assert.deepStrictEqual(two(), ["hol-fr", "hol-de"]);
    // A switch redraws the names in the new language, from the payload held.
    I18N.lang = "fr"; I18N.cur = "fr";
    M.repaintFeedDirFromCache();
    assert.ok($("feeddir-list").innerHTML.includes("«fr:France — public holidays»"));
    // The search finds a row by the name on screen and by the catalogue's own.
    $("feeddir-q").value = "allemagne";
    assert.deepStrictEqual(M._feedDirFiltered().map((f) => f.key), ["hol-de"]);
    $("feeddir-q").value = "germany";
    assert.deepStrictEqual(M._feedDirFiltered().map((f) => f.key).sort(), ["hol-de", "sub"]);
    $("feeddir-q").value = "";
  });

  await test("U-3: the Agenda's month names are the reader's language", () => {
    DOC.documentElement.lang = "fr";
    assert.strictEqual(M._agMonth(7), "août");
    DOC.documentElement.lang = "en";
    assert.strictEqual(M._agMonth(7), "Aug");
    DOC.documentElement.lang = "fr";
  });

  // --- M-12: the editions list's Open carries the reading language ----------------- //
  await test("M-12: Open renders the edition in the language the app is read in", () => {
    OPENED.length = 0;
    I18N.cur = "fr";
    M.bulletinOpenFile("20260926-OOS-weekly.json");
    assert.strictEqual(OPENED[0], "/api/bulletin/editions/20260926-OOS-weekly.json/render?lang=fr&fmt=html");
    I18N.cur = "en";
    M.bulletinOpenFile("x.json");
    assert.strictEqual(OPENED[1], "/api/bulletin/editions/x.json/render?fmt=html", "English is the server default");
    I18N.cur = "fr";
  });

  console.log(`\n${n} checks passed`);
})().catch((e) => { console.error(e); process.exit(1); });
