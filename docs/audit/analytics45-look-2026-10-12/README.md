# The Chromium look at analytics 4 and 5 — 2026-10-12

Row F's two cross-edition readers (Living sources → Wikipedia: **One item across editions** and
**Most-viewed pages beside your corpus**, S4, PR #1256) were Chromium-verified on 2026-09-30 in `en`,
`ar` and at phone width "awaiting human UX pass". R126 lets the sandbox walk close that pass; this is
that walk, from `main` at `6c858f353` (plus the CSS rules below), in **Chromium 141** (the sandbox's).

**It does not close row F's clause «analytics 4–5 render from real rows».** Every row here is a row
`scripts/analytics45_seed.py` wrote on purpose; the operator's walk is what puts real rows behind them.

## What was walked

An offline loopback app (booted without `OO_NO_SCHEDULER`; `GET /api/system/network` answered
`online:false` at the start of every browser context and at the end of every run) on a seeded state whose
every figure the seed prints (`python scripts/analytics45_seed.py`, which refuses a data directory that
already holds anything and a set `DATABASE_URL`): Q34 found in four editions (one of them not followed),
the walk never run in one, finished with no page in another, a stream that recorded changes for one page
of one edition and nothing for another; a one-day top list of five titles with a Wikipedia-sourced article
that must not count; a title no search index can match.

`scripts/analytics45_look.py` ran **80 runs**: 1440×900, 768×1024, 390×844, 360×800 and 320×568 × the 15
themes of the picker in English, plus Arabic (RTL) in the first theme (ink) at each width. Each run
judges **28 checks (29 in Arabic)**, **2,245 in all**:

- the suggestions are offered with their numbers (Q42: 9 changes, found in 2 editions; Q34: 3, 4) and one
  is clicked: the box and the table then show that item, with `eng` and `deu` found and the rest named;
- an item typed in lower case (`q34`) is read; six rows in the order followed then the extra edition;
  each size (8.8 KB, 11.7 KB, 300 B, 500 B); each change count (**3, 0, then `unknown` twice — an edition
  the stream recorded nothing for is never 0**); both absences named in words; the smallest and largest
  edition with no ratio; the size bars' lengths from a zero baseline over the largest (75 %, 100 %, 3 %,
  4 %); the caveat visible, not behind a toggle;
- an invalid item (`42`) is refused in words and draws no table; an item no walk found (`Q999`) draws five
  absences, each with its reason, and no size bar;
