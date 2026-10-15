/**
 * Behavioural node test for the empty-ring caveat (R131, the T5 layout PR and its follow-up).
 *
 * showRingMap is EXTRACTED FROM THE SHIPPED SOURCE (a re-typed copy would pass while the real code was
 * broken) and run against payloads of the shapes the endpoint really sends, with the REAL locale files and the
 * REAL tf() from i18n.js. What is asserted is what the reader sees: the host's rendered HTML.
 *
 * The first version of this feature put the caveat on a path an empty ring never reaches (an empty ring draws
 * no map, so ooMap is never called); a test that only greps the source passed anyway. This one fails when the
 * empty state stops carrying the caveat.
 *
 * Run by tests/test_ring_caveat_i18n.py, which hands over the two sentences the endpoint sends in RING_COUNTRY_CAVEAT
 * and RING_COUNTRY_METHOD (the test refuses to start without them, so run it through that wrapper).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const read = (name) => fs.readFileSync(path.join(STATIC, name), "utf-8");
const INS = read("app-insights.js");
const I18N = read("i18n.js");
// Every shipped locale, read from the directory: a 13th locale is rendered without anyone editing this list.
const CODES = fs.readdirSync(path.join(STATIC, "locales")).filter((f) => f.endsWith(".json"))
  .map((f) => f.slice(0, -5)).sort();
// The caveat of a ring that has mention rows: handed over by tests/test_ring_caveat_i18n.py from
// src/analytics/queries.py (_RING_COUNTRY_CAVEAT), so the fixtures carry the sentence the endpoint really sends.
const STANDARD = process.env.RING_COUNTRY_CAVEAT || "";
const METHOD = process.env.RING_COUNTRY_METHOD || "";
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));

if (!STANDARD || !METHOD) { console.error("FAIL: RING_COUNTRY_CAVEAT / RING_COUNTRY_METHOD is not set (run tests/test_ring_caveat_i18n.py)"); process.exit(1); }
let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) {
  return Promise.resolve().then(fn).then(() => { passed += 1; console.log("ok  - " + name); });
}

function extract(name, decl, src) {
  const head = decl || ("function " + name + "(");
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  let p = 0, i = -1;
  for (let j = src.indexOf("(", at); j < src.length; j++) {
    if (src[j] === "(") p++;
    else if (src[j] === ")") { p--; if (p === 0) { i = src.indexOf("{", j); break; } }
  }
  assert(i !== -1, "could not find the body of " + head);
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

const SHOW = extract("showRingMap", "async function showRingMap(", INS);
const TF_SRC = extract("tf", "function tf(", I18N);
const ESC = (s) => (s == null ? "" : String(s).replace(/[&<>"']/g,
  (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", "\"": "&quot;", "'": "&#39;"}[c])));

// Run the real showRingMap for one payload in one locale; returns what the reader sees.
async function render(payload, code, opts) {
  opts = opts || {};
  const map = code === "en" ? {} : LOCALE(code);
  const tf = new Function("map", TF_SRC + "; return tf;")(map);
  const t = (s) => (map[s] == null ? s : map[s]);
  const els = { "sg-ringmap": { innerHTML: "" }, "sg-ringmap-detail": { innerHTML: "" } };
  const drawn = [];
  const run = new Function("window", "OOI18N", "$", "esc", "api", "ooRegionName", "ooMap", "ooLabelHtml", "ooLangCell",
    "ooCountryCell", "ringDumbbellSvg", "_conceptDrillCountry",
    "let _ringMapLast = null; let _ringSeq = 0; let _ringCleared = false; const _ringLangIndex = {};\n" + SHOW + "\nreturn showRingMap;");
  const fn = run({ OOI18N: opts.noTf ? { t } : { t, tf } }, opts.noTf ? { t } : { t, tf }, (id) => els[id] || null, ESC,
    async () => payload, (c) => c, async (host, o) => { drawn.push(o); }, (a, b) => a + b, (x) => x, (x) => x,
    () => "", () => {});
  await fn("news-media", null);
  return { host: els["sg-ringmap"].innerHTML, detail: els["sg-ringmap-detail"].innerHTML, drawn };
}

const REPAINT = extract("repaintRingMapFromCache", "function repaintRingMapFromCache(", INS);

// A reader's session: one set of elements and one _ringMapLast, so a language switch can repaint what is on screen.
function session(code, apiFn, ooMapFn) {
  const map = {};
  const load = (c) => { Object.keys(map).forEach((k) => delete map[k]); if (c !== "en") Object.assign(map, LOCALE(c)); };
  load(code);
  const tf = new Function("map", TF_SRC + "; return tf;")(map);
  const t = (s) => (map[s] == null ? s : map[s]);
  const els = { "sg-ringmap": { innerHTML: "", querySelector: () => null }, "sg-ringmap-detail": { innerHTML: "" } };
  const run = new Function("window", "OOI18N", "$", "esc", "api", "ooRegionName", "ooMap", "ooLabelHtml", "ooLangCell",
    "ooCountryCell", "ringDumbbellSvg", "_conceptDrillCountry",
    "let _ringMapLast = null; let _ringSeq = 0; let _ringCleared = false; const _ringLangIndex = {};\n" + SHOW + "\n" + REPAINT + "\nreturn { showRingMap, repaintRingMapFromCache };");
  const fns = run({ OOI18N: { t, tf } }, { t, tf }, (id) => els[id] || null, ESC, apiFn, (c) => c, ooMapFn || (async () => {}),
    (a, b) => a + b, (x) => x, (x) => x, () => "", () => {});
  return { show: (ring) => fns.showRingMap(ring, null), repaint: fns.repaintRingMapFromCache,
           switchTo: (c) => load(c), host: () => els["sg-ringmap"].innerHTML };
}

const HIDDEN = {
  found: true, ring_id: "news-media", countries: [], n_keywords: 0, languages: [], n_countries: 0, countries_listed: 0,
  truncated: false,
  caveat: "Every keyword of this group in your corpus (7) is hidden by the stoplist or your own exclusions, so there is nothing to count.",
  caveat_i18n: "Every keyword of this group in your corpus ({n}) is hidden by the stoplist or your own exclusions, so there is nothing to count.",
  caveat_vars: { n: 7 },
};
const NONE = {
  found: true, ring_id: "news-media", countries: [], n_keywords: 0, languages: [], n_countries: 0, countries_listed: 0,
  truncated: false,
  caveat: "No indexed keywords in this group yet for your corpus.",
  caveat_i18n: "No indexed keywords in this group yet for your corpus.", caveat_vars: {},
};
// The populated shapes carry what the endpoint always sends: label, method and the standard caveat.
const UNLOCATED_ONLY = {
  found: true, ring_id: "news-media", label: "News media", n_keywords: 3, languages: ["en"], n_countries: 0,
  countries_listed: 0, truncated: false, countries: [{ country: null, articles: 4, mentions: 9 }],
  method: METHOD, caveat: STANDARD,
};
const LOCATED = {
  found: true, ring_id: "news-media", label: "News media", n_keywords: 3, languages: ["en"], n_countries: 1,
  countries_listed: 1, truncated: false, countries: [{ country: "FR", articles: 4, mentions: 9 }],
  method: METHOD, caveat: STANDARD,
};
// Keywords are indexed but none has a mention row (e.g. the day window is empty): the endpoint answers with the
// standard caveat and no bucket at all. The sentence names a "Not mapped" bucket that is not on screen then; it stays
// shown because it is still true of the figures (documented, harmless; the unlocated-only case above is the one that
// has the bucket).
const NO_MENTIONS = {
  found: true, ring_id: "news-media", label: "News media", n_keywords: 3, languages: ["en"], n_countries: 0,
  countries_listed: 0, truncated: false, countries: [], method: METHOD, caveat: STANDARD,
};

(async () => {
  for (const code of CODES) {
    await test(code + ": an empty ring whose keywords are all hidden shows the translated sentence with the count, not 'no located sources' alone", async () => {
      const map = code === "en" ? {} : LOCALE(code);
      const expected = (map[HIDDEN.caveat_i18n] || HIDDEN.caveat_i18n).replace("{n}", "7");
      const r = await render(HIDDEN, code);
      assert(r.host.includes(ESC(expected)), code + ": the rendered empty state lacks " + expected + " -> " + r.host);
      assert(!r.host.includes("{n}"), code + ": the placeholder reached the screen");
      assert(r.drawn.length === 0, "an empty ring must not draw a map");
      if (code !== "en") assert(map[HIDDEN.caveat_i18n] && map[HIDDEN.caveat_i18n] !== HIDDEN.caveat_i18n, code + ": the template is not translated");
    });
    await test(code + ": an empty ring with nothing indexed yet shows its own translated sentence", async () => {
      const map = code === "en" ? {} : LOCALE(code);
      const expected = map[NONE.caveat_i18n] || NONE.caveat_i18n;
      const r = await render(NONE, code);
      assert(r.host.includes(ESC(expected)), code + ": " + r.host);
    });
    await test(code + ": an unlocated-only payload shows the translated standard caveat beside the Not mapped bucket (decided: yes)", async () => {
      // The state draws no map (nothing is located), but it does show counts the caveat governs: 'Not mapped'
      // is exactly what the standard sentence explains, so informed consent keeps it visible here too.
      const map = code === "en" ? {} : LOCALE(code);
      const expected = map[STANDARD] || STANDARD;
      if (code !== "en") assert(map[STANDARD] && map[STANDARD] !== STANDARD, code + ": the standard caveat is not translated");
      const r = await render(UNLOCATED_ONLY, code);
      assert(r.drawn.length === 0, "nothing is located, so no map is drawn");
      assert(r.host.includes(ESC(expected)), code + ": the standard caveat is missing from the unlocated-only state: " + r.host);
      assert(r.detail.length > 0, code + ": the Not mapped bucket must stay reachable");
    });
    await test(code + ": a ring with keywords but no mention rows shows the same standard caveat (no bucket to explain, documented)", async () => {
      const map = code === "en" ? {} : LOCALE(code);
      const r = await render(NO_MENTIONS, code);
      assert(r.drawn.length === 0 && r.host.includes(ESC(map[STANDARD] || STANDARD)), code + ": " + r.host);
    });
    await test(code + ": a located payload hands the translated caveat to the map", async () => {
      const map = code === "en" ? {} : LOCALE(code);
      const r = await render(LOCATED, code);
      assert(r.drawn.length === 1 && r.drawn[0].caveat === (map[STANDARD] || STANDARD), code + ": " + JSON.stringify(r.drawn));
    });
  }
  await test("a language switch repaints the empty state and its caveat in the new language", async () => {
    const sess = session("en", async () => HIDDEN);
    await sess.show("news-media");
    assert(sess.host().includes("hidden by the stoplist"), sess.host());
    sess.switchTo("fr"); sess.repaint();
    await new Promise((r) => setImmediate(r));
    const expected = LOCALE("fr")[HIDDEN.caveat_i18n].replace("{n}", "7");
    assert(sess.host().includes(ESC(expected)), "the empty state stayed in the previous language: " + sess.host());
  });
  await test("a language switch never resurrects a group that is no longer on screen", async () => {
    let answer = HIDDEN;
    const sess = session("en", async () => answer);
    await sess.show("news-media");
    answer = { found: false };
    await sess.show("another-group");
    const before = sess.host();
    assert(before.includes("No cross-country coverage"), before);
    sess.switchTo("fr"); sess.repaint();
    await new Promise((r) => setImmediate(r));
    assert(!sess.host().includes("hidden") && sess.host() === before, "the previous group came back: " + sess.host());
  });
  await test("a draw that failed is not redrawn by a language switch (the host shows the error, not the payload)", async () => {
    let attempts = 0;
    const sess = session("en", async () => LOCATED, async () => { attempts += 1; throw new Error("map failed"); });
    await sess.show("news-media");
    const before = sess.host();
    assert(before.includes("map failed") && attempts === 1, before);
    sess.switchTo("fr"); sess.repaint();
    await new Promise((r) => setImmediate(r));
    assert(sess.host() === before, "the failed draw was redrawn: " + sess.host());
    assert(attempts === 1, "the failed draw was attempted again (" + attempts + " draws)");
  });
  await test("an answer that arrives after a newer pick is dropped, and a language switch redraws the newer group", async () => {
    const waiting = {};
    const NEWER = Object.assign({}, LOCATED, { ring_id: "second", label: "Second group" });
    const sess = session("en", (url) => new Promise((resolve) => { waiting[url.split("ring_id=")[1]] = resolve; }),
      async (host, o) => { host.innerHTML = "drawn:" + o.aria; });
    const first = sess.show("first"), second = sess.show("second");
    waiting.second(NEWER); await second;
    assert(sess.host().includes("drawn:Second group"), "the newer pick did not draw: " + sess.host());
    const shown = sess.host();
    waiting.first(Object.assign({}, LOCATED, { ring_id: "first", label: "First group" })); await first;
    assert(sess.host() === shown, "the slow answer of the older pick painted over the newer one: " + sess.host());
    sess.switchTo("fr"); sess.repaint();
    await new Promise((r) => setImmediate(r));
    assert(!sess.host().includes("First group"), "a language switch redrew the older pick: " + sess.host());
  });
  await test("a late ERROR of an older pick does not replace the newer group either", async () => {
    const waiting = {};
    const sess = session("en", (url) => new Promise((resolve, reject) => { waiting[url.split("ring_id=")[1]] = { resolve, reject }; }),
      async (host, o) => { host.innerHTML = "drawn:" + o.aria; });
    const first = sess.show("first"), second = sess.show("second");
    waiting.second.resolve(Object.assign({}, LOCATED, { ring_id: "second", label: "Second group" })); await second;
    waiting.first.reject(new Error("slow failure")); await first;
    assert(sess.host().includes("drawn:Second group") && !sess.host().includes("slow failure"), "a late error replaced the newer group: " + sess.host());
    sess.switchTo("fr"); sess.repaint();
    await new Promise((r) => setImmediate(r));
    assert(sess.host().includes("drawn:Second group"), "the newer group stopped being redrawable after the late error: " + sess.host());
  });
  // ooMap awaits its own geometry loads: a draw that is still inside it when a newer pick draws (or the picker is
  // cleared) must not leave its map in the host. The stub holds every ooMap call until the test releases it.
  const held = () => {
    const calls = [];
    return { calls, ooMap: (host, o) => new Promise((resolve, reject) => {
      calls.push({ aria: o.aria, release: () => { host.innerHTML = "drawn:" + o.aria; resolve(); }, fail: () => reject(new Error("late failure")) });
    }) };
  };
  const tick = () => new Promise((r) => setImmediate(r));
  const GA = Object.assign({}, LOCATED, { ring_id: "a", label: "Group A" });
  const GB = Object.assign({}, LOCATED, { ring_id: "b", label: "Group B" });
  await test("an older pick still inside ooMap when a newer pick draws leaves the newer group in the host", async () => {
    const h = held();
    const sess = session("en", (url) => Promise.resolve(url.endsWith("=a") ? GA : GB), h.ooMap);
    const a = sess.show("a"); await tick();
    const b = sess.show("b"); await tick();
    assert(h.calls.length === 2, "both picks should be inside ooMap: " + h.calls.length);
    h.calls[1].release(); await b;
    h.calls[0].release(); await tick();
    // the older draw's stale tail puts the newer group back; release that redraw too
    for (let i = 2; i < h.calls.length; i++) h.calls[i].release();
    await a;
    assert(sess.host() === "drawn:Group B — 1 countries", "the older pick's map was left in the host: " + sess.host());
    sess.switchTo("fr"); sess.repaint(); await tick();
    for (let i = 3; i < h.calls.length; i++) h.calls[i].release();
    await tick();
    assert(sess.host().includes("Group B"), "the cache stopped holding the newer group: " + sess.host());
  });
  await test("a picker cleared while a draw is inside ooMap ends with an empty host", async () => {
    const h = held();
    const sess = session("en", async () => GA, h.ooMap);
    const a = sess.show("a"); await tick();
    await sess.show("");
    h.calls[0].release(); await a;
    assert(sess.host() === "", "the cleared picker was painted by a draw that finished late: " + sess.host());
  });
  await test("a language-switch repaint of an older group that fails late does not replace the newer group", async () => {
    const h = held();
    const sess = session("en", (url) => Promise.resolve(url.endsWith("=a") ? GA : GB), h.ooMap);
    const first = sess.show("a"); await tick();
    h.calls[0].release(); await first;
    sess.switchTo("fr"); sess.repaint(); await tick();
    const b = sess.show("b"); await tick();
    h.calls[2].release(); await b;
    h.calls[1].fail(); await tick();
    assert(sess.host().includes("Group B") && !sess.host().includes("late failure"), "a late error of the repaint replaced the newer group: " + sess.host());
  });
  await test("a language-switch repaint still inside ooMap when another group is picked does not stay on screen", async () => {
    const h = held();
    const sess = session("en", (url) => Promise.resolve(url.endsWith("=a") ? GA : GB), h.ooMap);
    const first = sess.show("a"); await tick();
    h.calls[0].release(); await first;
    sess.switchTo("fr"); sess.repaint(); await tick();
    assert(h.calls.length === 2, "the repaint should be inside ooMap: " + h.calls.length);
    const b = sess.show("b"); await tick();
    h.calls[2].release(); await b;
    h.calls[1].release(); await tick();
    for (let i = 3; i < h.calls.length; i++) h.calls[i].release();
    await tick();
    assert(sess.host().includes("Group B") && !sess.host().includes("Group A"), "the repaint of the older group stayed on screen: " + sess.host());
  });
  await test("a late answer after the picker was cleared draws nothing", async () => {
    const waiting = {};
    const sess = session("en", (url) => new Promise((resolve) => { waiting.r = resolve; }),
      async (host, o) => { host.innerHTML = "drawn:" + o.aria; });
    const pending = sess.show("first");
    await sess.show("");
    waiting.r(LOCATED); await pending;
    assert(sess.host() === "", "a cleared picker was painted by a late answer: " + sess.host());
  });
  await test("the 'all hidden' and the 'nothing indexed' states read differently (R111 T2)", async () => {
    const a = (await render(HIDDEN, "en")).host, b = (await render(NONE, "en")).host;
    assert(a.includes("hidden by the stoplist") && !b.includes("hidden by the stoplist"), a + " | " + b);
    assert(b.includes("No indexed keywords"), b);
  });
  await test("a missing tf falls back to the plain sentence, never a literal {n}", async () => {
    const r = await render(HIDDEN, "fr", { noTf: true });
    assert(r.host.includes("(7)") && !r.host.includes("{n}"), r.host);
  });
  console.log(passed + " passed");
})().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
