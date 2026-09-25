// The Wikipedia-stream toggle's painter, driven for real.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Q702's NOTE (ruled 2026-09-15) asks for a top-bar toggle with stop / start / halt /
// resume. What a source-text assertion can prove about that is almost nothing: the
// recorded lesson is that `assert_present(source, "s.tags")` stayed green against a
// mutant that read the field and threw it away. So this EXTRACTS the shipped function
// and EXECUTES it against a fake DOM, and asserts what the button ends up carrying.
//
// EXTRACTED, never re-typed: a re-typed copy passes while the real painter is broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace -- a `{}` in a default parameter would
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

// The state vocabulary, EXTRACTED from the shipped module rather than re-typed --
// a re-typed list would let this suite pass while the real one said something else.
const STATES_DECL = (function () {
  const m = /const WIKI_LANE_STATES = \[[^\]]+\];/.exec(APP);
  assert.ok(m, "the painter no longer declares WIKI_LANE_STATES");
  return m[0];
})();

// -- a fake DOM, just enough ------------------------------------------------- //
function makeButton() {
  const el = {
    _cls: new Set(), _attrs: {}, title: "",
    classList: {
      toggle(name, on) { if (on) el._cls.add(name); else el._cls.delete(name); },
      contains(n) { return el._cls.has(n); },
    },
    setAttribute(k, v) { el._attrs[k] = v; },
    getAttribute(k) { return Object.prototype.hasOwnProperty.call(el._attrs, k) ? el._attrs[k] : null; },
  };
  return el;
}

function run(state, translate, active, why) {
  const btn = makeButton();
  const mark = makeButton();
  const sandbox = {
    $: (id) => (id === "wiki-toggle" ? btn : null),
    document: { getElementById: (id) => (id === "wiki-mark" ? mark : null) },
    window: translate ? { OOI18N: { t: translate } } : {},
    _wikiLaneState: null,
  };
  // ``OOI18N`` is passed as a BARE name as well as on ``window``, because the shipped
  // line reads ``(window.OOI18N && OOI18N.t)`` -- in a browser those are the same
  // object, and a sandbox that supplied only the ``window`` half would throw on the
  // very expression under test. (``_paintRateMode`` beside it has the same shape.)
  // ``active`` DEFAULTS TO TRUE here, so every assertion below is about the state
  // machine rather than about the temporary fact that nothing collects yet. The
  // chosen-but-idle case has its own block at the end, where it is the subject.
  // ``_wikiLaneWhy`` is the reason the status last gave (S04-08's S5); null unless a
  // test is about it.
  const body = STATES_DECL + "\nlet _wikiLaneState = null; let _wikiLaneActive = false;\n"
    + "let _wikiLaneWhy = WHY;\n"
    + extract("_paintWikiLane")
    + "\n_paintWikiLane(STATE, ACTIVE); return {btn: BTN, mark: MARK, state: _wikiLaneState, active: _wikiLaneActive};";
  const fn = new Function("$", "document", "window", "OOI18N", "console", "BTN", "MARK", "STATE", "ACTIVE", "WHY", body);
  return fn(sandbox.$, sandbox.document, sandbox.window, sandbox.window.OOI18N,
            {warn() {}}, btn, mark, state, active === undefined ? true : active,
            why || {reason: null, waitingOn: null});
}

// -- invariant #14's grammar: FILL is the state, never an action glyph -------- //
{
  const r = run("running");
  assert.strictEqual(r.mark.getAttribute("fill"), "currentColor",
    "running must FILL the mark -- the state lives in the fill, not in a swapped glyph");
  assert.ok(r.btn.classList.contains("wiki-live"));
  assert.strictEqual(r.btn.getAttribute("aria-pressed"), "true");
}
{
  const r = run("halted");
  assert.strictEqual(r.mark.getAttribute("fill"), "none");
  assert.ok(r.btn.classList.contains("wiki-halted"));
  assert.ok(!r.btn.classList.contains("wiki-live"));
  assert.strictEqual(r.btn.getAttribute("aria-pressed"), "false");
}
{
  const r = run("stopped");
  assert.strictEqual(r.mark.getAttribute("fill"), "none");
  assert.ok(!r.btn.classList.contains("wiki-live"), "stopped must not read as live");
  assert.ok(!r.btn.classList.contains("wiki-halted"), "stopped and halted are different states");
}

// -- the three states are DISTINGUISHABLE to a reader ------------------------ //
{
  const titles = ["running", "halted", "stopped"].map((s) => run(s).btn.title);
  assert.strictEqual(new Set(titles).size, 3,
    "two states rendered the same hover -- an operator cannot tell them apart");
}

