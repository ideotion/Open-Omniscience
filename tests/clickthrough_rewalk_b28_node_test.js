/**
 * Behavioural node test for batch B28 of the 2026-09-27 re-walk (Settings → Advanced →
 * Quality gates, row S): the backlog line follows every write on the panel (S-3); the
 * memory floor's reason is written in the UI language (S-5); the merge refusals are keyed
 * and repaint on a switch (S-6); a machine the floor declines never offers the consent
 * popup, and its button says why (S-7); the audit's gap line is a sentence and its caveats
 * use the typographic dash (S-9); the adopt / revert toasts pick one/many frames (S-11);
 * the backlog count is a sentence with a singular (S-12).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name -- a re-typed
 * copy would pass while the real code was still broken (the sibling-test convention).
 * Translations come from the REAL locale files. The server payloads come from the SERVER'S
 * OWN FUNCTIONS when tests/test_clickthrough_rewalk_b28.py runs this file (it passes them
 * in B28_PAYLOADS); standalone, the copies below are used.
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const read = (name) => fs.readFileSync(path.join(STATIC, name), "utf-8");
const CORE = read("app-core.js");
const AI = read("app-ai-tools.js");
const MARKETS = read("app-markets.js");
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
// An `async function` is extracted with its keyword, so the copy is still async.
const A = (name) => extract(name, AI.indexOf("async function " + name + "(") !== -1
  ? "async function " + name + "(" : null, AI);
const C = (name) => extract(name, null, CORE);

const ESC = `const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
  c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","'":"&#39;"}[c])));`;
const NNBSP = "\u202f";
const fill = (frame, v) => frame.replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));
const FMTNUM = extract("fmtNum", null, MARKETS);

// A fake i18n engine over a real locale: t()/tf() behave like src/static/i18n.js (an
// unknown key renders its English). `lang` may be switched live, like OOI18N.setLang.
function i18n(lang) {
  const I = {
    lang,
    map: lang === "en" ? {} : LOCALE(lang),
    set(code) { I.lang = code; I.map = code === "en" ? {} : LOCALE(code); },
    t: (s) => (I.map[s] == null ? s : I.map[s]),
    tf: (s, v) => {
      let out = I.map[s] == null ? s : I.map[s];
      if (v) out = out.replace(/\{(\w+)\}/g, (m, k) => (v[k] == null ? m : String(v[k])));
      return out;
    },
  };
  return I;
}

// ---- the server shapes ------------------------------------------------------------- //
const GIVEN = process.env.B28_PAYLOADS ? JSON.parse(process.env.B28_PAYLOADS) : null;
// machine_floor(total_mb=3924, available_mb=800) -- the field's machine A.
const FLOOR = (GIVEN && GIVEN.floor) || {
  declines: true, below: true, overridden: false, override_env: "OO_ALLOW_BIG_SCANS",
  reason: "this machine has 3924 MB of RAM with 800 MB available — total under the 4096 MB floor and available under the 1024 MB floor",
  reason_i18n: "this machine has {ram} with {available} — {verdict}",
  reason_vars: {
    ram: {i18n: "{mb} MB of RAM", vars: {mb: 3924.0}},
    available: {i18n: "{mb} MB available", vars: {mb: 800.0}},
    verdict: {i18n: "total under the {total_floor} MB floor and available under the {available_floor} MB floor",
      vars: {total_floor: 4096.0, available_floor: 1024.0}},
  },
};
// The merge route's 400 for {"hello": "world"} named not-an-export.json.
const REFUSAL = (GIVEN && GIVEN.refusal) || {
  detail: "not-an-export.json: no 'verdicts' list — is this a source-qualification export?",
  detail_i18n: "{file}: no 'verdicts' list — is this a source-qualification export?",
  detail_vars: {file: "not-an-export.json"},
};
// admission_audit()'s prose.
const AUDIT_PROSE = (GIVEN && GIVEN.audit) || null;

function el(extra) {
  const e = {textContent: "", innerHTML: "", title: "", disabled: false, dataset: {}, style: {}, attrs: {},
    setAttribute(k, v) { if (k === "title") e.title = String(v); else e.attrs[k] = String(v); },
    getAttribute(k) { return k === "title" ? (e.title || null) : (e.attrs[k] == null ? null : e.attrs[k]); },
    removeAttribute(k) { if (k === "title") e.title = ""; else delete e.attrs[k]; },
    querySelectorAll() { return []; }};
  return Object.assign(e, extra || {});
}

async function run() {
  // ================================================================ S-5 ============== //
  await test("S-5: the floor's reason is written in the UI language, with formatted numbers", async () => {
    for (const lang of ["fr", "ar", "zh", "en"]) {
      const I = i18n(lang), L = lang === "en" ? {} : LOCALE(lang);
      const tl = (k) => (L[k] == null ? k : L[k]);
      const src = [FMTNUM, C("_jobLabel"), C("_framedText"), A("_qualTf"), A("_qualDeclinedText"),
        "return _qualDeclinedText;"].join("\n");
      // eslint-disable-next-line no-new-func
      const f = new Function("window", "OOI18N", src)({OOI18N: I}, I);
      const got = f(FLOOR.reason, FLOOR.override_env, FLOOR.reason_i18n, FLOOR.reason_vars);
      const v = FLOOR.reason_vars;
      const want = fill(tl(FLOOR.reason_i18n), {
        ram: fill(tl(v.ram.i18n), {mb: "3" + NNBSP + "924"}),
        available: fill(tl(v.available.i18n), {mb: "800"}),
        verdict: fill(tl(v.verdict.i18n), {total_floor: "4" + NNBSP + "096", available_floor: "1" + NNBSP + "024"}),
      });
      assert(got.indexOf("(" + want + ")") !== -1, `${lang}: ${got}\n  wanted (${want})`);
      if (lang !== "en") {
        assert(!/this machine has|MB of RAM|under the/.test(got), `${lang}: English left in the refusal: ${got}`);
        assert(got.indexOf(L["Qualification is declined on this machine: it is below the memory floor, so no candidate is judged."]) === 0,
          `${lang}: the refusal lost its lead sentence: ${got}`);
      }
    }
    // An older server with no frame still shows its English as data -- never nothing.
    const I = i18n("fr");
    const src = [FMTNUM, C("_jobLabel"), C("_framedText"), A("_qualTf"), A("_qualDeclinedText"),
      "return _qualDeclinedText;"].join("\n");
    // eslint-disable-next-line no-new-func
    const f = new Function("window", "OOI18N", src)({OOI18N: I}, I);
    assert(f("raw reason", "OO_ALLOW_BIG_SCANS").indexOf("(raw reason)") !== -1, "a frameless reason vanished");
  });

  // ================================================================ S-7 / S-12 ======== //
  function bulk(lang, status) {
    const I = i18n(lang);
    const els = {"qualify-bulk-status": el(), "qualify-bulk-cancel-btn": el(), "qualify-bulk-btn": el()};
    const src = [ESC, FMTNUM, C("_jobLabel"), C("_framedText"), A("_qualTf"), A("_qualDeclinedText"),
      A("loadQualifyBulk"), "return loadQualifyBulk;"].join("\n");
    let st = status;
    // eslint-disable-next-line no-new-func
    const f = new Function("window", "OOI18N", "$", "api", src)({OOI18N: I}, I, (id) => els[id] || null,
      async () => st);
    return {f, els, I, set: (s) => { st = s; }};
  }
  const IDLE = (backlog, floor) => ({running: false, backlog: {unqualified: backlog, due_disqualified: 0}, floor});

  await test("S-12: the backlog count is a sentence, one/many, and the decline follows its full stop", async () => {
    const one = bulk("en", IDLE(1, {declines: false}));
    await one.f();
    assert(one.els["qualify-bulk-status"].textContent === "1 candidate awaiting qualification.",
      "en one: " + one.els["qualify-bulk-status"].textContent);
    const many = bulk("en", IDLE(6, FLOOR));
    await many.f();
    const line = many.els["qualify-bulk-status"].textContent;
    assert(line.indexOf("6 candidates awaiting qualification. Qualification is declined") === 0,
      "en: the count and the decline must be two sentences: " + line);
    for (const lang of ["fr", "zh", "ar"]) {
      const L = LOCALE(lang), b = bulk(lang, IDLE(6, FLOOR));
      await b.f();
      const got = b.els["qualify-bulk-status"].textContent;
      const lead = fill(L["{n} candidates awaiting qualification."], {n: "6"});
      // A full-width stop carries its own spacing; a Latin one is followed by a space.
      const sep = /[。！？]$/.test(lead) ? "" : " ";
      assert(got.indexOf(lead + sep + L["Qualification is declined on this machine: it is below the memory floor, so no candidate is judged."]) === 0,
        `${lang}: ${got}`);
      assert(!/candidates awaiting/.test(got), `${lang}: English count left: ${got}`);
      assert(!/[。！？] /.test(got), `${lang}: a Latin space after a full-width stop: ${got}`);
    }
  });

  await test("S-7: below the floor the button is disabled and says why; above it, it comes back", async () => {
    const b = bulk("fr", IDLE(6, FLOOR));
    await b.f();
    const btn = b.els["qualify-bulk-btn"];
    assert(btn.disabled === true, "the button must be disabled when the floor declines");
    // It says why through the line it is described by, which is written in the UI language.
    assert(btn.getAttribute("aria-describedby") === "qualify-bulk-status",
      "the disabled button must be described by the line that names the refusal: " + JSON.stringify(btn.attrs));
    const why = b.els["qualify-bulk-status"].textContent;
    assert(why.indexOf(LOCALE("fr")["Qualification is declined on this machine: it is below the memory floor, so no candidate is judged."]) !== -1
      && why.indexOf("OO_ALLOW_BIG_SCANS=1") !== -1, "the describing line must name the refusal and its override: " + why);
    // No title: the i18n walker would freeze one in the language it was first set in.
    assert(btn.title === "", "a title on this static button freezes in its first language: " + btn.title);
    b.set(IDLE(6, {declines: false}));
    await b.f();
    assert(btn.disabled === false && btn.getAttribute("aria-describedby") === null,
      "a lifted floor must give the button back: " + JSON.stringify(btn.attrs));
    // A button disabled by someone else (a run in flight) is not this loader's to lift.
    const c = bulk("en", IDLE(6, {declines: false}));
    c.els["qualify-bulk-btn"].disabled = true;
    await c.f();
    assert(c.els["qualify-bulk-btn"].disabled === true, "the loader lifted a state it did not set");
  });

  await test("S-7: pressing the button on a declining machine never opens the consent popup", async () => {
    const I = i18n("en");
    const calls = [];
    const els = {"qualify-bulk-status": el(), "qualify-bulk-cancel-btn": el()};
    const src = [FMTNUM, C("_jobLabel"), C("_framedText"), A("_qualTf"), A("_qualDeclinedText"),
      C("_jobStillRunning"), A("qualifyBulkStart"), "return qualifyBulkStart;"].join("\n");
    // eslint-disable-next-line no-new-func
    const start = new Function("window", "OOI18N", "$", "api", "ensureOnline", "pollJobStatus", "loadQualifyBulk", src)(
      {OOI18N: I}, I, (id) => els[id] || null,
      async (url, opts) => { calls.push((opts && opts.method || "GET") + " " + url); return {floor: FLOOR}; },
      async () => { calls.push("ensureOnline"); return true; },
      async () => { calls.push("poll"); return {state: "done"}; },
      () => { calls.push("loadQualifyBulk"); });
    await start({disabled: false});
    assert(calls.indexOf("ensureOnline") === -1, "the consent popup opened for a job the floor refuses: " + calls);
    assert(!calls.some((c) => c.indexOf("POST") === 0), "the job was started anyway: " + calls);
    assert(calls.indexOf("loadQualifyBulk") !== -1, "the refusal must be drawn by the panel's loader: " + calls);
    // Above the floor nothing changes: the popup is asked, then the job starts.
    const calls2 = [];
    const start2 = new Function("window", "OOI18N", "$", "api", "ensureOnline", "pollJobStatus", "loadQualifyBulk", src)(
      {OOI18N: I}, I, (id) => els[id] || null,
      async (url, opts) => { calls2.push((opts && opts.method || "GET") + " " + url); return {floor: {declines: false}, started: true}; },
      async () => { calls2.push("ensureOnline"); return true; },
      async () => ({state: "done", result: {qualified: 0, disqualified: 0, no_evidence: 0}}), () => {});
    await start2(null);
    assert(calls2.indexOf("ensureOnline") !== -1 && calls2.some((c) => c.indexOf("POST") === 0),
      "above the floor the run must still ask consent and start: " + calls2);
  });

  // ================================================================ S-11 / S-3 ======== //
  function writer(lang, name, reply) {
    const I = i18n(lang);
    const log = {toasts: [], loads: []};
    // _qualRefresh is the fix's helper; taken only when it exists, so on the unfixed code
    // this fails on the toast and the loaders it measures, not on a missing name.
    const refresh = AI.indexOf("function _qualRefresh(") !== -1 ? A("_qualRefresh") : "";
    const src = [FMTNUM, A("_qualTf"), refresh, A(name), "return " + name + ";"].join("\n");
    // eslint-disable-next-line no-new-func
    const f = new Function("window", "OOI18N", "api", "toast", "confirm", "loadQualificationGates", "loadQualifyBulk",
      "_apiErrorMessage", src)({OOI18N: I}, I, async () => reply, (m, k) => log.toasts.push([m, k]), () => true,
      () => log.loads.push("gates"), () => log.loads.push("bulk"), (e) => String(e));
    return {f, log};
  }
  await test("S-11: the adopt and revert toasts read in the singular for one", async () => {
    const cases = [
      ["overlayAdopt", {adopted: 3, admitted: 1}, "Adopted 3 verdicts; 1 source started being collected."],
      ["overlayAdopt", {adopted: 1, admitted: 1}, "Adopted 1 verdict; 1 source started being collected."],
      ["overlayAdopt", {adopted: 1, admitted: 0}, "Adopted 1 verdict; 0 sources started being collected."],
      ["overlayAdopt", {adopted: 3, admitted: 2}, "Adopted 3 verdicts; 2 sources started being collected."],
      ["overlayRevert", {reverted: 3, admissions_undone: 1}, "Put back 3 sources; 1 admission undone."],
      ["overlayRevert", {reverted: 1, admissions_undone: 1}, "Put back 1 source; 1 admission undone."],
      ["overlayRevert", {reverted: 1, admissions_undone: 2}, "Put back 1 source; 2 admissions undone."],
      ["overlayRevert", {reverted: 3, admissions_undone: 0}, "Put back 3 sources; 0 admissions undone."],
    ];
    for (const [name, reply, want] of cases) {
      const w = writer("en", name, reply);
      await w.f(null);
      assert(w.log.toasts[0] && w.log.toasts[0][0] === want, `${name} ${JSON.stringify(reply)}: ${w.log.toasts[0]}`);
    }
    const fr = LOCALE("fr");
    const w = writer("fr", "overlayAdopt", {adopted: 3, admitted: 1});
    await w.f(null);
    assert(w.log.toasts[0][0] === fill(fr["Adopted {n} verdicts; {admitted} source started being collected."], {n: "3", admitted: "1"}),
      "fr: " + w.log.toasts[0][0]);
  });

  await test("S-3: undo, adopt, revert and a settings write all repaint the backlog line", async () => {
    for (const [name, reply] of [["overlayAdopt", {adopted: 1}], ["overlayRevert", {reverted: 1}]]) {
      const w = writer("en", name, reply);
      await w.f(null);
      assert(w.log.loads.indexOf("gates") !== -1 && w.log.loads.indexOf("bulk") !== -1,
        `${name} must refresh both loaders: ${w.log.loads}`);
    }
    const w = writer("en", "_qualPut", {});
    await w.f({qualification_per_pass: 0});
    assert(w.log.loads.indexOf("bulk") !== -1, "a settings write must refresh the backlog line: " + w.log.loads);
    const undo = writer("en", "undoAdmission", {undone: true});
    await undo.f(7, {disabled: false});
    assert(undo.log.loads.indexOf("bulk") !== -1, "an undo must refresh the backlog line: " + undo.log.loads);
  });

  // ================================================================ S-6 =============== //
  await test("S-6: a keyed merge refusal is written in the UI language and follows a switch", async () => {
    const I = i18n("fr");
    const els = {"qual-ov-merge-out": el(), "qual-ov-files": {files: [{name: "not-an-export.json"}]}};
    let res = {ok: false, status: 400, statusText: "Bad Request", json: async () => REFUSAL};
    const saved = [];
    const src = [ESC, FMTNUM, C("_jobLabel"), C("_framedText"), C("_apiErrorMessage"), A("_qualTf"),
      "var _qualMergeLast = null; var _qualMergeRefusal = null;",
      A("overlayMerge"), A("_renderOverlayMerge"),
      "return {merge: overlayMerge, render: _renderOverlayMerge};"].join("\n");
    // eslint-disable-next-line no-new-func
    const m = new Function("window", "OOI18N", "$", "fetch", "FormData", "_overlaySaveAs", src)(
      {OOI18N: I}, I, (id) => els[id] || null, async () => res, class { append() {} },
      (text, name) => saved.push(name));
    const want = (lang) => {
      const frame = LOCALE(lang)[REFUSAL.detail_i18n];
      assert(frame, `${lang}: the merge refusal is not keyed: ${REFUSAL.detail_i18n}`);
      return fill(frame, {file: "\u2068" + REFUSAL.detail_vars.file + "\u2069"});
    };
    await m.merge({disabled: false});
    const out = els["qual-ov-merge-out"];
    assert(!/no 'verdicts' list|is this a/.test(out.textContent), "fr: English left: " + out.textContent);
    assert(out.textContent === want("fr"), "fr: " + out.textContent);
    assert(saved.length === 0, "a refused merge must not download anything");
    I.set("zh");
    m.render();
    assert(out.textContent === want("zh"), "a switch must redraw the refusal: " + out.textContent);
    // A later success replaces the refusal and is what a switch redraws from then on.
    res = {ok: true, status: 200, json: async () => ({merged_verdicts: 2, overlay_yaml: "verdicts: []\n",
      note: "n", report: {added: 1, updated: 0, carried_through_untouched: 1, conflicts: [], inputs: []}})};
    await m.merge({disabled: false});
    I.set("fr");
    m.render();
    assert(out.innerHTML.indexOf(fill(LOCALE("fr")["{n} verdicts in the merged file"], {n: 2})) !== -1,
      "the report must win over an old refusal: " + out.innerHTML);
  });

  // ================================================================ S-9 =============== //
  await test("S-9: the gap line is a sentence before its note, and the caveats carry no ASCII --", async () => {
    const prose = AUDIT_PROSE || {
      caveat: Object.keys(LOCALE("en")).find((k) => k.startsWith("Admission is about EXTRACTION VALIDITY")),
      coverage_note: Object.keys(LOCALE("en")).find((k) => k.startsWith("This lists admissions made by judging")),
    };
    assert(prose.caveat && prose.coverage_note, "the audit prose was not found");
    for (const lang of ["en", "fr", "zh", "ar"]) {
      const I = i18n(lang), L = lang === "en" ? null : LOCALE(lang);
      const host = el();
      const src = [ESC, C("ooLabelHtml"), A("_qualTf"), A("_admissionRow"), A("loadAdmissionAudit"),
        "return loadAdmissionAudit;"].join("\n");
      // eslint-disable-next-line no-new-func
      const f = new Function("window", "OOI18N", "$", "api", "undoAdmission", "_apiErrorMessage", src)(
        {OOI18N: I}, I, (id) => (id === "qual-admission" ? host : null),
        async () => ({events: [{id: 1, domain: "a.example", prior_enabled: false, prior_status: "unqualified",
          occurred_at: "2026-09-18T09:00:00+00:00", reversible: true}], total: 1, undone_total: 0,
          collecting: 3, unaccounted: 2, caveat: prose.caveat, coverage_note: prose.coverage_note}),
        () => {}, (e) => String(e));
      await f();
      const tl = (k) => (L && L[k] != null ? L[k] : k);
      const gap = fill(tl("{n} of {total} collecting sources are not accounted for here."), {n: 2, total: 3});
      const escd = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
      // A full-width stop carries its own spacing; a Latin one is followed by a space.
      const sep = /[。！？]$/.test(gap) ? "" : " ";
      assert(host.innerHTML.indexOf(escd(gap) + sep + escd(tl(prose.coverage_note))) !== -1,
        `${lang}: the gap sentence and its note: ${host.innerHTML}`);
      assert(!/。 /.test(host.innerHTML), `${lang}: a Latin space after a full-width stop: ${host.innerHTML}`);
      assert(/[.。]$/.test(gap), `${lang}: the gap line has no full stop: ${gap}`);
      if (lang === "en") assert(!/ -- /.test(host.innerHTML), "en: an ASCII -- is left in the audit: " + host.innerHTML);
    }
  });

  console.log(`\nall assertions passed (${passed} tests)`);
}

run().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
