// Settings -> AI and Custody: the setup card, the hero card, the model store, the uninstall box and the custody lines
// (row 367, app-ai-tools.js batch A), then the model catalogue, the backend panel with its Ollama buttons and the vLLM
// status and install boxes (batch B) follow a language switch, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Each of these used to be written once with t() output into an ordinary node, so it stayed in the language that was
// active when it was drawn. They now draw through ooLive/ooLiveHtml from what the panel already holds; where a click
// changes a button inside a held panel, the click's state is part of the panel's render. The panel functions AND the
// helpers are EXTRACTED from the shipped modules, and t()/tf() are the shipped engine over the shipped locales.

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
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const end = APP.indexOf(";\n", at);
  return APP.slice(at, end + 1);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));
const FR = locale("fr"), DE = locale("de"), JA = locale("ja");

class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
let REGISTRY = null;
class El {
  constructor(tag) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this.style = {}; this.value = ""; this.checked = false; this.disabled = false; this.dataset = {}; this._connected = true;
  }
  get isConnected() { return this._connected; }
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
  set innerHTML(v) {
    const html = String(v);
    this.replaceChildren(new Text(html)); this._html = html;
    for (const m of html.matchAll(/\bid="([^"]+)"/g)) REGISTRY.fresh(m[1]);
  }
  addEventListener() {}
}

const IDS = ["ai-setup-box", "ai-hero", "ai-store-box", "ai-uninstall-box", "custody-status", "cust-result", "cust-entries",
  "cust-gap-record", "cust-root", "cust-ots", "llm-catalog-box", "ai-backend-box", "ai-backend-select", "vllm-status-box",
  "vllm-install-box"];
// Batch B's module state, read from the shipped file so a rename fails here rather than drifting.
const STATE_B = ["let _mcRows = null, _mcStatus = null, _mcFollowing = 0;", "const _mcStarting = new Set();",
  'let _abRender = null, _abFresh = false, _ollBusy = "";', "let _vllmInstalling = false, _vllmProgress = null, _vllmInstallBtn = null;",
  "let _aiBackendPicks = 0;", "let _aiBackendSaving = 0;"];
for (const line of STATE_B) assert.ok(APP.includes(line), "the shipped file must declare: " + line);

