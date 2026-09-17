# S04-07 — the concept map and the watch that covers a ring (2026-09-17)

Chromium in the remote sandbox at 1280×900, five locales for the mind map (`en` · `ar` ·
`zh` · `ja` · `hi`) and two for the Watches panel (`en` · `ar`), against the same live
instance as the [lens click-through](../cross-language-lens-clickthrough-2026-09-17/):
the standing STATE C seed plus nine concept-bearing fixture articles.

Q1128 = a's bar is *Chromium in the sandbox **plus** the maintainer's own click-through*.
**This is the first half; the maintainer's pass is still owed**, and the honest stamp is
"Chromium-verified (remote sandbox) · awaiting human UX pass".

Re-run: `OO_WALK_URL=http://127.0.0.1:8010 .venv/bin/python walk.py --out .`

## Why a browser, when the geometry is already measured in node

`tests/concept_tree_node_test.js` reads the coordinates back out of the emitted SVG and
measures the mind-map rules directly — every edge outward, every association inside its
own arm's angular sector, deterministic, nothing crossing. It cannot see a **label**. An
SVG does not clip its text, so an arm whose label is long simply leaves the picture, and
that is a per-locale and per-script failure by definition. So the walk measures one thing
node cannot: how many `<text>` nodes fall outside the canvas rectangle.

## What it found — two defects in the harness, one in the app's own boot

**The Map button's handler contains the word "concept".** `anMMset({cloud:false,
concept:false})` — so the walk's first version, matching the substring `concept`, clicked
**Map**, measured the radial keyword map, and reported it as the Concept view. It read as
a pass. The matcher now requires `concept:true`. Recorded here because the shape is
general: a click-through that selects a control by a substring of its handler is one
refactor away from measuring the wrong surface and saying nothing.

**The first locale walked pays the cold start.** A fixed settle tuned on the second
locale measured an empty panel in `en` and reported "no Concept button" — a fail that
looks exactly like the feature being absent. The walk now WAITS for the control.

**`python -m src.api.main` serves a half-broken app.** Booting that way makes the module
`__main__`, and `src/api/insights.py`'s runtime `from src.api.main import _query_articles`
then imports it a SECOND time under its real name — re-executing the Prometheus `Counter`
definitions and raising `DuplicateTimeseries`. `/api/insights/graph` returns a 500 whose
message is about a metrics registry. Booting through the console entry
(`.venv/bin/open-omniscience serve`, which is what `open-omniscience` does) is unaffected,
**but `_run_ephemeral` spawns `[sys.executable, "-m", "src.api.main", ...]`** — so
`--ephemeral` ships this. Pre-existing (the import is on `main` at `insights.py:417`) and
NOT fixed here, because it has nothing to do with cross-language search; recorded with its
reproduction so it is a finding rather than a rumour.

## The Concept view, read back from the rendered DOM

Identical in all five locales, `ar` at `dir=rtl`:

| what | measured |
|---|---|
| view buttons | `Map · Cloud · Concept · ⛶` (localised: `概念` · `संकल्पना` · `المفهوم`) |
| SVG labels | `climate` (centre) + `eng 3 · fra 3 · deu 1 · spa 1 · ita 1 · por 1` (arms) + `assembly · rapport` (associations) |
| edges | **8** — six centre→arm, two arm→association, and nothing else |
| labels outside the canvas | **0** |
| the omission, named | `Not observed in this corpus: ara: مناخ · nld: klimaat · rus: климат` |

The arm labels are **alpha-3** (`eng`, `fra`, `deu`) with the localised language name in
the hover — Q302, expressed in the markup an SVG can hold: `ooLangCell` renders an HTML
`<span title=…>` that an SVG `<text>` cannot, so the code comes from `ooLangCode` and the
name joins the `<title>` the node already carries. The first version of this view drew
the bare two-letter code and `test_alpha3_display_surfaces` caught it.

Six arms over seven articles is the overlap the caveat warns about, visible in the
picture: `clima` is the ring's form for Spanish, Italian **and** Portuguese, so one
Spanish article draws three arms of one article each. The arms say so in their hover
(`form_shared_with`) rather than letting three arms read as coverage in three languages.

`مناخ` sits in `not_observed` although the corpus holds an Arabic fixture article about
exactly that: the article writes it with the definite article (`المناخ`) and the index has
no Arabic folding yet — the same gap the lens click-through measured, which is what
S8/Q507 exists to close.

## The watch row

A watch on `climate`, created through the real API and read back off the panel:

> This watch covers the concept “climate” in every language its ring carries.

with the ring's per-language members in the hover, and the expansion caveat once at the
foot of the panel rather than once per row. `ar` renders `dir=rtl` with the caveat in
Arabic.

## Not covered here

375 px width; the ⛶ enlarged mind map; the Cloud view; the watch FIRING path (a firing
needs new articles after the watch is created, which this static corpus cannot produce —
it is driven in `tests/test_watch_rings.py` instead); `fr`, `de`, `es`, `pt`, `ru`, `bn`,
`id`. Each is a surface this walk did not reach, **not** one that passed.
