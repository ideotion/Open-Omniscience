// Row 326: data is never translated, and the AI activity feed and the custody table speak the reader's language.
//
// Part 1 runs the REAL src/static/i18n.js over a small fake DOM with the REAL French locale file:
//   - a keyword whose text is "content" is left as written (the bare key is gone, and the node is marked data);
//   - a word that IS still a bare key ("person") is translated in chrome and left alone inside translate="no";
//   - a title attribute inside translate="no" is left alone too.
// Part 2 runs the real feed and custody helpers out of the app modules.
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");

const STATIC = path.join(__dirname, "..", "src", "static");
const FR = JSON.parse(fs.readFileSync(path.join(STATIC, "locales", "fr.json"), "utf8"));

// ---------------------------------------------------------------- a fake DOM, just enough for the walker
function matches(el, sel) {
  if (sel === '[translate="no"]') return el.attrs && el.attrs.translate === "no";
  if (sel === "[data-i18n-dyn]") return !!(el.attrs && "data-i18n-dyn" in el.attrs);
  throw new Error("selector not modelled: " + sel);
}
function el(nodeName, attrs, kids) {
  const e = {
    nodeName, attrs: Object.assign({}, attrs || {}), childNodes: [], parentNode: null,
    closest(sel) {
      const alts = sel.split(",").map((s) => s.trim());
      for (let n = this; n && n.attrs; n = n.parentNode) if (alts.some((s) => matches(n, s))) return n;
      return null;
    },
    hasAttribute(a) { return a in this.attrs; },
    getAttribute(a) { return a in this.attrs ? this.attrs[a] : null; },
    setAttribute(a, v) { this.attrs[a] = String(v); },
    querySelectorAll(sel) {
      const want = sel.replace(/[[\]]/g, "").split(",");
      const out = [];
      (function walk(n) {
        for (const c of n.childNodes) if (c.attrs) { if (want.some((a) => a in c.attrs)) out.push(c); walk(c); }
      })(this);
      return { forEach: (f) => out.forEach(f) };
    },
  };
  for (const k of kids || []) { k.parentNode = e; e.childNodes.push(k); }
  return e;
}
const text = (v) => ({ nodeValue: v, parentNode: null });

const chromeKw = text("Keyword triage");
const chromePerson = text("person");
const dataContent = text("content");
const dataContentUnmarked = text("content");
const dataPerson = text("person");
const titled = el("SPAN", { title: "person" }, [text("x")]);
const body = el("BODY", {}, [
  el("DIV", {}, [chromeKw]),
  el("BUTTON", {}, [chromePerson]),
  el("SPAN", { class: "pill" }, [el("SPAN", { translate: "no" }, [dataContent])]),
  el("SPAN", {}, [dataContentUnmarked]),
  el("SPAN", { translate: "no" }, [dataPerson, titled]),
]);

const document = {
  readyState: "complete", body, documentElement: {},
  getElementById: () => null, addEventListener() {}, dispatchEvent() {},
  createTreeWalker(root) {
    const nodes = [];
    (function walk(n) { for (const c of n.childNodes) { if (c.attrs) walk(c); else nodes.push(c); } })(root);
    let i = 0;
    return { nextNode: () => (i < nodes.length ? nodes[i++] : null) };
  },
};
const window = {};
const localStorage = { getItem: () => "fr", setItem() {} };
const fetch = async () => ({ ok: true, json: async () => FR });
new Function("window", "document", "localStorage", "fetch", "NodeFilter", "CustomEvent",
  fs.readFileSync(path.join(STATIC, "i18n.js"), "utf8"))(window, document, localStorage, fetch, { SHOW_TEXT: 4 }, function () {});

const seen = new Set();
const t = (s) => { seen.add(s); return "T[" + s + "]"; };
const tf = (s, v) => { seen.add(s); return "T[" + String(s).replace(/\{(\w+)\}/g, (m, k) => (v && v[k] != null) ? String(v[k]) : m) + "]"; };

