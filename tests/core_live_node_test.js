// The app's chrome follows a language switch (row 367, app-core.js), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Eleven renderers in app-core.js wrote t() output into ordinary nodes, so their words stayed in the language that was
// active when they were drawn. Now the health pill (and its hover), the crash screen (its button keeps its listener),
// the airplane pop-up's OK, the network consent popup's lane list and interfaces line, the guided setup's interfaces
// line, the AI install question's default reason and the Coverage loading line are held; the task manager's Active,
// Queue, Schedule and Coverage panels are drawn again from what they last read (repaintTaskManager, from app-boot's one
// oo:langchange listener).
//
// The functions are EXTRACTED from the shipped app-core.js with the shipped ooLive family; t()/tf() are the shipped
// i18n engine over the shipped locales. Only the network and the DOM are stubs.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

const BOOT_JS = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-boot.js"), "utf-8");

function extract(name) {
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
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
// $(id) and querySelector(".cls"); those children leave the page when the markup is replaced.
class El {
  constructor(tag, cls) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this.style = {}; this._connected = true; this._kids = []; this.cls = cls || []; this.listeners = {};
    this.hidden = false; this.disabled = false; this.title = "";
    this.classList = { add() {}, remove() {}, toggle() {} };
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
      for (const at of m[2].matchAll(/([\w-]+)(?:="([^"]*)")?/g)) el.attrs[at[1]] = at[2] == null ? "" : at[2];
      this._kids.push(el);
      if (id) REGISTRY.fresh(id[1], el);
    }
  }
  _drop() { for (const k of this._kids) { k._connected = false; k._drop(); } this._kids = []; }
  _all() { return this._kids.flatMap((k) => [k, ...k._all()]); }
  querySelector(sel) {
    if (sel.startsWith("#")) return this._all().find((k) => k.isConnected && k.attrs.id === sel.split(" ")[0].slice(1)) || null;
    const c = sel.replace(/^\./, "");
    return this._all().find((k) => k.isConnected && k.cls.includes(c)) || null;
  }
  querySelectorAll(sel) { const c = sel.replace(/^\./, ""); return this._all().filter((k) => k.isConnected && k.cls.includes(c)); }
  addEventListener(ev, fn) { (this.listeners[ev] = this.listeners[ev] || []).push(fn); }
  appendChild(c) { return c; }
  remove() { this._connected = false; }
  showModal() { this.open = true; }
  close() { this.open = false; }
}
let REGISTRY = null;

const CORE = ["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml",
  "ooLiveRepaint"];
const FNS = ["_paintHealth", "_paintCrashScreen", "_airplanePopup", "_renderNetLanes", "_laneState", "_transportKind",
  "_storeUnreadable", "_transportHint", "_laneHostTitle", "_laneLine", "_gwT", "_gwRenderFinish", "ensureAiEgress",
  "repaintTaskManager", "_paintJobs", "_jobRow", "_renderSchedule", "_renderCoverage", "loadTagCoverage",
  "_renderEquilibrium", "_covBar", "_planNoteHtml", "_storagePausedText", "_resumeQueueLabel"];

