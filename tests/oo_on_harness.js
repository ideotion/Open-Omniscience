// Runs one data-on-click value through the REAL src/static/oo-on.js, the way the browser
// now runs it: parsed by its grammar (never evaluated), calling only allowlisted names.
// For node suites that used to compile an inline onclick="…" body with new Function.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "oo-on.js"), "utf8");

// runBinding(value, stubs, event) -> {prevented, stopped, threw}
// `stubs` supplies the app functions the binding may call ({openLinkPreview: fn, ...}).
function runBinding(value, stubs = {}, event = {}) {
  const listeners = {};
  const errors = [];
  const sandbox = {
    console: { error: (e) => errors.push(e), warn: (e) => errors.push(e), log() {} },
    document: {
      documentElement: { addEventListener(t, f) { listeners[t] = f; } },
      getElementById: () => null,
      body: { classList: { toggle() {} } },
    },
    ...stubs,
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(SRC, sandbox);
  const el = { nodeType: 1, getAttribute: (n) => (n === "data-on-click" ? value : null),
               hasAttribute: (n) => n === "data-on-click" };
  const ev = Object.assign({
    type: "click", target: el, bubbles: true, cancelBubble: false, defaultPrevented: false,
    composedPath: () => [el],
    stopPropagation() { this.cancelBubble = true; },
    preventDefault() { this.defaultPrevented = true; },
  }, event);
  listeners.click(ev);
  const threw = errors.length ? errors[0] : null;
  return { prevented: ev.defaultPrevented, stopped: ev.cancelBubble, threw };
}

module.exports = { runBinding };
