// Settings -> Leads and Models: the Leads catalogue, the AI behaviour line, the Copy buttons, the custom-model box and
// the model downloads follow a language switch, run as REAL code (row 367 batch 3).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Each of these used to be written once with t() output into an ordinary node, so it stayed in the language that was
// active when it was drawn. They are now drawn through ooLive/ooLiveHtml from what the panel already holds, and a
// switch redraws them with no request. The Leads catalogue is a FORM: its redraw starts from the form as it stands, so
// what was ticked or typed and not saved yet, and which families were open, survive the switch. The panel functions
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
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = {");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const end = APP.indexOf("\n    };", at);
  return APP.slice(at, end + 7);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));
const FR = locale("fr"), DE = locale("de");
const unesc = (s) => String(s).replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&amp;/g, "&");

// ---- a DOM just large enough for ooLive: text nodes, elements, attributes, connection ----
class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
class El {
  constructor(tag) {
    this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null;
    this.style = {}; this.value = ""; this.hidden = false; this.disabled = false; this.dataset = {}; this.placeholder = "";
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
  set innerHTML(v) { this.replaceChildren(new Text(String(v))); this._html = String(v); this._parsed(String(v)); }
  _parsed() {}
  addEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
}
// #cards-host: the catalogue form, read back from the HTML it was given. The objects stand for the form controls, so
// a test can tick, type and open them the way an operator does: that changes no text, exactly like the real page.
class CardsHost extends El {
  _parsed(html) {
    const fams = [], boxes = [], rows = [], prods = [];
    for (const fh of html.split('<details class="card-fam"').slice(1)) {
      const m = /^ data-fam="([^"]*)"( open)?>/.exec(fh);
      const fam = { dataset: { fam: unesc(m[1]) }, open: !!m[2] };
      fams.push(fam);
      for (const ph of fh.split('<div class="card-prod"').slice(1)) {
        const prod = { dataset: { prod: unesc(/^ data-prod="([^"]*)"/.exec(ph)[1]) }, fine: null };
        prod.querySelector = (sel) => (sel === "details.card-finetune" ? prod.fine : null);
        prods.push(prod);
        const cb = /<input type="checkbox" class="card-on" value="([^"]*)" (checked)?/.exec(ph);
        const box = { value: unesc(cb[1]), checked: !!cb[2], closest: (sel) => (sel === ".card-fam" ? fam : null),
          focus: () => { this.focused = box; } };
        boxes.push(box);
        const ft = /<details class="card-finetune"( open)?>/.exec(ph);
        if (ft) prod.fine = { open: !!ft[1] };
        for (const rh of ph.split('<div class="card-tune"').slice(1)) {
          const r = /^ data-prod="([^"]*)" data-key="([^"]*)">[\s\S]*?<input [^>]*?value="([^"]*)"[\s\S]*?<button class="ghost tiny card-tune-reset" (disabled)?/.exec(rh);
          const input = { value: unesc(r[3]) };
          rows.push({ dataset: { prod: unesc(r[1]), key: unesc(r[2]) }, input, resetDisabled: !!r[4], querySelector: (sel) => (sel === "input" ? input : null) });
        }
      }
    }
    this.form = { fams, boxes, rows, prods };
  }
  querySelector(sel) { return sel === ".card-fam" ? (this.form && this.form.fams[0]) || null : null; }
  querySelectorAll(sel) {
    const f = this.form || { fams: [], boxes: [], rows: [], prods: [] };
    return { ".card-on": f.boxes, ".card-tune": f.rows, "details.card-fam": f.fams, ".card-prod": f.prods }[sel] || [];
  }
}

const IDS = ["cards-msg", "llm-behaviour-status", "custom-model-intro", "custom-model-label", "llm-pull-tag",
  "llm-pull-progress", "llm-downloads", "llm-keep-alive", "llm-prompt-summary"];

