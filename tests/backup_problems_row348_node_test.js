// Row 348: each backup-verify problem is said in the reader's language from the server's
// {code, params}; params are data (translate="no", escaped); an unknown code falls back to
// the server's English line. Runs the real helper out of the app modules.
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
const cAt = APP.indexOf("const BACKUP_PROBLEM_FRAMES = {");
assert.ok(cAt >= 0, "frames");
const frames = APP.slice(cAt, APP.indexOf("};", cAt) + 2);
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const R = new Function("esc", frames + "\n" + fn("backupProblemHtml") + "\nreturn {backupProblemHtml, BACKUP_PROBLEM_FRAMES};")(esc);
const tf = (s, v) => "T[" + String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m) + "]";

const out = R.backupProblemHtml("member x failed to decrypt: boom",
  {code: "member-decrypt-failed", params: {member: "<b>m</b>.db", reason: "bad tag"}}, tf);
assert.strictEqual(out, 'T[Member <bdi translate="no">&lt;b&gt;m&lt;/b&gt;.db</bdi> could not be decrypted: <bdi translate="no">bad tag</bdi>]');
// a code with no params renders the keyed sentence alone
assert.strictEqual(R.backupProblemHtml("raw", {code: "passphrase-mismatch", params: {}}, tf),
  "T[The passphrase does not match this volume set.]");
// unknown code, or no code (an older server): the server's own line, escaped
assert.strictEqual(R.backupProblemHtml("a <raw> line", {code: "nope", params: {}}, tf), "a &lt;raw&gt; line");
assert.strictEqual(R.backupProblemHtml("a <raw> line", undefined, tf), "a &lt;raw&gt; line");
// a param the frame does not name is never injected; a placeholder without a param stays visible text
assert.ok(!R.backupProblemHtml("r", {code: "bad-volumes", params: {other: "<x>"}}, tf).includes("<x>"));
// a param value that itself looks like a marker or a placeholder stays inert data
const sneaky = R.backupProblemHtml("r", {code: "member-checksum-mismatch", params: {member: "\u0001member\u0002{member}"}}, tf);
assert.strictEqual((sneaky.match(/<bdi/g) || []).length, 1, sneaky);
console.log("backup problems row 348: all checks passed");
