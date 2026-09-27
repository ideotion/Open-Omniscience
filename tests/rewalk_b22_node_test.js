/**
 * Behavioural node test for fix batch B22 of the 2026-09-27 delegated re-walk: the Home
 * at-a-glance strip's age note (H-1, P-5, T-4, U-1), the Home status line's agreement
 * (U-10), the "By channel" chips (U-8), the split-figure label (S-10), and the surfaces
 * that stayed in a previous language after a switch that started in a non-English locale
 * (T-3: Home "Most recent", Home "Latest", the Settings Collection toggle, the Feed tab).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name, and the
 * translations come from the REAL locale files -- the sibling-test convention (see
 * tests/clickthrough_b8_node_test.js).
 *
 * Run by tests/test_rewalk_b22_fixes.py (and standalone:
 * `node tests/rewalk_b22_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const HOME = fs.readFileSync(path.join(STATIC, "app-home.js"), "utf-8");
const SOURCES = fs.readFileSync(path.join(STATIC, "app-sources.js"), "utf-8");
const BOOT = fs.readFileSync(path.join(STATIC, "app-boot.js"), "utf-8");
const CORE = fs.readFileSync(path.join(STATIC, "app-core.js"), "utf-8");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));
const LANGS = ["ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"];

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) {
  return Promise.resolve().then(fn).then(() => { passed += 1; console.log("ok  - " + name); });
}

// Same balanced-brace extraction every node suite here uses (duplicated per convention).
function extract(name, decl, src) {
  const head = decl || ("function " + name + "(");
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = src.indexOf("(", at); j < src.length; j++) {
    if (src[j] === "(") p++;
    else if (src[j] === ")") { p--; if (p === 0) { i = src.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}
function extractConst(name, src) {
  const head = "const " + name + " = ";
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  const open = at + head.length, oc = src[open], cc = oc === "{" ? "}" : "]";
  let depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === oc) depth++;
    else if (src[j] === cc) { depth--; if (depth === 0) return src.slice(at, j + 1) + ";"; }
  }
  assert(false, "unbalanced literal extracting " + name);
}

const ESC = `const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));`;

// A fake i18n engine over a swappable real locale: t()/tf()/current() behave like
// src/static/i18n.js (an unknown key renders its English).
function makeI18n(lang) {
  const I = { lang, map: lang === "en" ? {} : LOCALE(lang) };
  I.use = (code) => { I.lang = code; I.map = code === "en" ? {} : LOCALE(code); };
  I.api = {
    t: (s) => (I.map[s] == null ? s : I.map[s]),
    tf: (s, v) => {
      let out = I.map[s] == null ? s : I.map[s];
      if (v) out = out.replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));
      return out;
    },
    current: () => I.lang,
    ready: Promise.resolve(lang),
  };
  return I;
}

function makeEl() {
  return { innerHTML: "", textContent: "", hidden: true, attrs: {},
    setAttribute(k, v) { this.attrs[k] = String(v); }, getAttribute(k) { return (k in this.attrs) ? this.attrs[k] : null; },
    hasAttribute(k) { return k in this.attrs; }, removeAttribute(k) { delete this.attrs[k]; } };
}

// Run `body` (source text) in a sandbox where `this` carries the fakes; returns `this`.
function sandbox(I, els, body, extra) {
  const src = `
    const window = { OOI18N: this.I.api };
    const OOI18N = this.I.api;
    ${ESC}
    const $ = (id) => this.els[id] || null;
    const fmtNum = (n) => String(n);
    const calls = this.calls;
    async function api(p) { calls.push(p); throw new Error("no fetch expected: " + p); }
    ${body}
  `;
  const sb = Object.assign({ I, els, calls: [] }, extra || {});
  // eslint-disable-next-line no-new-func
  new Function(src).call(sb);
  return sb;
}

async function run() {
  // ===================== H-1, P-5, T-4, U-1: the age note ===================== //
  const noteSb = (I) => sandbox(I, {}, `
    const _STALE_NOTE_S = 90;
    ${extract("homeStatsAgeNote", null, HOME)}
    this.note = homeStatsAgeNote;
  `);
  const AS_OF = "2026-09-27T10:25:16+00:00";

  await test("H-1: an idle value the server VERIFIED unchanged carries no note, however old", () => {
    const I = makeI18n("en");
    const sb = noteSb(I);
    for (const age of [90, 400, 86400]) {
      const n = sb.note({ cache_age_s: age, as_of: AS_OF, cache_ttl_s: 30, verified_current: true,
        recount_running_s: null }, I.api.t);
      assert(n === "", "a verified-current value got a note at age " + age + ": " + n);
    }
  });

  await test("H-1: 'server busy' only when a recount has run for at least the cache's own interval", () => {
    for (const code of ["en", "fr", "ar", "zh"]) {
      const I = makeI18n(code);
      const sb = noteSb(I);
      // The cause is what follows the time in each locale's frame.
      const cause = (key) => I.api.t(key).split("{time}")[1].trim();
      const busyWord = cause("as of {time} (server busy)");
      const pendingWord = cause("as of {time} (recount pending)");
      const base = { cache_age_s: 400, as_of: AS_OF, cache_ttl_s: 30, verified_current: false };
      const pending = sb.note(Object.assign({}, base, { recount_running_s: null }), I.api.t);
      assert(pending && pending.indexOf(busyWord) === -1, code + ": busy claimed with no recount running: " + pending);
      assert(pending.indexOf(pendingWord) !== -1, code + ": no pending wording: " + pending);
      const young = sb.note(Object.assign({}, base, { recount_running_s: 5 }), I.api.t);
      assert(young.indexOf(busyWord) === -1, code + ": a 5 s recount was called busy: " + young);
      const slow = sb.note(Object.assign({}, base, { recount_running_s: 45 }), I.api.t);
      assert(slow.indexOf(busyWord) !== -1, code + ": a 45 s recount (ttl 30) was not called busy: " + slow);
      // A payload with no verification field (an older server) is never called busy either.
      const legacy = sb.note({ cache_age_s: 400, as_of: AS_OF }, I.api.t);
      assert(legacy.indexOf(busyWord) === -1, code + ": an unmeasured payload was called busy: " + legacy);
    }
  });

  await test("H-1: below the threshold nothing is added, verified or not", () => {
    const I = makeI18n("en");
    const sb = noteSb(I);
    assert(sb.note({ cache_age_s: 60, as_of: AS_OF, verified_current: false, recount_running_s: 60, cache_ttl_s: 30 }, I.api.t) === "",
      "a 60 s value got a note");
  });

  // ============================ U-10: the status line ========================== //
  function homeStatus(lang, running) {
    const els = { "home-status": makeEl() };
    const sb = sandbox(makeI18n(lang), els, `
      let _homeRunningLast = null;
      function _homeGlanceWhenReady() {}
      ${extract("renderHomeStatus", null, HOME)}
      this.render = renderHomeStatus;
    `);
    sb.render(running);
    return els["home-status"].innerHTML;
  }

  await test("U-10: French agrees the state with 'collecte' (arrêtée), and every locale keeps its pill", () => {
    const f = homeStatus("fr", false);
    assert(f.indexOf("Collecte automatique : <span class=\"pill \">arrêtée</span>") === 0, "fr: " + f);
    assert(f.indexOf(">arrêté<") === -1, "fr: the masculine form survived: " + f);
    for (const code of LANGS) {
      for (const running of [true, false]) {
        const h = homeStatus(code, running);
        const m = h.match(/<span class="pill (?:ok)?">([^<]*)<\/span>/);
        assert(m && m[1].trim().length > 0, code + "/" + running + ": no state word in the pill: " + h);
        assert(!/[\u0001\u0002]|\{pill\}|\{endpill\}/.test(h), code + "/" + running + ": a marker leaked: " + h);
      }
    }
  });

  // ============================ S-10: the split label ========================== //
  await test("S-10: the enabled=false figure is labelled by its predicate, and its hover names every population", () => {
    const I = makeI18n("en");
    const sb = sandbox(I, {}, `
      ${extractConst("HOME_STAT_LABELS", HOME)}
      ${extractConst("HOME_SOURCE_SPLIT_HOVER", HOME)}
      ${extractConst("HOME_SOURCE_SPLIT_KEYS", HOME)}
      ${extract("homeStatLabel", null, HOME)}
      ${extract("homeSourceSplitHover", null, HOME)}
      this.label = homeStatLabel; this.hover = homeSourceSplitHover;
    `);
    assert(sb.label("sources_candidates") === "Not enabled", "label: " + sb.label("sources_candidates"));
    const h = sb.hover("sources_candidates", { sources: 11, sources_candidates: 5 });
    assert(/switched off/.test(h) && /admission was undone/.test(h), "hover omits a population: " + h);
    assert(!/awaiting review\. /.test(h.replace("candidates awaiting review", "")), "hover still says every one awaits review: " + h);
  });

  // ============================= U-8: channel chips ============================ //
  const FACETS = { facets: [
    { source_type: "news", articles: 449 }, { source_type: "hazard", articles: 1 },
    { source_type: "legal", articles: 1 }, { source_type: "newsletter", articles: 1 },
    { source_type: "wiki", articles: 1 }, { source_type: "brand-new-type", articles: 1 }] };
  function channels(I) {
    const els = { "home-channels-panel": makeEl(), "home-channels": makeEl() };
    const sb = sandbox(I, els, `
      let _homeChannelsPayload = this.payload;
      ${extractConst("HOME_CHANNEL_LABELS", HOME)}
      ${extract("homeChannelLabel", null, HOME)}
      ${extract("_renderHomeChannels", null, HOME)}
      this.render = _renderHomeChannels;
    `, { payload: FACETS });
    return { sb, els };
  }

  await test("U-8: chips carry translated channel names; the raw code stays the click value and the hover", () => {
    for (const code of ["en", "fr", "ar", "zh"]) {
      const I = makeI18n(code);
      const { sb, els } = channels(I);
      sb.render();
      const html = els["home-channels"].innerHTML;
      const loc = code === "en" ? {} : LOCALE(code);
      const name = (k) => (loc[k] == null ? k : loc[k]);
      for (const [raw, label] of [["news", "News"], ["hazard", "Hazards"], ["legal", "Legal"],
                                  ["newsletter", "Newsletters"], ["wiki", "Wiki"]]) {
        assert(html.indexOf(">" + name(label) + " <span") !== -1, code + ": chip for " + raw + " is not '" + name(label) + "': " + html.slice(0, 300));
        assert(html.indexOf("openChannelCorpus(&quot;" + raw + "&quot;)") !== -1, code + ": click value changed for " + raw);
      }
      if (code !== "en") {
        assert(html.indexOf(">news <span") === -1, code + ": a raw code reached a chip label");
      }
      // A type the map does not know stays itself (data), never a guessed name.
      assert(html.indexOf(">brand-new-type <span") !== -1, code + ": an unknown type was renamed");
      // The hover names this chip's channel and its code.
      assert(html.indexOf(esc(name("News"))) !== -1 && /news/.test(html), code + ": hover lacks name/code");
      assert(sb.calls.length === 0, code + ": the render fetched");
    }
  });

  await test("U-8: every channel label is keyed in all twelve locales", () => {
    const src = extractConst("HOME_CHANNEL_LABELS", HOME);
    const vals = [...src.matchAll(/:\s*"([^"]+)"/g)].map((m) => m[1]);
    assert(vals.length >= 30, "parsed only " + vals.length + " labels");
    for (const code of LANGS) {
      const loc = LOCALE(code);
      for (const v of vals) assert(typeof loc[v] === "string" && loc[v], code + ": no key for " + v);
    }
  });

  // =============== T-3: Home "Most recent" repaints after a switch =============== //
  await test("T-3: 'Most recent' painted in fr repaints in ar and zh from its rows, no fetch", () => {
    const I = makeI18n("fr");
    const els = { "home-recent-panel": makeEl(), "home-recent": makeEl() };
    const sb = sandbox(I, els, `
      let _homeRecentLast = {rows: []};
      ${extract("_renderHomeRecent", null, HOME)}
      this.render = _renderHomeRecent;
      this.setRows = (r) => { _homeRecentLast = r == null ? null : {rows: r}; };
    `);
    sb.render();
    assert(els["home-recent"].innerHTML.indexOf(esc(LOCALE("fr")["No articles for this tag yet."])) !== -1, "fr empty line");
    for (const code of ["ar", "zh", "en"]) {
      I.use(code);
      sb.render();
      const want = code === "en" ? "No articles for this tag yet." : LOCALE(code)["No articles for this tag yet."];
      assert(els["home-recent"].innerHTML.indexOf(esc(want)) !== -1, code + ": not repainted: " + els["home-recent"].innerHTML);
    }
    sb.setRows([{ id: 7, title: "T", source: "s", published_at: "2026-09-01" }]);
    I.use("ar");
    sb.render();
    assert(els["home-recent"].innerHTML.indexOf(esc(LOCALE("ar")["offline stored copy"])) !== -1, "ar: row hover not repainted");
    // Nothing read (or a failed read) -> nothing to repaint, and the box is left alone.
    sb.setRows(null);
    els["home-recent"].innerHTML = "SERVER ERROR";
    sb.render();
    assert(els["home-recent"].innerHTML === "SERVER ERROR", "painted over a failed read");
    assert(sb.calls.length === 0, "the repaint fetched");
  });

  // ==================== T-3 class: Home "Latest" repaints too ==================== //
  await test("T-3/U-8: 'Latest' redraws its channel pill, counts' words and facet options in the new language", () => {
    const I = makeI18n("fr");
    const sel = () => { const s = makeEl(); s.value = ""; return s; };
    const els = { "home-latest-panel": makeEl(), "home-latest": makeEl(), "latest-channel": sel(), "latest-tag": sel() };
    const payload = { articles: [{ id: 1, title: "A", created_at: "2026-09-01", word_count: 120,
      cited_sources: 2, source: { name: "S", source_type: "news" } }],
      available_content_types: { news: 3 }, available_tags: [{ tag: "x", articles: 3 }], caveat: "c" };
    const sb = sandbox(I, els, `
      let _homeLatestPayload = this.payload;
      ${extractConst("HOME_CHANNEL_LABELS", HOME)}
      ${extract("homeChannelLabel", null, HOME)}
      ${extract("_fillLatestFacet", null, HOME)}
      ${extract("_renderHomeLatest", null, HOME)}
      this.render = _renderHomeLatest;
    `, { payload });
    sb.render();
    const fr = LOCALE("fr"), ar = LOCALE("ar");
    assert(els["home-latest"].innerHTML.indexOf(">" + fr["News"] + "<") !== -1, "fr pill: " + els["home-latest"].innerHTML);
    assert(els["latest-channel"].innerHTML.indexOf(">" + fr["News"] + " (3)<") !== -1, "fr option: " + els["latest-channel"].innerHTML);
    I.use("ar");
    sb.render();
    assert(els["home-latest"].innerHTML.indexOf(">" + ar["News"] + "<") !== -1, "ar pill not repainted");
    assert(els["home-latest"].innerHTML.indexOf(esc(ar["words"])) !== -1, "ar 'words' not repainted");
    assert(els["latest-channel"].innerHTML.indexOf(esc(ar["All channels"])) !== -1, "ar 'All channels' not repainted");
    assert(sb.calls.length === 0, "the repaint fetched");
  });

  // ============ T-3: the Settings Collection toggle repaints after a switch ============ //
  await test("T-3: the Collection toggle painted in fr repaints in ar from the state it holds", () => {
    const I = makeI18n("fr");
    const btn = makeEl();
    const els = { "collect-toggle": btn };
    const sb = sandbox(I, els, `
      ${extract("_paintCollectToggle", null, SOURCES)}
      this.paint = _paintCollectToggle;
    `);
    // Before any paint the button holds no reading, so the listener must leave it alone.
    assert(btn.getAttribute("data-collect-state") === null, "state set before any paint");
    sb.paint(false);
    assert(btn.textContent === LOCALE("fr")["Collection is OFF — click to turn on"], "fr: " + btn.textContent);
    assert(btn.getAttribute("data-collect-state") === "off", "state not recorded");
    // What the oo:langchange listener does (app-boot.js), from the attribute alone.
    I.use("ar");
    const st = btn.getAttribute("data-collect-state");
    sb.paint(st === "on");
    assert(btn.textContent === LOCALE("ar")["Collection is OFF — click to turn on"], "ar: " + btn.textContent);
    sb.paint(true);
    assert(btn.getAttribute("data-collect-state") === "on", "state not updated");
  });

  await test("T-3: the ONE oo:langchange listener redraws all four, guarded, never fetching", () => {
    const at = BOOT.indexOf('document.addEventListener("oo:langchange"');
    assert(at !== -1, "no oo:langchange listener");
    const body = BOOT.slice(at, BOOT.indexOf("\n    });", at));
    assert(/typeof _renderHomeRecent === "function"\) _renderHomeRecent\(\)/.test(body), "recent list not repainted");
    assert(/typeof _renderHomeLatest === "function"\) _renderHomeLatest\(\)/.test(body), "latest panel not repainted");
    assert(/getAttribute\("data-collect-state"\)/.test(body) && /_paintCollectToggle\(st === "on"\)/.test(body),
      "collection toggle not repainted from its own state");
    assert(/typeof _repaintFeed === "function"\) _repaintFeed\(\)/.test(body), "the Feed tab not repainted");
  });

  // ========== T-3, found again by the batch review: the Feed tab repaints ========== //
  // Reviewer's repro: cold in fr, open the Feed, switch live to ar then zh -> the order
  // controls, the held-back line and "Load more" stayed French. The cards' own chrome
  // ("Show less", the keyword hover) was the same class, measured in the same walk.
  const feedSb = (I, els, extra) => sandbox(I, els, `
    ${extract("ooLabelHtml", null, CORE)}
    const _toneChip = () => "";
    const ooLangCell = (c) => esc(c);
    const expanded = this.expanded;
    function _feedExpand(b) { expanded.push(b.aid); }
    function _feedOrder() { return "shuffled"; }
    let _feedBusy = false, _feedDone = false, _feedHeld = null;
    let _feedRows = [], _feedLast = null, _feedErr = null;
    ${extract("_feedControls", null, HOME)}
    ${extract("_feedCard", null, HOME)}
    ${extract("_feedNote", null, HOME)}
    ${extract("_feedMoreHtml", null, HOME)}
    ${extract("_repaintFeed", null, HOME)}
    this.repaint = _repaintFeed;
    this.set = (o) => {
      if ("rows" in o) _feedRows = o.rows; if ("last" in o) _feedLast = o.last;
      if ("held" in o) _feedHeld = o.held; if ("done" in o) _feedDone = o.done;
      if ("err" in o) _feedErr = o.err; if ("busy" in o) _feedBusy = o.busy;
    };
  `, Object.assign({ expanded: [] }, extra || {}));
  const feedEls = () => {
    const list = makeEl();
    // One card (aid 7) is open; the repaint must reopen it after redrawing.
    list.querySelectorAll = (sel) => sel.indexOf('data-open="1"') !== -1
      ? [{ closest: () => ({ getAttribute: () => "7" }) }]
      : [{ getAttribute: () => "7", querySelector: () => ({ aid: "7" }) },
         { getAttribute: () => "8", querySelector: () => ({ aid: "8" }) }];
    const ctl = makeEl(); ctl.children = { length: 0 };
    return { "feed-controls": ctl, "feed-note": makeEl(), "feed-list": list, "feed-more": makeEl() };
  };
  const ROWS = [
    { id: 7, title: "A", reader_url: "/r/7", source: "S", published_at: "2026-06-01", language: "fr",
      keywords: [{ term: "vote", count: 2 }], excerpt: "short", excerpt_full: "short and long" },
    { id: 8, title: "", reader_url: "/r/8", source: "S", keywords: [], excerpt: "x", excerpt_full: "x" },
  ];
  const PAGE = { method: "A fixed order chosen by a seed — it uses each article's id and that seed and nothing else. No reading history is kept or consulted.",
    caveat: "c", results: ROWS };

  await test("T-3: the Feed painted in fr repaints in ar and zh from what it drew, no fetch", () => {
    const I = makeI18n("fr");
    const els = feedEls();
    const sb = feedSb(I, els);
    // Never opened: the listener must leave every node alone.
    sb.repaint();
    assert(els["feed-controls"].innerHTML === "" && els["feed-list"].innerHTML === "" && els["feed-more"].innerHTML === "",
      "a Feed never opened was painted");
    els["feed-controls"].children.length = 1;
    sb.set({ rows: ROWS, last: PAGE, held: { source_not_qualified: 83 }, done: false, err: null });
    sb.repaint();
    const fr = LOCALE("fr");
    assert(els["feed-controls"].innerHTML.indexOf(esc(fr["Shuffled"])) !== -1, "fr controls: " + els["feed-controls"].innerHTML);
    for (const code of ["ar", "zh"]) {
      I.use(code);
      sb.expanded.length = 0;
      sb.repaint();
      const L = LOCALE(code);
      const ctl = els["feed-controls"].innerHTML, list = els["feed-list"].innerHTML;
      assert(ctl.indexOf(esc(fr["Shuffled"])) === -1 && ctl.indexOf(esc(fr["Reshuffle"])) === -1, code + ": French left in the controls: " + ctl);
      for (const k of ["Shuffled", "Newest first", "Reshuffle", "Start from the top", "Draw a new order and start again from the top."]) {
        assert(ctl.indexOf(esc(L[k])) !== -1, code + ": controls miss " + k + ": " + ctl);
      }
      assert(els["feed-note"].innerHTML.indexOf(esc(L["{n} held back: their source has not been qualified yet"].replace("{n}", "83"))) !== -1,
        code + ": held-back line not repainted: " + els["feed-note"].innerHTML);
      assert(els["feed-more"].innerHTML.indexOf(esc(L["Load more"])) !== -1, code + ": 'Load more' not repainted: " + els["feed-more"].innerHTML);
      assert(list.indexOf(esc(L["Read more"])) !== -1, code + ": card 'Read more' not repainted");
      assert(list.indexOf(esc(L["Mentions in this article — open this keyword's corpus."])) !== -1, code + ": keyword hover not repainted");
      assert(list.indexOf(esc(L["(untitled)"])) !== -1, code + ": '(untitled)' not repainted");
      assert(list.indexOf('data-aid="7"') !== -1 && list.indexOf('data-aid="8"') !== -1, code + ": a card was lost");
      assert(sb.expanded.length === 1 && sb.expanded[0] === "7", code + ": the open card was not reopened: " + sb.expanded);
    }
    // The end of the pass, and a failed page, redraw in the new language too.
    sb.set({ done: true });
    sb.repaint();
    assert(els["feed-more"].innerHTML.indexOf(esc(LOCALE("zh")["That is the end of this pass."])) !== -1, "zh end-of-pass line");
    I.use("ar");
    sb.set({ err: "" });
    sb.repaint();
    assert(els["feed-more"].innerHTML.indexOf(esc(LOCALE("ar")["The feed could not load."])) !== -1, "ar failure line");
    sb.set({ err: null, busy: true });
    sb.repaint();
    assert(els["feed-more"].innerHTML.indexOf(esc(LOCALE("ar")["Loading…"])) !== -1, "ar in-flight line");
    assert(sb.calls.length === 0, "the repaint fetched");
  });

  console.log("all assertions passed (" + passed + " tests)");
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;" }[c]));
}

run().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
