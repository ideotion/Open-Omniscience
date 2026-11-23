// Settings -> Data & backup: the import, newsletter and storage lines follow a language switch, run as REAL code (row 367).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Each of these lines used to be written once with t() output into an ordinary node, so it stayed in the language that
// was active when it was drawn. They are now drawn through ooLive/ooLiveHtml from what the panel already holds, and a
// switch redraws them with no request. The panel functions AND the helper are EXTRACTED from the shipped modules, and
// t()/tf() are the shipped engine over the shipped locales, so a plural form or a translation is the real one.

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

// ---- a DOM just large enough for ooLive: text nodes, elements, attributes, connection ----
class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; }
  get textContent() { return this.nodeValue; }
  set textContent(v) { this.nodeValue = String(v); }
}
class El {
  constructor(tag) { this.nodeName = tag; this.childNodes = []; this.attrs = {}; this.parentNode = null; this._html = null; this.style = {}; this.value = ""; }
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
}

const IDS = ["nl-result", "nl-folder-progress", "nl-folder-controls", "nl-folder-bar", "nl-remove-panel", "nl-remove-count",
  "storage-lanes", "storage-reading", "mbox-result", "mbox-btn", "mbox-host", "mbox-user", "mbox-pass", "mbox-proto", "mbox-port", "mbox-folder", "mbox-limit"];

// answers: route -> a reply, an Error to throw, or a function of the call returning either.
function harness(answers) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = {};
  for (const id of IDS) nodes[id] = new El("DIV");
  const calls = { api: [], toasts: [] };
  const api = async (url) => {
    calls.api.push(url);
    let a = answers[url];
    if (typeof a === "function") a = a();
    if (a instanceof Error) throw a;
    if (a === undefined) throw new Error("unexpected call " + url);
    return a;
  };
  const src = [
    "const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    ...["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml", "ooLiveRepaint",
      "ooLtrIsolate", "ooLabelHtml", "ooLabelText", "_nlAnonLine"].map(extract),
    "let _nlLastRun = null, _nlImportPoll = null, _laneStorageLast = null, _laneStorageErr = false, _readPaints = 0;",
    // the table itself is another surface's (and repainted by its own listener); here it only has to be told apart.
    // The reading line counts its draws, so a switch during an error is seen to redraw it from the last good payload.
    'function _paintLaneStorage(rep, withTable = true) { _readPaints++; $("storage-reading").innerHTML = "R" + _readPaints + ":" + rep.mark;' +
    ' if (withTable) $("storage-lanes").innerHTML = "<table>" + rep.mark + "</table>"; }',
    ...["_folderImportRefresh", "loadNewsletterRemoveCount", "undoNewsletterAttach", "repaintLaneStorageFromCache",
      "loadLaneStorage", "pullMailbox"].map(extract),
    "return { _folderImportRefresh, loadNewsletterRemoveCount, undoNewsletterAttach, repaintLaneStorageFromCache, loadLaneStorage, pullMailbox, ooLiveRepaint };",
  ].join("\n");
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  const fmtNum = (x) => String(Math.round(x)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const document = { createElement: (tag) => new El(tag.toUpperCase()), documentElement: { dir: "ltr" }, querySelectorAll: () => [] };
  const env = {
    window: { OOI18N }, OOI18N, document, MutationObserver: undefined, console,
    $: (id) => nodes[id] || null, api, esc, fmtNum,
    toast: (m, k) => calls.toasts.push([m, k]), confirm: () => true,
    clearInterval: () => {}, loadNewsletterAttach: async () => {},
    ensureOnline: async () => true, _jobStillRunning: (st) => !!(st && st.running),
    pollJobStatus: null,
  };
  const box = { pollJobStatus: async () => ({}) };
  env.pollJobStatus = (...a) => box.pollJobStatus(...a);
  const fns = new Function(...Object.keys(env), src)(...Object.values(env));
  return {
    fns, nodes, calls, box,
    // setLang() as shipped: swap the map, then the ONE oo:langchange listener, in its order (app-boot.js)
    switchTo(l) {
      lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l));
      fns.ooLiveRepaint();
      fns.repaintLaneStorageFromCache();
    },
  };
}

