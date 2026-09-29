// The version reader's «Add to corpus» (R52), run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The WHOLE shipped component is loaded (src/static/ooversions.js) and mounted on a stand-in
// host, with the SPA's api() answering from fixtures, so what is checked is the renderer and
// the delegated listener the page really runs. What must not happen is mostly quiet:
//
//   * a law reader offering an add nothing implements (the button exists only where the
//     payload carries `corpus_add`);
//   * a version whose text was never stored offered as addable, or POSTed anyway;
//   * a version the corpus already holds offered again, instead of saying so with the
//     article one click away in the local reader;
//   * a second POST while the first is in flight, or after the add answered;
//   * an outcome that does not say which end of the comparison it is about, or that is
//     drawn twice when both ends are the same version;
//   * a refusal shown as the server's code where there are words for it, or unescaped;
//   * an answer for the page the reader USED to show landing on the page it shows now;
//   * a language switch that re-requests, or drops what the add answered.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "ooversions.js"), "utf8");

// --- a stand-in page -------------------------------------------------------------------
const docListeners = {};
const document = {
  readyState: "complete",
  head: { appendChild() {} },
  getElementById() { return null; },
  createElement() { return {}; },
  querySelectorAll() { return []; },
  addEventListener(type, fn) { (docListeners[type] = docListeners[type] || []).push(fn); },
};
let lang = "en";
const window = {
  OOI18N: {
    t: (s) => (lang === "fr" ? "«" + s + "»" : s),
    tf: (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => (v[k] == null ? "" : v[k])),
  },
};

function deferred() {
  let resolve, reject;
  const p = new Promise((a, b) => { resolve = a; reject = b; });
  return { p, resolve, reject };
}

const calls = [];
const payloads = {};
let pendingAdd = null;
window.api = (url, opts) => {
  calls.push([url, opts || null]);
  if (opts && opts.method === "POST") { pendingAdd = deferred(); return pendingAdd.p; }
  if (url.includes("/compare?")) {
    return Promise.resolve({ method: "identical", rows: [], parts: null, parts_reason: null, changed: 0, added: 0, removed: 0 });
  }
  const base = url.replace(/\/versions$/, "");
  assert.ok(payloads[base], "no fixture for " + url);
  return Promise.resolve(JSON.parse(JSON.stringify(payloads[base])));
};

const ctx = vm.createContext({
  window, document, console, setTimeout,
  location: { origin: "http://127.0.0.1:8000", assign() {} },
  fetch: () => { throw new Error("fetch used although the SPA's api() is present"); },
});
vm.runInContext(SRC, ctx, { filename: "ooversions.js" });
const mount = window.ooVersionReader;
assert.strictEqual(typeof mount, "function", "window.ooVersionReader is the component");

function makeHost() {
  const ls = {};
  return {
    innerHTML: "", isConnected: true,
    classList: { add() {} }, setAttribute() {},
    addEventListener(type, fn) { (ls[type] = ls[type] || []).push(fn); },
    contains() { return true; },
    fire(type, ev) { (ls[type] || []).forEach((fn) => fn(ev)); },
  };
}
function clickAdd(host, id) {
  const el = { hasAttribute: (a) => a === "data-ov-add", getAttribute: (a) => (a === "data-ov-add" ? id : null) };
  host.fire("click", { target: { closest: () => el } });
}
function pick(host, which, id) {
  host.fire("change", { target: { getAttribute: (a) => (a === "data-ov" ? which : null), value: id } });
}
const flush = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };
function button(html, id) {
  const m = html.match(new RegExp(`<button[^>]*data-ov-add="${id}"[^>]*>`));
  return m ? m[0] : null;
}
const outcomes = (html) => html.match(/<p class="ov-added[^"]*">[\s\S]*?<\/p>/g) || [];
const posts = () => calls.filter(([, o]) => o && o.method === "POST");

function version(id, extra) {
  return Object.assign({
    id, label: "a revision", observed_at: null, valid_from: "2025-05-01 09:30", valid_to: null,
    partial: false, dating: "edit", has_text: true, delta_bytes: null, local_url: null,
    external_url: null, summary: null,
  }, extra || {});
}
function wiki(base, versions, extra) {
  payloads[base] = Object.assign({
    kind: "wiki", id: Number(base.split("/").pop()), title: "Saltpetre works", language: "en",
    jurisdiction: null, versions, total: versions.length, permalink: null, identifier: null,
    licence: { name: "CC BY-SA 4.0", url: "https://creativecommons.org/licenses/by-sa/4.0/", id: "cc-by-sa-4.0" },
    provenance: null, languages: [], parts_name: "sections", stores: ["lane", "tracker"],
    method: "The method.", caveat: "The caveat.", corpus_add: { articles: {} },
  }, extra || {});
}
const THREE = [
  version("l9", { valid_from: "2025-05-22 09:30" }),
  version("t2", { valid_from: "2025-05-02 09:30", valid_to: "2025-05-22 09:30" }),
  version("t3", { valid_from: "2025-05-01 09:30", valid_to: "2025-05-02 09:30", has_text: false }),
];

