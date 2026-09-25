# Storage budgets click-through — 2026-09-25 (S04-08 S4, gate row O)

Chromium (Playwright, `/opt/pw-browsers/chromium`) against a real server
(`OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_AUTOSEED=0`, port 8744) on a data folder that
`seed.py` prepared: a corpus, a real `wiki.db` made by `create_lane("wiki")`, and
`lane_mib_*` rows — 19 days for the corpus (so a rate is measured) and 2 days for the wiki
lane (so the refusal shows). Languages switched through the real top-bar switcher
(invariant #15); Settings → Data & backup opened through its real subtab button. The
first-run guide opens over a fresh install and is closed before each step; it is not the
surface under test.

| View | Result |
|---|---|
| en / fr / ar at 1440 px, en at 375 px | Reading, table, disk line and caveat translated (ar right-to-left). Corpus: `+6.0 MB in 19 days`, `≈ +9.5 MB per 30 days at that rate`. Wiki: `20 GB the published default`, `<1% used`, `Not measured yet`. Law and maps: `Not built yet`, `No published budget`, no growth. No horizontal page scroll; **0 page errors** |
| Raise the wiki budget to 35 → Save | `Saved.`; the row reads `35 GB yours; the published default is 20 GB`; the config holds 35; with 28.3 GB free the disk line turns into the caveat `… That is more than the drive has free.` (`storage-en-1440-raised.png`) |
| 1.5, then 5000 → Save | Both refused on the page in the operator's language (`Enter a whole number of GB from 1 to 2000.`); the config still holds 35 |
| Back to 20 → Save | `20 GB the published default` again |

`report.json` holds the measured values; `seed.py` and `walk.py` reproduce it.

**Found and fixed by this walk, before it was recorded:**

- The server rounded the used share to four decimals, so a 120 KiB lane under 20 GB was
  `0.0` and the panel drew `0% used` for a lane that holds something. The share is now
  sent unrounded (`test_a_small_lane_is_never_rounded_into_an_empty_share`).
- A budget over the maximum reached the server and came back as its English field
  message. The page now refuses a fraction or an out-of-range number itself, in the
  operator's language, using the bounds the server put on the input.
- In Arabic, `+6.0 MB` rendered as `MB 6.0+`, and the hover's ISO dates would have put
  the year at the wrong end. The signed figures and the dates now go through the app's
  existing `_ltrIsolate` (asserted in `lane_storage_node_test.js`).

**Still owed:** the maintainer's own click-through (Q1128 = a). At 375 px the table
scrolls sideways inside its own box, as the app's other wide tables do.
