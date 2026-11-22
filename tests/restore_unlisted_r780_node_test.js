/**
 * R780: files a restore brought back that the backup's current manifest does not list are said
 * apart, per category, in the result and on the import checklist row -- never as proof of anything.
 * _fbRefusalLines and _uxImBlobRow are EXTRACTED FROM THE SHIPPED SOURCE and run with the REAL locale files.
 * Run by tests/test_restore_unlisted_r780.py (and standalone).
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
const LINE = "Restored, but not listed in this backup's current manifest; they may come from an earlier or interrupted backup pass";
const PART = "({n} not in the manifest)";
const HOVER = "Some files here are not listed in this backup's current manifest; they may come from an earlier or interrupted backup pass. They are restored like the others, without a recorded checksum to check them against. Anyone who can write to this backup folder could also have placed them there, or listed files of their own: the manifest carries its own signing key.";

for (const lang of ["en", "fr", "ar", "ja"]) {
  const cat = LOCALE(lang);
  const t = (k) => (cat[k] != null ? cat[k] : k);
  const tf = (s, v) => String(t(s)).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
  const OOI18N = { t, tf };
  for (const k of [LINE, PART, HOVER]) assert(lang === "en" || t(k) !== k, lang + ": not translated: " + k);
  // eslint-disable-next-line no-new-func
  const lines = new Function("window", "OOI18N", "esc", "fmtNum",
    [extract("ooLabelText", CORE), extract("_fbRefusalLines", SRC), "return _fbRefusalLines;"].join("\n"))(
    { OOI18N }, OOI18N, esc, (n) => String(n));
  // Per category, readable names, the two model stores added into the one "LLM models".
  const out = lines({ restored_unlisted: { wiki_dumps: 2, models: 1, hf_models: 3, osm_regions: 0 } });
  assert(out.length === 1, lang + ": expected one line, got " + JSON.stringify(out));
  const l = out[0];
  assert(l.includes(t(LINE)), lang + ": the line is missing: " + l);
  assert(l.includes(t("Wikipedia dumps") + " 2") && l.includes(t("LLM models") + " 4"), lang + ": the counts: " + l);
  assert(!l.includes(t("Offline maps")), lang + ": a zero category was drawn: " + l);
  // Nothing unlisted draws nothing.
  assert(lines({ restored_unlisted: {} }).length === 0 && lines({}).length === 0, lang + ": a clean restore drew a line");
  // The checklist row: the count on the row, the reason on hover.
  const paren = (html) => esc(tf("({text})", { text: "\u0001" })).replace("\u0001", () => html);
  // eslint-disable-next-line no-new-func
  const row = new Function("window", "OOI18N", "esc", "fmtNum",
    [extract("ooLabelText", CORE), extract("_uxImBlobRow", SRC), "return _uxImBlobRow;"].join("\n"))(
    { OOI18N }, OOI18N, esc, (n) => String(n));
  const r = row({ wiki: { count: 3, bytes: 9, unlisted: 1, unlisted_reason: "x" } }, t, tf, paren);
  assert(r.includes(esc(tf(PART, { n: "1" }))), lang + ": the row count is missing: " + r);
  assert(r.includes(esc(t(HOVER))), lang + ": the hover reason is missing: " + r);
  const clean = row({ wiki: { count: 3, bytes: 9 } }, t, tf, paren);
  assert(!clean.includes(esc(t(HOVER))), lang + ": a fully listed row says unlisted: " + clean);
}
console.log("ok - restore unlisted R780 (5 checks x 4 languages)");
