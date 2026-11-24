// Settings -> Advanced: the compact, rebuild and update lines and the stoplist view follow a language switch, run as REAL
// code (row 367 batch 2).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Each of these lines used to be written once with t() output into an ordinary node, so it stayed in the language that
// was active when it was drawn. They are now drawn through ooLive/ooLiveHtml from what the panel already holds, and a
// switch redraws them with no request. The panel functions AND the helper are EXTRACTED from the shipped modules, and
// t()/tf() are the shipped engine over the shipped locales, so every translation checked here is the real one.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

function extract(name) {
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  const at = APP.slice(at0 - 6, at0) === "async " ? at0 - 6 : at0;
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
  return APP.slice(at, j);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));
const FR = locale("fr"), DE = locale("de");

// ---- a DOM just large enough for ooLive: text nodes, elements, attributes, connection ----
class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
class El {
  constructor(tag) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this.style = {}; this.value = ""; this.hidden = false; this.disabled = false; this.dataset = {};
  }
  get isConnected() { return true; }
  hasAttribute(a) { return Object.prototype.hasOwnProperty.call(this.attrs, a); }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  removeAttribute(a) { delete this.attrs[a]; }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = nodes; this._html = null;
    for (const c of nodes) c.parentNode = this;
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(...(v === "" ? [] : [new Text(String(v))])); }
  get innerHTML() { return this._html != null ? this._html : this.textContent; }
  set innerHTML(v) { this.replaceChildren(new Text(String(v))); this._html = String(v); }
  addEventListener() {}
}

const IDS = ["vacuum-btn", "vacuum-result", "rebuild-status", "rebuild-btn", "rebuild-stop-btn", "rebuild-result", "rebuild-kept",
  "rebuild-lanes", "upd-current", "upd-latest", "upd-check", "upd-apply", "upd-msg", "upd-manual", "upd-last",
  "kf-builtin-q", "kf-builtin-list", "kf-builtin-count"];

// answers: "METHOD url" or url -> a reply, an Error to throw, a Promise, or a function of the call returning either.
function harness(answers) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  for (const id of IDS) nodes[id] = new El("DIV");
  const calls = { api: [], toasts: [], confirms: [] };
  const api = async (url, opts) => {
    const key = ((opts && opts.method) || "GET") + " " + url;
    calls.api.push(key);
    let a = answers[key] !== undefined ? answers[key] : answers[url];
    if (typeof a === "function") a = a();
    a = await a;
    if (a instanceof Error) throw a;
    if (a === undefined) throw new Error("unexpected call " + key);
    return a;
  };
  const src = [
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    ...["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml", "ooLiveRepaint",
      "ooLabelHtml", "ooLabelText"].map(extract),
    "let _dbFileBytes = null, _dbReclaimBytes = 0; const VACUUM_GATE_BYTES = 500 * 1000 * 1000, VACUUM_LO_S_PER_GB = 10, VACUUM_HI_S_PER_GB = 17;",
    "const REBUILD_LO_S_PER_GB = 15, REBUILD_HI_S_PER_GB = 35;",
    // the wiring needs a page: it is not under test here
    "let _rebuildWired = true, _rebuildPoll = null, _rebuildSt = null, _rebuildNote = null; const _rbRemoving = new Set();",
    "let _updCheck = null;",
    ...["_confirmVacuum", "vacuumNow",
      "_rbT", "_rbTf", "_rbSettings", "_rbStatusText", "_rbResultText", "_rbRemoveDisabled", "_rbPaint", "_rbPaintLanes",
      "loadRebuild", "rebuildNow", "rebuildStoreNow", "rebuildRemoveKept",
      "_updT", "_updReason", "_updPaintInstall", "_updLastSay", "updLoadStatus", "updCheck", "updApply",
      "loadBuiltinStoplist"].map(extract),
    "return { vacuumNow, _rbPaint, loadRebuild, rebuildNow, rebuildStoreNow, rebuildRemoveKept, updLoadStatus, updCheck, updApply," +
    " loadBuiltinStoplist, ooLiveRepaint, setUpdCheck: (v) => { _updCheck = v; } };",
  ].join("\n");
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const fmtNum = (x, dp) => (dp ? Number(x).toFixed(dp) : String(Math.round(x))).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const pageButtons = [];   // what document.querySelectorAll("[data-rebuild-remove]") finds on the page now
  const document = { createElement: (tag) => new El(tag.toUpperCase()), documentElement: { dir: "ltr" },
    querySelectorAll: (sel) => (sel === "[data-rebuild-remove]" ? pageButtons.slice() : []), querySelector: () => null };
  const online = { answer: true };
  const confirmAnswers = [];
  const window = {
    OOI18N,
    confirm: (m) => { calls.confirms.push(m); return confirmAnswers.length ? confirmAnswers.shift() : true; },
  };
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console,
    $: (id) => nodes[id] || null, api, esc, fmtNum,
    toast: (m, k) => calls.toasts.push([m, k]),
    setInterval: () => 1, clearInterval: () => {},
    _fmtBytes: (b) => fmtNum(b) + " B", fmtDateTime: (s) => String(s), _paintReclaim: () => {},
    openUnifiedExport: () => { calls.api.push("EXPORT"); },
    ensureOnline: async () => online.answer,
  };
  const fns = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns, nodes, calls, confirmAnswers, OOI18N, pageButtons, online,
    // setLang() as shipped: swap the map, then the ONE oo:langchange listener's ooLiveRepaint (app-boot.js)
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      fns.ooLiveRepaint();
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));

