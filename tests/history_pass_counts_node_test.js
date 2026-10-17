// The History tab says how far an errored collection pass got, with the BASIS word on the row, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// All 30 recent runs in each of the two 2026-10-16 field bundles ended in a pool timeout, and the tab drew the same red row
// thirty times. The run record now carries ``pass_counts`` (src/scheduler/runner.py): sources processed, sources chosen and
// articles stored, plus a basis word that is also the reason the numbers are unknown when they are. These assertions pin what
// the page may and may not say about them:
//   * the basis word is TEXT ON THE ROW, not only in a hover (the row is read at a glance, the hover by the few who ask);
//   * a count the record does not carry reads "not reported" and NEVER 0 -- but a count that IS zero reads 0 (the two are
//     different facts: "processed nothing" and "does not know");
//   * a row with no ``pass_counts`` (written before the app kept them) and an ok row draw no counts line at all;
//   * the basis vocabulary is closed: a word the page does not know reads as "not reported", never as itself.
//
// Extracted from the shipped file; a re-typed copy would pass while the real one broke.

const assert = require("assert");
const TM = require("./app_source.js").pageSource("taskmanager.html");

// One top-level `function name(...) { ... }` out of the shipped file, source text and all.
function fullFunction(SRC, name) {
  const at = SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = SRC.indexOf("(", at), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "(") depth++;
    else if (SRC[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = SRC.indexOf("{", i);
  let d = 0, j = open;
  for (; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return SRC.slice(at, j);
}

const parts = ["esc", "t", "tf", "fmtNum", "passBasisText", "passBasisTitle", "passCountsLine"].map((n) => fullFunction(TM, n));
const src = "var window = globalThis.__win || {}; var OOI18N = window.OOI18N;\n" + parts.join("\n") + "\nmodule.exports = { passCountsLine, passBasisText, passBasisTitle };";

function load(win) {
  globalThis.__win = win || {};
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
}

const NNBSP = " ";
// Tags become a space (never nothing), so the text that was either side of a tag cannot join into new markup; runs of ASCII white space collapse (the narrow no-break space of a thousands group is kept).
const text = (html) => html.replace(/<[^>]*>/g, " ").replace(/[ \t\r\n]+/g, " ").replace(/^ | $/g, "");
const basisSpan = (html) => (html.match(/<span class="basis"[^>]*>([^<]*)<\/span>/) || [])[1];

// 1. a pass that raised, with counts: the basis word is on the row; the numbers are the record's.
{
  const { passCountsLine } = load();
  const h = passCountsLine({ sources_total: 20, sources_processed: 17, articles_stored: 34, basis: "pass_raised" });
  assert.strictEqual(text(h), "Sources processed: 17 of 20 · Articles stored: 34 · The pass stopped part-way");
  assert.strictEqual(basisSpan(h), "The pass stopped part-way", "the basis word is visible text on the row");
  assert.ok(/data-basis="pass_raised"/.test(h));
  assert.ok(/title="[^"]*every source whose worker had returned a result/.test(h), "the method is in the hover");
}
// 2. unknown reads "not reported" and never 0.
{
  const { passCountsLine } = load();
  const h = passCountsLine({ sources_total: null, sources_processed: null, articles_stored: null, basis: "not_reported" });
  assert.strictEqual(text(h), "Sources processed: not reported · Articles stored: not reported · The failure came before anything was counted");
  assert.ok(!/: 0\b/.test(text(h)), "an unknown count must not be drawn as 0");
  assert.ok(/title="[^"]*They are not zero/.test(h), "the hover says the figures are unknown, not zero");
}
// 3. a count that IS zero reads 0 -- "processed nothing" is a fact, "does not know" is another.
{
  const { passCountsLine } = load();
  const h = passCountsLine({ sources_total: 5, sources_processed: 0, articles_stored: 0, basis: "pass_raised" });
  assert.strictEqual(text(h), "Sources processed: 0 of 5 · Articles stored: 0 · The pass stopped part-way");
}
// 4. partial knowledge: each missing figure says so by itself; the total is dropped, not invented.
{
  const { passCountsLine } = load();
  assert.strictEqual(text(passCountsLine({ sources_total: null, sources_processed: 17, articles_stored: null, basis: "pass_raised" })),
    "Sources processed: 17 · Articles stored: not reported · The pass stopped part-way");
  assert.strictEqual(text(passCountsLine({ sources_total: 20, sources_processed: null, articles_stored: 3, basis: "pass_raised" })),
    "Sources processed: not reported · Articles stored: 3 · The pass stopped part-way");
}
// 5. a pass that returned and whose tail failed.
{
  const { passCountsLine } = load();
  const h = passCountsLine({ sources_total: 5, sources_processed: 5, articles_stored: 12, basis: "pass_returned" });
  assert.strictEqual(basisSpan(h), "The pass finished, a later step failed");
  assert.ok(/title="[^"]*ran to its end and a later step failed/.test(h));
}
// 6. the vocabulary is closed: another word is "not reported", and cannot inject markup.
{
  const { passCountsLine } = load();
  const h = passCountsLine({ sources_total: 1, sources_processed: 1, articles_stored: 1, basis: "<img src=x onerror=alert(1)>" });
  assert.strictEqual(basisSpan(h), "The failure came before anything was counted");
  assert.ok(/data-basis="not_reported"/.test(h) && !/<img/.test(h));
}
// 7. only whole non-negative numbers are counts; a string, NaN, a negative or a float-looking text is "not reported".
{
  const { passCountsLine } = load();
  const h = passCountsLine({ sources_total: "20", sources_processed: -1, articles_stored: NaN, basis: "pass_raised" });
  assert.strictEqual(text(h), "Sources processed: not reported · Articles stored: not reported · The pass stopped part-way");
}
// 8. thousands use the app's one formatter.
{
  const { passCountsLine } = load();
  const h = passCountsLine({ sources_total: 12345, sources_processed: 1234, articles_stored: 56789, basis: "pass_raised" });
  assert.ok(text(h).includes("1" + NNBSP + "234 of 12" + NNBSP + "345") && text(h).includes("56" + NNBSP + "789"), text(h));
}
// 9. no member (a row written before the app kept them) and non-objects draw nothing.
{
  const { passCountsLine } = load();
  for (const v of [undefined, null, 0, "", "pass_raised", []]) {
    if (Array.isArray(v)) { assert.ok(typeof passCountsLine(v) === "string"); continue; }
    assert.strictEqual(passCountsLine(v), "", "no counts line for " + JSON.stringify(v));
  }
}
// 10. every translated string goes through esc(): a language file cannot add markup.
{
  const { passCountsLine } = load({ OOI18N: { t: (s) => "<b>" + s + "</b>", tf: (s, v) => "<i>" + s.replace(/\{(\w+)\}/g, (m, k) => v[k]) + "</i>" } });
  const h = passCountsLine({ sources_total: 2, sources_processed: 1, articles_stored: 1, basis: "pass_raised" });
  assert.ok(!/<b>|<i>/.test(h), h);
  assert.ok(h.includes("&lt;b&gt;Sources processed&lt;/b&gt;"));
}
// 11. the wiring: an errored row carries the line, an ok row and a pre-feature errored row do not.
(async () => {
  const hist = fullFunction(TM, "renderHistory");
  const helpers = ["esc", "t", "tf", "fmtNum", "passBasisText", "passBasisTitle", "passCountsLine"].map((n) => fullFunction(TM, n)).join("\n");
  const wiring = "var window = {}; var OOI18N = undefined;\nvar el = { innerHTML: '' };\nfunction $(id) { return el; }\n" +
    "var RUNS = [];\nasync function api() { return { runs: RUNS }; }\n" +
    "function fmtRel(x) { return 'just now'; }\nfunction fmtLocal(x) { return String(x); }\nfunction fmtDur(x) { return x + ' s'; }\n" +
    helpers + "\nasync " + hist +
    "\nmodule.exports = { run: async (runs) => { RUNS = runs; await renderHistory(); return el.innerHTML; } };";
  const m = { exports: {} };
  new Function("module", "exports", wiring)(m, m.exports);
  const html = await m.exports.run([
    { ok: false, error: "TimeoutError", finished_at: "2026-10-16T10:00:00Z",
      pass_counts: { sources_total: 20, sources_processed: 17, articles_stored: 34, basis: "pass_raised" } },
    { ok: false, error: "TimeoutError", finished_at: "2026-10-16T09:00:00Z" },
    { ok: true, result: { articles_stored: 4, duration_s: 12 }, finished_at: "2026-10-16T08:00:00Z",
      pass_counts: { sources_total: 1, sources_processed: 1, articles_stored: 4, basis: "pass_returned" } },
  ]);
  const jobs = html.split('<div class="job">').slice(1);
  assert.strictEqual(jobs.length, 3);
  assert.ok(jobs[0].includes("Sources processed: 17 of 20") && jobs[0].includes('class="basis"'), "errored row with counts");
  assert.ok(!jobs[1].includes("Sources processed"), "an errored row written before the counts existed draws no counts line");
  assert.ok(!jobs[2].includes("Sources processed"), "an ok row never draws one: its result already says what it stored");
  console.log("history_pass_counts_node_test: ok");
})().catch((e) => { console.error(e); process.exit(1); });
