// The corpus-integrity (fixity) result, run as REAL code: R804 (row 353) and the row 352 repaint.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// A row with no stored hash was never checked, so it is counted apart as not checkable: never as
// diverged, never as evidence of tampering, never shown with the hash the server computes now, and
// with such rows present the verdict never reads "All articles match". The result is drawn from the
// last report, so a language switch repaints it without a second audit. _fixityPaint and runFixity are
// EXTRACTED from the shipped module, and t()/tf() are the shipped engine over the shipped locales.

const assert = require("assert");
const fs = require("fs");
const path = require("path");
const APP = require("./app_source.js").appJs();
const { engine } = require("./i18n_engine_node.js");

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
const locale = (l) => JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", l + ".json"), "utf-8"));

// The cap is read from the shipped source, so the test follows it if it ever moves.
const CAP_DECL = (APP.match(/const _FIXITY_LIST_CAP = \d+;/) || [])[0];
assert.ok(CAP_DECL, "_FIXITY_LIST_CAP not found -- was it renamed?");
const CAP = Number(CAP_DECL.match(/\d+/)[0]);

function harness(reports) {
  const map = Object.assign({}, locale("en"));
  let lang = "en";
  const OOI18N = engine(map, () => lang);
  const nodes = { "fixity-summary": { textContent: "", innerHTML: "" }, "fixity-result": { textContent: "", innerHTML: "" } };
  let calls = 0;
  const src = ["let _fixityState = null; " + CAP_DECL, extract("_fixityNoHash"), extract("_fixityPaint"), extract("fixityRepaint"), extract("runFixity"),
    "return { runFixity, fixityRepaint };"].join("\n");
  const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  // The shipped grouping (thin space every three digits), so plural choice sees what the panel passes.
  const fmtNum = (x) => String(Math.round(x)).replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f");
  const f = new Function("$", "api", "esc", "fmtNum", "ooSaidText", "window", "OOI18N", src);
  const fns = f((id) => nodes[id], async () => { const r = reports[calls++]; if (r instanceof Error) throw r; return r; }, esc, fmtNum, (m, k) => m[k] || "", { OOI18N }, OOI18N);
  return {
    fns, nodes, calls: () => calls,
    switchTo(l) { lang = l; for (const k of Object.keys(map)) delete map[k]; Object.assign(map, locale(l)); },
  };
}

