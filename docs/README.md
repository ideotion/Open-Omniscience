# Documentation index

The documentation is consolidated into a small set of complete guides. Start with the
one that matches what you need.

> **Planning lives in a few clearly-separated homes** (the map):
> **[ROADMAP.md](ROADMAP.md)** = the forward-looking board (what's next + status) ·
> **[../CLAUDE.md](../CLAUDE.md)** = the binding ruling ledger + live Open queue (source of
> truth) · **[FUTURE_DEVELOPMENTS.md](FUTURE_DEVELOPMENTS.md)** = design intent (the *why*) ·
> **[product/SCALE_ROADMAP.md](product/SCALE_ROADMAP.md)** = the deep scale/stability detail ·
> **[ledger/](ledger/)** = what already shipped. Older/historical planning docs are under
> **[archive/](archive/)**.

## Use it
- **[QUICKSTART.md](QUICKSTART.md)** — install (Qubes + local dev) and the end-to-end loop.
  A machine-drafted French mirror lives at
  [`i18n/fr/QUICKSTART.md`](i18n/fr/QUICKSTART.md) (honest-banner convention;
  [`i18n/`](i18n/) is where future translated docs land).
- **[USER_MANUAL.md](USER_MANUAL.md)** — the complete guide: every tab, control, setting,
  workflow, env var and API area, **plus per-feature deep-dives** (Home briefing, source
  integrity & anti-amplification, shared annotations, insights, the world map &
  article date-tags, Wikipedia tracking, world-law tracking, markets, chain of custody).
- **[PRESENTATION_PUBLIC.md](archive/PRESENTATION_PUBLIC.md) *(archived)*** — a plain-language public
  presentation (français).

## Understand it
- **[DESIGN.md](DESIGN.md)** — what the app is and isn't (product synthesis), where each
  original "pillar" now lives, the GUI redesign reasoning, and the content-analysis strategy.
- **[ARCHITECTURE.md](ARCHITECTURE.md)** — the database & configuration, the HTTP API map
  (live reference at `/docs`), and internationalisation.
- **[FUTURE_DEVELOPMENTS.md](FUTURE_DEVELOPMENTS.md)** — the persistent design memory (north
  star): design intent + rationale + open questions for the big features.
- **[research/](research/)** — committed reference material (not status) for two design
  tracks: statistical-data ingestion/diversified visualization, and keyword-engine
  optimization; verify-before-trust, per its own README.

## Plan / track
- **[ROADMAP.md](ROADMAP.md)** — the single forward-looking board: current DB limitations,
  performance & scale (P0/P1), known bugs, and the feature backlog, each with a status.
- **[product/SCALE_ROADMAP.md](product/SCALE_ROADMAP.md)** — the deep scale/stability roadmap
  (the 0.2 cycle's P0/P1 acceptance detail).
- **[ledger/shipped.csv](ledger/shipped.csv)** + **[ledger/SHIPPED_LOG.md](ledger/SHIPPED_LOG.md)**
  — the index and verbatim log of shipped work (with reusable lessons).
- **[design/](design/)** — per-feature design-of-record specs.
- **[process/](process/)** — the standing recursive-improvement-cycle protocol
  ([`IMPROVEMENT_CYCLE.md`](process/IMPROVEMENT_CYCLE.md)) plus sequencing drafts awaiting a
  maintainer decision (never executed on their own say-so).

## Trust it
- **[ETHICS.md](ETHICS.md)** — the principles (Munich Charter), plus GPLv3 compliance and
  third-party notices/attributions.
- **[GOVERNANCE.md](GOVERNANCE.md)** — acceptable-use principles: what the tool is for, the
  lines it won't cross, and how it intends to stay trustworthy as it grows.
- **[legal/](legal/)** — the first-launch-gated legal documents (Terms, Usage Charter, Privacy
  Policy, Legal Notices — French original + all 12 UI-language translations), with a permanent,
  visible notice that they are drafted without professional legal review.
- **[SECURITY.md](SECURITY.md)** — threat model, the local-first security posture, and the
  application-security audit + hardening.
- **[audit/](audit/)** — the audit trail: the 0.0.9 full audit, the V0.1 and 0.3 transversal
  audits, a cumulative-integrity audit, an external bug-bounty-style audit, and a 100-agent
  systematic GUI test report — each read-only, with findings hand-re-verified before being
  recorded.
- **[testing/LEGAL_DECLINE_UNINSTALL_TEST.md](testing/LEGAL_DECLINE_UNINSTALL_TEST.md)** — the
  manual test procedure for the first-launch legal-decline → secure-uninstall path (confirms
  the data dir and signing keys are actually wiped).

## Contribute / history
- **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to contribute, and the versioning policy
  (the cycle-branch ⇒ version convention, the maturity ladder, the single source of truth).
- **[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)** — the contributor conduct pledge.
- **[maintenance/EXTERNAL_DEPENDENCIES.md](maintenance/EXTERNAL_DEPENDENCIES.md)** — the
  canonical list + upgrade checklist for everything the project pins, vendors, or bundles from
  an outside source.
- **[CHANGES.md](CHANGES.md)** — the changelog.
- **[HISTORY.md](HISTORY.md)** — a consolidated archive of audits, the security proof
  trail, quality check-ups, the salvage map, and the early phase/optimization reports.
- **[QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md)** — the permanent record of the removed
  six-pillar/fabricated-module tree (never wired into the running app; preserved on the
  `quarantine-archive` branch).
- **[archive/](archive/)** — historical planning docs (pre-0.2 roadmaps under
  `archive/roadmaps/`, spent autonomous-session briefs under
  [`archive/session-briefs/`](archive/session-briefs/), superseded release plans + gates under
  [`archive/releases/`](archive/releases/), closed field-test ledgers under
  [`archive/field-tests/`](archive/field-tests/), machine-readable audit findings, raw
  phase-report data, the public presentation).