(async () => {
  // 1. Compact: the progress line follows a switch WHILE it runs, the result (two lines) is drawn in the language of the
  //    moment and follows the next switch, and a failure carrying markup is shown as text, its label translated.
  {
    let finish;
    const h = harness({ "POST /api/database/vacuum": () => new Promise((r) => { finish = r; }) });
    const out = h.nodes["vacuum-result"];
    const run = h.fns.vacuumNow();
    assert.strictEqual(out.textContent, "Compacting… this can take a while on a large corpus.");
    h.switchTo("fr");
    assert.strictEqual(out.textContent, FR["Compacting… this can take a while on a large corpus."], "the progress line follows a switch");
    finish({ bytes_reclaimed: 1000, duration_ms: 1234, freed_not_yet_shrunk: { bytes: 2000 }, journal_mode: "wal" });
    await run;
    assert.ok(out.innerHTML.startsWith(FR["Compacted. Space returned to the disk: {freed} · {secs} s"].replace("{freed}", "1 000 B").replace("{secs}", "1.2")), out.innerHTML);
    assert.ok(out.innerHTML.includes('<div class="muted">2 000 B '), "the not-yet-shrunk line is part of the same drawing: " + out.innerHTML);
    const n = h.calls.api.length, fr = out.innerHTML;
    h.switchTo("de");
    const de = DE["Compacted. Space returned to the disk: {freed} · {secs} s"].replace("{freed}", "1 000 B").replace("{secs}", "1.2");
    assert.ok(out.innerHTML.startsWith(de) && out.innerHTML !== fr, out.innerHTML);
    const wal = "{pending} freed inside the database is not yet back on the disk: on this store's write-ahead log that space returns only when a later checkpoint completes, such as the one the app attempts when it closes; a read still in progress or an abrupt stop can delay it.";
    assert.ok(out.innerHTML.endsWith('<div class="muted">' + esc(DE[wal].replace("{pending}", "2 000 B")) + "</div>"), "the second line survives the switch: " + out.innerHTML);
    assert.strictEqual(h.calls.api.length, n, "a switch never compacts again");
  }
  {
    const h = harness({ "POST /api/database/vacuum": new Error("locked <b>by</b> a reader") });
    await h.fns.vacuumNow();
    const out = h.nodes["vacuum-result"];
    assert.strictEqual(out.textContent, "Compaction failed: locked <b>by</b> a reader");
    assert.strictEqual(out._html, null, "drawn as TEXT, so the server's markup is never parsed");
    h.switchTo("fr");
    assert.ok(out.textContent.startsWith(FR["Compaction failed"]) && out.textContent.endsWith("locked <b>by</b> a reader"), out.textContent);
    assert.deepStrictEqual(h.calls.api, ["POST /api/database/vacuum"]);
  }

  // 2. Rebuild: the status line, the job's progress, the kept files and the separate stores follow a switch; the newest
  //    poll's answer is the one redrawn; a kept file's name carrying markup is escaped.
  const lane = { store: "wikipedia", label: "Wikipedia", supported: true, current: { page_size: 4096, auto_vacuum: 0 },
    target: { page_size: 16384, auto_vacuum: 2 }, needed: true, preflight: { sufficient: true }, bytes_in_use: 2e9,
    kept_copies: [{ name: "wiki.<i>old</i>.db", bytes: 5, made_at: "M" }] };
  const base = () => ({ supported: true, current: { page_size: 4096, auto_vacuum: 0 }, target: { page_size: 16384, auto_vacuum: 2 },
    needed: true, preflight: { sufficient: true }, bytes_in_use: 1e9, job: {}, lanes: [lane],
    kept_copies: [{ name: "lib.<img src=x>.db", bytes: 7, made_at: "T" }] });
  {
    const st1 = Object.assign(base(), { job: { state: "running", detail_i18n: "Copying the {store} store into a new file at the current settings ({mb} MB in use)", detail_vars: { store: "Wikipedia", mb: 12 } } });
    const h = harness({});
    h.fns._rbPaint(st1);
    const res = h.nodes["rebuild-result"], kept = h.nodes["rebuild-kept"], lanes = h.nodes["rebuild-lanes"], box = h.nodes["rebuild-status"];
    assert.strictEqual(res.textContent, "Copying the Wikipedia store into a new file at the current settings (12 MB in use)");
    assert.ok(kept.innerHTML.includes("lib.&lt;img src=x&gt;.db") && !kept.innerHTML.includes("<img"), "a kept file's name is escaped: " + kept.innerHTML);
    assert.ok(lanes.innerHTML.includes("wiki.&lt;i&gt;old&lt;/i&gt;.db") && !lanes.innerHTML.includes("<i>old"), lanes.innerHTML);
    assert.ok(box.textContent.startsWith("Now: 4 KiB pages"), box.textContent);
    // a newer poll: not running, a different store state. The switch must redraw THIS one, never st1.
    const st2 = Object.assign(base(), { needed: false, lanes: [], kept_copies: [], last: { outcome: "rebuilt", store: "library", seconds: 3, kept_file: "k.db" } });
    h.fns._rbPaint(st2);
    h.switchTo("fr");
    assert.strictEqual(res.textContent, FR["Last rebuild finished in {secs} s. The old file was kept as {name}."].replace("{secs}", "3.0").replace("{name}", "k.db"));
    assert.ok(box.textContent.includes(FR["This library already has the current settings; nothing to rebuild."]), box.textContent);
    assert.strictEqual(kept.innerHTML, "", "the older poll's kept list never comes back");
    assert.strictEqual(lanes.innerHTML, "");
    assert.strictEqual(h.calls.api.length, 0, "a switch never polls");
    h.fns._rbPaint(st1);
    h.switchTo("de");
    assert.ok(kept.innerHTML.includes(">" + DE["Remove"] + "</button>") && kept.innerHTML.includes("lib.&lt;img"), kept.innerHTML);
    assert.ok(lanes.innerHTML.includes(esc(DE["Separate stores:"])) && lanes.innerHTML.includes(">" + esc(DE["Rebuild…"]) + "</button>"), lanes.innerHTML);
    assert.strictEqual(res.textContent, DE["Copying the {store} store into a new file at the current settings ({mb} MB in use)"]
      .replace("{store}", DE["Wikipedia"] || "Wikipedia").replace("{mb}", "12"));
    assert.strictEqual(h.calls.api.length, 0, "a switch never polls");
  }
  // 2b. A refused start (it was res.dataset.keep): the refusal stays over the last outcome through the poll AND through a
  //     switch, and a job seen running replaces it.
  {
    let status = Object.assign(base(), { last: { outcome: "stopped", store: "library" } });
    const h = harness({
      "GET /api/database/rebuild": () => status,
      "POST /api/database/rebuild": new Error("busy <b>now</b>"),
    });
    h.fns._rbPaint(status);
    const res = h.nodes["rebuild-result"];
    assert.strictEqual(res.textContent, "The last rebuild was stopped. The library is as it was.");
    await h.fns.rebuildNow();
    await tick();
    assert.ok(h.calls.api.includes("POST /api/database/rebuild") && h.calls.api.includes("GET /api/database/rebuild"), h.calls.api.join());
    assert.strictEqual(res.textContent, "The rebuild did not start: busy <b>now</b>", "the poll after the refusal keeps it");
    assert.strictEqual(res._html, null, "the server's words are TEXT, never parsed");
    const n = h.calls.api.length;
    h.switchTo("fr");
    assert.ok(res.textContent.startsWith(FR["The rebuild did not start"]) && res.textContent.endsWith("busy <b>now</b>"), res.textContent);
    assert.ok(!res.textContent.includes(FR["The last rebuild was stopped. The library is as it was."]), "the switch drew the older outcome back over the refusal");
    assert.strictEqual(h.calls.api.length, n, "a switch never polls");
    status = Object.assign(base(), { job: { state: "running" }, last: { outcome: "stopped", store: "library" } });
    await h.fns.loadRebuild();
    assert.strictEqual(res.textContent, FR["Rebuilding…"], "a start that did go ahead replaces the refusal");
    status = Object.assign(base(), { last: { outcome: "rebuilt", store: "library", seconds: 2, kept_file: "x.db" } });
    await h.fns.loadRebuild();
    assert.ok(res.textContent.startsWith(FR["Last rebuild finished in {secs} s. The old file was kept as {name}."].slice(0, 12)), res.textContent);
  }
  // 2c. A separate store's start that was taken, then a failed status read: both lines follow a switch.
  {
    let status = Object.assign(base(), { lanes: [lane] });
    const h = harness({ "GET /api/database/rebuild": () => status, "POST /api/database/rebuild": { started: true } });
    h.fns._rbPaint(status);
    status = new Error("gone");
    await h.fns.rebuildStoreNow("wikipedia");
    await tick();   // the status read it starts
    const res = h.nodes["rebuild-result"], box = h.nodes["rebuild-status"];
    assert.strictEqual(res.textContent, "Rebuilding…");
    assert.strictEqual(box.textContent, "Could not read the rebuild status: gone");
    h.switchTo("fr");
    assert.strictEqual(res.textContent, FR["Rebuilding…"]);
    assert.ok(box.textContent.startsWith(FR["Could not read the rebuild status"]), box.textContent);
  }
  // 2d. A Remove in flight stays disabled through a switch's redraw.
  {
    let finish;
    const status = base();
    const h = harness({ "POST /api/database/rebuild/remove-kept": () => new Promise((r) => { finish = r; }), "GET /api/database/rebuild": () => status });
    h.fns._rbPaint(status);
    const run = h.fns.rebuildRemoveKept({ dataset: { rebuildRemove: "lib.<img src=x>.db" }, disabled: false });
    h.switchTo("fr");
    assert.ok(/data-rebuild-remove="lib\.&lt;img src=x&gt;\.db" disabled>/.test(h.nodes["rebuild-kept"].innerHTML), h.nodes["rebuild-kept"].innerHTML);
    finish({ bytes: 7 }); await run;
    h.switchTo("de");
    assert.ok(!h.nodes["rebuild-kept"].innerHTML.includes(" disabled>"), h.nodes["rebuild-kept"].innerHTML);
  }
  // 2e. A FAILED Remove whose list a switch redrew mid-flight: the button now on the page is enabled again, not only the
  //     detached one the click came from (only that store's file of that name: a namesake in another store is left alone).
  {
    let fail;
    const status = base();
    const h = harness({ "POST /api/database/rebuild/remove-kept": () => new Promise((_, r) => { fail = r; }), "GET /api/database/rebuild": () => status });
    h.fns._rbPaint(status);
    const clicked = { dataset: { rebuildRemove: "lib.<img src=x>.db" }, disabled: false };
    const run = h.fns.rebuildRemoveKept(clicked);
    assert.strictEqual(clicked.disabled, true);
    h.switchTo("fr");   // the list is redrawn: the button on the page is a new one, drawn disabled
    const redrawn = { dataset: { rebuildRemove: "lib.<img src=x>.db" }, disabled: true };
    const otherStore = { dataset: { rebuildRemove: "lib.<img src=x>.db", rebuildStore: "wikipedia" }, disabled: true };
    h.pageButtons.push(redrawn, otherStore);
    fail(new Error("locked")); await run;
    assert.strictEqual(redrawn.disabled, false, "the live button stays disabled after a failed remove");
    assert.strictEqual(otherStore.disabled, true, "another store's file of the same name was touched");
    assert.ok(h.calls.toasts.some(([m, k]) => k === "err" && m.endsWith("locked")), JSON.stringify(h.calls.toasts));
  }
  // 2f. The Rebuild button: offered only for a supported, readable library that needs it and has room, and never while one runs.
  {
    const h = harness({});
    const btn = h.nodes["rebuild-btn"];
    h.fns._rbPaint(base());
    assert.strictEqual(btn.disabled, false, "a needed rebuild with room is offered");
    for (const [why, over] of [["unsupported", { supported: false }], ["unreadable", { current: null }], ["current", { needed: false }],
      ["no room", { preflight: { sufficient: false, needed_bytes: 9, free_bytes: 1 } }], ["running", { job: { state: "running" } }]]) {
      h.fns._rbPaint(Object.assign(base(), over));
      assert.strictEqual(btn.disabled, true, why + ": the Rebuild button is offered");
    }
  }

  // 3. Updates: the last outcome and the cannot-update sentence, the check's answer, and the apply's refusal.
  {
    const h = harness({
      "GET /api/system/update/status": { current: "v1.0", last_result: { status: "updated" },
        install: { can_apply: false, reason: "local_changes", manual_steps: ["git pull"] } },
    });
    await h.fns.updLoadStatus();
    const last = h.nodes["upd-last"], manual = h.nodes["upd-manual"];
    assert.strictEqual(last.textContent, "The last update was installed.");
    assert.strictEqual(manual.hidden, false);
    assert.strictEqual(manual.childNodes[0].textContent, "This install cannot be updated from here. This checkout has local changes. To update it yourself:");
    assert.strictEqual(manual.childNodes[1].textContent, "git pull");
    const n = h.calls.api.length;
    h.switchTo("fr");
    assert.strictEqual(last.textContent, FR["The last update was installed."]);
    assert.strictEqual(manual.childNodes[0].textContent, [FR["This install cannot be updated from here."], FR["This checkout has local changes."], FR["To update it yourself:"]].join(" "));
    assert.strictEqual(h.nodes["upd-current"].textContent, "v1.0");
    assert.strictEqual(h.calls.api.length, n, "a switch never re-reads the status");
  }
  {
    const h = harness({ "POST /api/system/update/check": { latest: "v2.0", update_available: true, install: { can_apply: true }, ref: "r", sha: "s" } });
    await h.fns.updCheck();
    const msg = h.nodes["upd-msg"];
    assert.strictEqual(msg.textContent, "A newer version is available.");
    assert.strictEqual(h.nodes["upd-latest"].textContent, "v2.0");
    assert.strictEqual(h.nodes["upd-apply"].hidden, false);
    h.switchTo("fr");
    assert.strictEqual(msg.textContent, FR["A newer version is available."]);
    assert.strictEqual(h.nodes["upd-latest"].textContent, "v2.0", "the version is never translated");
    assert.deepStrictEqual(h.calls.api, ["POST /api/system/update/check"], "a switch never checks again");
  }
  // A declined consent: the earlier answer is cleared first, and nothing is checked.
  {
    const h = harness({ "POST /api/system/update/check": { latest: "v2.0", update_available: true, install: { can_apply: true } } });
    await h.fns.updCheck();
    assert.strictEqual(h.nodes["upd-msg"].textContent, "A newer version is available.");
    h.online.answer = false;
    await h.fns.updCheck();
    assert.strictEqual(h.nodes["upd-msg"].textContent, "", "an older answer stayed beside a check that never ran");
    assert.strictEqual(h.nodes["upd-apply"].hidden, true, "the update stayed offered after a declined check");
    h.switchTo("fr");
    assert.strictEqual(h.nodes["upd-msg"].textContent, "", "a switch drew the older answer back");
    assert.deepStrictEqual(h.calls.api, ["POST /api/system/update/check"], "a declined check reached the network");
  }
  {
    const err = new Error("409"); err.detail = { code: "airplane" };
    const h = harness({ "POST /api/system/update/check": err });
    await h.fns.updCheck();
    h.switchTo("de");
    assert.strictEqual(h.nodes["upd-msg"].textContent, DE["Airplane mode is on: the update check did not run."]);
  }
  {
    const err = new Error("500"); err.detail = "git <b>refused</b>";
    const h = harness({ "GET /api/system/update/status": { blocked: null }, "POST /api/system/update/apply": err });
    h.fns.setUpdCheck({ update_available: true, ref: "r", sha: "s" });
    const msg = h.nodes["upd-msg"];
    // the check's line is held there first: the apply takes the same node, and a switch redraws the apply's line, never the check's
    h.fns.ooLiveRepaint();
    await h.fns.updApply();
    assert.strictEqual(msg.textContent, "The update could not start; nothing was changed. (git <b>refused</b>)");
    assert.strictEqual(msg._html, null, "the server's reason is TEXT");
    const n = h.calls.api.length;
    h.switchTo("fr");
    assert.strictEqual(msg.textContent, FR["The update could not start; nothing was changed."] + " (git <b>refused</b>)");
    assert.strictEqual(h.calls.api.length, n, "a switch never applies again");
    assert.strictEqual(h.nodes["upd-apply"].disabled, false);
  }
  {
    const h = harness({ "GET /api/system/update/status": { blocked: "protected" } });
    h.fns.setUpdCheck({ update_available: true });
    await h.fns.updApply();
    h.switchTo("de");
    assert.ok(h.nodes["upd-msg"].textContent === DE["Protected mode is on, so the update did not start: it would connect to GitHub directly, not through your proxy. Switch to standard mode to update, or update by hand through your proxy."]);
  }

  // 4. The built-in stoplist view: the cap note and the empty line follow a switch; the words are escaped.
  {
    let reply = { total: 2555, matched: 900, capped: true, terms: ["a&b", "<x>"] };
    const h = harness({ "/api/insights/filter/builtin?limit=500&q=": () => reply, "/api/insights/filter/builtin?limit=500&q=zz": () => reply });
    await h.fns.loadBuiltinStoplist();
    const list = h.nodes["kf-builtin-list"];
    assert.ok(list.innerHTML.startsWith('<div class="muted" style="width:100%">900 matches — showing the first 2. Refine your search.</div>'), list.innerHTML);
    assert.ok(list.innerHTML.includes(">a&amp;b</span>") && list.innerHTML.includes(">&lt;x&gt;</span>"), list.innerHTML);
    assert.strictEqual(h.nodes["kf-builtin-count"].textContent, "2 555");
    const n = h.calls.api.length;
    h.switchTo("fr");
    assert.ok(list.innerHTML.includes(esc(FR["{n} matches — showing the first {shown}."].replace("{n}", "900").replace("{shown}", "2")) + " " + esc(FR["Refine your search."])), list.innerHTML);
    assert.strictEqual(h.calls.api.length, n, "a switch never re-reads the stoplist");
    reply = { total: 2555, matched: 0, terms: [] };
    h.nodes["kf-builtin-q"].value = "zz";
    await h.fns.loadBuiltinStoplist();
    assert.strictEqual(list.innerHTML, `<span class="muted">${esc(FR["No built-in stopword matches that."])}</span>`);
    h.switchTo("de");
    assert.strictEqual(list.innerHTML, `<span class="muted">${esc(DE["No built-in stopword matches that."])}</span>`);
    reply = new Error("x");
    await h.fns.loadBuiltinStoplist();
    h.switchTo("fr");
    assert.strictEqual(list.innerHTML, `<span class="muted">${esc(FR["Could not load the stoplist."])}</span>`);
  }

  console.log("settings_safety_updates_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
