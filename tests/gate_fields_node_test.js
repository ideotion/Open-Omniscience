// The extraction-gate line, rendered as real code, at BOTH of its levels.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHY A BEHAVIOURAL SUITE AND NOT A SOURCE GREP. The 2026-09-05 field defect was that a
// distinction present in the payload died at a render boundary: `_gate_lines` published
// only the language-level rollup, so a check whose gate had refused `who` in every one of
// thirteen languages rendered "cleared: 7". Publishing the per-field verdicts fixes the
// FIRST boundary; this file exists because there is a SECOND one immediately after it, and
// shipping the payload without rendering it would have moved the silence one function
// along rather than ending it. A source assertion over `g.refused_fields` proves the
// identifier appears somewhere in the slice -- neutering the loop that draws it would keep
// that identifier in its own binding and the guard would stay green while the sentence
// vanished, which is the exact shape recorded against the `d.other` disclosure guard.
//
// So the REAL `_renderAiCheck` is extracted from the shipped engine and driven over real
// payload shapes, and every assertion is on the text an operator ends up reading.
//
// NEGATIVE-SPACE TWINS ARE MANDATORY HERE. A renderer that printed a refusal banner
// unconditionally would satisfy every "the refusal is visible" case while inventing a
// failure on a clean machine -- a fabricated red is exactly as dishonest as the fabricated
// all-clear being fixed. Both directions are asserted.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function functionSource(src, name) {
  const at = src.indexOf("function " + name + "(");
  if (at < 0) throw new Error("no function named " + name);
  // Balance the PARENTHESES first: a `{}` in a default parameter would otherwise
  // truncate the slice to the signature and every assertion over it would pass free.
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  depth = 0;
  for (let j = open; j < src.length; j++) {
    if (src[j] === "{") depth++;
    else if (src[j] === "}") { depth--; if (depth === 0) return src.slice(at, j + 1); }
  }
  throw new Error("unbalanced braces in " + name);
}

// `esc` is a const arrow, not a declaration, so it needs its own extractor: scan to the
// first `;` at depth zero rather than guessing at a line end (the body spans lines and
// carries braces of its own inside a string map).
function constArrow(src, name) {
  const at = src.indexOf("const " + name + " = ");
  if (at < 0) throw new Error("no const named " + name);
  let depth = 0;
  for (let i = at; i < src.length; i++) {
    const c = src[i];
    if ("([{".includes(c)) depth++;
    else if (")]}".includes(c)) depth--;
    else if (c === ";" && depth === 0) return src.slice(at, i + 1);
  }
  throw new Error("unterminated const " + name);
}

// --- the harness ------------------------------------------------------------------ //
// Only what the extracted function touches, and nothing stubbed that it is being tested
// on: `esc` and `_aiCheckLine` are the SHIPPED ones, so an escaping regression shows here.

let rendered = "";

const sandbox = {
  window: {},
  $: (id) => (id === "aicheck-result" ? { set innerHTML(v) { rendered = v; } } : null),
};

const src = [
  constArrow(APP, "esc"),
  functionSource(APP, "_aiCheckLine"),
  functionSource(APP, "_renderAiCheck"),
  "return { _renderAiCheck, esc };",
].join("\n");

const { _renderAiCheck } = new Function("window", "$", src)(sandbox.window, sandbox.$);

function render(gate) {
  rendered = "";
  _renderAiCheck({ reading: { backend: { available: false, reason: "x" }, extraction_gate: gate } });
  return rendered;
}

let passed = 0;
function check(name, fn) {
  fn();
  passed++;
  console.log("  ok  " + name);
}

// --- the field defect, at the render boundary -------------------------------------- //

check("a field refused inside a cleared language reaches the reader", () => {
  const html = render({
    cleared: ["hi"], refused: [], unmeasured: [],
    by_field: {
      who: { cleared: [], refused: ["hi"], unmeasured: [] },
      where: { cleared: ["hi"], refused: [], unmeasured: [] },
      when: { cleared: [], refused: [], unmeasured: ["hi"] },
    },
    refused_fields: [{ language: "hi", field: "who", reason: "who hallucination 1.0 above 0.5" }],
    partly_cleared: [{ language: "hi", not_cleared: ["who", "when"] }],
    field_counts: { cleared: 1, refused: 1, unmeasured: 1, total: 3 },
    note: "n",
  });
  assert.ok(html.includes("hi"), "the language is named");
  assert.ok(html.includes("who"), "the FIELD is named -- this is what was invisible");
  assert.ok(
    html.includes("hallucination 1.0 above 0.5"),
    "and the harness's own reason, which says WHICH floor it hit",
  );
});

