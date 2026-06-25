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
