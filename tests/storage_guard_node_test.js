// The storage guard's notice, run as real EXTRACTED code in both UIs (the app's vitals panel /
// Schedule subtab and the standalone /tasks page) against small fakes. Open Omniscience -
// Global Intelligence Platform for Investigative Journalism. Copyright (C) 2026 Ideotion.
// GPL-3.0-or-later.
//
//   * an engaged guard draws each note from its FRAME with the numbers filled in through the
//     page's own byte formatter, the "Resume anyway" button (the operator's OVERRIDE, R112), and
//     the method one hover away (which says what bounds an override and that quitting and
//     reopening ends what the app itself holds open);
//   * while an override holds the notice says so, with the floor it stops at, and offers no
//     button; the click shows the server's refusal sentence with the sizes through the page's
//     formatter, or says that collection resumed although the limit is exceeded;
//   * it draws NOTHING unless collection is meant to be running: a "Collection is paused"
//     notice over a stopped scheduler or airplane mode would claim a state that is not the case;
//   * a healthy or absent guard draws nothing, and no placeholder survives into the text.

"use strict";

const assert = require("assert");
const path = require("path");
const fs = require("fs");

const APP = require("./app_source.js").appJs();
const TM = require("./app_source.js").pageSource("taskmanager.html");
const EN = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "src", "static", "locales", "en.json"), "utf-8"));

function extract(src, name) {
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
  return src.slice(at, j) + "\n";
}

const esc = (s) => String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const tf = (s, o) => s.replace(/\{(\w+)\}/g, (m, k) => (o && o[k] != null ? String(o[k]) : m));
const bytes = (n) => (n == null ? "—" : Math.round(n / 1048576) + " MB");

// The frames are the CURRENT locale keys, found by their opening words: a fixture copied by hand
// goes stale silently (it did, once), and a frame reworded in the module without its locale key
// would fail here and in test_every_storage_string_is_in_the_twelve_locales.
const frame = (prefix) => {
  const ks = Object.keys(EN).filter((k) => k.startsWith(prefix));
  assert.strictEqual(ks.length, 1, "expected one locale key starting " + JSON.stringify(prefix) + ", found " + ks.length);
  return ks[0];
};
const FRAME_WAL = frame("Collection is paused: the database's working file (its write-ahead log) has grown to {size}");
const GUARD = { engaged: true, notes: [{ kind: "wal", frame: FRAME_WAL, vars: { size: 3221225472, limit: 1073741824 } }] };
const FRAME_STOPPED = frame("Collection cannot be kept running against this limit: free space is {free}, at or below {floor}");
const FRAME_HELD = frame("The drive refused a write for lack of space a short while ago, so collection cannot be forced on yet");
const FRAME_UNREADABLE = frame("Free space on the data drive cannot be read, so a forced resume could not be kept within");
const FRAME_OVERRIDE_WAL = frame("Collection was resumed by you although the database's working file");
const FRAME_OVERRIDE_DAMAGE = frame("Collection cannot be forced on: the database reported damage in your library's file");
const FRAME_DAMAGE_DATA = frame("Part of your library's data file could not be read: the database reported damage.");
const OVERRIDDEN = { engaged: true, overridden: true, notes: [{ kind: "override-wal", frame: FRAME_OVERRIDE_WAL, vars: { size: 3221225472, limit: 1073741824, floor: 3221225472 } }] };
const ok = (over) => Object.assign({ running: true, online: true, storage_guard: GUARD }, over || {});

const app = new Function("esc", "_fmtBytes",
  extract(APP, "_storageGuardTail") + extract(APP, "_damageHtml") + extract(APP, "_storageGuardHtml") + "return _storageGuardHtml;")(esc, bytes);
const tm = new Function("esc", "fmtBytes", "tf", "t",
  extract(TM, "storageGuardTail") + extract(TM, "damageHtml") + extract(TM, "storageGuardHtml") + "return storageGuardHtml;")(esc, bytes, tf, (s) => s);
const render = {
  "the app": (a) => app(a, (s) => s, tf),
  "/tasks": (a) => tm(a),
};

const fails = [];
function check(name, fn) { try { fn(); } catch (e) { fails.push(name + ": " + e.message); } }

