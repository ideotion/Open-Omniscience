# The Chromium look at analytics 4 and 5, on rows the app's own walk code wrote — 2026-10-15 (`R133`)

Row F's two cross-edition readers (Living sources → Wikipedia: **One item across editions** and **Most-viewed pages beside your
corpus**) were walked on 2026-10-12 on rows `analytics45_seed.py` wrote straight into the tables
(`docs/audit/analytics45-look-2026-10-12/`). This is the same walk on a state the **app's own code** wrote.

**Every row here is a stand-in's. Nothing in this folder is a measurement of Wikipedia, and it does not close row F's clause «render from real
rows»** (`RELEASE_0.5_GATE.md` §1c item 4). It shows that the readers draw what the walk code stores.

## How the state was made

`scripts/analytics45_generate.py` runs `WikiClient` (its parameter builders and parsers), `WikiWalker`, `WikiEventStream` → `WikiStreamAdapter` →
`drain_once`, the service's own `_refresh_one_pageview_top` and the `index_article` chokepoint, against `src/testing/wiki_standin.py`: a seeded
(`20261015`) world of six editions (3,000 / 1,500 / 2,000 / 1,200 / 800 / 600 titles) that answers the Action API's `meta=siteinfo` and
`generator=allpages` calls, the pageviews REST call and an EventStreams text, and raises on anything else. A socket tripwire refused every
non-loopback connection for the run. The walk stopped mid-pass in `en` (41 of 60 windows), completed in `de`, `fr`, `ar` and `it`, and never ran
in `es`; the stream sent 104 events and the lane recorded 89 edits (talk-page, redirect and un-followed-edition events were filtered by the app); five
top-viewed lists were stored; 63 press articles were indexed. The script then read the lane back against its plan and exited non-zero on any
difference: none (`truth.json` is the plan it printed).

**The one measured input** is the share of a 50-title window that is not a redirect: en 36 %, fr 58 %, de and es 91 % (the 2026-10-06 bundles);
`ar` 50 % and `it` 60 % are assumed. The mechanism (a window of 50 titles with the redirects filtered out after it) is read from MediaWiki's
documentation and was not reproduced. Other simplifications: one answer per window, `articles` equal to the non-redirect count, syllable titles.

## What was walked

An offline loopback app (`GET /api/system/network` answered `online:false` at the start of every browser context and at the end of every run) on that
state; `scripts/analytics45_look.py --truth truth.json`: **80 runs** — 1440×900, 768×1024, 390×844, 360×800 and 320×568 × the 15 themes in English, plus
Arabic at the first theme — each judging 28 checks (29 in Arabic), **2,325 in all**, against the PLAN (never against the lane): the suggestions by their
numbers (Q42: 9 changes, found in 2 editions; Q34: 3, 4; Q7001: 2, 2; Q7002: 1, 1), the six-row table for Q34 (sizes 8.8 KB, 11.7 KB, 300 B, 500 B;
changes 3, 0, unknown, unknown; bars 75 / 100 / 3 / 4 %; the two absences in words), the invalid and unknown items, all 50 rows of the `en` top list with
their press counts (day / week, `not counted` for the bare «-»), **every option of the edition drop-down picked** (en, de, fr, es, ar: each read back
from the control now on screen, the page rebuilds it on every pick — `rebuilt` is recorded — and the table it draws judged row by row), every drop-down
in the panel, both tables inside their frame with headroom measured, no page scroll, right-to-left in Arabic, every request to the loopback origin, no
CSP event, and a console error, warning, page error or HTTP ≥ 400 failing the run.

## Result

**80 runs, 2,325 checks, 0 FAIL, 0 console lines (`console-all-80-runs.txt`: only the 80 headers), 0 requests off the loopback origin; the app's server log
(12,057 lines) holds no error and one address, `127.0.0.1`** (`server-log-check.txt`). No defect found in the readers or the page on this state.

**The judges can fail.** (1) Run once against a copy of the plan with three values changed (a size, a press count, a suggestion's change count) the
look failed exactly those three checks. (2) `mutation_checks.py --truth` serves the page a broken copy of one file at a time: control passes, all four caught
(`mutation-results.json`). (3) `tests/test_analytics45_generate.py` asks the real readers the same questions of the generated state, and mutating the
stand-in's item answer or the plan's press count failed it.

Screenshots: `look-*.png` (ink theme, a selection of widths); the tall element capture at 360 px may show the sticky top bar over a long table — a capture
artefact, not a page defect.
