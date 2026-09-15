# S04-07 — Cross-language search through the rings, everywhere: CJK segmenters, Arabic folding, the literal toggle, per-language counts · 0.4, `RELEASE_0.4_GATE.md` row N

> **Scope:** `src/database/fts.py` (the folding; the tokenizer config and the re-index it implies),
> `src/api/main.py` (`/api/articles`), `src/api/search_omni.py`, `src/api/insights.py` (`_resolve_corpus` and
> the eleven endpoints), a new `resolve_concept`, `src/analytics/equivalence.py` (`QueryExpander`, the cap),
> `src/analytics/watches.py`, `src/bulletin/sections.py` + `annexes.py`, `src/static/app-analysis.js` (the
> toggles, the URL, the mind map), `app-observatory.js` / `app-map.js` / `app-sources.js`, the results list,
> `pyproject.toml` + `configs/external_artifacts.yml` (segmenters), the locales, the tests. Must NOT: build
> the advanced search (R11 → `S05-01`), the language multi-select (Q505 = b → `S05-01`), title / summary
> translation (Q513 → `S05-08`), or the ladder's display helper (`S04-06`, which this slice reads).
> **Implements:** Q417, Q501, Q502, Q503 (note), Q504, Q506 🔒, Q507, Q508 (note), Q509 (note), Q510, Q511
> (note), Q512, Q514, Q515, Q516.
> **Gated on:** `S04-06`'s `translation_tier` (Q514) and its rings member; nothing pending.
> **Sequencing:** after `S04-06`; the re-index (S8) last, as its own PR, never concurrent with `S04-02`'s
> import work on the FTS path.

## 0. Working mode

Read [`_WORKING_MODE.md`](_WORKING_MODE.md) (which points at the 2026-09-06 base) in full, then the gate row
named above, then every ruling in §1 as it stands in `docs/ledger/RULINGS_INDEX.md`, then the answer sheet's
own section for those questions (their verified context and option lists). Grep the tree before building
anything — the sheet's anchors were verified at `main`@`bebcef4` on 2026-09-12 and may have moved. The sheet
sections are §6 (R10) and §5 (Q417); the honesty rules on anti-capping and cross-time recall (base §7) bind
every chip and total here.

## 1. The rulings this slice implements — verbatim, by ID

- **Q417** — **(a)** «Aggregates (rising, trends, top) are computed per RING when the term is in one, with a
  per-language breakdown in the hover; the display shows the UI-language label.»
- **Q501** — **(a)** «Yes: `resolve_concept(term, ui_lang, sense)` computed once per analysis tab and passed
  to both the FTS path and the keyword-keyed aggregates; "only the words I typed" is one toggle persisted in
  the tab seed and the URL.»
- **Q502** — **(a)** «Stacked per language with a legend.»
- **Q503** — **(a)** «Cap at 40 literals, the most frequent first, disclosed as "expanded to 40 of 63
  forms".» — NOTE (verbatim): «but give users the option to deactivate the cap with a toggle / switch,
  activate the cap by default»
- **Q504** — **(a)** «Confirm (`?expand=0`, `?sense=`).»
- **Q506** 🔒 — **(b)** «A segmenter dependency (`jieba` for zh, `sudachipy` for ja).»
- **Q507** — **(a)** «`remove_diacritics=2` + alef/teh-marbuta/yeh folding at index and query time.»
- **Q508** — **(a)** «Interleaved by date, a language chip on every row.» — NOTE (verbatim): «but it should be
  possible to group results by language»
- **Q509** — **(a)** «"climate 120 · climat 45 · Klima 30 · …" — the honest picture of where the concept
  lives.» — NOTE (verbatim): «but add the single total also»
- **Q510** — **(a)** «A watch on "climate" watches the ring»
- **Q511** — **(a)** «Bulletin sections built from keywords use the ring» — NOTE (verbatim): «add all ring
  analytics and details into a new bulletin annexe»
- **Q512** — **(a)** «The ring is the centre node; each language is an arm; associations hang off the arms.»
- **Q514** — **(a)** «Confirm: expansion is ring-verified only; a ≈ translation may display but expands a
  query only when the user opts in per query.»
