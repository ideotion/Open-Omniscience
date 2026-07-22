> **Status update (2026-07-22, docs-audit remediation pass):** verified against live `main` by a subagent fan-out audit of the whole `docs/design/` tree — S1 (the `KeywordTag` model), S2 (positive baseline data files), and S3 (the explore/hide/tag Settings subtab) are confirmed SHIPPED. Two items remain genuinely open: Q3/S1b (migrating `_EXTRA_STOPWORD_TEXT` from a Python string blob into per-language data files) and S4 (an in-app one-click apply of the offline analyzer's proposed stopword/ring/mistag candidates) — this doc should NOT be archived yet on account of those two. See [`ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md`](./ACTION_PLAN_2026-07-22_DESIGN_AUDIT_REMEDIATION.md) for the full remediation plan.

# Item AC — Pre-tagged per-language keyword baseline + keyword-management subtab

> **Status: DESIGN (kicked off 2026-06-16, maintainer-asked "kick off the Item AC
> design").** Not built. This document is the architecture + the decisions to
> settle before implementation. It is grounded in the code as it stands after the
> 2026-06-16 keyword batch (analyzer #279, equivalence rings #281, entity-detection
> #283, log-diff #285, plural merge #286).

## 1. Motivation (the maintainer's words)

> "We've tried to optimize by pre-computing a preliminary, **pretagged**, list of
> keywords **in each language** to allow the app to use it as a **baseline**, and
> avoid stupid keyword collection such as 'that'. … allow the logging system to
> create manageable documents that you can ingest … always think of better
> analytics tools."

Two intertwined asks:

- **A. A pre-tagged per-language keyword BASELINE** the extractor consults — both a
  *negative* baseline (don't collect junk like "that") and a *positive* one
  (known keywords arrive pre-classified, a quality reference).
- **B. A keyword-management Settings SUBTAB** to explore / add / remove / **tag**
  keywords per language / tag / family — the human-review surface that the
  analyzer's proposals feed into, closing the optimization loop *inside the app*.

## 2. What already exists (so we extend, never duplicate)

| Capability | Where | Note |
|---|---|---|
| Negative baseline (function words) | `src/analytics/extract.py:_EXTRA_STOPWORD_TEXT` + `src/services/stopwords.py`; unioned by `global_stopwords()` | a **Python string blob**, evidence-grown from logs; applied at index *and* query time |
| Entity vs term, language | `Keyword.is_entity` / `entity_type` / `language` (`src/database/models.py`) | `kind` is now acronym-or-gazetteer (post #283); `language` is honest-NULL when unknown |
| Family merge/split (user) | `KeywordFamilyOverride` + `/api/insights/family/{merge,split,overrides}` (`src/api/insights.py`) | the reversible override mechanism |
| Super-groups (user) | `KeywordSuperGroup(Member)` + `/api/insights/supergroups`; seeded from `configs/keyword_supergroups.yml` | curated-seed-then-user-owns pattern |
| User exclusions (hide) | `src/analytics/filters.py:hidden_set()` (Settings → Keyword filtering) | the per-user "stupid keyword" list |
| Cross-language rings | `configs/keyword_equivalents.yml` + `src/analytics/equivalence.py` | curated language-qualified concept merging |
| The optimization LOOP | `scripts/analyze_keyword_log.py` (+ `--baseline` diff) + `GET /api/diagnostics/keywords` | proposes stopwords / rings / mistags; measures impact between logs |

**Curated-seed-then-user-owns** (supergroups, rings, stoplists) is the established,
honest pattern. Item AC adds **tags** as a new axis on that same spine.

## 3. Component A — the pre-tagged per-language baseline

### A.1 Two baselines, one file family

1. **Negative (exclude).** Formalize the per-language stoplists into **data files**
   (`configs/keyword_baseline/<lang>.yml`) instead of the Python blob. Same content,
   but: (a) the analyzer can WRITE proposed additions (closing the loop), (b)
   per-language ownership is explicit, (c) a freshness/coverage test like the
   catalog. The blob stays as the loader's fallback during migration.
2. **Positive (pre-tag).** A per-language list of known keywords carrying a **tag**
   (semantic type and/or topic), so a keyword that matches arrives pre-classified:
   `election → {type: event, topic: politics}`, `inflation → {topic: economy}`,
   `covid-19 → {type: disease, topic: health}`.

### A.2 What a "tag" is (OPEN — see §6 Q2)

Tags are a **new analytical axis**, distinct from `kind` (term/acronym/gazetteer):
- **Semantic type** (the maintainer's Wikidata-P31 idea): event · disease ·
  technology · currency · treaty · organization-type … (richer than person/org/place).
- **Topic / domain**: politics · economy · health · science · climate · sport …

Both are useful and orthogonal; the design allows **multiple tags per keyword** so
we needn't choose one axis. A tag is a **labelled assertion** (`source: baseline` |
`user`), never ground truth, never a score, always user-overridable.

### A.3 Sourcing the positive baseline (OPEN — see §6 Q1)

Local-first forbids a live dependency. Candidates, with trade-offs:
- **Curated-small** (hand-built like supergroups): honest, tiny coverage, slow to grow.
- **Wikidata-P31 offline snapshot** (dated, generated on a networked machine like the
  de-US-centring run): rich + multilingual + sourced, but large + a generation step +
  licensing (CC0 — fine).
- **Bundled public lexicon** per language: medium coverage, licensing/size to vet.

Recommendation: **start curated-small + analyzer-grown**, design the file format so a
Wikidata-snapshot importer can later populate it without schema change. The diff tool
measures whether each baseline batch actually improved tagging coverage.

### A.4 Application & honesty

- **At index time** (`src/analytics/store.py:index_article`): when a keyword is
  created/updated, if its `(language, normalized)` is in the baseline, attach the
  tag(s) with `source="baseline:vX"`. Retroactive re-index applies it to existing
  rows (the established hook). Forward-only is the cheap first slice.
- A baseline tag is **overridable**: a user add/remove writes a `user` tag row that
  wins. No composite score; counts only. The tag's provenance is visible (hover
  bubble, invariant #17). `OO_KEYWORD_TAGS=0` disables, missing file = no-op.

## 4. Data model

A dedicated association table keeps tags queryable + provenance-carrying (preferred
over a CSV column on `Keyword`):

```
keyword_tags
  id            PK
  normalized    str      # the keyword's normalized_term (language-qualified below)
  language      str|None # so fr:élection and en:election can tag independently
  tag           str      # "politics" | "disease" | ...
  axis          str      # "topic" | "type"
  source        str      # "baseline:v1" | "user"
  created_at    datetime
  UNIQUE(normalized, language, tag, axis, source)
```

Reads join on `(normalized, language)`; a `user` row shadows a `baseline` row for the
same `(normalized, language, tag, axis)`. (Mirrors how `KeywordFamilyOverride` is
authoritative over auto-families.) Migration adds the table only — additive.

## 5. Component B — the keyword-management Settings subtab

A **Settings → Keywords** subtab (invariant #18 `ooSubtabs`; invariant #8
content-vs-plumbing: curation belongs in Settings) that unifies today's scattered
curation and adds tagging:

- **Explore**: a filterable keyword list — by language · kind · **tag** · family ·
  source · hidden — with real counts (mentions / articles / #languages), method +
  caveats visible, NO score. Paged/bounded (62k+ keywords ⇒ server-side filter, never
  ship all).
- **Act** (per keyword or multi-select): hide/unhide (→ the existing exclusion list);
  **tag/untag** (→ `keyword_tags` user rows); merge/split family (→ the existing
  override endpoints); add to a super-group (existing). All reversible.
- **Review the loop** (the payoff): surface the analyzer's proposals —
  stopword candidates, ring candidates, mistagged-entity suspects — for **one-click
  review + apply**, so the maintainer no longer hand-edits `_EXTRA_STOPWORD_TEXT`. The
  export-log button already exists; this adds the *apply* half in-app.

Constraints: ×12 i18n (every string), informed-consent layering, **local-only** (no
network for curation — nothing here phones home), honest empty states, no fabricated
counts.

## 6. Open questions for the maintainer

1. **Positive-baseline sourcing** — curated-small + analyzer-grown (my lean), a dated
   Wikidata-P31 offline snapshot, or a bundled per-language lexicon?
2. **Tag taxonomy** — semantic **type** (P31-like), **topic/domain**, or both axes
   (my lean: allow both, multi-tag)?
3. **Move the stoplists to data files** now (analyzer-writable) or keep the Python
   blob and only add the positive baseline?
4. **Subtab scope for the first slice** — read-only explorer first, or ship explore +
   the hide/tag actions together?
5. **Retroactive tagging** — re-index to apply baseline tags to existing rows, or
   forward-only first (cheaper)?
6. **Where tags surface beyond Settings** — a tag facet in the analysis window /
   trends? (out of scope for the first slices; recorded.)

## 7. Build slices (one PR each, after the questions are answered)

- **S1 — schema + loader** (backend): `keyword_tags` table + migration; baseline file
  format + a network-free loader; index-time application with provenance;
  `OO_KEYWORD_TAGS` switch; tests. No UI.
- **S2 — baseline data**: the first per-language positive baseline (sourced per Q1),
  dated + a freshness/coverage test; the diff tool measures tagging coverage gained.
- **S3 — the subtab**: Settings → Keywords explorer + filters + hide/tag/family/
  supergroup actions, reusing existing endpoints + new tag endpoints; ×12 i18n; tests
  (+ `test_ui_invariants`).
- **S4 — in-app loop**: surface analyzer proposals (stopword/ring/mistag) for
  one-click review/apply — the human-review surface the maintainer asked for.

## 8. Honesty ledger (binding)

- Tags are **labelled assertions** (`source`), overridable, never ground truth, never
  a score (`assert_no_score_fields` discipline carries to tags).
- **Local-only**; the baseline ships bundled + dated; no curation step touches the
  network; zero-network boot preserved.
- Reversible everywhere (user rows shadow baseline; `OO_KEYWORD_TAGS=0`; split/hide
  already reversible).
- Caveats + provenance **visible by default** (invariant #23 / #17), ×12 locales.
- The negative baseline keeps the existing rule: **no cap on keyword counts**; the
  exception policy (stoplists) is the instrument, grown from evidence (the logs).
