// The Agenda's election date-confidence pill/chip rendering, run as REAL code
// (audit P1-04, 2026-09-08).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// src/civic/elections.py computes a three-tier date-confidence system for every
// ELECTIONS-calendar event (scheduled / window / projected, plus a PASSED sub-state)
// and src/events/catalog.py serves it in every agenda response -- but the frontend
// never read date_confidence/date_caveat/projection at all, so every affected event
// collapsed into the same generic "approx · check source" pill regardless of tier.
// This is exactly the "a machine-readable answer with no caller" dead-end this repo
// has hit before, and a source-level grep for "date_confidence" cannot tell a real
// render from a mention in a comment -- so this drives the actual functions.
//
// EXTRACTED from the shipped module rather than re-typed: a re-typed copy would pass
// while the real renderer stayed broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace -- a `{}` default parameter would
  // otherwise truncate the slice to the signature alone (the recorded ooChart trap).
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found in the UI engine -- was it renamed?");
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

function objectLiteral(name) {
  const at = APP.indexOf("const " + name + " = {");
  assert.ok(at !== -1, name + " not found in the UI engine -- was it renamed?");
  const open = APP.indexOf("{", at);
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return APP.slice(at, j) + ";";
}

// --- static-source guard: never e.cadence, in ANY of the four functions ---------- //
// src/civic/elections.py deliberately never reads `cadence` (free prose, not a sourced
// recurrence rule); the UI must not reintroduce that fabrication risk one layer up.
for (const name of ["agElectionTier", "agConfPill", "agChipCls", "agChipTitleSuffix"]) {
  const body = extract(name);
  assert.ok(!/\.cadence\b/.test(body), name + " must never read e.cadence: " + body);
}

// --- load the REAL shipped code, with the real esc() and an absent OOI18N -------- //
// (OOI18N absent is the boot-time state, and it also exercises the identity T()
// fallback every one of these functions falls back to.)
const ctx = { window: {} };
new Function(
  "ctx",
  'const esc = (s) => (s == null ? "" : String(s).replace(/[&<>"\']/g, ' +
    'c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\\"":"&quot;","\'":"&#39;"}[c])));\n' +
    "const window = ctx.window;\n" +
    objectLiteral("_AG_TIER_META") + "\n" +
    extract("agElectionTier") + "\n" +
    extract("agConfPill") + "\n" +
    extract("agChipCls") + "\n" +
    extract("agChipTitleSuffix") + "\n" +
    "ctx.agElectionTier = agElectionTier; ctx.agConfPill = agConfPill; " +
    "ctx.agChipCls = agChipCls; ctx.agChipTitleSuffix = agChipTitleSuffix;"
)(ctx);
const { agElectionTier, agConfPill, agChipCls, agChipTitleSuffix } = ctx;

// The backend's own caveat constants (src/civic/elections.py) -- kept here as plain
// strings rather than re-derived, so a drift between the two sides shows up as a
// FAILING assertion instead of two copies quietly agreeing with each other.
const CAVEAT_SCHEDULED = "Date set by the electoral authority. Confirm at the official source.";
const CAVEAT_WINDOW = "The exact day is not yet set — only the legal window is known. " +
  "Confirm at the official source.";
const CAVEAT_PROJECTED = "Projected from a recurrence rule, not announced. Elections are " +
  "postponed, moved or cancelled — treat this as a prompt to check the official source, " +
  "never as a date.";
const CAVEAT_PASSED = "The projected date has passed and no result is recorded here — " +
  "status unknown. Check the official source.";

// --- agElectionTier -------------------------------------------------------------- //
{
  assert.strictEqual(agElectionTier({}), null, "no date_confidence at all -> null");
  assert.strictEqual(agElectionTier({ date_confidence: null }), null,
    "an explicit null (non-election, or the refusal-1 gap) -> null");
  assert.strictEqual(agElectionTier({ date_confidence: "scheduled" }), "scheduled");
  assert.strictEqual(agElectionTier({ date_confidence: "window" }), "window");
  assert.strictEqual(
    agElectionTier({ date_confidence: "projected", projection: { status: "upcoming" } }),
    "projected", "an upcoming projection stays the projected tier"
  );
  assert.strictEqual(
    agElectionTier({ date_confidence: "projected", projection: { status: "passed" } }),
    "passed", "a passed projection is its own, distinct sub-state"
  );
  // Defensive: a projected tier with no projection block at all (should not happen per
  // the backend's own contract, but the UI must not crash or silently mislabel it).
  assert.strictEqual(agElectionTier({ date_confidence: "projected" }), "projected");
}

