# Release plan — 0.0.8, part 2 ("the sense-making horizon")

> **STATUS: EXECUTED — WP1–WP5 all delivered** (PRs #64/#65 WP1+WP2, #67 WP3, #68 WP4,
> #69 WP5). Release verification at cycle close recorded in `docs/CHANGES.md` and below.
>
> Continuation of [`RELEASE_0.0.8_PLAN.md`](RELEASE_0.0.8_PLAN.md) — per the maintainer's
> direction the whole roadmap push (RM-01–RM-19) ships under the `0.08` cycle. This part
> covers the **Next** horizon's M-effort, high-RICE items; the XL centerpiece (**RM-05
> semantic/NER search**) plus packaging (RM-08) and perf niceties (RM-04) anchor the
> following cycle — the public-alpha gate — rather than being rushed here.
> Same discipline as 0.0.8: one reviewable work package at a time, acceptance criteria up
> front, the Evidence Protocol throughout, every §0.5 invariant preserved.

## Scope

| WP | Roadmap | Item | Effort |
|----|---------|------|--------|
| WP1 | RM-07 | Methods-appendix / report generator | M |
| WP2 | RM-15 | Provenance-preserving export formats (versioned schema, graph export) | M |
| WP3 | RM-06 | Scheduler polish: per-run report + auto-export drop folder | M |
| WP4 | RM-12 | Corpus-wide LLM synthesis (bounded, provenance-tracked) | M |
| WP5 | RM-19 | Source discovery, **offline channels only** (citation-promotion + catalog refresh into a candidates staging state, with the activity log) | L |
| — | RM-05/08/04 | Deferred to 0.1.0 by design | — |

## WP1 — RM-07: methods-appendix / report generator (M)

**Motivation:** scenarios 3 and 7 (fact-checker verdict; reproducibility). The corpus can
already prove *what* it holds (hashes, custody, evidence bundles); it cannot yet emit the
*how* — the exact query, filters, versions and counts behind an analysis — as a document.

**Changes**
- `POST /api/reports/methods` — body `{query | article_ids, case_name?, notes?}` → a
  **Markdown methods appendix**: app version, generated-at, the verbatim query and filters,
  result count, per-article provenance rows (title · source · url · canonical · content
  hash · published), corpus context (total articles, date range), and a verification footer
  (how to re-verify against an evidence bundle). Pure function over existing data — nothing
  new is computed, nothing is concluded.
- Optional `include_bundle: true` → also returns the signed evidence bundle inline so one
  response carries document + proof.
- UI: a "Methods appendix" button on Search results and in the Briefing drawer.

**Acceptance:** endpoint tests (by ids and by query; 400/404 paths; the appendix contains
the verbatim query, the version, and every article's hash); the document round-trips
against `verify_evidence` when `include_bundle` is used; suite green.

## WP2 — RM-15: provenance-preserving exports (M)

**Motivation:** scenarios 2/4/8 — researchers feed their own tooling; exports must carry
provenance and a stable contract.

**Changes**
- **Versioned export schema:** every CSV/JSON export gains a header/envelope
  (`export_schema: oo-export-1`, app version, generated_at, the generating query) without
  breaking existing columns; documented in `docs/ARCHITECTURE.md`.
- **Graph export:** `GET /api/links/export.graphml` (and `.json`) — the who-cites-whom
  graph (articles ↔ external domains from `article_links`/`external_sources`) as GraphML,
  counts only, no inferred scores. Honest caveat in the file header.

**Acceptance:** schema envelope asserted in export tests; GraphML parses (xml.etree) and
node/edge counts match the DB; documented.

## WP3 — RM-06: scheduler polish + drop-folder export (M)

**Motivation:** scenario 4 (newsroom desk): hands-off corpus upkeep and integration without
pull-exports.

**Changes**
- Scheduler run report: each run appends one JSON line (started, mode, per-source tallies,
  errors) to `data/scheduler_runs.jsonl`; surfaced in the Collect tab ("last run" detail).
- Optional **drop-folder export**: a scheduler setting `export_dir` — after each run, write
  the new-articles delta as a timestamped CSV/JSON into that local folder (no network, no
  inbound service; pure local file drop). Off by default.

**Acceptance:** runner tests for the report line and the delta drop (tmp dir); settings
round-trip; off-by-default asserted; suite green.

## WP4 — RM-12: corpus-wide LLM synthesis (M)

**Motivation:** scenario 8; the LLM layer is single-article today.

**Changes**
- `POST /api/llm/synthesize` — body `{query | article_ids (≤ 20), model?}`: summarises the
  *set* (bounded fan-out: per-article extractive trim, then one synthesis call; never
  unbounded). Stored in `article_analyses` per source article (`kind="synthesis"`,
  provenance: model + prompt version + the member ids). Response carries the member list so
  the output is traceable to its inputs. Honest 503 without Ollama, like the rest.
- UI: "Synthesize these results" on Search (visible cap).

**Acceptance:** endpoint tests with the fake Ollama client (bounded inputs, member-id
provenance, 503 path, cap enforcement at 20); suite green.

## WP5 — RM-19: source discovery, offline channels (L)

**Motivation:** the maintainer's automated-source-aggregation direction — *transparency
non-negotiable* — starting with the channels that never touch the network.

**Changes**
- `source_candidates` staging table (domain, evidence kind, evidence detail JSON, first/last
  seen, status: candidate|promoted|dismissed) + Alembic migration.
- **Citation-promotion channel:** a scheduler-run step that promotes frequently-cited
  external domains (`external_sources` with ≥ N citing articles, not already a Source) into
  candidates, with the citation count as evidence.
- **Catalog-refresh channel:** surface catalog entries for countries the corpus covers
  thinly (reuses the coverage report) as candidates with that reasoning as evidence.
- **Discovery activity panel** (Sources tab): the candidates list with evidence, promote /
  dismiss buttons (promote = create a disabled Source the operator then enables), and a
  visible log line per discovery run. A Home card surfaces "N new source candidates".
- Budget: a `discovery_per_run` cap in scheduler settings; the DuckDuckGo channel stays
  **out** (it ships only after this staging UX exists, per RM-19's RM-03 dependency).

**Acceptance:** migration applies + zero-drift guard; channel tests (candidate appears with
correct evidence; already-a-source domains skipped; cap honoured; promote/dismiss
round-trip); nothing fetched from the network in any of it; suite green.

## Sequencing

1. **WP1 → WP2** (report + exports: one "defensible output" theme, ships first value fast).
2. **WP3** (scheduler polish) — unlocks WP5's run-step pattern.
3. **WP4** (synthesis) — independent, any time.
4. **WP5** (discovery) — the cycle's largest piece, last.
5. Release ritual as 0.0.8's: checklist re-run, CHANGES section, version verified.
