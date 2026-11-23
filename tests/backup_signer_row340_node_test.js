// Row 340 (R800): the backup UI says what a signature shows (the content is unchanged since it was
// signed) and whose key signed it (this installation or another), never an origin. Runs the real
// helpers out of the app modules.
"use strict";
const assert = require("assert");

const APP = require("./app_source.js").appJs();
const fn = (name) => {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at >= 0, name);
  let i = APP.indexOf("{", APP.indexOf(")", at)), depth = 0;
  for (; i < APP.length; i++) { if (APP[i] === "{") depth++; else if (APP[i] === "}" && --depth === 0) break; }
  return APP.slice(at, i + 1);
};
const R = new Function(fn("backupSignerWords") + "\n" + fn("backupSignatureWords")
  + "\nreturn {backupSignerWords, backupSignatureWords};")();
const t = (s) => "T[" + s + "]";
const tf = (s, v) => "T[" + String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m) + "]";
const K = "ab".repeat(32);
const FP = "⁨" + K.slice(0, 16) + "⁩";

assert.strictEqual(R.backupSignerWords("this-installation", K, t, tf), "T[Signed by this installation, key " + FP + "]");
assert.strictEqual(R.backupSignerWords("another-installation", K, t, tf), "T[Signed by another installation, key " + FP + "]");
assert.strictEqual(R.backupSignerWords("not-compared", K, t, tf), "T[Signed by key " + FP + "]");
assert.strictEqual(R.backupSignerWords(undefined, K, t, tf), "T[Signed by key " + FP + "]");
// row 345: a stored record that cannot tell unsigned from a failed signature never says "Not signed"
for (const stored of ["unsigned", "unknown-origin", "local", "", null]) {
  assert.strictEqual(R.backupSignerWords("unverified", stored, t, tf), "T[No verified signature]", String(stored));
}
assert.strictEqual(R.backupSignerWords("unsigned", "unsigned", t, tf), "T[Not signed]");
assert.strictEqual(R.backupSignerWords("bad-signature", "bad-signature", t, tf), "T[Signature does not match its content]");
assert.strictEqual(R.backupSignatureWords("verified", "this-installation", K, t, tf),
  "T[Content unchanged since it was signed] · T[Signed by this installation, key " + FP + "]");
assert.strictEqual(R.backupSignatureWords("bad-signature", "unsigned", null, t, tf), "T[Signature does not match its content]");
assert.strictEqual(R.backupSignatureWords("unsigned", "unsigned", null, t, tf), "T[Not signed]");
assert.strictEqual(R.backupSignatureWords("not-applicable (oo-volumes-1 sets are unsigned)", "unsigned", null, t, tf), "T[Not signed]");
// nothing a person reads calls the key an origin
for (const out of [R.backupSignerWords("another-installation", K, t, tf), R.backupSignatureWords("verified", "another-installation", K, t, tf)]) {
  assert.ok(!/origin/i.test(out), out);
}
console.log("backup signer row 340: all checks passed");
