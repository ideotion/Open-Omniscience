// The settings panel's "Remove imported newsletters" action, run as REAL code (queue item 58).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// WHY THIS IS BEHAVIOURAL AND NOT A SOURCE GREP. What is guarded is what the user is left
// looking at, and that is decided by the ORDER of two calls: the removal's answer is drawn
// into a panel that `loadNewsletterRemoveCount` then hides once nothing is left to remove.
// A grep finds the note's words in the source whether or not anything ever shows them; the
// independent read of this change found exactly that (the note was appended to the panel,
// which the count refresh then hid). Only running the two functions in order can tell.
//
// EXTRACTED from the shipped module rather than re-typed -- a re-typed copy would pass
// while the real handler was broken.

"use strict";

const assert = require("assert");
const SRC = require("./app_source.js").appJs();

function extract(name) {
  const at = SRC.indexOf("async function " + name + "(");
  assert.ok(at !== -1, name + " not found -- was it renamed?");
  let i = SRC.indexOf("(", at), depth = 0;
  for (; i < SRC.length; i++) {
    if (SRC[i] === "(") depth++;
    else if (SRC[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = SRC.indexOf("{", i);
  let d = 0, j = open;
  for (; j < SRC.length; j++) {
    if (SRC[j] === "{") d++;
    else if (SRC[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return SRC.slice(at, j);
}

const CODE = extract("loadNewsletterRemoveCount") + "\n" + extract("removeImportedNewsletters") +
  "\nreturn {loadNewsletterRemoveCount, removeImportedNewsletters};";

function el() {
  return {style: {display: ""}, textContent: "", innerHTML: "", disabled: false};
}

// One run of the handler against a server whose answers the test writes: `counts` is what
// /api/newsletters/imported-count answers on each call (or throws, an Error), `post` what the
// removal answers (an object) or throws (an Error).
async function run({counts, post}) {
  const nodes = {"nl-remove-panel": el(), "nl-remove-count": el(), "nl-remove-result": el()};
  const calls = {posts: 0, toasts: []};
  let countCall = 0;
  const api = async (url, opts) => {
    if (url === "/api/newsletters/imported-count") {
      const c = counts[Math.min(countCall++, counts.length - 1)];
      if (c instanceof Error) throw c;
      return {count: c};
    }
    if (url === "/api/newsletters/remove-imported") {
      assert.strictEqual(opts.method, "POST");
      calls.posts += 1;
      if (post instanceof Error) throw post;
      return post;
    }
    throw new Error("unexpected call " + url);
  };
  const env = {
    $: (id) => nodes[id],
    api,
    toast: (msg, kind) => calls.toasts.push([msg, kind]),
    confirm: () => true,
    fmtNum: (x) => String(x),
    esc: (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"),
    ooLabelText: (label, text) => label + ": " + text,
    window: {},
    OOI18N: undefined,
  };
  const make = new Function(...Object.keys(env), CODE);
  const fns = make(...Object.values(env));
  const btn = {disabled: false};
  await fns.removeImportedNewsletters(btn);
  assert.strictEqual(btn.disabled, false, "the button is given back");
  return {nodes, calls};
}

(async () => {
  const NOTE = "The keyword and source counts could not be refreshed after the removal, so some may read high until the app reconciles them again.";

  // 1. Every article removed, the counts not refreshed: the panel hides itself (nothing is left to
  //    remove), so the note must reach the user some other way -- a warning toast, as text.
  {
    const {nodes, calls} = await run({counts: [3, 0], post: {removed: true, removed_articles: 3, counts_refreshed: false, note: NOTE}});
    assert.strictEqual(calls.posts, 1, "one removal, never re-sent");
    assert.strictEqual(nodes["nl-remove-panel"].style.display, "none", "the panel hides once nothing is left");
    assert.deepStrictEqual(calls.toasts.find((x) => x[1] === "warn"), [NOTE, "warn"], "the note reaches the user");
    assert.ok(calls.toasts.some((x) => x[1] === "ok"), "and the removal is still announced");
  }

  // 2. Every article removed, the counts refreshed: no warning.
  {
    const {calls} = await run({counts: [2, 0], post: {removed: true, removed_articles: 2, counts_refreshed: true}});
    assert.deepStrictEqual(calls.toasts, [["Imported newsletters removed.", "ok"]]);
  }

  // 3. A removal that stopped partway: the server's fixed words are shown in the panel, which stays
  //    visible because something is left, and its count is what is left.
  {
    const words = "The removal stopped after removing 900 of the 1000 imported newsletter articles; the other 100 are still in your corpus. Run the removal again to remove them.";
    const {nodes, calls} = await run({counts: [1000, 100], post: new Error(words)});
    assert.strictEqual(calls.posts, 1, "a failed removal is never re-sent");
    assert.strictEqual(nodes["nl-remove-panel"].style.display, "", "something is left, so the panel stays");
    assert.strictEqual(nodes["nl-remove-count"].textContent, "100 imported newsletters in your corpus", "the count is what is left");
    assert.ok(nodes["nl-remove-result"].innerHTML.includes(words), "the stopped removal's words are shown");
    assert.ok(nodes["nl-remove-result"].innerHTML.startsWith('<span class="note err">Removal failed: '));
    assert.ok(!calls.toasts.some((x) => x[1] === "ok"), "no success is announced");
    assert.deepStrictEqual(calls.toasts, [["Removal failed: " + words, "err"]], "and the words are toasted, as text");
  }

  // 3b. A stopped removal whose count read then fails too (a damaged file can fail both): the count refresh hides the
  //     panel and its words with it, so the words must still reach the user, in the error toast.
  {
    const words = "The removal stopped after removing 900 of the 1000 imported newsletter articles; the other 100 are still in your corpus. Run the removal again to remove them.";
    const {nodes, calls} = await run({counts: [1000, new Error("count read failed")], post: new Error(words)});
    assert.strictEqual(calls.posts, 1, "a failed removal is never re-sent");
    assert.strictEqual(nodes["nl-remove-panel"].style.display, "none", "the panel hides when the count cannot be read");
    assert.deepStrictEqual(calls.toasts, [["Removal failed: " + words, "err"]], "the words reach the user anyway");
  }

  // 4. The note is never parsed as markup.
  {
    const {calls} = await run({counts: [1, 0], post: {removed: true, removed_articles: 1, counts_refreshed: false, note: "<img src=x>"}});
    assert.deepStrictEqual(calls.toasts.find((x) => x[1] === "warn"), ["<img src=x>", "warn"], "handed to toast, which sets text");
  }

  console.log("newsletter_remove_node_test: all assertions passed");
})().catch((err) => {
  console.error(err);
  process.exit(1);
});
