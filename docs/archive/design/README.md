# Archive — spent design docs (non-session-brief)

Older architecture/design documents whose proposals have been fully executed and
verified against live `main`, kept for accountability and history. **None of these
describe pending work** — the binding ledger is
[`../../../CLAUDE.md`](../../../CLAUDE.md) and the forward board is
[`../../ROADMAP.md`](../../ROADMAP.md).

This folder is distinct from
[`../session-briefs/`](../session-briefs/README.md) (single-session operating
manuals): these are longer-lived architecture/strategy docs whose *entire* scope
turned out to be shipped, not a session's own brief.

Moved here on 2026-07-22, after a subagent-fanned-out audit of the whole
`docs/design/` tree verified each file's claims against live code — see
[`../design/ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](../../design/ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md)
for the verification detail (each doc's own self-description was stale in at least
one place; the plan doc records the real, checked status).

| file | was at | verified status |
| --- | --- | --- |
| `DB_RELIABILITY_01_GAP_ANALYSIS.md` | `docs/design/` | Fully executed. One documented deviation (annotations stayed as JSON files rather than moving into DB tables), but the underlying goal — comprehensive backup coverage — is met a different way (the folder-backup engine collects them as first-class members). |
| `DB_RELIABILITY_02_DESIGN.md` | `docs/design/` | Fully executed alongside 01 (SQLCipher gate-zero, merge pipeline, per-domain conflict policies, torture-test doctrine all shipped and tested). |
| `COLLECTOR_WRITER_BATCHING.md` | `docs/design/` | Fully executed — `src/ingest/batch.py` implements the doc's exact design (`OO_COLLECT_COMMIT_BATCH`, default 8, with a `=0` legacy-behavior escape hatch), wired into both the RSS and crawl ingest paths, with a dedicated soak-test harness. The doc's own header ("Status: DESIGN, not built") was stale. |

Older prose in `CLAUDE.md` and `docs/ledger/SHIPPED_LOG.md` may still cite the original
`docs/design/…` paths as historical records; this table is the old→new map.

- [`UNIFIED_IMPORT_EXPORT.md`](UNIFIED_IMPORT_EXPORT.md) — the unified Import + Export/Backup dialog
  consolidation (field remarks 2 / 5 / 6). **Archived 2026-09-07** once its one live carry-over was
  lifted: the browser-gated cleanup (retire the orphaned `folderBackupStart` / `volBackupStart`
  handlers and the capped single-file-CREATE remnant, after a click-through) is now a row in
  `docs/ROADMAP.md` §4 under *Backup, import / export & data-safety*, so it no longer depends on
  anyone reading this file. Everything the doc designed is shipped: the `#ux-export` / `#ux-import`
  dialogs, the volumes+parity and folder engines behind them, and `scan_import_folder`'s discovery.
