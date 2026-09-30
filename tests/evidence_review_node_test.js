// The signed-evidence review's renderers, run as REAL code (gate row K, brief S05-11 S5).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// The review is what stands between a click and a file that leaves the machine, so most
// checks are refusals:
//
//   * it says the file is PLAINTEXT, beside the numbers and before the button, not in a hover;
//   * it says what the signature proves and that one key on every bundle links them all;
//   * with no key yet it says one will be created, instead of showing an empty key;
//   * it lists what the file holds, and names the item fields it was given (the wire, not a
//     re-typed list), with the JSON keys shown as code, never translated;
//   * after saving it names the file, the size and the key to hand over, and how to check it
//     offline;
//   * nothing it says scores, ranks or vouches for the articles.
//
// EXTRACTED from the shipped module rather than re-typed.

const assert = require("assert");
const fs = require("fs");
const path = require("path");

const SRC = fs.readFileSync(path.join(__dirname, "..", "src", "static", "app-evidence.js"), "utf-8");

function extract(name) {
  const at = SRC.indexOf("function " + name + "(");
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

const FNS = ["_evNum", "evidenceMembersHtml", "evidenceReviewHtml", "evidenceDoneHtml"];
const src =
  "function esc(s) { return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\"/g, '&quot;'); }\n" +
  FNS.map(extract).join("\n") + "\n" +
  "module.exports = {" + FNS.join(", ") + "};";
const R = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const t = (s) => s;
const tf = (s, v) => s.replace(/\{(\w+)\}/g, (_, k) => v[k]);
const decode = (s) => s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, "\"")
  .replace(/&#39;/g, "'").replace(/&amp;/g, "&");
const visible = (html) => decode(String(html).replace(/<[^>]*>/g, " ")).replace(/\s+/g, " ").trim();

const FIELDS = ["id", "url", "canonical_url", "source_id", "title", "published_at", "stored_hash", "content_sha256"];
const PLAN = { bundle_version: "oo-evidence-1", articles: 14, sources: 5, item_fields: FIELDS, text_included: false,
  signer: { exists: true, ed25519_pub: "ab".repeat(32) } };

const SCOPE_Q = { query: "border AND crossing", case_name: "border AND crossing" };
const review = visible(R.evidenceReviewHtml(PLAN, t, tf, SCOPE_Q));
assert.ok(review.includes("Articles: 14") && review.includes("Sources: 5"), review);
assert.ok(review.includes("Plaintext: the file is not encrypted."), review);
assert.ok(review.includes("The articles' text is not in it, only its SHA-256."), review);
assert.ok(review.includes("It is signed with this install's evidence key.") && review.includes("links all of them"), review);
assert.ok(review.includes("id, url, canonical_url, source_id, title, published_at, stored_hash, content_sha256"), review);
assert.ok(review.includes("manifest") && review.includes("signature") && review.includes("public_key"), review);
assert.ok(!review.includes("created on this machine"), "a key that exists is not 'created'");
// the case name is shown as the file will carry it, isolated; an analysis with no label carries none
assert.ok(review.includes("the case name (your search query or the analysis label)"), review);
assert.ok(review.includes("The case name written in the file, readable by anyone who has it: ⁨border AND crossing⁩"), review);
const noName = visible(R.evidenceReviewHtml(PLAN, t, tf, { article_ids: [1, 2], case_name: null }));
assert.ok(noName.includes("No case name is written in the file.") && !noName.includes("The case name written"), noName);
assert.ok(!visible(R.evidenceReviewHtml(PLAN, t, tf)).includes("The case name written"), "no scope: claims no name");
// the file's fourth member is listed
assert.ok(review.includes("algorithm the name of the signature scheme, ed25519"), review);
// the key that WILL sign is shown before saving, so it can be checked
assert.ok(review.includes("The key that will sign: " + "ab".repeat(32)), review);

// no key yet: say one will be made, and that it stays here
const fresh = visible(R.evidenceReviewHtml(Object.assign({}, PLAN, { signer: { exists: false, ed25519_pub: null } }), t, tf));
assert.ok(fresh.includes("no evidence key yet") && fresh.includes("created on this machine when you save"), fresh);
assert.ok(!fresh.includes("It is signed with this install's evidence key."), fresh);
assert.ok(!fresh.includes("The key that will sign"), "no key yet: none is shown");
// a key file is there but unusable: never promise that one is created
const bad = visible(R.evidenceReviewHtml(Object.assign({}, PLAN, { signer: { exists: true, state: "unreadable", ed25519_pub: null } }), t, tf, SCOPE_Q));
assert.ok(bad.includes("cannot be read as an Ed25519 key, so saving will fail"), bad);
assert.ok(!bad.includes("created on this machine") && !bad.includes("It is signed with") && !bad.includes("The key that will sign"), bad);
// digit grouping goes through the app formatter when it is there
const G = (() => { const m = { exports: {} }; new Function("fmtNum", "module", "exports", src)((n) => "#" + n, m, m.exports); return m.exports; })();
assert.ok(visible(G.evidenceReviewHtml(PLAN, t, tf)).includes("Articles: #14 · Sources: #5"));
// no fields on the wire: still a well-formed line, never "undefined"
const bare = visible(R.evidenceReviewHtml({ articles: 1, sources: 1, signer: {} }, t, tf));
assert.ok(!bare.includes("undefined") && !bare.includes("null"), bare);

// the JSON keys are code (never translated); the explanation beside them is text
const members = R.evidenceMembersHtml(PLAN, t, tf);
assert.ok(members.includes("<code>manifest</code>") && members.includes("<code>manifest.items</code>"), members);
assert.strictEqual((members.match(/<li>/g) || []).length, 4);

// caveats are on the page as plain paragraphs, not in a title attribute
const html = R.evidenceReviewHtml(PLAN, t, tf);
assert.strictEqual((html.match(/class="card-caveat"/g) || []).length, 3);
assert.ok(!/title=/.test(html), "the caveats do not hide in a hover");

// after saving
const done = visible(R.evidenceDoneHtml(PLAN, { filename: "evidence-bundle-2026-09-30.json", bytes: 5120, count: 14, pub: "cd".repeat(32) },
  t, tf, (n) => "B(" + n + ")"));
assert.ok(done.includes("Handed to your browser as ⁨evidence-bundle-2026-09-30.json⁩: 14 articles, B(5120). Your browser chooses where it goes and may rename it."), done);
assert.ok(!done.includes("Saved"), "the page cannot know the file was saved");
// a bundle with no item_count falls back to the plan's count, never "undefined"
const noCount = visible(R.evidenceDoneHtml(PLAN, { filename: "f.json", bytes: 1, count: undefined, pub: "cd" }, t, tf, (n) => n));
assert.ok(noCount.includes("f.json⁩: 14 articles") && !noCount.includes("undefined"), noCount);
assert.ok(done.includes("Signing key (Ed25519), to give the recipient some other way:") && done.includes("cd".repeat(32)), done);
assert.ok(done.includes("scripts/verify_evidence.py") && done.includes("What the file holds"), done);
assert.ok(done.indexOf("Handed") < done.indexOf("What the file holds") && done.indexOf("What the file holds") < done.indexOf("Signing key"), done);

// the file name is text, never markup
const hostile = R.evidenceDoneHtml(PLAN, { filename: "<img src=x onerror=1>.json", bytes: 1, count: 1, pub: "<b>k</b>" }, t, tf, (n) => n);
assert.ok(!hostile.includes("<img") && !hostile.includes("<b>k"), hostile);

// nothing vouches for the articles
const all = review + " " + fresh + " " + done;
assert.ok(!/\b(score[sd]?|rating|rank(ed|ing)?|grade[sd]?|credib\w*|trustworth\w*|reliab\w*|verified)\b/i.test(all), all);

console.log("evidence review node test: all checks passed");