check("the refusal is rendered as a caveat, not buried in a hint", () => {
  const html = render({
    cleared: ["hi"], refused: [], unmeasured: [],
    by_field: { who: { cleared: [], refused: ["hi"], unmeasured: [] } },
    refused_fields: [{ language: "hi", field: "who", reason: "r" }],
    partly_cleared: [], field_counts: { cleared: 0, refused: 1, unmeasured: 0, total: 1 },
  });
  assert.ok(
    /class="card-caveat"[^>]*>[^<]*hi[^<]*who/.test(html),
    "a refusal is a caveat by the house convention -- visible by default, never a toggle",
  );
});

check("a clean gate renders NO refusal — the negative-space twin", () => {
  const html = render({
    cleared: ["en"], refused: [], unmeasured: [],
    by_field: {
      who: { cleared: ["en"], refused: [], unmeasured: [] },
      where: { cleared: ["en"], refused: [], unmeasured: [] },
      when: { cleared: ["en"], refused: [], unmeasured: [] },
    },
    refused_fields: [], partly_cleared: [],
    field_counts: { cleared: 3, refused: 0, unmeasured: 0, total: 3 },
  });
  assert.ok(!html.includes("card-caveat"), "no refusal exists, so none may be drawn");
  assert.ok(!/only/i.test(html), "cleared for everything is not 'cleared for some fields only'");
  assert.ok(!/refused/.test(html), "and the word must not appear at all on a clean gate");
  // Counted PER FIELD, never summed into one number: 'who 1 cleared · where 1 cleared'
  // says which field, where a bare '3' would be the composite this report refuses.
  assert.ok(
    /who 1 cleared.*where 1 cleared.*when 1 cleared/.test(html),
    "the per-field counts are still shown, per field",
  );
});

check("a language cleared on one field says which fields it was not", () => {
  const html = render({
    cleared: ["zh"], refused: [], unmeasured: [],
    by_field: {
      who: { cleared: [], refused: [], unmeasured: ["zh"] },
      where: { cleared: ["zh"], refused: [], unmeasured: [] },
    },
    refused_fields: [],
    partly_cleared: [{ language: "zh", not_cleared: ["who", "when"] }],
    field_counts: { cleared: 1, refused: 0, unmeasured: 2, total: 3 },
  });
  assert.ok(/zh \(who, when\)/.test(html), "'cleared' over-reads without this");
});

check("the per-field counts carry every state that is non-empty", () => {
  const html = render({
    cleared: ["en"], refused: [], unmeasured: [],
    by_field: {
      who: { cleared: ["en"], refused: ["hi"], unmeasured: ["zh", "ja"] },
    },
    refused_fields: [{ language: "hi", field: "who", reason: "r" }],
    partly_cleared: [], field_counts: { cleared: 1, refused: 1, unmeasured: 2, total: 4 },
  });
  assert.ok(html.includes("1 cleared"), "cleared count");
  assert.ok(html.includes("1 refused"), "refused count");
  assert.ok(html.includes("2 unmeasured"), "unmeasured count -- never folded into refused");
});

check("an old report with no per-field verdicts says so instead of showing a gap", () => {
  const html = render({
    cleared: ["en"], refused: [], unmeasured: [],
    by_field: {}, refused_fields: [], partly_cleared: [],
    field_counts: { cleared: 0, refused: 0, unmeasured: 0, total: 0 },
    no_field_verdicts: { languages: ["en"], reason: "written before per-field gating existed" },
  });
  assert.ok(html.includes("written before per-field gating existed"));
  assert.ok(!html.includes("By field"), "no field block, because there are no field verdicts");
});

check("the language line still renders exactly as it did", () => {
  const html = render({
    cleared: ["en", "fr"], refused: ["ar"], unmeasured: ["ja"],
    by_field: {}, refused_fields: [], partly_cleared: [],
    field_counts: { cleared: 0, refused: 0, unmeasured: 0, total: 0 },
  });
  assert.ok(html.includes("en, fr"), "cleared languages");
  assert.ok(html.includes("ar"), "refused languages");
  assert.ok(html.includes("ja"), "unmeasured languages");
});

check("a gate that failed to read renders nothing rather than a false all-clear", () => {
  const html = render({ error: "ValueError: x" });
  assert.ok(!html.includes("Extraction gate"), "an unread gate is not a cleared one");
});

check("the reason is escaped, not injected", () => {
  const html = render({
    cleared: [], refused: [], unmeasured: [],
    by_field: { who: { cleared: [], refused: ["hi"], unmeasured: [] } },
    refused_fields: [{ language: "hi", field: "who", reason: "<img onerror=x>" }],
    partly_cleared: [], field_counts: { cleared: 0, refused: 1, unmeasured: 0, total: 1 },
  });
  assert.ok(!html.includes("<img"), "the harness reason is text, never markup");
  assert.ok(html.includes("&lt;img"));
});

console.log(passed + " passed");
