// The Trends tab's weather-signals layer, run as REAL code (row 122, register ruling G7: a toggleable layer, OFF by default).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// What it must NOT do is most of what it is:
//   * with nothing stored, the layer is off and NOTHING is read;
//   * a browser that refuses storage reads as off, never as on, and never throws;
//   * switched off, the rows go and the switch says off;
//   * a value from the store is text, never markup.
// EXTRACTED from the shipped module, never re-typed.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  const open = APP.indexOf("{", APP.indexOf(")", at));
  let d = 0, j = open;
  for (; j < APP.length; j++) {
    if (APP[j] === "{") d++;
    else if (APP[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  const asyncAt = APP.lastIndexOf("async ", at);
  return (asyncAt === at - 6 ? "async " : "") + APP.slice(at, j);
}
function extractConst(name) {
  const at = APP.indexOf("const " + name + " = ");
  assert.ok(at !== -1, "const " + name + " not found -- was it renamed?");
  return APP.slice(at, APP.indexOf(";\n", at) + 1);
}

function el(id) {
  const e = { id, attrs: {}, style: {}, children: [], listeners: {}, textContent: "", innerHTML: "", title: "" };
  e.setAttribute = (k, v) => { e.attrs[k] = String(v); };
  e.getAttribute = (k) => e.attrs[k];
  e.appendChild = (c) => { e.children.push(c); return c; };
  e.addEventListener = (k, f) => { e.listeners[k] = f; };
  Object.defineProperty(e, "textContent", {
    get() { return e._text || ""; },
    set(v) { e._text = String(v); if (v === "") { e.children = []; e.innerHTML = ""; } },
  });
  return e;
}

function makeWorld({ store, storageThrows, payload }) {
  const nodes = { "trd-wsig-toggle": el("trd-wsig-toggle"), "trd-wsig": el("trd-wsig") };
  const calls = [], opened = [];
  const ls = {
    getItem(k) { if (storageThrows) throw new Error("blocked"); return Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null; },
    setItem(k, v) { if (storageThrows) throw new Error("blocked"); store[k] = String(v); },
    removeItem(k) { if (storageThrows) throw new Error("blocked"); delete store[k]; },
  };
  const src =
    extractConst("esc") + "\n" + extractConst("_WSIG_KEY") + "\n" +
    ["weatherSignalsOn", "toggleWeatherSignals", "paintWeatherSignals"].map(extract).join("\n") + "\n" +
    "return {weatherSignalsOn, toggleWeatherSignals, paintWeatherSignals};";
  const api = async (url) => { calls.push(url); return payload; };
  const document = { createElement: () => el("") };
  const F = new Function("$", "api", "localStorage", "document", "window", "openAnalysisForIds", src)(
    (id) => nodes[id], api, ls, document, {}, (ids, label) => opened.push({ ids, label }));
  return { F, nodes, calls, opened, store };
}

const ROW = { label: "<b>Flood</b>", signal: "flood", place: "Lyon", place_country: "FR", window_start: "2026-10-01",
  window_end: "2026-10-07", n_articles: 4, article_ids: [1, 2, 3, 4], threshold_rule: ">= 3 articles" };
const PAYLOAD = { derived_at: "2026-11-16T03:00:00+00:00", signals: [ROW] };

(async () => {
  // 1. Off by default: nothing stored, nothing read, the switch says off.
  {
    const w = makeWorld({ store: {}, payload: PAYLOAD });
    assert.strictEqual(w.F.weatherSignalsOn(), false);
    await w.F.paintWeatherSignals();
    assert.deepStrictEqual(w.calls, [], "off must read nothing");
    assert.strictEqual(w.nodes["trd-wsig-toggle"].attrs["aria-checked"], "false");
    assert.strictEqual(w.nodes["trd-wsig-toggle"].textContent, "Weather signals: off");
    assert.strictEqual(w.nodes["trd-wsig"].children.length, 0);
  }
  // 2. Storage refused: reads as off, toggling never throws, nothing is read until switched on for this view.
  {
    const w = makeWorld({ store: {}, storageThrows: true, payload: PAYLOAD });
    assert.strictEqual(w.F.weatherSignalsOn(), false);
    await w.F.paintWeatherSignals();
    assert.deepStrictEqual(w.calls, []);
  }
  // 3. Switched on: one local read, rows as text, a click opens exactly the signal's articles; the state is remembered.
  {
    const w = makeWorld({ store: {}, payload: PAYLOAD });
    w.F.toggleWeatherSignals();
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(w.store["oo.trends.weatherSignals"], "1");
    assert.deepStrictEqual(w.calls, ["/api/signals/weather-signals"]);
    assert.strictEqual(w.nodes["trd-wsig-toggle"].attrs["aria-checked"], "true");
    const host = w.nodes["trd-wsig"];
    assert.strictEqual(host.children.length, 2, "a header line and the list");
    assert.ok(host.children[0].textContent.includes("2026-11-16") && host.children[0].textContent.includes("1"));
    const btn = host.children[1].children[0];
    assert.ok(btn.textContent.startsWith("<b>Flood</b> · Lyon (FR) · 2026-10-01 – 2026-10-07"), btn.textContent);
    assert.ok(btn.textContent.includes("anomaly not checked"));
    assert.strictEqual(btn.innerHTML, "", "a stored label is text, never markup");
    btn.listeners.click();
    assert.deepStrictEqual(w.opened[0].ids, [1, 2, 3, 4]);
    // 4. Switched off again: the rows go, nothing more is read, the store forgets it.
    w.F.toggleWeatherSignals();
    await new Promise((r) => setTimeout(r, 0));
    assert.strictEqual(w.calls.length, 1);
    assert.strictEqual(host.children.length, 0);
    assert.ok(!("oo.trends.weatherSignals" in w.store));
    assert.strictEqual(w.nodes["trd-wsig-toggle"].attrs["aria-checked"], "false");
  }
  // 5. On with an empty store: an honest empty line, never a blank.
  {
    const w = makeWorld({ store: { "oo.trends.weatherSignals": "1" }, payload: { derived_at: null, signals: [] } });
    await w.F.paintWeatherSignals();
    assert.ok(w.nodes["trd-wsig"].innerHTML.includes("No weather signal has been derived yet."));
  }
  console.log("weather signals layer: all checks passed");
})().catch((e) => { console.error(e); process.exit(1); });
