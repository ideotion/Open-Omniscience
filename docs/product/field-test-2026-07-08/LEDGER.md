# Field-Test Ledger — 2026-07-08 session

**Mode: CAPTURE-ONLY.** The maintainer is live-testing a build and streaming
feedback; a **parallel session owns implementation on `0.1`**. This ledger is
verbatim observation + code-grounded mapping + a concrete fix plan for **later
autonomous live-coding sessions**. **No code changes are made here** (beyond this
notes file). Load-bearing rulings will be folded into `CLAUDE.md`'s Open queue at
session end, against a freshly-fetched `0.1` tip, to avoid clobbering the parallel
session.

Legend: **[NEW]** net-new · **[PLANNED]** already ruled/known · ✅ shipped ·
⏭ remaining · 🔍 needs live verification on a networked machine.

---

## Item 1 — Indices board is empty on most continents; OECD-tagged indices never show; want many more indices, properly tagged  [NEW / partly PLANNED]  ⏭

**Verbatim:** "In the indice tab, there is no data for Africa subtab, Asia only
has the Nikkei, Europe and oceania are also empty, South America is empty, and
North America should also have non US indices. We should have as much indices as
possible, and they should be properly tagged. For example, there is an "oecd" tag,
but currently no indice is tagged with it."

### Root cause (high confidence — the malformed FRED country code)

The catalog **already** contains all-continent indices, and they **are** tagged
`oecd`. The board is empty because those feeds **fail to import**, so they have no
stored `CommodityPrice` and render as empty cards / empty family graphs.

**The bug:** in `configs/index_feeds.yml`, every OECD entry's FRED series id uses a
**3-letter ISO country code**, but FRED's `SPASTT01<CC>M661N` share-price family
uses a **2-letter code**. Confirmed live via search — real FRED series are
`SPASTT01USM661N` (US), `SPASTT01CNM661N` (China), `SPASTT01ESM661N` (Spain),
`SPASTT01KRM661N` (Korea). The catalog has `SPASTT01DEUM661N`, `SPASTT01CHNM661N`,
`SPASTT01ESPM661N`, `SPASTT01KORM661N` — all wrong. Every such URL 404s / returns
no rows → `import_due_feeds` records a `failed` tally → no data point stored.

