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

---

# S6 — the Wikidata ring panel, rendered in four locales (same day, same instance)

`rings-en.png` · `rings-fr.png` · `rings-ar.png` · `rings-ja.png` · `rings-consent.png`,
measurements in `report-rings.json`. **`ja` is here because the brief named it and the walk
above did not reach it** — that was a substitution (`zh` for `ja`), and a locale not walked
is not a locale that passed.

## What was checked, and why a browser was needed for it

Two claims, neither visible to a source test. First, that the panel's caveat is **on the
surface** — the informed-consent non-negotiable, and the reason it needs a rendered page is
that `.card-caveat` is a class the flip-card briefing also uses, so "the element is in the
DOM" says nothing about whether this one is painted. Second, that the **consent dialog
stands between the button and the egress**, which is a runtime fact about `ensureOnline`,
not a source fact about a call site.

| locale | dir | panel on screen | caveat visible | overflows | title as rendered |
|---|---|---|---|---|---|
| en | ltr | yes | **yes** | no | Keyword translations — load rings from Wikidata |
| fr | ltr | yes | **yes** | no | Traductions des mots-clés — charger des anneaux depuis Wikidata |
| ar | **rtl** | yes | **yes** | no | ترجمات الكلمات المفتاحية — تحميل الحلقات من ويكي بيانات |
| ja | ltr | yes | **yes** | no | キーワードの翻訳 — Wikidata からリングを読み込む |

The gap read renders the same figures in all four (`200 concepts have no ring`, chips
`60 · 60 · 60 · 20` over German / Chinese / French / English on this seeded corpus), which is
the per-language round-robin working: a flat top-200 would have been one language deep.

## The consent gate, exercised rather than asserted

The load button was clicked **with the kill switch engaged**, with Chromium recording every
request the page made:

```
dialog_on_screen   : true
dialog_text        : "Go online? This action needs the network: Where this will let the app
                      connect: Your machine presents these local network addresses: …"
offsite_requests   : []      ← nothing left the machine
```

That is invariant #14's one popup doing its job on a new lane, and the honest half of what a
sandbox can prove: **no request was made to Wikidata by this walk at all.** The live API has
not been exercised from the app — that is the operator ritual (Q410), and it stays owed.

## Two harness defects found first, both of which would have produced a false reading

Worth recording because each produced a *confident wrong answer*, not an error:

1. **The first run reported `caveat_visible: false` in every locale.** `_openAdvanced` opens
   the Advanced *subtab* and the accordion; it does not switch the main tab. So the panel was
   readable in the DOM — `textContent` works on hidden nodes, and the titles, buttons and
   caveats all came back correctly translated — while the whole Settings view was
   `display:none`. A measurement of an off-screen element reads exactly like a styling bug.
   The harness now calls `showTab('settings')` first and records `panel_on_screen` and
   `settings_visible` beside the claim, so a navigation that silently fails can no longer be
   reported as an invisible caveat.
2. **The consent step hung.** `page.evaluate("() => ringLoadStart()")` returns the async
   function's promise, which Playwright awaits — and that promise does not resolve until the
   consent dialog is answered, which is precisely what the test is there to observe. The call
   now discards the promise.

## Not covered here

375 px width; a real load against Wikidata; the task-manager row for a running load; the
cancel path mid-wait; the eight alternative GUIs. Each is a surface this walk did not reach,
not a surface that passed. The stamp stays **Chromium-verified (remote sandbox) · awaiting
human UX pass**.
