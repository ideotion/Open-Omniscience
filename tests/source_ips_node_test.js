// The Sources trail's "Server IPs" line, run as REAL code (Lane M, R684).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// Checks: every IP and its article count are shown; the IPs the app never had are counted by
// reason, never hidden; the CDN caveat is visible text, not a hover; the DB-IP credit rides
// with a looked-up country and only then; an IP or a country is text, never markup.
// EXTRACTED from the shipped module rather than re-typed.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-sources.js"), "utf-8");
const CORE = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-core.js"), "utf-8");

function extract(text, name) {
  const at = text.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = text.indexOf("{", text.indexOf(")", at));
  let d = 0, j = open;
  for (; j < text.length; j++) {
    if (text[j] === "{") d++;
    else if (text[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return text.slice(at, j);
}

const src =
  "function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;'); }\n" +
  // ooCountryCell is the shared country renderer (app-core.js, alpha-3 tables and CLDR behind it);
  // a stand-in with its contract -- the code visible and escaped, a name in the hover -- keeps this
  // test on srcIpsHtml. tests/test_alpha3_display_surfaces.py pins that the real helper is called.
  "function ooCountryCell(v) { return '<span title=\"' + esc('name of ' + v) + '\">' + esc(v) + '</span>'; }\n" +
  "var window = {}; var document = { documentElement: { dir: \"ltr\" } };\n" + extract(CORE, "ooIsoDate") + "\n" + extract(CORE, "ooLabelHtml") + "\n" + extract(SRC, "srcIpsHtml") +
  "\nmodule.exports = { srcIpsHtml };";
const m = { exports: {} };
new Function("module", "exports", src)(m, m.exports);
const { srcIpsHtml } = m.exports;

const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
const visible = (html) => String(html).replace(/<[^>]*>/g, " ").replace(/&amp;/g, "&").replace(/\s+/g, " ").trim();
const CREDIT = "IP geolocation by DB-IP (https://db-ip.com) — CC BY 4.0";

const d = {
  ips: [
    { ip: "203.0.113.7", articles: 12, first_seen: "2026-10-01T08:00:00", last_seen: "2026-11-12T09:00:00", country: "FR" },
    { ip: "198.51.100.2", articles: 3, first_seen: null, last_seen: null, country: null },
  ],
  unavailable: { tor_or_proxy: 4, not_captured: 9 },
  method: "Article.server_ip, recorded at fetch time", attribution: CREDIT,
};
const html = srcIpsHtml(d, t, tf);
const v = visible(html);
assert.ok(v.includes("Server IPs (2)"), v);
assert.ok(v.includes("203.0.113.7 FR ×12") && v.includes("198.51.100.2 ×3"), v);
assert.ok(html.includes('<span title="name of FR">FR</span>'), "the country goes through the shared cell, its name in the hover");
assert.ok(v.includes("4 via Tor or a proxy (no IP by design)") && v.includes("9 not captured"), v);
assert.ok(html.includes('title="first seen 2026-10-01, last seen 2026-11-12"'), html);
assert.ok(html.includes('title="first seen ?, last seen ?"'), "a missing date reads as unknown, never 'null'");
assert.ok(/class="card-caveat"[^>]*>The server that answered/.test(html), "the caveat is visible text");
assert.ok(v.includes(CREDIT), "a shown country carries its licence credit");
assert.ok(!v.includes("null") && !v.includes("undefined"), v);

// no country shown: no credit; no IPs at all: a dash, still the caveat
const bare = visible(srcIpsHtml({ ips: [], unavailable: {}, attribution: CREDIT }, t, tf));
assert.ok(bare.includes("Server IPs (0)") && bare.includes("—") && !bare.includes("DB-IP"), bare);
assert.ok(bare.includes("The server that answered"), bare);
assert.ok(!visible(srcIpsHtml({ ips: [{ ip: "192.0.2.1", articles: 1 }], unavailable: {}, attribution: CREDIT }, t, tf)).includes("DB-IP"));

// hostile values are text
const hostile = srcIpsHtml({ ips: [{ ip: "<img src=x onerror=1>", articles: "<b>", country: "<i>x" }], unavailable: {} }, t, tf);
assert.ok(!hostile.includes("<img") && !hostile.includes("<b>") && !hostile.includes("<i>"), hostile);

// nothing vouches for the source
assert.ok(!/\b(score[sd]?|rating|rank(ed|ing)?|credib\w*|trustworth\w*|reliab\w*|verified)\b/i.test(v), v);

console.log("source ips node test: all checks passed");
