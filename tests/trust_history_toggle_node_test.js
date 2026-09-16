// The Q701-note trust toggle's real branches, run as real code.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHY THIS SUITE EXISTS. The pytest half of this slice can assert that the markup
// carries the checkbox and that the server resolves three states -- it cannot see a
// LIVE BRANCH. `_uxImTrust()` returning `null` instead of `false` for a hidden row is
// exactly such a branch, and it is the one that decides whether an invisible control
// speaks for the operator: `false` would tell the server "this operator declined the
// history" on an import where they were never shown the question, and the restore would
// then re-download a corpus the backup already had. A source-level grep sees the word
// `null` in the file either way.
//
// EXTRACTED from the shipped module, never re-typed: a re-typed copy passes while the
// real function is broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace (the recorded ooChart trap: a `{}` in a
  // default parameter truncates a brace-first slice to the signature alone).
  let at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  // Keep an `async` prefix: dropping it yields a body with a bare `await` in it, which
  // is a SyntaxError -- a failure that reads like a broken harness rather than a
  // broken function, so it is handled rather than tripped over.
  if (APP.slice(at - 6, at) === "async ") at -= 6;
  let i = APP.indexOf("(", APP.indexOf("function", at)), depth = 0;
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

// --- the harness ------------------------------------------------------------------
// A DOM small enough to read, seeded from the SHIPPED markup's own initial state:
// `#ux-imp-trust-row` ships `style="display:none"`, so a run where the scan never
// offered the toggle is the default here too.
let apiCalls = [];
let apiImpl = async () => ({});

function makeDom(opts) {
  const o = opts || {};
  const row = { style: { display: o.display === undefined ? "none" : o.display } };
  const box = { checked: o.checked === undefined ? false : o.checked };
  return {
    row, box,
    getElementById(id) {
      if (id === "ux-imp-trust-row") return o.noRow ? null : row;
      if (id === "ux-imp-trust") return o.noBox ? null : box;
      return null;
    },
  };
}

function load(dom) {
  const src =
    "var document = __dom;\n" +
    "var api = async function (u) { __calls.push(u); return __api(u); };\n" +
    extract("_uxImTrustRow") + "\n" +
    extract("_uxImTrust") + "\n" +
    "module.exports = { _uxImTrustRow, _uxImTrust };";
  const m = { exports: {} };
  new Function("module", "exports", "__dom", "__calls", "__api", src)(
    m, m.exports, dom, apiCalls, (u) => apiImpl(u)
  );
  return m.exports;
}

(async () => {
  // --- the hidden row NEVER answers for the operator -------------------------------
  {
    const dom = makeDom({ display: "none", checked: true });
    const { _uxImTrust } = load(dom);
    assert.strictEqual(
      _uxImTrust(), null,
      "a hidden toggle returned a boolean -- the server would read a choice off a " +
      "control the operator was never shown"
    );
  }

  // The sharp edge: a PREVIOUS scan left the box unchecked, the next scan finds only
  // blobs, so the row hides. `false` here would assert a refusal nobody made on THIS
  // import. This is the whole reason the function returns three states.
  {
    const dom = makeDom({ display: "block", checked: false });
    const { _uxImTrustRow, _uxImTrust } = load(dom);
    assert.strictEqual(_uxImTrust(), false, "a shown, unchecked box must read as false");
    await _uxImTrustRow(false);
    assert.strictEqual(dom.row.style.display, "none");
    assert.strictEqual(
      _uxImTrust(), null,
      "a stale unchecked box spoke for an import whose toggle was never offered"
    );
  }

  // Missing markup is the same silence, not a fabricated `false`.
  for (const missing of [{ noRow: true }, { noBox: true }]) {
    const { _uxImTrust } = load(makeDom(missing));
    assert.strictEqual(_uxImTrust(), null, "absent markup invented an answer");
  }

  // --- the shown row reports what the operator sees --------------------------------
  {
    const dom = makeDom({ display: "block", checked: true });
    const { _uxImTrust } = load(dom);
    assert.strictEqual(_uxImTrust(), true);
    dom.box.checked = false;
    assert.strictEqual(_uxImTrust(), false, "the toggle does not track the checkbox");
  }

  // --- seeding: the row opens on the answer the operator already gave --------------
  // Driven in BOTH directions. Seeding that always produced `true` would satisfy a
  // one-sided test while silently discarding a stored "do not trust".
  for (const stored of [true, false]) {
    apiCalls = [];
    apiImpl = async () => ({ trust_backup_fetch_history: stored });
    const dom = makeDom({ display: "none", checked: !stored });
    const { _uxImTrustRow, _uxImTrust } = load(dom);
    await _uxImTrustRow(true);
    assert.strictEqual(dom.row.style.display, "block");
    assert.deepStrictEqual(apiCalls, ["/api/settings"], "the stored answer was not read");
    assert.strictEqual(
      _uxImTrust(), stored,
      "the dialog opened on " + _uxImTrust() + " while the stored answer was " + stored
    );
  }

  // A settings payload with no such key at all (an older settings file) falls to the
  // SHIPPED default, which is trust.
  {
    apiCalls = [];
    apiImpl = async () => ({});
    const dom = makeDom({ display: "none", checked: false });
    const { _uxImTrustRow, _uxImTrust } = load(dom);
    await _uxImTrustRow(true);
    assert.strictEqual(_uxImTrust(), true, "a missing key must resolve to the shipped default");
  }

  // An UNREADABLE store falls to the shipped default too -- never to whatever the box
  // happened to hold, which would show a choice nobody made.
  {
    apiCalls = [];
    apiImpl = async () => { throw new Error("settings unreadable"); };
    const dom = makeDom({ display: "none", checked: false });
    const { _uxImTrustRow, _uxImTrust } = load(dom);
    await _uxImTrustRow(true);
    assert.strictEqual(
      _uxImTrust(), true,
      "an unreadable settings store left the stale box value on screen"
    );
  }

  // --- hiding costs nothing ---------------------------------------------------------
  // The negative-space twin of the seeding tests: a row that is not offered must not
  // read the settings store at all, or every .eml import pays for a control it never shows.
  {
    apiCalls = [];
    apiImpl = async () => ({ trust_backup_fetch_history: true });
    const dom = makeDom({ display: "block", checked: true });
    const { _uxImTrustRow } = load(dom);
    await _uxImTrustRow(false);
    assert.deepStrictEqual(apiCalls, [], "hiding the toggle still read /api/settings");
  }

  console.log("trust-history toggle: all assertions passed");
})().catch((e) => { console.error(e); process.exit(1); });
