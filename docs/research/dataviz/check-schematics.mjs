// SPDX-License-Identifier: MIT
// Copyright (c) 2026 Ideotion
// check-schematics.mjs - verifies the claims made about chart-schematics.html
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";

const html = readFileSync(new URL("./chart-schematics.html", import.meta.url), "utf8");
const body = html.slice(html.indexOf("</style>")); // exclude token definitions
let checks = 0;
const ok = (msg) => { checks++; console.log("ok  - " + msg); };

// 1. No hardcoded hex colours in the markup (all colours come from CSS tokens).
const hex = body.match(/#[0-9a-fA-F]{3,8}\b/g) || [];
assert.equal(hex.length, 0, "found hardcoded hex in markup: " + hex.join(", "));
ok("no hardcoded hex colours in the markup (theme tokens only)");

// 2. Determinism: no random CALLS, no browser-storage ACCESS. (Prose mentions
//    inside comments are fine; we check for actual usage, not the words.)
assert.ok(!/Math\.random\s*\(/.test(html), "Math.random() call present");
assert.ok(!/(?:localStorage|sessionStorage)\s*[.\[]/.test(html), "browser storage access present");
ok("deterministic: no Math.random() calls, no browser-storage access");

// 3. Offline: no external URLs (http/https) anywhere.
assert.ok(!/https?:\/\//.test(html), "external URL present");
ok("fully offline: no external URLs");

// 4. Each chart SVG is role="img" and aria-labelledby; count matches figures.
const figures = body.match(/<figure[\s\S]*?<\/figure>/g) || [];
assert.equal(figures.length, 18, "expected 18 figures, got " + figures.length);
ok("18 figures, one per recommended technique");

const roleImg = (body.match(/<svg\b[^>]*\brole="img"/g) || []).length;
const labelledby = body.match(/aria-labelledby="([^"]+)"/g) || [];
assert.equal(roleImg, 18, "expected 18 role=img, got " + roleImg);
assert.equal(labelledby.length, 18, "expected 18 aria-labelledby, got " + labelledby.length);
ok("every chart is role=img with aria-labelledby");

// 5. Every referenced title/desc id actually exists.
for (const m of labelledby) {
  const ids = m.replace('aria-labelledby="', "").replace('"', "").split(/\s+/);
  for (const id of ids) {
    assert.ok(new RegExp('id="' + id + '"').test(body), "missing id referenced by aria-labelledby: " + id);
  }
}
const titles = (body.match(/<title id=/g) || []).length;
const descs = (body.match(/<desc id=/g) || []).length;
assert.equal(titles, 18, "expected 18 <title>, got " + titles);
assert.equal(descs, 18, "expected 18 <desc>, got " + descs);
ok("all 18 title/desc ids resolve; 18 titles + 18 descriptions present");

// 6. Every figure carries a text equivalent (a data table or an accessible tree).
let withEquivalent = 0;
for (const f of figures) {
  if (/<table/.test(f) || /role="tree"/.test(f)) withEquivalent++;
}
assert.equal(withEquivalent, 18, "figures missing a text equivalent: " + (18 - withEquivalent));
ok("every figure has a text equivalent (data table or indented tree)");

console.log("\n" + checks + " structural checks passed.");
