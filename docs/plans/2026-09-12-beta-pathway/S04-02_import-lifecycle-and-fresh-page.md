# S04-02 — The import lifecycle: fresh page, four stages, one poll chain, K = 3, one API path · 0.4, `RELEASE_0.4_GATE.md` row I

> **Scope:** the import half of `src/static/app-backup.js` and the `#ux-import` dialog in `index.html`,
> `src/api/backup_v2.py`, `src/backup/import_queue.py`, `src/analytics/reindex_job.py`,
> `src/config/app_settings.py` (`import_checkpoint_k`), the boot block in `src/api/main.py`, the locales, the
> tests. Must NOT: change the merge algorithm (`src/backup/merge.py` beyond wiring), the export half
> (`S04-03`), the backup format (`S04-04`), or `read_artifact`'s legacy acceptance (Q215 ⛔ = a keeps it).
> **Implements:** Q201, Q202, Q203, Q204, Q205, Q206, Q207 (ASSUMPTION), Q214, Q216 ⛔, Q217, Q221, Q222.
> **Gated on:** nothing pending. Q217 waits on a measurement; Q221's lanes on `S04-08` (the hook ships now).
> **Sequencing:** after `S03-01`; never concurrent with `S04-03` on `app-backup.js`; land the API
> consolidation (S5) before `S04-04`'s CI restore fixture is written against it (a suggestion, not a ruling).

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved. The sheet
section is §3 (R1–R5); the `OPEN_QUEUE.md` entries: the 2026-09-15 head entry and the register's C1/C2/C3
lines (`grep -n "C2 = Q216" docs/ledger/OPEN_QUEUE.md`). Data safety: the full skeptic matrix applies.

## 1. The rulings this slice implements — verbatim, by ID

- **Q201** — **(a)** «One quiet line: "Last import · 2026-09-12 10:45 · 12,340 articles · open report",
  linking the persisted import report (`GET /api/backup/import-reports`, unused today).»
- **Q202** — **(a)** «Four stages, shown as four rows with their own progress.»
- **Q203** — **(a)** «Files: after the swap. Close/update: after the swap (a durable cursor resumes stages 3–4
  on the next boot). Analytics complete: after stage 4.»
- **Q204** — **(a)** «Stage 4 lives inside the import experience as its own row (progress from
  `GET …/reindex-backlog/resume/status`) with a link to the task manager.»
- **Q205** — **(a)** «The existing durable cursor (`reindex-resume`) auto-resumes on boot; the UI shows
  "resuming re-index (N left)".»
- **Q206** — **(a)** «One poll chain, one bar owner, rows patched in place (keyed by item id), the two
  `_uxImQueuePoll` chains reduced to one.»
- **Q207** — **(a)** «Remove it.» [ASSUMPTION — blank, the sheet's default; the JSON: "ASSUMPTION (blank,
  default a)"; supported by R2 "the import 'details' adds no value and goes"]
- **Q214** — **(a)** «`import-queue/*` is the one path: delete `v2/restore/*` after moving anything only it
  does into the queue; wire `reindex-*` (Q204).»
- **Q216** ⛔ — **(a)** «K = 3.»
- **Q217** — **(a)** «Build only if the first real `verify_copy` timing shows "prepare" still dominating.»
- **Q221** — **(a)** «The same import dialog and lifecycle; each lane is a row with the same four stages.»
  [placement: the hook now; lanes from 0.4/0.5]
- **Q222** — **(b)** «Settings → Backup.»

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §3 context (VERIFIED, `src/static/app-backup.js`): `openUnifiedImport()` (`:494–508`) re-renders the
  previous run through `_uxShowLastCompletedSummary()` (`:521–554`); two bar owners at two cadences (1200 ms
  verify poll, 1000 ms queue renderer), rows rebuilt by `innerHTML` every tick; "Details" duplicates the
  queue rows except the path; the re-index is a separate deferred job (`ReindexJobManager`, four endpoints
  in `src/api/backup_v2.py:770–905`) with zero frontend callers; "staged" ≠ "done" at
  `import_queue.py:232–241`.
- grep-verified in this brief (`grep -n` on `app-backup.js`): `openUnifiedImport` `:494`,
  `_uxShowLastCompletedSummary` `:521`, `_uxImQueuePoll` `:734` (timers `:740` 3000 ms, `:742` 1000 ms), the
  verify `tick` `:285`/`:304` (1200 ms), `_uxImDetails` `:916` into `#ux-imp-details-body` (`:876`);
  `grep -rn "reindex-backlog" src/static/` → none.
