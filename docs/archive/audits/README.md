# Archive — spent audit-cycle working files

The working artifacts of the pre-0.2 audit cycles, kept for accountability. **None of
these describe the current system**; the binding ledger is
[`../../../CLAUDE.md`](../../../CLAUDE.md).

Moved here in the 2026-07-13 doc-archival pass (non-lossy `git mv`) to declutter the live
`docs/audit/` directory. Older prose in `CLAUDE.md`, `docs/CHANGES.md`, `README.md`,
`docs/ARCHITECTURE.md` and `docs/ledger/SHIPPED_LOG.md` may still cite the original
`docs/audit/…` paths as historical records; the mapping is `docs/audit/<name>` →
`docs/archive/audits/<name>`.

| file(s) | what it is |
| --- | --- |
| `00_BASELINE.md` … `05_DOCS_AND_RELEASE.md` | the six-phase pre-0.1 audit working docs |
| `ACTION_PLAN_2026-06-14.md`, `ACTION_PLAN_2026-06-15_solo.md` | audit remediation plans |
| `AUDIT_LOG_2026-06-14.md`, `AUDIT_LOG_2026-06-15_solo.md`, `AUDIT_LOG_2026-06-18.md` | audit run logs |
| `findings.csv` | the findings register for those cycles |
| `raw/` | raw tool dumps (bandit / mypy / ruff / radon / vulture / coverage / schema) |
| `diagrams/` | audit diagrams |

The audit **records of record** stay live in [`../../audit/`](../../audit/):
`06_FULL_AUDIT_0_0_9.md`, `07_TRANSVERSAL_AUDIT_V01.md`, and the current
`CUMULATIVE_INTEGRITY_AUDIT_2026-07-13.md`.