// -- hosts are compared as whole TOKENS, never as substrings ----------------- //
//
// CodeQL flagged `indexOf("wikimedia.org")` as incomplete URL substring
// sanitization, which is the right shape to complain about even though this is an
// assertion and not a sanitizer. THE DEFECT UNDERNEATH IT IS THE REAL ONE:
// `"...stream.wikimedia.org...".indexOf("wikimedia.org")` succeeds, so the assertion
// that the PAGEVIEWS host appears in the hover was being satisfied by the STREAM
// host and tested nothing at all. Deleting the pageviews host from the sentence
// would have left it green.
//
// Extracting host-shaped TOKENS and comparing sets fixes both: the pattern CodeQL
// objects to is gone, and each host is now asserted on its own.
function hostsIn(text) {
  // Trailing `-`/`.` trimmed: a host token cannot end in one, and some locales attach
  // a case suffix to a Latin word with a hyphen (Bengali writes
  // `stream.wikimedia.org-\u098f\u09b0`, the shape bn.json already uses for `GB`), so a greedy
  // class reports a mangled host where the host is verbatim and correct.
  const raw = String(text).match(/[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+/g) || [];
  return new Set(raw.map((h) => h.replace(/[-.]+$/, "")));
}

// -- a hover is a consent surface: it names what the lane CONTACTS ------------ //
["running", "halted", "stopped"].forEach((s) => {
  const hosts = hostsIn(run(s).btn.title);
  assert.ok(hosts.has("stream.wikimedia.org"),
    s + ": the stream host is not named in the hover (invariant #17 + informed consent)");
  assert.ok(hosts.has("wikimedia.org"),
    s + ": the pageviews host is not named in the hover -- and note this is a WHOLE-TOKEN "
      + "check, so stream.wikimedia.org does not satisfy it");
});

// -- a control that renders CLAIMS its capability: every state names its action //
["running", "halted", "stopped"].forEach((s) => {
  const aria = run(s).btn.getAttribute("aria-label");
  assert.ok(aria && aria.length > 0, s + ": no aria-label -- the button promises nothing");
  assert.ok(/Pause|Resume|Start/.test(aria), s + ": the label does not name the action: " + aria);
});

// -- EVERY sentence goes through t(), so the surface can ship x12 ------------- //
{
  // A translator that uppercases proves the string PASSED THROUGH t() -- which a
  // source grep for `t9(` cannot prove, because a grep sees a mention and not a call.
  const seen = [];
  const shout = (s) => { seen.push(s); return s.toUpperCase(); };
  const r = run("running", shout);
  assert.ok(seen.length >= 4, "too few t() calls: some of this hover is hardcoded English");
  const untouched = r.btn.title.split("\n").filter((line) => line && line !== line.toUpperCase());
  assert.deepStrictEqual(untouched, [],
    "part of the hover never reached t() and would render English in eleven locales: "
    + JSON.stringify(untouched));
}

// -- the host literals are NOT translated ------------------------------------ //
{
  // The hosts must survive a translator verbatim: a localized hostname is an
  // unreachable address printed on a consent surface.
  const r = run("running", (s) => s.replace(/wikimedia/g, "WIKIMEDIA-TRANSLATED"));
  assert.ok(!hostsIn(r.btn.title).has("stream.wikimedia.org"),
    "sanity: this probe is meant to mangle the host, so the assertions above mean something");
}

console.log("wiki_toggle_node_test: ok");

// -- an unknown state is REFUSED, not drawn as "stopped" --------------------- //
{
  // The failure direction this control must not have: telling an operator the lane
  // is off when it is something the build does not recognise.
  const first = run("running");
  const btn = first.btn, mark = first.mark;
  const before = {title: btn.title, fill: mark.getAttribute("fill"),
                  live: btn.classList.contains("wiki-live")};
  const body = STATES_DECL + "\nlet _wikiLaneState = null; let _wikiLaneActive = false;\n"
    + "let _wikiLaneWhy = {reason: null, waitingOn: null};\n"
    + extract("_paintWikiLane")
    + "\n_paintWikiLane('running', true); _paintWikiLane('draining', true);"
    + "\nreturn {btn: BTN, mark: MARK, state: _wikiLaneState};";
  const fn = new Function("$", "document", "window", "OOI18N", "console", "BTN", "MARK", body);
  const b2 = makeButton(), m2 = makeButton();
  const warned = [];
  const out = fn((id) => (id === "wiki-toggle" ? b2 : null),
    {getElementById: (id) => (id === "wiki-mark" ? m2 : null)}, {}, undefined,
    {warn: (...a) => warned.push(a.join(" "))}, b2, m2);
  assert.strictEqual(out.state, "running",
    "an unrecognised state overwrote the last state we actually knew");
  assert.strictEqual(m2.getAttribute("fill"), before.fill,
    "the button was repainted for a state the build does not know");
  assert.ok(warned.length === 1 && /unknown state/.test(warned[0]),
    "the refusal was silent -- nothing anywhere says the UI and the backend disagree");
}

console.log("wiki_toggle_node_test: unknown-state refusal ok");

// -- CHOSEN is not HAPPENING, and the surface must not blur them -------------- //
{
  // Nothing consumes `wiki_lane_state` on this build. A toggle reading only the
  // stored state would say "every edit arrives as it happens" while nothing was
  // connected -- a control claiming a capability it does not have.
  const live = run("running", null, true);
  const chosen = run("running", null, false);
  assert.notStrictEqual(live.btn.title, chosen.btn.title,
    "a lane that is merely CHOSEN reads identically to one that is collecting");
  assert.ok(live.btn.classList.contains("wiki-live"));
  assert.ok(!chosen.btn.classList.contains("wiki-live"),
    "the breathing accent means 'happening now'; over an idle lane the picture "
    + "contradicts the words");
  assert.ok(chosen.btn.classList.contains("wiki-chosen"),
    "the chosen state has no presentation of its own, so it falls back to looking off");
  // The FILL still carries the CHOICE, which is what invariant #14's grammar is about.
  assert.strictEqual(chosen.mark.getAttribute("fill"), "currentColor",
    "the chosen state must still read as chosen: the FILL is the state");
}

console.log("wiki_toggle_node_test: chosen-vs-happening ok");

// -- a WAITING stream says so, and on what (S04-08's S5, Q1014) --------------- //
{
  // The status reports `transport-waiting` while the stream's connections keep
  // failing -- a refused or dead proxy. loadWikiLane then paints it as NOT active
  // (nothing is arriving), and the hover must name the failure rather than read as
  // "chosen, but not running", which would send an operator looking in the wrong place.
  const failure = "TransportUnavailable: protected fetch mode is on but no proxy is configured";
  const waiting = run("running", null, false, {reason: "transport-waiting", waitingOn: failure});
  assert.ok(waiting.btn.title.includes(failure),
    "the hover does not carry the failure the stream is waiting on: " + waiting.btn.title);
  assert.ok(/never falls back to a direct connection/.test(waiting.btn.title),
    "the waiting hover must say the lane does not go direct in the meantime");
  assert.ok(!waiting.btn.classList.contains("wiki-live"),
    "a waiting stream delivers nothing, so it must not breathe as live");
  const idle = run("running", null, false);
  assert.notStrictEqual(waiting.btn.title, idle.btn.title,
    "waiting on a failing connection reads the same as not running at all");
  // The failure is verbatim (an error message), the sentence around it translated.
  // Placeholders survive translation (the i18n gates hold every locale to that), so
  // the probe keeps `{why}` as it is and shouts the words around it.
  const shout = (x) => x.toUpperCase().replace(/\{WHY\}/g, "{why}");
  const t = run("running", shout, false, {reason: "transport-waiting", waitingOn: failure}).btn.title;
  assert.ok(t.includes(failure), "the failure text went through the translator");
  assert.ok(t.includes("NEVER FALLS BACK"), "the sentence around the failure is not translated");
  // A wait with no reported failure still says it is waiting, and names the absence.
  const bare = run("running", null, false, {reason: "transport-waiting", waitingOn: null});
  assert.ok(/no reason was reported/.test(bare.btn.title), bare.btn.title);
}
{
  // Airplane mode is THIS APP holding the lane (invariant #14e's corollary), and the
  // hover names it as such rather than as a lane that simply is not running.
  const plane = run("running", null, false, {reason: "airplane-mode", waitingOn: null});
  assert.ok(/airplane mode/.test(plane.btn.title), plane.btn.title);
  const idle = run("running", null, false, {reason: "not-started", waitingOn: null});
  assert.ok(!/airplane mode/.test(idle.btn.title), idle.btn.title);
  assert.ok(!/on this build/.test(idle.btn.title),
    "the retired 'nothing is collecting yet on this build' came back: a collector exists");
}

console.log("wiki_toggle_node_test: waiting-reason ok");
