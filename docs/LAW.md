# World law — change-tracking for statutes, gazettes & IP

> **Status:** `0.06` Phase E — shipped. The §5 vertical: a "Wikipedia for the law."
> Reuses the change-tracking engine (`src/wiki`) and the shared `src/signals/` engines.

Aggregate the **law** — statutes, legislation, official gazettes, IP records — from
official sources worldwide, and **track how it changes over time**. Law is public in
many countries and changes by amendment, so the data *is the diff*: what changed, when.

## On by default — a worldwide catalog of real official sources

`configs/legal_sources.yml` ships a curated, worldwide set of **real official primary
sources** — national legislation databases (`legislation.gov.uk`, EUR-Lex, Légifrance,
`gesetze-im-internet.de`, `congress.gov`/`govinfo.gov`, `legislation.gov.au`,
`indiacode.nic.in`, `elaws.e-gov.go.jp`, `law.go.kr`, …), official gazettes, IP offices
(WIPO Lex, USPTO, EPO, EUIPO, JPO, …) and open case-law/filing systems (CourtListener,
SEC EDGAR). On first run these are seeded as ordinary **ingestible, searchable** sources
(`source_type` legal/ip), so they flow through the *same* ethical pipeline as news.

A curated subset of stable, well-known **consolidated-law documents** (e.g. the UK Human
Rights Act, the EU GDPR, the US Constitution) is registered for **change-tracking** out
of the box.

## How tracking works (reuses the Wikipedia engine)

For each tracked document, the first successful fetch is the immutable **baseline**
("the law as it stood on date X"). Every later fetch whose *normalised visible text*
differs records a revision carrying the byte delta, a capped unified **diff** against the
baseline, and an honest **large-change flag** (reusing the wiki flagging thresholds).
Run it from the **World law** tab ("Track changes now") or on the background scheduler
(`law` mode). All fetching is through the **ethical, robots-fail-closed** path.

## Briefing cards from the law corpus

- **Law changed** (watch) — a flagged change to a tracked legal document.
- **Model legislation** (investigate) — near-identical legal text across two or more
  jurisdictions (the §1/§2 near-dup engine), a measurable diffusion pattern.

Plus, because legal text is in the unified corpus, **law ↔ news** correlation and
keyword analytics work over it like any other source.

## API

| Method & path | Purpose |
|---|---|
| `GET /api/law/status` | coverage: documents per jurisdiction, change/flag totals |
| `GET /api/law/documents` | tracked documents (optionally `?jurisdiction=`) |
| `GET /api/law/documents/{id}` | one document with its change history (diffs) |
| `GET /api/law/changes` | recent (flagged) legal changes, newest first |
| `POST /api/law/track` | fetch all watched documents now (ethical fetcher) |
| `POST /api/law/seed` | (re)seed the worldwide catalog + register documents |

## Honesty constraints (law is high-stakes)

- **Not legal advice, not the authoritative source.** The aggregated copy is a
  *research mirror*; every record links back to the official gazette, and the UI says so.
  Track and surface; never interpret legality or judge a law.
- **"Public" ≠ "freely redistributable."** Licences vary even where text is public —
  each is respected, attributed, with provenance stored, robots fail-closed (as for news).
- **Scope honestly.** "Every country" is the north star, not v1: the catalog is broad but
  curated, and change-tracking is by normalised-text diff (consolidated-text portals give
  the cleanest signal). Structured formats (Akoma Ntoso / ELI) per-edit diffs are the next
  refinement; the tool says which it has.
- **Translation** (via the local LLM) is a separate, clearly-labelled aid — never an
  authoritative legal translation.
