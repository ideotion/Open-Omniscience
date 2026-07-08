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

---

## Item 3 — "Discover new sources (Wikidata)" errors "Enter country codes first"; should auto-pick countries, and be in all UI languages  [NEW]  ⏭

**Verbatim:** "In settings, in data-backup, clicking on "discover new sources
(wikidata)", an error code appears saying: "Enter country codes first, e.g.
ke,ng,br". It should automatically do that and in all of the app's languages."

**Two asks:** (a) don't require manual country-code entry — auto-select the
countries; (b) the button + its messages must be translated (×12).

### Code grounding

- **Button + input:** `src/static/index.html:1560-1561` — a text input `#discover-cc`
  (placeholder "countries e.g. ke,ng,br") + a button `onclick="discoverSources(this)"`.
  The label ("Discover new sources (Wikidata) ↗") and the long `title` tip are
  **hardcoded English** (not keyed). The tip already says *"pick under-represented
  countries to keep coverage balanced."*
- **Handler:** `src/static/app.js:8700 discoverSources(btn)` — reads `#discover-cc`;
  if empty → `toast(t("Enter country codes first, e.g. ke,ng,br"), "err")` and
  returns. Then `ensureOnline(...)` consent gate → `POST /api/diagnostics/discover-sources?countries=…`.
  The status strings `"Discovering…"`, `` `Added ${d.added} disabled sources — review
  in Settings → Sources` ``, `"Discovery failed — see console"` are **hardcoded
  English** (the empty-input toast is the only keyed string).
- **Endpoint:** `src/api/diagnostics.py:920 discover_sources_endpoint` —
  `countries: str = Query(...)` is **required**; splits to ISO-2 codes; discovers
  Wikidata media orgs per country, adds them `enabled:false` for review; 409 under
  airplane mode; guarded transport; docstring says *"Bounded to a handful of countries
  per call … pick UNDER-REPRESENTED countries to keep the catalogue's coverage
  balanced."*
- **The auto-select mechanism ALREADY EXISTS:** `src/catalog/coverage.py` →
  `country_counts_from_session(session)` + `coverage_report(counts, thin_threshold=3)`
  returns `{"thin": [...], "missing": [...]}`. It is already used by
  `src/discovery/channels.py::catalog_channel` to target thin/missing countries.
  Also `queries.source_country_counts(session)` (from the map work).

### Fix plan (for the autonomous session)

