/**
 * R777: the import checklist shows the Hugging Face cache and the Ollama store as ONE "LLM models"
 * count, and says on the row that a restore never overwrites a file already there.
 * _uxImBlobRow is EXTRACTED FROM THE SHIPPED SOURCE and run with the REAL locale files.
 * Run by tests/test_import_scan_hf_models_r777.py (and standalone).
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
const KEEP = "A file already in your data folders is kept as it is: a restore never overwrites it, and never downloads anything.";

for (const lang of ["en", "fr", "ar"]) {
  const cat = LOCALE(lang);
  const t = (k) => (cat[k] != null ? cat[k] : k);
  const tfs = (s, v) => String(t(s)).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
  const OOI18N = { t, tf: tfs };
  const paren = (html) => esc(tfs("({text})", { text: "\u0001" })).replace("\u0001", () => html);
  // eslint-disable-next-line no-new-func
  const row = new Function("window", "OOI18N", "esc", "fmtNum",
    [extract("ooLabelText", CORE), extract("_uxImBlobRow", SRC), "return _uxImBlobRow;"].join("\n"))(
    { OOI18N }, OOI18N, esc, (n) => String(n));
  assert(lang === "en" || t(KEEP) !== KEEP, lang + ": the keep line is not translated");
  // Both stores: one line, the two counts added.
  const both = row({ models: { count: 2, bytes: 5 }, hf_models: { count: 3, bytes: 7 } }, t, tfs, paren);
  assert(both.includes(esc(tfs("{n} files", { n: "5" }))), lang + ": counts not added: " + both);
  assert((both.match(new RegExp(esc(t("LLM models")), "g")) || []).length === 1, lang + ": LLM models named twice: " + both);
  // Only the Hugging Face cache (a vLLM-only machine): still the one line.
  const hf = row({ hf_models: { count: 1, bytes: 9 } }, t, tfs, paren);
  assert(hf.includes(esc(t("LLM models"))) && hf.includes(esc(tfs("{n} file", { n: "1" }))), lang + ": hf alone not shown: " + hf);
  // The keep line is visible on the row, not only on hover.
  assert(both.includes(">" + esc(t(KEEP)) + "<"), lang + ": the keep line is not visible: " + both);
}
console.log("ok - import scan hf_models R777 (3 checks x 3 languages)");
