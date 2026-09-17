// Q512 — the concept tree's GEOMETRY, which is where the mind-map rules live.
//
// Open Omniscience - Global Intelligence Platform for Investigative Journalism
// Copyright (C) 2026 Ideotion. GPL-3.0-or-later.
//
// *"The ring is the centre node; each language is an arm; associations hang off the
// arms"*, drawn under the standing mind-map rules: centre → arms → ALWAYS outward,
// deterministic radial tree, NO cross-tangle, never interpolate structure that is not
// there. Those are geometric claims, and geometry is exactly the thing a payload test
// cannot check and a screenshot cannot check precisely — so the coordinates are read
// back out of the emitted SVG and measured.
//
// EXTRACTED from the shipped module rather than re-typed.

const assert = require("assert");
const APP = require("./app_source.js").appJs();

function extract(name) {
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

const src = "function esc(s){return String(s==null?'':s).replace(/[&<>\"]/g,"
  + "c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;'}[c]));}\n"
  + "var window = {};\n"
  // Q302's display helpers, SHIMMED to pass the value through: app-core's real ones
  // carry two code tables of their own and have their own tests, and what is measured
  // here is geometry, not how a code is spelled. The shim keeps the value findable so
  // an assertion can still say which arm is which.
  + "function ooLangCode(v){return String(v == null ? '' : v);}\n"
  + "function ooLangDisplayName(v, fb){return String(v == null ? (fb || '') : v);}\n"
  + extract("_anConceptTreeSvg") + "\n"
  + "module.exports = { _anConceptTreeSvg };";
const { _anConceptTreeSvg } = (() => {
  const m = { exports: {} };
  new Function("module", "exports", src)(m, m.exports);
  return m.exports;
})();

const GEO = { cx: 340, cy: 230, R: 150, scale: 1 };
const D = {
  center: { ring_id: "climate", label: "climate", articles: 7 },
  arms: [
    { language: "en", forms: ["climate"], articles: 3,
      associations: [{ term: "assembly", articles: 2 }, { term: "harbour", articles: 2 }] },
    { language: "fr", forms: ["climat"], articles: 3,
      associations: [{ term: "rapport", articles: 2 }] },
    { language: "de", forms: ["klima"], articles: 1, associations: [] },
  ],
  not_observed: [{ language: "ar", forms: ["مناخ"] }],
};

function lines(svg) {
  return [...svg.matchAll(/<line[^>]*x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" y2="([-\d.]+)"/g)]
    .map((m) => ({ x1: +m[1], y1: +m[2], x2: +m[3], y2: +m[4] }));
}
function labels(svg) {
  return [...svg.matchAll(/<g transform="translate\(([-\d.]+),([-\d.]+)\)">(?:<title>([^<]*)<\/title>)?<text[^>]*>([^<]*)<\/text>/g)]
    .map((m) => ({ x: +m[1], y: +m[2], title: m[3] || "", text: m[4] }));
}
const rOf = (p) => Math.hypot(p.x - GEO.cx, p.y - GEO.cy);
const angOf = (x, y) => Math.atan2(y - GEO.cy, x - GEO.cx);
const dAng = (a, b) => {
  let d = Math.abs(a - b) % (2 * Math.PI);
  return d > Math.PI ? 2 * Math.PI - d : d;
};

// 1. THREE LEVELS, AT THREE RADII, ALWAYS OUTWARD. The centre is AT the centre, every
//    arm is further out than it, and every association is further out than its arm.
//    An inward edge is the one thing "centre -> arms -> always outward" forbids.
{
  const svg = _anConceptTreeSvg(D, GEO);
  const L = labels(svg);
  const centre = L.find((p) => p.text === "climate");
  assert.ok(centre && rOf(centre) < 0.5, "the concept is not at the centre");
  const arms = L.filter((p) => /^(en|fr|de) \d+$/.test(p.text));
  assert.strictEqual(arms.length, 3, "one arm per language the corpus carries");
  for (const a of arms) {
    assert.ok(rOf(a) > 1, `arm ${a.text} sits on the centre`);
    assert.ok(Math.abs(rOf(a) - GEO.R) < 1, `arm ${a.text} is not on the arm circle`);
  }
  for (const term of ["assembly", "harbour", "rapport"]) {
    const n = L.find((p) => p.text === term);
    assert.ok(n, `association ${term} is missing`);
    assert.ok(rOf(n) > GEO.R + 1, `association ${term} is drawn INSIDE its arm`);
  }
}

// 2. NO CROSS-TANGLE: every association sits inside its OWN arm's angular sector, so
//    which language it hangs off is read off the picture rather than from a legend.
//    Without the sector bound, a fanned association can drift under the neighbour and
//    silently attribute a French word to English.
{
  const svg = _anConceptTreeSvg(D, GEO);
  const L = labels(svg);
  const armAng = {};
  L.filter((p) => /^(en|fr|de) \d+$/.test(p.text))
    .forEach((p) => { armAng[p.text.split(" ")[0]] = angOf(p.x, p.y); });
  const step = (2 * Math.PI) / 3;
  const owner = { assembly: "en", harbour: "en", rapport: "fr" };
  for (const [term, lang] of Object.entries(owner)) {
    const n = L.find((p) => p.text === term);
    const off = dAng(angOf(n.x, n.y), armAng[lang]);
    assert.ok(off <= step / 2, `${term} is outside the ${lang} arm's sector (${off} rad)`);
    for (const other of Object.keys(armAng)) {
      if (other === lang) continue;
      assert.ok(off < dAng(angOf(n.x, n.y), armAng[other]),
        `${term} is nearer the ${other} arm than the ${lang} one it belongs to`);
    }
  }
}

// 3. EVERY EDGE IS RADIAL — centre→arm or arm→association, never arm→arm and never
//    association→association. The rule is "no cross-tangle", and an edge between two
//    arms is the tangle.
{
  const svg = _anConceptTreeSvg(D, GEO);
  const E = lines(svg);
  assert.strictEqual(E.length, 3 + 3, "expected one edge per arm plus one per association");
  for (const e of E) {
    const r1 = Math.hypot(e.x1 - GEO.cx, e.y1 - GEO.cy);
    const r2 = Math.hypot(e.x2 - GEO.cx, e.y2 - GEO.cy);
    assert.ok(r2 > r1, "an edge points inward or sideways, never outward");
  }
  const fromCentre = E.filter((e) => Math.hypot(e.x1 - GEO.cx, e.y1 - GEO.cy) < 0.5);
  assert.strictEqual(fromCentre.length, 3, "the centre must join each arm exactly once");
}

// 4. DETERMINISTIC. Two runs over one corpus that disagree about the picture make CHANGE
//    stop being signal — the observatory's own rule, one surface over.
{
  assert.strictEqual(_anConceptTreeSvg(D, GEO), _anConceptTreeSvg(D, GEO));
}

// 5. AN ARM WITH NO ASSOCIATIONS IS STILL AN ARM. The language is a fact about the
//    corpus; having nothing to hang off it is a separate fact, and dropping the arm
//    would report the first as if it were false.
{
  const svg = _anConceptTreeSvg(D, GEO);
  assert.ok(labels(svg).some((p) => p.text === "de 1"),
    "a language with no associations lost its arm");
}

// 6. A SHARED SPELLING SAYS SO. `clima` is the ring's form for es, it AND pt, so one
//    Spanish article draws three arms of one article each — three arms that look like
//    coverage in three languages and are the same row counted three times.
{
  const shared = { center: { label: "c", articles: 1 }, arms: [
    { language: "es", forms: ["clima"], articles: 1, form_shared_with: ["it", "pt"],
      associations: [] },
    { language: "it", forms: ["clima"], articles: 1, form_shared_with: ["es", "pt"],
      associations: [] },
  ] };
  const svg = _anConceptTreeSvg(shared, GEO);
  const es = labels(svg).find((p) => p.text === "es 1");
  assert.ok(es && /it, pt/.test(es.title),
    "an arm sharing its spelling with two others does not say so in the hover");
}

// 7. NEGATIVE SPACE + escaping. No arms -> nothing drawn (an empty tree is a claim that
//    the concept exists everywhere and is quiet). A term is corpus data and reaches this
//    renderer, so it must not become an injection surface.
{
  assert.strictEqual(_anConceptTreeSvg({ arms: [] }, GEO), "");
  assert.strictEqual(_anConceptTreeSvg(null, GEO), "");
  const hostile = { center: { label: "<script>x</script>", articles: 1 }, arms: [
    { language: "en", forms: ["<b>"], articles: 1,
      associations: [{ term: "<img src=x onerror=alert(1)>", articles: 1 }] }] };
  const svg = _anConceptTreeSvg(hostile, GEO);
  assert.ok(!svg.includes("<script>x") && !svg.includes("<img src=x"), "not escaped");
  assert.ok(svg.includes("&lt;img"), "escaping should keep the text, not drop it");
}

console.log("concept_tree_node_test: all assertions passed");