function harness(answers) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  REGISTRY = { fresh(id, el) { if (nodes[id]) nodes[id]._connected = false; nodes[id] = el; } };
  for (const id of ["health", "net-consent-lanes", "gw-ifaces", "jobs-body", "queue-body", "sched-tm-body", "cov-tm-body"]) {
    nodes[id] = new El("DIV");
  }
  const egress = new El("DIALOG");
  egress.innerHTML = '<p id="ai-egress-reason"><b class="slot"></b></p><p id="ai-egress-offline"></p>';
  egress.querySelector = (sel) => (sel === "#ai-egress-reason b" ? egress._all().find((k) => k.cls.includes("slot")) : null);
  egress.querySelectorAll = () => [];
  nodes["ai-egress-consent"] = egress;
  nodes["ai-egress-ok"] = new El("BUTTON"); nodes["ai-egress-cancel"] = new El("BUTTON");
  const held = [];
  const api = (url, o) => {
    const key = ((o && o.method) || "GET") + " " + url;
    const a = answers[key];
    if (a === "hold") return new Promise((resolve, reject) => held.push({ resolve, reject }));
    if (a === undefined) return Promise.reject(new Error("unexpected call " + key));
    if (a instanceof Error) return Promise.reject(a);
    return Promise.resolve(a);
  };
  let created = null;
  const document = {
    getElementById: (id) => nodes[id] || null,
    createElement: (tag) => { created = new El(tag.toUpperCase()); return created; },
    body: { appendChild(el) { nodes[el.id] = el; } },
  };
  const window = { OOI18N, OO_NET_LANES: [] };
  const src = [
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    "let _serverDown = false, _lastReachableAt = Date.now();",
    "let _jobsData = null, _actData = null, _covData = null, _covLoading = false, _covEq = null;",
    extractConst("_CRASH_WHAT"), extractConst("_CRASH_UNKNOWN"), extractConst("_CRASH_CORPUS"),
    ...CORE.map(extract), ...FNS.map(extract),
    "return { fns: {" + FNS.join(",") + ", ooLiveRepaint}," +
    " set: (k, v) => { if (k === 'down') _serverDown = v; if (k === 'jobs') _jobsData = v; if (k === 'act') _actData = v; } };",
  ].join("\n");
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console, esc, $: (id) => nodes[id] || null, api,
    toast() {}, setTimeout: () => 1, clearTimeout() {}, fmtNum: (x) => String(x), fmtAgo: (x) => String(x),
    ooLtrIsolate: (s) => s, ooIsoDateTime: (s) => s, _paintNetwork() {}, _paintEgressWindow() {}, _openEgressWindow: async () => true,
    _isDownloadKind: () => false, _dlKey: (j) => j.id, _jobActions: () => "", _dlRateNote: () => "",
  };
  const out = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns: out.fns, set: out.set, nodes, held, $: (id) => nodes[id], created: () => created,
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      // app-boot's ONE oo:langchange listener: every held node, then the task manager
      out.fns.ooLiveRepaint();
      out.fns.repaintTaskManager();
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));
const has = (el, s) => el.innerHTML.includes(s) || el.textContent.includes(s);

