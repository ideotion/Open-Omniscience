# S04-06 — Keywords in the UI language, "translated from X": the label grammar, the three-tier ladder, auto-loaded rings at 1 / 10 s, lemmatisation, the per-mention language · 0.4, `RELEASE_0.4_GATE.md` row M

> **Scope:** `src/analytics/equivalence.py`, `src/analytics/queries.py` (`_annotate_translations`), the
> keyword endpoints in `src/api/insights.py` and their siblings (`target_lang`), ONE display helper for every
> keyword surface, `src/briefing/producers.py` / `card.py` (`title_vars`) with the `i18n.js:162` note,
> `src/database/models.py` (`KeywordMention.language`; `Keyword.language` as a cache) + a migration,
> `src/analytics/extract.py` and `families.py` (lemmatise at extraction), `pyproject.toml` +
> `configs/external_artifacts.yml` (`simplemma` to core), a new consented in-app Wikidata ring job with its
> Settings surface, `scripts/generate_wikidata_rings.py` (10 s), `src/ai_layer/translate.py` (persist into
> `keyword_translations`), the locales, the tests. Must NOT: merge anything into the stoplists (HELD), build
> search expansion (`S04-07`), the entity ladder (Q415 → `S05-03`), the AI sweep (Q405 → `S05-08`), or the
> `keyword_translations` migration itself (`S04-04` — coordinate).
> **Implements:** Q401, Q402, Q403, Q406 ⛔, Q407, Q408, Q410 (operator), Q411, Q412, Q413, Q414, Q416,
> Q418, Q1103 (CONFLICT, TENSION), Q1104 (CONFLICT).
> **Gated on:** `S04-04`'s `keyword_translations` table; `S04-01`'s host list (the job's hosts); the CONFLICT
> Q1103 / Q1104 is HELD — nothing merges until the maintainer picks.
> **Sequencing:** after `S04-04` and `S04-01`; before `S04-07` (which reads `translation_tier` for Q514).

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved. The sheet
sections are §5 (R7–R9) and §12 (Q1103, Q1104); the `OPEN_QUEUE.md` 2026-09-15 head entry lists the CONFLICT.

## 1. The rulings this slice implements — verbatim, by ID

- **Q401** — **(a)** «The translation is the visible term; a small tag "translated from French" follows it;
  the hover bubble shows the original `climat`, the ring's other members with counts, and the source.»
- **Q402** — **(a)** «The language's name in the UI language ("traduit de l'anglais", "translated from
  Arabic").»
- **Q403** — **(a)** «Confirm.»
- **Q406** ⛔ — **(b)** «Auto-load without review»
- **Q407** — **(a)** «The gap digest: the most frequent untranslated keywords per language first»
- **Q408** — **(a)** «`wbsearchentities` in the term's language, then `wbgetentities` for labels in all twelve
  languages, one item per request, 10 s apart.»
- **Q410** — **(a)** «Regenerate `keyword_rings_generated.yml` on your machine before each tag at the polite
  rate, targeting the top 2,000 keywords per language (≈ 24,000 lookups ≈ 3 days of a background script).»
  [placement: operator ritual before each tag]
- **Q411** — **(a)** «Yes, as a ruled exception to the "data never translates" design: `title_vars` gains
  `term_translation` + `term_lang`; the template reads `"{term_translation}" (translated from {term_lang}:
  {term})`.» [placement: amends the i18n.js:162 design note]
- **Q412** — **(a)** «No single translation: "several senses" + a sense picker; `translate_term` gains the
  refusal path `expand_term` already has.»
- **Q413** — **(a)** «Confirm; the `reconcile_keyword_language` pass runs in the 0.4 gate.»
- **Q414** — **(a)** «Store the language per mention (= the article's language) and derive the keyword's
  language as the majority; the first-write-wins column becomes a cache.»
- **Q416** — **(a)** «Add `simplemma` to the core dependencies; lemmatise at extraction; a migration
  re-normalises existing keywords under a job.»
- **Q418** — **(a)** «Original term · source language · ring members with per-language counts · the QID with
  a LOCAL preview first (invariant #6) · the tier (verified / ≈ tentative).»
- **Q1103** — **(b)** «Never; the shipped stoplists are frozen.» — NOTE (verbatim): «but we will update the
  list as we update the app, there should be a stopword related diagnostic to allow us to optimize the list,
  enlarge it when possible» [CONFLICT with Q1104] [TENSION: the note is the ruling]
- **Q1104** — **(a)** «Yes, through the review surface, batch by batch.» [CONFLICT with Q1103]

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §5 context (VERIFIED): 698 rings / 21,927 members; `equivalence.py`: `ring_of`, `translate_term` (no
  refusal path), `expand_term` (refuses the 91 collisions), `QueryExpander`; three `lru_cache(maxsize=1)`
  loaders, no runtime invalidation; `_annotate_translations` (`queries.py:245–274`) emits `translation` +
  `translation_source="ring"` and no source language; `i18n.js:162`; `Keyword.language` first-write-wins;
  the LLM fallback loopback-only, ≈-marked, a 5,000-entry cache; the generator sleeps 0.2 s; six surfaces
  render a translation, eleven the raw term, seven endpoints accept no `target_lang`.
- grep-verified in this brief: `src/analytics/equivalence.py` — `_PATH` (curated) `:43`, `_GENERATED_PATH`
  `:46`, `load_rings` `:98`, `_index` `:113`, `ring_of` `:136`, `ring_translation` `:162`, `translate_term`
  `:179`, the 91-collision comment `:340`, `_multi_index` `:378`, `ring_matches` `:496`, `expand_term` `:525`,
  `parse_sense_pins` `:599`, `QueryExpander` `:624`; `queries.py:245` `_annotate_translations`;
  `src/static/i18n.js:162` "titles ({title_i18n, title_vars}) whose data (the keyword term) must not
  translate"; cards: `src/briefing/card.py:191` `title_vars` (validated `:228`, `:247`),
  `src/briefing/producers.py:299`, rendered by `app-home.js:1217–1222` through `OOI18N.tf`.
- grep-verified: `src/database/models.py` — `class Keyword` `:1024` with `language String(10)` ("honest NULL
  when unknown"); `class KeywordMention` `:1925` has `country` (`:1947`) and NO `language` column — Q414's
  column is new. `docs/ledger/LESSONS.md:5568`: "`Keyword.language` is first-write-wins
  (`reconcile_keyword_language` is the documented repair and runs only in the re-index cleanup)"; the pass
  lives in `src/analytics/store.py`, exposed at `src/api/insights.py:639–646`.
- grep-verified: `simplemma>=1.1` is ALREADY in `pyproject.toml:147` — in the `[analysis]` extra, used only
  for the OPT-IN display-time conflation in `src/analytics/families.py` (`:39` import, `:174` `_LEMMA_LANGS`
  excludes zh/ja, `:200` `OO_FAMILY_LEMMA`); no entry in `configs/external_artifacts.yml`;
  `tests/test_repo_invariants.py:551–552` asserts the string is in `pyproject`. The sheet's context reads it
  as a new dependency — CONTRADICTED: the delta is core + at-extraction + the migration, not "add".
- grep-verified: `scripts/generate_wikidata_rings.py` — `sleep=0.2` defaults (`:141`, `:273`), `_UA` `:136`,
  `wbsearchentities` `:73`, `wbgetentities` `:81`, ids BATCHED per `wbgetentities` call (`:191–202`), `--top`
  (`:431`, `:436`). The gap digest: `src/api/diagnostics.py:127 _ring_candidates` (bundle key
  `ring_candidates`); a stopword diagnostic ALREADY exists: `:82 _stopword_candidates`
  (`tests/test_stopword_candidates.py`). `configs/stopwords_extra/<lang>.yml` + `PROVENANCE.md`
  (`src/analytics/extract.py:407–415`).
- grep-verified: `src/ai_layer/translate.py` — `lang_name` `:60`, `translate_keyword` `:92`,
  `translate_keywords` `:132`, `_CACHE_MAX = 5000` `:125`. `target_lang` on the insights side today: only
  `/corpus-keywords` (`insights.py:754`, `_tlang` `:1130`). Runtime Wikidata today: `src/catalog/discover.py:
  30–45` (WDQS through `guarded_session`), `src/catalog/wikidata_enrich.py:33` (`www.wikidata.org/w/api.php`).
  Tests to extend: `tests/test_keyword_equivalence.py`, `test_keyword_translation.py`,
  `test_keyword_llm_translate.py`, `test_ring_candidates_digest.py`, `test_wikidata_ring_gen.py`,
  `test_families.py`, `test_ring_ui.py`.

## 3. Slices — what to build, in order

### S1 — The ladder through ONE display helper (Q401, Q402, Q403, Q418)
- **What:** server: `_annotate_translations` gains `translation_source_lang`, `translation_tier`
  (verified / tentative / untranslated) and `senses`; the seven silent endpoints gain `target_lang` (the
  session enumerates them in the PR). Client: one helper renders the translation as the visible term, the
  small "translated from <language name in the UI language>" tag, and the `#oo-tip` hover with Q418's
  contents — the QID through the LOCAL preview first (invariant #6, the `openLinkPreview` path). Untranslated
  terms stay tagged with their language and searchable. The ≈ marker is visible, never behind a toggle.
- **Why (ruling):** Q401 = a; Q402 = a; Q403 = a; Q418 = a; R7.
- **Acceptance:** the gate's click-through across the eleven silent surfaces, each rendering a tier tag.

### S2 — Cards translate the term (Q411)
- **What:** `title_vars` gains `term_translation` + `term_lang`; the template `"{term_translation}"
  (translated from {term_lang}: {term})` ×12; `CardSchemaError` validation extended; the `i18n.js:162` note
  amended in the same change as the ruled exception. **Why (ruling):** Q411 = a.

### S3 — Collisions: several senses and a sense picker (Q412)
- **What:** `translate_term` gains the refusal path `expand_term` has (through `_multi_index`); the surface
  shows "several senses" + a picker on the sense-pin grammar (`parse_sense_pins`). **Why (ruling):** Q412 = a.

### S4 — The source language and the per-mention language (Q413, Q414)
- **What:** `KeywordMention.language` (= the article's language) with a backfill job; `Keyword.language`
  derived as the majority and kept as a cache; the source language of a translation is the ring member's
  effective language; the `reconcile_keyword_language` pass RUNS in this gate — the report is the artifact.
  The column change is coordinated with `S04-04`'s ONE format bump.
- **Why (ruling):** Q413 = a; Q414 = a. **Acceptance:** the reconcile report (CI on the fixture; the
  maintainer on the real corpus).

### S5 — Lemmatisation at extraction (Q416)
- **What:** `simplemma` moves from `[analysis]` to core with its registry entry (Q1015 = a: pure Python in
  core, every addition registered); lemmatise at EXTRACTION, never across languages (`families.py:336`);
  zh/ja stay excluded (`_LEMMA_LANGS`) — disclosed, the segmenters are `S04-07`'s; a resumable,
  task-manager-visible migration job re-normalises existing keywords.
- **Why (ruling):** Q416 = a; Q1015 = a. **Acceptance:** the gate's "`simplemma` is in `pyproject` core with
  its registry entry"; the job's report.

### S6 — Rings auto-load without review (Q406 ⛔ = b, Q407, Q408) — a consented, refusing job
- **What:** a job triggered by the gap digest (`_ring_candidates`), calling `wbsearchentities` in the term's
  language then `wbgetentities` for labels in all twelve languages, one item per request, 10 s apart (R8:
  ≤ 1 request / 10 s), through `guarded_session` with the honest bot UA, task-manager-visible (invariant #20),
  under the ONE online consent (`ensureOnline`), refused under the kill switch with a NAMED refusal, its hosts
  already in `S04-01`'s list and hover (the same diff if any host is new), never Tor → clearnet (Q1014).
  Loaded rings land in a local rings file that rides the backup (Q409 = b, `S04-04`), curated-wins precedence
  as `equivalence.py:45` states; the three cached loaders are invalidated after a load. The gate's design note
  ("from Wikidata, unreviewed", editable in Settings) binds nobody — the DISCLOSURE half follows from the
  honesty non-negotiable (method + caveat, ×12); adopt the rest or write why not.
- **Why (ruling):** Q406 = b; Q407 = a; Q408 = a; R8.
- **Acceptance:** a fixture proving the 10 s spacing and the kill-switch refusal by name.
- **May not decide:** the local file's name and the `maxlag` / UA details option (a) carried (§6).

### S7 — The generator at the polite rate (Q410)
- **What:** `generate_wikidata_rings.py` sleeps 10 s in every mode (the sheet: "changes to 10 s in every
  case"); a documented `--top 2000` per-language invocation; the operator ritual recorded in the release
  notes.
- **Why (ruling):** Q410 = a. **May not decide:** whether the script keeps batching ids per `wbgetentities`
  call under the 10 s rule — Q408 rules the in-app pattern (§6).

### S8 — The stopword DIAGNOSTIC may ship; the merge is HELD (Q1103 note, Q1104)
- **What:** extend and surface `_stopword_candidates` so the list can be optimised and enlarged as the note
  asks — it decides nothing and merges nothing into `configs/stopwords_extra`. No batch through the review
  surface until the maintainer picks between Q1103 = b and Q1104 = a.
- **Why (ruling):** the gate row ("the stopword DIAGNOSTIC the note asks for may ship (it decides nothing)").

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: `node
--check` on every touched `<script>` block; the three i18n gates for every new string — the 12 × 12 language
names of Q402 included (the sheet says they exist in the locale files: confirm); the whole-tree guard set;
the Chromium click-through (Q1128 = a) of every keyword surface — Home cards, Insights rising / trending /
top, the analysis window subtabs, search rows, the mind map, the Observatory labels, the bulletin — in en, fr,
ar (RTL), zh; the 10 s + kill-switch fixture; the `simplemma` core + registry assertion; the reconcile report;
the schema change under the skeptic matrix (negative space: a lemma never merges across languages; an
untranslated term is never shown as translated; a tentative row never reads "verified"); every guard
mutation-checked by name; the numstat rule for the ledger files.

## 5. Operator steps

1. Regenerate `keyword_rings_generated.yml` on the maintainer's machine before each tag, at the polite rate,
   top 2,000 per language (Q410). Artifact: the regenerated file + the run log, noted in the release notes.
2. The `reconcile_keyword_language` pass and the lemmatisation migration job on the real corpus. Artifact:
   both reports.
3. The click-through of every surface in §4 (Q1128 = a). Artifact: the record under `docs/audit/`.
4. The maintainer's pick on the Q1103 / Q1104 CONFLICT — recorded in `OPEN_QUEUE.md` in the turn it is given.

## 6. What this slice may not decide

- The CONFLICT Q1103 = b (frozen; the note wants a diagnostic and per-release growth) vs Q1104 = a (batch by
  batch through the review surface): recorded as given, both sides; nothing merges.
- The local rings file's name and location, the ring-version precedence (`S04-04`'s design note), and the
  `maxlag=5` / bot-UA details that only option (a) of Q406 spelled out.
- Whether the operator generator keeps batching ids per call under the 10 s rule.
- The identity of the seven endpoints and the eleven surfaces — the sheet gives counts, not lists.
- Q415 (entities, `S05-03`), Q405 (the AI sweep, `S05-08`), Q404's table (`S04-04`).
- No ASSUMPTION is built on here; Q406 ⛔ was answered (b) and is built as such.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or
  PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
