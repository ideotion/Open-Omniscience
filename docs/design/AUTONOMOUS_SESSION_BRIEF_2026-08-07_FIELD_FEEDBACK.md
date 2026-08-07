# Autonomous session brief — field feedback 2026-08-07

**Status:** PENDING execution. Planning only; nothing in this brief is built.
**Origin:** eight maintainer field impressions (2026-08-07) + two attachments, investigated
against `main`@`9c651ee` and re-based on `main`@`563dd15`. 47 numbered questions were put and
answered the same day; every ruling is recorded in `CLAUDE.md`'s Open queue under the
2026-08-07 entry, which is the binding record. This document is the *how*.
**Composes with (never duplicates):** the law vertical brief
(`AUTONOMOUS_SESSION_BRIEF_2026-07-17_LAW_VERTICAL.md`, whose S6 adapter work Phase B
executes), the 2026-07-24 Session A/B briefs, `SCRAPING_10X_SCALING_STRATEGIES_2026-07-24.md`,
and the GUI audit brief `AUTONOMOUS_SESSION_BRIEF_2026-07-28_GUI_AUDIT.md`.

---

## 0. Working mode

- **Draft PRs only.** Nothing self-merges; the maintainer's review is the gate.
- **Branch prefix** `claude/oos-*`. Fetch `origin/main` immediately before cutting each
  branch (the recorded stale-base hazard has cost this project two incidents).
- **Staleness guard, mandatory.** This brief is dated. Before each slice, re-read the
  anchors named in it. The repository has repeatedly turned out to have *already shipped*
  something a brief called open — verify-and-mark, never rebuild.
- **Skeptics before push** on every slice marked ⚠, with the negative-space lens mandatory
  (generate inputs that *should* produce nothing, and assert they do).
- **Frontend is browser-unverified** in the sandbox unless the session drives Chromium
  (`/opt/pw-browsers/`, and `python3.13` exists — the "no browser here" caveat is a habit,
  not a limit; see the 2026-08-04 lesson). Prefer driving it. Where it is not driven, ship
  conservative + flagged and say so.
- **CI gates, verbatim:** `ruff check --select=F,B --extend-ignore=B008`;
  `bandit==1.9.4 -r src/ -ll -q` (redirect to a file and capture `$?` on its own line — a
  pipe to `tail` makes `$?` the exit code of `tail`); `python -m mypy src/ | grep -c " error: "`
  against `MYPY_BASELINE=127` using the **pyproject-pinned** mypy in the project venv, not the
  ambient one; `scripts/i18n_report.py --min 100`; `node --check` on every touched script block.

### Scope fence

Out of scope for this session: the five new verticals; the Observatory; the LLM-rig-dependent
runs; the inline-handler retirement; anything needing egress (see §7). Do not relax the
airplane, robots, politeness or single-writer invariants for any slice here.

---

## 1. Verified findings (do not re-derive)

Everything in this section was read from the tree or from the attachments. Line anchors are
from `9c651ee`; re-confirm before editing.

### Governments (item 8)

| # | Defect | Anchor | Evidence |
|---|---|---|---|
| G1 | `fetch_worldbank` **never paginates** — one GET at `per_page=1000`; `_worldbank_observations` returns `payload[1]` and **discards `payload[0]`**, the page meta carrying `pages`/`total`. `country=all` is ~266 economies × ~65 years ≈ 17k rows. | `src/stats/fetch.py:181`, `src/stats/sdmx.py` | Code + the PDF's 2016–2025 span (n=9/8/5/1) where ~65 years exist |
| G2 | `to_iso2()` returns any 2-letter string unchanged, so **World Bank 2-letter aggregate codes are admitted as countries** (`XD` High income, `XC` Euro area, `XT`/`XM`/`XN`/`XO`/`XP` income groups, `EU`, `OE` OECD, `1W` World, `Z4`/`Z7`/`ZG`/`ZJ`/`ZQ` regions, `8S`, `B8`, `F1`, `S1`–`S4`, …). Its docstring promises `None` for aggregates — **true only for the 3-letter form**. `to_iso3` has the mirror hole. | `src/catalog/countries.py` | Code |
| G3 | `_govFmt` covers 5 of the catalog's 11 units. `intl$`, `per 100`, `per 1,000`, `per 100,000`, `births/woman`, `t/capita` fall to `fmtNum(v,2)`. | `src/static/app.js:4690` | PDF: GDP-PPP renders `99 594 884 137 256.80`; mobile subs render bare `141.60` |
| G4 | **Chart gridline labels are unformatted too** — the axis of the GDP sparkline reads `51167643745037.1`. | `dashChartSvg` gridline labels | PDF |
| G5 | **Single-point series render a broken x-axis** — Physicians (n=1) shows `01-01` instead of `2022`. | `dashChartSvg` | PDF |
| G6 | **Sparkline aspect distortion** — `.gov-ind-spark svg{width:100%;height:32px}` forces a fixed `300×120` viewBox into 9:1. | `app.css:512-517` | Code + PDF |

