> **Archived 2026-09-07 from `docs/FUTURE_DEVELOPMENTS.md`, verbatim and unedited.** It is an embedded
> HISTORICAL LEDGER — the agreed build order for the 0.0.9 cycle, long since executed — and it was displacing the design-intent material that document exists
> for. Nothing was condensed or dropped in the move. Its still-open items live on the live boards
> (`CLAUDE.md`'s Open queue and `docs/ROADMAP.md`); read this file as a record of what was observed and
> when, not as a status.

## The 0.0.9 sequencing (maintainer-agreed 2026-06-11)

1. **Database reliability batch** — the mandate below, designed TOGETHER with
   SQLCipher at-rest encryption (standing ruling: a fresh, dedicated session;
   crypto and data-integrity deserve full attention, not a session tail).
   Deliverables: gap analysis → design doc → implementation with a torture-test
   suite (interrupted imports, duplicate floods, cross-version restores).
2. **Newsletter scraper** — only after (1) is solid (see its section below).
3. **Convergence flagship** (space-time layers 3+4) built on the
   When×Where×Who ingest-time anchoring substrate.
4. **Audit remediation queue** — `docs/audit/06_FULL_AUDIT_0_0_9.md` (ranked;
   two items await a maintainer ruling: the "stays on this machine" wording and
   caveats-visible-by-default vs calm UI). Rides along in normal sessions.
5. Standing queue items (CLAUDE.md) continue as session work between batches:
   agenda views/depth, corpora system, global search rework, download/task
   manager, interactive charts + SI formatter, i18n long tail.

---
