# Import-lifecycle click-through — 2026-09-16 (state D only)

**What this is, and what it is not.** A Chromium click-through of the import lifecycle
(`S04-02`) driven on a **real import**: a 24-article, 1.6 MB volume backup restored through
the actual dialog on a fresh instance. It is **state D only** — the four-state walk
(virgin / empty / populated / import) re-litigates surfaces this slice does not touch, and
booting three of its four states would have filled the record with `blocked` rows that read
as regressions. It is also a **plaintext** run: the `at_rest` rows in
[`report.json`](import-lifecycle-clickthrough-2026-09-16/report.json) say `detected:
plaintext` for both readings, because that is what it was. The per-release encrypted walk
(Q1149) is [`13_ENCRYPTED_CLICKTHROUGH_2026-09-16.md`](13_ENCRYPTED_CLICKTHROUGH_2026-09-16.md)
and is not replaced by this.

Artifacts: [`report.json`](import-lifecycle-clickthrough-2026-09-16/report.json) ·
[`coverage.csv`](import-lifecycle-clickthrough-2026-09-16/coverage.csv) ·
[`findings.csv`](import-lifecycle-clickthrough-2026-09-16/findings.csv). The 9 evidence
screenshots are not committed (the 2026-08-13 / 2026-08-20 / 2026-09-16 precedent); every
claim below is reproduced in text or cited to a file and line, so nothing rests on an image.
The `evidence` column in `findings.csv` therefore names a path that existed only in the run.

## How it was run

```
OO_DATA_DIR=…/state-d-src OO_DB_PLAINTEXT=1 .venv/bin/python scripts/ui_clickthrough_seed.py --mini
#   -> write_volume_backup(…/artifact, '…')      24 articles, 2 volumes + parity, 1.6 MB

OO_DATA_DIR=…/state-d OO_DB_PLAINTEXT=1 OO_NO_SCHEDULER=1 OO_LLM_AUTOSTART=0 \
    OO_AIRPLANE_SOCKET_GUARD=1 .venv/bin/python -m uvicorn src.api.main:app \
    --host 127.0.0.1 --port 8003

OO_UIWALK_IMPORT_ARTIFACT=…/artifact OO_UIWALK_IMPORT_PASS='…' \
    .venv/bin/python …/run_state_d.py     # calls investigate_state_d_import directly
```

21 coverage rows, all `verified`; 2 POSITIVE findings, no P0/P1/P2.

## What was verified, on the run that had just happened

| axis | what the browser showed |
|---|---|
| `four-stage-rows` | `['verify_stage', 'merge_swap', 'search_index', 'reindex']` — by `data-row-key`, in order |
| `three-statements` | files removable · safe to close · additive — all three rendered |
| `stage-four-task-manager-link` | stage 4's row carries `openTaskManager()`; it publishes no count of its own |
| `checkpoint-sentence` | "Verified and written to your corpus once every **3** backups — nothing is durable until a save…" (Q216 ⛔ = a) |
| `fresh-page-on-reopen` | after close + reopen: `#ux-imp-summary` **empty**, `#ux-imp-last` = one line (R1, Q201 = a) |
| `last-import-line-links-the-report` | `/api/backup/import-reports/restore-20260916T142753Z-1.json?format=md` |
| `history-in-settings` | `September 16, 2026 at 02:27 PM · restore · 24 articles · open report` (Q222 = b) |
| `locale-fr/ar/zh/en` | each of the four surfaces re-read separately; `dir=rtl` in `ar` |

## The defect this run found, and the one that nearly hid it

The first run reported every locale `verified` while the **checkpoint sentence was still
English in fr, ar AND zh**. Two separate faults, and the second is the more instructive:

1. **The app fault** — the recorded frozen-locale bug class, a third time. The i18n DOM
   walker re-translates a text node whose content is still an exact key; an already
   interpolated `OOI18N.tf()` string ("once every 3 backups") is no longer a key and stays
   in whatever locale first rendered it. Every surface this slice adds is built that way,
   and the poll chain that would repaint them **stops at a terminal state** — so after a
   finished import nothing repaints them at all. A durability caveat was reaching an
   Arabic operator in English. Fixed by an `oo:langchange` listener that re-renders the
   dialog's interpolated surfaces from the **same facts** (the last status, the cached
   re-index read) — never a re-fetch: a language switch is a render, not a tick. Guarded
   by `tests/test_import_lifecycle_ui.py::test_a_language_switch_re_renders_the_interpolated_import_surfaces`,
   mutation-checked three ways.
2. **The check's own fault** — the sweep compared the **concatenation** of the quiet line
   and the checkpoint sentence, which changed in every locale because the quiet line
   translated. One translated half masked an untranslated half, and the row said
   `verified`. It now reads each of the four surfaces separately and names which ones are
   still in the previous locale. This is the same shape as a non-unique mutation needle: a
   check whose subject is broader than its claim can pass for the wrong reason.

## Not measurable here

A **real restore on the maintainer's corpus** (§5 operator steps 1, 2 and 4): a queue of at
least four real backups so the K = 3 group is visible across items, a kill between stages 3
and 4 followed by a boot, and the maintainer's own click-through. This fixture is 24
articles and 1.6 MB; every timing it produces is sub-second and cannot stand in for one.