window.OOI18N.ready.then(() => {
  // the walker is live: chrome is translated
  assert.strictEqual(chromeKw.nodeValue, FR["Keyword triage"], "the walker did not run");
  assert.ok(FR.person && FR.person !== "person", "fixture: person must still be a bare key in fr");
  assert.strictEqual(chromePerson.nodeValue, FR.person, "chrome with a bare key is translated");
  // data is not
  for (const k of ["junk", "content", "unsure"]) assert.ok(!(k in FR), "bare verdict key still in fr.json: " + k);
  assert.strictEqual(dataContent.nodeValue, "content", "a keyword was translated");
  assert.strictEqual(dataContentUnmarked.nodeValue, "content", "an unmarked keyword 'content' was translated");
  assert.strictEqual(dataPerson.nodeValue, "person", "a keyword equal to a bare key was translated inside translate=no");
  assert.strictEqual(titled.attrs.title, "person", "a title inside translate=no was translated");

  // ---------------------------------------------------------------- part 2: the real helpers
  const APP = require("./app_source.js").appJs();
  const fn = (name) => {
    const at = APP.indexOf("function " + name + "(");
    assert.ok(at >= 0, name);
    let i = APP.indexOf("{", APP.indexOf(")", at)), depth = 0;
    for (; i < APP.length; i++) { if (APP[i] === "{") depth++; else if (APP[i] === "}" && --depth === 0) break; }
    return APP.slice(at, i + 1);
  };
  const constant = (name) => {
    const at = APP.indexOf("const " + name + " = ");
    assert.ok(at >= 0, name);
    return APP.slice(at, APP.indexOf(";\n", at) + 1);
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m]));
  const src = [constant("_AI_TOTALS_WORDS"), constant("_AI_FIELD_WORDS"), constant("_AI_KIND_WORDS"), constant("_aiOwn"),
    constant("_AI_COORDINATOR_IDLE_NOTE"), fn("_aiTotalsBit"), fn("_aiKindHtml"), fn("_aiCoordinatorNote"),
    fn("_aiTriageVerdictWords"), fn("custodyEntryTimeHtml")].join("\n")
    + "\nreturn {_AI_TOTALS_WORDS, _AI_KIND_WORDS, _AI_COORDINATOR_IDLE_NOTE, _aiTotalsBit, _aiKindHtml, _aiCoordinatorNote, _aiTriageVerdictWords, custodyEntryTimeHtml};";
  const R = new Function("esc", src)(esc);

  // verdicts: labelled keys, never the bare word
  for (const v of ["junk", "content", "unsure"]) assert.strictEqual(R._aiTriageVerdictWords(v, t), "T[Verdict: " + v + "]");
  assert.strictEqual(R._aiTriageVerdictWords("<new>", t), "<new>");
  // totals: known counter worded, unknown as code, nested spelled out, never [object Object]
  assert.strictEqual(R._aiTotalsBit("keywords_in", 12, t, tf), "T[Keywords sent] 12");
  assert.strictEqual(R._aiTotalsBit("fresh_counter", 3, t, tf), '<code dir="ltr">fresh_counter</code> 3');
  const fg = R._aiTotalsBit("field_gated", { who: 1, where: 2, when: 0, why: 5 }, t, tf);
  assert.ok(!fg.includes("[object Object]"), fg);
  assert.strictEqual(fg, 'T[Fields discarded (language not cleared)] (T[Names: 1], T[Places: 2], T[Dates: 0], <code dir="ltr">why</code> 5)');
  assert.strictEqual(R._aiTotalsBit("<b>", 1, t, tf), '<code dir="ltr">&lt;b&gt;</code> 1');
  // stored kinds
  assert.strictEqual(R._aiKindHtml("ai-who", t), "T[Names (AI)]");
  assert.strictEqual(R._aiKindHtml("language", t), "T[Languages detected]");
  assert.strictEqual(R._aiKindHtml("ai-new", t), '<code dir="ltr">ai-new</code>');
  // the coordinator note: by code, else as sent
  assert.strictEqual(R._aiCoordinatorNote({ note: "x", note_code: "lane-runs-members-directly" }, t), "T[" + R._AI_COORDINATOR_IDLE_NOTE + "]");
  assert.strictEqual(R._aiCoordinatorNote({ note: "an older server's words" }, t), "an older server's words");
  assert.strictEqual(R._aiCoordinatorNote({ note: "y", note_code: "other" }, t), "y");
  // custody time cell
  assert.strictEqual(R.custodyEntryTimeHtml({ kind: "local", asserted_time: "2026-11-22T10:00:00Z" }, t), "2026-11-22T10:00:00Z");
  assert.strictEqual(R.custodyEntryTimeHtml({ kind: "opentimestamps", asserted_time: null }, t), "T[OpenTimestamps: not yet confirmed in Bitcoin]");
  assert.strictEqual(R.custodyEntryTimeHtml({ kind: "chain<x>", asserted_time: null }, t), '<code dir="ltr">chain&lt;x&gt;</code>');
  assert.strictEqual(R.custodyEntryTimeHtml(null, t), "—");

  // every key the helpers used, plus the table words, for the Python half to check x12
  for (const k of Object.values(R._AI_TOTALS_WORDS)) seen.add(k);
  for (const k of Object.values(R._AI_KIND_WORDS)) seen.add(k);
  console.log(JSON.stringify([...seen].sort()));
  console.log("raw values row 326: all checks passed");
}).catch((e) => { console.error(e); process.exit(1); });