function harness(answers, opts = {}) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  REGISTRY = { fresh(id) { if (nodes[id]) nodes[id]._connected = false; nodes[id] = new El("DIV"); } };
  for (const id of IDS) nodes[id] = new El("DIV");
  const calls = { api: [], toasts: [], refreshed: 0, timers: [] };
  const api = async (url, o) => {
    const key = ((o && o.method) || "GET") + " " + url;
    calls.api.push(key);
    let a = answers[key] !== undefined ? answers[key] : answers[url];
    if (typeof a === "function") a = a(o);
    a = await a;
    if (a instanceof Error) throw a;
    if (a === undefined) throw new Error("unexpected call " + key);
    return a;
  };
  const src = [
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    ...["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml", "ooLiveRepaint",
      "ooLabelHtml", "ooLabelText", "_sizeText", "_fmtBytes", "_tf", "_hwChips", "_failMsg"].map(extract),
    "let _aiSetupRunning = false, _aiSetupAction = null;",
    "let _aiHeroRender = null, _aiHeroStarting = false, _aiStartFailure = null;",
    "let _aiStoreRender = null, _aiStoreBusy = null;",
    "let _aiUninstallPlan = null, _aiUninstallBusy = \"\", _aiUninstallStatus = null;",
    "const _KEY_PROTECTION_TIPS = " + APP.slice(APP.indexOf("{", APP.indexOf("const _KEY_PROTECTION_TIPS")), APP.indexOf("\n    };", APP.indexOf("const _KEY_PROTECTION_TIPS")) + 6) + ";",
    extractConst("_CUSTODY_NO_KEY_TIP"), extractConst("_CUSTODY_KEY_LOST_TIP"),
    "const CUST_STORE_UNREADABLE = 'x', CUST_PQC_LIBRARY_MISSING = 'y', CUST_ACCEPTED_UNENDORSED = 'z';",
    ...["loadAiSetup", "_aiSetupRows", "_aiSetupActionHtml", "_aiSetupActionRedraw", "runAiSetup",
      "loadAiHero", "_aiHeroRedraw", "_aiHeroHtml", "aiStartNow",
      "loadAiStore", "_aiStoreRedraw", "_aiStoreHtml", "migrateOllamaStore",
      "_gbytes", "loadAiUninstall", "_aiUninstallRedraw", "_aiUninstallPlanHtml", "uninstallAi",
      "renderCustodyStatus", "_custodyStatusHtml", "verifyChain", "viewChain", "custodyAnchorResultHtml", "anchorRoot"].map(extract),
    ...STATE_B,
    ...["_mcRedraw", "_mcSay", "loadModelCatalog", "_modelCatalogRowsHtml", "installOneModel",
      "_abRedraw", "loadAiBackendPanel", "_aiBackendHtml", "launchOllama", "_ollamaAct", "releaseOllama",
      "_vllmInstallRedraw", "_vllmSay", "loadVllmStatusPanel", "_vllmInstallBtnHtml", "_vllmStatusHtml", "_vllmInstallCost",
      "vllmCostLine", "vllmLogNotes", "installVllm"].map(extract),
    "return { loadAiSetup, runAiSetup, loadAiHero, aiStartNow, loadAiStore, migrateOllamaStore, loadAiUninstall, uninstallAi," +
    " renderCustodyStatus, verifyChain, viewChain, anchorRoot, ooLiveRepaint," +
    " loadModelCatalog, installOneModel, loadAiBackendPanel, launchOllama, releaseOllama, loadVllmStatusPanel, installVllm };",
  ].join("\n");
  const fmtNum = (x) => String(x);
  const document = { createElement: (tag) => new El(tag.toUpperCase()), documentElement: { dir: "ltr" } };
  const window = { OOI18N };
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console,
    $: (id) => nodes[id] || null, api, esc, fmtNum,
    toast: (m, k) => calls.toasts.push([m, k || "ok"]),
    confirm: () => true,
    setTimeout: (fn, ms) => { calls.timers.push(ms); return 1; },
    ensureAiEgress: async () => true, ensureOnline: async () => true,
    _aiSetupPlan: async () => opts.plan,
    _vllmInstallStart: opts.vllmStart || (async () => true),
    _followJob: opts.follow || (async (url, onLine) => { for (const l of (opts.jobLines || [])) onLine(l); return opts.jobEnd || { state: "done" }; }),
    _llmPullStartPoll: () => {}, loadLlmModels: () => { calls.models = (calls.models || 0) + 1; },
    prepareOllamaInstall: async () => {}, _installDefaultModel: async () => {},
    aiPillStartOrInstall: async () => {}, refreshAiPanels: () => { calls.refreshed++; },
    loadLlmHealth: () => {},
    ooSaidHtml: (o, f) => esc(String(o[f] || "")),
    _apiErrorMessage: (e) => (e && e.message) || String(e),
    custItem: () => "item-1", custodyEntriesPaint: (host, entries) => { host._ooCustEntries = entries; },
    _custT: (s) => OOI18N.t(s),
  };
  const fns = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns, nodes, calls, $: (id) => nodes[id],
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      fns.ooLiveRepaint();
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));
const frame = (L, label, text) => L["{prefix}: {text}"].replace("{prefix}", label).replace("{text}", text);

