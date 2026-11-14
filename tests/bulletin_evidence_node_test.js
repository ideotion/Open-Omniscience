// The Bulletin's evidence-archive Check / Write pair and narration Stop, run as REAL code
// (Lane M's routes list: POST /api/bulletin/evidence/plan, /evidence/build and
// /narration/stop had no button).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What is guarded is BEHAVIOUR a source grep cannot see: Write stays off until a PASSING
// Check for the SAME period and folder; a click after either changed writes nothing; a
// reply from an earlier Check never paints over a later one; the plaintext caveat is drawn
// with the numbers; and Stop shows only while a run is watched. EXTRACTED from the shipped
// module, never re-typed.

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
  const head = APP.slice(Math.max(0, at - 6), at);
  return (head.endsWith("async ") ? "async " : "") + APP.slice(at, j);
}

const NAMES = ["_bulT", "_bulTf", "_bulSay", "_bulClearMsg", "_bulPaintMsg", "_bulPrivacyHtml",
  "_bulEvKey", "_bulEvReady", "bulletinEvidencePlan", "bulletinEvidenceBuild", "_bulPaintEvidence",
  "_bulNarrateButtons"];
const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "var _bulMsgs = {}; let _bulEvPlan = null, _bulEvBuilt = null, _bulEvSeq = 0, _bulEvBuilding = false; let _bulNarrating = false, _bulStopAsked = false;\n" +
  NAMES.map(extract).join("\n") + "\n" +
  "return { " + NAMES.join(", ") + ", setNarrating: (v) => { _bulNarrating = v; }, setStopAsked: (v) => { _bulStopAsked = v; } };";

const els = {};
function el(id, extra) { els[id] = Object.assign({id, value: "", textContent: "", innerHTML: "", disabled: false, hidden: false}, extra || {}); return els[id]; }
el("bul-cadence", {value: "weekly"}); el("bul-ev-dest"); el("bul-ev-msg"); el("bul-ev-out");
el("bul-ev-build", {disabled: true}); el("bul-ev-plan"); el("bul-narrate-run"); el("bul-narrate-stop", {hidden: true});
const calls = [];
let pending = [];
function api(url, opts) {
  calls.push({url, method: (opts || {}).method});
  return new Promise((res, rej) => pending.push({url, res, rej}));
}
const window = {};
const M = new Function("$", "api", "window", "_fmtBytes", "ooIsoDate", src)(
  (id) => els[id], api, window, (n) => n + " B", (s) => String(s || "").slice(0, 10));
const flush = () => new Promise((r) => setImmediate(r));

const PLAN_OK = {articles: 12, estimated_bytes: 5000, destination_writable: true, free_bytes: 999999,
  period: {start: "2026-11-02", last_day: "2026-11-08"},
  privacy: {caveat: "c", items: [{what: "Article text", why_it_matters: "w", present: true, n: 12}]}};