(async () => {
  // 1. The folder import's RUNNING line (S5): one keyed sentence, repainted on a switch without a poll.
  {
    const h = harness({
      "/api/newsletters/import-folder/status": { state: "running", percent: 45, files_done: 9, files_total: 20, eta_seconds: 120, tally: { stored: 5, duplicate: 2 } },
    });
    await h.fns._folderImportRefresh();
    const prog = h.nodes["nl-folder-progress"];
    assert.strictEqual(prog.innerHTML, "Importing… 45% (9/20) · imported: 5 · duplicates skipped: 2 · ~2 min left");
    const n = h.calls.api.length;
    h.switchTo("fr");
    assert.strictEqual(prog.innerHTML, "Importation… 45% (9/20) · importés : 5 · doublons ignorés : 2 · ~2 " + locale("fr")["min left"]);
    assert.strictEqual(h.calls.api.length, n, "a switch never polls");
  }

  // 2. The DONE line (S4): the poll stops here, which is exactly when the old line froze.
  {
    const h = harness({
      "/api/newsletters/import-folder/status": { state: "done", percent: 100, tally: { stored: 5, duplicate: 2 } },
      "/api/newsletters/imported-count": { count: 5 },
    });
    await h.fns._folderImportRefresh();
    const prog = h.nodes["nl-folder-progress"];
    assert.strictEqual(prog.textContent, "Done. Imported: 5 · duplicates skipped: 2.");
    await new Promise((r) => setImmediate(r));   // the count refresh the done line starts
    const n = h.calls.api.length;
    h.switchTo("zh");
    assert.strictEqual(prog.textContent, "完成。已导入：5 · 跳过的重复项：2。", "no Latin space after the full-width mark");
    assert.strictEqual(h.calls.api.length, n, "a switch never polls");
  }

  // 3. The remove panel's count (S2): a plural chosen by the engine, and chosen again in the new language.
  {
    let count = 1;
    const h = harness({ "/api/newsletters/imported-count": () => ({ count }) });
    await h.fns.loadNewsletterRemoveCount();
    const lab = h.nodes["nl-remove-count"];
    assert.strictEqual(lab.textContent, "1 imported newsletter in your corpus", "singular, never '1 imported newsletters'");
    count = 3;
    await h.fns.loadNewsletterRemoveCount();
    assert.strictEqual(lab.textContent, "3 imported newsletters in your corpus");
    const n = h.calls.api.length;
    h.switchTo("ru");
    assert.strictEqual(lab.textContent, "3 импортированные рассылки в вашем корпусе", "the Russian [few] form");
    assert.strictEqual(h.calls.api.length, n, "a switch never re-reads the count");
    count = 0;
    await h.fns.loadNewsletterRemoveCount();
    assert.strictEqual(lab.textContent, "", "nothing to remove, nothing said");
  }

  // 4. The move-back line (S3): the count in bold inside one keyed plural sentence; the toast says the same.
  {
    const h = harness({ "/api/newsletters/attach/undo": { restored: 1, sources_deleted: ["example.org"] } });
    await h.fns.undoNewsletterAttach({ disabled: false });
    const out = h.nodes["nl-result"];
    assert.ok(out.innerHTML.startsWith("<b>1</b> newsletter moved back to the import bucket."), out.innerHTML);
    assert.ok(out.innerHTML.includes("example.org"), out.innerHTML);
    assert.deepStrictEqual(h.calls.toasts, [["1 newsletter moved back to the import bucket.", "ok"]]);
    const n = h.calls.api.length;
    h.switchTo("fr");
    assert.ok(out.innerHTML.startsWith("<b>1</b> newsletter replacée dans le bac d&#39;importation."), out.innerHTML);
    assert.ok(out.innerHTML.includes(locale("fr")["Removed the now-empty sources this filing had created"]), out.innerHTML);
    assert.strictEqual(h.calls.api.length, n, "a switch never re-runs the undo");
  }

  // 5. Settings -> Storage: an error after a table. A switch must not draw the OLD table back over the error, and the
  //    error itself follows the switch; a later good read takes the host back for the table.
  {
    let reply = { mark: "OLD" };
    const h = harness({ "/api/storage/lanes": () => reply });
    await h.fns.loadLaneStorage();
    const lanes = h.nodes["storage-lanes"];
    assert.strictEqual(lanes.innerHTML, "<table>OLD</table>");
    reply = new Error("disk <b>gone</b>");
    await h.fns.loadLaneStorage();
    assert.ok(lanes.innerHTML.includes("Storage could not be read") && lanes.innerHTML.includes("disk &lt;b&gt;gone&lt;/b&gt;"), lanes.innerHTML);
    assert.ok(!lanes.innerHTML.includes("<b>gone"), "the server's words are escaped: " + lanes.innerHTML);
    const n = h.calls.api.length;
    const reading = h.nodes["storage-reading"].innerHTML;
    h.switchTo("fr");
    assert.ok(!lanes.innerHTML.includes("<table>"), "the stale table was drawn over the error: " + lanes.innerHTML);
    assert.ok(lanes.innerHTML.includes(locale("fr")["Storage could not be read"]) && lanes.innerHTML.includes("disk &lt;b&gt;gone"), lanes.innerHTML);
    assert.ok(h.nodes["storage-reading"].innerHTML !== reading && h.nodes["storage-reading"].innerHTML.endsWith(":OLD"),
      "the reading line still follows a switch during an error, from the last good payload: " + h.nodes["storage-reading"].innerHTML);
    assert.strictEqual(h.calls.api.length, n, "a switch never re-reads storage");
    reply = { mark: "NEW" };
    await h.fns.loadLaneStorage();
    assert.strictEqual(lanes.innerHTML, "<table>NEW</table>");
    h.switchTo("de");
    assert.strictEqual(lanes.innerHTML, "<table>NEW</table>", "the released error never comes back");
  }

  // 6. The mailbox pull: the server's progress words are TEXT (an "&" stays "&", never "&amp;"), and the tally follows a switch.
  {
    const h = harness({ "/api/newsletters/mailbox": { started: true } });
    for (const [id, v] of [["mbox-host", "imap.example.org"], ["mbox-user", "me"], ["mbox-pass", "pw"], ["mbox-proto", "imap"], ["mbox-limit", "50"]]) h.nodes[id].value = v;
    const out = h.nodes["mbox-result"];
    let during = null;
    h.box.pollJobStatus = async (url, opts) => {
      opts.onProgress({ detail: "Fetched 3 of 10 & counting" });
      during = out.textContent;
      return { state: "done", result: { tally: { stored: 2, duplicate: 1 } } };
    };
    await h.fns.pullMailbox();
    assert.strictEqual(during, "Fetched 3 of 10 & counting");
    assert.ok(out.innerHTML.startsWith("<b>2</b> imported · 1 duplicates skipped"), out.innerHTML);
    assert.strictEqual(h.nodes["mbox-pass"].value, "", "the password never stays in the field");
    const n = h.calls.api.length;
    h.switchTo("de");
    const de = locale("de");
    assert.ok(out.innerHTML.startsWith("<b>2</b> " + de["imported"] + " · 1 " + de["duplicates skipped"]), out.innerHTML);
    assert.strictEqual(h.calls.api.length, n, "a switch never pulls again");
  }

  console.log("settings_imports_live_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
