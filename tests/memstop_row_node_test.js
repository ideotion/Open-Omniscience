/**
 * The clean stop's three UI surfaces (B2), run as the SHIPPED code extracted by name from src/static/app-core.js, with the REAL
 * locale files: the Sessions row names a session the app ended itself for memory (and its hover carries the caveat), the task
 * manager words the phase while the stop runs, and a one-time toast is shown per stop and never twice for the same one.
 *
 * Run by tests/test_memstop_row.py (and standalone: `node tests/memstop_row_node_test.js`).
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const CORE = fs.readFileSync(path.join(STATIC, "app-core.js"), "utf-8");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));
const CODES = ["ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"];

function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function extract(name, decl) {
  const head = decl || ("function " + name + "(");
  const at = CORE.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = CORE.indexOf("(", at); j < CORE.length; j++) {
    if (CORE[j] === "(") p++;
    else if (CORE[j] === ")") { p--; if (p === 0) { i = CORE.indexOf("{", j); break; } }
  }
  let depth = 0;
  for (let j = i; j < CORE.length; j++) {
    if (CORE[j] === "{") depth++;
    else if (CORE[j] === "}") { depth--; if (depth === 0) return CORE.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}
const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c])));
const i18n = (lang) => {
  const map = lang === "en" ? {} : LOCALE(lang);
  return { t: (s) => (map[s] == null ? s : map[s]), tf: (s, v) => (map[s] == null ? s : map[s]).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? v[k] : m)) };
};

const EN_PHASE = "The app is stopping itself because memory stayed exhausted";
const EN_ROW = "Stopped itself — memory stayed exhausted";
const EN_HOVER = "The app ended this session itself because available memory stayed at the floor while collection was paused, and the memory it held did not come back. Your saved data was not touched. Work that was in progress when it stopped was not finished, and stays stopped until you start it again.";
const EN_TOAST = "The app stopped itself last time because memory stayed exhausted. Your saved data was not touched, and work that was in progress then was not finished. Start collection again when you are ready.";

let passed = 0;
async function test(name, fn) { await fn(); passed += 1; console.log("ok  - " + name); }

function sessionHtml(lang) {
  const I = i18n(lang);
  const src = [`const esc = ${esc.toString()};`, "const fmtNum = (n) => String(n);", "const fmtDateTime = (x) => 'T:' + x;",
    extract("_sessionHtml"), "return _sessionHtml;"].join("\n");
  return new Function("window", src)({ OOI18N: I });
}

(async () => {
  await test("every locale keys the four strings", async () => {
    for (const code of CODES) {
      const d = LOCALE(code);
      for (const k of [EN_PHASE, EN_ROW, EN_HOVER, EN_TOAST]) assert(d[k] && d[k].trim(), `${code} lacks ${k.slice(0, 40)}`);
      if (code !== "en") for (const k of [EN_PHASE, EN_ROW, EN_HOVER, EN_TOAST]) assert(d[k] !== k, `${code} leaves ${k.slice(0, 40)} in English`);
    }
  });

  await test("the Sessions row names a memory stop, in every language, and its hover is the caveat", async () => {
    for (const code of CODES) {
      const I = i18n(code), d = code === "en" ? {} : LOCALE(code);
      const html = sessionHtml(code)({ since_last_restart_s: 60, previous_session_end: { at: "2026-10-15T19:00:00Z", clean: true, basis: "the app's own shutdown", stopped_for: "memory" } });
      assert(html.includes(esc(I.t(EN_ROW))), `${code}: the row names the stop`);
      assert(html.includes(`title="${esc(I.t(EN_HOVER))}"`), `${code}: the hover carries the caveat`);
      assert(!html.includes(`>${esc(I.t("clean shutdown"))} ·`), `${code}: it is not worded as a clean shutdown`);
    }
  });

  await test("an ordinary end keeps its old words and its basis hover", async () => {
    const html = sessionHtml("en")({ since_last_restart_s: 60, previous_session_end: { at: "2026-10-15T19:00:00Z", clean: false, basis: "no end record", stopped_for: null } });
    assert(html.includes("unclean end") && html.includes('title="no end record"') && !html.includes("Stopped itself"), html);
  });

  await test("the phase is worded while the stop runs, and an override cannot hide it", async () => {
    const f = new Function(extract("_storagePausedText") + "; return _storagePausedText;")();
    assert(f("memory-stop", null) === EN_PHASE, "worded");
    assert(f("memory-stop", { overridden: true }) === EN_PHASE, "not a limit the override covers");
    assert(f("collecting", null) === null, "other phases are unchanged");
  });

  function notice(vitals, store) {
    const shown = [];
    const src = [extract("memoryStopNoticeOnce", "async function memoryStopNoticeOnce("), "return memoryStopNoticeOnce;"].join("\n");
    const run = new Function("api", "localStorage", "toast", "window", src)(
      async () => vitals, store, (msg, kind) => shown.push([msg, kind]), { OOI18N: i18n("fr") });
    return { run, shown };
  }
  const stopped = { session: { previous_session_end: { at: "2026-10-15T19:00:00Z", stopped_for: "memory" } } };

  await test("the toast shows once per stop, in the UI language, and again for a later stop", async () => {
    const mem = {}; const store = { getItem: (k) => (k in mem ? mem[k] : null), setItem: (k, v) => { mem[k] = v; } };
    let n = notice(stopped, store); await n.run();
    assert(n.shown.length === 1 && n.shown[0][0] === LOCALE("fr")[EN_TOAST], "shown in French: " + JSON.stringify(n.shown));
    n = notice(stopped, store); await n.run();
    assert(n.shown.length === 0, "not twice for the same stop");
    n = notice({ session: { previous_session_end: { at: "2026-10-16T08:00:00Z", stopped_for: "memory" } } }, store); await n.run();
    assert(n.shown.length === 1, "a later stop toasts again");
  });

  await test("no toast without a memory stop, and a failing vitals read is silent", async () => {
    const store = { getItem: () => null, setItem: () => {} };
    let n = notice({ session: { previous_session_end: { at: "x", clean: true, stopped_for: null } } }, store); await n.run();
    assert(n.shown.length === 0, "nothing to say");
    const bad = new Function("api", "localStorage", "toast", "window",
      extract("memoryStopNoticeOnce", "async function memoryStopNoticeOnce(") + "; return memoryStopNoticeOnce;")(
      async () => { throw new Error("offline"); }, store, () => { throw new Error("no toast"); }, { OOI18N: i18n("en") });
    await bad();
  });

  await test("a browser without storage still shows the toast rather than none", async () => {
    const store = { getItem: () => { throw new Error("blocked"); }, setItem: () => { throw new Error("blocked"); } };
    const n = notice(stopped, store); await n.run();
    assert(n.shown.length === 1, "shown");
  });

  console.log(`all assertions passed (${passed} tests)`);
})();
