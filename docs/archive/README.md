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

The **current** audit cycle's reports live in [`docs/audit/`](../audit/), with
`docs/audit/findings.csv` as the live findings register.
