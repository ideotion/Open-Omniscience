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
