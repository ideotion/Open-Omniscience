// The 2026-09-27 re-walk, batch B26 (rows J, H and U), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What a source-level check cannot see: that an export whose large-data copy never ran
// reads as INCOMPLETE and offers to finish it (J-1), that the shared folder picker draws
// a path and a dated folder name as left-to-right runs that wrap (J-2, J-4), that the
// reopened completion line takes the locale's own brackets (J-3), and that the at-rest
// lines and the topic-discovery result line are drawn in the CURRENT language from what
// they last showed (U-2, H-2). A MARKING translator ("«…»") shows every string that went
// through it. EXTRACTED from the shipped modules, never re-typed.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = APP.indexOf("(", at), depth = 0;
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

const ESC = "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n";
const mark = (s) => "«" + s + "»";
const tfMark = (s, v) => mark(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m));
const plainT = (s) => s;
const plainTf = (s, v) => s.replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m));

let n = 0;
const pending = [];
function test(name, fn) {
  pending.push((async () => { await fn(); n++; console.log("ok  - " + name); })());
}

const el = () => ({ innerHTML: "", textContent: "", value: "", style: {}, dataset: {}, disabled: false,
                    removeAttribute() {}, setAttribute() {} });

// ------------------------------------------------------------------------------ //
//  J-1: the completion panel names what the export asked for and does not hold    //
// ------------------------------------------------------------------------------ //
const base = {
  destination: "/mnt/stick/202609271124_OpenOmniscience_Backup",
  folder: "202609271124_OpenOmniscience_Backup",
  corpus_included: true,
  volumes: { count: 4, bytes: 800, plaintext_bytes: 540, parity: true },
  tables: [{ name: "articles", rows: 300 }],
  files: [],
  elapsed: { corpus_s: 12.5, files_s: null, files_s_reason: "no large-data files were copied" },
  encryption: { corpus_encrypted: true, files_encrypted: null, note: "n" },
  schema: { backup_schema: "oo-backup-2", container: "oo-volumes-2", alembic_rev: "abc" },
  app_version: "0.4.0",
  verify: { state: "verified", total: 4, bad: [] },
  attribution: [],
  attribution_error: null,
};

function panel(I18N) {
  const host = { innerHTML: "", clicked: [], button: null };
  // The renderer attaches the button's listener through querySelector after drawing.
  host.querySelector = (sel) => {
    if (sel !== "[data-ux-complete]" || !/data-ux-complete/.test(host.innerHTML)) return null;
    host.button = { listeners: [], addEventListener(ev, fn) { this.listeners.push([ev, fn]); } };
    return host.button;
  };
  const src = ESC +
    "function humanBytes(n){return String(n)+' B';}\n" +
    extract("fmtNum") + "\n" +
    "var document = { getElementById: function(id){ return id === 'ux-summary' ? HOST : null; } };\n" +
    "var _uxExportFacts = null;\n" +
    "function _uxCompleteExport(b){ HOST.clicked.push(b); }\n" +
    extract("_uxRenderExportPanel") + "\n" + extract("_uxVerifySentence") + "\n" + extract("_uxVerifyDetail") + "\n" +
    "return { render: _uxRenderExportPanel };";
  const mod = new Function("window", "OOI18N", "HOST", src)({ OOI18N: I18N }, I18N, host);
  return (facts) => { host.innerHTML = ""; host.button = null; mod.render(facts, I18N.t); return host; };
}

test("J-1: a folder missing the ticked LLM models reads INCOMPLETE, above the verdict, with a way to finish", () => {
  const render = panel({ t: plainT, tf: plainTf });
  const h = render({ ...base, missing: { known: true, corpus: false, categories: ["models", "hf_models"] } });
  const html = h.innerHTML;
  assert.ok(/Incomplete — requested for this export but not in this folder: LLM models/.test(html),
    "the missing member is not named: " + html);
  // Two categories, ONE tick: the operator ticked "LLM models" once.
  assert.strictEqual((html.match(/LLM models/g) || []).length, 1, "one tick named twice: " + html);
  assert.ok(html.indexOf("Incomplete") < html.indexOf("Verified —"),
    "the incomplete line must lead the panel, above a clean verify verdict");
  assert.ok(/data-ux-complete/.test(html) && /Copy the large-data files now/.test(html), "no way to finish the export");
  assert.ok(h.button && h.button.listeners.some(([ev]) => ev === "click"), "the finish button has no listener");
  h.button.listeners[0][1]();
  assert.strictEqual(h.clicked.length, 1, "the finish button does not start the copy");
});

