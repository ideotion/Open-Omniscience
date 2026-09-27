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
  // J2: a file that could not be written is NAMED, never passed over in silence.
  const failed = render({ summary_error: "Permission denied" });
  assert.ok(/note err/.test(failed) && /summary file could not be/.test(failed) && /Permission denied/.test(failed),
    "a summary that could not be written is not reported: " + failed);
}

// ========================================================================== //
//  The 2026-09-26 delegated click-through, row J (J1, J3, J5, J6, J7, J9)
// ========================================================================== //

// --- J1: a folder whose measurements the app no longer holds is NOT "no corpus" //
{
  const out = render({
    corpus_facts: "not_held", corpus_included: true, tables: [],
    volumes: { count: 4, bytes: 800, plaintext_bytes: null, parity: true },
    verify: { state: "not_held", reason: "gone", method: null },
  });
  assert.ok(!/no corpus was selected/.test(out),
    "a folder holding four encrypted volumes was described as holding no corpus: " + out);
  assert.ok(/>4 · 800 B/.test(out), "the volume figures read off the drive are not drawn: " + out);
  assert.ok(/not known here/.test(out), "the unknown verdict is not named: " + out);
  assert.ok(!/note err/.test(out),
    "an export this app merely no longer remembers was painted as a failure: " + out);
  assert.ok(!/Not verified|NOT verified/.test(_uxVerifySentence({ state: "not_held" }, t)),
    "'not held' is not a not-verified verdict");
}

// --- J3: left-to-right data keeps its own direction inside an RTL panel ----- //
{
  const out = render({ attribution: [{ key: "w", text: "Wikipedia — CC BY-SA 4.0.", because: "table:wiki_pages" }],
                       summary_path: "/mnt/stick/x/BACKUP_SUMMARY.md" });
  assert.ok(/<code dir="ltr"[^>]*>\/mnt\/stick\/202609121045_OpenOmniscience_Backup<\/code>/.test(out),
    "the Destination path is not isolated left-to-right: " + out);
  assert.ok(/<code dir="ltr">\/mnt\/stick\/x\/BACKUP_SUMMARY\.md<\/code>/.test(out),
    "the summary path is not isolated left-to-right");
  assert.ok(/<div dir="auto"[^>]*>Wikipedia — CC BY-SA 4\.0\.<\/div>/.test(out),
    "an English licence line inherits the panel's direction: " + out);
}

// --- J5: the plaintext-corpus Encryption row no longer contradicts its note -- //
{
  const out = render({ encryption: { corpus_encrypted: false, files_encrypted: null, note: "n" } });
  assert.ok(!/stored unencrypted/.test(out),
    "a corpus inside encrypted volumes is still called 'stored unencrypted': " + out);
  assert.ok(/not separately encrypted/.test(out) && /volumes are/.test(out),
    "the row does not say which layer the flag measures: " + out);
}

// --- J7 + J9: hovers and the files-none value go through the locale --------- //
{
  const FR = {
    "the large-data copy records no timing of its own": "FR-untimed",
    "no large-data files were copied": "FR-nofiles",
    "NOTE-EN": "FR-note",
    "none": "aucune",
    "no files": "aucun fichier",
  };
  const tFr = (s) => (FR[s] == null ? s : FR[s]);
  host.innerHTML = "";
  _uxRenderExportPanel({ ...base, encryption: { corpus_encrypted: true, note: "NOTE-EN" } }, tFr);
  const out = host.innerHTML;
  assert.ok(/title="FR-nofiles"/.test(out), "the Elapsed hover stayed in English: " + out);
  assert.ok(/title="FR-note"/.test(out), "the Encryption hover stayed in English: " + out);
  assert.ok(!/title="NOTE-EN"/.test(out), "the raw backend note reached the hover");
  assert.ok(/Files copied<\/span><span>aucun fichier/.test(out),
    "'Files copied' borrows the shared (feminine) 'none': " + out);
}

// --- J6: the verify-after-write re-read is named, with its own count -------- //
{
  const m = { exports: {} };
  const psrc =
    "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
    "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
    "function humanBytes(n){return String(n)+' B';}\n" +
    "var window = {};\n" +
    extract("_uxVolPhase") + "\n" + extract("_uxPhaseCount") + "\n" + extract("_uxProgressView") + "\n" +
    "module.exports = { _uxProgressView };";
  new Function("module", "exports", psrc)(m, m.exports);
  const view = (p) => m.exports._uxProgressView("volumes", { mode: "backup", state: "running", progress: p }, t).text;
  const v = view({ phase: "verifying", volumes_verified: 1, volumes_total: 3 });
  assert.ok(/Verifying volumes…/.test(v), "the re-read is not named: " + v);
  assert.ok(!/Backing up…/.test(v), "the re-read fell through to the generic label: " + v);
  assert.ok(/1\/3 volumes/.test(v), "the re-read's own count is not shown: " + v);
  // The first report comes before any volume is hashed and carries no total: named,
  // but no invented "0/?".
  const first = view({ phase: "verifying", volumes_verified: 0 });
  assert.ok(/Verifying volumes…/.test(first) && !/\d\/|\/\?/.test(first), "the first report drew a made-up count: " + first);
}

