// Row 361 group 5 (app-diagnostics.js): the enrich, discover, gold-builder and parts-bar lines follow a language
// switch. Each is drawn through ooLive/ooLiveHtml (row 364), so the switch calls the kept render again. The helper
// here is reduced to "draw now, keep the render, redraw on switchTo, a null release puts the old text back"; its
// own behaviour (marker, walker, prune, foreign writes) is tested on the real code in oo_live_node_test.js.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

"use strict";
const assert = require("assert");
const APP = require("./app_source.js").appJs();

function fnSource(name) {
  const m = new RegExp("(?:async\\s+)?function\\s+" + name + "\\s*\\(").exec(APP);
  assert.ok(m, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", m.index));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(m.index, j);
}

const SRC = [
  "let lang = 'en';",
  "const fr = (s) => lang === 'fr' ? 'FR[' + s + ']' : s;",
  "const OOI18N = { t: fr, tf: (s, v) => fr(s).replace(/\\{(\\w+)\\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)) };",
  "const window = { OOI18N };",
  "const kept = new Map(), before = new Map();",
  "function ooLive(el, render) { if (!el) return; if (render == null) { if (before.has(el)) el.textContent = before.get(el); kept.delete(el); before.delete(el); return; }",
  "  if (!before.has(el)) before.set(el, el.textContent); kept.set(el, [render, false]); el.textContent = String(render()); }",
  "function ooLiveHtml(el, render) { if (!el) return; kept.set(el, [render, true]); el.innerHTML = String(render()); }",
  "function switchTo(l) { lang = l; kept.forEach(([r, html], el) => { if (html) el.innerHTML = String(r()); else el.textContent = String(r()); }); }",
  "const esc = (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;');",
  "function ooSaidHtml(o, f) { return '<said>' + esc(o[f]) + '</said>'; }",
  "let timers = [];",
  "const setTimeout = (fn) => { timers.push(fn); };",
  "const els = {};",
  "const $ = (id) => els[id] || null;",
  "const document = { getElementById: $ };",
  "let apiReply = null;",
  "const api = async () => apiReply;",
  "const ensureOnline = async () => true;",
  "const toasts = []; const toast = (m) => toasts.push(m);",
  "let pollReply = null;",
  "const pollJobStatus = async (url, o) => { if (o && o.onProgress) o.onProgress({ detail: 'ke: +3', progress: true, done: 1, total: 2 }); return pollReply; };",
  "const _jobStillRunning = () => false;",
  "const _failMsg = (s) => s;",
  "let _gbQueries = [{ id: 1, query: 'q', language: 'fr', axis: 'a', relevances: {} }];",
  "let _partsStatusRender = null;",
  fnSource("enrichSources"), fnSource("discoverSources"), fnSource("discoverWorld"), fnSource("goldBuilderSave"),
  fnSource("_partsStatus"),
  "module.exports = { enrichSources, discoverSources, discoverWorld, goldBuilderSave, _partsStatus, switchTo, els, toasts,",
  "  setApi: (r) => { apiReply = r; }, setPoll: (r) => { pollReply = r; }, flush: () => { const t = timers; timers = []; t.forEach((f) => f()); },",
  "  current: () => _partsStatusRender };",
].join("\n");

const mod = { exports: {} };
new Function("module", "require", SRC)(mod, require);
const H = mod.exports;
const el = (id, text) => (H.els[id] = { id, textContent: text || "", innerHTML: "", value: "", hidden: true, disabled: false });

(async () => {
  // 1. enrichSources: the tally follows a switch while shown; the release puts the button's own label back.
  H.switchTo("en");
  const b1 = el("b1", "Enrich sources");
  H.setApi({ sources_updated: 3, tags_added: 1 });
  await H.enrichSources(b1);
  assert.strictEqual(b1.textContent, "Sources enriched: 3 · tags added: 1", "a labelled count, never «1 tags»");
  H.switchTo("fr");
  assert.strictEqual(b1.textContent, "FR[Sources enriched: {n} · tags added: {tags}]".replace("{n}", "3").replace("{tags}", "1"));
  H.flush();
  assert.strictEqual(b1.textContent, "Enrich sources", "the release gives the label back");
  assert.strictEqual(b1.disabled, false);

  // 2. discoverSources: the same, for the added count.
  H.switchTo("en");
  el("discover-cc").value = "ke";
  const b2 = el("b2", "Discover");
  H.setApi({ added: 4 });
  await H.discoverSources(b2);
  assert.strictEqual(b2.textContent, "Disabled sources added: 4. Review them in Settings → Sources.");
  H.switchTo("fr");
  assert.ok(b2.textContent.startsWith("FR[Disabled sources added: 4."), b2.textContent);
  H.flush();

  // 3. discoverWorld: the result line is HTML (a server reason may follow), names what the total counts, and
  //    follows a switch; the paused reason keeps the server's own words.
  H.switchTo("en");
  const out = el("discover-world-status");
  const b3 = el("b3", "Discover worldwide");
  H.setApi({ started: true });
  H.setPoll({ state: "done", result: { countries_done: 2, countries_requested: 5, added_this_run: 7, added_total: 40, paused_reason: "airplane <on>" } });
  await H.discoverWorld(b3);
  assert.strictEqual(out.innerHTML,
    "Countries done: 2/5 · new disabled sources: 7 · disabled sources added in total: 40 — <said>airplane &lt;on&gt;</said>");
  assert.strictEqual(b3.textContent, "Discover worldwide", "the button's label is back once the watch ends");
  H.switchTo("fr");
  assert.ok(out.innerHTML.startsWith("FR[Countries done: 2/5"), out.innerHTML);
  assert.ok(out.innerHTML.endsWith("<said>airplane &lt;on&gt;</said>"), "the server's reason is not re-translated");

  // 4. goldBuilderSave: the path and the per-language counts are data in <bdi translate="no">, escaped; the
  //    counts read «fr 12, de 4», never raw JSON; the line follows a switch.
  H.switchTo("en");
  el("gold-builder-path").value = "/tmp/gold.json";
  const cov = el("gold-builder-cov");
  H.setApi({ saved: "/tmp/<gold>.json", coverage: { graded_queries: 2, total_judgements: 16, by_language: { fr: 12, de: 4 } } });
  await H.goldBuilderSave(null);
  assert.strictEqual(cov.innerHTML,
    'Saved to <bdi translate="no">/tmp/&lt;gold&gt;.json</bdi>. Judgements: 16 (<bdi translate="no">fr 12, de 4</bdi>). '
    + "Point the IR-eval run below at this path.");
  assert.strictEqual(H.toasts.pop(), "Saved · graded queries: 2 · judgements: 16");
  H.switchTo("fr");
  assert.ok(cov.innerHTML.startsWith('FR[Saved to <bdi translate="no">/tmp/&lt;gold&gt;.json</bdi>.'), cov.innerHTML);

  // 5. _partsStatus keeps the render it drew, so a later line can extend it (the hand-over) and both follow a switch.
  H.switchTo("en");
  el("parts-bar"); const ps = el("parts-status");
  H._partsStatus(() => "Splitting the archive…");
  const prev = H.current();
  H._partsStatus(() => prev() + " +more");
  assert.strictEqual(ps.textContent, "Splitting the archive… +more");
  assert.strictEqual(H.els["parts-bar"].hidden, false);

  console.log("diag_group5_switch_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
