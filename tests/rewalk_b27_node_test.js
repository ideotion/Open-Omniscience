// Re-walk 2026-09-27, batch B27: the behaviour behind rows M-14, T-2, U-11, T-7, H-3,
// T-5, T-6 and T-8, run as real, EXTRACTED code (never re-typed) against small fakes.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Every check below runs independently and all failures are listed together, so a
// regression names every row it reopens rather than the first one.
//
//   M-14  the network-consent popup's "Go online" stays disabled until the lane list and
//         the interface list are both rendered, each read or honestly marked unreadable;
//         a slow read is bounded, and its late answer still replaces "could not read".
//   T-2   the DOM walker leaves an attribute alone when an ANCESTOR carries
//         data-i18n-dyn, so a self-translated hover is not frozen in its first language.
//   U-11  the guided-setup theme chips render a source tag verbatim (data-i18n-dyn) and
//         the count through fmtNum.
//   T-7   the red AI pill's hover leads with a KEYED sentence, not the server's English.
//   H-3   Help's "Find on this page" runs its highlight-and-scroll OUTSIDE the keystroke.
//   T-5   neither schedule view prints the retired "Mode" row.
//   T-6   /tasks paints the health dot in the state's colour class.
//   T-8   /tasks takes the app's theme from localStorage "oo.ui", as the app writes it.

"use strict";

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const APP = require("./app_source.js").appJs();
const I18N = fs.readFileSync(path.join(STATIC, "i18n.js"), "utf-8");
const TM = fs.readFileSync(path.join(STATIC, "taskmanager.html"), "utf-8");
const loc = (c) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", c + ".json"), "utf-8"));
const FR = loc("fr"), AR = loc("ar");

