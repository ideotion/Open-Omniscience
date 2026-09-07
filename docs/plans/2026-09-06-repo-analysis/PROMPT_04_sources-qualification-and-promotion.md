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

## 1. State of the tree

> **Re-verified 2026-09-07 against `main`, and most of the "not built" list was stale.** The corrections
> are inline below; the inventory rows carry the same. Read them before planning: four of the seven slices
> turned out to be already shipped in whole or in part.

Built: the auditor (**`src/analytics/source_audit.py`** — not `src/catalog/`), the qualification pass and
its ladder (`src/catalog/qualification.py`), stamps that survive a restore-merge, the
`configs/source_qualification.yml` overlay loader plus its export and merge script, the world-discovery job
and its per-pass ride-along, the Wikipedia-references discovery channel, `external_sources` resolution with
`discovered_via` provenance.

**Also built, contrary to this prompt's first draft:** the discovery-trail surface AND the citations tally
(S6 — `src/discovery/source_trail.py`, both endpoints in `source_management.py`, rendered at
`app-sources.js:437`, covered by `tests/test_source_trail.py`); the qualification cohort hoist (S7's last
bullet — shipped as S5.1 in the 2026-09-02 crash work, `qualification.py:658-692`, cohort frozen once per
run); and the disclosure halves of S4 and S5 (see those slices).

Genuinely not built: the promotion frontier (S2), and — before 2026-09-07 — an ENFORCED clause-(d) skip
(S3: the behaviour was already correct, the guarantee was emergent).

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

> **DONE 2026-09-07, and the premise was wrong.** Driven live before anything was changed: BOTH funnels
> already skipped a disqualified domain — `promote_cited_sources` reported it as `already_a_source: 1` and
> `citation_channel` proposed nothing — because each dedupes against every existing `Source` domain,
> disqualified ones included. The re-trial half needed nothing either: `select_unqualified` filters exactly
> `status == 'unqualified'`, so the ladder is already the only way back.
>
> The real defect was that the guarantee was EMERGENT, not enforced: it rested on a dedup set whose purpose
> is something else, so narrowing that set — precisely the shape S1/B1 would take — would have reopened it
> silently, with no test to notice. The refusal now lives at `_add_candidate`, the one chokepoint every
> channel stages through, and `promote_cited_sources` reports the reason apart from `already_a_source`.
> See `tests/test_discovery_skips_disqualified.py`, which pins both levels and says which is which.

### S4 — B6: the `PATHOLOGY_ABS_FLOOR` calibration

The floor is 0.5; the strongest signal observed in the field was 0.211, so the admission gate's one decisive
criterion **cannot fire**. This is a maintainer decision (keep and say so; lower with a stated new meaning;
or add `high_link_density`, the strongest measured discriminator, as a second differently-shaped criterion).
Whatever B6 rules, the export already carries the full per-source distribution — publish the choice's basis
beside the constant so the next session does not re-derive it. Do not tune a data-safety threshold to make a
number move.

> **Verified 2026-09-07: the publish-the-basis half already ships.** `src/catalog/gates.py:124-134` states in
> the tunable's own `impact` that no source reached the floor on the 2026-08-03 field corpus, that the
> strongest signal was 0.211, and that it is therefore "a rare-catastrophe detector rather than an everyday
> gate". Only the constant itself is open, and that is B6.

### S5 — B7: the recency-windowed re-check

`source_audit`'s chain reads a source's whole stored history, so the six-month re-verification detects a
source that is *broadly* broken and cannot see one that degraded recently against years of good articles.
Adding a window touches `collect_article_stats`, which the audit REPORT shares — so it is its own slice with
its own before/after on both consumers.

> **Verified 2026-09-07: "and that is what its report should say" already ships.** The quality-gates payload
> carries `recheck.scope_note` (`source_management.py:1615`) saying the re-check sees a broadly-broken source
> and not one that degraded recently, and that its value is judging a source admitted on one or two articles
> against a cohort baseline that did not exist then. Only the window is open, and that is B7.

### S6 — The discovery trail and the citations tally — **ALREADY BUILT (verified 2026-09-07)**