const NOW_HASH = "c0ffee00c0ffee00c0ffee00";
(async () => {
  // Only rows without a stored hash: not checkable, never diverged, never "all match".
  {
    const h = harness([{ checked: 5, ok: 3, mismatched: 0, missing_hash: 2,
      mismatches: [{ id: 7, title: "A", stored_hash: null, computed_hash: NOW_HASH }, { id: 8, title: "B", stored_hash: null, computed_hash: NOW_HASH }] }]);
    await h.fns.runFixity({ disabled: false });
    const sum = h.nodes["fixity-summary"].innerHTML, res = h.nodes["fixity-result"].innerHTML;
    assert.ok(sum.includes("3 checked") && sum.includes("3 intact") && sum.includes("2 not checkable (no stored hash)"), sum);
    assert.ok(!sum.includes("diverged"), "a missing hash is not a divergence: " + sum);
    assert.ok(res.includes("2 articles have no capture-time hash, so they could not be checked."), res);
    assert.ok(!res.includes("All articles match"), "never a clean verdict while rows were not checkable: " + res);
    assert.ok(!res.includes("tampering"), "a missing hash is not evidence of tampering: " + res);
    assert.ok(!res.includes(NOW_HASH.slice(0, 12)) && !res.includes("≠"), "a hash computed now is never shown as a capture-time comparison: " + res);
    assert.ok(res.includes("#7 A") && res.includes("#8 B"), "the not-checkable rows are still named: " + res);

    // A language switch repaints from the kept report, with plural agreement, and never re-audits.
    h.switchTo("ru");
    h.fns.fixityRepaint();
    assert.ok(h.nodes["fixity-summary"].innerHTML.includes("2 нельзя проверить"), h.nodes["fixity-summary"].innerHTML);
    assert.ok(h.nodes["fixity-result"].innerHTML.includes("У 2 статей нет хеша"), h.nodes["fixity-result"].innerHTML);
    assert.strictEqual(h.calls(), 1, "a repaint never re-runs the audit");
  }
  // Absent and empty are the same to the backend (fixity.py), so to the UI: an empty or blank stored
  // hash, or the backend's own no-hash reason, is not checkable and never a "≠" row.
  {
    const REASON = "no stored hash recorded for this row";
    const h = harness([{ checked: 3, ok: 0, mismatched: 0, missing_hash: 3,
      mismatches: [{ id: 1, title: "E", stored_hash: "", computed_hash: NOW_HASH },
                   { id: 2, title: "F", stored_hash: "   ", computed_hash: NOW_HASH },
                   { id: 3, title: "G", stored_hash: "zzzzzzzzzzzzzzzz", computed_hash: NOW_HASH, reason: REASON }] }]);
    await h.fns.runFixity({ disabled: false });
    const res = h.nodes["fixity-result"].innerHTML;
    assert.ok(!res.includes("≠") && !res.includes(NOW_HASH.slice(0, 12)), "empty, blank or reason-marked rows are never compared: " + res);
    assert.ok(res.includes("#1 E") && res.includes("#2 F") && res.includes("#3 G"), res);
  }
  // A real mismatch: the tampering note, the row with both hashes; singular agreement.
  {
    const h = harness([{ checked: 4, ok: 3, mismatched: 1, missing_hash: 0,
      mismatches: [{ id: 9, title: "C", stored_hash: "aaaaaaaaaaaaaaaa", computed_hash: "bbbbbbbbbbbbbbbb" }] }]);
    await h.fns.runFixity({ disabled: false });
    const res = h.nodes["fixity-result"].innerHTML;
    assert.ok(h.nodes["fixity-summary"].innerHTML.includes("1 diverged"));
    assert.ok(res.includes("1 article diverges from its capture-time hash"), res);
    assert.ok(res.includes("aaaaaaaaaaaa ≠ bbbbbbbbbbbb"), res);
    assert.ok(!h.nodes["fixity-summary"].innerHTML.includes("not checkable"));
  }
  // Everything intact: the one clean verdict.
  {
    const h = harness([{ checked: 2, ok: 2, mismatched: 0, missing_hash: 0, mismatches: [] }]);
    await h.fns.runFixity({ disabled: false });
    assert.ok(h.nodes["fixity-result"].innerHTML.includes("All articles match their capture-time hash."));
    h.switchTo("fr");
    h.fns.fixityRepaint();
    assert.ok(!h.nodes["fixity-result"].innerHTML.includes("All articles match"), "the verdict follows a language switch");
    assert.ok(h.nodes["fixity-summary"].innerHTML.includes("2 vérifiés"), h.nodes["fixity-summary"].innerHTML);
  }
  // "checked" never counts the rows the same panel calls not checkable (5 examined, 2 without a hash).
  {
    const h = harness([{ checked: 5, ok: 3, mismatched: 0, missing_hash: 2, mismatches: [{ id: 7, stored_hash: null }, { id: 8, stored_hash: null }] }]);
    await h.fns.runFixity({ disabled: false });
    assert.ok(!h.nodes["fixity-summary"].innerHTML.includes("5 checked"), h.nodes["fixity-summary"].innerHTML);
  }
  // Both at once: two notes, each list under its own, each count from its own field.
  {
    const h = harness([{ checked: 1204, ok: 1200, mismatched: 1, missing_hash: 3,
      mismatches: [{ id: 9, title: "C", stored_hash: "aaaaaaaaaaaaaaaa", computed_hash: "bbbbbbbbbbbbbbbb" },
                   { id: 1, title: "D", stored_hash: null, computed_hash: NOW_HASH }, { id: 2, stored_hash: "" }, { id: 3, stored_hash: null }] }]);
    await h.fns.runFixity({ disabled: false });
    const sum = h.nodes["fixity-summary"].innerHTML, res = h.nodes["fixity-result"].innerHTML;
    assert.ok(sum.includes("1\u202f201 checked") && sum.includes("1 diverged") && sum.includes("3 not checkable"), sum);
    assert.ok(res.includes("1 article diverges") && res.includes("3 articles have no capture-time hash"), res);
    assert.ok(res.indexOf("aaaaaaaaaaaa ≠") < res.indexOf("3 articles have no"), "the mismatch row sits under the tampering note");
    assert.ok(!res.includes(NOW_HASH.slice(0, 12)) && !res.includes("All articles match"), res);
  }
  // A failure, and a reply that is not a report: an error, never a verdict, and the button comes back.
  for (const bad of [new Error("boom"), null]) {
    const h = harness([bad]);
    const btn = { disabled: false };
    await h.fns.runFixity(btn);
    assert.strictEqual(btn.disabled, false, "the button is usable again");
    assert.ok(h.nodes["fixity-summary"].innerHTML.includes('class="note err"'), h.nodes["fixity-summary"].innerHTML);
    assert.strictEqual(h.nodes["fixity-result"].innerHTML, "", "no verdict beside an error");
  }
  // Row 356: a list past the cap says how many it shows of how many; one at the cap says nothing.
  {
    const many = (k, noHash) => Array.from({ length: k }, (_, i) => noHash ? { id: i, stored_hash: null } : { id: i, stored_hash: "aaaaaaaaaaaaaaaa", computed_hash: "bbbbbbbbbbbbbbbb" });
    const g = (x) => String(x).replace(/\B(?=(\d{3})+(?!\d))/g, "\u202f");
    const D = CAP + 1034, M = CAP + 266;
    const h = harness([{ checked: D + M, ok: 0, mismatched: D, missing_hash: M, mismatches: many(D, false).concat(many(M, true)) },
      { checked: 2 * CAP, ok: 0, mismatched: CAP, missing_hash: CAP, mismatches: many(CAP, false).concat(many(CAP, true)) },
      { checked: CAP + 1, ok: 0, mismatched: 0, missing_hash: CAP + 1, mismatches: many(CAP + 1, true) },
      { checked: CAP + 1, ok: 0, mismatched: CAP + 1, missing_hash: 0, mismatches: many(CAP + 1, false) }]);
    await h.fns.runFixity({ disabled: false });
    const res = h.nodes["fixity-result"].innerHTML;
    const dLine = "Showing the first " + CAP + " of " + g(D) + ".", mLine = "Showing the first " + CAP + " of " + g(M) + ".";
    assert.ok(res.includes(dLine) && res.includes(mLine), res);
    // Each line sits under the list it counts: diverged rows, their line, the no-hash note, its rows, its line.
    const lastNe = res.lastIndexOf(" ≠ "), dAt = res.indexOf(dLine), noteAt = res.indexOf("note warn", dAt), mAt = res.indexOf(mLine);
    assert.ok(lastNe < dAt && dAt < noteAt && noteAt < mAt, "each line follows its own list");
    assert.strictEqual((res.match(/ ≠ /g) || []).length, CAP, "the diverged list is capped");
    assert.strictEqual((res.slice(noteAt).match(/#\d+/g) || []).length, CAP, "the no-hash list is capped");
    h.switchTo("fr");
    h.fns.fixityRepaint();
    assert.ok(h.nodes["fixity-result"].innerHTML.includes("Affichage des " + CAP + " premiers sur " + g(M) + "."), "the line follows a language switch");
    h.switchTo("en");
    await h.fns.runFixity({ disabled: false });
    assert.ok(!h.nodes["fixity-result"].innerHTML.includes("Showing the first"), "a list at the cap is whole, so no line");
    // One past the cap, one list at a time: exactly one line, under that list.
    for (const which of ["no-hash", "diverged"]) {
      await h.fns.runFixity({ disabled: false });
      const r = h.nodes["fixity-result"].innerHTML;
      assert.strictEqual((r.match(/Showing the first/g) || []).length, 1, which + ": " + r.slice(-300));
      assert.ok(r.includes("Showing the first " + CAP + " of " + (CAP + 1) + "."), which);
      assert.ok(r.trimEnd().endsWith("of " + (CAP + 1) + ".</div>"), which + ": the line closes its list");
    }
  }
  console.log("fixity_result_node_test.js: OK");
})().catch((e) => { console.error(e); process.exit(1); });