**A. Auto-select countries (server-side, single source of truth).** Make the
endpoint's `countries` param **optional**; when absent/empty, auto-derive the target
list from `coverage_report(...)` — the **under-represented** countries (`missing`
first, then `thin`). This matches the button's own tip AND the **de-US-centring
non-negotiable** (discovery that automatically improves balance). Keep it **bounded
per call** (the docstring already promises "a handful" — each country queries several
media types) and **rotate** across calls (least-recently-discovered first, like the
continuous per-country round-robin) so repeated clicks progressively cover the world
without one huge unbounded call. The manual `#discover-cc` input stays as an
**optional override** (the Desk lesson — don't remove the capability). Frontend: when
the input is empty, DON'T toast-and-return; call the endpoint with no `countries` and
show a keyed status like "Discovering for under-represented countries…". Consent gate
(`ensureOnline`) and airplane-refusal are unchanged (still networked to Wikidata; the
country SELECTION is a local DB read, no network).

**B. i18n (×12).** Key every user-facing string on this control:
- The button label "Discover new sources (Wikidata) ↗" + its `title` tip
  (index.html:1561).
- The input placeholder "countries e.g. ke,ng,br".
- The status strings in `discoverSources`: "Discovering…", "Added N disabled sources
  — review in Settings → Sources" (interpolated → use `t()` with a count arg),
  "Discovery failed — see console", and the new auto-mode status.
- Verify with `python scripts/i18n_report.py --min 100`. Non-en AI-drafted, flagged
  for native review (per house convention). Coordinate with the parallel session on
  the locale files (hot-conflict surface) — additive keys only.

### Notes / honesty
- Auto-selecting under-represented countries is the on-mission choice, but keep it
  **transparent**: the status/result should say which countries were targeted (e.g.
  "Discovered for: ng, ke, bd, …") so the user knows what the app chose on their
  behalf — never a silent, opaque selection.
- Still adds sources **disabled** for review; nothing scraped until enabled. Unchanged.
- ⏭ Acceptance: clicking with an empty input runs discovery against auto-selected
  under-represented countries (bounded, rotating, disclosed), never errors; all
  strings render in the active UI language; `--min 100` green.

---

## Item 4 — Governments tab must auto-load country statistics in the background (no "Load" button); visible in the task manager  [NEW + general principle]  ⏭

**Verbatim:** "The Governments tab should automatically show data. Users should not
have to do anything, it should automatically load country government statistical data
such as GDP, population, life expectancy, population statistics, employment
statistics, market statistics, government debt, and so forth. There shouldn't be a
button "load....", because all loadings should be automatic, made in the background,
and accessible within the task manager."

**General principle asserted (applies app-wide):** *no manual "Load…/Refresh…"
gate anywhere* — all loading is automatic, background, and surfaced in the task
manager (the same philosophy as auto-collect, auto-index #21, and the markets
auto-load already shipped). This item is the Governments instance; also audit the
Settings → Statistics "Fetch figures" button and any other remaining manual loaders.

### Code grounding

- **Tab:** `data-tab="law"` labelled **"Governments"** (index.html:59; the code
  anchor stayed `law` after the rename). Subtabs (`#gov-subtabs`): `gov-countries`
  (per-country World Bank stats), `gov-map` (choropleth by indicator), `gov-law`
  (world law). API `/api/governments/*` (`src/api/governments.py`).
- **The button to remove:** `#gov-load-btn` → `app.js:3465 govLoadStandard(btn)` →
  `POST /api/governments/load-standard` (consent-gated via `ensureOnline`).
- **Backend (`src/api/governments.py:136 load_standard`):** loops the curated
  indicator set (`src/stats/indicators.INDICATOR_CATALOG` / `indicator_ids()`),
  fetches each via `statfetch.fetch_worldbank(code, "all")` for ALL countries, stores
  vintaged `StatFigure`s (`store_figures`), records a `StatSubscription`
  (worldbank/indicator/country="all"), refuses up front under airplane mode (409),
  degrades loudly per indicator. It is a **synchronous request** (a `def` handler —
  runs in the threadpool, but blocks that one request for the whole multi-indicator ×
  all-countries fetch; not cancellable, not visible).
- **The ongoing-refresh half ALREADY EXISTS:** `src/stats/subscriptions.py` replays
  DUE subscriptions in the scheduler pass (freshness-gated, airplane-gated, new
  vintage each time) — SHIPPED (ruling #12). So once subscriptions exist, refresh is
  automatic. The GAP is the **initial** load (no subscriptions until the button is
  clicked once) + **task-manager visibility**.
- **Indicator catalog (`src/stats/indicators.py`) already covers the ask:** GDP
  (NY.GDP.MKTP.CD/PCAP/growth), inflation (FP.CPI.TOTL.ZG), population (SP.POP.TOTL/
  GROW), life expectancy (SP.DYN.LE00.IN), employment (SL.UEM.TOTL.ZS, SL.TLF.TOTL.IN),
  government debt (GC.DOD.TOTL.GD.ZS, GC.NLD.TOTL.GD.ZS), Gini (SI.POV.GINI). **Only
  "market statistics" is missing** — optional add: CM.MKT.LCAP.CD (market cap of
  listed companies), CM.MKT.TRAD.CD (stocks traded), and/or cross-link the Indices
  board. This is a data-breadth nicety, NOT the core of the item.

### Fix plan (for the autonomous session)

**A. Auto-seed + auto-load (no button).** Seed the curated indicator subscriptions
(worldbank / each `indicator_id()` / country="all") automatically — at source-seed
time or on the first online scheduler pass when none exist — so the **existing
subscription-refresh machinery** fetches them on the next due pass with no manual
trigger. The initial load then rides the same freshness-gated pass as ongoing
refresh. This reuses shipped infrastructure (subscriptions + scheduler pass) rather
than a new path.

**B. Make the fetch a task-manager JOB.** Refactor the synchronous
`load_standard` loop into a background job manager (worker thread, like
DumpDownloadManager / the markets pass) surfaced in `/api/jobs` (kind e.g. `stats` /
`governments`): progress = indicators done/total + current indicator + figures
stored; **cancellable** (Stop); it is a **NETWORK job** whose DB writes take the
single-writer gate (arbitrates with collect/import). Per-indicator failures degrade
loudly (already do), never abort the set, never fabricate.

**C. Consent = the ONE network consent, not a per-fetch popup.** Boot is airplane
(zero-network); the first offline→online transition passes the ONE consent
(`ensureOnline`, invariant #14), then background fetch runs like auto-collect/markets.
Airplane refuses (already 409). No per-load button/popup.

**D. Remove the button; render stored data with an honest background state.** Drop
`#gov-load-btn` from index.html. The `gov-countries` / `gov-map` views render whatever
is stored (auto-populated over time) with an honest empty/loading state — e.g.
"Loading government data in the background — see the task manager" — never a blank and
never a required click. Keep at most a manual "refresh now" INSIDE the task manager /
Settings (Desk lesson — capability preserved, not a gate on the tab). `govLoadStandard`
becomes that optional refresh or is retired.

**E. Bandwidth ladder (already ruled):** stats fetches are small-payload / high-value
→ run EARLY in the pass (with markets/commodities/weather), ahead of heavy crawling.

### Notes / honesty
- World Bank figures are a **stanced producer's published values**, VINTAGED (a
  re-fetch is a new vintage, never an overwrite) — unchanged; keep the producer +
  method + as-of + the existing caveat visible. No score.
- Scale: the curated set × all countries is a bounded, freshness-gated fetch (annual
  data changes rarely) — the freshness gate keeps passes cheap after the first load.
- ⏭ Acceptance: a fresh online install populates the Governments tab automatically
  (no click); the fetch appears in the task manager as a cancellable job; airplane
  refuses; the tab shows an honest background state while loading; the same
  no-manual-load principle is applied to the Settings → Statistics fetch button.

---

## Item 5 — Agenda looks empty (only moon phases); must show ALL article-extracted dates + a comprehensive global election/summit calendar  [PLANNED — "flood it" ruling, re-raised with specifics]  ⏭

**Verbatim:** "The Agenda seems empty. We should be able to see all article
extracted dates. The problem should become "there's too much data" rather than
currently showing moon phases and so forth. We should see country's next main
leader's election dates, and any major events that have been grabbed from articles
(G7 summits, BRICS summits, NATO, UNO, and other inter government entity's related
events from the entire globe, including asia, middle east, africa, south america,
Europe, oceania and north america."

**Maps to:** the standing **"we should be flooded; it's the point of datamining —
expand calendars massively (elections, summits, central banks, parliaments, courts,
UN days, fiscal dates…), every entry sourced, movable dates marked"** ruling
(2026-06-10), the **ELECTIONS & CIVIC VERTICAL** design (sourced elections calendar,
France 2027 pilot), and the **AGENDA ARTICLE-EXTRACTED DATES** shipped backend. This
feedback elevates all three from thin/pilot to comprehensive-and-visible.

### Why it looks empty (three causes)

1. **The article-extracted (deduced) layer is gated to near-nothing.**
   `GET /api/events/deduced` (`src/api/events.py:178`) defaults `min_articles=2`, and
   `datestore.upcoming_deduced` (`src/timemap/datestore.py:172`) is **FUTURE-ONLY**
   (`days_ahead`) with a `HAVING COUNT(DISTINCT article_id) >= min_articles` gate
   (`:208`). So on a real corpus almost every extracted date is filtered out — the
   opposite of "too much data." The frontend `loadAgenda` (`app.js:2648`) does call
   `/api/events/deduced` and maps it via `mapDeducedToAgenda` (`:2632`), so the
   pipeline works — it's just starved by the gate + future-only.
2. **Moons are an always-on glyph overlay, not a gated event.** `_astroByDate`
   (`app.js:3098` `_ensureAstro`) paints a moon glyph on every relevant day
   regardless of the event layers, so when the real layers are empty the moons are
   all that's left → "only moon phases."
3. **Curated global events are thin.** `configs/world_events.yml` (161 lines) has UN
   days + some national days + a France election pilot + a `summits` calendar KEY that
   is essentially unpopulated. No comprehensive global election calendar, no populated
   G7/G20/BRICS/NATO/UNGA/SCO/ASEAN/AU/Arab-League/CELAC/Pacific-Islands-Forum/EU-Council
   summit set across all continents.

### Fix plan (for the autonomous session)

**A. Show ALL article-extracted dates (invert the gate — flood, then let the user
filter).**
- The deduced layer should serve **the whole visible agenda window (past AND
  future)**, not just "upcoming." Add/extend a windowed query
  (`datestore.deduced_in_range(start, end, min_articles=1)`) that the agenda calls
  with the view's actual date range (like the World-map signals layer serves its
  window), instead of the fixed future-only `upcoming_deduced`.
- Default `min_articles` to **1** (show single-mention dates) — the maintainer wants
  "too much data" as the desired state. Keep `min_articles` as a **user filter** to
  narrow down (the honest instrument), not a hidden default that hides everything.
- Honesty carries unchanged: each deduced date keeps the "deduced · never confirmed"
  pill, distinct-article + source counts, and the `article_ids` for open-through
  (`mapDeducedToAgenda` already renders these). Flooding ≠ fabricating — every date is
  a real extracted mention with provenance.
- **Secondary lever — extraction recall.** The 2026-06/07 field diagnostics measured
  date-extraction recall ~36–52% (F4), so even ungated the extracted set is thinner
  than it should be. Improving `src/timemap/dateextract.py` recall (the F4 item) is a
  separate, complementary task — note it, don't block A on it.

**B. Make astronomy a subordinate/toggleable layer, not the default-dominant one.**
Once A+B populate real content, moons recede naturally; additionally consider making
the moon/season glyph overlay a **toggle** (off-able) so it never dominates. Keep it
(computed-locally, honest) — just not the headline.

**C. Comprehensive, SOURCED global election + intergovernmental-summit calendar.**
Populate `configs/world_events.yml` (the `elections` + `summits` calendars) with:
- **Next main-leader elections for every country** (presidential / general /
  legislative), across ALL continents (the de-US-centring non-negotiable — explicitly
  Asia, Middle East, Africa, South America, Europe, Oceania, North America). Each
  entry: `official_url` (the electoral authority), `confirmed:true` for a scheduled
  date, `confirmed:false` + typical window for a movable/announced-later one. **NEVER
  fabricate a date** — an unscheduled election carries the authority source + a "date
  not yet set" state, never a guessed day (the ELECTIONS-vertical rule).
- **Intergovernmental summits from the whole globe:** G7, G20, BRICS, NATO, UN General
  Assembly (UNGA), UN climate COP, SCO, ASEAN, African Union (AU), Arab League, CELAC,
  Mercosur, Pacific Islands Forum, EU Council, APEC, Commonwealth (CHOGM), OIC, etc.
  Movable summits carry `confirmed:false` + typical month + host + `official_url` (the
  existing `summits` calendar convention already supports this — line 18 of the file).
- This is a DATA-curation task: sourced, dated, provenance-carrying, never fabricated.
  🔍 verify each date/source on a networked machine before shipping (the maintainer's
  live env is networked). Movable future instances are marked, not invented.

**D. Link article-grabbed summit/election mentions to the curated events.** The
maintainer says events "grabbed from articles" — the deduced layer (A) surfaces the
DATES articles mention; where a mentioned date coincides with a curated
election/summit, they should reinforce (the curated event shows + the deduced count
shows "N of your articles mention this"). Cross-referencing = the lexical/temporal
match the ELECTIONS design already sketched (family↔event titles/tags + mentioned-date
∩ event-date). Nice-to-have on top of A+C.

### Notes / honesty
- The agenda month-grid defaults to the current month; deduced/curated dates far in
  the future won't show until navigated. That's fine, but the "flood" is felt when the
  visible window actually serves its extracted dates (A) — confirm the deduced query
  is window-driven, not a fixed horizon.
- Everything stays labeled: curated = confirmed/movable + source; deduced = "never
  confirmed" + counts. No score, no fabricated dates.
- ⏭ Acceptance: on a real corpus the agenda is DENSE with article-extracted dates
  (past + future, single-mention included, filterable down), a global
  election+summit calendar is visible across all continents, and moon glyphs are a
  minor toggleable layer rather than the only content.

---

## Item 6 — Elaborate the World map: give it sub-tabs, richer localized data, and a story-exploration UI  [PLANNED — extends the ooMap rework]  ⏭ (PLAN)

**Verbatim:** "We should elaborate further the world map. Currently not useful.
There should be sub-tabs like in all other tabs. We should plan to work on that to
have richer localized data and allow the UI to incite users to using this interface
to explore location-based stories (war, climate events, elections, accidents,
lawsuits, etc.)."

**Nature:** the maintainer said "plan to work on that" → this is a **design plan**,
not a one-shot fix. Extends the **MAP REWORK — UNIVERSAL ooMap + CHOROPLETH** work
(2026-06-18, slices 1–5b shipped): the map *component* is built and capable; what's
missing is the **tab-level organization (ooSubtabs)**, the **story-first framing**,
and **incitement UI**.

### Code grounding (current state)

- **Tab:** `data-tab="timemap"` labelled **"World map"** (index.html:58) → dispatch
  `timemap: loadOoMapCoverage` (app.js:1181; slice 5b folded the temporal map in +
  retired it). Panel `#tab-timemap` (index.html:967) is a **single `<section>`** —
  `#oo-coverage-map` + `#oo-coverage-detail`, NO subtab nav. All richness lives in
  **in-map overlay controls** (dimension picker sources/articles/keywords/tone,
  continent grouping, places overlay, time-signals + slider) — powerful but hidden,
  and it defaults to the least-compelling view (sources-per-country choropleth), which
  is why it reads as "not useful."
- **Story-type substrate already exists:** the signals layer plots timemap events by
  KIND (`TMAP_KINDS`/`kindColor`); hazards via `/api/signals/alerts` (climate/disaster
  snapshot); the When×Where extraction (`article_mentioned_places`, `article_entities`)
  + `/api/insights/where`; keyword families (war/climate/election concepts). These are
  the raw material for "location-based stories" — not yet organized as such.
- **Overlap to reconcile:** the Governments tab ALSO has a world-map choropleth
  (`#gov-map`, per-country statistical indicators via ooMap). Both use the same ooMap
  component — the statistical lens could become a World-map subtab, or stay in
  Governments (a consolidation decision for the plan).

### Proposed plan (for a design + build session)

**1. Give the World map an ooSubtabs strip** (invariant #18, the universal grammar
every other tab has). Promote the hidden in-map dimensions into first-class LENSES.
Proposed subtabs:
  - **Stories** (the new HEADLINE lens) — location-based events/stories by TYPE
    (war/conflict · climate events · elections · disasters/accidents · lawsuits ·
    protests · economy…), plotted as points; each type a filter chip with a COUNT;
    clicking a place/cluster opens its corpus (`openAnalysisForIds`) = a place+topic
    investigation. This is the "incite users to explore location-based stories" ask.
  - **Coverage** — the existing choropleth (sources · articles · keywords · tone per
    country). Keep (the current default demotes to one lens among several).
  - **Places** — the mentioned-places overlay (what the corpus is ABOUT), by article
    spread, deduced-labeled.
  - **Data** — per-country statistical choropleth ("richer localized data"; reuse the
    Governments indicator set — GDP/population/etc. — or cross-link/consolidate the
    `#gov-map`).
  - **Hazards/Signals** — the live hazard snapshot layer (climate/disaster), honest
    staleness shown.
  The time slider stays an in-map control within the lenses where time matters
  (Stories/Places), not a top subtab.

**2. Richer localized data — derive story TYPES from the corpus (honestly).** A
"story type" per place = the corpus's own signal, NOT a new classifier: articles
mentioning place X that carry a topic-family's keywords (conflict/climate/election/
legal…) → a "conflict near X" cluster, COUNTS only, "deduced from your corpus, never a
verdict." Sources to fuse per place: the When×Where extraction (place ∩ topic
keywords/families), the signal kinds, hazards, the elections calendar (Item 5), and
the Law tab (lawsuits — cross-link). This ties the map to real corpus content =
"richer localized data," reusing shipped extraction (no fabricated geodata).