- attention: five rows with the views as given, press counts 4/6, 0/0, 2/3, `not counted`, 1/1;
- **every drop-down in the Wikipedia panel is picked and read back after the pick** (one per run, the
  attention edition; 80 of 80 held). The control is marked before the pick and looked for by node identity
  after it: **the page redraws this drop-down on every pick** (its options come from the server's answer),
  so in 80 of 80 runs the pick was read from the NEW control, the one a person now sees, and again 700 ms
  later; the rebuild is in the record (`rebuilt: true`) rather than hidden. The table it must change goes
  to 3 rows and back to 5, one request each; Refresh asks once and keeps the chosen edition;
- both tables fit their frame, with their **headroom measured** (the frame minus the narrowest the table
  can be drawn; 0 or less means the last column is cut off behind a sideways scroll); no horizontal scroll
  of the page; right-to-left in Arabic;
- every request the page made went to the loopback origin; no CSP violation; **a console error, warning,
  page error or HTTP ≥ 400 fails the run** (the text is also kept per width, theme and language in
  `console-*.txt`).

## Result

**80 runs, 2,245 checks, 0 FAIL, 0 console lines in 80 files, 0 CSP events, 0 requests off the loopback
origin; the app's server logs (three boots, 14,574 lines for the one that served this run) hold no error and one host,
`127.0.0.1`** (`server-log-check.txt`). The look script was edited after this run only in its
`--serve` handler (a route-handler argument fix found by the mutation script), which this run does not use.

**The look can fail.** `mutation_checks.py` serves the page a broken copy of one file at a time and needs the
look to exit non-zero and name the check that should catch it; first the unmutated control must pass.
`mutation-results.json`: control passes; all four caught — the changes cell drawing `0` for an unknown
count (the changes check), the edition drop-down no longer reloading (the run times out waiting for the
table), the drop-down redrawn showing the old edition (the explicit check and the generic read-back),
and the phone-width rules removed (both fit-the-frame checks at 360 px).

## The defect it found, and its fix

At **390 px both tables were wider than their frame**: the divergence table 340 px in a 316 px frame (24 px
over), the attention table 364 px (48 px over); in Arabic 342 px (26 over) and 330 px (14 over). The last
column — the figure each table is for, *changes in the last 7 days* and *articles in 7 days* — was cut off
behind a sideways scroll inside the table, with no mark that it scrolled. The page itself did not scroll,
which is why the existing "no horizontal scroll" check passed. Measured before the fix in
`before-the-css-fix/look-results.json` (and its two shots).

**The first fix was not enough, and the record says so.** Tightening only the cell padding (3 px) fitted
at 390 px (headroom +25 and **+1** px) but not at 360 px (−5 and −29) or 320 px (−45 and −69):
`padding-only-rule/look-results.json`, produced by serving that rule through `--serve`. The rule in
`app.css` now also steps the type down (at ≤ 480 px: 12 px text, 10 px headings, 2 px padding; at ≤ 340 px:
11 px, 9 px, 1 px), scoped to the two tables (`.wiki-table-wrap .living-table`; no other table uses that
wrapper). Smallest headroom over the 15 themes and both languages, divergence / attention:
**390 px +62 / +56, 360 px +32 / +26, 320 px +16 / +18**; at 768 px and above the tables fit with 263 px or
more to spare. The cost is smaller type on a phone (11–12 px text, 9 px headings at ≤ 340 px), chosen over a clipped last column.
**9 px is the floor and it is the app's smallest text** (the headings are uppercase labels over figures that stay 11 px): 10 px
headings were measured at 320 px (`ten-px-heading-probe/look-results.json`: ink, terminal and paper, served through `--serve`) and leave +4 px in the ink theme in English (+8 / +33 in Arabic), a margin a font fallback
would spend, against +16 / +18 px at 9 px.
`tests/test_analytics45_seed.py` pins the rules and keeps the seed's truth equal to what the readers answer.

## What the look does not show

- **Fixture rows, not real ones** (above). Chromium only. One page of the app; the other Living sources
  views are row I's sweep. Phone widths down to 320 px; nothing narrower.
- **The generic drop-down judge** (`csp_sweep.sweep_selects`, reused here) reads an effect from page
  mutations and requests against one idle sample; here 9 picks read `net` and 71 `dom`, none `none`
  (the earlier 48-run record had one `none`, from its idle sample catching a background request). The
  explicit check of the same pick (table to 3 rows, one request) is what proves the effect.
- The element shots (`look-*-divergence.png`, `look-*-attention.png`, ink only) were taken with the page
  scrolled to the element, so the app's sticky top bar overlaps the top of the narrow ones.

## Observations, not defects of these two readers

- Sizes read "8.8 KB" for 9,000 bytes: the app's one size formatter steps by 1024 under SI-style names
  (`_sizeText`, `app-core.js`), on every surface; the exact byte count is in the hover.
- At phone widths the *Read* column wraps `2026-10-11 18:29 UTC` onto several lines; nothing is cut.

## Repeat

```
OO_DATA_DIR=/tmp/oo-a45/state OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1 python scripts/analytics45_seed.py   # a NEW, empty directory
OO_DATA_DIR=/tmp/oo-a45/state OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_PORT=8014 python -c "from src.api.main import main; main()"   # no OO_NO_SCHEDULER: it starts offline
python scripts/analytics45_look.py --url http://127.0.0.1:8014 --out DIR
python docs/audit/analytics45-look-2026-10-12/mutation_checks.py --url http://127.0.0.1:8014
```
