// The consent popup's per-lane TRANSPORT line, run as REAL code (S04-08's S5, Q1014).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Q1014: "each lane declares its transport in the consent hover". The popup used to read
// the stored `http_proxy` field alone, so it said three wrong things an operator decides
// on: "fetches ride the proxy you configured" in transparent mode, where that proxy is
// not used; "no proxy, fetches go direct" beside a working proxy POOL; and the same
// "go direct" when the settings could not be read at all. The line now comes from the
// SERVER's reading of the fetch path (`transport.kind`), and these checks are mostly
// negative space: which sentence each state may NEVER produce.
//
// Extracted from the shipped module (a re-typed copy would pass while the real one was
// wrong) and run against the REAL lane table.

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

function load(translator) {
  const src =
    "var window = " + (translator ? "{OOI18N: {t: TR}}" : "{}") + ";\n" +
    "var OOI18N = window.OOI18N;\n" +
    extract("_transportKind") + "\n" +
    extract("_laneTransport") + "\n" +
    extract("_transportHint") + "\n" +
    extract("_laneHostTitle") + "\n" +
    "module.exports = { _transportKind, _laneTransport, _transportHint, _laneHostTitle };";
  const m = { exports: {} };
  new Function("module", "exports", "TR", src)(m, m.exports, translator);
  return m.exports;
}

const F = load(null);
const lane = (id) => {
  const l = OO_NET_LANES.find((x) => x.id === id);
  assert.ok(l, "no lane " + id + " in net-hosts.js");
  return l;
};
const cfg = (transport) => ({ safety: { fetch_mode: "x", transport } });
const KINDS = ["direct", "proxy", "pool", "refused", "unknown"];

// --- the kind is the server's, and anything unrecognised is "unknown" -------------- //
{
  for (const k of ["direct", "proxy", "pool", "refused"]) {
    assert.strictEqual(F._transportKind(cfg({ kind: k })), k, k);
  }
  // An unreadable settings payload (null), a payload from a server that predates the
  // field, and a kind this build does not know are all "we could not tell" -- never a
  // guess that happens to read as "direct".
  for (const c of [null, undefined, {}, { safety: null }, { safety: {} },
                   { safety: { http_proxy: "socks5h://127.0.0.1:9050" } },
                   cfg(null), cfg({}), cfg({ kind: "tor" })]) {
    assert.strictEqual(F._transportKind(c), "unknown", JSON.stringify(c));
  }
}

// --- a lane that uses the fetcher -------------------------------------------------- //
{
  const press = lane("press");
  assert.notStrictEqual(press.fetcher, false, "the press lane is meant to use the fetcher");
  const at = (k) => F._laneTransport(press, k);
  assert.ok(/through your proxy\./.test(at("proxy")), at("proxy"));
  assert.ok(/proxy pool, one member per host/.test(at("pool")), at("pool"));
  assert.ok(/see your address/.test(at("direct")) && /protected mode is off/.test(at("direct")),
    at("direct"));
  assert.ok(/refused, never sent direct/.test(at("refused")), at("refused"));
  assert.ok(/unknown/.test(at("unknown")), at("unknown"));
  // The refusals. A refused transport sends nothing, so it may never read as proxied
  // or as direct; an unreadable one may claim neither.
  assert.ok(!/through your proxy/.test(at("refused")), "refused read as proxied: " + at("refused"));
  assert.ok(!/through your proxy/.test(at("direct")), "direct read as proxied: " + at("direct"));
  assert.ok(!/through your proxy|see your address/.test(at("unknown")),
    "an unreadable transport made a claim: " + at("unknown"));
  // Five states, five different sentences: a collapsed branch would repeat one.
  assert.strictEqual(new Set(KINDS.map(at)).size, 5, "two transport states share a sentence");
}

