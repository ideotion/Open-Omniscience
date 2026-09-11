// P5's task-manager Workers section, run as REAL code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Both concurrency caps existed in the backend and NEITHER reached this window: the
// learned ceiling was rendered only inside the diagnostics report payload, the
// machine-floor worker cap only into a log line. So a pass running one worker of a
// configured fifty -- measured at 1.91 -> 0.45 articles/s over a slow transport, and
// persisting across restarts -- read here as "the app got slow". A payload nobody draws
// is the recorded machine-readable-answer-with-no-caller dead end, so the RENDER is part
// of the slice.
//
// What is guarded is a set of REFUSALS, and none is visible in a diff:
//   * no pass in flight -> NO "Fetching now" row, because 0 workers and no pass are
//     different facts and a "0" there is a number where there is no measurement;
//   * the block could not be read -> say so, never a quiet "nothing is capping it";
//   * nothing capping -> say THAT plainly, so the section is not only a bad-news panel;
//   * the two caps stay APART, because they have different remedies.
// A source-level assertion cannot tell those apart -- every one of them is "the function
// mentions c.learned_ceiling" -- so this runs the function.
//
// EXTRACTED from the shipped module rather than re-typed: a re-typed copy would pass
// while the real renderer was broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace: a `{}` in a default parameter would
  // otherwise truncate the slice to the signature alone (the recorded ooChart trap).
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

const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  extract("_concurrencyHtml") + "\n" +
  "module.exports = { _concurrencyHtml };";
const { _concurrencyHtml } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const t = (s) => s;                                   // the pre-i18n identity fallback
const row = (k, v) => `<ROW k=${k}|v=${v}>`;          // the real signature, made visible
const sect = (x) => `<SECT ${x}>`;
const render = (c, pg) => _concurrencyHtml(c, pg, t, row, sect);

// --- nothing capping: say so, rather than showing an empty panel ----------- //
{
  const out = render(
    { configured: 50, effective_max: 50, learned_ceiling: null, floor_cap: null,
      capped: false, method: "m" },
    { permits: 37 },
  );
  assert.ok(out.includes("<SECT Workers>"), out);
  assert.ok(out.includes("Fetching now") && out.includes("37"), "the live permits are not drawn: " + out);
  assert.ok(/nothing is holding it back/.test(out), "a healthy machine says nothing: " + out);
  assert.ok(!/pill warn/.test(out), "a healthy machine drew a warning: " + out);
}

// --- THE REFUSAL. No pass in flight -> no "Fetching now" row at all -------- //
for (const pg of [null, undefined, {}, { done: 3, total: 9 }]) {
  const out = render({ configured: 50, effective_max: 50, capped: false }, pg);
  assert.ok(!/Fetching now/.test(out),
    "a permit count was drawn with no pass in flight: " + JSON.stringify(pg) + " -> " + out);
  // ...and the rest of the section still renders, so the absence is one row, not a hole.
  assert.ok(out.includes("Configured maximum") && out.includes("50"), out);
}
// A REAL zero is a measurement and must still draw -- the guard is on absence, not on 0.
{
  const out = render({ configured: 50, effective_max: 50, capped: false }, { permits: 0 });
  assert.ok(/Fetching now/.test(out), "a measured 0 was suppressed as if absent: " + out);
}

// --- the learned ceiling: named, with its method on hover ------------------ //
{
  const out = render(
    { configured: 50, effective_max: 1, learned_ceiling: 1, floor_cap: null, capped: true,
      method: "measured by the collector's own back-off" },
    { permits: 1 },
  );
  assert.ok(/backed off under memory pressure/.test(out), out);
  // The hover is TRANSLATED, and the backend's own English `method` must NOT reach it:
  // renderMachineFloor set that precedent for the same payload, and a bubble is a
  // caveat surface, which the informed-consent rule puts in 12 locales.
  assert.ok(/title="This machine reduced its own worker count/.test(out),
    "the translated method is not offered on hover: " + out);
  assert.ok(!/measured by the collector/.test(out),
    "the backend's English method leaked into the UI: " + out);
  assert.ok(/cache of a measurement/.test(out),
    "the note that this is a cache, not a setting, is missing: " + out);
  assert.ok(!/below the memory floor/.test(out), "the two causes were blurred: " + out);
}

// --- the machine floor: a different cause, a different remedy -------------- //
{
  const out = render(
    { configured: 50, effective_max: 8, learned_ceiling: null, floor_cap: 8, capped: true,
      floor_reason: "this machine has 3924 MB of RAM", override_env: "OO_ALLOW_BIG_SCANS" },
    { permits: 8 },
  );
  assert.ok(/below the memory floor/.test(out), out);
  assert.ok(/OO_ALLOW_BIG_SCANS=1/.test(out), "the override is not offered: " + out);
  assert.ok(/title="A machine below the memory floor is held/.test(out),
    "the translated reason is not offered on hover: " + out);
  assert.ok(!/3924 MB of RAM/.test(out),
    "the backend's English reason leaked into the UI: " + out);
  assert.ok(!/backed off under memory pressure/.test(out), "the two causes were blurred: " + out);
  assert.ok(!/cache of a measurement/.test(out),
    "the learned-ceiling note leaked onto a floor-only cap: " + out);
}

// --- both at once is its own answer, not one of them silently winning ------ //
{
  const out = render(
    { configured: 50, effective_max: 1, learned_ceiling: 1, floor_cap: 8, capped: true,
      method: "m", floor_reason: "r" },
    { permits: 1 },
  );
  assert.ok(/both a measured memory back-off and the machine floor/.test(out), out);
}

// --- THE REFUSAL. Unreadable must say so, never read as "nothing is capping" //
{
  const out = render({ read: false, reason: "psutil is not installed" }, { permits: 4 });
  assert.ok(/could not be read/.test(out), out);
  assert.ok(/psutil is not installed/.test(out), "the reason is not carried: " + out);
  assert.ok(!/nothing is holding it back/.test(out),
    "an unreadable block rendered as a healthy one: " + out);
}

// --- an absent block draws nothing rather than an empty section ------------ //
for (const c of [null, undefined, "", 0]) {
  assert.strictEqual(render(c, { permits: 4 }), "", "an absent block drew a section: " + c);
}

console.log("concurrency panel: all checks passed");