(async () => {
  // 1. The health pill: its word and its hover.
  {
    const h = harness({});
    h.fns._paintHealth(true);
    assert.ok(has(h.$("health"), "healthy"));
    h.switchTo("fr");
    assert.ok(has(h.$("health"), esc(FR["healthy"])), "the pill's word follows a switch: " + h.$("health").innerHTML);
    assert.strictEqual(h.$("health").title, FR["Backend status"], "the hover the walker no longer reaches is written");
    h.fns._paintHealth(false);
    h.switchTo("de");
    assert.ok(has(h.$("health"), esc(DE["not responding"])));
  }

  // 2. The crash screen: its words follow a switch, and the button keeps its listener across it.
  {
    const h = harness({ "GET /api/health": new Error("down") });
    h.set("down", true);
    h.fns._paintCrashScreen();
    const o = h.$("oo-crash-screen");
    assert.ok(o.hasAttribute("data-i18n-dyn"), "the walker is kept off the words the screen holds");
    const btn = h.$("crash-retry");
    assert.strictEqual(h.$("crash-title").textContent, "The app stopped answering");
    assert.strictEqual(btn.textContent, "Check again");
    h.switchTo("fr");
    assert.strictEqual(h.$("crash-title").textContent, FR["The app stopped answering"]);
    assert.ok(h.$("crash-unknown").textContent.length > 20 && h.$("crash-unknown").textContent !== "What happened is not known from here: a stopped server, a crash and a sleeping machine look identical to this page. Nothing has been restarted for you.");
    assert.strictEqual(btn.textContent, FR["Check again"]);
    assert.strictEqual(h.$("crash-retry"), btn, "the button is not drawn again");
    for (const fn of btn.listeners.click) await fn();
    h.switchTo("de");
    assert.strictEqual(h.$("crash-since").textContent, DE["Still not answering."], "the retry's result follows a switch");
    assert.strictEqual(btn.textContent, DE["Check again"]);
    assert.ok(!btn.disabled);
    assert.ok(has(h.$("crash-journal"), esc(DE["The run journal cannot be downloaded while the server is not answering."])));
  }

  // 3. The airplane pop-up's OK.
  {
    const h = harness({});
    h.fns._airplanePopup("x");
    const ok = h.$("net-popup").querySelector(".net-popup-ok");
    assert.strictEqual(ok.textContent, "OK");
    h.switchTo("ar");
    assert.strictEqual(ok.textContent, locale("ar")["OK"], "the pop-up's OK follows a switch");
  }

  // 4. The consent popup's lane list, drawn from the settings it was given; and the guided setup's interfaces line.
  {
    const h = harness({ "GET /api/system/interfaces": new Error("x") });
    h.fns._renderNetLanes({}, null);
    assert.ok(has(h.$("net-consent-lanes"), "The host table could not be read."));
    h.switchTo("fr");
    assert.ok(has(h.$("net-consent-lanes"), esc(FR["The host table could not be read."])), h.$("net-consent-lanes").innerHTML);
    h.switchTo("en");
    await h.fns._gwRenderFinish();
    h.switchTo("de");
    assert.strictEqual(h.$("gw-ifaces").textContent, DE["This machine's network interfaces could not be read just now."]);
  }

  // 5. The AI install question's default reason.
  {
    const h = harness({ "GET /api/system/network": { online: false }, "GET /api/system/egress-window": { open: false } });
    h.fns.ensureAiEgress("");
    await tick(); await tick();
    const slot = h.$("ai-egress-consent").querySelector("#ai-egress-reason b");
    assert.strictEqual(slot.textContent, "Install the local AI");
    h.switchTo("fr");
    assert.strictEqual(slot.textContent, FR["Install the local AI"], "the default reason follows a switch");
  }

  // 6. The task manager: the lists and the schedule redraw from what they read; a panel never drawn is left alone;
  //    the Coverage loading line is held until the read lands.
  {
    const h = harness({ "GET /api/scheduler/coverage": "hold" });
    h.switchTo("fr");
    for (const id of ["jobs-body", "sched-tm-body", "cov-tm-body"]) assert.strictEqual(h.$(id).innerHTML, "", id + " never drawn");
    h.switchTo("en");
    h.set("jobs", { jobs: [] });
    h.fns._paintJobs();
    h.fns._renderSchedule();
    assert.ok(has(h.$("jobs-body"), esc("Active")));
    h.fns.loadTagCoverage(true);
    h.switchTo("de");
    assert.ok(has(h.$("jobs-body"), esc(DE["Active"])), "the Active list follows a switch");
    assert.ok(has(h.$("queue-body"), esc(DE["Queue"])), "the Queue list follows a switch");
    assert.ok(has(h.$("sched-tm-body"), esc(DE["No collection scheduled or running right now — when collection is on, the schedule appears here."])),
      "the Schedule follows a switch");
    assert.ok(has(h.$("cov-tm-body"), esc(DE["Loading coverage…"])), "the Coverage loading line follows a switch");
    h.held[0].reject(new Error("x"));
    await tick(); await tick();
    h.switchTo("fr");
    assert.ok(has(h.$("cov-tm-body"), esc(FR["Coverage is unavailable right now."])), "the Coverage result follows a switch");
  }

  // 7. The listener calls the task manager's repaint.
  {
    const at = BOOT_JS.indexOf('document.addEventListener("oo:langchange"');
    assert.ok(at !== -1);
    assert.strictEqual(BOOT_JS.split("repaintTaskManager()").length - 1, 1);
    assert.ok(BOOT_JS.indexOf("repaintTaskManager()") > at);
  }

  const own = (loc, name, keys) => keys.forEach((k) => assert.ok(loc[k] && loc[k] !== k, name + " has its own words for " + k));
  own(FR, "fr", ["healthy", "Backend status", "The app stopped answering", "Check again", "The host table could not be read.",
    "Install the local AI", "Coverage is unavailable right now."]);
  own(DE, "de", ["not responding", "Still not answering.", "Check again", "Active", "Queue", "Loading coverage…",
    "This machine's network interfaces could not be read just now.",
    "No collection scheduled or running right now — when collection is on, the schedule appears here."]);
  console.log("core_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