**The figures are not cross-assigned.** `XD` is the World Bank **"High income"** aggregate
(iso3 `HIC`). Every value in the PDF is mutually consistent with it: GDP $77T, GDP/capita
$54k, population 1.4B, life expectancy 80.4, fertility 1.42, literacy 97.7%, electricity
100%, internet 94.2%, mobile 141.6 per 100. **Do not open a data-corruption investigation.**
The work is filtering, pagination and labelling.

Two figures that look wrong and are **correct**, needing a label rather than a fix:
`IT.CEL.SETS.P2` at 141.6 (subscriptions, not people — multiple SIMs) and
`SE.SEC.ENRR` at 103.2% (gross enrollment includes repeaters and over-age pupils).
Working correctly and not to be broken: `CO2 emissions —`, `Gini index — not enough points`,
`Central government debt — not enough points` are honest gaps rendering honestly.

**Not settled:** *why exactly one* economy survives rather than fifteen. The World Bank API
is egress-blocked in the sandbox (HTTP 000), so the shape of page 1 is unconfirmed. It does
not change the fix. The subscription replay path was checked and is not a second culprit —
`refresh_due` calls the same un-paginated `fetch_worldbank` (`src/stats/subscriptions.py`).

### Law extraction (item 3)

The attached reader export of *Data Protection Act 2018 (consolidated)* stores **the entire
`legislation.gov.uk` page chrome** as article text: `Skip to main content · Cymraeg · Home ·
Explore our collections · Search Legislation · Title: · Year: · Number: · Type: · All UK
Legislation (excluding originating from the EU) · … · UK Private and Personal Acts · Acts of
the Scottish Parliament · …` — the site's search-form dropdown, ingested as prose.

Every bogus extraction traces to it:

- `Personal Acts ×2` as a **person** — a dropdown option
- `Data Protection ×4`, `Great Britain ×3`, `United Kingdom ×2` as **people** (two are places)
- `PART ×24` as an **organization** — the all-caps rule catching structural headings
- `Uk (gb)` + `United Kingdom (gb)` + `Britain (gb)` — three surface forms, uncanonicalised
- `Ireland (ie)` inside a **UK** Act — almost certainly "Northern Ireland" mis-resolved to the
  Republic. A geographic fabrication, not noise
- Event dates `2026-07-25`/`2026-07-27`, three days before capture — the site's "changes to
  legislation as at" banner, not events in the Act
- `Published 2026-07-31` for the **2018** Act — the tracking date stored as publication date

**Why the gates missed it:** `classify_non_article` + `prose_gate_verdict` are *binary* —
article or not-article — and this page is ~80% genuine Act text, so it is correctly kept and
the 20% of chrome rides along. There is a **reject** stage and no **strip** stage. That is an
architectural gap affecting every source without a clean extractor, not a law-specific bug.

### Others

- **Item 4:** `loadHealth()` is called **exactly once**, at boot (`app.js:22320`). Never
  polled. The green "healthy" pill is a boot-time paint that can never go red; its
  `catch → offline` only fires if the *first* call fails.
- **Item 5:** sorting **already exists** end-to-end (`an-adv-sort`/`an-adv-dir` →
  `sort_by` = date│source│title│language, `src/api/main.py:1038`), but lives in the
  **Advanced** subtab. This is placement, not absence. Sort-by-**tag** does not exist. A
  keyword-count sort exists but counts *the searched keyword*, not the article's own top
  keyword. The `source ↗` column and the Summarize/Translate buttons are confirmed present
  in `_anLoadArticles`; the reader carries both, so removal is absorption-safe.
