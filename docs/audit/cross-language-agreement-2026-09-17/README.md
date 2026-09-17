# S1 acceptance — every analysis tab agrees with the Articles list on one concept

`RELEASE_0.4_GATE.md` row N closes on *"every analysis tab agrees with the Articles list
on the same concept"* being **demonstrated**, with the numbers in the PR. This directory
is the demonstration: a probe, its raw output, and what the two of them do and do not
settle.

## What the probe does

`agreement_probe.py` seeds a synthetic seven-article corpus through the **real**
`index_article` (never by inserting rows), rebuilds the FTS index, and then asks the same
concept of the Articles path and of each analysis tab, twice per term — once with
expansion on, once with the reader's *"only the words I typed"* toggle.

The corpus: 2 English `climate`, 2 French `climat`, 1 German `Klima`, 1 Spanish `clima`,
and 1 article about football that must never match.

## The measurement (`agreement_output.txt`, reproduced verbatim)

| term · ui_lang · expand | Articles ids | Articles total | Trend articles | Keywords | Context | Associations |
|---|---|---|---|---|---|---|
| `climate` · en · **on**  | 6 | 6 | 6 | 6 | 6 | 6 |
| `climate` · en · **off** | 2 | 2 | 2 | 2 | 2 | 2 |
| `climat`  · fr · **on**  | 6 | 6 | 6 | 6 | 6 | 6 |
| `climat`  · fr · **off** | 2 | 2 | 2 | 2 | 2 | 2 |

Four things this settles.

1. **The tabs agree with the list**, on every row, in both states.
2. **The toggle is a real refusal**: 6 → 2, and the 2 are exactly the articles carrying
   the typed spelling.
3. **A French reader typing `climat` reaches the same six articles** an English reader
   typing `climate` does — which is the ruling (R10) in one line.
4. **The total is the count of the search that ran.** Before this slice `search_total`
   accepted an expansion hook and dropped it, so that column read `3` beside `7` ids on a
   smaller fixture; it is now the same number on both sides by construction.

## What it does NOT settle, stated

* **Scale.** Seven articles. The ring-size extremes, the timing of the uncapped
  `search_total` on a broad term, and the re-index are the operator's run on the real
  corpus — `not-measurable-here`.
* **The browser.** This slice is backend-only; no control changed on screen, so there is
  nothing to click through yet. The toggles, the chip and the group-by control are the
  next slice's, and Q1128's bar is Chromium **plus** the maintainer's own pass.
* **`by_language` overlaps.** The run reports six languages for four stored keywords,
  because the ring files `clima` under `es`, `it` and `pt` at once. That is the ring's own
  statement, not a defect, and it is why the per-language figures carry a caveat saying
  they do not add up to the distinct total.

## Reproducing it

```
OO_DATA_DIR=$(mktemp -d) .venv/bin/python docs/audit/cross-language-agreement-2026-09-17/agreement_probe.py
```

The probe sets its own `OO_DATA_DIR`, `OO_DB_PLAINTEXT=1` and `OO_NO_SCHEDULER=1`, so it
never touches a real corpus and starts no scheduler.
