// The corpus encryption, panic wipe, free-space overwrite and uninstall results follow a language switch (row 366(c)).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Each function is EXTRACTED from the shipped module and drawn through the shipped ooLive helper, with the shipped t() over
// the shipped locales; a line drawn in one language is switched by ooLiveRepaint alone, with no request.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

function extractFrom(src, name) {
  const re = new RegExp("(?:async )?function " + name + "\\(");
  const m = re.exec(src);
  assert.ok(m, name + " not found -- was it renamed?");
  const at = m.index;
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
  return src.slice(at, j);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));

class Text {
  constructor(v) { this.nodeValue = String(v); this.parentNode = null; }
  get textContent() { return this.nodeValue; }
}
class El {
  constructor(tag) { this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null; this.style = {}; this.disabled = false; this.dataset = {}; }
  append(...nodes) { for (const n of nodes) { const c = typeof n === "string" ? new Text(n) : n; c.parentNode = this; this.childNodes.push(c); } this._html = null; }
  appendChild(n) { this.append(n); return n; }
  get isConnected() { return true; }
  hasAttribute(a) { return Object.prototype.hasOwnProperty.call(this.attrs, a); }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  removeAttribute(a) { delete this.attrs[a]; }
  replaceChildren(...nodes) { this.childNodes = nodes; this._html = null; for (const c of nodes) c.parentNode = this; }
  set innerHTML(h) { this.replaceChildren(); this._html = String(h); }
  get innerHTML() { return this._html == null ? "" : this._html; }
  set textContent(v) { this.replaceChildren(new Text(v)); }
  get textContent() {
    if (this._html != null) {
      // the text a page shows for this markup: everything outside a tag (a character walk, not a regex rewrite)
      let out = "", inTag = false;
      for (const ch of this._html) {
        if (ch === "<") inTag = true;
        else if (ch === ">" && inTag) inTag = false;
        else if (!inTag) out += ch;
      }
      return out;
    }
    return this.childNodes.map((c) => c.textContent).join("");
  }
}


// The esc the page uses, so an apostrophe or a quote in a translation is compared as the page writes it.
const esc = (x) => String(x).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const ESCAPED = (s) => esc(s);

function harness(byId) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const asked = { confirm: [], prompt: [], toast: [], requests: [] };
  const answers = {};
  let typed = null;
  const window = { OOI18N, console: { warn() {} } };
  const document = { createElement: (tag) => new El(tag.toUpperCase()), getElementById: (id) => byId[id] || null };
  const names = ["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml",
    "ooLiveRepaint", "_uninstallSel", "_panicScrubHtml", "panicWipe", "secureErase", "uninstallApp", "encryptCorpus"];
  const src = ["const _ooLiveNodes = new Set();", "let _ooLiveObs = null;", "let _panicPaint = null;", "let _panicScrubs = [];",
    "const _atRestDoc = {};", ...names.map((n) => extractFrom(APP, n)),
    "return { ooLiveRepaint, panicWipe, secureErase, uninstallApp, encryptCorpus };"].join("\n");
  const api = async (url) => { asked.requests.push(url); const a = answers[url.split("?")[0]]; if (a instanceof Error) throw a; return a; };
  const fns = new Function("window", "document", "console", "OOI18N", "$", "api", "ooServerText", "esc", "MutationObserver", "confirm",
    "prompt", "toast", "localStorage", "fmtNum", "humanBytes", "_fmtBytes", "_failMsg", "_terminalOverlay", "openUnifiedExport",
    "loadAtRestState", src)(
    window, document, window.console, OOI18N, (id) => byId[id] || null, api, (s) => String(s), esc, undefined,
    (m) => { asked.confirm.push(m); return true; }, (m) => { asked.prompt.push(m); return typed; }, (m) => { asked.toast.push(m); },
    { removeItem() {} }, (n) => String(n), (n) => n + " B", (n) => n + " B", (k) => k, () => {}, () => {}, () => {});
  return {
    fns, asked, fr: locale("fr"),
    answer: (url, v) => { answers[url] = v; },
    type: (w) => { typed = w; },
    switchTo: (l) => { lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l)); fns.ooLiveRepaint(); },
  };
}

const HOLDER_EN = "Another program had the database open during the erase, so the erase may be incomplete: that program may have written the database’s key material back to the disk. Close that program or restart the computer, then run a full overwrite of free disk space below.";
const REC_EN = "Your store was not encrypted, so a full disk-overwrite is recommended before you stop.";
const PS_EN = "The unencrypted main database was overwritten in full.";