// --- a lane that does NOT use the fetcher ------------------------------------------ //
{
  const offFetcher = OO_NET_LANES.filter((l) => l.fetcher === false && !l.mixed);
  assert.ok(offFetcher.length, "no off-fetcher lane left to check -- the table changed");
  for (const l of offFetcher) {
    // Protected mode is the case that matters: an operator relying on Tor must read
    // that THIS lane leaves on its own connection before going online.
    for (const k of ["proxy", "pool", "refused"]) {
      const s = F._laneTransport(l, k);
      assert.ok(/even with protected mode on/.test(s) && /see your address/.test(s),
        l.id + "/" + k + " hides that it goes direct: " + s);
      assert.ok(!/through your proxy\./.test(s), l.id + "/" + k + " claims the proxy: " + s);
    }
    for (const k of ["direct", "unknown"]) {
      assert.strictEqual(F._laneTransport(l, k), "Not through this app's fetcher or proxy.",
        l.id + "/" + k);
    }
  }
}

// --- the one MIXED lane: the installer check proxied, the downloads not ------------ //
{
  const mixed = OO_NET_LANES.filter((l) => l.mixed);
  assert.deepStrictEqual(mixed.map((l) => l.id), ["ai"],
    "the mixed lanes changed -- update docs/SECURITY.md's 'Mixed.' rows in the same diff");
  const ai = mixed[0];
  assert.strictEqual(ai.fetcher, false, "a mixed lane is a fetcher:false lane with one proxied host");
  for (const k of ["proxy", "pool"]) {
    const s = F._laneTransport(ai, k);
    assert.ok(/mostly direct/.test(s) && /installer check goes through your proxy/.test(s), s);
  }
  // With no usable proxy the installer check is refused, not proxied: "goes through
  // your proxy" would be the overclaim this line exists to prevent.
  const r = F._laneTransport(ai, "refused");
  assert.ok(!/through your proxy/.test(r), "refused mode claims the installer check is proxied: " + r);
  assert.ok(/even with protected mode on/.test(r), r);
}

// --- the hint under the list ------------------------------------------------------- //
{
  const h = (k) => F._transportHint(k);
  assert.ok(/proxy you configured/.test(h("proxy")), h("proxy"));
  assert.ok(/proxy pool/.test(h("pool")), h("pool"));
  assert.ok(/refused rather than sent direct/.test(h("refused")), h("refused"));
  assert.ok(/go direct/.test(h("direct")), h("direct"));
  // THE recorded bug: an unreadable payload said "No proxy is configured, so fetches go
  // direct". Not knowing is not "direct".
  assert.ok(!/go direct|ride the proxy/.test(h("unknown")), "unknown made a claim: " + h("unknown"));
  assert.ok(!/ride the proxy/.test(h("refused")), "refused claimed the proxy: " + h("refused"));
  assert.strictEqual(new Set(KINDS.map(h)).size, 5, "two transport states share a hint");
}

// --- every lane's hover carries exactly one transport line, in every state ---------- //
{
  for (const l of OO_NET_LANES) {
    for (const k of KINDS) {
      const title = F._laneHostTitle(l, k);
      const n = (title.match(/Transport:|Not through this app's fetcher or proxy\./g) || []).length;
      assert.strictEqual(n, 1, l.id + "/" + k + " has " + n + " transport lines: " + title);
    }
  }
}

// --- and it is translated: a hover is a caveat surface, so it ships x12 ------------- //
{
  const shout = (s) => "<<" + s.toUpperCase() + ">>";
  const T = load(shout);
  const s = T._laneTransport(lane("press"), "pool");
  assert.ok(s.startsWith("<<TRANSPORT:"), "the transport line bypassed the translator: " + s);
  const off = OO_NET_LANES.find((l) => l.fetcher === false && !l.mixed);
  assert.ok(T._laneTransport(off, "proxy").startsWith("<<"), "the off-fetcher line bypassed the translator");
  assert.ok(T._transportHint("unknown").startsWith("<<"), "the hint bypassed the translator");
}

console.log("net_lane_transport_node_test: all assertions passed");
