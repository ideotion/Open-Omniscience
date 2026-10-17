// The Home trends poll backs OFF after a deadline refusal, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// 2026-10-16, a running install: Home's 15 s tick asked /api/insights/trending-windows 533 times in one session,
// 362 of them a 503 at the 60 s statement deadline. The client-wide ladder (app-core.js `_loadFactor`) counts refusals
// inside a 60 s window, and a deadline refusal is itself 60 s long, so each one had left the window before the next
// arrived and the factor never rose. The call also was not marked `polled`, so it carried the user-action retry budget.
//
// The pure schedule (`homeTrendsDue` / `homeTrendsNoteResult`) is lifted out of the shipped engine and driven with a
// fake clock; the three facts about the wiring (the call is `polled`, the tick asks `homeTrendsDue` first, the catch
// hands over the HTTP status) are read from the source, because they are what a refactor loses first.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

const from = APP.indexOf("const _HOME_TRENDS_BASE_MS");
const to = APP.indexOf("async function loadHomeTrends()");
assert.ok(from > 0 && to > from, "the trends backoff block must be in the engine");
const block = APP.slice(from, to);

const T0 = 1_000_000;
let n = 0;
function test(name, fn) { fn(); n++; console.log("ok - " + name); }

test("a healthy server is asked on every tick", () => {
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  for (let i = 0; i < 5; i++) {
    assert.ok(s.homeTrendsDue(T0 + i * 15000));
    s.homeTrendsNoteResult(true, T0 + i * 15000);
  }
  assert.strictEqual(s.homeTrendsBackoff().fails, 0);
});

test("each consecutive deadline refusal doubles the gap, from the 15 s tick", () => {
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  let now = T0;
  const gaps = [];
  for (let i = 0; i < 4; i++) {
    s.homeTrendsNoteResult(false, now, 503);
    gaps.push(s.homeTrendsBackoff().next_at - now);
    now = s.homeTrendsBackoff().next_at;
  }
  assert.deepStrictEqual(gaps, [30000, 60000, 120000, 240000]);
});

test("the very next ticks inside the gap are not asked, and the first after it is", () => {
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  s.homeTrendsNoteResult(false, T0, 503);
  assert.ok(!s.homeTrendsDue(T0 + 15000), "the next tick is inside the gap");
  assert.ok(!s.homeTrendsDue(T0 + 29999));
  assert.ok(s.homeTrendsDue(T0 + 30000));
});

test("a refusal that arrives after the client-wide 60 s window still backs this call off", () => {
  // the defect: refusals 70 s apart never sit in one 60 s window, so only a per-call memory can see the run of them
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  s.homeTrendsNoteResult(false, T0, 503);
  s.homeTrendsNoteResult(false, T0 + 70000, 503);
  assert.strictEqual(s.homeTrendsBackoff().fails, 2);
  assert.strictEqual(s.homeTrendsBackoff().next_at, T0 + 70000 + 60000);
});

test("a partial answer counts as degraded the same way", () => {
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  s.homeTrendsNoteResult(false, T0, "partial");   // loadHomeTrends passes !d.partial and "partial"
  assert.strictEqual(s.homeTrendsBackoff().fails, 1);
});

test("a full answer returns the poll to the tick at once", () => {
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  for (let i = 0; i < 3; i++) s.homeTrendsNoteResult(false, T0, 503);
  s.homeTrendsNoteResult(true, T0 + 100000);
  assert.strictEqual(s.homeTrendsBackoff().fails, 0);
  assert.ok(s.homeTrendsDue(T0 + 100001));
});

test("the gap stops growing at the stated ceiling", () => {
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  for (let i = 0; i < 30; i++) s.homeTrendsNoteResult(false, T0, 503);
  assert.strictEqual(s.homeTrendsBackoff().next_at - T0, s.homeTrendsBackoff().max_ms);
});

test("an error that is not a deadline refusal (a 404, a 422) does not slow the poll", () => {
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  s.homeTrendsNoteResult(false, T0, 404);
  s.homeTrendsNoteResult(false, T0, 422);
  assert.strictEqual(s.homeTrendsBackoff().fails, 0);
  assert.ok(s.homeTrendsDue(T0));
});

