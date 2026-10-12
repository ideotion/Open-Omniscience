# The Chromium look at analytics 4 and 5 — 2026-10-12

Row F's two cross-edition readers (Living sources → Wikipedia: **One item across editions** and
**Most-viewed pages beside your corpus**, S4, PR #1256) were Chromium-verified on 2026-09-30 in `en`,
`ar` and at phone width "awaiting human UX pass". R126 lets Claude's walk close that pass; this is
that walk, from `main` at `6c858f353` (plus the one CSS rule below), in **Chromium 141** (the
sandbox's).

**It does not close row F's clause «analytics 4–5 render from real rows».** Every row here is a row
`scripts/analytics45_seed.py` wrote on purpose; the operator's walk is what puts real rows behind them.

## What was walked

An offline loopback app (booted without `OO_NO_SCHEDULER`; `GET /api/system/network` answered
`online:false` at the start of every browser context and at the end of every run) on a seeded state whose
every figure the seed prints (`python scripts/analytics45_seed.py`): Q34 found in four editions (one of
them not followed), the walk never run in one, finished with no page in another, a stream that recorded
changes for one page of one edition and nothing for another; a one-day top list of five titles with a
Wikipedia-sourced article that must not count; a title no search index can match.

`scripts/analytics45_look.py` ran **48 runs**: 1440×900, 768×1024 and 390×844 × the 15 themes of the picker
in English, plus Arabic (RTL) in the first theme (ink) at each width. Each run judges **27 checks (28 in
Arabic)**, 1,299 in all:

- the suggestion buttons are offered in order (Q42 with 9 changes, Q34 with 3) and one is clicked: the box
  and the table then show that item;
- an item typed in lower case (`q34`) is read; six rows in the order followed then the extra edition;
  each size (8.8 KB, 11.7 KB, 300 B, 500 B); each change count (**3, 0, then `unknown` twice — an edition
  the stream recorded nothing for is never 0**); both absences named in words; the smallest and largest
  edition with no ratio; the size bars' lengths from a zero baseline over the largest (75 %, 100 %, 3 %,
  4 %); the caveat visible, not behind a toggle;
- an invalid item (`42`) is refused in words and draws no table; an item no walk found says so;
- attention: five rows with the views as given, press counts 4/6, 0/0, 2/3, `not counted`, 1/1;
- **every drop-down in the Wikipedia panel is picked and read back from the control after the pick**
  (one per run, the attention edition; 48 of 48 held): the table changes to 3 rows and back to 5, and the
  request it must make is counted; Refresh asks once and keeps the chosen edition;
- no horizontal scroll of the page; both tables fit their frame (the check that found the defect below);
  right-to-left in Arabic;
- every request the page made went to the loopback origin; no CSP violation; the console kept per width,
  theme and language (`console-*.txt`).

## Result

**48 runs, 1,299 checks, 0 FAIL, 0 console lines (error or warning) in 48 files, 0 CSP events, 0 requests
off the loopback origin; the app's server log (20,929 lines) holds no error and one host, `127.0.0.1`**
(`server-log-check.txt`). The look script has teeth: with the changes cell's `unknown` replaced by `0` it
fails that check (tried at 1440×900 in ink, English and Arabic), and with the attention drop-down's change handler removed it fails the run.

## The one defect it found, and its fix

At **390 px both tables were wider than their frame**: the divergence table 340 px in a 316 px frame (24 px
over), the attention table 364 px (48 px over), and 342 / 330 px in Arabic, so the last column — the
figure each table is for, *changes in the last 7 days* and *articles in 7 days* — was cut off behind a
sideways scroll inside the table, with no mark that it scrolled. The page itself did not scroll, which is
why the existing "no horizontal scroll" check passed. Measured before the fix in
`before-the-css-fix/look-results.json` (and its two shots); fixed by one rule in `app.css`
(`@media (max-width: 480px)`: 3 px cell padding on `.wiki-table-wrap .living-table`, from 8 px) and
measured after: both tables 316 px in a 316 px frame in all 16 runs at 390 px, in both languages. At 768 px and above the tables
already fitted. `tests/test_analytics45_seed.py` pins the rule and keeps the seed's truth equal to what the
readers answer.

## What the look does not show

- **Fixture rows, not real ones** (above). Chromium only. One page of the app; the other Living sources
  views are row I's sweep.
- **The generic drop-down judge** (`csp_sweep.sweep_selects`, reused here) read the attention drop-down's
  effect as `dom` in one run (aubergine, 1440) and `none` in another (sepia, 1440): its idle sample had a
  background request in it (`idle_net` 1), which is the limit row I's record names. The explicit check in
  the same two runs (table to 3 rows, one request) passed; the other 46 read `net`.
- The element shots (`look-*-divergence.png`, `look-*-attention.png`, ink only) were taken with the page
  scrolled to the element, so the app's sticky top bar overlaps the top of the narrow ones.

## Observations, not defects of these two readers

- Sizes read "8.8 KB" for 9,000 bytes: the app's one size formatter steps by 1024 under SI-style names
  (`_sizeText`, `app-core.js`), on every surface; the exact byte count is in the hover.
- At 390 px the *Read* column wraps `2026-10-11 18:29 UTC` onto four lines; nothing is cut.

## Repeat

```
OO_DATA_DIR=/tmp/oo-a45/state OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1 python scripts/analytics45_seed.py
OO_DATA_DIR=/tmp/oo-a45/state OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_PORT=8014 python -c "from src.api.main import main; main()"   # no OO_NO_SCHEDULER: it starts offline
python scripts/analytics45_look.py --url http://127.0.0.1:8014 --out DIR
```
