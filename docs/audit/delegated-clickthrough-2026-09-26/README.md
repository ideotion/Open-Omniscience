# The delegated 0.4 click-through — 2026-09-26 (rows H, I, J, L, M, N, O, P, S, T, U)

The maintainer delegated the click-through of eleven `RELEASE_0.4_GATE.md` rows to Claude
(«I want to delegate the click-through to YOU or a claude code session, or an entire
workflow», 2026-09-26; recorded as `R35` in `docs/ledger/RULINGS_INDEX.md`). This folder is
that walk. Under Q1128 = a, as amended by R35, it is the record that closes, or fails, each
row's click-through clause. It does not replace any row's **operator** steps: the real
restore, the real-corpus runs, the removable drive and the upgrade of the maintainer's own
encrypted install stay operator work.

**Verdict: two rows pass, nine fail.** J and O pass on everything a sandbox can reach. H, I,
L, M, N, P, S, T and U each fail at least one step on a defect an independent re-check
reproduced. Across the eleven rows the re-check confirmed **115 defects: 5 P1, 38 P2, 72
P3**. Two more were reported and judged by design. A few appear on several rows (the hover
bubble under modal dialogs, the first-launch data-location screen, the Home strip's labels);
they are listed once per row that saw them.

## How it was run

- **Build:** `main` at `462145c`, untouched (every walker read the tree and wrote only to
  its own scratch folder).
- **App:** launched with the `open-omniscience` console script, never `python -m
  src.api.main`. Launched with `-m`, the module imports twice, so unlock fails with a
  duplicated Prometheus counter. That defect is known and was recorded on 2026-09-17 (gate
  amendment log, row N).
- **At rest:** every row ran on an ENCRYPTED store. It was seeded with `OO_DB_PASSPHRASE`
  and booted with neither `OO_DB_PASSPHRASE` nor `OO_DB_PLAINTEXT`, so the app started
  locked, and each walk entered through the real `#pw` / `#btn-unlock` form. Row P also made
  a fresh folder encrypted through the real first-launch screens.
- **Data:** `scripts/ui_clickthrough_seed.py` (the `--mini` 24-article seed or the default
  ~450-article multilingual one), plus this row's earlier sandbox seed where the row needed
  lane, law, map or source state (copied, never edited).
- **Network:** the app stayed in airplane mode throughout. Every consent popup was opened,
  read and screenshotted, then cancelled. «Go online» was never pressed, so everything after
  consent reads `not-measurable-here`.
- **Browser:** Chromium (Playwright), driven through the real sidebar, subtabs, buttons and
  top-bar language switcher. The main pass ran at 1440×950 in en, then fr, ar (RTL) and zh,
  plus one 375 px pass in en. Every page error, console error, response ≥ 400 and visible
  `undefined` / `NaN` / `null` / `[object Object]` was recorded.
- **Process** (44 agents, one workflow):
  1. Draft each row's steps from the gate row, its brief and the earlier sandbox walks.
  2. An adversarial checker corrected every label, path and pass criterion against `main`.
  3. One walker per row drove the steps in Chromium.
  4. An independent re-checker reproduced each reported defect on its own fresh instance,
     read the code and gave a verdict: confirmed, harness artifact, by design, or could not
     reproduce.

## The rows

| Row | Steps (pass · fail · other) | Confirmed defects | Click-through clause |
|---|---|---|---|
| H | 7 · 1 · 2 | P1 1 · P3 7 | **Fails.** The per-lane host bubble, the one thing Q1002 adds to the popup, is drawn under the modal «Go online?» dialog: 0 changed pixels in en/fr/zh, a clipped fragment in ar. Everything else passes, including the 15 lanes with their n= counts and a SECURITY.md table that matches them |
| I | 5 · 8 · 1 | P2 9 · P3 6 | **Fails.** Q203: «✓ Analytics are complete» shows at the START of an import, and «✓ Safe to close» shows before the run is recorded finished. Q204/Q205: stage 4 freezes, then reads «could not be read» on every reopen. R1/Q201: reopening re-renders the previous run instead of a fresh page. The four stages, K = 3, the single poll chain, reattach and the boot auto-resume all work |
| J | 6 · 0 · 2 | P2 2 · P3 7 | **Passes** for everything the sandbox reaches. Dated folders in local time, `_2`/`_3` on collision, «Verified», `BACKUP_SUMMARY.md` identical to `volumes.json`, in en/fr/ar/zh and at 375 px. Left open: the removable drive, and whether this sandbox counts as the reference VM. Two P2s to fix (below) |
| L | 5 · 9 · 0 | P2 4 · P3 13 | **Fails.** 28 real ISO territories (Vatican City among them) are missing from the alpha-3 table. Insights → Map «By country», Minerals supply, the Sources filter label, the law-change card and the Groups refusal still print two-letter codes |
| M | 2 · 7 · 2 | P2 7 · P3 7 | **Fails.** Most keyword surfaces still draw bare foreign words without the tier tag, which is the gate's own closing criterion. After a fold, the old inflected term resolves to an emptied keyword. The Analysis-window tag has no hover and 1.14:1 contrast. The «several senses» picker does nothing. The fold job has no task-manager controls. The fold job and the consent gate pass |
| N | 8 · 3 · 2 | P1 1 · P2 3 · P3 10 | **Fails.** P1: a new analysis tab can paint another tab's results under its own label. A sense pin leaks between tabs. A hidden chart series cannot be clicked back. The toggles, chips, stacked chart, concept map and the Arabic/Chinese re-index pass (预算 and 诊所 from 0 to 28 hits, voweled Arabic from 0 to 55) |
| O | 14 · 0 · 4 | P1 1 · P2 1 · P3 2 | **Passes** for everything the sandbox reaches: Storage, Living sources (all three subtabs, the diff, the deep link), the transport lines in both fetch modes, the task-manager cause lines, the retired-mode notice. The P1 is the modal-hover defect again, found by the re-check on the export dialog. Left open: O13–O15 on the maintainer's real encrypted install |
| P | 7 · 4 · 1 | P1 1 · P2 4 · P3 5 | **Fails.** The modal-hover P1 hides the consent popup's host and transport lines. The W hover goes stale after a click. The reader's external-link confirmation is English in every language (a consent string). «use ORES scores» is pre-ticked although Q717 rules ORES opt-in |
| S | 8 · 3 · 0 | P2 4 · P3 4 | **Fails.** «Build a merged file» never shows the server's refusal (a TypeError leaves «Merging…» stuck), and Export's YAML is not accepted by Merge. A live language switch leaves the Quality gates panel in the old language. After Undo, the «Collecting now» headline stays stale |
| T | 6 · 3 · 2 | P1 1 · P2 3 · P3 3 | **Fails.** P1: the task-manager page always shows ONLINE. It reads `online` from `/api/scheduler/activity`, which never carries it, so in airplane mode the plane never fills. Its health pill always reads «degraded». The coach buttons at equal weight (Q1125), the speed gauge (Q1012) and the loopback limit (Q1148) pass |
| U | 8 · 5 · 2 | P2 1 · P3 8 | **Fails.** On a fresh install the «Where should your corpus live?» screen never appears: `/api/system/data-location` answers 503 while the app is locked, which on a fresh install is always. All 12 languages, the RTL re-render and Undo pass |

## The five P1s (three causes)

1. **Every `#oo-tip` hover inside a modal dialog is drawn behind the dialog** (rows H, O and
   P, found independently three times). `#oo-tip` is appended to `document.body`
   (`src/static/app-boot.js:259-267`), but dialogs opened with `showModal()` live in the
   browser's top layer, which no `z-index` reaches. The consent popup's per-lane hosts and
   transport sentence (Q1002, Q1014), and every other hover in a modal dialog, are
   unreadable. The informed-consent non-negotiable is broken exactly where it matters most.
2. **A new analysis tab can paint another tab's results under its own label** (row N).
   On a deep-linked open (`?analyze=` / `?corpus=`), boot restores the saved strip and loads
   its active tab, then spawns the new tab and loads that too
   (`src/static/app-boot.js:448-474`). `loadAnalysis` carries no run token, so whichever
   run finishes last writes the shared list, total and facets
   (`src/static/app-analysis.js:1961`).
3. **The task-manager page always reads online** (row T). `taskmanager.html:522-524` reads
   `act.online`, which `/api/scheduler/activity` never sends, so an absent field becomes
   «online». The operator in airplane mode is told the opposite of the truth, and the
   page's own go-offline click reverts at once.

The P2s and P3s, each with its repro, expected and actual behaviour, root cause
(`file:line`) and smallest fix, are in [`defects.csv`](defects.csv).

## Not measurable here

Everything after «Go online» (Wikipedia stream, Wikidata rings, World Bank load, law
adapters, collection passes and the per-process budget panel they feed) needs egress this
sandbox does not have. Also out of reach: the maintainer's real encrypted install (I1, O13–O15,
N12, U4, U8), a removable drive (J7, J8), corpus-scale timings, a local Ollama, and
`tests/test_security_endpoint_enumeration.py`, which needs pytest in the walk's venv (its two
node suites passed). Each row's list is in `rows/<ROW>.json` under `walk.not_measurable`.

## Files

- `defects.csv`: one line per re-checked defect (row, severity, verdict, title, steps,
  repro, expected, actual, evidence, root cause, suggested fix).
- `rows/<ROW>.json`: the steps as walked (drafted, then corrected against `main`), the
  walker's per-step results and observations, and the re-checker's verdicts.
- `shots/<ROW>/`: the screenshots each step cites, downscaled to 1200 px and quantized.
- `scripts/<ROW>/` and `scripts/<ROW>-recheck/`: the Playwright walks and seeds, as run.
  They use absolute `/tmp/claude-0/walk/...` paths and the throwaway passphrase
  `walk-pass-2026`.