// answers: "METHOD url" or url -> a reply, an Error to throw, a Promise, or a function of the call returning either.
function harness(answers, opts = {}) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  for (const id of IDS) nodes[id] = new El("DIV");
  nodes["cards-host"] = new CardsHost("DIV");
  const calls = { api: [], toasts: [], egress: [], loads: [] };
  const timers = [];
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
      "ooLabelHtml", "ooLabelText", "ooLtrIsolate", "_failMsg"].map(extract),
    "let _cardCat = null, _cardFresh = false;",
    "let _llmPullPoll = null; let _llmPromptDefaults = {summary: \"\"};",
    extractConst("_CUSTOM_MODEL_HELP"),
    ...["loadCardCatalog", "_cardKey", "_cardFormState", "_cardVal", "_cardOn", "_cardTunableRow", "_cardFineTune",
      "renderCardCatalog", "_cardCatalogHtml", "cardSetEnabled", "saveCardSettings",
      "loadCustomModelBox", "_ooIsCloudModel", "pullModel", "_llmPullRefresh", "_llmPullHtml",
      "copyLlmPrompt", "saveLlmBehaviour"].map(extract),
    "return { loadCardCatalog, cardSetEnabled, saveCardSettings, renderCardCatalog, loadCustomModelBox, pullModel, _llmPullRefresh," +
    " copyLlmPrompt, saveLlmBehaviour, ooLiveRepaint, setPoll: (v) => { _llmPullPoll = v; }, poll: () => _llmPullPoll };",
  ].join("\n");
  const fmtNum = (x) => String(x);
  const document = { createElement: (tag) => new El(tag.toUpperCase()), documentElement: { dir: "ltr" },
    querySelectorAll: (sel) => (sel === "#cards-host .card-on" ? nodes["cards-host"].querySelectorAll(".card-on")
      : sel === "#cards-host .card-tune" ? nodes["cards-host"].querySelectorAll(".card-tune") : []) };
  const window = { OOI18N };
  const env = {
    window, OOI18N, document, MutationObserver: undefined, console,
    $: (id) => nodes[id] || null, api, esc, fmtNum,
    toast: (m, k) => calls.toasts.push([m, k]),
    setInterval: () => 7, clearInterval: () => {},
    setTimeout: (fn) => { timers.push(fn); return timers.length; },
    navigator: { clipboard: { writeText: () => Promise.resolve() } },
    uiDepth: () => opts.depth || "standard",
    ooSaidHtml: (n, f) => esc(String(n[f])),
    ensureAiEgress: async (why) => { calls.egress.push(why); return opts.egress !== false; },
    _followJob: async (url, onDetail) => { for (const m of (opts.jobLines || [])) onDetail(m); return { state: "done" }; },
    _llmPullStartPoll: () => { calls.loads.push("poll"); },
    loadLlmModels: () => { calls.loads.push("models"); },
    loadLlmPrompts: () => { calls.loads.push("prompts"); },
  };
  const fns = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns, nodes, calls, timers, OOI18N, form: () => nodes["cards-host"].form,
    // setLang() as shipped: swap the map, then the ONE oo:langchange listener's ooLiveRepaint (app-boot.js)
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      fns.ooLiveRepaint();
    },
  };
}

const catalogue = () => ({ families: [
  { family: "news", label: "Rising now", producers: [
    { name: "spike", label: "Spike", description: "d1", enabled: true,
      tunables: [{ key: "min_n", label: "Minimum", kind: "int", value: 5, default: 5, lo: 2, hi: 50, unit: "", impact: "i" }] },
    { name: "quiet", label: "Quiet", description: "d2", enabled: true, tunables: [] }] },
  { family: "law", label: "Law", producers: [{ name: "lawp", label: "Law P", description: "d3", enabled: false, tunables: [] }] },
] });

