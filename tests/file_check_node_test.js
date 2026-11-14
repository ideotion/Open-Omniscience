// The Evidence & custody tab's «Check a file» renderers, run as REAL code (Lane M, R684).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The review is what stands between a click and a file that leaves the machine, so most
// checks are refusals:
//
//   * it says the file is PLAINTEXT, beside the numbers and before the button, not in a hover;
//   * it says what the signature proves and that one key on every bundle links them all;
//   * with no key yet it says one will be created, instead of showing an empty key;
//   * it lists what the file holds, and names the item fields it was given (the wire, not a
//     re-typed list), with the JSON keys shown as code, never translated;
//   * after saving it names the file, the size and the key to hand over, and how to check it
//     offline;
//   * nothing it says scores, ranks or vouches for the articles.
//
// EXTRACTED from the shipped module rather than re-typed.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-evidence.js"), "utf-8");

function extract(name) {
  const at = SRC.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = SRC.indexOf("(", at), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "(") depth++;
    else if (SRC[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = SRC.indexOf("{", i);
  let d = 0, j = open;
  for (; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return SRC.slice(at, j);
}

// Refusals first: an unknown server reason is shown, never dropped; a bundle checked without
// the signer's key never reads as "signed by the key you gave"; GPS that cannot be read is
// said, never invented; no EXIF is never called tampering; the caveat is on every image result.
const FNS = ["bundleCheckHtml", "gpsDecimal", "imageCheckHtml"];
const src =
  "function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;'); }\n" +
  FNS.map(extract).join("\n") + "\n" +
  "module.exports = {" + FNS.join(", ") + "};";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();
const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();

// bundles: the server's exact reasons (src/reporting/evidence.py verify_bundle)
const unpinned = visible(R.bundleCheckHtml({ verified: true, reason: "ok (signed by unpinned key abcdef0123456789...; pin the key to prove provenance)" }, t, tf));
assert.ok(unpinned.includes("Bundle verified") && unpinned.includes("paste the signer's key"), unpinned);
assert.ok(!unpinned.includes("signed by the key you gave"), "an unpinned check never claims the reader's key");
const pinned = visible(R.bundleCheckHtml({ verified: true, reason: "ok (signature valid and key matches the pinned trusted key)" }, t, tf));
assert.ok(pinned.includes("signed by the key you gave"), pinned);
const cases = {
  "no manifest": "not an evidence bundle",
  "malformed bundle: not the shape this app exports": "not in the shape of an evidence bundle",
  "signed by an untrusted key (does not match the pinned public key)": "different key",
  "merkle root mismatch (an item was altered/added/removed)": "Changed since signing",
  "malformed signature or public key": "damaged",
  "signature does not match (manifest altered or wrong key)": "does not match",
};
for (const [reason, want] of Object.entries(cases)) {
  const s = visible(R.bundleCheckHtml({ verified: false, reason }, t, tf));
  assert.ok(s.startsWith("Verification failed") && s.includes(want), reason + " -> " + s);
}
const odd = visible(R.bundleCheckHtml({ verified: false, reason: "something new <b>" }, t, tf));
assert.ok(odd.includes("something new <b>"), "an unknown reason is shown as sent, escaped: " + odd);

// GPS
assert.strictEqual(R.gpsDecimal([48, 51, 29.5], "N").toFixed(5), "48.85819");
assert.ok(R.gpsDecimal([2, 17, 40], "W") < 0 && R.gpsDecimal([33, 52, 0], "S") < 0);
assert.strictEqual(R.gpsDecimal(["x", 1, 2], "N"), null);
assert.strictEqual(R.gpsDecimal([1, 2], "N"), null);

// images
const full = visible(R.imageCheckHtml({ format: "JPEG", width: 4000, height: 3000, has_exif: true,
  exif: { Make: "Canon", Model: "EOS", DateTimeOriginal: "2026:01:02 10:11:12", Software: "GIMP" },
  gps: { GPSLatitude: [48, 51, 29.5], GPSLatitudeRef: "N", GPSLongitude: [2, 17, 40], GPSLongitudeRef: "E" } }, t, tf));
for (const want of ["JPEG", "4000 × 3000 px", "Date in the file: 2026:01:02 10:11:12", "Camera: Canon EOS", "Software: GIMP",
  "Location in the file: 48.85819, 2.29444", "All tags (4)", "it is not proof", "nothing stored"]) {
  assert.ok(full.includes(want), want + " missing: " + full);
}
const bare = visible(R.imageCheckHtml({ format: "PNG", width: 10, height: 10, has_exif: false, exif: {}, gps: {} }, t, tf));
assert.ok(bare.includes("No date in the file.") && bare.includes("proves nothing") && bare.includes("it is not proof"), bare);
assert.ok(!/tamper|fake|manipulat|score/i.test(bare + full), "metadata is never a verdict");
assert.ok(!bare.includes("Location"), "no GPS: no location line");
const badGps = visible(R.imageCheckHtml({ format: "JPEG", width: 1, height: 1, has_exif: true, exif: { Make: "X" }, gps: { GPSLatitude: "?" } }, t, tf));
assert.ok(badGps.includes("Location tags present but unreadable."), badGps);
const xss = R.imageCheckHtml({ format: "<img>", width: 1, height: 1, has_exif: true, exif: { "<k>": "<v>" }, gps: {} }, t, tf);
assert.ok(!xss.includes("<img>") && !xss.includes("<v>"), "every value is escaped");

console.log("file check: all checks passed");