- grep-verified: `src/api/backup_v2.py` (prefix `/api/backup`, `:43`): `/import-reports` `:68`,
  `/import-reports/{filename}` `:78`, `/v2/restore/preview` `:187`, `/v2/restore/commit` `:256`,
  `/legacy/restore` `:298`, `DELETE /v2/restore/preview/{token}` `:379`, `/v2/batches` `:388`,
  `/import-queue/start|status|stop|clear` `:721–759`, `/reindex-backlog` `:770`, `…/resume` `:879`,
  `…/resume/status` `:896`, `…/resume/cancel` `:902`.
- grep-verified: dialog ids in `index.html` — `ux-import`, `ux-imp-src|checklist|pass|pass-row|run|stop|
  progress|bar|bg|status|summary|queue|queue-note|queue-rows|details|details-body`; the checkboxes
  `ux-i-corpus|legacy|blobs|eml` in `app-backup.js`. Settings → "Data & backup" is `#set-data`
  (`index.html:1479`, `:1827`).
- grep-verified: `src/analytics/reindex_job.py` — `_STATE_FILE = "reindex_job.json"` (`:42`);
  `_load_persisted` (`:124–140`) restores an interrupted run as PAUSED, never resumes it; `resume()` `:430`;
  the boot block `src/api/main.py:124–142` only LOGS the backlog. The cursor exists; the auto-resume of Q205
  does not.
- grep-verified: `src/backup/import_queue.py:59–110` — `CHECKPOINT_K_MAX = 24`, `CHECKPOINT_K_DEFAULT = 1`,
  `import_checkpoint_k()` reads `OO_IMPORT_CHECKPOINT_K` then `AppSettings.import_checkpoint_k`
  (`src/config/app_settings.py:133`, default 1); `KINDS = ("corpus", "legacy", "blobs", "newsletters")` `:56`.
- grep-verified: the measure the gate row cites — `docs/ledger/LESSONS.md:7146`: "the discriminator is
  `SELECT COUNT(*) FROM merge_batches` in the carried file: two after two held items, one after a
  re-snapshot". The "prepare" timings of Q217: `merge.py:568–629` (`prepare_staged:validate` `:613`,
  `prepare_staged:upgrade` `:629`; `:532` "Hoisted out of `prepare_staged_corpus` when `verify_copy`…"),
  `src/backup/timing.py:86`.
- grep-verified: `src/backup/import_reports.py` — `persist_import_report` `:43` (writes
  `data_dir()/import_reports/<kind>-<UTC ts>-<id>.json`), `render_import_report_markdown` `:73`,
  `list_import_reports` `:332`. Ten test files pin `v2/restore` or `legacy/restore`
  (`grep -rln "v2/restore\|legacy/restore" tests/` — the list goes in the PR).

## 3. Slices — what to build, in order

### S1 — One poll chain, one bar owner, rows patched in place; "Details" gone (Q206, Q207, R2)
- **What:** fold the 1200 ms verify `tick` and `_uxImQueuePoll` into ONE chain owning the bar; rows keyed by
  item id and patched, never rebuilt; `_uxImDetails` and `#ux-imp-details(-body)` removed (the path it added
  moves into the persisted report).
