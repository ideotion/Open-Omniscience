/**
 * Row 293: the import checklist's large-data row says "at least" and why, and a refused folder is said on screen.
 *
 * _uxImBlobRow and _uxImUnreadNote are EXTRACTED FROM THE SHIPPED SOURCE and run with the REAL locale files.
 * Run by tests/test_import_scan_unread_r293.py (and standalone).
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
const UNREAD = "Some files or folders here could not be read, so this count includes only the ones that could.";
const LINKS = "Links in this backup folder are not counted: a restore never follows a link, so they are never restored.";

function sandbox(lang) {
  const cat = LOCALE(lang);
  const t = (k) => (cat[k] != null ? cat[k] : k);
  const tfs = (s, v) => String(t(s)).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
  const OOI18N = { t, tf: tfs };
  const paren = (html) => esc(tfs("({text})", { text: "\u0001" })).replace("\u0001", () => html);
  // eslint-disable-next-line no-new-func
  const api = new Function("window", "OOI18N", "esc", "fmtNum",
    [extract("ooLabelText", CORE), extract("_uxImBlobRow", SRC), extract("_uxImUnreadNote", SRC),
      "return { row: _uxImBlobRow, note: _uxImUnreadNote };"].join("\n"))({ OOI18N }, OOI18N, esc, (n) => String(n));
  return { api, t, tfs, paren };
}

for (const lang of ["en", "fr"]) {
  const { api, t, tfs, paren } = sandbox(lang);
  // 1. A clean scan: no "at least", no hover.
  const clean = api.row({ wiki: { count: 2, bytes: 9 } }, t, tfs, paren);
  assert(!clean.includes(esc(t("at least"))) && !clean.includes("title="), lang + ": clean row marked: " + clean);
  // 2. Refusals: "at least" before that category's count, the reason on the hover, the other category untouched.
  const part = api.row({ wiki: { count: 1, bytes: 3, unread_entries: 1, reason: UNREAD }, maps: { count: 4, bytes: 1 } }, t, tfs, paren);
  assert(part.includes(esc(t("at least") + " " + tfs("{n} file", { n: "1" }))), lang + ": no 'at least' on the partial count: " + part);
  assert(!part.includes(esc(t("at least") + " " + tfs("{n} files", { n: "4" }))), lang + ": a whole count read 'at least'");
  assert(part.includes(`title="${esc(t(UNREAD))}"`), lang + ": the reason is not on the hover: " + part);
  // 3. Links: not counted, said on the hover, the count stays whole.
  const lnk = api.row({ models: { count: 2, bytes: 3, refused_links: 1 } }, t, tfs, paren);
  assert(lnk.includes(esc(t(LINKS))) && !lnk.includes(esc(t("at least"))), lang + ": links not explained, or count marked: " + lnk);
  // 4. A category it could not list at all still shows, as "at least 0 files".
  const zero = api.row({ maps: { count: 0, bytes: 0, unread_entries: 1, reason: UNREAD } }, t, tfs, paren);
  assert(zero.includes(esc(t("at least") + " " + tfs("{n} files", { n: "0" }))), lang + ": unlistable category hidden: " + zero);
  // 5. Refused folders of the scan itself: one and many, keyed.
  assert(api.note(1, t, tfs) === esc(t("1 folder here could not be read, so anything inside it is not listed.")), lang + ": one-folder note");
  assert(api.note(3, t, tfs).includes("3") && api.note(3, t, tfs) !== api.note(1, t, tfs), lang + ": many-folder note");
}
console.log("ok - import scan row 293 (5 checks x 2 languages)");
