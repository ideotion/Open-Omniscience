// Settings > Backup text that follows a language switch (row 366, the app-backup.js part of the row 352 list).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Each renderer below is EXTRACTED from the shipped module and drawn through the shipped ooLive helper, with the shipped
// t() over the shipped locales. A line drawn in English is switched to French by ooLiveRepaint alone, with no request:
// the repaint draws from what was already read.

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
  constructor(tag) { this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null; this.style = {}; this.disabled = false; }
  get isConnected() { return true; }
  hasAttribute(a) { return Object.prototype.hasOwnProperty.call(this.attrs, a); }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  removeAttribute(a) { delete this.attrs[a]; }
  replaceChildren(...nodes) { this.childNodes = nodes; this._html = null; for (const c of nodes) c.parentNode = this; }
  set innerHTML(h) { this.replaceChildren(); this._html = String(h); }
  get innerHTML() { return this._html == null ? "" : this._html; }
  set textContent(v) { this.replaceChildren(new Text(v)); }
  get textContent() {
    if (this._html != null) return this._html.replace(/<[^>]*>/g, "");
    return this.childNodes.map((c) => c.textContent).join("");
  }
}

function harness(byId) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const requests = [];
  let answer = null;
  const window = { OOI18N, console: { warn() {} } };
  const document = { createElement: (tag) => new El(tag.toUpperCase()), getElementById: (id) => byId[id] || null };
  const names = ["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml",
    "ooLiveRepaint", "_volRefresh", "loadAlternates", "_altFetch"];
  const src = ["const _ooLiveNodes = new Set();", "let _ooLiveObs = null;", "let _volPollTimer = null;", "let _altRep = null;",
    ...names.map((n) => extractFrom(APP, n)),
    "return { ooLiveRepaint, _volRefresh, loadAlternates };"].join("\n");
  const api = async (url) => { requests.push(url); if (answer instanceof Error) throw answer; return answer; };
  const fns = new Function("window", "document", "console", "OOI18N", "$", "api", "ooServerText", "_uxFmtS", "esc", "_altHtml", "MutationObserver", src)(
    window, document, window.console, OOI18N, (id) => byId[id] || null, api, (s) => String(s), (n) => n + " s",
    (s) => String(s), (rep, t) => "<b>" + t("Cancelled.") + "</b> " + rep.items.length, undefined);
  return {
    fns, requests,
    answer: (v) => { answer = v; },
    switchTo: (l) => { lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l)); fns.ooLiveRepaint(); },
  };
}

async function main() {
  const fr = locale("fr");
  // the volume status line, in each state it draws
  for (const [status, en, frKey] of [
    [{ state: "done", mode: "restore" }, "Restore complete.", "Restore complete."],
    [{ state: "cancelled" }, "Cancelled.", "Cancelled."],
    [{ state: "error" }, "Failed: unknown error", null],
  ]) {
    const prog = new El("SPAN");
    const h = harness({ "vb-progress": prog });
    h.answer(status);
    await h.fns._volRefresh("vb-progress", null, null);
    assert.strictEqual(prog.textContent, en);
    const asked = h.requests.length;
    h.switchTo("fr");
    const want = frKey ? fr[frKey] : fr["Failed:"] + " " + fr["unknown error"];
    assert.strictEqual(prog.textContent, want, "the volume line follows the switch");
    assert.strictEqual(h.requests.length, asked, "a repaint never asks the server again");
  }
  {
    const prog = new El("SPAN");
    const h = harness({ "vb-progress": prog });
    h.answer({ state: "done", summary: { volumes: 3 } });
    await h.fns._volRefresh("vb-progress", null, null);
    assert.strictEqual(prog.textContent, "Backup complete: 3 volumes");
    h.switchTo("fr");
    assert.strictEqual(prog.textContent, fr["Backup complete:"] + " 3 " + fr["volumes"]);
  }
  {
    const prog = new El("SPAN");
    const h = harness({ "vb-progress": prog });
    h.answer(new Error("offline"));
    await h.fns._volRefresh("vb-progress", null, null);
    assert.strictEqual(prog.textContent, "Status check failed.");
    h.switchTo("fr");
    assert.strictEqual(prog.textContent, fr["Status check failed."]);
  }
  // the differences panel: drawn from the page it read, and its failure line
  {
    const host = new El("DIV");
    const h = harness({ "alt-body": host, "alt-status": { value: "pending" } });
    h.answer({ items: [{ id: 1 }, { id: 2 }] });
    await h.fns.loadAlternates();
    assert.strictEqual(host.textContent, "Cancelled. 2");
    const asked = h.requests.length;
    h.switchTo("fr");
    assert.strictEqual(host.textContent, fr["Cancelled."] + " 2", "the differences panel follows the switch");
    assert.strictEqual(h.requests.length, asked, "a repaint never asks the server again");
    assert.ok(host.hasAttribute("data-i18n-dyn"), "the HTML host is marked while it is held");
  }
  {
    const host = new El("DIV");
    const h = harness({ "alt-body": host, "alt-status": { value: "pending" } });
    h.answer(new Error("offline"));
    await h.fns.loadAlternates();
    assert.strictEqual(host.textContent, "The differences could not be read.");
    h.switchTo("fr");
    assert.strictEqual(host.textContent, fr["The differences could not be read."]);
  }
  console.log("backup_live_text_node_test.js: OK");
}

main().catch((e) => { console.error(e); process.exit(1); });
