/**
 * Behavioural node test for batch B11 of the 2026-09-26 delegated click-through: byte
 * sizes written for the reader's language (P8), and two findings on the export panel --
 * its Licences lines (J-licences) and its Elapsed value (J-elapsed).
 *
 * Every function under test is EXTRACTED FROM THE SHIPPED SOURCE by name, and the
 * translations come from the REAL locale files through the REAL t()/tf() of
 * src/static/i18n.js, so "the unit is translated" means translated by what ships.
 *
 * Run by tests/test_clickthrough_b11_fixes.py (and standalone:
 * `node tests/clickthrough_b11_node_test.js`).
 *
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const APP = require("./app_source.js").appJs();
const I18N = fs.readFileSync(path.join(STATIC, "i18n.js"), "utf-8");
const TM = require("./app_source.js").pageSource("taskmanager.html");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));
const LANGS = ["ar", "bn", "de", "en", "es", "fr", "hi", "id", "ja", "pt", "ru", "zh"];

let passed = 0;
function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }
function test(name, fn) { fn(); passed += 1; console.log("ok  - " + name); }

// Same balanced-brace extraction every node suite here uses (duplicated per convention).
function extract(name, src) {
  const head = "function " + name + "(";
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
function extractConst(name, src) {
  const at = src.indexOf("const " + name + " = ");
  assert(at !== -1, "const " + name + " not found");
  return src.slice(at, src.indexOf(";\n", at) + 1);
}

// The REAL engine's t() and tf() over one locale's map, plus current().
function makeI18n(lang) {
  const src = "var map = MAP;\n" + extract("t", I18N) + "\n" + extract("tf", I18N) + "\n" +
    "return { t: t, tf: tf, current: function () { return LANG; } };";
  return new Function("MAP", "LANG", src)(lang === "en" ? {} : LOCALE(lang), lang);
}

const HOST = { innerHTML: "" };
function load(lang) {
  const I = makeI18n(lang);
  const src =
    "var window = { OOI18N: I }; var OOI18N = I;\n" +
    "var document = { getElementById: function (id) { return id === 'ux-summary' ? HOST : null; } };\n" +
    "var _uxExportFacts = null;\n" +
    extractConst("esc", APP) + "\n" +
    ["_sizeText", "_fmtBytes", "humanBytes", "_storageSignedBytes", "fmtNum",
     "_uxRenderExportPanel", "_uxVerifySentence", "_uxVerifyDetail"].map((n) => extract(n, APP)).join("\n") + "\n" +
    extract("fmtBytes", TM).replace("function fmtBytes(", "function tmFmtBytes(").replace(/fmtBytes\.nf/g, "tmFmtBytes.nf") + "\n" +
    extract("fmtRate", TM).replace("function fmtRate(", "function tmFmtRate(").replace("fmtBytes(bps)", "tmFmtBytes(bps)") + "\n" +
    "return { I, humanBytes, _fmtBytes, _storageSignedBytes, _uxRenderExportPanel, tmFmtBytes, tmFmtRate };";
  return new Function("I", "HOST", src)(I, HOST);
}

const FSI = "\u2068", PDI = "\u2069", NB = "\u00a0";
const MIB = 1024 * 1024, GIB = 1024 * MIB;
// Without the isolates, and with the no-break space read as a space.
const bare = (s) => String(s).replace(/[\u2068\u2069]/g, "").replace(/\u00a0/g, " ");

// =========================== P8: byte sizes ================================ //
test("P8: the unit's written form follows the UI language; the number keeps the app's decimal point", () => {
  const en = load("en"), fr = load("fr"), ar = load("ar"), zh = load("zh"), ru = load("ru");
  assert(en.humanBytes(8.5 * MIB) === FSI + "8.5" + NB + "MB" + PDI, "en: " + JSON.stringify(en.humanBytes(8.5 * MIB)));
  assert(en.humanBytes(0) === FSI + "0" + NB + "B" + PDI, "en zero: " + JSON.stringify(en.humanBytes(0)));
  assert(fr.humanBytes(8.5 * MIB) === FSI + "8.5" + NB + "Mo" + PDI, "fr: " + JSON.stringify(fr.humanBytes(8.5 * MIB)));
  assert(fr.humanBytes(0) === FSI + "0" + NB + "o" + PDI, "fr zero: " + JSON.stringify(fr.humanBytes(0)));
  assert(fr.humanBytes(480 * 1024) === FSI + "480.0" + NB + "ko" + PDI, "fr KB: " + JSON.stringify(fr.humanBytes(480 * 1024)));
  assert(fr.humanBytes(20 * GIB) === FSI + "20.0" + NB + "Go" + PDI, "fr GB: " + JSON.stringify(fr.humanBytes(20 * GIB)));
  assert(ar.humanBytes(8.5 * MIB) === FSI + "8.5" + NB + "ميغابايت" + PDI, "ar: " + JSON.stringify(ar.humanBytes(8.5 * MIB)));
  assert(ar.humanBytes(0) === FSI + "0" + NB + "بايت" + PDI, "ar zero: " + JSON.stringify(ar.humanBytes(0)));
  assert(zh.humanBytes(8.5 * MIB) === FSI + "8.5" + NB + "MB" + PDI, "zh: " + JSON.stringify(zh.humanBytes(8.5 * MIB)));
  assert(ru.humanBytes(8.5 * MIB) === FSI + "8.5" + NB + "МБ" + PDI, "ru: " + JSON.stringify(ru.humanBytes(8.5 * MIB)));
});

test("P8: every locale isolates the size, fills the frame, and writes Latin digits", () => {
  for (const lang of LANGS) {
    const R = load(lang);
    for (const n of [0, 1023, 1536, 8.5 * MIB, 3.2 * GIB, 5 * 1024 * GIB]) {
      for (const [who, s] of [["humanBytes", R.humanBytes(n)], ["_fmtBytes", R._fmtBytes(n)], ["taskmanager fmtBytes", R.tmFmtBytes(n)]]) {
        assert(s.startsWith(FSI) && s.endsWith(PDI), `${lang} ${who}(${n}) is not isolated: ${JSON.stringify(s)}`);
        assert(!/\{n\}/.test(s), `${lang} ${who}(${n}) left the placeholder: ${s}`);
        assert(!/ /.test(s), `${lang} ${who}(${n}) can break between the number and its unit: ${JSON.stringify(s)}`);
        assert(/[0-9]/.test(s) && !/[\u0660-\u0669\u06f0-\u06f9\u09e6-\u09ef\u0966-\u096f]/.test(s),
          `${lang} ${who}(${n}) is not in Latin digits: ${s}`);
      }
    }
    assert(R.humanBytes(null) === "—" && R._fmtBytes(undefined) === "—" && R.tmFmtBytes(null) === "—",
      lang + ": an absent size must stay a dash");
  }
});

test("P8: the VALUE is unchanged -- only how it is written", () => {
  const en = load("en");
  assert(bare(en.humanBytes(1536)) === "1.5 KB", bare(en.humanBytes(1536)));
  assert(bare(en.humanBytes(16 * GIB)) === "16.0 GB", "humanBytes keeps one decimal: " + bare(en.humanBytes(16 * GIB)));
  assert(bare(en._fmtBytes(150 * MIB)) === "150 MB", "_fmtBytes keeps whole numbers from 100: " + bare(en._fmtBytes(150 * MIB)));
  assert(bare(en._fmtBytes(1.25 * MIB)) === "1.3 MB" || bare(en._fmtBytes(1.25 * MIB)) === "1.2 MB", bare(en._fmtBytes(1.25 * MIB)));
  assert(bare(en.tmFmtBytes(512.4)) === "512 B", "the task manager no longer prints a raw float tail: " + bare(en.tmFmtBytes(512.4)));
});

test("P8: a signed growth keeps its sign on the digits, inside the size's own isolate", () => {
  const ar = load("ar"), en = load("en");
  const down = ar._storageSignedBytes(-300 * MIB);
  assert(down === FSI + FSI + "−300.0" + PDI + NB + "ميغابايت" + PDI, "ar signed: " + JSON.stringify(down));
  assert(bare(en._storageSignedBytes(1.3 * GIB)) === "+1.3 GB", bare(en._storageSignedBytes(1.3 * GIB)));
  assert(bare(en._storageSignedBytes(0)) === "0 B", "a zero growth carries no sign");
});

test("P8: a rate is the size's frame inside the locale's per-second frame", () => {
  const ar = load("ar"), fr = load("fr"), en = load("en");
  assert(bare(en.tmFmtRate(MIB)) === "1.0 MB/s", bare(en.tmFmtRate(MIB)));
  assert(bare(fr.tmFmtRate(MIB)) === "1.0 Mo/s", bare(fr.tmFmtRate(MIB)));
  const r = bare(ar.tmFmtRate(MIB));
  assert(r.includes("ميغابايت") && r.includes("/ث") && !/\/s\b/.test(r), "ar rate: " + r);
  assert(en.tmFmtRate(null) === "—", "an absent rate stays a dash");
});

// ================== J-elapsed and J-licences: the export panel =================== //
const LAW = Object.keys(LOCALE("en")).find((k) => k.startsWith("Tracked legal documents — "));
assert(LAW, "the law licence line is not keyed in en.json");
const base = {
  destination: "/mnt/stick/202609121045_OpenOmniscience_Backup",
  corpus_included: true,
  volumes: { count: 5, bytes: 800, plaintext_bytes: 540, parity: true },
  tables: [{ name: "articles", rows: 300 }],
  files: [{ category: "wiki_dumps", files: 2, bytes: 90 }],
  elapsed: { corpus_s: 12.5, files_s: null, files_s_reason: "the large-data copy records no timing of its own" },
  encryption: { corpus_encrypted: true, note: "n" },
  schema: { backup_schema: "oo-backup-2", container: "oo-volumes-2", alembic_rev: "abc" },
  app_version: "0.3.0",
  verify: { state: "verified", total: 5, bad: [] },
  attribution: [{ key: "law", text: LAW, because: "table:law_documents" }],
  attribution_error: null,
};
function panel(lang, over) {
  const R = load(lang);
  HOST.innerHTML = "";
  R._uxRenderExportPanel({ ...base, ...over }, R.I.t);
  return { html: HOST.innerHTML, I: R.I };
}
const rowValue = (html, label) => {
  const e = label.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = new RegExp(">" + e + "</span><span>(.*?)</span></div>").exec(html);
  return m ? m[1] : null;
};

test("J-elapsed: each part of the Elapsed value is ONE keyed frame that reads as a phrase", () => {
  const en = panel("en", {});
  assert(rowValue(en.html, "Elapsed") === "12.5 s for the corpus · not recorded for the files",
    "en: " + rowValue(en.html, "Elapsed"));
  const fr = panel("fr", {});
  const v = rowValue(fr.html, fr.I.t("Elapsed"));
  assert(v === "12.5 s pour le corpus · non enregistré pour les fichiers", "fr: " + v);
  assert(!/non enregistré fichiers/.test(fr.html), "the fr value still welds a state to a bare noun");
  // A corpus-less export leaves the corpus part out rather than drawing "— corpus".
  const noCorpus = rowValue(panel("en", { corpus_included: false, volumes: {}, tables: [] }).html, "Elapsed");
  assert(noCorpus === "not recorded for the files", "corpus-less: " + noCorpus);
  // A corpus the app no longer holds the timing of says so; nothing at all is a dash.
  const notHeld = rowValue(panel("en", { files: [], elapsed: { corpus_s: null, files_s: null } }).html, "Elapsed");
  assert(notHeld === "not recorded for the corpus", "not held: " + notHeld);
  const nothing = rowValue(panel("en", { corpus_included: false, files: [], elapsed: {} }).html, "Elapsed");
  assert(nothing === "—", "nothing exported: " + nothing);
});

test("J-elapsed: no locale leaves an English fragment in the Elapsed value", () => {
  for (const lang of LANGS.filter((l) => l !== "en")) {
    const p = panel(lang, {});
    const v = rowValue(p.html, p.I.t("Elapsed"));
    const L = LOCALE(lang);
    const want = L["{d} for the corpus"].replace("{d}", L["{n} s"].replace("{n}", "12.5"))
      + " · " + L["not recorded for the files"];
    const escd = want.replace(/&/g, "&amp;").replace(/'/g, "&#39;");
    assert(v === escd, `${lang}: ${v} (want ${escd})`);
    assert(!/for the|not recorded/.test(v), lang + " kept an English fragment: " + v);
  }
});

test("J-licences: a licence line is looked up as a key, in every locale", () => {
  const en = panel("en", {});
  assert(en.html.includes(">" + LAW.replace(/'/g, "&#39;") + "</div>"), "en lost the line: " + en.html);
  for (const lang of LANGS.filter((l) => l !== "en")) {
    const p = panel(lang, {});
    const want = LOCALE(lang)[LAW];
    assert(want && want !== LAW, lang + ".json has no translation of the law line");
    const escd = want.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    assert(p.html.includes('<div dir="auto" title="') && p.html.includes(">" + escd + "</div>"),
      lang + ": the licence line is still the server's English: " + p.html.slice(p.html.indexOf("dir=\"auto\""), p.html.indexOf("dir=\"auto\"") + 200));
    assert(!p.html.includes(LAW), lang + ": the English line still renders");
  }
});

console.log("all assertions passed (" + passed + " tests)");
