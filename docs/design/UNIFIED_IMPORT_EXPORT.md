> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — Slice 2 ("Import discovery") is confirmed SHIPPED — `src/backup/import_scan.py:scan_import_folder` + the wired `#ux-import` dialog — this doc was stale in not marking it BUILT. The one remaining disclosed residue (the legacy capped single-file `write_backup_v2` create endpoint and its orphaned frontend handlers, kept deliberately UI-unreachable pending a browser click-through) is confirmed still present, unchanged. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Unified Import + Unified Export/Backup (field remarks 2 / 5 / 6)

> **Status: DESIGN.** A frontend-heavy consolidation that REUSES the shipped backup/import
> backends (no new backend) but cannot be browser-verified in the autonomous sandbox (fork-3).
> The merge MUST not lose a capability (the Desk lesson), so it ships behind an absorption test.
> Build it from this doc in a session that can click through it. Split into 6a (Import) + 6b
> (Export/Backup) PRs.

## The ask (verbatim, remarks 2/5/6)

- ONE Import entry point + ONE Export/Backup entry point. Each opens a **follow-up pop-up** to
  gather that action's options, **ending in a file/folder selection**.
- **Fuse the two newsletter-import paths** (the small-file `.eml` upload + the server-side folder
  job) into the one Import flow.
- A **visually clear progress bar** for every import/export, and — where possible — a **live
  "amount of data imported/exported" readout**.
- It MUST sit on the **NEW OOENC2 streaming-volume backup path** (not the legacy OOENC1 2 GiB
  single-file path) for the encrypted corpus backup.

## What already exists (reuse, do NOT rebuild — from CLAUDE.md shipped log)

| Capability | Backend (reuse) |
| --- | --- |
| Encrypted corpus backup, **streaming volumes + Reed–Solomon parity** | `src/backup/volume_job.py:VolumeBackupManager` + `POST /api/backup/v2/volumes/{start,restore,cancel,status}` (the OOENC2 path — `src/safety/crypto.py` `encrypt_file`/`decrypt_file`, `src/backup/volumes.py`, `src/backup/parity.py`, `src/backup/artifact.py` `write_volume_backup`/`read_volume_backup`) |
| Large-data **folder backup** (wiki dumps + OSM regions + models → a drive), pausable job | `src/backup/folder_backup.py:FolderBackupManager` + `/api/backup/folder/{plan,start,restore,status,pause,resume,cancel}` |
| Legacy single-file encrypted/plaintext backup (oo-backup-2, OOENC1) | `src/backup/artifact.py` `write_backup_v2` + `/api/backup/v2/*` (selective tickboxes incl. exclude-newsletters) |
| Models-only backup (`.oomodels`) | `src/backup/ollama_models.py` + `/api/backup/models/{export,import}` |
| Newsletter `.eml` **small-file upload** | `POST /api/newsletters/import` (async, max 5000 files) |
| Newsletter **server-side folder job** (20 GB+, pausable, persisted cursor) | `src/ingest/import_job.py:NewsletterImportManager` + `/api/newsletters/import-folder/{,status,pause,resume,cancel}` |
| Newsletter **mailbox pull** (IMAP/POP3) | `POST /api/newsletters/mailbox` |
| **Server-side folder picker** | `GET /api/fs/list` + the `ooFolderPicker()` frontend helper |
| Restore (additive merge) | `/api/backup/v2/restore` + the volume/folder restores above |

So this work is **presentation + routing only**: one entry chip each, a dialog that picks the
*kind* + its options, then dispatches to the existing endpoint and shows its existing progress.

## 6a — Unified IMPORT

**One "Import" button** (in Settings → Data & backup, replacing the scattered import controls).
Click → `#import-dialog` (a `<dialog>`), which asks **what to import**:

1. **Backup / corpus** — restore an oo-backup-2 file OR a volume-set folder OR a large-data
   folder. → routes to `/api/backup/v2/restore` (file) · `/api/backup/v2/volumes/restore`
   (folder of volumes) · `/api/backup/folder/restore` (drive). Encryption auto-detected
   client-side (the `v2DetectEncryption` first-8-bytes read, already shipped) → shows the
   passphrase field only when needed. "What to restore" tickboxes preserved.
2. **Newsletters** — choose **a file selection** (the `<input multiple>` upload → `POST
   /api/newsletters/import`) **or a server-side folder** (the `ooFolderPicker` → the
   `NewsletterImportManager` job). ONE radio in the dialog picks which; both end in a
   file/folder pick (remark 5). The mailbox pull (IMAP/POP3) is a third radio → the mailbox
   form (consent + the network disclosure).
3. **Models** (`.oomodels`) → `/api/backup/models/import`.

Progress: the upload path shows a determinate `<progress>` (files done / total from the import
tally); the folder/volume/drive jobs reuse the task-manager job progress poll (done/total +
the rule-of-three ETA already in the managers) → the "clear progress bar + live data-volume
readout" (bytes + files) the maintainer asked for.

## 6b — Unified EXPORT / BACKUP

**One "Export / Back up" button** → `#export-dialog`, which asks **what to export**:

1. **Encrypted corpus backup (recommended)** → the **OOENC2 volumes + parity** path
   (`VolumeBackupManager`, `/api/backup/v2/volumes/start`) — server-side dest folder via
   `ooFolderPicker` + passphrase + the parity fraction. NOT the legacy 2 GiB single-file path
   (the mandate). The selective "what to back up" tickboxes (articles / newsletters / …) ride
   here.
