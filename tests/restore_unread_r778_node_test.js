/**
 * R778: a file the restore could not READ is left out, the rest is restored, and the page says
 * "Restore incomplete: N files not restored" with the reason for each -- counted over every file.
 *
 * _fbRefusalLines is EXTRACTED FROM THE SHIPPED SOURCE and run with the REAL locale files.
 * Run by tests/test_restore_unread_r778.py (and standalone).
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
const DIRS = "Restore incomplete — folders in the backup that could not be listed, so whatever they hold was not restored";
const MAIN = "Restore incomplete: {n} files not restored, because they could not be read. The rest was restored; run the import again to bring back only these";

for (const lang of ["en", "fr", "ar", "ja"]) {
  const cat = LOCALE(lang);
  const t = (k) => (cat[k] != null ? cat[k] : k);
  const tf = (s, v) => String(t(s)).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
  const OOI18N = { t, tf };
  // eslint-disable-next-line no-new-func
  const lines = new Function("window", "OOI18N", "esc", "fmtNum",
    [extract("ooLabelText", CORE), extract("_fbRefusalLines", SRC), "return _fbRefusalLines;"].join("\n"))(
    { OOI18N }, OOI18N, esc, (n) => String(n));
  assert(lang === "en" || t(MAIN) !== MAIN, lang + ": the main line is not translated");
  // 200 unread files and 50 unlisted folders, only a few named (the backend caps the list): the
  // reasons are counted over every one, and a folder is never added to the FILE count.
  const out = lines({
    unread_total: 200,
    unread_folders: 50,
    unread_by_why: { denied: 200, "folder-unlisted": 50 },
    unread: [{ category: "wiki_dumps", rel: "a.bz2", why: "denied" }, { category: "osm_regions", rel: "sub", why: "folder-unlisted" }],
  });
  assert(out.length === 2, lang + ": expected a file line and a folder line, got " + JSON.stringify(out));
  const [l, d] = out;
  assert(l.includes(tf(MAIN, { n: "200" })), lang + ": the file count is not stated: " + l);
  assert(l.includes(t("permission denied") + " 200"), lang + ": the denied count is not over every file: " + l);
  assert(l.includes("wiki_dumps/a.bz2") && !l.includes("osm_regions/sub"), lang + ": the named file is wrong: " + l);
  assert(l.includes(tf("+ {n} more (not shown)", { n: 199 })), lang + ": the remainder is not stated: " + l);
  assert(d.includes(t(DIRS)) && d.includes("50") && d.includes("osm_regions/sub"), lang + ": the folder line: " + d);
  // An unknown code from an older or damaged record still reads as "could not be read", never blank.
  const odd = lines({ unread_total: 1, unread_by_why: { weird: 1 }, unread: [{ category: "models", rel: "x", why: "weird" }] })[0];
  assert(odd.includes(t("could not be read") + " 1"), lang + ": an unknown reason fell through: " + odd);
  // A clean restore draws nothing.
  assert(lines({ unread_total: 0, unread: [] }).length === 0, lang + ": a clean restore drew a line");
}
console.log("ok - restore unread R778 (4 checks x 4 languages)");