> Both rulings are shipped end to end and were mis-recorded as unbuilt. `src/discovery/source_trail.py`
> implements `source_provenance` (channel + the first citing article by `min(created_at)` and its source,
> recomputed from `article_links`) and `source_citation_tally` (qualified / disqualified / pending /
> never-registered as per-class DOMAIN LISTS, so each class is a clickable drill in both directions).
> `TALLY_CAVEAT` carries the both-directions wording verbatim; no key contains `score`/`rating`/`ranking`/
> `grade`. Endpoints at `source_management.py:239,252`; rendered at `app-sources.js:437`; covered by
> `tests/test_source_trail.py`. **Do not rebuild.** The spec below is kept as the record of what was asked:

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

- ~~**`r.samples` for sources is dead**~~ — **DONE 2026-09-07, and it was THREE sites, not one.** The
  defect lives in `src/backup/merge.py` (not `source_management.py`) and affects `sources`, `articles` AND
  `wiki_pages` identically: each sample query runs after its own `_insert_tracked`, with the predicate the
  INSERT has just falsified, so every restore report has always omitted its examples entirely. The four
  `r.conflicts` sites are unaffected — they query rows present on both sides. Fixed by reading back from
  `merged_rows`, which also removes a drift the obvious repair would keep (the `articles` INSERT joins
  `temp.map_sources`, so a restated predicate could name a row the INSERT then skipped).
- ~~**54 duplicate domains → 227 entries unreachable.** Fix the data, add the guard.~~ — **GUARD DONE
  2026-09-07; "fix the data" is the WRONG DIRECTION and is now a maintainer ruling (B11).** Measured: 108 of
  the 227 shadowed entries are in a DIFFERENT language than the surviving sibling. `bbc.com` carries 31
  entries and the 30 that lose are BBC Arabic, Hausa, Swahili, Persian and the rest; `dw.com` shadows DW
  Arabic, Deutsch, Español and Brasil. Deleting them to make the catalogue "clean" would delete exactly the
  multilingual breadth the language-equilibrium work exists to build. `seed_sources` now reports
  `shadowed` apart from `skipped_existing`, and `tests/test_catalog_domain_collisions.py` ratchets the count.
  RECOVERY needs the source-identity ruling (a domain, or a feed) — see B11.
- ~~**A NULL-only backfill migration** for the `country_from_title` recoveries~~ — **NON-ITEM (measured
  2026-09-07): it would migrate nothing.** `country_from_title` recovers **0** of the 1,599 catalogue entries
  that carry no explicit `country`, because the 2026-06-16 batch promoted all 68 `(Country)`-suffix entries
  into explicit fields and `test_catalog_honours_its_own_country_suffix_convention` keeps it that way. The
  real gap it stood in for is broader and unmeasured: **the seeder is create-only, so no catalogue metadata
  improvement — country, language or tags — ever reaches an existing install.** That is the same root cause
  as the tag bullet below, and the safe shape for both is a NULL-only reconcile (fill a local NULL from the
  catalogue, never overwrite a value — the merge's own adoption rule, one level down). Not built here.
- **Retroactive apply of tag edits** to an existing corpus (the seeder is create-only, so the 2026-09-05
  tag batch reaches fresh installs only). This is a reviewed data change: propose, review, apply. Not built.
- **L9/L10 vocabulary hygiene**: remove the `lean-*` scale from the offerable tag vocabulary if L9 says so;
  filter the `via:*` and coverage-state prefixes per L10. **Not built: both are unanswered rulings, and
  `src/ai_layer/source_tags.py` already carries `_NON_TOPICAL_CLASSES` "reported, never filtered" with the
  reason in its own comment — "deciding that `independent` is not a topic is a taxonomy ruling a human
  makes".** The classification exists; only the decision to act on it is missing.
- ~~**The qualification cohort hoist**~~ — **ALREADY BUILT (verified 2026-09-07).** Shipped as S5.1 in the
  2026-09-02 crash work: `run_qualification_pass` takes a `cohort_provider`, freezes the baselines once per
  run (`qualification.py:658-692`) and REFUSES a cohort frozen at a different `min_articles` rather than
  silently judging against the wrong cut. Do not rebuild.

## 3. Operator steps this prompt cannot do

Generating `configs/source_qualification.yml` from real instances (B5); the source-tag canary re-run for the
47 batches that failed it and the 59 domains below the article floor; the source-diversification networked
run; the Wikidata generator run for the 73 named country gaps.

## 4. Scope fence

Do not change what `qualified` MEANS. Do not enable a source in bulk without the ruled gate. Do not build a
composite quality figure. Extraction validity, never editorial merit.