test("J-1: a complete folder, an unknown request and a missing corpus are three different panels", () => {
  const render = panel({ t: plainT, tf: plainTf });
  const clean = render({ ...base, missing: { known: true, corpus: false, categories: [] } }).innerHTML;
  assert.ok(!/Incomplete/.test(clean) && !/data-ux-complete/.test(clean), "a complete export reads incomplete");
  // No record (an export older than the record): what was asked for is UNKNOWN, never a warning.
  const unknown = render({ ...base, missing: { known: false, corpus: false, categories: [] } }).innerHTML;
  assert.ok(!/Incomplete/.test(unknown), "an unknown request was drawn as a missing member");
  const legacy = render({ ...base }).innerHTML;
  assert.ok(!/Incomplete/.test(legacy), "facts without the field were drawn as incomplete");
  // A missing corpus is named, but no button: the large-data copy cannot write a corpus.
  const noCorpus = render({ ...base, missing: { known: true, corpus: true, categories: [] } }).innerHTML;
  assert.ok(/not in this folder: Corpus/.test(noCorpus), "a missing corpus is not named: " + noCorpus);
  assert.ok(!/data-ux-complete/.test(noCorpus), "a copy button offered for a missing corpus");
  // A category no member knows is named as itself rather than dropped.
  const odd = render({ ...base, missing: { known: true, corpus: false, categories: ["wiki_dumps", "future_lane"] } }).innerHTML;
  assert.ok(/Wikipedia dumps · future_lane/.test(odd), "an unmapped category vanished: " + odd);
});