for (const [ui, draw] of Object.entries(render)) {
  check(ui + ": an engaged guard draws the sentence with the numbers filled in", () => {
    const html = draw(ok());
    assert.ok(html.includes("has grown to 3072 MB (this machine&#39;s limit") || html.includes("has grown to 3072 MB (this machine's limit"), html);
    assert.ok(html.includes("limit is 1024 MB)"), html);
    assert.ok(!/\{\w+\}/.test(html), "a placeholder survived: " + html);
  });
  check(ui + ": the override button is there and the hover says what bounds it and the restart sentence", () => {
    const html = draw(ok());
    assert.ok(/data-(on-click="storageGuardResume\(\)"|tm="storage-resume")/.test(html), html);
    assert.ok(html.includes("Resume anyway"), html);
    assert.ok(!html.includes("Try again now"), "the retry-era label is gone: " + html);
    assert.ok(html.includes("forces it on while the limit is still exceeded"), html);
    assert.ok(html.includes("never less than 128 MB"), html);
    assert.ok(html.includes("Quitting and reopening the app ends anything the app itself is holding open"), html);
    assert.ok(html.includes("the larger of 1 GB (for the writes still in flight) and 2% of the drive (room for everything else that writes to it)"), html);
    assert.ok(!html.includes("plus 2% of the drive"), "the reserve is a max, not a sum: " + html);
    assert.ok(html.includes("or if a second limit is crossed"), html);
  });
  check(ui + ": while an override holds the note says so with its floor and the button is not offered", () => {
    const html = draw(ok({ storage_guard: OVERRIDDEN }));
    assert.ok(html.includes("Collection was resumed by you although the database"), html);
    assert.ok(html.includes("falls to 3072 MB"), html);
    assert.ok(!/data-(on-click="storageGuardResume\(\)"|tm="storage-resume")/.test(html), html);
    assert.ok(!/\{\w+\}/.test(html), "a placeholder survived: " + html);
  });
  check(ui + ": a click that the server would refuse gets the refusal sentence, not a button", () => {
    const refusal = (kind, frame, vars) => ({ kind, frame, vars });
    for (const rf of [
      refusal("floor", FRAME_STOPPED, { free: 104857600, floor: 134217728 }),
      refusal("held", FRAME_HELD, {}),
      refusal("unreadable", FRAME_UNREADABLE, {}),
    ]) {
      const html = draw(ok({ storage_guard: Object.assign({}, GUARD, { kinds: ["wal"], override_refusal: rf }) }));
      assert.ok(!/data-(on-click="storageGuardResume\(\)"|tm="storage-resume")/.test(html), "button drawn beside a refusal: " + html);
      assert.ok(html.includes(tf(rf.frame, { free: "100 MB", floor: "128 MB" })), "the refusal is not said: " + html);
      assert.ok(html.includes('<div class="vnote">'), "the refusal sentence lost its styled note class: " + html);
      assert.ok(!/\{\w+\}/.test(html), "a placeholder survived: " + html);
    }
  });
  check(ui + ": a withdrawal note already says the refusal, so it is not said twice and no button is drawn", () => {
    const g = { engaged: true, kinds: ["wal", "override-withdrawn"],
      override_refusal: { kind: "floor", frame: FRAME_STOPPED, vars: { free: 104857600, floor: 134217728 } },
      notes: [GUARD.notes[0], { kind: "override-withdrawn", frame: FRAME_STOPPED, vars: { free: 104857600, floor: 134217728 } }] };
    const html = draw(ok({ storage_guard: g }));
    assert.strictEqual(html.split("cannot be kept running against this limit").length - 1, 1, html);
    assert.ok(!/data-(on-click="storageGuardResume\(\)"|tm="storage-resume")/.test(html), html);
  });
  check(ui + ": a payload without the preview (an older server) keeps the button", () => {
    const html = draw(ok({ storage_guard: Object.assign({}, GUARD, { override_refusal: undefined }) }));
    assert.ok(/data-(on-click="storageGuardResume\(\)"|tm="storage-resume")/.test(html), html);
  });
  check(ui + ": nothing is drawn while the scheduler is stopped", () => {
    assert.strictEqual(draw(ok({ running: false })), "");
  });
  check(ui + ": nothing is drawn in airplane mode", () => {
    assert.strictEqual(draw(ok({ online: false })), "");
  });
  check(ui + ": a healthy or absent guard draws nothing", () => {
    assert.strictEqual(draw(ok({ storage_guard: { engaged: false, notes: [] } })), "");
    assert.strictEqual(draw(ok({ storage_guard: null })), "");
    assert.strictEqual(draw(null), "");
  });

  // The database-damage notice (database/damage.py): a fact about the DATA, so unlike the limits
  // it draws whether or not the scheduler is on and in airplane mode; no number, no button (the
  // operator's way back is starting collection again, which the sentence says).
  const DAMAGE = { latched: ["corpus"], notes: [{ kind: "damage", file: "corpus", frame: FRAME_DAMAGE_DATA, vars: {} }] };
  const withDamage = (over) => ok(Object.assign({ storage_guard: { engaged: false, notes: [], database_damage: DAMAGE } }, over || {}));
  check(ui + ": a damaged file draws its sentence and the long form on hover, with no button", () => {
    const html = draw(withDamage());
    assert.ok(html.includes("Part of your library&#39;s data file could not be read") || html.includes("Part of your library's data file could not be read"), html);
    assert.ok(html.includes('class="vwarn"'), html);
    assert.ok(html.includes("database disk image is malformed"), "the hover lost its long form: " + html);
    assert.ok(html.includes("database-damage.json"), html);
    assert.ok(!/data-(on-click="storageGuardResume\(\)"|tm="storage-resume")/.test(html), "a damage notice offers no override: " + html);
    assert.ok(!/\{\w+\}/.test(html), "a placeholder survived: " + html);
  });
  check(ui + ": the damage notice draws with the scheduler stopped and in airplane mode", () => {
    assert.ok(draw(withDamage({ running: false })).includes("could not be read"));
    assert.ok(draw(withDamage({ online: false })).includes("could not be read"));
  });
  check(ui + ": an engaged limit and a damaged file are both said", () => {
    const g = Object.assign({}, GUARD, { database_damage: DAMAGE });
    const html = draw(ok({ storage_guard: g }));
    assert.ok(html.includes("could not be read"), html);
    assert.ok(html.includes("has grown to 3072 MB"), html);
  });
  check(ui + ": an engaged limit with the scheduler stopped or offline still draws the damage and not the limit", () => {
    const g = Object.assign({}, GUARD, { database_damage: DAMAGE });
    for (const over of [{ running: false }, { online: false }]) {
      const html = draw(ok(Object.assign({ storage_guard: g }, over)));
      assert.ok(html.includes("could not be read"), "the damage went quiet with the limit engaged: " + html);
      assert.ok(!html.includes("has grown to"), "the limit's sentence is about collection running: " + html);
    }
  });
  check(ui + ": while the corpus is damaged the refusal is said where the Resume button would be, and no button", () => {
    const refusal = { kind: "damage", frame: FRAME_OVERRIDE_DAMAGE, vars: {} };
    const g = Object.assign({}, GUARD, { database_damage: DAMAGE, override_refusal: refusal });
    const html = draw(ok({ storage_guard: g }));
    assert.ok(html.includes("Collection cannot be forced on"), html);
    assert.ok(!/data-(on-click="storageGuardResume\(\)"|tm="storage-resume")/.test(html), "a button beside its own refusal: " + html);
  });
  check(ui + ": no latched file means no damage notice", () => {
    const g = { engaged: false, notes: [], database_damage: { latched: [], notes: [] } };
    assert.strictEqual(draw(ok({ storage_guard: g })), "");
  });
}