- **Q515** — **(b)** «Exact, uncapped.»
- **Q516** — **(a)** «Confirm.»

## 2. Where this stands in the tree — the staleness guard, with anchors

- Sheet §6 context (VERIFIED): `ExpandTerms` (`fts.py:170–194`) + `QueryExpander` thread expansion through
  AND/OR/NOT; `expand=false` is the literal escape; wired on two endpoints only (`/api/articles`,
  `main.py:1452–1454`; `/api/search/omni`); `_resolve_corpus` (`insights.py:381`) is literal-only, so eleven
  endpoints know nothing of rings; `expand=false` and sense pins live only in `_articleQuery`
  (`app-analysis.js:1107–1123`) and do not survive a reload; `search_total` re-runs the MATCH uncapped
  (`search_omni.py:110`). FROM MEMORY in the sheet: the FTS5 tokeniser is `unicode61` — grep-confirmed below.
- grep-verified in this brief: `src/database/fts.py:254` `tokenize='unicode61 remove_diacritics 2'` (also
  `src/wiki/dump_index.py:84`) — Q507's `remove_diacritics=2` half is ALREADY in place; the alef /
  teh-marbuta / yeh folding is absent (`grep -rln "marbuta\|alef" src/ --include=*.py` → only
  `src/analytics/extract.py`, whose `_ARABIC_MARKS` `:56–66` handles combining marks in the keyword
  tokenizer; `tests/test_arabic_tokenizer.py` covers those marks only). `_OPERATORS` `:49`, `_quote` `:160`,
  `ExpandTerms` `:173`, `_render_term` `:176` (expansion applies to excludes too, by design).
- grep-verified: `src/api/main.py:1450–1455` `/api/articles` takes `expand: bool = True`, `ui_lang`, `sense`;
  `src/api/search_omni.py:108–111` "search_total takes no cap" — Q515 = b is today's behaviour, to be kept
  and costed; `src/api/insights.py:381` `_resolve_corpus`; the endpoints: `/corpus-keywords` `:742`,
  `/corpus-sources` `:1034`, `/trend` `:1284`, `/trend-articles` `:1295`, `/associations` `:1331`,
  `/keyword-stats` `:1384`, `/context` `:1408`, `/map-coverage` `:1470`, `/who` `:1788`, `/where` `:1816`,
  `/graph` `:2708` (plus `/trending` `:1223`, `/trending-windows` `:1248` for Q417).
  `grep -rn "def resolve_concept" src/` → none: it is new.
