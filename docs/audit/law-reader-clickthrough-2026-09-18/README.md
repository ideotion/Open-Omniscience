# Law reader — Chromium click-through, 2026-09-18

The S04-10 S1 slice's browser half: **Chromium-verified (remote sandbox) · awaiting the
maintainer's own UX pass.** Four locales × two reader views × the tracked-document panel,
driven against a real server (`OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_AUTOSEED=0`, port
8731) on a corpus seeded through the REAL tracker.

`seed.py` and `walk.py` (with `cdp.py`) are the harness that produced this, kept beside
the record so the run can be repeated rather than believed.

## The harness is not playwright, and that is worth a paragraph

The repo's standing instrument is `src/monitoring/ui_walk_playwright.py`. It could not be
used here: this sandbox cannot reach PyPI (`pypi.org` answered `503` to every attempt,
and `pip download playwright` timed out on `/simple/playwright/`), so the package is not
installable and is absent from both venvs. The **pinned Chromium build is present**
(`/opt/pw-browsers/chromium-1194`, `Chrome/141.0.7390.37`), so `cdp.py` drives it over the
DevTools Protocol directly — a ~150-line stdlib WebSocket + CDP client. The rendering, the
fonts, the JS, the RTL bidi and the screenshots are Chromium's. What is NOT covered,
relative to the standing driver: its accumulated per-surface assertions and its regression
suite. This walk is one investigation, not a replacement for that instrument.

## What was seeded

One UK Act, ingested **three times** through `track_document` with a growing CLML body —
never by inserting rows. The three passes produce a baseline plus two amendments, and the
recorded deltas are the behavioural proof of L0 defect 2:

```
{'status': 'baseline', 'size': 465}
{'status': 'changed', 'delta_bytes': 159}
{'status': 'changed', 'delta_bytes': 96}
```

`159` then `96` — each amendment measured against **the version before it**. The unfixed
code reported `159` then `255`, because both were measured against the immutable first
capture, so a row reading as one amendment carried the cumulative figure.

Three versions, not two, is deliberate: on a two-revision document the previous revision
IS the baseline, so the two anchors coincide and the fixture cannot discriminate.

## What was walked

`en` · `fr` · `de` · `ar` (RTL), each over:

1. the reader's **current text** (`/api/law/documents/1/view`),
2. the reader's **stored past version** (`?version=<baseline revision>`),
3. the **tracked-document panel** (Governments → Law), where `last_status` renders.

## What it measures, per surface and per locale

Per surface, never over a concatenation of the page:

- the **version selector** exists and lists every stored version (4 entries: current +
  three revisions) — L0 defect 1, whose failure mode was a much-amended Act rendered as
  its superseded self;
- `?version=` shows the **stored past version** and marks it as shown;
- the three **dates** appear under labels that say what each one means (`Enacted`
  2018-05-23 · `This text is in force from` 2024-01-01 · `Captured by this instance`
  2026-09-18) — L0 defect 3, whose failure mode was one field standing in for three;
- every phrase this slice added is **not English** outside `en` (`still_english` is the
  measurement, and it is `[]` for `fr`, `de` and `ar`);
- `dir` is `rtl` and `<html lang>` is `ar` on the Arabic pages;
- **zero page errors** on all twelve page loads.

## What the walk FOUND, and what was fixed because of it

The reader previously loaded no i18n at all, so every word on it was English by
construction. Adding `i18n.js` makes an unkeyed string a visible defect rather than the
status quo — and the first run found **seven** of them still English beside phrases that
had just been translated:

| surface | what it was | what was done |
| --- | --- | --- |
| meta block | `Last checked`, `Changes recorded` unkeyed | keyed ×12 |
| meta block | label `Text`, value `point-in-time consolidation` / `raw captured fetch` | label renamed `Text kind` and keyed ×12 — a bare `Text` cannot safely be a key, because the walker matches a text node EXACTLY and would translate every element anywhere whose whole content is that word |
| crumb | `Open Omniscience · World law · offline stored copy — …` | keyed ×12 |
| history | `Amendment history` | keyed ×12 |
| history | `… · baseline captured (the reference text — …)` | **could not be keyed as it stood**: the phrase shared its text node with a timestamp, so no key could ever match it. Split into its own `<span>` — the data travels BESIDE the phrase — then keyed ×12 |
| history | `No change: this is the first snapshot.` | keyed ×12 |
| footer | `Open the official gazette ↗`, its caveat line, `No official (http/https) URL recorded.` | keyed ×12 |
| footer | the page's own external-link `confirm()` | routed through `OOI18N.t` (invariant #7 names it) and keyed ×12 — a `confirm()` argument is a JS string the DOM walker never sees, and a consent string owes twelve locales |

Guards added in the same pass (`tests/test_law_l0_defects.py`), each mutation-checked and
killed by name: every chrome phrase must be a key in every locale AND still emitted by
the page; the baseline phrase must sit in its own element; the confirm must reach the
engine.

## What is still English, deliberately

- `legislation` — the stored `category` VALUE. Data, not chrome.
- `changed (+96 bytes vs the previous version)` — the stored `last_status`. It is the
  free-text operator diagnostic `_verdict_of` classifies ("a label over the real message,
  which stays visible verbatim on hover"), written in English by eight call sites that
  predate this slice. This slice made one of its values longer; translating the vocabulary
  is a redesign of a stored field with three readers and was not done here. Measured, not
  assumed: `_verdict_of` still classifies both new forms as `changed`, because
  `startswith("changed (")` is checked before the `"baseline" in s` branch.
- `+96 bytes` — a measurement with its unit. Translating the unit word needs a template
  mechanism the server-rendered page does not have, and a bare `bytes` key is the same
  trap the `Text` label just avoided.

## What this run does NOT show

- **A two-language document.** The brief's click-through asks for one; the metadata model
  that gives a document N language versions is the NEXT slice (S2). There is nothing to
  photograph yet, and a single-language document photographed as if it were the check
  would be the wrong kind of evidence.
- **A live source.** `www.legislation.gov.uk`, `eur-lex.europa.eu` and
  `gesetze-im-internet.de` are all refused by this sandbox's egress proxy
  (`connect_rejected`, gateway 403 to CONNECT). The CLML body here is a fixture. Those
  checks are `not-measurable-here` and are the operator's step.
- **The human UX pass.** Nothing here says the page reads WELL in Arabic or German — only
  that it is translated, laid out, and free of console errors.
