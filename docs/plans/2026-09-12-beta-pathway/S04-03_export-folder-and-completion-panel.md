# S04-03 — The export: the dated `OpenOmniscience_Backup` folder, the completion panel, `BACKUP_SUMMARY.md`, verify-after-write · 0.4, `RELEASE_0.4_GATE.md` row J

> **Scope:** the export half of `src/static/app-backup.js` and the `#ux-export` dialog,
> `src/backup/volume_job.py` (the destination), `src/backup/stream_backup.py` (naming, the summary, no reuse),
> `src/backup/volumes.py` (`verify_volume_set`), `src/backup/folder_backup.py` (categories), a
> `BACKUP_SUMMARY.md` writer, the licence lines in exports, the bulletin and the evidence ZIP
> (`src/bulletin/evidence.py`), the locales, the tests. Must NOT: touch the import half (`S04-02`), the format
> version (`S04-04` owns the ONE bump — a folder-level summary file is not a manifest change; say so in the
> PR), or build scheduled exports (Q220 = c).
> **Implements:** Q208, Q209, Q210, Q211, Q212, Q213, Q218, Q219, Q220, Q1008.
> **Gated on:** Q823 ⛔ (ODbL) for the OSM licence lines — STOP at that seam; nothing else pending.
> **Sequencing:** after `S04-02` on the shared file, never concurrent with it; before `S04-04`'s CI fixture,
> which exports through this path (a suggestion, not a ruling).

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved. The sheet
sections are §3 (R4, R5) and §11 (Q1008). Data safety: the full skeptic matrix applies.

## 1. The rulings this slice implements — verbatim, by ID

- **Q208** — **(a)** «Volumes · total bytes · per-table counts with articles first (the ruled headline unit) ·
  files copied per category (dumps, models, newsletters) · elapsed · destination path · encryption state ·
  schema version · app version · the licence lines that apply (Q1008).»
- **Q209** — **(a)** «Write `BACKUP_SUMMARY.md` beside `volumes.json` with the same facts, so the folder
  explains itself on a removable drive years later.»
