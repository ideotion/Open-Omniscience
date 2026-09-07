# Prompt 05 — Keyword engine quality: stoplists, quarantine, fingerprints, the review loop

> **Scope:** `src/analytics/` (extraction, store, rollups), `configs/stopwords_*`, the keyword review loop.
> **Gated on:** B2 (the formal stoplist ruling), B3, B4, PRH-13. Everything else proceeds.
> **Sequencing:** independent. Its S3 shares a data-safety boundary with prompt 07 — do not run both at once.

## 0. Working mode

Read `_WORKING_MODE.md`. Then the CLAUDE.md **stoplist-architecture** lesson, the **open-class garbage**
lesson, and the 2026-09-05 keyword-triage entries. Then
`docs/design/KEYWORD_ENGINE_OPTIMIZATION_STRATEGY.md`.

The stoplist architecture has a correction that has already misled once and is recorded as such:
`configs/stopwords_extra/<lang>.yml` is the **GLOBAL** channel — `global_stopwords()` unions every file in
that directory regardless of language, and the per-language filenames are a readability convenience. The
scoped channel is the vendored `configs/stopwords_iso/<lang>.txt` plus the in-code
`CURATED_SCOPED_STOPWORDS` and `PUBLISHING_BOILERPLATE_SCOPED`. `en` and `fr` cannot reach the scoped channel
at all, so any English or French addition is necessarily global and owes cross-language review.

## 1. Slices

### S1 — B2: the formal stoplist ruling, then the batches

The (1)-vs-(2) ruling (a versioned per-language stoplist derived into the repo once and reviewed, versus an
auto-updating one) has a recommendation on record: **(1)**, because a stoplist entry is applied at both ends
— query-time hiding, reversible; and index-time exclusion, recoverable only by a full re-index — so an
auto-updating stoplist is a partially irreversible corpus-wide deletion with no UI presence, it makes two
instances holding the same articles disagree, and it is a poisoning vector.

Once ruled, the batches waiting on it:
- **B3:** English 11,263 and French 881 triage proposals, as a global-channel batch with cross-language
  review. The 2026-09-05 review measured what these lists actually contain — roughly 10% site chrome, 40%
  inflected verbs and adjectives, 27% real content nouns, 20% phrase fragments, 3% genuine function-word
  gaps — so the batch is a hand-reviewed subset, never a merge.
- **B4:** the 64,910 `kind_overrides` proposals. A 25-item sample showed roughly 50% precision (roles as
  persons, common nouns as orgs, adjectives as persons, mis-languaged rows). Treat as a worklist, never a
  patch.
- **zh/ja/th (611 terms)** wait on the `[segmentation]` extra plus a re-index — the tokens in the log are
  mark fragments and un-segmented run-ons, so an entry made now is pinned to a tokenizer failure mode.
- **PRH-13:** the platform-name ruling (`facebook`/`twitter`, `comments`/`follow`) — dual-use, never ruled.
- **PRH-11:** record the four deliberately-omitted cross-language collisions (`sea`, `tom`, `fin`, `laut`)
  where a future batch will read them; the refusal is reasoned and currently lives only in a PR body.
- **PRH-15:** per-source boilerplate flags (the Pluralistic `yrsago` / `permalink` / `ISSN` case) — a
  source-scoped furniture channel, distinct from the language-scoped stoplist and collision-free by
  construction.

### S2 — PRH-01: `backfill_corpus` has no cursor

`src/analytics/store.py` selects unindexed articles ordered by id with a limit. An article that legitimately
yields **zero terms** stays unindexed forever and occupies the front of the queue on every call — the exact
livelock shape the 2026-07-23 qualification fix already taught this codebase, one subsystem over. A
reproducer exists at `scripts/analysis/repro_backfill_wedge.py`.

The fix is the same family: record the attempt distinctly from a verdict, and order by least-recently-tried
rather than by insertion order, so a structurally-unresolvable row rotates out of the way after one try.
Reproduce the wedge live before trusting the fix.

### S3 — PRH-06: the quarantine filter reaches three modules and not the other three

`src/analytics/queries.py` has nine `quarantined` references. `store.py`, `rollup_serve.py` and
`columnar.py` have **zero**, so every keyword aggregate served from the counters, the rollup or the columnar
store counts quarantined articles. `corpus_language_shares` and the per-language growth feed are in the same
position and the two must move together — that is recorded in a docstring.

This changes published figures. Do it as one slice with one disclosure, not scattered; and check what a
changed denominator does to `furniture_share`, which feeds the qualification gate (that coupling is why the
2026-08 pass deliberately left it alone).

### S4 — PRH-05: `extract_locations` is O(entries × text)

`src/timemap/locextract.py` runs `finditer` over the whole text once per gazetteer entry — roughly 4,700
compiled patterns, measured at 2,558 ms per article on a 4,500-city gazetteer. It only bites installs that
ran `build_city_gazetteer.py`, which is why it has survived. The rewrite touches case-sensitivity semantics
(cities match case-sensitively, countries do not) and the longest-match-consumes-the-span rule, so it needs a
differential test against the current implementation over a corpus of real article bodies before and after.

### S5 — The review loop the analyzer was built for

`analyze_keyword_log.py --generic-terms` proposes; nothing consumes proposals in-app. Build the S4 panel from
the 2026-07-22 plan: review-and-apply for `generic_terms`, ring candidates and mis-tagged entities, as a
reviewed batch that lands as a config change. Propose, never auto-apply — that is the standing rule and it is
what makes the whole channel safe.

### S6 — Skeleton fingerprint persistence

`src/analytics/skeleton.py` holds a pure, tested core (`skeleton_fingerprint`, MinHash clustering, the
LCS-ratio ordered comparator, the `skeleton_echo` producer assembly) with no persistence and no live wiring.
It was gated on the triage cleanup, and that gate has lifted. Persist fingerprints (schema + migration +
backfill) and wire the producer. It fires on structural repetition across ≥3 sources and must refuse a text
near-dup, which is `echo_chamber`'s job — the negative-space test is that a wire republish produces nothing
here.

### S7 — The measurement-gated tail (record, do not force)

`P5.2` static-embedding recall (model2vec + sqlite-vec + RRF, labelled and disposable), `P6` entity→QID via
OpenTapioca, and the BM25F default weights all wait on a **human-graded gold set** over the maintainer's own
corpus. The builder is one click away in Settings → Diagnostics and grading is roughly ten minutes. If the
gold set has not been graded, say so and stop — picking weights without it would be the fabricated-pass shape.

## 2. Scope fence

No cap on keyword capture, ever — the standing ruling is explicit and the measured junk share (~6% of
mentions) is what makes capping worthless anyway. No composite score. Never globalise a word that is content
in another language without the cross-language check.
