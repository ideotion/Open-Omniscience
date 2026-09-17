# S04-07 — the cross-language lens, rendered in five locales (2026-09-17)

Chromium in the remote sandbox at 1280×900, against a live instance: the standing
`scripts/ui_clickthrough_seed.py` STATE C (440 articles across the language pool, indexed
by the real `index_article`) **plus nine articles added by `concept_fixture.py`**, because
the standing seeder's per-language prose is about a climate *topic* and does not carry the
ring's surface forms (`Klima`, `مناخ`, `climat`) — a walk over it alone would have
exercised the rail against an empty expansion. One of those nine is deliberately bilingual,
so the overlap the per-form readout warns about is **on screen** rather than only in the
caveat.

Q1128 = a's bar is *Chromium in the sandbox **plus** the maintainer's own click-through*.
**This is the first half. The maintainer's pass is still owed**, and the honest stamp is
"Chromium-verified (remote sandbox) · awaiting human UX pass".

Re-run: boot the app against a seeded store, then
`OO_WALK_URL=http://127.0.0.1:8010 .venv/bin/python walk.py --out .` — measurements land
in `report.json`, screenshots beside it.

## What it found — three defects, none of which a test could see

**1. The server's own caveat rendered in ENGLISH on four translated pages.** The rail's own
sentences are `OOI18N.tf` frames and were correct in `ar`, `zh`, `ja` and `hi`. The caveat
beneath them arrived in the payload and the client escaped it straight onto the page. Every
i18n gate was green, because the gates measure the locale FILES and a string that never asks
for a key is not missing one. Fixed by passing server prose through `t()` — the convention
`_anRenderProvenance` already uses — and keying all four sentences ×12. **The same fix
removed a number from prose:** the caveat read *"Rings cover 698 concepts"*, which goes
stale the moment the ring file grows **and** makes the sentence unkeyable, since a locale
key must match verbatim.

**2. A boot RACE, visible in exactly one locale.** A deep link straight to an analysis in
`hi` rendered the rail's frame in English while `ar`, `zh` and `ja` came out translated —
the analysis fetch simply beat the locale fetch. Which locale loses is a matter of file
size and timing. Closed by awaiting `OOI18N.ready` (the promise this project added for this
exact race), with the rail also registered in app-boot's ONE `oo:langchange` listener so a
language *switch* redraws it from the payload already in hand and never fetches.

**3. `class="linkish"` styled nothing.** All nine inline controls of this feature — the way
back to the literal term, the sense picks, the cap switch, the per-form count trigger —
carried a class with **no CSS rule anywhere in the tree**, so every one fell through to the
primary `button` rule: a stack of filled accent blocks where the author wrote a link, one of
them landing mid-sentence and breaking the caveat's line in half. Invisible to every test in
the repository and obvious in one screenshot. Now styled as underlined inline links
(underlined, never colour alone), and the group-by control became a **segmented pair with
stable labels** rather than one button whose label flips — a flipping label has to name the
action while `aria-pressed` describes the state, so a screen reader announced *"Interleave
by date, pressed"* about a view the reader was not in.

## After the fixes — read back from the rendered DOM

| locale | dir | rail on screen | caveat language | overflow | rows | with a Language cell | groups |
|---|---|---|---|---|---|---|---|
| en | ltr | yes | English | 0 px | 50 | 50 | 5 |
| ar | **rtl** | yes | **Arabic** | 0 px | 50 | 50 | 5 |
| zh | ltr | yes | **Chinese** | 0 px | 50 | 50 | 5 |
| ja | ltr | yes | **Japanese** | 0 px | 50 | 50 | 5 |
| hi | ltr | yes | **Hindi** | 0 px | 50 | 50 | 5 |

Identical in all five: the column headers localised (`اللغة` · `语言` · `言語` · `भाषा`),
zero horizontal overflow, the count trigger present and answering, `cap=0` and `expand=0`
entering the URL on a toggle and leaving it again, and grouping preserving all 50 rows.

## The numbers the lens actually moves

**The literal toggle is a real refusal, not an approximation of one:** the list reports
**160** articles with expansion on and **156** with it off, on the same corpus, in every
locale. The four are the French, German, Spanish and bilingual fixture articles.

**The per-form counts, and the overlap demonstrated:**

```
climate 156 · climat 3 · clima 1 · klima 1 · klimaat 0 · климат 0 · مناخ 0
sum of the forms : 161          TOTAL (distinct) : 160
```

The sum exceeds the total by exactly the bilingual article, which is counted under
`climate` **and** under `climat` and **once** in the total. That is the caveat beside it,
measured rather than asserted.

## What it also measured, which is a gap rather than a pass

**`مناخ` is searched and matches nothing**, although the corpus contains an Arabic fixture
article about exactly that. The article writes it with the definite article (`المناخ`) and
the index has no Arabic alef/definite-article folding, so the ring's bare form never
matches. **This is precisely what `S04-07`'s S8 slice (Q507) exists to fix**, and it is
recorded here as the measurement that will show whether it worked. `klimaat` and `климат`
read 0 honestly: this corpus carries no Dutch or Russian article using them.

## The other named surfaces

Search, Insights, the Observatory and the world map were rendered in `en` and `ar` and
recorded **zero page errors** in all eight combinations, `dir=rtl` throughout the Arabic
pass. That is a rendering check, not a feature walk — none of those four surfaces reaches
the concept by term (they reach the corpus by id), which is the premise correction PR #1149
recorded against Q516.

## Not covered here

375 px (phone) width; the analysis window's other subtabs; the mind map (Q512, not built);
the stacked per-language trend (Q502, not built); the sense picker — the fixture corpus
reached no colliding term on screen, so the R2a refusal is proven in
`tests/cross_language_lens_node_test.js` and not here; `fr`, `de`, `es`, `pt`, `ru`, `bn`,
`id`. Each is a surface this walk did not reach, **not** a surface that passed.