test("an error with no HTTP status (a dropped connection, a restart, a render exception) does not slow the poll", () => {
  // the defect: `status !== undefined && status !== 503` let a statusless error through, so a server restarting for
  // three minutes stretched the gap to four, and the strip stayed empty for that long after it came back
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  for (let i = 0; i < 5; i++) s.homeTrendsNoteResult(false, T0, undefined);   // fetch rejected: e.status is undefined
  s.homeTrendsNoteResult(false, T0, null);
  s.homeTrendsNoteResult(false, T0);                                           // and nothing passed at all
  assert.strictEqual(s.homeTrendsBackoff().fails, 0);
  assert.ok(s.homeTrendsDue(T0));
});

const load = APP.slice(to, APP.indexOf("function enlargeHomeTrend"));
test("the trends call is marked polled, records its outcome and hands over the HTTP status", () => {
  assert.ok(/api\("\/api\/insights\/trending-windows[^"]*"\s*\+\s*tgtLangParam\(\),\s*\{polled: true\}\)/.test(load),
    "the trending-windows call must be {polled: true}");
  assert.ok(/homeTrendsNoteResult\(!d\.partial, Date\.now\(\), "partial"\)/.test(load), "a success must be recorded, a partial one as degraded");
  assert.ok(/homeTrendsNoteResult\(false, Date\.now\(\), e && e\.status\)/.test(load), "a failure must carry its status");
});

test("the Home tick asks the schedule before it asks the server", () => {
  const live = APP.slice(APP.indexOf("async function refreshHomeLive()"));
  const body = live.slice(0, live.indexOf("\n    }\n") + 7);
  assert.ok(/if \(homeTrendsDue\(Date\.now\(\)\)\) \{ try \{ await loadHomeTrends\(\); \} catch \(e\) \{\} \}/.test(body),
    "refreshHomeLive must gate loadHomeTrends on homeTrendsDue");
  assert.ok(!/\n\s*try \{ await loadHomeTrends\(\); \} catch/.test(body.replace(/if \(homeTrendsDue[^\n]*\n/, "")),
    "no ungated loadHomeTrends call may remain in the tick");
});

test("a replayed partial answer is counted as partial: the schedule keeps doubling", () => {
  // the server replays a partial inside its 30 s window with partial:true AND replayed:true; the client must not read
  // the replay as a fresh full answer (the line below is what loadHomeTrends records, taken from the source)
  assert.ok(/homeTrendsNoteResult\(!d\.partial, Date\.now\(\), "partial"\)/.test(load) && !/d\.replayed/.test(load),
    "the outcome must depend on partial alone, never on replayed");
  const s = new Function(block + "\nreturn {homeTrendsDue, homeTrendsNoteResult, homeTrendsBackoff};")();
  const gaps = [];
  let now = T0;
  for (let i = 0; i < 3; i++) {
    const d = {partial: true, replayed: true};
    s.homeTrendsNoteResult(!d.partial, now, "partial");
    gaps.push(s.homeTrendsBackoff().next_at - now);
    now = s.homeTrendsBackoff().next_at;
  }
  assert.deepStrictEqual(gaps, [30000, 60000, 120000]);
});

test("a partial answer with no window in it says 'not computed' where the strip would be, with the server's words", () => {
  // the defect: `!terms.length` hid the strip, so the caveat a partial payload carried was never shown
  const i = load.indexOf("if (!terms.length) {");
  assert.ok(i > 0, "the empty-terms branch must exist");
  const branch = load.slice(i, load.indexOf("return;", i) + 7);
  assert.ok(/d\.partial && d\.caveat/.test(branch) && /esc\(t\(d\.caveat\)\)/.test(branch) && /role="status"/.test(branch),
    "a partial payload with no terms must print its caveat");
  assert.ok(/panel\.hidden = true/.test(branch), "a full payload with no terms still hides the strip");
});

console.log(n + " checks");
