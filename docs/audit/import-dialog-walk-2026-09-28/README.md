# Import dialog walk — 2026-09-28

Asked in the claim-workspace thread: «did you check the import window and how it reacts to an
active import? I heard there was some overlapping texts during import or during an import that
followed a failed import», then «I'm thinking about the language, the translation, and the overall
aesthetics of the UI and the overall user experience».

Chromium (Playwright, `/opt/pw-browsers/chromium-1194`) against real servers started with
`OO_DB_PLAINTEXT=1 OO_AUTOSEED=0 OO_NO_SCHEDULER=1`. `seed_big.py` made two installs (60,000 and
40,000 invented articles, `.invalid` hosts); each was exported through the app's own
`/api/backup/export-folder` + `/api/backup/v2/volumes/start` as an encrypted volume set, into one
folder. Every walk then used a fresh install holding 3,000 of the first backup's articles
(`fresh_dest.sh`), so the import has new articles and duplicates.

`walk_import.py` drives the real dialog: Settings → Data & backup → Import…, the folder, Scan, then
the scenario. It records the dialog on every change of its text: the text itself, every pair of
text boxes that overlap (per text node, `Range.getClientRects()`, closed `<details>` excluded),
text outside the dialog's edges, horizontal scroll, leftover `{placeholders}` / `undefined` /
`null` / `NaN`, and, off the Latin-script locales, every Latin word left once paths and folder
names are removed.

| Scenario | Walks |
|---|---|
| Wrong passphrase, then the right one, in the same opening | en, fr, de, ar, ja at 1366 px; ar at 375 px |
| Stop during the first backup, then import again | en |

`report.json` has every figure per walk. **Across all of them: 0 page errors, 0 responses of 400
or more, 0 frames with overlapping text, 0 text outside the dialog, 0 horizontal scroll, no
leftover placeholders, and no English left on the Arabic or Japanese pages.**

## What was wrong (`before/`) and what changed (`after/`)

1. **The failed run's rows under the next import.** The run view was emptied only when the dialog
   opened. Pressing Import again in the same opening drew the new run under "2 failed · Failed"
   and both backups' red errors until the first status tick. Now the view is cleared at the click
   and shows "Starting…" (`after/en-click-moment.png`); a new scan also clears a finished run.
2. **A failed import said its later stages were done.** With every backup failed, stage 3 read
   "done", stage 4 "complete", "✓ Analytics are complete", and "keep the files until this import is
   saved" stayed up for a save that never comes. An ended run now says what it left: "Nothing from
   this import reached your corpus", which files to keep, and "nothing to do" on stages 3 and 4.
   A partly saved run names the backups to import again.
3. **A Stop mid-merge read "Failed" with a database error** ("trigger article_fts_ai already
   exists"). The stop rolled the merge back, which restored the search trigger, and the restore
   step then failed on the trigger it found and hid the stop. Fixed in `src/backup/merge.py`
   (`_fts_insert_suspended`); the backup now reads "Stopped" and the next import succeeds.
4. **The wrong-passphrase error was English in every language.** It is translated ×12 now.
5. **Folder names were squeezed to four lines of ten characters** in the per-backup table. Each
   backup's name now has its own line, with the bar, the counts and the time under it.
6. **"from 0 new sources spanning 0 new languages"** now names only what grew, and French,
   Spanish and Portuguese "imported" agrees with its plural.

The ar, de, fr and ja walks in `after/` ran before items 1's click-moment change, 3 and the
per-backup row's error cell; `en2` and `stop-en2` ran with everything.

## Not changed, for a decision

- The finished summary states the re-index backlog twice ("Indexing continues…: 97 000" and
  "Articles awaiting indexing: 97 000"), frozen at the end of the run, while the live stage-4 row
  and the analytics line above it keep counting down: four numbers for one fact.
- Stage 1 after a Stop reads "1 failed · Stopped": the server counts the cancelled backup as failed.
- "database records, all types: 194 000" is plumbing beside the article counts.

**Decided 2026-09-29 (`R68`, «6=a» in the project chat):** all three change — the frozen «awaiting indexing»
lines go (the live counters stay), a stopped backup reads «stopped» rather than «failed», and «database records,
all types» moves into hover text, still labelled. Built by the claim workspace's thread (0.5 row K), not here.