- **Item 1:** `famHue(bi) = hsl((bi*53)%360 60% 55%)` is keyed to **bucket index**
  (`app.js:2816`), so the hue shifts whenever the set of non-empty buckets changes.
  `openCardCorpus(ids, label, tab)` (`app.js:3122`) carries no card identity, hue, producer,
  trigger or method.
- **Items 6/7:** Settings has 10 subtabs. `set-data` (314 lines) holds "Diagnostics log",
  "All diagnostics (.zip)", "Run perception-eval harness", "Enrich source tags from corpus".
  `set-advanced` holds 21 headings / 16 `<details>`. `set-safety` holds 13 sections including
  Panic wipe and Uninstall. **The 2026-07-20 one-button diagnostics ruling was never
  executed** — item 6 is a repeat, which by this project's own protocol is a ledger failure,
  not merely a task.
- **Blocs:** there is **no membership/bloc registry anywhere in the tree**. `CONTINENT_OF`
  exists and is complete (`src/catalog/countries.py:586`). OECD and IMF appear in
  `src/stats/agencies.py:73-76` as directory entries with a home URL only — **no fetch or
  parse wiring**. `parse_sdmx_json` handles SDMX-JSON **2.1**; OECD is 1.0 and IMF 3.0, so
  the parser needs verifying, not assuming.

---

## 2. Phase A — Governments

Sequenced. A1+A2 must land together: A1 alone floods the dropdown with aggregates.

### ⚠ A1 — paginate the World Bank fetch

`fetch_worldbank` reads `payload[0]["pages"]` and loops pages 2..N, concatenating
observations. Keep `parse_worldbank` pure — pagination belongs in the fetch layer.

- Bound the loop by the **reported** `pages`, and additionally by a hard ceiling, so a
  malformed or hostile meta cannot spin forever.
- Stop on a page that returns zero observations (defensive against `pages` over-reporting).
- Preserve the injectable `get` seam; tests need no socket.
- The guarded session, kill switch and circuit isolation apply per request as today.

**Skeptic lens: resource exhaustion.** Negative-space tests: `pages: 1` issues exactly one
request; `pages: 0`, a missing meta, a non-integer `pages`, and a meta claiming 10⁶ pages all
terminate; an empty page-2 stops the loop.

**Acceptance:** a fixture with 3 pages yields all three pages' rows in order; a single-page
fixture is byte-identical to today's behaviour.

### ⚠ A2 — classify aggregates instead of admitting them

Ruling 1(b): keep them, tag them, exclude them from country surfaces, give them their own view.

- Add an explicit **aggregate code registry** (dated, in `configs/`, registry-tracked per the
  external-artifact protocol) listing the World Bank's ~48 aggregates with their 2- and
  3-letter codes and display names.
- `to_iso2`/`to_iso3`: a code in the aggregate registry returns `None`. Fix the docstrings —
  the current one states a guarantee the function does not provide.
- `StatFigure` rows keep their `ref_area` unchanged; classification is a **read-time** lookup,
  not a stored flag, so a registry correction needs no migration.
- The Governments country dropdown and choropleth take countries only.

**Skeptic lens: the fabricated-gap twin.** A real country must never be classified as an
aggregate. Test both directions explicitly — the over-eager version of this fix silently
deletes countries and looks conservative while doing it.

**Acceptance:** with a fixture containing `XD`, `HIC`, `WLD`, `FRA`, `FR`, the country
surfaces return France only; the aggregate surface returns High income and World, named.

### A3 — units and number formatting

- Give every one of the 37 catalog entries an explicit **`unit_display`** and route
  `_govFmt` through the shared smart formatter for *all* units, not five of them.
- `intl$` formats like `USD`; `per 100` / `per 1,000` / `per 100,000` render **with their
  unit**; `t/capita`, `births/woman`, `years`, `index` likewise.
