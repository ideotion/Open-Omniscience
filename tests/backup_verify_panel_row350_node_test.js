// Row 350: the backup verify panel says its counts and names in whole keyed frames, and a live
// language switch repaints it from the report it holds (never a fetch). Runs the real functions.
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
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
// a fake page: one host element, and an OOI18N whose language we can switch
let lang = "xx";
const tr = (s) => lang + "[" + s + "]";
const trf = (s, v) => lang + "[" + String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m) + "]";
// The host is shared with other writers: writing its innerHTML makes a fresh panel child when the
// markup opens with the verify panel, and drops any earlier child (and the report it held) otherwise.
const host = {
  _html: "", firstElementChild: null, dataset: {},
  get innerHTML() { return this._html; },
  set innerHTML(v) {
    this._html = v;
    const m = /^<div ([^>]*)>/.exec(v);
    this.firstElementChild = m ? { parentNode: this, attrs: m[1] } : null;
  },
};
const panel = () => host.firstElementChild;
const window = { OOI18N: { t: (s) => tr(s), tf: (s, v) => trf(s, v) } };
const document = { querySelectorAll: (sel) => (sel === "[data-oo-verify]" && panel() && /data-oo-verify/.test(panel().attrs) ? [panel()] : []) };
const R = new Function("esc", "window", "document", "OOI18N",
  "const fmtNum = (v) => String(v);\nconst ooSaidHtml = () => '';\n"
  + "function backupSignatureWords() { return 'sig'; }\nfunction backupProblemHtml(p) { return esc(p); }\n"
  + fn("_uxRenderVerify") + "\n" + fn("_uxVerifyFrameHtml") + "\n" + fn("_uxVerifyRepaint")
  + "\nreturn {_uxRenderVerify, _uxVerifyRepaint};")(esc, window, document, window.OOI18N);

const rep = {
  ok: false, volumes: 4, problems: [], bad_volumes: ["vol-0002.ooenc"], missing_volumes: ["‮gpj.exe"],
  recoverable: true, parity: { volumes: 2, bad: [], tolerance_remaining: 1 },
};
R._uxRenderVerify(host, rep, tr);
const first = host.innerHTML;
// whole frames, names isolated as data, counts in the frame
assert.ok(first.includes('xx[Corrupt or missing volumes: <bdi translate="no">vol-0002.ooenc</bdi>, <bdi translate="no">‮gpj.exe</bdi>]'), first);
assert.ok(first.includes("xx[Parity volumes: 2]"), first);
assert.ok(first.includes("xx[Up to 1 more volumes can be lost and rebuilt from parity.]"), first);
assert.ok(!/Corrupt\/missing|can still lose|\[Parity:\]/.test(first), first);
// the walker keeps out, and the report is kept for the repaint
assert.ok(/data-i18n-dyn/.test(panel().attrs) && /data-oo-verify/.test(panel().attrs), "the panel, not the host, is marked");
assert.strictEqual(panel()._ooVerifyRep, rep);
assert.strictEqual(host._ooVerifyRep, undefined);
// a name carrying the frame's own marker characters stays inert data
R._uxRenderVerify(host, { ...rep, bad_volumes: ["\u0001names\u0002"], missing_volumes: [] }, tr);
assert.strictEqual((host.innerHTML.match(/<bdi translate/g) || []).length, 1, host.innerHTML);
assert.ok(host.innerHTML.includes("<bdi translate=\"no\">\u0001names\u0002</bdi>"), host.innerHTML);
R._uxRenderVerify(host, rep, tr);
// a live language switch repaints from memory
lang = "yy";
R._uxVerifyRepaint();
assert.ok(host.innerHTML.includes("yy[Parity volumes: 2]"), host.innerHTML);
assert.ok(!host.innerHTML.includes("xx["), host.innerHTML);
// n = 0 says it in its own words, never "Up to 0"
R._uxRenderVerify(host, { ...rep, parity: { volumes: 2, bad: [], tolerance_remaining: 0 } }, window.OOI18N.t);
assert.ok(host.innerHTML.includes("yy[No more volumes can be lost: any further loss cannot be rebuilt from parity.]"), host.innerHTML);
assert.ok(!host.innerHTML.includes("Up to"), host.innerHTML);
// another writer of the shared host (a failed verify, an import summary, a clear) takes the report
// with the panel: a switch never brings the old verdict back over the newer text
lang = "xx";
R._uxRenderVerify(host, rep, tr);
host.innerHTML = "Verification failed: boom";
lang = "yy";
R._uxVerifyRepaint();
assert.strictEqual(host.innerHTML, "Verification failed: boom");
host.innerHTML = "";
R._uxVerifyRepaint();
assert.strictEqual(host.innerHTML, "");
// a parity count the report did not carry is left out, never a dash inside the claim
R._uxRenderVerify(host, { ...rep, parity: { bad: [] } }, tr);
assert.ok(!/Parity volumes|Up to|No more volumes/.test(host.innerHTML), host.innerHTML);
R._uxRenderVerify(host, { ...rep, parity: { volumes: 2, bad: [] } }, tr);
assert.ok(host.innerHTML.includes("yy[Parity volumes: 2]") && !/Up to|No more volumes/.test(host.innerHTML), host.innerHTML);
console.log("backup verify panel row 350: all checks passed");