- grep-verified: `src/static/app-analysis.js:1105–1123` `_articleQuery` with `_anExpand` / `_anSenses` in
  memory only; the mind map at `:758–782` (`an-mindmap`, "radial, no cross-tangle; never interpolate fake
  structure"). The Observatory reads `/api/insights/observatory` (`app-observatory.js:73`); the map reads
  `/api/insights/map-coverage` (`app-map.js:26`) and `/api/insights/where` (`:730`); the sources tab reads
  `/api/database/coverage` and `/api/database/countries` (`app-sources.js:79–80`).
- grep-verified: `src/analytics/watches.py:20`, `:62–64` — the matcher reuses `search_ids` (FTS5), the SAME
  search the user sees; `evaluate_watches` `:204`; the API `src/api/watches.py`. The bulletin:
  `src/bulletin/sections.py`, `annexes.py` (`bundle_stem` `:121`, `annexes_filename` `:140`), `evidence.py`.
- grep-verified: segmenters today — `pyproject.toml:193–195` `[segmentation]` extra = `jieba` (zh), `janome`
  (ja), `pythainlp` (th), consumed by `src/analytics/segmentation.py` for KEYWORD extraction only, degrading
  to the whitespace tokenizer with zh/ja/th disclosed "unsegmented" (`tests/test_unsegmented_disclosure.py`);
  `sudachipy` appears nowhere; no registry entries for any of them (`grep -n "jieba\|sudachi"
  configs/external_artifacts.yml` → none). Q506 = b names `jieba` + `sudachipy`; the tree carries `janome`
  for ja — recorded in §6, never substituted silently.
- Q1015 = a (cited by the gate row): «Compiled code only in optional extras (`[geo]` = pyosmium); pure Python
  in core (`simplemma`); … every addition registered in `configs/external_artifacts.yml`.» That `sudachipy`
  ships compiled bindings is FROM MEMORY — confirm before placing it. The Q911 note (verbatim, the zh
  emphasis the gate row cites): «but are we enterly missing china ? Also in the UI language ? This must be a
  mistake I made. We should incororate china and chinese support throughout the app. This is important.»
  Tests to extend: `tests/test_corpus_algebra_expand.py`, `test_fts_search.py`, `test_search_omni.py`,
  `test_segmentation.py`, `test_arabic_tokenizer.py`, `test_fts_rebuild_gate.py`.

## 3. Slices — what to build, in order

### S1 — `resolve_concept` once per tab, on both paths; the literal toggle persisted (Q501, Q504)
- **What:** `resolve_concept(term, ui_lang, sense)` computed once per analysis tab and passed to the FTS path
  (`ExpandTerms`) AND to `_resolve_corpus` and the eleven keyword-keyed endpoints (`expand` / `sense` /
  `ui_lang`); "only the words I typed" is ONE toggle persisted in the tab seed and the URL (`?expand=0`,
  `?sense=`), replacing the in-memory `_anExpand` / `_anSenses`.
- **Why (ruling):** Q501 = a; Q504 = a; R10.
- **Acceptance:** the gate's "every analysis tab agrees with the Articles list on the same concept" — a
  recorded comparison on the reference corpus, numbers in the PR.

### S2 — Per-ring aggregates and stacked series (Q417, Q502)
- **What:** rising / trends / top computed per ring when the term is in one, the per-language breakdown in
  the hover, the UI-language label on screen (`S04-06`'s helper); trend series stacked per language with a
  legend through `ooChart` (invariant #16: full resolution, n < 10 → bars, never a thinned series).
- **Why (ruling):** Q417 = a; Q502 = a.

### S3 — The cap and its toggle (Q503 with its note)
- **What:** 40 literals, most frequent first, disclosed as "expanded to 40 of 63 forms" with the REAL counts;
  a user toggle deactivates the cap; the cap is ON by default. The cap bounds the OR fan-out only — never a
  reported number (anti-capping; totals stay exact per Q515).
- **Why (ruling):** Q503 = a as the note amends it. **Acceptance:** a fixture with 63 forms: capped query,
  uncapped query, the disclosure string, identical totals.

### S4 — Results and the chip (Q508 note, Q509 note)
- **What:** results interleaved by date with a language chip on every row AND a group-by-language option; the
  expansion chip shows the per-language counts ("climate 120 · climat 45 · Klima 30 · …") AND the single
  total. Strings ×12. **Why (ruling):** Q508 = a + note; Q509 = a + note.

### S5 — Exact, uncapped totals, costed (Q515 = b)
- **What:** keep `search_total` uncapped; measure the re-run MATCH on the ring-size extremes of the reference
  corpus and publish the timing beside the total (a fact, not a cap) — the gate row: "state the cost".
- **Why (ruling):** Q515 = b.

### S6 — Tentative translations never expand (Q514)
- **What:** expansion is ring-verified only; a ≈ row (`translation_tier` tentative) may display and expands a
  query only on an explicit per-query opt-in that is never persisted as a default.
- **Why (ruling):** Q514 = a. **Acceptance:** negative space — a corpus whose only translation is tentative
  returns literal hits only.

### S7 — Watches, the bulletin and its annexe, the mind map, the same resolution (Q510, Q511, Q512, Q516)
- **What:** `evaluate_watches` passes the expansion so a watch on "climate" watches the ring, disclosed on the
  watch row; bulletin sections built from keywords use the ring; a NEW bulletin annexe carries all ring
  analytics and details (the note) through the annexes bundle; the mind map puts the ring at the centre, one
  arm per language, associations off the arms (the mind-map rules: centre → arms → outward, deterministic,
  no cross-tangle); the Observatory, the map and the sources tab read the same `resolve_concept` output.
- **Why (ruling):** Q510 = a; Q511 = a + note; Q512 = a; Q516 = a.
- **Acceptance:** one fixture per surface; the annexe rendered in the click-through record.

### S8 — CJK segmenters and Arabic folding, then the re-index (Q506 🔒 = b, Q507) — its own PR, last
- **What:** `jieba` (zh) and `sudachipy` (ja) on the FTS index and query path — placed per Q1015 = a (pure
  Python in core, compiled in an optional extra) once the compiled-or-not fact is confirmed, each registered
  in `configs/external_artifacts.yml`; Arabic alef / teh-marbuta / yeh folding applied at index AND query
  time beside the existing `remove_diacritics 2`; the re-index job this implies, resumable and
  task-manager-visible; counts before / after on the fixture and on the reference corpus.
- **Why (ruling):** Q506 = b; Q507 = a; Q1015 = a; the Q911 note's zh emphasis.
- **Acceptance:** the gate's "the CJK and Arabic re-index has run … counts before/after".
- **May not decide:** `sudachipy` versus the tree's `janome` for ja, and the fate of the keyword-extraction
  segmenters (§6).

## 4. Verification

The gates verbatim (`_WORKING_MODE.md` §4), each run separately with its exit code captured. Plus: `node
--check` on every touched `<script>` block; the three i18n gates for every new string (chips, toggles, the
group-by control, the annexe headings); the whole-tree guard set; the recorded comparison of S1 with its
numbers; the CJK / Arabic before-after counts; the Chromium click-through (Q1128 = a) of the literal toggle,
the cap toggle, the group-by control, the sense picker and the chip — in en, fr, ar (RTL), zh, ja; the FTS
rebuild under the skeptic matrix (a data path: negative space — `expand=0` returns ONLY literal hits, a ≈
translation never expands without opt-in, the cap never changes a total, a folded query never matches a
non-Arabic token it did not match before); every guard mutation-checked by name; the numstat rule for the
ledger files. This slice adds no fetch. The real-corpus re-index is an operator step: `not-measurable-here`.

## 5. Operator steps

1. The S1 comparison and the S8 re-index on the maintainer's real corpus (counts before / after; the timing
   published as a measurement). Artifact: the numbers in the PR.
2. The click-through of every control in §4 (Q1128 = a). Artifact: the record under `docs/audit/`.
3. The maintainer's word on `sudachipy` versus `janome` (§6).

## 6. What this slice may not decide

- Q506 = b names `sudachipy` for ja; the tree's `[segmentation]` extra already carries `janome` for ja and
  `pythainlp` for th on the keyword path — whether they stay, move or go is not ruled; nothing is substituted.
- Each segmenter's placement (core vs optional extra) follows Q1015 = a once the compiled-or-not fact is
  confirmed; the Arabic folding mechanism (a custom tokenizer vs a pre-fold at both ends) is the session's,
  with its measurement.
- Whether the cap toggle persists in the tab seed and URL like the literal toggle (Q504 names only
  `?expand=0` and `?sense=`), and how "group by language" composes with the date interleave default.
- The annexe's exact contents; Q505 = b (the multi-select, `S05-01`); Q513 (`S05-08`).
- No ASSUMPTION and no CONFLICT is built on here; no ⛔ question is touched.

## 7. Closeout

- A `shipped.csv` row per PR naming WHICH part of this slice shipped and what remains (binary append, LF).
- The gate row's status in `RELEASE_0.4_GATE.md` §3 (the amendment log), with the artifact that closes it.
- The `where enforced` cell of every ruling in §1 in `docs/ledger/RULINGS_INDEX.md`, updated to the test or
  PR.
- A `docs/ledger/LESSONS.md` entry only where a lesson was earned (with its verbatim `SHIPPED_LOG.md` twin).
- Never a tag, never a merge, never a model identifier in a commit or PR body.