(async () => {
  const planBtn = {disabled: false}, buildBtn = els["bul-ev-build"];

  // --- no folder: nothing is asked ----------------------------------------- //
  await M.bulletinEvidencePlan(planBtn);
  assert.strictEqual(calls.length, 0, "an empty folder must not reach the server");
  assert.ok(els["bul-ev-msg"].textContent.includes("folder"));

  // --- a passing Check enables Write and draws the caveat with the numbers -- //
  els["bul-ev-dest"].value = "/data/archive";
  let p = M.bulletinEvidencePlan(planBtn);
  assert.strictEqual(calls[0].method, "POST");
  assert.ok(calls[0].url.startsWith("/api/bulletin/evidence/plan?cadence=weekly&dest=%2Fdata%2Farchive"), calls[0].url);
  pending.shift().res(PLAN_OK); await p;
  assert.strictEqual(buildBtn.disabled, false, "a passing Check enables Write");
  const out = els["bul-ev-out"].innerHTML;
  assert.ok(/class="card-caveat"[^>]*>Plain text: your corpus is encrypted, this archive is not/.test(out), "the plaintext caveat is visible");
  assert.ok(out.includes("Articles: 12") && out.includes("2026-11-02") && out.includes("2026-11-08"), out);
  assert.ok(out.includes("What a reader of this archive can see"));

  // --- the folder changes: Write refuses and asks nothing ------------------ //
  els["bul-ev-dest"].value = "/elsewhere";
  const before = calls.length;
  await M.bulletinEvidenceBuild(buildBtn);
  assert.strictEqual(calls.length, before, "a Write after the folder changed must not reach the server");
  assert.strictEqual(buildBtn.disabled, true);
  assert.ok(els["bul-ev-msg"].textContent.includes("changed since the check"));

  // --- the period changes: same ------------------------------------------- //
  els["bul-ev-dest"].value = "/data/archive"; els["bul-cadence"].value = "monthly";
  await M.bulletinEvidenceBuild(buildBtn);
  assert.strictEqual(calls.length, before, "a Write after the period changed must not reach the server");
  els["bul-cadence"].value = "weekly";

  // --- a Write with the checked pair goes, and reports what landed --------- //
  M._bulPaintEvidence();
  assert.strictEqual(buildBtn.disabled, false);
  p = M.bulletinEvidenceBuild(buildBtn);
  assert.ok(calls[calls.length - 1].url.startsWith("/api/bulletin/evidence/build?cadence=weekly&dest=%2Fdata%2Farchive"));
  assert.ok(calls[calls.length - 1].url.endsWith("&plaintext_ack=true"), "the write says the warning was shown");
  // WHILE the write is in flight: a repaint (a language switch) or a Check must not turn Write back on.
  M._bulPaintEvidence();
  assert.strictEqual(buildBtn.disabled, true, "a repaint during a write re-enabled Write");
  assert.strictEqual(els["bul-ev-plan"].disabled, true, "Check stays off during a write");
  const n0 = calls.length;
  await M.bulletinEvidencePlan(planBtn);
  assert.strictEqual(calls.length, n0, "a Check during a write must not reach the server");
  await M.bulletinEvidenceBuild(buildBtn);
  assert.strictEqual(calls.length, n0, "a second Write during a write must not reach the server");
  pending.shift().res({path: "/data/archive/x.zip", articles: 12, articles_expected: 12, complete: true, bytes: 4000}); await p;
  assert.ok(els["bul-ev-out"].innerHTML.includes("/data/archive/x.zip"));
  assert.ok(els["bul-ev-out"].innerHTML.includes("Articles: 12 · 4000 B"));
  assert.strictEqual(buildBtn.disabled, true, "a written archive needs a new Check before another Write");
  assert.strictEqual(els["bul-ev-plan"].disabled, false);

  // --- an unwritable folder keeps Write off -------------------------------- //
  p = M.bulletinEvidencePlan(planBtn);
  pending.shift().res(Object.assign({}, PLAN_OK, {destination_writable: false, destination_error: "Permission denied"})); await p;
  assert.strictEqual(buildBtn.disabled, true, "an unwritable folder keeps Write off");
  assert.ok(els["bul-ev-out"].innerHTML.includes("cannot be written to"));

  // --- an empty period keeps Write off ------------------------------------ //
  p = M.bulletinEvidencePlan(planBtn);
  pending.shift().res(Object.assign({}, PLAN_OK, {articles: 0})); await p;
  assert.strictEqual(buildBtn.disabled, true, "nothing to write keeps Write off");

  // --- an earlier Check's late reply never paints over a later one --------- //
  const p1 = M.bulletinEvidencePlan(planBtn), first = pending.shift();
  const p2 = M.bulletinEvidencePlan(planBtn), second = pending.shift();
  second.res(Object.assign({}, PLAN_OK, {articles: 7})); await p2;
  first.res(Object.assign({}, PLAN_OK, {articles: 99})); await p1;
  await flush();
  assert.ok(els["bul-ev-out"].innerHTML.includes("Articles: 7"), "the later Check owns the panel");
  assert.ok(!els["bul-ev-out"].innerHTML.includes("Articles: 99"));

  // --- a failed enumeration is an unanswered question, not an all-clear ---- //
  const html = M._bulPrivacyHtml({kind: "evidence", error: "OperationalError", caveat: "x"}, "h");
  assert.ok(html.includes("could not be listed") && html.includes("not an all-clear"), html);

  // --- Stop shows only while a run is watched ------------------------------ //
  M._bulNarrateButtons();
  assert.strictEqual(els["bul-narrate-stop"].hidden, true);
  M.setNarrating(true); M._bulNarrateButtons();
  assert.strictEqual(els["bul-narrate-stop"].hidden, false);
  assert.strictEqual(els["bul-narrate-run"].disabled, true);
  M.setStopAsked(true); M._bulNarrateButtons();
  assert.strictEqual(els["bul-narrate-stop"].disabled, true, "Stop is not offered twice");
  M.setStopAsked(false);
  M.setNarrating(false); M._bulNarrateButtons();
  assert.strictEqual(els["bul-narrate-stop"].hidden, true);
  assert.strictEqual(els["bul-narrate-run"].disabled, false);

  console.log("bulletin evidence: all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
