// The export completion panel, run as REAL code (S04-03; R4, Q208 = a, Q218 = a).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHAT IS BEING GUARDED IS A SET OF DISTINCTIONS THAT LOOK IDENTICAL IN A DIFF and
// are opposite on screen, which is exactly what a source-level assertion cannot see:
//
//   * "verified" versus the FOUR ways a set is not verified -- off, cancelled,
//     unavailable, and FAILED. Collapsing them is how a corrupt backup comes to read
//     like one the operator simply chose not to check;
//   * an unmeasured elapsed span rendering as "—" rather than as 0, because a None
//     that means "unmeasured" and a real zero are different facts;
//   * an EMPTY licence list drawing "no attribution line applies" rather than an
//     empty Licences row, and an attribution REFUSAL (the Q823 seam) drawing the
//     refusal instead of silence.
//
// EXTRACTED from the shipped module rather than re-typed: a re-typed copy would pass
// while the real renderer was broken.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
  // Balanced PARENS first, then the body brace: a `{}` in a default parameter would
  // otherwise truncate the slice to the signature alone.
  const at = APP.indexOf("function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = APP.indexOf("(", at), depth = 0;
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

// A DOM stub just wide enough for the renderer: one host element whose innerHTML we
// read back. `window` is defined so both halves of `window.OOI18N && OOI18N.tf`
// resolve (a sandbox defining only the property raises ReferenceError on a bare
// global read -- the recorded node-harness trap).
const host = { innerHTML: "" };
const src =
  "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
  "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
  "function humanBytes(n){return String(n)+' B';}\n" +
  "var window = {};\n" +
  "var document = { getElementById: function(id){ return id === 'ux-summary' ? HOST : null; } };\n" +
  extract("_uxRenderExportPanel") + "\n" +
  extract("_uxVerifySentence") + "\n" +
  extract("_uxVerifyDetail") + "\n" +
  "module.exports = { _uxRenderExportPanel, _uxVerifySentence, _uxVerifyDetail };";
const { _uxRenderExportPanel, _uxVerifySentence, _uxVerifyDetail } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", "HOST", src)(m, m.exports, host);
  return m.exports;
})();

const t = (s) => s;
const base = {
  destination: "/mnt/stick/202609121045_OpenOmniscience_Backup",
  folder: "202609121045_OpenOmniscience_Backup",
  corpus_included: true,
  volumes: { count: 5, bytes: 800, plaintext_bytes: 540, parity: true },
  tables: [{ name: "articles", rows: 300 }, { name: "sources", rows: 9 }],
  files: [],
  elapsed: { corpus_s: 12.5, files_s: null, files_s_reason: "no large-data files were copied" },
  encryption: { corpus_encrypted: true, files_encrypted: null, note: "n" },
  schema: { backup_schema: "oo-backup-2", container: "oo-volumes-2", alembic_rev: "abc123" },
  app_version: "0.3.0",
  verify: { state: "verified", total: 5, bad: [] },
  attribution: [],
  attribution_error: null,
};
const render = (over) => { host.innerHTML = ""; _uxRenderExportPanel({ ...base, ...over }, t); return host.innerHTML; };

// --- the four not-verified cases stay apart -------------------------------- //
{
  assert.ok(/Verified — all 5 volumes/.test(_uxVerifySentence({ state: "verified", total: 5 }, t)),
    "a clean set does not read as verified");

  const failed = _uxVerifySentence({ state: "failed", total: 5, bad: ["vol-a.ooenc", "vol-b.ooenc"] }, t);
  assert.ok(/NOT verified/.test(failed), "a FAILED re-read does not say so: " + failed);
  assert.ok(failed.includes("vol-a.ooenc") && failed.includes("vol-b.ooenc"),
    "a failed verify must NAME the volumes: " + failed);
  assert.ok(/2 of 5/.test(failed), "the failed count is wrong: " + failed);

  const off = _uxVerifySentence({ state: "off" }, t);
  assert.ok(/turned off/.test(off) && !/^Verified/.test(off), "'off' read as verified: " + off);

  const stopped = _uxVerifySentence({ state: "stopped" }, t);
  assert.ok(/cancelled/.test(stopped) && /not read back/.test(stopped),
    "a cancelled re-read must say the volumes were written but not read back: " + stopped);

  // The backend's own English reason must NOT be the visible sentence (a caveat
  // surface ships x12); it rides the hover instead.
  const unavailable = _uxVerifySentence({ state: "unavailable", reason: "ENGLISH FROM THE JOB" }, t);
  assert.ok(/could not be read back/.test(unavailable), "the unavailable case is not named: " + unavailable);
  assert.ok(!/ENGLISH FROM THE JOB/.test(unavailable),
    "a backend English string reached the translated sentence: " + unavailable);
  const unknown = _uxVerifySentence({ state: "unknown", reason: "x" }, t);
  assert.ok(/no verify result/.test(unknown), "an absent verdict is not named: " + unknown);

  // None of the four may be mistaken for the first.
  for (const st of ["failed", "off", "stopped", "unavailable"]) {
    const s = _uxVerifySentence({ state: st, total: 5, bad: ["v"] }, t);
    assert.ok(!/^Verified —/.test(s), st + " reads as verified: " + s);
  }
}