- **Why (ruling):** Q206 = a; Q207 = a (ASSUMPTION — blank, the sheet's default); R2.
- **Acceptance:** a source test through `tests/js_source_helper.py` (the ad-hoc slicer budget is 232 with
  zero slack) that one chain remains and `_uxImDetails` is gone; the Chromium record shows no rebuild of an
  unchanged row (count DOM mutations).
- **May not decide:** whether Q207 stands — name the assumption in the PR so it can be reversed.

### S2 — A fresh page and the one quiet line (Q201, R1)
- **What:** `openUnifiedImport` stops calling `_uxShowLastCompletedSummary`; one line reads the newest entry
  of `/import-reports` and links `/import-reports/{filename}`; strings ×12; the ledger records the 2026-07-16
  behaviour as SUPERSEDED.
- **Why (ruling):** Q201 = a; R1. **Acceptance:** the click-through of a reopen: the line, nothing else.

### S3 — Four rows with their own progress; the three statements at their stages (Q202, Q203, R3)
- **What:** the queue status exposes the stage per item (1 verify + stage · 2 merge + swap · 3 search-index
  merge · 4 re-index) mapped from today's phases; a stage without a measured progress renders indeterminate,
  never a fabricated percentage; the statements appear when ruled — files removable after the swap,
  close/update safe after the swap, analytics complete after stage 4 — visible ×12, caveats included.
- **Why (ruling):** Q202 = a; Q203 = a; R3. **Acceptance:** the four rows and three statements on record.

### S4 — Stage 4 inside the experience; auto-resume on boot (Q204, Q205)
- **What:** the stage-4 row reads `/reindex-backlog/resume/status` (the first frontend caller) with a link to
  the task manager; boot resumes the persisted cursor instead of parking it as PAUSED, off the startup path
  (a report must never block boot); the UI shows "resuming re-index (N left)" ×12.
- **Why (ruling):** Q204 = a; Q205 = a; Q203's "a durable cursor resumes stages 3–4 on the next boot".
- **Acceptance:** the gate's test (2): kill between stages 3 and 4, boot, the resume proceeds — a subprocess
  test (never switch branches while it runs).

### S5 — One API path (Q214)
- **What:** delete the three `/v2/restore/*` routes after moving anything only they do into the queue (listed
  in the PR); wire `reindex-*`; re-anchor the ten test files; a repo test that the routes are gone, anchored
  on the router's own `router.routes` definitions — never `app.routes` (the recorded flakiness lesson).
- **Why (ruling):** Q214 = a. **Acceptance:** the gate's test (3), mutation-checked (re-add one route → red).
- **May not decide:** the fate of `/legacy/restore`, `/v2/batches`, `/v2/volumes/*` (§6).

### S6 — K = 3 (Q216 ⛔ = a)
- **What:** `CHECKPOINT_K_DEFAULT` and `AppSettings.import_checkpoint_k` default to 3; the override paths
  stay; "verified and swapped once per 3 backups — nothing is durable until a swap" visible in the dialog ×12.
- **Why (ruling):** Q216 = a. **Acceptance:** the discriminator as the test — `merge_batches` counts 2 for two
  held items, 1 after a re-snapshot (never a duration comparison).

### S7 — Prefetch only on evidence (Q217)
- **What:** read the `prepare_staged:validate` / `:upgrade` timings from the first real `verify_copy` run on
  the reference corpus (§5); build the prefetch only if "prepare" dominates; otherwise park it with the
  numbers.
- **Why (ruling):** Q217 = a. **Acceptance:** the timing record in the PR, whichever branch it takes.

### S8 — The lane hook and where history lives (Q221, Q222 = b)
- **What:** `KINDS` is the row registry — a future lane is a kind rendering as a row with the same four
  stages; nothing lane-specific is built. The history list lives in Settings → Data & backup (`#set-data`)
  reading `list_import_reports`; no History subtab in the task manager (invariant #20's "REMAINING: History"
  is answered as Settings — record it).
- **Why (ruling):** Q221 = a; Q222 = b. **Acceptance:** the history list in the click-through record.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: `node
--check` on every touched `<script>` block; the three i18n gates for every new string (ratchets read from
`ci.yml`: 470 / 231 today); the whole-tree guard set; the full skeptic matrix with the negative-space lens
mandatory — a killed import never reads "done", a staged item reads "discarded" (`import_queue.py:232–241`),
a stage with no measurement never shows a number; every new guard mutation-checked by name; the Chromium
click-through (Q1128 = a) of Settings → Data & backup → Import (`#ux-import`): the fresh reopen and its line,
the four rows, the three statements, the task-manager link, the boot-resume banner, the history list — en,
fr, ar (RTL); the numstat rule for the ledger files. The real-restore half is an operator step:
`not-measurable-here`.

## 5. Operator steps

1. A real import of a queue of at least four backups on the maintainer's machine (K = 3 makes the group
   visible), watching the rows and the statements. Artifact: the click-through record + the import report.
2. A kill between stages 3 and 4 on that machine, then a boot. Artifact: the report and the task-manager
   screenshot showing the completed stage 4.
3. The `verify_copy` timing read for Q217 (S7). Artifact: the numbers in the PR.
4. The maintainer's click-through of every surface in §4 (Q1128 = a).

## 6. What this slice may not decide

- Q207 is an ASSUMPTION (blank, the sheet's default) — named in the PR body so it can be reversed.
- Q216 ⛔ was answered (a); "another K" is not a session's to pick, and neither is hiding the override.
- The fate of `/legacy/restore`, `/v2/batches` and `/v2/volumes/*`: Q214's label deletes `v2/restore/*` only;
  the legacy single-file restore stays forever (Q215 ⛔ = a, `S04-04`; the `OPEN_QUEUE.md` C1 entry records
  that the queue's `_run_legacy` shares the endpoint's helper on purpose).
- The mapping of today's phases onto the four stages where a phase straddles two.
- Q221's lanes themselves (`S04-08` and later); Q222's subtab name — "Settings → Backup" is today's "Data &
  backup", and a rename is not ruled.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or
  PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