This maps **exactly** onto the observed board:
- **Europe empty** — Europe has ONLY OECD entries (named DAX/FTSE/CAC were removed
  earlier because Stooq's robots.txt disallows them), so all 8 fail → nothing.
- **Asia only Nikkei** — Nikkei uses the valid named id `NIKKEI225`; the 4 Asian
  OECD entries (KOR/IND/CHN/IDN) fail.
- **North America only US** — the 5 US *named* ids (SP500/NASDAQCOM/NASDAQ100/
  DJIA/VIXCLS) are valid; the 2 OECD entries (CAN/MEX) fail.
- **Africa / South America / Oceania empty** — OECD-only (ZAF; BRA/CHL; AUS/NZL)
  → all fail.
- **"oecd" tag shows nothing** — every `oecd`-tagged card has `latest: null`, so
  clicking the tag chip / looking at the board surfaces no populated index.

### Code grounding

- **Catalog:** `configs/index_feeds.yml`. The 19 OECD entries are the block under
  "ALL CONTINENTS — OECD MEI share-price indices". The file's own honesty note
  even warns: *"the OECD `SPASTT01<ISO3>M661N` IDs follow a documented FRED/OECD
  pattern and are accurate to our knowledge, but were NOT live-verified… Verify on
  a networked machine."* — this is precisely the predicted failure that fired.
- **Loader:** `src/markets/feed_catalog.py::load_index_feeds` → `Feed` (carries
  `continent` + `tags`).
- **Board API:** `src/api/markets.py::market_board` (`GET /api/markets/board?category=index`).
  Returns **all** catalog cards; entries with no stored data come back
  `latest: null` and sort last; response also carries `with_data` count.
- **Import path:** `src/markets/pipeline.py::import_due_feeds` (freshness-gated;
  one feed's failure never aborts the pass; failures counted in the `failed`
  tally). Called from the scheduler's markets pass.
- **Frontend:** `src/static/app.js::renderIndicesBoard` (~L6249). Continent
  subtabs + tag chips are built from `_idxCards` (the board payload). Default view
  is **families** — one multi-series graph per continent from the full series; a
  continent whose feeds have no data yields an empty/absent family graph = "empty".
- **Existing test:** `tests/test_index_catalog.py` asserts all-6-continents +
  named-vs-OECD unit, but does **not** (can't, offline) validate that FRED ids
  resolve — so nothing caught the ISO-3 mistake.

### Fix plan (for the autonomous session)

**A. Quick win — correct the FRED ids (ISO-3 → ISO-2).** 🔍 verify each resolves
live on FRED before shipping (I inferred the pattern from 4 confirmed examples;
some OECD MEI series were also *discontinued* by FRED ~2024, so a corrected id may
still be stale/dead — check the series page's last observation). Corrected ids:

| catalog (wrong) | corrected | country |
|---|---|---|
| SPASTT01DEUM661N | SPASTT01**DE**M661N | Germany |
| SPASTT01GBRM661N | SPASTT01**GB**M661N | UK |
| SPASTT01FRAM661N | SPASTT01**FR**M661N | France |
| SPASTT01ITAM661N | SPASTT01**IT**M661N | Italy |
| SPASTT01ESPM661N | SPASTT01**ES**M661N | Spain ✓confirmed |
| SPASTT01CHEM661N | SPASTT01**CH**M661N | Switzerland |
| SPASTT01NLDM661N | SPASTT01**NL**M661N | Netherlands |
| SPASTT01SWEM661N | SPASTT01**SE**M661N | Sweden |
| SPASTT01KORM661N | SPASTT01**KR**M661N | Korea ✓confirmed |
| SPASTT01INDM661N | SPASTT01**IN**M661N | India |
| SPASTT01CHNM661N | SPASTT01**CN**M661N | China ✓confirmed |
| SPASTT01IDNM661N | SPASTT01**ID**M661N | Indonesia |
| SPASTT01CANM661N | SPASTT01**CA**M661N | Canada |
| SPASTT01MEXM661N | SPASTT01**MX**M661N | Mexico |
| SPASTT01BRAM661N | SPASTT01**BR**M661N | Brazil |
| SPASTT01CHLM661N | SPASTT01**CL**M661N | Chile |
| SPASTT01ZAFM661N | SPASTT01**ZA**M661N | South Africa |
| SPASTT01AUSM661N | SPASTT01**AU**M661N | Australia |
| SPASTT01NZLM661N | SPASTT01**NZ**M661N | New Zealand |

(`symbol` and `url` both embed the id — fix both. `key` can stay for stability.)

**B. Add an offline format guard so this can't recur.** Extend
`tests/test_index_catalog.py`: assert every OECD/share-price id matches
`^SPASTT01[A-Z]{2}M6[0-9]{2}N$` (2-letter code), not 3-letter. Cheap, offline,
catches the exact mistake without network.

**C. Breadth — "as much indices as possible."** After A lands and populates the
board, expand coverage. Options, ethics-ranked:
  1. **More OECD economies via the same FRED `SPASTT01` family** (~40 available):
     add e.g. Japan, Poland, Turkey, Norway, Denmark, Belgium, Austria, Ireland,
     Portugal, Greece, Finland, Czechia, Hungary, Israel, Colombia, Argentina(?),
     Saudi(?) — verify each id + liveness. This is the honest all-continent path
     the file already commits to.
  2. **OECD SDMX API directly** instead of FRED — the app already has an SDMX
     parser (`src/stats/sdmx.py`) + fetch client (`src/stats/fetch.py`). This is
     the app's sanctioned "official endpoint" path, gives comprehensive + more
     current coverage, and dodges FRED-mirror discontinuations. Worth evaluating
     as the scalable breadth source (bigger build than A).
  3. **Named non-US indices** are largely blocked (Stooq robots-disallows;
     verified in-file). Do NOT scrape them. Only add a named index if a free,
     robots-permitting daily CSV genuinely exists (Nikkei via FRED is the pattern).

**D. Tagging — "properly tagged."** Once ids work, the `oecd` tag populates for
free. Ensure a consistent tag vocabulary across all entries: channel (`named` vs
`oecd`), market cap / breadth (`broad`/`large-cap`/`blue-chip`), theme
(`technology`/`volatility`), and development (`emerging`/`developed`). The
maintainer wants tags to be a real, usable facet — audit that every entry carries
a meaningful, non-empty tag set and that each visible tag chip returns ≥1
data-bearing card once the feed works.

### Notes / honesty caveats for the implementer
- OECD `SPASTT01…M661N` are **monthly**, index **2015 = 100**, `unit: idx` (NOT a
  named exchange point level). After the fix the board will show MONTHLY points
  (sparse vs the daily US/Nikkei) — that is correct, not still-broken. The
  twin-board work already handles `idx` vs `pts` (indexed/absolute scale, coherent
  time axis). Keep the "normalised index, not the exchange's point level" labeling.
- **Consider surfacing failed feeds honestly** rather than showing an invisible
  empty card. The board already returns `latest: null` + a `with_data` count; a
  small "feed unavailable" state (reusing the T4 transport-aware verdict grammar
  the Indices UI already has for dead-series) would make a genuine future
  discontinuation *loud* instead of an invisibly-empty continent. Aligns with the
  "degrade loudly" non-negotiable. (Design choice for the session.)
- ⏭ Acceptance: every continent subtab shows ≥1 populated index; the `oecd` tag
  chip returns populated cards; format-guard test green; ids live-verified.

---

## Item 2 — Foreign-language keywords shown untranslated everywhere; want UI-language translation (original always shown) throughout the app  [PLANNED — re-raised]  ⏭

**Verbatim:** "All keywords should be shown in the user's chosen UI language. We
need to setup a strategy to allow this. For example, I do not speak Arabic, but
there's a trending keyword that appears in Arabic, and I don't know what it means.
Let's build up a strategy to allow the app not to obstruct foreign language
keywords (we don't want that), but to show a translation of the keyword (with the
original untranslated keyword always shown for full transparency). The current
state of the app pushes keywords to the user that cannot be understood and does not
allow further investigation due to the lack of translation. This should be true
throughout the app. How should we proceed? Should we ingest more wikidata "rings"?
Should we implement a tool in the AI settings that allows a local llm automatic
keyword translation? Should we pre-translate a great deal of keywords and have them
loaded in the app? What would be the most ethical, neutral, unbiased, rational, and
professional approach?"

**Maps to:** the **"LANGUAGE-AWARE KEYWORDS — TRANSLATE, NEVER BLIND"** ruling
(maintainer, 2026-06-19). The rejected instinct then was a blind-by-language FILTER
(PR #398, built then CLOSED: *"we shouldn't blind a user from foreign language
keyword trends"*). The layered strategy the maintainer now asks for **is that
ruling** — and it is ~80% built. The complaint is that it isn't finished: coverage
is thin, the fallback is manual + ephemeral, and it isn't wired to every surface.

### What already exists (code-grounded)

- **Tier 1 — VERIFIED Wikidata-ring translations (offline, deterministic, QID-sourced):**
  `src/analytics/equivalence.py::translate_term` / `ring_translation`. Threaded via
  `target_lang` through `/api/insights/{top,trending,trending-windows,corpus-keywords,
  where,supergroups}` (`insights.py::_tlang`). Frontend `kwTransHtml(row)` renders
  `→ translation` (app.js ~L9402).
- **Tier 2 — TENTATIVE local-LLM fallback:** `src/ai_layer/translate.py::translate_keyword`
  / `translate_keywords` (skips any term a verified ring covers; labeled unreliable;
  never into the trusted index). Endpoint `POST /api/ai/translate-keywords`. Frontend
  `kwTentativeHtml(row)` renders `≈ translation` + the analysis-window button
  `✦ Translate the rest (AI, tentative)` (`anFillTentative`, app.js ~L9439).
- **Original always shown** already holds (translation is appended beside the term).
- Ring breadth: 540 concept rings shipped (Phase 2); `translation_coverage` metric
  exists in the keyword-engine report; corpus-driven gap generator
  `scripts/generate_wikidata_rings.py --from-log` already built.

### The gaps that produce the live complaint (why the Arabic keyword had no translation)

1. **LLM cache is IN-MEMORY only.** `ai_layer/translate.py::_CACHE` is a process-global
   dict (`_CACHE_MAX=5000`, `clear_cache()`), NOT persisted. Every restart re-asks the
   model, and a computed translation is never available offline afterward.
2. **The fallback is MANUAL, not automatic, and only in ONE surface.** It fires only
   when the user clicks `✦ Translate the rest` in the analysis-window Keywords subtab.
   There is **no AI-settings toggle** for automatic keyword translation and **no
   fallback on the Trends/Home surface** — so on the very surface where the maintainer
   saw the trending Arabic keyword, a term with no ring shows raw, with nothing.
3. **Not universal.** Bare `term` is rendered untranslated in many surfaces:
   `src/static/reader.js` (Keywords tab `renderKeywords`, in-article marked keywords
   `markArticleBody`/`kwLink`), Home "Top keywords of the local copy" (app.js ~L2280),
   the **Families** view (app.js ~L7920 `f.term`), the super-group `<option>` list
   (~L8099), the new keyword-stats hover, mindmap / 3D-explorer nodes, agenda deduced,
   where/who + corpus-facet chips, omnibar keyword group (~L1549).
4. **Coverage / offline gap (the deepest).** The verified tier is offline but sparse
   (only concepts with a ring); the LLM tier is broad but needs Ollama + a model +
   (usually) being online. So an **offline, no-model** user has **no path** to
   translate a non-ring foreign keyword — the exact dead end.

### Recommendation (answers the maintainer's question)

**Not either/or — the ethical/professional answer is a single labeled tiered
cascade, which is already the architecture. All three of the maintainer's options
are tiers of it.** One resolver `resolve_keyword_translation(term, source_lang,
target_lang) -> {translation, source, confidence}`, the **original ALWAYS shown**,
each result **labeled by provenance**:

- **Tier 1 · Verified Wikidata rings** (offline, deterministic, QID-sourced) — the
  trust anchor. Grow **corpus-driven** (`generate_wikidata_rings.py --from-log`,
  gap-targeted), NOT by bulk-absorbing Wikidata (115M items = wrong shape + coverage
  bias). Label: *verified*. → answers "more rings?": **yes, corpus-driven, as the
  anchor — but rings alone can never cover proper nouns / novel terms.**
- **Tier 2 · Bundled, pre-translated CURATED dictionary of the common cross-language
  keyword vocabulary** (offline, deterministic, shipped ×12, dated + freshness-tested
  like the rings/catalogs; QID/human-anchored where possible). The **offline safety
  net** so a no-model user still gets the frequent vocabulary. → answers
  "pre-translate a great deal?": **yes — the COMMON vocabulary only** (a user's unique
  corpus keywords are unknown at build time, so you can't pre-translate everything;
  bulk-LLM-without-review would be fabrication).
- **Tier 3 · Local-LLM fallback, made AUTOMATIC + PERSISTENT + opt-in**
  (`ai_layer/translate.py`) — covers the arbitrary/proper-noun/novel tail the user's
  corpus produces. Build items: **(a)** persist results in a DB cache table keyed by
  `(term, src_lang, tgt_lang, model, prompt_version)` — pay once, survive restart,
  available offline afterward; **(b)** an **AI-settings toggle** "Auto-translate
  foreign keywords (local AI, tentative)" that, when on + a model present,
  background-translates *visible* foreign keywords (bounded, rate-limited, like the
  auto-on-ingest AI extractor pattern); **(c)** always labeled `≈ AI · unreliable,
  verify`; **(d)** never into the trusted index. → answers "LLM tool in AI settings?":
  **yes — as the fallback, auto + cached + labeled + opt-in.**
- **Tier 0 · original untranslated keyword ALWAYS shown** (transparency; never blind —
  the PR #398 lesson).
- **Empty state:** no translation at any tier + no model/offline → show original + a
  neutral, always-present "translate" affordance + an honest "needs a local model /
  go online" hint. **Never a blank, never hidden.**

**Universality (the fix for "throughout the app"):** route EVERY keyword-display
surface through ONE shared render helper (generalize `kwTransHtml` + `kwTentativeHtml`)
fed by ONE backend annotation that attaches `{translation, translation_source,
tentative}` to every keyword row. Audit + wire the surfaces listed in gap #3.

### Why this is the most ethical / neutral / unbiased / rational / professional
- **Verified-first + provenance labels** — never presents a guess as fact (honesty by
  construction); trust is explicit at each tier (verified vs ≈AI-unreliable).
- **Original always shown** — full transparency; the app never becomes an opaque
  translator that could silently reframe meaning; the user can always verify.
- **No English pivot** — rings are direct multilingual (QID→target label); the LLM
  should translate source→target directly and disclose any pivot → avoids anglocentric
  bias.
- **The cascade DE-BIASES coverage** — rings skew toward well-documented (often
  Western) concepts; the LLM fallback + corpus-driven ring growth *improve*
  under-documented-language coverage, so the layered approach is MORE neutral than
  rings alone.
- **Offline verified tiers** — local-first; translation is not gated behind owning an
  LLM (which would bias toward users with powerful hardware).
- **Never blind** — translation ADDS, never filters (the closed PR #398 principle).

### Build sequencing (for the autonomous session)
1. **Persist the LLM tentative cache** to a DB table (biggest reliability win; pay
   once, survive restart, offline-after). 2. **Universal wiring** — the shared helper +
   backend annotation across all gap-#3 surfaces (fixes "throughout the app"). 3.
   **AI-settings auto-translate toggle** + bounded background pass. 4. **Bundled common
   dictionary** (Tier 2 offline breadth). 5. **Corpus-driven ring growth** (raise the
   verified tier; measure with `translation_coverage`). ⏭ Acceptance: on Trends/Home,
   a foreign keyword with no ring shows a labeled translation (verified or ≈AI) or a
   neutral translate affordance — never bare; the original is always present; coverage
   measurable via the keyword-engine report.
