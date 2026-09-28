/**
 * Behavioural node test for batch B12 of the 2026-09-26 delegated click-through: the
 * task-manager page's Resume routed to the app's ONE consent popup (X1), the Governments
 * partial-roster refusal as a keyed frame (X5), the Quality gates panel's keyed frames
 * and tunables (X6), the Library's Database & storage repainted on a language switch
 * without a fetch (X7) and the Home "Automatic collection" frame (X8).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name -- a re-typed
 * copy would pass while the real code was still broken (the sibling-test convention;
 * see tests/clickthrough_b8_node_test.js). Translations come from the REAL locale files.
 *
 * Run by tests/test_clickthrough_b12_fixes.py (and standalone:
 * `node tests/clickthrough_b12_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const read = (name) => fs.readFileSync(path.join(STATIC, name), "utf-8");
const TM = require("./app_source.js").pageSource("taskmanager.html");
const BOOT = read("app-boot.js");
const GOV = read("app-gov-law.js");
const QUAL = read("app-ai-tools.js");
const LIB = read("app-library.js");
const HOME = read("app-home.js");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));

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

const ESC = `const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));`;

// A fake i18n engine over a real locale: t()/tf() behave like src/static/i18n.js
// (an unknown key renders its English).
function i18n(lang, extra) {
  const map = Object.assign(lang === "en" ? {} : LOCALE(lang), extra || {});
  return {
    t: (s) => (map[s] == null ? s : map[s]),
    tf: (s, v) => {
      let out = map[s] == null ? s : map[s];
      if (v) out = out.replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));
      return out;
    },
    current: () => lang,
    ready: Promise.resolve(lang),
  };
}

async function run() {
  // ======================= X1: /tasks Resume ================================ //
  // The page has no consent popup of its own; it used to POST the resume straight away,
  // so a paused download re-opened a fetch with no consent step at all.
  function makeResume(online, calls) {
    const src = extract("resume", "resume: async function (id, local)", TM).replace(/^resume:\s*/, "");
    const sb = {
      api: async (p, opts) => {
        calls.api.push([p, (opts && opts.method) || "GET"]);
        if (p === "/api/system/network") {
          if (online === "throws") throw new Error("down");
          return {online};
        }
        return {detail: null};
      },
      location: {href: "/tasks"},
      toast: (m, kind) => calls.toast.push([m, kind || "ok"]),
      t: (s) => s,
    };
    // eslint-disable-next-line no-new-func
    const fn = new Function("api", "location", "toast", "t", "return " + src)(sb.api, sb.location, sb.toast, sb.t);
    return {fn, sb};
  }

  await test("X1: a download resume while offline hands off to the app's consent popup", async () => {
    const calls = {api: [], toast: []};
    const {fn, sb} = makeResume(false, calls);
    await fn("osm:asia");
    assert(sb.location.href === "/?resume=osm%3Aasia", "did not hand off: " + sb.location.href);
    assert(!calls.api.some(([p, m]) => m === "POST"), "POSTed the resume without consent: " + JSON.stringify(calls.api));
  });

  await test("X1: an unreadable network state is treated as offline, never as consent", async () => {
    const calls = {api: [], toast: []};
    const {fn, sb} = makeResume("throws", calls);
    await fn("dump:en:2026");
    assert(sb.location.href === "/?resume=dump%3Aen%3A2026", "did not hand off: " + sb.location.href);
    assert(!calls.api.some(([, m]) => m === "POST"), "POSTed on an unknown network state");
  });

  await test("X1: a resume while ONLINE stays a direct POST, as before", async () => {
    const calls = {api: [], toast: []};
    const {fn, sb} = makeResume(true, calls);
    await fn("osm:asia");
    assert(sb.location.href === "/tasks", "navigated away while online");
    assert(calls.api.some(([p, m]) => p === "/api/jobs/osm%3Aasia/resume" && m === "POST"), JSON.stringify(calls.api));
  });

  await test("X1: a LOCAL job (no network) resumes directly, offline or not", async () => {
    const calls = {api: [], toast: []};
    const {fn, sb} = makeResume(false, calls);
    await fn("translate:1", true);
    assert(sb.location.href === "/tasks", "a local resume was sent to the consent popup");
    assert(!calls.api.some(([p]) => p === "/api/system/network"), "a local resume read the network state");
    assert(calls.api.some(([p, m]) => p === "/api/jobs/translate%3A1/resume" && m === "POST"), JSON.stringify(calls.api));
  });

  // The app side: ?resume=<id> reaches the SPA's jobResume, which is gated by ensureOnline.
  function runHandoff(search) {
    const calls = {resume: [], replaced: []};
    const src = extract("_hydrateResumeHandoff", null, BOOT);
    const sb = {
      location: {search, pathname: "/", hash: "#home"},
      history: {replaceState: (a, b, url) => calls.replaced.push(url)},
      jobResume: (id) => calls.resume.push(id),
      window: {OOI18N: {ready: Promise.resolve("en")}},
    };
    // eslint-disable-next-line no-new-func
    new Function("location", "history", "jobResume", "window", "OOI18N", src + "\n" + "_hydrateResumeHandoff();")(
      sb.location, sb.history, sb.jobResume, sb.window, sb.window.OOI18N);
    return calls;
  }

  await test("X1: the app picks the hand-off up, drops it from the URL and runs jobResume", async () => {
    const calls = runHandoff("?resume=osm%3Aasia&corpus=x");
    await new Promise((r) => setTimeout(r, 5));
    assert(calls.resume.length === 1 && calls.resume[0] === "osm:asia", "jobResume not called: " + JSON.stringify(calls));
    assert(calls.replaced[0] === "/?corpus=x#home", "the id was left in the URL: " + calls.replaced[0]);
  });

  await test("X1: only a download id is honoured (a crafted link cannot name another job kind)", async () => {
    for (const bad of ["?resume=translate%3A1", "?resume=osm%3A", "?resume=%3Cscript%3E"]) {
      const calls = runHandoff(bad);
      await new Promise((r) => setTimeout(r, 5));
      assert(calls.resume.length === 0, "resumed a non-download id from " + bad);
      assert(calls.replaced.length === 1, "the parameter was not cleaned from " + bad);
    }
    const none = runHandoff("?corpus=x");
    assert(none.replaced.length === 0 && none.resume.length === 0, "acted without a resume parameter");
  });

  // ======================= X5: the partial-roster refusal =================== //
  function govHtml(lang, strategies) {
    const I = i18n(lang);
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      const ooCountryCode = (c) => String(c).toUpperCase();
      ${extract("_govTf", null, GOV)}
      ${extract("_govNames", null, GOV)}
      ${extract("_govGroupHtml", null, GOV)}
      this.render = _govGroupHtml;
    `;
    const sb = {I};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb.render({
      group: {members: ["fr", "de", "it"], resolved_year: 2024, as_of: "2026-09-01"},
      aggregate: {
        coverage: {members: 3, reported: 2, missing: ["it"], complete: false},
        spread: {}, strategies,
      },
    }, false);
  }
  const ENGLISH = "1 of 3 members did not report this indicator for this period (IT). A figure over the "
    + "members that happen to have reported is not the group's figure, and nothing downstream could "
    + "tell the difference. Choose 'Compute over the members that did report' to compute it anyway — "
    + "the missing members travel with the result.";

  await test("X5: the refusal is the reader's language and names the button by its own label", async () => {
    const fr = LOCALE("fr");
    const html = govHtml("fr", {sum: {label: "Sum", refused: ENGLISH, refused_code: "incomplete"}});
    const button = fr["Compute over the members that did report"];
    assert(html.indexOf("« " + button + " »") !== -1, "the button is not named by its French label: " + html);
    assert(html.indexOf("1 sur 3") !== -1, "the counts did not reach the frame");
    assert(html.indexOf("allow_incomplete") === -1 && html.indexOf("did not report") === -1,
      "English (or the parameter name) leaked into the French refusal: " + html);
  });

  await test("X5: any OTHER refusal is still the engine's sentence, verbatim", async () => {
    const html = govHtml("fr", {sum: {label: "Sum", refused: "Not a statistic at all."}});
    assert(html.indexOf("Not a statistic at all.") !== -1, "a non-roster refusal was rewritten");
  });

  // ======================= X6: Quality gates ================================= //
  function qual(lang, extra) {
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      ${extract("_qualTf", null, QUAL)}
      ${extract("_qualTfHtml", null, QUAL)}
      ${extract("_qualShare", null, QUAL)}
      ${extract("_qualTunableHtml", null, QUAL)}
      this.tfHtml = _qualTfHtml; this.tunable = _qualTunableHtml;
    `;
    const sb = {I: i18n(lang, extra)};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb;
  }
  const JUDGED = "Judged so far — qualified: {qualified} · disqualified: {disqualified} · not yet judged: {unqualified}";

  await test("X6: the headline is ONE keyed frame, label before count, markup kept as markup", async () => {
    const q = qual("fr");
    const out = q.tfHtml(JUDGED, {qualified: "<b>4</b>", disqualified: "<b>1</b>", unqualified: "<b>0</b>"});
    assert(out.indexOf("qualifiées : <b>4</b>") !== -1, "French label/count not in the frame: " + out);
    assert(!/<b>4<\/b>\s*qualifi/.test(out), "a count still precedes its label: " + out);
  });

  await test("X6: a translation is text, never markup", async () => {
    const q = qual("fr", {"Collecting now: {n}": "<i>x</i> {n}"});
    const out = q.tfHtml("Collecting now: {n}", {n: "<b>7</b>"});
    assert(out === "&lt;i&gt;x&lt;/i&gt; <b>7</b>", "the frame's own text was not escaped: " + out);
  });

  await test("X6: every tunable sentence goes through t() -- label, unit and the hover", async () => {
    const q = qual("en", {L: "L-x", U: "U-x", I: "I-x", F: "F-x"});
    const out = q.tunable({label: "L", unit: "U", impact: "I", floor_reason: "F", value: 5, lo: 1, hi: 9});
    assert(out.indexOf("<b>L-x</b>") !== -1, "label not translated: " + out);
    assert(out.indexOf(">U-x<") !== -1, "unit not translated: " + out);
    assert(out.indexOf('title="I-x — F-x"') !== -1, "hover not translated: " + out);
  });

  await test("X6: the share reading still keys off the ENGLISH unit (logic is not translated)", async () => {
    const q = qual("fr");
    const out = q.tunable({label: "Not prose below", unit: "share of tokens that are function words (0–1)",
      impact: "", floor_reason: "", value: 0.12, lo: 0.02, hi: 0.35});
    assert(out.indexOf("0.12 (12%)") !== -1, "the percent reading was lost under French: " + out);
    assert(out.indexOf(LOCALE("fr")["share of tokens that are function words (0–1)"]) !== -1, "unit not French");
  });

  // ======================= X7: Database & storage ============================ //
  function lib(lang, state) {
    const calls = {api: [], paint: []};
    const els = {"db-file": {innerHTML: ""}, "db-stats": {innerHTML: ""},
      "library-storage": {id: "library-storage", innerHTML: "", querySelector: () => (state.painted ? {} : null)},
      "vitals-storage": {id: "vitals-storage", innerHTML: "", querySelector: () => null}};
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      const document = { getElementById: (id) => this.els[id] || null };
      const $ = (id) => this.els[id] || null;
      const calls = this.calls;
      async function api(p) { calls.api.push(p); throw new Error("no fetch expected: " + p); }
      const humanBytes = (n) => n + " B";
      const _fmtBytes = (n) => n + " B";
      function _sfPaint(host) { calls.paint.push(host.id); }
      let _dbStatsLast = this.state.last, _sfCache = this.state.sf, _sfPending = this.state.pending;
      let DB_KEYS = this.state.keys;
      ${extract("_paintDbFile", null, LIB)}
      ${extract("repaintDbStorageFromCache", null, LIB)}
      this.repaint = repaintDbStorageFromCache;
    `;
    const sb = {I: i18n(lang), els, calls, state};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    return sb;
  }
  const STATS = {backend: "sqlite", file: {bytes: 1024, path: "/d/open_omniscience.db"}};

  await test("X7: a language switch repaints #db-file and the footprint from cache, no fetch", async () => {
    const fr = LOCALE("fr");
    const sb = lib("fr", {last: STATS, sf: {totals: {grand_total_bytes: 2048}, components: []}, pending: null,
      keys: "files", painted: true});
    sb.repaint();
    const html = sb.els["db-file"].innerHTML;
    assert(html.indexOf(fr["Backend"]) !== -1 && html.indexOf(fr["on disk"]) !== -1, "not repainted in French: " + html);
    assert(html.indexOf("Backend") === -1, "English survived the switch: " + html);
    assert(sb.calls.paint.join() === "library-storage", "the drawn footprint was not repainted: " + sb.calls.paint);
    assert(sb.calls.api.length === 0, "the switch fetched: " + sb.calls.api);
  });

  await test("X7: a footprint still measuring is left to its own fetch; an empty store is keyed", async () => {
    const zh = LOCALE("zh");
    const sb = lib("zh", {last: STATS, sf: {totals: {}}, pending: Promise.resolve(), keys: "", painted: true});
    sb.repaint();
    assert(sb.calls.paint.length === 0, "painted over a measurement in flight");
    assert(sb.els["db-stats"].innerHTML.indexOf(zh["No tables yet."]) !== -1, "empty grid not repainted");
  });

  // ======================= X8: Home "Automatic collection" =================== //
  function homeStatus(lang, running) {
    const el = {innerHTML: ""};
    const src = `
      const window = { OOI18N: this.I };
      const OOI18N = this.I;
      ${ESC}
      const $ = (id) => (id === "home-status" ? this.el : null);
      let _homeRunningLast = null;
      function _homeGlanceWhenReady() {}
      ${extract("renderHomeStatus", null, HOME)}
      this.render = renderHomeStatus;
    `;
    const sb = {I: i18n(lang), el};
    // eslint-disable-next-line no-new-func
    new Function(src).call(sb);
    sb.render(running);
    return el.innerHTML;
  }

  await test("X8: the colon is the locale's, inside a frame around the state pill", async () => {
    // Since re-walk U-10 the state word is part of the frame too (one sentence per state,
    // the pill's edges marked by {pill}/{endpill}), so it agrees with its noun: French
    // 'Collecte ... arrêtée', never the generic 'arrêté'.
    const f = homeStatus("fr", false);
    assert(f.indexOf("Collecte automatique : <span class=\"pill \">arrêtée</span>") === 0,
      "French lost its space before the colon, or its agreement: " + f);
    const z = homeStatus("zh", true);
    assert(z.indexOf("自动采集：<span class=\"pill ok\">运行中</span>") === 0, "Chinese colon: " + z);
    const e = homeStatus("en", true);
    assert(e.indexOf("Automatic collection: <span class=\"pill ok\">running</span>") === 0, "English: " + e);
    const s = homeStatus("en", false);
    assert(s.indexOf("Automatic collection: <span class=\"pill \">stopped</span>") === 0, "English stopped: " + s);
  });

  console.log("all assertions passed (" + passed + " tests)");
}

run().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