// The click: the server grants the override, or refuses with a sentence frame whose sizes are
// written through the page's own formatter -- and a refusal is an error toast, never a success.
function handlerSource(src, marker) {
  const at = src.indexOf(marker);
  assert.ok(at !== -1, marker + " not found -- was it renamed?");
  const open = src.indexOf("{", src.indexOf(")", at));
  let d = 0, j = open;
  for (; j < src.length; j++) {
    if (src[j] === "{") d++;
    else if (src[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return "async function _h()" + src.slice(open, j);
}
async function clickCase(makeHandler, reply) {
  const toasts = [];
  const api = async () => { if (reply instanceof Error) throw reply; return reply; };
  const toast = (m, kind) => toasts.push([m, kind || "ok"]);
  await makeHandler(api, toast)();
  return toasts;
}
const FAKE_I18N = { t: (s) => s, tf };
const appHandler = (api, toast) => new Function("api", "toast", "_fmtBytes", "window", "OOI18N", "_pollVitals",
  handlerSource(APP, "async function storageGuardResume(") + "return _h;")(api, toast, bytes, { OOI18N: FAKE_I18N }, FAKE_I18N, undefined);
const tmHandler = (api, toast) => new Function("api", "toast", "fmtBytes", "t", "tf",
  handlerSource(TM, "storageResume: async function") + "return _h;")(api, toast, bytes, (s) => s, tf);
const clicks = { "the app": appHandler, "/tasks": tmHandler };
const pending = [];
for (const [ui, make] of Object.entries(clicks)) {
  pending.push((async () => {
    let t = await clickCase(make, { storage_guard_override: { engaged: true, overridden: true, refused: null } });
    check(ui + ": a granted override says collection resumed although the limit is still exceeded", () => {
      assert.strictEqual(t.length, 1);
      assert.ok(t[0][0].startsWith("Collection resumed although the limit is still exceeded"), t[0][0]);
      assert.strictEqual(t[0][1], "ok");
    });
    t = await clickCase(make, { storage_guard_override: { engaged: true, overridden: false,
      refused: { kind: "floor", frame: FRAME_STOPPED, vars: { free: 104857600, floor: 134217728 } } } });
    check(ui + ": a refusal is an error toast with the sizes through the formatter", () => {
      assert.strictEqual(t.length, 1);
      assert.strictEqual(t[0][1], "err");
      assert.ok(t[0][0].includes("free space is 100 MB, at or below 128 MB"), t[0][0]);
      assert.ok(!/\{\w+\}/.test(t[0][0]), t[0][0]);
    });
    t = await clickCase(make, { storage_guard_override: { engaged: false, overridden: false, refused: null } });
    check(ui + ": nothing left to override just says resumed", () => {
      assert.strictEqual(t[0][0], "Resumed.");
    });
    t = await clickCase(make, new Error("boom"));
    check(ui + ": a failed request shows its error", () => {
      assert.deepStrictEqual(t, [["boom", "err"]]);
    });
  })());
}

// A page whose i18n engine has no tf (it loads late, or not at all) still fills the refusal's
// placeholders: the toast must never show "{free}".
pending.push((async () => {
  const noTf = { t: (s) => s };
  const handler = (api, toast) => new Function("api", "toast", "_fmtBytes", "window", "OOI18N", "_pollVitals",
    handlerSource(APP, "async function storageGuardResume(") + "return _h;")(api, toast, bytes, { OOI18N: noTf }, noTf, undefined);
  const t = await clickCase(handler, { storage_guard_override: { engaged: true, overridden: false,
    refused: { kind: "floor", frame: FRAME_STOPPED, vars: { free: 104857600, floor: 134217728 } } } });
  check("the app: a refusal toast fills its placeholders without OOI18N.tf", () => {
    assert.strictEqual(t.length, 1);
    assert.ok(t[0][0].includes("free space is 100 MB, at or below 128 MB"), t[0][0]);
    assert.ok(!/\{\w+\}/.test(t[0][0]), t[0][0]);
  });
})());

// The loop's phase can read paused for up to one poll after "Resume anyway": no "Paused" label may
// sit beside the "resumed by you" note while an override holds.
const pausedApp = new Function(extract(APP, "_storagePausedText") + "return _storagePausedText;")();
const pausedTm = new Function(extract(TM, "storagePausedText") + "return storagePausedText;")();
for (const [ui, fn] of [["the app", pausedApp], ["/tasks", pausedTm]]) {
  check(ui + ": the paused label shows while the guard holds and never while overridden", () => {
    assert.ok(/^Paused: the database log/.test(fn("paused-wal-pinned", GUARD)));
    assert.ok(/^Paused: the data drive/.test(fn("paused-low-disk", undefined)));
    assert.strictEqual(fn("paused-wal-pinned", OVERRIDDEN), null);
    assert.strictEqual(fn("paused-low-disk", OVERRIDDEN), null);
    assert.strictEqual(fn("collecting", GUARD), null);
  });
  check(ui + ": the damage pause label survives an override (the override does not cover it)", () => {
    assert.ok(/^Paused: the database reported damage/.test(fn("paused-damaged", OVERRIDDEN)));
    assert.ok(/^Paused: the database reported damage/.test(fn("paused-damaged", GUARD)));
    assert.ok(/^Paused: the database reported damage/.test(fn("paused-damaged", undefined)));
  });
}
const callSites = (src, name) => (src.match(new RegExp(name + "\\(a\\.phase[^)]*\\)", "g")) || []);
check("every pill call site passes the guard (a site that forgets brings the label back)", () => {
  const sites = callSites(APP, "_storagePausedText").concat(callSites(TM, "storagePausedText"));
  assert.strictEqual(sites.length, 3, sites.join(" | "));
  sites.forEach((x) => assert.ok(x.includes("a.storage_guard"), x));
});

check("the hover key in both UIs is a locale key (the page translates it by that exact text)", () => {
  for (const [name, src] of [["app-core", APP], ["taskmanager", TM]]) {
    const m = src.match(/t\("(Measured from the size of the database[^"]*)"\)/);
    assert.ok(m, name + " lost its hover text");
    assert.ok(m[1] in EN, name + ": the hover text is not a locale key: " + m[1].slice(0, 60));
  }
});

Promise.all(pending).then(() => {
  if (fails.length) {
    console.log(fails.join("\n"));
    process.exit(1);
  }
  console.log("storage guard notice: all checks ok");
});
