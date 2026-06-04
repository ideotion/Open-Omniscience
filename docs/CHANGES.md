# Changelog

## 0.4 — Trustworthy core + honesty pass

A near-total rebuild around a small, genuinely-working spine, plus a ruthless
audit/debug pass. Highlights:

**Core (Phases 0–1):** single `pyproject.toml` on Python 3.13; clean DB session
layer (no import-time side effects, WAL); one ethical fetch path (robots.txt
fail-closed, rate-limited) → trafilatura extraction → dedup + provenance; real
SQLite **FTS5 Boolean search** (AND/OR/NOT, phrases, precedence); CSV/JSON export;
dependency-free offline web UI; Qubes-aware installer; honest docs.

**Capabilities (Phases 2–5):** local LLM via Ollama (HTTP, loud 503 degradation);
commodity prices + **real scipy correlation** (no fabricated p-values); real
source-uptime monitoring + z-score anomalies; IMAP email into the unified corpus;
honest EXIF metadata verification; **Merkle + Ed25519 signed evidence bundles**
with a standalone verifier.

**Phase 6 — repository honesty:** purged ~19k lines of fabricated/dead code (live
ratio 36%→68%); removed the hallucinated LLM model catalog; auto-seed the full
~1,780-source catalog on first run; Alembic migration path with a CI drift gate;
salvaged Pillar-2's genuine statistics into `src/analysis` and **quarantined the
remaining pillars** (intent preserved — see PILLAR_INTENT_MAP).

**Full re-audit (2026-06):** quarantined the fabricated `link_analyzer` stack;
fixed broken endpoints and salvaged-stat bugs (chi-square crash, regression CI,
odds-ratio); closed the evidence-verification trust hole (pinned key + full-item
Merkle + domain separation); fixed email charset corruption, ingest rollback
isolation, the core-only-install boot, and the whole P2 backlog (DI to
`Depends(get_db)`, shared rate limiter, bounded uploads, cache/url/regex/compression
fixes). See [AUDIT_2026-06.md](AUDIT_2026-06.md). 400+ tests, all green.

## 0.01–0.03 (historical)

Early concept releases (forked from HTTrack). Largely non-functional / design-only;
superseded by the 0.4 rebuild. Retained only in git history.