**3. Incitement UI (make the map an ENTRY POINT, not a passive choropleth).**
  - Story-type chips with live counts ("142 climate · 88 conflict · 34 elections ·
    27 lawsuits") as the invitation to click in.
  - A "top locations right now" strip (places with the most recent/active stories) →
    click → that place's corpus.
  - Clickable clusters/countries → the place's corpus, organized by story type.
  - An inviting empty/onboarding state that suggests what to explore, rather than a
    blank choropleth.
  - Hover previews of a place's top stories.

### Honesty / non-negotiables carried
- Story-type = deduced from rule-based keyword families / signal kinds / hazard types,
  LABELED "deduced, never confirmed / never a verdict." No classifier fabrication, no
  composite score, no "importance" ranking (counts + recency ordering, method stated).
- ooMap honesty stays: "no data" ≠ zero (un-shaded, never a guessed colour);
  unlocated bucketed + disclosed; deduced places "never confirmed"; VADER-EN-only
  caveat on any tone lens; Tor "server location unavailable" honesty.
- Reuse the shipped ooMap component + existing endpoints; new work is
  organization/framing/incitement + the per-place story aggregation, not a new map
  engine.

### Notes
- This is the maintainer's map-rework vision maturing from "choropleth of coverage"
  (a producer-facing diagnostic) to "explore the world's stories" (a reader-facing
  investigation surface) — the invariant-#8 "show DATA, the added value" principle.
- ⏭ Acceptance (plan-level): World map has ooSubtabs (Stories/Coverage/Places/Data/
  Hazards); Stories is the default and invites click-through into place+topic corpora
  across all continents; localized data is corpus-derived + honestly labeled; the
  Governments `#gov-map` overlap is resolved (consolidated or clearly distinct).

---

## Item 7 — Many more indexed commodities; rare earths especially (blocked on data source — question raised)  [NEW + PLANNED-expansion]  ⏭ (rare earths: AWAITS MAINTAINER RULING)

**Verbatim:** "There should be much more indexed commodities. There should be rare
earths, this is important. If it cannot be done for any reasons, ask questions so we
can find solutions together."

**Two separable parts:** (a) broaden the free commodity set — **doable now**; (b)
rare earths — **blocked on data availability**, question raised (the maintainer
explicitly invited it).

### Code grounding

- **Catalog:** `configs/commodity_feeds.yml` — **33 feeds** via free, no-key,
  robots-permitting CSV: **FRED** (EIA daily energy) + **World Bank Pink Sheet** /
  **IMF PCPS** (monthly, redistributed by FRED). Categories: energy 11, metals 7
  (copper/aluminum/nickel/zinc/iron-ore/tin/lead), agriculture 9, precious 2
  (gold/silver), strategic 1 (uranium), construction 2 (logs/sawnwood), fx 1.
- **The rare-earth wall is documented in-file (line 204):** *"Rare-earth element
  prices (Nd, Dy, Pr…) have NO free, no-API-key official series: producers publish via
  paywalled assessors (Asian Metal, Argus). Honesty rule: we do not relay scraped or
  guessed numbers — add a custom extraction rule pointing at a source you have the
  right to read."* → the non-negotiable (no fabricated/scraped numbers) hitting a
  genuine data-availability limit.
- **Custom-rule mechanism exists:** `MarketExtractionRule` + the markets.py CRUD — a
  maintainer-authorized paid source can be wired as a custom rule (the in-file note's
  own suggested path).

### Part (a) — broaden FREE commodities (DOABLE NOW, no question needed)

The World Bank Pink Sheet has ~70 series; the catalog uses ~25 of them. Add (🔍 verify
each FRED id on a networked machine — same ISO-code caution as Item 1):
- **Critical/battery minerals (adjacent to rare earths, high strategic value):**
  lithium, cobalt (WB Pink Sheet added these), molybdenum/manganese where free.
- **Precious:** platinum, palladium.
- **Agriculture:** barley, sorghum, palm oil, soybean/sunflower oil, tea, bananas,
  oranges, tobacco, wool, groundnuts, fishmeal.
- **Fertilizers (strategic, WB Pink Sheet):** phosphate rock, DAP, TSP, urea, potash.
This is a straightforward catalog expansion via the existing FRED/WB path (a wrong id
fails loudly, never fabricates).

### Part (b) — rare earths: the honest constraint + options (QUESTION RAISED)

Rare-earth SPOT prices have **no free, no-key, robots-permitting source** — only
paywalled assessors (Argus, Asian Metal, SMM). The honesty non-negotiable forbids
relaying scraped/guessed numbers, so we cannot ship a rare-earth *price* feed from a
free source. But the intent (rare earths matter geopolitically) CAN be served by free
official DATA:
- **Option 1 — USGS Mineral Commodity Summaries (RECOMMENDED):** free, PUBLIC-DOMAIN,
  official annual **production · reserves · net-import-reliance BY COUNTRY** for rare
  earths + all critical minerals. Not prices, but arguably MORE valuable for a
  geopolitics/datamining app (WHO mines/controls rare earths — China dominance) — and
  it feeds the World map (Item 6) + Governments (Item 4) as localized data.
- **Option 2 — free price-adjacent proxy:** a FRED Producer Price Index for rare-earth
  metals, or a rare-earth/strategic-metals equity index, IF a free robots-permitting
  series exists (verify). An official trend, labeled a proxy — not spot price.
- **Option 3 — a paid assessor the maintainer authorizes:** provide/authorize Argus /
  Asian Metal / SMM (a "source you have the right to read"), wired via a custom
  `MarketExtractionRule`. Real spot prices, but needs the maintainer's subscription +
  NOT bundled/shipped.
- **Option 4 — broaden free commodities first (part a), defer RE prices.**
Combinable (e.g. 1 + a). **PENDING the maintainer's answer** (asked via AskUserQuestion
this session) — amend this section with the ruling.

### Honesty / notes
- No scraped/guessed numbers, ever (the in-file rule). A rare-earth surface must be
  free official data (USGS/PPI, labeled by method) or a maintainer-authorized source
  (custom rule) — never a relayed paywalled/scraped price.
- ⏭ Acceptance (part a): the commodity board is materially denser (critical minerals +
  fertilizers + more agri/precious), all via verified free ids. Part b: per the
  maintainer's chosen option(s).
