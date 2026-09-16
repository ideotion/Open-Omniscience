# Alpha-3 display click-through — 2026-09-16 (S04-05, gate row L)

Chromium (Playwright, `/opt/pw-browsers/chromium-1194`), one seeded instance on
`127.0.0.1:8010` (`ui_clickthrough_seed.py --mini` + `POST /api/law/seed`: 24 articles,
1454 catalogue sources of which 495 carry a country, 23 tracked legal documents, 152
agenda events), walked in **en · fr · ar (RTL) · zh** — the brief's §4 locale set.

**What was being verified.** Q302 as its note rules it: *the country CODE is displayed,
the localised name is in the hover.* Plus Q306 = b for language codes, Q303's four
non-ISO disclosures, and that nothing on a walked surface still shows a bare stored
alpha-2. Zero page errors were raised in any locale.

## The helpers, driven in the browser on the shipped code

| call | result |
| --- | --- |
| `ooCountryCell("fr")` | `<span title="France">FRA</span>` |
| `ooCountryCell("uk")` | `<span title="United Kingdom">GBR</span>` — Q303 |
| `ooCountryCell("eu")` | `<span title="European Union — not an ISO code">EUU</span>` |
| `ooCountryCell("xk")` | `<span title="Kosovo — not an ISO code">XKX</span>` |
| `ooCountryCell("int")` | `<span title="International — not an ISO code">INT</span>` |
| `ooCountryCell("an")` | `<span title="Netherlands Antilles — not an ISO code">ANT</span>` |
| `ooCountryCell("zz")` | `<span title="not a recognised country code">zz</span>` — degrades loudly |
| `ooCountryCell("")` | `` — empty, never a fabricated marker |
| `ooLangCell("fr")` / `("zh")` | `<span title="French">fra</span>` / `<span title="Chinese">zho</span>` |
| `ooLangCell("pcm")` | `<span>pcm</span>` — no 639-1, so no name, and none invented |

The `an` and `int` rows are the two the run FIXED: see *Findings* below. Measured in the
same browser, in each locale: `Intl.DisplayNames(…,{type:"region"}).of("AN")` returns
`Curaçao` / `كوراساو` / `库拉索`. The override is what stops that reaching the hover, and
it ships ×12 — `Antilles néerlandaises`, `جزر الأنتيل الهولندية`, `荷属安的列斯`.

## The hover convention (invariant #17), measured end to end

Hovering the first alpha-3 cell in the Laws table: element carries
`class="oo-tip-target"` (the MutationObserver marked it), `title="Canada"`, and the
shared `#oo-tip` bubble opened reading **Canada**. The bubble re-reads the live
translated title, so the layer is ×12 by construction.

## Per surface

| surface | en | fr | ar (RTL) | zh |
| --- | --- | --- | --- | --- |
| Laws (`#tab-law` → Law) | `CAN`/Canada, `DEU`/Germany, `EUU`/… | `DEU`/**Allemagne** | `CAN`/**كندا**, `EUU`/**الاتحاد الأوروبي — ليس رمزًا من رموز أيزو** | `DEU`/**德国**, `EUU`/**欧盟 — 非 ISO 代码** |
| Agenda (month + year views) | 32 alpha-3 tokens incl. `EUU` | same | same | same |
| Library → World coverage | 218 country cells, **every one** with a hover name | ✓ | ✓ (see finding 2) | ✓ (see finding 2) |
| Settings → Data (sources table) | `ISR`/Israel, `FRA`/France, `UGA`/Uganda; `eng`, `fra` | ✓ | `UGA`/**أوغندا** | `ISR`/**以色列**, `eng`/**英语** |
| Settings → Data (country filter) | `Argentina (ARG) ·75` | ✓ | `أرمينيا (ARM) ·9` | `阿根廷 (ARG) ·75` |
| Settings → Wikipedia (invariant #1) | `<select id="wiki-lang">`, 147 flat options, native name first | ✓ | ✓ | ✓ |
| Map (`#tab-timemap`) | renders; signal detail needs a click-through with located signals | ✓ | ✓ | ✓ |
| Governments → Countries / Map | **not walkable offline** | | | |
| Markets | **not walkable offline** | | | |

The country FILTER shows the name *and* the code on purpose: a checkbox label has no
hover to layer a name into, which is ruling Q308 and why it is not a Q302 exception.

### The two surfaces that could not be walked

Governments → Countries/Map reads `/api/governments/map`, and Markets reads the market
importers; both are empty on a machine that has never been online, so the walk saw
their honest empty states rather than a country. That is a **data gap in this run, not
a verified surface** — recorded as such rather than counted as a pass. Their renderers
are covered by `tests/test_alpha3_display_surfaces.py`'s table
(`app-gov-law.js`: the roster, the value label, the spread min/max; `app-map.js`: the
per-area figures table and the indicator line), which is a weaker instrument than a
real screen and is stated as weaker.

## Findings — both fixed in this PR

**1. The two halves of one helper disagreed about `an` and `int`.** The server's
`SPECIAL_CODES` names `an` *Netherlands Antilles*; the browser asked CLDR, and
`Intl.DisplayNames(…,{type:"region"}).of("AN")` answers **Curaçao** — CLDR aliases the
withdrawn code to its successor territory, so the hover named a DIFFERENT place than
the code means. `INT` is not a region at all, so CLDR threw and the name was simply
absent. Only a real browser could find this: node has no CLDR region data of its own to
disagree with. `OO_CLDR_WRONG_ABOUT` in `app-core.js` now owns those two names, ×12,
and `eu`/`xk` are deliberately NOT in it — CLDR names both correctly in every UI locale
and an English table beside it would be the worse answer.

**2. The coverage panel froze its locale — and the first fix for it was half a fix,
which the re-walk is what caught.** Walking en → fr → ar → zh left every one of the 218
hovers reading **French**. Pre-existing: the same "frozen-locale" family the
`oo:langchange` handler in `app-boot.js` already documents for the Lead titles and the
Composition figures, and newly load-bearing because the localised name now lives in a
hover rather than in the visible text.

It needed BOTH halves, and each looked sufficient on its own:

* The panel has **two** repaint guards that fingerprint the payload — one for the map,
  one for the 218-row table — and the first pass made only the map's locale-aware. The
  re-walk then read `ar` showing French and a second `en` showing Chinese: a pattern
  that looks like a timing flake and is not. Both now fingerprint through one
  `_covUiLang()`, because two guards disagreeing about one quantity is how this
  happened.
* With both guards fixed, a **forced** `loadCoverage()` came back correct in every
  locale and a bare language switch still did not — because nothing re-ran the loader.
  The `oo:langchange` handler now re-renders it, guarded on the table already having
  rows exactly as `src-table` beside it is, so a switch never fetches for a panel the
  reader has not opened (measured: 0 rows on an unopened panel).

Re-verified on a bare switch with no re-navigation, fr → ar → zh → en → ar → fr, every
step correct, zero page errors.

## Reproducing

Seed, boot, then drive. The walk scripts are one-off instruments for this slice and
live in the session scratchpad rather than in `scripts/`; the standing instrument is
`scripts/ui_clickthrough_run.py`, whose per-release encrypted run (Q1149) is a separate
obligation this report does not discharge.

```
OO_DATA_DIR=<dir> OO_DB_PLAINTEXT=1 .venv/bin/python scripts/ui_clickthrough_seed.py --mini
OO_DATA_DIR=<dir> OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 \
  .venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8010
curl -s -X POST http://127.0.0.1:8010/api/law/seed
```
