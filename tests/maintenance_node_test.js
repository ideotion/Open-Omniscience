// The Maintenance section's renderers, run as REAL code (R196).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Most of what the panel must NOT do is what it is, so most checks are refusals:
//   * a dry run's URL says write=false and no flag can change that;
//   * unknown is its own row, never merged into the mismatch count;
//   * a tally key the job sent that the panel has no word for is shown as sent;
//   * zero is a measurement and is drawn; a signal the run did not ask for is "not measured";
//   * a sample title opens the LOCAL reader and the stored URL is text, never an outbound link;
//   * no verdict wording ("error rate", "bad", "spam") anywhere in what is drawn.

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
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}

const NAMES = ["_maintTallyLabel", "maintRunHtml", "maintTallyHtml", "maintSampleRowHtml", "maintSamplesHtml",
  "maintRawIdsHtml", "maintFurnitureHtml", "maintStartUrl"];
const src = extractConst("esc") + "\n" +
  "function fmtNum(v) { return String(v); }\n" +
  NAMES.map(extract).join("\n") + "\n" +
  "module.exports = {" + NAMES.join(", ") + "};";
const R = (() => { const m = { exports: {} }; new Function("module", "exports", src)(m, m.exports); return m.exports; })();

const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (h) => decode(String(h).replace(/[\u2068\u2069]/g, "").replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();
const noJunk = (h, what) => {
  for (const bad of ["undefined", "null", "NaN", "[object Object]"]) assert.ok(!visible(h).includes(bad), `${what} drew "${bad}": ${h}`);
};
const VERDICT = /\b(error rate|spam|junk|bad source|unreliable|score)\b/i;

// -- the start URL ---------------------------------------------------------------
for (const [a, b] of [[false, false], [true, false], [false, true], [true, true]]) {
  const u = R.maintStartUrl(a, b);
  assert.ok(u.startsWith("/api/quarantine/start?write=false"), u);
  assert.ok(!/write=true/.test(u), u);
  assert.strictEqual(u.includes("include_stubs=true"), a);
  assert.strictEqual(u.includes("include_host_mismatch=true"), b);
}

// -- the tally -------------------------------------------------------------------
const tally = { "host:unknown": 7, "host:mismatch": 3, scanned: 100, quarantined: 4, "reason:menu_stub": 4, "zzz:future": 0 };
const th = R.maintTallyHtml(tally, t, tf);
noJunk(th, "tally");
assert.ok(visible(th).includes("Site could not be read (not counted as different)"), "unknown has its own row");
assert.ok(visible(th).includes("Stored on a different site than its source"));
assert.ok(visible(th).includes("Rule: menu_stub"));
assert.ok(visible(th).includes("zzz:future"), "a key with no word is shown as the job sent it");
assert.ok(/zzz:future<\/td><td class="num">0</.test(th), "zero is a measurement and is drawn");
assert.ok(th.indexOf("Articles scanned") < th.indexOf("Stored on a different site"), "scanned leads");
assert.strictEqual(R.maintTallyHtml({}, t, tf), "");
assert.ok(!VERDICT.test(visible(th)));

// -- the run line ----------------------------------------------------------------
assert.ok(visible(R.maintRunHtml(null, t, tf)).includes("No run since this app started."));
assert.ok(visible(R.maintRunHtml({ state: "idle" }, t, tf)).includes("No run since"));
const rh = R.maintRunHtml({ state: "running", articles_total: 200, articles_done: 50, dry_run: true, include_stubs: true, include_host_mismatch: false }, t, tf);
noJunk(rh, "run");
assert.ok(visible(rh).includes("50 of 200 articles read"));
assert.ok(visible(rh).includes("dry run: nothing was written") && visible(rh).includes("stub pages counted"));
assert.ok(!visible(rh).includes("sites compared"));
const wh = R.maintRunHtml({ state: "done", dry_run: false }, t, tf);
assert.ok(visible(wh).includes("this run was started with writing on"), "a run that DID write says so");

// -- samples ---------------------------------------------------------------------
const sample = { signals: {
  host_mismatch: { candidates: 3, shown: 1, unknown: 7, note: "a fact about where it lives",
    rows: [{ id: 12, title: "T <b>x</b>", url: "https://a.example/p?x=1&y=2", already_marked: false, source_site: "a.example", article_site: "b.example" },
           { id: 13, present: false }] },
  host_confirmed: { candidates: null, shown: 0, rows: [] },
}, method: "spot-check, not an error rate", limit: 20 };
const sh = R.maintSamplesHtml(sample, t, tf);
noJunk(sh, "samples");
assert.ok(sh.includes('href="/api/articles/12/view"'), "the title opens the LOCAL reader");
assert.ok(!/href="https?:/.test(sh), "no outbound link from this page");
assert.ok(!sh.includes("<b>x</b>"), "a title is escaped");
assert.ok(visible(sh).includes("https://a.example/p?x=1&y=2"), "the stored URL is shown as text");
assert.ok(visible(sh).includes("1 shown of 3 candidates"));
assert.ok(visible(sh).includes("not measured in this run"), "a signal not asked for is not zero");
assert.ok(visible(sh).includes("Article 13 is no longer stored."));
assert.ok(visible(R.maintSamplesHtml({ signals: {} }, t, tf)).includes("No sample is held yet"));
const conf = R.maintSampleRowHtml({ id: 1, title: "x", url: "u", state: "confirmed", source_site: "a", article_site: "b" }, t, tf);
assert.ok(visible(conf).includes("confirmed by you"));

// -- reports ---------------------------------------------------------------------
assert.ok(visible(R.maintRawIdsHtml({ raw_id_sources: 0, rows: [] }, t, tf)).includes("No source is named by a bare identifier."));
const rid = R.maintRawIdsHtml({ raw_id_sources: 2, articles_in_shown: 9, rows: [{ source_id: 5, name: "Q11858063", domain: "d.example", articles: 9 }], method: "m" }, t, tf);
noJunk(rid, "raw ids");
assert.ok(visible(rid).includes("2 sources, 9 articles in the ones shown") && visible(rid).includes("Q11858063"));
const fu = R.maintFurnitureHtml({ source: { id: 5, name: "S" }, sampled: 10, articles_in_source: 40,
  candidates: [{ line: "Subscribe now", articles: 8, share: 0.8, known: true }, { line: "Column", articles: 4, share: 0.4, known: false }], method: "m" }, t, tf);
noJunk(fu, "furniture");
assert.ok(visible(fu).includes("S: 10 of 40 articles read") && visible(fu).includes("already stripped by the rules"));
assert.strictEqual((fu.match(/already stripped/g) || []).length, 1, "only the known line carries it");
assert.ok(visible(R.maintFurnitureHtml({ source: { id: 5 }, sampled: 3, articles_in_source: 3, candidates: [] }, t, tf)).includes("No repeated line reaches the threshold."));

// -- every string field is escaped (the XSS fuzz) ----------------------------------
const X = "<img src=x onerror=1>";
const fuzz = [
  R.maintRunHtml({ state: X, error: X, articles_total: 5, articles_done: 1, dry_run: true }, t, tf),
  R.maintTallyHtml({ [X]: 1, ["reason:" + X]: 2 }, t, tf),
  R.maintSamplesHtml({ signals: { [X]: { candidates: 1, shown: 1, note: X, unknown: 0,
    rows: [{ id: 1, title: X, url: X, source_site: X, article_site: X, state: "confirmed" }] } }, method: X }, t, tf),
  R.maintRawIdsHtml({ raw_id_sources: 1, articles_in_shown: 1, method: X, rows: [{ source_id: 1, name: X, domain: X, articles: 1 }] }, t, tf),
  R.maintFurnitureHtml({ source: { id: 1, name: X }, sampled: 1, articles_in_source: 1, method: X,
    candidates: [{ line: X, articles: 1, known: true }] }, t, tf),
];
fuzz.forEach((h, i) => assert.ok(!h.includes("<img"), `renderer ${i} let markup through: ${h}`));

console.log("maintenance: all checks passed");
