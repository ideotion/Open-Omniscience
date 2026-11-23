// ooLive / ooLiveHtml / ooLiveRepaint (app-core.js), run as REAL code: row 364, the shared fix for the row 352 list.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// A node drawn through ooLive keeps its render and is redrawn in the new language on a switch, with no request; a
// release gives the node back to the i18n walker with the nodes it held before, so a button's static label is
// translated again; a node written by something else, or gone from the page, is dropped; one render that throws
// does not stop the others. The helper is EXTRACTED from the shipped module, t() is the shipped engine over the
// shipped locales, and the walker's doText()/tr() are EXTRACTED from the shipped i18n.js, so "the walker takes the
// label back" is the walker's own rule and not a stand-in.

"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");
const I18N = fs.readFileSync(path.join(__dirname, "..", "src", "static", "i18n.js"), "utf-8");

function extractFrom(src, name) {
  const at = src.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = src.indexOf("(", at), depth = 0;
  for (; i < src.length; i++) {
    if (src[i] === "(") depth++;
    else if (src[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = src.indexOf("{", i);
  let d = 0, j = open;
  for (; j < src.length; j++) {
    if (src[j] === "{") d++;
    else if (src[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return src.slice(at, j);
}
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));

// ---- a DOM just large enough: text nodes, elements, attributes, closest(), connection ----
class Text {
  constructor(v) { this.nodeValue = v; this.parentNode = null; this.nodeName = "#text"; }
  get textContent() { return this.nodeValue; }
}
class El {
  constructor(tag, attrs) { this.nodeName = tag; this.childNodes = []; this.attrs = Object.assign({}, attrs || {}); this.parentNode = null; this.attached = true; this._html = null; }
  get isConnected() { return this.attached; }
  hasAttribute(a) { return Object.prototype.hasOwnProperty.call(this.attrs, a); }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  getAttribute(a) { return this.hasAttribute(a) ? this.attrs[a] : null; }
  removeAttribute(a) { delete this.attrs[a]; }
  closest(sel) {
    assert.strictEqual(sel, '[data-i18n-dyn],[translate="no"]', "the walker's selector changed: update this harness");
    for (let e = this; e; e = e.parentNode) if (e.hasAttribute("data-i18n-dyn") || e.attrs.translate === "no") return e;
    return null;
  }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = nodes; this._html = null;
    for (const c of nodes) c.parentNode = this;
  }
  get textContent() { return this.childNodes.map((c) => c.textContent).join(""); }
  set textContent(v) { this.replaceChildren(...(v === "" ? [] : [new Text(String(v))])); }
  get innerHTML() { return this._html != null ? this._html : this.textContent; }
  set innerHTML(v) { this.replaceChildren(new Text(String(v))); this._html = String(v); }
}

// ---- the shipped walker rule (doText + doAttrs + tr), over the live map ----
function walkerFor(map) {
  const plural = I18N.slice(I18N.indexOf("// >>> PLURAL FORMS"), I18N.indexOf("// <<< PLURAL FORMS"));
  const src = ['const SKIP = /^(SCRIPT|STYLE|TEXTAREA|CODE|PRE)$/; const ATTRS = ["placeholder", "title", "aria-label"];',
    "const origText = new WeakMap(); const origAttr = new WeakMap();", plural,
    extractFrom(I18N, "tr"), extractFrom(I18N, "doText"), extractFrom(I18N, "doAttrs"), "return { doText, doAttrs };"].join("\n");
  const { doText, doAttrs } = new Function("map", src)(map);
  // apply(): every text node under the given roots, as the TreeWalker would visit them, then every element's hovers
  return function apply(...roots) {
    const visit = (n) => {
      if (n instanceof Text) { doText(n); return; }
      if (n.hasAttribute("title")) doAttrs(n);
      n.childNodes.forEach(visit);
    };
    roots.forEach(visit);
  };
}

function harness() {
  const map = {};
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const t = OOI18N.t;
  const warned = [];
  const src = ["const _ooLiveNodes = new Set();", "let _ooLiveObs = null;",
    ...["_ooLiveWatch", "_ooLiveMark", "_ooLiveForeign", "_ooLiveDrop", "_ooLiveDraw", "_ooLiveTake", "ooLive", "ooLiveHtml", "ooLiveRepaint"].map((n) => extractFrom(APP, n)),
    "return { ooLive, ooLiveHtml, ooLiveRepaint, nodes: _ooLiveNodes };"].join("\n");
  const document = { createElement: (tag) => new El(tag.toUpperCase()) };
  // A MutationObserver that records what it watches; mutate() delivers a child change, as the browser does after a write.
  const watched = new Set(); let observerCb = null;
  class MutationObserver { constructor(cb) { observerCb = cb; } observe(el, opts) { assert.deepStrictEqual(opts, {childList: true}); watched.add(el); } }
  const applied = [];
  const win = { console: true, OOI18N: { apply: (el) => { applied.push(el); apply(el); } } };
  const fns = new Function("window", "console", "document", "MutationObserver", src)(win, { warn: (...a) => warned.push(a) }, document, MutationObserver);
  const apply = walkerFor(map);
  return {
    fns, t, apply, warned, watched, applied,
    mutate(el) { if (watched.has(el) && observerCb) observerCb([{ target: el, type: "childList" }]); },
    // setLang() as shipped: swap the map, walk the page, then fire oo:langchange (here: the one listener's call)
    switchTo(l, ...roots) {
      lang = l; for (const k of Object.keys(map)) delete map[k];
      if (l !== "en") { const d = locale(l); for (const k in d) if (k !== "_meta") map[k] = d[k]; }
      apply(...roots);
      fns.ooLiveRepaint();
    },
  };
}

// 1. DRAW and REPAINT: the kept render is redrawn in the new language; the node opts out of the walker.
{
  const h = harness();
  const st = new El("SPAN");
  h.switchTo("fr", st);
  h.fns.ooLive(st, () => h.t("Running…"));
  assert.strictEqual(st.textContent, "En cours…");
  assert.ok(!st.hasAttribute("data-i18n-dyn"), "text mode leaves the node itself unmarked");
  assert.strictEqual(st.childNodes.length, 1);
  assert.ok(st.childNodes[0].hasAttribute("data-i18n-dyn"), "the text sits in one marked child, so the walker keeps out");
  h.switchTo("de", st);
  assert.strictEqual(st.textContent, "Läuft…", "repainted in the new language");
  h.switchTo("en", st);
  assert.strictEqual(st.textContent, "Running…");
  // the same node drawn again replaces the render; it is kept once
  h.fns.ooLive(st, () => h.t("Cancelling…"));
  assert.strictEqual(h.fns.nodes.size, 1);
  h.switchTo("fr", st);
  assert.strictEqual(st.textContent, "Annulation…");
}

// 1b. HTML: drawn as HTML and repainted as HTML.
{
  const h = harness();
  const out = new El("DIV");
  h.fns.ooLiveHtml(out, () => "<b>" + h.t("Running…") + "</b>");
  assert.strictEqual(out.innerHTML, "<b>Running…</b>");
  h.switchTo("fr", out);
  assert.strictEqual(out.innerHTML, "<b>En cours…</b>");
}

// 1c. THE HOVER CONVENTION: app-boot.js marks every [title] the HTML holds (a class; a role and aria-label on SVG) after
// the write. The serialised HTML changes, the text does not, and the node must still be repainted.
{
  const h = harness();
  const out = new El("DIV");
  h.fns.ooLiveHtml(out, () => '<span title="x">' + h.t("Running…") + "</span>");
  out._html = out._html.replace("<span ", '<span class="oo-tip-target" ');   // what mark() does to the live DOM
  h.switchTo("fr", out);
  assert.ok(h.fns.nodes.has(out), "a node the hover convention marked is still kept");
  assert.strictEqual(out.innerHTML, '<span title="x">En cours…</span>');
}

// 1d. A render that releases its own node: what it returns is not written into the released node.
{
  const h = harness();
  const btn = new El("BUTTON");
  btn.replaceChildren(new Text("Start sweep"));
  let release = false;
  h.fns.ooLive(btn, () => { if (release) h.fns.ooLive(btn, null); return h.t("Running…"); });
  release = true;
  h.switchTo("fr", btn);
  assert.strictEqual(btn.textContent, "Start sweep", "the static label is back, not the render's output");
  assert.ok(!btn.hasAttribute("data-i18n-dyn"));
}

// 1e. A BUTTON WITH A TRANSLATED HOVER: text mode leaves the button unmarked, so the walker keeps translating its title
// while the live label is held; HTML mode marks the host itself.
{
  const h = harness();
  const btn = new El("BUTTON", { title: "Start sweep" });
  btn.replaceChildren(new Text("Start sweep"));
  h.apply(btn);
  h.fns.ooLive(btn, () => h.t("Running…"));
  h.switchTo("fr", btn);
  assert.strictEqual(btn.textContent, "En cours…");
  assert.strictEqual(btn.getAttribute("title"), "Démarrer le balayage", "the hover follows the switch while the label is live");
  h.switchTo("de", btn);
  assert.strictEqual(btn.getAttribute("title"), "Durchlauf starten");
  const host = new El("DIV");
  h.fns.ooLiveHtml(host, () => "<b>" + h.t("Running…") + "</b>");
  assert.ok(host.hasAttribute("data-i18n-dyn"), "HTML mode marks the host");
  h.fns.ooLive(host, () => h.t("Running…"));
  assert.ok(!host.hasAttribute("data-i18n-dyn"), "and text mode on the same host takes the marker off again");
  h.fns.ooLive(host, null);
  assert.ok(!host.hasAttribute("data-i18n-dyn"));
}

// 1f. A foreign write of the SAME text in text mode (the live span replaced) is still a foreign write.
{
  const h = harness();
  const st = new El("SPAN");
  h.fns.ooLive(st, () => h.t("Running…"));
  st.textContent = "Running…";
  h.switchTo("fr", st);
  assert.ok(!h.fns.nodes.has(st), "dropped");
  assert.strictEqual(st.textContent, "En cours…", "and the walker, not ooLive, translated the plain text it now holds");
}

// 1g. The same, for text no locale translates: the walker leaves it alone, so only the span check can tell.
{
  const h = harness();
  const st = new El("SPAN");
  h.fns.ooLive(st, () => "Job 7");
  st.textContent = "Job 7";
  h.switchTo("fr", st);
  assert.ok(!h.fns.nodes.has(st), "dropped although its text is unchanged");
  assert.ok(!st.hasAttribute("data-i18n-dyn"), "and left unmarked");
}

// 1h. AN HTML HOST DRAWN OVER BY OTHER CODE is let go at once, not at the next switch, and what was written is walked:
//     a list drawn where the "Loading…" line was must not sit untranslated behind the marker.
{
  const h = harness();
  const box = new El("DIV");
  h.switchTo("fr", box);
  h.fns.ooLiveHtml(box, () => h.t("Running…"));
  assert.ok(h.watched.has(box), "an HTML host is watched");
  h.mutate(box);                          // its own draw: nothing changes
  assert.ok(h.fns.nodes.has(box) && box.hasAttribute("data-i18n-dyn"));
  box.innerHTML = "Start sweep";          // other code draws walker-translated English over it
  h.mutate(box);
  assert.ok(!h.fns.nodes.has(box), "let go");
  assert.ok(!box.hasAttribute("data-i18n-dyn"), "unmarked");
  assert.deepStrictEqual(h.applied, [box], "and walked at once");
  assert.strictEqual(box.textContent, "Démarrer le balayage", "so it reads in the page's language now");
  const span = new El("SPAN");
  h.fns.ooLive(span, () => h.t("Running…"));
  assert.ok(!h.watched.has(span), "text mode leaves its host unmarked, so nothing to watch");
  span.textContent = "other";
  h.switchTo("de", span);
  assert.ok(!h.fns.nodes.has(span));
  assert.strictEqual(h.applied.length, 1, "an unmarked host needs no extra walk: setLang already walked it");
}

// 2. RELEASE: a button's static label comes back, and the walker translates it again on every switch.
{
  const h = harness();
  const btn = new El("BUTTON");
  btn.replaceChildren(new Text("Start sweep"));
  h.apply(btn);                          // the walker has seen the English
  h.switchTo("fr", btn);
  assert.strictEqual(btn.textContent, "Démarrer le balayage");
  h.fns.ooLive(btn, () => h.t("Running…"));
  assert.strictEqual(btn.textContent, "En cours…");
  h.switchTo("de", btn);
  assert.strictEqual(btn.textContent, "Läuft…");
  h.fns.ooLive(btn, null);
  assert.ok(!btn.hasAttribute("data-i18n-dyn"), "released: the marker goes");
  assert.strictEqual(h.fns.nodes.size, 0, "released: nothing kept");
  h.apply(btn);                          // the walker's MutationObserver pass after the release
  assert.strictEqual(btn.textContent, "Durchlauf starten", "the static label is back, in the current language");
  h.switchTo("fr", btn);
  assert.strictEqual(btn.textContent, "Démarrer le balayage", "and the walker follows the next switch");
  h.switchTo("en", btn);
  assert.strictEqual(btn.textContent, "Start sweep");
  // a release of a node never taken does nothing
  const other = new El("SPAN"); other.replaceChildren(new Text("x"));
  h.fns.ooLive(other, null);
  assert.strictEqual(other.textContent, "x");
}

// 2b. A marker the page put there stays after a release (index.html hosts marked data-i18n-dyn).
{
  const h = harness();
  const host = new El("DIV", { "data-i18n-dyn": "" });
  h.fns.ooLive(host, () => h.t("Running…"));
  h.fns.ooLive(host, null);
  assert.ok(host.hasAttribute("data-i18n-dyn"), "the page's own marker is kept");
  assert.strictEqual(host.textContent, "", "a host that held nothing is left empty");
}

// 3. PRUNE: a node that left the page is dropped (on repaint, and on the next draw), and never redrawn.
{
  const h = harness();
  const a = new El("SPAN"), b = new El("SPAN"), c = new El("SPAN");
  h.fns.ooLive(a, () => h.t("Running…"));
  h.fns.ooLive(b, () => h.t("Running…"));
  a.attached = false;
  h.switchTo("fr");
  assert.ok(!h.fns.nodes.has(a), "a gone node is dropped by the repaint");
  assert.strictEqual(a.textContent, "Running…", "and is not redrawn");
  assert.strictEqual(b.textContent, "En cours…");
  b.attached = false;
  h.fns.ooLive(c, () => h.t("Running…"));
  assert.ok(!h.fns.nodes.has(b), "a gone node is dropped by the next draw too");
  assert.deepStrictEqual(Array.from(h.fns.nodes), [c]);
}

// 4. A FOREIGN WRITE: a node something else wrote since its last draw is dropped and left as it is.
{
  const h = harness();
  const st = new El("SPAN");
  h.fns.ooLive(st, () => h.t("Running…"));
  st.textContent = "an error the server sent";
  h.switchTo("fr");
  assert.strictEqual(st.textContent, "an error the server sent");
  assert.ok(!h.fns.nodes.has(st));
  assert.ok(!st.hasAttribute("data-i18n-dyn"), "handed back to the walker");
}

// 3b. BUILT, THEN ATTACHED: rows taken before they join the page are kept by the next draws, and follow a switch.
{
  const h = harness();
  const rows = [new El("SPAN"), new El("SPAN"), new El("SPAN")];
  for (const r of rows) { r.attached = false; h.fns.ooLive(r, () => h.t("Running…")); }
  for (const r of rows) r.attached = true;
  h.switchTo("fr");
  for (const r of rows) assert.strictEqual(r.textContent, "En cours…", "every row, not only the last");
  rows[0].attached = false;
  h.fns.ooLive(new El("SPAN"), () => h.t("Running…"));
  assert.ok(!h.fns.nodes.has(rows[0]), "once seen in the page, leaving it is gone");
  const lone = new El("SPAN"); lone.attached = false;
  h.fns.ooLive(lone, () => h.t("Running…"));
  h.switchTo("de");
  assert.ok(!h.fns.nodes.has(lone), "a switch while still detached drops it");
  const shown = new El("SPAN");
  h.fns.ooLive(shown, () => h.t("Running…"));   // taken while in the page
  shown.attached = false;
  h.fns.ooLive(new El("SPAN"), () => h.t("Running…"));
  assert.ok(!h.fns.nodes.has(shown), "a node taken in the page and then removed is gone at the next draw");
}

// 4b. RELEASE AFTER A FOREIGN WRITE keeps that write: the saved label does not come back over it.
{
  const h = harness();
  const btn = new El("BUTTON");
  btn.replaceChildren(new Text("Start sweep"));
  h.fns.ooLive(btn, () => h.t("Running…"));
  btn.textContent = "Saved";
  h.fns.ooLive(btn, null);
  assert.strictEqual(btn.textContent, "Saved");
  assert.strictEqual(h.fns.nodes.size, 0);
  const b2 = new El("BUTTON");
  b2.replaceChildren(new Text("Start sweep"));
  h.fns.ooLive(b2, () => "Job 7");
  b2.textContent = "Job 7";              // the same text, but not this render's span
  h.fns.ooLive(b2, null);
  assert.strictEqual(b2.childNodes.length, 1);
  assert.strictEqual(b2.childNodes[0].nodeName, "#text", "the foreign text node stays; the label is not restored over it");
}

// 4c. A RENDER THAT RE-TAKES ITS OWN NODE: the newer render's output stands.
{
  const h = harness();
  const st = new El("SPAN");
  let once = true;
  h.fns.ooLive(st, () => { if (once) { once = false; h.fns.ooLive(st, () => h.t("Done.")); } return h.t("Running…"); });
  assert.strictEqual(st.textContent, "Done.");
  h.switchTo("fr");
  assert.strictEqual(st.textContent, h.t("Done."));
}

// 5. ONE RENDER THAT THROWS does not stop the others.
{
  const h = harness();
  const bad = new El("SPAN"), good = new El("SPAN");
  let boom = false;
  h.fns.ooLive(bad, () => { if (boom) throw new Error("boom"); return h.t("Running…"); });
  h.fns.ooLive(good, () => h.t("Cancelling…"));
  boom = true;
  h.switchTo("fr");
  assert.strictEqual(good.textContent, "Annulation…");
  assert.strictEqual(bad.textContent, "Running…", "the failed node keeps what it showed");
  assert.strictEqual(h.warned.length, 1, "the failure is reported, once");
  boom = false;
  h.switchTo("de");
  assert.strictEqual(bad.textContent, "Läuft…", "and is redrawn on the next switch");
}

// 6. A missing node is ignored (the $() of an absent id).
{
  const h = harness();
  h.fns.ooLive(null, () => h.t("Running…"));
  h.fns.ooLiveHtml(undefined, () => "x");
  assert.strictEqual(h.fns.nodes.size, 0);
}

console.log("oo_live_node_test.js: OK");
