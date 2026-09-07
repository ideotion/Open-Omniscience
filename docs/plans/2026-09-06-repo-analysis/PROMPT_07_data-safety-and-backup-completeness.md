# Prompt 07 — Data safety: backup completeness, restore honesty, the data-location chooser

> **Scope:** `src/backup/`, `src/api/backup_v2.py`, the restore path, first-launch data location.
> **Gated on:** C1 ⛔ (legacy single-file restore removal), C6, C7.
> **Sequencing:** independent, but **never concurrent with prompt 09** (both touch the merge and the write
> path). Every slice here is data-safety-critical: the full skeptic matrix applies, negative-space lens
> mandatory.

## 0. Working mode

Read `_WORKING_MODE.md`. Then the CLAUDE.md non-negotiables on backup, the
**BACKUP/RESTORE BAR = PLAIN-FOLDER-COPY PARITY** ruling, and the S6 closeout item (1). Then
`docs/design/STORAGE_5TB_PLAN.md` §"what the backup engine does today".

The standing bar governs every decision here: an app-stopped filesystem copy of the data folder is a
first-class endorsed backup at every scale, and the in-app path must never be **more complicated, slower per
byte, or riskier** than that. Its justification is what it adds — signed-manifest verification, parity
recovery, additive merge, selective members, running attended — never that it is the only way.

## 1. Slices

### S1 — S6.2: file members inside the signed volume artifact

The top parked item from the 2026-07-12 S6 closeout, and the reason both the wiki-dump-inclusion ruling and
the models-in-backup ruling have sat unbuilt: one portable artifact should carry the wiki dumps, the OSM
regions and the model blobs, and today only the separate folder backup does.

There is a proven pattern to reuse rather than invent: `folder_backup.collect_items` and
`restore_folder_backup` already do checksum dedup, never-overwrite, and skip-non-`done`. What is new is a
`file_members` block in the manifest and its guards — and the guard list is not optional. The 2026-07-10
lesson names exactly how this class fails: enumerate **every** manifest field that becomes a filesystem path
(not only the ones literally called `name`), run them all through the one traversal guard, on **both** the
verify and the restore paths. A self-signed hostile backup turning a member name into an arbitrary-file
delete of the live corpus is the failure mode that already happened once.

Skip non-`done` downloads. State the residual cost honestly (two revisions of one HF repo sharing a blob are
stored once per revision).

### S2 — ⛔ C1: the legacy single-file restore

Ruling 11 (2026-07-20) marked it for removal and FUTURE_DEVELOPMENTS records it. The blocker flagged when
the Settings restructure removed the panel is still live: `restore_legacy_path` **may be load-bearing for
the unified Import**. So the removal is: prove the unified Import path does not reach it (drive the real
import, not a double), then remove backend and frontend together, then confirm `read_artifact`'s
forever-acceptance of old formats is untouched — that is the promise that no old backup is ever stranded and
it must survive the removal.

If the proof does not come out clean, say so and stop. A half-removed restore path is worse than a legacy one.

### S3 — PRH-30: `RestoreAborted` labels the wrong actor

The handler labels the outcome `cancelled` and journals **"stopped-by-operator"** when the operator cancelled
nothing (the quiesce barrier does the same). It is recorded in a source comment and nowhere else. Re-labelling
belongs to a slice that changes both — this one. A restore that refused for a real reason must say the real
reason; blaming the operator sends them looking for a job they did not start.

### S4 — C7: the data-location chooser at first launch

Default to the app data folder, or "choose a folder" in which an **"OOS data"** subfolder is created. Decided
at first launch **after** language and legal acceptance, **before** the passphrase. Reuse the shipped A11
`OO_DATA_DIR` / `oo.env` persistence seam and the honest writable / free-disk / tmpfs preflight — a
disposable-VM tmpfs is exactly the case the preflight exists for, and the honest message names it rather than
telling anyone to change how they work.

### S5 — The 0.4 row 4 tooling

Row 4 is the maintainer's run, but its **closing clause** is code: after a committed full import, spot-check
that a previously-DISQUALIFIED source is still disqualified. A pass counting only `qualified` rows cannot see
the inversion — and that inversion is precisely the defect the 2026-07-24 merge fix repaired (a dropped
qualification stamp arriving as `unqualified`, which is byte-identical to never-judged, laundering known-bad
sources back into the trial queue with the backoff ladder reset).

Build the check as a diagnostic that names the sources it verified, so the row closes on evidence.

### S6 — Small and verified

- **PRH-08:** `r.samples` for sources is dead — the sample query runs after the INSERT so its `NOT EXISTS`
  is never true. Either make it real or delete it; an always-empty list in a report is a fabricated absence.
- **DAT-09:** decide and record whether the run journals under `run_logs` ride a backup. They are per-machine
  and currently do not; the answer is probably no, but "probably no, undecided" is not a state a data-safety
  boundary should be left in.
- **C6:** the DuckDB httpfs binaries. The registry pins ship deliberately blank and
  `extensions.duckdb.org` is egress-blocked here. Recommended: park it explicitly with the reason, rather
  than leaving it reading as pending work.

## 2. Verification contract

Every slice: reproduce the failure first where one exists; adversarial passes with a data-loss lens and a
negative-space lens; mutation-check each new guard by name. For S1 specifically, drive a **hostile** manifest
(traversal in every path-bearing field, on both verify and restore) and assert refusal, not tolerance.

## 3. Scope fence

Do not build a post-swap undo — it is unsound and the analysis for why is recorded (dangling ids after a
`merged_rows` delete, hash-joined pre-existing articles, unrepaired counters, no `foreign_keys` pragma on the
merge connection, and `_SNAPSHOT_KEEP=3` meaning item 1's snapshot is gone by item 4). Do not touch the merge
windowing (prompt 09). Do not remove `read_artifact`'s legacy acceptance.