function has(src, name) { return src.indexOf("function " + name + "(") !== -1; }
function extract(src, name) {
  const at = src.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const start = src.slice(Math.max(0, at - 6), at) === "async " ? at - 6 : at;
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  let d = 0, j = open;
  for (; j < src.length; j++) {
    if (src[j] === "{") d++;
    else if (src[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return src.slice(start, j) + "\n";
}
const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

// A clock the test drives: timers fire in order, and every pending promise reaction runs
// between two of them, so "what the popup shows at t" is a fact rather than a race.
function makeClock() {
  let now = 0, seq = 0;
  const timers = [];
  const flush = () => new Promise((r) => setImmediate(r));
  return {
    setTimeout: (fn, ms) => { const id = ++seq; timers.push({ id, at: now + (ms || 0), fn }); return id; },
    clearTimeout: (id) => { const k = timers.findIndex((x) => x.id === id); if (k >= 0) timers.splice(k, 1); },
    pending: () => timers.length,
    async advanceTo(T) {
      for (;;) {
        await flush(); await flush();
        timers.sort((a, b) => a.at - b.at || a.id - b.id);
        const nx = timers[0];
        if (!nx || nx.at > T) { now = T; await flush(); return; }
        timers.shift(); now = nx.at; nx.fn();
      }
    },
  };
}

const failures = [];
async function check(label, fn) {
  try { await fn(); console.log("  ok  " + label); }
  catch (e) { failures.push(label + ": " + (e && e.message ? e.message : e)); console.log("  FAIL " + label); }
}

// ---------------------------------------------------------------- M-14 --- //
const _budgetMatch = APP.match(/const _NET_CONSENT_READ_MS = (\d+);/);
const BUDGET = _budgetMatch ? Number(_budgetMatch[1]) : 2000;

function consentHarness(delays, values) {
  const clock = makeClock();
  const el = () => ({ textContent: "", style: {}, disabled: false, onclick: null });
  const reasonB = el();
  const dlg = { open: false, oncancel: null,
    querySelector: (s) => (s === "#net-consent-reason b" ? reasonB : null),
    showModal() { this.open = true; }, close() { this.open = false; } };
  const nodes = { "net-consent": dlg, "net-consent-lanes": el(), "net-consent-ifaces": el(),
    "net-consent-ok": el(), "net-consent-cancel": el() };
  const document = { getElementById: (id) => nodes[id] || null };
  const renders = [];
  const api = (p) => new Promise((res, rej) => {
    const d = delays[p];
    if (d === undefined) { rej(new Error("unexpected read " + p)); return; }
    if (d === Infinity) return;   // never answers
    clock.setTimeout(() => (d < 0 ? rej(new Error("read failed")) : res(values[p])), Math.abs(d));
  });
  const body = "const _NET_CONSENT_READ_MS = " + BUDGET + ";\nlet _netConsentGen = 0;\n"
    + extract(APP, "_netConsentConfig") + extract(APP, "ensureOnline") + "return ensureOnline;";
  const ensureOnline = new Function("api", "document", "window", "setTimeout", "_renderNetLanes",
    "_paintNetwork", "_postGoOnline", body)(
    api, document, {}, clock.setTimeout,
    (cfg, enabling) => { renders.push(Object.assign({ enabling }, cfg)); nodes["net-consent-lanes"].textContent = "rendered"; },
    () => {}, async () => true);
  return { clock, nodes, dlg, renders, ensureOnline };
}
const NET_VALUES = {
  "/api/system/network": { online: false },
  "/api/scheduler/config": { continuous: true },
  "/api/safety/settings": { dns_mode: "system" },
  "/api/custody/settings": { anchoring_mode: "local" },
  "/api/system/interfaces": { interfaces: [{ interface: "eth0", addresses: ["10.0.0.2"] }] },
};

async function m14() {
  await check("M-14 the real read budget is declared and bounded", () => {
    assert.ok(_budgetMatch, "no `const _NET_CONSENT_READ_MS = <ms>;` -- the lane reads are unbounded");
    assert.ok(BUDGET >= 500 && BUDGET <= 5000, "a read budget of " + BUDGET + " ms is not a pause an operator waits through");
  });

  await check("M-14 a slow lane read: consent waits for the disclosure, then the late answer replaces it", async () => {
    const H = consentHarness({ "/api/system/network": 0, "/api/scheduler/config": 5, "/api/safety/settings": 5,
      "/api/custody/settings": 5700, "/api/system/interfaces": 5 }, NET_VALUES);
    const done = H.ensureOnline("Collect now", { enabling: "collection" });
    await H.clock.advanceTo(1);
    assert.ok(H.dlg.open, "the consent popup did not open");
    assert.strictEqual(H.nodes["net-consent-ok"].disabled, true, "\"Go online\" is clickable before a single lane was read");
    await H.clock.advanceTo(100);
    assert.strictEqual(H.nodes["net-consent-lanes"].textContent, "…", "the lanes rendered before the budget with a read still out");
    assert.strictEqual(H.nodes["net-consent-ok"].disabled, true,
      "\"Go online\" is clickable while the lane list still reads \"…\" (the M-14 defect)");
    await H.clock.advanceTo(BUDGET + 1);
    assert.strictEqual(H.renders.length, 1, "the lanes were not rendered once the budget ran out");
    assert.strictEqual(H.renders[0].custody, null, "an unanswered read must render as unreadable (null), never as off");
    assert.ok(H.renders[0].scheduler && H.renders[0].safety, "answered reads were dropped from the first render");
    assert.strictEqual(H.renders[0].enabling, "collection", "the lane this action enables was not passed on");
    assert.strictEqual(H.nodes["net-consent-ok"].disabled, false, "\"Go online\" stayed disabled after the disclosure was complete");
    await H.clock.advanceTo(6000);
    assert.strictEqual(H.renders.length, 2, "the late custody answer did not re-render the open popup");
    assert.deepStrictEqual(H.renders[1].custody, NET_VALUES["/api/custody/settings"], "the re-render lost the late answer");
    assert.strictEqual(H.nodes["net-consent-ok"].disabled, false);
    H.nodes["net-consent-cancel"].onclick();
    assert.strictEqual(await done, false, "Stay offline must resolve false");
  });

  await check("M-14 fast reads: rendered once, consent enabled without waiting out the budget", async () => {
    const H = consentHarness({ "/api/system/network": 0, "/api/scheduler/config": 3, "/api/safety/settings": 4,
      "/api/custody/settings": 6, "/api/system/interfaces": 5 }, NET_VALUES);
    H.ensureOnline("Collect now", {});
    await H.clock.advanceTo(20);
    assert.strictEqual(H.renders.length, 1);
    assert.ok(H.renders[0].scheduler && H.renders[0].safety && H.renders[0].custody, "a fast read was rendered as unreadable");
    assert.strictEqual(H.nodes["net-consent-ok"].disabled, false, "consent waited out the budget with every read answered");
    assert.ok(/eth0: 10\.0\.0\.2/.test(H.nodes["net-consent-ifaces"].textContent), "the interfaces were not listed");
  });

  await check("M-14 interfaces that never answer are SAID to be unread, and consent is not held hostage", async () => {
    const H = consentHarness({ "/api/system/network": 0, "/api/scheduler/config": 3, "/api/safety/settings": 3,
      "/api/custody/settings": 3, "/api/system/interfaces": Infinity }, NET_VALUES);
    H.ensureOnline("Collect now", {});
    await H.clock.advanceTo(50);
    assert.strictEqual(H.nodes["net-consent-ok"].disabled, true, "consent enabled beside an interface list reading \"…\"");
    await H.clock.advanceTo(BUDGET + 1);
    assert.strictEqual(H.nodes["net-consent-ifaces"].textContent, "This machine's network interfaces could not be read just now.");
    assert.strictEqual(H.nodes["net-consent-ok"].disabled, false);
  });

  await check("M-14 a lane read that FAILS renders as unreadable at once, not after the budget", async () => {
    const H = consentHarness({ "/api/system/network": 0, "/api/scheduler/config": 3, "/api/safety/settings": -3,
      "/api/custody/settings": 3, "/api/system/interfaces": 3 }, NET_VALUES);
    H.ensureOnline("Collect now", {});
    await H.clock.advanceTo(20);
    assert.strictEqual(H.renders.length, 1);
    assert.strictEqual(H.renders[0].safety, null);
    assert.strictEqual(H.nodes["net-consent-ok"].disabled, false);
  });

  await check("M-14 a late answer after the popup closed does not repaint it", async () => {
    const H = consentHarness({ "/api/system/network": 0, "/api/scheduler/config": 3, "/api/safety/settings": 3,
      "/api/custody/settings": 5700, "/api/system/interfaces": 3 }, NET_VALUES);
    const done = H.ensureOnline("Collect now", {});
    await H.clock.advanceTo(BUDGET + 1);
    H.nodes["net-consent-cancel"].onclick();
    assert.strictEqual(await done, false);
    await H.clock.advanceTo(6000);
    assert.strictEqual(H.renders.length, 1, "a closed popup was repainted by a late read");
  });
}

// ----------------------------------------------------------------- T-2 --- //
async function t2() {
  await check("T-2 an attribute inside a data-i18n-dyn container is not cached or reverted", () => {
    const attrsDecl = (I18N.match(/const ATTRS = \[[^\]]*\];/) || ['const ATTRS = ["placeholder", "title", "aria-label"];'])[0];
    const body = "let map = {};\n" + attrsDecl + "\nconst origAttr = new WeakMap();\n"
      + extract(I18N, "tr") + extract(I18N, "doAttrs")
      + "return { doAttrs, setMap: (m) => { map = m; } };";
    const W = new Function(body)();
    const node = (attrs, dyn, parent) => {
      const a = new Map(Object.entries(attrs || {}));
      if (dyn) a.set("data-i18n-dyn", "");
      const el = { parent, hasAttribute: (k) => a.has(k), getAttribute: (k) => (a.has(k) ? a.get(k) : null),
        setAttribute: (k, v) => { a.set(k, String(v)); },
        closest(sel) {
          assert.strictEqual(sel, "[data-i18n-dyn]");
          for (let n = el; n; n = n.parent) if (n.hasAttribute("data-i18n-dyn")) return n;
          return null;
        } };
      return el;
    };
    const key = "Search";
    assert.ok(FR[key] && AR[key] && FR[key] !== AR[key], "fixture key missing from fr/ar");
    // Home's #home-tier: its renderer writes the hover through t(), inside .home-glance[data-i18n-dyn].
    const glance = node({}, true);
    const tier = node({ title: FR[key] }, false, glance);
    W.setMap(FR); W.doAttrs(tier);
    W.setMap(AR); tier.setAttribute("title", AR[key]); W.doAttrs(tier);   // oo:langchange repaint, then a walker pass
    assert.strictEqual(tier.getAttribute("title"), AR[key],
      "the walker put the FIRST language's hover back over the renderer's (" + tier.getAttribute("title") + ")");
    // The element's own marker still counts.
    const own = node({ title: FR[key] }, true);
    W.setMap(FR); W.doAttrs(own); W.setMap(AR); own.setAttribute("title", AR[key]); W.doAttrs(own);
    assert.strictEqual(own.getAttribute("title"), AR[key]);
    // And an ordinary element is still translated, and restored to English.
    const plain = node({ title: key }, false, node({}, false));
    W.setMap(FR); W.doAttrs(plain);
    assert.strictEqual(plain.getAttribute("title"), FR[key], "an ordinary title is no longer translated");
    W.setMap({}); W.doAttrs(plain);
    assert.strictEqual(plain.getAttribute("title"), key, "an ordinary title did not return to English");
  });
}

// ---------------------------------------------------------------- U-11 --- //
async function u11() {
  await check("U-11 theme chips: the tag verbatim, the count through fmtNum", async () => {
    const box = { innerHTML: "", querySelectorAll: () => [] };
    const cov = { tags: [{ tag: "technology", total: 4909 }, { tag: "economy", total: 12 }, { tag: "(untagged)", total: 3 }] };
    const api = async (p) => (p === "/api/scheduler/coverage" ? cov : p === "/api/scheduler/config" ? {} : {});
    const body = "const _gwSrc = { picked: null, emph: {} };\n" + extract(APP, "fmtNum")
      + extract(APP, "_gwRenderSources") + "return { run: _gwRenderSources, fmtNum };";
    const G = new Function("$", "api", "esc", "_gwT", "_gwUpdateThemeNote", "LANGS_12", body)(
      (id) => (id === "gw-themes" ? box : null), api, esc, (s) => s, () => {}, []);
    await G.run();
    const chips = [...box.innerHTML.matchAll(/<input type="checkbox" data-theme="([^"]*)"[^>]*> <span([^>]*)>([^<]*)<\/span> <span class="muted">([^<]*)<\/span>/g)];
    assert.strictEqual(chips.length, 2, "expected two theme chips, got " + chips.length);
    const byTag = { technology: 4909, economy: 12 };
    for (const [, tag, attrs, text, count] of chips) {
      assert.ok(/\bdata-i18n-dyn\b/.test(attrs), "the tag \"" + tag + "\" is open to the DOM walker, which translates it when it equals a chrome key");
      assert.strictEqual(text, tag, "the tag was not rendered verbatim");
      assert.strictEqual(count, G.fmtNum(byTag[tag], 0), "the count \"" + count + "\" bypasses fmtNum");
    }
    assert.notStrictEqual(G.fmtNum(4909, 0), "4909", "fixture: fmtNum should group thousands");
  });
}

// ----------------------------------------------------------------- T-7 --- //
async function t7() {
  const LEAD = "No AI backend is reachable right now — neither Ollama nor vLLM answers.";
  const TAIL = "AI is offline — click to start it, or open AI settings to install one";
  const paint = (h, map) => {
    const el = { style: {}, className: "", title: "", textContent: "" };
    const O = { t: (s) => (map[s] != null ? map[s] : s) };
    const f = new Function("$", "window", "OOI18N", "aiPillClick", "_aiStarting", "_aiHealth", "_aiBusy",
      "_aiBusyLabel", "_jobLabel", extract(APP, "_paintAiPill") + "return _paintAiPill;")(
      (id) => (id === "llm" ? el : null), { OOI18N: O }, O, () => {}, false, h, () => false, null, null);
    f();
    return el;
  };
  await check("T-7 the no-backend hover is keyed, whole, in the UI language", () => {
    assert.ok(FR[LEAD] && FR[TAIL], "the pill's sentences are not keys in fr.json");
    const el = paint({ available: false, no_backend: true, detail: "connection refused",
      backend_reason: "no GPU detected (or vLLM unavailable), and Ollama is NOT reachable either" }, FR);
    assert.strictEqual(el.title, FR[LEAD] + " — " + FR[TAIL],
      "the French hover is \"" + el.title + "\"");
    assert.ok(!/GPU|NOT reachable/.test(el.title), "the server's English reason leaked into the hover");
  });
  await check("T-7 a selected backend that is merely down keeps its detail", () => {
    const el = paint({ available: false, no_backend: false, detail: "connection refused" }, FR);
    assert.strictEqual(el.title, "connection refused — " + FR[TAIL]);
  });
}

// ----------------------------------------------------------------- H-3 --- //
async function h3() {
  await check("H-3 Find on this page highlights after the keystrokes, once, not inside each one", async () => {
    const clock = makeClock();
    const prose = { innerHTML: "" }, find = { value: "Where in the tree" };
    const calls = [];
    const body = "let _docRaw = \"# Security\\n\\n| a | b |\";\nlet _docFindTimer = null;\n"
      + extract(APP, "filterDoc") + (has(APP, "_filterDocNow") ? extract(APP, "_filterDocNow") : "")
      + "return filterDoc;";
    const filterDoc = new Function("$", "mdToHtml", "highlightProse", "setTimeout", "clearTimeout", body)(
      (id) => ({ "doc-prose": prose, "doc-find": find })[id] || null, (s) => "<p>" + s + "</p>",
      (q) => calls.push(q), clock.setTimeout, clock.clearTimeout);
    filterDoc(); filterDoc(); filterDoc();   // three keystrokes, each an input event
    assert.strictEqual(calls.length, 0,
      "the highlight (and its scroll to the first match) ran inside the input event " + calls.length + " time(s)");
    assert.strictEqual(clock.pending(), 1, "each keystroke left its own pending search");
    await clock.advanceTo(400);
    assert.deepStrictEqual(calls, ["Where in the tree"], "the search did not run once after the typing stopped");
    assert.strictEqual(prose.innerHTML, "<p># Security\n\n| a | b |</p>", "the document was not re-rendered before highlighting");
  });
}

// ------------------------------------------------------------ T-5 / T-6 / T-8 --- //
const ACT = { settings: { continuous: true, mode: "" }, progress: { total: 10, done: 3, current: "example.org", mode: "" },
  running: true, active: true, online: true, last_run: "2026-09-27T10:00:00Z" };
const rowLabels = (html) => [...html.matchAll(/<div class="vr"><span>([^<]*)<\/span>/g)].map((m) => m[1]);

async function t5() {
  await check("T-5 the app's Schedule subtab prints no Mode row", () => {
    const el = { innerHTML: "" };
    const f = new Function("$", "window", "_actData", "esc", "fmtLocal", "fmtRelative", "_concurrencyHtml",
      "_housekeepingHtml", extract(APP, "_renderSchedule") + "return _renderSchedule;")(
      (id) => (id === "sched-tm-body" ? el : null), {}, ACT, esc, (x) => x, (x) => x, () => "", () => "");
    f();
    const labels = rowLabels(el.innerHTML);
    assert.ok(labels.includes("Current pass") && labels.includes("Last run"), "fixture: the schedule did not render");
    assert.ok(!labels.includes("Mode"), "the retired Mode row is back: " + labels.join(" | "));
  });
  await check("T-5 /tasks prints no Mode row and no empty mode after the domain", () => {
    const el = { innerHTML: "" };
    const f = new Function("$", "esc", "t", "fmtNum", "fmtLocal", "fmtRel",
      extract(TM, "renderSchedule") + "return renderSchedule;")(
      (id) => (id === "sched-body" ? el : null), esc, (s) => s, (n) => String(n), (x) => x, (x) => x);
    f(ACT);
    const labels = rowLabels(el.innerHTML);
    assert.ok(labels.includes("Current pass"), "fixture: the schedule did not render");
    assert.ok(!labels.includes("Mode"), "the retired Mode row is back on /tasks: " + labels.join(" | "));
    const cur = el.innerHTML.match(/<span>Current pass<\/span><b>(.*?)<\/b>/);
    assert.ok(cur, "no Current pass row");
    assert.strictEqual(cur[1], "example.org", "the current pass carries a trailing mode fragment: " + cur[1]);
  });
}

async function t6() {
  await check("T-6 /tasks: the health dot carries the state's colour class", () => {
    for (const [state, cls] of [["healthy", "ok"], ["degraded", "warn"], ["offline", "err"]]) {
      const el = { innerHTML: "" };
      new Function("$", "t", "esc", "var _healthState = " + JSON.stringify(state) + ";\n"
        + extract(TM, "paintHealth") + "return paintHealth;")((id) => (id === "health" ? el : null), (s) => s, esc)();
      const m = el.innerHTML.match(/<span class="([^"]*)"><\/span>/);
      assert.ok(m, "no dot in " + el.innerHTML);
      assert.deepStrictEqual(m[1].trim().split(/\s+/).sort(), ["dot", cls].sort(),
        state + ": the dot is \"" + m[1] + "\" (a bare .dot is the muted grey)");
    }
  });
}

async function t8() {
  await check("T-8 /tasks follows the theme the app stores in oo.ui", () => {
    assert.ok(has(TM, "applyAppLook"), "taskmanager.html has no applyAppLook -- it still reads a key nothing writes");
    const run = (stored, prefersLight) => {
      const attrs = new Map(), props = new Map();
      const root = { setAttribute: (k, v) => attrs.set(k, v), removeAttribute: (k) => attrs.delete(k),
        style: { setProperty: (k, v) => props.set(k, v), removeProperty: (k) => props.delete(k) } };
      root.setAttribute("data-theme", "stale"); root.style.setProperty("--accent", "#000");
      const ls = { getItem: (k) => (k === "oo.ui" ? stored : null) };
      new Function("localStorage", "document", "_lightQuery",
        extract(TM, "applyAppLook") + "return applyAppLook;")(ls, { documentElement: root }, { matches: prefersLight })();
      return { theme: attrs.get("data-theme") || null, accent: props.get("--accent") || null };
    };
    assert.deepStrictEqual(run(JSON.stringify({ theme: "paper", accent: "#9a6a2f" }), false), { theme: "paper", accent: "#9a6a2f" });
    assert.deepStrictEqual(run(JSON.stringify({ theme: "ink" }), true), { theme: null, accent: null });
    assert.deepStrictEqual(run(JSON.stringify({ theme: "system" }), true), { theme: "light", accent: null });
    assert.deepStrictEqual(run(JSON.stringify({ theme: "system" }), false), { theme: null, accent: null });
    assert.deepStrictEqual(run(null, false), { theme: null, accent: null }, "nothing stored is the app's default, Ink");
    assert.deepStrictEqual(run("{not json", false), { theme: null, accent: null }, "an unreadable blob must fall back, not throw");
  });
  await check("T-8 /tasks re-applies the look when the app changes it", () => {
    assert.ok(!/localStorage\.getItem\("oo\.theme"\)/.test(TM), "taskmanager.html still reads the unwritten oo.theme key");
    assert.ok(/e\.key === "oo\.ui"\)\s*\{\s*applyAppLook\(\)/.test(TM), "the storage listener does not re-apply oo.ui");
  });
}

(async () => {
  await m14(); await t2(); await u11(); await t7(); await h3(); await t5(); await t6(); await t8();
  if (failures.length) {
    console.error("\nrewalk_b27_node_test: " + failures.length + " failure(s)\n - " + failures.join("\n - "));
    process.exit(1);
  }
  console.log("rewalk_b27_node_test: all checks ok");
})();
