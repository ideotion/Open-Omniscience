# Trust-the-scraping-history toggle — Chromium click-through, 2026-09-16

The Q701-NOTE surface built in `S04-04`, walked in a real browser on both of the two
places the note names: **at install** (the guide wizard's *sources* step, where the
answer becomes the stored default) and **at import** (the unified import dialog, where
it overrides that default for one import).

Chromium 1194 (headless, `/opt/pw-browsers/chromium-1194`), Playwright 1.63, against a
live app on a fresh `OO_DATA_DIR` with `OO_DB_PLAINTEXT=1` and `OO_NO_SCHEDULER=1`.
Q1128 = a makes this the verification bar; the browser half is `run.py` and its verbatim
record is `report.json`.

## What was driven, and what it measured

| Step | Measured |
|---|---|
| `wizard/en` · `wizard/fr` · `wizard/ar` | the toggle is really on the **`sources`** step (`data-step`, read from the DOM — the screenshots are taken scrolled, so "it looked like the language step" is exactly the reading a picture supports and a measurement settles); label, visible caveat and layered hover all render in the locale; `dir="rtl"` for Arabic |
| `import/before-scan` | the row is **absent** before a scan finds anything — a toggle over nothing would claim a capability it does not have |
| `import/after-scan` | a real `oo-backup-3` artifact, written by the app's own writer, makes the row appear, seeded from the stored answer |
| `import/three-states` | `_uxImTrust()` read off the LIVE control: unchecked → `false`, checked → `true`, row hidden → **`null`** |
| `import/fr` · `import/ar` | the same dialog in the other two locales |

`import/three-states` is the one that matters. `null` is "this import did not choose",
which the server resolves to the stored answer; `false` would tell it the operator
declined a history they were never shown, and the restore would then re-download a
corpus the backup already carried.

## The defect this walk found, and the fix

`app.css` styles `input, select, textarea { width: 100% }`. A bare
`<input type="checkbox">` inherits it, so **both** new checkboxes rendered ~340–360 px
wide, pushing each label far from its box. Nothing in the test suite could see it — a
source guard reads markup, not layout.

Fixed with the repo's own escape (`style="width:auto"`, as `#cust-ots` and
`#set-rerun-guide` already use). Re-measured: 13 px on all four surfaces. The walk now
asserts the rendered width so the fix cannot silently come undone, and
`tests/test_fetch_history_member.py::test_the_checkboxes_escape_the_global_input_width`
holds the same line where CI can reach it.

## Not measurable here

A real operator restore — an artifact from another machine, a genuinely populated
corpus, a wall-clock comparison of collection passes with and without the history —
needs an operator and two machines. The fetch-history mechanism is proven in
`tests/test_fetch_history_member.py` through the collector's own `feed_is_due` and
`_feed_conditional_headers`; the *saving* it produces in the field is not.
