// Row 250 (R766): the consent popup never says "protected mode is on" when the settings could not be read.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// When the stored choice cannot be read but the environment names a proxy, the server reads
// the transport as `proxy` (or `pool`, or `refused` for an unusable one) and marks it
// `stored: "unreadable"`. Nobody chose protected mode, so every line the popup draws in that
// state must name the unreadable settings and never claim protected mode is on. Extracted from
// the shipped module and run against the REAL lane table, like net_lane_transport_node_test.js.

const assert = require("assert");
const APP = require("./app_source.js").appJs();
const { OO_NET_LANES } = require("../src/static/net-hosts.js");

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

const src =
  "var window = {};\n" +
  ["_transportKind", "_storeUnreadable", "_laneTransport", "_transportHint", "_laneHostTitle"].map(extract).join("\n") +
  "\nmodule.exports = { _transportKind, _storeUnreadable, _laneTransport, _transportHint, _laneHostTitle };";
const m = { exports: {} };
new Function("module", "exports", src)(m, m.exports);
const F = m.exports;
const cfg = (transport) => ({ safety: { transport } });
const CLAIM = /protected mode is on|protected mode on/i;

// --- the marker is the server's, read strictly ------------------------------------- //
assert.strictEqual(F._storeUnreadable(cfg({ kind: "proxy", stored: "unreadable" })), true);
for (const c of [null, undefined, {}, cfg(null), cfg({ kind: "proxy" }), cfg({ kind: "proxy", stored: "ok" })]) {
  assert.strictEqual(F._storeUnreadable(c), false, JSON.stringify(c));
}

// the other unreadable state (no environment proxy): the server says kind "unknown", reason "unreadable"
assert.strictEqual(F._storeUnreadable(cfg({ kind: "unknown", reason: "unreadable" })), true);
assert.strictEqual(F._storeUnreadable(cfg({ kind: "unknown" })), false);
for (const id of ["ai", "update"]) {
  const l = OO_NET_LANES.find((x) => x.id === id);
  const line = F._laneTransport(l, "unknown", true);
  assert.ok(/settings could not be read, so these fetches are refused/.test(line), id + ": " + line);
  assert.ok(!/Mostly not through/.test(line), id + ": " + line);
}
for (const l of OO_NET_LANES.filter((x) => x.fetcher === false && !x.mixed)) {
  assert.strictEqual(F._laneTransport(l, "unknown", true), F._laneTransport(l, "unknown"), l.id);
}

// --- the popup's renderer hands the flag to every line and to the hint ---------------- //
{
  const render = extract("_renderNetLanes");
  assert.ok(/const unreadable = _storeUnreadable\(cfg\);/.test(render), "the renderer reads the mark");
  assert.ok(render.includes("_laneLine(l, kind, unreadable)"), "each lane line gets the flag");
  assert.ok(render.includes("_transportHint(kind, unreadable)"), "the hint gets the flag");
  assert.ok(extract("_laneLine").includes("_laneHostTitle(lane, kind, unreadable)"), "each hover gets the flag");
  assert.ok(extract("_laneHostTitle").includes("_laneTransport(lane, kind, unreadable)"), "the hover's transport gets the flag");
}

// --- unreadable: no line and no hint claims protected mode is on --------------------- //
for (const kind of ["proxy", "pool", "refused"]) {
  for (const lane of OO_NET_LANES) {
    const line = F._laneTransport(lane, kind, true);
    assert.ok(!CLAIM.test(line), `${lane.id}/${kind}: ${line}`);
    const title = F._laneHostTitle(lane, kind, true);
    assert.ok(!CLAIM.test(title), `${lane.id}/${kind} hover: ${title}`);
  }
  const hint = F._transportHint(kind, true);
  assert.ok(/settings could not be read/.test(hint), kind + ": " + hint);
  assert.ok(!CLAIM.test(hint) && !/Protected mode is on/.test(hint), kind + ": " + hint);
}
// a refused fetcher lane names the unreadable settings, never "no usable proxy" under protected mode
assert.ok(/settings could not be read/.test(F._laneTransport(OO_NET_LANES.find((l) => l.fetcher !== false), "refused", true)));
// the install/update lanes say the install itself is refused (R766), never "mostly direct"
for (const id of ["ai", "update"]) {
  const l = OO_NET_LANES.find((x) => x.id === id);
  const line = F._laneTransport(l, "proxy", true);
  assert.ok(/refused while the settings cannot be read/.test(line), id + ": " + line);
  assert.ok(!/mostly direct/.test(line), id + ": " + line);
}
// a lane that never uses a proxy still says it goes direct: the fact an operator needs most
for (const l of OO_NET_LANES.filter((x) => x.fetcher === false && !x.mixed)) {
  assert.ok(/direct/.test(F._laneTransport(l, "proxy", true)), l.id);
}

// --- readable settings: the lines are exactly what they were ------------------------- //
for (const kind of ["direct", "proxy", "pool", "refused", "unknown"]) {
  for (const lane of OO_NET_LANES) {
    assert.strictEqual(F._laneTransport(lane, kind, false), F._laneTransport(lane, kind), lane.id + "/" + kind);
  }
  assert.strictEqual(F._transportHint(kind, false), F._transportHint(kind), kind);
}
assert.ok(/protected mode is on with no usable proxy/.test(F._laneTransport(OO_NET_LANES.find((l) => l.fetcher !== false), "refused", false)));

console.log("all assertions passed");
