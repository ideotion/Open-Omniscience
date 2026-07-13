# Archive — historical reports and superseded documents

Records kept for accountability; nothing here describes the current system.

- `PHASE1_REPORT.json`, `QUBS_PHASE*_REPORT*.json` — prior (pre-v0.0.7) automated audit
  scans. The three **full** dumps (`QUBS_PHASE2_FULL_REPORT.json` 62.9 MB,
  `PHASE2_REPORT.json` 3.1 MB, `PHASE3_REPORT.json` 1.8 MB) were removed from the working
  tree in the v0.0.7 audit (finding DOC-03) because they inflated every clone of a
  local-first tool by ~68 MB while duplicating what the kept indexes summarise. They remain
  fully retrievable from git history (removed in the Phase-5 docs commit on the
  `claude/laughing-bohr-mzqflp` audit branch).
- `findings.{csv,json}`, `security_findings.{csv,json}` — the kept indexes of those scans.
- `PRESENTATION_PUBLIC.md` — the public pitch narrative; archived because it is marketing
  material, not technical documentation. Still accurate as a narrative.
- `SOLO_SESSION_DECISIONS.md`, `SOLO_SESSION_PR_PLAN.md` — a completed solo session's
  decision log + PR plan (was `docs/`).

## Subfolders

- [`session-briefs/`](session-briefs/) — spent autonomous-session operating manuals
  (through the 2026-07-11 S1–S6 program). See its README for the old→new map.
- [`audits/`](audits/) — the pre-0.2 audit cycles' working files (phase docs, logs,
  action plans, `findings.csv`, `raw/` tool dumps, `diagrams/`). See its README.
- [`source_enrichment/`](source_enrichment/) — the completed source-metadata-enrichment
  session's prompts + fan-out workflow (was `docs/design/source_enrichment/`).
- [`roadmaps/`](roadmaps/), [`field-tests/`](field-tests/), [`releases/`](releases/) —
  earlier archival passes.

The audit **records of record** stay live in [`docs/audit/`](../audit/)
(`06_FULL_AUDIT_0_0_9.md`, `07_TRANSVERSAL_AUDIT_V01.md`, and the current
`CUMULATIVE_INTEGRITY_AUDIT_2026-07-13.md`).
