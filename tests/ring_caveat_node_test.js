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
 * Run by tests/test_ring_caveat_i18n.py (and standalone: `node tests/ring_caveat_node_test.js`).
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
const CODES = ["ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"];
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));

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
    "let _ringMapLast = null; const _ringLangIndex = {};\n" + SHOW + "\nreturn showRingMap;");
  const fn = run({ OOI18N: opts.noTf ? { t } : { t, tf } }, opts.noTf ? { t } : { t, tf }, (id) => els[id] || null, ESC,
    async () => payload, (c) => c, async (host, o) => { drawn.push(o); }, (a, b) => a + b, (x) => x, (x) => x,
    () => "", () => {});
  await fn("news-media", null);
  return { host: els["sg-ringmap"].innerHTML, detail: els["sg-ringmap-detail"].innerHTML, drawn };
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
const STANDARD = "Coverage by producing-source country, never a credibility ranking or score. Articles whose source has no country are counted under 'Not mapped'.";
const UNLOCATED_ONLY = {
  found: true, ring_id: "news-media", n_keywords: 3, languages: ["en"], n_countries: 0, countries_listed: 0, truncated: false,
  countries: [{ country: null, articles: 4, mentions: 9 }], caveat: STANDARD,
};
const LOCATED = {
  found: true, ring_id: "news-media", n_keywords: 3, languages: ["en"], n_countries: 1, countries_listed: 1, truncated: false,
  countries: [{ country: "FR", articles: 4, mentions: 9 }], caveat: STANDARD,
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
  }
  await test("the 'all hidden' and the 'nothing indexed' states read differently (R111 T2)", async () => {
    const a = (await render(HIDDEN, "en")).host, b = (await render(NONE, "en")).host;
    assert(a.includes("hidden by the stoplist") && !b.includes("hidden by the stoplist"), a + " | " + b);
    assert(b.includes("No indexed keywords"), b);
  });
  await test("a missing tf falls back to the plain sentence, never a literal {n}", async () => {
    const r = await render(HIDDEN, "fr", { noTf: true });
    assert(r.host.includes("(7)") && !r.host.includes("{n}"), r.host);
  });
  await test("an unlocated-only payload shows the standard caveat beside the Not mapped bucket (decided: yes)", async () => {
    // The state draws no map (nothing is located), but it does show counts the caveat governs: 'Not mapped'
    // is exactly what the standard sentence explains, so informed consent keeps it visible here too.
    const r = await render(UNLOCATED_ONLY, "en");
    assert(r.host.includes("No located sources"), r.host);
    assert(r.host.includes(ESC(STANDARD)), "the standard caveat is missing from the unlocated-only state: " + r.host);
    assert(r.detail.includes("Not mapped"), "the Not mapped bucket must stay reachable: " + r.detail);
  });
  await test("a located payload hands the caveat to the map", async () => {
    const r = await render(LOCATED, "en");
    assert(r.drawn.length === 1 && r.drawn[0].caveat === STANDARD, JSON.stringify(r.drawn));
  });
  console.log(passed + " passed");
})().catch((e) => { console.error("FAIL: " + (e && e.stack || e)); process.exit(1); });
