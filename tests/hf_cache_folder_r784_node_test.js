/**
 * R784: the Hugging Face cache folder a restore writes to is shown on the import checklist before
 * the person chooses; a folder that cannot be used, and an older backup that did not record its folder, are said.
 * _uxImHfNote, _hfTargetWhy and _fbRefusalLines are EXTRACTED FROM THE SHIPPED SOURCE and run with the REAL locale files.
 * Run by tests/test_hf_cache_folder_r784.py (and standalone).
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const SRC = fs.readFileSync(path.join(STATIC, "app-backup.js"), "utf-8");
const CORE = fs.readFileSync(path.join(STATIC, "app-core.js"), "utf-8");
const LOCALE = (code) => JSON.parse(fs.readFileSync(path.join(STATIC, "locales", code + ".json"), "utf-8"));

function assert(cond, msg) { if (!cond) { console.error("FAIL: " + msg); process.exit(1); } }

function extract(name, src) {
  const head = "function " + name + "(";
  const at = src.indexOf(head);
  assert(at !== -1, "could not find " + head);
  const i = src.indexOf("{", src.indexOf(")", at));
  let depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  assert(false, "unbalanced braces extracting " + name);
}

const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const TO = "Hugging Face models are restored to";
const NOT_HERE = "Hugging Face models will not be restored on this computer";
const INC = "Restore incomplete — the Hugging Face model cache was not restored";
const OLD = "This backup was made before it recorded which Hugging Face cache folder it read: if that computer's cache folder was not named “hub”, its models are not in this backup.";
const WHY = {
  "not-a-folder": "its path is taken by something that is not a folder",
  "not-writable": "its folder cannot be written to",
  "unresolved": "its folder could not be worked out",
};

for (const lang of ["en", "fr", "ar", "ja"]) {
  const cat = LOCALE(lang);
  const t = (k) => (cat[k] != null ? cat[k] : k);
  const tf = (s, v) => String(t(s)).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
  const OOI18N = { t, tf };
  for (const k of [TO, NOT_HERE, INC, OLD, ...Object.values(WHY)]) assert(lang === "en" || t(k) !== k, lang + ": not translated: " + k);
  const mk = (fn) => new Function("window", "OOI18N", "esc", "fmtNum",
    [extract("ooLabelText", CORE), extract("_hfTargetWhy", SRC), extract(fn, SRC), "return " + fn + ";"].join("\n"))(
    { OOI18N }, OOI18N, esc, (n) => String(n));
  const note = mk("_uxImHfNote");
  const b = { hf_models: { count: 2, bytes: 9 } };
  // The real folder, drawn as an LTR run, escaped -- before the person chooses.
  const p = "/home/a&b/.cache/my-models";
  const n1 = note(b, { path: p, refused: null }, t);
  assert(n1.includes(esc(t(TO))) && n1.includes('<bdi dir="ltr"') && n1.includes(esc(p)), lang + ": the folder is missing: " + n1);
  assert(!n1.includes(esc(t(OLD))), lang + ": a recorded backup drew the older-backup note: " + n1);
  // A folder that cannot be used: the named reason, never the path as if it would be used.
  for (const [code, why] of Object.entries(WHY)) {
    const n2 = note(b, { path: p, refused: code }, t);
    assert(n2.includes(esc(t(NOT_HERE))) && n2.includes(esc(t(why))) && !n2.includes(esc(t(TO))) && n2.includes(esc(p)), lang + ": refusal " + code + ": " + n2);
  }
  // An older backup says what it may be missing.
  const n3 = note({ hf_models: { count: 1, layout_unrecorded: 1 } }, { path: p, refused: null }, t);
  assert(n3.includes(esc(t(OLD))), lang + ": the older-backup note is missing: " + n3);
  // No model cache in the backup: nothing drawn.
  assert(note({ wiki: { count: 1 } }, { path: p }, t) === "" && note({ hf_models: { count: 0 } }, null, t) === "", lang + ": drew a note for no models");
  // The result line.
  const lines = mk("_fbRefusalLines");
  const out = lines({ refused_targets: { hf_models: "not-writable" }, incomplete: true });
  assert(out.length === 1 && out[0].includes(t(INC)) && out[0].includes(t(WHY["not-writable"])), lang + ": result line: " + JSON.stringify(out));
  assert(lines({ refused_targets: {} }).length === 0, lang + ": drew a line for nothing refused");
}

// R787: the same rules for the models an encrypted artifact carries.
const TICK = "Also restore the Hugging Face models this backup carries";
const LEFT1 = "Not restored, because it was not ticked: {n} Hugging Face model file stays in this backup";
const LEFTN = "Not restored, because they were not ticked: {n} Hugging Face model files stay in this backup";
const FMERR = "The corpus was restored; putting the large files this backup carries back in place did not work.";
for (const lang of ["en", "fr", "ar", "ja", "ru", "hi"]) {
  const cat = LOCALE(lang);
  const t = (k) => (cat[k] != null ? cat[k] : k);
  const tf = (s, v) => String(t(s)).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
  const OOI18N = { t, tf };
  for (const k of [TICK, LEFT1, LEFTN, FMERR]) assert(lang === "en" || t(k) !== k, lang + ": not translated: " + k);
  const paren = (html) => "(" + html + ")";
  const mk = (fn, extra) => new Function("window", "OOI18N", "esc", "fmtNum",
    [extract("ooLabelText", CORE), extract("_hfTargetWhy", SRC), extract("_uxImHfNote", SRC), ...(extra || []).map((x) => extract(x, SRC)),
      extract(fn, SRC), "return " + fn + ";"].join("\n"))({ OOI18N }, OOI18N, esc, (n) => String(n));
  const row = mk("_uxImArtifactHfRow", ["_uxImHfTick"]);
  const p = "/home/x/.cache/huggingface/hub";
  // Never ticked by default; the folder beside the tick.
  const r1 = row([{ path: "a", hf_models: { count: 3, layout_recorded: true } }], { path: p, refused: null }, t, tf, paren);
  assert(r1.includes('id="ux-i-corpus-hf"') && !/ux-i-corpus-hf"[^>]*checked/.test(r1), lang + ": ticked by default: " + r1);
  assert(r1.includes(esc(t(TICK))) && r1.includes(esc(p)) && r1.includes(esc(t(TO))) && !r1.includes(esc(t(OLD))), lang + ": row: " + r1);
  // A folder that cannot take them: the tick cannot be made, the reason is said.
  const r2 = row([{ hf_models: { count: 1, layout_recorded: true } }], { path: p, refused: "not-writable" }, t, tf, paren);
  assert(/ux-i-corpus-hf" disabled/.test(r2) && r2.includes(esc(t(NOT_HERE))) && r2.includes(esc(t(WHY["not-writable"]))), lang + ": refused row: " + r2);
  // An old artifact without the layout marker.
  const r3 = row([{ hf_models: { count: 1, layout_recorded: false } }], { path: p, refused: null }, t, tf, paren);
  assert(r3.includes(esc(t(OLD))), lang + ": old-artifact note missing: " + r3);
  assert(row([{ path: "a" }], { path: p }, t, tf, paren) === "", lang + ": drew a row for no models");
  // The result lines.
  const fl = mk("_uxImArtifactFileLines");
  const o1 = fl({ hf_not_chosen: 2, refused_targets: {}, incomplete: false }, t);
  assert(o1.lines.length === 1 && o1.lines[0] === tf(LEFTN, { n: "2" }) && o1.incomplete === false, lang + ": not ticked: " + JSON.stringify(o1));
  assert(fl({ hf_not_chosen: 1 }, t).lines[0] === tf(LEFT1, { n: "1" }), lang + ": one file");
  const o2 = fl({ refused_targets: { hf_models: "not-a-folder" }, incomplete: true }, t);
  assert(o2.incomplete === true && o2.lines[0].includes(t(INC)) && o2.lines[0].includes(t(WHY["not-a-folder"])), lang + ": refused: " + JSON.stringify(o2));
  const o3 = fl({ placed: 0, error: "x" }, t);
  assert(o3.incomplete === true && o3.lines[0] === t(FMERR), lang + ": error: " + JSON.stringify(o3));
  assert(fl(null, t).lines.length === 0 && fl({ placed: 3, hf_not_chosen: 0, refused_targets: {}, incomplete: false }, t).incomplete === false, lang + ": drew for nothing");
}
console.log("hf cache folder r784 node: ok");