// --- J1: a reopened dialog shows the LATER export, not the folder job's older one //
{
  const PICK = APP.includes("function _uxPickLastExport(") ? extract("_uxPickLastExport") : "";
  const el = () => ({ innerHTML: "", textContent: "", value: "", style: {}, dataset: {},
                      removeAttribute() {}, setAttribute() {} });
  async function reopen(statuses, facts) {
    const dom = { "ux-progress": el(), "ux-bar": el(), "ux-pause": el(), "ux-dest": el(), "ux-summary": el() };
    const calls = [];
    const api = async (url, opts) => {
      calls.push({ url, method: (opts && opts.method) || "GET" });
      if (url === "/api/backup/v2/volumes/status") return statuses.vol;
      if (url === "/api/backup/folder/status") return statuses.fold;
      if (url.startsWith("/api/backup/export-summary?dir=")) return facts(decodeURIComponent(url.split("=")[1]));
      if (url === "/api/backup/export-summary") return { summary_path: "/written/BACKUP_SUMMARY.md", facts: facts("POST") };
      throw new Error("unexpected " + url);
    };
    const rsrc =
      "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g," +
      "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n" +
      "function humanBytes(n){return String(n)+' B';}\n" +
      "var window = {}; var _uxExportDir = null, _uxPhase = null, _uxExportFacts = null;\n" +
      "var document = { getElementById: function(id){ return DOM[id] || null; } };\n" +
      "function _uxShowPaused(){ DOM['ux-progress'].innerHTML = 'PAUSED'; }\n" +
      extract("_uxSamePath") + "\n" + PICK + "\n" +
      extract("_uxRenderExportPanel") + "\n" + extract("_uxVerifySentence") + "\n" + extract("_uxVerifyDetail") + "\n" +
      // extract() starts at "function", so the async keyword is put back here.
      "async " + extract("_uxShowLastCompletedExportSummary") + "\n" +
      "module.exports = { run: _uxShowLastCompletedExportSummary, phase: () => _uxPhase, dir: () => _uxExportDir };";
    const mod = { exports: {} };
    new Function("module", "exports", "DOM", "api", rsrc)(mod, mod.exports, dom, api);
    await mod.exports.run();
    return { dom, calls, phase: mod.exports.phase(), dir: mod.exports.dir() };
  }
  const A = "/x/202609262011_OpenOmniscience_Backup", B = "/x/202609262012_OpenOmniscience_Backup";
  const withPath = (d) => ({ ...base, destination: d, summary_path: d + "/BACKUP_SUMMARY.md" });
  (async () => {
    // Export A carried models (both managers -> A); export B was corpus-only (volumes -> B).
    const r = await reopen({
      vol: { mode: "backup", state: "done", dest: B, started_at: 300 },
      fold: { mode: "backup", state: "done", dest: A, started_at: 100 },
    }, withPath);
    assert.ok(r.dom["ux-progress"].innerHTML.includes(B) && !r.dom["ux-progress"].innerHTML.includes(A),
      "the reopened dialog names the OLDER export: " + r.dom["ux-progress"].innerHTML);
    assert.ok(r.calls.some((c) => c.url.includes(encodeURIComponent(B))), "the facts were read for the wrong folder");
    assert.ok(/<span dir="ltr"/.test(r.dom["ux-progress"].innerHTML), "the completion path is not isolated LTR (J3)");

    // One export, both phases: the folder job is the later state of the SAME export.
    const same = await reopen({
      vol: { mode: "backup", state: "done", dest: A, started_at: 100 },
      fold: { mode: "backup", state: "paused", dest: A, started_at: 150 },
    }, withPath);
    assert.strictEqual(same.phase, "folder", "a paused large-data phase lost its Resume target");

    // A PAUSED later corpus export must win over an older finished one, or its Resume is lost.
    const paused = await reopen({
      vol: { mode: "backup", state: "paused", dest: B, started_at: 300 },
      fold: { mode: "backup", state: "done", dest: A, started_at: 100 },
    }, withPath);
    assert.strictEqual(paused.phase, "volumes", "the later, paused corpus export was hidden behind an older one");
    assert.strictEqual(paused.dir, B);

    // J2: the file is missing on reopen -> it is asked for once, and the panel names it.
    const missing = await reopen({ vol: { mode: "backup", state: "done", dest: B, started_at: 1 }, fold: null },
      (d) => (d === "POST" ? { ...base, destination: B } : { ...base, destination: B, summary_path: null }));
    assert.ok(missing.calls.some((c) => c.url === "/api/backup/export-summary" && c.method === "POST"),
      "a missing BACKUP_SUMMARY.md was not asked for on reopen");
    assert.ok(/\/written\/BACKUP_SUMMARY\.md/.test(missing.dom["ux-summary"].innerHTML),
      "the recovered summary path is not shown");

    console.log("export panel node suite: ok");
  })().catch((e) => { console.error(e); process.exit(1); });
}
