// Settings -> Models: the Ollama installer, the models box, the default-model block and the language-detection line
// follow a language switch, run as REAL code (row 367 batch 4).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Each of these used to be written once with t() output into an ordinary node, so it stayed in the language that was
// active when it was drawn. They are now drawn through ooLive/ooLiveHtml from what the panel already holds. Where a
// panel is repainted from inside (the installer's detail and log, the default-model block inside the models box), the
// parts are held one by one, because a hold on the whole is dropped by the first write inside it. The panel functions
// AND the helpers are EXTRACTED from the shipped modules, and t()/tf() are the shipped engine over the shipped
// locales, so every translation checked here is the real one.

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

// ---- a DOM just large enough for ooLive. An element written with innerHTML registers a FRESH node for every id the
//      HTML carries and disconnects the one that held that id before, so a held child of a redrawn panel is detached
//      exactly as on the page.
class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
let REGISTRY = null;
class El {
  constructor(tag) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this.style = {}; this.value = ""; this.hidden = false; this.disabled = false; this.dataset = {}; this._connected = true;
    this.scrollTop = 0; this.scrollHeight = 0;
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

function harness(answers, opts = {}) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  REGISTRY = { fresh(id) { if (nodes[id]) nodes[id]._connected = false; nodes[id] = new El("DIV"); } };
  for (const id of ["llm-install-box", "llm-models-box", "langdetect-status", "llm-default-model"]) nodes[id] = new El("DIV");
  const calls = { api: [], toasts: [], egress: [], rechecks: 0, timers: [] };
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
      "ooLabelHtml", "ooLabelText"].map(extract),
    "let _ollamaInstalling = false;",
    "let _dlModelPoll = null, _dmRender = null, _dmStarting = false;",
    "let _langDetectPolling = false; let _langDetectCount = null;",
    ...["loadOllamaInstall", "prepareOllamaInstall", "runOllamaInstall", "_miniBlockHtml", "_miniBlockHold", "_dmRedraw",
      "_paintDefaultModel", "_defaultModelHtml", "installDefaultModel", "_installDefaultModel", "loadLlmModels", "_llmModelsHtml",
      "_langDetectSay", "pollLangDetect", "loadLangDetectCount"].map(extract),
    "return { loadOllamaInstall, prepareOllamaInstall, runOllamaInstall, _paintDefaultModel, installDefaultModel, _installDefaultModel," +
    " loadLlmModels, pollLangDetect, loadLangDetectCount, ooLiveRepaint, starting: () => _dmStarting };",
  ].join("\n");
  const fmtNum = (x) => String(x);
  const document = { createElement: (tag) => new El(tag.toUpperCase()), documentElement: { dir: "ltr" } };
  const window = { OOI18N };
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console, TextDecoder,
    $: (id) => nodes[id] || null, api, esc, fmtNum,
    toast: (m, k) => calls.toasts.push([m, k || "ok"]),
    confirm: () => true,
    setTimeout: (fn, ms) => { calls.timers.push(ms); return ms === undefined ? 0 : (opts.runTimers ? setImmediate(fn) : 1); },
    clearTimeout: () => {},
    fetch: opts.fetch,
    ensureAiEgress: async (why) => { calls.egress.push(why); return opts.egress !== false; },
    recheckOllama: () => { calls.rechecks++; },
    ooSaidText: (o, f) => String(o[f] || ""), ooSaidHtml: (o, f) => esc(String(o[f] || "")),
    _sizeText: (b) => (b / 1073741824) + " GiB",
    _aiPillSettle: () => {}, _llmPullRefresh: () => {},
  };
  const fns = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns, nodes, calls, $: (id) => nodes[id],
    // setLang() as shipped: swap the map, then the ONE oo:langchange listener's ooLiveRepaint (app-boot.js)
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      fns.ooLiveRepaint();
    },
  };
}
const tick = () => new Promise((r) => setImmediate(r));
const stream = (lines) => {
  const enc = new TextEncoder(), parts = lines.map((o) => enc.encode(JSON.stringify(o) + "\n"));
  return async () => ({ body: { getReader: () => ({ read: async () => (parts.length ? { value: parts.shift(), done: false } : { done: true }) }) } });
};

