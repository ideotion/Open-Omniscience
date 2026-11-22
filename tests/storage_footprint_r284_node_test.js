/**
 * Row 284: the storage footprint panel never shows a store it could not read as 0, nor drops it.
 *
 * _sfPaint and _paintDbFile are EXTRACTED FROM THE SHIPPED SOURCE and run on a complete payload, a
 * payload with a protected Ollama store (bytes null + reason) and one with a partly read line. Translations
 * come from the REAL locale files, so the visible words and the hover reason are checked in French too.
 *
 * Run by tests/test_storage_footprint_r284.py (and standalone).
 * Open Omniscience - Global Intelligence Platform for Investigative Journalism
 * Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
 */
"use strict";

const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const LIB = fs.readFileSync(path.join(STATIC, "app-library.js"), "utf-8");
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
const SRC = [
  "const _SF_PUBLIC = new Set(['wiki_dumps', 'osm_regions', 'ollama_models']);",
  "let _sfCache = null, _dbStatsLast = null;",
  extract("ooLabelHtml", CORE), extract("_sfLabel", LIB), extract("_sfPaint", LIB), extract("_paintDbFile", LIB),
  "return { paint: _sfPaint, dbFile: _paintDbFile, set: (sf, st) => { _sfCache = sf; _dbStatsLast = st; } };",
].join("\n");

function sandbox(lang) {
  const cat = LOCALE(lang);
  const OOI18N = { t: (k) => (cat[k] != null ? cat[k] : k), tf: (s, v) => String(cat[s] != null ? cat[s] : s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m) };
  const els = { "db-file": { innerHTML: "" } };
  // eslint-disable-next-line no-new-func
  const api = new Function("window", "OOI18N", "esc", "_fmtBytes", "humanBytes", "ooSaidText", "$", SRC)(
    { OOI18N }, OOI18N, esc, (n) => n + " B", (n) => n + " B", () => "method", (id) => els[id] || null);
  return { api, t: OOI18N.t, els, cat };
}

const PROT = "This model store is protected: this app is not allowed to read it, so its size is not counted.";
const PART = "Some folders or files here could not be read; this figure counts only the ones that could.";
const CAV = "Not every store could be measured, so this total is a lower bound. Hover a line for the reason.";

const COMPLETE = { totals: { grand_total_bytes: 30, complete: true }, components: [
  { kind: "db", name: "database", bytes: 20 }, { kind: "wiki_dumps", name: "wiki dumps", bytes: 10 },
  { kind: "ollama_models", name: "Ollama model store", bytes: 0 }] };
const PROTECTED = { totals: { grand_total_bytes: 30, complete: false }, components: [
  { kind: "db", name: "database", bytes: 20 }, { kind: "wiki_dumps", name: "wiki dumps", bytes: 10 },
  { kind: "ollama_models", name: "Ollama model store", bytes: 0 },
  { kind: "ollama_models", name: "Ollama model store (protected)", bytes: null, measured: false,
    reason: PROT, detail: "/usr/share/ollama/.ollama/models", outside_data_dir: true }] };
const PARTIAL = { totals: { grand_total_bytes: 30, complete: false }, components: [
  { kind: "db", name: "database", bytes: 20 },
  { kind: "wiki_dumps", name: "wiki dumps", bytes: 10, partial: true, reason: PART }] };

function paint(lang, d) {
  const sb = sandbox(lang);
  const host = { id: "library-storage", innerHTML: "" };
  sb.api.paint(host, d, sb.t);
  return { html: host.innerHTML, sb };
}

function rowFor(html, label) {
  const rows = html.split('<div class="sf-row"').slice(1);
  const hit = rows.find((x) => x.includes(esc(label)));
  assert(hit, "no row labelled " + label + " in " + html);
  return hit;
}

// 1. A complete footprint keeps its plain look: no "at least", no caveat, no "not measured".
{
  const { html, sb } = paint("en", COMPLETE);
  assert(!html.includes("at least") && !html.includes(CAV) && !html.includes("not measured"), "complete payload marked incomplete: " + html);
  assert(html.includes("<b style=\"font-size:1.15em\">30 B</b>"), "total missing: " + html);
  assert(!html.includes("Ollama model store"), "a measured 0 line is still hidden as before");
  sb.api.set(COMPLETE, { backend: "sqlite", file: { bytes: 20, path: "/x" } });
  sb.api.dbFile();
  assert(!sb.els["db-file"].innerHTML.includes("at least"), "db line marked incomplete");
}

