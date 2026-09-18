# The law metadata model in the reader — Chromium click-through, 2026-09-18

The S04-10 S2 slice's browser half: **Chromium-verified (remote sandbox) · awaiting the
maintainer's own UX pass.** Four locales × a TWO-LANGUAGE document — the original and its
official translation, on one identity — driven against a real server
(`OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_AUTOSEED=0`, port 8742).

`seed.py` and `walk.py` (with `cdp.py`) are the harness, kept beside the record so the run
can be repeated rather than believed. It is not playwright, for the reason the sibling
`law-reader-clickthrough-2026-09-18/` artefact states at length: this sandbox cannot reach
PyPI, the pinned Chromium build is present, and the walk drives it over the DevTools
Protocol directly.

## What was seeded

Two documents in the `ZZZ` synthetic jurisdiction (Q1018), ingested through the REAL
tracker:

| document | language | fixture | what it becomes |
| --- | --- | --- | --- |
| Measurement Standards Act | `zxx` | `act.v1` then `act.v2` | the original, two versions |
| Loi sur les normes de mesure | `zxx-fr` | `act.translation` | an official translation |

They land on **one identity** (`act-number:ZZZ:2019/7`) by construction, because both
fixtures state the same act number in the same jurisdiction — which is Q908's "one
document identity, N language versions" happening through the data rather than through a
link somebody remembered to write. Only the provenance and the licence are set by hand
afterwards: nothing in the catalogue states them for a synthetic jurisdiction, and
inventing a catalogue row to avoid one hand-set field would be inventing a source.

## What it measures, per locale

- the **licence** row (Q927), rendered as a link where the licence has a URL;
- the **redistribution** row — three states, never a boolean;
- the **provenance** row (Q901's note), with the phrase and the body as **separate
  elements**;
- the **identity** row (Q908);
- the **other language versions** section, read from BOTH members — a link that resolves in
  one direction only is half of what the ruling asks for;
- `dir=rtl` on Arabic, and **zero page errors** on all eight loads.

## What it found

Nothing that needed fixing. The measurements are in `report.json`; the two entries in
`still_english` are both expected and are worth naming, because a reader of the raw report
would otherwise read them as findings:

- **`fr`: "Licence" and "Redistribution".** These are the correct French words, spelled
  identically to the English. The walk's check is a substring scan over the whole page, so
  a correct translation that happens to match its source trips it. The `meta_block` in the
  same report shows the labels translated in every other locale and these two rendering as
  French; `Provenance` was translated `Origine` and `Identity` `Identité`.
- **`ar`: "Licence".** The licence NAME is *Open Government Licence v3.0* — a proper name,
  correctly untranslated. The Arabic label beside it reads `الترخيص`.

## Still English, correctly

- `legislation` — the stored `category` value.
- `changed (+160 bytes vs the previous version)` and `baseline captured` — the stored
  `last_status`, the free-text operator diagnostic (see the sibling artefact).
- *Open Government Licence v3.0*, *CC BY 4.0*, *Office of the Government Translator* —
  proper names. Keeping the body name out of the translated phrase is the entire reason
  `provenance_of` returns a pair.

## What this run does NOT show

- **A live source.** The fixtures are hand-written CLML; all three priority hosts are
  egress-blocked from this sandbox.
- **The reader's language SWITCH.** Q908 puts that in 0.5 (S05-07). This is the LINK half:
  the versions are listed and named, not switched between.
- **The human UX pass.** Nothing here says the page reads well in Arabic or German — only
  that it is translated, laid out, and free of console errors.
