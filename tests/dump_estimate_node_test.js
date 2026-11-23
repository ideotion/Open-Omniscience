// The Wikipedia dump size line (Living sources), run as REAL code: the row 352 repaint.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// #dump-estimate is data-i18n-dyn, so nothing but _dumpEstimatePaint redraws it. Each state must
// redraw in the language now current, a declined consent must leave the line and state untouched,
// and a repaint must never fetch. _dumpEstimatePaint, _dumpEstimateSet and refreshDumpSizes are
// EXTRACTED from the shipped module.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const marker = "function " + name + "(";
  const at0 = APP.indexOf(marker);
  assert.ok(at0 !== -1, name + " not found -- was it renamed?");
  const at = APP.slice(at0 - 6, at0) === "async " ? at0 - 6 : at0;
  let i = APP.indexOf("(", at0), depth = 0;
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

function harness({ picked, consent, reply }) {
  const dict = {};
  const OOI18N = { t: (s) => dict[s] || s };
  const out = { textContent: "" };
  let calls = 0;
  const src = ["let _dumpEstState = null; const _dumpExactSizes = {};", extract("_dumpSizeReason"),
    extract("_dumpEstimatePaint"), extract("_dumpEstimateSet"), extract("refreshDumpSizes"),
    "return { refreshDumpSizes, _dumpEstimatePaint, _dumpExactSizes };"].join("\n");
  const f = new Function("$", "api", "ensureOnline", "dumpSelected", "renderWikiLanguages", "_fmtBytes", "ooLabelText", "window", "OOI18N", src);
  const fns = f((id) => (id === "dump-estimate" ? out : null),
    async () => { calls++; if (reply instanceof Error) throw reply; return reply; },
    async () => consent, () => picked, () => {}, (b) => b + " B", (l, v) => l + ": " + v, { OOI18N }, OOI18N);
  return { fns, out, dict, calls: () => calls };
}

(async () => {
  // done: the label:value line, redrawn in the new language without a second request.
  {
    const h = harness({ picked: ["en", "fr"], consent: true, reply: { sizes: [{ wiki: "en", size_bytes: 10 }, { wiki: "fr", size_bytes: null, reason: "x" }], not_probed: ["de"] } });
    await h.fns.refreshDumpSizes();
    assert.ok(h.out.textContent.startsWith("Read from the dump host: en 10 B — Could not be read: fr — "), h.out.textContent);
    assert.ok(h.out.textContent.endsWith(" — Not attempted (batch limit): de"), h.out.textContent);
    assert.strictEqual(h.fns._dumpExactSizes.en, 10);
    h.dict["Read from the dump host"] = "Lu sur l'hôte";
    h.fns._dumpEstimatePaint();
    assert.ok(h.out.textContent.startsWith("Lu sur l'hôte: en 10 B"), h.out.textContent);
    assert.strictEqual(h.calls(), 1, "a repaint never fetches");
  }
  // error: the label follows the language; the server's message is kept as it came.
  {
    const h = harness({ picked: ["en"], consent: true, reply: new Error("boom") });
    await h.fns.refreshDumpSizes();
    assert.strictEqual(h.out.textContent, "Could not read the sizes: boom");
    h.dict["Could not read the sizes"] = "Lecture impossible";
    h.fns._dumpEstimatePaint();
    assert.strictEqual(h.out.textContent, "Lecture impossible: boom");
  }
  // pick: nothing selected never probes, and the line follows the language.
  {
    const h = harness({ picked: [], consent: true, reply: {} });
    await h.fns.refreshDumpSizes();
    assert.strictEqual(h.out.textContent, "Select one or more editions first.");
    h.dict["Select one or more editions first."] = "Choisissez une édition.";
    h.fns._dumpEstimatePaint();
    assert.strictEqual(h.out.textContent, "Choisissez une édition.");
    assert.strictEqual(h.calls(), 0);
  }
  // declined consent: no request, and the line and its state stay as they were.
  {
    const h = harness({ picked: ["en"], consent: false, reply: {} });
    h.out.textContent = "earlier";
    await h.fns.refreshDumpSizes();
    assert.strictEqual(h.out.textContent, "earlier");
    h.fns._dumpEstimatePaint();
    assert.strictEqual(h.out.textContent, "earlier", "no state was set, so a repaint draws nothing new");
    assert.strictEqual(h.calls(), 0, "a declined consent never fetches");
  }
  console.log("dump_estimate_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
