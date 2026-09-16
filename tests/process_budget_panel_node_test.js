// S04-13 S1's task-manager budget panel, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// A payload nobody draws is the recorded "machine-readable answer with no caller"
// dead end, so the RENDER is part of this slice rather than a follow-up. There is
// no browser in this lane, so it is driven in node.
//
// WHAT IS BEING GUARDED IS A SET OF REFUSALS, and not one of them is visible in a
// diff -- every pair below is one character apart in source and opposite on screen:
//
//   * no pass running draws NOTHING, where a budget row over an idle app would be
//     a measurement of nothing;
//   * an UNMEASURABLE download draws no row, where a "0" claims it is contributing
//     nothing (a fact nobody measured);
//   * a MEASURED ZERO would have to draw, because that is a real observation --
//     the distinction `b.downloads_kbps != null` versus a truthiness test, which
//     no source-level assertion can tell apart;
//   * a PARTIAL total says so in words.
//
// The prose is also checked to come from the CLIENT's keyed templates rather than
// the server's own `budget_reason`: a backend reason field is English, and a caveat
// surface ships x12.
//
// EXTRACTED from the shipped module rather than re-typed: a re-typed copy would
// pass while the real renderer was broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace: a `{}` in a default parameter
  // would otherwise truncate the slice to the signature alone.
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

// `window` is defined so BOTH halves of `window.OOI18N && window.OOI18N.tf`
// resolve: a sandbox defining only the property raises ReferenceError on a bare
// global read, which is the recorded node-harness trap.
const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "var window = {};\n" +
  extract("_budgetHtml") + "\n" +
  "module.exports = { _budgetHtml };";
const { _budgetHtml } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const act = (budget) => ({ collect_perf: budget ? { process_budget: budget } : {} });

// --- nothing to say draws nothing ------------------------------------------ //
{
  assert.strictEqual(_budgetHtml(null), "", "a missing payload drew something");
  assert.strictEqual(_budgetHtml({}), "", "an empty payload drew something");
  assert.strictEqual(_budgetHtml(act(null)), "",
    "a payload with no process_budget drew a budget panel");
}

// --- an ordinary under-budget pass ----------------------------------------- //
{
  const out = _budgetHtml(act({
    mode: "target", budget_kbps: 500, process_kbps: 180.5, collector_kbps: 180.5,
    downloads_kbps: null, downloads_measured: false, downloads_idle: true,
    partial: false, unmeasured: [],
  }));
  assert.ok(out.includes("500 kbit/s"), "the budget is not drawn: " + out);
  assert.ok(out.includes("180.5 kbit/s"), "the measured rate is not drawn: " + out);
  assert.ok(!/lower bound/.test(out),
    "a complete total claimed to be a lower bound: " + out);
  assert.ok(!/of which/.test(out),
    "an idle download channel drew a row: " + out);
}

// --- THE REFUSAL. An unmeasurable download draws no row, and never a 0 ------ //
{
  const out = _budgetHtml(act({
    mode: "target", budget_kbps: 500, process_kbps: 100, collector_kbps: 100,
    downloads_kbps: null, downloads_measured: false, downloads_idle: false,
    partial: true, unmeasured: [{ key: "oo-dump-en", reason: "no bytes observed yet" }],
  }));
  assert.ok(!/of which/.test(out),
    "an unmeasurable download drew a row: " + out);
  assert.ok(!/\b0 kbit\/s/.test(out),
    "an unmeasurable download was drawn as 0 -- that claims it is contributing " +
    "nothing, which is not what was measured: " + out);
  assert.ok(/lower bound/.test(out),
    "a partial total did not say it is a lower bound: " + out);
}

// --- THE TWIN. A MEASURED zero is a real observation and MUST draw ---------- //
{
  const out = _budgetHtml(act({
    mode: "target", budget_kbps: 500, process_kbps: 40, collector_kbps: 40,
    downloads_kbps: 0, downloads_measured: true, downloads_idle: false,
    partial: false, unmeasured: [],
  }));
  assert.ok(/of which/.test(out),
    "a MEASURED zero was suppressed -- 'we measured it and it is 0' and 'we could " +
    "not measure it' are opposite facts, and only this case tells a null check " +
    "from a truthiness test: " + out);
  assert.ok(/0 kbit\/s/.test(out), out);
}

// --- maximum mode has no ceiling, and it is never rendered as a number ------ //
{
  const out = _budgetHtml(act({
    mode: "maximum", budget_kbps: null, process_kbps: 9000, collector_kbps: 9000,
    downloads_kbps: null, downloads_measured: false, downloads_idle: true,
    partial: false, unmeasured: [], over_budget: null,
  }));
  assert.ok(/no ceiling/.test(out), "maximum mode did not say it has no ceiling: " + out);
  assert.ok(!/null|undefined|NaN/.test(out), "a null budget leaked into the DOM: " + out);
  assert.ok(!/\b0 kbit\/s/.test(out),
    "'no ceiling' rendered as a 0 budget -- the opposite instruction: " + out);
}

// --- over budget BY A DOWNLOAD says cutting collection cannot help ---------- //
{
  const out = _budgetHtml(act({
    mode: "target", budget_kbps: 500, process_kbps: 4020, collector_kbps: 20,
    downloads_kbps: 4000, downloads_measured: true, downloads_idle: false,
    partial: false, unmeasured: [], over_budget: true, governed_kbps: 20,
  }));
  assert.ok(/cannot recover it/.test(out),
    "the panel did not say that reducing collection cannot recover a download's " +
    "share -- an operator watching collection fall to one worker would read it as " +
    "a broken collector: " + out);
}

// --- the prose is the CLIENT's, never the server's English reason ----------- //
{
  const out = _budgetHtml(act({
    mode: "target", budget_kbps: 500, process_kbps: 100, collector_kbps: 100,
    downloads_kbps: null, downloads_measured: false, downloads_idle: true,
    partial: false, unmeasured: [],
    budget_reason: "SERVER_SIDE_ENGLISH_SENTINEL",
    method: "METHOD_SENTINEL",
  }));
  assert.ok(!/SERVER_SIDE_ENGLISH_SENTINEL/.test(out),
    "the server's own budget_reason was piped into the DOM; it is English and a " +
    "caveat surface ships x12: " + out);
  assert.ok(!/METHOD_SENTINEL/.test(out),
    "the server's method string was piped into the DOM: " + out);
}

// --- every value is escaped ------------------------------------------------ //
{
  const out = _budgetHtml(act({
    mode: "target", budget_kbps: "<script>x</script>", process_kbps: 1,
    collector_kbps: 1, downloads_kbps: null, downloads_measured: false,
    downloads_idle: true, partial: false, unmeasured: [],
  }));
  assert.ok(!out.includes("<script>"), "a payload value reached the DOM unescaped: " + out);
}

console.log("process_budget_panel_node_test.js: all assertions passed");
