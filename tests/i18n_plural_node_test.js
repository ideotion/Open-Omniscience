// Plural forms in the shipped i18n.js, run as REAL code (2026-11-14).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// A translation may hold one form per CLDR category ("[one]...[few]...[other]..."). tf()
// picks the form with the browser's Intl.PluralRules for the app language, on `n`, else
// `count`, else the key's first placeholder; with no number (t(), the DOM walker, a var that
// is not a number) the form the language uses for 5, the plain plural of a whole count, since
// Russian [other] is the fraction form; a value without markers reads exactly as before.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "i18n.js"), "utf-8");

async function boot(lang, localeMap) {
  const target = new EventTarget();
  const document = {
    readyState: "complete",
    documentElement: {},
    body: null,
    getElementById: () => null,
    addEventListener: (type, fn) => target.addEventListener(type, fn),
    dispatchEvent: (e) => target.dispatchEvent(e),
  };
  const store = { "oo.lang": lang };
  const window = {};
  const ctx = {
    window, document, CustomEvent, setTimeout, console, Intl,
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } },
    fetch: async () => ({ ok: true, json: async () => localeMap }),
  };
  vm.runInNewContext(SRC, ctx);
  await window.OOI18N.ready;
  return window.OOI18N;
}

(async () => {
  const RU = "[one]{n} источник[few]{n} источника[many]{n} источников[other]{n} источника";
  const ru = await boot("ru", {
    _meta: { dir: "ltr" },
    "{n} sources": RU,
    "{done} of {total} sources": "[one]{done} из {total} источника[few]{done} из {total} источников"
      + "[many]{done} из {total} источников[other]{done} из {total} источника",
    "{n} selected": "Выбрано: {n}",
  });
  const want = { 1: "1 источник", 2: "2 источника", 4: "4 источника", 5: "5 источников",
    11: "11 источников", 12: "12 источников", 21: "21 источник", 22: "22 источника",
    111: "111 источников", 0: "0 источников" };
  for (const k of Object.keys(want)) {
    assert.strictEqual(ru.tf("{n} sources", { n: Number(k) }), want[k], "ru n=" + k);
  }
  assert.strictEqual(ru.tf("{n} sources", { n: 1.5 }), "1.5 источника", "a fraction takes [other]");
  assert.strictEqual(ru.tf("{n} sources", { n: "12 345" }), "12 345 источников",
    "a count already written with grouping spaces still chooses its form");
  assert.strictEqual(ru.tf("{n} sources", { n: "—" }), "— источников", "no number: the form for 5");
  assert.strictEqual(ru.tf("{n} sources"), "{n} источников", "no vars: the form for 5, placeholder kept");
  assert.strictEqual(ru.t("{n} sources"), "{n} источников", "t() has no number: the form for 5, never the markers");
  assert.strictEqual(ru.tf("{n} sources", { n: "\u2068+21\u2069" }), "\u2068+21\u2069 источник",
    "a count wrapped in bidi isolates for an RTL page still chooses its form");
  assert.strictEqual(ru.tf(ru.t("{n} sources"), { n: 21 }), "21 источник",
    "tf(t(KEY), vars): the no-number form t() returned is looked back up to its key and chooses");
  assert.strictEqual(ru.tf(ru.t("{done} of {total} sources"), { done: 1, total: 25 }), "1 из 25 источника",
    "...and the key's own first placeholder still drives it");
  assert.strictEqual(ru.tf("{done} of {total} sources", { done: 1, total: 25 }), "1 из 25 источника",
    "no n/count: the key's FIRST placeholder chooses ({done}=1 is [one], {total}=25 would be [many])");
  assert.strictEqual(ru.tf("{done} of {total} sources", { done: 5, total: 21 }), "5 из 21 источников");
  assert.strictEqual(ru.tf("{n} selected", { n: 5 }), "Выбрано: 5", "a plain value is unchanged");
  assert.strictEqual(ru.tf("Not in the file {n}", { n: 2 }), "Not in the file 2", "English fallback unchanged");

  const ar = await boot("ar", {
    _meta: { dir: "rtl" },
    "{n} sources": "[zero]{n} مصدر[one]مصدر واحد ({n})[two]مصدران ({n})[few]{n} مصادر[many]{n} مصدرًا[other]{n} مصدر",
  });
  const arWant = { 0: "0 مصدر", 1: "مصدر واحد (1)", 2: "مصدران (2)", 3: "3 مصادر", 10: "10 مصادر",
    11: "11 مصدرًا", 99: "99 مصدرًا", 100: "100 مصدر", 103: "103 مصادر" };
  for (const k of Object.keys(arWant)) {
    assert.strictEqual(ar.tf("{n} sources", { n: Number(k) }), arWant[k], "ar n=" + k);
  }
  assert.strictEqual(ar.t("{n} sources"), "{n} مصادر", "ar with no number: the form for 5 (the plural)");
  assert.strictEqual(ar.tf("{n} sources", { n: "" }), " مصادر", "an empty count is no number, never 0");
  assert.strictEqual(ar.tf("{n} sources", { n: "\u0661" }), "\u0661 مصادر", "only ASCII digits are a number, as in the terminal");

  // Two keys whose no-number forms agree but whose other forms differ: tf(t(KEY)) cannot tell
  // which key the text came from, so it chooses nothing rather than the wrong key's form.
  const amb = await boot("ar", {
    "{n} article": "[one]مقالة واحدة[few]{n} مقالات[other]{n} مقالة",
    "{n} article(s)": "[one]مقال واحد[few]{n} مقالات[other]{n} مقال",
  });
  assert.strictEqual(amb.tf(amb.t("{n} article"), { n: 1 }), "1 مقالات", "an ambiguous no-number form is looked up to neither key");
  assert.strictEqual(amb.tf("{n} article", { n: 1 }), "مقالة واحدة", "the key itself still chooses");

  // A value that merely starts with a bracket is not a plural value.
  const en = await boot("fr", { "[beta] {n} items": "[bêta] {n} éléments" });
  assert.strictEqual(en.tf("[beta] {n} items", { n: 3 }), "[bêta] 3 éléments");

  console.log("all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
