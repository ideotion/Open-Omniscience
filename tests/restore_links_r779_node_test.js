/**
 * R779: a backup category folder that is a link restores nothing, and the page says so -- on the import
 * checklist before the restore, and as "Restore incomplete" after it.
 *
 * _uxImBlobRow and _fbRefusalLines are EXTRACTED FROM THE SHIPPED SOURCE and run with the REAL locale files.
 * Run by tests/test_restore_links_r779.py (and standalone).
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
const LINKED = "This folder in the backup is a link, and a restore never follows a link, so nothing in it will be restored. To restore it, copy the real folder into the backup in place of the link.";
const CAT_LINES = "Restore incomplete — these folders in the backup are links, and a restore never follows a link, so nothing in them was restored. To restore them, copy the real folder into the backup in place of the link";
const DEST_LINES = "Restore incomplete — not restored, because a link stands on the way to their place in your data folder, and a restore never writes through a link";
const MEMBER_LINES = "Not restored — links inside the backup, which a restore never follows";

function sandbox(lang) {
  const cat = LOCALE(lang);
  const t = (k) => (cat[k] != null ? cat[k] : k);
  const tfs = (s, v) => String(t(s)).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
  const OOI18N = { t, tf: tfs };
  const paren = (html) => esc(tfs("({text})", { text: "\u0001" })).replace("\u0001", () => html);
  // eslint-disable-next-line no-new-func
  const api = new Function("window", "OOI18N", "esc", "fmtNum",
    [extract("ooLabelText", CORE), extract("_uxImBlobRow", SRC), extract("_fbRefusalLines", SRC),
      "return { row: _uxImBlobRow, lines: _fbRefusalLines };"].join("\n"))({ OOI18N }, OOI18N, esc, (n) => String(n));
  return { api, t, tfs, paren };
}

for (const lang of ["en", "fr", "ar"]) {
  const { api, t, tfs, paren } = sandbox(lang);
  assert(t(LINKED) !== LINKED || lang === "en", lang + ": the linked-folder reason is not translated");
  // 1. Before the restore: a linked category reads "a link, not restored", never a count, the remedy on hover.
  const row = api.row({ wiki: { count: 0, bytes: 0, linked: 1, reason: LINKED }, maps: { count: 2, bytes: 5 } }, t, tfs, paren);
  assert(row.includes(esc(t("a link, not restored"))), lang + ": linked category not said: " + row);
  assert(row.includes(`title="${esc(t(LINKED))}"`), lang + ": the remedy is not on the hover: " + row);
  assert(!row.includes(esc(tfs("{n} files", { n: "0" }))), lang + ": a linked category reads as an empty one: " + row);
  // 2. After the restore: each refusal is its own visible line, naming the category, never a path.
  const lines = api.lines({ refused_categories: ["wiki_dumps"], refused_dest_links: 2, refused_symlinks: 3 });
  assert(lines.length === 3, lang + ": expected three refusal lines, got " + JSON.stringify(lines));
  assert(lines[0].includes(t(CAT_LINES)) && lines[0].includes("wiki_dumps"), lang + ": category line: " + lines[0]);
  assert(lines[1].includes(t(DEST_LINES)) && lines[1].includes("2"), lang + ": destination line: " + lines[1]);
  assert(lines[2].includes(t(MEMBER_LINES)) && lines[2].includes("3"), lang + ": member line: " + lines[2]);
  // 3. A clean restore says nothing.
  assert(api.lines({ refused_categories: [], refused_dest_links: 0, refused_symlinks: 0 }).length === 0, lang + ": clean restore drew a line");
}
console.log("ok - restore links R779 (3 checks x 3 languages)");