(async () => {
  // 1. The Leads catalogue: the counter, the labels and the fine-tune fold follow a switch, and the form keeps what the
  //    operator ticked, typed and opened and has not saved; only a fresh read draws the stored values.
  {
    let cat = catalogue();
    const h = harness({ "GET /api/settings/cards": () => cat });
    await h.fns.loadCardCatalog();
    const host = h.nodes["cards-host"];
    assert.ok(host.innerHTML.includes("— 2/2 on</span>") && host.innerHTML.includes("— 0/1 on</span>"), host.innerHTML);
    assert.ok(host.innerHTML.includes(">safe range ") && host.innerHTML.includes(">Save Lead settings</button>"), host.innerHTML);
    assert.strictEqual(h.form().prods[0].fine.open, false, "at Standard an unchanged fine-tune is folded");
    // the operator: opens the first family and the Spike fold, types 9, unticks Quiet
    const f = h.form();
    f.fams[0].open = true; f.prods[0].fine.open = true; f.rows[0].input.value = "9";
    const quiet = f.boxes.find((b) => b.value === "quiet");
    quiet.checked = false;
    h.fns.cardSetEnabled(quiet);
    assert.ok(host.innerHTML.includes("— 1/2 on</span>"), "the counter follows the click: " + host.innerHTML);
    assert.strictEqual(host.focused && host.focused.value, "quiet", "the focus goes back to the box that was clicked");
    assert.strictEqual(h.form().rows[0].input.value, "9", "a click redraw kept the typed value");
    const n = h.calls.api.length;
    h.switchTo("fr");
    const g = h.form();
    assert.ok(host.innerHTML.includes("— 1/2 " + esc(FR["on"]) + "</span>"), host.innerHTML);
    // a family name is a server label the locales carry; the held render translates it (the page walker skips it)
    assert.ok(FR["Rising now"] && host.innerHTML.includes('<span class="card-fam-t">' + esc(FR["Rising now"]) + "</span>"), host.innerHTML);
    assert.ok(host.innerHTML.includes(">" + esc(FR["safe range"]) + " ") && host.innerHTML.includes(">" + esc(FR["Save Lead settings"]) + "</button>"), host.innerHTML);
    assert.ok(host.innerHTML.includes(esc(FR["Fine-tune ({n})"].replace("{n}", "1"))), host.innerHTML);
    assert.ok(host.innerHTML.includes(esc(FR["{n} changed"].replace("{n}", "1"))), "the typed value counts as changed: " + host.innerHTML);
    assert.strictEqual(g.rows[0].input.value, "9", "the switch lost the typed value");
    assert.strictEqual(g.rows[0].resetDisabled, false, "Reset is offered for the typed value");
    assert.strictEqual(g.boxes.find((b) => b.value === "quiet").checked, false, "the switch ticked the box again");
    assert.strictEqual(g.fams[0].open, true, "the switch closed the family that was open");
    assert.strictEqual(g.fams[1].open, false);
    assert.strictEqual(g.prods[0].fine.open, true, "the switch folded the fine-tune that was open");
    assert.strictEqual(h.calls.api.length, n, "a switch never re-reads the catalogue");
    // a fresh read (after a save) draws what is stored; the family stays open
    cat = catalogue(); cat.families[0].producers[0].tunables[0].value = 7;
    await h.fns.loadCardCatalog();
    assert.strictEqual(h.form().rows[0].input.value, "7", "a fresh read shows the stored value, not the older typed one");
    assert.strictEqual(h.form().boxes.find((b) => b.value === "quiet").checked, true, "a fresh read shows the stored state");
    assert.strictEqual(h.form().fams[0].open, true, "a fresh read closed the family the operator had open");
    assert.ok(host.innerHTML.includes("— 2/2 " + esc(FR["on"])), host.innerHTML);
    h.switchTo("de");
    assert.ok(host.innerHTML.includes("— 2/2 " + esc(DE["on"])), host.innerHTML);
    assert.strictEqual(h.form().rows[0].input.value, "7");
  }
  {
    const h = harness({ "GET /api/settings/cards": new Error("down") });
    await h.fns.loadCardCatalog();
    const host = h.nodes["cards-host"];
    assert.strictEqual(host.innerHTML, '<div class="muted">Could not load the Leads catalogue.</div>');
    h.switchTo("fr");
    assert.strictEqual(host.innerHTML, `<div class="muted">${esc(FR["Could not load the Leads catalogue."])}</div>`);
  }
  // 1b. Saving: the saved line, the clamp notes and a failure follow a switch; the server's words stay escaped.
  {
    let reply = { clamped: [{ producer: "spike", key: "min_n", given: 1, used: 2, reason: "below <b>floor</b>" }] };
    const h = harness({ "GET /api/settings/cards": catalogue, "PUT /api/settings": () => reply });
    await h.fns.loadCardCatalog();
    await h.fns.saveCardSettings();
    const msg = h.nodes["cards-msg"];
    assert.ok(msg.innerHTML.startsWith('<span class="note warn">Some values were adjusted to stay in their safe range:</span>'), msg.innerHTML);
    assert.ok(msg.innerHTML.includes("below &lt;b&gt;floor&lt;/b&gt;"), msg.innerHTML);
    h.switchTo("fr");
    assert.ok(msg.innerHTML.startsWith(`<span class="note warn">${esc(FR["Some values were adjusted to stay in their safe range:"])}</span>`), msg.innerHTML);
    reply = {};
    await h.fns.saveCardSettings();
    assert.strictEqual(msg.innerHTML, `<span class="note ok">${esc(FR["Lead settings saved."])}</span>`);
    h.switchTo("de");
    assert.strictEqual(msg.innerHTML, `<span class="note ok">${esc(DE["Lead settings saved."])}</span>`);
    reply = new Error("disk <i>full</i>");
    await h.fns.saveCardSettings();
    assert.strictEqual(msg.innerHTML, `<span class="note err">${esc(DE["Save failed: {error}"].replace("{error}", "disk <i>full</i>"))}</span>`);
    h.switchTo("fr");
    assert.strictEqual(msg.innerHTML, `<span class="note err">${esc(FR["Save failed: {error}"].replace("{error}", "disk <i>full</i>"))}</span>`);
  }

  // 2. AI behaviour: the saved line follows a switch; a failure is the server's words, escaped.
  {
    let reply = { ok: true };
    const h = harness({ "PUT /api/settings": () => reply });
    h.nodes["llm-keep-alive"].value = "10m";
    await h.fns.saveLlmBehaviour(null);
    const st = h.nodes["llm-behaviour-status"];
    assert.strictEqual(st.textContent, "Saved.");
    h.switchTo("fr");
    assert.strictEqual(st.textContent, FR["Saved."]);
    reply = new Error("bad <b>value</b>");
    await h.fns.saveLlmBehaviour(null);
    assert.strictEqual(st.innerHTML, '<span class="note err">bad &lt;b&gt;value&lt;/b&gt;</span>');
    h.switchTo("de");
    assert.strictEqual(st.innerHTML, '<span class="note err">bad &lt;b&gt;value&lt;/b&gt;</span>', "the error line was replaced by an older Saved.");
  }

  // 3. Copy: "Copied" follows a switch, the button's own label comes back after the pause, and a second click never
  //    makes "Copied" the label.
  {
    const h = harness({});
    h.nodes["llm-prompt-summary"].value = "prompt";
    const btn = new El("BUTTON");
    const own = new Text("Copy");
    btn.replaceChildren(own);
    h.fns.copyLlmPrompt("summary", btn);
    await tick();
    assert.strictEqual(btn.textContent, "Copied");
    h.switchTo("fr");
    assert.strictEqual(btn.textContent, FR["Copied"]);
    h.fns.copyLlmPrompt("summary", btn);   // a second click inside the pause
    await tick();
    assert.strictEqual(h.timers.length, 2);
    h.timers[0]();
    assert.strictEqual(btn.textContent, FR["Copied"], "the first click's timer cut the second click's pause short");
    h.timers[1]();
    assert.strictEqual(btn.childNodes.length, 1);
    assert.strictEqual(btn.childNodes[0], own, "the button's own label node is put back (the page walker translates it)");
  }

  // 4. The custom-model box: the intro and the label follow a switch for the backend this read found; the example is
  //    the server's identifier and is never translated; no backend is its own sentence.
  {
    const h = harness({ "/api/llm/default-model": { backend: "ollama", artifact: "ministral:q4" } });
    await h.fns.loadCustomModelBox();
    const intro = h.nodes["custom-model-intro"], label = h.nodes["custom-model-label"];
    assert.strictEqual(label.textContent, "Ollama model tag");
    assert.ok(intro.innerHTML.startsWith("Your backend is Ollama, so it downloads images from the Ollama library. Browse them at <a href=\"https://ollama.com/library\""), intro.innerHTML);
    assert.strictEqual(h.nodes["llm-pull-tag"].placeholder, "ministral:q4");
    h.switchTo("fr");
    assert.strictEqual(label.textContent, FR["Ollama model tag"]);
    assert.ok(intro.innerHTML.startsWith(esc(FR["Your backend is Ollama, so it downloads images from the Ollama library. Browse them at"]) + " <a"), intro.innerHTML);
    assert.ok(intro.innerHTML.endsWith(esc(FR["Copy the tag exactly as the model page shows it, including the part after the colon — that part is the quantisation, and leaving it off gets you whichever build the library currently points at."])), intro.innerHTML);
    assert.strictEqual(h.calls.api.length, 1, "a switch never re-reads the backend");
  }
  {
    const h = harness({ "/api/llm/default-model": new Error("down") });
    await h.fns.loadCustomModelBox();
    h.switchTo("de");
    assert.strictEqual(h.nodes["custom-model-label"].textContent, DE["Model name"]);
    assert.strictEqual(h.nodes["custom-model-intro"].textContent, DE["Set up the local AI first — until a backend is chosen, there is no telling which kind of model name to ask you for."]);
  }

  // 5. Pulling a model: each line follows a switch; the job's own progress words are shown as they came.
  {
    const h = harness({});
    const prog = h.nodes["llm-pull-progress"];
    await h.fns.pullModel("gpt-oss:20b-cloud");
    const cloud = "That model runs on Ollama's cloud, not on this computer, so it is refused: the text you give it would leave the machine. Choose a local model.";
    assert.strictEqual(prog.textContent, cloud);
    assert.deepStrictEqual(h.calls.egress, [], "a cloud model is refused before the consent popup");
    h.switchTo("fr");
    assert.strictEqual(prog.textContent, FR[cloud]);
  }
  {
    let reply = { refused: [{ reason: "refused" }, {}] };
    const h = harness({ "POST /api/llm/models/pull-custom": () => reply }, { jobLines: ["fetching 2/5 <shards>"] });
    const prog = h.nodes["llm-pull-progress"];
    await h.fns.pullModel("owner/name");
    assert.strictEqual(prog.textContent, "refused refused");
    h.switchTo("fr");
    assert.strictEqual(prog.textContent, FR["refused"] + " " + FR["refused"]);
    let finish;
    reply = new Promise((r) => { finish = r; });
    const run = h.fns.pullModel("owner/name");
    await tick();
    const queued = (L) => esc(L["{prefix}: {text}"]).replace("{prefix}", esc(L["Queued"])).replace("{text}", '<span translate="no">owner/name</span>');
    assert.strictEqual(prog.innerHTML, queued(FR), "Queued: {tag} through the label frame, the tag never translated");
    h.switchTo("de");
    assert.strictEqual(prog.innerHTML, queued(DE), "the queued line follows a switch while the request runs");
    finish({ backend: "vllm" }); await run;
    assert.strictEqual(prog.textContent, "fetching 2/5 <shards>", "the job's own words, as text");
    h.switchTo("fr");
    assert.strictEqual(prog.textContent, "fetching 2/5 <shards>");
    reply = new Error("no <b>space</b>");
    await h.fns.pullModel("owner/name");
    assert.strictEqual(prog.textContent, FR["{prefix}: {text}"].replace("{prefix}", FR["Download failed"]).replace("{text}", "no <b>space</b>"));
    assert.strictEqual(prog._html, null, "a failure is TEXT");
    h.switchTo("de");
    assert.strictEqual(prog.textContent, DE["{prefix}: {text}"].replace("{prefix}", DE["Download failed"]).replace("{text}", "no <b>space</b>"));
  }
  {
    const h = harness({}, { egress: false });
    h.nodes["llm-pull-progress"].textContent = "";
    await h.fns.pullModel("ministral:q4");
    assert.strictEqual(h.calls.egress.length, 1);
    assert.deepStrictEqual(h.calls.api, [], "a declined consent reached the network");
  }

  // 6. The downloads list: the heading and the states follow a switch between polls; an empty queue empties it.
  {
    let status = { active: { model: "a<b>", percent: 40, status: "pulling manifest" }, queue: ["q1"] };
    const h = harness({ "/api/llm/pull/status": () => status });
    await h.fns._llmPullRefresh();
    const box = h.nodes["llm-downloads"];
    assert.ok(box.innerHTML.startsWith('<h3 style="margin:0 0 6px">Downloads</h3>') && box.innerHTML.includes("<code>a&lt;b&gt;</code>"), box.innerHTML);
    assert.strictEqual(box.style.display, "");
    h.switchTo("fr");
    assert.ok(box.innerHTML.startsWith(`<h3 style="margin:0 0 6px">${esc(FR["Downloads"])}</h3>`), box.innerHTML);
    assert.ok(box.innerHTML.includes(`<span class="pill">${esc(FR["Pulling"])}</span>`) && box.innerHTML.includes(`<span class="pill muted">${esc(FR["Queued"])}</span>`), box.innerHTML);
    assert.ok(box.innerHTML.includes(">" + esc(FR["Cancel"]) + "</button>"), box.innerHTML);
    assert.strictEqual(h.calls.api.length, 1, "a switch never polls");
    status = { active: null, queue: [] };
    h.fns.setPoll(7);
    await h.fns._llmPullRefresh();
    assert.strictEqual(box.innerHTML, "");
    assert.strictEqual(box.style.display, "none");
    assert.deepStrictEqual(h.calls.loads, ["models"], "a finished pull re-reads the installed models");
    h.switchTo("de");
    assert.strictEqual(box.innerHTML, "", "an older list came back after the queue emptied");
  }

  console.log("settings_models_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });

function tick() { return new Promise((r) => setImmediate(r)); }
function esc(s) { return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;"); }
