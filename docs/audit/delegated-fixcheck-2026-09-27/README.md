# The delegated 0.4 fix-check walk — 2026-09-27 (rows H, I, J, L, M, N, O, P, S, T, U, and R)

The re-walk (`../delegated-rewalk-2026-09-27/`) confirmed 119 items on top of the first walk's
115 defects. The maintainer ruled that all 119 are fixed before the tag, **and that this walk
checks only those fixes and each row's own steps, so the loop ends** (`R37`). The fixes landed in
PR #1191, batches B20 to B30. This folder is that walk.

**Verdict: every row's click-through clause passes.** Ten rows passed as walked. Rows N and O each
had one P3 item left, both fixed afterwards and checked again in Chromium (below). Of the 119
items, 117 were fixed on the walked build and the last 2 on `38965c0e`. No walkable step fails
on any row. The steps that could not be walked here need the maintainer's real install, a
removable drive, their own word, or going online; they are listed below, because they are the
runs the gate still owes.

## How it was run

Exactly as the re-walk (see its README), with the scope narrowed by `R37`:

- **Build:** a read-only worktree at `9eb10528` (PR #1191 after batch B30 and its ledger commit).
- **Scope:** each walker re-ran its row's steps as the re-walk recorded them
  (`../delegated-rewalk-2026-09-27/rows/<ROW>.json`, `walk.steps`; for row R, `walk.checks` and
  `walk.surfaces`) and reproduced each of its row's items from `../delegated-rewalk-2026-09-27/defects.csv`.
  It did **not** hunt for new defects. Anything else it happened to see is listed as incidental
  (`incidental.csv`), which neither fails a row nor was re-checked.
- **Conditions:** every data folder encrypted at rest, locked at boot and unlocked through the real
  `#pw` / `#btn-unlock` form; airplane mode throughout; every consent popup opened, read and
  cancelled; «Go online» never pressed. No walker reported a non-loopback request, and the seven
  that counted them (H, I, L, R, S, T, U) measured none. The HTTP errors recorded are the designed
  ones: wrong-passphrase attempts, refused merges, a report read before any fold, and the walkers'
  own probes.
- **Process:** one workflow of 14 agents. One walker per row (12), then an independent re-checker
  for each row with a failure (2: rows N and O), which reproduced it on its own fresh instance
  and gave the root cause.
- **Kept here:** each row's walk and re-check (`rows/<ROW>.json`), the incidental notes
  (`incidental.csv`, ids `<ROW>-i<n>`), and the after-fix check of N-4 and O-5 (`after-fix.json`).
  The Playwright scripts and screenshots stayed in the session's scratch folders.

## The rows

| Row | Steps | Re-walk items | Click-through clause |
|---|---|---|---|
| H | 8 pass · 2 not measurable | 5 fixed | **Passes.** |
| I | 13 pass · 1 not measurable | 8 fixed | **Passes.** |
| J | 7 pass · 2 not measurable | 4 fixed (J-1: the minimum fix) | **Passes.** |
| L | 14 pass | 10 fixed | **Passes.** |
| M | 9 pass · 2 not measurable | 16 fixed | **Passes.** |
| N | 11 pass · 2 not measurable | 7 fixed · N-4 fixed after the walk | **Passes** since `38965c0e`. |
| O | 14 pass · 4 not measurable | 5 fixed · O-5 fixed after the walk | **Passes** since `38965c0e`. |
| P | 11 pass · 1 not measurable | 6 fixed | **Passes.** |
| S | 11 pass | 12 fixed | **Passes.** |
| T | 9 pass · 2 not measurable | 9 fixed | **Passes.** |
| U | 13 pass · 2 not measurable | 11 fixed | **Passes.** |
| R | 31 checks pass · 1 not measurable | 24 fixed (R-6, R-14, R-24 by the gate correction) | **Passes.** |

## The two items fixed after the walk

- **N-4** (row N, P3). The analysis-window half was fixed on the walked build. The Settings →
  Advanced → Diagnostics half was not: the three job lines (re-index, keyword fold, search
  re-index) kept the language they were drawn in, because their watch loop ends once the job is
  done. Each line now keeps the reading it last drew, and the one `oo:langchange` listener
  redraws it with no fetch (`src/static/app-diagnostics.js`, `repaintDiagnosticsJobsFromCache`).
  **Checked on `38965c0e`** with the re-checker's own script: the search re-index line follows
  live switches en → fr, fr → ar, ar → zh and zh → en, with no page error and no external request.
- **O-5** (row O, P3). Storage and Living sources were fixed on the walked build. The `/tasks`
  page was not: its failure line built `t("Failed:") + " " + error`, so zh read
  «失败： HTTP 503 from the mirror». It now uses the keyed `{prefix}: {text}` frame the in-app
  renderer uses (`src/static/taskmanager.html`, `jobWhy`). **Checked on `38965c0e`**: «失败：HTTP 503
  from the mirror» (U+FF1A then `H`) after a live switch, after a reload and on a direct load of
  `/tasks`, and the Storage and Maps lines still read with no space after a full-width mark.

Both are pinned by tests: `tests/fixcheck_n4_node_test.js` and `tests/test_fixcheck_walk.py` for
N-4, and a zh case in `tests/job_why_node_test.js` for O-5 (each fails on the old code).

## What a sandbox could not walk (the gate's operator runs)

These are **not failures**. Each needs something this environment does not have, and each maps to
a run the gate already names as the maintainer's:

- **H9**: the maintainer's word on the 15 lane names and 3 headings. **H10**: going online.
- **I1**: the real install and its import history.
- **J7, J8**: the removable drive and the operator's own listing (their sandbox equivalents pass).
- **M7**: a real corpus with a rising Lead (the synthetic one has none). **M10**: going online to Wikidata.
- **N12, N13**: the real install (its 2M+ article corpus, and its pre-S8 index).
- **O11** (the online half), **O13, O14, O15**: the real encrypted install, its upgrade, its stored
  scheduler choices, and a copy of its data folder on an encrypted drive.
- **P5**: everything after consent needs Wikimedia.
- **T9**: a collection pass needs egress. **T10**: not observed on this corpus.
- **U4, U8**: the real install and passphrase, and the real mailbox.
- **R**, Insights → Map (cities): only its honest empty state, since placing a city needs a source city.

## The incidental notes

32 notes, one line each with a file lead, in `incidental.csv`. None was re-checked, and none fails
a row. The recurring ones:

- **The consent popup's custody read.** Rows H, M, O, S and R each saw «Chain of custody» listed
  once under «Could not read whether these are on» on a first open, then read correctly. It is the
  2 s read budget from the M-14 fix, and the slow custody read was already a recorded lead.
- **Raw tokens and hard-coded joins** in otherwise translated lines: the import history's `restore`
  kind (I-i1), the Lead's `large-removal` flag (L-i1), the preview's `news` source type (S-i3), the
  chart hover's `: ` (N-i1), the agenda's lowercase `all` (U-i1), the zh qualify refusal's ASCII
  parentheses (S-i1).
- **Surfaces that keep their first language after a live switch:** the retired-mode notice (O-i2)
  and the newsletter import result (U-i2, recorded as by design by the earlier walks).
- **O-i1 is the one with a behavioural effect:** a reload in a non-English UI can retire the
  offline coach with no user action, because the boot-time `oo:langchange` repaints the network
  state before the first read. Nothing goes online; the coach just never shows again.
- **Layout:** the fr discovery checkbox at 375 px (H-i1, exposed by the H-5 width fix), the fr
  Trends overlap and the ar tick clipping (N-i3, N-i4), the Home tag select at 375 px (T-i1), and
  the selected ring chip's white-on-pale text (R-i1).