// --- agConfPill: non-election fallback is BYTE-IDENTICAL to the old markup ------- //
{
  const confirmed = agConfPill({ confirmed: true, title: "A trade summit" });
  assert.strictEqual(confirmed,
    '<span class="pill ok" title="fixed annual date">confirmed</span>',
    "a non-election confirmed event must render EXACTLY as before P1-04: " + confirmed);

  const unconfirmed = agConfPill({ confirmed: false, title: "A trade summit" });
  assert.strictEqual(unconfirmed,
    '<span class="pill" title="follow the official source for the exact date">approx · check source</span>',
    "a non-election unconfirmed event must render EXACTLY as before P1-04: " + unconfirmed);

  const deduced = agConfPill({ deduced: true, confirmed: false, title: "x" });
  assert.ok(deduced.includes("pill warn"), "the deduced pill must be unaffected: " + deduced);
  assert.ok(deduced.includes("deduced · never confirmed"), deduced);
}

// --- agConfPill: the four election tiers render DISTINCT, correctly-captioned pills //
{
  const scheduled = agConfPill({ date_confidence: "scheduled", date_caveat: CAVEAT_SCHEDULED });
  assert.ok(scheduled.includes('class="pill ok"'), "scheduled must be the ok pill: " + scheduled);
  assert.ok(scheduled.includes(CAVEAT_SCHEDULED), "the backend's own caveat must be in the title: " + scheduled);

  const window_ = agConfPill({ date_confidence: "window", date_caveat: CAVEAT_WINDOW });
  assert.ok(window_.includes('class="pill tier-window"'), "window must be its own tier: " + window_);
  assert.ok(window_.includes(CAVEAT_WINDOW), window_);

  const projected = agConfPill({
    date_confidence: "projected", date_caveat: CAVEAT_PROJECTED,
    projection: { status: "upcoming" },
  });
  assert.ok(projected.includes('class="pill warn"'), "projected must be the warn pill: " + projected);
  assert.ok(projected.includes(CAVEAT_PROJECTED), projected);

  const passed = agConfPill({
    date_confidence: "projected", date_caveat: CAVEAT_PASSED,
    projection: { status: "passed" },
  });
  assert.ok(passed.includes('class="pill err"'),
    "a passed projection must read as more notable than an ordinary approx pill, never less: " + passed);
  assert.ok(passed.includes(CAVEAT_PASSED), passed);
  assert.ok(/[^\x00-\x7F]/.test(passed.split(">").pop().split("<")[0]) || passed.includes("passed"),
    "the passed pill must carry its own visible marker: " + passed);

  // The four must be pairwise distinct -- the whole point of the fix.
  const all = [scheduled, window_, projected, passed];
  assert.strictEqual(new Set(all).size, 4, "all four tiers must render distinctly: " + JSON.stringify(all));
}

// --- agChipCls: same tier-awareness on the small grid chips ---------------------- //
{
  assert.strictEqual(agChipCls({ confirmed: true }), "");
  assert.strictEqual(agChipCls({ confirmed: false }), "approx");
  assert.strictEqual(agChipCls({ date_confidence: "scheduled" }), "");
  assert.strictEqual(agChipCls({ date_confidence: "window" }), "tier-window");
  assert.strictEqual(
    agChipCls({ date_confidence: "projected", projection: { status: "upcoming" } }), "approx");
  const passedCls = agChipCls({ date_confidence: "projected", projection: { status: "passed" } });
  assert.strictEqual(passedCls, "leadpassed");
  assert.notStrictEqual(passedCls, "approx",
    "a passed projection's chip must not blend into the routine approx chip");
}

// --- agChipTitleSuffix: caveat on hover for a tier, the OLD suffix otherwise ----- //
{
  assert.strictEqual(agChipTitleSuffix({ confirmed: true }, ""), "");
  assert.strictEqual(
    agChipTitleSuffix({ confirmed: false }, " — exact date moves; check the official source"),
    " — exact date moves; check the official source",
    "a non-election chip's title suffix must be UNCHANGED by this fix");
  assert.strictEqual(agChipTitleSuffix({ confirmed: false }), "",
    "a call site that never had a suffix (Year/Month-card) must still get none for a non-election event");

  const suf = agChipTitleSuffix({ date_confidence: "scheduled", date_caveat: CAVEAT_SCHEDULED });
  assert.ok(suf.includes(CAVEAT_SCHEDULED), "an election chip must surface the real caveat: " + suf);
  assert.ok(suf.startsWith(" — "), suf);
}

console.log("all assertions passed");