- The hover (`#oo-tip`, invariant #17) carries the indicator's definition, so 141.6 per 100
  and 103.2% gross reads as intended rather than as an error.
- Fix G4: chart gridline labels use the same formatter.
- Fix G5: a single-point series labels its real year.
- Fix G6: give `dashChartSvg` a `preserveAspectRatio`-correct viewBox, or size the container
  to the chart's real ratio. Do not distort.

**Acceptance:** the PDF's specimen values render as `$99.6T`, `141.6 per 100 people`,
`3.78 per 1,000 (2022)`; no raw ≥10-digit number appears anywhere in the tab; a guard test
asserts every catalog unit has a formatter branch (so a new unit cannot silently fall through).

### A4 — the aggregate view

Ruling 32: a **curated shortlist** by default, with "show all 48".

Shortlist: World · the four income groups · the seven WB regions · EU · Euro area · OECD ·
Arab World. The full set behind one control. Aggregates are visually distinct from countries
and labelled as aggregates wherever they appear.

### A5 — two-country side-by-side

Ruling 4: two countries, all 37 indicators, side by side, with the per-indicator year and the
honest gap where one side has no value. Reuse the existing indicator grid; do not invent a
second layout.

### ⚠ A6 — the bloc membership registry

Ruling 45. `configs/country_blocs.yml`, dated, sourced, registry-tracked.

Each bloc: id, display name ×12, the publisher of its data if any, and members as
`{iso2, joined: YYYY-MM-DD, left: YYYY-MM-DD|null, source_url}`.

**Membership is time-varying and this is load-bearing.** BRICS was five members until 2024,
then admitted Egypt, Ethiopia, Iran and the UAE, and Indonesia in 2025. NATO gained Finland
(2023) and Sweden (2024). The EU lost the UK (2020). A bloc figure computed with today's
roster over a 1995 series is wrong in a way no reader can detect. So:

- Every bloc query resolves membership **as of the figure's year**.
- Every bloc surface — including the side-by-side comparison, which is not "computed" —
  states its membership vintage and member count.
- Membership dates are read off a source, never inferred. A member whose accession date
  cannot be sourced is recorded with `joined: null` and the bloc's series then states that its
  pre-`null` history is unresolvable for that member. Never guess a date to make a series
  continuous.

Blocs to seed (members only; whether we *compute* for them is A7's question):
BRICS · G7 · G20 · NATO · African Union · ASEAN · Mercosur · CARICOM · GCC · OPEC ·
Commonwealth · OIF · EU (already a WB aggregate — seeded for comparison parity).

### ⚠ A7 — the aggregation engine

Rulings 43/44: user-selectable strategies, transparent, refuse-by-default on incomplete
coverage with an explicit publish-anyway override.

**The load-bearing rail: aggregation is indicator-aware.**

Add an explicit **`extensive: true|false`** field to every catalog entry — declared, not
inferred from the unit string, because a string heuristic breaks the day someone adds a unit.

- **Extensive** (population, GDP, GDP-PPP, labour force): a **sum** is meaningful.
- **Intensive** (every `%`, `per N`, `years`, `index`, `births/woman`, `t/capita`): a sum is a
  **fabricated statistic** and must be refused, not offered greyed-out and not computed.

Strategies, all offered side by side so the user compares rather than trusts one:

| Strategy | Applies to | Note |
|---|---|---|
| **Population-weighted mean** (default) | intensive | For a per-capita indicator this equals `Σ numerator / Σ denominator` — the true aggregate, not an approximation. Reconstruct the numerator as `value × population`. |
| Simple (unweighted) mean | intensive | "What does a typical member look like." Legitimate and different; label it as such. |
| GDP-weighted mean | intensive | Economic weight. |
| Median | intensive | Robust to one dominant member. |
| **Sum / total** | extensive only | Refused on intensive indicators. |

Alongside the central figure, always display **the spread** (min, max, n) — a BRICS
GDP-per-capita headline that hides a ten-fold range is technically true and practically
misleading, and the spread costs nothing to compute.

**Coverage:** default **refuse** when any member lacks a value for that year. The refusal
names the missing members. The user may publish anyway; when they do, the warning and the
coverage denominator travel **in the payload**, not only in the UI — a downstream consumer
must not be able to read a partial aggregate as complete.

**The weight series must be real.** Population-weighting needs `SP.POP.TOTL` for the same
members and the same year; a missing weight is a coverage failure like any other, not a
silent fallback to unweighted.

**Skeptic lens: honesty.** Negative-space tests: `sum` on `SP.DYN.LE00.IN` is refused;
a bloc with one missing member refuses by default; the override's payload carries
`coverage: {have: 6, of: 7, missing: ["ZA"]}`; a weighted mean with a missing weight refuses
rather than falling back; a bloc queried for 1995 uses 1995's membership.

### A8 — continents *and* World Bank regions

Ruling 47: both, as two lenses, and **not only averages — cumulative totals too** (which A7's
extensive/intensive rail already makes safe).

Say plainly what each lens is: World Bank regions are the producer's own published
aggregates; continents are ours, computed from `CONTINENT_OF` under A7's strategies. They
differ, and the difference is worth stating on screen: WB "Sub-Saharan Africa" excludes
Egypt, Libya, Tunisia, Algeria and Morocco, which sit in "Middle East & North Africa" — so
the WB lens has no continental Africa figure at all. That is exactly why both lenses exist.

### ⚠ A9 — government data in search (deep)

Rulings 5, 30, 31: **one Article per series** (indicator × country ≈ 9,800), included in
search, keywords, Leads and the Feed.

- Synthetic Article per `(series_id, ref_area)`, carrying the indicator label, the country
  name, the unit, the producer, the full history and the caveat, through `index_article` —
  so "GDP china" matches lexically without a bespoke search path.
- A distinct **`statistics` provenance class**, filterable everywhere, per the standing
  provenance-class convention.
- Re-generated, not appended, when a new vintage lands — an idempotent upsert keyed on
  `(series_id, ref_area)`, never a duplicate per vintage.

**Skeptic lens: corpus pollution.** ~9,800 synthetic Articles enter trending keywords, Leads,
the Feed and every corpus-wide aggregate. Assert: the keyword engine does not now rank
"indicator" or "World Bank" as a top corpus term; the near-dup detector does not cluster
9,800 near-identically-templated documents into a fabricated coordination signal (this is a
real risk — templated text is *exactly* what MinHash clusters); source-concentration figures
disclose the statistics class rather than silently absorbing it.

### A10 — gradual load

Ruling 33: the existing ride-along fills the catalog a few indicators per pass. With
pagination and all years, a full load is ~640k figures across ~666 requests. Keep it on the
ride-along; do not add a "load everything now" button that runs for hours over Tor.

---

## 3. Phase B — law extraction

### ⚠ B1 — the legislation.gov.uk XML adapter

Ruling 34. This is adapter #1 of the law brief's S6, and the attachment is its mandate.
`legislation.gov.uk` publishes structured XML per item; the XML has no navigation, and it
gives real section structure, which the act-level granularity ruling (A3 of 2026-07-24) can
consume without per-article splitting.

Live-verify the endpoint shape during the session; a source that cannot be verified ships
disabled rather than guessed.

### ⚠ B2 — a boilerplate **strip** stage

The gap is architectural: today there is a reject stage and no strip stage. Add one, applied
to sources with no structured feed, before `classify_non_article` sees the text.

**Skeptic lens: negative space, both directions.** A strip that removes real content is worse
than the chrome it removes. Test that a clean article passes through **byte-identical**, and
that the attachment's specimen loses its dropdown and keeps its Act.

### B3 — re-extract the 23 tracked documents

Ruling 35. Re-extraction changes content hashes; confirm the dedup path treats a re-extracted
document as the same document rather than storing a second copy, and that the old polluted
extractions' derived rows (entities, places, dates, keywords) are cleared, not merged with the
new ones.

### B4 — legislative furniture

Ruling 36. Add `PART`, `SCHEDULE`, `CHAPTER`, `SECTION`, `ANNEX`, `APPENDIX`, `ARTICLE` to
the caps-acronym detection stoplist. Collision-free by construction — lowercase "part" and
"article" as content words are untouched.

Sequencing note worth keeping: fix the input (B1/B2/B3) **before** judging the entity
classifier. Four of the five bogus "people" in the attachment come from nav text; tuning a
classifier against that input would calibrate it on an artefact.

### B5 — the Northern Ireland gazetteer bug

Ruling 37. `Ireland (ie)` inside a UK Act is a wrong country, not noise. Reproduce it, fix
the longest-match resolution so "Northern Ireland" is not split, and pin it with a regression
test. Check the same class for "Republic of Ireland", "South Africa" vs "Africa", "Guinea" vs
"Papua New Guinea" / "Equatorial Guinea", "Niger" vs "Nigeria".

### B6 — the XML-ingest reliability diagnostic

Ruling 34's addition. Per structured law source, verify the adapter's extraction is sound:
plausible section count, no navigation markers, a body/chrome ratio in range, the document's
own title matching the catalog. Rides the all-diagnostics bundle as a member (the completeness
ratchet requires it to be a member or a documented exemption).

**Decision taken unless the maintainer objects:** the diagnostic re-parses **stored** copies
offline by default, so it runs under airplane mode. A live re-fetch is an option behind the
one network consent.

---

## 4. Phase C — application UX

### C1 — the crash screen (item 4)

Rulings 17/18/19: an honest crash screen; **no auto-restart**.

- Poll `/api/health` on the existing chrome cadence. Today it is painted once at boot and can
  never go red.
- On N consecutive failed loopback polls, replace the UI with a crash screen: a plain
  statement that the backend stopped responding, a Retry, and a one-click "download the run
  journal" so the crash immediately produces its own diagnostic artifact.
- **Freeze and mark stale** every live surface — the collection activity must stop reading as
  though collection were still running.
- For a loopback-only app a failed fetch to `127.0.0.1` is strong evidence the server is gone;
  there is no network in between. Still require N consecutive failures and exclude 429 and
  slow responses, so a busy server is never reported as a dead one.

### C2 — card colour and provenance (item 1)

Rulings 14/15/16.

- Derive the family hue from a **stable hash of the family name**, not the bucket index. This
  changes today's Home colours; that is the point — an identity colour that moves is worse
  than a new palette.
- `openCardCorpus` carries the whole provenance: card title, family, producer, the trigger
  and its evidence tier, the method and the caveat.
- The analysis window paints the family colour and shows a **persistent header** carrying that
  provenance. Reuse the existing `_trigger`/method/caveat data — this is transport, not new
  measurement.

### C3 — the Articles tab (item 5)

Rulings 20/21/22/23/38/39.

- **Move** the sort controls into the Articles tab (do not duplicate — two homes for one
  control drift apart).
- **Sortable column headers**, which makes tag and top-keyword natural as new columns.
- **Remove** the `source ↗` column and the Summarize/Translate buttons; the reader carries
  both. Absorption-verified above.
- **Precompute** the top keyword: additive nullable `Article.top_keyword_id` +
  `top_keyword_count`, maintained by `index_article`, with migration, boot self-heal and
  deterministic backfill — the `detected_language`/`quarantined` pattern. **Ties store both**
  (ruling 39).
- **Add the new columns to `_merge_articles`' explicit column allowlist in the same commit.**
  The project has already lost fourteen columns through exactly this omission, and the failure
  is invisible: a dropped column with a default arrives populated and plausible.
- Use a random revision id and read the head from `python3 -m alembic heads`, not a regex
  scan.

### C4 — Settings (items 6, 7; ruling 42)

End state: **9 subtabs** — Graphics · General · Cards · AI · Wikipedia · OpenStreetMap ·
Agenda · Data & backup · Advanced.

- Diagnostics leave Data & backup for a new **Diagnostics** section in Advanced. Execute the
  2026-07-20 one-button ruling at last: one all-diagnostics button; per-report download
  buttons go. **Job-starters and interactive tools are actions, not report downloads, and
  stay** (P0 validation, page-size bench, source-quality ZIP, IR-eval and the gold-set
  builder, discover-world).
- Safety becomes a section in Advanced; **Uninstall & wipe becomes its own separate section**
  (ruling 26), not nested inside Safety. Panic wipe must not become hard to reach — this app
  is built for people who may need it in a hurry.
- Per-sweep AI **on/off toggles are kept** (ruling 24); the redundant per-sweep *run* buttons
  go; the coordinator toggle stays the master. Descriptions move to `#oo-tip` hovers.
- Advanced keeps its flat collapsible structure (ruling 27) — no second-level subtab strip.
- **Anchors are load-bearing.** Panel ids are used as source-slicing delimiters by tests that
  are not about them. Grep the test tree for every id you move before moving it.
- **Folded must not mean fetched:** loaders fire on section expand, not subtab select.

### C5 — the Feed tab (item 2)

Rulings 8–13, 40, 41. Name: **Feed**. New sidebar tab.

- Chronological or random; **random uses a seed persisted per session**, so pagination cannot
  repeat or skip. Settings → General gets "reset scrolling history", offering **both** a
  reshuffle and a clear-seen reset (ruling 41).
- A **seen/unseen** marker per article, which is what makes chronological mode useful across
  sessions.
- Default: **everything on**. Provenance selection lives in Settings (ruling 9).
- **Exclude quarantined and not-yet-qualified** articles (ruling 11).
- Post: fixed visible height, "read more" expands **in place** (ruling 12). Truncation is
  display-only and must never truncate what is indexed or searched.
- Metadata per post: source, date, tags, and the article's **own** top three keywords
  (ruling 10) — batched for the visible page, never one query per row, and never through the
  `keyword_mentions → articles` join that the recorded codec trap names.
- **Keyset pagination**, not offset. At ~1M articles an offset scroll is O(offset) and the
  feed degrades the further you go — which is the one thing an infinite feed must not do.

---

## 5. Suggested PR sequence

File scopes are largely disjoint; A and C can run in parallel, B is self-contained.

1. **A1+A2** — pagination + aggregate classification (together; neither ships alone)
2. **A3** — units, formatting, chart fixes
3. **B1+B2+B3** — XML adapter, strip stage, re-extract
4. **C1** — crash screen (small, high user value)
5. **C4** — Settings restructure (touches many anchors; land before other frontend work)
6. **A4+A5** — aggregate view, side-by-side
7. **A6+A7+A8** — membership registry, aggregation engine, both lenses
8. **B4+B5+B6** — furniture, gazetteer, diagnostic
9. **C2** — card colour and provenance
10. **C3** — Articles tab (carries a migration)
11. **A9+A10** — statistics as Articles
12. **C5** — the Feed tab

---

## 6. Deferred — Tier-2 publishers

Ruling 46's order, each needing the full vertical pattern (dated catalog → guarded fetch →
pure parser with a negative-space skeptic → vintaged store → provenance class → surface with
visible caveats → freshness diagnostic → ledger row). Not this session:

1. **OECD** and **IMF** — highest value by a distance; both SDMX, hundreds of indicators.
   `parse_sdmx_json` handles 2.1; OECD is 1.0 and IMF 3.0, so **verify the shape, do not
   assume the existing parser covers them**.
2. **AfDB** — the only route to continental Africa from a publisher rather than a computation.
3. Regional bodies: ASEANstats, GCC-Stat, CARICOM, UNECA, OPEC, NATO defence expenditure,
   the BRICS Joint Statistical Publication.

---

## 7. Operator / internet-connected session to-do

Egress-blocked here; none of this may be guessed.

1. **Verify the 37 World Bank indicator codes live** (ruling 7). They were search-verified,
   not fetched. A wrong code fails silently as "no data".
2. **Confirm the shape of World Bank page 1** for `country/all` — settles why exactly one
   economy survived.
3. **BRICS Joint Statistical Publication** — an annual volume from the members' own
   statistical offices; a PDF/Excel acquisition task, not an API.
4. **AfDB / UNECA** continental Africa endpoints.
5. **OECD and IMF SDMX** endpoint and message-version verification.
6. **Bloc membership sourcing with dates** — every `joined`/`left` read off a source.

---

## 8. Honest limits of this brief

- No browser was driven while writing it; the frontend findings are from source and from the
  maintainer's own PDF export.
- The World Bank API was not reachable, so G1's *consequence* is proven from code and from the
  stored data's shape, while the precise contents of page 1 are not.
- The entity-classifier defects in §1 are described as *observed outputs*. Their mechanism is
  not diagnosed here, deliberately: the input is polluted, and the correct order is to clean
  it and re-measure before touching the classifier.