(async () => {
  // 1. The installer panel: title, lead and action follow a switch, in both platform shapes; the server's own reason
  //    is shown as it came.
  {
    const h = harness({ "/api/llm/install/status": { ollama_present: false, platform: { scripted: true } } });
    await h.fns.loadOllamaInstall();
    assert.strictEqual(h.$("llm-install-title").textContent, "Install Ollama");
    assert.strictEqual(h.$("llm-install-prepare-btn").textContent, "Download & verify the official installer");
    h.switchTo("fr");
    assert.strictEqual(h.$("llm-install-title").textContent, FR["Install Ollama"]);
    assert.strictEqual(h.$("llm-install-lead").textContent, FR["Ollama is not installed yet. The app can download the official installer, verify its checksum against the publisher's attestation, and run it. Installing needs administrator rights and downloads over the clear internet (not this app's Tor proxy)."]);
    assert.strictEqual(h.$("llm-install-prepare-btn").textContent, FR["Download & verify the official installer"]);
    assert.strictEqual(h.calls.api.length, 1, "a switch never re-reads the status");
  }
  {
    const h = harness({ "/api/llm/install/status": { ollama_present: false, platform: { scripted: false, reason: "Use the .dmg <b>here</b>" } } });
    await h.fns.loadOllamaInstall();
    h.switchTo("de");
    assert.strictEqual(h.$("llm-install-title").textContent, DE["Install Ollama"]);
    assert.strictEqual(h.$("llm-install-lead").textContent, "Use the .dmg <b>here</b>", "the server's reason, as text");
    assert.strictEqual(h.$("llm-install-link").textContent, DE["Open ollama.com/download ↗"]);
    assert.ok(h.$("llm-install-box").innerHTML.includes('href="https://ollama.com/download"'));
  }

  // 2. Prepare: the progress line, a failure and the verified result follow a switch; the prepare result is drawn from
  //    what the step read, with no second download.
  {
    let prep = new Error("checksum <b>mismatch</b>");
    const h = harness({
      "/api/llm/install/status": () => ({ ollama_present: false, platform: { scripted: true }, can_run_unattended: true }),
      "POST /api/llm/install/prepare": () => prep,
    });
    await h.fns.loadOllamaInstall();
    await h.fns.prepareOllamaInstall();
    const detail = () => h.$("llm-install-detail");
    assert.strictEqual(detail().textContent, "Could not prepare the installer: checksum <b>mismatch</b>");
    assert.strictEqual(detail()._html, null, "a failure is TEXT");
    h.switchTo("fr");
    assert.strictEqual(detail().textContent, FR["{prefix}: {text}"].replace("{prefix}", FR["Could not prepare the installer"]).replace("{text}", "checksum <b>mismatch</b>"));
    prep = { path: "/tmp/i.sh", version: "0.9.1", sha256: "abcdef0123456789ff", manual_command: "sudo sh i.sh" };
    await h.fns.prepareOllamaInstall();
    assert.ok(detail().innerHTML.startsWith(`<div>${esc(FR["Verified Ollama"])} <code>0.9.1</code> · SHA-256 <code>abcdef0123456789…</code></div>`), detail().innerHTML);
    assert.ok(detail().innerHTML.includes(">" + esc(FR["Install now"]) + "</button>"), detail().innerHTML);
    const n = h.calls.api.length;
    h.switchTo("de");
    assert.ok(detail().innerHTML.startsWith(`<div>${esc(DE["Verified Ollama"])} `) && detail().innerHTML.includes(esc(DE["Or run it yourself in a terminal:"])), detail().innerHTML);
    assert.ok(detail().innerHTML.includes(">" + esc(DE["Recheck"]) + "</button>"), detail().innerHTML);
    assert.strictEqual(h.calls.api.length, n, "a switch never prepares again");
    assert.strictEqual(h.$("llm-install-title").textContent, DE["Install Ollama"], "the title outlived the writes into the detail beside it");
  }

  // 3. Run: the log is ONE list. The installer's own lines stay as they came; this app's error and end lines follow a
  //    switch, and a non-zero exit says so through the keyed frame (S1), never a welded number.
  {
    const h = harness({ "/api/llm/install/status": { ollama_present: false, platform: { scripted: true } } },
      { fetch: stream([{ event: "line", text: ">>> Installing <ollama>" }, { event: "error", error: "disk & cpu" }, { event: "done", exit_code: 3 }]) });
    await h.fns.loadOllamaInstall();
    await h.fns.runOllamaInstall("/tmp/i.sh");
    const log = h.$("llm-install-log");
    assert.strictEqual(log.style.display, "");
    assert.strictEqual(log.textContent, ">>> Installing <ollama>\n\nError: disk & cpu\n\nInstaller exited with code 3.\n");
    h.switchTo("fr");
    assert.strictEqual(log.textContent, ">>> Installing <ollama>\n\n" + FR["{prefix}: {text}"].replace("{prefix}", FR["Error"]).replace("{text}", "disk & cpu")
      + "\n\n" + FR["Installer exited with code {code}."].replace("{code}", "3") + "\n");
    assert.strictEqual(h.calls.rechecks, 1);
    assert.strictEqual(h.calls.egress.length, 1, "the run asks its own consent");
  }
  {
    const h = harness({ "/api/llm/install/status": { ollama_present: false, platform: { scripted: true } } },
      { fetch: stream([{ event: "line", text: "ok" }, { event: "done", exit_code: 0 }]) });
    await h.fns.loadOllamaInstall();
    await h.fns.runOllamaInstall("/tmp/i.sh");
    h.switchTo("de");
    assert.strictEqual(h.$("llm-install-log").textContent, "ok\n\n" + DE["Installation finished."] + "\n");
  }
  {
    const h = harness({ "/api/llm/install/status": { ollama_present: false, platform: { scripted: true } } }, { egress: false, fetch: () => { throw new Error("fetched"); } });
    await h.fns.loadOllamaInstall();
    await h.fns.runOllamaInstall("/tmp/i.sh");
    assert.strictEqual(h.$("llm-install-log").textContent, "", "a declined consent ran nothing");
    assert.strictEqual(h.$("llm-install-log").style.display, undefined, "a declined consent showed the log");
    assert.strictEqual(h.calls.rechecks, 0);
  }

  // 4. The models box: a failure and the installed list follow a switch; when Ollama is not answering, the sentence, the
  //    heading and the placeholder are held one by one, and the default-model block painted into it keeps them.
  {
    let models = new Error("refused <b>x</b>");
    const h = harness({ "/api/llm/models": () => models, "/api/llm/default-model": new Error("down") });
    await h.fns.loadLlmModels();
    const box = h.$("llm-models-box");
    assert.strictEqual(box.innerHTML, '<p class="muted">Model info unavailable: refused &lt;b&gt;x&lt;/b&gt;</p>');
    h.switchTo("fr");
    assert.strictEqual(box.innerHTML, `<p class="muted">${esc(FR["{prefix}: {text}"].replace("{prefix}", FR["Model info unavailable"])).replace("{text}", "refused &lt;b&gt;x&lt;/b&gt;")}</p>`);
    models = { available: true, total_ram_gb: 16, active: "m:1", installed: [{ tag: "m:1", size_gb: 2, modified: "2026-11-01T00" }, { tag: "m:2", size_gb: 1, modified: "" }] };
    await h.fns.loadLlmModels();
    assert.ok(box.innerHTML.startsWith(`<p class="muted">${esc(FR["{size} RAM detected"].replace("{size}", "16 GiB"))}.</p><table><tr><th>${esc(FR["Installed model"])}</th>`), box.innerHTML);
    const n = h.calls.api.length;
    h.switchTo("de");
    assert.ok(box.innerHTML.includes(`<span class="pill ok">${esc(DE["active"])}</span>`) && box.innerHTML.includes(">" + esc(DE["Set active"]) + "</button>"), box.innerHTML);
    assert.strictEqual(h.calls.api.length, n, "a switch never re-reads the models");
    // Ollama stops answering: the box is released and drawn in parts
    models = { available: false, ministral: { tag: "ministral:q4" } };
    await h.fns.loadLlmModels();
    await tick();
    assert.strictEqual(h.$("llm-models-note").textContent, DE["Ollama isn't running. Click the AI pill in the top bar to start it; your installed models appear here once it answers."]);
    assert.strictEqual(h.$("llm-default-model-h").textContent, DE["Default model"]);
    const host = h.$("llm-default-model");
    assert.strictEqual(host.innerHTML, `<p class="muted">${esc(DE["{prefix}: {text}"].replace("{prefix}", DE["Could not determine the default model"])).replace("{text}", "down")}</p>`,
      "the default-model block painted its read into the held placeholder");
    h.switchTo("fr");
    assert.strictEqual(h.$("llm-models-note").textContent, FR["Ollama isn't running. Click the AI pill in the top bar to start it; your installed models appear here once it answers."], "the sentence was dropped by the block painted beside it");
    assert.strictEqual(h.$("llm-default-model-h").textContent, FR["Default model"]);
    assert.ok(host.innerHTML.includes(esc(FR["Could not determine the default model"])), host.innerHTML);
  }

  // 5. The default-model block: the picker, the download line and the licence follow a switch with no request; a
  //    download started from its own button is drawn as "Starting…" by the same render, then given back.
  {
    let plan = { artifact: "ministral:q4", backend: "ollama", installed: false, size: "4 GB", license: "Apache-2.0", caveats: ["c1"], reason: "r" };
    let release;
    const h = harness({
      "/api/llm/default-model": () => plan,
      "/api/llm/models/catalog": { models: [] },
      "POST /api/llm/default-model/install": () => new Promise((r) => { release = r; }),
    });
    await h.fns._paintDefaultModel();
    const host = h.$("llm-default-model");
    assert.ok(host.innerHTML.includes(">Download the default model</button>") && host.innerHTML.includes(">Licence: Apache-2.0. c1</p>"), host.innerHTML);
    const n = h.calls.api.length;
    h.switchTo("fr");
    assert.ok(host.innerHTML.includes(">" + esc(FR["Download the default model"]) + "</button>"), host.innerHTML);
    assert.ok(host.innerHTML.includes(esc(FR["{prefix}: {text}"].replace("{prefix}", FR["Licence"])).replace("{text}", "Apache-2.0")), host.innerHTML);
    assert.strictEqual(h.calls.api.length, n, "a switch never re-reads the plan");
    const run = h.fns.installDefaultModel({ textContent: "x" });
    await tick(); await tick();
    assert.ok(host.innerHTML.includes(" disabled>" + esc(FR["Starting…"]) + "</button>"), "the button is redrawn as starting: " + host.innerHTML);
    h.switchTo("de");
    assert.ok(host.innerHTML.includes(" disabled>" + esc(DE["Starting…"]) + "</button>"), host.innerHTML);
    plan = Object.assign({}, plan, { installed: true });
    release({ action: "queued" }); await run; await tick(); await tick();
    assert.strictEqual(h.fns.starting(), false);
    assert.ok(host.innerHTML.includes(`<span class="pill ok">${esc(DE["Downloaded"])}</span>`), "the block re-read after the start: " + host.innerHTML);
    assert.ok(!host.innerHTML.includes("disabled"), host.innerHTML);
    assert.deepStrictEqual(h.calls.toasts, [[DE["Queued — it becomes the active model once downloaded."], "ok"]]);
  }
  {
    const h = harness({
      "/api/llm/default-model": { artifact: "a", backend: "vllm", installed: false, license: "L", reason: "why" },
      "/api/llm/models/catalog": { models: [{ artifact: "a", label: "A <x>", available: true, installed: true, is_default: true },
        { artifact: "b", label: "B", available: true, installed: true }], active: "a" },
      "/api/llm/default-model/status": { job: { running: true, progress: { detail: "3/5 shards" } } },
    });
    await h.fns._paintDefaultModel();
    const host = h.$("llm-default-model");
    assert.ok(host.innerHTML.includes(`<option value="a" selected>A &lt;x&gt; — default</option>`), host.innerHTML);
    assert.ok(host.innerHTML.includes(`<p class="hint">Downloading… 3/5 shards</p>`), host.innerHTML);
    assert.ok(h.calls.timers.includes(3000), "the vLLM job is followed");
    // the operator picks B; a switch before the re-read keeps B selected
    h.nodes["llm-model-pick"] = Object.assign(new El("SELECT"), { value: "b" });
    h.switchTo("fr");
    assert.ok(host.innerHTML.includes(`<option value="b" selected>B</option>`) && !host.innerHTML.includes(`value="a" selected`), host.innerHTML);
    assert.ok(host.innerHTML.includes(">" + esc(FR["Model in use"]) + "</label>") && host.innerHTML.includes(" — " + esc(FR["default"]) + "</option>"), host.innerHTML);
    assert.ok(host.innerHTML.includes(`<p class="hint">${esc(FR["Downloading…"])} 3/5 shards</p>`), host.innerHTML);
  }

  // 6. Language detection: the count's hover and each poll line follow a switch; the job's detail is escaped ONCE.
  {
    let status = { state: "running", progress: { done: 2, total: 9 }, detail: "AT&T <b>" };
    const h = harness({
      "/api/ai/detect-language/candidates": { candidates: 9 },
      "/api/ai/detect-language/status": () => status,
    }, { runTimers: true });
    const el = h.$("langdetect-status");
    const poll = h.fns.loadLangDetectCount();
    await tick();
    const tipEn = 'Articles still in an unknown language after the offline detector: 9.';
    for (let i = 0; i < 6 && !el.innerHTML.startsWith(`<span title="${tipEn}">2/9`); i++) await tick();
    assert.strictEqual(el.innerHTML, `<span title="${tipEn}">2/9 · AT&amp;T &lt;b&gt;</span>`,
      "an & reads as & (escaped once), and the count's hover stays under the poll line");
    h.switchTo("fr");
    assert.ok(el.innerHTML.startsWith(`<span title="${esc(FR["Articles still in an unknown language after the offline detector: {n}."].replace("{n}", "9"))}">2/9`), el.innerHTML);
    status = { state: "done", result: { stored: 3, none: 1, total: 4 } };
    await poll;
    const done = FR["Done. {stored} labelled · {none} unclear · {total} scanned"].replace("{stored}", "3").replace("{none}", "1").replace("{total}", "4");
    for (let i = 0; i < 10 && !el.innerHTML.endsWith(">" + esc(done) + "</span>"); i++) await tick();
    assert.ok(el.innerHTML.endsWith(">" + esc(done) + "</span>"), el.innerHTML);
    h.switchTo("de");
    const deDone = DE["Done. {stored} labelled · {none} unclear · {total} scanned"].replace("{stored}", "3").replace("{none}", "1").replace("{total}", "4");
    assert.ok(el.innerHTML.endsWith(">" + esc(deDone) + "</span>"), el.innerHTML);
    assert.ok(el.innerHTML.includes(`title="${esc(DE["Articles still in an unknown language after the offline detector: {n}."].replace("{n}", "9"))}"`), el.innerHTML);
  }
  {
    const h = harness({ "/api/ai/detect-language/candidates": { candidates: 0 }, "/api/ai/detect-language/status": { state: "idle" } });
    await h.fns.loadLangDetectCount();
    const el = h.$("langdetect-status");
    assert.strictEqual(el.innerHTML, `<span title="${esc("No articles are missing a language — nothing to detect.")}"></span>`);
    h.switchTo("fr");
    assert.strictEqual(el.innerHTML, `<span title="${esc(FR["No articles are missing a language — nothing to detect."])}"></span>`);
  }

  console.log("settings_ai_install_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });

function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
