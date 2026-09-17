# S04-06 — the keyword label, rendered in four locales (2026-09-17)

Chromium in the remote sandbox, against a live instance seeded through the app's own
`scripts/ui_clickthrough_seed.py` (STATE C: 440 articles across the language pool, indexed
by the real `index_article`). Q1128 = a's bar is *Chromium in the sandbox + the
maintainer's click-through*; **this is the first half. The maintainer's own pass is still
owed**, and the honest stamp is "Chromium-verified (remote sandbox) · awaiting human UX
pass", never "verified".

## Why a rendered page and not the node suite

`tests/keyword_label_node_test.js` drives the shipped renderer and proves the HTML. It
cannot see the page. The two failures this slice actually risks are both invisible to it:
the i18n DOM walker translating a keyword because it happens to match a chrome key, and an
RTL or CJK locale clipping or mis-ordering the tag. Both need a browser.

## What it found — a real defect, on the first run

The tag read **`in Russian` in all four locales**, including `ar` and `zh`, while the page
chrome switched correctly (`ar` came back `dir=rtl`). The keyword labels opt out of the
i18n walker via `data-i18n-dyn`, so nothing repaints them on a language switch — and the
repaint list had been written from memory and was **wrong about three of its four host
ids**. `#home-trends`, the panel actually on screen, was not on it.

No test could see this. The helper was correct, the keys were in all twelve locale files,
the node suite passed, and all three i18n gates were green. The list is now DERIVED from
the call sites, and `test_keyword_label_ui.py::test_every_surface_that_renders_a_keyword_
label_also_repaints_on_a_language_switch` asserts that derivation holds — mutation-checked
by deleting `home-trends` from the list, which reproduces this exact defect and reddens
the test by name.

## After the fix — read back from the rendered DOM

| locale | dir | tags | clipped | untranslated | verified |
|---|---|---|---|---|---|
| en | ltr | 12 | 0 | `in Russian` | — (none on screen) |
| fr | ltr | 16 | 0 | `en russe` | `traduit de : anglais` |
| ar | rtl | 17 | 0 | `اللغة: الروسية` | `مترجم من لغة: الإنجليزية` |
| zh | ltr | 17 | 0 | `语言：俄语` | `译自：英语` |

19 `.kw-term` spans per locale, **all** carrying `data-i18n-dyn`; the Russian term
`избирателей` is rendered untranslated in every locale, which is the point. The language
NAMES are localised by CLDR (`russe` / `الروسية` / `俄语`), which is Q402 = a working
through one keyed frame rather than 144 hand-written names. Zero clipped tags at 1280×900.

## The tier distribution, and the denominator that matters

Measured live on this corpus over the top 200 keywords, per target language:

| target | n | untranslated | same_language | verified |
|---|---|---|---|---|
| en | 200 | 170 (85.0%) | 30 (15.0%) | 0 |
| fr | 200 | 189 (94.5%) | 8 (4.0%) | 3 (1.5%) |
| ar | 200 | 142 (71.0%) | 53 (26.5%) | 5 (2.5%) |
| zh | 200 | 150 (75.0%) | 45 (22.5%) | 5 (2.5%) |

**This is a different number from the 96.4% verified measured over the ring TABLE, and
both are real.** 96.4% answers "of the ring members, how many resolve into a target
language" — the table's internal completeness. The 1.5–2.5% here answers "of the keywords
a reader actually sees, how many carry a verified translation" — the coverage of the
surface. Quoting only the first would be a verdict mapped to a bar it never tested.

The gap is not a defect in the ladder; it is the ring table's reach, and it is exactly what
Q407's gap digest (`_ring_candidates`) and Q410's operator ritual exist to close. It is
also the honest argument for building S06 (the consented in-app ring job), which this PR
does not.

## Not covered here

375 px (phone) width; the analysis window's subtabs; the mind map; the Observatory labels;
the bulletin; the sense picker (the fixture corpus reached no colliding term on screen);
the tentative tier (no local model ran). Each is a surface this walk did not reach, not a
surface that passed.