- **Q210** — **(a)** «Local time»
- **Q211** — **(a)** «`_2`, `_3` … appended: `202609121045_OOS_Backup_2`.»
- **Q212** — **(c)** «Spell it out: `OpenOmniscience`.» [placement: amends R5's literal token]
- **Q213** — **(c)** «Always a full new backup, no reuse.»
- **Q218** — **(a)** «Re-read every volume after writing and check its checksum; default ON; the panel says
  "verified".»
- **Q219** — **(a)** «The corpus always; the Wikipedia, OSM and law lanes as opt-in members with their sizes
  shown before the export starts» [placement: the hook now; lane members from 0.4 (wiki) and 0.5 (OSM, law)]
- **Q220** — **(c)** «Never»
- **Q1008** — **(a)** «Every export, bulletin and evidence ZIP carries the attribution lines that apply (CC
  BY-SA 4.0 Wikipedia, ODbL OSM, per-law licences, DB-IP CC BY) and, for OSM-derived rows, the share-alike
  note.» [placement: press lines now; OSM lines wait on Q823]

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §3 context (VERIFIED): export writes volumes directly into the chosen directory, no subfolder, no
  timestamp (`volume_job.py:237–243`); the completion line discards the summary that carries per-table counts
  and bytes (`stream_backup.py:456–465`); the reuse pool scans the destination (`stream_backup.py:766+`);
  "No "OOS" string exists in the tree" — CONTRADICTED by the tree (the fourth bullet).
- grep-verified in this brief: `sed -n '235,245p' src/backup/volume_job.py` — the destination is `mkdir`'d and
  used as-is; `stream_backup.py` — `_load_reuse_pool` `:757` (`:778` "reuse (older format); volumes are fully
  re-written"), `volumes_reused` / `bytes_reused` `:636–653`, the summary `{"tables": counts,
  "articles_commitment"}` + the alembic `version_num` `:434–500`, `dest/volumes.json` swapped once
  `:1135–1154`; `volumes.py:37` `MANIFEST_NAME = "volumes.json"`, `:42` `_KNOWN_KINDS = ("oo-volumes-1",
  "oo-volumes-2")`, `verify_volume_set` `:161`; `artifact.py:159` the manifest's `encrypted` flag, `:412`
  `app_version` from `src/utils/export_envelope.py`; volumes are always encrypted (`volume_job.py:236`).
- grep-verified: the export UI — `openUnifiedExport` (`app-backup.js:20`); `_uxShowLastCompletedExportSummary`
  (`:40–71`) prints only "Backup complete → <dest> (last completed export)"; two phases POST
  `/api/backup/v2/volumes/start` (`:387`) then `/api/backup/folder/start` (`:409`); a SEPARATE verify job
  exists (`/api/backup/v2/volumes/verify` `:577`, "Backup verified — the set is complete and intact." `:597`),
  not run after a write. Ids: `ux-export|dest|pass|run|pause|progress|bar|checklist|inv-status`; the
  inventory is `/api/backup/inventory` (`backup_v2.py:52`).
- grep-verified: `grep -rn "OOS" src/ --include=*.py` — the bulletin already uses the token:
  `src/bulletin/annexes.py:121–135` `bundle_stem` → `YYYYMMDD_OOS_Bulletin_<cadence>` "with `_2` and up for a
  repeat" (the collision precedent Q211 mirrors); `src/bulletin/evidence.py:232` the evidence ZIP
  `YYYYMMDD-OOS-<cadence>-evidence.zip`; `src/bulletin/store.py:50`.
- grep-verified: `src/backup/folder_backup.py:48` `_CATEGORIES = ("wiki_dumps", "osm_regions", "models",
  "hf_models")` — newsletters ride the corpus artifact as a queue kind, not a folder category; the member
  mechanism is `file_members` (`artifact.py:154`) + `place_artifact_file_members` (`folder_backup.py:540`),
  which the sheet's Q219 calls "the artifact-member mechanism of PR #1020".
- grep-verified: the only attribution strings in `src/`: `src/geo/ip_geo.py:59` `ATTRIBUTION = "IP geolocation
  by DB-IP (https://db-ip.com) — CC BY 4.0"`, `src/weather/openmeteo.py:52` (Open-Meteo CC BY 4.0),
  `app-map.js:539`; no `CC BY-SA` or `ODbL` string anywhere; `src/bulletin/evidence.py` carries none;
  `wiki_pages` / `wiki_revisions` / `law_documents` / `law_revisions` DO ride the merge
  (`merge.py:1714–1715`).
- grep-verified: no scheduled-export code exists (`grep -rn "scheduled export\|auto_export\|export_schedule"
  src/` → none) — Q220 = c is the status quo, to be STATED.

## 3. Slices — what to build, in order

### S1 — The dated folder (R5 amended by Q212; Q210, Q211, Q213)
- **What:** the export creates `<dest>/YYYYMMDDHHMM_OpenOmniscience_Backup` — local time — with `_2`, `_3` …
  on collision, never touching an existing folder's bytes; both phases write inside it; exports never consult
  the reuse pool (Q213 = c) and the panel states the cost the gate row names: every export writes every
  volume. One constant for the token is a design choice, not a ruling.
- **Why (ruling):** R5; Q212 = c; Q210 = a; Q211 = a; Q213 = c.
- **Acceptance:** a test that two exports in the same minute yield `…_Backup` and `…_Backup_2` with the first
  untouched (negative space: no overwrite, ever); the folder listing quoted in the PR.
- **May not decide:** whether the bulletin's `_OOS_` names follow the spelled-out token (§6).

### S2 — Verify after write (Q218)
- **What:** after the last volume lands, `verify_volume_set` re-reads every volume and checks its checksum;
  default ON; the panel reads "verified" only on a full pass — OFF or failed reads exactly that; the
  removable-drive cost (a second read of every byte) is stated ×12.
- **Why (ruling):** Q218 = a. **Acceptance:** a fixture corrupting one byte of one volume after the write:
  the panel does NOT read "verified" and names the volume; mutation-checked.

### S3 — The completion panel and `BACKUP_SUMMARY.md` (R4; Q208, Q209)
- **What:** the panel lists, in this order, volumes · total bytes · per-table counts with `articles` first ·
  files copied per category (the real `_CATEGORIES` plus the corpus kinds) · elapsed · destination ·
  encryption state (the manifest flag) · schema version (the alembic `version_num` the summary already reads)
  · app version · the licence lines (S4); `BACKUP_SUMMARY.md` beside `volumes.json` carries the same facts and
  is written LAST so it can carry the verify result; `_uxShowLastCompletedExportSummary` renders the same
  panel.
- **Why (ruling):** R4; Q208 = a; Q209 = a. **Acceptance:** the gate's "closes when" — a test reads
  `BACKUP_SUMMARY.md` and `volumes.json` from one export and asserts every shared figure equal; the summary
  file quoted in the PR.

### S4 — The licence lines (Q1008) — the lines that apply today; STOP at Q823
- **What:** every export, bulletin and evidence ZIP carries the attribution lines that APPLY to what it holds:
  DB-IP CC BY 4.0 (reuse `ip_geo.ATTRIBUTION`), Open-Meteo CC BY 4.0 where weather rows ride, Wikipedia CC
  BY-SA 4.0 where `wiki_pages` / `wiki_revisions` ride, per-law licences from whatever licence metadata the
  law rows carry — where a row carries none, the line says so (a gap published as a gap, never a fabricated
  licence). NO ODbL line and NO share-alike note until Q823 ⛔ is answered.
- **Why (ruling):** Q1008 = a; the gate row: "the press lines now; OSM lines wait on Q823 ⛔".
- **Acceptance:** a test per carrier (export panel + summary, bulletin, evidence ZIP) that the lines present
  match the members present, and that no OSM line exists.
- **May not decide:** what the "press lines" say for scraped press content (§6).

### S5 — The member hook (Q219)
- **What:** the inventory (`/api/backup/inventory`, the `ux-checklist`) carries a size per member; the corpus
  is always in; the Wikipedia, OSM and law lanes appear as opt-in members with their sizes shown BEFORE the
  export starts, as each lane lands (`S04-09`, `S05-04`, `S04-10`) — nothing lane-specific is built here.
- **Why (ruling):** Q219 = a. **Acceptance:** the sizes visible in the click-through for today's members.

### S6 — Never scheduled (Q220 = c)
- **What:** a stated non-feature in the user-facing backup docs (exports are a deliberate act); no backlog
  entry (option a was not chosen); no code. **Why (ruling):** Q220 = c.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: `node
--check` on touched script blocks; the three i18n gates for every new string (ratchets from `ci.yml`); the
whole-tree guard set; the full skeptic matrix with the negative-space lens (no overwrite on collision, no
"verified" on a failed re-read, no licence line for an absent member, no OSM line at all); every guard
mutation-checked by name; the Chromium click-through (Q1128 = a) of Settings → Data & backup → Export
(`#ux-export`): the member sizes, the panel, the "verified" state — en, fr, ar; the export on the reference VM
the gate names (§5); the numstat rule for the ledger files. The removable-drive re-read is an operator step:
`not-measurable-here`.

## 5. Operator steps

1. An export to a removable drive from the maintainer's instance: the folder name, `BACKUP_SUMMARY.md`
   quoted beside `volumes.json`, the panel reading "verified". Artifact: the listing + the summary in the PR.
2. The click-through of the export surfaces (Q1128 = a). Artifact: the record under `docs/audit/`.
3. The maintainer's word on whether the sandbox counts as "the reference VM" the gate row names.

## 6. What this slice may not decide

- Q823 ⛔ (ODbL): no OSM licence line, no share-alike note — the slice stops at that seam.
- The wording of the "press lines" for scraped press content; the tree holds no such statement today.
- Whether the bulletin's and evidence ZIP's `_OOS_` / `-OOS-` names follow Q212's spelled-out token — Q212
  ruled the backup folder only.
- The encryption-state wording when a folder phase copies unencrypted category files beside encrypted volumes.
- No ASSUMPTION and no CONFLICT is built on here.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or
  PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