(async () => {
  // 1. A law payload carries no `corpus_add`: nothing is offered.
  wiki("/api/law/documents/4", THREE);
  payloads["/api/law/documents/4"].kind = "law";
  delete payloads["/api/law/documents/4"].corpus_add;
  const law = makeHost();
  mount(law, "/api/law/documents/4", {});
  await flush();
  assert.ok(law.innerHTML.includes('data-ov="from"'), "the law reader drew its pickers");
  assert.ok(!law.innerHTML.includes("data-ov-add"), "no add where the payload offers none");

  // 2. A Wikipedia page: one button per end, enabled where the text is held, titled.
  wiki("/api/wiki/pages/5", THREE);
  const host = makeHost();
  const reader = mount(host, "/api/wiki/pages/5", {});
  await flush();
  let to = button(host.innerHTML, "l9"), from = button(host.innerHTML, "t2");
  assert.ok(to && from, "a button at each end (newest with text against the one before it)");
  assert.ok(!to.includes(" disabled") && !from.includes(" disabled"), "both ends are addable");
  assert.ok(to.includes('title="Adds this exact version to your corpus as its own article."'), to);
  assert.strictEqual(button(host.innerHTML, "t3"), null, "only the two ends carry a button");
  assert.deepStrictEqual(outcomes(host.innerHTML), [], "no outcome before any add");

  // 3. A version whose text was not stored: the button is off and says why; a click POSTs nothing.
  pick(host, "from", "t3");
  await flush();
  const bare = button(host.innerHTML, "t3");
  assert.ok(bare && bare.includes(" disabled"), "a version without text cannot be added");
  assert.ok(bare.includes("This version&#39;s text was not stored on this machine, so it cannot be added."), bare);
  clickAdd(host, "t3");
  await flush();
  assert.strictEqual(posts().length, 0, "nothing POSTed for a version without text");
  pick(host, "from", "t2");
  await flush();

  // 4. Add the newest: busy while in flight (no second POST), then the outcome, linked.
  clickAdd(host, "l9");
  await flush();
  assert.strictEqual(posts().length, 1);
  // Compared as JSON: the init object was made inside the component's own realm.
  assert.strictEqual(JSON.stringify(posts()[0]), JSON.stringify(["/api/wiki/pages/5/versions/l9/add-to-corpus", { method: "POST" }]));
  assert.ok(button(host.innerHTML, "l9").includes(" disabled"), "off while the add is in flight");
  clickAdd(host, "l9");
  await flush();
  assert.strictEqual(posts().length, 1, "a second click during the add POSTs nothing");
  pendingAdd.resolve({ status: "created", article_id: 501, title: "Saltpetre works", revid: 21, version: "l9", store: "lane" });
  await flush();
  let lines = outcomes(host.innerHTML);
  assert.strictEqual(lines.length, 1, lines.join("\n"));
  assert.ok(lines[0].startsWith('<p class="ov-added"><b>To</b> · Added to your corpus as its own article.'), lines[0]);
  assert.ok(lines[0].includes('<a href="/api/articles/501/view" target="_blank" rel="noopener">Open it in the reader</a>'), lines[0]);
  assert.ok(button(host.innerHTML, "l9").includes(" disabled"), "an added version is not offered again");
  assert.ok(button(host.innerHTML, "l9").includes('title="Added to your corpus as its own article."'), "its hover says why it is off");
  clickAdd(host, "l9");
  await flush();
  assert.strictEqual(posts().length, 1, "no POST after the add answered");

  // 5. A language switch repaints from what the add answered, and requests nothing.
  const before = calls.length;
  lang = "fr";
  docListeners["oo:langchange"].forEach((fn) => fn());
  lines = outcomes(host.innerHTML);
  assert.ok(lines[0].includes("<b>«To»</b> · «Added to your corpus as its own article.»"), lines[0]);
  assert.ok(lines[0].includes("«Open it in the reader»"), lines[0]);
  assert.strictEqual(calls.length, before, "a language switch requests nothing");
  lang = "en";
  docListeners["oo:langchange"].forEach((fn) => fn());

  // 6. The outcome follows the version, not the end: picked at the other end, it moves there.
  pick(host, "to", "t2");
  pick(host, "from", "l9");
  await flush();
  lines = outcomes(host.innerHTML);
  assert.ok(lines.length === 1 && lines[0].startsWith('<p class="ov-added"><b>From</b> · Added'), lines.join("\n"));
  // Both ends on the same version: one line, not two.
  pick(host, "to", "l9");
  await flush();
  assert.strictEqual(outcomes(host.innerHTML).length, 1, "one line when both ends are one version");

  // 7. What the corpus already holds is said, never offered, with the article one click away.
  wiki("/api/wiki/pages/6", THREE, { corpus_add: { articles: { t2: 77 } } });
  const held = makeHost();
  mount(held, "/api/wiki/pages/6", {});
  await flush();
  assert.ok(button(held.innerHTML, "t2").includes(" disabled"), "already in the corpus: not offered");
  assert.ok(button(held.innerHTML, "t2").includes('title="This version is already in your corpus."'), button(held.innerHTML, "t2"));
  lines = outcomes(held.innerHTML);
  assert.strictEqual(lines.length, 1, lines.join("\n"));
  assert.ok(lines[0].startsWith('<p class="ov-added"><b>From</b> · This version is already in your corpus.'), lines[0]);
  assert.ok(lines[0].includes('href="/api/articles/77/view"'), lines[0]);

  // 8. Refusals in words where there are words, the server's message (escaped) otherwise,
  //    and the button offered again, since a refused add stored nothing.
  const refusing = makeHost();
  mount(refusing, "/api/wiki/pages/5", {});
  await flush();
  clickAdd(refusing, "l9");
  await flush();
  pendingAdd.reject(Object.assign(new Error("404 Not Found"), { detail: "not-held" }));
  await flush();
  lines = outcomes(refusing.innerHTML);
  assert.ok(lines[0] === '<p class="ov-added ov-muted"><b>To</b> · This version is no longer held on this machine.</p>', lines[0]);
  assert.ok(!button(refusing.innerHTML, "l9").includes(" disabled"), "a refused add can be tried again");
  clickAdd(refusing, "l9");
  await flush();
  pendingAdd.reject(Object.assign(new Error("<b>boom</b>"), { detail: "lane-exploded" }));
  await flush();
  lines = outcomes(refusing.innerHTML);
  assert.ok(lines[0].includes("&lt;b&gt;boom&lt;/b&gt;") && !lines[0].includes("<b>boom</b>"), lines[0]);

  // 9. An answer for the page the reader used to show never lands on the page it shows now.
  const moving = makeHost();
  const r2 = mount(moving, "/api/wiki/pages/5", {});
  await flush();
  clickAdd(moving, "l9");
  await flush();
  const late = pendingAdd;
  wiki("/api/wiki/pages/8", THREE);
  r2.load("/api/wiki/pages/8");
  await flush();
  late.resolve({ status: "created", article_id: 999 });
  await flush();
  // Repainted from the state it holds now: the old page's answer is not in it.
  docListeners["oo:langchange"].forEach((fn) => fn());
  assert.deepStrictEqual(outcomes(moving.innerHTML), [], "the old page's answer is dropped");
  assert.ok(!button(moving.innerHTML, "l9").includes(" disabled"), "the new page starts with nothing in flight");

  // 10. A page with one version: its button, and an outcome with no end to name.
  wiki("/api/wiki/pages/9", [version("t7")]);
  const single = makeHost();
  mount(single, "/api/wiki/pages/9", {});
  await flush();
  assert.ok(single.innerHTML.includes('<div class="ov-pick"><button type="button" class="secondary tiny" data-ov-add="t7"'), single.innerHTML);
  clickAdd(single, "t7");
  await flush();
  pendingAdd.resolve({ status: "skipped-empty-after-strip", revid: 7 });
  await flush();
  lines = outcomes(single.innerHTML);
  assert.deepStrictEqual(lines, ['<p class="ov-added">Nothing to add: no text is left once the wiki markup is removed.</p>'], "no link where no article was named");
  assert.ok(button(single.innerHTML, "t7").includes(" disabled"), "an add that found nothing to add is not offered again");

  assert.ok(reader && typeof reader.load === "function");
  console.log("all checks passed");
})().catch((e) => { console.error(e); process.exit(1); });