(async () => {
  // 1. The setup card: the plan (its step labels translated now), the action and the run's status lines follow a
  //    switch; the button says "Working…" while a run is on, drawn by the action's render.
  {
    const plan = { target: "vllm", steps: [{ id: "install-vllm", label: "Install vLLM", size: "6 GB" },
      { id: "model", label: "Download the default model", artifact: "m:q4", size: "4 GB", note: "", caveats: [] }] };
    let finish;
    const h = harness({}, { plan, jobLines: ["pip 3/9"] });
    await h.fns.loadAiSetup();
    const planEl = h.$("ai-setup-plan"), action = h.$("ai-setup-action");
    assert.ok(planEl.innerHTML.includes("<li>Install vLLM <span class=\"muted\">(6 GB)</span></li>"), planEl.innerHTML);
    h.switchTo("fr");
    assert.ok(planEl.innerHTML.includes(`<li>${esc(FR["Install vLLM"])} `) && planEl.innerHTML.includes(`<li>${esc(FR["Download the default model"])} — <code>m:q4</code>`),
      "the step labels are translated: " + planEl.innerHTML);
    assert.ok(planEl.innerHTML.startsWith(`<strong>${esc(FR["Set up local AI"])}</strong>`), planEl.innerHTML);
    assert.ok(action.innerHTML.includes(">" + esc(FR["Set up local AI"]) + "</button>"), action.innerHTML);
    const run = h.fns.runAiSetup(null);
    await run;
    const status = h.$("ai-setup-status");
    assert.strictEqual(status.textContent, FR["Done."]);
    h.switchTo("de");
    assert.strictEqual(status.textContent, DE["Done."], "the run's last line follows a switch");
    assert.strictEqual(h.calls.refreshed, 1);
    assert.ok(action.innerHTML.includes(">" + esc(DE["Set up local AI"]) + "</button>") && !action.innerHTML.includes("disabled"), action.innerHTML);
    void finish;
  }
  {
    const plan = { target: "vllm", steps: [{ id: "install-vllm", label: "Install vLLM", size: "" }] };
    const h = harness({}, { plan, jobEnd: { state: "error", error: "pip <exit 1>" } });
    await h.fns.loadAiSetup();
    await h.fns.runAiSetup(null);
    const status = h.$("ai-setup-status");
    assert.strictEqual(status.textContent, "vLLM install failed: pip <exit 1>");
    h.switchTo("fr");
    assert.strictEqual(status.textContent, FR["vLLM install failed:"] + " pip <exit 1>");
  }

  // 2. The hero card: drawn from its reads; the Start button is drawn "Starting…" by the card's render while a start
  //    runs, and a switch in between keeps it so.
  {
    let release;
    const h = harness({
      "/api/llm/activation": { backend: "ollama", can_start: true },
      "/api/llm/backend": { gpu: { available: false }, hardware: { total_ram_gb: 16, cpu_cores: 8 } },
      "/api/llm/health": { available: false },
      "POST /api/llm/activation/start": () => new Promise((r) => { release = r; }),
    });
    await h.fns.loadAiHero();
    const hero = h.$("ai-hero");
    assert.ok(hero.innerHTML.includes(">Start the local AI</button>"), hero.innerHTML);
    h.switchTo("fr");
    assert.ok(hero.innerHTML.includes(esc(FR["Installed but not running — {backend}"].replace("{backend}", "Ollama"))), hero.innerHTML);
    const n = h.calls.api.length;
    const run = h.fns.aiStartNow(null);
    await tick();
    assert.ok(hero.innerHTML.includes(" disabled>" + esc(FR["Starting…"]) + "</button>"), hero.innerHTML);
    h.switchTo("de");
    assert.ok(hero.innerHTML.includes(" disabled>" + esc(DE["Starting…"]) + "</button>"), "the starting button follows a switch: " + hero.innerHTML);
    release({ started: true }); await run;
    assert.ok(hero.innerHTML.includes(">" + esc(DE["Start the local AI"]) + "</button>") && !hero.innerHTML.includes("disabled"), hero.innerHTML);
    assert.strictEqual(h.calls.api.length, n + 1, "a switch never re-reads the state");
  }

  // 3. The store: sizes through the one writer; the move buttons' busy labels are the store's render; the toast is a
  //    labelled count in the page's language.
  {
    let mig;
    const h = harness({
      "/api/llm/model-store": { root: "/d", ollama: { in_app_folder: true, configured: "/d/o", bytes: 5300000, note: "two stores" },
        huggingface: { configured: "/d/h", bytes: 0 } },
      "POST /api/llm/model-store/migrate?reclaim=true": () => new Promise((r) => { mig = r; }),
    });
    await h.fns.loadAiStore();
    const box = h.$("ai-store-box");
    h.switchTo("fr");
    assert.ok(box.innerHTML.includes(">" + esc(FR["Move them into the app folder"]) + "</button>"), box.innerHTML);
    const run = h.fns.migrateOllamaStore(null, true);
    await tick();
    assert.ok(box.innerHTML.includes(" disabled ") && box.innerHTML.includes(">" + esc(FR["Deleting…"]) + "</button>"), box.innerHTML);
    h.switchTo("de");
    assert.ok(box.innerHTML.includes(">" + esc(DE["Deleting…"]) + "</button>"), box.innerHTML);
    mig({ ok: true, copied: 3, removed: 2 }); await run;
    assert.deepStrictEqual(h.calls.toasts, [[DE["Done. Copied: {copied} · originals removed: {removed}."].replace("{copied}", "3").replace("{removed}", "2"), "ok"]]);
    assert.ok(!box.innerHTML.includes("disabled"), box.innerHTML);
  }

  // 4. Uninstall: the plan's buttons read "Uninstall {backend}" with the name untranslated, "Removing…" while one runs,
  //    and the answer survives the rebuild that follows it; sizes through the one writer, never a hand-written "GB".
  {
    let plan = { installed: ["ollama"], method: "m", backends: [{ backend: "ollama", installed: true, removable: true, bytes: 2147483648 }], stores: [] };
    let release;
    const h = harness({
      "/api/llm/uninstall/plan": () => plan,
      "POST /api/llm/uninstall": () => new Promise((r) => { release = r; }),
    });
    await h.fns.loadAiUninstall();
    const planEl = () => h.$("ai-uninstall-plan");
    const u1 = (L) => esc(L["Uninstall {backend}"]).replace("{backend}", '<span translate="no">Ollama</span>');
    assert.ok(planEl().innerHTML.includes(u1(locale("en"))), planEl().innerHTML);
    assert.ok(!planEl().innerHTML.includes(" GB)") || planEl().innerHTML.includes("(2"), planEl().innerHTML);
    h.switchTo("fr");
    assert.ok(planEl().innerHTML.includes(u1(FR)), planEl().innerHTML);
    assert.strictEqual(h.$("ai-uninstall-models-l").textContent, FR["also delete the downloaded models in this app's folder"]);
    const run = h.fns.uninstallAi(["ollama"], null);
    await tick(); await tick();
    assert.ok(planEl().innerHTML.includes(">" + esc(FR["Removing…"]) + "</button>"), planEl().innerHTML);
    plan = { installed: [], backends: [], stores: [] };
    release({ complete: true, freed_bytes: 0, kept: [{ what: "the program", reason: "system install" }] }); await run;
    assert.strictEqual(h.calls.refreshed, 1);
    await h.fns.loadAiUninstall();   // what refreshAiPanels does
    const box = h.$("ai-uninstall-box");
    assert.ok(box.innerHTML.includes(esc(FR["Uninstalled."] + "\n• the program: system install")), "the answer survived the rebuild: " + box.innerHTML);
    h.switchTo("de");
    assert.ok(box.innerHTML.includes(esc(DE["Uninstalled."])), box.innerHTML);
    // the answer belongs to the read that followed it: a later read (here a reinstall) no longer shows it
    plan = { installed: ["ollama"], method: "m", backends: [{ backend: "ollama", installed: true, removable: true, bytes: 1 }], stores: [] };
    await h.fns.loadAiUninstall();
    assert.ok(!box.innerHTML.includes(esc(DE["Uninstalled."])), "a stale answer outlived its read: " + box.innerHTML);
    assert.strictEqual(h.$("ai-uninstall-status").textContent, "", "the status line starts empty on a later read");
    plan = { installed: [], backends: [], stores: [] };
    await h.fns.loadAiUninstall();
    assert.ok(!box.innerHTML.includes(esc(DE["Uninstalled."])), "a stale answer outlived its read: " + box.innerHTML);
  }

  // 5. Custody: the status pills are translated by the render (inside a held node the walker no longer looks), the
  //    scheme id is data in translate="no", "unreadable" has its own sentence; "verified" carries the hover that says
  //    what it proves; a failure says FAILED in the page's language.
  {
    const h = harness({
      "/api/custody/item-1/verify": () => ({ verified: true, accepted_unendorsed: false, notes: [] }),
    });
    const st = { pqc_effective: false, pqc_enabled: false, ots_effective: false, anchoring_mode: "local", keys_created: true,
      key_protection: "plaintext-0600", signer: { ed25519_pub: "abcdef0123456789abcd" } };
    h.fns.renderCustodyStatus(st);
    const el = h.$("custody-status");
    h.switchTo("fr");
    assert.ok(el.innerHTML.startsWith(esc(frame(FR, FR["Signing"], "\u0001")).replace("\u0001", `<span class="pill">${esc(FR["Ed25519 only"])}</span>`)), el.innerHTML);
    assert.ok(el.innerHTML.includes(`<span class="pill">${esc(FR["local-only"])}</span>`), el.innerHTML);
    assert.ok(el.innerHTML.includes(esc(FR["keys: {protection}"]).replace("{protection}", '<code translate="no">plaintext-0600</code>')), el.innerHTML);
    assert.ok(el.innerHTML.includes(`title="${esc(FR[Object.keys(locale("en")).find((k) => k.startsWith("A signing key in use is stored unencrypted"))])}"`), "the hover is translated: " + el.innerHTML);
    h.fns.renderCustodyStatus(Object.assign({}, st, { key_protection: "unreadable" }));
    assert.ok(el.innerHTML.includes(">" + esc(FR["keys: unreadable"]) + "</span>"), el.innerHTML);
    await h.fns.verifyChain();
    const out = h.$("cust-result");
    const H1 = "Checked against the keys recorded in the log itself: this shows the log has not changed since it was signed, not who signed it.";
    h.switchTo("ja");
    assert.strictEqual(out.innerHTML, `<span class="pill ok" title="${esc(JA[H1])}">${esc(JA["verified"])}</span> ${esc(JA["chain intact, signatures valid."])}`);
    assert.strictEqual(JA["verified"], "検証済み", "the custody pill no longer reads 'date confirmed'");
  }
  {
    const h = harness({ "/api/custody/item-1/verify": { verified: false, issues: ["seq <gap> at 3"] }, "/api/custody/item-1": { entries: [], entry_count: 4 } });
    await h.fns.verifyChain();
    const out = h.$("cust-result");
    h.switchTo("de");
    assert.strictEqual(out.innerHTML, `<span class="pill err">${esc(DE["FAILED"])}</span> seq &lt;gap&gt; at 3`);
    await h.fns.viewChain();
    h.switchTo("fr");
    assert.strictEqual(out.textContent, FR["Custody entries: {n}"].replace("{n}", "4"));
  }

  // 6. The model catalogue (batch B): the head and the rows follow a switch; a click's "Starting…" is drawn by the rows'
  //    render and survives a refresh made while the download runs, as does the status line; the read that follows the
  //    end draws the last line once, and a later read no longer shows it.
  {
    const cat = { backend: "ollama", method: "m", models: [{ key: "k1", label: "Model One", available: true, installed: false,
      artifact: "a:1", size: "2 GB" }] };
    let follow = null, release;
    const h = harness({
      "/api/llm/models/catalog": () => cat,
      "POST /api/llm/models/install": () => ({ queued: ["a:1"], backend: "ollama" }),
    }, { follow: (url, onLine) => { follow = onLine; return new Promise((r) => { release = r; }); } });
    await h.fns.loadModelCatalog();
    const rows = () => h.$("mc-rows").innerHTML;
    assert.ok(rows().includes(">" + esc(locale("en")["Download"]) + "</button>"), rows());
    h.switchTo("fr");
    assert.ok(h.$("mc-head").innerHTML.includes(esc(FR["Available models"])), h.$("mc-head").innerHTML);
    assert.ok(rows().includes(">" + esc(FR["Download"]) + "</button>"), rows());
    const run = h.fns.installOneModel("k1", null);
    for (let i = 0; i < 4; i++) await tick();
    assert.ok(rows().includes(" disabled ") && rows().includes(">" + esc(FR["Starting…"]) + "</button>"), "busy: " + rows());
    follow("running");   // a bare job state is a key: translated
    assert.strictEqual(h.$("mc-status").textContent, FR["running"]);
    follow("pulling 40%");
    await h.fns.loadModelCatalog();   // a refresh while the download runs
    assert.ok(rows().includes(">" + esc(FR["Starting…"]) + "</button>"), "the refresh kept the busy button: " + rows());
    assert.strictEqual(h.$("mc-status").textContent, "pulling 40%", "the refresh kept the running status");
    await h.fns.loadModelCatalog();   // and a second one, before any new line
    assert.strictEqual(h.$("mc-status").textContent, "pulling 40%", "a running download's status is not consumed by a read");
    release({ state: "done", detail: "" }); await run;
    for (let i = 0; i < 4; i++) await tick();
    assert.strictEqual(h.$("mc-status").textContent, FR["Done."], "the read that follows the end draws the last line");
    assert.ok(rows().includes(">" + esc(FR["Download"]) + "</button>") && !rows().includes("disabled"), rows());
    h.switchTo("de");
    assert.strictEqual(h.$("mc-status").textContent, DE["Done."]);
    await h.fns.loadModelCatalog();
    assert.strictEqual(h.$("mc-status").textContent, "", "a later read no longer shows the old line");
  }
  {
    // a failure no read follows is drawn where it is, follows a switch, and is not kept for the next read
    const h = harness({
      "/api/llm/models/catalog": () => ({ backend: "ollama", models: [{ key: "k1", label: "M", available: true, installed: null, artifact: "a" }] }),
      "POST /api/llm/models/install": () => new Error("boom"),
    });
    await h.fns.loadModelCatalog();
    await h.fns.installOneModel("k1", null);
    h.switchTo("fr");
    assert.strictEqual(h.$("mc-status").textContent, FR["Download failed:"] + " boom");
    await h.fns.loadModelCatalog();
    assert.strictEqual(h.$("mc-status").textContent, "");
  }

  // 7. The backend panel (batch B): its words follow a switch; a repaint keeps the operator's live override tick and
  //    only a fresh read draws the server's value; "Launching…" is drawn by the render while Ollama starts.
  {
    let release;
    const b = { backend: "ollama", reason: "r", gpu: {}, vllm: {}, stored_override: "auto",
      ollama: { installed: true, running: false, can_launch: true },
      hardware: { practical: true, overridden: false, override_requested: false, reason: "ok", warnings: [] } };
    const h = harness({
      "/api/llm/backend": () => b,
      "POST /api/llm/ollama/start": () => new Promise((r) => { release = r; }),
    });
    await h.fns.loadAiBackendPanel();
    const box = h.$("ai-backend-box");
    h.switchTo("fr");
    assert.ok(box.innerHTML.includes(`<b>${esc(FR["Active backend:"])}</b>`), box.innerHTML);
    assert.ok(!box.innerHTML.includes('id="ai-hw-override" checked'), box.innerHTML);
    h.$("ai-hw-override").checked = true;   // the operator ticks; the save is still in flight
    h.switchTo("de");
    assert.ok(box.innerHTML.includes('id="ai-hw-override" checked'), "the repaint kept the live tick: " + box.innerHTML);
    await h.fns.loadAiBackendPanel();       // a fresh read: the server's value
    assert.ok(!box.innerHTML.includes('id="ai-hw-override" checked'), "a fresh read draws the server's value: " + box.innerHTML);
    const run = h.fns.launchOllama(null);
    await tick();
    assert.ok(box.innerHTML.includes(` disabled data-on-click="launchOllama(this)">${esc(DE["Launching…"])}</button>`), box.innerHTML);
    h.switchTo("fr");
    assert.ok(box.innerHTML.includes(`>${esc(FR["Launching…"])}</button>`), box.innerHTML);
    release({ started: true, ready: true }); await run;
    assert.ok(box.innerHTML.includes(`>${esc(FR["Launch Ollama"])}</button>`) && !box.innerHTML.includes(" disabled"), box.innerHTML);
  }

  // 8. vLLM (batch B): the install button follows a switch with its version as data; "Starting the install…" is drawn
  //    by its render; the progress line survives a refresh during the install, is drawn once by the read after it,
  //    and is gone from a later read; a status that could not be read says so in the page's language.
  {
    let follow = null, release;
    const s = { installed: false, gpu: { available: true }, verified_version: "0.11.0", base_url: "http://127.0.0.1:8000" };
    const h = harness({
      "/api/llm/vllm/status": () => s,
      "/api/llm/vllm/install/preflight": () => ({ disk: { measured: true, free_gb: 50, floor_gb: 20 }, ram: {}, blocking: [], warnings: [] }),
    }, { follow: (url, onLine) => { follow = onLine; return new Promise((r) => { release = r; }); } });
    await h.fns.loadVllmStatusPanel();
    await tick();
    const btn = () => h.$("vllm-install-btn").innerHTML;
    h.switchTo("fr");
    assert.strictEqual(btn(), `<button data-on-click="installVllm(this)">${esc(FR["Install vLLM"])} (<span translate="no">0.11.0</span>)</button>`);
    assert.strictEqual(h.$("vllm-install-cost").textContent, FR["{free} GB free, needs {floor} GB"].replace("{free}", "50").replace("{floor}", "20"));
    const run = h.fns.installVllm(null);
    for (let i = 0; i < 4; i++) await tick();
    assert.strictEqual(btn(), `<button disabled>${esc(FR["Starting the install…"])}</button>`);
    assert.strictEqual(h.$("vllm-install-progress").textContent, FR["Installing — this can take several minutes…"]);
    await h.fns.loadVllmStatusPanel();   // a refresh during the install
    assert.strictEqual(btn(), `<button disabled>${esc(FR["Starting the install…"])}</button>`, "the refresh kept the busy button");
    assert.strictEqual(h.$("vllm-install-progress").textContent, FR["Installing — this can take several minutes…"]);
    await h.fns.loadVllmStatusPanel();   // and a second one
    assert.strictEqual(h.$("vllm-install-progress").textContent, FR["Installing — this can take several minutes…"],
      "a running install's progress is not consumed by a read");
    h.switchTo("de");
    assert.strictEqual(h.$("vllm-install-progress").textContent, DE["Installing — this can take several minutes…"]);
    follow("running");
    assert.strictEqual(h.$("vllm-install-progress").textContent, DE["running"], "a bare job state follows the page's language");
    follow("pip: failed to build");
    release({ state: "error", detail: "pip: failed to build" }); await run;
    for (let i = 0; i < 4; i++) await tick();
    assert.strictEqual(h.$("vllm-install-progress").textContent, "pip: failed to build", "the read after the install draws its last line");
    assert.ok(btn().includes(`>${esc(DE["Install vLLM"])} (`), btn());
    await h.fns.loadVllmStatusPanel();
    assert.strictEqual(h.$("vllm-install-progress").textContent, "", "a later read no longer shows it");
  }
  {
    // the operator declines the resource warning: "Install cancelled." is drawn where it is, and no read keeps it
    const h = harness({ "/api/llm/vllm/status": () => ({ installed: false, gpu: { available: true }, verified_version: "1" }),
      "/api/llm/vllm/install/preflight": () => new Error("no") }, { vllmStart: async () => null });
    await h.fns.loadVllmStatusPanel();
    await h.fns.installVllm(null);
    h.switchTo("fr");
    assert.strictEqual(h.$("vllm-install-progress").textContent, FR["Install cancelled."]);
    assert.ok(h.$("vllm-install-btn").innerHTML.startsWith('<button data-on-click="installVllm(this)">'), "the button is back");
    await h.fns.loadVllmStatusPanel();
    assert.strictEqual(h.$("vllm-install-progress").textContent, "", "a later read does not bring the cancel back");
  }
  {
    const h = harness({ "/api/llm/vllm/status": () => new Error("down") });
    await h.fns.loadVllmStatusPanel();
    h.switchTo("ja");
    assert.ok(h.$("vllm-status-box").innerHTML.includes(esc(JA["Could not read vLLM status."])), h.$("vllm-status-box").innerHTML);
  }

  console.log("ai_tools_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
