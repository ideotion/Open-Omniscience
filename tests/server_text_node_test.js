// A sentence the server wrote, in the reader's language or labelled as English (row 206).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// ooSaidHtml / ooSaidText are EXTRACTED from the shipped app-core.js, never re-typed, and run over a stub
// translator. Mostly refusals: an English sentence is never passed off as translated on a page that is not English;
// a frame's value is data and is not looked up, unless the frame names it in `tr`; a malformed frame never hides the
// English; nothing a server value holds is read as markup.

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

let n = 0;
function check(cond, msg) { assert.ok(cond, msg); n++; }

const FR = {
  "Server text, in English": "Texte du serveur, en anglais",
  "{prefix}: {text}": "{prefix} : {text}",
  "Stored with care.": "Conservé avec soin.",
  "Flags at robust z >= {z} with >= {n} earlier revisions.": "Signalé à z robuste >= {z} avec >= {n} révisions antérieures.",
  "skipped: {why}": "ignoré : {why}",
  "scanned": "numérisé",
};

function make(lang, table) {
  const OOI18N = {
    current: () => lang,
    t: (s) => (table[s] != null ? table[s] : s),
    tf: (s, v) => String(table[s] != null ? table[s] : s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null ? String(v[k]) : m)),
  };
  const src =
    "const esc = (s) => (s == null ? '' : String(s).replace(/[&<>\"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',\"'\":'&#39;'}[c])));\n" +
    "function fmtNum(v) { return 'N' + v; }\n" +
    extract("ooLabelHtml") + "\n" + extract("ooLabelText") + "\n" +
    extract("_ooSaidFramed") + "\n" + extract("ooSaidText") + "\n" + extract("ooSaidHtml") + "\n" +
    "return { ooSaidText, ooSaidHtml };";
  return new Function("window", "OOI18N", src)({ OOI18N }, OOI18N);
}

const fr = make("fr", FR), en = make("en", {}), ar = make("ar", {});

// a frame renders through the template key; a number is written with the shared formatter
const framed = {
  method: "Flags at robust z >= 3.5 with >= 4 earlier revisions.",
  method_i18n: [{ t: "Flags at robust z >= {z} with >= {n} earlier revisions.", v: { z: 3.5, n: 4 } }],
};
check(fr.ooSaidText(framed, "method") === "Signalé à z robuste >= N3.5 avec >= N4 révisions antérieures.", "a frame renders in the page's language");
check(en.ooSaidText(framed, "method") === "Flags at robust z >= N3.5 with >= N4 earlier revisions.", "the English page fills the same template");

// a value is data, never looked up -- unless the frame names it in `tr`
const reason = { reason: "skipped: scanned", reason_i18n: [{ t: "skipped: {why}", v: { why: "scanned" } }] };
check(fr.ooSaidText(reason, "reason") === "ignoré : scanned", "a plain value is never translated");
reason.reason_i18n[0].tr = ["why"];
check(fr.ooSaidText(reason, "reason") === "ignoré : numérisé", "a `tr` value is itself a keyed word");

// no frames: an English sentence that IS a key is looked up
check(fr.ooSaidText({ caveat: "Stored with care." }, "caveat") === "Conservé avec soin.", "a keyed constant translates");

// no frames, no key: shown as sent, LABELLED on a page that is not English, plain on an English page
const raw = { caveat: "A sentence only the server knows." };
check(en.ooSaidText(raw, "caveat") === "A sentence only the server knows.", "an English page shows it plainly");
check(fr.ooSaidText(raw, "caveat") === "Texte du serveur, en anglais : A sentence only the server knows.", "a French page labels it");
const html = fr.ooSaidHtml(raw, "caveat");
check(html.includes('<span lang="en" dir="ltr">A sentence only the server knows.</span>'), "the English rides in its own left-to-right span");
check(html.startsWith("Texte du serveur, en anglais"), "behind the visible label");
check(ar.ooSaidHtml(raw, "caveat").includes('dir="ltr"'), "an Arabic page keeps the English left to right");
check(en.ooSaidHtml(raw, "caveat") === "A sentence only the server knows.", "no label on an English page");

// a malformed frame never hides the English (and is labelled, since nothing translated it)
check(fr.ooSaidText({ caveat: "Plain.", caveat_i18n: [{ v: {} }, null] }, "caveat").endsWith("Plain."), "a malformed frame falls back to the English");
check(fr.ooSaidText({ caveat: "Plain.", caveat_i18n: [] }, "caveat").endsWith("Plain."), "an empty frame list falls back too");

// nothing to say renders nothing, never a label over nothing
check(fr.ooSaidText({}, "caveat") === "" && fr.ooSaidHtml(null, "caveat") === "", "an absent sentence renders nothing");

// nothing a server value holds is read as markup
const evil = { caveat: "<img src=x onerror=alert(1)>", caveat_i18n: [{ t: "skipped: {why}", v: { why: "<b>x</b>" } }] };
check(!fr.ooSaidHtml(evil, "caveat").includes("<b>"), "a frame value is escaped");
check(!fr.ooSaidHtml({ caveat: evil.caveat }, "caveat").includes("<img"), "the English fallback is escaped");

console.log(n + " checks, all checks passed");
