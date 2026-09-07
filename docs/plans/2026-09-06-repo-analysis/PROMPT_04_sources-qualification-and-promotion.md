# Prompt 04 — Source qualification, the promotion frontier, and the discovery trail

> **Scope:** `src/catalog/`, `src/discovery/`, `src/api/source_management.py`, the qualification lifecycle.
> **Gated on:** B1 ⛔, B6, B7, L9, L10. B1 blocks S1 only; everything else can proceed.
> **Sequencing:** after prompt 01. This is the largest genuinely-unbuilt backend area in the repository.

## 0. Working mode

Read `_WORKING_MODE.md`. Then the CLAUDE.md entries: **"SOURCE-MANAGEMENT ASKS"** (2026-07-20, with its
amendment ruling the qualification lifecycle), **"QUALIFICATION ACCUMULATES ACROSS INSTALLS"** (2026-09-04),
and the **"OMNIBUS SESSION RULINGS"** Q3a/Q4a. Then `docs/design/ACTION_PLAN_2026-07-13_SOURCES_MAPS_GAPS.md`.

The lifecycle's *rulings* are complete and unusually detailed. What is missing is the frontier that connects
them: a source can be judged, and a judged source can be adopted from a backup or a catalog overlay, but
nothing moves a candidate through trial into collection.

## 1. State of the tree, verified 2026-09-06

Built: the auditor (`src/catalog/source_audit.py`), the qualification pass and its ladder
(`src/catalog/qualification.py`), stamps that survive a restore-merge, the `configs/source_qualification.yml`
overlay loader plus its export and merge script, the world-discovery job and its per-pass ride-along, the
Wikipedia-references discovery channel, `external_sources` resolution with `discovered_via` provenance.

Not built: the promotion frontier; the discovery-trail surface; the citations tally; the clause-(d) skip.

## 2. Slices

### S1 — ⛔ B1: the `enabled` vs `qualified` split

`select_unqualified` (`src/catalog/qualification.py`) has **no `enabled` filter**, `evaluate_and_stamp` never
writes `enabled`, and the runner requires **both** `enabled=True` and `status == qualified`. So today roughly
42,000 disabled discovery and cited candidates are trial-fetched over Tor for a verdict that can have no
collection effect, and a successful verdict on a discovered candidate is thrown away.

Under B1(a): add the `enabled` filter and give candidates their own enable step. Under B1(b): let a
`qualified` verdict flip `enabled`, which makes qualification itself the Phase-2 promotion mechanism —
consistent with the 2026-07-20 ruling that qualification IS the admission gate, and a real Tor-bandwidth
decision at 42k rows. Whichever is ruled, the other direction must be impossible by construction, with a test
that says so.

### S2 — The Phase-2 promotion frontier

Candidate → **trial** → graduated, with the auditor as the graduation gate. Additive `SourceCandidate` state
columns and a migration (random 12-hex revision id, confirmed free by grep; head read from
`python -m alembic heads`, never a regex scan of the versions directory). Trial-enable is a network action
and passes the one consent. Diversity-weighted selection. An audit view and an undo.

This is migration-heavy state-machine work: build it as its own stack of small draft PRs, and if the session
runs short, **park it whole** rather than landing half a migration.

### S3 — Ruling clause (d): the funnels must skip disqualified domains

The 2026-07-20 ruling says a re-import or a fresh citation of a disqualified domain must never re-register or
re-trial it. The never-re-CREATE half comes free from the alias-aware dedup as long as rows persist. The skip
half — the citation and discovery funnels declining to re-propose a disqualified domain — is **not wired**.
It is a known deliberate gap recorded in PR #732 and nowhere else.

Negative-space test: a disqualified domain cited by three fresh articles produces zero candidates, and a
`qualified` and an `unqualified` domain in the same batch still do.

### S4 — B6: the `PATHOLOGY_ABS_FLOOR` calibration

The floor is 0.5; the strongest signal observed in the field was 0.211, so the admission gate's one decisive
criterion **cannot fire**. This is a maintainer decision (keep and say so; lower with a stated new meaning;
or add `high_link_density`, the strongest measured discriminator, as a second differently-shaped criterion).
Whatever B6 rules, the export already carries the full per-source distribution — publish the choice's basis
beside the constant so the next session does not re-derive it. Do not tune a data-safety threshold to make a
number move.

### S5 — B7: the recency-windowed re-check

`source_audit`'s chain reads a source's whole stored history, so the six-month re-verification detects a
source that is *broadly* broken and cannot see one that degraded recently against years of good articles.
The re-check's honest claim today is the cold-start firming, and that is what its report should say. Adding a
window touches `collect_article_stats`, which the audit REPORT shares — so it is its own slice with its own
before/after on both consumers.

### S6 — The discovery trail and the citations tally

Both are 2026-07-20 rulings with no surface:

- **Trail:** per source, where it was first discovered — the first citing article (`min(created_at)` among
  citers) and its source, click-through to the local reader and to that source's row. Channel-appropriate:
  a catalog or wikidata source shows channel and evidence instead.
- **Tally:** of this source's cited domains, how many are qualified / disqualified / pending /
  never-registered (filtered as commerce, social or infrastructure). Show the **tally with n**, not a
  percentage badge; the long form goes in the hover. The denominator is domains that entered the funnel —
  raw cited domains include masses of legitimate non-article links. Each class drills to the list, and each
  row drills to the citing articles.
  **Both directions carry the same caveat:** citing a disqualified domain is not guilt (disqualification is
  extraction validity, never editorial merit), and citing many qualified ones is not endorsement — a
  laundering hub can cite reputable sources deliberately. No field name may contain `score`, `rating`,
  `ranking` or `grade`.

### S7 — Small, verified, and each its own commit

- **`r.samples` for sources is dead**: the sample query runs after the INSERT so its `NOT EXISTS` is never
  true and the list is always empty (PR #915).
- **54 duplicate domains → 227 of 3,429 `configs/sources.yml` entries are unreachable** by the create-only
  seeder. Fix the data, add the guard.
- **A NULL-only backfill migration** so existing installs pick up the `country_from_title` source-country
  recoveries — the fix is forward-only today.
- **Retroactive apply of tag edits** to an existing corpus (the seeder is create-only, so the 2026-09-05
  tag batch reaches fresh installs only). This is a reviewed data change: propose, review, apply.
- **L9/L10 vocabulary hygiene**: remove the `lean-*` scale from the offerable tag vocabulary if L9 says so;
  filter the `via:*` and coverage-state prefixes per L10.
- **The qualification cohort hoist** — `per_source_metrics` → `collect_article_stats` is O(corpus) **per
  batch**, so `qualification_per_pass` (default 5) cannot make it cheaper and lowering it saves nothing.
  Hoist the cohort baselines out of the batch loop into a per-RUN computation. This was deliberately not
  built on 2026-07-23 because it changes the verdict path immediately before an unattended run; that reason
  has expired, but the full skeptic matrix has not.

## 3. Operator steps this prompt cannot do

Generating `configs/source_qualification.yml` from real instances (B5); the source-tag canary re-run for the
47 batches that failed it and the 59 domains below the article floor; the source-diversification networked
run; the Wikidata generator run for the 73 named country gaps.

## 4. Scope fence

Do not change what `qualified` MEANS. Do not enable a source in bulk without the ruled gate. Do not build a
composite quality figure. Extraction validity, never editorial merit.