2. **Large data to a drive** (wiki dumps + OSM regions + models, copied as-is) → the folder
   backup (`/api/backup/folder/plan` preflight → `/start`), server-side dest + the
   category tickboxes + the free-disk preflight.
3. **Plaintext / quick export** (small, no passphrase) → the legacy `write_backup_v2`
   plaintext path (kept honest — a deliberate plaintext escape hatch).
4. **Models only** (`.oomodels`) → `/api/backup/models/export`.

Progress: the volume + folder jobs already report `{phase, volumes_written}` / `{files, bytes}`
— surface a determinate bar + a live "N volumes · X GB written" readout. Encryption verdict
(the shipped "encrypted (AES-256-GCM)" pill) shown on completion.

## Honesty + Desk-lesson guardrails

- **Nothing lost.** Every existing import/export type stays reachable through the new dialogs.
  An absorption test (`test_repo_invariants`) asserts the unified Import dialog routes to ALL of
  `{/api/backup/v2/restore, /api/backup/v2/volumes/restore, /api/backup/folder/restore,
  /api/newsletters/import, /api/newsletters/import-folder, /api/newsletters/mailbox,
  /api/backup/models/import}` and the Export dialog to the volume/folder/plaintext/models export
  endpoints — so a future edit can't silently drop one.
- **OOENC2 mandate**: a guard asserts the unified encrypted-backup path calls
  `/api/backup/v2/volumes/start` (the streaming-volume path), NOT the 2 GiB single-file
  `write_backup_v2` encrypted path.
- **No fabricated progress**: the bar shows only the owner-reported bytes/files/volumes
  (never a guessed rate), exactly as the existing jobs do.
- **The network disclosure** (mailbox pull) + **the restore-is-additive** note stay visible.
- New dialog strings via `t()` (English fallback; key ×12 in the i18n tail).

## Build order

6a Import dialog (routing + the newsletter fuse + the absorption test) → 6b Export dialog (the
OOENC2-mandate guard + the selective tickboxes) → retire the scattered controls (made
unreachable, not deleted, until the click-through confirms the dialogs cover everything).

---

## ADDENDUM — maintainer refinements 2026-07-01 (SUPERSEDES parts of 6a/6b above)

The maintainer confirmed a simpler, folder-centric shape this session. Where this conflicts
with the sections above, THIS wins:

- **Remove the 2 GiB single-file path ENTIRELY** (both backup and restore). "Some backup
  options simply don't work [at scale] — remove them entirely; keep what works all the time,
  whatever the database." So 6b's "plaintext / quick export escape hatch" is DROPPED; the only
  encrypted-corpus backup is the OOENC2 volumes + parity path. The single-file *restore* stays
  reachable ONLY as a one-time legacy-migration case discovered by the Import scan (below), then
  the endpoints are removed in the final slice.
- **Import is FOLDER-DISCOVERY-driven, not a kind-picker.** Point the Import at a folder → it
  SCANS + classifies the contents (progress bar if slow) → asks "what do you want to import?"
  over what was ACTUALLY FOUND (our corpus volumes, model blobs, maps, wiki dumps, loose `.eml`,
  source CSV, legacy single-file backup). No dedicated LLM tool — models are one detected kind.
- **Export is INVENTORY-driven, one checklist.** ONE question "what do you want to back up?" over
  what EXISTS + sizes: **Corpus** (one atomic encrypted item, with a breakdown shown — articles ·
  sources · **dates** · keywords · size — so nothing feels forgotten) + **LLM models · offline
  maps · Wikipedia dumps** (separately selectable blobs). Not the 4 kinds of 6b.
- **New backend:** `GET /api/backup/inventory` (`src/backup/inventory.py`) reports the above.
- **Folder pick:** reuse the existing `ooFolderPicker(inputId, requireWritable)` + `/api/fs/list`.

### Slice status (this build)
- **Slice 1 — Export/Backup: BUILT (this PR).** `/api/backup/inventory` + a unified
  "Export / Backup" dialog (`#ux-export`) that drives `/backup/v2/volumes/start` (corpus) then
  `/backup/folder/start` (blobs) into one destination folder, inventory-checklist + progress.
  Additive — old panels stay. `tests/test_backup_inventory.py`. Frontend browser-unverified.
- **Slice 2 — Import discovery:** a folder-scan/classify endpoint + the folder-discovery Import
  dialog (reuses the restore/ingest endpoints in the table above).
- **Slice 3 — Simplify + remove: BUILT (this PR).** Collapsed the two fully-redundant panels
  (large-data folder + encrypted volumes) into the unified dialogs and removed the capped
  single-file CREATE controls (the option that fails at scale). Kept — deliberately — the
  legacy single-file RESTORE (the only migration path for an existing single-file backup) and
  the backend endpoints (heavily tested; UI-unreachable now, per "made unreachable, not
  deleted"). `tests/test_unified_backup_ui.py` is the absorption guard (the dialogs still route
  to inventory + volumes/folder backup + import-scan + volumes/folder restore + newsletter
  folder import; the redundant panels + capped create UI are gone; the legacy restore stays).
  REMAINING (browser-verified follow-up): physically delete the orphaned volume/folder JS
  handlers + the capped-create backend endpoint once a click-through confirms nothing regressed.

Full standalone write-up: `docs/design/UNIFIED_IMPORT_EXPORT.md` addendum + this session's ledger.