// --- a failed verify paints the alarming style, a clean one does not -------- //
{
  assert.ok(!/note err/.test(render({})), "a verified export drew an error note");
  const bad = render({ verify: { state: "failed", total: 5, bad: ["vol-00001.ooenc"], method: "sha-256 re-read" } });
  assert.ok(/note err/.test(bad), "a FAILED verify drew no error style");
  assert.ok(bad.includes("vol-00001.ooenc"), "the bad volume is not named in the panel");
  assert.strictEqual(_uxVerifyDetail({ reason: "r", method: "m" }), "r · m");
  assert.strictEqual(_uxVerifyDetail({}), "", "an empty detail must draw no hover at all");
  assert.ok(/title="sha-256 re-read"/.test(bad), "the method is not carried on the hover: " + bad);
}

// --- an unmeasured span is never a zero ------------------------------------ //
{
  const out = render({ files: [{ category: "wiki_dumps", files: 2, bytes: 90 }],
                       elapsed: { corpus_s: 12.5, files_s: null, files_s_reason: "not timed" } });
  assert.ok(/not recorded/.test(out), "an unmeasured files span did not say so: " + out);
  assert.ok(!/\b0(\.0)? (s|min)\b/.test(out), "an unmeasured span rendered as zero: " + out);
}

// --- a MEASURED ZERO must DRAW, where an absence must not ------------------ //
// These two are one character apart in source (`x != null` versus a truthiness test)
// and opposite on screen: a measured 0 is a real observation an operator needs, and an
// absent value is a question nobody answered. Only running the renderer on both tells
// them apart.
{
  const zero = render({
    volumes: { count: 0, bytes: 0, plaintext_bytes: 0, parity: false },
    elapsed: { corpus_s: 0, files_s: null, files_s_reason: "not timed" },
  });
  assert.ok(/>0 · 0 B/.test(zero), "a measured zero volume count was not drawn: " + zero);
  assert.ok(/0\.0 s/.test(zero), "a measured zero elapsed was not drawn: " + zero);
  assert.ok(/none/.test(zero), "parity: false must draw 'none', not a blank");

  const absent = render({
    volumes: { count: null, bytes: null, plaintext_bytes: null, parity: false },
    elapsed: { corpus_s: null, files_s: null, files_s_reason: "not timed" },
  });
  assert.ok(/—/.test(absent), "an absent figure did not draw a dash: " + absent);
  assert.ok(!/>0 · 0 B/.test(absent), "an absent volume count was drawn as zero: " + absent);
  assert.ok(!/0\.0 s/.test(absent), "an absent elapsed was drawn as zero: " + absent);
}

// --- articles lead, and an empty table is counted rather than listed -------- //
{
  const out = render({ tables: [{ name: "articles", rows: 300 }, { name: "keyword_mentions", rows: 900 },
                                { name: "law_documents", rows: 0 }] });
  assert.ok(out.indexOf("articles") < out.indexOf("keyword_mentions"),
    "articles must lead the counts even when another table is larger");
  assert.ok(!/law_documents/.test(out), "an empty table was listed as content");
  assert.ok(/1 more tables are empty/.test(out), "the empty tables were not counted: " + out);
}

// --- the licence block: absent, present, and refused ----------------------- //
{
  const none = render({ attribution: [] });
  assert.ok(/no attribution line applies/.test(none),
    "an empty licence list drew nothing at all, which reads as a failure to compute");

  const some = render({ attribution: [{ key: "wikipedia", text: "Wikipedia text — CC BY-SA 4.0", because: "table:wiki_pages" }] });
  assert.ok(/CC BY-SA 4.0/.test(some), "the licence line is not drawn");
  assert.ok(/applies because/.test(some), "the measured reason is not carried");

  const refused = render({ attribution: [], attribution_error: "Q823 (ODbL) is unanswered" });
  assert.ok(/note err/.test(refused),
    "an attribution REFUSAL was drawn as if nothing applied: " + refused);
  assert.ok(!/no attribution line applies/.test(refused),
    "a refusal was reported as 'none apply', which is a different fact: " + refused);
  // The backend's words stay reachable as the hover detail, and out of the sentence.
  assert.ok(/title="Q823/.test(refused), "the refusal detail is not on the hover: " + refused);
  assert.ok(/could not be completed/.test(refused), "the keyed sentence is missing: " + refused);
}

// --- a corpus-less export says so rather than drawing a zero --------------- //
{
  const out = render({ corpus_included: false, volumes: {}, tables: [] });
  assert.ok(/no corpus was selected/.test(out), "a corpus-less export drew an empty volume count: " + out);
  assert.ok(!/Encrypted volumes<\/span><span>0/.test(out), "a corpus-less export claimed 0 volumes");
}

// --- the Q213 cost is always stated --------------------------------------- //
{
  assert.ok(/nothing is reused from an earlier backup/.test(render({})),
    "the full-write cost is not stated in the panel");
}

// --- the summary path is shown when there is one, and never invented ------- //
{
  assert.ok(!/BACKUP_SUMMARY/.test(render({})), "a summary path was claimed with none written");
  assert.ok(/BACKUP_SUMMARY\.md/.test(render({ summary_path: "/mnt/stick/x/BACKUP_SUMMARY.md" })),
    "the written summary path is not shown");
}

console.log("export panel node suite: ok");