// 2. A protected store: its own row, "not measured" visible, reason on hover; total + public sum "at least".
for (const lang of ["en", "fr"]) {
  const { html, sb } = paint(lang, PROTECTED);
  const t = sb.t;
  const row = rowFor(html, t("Local AI models"));
  const prot = html.split('<div class="sf-row"').slice(1).find((x) => x.includes(esc(t("not measured"))));
  assert(prot, lang + ": no 'not measured' row: " + html);
  assert(prot.includes(esc(t(PROT))), lang + ": the reason is not on the hover: " + prot);
  assert(prot.includes("/usr/share/ollama/.ollama/models"), lang + ": the path is not on the hover");
  assert(!/>0 B</.test(prot), lang + ": the protected store reads 0: " + prot);
  assert(html.includes(esc(t(CAV))), lang + ": the incomplete caveat is not visible");
  assert(html.includes(esc(t("at least")) + " <b style=\"font-size:1.15em\">30 B</b>"), lang + ": total not 'at least': " + html);
  assert(html.includes(esc(t("at least")) + " <b>10 B</b>"), lang + ": public sum not 'at least'");
  assert(!html.includes(esc(t("at least")) + " <b>20 B</b>"), lang + ": private sum wrongly 'at least'");
  assert(html.indexOf(esc(t("not measured"))) > html.indexOf("20 B</div></div>"), lang + ": unmeasured row not last");
  assert(row, "row");
  sb.api.set(PROTECTED, { backend: "sqlite", file: { bytes: 20, path: "/x" } });
  sb.api.dbFile();
  assert(sb.els["db-file"].innerHTML.includes(esc(t("at least")) + " <strong>30 B</strong>"), lang + ": db line not 'at least': " + sb.els["db-file"].innerHTML);
}

// 3. A partly read line: its figure reads "at least", the reason on hover.
{
  const { html, sb } = paint("fr", PARTIAL);
  const row = rowFor(html, sb.t("Wikipedia dumps"));
  assert(row.includes(esc(sb.t("at least")) + " 10 B"), "partial row not 'at least': " + row);
  assert(row.includes(esc(sb.t(PART))), "partial reason not on hover: " + row);
  assert(html.includes(esc(sb.t(CAV))), "caveat missing for a partial footprint");
}


// 4. The forensics panel's data-folder block (app-diagnostics.js): an unlisted folder is "not measured",
//    never "0 B"; refused entries make every figure "at least" with the reason on screen.
{
  const DIAG = fs.readFileSync(path.join(STATIC, "app-diagnostics.js"), "utf-8");
  const cat = LOCALE("fr");
  const t = (k) => (cat[k] != null ? cat[k] : k);
  const tf = (s, v) => String(t(s)).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m);
  const OOI18N = { t, tf };
  // eslint-disable-next-line no-new-func
  const render = new Function("window", "OOI18N", "esc", "humanBytes", "fmtNum", "_fmtTs", "_tf", "_diagIso", "ooSaidHtml",
    extract("ooLabelHtml", CORE) + "\n" + extract("_invTotalHtml", DIAG) + "\n" + extract("_renderSessionForensics", DIAG) + "\nreturn _renderSessionForensics;")(
    { OOI18N }, OOI18N, esc, (n) => n + " B", (n) => String(n), (x) => String(x), tf, (x) => x, () => "");
  const none = render({ inventory: { data_dir: "/d", totals: {}, unreadable: true } }, t);
  assert(none.includes(esc(t("not measured"))), "unlisted data folder not 'not measured': " + none);
  assert(!none.includes(">0 B") && !/ 0 B/.test(none), "unlisted data folder shows 0 B: " + none);
  const fresh = render({ inventory: { data_dir: "/d", totals: {}, note: "data dir does not exist (fresh install / custom OO_DATA_DIR)" } }, t);
  assert(!fresh.includes(esc(t("not measured"))) && fresh.includes("0 B"), "a fresh install's real 0 reads 'not measured': " + fresh);
  const part = render({ inventory: { data_dir: "/d", totals: { total_bytes: 30, db_bytes: 20, wal_bytes: 0, other_bytes: 10, unread_entries: 2 },
    entries: [{ name: "wiki_dumps", kind: "dir", bytes: 10, files: 1, unread_entries: 2 }] } }, t);
  assert(part.includes(esc(t("at least")) + " 30 B"), "partial total not 'at least': " + part);
  assert(part.includes(esc(t(PART))), "partial reason not visible: " + part);
  assert(part.includes(esc(t("at least")) + " 10 B · "), "partial entry not 'at least': " + part);
  const clean = render({ inventory: { data_dir: "/d", totals: { total_bytes: 30, db_bytes: 20, wal_bytes: 0, other_bytes: 10, unread_entries: 0 } } }, t);
  assert(!clean.includes(esc(t("at least"))) && clean.includes("30 B"), "clean inventory marked partial: " + clean);
}

// 5. A line refused before any byte was read (partial at 0) is still shown, and a null total reads "not measured".
{
  const { html, sb } = paint("en", { totals: { grand_total_bytes: 20, complete: false }, components: [
    { kind: "db", name: "database", bytes: 20 },
    { kind: "wiki_dumps", name: "wiki dumps", bytes: 0, partial: true, reason: PART }] });
  const row = rowFor(html, sb.t("Wikipedia dumps"));
  assert(row.includes("at least 0 B") && row.includes(esc(PART)), "a partial 0 line is hidden or unexplained: " + row);
  const nul = paint("en", { totals: { grand_total_bytes: null, complete: false }, components: [
    { kind: "db", name: "database", bytes: null, reason: "The data folder could not be read, so its size is not counted." }] }).html;
  assert(nul.includes('<b style="font-size:1.15em;color:var(--caveat)">not measured</b>'), "null total not 'not measured': " + nul);
  assert(!nul.includes("at least 0 B"), "null total reads 'at least 0 B': " + nul);
}

console.log("ok - storage footprint row 284 (5 groups)");
