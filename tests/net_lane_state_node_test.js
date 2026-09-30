// The consent popup's per-lane state, run as REAL code (R31, 2026-09-25).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// `_laneState` sorts every lane of `net-hosts.js` into the popup's four buckets -- runs on
// every pass / only when you ask / switched off right now / could not read -- and the
// operator decides whether to go online from what that sort says. "Switched off right
// now" is a promise that no request goes to those hosts, so it is the one answer this
// function may never give by mistake.
//
// R31 made the refresh of tracked statistics default ON, which gave the "Official
// statistics" row a SECOND switch reaching the same hosts. With one key per lane, an
// operator who set the country-data ride-along to 0 saw the row under "switched off"
// while the refresh kept fetching from api.worldbank.org -- the popup under-stating
// egress, in the one place it exists to state it. `setting` may now be an array; the
// lane is on while ANY key is on.
//
// A source-level assertion cannot tell "any" from "all" or from "the first" -- all three
// mention every key -- so this runs the function, EXTRACTED from the shipped module
// (a re-typed copy would pass while the real one was wrong), against the REAL table.

const assert = require("assert");
const APP = require("./app_source.js").appJs();
const { OO_NET_LANES } = require("../src/static/net-hosts.js");

function extract(name) {
  // Balanced PARENS first, then the body brace (the recorded default-parameter trap).
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

// The four state constants are ONE statement spanning two lines; take it whole, by its
// own terminator, rather than re-typing the values.
const cAt = APP.indexOf("const _NET_STATE_ON");
assert.ok(cAt !== -1, "the lane-state constants are gone -- were they renamed?");
const constants = APP.slice(cAt, APP.indexOf(";", cAt) + 1);

const src = constants + "\n" + extract("_laneState") + "\n" +
  "module.exports = { _laneState, ON: _NET_STATE_ON, OFF: _NET_STATE_OFF, " +
  "ASK: _NET_STATE_ASK, UNKNOWN: _NET_STATE_UNKNOWN };";
const S = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();
const { _laneState } = S;

const lane = (id) => {
  const l = OO_NET_LANES.find((x) => x.id === id);
  assert.ok(l, "no lane " + id + " in net-hosts.js");
  return l;
};
const sched = (payload) => ({ scheduler: payload, safety: {}, custody: {} });

// --- the row R31 is about --------------------------------------------------- //
const stats = lane("statistics");
assert.ok(Array.isArray(stats.setting), "the statistics row must name BOTH of its switches");
assert.deepStrictEqual(
  stats.setting.slice().sort(),
  ["auto_refresh_stat_subscriptions", "country_data_per_pass"],
  "the statistics row's switches changed -- re-read R31 before editing this"
);

// The case the fix exists for: the ride-along is off, the refresh is not.
assert.strictEqual(
  _laneState(stats, sched({ country_data_per_pass: 0, auto_refresh_stat_subscriptions: true })),
  S.ON, "a running statistics refresh was shown as 'switched off'"
);
// The mirror: the ride-along alone still reaches the hosts.
assert.strictEqual(
  _laneState(stats, sched({ country_data_per_pass: 2, auto_refresh_stat_subscriptions: false })),
  S.ON
);
// Off only when EVERY switch reads off.
assert.strictEqual(
  _laneState(stats, sched({ country_data_per_pass: 0, auto_refresh_stat_subscriptions: false })),
  S.OFF
);
// A fresh install's defaults (2 per pass, refresh on).
assert.strictEqual(
  _laneState(stats, sched({ country_data_per_pass: 2, auto_refresh_stat_subscriptions: true })),
  S.ON
);

// ABSENT IS NOT OFF, per key: one unreadable switch beside one that is off is "could not
// read", never "off" -- the missing one may be the one that is on.
assert.strictEqual(
  _laneState(stats, sched({ country_data_per_pass: 0 })), S.UNKNOWN,
  "an unreadable switch beside an off one was reported as off"
);
assert.strictEqual(
  _laneState(stats, sched({ country_data_per_pass: 0, auto_refresh_stat_subscriptions: null })),
  S.UNKNOWN
);
// ...but one switch that IS on settles it, whatever the other says.
assert.strictEqual(
  _laneState(stats, sched({ auto_refresh_stat_subscriptions: true })), S.ON
);
// The whole payload unreadable stays unknown, as before.
assert.strictEqual(_laneState(stats, sched(null)), S.UNKNOWN);

// --- single-key lanes behave exactly as before ------------------------------ //
const discovery = lane("discovery");
assert.strictEqual(typeof discovery.setting, "string");
assert.strictEqual(_laneState(discovery, sched({ world_discovery_per_pass: 3 })), S.ON);
assert.strictEqual(_laneState(discovery, sched({ world_discovery_per_pass: 0 })), S.OFF);
assert.strictEqual(_laneState(discovery, sched({})), S.UNKNOWN);
assert.strictEqual(_laneState(discovery, sched(null)), S.UNKNOWN);

// `settingOn` (a non-boolean switch) still compares the exact value.
const wiki = lane("wikipedia");
assert.strictEqual(_laneState(wiki, sched({ wiki_lane_state: "running" })), S.ON);
assert.strictEqual(_laneState(wiki, sched({ wiki_lane_state: "stopped" })), S.OFF);
const custody = lane("custody");
assert.strictEqual(
  _laneState(custody, { scheduler: {}, safety: {}, custody: { anchoring_mode: "opentimestamps" } }),
  S.ON
);
assert.strictEqual(
  _laneState(custody, { scheduler: {}, safety: {}, custody: { anchoring_mode: "local" } }),
  S.OFF
);

// The triggers that never read a setting are untouched.
assert.strictEqual(_laneState(lane("press"), sched(null)), S.ON);
assert.strictEqual(_laneState(lane("osm"), sched(null)), S.ASK);
assert.strictEqual(_laneState(lane("markets"), sched({})), S.ON); // the one noOptOut ride-along left

// PF07 = a (2026-09-30): law, calendars and hazards each read their own real switch. Before
// it, law and calendars were flagged noOptOut and showed ON whatever the settings said.
for (const [id, key] of [["law", "auto_track_law"], ["calendar", "auto_import_calendars"],
                         ["hazards", "auto_track_signals"]]) {
  assert.strictEqual(lane(id).noOptOut, undefined, id + " must not claim to be always on");
  assert.strictEqual(_laneState(lane(id), sched({ [key]: true })), S.ON, id + " on");
  assert.strictEqual(_laneState(lane(id), sched({ [key]: false })), S.OFF, id + " off");
  assert.strictEqual(_laneState(lane(id), sched({})), S.UNKNOWN, id + " key absent");
}

// --- Discover by topic: switched on, it is still only "when you ask" -------- //
// (delegated click-through 2026-09-26, row H). Its switch unlocks a button; nothing
// schedules it, and docs/SECURITY.md says so. Listing it under "Runs on every
// collection pass" told the operator the scheduler would query DuckDuckGo.
{
  const topic = lane("topic-discovery");
  assert.strictEqual(topic.whenOn, "ask", "the topic-discovery lane lost whenOn: 'ask'");
  const safety = (v) => ({ scheduler: {}, safety: v, custody: {} });
  assert.strictEqual(_laneState(topic, safety({ discovery_external_enabled: true })), S.ASK,
    "an enabled topic discovery was listed as running on every pass");
  assert.strictEqual(_laneState(topic, safety({ discovery_external_enabled: false })), S.OFF);
  assert.strictEqual(_laneState(topic, safety(null)), S.UNKNOWN);
  // The custody lane shares the "opt-in" trigger and must NOT follow: once on, it
  // anchors every ingested article with no click of its own.
  assert.strictEqual(custody.whenOn, undefined, "the custody lane is not a when-you-ask lane");
}

// --- the lane an action turns ON is listed as it WILL be (row P) ------------ //
// Start/Resume on the Wikipedia toggle passes {enabling: "wikipedia"}: the popup that
// asks to start the stream used to list it under "Switched off right now".
{
  const stopped = sched({ wiki_lane_state: "stopped" });
  assert.strictEqual(_laneState(wiki, stopped), S.OFF, "sanity: a stopped lane reads off");
  assert.strictEqual(_laneState(wiki, stopped, "wikipedia"), S.ON,
    "the lane this action turns on was listed as switched off");
  assert.strictEqual(_laneState(wiki, sched({ wiki_lane_state: "halted" }), "wikipedia"), S.ON);
  // Only the named lane moves; every other lane still reports its own switch.
  assert.strictEqual(_laneState(discovery, sched({ world_discovery_per_pass: 0 }), "wikipedia"), S.OFF);
  assert.strictEqual(_laneState(lane("osm"), sched(null), "wikipedia"), S.ASK);
}

console.log("net lane state: all assertions passed");
