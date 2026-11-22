// Row 322: four places that printed a raw token or an English constant inside translated UI, now worded through t().
// Run against the real functions; every unknown token is shown as sent.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

"use strict";
const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", at));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j);
}
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found");
  return APP.slice(at, APP.indexOf("};\n", at) + 2);
}
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
const ooLabelHtml = (l, v) => l + " :: " + v;
const src = [extract("custodyAnchorResultHtml"), extract("batchIngestStatusWords"), extractConst("_AI_NOT_RUN_WORDS"),
  extract("_aiNotRunHereLine"), extract("_aiSweepNote"), extract("_aiLatestNote"), extract("_aiTriageVerdictWords")].join("\n")
  + "\nreturn {custodyAnchorResultHtml, batchIngestStatusWords, _AI_NOT_RUN_WORDS, _aiNotRunHereLine, _aiSweepNote, _aiLatestNote, _aiTriageVerdictWords};";
const R = new Function("esc", "ooLabelHtml", "window", src)(esc, ooLabelHtml, {});
const seen = new Set();
const t = (s) => { seen.add(s); return "T[" + s + "]"; };
const tf = (s, v) => { seen.add(s); return "T[" + String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m) + "]"; };
// Tags are dropped by a character walk, not a regex replace (CodeQL reads that as an
// incomplete sanitizer; the same helper as rewalk_b29_node_test.js). Entities stay as written.
const text = (h) => {
  let out = "", inTag = false;
  for (const ch of String(h)) {
    if (ch === "<") inTag = true;
    else if (ch === ">" && inTag) inTag = false;
    else if (!inTag) out += ch;
  }
  return out;
};

// 1. custody anchor: the caveat in words at full strength, the provider as data, an unknown provider's detail as data
const local = R.custodyAnchorResultHtml({ provider: "local", detail: "Recorded in the local anchor book…" }, t, tf);
assert.ok(local.includes('<code dir="ltr">local</code>'), local);
assert.ok(text(local).includes("it is NOT independent third-party proof."), local);
assert.ok(!local.includes("Recorded in the local anchor book…"), "the English receipt detail was shown as the caveat");
const ots = R.custodyAnchorResultHtml({ provider: "opentimestamps", detail: "x", detail_vars: { calendars_reached: 2, calendars_total: 3 } }, t, tf);
assert.ok(text(ots).includes("T[Submitted to 2 of 3 OpenTimestamps calendars.]"), ots);
assert.ok(text(ots).includes("this is not a proof of time"), ots);
const otsNoVars = R.custodyAnchorResultHtml({ provider: "opentimestamps", detail: "x" }, t, tf);
assert.ok(!otsNoVars.includes("Submitted to") && otsNoVars.includes("not a proof of time"), otsNoVars);
const other = R.custodyAnchorResultHtml({ provider: "<b>chain</b>", detail: "a newer provider's words" }, t, tf);
assert.ok(other.includes('&lt;b&gt;chain&lt;/b&gt;') && other.includes('T[Receipt] :: <code dir="ltr">a newer provider&#39;s words</code>'), other);
assert.ok(!/<b>chain/.test(other), "a provider name was not escaped");

// 2. batch ingest status words
assert.strictEqual(R.batchIngestStatusWords("not_found", t), "T[Source not found]");
assert.strictEqual(R.batchIngestStatusWords("no_feed", t), "T[No feed to fetch]");
assert.strictEqual(R.batchIngestStatusWords("error", t), "T[Fetch failed]");
assert.strictEqual(R.batchIngestStatusWords("brand_new", t), "brand_new");
assert.strictEqual(R.batchIngestStatusWords(undefined, t), "");

// 3. AI check: known ids worded, an unknown entry as sent, an inherited name is not an id
const bench = R._aiNotRunHereLine({ id: "model-bench", name: "x", why: "y", where: "z" }, t);
assert.ok(bench.startsWith("T[Model bench] — T[It runs the frozen input set"), bench);
assert.ok(R._aiNotRunHereLine({ id: "anchor-grading" }, t).includes("T[Settings → Advanced → AI diagnostics → grade a sitting]"));
assert.strictEqual(R._aiNotRunHereLine({ id: "later", name: "N", why: "W", where: "H" }, t), "N — W (H)");
assert.strictEqual(R._aiNotRunHereLine({ id: "toString", name: "N", why: "W", where: "H" }, t), "N — W (H)");
assert.strictEqual(R._aiNotRunHereLine({ name: "<i>", why: "", where: "" }, t), "&lt;i&gt; —  ()");

// 4. AI activity notes and verdicts
assert.strictEqual(R._aiSweepNote({ note: "x", note_code: "no-run-log" }, t, tf), "T[No run log yet: this sweep has not run on this machine.]");
assert.strictEqual(R._aiSweepNote({ note: "x", note_code: "not-run" }, t, tf), "T[This sweep has not run on this machine.]");
assert.strictEqual(R._aiSweepNote({ note_code: "translation-progress", note_vars: { lang: "fr", n: 12, unit: "keywords" } }, t, tf),
  "T[Translating into fr. Keywords walked this pass: 12.]");
assert.strictEqual(R._aiSweepNote({ note_code: "translation-progress", note_vars: { lang: "de", n: 3, unit: "articles" } }, t, tf),
  "T[Translating into de. Articles walked this pass: 3.]");
assert.strictEqual(R._aiSweepNote({ note: "into xx, 4 pages walked", note_code: "translation-progress", note_vars: { unit: "pages" } }, t, tf),
  "into xx, 4 pages walked", "an unknown unit keeps the English record");
assert.strictEqual(R._aiSweepNote({ note: "an older server's words" }, t, tf), "an older server's words");
assert.strictEqual(R._aiSweepNote({ note: "into None, 0 keywords walked this pass", note_code: "translation-progress",
  note_vars: { lang: null, n: 0, unit: "keywords" } }, t, tf), "into None, 0 keywords walked this pass", "never 'Translating into null'");
assert.ok(R._aiLatestNote({ latest_note_code: "perception-stored" }, t).startsWith("T[The extracted names"));
assert.ok(R._aiLatestNote({ latest_note_code: "translation-stored" }, t).startsWith("T[Its answers are stored as tentative"));
assert.strictEqual(R._aiLatestNote({ latest_note: "older words" }, t), "older words");
for (const v of ["junk", "content", "unsure"]) assert.strictEqual(R._aiTriageVerdictWords(v, t), "T[" + v + "]");
assert.strictEqual(R._aiTriageVerdictWords("maybe-later", t), "maybe-later");

// every string these maps use reached the translator, so it must be a locale key (checked from Python)
console.log(JSON.stringify([...seen]));
console.log("raw constants row 322: all checks passed");