async function main() {
  // The panic wipe's result, and a free-space overwrite listed under it, follow a switch with no request.
  {
    const box = new El("DIV");
    const h = harness({ "panic-result": box });
    h.type("WIPE");
    h.answer("/api/safety/panic", { encrypted_corpus: false, other_holder: "held", files_wiped: 2, files_seen: 2, limit: "L",
      corpus_encryption: "not_encrypted", plaintext_store: { form: "plaintext", state: "overwritten" } });
    await h.fns.panicWipe();
    for (const en of [HOLDER_EN, REC_EN, PS_EN, "erase may be incomplete", "Single pass"]) assert.ok(box.innerHTML.includes(esc(en)), en);
    h.answer("/api/safety/secure-erase", { passes: 3, bytes_written: 9, limit: "L2", scrub_folder: "/s", reserve_bytes: 1 });
    await h.fns.secureErase(3);
    assert.ok(box.innerHTML.includes(">overwritten<"), "the overwrite is listed under the wipe");
    assert.ok(box.innerHTML.includes(esc(HOLDER_EN)), "and the wipe's result stays above it");
    const n = h.asked.requests.length;
    h.switchTo("fr");
    for (const en of [HOLDER_EN, REC_EN, PS_EN, "erase may be incomplete", "Single pass", "overwritten"]) {
      assert.ok(h.fr[en] && h.fr[en] !== en, "a French line exists for " + en);
      assert.ok(box.innerHTML.includes(esc(h.fr[en])), "the result follows the switch: " + en);
      assert.ok(!box.innerHTML.includes(esc(en)), "no English left: " + en);
    }
    assert.ok(box.innerHTML.includes("3×"), "the overwrite stays listed");
    assert.strictEqual(h.asked.requests.length, n, "a repaint never asks the server again");
    // a new wipe replaces the overwrites listed under the last one
    await h.fns.panicWipe();
    assert.ok(!box.innerHTML.includes("3×"));
  }
  // An overwrite whose free space could not be used says so, and follows a switch.
  {
    const box = new El("DIV");
    const h = harness({ "panic-result": box });
    h.answer("/api/safety/secure-erase", { scrub_not_done: "other_drive" });
    await h.fns.secureErase(1);
    const en = "Free disk space was not overwritten: the folder above the erased data folder is on another drive, so writing there would not reach the erased data.";
    assert.ok(box.innerHTML.includes(esc(en)));
    h.switchTo("de");
    assert.ok(box.innerHTML.includes(esc(locale("de")[en])));
  }
  // The uninstall dialog asks in the operator's language; the typed word stays the ASCII UNINSTALL; the result follows a switch.
  {
    const box = new El("DIV");
    const h = harness({ "uninstall-result": box, "uninstall-mode": { value: "minimal" } });
    h.switchTo("fr");
    h.type("UNINSTALL");
    h.answer("/api/safety/uninstall", { scheduled: true, note: "N" });
    await h.fns.uninstallApp();
    const fr = h.fr;
    assert.ok(h.asked.confirm[0].startsWith(fr["UNINSTALL: remove the virtualenv and desktop launchers, then stop the server."]));
    assert.ok(h.asked.confirm[0].includes(fr["Your data is KEPT."]) && h.asked.confirm[0].endsWith(fr["Continue?"]));
    assert.strictEqual(h.asked.prompt[0], fr["To confirm, type UNINSTALL in capitals:"]);
    assert.ok(h.asked.prompt[0].includes("UNINSTALL"));
    assert.ok(box.innerHTML.includes(esc(fr["uninstalling"])));
    h.switchTo("ja");
    assert.ok(box.innerHTML.includes(esc(locale("ja")["uninstalling"])), "the result follows the switch");
  }
  {
    const box = new El("DIV");
    const h = harness({ "uninstall-result": box });
    h.type("UNINSTALL");
    h.answer("/api/safety/uninstall", { scheduled: false });
    await h.fns.uninstallApp();
    assert.strictEqual(box.textContent, "Nothing to remove.");
    h.switchTo("fr");
    assert.strictEqual(box.textContent, h.fr["Nothing to remove."]);
  }
  // The corpus encryption message follows a switch.
  {
    const msg = new El("DIV");
    const panel = { querySelector: (sel) => (sel === "#atrest-msg" ? msg : sel === "#atrest-consent" ? { checked: false } : { value: "" }) };
    const h = harness({});
    await h.fns.encryptCorpus({ closest: () => panel });
    assert.strictEqual(msg.textContent, "Tick the consent box first.");
    h.switchTo("fr");
    assert.strictEqual(msg.textContent, h.fr["Tick the consent box first."]);
  }
  console.log("erase_live_text_366c_node_test.js: OK");
}

main().catch((e) => { console.error(e); process.exit(1); });
