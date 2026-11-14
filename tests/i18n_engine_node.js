// The shipped i18n.js t()/tf() over a given locale map, for node suites (2026-11-14).
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// A translation may hold plural forms ("[one]...[few]...[other]..."); tf() chooses one with
// Intl.PluralRules for the language current() names, and t() returns [other]. A suite that
// stands in its own t()/tf() would print the markers, so it takes these, EXTRACTED from the
// shipped file rather than re-typed: `engine(map, current)` returns { t, tf }, where `map` is
// read live (a suite may swap its contents) and `current()` names the language.

const fs = require("fs");
const path = require("path");

const I18N = fs.readFileSync(path.join(__dirname, "..", "src", "static", "i18n.js"), "utf-8");

function extract(name) {
  const at = I18N.indexOf("function " + name + "(");
  if (at < 0) throw new Error("i18n.js has no function " + name + " -- was it renamed?");
  let i = I18N.indexOf("(", at), depth = 0;
  for (; i < I18N.length; i++) {
    if (I18N[i] === "(") depth++;
    else if (I18N[i] === ")") { depth--; if (depth === 0) { i++; break; } }
  }
  const open = I18N.indexOf("{", i);
  let d = 0, j = open;
  for (; j < I18N.length; j++) {
    if (I18N[j] === "{") d++;
    else if (I18N[j] === "}") { d--; if (d === 0) { j++; break; } }
  }
  return I18N.slice(at, j);
}

const markAt = I18N.indexOf("const PLURAL_MARK");
if (markAt < 0) throw new Error("i18n.js has no PLURAL_MARK -- was it renamed?");
const SRC = I18N.slice(markAt, I18N.indexOf("\n", markAt)) + "\n"
  + ["pluralForms", "pluralPick", "t", "tf"].map(extract).join("\n")
  + "\nreturn { t: t, tf: tf };";

function engine(map, current) {
  return new Function("map", "current", SRC)(map, current);
}

module.exports = { engine };