test("J-1: the incomplete sentence, the button and its hover all go through the translator", () => {
  const render = panel({ t: mark, tf: tfMark });
  const html = render({ ...base, missing: { known: true, corpus: false, categories: ["osm_regions"] } }).innerHTML;
  assert.ok(/«Incomplete — requested for this export but not in this folder: «Offline maps»»/.test(html), html);
  assert.ok(/«Copy the large-data files now»/.test(html), "the button label skipped t()");
  assert.ok(/title="«Starts the large-data copy/.test(html), "the button's hover skipped t()");
});

// Reopened dialog: the heading follows the folder's facts, and the brackets are keyed.
async function reopen(I18N, facts) {
  const dom = { "ux-progress": el(), "ux-bar": el(), "ux-pause": el(), "ux-dest": el(), "ux-summary": el() };
  const api = async (url, opts) => {
    if (url === "/api/backup/v2/volumes/status") return { mode: "backup", state: "done", dest: facts.destination, started_at: 5 };
    if (url === "/api/backup/folder/status") return { mode: "backup", state: "done", dest: "/older", started_at: 1 };
    if (url.startsWith("/api/backup/export-summary?dir=")) return { ...facts, summary_path: facts.destination + "/BACKUP_SUMMARY.md" };
    throw new Error("unexpected " + url + " " + JSON.stringify(opts || {}));
  };
  const src = ESC +
    "function humanBytes(n){return String(n)+' B';}\n" +
    "var _uxExportDir = null, _uxPhase = null, _uxExportFacts = null;\n" +
    extract("fmtNum") + "\n" +
    "var document = { getElementById: function(id){ return DOM[id] || null; } };\n" +
    "function _uxShowPaused(){ DOM['ux-progress'].innerHTML = 'PAUSED'; }\n" +
    "function _uxCompleteExport(){}\n" +
    extract("_uxSamePath") + "\n" + extract("_uxPickLastExport") + "\n" +
    extract("_uxRenderExportPanel") + "\n" + extract("_uxVerifySentence") + "\n" + extract("_uxVerifyDetail") + "\n" +
    "async " + extract("_uxShowLastCompletedExportSummary") + "\n" +
    "return { run: _uxShowLastCompletedExportSummary };";
  const mod = new Function("window", "OOI18N", "DOM", "api", src)({ OOI18N: I18N }, I18N, dom, api);
  await mod.run();
  return dom;
}

test("J-1: the reopened dialog no longer reads 'Backup complete' over a folder missing a ticked member", async () => {
  const dom = await reopen({ t: plainT, tf: plainTf },
    { ...base, missing: { known: true, corpus: false, categories: ["models", "hf_models"] } });
  const line = dom["ux-progress"].innerHTML;
  assert.ok(/Backup incomplete →/.test(line) && !/Backup complete/.test(line), "the heading still says complete: " + line);
  assert.ok(/<span dir="ltr"/.test(line) && line.includes(base.destination), "the path lost its LTR isolate: " + line);
  assert.ok(/data-ux-complete/.test(dom["ux-summary"].innerHTML), "the reopened panel offers no way to finish");
});

test("J-3: the '(last completed export)' brackets come from a keyed frame, so zh can use full-width ones", async () => {
  const zhTf = (s, v) => (s === "({text})" ? "（{text}）" : s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m));
  const zhT = (s) => (s === "last completed export" ? "上次已完成的导出" : s);
  const dom = await reopen({ t: zhT, tf: zhTf }, { ...base, missing: { known: true, corpus: false, categories: [] } });
  const line = dom["ux-progress"].innerHTML;
  assert.ok(/（上次已完成的导出）/.test(line), "the zh line kept welded ASCII brackets: " + line);
  assert.ok(!/\(上次/.test(line), "ASCII brackets around a Chinese phrase: " + line);
});

test("J-1: 'Copy the large-data files now' copies the MISSING categories into the SAME folder, then completes", async () => {
  const dom = { "ux-progress": el(), "ux-bar": el(), "ux-pause": el(), "ux-run": el(), "ux-summary": el() };
  const calls = [];
  const finished = [];
  const api = async (url, opts) => { calls.push({ url, body: opts && opts.body ? JSON.parse(opts.body) : null }); return {}; };
  const facts = { ...base, missing: { known: true, corpus: false, categories: ["models", "hf_models"] } };
  const src = ESC +
    "function ooServerText(s){return String(s);}\n" +
    "var _uxExportDir = null, _uxPhase = null, _uxExportIncluded = null, _uxExportFacts = FACTS;\n" +
    "var document = { getElementById: function(id){ return DOM[id] || null; } };\n" +
    "function _uxShowPaused(){ DOM['ux-progress'].innerHTML = 'PAUSED'; }\n" +
    "async function _uxStartThenPoll(start, statusUrl, kind, ui, expect){ await start(); CALLS.push({ poll: statusUrl, kind, expect }); return { state: 'done' }; }\n" +
    "async function _uxFinishExport(prog, dest){ FIN.push({ dest, inc: _uxExportIncluded, phase: _uxPhase }); }\n" +
    "async " + extract("_uxCompleteExport") + "\n" +
    "return { run: _uxCompleteExport, dir: () => _uxExportDir };";
  const I18N = { t: plainT, tf: plainTf };
  const mod = new Function("window", "OOI18N", "DOM", "api", "FACTS", "CALLS", "FIN", src)(
    { OOI18N: I18N }, I18N, dom, api, facts, calls, finished);
  const btn = el();
  await mod.run(btn);
  const start = calls.find((c) => c.url === "/api/backup/folder/start");
  assert.ok(start, "the copy was never started: " + JSON.stringify(calls));
  assert.deepStrictEqual(start.body, { dest: base.destination, categories: ["models", "hf_models"] },
    "the copy does not go into the export's own folder with the missing categories");
  const poll = calls.find((c) => c.poll);
  assert.deepStrictEqual(poll.expect, { dest: base.destination }, "the poll would adopt another destination's job");
  assert.strictEqual(finished.length, 1, "the finished copy does not end on the one completion");
  assert.strictEqual(finished[0].dest, base.destination);
  assert.deepStrictEqual(finished[0].inc, { corpus: true, blobs: ["models", "hf_models"] });
  assert.strictEqual(mod.dir(), base.destination, "a pause mid-copy would resume into another folder");
});

// ------------------------------------------------------------------------------ //
//  J-2 / J-4: the shared folder picker                                            //
// ------------------------------------------------------------------------------ //
test("J-2/J-4: the picker draws the path and each folder name as LTR runs, and the rows wrap", async () => {
  const dom = { "fp-path": el(), "fp-list": el(), "fp-use": el(), "fp-note": el() };
  dom["fp-list"].querySelectorAll = () => [];
  const listing = {
    path: "/tmp/claude-0/rewalk/J/drive", parent: "/tmp/claude-0/rewalk/J",
    entries: [
      { name: "202609271124_OpenOmniscience_Backup", path: "/tmp/claude-0/rewalk/J/drive/202609271124_OpenOmniscience_Backup" },
      { name: "202609271124_OpenOmniscience_Backup_2", path: "/tmp/claude-0/rewalk/J/drive/202609271124_OpenOmniscience_Backup_2" },
    ],
    writable: true,
  };
  const src = ESC +
    "var _fpState = { inputId: 'ux-dest', requireWritable: true, current: null };\n" +
    "function $(id){ return DOM[id] || null; }\n" +
    "async function api(){ return LISTING; }\n" +
    "async " + extract("_fpNav") + "\n" +
    "return { nav: _fpNav };";
  const I18N = { t: plainT, tf: plainTf };
  const mod = new Function("window", "OOI18N", "DOM", "LISTING", src)({ OOI18N: I18N }, I18N, dom, listing);
  await mod.nav(null);
  assert.strictEqual(dom["fp-path"].innerHTML, '<bdi dir="ltr">/tmp/claude-0/rewalk/J/drive</bdi>',
    "the path line is not an LTR run: " + dom["fp-path"].innerHTML);
  const rows = dom["fp-list"].innerHTML;
  for (const e of listing.entries) {
    assert.ok(rows.includes(`<bdi dir="ltr">${e.name}</bdi>`), "a folder name is not an LTR run: " + rows);
  }
  const folderRows = rows.split("</div>").filter((r) => /📁/.test(r));
  assert.strictEqual(folderRows.length, 2);
  for (const r of folderRows) assert.ok(/overflow-wrap:anywhere/.test(r), "a folder row cannot wrap at 375 px: " + r);
  // The data-path (what a click navigates to) is unchanged.
  assert.ok(rows.includes(`data-path="${listing.entries[1].path}"`));
});

// ------------------------------------------------------------------------------ //
//  U-2: the at-rest lines redraw in the current language, from the last reading   //
// ------------------------------------------------------------------------------ //
test("U-2: _renderAtRest draws from the cached doctor reading in whatever language is current", () => {
  const box = el(), enc = el();
  const I18N = { t: plainT, tf: plainTf };
  const src = ESC +
    "function $(id){ return id === 'atrest-state' ? BOX : (id === 'atrest-encrypt' ? ENC : null); }\n" +
    extract("ooLabelHtml") + "\n" +
    "var _atRestDoc = { corpus: { state: 'encrypted', cipher: '4.12.0 community' }, custody_log: { state: 'absent' } };\n" +
    extract("_renderAtRest") + "\n" +
    "return { render: _renderAtRest };";
  const win = { OOI18N: I18N };
  const mod = new Function("window", "OOI18N", "BOX", "ENC", src)(win, I18N, box, enc);
  // First paint in Arabic…
  const AR = { Corpus: "المجموعة", "Custody log": "سجل العهدة", "Encrypted (SQLCipher 4)": "مشفّر (SQLCipher 4)",
               "not created yet": "لم يُنشأ بعد" };
  I18N.t = (s) => AR[s] || s;
  mod.render();
  assert.ok(/المجموعة/.test(box.innerHTML), box.innerHTML);
  // …then the language switch: the SAME function, no fetch, now English.
  I18N.t = plainT;
  mod.render();
  assert.ok(/Corpus: <b>Encrypted \(SQLCipher 4\)<\/b>/.test(box.innerHTML), "ar→en left the lines Arabic: " + box.innerHTML);
  assert.ok(/Custody log: <b>not created yet<\/b>/.test(box.innerHTML), box.innerHTML);
  assert.ok(!/المجموعة|سجل العهدة/.test(box.innerHTML), "Arabic survived the switch: " + box.innerHTML);
  assert.strictEqual(enc.style.display, "none", "an encrypted corpus offered the encrypt form");
});

// ------------------------------------------------------------------------------ //
//  H-2: the topic-discovery result line                                           //
// ------------------------------------------------------------------------------ //
test("H-2: the discovery result line goes through t() and redraws from the saved state", () => {
  const box = el();
  const I18N = { t: mark, tf: tfMark };
  const src = ESC +
    "function $(id){ return id === 'discovery-external-result' ? BOX : null; }\n" +
    "var _discoveryResultOn = null;\n" +
    extract("_paintDiscoveryResult") + "\n" +
    "return { paint: _paintDiscoveryResult, set: (v) => { _discoveryResultOn = v; } };";
  const mod = new Function("window", "OOI18N", "BOX", src)({ OOI18N: I18N }, I18N, box);
  mod.paint();
  assert.strictEqual(box.textContent, "", "a line drawn before anything was saved");
  mod.set(true); mod.paint();
  assert.strictEqual(box.textContent, "«Enabled: topic-discovery queries will be sent to DuckDuckGo.»");
  mod.set(false); mod.paint();
  assert.strictEqual(box.textContent, "«Disabled (the default): no topic query leaves this machine.»");
});

Promise.all(pending).then(() => {
  console.log(`clickthrough b26 node suite: ${n} ok`);
}).catch((e) => { console.error(e); process.exit(1); });
