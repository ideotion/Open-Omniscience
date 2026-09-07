> **SUPERSEDED (2026-09-07) — kept as the record of how the criterion was proposed, not as status.**
> Everything this note proposes as hypothetical has since shipped, so its "scaffold only / dry-run / not
> wired into the app" description of the mechanism is now false. Re-verified against `main`:
> `Article.quarantined` / `quarantine_reason` / `quarantined_at` are real nullable columns
> (`src/database/models.py`), reversible by design, with `quarantined=NULL` reading as "never judged";
> `src/analytics/quarantine_job.py:...candidates_batch` carries the `write: bool = False` parameter,
> where `write=True` idempotently STAMPS each detected candidate; and `src/api/quarantine.py` exposes
> it. The proposed *sequencing* (discuss → agree → execute) became **row 5 of the 0.3 close gate**, which
> is where its live status lives: Tier A (8 articles, criteria version `nav-soup-v2`) was agreed
> 2026-08-23 and the pass itself is the maintainer's operator step. Read
> [`docs/product/RELEASE_0.3_GATE.md`](../product/RELEASE_0.3_GATE.md) for what remains; read this file
> only for the reasoning behind the criterion.

# NAV-SOUP retroactive quarantine — sequencing draft (proposal, not a build spec)

Status: **draft note only**. Nothing here is executed or scheduled. It proposes how the
maintainer might sequence discuss -> agree -> execute for the row-5 cleanup the NAV-SOUP SPECIMEN
ruling (2026-07-20) names, using this session's new detection criterion as the input evidence.

## What changed this session (the evidence)

- `src/services/prose_gate.py` — a new function-word-density / sentence-punctuation criterion
  ("the PROSE GATE"), closing the recall gap where a word-rich nav/menu page (>= 100 extracted
  words) cleared the ingest filter's load-bearing body-length guard.
- Wired into `src/ingest/non_article.py` (the door gate, forward-looking) and, opt-in, into
  `src/analytics/non_article_scan.py`'s existing retroactive scan (`include_prose_gate=True`) as a
  bounded, resumable, content-decrypting subpass — detection only, no removal.
- `src/analytics/quarantine_job.py` — a resumable job-manager SCAFFOLD (mirrors
  `ReindexJobManager`'s chassis) that COULD carry out a retroactive quarantine, but today only
  detects and tallies (dry-run; no DB write; not wired into the app).

## Proposed sequencing

1. **Discuss** — run `scan_non_article_candidates(session, include_prose_gate=True)` in bounded
   batches (`prose_gate_limit`/`prose_gate_after_id`) across the corpus (or a representative
   sample first) and bring the maintainer real numbers: total flagged by URL-shape vs. newly
   flagged by the prose gate, `by_reason` breakdown, and a spot-check of the bounded `sample_ids`
   for both passes. This is the evidence base — no action yet.
2. **Agree** — with real numbers in hand, the maintainer decides: (a) the quarantine mechanism
   itself (a nullable `quarantined`/`quarantine_reason`/`quarantined_at` column on `Article`, an
   additive migration, mirroring `Source.enabled`'s reversible flag-not-delete pattern), and (b)
   the threshold/scope for a first pass (e.g. URL-shape only first, since it is the more mature,
   longer-tested signal; prose-gate nav-soup as a fast-follow once its false-positive rate has
   been spot-checked against a larger sample than this session's synthetic fixtures).
3. **Execute** — only after (2): add the migration, wire a REAL write step into
   `QuarantineJobManager`'s `_work_fn` seam (idempotent: a no-op if the row is already
   quarantined), run it via the existing pausable/resumable chassis, and expose it in `/api/jobs`
   only at that point — never before. Quarantine, not deletion: the row stays, reversible, exactly
   like a demoted `Source`.

## Explicitly out of scope for this session

No migration was added, no `quarantined` column exists, no write path was wired, and
`QuarantineJobManager` has no singleton/getter and is not imported anywhere in `src/api/`. This
document is the sequencing proposal only — it does not authorize step 3.
