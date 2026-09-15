# S05-07 — Laws: the evolution surface · 0.5, `RELEASE_0.5_GATE.md` row G

> **Scope:** `src/law/` (the adapters' `valid_on`, `diff.py`, `summarize.py`), `src/api/law.py` (the reader
> `/documents/{id}/view`, `/changes`), `src/static/app-gov-law.js`, `#law-changes` / `#law-docs`; for the
> homogeneity the Q918 note demands, the wiki change surfaces (`#wiki-changes`, `#wiki-tc*`, `#wiki-diff`,
> `/api/wiki/changes`, `/pages/{id}/revisions`) and 0.4 row O's Living sources view; FTS over versions with
> `valid_on`; analytics 3–5; the language switch; AI summaries. Must NOT build: breadth (0.6), subnational
> (0.7; Q903 is a recorded CONFLICT), a second adapter (Q925 ⛔ is 0.4 row Q's PENDING), the versioning
> primitive itself (0.4 row Q, Q905 — surfaced here), a law-only change-tracking grammar.
> **Implements:** Q916, Q918 (+ note — the note is a requirement), Q920; via the gate row: Q107 (0.5 = the
> evolution surface), Q905, Q908, Q914 · 3–5.
> **Gated on:** 0.4 row Q (the metadata model, `valid_from` / `valid_to`, the L0 defects — including the
> reader rendering `baseline_text`); 0.4 row O (the Living sources view); 0.4 row R (Equal Earth, for
> analytic 4); S05-02 (alpha-3 jurisdictions); S05-01's `ooTimeScope` (Q609) for the point-in-time control.
> **Sequencing:** after 0.4 rows O, Q and R; the wiki reader's version controls exist before the law reader
> shares them.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved.

## 1. The rulings this slice implements — verbatim, by ID

- **Q916** — **(a)** «(a) FTS over versions with `valid_on`, so "what did this say in 2019" works without an
  Article per version.»
- **Q918** — **(a)** «(a) Version selector · side-by-side diff · provision navigation · an ELI/CELEX
  permalink · the licence line · "AI-derived · unreliable" on summaries · translation provenance where
  applicable.» — NOTE (verbatim): «but the UI should be homogenous with other parts of the app's ability to
  track change, such as wikipedia articles, and so forth» [the note adds a requirement: one grammar shared
  with the wiki change surfaces — build the note]
- **Q920** — **(a)** «(a) Summaries only, ≈, "AI-derived · unreliable"; dates, provisions and identifiers
  come from rules, never from the model.»
- Carried by the gate row: **Q107 = (a)** (0.5: the evolution surface); **Q905 = (a)** «Point-in-time
  consolidated versions with `valid_from` / `valid_to` (the legislation.gov.uk and Légifrance model); an
  observed snapshot without official dating becomes a version dated by observation and labelled so.»;
  **Q908 = (a)** «One document identity (CELEX/ELI), N language versions aligned by identity — no ring
  needed; the reader offers the language switch; cross-language search finds it through any version.»;
  **Q914 = (a)** «Confirm the five (1–2 in 0.4 on the small corpus, 3–5 in 0.5).» — 3 cross-jurisdiction
  comparison by topic · 4 an Equal Earth map of amendment activity with the vintage stated · 5 "what
  changed this week in the laws I follow".

## 2. Where this stands in the tree — the staleness guard, with anchors

- `src/law/` holds `adapters/{__init__,clml,diff}.py`, `catalog.py`, `corpus.py`, `coverage.py`,
  `ingest_report.py`, `summarize.py`, `track.py` (grep-verified `ls`). `valid_on` is an adapter field at
  `src/law/adapters/__init__.py:28, 128, 163` and `clml.py:216–224` (grep-verified); `diff_provisions` at
  `src/law/adapters/diff.py:133` has no caller (sheet §10 VERIFIED; grep-verified `def`).
- `LawDocument` at `src/database/models.py:2227` (`jurisdiction` a free `String(8)` at `:2244`),
  `LawRevision` at `:2285`, `LawRevisionSummary` at `:2323` (grep-verified). `LawRevision.full_text` is
  written and never read; diffs run against the immutable baseline; the reader renders `doc.baseline_text`
  at `src/api/law.py:417` (sheet VERIFIED; grep-verified `sed -n '414,419p' src/api/law.py`) — the L0
  defect 0.4 row Q (Q917) fixes; this slice builds on the FIXED reader, never around the defect.
- `src/api/law.py` routes: `/status`, `/documents`, `/changes` (:182), `/track`, `/seed`,
  `/documents/{id}` (:330), `/revisions/{id}/summarize` (:361), `/documents/{id}/view` (:399);
  `src/api/wiki.py`: `/changes` (:217), `/pages/{id}/revisions` (:234) (grep-verified). `index.html` ids:
  `#law-changes`, `#law-docs`, `#wiki-changes`, `#wiki-diff`, `#wiki-tc`, `#wiki-tc-body`,
  `#wiki-tc-method`, `#wiki-tc-flagged` (grep-verified) — the tracked-changes modal Q1016 replaces.
- Corpus state (sheet §10 VERIFIED): 24 documents → 23 `LawDocument` rows on a fresh install (uk 5, tl 6,
  eu 4, de 2, ca 2, int 2, us 1, fr 1); es, ru, ar, zh, ja, hi, bn, id have zero; one adapter (CLML),
  fixture-tested, never run on a fetched document; every priority portal is egress-blocked from the sandbox
  (Q114) — the gate's "one real source" needs the maintainer's machine or 0.4 row V's allowlist.
- AI summaries exist: `src/law/summarize.py`, `LawRevisionSummary`, `tests/test_law_ai_summaries.py`
  (grep-verified) — A5 (auto for UI-language jurisdictions) is shipped per the sheet.
- Tests present: `tests/test_law_reader.py`, `test_law_section_diff.py`, `test_law_clml_adapter.py`,
  `test_law_corpus.py`, `test_law_coverage.py`, `test_wiki_page_revisions.py`, `test_wiki_track.py`.
- 0.4 rows O, Q and R are not in the tree at this brief's writing — verify each landed before building.

## 3. Slices — what to build, in order

### S1 — One change-tracking grammar, the wiki reader first (Q918 + note, Q1016)
- **What:** one shared reader component (the `ooSubtabs` precedent of invariant #18 — one helper, many
  surfaces) giving version selector · side-by-side diff · provision navigation · permalink · licence line ·
  "AI-derived · unreliable" · translation provenance; adopted by the wiki reader's revision/diff surfaces
  AND the law reader; no law-only widget where a wiki one exists; the disclosures identical on both.
- **Acceptance:** both readers drive the same component in the Chromium record ("same controls, same
  disclosures" — the gate's clause); strings ×12 with caveats visible.

### S2 — Point-in-time search (Q916, Q905)
- **What:** FTS over versions with `valid_on`; "what did this say in 2019" through the advanced search's
  `ooTimeScope` control (Q609) without an Article per version; each hit names its version, `valid_from` /
  `valid_to`, and "dated by observation" where no official date exists (Q905).
- **Acceptance:** a law's 2019 text findable on the fixture jurisdiction (0.4 row O) and on one real source
  (operator / allowlist) — the gate's clause; the version-dating label proven by a negation fixture.

### S3 — Identity, permalink, licence, the language switch (Q908, Q918)
- **What:** the ELI/CELEX permalink; the licence line per document (0.4 row Q's Q927 record); one document
  identity with N language versions aligned, the reader's language switch, cross-language search finding
  the document through any version; translation provenance shown where applicable.
- **Acceptance:** a two-language fixture document switches languages and is found from either; a
  one-language document shows no switch and no fabricated translation.

### S4 — AI summaries only, labelled (Q920)
- **What:** summaries ≈ "AI-derived · unreliable" through the existing `summarize.py` path; dates,
  provisions and identifiers from rules, never the model; a missing summary renders as absent.
- **Acceptance:** the label ×12 on every summary; a negative-space fixture with no summary.

### S5 — Analytics 3–5 (Q914)
- **What:** cross-jurisdiction comparison by topic; an Equal Earth map of amendment activity with the
  vintage stated (0.4 row R's seam; alpha-3 keys from S05-02); "what changed this week in the laws I
  follow" from the version rows the user tracks — counts, n, method, never a verdict.
- **Acceptance:** the map states its vintage (the gate's clause); each analytic renders from fixture rows.

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: the
point-in-time fixture (S2) on the fixture jurisdiction; the negative-space lens — a version with no official
date, a document in one language, a document with no summary, a provision missing from a version — each an
honest label or gap, never a blank ≈ or a guessed date; the whole-tree guard set; `node --check` on touched
scripts; the three i18n gates; the Chromium click-through of the law reader's diff beside the wiki reader's
in `en` and `ar`, stamped "Chromium-verified (remote sandbox) · awaiting human UX pass". The real-source
half of S2 is `not-measurable-here` (the portals are egress-blocked).

## 5. Operator steps

1. On the maintainer's machine (or through 0.4 row V's allowlist): fetch one real source's versions and
   prove the 2019 point-in-time search on it → the record (the query, the version returned, its dates).
2. The click-through of both readers and the amendment map (Q1128 = a) → the record on the PR.

## 6. What this slice may not decide

- Q925 ⛔ (the adapter order): no second adapter is chosen — the fixture jurisdiction and the CLML adapter
  that exists are the only inputs.
- Q903 (CONFLICT — subnational post-beta vs from 0.7): nothing subnational here; the 0.7 gate ships around it.
- The shared component's name and API; whether the map of amendment activity is per country only or admin-1
  (Q914 · 4 names a map with a vintage, not the level; S05-05's artifacts would allow admin-1).
- The Living sources view's placement (main tab or Home family — 0.4 row O's open detail, Q1016).

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.5_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every §1 ruling in `docs/ledger/RULINGS_INDEX.md`, updated to the test or PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
